"""Strict JSON helpers for self-harness control-plane artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_strict_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(
            handle,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_object_pairs,
        )


def loads_strict_json(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=_reject_json_constant,
        object_pairs_hook=_reject_duplicate_json_object_pairs,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _reject_duplicate_json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    duplicate_keys: list[str] = []
    for key, value in pairs:
        if key in result and key not in duplicate_keys:
            duplicate_keys.append(key)
        result[key] = value
    if duplicate_keys:
        rendered = ", ".join(repr(key) for key in duplicate_keys)
        raise ValueError(f"duplicate JSON object key(s): {rendered}")
    return result
