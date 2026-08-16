# Changelog

All notable changes to CEB are documented here. Case meaning, oracle semantics, default trials, and release-gate changes are explicitly marked when they affect score comparability.

The project follows semantic versioning for software interfaces. Benchmark comparability additionally depends on the case-pack version and git commit SHA.

## [Unreleased]

### Added

- Default public evaluation grows from 83 to **208 scenarios across 207 distinct domains**, in twenty-seven case packs
- `behavior_gaps`, `call_conduct`, `consistency_deep`, `consistency_hard`, `hard_ux`, `parallel_traps`, `phone_ux`, `realtime_findings`, and `turkish_callcenter_hard` packs
- `long_call` and `scope_ladder` packs give the suite a deliberate call-length spread. The production transcripts this suite is mined from run a median of 11 turns while the suite ran a median of 3, so constraint decay had no room to appear. One case runs 22 turns; a ladder repeats one confirmed defect at 3, 5 and 11 turns so length is measured as its own variable
- `chaos` and `composition` packs. Four controlled probes established that this model's failures are **compositional** — neither flow length, nor semantically adjacent steps, nor a vague opener, nor the post-tool generation slot, nor a contentless confirmation turn reproduces on its own what a genuinely messy call does. The composition cases therefore stack three to five traps that each pass individually, so any failure is attributable to composition alone
- `common_behaviors` and `common_behaviors_2`: twenty everyday caller behaviours, one per case, with a test asserting the two packs share no family so the second cannot drift into paraphrases of the first
- `constraint_scope` pack: a restriction must bind only what it names, tested on the channel, object and person axes
- `cross_domain` pack carries failure modes with no banking equivalent — an allergen the data does not cover while a severe allergy is stated, a dosing question that is medical advice, and a brake fault the caller wants booked two weeks out
- `off_script` pack leaves one user-plan turn with no step in the flow the model receives, so improvisation is measured rather than assumed. Fluency is scored through its observable proxies: stays in role, invents no capability, returns to the pending task
- `loop_and_carry` and `premise_and_compound` packs: the two everyday shapes that produce a repetition loop, information hand-off across a whole call, a false premise asserted as settled background, and a compound request whose halves carry different permission levels
- `user_plan.impatience`: the caller now reacts to the agent's OWN silence. Latency was measured but never fed back into the conversation, so a four-second pause — routine in the live sweeps — cost nothing, and the simulator waited forever. After a declared pause the caller asks whether anyone is there, and the agent has to confirm its presence and resume rather than ignore the question or restart its query. `_mock_latencies` lets a fixture declare its own timing so this stays reproducible instead of tracking the speed of whatever machine runs the mock, and `conversation.max_dead_air_prompts` lets a case say how much silence it tolerates
- `user_plan.abandon_when`: the caller now hangs up on an agent that repeats a contentless holding phrase, scored as a P1 `customer_did_not_abandon` check. 43 of 178 real calls ended exactly that way, and the suite previously had no notion of the customer abandoning
- TOON system-prompt format for authoring scenario flows (`src/ceb/toon.py`, `src/ceb/patterns.py`)
- Self-contained interactive HTML report renderer (`src/ceb/report.py`) with filter/search/expand/CSV export, written automatically alongside every JSON report
- Static case auditor (`tools/audit_cases.py`) catching self-inconsistent rules: a forbidden-content regex that matches the case's own reference answer, a rule no negative fixture exercises, a milestone the reference transcript never satisfies, or a behavioural phrase hand-written where a canonical shared pattern already owns it
- `benchmark.release.json` — a release-gate manifest calibrated from measured live sweeps, distinct from `benchmark.json`'s deterministic mock self-test gate
- `--concurrency` flag on the CLI for parallel live sweeps
- `phone_ux` pack: phone-appropriate UX for requesting/collecting numbers and codes over voice — agent-initiated pacing, interrupted-code self-correction, masked-ID readback under repeated pressure, sequential no-overload credential collection, backchannel-repeat deduplication, disguised-correction detection, sustained multi-interjection accumulation, and natural tens-compound number-word parsing
- `realtime_findings` pack extended with six cases mined from real production test transcripts: an identity-verification loop overriding a medical emergency, spontaneous persona reinvention abandoning a live crisis, weekday-name arithmetic hallucination, an outage report misrouted to the billing tool with fabricated cause/ETA, a transfer veto ignored via a repeated canned line, and a fabricated operational detail answering a legitimate no-data question
- `parallel_traps` pack: cases holding several unrelated policy/action disciplines live in the same call, so passing requires all of them at once

### Changed

- README now documents what the simulated caller does, not just how many scenarios exist: a section on the caller reacting to dead air and hanging up on a stalling agent, and caller-reaction metrics in the list of what a report contains. The gate paragraph cites a measurement that was actually taken rather than one that predates most of the current suite, and says plainly that the figure should be expected to fall as coverage grows

### Fixed (case quality)

