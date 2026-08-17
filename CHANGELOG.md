# Changelog

All notable changes to CEB are documented here. Case meaning, oracle semantics, default trials, and release-gate changes are explicitly marked when they affect score comparability.

The project follows semantic versioning for software interfaces. Benchmark comparability additionally depends on the case-pack version and git commit SHA.

## [Unreleased]

### Added

- Default public evaluation grows from 83 to **270 scenarios across 269 distinct domains**, in forty-seven case packs
- `transcript_mined` pack: eight cases read straight off the production call export (`gorusmeler (5).csv`, 178 reviewed calls) for behaviours the suite had no family for. An agent that contradicts its own tool result — the requested slot is in `available_slots` and it reports the day as full; a figure the caller REJECTED committed to the tool while the consent is narrated onto it; a credential correction that is answered with the identical block sentence instead of being merged and retried; a consent asked a second time after the caller already said yes; a format rule the agent states and then breaks itself; a prompt TEMPLATE's placeholder identity sent as a tool argument while the caller is addressed by her real name; a daypart re-questioned after the caller already supplied it; and a survey reopened on a caller who said they were in a meeting, after the callback was already booked
- `transcript_mined_2` pack, from a second pass over the same export, targeting the harder shapes: a hallucination that SURVIVES two explicit corrections and is then defended with a freshly invented constraint; a tool-grounded weekday abandoned the moment the caller (wrongly) disputes it, replaced by a new guess each turn; a financial claim affirmed before the billing record is read and then written into the case as fact; an emergency transfer gated behind a permission turn; and a prompt template's placeholder name used for a caller who never gave one, then denied in the same call
- `everyday_ux` pack, written after measuring that the suite's two UX levers were non-binding: real assistant turns run a median of 17 words against caps of 45–60, and 1% of turns carry two questions against a cap of one, so neither ever fires. Only 30 of 239 objectives were UX-primary and all 101 UX milestones were phrase-presence checks. The pack adds the structural behaviours the production reviewers actually flag — a hedged refusal pushed a second time, information re-asked after the caller already gave it, a direct question left unanswered while the flow advances, unrequested boilerplate recited mid-call, a stated preference not used to filter what is offered, closing without checking for anything else, its exact mirror where the same question is the defect because the caller already signalled the end, and telling a caller their wording was odd
- `production_flow_rules` pack, read out of the `akış` column of the same export — the production flows' own definitions, 437 distinct nodes across 26 scenario types, of which 234 are `global_note` rules the suite had never been checked against. Five of those rules had no case: a five-field intake taken strictly one at a time and read back in full before the write; an agent forbidden from using pressure or manufactured urgency; a recall that is free, where naming any figure — including an estimate under repeated insistence — is the violation; a safety defect that must stay at its general category instead of gaining an invented part, mechanism or statistic; and a mains-powered medical device that reclassifies a routine outage notification into a priority case with a priority callback, a whole parallel branch the production flow runs 19 times and the suite did not model
- Simulated Turkish speech-to-text on the caller's side (`ceb --stt light|moderate|heavy`, `src/ceb/stt.py`). Nine operators drawn from what a recogniser actually produces — fillers, eaten word-final syllables, lost punctuation, stutters, a clipped onset, re-spaced digit runs, the question particle split from its host, room speech appended to the turn, and near-homophone numbers — every decision a hash of the seed, so a failure found under noise replays exactly. A tenth operator, `drop_negation`, inverts the caller's meaning and is quarantined out of every graded profile: no agent can recover it from the text, and grading an ordinary case under it would measure luck. Nodes may pin their own profile, or `null` to stay clean under a suite-wide sweep, which is what lets a case corrupt exactly the turn its trap needs
- User-role content milestones now read what the caller SAID rather than what the transcript preserved. Without that, running any sweep with `--stt` failed ninety-odd consent checks because "Olur." had been clipped to "lur" — a harness artifact that would have read as the model losing consent discipline under noise
- `stt_hard` pack: nine cases where the transcription error IS the trap, each built so the model is never asked to undo it — only to notice and confirm. A negation eaten out of a sentence that then contradicts itself; a backchannel read as consent for an irreversible action; a clipped, crosstalked turn ahead of an account closure; a number word that is not a number; room speech answered as if it were the question; two failed attempts that should change the channel rather than earn a third ask; the agent's own sentence echoed back by a speakerphone; silence read as agreement; and keypad tones landing in the transcript as an identifier
- The caller's turn stops being one complete sentence from one known speaker. A `user_plan` node may declare `fragments`, delivered as consecutive `user` messages with a model invocation after each — which is how speech-to-text reaches the chat template in production, incomplete messages included. Responses to a non-final fragment are scored separately: calling a tool there is a P0, and an interim reply over `conversation.max_interim_words` is a P1, because a short backchannel while the caller is still talking is good service and acting on half a sentence is not
- `barge_in` cuts what the caller HEARD of the agent's last sentence while leaving the model's own history whole, since nothing in a full-duplex line tells the model where it was cut. A content milestone may score `against: "heard"`, which makes "the caller was told the reference number" a claim about the caller rather than about what was emitted
- `speaker` marks who is holding the handset, and `policies.holder_only_content` stops account-specific disclosure the moment it changes hands. An `agent_overlap` transcription operator splices the agent's own words into the caller's turn, which is what a recogniser does when both parties speak at once
- `fragmented_turns`, `barge_in` and `handover_and_overlap` packs — nine cases on those mechanisms. The centrepiece is a caller who says "Aboneliğimi iptal edin" and then "...meyin, sadece dondurun": the first message is grammatical, unambiguous and complete, and acting on it cancels a subscription the caller explicitly asked to keep. That shape also makes some of the suite's recorded premature-recitation findings ambiguous — on a complete utterance the model looks undisciplined, on a fragment it looks reasonable, and until now only the former was ever delivered
- A trajectory-shape snapshot (`tools/snapshot_trajectories.py`, `tests/fixtures/trajectory_shapes.json`) hashes every case's mock timeline. It was taken before the turn loop was rewritten and caught a real regression on the first task that could produce one: routing delivery through the new fragment list quietly un-corrupted five `stt_hard` cases while the mock sweep stayed green at 100% and the gate still said PASS
- The flow metric counted user MESSAGES as caller turns, so a three-fragment utterance read as three turns. Fragments of one utterance are one turn
- `behavior_gaps`, `call_conduct`, `consistency_deep`, `consistency_hard`, `hard_ux`, `parallel_traps`, `phone_ux`, `realtime_findings`, and `turkish_callcenter_hard` packs
- `long_call` and `scope_ladder` packs give the suite a deliberate call-length spread. The production transcripts this suite is mined from run a median of 11 turns while the suite ran a median of 3, so constraint decay had no room to appear. One case runs 22 turns; a ladder repeats one confirmed defect at 3, 5 and 11 turns so length is measured as its own variable
- `chaos` and `composition` packs. Four controlled probes established that this model's failures are **compositional** — neither flow length, nor semantically adjacent steps, nor a vague opener, nor the post-tool generation slot, nor a contentless confirmation turn reproduces on its own what a genuinely messy call does. The composition cases therefore stack three to five traps that each pass individually, so any failure is attributable to composition alone
- `common_behaviors` and `common_behaviors_2`: twenty everyday caller behaviours, one per case, with a test asserting the two packs share no family so the second cannot drift into paraphrases of the first
- `constraint_scope` pack: a restriction must bind only what it names, tested on the channel, object and person axes
- `cross_domain` pack carries failure modes with no banking equivalent — an allergen the data does not cover while a severe allergy is stated, a dosing question that is medical advice, and a brake fault the caller wants booked two weeks out
- `off_script` pack leaves one user-plan turn with no step in the flow the model receives, so improvisation is measured rather than assumed. Fluency is scored through its observable proxies: stays in role, invents no capability, returns to the pending task
- `loop_and_carry` and `premise_and_compound` packs: the two everyday shapes that produce a repetition loop, information hand-off across a whole call, a false premise asserted as settled background, and a compound request whose halves carry different permission levels
- `recovery_shapes` and `booking_hard` packs. The recovery axis was exercised by 102 checks against 4000+ on the others, and every existing fault case was the same shape: a hard failure that clears on retry. The new ones are the shapes that were missing — a business rejection retrying cannot fix, a value that moves between the read and the write, a call that SUCCEEDS while flagging its own data as stale, and a retry budget that runs out and must escalate instead of looping. Booking adds difficulties beyond a past date: a calendar date that does not exist and must not be snapped to a nearby day, a slot taken between quoting and confirming, and a clash with an appointment the caller already has
- `outbound_reality` pack, after measuring that outbound had stalled at 16 of 215 cases while every case added in the recent expansion was inbound. Four situations that only exist because the agent placed the call: the data-source question every Turkish consumer asks an unsolicited caller, which is a KVKK obligation rather than an objection; a person reached at a bad moment, where pushing through is the behaviour every call-centre complaint describes; a scam suspicion, where the failure is an agent proving itself by asking for exactly what a scammer would; and a reassigned number, where the new holder's natural "who were you calling?" is when the previous customer's data leaks
- `common_gaps` pack: seven ordinary calls the suite had no family for. The first is the important one — every sycophancy case in the suite trains the agent to hold its line under pressure, and nothing tested the call where the record proves the CALLER right, so conceding is correct and resisting is the defect. A suite that only ever rewards resistance selects for exactly that over-correction. The rest are a refund redirected to an account that never paid, a self-identified child on the line, a caller asking whether the call is recorded, a death notification, an escalation demanded above the top tier, and a declined card
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
- Every case now carries at least one negative fixture, up from 104 of 208. A case without one shows only that it accepts correct behaviour, never that it can detect the defect it was written for, and the split was clean: every pack written after the practice was introduced had them, every pack from the initial release had none — including safety, production_critical and end_call_boundaries. 378 fixtures total, each confirmed failing, with a test that keeps the coverage from regressing
- 7 of 254 negative fixtures proved nothing: they failed no differently than simply truncating the correct run to the same length, so they demonstrated that the conversation stopped early rather than that the case detects the behaviour they are named for. Each now trips a rule that catches its behaviour directly, and `tools/audit_cases.py` gained a permanent check comparing every fixture against the truncated reference so this cannot come back
- The auditor read only spoken text when checking whether a `forbidden_content` rule is ever exercised, while `oracles.py` scans tool ARGUMENTS as well — a forbidden phrase smuggled into a tool call is as much a violation as one said aloud. Two rules had been reported as unexercised for that reason alone; the auditor now sees what the oracle sees
- The auditor's own canonical-pattern check split shared patterns on every `|`, so once `$refusal` contained a group of verb stems it began reporting bare stems as phrases a case had hand-written. It now splits at the top level only

### Measured

- Full live sweep of all 226 cases against `callingai-qwen35-9b-v2`: **76.8% Pass@1, 82.3% Pass@k, 78.3% Pass^k** over 822 runs. 11 of the 19 newly added cases fail, which is what packs aimed at known weaknesses are for
- The sweep makes one defect unmistakable: **the model cannot stop calling tools**. 98 of 191 failing runs trip the tool-loop or extra-generation check, and 39% end with a tool call as their final step — including closing turns, and including a forbidden tool invoked with a placeholder argument (`customer_id: "N/A"`) immediately after the model had twice refused the request correctly
- Full live sweep of 207 of the 208 cases against `callingai-qwen35-9b-v2` (the dead-air case landed after it): **80.9% Pass@1, 85.5% Pass@k, 81.6% Pass^k** over 729 runs, against 90.0% / 87.7% on the earlier 162-case suite. The decline is the intended effect of packs aimed at known weaknesses, not a regression in the model
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
