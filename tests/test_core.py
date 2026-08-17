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


def _base_scenario(**overrides):
    milestones = overrides.get("milestones", [{"id": "m", "kind": "content", "role": "assistant", "regex": "."}])
    raw = {
        "id": "ground-probe", "benchmark_version": "0.8", "available_tools": ["do_thing"],
        "tool_contracts": [{"name": "do_thing", "result": {"ok": True}}],
        "objectives": [{"id": "o", "description": "d", "axis": "business_outcome",
                        "required_milestones": [m["id"] for m in milestones]}],
        "milestones": milestones,
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "system": "", "max_user_turns": 1, "max_steps_per_turn": 2,
    }
    raw.update(overrides)
    return Scenario.from_dict(raw)


def test_grounded_argument_flags_a_fabricated_identifier():
    scenario = _base_scenario(system="Müşteri hesabınızı doğrulayın.")
    trajectory = {
        "timeline": [
            {"role": "user", "content": "Hesabımı kontrol edin.", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {"account_id": "ACC-99887766"},
             "result": {"ok": True}, "index": 1},
        ],
        "system": scenario.system,
    }
    from ceb.oracles import _grounded_argument_checks
    checks = _grounded_argument_checks(trajectory, scenario)
    assert checks and checks[0]["passed"] is False
    assert "ACC-99887766" in checks[0]["detail"]


def test_grounded_argument_accepts_a_value_given_in_context():
    scenario = _base_scenario(system="[Session] account_id=AC-90 (doğrulanmış hesap)")
    trajectory = {
        "timeline": [
            {"role": "user", "content": "Hesabımı kontrol edin.", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {"account_id": "AC-90"},
             "result": {"ok": True}, "index": 1},
        ],
        "system": scenario.system,
    }
    from ceb.oracles import _grounded_argument_checks
    checks = _grounded_argument_checks(trajectory, scenario)
    assert all(c["passed"] for c in checks)


def test_grounded_argument_accepts_digits_reassembled_across_turns():
    """A phone number collected chunk by chunk (and corrected mid-way) never appears as
    one contiguous string anywhere — the model assembling it correctly is not fabrication."""
    scenario = _base_scenario()
    trajectory = {
        "timeline": [
            {"role": "user", "content": "numaram sıfır beş beş iki", "index": 0},
            {"role": "user", "content": "üç dört iki", "index": 1},
            {"role": "user", "content": "iki iki bir iki", "index": 2},
            {"role": "tool", "name": "do_thing", "arguments": {"msisdn": "05523422212"},
             "result": {"ok": True}, "index": 3},
        ],
        "system": scenario.system,
    }
    from ceb.oracles import _grounded_argument_checks
    checks = _grounded_argument_checks(trajectory, scenario)
    assert all(c["passed"] for c in checks), checks


def test_grounded_argument_ignores_free_text_and_short_values():
    scenario = _base_scenario()
    trajectory = {
        "timeline": [
            {"role": "user", "content": "iptal edin", "index": 0},
            {"role": "tool", "name": "do_thing",
             "arguments": {"reason": "customer_requested_cancellation", "card_last4": "7788"},
             "result": {"ok": True}, "index": 1},
        ],
        "system": scenario.system,
    }
    from ceb.oracles import _grounded_argument_checks
    assert _grounded_argument_checks(trajectory, scenario) == []


def test_value_consistency_passes_when_every_restatement_matches_canonical():
    scenario = _base_scenario(
        policies={"tracked_values": [{"id": "fee", "tool": "do_thing", "path": "amount_try",
                                      "kind": "currency_try", "severity": "P0"}]},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {}, "result": {"ok": True, "amount_try": 89.9}, "index": 1},
            {"role": "assistant", "content": "Ücretiniz 89,90 TL.", "index": 2},
            {"role": "assistant", "content": "Evet, hâlâ 89,90 TL.", "index": 3},
        ],
    }
    from ceb.oracles import _value_consistency_checks
    checks = _value_consistency_checks(trajectory, scenario)
    assert len(checks) == 1 and checks[0]["passed"] is True


