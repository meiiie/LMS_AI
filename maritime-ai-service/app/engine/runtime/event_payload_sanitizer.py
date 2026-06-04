"""Privacy-safe sanitizer for runtime event/eval payloads."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_RUNTIME_IDENTIFIER_FINGERPRINT_KEY = b"wiii-runtime-identifier-fingerprint-v1"
_MAX_SANITIZED_DEPTH = 8
_MAX_SANITIZED_ITEMS = 64
_MAX_SANITIZED_STRING = 4000
_SENSITIVE_KEY_MARKERS = (
    "access_token",
    "ak_secret",
    "api_key",
    "apikey",
    "approval_token",
    "authorization",
    "bearer",
    "client_secret",
    "connection_id",
    "connection_ref",
    "cookie",
    "credential",
    "external_account_ref",
    "image_base64",
    "page_id",
    "password",
    "private_key",
    "provider_payload",
    "raw_provider",
    "refresh_token",
    "secret",
    "token",
    "vault_ref",
)
_CONTROL_KEYS = {"__proto__", "constructor", "prototype"}
_JSON_STRING_KEYS = {"content", "result", "tool_result", "payload"}
_REDACTED_SECRET = "<redacted-secret>"
_BEARER_SECRET_RE = re.compile(
    r"\bBearer\s+([A-Za-z0-9._~+/=-]{8,})",
    re.IGNORECASE,
)
_KEY_VALUE_SECRET_RE = re.compile(
    r"(?i)([\"']?(?:access[_-]?token|refresh[_-]?token|approval[_-]?token|"
    r"api[_-]?key|apikey|ak[_-]?secret|client[_-]?secret|authorization|"
    r"connection[_-]?id|connection[_-]?ref|connected[_-]?account[_-]?id|"
    r"external[_-]?account[_-]?ref|image[_-]?base64|page[_-]?id|"
    r"password|provider[_-]?payload|secret|token|credential|private[_-]?key|"
    r"cookie|vault[_-]?key[_-]?id)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\"'\s,;}{]{6,})([\"']?)"
)
_BARE_SECRET_RE = re.compile(
    r"\b("
    r"sk-(?:proj-)?[A-Za-z0-9_-]{12,}|"
    r"ghp_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"ya29\.[A-Za-z0-9_-]{10,}|"
    r"wcn_[A-Za-z0-9_-]{8,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")\b"
)


def _normalize_key(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
    )


def hash_runtime_identifier(value: Any) -> str | None:
    """Return the stable public hash used for user IDs in runtime artifacts."""

    text = str(value or "").strip()
    if not text:
        return None
    digest = hashlib.blake2b(
        text.encode("utf-8"),
        digest_size=8,
        key=_RUNTIME_IDENTIFIER_FINGERPRINT_KEY,
    ).hexdigest()
    return f"sha256:{digest}"


def _looks_sensitive_key(key: str) -> bool:
    return any(marker in key for marker in _SENSITIVE_KEY_MARKERS)


def _is_safe_presence_flag(key: str, value: Any) -> bool:
    """Preserve boolean presence flags while redacting the sensitive value itself."""

    return isinstance(value, bool) and (
        key.endswith("_present")
        or key.endswith("_configured")
        or key.endswith("_enabled")
    )


def _parse_json_string(value: str) -> Any:
    text = value.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _redact_secret_text(value: str) -> tuple[str, int]:
    text = value
    redacted_count = 0

    def _replace_bearer(match: re.Match[str]) -> str:
        nonlocal redacted_count
        redacted_count += 1
        return f"Bearer {_REDACTED_SECRET}"

    def _replace_key_value(match: re.Match[str]) -> str:
        nonlocal redacted_count
        redacted_count += 1
        return _REDACTED_SECRET

    def _replace_bare_secret(match: re.Match[str]) -> str:
        nonlocal redacted_count
        redacted_count += 1
        return _REDACTED_SECRET

    text = _BEARER_SECRET_RE.sub(_replace_bearer, text)
    text = _KEY_VALUE_SECRET_RE.sub(_replace_key_value, text)
    text = _BARE_SECRET_RE.sub(_replace_bare_secret, text)
    return text, redacted_count


def redact_runtime_secret_text(
    value: Any,
    *,
    max_length: int | None = _MAX_SANITIZED_STRING,
) -> str:
    """Redact secret-like substrings from diagnostic text."""

    text = str(value or "")
    if max_length is not None:
        text = text[:max(0, max_length)]
    redacted, _ = _redact_secret_text(text)
    return redacted


def sanitize_runtime_payload(value: Any, *, _depth: int = 0) -> Any:
    """Return a durable-log-safe copy while preserving replay-useful shape."""

    if _depth > _MAX_SANITIZED_DEPTH:
        return "<truncated>"
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict"):
        value = value.dict()

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        redacted_count = 0
        for raw_key, raw_item in list(value.items())[:_MAX_SANITIZED_ITEMS]:
            key = str(raw_key)
            normalized_key = _normalize_key(key)
            if not normalized_key or normalized_key in _CONTROL_KEYS:
                continue
            if normalized_key == "user_id":
                user_id_hash = hash_runtime_identifier(raw_item)
                if user_id_hash:
                    cleaned["user_id_hash"] = user_id_hash
                continue
            if normalized_key == "redacted_secret_count":
                try:
                    cleaned["redacted_secret_count"] = int(raw_item)
                except (TypeError, ValueError):
                    pass
                continue
            if _looks_sensitive_key(normalized_key):
                if _is_safe_presence_flag(normalized_key, raw_item):
                    cleaned[key] = raw_item
                    continue
                if raw_item not in (None, "", [], {}):
                    redacted_count += 1
                continue
            if normalized_key in _JSON_STRING_KEYS and isinstance(raw_item, str):
                parsed = _parse_json_string(raw_item)
                if parsed is not None:
                    cleaned[key] = sanitize_runtime_payload(
                        parsed,
                        _depth=_depth + 1,
                    )
                    continue
            cleaned_item = sanitize_runtime_payload(raw_item, _depth=_depth + 1)
            if isinstance(raw_item, str):
                _, item_redactions = _redact_secret_text(
                    raw_item[:_MAX_SANITIZED_STRING]
                )
                redacted_count += item_redactions
            cleaned[key] = cleaned_item
        if redacted_count:
            cleaned["redacted_secret_count"] = (
                int(cleaned.get("redacted_secret_count") or 0) + redacted_count
            )
        return cleaned

    if isinstance(value, list):
        return [
            sanitize_runtime_payload(item, _depth=_depth + 1)
            for item in value[:_MAX_SANITIZED_ITEMS]
        ]

    if isinstance(value, str):
        return redact_runtime_secret_text(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return str(value)[:_MAX_SANITIZED_STRING]


__all__ = [
    "hash_runtime_identifier",
    "redact_runtime_secret_text",
    "sanitize_runtime_payload",
]
