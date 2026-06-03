#!/usr/bin/env python3
"""Validate completion-audit launch pack artifacts."""

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

from generate_completion_audit_launch_pack import (  # noqa: E402
    LAUNCH_PACK_SCHEMA_VERSION,
    format_markdown,
    generate_completion_audit_launch_pack,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_run_plan as run_plan_validator  # noqa: E402
from validate_runtime_evidence_preflight import SETUP_CONTRACT_VERSION  # noqa: E402


LAUNCH_PACK_VALIDATION_SCHEMA_VERSION = "wiii.completion_audit_launch_pack_validation.v1"
READINESS_SOURCE_VALIDATION_COMMAND_TOKEN = (
    "run plan against readiness Markdown, preflight sources, and self-harness bundle"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "run_plan_path",
    "run_plan_sha256",
    "run_plan_schema_version",
    "run_plan_execution_state",
    "run_plan_run_items_fingerprint_sha256",
    "run_plan_operator_setup_fingerprint_sha256",
    "run_plan_acceptance_contract_fingerprint_sha256",
    "run_plan_post_run_verification_command_specs_fingerprint_sha256",
    "launch_item_count",
    "launch_items_fingerprint_sha256",
    "launch_acceptance_fingerprint_sha256",
    "launch_setup_fingerprint_sha256",
    "launch_command_specs_fingerprint_sha256",
    "launch_items",
    "unsupported_run_item_count",
    "unsupported_requirement_ids",
    "post_launch_verification_commands",
    "post_launch_verification_command_specs_fingerprint_sha256",
    "post_launch_verification_command_specs",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
LAUNCH_ITEM_FIELDS = {
    "requirement_id",
    "title",
    "current_status",
    "workflow",
    "probe",
    "expected_artifact",
    "expected_schema_version",
    "artifact_tokens",
    "diagnostic_artifact_tokens",
    "preflight_source_file",
    "preflight_status",
    "preflight_schema_version",
    "preflight_generated_at",
    "preflight_source_file_sha256",
    "preflight_source_validation_schema_version",
    "preflight_source_validation_ok",
    "preflight_source_validation_error_codes",
    "preflight_raw_payload_included",
    "preflight_required_next",
    "preflight_setup_contract",
    "preflight_setup_contract_bindings",
    "required_operator_action_tokens",
    "required_operator_actions",
    "required_github_inputs",
    "required_github_vars",
    "required_github_secrets",
    "conditional_github_secrets",
    "required_environment_variables",
    "commands",
    "command_specs",
    "acceptance_checks",
}
OPERATOR_ACTION_FIELDS = {"token", "category", "instruction"}
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
SETUP_BINDING_FIELDS = {
    "workflow_inputs_required",
    "environment_flags_required",
    "credential_slots_required",
    "external_setup_required",
}
COMMAND_FIELDS = {
    "workflow_dispatch",
    "local_preflight",
    "validate_preflight",
    "local_failure_from_preflight",
    "local_live_probe",
    "validate_artifact",
    "download_artifact",
    "download_preflight_artifact",
}
COMMAND_SPEC_FIELDS = {"working_directory", "argv", "uses_shell"}
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
CANONICAL_VERIFICATION_ORDER_TOKEN = "canonical verification order"
ONLY_CANONICAL_VERIFICATION_COMMANDS_TOKEN = "only canonical verification commands"


@dataclass(frozen=True)
class LaunchPackValidationResult:
    validation_schema_version: str
    launch_pack_path: str
    run_plan_path: str | None
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


def validate_launch_pack(
    launch_pack_path: Path,
    *,
    run_plan_path: Path | None = None,
    repo_root: Path | None = None,
    markdown_report_path: Path | None = None,
) -> LaunchPackValidationResult:
    errors: list[str] = []
    payload = _load_payload(launch_pack_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if run_plan_path is not None:
            errors.extend(
                _run_plan_source_errors(
                    payload,
                    run_plan_path=run_plan_path,
                )
            )
        if repo_root is not None:
            errors.extend(_repo_source_errors(payload, repo_root))
        if markdown_report_path is not None:
            errors.extend(
                _markdown_report_errors(
                    markdown_report_path,
                    run_plan_path=run_plan_path,
                )
            )
    return LaunchPackValidationResult(
        validation_schema_version=LAUNCH_PACK_VALIDATION_SCHEMA_VERSION,
        launch_pack_path=str(launch_pack_path),
        run_plan_path=str(run_plan_path) if run_plan_path is not None else None,
        markdown_report_path=(
            str(markdown_report_path) if markdown_report_path is not None else None
        ),
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit launch pack path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit launch pack JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit launch pack root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append("launch pack missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("launch pack has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != LAUNCH_PACK_SCHEMA_VERSION:
        errors.append(
            f"launch pack schema_version must be {LAUNCH_PACK_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("launch pack ok must be true for generated launch packs")
    for field in (
        "run_plan_path",
        "run_plan_schema_version",
        "run_plan_execution_state",
        "run_plan_run_items_fingerprint_sha256",
        "run_plan_operator_setup_fingerprint_sha256",
        "run_plan_acceptance_contract_fingerprint_sha256",
        "run_plan_post_run_verification_command_specs_fingerprint_sha256",
        "launch_items_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"launch pack {field} must be a non-empty string")
    for field in (
        "run_plan_sha256",
        "run_plan_run_items_fingerprint_sha256",
        "run_plan_operator_setup_fingerprint_sha256",
        "run_plan_acceptance_contract_fingerprint_sha256",
        "run_plan_post_run_verification_command_specs_fingerprint_sha256",
        "launch_items_fingerprint_sha256",
        "launch_acceptance_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "launch_command_specs_fingerprint_sha256",
        "post_launch_verification_command_specs_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"launch pack {field} must be a SHA-256 hex string")
    for field in ("launch_item_count", "unsupported_run_item_count"):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"launch pack {field} must be a non-negative integer")
    for field in (
        "unsupported_requirement_ids",
        "post_launch_verification_commands",
        "errors",
        "error_codes",
    ):
        if not _is_string_list(payload.get(field)):
            errors.append(f"launch pack {field} must be a string list")
    errors.extend(
        _post_launch_verification_command_errors(
            payload.get("post_launch_verification_commands")
        )
    )
    errors.extend(
        _post_launch_verification_command_spec_errors(
            payload.get("post_launch_verification_command_specs"),
            payload.get("post_launch_verification_commands"),
        )
    )
    errors.extend(_post_launch_verification_fingerprint_errors(payload))
    item_errors, items = _launch_item_errors(payload.get("launch_items"))
    errors.extend(item_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    errors.extend(_launch_acceptance_fingerprint_errors(payload, items))
    errors.extend(_launch_setup_fingerprint_errors(payload, items))
    errors.extend(_launch_command_specs_fingerprint_errors(payload, items))
    if not item_errors:
        errors.extend(_summary_errors(payload, items))
    return errors


def _post_launch_verification_command_errors(value: Any) -> list[str]:
    if not _is_string_list(value):
        return []
    errors: list[str] = []
    errors.extend(_post_launch_shell_control_errors(value))
    errors.extend(_post_launch_command_order_errors(value))
    errors.extend(_post_launch_pack_regeneration_errors(value))
    preflight_commands = [
        command
        for command in value
        if "--preflight-dir <preflight-dir>" in command
    ]
    if len(preflight_commands) < 5:
        errors.append(
            "launch pack post_launch_verification_commands must validate "
            "downloaded preflight artifacts with <preflight-dir> placeholder"
        )
    for command in value:
        for match in re.finditer(r"--preflight-dir\s+(\S+)", command):
            if match.group(1) != "<preflight-dir>":
                errors.append(
                    "launch pack post_launch_verification_commands must not "
                    "bind preflight-dir to a concrete local path"
                )
                return errors
    return errors


def _post_launch_verification_command_spec_errors(
    value: Any,
    commands: Any,
) -> list[str]:
    if not isinstance(value, list):
        return ["launch pack post_launch_verification_command_specs must be a list"]
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
            "launch pack post_launch_verification_command_specs must contain "
            "only canonical verification steps"
        )
    rendered_commands: list[str] = []
    for index, spec in enumerate(value):
        if not isinstance(spec, dict):
            errors.append("launch pack post_launch_verification_command_specs entries must be objects")
            continue
        if set(spec) != VERIFICATION_COMMAND_SPEC_FIELDS:
            errors.append(
                "launch pack post_launch_verification_command_specs fields must match contract"
            )
        step_id = spec.get("step_id")
        expected_step = expected_steps[index] if index < len(expected_steps) else ""
        if step_id != expected_step:
            errors.append(
                "launch pack post_launch_verification_command_specs must keep canonical "
                f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
            )
        if spec.get("working_directory") != ".":
            errors.append(
                "launch pack post_launch_verification_command_specs working_directory "
                "must be repo root"
            )
        if spec.get("uses_shell") is not False:
            errors.append(
                "launch pack post_launch_verification_command_specs uses_shell must be false"
            )
        argv = spec.get("argv")
        if not _is_string_list(argv) or not argv:
            errors.append(
                "launch pack post_launch_verification_command_specs argv must be "
                "a non-empty string list"
            )
            continue
        rendered_commands.append(" ".join(argv))
        errors.extend(_post_launch_argv_shell_control_errors(argv))
        if _argv_preflight_dir_value(argv) not in {"", "<preflight-dir>"}:
            errors.append(
                "launch pack post_launch_verification_command_specs must not "
                "bind preflight-dir to a concrete local path"
            )
    if _is_string_list(commands) and rendered_commands and commands != rendered_commands:
        errors.append(
            "launch pack post_launch_verification_commands must match "
            "post_launch_verification_command_specs argv"
        )
    return errors


def _post_launch_verification_fingerprint_errors(payload: dict[str, Any]) -> list[str]:
    specs = payload.get("post_launch_verification_command_specs")
    fingerprint = payload.get(
        "post_launch_verification_command_specs_fingerprint_sha256"
    )
    if not isinstance(specs, list) or not isinstance(fingerprint, str):
        return []
    if fingerprint != _verification_command_specs_fingerprint(
        specs,
        run_plan_post_run_verification_command_specs_fingerprint_sha256=str(
            payload.get(
                "run_plan_post_run_verification_command_specs_fingerprint_sha256"
            )
            or ""
        ),
    ):
        return [
            "launch pack post_launch_verification_command_specs_fingerprint_sha256 "
            "must match post_launch_verification_command_specs"
        ]
    return []


def _post_launch_argv_shell_control_errors(argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "launch pack post_launch_verification_command_specs argv must not "
                "contain shell control operator tokens"
            ]
    return []


def _argv_preflight_dir_value(argv: list[str]) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == "--preflight-dir":
            return argv[index + 1]
    return ""


def _post_launch_shell_control_errors(commands: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for command in commands:
        if any(token in command for token in shell_control_tokens):
            return [
                "launch pack post_launch_verification_commands must not contain "
                "shell control operator tokens"
            ]
    return []


def _post_launch_command_order_errors(commands: list[str]) -> list[str]:
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
            "launch pack post_launch_verification_commands must contain "
            f"{ONLY_CANONICAL_VERIFICATION_COMMANDS_TOKEN}"
        ]
    for command, tokens in zip(commands, expected_token_groups, strict=True):
        if not _command_has_tokens(command, tokens):
            return [
                "launch pack post_launch_verification_commands must keep canonical "
                f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
            ]
    if len({tuple(command.split()) for command in commands}) != len(commands):
        return [
            "launch pack post_launch_verification_commands must keep canonical "
            f"{CANONICAL_VERIFICATION_ORDER_TOKEN}"
        ]
    return []


def _post_launch_pack_regeneration_errors(commands: list[str]) -> list[str]:
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
            "launch pack post_launch_verification_commands must regenerate launch pack"
        )
    if not validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate launch pack"
        )
    if not setup_generate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must regenerate setup state"
        )
    if not setup_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate setup state"
        )
    if not setup_handle_plan_generate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must regenerate setup handle plan"
        )
    if not setup_handle_plan_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate setup handle plan"
        )
    if not dispatch_gate_generate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must regenerate dispatch gate"
        )
    if not dispatch_gate_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate dispatch gate"
        )
    if not dispatch_gate_run_commands:
        errors.append(
            "launch pack post_launch_verification_commands must run dispatch gate runner"
        )
    if not dispatch_run_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate dispatch run"
        )
    if not dispatch_diagnostics_run_commands:
        errors.append(
            "launch pack post_launch_verification_commands must run dispatch diagnostics"
        )
    if not dispatch_diagnostics_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate dispatch diagnostics"
        )
    if not control_chain_validate_commands:
        errors.append(
            "launch pack post_launch_verification_commands must validate control chain"
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
            "launch pack post_launch_verification_commands must write "
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
            "launch pack post_launch_verification_commands must bind setup "
            "handle evidence to <runtime-evidence-bundle-report-json>"
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
            "launch pack post_launch_verification_commands must regenerate "
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must regenerate "
            "run plan Markdown into <run-plan-markdown>"
        )
    if run_plan_validate_commands and not any(
        _command_has_tokens(
            command,
            ["--markdown-report <run-plan-markdown>"],
        )
        for command in run_plan_validate_commands
    ):
        errors.append(
            "launch pack post_launch_verification_commands must validate "
            "run plan Markdown"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must regenerate "
            "launch pack from <run-plan-json> into <launch-pack-json>"
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
            "launch pack post_launch_verification_commands must regenerate "
            "launch pack Markdown from <run-plan-json> into <launch-pack-markdown>"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must regenerate "
            "setup state from <launch-pack-json> and repo source into <setup-state-json>"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must regenerate "
            "setup handle plan from setup-state/launch-pack sources"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must regenerate "
            "dispatch gate from launch-pack/setup-state sources"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must materialize "
            "dispatch gate runner report without bypassing pending setup"
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must materialize "
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
            "launch pack post_launch_verification_commands must validate "
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
            "launch pack post_launch_verification_commands must validate the "
            "full completion audit control chain"
        )
    return errors


