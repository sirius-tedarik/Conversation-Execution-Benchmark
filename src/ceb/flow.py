"""Long-horizon flow metrics and deterministic off-flow checks."""
from __future__ import annotations

import re
from typing import Any


def _is_rejoined(trace: list[dict[str, Any]], index: int) -> bool:
    """A detour rejoins when the conversation returns to its declared resume target.

    Nested detours are allowed in between: the scan skips deeper off-flow nodes and
    fails only when the conversation lands on a different main-flow node first.
    """
    tail = trace[index + 1:]
    if not tail:
        return False
    expected = trace[index].get("resume_to")
    if expected is None:
        return not tail[0].get("off_flow")
    for item in tail:
        if item.get("node") == expected:
            return True
        if not item.get("off_flow"):
            return False
    return False


def _max_off_flow_span(trace: list[dict[str, Any]]) -> int:
    spans, current = [0], 0
    for item in trace:
        current = current + 1 if item.get("off_flow") else 0
        spans.append(current)
    return max(spans)


def compute_flow_metrics(trajectory: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    timeline = trajectory.get("timeline", [])
    trace = trajectory.get("simulator_trace", [])
    detour_positions = [index for index, item in enumerate(trace) if item.get("off_flow")]
    rejoined = sum(_is_rejoined(trace, index) for index in detour_positions)
    assistant_text = "\n".join(
        str(step.get("content", "")) for step in timeline if step.get("role") == "assistant"
    )
    reask_pattern = (config or {}).get("reask_regex", r"tekrar söyler misiniz|yeniden söyler misiniz")
    reasks = len(re.findall(str(reask_pattern), assistant_text, re.I)) if reask_pattern else 0
    return {
        "assistant_steps": sum(step.get("role") == "assistant" for step in timeline),
        "user_turns": sum(step.get("role") == "user" for step in timeline),
        "tool_calls": sum(step.get("role") == "tool" for step in timeline),
        "timeline_events": len(timeline),
        "detours": len(detour_positions),
        "detour_rejoins": rejoined,
        "detour_rejoin_rate": round(rejoined / len(detour_positions), 4) if detour_positions else None,
        "max_off_flow_span": _max_off_flow_span(trace),
        "reasks": reasks,
        "visited_nodes": [item.get("node") for item in trace],
    }


def _check(name: str, passed: bool, detail: str, severity: str = "P1") -> dict[str, Any]:
    return {"axis": "flow_control", "name": name, "passed": passed, "severity": severity, "detail": detail}


def flow_checks(trajectory: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    if not config:
        return []
    metrics = compute_flow_metrics(trajectory, config)
    checks: list[dict[str, Any]] = []
    exact_fields = {
        "target_assistant_steps": "assistant_steps",
        "target_user_turns": "user_turns",
        "expected_detours": "detours",
        "expected_off_flow_span": "max_off_flow_span",
    }
    for requirement, metric in exact_fields.items():
        if requirement not in config:
            continue
        expected, actual = int(config[requirement]), int(metrics[metric])
        checks.append(_check(requirement, actual == expected, f"{metric}={actual}, expected={expected}"))
    # A ceiling, not an exact target: for behavioral cases (as opposed to the long-horizon
    # depth cases, which intentionally require an exact step count) a model that resolves
    # the task in FEWER steps than expected is not a defect — punishing efficiency with an
    # exact-match check is what let a genuinely good recovery ("retried only the failed
    # step, in one turn") register as a flow_control failure.
    ceiling_fields = {"max_assistant_steps": "assistant_steps", "max_user_turns": "user_turns"}
    for requirement, metric in ceiling_fields.items():
        if requirement not in config:
            continue
        limit, actual = int(config[requirement]), int(metrics[metric])
        checks.append(_check(requirement, actual <= limit, f"{metric}={actual}, limit={limit}"))
    if metrics["detours"]:
        checks.append(
            _check(
                "all_detours_rejoined",
                metrics["detour_rejoins"] == metrics["detours"],
                f"rejoined={metrics['detour_rejoins']}/{metrics['detours']}",
                "P0",
            )
        )
    if "max_reasks" in config:
        limit = int(config["max_reasks"])
        checks.append(_check("bounded_reasks", metrics["reasks"] <= limit, f"reasks={metrics['reasks']}, limit={limit}"))
    required_nodes = list(config.get("required_resume_nodes", []))
    if required_nodes:
        missing = [node for node in required_nodes if node not in metrics["visited_nodes"]]
        checks.append(_check("required_resume_nodes", not missing, "all resume nodes visited" if not missing else f"missing={missing}", "P0"))
    return checks
