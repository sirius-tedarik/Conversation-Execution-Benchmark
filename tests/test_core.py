import copy

import pytest

from ceb.adapters import MockRunner, OpenAICompatibleRunner
from ceb.environment import StatefulEnvironment
from ceb.parser import parse_assistant_output
from ceb.schema import Scenario, ScenarioValidationError
from ceb.scorecard import score_run
from ceb.session import run_scenario
from ceb.user_simulator import ControlledUserSimulator
from ceb.termination import termination_checks


def test_parser_normalizes_json_and_qwen_formats():
    parsed = parse_assistant_output('hello <tool_call>{"name":"lookup","arguments":{"id":7}}</tool_call>')
    assert parsed["content"] == "hello"
    assert parsed["tool_calls"] == [{"name": "lookup", "arguments": {"id": 7}}]
    qwen = parse_assistant_output("<tool_call><function=lookup><parameter=id>7</parameter></function></tool_call>")
    assert qwen["tool_calls"] == [{"name": "lookup", "arguments": {"id": 7}}]


def test_failed_contract_result_does_not_mutate_state_then_retry_does():
    environment = StatefulEnvironment(
        {"status": "new"},
        ({"name": "save", "sequence": [
            {"result": {"ok": False, "error": "timeout"}, "state_patch": [{"op": "set", "path": "status", "value": "bad"}]},
            {"result": {"ok": True}, "state_patch": [{"op": "set", "path": "status", "value": "saved"}]},
        ]},),
    )
    assert not environment.call("save", {}).result["ok"]
    assert environment.state["status"] == "new"
    assert environment.call("save", {}).result["ok"]
    assert environment.state["status"] == "saved"


def test_user_variants_are_stable_for_same_seed():
    plan = {"start": "n", "nodes": [{"id": "n", "variants": ["a", "b", "c"], "terminal": True}]}
    first = ControlledUserSimulator("case", plan, 19).emit()
    second = ControlledUserSimulator("case", plan, 19).emit()
    assert first == second


def test_off_flow_node_resumes_to_declared_main_flow():
    plan = {
        "start": "detour",
        "max_detours": 1,
        "nodes": [
            {"id": "detour", "variants": ["off topic"], "off_flow": True, "resume_to": "main"},
            {"id": "main", "variants": ["main fact"], "terminal": True},
        ],
    }
    simulator = ControlledUserSimulator("case", plan, 7)
    assert simulator.emit() == "off topic"
    assert simulator.is_off_flow
    assert simulator.advance([]) == "main"
    assert simulator.emit() == "main fact"
    assert simulator.detour_count == 1


def test_schema_rejects_unknown_user_transition():
    raw = {
        "id": "bad", "benchmark_version": "0.8", "available_tools": [], "tool_contracts": [],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "transitions": [{"to": "missing"}]}]},
    }
    with pytest.raises(ScenarioValidationError, match="unknown transition"):
        Scenario.from_dict(copy.deepcopy(raw))


def test_schema_rejects_objective_without_declared_evidence():
    raw = {
        "id": "bad-objective", "benchmark_version": "0.8", "available_tools": [], "tool_contracts": [],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "milestones": [],
        "objectives": [{"id": "goal", "description": "Unmeasured goal", "axis": "policy_safety", "required_milestones": ["missing"]}],
    }
    with pytest.raises(ScenarioValidationError, match="required declared milestones"):
        Scenario.from_dict(raw)


def test_termination_policy_detects_premature_and_wrong_reason_calls():
    trajectory = {"timeline": [{
        "index": 4, "role": "tool", "name": "end_call", "arguments": {"reason": "silence"},
        "result": {"ok": True},
    }], "terminal_tool": "end_call"}
    forbidden = termination_checks(
        trajectory, {"tool": "end_call", "mode": "forbidden", "max_calls": 0, "severity": "P0"}, {}
    )
    assert any(check["name"] == "premature_end_call_absent" and check["passed"] is False for check in forbidden)
    required = termination_checks(trajectory, {
        "tool": "end_call", "mode": "required", "allowed_reasons": ["task_completed"],
        "required_milestones": ["task_done"], "max_calls": 1, "severity": "P0",
    }, {})
    assert any(check["name"] == "valid_end_call_reason" and check["passed"] is False for check in required)
    assert any(check["name"].startswith("end_call_prerequisites") and check["passed"] is False for check in required)


def test_detour_budget_exhaustion_is_scored_not_crashed():
    raw = {
        "id": "detour-cycle", "benchmark_version": "0.8", "available_tools": [], "tool_contracts": [],
        "objectives": [{"id": "o", "description": "d", "axis": "flow_control", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "role": "assistant", "regex": "asla-eslesmez"}],
        "user_plan": {"start": "detour", "max_detours": 1, "nodes": [
            {"id": "detour", "variants": ["araya girdim"], "off_flow": True,
             "transitions": [{"when": {"assistant_regex": "peki"}, "to": "detour"}]}]},
        "max_user_turns": 5, "max_steps_per_turn": 1,
    }
    scenario = Scenario.from_dict(raw)
    trajectory = run_scenario(MockRunner(["peki", "peki", "peki"]), scenario, seed=1)
    assert trajectory["execution_error"] == "off_flow_detour_budget_exhausted"
    assert score_run(trajectory, scenario)["passed"] is False


def test_claim_grounding_rejects_results_that_carry_an_error():
    raw = {
        "id": "ground-error", "benchmark_version": "0.8", "available_tools": ["t1"],
        "tool_contracts": [{"name": "t1", "result": {"error": "timeout"}}],
        "objectives": [{"id": "o", "description": "d", "axis": "policy_safety", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "role": "assistant", "regex": "."}],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "policies": {"claim_requires_tool": [{"regex": "tamamlandı", "tool": "t1", "severity": "P0"}]},
        "max_user_turns": 1, "max_steps_per_turn": 2,
    }
    scenario = Scenario.from_dict(raw)
    outputs = ['<tool_call>{"name":"t1","arguments":{}}</tool_call>', "işlem tamamlandı"]
    result = score_run(run_scenario(MockRunner(outputs), scenario, seed=1), scenario)
    grounded = next(check for check in result["checks"] if check["name"].startswith("grounded_claim"))
    assert grounded["passed"] is False


def test_schema_rejects_sequence_entry_without_result():
    raw = {
        "id": "bad-sequence", "benchmark_version": "0.8", "available_tools": ["t"],
        "tool_contracts": [{"name": "t", "sequence": [{"state_patch": [{"op": "set", "path": "v", "value": 1}]}]}],
        "objectives": [{"id": "o", "description": "d", "axis": "business_outcome", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "regex": "."}],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
    }
    with pytest.raises(ScenarioValidationError, match="sequence entries"):
        Scenario.from_dict(raw)


def test_openai_adapter_translates_provider_neutral_tool_calls():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "lookup", "arguments": {"id": 7}}]},
        {"role": "tool", "name": "lookup", "tool_call_id": "call_1", "content": '{"ok": true}'},
    ]
    wire = OpenAICompatibleRunner._wire_messages(messages)
    assert wire[0]["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"id": 7}'}
    assert wire[1]["tool_call_id"] == "call_1"
