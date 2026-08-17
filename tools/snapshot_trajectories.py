"""Hash every case's golden mock trajectory, so harness work can prove it changed nothing.

The fragmented-turn work rewrites session.py's turn loop. The only convincing evidence that the
existing cases still behave identically is a before/after hash of what they actually do — a pass
rate can stay green while the shape underneath shifts, because a case can reach the same verdict
by a different route.

Run: PYTHONPATH=src python3 tools/snapshot_trajectories.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ceb.adapters import MockRunner
from ceb.schema import load_scenarios
from ceb.session import run_scenario

ROOT = Path(__file__).resolve().parents[1]


def shape(trajectory: dict) -> str:
    """A digest of the timeline's observable shape: who spoke, what they said, which tool ran
    with which arguments, in order. Deliberately ignores latency and indices, which are not
    behaviour."""
    parts = []
    for step in trajectory["timeline"]:
        parts.append("|".join([
            str(step.get("role")),
            str(step.get("content", "")),
            str(step.get("name", "")),
            json.dumps(step.get("arguments", {}), ensure_ascii=False, sort_keys=True),
        ]))
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def snapshot() -> dict[str, str]:
    shapes: dict[str, str] = {}
    for scenario in load_scenarios(ROOT / "cases"):
        if not scenario.mock_runs:
            continue
        trajectory = run_scenario(MockRunner(list(scenario.mock_runs[0])), scenario, seed=17)
        shapes[scenario.id] = shape(trajectory)
    return shapes


if __name__ == "__main__":
    target = ROOT / "tests" / "fixtures" / "trajectory_shapes.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} with {len(snapshot())} entries")
