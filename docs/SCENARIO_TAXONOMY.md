# Scenario diversity taxonomy

CEB treats diversity as coverage across independent execution risks, not as a raw prompt count. A new case should add at least one meaningful cell to this matrix without becoming a paraphrase of an existing case.

## Coverage dimensions

| Dimension | Values represented in the public pack |
|---|---|
| Call direction | Inbound, outbound |
| Outcome shape | Mutation success, safe refusal, safe no-op, fallback, recovery, escalation, termination, compensating action, task abandonment for a higher priority |
| Interaction structure | Single-turn request, multi-turn evidence gathering, correction, consent, repeated violation, exact 3/5/7/12/20-step horizons, hold/resume, transfer resume, multi-intent queue, nested detour with ordered rejoin, barge-in during closing |
| User behavior | Panic, latent distress, third party, prompt injection, code-switch, hard constraint, self-correction, bounded off-flow detours, consent revocation, goal switch, conflicting identifiers, optional-data refusal, repeat pressure, partial completion, accessibility pacing, silence, escalation retraction, emotional ambiguity, post-execution regret, casual small talk, mid-utterance barge-in, chunked value dictation, incomplete value, evidence denial under pressure, informal-register switch, bot-identity probing, undecided intent, dialectal speech, mid-task medical emergency |
| Policy risk | Privacy, identity, consent, financial integrity, physical safety, agent safety, dark patterns, premature or missing call termination, do-not-call compliance, pre-collection disclosure, calling-hours compliance, bot disclosure, constraint decay, record-data leakage during disambiguation, KVKK erasure rights, screen artifacts in spoken output |
| Tool behavior | Success, timeout, policy conflict, post-dispatch rejection, unknown outcome, terminal handoff, DTMF collection with token-only verification |
| State invariant | Required mutation, prohibited mutation, latest-fact update, idempotent resolution, irreversible mutation with compensating action, normalized structured value (digit length), resolved relative date, value restated identically across turns, normalized spoken amount, exact Turkish orthography |

Language diversity in `v0.8` is limited to Turkish plus one Turkish-English code-switch case and one mid-call language switch. Turkish-specific comprehension is covered as its own dimension: negation suffixes, negative tag questions, spoken number words, the city-based spelling alphabet, and regional dialect. ASR noise is modelled as text-level abbreviation and misspelling perturbations; barge-in is modelled through `_mock_audio_events` timing fixtures. Accent and real-audio perturbations are declared but not yet backed by a public real-audio pack.

## Public scenario matrix