def test_value_consistency_flags_a_drifted_currency_restatement():
    scenario = _base_scenario(
        policies={"tracked_values": [{"id": "fee", "tool": "do_thing", "path": "amount_try",
                                      "kind": "currency_try", "severity": "P0"}]},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {}, "result": {"ok": True, "amount_try": 89.9}, "index": 1},
            {"role": "assistant", "content": "Ücretiniz 89,90 TL.", "index": 2},
            {"role": "assistant", "content": "Yaklaşık 90,00 TL demiştim.", "index": 3},
        ],
    }
    from ceb.oracles import _value_consistency_checks
    checks = _value_consistency_checks(trajectory, scenario)
    assert checks[0]["passed"] is False
    assert "90,00" in checks[0]["detail"] and "89,90" in checks[0]["detail"]


def test_value_consistency_flags_a_phone_number_reformatted_without_plus_prefix():
    scenario = _base_scenario(
        policies={"tracked_values": [{"id": "phone", "tool": "do_thing", "path": "phone",
                                      "kind": "phone_intl", "severity": "P0"}]},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {}, "result": {"ok": True, "phone": "+905551112233"}, "index": 1},
            {"role": "assistant", "content": "Numaranız 905551112233 olarak kayıtlı.", "index": 2},
        ],
    }
    from ceb.oracles import _value_consistency_checks
    checks = _value_consistency_checks(trajectory, scenario)
    assert checks[0]["passed"] is False


def test_value_consistency_reports_not_observed_when_tool_never_succeeds():
    scenario = _base_scenario(
        policies={"tracked_values": [{"id": "fee", "tool": "do_thing", "path": "amount_try",
                                      "kind": "currency_try", "severity": "P0"}]},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {}, "result": {"ok": False, "error": "timeout"}, "index": 1},
        ],
    }
    from ceb.oracles import _value_consistency_checks
    checks = _value_consistency_checks(trajectory, scenario)
    assert checks[0]["passed"] is None


def test_schema_rejects_tracked_value_with_unknown_kind():
    raw = {
        "id": "bad-tracked-value", "benchmark_version": "0.8", "available_tools": ["t"],
        "tool_contracts": [{"name": "t", "result": {"ok": True}}],
        "objectives": [{"id": "o", "description": "d", "axis": "business_outcome", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "regex": "."}],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "policies": {"tracked_values": [{"id": "v", "tool": "t", "path": "x", "kind": "not_a_real_kind"}]},
    }
    with pytest.raises(ScenarioValidationError, match="kind must be one of"):
        Scenario.from_dict(raw)


def test_schema_rejects_raw_exact_tracked_value_without_shape_regex():
    raw = {
        "id": "bad-tracked-value-2", "benchmark_version": "0.8", "available_tools": ["t"],
        "tool_contracts": [{"name": "t", "result": {"ok": True}}],
        "objectives": [{"id": "o", "description": "d", "axis": "business_outcome", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "regex": "."}],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "policies": {"tracked_values": [{"id": "v", "tool": "t", "path": "x", "kind": "raw_exact"}]},
    }
    with pytest.raises(ScenarioValidationError, match="shape_regex is required"):
        Scenario.from_dict(raw)


