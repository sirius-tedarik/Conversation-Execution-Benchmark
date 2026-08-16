"""Executable per-scenario state and deterministic tool contracts."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


class ToolExecutionError(ValueError):
    """A tool call cannot be resolved against declared contracts."""


def _parts(path: str) -> list[str]:
    parts = [part for part in path.split(".") if part]
    if not parts:
        raise ToolExecutionError("state patch path cannot be empty")
    return parts


def get_path(state: dict[str, Any], path: str, missing: Any = None) -> Any:
    current: Any = state
    for part in _parts(path):
        if not isinstance(current, dict) or part not in current:
            return missing
        current = current[part]
    return current


def set_path(state: dict[str, Any], path: str, value: Any) -> None:
    current: dict[str, Any] = state
    parts = _parts(path)
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ToolExecutionError(f"state patch intermediate path is not an object: {path}")
        current = child
    current[parts[-1]] = copy.deepcopy(value)


def delete_path(state: dict[str, Any], path: str) -> None:
    current: Any = state
    parts = _parts(path)
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def apply_patch(state: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    """Apply the auditable patch operations: set, append, increment and delete."""
    for operation in operations:
        op, path = operation.get("op"), str(operation.get("path", ""))
        if op == "set":
            set_path(state, path, operation.get("value"))
        elif op == "append":
            target = get_path(state, path)
            if not isinstance(target, list):
                raise ToolExecutionError(f"append target is not a list: {path}")
            target.append(copy.deepcopy(operation.get("value")))
        elif op == "increment":
            target, amount = get_path(state, path, 0), operation.get("value", 1)
            if not isinstance(target, (int, float)) or not isinstance(amount, (int, float)):
                raise ToolExecutionError(f"increment requires numeric values: {path}")
            set_path(state, path, target + amount)
        elif op == "delete":
            delete_path(state, path)
        else:
            raise ToolExecutionError(f"unknown state patch operation: {op}")


_TR_FOLD = str.maketrans("çÇşŞıİğĞöÖüÜ", "ccssiiggoouu")


def _normalize_text(value: str) -> str:
    """Fold case and Turkish diacritics so 'SMS'/'sms' and 'Kadıköy'/'Kadikoy' compare
    equal — a model choosing a different casing or an ASCII-folded spelling for the same
    value is not a different value, and scoring it as one hides real defects behind noise."""
    return value.strip().casefold().translate(_TR_FOLD)


def deep_subset(expected: Any, actual: Any, path: str = "state", normalize_strings: bool = False) -> list[str]:
    """Return mismatches; undeclared fields in actual state are allowed.

    `normalize_strings` folds case and Turkish diacritics before comparing plain string
    leaves — intended for comparing *model-supplied arguments* (where "SMS" and "sms" are
    the same instruction), not for state assertions, where the persisted value is exact
    by construction and a literal mismatch is itself the signal."""
    mismatches: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        for key, value in expected.items():
            child = f"{path}.{key}"
            if key not in actual:
                mismatches.append(f"{child}: missing")
            else:
                mismatches.extend(deep_subset(value, actual[key], child, normalize_strings))
        return mismatches
    if normalize_strings and isinstance(expected, str) and isinstance(actual, str):
        if _normalize_text(expected) != _normalize_text(actual):
            mismatches.append(f"{path}: expected {expected!r}, got {actual!r}")
        return mismatches
    if expected != actual:
        mismatches.append(f"{path}: expected {expected!r}, got {actual!r}")
    return mismatches


def _args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return not deep_subset(expected, actual, normalize_strings=True)


@dataclass
class ToolResult:
    result: dict[str, Any]
    latency_ms: float
    terminal: bool


class StatefulEnvironment:
    """Stateful executor with explicit contracts and no permissive fallback."""

    def __init__(self, initial_state: dict[str, Any], contracts: tuple[dict[str, Any], ...]):
        self.state = copy.deepcopy(initial_state)
        self.contracts = list(contracts)
        self.call_counts: dict[int, int] = {}
        self.ledger: list[dict[str, Any]] = []

    def _contract(self, name: str, arguments: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        for index, contract in enumerate(self.contracts):
            if contract.get("name") == name and _args_match(contract.get("match_args", {}), arguments):
                return index, contract
        raise ToolExecutionError(f"no executable contract for tool: {name} args={arguments}")

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        index, contract = self._contract(name, arguments)
        call_index = self.call_counts.get(index, 0)
        self.call_counts[index] = call_index + 1
        variants = contract.get("sequence")
        variant = variants[min(call_index, len(variants) - 1)] if variants else contract
        result = copy.deepcopy(variant.get("result", {}))
        patch = variant.get("state_patch", contract.get("state_patch", []))
        if not isinstance(patch, list):
            raise ToolExecutionError(f"{name}.state_patch must be a list")
        before = copy.deepcopy(self.state)
        if result.get("ok", True) and not result.get("error"):
            apply_patch(self.state, patch)
        latency_ms = float(variant.get("latency_ms", contract.get("latency_ms", 0)))
        terminal = bool(variant.get("terminal", contract.get("terminal", False)))
        self.ledger.append(
            {
                "name": name,
                "arguments": copy.deepcopy(arguments),
                "result": result,
                "latency_ms": latency_ms,
                "terminal": terminal,
                "state_before": before,
                "state_after": copy.deepcopy(self.state),
            }
        )
        return ToolResult(result=result, latency_ms=latency_ms, terminal=terminal)
