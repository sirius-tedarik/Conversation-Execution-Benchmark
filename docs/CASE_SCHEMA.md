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

`target_assistant_steps`/`target_user_turns` are exact and belong to long-horizon depth cases, where the point under test is the depth itself. For behavioral cases, prefer the ceiling form `max_assistant_steps`/`max_user_turns`: a model that resolves the task correctly in fewer steps than expected is not a defect, and an exact-match target scores an efficient recovery as a flow_control failure. Use `target_*` only when the exact count is itself the thing being verified.

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
- `tracked_values` for cross-turn value consistency (below);
- `read_only_tools` for early-tool-call tolerance (below);
- `max_tool_repeats`.

### Early tool calls and `read_only_tools`

A `user_plan` transition's `tool_called`/`tool_succeeded`/`tool_failed` condition is matched
against the current user turn only, by default — a tool call bundled into an *earlier* node's
turn (the model acting one node ahead of its trigger) can never satisfy a later node's
condition, and since that node has no fallback, the conversation ends early. This is a
deliberately strict default: it is exactly how the benchmark catches a model reciting or
acting on a later flow step before the customer has actually reached it.

For tools that are genuinely read-only (a query, not a mutation), that strictness can be
disproportionate: the model already did the work, has no reason to repeat it, and the
resulting collapse can zero out every downstream milestone even when the rest of the call
was handled correctly. Declaring a tool in `policies.read_only_tools` widens its matching
window to the whole session — a call made anywhere earlier now satisfies a later node's
condition, so the conversation continues instead of stranding.

This does not hide the early call. Every node visit records the timeline index at which it
became active; an `early_tool_call:<node>:<visit>:<tool>` check independently fails whenever
a read-only tool tagged to that node's own transition was called before that boundary —
regardless of whether the conversation went on to complete. A run can therefore finish every
milestone and still fail overall on this check alone. Only tools *not* listed here — the
default — keep the original strict, turn-scoped, no-early-credit behavior; this is opt-in
per scenario and changes nothing for a case that never declares it.

### Cross-turn value consistency

`policies.tracked_values` catches a value the model states once from a tool result — an
amount, a due date, a phone number — then restates differently later: rounded, reformatted,
or drifted toward a number the customer merely suggested. Each rule finds the value's first
grounding tool call, then scans every later assistant turn for a same-shaped restatement:

```json
{
  "tracked_values": [
    {"id": "debt_amount", "tool": "lookup_debt", "path": "amount_try", "kind": "currency_try", "severity": "P0"}
  ]
}
```

- `tool` / `path`: which successful tool result holds the ground-truth value (dotted path into the result object).
- `kind`: one of `currency_try` (e.g. `248,50 TL`), `date_tr_long` (e.g. `14 Ağustos`), `phone_intl` (E.164, `+` prefix required and checked), or `raw_exact` (author-supplied `shape_regex`, exact string match).
- `severity`: defaults to `P0` — a wrong restatement of a grounded fact is a trust failure, not a style nit.

A rule fires once per matching span in each assistant turn after the tool result; if no turn ever mentions a same-shaped value again, nothing fails — the check only triggers on an actual restatement. If the source tool never succeeds in a given trial, the check reports `passed: null` ("not observed this trial") rather than failing, the same convention `recovery_rules` uses for an untriggered fault.

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
