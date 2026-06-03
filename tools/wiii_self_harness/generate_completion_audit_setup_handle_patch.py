#!/usr/bin/env python3
"""Generate a source-bound completion-audit setup-handle patch."""

from __future__ import annotations

import argparse
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
    _sha256_file,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


PATCH_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup handle patch output path must not be a directory"
)
PATCH_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup handle patch output path must not be a symlink"
)
PATCH_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup handle patch output path parent must not be a symlink"
)


def generate_completion_audit_setup_handle_patch(
    setup_state_path: Path,
    handle_specs: list[str],
    *,
    launch_pack_path: Path | None = None,
) -> dict[str, Any]:
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        raise ValueError(
            "completion audit setup handle patch source setup state failed validation: "
            + "; ".join(setup_validation.errors)
        )
    setup_payload = load_strict_json_file(setup_state_path)
    if not isinstance(setup_payload, dict):
        raise ValueError("completion audit setup state root must be an object")
    checks = [_parse_handle_spec(spec) for spec in handle_specs]
    patch = {
        "schema_version": SETUP_HANDLE_PATCH_SCHEMA_VERSION,
        "ok": True,
        "setup_state_sha256": _sha256_file(setup_state_path),
        "setup_state_schema_version": setup_payload.get("schema_version"),
        "setup_state_fingerprint_sha256": setup_payload.get(
            "setup_state_fingerprint_sha256"
        ),
        "checks": checks,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
        },
    }
    errors = _patch_errors(patch)
    if not errors:
        errors.extend(
            _patch_source_errors(
                patch,
                setup_payload=setup_payload,
                setup_state_path=setup_state_path,
            )
        )
        errors.extend(_patch_binding_errors(setup_payload, patch))
    if errors:
        raise ValueError(
            "completion audit setup handle patch generation failed validation: "
            + "; ".join(errors)
        )
    return patch


def _parse_handle_spec(value: str) -> dict[str, str]:
    if "=" not in value:
        raise ValueError(
            "completion audit setup handle patch handle spec must be "
            "requirement_id:category:key=source_handle"
        )
    left, source_handle = value.split("=", 1)
    parts = left.split(":")
    if len(parts) != 3 or not all(parts) or not source_handle:
        raise ValueError(
            "completion audit setup handle patch handle spec must be "
            "requirement_id:category:key=source_handle"
        )
    requirement_id, category, key = parts
    return {
        "requirement_id": requirement_id,
        "category": category,
        "key": key,
        "source_handle": source_handle,
    }


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(PATCH_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(PATCH_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(PATCH_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a source-bound setup-handle patch from a validated "
            "completion-audit setup state."
        ),
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument(
        "--handle",
        action="append",
        default=[],
        help=(
            "Setup handle as requirement_id:category:key=source_handle. "
            "Repeat once per setup check to mark present."
        ),
    )
    parser.add_argument(
        "--launch-pack",
        type=Path,
        default=None,
        help="Optional launch pack source that the setup state must continue to match.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        patch = generate_completion_audit_setup_handle_patch(
            args.setup_state,
            args.handle,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(patch, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_HANDLE_PATCH_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "source setup state failed validation" in error:
        return "completion_audit_setup_handle_patch_source_invalid"
    if "handle spec must be" in error:
        return "completion_audit_setup_handle_patch_handle_spec_invalid"
    if "generation failed validation" in error:
        if "source_handle must match a binding token" in error:
            return "completion_audit_setup_handle_patch_unbound_handle"
        if "unknown setup check" in error:
            return "completion_audit_setup_handle_patch_unknown_check"
        if "duplicate setup checks" in error:
            return "completion_audit_setup_handle_patch_duplicate_check"
        if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
            return "completion_audit_setup_handle_patch_privacy_invalid"
        return "completion_audit_setup_handle_patch_generation_validation_failed"
    if error == PATCH_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_handle_patch_output_path_directory"
    if error == PATCH_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_handle_patch_output_path_symlink"
    if error == PATCH_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_handle_patch_output_path_parent_symlink"
    return "completion_audit_setup_handle_patch_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
