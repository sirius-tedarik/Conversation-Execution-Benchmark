# Case schema (`benchmark_version: 0.8`)

Cases are JSON objects. A JSON file may contain one object or an array; JSONL is also supported.

## Required core fields

| Field | Meaning |
|---|---|
| `id` | Stable globally unique case ID |
| `benchmark_version` | Currently `0.8` |
| `user_plan` | Controlled user finite-state plan |
| `objectives` | Evidence-linked scenario goals |
| `available_tools` | Exact tool allowlist |
| `tool_contracts` | Executable results and state effects |

`tool_schemas`, when present, must name exactly the same tools as `available_tools`.

## User plan

```json
{
  "start": "request",
  "nodes": [
    {
      "id": "request",
      "variants": ["I need an appointment."],
      "transitions": [
        {"when": {"assistant_regex": "identity"}, "to": "identity"}
      ]
    },
    {
      "id": "identity",
      "variants": ["My date of birth is ..."],
      "terminal": true
    }
  ]
}
```

Supported transition predicates are `assistant_regex`, `tool_called`, `tool_succeeded`, `tool_failed`, and `no_tool_called`. The first matching transition wins.

### Off-flow and resume semantics

`user_plan.max_detours` is a non-negative bound on emitted off-flow nodes. A node can declare:

- `off_flow: true` to mark an interruption or side request;
- `resume_to` as the main-flow node used when no explicit transition matches;
- `fallback_to` as the normal node used when no explicit transition matches.

All targets must reference declared nodes. An off-flow node must have either `resume_to` or an explicit transition. Simulator traces retain `off_flow` and `resume_to`, allowing the scorecard to distinguish a genuine detour/rejoin from a merely long scripted conversation.

Detours may nest. A detour counts as rejoined when the conversation later reaches its declared `resume_to`; deeper off-flow nodes in between are skipped, and the check fails as soon as the conversation lands on a different main-flow node first. An inner detour therefore points its `resume_to` at the outer detour's return node, which makes reverse-order rejoin observable. `max_off_flow_span` reports the longest run of consecutive off-flow turns, so a nested case is distinguishable from a sequence of independent detours.

## Flow profile

The optional top-level `flow` object enables deterministic long-horizon checks:

```json
{
  "target_assistant_steps": 12,
  "target_user_turns": 6,
  "expected_detours": 2,
  "max_reasks": 0,
  "expected_off_flow_span": 1,
  "required_resume_nodes": ["target_plan", "consent"],
  "reask_regex": "tekrar söyler misiniz|yeniden söyler misiniz"
}
```

Step, turn, detour, and off-flow-span targets are exact. `all_detours_rejoined` and `required_resume_nodes` are P0 checks; depth and re-ask bounds are P1 checks. Every report exposes the observed values under `flow_metrics`, including assistant steps, user turns, tool calls, detours, rejoin rate, longest off-flow span, re-asks, and visited nodes.

For call-center cases, use a scenario-specific `reask_regex` to match already-known identity, case, or transaction fields. The initial collection question should not match this expression; reserve it for repeated requests such as “hesap numaranızı tekrar söyler misiniz”.

## Tool contracts

```json
{
  "name": "create_item",
  "match_args": {"item": "A"},
  "result": {"ok": true, "id": "I-1"},
  "state_patch": [{"op": "append", "path": "items", "value": {"id": "I-1"}}],
  "latency_ms": 200,
  "terminal": false
}
```

Use `sequence` instead of a single result for deterministic faults and retries. Supported state operations are `set`, `append`, `increment`, and `delete`. State patches apply only when the selected result succeeds.

## Milestones

Milestones have `id`, `kind`, `axis`, `severity`, and optional `required`. Kinds:

- `tool`: match `tool`, optional argument/result subset, and `failed` status;
- `content`: match `role` plus regular expression;
- `state`: match final-state `path` and exact `value`;
- `terminal`: match one of `tools`.

## Objectives

Objectives state why a case exists and bind that intent to observable evidence:

```json
{
  "id": "protect_sensitive_balance",
  "description": "Refuse balance disclosure when identity is not verified.",
  "axis": "policy_safety",
  "severity": "P0",
  "required_milestones": ["safe_refusal"]
}
```

Every case must declare at least one objective. Objective IDs must be unique, `axis` must be one of the seven published score axes, and every referenced milestone must be declared and required. The scorecard reports each objective as met or unmet plus its missing evidence. The underlying milestone checks remain the scoring source of truth, avoiding a second subjective objective judge.

## Policies and expectations

`policies` supports:

- `forbidden_tools`, `forbidden_content`;
- `tool_prerequisites` mapping a tool to milestone IDs that must occur earlier;
- `tool_requirements` for required, exact, and forbidden arguments;
- `claim_requires_tool` for successful-tool-before-claim grounding;
- `recovery_rules` mapping a failed tool to a later required milestone;
- `max_tool_repeats`.

### Termination policy

`policies.termination_policy` gives call-ending tools a dedicated deterministic contract:

```json
{
  "tool": "end_call",
  "mode": "required",
  "allowed_reasons": ["task_completed"],
  "required_milestones": ["mutation_succeeded", "completion_disclosed"],
  "max_calls": 1,
  "severity": "P0"
}
```

`mode` is `forbidden`, `optional`, or `required`. When the tool is called, every required milestone must occur earlier and its `reason` must be allowlisted. The oracle separately reports premature calls, missing required termination, invalid reasons, exceeded call count, and missing prerequisites. `tool` may be any declared provider-neutral name, including a production adapter's `endCall` alias.

`expected.state` is a recursive subset assertion, so observational fields may remain in actual state. `expected.tool_sequence` is an ordered required subsequence. `expected.terminal_tools` restricts allowed terminal outcomes.

## Runtime and mock fixtures

Keys beginning with `max_` in `runtime` become threshold checks. The shipped metrics are listed in `src/ceb/runtime.py`.

Fields prefixed `_mock_` are public reference fixtures, not model inputs:

- `_mock_runs`: deterministic assistant output sequences;
- `_mock_audio_events`: timestamped event fixtures.

Private benchmark packs should omit reference outputs.
