"""Conversation Execution Benchmark (CEB)."""

from .schema import Scenario, ScenarioValidationError, load_scenarios
from .scorecard import aggregate_runs, apply_gate, score_run
from .session import run_scenario

__version__ = "0.8.0"
__all__ = [
    "Scenario",
    "ScenarioValidationError",
    "aggregate_runs",
    "apply_gate",
    "load_scenarios",
    "run_scenario",
    "score_run",
]
