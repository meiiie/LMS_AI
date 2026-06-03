"""Privacy-safe summaries for provider-shaped message metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_MAX_MESSAGES = 16
_MAX_BLOCKS = 16
_MAX_TOOL_CALLS = 16
_SENSITIVE_KEY_MARKERS = (
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)


def _text_provenance(value: Any) -> dict[str, Any]:
    text = str(value or "")
    payload: dict[str, Any] = {"present": bool(text), "char_count": len(text)}
    if text:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        payload["hash"] = f"sha256:{digest}"
    return payload


def _safe_text_token(value: Any, *, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _json_argument_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        data = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        data = parsed if isinstance(parsed, dict) else {}
    else:
        data = {}
    return sorted(
        str(key)
        for key in data.keys()
        if not any(marker in str(key).lower() for marker in _SENSITIVE_KEY_MARKERS)
    )[:32]


def _summarize_image_url(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        raw_url = value.get("url")
    else:
        raw_url = value
    url = str(raw_url or "")
    scheme = url.split(":", 1)[0].lower() if ":" in url else ""
    return {
        "url_present": bool(url),
        "url_scheme": scheme[:24],
        "is_data_url": url.lower().startswith("data:"),
    }


def _summarize_source(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "type": _safe_text_token(source.get("type"), limit=40),
        "media_type": _safe_text_token(source.get("media_type"), limit=80),
        "data_present": bool(source.get("data")),
    }


def _summarize_tool_call(value: Any) -> dict[str, Any]:
    call = value if isinstance(value, dict) else {}
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = function.get("name") or call.get("name")
    args = function.get("arguments", call.get("input"))
    return {
        "id_present": bool(call.get("id")),
        "name": _safe_text_token(name),
        "argument_keys": _json_argument_keys(args),
    }


def _summarize_block(value: Any) -> dict[str, Any]:
    block = value if isinstance(value, dict) else {}
    block_type = _safe_text_token(block.get("type"), limit=40)
    summary: dict[str, Any] = {"type": block_type or type(value).__name__}
    if "text" in block:
        summary["text"] = _text_provenance(block.get("text"))
    if block_type in {"image_url", "input_image"}:
        summary["image_url"] = _summarize_image_url(block.get("image_url"))
    if block_type == "image":
        summary["source"] = _summarize_source(block.get("source"))
    if block_type == "tool_use":
        summary["tool_use"] = {
            "id_present": bool(block.get("id")),
            "name": _safe_text_token(block.get("name")),
            "argument_keys": _json_argument_keys(block.get("input")),
        }
    if block_type == "tool_result":
        content = block.get("content")
        summary["tool_result"] = {
            "tool_use_id_present": bool(block.get("tool_use_id")),
            "content": summarize_content(content),
        }
    return summary


def summarize_content(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"kind": "text", "text": _text_provenance(value)}
    if isinstance(value, list):
        return {
            "kind": "blocks",
            "block_count": len(value),
            "blocks": [_summarize_block(item) for item in value[:_MAX_BLOCKS]],
        }
    if value is None:
        return {"kind": "empty"}
    return {
        "kind": type(value).__name__,
        "text": _text_provenance(value),
    }


def summarize_provider_messages(raw_messages: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_messages, list):
        return []
    summaries: list[dict[str, Any]] = []
    for raw in raw_messages[:_MAX_MESSAGES]:
        if not isinstance(raw, dict):
            continue
        summary: dict[str, Any] = {
            "role": _safe_text_token(raw.get("role"), limit=40),
            "content": summarize_content(raw.get("content")),
        }
        if raw.get("name"):
            summary["name"] = _safe_text_token(raw.get("name"))
        tool_call_id = raw.get("tool_call_id")
        if tool_call_id:
            summary["tool_call_id_present"] = True
        tool_calls = raw.get("tool_calls")
        if isinstance(tool_calls, list):
            summary["tool_calls"] = [
                _summarize_tool_call(call)
                for call in tool_calls[:_MAX_TOOL_CALLS]
            ]
        summaries.append(summary)
    return summaries


__all__ = ["summarize_content", "summarize_provider_messages"]
