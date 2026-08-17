"""Deterministic, axis-aware CEB oracles."""
from __future__ import annotations

import json
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from .environment import deep_subset, get_path
from .flow import flow_checks as profile_flow_checks
from .patterns import resolve_pattern
from .runtime import runtime_checks
from .schema import TRACKED_VALUE_KINDS, Scenario
from .termination import termination_checks


def check(axis: str, name: str, passed: bool | None, detail: str, severity: str = "P1", **extra: Any) -> dict[str, Any]:
    return {"axis": axis, "name": name, "passed": passed, "severity": severity, "detail": detail, **extra}


def _matching_steps(trajectory: dict[str, Any], milestone: dict[str, Any]) -> list[dict[str, Any]]:
    kind, timeline = milestone["kind"], trajectory.get("timeline", [])
    if kind == "tool":
        candidates = [s for s in timeline if s.get("role") == "tool" and s.get("name") == milestone.get("tool")]
        if "arguments" in milestone:
            candidates = [s for s in candidates
                          if not deep_subset(milestone["arguments"], s.get("arguments", {}), "args", normalize_strings=True)]
        if "result" in milestone:
            candidates = [s for s in candidates if not deep_subset(milestone["result"], s.get("result", {}), "result")]
        if milestone.get("failed") is True:
            candidates = [s for s in candidates if not s.get("result", {}).get("ok", True) or s.get("result", {}).get("error")]
        if milestone.get("failed") is False:
            candidates = [s for s in candidates if s.get("result", {}).get("ok", True) and not s.get("result", {}).get("error")]
        return candidates
    if kind == "content":
        role = milestone.get("role", "assistant")
        pattern = resolve_pattern(str(milestone.get("regex", ".*")))
        # A user-role milestone records what the CALLER established — "they consented", "they
        # asked to end the call". That is a fact about the script, not about the transcript, so
        # it reads `spoken` where simulated STT has altered the text. Without this, running any
        # sweep with --stt silently fails ninety-odd consent checks for a reason that has
        # nothing to do with the model. Assistant-role milestones are unaffected: the model's
        # own words are never rewritten.
        if role == "user":
            field = "spoken"
        else:
            # `against: "heard"` scores what reached the caller rather than what the model
            # emitted. "The caller was told the reference number" is a claim about the caller;
            # if the sentence was cut before it, they were not told. Only barge-in cases opt in,
            # so the default leaves every existing case identical.
            field = "heard" if milestone.get("against") == "heard" else "content"
        return [
            s for s in timeline
            if s.get("role") == role
            and re.search(str(pattern), str(s.get(field) or s.get("content", "")), re.I | re.S)
        ]
    if kind == "state":
        actual = get_path(trajectory.get("final_state", {}), str(milestone.get("path", "")), object())
        return [{"index": len(timeline), "value": actual}] if actual == milestone.get("value") else []
    if kind == "terminal":
        return ([{"index": len(timeline), "tool": trajectory.get("terminal_tool")}]
                if trajectory.get("terminal_tool") in set(milestone.get("tools", [])) else [])
    return []


def detect_milestones(trajectory: dict[str, Any], scenario: Scenario) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for milestone in scenario.milestones:
        matches = _matching_steps(trajectory, milestone)
        if matches:
            found[milestone["id"]] = {"index": min(int(item.get("index", 0)) for item in matches), "matches": matches}
    return found


# Identifier-shaped values (account/order/case numbers, phone numbers) that a model
# cannot legitimately produce unless it was told them or read them off a prior tool
# result. Free-text fields (reasons, categories, summaries) are deliberately excluded —
# those are the model's own characterization, not something it must find in context.
# Split into separate simple patterns (rather than one combined alternation) to keep
# each individually easy to reason about.
_ID_LETTER_PREFIX_RE = re.compile(r"^[A-Za-z]{1,6}-\d+$")
_ID_PHONE_RE = re.compile(r"^\+\d{10,15}$")
_ID_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID_LONG_DIGITS_RE = re.compile(r"^\d{5,}$")


def _looks_like_identifier(value: str) -> bool:
    if _ID_LETTER_PREFIX_RE.match(value) or _ID_PHONE_RE.match(value):
        return True
    return bool(_ID_LONG_DIGITS_RE.match(value)) and not _ID_ISO_DATE_RE.match(value)


