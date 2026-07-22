# Changelog

All notable changes to CEB are documented here. Case meaning, oracle semantics, default trials, and release-gate changes are explicitly marked when they affect score comparability.

The project follows semantic versioning for software interfaces. Benchmark comparability additionally depends on the case-pack version and git commit SHA.

## [Unreleased]

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
