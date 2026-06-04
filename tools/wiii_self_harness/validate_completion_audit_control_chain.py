#!/usr/bin/env python3
"""Validate the source-bound completion-audit control chain."""

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

from strict_json import load_strict_json_file  # noqa: E402
from run_completion_audit_dispatch_gate import _sha256_file  # noqa: E402
import validate_completion_audit_dispatch_gate as dispatch_gate_validator  # noqa: E402
import validate_completion_audit_dispatch_diagnostics as dispatch_diagnostics_validator  # noqa: E402
import validate_completion_audit_dispatch_run as dispatch_run_validator  # noqa: E402
import validate_completion_audit_launch_pack as launch_pack_validator  # noqa: E402
import validate_completion_audit_readiness as readiness_validator  # noqa: E402
import validate_completion_audit_run_plan as run_plan_validator  # noqa: E402
import validate_completion_audit_setup_gaps as setup_gap_validator  # noqa: E402
import validate_completion_audit_setup_handle_plan as setup_handle_plan_validator  # noqa: E402
import validate_completion_audit_setup_attestation as setup_attestation_validator  # noqa: E402
import validate_completion_audit_setup_attestation_smoke as setup_attestation_smoke_validator  # noqa: E402
import validate_completion_audit_setup_attestation_template as setup_attestation_template_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_state_validator  # noqa: E402


CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_control_chain_validation.v1"
)
CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit control chain output path must not be a directory"
)
CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit control chain output path must not be a symlink"
)
CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit control chain output path parent must not be a symlink"
)


@dataclass(frozen=True)
class ControlChainValidationResult:
    validation_schema_version: str
    readiness_report_path: str
    run_plan_path: str
    launch_pack_path: str
    setup_state_path: str
    setup_handle_plan_path: str
    setup_gap_report_path: str | None
    setup_gap_markdown_report_path: str | None
    setup_attestation_template_path: str | None
    setup_attestation_smoke_path: str | None
    setup_attestation_smoke_out_dir: str | None
    setup_attestation_path: str | None
    setup_attestation_patch_path: str | None
    attested_setup_state_path: str | None
    attested_dispatch_gate_path: str | None
    attested_dispatch_run_path: str | None
    dispatch_gate_path: str
    dispatch_run_path: str
    dispatch_diagnostics_path: str | None
    recovery_control_chain_path: str | None
    recovery_checkpoint_path: str | None
    readiness_preflight_dirs: list[str]
    control_chain_ready: bool
    dispatch_ready: bool
    recovery_chain_ready: bool | None
    recovery_release_gate_ready: bool | None
    recovery_operator_setup_required: bool | None
    recovery_resume_state: str | None
    recovery_required_resume_inputs: list[str] | None
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


