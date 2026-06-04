#!/usr/bin/env python3
"""Validate completion-audit setup-handle patch artifacts."""

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

from apply_completion_audit_setup_state import (  # noqa: E402
    SETUP_HANDLE_PATCH_SCHEMA_VERSION,
    _patch_binding_errors,
    _patch_errors,
    _patch_source_errors,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_HANDLE_PATCH_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_handle_patch_validation.v1"
)


@dataclass(frozen=True)
class SetupHandlePatchValidationResult:
    validation_schema_version: str
    patch_path: str
    setup_state_path: str
    launch_pack_path: str | None
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


def validate_setup_handle_patch(
    patch_path: Path,
    *,
    setup_state_path: Path,
    launch_pack_path: Path | None = None,
) -> SetupHandlePatchValidationResult:
    errors: list[str] = []
    patch_payload = _load_patch_payload(patch_path, errors)
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        errors.append(
            "completion audit setup handle patch setup state failed validation: "
            + "; ".join(setup_validation.errors)
        )
    setup_payload: dict[str, Any] | None = None
    if setup_validation.ok:
        loaded_setup = load_strict_json_file(setup_state_path)
        if isinstance(loaded_setup, dict):
            setup_payload = loaded_setup
        else:
            errors.append("completion audit setup handle patch setup state root must be an object")
    if patch_payload is not None:
        patch_errors = _patch_errors(patch_payload)
        errors.extend(patch_errors)
        if not patch_errors and setup_payload is not None:
            errors.extend(
                "completion audit setup handle patch source mismatch: " + error
                for error in _patch_source_errors(
                    patch_payload,
                    setup_payload=setup_payload,
                    setup_state_path=setup_state_path,
                )
            )
            errors.extend(_patch_binding_errors(setup_payload, patch_payload))
    return SetupHandlePatchValidationResult(
        validation_schema_version=SETUP_HANDLE_PATCH_VALIDATION_SCHEMA_VERSION,
        patch_path=str(patch_path),
        setup_state_path=str(setup_state_path),
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_patch_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup handle patch path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup handle patch JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup handle patch root must be an object")
        return None
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a source-bound completion-audit setup-handle patch.",
    )
    parser.add_argument("patch", type=Path)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_handle_patch(
        args.patch,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
    )
    if args.json or args.out:
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
    elif result.ok:
        print("Wiii Completion Audit Setup Handle Patch Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Handle Patch Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit setup handle patch path must be a regular file":
        return "completion_audit_setup_handle_patch_path_invalid"
    if error.startswith("completion audit setup handle patch JSON is invalid"):
        return "completion_audit_setup_handle_patch_json_invalid"
    if error == "completion audit setup handle patch root must be an object":
        return "completion_audit_setup_handle_patch_root_invalid"
    if "setup state failed validation" in error or "setup state root" in error:
        return "completion_audit_setup_handle_patch_setup_state_invalid"
    if "source mismatch" in error:
        return "completion_audit_setup_handle_patch_source_mismatch"
    if "duplicate setup checks" in error:
        return "completion_audit_setup_handle_patch_duplicate_check"
    if "unknown setup check" in error:
        return "completion_audit_setup_handle_patch_unknown_check"
    if "source_handle must match a binding token" in error:
        return "completion_audit_setup_handle_patch_unbound_handle"
    if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
        return "completion_audit_setup_handle_patch_privacy_invalid"
    if "schema_version" in error:
        return "completion_audit_setup_handle_patch_schema_mismatch"
    if "SHA-256" in error or "fingerprint" in error:
        return "completion_audit_setup_handle_patch_fingerprint_invalid"
    if "check" in error or "source_handle" in error:
        return "completion_audit_setup_handle_patch_check_invalid"
    if SETUP_HANDLE_PATCH_SCHEMA_VERSION not in error and "setup handle patch" in error:
        return "completion_audit_setup_handle_patch_invalid"
    return "completion_audit_setup_handle_patch_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