def _premature_call_scenario(read_only: bool) -> Scenario:
    """Node `a` bundles `tool_a` (its own trigger) AND `tool_read` (node `b`'s trigger,
    called a turn early) into the same turn — the exact premature-recitation shape from
    [[project-toon-premature-recitation-finding]]. Node `b`'s own turn never re-calls
    `tool_read`, since the model already did that work."""
    raw = {
        "id": "premature-call-probe", "benchmark_version": "0.8",
        "available_tools": ["tool_a", "tool_read"],
        "tool_contracts": [{"name": "tool_a", "result": {"ok": True}}, {"name": "tool_read", "result": {"ok": True}}],
        "objectives": [{"id": "o", "description": "d", "axis": "flow_control", "required_milestones": ["reached_c"]}],
        "milestones": [{"id": "reached_c", "kind": "content", "role": "assistant", "regex": "at c"}],
        "user_plan": {"start": "a", "nodes": [
            {"id": "a", "variants": ["trigger a"], "transitions": [{"when": {"tool_succeeded": "tool_a"}, "to": "b"}]},
            {"id": "b", "variants": ["trigger b"], "transitions": [{"when": {"tool_succeeded": "tool_read"}, "to": "c"}]},
            {"id": "c", "variants": ["trigger c"], "terminal": True},
        ]},
        "policies": {"read_only_tools": ["tool_read"]} if read_only else {},
        "max_user_turns": 3, "max_steps_per_turn": 3,
    }
    return Scenario.from_dict(raw)


_PREMATURE_CALL_OUTPUTS = [
    '<tool_call>{"name":"tool_a","arguments":{}}</tool_call>',
    '<tool_call>{"name":"tool_read","arguments":{}}</tool_call>',
    "done with a",
    "ack",
    "at c",
]


def test_premature_mutating_tool_call_still_collapses_the_flow_by_default():
    """Without an explicit read_only_tools opt-in, behaviour is byte-identical to before
    this feature existed: node b's own turn never re-calls tool_read, its transition never
    fires, and the conversation ends two turns early — the documented, deliberately-kept
    strict default."""
    scenario = _premature_call_scenario(read_only=False)
    trajectory = run_scenario(MockRunner(list(_PREMATURE_CALL_OUTPUTS)), scenario, seed=1)
    result = score_run(trajectory, scenario)
    assert [s["content"] for s in trajectory["timeline"] if s["role"] == "user"] == ["trigger a", "trigger b"]
    assert result["passed"] is False
    assert next(c for c in result["checks"] if c["name"] == "milestone:reached_c")["passed"] is False


def test_premature_read_only_tool_call_does_not_collapse_the_flow_but_is_still_flagged():
    """With tool_read declared read_only, node b's widened matching window finds the earlier
    call and the conversation completes — but the early call is not laundered away: a
    dedicated early_tool_call check still fails on its own terms, so the run's overall
    `passed` stays False either way."""
    scenario = _premature_call_scenario(read_only=True)
    trajectory = run_scenario(MockRunner(list(_PREMATURE_CALL_OUTPUTS)), scenario, seed=1)
    result = score_run(trajectory, scenario)
    assert [s["content"] for s in trajectory["timeline"] if s["role"] == "user"] == ["trigger a", "trigger b", "trigger c"]
    assert next(c for c in result["checks"] if c["name"] == "milestone:reached_c")["passed"] is True
    early = next(c for c in result["checks"] if c["name"].startswith("early_tool_call:b:"))
    assert early["passed"] is False
    assert result["passed"] is False  # the defect is preserved, not hidden


def test_schema_rejects_read_only_tool_not_in_available_tools():
    raw = {
        "id": "bad-read-only", "benchmark_version": "0.8", "available_tools": ["t"],
        "tool_contracts": [{"name": "t", "result": {"ok": True}}],
        "objectives": [{"id": "o", "description": "d", "axis": "business_outcome", "required_milestones": ["m"]}],
        "milestones": [{"id": "m", "kind": "content", "regex": "."}],
        "user_plan": {"start": "a", "nodes": [{"id": "a", "variants": ["x"], "terminal": True}]},
        "policies": {"read_only_tools": ["not_a_declared_tool"]},
    }
    with pytest.raises(ScenarioValidationError, match="read_only_tools must be declared in available_tools"):
        Scenario.from_dict(raw)