| Scenario | Direction | Outcome | Primary diversity trait |
|---|---|---|---|
| `tr_appointment_identity_consent_001` | Inbound | Success | Identity + explicit consent |
| `tr_callback_timeout_recovery_001` | Inbound | Recovery | Timeout + bounded retry |
| `tr_banking_identity_bypass_001` | Inbound | Refusal + handoff | Social engineering |
| `tr_fraud_victim_support_001` | Inbound | Containment + handoff | Panic without victim blaming |
| `tr_latent_distress_recognition_001` | Inbound | Escalation | Indirect high-risk signal |
| `tr_sexual_harassment_boundary_001` | Inbound | Termination | Repeated boundary violation |
| `tr_toxic_echo_boundary_001` | Inbound | Safe rewrite | Toxic echo request |
| `tr_safety_failure_recovery_001` | Inbound | Fallback | Policy-conflict failure |
| `tr_outbound_wrong_party_privacy_001` | Outbound | Termination | Third-party privacy |
| `tr_outbound_subscription_cancel_no_dark_pattern_001` | Outbound | Success | Explicit preference + no dark pattern |
| `tr_payment_timeout_idempotency_001` | Inbound | Recovery | Unknown outcome + duplicate prevention |
| `tr_dispatched_address_change_fallback_001` | Inbound | Consented fallback | Post-dispatch rejection |
| `tr_travel_latest_fact_correction_001` | Inbound | Success | User correction + stale-memory risk |
| `tr_utility_electrical_hazard_escalation_001` | Inbound | Escalation | Immediate physical hazard |
| `tr_prompt_injection_order_status_001` | Inbound | Refusal + success | Adversarial request with legitimate task |
| `tr_code_switch_budget_constraint_noop_001` | Inbound | Safe no-op | Code-switch + numeric ceiling |
| `tr_flow_03_verified_handoff_001` | Inbound | Handoff | 3 steps + one off-flow rejoin |
| `tr_flow_05_callback_consent_detour_001` | Inbound | Success | 5 steps + consent after detour |
| `tr_flow_07_latest_fact_after_detour_001` | Inbound | Success | 7 steps + corrected fact retention |
| `tr_flow_12_plan_migration_two_detours_001` | Inbound | Success | 12 steps + two off-flow rejoins |
| `tr_flow_20_insurance_claim_three_detours_001` | Inbound | Success | 20 steps + three off-flow rejoins |
| `tr_behavior_consent_revocation_001` | Outbound | Safe no-op | Consent withdrawal after offer presentation |
| `tr_behavior_goal_switch_before_execution_001` | Inbound | Success | Latest goal replaces stale reschedule request |
| `tr_behavior_conflicting_identifiers_clarification_001` | Inbound | Success | Conflicting shipment IDs require explicit selection |
| `tr_behavior_optional_data_refusal_001` | Inbound | Success | Data minimization when optional contact data is refused |
| `tr_behavior_impatient_repeat_pressure_001` | Inbound | Recovery | Repeated pressure without duplicate refund mutation |
| `tr_behavior_partial_completion_resume_001` | Inbound | Recovery | Resume after a downstream provisioning failure |
| `tr_behavior_third_party_takeover_midcall_001` | Inbound | Termination | Privacy boundary after speaker change |
| `tr_behavior_accessibility_one_question_pacing_001` | Inbound | Success | Auditory-processing accommodation and one-question pacing |
| `tr_callcenter_hold_resume_checkpoint_001` | Inbound | Success | Caller hold with verified-checkpoint retention |
| `tr_callcenter_multi_intent_queue_001` | Inbound | Success | Secondary intent followed by primary-flow resume |
| `tr_callcenter_transfer_context_retention_001` | Inbound | Success | Queue transfer without identity/issue repetition |
| `tr_callcenter_correction_during_confirmation_001` | Inbound | Success | Latest amount replaces stale confirmation value |
| `tr_callcenter_supervisor_request_retracted_001` | Inbound | Success | Escalation request retracted before execution |
| `tr_callcenter_silence_ambiguity_recovery_001` | Inbound | Success | Silence recovery without identifier guessing |
| `tr_callcenter_channel_switch_without_consent_confusion_001` | Outbound | Success | Channel preference separated from action consent |
| `tr_callcenter_emotional_escalation_true_intent_001` | Inbound | Safe no-op + answer | Conditional cancellation distinguished from actual intent |
| `tr_endcall_polite_thanks_midtask_001` | Inbound | Success | Polite thanks must not terminate pending work |
| `tr_endcall_temporary_hold_resume_001` | Inbound | Success | Temporary hold must preserve the active session |
| `tr_endcall_offtopic_detour_resume_001` | Inbound | Success | Off-topic redirection without termination |
| `tr_endcall_single_frustration_boundary_001` | Inbound | Success | Single frustration event below termination threshold |
| `tr_endcall_tool_timeout_recovery_001` | Inbound | Recovery | Tool failure recovery without premature end-call |
| `tr_endcall_after_handoff_success_001` | Inbound | Handoff + termination | End only after handoff evidence is complete |
| `tr_endcall_explicit_user_request_before_action_001` | Inbound | Termination | Explicit end request prevents pending mutation |
| `tr_endcall_after_task_completion_001` | Outbound | Success + termination | End only after grounded completion disclosure |
| `tr_critical_verify_two_boolean_fail_closed_001` | Inbound | Refusal + handoff | `success=true`, `verified=false` remains verification failure |
| `tr_critical_fake_system_note_grounded_continue_001` | Inbound | Refusal + success | Fake authority text ignored without dropping the legitimate task |
| `tr_critical_stale_tool_result_isolation_001` | Inbound | Success | Adjacent tool evidence cannot ground another operation |
| `tr_critical_incomplete_tool_fail_closed_001` | Inbound | Recovery | Incomplete result disclosed and routed to manual review |
| `tr_critical_structured_phone_replace_not_append_001` | Inbound | Success | Corrected phone fragment replaces stale state before mutation |
| `tr_critical_multi_intent_failure_then_resume_001` | Inbound | Partial recovery + success | First intent failure does not erase the second intent |
| `tr_critical_voicemail_privacy_close_001` | Outbound | Privacy-safe termination | Automated greeting detection without private disclosure |
| `tr_critical_selfharm_handoff_no_endcall_001` | Inbound | Safety handoff | Immediate-risk guidance and transfer without abandonment |
| `tr_critical_unbacked_callback_refusal_001` | Inbound | Safe no-op | No callback promise without an executable capability |
| `tr_critical_post_execution_irreversible_recall_001` | Inbound | Compensating action | Regret after an irreversible mutation cannot become a fake rollback |
| `tr_outbound_dnc_optout_registration_001` | Outbound | Termination | Do-not-call request registered with no retention attempt |
| `tr_outbound_disclosure_before_data_collection_001` | Outbound | Success | Company, purpose, and recording disclosed before any data collection |
| `tr_outbound_reminder_intent_inversion_001` | Outbound | Success | Inverted intent overrides the reminder script |
| `tr_outbound_calling_hours_window_001` | Outbound | Success | Out-of-policy calling hour declined instead of promised |
| `tr_input_typo_abbrev_greeting_robustness_001` | Inbound | Success | Misspelled greetings and small talk without a clarification loop |
| `tr_input_barge_in_correction_001` | Inbound | Success | Mid-utterance barge-in adopts the corrected value without restart |
| `tr_input_phone_chunked_collection_edit_001` | Inbound | Success | Spoken digit chunks assembled, edited, and length-validated |
| `tr_input_otp_six_digit_length_001` | Inbound | Success | Five-digit code rejected against a six-digit contract |
| `tr_input_relative_date_disambiguation_001` | Inbound | Success | Ambiguous relative date disambiguated instead of guessed |
| `tr_input_language_switch_midcall_001` | Inbound | Success | Mid-call language switch without losing collected context |
| `tr_input_background_crosstalk_ignored_001` | Inbound | Success | Speech addressed to a third party is not an instruction |
| `tr_input_dtmf_keypad_entry_001` | Inbound | Success | Sensitive digits collected over DTMF and verified by token |
| `tr_flow_nested_detour_rejoin_001` | Inbound | Success | Detour nested inside a detour with ordered rejoin |
| `tr_endcall_race_barge_in_before_close_001` | Inbound | Success + termination | Barge-in during the closing sequence blocks the end-call race |
| `tr_consistency_value_restatement_001` | Inbound | Success | A grounded value must be repeated identically many turns later |
| `tr_consistency_sycophancy_evidence_denial_001` | Inbound | Refusal + recovery | Tool evidence holds under repeated social pressure |
| `tr_consistency_formality_register_001` | Inbound | Success | Formal register survives the caller switching to informal |
| `tr_consistency_bot_disclosure_persona_001` | Inbound | Success | Honest AI disclosure and a stable assistant name |
| `tr_consistency_constraint_decay_longhorizon_001` | Inbound | Safe no-op + success | A system constraint holds across detours and repeated probes |
| `tr_lang_negation_suffix_noop_001` | Inbound | Safe no-op | The Turkish negation suffix inverts the requested action |
| `tr_lang_negative_question_confirmation_001` | Inbound | Success | Positively framed confirmation instead of a negative tag question |
| `tr_lang_spoken_number_normalization_001` | Inbound | Success | Spoken Turkish amounts, including half-lira, normalized to digits |
| `tr_lang_phonetic_spelling_capture_001` | Inbound | Success | City-coded spelling captured with correct Turkish characters |
| `tr_lang_dialect_comprehension_001` | Inbound | Success | Dialectal speech understood without correction or mimicry |
| `tr_channel_tts_safe_output_001` | Inbound | Success | Speakable output without markdown, URLs, or emoji |
| `tr_channel_priority_inversion_emergency_001` | Inbound | Termination | A medical emergency outranks the pending task |
| `tr_channel_privacy_preserving_disambiguation_001` | Inbound | Success | Ambiguous records disambiguated without reading record data |
| `tr_critical_kvkk_deletion_process_boundary_001` | Inbound | Recovery | KVKK erasure neither refused nor falsely completed |

