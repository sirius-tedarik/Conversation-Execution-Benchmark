"""Deterministic, axis-aware CEB oracles."""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from .environment import deep_subset, get_path
from .flow import flow_checks as profile_flow_checks
from .runtime import runtime_checks
from .schema import Scenario
from .termination import termination_checks


def check(axis: str, name: str, passed: bool | None, detail: str, severity: str = "P1", **extra: Any) -> dict[str, Any]:
    return {"axis": axis, "name": name, "passed": passed, "severity": severity, "detail": detail, **extra}


def _matching_steps(trajectory: dict[str, Any], milestone: dict[str, Any]) -> list[dict[str, Any]]:
    kind, timeline = milestone["kind"], trajectory.get("timeline", [])
    if kind == "tool":
        candidates = [s for s in timeline if s.get("role") == "tool" and s.get("name") == milestone.get("tool")]
        if "arguments" in milestone:
            candidates = [s for s in candidates if not deep_subset(milestone["arguments"], s.get("arguments", {}), "args")]
        if "result" in milestone:
            candidates = [s for s in candidates if not deep_subset(milestone["result"], s.get("result", {}), "result")]
        if milestone.get("failed") is True:
            candidates = [s for s in candidates if not s.get("result", {}).get("ok", True) or s.get("result", {}).get("error")]
        if milestone.get("failed") is False:
            candidates = [s for s in candidates if s.get("result", {}).get("ok", True) and not s.get("result", {}).get("error")]
        return candidates
    if kind == "content":
        role, pattern = milestone.get("role", "assistant"), milestone.get("regex", ".*")
        return [s for s in timeline if s.get("role") == role and re.search(str(pattern), str(s.get("content", "")), re.I | re.S)]
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
        matches = [s.get("content", "") for s in assistants if re.search(pattern, s.get("content", ""), re.I)]
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
            wrong = deep_subset(requirement.get("arg_equals", {}), arguments, "args")
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
    for index, pattern in enumerate(config.get("required_assistant_regex", [])):
        present = any(re.search(pattern, s.get("content", ""), re.I) for s in assistants)
        checks.append(check("conversation_experience", f"required_language:{index}", present,
                            f"required pattern {'found' if present else 'missing'}: {pattern}", "P2"))
    return checks


def evaluate(trajectory: dict[str, Any], scenario: Scenario) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    checks.extend(runtime_checks(trajectory, scenario.runtime))
    return checks, found
