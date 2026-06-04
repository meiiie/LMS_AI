#!/usr/bin/env python3
"""Validate completion-audit setup attestation artifacts."""

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
    _patch_binding_errors,
    _patch_errors,
    _patch_source_errors,
)
from generate_completion_audit_setup_attestation import (  # noqa: E402
    SETUP_ATTESTATION_SCHEMA_VERSION,
    _attestation_errors,
    _attestation_source_errors,
    setup_handle_patch_from_attestation,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_ATTESTATION_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_attestation_validation.v1"
)


@dataclass(frozen=True)
class SetupAttestationValidationResult:
    validation_schema_version: str
    attestation_path: str
    setup_state_path: str
    launch_pack_path: str | None
    patch_path: str | None
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


def validate_setup_attestation(
    attestation_path: Path,
    *,
    setup_state_path: Path,
    launch_pack_path: Path | None = None,
    patch_path: Path | None = None,
) -> SetupAttestationValidationResult:
    errors: list[str] = []
    payload = _load_attestation_payload(attestation_path, errors)
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        errors.append(
            "completion audit setup attestation setup state failed validation: "
            + "; ".join(setup_validation.errors)
        )
    setup_payload: dict[str, Any] | None = None
    if setup_validation.ok:
        loaded_setup = load_strict_json_file(setup_state_path)
        if isinstance(loaded_setup, dict):
            setup_payload = loaded_setup
        else:
            errors.append(
                "completion audit setup attestation setup state root must be an object"
            )

    expected_patch: dict[str, Any] | None = None
    if payload is not None:
        errors.extend(_attestation_errors(payload))
        if setup_payload is not None:
            errors.extend(
                "completion audit setup attestation source mismatch: " + error
                for error in _attestation_source_errors(
                    payload,
                    setup_payload=setup_payload,
                    setup_state_path=setup_state_path,
                )
            )
            expected_patch = setup_handle_patch_from_attestation(payload)
            errors.extend(_patch_errors(expected_patch))
            if not errors:
                errors.extend(
                    "completion audit setup attestation patch source mismatch: " + error
                    for error in _patch_source_errors(
                        expected_patch,
                        setup_payload=setup_payload,
                        setup_state_path=setup_state_path,
                    )
                )
                errors.extend(_patch_binding_errors(setup_payload, expected_patch))

    if patch_path is not None and expected_patch is not None:
        patch_payload = _load_patch_payload(patch_path, errors)
        if patch_payload is not None and patch_payload != expected_patch:
            errors.append(
                "completion audit setup attestation patch must match attestation"
            )

    return SetupAttestationValidationResult(
        validation_schema_version=SETUP_ATTESTATION_VALIDATION_SCHEMA_VERSION,
        attestation_path=str(attestation_path),
        setup_state_path=str(setup_state_path),
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        patch_path=str(patch_path) if patch_path else None,
        errors=errors,
    )


def _load_attestation_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup attestation path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup attestation JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup attestation root must be an object")
        return None
    return payload


def _load_patch_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup attestation patch path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup attestation patch JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup attestation patch root must be an object")
        return None
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a source-bound completion-audit setup attestation.",
    )
    parser.add_argument("attestation", type=Path)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--patch", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_attestation(
        args.attestation,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
        patch_path=args.patch,
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
        print("Wiii Completion Audit Setup Attestation Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Attestation Validation: FAIL\n"
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
    if error == "completion audit setup attestation path must be a regular file":
        return "completion_audit_setup_attestation_path_invalid"
    if error.startswith("completion audit setup attestation JSON is invalid"):
        return "completion_audit_setup_attestation_json_invalid"
    if error == "completion audit setup attestation root must be an object":
        return "completion_audit_setup_attestation_root_invalid"
    if "setup state failed validation" in error or "setup state root" in error:
        return "completion_audit_setup_attestation_setup_state_invalid"
    if "source mismatch" in error:
        return "completion_audit_setup_attestation_source_mismatch"
    if "patch must match attestation" in error:
        return "completion_audit_setup_attestation_patch_mismatch"
    if "patch path must be" in error:
        return "completion_audit_setup_attestation_patch_path_invalid"
    if "patch JSON is invalid" in error:
        return "completion_audit_setup_attestation_patch_json_invalid"
    if "patch root must be" in error:
        return "completion_audit_setup_attestation_patch_root_invalid"
    if "duplicate setup checks" in error:
        return "completion_audit_setup_attestation_duplicate_check"
    if "unknown setup check" in error:
        return "completion_audit_setup_attestation_unknown_check"
    if "source_handle must match a binding token" in error:
        return "completion_audit_setup_attestation_unbound_handle"
    if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
        return "completion_audit_setup_attestation_privacy_invalid"
    if "schema_version" in error:
        return "completion_audit_setup_attestation_schema_mismatch"
    if "SHA-256" in error or "fingerprint" in error:
        return "completion_audit_setup_attestation_fingerprint_invalid"
    if "safe token handle" in error:
        return "completion_audit_setup_attestation_unsafe_token"
    if "evidence_kind" in error:
        return "completion_audit_setup_attestation_evidence_kind_invalid"
    if SETUP_ATTESTATION_SCHEMA_VERSION not in error and "setup attestation" in error:
        return "completion_audit_setup_attestation_invalid"
    return "completion_audit_setup_attestation_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
