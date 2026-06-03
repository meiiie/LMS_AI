from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile

import pytest


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "runtime_evidence_output.py"
SPEC = importlib.util.spec_from_file_location("runtime_evidence_output", SCRIPT_PATH)
runtime_output = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runtime_output)


def test_emit_json_payload_writes_utf8_json_file() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        out_path = Path(temp_dir) / "evidence.json"

        runtime_output.emit_json_payload({"status": "pass", "text": "T\u1ed1t"}, out_path)

        payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert payload == {"status": "pass", "text": "T\u1ed1t"}


def test_emit_json_payload_replaces_existing_file_atomically() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        out_path = Path(temp_dir) / "evidence.json"
        out_path.write_text("old", encoding="utf-8")

        runtime_output.emit_json_payload({"status": "pass", "count": 1}, out_path)

        payload = json.loads(out_path.read_text(encoding="utf-8"))
        temp_files = list(Path(temp_dir).glob(".evidence.json.*.tmp"))

    assert payload == {"status": "pass", "count": 1}
    assert temp_files == []


def test_emit_json_payload_cleans_temp_file_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        out_path = Path(temp_dir) / "evidence.json"
        out_path.write_text("keep", encoding="utf-8")

        def fail_replace(_source: Path, _target: Path) -> None:
            raise RuntimeError("replace failed")

        monkeypatch.setattr(runtime_output.os, "replace", fail_replace)

        with pytest.raises(RuntimeError, match="replace failed"):
            runtime_output.emit_json_payload({"status": "pass"}, out_path)

        target_text = out_path.read_text(encoding="utf-8")
        temp_files = list(Path(temp_dir).glob(".evidence.json.*.tmp"))

    assert target_text == "keep"
    assert temp_files == []


def test_emit_json_payload_rejects_directory_output() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        out_path = Path(temp_dir) / "evidence"
        out_path.mkdir()

        with pytest.raises(ValueError, match=runtime_output.OUTPUT_PATH_DIRECTORY_ERROR):
            runtime_output.emit_json_payload({"status": "pass"}, out_path)

        entries = list(out_path.iterdir())

    assert entries == []


def test_emit_json_payload_rejects_symlink_output() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        target_path = Path(temp_dir) / "target.json"
        target_path.write_text("keep", encoding="utf-8")
        out_path = Path(temp_dir) / "evidence.json"
        try:
            os.symlink(target_path, out_path)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink not available: {exc}")

        with pytest.raises(ValueError, match=runtime_output.OUTPUT_PATH_SYMLINK_ERROR):
            runtime_output.emit_json_payload({"status": "pass"}, out_path)

        target_text = target_path.read_text(encoding="utf-8")

    assert target_text == "keep"


def test_emit_json_payload_rejects_parent_symlink_output() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        target_dir = Path(temp_dir) / "target-dir"
        target_dir.mkdir()
        symlink_parent = Path(temp_dir) / "linked-parent"
        try:
            os.symlink(target_dir, symlink_parent, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink not available: {exc}")
        out_path = symlink_parent / "evidence.json"

        with pytest.raises(
            ValueError,
            match=runtime_output.OUTPUT_PATH_PARENT_SYMLINK_ERROR,
        ):
            runtime_output.emit_json_payload({"status": "pass"}, out_path)

        target_entries = list(target_dir.iterdir())

    assert target_entries == []
