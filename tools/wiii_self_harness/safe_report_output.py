"""Shared safe report-output helpers for Wiii self-harness CLIs."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile


REPORT_OUTPUT_PATH_DIRECTORY_ERROR = "report output path must not be a directory"
REPORT_OUTPUT_PATH_SYMLINK_ERROR = "report output path must not be a symlink"
REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "report output path parent must not be a symlink"
)


def validate_report_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(REPORT_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(REPORT_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def safe_write_report_text(out_path: Path, text: str) -> None:
    validate_report_output_path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    validate_report_output_path(out_path)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=out_path.parent,
            encoding="utf-8",
            prefix=f".{out_path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        validate_report_output_path(out_path)
        os.replace(temp_path, out_path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
