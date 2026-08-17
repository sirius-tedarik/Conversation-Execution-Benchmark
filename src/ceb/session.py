"""Controlled user ↔ model ↔ executable tool orchestration."""
from __future__ import annotations

import copy
import json
import time
from typing import Any

from .environment import StatefulEnvironment, ToolExecutionError
from .parser import parse_assistant_output
from .schema import Scenario
from .stt import summarise as stt_summary
from .user_simulator import ControlledUserSimulator


def _append(timeline: list[dict[str, Any]], step: dict[str, Any]) -> dict[str, Any]:
    item = dict(step)
    item["index"] = len(timeline)
    timeline.append(item)
    return item


def _agent_turn(
    runner: Any,
    scenario: Scenario,
    seed: int,
    messages: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    environment: StatefulEnvironment,
    user_turn: int,
    max_steps: int,
    interim: bool = False,
) -> dict[str, Any]:
    """One model-facing turn: up to `max_steps` generate calls, executing any tools they ask for.

    Split out of run_scenario so a fragmented caller utterance can run it once per fragment.
    `interim=True` marks the steps as answers to a caller who has not finished speaking. The
    machinery is otherwise identical on purpose: in production an interim tool call really does
    execute, and that execution is the harm the oracle measures.
    """
    turn_steps: list[dict[str, Any]] = []
    terminal_tool: str | None = None
    execution_error: str | None = None
    for agent_step in range(max_steps):
        started = time.perf_counter()
        raw = runner.generate(messages, tools=list(scenario.tool_schemas) or None, seed=seed)
        # a fixture may DECLARE its latency so silence-dependent behaviour stays reproducible
        # instead of depending on how fast the machine running the mock happens to be
        declared = getattr(runner, "declared_latency_ms", None)
        latency_ms = float(declared) if declared is not None else round((time.perf_counter() - started) * 1000, 3)
        parsed = parse_assistant_output(raw)
        normalized_calls = []
        for call_position, call in enumerate(parsed["tool_calls"]):
            normalized = copy.deepcopy(call)
            normalized["id"] = normalized.get("id") or f"call_{len(timeline)}_{call_position}"
            normalized_calls.append(normalized)
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": parsed["content"],
            # What the caller HEARD. Equal to `content` unless a later node's barge_in trims it.
            "heard": parsed["content"],
            "tool_calls": copy.deepcopy(normalized_calls),
            "parse_ok": parsed["parse_ok"],
            "raw": parsed["raw"],
            "user_turn": user_turn,
            "agent_step": agent_step,
            "model_latency_ms": latency_ms,
        }
        if interim:
            entry["interim"] = True
        assistant = _append(timeline, entry)
        turn_steps.append(assistant)
        assistant_message: dict[str, Any] = {"role": "assistant", "content": parsed["content"]}
        if normalized_calls:
            assistant_message["tool_calls"] = copy.deepcopy(normalized_calls)
        messages.append(assistant_message)
        if not parsed["parse_ok"] or not normalized_calls:
            break
        terminal_hit = False
        for call in normalized_calls:
            try:
                outcome = environment.call(call["name"], call.get("arguments", {}))
                result, logical_latency, is_terminal = outcome.result, outcome.latency_ms, outcome.terminal
            except ToolExecutionError as exc:
                execution_error = str(exc)
                result = {"ok": False, "error": "undeclared_tool_contract", "detail": str(exc)}
                logical_latency, is_terminal = 0.0, False
            tool_entry: dict[str, Any] = {
                "role": "tool",
                "name": call["name"],
                "arguments": copy.deepcopy(call.get("arguments", {})),
                "result": copy.deepcopy(result),
                "logical_latency_ms": logical_latency,
                "user_turn": user_turn,
                "agent_step": agent_step,
            }
            if interim:
                tool_entry["interim"] = True
            tool_step = _append(timeline, tool_entry)
            turn_steps.append(tool_step)
            messages.append(
                {
                    "role": "tool",
                    "name": call["name"],
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
            if is_terminal:
                # The call ended here; later calls in the same message never execute.
                terminal_tool, terminal_hit = call["name"], True
                break
        if terminal_hit:
            break
    else:
        execution_error = execution_error or "max_steps_per_turn exceeded"
    return {"turn_steps": turn_steps, "terminal_tool": terminal_tool, "execution_error": execution_error}


def run_scenario(runner: Any, scenario: Scenario, seed: int = 0, stt: Any = None) -> dict[str, Any]:
    read_only_tools = frozenset(scenario.policies.get("read_only_tools", []))
    # `stt` is a profile name or operator->rate mapping; None keeps every caller
    # utterance exactly as written. A scenario may pin its own under perturbations.stt,
    # which wins over the sweep-wide setting so a case built around a specific
    # mis-transcription still behaves the same in an otherwise clean run.
    stt_profile = (scenario.perturbations or {}).get("stt", stt)
    simulator = ControlledUserSimulator(scenario.id, scenario.user_plan, seed, read_only_tools, stt_profile)
    environment = StatefulEnvironment(scenario.initial_state, scenario.tool_contracts)
    messages: list[dict[str, Any]] = []
    if scenario.system:
        messages.append({"role": "system", "content": scenario.system})
    timeline: list[dict[str, Any]] = []
    terminal_tool, execution_error, max_turns_hit = None, None, False

    for user_turn in range(scenario.max_user_turns):
        utterance = simulator.emit()
        if utterance is None:
            break
        # What the caller actually said, before simulated transcription. The model only ever
        # sees `content`; `spoken` exists so a user-role milestone can assert a fact the SCRIPT
        # established rather than a word the recogniser happened to preserve.
        spoken = (simulator.trace[-1].get("spoken") if simulator.trace else None) or utterance
        # Full-duplex: this caller turn cut the agent off. Trim what the caller HEARD of the last
        # thing the agent said, and leave `content` and the model's own history intact — nothing
        # in production tells the model where it was cut, and that gap is the case.
        barge_in = (simulator.current_node or {}).get("barge_in")
        if barge_in:
            for step in reversed(timeline):
                if step.get("role") == "assistant":
                    step["heard"] = " ".join(
                        str(step.get("content", "")).split()[: int(barge_in["after_words"])]
                    )
                    break

        # Speech-to-text delivers one utterance as several consecutive user messages and the
        # model is invoked on every one of them, so a caller can be answered mid-sentence.
        fragments = simulator.pending_fragments or [utterance]
        turn_steps: list[dict[str, Any]] = []
        for fragment_index, fragment in enumerate(fragments):
            is_final = fragment_index == len(fragments) - 1
            messages.append({"role": "user", "content": fragment})
            _append(
                timeline,
                {
                    "role": "user",
                    "content": fragment,
                    # `spoken` carries the WHOLE utterance on every fragment: a user-role
                    # milestone asserts what the caller established, which no single fragment
                    # holds on its own.
                    "spoken": spoken,
                    "user_turn": user_turn,
                    "fragment_index": fragment_index,
                    "is_final_fragment": is_final,
                    # Who is holding the handset for this turn. Disclosure scoped to the account
                    # holder has to stop when it changes, without restarting the call.
                    "speaker": (simulator.current_node or {}).get("speaker", "holder"),
                    "simulator_node": simulator.current_id,
                    "simulator_off_flow": simulator.is_off_flow,
                },
            )
            outcome = _agent_turn(
                runner, scenario, seed, messages, timeline, environment, user_turn,
                scenario.max_steps_per_turn if is_final else 1,
                interim=not is_final,
            )
            turn_steps.extend(outcome["turn_steps"])
            terminal_tool = outcome["terminal_tool"] or terminal_tool
            # A non-final fragment runs with max_steps=1 and would otherwise always report
            # "max_steps_per_turn exceeded"; only the real turn can exhaust its budget.
            if is_final:
                execution_error = execution_error or outcome["execution_error"]
            if terminal_tool:
                break
        if terminal_tool or simulator.advance(turn_steps, timeline) is None:
            break
    else:
        max_turns_hit = True

    if simulator.budget_exhausted:
        execution_error = execution_error or "off_flow_detour_budget_exhausted"

    return {
        "scenario_id": scenario.id,
        "benchmark_version": scenario.benchmark_version,
        "seed": seed,
        "timeline": timeline,
        "messages": messages,
        "tool_ledger": copy.deepcopy(environment.ledger),
        "initial_state": copy.deepcopy(scenario.initial_state),
        "final_state": copy.deepcopy(environment.state),
        "terminal_tool": terminal_tool,
        "final_content": next((step.get("content", "") for step in reversed(timeline) if step.get("role") == "assistant"), ""),
        "simulator_trace": copy.deepcopy(simulator.trace),
        "detour_count": simulator.detour_count,
        "max_turns_hit": max_turns_hit,
        "customer_abandoned": simulator.abandoned,
        "impatience_prompts": simulator.impatience_prompts,
        "execution_error": execution_error,
        "audio_events": copy.deepcopy(list(scenario.mock_audio_events)),
        "stt": stt_summary(simulator.trace),
        "perturbations": copy.deepcopy(scenario.perturbations),
    }
