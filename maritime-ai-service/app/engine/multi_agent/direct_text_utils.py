"""Shared direct-runtime text normalization helpers."""

from __future__ import annotations

import unicodedata


def _fold_direct_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace("đ", "d").split())