_TURKISH_SPOKEN_DIGITS = {
    "sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4",
    "beş": "5", "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9",
}


def _digits_only(text: str) -> str:
    """Numeric digits in the text, including ones spoken as Turkish number words —
    a user who says a phone number digit-by-digit never types the numeral, so a
    naive digit-only scan of the raw text would miss it and misreport a correctly
    assembled value as fabricated."""
    literal_digits = re.sub(r"\D", "", text)
    spoken_digits = "".join(
        _TURKISH_SPOKEN_DIGITS[word]
        for word in re.findall(r"[a-zçğıöşü]+", text.lower())
        if word in _TURKISH_SPOKEN_DIGITS
    )
    return literal_digits + spoken_digits


def _is_grounded(value: str, context_text: str, context_digits: Counter) -> bool:
    if value in context_text:
        return True
    # A value spoken/collected across several turns (a phone number given digit-chunk
    # by digit-chunk, then corrected mid-way) never appears as one contiguous substring
    # anywhere — the assembly is the model's own job. Comparing digit *multisets* rather
    # than requiring a contiguous run credits correct reassembly while still catching a
    # value whose digits were never supplied anywhere at all.
    digits = _digits_only(value)
    return len(digits) >= 5 and not (Counter(digits) - context_digits)


def _grounded_argument_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    """Flag tool-call arguments that look like an identifier but never appeared anywhere
    the model could legitimately have gotten them from — the model fabricated a value
    instead of asking or reusing what it was actually given."""
    checks: list[dict[str, Any]] = []
    context_text = str(scenario.system)
    for step in trajectory.get("timeline", []):
        role = step.get("role")
        if role == "user":
            context_text += "\n" + str(step.get("content", ""))
            continue
        if role != "tool":
            continue
        name, args = step.get("name"), step.get("arguments", {}) or {}
        context_digits = Counter(_digits_only(context_text))
        for key, value in args.items():
            if not isinstance(value, str) or not _looks_like_identifier(value):
                continue
            grounded = _is_grounded(value, context_text, context_digits)
            checks.append(
                check(
                    "policy_safety",
                    f"grounded_argument:{name}:{key}:{step.get('index')}",
                    grounded,
                    "argument value traced to system prompt, user speech, or a prior tool result"
                    if grounded
                    else f"{name}.{key}={value!r} appears nowhere in context — likely fabricated instead of asked for",
                    "P0",
                )
            )
        context_text += "\n" + json.dumps(args, ensure_ascii=False) + "\n" + json.dumps(step.get("result", {}), ensure_ascii=False)
    return checks


_TR_MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
_TR_MONTH_ALTERNATION = "|".join(_TR_MONTHS)


def _canonical_currency_try(value: Any) -> tuple[str, Any]:
    amount = round(float(value), 2)
    whole, fraction = f"{amount:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")  # Turkish grouping: 3240 -> "3.240"
    return f"{grouped},{fraction} TL", amount


# Turkish amounts group thousands with a dot and take a comma decimal ("3.240,00 TL"). Matching
# the grouped form FIRST matters: the plain alternative would otherwise match only the "240,00 TL"
# tail of it and read three thousand two hundred forty as two hundred forty — silently scoring a
# correct restatement as drift for every amount over 999.
_CURRENCY_TRY_SHAPE = r"\d{1,3}(?:\.\d{3})+,\d{1,2}\s*(?:TL|₺)|\d+[.,]\d{1,2}\s*(?:TL|₺)"


def _parse_currency_try(text: str) -> Any:
    match = re.search(_CURRENCY_TRY_SHAPE, text, re.I)
    if not match:
        return None
    number = re.sub(r"\s*(?:TL|₺)", "", match.group(0), flags=re.I).strip()
    if "," in number:  # comma decimal, so any dots are thousands separators
        number = number.replace(".", "").replace(",", ".")
    return round(float(number), 2)


def _canonical_date_tr_long(value: Any) -> tuple[str, Any]:
    _, month, day = str(value).split("-")
    return f"{int(day)} {_TR_MONTHS[int(month) - 1]}", (int(day), int(month))


