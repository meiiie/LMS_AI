"""Parse provider-emitted raw tool-call JSON safely.

Some OpenAI-compatible models occasionally return a function-call object as
plain assistant text instead of the structured ``tool_calls`` channel. This
module only accepts a complete JSON object/array whose tool name is present in
the bound tool inventory, so normal prose or JSON examples remain visible.
"""

from __future__ import annotations

import json
import re
from typing import Any


_FENCED_JSON_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def tool_names_from_tools(tools: list[Any] | tuple[Any, ...] | set[Any] | None) -> set[str]:
    """Return tool names from LangChain-like tools or OpenAI function schemas."""
    names: set[str] = set()
    for tool in tools or []:
        candidate = ""
        if isinstance(tool, dict):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            candidate = str(
                function.get("name")
                or tool.get("name")
                or tool.get("tool_name")
                or ""
            ).strip()
        else:
            candidate = str(
                getattr(tool, "name", "")
                or getattr(tool, "__name__", "")
                or ""
            ).strip()
        if candidate:
            names.add(candidate)
    return names


def _strip_json_fence(value: str) -> str:
    text = str(value or "").strip()
    match = _FENCED_JSON_RE.match(text)
    return match.group(1).strip() if match else text


def _loads_json_object(value: str) -> Any | None:
    text = _strip_json_fence(value)
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _coerce_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        args = dict(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = {}
        args = dict(parsed) if isinstance(parsed, dict) else {}
    else:
        args = {}
    if "query" not in args and "q" in args:
        args["query"] = args.get("q")
    return args


def _candidate_tool_call_objects(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("tool_calls"), list):
        return list(payload.get("tool_calls") or [])
    return [payload]


def _normalize_raw_tool_call(
    candidate: Any,
    *,
    allowed_tool_names: set[str] | None,
    index: int,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    function = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
    name = str(
        candidate.get("name")
        or candidate.get("tool")
        or candidate.get("tool_name")
        or function.get("name")
        or ""
    ).strip()
    if not name:
        return None
    if allowed_tool_names is not None and name not in allowed_tool_names:
        return None
    args = _coerce_arguments(
        candidate.get("arguments")
        if "arguments" in candidate
        else candidate.get("args")
        if "args" in candidate
        else function.get("arguments")
    )
    call_id = str(candidate.get("id") or f"raw_tool_call_{index}").strip()
    return {"id": call_id, "name": name, "args": args}


def extract_raw_tool_calls_from_text(
    value: Any,
    *,
    allowed_tool_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract structured tool calls from an assistant response that is only JSON."""
    if not isinstance(value, str):
        return []
    payload = _loads_json_object(value)
    if payload is None:
        return []
    calls: list[dict[str, Any]] = []
    for index, candidate in enumerate(_candidate_tool_call_objects(payload)):
        normalized = _normalize_raw_tool_call(
            candidate,
            allowed_tool_names=allowed_tool_names,
            index=index,
        )
        if normalized:
            calls.append(normalized)
    return calls