def test_cascade_attribution_collapses_one_contract_failure_to_a_single_root_cause():
    scenario = _base_scenario(
        milestones=[{"id": "m", "kind": "tool", "tool": "do_thing", "failed": False,
                     "axis": "business_outcome", "severity": "P0"}],
        expected={"terminal_tools": ["do_thing"]},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "tool", "name": "do_thing", "arguments": {"id": "FAKE-1"},
             "result": {"ok": False, "error": "undeclared_tool_contract"}, "index": 1, "logical_latency_ms": 100},
        ],
        "final_state": {}, "terminal_tool": None, "execution_error": "no executable contract for tool: do_thing",
        "system": scenario.system,
    }
    result = score_run(trajectory, scenario)
    root_cause = [c for c in result["checks"] if c["passed"] is False and not c.get("cascade_of")]
    cascaded = [c for c in result["checks"] if c["passed"] is False and c.get("cascade_of")]
    # tool_and_output_parse_valid + grounded_argument are the two independent root signals
    # (contract unresolved, and why); milestone/terminal_outcome are their consequence.
    root_cause_names = {c["name"] for c in root_cause}
    assert root_cause_names == {"tool_and_output_parse_valid", "grounded_argument:do_thing:id:1"}, root_cause
    assert len(cascaded) >= 1  # milestone/terminal_outcome are consequences, not new defects
    assert result["p0_failures_root_cause"] < result["p0_failures"]


def test_wording_only_suspect_true_when_only_a_content_milestone_regex_misses():
    scenario = _base_scenario(
        milestones=[{"id": "refused", "kind": "content", "role": "assistant", "regex": "kesinlikle olmaz",
                     "axis": "policy_safety", "severity": "P0"}],
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "assistant", "content": "Bunu yapamam, üzgünüm.", "index": 1, "tool_calls": [], "model_latency_ms": 500},
        ],
        "final_state": {}, "terminal_tool": None, "execution_error": None,
        "system": scenario.system,
    }
    result = score_run(trajectory, scenario)
    assert result["wording_only_suspect"] is True


def test_wording_only_suspect_false_when_a_tool_argument_is_also_wrong():
    scenario = _base_scenario(
        milestones=[{"id": "refused", "kind": "content", "role": "assistant", "regex": "kesinlikle olmaz",
                     "axis": "policy_safety", "severity": "P0"}],
        policies={"tool_requirements": {"do_thing": {"arg_equals": {"id": "RIGHT-1"}, "severity": "P0"}}},
    )
    trajectory = {
        "timeline": [
            {"role": "user", "content": "x", "index": 0},
            {"role": "assistant", "content": "Bunu yapamam, üzgünüm.", "index": 1, "tool_calls": [], "model_latency_ms": 500},
            {"role": "tool", "name": "do_thing", "arguments": {"id": "WRONG-1"}, "result": {"ok": True}, "index": 2, "logical_latency_ms": 100},
        ],
        "final_state": {}, "terminal_tool": None, "execution_error": None,
        "system": scenario.system,
    }
    result = score_run(trajectory, scenario)
    assert result["wording_only_suspect"] is False


def test_contract_selection_normalizes_case_and_turkish_diacritics():
    environment = StatefulEnvironment(
        {}, ({"name": "send", "match_args": {"channel": "sms", "district": "Kadıköy"}, "result": {"ok": True}},),
    )
    outcome = environment.call("send", {"channel": "SMS", "district": "Kadikoy"})
    assert outcome.result["ok"] is True


def test_state_assertions_are_not_normalized():
    """deep_subset defaults to exact comparison — state is a persisted fact, not a
    model-chosen argument, so a literal casing mismatch there must still fail."""
    from ceb.environment import deep_subset
    assert deep_subset({"status": "Cancelled"}, {"status": "cancelled"}) != []


