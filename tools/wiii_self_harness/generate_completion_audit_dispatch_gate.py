#!/usr/bin/env python3
"""Generate a fail-closed dispatch gate from launch pack and setup state."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_launch_pack as launch_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


DISPATCH_GATE_SCHEMA_VERSION = "wiii.completion_audit_dispatch_gate.v1"
DISPATCH_GATE_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit dispatch gate output path must not be a directory"
)
DISPATCH_GATE_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit dispatch gate output path must not be a symlink"
)
DISPATCH_GATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit dispatch gate output path parent must not be a symlink"
)
DISPATCH_GATE_LAUNCH_PACK_VALIDATION_ERROR = (
    "completion audit dispatch gate launch pack failed validation"
)
DISPATCH_GATE_SETUP_STATE_VALIDATION_ERROR = (
    "completion audit dispatch gate setup state failed validation"
)
UNLOCKED_LIVE_COMMAND_SPEC_FIELDS = ("workflow_dispatch", "local_live_probe")
BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS = ("local_failure_from_preflight",)


@dataclass(frozen=True)
class DispatchSetupCheck:
    category: str
    key: str
    binding_tokens: list[str]
    source_handle: str


@dataclass(frozen=True)
class DispatchGateItem:
    requirement_id: str
    title: str
    workflow: str
    probe: str
    expected_artifact: str
    setup_status: str
    dispatch_ready: bool
    ready_setup_handle_count: int
    ready_setup_handles: list[DispatchSetupCheck]
    blocked_setup_check_count: int
    blocked_setup_checks: list[DispatchSetupCheck]
    unlocked_live_command_specs: dict[str, Any]
    blocked_diagnostic_command_specs: dict[str, Any]


@dataclass(frozen=True)
class CompletionAuditDispatchGate:
    schema_version: str
    ok: bool
    launch_pack_path: str
    launch_pack_sha256: str
    launch_pack_schema_version: str
    launch_items_fingerprint_sha256: str
    launch_setup_fingerprint_sha256: str
    setup_state_path: str
    setup_state_sha256: str
    setup_state_schema_version: str
    setup_state_fingerprint_sha256: str
    dispatch_gate_fingerprint_sha256: str
    dispatch_ready: bool
    dispatch_item_count: int
    ready_dispatch_item_count: int
    blocked_dispatch_item_count: int
    dispatch_items: list[DispatchGateItem]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_dispatch_gate(
    launch_pack_path: Path,
    setup_state_path: Path,
) -> CompletionAuditDispatchGate:
    launch_validation = launch_validator.validate_launch_pack(launch_pack_path)
    if not launch_validation.ok:
        raise ValueError(
            DISPATCH_GATE_LAUNCH_PACK_VALIDATION_ERROR
            + ": "
            + "; ".join(launch_validation.errors)
        )
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        raise ValueError(
            DISPATCH_GATE_SETUP_STATE_VALIDATION_ERROR
            + ": "
            + "; ".join(setup_validation.errors)
        )
    launch_payload = load_strict_json_file(launch_pack_path)
    setup_payload = load_strict_json_file(setup_state_path)
    if not isinstance(launch_payload, dict):
        raise ValueError("completion audit launch pack root must be an object")
    if not isinstance(setup_payload, dict):
        raise ValueError("completion audit setup state root must be an object")

    setup_requirements = {
        item.get("requirement_id"): item
        for item in setup_payload.get("requirements", [])
        if isinstance(item, dict)
    }
    dispatch_items = [
        _dispatch_item(item, setup_requirements.get(item.get("requirement_id")))
        for item in launch_payload.get("launch_items", [])
        if isinstance(item, dict)
    ]
    ready_count = sum(1 for item in dispatch_items if item.dispatch_ready)
    errors: list[str] = []
    return CompletionAuditDispatchGate(
        schema_version=DISPATCH_GATE_SCHEMA_VERSION,
        ok=True,
        launch_pack_path=str(launch_pack_path),
        launch_pack_sha256=_sha256_file(launch_pack_path),
        launch_pack_schema_version=_string(launch_payload.get("schema_version")),
        launch_items_fingerprint_sha256=_string(
            launch_payload.get("launch_items_fingerprint_sha256")
        ),
        launch_setup_fingerprint_sha256=_string(
            launch_payload.get("launch_setup_fingerprint_sha256")
        ),
        setup_state_path=str(setup_state_path),
        setup_state_sha256=_sha256_file(setup_state_path),
        setup_state_schema_version=_string(setup_payload.get("schema_version")),
        setup_state_fingerprint_sha256=_string(
            setup_payload.get("setup_state_fingerprint_sha256")
        ),
        dispatch_gate_fingerprint_sha256=_dispatch_gate_fingerprint(
            [asdict(item) for item in dispatch_items]
        ),
        dispatch_ready=ready_count == len(dispatch_items) and bool(dispatch_items),
        dispatch_item_count=len(dispatch_items),
        ready_dispatch_item_count=ready_count,
        blocked_dispatch_item_count=len(dispatch_items) - ready_count,
        dispatch_items=dispatch_items,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        errors=errors,
    )


def _dispatch_item(
    launch_item: dict[str, Any],
    setup_requirement: Any,
) -> DispatchGateItem:
    setup = setup_requirement if isinstance(setup_requirement, dict) else {}
    checks = [
        check
        for check in setup.get("setup_checks", [])
        if isinstance(check, dict)
    ]
    ready_checks = [_dispatch_setup_check(check) for check in checks if check.get("present") is True]
    blocked_checks = [
        _dispatch_setup_check(check) for check in checks if check.get("present") is not True
    ]
    dispatch_ready = bool(checks) and not blocked_checks
    return DispatchGateItem(
        requirement_id=_string(launch_item.get("requirement_id")),
        title=_string(launch_item.get("title")),
        workflow=_string(launch_item.get("workflow")),
        probe=_string(launch_item.get("probe")),
        expected_artifact=_string(launch_item.get("expected_artifact")),
        setup_status="ready" if dispatch_ready else "pending",
        dispatch_ready=dispatch_ready,
        ready_setup_handle_count=len(ready_checks),
        ready_setup_handles=ready_checks,
        blocked_setup_check_count=len(blocked_checks),
        blocked_setup_checks=blocked_checks,
        unlocked_live_command_specs=(
            _unlocked_live_command_specs(launch_item) if dispatch_ready else {}
        ),
        blocked_diagnostic_command_specs=(
            {} if dispatch_ready else _blocked_diagnostic_command_specs(launch_item)
        ),
    )


def _dispatch_setup_check(check: dict[str, Any]) -> DispatchSetupCheck:
    return DispatchSetupCheck(
        category=_string(check.get("category")),
        key=_string(check.get("key")),
        binding_tokens=_string_list(check.get("binding_tokens")),
        source_handle=_string(check.get("source_handle")),
    )


def _unlocked_live_command_specs(launch_item: dict[str, Any]) -> dict[str, Any]:
    command_specs = launch_item.get("command_specs")
    if not isinstance(command_specs, dict):
        return {}
    return {
        name: command_specs.get(name, {})
        for name in UNLOCKED_LIVE_COMMAND_SPEC_FIELDS
    }


def _blocked_diagnostic_command_specs(launch_item: dict[str, Any]) -> dict[str, Any]:
    command_specs = launch_item.get("command_specs")
    if not isinstance(command_specs, dict):
        return {}
    return {
        name: command_specs.get(name, {})
        for name in BLOCKED_DIAGNOSTIC_COMMAND_SPEC_FIELDS
    }


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(DISPATCH_GATE_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(DISPATCH_GATE_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(DISPATCH_GATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fail-closed dispatch gate from a completion-audit "
            "launch pack and setup state."
        ),
    )
    parser.add_argument("launch_pack", type=Path)
    parser.add_argument("setup_state", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        gate = generate_completion_audit_dispatch_gate(
            args.launch_pack,
            args.setup_state,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(gate.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": DISPATCH_GATE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith(DISPATCH_GATE_LAUNCH_PACK_VALIDATION_ERROR):
        return "completion_audit_dispatch_gate_launch_pack_invalid"
    if error.startswith(DISPATCH_GATE_SETUP_STATE_VALIDATION_ERROR):
        return "completion_audit_dispatch_gate_setup_state_invalid"
    if error == DISPATCH_GATE_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_dispatch_gate_output_path_directory"
    if error == DISPATCH_GATE_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_dispatch_gate_output_path_symlink"
    if error == DISPATCH_GATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_dispatch_gate_output_path_parent_symlink"
    return "completion_audit_dispatch_gate_generation_failed"


def _dispatch_gate_fingerprint(dispatch_items: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        dispatch_items,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


if __name__ == "__main__":
    raise SystemExit(main())
