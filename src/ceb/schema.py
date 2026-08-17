"""Strict, dependency-free schema for CEB scenarios."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ScenarioValidationError(ValueError):
    """A scenario cannot be executed or scored deterministically."""


# Named value formats the cross-turn consistency oracle (oracles.py::_value_consistency_checks)
# knows how to canonicalize and re-detect in later assistant turns. Kept here, not in oracles.py,
# so schema validation and the oracle share one definition instead of drifting apart.
TRACKED_VALUE_KINDS = frozenset({"currency_try", "date_tr_long", "phone_intl", "raw_exact"})


def _require(mapping: dict[str, Any], key: str, expected_type: type, where: str) -> Any:
    if key not in mapping:
        raise ScenarioValidationError(f"{where}.{key} is required")
    value = mapping[key]
    if not isinstance(value, expected_type):
        raise ScenarioValidationError(
            f"{where}.{key}: expected {expected_type.__name__}, got {type(value).__name__}"
        )
    return value


def _validate_user_plan(plan: dict[str, Any], scenario_id: str) -> None:
    start = _require(plan, "start", str, f"{scenario_id}.user_plan")
    nodes = _require(plan, "nodes", list, f"{scenario_id}.user_plan")
    if not nodes:
        raise ScenarioValidationError(f"{scenario_id}.user_plan.nodes cannot be empty")
    ids: list[str] = []
    for index, node in enumerate(nodes):
        where = f"{scenario_id}.user_plan.nodes[{index}]"
        if not isinstance(node, dict):
            raise ScenarioValidationError(f"{where}: expected object")
        node_id = _require(node, "id", str, where)
        ids.append(node_id)
        if "variants" in node and "fragments" in node:
            raise ScenarioValidationError(f"{where}: declare variants or fragments, not both")
        if "fragments" in node:
            # One caller utterance delivered as several consecutive user messages, because that is
            # how speech-to-text reaches the chat template in production — and the model is
            # invoked on every one of them, including the unfinished ones.
            fragments = _require(node, "fragments", list, where)
            if len(fragments) < 2 or not all(isinstance(item, str) and item.strip() for item in fragments):
                raise ScenarioValidationError(
                    f"{where}.fragments must contain at least two non-empty strings"
                )
        else:
            variants = _require(node, "variants", list, where)
            if not variants or not all(isinstance(item, str) and item.strip() for item in variants):
                raise ScenarioValidationError(f"{where}.variants must contain non-empty strings")
        transitions = node.get("transitions", [])
        if not isinstance(transitions, list) or not all(isinstance(item, dict) for item in transitions):
            raise ScenarioValidationError(f"{where}.transitions must be list[object]")
        if "stt" in node and not isinstance(node["stt"], (str, dict, type(None))):
            raise ScenarioValidationError(f"{where}.stt must be a profile name, an operator map, or null")
    if len(ids) != len(set(ids)):
        raise ScenarioValidationError(f"{scenario_id}.user_plan has duplicate node ids")
    if start not in ids:
        raise ScenarioValidationError(f"{scenario_id}.user_plan.start is unknown: {start}")
    known = set(ids)
    max_detours = plan.get("max_detours", len(nodes))
    if not isinstance(max_detours, int) or max_detours < 0:
        raise ScenarioValidationError(f"{scenario_id}.user_plan.max_detours must be a non-negative integer")
    impatience = plan.get("impatience", {})
    if not isinstance(impatience, dict):
        raise ScenarioValidationError(f"{scenario_id}.user_plan.impatience must be an object")
    if impatience:
        after = impatience.get("after_ms")
        if not isinstance(after, (int, float)) or after <= 0:
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan.impatience.after_ms must be a positive number"
            )
        utterances = impatience.get("utterances", [])
        if not isinstance(utterances, list) or not all(
            isinstance(item, str) and item.strip() for item in utterances
        ):
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan.impatience.utterances must be non-empty strings"
            )
        prompts = impatience.get("max_prompts", 1)
        if not isinstance(prompts, int) or prompts < 1:
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan.impatience.max_prompts must be an integer >= 1"
            )
    abandon = plan.get("abandon_when", {})
    if not isinstance(abandon, dict):
        raise ScenarioValidationError(f"{scenario_id}.user_plan.abandon_when must be an object")
    if abandon:
        repeats = abandon.get("repeated_assistant_turns")
        if not isinstance(repeats, int) or repeats < 2:
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan.abandon_when.repeated_assistant_turns must be an integer >= 2"
            )
        similarity = abandon.get("similarity", 0.92)
        if not isinstance(similarity, (int, float)) or not 0 < float(similarity) <= 1:
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan.abandon_when.similarity must be a ratio in (0, 1]"
            )
    for node in nodes:
        if "off_flow" in node and not isinstance(node["off_flow"], bool):
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan node={node['id']}: off_flow must be boolean"
            )
        for transition in node.get("transitions", []):
            target = transition.get("to")
            if target is not None and target not in known:
                raise ScenarioValidationError(
                    f"{scenario_id}.user_plan node={node['id']}: unknown transition target {target}"
                )
        for key in ("resume_to", "fallback_to"):
            target = node.get(key)
            if target is not None and target not in known:
                raise ScenarioValidationError(
                    f"{scenario_id}.user_plan node={node['id']}: unknown {key} target {target}"
                )
        if node.get("off_flow") and not node.get("resume_to") and not node.get("transitions"):
            raise ScenarioValidationError(
                f"{scenario_id}.user_plan node={node['id']}: off_flow node requires resume_to or transitions"
            )


def _validate_flow(flow: dict[str, Any], user_plan: dict[str, Any], scenario_id: str) -> None:
    non_negative = ("expected_detours", "max_reasks", "expected_off_flow_span")
    positive = ("target_assistant_steps", "target_user_turns", "max_assistant_steps", "max_user_turns")
    for key in positive:
        value = flow.get(key)
        if value is not None and (not isinstance(value, int) or value <= 0):
            raise ScenarioValidationError(f"{scenario_id}.flow.{key} must be a positive integer")
    for key in non_negative:
        value = flow.get(key)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ScenarioValidationError(f"{scenario_id}.flow.{key} must be a non-negative integer")
    reask_regex = flow.get("reask_regex")
    if reask_regex is not None and not isinstance(reask_regex, str):
        raise ScenarioValidationError(f"{scenario_id}.flow.reask_regex must be a string")
    required_nodes = flow.get("required_resume_nodes", [])
    known_nodes = {node["id"] for node in user_plan["nodes"]}
    if (
        not isinstance(required_nodes, list)
        or not all(isinstance(node, str) for node in required_nodes)
        or not set(required_nodes) <= known_nodes
    ):
        raise ScenarioValidationError(
            f"{scenario_id}.flow.required_resume_nodes must contain known user-plan nodes"
        )
    resume_targets = {
        target
        for node in user_plan["nodes"]
        if node.get("off_flow")
        for target in (
            [node["resume_to"]] if node.get("resume_to") else []
        ) + [transition.get("to") for transition in node.get("transitions", []) if transition.get("to")]
    }
    if not set(required_nodes) <= resume_targets:
        raise ScenarioValidationError(
            f"{scenario_id}.flow.required_resume_nodes must be reachable from off-flow nodes"
        )
    expected_detours = flow.get("expected_detours")
    if expected_detours is not None and expected_detours > user_plan.get("max_detours", len(user_plan["nodes"])):
        raise ScenarioValidationError(
            f"{scenario_id}.flow.expected_detours exceeds user_plan.max_detours"
        )


def _validate_tool_contracts(contracts: list[Any], scenario_id: str, tools: set[str]) -> None:
    for index, contract in enumerate(contracts):
        where = f"{scenario_id}.tool_contracts[{index}]"
        if not isinstance(contract, dict):
            raise ScenarioValidationError(f"{where}: expected object")
        name = _require(contract, "name", str, where)
        if name not in tools:
            raise ScenarioValidationError(f"{where}.name={name} is not in available_tools")
        sequence = contract.get("sequence")
        if sequence is not None and (
            not isinstance(sequence, list) or not sequence or not all(isinstance(item, dict) for item in sequence)
        ):
            raise ScenarioValidationError(f"{where}.sequence must be non-empty list[object]")
        if sequence is not None and not all("result" in item for item in sequence):
            raise ScenarioValidationError(f"{where}.sequence entries must each declare a result")
        if sequence is None and "result" not in contract:
            raise ScenarioValidationError(f"{where}: result or sequence is required")


@dataclass(frozen=True)
class Scenario:
    id: str
    benchmark_version: str
    domain: str
    language: str
    call_direction: str
    system: str
    available_tools: tuple[str, ...]
    tool_schemas: tuple[dict[str, Any], ...]
    initial_state: dict[str, Any]
    tool_contracts: tuple[dict[str, Any], ...]
    user_plan: dict[str, Any]
    objectives: tuple[dict[str, Any], ...]
    milestones: tuple[dict[str, Any], ...]
    policies: dict[str, Any]
    expected: dict[str, Any]
    conversation: dict[str, Any]
    flow: dict[str, Any]
    runtime: dict[str, Any]
    perturbations: dict[str, Any]
    trials: int
    max_user_turns: int
    max_steps_per_turn: int
    mock_runs: tuple[tuple[str, ...], ...]
    mock_latencies: tuple[float, ...]
    mock_negative_runs: tuple[dict[str, Any], ...]
    mock_audio_events: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Scenario":
        if not isinstance(raw, dict):
            raise ScenarioValidationError("scenario must be an object")
        scenario_id = _require(raw, "id", str, "scenario")
        version = _require(raw, "benchmark_version", str, scenario_id)
        if version != "0.8":
            raise ScenarioValidationError(f"{scenario_id}.benchmark_version is unsupported: {version}")
        direction = raw.get("call_direction", "inbound")
        if direction not in {"inbound", "outbound"}:
            raise ScenarioValidationError(f"{scenario_id}.call_direction must be inbound|outbound")
        tools_raw = raw.get("available_tools", [])
        if not isinstance(tools_raw, list) or not all(isinstance(item, str) for item in tools_raw):
            raise ScenarioValidationError(f"{scenario_id}.available_tools must be list[str]")
        if len(tools_raw) != len(set(tools_raw)):
            raise ScenarioValidationError(f"{scenario_id}.available_tools contains duplicates")
        tool_schemas = raw.get("tool_schemas", [])
        if not isinstance(tool_schemas, list) or not all(isinstance(item, dict) for item in tool_schemas):
            raise ScenarioValidationError(f"{scenario_id}.tool_schemas must be list[object]")
        schema_names = {
            item.get("function", {}).get("name") if item.get("type") == "function" else item.get("name")
            for item in tool_schemas
        }
        if tool_schemas and schema_names != set(tools_raw):
            raise ScenarioValidationError(
                f"{scenario_id}.tool_schemas names must exactly match available_tools: {schema_names} != {set(tools_raw)}"
            )

        user_plan = _require(raw, "user_plan", dict, scenario_id)
        _validate_user_plan(user_plan, scenario_id)
        contracts = raw.get("tool_contracts", [])
        if not isinstance(contracts, list):
            raise ScenarioValidationError(f"{scenario_id}.tool_contracts must be a list")
        _validate_tool_contracts(contracts, scenario_id, set(tools_raw))

        milestones = raw.get("milestones", [])
        if not isinstance(milestones, list):
            raise ScenarioValidationError(f"{scenario_id}.milestones must be a list")
        milestone_ids: list[str] = []
        for index, milestone in enumerate(milestones):
            where = f"{scenario_id}.milestones[{index}]"
            if not isinstance(milestone, dict):
                raise ScenarioValidationError(f"{where}: expected object")
            milestone_ids.append(_require(milestone, "id", str, where))
            if _require(milestone, "kind", str, where) not in {"tool", "content", "state", "terminal"}:
                raise ScenarioValidationError(f"{where}.kind is unsupported")
            if milestone.get("severity", "P1") not in {"P0", "P1", "P2"}:
                raise ScenarioValidationError(f"{where}.severity must be P0|P1|P2")
        if len(milestone_ids) != len(set(milestone_ids)):
            raise ScenarioValidationError(f"{scenario_id}.milestones contains duplicate ids")

        objectives = _require(raw, "objectives", list, scenario_id)
        if not objectives:
            raise ScenarioValidationError(f"{scenario_id}.objectives cannot be empty")
        objective_ids: list[str] = []
        axes = {
            "business_outcome", "policy_safety", "action_correctness", "flow_control",
            "recovery", "conversation_experience", "runtime",
        }
        required_milestones = {
            milestone["id"] for milestone in milestones if milestone.get("required", True)
        }
        for index, objective in enumerate(objectives):
            where = f"{scenario_id}.objectives[{index}]"
            if not isinstance(objective, dict):
                raise ScenarioValidationError(f"{where}: expected object")
            objective_ids.append(_require(objective, "id", str, where))
            _require(objective, "description", str, where)
            if _require(objective, "axis", str, where) not in axes:
                raise ScenarioValidationError(f"{where}.axis is unsupported")
            if objective.get("severity", "P1") not in {"P0", "P1", "P2"}:
                raise ScenarioValidationError(f"{where}.severity must be P0|P1|P2")
            evidence = _require(objective, "required_milestones", list, where)
            if not evidence or not all(isinstance(item, str) for item in evidence):
                raise ScenarioValidationError(f"{where}.required_milestones must be non-empty list[str]")
            if not set(evidence) <= required_milestones:
                raise ScenarioValidationError(
                    f"{where}.required_milestones must reference required declared milestones"
                )
        if len(objective_ids) != len(set(objective_ids)):
            raise ScenarioValidationError(f"{scenario_id}.objectives contains duplicate ids")

        policies = raw.get("policies", {})
        if not isinstance(policies, dict):
            raise ScenarioValidationError(f"{scenario_id}.policies must be an object")
        prerequisites = policies.get("tool_prerequisites", {})
        if not isinstance(prerequisites, dict):
            raise ScenarioValidationError(f"{scenario_id}.policies.tool_prerequisites must be an object")
        for tool, required in prerequisites.items():
            if tool not in tools_raw or not isinstance(required, list) or not set(required) <= set(milestone_ids):
                raise ScenarioValidationError(f"{scenario_id}: invalid prerequisites for {tool}")
        read_only_tools = policies.get("read_only_tools", [])
        if not isinstance(read_only_tools, list) or not all(isinstance(item, str) for item in read_only_tools):
            raise ScenarioValidationError(f"{scenario_id}.policies.read_only_tools must be a list[str]")
        if not set(read_only_tools) <= set(tools_raw):
            raise ScenarioValidationError(f"{scenario_id}.policies.read_only_tools must be declared in available_tools")
        tracked_values = policies.get("tracked_values", [])
        if not isinstance(tracked_values, list):
            raise ScenarioValidationError(f"{scenario_id}.policies.tracked_values must be a list")
        tracked_value_ids: list[str] = []
        for index, rule in enumerate(tracked_values):
            where = f"{scenario_id}.policies.tracked_values[{index}]"
            if not isinstance(rule, dict):
                raise ScenarioValidationError(f"{where}: expected object")
            tracked_value_ids.append(_require(rule, "id", str, where))
            tool = _require(rule, "tool", str, where)
            if tool not in tools_raw:
                raise ScenarioValidationError(f"{where}.tool={tool} is not in available_tools")
            _require(rule, "path", str, where)
            kind = _require(rule, "kind", str, where)
            if kind not in TRACKED_VALUE_KINDS:
                raise ScenarioValidationError(f"{where}.kind must be one of {sorted(TRACKED_VALUE_KINDS)}")
            if kind == "raw_exact" and not isinstance(rule.get("shape_regex"), str):
                raise ScenarioValidationError(f"{where}.shape_regex is required when kind=raw_exact")
            if rule.get("severity", "P0") not in {"P0", "P1", "P2"}:
                raise ScenarioValidationError(f"{where}.severity must be P0|P1|P2")
        if len(tracked_value_ids) != len(set(tracked_value_ids)):
            raise ScenarioValidationError(f"{scenario_id}.policies.tracked_values contains duplicate ids")

        termination = policies.get("termination_policy", {})
        if not isinstance(termination, dict):
            raise ScenarioValidationError(f"{scenario_id}.policies.termination_policy must be an object")
        if termination:
            termination_tool = termination.get("tool", "end_call")
            if termination_tool not in tools_raw:
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy.tool must be in available_tools"
                )
            if termination.get("mode", "optional") not in {"forbidden", "optional", "required"}:
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy.mode must be forbidden|optional|required"
                )
            required = termination.get("required_milestones", [])
            if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy.required_milestones must be list[str]"
                )
            if not set(required) <= set(milestone_ids):
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy references unknown milestones"
                )
            reasons = termination.get("allowed_reasons", [])
            if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy.allowed_reasons must be list[str]"
                )
            max_calls = termination.get("max_calls", 1)
            if not isinstance(max_calls, int) or max_calls < 0:
                raise ScenarioValidationError(
                    f"{scenario_id}.policies.termination_policy.max_calls must be a non-negative integer"
                )

        values: dict[str, Any] = {}
        for key in ("initial_state", "expected", "conversation", "flow", "runtime", "perturbations", "metadata"):
            value = raw.get(key, {})
            if not isinstance(value, dict):
                raise ScenarioValidationError(f"{scenario_id}.{key} must be an object")
            values[key] = value
        _validate_flow(values["flow"], user_plan, scenario_id)
        positive_ints = {
            "trials": raw.get("trials", 3),
            "max_user_turns": raw.get("max_user_turns", 12),
            "max_steps_per_turn": raw.get("max_steps_per_turn", 6),
        }
        for key, value in positive_ints.items():
            if not isinstance(value, int) or value <= 0:
                raise ScenarioValidationError(f"{scenario_id}.{key} must be a positive integer")
        mock_latencies = raw.get("_mock_latencies", [])
        if mock_latencies and (
            not isinstance(mock_latencies, list)
            or not all(isinstance(item, (int, float)) for item in mock_latencies)
        ):
            raise ScenarioValidationError(f"{scenario_id}._mock_latencies must be list[number]")
        mock_runs = raw.get("_mock_runs", [])
        if mock_runs and (
            not isinstance(mock_runs, list)
            or not all(isinstance(run, list) and all(isinstance(item, str) for item in run) for run in mock_runs)
        ):
            raise ScenarioValidationError(f"{scenario_id}._mock_runs must be list[list[str]]")
        negative_runs = raw.get("_mock_negative_runs", [])
        if negative_runs and not isinstance(negative_runs, list):
            raise ScenarioValidationError(f"{scenario_id}._mock_negative_runs must be a list")
        for index, entry in enumerate(negative_runs):
            where = f"{scenario_id}._mock_negative_runs[{index}]"
            if not isinstance(entry, dict):
                raise ScenarioValidationError(f"{where}: expected object")
            _require(entry, "label", str, where)
            outputs = _require(entry, "outputs", list, where)
            if not all(isinstance(item, str) for item in outputs):
                raise ScenarioValidationError(f"{where}.outputs must be list[str]")
        audio_events = raw.get("_mock_audio_events", [])
        if audio_events and (
            not isinstance(audio_events, list) or not all(isinstance(item, dict) for item in audio_events)
        ):
            raise ScenarioValidationError(f"{scenario_id}._mock_audio_events must be list[object]")

        return cls(
            id=scenario_id,
            benchmark_version=version,
            domain=str(raw.get("domain", "unknown")),
            language=str(raw.get("language", "tr-TR")),
            call_direction=direction,
            system=str(raw.get("system", "")),
            available_tools=tuple(tools_raw),
            tool_schemas=tuple(tool_schemas),
            initial_state=values["initial_state"],
            tool_contracts=tuple(contracts),
            user_plan=user_plan,
            objectives=tuple(objectives),
            milestones=tuple(milestones),
            policies=policies,
            expected=values["expected"],
            conversation=values["conversation"],
            flow=values["flow"],
            runtime=values["runtime"],
            perturbations=values["perturbations"],
            trials=positive_ints["trials"],
            max_user_turns=positive_ints["max_user_turns"],
            max_steps_per_turn=positive_ints["max_steps_per_turn"],
            mock_runs=tuple(tuple(run) for run in mock_runs),
            mock_latencies=tuple(float(item) for item in mock_latencies),
            mock_negative_runs=tuple(negative_runs),
            mock_audio_events=tuple(audio_events),
            metadata=values["metadata"],
        )


def load_scenarios(path: str | Path) -> list[Scenario]:
    source = Path(path)
    files = sorted(source.glob("*.jsonl")) + sorted(source.glob("*.json")) if source.is_dir() else [source]
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for file in files:
        if file.suffix == ".jsonl":
            records = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            loaded = json.loads(file.read_text(encoding="utf-8"))
            records = loaded if isinstance(loaded, list) else [loaded]
        for raw in records:
            scenario = Scenario.from_dict(raw)
            if scenario.id in seen:
                raise ScenarioValidationError(f"duplicate scenario id: {scenario.id}")
            seen.add(scenario.id)
            scenarios.append(scenario)
    if not scenarios:
        raise ScenarioValidationError(f"no scenarios found: {source}")
    return scenarios