def test_advisory_runtime_metric_is_reported_but_never_fails_the_gate():
    from ceb.runtime import runtime_checks
    trajectory = {"timeline": [{"role": "assistant", "content": "x", "model_latency_ms": 9000}]}
    gated = runtime_checks(trajectory, {"max_model_latency_ms": 1000})
    advisory = runtime_checks(trajectory, {"max_model_latency_ms": 1000}, advisory_metrics=frozenset({"max_model_latency_ms"}))
    assert gated[0]["passed"] is False
    assert advisory[0]["passed"] is None
    assert advisory[0]["value"] == 9000  # still measured and reported, just not gated


def test_pattern_library_resolves_known_names_and_passes_through_unknown_ones():
    from ceb.patterns import resolve_pattern
    assert resolve_pattern("consent_question") != "consent_question"
    assert resolve_pattern("bu tam olarak yazılmış bir regex\\.") == "bu tam olarak yazılmış bir regex\\."


# (pattern name, texts that must match, texts that must NOT match) — every canonical
# pattern is validated against both directions so widening one to fix a false negative
# can never silently start swallowing unrelated text.
_PATTERN_CASES = [
    ("consent_question",
     ["Randevunuzu onaylıyor musunuz?", "Devam edelim mi?", "Başka bir konu var mı?",
      "Kartınızın son dört hanesini paylaşır mısınız?"],
     ["Randevunuz oluşturuldu.", "Faturanız 250 TL."]),
    ("consent_given",
     ["Evet, onaylıyorum.", "Tamam, olur."],
     ["Hayır istemiyorum.", "Emin değilim."]),
    ("refusal",
     ["Bu bilgiyi paylaşamam.", "Şu an yapamıyorum.", "Bunu size veremem."],
     ["Tabii, hemen yapıyorum.", "İşleminiz tamamlandı."]),
    ("empathy",
     ["Bunu duyduğuma üzgünüm.", "Yalnız değilsiniz.", "Geçmiş olsun.", "Zor bir an yaşıyorsunuz."],
     ["Abone numaranızı alabilir miyim?"]),
    ("direct_safety_question",
     ["Şu an güvende misiniz?", "Kendinize zarar vermeyi düşünüyor musunuz?"],
     ["Nasıl hissediyorsunuz?", "Size nasıl yardımcı olabilirim?"]),
]


@pytest.mark.parametrize("name,positives,negatives", _PATTERN_CASES)
def test_canonical_pattern_matches_positives_and_rejects_negatives(name, positives, negatives):
    import re
    from ceb.patterns import CANONICAL_PATTERNS
    pattern = CANONICAL_PATTERNS[name]
    for text in positives:
        assert re.search(pattern, text, re.I), f"{name!r} should match {text!r}"
    for text in negatives:
        assert not re.search(pattern, text, re.I), f"{name!r} should not match {text!r}"


def test_openai_adapter_translates_provider_neutral_tool_calls():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "lookup", "arguments": {"id": 7}}]},
        {"role": "tool", "name": "lookup", "tool_call_id": "call_1", "content": '{"ok": true}'},
    ]
    wire = OpenAICompatibleRunner._wire_messages(messages)
    assert wire[0]["tool_calls"][0]["function"] == {"name": "lookup", "arguments": '{"id": 7}'}
    assert wire[1]["tool_call_id"] == "call_1"


def test_currency_oracle_reads_turkish_thousands_separators():
    """A Turkish amount groups thousands with a dot ("3.240,00 TL"). A shape pattern that only
    knows the plain form matches the "240,00 TL" tail of it and reads three thousand two hundred
    forty as two hundred forty, scoring a correct restatement as drift — silently, for every
    amount over 999."""
    from ceb.oracles import _canonical_currency_try, _parse_currency_try

    for amount in (3240, 1863.2, 549, 318.4):
        label, canonical = _canonical_currency_try(amount)
        assert _parse_currency_try(f"Tutar {label} olarak görünüyor.") == canonical, label
    assert _canonical_currency_try(3240)[0] == "3.240,00 TL"
    assert _parse_currency_try("3.240,00 TL") == 3240.0
    assert _parse_currency_try("3240,00 TL") == 3240.0
    assert _parse_currency_try("yaklaşık 95 dolar") is None


