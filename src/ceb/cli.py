"""Command-line runner for CEB scenario packs."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import MockRunner, OpenAICompatibleRunner
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
    parser.add_argument("--out")
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


def _trial_count(args: argparse.Namespace, scenario_trials: int, manifest: dict[str, Any]) -> int:
    if args.trials is not None:
        return args.trials
    return scenario_trials or int(manifest.get("default_trials", 3))


def run(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = load_scenarios(args.cases)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    scored = []
    for scenario in scenarios:
        trials = _trial_count(args, scenario.trials, manifest)
        for trial in range(trials):
            seed = args.seed + trial
            if args.mock:
                if not scenario.mock_runs:
                    raise ValueError(f"{scenario.id}: --mock requires _mock_runs")
                outputs = scenario.mock_runs[min(trial, len(scenario.mock_runs) - 1)]
                runner = MockRunner(outputs)
                scored.append(score_run(run_scenario(runner, scenario, seed), scenario))
                continue
            runner = OpenAICompatibleRunner(
                args.base_url, args.model, args.api_key,
                timeout=args.timeout, max_retries=args.max_retries,
            )
            try:
                scored.append(score_run(run_scenario(runner, scenario, seed), scenario))
            except Exception as error:  # transport, not model behaviour: keep the sweep alive
                print(f"  ! {scenario.id} seed={seed}: {type(error).__name__}: {error}")
                scored.append(_transport_failure(scenario.id, seed, error))
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
    if args.out:
        target = Path(args.out); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = run(_arguments())
    summary = report["summary"]
    print(f"CEB {report['version']} — {report['model']}")
    print(f"scenarios={summary['scenarios']} runs={summary['runs']} eligible={summary['eligible']}")
    print(f"Pass@1={summary['pass_at_1']:.2%} Pass@k={summary['pass_at_k']:.2%} Pass^k={summary['pass_pow_k']:.2%}")
    for axis, values in summary["axes"].items():
        print(f"  {axis}: {values['score']:.1f}% ({values['passed']}/{values['total']})")
    print(f"release_gate={'PASS' if report['gate']['passed'] else 'FAIL'}")
    return 0 if report["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
