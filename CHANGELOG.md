# Changelog

All notable changes to CEB are documented here. Case meaning, oracle semantics, default trials, and release-gate changes are explicitly marked when they affect score comparability.

The project follows semantic versioning for software interfaces. Benchmark comparability additionally depends on the case-pack version and git commit SHA.

## [Unreleased]

### Added

- Nine new case packs — `behavior_gaps`, `call_conduct`, `consistency_deep`, `consistency_hard`, `hard_ux`, `parallel_traps`, `phone_ux`, `realtime_findings`, and `turkish_callcenter_hard` — growing default public evaluation from 83 to 160 scenarios across 159 distinct domains
- `phone_ux` pack: phone-appropriate UX for requesting/collecting numbers and codes over voice — agent-initiated pacing, interrupted-code self-correction, masked-ID readback under repeated pressure, sequential no-overload credential collection, backchannel-repeat deduplication, disguised-correction detection, sustained multi-interjection accumulation, and natural tens-compound number-word parsing
- `realtime_findings` pack extended with six cases mined from real production test transcripts: an identity-verification loop overriding a medical emergency, spontaneous persona reinvention abandoning a live crisis, weekday-name arithmetic hallucination, an outage report misrouted to the billing tool with fabricated cause/ETA, a transfer veto ignored via a repeated canned line, and a fabricated operational detail answering a legitimate no-data question
- `parallel_traps` pack: cases holding several unrelated policy/action disciplines live in the same call, so passing requires all of them at once
- TOON system-prompt format for authoring scenario flows (`src/ceb/toon.py`, `src/ceb/patterns.py`)
- Self-contained interactive HTML report renderer (`src/ceb/report.py`) with filter/search/expand/CSV export, written automatically alongside every JSON report
- Static case auditor (`tools/audit_cases.py`) catching self-inconsistent rules: a forbidden-content regex that matches the case's own reference answer, a rule no negative fixture exercises, or a milestone the reference transcript never satisfies
- `benchmark.release.json` — a release-gate manifest calibrated from measured live sweeps, distinct from `benchmark.json`'s deterministic mock self-test gate
- `--concurrency` flag on the CLI for parallel live sweeps

### Fixed

- Regex-too-narrow case bugs found via live sweeps against `callingai-qwen35-9b-v2`, verified independently against captured transcripts before widening
- `read_only_tools` policy plus an independent `early_tool_call` check, closing a turn-scoped matching gap where an early tool call could permanently break a node's transition

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
