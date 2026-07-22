"""Per-trial scorecards, reliability aggregation, and release gates."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .flow import compute_flow_metrics
from .oracles import evaluate
from .runtime import compute_runtime_metrics
from .schema import Scenario
from .termination import compute_termination_metrics


def score_run(trajectory: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    checks, found = evaluate(trajectory, scenario)
    objectives = []
    for objective in scenario.objectives:
        required = list(objective["required_milestones"])
        missing = [milestone for milestone in required if milestone not in found]
        objectives.append(
            {
                "id": objective["id"],
                "description": objective["description"],
                "axis": objective["axis"],
                "severity": objective.get("severity", "P1"),
                "passed": not missing,
                "required_milestones": required,
                "missing_milestones": missing,
            }
        )
    axes: dict[str, dict[str, Any]] = {}
    for axis in sorted({item["axis"] for item in checks}):
        observed = [item for item in checks if item["axis"] == axis and item["passed"] is not None]
        passed = sum(item["passed"] is True for item in observed)
        axes[axis] = {"score": round(100 * passed / len(observed), 2) if observed else None,
                      "passed": passed, "total": len(observed)}
    failures = [item for item in checks if item["passed"] is False]
    blocking = [item for item in failures if item["severity"] in {"P0", "P1"}]
    p0 = [item for item in failures if item["severity"] == "P0"]
    return {
        "scenario_id": scenario.id,
        "seed": trajectory.get("seed"),
        "passed": not blocking,
        "eligible": not p0,
        "p0_failures": len(p0),
        "axes": axes,
        "checks": checks,
        "objectives": objectives,
        "milestones": {key: {"index": value["index"]} for key, value in found.items()},
        "runtime_metrics": compute_runtime_metrics(trajectory),
        "flow_metrics": compute_flow_metrics(trajectory, scenario.flow),
        "termination_metrics": compute_termination_metrics(
            trajectory, scenario.policies.get("termination_policy", {})
        ),
        "trajectory": trajectory,
    }


def aggregate_runs(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise ValueError("at least one scored run is required")
    axes: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_scenario[result["scenario_id"]].append(result)
        for axis, values in result["axes"].items():
            axes[axis][0] += values["passed"]
            axes[axis][1] += values["total"]
    scenario_reliability = {}
    for scenario_id, trials in sorted(by_scenario.items()):
        passed = sum(item["passed"] for item in trials)
        scenario_reliability[scenario_id] = {
            "trials": len(trials), "passed_trials": passed,
            "pass_at_k": passed > 0, "pass_pow_k": passed == len(trials),
        }
    return {
        "runs": len(results),
        "scenarios": len(by_scenario),
        "eligible": all(item["eligible"] for item in results),
        "p0_failures": sum(item["p0_failures"] for item in results),
        "pass_at_1": round(sum(item["passed"] for item in results) / len(results), 4),
        "pass_at_k": round(sum(item["pass_at_k"] for item in scenario_reliability.values()) / len(by_scenario), 4),
        "pass_pow_k": round(sum(item["pass_pow_k"] for item in scenario_reliability.values()) / len(by_scenario), 4),
        "axes": {axis: {"score": round(100 * passed / total, 2) if total else None,
                         "passed": passed, "total": total}
                 for axis, (passed, total) in sorted(axes.items())},
        "by_scenario": scenario_reliability,
    }


def apply_gate(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    requirements = manifest.get("gate", {})
    checks = [{"name": "p0_failures", "passed": summary["p0_failures"] <= int(requirements.get("p0_failures", 0)),
               "actual": summary["p0_failures"], "required": int(requirements.get("p0_failures", 0))}]
    if "pass_pow_k" in requirements:
        checks.append({"name": "pass_pow_k", "passed": summary["pass_pow_k"] >= float(requirements["pass_pow_k"]),
                       "actual": summary["pass_pow_k"], "required": float(requirements["pass_pow_k"])})
    for axis, threshold in requirements.get("axes", {}).items():
        actual = summary.get("axes", {}).get(axis, {}).get("score")
        checks.append({"name": f"axis:{axis}", "passed": actual is not None and actual >= float(threshold),
                       "actual": actual, "required": float(threshold)})
    return {"passed": all(item["passed"] for item in checks), "checks": checks}