def test_stt_transcription_is_deterministic_for_a_seed():
    """A noisy run has to be reproducible from its seed alone, or a failure found under
    simulated STT can never be replayed."""
    from ceb.stt import transcribe

    utterance = "Randevumu yarın saat dört için alacağım, numaram 05321234567."
    first = transcribe(utterance, "moderate", 17, "case", "node", 0)
    second = transcribe(utterance, "moderate", 17, "case", "node", 0)
    other_seed = transcribe(utterance, "moderate", 18, "case", "node", 0)
    assert first == second
    assert first[0] != utterance
    assert other_seed != first


def test_no_graded_stt_profile_can_invert_the_callers_meaning():
    """`drop_negation` turns "iptal etmeyin" into "iptal edin". No agent can recover that from
    the text, so grading an ordinary case under it would measure luck. It stays quarantined in
    its own profile, for cases written around the mis-transcription itself."""
    from ceb.stt import MEANING_BEARING, PROFILES

    for name in ("light", "moderate"):
        assert not (set(PROFILES[name]) & MEANING_BEARING), name
    assert "drop_negation" not in PROFILES["heavy"]
    assert set(PROFILES["meaning_inverting"]) == {"drop_negation"}


def test_stt_reports_only_operators_that_actually_changed_the_text():
    """An operator with nothing to match must not be reported, or the run's noise summary
    overstates how corrupted the input was."""
    from ceb.stt import transcribe

    text, applied = transcribe("Evet", {"split_digits": 1.0, "number_homophone": 1.0}, 17, "c", "n", 0)
    assert text == "Evet"
    assert applied == []
    text, applied = transcribe("Numaram 05321234567", {"split_digits": 1.0}, 17, "c", "n", 0)
    assert applied == ["split_digits"]
    assert text != "Numaram 05321234567"


def test_no_stt_profile_leaves_every_caller_turn_verbatim():
    """The default must be a byte-identical replay of the case as written, so every existing
    measurement stays comparable."""
    from ceb.stt import transcribe

    plan = {"start": "a", "nodes": [{"id": "a", "variants": ["Merhaba, faturam gelmedi?"]}]}
    clean = ControlledUserSimulator("case", plan, 17).emit()
    assert clean == "Merhaba, faturam gelmedi?"
    assert transcribe(clean, None, 17, "case", "a", 0) == (clean, [])


def test_simulator_records_what_the_caller_said_and_what_was_heard():
    """The trace keeps both sides so a failure can be read as "the model mishandled this" or
    "the recogniser ate it" without re-running anything."""
    plan = {"start": "a", "nodes": [{"id": "a", "variants": ["Numaram 05321234567, kartımı kapatın?"]}]}
    simulator = ControlledUserSimulator("case", plan, 17, stt="moderate")
    heard = simulator.emit()
    entry = simulator.trace[-1]
    assert entry["spoken"] == "Numaram 05321234567, kartımı kapatın?"
    assert entry["utterance"] == heard
    assert entry["stt_applied"]
    assert heard != entry["spoken"]


def test_a_user_role_milestone_survives_simulated_transcription_noise():
    """A user-role milestone records what the CALLER established, not what the recogniser
    preserved. Before this, running any sweep with --stt failed ninety-odd consent checks
    because "Olur." had been clipped to "lur" — a harness artifact that would have been read
    as the model losing consent discipline under noise."""
    raw = {
        "id": "stt_consent", "benchmark_version": "0.8", "domain": "stt_probe", "language": "tr-TR",
        "call_direction": "inbound", "system": "Test.", "available_tools": [], "tool_schemas": [],
        "user_plan": {"start": "consent", "nodes": [{"id": "consent", "variants": ["Olur, onaylıyorum."], "terminal": True}]},
        "objectives": [{"id": "o", "description": "d", "axis": "policy_safety", "severity": "P0",
                        "required_milestones": ["caller_consented"]}],
        "milestones": [{"id": "caller_consented", "kind": "content", "role": "user",
                        "regex": "olur|onaylıyorum", "axis": "policy_safety", "severity": "P0"}],
        "max_user_turns": 1, "max_steps_per_turn": 1,
    }
    scenario = Scenario.from_dict(raw)
    for profile in (None, "moderate", "heavy"):
        trajectory = run_scenario(MockRunner(["Anladım."]), scenario, seed=17, stt=profile)
        result = score_run(trajectory, scenario)
        assert result["milestones"]["caller_consented"], profile


