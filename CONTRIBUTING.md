# Contributing to CEB

Thanks for helping make conversational-agent evaluation more rigorous. CEB accepts focused contributions to cases, model adapters, deterministic oracles, runtime instrumentation, tests, and documentation.

## Before opening a pull request

1. Search existing issues and pull requests for related work.
2. Open an issue first for new benchmark axes, schema changes, or compatibility-breaking behavior.
3. Keep one pull request focused on one reviewable outcome.
4. Explain whether the change affects score comparability.

## Development setup

```bash
git clone https://github.com/sirius-tedarik/Conversation-Execution-Benchmark.git
cd Conversation-Execution-Benchmark
python -m pip install -e ".[dev]"

python -m compileall -q src
pytest
ceb --mock --out reports/reference.json
```

All three commands must pass before review.

## Contributing a case

Cases are executable specifications, not prompt-only examples. Every case must include:

- a stable, descriptive, globally unique ID;
- provenance and split metadata;
- explicit objectives linked to required milestone evidence;
- a controlled user plan with facts and decisions owned by the case;
- an exact tool allowlist, schemas, and executable contracts;
- initial state and an expected final-state subset;
- policy prerequisites and severity-labelled milestones;
- deterministic recovery behavior when a fault is in scope;
- at least three trials and focused regression tests;
- no real customer data, credentials, private policy text, or hidden-test answers.

Use [`docs/CASE_SCHEMA.md`](docs/CASE_SCHEMA.md) as the field reference and [`cases/pilot_v0_8.json`](cases/pilot_v0_8.json) as a working example.

Before creating a new scenario, use [`docs/SCENARIO_TAXONOMY.md`](docs/SCENARIO_TAXONOMY.md) to identify the new or underrepresented diversity cell. Language-only paraphrases belong in a node's `variants`, not in a new scenario.

## Review principles

Reviewers will check that:

- the case distinguishes model behavior rather than rewarding one exact phrasing;
- success can be decided from trajectory evidence;
- state mutations occur only through successful declared tools;
- policy prerequisites are observable before the protected action;
- `P0`, `P1`, and `P2` severities match the published methodology;
- reference fixtures prove harness behavior without leaking private evaluation data;
- documentation and changelog entries cover user-visible or comparability-impacting changes.

Changes to case meaning, oracle semantics, default trials, or release gates require a benchmark version decision. Do not silently change scores under an existing version.

## Pull requests

Include:

- the problem and intended outcome;
- the affected track, cases, or axes;
- commands used for validation;
- an example report or failure excerpt when scoring changes;
- a compatibility note: `none`, `backward compatible`, or `score breaking`.

By contributing, you agree that your contribution is licensed under Apache-2.0.
