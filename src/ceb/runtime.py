"""Runtime/audio event metrics for cascade and full-duplex tracks."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _by_turn(events: list[dict[str, Any]], event_type: str) -> dict[int, list[float]]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for event in events:
        if event.get("type") == event_type and isinstance(event.get("ts_ms"), (int, float)):
            grouped[int(event.get("turn", 0))].append(float(event["ts_ms"]))
    return grouped


def compute_runtime_metrics(trajectory: dict[str, Any]) -> dict[str, Any]:
    timeline = trajectory.get("timeline", [])
    model_latencies = [float(step["model_latency_ms"]) for step in timeline if step.get("role") == "assistant"]
    tool_latencies = [float(step["logical_latency_ms"]) for step in timeline if step.get("role") == "tool"]
    unbridged = []
    for index, step in enumerate(timeline):
        if step.get("role") != "tool":
            continue
        previous = timeline[index - 1] if index else {}
        bridge = previous.get("content", "") if previous.get("role") == "assistant" else ""
        if not str(bridge).strip():
            unbridged.append(float(step.get("logical_latency_ms", 0)))

    events = trajectory.get("audio_events") or []
    user_end, agent_start = _by_turn(events, "user_speech_end"), _by_turn(events, "agent_speech_start")
    turn_latencies = []
    for turn, ends in user_end.items():
        for end in ends:
            candidates = [start for start in agent_start.get(turn, []) if start >= end]
            if candidates:
                turn_latencies.append(min(candidates) - end)

    barge_in_stop = []
    for barge in (event for event in events if event.get("type") == "user_barge_in"):
        ts, turn = float(barge["ts_ms"]), int(barge.get("turn", 0))
        candidates = [
            float(stop["ts_ms"])
            for stop in events
            if stop.get("type") == "agent_speech_stop"
            and int(stop.get("turn", 0)) == turn
            and float(stop.get("ts_ms", -1)) >= ts
        ]
        if candidates:
            barge_in_stop.append(min(candidates) - ts)

    dead_air = []
    for start_event in (event for event in events if event.get("type") == "tool_call_start"):
        start, call_id = float(start_event["ts_ms"]), start_event.get("call_id")
        ends = [
            float(event["ts_ms"])
            for event in events
            if event.get("type") == "tool_call_end"
            and event.get("call_id") == call_id
            and float(event.get("ts_ms", -1)) >= start
        ]
        if not ends:
            continue
        end = min(ends)
        spoke = any(
            event.get("type") == "agent_speech_start" and start <= float(event.get("ts_ms", -1)) <= end
            for event in events
        )
        dead_air.append(0.0 if spoke else end - start)

    return {
        "max_model_latency_ms": max(model_latencies) if model_latencies else None,
        "max_logical_tool_latency_ms": max(tool_latencies) if tool_latencies else None,
        "max_unbridged_tool_wait_ms": max(unbridged) if unbridged else 0.0,
        "max_turn_latency_ms": max(turn_latencies) if turn_latencies else None,
        "max_barge_in_stop_ms": max(barge_in_stop) if barge_in_stop else None,
        "max_tool_dead_air_ms": max(dead_air) if dead_air else None,
        "audio_event_count": len(events),
    }


def runtime_checks(trajectory: dict[str, Any], requirements: dict[str, Any]) -> list[dict[str, Any]]:
    metrics, checks = compute_runtime_metrics(trajectory), []
    for metric, threshold in requirements.items():
        if not metric.startswith("max_"):
            continue
        value = metrics.get(metric)
        checks.append(
            {
                "axis": "runtime",
                "name": metric,
                "passed": None if value is None else value <= float(threshold),
                "severity": "P1",
                "detail": f"not observed; threshold={threshold}" if value is None else f"{value:.1f}ms <= {float(threshold):.1f}ms",
                "value": value,
                "threshold": float(threshold),
            }
        )
    return checks
