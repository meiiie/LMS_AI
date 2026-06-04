#!/usr/bin/env python3
"""Apply a validated completion-audit setup attestation to setup state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

import apply_completion_audit_setup_state as setup_applier  # noqa: E402
from generate_completion_audit_setup_attestation import (  # noqa: E402
    setup_handle_patch_from_attestation,
)
from strict_json import load_strict_json_file  # noqa: E402
from validate_completion_audit_setup_attestation import (  # noqa: E402
    validate_setup_attestation,
)


SETUP_ATTESTATION_APPLY_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup attestation apply output path must not be a directory"
)
SETUP_ATTESTATION_APPLY_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup attestation apply output path must not be a symlink"
)
SETUP_ATTESTATION_APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation apply output path parent must not be a symlink"
)


def apply_completion_audit_setup_attestation(
    setup_state_path: Path,
    attestation_path: Path,
    *,
    launch_pack_path: Path | None = None,
) -> dict[str, Any]:
    validation = validate_setup_attestation(
        attestation_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not validation.ok:
        raise ValueError(
            "completion audit setup attestation apply attestation failed validation: "
            + "; ".join(validation.errors)
        )

    attestation_payload = load_strict_json_file(attestation_path)
    if not isinstance(attestation_payload, dict):
        raise ValueError(
            "completion audit setup attestation apply attestation root must be an object"
        )
    patch_payload = setup_handle_patch_from_attestation(attestation_payload)

    with tempfile.TemporaryDirectory(prefix="wiii-setup-attestation-apply-") as temp_dir:
        patch_path = Path(temp_dir) / "setup-handle-patch.json"
        safe_write_report_text(
            patch_path,
            json.dumps(patch_payload, indent=2, sort_keys=True).rstrip("\n") + "\n",
        )
        return setup_applier.apply_completion_audit_setup_state(
            setup_state_path,
            patch_path,
            launch_pack_path=launch_pack_path,
        )


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(SETUP_ATTESTATION_APPLY_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(SETUP_ATTESTATION_APPLY_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(SETUP_ATTESTATION_APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Apply a source-bound setup attestation to completion-audit setup "
            "state without requiring a persisted setup-handle patch."
        ),
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument("attestation", type=Path)
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
        result = apply_completion_audit_setup_attestation(
            args.setup_state,
            args.attestation,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": setup_applier.SETUP_STATE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "attestation failed validation" in error:
        return "completion_audit_setup_attestation_apply_attestation_invalid"
    if "source failed validation" in error:
        return "completion_audit_setup_attestation_apply_source_invalid"
    if "patch" in error:
        return "completion_audit_setup_attestation_apply_derived_patch_invalid"
    if "result failed validation" in error:
        return "completion_audit_setup_attestation_apply_result_invalid"
    if error == SETUP_ATTESTATION_APPLY_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_attestation_apply_output_path_directory"
    if error == SETUP_ATTESTATION_APPLY_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_apply_output_path_symlink"
    if error == SETUP_ATTESTATION_APPLY_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_apply_output_path_parent_symlink"
    return "completion_audit_setup_attestation_apply_failed"


if __name__ == "__main__":
    raise SystemExit(main())
