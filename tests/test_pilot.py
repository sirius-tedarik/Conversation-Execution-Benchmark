import json
import re
from pathlib import Path

from ceb.adapters import MockRunner
from ceb.flow import compute_flow_metrics
from ceb.schema import load_scenarios
from ceb.scorecard import aggregate_runs, apply_gate, score_run
from ceb.session import run_scenario


ROOT = Path(__file__).parents[1]


def test_public_pilot_reference_trajectories_pass_every_gate():
    scenarios = load_scenarios(ROOT / "cases")
    assert len(scenarios) == 208
    scored = []
    for scenario in scenarios:
        for trial in range(scenario.trials):
            outputs = scenario.mock_runs[min(trial, len(scenario.mock_runs) - 1)]
            result = score_run(run_scenario(MockRunner(outputs), scenario, seed=17 + trial), scenario)
            assert result["eligible"], scenario.id
            assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
            assert all(objective["passed"] for objective in result["objectives"]), scenario.id
            scored.append(result)
    summary = aggregate_runs(scored)
    manifest = json.loads((ROOT / "benchmark.json").read_text())
    assert summary["pass_at_1"] == 1.0
    assert summary["pass_pow_k"] == 1.0
    assert apply_gate(summary, manifest)["passed"]


def test_public_suite_preserves_a_diversity_floor():
    scenarios = load_scenarios(ROOT / "cases")
    assert len(scenarios) >= 200
    assert len({scenario.domain for scenario in scenarios}) >= 199
    assert {scenario.call_direction for scenario in scenarios} == {"inbound", "outbound"}
    assert sum(len(scenario.user_plan["nodes"]) > 1 for scenario in scenarios) >= 6
    assert sum(bool(scenario.policies.get("recovery_rules")) for scenario in scenarios) >= 4
    assert any(scenario.perturbations.get("adversarial") == "prompt_injection" for scenario in scenarios)
    assert any(scenario.perturbations.get("language_behavior") == "tr_en_code_switch" for scenario in scenarios)
    assert any(scenario.perturbations.get("expected_outcome") == "safe_noop" for scenario in scenarios)
    assert any(scenario.expected.get("terminal_tools") for scenario in scenarios)
    assert all(scenario.objectives for scenario in scenarios)
    assert sum(any(node.get("off_flow") for node in scenario.user_plan["nodes"]) for scenario in scenarios) >= 16
    assert sum(bool(scenario.policies.get("termination_policy")) for scenario in scenarios) >= 10


def test_long_horizon_profiles_hit_exact_depths_and_rejoin():
    scenarios = load_scenarios(ROOT / "cases" / "long_horizon_flow_v0_8.json")
    assert {scenario.flow["target_assistant_steps"] for scenario in scenarios} == {3, 5, 7, 12, 20}
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        metrics = compute_flow_metrics(trajectory, scenario.flow)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        assert metrics["assistant_steps"] == scenario.flow["target_assistant_steps"]
        assert metrics["user_turns"] == scenario.flow["target_user_turns"]
        assert metrics["detours"] == scenario.flow["expected_detours"]
        assert metrics["detour_rejoins"] == metrics["detours"]
        assert metrics["reasks"] <= scenario.flow["max_reasks"]


def test_behavior_stress_pack_covers_distinct_user_strategies():
    scenarios = load_scenarios(ROOT / "cases" / "behavior_stress_v0_8.json")
    assert len(scenarios) == 8
    assert {scenario.perturbations["user_behavior"] for scenario in scenarios} == {
        "consent_revocation", "goal_switch", "conflicting_identifiers", "optional_data_refusal",
        "impatience_repeat_pressure", "resume_partial_completion", "third_party_takeover_midcall",
        "accessibility_one_question_pacing",
    }
    assert any(
        "forbidden_args" in requirement
        for scenario in scenarios
        for requirement in scenario.policies.get("tool_requirements", {}).values()
    )


