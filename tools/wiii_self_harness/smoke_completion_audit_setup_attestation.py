#!/usr/bin/env python3
"""Smoke-test setup-attestation handoff through dispatch dry-run unlock."""

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

import apply_completion_audit_setup_attestation as setup_attestation_applier  # noqa: E402
import generate_completion_audit_dispatch_gate as dispatch_gate_generator  # noqa: E402
from generate_completion_audit_setup_attestation import (  # noqa: E402
    setup_handle_patch_from_attestation,
)
import generate_completion_audit_setup_attestation_from_template as template_attestor  # noqa: E402
from run_completion_audit_dispatch_gate import (  # noqa: E402
    run_completion_audit_dispatch_gate,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_gate as dispatch_gate_validator  # noqa: E402
import validate_completion_audit_dispatch_run as dispatch_run_validator  # noqa: E402
import validate_completion_audit_setup_attestation as attestation_validator  # noqa: E402
import validate_completion_audit_setup_attestation_template as template_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_state_validator  # noqa: E402


SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_attestation_smoke.v1"
)
SMOKE_OUTPUT_DIR_FILE_ERROR = (
    "completion audit setup attestation smoke output dir must be a directory"
)
SMOKE_OUTPUT_DIR_SYMLINK_ERROR = (
    "completion audit setup attestation smoke output dir must not be a symlink"
)
SMOKE_OUTPUT_DIR_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation smoke output dir parent must not be a symlink"
)
SMOKE_JSON_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup attestation smoke json output path must not be a directory"
)
SMOKE_JSON_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup attestation smoke json output path must not be a symlink"
)
SMOKE_JSON_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation smoke json output path parent must not be a symlink"
)
SMOKE_JSON_OUTPUT_PATH_INSIDE_OUT_DIR_ERROR = (
    "completion audit setup attestation smoke json output path must be outside output dir"
)


