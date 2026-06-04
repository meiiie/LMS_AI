"""Public event payload shaping for Code Studio tool calls."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping


_RAW_CODE_ARG_KEYS = {
    "code",
    "code_html",
    "fallback_html",
    "full_code",
    "html",
    "source",
    "source_code",
    "visual_payload",
}
_SENSITIVE_ARG_KEYS = {
    "access_token",
    "api_key",
    "approval_token",
    "authorization",
    "connected_account_id",
    "connection_id",
    "connection_ref",
    "credential",
    "image_base64",
    "image_url",
    "page_id",
    "password",
    "provider_payload",
    "raw_prompt",
    "refresh_token",
    "secret",
    "token",
    "vault_key_id",
}
_SENSITIVE_ARG_KEY_MARKERS = (
    "authorization",
    "connected_account",
    "credential",
    "password",
    "provider_payload",
    "secret",
    "token",
    "vault",
)
_MAX_PUBLIC_ARG_KEYS = 16
_MAX_PUBLIC_STRING_CHARS = 180


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _redacted_text_summary(value: Any) -> dict[str, Any]:
    text = str(value or "")
    return {
        "redacted": True,
        "chars": len(text),
        "sha256": _hash_text(text) if text else None,
    }


def _summarize_public_value(key: str, value: Any) -> Any:
    normalized_key = str(key or "").strip().lower()
    if normalized_key in _SENSITIVE_ARG_KEYS or any(
        marker in normalized_key for marker in _SENSITIVE_ARG_KEY_MARKERS
    ):
        return "[redacted]"
    if normalized_key in _RAW_CODE_ARG_KEYS:
        return _redacted_text_summary(value)
    if isinstance(value, str):
        if len(value) <= _MAX_PUBLIC_STRING_CHARS:
            return value
        return {
            "truncated": True,
            "preview": value[:_MAX_PUBLIC_STRING_CHARS],
            "chars": len(value),
            "sha256": _hash_text(value),
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        keys = [str(item) for item in list(value.keys())[:_MAX_PUBLIC_ARG_KEYS]]
        return {"type": "object", "keys": keys, "key_count": len(value)}
    if isinstance(value, (list, tuple, set)):
        return {"type": "array", "item_count": len(value)}
    return {"type": type(value).__name__}


def sanitize_code_studio_tool_call_args_for_stream(
    tool_name: str,
    args: Any,
) -> dict[str, Any]:
    """Return public-safe tool args for SSE without mutating internal args."""

    if not isinstance(args, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in list(args.items())[:_MAX_PUBLIC_ARG_KEYS]:
        sanitized[str(key)] = _summarize_public_value(str(key), value)
    omitted_count = max(0, len(args) - _MAX_PUBLIC_ARG_KEYS)
    if omitted_count:
        sanitized["_omitted_arg_count"] = omitted_count
    if str(tool_name or "").strip() == "tool_create_visual_code":
        sanitized.setdefault("_public_contract", "code_studio_tool_call_args.v1")
    return sanitized


__all__ = ["sanitize_code_studio_tool_call_args_for_stream"]
