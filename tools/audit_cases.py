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
from ceb.patterns import resolve_pattern
from ceb.schema import load_scenarios
from ceb.session import run_scenario


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
