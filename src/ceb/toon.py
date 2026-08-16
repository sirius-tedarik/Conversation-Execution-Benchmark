"""Generate a TOON-style `AKIŞ` flow block from a case's `user_plan`.

The live model this benchmark tests was fine-tuned on a specific system-prompt shape:
persona/rules text followed by a machine-readable `AKIŞ (TOON)` block —
`entry_after_greeting`, `steps[].id/type/say_to_customer/internal_guidance/next`. Cases
written in that shape measurably changed model behavior in this session (a case that
failed before a TOON rewrite passed immediately after); cases without it left the model
guessing at the scenario's flow and, in several confirmed instances, fabricating an
identifier instead of asking for it.

This module derives a first-draft AKIŞ block mechanically from `user_plan`: node ids,
the `next`/`condition` chain, and the tool list are exact. `say_to_customer` is a best
guess taken from the case-specific (non-generic) part of the node's own transition
regex — the pattern authors already write to say "this is what the assistant must say
here for the plan to advance". It is a starting point for a human to refine, not a
finished prompt: review the generated block before trusting it verbatim, the same way
you'd review any other generated code.
"""
from __future__ import annotations

import re
from typing import Any

from .patterns import CANONICAL_PATTERNS

_GENERIC_ALTS = {alt for pattern in CANONICAL_PATTERNS.values() for alt in pattern.split("|")}
_TOKEN_RE = re.compile(r"\$[a-z_]+")


def _case_specific_alternatives(regex: str) -> list[str]:
    """The part of a transition regex the case author actually wrote for this scenario,
    with the shared `$consent_question`-style generic tail and bare generic alternatives
    stripped back out."""
    without_tokens = _TOKEN_RE.sub("", regex)
    alts = [alt.strip() for alt in without_tokens.split("|")]
    return [alt for alt in alts if alt and alt not in _GENERIC_ALTS]


def _guess_say_to_customer(node: dict[str, Any]) -> str:
    for transition in node.get("transitions", []):
        alts = _case_specific_alternatives(str(transition.get("when", {}).get("assistant_regex", "")))
        if alts:
            return alts[0]
    return ""


def _guess_internal_guidance(node_id: str, tool_contracts: list[dict[str, Any]]) -> str:
    hints = [
        f"{contract['name']}({', '.join(f'{k}={v!r}' for k, v in contract['match_args'].items())}) çağır."
        for contract in tool_contracts
        if contract.get("match_args")
    ]
    return f"[REVIEW] Bu node ile ilişkili olabilecek araç çağrıları: {' '.join(hints[:2])}" if hints else ""


def _step_type(node: dict[str, Any]) -> str:
    if node.get("terminal"):
        return "end"
    return "node"


def generate_toon_flow(scenario: dict[str, Any]) -> str:
    """Return a standalone `AKIŞ:` block text (no surrounding persona/rules) built from
    `scenario['user_plan']` and `scenario['available_tools']`/`tool_contracts`."""
    plan = scenario["user_plan"]
    nodes = {node["id"]: node for node in plan["nodes"]}
    tools = ", ".join(scenario.get("available_tools", []))
    contracts = scenario.get("tool_contracts", [])

    lines = [f"KULLANILABİLİR ARAÇLAR: {tools}", "", "AKIŞ (taslak — gözden geçirin):", "entry_after_greeting:", f"  id: {plan['start']}", "steps:"]
    for node_id, node in nodes.items():
        say = _guess_say_to_customer(node)
        guidance = _guess_internal_guidance(node_id, contracts)
        lines.append(f"  - id: {node_id}")
        lines.append(f"    type: {_step_type(node)}")
        if say:
            lines.append(f'    say_to_customer: "{say}"')
        if guidance:
            lines.append(f'    internal_guidance: "{guidance}"')
        targets = [t.get("to") for t in node.get("transitions", []) if t.get("to")]
        if node.get("resume_to"):
            targets.append(node["resume_to"])
        if targets:
            lines.append("    next:")
            for target in dict.fromkeys(targets):  # de-dupe, keep order
                lines.append(f"      - id: {target}")
                lines.append("        condition: '[REVIEW] koşulu netleştirin'")
    return "\n".join(lines)


def append_toon_flow(scenario: dict[str, Any]) -> str:
    """Return the scenario's existing `system` text with a generated AKIŞ block appended
    — the current rules/constraints text is preserved untouched; the flow is additive."""
    existing = str(scenario.get("system", "")).rstrip()
    flow = generate_toon_flow(scenario)
    return f"{existing}\n\n{flow}" if existing else flow
