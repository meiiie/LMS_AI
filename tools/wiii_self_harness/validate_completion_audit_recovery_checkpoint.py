#!/usr/bin/env python3
"""Validate a source-bound recovery resume checkpoint."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

import generate_completion_audit_recovery_checkpoint as checkpoint_generator  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402


RECOVERY_CHECKPOINT_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_checkpoint_validation.v1"
)

CHECKPOINT_FIELDS = {
    "schema_version",
    "ok",
    "recovery_control_chain_path",
    "recovery_control_chain_sha256",
    "recovery_control_chain_validation_schema_version",
    "chain_fingerprint_sha256",
    "chain_state",
    "resume_state",
    "release_gate_ready",
    "recovery_chain_ready",
    "operator_setup_required",
    "autonomous_dispatch_allowed",
    "queue_state",
    "work_order_state",
    "status_state",
    "authorization_state",
    "dispatch_run_state",
    "next_group_ids",
    "completed_group_ids",
    "pending_group_ids",
    "authorized_group_ids",
    "blocked_group_ids",
    "command_count",
    "required_resume_inputs",
    "resume_checkpoint_fingerprint_sha256",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}


@dataclass(frozen=True)
class RecoveryCheckpointValidationResult:
    validation_schema_version: str
    checkpoint_path: str
    recovery_control_chain_path: str | None
    resume_state: str
    chain_state: str
    release_gate_ready: bool
    operator_setup_required: bool
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def validate_recovery_checkpoint(
    checkpoint_path: Path,
    *,
    recovery_control_chain_path: Path | None = None,
    repo_root: Path = Path("."),
) -> RecoveryCheckpointValidationResult:
    errors: list[str] = []
    payload: dict[str, Any] = {}
    try:
        loaded = load_strict_json_file(checkpoint_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit recovery checkpoint JSON invalid: {exc}")
    else:
        if isinstance(loaded, dict):
            payload = loaded
        else:
            errors.append("completion audit recovery checkpoint root must be an object")
    if payload:
        errors.extend(_payload_shape_errors(payload))
        embedded_control_chain_path = Path(
            _string(payload.get("recovery_control_chain_path"))
        )
        if recovery_control_chain_path is not None:
            if (
                checkpoint_generator._sha256_file(recovery_control_chain_path)
                != payload.get("recovery_control_chain_sha256")
            ):
                errors.append(
                    "completion audit recovery checkpoint supplied control chain SHA-256 must match checkpoint source"
                )
            source_path = recovery_control_chain_path
        else:
            source_path = embedded_control_chain_path
        expected = checkpoint_generator.generate_completion_audit_recovery_checkpoint(
            source_path,
            repo_root=repo_root,
        ).to_dict()
        if recovery_control_chain_path is not None:
            expected["recovery_control_chain_path"] = payload.get(
                "recovery_control_chain_path"
            )
        if expected.get("ok") is not True:
            errors.append(
                "completion audit recovery checkpoint source regeneration failed: "
                + "; ".join(expected.get("errors", []))
            )
        errors.extend(_payload_parity_errors(payload, expected))
    return RecoveryCheckpointValidationResult(
        validation_schema_version=RECOVERY_CHECKPOINT_VALIDATION_SCHEMA_VERSION,
        checkpoint_path=str(checkpoint_path),
        recovery_control_chain_path=(
            _string(payload.get("recovery_control_chain_path")) if payload else None
        ),
        resume_state=_string(payload.get("resume_state")) if payload else "",
        chain_state=_string(payload.get("chain_state")) if payload else "",
        release_gate_ready=payload.get("release_gate_ready") is True if payload else False,
        operator_setup_required=(
            payload.get("operator_setup_required") is True if payload else False
        ),
        errors=errors,
    )


def _payload_shape_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    unsupported = sorted(set(payload) - CHECKPOINT_FIELDS)
    if unsupported:
        errors.append(
            "completion audit recovery checkpoint unsupported field(s): "
            + ", ".join(unsupported)
        )
    missing = sorted(CHECKPOINT_FIELDS - set(payload))
    if missing:
        errors.append(
            "completion audit recovery checkpoint missing field(s): "
            + ", ".join(missing)
        )
    if payload.get("schema_version") != checkpoint_generator.RECOVERY_CHECKPOINT_SCHEMA_VERSION:
        errors.append("completion audit recovery checkpoint schema version invalid")
    if payload.get("ok") is not True:
        errors.append("completion audit recovery checkpoint must be ok")
    if payload.get("errors") != []:
        errors.append("completion audit recovery checkpoint errors must be empty")
    if payload.get("error_codes") != []:
        errors.append("completion audit recovery checkpoint error_codes must be empty")
    if payload.get("error_code_counts") != {}:
        errors.append(
            "completion audit recovery checkpoint error_code_counts must be empty"
        )
    if not isinstance(payload.get("privacy"), dict):
        errors.append("completion audit recovery checkpoint privacy must be an object")
    elif any(value is not False for value in payload["privacy"].values()):
        errors.append("completion audit recovery checkpoint privacy flags must be false")
    for field in (
        "next_group_ids",
        "completed_group_ids",
        "pending_group_ids",
        "authorized_group_ids",
        "blocked_group_ids",
        "required_resume_inputs",
    ):
        if not _is_string_list(payload.get(field)):
            errors.append(f"completion audit recovery checkpoint {field} invalid")
    if not _is_sha256(payload.get("recovery_control_chain_sha256")):
        errors.append(
            "completion audit recovery checkpoint recovery_control_chain_sha256 invalid"
        )
    if not _is_sha256(payload.get("chain_fingerprint_sha256")):
        errors.append("completion audit recovery checkpoint chain fingerprint invalid")
    if not _is_sha256(payload.get("resume_checkpoint_fingerprint_sha256")):
        errors.append("completion audit recovery checkpoint fingerprint invalid")
    if not isinstance(payload.get("command_count"), int) or isinstance(
        payload.get("command_count"),
        bool,
    ):
        errors.append("completion audit recovery checkpoint command_count invalid")
    return errors


def _payload_parity_errors(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not expected:
        return errors
    for field in CHECKPOINT_FIELDS:
        if payload.get(field) != expected.get(field):
            errors.append(
                f"completion audit recovery checkpoint {field} must match regenerated checkpoint"
            )
    return errors


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "JSON invalid" in error or "root must be an object" in error:
        return "completion_audit_recovery_checkpoint_json_invalid"
    if "unsupported field" in error or "missing field" in error:
        return "completion_audit_recovery_checkpoint_shape_invalid"
    if "schema version invalid" in error:
        return "completion_audit_recovery_checkpoint_schema_invalid"
    if "privacy" in error:
        return "completion_audit_recovery_checkpoint_privacy_invalid"
    if "supplied control chain SHA-256 must match" in error:
        return "completion_audit_recovery_checkpoint_source_mismatch"
    if "source regeneration failed" in error:
        return "completion_audit_recovery_checkpoint_source_invalid"
    if "must match regenerated checkpoint" in error:
        return "completion_audit_recovery_checkpoint_fingerprint_mismatch"
    if "fingerprint" in error or "sha256" in error:
        return "completion_audit_recovery_checkpoint_fingerprint_invalid"
    if "must be ok" in error or "errors must be empty" in error:
        return "completion_audit_recovery_checkpoint_not_ok"
    return "completion_audit_recovery_checkpoint_validation_error"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "validation_schema_version": RECOVERY_CHECKPOINT_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a source-bound completion-audit recovery checkpoint.",
    )
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--recovery-control-chain", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_recovery_checkpoint(
            args.checkpoint,
            recovery_control_chain_path=args.recovery_control_chain,
            repo_root=args.repo_root,
        )
        if args.json or args.out:
            text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        elif result.ok:
            text = "Wiii Completion Audit Recovery Checkpoint Validation: PASS\n"
        else:
            text = (
                "Wiii Completion Audit Recovery Checkpoint Validation: FAIL\n"
                + "\n".join(f"- {error}" for error in result.errors)
                + "\n"
            )
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
        return 0 if result.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="" if args.json else "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