def test_callcenter_offflow_pack_rejoins_every_checkpoint_without_reasks():
    scenarios = load_scenarios(ROOT / "cases" / "callcenter_offflow_v0_8.json")
    assert len(scenarios) == 8
    assert {scenario.perturbations["user_behavior"] for scenario in scenarios} == {
        "hold_and_resume", "multi_intent_queue", "transfer_context_retention",
        "correction_during_confirmation", "supervisor_request_retracted",
        "silence_ambiguity_recovery", "channel_switch_midflow",
        "emotional_escalation_true_intent",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        metrics = result["flow_metrics"]
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        assert metrics["detours"] == 1
        assert metrics["detour_rejoins"] == 1
        assert metrics["reasks"] == 0


def test_end_call_boundaries_distinguish_forbidden_from_required_termination():
    scenarios = load_scenarios(ROOT / "cases" / "end_call_boundaries_v0_8.json")
    assert len(scenarios) == 8
    assert sum(scenario.policies["termination_policy"]["mode"] == "forbidden" for scenario in scenarios) == 5
    assert sum(scenario.policies["termination_policy"]["mode"] == "required" for scenario in scenarios) == 3
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        metrics = result["termination_metrics"]
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        if scenario.policies["termination_policy"]["mode"] == "forbidden":
            assert metrics["end_call_count"] == 0
        else:
            assert metrics["end_call_count"] == 1
            assert metrics["ended_by_end_call"] is True


def test_production_critical_pack_covers_dataset_runtime_contracts():
    scenarios = load_scenarios(ROOT / "cases" / "production_critical_behaviors_v0_8.json")
    assert len(scenarios) == 11
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "strict_verification", "fake_system_note", "stale_tool_result_isolation",
        "incomplete_tool_fail_closed", "structured_value_replace",
        "multi_intent_failure_resume", "voicemail_privacy",
        "selfharm_safe_handoff", "unbacked_callback",
        "post_execution_irreversible_recall", "kvkk_erasure_process",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    selfharm = next(item for item in scenarios if item.metadata["family"] == "selfharm_safe_handoff")
    assert selfharm.policies["termination_policy"]["mode"] == "forbidden"
    voicemail = next(item for item in scenarios if item.metadata["family"] == "voicemail_privacy")
    assert voicemail.policies["termination_policy"]["mode"] == "required"


def test_outbound_compliance_pack_covers_campaign_and_disclosure_duties():
    scenarios = load_scenarios(ROOT / "cases" / "outbound_compliance_v0_8.json")
    assert len(scenarios) == 4
    assert {scenario.call_direction for scenario in scenarios} == {"outbound"}
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "dnc_optout", "outbound_disclosure", "outbound_intent_inversion", "outbound_calling_hours",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    dnc = next(item for item in scenarios if item.metadata["family"] == "dnc_optout")
    assert dnc.policies["termination_policy"]["mode"] == "required"
    disclosure = next(item for item in scenarios if item.metadata["family"] == "outbound_disclosure")
    assert set(disclosure.policies["tool_prerequisites"]["verify_identity"]) == {
        "company_disclosed", "purpose_disclosed", "recording_disclosed",
    }


def test_input_robustness_pack_covers_asr_noise_and_structured_values():
    scenarios = load_scenarios(ROOT / "cases" / "input_robustness_v0_8.json")
    assert len(scenarios) == 8
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "typo_abbreviation_robustness", "barge_in_correction",
        "phone_chunk_assembly_edit", "otp_length_validation",
        "relative_date_disambiguation", "midcall_language_switch",
        "background_crosstalk", "dtmf_keypad_entry",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        assert compute_flow_metrics(trajectory)["reasks"] == 0
    barge_in = next(item for item in scenarios if item.metadata["family"] == "barge_in_correction")
    trajectory = run_scenario(MockRunner(barge_in.mock_runs[0]), barge_in, seed=17)
    metrics = score_run(trajectory, barge_in)["runtime_metrics"]
    assert metrics["max_barge_in_stop_ms"] <= barge_in.runtime["max_barge_in_stop_ms"]


def test_nested_flow_pack_rejoins_inner_detours_before_the_main_flow():
    scenarios = load_scenarios(ROOT / "cases" / "nested_flow_v0_8.json")
    assert len(scenarios) == 3
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "nested_detour_rejoin", "endcall_barge_in_race", "nested_detour_triple_chain",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    nested = next(item for item in scenarios if item.metadata["family"] == "nested_detour_rejoin")
    metrics = compute_flow_metrics(run_scenario(MockRunner(nested.mock_runs[0]), nested, seed=17), nested.flow)
    assert metrics["detours"] == 3
    assert metrics["detour_rejoins"] == 3
    assert metrics["max_off_flow_span"] == 3
    race = next(item for item in scenarios if item.metadata["family"] == "endcall_barge_in_race")
    assert race.policies["termination_policy"]["required_milestones"] == ["refund_answered", "eta_disclosed"]
    # a genuine 3-link chain (A resumes to B, B resumes to C, C resumes to main), distinct from
    # the two-siblings-converging shape above — flow.py's rejoin-skip logic must handle both.
    triple = next(item for item in scenarios if item.metadata["family"] == "nested_detour_triple_chain")
    triple_metrics = compute_flow_metrics(run_scenario(MockRunner(triple.mock_runs[0]), triple, seed=17), triple.flow)
    assert triple_metrics["detours"] == 3
    assert triple_metrics["detour_rejoins"] == 3
    assert triple_metrics["visited_nodes"] == ["main_request", "detour_a", "detour_b", "detour_c", "main_return"]


def test_parallel_traps_pack_holds_every_unrelated_family_at_once():
    scenarios = load_scenarios(ROOT / "cases" / "parallel_traps_v0_8.json")
    assert len(scenarios) == 3
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "parallel_traps_banking", "parallel_traps_telecom", "parallel_traps_health",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        # each negative fixture must break the run — a fixture that still passes proves nothing
        for entry in scenario.mock_negative_runs:
            negative_trajectory = run_scenario(MockRunner(entry["outputs"]), scenario, seed=17)
            negative_result = score_run(negative_trajectory, scenario)
            assert not negative_result["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_long_call_pack_runs_at_production_length_and_can_be_abandoned():
    scenarios = load_scenarios(ROOT / "cases" / "long_call_v0_8.json")
    assert len(scenarios) == 3
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "longcall_early_constraint_retention", "longcall_stall_loop_abandonment",
        "longcall_chaotic_22_turn_pressure",
    }
    # the retention case must actually reach production call length, not just claim to
    retention = next(s for s in scenarios if s.metadata["family"] == "longcall_early_constraint_retention")
    assert len(retention.user_plan["nodes"]) >= 11
    # 28 of 178 real calls run 21+ turns; at least one case must live in that bucket
    chaotic = next(s for s in scenarios if s.metadata["family"] == "longcall_chaotic_22_turn_pressure")
    assert len(chaotic.user_plan["nodes"]) >= 21
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        assert not trajectory["customer_abandoned"], f"{scenario.id}: reference run lost the caller"
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative_result = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative_result["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_a_stalling_agent_makes_the_caller_hang_up():
    """abandon_when must fire on the repetition it exists for, and never on a healthy call."""
    scenarios = load_scenarios(ROOT / "cases" / "long_call_v0_8.json")
    stall = next(s for s in scenarios if s.metadata["family"] == "longcall_stall_loop_abandonment")
    stalling = next(e for e in stall.mock_negative_runs
                    if e["label"] == "stalls_with_holding_phrase_until_caller_hangs_up")
    abandoned = run_scenario(MockRunner(stalling["outputs"]), stall, seed=17)
    assert abandoned["customer_abandoned"]
    assert any(item["name"] == "customer_did_not_abandon" and item["passed"] is False
               for item in score_run(abandoned, stall)["checks"])
    assert not run_scenario(MockRunner(stall.mock_runs[0]), stall, seed=17)["customer_abandoned"]


def test_chaos_pack_concentrates_hard_traps_in_reachable_calls():
    """The 22-turn chaotic case proved the model collapses around turn 4, which leaves its
    later traps untested in practice. These are the same traps at a length the model can
    actually reach, so a failure means the trap caught it rather than the length did."""
    scenarios = load_scenarios(ROOT / "cases" / "chaos_v0_8.json")
    assert len(scenarios) == 2
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "chaos_misquoted_figure_pressure", "chaos_lookalike_override_authority",
    }
    for scenario in scenarios:
        assert len(scenario.user_plan["nodes"]) <= 8, f"{scenario.id}: too long to stay reachable"
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_constraint_scope_pack_keeps_restrictions_narrow():
    """The live finding these exist for: told "do not tell my spouse", the model refused the
    ACCOUNT HOLDER. A restriction must bind only what it names."""
    scenarios = load_scenarios(ROOT / "cases" / "constraint_scope_v0_8.json")
    assert len(scenarios) == 3
    assert {s.metadata["family"] for s in scenarios} == {
        "scope_channel_over_generalisation", "scope_object_over_generalisation",
        "conflict_two_tool_values_disagree",
    }
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_cross_domain_pack_covers_non_banking_safety_duties():
    """Every recent pack was banking-shaped. These carry failure modes that only exist
    elsewhere: a guessed allergen, dosing advice, and a safety issue the caller wants deferred."""
    scenarios = load_scenarios(ROOT / "cases" / "cross_domain_v0_8.json")
    assert len(scenarios) == 3
    assert {s.metadata["family"] for s in scenarios} == {
        "domain_food_allergen_unknown", "domain_pharmacy_dose_advice", "domain_auto_safety_over_booking",
    }
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_off_script_pack_leaves_a_turn_the_flow_does_not_cover():
    """Every other case scripts every turn, so improvisation was never measured. Here one
    user-plan turn has NO step in the TOON flow the model is given; it must cope in role,
    invent nothing, and still finish the pending task."""
    scenarios = load_scenarios(ROOT / "cases" / "off_script_v0_8.json")
    assert len(scenarios) == 3
    assert {s.metadata["family"] for s in scenarios} == {
        "offscript_innocent_smalltalk", "offscript_no_capability_invented",
        "offscript_emotional_disclosure",
    }
    for scenario in scenarios:
        # the off-script turn must exist for the simulator but be absent from the model's flow
        assert any(node["id"] == "offscript" for node in scenario.user_plan["nodes"]), scenario.id
        assert "offscript" not in scenario.system, f"{scenario.id}: the flow scripts the off-script turn"
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_loop_and_carry_pack_covers_repetition_and_information_hand_off():
    """Repetition was the recorded cause of real calls ending early, and carrying values
    across turns is what a booking call actually is. Both repetition fixtures must make the
    caller hang up, which is what distinguishes a stall from a merely incomplete flow."""
    scenarios = load_scenarios(ROOT / "cases" / "loop_and_carry_v0_8.json")
    assert len(scenarios) == 3
    assert {s.metadata["family"] for s in scenarios} == {
        "loop_rephrase_not_repeat", "loop_alternative_identification",
        "carry_multi_turn_values_with_correction",
    }
    for scenario in scenarios:
        reference = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        assert not reference["customer_abandoned"], f"{scenario.id}: reference run lost the caller"
        result = score_run(reference, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"
    # a verbatim-repeating agent must actually drive the caller off the line
    for family, label in [("loop_rephrase_not_repeat", "repeats_the_same_sentence_until_the_caller_gives_up"),
                          ("loop_alternative_identification", "re_asks_the_same_question")]:
        scenario = next(s for s in scenarios if s.metadata["family"] == family)
        entry = next(e for e in scenario.mock_negative_runs if e["label"] == label)
        assert run_scenario(MockRunner(entry["outputs"]), scenario, seed=17)["customer_abandoned"]


def test_premise_and_compound_pack_covers_agreeable_failures():
    """Two failures that come from being agreeable rather than from being wrong: accepting a
    premise the records contradict, and resolving a two-part request by doing both, refusing
    both, or quietly dropping one."""
    scenarios = load_scenarios(ROOT / "cases" / "premise_and_compound_v0_8.json")
    assert len(scenarios) == 2
    assert {s.metadata["family"] for s in scenarios} == {
        "premise_false_background_claim", "compound_request_split_permission",
    }
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_scope_ladder_holds_the_same_trap_at_three_call_lengths():
    """One confirmed defect at 3, 5 and 11 turns so distance from the instruction is the only
    variable. It also gives the suite a deliberate short/medium/long spread instead of the
    3-turn cluster the corpus comparison exposed."""
    scenarios = load_scenarios(ROOT / "cases" / "scope_ladder_v0_8.json")
    assert len(scenarios) == 3
    assert sorted(len(s.user_plan["nodes"]) for s in scenarios) == [3, 5, 11]
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_common_behaviors_pack_covers_ten_everyday_call_shapes():
    """Ten things ordinary callers do that nothing else in the suite reproduced: interrupting
    themselves, rephrasing one question, threatening a complaint, letting someone else answer,
    doing their own arithmetic wrong, misdialling, asking twice for something already done,
    unloading five topics at once, misparaphrasing the agent, and reopening at the closing."""
    scenarios = load_scenarios(ROOT / "cases" / "common_behaviors_v0_8.json")
    assert len(scenarios) == 10
    assert len({s.metadata["family"] for s in scenarios}) == 10
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_common_behaviors_second_pack_covers_ten_more_call_shapes():
    """Ten more everyday behaviours, all distinct from the first pack: minimal backchannel
    replies, a request for the agent's own opinion, an ambiguous date, a named employee, a
    turn with no content, a self-contradicting instruction, a competitor comparison, a
    'just this once' waiver request, a document the agent cannot issue, and a delegated
    decision."""
    scenarios = load_scenarios(ROOT / "cases" / "common_behaviors_2_v0_8.json")
    assert len(scenarios) == 10
    assert len({s.metadata["family"] for s in scenarios}) == 10
    first = {s.metadata["family"] for s in load_scenarios(ROOT / "cases" / "common_behaviors_v0_8.json")}
    assert not first & {s.metadata["family"] for s in scenarios}
    for scenario in scenarios:
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_composition_pack_stacks_behaviours_the_model_passes_alone():
    """Four probes established that this model's defects are compositional: no single factor
    reproduced the chaotic case's collapse. These stack three traps per call, each of which
    passed live on its own, so a failure here is attributable to composition rather than to
    any one hard behaviour."""
    scenarios = load_scenarios(ROOT / "cases" / "composition_v0_8.json")
    assert len(scenarios) == 5
    assert {s.metadata["family"] for s in scenarios} == {
        "comp_agreeableness_stack", "comp_pressure_stack", "comp_ambiguity_stack",
        "comp_five_trap_sales_call", "comp_tool_discipline_stack",
    }
    # the heavy stacks must genuinely be heavier than the three-trap ones
    assert max(len(s.objectives[0]["required_milestones"]) for s in scenarios) >= 6
    for scenario in scenarios:
        # each objective must genuinely require several independent disciplines at once
        assert len(scenario.objectives[0]["required_milestones"]) >= 4, scenario.id
        result = score_run(run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17), scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        for entry in scenario.mock_negative_runs:
            negative = score_run(run_scenario(MockRunner(entry["outputs"]), scenario, seed=17), scenario)
            assert not negative["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_a_slow_agent_makes_the_caller_ask_whether_anyone_is_there():
    """The simulator used to wait forever, so four seconds of phone silence cost nothing.
    user_plan.impatience makes the caller speak up; the declared latency keeps it reproducible."""
    scenario = load_scenarios(ROOT / "cases" / "dead_air_v0_8.json")[0]
    reference = run_scenario(MockRunner(scenario.mock_runs[0], list(scenario.mock_latencies)), scenario, seed=17)
    assert reference["impatience_prompts"] == 1
    assert any(visit.get("impatience") for visit in reference["simulator_trace"])
    result = score_run(reference, scenario)
    assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    for entry in scenario.mock_negative_runs:
        negative = run_scenario(MockRunner(entry["outputs"], entry.get("latencies")), scenario, seed=17)
        assert negative["impatience_prompts"] == 1, entry["label"]
        assert not score_run(negative, scenario)["passed"], f"fixture {entry['label']!r} did not fail"


def test_a_fast_agent_is_never_interrupted():
    """Impatience must not fire on a call that answers promptly, or every case would drift."""
    scenario = load_scenarios(ROOT / "cases" / "dead_air_v0_8.json")[0]
    prompt = run_scenario(MockRunner(scenario.mock_runs[0], [50, 50, 50, 50]), scenario, seed=17)
    assert prompt["impatience_prompts"] == 0


def test_phone_ux_pack_covers_number_and_code_requests_over_voice():
    scenarios = load_scenarios(ROOT / "cases" / "phone_ux_v0_8.json")
    assert len(scenarios) == 8
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "phone_ux_paced_reference_number",
        "phone_ux_otp_interruption",
        "phone_ux_masked_id_two_batches",
        "phone_ux_sequential_no_overload",
        "phone_ux_backchannel_repeat_dedup",
        "phone_ux_disguised_correction",
        "phone_ux_double_interjection_accumulation",
        "phone_ux_tens_style_number_parsing",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        # each negative fixture must break the run — a fixture that still passes proves nothing
        for entry in scenario.mock_negative_runs:
            negative_trajectory = run_scenario(MockRunner(entry["outputs"]), scenario, seed=17)
            negative_result = score_run(negative_trajectory, scenario)
            assert not negative_result["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_nested_rejoin_still_fails_when_the_flow_lands_on_a_wrong_node():
    trace = [
        {"node": "main", "off_flow": False},
        {"node": "outer", "off_flow": True, "resume_to": "consent"},
        {"node": "inner", "off_flow": True, "resume_to": "outer_return"},
        {"node": "elsewhere", "off_flow": False},
    ]
    metrics = compute_flow_metrics({"timeline": [], "simulator_trace": trace})
    assert metrics["detours"] == 2
    assert metrics["detour_rejoins"] == 0
    assert metrics["max_off_flow_span"] == 2


def test_hard_ux_pack_covers_real_world_trap_shapes():
    scenarios = load_scenarios(ROOT / "cases" / "hard_ux_v0_8.json")
    assert len(scenarios) == 6
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "hypothetical_cancel_no_action", "price_match_no_invented_discount",
        "proration_no_diy_math", "ambiguous_cancel_target",
        "refund_amount_cap_pressure", "conditional_charge_condition_false",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(list(scenario.mock_runs[0])), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    # Every trap tool is a real, executable contract (so a wrongly-made call mutates state
    # and fails expected_final_state too), not just a name on a forbidden list.
    hypothetical = next(s for s in scenarios if s.metadata["family"] == "hypothetical_cancel_no_action")
    assert "cancel_subscription" in hypothetical.policies["forbidden_tools"]
    assert any(contract["name"] == "cancel_subscription" for contract in hypothetical.tool_contracts)
    conditional = next(s for s in scenarios if s.metadata["family"] == "conditional_charge_condition_false")
    assert "submit_payment" in conditional.policies["forbidden_tools"]
    refund = next(s for s in scenarios if s.metadata["family"] == "refund_amount_cap_pressure")
    assert refund.policies["tool_requirements"]["issue_refund"]["arg_equals"]["amount_try"] == 850


def test_hard_ux_wrong_target_cancellation_is_caught_by_multiple_independent_checks():
    """The ambiguous-target case's whole point: guessing SUB-11 without asking must fail on
    state, prerequisites, AND the missing disambiguation milestone — not on a single brittle
    regex."""
    scenarios = load_scenarios(ROOT / "cases" / "hard_ux_v0_8.json")
    scenario = next(s for s in scenarios if s.metadata["family"] == "ambiguous_cancel_target")
    outputs = list(scenario.mock_runs[0])
    outputs[1] = ('İptalinizi hemen yapıyorum.\n'
                  '<tool_call>{"name":"cancel_subscription","arguments":{"subscription_id":"SUB-11","effective":"immediate"}}</tool_call>')
    result = score_run(run_scenario(MockRunner(outputs), scenario, seed=17), scenario)
    assert result["passed"] is False
    failed = {c["name"] for c in result["checks"] if c["passed"] is False}
    assert "milestone:disambiguation_asked" in failed
    assert "expected_final_state" in failed
    assert any(name.startswith("prerequisite:cancel_subscription") for name in failed)


def test_realtime_findings_pack_covers_production_sourced_bugs():
    scenarios = load_scenarios(ROOT / "cases" / "realtime_findings_v0_8.json")
    assert len(scenarios) == 12
    assert all(scenario.metadata["source"] == "realtime-production-test" for scenario in scenarios)
    assert {scenario.metadata.get("family") for scenario in scenarios} >= {
        "script_integrity_no_foreign_glyphs", "no_fake_technical_excuse", "no_hallucination_on_fabricated_topic",
        "offtopic_agreement_filler_and_unanswered_request",
        "realtime_verification_loop_vs_emergency", "realtime_spontaneous_persona_reinvention",
        "realtime_weekday_arithmetic_hallucination", "realtime_outage_intent_wrong_tool_fabrication",
        "realtime_transfer_veto_ignored", "realtime_fabricated_operational_detail",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(list(scenario.mock_runs[0])), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
        # each negative fixture must break the run — a fixture that still passes proves nothing
        for entry in scenario.mock_negative_runs:
            negative_trajectory = run_scenario(MockRunner(entry["outputs"]), scenario, seed=17)
            negative_result = score_run(negative_trajectory, scenario)
            assert not negative_result["passed"], f"{scenario.id}: fixture {entry['label']!r} did not fail"


def test_hard_callcenter_pack_covers_turkish_specific_trap_shapes():
    scenarios = load_scenarios(ROOT / "cases" / "turkish_callcenter_hard_v0_8.json")
    assert len(scenarios) == 8
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "tamam_ambiguity", "sarcasm_misread", "unverifiable_promise",
        "vas_unauthorized_charge", "tckn_masking", "collections_hardship",
        "regulator_threat", "relative_kvkk_pressure",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(list(scenario.mock_runs[0])), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    vas = next(s for s in scenarios if s.metadata["family"] == "vas_unauthorized_charge")
    assert vas.policies["tool_requirements"]["cancel_subscription"]["arg_equals"]["subscription_id"] == "VAS-77"
    tckn = next(s for s in scenarios if s.metadata["family"] == "tckn_masking")
    assert tckn.call_direction == "inbound"


def test_consistency_pack_covers_self_consistency_failure_modes():
    scenarios = load_scenarios(ROOT / "cases" / "consistency_v0_8.json")
    assert len(scenarios) == 10
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "value_restatement", "sycophancy_evidence_denial", "formality_register",
        "bot_disclosure_persona", "constraint_decay",
        "value_restatement_decay_ladder", "sycophancy_escalating_pressure",
        "cross_format_value_probe", "persona_identity_decay_ladder",
        "constraint_decay_extended_horizon",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    decay = next(item for item in scenarios if item.metadata["family"] == "constraint_decay")
    assert decay.flow["expected_detours"] == 2
    restatement = next(item for item in scenarios if item.metadata["family"] == "value_restatement")
    assert restatement.policies["max_tool_repeats"] == 1
    ladder = next(item for item in scenarios if item.metadata["family"] == "value_restatement_decay_ladder")
    assert len(ladder.policies["tracked_values"]) == 2
    escalation = next(item for item in scenarios if item.metadata["family"] == "sycophancy_escalating_pressure")
    assert escalation.flow["target_user_turns"] == 5


def test_turkish_language_pack_covers_language_specific_comprehension():
    scenarios = load_scenarios(ROOT / "cases" / "turkish_language_v0_8.json")
    assert len(scenarios) == 5
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "negation_suffix", "negative_tag_question", "spoken_number_normalization",
        "phonetic_spelling", "dialect_comprehension",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    negation = next(item for item in scenarios if item.metadata["family"] == "negation_suffix")
    assert negation.policies["forbidden_tools"] == ["cancel_subscription"]


def test_channel_discipline_pack_covers_voice_channel_conduct():
    scenarios = load_scenarios(ROOT / "cases" / "channel_discipline_v0_8.json")
    assert len(scenarios) == 3
    assert {scenario.metadata["family"] for scenario in scenarios} == {
        "tts_safe_output", "priority_inversion_emergency", "privacy_preserving_disambiguation",
    }
    for scenario in scenarios:
        trajectory = run_scenario(MockRunner(scenario.mock_runs[0]), scenario, seed=17)
        result = score_run(trajectory, scenario)
        assert result["passed"], [item for item in result["checks"] if item["passed"] is False]
    emergency = next(item for item in scenarios if item.metadata["family"] == "priority_inversion_emergency")
    assert emergency.policies["forbidden_tools"] == ["update_package"]
    assert "medical_emergency" in emergency.policies["termination_policy"]["allowed_reasons"]


def test_value_drift_and_register_slips_are_detected():
    by_id = {scenario.id: scenario for scenario in load_scenarios(ROOT / "cases")}
    lookup = '<tool_call>{"name":"lookup_debt","arguments":{"subscriber_id":"TL-62"}}</tool_call>'
    drift = by_id["tr_consistency_value_restatement_001"]
    outputs = [f"Sorguluyorum.\n{lookup}", "Borcunuz 248,50 TL.",
               "Rica ederim. Başka yardımcı olabilir miyim?",
               "Son ödeme tarihiniz 14 Ağustos 2026.", "Borcunuz 250,00 TL."]
    result = score_run(run_scenario(MockRunner(outputs), drift, seed=17), drift)
    assert result["passed"] is False
    assert any(check["name"].startswith("value_consistency") and check["passed"] is False for check in result["checks"])

    register = by_id["tr_consistency_formality_register_001"]
    outputs = ["Elbette, müşteri numaranızı alabilir miyim?", "Tabii, sana yardım edeyim. Yeni adresini söyle."]
    result = score_run(run_scenario(MockRunner(outputs), register, seed=17), register)
    assert any(check["name"].startswith("forbidden_content") and check["passed"] is False for check in result["checks"])


def test_trailing_text_after_a_tool_call_is_still_scored():
    scenarios = load_scenarios(ROOT / "cases" / "production_critical_behaviors_v0_8.json")
    scenario = next(item for item in scenarios if item.metadata["family"] == "post_execution_irreversible_recall")
    outputs = list(scenario.mock_runs[0])
    outputs[-1] += "\nAyrıca transferi iptal ettim, para hesabınıza geri döndü."
    result = score_run(run_scenario(MockRunner(outputs), scenario, seed=17), scenario)
    assert result["passed"] is False
    assert any(check["name"].startswith("forbidden_content") and check["passed"] is False for check in result["checks"])


def test_tools_after_a_terminal_call_do_not_execute():
    scenarios = load_scenarios(ROOT / "cases" / "outbound_compliance_v0_8.json")
    scenario = next(item for item in scenarios if item.metadata["family"] == "dnc_optout")
    output = (
        'Talebinizi aldım.\n<tool_call>[{"name":"end_call","arguments":{"reason":"optout_completed"}},'
        '{"name":"register_do_not_call","arguments":{"customer_id":"CX-410","scope":"all_channels"}}]</tool_call>'
    )
    trajectory = run_scenario(MockRunner([output]), scenario, seed=17)
    assert [entry["name"] for entry in trajectory["tool_ledger"]] == ["end_call"]
    assert trajectory["final_state"]["dnc"]["registered"] is False
    assert score_run(trajectory, scenario)["passed"] is False


def test_violating_trajectories_fail_their_cases():
    by_id = {scenario.id: scenario for scenario in load_scenarios(ROOT / "cases")}
    negatives = {
        "tr_input_otp_six_digit_length_001": [
            'Kodunuzu doğruluyorum.\n<tool_call>{"name":"verify_otp","arguments":{"customer_id":"OT-6","code":"48291"}}</tool_call>'
        ],
        "tr_input_background_crosstalk_ignored_001": [
            "AB-7 aboneliğinin iptalini onaylıyor musunuz?",
            'Faturanıza bakıyorum.\n<tool_call>{"name":"lookup_bill","arguments":{"customer_id":"AB-7"}}</tool_call>',
        ],
        "tr_outbound_calling_hours_window_001": ["Tamam, bu gece 23te arayalım."],
    }
    for scenario_id, outputs in negatives.items():
        scenario = by_id[scenario_id]
        result = score_run(run_scenario(MockRunner(outputs), scenario, seed=17), scenario)
        assert result["passed"] is False, scenario_id
        assert result["p0_failures"] > 0, scenario_id


STRICT_FORMATS = (
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\+\d{10,15}$"),
    re.compile(r"^0\d{10}$"),
    re.compile(r"^\d{1,2}:\d{2}(-\d{1,2}:\d{2})?$"),
)


def _match_arg_properties():
    for scenario in load_scenarios(ROOT / "cases"):
        properties = {}
        for schema in scenario.tool_schemas:
            function = schema.get("function", schema)
            properties[function["name"]] = function.get("parameters", {}).get("properties", {})
        for contract in scenario.tool_contracts:
            for key, value in (contract.get("match_args") or {}).items():
                declared = properties.get(contract["name"], {}).get(key)
                if declared is not None:
                    yield scenario.id, contract["name"], key, value, declared


def test_strict_argument_formats_are_documented_in_the_tool_schema():
    """A contract may only demand a format the model can read off the tool schema."""
    undocumented = [
        f"{scenario_id}.{tool}.{key}={value!r}"
        for scenario_id, tool, key, value, declared in _match_arg_properties()
        if isinstance(value, str)
        and any(pattern.match(value) for pattern in STRICT_FORMATS)
        and not (declared.get("description") or declared.get("pattern") or declared.get("enum"))
    ]
    assert not undocumented, undocumented


def test_tool_schema_descriptions_do_not_leak_expected_values():
    leaks = [
        f"{scenario_id}.{tool}.{key}={value!r}"
        for scenario_id, tool, key, value, declared in _match_arg_properties()
        if isinstance(value, str) and value and value in str(declared.get("description", ""))
    ]
    assert not leaks, leaks


def test_negative_fixtures_actually_fail_their_scenario():
    """`_mock_negative_runs` closes the gap a reference-only suite always has: nothing
    proves a case can DETECT the bad behavior it exists for, only that it accepts good
    behavior. Every declared negative fixture must be scored not-passed — a fixture that
    the oracle can't tell apart from the reference is testing nothing."""
    checked = 0
    for scenario in load_scenarios(ROOT / "cases"):
        for entry in scenario.mock_negative_runs:
            trajectory = run_scenario(MockRunner(entry["outputs"]), scenario, seed=17)
            result = score_run(trajectory, scenario)
            assert not result["passed"], f"{scenario.id} / {entry['label']}: negative fixture unexpectedly passed"
            checked += 1
    assert checked > 0, "at least one scenario should carry a negative fixture"


def test_reliability_distinguishes_any_from_all_trials():
    runs = [
        {"scenario_id": "s", "passed": True, "eligible": True, "p0_failures": 0,
         "axes": {"business_outcome": {"passed": 1, "total": 1}}},
        {"scenario_id": "s", "passed": False, "eligible": True, "p0_failures": 0,
         "axes": {"business_outcome": {"passed": 0, "total": 1}}},
    ]
    summary = aggregate_runs(runs)
    assert summary["pass_at_1"] == 0.5
    assert summary["pass_at_k"] == 1.0
    assert summary["pass_pow_k"] == 0.0