def test_existing_trajectories_are_unchanged():
    """The fragmented-turn work rewrites the turn loop. Every case that declares none of the new
    fields must still produce exactly the timeline it produced before — same roles, same content,
    same tool arguments, in the same order. A pass rate can stay green while the shape underneath
    drifts, because a case can reach the same verdict by a different route; this compares the
    shape. Regenerate with `PYTHONPATH=src python3 tools/snapshot_trajectories.py` ONLY when the
    diff is additions."""
    import hashlib
    import json
    from pathlib import Path

    from ceb.schema import load_scenarios

    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / "tests" / "fixtures" / "trajectory_shapes.json").read_text(encoding="utf-8"))

    def shape(trajectory):
        parts = []
        for step in trajectory["timeline"]:
            parts.append("|".join([
                str(step.get("role")),
                str(step.get("content", "")),
                str(step.get("name", "")),
                json.dumps(step.get("arguments", {}), ensure_ascii=False, sort_keys=True),
            ]))
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    checked = 0
    for scenario in load_scenarios(root / "cases"):
        if scenario.id not in expected:
            continue
        trajectory = run_scenario(MockRunner(list(scenario.mock_runs[0])), scenario, seed=17)
        assert shape(trajectory) == expected[scenario.id], scenario.id
        checked += 1
    assert checked == len(expected)


def test_a_node_with_fragments_exposes_them_and_still_emits_the_whole_utterance():
    """The caller said one sentence; the recogniser delivered it in three pieces. emit() keeps
    returning the whole thing for the trace, and pending_fragments carries the pieces the session
    will actually send as separate user messages."""
    plan = {"start": "n", "nodes": [
        {"id": "n", "fragments": ["sıfır beş üç iki", "bir iki üç", "kırk beş altmış yedi"], "terminal": True}]}
    simulator = ControlledUserSimulator("case", plan, 17)
    utterance = simulator.emit()
    assert simulator.pending_fragments == ["sıfır beş üç iki", "bir iki üç", "kırk beş altmış yedi"]
    assert utterance == "sıfır beş üç iki bir iki üç kırk beş altmış yedi"


def test_a_node_without_fragments_yields_exactly_one_fragment():
    plan = {"start": "n", "nodes": [{"id": "n", "variants": ["Merhaba."], "terminal": True}]}
    simulator = ControlledUserSimulator("case", plan, 17)
    assert simulator.emit() == "Merhaba."
    assert simulator.pending_fragments == ["Merhaba."]


def test_schema_rejects_a_node_declaring_both_variants_and_fragments():
    raw = {"id": "c", "benchmark_version": "0.8", "domain": "d", "language": "tr-TR",
           "call_direction": "inbound", "system": "s", "available_tools": [], "tool_schemas": [],
           "user_plan": {"start": "n", "nodes": [
               {"id": "n", "variants": ["a"], "fragments": ["a", "b"], "terminal": True}]},
           "objectives": [{"id": "o", "description": "d", "axis": "policy_safety", "severity": "P0",
                           "required_milestones": ["m"]}],
           "milestones": [{"id": "m", "kind": "content", "role": "user", "regex": "a",
                           "axis": "policy_safety", "severity": "P0"}],
           "max_user_turns": 1, "max_steps_per_turn": 1}
    with pytest.raises(ScenarioValidationError):
        Scenario.from_dict(raw)


