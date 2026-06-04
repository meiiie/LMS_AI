"""Public-event sanitization for tool-call arguments."""

from __future__ import annotations

import json
from typing import Any

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)


_MAX_PUBLIC_TOOL_RESULT_CHARS = 20_000
_MAX_PUBLIC_TOOL_RESULT_STRING_CHARS = 4_000
_SENSITIVE_TOOL_ARG_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "approval_token",
        "authorization",
        "code",
        "connected_account_id",
        "connection_id",
        "connection_ref",
        "credential",
        "image_base64",
        "image_filename",
        "image_media_type",
        "image_url",
        "page_id",
        "password",
        "provider_payload",
        "raw_prompt",
        "refresh_token",
        "secret",
        "state",
        "token",
        "vault_key_id",
    }
)
_RAW_CONTENT_TOOL_ARG_KEYS = frozenset(
    {
        "code_html",
        "content",
        "course_patch",
        "course_plan",
        "document_text",
        "excerpt",
        "fallback_html",
        "full_code",
        "html",
        "lesson_patch",
        "markdown",
        "quality_report",
        "raw_html",
        "source_code",
        "source_references",
        "visual_payload",
    }
)
_SENSITIVE_TOOL_ARG_KEY_MARKERS = (
    "authorization",
    "connected_account",
    "credential",
    "password",
    "provider_payload",
    "secret",
    "token",
    "vault",
)


def sanitize_tool_args_for_event(value: Any) -> Any:
    """Return event-safe tool args without changing executor input."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            normalized = key.strip().lower()
            if (
                normalized in _SENSITIVE_TOOL_ARG_KEYS
                or normalized in _RAW_CONTENT_TOOL_ARG_KEYS
                or any(
                    marker in normalized
                    for marker in _SENSITIVE_TOOL_ARG_KEY_MARKERS
                )
            ):
                safe[key] = "[redacted]"
            else:
                safe[key] = sanitize_tool_args_for_event(raw_item)
        return safe
    if isinstance(value, list):
        return [sanitize_tool_args_for_event(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_tool_args_for_event(item) for item in value]
    if isinstance(value, set):
        return [sanitize_tool_args_for_event(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("wcn_") or stripped.lower().startswith("bearer "):
            return "[redacted]"
    return value


def sanitize_tool_result_for_event(value: Any) -> str:
    """Return a public-safe tool result string for in-memory event ledgers."""

    if isinstance(value, str):
        parsed = _parse_json_value(value)
        if parsed is not None:
            return _stringify_sanitized_payload(
                _sanitize_tool_result_payload_for_event(parsed)
            )
        return redact_runtime_secret_text(
            value,
            max_length=_MAX_PUBLIC_TOOL_RESULT_CHARS,
        )

    if isinstance(value, (dict, list, tuple, set)) or hasattr(value, "model_dump"):
        sanitized = _sanitize_tool_result_payload_for_event(value)
        return str(sanitized)

    return redact_runtime_secret_text(
        value,
        max_length=_MAX_PUBLIC_TOOL_RESULT_CHARS,
    )


def _parse_json_value(value: str) -> Any | None:
    text = value.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _stringify_sanitized_payload(value: Any) -> str:
    sanitized = sanitize_runtime_payload(value)
    if isinstance(sanitized, (dict, list)):
        return json.dumps(sanitized, ensure_ascii=False)
    return str(sanitized or "")


def _sanitize_tool_result_payload_for_event(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict"):
        value = value.dict()

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            normalized = key.strip().lower()
            if (
                normalized in _SENSITIVE_TOOL_ARG_KEYS
                or any(
                    marker in normalized
                    for marker in _SENSITIVE_TOOL_ARG_KEY_MARKERS
                )
            ):
                continue
            if normalized in _RAW_CONTENT_TOOL_ARG_KEYS:
                safe[key] = _redacted_content_summary(raw_item)
                continue
            safe[key] = _sanitize_tool_result_payload_for_event(raw_item)
        return safe
    if isinstance(value, list):
        return [_sanitize_tool_result_payload_for_event(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_tool_result_payload_for_event(item) for item in value]
    if isinstance(value, set):
        return [_sanitize_tool_result_payload_for_event(item) for item in value]
    if isinstance(value, str):
        return redact_runtime_secret_text(
            value,
            max_length=_MAX_PUBLIC_TOOL_RESULT_STRING_CHARS,
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_runtime_secret_text(
        value,
        max_length=_MAX_PUBLIC_TOOL_RESULT_STRING_CHARS,
    )


def _redacted_content_summary(value: Any) -> dict[str, Any]:
    return {
        "redacted": True,
        "chars": len(str(value or "")),
    }


__all__ = ["sanitize_tool_args_for_event", "sanitize_tool_result_for_event"]