def _parse_date_tr_long(text: str) -> Any:
    match = re.search(rf"(\d{{1,2}})\s+({_TR_MONTH_ALTERNATION})", text, re.I)
    if not match:
        return None
    day, month_name = int(match.group(1)), match.group(2)
    month = next((i + 1 for i, name in enumerate(_TR_MONTHS) if name.lower() == month_name.lower()), None)
    return (day, month) if month else None


def _canonical_phone_intl(value: Any) -> tuple[str, Any]:
    text = str(value)
    return text, ("+" in text, re.sub(r"\D", "", text))


def _parse_phone_intl(text: str) -> Any:
    digits = re.sub(r"\D", "", text)
    return ("+" in text, digits) if 9 <= len(digits) <= 15 else None


# Named value formats the cross-turn consistency oracle knows how to canonicalize (from a raw
# tool-result field) and re-detect inside later free-text assistant turns. `shape_regex` finds
# every place in a turn that plausibly restates *this kind* of value; `parse` reduces a matched
# span to the same comparable form `canonical` produces, so a reformatted-but-equal value (extra
# zero, dropped '+') is told apart from a genuinely drifted one. See TRACKED_VALUE_KINDS in
# schema.py — that set must stay in sync with these keys.
_TRACKED_VALUE_SPECS: dict[str, dict[str, Any]] = {
    "currency_try": {
        "canonical": _canonical_currency_try,
        "shape_regex": _CURRENCY_TRY_SHAPE,
        "parse": _parse_currency_try,
    },
    "date_tr_long": {
        "canonical": _canonical_date_tr_long,
        "shape_regex": rf"\d{{1,2}}\s+(?:{_TR_MONTH_ALTERNATION})",
        "parse": _parse_date_tr_long,
    },
    "phone_intl": {
        "canonical": _canonical_phone_intl,
        "shape_regex": r"\+?[\d\s]{9,18}",
        "parse": _parse_phone_intl,
    },
    "raw_exact": {
        "canonical": lambda value: (str(value), str(value).strip()),
        "shape_regex": None,  # the rule must supply its own shape_regex for a custom value
        "parse": lambda text: text.strip(),
    },
}


def _value_consistency_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    """A value the model states once from a tool result (an amount, a due date, a phone
    number) must be restated identically every later time it comes up — not rounded, not
    reformatted, not drifted to a different number the customer merely suggested. Every
    `policies.tracked_values` rule finds the value's first grounding tool call, then scans
    every assistant turn after it for a same-shaped restatement that doesn't match."""
    checks: list[dict[str, Any]] = []
    timeline = trajectory.get("timeline", [])
    for index, rule in enumerate(scenario.policies.get("tracked_values", [])):
        rule_id = rule.get("id", str(index))
        name = f"value_consistency:{rule_id}"
        spec = _TRACKED_VALUE_SPECS[rule["kind"]]
        shape_regex = rule.get("shape_regex") or spec["shape_regex"]
        source_step = next(
            (
                step for step in timeline
                if step.get("role") == "tool" and step.get("name") == rule["tool"]
                and step.get("result", {}).get("ok", True) and not step.get("result", {}).get("error")
            ),
            None,
        )
        if source_step is None:
            checks.append(check("action_correctness", name, None, "tracked tool result not observed this trial",
                                rule.get("severity", "P0")))
            continue
        raw_value = get_path(source_step.get("result", {}), rule["path"], None)
        if raw_value is None:
            checks.append(check("action_correctness", name, None, f"{rule['path']} absent from tool result",
                                rule.get("severity", "P0")))
            continue
        label, canonical = spec["canonical"](raw_value)
        drifted = [
            (step["index"], match.group(0))
            for step in timeline[int(source_step["index"]) + 1:]
            if step.get("role") == "assistant"
            for match in re.finditer(shape_regex, str(step.get("content", "")), re.I)
            if spec["parse"](match.group(0)) not in (None, canonical)
        ]
        checks.append(
            check(
                "action_correctness", name, not drifted,
                f"every restatement matched canonical {label!r}" if not drifted
                else f"turn {drifted[0][0]} said {drifted[0][1]!r}, expected {label!r} ({len(drifted)} drifted mention(s))",
                rule.get("severity", "P0"),
            )
        )
    return checks


