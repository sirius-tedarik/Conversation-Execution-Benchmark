"""Parse common assistant tool-call formats into one provider-neutral form."""
from __future__ import annotations

import json
import re
from typing import Any


TOOLCALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
XML_TOOLCALL_RE = re.compile(r"<tool_call>\s*<function=([^>]+)>(.*?)</function>\s*</tool_call>", re.S)
XML_PARAM_RE = re.compile(r"<parameter=([^>]+)>\s*(.*?)\s*</parameter>", re.S)
END_RE = re.compile(r"<\|end\|>|<\|im_end\|>|<\|eot_id\|>|<\|endoftext\|>")


def _coerce(value: str) -> Any:
    try:
        return json.loads(value.strip())
    except Exception:
        return value.strip()


def _parse_json_calls(payload_text: str) -> tuple[list[dict[str, Any]], bool]:
    try:
        payload = json.loads(payload_text)
        payload = [payload] if isinstance(payload, dict) else payload
        calls = []
        valid = isinstance(payload, list)
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict) or not item.get("name"):
                valid = False
                continue
            arguments = item.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                valid = False
                arguments = {}
            calls.append({"name": item["name"], "arguments": arguments})
    except Exception:
        return [], False
    return calls, valid


def parse_assistant_output(text: str) -> dict[str, Any]:
    """Parse JSON-wrapped or Qwen-style XML tool calls without provider SDKs."""
    raw = text
    end = END_RE.search(text)
    if end:
        text = text[: end.start()]
    text = re.sub(r"^<\|assistant\|>\s*", "", text.strip())
    xml_matches = list(XML_TOOLCALL_RE.finditer(text))
    if xml_matches:
        calls = []
        for match in xml_matches:
            name = match.group(1).strip()
            arguments = {key.strip(): _coerce(value) for key, value in XML_PARAM_RE.findall(match.group(2))}
            calls.append({"name": name, "arguments": arguments})
        valid = len(re.findall(r"<tool_call>", text)) == len(xml_matches) and all(call["name"] for call in calls)
        return {
            # Text around the call blocks stays in content so oracles can score it.
            "content": XML_TOOLCALL_RE.sub("", text).strip(),
            "tool_calls": calls,
            "parse_ok": valid,
            "raw": raw,
        }

    match = TOOLCALL_RE.search(text)
    if not match:
        return {
            "content": text.strip(),
            "tool_calls": [],
            "parse_ok": "<tool_call>" not in text,
            "raw": raw,
        }
    calls, valid = _parse_json_calls(match.group(1).strip())
    # Text around the call block stays in content so oracles can score it.
    remainder = f"{text[: match.start()]}\n{text[match.end():]}".strip()
    if "<tool_call>" in remainder:
        valid = False
    return {
        "content": remainder,
        "tool_calls": calls,
        "parse_ok": valid,
        "raw": raw,
    }
