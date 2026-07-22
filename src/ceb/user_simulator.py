"""Finite-state, seedable user controller for reproducible multi-turn calls."""
from __future__ import annotations

import hashlib
import re
from typing import Any


def _stable_index(seed: int, scenario_id: str, node_id: str, visit: int, size: int) -> int:
    digest = hashlib.sha256(f"{seed}:{scenario_id}:{node_id}:{visit}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _tool_entries(steps: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [step for step in steps if step.get("role") == "tool" and step.get("name") == name]


def _matches(condition: dict[str, Any], steps: list[dict[str, Any]]) -> bool:
    if not condition:
        return True
    assistant_text = "\n".join(str(step.get("content", "")) for step in steps if step.get("role") == "assistant")
    if condition.get("tool_called") and not _tool_entries(steps, str(condition["tool_called"])):
        return False
    if condition.get("tool_succeeded"):
        entries = _tool_entries(steps, str(condition["tool_succeeded"]))
        if not entries or not any(item.get("result", {}).get("ok", True) and not item.get("result", {}).get("error") for item in entries):
            return False
    if condition.get("tool_failed"):
        entries = _tool_entries(steps, str(condition["tool_failed"]))
        if not entries or not any(not item.get("result", {}).get("ok", True) or item.get("result", {}).get("error") for item in entries):
            return False
    if condition.get("assistant_regex") and not re.search(
        str(condition["assistant_regex"]), assistant_text, re.I | re.S
    ):
        return False
    if condition.get("no_tool_called") and any(step.get("role") == "tool" for step in steps):
        return False
    return True


class ControlledUserSimulator:
    """The model may vary language, but it never controls user facts or decisions."""

    def __init__(self, scenario_id: str, plan: dict[str, Any], seed: int):
        self.scenario_id = scenario_id
        self.nodes = {node["id"]: node for node in plan["nodes"]}
        self.current_id: str | None = plan["start"]
        self.seed = seed
        self.visits: dict[str, int] = {}
        self.trace: list[dict[str, Any]] = []
        self.max_detours = int(plan.get("max_detours", len(self.nodes)))
        self.detour_count = 0
        self.budget_exhausted = False

    @property
    def current_node(self) -> dict[str, Any] | None:
        return self.nodes.get(self.current_id) if self.current_id is not None else None

    @property
    def is_off_flow(self) -> bool:
        return bool(self.current_node and self.current_node.get("off_flow"))

    def emit(self) -> str | None:
        if self.current_id is None:
            return None
        node = self.nodes[self.current_id]
        if node.get("off_flow"):
            if self.detour_count >= self.max_detours:
                # A plan cycle re-entered off-flow beyond the bound: end the
                # conversation as a scored run failure instead of crashing the harness.
                self.budget_exhausted = True
                self.current_id = None
                return None
            self.detour_count += 1
        visit = self.visits.get(self.current_id, 0)
        self.visits[self.current_id] = visit + 1
        variants = node["variants"]
        utterance = variants[_stable_index(self.seed, self.scenario_id, self.current_id, visit, len(variants))]
        self.trace.append(
            {
                "node": self.current_id,
                "visit": visit,
                "utterance": utterance,
                "off_flow": bool(node.get("off_flow")),
                "resume_to": node.get("resume_to"),
            }
        )
        return utterance

    def advance(self, turn_steps: list[dict[str, Any]]) -> str | None:
        if self.current_id is None:
            return None
        node = self.nodes[self.current_id]
        if node.get("terminal"):
            self.current_id = None
            return None
        target = None
        for transition in node.get("transitions", []):
            if _matches(transition.get("when", {}), turn_steps):
                target = transition.get("to")
                break
        if target is None:
            target = node.get("resume_to") if node.get("off_flow") else node.get("fallback_to")
        self.current_id = target
        return target