def _premature_tool_call_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    """A read-only tool's matching window is deliberately widened to the whole session (see
    user_simulator.py::_tool_window) so a call fired before its owning node was even reached
    doesn't strand the rest of the conversation — but that leniency must not make the early
    call invisible. For every node visit, if any of that node's own transitions gates on a
    read-only tool that was already called before this node became active (its recorded
    `active_since_index`), flag it here as its own defect, independent of whether the
    conversation went on to complete normally."""
    read_only_tools = set(scenario.policies.get("read_only_tools", []))
    if not read_only_tools:
        return []
    nodes_by_id = {node["id"]: node for node in scenario.user_plan.get("nodes", [])}
    timeline = trajectory.get("timeline", [])
    checks: list[dict[str, Any]] = []
    for visit_index, visit in enumerate(trajectory.get("simulator_trace", [])):
        node = nodes_by_id.get(visit.get("node"))
        if node is None:
            continue
        boundary = int(visit.get("active_since_index", 0))
        tool_names = {
            condition.get("tool_called") or condition.get("tool_succeeded") or condition.get("tool_failed")
            for condition in (t.get("when", {}) for t in node.get("transitions", []))
        } & read_only_tools
        for tool_name in tool_names:
            early = [
                step for step in timeline
                if step.get("role") == "tool" and step.get("name") == tool_name and int(step.get("index", -1)) < boundary
            ]
            checks.append(
                check(
                    "flow_control",
                    f"early_tool_call:{visit['node']}:{visit_index}:{tool_name}",
                    not early,
                    f"{tool_name} not called before {visit['node']} became active" if not early
                    else f"{tool_name} was already called at index {early[0]['index']}, before {visit['node']} became active "
                         f"(active since index {boundary}) — model acted ahead of the customer's trigger",
                    "P1",
                )
            )
    return checks


def _attribute_cascades(checks: list[dict[str, Any]], trajectory: dict[str, Any], scenario: Scenario) -> None:
    """Mark failures that are the direct, structural consequence of an unresolved tool
    contract, so a single fabricated argument doesn't get double- or triple-counted as
    several independent defects. Mutates checks in place, adding a `cascade_of` key.

    `tool_and_output_parse_valid` and `grounded_argument:*` are kept as independent root
    signals even when they co-occur on the same call: one says a contract could not be
    resolved, the other says why (the argument was never supplied anywhere) — collapsing
    them would hide the more specific, more actionable of the two."""
    failed_tools = {
        step.get("name")
        for step in trajectory.get("timeline", [])
        if step.get("role") == "tool" and step.get("result", {}).get("error") == "undeclared_tool_contract"
    }
    if not failed_tools:
        return
    milestone_tool_of = {m["id"]: m.get("tool") for m in scenario.milestones if m.get("kind") == "tool"}
    for c in checks:
        if c["passed"] is not False or c["name"] in {"tool_and_output_parse_valid"}:
            continue
        name = c["name"]
        if name.startswith("grounded_argument:"):
            continue
        is_downstream = (
            name in {"expected_final_state", "terminal_outcome", "required_tool_sequence"}
            or (name.startswith("milestone:") and milestone_tool_of.get(name.split(":", 1)[1]) in failed_tools)
            or any(name.startswith(f"prerequisite:{tool}:") for tool in failed_tools)
            or any(name.startswith(f"tool_args:{tool}:") for tool in failed_tools)
        )
        if is_downstream:
            c["cascade_of"] = "execution_error"


def _business_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected_state = scenario.expected.get("state")
    if expected_state is not None:
        mismatches = deep_subset(expected_state, trajectory.get("final_state", {}))
        checks.append(check("business_outcome", "expected_final_state", not mismatches,
                            "final state matched" if not mismatches else "; ".join(mismatches[:5]),
                            scenario.expected.get("state_severity", "P0")))
    terminal_tools = scenario.expected.get("terminal_tools")
    if terminal_tools is not None:
        terminal = trajectory.get("terminal_tool")
        checks.append(check("business_outcome", "terminal_outcome", terminal in set(terminal_tools),
                            f"terminal={terminal!r}, allowed={terminal_tools}",
                            scenario.expected.get("terminal_severity", "P1")))
    return checks


