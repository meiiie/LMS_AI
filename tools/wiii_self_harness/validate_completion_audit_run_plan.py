#!/usr/bin/env python3
"""Validate completion-audit operator run plan artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_run_plan import (  # noqa: E402
    RUN_PLAN_SCHEMA_VERSION,
    format_markdown,
    generate_completion_audit_run_plan,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_readiness as readiness_validator  # noqa: E402
from validate_runtime_evidence_preflight import SETUP_CONTRACT_VERSION  # noqa: E402


RUN_PLAN_VALIDATION_SCHEMA_VERSION = "wiii.completion_audit_run_plan_validation.v1"
READINESS_SOURCE_VALIDATION_COMMAND_TOKEN = (
    "run plan against readiness Markdown, preflight sources, and self-harness bundle"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "readiness_report_path",
    "readiness_report_sha256",
    "readiness_schema_version",
    "readiness_scoped_completion_audit_ready",
    "readiness_scoped_next_actions_fingerprint_sha256",
    "readiness_preflight_summary_count",
    "excluded_requirement_ids",
    "scoped_counts",
    "execution_state",
    "run_item_count",
    "blocked_by_live_setup_count",
    "acceptance_contract_fingerprint_sha256",
    "operator_setup_fingerprint_sha256",
    "run_items_fingerprint_sha256",
    "run_items",
    "post_run_verification_commands",
    "post_run_verification_command_specs_fingerprint_sha256",
    "post_run_verification_command_specs",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
COUNT_FIELDS = {"requirements", "passed", "missing", "failed"}
RUN_ITEM_FIELDS = {
    "requirement_id",
    "title",
    "layer",
    "current_status",
    "artifact",
    "evidence_schema_version",
    "probe",
    "error_codes",
    "workflow_execution",
    "preflight",
    "blocked_by_live_setup",
    "required_operator_actions",
    "credential_or_external_setup_tokens",
    "acceptance",
}
WORKFLOW_FIELDS = {
    "workflow",
    "workflow_dispatch_inputs",
    "schedule_env_flags",
    "live_probe_env_flags",
    "live_probe_guard_tokens",
    "artifact_tokens",
    "diagnostic_artifact_tokens",
}
PREFLIGHT_FIELDS = {
    "status",
    "schema_version",
    "generated_at",
    "required_next",
    "source_file",
    "source_file_sha256",
    "source_validation_schema_version",
    "source_validation_ok",
    "source_validation_error_codes",
    "raw_payload_included",
    "setup_contract",
}
SETUP_CONTRACT_FIELDS = {
    "version",
    "requirement_id",
    "required_next",
    "workflow_inputs_required",
    "environment_flags_required",
    "credential_slots_required",
    "external_setup_required",
    "dispatch_ready",
}
OPERATOR_ACTION_FIELDS = {"token", "category", "instruction"}
ACCEPTANCE_FIELDS = {"expected_artifact", "expected_schema_version", "accepted_when"}
VERIFICATION_COMMAND_SPEC_FIELDS = {
    "step_id",
    "working_directory",
    "argv",
    "uses_shell",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_payload_included",
    "raw_identifiers_included",
}
EXECUTION_STATES = {
    "scoped_ready",
    "no_scoped_blockers",
    "blocked_on_live_setup",
    "ready_for_live_dispatch",
}
CANONICAL_VERIFICATION_ORDER_TOKEN = "canonical verification order"
ONLY_CANONICAL_VERIFICATION_COMMANDS_TOKEN = "only canonical verification commands"


@dataclass(frozen=True)
class RunPlanValidationResult:
    validation_schema_version: str
    run_plan_path: str
    readiness_report_path: str | None
    readiness_markdown_report_path: str | None
    readiness_preflight_dir: str | None
    readiness_preflight_dirs: list[str]
    self_harness_report_bundle_path: str | None
    markdown_report_path: str | None
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


def validate_run_plan(
    run_plan_path: Path,
    *,
    readiness_report_path: Path | None = None,
    readiness_markdown_report_path: Path | None = None,
    readiness_preflight_dir: Path | None = None,
    readiness_preflight_dirs: list[Path] | None = None,
    self_harness_report_bundle_path: Path | None = None,
    markdown_report_path: Path | None = None,
) -> RunPlanValidationResult:
    errors: list[str] = []
    source_dirs = _combined_preflight_dirs(
        readiness_preflight_dir,
        readiness_preflight_dirs,
    )
    payload = _load_payload(run_plan_path, errors)
    readiness_payload: dict[str, Any] | None = None
    if readiness_report_path is not None:
        readiness_payload = _load_readiness_payload(
            readiness_report_path,
            errors,
            readiness_markdown_report_path=readiness_markdown_report_path,
            readiness_preflight_dirs=source_dirs,
            self_harness_report_bundle_path=self_harness_report_bundle_path,
        )
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if readiness_report_path is not None and readiness_payload is not None:
            errors.extend(
                _readiness_source_errors(
                    payload,
                    readiness_report_path=readiness_report_path,
                    readiness_payload=readiness_payload,
                )
            )
        if markdown_report_path is not None:
            errors.extend(
                _markdown_report_errors(
                    markdown_report_path,
                    readiness_report_path=readiness_report_path,
                )
            )
    return RunPlanValidationResult(
        validation_schema_version=RUN_PLAN_VALIDATION_SCHEMA_VERSION,
        run_plan_path=str(run_plan_path),
        readiness_report_path=str(readiness_report_path)
        if readiness_report_path is not None
        else None,
        readiness_markdown_report_path=(
            str(readiness_markdown_report_path)
            if readiness_markdown_report_path is not None
            else None
        ),
        readiness_preflight_dir=(
            str(readiness_preflight_dir) if readiness_preflight_dir is not None else None
        ),
        readiness_preflight_dirs=[str(path) for path in source_dirs],
        self_harness_report_bundle_path=(
            str(self_harness_report_bundle_path)
            if self_harness_report_bundle_path is not None
            else None
        ),
        markdown_report_path=(
            str(markdown_report_path) if markdown_report_path is not None else None
        ),
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit run plan path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit run plan JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit run plan root must be an object")
        return None
    return payload


def _load_readiness_payload(
    path: Path,
    errors: list[str],
    *,
    readiness_markdown_report_path: Path | None,
    readiness_preflight_dirs: list[Path],
    self_harness_report_bundle_path: Path | None,
) -> dict[str, Any] | None:
    readiness_validation = readiness_validator.validate_readiness_report(
        path,
        markdown_report_path=readiness_markdown_report_path,
        preflight_dirs=readiness_preflight_dirs,
        self_harness_report_bundle_path=self_harness_report_bundle_path,
    )
    if not readiness_validation.ok:
        errors.append(
            "completion audit run plan readiness source failed validation: "
            + "; ".join(readiness_validation.errors)
        )
        return None
    payload = load_strict_json_file(path)
    return payload if isinstance(payload, dict) else None


def _combined_preflight_dirs(
    preflight_dir: Path | None,
    preflight_dirs: list[Path] | None,
) -> list[Path]:
    combined: list[Path] = []
    if preflight_dir is not None:
        combined.append(preflight_dir)
    combined.extend(preflight_dirs or [])
    return combined


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append("run plan missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("run plan has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != RUN_PLAN_SCHEMA_VERSION:
        errors.append(f"run plan schema_version must be {RUN_PLAN_SCHEMA_VERSION!r}")
    if payload.get("ok") is not True:
        errors.append("run plan ok must be true for generated run plans")
    for field in (
        "readiness_report_path",
        "readiness_schema_version",
        "readiness_scoped_next_actions_fingerprint_sha256",
        "execution_state",
        "run_items_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"run plan {field} must be a non-empty string")
    if payload.get("execution_state") not in EXECUTION_STATES:
        errors.append("run plan execution_state must be a known value")
    for field in (
        "readiness_report_sha256",
        "run_items_fingerprint_sha256",
        "acceptance_contract_fingerprint_sha256",
        "operator_setup_fingerprint_sha256",
        "readiness_scoped_next_actions_fingerprint_sha256",
        "post_run_verification_command_specs_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"run plan {field} must be a SHA-256 hex string")
    if not isinstance(payload.get("readiness_scoped_completion_audit_ready"), bool):
        errors.append("run plan readiness_scoped_completion_audit_ready must be a boolean")
    for field in (
        "readiness_preflight_summary_count",
        "run_item_count",
        "blocked_by_live_setup_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"run plan {field} must be a non-negative integer")
    for field in (
        "excluded_requirement_ids",
        "post_run_verification_commands",
        "errors",
        "error_codes",
    ):
        if not _is_string_list(payload.get(field)):
            errors.append(f"run plan {field} must be a string list")
    errors.extend(
        _post_run_verification_command_errors(
            payload.get("post_run_verification_commands")
        )
    )
    errors.extend(
        _post_run_verification_command_spec_errors(
            payload.get("post_run_verification_command_specs"),
            payload.get("post_run_verification_commands"),
        )
    )
    errors.extend(_post_run_verification_fingerprint_errors(payload))
    errors.extend(_scoped_count_errors(payload.get("scoped_counts")))
    run_item_errors, run_items = _run_item_errors(payload.get("run_items"))
    errors.extend(run_item_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not run_item_errors:
        errors.extend(_run_item_summary_errors(payload, run_items))
        errors.extend(_acceptance_contract_fingerprint_errors(payload, run_items))
        errors.extend(_operator_setup_fingerprint_errors(payload, run_items))
    return errors


def _post_run_verification_command_errors(value: Any) -> list[str]:
    if not _is_string_list(value):
        return []
    errors: list[str] = []
    errors.extend(_post_run_shell_control_errors(value))
    errors.extend(_post_run_command_order_errors(value))
    errors.extend(_post_run_launch_pack_command_errors(value))
    preflight_commands = [
        command
        for command in value
        if "--preflight-dir <preflight-dir>" in command
    ]
    if len(preflight_commands) < 5:
        errors.append(
            "run plan post_run_verification_commands must validate downloaded "
            "preflight artifacts with <preflight-dir> placeholder"
        )
    for command in value:
        for match in re.finditer(r"--preflight-dir\s+(\S+)", command):
            if match.group(1) != "<preflight-dir>":
                errors.append(
                    "run plan post_run_verification_commands must not bind "
                    "preflight-dir to a concrete local path"
                )
                return errors
    return errors


def _post_run_verification_command_spec_errors(
    value: Any,
    commands: Any,
) -> list[str]:
    if not isinstance(value, list):
        return ["run plan post_run_verification_command_specs must be a list"]
    errors: list[str] = []
    expected_steps = [
        "validate_runtime_evidence_bundle",
        "report_completion_audit_readiness",
        "report_completion_audit_readiness_markdown",
        "validate_completion_audit_readiness",
        "generate_completion_audit_run_plan",
        "generate_completion_audit_run_plan_markdown",
        "validate_completion_audit_run_plan",
        "generate_completion_audit_launch_pack",
        "generate_completion_audit_launch_pack_markdown",
        "validate_completion_audit_launch_pack",
        "generate_completion_audit_setup_state",
        "validate_completion_audit_setup_state",
        "generate_completion_audit_setup_handle_plan",
        "validate_completion_audit_setup_handle_plan",
        "probe_completion_audit_setup_handle_evidence",
        "generate_completion_audit_setup_attestation_from_handles",
        "apply_completion_audit_setup_attestation",
        "generate_completion_audit_dispatch_gate_attested",
        "validate_completion_audit_dispatch_gate_attested",
        "run_completion_audit_dispatch_gate_attested",
        "validate_completion_audit_dispatch_run_attested",
        "generate_completion_audit_dispatch_gate",
        "validate_completion_audit_dispatch_gate",
        "run_completion_audit_dispatch_gate",
        "validate_completion_audit_dispatch_run",
        "run_completion_audit_dispatch_diagnostics",
        "validate_completion_audit_dispatch_diagnostics",
        "validate_completion_audit_control_chain",
    ]
    if len(value) != len(expected_steps):
        errors.append(
            "run plan post_run_verification_command_specs must contain only "
            "canonical verification steps"
        )
    rendered_commands: list[str] = []
    for index, spec in enumerate(value):
        if not isinstance(spec, dict):
            errors.append("run plan post_run_verification_command_specs entries must be objects")
            continue
        if set(spec) != VERIFICATION_COMMAND_SPEC_FIELDS:
            errors.append(
                "run plan post_run_verification_command_specs fields must match contract"
            )
        step_id = spec.get("step_id")
        expected_step = expected_steps[index] if index < len(expected_steps) else ""
        if step_id != expected_step:
            errors.append(
                "run plan post_run_verification_command_specs must keep canonical "
                f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
            )
        if spec.get("working_directory") != ".":
            errors.append(
                "run plan post_run_verification_command_specs working_directory "
                "must be repo root"
            )
        if spec.get("uses_shell") is not False:
            errors.append(
                "run plan post_run_verification_command_specs uses_shell must be false"
            )
        argv = spec.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(
                "run plan post_run_verification_command_specs argv must be a "
                "non-empty string list"
            )
            continue
        rendered_commands.append(" ".join(argv))
        errors.extend(_post_run_argv_shell_control_errors(argv))
        if _argv_preflight_dir_value(argv) not in {"", "<preflight-dir>"}:
            errors.append(
                "run plan post_run_verification_command_specs must not bind "
                "preflight-dir to a concrete local path"
            )
    if _is_string_list(commands) and rendered_commands and commands != rendered_commands:
        errors.append(
            "run plan post_run_verification_commands must match "
            "post_run_verification_command_specs argv"
        )
    return errors


def _post_run_verification_fingerprint_errors(payload: dict[str, Any]) -> list[str]:
    specs = payload.get("post_run_verification_command_specs")
    fingerprint = payload.get("post_run_verification_command_specs_fingerprint_sha256")
    if not isinstance(specs, list) or not isinstance(fingerprint, str):
        return []
    if fingerprint != _verification_command_specs_fingerprint(specs):
        return [
            "run plan post_run_verification_command_specs_fingerprint_sha256 "
            "must match post_run_verification_command_specs"
        ]
    return []


def _post_run_argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "run plan post_run_verification_command_specs argv must not contain "
                "shell control operator tokens"
            ]
    return []


def _argv_preflight_dir_value(argv: list[str]) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == "--preflight-dir":
            return argv[index + 1]
    return ""


def _post_run_shell_control_errors(commands: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for command in commands:
        if any(token in command for token in shell_control_tokens):
            return [
                "run plan post_run_verification_commands must not contain "
                "shell control operator tokens"
            ]
    return []


def _post_run_command_order_errors(commands: list[str]) -> list[str]:
    expected_token_groups = [
        [
            "validate_runtime_evidence_bundle.py",
            "--format json",
            "--out <runtime-evidence-bundle-report-json>",
        ],
        ["report_completion_audit_readiness.py", "--format json"],
        ["report_completion_audit_readiness.py", "--format markdown"],
        [
            "validate_completion_audit_readiness.py",
            "--markdown-report",
            "--self-harness-report-bundle",
        ],
        ["generate_completion_audit_run_plan.py", "--format json"],
        ["generate_completion_audit_run_plan.py", "--format markdown"],
        [
            "validate_completion_audit_run_plan.py",
            "--readiness-markdown-report",
            "--readiness-preflight-dir",
            "--self-harness-report-bundle",
        ],
        ["generate_completion_audit_launch_pack.py", "--format json"],
        ["generate_completion_audit_launch_pack.py", "--format markdown"],
        ["validate_completion_audit_launch_pack.py"],
        ["generate_completion_audit_setup_state.py", "--out <setup-state-json>"],
        ["validate_completion_audit_setup_state.py", "--launch-pack <launch-pack-json>"],
        [
            "generate_completion_audit_setup_handle_plan.py",
            "<setup-state-json>",
            "--launch-pack <launch-pack-json>",
            "--out <setup-handle-plan-json>",
        ],
        [
            "validate_completion_audit_setup_handle_plan.py",
            "<setup-handle-plan-json>",
            "--setup-state <setup-state-json>",
            "--launch-pack <launch-pack-json>",
        ],
        [
            "probe_completion_audit_setup_handle_evidence.py",
            "<setup-handle-plan-json>",
            "--runtime-evidence-dir <runtime-evidence-dir>",
            "--runtime-evidence-bundle-report <runtime-evidence-bundle-report-json>",
            "--allow-env-read",
            "--allow-network",
            "--out <setup-handle-evidence-json>",
        ],
        [
            "generate_completion_audit_setup_attestation_from_handles.py",
            "<setup-handle-plan-json>",
            "<setup-handle-evidence-json>",
            "--setup-state <setup-state-json>",
            "--launch-pack <launch-pack-json>",
            "--out <setup-attestation-json>",
        ],
        [
            "apply_completion_audit_setup_attestation.py",
            "<setup-state-json>",
            "<setup-attestation-json>",
            "--launch-pack <launch-pack-json>",
            "--out <setup-state-attested-json>",
        ],
        [
            "generate_completion_audit_dispatch_gate.py",
            "<launch-pack-json>",
            "<setup-state-attested-json>",
            "--out <dispatch-gate-attested-json>",
        ],
        [
            "validate_completion_audit_dispatch_gate.py",
            "<dispatch-gate-attested-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-attested-json>",
        ],
        [
            "run_completion_audit_dispatch_gate.py",
            "<dispatch-gate-attested-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-attested-json>",
            "--allow-pending-report",
            "--out <dispatch-run-attested-json>",
        ],
        [
            "validate_completion_audit_dispatch_run.py",
            "<dispatch-run-attested-json>",
            "--dispatch-gate <dispatch-gate-attested-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-attested-json>",
            "--repo-root .",
        ],
        [
            "generate_completion_audit_dispatch_gate.py",
            "<launch-pack-json>",
            "<setup-state-json>",
            "--out <dispatch-gate-json>",
        ],
        [
            "validate_completion_audit_dispatch_gate.py",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-json>",
        ],
        [
            "run_completion_audit_dispatch_gate.py",
            "<dispatch-gate-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-json>",
            "--allow-pending-report",
            "--out <dispatch-run-json>",
        ],
        [
            "validate_completion_audit_dispatch_run.py",
            "<dispatch-run-json>",
            "--dispatch-gate <dispatch-gate-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-json>",
            "--repo-root .",
        ],
        [
            "run_completion_audit_dispatch_diagnostics.py",
            "<dispatch-run-json>",
            "--dispatch-gate <dispatch-gate-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-json>",
            "--repo-root .",
            "--out <dispatch-diagnostics-json>",
        ],
        [
            "validate_completion_audit_dispatch_diagnostics.py",
            "<dispatch-diagnostics-json>",
            "--dispatch-run <dispatch-run-json>",
            "--dispatch-gate <dispatch-gate-json>",
            "--launch-pack <launch-pack-json>",
            "--setup-state <setup-state-json>",
            "--repo-root .",
        ],
        [
            "validate_completion_audit_control_chain.py",
            "--readiness-report",
            "--run-plan <run-plan-json>",
            "--setup-handle-plan <setup-handle-plan-json>",
            "--dispatch-run <dispatch-run-json>",
            "--repo-root .",
        ],
    ]
    if len(commands) != len(expected_token_groups):
        return [
            "run plan post_run_verification_commands must contain "
            f"{ONLY_CANONICAL_VERIFICATION_COMMANDS_TOKEN}"
        ]
    for command, tokens in zip(commands, expected_token_groups, strict=True):
        if not _command_has_tokens(command, tokens):
            return [
                "run plan post_run_verification_commands must keep canonical "
                f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
            ]
    if len({tuple(command.split()) for command in commands}) != len(commands):
        return [
            "run plan post_run_verification_commands must keep canonical "
            f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
        ]
    return []


def _post_run_launch_pack_command_errors(commands: list[str]) -> list[str]:
    errors: list[str] = []
    bundle_validate_commands = [
        command
        for command in commands
        if "validate_runtime_evidence_bundle.py" in command
    ]
    setup_handle_probe_commands = [
        command
        for command in commands
        if "probe_completion_audit_setup_handle_evidence.py" in command
    ]
    run_plan_generate_commands = [
        command
        for command in commands
        if "generate_completion_audit_run_plan.py" in command
    ]
    run_plan_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_run_plan.py" in command
    ]
    readiness_report_commands = [
        command
        for command in commands
        if "report_completion_audit_readiness.py" in command
    ]
    readiness_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_readiness.py" in command
    ]
    generate_commands = [
        command
        for command in commands
        if "generate_completion_audit_launch_pack.py" in command
    ]
    validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_launch_pack.py" in command
    ]
    setup_generate_commands = [
        command
        for command in commands
        if "generate_completion_audit_setup_state.py" in command
    ]
    setup_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_setup_state.py" in command
    ]
    setup_handle_plan_generate_commands = [
        command
        for command in commands
        if "generate_completion_audit_setup_handle_plan.py" in command
    ]
    setup_handle_plan_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_setup_handle_plan.py" in command
    ]
    dispatch_gate_generate_commands = [
        command
        for command in commands
        if "generate_completion_audit_dispatch_gate.py" in command
    ]
    dispatch_gate_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_dispatch_gate.py" in command
    ]
    dispatch_gate_run_commands = [
        command
        for command in commands
        if "run_completion_audit_dispatch_gate.py" in command
    ]
    dispatch_run_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_dispatch_run.py" in command
    ]
    dispatch_diagnostics_run_commands = [
        command
        for command in commands
        if "run_completion_audit_dispatch_diagnostics.py" in command
    ]
    dispatch_diagnostics_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_dispatch_diagnostics.py" in command
    ]
    control_chain_validate_commands = [
        command
        for command in commands
        if "validate_completion_audit_control_chain.py" in command
    ]
    if not generate_commands:
        errors.append(
            "run plan post_run_verification_commands must regenerate launch pack"
        )
    if not validate_commands:
        errors.append("run plan post_run_verification_commands must validate launch pack")
    if not setup_generate_commands:
        errors.append(
            "run plan post_run_verification_commands must regenerate setup state"
        )
    if not setup_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate setup state"
        )
    if not setup_handle_plan_generate_commands:
        errors.append(
            "run plan post_run_verification_commands must regenerate setup handle plan"
        )
    if not setup_handle_plan_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate setup handle plan"
        )
    if not dispatch_gate_generate_commands:
        errors.append(
            "run plan post_run_verification_commands must regenerate dispatch gate"
        )
    if not dispatch_gate_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate dispatch gate"
        )
    if not dispatch_gate_run_commands:
        errors.append(
            "run plan post_run_verification_commands must run dispatch gate runner"
        )
    if not dispatch_run_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate dispatch run"
        )
    if not dispatch_diagnostics_run_commands:
        errors.append(
            "run plan post_run_verification_commands must run dispatch diagnostics"
        )
    if not dispatch_diagnostics_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate dispatch diagnostics"
        )
    if not control_chain_validate_commands:
        errors.append(
            "run plan post_run_verification_commands must validate control chain"
        )
    if bundle_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_runtime_evidence_bundle.py",
                "--format json",
                "--out <runtime-evidence-bundle-report-json>",
            ],
        )
        for command in bundle_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must write "
            "<runtime-evidence-bundle-report-json>"
        )
    if setup_handle_probe_commands and not any(
        _command_has_tokens(
            command,
            [
                "probe_completion_audit_setup_handle_evidence.py",
                "--runtime-evidence-dir <runtime-evidence-dir>",
                "--runtime-evidence-bundle-report <runtime-evidence-bundle-report-json>",
            ],
        )
        for command in setup_handle_probe_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must bind setup handle "
            "evidence to <runtime-evidence-bundle-report-json>"
        )
    if readiness_report_commands and not any(
        _command_has_tokens(
            command,
            [
                "--format markdown",
                "--out <readiness-markdown>",
            ],
        )
        for command in readiness_report_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate "
            "readiness Markdown into <readiness-markdown>"
        )
    if readiness_validate_commands and not any(
        _command_has_tokens(
            command,
            ["--markdown-report <readiness-markdown>"],
        )
        for command in readiness_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "readiness Markdown"
        )
    if readiness_validate_commands and not any(
        _command_has_tokens(
            command,
            ["--self-harness-report-bundle <downloaded-self-harness-reports-dir>"],
        )
        for command in readiness_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "readiness self-harness bundle source"
        )
    if run_plan_generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "--format markdown",
                "--out <run-plan-markdown>",
            ],
        )
        for command in run_plan_generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate run "
            "plan Markdown into <run-plan-markdown>"
        )
    if run_plan_validate_commands and not any(
        _command_has_tokens(
            command,
            ["--markdown-report <run-plan-markdown>"],
        )
        for command in run_plan_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate run plan "
            "Markdown"
        )
    if run_plan_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "--readiness-markdown-report <readiness-markdown>",
                "--readiness-preflight-dir <preflight-dir>",
                "--self-harness-report-bundle <downloaded-self-harness-reports-dir>",
            ],
        )
        for command in run_plan_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            f"{READINESS_SOURCE_VALIDATION_COMMAND_TOKEN}"
        )
    if generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "<run-plan-json>",
                "--format json",
                "--out <launch-pack-json>",
            ],
        )
        for command in generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate launch "
            "pack from <run-plan-json> into <launch-pack-json>"
        )
    if generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "<run-plan-json>",
                "--format markdown",
                "--out <launch-pack-markdown>",
            ],
        )
        for command in generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate launch "
            "pack Markdown from <run-plan-json> into <launch-pack-markdown>"
        )
    if validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "<launch-pack-json>",
                "--run-plan <run-plan-json>",
                "--repo-root .",
                "--markdown-report <launch-pack-markdown>",
            ],
        )
        for command in validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<launch-pack-json> against <run-plan-json>, repo source, and "
            "launch-pack Markdown"
        )
    if setup_generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "generate_completion_audit_setup_state.py",
                "<launch-pack-json>",
                "--repo-root .",
                "--out <setup-state-json>",
            ],
        )
        for command in setup_generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate setup "
            "state from <launch-pack-json> and repo source into <setup-state-json>"
        )
    if setup_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_setup_state.py",
                "<setup-state-json>",
                "--launch-pack <launch-pack-json>",
            ],
        )
        for command in setup_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<setup-state-json> against <launch-pack-json>"
        )
    if setup_handle_plan_generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "generate_completion_audit_setup_handle_plan.py",
                "<setup-state-json>",
                "--launch-pack <launch-pack-json>",
                "--out <setup-handle-plan-json>",
            ],
        )
        for command in setup_handle_plan_generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate setup "
            "handle plan from setup-state/launch-pack sources"
        )
    if setup_handle_plan_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_setup_handle_plan.py",
                "<setup-handle-plan-json>",
                "--setup-state <setup-state-json>",
                "--launch-pack <launch-pack-json>",
            ],
        )
        for command in setup_handle_plan_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<setup-handle-plan-json> against setup-state/launch-pack sources"
        )
    if dispatch_gate_generate_commands and not any(
        _command_has_tokens(
            command,
            [
                "generate_completion_audit_dispatch_gate.py",
                "<launch-pack-json>",
                "<setup-state-json>",
                "--out <dispatch-gate-json>",
            ],
        )
        for command in dispatch_gate_generate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must regenerate dispatch "
            "gate from launch-pack/setup-state sources"
        )
    if dispatch_gate_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_dispatch_gate.py",
                "<dispatch-gate-json>",
                "--launch-pack <launch-pack-json>",
                "--setup-state <setup-state-json>",
            ],
        )
        for command in dispatch_gate_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<dispatch-gate-json> against launch-pack/setup-state sources"
        )
    if dispatch_gate_run_commands and not any(
        _command_has_tokens(
            command,
            [
                "run_completion_audit_dispatch_gate.py",
                "<dispatch-gate-json>",
                "--launch-pack <launch-pack-json>",
                "--setup-state <setup-state-json>",
                "--allow-pending-report",
                "--out <dispatch-run-json>",
            ],
        )
        for command in dispatch_gate_run_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must materialize dispatch "
            "gate runner report without bypassing pending setup"
        )
    if dispatch_run_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_dispatch_run.py",
                "<dispatch-run-json>",
                "--dispatch-gate <dispatch-gate-json>",
                "--launch-pack <launch-pack-json>",
                "--setup-state <setup-state-json>",
                "--repo-root .",
            ],
        )
        for command in dispatch_run_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<dispatch-run-json> against dispatch gate sources"
        )
    if dispatch_diagnostics_run_commands and not any(
        _command_has_tokens(
            command,
            [
                "run_completion_audit_dispatch_diagnostics.py",
                "<dispatch-run-json>",
                "--dispatch-gate <dispatch-gate-json>",
                "--launch-pack <launch-pack-json>",
                "--setup-state <setup-state-json>",
                "--repo-root .",
                "--out <dispatch-diagnostics-json>",
            ],
        )
        for command in dispatch_diagnostics_run_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must materialize "
            "dispatch diagnostics from <dispatch-run-json>"
        )
    if dispatch_diagnostics_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_dispatch_diagnostics.py",
                "<dispatch-diagnostics-json>",
                "--dispatch-run <dispatch-run-json>",
                "--dispatch-gate <dispatch-gate-json>",
                "--launch-pack <launch-pack-json>",
                "--setup-state <setup-state-json>",
                "--repo-root .",
            ],
        )
        for command in dispatch_diagnostics_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate "
            "<dispatch-diagnostics-json> against dispatch-run sources"
        )
    if control_chain_validate_commands and not any(
        _command_has_tokens(
            command,
            [
                "validate_completion_audit_control_chain.py",
                "--readiness-report",
                "--run-plan <run-plan-json>",
                "--run-plan-markdown <run-plan-markdown>",
                "--launch-pack <launch-pack-json>",
                "--launch-pack-markdown <launch-pack-markdown>",
                "--setup-state <setup-state-json>",
                "--setup-handle-plan <setup-handle-plan-json>",
                "--dispatch-gate <dispatch-gate-json>",
                "--dispatch-run <dispatch-run-json>",
                "--repo-root .",
            ],
        )
        for command in control_chain_validate_commands
    ):
        errors.append(
            "run plan post_run_verification_commands must validate the full "
            "completion audit control chain"
        )
    return errors


def _command_has_tokens(command: str, tokens: list[str]) -> bool:
    return all(token in command for token in tokens)


def _scoped_count_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["run plan scoped_counts must be an object"]
    errors: list[str] = []
    fields = set(value)
    if fields != COUNT_FIELDS:
        errors.append("run plan scoped_counts fields must match contract")
    for field in COUNT_FIELDS:
        if not _is_non_negative_int(value.get(field)):
            errors.append(f"run plan scoped_counts.{field} must be a non-negative integer")
    return errors


def _run_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["run plan run_items must be a list"], items
    for item in value:
        if not isinstance(item, dict):
            errors.append("run plan run_item entries must be objects")
            continue
        items.append(item)
        fields = set(item)
        if fields != RUN_ITEM_FIELDS:
            errors.append("run plan run_item fields must match contract")
        for field in (
            "requirement_id",
            "title",
            "layer",
            "current_status",
            "artifact",
            "evidence_schema_version",
            "probe",
        ):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"run plan run_item {field} must be a non-empty string")
        if item.get("current_status") not in {"missing", "failed"}:
            errors.append("run plan run_item current_status must be missing or failed")
        for field in (
            "error_codes",
            "credential_or_external_setup_tokens",
        ):
            if not _is_string_list(item.get(field)):
                errors.append(f"run plan run_item {field} must be a string list")
        if not isinstance(item.get("blocked_by_live_setup"), bool):
            errors.append("run plan run_item blocked_by_live_setup must be a boolean")
        errors.extend(_workflow_errors(item.get("workflow_execution")))
        errors.extend(
            _preflight_errors(
                item.get("preflight"),
                requirement_id=str(item.get("requirement_id") or ""),
            )
        )
        errors.extend(_operator_action_errors(item.get("required_operator_actions")))
        errors.extend(_acceptance_errors(item.get("acceptance"), item))
    return errors, items


def _workflow_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["run plan workflow_execution must be an object"]
    errors: list[str] = []
    if set(value) != WORKFLOW_FIELDS:
        errors.append("run plan workflow_execution fields must match contract")
    if not isinstance(value.get("workflow"), str) or not value.get("workflow"):
        errors.append("run plan workflow_execution workflow must be a non-empty string")
    for field in WORKFLOW_FIELDS - {"workflow"}:
        if not _is_string_list(value.get(field)):
            errors.append(f"run plan workflow_execution {field} must be a string list")
    return errors


def _preflight_errors(value: Any, *, requirement_id: str) -> list[str]:
    if not isinstance(value, dict):
        return ["run plan preflight must be an object"]
    errors: list[str] = []
    if set(value) != PREFLIGHT_FIELDS:
        errors.append("run plan preflight fields must match contract")
    for field in (
        "status",
        "schema_version",
        "generated_at",
        "source_file",
        "source_file_sha256",
        "source_validation_schema_version",
    ):
        if not isinstance(value.get(field), str):
            errors.append(f"run plan preflight {field} must be a string")
    if value.get("status") and value.get("status") not in {"pass", "fail"}:
        errors.append("run plan preflight status must be empty, pass, or fail")
    source_sha = value.get("source_file_sha256")
    if source_sha and not _is_fingerprint(source_sha):
        errors.append("run plan preflight source_file_sha256 must be a SHA-256 hex string")
    if not _is_string_list(value.get("required_next")):
        errors.append("run plan preflight required_next must be a string list")
    if not _is_string_list(value.get("source_validation_error_codes")):
        errors.append(
            "run plan preflight source_validation_error_codes must be a string list"
        )
    for field in ("source_validation_ok", "raw_payload_included"):
        if not isinstance(value.get(field), bool):
            errors.append(f"run plan preflight {field} must be a boolean")
    if value.get("raw_payload_included") is not False:
        errors.append("run plan preflight raw_payload_included must be false")
    errors.extend(_setup_contract_errors(value, requirement_id=requirement_id))
    return errors


def _setup_contract_errors(
    preflight: dict[str, Any],
    *,
    requirement_id: str,
) -> list[str]:
    value = preflight.get("setup_contract")
    if not isinstance(value, dict):
        return ["run plan preflight setup_contract must be an object"]
    if value == {}:
        return []
    errors: list[str] = []
    if set(value) != SETUP_CONTRACT_FIELDS:
        errors.append("run plan preflight setup_contract fields must match contract")
    if value.get("version") != SETUP_CONTRACT_VERSION:
        errors.append("run plan preflight setup_contract.version must match contract")
    if value.get("requirement_id") != requirement_id:
        errors.append(
            "run plan preflight setup_contract.requirement_id must match run_item"
        )
    if value.get("required_next") != preflight.get("required_next"):
        errors.append(
            "run plan preflight setup_contract.required_next must match preflight"
        )
    for field in (
        "required_next",
        "workflow_inputs_required",
        "environment_flags_required",
        "credential_slots_required",
        "external_setup_required",
    ):
        field_value = value.get(field)
        if not _is_string_list(field_value):
            errors.append(f"run plan preflight setup_contract.{field} must be a string list")
        elif "" in field_value:
            errors.append(
                f"run plan preflight setup_contract.{field} must not include empty strings"
            )
        elif len(field_value) != len(set(field_value)):
            errors.append(
                f"run plan preflight setup_contract.{field} must not contain duplicates"
            )
    dispatch_ready = value.get("dispatch_ready")
    if not isinstance(dispatch_ready, bool):
        errors.append("run plan preflight setup_contract.dispatch_ready must be a boolean")
    elif dispatch_ready != (preflight.get("status") == "pass" and not preflight.get("required_next")):
        errors.append(
            "run plan preflight setup_contract.dispatch_ready must match preflight status"
        )
    forbidden_tokens = {
        "TELEGRAM_BOT_TOKEN",
        "FACEBOOK_PAGE_ACCESS_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
        "WIII_ACCEPTANCE_BEARER_TOKEN",
        "access_token",
        "api_key",
        "authorization",
    }
    rendered = json.dumps(value, sort_keys=True)
    if any(token in rendered for token in forbidden_tokens):
        errors.append(
            "run plan preflight setup_contract must not include raw credential names"
        )
    return errors


def _operator_action_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["run plan required_operator_actions must be a list"]
    errors: list[str] = []
    for action in value:
        if not isinstance(action, dict):
            errors.append("run plan required_operator_action entries must be objects")
            continue
        if set(action) != OPERATOR_ACTION_FIELDS:
            errors.append("run plan required_operator_action fields must match contract")
        for field in OPERATOR_ACTION_FIELDS:
            if not isinstance(action.get(field), str) or not action.get(field):
                errors.append(
                    f"run plan required_operator_action {field} must be a non-empty string"
                )
    return errors


def _acceptance_errors(value: Any, item: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return ["run plan acceptance must be an object"]
    errors: list[str] = []
    if set(value) != ACCEPTANCE_FIELDS:
        errors.append("run plan acceptance fields must match contract")
    if value.get("expected_artifact") != item.get("artifact"):
        errors.append("run plan acceptance expected_artifact must match item artifact")
    if value.get("expected_schema_version") != item.get("evidence_schema_version"):
        errors.append(
            "run plan acceptance expected_schema_version must match item schema"
        )
    if not _is_string_list(value.get("accepted_when")) or not value.get("accepted_when"):
        errors.append("run plan acceptance accepted_when must be a non-empty string list")
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["run plan privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("run plan privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"run plan privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    report_errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(report_errors):
        return errors
    expected_codes = _error_codes(report_errors)
    expected_counts = _error_code_counts(report_errors)
    if _is_string_list(error_codes) and error_codes != expected_codes:
        errors.append("run plan error_codes must match errors")
    if error_code_counts != expected_counts:
        errors.append("run plan error_code_counts must match errors")
    return errors


def _run_item_summary_errors(
    payload: dict[str, Any],
    run_items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("run_item_count") != len(run_items):
        errors.append("run plan run_item_count must match run_items")
    blocked_count = sum(1 for item in run_items if item.get("blocked_by_live_setup"))
    if payload.get("blocked_by_live_setup_count") != blocked_count:
        errors.append("run plan blocked_by_live_setup_count must match run_items")
    if payload.get("run_items_fingerprint_sha256") != _run_items_fingerprint(
        run_items,
        schema_version=RUN_PLAN_SCHEMA_VERSION,
        readiness_schema_version=str(payload.get("readiness_schema_version") or ""),
        readiness_scoped_next_actions_fingerprint_sha256=str(
            payload.get("readiness_scoped_next_actions_fingerprint_sha256") or ""
        ),
    ):
        errors.append("run plan run_items_fingerprint_sha256 must match run_items")
    requirement_ids = [item.get("requirement_id") for item in run_items]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("run plan run_items must not duplicate requirement_id")
    expected_state = _expected_execution_state(payload, run_items)
    if payload.get("execution_state") != expected_state:
        errors.append("run plan execution_state must match readiness and run_items")
    return errors


def _operator_setup_fingerprint_errors(
    payload: dict[str, Any],
    run_items: list[dict[str, Any]],
) -> list[str]:
    fingerprint = payload.get("operator_setup_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        return []
    if fingerprint != _operator_setup_fingerprint(run_items):
        return [
            "run plan operator_setup_fingerprint_sha256 must match setup fields"
        ]
    return []


def _acceptance_contract_fingerprint_errors(
    payload: dict[str, Any],
    run_items: list[dict[str, Any]],
) -> list[str]:
    fingerprint = payload.get("acceptance_contract_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        return []
    if fingerprint != _acceptance_contract_fingerprint(run_items):
        return [
            "run plan acceptance_contract_fingerprint_sha256 must match "
            "acceptance fields"
        ]
    return []


def _readiness_source_errors(
    payload: dict[str, Any],
    *,
    readiness_report_path: Path,
    readiness_payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if payload.get("readiness_report_sha256") != _sha256_file(readiness_report_path):
        errors.append("run plan readiness_report_sha256 must match readiness report")
    expected_fields = {
        "readiness_schema_version": readiness_payload.get("schema_version"),
        "readiness_scoped_completion_audit_ready": readiness_payload.get(
            "scoped_completion_audit_ready"
        ),
        "readiness_scoped_next_actions_fingerprint_sha256": readiness_payload.get(
            "scoped_next_actions_fingerprint_sha256"
        ),
        "readiness_preflight_summary_count": readiness_payload.get(
            "preflight_summary_count"
        ),
        "excluded_requirement_ids": readiness_payload.get("excluded_requirement_ids"),
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            errors.append(f"run plan {field} must match readiness report")
    expected_counts = {
        "requirements": readiness_payload.get("scoped_requirement_count"),
        "passed": readiness_payload.get("scoped_passed_count"),
        "missing": readiness_payload.get("scoped_missing_count"),
        "failed": readiness_payload.get("scoped_failed_count"),
    }
    if payload.get("scoped_counts") != expected_counts:
        errors.append("run plan scoped_counts must match readiness report")
    errors.extend(_readiness_action_match_errors(payload, readiness_payload))
    return errors


def _markdown_report_errors(
    markdown_report_path: Path,
    *,
    readiness_report_path: Path | None,
) -> list[str]:
    if readiness_report_path is None:
        return ["run plan markdown report validation requires --readiness-report"]
    if not markdown_report_path.is_file() or markdown_report_path.is_symlink():
        return ["completion audit run plan markdown report path must be a regular file"]
    readiness_validation = readiness_validator.validate_readiness_report(
        readiness_report_path
    )
    if not readiness_validation.ok:
        return [
            "completion audit run plan markdown report readiness source failed "
            "validation: "
            + "; ".join(readiness_validation.errors)
        ]
    expected_markdown = format_markdown(
        generate_completion_audit_run_plan(readiness_report_path)
    )
    actual_markdown = markdown_report_path.read_text(encoding="utf-8")
    if actual_markdown.rstrip("\n") != expected_markdown.rstrip("\n"):
        return ["run plan markdown report must match generated run plan"]
    return []


def _readiness_action_match_errors(
    payload: dict[str, Any],
    readiness_payload: dict[str, Any],
) -> list[str]:
    run_items = payload.get("run_items")
    actions = readiness_payload.get("scoped_next_actions")
    if not isinstance(run_items, list) or not isinstance(actions, list):
        return []
    errors: list[str] = []
    if len(run_items) != len(actions):
        return ["run plan run_items must match readiness scoped_next_actions"]
    preflight_by_requirement = {
        summary.get("requirement_id"): summary
        for summary in readiness_payload.get("preflight_summaries", [])
        if isinstance(summary, dict)
    }
    for item, action in zip(run_items, actions, strict=True):
        if not isinstance(item, dict) or not isinstance(action, dict):
            continue
        expected_preflight = preflight_by_requirement.get(action.get("requirement_id"))
        if not _run_item_matches_action(item, action, expected_preflight):
            errors.append("run plan run_item must match readiness scoped_next_action")
            break
    return errors


def _run_item_matches_action(
    item: dict[str, Any],
    action: dict[str, Any],
    preflight_summary: dict[str, Any] | None,
) -> bool:
    workflow = item.get("workflow_execution")
    preflight = item.get("preflight")
    if not isinstance(workflow, dict) or not isinstance(preflight, dict):
        return False
    expected_dispatch_inputs = [
        token
        for token in action.get("dispatch_or_schedule_gate_tokens", [])
        if isinstance(token, str) and not token.startswith("WIII_")
    ]
    expected_schedule_flags = [
        token
        for token in action.get("dispatch_or_schedule_gate_tokens", [])
        if isinstance(token, str) and token.startswith("WIII_")
    ]
    return (
        item.get("requirement_id") == action.get("requirement_id")
        and item.get("title") == action.get("title")
        and item.get("layer") == action.get("layer")
        and item.get("current_status") == action.get("status")
        and item.get("artifact") == action.get("artifact")
        and item.get("evidence_schema_version") == action.get("schema_version")
        and item.get("probe") == action.get("probe")
        and item.get("error_codes") == action.get("error_codes")
        and workflow.get("workflow") == action.get("workflow")
        and workflow.get("workflow_dispatch_inputs") == expected_dispatch_inputs
        and workflow.get("schedule_env_flags") == expected_schedule_flags
        and workflow.get("live_probe_env_flags") == action.get("live_env_flags")
        and workflow.get("live_probe_guard_tokens") == action.get("live_guard_tokens")
        and workflow.get("artifact_tokens") == action.get("artifact_tokens")
        and preflight.get("status") == action.get("preflight_status")
        and preflight.get("schema_version") == action.get("preflight_schema_version")
        and preflight.get("generated_at") == action.get("preflight_generated_at")
        and preflight.get("required_next") == action.get("preflight_required_next")
        and preflight.get("source_file") == action.get("preflight_source_file")
        and _preflight_source_matches_summary(preflight, preflight_summary)
    )


def _preflight_source_matches_summary(
    preflight: dict[str, Any],
    summary: dict[str, Any] | None,
) -> bool:
    if summary is None:
        return (
            preflight.get("source_file_sha256") == ""
            and preflight.get("source_validation_schema_version") == ""
            and preflight.get("source_validation_ok") is False
            and preflight.get("source_validation_error_codes") == []
            and preflight.get("raw_payload_included") is False
            and preflight.get("setup_contract") == {}
        )
    return (
        preflight.get("source_file_sha256") == summary.get("source_file_sha256")
        and preflight.get("source_validation_schema_version")
        == summary.get("source_validation_schema_version")
        and preflight.get("source_validation_ok") == summary.get("source_validation_ok")
        and preflight.get("source_validation_error_codes")
        == summary.get("source_validation_error_codes")
        and preflight.get("raw_payload_included") == summary.get("raw_payload_included")
        and preflight.get("setup_contract") == summary.get("setup_contract")
    )


def _expected_execution_state(
    payload: dict[str, Any],
    run_items: list[dict[str, Any]],
) -> str:
    if payload.get("readiness_scoped_completion_audit_ready") is True:
        return "scoped_ready"
    if not run_items:
        return "no_scoped_blockers"
    if any(item.get("blocked_by_live_setup") for item in run_items):
        return "blocked_on_live_setup"
    return "ready_for_live_dispatch"


def _run_items_fingerprint(
    run_items: list[dict[str, Any]],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
    readiness_schema_version: str = "",
    readiness_scoped_next_actions_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "readiness_schema_version": readiness_schema_version,
        "readiness_scoped_next_actions_fingerprint_sha256": (
            readiness_scoped_next_actions_fingerprint_sha256
        ),
        "run_items": run_items,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operator_setup_fingerprint(
    run_items: list[dict[str, Any]],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "operator_setup": [
            {
                "blocked_by_live_setup": item.get("blocked_by_live_setup"),
                "credential_or_external_setup_tokens": item.get(
                    "credential_or_external_setup_tokens"
                ),
                "preflight": _setup_preflight(item.get("preflight")),
                "required_operator_actions": item.get("required_operator_actions"),
                "requirement_id": item.get("requirement_id"),
                "workflow_execution": item.get("workflow_execution"),
            }
            for item in run_items
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _acceptance_contract_fingerprint(
    run_items: list[dict[str, Any]],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "acceptance_contract": [
            {
                "acceptance": item.get("acceptance"),
                "requirement_id": item.get("requirement_id"),
            }
            for item in run_items
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _setup_preflight(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "required_next": value.get("required_next"),
        "schema_version": value.get("schema_version"),
        "setup_contract": value.get("setup_contract"),
        "source_file": value.get("source_file"),
        "status": value.get("status"),
    }


def _verification_command_specs_fingerprint(
    specs: list[Any],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "post_run_verification_command_specs": specs,
    }
    encoded = json.dumps(
        manifest,
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


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit run plan path must be a regular file":
        return "completion_audit_run_plan_path_invalid"
    if error.startswith("completion audit run plan JSON is invalid"):
        return "completion_audit_run_plan_json_invalid"
    if error == "completion audit run plan root must be an object":
        return "completion_audit_run_plan_root_invalid"
    if error.startswith("completion audit run plan readiness source failed validation"):
        return "completion_audit_run_plan_readiness_invalid"
    if "markdown report" in error:
        return "completion_audit_run_plan_markdown_invalid"
    if error.startswith("run plan missing required field"):
        return "completion_audit_run_plan_missing_required_fields"
    if error.startswith("run plan has unsupported field"):
        return "completion_audit_run_plan_unsupported_fields"
    if error.startswith("run plan schema_version must be"):
        return "completion_audit_run_plan_schema_mismatch"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_run_plan_fingerprint_invalid"
    if "must match readiness report" in error:
        return "completion_audit_run_plan_readiness_mismatch"
    if "canonical verification" in error:
        return "completion_audit_run_plan_post_run_verification_order_invalid"
    if "shell control operator" in error:
        return "completion_audit_run_plan_post_run_verification_command_unsafe"
    if (
        "post_run_verification_command_specs" in error
        or "post_run_verification_commands must match" in error
    ):
        return "completion_audit_run_plan_post_run_verification_spec_invalid"
    if "readiness Markdown" in error or "readiness self-harness bundle source" in error:
        return "completion_audit_run_plan_readiness_verification_invalid"
    if "launch pack" in error:
        return "completion_audit_run_plan_launch_pack_verification_invalid"
    if "run_item" in error or "run_items" in error:
        return "completion_audit_run_plan_item_invalid"
    if "preflight" in error:
        return "completion_audit_run_plan_preflight_invalid"
    if "privacy" in error:
        return "completion_audit_run_plan_privacy_invalid"
    if "workflow_execution" in error:
        return "completion_audit_run_plan_workflow_invalid"
    if "acceptance" in error:
        return "completion_audit_run_plan_acceptance_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_run_plan_error_summary_invalid"
    if "must be a boolean" in error:
        return "completion_audit_run_plan_boolean_invalid"
    if "non-negative integer" in error:
        return "completion_audit_run_plan_count_invalid"
    if "string list" in error:
        return "completion_audit_run_plan_string_list_invalid"
    return "completion_audit_run_plan_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit operator run plan artifact.",
    )
    parser.add_argument("run_plan_path", type=Path)
    parser.add_argument(
        "--readiness-report",
        type=Path,
        default=None,
        help="Optional readiness report that the run plan must match.",
    )
    parser.add_argument(
        "--readiness-markdown-report",
        type=Path,
        default=None,
        help=(
            "Optional readiness Markdown report that must match the supplied "
            "readiness JSON."
        ),
    )
    parser.add_argument(
        "--readiness-preflight-dir",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional preflight source directory referenced by the readiness "
            "report. May be supplied more than once."
        ),
    )
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        default=None,
        help=(
            "Optional self-harness report bundle source referenced by the "
            "readiness report."
        ),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=None,
        help=(
            "Optional Markdown run-plan report that must match the supplied "
            "readiness report."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_run_plan(
        args.run_plan_path,
        readiness_report_path=args.readiness_report,
        readiness_markdown_report_path=args.readiness_markdown_report,
        readiness_preflight_dirs=args.readiness_preflight_dir,
        self_harness_report_bundle_path=args.self_harness_report_bundle,
        markdown_report_path=args.markdown_report,
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
        print("Wiii Completion Audit Run Plan Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Run Plan Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
