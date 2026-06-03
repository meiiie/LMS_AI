"""Privacy helpers for outbound notification adapters."""

from __future__ import annotations

import re
from urllib.parse import quote

from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

_REDACTED = "<redacted-secret>"
_NOTIFICATION_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:access[_-]?token|api[_-]?key|apikey|token|text|chat_id|user_id)=)"
    r"([^&\s]+)"
)


def notification_recipient_ref(user_id: object) -> str:
    return hash_runtime_identifier(user_id) or "sha256:empty"


def sanitize_notification_detail(
    value: object,
    *secret_values: object,
    max_length: int = 500,
) -> str:
    """Return a log/result-safe provider diagnostic string."""

    text = str(value or "")
    for raw_secret in secret_values:
        secret = str(raw_secret or "")
        if not secret:
            continue
        text = text.replace(secret, _REDACTED)
        text = text.replace(quote(secret, safe=""), _REDACTED)

    text = _NOTIFICATION_QUERY_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{_REDACTED}",
        text,
    )
    text = redact_runtime_secret_text(text, max_length=None)
    text = " ".join(text.split())
    if max_length is not None:
        text = text[: max(0, max_length)]
    return text or "Notification provider error"
