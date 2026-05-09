"""Shared secret validation helpers for fail-closed production config."""

from __future__ import annotations

from typing import Any


PLACEHOLDER_SECRET_MARKERS: tuple[str, ...] = (
    "change_me",
    "change-me",
    "changeme",
    "placeholder",
    "your_",
    "your-",
    "example",
    "dummy",
    "test-secret",
)


def is_missing_or_placeholder_secret(value: Any) -> bool:
    """Return True when a secret is absent or still looks like a placeholder."""
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in PLACEHOLDER_SECRET_MARKERS)
