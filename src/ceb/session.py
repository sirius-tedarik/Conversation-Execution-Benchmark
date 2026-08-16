"""Controlled user ↔ model ↔ executable tool orchestration."""
from __future__ import annotations

import copy
import json
import time
from typing import Any

from .environment import StatefulEnvironment, ToolExecutionError
from .parser import parse_assistant_output
from .schema import Scenario
from .user_simulator import ControlledUserSimulator


def _append(timeline: list[dict[str, Any]], step: dict[str, Any]) -> dict[str, Any]:
    item = dict(step)
    item["index"] = len(timeline)
    timeline.append(item)
    return item


def run_scenario(runner: Any, scenario: Scenario, seed: int = 0) -> dict[str, Any]:
    read_only_tools = frozenset(scenario.policies.get("read_only_tools", []))
    simulator = ControlledUserSimulator(scenario.id, scenario.user_plan, seed, read_only_tools)
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
        messages.append({"role": "user", "content": utterance})
        _append(
            timeline,
            {
                "role": "user",
                "content": utterance,
                "user_turn": user_turn,
                "simulator_node": simulator.current_id,
                "simulator_off_flow": simulator.is_off_flow,
            },
        )
        turn_steps: list[dict[str, Any]] = []
        for agent_step in range(scenario.max_steps_per_turn):
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
            assistant = _append(
                timeline,
                {
                    "role": "assistant",
                    "content": parsed["content"],
                    "tool_calls": copy.deepcopy(normalized_calls),
                    "parse_ok": parsed["parse_ok"],
                    "raw": parsed["raw"],
                    "user_turn": user_turn,
                    "agent_step": agent_step,
                    "model_latency_ms": latency_ms,
                },
            )
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
                tool_step = _append(
                    timeline,
                    {
                        "role": "tool",
                        "name": call["name"],
                        "arguments": copy.deepcopy(call.get("arguments", {})),
                        "result": copy.deepcopy(result),
                        "logical_latency_ms": logical_latency,
                        "user_turn": user_turn,
                        "agent_step": agent_step,
                    },
                )
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
        "perturbations": copy.deepcopy(scenario.perturbations),
    }
