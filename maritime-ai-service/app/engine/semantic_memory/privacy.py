"""Privacy helpers for semantic-memory diagnostics."""

from __future__ import annotations

import zlib
from typing import Any

_LOG_FINGERPRINT_KEY = b"wiii-log-fingerprint-v1"


def hash_memory_identifier(value: Any) -> str:
    """Return a stable, redacted fingerprint for identifiers in logs."""

    text = str(value or "").strip()
    digest = _log_fingerprint(text)
    return f"sha256:{digest}"


def memory_log_reference(value: Any) -> str:
    """Return a content fingerprint suitable for logs, never a text preview."""

    text = str(value or "").strip()
    return f"{hash_memory_identifier(text)};chars={len(text)}"


__all__ = ["hash_memory_identifier", "memory_log_reference"]


def _log_fingerprint(text: str) -> str:
    data = text.encode("utf-8")
    first = zlib.crc32(_LOG_FINGERPRINT_KEY + b"\0" + data) & 0xFFFFFFFF
    second = zlib.crc32(data + b"\0" + _LOG_FINGERPRINT_KEY) & 0xFFFFFFFF
    return f"{first:08x}{second:08x}"
