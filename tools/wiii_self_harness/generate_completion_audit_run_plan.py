#!/usr/bin/env python3
"""Generate an operator run plan from a completion-audit readiness report."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_readiness as readiness_validator  # noqa: E402


RUN_PLAN_SCHEMA_VERSION = "wiii.completion_audit_run_plan.v1"
RUN_PLAN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit run plan output path must not be a directory"
)
RUN_PLAN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit run plan output path must not be a symlink"
)
RUN_PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit run plan output path parent must not be a symlink"
)
RUN_PLAN_READINESS_VALIDATION_ERROR = (
    "completion audit readiness report failed validation"
)


@dataclass(frozen=True)
class OperatorAction:
    token: str
    category: str
    instruction: str


@dataclass(frozen=True)
class WorkflowExecution:
    workflow: str
    workflow_dispatch_inputs: list[str]
    schedule_env_flags: list[str]
    live_probe_env_flags: list[str]
    live_probe_guard_tokens: list[str]
    artifact_tokens: list[str]
    diagnostic_artifact_tokens: list[str]


@dataclass(frozen=True)
class RunPlanPreflight:
    status: str
    schema_version: str
    generated_at: str
    required_next: list[str]
    source_file: str
    source_file_sha256: str
    source_validation_schema_version: str
    source_validation_ok: bool
    source_validation_error_codes: list[str]
    raw_payload_included: bool
    setup_contract: dict[str, Any]


@dataclass(frozen=True)
class EvidenceAcceptance:
    expected_artifact: str
    expected_schema_version: str
    accepted_when: list[str]


@dataclass(frozen=True)
class VerificationCommandSpec:
    step_id: str
    working_directory: str
    argv: list[str]
    uses_shell: bool


@dataclass(frozen=True)
class RunPlanItem:
    requirement_id: str
    title: str
    layer: str
    current_status: str
    artifact: str
    evidence_schema_version: str
    probe: str
    error_codes: list[str]
    workflow_execution: WorkflowExecution
    preflight: RunPlanPreflight
    blocked_by_live_setup: bool
    required_operator_actions: list[OperatorAction]
    credential_or_external_setup_tokens: list[str]
    acceptance: EvidenceAcceptance


@dataclass(frozen=True)
class CompletionAuditRunPlan:
    schema_version: str
    ok: bool
    readiness_report_path: str
    readiness_report_sha256: str
    readiness_schema_version: str
    readiness_scoped_completion_audit_ready: bool
    readiness_scoped_next_actions_fingerprint_sha256: str
    readiness_preflight_summary_count: int
    excluded_requirement_ids: list[str]
    scoped_counts: dict[str, int]
    execution_state: str
    run_item_count: int
    blocked_by_live_setup_count: int
    acceptance_contract_fingerprint_sha256: str
    operator_setup_fingerprint_sha256: str
    run_items_fingerprint_sha256: str
    run_items: list[RunPlanItem]
    post_run_verification_commands: list[str]
    post_run_verification_command_specs_fingerprint_sha256: str
    post_run_verification_command_specs: list[VerificationCommandSpec]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_run_plan(
    readiness_report_path: Path,
    *,
    preflight_dir: Path | None = None,
    preflight_dirs: list[Path] | None = None,
) -> CompletionAuditRunPlan:
    readiness_validation = readiness_validator.validate_readiness_report(
        readiness_report_path,
        preflight_dir=preflight_dir,
        preflight_dirs=preflight_dirs,
    )
    if not readiness_validation.ok:
        raise ValueError(
            RUN_PLAN_READINESS_VALIDATION_ERROR
            + ": "
            + "; ".join(readiness_validation.errors)
        )
    payload = load_strict_json_file(readiness_report_path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit readiness report root must be an object")

    preflight_by_requirement = {
        summary["requirement_id"]: summary
        for summary in payload.get("preflight_summaries", [])
        if isinstance(summary, dict)
        and isinstance(summary.get("requirement_id"), str)
    }
    run_items = [
        _run_plan_item(action, preflight_by_requirement)
        for action in payload.get("scoped_next_actions", [])
        if isinstance(action, dict)
    ]
    blocked_count = sum(1 for item in run_items if item.blocked_by_live_setup)
    scoped_ready = bool(payload.get("scoped_completion_audit_ready"))
    errors: list[str] = []
    post_run_specs = _post_run_verification_command_specs(readiness_report_path)
    readiness_schema_version = str(payload.get("schema_version") or "")
    readiness_actions_fingerprint = str(
        payload.get("scoped_next_actions_fingerprint_sha256") or ""
    )
    return CompletionAuditRunPlan(
        schema_version=RUN_PLAN_SCHEMA_VERSION,
        ok=True,
        readiness_report_path=str(readiness_report_path),
        readiness_report_sha256=_sha256_file(readiness_report_path),
        readiness_schema_version=readiness_schema_version,
        readiness_scoped_completion_audit_ready=scoped_ready,
        readiness_scoped_next_actions_fingerprint_sha256=readiness_actions_fingerprint,
        readiness_preflight_summary_count=int(payload.get("preflight_summary_count")),
        excluded_requirement_ids=list(payload.get("excluded_requirement_ids") or []),
        scoped_counts={
            "requirements": int(payload.get("scoped_requirement_count")),
            "passed": int(payload.get("scoped_passed_count")),
            "missing": int(payload.get("scoped_missing_count")),
            "failed": int(payload.get("scoped_failed_count")),
        },
        execution_state=_execution_state(
            scoped_ready=scoped_ready,
            run_items=run_items,
            blocked_by_live_setup_count=blocked_count,
        ),
        run_item_count=len(run_items),
        blocked_by_live_setup_count=blocked_count,
        acceptance_contract_fingerprint_sha256=_acceptance_contract_fingerprint(
            run_items
        ),
        operator_setup_fingerprint_sha256=_operator_setup_fingerprint(run_items),
        run_items_fingerprint_sha256=_run_items_fingerprint(
            run_items,
            readiness_schema_version=readiness_schema_version,
            readiness_scoped_next_actions_fingerprint_sha256=readiness_actions_fingerprint,
        ),
        run_items=run_items,
        post_run_verification_commands=_render_verification_commands(post_run_specs),
        post_run_verification_command_specs_fingerprint_sha256=(
            _verification_command_specs_fingerprint(post_run_specs)
        ),
        post_run_verification_command_specs=post_run_specs,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def format_markdown(plan: CompletionAuditRunPlan) -> str:
    status = "SCOPED READY" if plan.readiness_scoped_completion_audit_ready else "NOT READY"
    lines = [
        "# Wiii Completion Audit Run Plan",
        "",
        f"- Schema version: `{plan.schema_version}`",
        f"- Plan status: `{status}`",
        f"- Execution state: `{plan.execution_state}`",
        f"- Readiness report: `{plan.readiness_report_path}`",
        f"- Readiness report SHA-256: `{plan.readiness_report_sha256}`",
        "- Scoped counts: "
        f"`passed={plan.scoped_counts['passed']}, "
        f"missing={plan.scoped_counts['missing']}, "
        f"failed={plan.scoped_counts['failed']}, "
        f"requirements={plan.scoped_counts['requirements']}`",
        f"- Excluded requirement IDs: `{', '.join(plan.excluded_requirement_ids) or '-'}`",
        f"- Run items: `{plan.run_item_count}`",
        f"- Blocked by live setup: `{plan.blocked_by_live_setup_count}`",
        f"- Run items fingerprint SHA-256: `{plan.run_items_fingerprint_sha256}`",
        "",
        "## Run Items",
        "",
        "| Requirement | Current | Workflow | Live Gates | Required Setup | Artifact |",
        "|---|---|---|---|---|---|",
    ]
    for item in plan.run_items:
        gates = [
            *item.workflow_execution.workflow_dispatch_inputs,
            *item.workflow_execution.schedule_env_flags,
            *item.workflow_execution.live_probe_env_flags,
            *item.workflow_execution.live_probe_guard_tokens,
        ]
        setup = [action.token for action in item.required_operator_actions]
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item.requirement_id),
                    _cell(item.current_status),
                    _cell(item.workflow_execution.workflow),
                    _cell(", ".join(gates) or "-"),
                    _cell(", ".join(setup) or "-"),
                    _cell(item.artifact),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Operator Actions", ""])
    for item in plan.run_items:
        lines.append(f"### {item.requirement_id}")
        if not item.required_operator_actions:
            lines.append("- No additional live setup actions were reported by preflight.")
        for action in item.required_operator_actions:
            lines.append(
                f"- `{action.token}` ({action.category}): {action.instruction}"
            )
        lines.append("")
    lines.extend(["## Verification", ""])
    lines.extend(f"- `{command}`" for command in plan.post_run_verification_commands)
    lines.extend(["", "## Structured Verification Specs", ""])
    for spec in plan.post_run_verification_command_specs:
        argv = " ".join(spec.argv)
        uses_shell = "true" if spec.uses_shell else "false"
        lines.append(
            f"- `{spec.step_id}` cwd=`{spec.working_directory}` "
            f"uses_shell=`{uses_shell}` argv=`{argv}`"
        )
    return "\n".join(lines).rstrip()


def _run_plan_item(
    action: dict[str, Any],
    preflight_by_requirement: dict[str, dict[str, Any]],
) -> RunPlanItem:
    requirement_id = _string(action.get("requirement_id"))
    preflight_summary = preflight_by_requirement.get(requirement_id, {})
    required_next = _string_list(action.get("preflight_required_next"))
    operator_actions = [
        _operator_action(token, action)
        for token in required_next
    ]
    workflow_execution = WorkflowExecution(
        workflow=_string(action.get("workflow")),
        workflow_dispatch_inputs=[
            token
            for token in _string_list(action.get("dispatch_or_schedule_gate_tokens"))
            if not token.startswith("WIII_")
        ],
        schedule_env_flags=[
            token
            for token in _string_list(action.get("dispatch_or_schedule_gate_tokens"))
            if token.startswith("WIII_")
        ],
        live_probe_env_flags=_string_list(action.get("live_env_flags")),
        live_probe_guard_tokens=_string_list(action.get("live_guard_tokens")),
        artifact_tokens=_string_list(action.get("artifact_tokens")),
        diagnostic_artifact_tokens=_diagnostic_artifact_tokens(
            action.get("diagnostic_uploads")
        ),
    )
    preflight = RunPlanPreflight(
        status=_string(action.get("preflight_status")),
        schema_version=_string(action.get("preflight_schema_version")),
        generated_at=_string(action.get("preflight_generated_at")),
        required_next=required_next,
        source_file=_string(action.get("preflight_source_file")),
        source_file_sha256=_string(preflight_summary.get("source_file_sha256")),
        source_validation_schema_version=_string(
            preflight_summary.get("source_validation_schema_version")
        ),
        source_validation_ok=bool(preflight_summary.get("source_validation_ok")),
        source_validation_error_codes=_string_list(
            preflight_summary.get("source_validation_error_codes")
        ),
        raw_payload_included=bool(preflight_summary.get("raw_payload_included")),
        setup_contract=_dict_field(preflight_summary.get("setup_contract")),
    )
    return RunPlanItem(
        requirement_id=requirement_id,
        title=_string(action.get("title")),
        layer=_string(action.get("layer")),
        current_status=_string(action.get("status")),
        artifact=_string(action.get("artifact")),
        evidence_schema_version=_string(action.get("schema_version")),
        probe=_string(action.get("probe")),
        error_codes=_string_list(action.get("error_codes")),
        workflow_execution=workflow_execution,
        preflight=preflight,
        blocked_by_live_setup=_blocked_by_live_setup(preflight),
        required_operator_actions=operator_actions,
        credential_or_external_setup_tokens=[
            item.token
            for item in operator_actions
            if item.category
            in {
                "approved_recipient",
                "configuration",
                "secret_or_credential",
                "service_endpoint",
            }
        ],
        acceptance=EvidenceAcceptance(
            expected_artifact=_string(action.get("artifact")),
            expected_schema_version=_string(action.get("schema_version")),
            accepted_when=[
                "the expected artifact exists in the downloaded runtime evidence bundle",
                "the artifact schema_version matches expected_schema_version",
                "validate_runtime_evidence_bundle.py passes the registered row checks",
                "the regenerated scoped readiness report no longer lists this requirement as missing or failed",
            ],
        ),
    )


def _operator_action(token: str, action: dict[str, Any]) -> OperatorAction:
    guard_tokens = ", ".join(_string_list(action.get("live_guard_tokens"))) or "the live guard token"
    env_flags = ", ".join(_string_list(action.get("live_env_flags"))) or "the live evidence env flag"
    mapping = {
        "pass_allow_send": (
            "operator_live_ack",
            f"Run the proactive probe with {guard_tokens}.",
        ),
        "set_live_proactive_channel_probe_env_flag": (
            "environment_flag",
            f"Set {env_flags}=1 in the evidence run environment.",
        ),
        "provide_recipient_id": (
            "approved_recipient",
            "Provide an approved live recipient identifier through the workflow or probe environment.",
        ),
        "enable_selected_channel": (
            "configuration",
            "Enable the selected proactive outbound channel in the runtime configuration.",
        ),
        "configure_selected_channel_credential": (
            "secret_or_credential",
            "Configure the selected channel credential through the approved secret store or environment.",
        ),
        "pass_allow_live": (
            "operator_live_ack",
            f"Run the acceptance probe with {guard_tokens}.",
        ),
        "set_live_composio_acceptance_flag": (
            "environment_flag",
            f"Set {env_flags}=1 in the evidence run environment.",
        ),
        "configure_backend_url": (
            "service_endpoint",
            "Configure the staging or live Wiii backend URL for the acceptance run.",
        ),
        "configure_acceptance_bearer_token": (
            "secret_or_credential",
            "Provide the acceptance bearer token through the approved secret store or environment.",
        ),
        "pass_allow_write": (
            "operator_live_ack",
            f"Run the LMS replay probe with {guard_tokens}.",
        ),
        "pass_allow_external_lms_write": (
            "operator_live_ack",
            "Acknowledge the external LMS test-course write guard before dispatch.",
        ),
        "set_live_lms_test_course_replay_flag": (
            "environment_flag",
            f"Set {env_flags}=1 in the evidence run environment.",
        ),
        "configure_external_lms_apply_url": (
            "service_endpoint",
            "Configure the approved external LMS test-course apply endpoint.",
        ),
        "configure_external_lms_apply_token": (
            "secret_or_credential",
            "Provide the external LMS test-course apply token through the approved secret store or environment.",
        ),
    }
    category, instruction = mapping.get(
        token,
        ("operator_input", "Satisfy this preflight requirement before live evidence dispatch."),
    )
    return OperatorAction(
        token=token,
        category=category,
        instruction=instruction,
    )


def _blocked_by_live_setup(preflight: RunPlanPreflight) -> bool:
    return (
        preflight.status != "pass"
        or bool(preflight.required_next)
        or not preflight.source_validation_ok
        or preflight.raw_payload_included
    )


def _execution_state(
    *,
    scoped_ready: bool,
    run_items: list[RunPlanItem],
    blocked_by_live_setup_count: int,
) -> str:
    if scoped_ready:
        return "scoped_ready"
    if not run_items:
        return "no_scoped_blockers"
    if blocked_by_live_setup_count:
        return "blocked_on_live_setup"
    return "ready_for_live_dispatch"


def _post_run_verification_commands(
    readiness_report_path: Path,
    *,
    preflight_dir: Path | None,
) -> list[str]:
    del preflight_dir
    return _render_verification_commands(
        _post_run_verification_command_specs(readiness_report_path)
    )


def _post_run_verification_command_specs(
    readiness_report_path: Path,
) -> list[VerificationCommandSpec]:
    readiness_path = str(readiness_report_path)
    readiness_markdown_path = "<readiness-markdown>"
    return [
        _verification_spec(
            "validate_runtime_evidence_bundle",
            [
                "python",
                "tools/wiii_self_harness/validate_runtime_evidence_bundle.py",
                "<downloaded-artifact-dir>",
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
                "--require-completion-audit-link",
                "--format",
                "json",
                "--out",
                "<runtime-evidence-bundle-report-json>",
            ],
        ),
        _verification_spec(
            "report_completion_audit_readiness",
            [
                "python",
                "tools/wiii_self_harness/report_completion_audit_readiness.py",
                "<downloaded-artifact-dir>",
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
                "--exclude-requirement-id",
                "lms-test-course-replay",
                "--preflight-dir",
                "<preflight-dir>",
                "--format",
                "json",
                "--out",
                readiness_path,
            ],
        ),
        _verification_spec(
            "report_completion_audit_readiness_markdown",
            [
                "python",
                "tools/wiii_self_harness/report_completion_audit_readiness.py",
                "<downloaded-artifact-dir>",
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
                "--exclude-requirement-id",
                "lms-test-course-replay",
                "--preflight-dir",
                "<preflight-dir>",
                "--format",
                "markdown",
                "--out",
                readiness_markdown_path,
            ],
        ),
        _verification_spec(
            "validate_completion_audit_readiness",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_readiness.py",
                readiness_path,
                "--preflight-dir",
                "<preflight-dir>",
                "--markdown-report",
                readiness_markdown_path,
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_run_plan",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_run_plan.py",
                readiness_path,
                "--preflight-dir",
                "<preflight-dir>",
                "--format",
                "json",
                "--out",
                "<run-plan-json>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_run_plan_markdown",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_run_plan.py",
                readiness_path,
                "--preflight-dir",
                "<preflight-dir>",
                "--format",
                "markdown",
                "--out",
                "<run-plan-markdown>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_run_plan",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_run_plan.py",
                "<run-plan-json>",
                "--readiness-report",
                readiness_path,
                "--readiness-markdown-report",
                readiness_markdown_path,
                "--readiness-preflight-dir",
                "<preflight-dir>",
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
                "--markdown-report",
                "<run-plan-markdown>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_launch_pack",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_launch_pack.py",
                "<run-plan-json>",
                "--format",
                "json",
                "--out",
                "<launch-pack-json>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_launch_pack_markdown",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_launch_pack.py",
                "<run-plan-json>",
                "--format",
                "markdown",
                "--out",
                "<launch-pack-markdown>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_launch_pack",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_launch_pack.py",
                "<launch-pack-json>",
                "--run-plan",
                "<run-plan-json>",
                "--repo-root",
                ".",
                "--markdown-report",
                "<launch-pack-markdown>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_setup_state",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_setup_state.py",
                "<launch-pack-json>",
                "--repo-root",
                ".",
                "--out",
                "<setup-state-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_setup_state",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_setup_state.py",
                "<setup-state-json>",
                "--launch-pack",
                "<launch-pack-json>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_setup_handle_plan",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_setup_handle_plan.py",
                "<setup-state-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--out",
                "<setup-handle-plan-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_setup_handle_plan",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_setup_handle_plan.py",
                "<setup-handle-plan-json>",
                "--setup-state",
                "<setup-state-json>",
                "--launch-pack",
                "<launch-pack-json>",
            ],
        ),
        _verification_spec(
            "probe_completion_audit_setup_handle_evidence",
            [
                "python",
                "tools/wiii_self_harness/probe_completion_audit_setup_handle_evidence.py",
                "<setup-handle-plan-json>",
                "--runtime-evidence-dir",
                "<runtime-evidence-dir>",
                "--runtime-evidence-bundle-report",
                "<runtime-evidence-bundle-report-json>",
                "--allow-env-read",
                "--allow-network",
                "--out",
                "<setup-handle-evidence-json>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_setup_attestation_from_handles",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_setup_attestation_from_handles.py",
                "<setup-handle-plan-json>",
                "<setup-handle-evidence-json>",
                "--setup-state",
                "<setup-state-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--out",
                "<setup-attestation-json>",
            ],
        ),
        _verification_spec(
            "apply_completion_audit_setup_attestation",
            [
                "python",
                "tools/wiii_self_harness/apply_completion_audit_setup_attestation.py",
                "<setup-state-json>",
                "<setup-attestation-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--out",
                "<setup-state-attested-json>",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_dispatch_gate_attested",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_dispatch_gate.py",
                "<launch-pack-json>",
                "<setup-state-attested-json>",
                "--out",
                "<dispatch-gate-attested-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_dispatch_gate_attested",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_dispatch_gate.py",
                "<dispatch-gate-attested-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-attested-json>",
            ],
        ),
        _verification_spec(
            "run_completion_audit_dispatch_gate_attested",
            [
                "python",
                "tools/wiii_self_harness/run_completion_audit_dispatch_gate.py",
                "<dispatch-gate-attested-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-attested-json>",
                "--repo-root",
                ".",
                "--allow-pending-report",
                "--out",
                "<dispatch-run-attested-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_dispatch_run_attested",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_dispatch_run.py",
                "<dispatch-run-attested-json>",
                "--dispatch-gate",
                "<dispatch-gate-attested-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-attested-json>",
                "--repo-root",
                ".",
            ],
        ),
        _verification_spec(
            "generate_completion_audit_dispatch_gate",
            [
                "python",
                "tools/wiii_self_harness/generate_completion_audit_dispatch_gate.py",
                "<launch-pack-json>",
                "<setup-state-json>",
                "--out",
                "<dispatch-gate-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_dispatch_gate",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_dispatch_gate.py",
                "<dispatch-gate-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-json>",
            ],
        ),
        _verification_spec(
            "run_completion_audit_dispatch_gate",
            [
                "python",
                "tools/wiii_self_harness/run_completion_audit_dispatch_gate.py",
                "<dispatch-gate-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-json>",
                "--repo-root",
                ".",
                "--allow-pending-report",
                "--out",
                "<dispatch-run-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_dispatch_run",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_dispatch_run.py",
                "<dispatch-run-json>",
                "--dispatch-gate",
                "<dispatch-gate-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-json>",
                "--repo-root",
                ".",
            ],
        ),
        _verification_spec(
            "run_completion_audit_dispatch_diagnostics",
            [
                "python",
                "tools/wiii_self_harness/run_completion_audit_dispatch_diagnostics.py",
                "<dispatch-run-json>",
                "--dispatch-gate",
                "<dispatch-gate-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-json>",
                "--repo-root",
                ".",
                "--out",
                "<dispatch-diagnostics-json>",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_dispatch_diagnostics",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_dispatch_diagnostics.py",
                "<dispatch-diagnostics-json>",
                "--dispatch-run",
                "<dispatch-run-json>",
                "--dispatch-gate",
                "<dispatch-gate-json>",
                "--launch-pack",
                "<launch-pack-json>",
                "--setup-state",
                "<setup-state-json>",
                "--repo-root",
                ".",
            ],
        ),
        _verification_spec(
            "validate_completion_audit_control_chain",
            [
                "python",
                "tools/wiii_self_harness/validate_completion_audit_control_chain.py",
                "--readiness-report",
                readiness_path,
                "--readiness-markdown-report",
                readiness_markdown_path,
                "--readiness-preflight-dir",
                "<preflight-dir>",
                "--self-harness-report-bundle",
                "<downloaded-self-harness-reports-dir>",
                "--run-plan",
                "<run-plan-json>",
                "--run-plan-markdown",
                "<run-plan-markdown>",
                "--launch-pack",
                "<launch-pack-json>",
                "--launch-pack-markdown",
                "<launch-pack-markdown>",
                "--setup-state",
                "<setup-state-json>",
                "--setup-handle-plan",
                "<setup-handle-plan-json>",
                "--dispatch-gate",
                "<dispatch-gate-json>",
                "--dispatch-run",
                "<dispatch-run-json>",
                "--repo-root",
                ".",
            ],
        ),
    ]


def _verification_spec(step_id: str, argv: list[str]) -> VerificationCommandSpec:
    return VerificationCommandSpec(
        step_id=step_id,
        working_directory=".",
        argv=argv,
        uses_shell=False,
    )


def _render_verification_commands(specs: list[VerificationCommandSpec]) -> list[str]:
    return [" ".join(spec.argv) for spec in specs]


def _verification_command_specs_fingerprint(
    specs: list[VerificationCommandSpec],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "post_run_verification_command_specs": [asdict(spec) for spec in specs],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(RUN_PLAN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RUN_PLAN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(RUN_PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a privacy-safe operator run plan from a validated "
            "completion-audit readiness report."
        ),
    )
    parser.add_argument("readiness_report", type=Path)
    parser.add_argument(
        "--preflight-dir",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional raw or embedded preflight source directory used to validate "
            "readiness source parity. May be supplied more than once."
        ),
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        plan = generate_completion_audit_run_plan(
            args.readiness_report,
            preflight_dirs=args.preflight_dir,
        )
    except Exception as exc:  # noqa: BLE001
        if args.format == "json":
            print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        else:
            print(f"Wiii Completion Audit Run Plan: FAIL\n- {exc}", file=sys.stderr)
        return 1

    rendered = (
        json.dumps(plan.to_dict(), indent=2, sort_keys=True)
        if args.format == "json"
        else format_markdown(plan)
    )
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": RUN_PLAN_SCHEMA_VERSION,
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
    if error.startswith(RUN_PLAN_READINESS_VALIDATION_ERROR):
        return "completion_audit_run_plan_readiness_invalid"
    if error == RUN_PLAN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_run_plan_output_path_directory"
    if error == RUN_PLAN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_run_plan_output_path_symlink"
    if error == RUN_PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_run_plan_output_path_parent_symlink"
    return "completion_audit_run_plan_generation_failed"


def _run_items_fingerprint(
    items: list[RunPlanItem],
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
        "run_items": [asdict(item) for item in items],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operator_setup_fingerprint(
    items: list[RunPlanItem],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "operator_setup": [
            {
                "blocked_by_live_setup": item.blocked_by_live_setup,
                "credential_or_external_setup_tokens": item.credential_or_external_setup_tokens,
                "preflight": {
                    "required_next": item.preflight.required_next,
                    "schema_version": item.preflight.schema_version,
                    "setup_contract": item.preflight.setup_contract,
                    "source_file": item.preflight.source_file,
                    "status": item.preflight.status,
                },
                "required_operator_actions": [
                    asdict(action) for action in item.required_operator_actions
                ],
                "requirement_id": item.requirement_id,
                "workflow_execution": asdict(item.workflow_execution),
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


def _acceptance_contract_fingerprint(
    items: list[RunPlanItem],
    *,
    schema_version: str = RUN_PLAN_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "acceptance_contract": [
            {
                "acceptance": asdict(item.acceptance),
                "requirement_id": item.requirement_id,
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


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dict_field(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _diagnostic_artifact_tokens(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tokens: list[str] = []
    for item in value:
        if isinstance(item, dict):
            tokens.extend(_string_list(item.get("artifact_tokens")))
    return tokens


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


if __name__ == "__main__":
    raise SystemExit(main())
