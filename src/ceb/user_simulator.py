"""Finite-state, seedable user controller for reproducible multi-turn calls."""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from .patterns import resolve_pattern
from .stt import transcribe


def _customer_gave_up(rule: dict[str, Any], full_timeline: list[dict[str, Any]] | None) -> bool:
    """A real caller does not wait politely forever. In the production transcripts this suite is
    built from, the single most common way a call died early was the agent emitting the SAME
    sentence again instead of moving the conversation on — the caller hung up. Scripted plans
    cannot express that: the simulator would keep feeding turns to an agent that is visibly stuck.
    `abandon_when.repeated_assistant_turns: N` ends the call once the last N assistant turns are
    near-identical, so a stuck agent is scored as the lost call it really is instead of being
    carried to a clean finish by an infinitely patient script."""
    limit = int(rule.get("repeated_assistant_turns", 0))
    if limit < 2 or full_timeline is None:
        return False
    spoken = [
        str(step.get("content", "")).strip()
        for step in full_timeline
        if step.get("role") == "assistant" and str(step.get("content", "")).strip()
    ]
    if len(spoken) < limit:
        return False
    threshold = float(rule.get("similarity", 0.92))
    recent = spoken[-limit:]
    return all(
        SequenceMatcher(None, recent[index], recent[index + 1]).ratio() > threshold
        for index in range(len(recent) - 1)
    )


