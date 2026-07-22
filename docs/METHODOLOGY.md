# Methodology

## Unit of evaluation

The unit is a complete conversation execution trial. A trial begins from a declared database-like state and ends when the controlled user plan finishes, a terminal tool fires, or a turn bound is exceeded.

Each trajectory records user utterances, raw assistant outputs, normalized tool calls, tool results, logical latency, state before/after each mutation, simulator decisions, runtime events, and terminal status. Results therefore remain debuggable after scoring.

Each scenario also declares evidence-linked objectives. An objective has a human-readable intent, score axis, severity, and required milestones. Objectives are rollups over deterministic evidence rather than separately judged prose, so the benchmark can explain both *what the scenario targets* and *which observation proves it*.

## Controlled user

The user is a finite-state decision process. Case authors own facts, constraints, consent, and behavior branches. Wording variants are selected with a stable hash of scenario, seed, node, and visit count. A model cannot steer the simulator by asserting that an unavailable action succeeded; transitions can depend on observed assistant text or actual tool success/failure.

Off-flow nodes represent controlled interruptions, such as a side question, topic shift, or clarification. Each has an explicit main-flow resume target and the plan has a maximum detour budget. The simulator records both the detour and its intended resume point, so flow recovery is observable rather than inferred from prose.

## Executable environment

Every available tool needs an explicit contract. Contracts match declared arguments, return deterministic or sequenced results, and apply auditable state patches only on success. Unknown calls or unmatched arguments are execution errors—there is no permissive fallback.

Fault sequences enable reproducible timeout, unavailable-service, and partial-progress trials. Logical latency is kept separate from local wall-clock model latency.

## Oracle hierarchy

1. **Deterministic state and contract oracles** verify final state, tool arguments/results, sequence, terminal outcome, loops, and runtime thresholds.
2. **Milestone oracles** locate required user, assistant, tool, state, and terminal evidence on the timeline.
3. **Policy oracles** enforce prerequisite-before-action, forbidden tools/content, and tool-grounded action claims.
4. **Conversation heuristics** measure concise speech, question discipline, required language, and near-duplicate turns.

For long-horizon cases, flow oracles additionally verify exact assistant-step and user-turn depth, expected detour count, complete detour rejoin, required resume nodes, and a configurable re-ask bound. These measurements are emitted as `flow_metrics` in every scored run, including cases without a flow profile.

Subjective LLM judging is deliberately outside the release gate in `v0.8`. If added, it must be calibrated against multi-annotator human labels, blinded to model identity, versioned, and reported separately.

## Behavior-stress protocol

Behavior-stress cases change the user's decision state or interaction constraints after the call has started. The assistant must privilege the latest explicit intent, resolve conflicting identifiers before a lookup, minimize optional data collection, avoid duplicate side effects under pressure, and adapt pacing for accessibility needs. A mid-call speaker change is treated as a privacy boundary, not as implicit authorization.

These cases use deterministic milestones and state assertions rather than an open-ended personality score. A scenario is successful only when the updated user state is reflected in tool selection, arguments, policy order, final state, and grounded assistant claims.

## Call-center off-flow protocol

An off-flow event is a temporary departure from the primary operational script, not a new conversation. Examples include a caller asking to hold, introducing a secondary intent, changing notification channel, requesting and then retracting escalation, correcting a value during confirmation, or returning after a queue transfer.

Each public call-center case labels the interruption node, the exact resume checkpoint, known facts that must survive, and any stale intent or value that must be invalidated. Passing requires complete detour rejoin, no forbidden action, correct latest-value tool arguments, bounded clarification, and no scenario-specific re-ask of facts already present in the trajectory.

## End-call protocol

Call termination is evaluated as an executable action, not a phrase-matching heuristic. A scenario declares whether the end-call tool is forbidden, optional, or required; its allowable reason codes; the evidence that must precede it; and a maximum call count.

Negative cases target common false-closing signals: mid-task thanks, temporary hold, off-topic detours, one-time frustration, and recoverable tool failure. Positive cases prevent the opposite failure mode by requiring termination after explicit user request, completed handoff, or grounded task completion. Reports expose raw end-call indices and reasons so an early termination can be distinguished from a missing or incorrectly coded termination.

## Long-horizon flow protocol

CEB separates horizon from event count: an assistant step is one parsed model response, a user turn is one emitted simulator utterance, and tool events are reported independently. The public flow pack targets exact assistant depths `{3, 5, 7, 12, 20}`. Its detours are semantically labelled and must rejoin the declared main-flow node immediately after the side issue is handled.

A long conversation does not pass merely by reaching the end. The run must also retain corrected facts, respect prerequisite and consent order, avoid redundant re-asks, execute the expected tool sequence, and reach the expected final state. This lets failures be attributed to horizon control, off-flow recovery, policy, or execution rather than collapsed into one subjective score.

## Severity and eligibility

- `P0`: safety, privacy, policy, or irreversible business-integrity failure. Any `P0` makes the trial ineligible.
- `P1`: required task, recovery, flow, or runtime failure. A trial does not pass.
- `P2`: experience-quality degradation. Reported on its axis but does not alone fail execution.

A passing trial has no `P0` or `P1` failures. The release gate can independently require minimum axis scores.

## Reliability

For `k` trials per scenario:

- `Pass@1`: successful trials divided by all trials;
- `Pass@k`: fraction of scenarios with at least one successful trial;
- `Pass^k`: fraction of scenarios where all `k` trials succeed.

`Pass^k` is the production-oriented measure: one intermittent unsafe or incorrect execution fails scenario reliability.

## Dataset governance

A mature release should maintain three partitions:

- **public development** cases and reference trajectories;
- **private test** cases with the same published schema and rubric;
- **fresh production-derived** cases refreshed on a fixed cadence after privacy review and de-identification.

Case authors, reviewers, and model developers should be separated where possible. Every case needs provenance, expected outcome, policy rationale, executable contracts, and a review history. Report contamination controls and version hashes with leaderboard results.

## Audio protocol

Runtime/audio metrics use timestamped events: user speech end, agent speech start/stop, user barge-in, and tool call start/end. CEB derives user-to-agent turn latency, barge-in stop latency, unbridged tool wait, and tool dead air. Absent observations are `not observed`, never silently treated as passes.

Real-audio comparisons must also declare codec, sample rate, channel count, loudness normalization, noise/SNR, accent cohort, ASR/TTS stack, geography, and network conditions.