- `$refusal` covered 6 of 12 common Turkish inability inflections, so a correct refusal phrased as "iletemiyorum" instead of "iletemem" was scored as a failure. It now models the -(y)Ama/-(y)Eme suffix once over a closed list of refusal verbs: 17 of 17 forms, no false positives. Two constraint-decay cases went 0/8 to 10/10 live with no change to the model
- 7 of 254 negative fixtures proved nothing: they failed no differently than simply truncating the correct run to the same length, so they demonstrated that the conversation stopped early rather than that the case detects the behaviour they are named for. Each now trips a rule that catches its behaviour directly, and `tools/audit_cases.py` gained a permanent check comparing every fixture against the truncated reference so this cannot come back
- The auditor's own canonical-pattern check split shared patterns on every `|`, so once `$refusal` contained a group of verb stems it began reporting bare stems as phrases a case had hand-written. It now splits at the top level only

### Measured

- Full live sweep of the 208-case suite against `callingai-qwen35-9b-v2`: **80.9% Pass@1, 85.5% Pass@k, 81.6% Pass^k** over 729 runs, against 90.0% / 87.7% on the earlier 162-case suite. The decline is the intended effect of packs aimed at known weaknesses, not a regression in the model
- The sweep flagged 8 runs as `wording_only_suspect`. Both scenarios were reviewed against their transcripts and both are genuine model defects rather than narrow regexes: one refuses the account holder their own balance, and the other drops the "the data is not recorded" half of an explicit two-part safety instruction in all five runs, with identical wording every time

### Fixed

- Regex-too-narrow case bugs found via live sweeps against `callingai-qwen35-9b-v2`, verified independently against captured transcripts before widening
- `read_only_tools` policy plus an independent `early_tool_call` check, closing a turn-scoped matching gap where an early tool call could permanently break a node's transition
- 33 hand-written behavioural regexes now delegate to the canonical shared patterns that already own them, so widening one reaches every case instead of one case at a time
- Several cases split information a competent agent says in one breath across two steps, which scored good service as racing ahead. The affected cases went from 0/5 to 5/5 live with no change to the model; the rule is now that a follow-up a human would volunteer unasked belongs to the same step
- Several content milestones matched the right string in the wrong turn — a value stated legitimately earlier also satisfied a late-call check, so fixtures that never performed the late behaviour still passed. Late-call milestones are now anchored on wording unique to their turn

### Known model findings (left undisturbed)

These reproduce against `callingai-qwen35-9b-v2` and are deliberately **not** worked around in the cases:

- Repetition stall: after two good simplifications the model tries to close on a still-confused caller, then repeats one sentence verbatim until the caller hangs up
- An emotional disclosure pushes it into executing an irreversible action before the confirmation its own flow requires, then executing it again
- A restriction naming one person is generalised to everyone, so the account holder is refused their own balance
- Two sources disagreeing is resolved silently in favour of the first, without querying the second
- A safety warning is delivered correctly and the action it requires is never completed
- Undeclared tools are invented, and a fabricated system-slowness excuse covers the gap
- Completed mutations are repeated after the closing
- A date confirmed with the caller in Turkish is converted to ISO with a year the conversation never contained; one run emitted template placeholders as argument names
- In a 22-turn chaotic call the model delivers a later step's answer before its trigger and desynchronises by turn 4

### Planned

- Additional domains and multilingual cases
- Public audio perturbation assets
- Realtime full-duplex transport adapters
- Versioned submission and result-card protocol

## [0.8.0] - 2026-07-22

Initial public release.

### Included

- Executable scenario schema and stateful tool environment
- Controlled, seedable multi-turn user simulator
- Deterministic business, policy, action, flow, recovery, conversation, termination, and runtime oracles
- `Pass@1`, `Pass@k`, strict `Pass^k`, and severity-aware release gates
- Evidence-linked scenario objectives surfaced in every scored report
- Configurable `termination_policy` with forbidden/optional/required modes, reason allowlists, prerequisite milestones, call-count bounds, and severity
- Per-run termination metrics including call count, reasons, timeline indices, terminal tool, and ended-by-end-call status
- Auditable flow metrics for steps, turns, detours, rejoins, re-asks, tool calls, and visited nodes
- Bounded off-flow user-plan nodes with explicit resume and fallback targets, including detours nested inside detours and a `max_off_flow_span` nesting metric
- `forbidden_args` action requirements for proving that optional sensitive fields were not collected or sent
- Scenario-specific re-ask detection for facts that should survive an interruption or transfer
- OpenAI-compatible model adapter and command-line runner
- Default public evaluation of 83 scenarios / 249 runs across 82 distinct domains, in fourteen case packs: pilot, safety, diversity, long-horizon flow, behavior stress, call-center off-flow, end-call boundaries, production-critical behaviors, outbound compliance, input robustness, nested flow, consistency, Turkish language, and channel discipline
- Methodology, schema reference, scenario-diversity taxonomy, contribution guide, CI workflow, machine-readable citation metadata, tests, and deterministic reference fixtures