def run_completion_audit_setup_attestation_smoke(
    *,
    launch_pack_path: Path,
    setup_state_path: Path,
    setup_handle_plan_path: Path,
    template_path: Path,
    out_dir: Path,
    json_out: Path | None = None,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    validate_output_dir(out_dir)
    validate_json_output_path(json_out, out_dir=out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    template_validation = template_validator.validate_setup_attestation_template(
        template_path,
        setup_handle_plan_path=setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    if template_validation["ok"] is not True:
        raise ValueError(
            "completion audit setup attestation smoke template validation failed: "
            + ", ".join(template_validation["error_codes"])
        )

    template = load_strict_json_file(template_path)
    if not isinstance(template, dict):
        raise ValueError("completion audit setup attestation smoke template root invalid")
    setup_handle_plan = load_strict_json_file(setup_handle_plan_path)
    if not isinstance(setup_handle_plan, dict):
        raise ValueError(
            "completion audit setup attestation smoke setup handle plan root invalid"
        )
    selected_specs = _select_one_option_per_pending_check(template)

    attestation = template_attestor.generate_completion_audit_setup_attestation_from_template(
        template_path,
        selected_specs,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        launch_pack_path=launch_pack_path,
        require_all_pending=True,
    )
    attestation_path = out_dir / "setup-attestation.json"
    _write_json(attestation_path, attestation)
    patch_path = out_dir / "setup-handle-patch.json"
    _write_json(patch_path, setup_handle_patch_from_attestation(attestation))

    attestation_validation = attestation_validator.validate_setup_attestation(
        attestation_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
        patch_path=patch_path,
    ).to_dict()
    if attestation_validation["ok"] is not True:
        raise ValueError(
            "completion audit setup attestation smoke attestation validation failed: "
            + ", ".join(attestation_validation["error_codes"])
        )

    attested_setup = setup_attestation_applier.apply_completion_audit_setup_attestation(
        setup_state_path,
        attestation_path,
        launch_pack_path=launch_pack_path,
    )
    attested_setup_path = out_dir / "setup-state-attested.json"
    _write_json(attested_setup_path, attested_setup)

    attested_setup_validation = setup_state_validator.validate_setup_state(
        attested_setup_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    if attested_setup_validation["ok"] is not True:
        raise ValueError(
            "completion audit setup attestation smoke applied setup validation failed: "
            + ", ".join(attested_setup_validation["error_codes"])
        )

    dispatch_gate = dispatch_gate_generator.generate_completion_audit_dispatch_gate(
        launch_pack_path,
        attested_setup_path,
    ).to_dict()
    dispatch_gate_path = out_dir / "dispatch-gate-attested.json"
    _write_json(dispatch_gate_path, dispatch_gate)

    dispatch_gate_validation = dispatch_gate_validator.validate_dispatch_gate(
        dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=attested_setup_path,
    ).to_dict()
    if dispatch_gate_validation["ok"] is not True:
        raise ValueError(
            "completion audit setup attestation smoke dispatch gate validation failed: "
            + ", ".join(dispatch_gate_validation["error_codes"])
        )

    dispatch_run = run_completion_audit_dispatch_gate(
        dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=attested_setup_path,
        repo_root=repo_root,
    ).to_dict()
    dispatch_run_path = out_dir / "dispatch-run-dry.json"
    _write_json(dispatch_run_path, dispatch_run)

    dispatch_run_validation = dispatch_run_validator.validate_dispatch_run(
        dispatch_run_path,
        dispatch_gate_path=dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=attested_setup_path,
        repo_root=repo_root,
    ).to_dict()
    if dispatch_run_validation["ok"] is not True:
        raise ValueError(
            "completion audit setup attestation smoke dispatch run validation failed: "
            + ", ".join(dispatch_run_validation["error_codes"])
        )

    payload = _smoke_payload(
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        template_path=template_path,
        out_dir=out_dir,
        template=template,
        setup_handle_plan=setup_handle_plan,
        selected_specs=selected_specs,
        attestation=attestation,
        attested_setup=attested_setup,
        dispatch_gate=dispatch_gate,
        dispatch_run=dispatch_run,
        template_validation=template_validation,
        attestation_validation=attestation_validation,
        attested_setup_validation=attested_setup_validation,
        dispatch_gate_validation=dispatch_gate_validation,
        dispatch_run_validation=dispatch_run_validation,
    )
    _assert_expected_unlock_smoke(payload)
    if json_out is not None:
        _write_json(json_out, payload)
    return payload


def validate_output_dir(out_dir: Path) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(SMOKE_OUTPUT_DIR_FILE_ERROR)
    if out_dir.is_symlink():
        raise ValueError(SMOKE_OUTPUT_DIR_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_dir):
        raise ValueError(SMOKE_OUTPUT_DIR_PARENT_SYMLINK_ERROR)


def validate_json_output_path(path: Path | None, *, out_dir: Path) -> None:
    if path is None:
        return
    if _path_is_inside_directory(path=path, directory=out_dir):
        raise ValueError(SMOKE_JSON_OUTPUT_PATH_INSIDE_OUT_DIR_ERROR)
    if path.exists() and path.is_dir():
        raise ValueError(SMOKE_JSON_OUTPUT_PATH_DIRECTORY_ERROR)
    if path.is_symlink():
        raise ValueError(SMOKE_JSON_OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(path):
        raise ValueError(SMOKE_JSON_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _select_one_option_per_pending_check(template: dict[str, Any]) -> list[str]:
    selected: list[str] = []
    for requirement in template.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        for check in requirement.get("setup_checks", []):
            if not isinstance(check, dict):
                continue
            if check.get("status") != "pending_operator_attestation":
                continue
            options = check.get("attestation_spec_options")
            if not isinstance(options, list) or not options:
                raise ValueError(
                    "completion audit setup attestation smoke pending check lacks options"
                )
            first_option = options[0]
            if not isinstance(first_option, str) or not first_option:
                raise ValueError(
                    "completion audit setup attestation smoke option is invalid"
                )
            selected.append(first_option)
    if not selected:
        raise ValueError(
            "completion audit setup attestation smoke requires at least one pending setup check"
        )
    return selected


def _smoke_payload(
    *,
    launch_pack_path: Path,
    setup_state_path: Path,
    setup_handle_plan_path: Path,
    template_path: Path,
    out_dir: Path,
    template: dict[str, Any],
    setup_handle_plan: dict[str, Any],
    selected_specs: list[str],
    attestation: dict[str, Any],
    attested_setup: dict[str, Any],
    dispatch_gate: dict[str, Any],
    dispatch_run: dict[str, Any],
    template_validation: dict[str, Any],
    attestation_validation: dict[str, Any],
    attested_setup_validation: dict[str, Any],
    dispatch_gate_validation: dict[str, Any],
    dispatch_run_validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION,
        "ok": True,
        "dry_run_only": True,
        "source_paths": {
            "launch_pack": str(launch_pack_path),
            "setup_state": str(setup_state_path),
            "setup_handle_plan": str(setup_handle_plan_path),
            "setup_attestation_template": str(template_path),
        },
        "out_dir": str(out_dir),
        "generated_reports": [
            "setup-attestation.json",
            "setup-handle-patch.json",
            "setup-state-attested.json",
            "dispatch-gate-attested.json",
            "dispatch-run-dry.json",
        ],
        "source_fingerprints": {
            "launch_setup_fingerprint_sha256": str(
                dispatch_gate.get("launch_setup_fingerprint_sha256") or ""
            ),
            "setup_state_fingerprint_sha256": str(
                setup_handle_plan.get("setup_state_fingerprint_sha256") or ""
            ),
            "setup_handle_plan_fingerprint_sha256": str(
                template.get("setup_handle_plan_fingerprint_sha256") or ""
            ),
            "setup_attestation_template_fingerprint_sha256": str(
                template.get("setup_attestation_template_fingerprint_sha256") or ""
            ),
            "setup_attestation_fingerprint_sha256": str(
                attestation.get("setup_attestation_fingerprint_sha256") or ""
            ),
            "attested_setup_state_fingerprint_sha256": str(
                attested_setup.get("setup_state_fingerprint_sha256") or ""
            ),
            "dispatch_gate_fingerprint_sha256": str(
                dispatch_gate.get("dispatch_gate_fingerprint_sha256") or ""
            ),
            "dispatch_run_fingerprint_sha256": str(
                dispatch_run.get("dispatch_run_fingerprint_sha256") or ""
            ),
        },
        "template_pending_setup_check_count": int(
            template.get("pending_setup_check_count") or 0
        ),
        "selected_attestation_count": len(selected_specs),
        "attestation_count": int(attestation.get("attestation_count") or 0),
        "attested_setup_dispatch_ready": bool(attested_setup.get("dispatch_ready")),
        "dispatch_gate_ready": bool(dispatch_gate.get("dispatch_ready")),
        "dispatch_run_ok": bool(dispatch_run.get("ok")),
        "dispatch_run_dry_run": bool(dispatch_run.get("dry_run")),
        "dispatch_run_command_count": int(dispatch_run.get("command_count") or 0),
        "dispatch_run_executed_command_count": int(
            dispatch_run.get("executed_command_count") or 0
        ),
        "validation": {
            "template": template_validation,
            "setup_attestation": attestation_validation,
            "attested_setup_state": attested_setup_validation,
            "dispatch_gate": dispatch_gate_validation,
            "dispatch_run": dispatch_run_validation,
        },
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
            "raw_output_included": False,
        },
        "errors": [],
        "error_codes": [],
        "error_code_counts": {},
    }


def _assert_expected_unlock_smoke(payload: dict[str, Any]) -> None:
    pending_count = payload["template_pending_setup_check_count"]
    if pending_count <= 0:
        raise ValueError("setup attestation smoke must exercise pending setup checks")
    if payload["selected_attestation_count"] != pending_count:
        raise ValueError("setup attestation smoke must select every pending check")
    if payload["attestation_count"] != pending_count:
        raise ValueError("setup attestation smoke attestation count mismatch")
    if payload["attested_setup_dispatch_ready"] is not True:
        raise ValueError("setup attestation smoke must ready applied setup state")
    if payload["dispatch_gate_ready"] is not True:
        raise ValueError("setup attestation smoke must unlock dispatch gate")
    if payload["dispatch_run_ok"] is not True:
        raise ValueError("setup attestation smoke dispatch dry-run must pass")
    if payload["dispatch_run_dry_run"] is not True:
        raise ValueError("setup attestation smoke must stay dry-run only")
    if payload["dispatch_run_executed_command_count"] != 0:
        raise ValueError("setup attestation smoke must not execute commands")
    if payload["dispatch_run_command_count"] <= 0:
        raise ValueError("setup attestation smoke must materialize commands")
    for field, value in payload["privacy"].items():
        if value is not False:
            raise ValueError(f"setup attestation smoke privacy.{field} must be false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test the completion-audit setup-attestation path by selecting "
            "one safe template option per pending setup check, applying it to a "
            "sidecar setup state, and materializing dispatch commands in dry-run."
        ),
    )
    parser.add_argument("--launch-pack", type=Path, required=True)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--setup-handle-plan", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/wiii-completion-audit-setup-attestation-smoke"),
    )
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_completion_audit_setup_attestation_smoke(
            launch_pack_path=args.launch_pack,
            setup_state_path=args.setup_state,
            setup_handle_plan_path=args.setup_handle_plan,
            template_path=args.template,
            out_dir=args.out_dir,
            json_out=args.json_out,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Wiii Completion Audit Setup Attestation Smoke: FAIL\n- {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        "Wiii Completion Audit Setup Attestation Smoke: PASS\n"
        f"- selected_attestations: {payload['selected_attestation_count']}\n"
        f"- materialized_commands: {payload['dispatch_run_command_count']}\n"
        f"- out_dir: {payload['out_dir']}"
    )
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    safe_write_report_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True).rstrip("\n") + "\n",
    )


def _path_is_inside_directory(*, path: Path, directory: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
    except ValueError:
        return False
    return True


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


if __name__ == "__main__":
    raise SystemExit(main())