def validate_control_chain(
    *,
    readiness_report_path: Path,
    run_plan_path: Path,
    launch_pack_path: Path,
    setup_state_path: Path,
    setup_handle_plan_path: Path,
    dispatch_gate_path: Path,
    dispatch_run_path: Path,
    setup_gap_report_path: Path | None = None,
    setup_gap_markdown_report_path: Path | None = None,
    setup_attestation_template_path: Path | None = None,
    setup_attestation_smoke_path: Path | None = None,
    setup_attestation_smoke_out_dir: Path | None = None,
    setup_attestation_path: Path | None = None,
    setup_attestation_patch_path: Path | None = None,
    attested_setup_state_path: Path | None = None,
    attested_dispatch_gate_path: Path | None = None,
    attested_dispatch_run_path: Path | None = None,
    dispatch_diagnostics_path: Path | None = None,
    recovery_control_chain_path: Path | None = None,
    recovery_checkpoint_path: Path | None = None,
    diagnostics_preflight_source_dirs: list[Path] | None = None,
    readiness_markdown_report_path: Path | None = None,
    readiness_preflight_dir: Path | None = None,
    readiness_preflight_dirs: list[Path] | None = None,
    self_harness_report_bundle_path: Path | None = None,
    run_plan_markdown_path: Path | None = None,
    launch_pack_markdown_path: Path | None = None,
    repo_root: Path = Path("."),
) -> ControlChainValidationResult:
    errors: list[str] = []
    source_dirs = _combined_preflight_dirs(
        readiness_preflight_dir,
        readiness_preflight_dirs,
    )
    errors.extend(
        _validator_errors(
            "readiness report",
            readiness_validator.validate_readiness_report(
                readiness_report_path,
                preflight_dirs=source_dirs,
                markdown_report_path=readiness_markdown_report_path,
                self_harness_report_bundle_path=self_harness_report_bundle_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "run plan",
            run_plan_validator.validate_run_plan(
                run_plan_path,
                readiness_report_path=readiness_report_path,
                readiness_markdown_report_path=readiness_markdown_report_path,
                readiness_preflight_dirs=source_dirs,
                self_harness_report_bundle_path=self_harness_report_bundle_path,
                markdown_report_path=run_plan_markdown_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "launch pack",
            launch_pack_validator.validate_launch_pack(
                launch_pack_path,
                run_plan_path=run_plan_path,
                repo_root=repo_root,
                markdown_report_path=launch_pack_markdown_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "setup state",
            setup_state_validator.validate_setup_state(
                setup_state_path,
                launch_pack_path=launch_pack_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "setup handle plan",
            setup_handle_plan_validator.validate_setup_handle_plan(
                setup_handle_plan_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ),
        )
    )
    if setup_gap_report_path is not None:
        errors.extend(
            _validator_errors(
                "setup gap report",
                setup_gap_validator.validate_setup_gap_report(
                    setup_gap_report_path,
                    setup_handle_plan_path=setup_handle_plan_path,
                    markdown_report_path=setup_gap_markdown_report_path,
                ),
            )
        )
    if setup_attestation_template_path is not None:
        errors.extend(
            _validator_errors(
                "setup attestation template",
                setup_attestation_template_validator.validate_setup_attestation_template(
                    setup_attestation_template_path,
                    setup_handle_plan_path=setup_handle_plan_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                ),
            )
        )
    if setup_attestation_smoke_path is not None:
        if setup_attestation_template_path is None:
            errors.append(
                "completion audit control chain setup attestation smoke requires template source"
            )
        else:
            errors.extend(
                _validator_errors(
                    "setup attestation smoke",
                    setup_attestation_smoke_validator.validate_completion_audit_setup_attestation_smoke(
                        setup_attestation_smoke_path,
                        launch_pack_path=launch_pack_path,
                        setup_state_path=setup_state_path,
                        setup_handle_plan_path=setup_handle_plan_path,
                        template_path=setup_attestation_template_path,
                        out_dir=setup_attestation_smoke_out_dir,
                        repo_root=repo_root,
                    ),
                )
            )
    if setup_attestation_path is not None:
        errors.extend(
            _validator_errors(
                "setup attestation",
                setup_attestation_validator.validate_setup_attestation(
                    setup_attestation_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                    patch_path=setup_attestation_patch_path,
                ),
            )
        )
    if attested_setup_state_path is not None:
        errors.extend(
            _validator_errors(
                "attested setup state",
                setup_state_validator.validate_setup_state(
                    attested_setup_state_path,
                    launch_pack_path=launch_pack_path,
                ),
            )
        )
    if attested_dispatch_gate_path is not None:
        if attested_setup_state_path is None:
            errors.append(
                "completion audit control chain attested dispatch gate requires attested setup state"
            )
        else:
            errors.extend(
                _validator_errors(
                    "attested dispatch gate",
                    dispatch_gate_validator.validate_dispatch_gate(
                        attested_dispatch_gate_path,
                        launch_pack_path=launch_pack_path,
                        setup_state_path=attested_setup_state_path,
                    ),
                )
            )
    if attested_dispatch_run_path is not None:
        if attested_setup_state_path is None or attested_dispatch_gate_path is None:
            errors.append(
                "completion audit control chain attested dispatch run requires attested setup state and gate"
            )
        else:
            errors.extend(
                _validator_errors(
                    "attested dispatch run",
                    dispatch_run_validator.validate_dispatch_run(
                        attested_dispatch_run_path,
                        dispatch_gate_path=attested_dispatch_gate_path,
                        launch_pack_path=launch_pack_path,
                        setup_state_path=attested_setup_state_path,
                        repo_root=repo_root,
                    ),
                )
            )
    errors.extend(
        _validator_errors(
            "dispatch gate",
            dispatch_gate_validator.validate_dispatch_gate(
                dispatch_gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "dispatch run",
            dispatch_run_validator.validate_dispatch_run(
                dispatch_run_path,
                dispatch_gate_path=dispatch_gate_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                repo_root=repo_root,
            ),
        )
    )
    if dispatch_diagnostics_path is not None:
        errors.extend(
            _validator_errors(
                "dispatch diagnostics",
                dispatch_diagnostics_validator.validate_dispatch_diagnostics(
                    dispatch_diagnostics_path,
                    dispatch_run_path=dispatch_run_path,
                    dispatch_gate_path=dispatch_gate_path,
                    launch_pack_path=launch_pack_path,
                    setup_state_path=setup_state_path,
                    preflight_source_dirs=diagnostics_preflight_source_dirs or [],
                    repo_root=repo_root,
                ),
            )
        )
    if recovery_checkpoint_path is not None:
        import validate_completion_audit_recovery_checkpoint as recovery_checkpoint_validator

        errors.extend(
            _validator_errors(
                "recovery checkpoint",
                recovery_checkpoint_validator.validate_recovery_checkpoint(
                    recovery_checkpoint_path,
                    recovery_control_chain_path=recovery_control_chain_path,
                    repo_root=repo_root,
                ),
            )
        )

    payloads = _load_chain_payloads(
        readiness_report_path=readiness_report_path,
        run_plan_path=run_plan_path,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        dispatch_gate_path=dispatch_gate_path,
        dispatch_run_path=dispatch_run_path,
        setup_gap_report_path=setup_gap_report_path,
        setup_attestation_template_path=setup_attestation_template_path,
        setup_attestation_smoke_path=setup_attestation_smoke_path,
        setup_attestation_path=setup_attestation_path,
        setup_attestation_patch_path=setup_attestation_patch_path,
        attested_setup_state_path=attested_setup_state_path,
        attested_dispatch_gate_path=attested_dispatch_gate_path,
        attested_dispatch_run_path=attested_dispatch_run_path,
        dispatch_diagnostics_path=dispatch_diagnostics_path,
        recovery_control_chain_path=recovery_control_chain_path,
        recovery_checkpoint_path=recovery_checkpoint_path,
        errors=errors,
    )
    if payloads:
        errors.extend(
            _chain_consistency_errors(
                payloads,
                readiness_report_path=readiness_report_path,
                run_plan_path=run_plan_path,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                dispatch_gate_path=dispatch_gate_path,
                dispatch_run_path=dispatch_run_path,
                setup_handle_plan_path=setup_handle_plan_path,
                setup_gap_report_path=setup_gap_report_path,
                attested_setup_state_path=attested_setup_state_path,
                attested_dispatch_gate_path=attested_dispatch_gate_path,
                recovery_control_chain_path=recovery_control_chain_path,
                repo_root=repo_root,
            )
        )
    dispatch_ready = bool(payloads.get("dispatch_gate", {}).get("dispatch_ready"))
    recovery_control_chain = payloads.get("recovery_control_chain")
    recovery_checkpoint = payloads.get("recovery_checkpoint")
    recovery_release_gate_ready = (
        None
        if recovery_control_chain is None
        else recovery_control_chain.get("release_gate_ready") is True
    )
    control_chain_ready = (
        bool(payloads.get("readiness", {}).get("scoped_completion_audit_ready"))
        and bool(payloads.get("setup_state", {}).get("dispatch_ready"))
        and dispatch_ready
        and bool(payloads.get("dispatch_run", {}).get("ok"))
        and bool(payloads.get("dispatch_run", {}).get("dispatch_ready"))
        and (
            recovery_control_chain is None
            or recovery_control_chain.get("release_gate_ready") is True
        )
    )
    return ControlChainValidationResult(
        validation_schema_version=CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
        readiness_report_path=str(readiness_report_path),
        run_plan_path=str(run_plan_path),
        launch_pack_path=str(launch_pack_path),
        setup_state_path=str(setup_state_path),
        setup_handle_plan_path=str(setup_handle_plan_path),
        setup_gap_report_path=(
            str(setup_gap_report_path) if setup_gap_report_path is not None else None
        ),
        setup_gap_markdown_report_path=(
            str(setup_gap_markdown_report_path)
            if setup_gap_markdown_report_path is not None
            else None
        ),
        setup_attestation_template_path=(
            str(setup_attestation_template_path)
            if setup_attestation_template_path is not None
            else None
        ),
        setup_attestation_smoke_path=(
            str(setup_attestation_smoke_path)
            if setup_attestation_smoke_path is not None
            else None
        ),
        setup_attestation_smoke_out_dir=(
            str(setup_attestation_smoke_out_dir)
            if setup_attestation_smoke_out_dir is not None
            else None
        ),
        setup_attestation_path=(
            str(setup_attestation_path) if setup_attestation_path is not None else None
        ),
        setup_attestation_patch_path=(
            str(setup_attestation_patch_path)
            if setup_attestation_patch_path is not None
            else None
        ),
        attested_setup_state_path=(
            str(attested_setup_state_path)
            if attested_setup_state_path is not None
            else None
        ),
        attested_dispatch_gate_path=(
            str(attested_dispatch_gate_path)
            if attested_dispatch_gate_path is not None
            else None
        ),
        attested_dispatch_run_path=(
            str(attested_dispatch_run_path)
            if attested_dispatch_run_path is not None
            else None
        ),
        dispatch_gate_path=str(dispatch_gate_path),
        dispatch_run_path=str(dispatch_run_path),
        dispatch_diagnostics_path=(
            str(dispatch_diagnostics_path) if dispatch_diagnostics_path else None
        ),
        recovery_control_chain_path=(
            str(recovery_control_chain_path) if recovery_control_chain_path else None
        ),
        recovery_checkpoint_path=(
            str(recovery_checkpoint_path) if recovery_checkpoint_path else None
        ),
        readiness_preflight_dirs=[str(path) for path in source_dirs],
        control_chain_ready=control_chain_ready,
        dispatch_ready=dispatch_ready,
        recovery_chain_ready=(
            None
            if recovery_control_chain is None
            else recovery_control_chain.get("recovery_chain_ready") is True
        ),
        recovery_release_gate_ready=recovery_release_gate_ready,
        recovery_operator_setup_required=(
            None
            if recovery_control_chain is None
            else recovery_control_chain.get("operator_setup_required") is True
        ),
        recovery_resume_state=(
            None
            if recovery_checkpoint is None
            else _string_or_none(recovery_checkpoint.get("resume_state"))
        ),
        recovery_required_resume_inputs=(
            None
            if recovery_checkpoint is None
            else _string_list(recovery_checkpoint.get("required_resume_inputs"))
        ),
        errors=errors,
    )


def _combined_preflight_dirs(
    preflight_dir: Path | None,
    preflight_dirs: list[Path] | None,
) -> list[Path]:
    combined: list[Path] = []
    if preflight_dir is not None:
        combined.append(preflight_dir)
    combined.extend(preflight_dirs or [])
    return combined


def _validator_errors(label: str, result: Any) -> list[str]:
    if result.ok:
        return []
    return [f"completion audit control chain {label} failed validation: {error}" for error in result.errors]


def _load_chain_payloads(
    *,
    readiness_report_path: Path,
    run_plan_path: Path,
    launch_pack_path: Path,
    setup_state_path: Path,
    setup_handle_plan_path: Path,
    dispatch_gate_path: Path,
    dispatch_run_path: Path,
    setup_gap_report_path: Path | None,
    setup_attestation_template_path: Path | None,
    setup_attestation_smoke_path: Path | None,
    setup_attestation_path: Path | None,
    setup_attestation_patch_path: Path | None,
    attested_setup_state_path: Path | None,
    attested_dispatch_gate_path: Path | None,
    attested_dispatch_run_path: Path | None,
    dispatch_diagnostics_path: Path | None,
    recovery_control_chain_path: Path | None,
    recovery_checkpoint_path: Path | None,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    paths = {
        "readiness": readiness_report_path,
        "run_plan": run_plan_path,
        "launch_pack": launch_pack_path,
        "setup_state": setup_state_path,
        "setup_handle_plan": setup_handle_plan_path,
        "dispatch_gate": dispatch_gate_path,
        "dispatch_run": dispatch_run_path,
    }
    if setup_gap_report_path is not None:
        paths["setup_gap_report"] = setup_gap_report_path
    if setup_attestation_template_path is not None:
        paths["setup_attestation_template"] = setup_attestation_template_path
    if setup_attestation_smoke_path is not None:
        paths["setup_attestation_smoke"] = setup_attestation_smoke_path
    if setup_attestation_path is not None:
        paths["setup_attestation"] = setup_attestation_path
    if setup_attestation_patch_path is not None:
        paths["setup_attestation_patch"] = setup_attestation_patch_path
    if attested_setup_state_path is not None:
        paths["attested_setup_state"] = attested_setup_state_path
    if attested_dispatch_gate_path is not None:
        paths["attested_dispatch_gate"] = attested_dispatch_gate_path
    if attested_dispatch_run_path is not None:
        paths["attested_dispatch_run"] = attested_dispatch_run_path
    if dispatch_diagnostics_path is not None:
        paths["dispatch_diagnostics"] = dispatch_diagnostics_path
    if recovery_control_chain_path is not None:
        paths["recovery_control_chain"] = recovery_control_chain_path
    if recovery_checkpoint_path is not None:
        paths["recovery_checkpoint"] = recovery_checkpoint_path
    payloads: dict[str, dict[str, Any]] = {}
    for key, path in paths.items():
        try:
            payload = load_strict_json_file(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"completion audit control chain {key} JSON is invalid: {exc}")
            return {}
        if not isinstance(payload, dict):
            errors.append(f"completion audit control chain {key} root must be an object")
            return {}
        payloads[key] = payload
    return payloads


def _chain_consistency_errors(
    payloads: dict[str, dict[str, Any]],
    *,
    readiness_report_path: Path,
    run_plan_path: Path,
    launch_pack_path: Path,
    setup_state_path: Path,
    dispatch_gate_path: Path,
    dispatch_run_path: Path,
    setup_handle_plan_path: Path,
    setup_gap_report_path: Path | None,
    attested_setup_state_path: Path | None,
    attested_dispatch_gate_path: Path | None,
    recovery_control_chain_path: Path | None,
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    readiness = payloads["readiness"]
    run_plan = payloads["run_plan"]
    launch_pack = payloads["launch_pack"]
    setup_state = payloads["setup_state"]
    setup_handle_plan = payloads["setup_handle_plan"]
    setup_gap_report = payloads.get("setup_gap_report")
    recovery_control_chain = payloads.get("recovery_control_chain")
    recovery_checkpoint = payloads.get("recovery_checkpoint")
    setup_attestation_template = payloads.get("setup_attestation_template")
    setup_attestation = payloads.get("setup_attestation")
    attested_setup_state = payloads.get("attested_setup_state")
    attested_dispatch_gate = payloads.get("attested_dispatch_gate")
    attested_dispatch_run = payloads.get("attested_dispatch_run")
    dispatch_gate = payloads["dispatch_gate"]
    dispatch_run = payloads["dispatch_run"]
    dispatch_diagnostics = payloads.get("dispatch_diagnostics")
    if recovery_control_chain is not None:
        errors.extend(
            _recovery_control_chain_report_errors(
                recovery_control_chain,
                repo_root=repo_root,
            )
        )
    if recovery_checkpoint is not None:
        errors.extend(
            _recovery_checkpoint_report_errors(
                recovery_checkpoint,
                recovery_control_chain=recovery_control_chain,
                recovery_control_chain_path=recovery_control_chain_path,
                repo_root=repo_root,
            )
        )

    expected_hashes = {
        "run plan readiness_report_sha256": (
            run_plan.get("readiness_report_sha256"),
            _sha256_file(readiness_report_path),
        ),
        "launch pack run_plan_sha256": (
            launch_pack.get("run_plan_sha256"),
            _sha256_file(run_plan_path),
        ),
        "setup state launch_pack_sha256": (
            setup_state.get("launch_pack_sha256"),
            _sha256_file(launch_pack_path),
        ),
        "setup handle plan setup_state_sha256": (
            setup_handle_plan.get("setup_state_sha256"),
            _sha256_file(setup_state_path),
        ),
        "dispatch gate setup_state_sha256": (
            dispatch_gate.get("setup_state_sha256"),
            _sha256_file(setup_state_path),
        ),
        "dispatch run dispatch_gate_sha256": (
            dispatch_run.get("dispatch_gate_sha256"),
            _sha256_file(dispatch_gate_path),
        ),
    }
    if setup_gap_report is not None:
        expected_hashes["setup gap report setup_handle_plan_sha256"] = (
            setup_gap_report.get("setup_handle_plan_sha256"),
            _sha256_file(setup_handle_plan_path),
        )
    if setup_attestation_template is not None:
        expected_hashes["setup attestation template setup_handle_plan_sha256"] = (
            setup_attestation_template.get("setup_handle_plan_sha256"),
            _sha256_file(setup_handle_plan_path),
        )
    if setup_attestation is not None:
        expected_hashes["setup attestation setup_state_sha256"] = (
            setup_attestation.get("setup_state_sha256"),
            _sha256_file(setup_state_path),
        )
    if attested_setup_state is not None:
        expected_hashes["attested setup state launch_pack_sha256"] = (
            attested_setup_state.get("launch_pack_sha256"),
            _sha256_file(launch_pack_path),
        )
    if attested_dispatch_gate is not None:
        if attested_setup_state is None:
            errors.append(
                "completion audit control chain attested gate requires attested setup state"
            )
        else:
            expected_hashes["attested dispatch gate setup_state_sha256"] = (
                attested_dispatch_gate.get("setup_state_sha256"),
                _sha256_file(attested_setup_state_path),
            )
    if attested_dispatch_run is not None:
        if attested_dispatch_gate is None or attested_setup_state is None:
            errors.append(
                "completion audit control chain attested run requires attested gate and setup state"
            )
        else:
            expected_hashes["attested dispatch run dispatch_gate_sha256"] = (
                attested_dispatch_run.get("dispatch_gate_sha256"),
                _sha256_file(attested_dispatch_gate_path),
            )
    if dispatch_diagnostics is not None:
        expected_hashes["dispatch diagnostics dispatch_run_sha256"] = (
            dispatch_diagnostics.get("dispatch_run_sha256"),
            _sha256_file(dispatch_run_path),
        )
    for label, (actual, expected) in expected_hashes.items():
        if actual != expected:
            errors.append(f"completion audit control chain {label} must match source")

    if setup_state.get("dispatch_ready") != dispatch_gate.get("dispatch_ready"):
        errors.append("completion audit control chain setup and gate dispatch_ready must match")
    if dispatch_gate.get("dispatch_ready") != dispatch_run.get("dispatch_ready"):
        errors.append("completion audit control chain gate and dispatch-run dispatch_ready must match")
    if setup_state.get("ready_requirement_count") != dispatch_gate.get(
        "ready_dispatch_item_count"
    ):
        errors.append("completion audit control chain ready counts must match")
    if setup_state.get("blocked_requirement_count") != dispatch_gate.get(
        "blocked_dispatch_item_count"
    ):
        errors.append("completion audit control chain blocked counts must match")
    if setup_handle_plan.get("pending_setup_check_count", 0) > 0 and dispatch_gate.get(
        "dispatch_ready"
    ):
        errors.append("completion audit control chain pending setup checks cannot unlock dispatch")
    if dispatch_gate.get("dispatch_ready") is not True:
        if dispatch_run.get("command_count") != 0:
            errors.append(
                "completion audit control chain pending dispatch must not materialize live commands"
            )
        if dispatch_run.get("executed_command_count") != 0:
            errors.append("completion audit control chain pending dispatch must not execute commands")
        if dispatch_run.get("ok") is not False:
            errors.append("completion audit control chain pending dispatch-run ok must be false")
        if "completion_audit_dispatch_run_gate_not_ready" not in dispatch_run.get(
            "error_codes",
            [],
        ):
            errors.append("completion audit control chain pending dispatch-run must report gate_not_ready")
        if dispatch_diagnostics is not None:
            if dispatch_diagnostics.get("ok") is not True:
                errors.append(
                    "completion audit control chain pending dispatch diagnostics must be ok"
                )
            if dispatch_diagnostics.get("dispatch_ready") is not False:
                errors.append(
                    "completion audit control chain pending diagnostics must remain not dispatch_ready"
                )
            if dispatch_diagnostics.get("diagnostic_command_count") != dispatch_run.get(
                "diagnostic_command_count"
            ):
                errors.append(
                    "completion audit control chain diagnostic command counts must match"
                )
            if dispatch_diagnostics.get("dispatch_run_fingerprint_sha256") != dispatch_run.get(
                "dispatch_run_fingerprint_sha256"
            ):
                errors.append(
                    "completion audit control chain diagnostics dispatch-run fingerprint must match"
                )
    if readiness.get("scoped_completion_audit_ready") and not dispatch_gate.get(
        "dispatch_ready"
    ):
        errors.append("completion audit control chain scoped readiness cannot be true while dispatch is locked")
    if attested_setup_state is not None:
        if attested_setup_state.get("dispatch_ready") is not True:
            errors.append("completion audit control chain attested setup state must be dispatch-ready")
    if attested_dispatch_gate is not None:
        if attested_dispatch_gate.get("dispatch_ready") is not True:
            errors.append("completion audit control chain attested dispatch gate must be ready")
    if attested_dispatch_run is not None:
        if attested_dispatch_run.get("dispatch_ready") is not True:
            errors.append("completion audit control chain attested dispatch run must be ready")
        if attested_dispatch_run.get("ok") is not True:
            errors.append("completion audit control chain attested dispatch run must be ok")
    return errors


RECOVERY_CONTROL_CHAIN_REQUIRED_PATH_FIELDS = (
    "recovery_plan_path",
    "recovery_queue_path",
    "recovery_work_order_path",
    "recovery_work_order_status_path",
    "recovery_queue_progress_path",
    "recovery_dispatch_authorization_path",
    "recovery_dispatch_run_path",
)
RECOVERY_CONTROL_CHAIN_REPLAY_FIELDS = (
    "validation_schema_version",
    "ok",
    "error_codes",
    "error_code_counts",
    "chain_state",
    "recovery_chain_ready",
    "release_gate_ready",
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
    "chain_fingerprint_sha256",
)


def _recovery_control_chain_report_errors(
    payload: dict[str, Any],
    *,
    repo_root: Path,
) -> list[str]:
    import validate_completion_audit_recovery_control_chain as recovery_control_chain_validator

    errors: list[str] = []
    if payload.get("validation_schema_version") != (
        recovery_control_chain_validator.RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION
    ):
        errors.append(
            "completion audit control chain recovery control schema_version is unsupported"
        )
    for field in RECOVERY_CONTROL_CHAIN_REQUIRED_PATH_FIELDS:
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(
                f"completion audit control chain recovery control {field} must be a non-empty path"
            )
    if errors:
        return errors
    try:
        replay = recovery_control_chain_validator.validate_recovery_control_chain(
            recovery_plan_path=Path(payload["recovery_plan_path"]),
            recovery_queue_path=Path(payload["recovery_queue_path"]),
            recovery_work_order_path=Path(payload["recovery_work_order_path"]),
            recovery_work_order_status_path=Path(
                payload["recovery_work_order_status_path"]
            ),
            recovery_queue_progress_path=Path(payload["recovery_queue_progress_path"]),
            recovery_dispatch_authorization_path=Path(
                payload["recovery_dispatch_authorization_path"]
            ),
            recovery_dispatch_run_path=Path(payload["recovery_dispatch_run_path"]),
            handoff_json_path=_optional_path(payload.get("handoff_json_path")),
            setup_state_path=_optional_path(payload.get("setup_state_path")),
            dispatch_gate_path=_optional_path(payload.get("dispatch_gate_path")),
            launch_pack_path=_optional_path(payload.get("launch_pack_path")),
            repo_root=repo_root,
        )
    except Exception as exc:  # noqa: BLE001
        return [
            "completion audit control chain recovery control replay failed: "
            + str(exc)
        ]
    if not replay.ok:
        errors.extend(_validator_errors("recovery control chain", replay))
    replay_payload = replay.to_dict()
    for field in RECOVERY_CONTROL_CHAIN_REPLAY_FIELDS:
        if payload.get(field) != replay_payload.get(field):
            errors.append(
                "completion audit control chain recovery control report "
                f"{field} must match replayed sources"
            )
    return errors


RECOVERY_CHECKPOINT_CONTROL_FIELDS = (
    "chain_fingerprint_sha256",
    "chain_state",
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
)


def _recovery_checkpoint_report_errors(
    payload: dict[str, Any],
    *,
    recovery_control_chain: dict[str, Any] | None,
    recovery_control_chain_path: Path | None,
    repo_root: Path,
) -> list[str]:
    import validate_completion_audit_recovery_checkpoint as recovery_checkpoint_validator

    errors: list[str] = []
    if recovery_control_chain is None or recovery_control_chain_path is None:
        return [
            "completion audit control chain recovery checkpoint requires recovery control chain"
        ]
    if payload.get("schema_version") != (
        recovery_checkpoint_validator.checkpoint_generator.RECOVERY_CHECKPOINT_SCHEMA_VERSION
    ):
        errors.append(
            "completion audit control chain recovery checkpoint schema_version is unsupported"
        )
    if payload.get("recovery_control_chain_sha256") != _sha256_file(
        recovery_control_chain_path
    ):
        errors.append(
            "completion audit control chain recovery checkpoint control chain SHA-256 must match source"
        )
    for field in RECOVERY_CHECKPOINT_CONTROL_FIELDS:
        if payload.get(field) != recovery_control_chain.get(field):
            errors.append(
                "completion audit control chain recovery checkpoint "
                f"{field} must match recovery control chain"
            )
    if not isinstance(payload.get("resume_state"), str) or not payload.get(
        "resume_state"
    ):
        errors.append(
            "completion audit control chain recovery checkpoint resume_state must be non-empty"
        )
    if not isinstance(payload.get("required_resume_inputs"), list):
        errors.append(
            "completion audit control chain recovery checkpoint required_resume_inputs must be a list"
        )
    return errors


def _optional_path(value: Any) -> Path | None:
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the source-bound completion-audit control chain.",
    )
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--readiness-markdown-report", type=Path, default=None)
    parser.add_argument(
        "--readiness-preflight-dir",
        action="append",
        type=Path,
        default=[],
    )
    parser.add_argument("--self-harness-report-bundle", type=Path, default=None)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--run-plan-markdown", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, required=True)
    parser.add_argument("--launch-pack-markdown", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--setup-handle-plan", type=Path, required=True)
    parser.add_argument("--setup-gap-report", type=Path, default=None)
    parser.add_argument("--setup-gap-markdown-report", type=Path, default=None)
    parser.add_argument("--setup-attestation-template", type=Path, default=None)
    parser.add_argument("--setup-attestation-smoke", type=Path, default=None)
    parser.add_argument("--setup-attestation-smoke-out-dir", type=Path, default=None)
    parser.add_argument("--setup-attestation", type=Path, default=None)
    parser.add_argument("--setup-attestation-patch", type=Path, default=None)
    parser.add_argument("--attested-setup-state", type=Path, default=None)
    parser.add_argument("--attested-dispatch-gate", type=Path, default=None)
    parser.add_argument("--attested-dispatch-run", type=Path, default=None)
    parser.add_argument("--dispatch-gate", type=Path, required=True)
    parser.add_argument("--dispatch-run", type=Path, required=True)
    parser.add_argument("--dispatch-diagnostics", type=Path, default=None)
    parser.add_argument("--recovery-control-chain", type=Path, default=None)
    parser.add_argument("--recovery-checkpoint", type=Path, default=None)
    parser.add_argument(
        "--diagnostics-preflight-source-dir",
        action="append",
        type=Path,
        default=[],
    )
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        print(text, end="")
        return 1
    result = validate_control_chain(
        readiness_report_path=args.readiness_report,
        readiness_markdown_report_path=args.readiness_markdown_report,
        readiness_preflight_dirs=args.readiness_preflight_dir,
        self_harness_report_bundle_path=args.self_harness_report_bundle,
        run_plan_path=args.run_plan,
        run_plan_markdown_path=args.run_plan_markdown,
        launch_pack_path=args.launch_pack,
        launch_pack_markdown_path=args.launch_pack_markdown,
        setup_state_path=args.setup_state,
        setup_handle_plan_path=args.setup_handle_plan,
        setup_gap_report_path=args.setup_gap_report,
        setup_gap_markdown_report_path=args.setup_gap_markdown_report,
        setup_attestation_template_path=args.setup_attestation_template,
        setup_attestation_smoke_path=args.setup_attestation_smoke,
        setup_attestation_smoke_out_dir=args.setup_attestation_smoke_out_dir,
        setup_attestation_path=args.setup_attestation,
        setup_attestation_patch_path=args.setup_attestation_patch,
        attested_setup_state_path=args.attested_setup_state,
        attested_dispatch_gate_path=args.attested_dispatch_gate,
        attested_dispatch_run_path=args.attested_dispatch_run,
        dispatch_gate_path=args.dispatch_gate,
        dispatch_run_path=args.dispatch_run,
        dispatch_diagnostics_path=args.dispatch_diagnostics,
        recovery_control_chain_path=args.recovery_control_chain,
        recovery_checkpoint_path=args.recovery_checkpoint,
        diagnostics_preflight_source_dirs=args.diagnostics_preflight_source_dir,
        repo_root=args.repo_root,
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
        print("Wiii Completion Audit Control Chain Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Control Chain Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "validation_schema_version": CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
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
    if "failed validation" in error:
        return "completion_audit_control_chain_child_invalid"
    if "JSON is invalid" in error:
        return "completion_audit_control_chain_json_invalid"
    if "root must be an object" in error:
        return "completion_audit_control_chain_root_invalid"
    if "must match" in error or "counts must match" in error:
        return "completion_audit_control_chain_source_mismatch"
    if "pending dispatch" in error or "unlock dispatch" in error:
        return "completion_audit_control_chain_fail_closed_invalid"
    if "scoped readiness" in error:
        return "completion_audit_control_chain_readiness_invalid"
    if error == CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_control_chain_output_path_directory"
    if error == CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_control_chain_output_path_symlink"
    if error == CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_control_chain_output_path_parent_symlink"
    return "completion_audit_control_chain_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
