"""Model adapters shipped with CEB."""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from typing import Any


TRANSIENT_ERRORS = (TimeoutError, urllib.error.URLError, http.client.HTTPException, ConnectionError)
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class MockRunner:
    """Deterministic runner used by benchmark self-tests and example cases.

    `latencies` lets a fixture DECLARE how long each turn took. Wall-clock time in a mock run
    is effectively zero, so without it nothing could exercise the behaviours that depend on the
    caller noticing a silence (see user_simulator.py::ControlledUserSimulator.impatience). The
    declared value is reported through `declared_latency_ms`, which session.py prefers over its
    own measurement, keeping those cases reproducible instead of dependent on machine speed."""

    def __init__(self, outputs: list[str] | tuple[str, ...], latencies: list[float] | None = None):
        self.outputs, self.index = list(outputs), 0
        self.latencies = list(latencies) if latencies else []
        self.declared_latency_ms: float | None = None

    def generate(self, messages: list[dict[str, Any]], **_: Any) -> str:
        if self.index >= len(self.outputs):
            self.declared_latency_ms = None
            return ""
        output = self.outputs[self.index]
        self.declared_latency_ms = (
            float(self.latencies[self.index]) if self.index < len(self.latencies) else None
        )
        self.index += 1
        return output


class OpenAICompatibleRunner:
    """Run any OpenAI-compatible chat-completions endpoint without an SDK."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout: int = 180,
        max_retries: int = 3,
        backoff_s: float = 2.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    @staticmethod
    def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Translate CEB's provider-neutral calls to OpenAI chat messages."""
        wire: list[dict[str, Any]] = []
        for message in messages:
            item = dict(message)
            if item.get("role") == "assistant" and item.get("tool_calls"):
                item["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for call in item["tool_calls"]
                ]
            wire.append(item)
        return wire

    def _post_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retry transient transport faults so one blip cannot void a long sweep."""
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(self.backoff_s * attempt)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRYABLE_STATUS:
                    raise
            except TRANSIENT_ERRORS as error:
                last_error = error
        raise RuntimeError(f"model endpoint failed after {self.max_retries + 1} attempts: {last_error}")

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        seed: int | None = None,
        **_: Any,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._wire_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload.update({"tools": tools, "tool_choice": "auto"})
        if seed is not None:
            payload["seed"] = seed
        data = self._post_with_retries(payload)
        message = data.get("choices", [{}])[0].get("message") or {}
        content, tool_calls = message.get("content") or "", message.get("tool_calls") or []
        if tool_calls:
            calls = []
            for call in tool_calls:
                function = call.get("function", {})
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        pass  # keep the raw string; the parser scores the turn as unparseable
                calls.append({"name": function.get("name"), "arguments": arguments})
            content = f"{content}\n" if content else ""
            content += f"<tool_call>\n{json.dumps(calls, ensure_ascii=False)}\n</tool_call>"
        return content
