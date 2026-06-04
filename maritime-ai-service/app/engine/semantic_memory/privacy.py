"""Privacy helpers for semantic-memory diagnostics."""

from __future__ import annotations

import hmac
from typing import Any

_LOG_FINGERPRINT_KEY = b"wiii-log-fingerprint-v1"


def hash_memory_identifier(value: Any) -> str:
    """Return a stable hash for user/session/memory identifiers in logs."""

    text = str(value or "").strip()
    digest = hmac.digest(
        _LOG_FINGERPRINT_KEY,
        text.encode("utf-8"),
        "sha256",
    ).hex()[:16]
    return f"sha256:{digest}"


def memory_log_reference(value: Any) -> str:
    """Return a content fingerprint suitable for logs, never a text preview."""

    text = str(value or "").strip()
    return f"{hash_memory_identifier(text)};chars={len(text)}"


__all__ = ["hash_memory_identifier", "memory_log_reference"]