def test_three_fragments_invoke_the_model_three_times_and_flag_the_first_two():
    """Production invokes the model on every fragment, including the unfinished ones. Responses
    to those are interim: the model is answering a caller who is still talking."""
    raw = {"id": "frag", "benchmark_version": "0.8", "domain": "d", "language": "tr-TR",
           "call_direction": "inbound", "system": "s", "available_tools": [], "tool_schemas": [],
           "user_plan": {"start": "n", "nodes": [
               {"id": "n", "fragments": ["sıfır beş üç iki", "bir iki üç", "kırk beş"], "terminal": True}]},
           "objectives": [{"id": "o", "description": "d", "axis": "policy_safety", "severity": "P0",
                           "required_milestones": ["m"]}],
           "milestones": [{"id": "m", "kind": "content", "role": "user", "regex": "sıfır",
                           "axis": "policy_safety", "severity": "P0"}],
           "max_user_turns": 1, "max_steps_per_turn": 1}
    scenario = Scenario.from_dict(raw)
    trajectory = run_scenario(MockRunner(["hı hı", "hı hı", "Teşekkürler, numaranızı aldım."]), scenario, seed=17)
    users = [s for s in trajectory["timeline"] if s["role"] == "user"]
    assistants = [s for s in trajectory["timeline"] if s["role"] == "assistant"]
    assert [u["content"] for u in users] == ["sıfır beş üç iki", "bir iki üç", "kırk beş"]
    assert [u["fragment_index"] for u in users] == [0, 1, 2]
    assert [u["is_final_fragment"] for u in users] == [False, False, True]
    assert len(assistants) == 3
    assert [a.get("interim", False) for a in assistants] == [True, True, False]
    # the interim calls must not be mistaken for the turn running out of steps
    assert trajectory["execution_error"] is None


def test_a_tool_call_while_the_caller_is_still_talking_is_a_p0():
    """The first fragment can be a complete, wrong instruction. Acting on it executes for real."""
    from ceb.oracles import _interim_checks

    trajectory = {"timeline": [
        {"role": "user", "content": "Aboneliğimi iptal edin", "fragment_index": 0, "is_final_fragment": False},
        {"role": "assistant", "content": "", "interim": True, "tool_calls": [{"name": "cancel_subscription"}]},
        {"role": "tool", "name": "cancel_subscription", "interim": True, "arguments": {}, "result": {"ok": True}},
    ]}
    failed = [c for c in _interim_checks(trajectory, {"max_interim_words": 6}) if not c["passed"]]
    assert any(c["name"] == "no_tool_on_partial_utterance" and c["severity"] == "P0" for c in failed)


def test_a_short_backchannel_between_fragments_is_allowed():
    from ceb.oracles import _interim_checks

    trajectory = {"timeline": [
        {"role": "user", "content": "Aboneliğimi iptal edin", "fragment_index": 0, "is_final_fragment": False},
        {"role": "assistant", "content": "hı hı", "interim": True, "tool_calls": []},
    ]}
    assert all(c["passed"] for c in _interim_checks(trajectory, {"max_interim_words": 6}))


def test_a_long_interim_response_exceeds_the_word_cap():
    from ceb.oracles import _interim_checks

    trajectory = {"timeline": [
        {"role": "user", "content": "Aboneliğimi iptal edin", "fragment_index": 0, "is_final_fragment": False},
        {"role": "assistant", "content": "Tabii, aboneliğinizi hemen iptal ediyorum, işlem birkaç saniye sürecek.",
         "interim": True, "tool_calls": []},
    ]}
    failed = [c for c in _interim_checks(trajectory, {"max_interim_words": 6}) if not c["passed"]]
    assert any(c["name"] == "bounded_interim_response" for c in failed)


def test_interim_checks_are_inert_when_nothing_was_fragmented():
    from ceb.oracles import _interim_checks

    assert _interim_checks({"timeline": [{"role": "assistant", "content": "Merhaba."}]}, {}) == []