def _command_has_tokens(command: str, tokens: list[str]) -> bool:
    return all(token in command for token in tokens)


def _launch_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["launch pack launch_items must be a list"], items
    for item in value:
        if not isinstance(item, dict):
            errors.append("launch pack launch_item entries must be objects")
            continue
        items.append(item)
        if set(item) != LAUNCH_ITEM_FIELDS:
            errors.append("launch pack launch_item fields must match contract")
        for field in (
            "requirement_id",
            "title",
            "current_status",
            "workflow",
            "probe",
            "expected_artifact",
            "expected_schema_version",
            "preflight_source_file",
        ):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"launch pack launch_item {field} must be a non-empty string")
        for field in (
            "preflight_status",
            "preflight_schema_version",
            "preflight_generated_at",
            "preflight_source_file_sha256",
            "preflight_source_validation_schema_version",
        ):
            if not isinstance(item.get(field), str):
                errors.append(f"launch pack launch_item {field} must be a string")
        for field in (
            "preflight_source_validation_ok",
            "preflight_raw_payload_included",
        ):
            if not isinstance(item.get(field), bool):
                errors.append(f"launch pack launch_item {field} must be a boolean")
        for field in (
            "artifact_tokens",
            "diagnostic_artifact_tokens",
            "preflight_source_validation_error_codes",
            "preflight_required_next",
            "required_operator_action_tokens",
            "required_github_inputs",
            "required_github_vars",
            "required_github_secrets",
            "conditional_github_secrets",
            "required_environment_variables",
            "acceptance_checks",
        ):
            if not _is_string_list(item.get(field)):
                errors.append(f"launch pack launch_item {field} must be a string list")
        errors.extend(_operator_action_errors(item.get("required_operator_actions")))
        errors.extend(_operator_requirement_errors(item))
        errors.extend(_setup_contract_errors(item))
        errors.extend(_setup_contract_binding_errors(item))
        errors.extend(_preflight_provenance_errors(item))
        errors.extend(_acceptance_check_errors(item))
        errors.extend(_command_errors(item.get("commands"), item))
        errors.extend(_command_spec_errors(item.get("command_specs"), item))
    return errors, items