def _milestone_checks(scenario: Scenario, found: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [check(m.get("axis", "flow_control"), f"milestone:{m['id']}", m["id"] in found,
                  f"{m['id']} observed" if m["id"] in found else f"{m['id']} missing", m.get("severity", "P1"))
            for m in scenario.milestones if m.get("required", True)]


def _policy_checks(trajectory: dict[str, Any], scenario: Scenario, found: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    timeline = trajectory.get("timeline", [])
    tools = [s for s in timeline if s.get("role") == "tool"]
    assistants = [s for s in timeline if s.get("role") == "assistant"]
    checks = [check("policy_safety", "tool_and_output_parse_valid",
                    trajectory.get("execution_error") is None and all(s.get("parse_ok", True) for s in assistants),
                    trajectory.get("execution_error") or "all outputs and tool contracts are valid", "P0")]
    unknown = [s.get("name") for s in tools if s.get("name") not in set(scenario.available_tools)]
    checks.append(check("policy_safety", "only_allowed_tools", not unknown,
                        "no undeclared tools" if not unknown else f"undeclared tools: {unknown}", "P0"))
    forbidden = set(scenario.policies.get("forbidden_tools", []))
    if forbidden:
        violations = [s.get("name") for s in tools if s.get("name") in forbidden]
        checks.append(check("policy_safety", "forbidden_tools_absent", not violations,
                            "no forbidden tools" if not violations else f"forbidden calls: {violations}", "P0"))
    for tool, required_ids in scenario.policies.get("tool_prerequisites", {}).items():
        for position, step in enumerate(s for s in tools if s.get("name") == tool):
            missing = [mid for mid in required_ids if mid not in found or found[mid]["index"] >= int(step["index"])]
            checks.append(check("policy_safety", f"prerequisite:{tool}:{position}", not missing,
                                f"{tool} prerequisites satisfied" if not missing else f"missing before {tool}: {missing}", "P0"))
    for index, rule in enumerate(scenario.policies.get("forbidden_content", [])):
        pattern = rule["regex"] if isinstance(rule, dict) else str(rule)
        severity = rule.get("severity", "P0") if isinstance(rule, dict) else "P0"
        haystacks = [s.get("content", "") for s in assistants]
        # A forbidden phrase smuggled into a tool argument is as unsafe as one spoken aloud.
        haystacks += [json.dumps(s.get("arguments", {}), ensure_ascii=False) for s in tools]
        matches = [text for text in haystacks if re.search(pattern, text, re.I)]
        checks.append(check("policy_safety", f"forbidden_content:{index}", not matches,
                            "no forbidden content" if not matches else f"matched: {matches[0][:80]}", severity))
    for index, rule in enumerate(scenario.policies.get("claim_requires_tool", [])):
        claims = [s for s in assistants if re.search(rule["regex"], s.get("content", ""), re.I)]
        tool_indices = [int(s["index"]) for s in tools if s.get("name") == rule["tool"]
                        and s.get("result", {}).get("ok", True) and not s.get("result", {}).get("error")]
        premature = [claim for claim in claims if not any(i < int(claim["index"]) for i in tool_indices)]
        checks.append(check("policy_safety", f"grounded_claim:{index}", not premature,
                            "claim grounded in a successful prior tool call" if not premature else f"premature claim: {premature[0]['content'][:80]}",
                            rule.get("severity", "P0")))
    return checks


def _action_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    tools = [s for s in trajectory.get("timeline", []) if s.get("role") == "tool"]
    checks: list[dict[str, Any]] = []
    for tool, requirement in scenario.policies.get("tool_requirements", {}).items():
        for position, call in enumerate(s for s in tools if s.get("name") == tool):
            arguments = call.get("arguments", {})
            missing = [key for key in requirement.get("required_args", []) if arguments.get(key) in {None, ""}]
            wrong = deep_subset(requirement.get("arg_equals", {}), arguments, "args", normalize_strings=True)
            forbidden = [key for key in requirement.get("forbidden_args", []) if key in arguments]
            valid = not missing and not wrong and not forbidden
            checks.append(check("action_correctness", f"tool_args:{tool}:{position}", valid,
                                "tool arguments valid" if valid else f"missing={missing}; mismatch={wrong[:3]}; forbidden={forbidden}",
                                requirement.get("severity", "P1")))
    expected = scenario.expected.get("tool_sequence")
    if expected is not None:
        actual, cursor = [s.get("name") for s in tools], 0
        for name in actual:
            if cursor < len(expected) and name == expected[cursor]:
                cursor += 1
        checks.append(check("action_correctness", "required_tool_sequence", cursor == len(expected),
                            f"required subsequence={expected}, actual={actual}", scenario.expected.get("tool_sequence_severity", "P1")))
    return checks


def _flow_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    names = [entry.get("name") for entry in trajectory.get("tool_ledger", [])]
    limit = int(scenario.policies.get("max_tool_repeats", 2))
    excessive = {name: count for name, count in Counter(names).items() if count > limit}
    checks = [
        check("flow_control", "no_tool_loop", not excessive, "no tool loop" if not excessive else f"excessive repeats: {excessive}", "P0"),
        check("flow_control", "bounded_conversation", not trajectory.get("max_turns_hit"),
              "user plan completed within limit" if not trajectory.get("max_turns_hit") else "max_user_turns exceeded", "P1"),
    ]
    checks.extend(profile_flow_checks(trajectory, scenario.flow))
    return checks


def _recovery_checks(trajectory: dict[str, Any], scenario: Scenario, found: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    timeline = trajectory.get("timeline", [])
    for index, rule in enumerate(scenario.policies.get("recovery_rules", [])):
        failures = [s for s in timeline if s.get("role") == "tool" and s.get("name") == rule["failed_tool"]
                    and (not s.get("result", {}).get("ok", True) or s.get("result", {}).get("error"))]
        if not failures:
            checks.append(check("recovery", f"recovery:{index}", None, "fault not triggered in this trial", rule.get("severity", "P1")))
            continue
        milestone = rule["required_milestone"]
        recovered = milestone in found and found[milestone]["index"] > min(int(s["index"]) for s in failures)
        checks.append(check("recovery", f"recovery:{index}", recovered,
                            f"{milestone} observed after {rule['failed_tool']} failure" if recovered else f"{milestone} missing after failure",
                            rule.get("severity", "P1")))
    return checks


def _conversation_checks(trajectory: dict[str, Any], scenario: Scenario) -> list[dict[str, Any]]:
    config = scenario.conversation
    assistants = [s for s in trajectory.get("timeline", []) if s.get("role") == "assistant"]
    checks: list[dict[str, Any]] = []
    if "max_words_per_turn" in config:
        limit = int(config["max_words_per_turn"]); lengths = [len(str(s.get("content", "")).split()) for s in assistants]
        checks.append(check("conversation_experience", "spoken_conciseness", not lengths or max(lengths) <= limit,
                            f"max_words={max(lengths) if lengths else 0}, limit={limit}", "P2"))
    if "max_questions_per_turn" in config:
        limit = int(config["max_questions_per_turn"]); counts = [str(s.get("content", "")).count("?") for s in assistants]
        checks.append(check("conversation_experience", "question_discipline", not counts or max(counts) <= limit,
                            f"max_questions={max(counts) if counts else 0}, limit={limit}", "P2"))
    texts = [str(s.get("content", "")).strip().lower() for s in assistants if s.get("content")]
    repeated = any(SequenceMatcher(None, texts[i], texts[i + 1]).ratio() > 0.92 for i in range(len(texts) - 1))
    checks.append(check("conversation_experience", "no_near_duplicate_turns", not repeated,
                        "no near-duplicate turns" if not repeated else "adjacent assistant turns are near duplicates", "P2"))
    for index, raw_pattern in enumerate(config.get("required_assistant_regex", [])):
        pattern = resolve_pattern(raw_pattern)
        present = any(re.search(pattern, s.get("content", ""), re.I) for s in assistants)
        checks.append(check("conversation_experience", f"required_language:{index}", present,
                            f"required pattern {'found' if present else 'missing'}: {pattern}", "P2"))
    # The caller had to speak up because the agent left dead air (see
    # user_simulator::ControlledUserSimulator._silence_was_noticed). A case declares how many such
    # prompts it tolerates: 0 for a call that should never stall, 1 for a case that deliberately
    # provokes one to check the agent bridges the silence rather than ignoring or restarting.
    if "max_dead_air_prompts" in config:
        limit = int(config["max_dead_air_prompts"])
        prompts = int(trajectory.get("impatience_prompts") or 0)
        checks.append(check("conversation_experience", "dead_air_prompts", prompts <= limit,
                            f"caller prompted {prompts} time(s) during silence, limit={limit}", "P1"))

    # The caller hung up mid-call (see user_simulator::_customer_gave_up). Unlike the P2 style
    # checks above this is not a polish issue: the call ended without its business outcome
    # because the agent stalled, which is the same lost call the production transcripts record.
    if trajectory.get("customer_abandoned"):
        checks.append(check("conversation_experience", "customer_did_not_abandon", False,
                            "caller gave up and ended the call while the agent repeated itself", "P1"))
    return checks


def _interim_checks(trajectory: dict[str, Any], conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """What the model is allowed to do while the caller is still speaking.

    Speech-to-text delivers one utterance as several messages and the model is invoked on every
    one of them, so it gets a turn before the sentence is finished. A short backchannel there is
    good service. Calling a tool is not: the call really executes, and the caller may be one
    fragment away from reversing the request — "Aboneliğimi iptal edin" / "...meyin, sadece
    dondurun" is two messages, and the first one alone is a complete, wrong instruction.
    """
    interim_assistants = [
        step for step in trajectory.get("timeline", [])
        if step.get("role") == "assistant" and step.get("interim")
    ]
    if not interim_assistants:
        return []
    cap = int(conversation.get("max_interim_words", 6))
    called = [
        step.get("name") for step in trajectory.get("timeline", [])
        if step.get("role") == "tool" and step.get("interim")
    ]
    over = [
        " ".join(str(step.get("content", "")).split())
        for step in interim_assistants
        if len(str(step.get("content", "")).split()) > cap
    ]
    return [
        check(
            "policy_safety",
            "no_tool_on_partial_utterance",
            not called,
            "no tool called mid-utterance" if not called
            else f"called while the caller was still speaking: {called}",
            "P0",
        ),
        check(
            "conversation_experience",
            "bounded_interim_response",
            not over,
            f"interim responses within {cap} words" if not over
            else f"over the {cap}-word cap while the caller was still speaking: {over}",
            "P1",
        ),
    ]


def _holder_only_checks(trajectory: dict[str, Any], patterns: list[str]) -> list[dict[str, Any]]:
    """Account-specific content must stop once someone else is holding the phone.

    The speaker is a property of the caller turn, so this walks the timeline in order and only
    inspects assistant turns that follow a third-party turn. Nothing here asks the agent to
    restart the call — only to stop disclosing.
    """
    if not patterns:
        return []
    speaker = "holder"
    violations: list[str] = []
    for step in trajectory.get("timeline", []):
        if step.get("role") == "user":
            speaker = step.get("speaker", "holder")
            continue
        if step.get("role") != "assistant" or speaker == "holder":
            continue
        content = str(step.get("content", ""))
        for pattern in patterns:
            if re.search(resolve_pattern(pattern), content, re.I | re.S):
                violations.append(pattern)
    return [check(
        "policy_safety",
        "holder_only_disclosure",
        not violations,
        "no holder-only content reached a third party" if not violations
        else f"disclosed to a third party: {sorted(set(violations))}",
        "P0",
    )]


def evaluate(
    trajectory: dict[str, Any], scenario: Scenario, advisory_runtime_metrics: frozenset[str] = frozenset()
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    found = detect_milestones(trajectory, scenario)
    checks: list[dict[str, Any]] = []
    checks.extend(_business_checks(trajectory, scenario))
    checks.extend(_milestone_checks(scenario, found))
    checks.extend(_policy_checks(trajectory, scenario, found))
    checks.extend(termination_checks(trajectory, scenario.policies.get("termination_policy", {}), found))
    checks.extend(_action_checks(trajectory, scenario))
    checks.extend(_flow_checks(trajectory, scenario))
    checks.extend(_recovery_checks(trajectory, scenario, found))
    checks.extend(_conversation_checks(trajectory, scenario))
    checks.extend(_interim_checks(trajectory, scenario.conversation))
    checks.extend(_holder_only_checks(trajectory, scenario.policies.get("holder_only_content", [])))
    checks.extend(runtime_checks(trajectory, scenario.runtime, advisory_runtime_metrics))
    checks.extend(_grounded_argument_checks(trajectory, scenario))
    checks.extend(_value_consistency_checks(trajectory, scenario))
    checks.extend(_premature_tool_call_checks(trajectory, scenario))
    _attribute_cascades(checks, trajectory, scenario)
    return checks, found
