"""Privacy helpers for semantic-memory diagnostics."""

from __future__ import annotations

import hashlib
from typing import Any


def hash_memory_identifier(value: Any) -> str:
    """Return a stable hash for user/session/memory identifiers in logs."""

    text = str(value or "").strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def memory_log_reference(value: Any) -> str:
    """Return a content fingerprint suitable for logs, never a text preview."""

    text = str(value or "").strip()
    return f"{hash_memory_identifier(text)};chars={len(text)}"


__all__ = ["hash_memory_identifier", "memory_log_reference"]