def _preflight_provenance_errors(item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = item.get("preflight_status")
    sha256 = item.get("preflight_source_file_sha256")
    validation_ok = item.get("preflight_source_validation_ok")
    validation_errors = item.get("preflight_source_validation_error_codes")
    raw_payload_included = item.get("preflight_raw_payload_included")
    required_next = _string_list(item.get("preflight_required_next"))

    if isinstance(status, str) and status and status not in {"pass", "fail"}:
        errors.append("launch pack preflight provenance status must be pass or fail")
    if isinstance(sha256, str) and sha256 and not _is_fingerprint(sha256):
        errors.append(
            "launch pack preflight provenance source_file_sha256 must be a "
            "SHA-256 hex string"
        )
    if raw_payload_included is True:
        errors.append(
            "launch pack preflight provenance raw payload included must be false"
        )
    if (
        validation_ok is True
        and _is_string_list(validation_errors)
        and validation_errors
    ):
        errors.append(
            "launch pack preflight provenance source validation error codes must "
            "be empty when validation is ok"
        )
    if not required_next:
        return errors

    if status != "fail":
        errors.append(
            "launch pack preflight provenance status must be fail when setup is required"
        )
    for field in (
        "preflight_schema_version",
        "preflight_generated_at",
        "preflight_source_file",
        "preflight_source_file_sha256",
        "preflight_source_validation_schema_version",
    ):
        if not isinstance(item.get(field), str) or not item.get(field):
            errors.append(
                "launch pack preflight provenance "
                f"{field} must be non-empty when setup is required"
            )
    if not _is_fingerprint(sha256):
        errors.append(
            "launch pack preflight provenance source_file_sha256 must be a "
            "SHA-256 hex string when setup is required"
        )
    if validation_ok is not True:
        errors.append(
            "launch pack preflight provenance source validation must be ok "
            "when setup is required"
        )
    if validation_errors != []:
        errors.append(
            "launch pack preflight provenance source validation error codes must "
            "be empty when setup is required"
        )
    if raw_payload_included is not False:
        errors.append(
            "launch pack preflight provenance raw payload must be excluded "
            "when setup is required"
        )
    return errors


def _operator_requirement_errors(item: dict[str, Any]) -> list[str]:
    required_next = _string_list(item.get("preflight_required_next"))
    action_tokens = set(_string_list(item.get("required_operator_action_tokens")))
    missing = sorted(token for token in required_next if token not in action_tokens)
    errors = []
    if missing:
        errors.append(
            "launch pack required_operator_action_tokens must cover "
            "preflight_required_next: "
            + ", ".join(missing)
        )
    structured_tokens = [
        action.get("token")
        for action in item.get("required_operator_actions", [])
        if isinstance(action, dict)
    ]
    if _is_string_list(structured_tokens) and structured_tokens != _string_list(
        item.get("required_operator_action_tokens")
    ):
        errors.append(
            "launch pack required_operator_actions tokens must match "
            "required_operator_action_tokens"
        )
    return errors


def _setup_contract_errors(item: dict[str, Any]) -> list[str]:
    value = item.get("preflight_setup_contract")
    if not isinstance(value, dict):
        return ["launch pack preflight_setup_contract must be an object"]
    if value == {}:
        return []
    errors: list[str] = []
    if set(value) != SETUP_CONTRACT_FIELDS:
        errors.append("launch pack preflight_setup_contract fields must match contract")
    if value.get("version") != SETUP_CONTRACT_VERSION:
        errors.append("launch pack preflight_setup_contract.version must match contract")
    if value.get("requirement_id") != item.get("requirement_id"):
        errors.append(
            "launch pack preflight_setup_contract.requirement_id must match item"
        )
    if value.get("required_next") != item.get("preflight_required_next"):
        errors.append(
            "launch pack preflight_setup_contract.required_next must match preflight"
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
            errors.append(
                f"launch pack preflight_setup_contract.{field} must be a string list"
            )
        elif "" in field_value:
            errors.append(
                f"launch pack preflight_setup_contract.{field} must not include empty strings"
            )
        elif len(field_value) != len(set(field_value)):
            errors.append(
                f"launch pack preflight_setup_contract.{field} must not contain duplicates"
            )
    dispatch_ready = value.get("dispatch_ready")
    if not isinstance(dispatch_ready, bool):
        errors.append(
            "launch pack preflight_setup_contract.dispatch_ready must be a boolean"
        )
    elif dispatch_ready != (
        item.get("preflight_status") == "pass"
        and not item.get("preflight_required_next")
    ):
        errors.append(
            "launch pack preflight_setup_contract.dispatch_ready must match preflight status"
        )
    forbidden_tokens = {
        "TELEGRAM_BOT_TOKEN",
        "FACEBOOK_PAGE_ACCESS_TOKEN",
        "ZALO_OA_ACCESS_TOKEN",
        "WIII_ACCEPTANCE_BEARER_TOKEN",
        "WIII_LMS_TEST_COURSE_BEARER_TOKEN",
        "WIII_LMS_TEST_COURSE_APPLY_URL",
        "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
        "access_token",
        "api_key",
        "authorization",
    }
    rendered = json.dumps(value, sort_keys=True)
    if any(token in rendered for token in forbidden_tokens):
        errors.append(
            "launch pack preflight_setup_contract must not include raw credential names"
        )
    return errors


def _setup_contract_binding_errors(item: dict[str, Any]) -> list[str]:
    contract = item.get("preflight_setup_contract")
    bindings = item.get("preflight_setup_contract_bindings")
    if not isinstance(bindings, dict):
        return ["launch pack preflight_setup_contract_bindings must be an object"]
    if not isinstance(contract, dict) or contract == {}:
        if bindings != {}:
            return [
                "launch pack preflight_setup_contract_bindings must be empty when setup_contract is empty"
            ]
        return []
    errors: list[str] = []
    if set(bindings) != SETUP_BINDING_FIELDS:
        errors.append(
            "launch pack preflight_setup_contract_bindings fields must match contract"
        )
    operational_surface = _setup_binding_operational_surface(item)
    for field in SETUP_BINDING_FIELDS:
        expected_keys = set(_string_list(contract.get(field)))
        group = bindings.get(field)
        if not isinstance(group, dict):
            errors.append(
                f"launch pack preflight_setup_contract_bindings.{field} must be an object"
            )
            continue
        if set(group) != expected_keys:
            errors.append(
                f"launch pack preflight_setup_contract_bindings.{field} keys must match setup_contract"
            )
        for key, values in group.items():
            if not isinstance(key, str) or not key:
                errors.append(
                    f"launch pack preflight_setup_contract_bindings.{field} keys must be non-empty strings"
                )
            if not _is_string_list(values) or not values:
                errors.append(
                    f"launch pack preflight_setup_contract_bindings.{field}.{key} must be a non-empty string list"
                )
                continue
            if "" in values or len(values) != len(set(values)):
                errors.append(
                    f"launch pack preflight_setup_contract_bindings.{field}.{key} values must be unique non-empty strings"
                )
            for token in values:
                if any(char.isspace() for char in token) or "=" in token or "<" in token or ">" in token:
                    errors.append(
                        f"launch pack preflight_setup_contract_bindings.{field}.{key} values must be token handles"
                    )
                    continue
                if token not in operational_surface:
                    errors.append(
                        f"launch pack preflight_setup_contract_bindings.{field}.{key} value {token!r} must appear in launch surface"
                    )
    return errors


def _setup_binding_operational_surface(item: dict[str, Any]) -> str:
    surface = {
        "commands": item.get("commands"),
        "command_specs": item.get("command_specs"),
        "conditional_github_secrets": item.get("conditional_github_secrets"),
        "required_environment_variables": item.get("required_environment_variables"),
        "required_github_inputs": item.get("required_github_inputs"),
        "required_github_secrets": item.get("required_github_secrets"),
        "required_github_vars": item.get("required_github_vars"),
        "required_operator_action_tokens": item.get("required_operator_action_tokens"),
    }
    return json.dumps(surface, sort_keys=True)


def _operator_action_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["launch pack required_operator_actions must be a list"]
    errors: list[str] = []
    for action in value:
        if not isinstance(action, dict):
            errors.append("launch pack required_operator_action entries must be objects")
            continue
        if set(action) != OPERATOR_ACTION_FIELDS:
            errors.append("launch pack required_operator_action fields must match contract")
        for field in OPERATOR_ACTION_FIELDS:
            if not isinstance(action.get(field), str) or not action.get(field):
                errors.append(
                    f"launch pack required_operator_action {field} must be a non-empty string"
                )
    return errors


def _acceptance_check_errors(item: dict[str, Any]) -> list[str]:
    checks = item.get("acceptance_checks")
    if not _is_string_list(checks):
        return []
    rendered = "\n".join(checks)
    required_tokens = [
        "expected artifact",
        "schema_version",
        "validate_runtime_evidence_bundle.py",
        "regenerated scoped readiness report",
    ]
    return [
        f"launch pack acceptance_checks must include {token}"
        for token in required_tokens
        if token not in rendered
    ]


def _command_errors(value: Any, item: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return ["launch pack commands must be an object"]
    errors: list[str] = []
    if set(value) != COMMAND_FIELDS:
        errors.append("launch pack commands fields must match contract")
    for field in COMMAND_FIELDS:
        command = value.get(field)
        if not isinstance(command, str) or not command:
            errors.append(f"launch pack command {field} must be a non-empty string")
    errors.extend(_launch_command_shell_control_errors(value))
    requirement_id = item.get("requirement_id")
    artifact = item.get("expected_artifact")
    if isinstance(requirement_id, str):
        for field in ("validate_preflight", "validate_artifact"):
            if requirement_id not in str(value.get(field, "")):
                errors.append(
                    f"launch pack command {field} must include requirement_id"
                )
    if isinstance(artifact, str) and artifact not in str(value.get("local_live_probe", "")):
        errors.append("launch pack local_live_probe must write expected artifact")
    if isinstance(artifact, str) and artifact not in str(
        value.get("local_failure_from_preflight", "")
    ):
        errors.append(
            "launch pack local_failure_from_preflight must write expected artifact"
        )
    if "<" not in str(value.get("workflow_dispatch", "")):
        errors.append("launch pack workflow_dispatch must include placeholders")
    errors.extend(_command_contract_errors(value, item))
    return errors


def _launch_command_shell_control_errors(commands: dict[str, Any]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for field in COMMAND_FIELDS:
        command = commands.get(field)
        if isinstance(command, str) and any(
            token in command for token in shell_control_tokens
        ):
            return [
                "launch pack command templates must not contain shell control "
                f"operator tokens: {field}"
            ]
    return []


def _command_contract_errors(commands: dict[str, Any], item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    workflow_dispatch = str(commands.get("workflow_dispatch", ""))
    local_preflight = str(commands.get("local_preflight", ""))
    validate_preflight = str(commands.get("validate_preflight", ""))
    local_failure_from_preflight = str(
        commands.get("local_failure_from_preflight", "")
    )
    local_live_probe = str(commands.get("local_live_probe", ""))
    validate_artifact = str(commands.get("validate_artifact", ""))
    download_artifact = str(commands.get("download_artifact", ""))
    download_preflight_artifact = str(commands.get("download_preflight_artifact", ""))

    workflow_file = _workflow_file_name(str(item.get("workflow", "")))
    if workflow_file and f"gh workflow run {workflow_file}" not in workflow_dispatch:
        errors.append("launch pack workflow_dispatch must run the registered workflow")
    for input_name in _string_list(item.get("required_github_inputs")):
        if not _command_has_form_input(workflow_dispatch, input_name):
            errors.append(
                "launch pack workflow_dispatch must bind required GitHub input "
                f"{input_name}"
            )

    if "--preflight-only" not in local_preflight:
        errors.append("launch pack local_preflight must run probe in preflight-only mode")
    preflight_output = _command_out_argument(local_preflight)
    if preflight_output:
        expected_preflight_path = f"maritime-ai-service/{preflight_output}"
        if expected_preflight_path not in validate_preflight:
            errors.append(
                "launch pack validate_preflight must validate local_preflight output"
            )
    else:
        errors.append("launch pack local_preflight must write an explicit --out file")
    if "validate_runtime_evidence_preflight.py" not in validate_preflight:
        errors.append("launch pack validate_preflight must run preflight validator")
    if "--failure-from-preflight" not in local_failure_from_preflight:
        errors.append(
            "launch pack local_failure_from_preflight must run failure-from-preflight"
        )
    if "--failure-preflight-json" not in local_failure_from_preflight:
        errors.append(
            "launch pack local_failure_from_preflight must bind failure preflight JSON"
        )
    if preflight_output and preflight_output not in local_failure_from_preflight:
        errors.append(
            "launch pack local_failure_from_preflight must use local_preflight output"
        )

    artifact = item.get("expected_artifact")
    live_output = _command_out_argument(local_live_probe)
    failure_output = _command_out_argument(local_failure_from_preflight)
    if isinstance(artifact, str) and artifact:
        if live_output != artifact:
            errors.append("launch pack local_live_probe must write expected artifact")
        if failure_output != artifact:
            errors.append(
                "launch pack local_failure_from_preflight must write expected artifact"
            )
        expected_artifact_path = f"maritime-ai-service/{artifact}"
        if expected_artifact_path not in validate_artifact:
            errors.append(
                "launch pack validate_artifact must validate local_live_probe output"
            )
    if "validate_runtime_evidence_artifact.py" not in validate_artifact:
        errors.append("launch pack validate_artifact must run artifact validator")

    artifact_tokens = _string_list(item.get("artifact_tokens"))
    if artifact_tokens and not all(
        _download_command_binds_token(download_artifact, token)
        for token in artifact_tokens
    ):
        errors.append("launch pack download_artifact must use artifact token")
    diagnostic_tokens = _string_list(item.get("diagnostic_artifact_tokens"))
    if diagnostic_tokens and not all(
        _download_command_binds_token(download_preflight_artifact, token)
        for token in diagnostic_tokens
    ):
        errors.append(
            "launch pack download_preflight_artifact must use diagnostic artifact token"
        )
    if "-D <downloaded-artifact-dir>" not in download_artifact:
        errors.append("launch pack download_artifact must use downloaded artifact dir")
    if "-D <preflight-dir>" not in download_preflight_artifact:
        errors.append("launch pack download_preflight_artifact must use preflight dir")
    return errors


def _command_spec_errors(value: Any, item: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict):
        return ["launch pack command_specs must be an object"]
    errors: list[str] = []
    if set(value) != COMMAND_FIELDS:
        errors.append("launch pack command_specs fields must match commands contract")
    specs: dict[str, dict[str, Any]] = {}
    for field in COMMAND_FIELDS:
        spec = value.get(field)
        if not isinstance(spec, dict):
            errors.append(f"launch pack command_spec {field} must be an object")
            continue
        specs[field] = spec
        if set(spec) != COMMAND_SPEC_FIELDS:
            errors.append(
                f"launch pack command_spec {field} fields must match contract"
            )
        working_directory = spec.get("working_directory")
        argv = spec.get("argv")
        if not _safe_working_directory(working_directory):
            errors.append(
                f"launch pack command_spec {field} working_directory must be repo-relative"
            )
        if spec.get("uses_shell") is not False:
            errors.append(f"launch pack command_spec {field} uses_shell must be false")
        if not _is_string_list(argv) or not argv:
            errors.append(f"launch pack command_spec {field} argv must be a non-empty string list")
            continue
        errors.extend(_argv_shell_control_errors(field, argv))
    if errors:
        return errors
    errors.extend(_command_template_spec_parity_errors(value, item.get("commands")))
    errors.extend(_command_spec_contract_errors(specs, item))
    return errors


def _command_template_spec_parity_errors(
    specs: dict[str, Any],
    commands: Any,
) -> list[str]:
    if not isinstance(commands, dict):
        return []
    errors: list[str] = []
    for field in COMMAND_FIELDS:
        spec = specs.get(field)
        if not isinstance(spec, dict):
            continue
        argv = spec.get("argv")
        command = commands.get(field)
        if _is_string_list(argv) and isinstance(command, str):
            rendered = _render_argv(argv)
            if command != rendered:
                errors.append(
                    "launch pack command templates must match command_specs argv: "
                    f"{field}"
                )
    return errors


def _safe_working_directory(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../"):
        return False
    if "/../" in normalized or normalized.endswith("/.."):
        return False
    return normalized in {".", "maritime-ai-service"}


def _argv_shell_control_errors(field: str, argv: list[str]) -> list[str]:
    shell_control_tokens = (";", "&&", "||", "|", "`", "$(")
    for arg in argv:
        if any(token in arg for token in shell_control_tokens):
            return [
                "launch pack command_specs argv must not contain shell control "
                f"operator tokens: {field}"
            ]
    return []


def _render_argv(argv: list[str]) -> str:
    return " ".join(argv)


def _command_spec_contract_errors(
    specs: dict[str, dict[str, Any]],
    item: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    workflow_file = _workflow_file_name(str(item.get("workflow", "")))
    workflow_argv = _argv(specs, "workflow_dispatch")
    if workflow_argv[:3] != ["gh", "workflow", "run"]:
        errors.append("launch pack command_spec workflow_dispatch must run gh workflow")
    if workflow_file and _argv_value(workflow_argv, 3) != workflow_file:
        errors.append("launch pack command_spec workflow_dispatch must run registered workflow")
    for input_name in _string_list(item.get("required_github_inputs")):
        if not _argv_has_form_input(workflow_argv, input_name):
            errors.append(
                "launch pack command_spec workflow_dispatch must bind required "
                f"GitHub input {input_name}"
            )

    local_preflight = _argv(specs, "local_preflight")
    local_failure_from_preflight = _argv(specs, "local_failure_from_preflight")
    local_live_probe = _argv(specs, "local_live_probe")
    if specs["local_preflight"].get("working_directory") != "maritime-ai-service":
        errors.append("launch pack command_spec local_preflight cwd must be maritime-ai-service")
    if specs["local_failure_from_preflight"].get("working_directory") != "maritime-ai-service":
        errors.append(
            "launch pack command_spec local_failure_from_preflight cwd must be maritime-ai-service"
        )
    if specs["local_live_probe"].get("working_directory") != "maritime-ai-service":
        errors.append("launch pack command_spec local_live_probe cwd must be maritime-ai-service")
    if specs["validate_preflight"].get("working_directory") != ".":
        errors.append("launch pack command_spec validate_preflight cwd must be repo root")
    if specs["validate_artifact"].get("working_directory") != ".":
        errors.append("launch pack command_spec validate_artifact cwd must be repo root")
    if "--preflight-only" not in local_preflight:
        errors.append("launch pack command_spec local_preflight must run preflight-only")
    preflight_output = _argv_out_argument(local_preflight)
    if not preflight_output:
        errors.append("launch pack command_spec local_preflight must write explicit --out")
    expected_preflight_path = (
        f"maritime-ai-service/{preflight_output}" if preflight_output else ""
    )
    validate_preflight = _argv(specs, "validate_preflight")
    if expected_preflight_path and expected_preflight_path not in validate_preflight:
        errors.append("launch pack command_spec validate_preflight must validate preflight output")
    if "tools/wiii_self_harness/validate_runtime_evidence_preflight.py" not in validate_preflight:
        errors.append("launch pack command_spec validate_preflight must run preflight validator")
    if "--failure-from-preflight" not in local_failure_from_preflight:
        errors.append(
            "launch pack command_spec local_failure_from_preflight must run failure-from-preflight"
        )
    if "--failure-preflight-json" not in local_failure_from_preflight:
        errors.append(
            "launch pack command_spec local_failure_from_preflight must bind failure preflight JSON"
        )
    if preflight_output and preflight_output not in local_failure_from_preflight:
        errors.append(
            "launch pack command_spec local_failure_from_preflight must use preflight output"
        )

    artifact = item.get("expected_artifact")
    live_output = _argv_out_argument(local_live_probe)
    failure_output = _argv_out_argument(local_failure_from_preflight)
    if isinstance(artifact, str) and artifact:
        if live_output != artifact:
            errors.append("launch pack command_spec local_live_probe must write expected artifact")
        if failure_output != artifact:
            errors.append(
                "launch pack command_spec local_failure_from_preflight must write expected artifact"
            )
        expected_artifact_path = f"maritime-ai-service/{artifact}"
        validate_artifact = _argv(specs, "validate_artifact")
        if expected_artifact_path not in validate_artifact:
            errors.append("launch pack command_spec validate_artifact must validate artifact output")
    if "tools/wiii_self_harness/validate_runtime_evidence_artifact.py" not in _argv(specs, "validate_artifact"):
        errors.append("launch pack command_spec validate_artifact must run artifact validator")
    requirement_id = item.get("requirement_id")
    if isinstance(requirement_id, str):
        for field in ("validate_preflight", "validate_artifact"):
            if requirement_id not in _argv(specs, field):
                errors.append(
                    f"launch pack command_spec {field} must include requirement_id"
                )

    artifact_tokens = _string_list(item.get("artifact_tokens"))
    download_artifact = _argv(specs, "download_artifact")
    if artifact_tokens and not all(
        _download_argv_binds_token(download_artifact, token)
        for token in artifact_tokens
    ):
        errors.append("launch pack command_spec download_artifact must use artifact token")
    diagnostic_tokens = _string_list(item.get("diagnostic_artifact_tokens"))
    download_preflight = _argv(specs, "download_preflight_artifact")
    if diagnostic_tokens and not all(
        _download_argv_binds_token(download_preflight, token)
        for token in diagnostic_tokens
    ):
        errors.append(
            "launch pack command_spec download_preflight_artifact must use diagnostic artifact token"
        )
    if "-D" not in download_artifact or "<downloaded-artifact-dir>" not in download_artifact:
        errors.append("launch pack command_spec download_artifact must use downloaded artifact dir")
    if "-D" not in download_preflight or "<preflight-dir>" not in download_preflight:
        errors.append("launch pack command_spec download_preflight_artifact must use preflight dir")
    return errors


def _argv(specs: dict[str, dict[str, Any]], field: str) -> list[str]:
    argv = specs[field].get("argv")
    return argv if _is_string_list(argv) else []


def _argv_value(argv: list[str], index: int) -> str:
    return argv[index] if index < len(argv) else ""


def _argv_has_form_input(argv: list[str], input_name: str) -> bool:
    expected_prefix = f"{input_name}="
    for index, arg in enumerate(argv[:-1]):
        if arg == "-f" and argv[index + 1].startswith(expected_prefix):
            return True
    return False


def _argv_out_argument(argv: list[str]) -> str:
    for index, arg in enumerate(argv[:-1]):
        if arg == "--out":
            return argv[index + 1].strip("\"'")
    return ""


def _download_argv_binds_token(argv: list[str], token: str) -> bool:
    rendered_token = token.replace("${{ github.run_id }}", "<run-id>")
    for index, arg in enumerate(argv[:-1]):
        if arg == "-n" and argv[index + 1] == rendered_token:
            return True
    return False


def _workflow_file_name(workflow: str) -> str:
    return workflow.replace("\\", "/").split("/")[-1]


def _command_has_form_input(command: str, input_name: str) -> bool:
    return re.search(rf"(?:^|\s)-f\s+{re.escape(input_name)}=", command) is not None


def _command_out_argument(command: str) -> str:
    match = re.search(r"(?:^|\s)--out\s+([^\s]+)", command)
    if not match:
        return ""
    return match.group(1).strip("\"'")


def _download_command_binds_token(command: str, token: str) -> bool:
    rendered_token = token.replace("${{ github.run_id }}", "<run-id>")
    return re.search(rf"(?:^|\s)-n\s+{re.escape(rendered_token)}(?:\s|$)", command) is not None


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["launch pack privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("launch pack privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"launch pack privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return []
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes) and error_codes != expected_codes:
        result.append("launch pack error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("launch pack error_code_counts must match errors")
    return result


def _summary_errors(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("launch_item_count") != len(items):
        errors.append("launch pack launch_item_count must match launch_items")
    if payload.get("launch_items_fingerprint_sha256") != _launch_items_fingerprint(
        items,
        run_plan_schema_version=str(payload.get("run_plan_schema_version") or ""),
        run_plan_run_items_fingerprint_sha256=str(
            payload.get("run_plan_run_items_fingerprint_sha256") or ""
        ),
        run_plan_operator_setup_fingerprint_sha256=str(
            payload.get("run_plan_operator_setup_fingerprint_sha256") or ""
        ),
        run_plan_acceptance_contract_fingerprint_sha256=str(
            payload.get("run_plan_acceptance_contract_fingerprint_sha256") or ""
        ),
    ):
        errors.append(
            "launch pack launch_items_fingerprint_sha256 must match launch_items"
        )
    requirement_ids = [item.get("requirement_id") for item in items]
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append("launch pack launch_items must not duplicate requirement_id")
    unsupported_ids = payload.get("unsupported_requirement_ids")
    if _is_string_list(unsupported_ids) and unsupported_ids != sorted(set(unsupported_ids)):
        errors.append(
            "launch pack unsupported_requirement_ids must be sorted and unique"
        )
    return errors


def _launch_command_specs_fingerprint_errors(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    fingerprint = payload.get("launch_command_specs_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        return []
    if fingerprint != _launch_command_specs_fingerprint(
        items,
        run_plan_run_items_fingerprint_sha256=str(
            payload.get("run_plan_run_items_fingerprint_sha256") or ""
        ),
    ):
        return [
            "launch pack launch_command_specs_fingerprint_sha256 must match "
            "launch_items command_specs"
        ]
    return []


def _launch_setup_fingerprint_errors(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    fingerprint = payload.get("launch_setup_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        return []
    if fingerprint != _launch_setup_fingerprint(
        items,
        run_plan_operator_setup_fingerprint_sha256=str(
            payload.get("run_plan_operator_setup_fingerprint_sha256") or ""
        ),
    ):
        return ["launch pack launch_setup_fingerprint_sha256 must match setup fields"]
    return []


def _launch_acceptance_fingerprint_errors(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
) -> list[str]:
    fingerprint = payload.get("launch_acceptance_fingerprint_sha256")
    if not isinstance(fingerprint, str):
        return []
    if fingerprint != _launch_acceptance_fingerprint(
        items,
        run_plan_acceptance_contract_fingerprint_sha256=str(
            payload.get("run_plan_acceptance_contract_fingerprint_sha256") or ""
        ),
    ):
        return [
            "launch pack launch_acceptance_fingerprint_sha256 must match "
            "acceptance fields"
        ]
    return []


def _run_plan_source_errors(
    payload: dict[str, Any],
    *,
    run_plan_path: Path,
) -> list[str]:
    errors: list[str] = []
    run_plan_validation = run_plan_validator.validate_run_plan(run_plan_path)
    if not run_plan_validation.ok:
        return [
            "completion audit launch pack run plan source failed validation: "
            + "; ".join(run_plan_validation.errors)
        ]
    expected_pack = generate_completion_audit_launch_pack(run_plan_path)
    expected = expected_pack.to_dict()
    if payload.get("run_plan_sha256") != _sha256_file(run_plan_path):
        errors.append("launch pack run_plan_sha256 must match run plan")
    for field in (
        "run_plan_schema_version",
        "run_plan_execution_state",
        "run_plan_run_items_fingerprint_sha256",
        "run_plan_operator_setup_fingerprint_sha256",
        "run_plan_acceptance_contract_fingerprint_sha256",
        "run_plan_post_run_verification_command_specs_fingerprint_sha256",
        "launch_item_count",
        "launch_items_fingerprint_sha256",
        "launch_acceptance_fingerprint_sha256",
        "launch_setup_fingerprint_sha256",
        "launch_command_specs_fingerprint_sha256",
        "unsupported_run_item_count",
        "unsupported_requirement_ids",
        "post_launch_verification_commands",
        "post_launch_verification_command_specs_fingerprint_sha256",
        "post_launch_verification_command_specs",
    ):
        if payload.get(field) != expected.get(field):
            errors.append(f"launch pack {field} must match run plan")
    if payload.get("launch_items") != expected.get("launch_items"):
        errors.append("launch pack launch_items must match run plan")
    return errors


def _markdown_report_errors(
    markdown_report_path: Path,
    *,
    run_plan_path: Path | None,
) -> list[str]:
    if run_plan_path is None:
        return ["launch pack markdown report validation requires --run-plan"]
    if not markdown_report_path.is_file() or markdown_report_path.is_symlink():
        return [
            "completion audit launch pack markdown report path must be a regular file"
        ]
    run_plan_validation = run_plan_validator.validate_run_plan(run_plan_path)
    if not run_plan_validation.ok:
        return [
            "completion audit launch pack markdown report run plan source "
            "failed validation: "
            + "; ".join(run_plan_validation.errors)
        ]
    expected_markdown = format_markdown(
        generate_completion_audit_launch_pack(run_plan_path)
    )
    actual_markdown = markdown_report_path.read_text(encoding="utf-8")
    if actual_markdown.rstrip("\n") != expected_markdown.rstrip("\n"):
        return ["launch pack markdown report must match generated launch pack"]
    return []


def _repo_source_errors(payload: dict[str, Any], repo_root: Path) -> list[str]:
    if repo_root.is_symlink():
        return [f"completion audit launch pack repo_root must not be a symlink: {repo_root}"]
    if not repo_root.exists():
        return [f"completion audit launch pack repo_root does not exist: {repo_root}"]
    if not repo_root.is_dir():
        return [f"completion audit launch pack repo_root must be a directory: {repo_root}"]
    launch_items = payload.get("launch_items")
    if not isinstance(launch_items, list):
        return []
    errors: list[str] = []
    for item in launch_items:
        if not isinstance(item, dict):
            continue
        errors.extend(_single_item_repo_source_errors(item, repo_root))
    return errors


def _single_item_repo_source_errors(
    item: dict[str, Any],
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    requirement_id = item.get("requirement_id")
    workflow = item.get("workflow")
    if isinstance(workflow, str) and workflow:
        workflow_path = repo_root / workflow
        if not workflow_path.is_file() or workflow_path.is_symlink():
            errors.append(f"launch pack workflow source must be a regular file: {workflow}")
        else:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            for token in _workflow_source_tokens(item):
                if token not in workflow_text:
                    errors.append(
                        "launch pack workflow source missing token "
                        f"{token!r} for {requirement_id}"
                    )
    probe = item.get("probe")
    if isinstance(probe, str) and probe:
        probe_path = repo_root / probe
        if not probe_path.is_file() or probe_path.is_symlink():
            errors.append(f"launch pack probe source must be a regular file: {probe}")
        else:
            commands = item.get("commands")
            command_text = json.dumps(commands, sort_keys=True) if isinstance(commands, dict) else ""
            probe_name = probe.replace("\\", "/").split("/")[-1]
            if probe_name not in command_text:
                errors.append(
                    f"launch pack command templates must reference probe {probe_name}"
                )
    return errors


def _workflow_source_tokens(item: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for field in (
        "required_github_inputs",
        "required_github_vars",
        "required_github_secrets",
        "conditional_github_secrets",
        "artifact_tokens",
        "diagnostic_artifact_tokens",
    ):
        value = item.get(field)
        if isinstance(value, list):
            tokens.extend(token for token in value if isinstance(token, str))
    artifact = item.get("expected_artifact")
    if isinstance(artifact, str) and artifact:
        tokens.append(artifact)
    normalized: list[str] = []
    for token in tokens:
        if "${{ github.run_id }}" in token:
            token = token.replace("${{ github.run_id }}", "")
        token = token.strip("-_")
        if token:
            normalized.append(token)
    return sorted(set(normalized))


def _launch_items_fingerprint(
    items: list[dict[str, Any]],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_schema_version: str = "",
    run_plan_run_items_fingerprint_sha256: str = "",
    run_plan_operator_setup_fingerprint_sha256: str = "",
    run_plan_acceptance_contract_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_schema_version": run_plan_schema_version,
        "run_plan_run_items_fingerprint_sha256": run_plan_run_items_fingerprint_sha256,
        "run_plan_operator_setup_fingerprint_sha256": (
            run_plan_operator_setup_fingerprint_sha256
        ),
        "run_plan_acceptance_contract_fingerprint_sha256": (
            run_plan_acceptance_contract_fingerprint_sha256
        ),
        "launch_items": items,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _launch_command_specs_fingerprint(
    items: list[dict[str, Any]],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_run_items_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_run_items_fingerprint_sha256": run_plan_run_items_fingerprint_sha256,
        "launch_command_specs": [
            {
                "command_specs": item.get("command_specs"),
                "requirement_id": item.get("requirement_id"),
            }
            for item in items
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _launch_setup_fingerprint(
    items: list[dict[str, Any]],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_operator_setup_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_operator_setup_fingerprint_sha256": (
            run_plan_operator_setup_fingerprint_sha256
        ),
        "launch_setup": [
            {
                "conditional_github_secrets": item.get("conditional_github_secrets"),
                "diagnostic_artifact_tokens": item.get("diagnostic_artifact_tokens"),
                "preflight": {
                    "required_next": item.get("preflight_required_next"),
                    "schema_version": item.get("preflight_schema_version"),
                    "setup_contract": item.get("preflight_setup_contract"),
                    "setup_contract_bindings": item.get(
                        "preflight_setup_contract_bindings"
                    ),
                    "source_file": item.get("preflight_source_file"),
                    "status": item.get("preflight_status"),
                },
                "required_environment_variables": item.get(
                    "required_environment_variables"
                ),
                "required_github_inputs": item.get("required_github_inputs"),
                "required_github_secrets": item.get("required_github_secrets"),
                "required_github_vars": item.get("required_github_vars"),
                "required_operator_action_tokens": item.get(
                    "required_operator_action_tokens"
                ),
                "required_operator_actions": item.get("required_operator_actions"),
                "requirement_id": item.get("requirement_id"),
            }
            for item in items
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _launch_acceptance_fingerprint(
    items: list[dict[str, Any]],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_acceptance_contract_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_acceptance_contract_fingerprint_sha256": (
            run_plan_acceptance_contract_fingerprint_sha256
        ),
        "launch_acceptance": [
            {
                "acceptance_checks": item.get("acceptance_checks"),
                "expected_artifact": item.get("expected_artifact"),
                "expected_schema_version": item.get("expected_schema_version"),
                "requirement_id": item.get("requirement_id"),
            }
            for item in items
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verification_command_specs_fingerprint(
    specs: list[Any],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_post_run_verification_command_specs_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_post_run_verification_command_specs_fingerprint_sha256": (
            run_plan_post_run_verification_command_specs_fingerprint_sha256
        ),
        "post_launch_verification_command_specs": specs,
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit launch pack path must be a regular file":
        return "completion_audit_launch_pack_path_invalid"
    if error.startswith("completion audit launch pack JSON is invalid"):
        return "completion_audit_launch_pack_json_invalid"
    if error == "completion audit launch pack root must be an object":
        return "completion_audit_launch_pack_root_invalid"
    if error.startswith("completion audit launch pack run plan source failed validation"):
        return "completion_audit_launch_pack_run_plan_invalid"
    if "markdown report" in error:
        return "completion_audit_launch_pack_markdown_invalid"
    if "repo_root" in error or "workflow source" in error or "probe source" in error:
        return "completion_audit_launch_pack_repo_source_invalid"
    if "preflight_setup_contract_bindings" in error:
        return "completion_audit_launch_pack_preflight_provenance_invalid"
    if "preflight_setup_contract" in error:
        return "completion_audit_launch_pack_preflight_provenance_invalid"
    if "preflight provenance" in error:
        return "completion_audit_launch_pack_preflight_provenance_invalid"
    if (
        "post_launch_verification_commands" in error
        and (
            "regenerate launch pack" in error
            or "validate launch pack" in error
            or "<launch-pack-json>" in error
            or "readiness Markdown" in error
            or "readiness self-harness bundle source" in error
            or "run plan against readiness" in error
        )
    ):
        return "completion_audit_launch_pack_post_launch_verification_invalid"
    if "canonical verification" in error:
        return "completion_audit_launch_pack_post_launch_verification_order_invalid"
    if (
        "shell control operator" in error
        and "post_launch_verification_command_specs" in error
    ):
        return "completion_audit_launch_pack_post_launch_verification_command_unsafe"
    if (
        "shell control operator" in error
        and ("command_specs" in error or "command templates" in error)
    ):
        return "completion_audit_launch_pack_command_unsafe"
    if "shell control operator" in error:
        return "completion_audit_launch_pack_post_launch_verification_command_unsafe"
    if error.startswith("launch pack missing required field"):
        return "completion_audit_launch_pack_missing_required_fields"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_launch_pack_fingerprint_invalid"
    if (
        "post_launch_verification_command_specs" in error
        or "post_launch_verification_commands must match" in error
    ):
        return "completion_audit_launch_pack_post_launch_verification_spec_invalid"
    if error.startswith("launch pack has unsupported field"):
        return "completion_audit_launch_pack_unsupported_fields"
    if error.startswith("launch pack schema_version must be"):
        return "completion_audit_launch_pack_schema_mismatch"
    if "run plan" in error and "must match" in error:
        return "completion_audit_launch_pack_run_plan_mismatch"
    if "privacy" in error:
        return "completion_audit_launch_pack_privacy_invalid"
    if (
        "command" in error
        or "commands" in error
        or error.startswith("launch pack workflow_dispatch")
        or error.startswith("launch pack local_")
        or error.startswith("launch pack validate_")
        or error.startswith("launch pack download_")
    ):
        return "completion_audit_launch_pack_command_invalid"
    if "acceptance" in error:
        return "completion_audit_launch_pack_acceptance_invalid"
    if "required_operator_action" in error:
        return "completion_audit_launch_pack_operator_requirements_invalid"
    if "launch_item" in error or "launch_items" in error:
        return "completion_audit_launch_pack_item_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_launch_pack_error_summary_invalid"
    if "string list" in error:
        return "completion_audit_launch_pack_string_list_invalid"
    if "non-negative integer" in error:
        return "completion_audit_launch_pack_count_invalid"
    return "completion_audit_launch_pack_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit launch pack artifact.",
    )
    parser.add_argument("launch_pack_path", type=Path)
    parser.add_argument(
        "--run-plan",
        type=Path,
        default=None,
        help="Optional run plan that the launch pack must match.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional repository root used to verify workflow/probe source tokens.",
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=None,
        help=(
            "Optional Markdown launch pack report that must match the supplied "
            "run plan."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_launch_pack(
        args.launch_pack_path,
        run_plan_path=args.run_plan,
        repo_root=args.repo_root,
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
        print("Wiii Completion Audit Launch Pack Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Launch Pack Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
