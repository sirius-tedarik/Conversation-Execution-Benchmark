"""Deterministic end-call metrics and policy checks."""
from __future__ import annotations

from typing import Any


def _end_call_steps(trajectory: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [
        step for step in trajectory.get("timeline", [])
        if step.get("role") == "tool" and step.get("name") == tool
    ]


def compute_termination_metrics(
    trajectory: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    policy = config or {}
    tool = str(policy.get("tool", "end_call"))
    calls = _end_call_steps(trajectory, tool)
    return {
        "tool": tool,
        "end_call_count": len(calls),
        "reasons": [call.get("arguments", {}).get("reason") for call in calls],
        "call_indices": [call.get("index") for call in calls],
        "terminal_tool": trajectory.get("terminal_tool"),
        "ended_by_end_call": trajectory.get("terminal_tool") == tool,
    }


def _check(name: str, passed: bool, detail: str, severity: str) -> dict[str, Any]:
    return {
        "axis": "flow_control",
        "name": name,
        "passed": passed,
        "severity": severity,
        "detail": detail,
    }


def termination_checks(
    trajectory: dict[str, Any],
    config: dict[str, Any],
    found: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not config:
        return []
    metrics = compute_termination_metrics(trajectory, config)
    tool = metrics["tool"]
    calls = _end_call_steps(trajectory, tool)
    mode = str(config.get("mode", "optional"))
    severity = str(config.get("severity", "P0"))
    checks: list[dict[str, Any]] = []

    if mode == "forbidden":
        checks.append(
            _check(
                "premature_end_call_absent",
                not calls,
                "no premature end-call" if not calls else f"{tool} called at indices={metrics['call_indices']}",
                severity,
            )
        )
    elif mode == "required":
        checks.append(
            _check(
                "required_end_call_present",
                bool(calls),
                f"{tool} observed" if calls else f"required {tool} missing",
                severity,
            )
        )

    max_calls = int(config.get("max_calls", 1))
    checks.append(
        _check(
            "bounded_end_call_count",
            len(calls) <= max_calls,
            f"{tool} calls={len(calls)}, limit={max_calls}",
            severity,
        )
    )

    allowed_reasons = set(config.get("allowed_reasons", []))
    if allowed_reasons and calls:
        invalid = [
            call.get("arguments", {}).get("reason")
            for call in calls
            if call.get("arguments", {}).get("reason") not in allowed_reasons
        ]
        checks.append(
            _check(
                "valid_end_call_reason",
                not invalid,
                "all end-call reasons allowed" if not invalid else f"invalid reasons={invalid}",
                severity,
            )
        )

    required = list(config.get("required_milestones", []))
    for position, call in enumerate(calls):
        missing = [
            milestone for milestone in required
            if milestone not in found or found[milestone]["index"] >= int(call["index"])
        ]
        checks.append(
            _check(
                f"end_call_prerequisites:{position}",
                not missing,
                "end-call prerequisites satisfied" if not missing else f"missing before {tool}: {missing}",
                severity,
            )
        )
    return checks
