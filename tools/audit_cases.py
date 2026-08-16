"""Audit every case for self-inconsistency, using its own reference and negative transcripts.

The recurring authoring bug in this suite is a rule that cannot tell the required behaviour from
the forbidden one — a `forbidden_content` regex that also matches the case's own correct answer,
or a milestone regex the reference transcript never satisfies. `--mock` catches these only when
they happen to flip a whole run; these checks name the exact rule instead.

Run: PYTHONPATH=src python3 tools/audit_cases.py [cases_path]
Exit code 1 if any finding is reported.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from ceb.adapters import MockRunner
from ceb.patterns import CANONICAL_PATTERNS, resolve_pattern
from ceb.schema import load_scenarios
from ceb.session import run_scenario


def _canonical_owner() -> dict[str, str]:
    """Map every plain-literal alternative of a canonical pattern back to its name, so a case
    that hand-writes one can be told it already exists centrally. Only literal alternatives
    count — an alternative carrying regex syntax cannot be compared by string equality."""
    owner: dict[str, str] = {}
    for name, pattern in CANONICAL_PATTERNS.items():
        # top-level split only: a canonical pattern may contain a group of verb stems, and the
        # stems inside it are not themselves phrases a case could be said to have hand-written
        for alternative in _alternatives(pattern):
            literal = alternative.strip()
            if literal and not any(character in literal for character in "[](){}.*+?\\"):
                owner.setdefault(literal, name)
    return owner


def _alternatives(pattern: str) -> list[str]:
    """Split on top-level `|` only, so alternations nested inside a group stay intact."""
    parts, depth, current = [], 0, ""
    for character in pattern:
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        if character == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += character
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


_CANONICAL_OWNER = _canonical_owner()


def _assistant_patterns(scenario) -> list[tuple[str, str]]:
    """Every regex the ASSISTANT must satisfy, labelled by where it lives."""
    found: list[tuple[str, str]] = []
    for node in scenario.user_plan["nodes"]:
        for transition in node.get("transitions", []):
            pattern = transition.get("when", {}).get("assistant_regex")
            if pattern:
                found.append((f"user_plan.{node['id']}.assistant_regex", str(pattern)))
    for milestone in scenario.milestones:
        if milestone.get("kind") == "content" and milestone.get("role", "assistant") == "assistant":
            found.append((f"milestone:{milestone['id']}", str(milestone.get("regex", ""))))
    for index, pattern in enumerate(scenario.conversation.get("required_assistant_regex", [])):
        found.append((f"required_assistant_regex[{index}]", str(pattern)))
    return found


def _assistant_text(scenario, outputs) -> str:
    trajectory = run_scenario(MockRunner(list(outputs)), scenario, seed=17)
    return "\n".join(
        str(step.get("content", ""))
        for step in trajectory.get("timeline", [])
        if step.get("role") == "assistant"
    )


def audit(scenario) -> list[str]:
    findings: list[str] = []
    if not scenario.mock_runs:
        return [f"{scenario.id}: no _mock_runs — the case has no reference behaviour to audit against"]
    reference = _assistant_text(scenario, scenario.mock_runs[0])
    negatives = {entry["label"]: _assistant_text(scenario, entry["outputs"])
                 for entry in scenario.mock_negative_runs}

    # 1. a forbidden rule that matches the case's own correct answer scores compliance as a violation
    for index, rule in enumerate(scenario.policies.get("forbidden_content", [])):
        pattern = rule["regex"] if isinstance(rule, dict) else str(rule)
        hit = re.search(pattern, reference, re.I)
        if hit:
            findings.append(
                f"{scenario.id}: forbidden_content[{index}] matches its OWN reference transcript "
                f"({hit.group(0)[:60]!r}) — the rule punishes the required behaviour"
            )
        # 2. a rule no negative fixture triggers is untested: nothing proves it can fire
        if negatives and not any(re.search(pattern, text, re.I) for text in negatives.values()):
            findings.append(
                f"{scenario.id}: forbidden_content[{index}] fires on no negative fixture "
                f"— rule is unexercised, so nothing proves it works"
            )

    # 3. a milestone the reference never satisfies makes the case unpassable
    for milestone in scenario.milestones:
        if milestone.get("kind") != "content" or milestone.get("role", "assistant") != "assistant":
            continue
        pattern = resolve_pattern(str(milestone.get("regex", ".*")))
        if not re.search(pattern, reference, re.I | re.S):
            findings.append(
                f"{scenario.id}: milestone {milestone['id']!r} never matches the reference transcript "
                f"— the case cannot be passed as written"
            )

    # 4. same for the required conversational language
    for index, raw in enumerate(scenario.conversation.get("required_assistant_regex", [])):
        if not re.search(resolve_pattern(str(raw)), reference, re.I):
            findings.append(
                f"{scenario.id}: required_assistant_regex[{index}] never matches the reference transcript"
            )

    # 5. two currency tracked_values in one case are mutually unsatisfiable: each rule flags every
    #    currency mention that is not its own canonical value, so the other rule's value fails it
    currency = [r["id"] for r in scenario.policies.get("tracked_values", []) if r.get("kind") == "currency_try"]
    if len(currency) > 1:
        findings.append(
            f"{scenario.id}: {len(currency)} currency_try tracked_values ({', '.join(currency)}) — "
            f"each pins EVERY currency mention to its own value, so they cannot both hold"
        )

    # 6. a behavioural phrase hand-written here that a canonical pattern already owns. These drift:
    #    `$consent_question` and friends get widened whenever a live model phrases the behaviour a
    #    new-but-valid way, and a case holding its own private copy never benefits from that. Only
    #    exact literal alternatives are reported, so this cannot fire on a case-specific phrase.
    for where, pattern in _assistant_patterns(scenario):
        if "$" in pattern:  # already delegating to a shared pattern
            continue
        borrowed = {
            alternative: _CANONICAL_OWNER[alternative]
            for alternative in _alternatives(pattern)
            if alternative in _CANONICAL_OWNER
        }
        if borrowed:
            names = sorted(set(borrowed.values()))
            findings.append(
                f"{scenario.id}: {where} hand-writes {sorted(borrowed)} which "
                f"${'/$'.join(names)} already owns — use the shared pattern so widening it once "
                f"reaches every case"
            )

    # A seventh check was tried and removed: "a tracked_values shape that also matches a literal
    # inside the case's own rules". It produced false positives (a milestone that requires the
    # canonical value legitimately contains it) and missed the bug that motivated it, because a
    # literal written as an alternation ("(3|üç) gün") does not match the shape in regex source.
    # Whether the model must utter a non-canonical value only shows in a realistic reference
    # transcript, which is a review question, not a static one.
    return findings


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "cases"
    scenarios = load_scenarios(Path(target))
    findings = [item for scenario in scenarios for item in audit(scenario)]
    for item in findings:
        print(f"  ! {item}")
    print(f"\naudited {len(scenarios)} scenarios — {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