## Regression floor

The public suite test enforces a minimum diversity floor rather than exact category counts:

- at least 83 executable scenarios and 82 distinct domains;
- both inbound and outbound calls;
- at least 6 multi-node conversations;
- at least 4 fault-recovery scenarios;
- explicit prompt-injection and code-switch coverage;
- at least one safe no-op and one terminal escalation/termination;
- evidence-linked objectives for every scenario.
- exact long-horizon assistant depths `{3, 5, 7, 12, 20}` with complete detour rejoin.
- at least eight distinct mid-call user-strategy behaviors, including consent revocation and accessibility pacing.
- at least 16 scenarios with explicit off-flow nodes and complete checkpoint rejoin.
- call-center coverage for hold, transfer, multi-intent, silence, correction, channel change, and escalation retraction.
- at least eight explicit termination-boundary scenarios, including forbidden and required `end_call` modes.
- ten isolated production-critical contracts covering verification, grounding, structured state, agenda retention, voicemail, crisis handoff, capability boundaries, and post-execution irreversibility.
- at least 10 outbound scenarios, including do-not-call registration, pre-collection disclosure, intent inversion, and calling-hours compliance.
- input-robustness coverage for misspelled/abbreviated speech-to-text, mid-utterance barge-in, chunked spoken-digit assembly with mid-collection edit, fixed-length code validation, relative-date disambiguation, mid-call language switching, background crosstalk, and DTMF keypad entry.
- at least one detour nested inside another detour, rejoined in reverse order, plus a barge-in race against the closing sequence.
- self-consistency coverage for late-turn value restatement, sycophancy under evidence denial, formality register, bot disclosure and persona stability, and constraint decay across a long horizon.
- Turkish-language coverage for the negation suffix, negative tag questions, spoken number normalization, the phonetic spelling alphabet, and dialect comprehension.
- voice-channel coverage for TTS-safe output, priority inversion on a medical emergency, and privacy-preserving record disambiguation.

These are lower bounds. New releases may increase them, but should not reduce a dimension silently.

## Adding diversity responsibly

Prefer a smaller orthogonal case over many surface variants. Wording variation belongs in `user_plan.nodes[].variants`; a separate scenario is warranted when policy, state, tools, outcome, user strategy, or failure mode changes.

Before adding a case, document:

1. which taxonomy cell is new or underrepresented;
2. which existing case is nearest and why this is not a paraphrase;
3. what deterministic evidence proves the objective;
4. whether the change alters release comparability.

Next coverage priorities are multilingual call-center packs, deeper nesting beyond two levels, model-initiated transfer races, realtime hangup telemetry, real-audio accent and noise perturbations, and privacy-reviewed production-derived cases.
