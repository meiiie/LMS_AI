"""Shared UTF-8 JSON output helper for runtime evidence probes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


OUTPUT_PATH_DIRECTORY_ERROR = "runtime evidence output path must not be a directory"
OUTPUT_PATH_SYMLINK_ERROR = "runtime evidence output path must not be a symlink"
OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "runtime evidence output path parent must not be a symlink"
)


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.is_symlink():
        raise ValueError(OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_path):
        raise ValueError(OUTPUT_PATH_PARENT_SYMLINK_ERROR)
    if out_path.exists() and out_path.is_dir():
        raise ValueError(OUTPUT_PATH_DIRECTORY_ERROR)


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def emit_json_payload(payload: dict[str, Any], out_path: Path | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if out_path is None:
        sys.stdout.write(rendered)
        return

    validate_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    validate_output_path(out_path)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=out_path.parent,
            encoding="utf-8",
            newline="\n",
            prefix=f".{out_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(rendered)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        validate_output_path(out_path)
        os.replace(temp_path, out_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
