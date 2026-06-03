#!/usr/bin/env python3
"""Generate strict setup attestations from selected template options."""

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

from generate_completion_audit_setup_attestation import (  # noqa: E402
    generate_completion_audit_setup_attestation,
    setup_handle_patch_from_attestation,
)
from strict_json import load_strict_json_file  # noqa: E402
from validate_completion_audit_setup_attestation_template import (  # noqa: E402
    validate_setup_attestation_template,
)


ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup attestation-from-template output path must not be a directory"
)
ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup attestation-from-template output path must not be a symlink"
)
ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation-from-template output path parent must not be a symlink"
)
UNKNOWN_SELECTION_ERROR = (
    "completion audit setup attestation-from-template selected spec must come from template options"
)
DUPLICATE_SELECTION_ERROR = (
    "completion audit setup attestation-from-template must not select multiple options for the same setup check"
)
INCOMPLETE_SELECTION_ERROR = (
    "completion audit setup attestation-from-template selections must cover all pending setup checks"
)


def generate_completion_audit_setup_attestation_from_template(
    template_path: Path,
    selected_specs: list[str],
    *,
    setup_state_path: Path,
    setup_handle_plan_path: Path | None = None,
    launch_pack_path: Path | None = None,
    require_all_pending: bool = False,
) -> dict[str, Any]:
    validation = validate_setup_attestation_template(
        template_path,
        setup_handle_plan_path=setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not validation.ok:
        raise ValueError(
            "completion audit setup attestation-from-template template failed "
            "validation: "
            + "; ".join(validation.errors)
        )
    template = load_strict_json_file(template_path)
    if not isinstance(template, dict):
        raise ValueError("completion audit setup attestation template root must be an object")
    option_keys = _option_keys(template)
    if not selected_specs:
        raise ValueError("completion audit setup attestation-from-template requires --select")
    selected_keys: set[tuple[str, str, str]] = set()
    for spec in selected_specs:
        key = _spec_key(spec)
        if spec not in option_keys:
            raise ValueError(UNKNOWN_SELECTION_ERROR)
        if key in selected_keys:
            raise ValueError(DUPLICATE_SELECTION_ERROR)
        selected_keys.add(key)
    if require_all_pending and selected_keys != set(option_keys.values()):
        raise ValueError(INCOMPLETE_SELECTION_ERROR)
    return generate_completion_audit_setup_attestation(
        setup_state_path,
        selected_specs,
        launch_pack_path=launch_pack_path,
    )


def _option_keys(template: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for requirement in template.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        for check in requirement.get("setup_checks", []):
            if not isinstance(check, dict):
                continue
            options = check.get("attestation_spec_options")
            if not isinstance(options, list):
                continue
            for option in options:
                if isinstance(option, str):
                    result[option] = _spec_key(option)
    return result


def _spec_key(value: str) -> tuple[str, str, str]:
    if "=" not in value:
        raise ValueError(
            "completion audit setup attestation-from-template selected spec is malformed"
        )
    left, _right = value.split("=", 1)
    parts = left.split(":")
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            "completion audit setup attestation-from-template selected spec is malformed"
        )
    return (parts[0], parts[1], parts[2])


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a strict setup attestation by selecting safe options from "
            "a validated setup attestation template."
        ),
    )
    parser.add_argument("template", type=Path)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--setup-handle-plan", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        help="An attestation spec copied exactly from the template options.",
    )
    parser.add_argument(
        "--require-all-pending",
        action="store_true",
        help="Require one selected option for every pending setup check.",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--patch-out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        validate_output_path(args.patch_out)
        attestation = generate_completion_audit_setup_attestation_from_template(
            args.template,
            args.select,
            setup_state_path=args.setup_state,
            setup_handle_plan_path=args.setup_handle_plan,
            launch_pack_path=args.launch_pack,
            require_all_pending=args.require_all_pending,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(attestation, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    if args.patch_out:
        patch = setup_handle_patch_from_attestation(attestation)
        safe_write_report_text(
            args.patch_out,
            json.dumps(patch, indent=2, sort_keys=True).rstrip("\n") + "\n",
        )
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": "wiii.completion_audit_setup_attestation_from_template.v1",
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "template failed validation" in error:
        return "completion_audit_setup_attestation_from_template_template_invalid"
    if "requires --select" in error:
        return "completion_audit_setup_attestation_from_template_no_selection"
    if "must come from template options" in error:
        return "completion_audit_setup_attestation_from_template_unknown_selection"
    if "multiple options for the same setup check" in error:
        return "completion_audit_setup_attestation_from_template_duplicate_check"
    if "selections must cover all pending setup checks" in error:
        return "completion_audit_setup_attestation_from_template_incomplete_selection"
    if "selected spec is malformed" in error:
        return "completion_audit_setup_attestation_from_template_malformed_selection"
    if error == ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_attestation_from_template_output_path_directory"
    if error == ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_from_template_output_path_symlink"
    if error == ATTESTATION_FROM_TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_from_template_output_path_parent_symlink"
    return "completion_audit_setup_attestation_from_template_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