def _stable_index(seed: int, scenario_id: str, node_id: str, visit: int, size: int) -> int:
    digest = hashlib.sha256(f"{seed}:{scenario_id}:{node_id}:{visit}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % size


def _tool_entries(steps: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [step for step in steps if step.get("role") == "tool" and step.get("name") == name]


def _tool_window(
    tool_name: str, steps: list[dict[str, Any]],
    full_timeline: list[dict[str, Any]] | None, read_only_tools: frozenset[str],
) -> list[dict[str, Any]]:
    """The steps to search for a `tool_called`/`tool_succeeded`/`tool_failed` condition on
    `tool_name`. Normally just the current turn (`steps`) — unchanged, strict behaviour for
    every scenario that doesn't opt in. Only for a tool the scenario has explicitly declared
    `read_only_tools` (see docs/CASE_SCHEMA.md) do we search the FULL session timeline instead:
    a read-only query the model already fired — even a turn early, bundled into an earlier
    node's own response — causes no real-world harm and the model has no reason to call it
    again just because the simulator's script catches up to it, so it shouldn't be able to
    permanently strand the conversation the way a genuinely early MUTATING call should.
    This intentionally does not distinguish early from late: an early call is not hidden by
    this leniency, only its power to collapse everything downstream is. A dedicated oracle
    check (oracles.py::_premature_tool_call_checks) uses each node visit's recorded
    `active_since_index` (see ControlledUserSimulator) to flag the early call as its own
    defect regardless of whether the conversation went on to complete normally."""
    if tool_name in read_only_tools and full_timeline is not None:
        return full_timeline
    return steps


def _matches(
    condition: dict[str, Any], steps: list[dict[str, Any]],
    full_timeline: list[dict[str, Any]] | None = None, read_only_tools: frozenset[str] = frozenset(),
) -> bool:
    if not condition:
        return True
    assistant_text = "\n".join(str(step.get("content", "")) for step in steps if step.get("role") == "assistant")
    if condition.get("tool_called"):
        window = _tool_window(str(condition["tool_called"]), steps, full_timeline, read_only_tools)
        if not _tool_entries(window, str(condition["tool_called"])):
            return False
    if condition.get("tool_succeeded"):
        name = str(condition["tool_succeeded"])
        window = _tool_window(name, steps, full_timeline, read_only_tools)
        entries = _tool_entries(window, name)
        if not entries or not any(item.get("result", {}).get("ok", True) and not item.get("result", {}).get("error") for item in entries):
            return False
    if condition.get("tool_failed"):
        name = str(condition["tool_failed"])
        window = _tool_window(name, steps, full_timeline, read_only_tools)
        entries = _tool_entries(window, name)
        if not entries or not any(not item.get("result", {}).get("ok", True) or item.get("result", {}).get("error") for item in entries):
            return False
    if condition.get("assistant_regex") and not re.search(
        resolve_pattern(str(condition["assistant_regex"])), assistant_text, re.I | re.S
    ):
        return False
    if condition.get("no_tool_called") and any(step.get("role") == "tool" for step in steps):
        return False
    return True


class ControlledUserSimulator:
    """The model may vary language, but it never controls user facts or decisions."""

    def __init__(self, scenario_id: str, plan: dict[str, Any], seed: int,
                 read_only_tools: frozenset[str] = frozenset(), stt: Any = None):
        self.scenario_id = scenario_id
        self.nodes = {node["id"]: node for node in plan["nodes"]}
        self.current_id: str | None = plan["start"]
        self.seed = seed
        self.read_only_tools = read_only_tools
        # Simulated speech-to-text noise on the caller's side; None leaves every
        # utterance exactly as the case wrote it (see stt.py).
        self.stt = stt
        self.visits: dict[str, int] = {}
        self.trace: list[dict[str, Any]] = []
        self.max_detours = int(plan.get("max_detours", len(self.nodes)))
        self.detour_count = 0
        self.budget_exhausted = False
        self.abandon_when = plan.get("abandon_when", {})
        self.abandoned = False
        # A real caller does not wait silently through a long pause — after a few seconds of dead
        # air they say "alo?". The simulator was infinitely patient, so nothing ever tested how the
        # agent recovers from its own silence. When the turn just spoken took longer than
        # `after_ms`, the caller interjects instead of the plan advancing; the node stays put, so
        # the conversation resumes where it was once the agent responds.
        self.impatience = plan.get("impatience", {})
        self.impatience_prompts = 0
        self._pending_impatience = False
        # Timeline index at which the current node became active — the boundary a read-only
        # tool call must be at or after to count for this node's own transition (see
        # _tool_window). Updated in advance(), consumed by emit()'s trace entry so the
        # premature-tool-call oracle check can tell "this node's own tool, called before the
        # customer ever reached it" apart from "called a beat late, within this node's window".
        self.active_since_index = 0

    @property
    def current_node(self) -> dict[str, Any] | None:
        return self.nodes.get(self.current_id) if self.current_id is not None else None

    @property
    def is_off_flow(self) -> bool:
        return bool(self.current_node and self.current_node.get("off_flow"))

    def emit(self) -> str | None:
        if self.current_id is None:
            return None
        if self._pending_impatience:
            self._pending_impatience = False
            self.impatience_prompts += 1
            utterances = self.impatience.get("utterances") or ["Alo? Orada mısınız?"]
            index = _stable_index(
                self.seed, self.scenario_id, "impatience", self.impatience_prompts, len(utterances)
            )
            utterance = utterances[index]
            utterance, stt_applied = transcribe(
                utterance, self.stt, self.seed, self.scenario_id, "impatience", self.impatience_prompts
            )
            self.trace.append(
                {
                    "node": self.current_id,
                    "visit": self.visits.get(self.current_id, 0),
                    "utterance": utterance,
                    "stt_applied": stt_applied,
                    "off_flow": False,
                    "resume_to": None,
                    "active_since_index": self.active_since_index,
                    "impatience": True,
                }
            )
            return utterance
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
        spoken = utterance
        # A node may pin its own transcription noise. Absent means inherit the sweep-wide
        # setting; an explicit null means keep this turn clean even under --stt, which is what
        # lets a case corrupt exactly the turn its trap needs and leave the turn that
        # ESTABLISHES the constraint intact.
        node_stt = node.get("stt", self.stt) if "stt" in node else self.stt
        utterance, stt_applied = transcribe(
            utterance, node_stt, self.seed, self.scenario_id, self.current_id, visit
        )
        self.trace.append(
            {
                "node": self.current_id,
                "visit": visit,
                "utterance": utterance,
                "spoken": spoken,
                "stt_applied": stt_applied,
                "off_flow": bool(node.get("off_flow")),
                "resume_to": node.get("resume_to"),
                "active_since_index": self.active_since_index,
            }
        )
        return utterance

    def _silence_was_noticed(self, turn_steps: list[dict[str, Any]]) -> bool:
        """True when the turn just spoken left the caller waiting long enough to speak up."""
        if not self.impatience:
            return False
        if self.impatience_prompts >= int(self.impatience.get("max_prompts", 1)):
            return False
        threshold = float(self.impatience["after_ms"])
        return any(
            float(step.get("model_latency_ms") or 0) > threshold
            for step in turn_steps
            if step.get("role") == "assistant"
        )

    def advance(self, turn_steps: list[dict[str, Any]], full_timeline: list[dict[str, Any]] | None = None) -> str | None:
        if self.current_id is None:
            return None
        node = self.nodes[self.current_id]
        if node.get("terminal"):
            self.current_id = None
            return None
        if self.abandon_when and _customer_gave_up(self.abandon_when, full_timeline):
            self.abandoned = True
            self.current_id = None
            return None
        if self._silence_was_noticed(turn_steps):
            # hold the node: the caller is interrupting, not moving the conversation on
            self._pending_impatience = True
            return self.current_id
        target = None
        for transition in node.get("transitions", []):
            if _matches(transition.get("when", {}), turn_steps, full_timeline, self.read_only_tools):
                target = transition.get("to")
                break
        if target is None:
            target = node.get("resume_to") if node.get("off_flow") else node.get("fallback_to")
        self.current_id = target
        if full_timeline is not None:
            self.active_since_index = len(full_timeline)
        return target
