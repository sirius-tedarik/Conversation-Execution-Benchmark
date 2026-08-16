"""Command-line runner for CEB scenario packs."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import MockRunner, OpenAICompatibleRunner
from .report import render_html
from .schema import load_scenarios
from .scorecard import aggregate_runs, apply_gate, score_run
from .session import run_scenario


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Conversation Execution Benchmark")
    parser.add_argument("--cases", default="cases")
    parser.add_argument("--manifest", default="benchmark.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="run deterministic self-test outputs")
    mode.add_argument("--base-url", help="OpenAI-compatible server root URL")
    parser.add_argument("--model", default="model-under-test")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "EMPTY"))
    parser.add_argument("--trials", type=int, help="override trial count per case")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--timeout", type=int, default=180, help="per-request timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=3, help="retries per transient transport fault")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="run this many (scenario, trial) tasks in parallel threads against a remote endpoint "
             "(each task opens its own runner/environment, so this is safe); default 1 keeps the "
             "original sequential behaviour",
    )
    parser.add_argument(
        "--advisory-model-latency", action="store_true",
        help="report max_model_latency_ms but don't gate on it — use against a remote endpoint, "
             "where the number is network round-trip plus think-time, not a conversational defect",
    )
    parser.add_argument(
        "--out",
        help="where to write the JSON report; the HTML report is always written alongside it. "
             "Defaults to reports/<model>-<UTC timestamp>.json, so every benchmark run leaves a "
             "report behind without having to remember the flag.",
    )
    parser.add_argument("--no-report", action="store_true", help="score only; write no report files")
    return parser.parse_args()


def _transport_failure(scenario_id: str, seed: int, error: Exception) -> dict[str, Any]:
    """Record an unreachable-model run as a scored failure instead of losing the sweep."""
    detail = f"{type(error).__name__}: {error}"
    return {
        "scenario_id": scenario_id,
        "seed": seed,
        "passed": False,
        "eligible": False,
        "p0_failures": 1,
        "axes": {"runtime": {"score": 0.0, "passed": 0, "total": 1}},
        "checks": [{"axis": "runtime", "name": "model_transport", "passed": False,
                    "severity": "P0", "detail": detail}],
        "objectives": [],
        "milestones": {},
        "transport_error": detail,
    }


def _default_report_path(report: dict[str, Any]) -> Path:
    """reports/<model>-<UTC timestamp>.json — a distinct file per run, so successive benchmarks
    of the same model accumulate instead of overwriting each other. The model name is slugified
    because ids like 'Qwen/Qwen3.5-9B' contain path separators."""
    model = re.sub(r"[^A-Za-z0-9._-]+", "-", str(report.get("model", "model"))).strip("-") or "model"
    stamp = str(report.get("created_at", ""))[:19].replace(":", "").replace("-", "").replace("T", "-")
    return Path("reports") / f"{model}-{stamp}.json"


def _with_transcript(scored: dict[str, Any], trajectory: dict[str, Any]) -> dict[str, Any]:
    """Attach the conversation to the scored run so the report can show *why* a check failed,
    not just that it did. Scoring itself stays transcript-free — this is a reporting concern,
    so it is attached here rather than inside score_run."""
    scored["transcript"] = [
        {key: step[key] for key in ("index", "role", "content", "name", "arguments", "result") if key in step}
        for step in trajectory.get("timeline", [])
    ]
    scored["visited_nodes"] = [visit.get("node") for visit in trajectory.get("simulator_trace", [])]
    if trajectory.get("execution_error"):
        scored["execution_error"] = trajectory["execution_error"]
    return scored


def _trial_count(args: argparse.Namespace, scenario_trials: int, manifest: dict[str, Any]) -> int:
    if args.trials is not None:
        return args.trials
    return scenario_trials or int(manifest.get("default_trials", 3))


def _run_one(
    args: argparse.Namespace, scenario: Any, trial: int, advisory_metrics: frozenset[str]
) -> dict[str, Any]:
    seed = args.seed + trial
    if args.mock:
        if not scenario.mock_runs:
            raise ValueError(f"{scenario.id}: --mock requires _mock_runs")
        outputs = scenario.mock_runs[min(trial, len(scenario.mock_runs) - 1)]
        runner = MockRunner(outputs, list(scenario.mock_latencies) or None)
        trajectory = run_scenario(runner, scenario, seed)
        return _with_transcript(score_run(trajectory, scenario, advisory_metrics), trajectory)
    runner = OpenAICompatibleRunner(
        args.base_url, args.model, args.api_key,
        timeout=args.timeout, max_retries=args.max_retries,
    )
    try:
        trajectory = run_scenario(runner, scenario, seed)
        return _with_transcript(score_run(trajectory, scenario, advisory_metrics), trajectory)
    except Exception as error:  # transport, not model behaviour: keep the sweep alive
        print(f"  ! {scenario.id} seed={seed}: {type(error).__name__}: {error}")
        return _transport_failure(scenario.id, seed, error)


def run(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = load_scenarios(args.cases)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    advisory_metrics = frozenset({"max_model_latency_ms"}) if args.advisory_model_latency else frozenset()
    tasks = [
        (scenario, trial)
        for scenario in scenarios
        for trial in range(_trial_count(args, scenario.trials, manifest))
    ]
    if args.concurrency > 1:
        # Each task builds its own runner/environment/simulator and deep-copies scenario state
        # before mutating it, so concurrent (scenario, trial) tasks share no mutable state — see
        # StatefulEnvironment.__init__ and ControlledUserSimulator.__init__.
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(_run_one, args, scenario, trial, advisory_metrics) for scenario, trial in tasks]
            scored = [future.result() for future in futures]
    else:
        scored = [_run_one(args, scenario, trial, advisory_metrics) for scenario, trial in tasks]
    summary = aggregate_runs(scored)
    report = {
        "benchmark": manifest.get("name", "Conversation Execution Benchmark"),
        "version": manifest.get("version", "0.8"),
        "model": "mock-reference" if args.mock else args.model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "gate": apply_gate(summary, manifest),
        "results": scored,
    }
    if not getattr(args, "no_report", False):
        target = Path(args.out) if args.out else _default_report_path(report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        target.with_suffix(".html").write_text(render_html(report), encoding="utf-8")
        report["report_path"] = str(target.with_suffix(".html"))
    return report


def main() -> int:
    report = run(_arguments())
    summary = report["summary"]
    print(f"CEB {report['version']} — {report['model']}")
    print(f"scenarios={summary['scenarios']} runs={summary['runs']} eligible={summary['eligible']}")
    print(f"Pass@1={summary['pass_at_1']:.2%} Pass@k={summary['pass_at_k']:.2%} Pass^k={summary['pass_pow_k']:.2%}")
    for axis, values in summary["axes"].items():
        # An axis whose every check was advisory (e.g. runtime under --advisory-model-latency)
        # scores None, not 0 — nothing was actually gated, so there is no percentage to print.
        score = values["score"]
        rendered = f"{score:.1f}%" if score is not None else "n/a (advisory only)"
        print(f"  {axis}: {rendered} ({values['passed']}/{values['total']})")
    cascaded = summary["p0_failures"] - summary["p0_failures_root_cause"]
    print(f"p0_failures={summary['p0_failures']} (root_cause={summary['p0_failures_root_cause']}, cascaded={cascaded})")
    if summary["wording_only_suspect_runs"]:
        print(f"wording_only_suspect_runs={summary['wording_only_suspect_runs']} — review these checks' regex before trusting the fail")
    print(f"release_gate={'PASS' if report['gate']['passed'] else 'FAIL'}")
    for item in report["gate"]["checks"]:
        if not item["passed"] and item.get("reason"):
            print(f"  gate {item['name']}: {item['reason']}")
    if report.get("report_path"):
        print(f"report={report['report_path']}")
    return 0 if report["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
