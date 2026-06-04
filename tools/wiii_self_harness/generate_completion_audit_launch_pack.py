#!/usr/bin/env python3
"""Generate an executable launch pack from a completion-audit run plan."""

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
import validate_completion_audit_run_plan as run_plan_validator  # noqa: E402


LAUNCH_PACK_SCHEMA_VERSION = "wiii.completion_audit_launch_pack.v1"
LAUNCH_PACK_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit launch pack output path must not be a directory"
)
LAUNCH_PACK_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit launch pack output path must not be a symlink"
)
LAUNCH_PACK_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit launch pack output path parent must not be a symlink"
)
LAUNCH_PACK_RUN_PLAN_VALIDATION_ERROR = (
    "completion audit run plan failed validation"
)
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"


@dataclass(frozen=True)
class LaunchCommands:
    workflow_dispatch: str
    local_preflight: str
    validate_preflight: str
    local_failure_from_preflight: str
    local_live_probe: str
    validate_artifact: str
    download_artifact: str
    download_preflight_artifact: str


@dataclass(frozen=True)
class LaunchCommandSpec:
    working_directory: str
    argv: list[str]
    uses_shell: bool


@dataclass(frozen=True)
class LaunchCommandSpecs:
    workflow_dispatch: LaunchCommandSpec
    local_preflight: LaunchCommandSpec
    validate_preflight: LaunchCommandSpec
    local_failure_from_preflight: LaunchCommandSpec
    local_live_probe: LaunchCommandSpec
    validate_artifact: LaunchCommandSpec
    download_artifact: LaunchCommandSpec
    download_preflight_artifact: LaunchCommandSpec


@dataclass(frozen=True)
class LaunchVerificationCommandSpec:
    step_id: str
    working_directory: str
    argv: list[str]
    uses_shell: bool


@dataclass(frozen=True)
class LaunchOperatorAction:
    token: str
    category: str
    instruction: str


@dataclass(frozen=True)
class LaunchItem:
    requirement_id: str
    title: str
    current_status: str
    workflow: str
    probe: str
    expected_artifact: str
    expected_schema_version: str
    artifact_tokens: list[str]
    diagnostic_artifact_tokens: list[str]
    preflight_source_file: str
    preflight_status: str
    preflight_schema_version: str
    preflight_generated_at: str
    preflight_source_file_sha256: str
    preflight_source_validation_schema_version: str
    preflight_source_validation_ok: bool
    preflight_source_validation_error_codes: list[str]
    preflight_raw_payload_included: bool
    preflight_required_next: list[str]
    preflight_setup_contract: dict[str, Any]
    preflight_setup_contract_bindings: dict[str, dict[str, list[str]]]
    required_operator_action_tokens: list[str]
    required_operator_actions: list[LaunchOperatorAction]
    required_github_inputs: list[str]
    required_github_vars: list[str]
    required_github_secrets: list[str]
    conditional_github_secrets: list[str]
    required_environment_variables: list[str]
    commands: LaunchCommands
    command_specs: LaunchCommandSpecs
    acceptance_checks: list[str]


@dataclass(frozen=True)
class CompletionAuditLaunchPack:
    schema_version: str
    ok: bool
    run_plan_path: str
    run_plan_sha256: str
    run_plan_schema_version: str
    run_plan_execution_state: str
    run_plan_run_items_fingerprint_sha256: str
    run_plan_operator_setup_fingerprint_sha256: str
    run_plan_acceptance_contract_fingerprint_sha256: str
    run_plan_post_run_verification_command_specs_fingerprint_sha256: str
    launch_item_count: int
    launch_items_fingerprint_sha256: str
    launch_acceptance_fingerprint_sha256: str
    launch_setup_fingerprint_sha256: str
    launch_command_specs_fingerprint_sha256: str
    launch_items: list[LaunchItem]
    unsupported_run_item_count: int
    unsupported_requirement_ids: list[str]
    post_launch_verification_commands: list[str]
    post_launch_verification_command_specs_fingerprint_sha256: str
    post_launch_verification_command_specs: list[LaunchVerificationCommandSpec]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_launch_pack(
    run_plan_path: Path,
    *,
    readiness_report_path: Path | None = None,
) -> CompletionAuditLaunchPack:
    validation = run_plan_validator.validate_run_plan(
        run_plan_path,
        readiness_report_path=readiness_report_path,
    )
    if not validation.ok:
        raise ValueError(
            LAUNCH_PACK_RUN_PLAN_VALIDATION_ERROR
            + ": "
            + "; ".join(validation.errors)
        )
    payload = load_strict_json_file(run_plan_path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit run plan root must be an object")

    launch_items: list[LaunchItem] = []
    unsupported_ids: list[str] = []
    for item in payload.get("run_items", []):
        if not isinstance(item, dict):
            continue
        requirement_id = _string(item.get("requirement_id"))
        contract_builder = LAUNCH_CONTRACT_BUILDERS.get(requirement_id)
        if contract_builder is None:
            unsupported_ids.append(requirement_id)
            continue
        launch_items.append(contract_builder(item))
    post_launch_specs = _verification_command_specs(
        payload.get("post_run_verification_command_specs")
    )
    run_plan_schema_version = _string(payload.get("schema_version"))
    run_plan_run_items_fingerprint = _string(
        payload.get("run_items_fingerprint_sha256")
    )
    run_plan_operator_setup_fingerprint = _string(
        payload.get("operator_setup_fingerprint_sha256")
    )
    run_plan_acceptance_fingerprint = _string(
        payload.get("acceptance_contract_fingerprint_sha256")
    )
    run_plan_verification_specs_fingerprint = _string(
        payload.get("post_run_verification_command_specs_fingerprint_sha256")
    )

    return CompletionAuditLaunchPack(
        schema_version=LAUNCH_PACK_SCHEMA_VERSION,
        ok=True,
        run_plan_path=str(run_plan_path),
        run_plan_sha256=_sha256_file(run_plan_path),
        run_plan_schema_version=run_plan_schema_version,
        run_plan_execution_state=_string(payload.get("execution_state")),
        run_plan_run_items_fingerprint_sha256=run_plan_run_items_fingerprint,
        run_plan_operator_setup_fingerprint_sha256=(
            run_plan_operator_setup_fingerprint
        ),
        run_plan_acceptance_contract_fingerprint_sha256=(
            run_plan_acceptance_fingerprint
        ),
        run_plan_post_run_verification_command_specs_fingerprint_sha256=_string(
            run_plan_verification_specs_fingerprint
        ),
        launch_item_count=len(launch_items),
        launch_items_fingerprint_sha256=_launch_items_fingerprint(
            launch_items,
            run_plan_schema_version=run_plan_schema_version,
            run_plan_run_items_fingerprint_sha256=run_plan_run_items_fingerprint,
            run_plan_operator_setup_fingerprint_sha256=(
                run_plan_operator_setup_fingerprint
            ),
            run_plan_acceptance_contract_fingerprint_sha256=(
                run_plan_acceptance_fingerprint
            ),
        ),
        launch_acceptance_fingerprint_sha256=_launch_acceptance_fingerprint(
            launch_items,
            run_plan_acceptance_contract_fingerprint_sha256=(
                run_plan_acceptance_fingerprint
            ),
        ),
        launch_setup_fingerprint_sha256=_launch_setup_fingerprint(
            launch_items,
            run_plan_operator_setup_fingerprint_sha256=(
                run_plan_operator_setup_fingerprint
            ),
        ),
        launch_command_specs_fingerprint_sha256=_launch_command_specs_fingerprint(
            launch_items,
            run_plan_run_items_fingerprint_sha256=run_plan_run_items_fingerprint,
        ),
        launch_items=launch_items,
        unsupported_run_item_count=len(unsupported_ids),
        unsupported_requirement_ids=sorted(unsupported_ids),
        post_launch_verification_commands=_string_list(
            payload.get("post_run_verification_commands")
        ),
        post_launch_verification_command_specs_fingerprint_sha256=(
            _verification_command_specs_fingerprint(
                post_launch_specs,
                run_plan_post_run_verification_command_specs_fingerprint_sha256=(
                    run_plan_verification_specs_fingerprint
                ),
            )
        ),
        post_launch_verification_command_specs=post_launch_specs,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=[],
    )


def format_markdown(pack: CompletionAuditLaunchPack) -> str:
    lines = [
        "# Wiii Completion Audit Launch Pack",
        "",
        f"- Schema version: `{pack.schema_version}`",
        f"- Run plan: `{pack.run_plan_path}`",
        f"- Run plan SHA-256: `{pack.run_plan_sha256}`",
        f"- Run plan state: `{pack.run_plan_execution_state}`",
        "- Run plan run-items fingerprint SHA-256: "
        f"`{pack.run_plan_run_items_fingerprint_sha256}`",
        "- Run plan operator setup fingerprint SHA-256: "
        f"`{pack.run_plan_operator_setup_fingerprint_sha256}`",
        "- Run plan acceptance fingerprint SHA-256: "
        f"`{pack.run_plan_acceptance_contract_fingerprint_sha256}`",
        "- Run plan post-run verification specs fingerprint SHA-256: "
        f"`{pack.run_plan_post_run_verification_command_specs_fingerprint_sha256}`",
        f"- Launch items: `{pack.launch_item_count}`",
        f"- Unsupported run items: `{pack.unsupported_run_item_count}`",
        f"- Launch items fingerprint SHA-256: `{pack.launch_items_fingerprint_sha256}`",
        "",
        "## Launch Items",
        "",
        "| Requirement | Workflow Dispatch | Required Secrets | Artifact |",
        "|---|---|---|---|",
    ]
    for item in pack.launch_items:
        secrets = [*item.required_github_secrets, *item.conditional_github_secrets]
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item.requirement_id),
                    _cell(item.commands.workflow_dispatch),
                    _cell(", ".join(secrets) or "-"),
                    _cell(item.expected_artifact),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Setup Requirements", ""])
    for item in pack.launch_items:
        lines.extend(
            [
                f"### {item.requirement_id}",
                "",
                f"- Preflight status: `{item.preflight_status or '-'}`",
                f"- Preflight schema: `{item.preflight_schema_version or '-'}`",
                f"- Preflight generated at: `{item.preflight_generated_at or '-'}`",
                f"- Preflight source: `{item.preflight_source_file}`",
                (
                    "- Preflight source SHA-256: "
                    f"`{item.preflight_source_file_sha256 or '-'}`"
                ),
                (
                    "- Preflight source validation schema: "
                    f"`{item.preflight_source_validation_schema_version or '-'}`"
                ),
                (
                    "- Preflight source validation: "
                    f"`{_validation_status(item.preflight_source_validation_ok, item.preflight_source_validation_error_codes)}`"
                ),
                (
                    "- Preflight raw payload included: "
                    f"`{_inline_bool(item.preflight_raw_payload_included)}`"
                ),
                f"- Preflight required next: `{_inline_list(item.preflight_required_next)}`",
                (
                    "- Preflight setup contract: "
                    f"`{_setup_contract_summary(item.preflight_setup_contract)}`"
                ),
                (
                    "- Preflight setup bindings: "
                    f"`{_setup_binding_summary(item.preflight_setup_contract_bindings)}`"
                ),
                f"- Operator action tokens: `{_inline_list(item.required_operator_action_tokens)}`",
                f"- Required GitHub inputs: `{_inline_list(item.required_github_inputs)}`",
                f"- Required GitHub vars: `{_inline_list(item.required_github_vars)}`",
                f"- Required GitHub secrets: `{_inline_list(item.required_github_secrets)}`",
                f"- Conditional GitHub secrets: `{_inline_list(item.conditional_github_secrets)}`",
                f"- Required environment variables: `{_inline_list(item.required_environment_variables)}`",
                "",
            ]
        )
        for action in item.required_operator_actions:
            lines.append(
                "- Operator action "
                f"`{action.token}` ({action.category}): {action.instruction}"
            )
        lines.append("")
    lines.extend(["## Command Templates", ""])
    for item in pack.launch_items:
        lines.extend(
            [
                f"### {item.requirement_id}",
                "",
                f"- Workflow dispatch: `{item.commands.workflow_dispatch}`",
                f"- Local preflight: `{item.commands.local_preflight}`",
                f"- Validate preflight: `{item.commands.validate_preflight}`",
                f"- Local live probe: `{item.commands.local_live_probe}`",
                f"- Validate artifact: `{item.commands.validate_artifact}`",
                f"- Download artifact: `{item.commands.download_artifact}`",
                f"- Download preflight artifact: `{item.commands.download_preflight_artifact}`",
                "",
            ]
        )
    lines.extend(["## Structured Command Specs", ""])
    for item in pack.launch_items:
        specs = asdict(item.command_specs)
        lines.extend([f"### {item.requirement_id}", ""])
        for name in (
            "workflow_dispatch",
            "local_preflight",
            "validate_preflight",
            "local_failure_from_preflight",
            "local_live_probe",
            "validate_artifact",
            "download_artifact",
            "download_preflight_artifact",
        ):
            spec = specs[name]
            argv = " ".join(spec["argv"])
            lines.append(
                f"- {name}: cwd=`{spec['working_directory']}` "
                f"uses_shell=`{_inline_bool(spec['uses_shell'])}` argv=`{argv}`"
            )
        lines.append("")
    lines.extend(["## Acceptance Checks", ""])
    for item in pack.launch_items:
        lines.extend([f"### {item.requirement_id}", ""])
        lines.extend(f"- {check}" for check in item.acceptance_checks)
        lines.append("")
    if pack.post_launch_verification_commands:
        lines.extend(["## Post-Launch Verification", ""])
        for command in pack.post_launch_verification_commands:
            lines.append(f"- `{command}`")
        lines.append("")
    if pack.post_launch_verification_command_specs:
        lines.extend(["## Structured Post-Launch Verification Specs", ""])
        for spec in pack.post_launch_verification_command_specs:
            argv = " ".join(spec.argv)
            lines.append(
                f"- `{spec.step_id}` cwd=`{spec.working_directory}` "
                f"uses_shell=`{_inline_bool(spec.uses_shell)}` argv=`{argv}`"
            )
        lines.append("")
    if pack.unsupported_requirement_ids:
        lines.extend(["## Unsupported Run Items", ""])
        lines.extend(f"- `{item}`" for item in pack.unsupported_requirement_ids)
    return "\n".join(lines).rstrip()


def _build_proactive_launch_item(item: dict[str, Any]) -> LaunchItem:
    workflow_file = _workflow_file(item)
    artifact = _string(item.get("artifact"))
    preflight_output = "autonomy-proactive-channel-preflight.json"
    artifact_token = _artifact_token(item)
    preflight_artifact_token = _diagnostic_artifact_token(item)
    preflight = _preflight(item)
    workflow_dispatch_argv = [
        "gh",
        "workflow",
        "run",
        workflow_file,
        "-f",
        "run_proactive_channel=true",
        "-f",
        "proactive_channel=<approved-channel>",
        "-f",
        "proactive_recipient_id=<approved-recipient-id>",
        "-f",
        "allow_production=false",
    ]
    local_preflight_argv = [
        "python",
        "scripts/probe_live_proactive_channel.py",
        "--preflight-only",
        "--allow-send",
        "--channel",
        "<approved-channel>",
        "--recipient-id",
        "<approved-recipient-id>",
        "--organization-id",
        "autonomy-runtime-evidence",
        "--out",
        preflight_output,
    ]
    validate_preflight_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_preflight.py",
        f"maritime-ai-service/{preflight_output}",
        "--requirement-id",
        "autonomy-proactive-channel",
    ]
    local_failure_from_preflight_argv = [
        "python",
        "scripts/probe_live_proactive_channel.py",
        "--failure-from-preflight",
        "--failure-preflight-json",
        preflight_output,
        "--allow-send",
        "--channel",
        "<approved-channel>",
        "--recipient-id",
        "<approved-recipient-id>",
        "--organization-id",
        "autonomy-runtime-evidence",
        "--out",
        artifact,
    ]
    local_live_probe_argv = [
        "python",
        "scripts/probe_live_proactive_channel.py",
        "--allow-send",
        "--channel",
        "<approved-channel>",
        "--recipient-id",
        "<approved-recipient-id>",
        "--organization-id",
        "autonomy-runtime-evidence",
        "--out",
        artifact,
    ]
    validate_artifact_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
        f"maritime-ai-service/{artifact}",
        "--requirement-id",
        "autonomy-proactive-channel",
    ]
    download_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        artifact_token,
        "-D",
        "<downloaded-artifact-dir>",
    ]
    download_preflight_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        preflight_artifact_token,
        "-D",
        "<preflight-dir>",
    ]
    preflight_setup_contract_bindings = _proactive_setup_contract_bindings()
    preflight_setup_contract = _setup_contract_from_preflight_or_bindings(
        preflight,
        requirement_id="autonomy-proactive-channel",
        bindings=preflight_setup_contract_bindings,
    )
    return LaunchItem(
        requirement_id=_string(item.get("requirement_id")),
        title=_string(item.get("title")),
        current_status=_string(item.get("current_status")),
        workflow=_string(item.get("workflow_execution", {}).get("workflow"))
        if isinstance(item.get("workflow_execution"), dict)
        else "",
        probe=_string(item.get("probe")),
        expected_artifact=artifact,
        expected_schema_version=_string(item.get("evidence_schema_version")),
        artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        diagnostic_artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("diagnostic_artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        preflight_source_file=_preflight_source_file(item, preflight_output),
        preflight_status=_string(preflight.get("status")),
        preflight_schema_version=_string(preflight.get("schema_version")),
        preflight_generated_at=_string(preflight.get("generated_at")),
        preflight_source_file_sha256=_string(preflight.get("source_file_sha256")),
        preflight_source_validation_schema_version=_string(
            preflight.get("source_validation_schema_version")
        ),
        preflight_source_validation_ok=_boolean(
            preflight.get("source_validation_ok")
        ),
        preflight_source_validation_error_codes=_string_list(
            preflight.get("source_validation_error_codes")
        ),
        preflight_raw_payload_included=_boolean(preflight.get("raw_payload_included")),
        preflight_required_next=_string_list(preflight.get("required_next")),
        preflight_setup_contract=preflight_setup_contract,
        preflight_setup_contract_bindings=preflight_setup_contract_bindings,
        required_operator_action_tokens=[
            _string(action.get("token"))
            for action in item.get("required_operator_actions", [])
            if isinstance(action, dict)
        ],
        required_operator_actions=_operator_actions(item),
        required_github_inputs=[
            "run_proactive_channel",
            "proactive_channel",
            "proactive_recipient_id",
            "allow_production",
        ],
        required_github_vars=[
            "WIII_PROACTIVE_CHANNEL_EVIDENCE_ENABLED",
            "WIII_PROACTIVE_CHANNEL_EVIDENCE_CHANNEL",
            "ENABLE_TELEGRAM",
            "ENABLE_ZALO",
        ],
        required_github_secrets=[
            "DATABASE_URL",
            "POSTGRES_URL_SYNC",
        ],
        conditional_github_secrets=[
            "WIII_PROACTIVE_PROBE_RECIPIENT_ID",
            "TELEGRAM_BOT_TOKEN",
            "FACEBOOK_PAGE_ACCESS_TOKEN",
            "ZALO_OA_ACCESS_TOKEN",
        ],
        required_environment_variables=[
            "WIII_LIVE_PROACTIVE_CHANNEL_PROBE",
            "DATABASE_URL",
            "POSTGRES_URL_SYNC",
        ],
        commands=LaunchCommands(
            workflow_dispatch=_render_argv(workflow_dispatch_argv),
            local_preflight=_render_argv(local_preflight_argv),
            validate_preflight=_render_argv(validate_preflight_argv),
            local_failure_from_preflight=_render_argv(
                local_failure_from_preflight_argv
            ),
            local_live_probe=_render_argv(local_live_probe_argv),
            validate_artifact=_render_argv(validate_artifact_argv),
            download_artifact=_render_argv(download_artifact_argv),
            download_preflight_artifact=_render_argv(download_preflight_artifact_argv),
        ),
        command_specs=LaunchCommandSpecs(
            workflow_dispatch=_command_spec(".", workflow_dispatch_argv),
            local_preflight=_command_spec(
                "maritime-ai-service",
                local_preflight_argv,
            ),
            validate_preflight=_command_spec(".", validate_preflight_argv),
            local_failure_from_preflight=_command_spec(
                "maritime-ai-service",
                local_failure_from_preflight_argv,
            ),
            local_live_probe=_command_spec(
                "maritime-ai-service",
                local_live_probe_argv,
            ),
            validate_artifact=_command_spec(".", validate_artifact_argv),
            download_artifact=_command_spec(".", download_artifact_argv),
            download_preflight_artifact=_command_spec(
                ".",
                download_preflight_artifact_argv,
            ),
        ),
        acceptance_checks=_acceptance_checks(item),
    )


def _build_composio_launch_item(item: dict[str, Any]) -> LaunchItem:
    workflow_file = _workflow_file(item)
    artifact = _string(item.get("artifact"))
    preflight_output = "wiii-connect-composio-acceptance-preflight.json"
    artifact_token = _artifact_token(item)
    preflight_artifact_token = _diagnostic_artifact_token(item)
    preflight = _preflight(item)
    workflow_dispatch_argv = [
        "gh",
        "workflow",
        "run",
        workflow_file,
        "-f",
        "run_composio_acceptance=true",
        "-f",
        "backend_url=<backend-url>",
        "-f",
        "auth_mode=bearer",
        "-f",
        "provider=<provider>",
        "-f",
        "action=<optional-action>",
        "-f",
        "arguments_json=<readonly-arguments-json>",
        "-f",
        "target_env=staging",
    ]
    local_preflight_argv = [
        "python",
        "scripts/wiii_connect_composio_acceptance.py",
        "--preflight-only",
        "--allow-live",
        "--backend-url",
        "<backend-url>",
        "--auth-mode",
        "bearer",
        "--provider",
        "<provider>",
        "--expect-connected",
        "--require-execution-ready",
        "--execute-readonly",
        "--skip-connect-link",
        "--arguments-json",
        "<readonly-arguments-json>",
        "--out",
        preflight_output,
    ]
    validate_preflight_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_preflight.py",
        f"maritime-ai-service/{preflight_output}",
        "--requirement-id",
        "wiii-connect-composio-acceptance",
    ]
    local_failure_from_preflight_argv = [
        "python",
        "scripts/wiii_connect_composio_acceptance.py",
        "--failure-from-preflight",
        "--failure-preflight-json",
        preflight_output,
        "--allow-live",
        "--backend-url",
        "<backend-url>",
        "--auth-mode",
        "bearer",
        "--provider",
        "<provider>",
        "--expect-connected",
        "--require-execution-ready",
        "--execute-readonly",
        "--skip-connect-link",
        "--arguments-json",
        "<readonly-arguments-json>",
        "--out",
        artifact,
    ]
    local_live_probe_argv = [
        "python",
        "scripts/wiii_connect_composio_acceptance.py",
        "--allow-live",
        "--backend-url",
        "<backend-url>",
        "--auth-mode",
        "bearer",
        "--provider",
        "<provider>",
        "--expect-connected",
        "--require-execution-ready",
        "--execute-readonly",
        "--skip-connect-link",
        "--arguments-json",
        "<readonly-arguments-json>",
        "--out",
        artifact,
    ]
    validate_artifact_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
        f"maritime-ai-service/{artifact}",
        "--requirement-id",
        "wiii-connect-composio-acceptance",
    ]
    download_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        artifact_token,
        "-D",
        "<downloaded-artifact-dir>",
    ]
    download_preflight_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        preflight_artifact_token,
        "-D",
        "<preflight-dir>",
    ]
    preflight_setup_contract_bindings = _composio_setup_contract_bindings()
    preflight_setup_contract = _setup_contract_from_preflight_or_bindings(
        preflight,
        requirement_id="wiii-connect-composio-acceptance",
        bindings=preflight_setup_contract_bindings,
    )
    return LaunchItem(
        requirement_id=_string(item.get("requirement_id")),
        title=_string(item.get("title")),
        current_status=_string(item.get("current_status")),
        workflow=_string(item.get("workflow_execution", {}).get("workflow"))
        if isinstance(item.get("workflow_execution"), dict)
        else "",
        probe=_string(item.get("probe")),
        expected_artifact=artifact,
        expected_schema_version=_string(item.get("evidence_schema_version")),
        artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        diagnostic_artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("diagnostic_artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        preflight_source_file=_preflight_source_file(item, preflight_output),
        preflight_status=_string(preflight.get("status")),
        preflight_schema_version=_string(preflight.get("schema_version")),
        preflight_generated_at=_string(preflight.get("generated_at")),
        preflight_source_file_sha256=_string(preflight.get("source_file_sha256")),
        preflight_source_validation_schema_version=_string(
            preflight.get("source_validation_schema_version")
        ),
        preflight_source_validation_ok=_boolean(
            preflight.get("source_validation_ok")
        ),
        preflight_source_validation_error_codes=_string_list(
            preflight.get("source_validation_error_codes")
        ),
        preflight_raw_payload_included=_boolean(preflight.get("raw_payload_included")),
        preflight_required_next=_string_list(preflight.get("required_next")),
        preflight_setup_contract=preflight_setup_contract,
        preflight_setup_contract_bindings=preflight_setup_contract_bindings,
        required_operator_action_tokens=[
            _string(action.get("token"))
            for action in item.get("required_operator_actions", [])
            if isinstance(action, dict)
        ],
        required_operator_actions=_operator_actions(item),
        required_github_inputs=[
            "run_composio_acceptance",
            "backend_url",
            "auth_mode",
            "provider",
            "action",
            "arguments_json",
            "target_env",
        ],
        required_github_vars=[
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_EVIDENCE_ENABLED",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_TARGET_ENV",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_BACKEND_URL",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_AUTH_MODE",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_PROVIDER",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_ACTION",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_ARGUMENTS_JSON",
            "WIII_CONNECT_COMPOSIO_ACCEPTANCE_ORG_ID",
        ],
        required_github_secrets=["WIII_ACCEPTANCE_BEARER_TOKEN"],
        conditional_github_secrets=[],
        required_environment_variables=[
            "WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE",
            "WIII_ACCEPTANCE_BEARER_TOKEN",
        ],
        commands=LaunchCommands(
            workflow_dispatch=_render_argv(workflow_dispatch_argv),
            local_preflight=_render_argv(local_preflight_argv),
            validate_preflight=_render_argv(validate_preflight_argv),
            local_failure_from_preflight=_render_argv(
                local_failure_from_preflight_argv
            ),
            local_live_probe=_render_argv(local_live_probe_argv),
            validate_artifact=_render_argv(validate_artifact_argv),
            download_artifact=_render_argv(download_artifact_argv),
            download_preflight_artifact=_render_argv(download_preflight_artifact_argv),
        ),
        command_specs=LaunchCommandSpecs(
            workflow_dispatch=_command_spec(".", workflow_dispatch_argv),
            local_preflight=_command_spec(
                "maritime-ai-service",
                local_preflight_argv,
            ),
            validate_preflight=_command_spec(".", validate_preflight_argv),
            local_failure_from_preflight=_command_spec(
                "maritime-ai-service",
                local_failure_from_preflight_argv,
            ),
            local_live_probe=_command_spec(
                "maritime-ai-service",
                local_live_probe_argv,
            ),
            validate_artifact=_command_spec(".", validate_artifact_argv),
            download_artifact=_command_spec(".", download_artifact_argv),
            download_preflight_artifact=_command_spec(
                ".",
                download_preflight_artifact_argv,
            ),
        ),
        acceptance_checks=_acceptance_checks(item),
    )


def _build_lms_test_course_launch_item(item: dict[str, Any]) -> LaunchItem:
    workflow_file = _workflow_file(item)
    artifact = _string(item.get("artifact"))
    preflight_output = "lms-test-course-preflight.json"
    artifact_token = _artifact_token(item)
    preflight_artifact_token = _diagnostic_artifact_token(item)
    preflight = _preflight(item)
    preflight_setup_contract_bindings = _lms_setup_contract_bindings()
    preflight_setup_contract = _setup_contract_from_preflight_or_bindings(
        preflight,
        requirement_id="lms-test-course-replay",
        bindings=preflight_setup_contract_bindings,
    )
    workflow_dispatch_argv = [
        "gh",
        "workflow",
        "run",
        workflow_file,
        "-f",
        "run_lms_replay=true",
        "-f",
        "transport_mode=asgi",
        "-f",
        "base_url=<backend-base-url>",
        "-f",
        "allow_production=false",
    ]
    local_preflight_argv = [
        "python",
        "scripts/probe_live_lms_test_course_replay.py",
        "--preflight-only",
        "--allow-write",
        "--allow-external-lms-write",
        "--transport-mode",
        "asgi",
        "--base-url",
        "<backend-base-url>",
        "--out",
        preflight_output,
    ]
    validate_preflight_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_preflight.py",
        f"maritime-ai-service/{preflight_output}",
        "--requirement-id",
        "lms-test-course-replay",
    ]
    local_failure_from_preflight_argv = [
        "python",
        "scripts/probe_live_lms_test_course_replay.py",
        "--failure-from-preflight",
        "--failure-preflight-json",
        preflight_output,
        "--allow-write",
        "--allow-external-lms-write",
        "--transport-mode",
        "asgi",
        "--base-url",
        "<backend-base-url>",
        "--out",
        artifact,
    ]
    local_live_probe_argv = [
        "python",
        "scripts/probe_live_lms_test_course_replay.py",
        "--allow-write",
        "--allow-external-lms-write",
        "--transport-mode",
        "asgi",
        "--base-url",
        "<backend-base-url>",
        "--out",
        artifact,
    ]
    validate_artifact_argv = [
        "python",
        "tools/wiii_self_harness/validate_runtime_evidence_artifact.py",
        f"maritime-ai-service/{artifact}",
        "--requirement-id",
        "lms-test-course-replay",
    ]
    download_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        artifact_token,
        "-D",
        "<downloaded-artifact-dir>",
    ]
    download_preflight_artifact_argv = [
        "gh",
        "run",
        "download",
        "<run-id>",
        "-n",
        preflight_artifact_token,
        "-D",
        "<preflight-dir>",
    ]
    return LaunchItem(
        requirement_id=_string(item.get("requirement_id")),
        title=_string(item.get("title")),
        current_status=_string(item.get("current_status")),
        workflow=_string(item.get("workflow_execution", {}).get("workflow"))
        if isinstance(item.get("workflow_execution"), dict)
        else "",
        probe=_string(item.get("probe")),
        expected_artifact=artifact,
        expected_schema_version=_string(item.get("evidence_schema_version")),
        artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        diagnostic_artifact_tokens=_string_list(
            item.get("workflow_execution", {}).get("diagnostic_artifact_tokens")
            if isinstance(item.get("workflow_execution"), dict)
            else []
        ),
        preflight_source_file=_preflight_source_file(item, preflight_output),
        preflight_status=_string(preflight.get("status")),
        preflight_schema_version=_string(preflight.get("schema_version")),
        preflight_generated_at=_string(preflight.get("generated_at")),
        preflight_source_file_sha256=_string(preflight.get("source_file_sha256")),
        preflight_source_validation_schema_version=_string(
            preflight.get("source_validation_schema_version")
        ),
        preflight_source_validation_ok=_boolean(
            preflight.get("source_validation_ok")
        ),
        preflight_source_validation_error_codes=_string_list(
            preflight.get("source_validation_error_codes")
        ),
        preflight_raw_payload_included=_boolean(preflight.get("raw_payload_included")),
        preflight_required_next=_string_list(preflight.get("required_next")),
        preflight_setup_contract=preflight_setup_contract,
        preflight_setup_contract_bindings=preflight_setup_contract_bindings,
        required_operator_action_tokens=[
            _string(action.get("token"))
            for action in item.get("required_operator_actions", [])
            if isinstance(action, dict)
        ],
        required_operator_actions=_operator_actions(item),
        required_github_inputs=[
            "run_lms_replay",
            "transport_mode",
            "base_url",
            "allow_production",
        ],
        required_github_vars=["WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED"],
        required_github_secrets=[
            "DATABASE_URL",
            "POSTGRES_URL_SYNC",
            "API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "WIII_LMS_TEST_COURSE_BEARER_TOKEN",
            "WIII_LMS_TEST_COURSE_APPLY_URL",
            "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
        ],
        conditional_github_secrets=[],
        required_environment_variables=[
            "WIII_LIVE_LMS_TEST_COURSE_REPLAY",
            "WIII_LMS_TEST_COURSE_APPLY_URL",
            "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
        ],
        commands=LaunchCommands(
            workflow_dispatch=_render_argv(workflow_dispatch_argv),
            local_preflight=_render_argv(local_preflight_argv),
            validate_preflight=_render_argv(validate_preflight_argv),
            local_failure_from_preflight=_render_argv(
                local_failure_from_preflight_argv
            ),
            local_live_probe=_render_argv(local_live_probe_argv),
            validate_artifact=_render_argv(validate_artifact_argv),
            download_artifact=_render_argv(download_artifact_argv),
            download_preflight_artifact=_render_argv(download_preflight_artifact_argv),
        ),
        command_specs=LaunchCommandSpecs(
            workflow_dispatch=_command_spec(".", workflow_dispatch_argv),
            local_preflight=_command_spec(
                "maritime-ai-service",
                local_preflight_argv,
            ),
            validate_preflight=_command_spec(".", validate_preflight_argv),
            local_failure_from_preflight=_command_spec(
                "maritime-ai-service",
                local_failure_from_preflight_argv,
            ),
            local_live_probe=_command_spec(
                "maritime-ai-service",
                local_live_probe_argv,
            ),
            validate_artifact=_command_spec(".", validate_artifact_argv),
            download_artifact=_command_spec(".", download_artifact_argv),
            download_preflight_artifact=_command_spec(
                ".",
                download_preflight_artifact_argv,
            ),
        ),
        acceptance_checks=_acceptance_checks(item),
    )


LAUNCH_CONTRACT_BUILDERS = {
    "autonomy-proactive-channel": _build_proactive_launch_item,
    "lms-test-course-replay": _build_lms_test_course_launch_item,
    "wiii-connect-composio-acceptance": _build_composio_launch_item,
}


def _setup_contract_from_preflight_or_bindings(
    preflight: dict[str, Any],
    *,
    requirement_id: str,
    bindings: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    contract = _dict_field(preflight.get("setup_contract"))
    if contract:
        return contract
    return {
        "version": SETUP_CONTRACT_VERSION,
        "requirement_id": requirement_id,
        "required_next": _string_list(preflight.get("required_next")),
        "workflow_inputs_required": sorted(
            _dict_field(bindings.get("workflow_inputs_required")).keys()
        ),
        "environment_flags_required": sorted(
            _dict_field(bindings.get("environment_flags_required")).keys()
        ),
        "credential_slots_required": sorted(
            _dict_field(bindings.get("credential_slots_required")).keys()
        ),
        "external_setup_required": sorted(
            _dict_field(bindings.get("external_setup_required")).keys()
        ),
        "dispatch_ready": (
            _string(preflight.get("status")) == "pass"
            and not _string_list(preflight.get("required_next"))
        ),
    }


def _proactive_setup_contract_bindings() -> dict[str, dict[str, list[str]]]:
    return {
        "workflow_inputs_required": {
            "channel": ["proactive_channel", "--channel"],
            "recipient_id": ["proactive_recipient_id", "--recipient-id"],
            "allow_send": ["run_proactive_channel", "--allow-send"],
            "allow_production": ["allow_production"],
        },
        "environment_flags_required": {
            "live_proactive_channel_probe_flag": [
                "WIII_LIVE_PROACTIVE_CHANNEL_PROBE"
            ],
        },
        "credential_slots_required": {
            "selected_channel_credential": [
                "TELEGRAM_BOT_TOKEN",
                "FACEBOOK_PAGE_ACCESS_TOKEN",
                "ZALO_OA_ACCESS_TOKEN",
            ],
        },
        "external_setup_required": {
            "approved_recipient": [
                "proactive_recipient_id",
                "WIII_PROACTIVE_PROBE_RECIPIENT_ID",
            ],
            "selected_channel_enabled": ["ENABLE_TELEGRAM", "ENABLE_ZALO"],
        },
    }


def _composio_setup_contract_bindings() -> dict[str, dict[str, list[str]]]:
    return {
        "workflow_inputs_required": {
            "backend_url": [
                "backend_url",
                "--backend-url",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_BACKEND_URL",
            ],
            "auth_mode": [
                "auth_mode",
                "--auth-mode",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_AUTH_MODE",
            ],
            "provider": [
                "provider",
                "--provider",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_PROVIDER",
            ],
            "allow_live": ["run_composio_acceptance", "--allow-live"],
            "expect_connected": ["--expect-connected"],
            "require_execution_ready": ["--require-execution-ready"],
            "execute_readonly": ["--execute-readonly"],
            "arguments_json": [
                "arguments_json",
                "--arguments-json",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_ARGUMENTS_JSON",
            ],
        },
        "environment_flags_required": {
            "live_composio_acceptance_flag": [
                "WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE"
            ],
        },
        "credential_slots_required": {
            "acceptance_bearer_token": ["WIII_ACCEPTANCE_BEARER_TOKEN"],
        },
        "external_setup_required": {
            "staging_or_live_backend": [
                "backend_url",
                "WIII_CONNECT_COMPOSIO_ACCEPTANCE_BACKEND_URL",
            ],
            "connected_provider_account": ["provider", "--expect-connected"],
            "readonly_action_schema": ["action", "--execute-readonly"],
            "execution_gateway_scope_policy": ["--require-execution-ready"],
        },
    }


def _lms_setup_contract_bindings() -> dict[str, dict[str, list[str]]]:
    return {
        "workflow_inputs_required": {
            "run_lms_replay": ["run_lms_replay"],
            "transport_mode": ["transport_mode", "--transport-mode"],
            "base_url": ["base_url", "--base-url"],
            "allow_write": ["run_lms_replay", "--allow-write"],
            "allow_external_lms_write": [
                "run_lms_replay",
                "--allow-external-lms-write",
            ],
            "allow_production": ["allow_production"],
        },
        "environment_flags_required": {
            "live_lms_test_course_replay_flag": [
                "WIII_LIVE_LMS_TEST_COURSE_REPLAY"
            ],
        },
        "credential_slots_required": {
            "external_lms_apply_token": ["WIII_LMS_TEST_COURSE_APPLY_TOKEN"],
            "lms_backend_bearer_token": ["WIII_LMS_TEST_COURSE_BEARER_TOKEN"],
        },
        "external_setup_required": {
            "external_lms_apply_endpoint": ["WIII_LMS_TEST_COURSE_APPLY_URL"],
            "staging_or_local_backend": ["base_url", "transport_mode"],
        },
    }


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(LAUNCH_PACK_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(LAUNCH_PACK_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(LAUNCH_PACK_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate command templates for launching live evidence from a "
            "completion-audit run plan."
        ),
    )
    parser.add_argument("run_plan", type=Path)
    parser.add_argument(
        "--readiness-report",
        type=Path,
        default=None,
        help="Optional readiness report that the run plan must match.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        pack = generate_completion_audit_launch_pack(
            args.run_plan,
            readiness_report_path=args.readiness_report,
        )
    except Exception as exc:  # noqa: BLE001
        code = _error_code_from_exception(exc)
        if args.format == "json":
            print(json.dumps(_json_error_payload(code), indent=2, sort_keys=True))
        else:
            print(f"Wiii Completion Audit Launch Pack: FAIL\n- {code}", file=sys.stderr)
        return 1
    if args.out:
        rendered = (
            json.dumps(pack.to_dict(), indent=2, sort_keys=True)
            if args.format == "json"
            else format_markdown(pack)
        )
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(_format_stdout_summary(pack, args.format))
    return 0


def _format_stdout_summary(pack: CompletionAuditLaunchPack, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(
            {
                "schema_version": pack.schema_version,
                "ok": pack.ok,
                "launch_item_count": pack.launch_item_count,
                "unsupported_run_item_count": pack.unsupported_run_item_count,
                "full_report": "use --out to write the launch pack contract",
            },
            indent=2,
            sort_keys=True,
        )
    return "\n".join(
        [
            "# Wiii Completion Audit Launch Pack",
            "",
            f"- Status: {'PASS' if pack.ok else 'FAIL'}",
            f"- Launch items: {pack.launch_item_count}",
            f"- Unsupported run items: {pack.unsupported_run_item_count}",
            "- Full report: use --out to write the launch pack contract",
        ]
    )


def _json_error_payload(code: str) -> dict[str, Any]:
    return {
        "schema_version": LAUNCH_PACK_SCHEMA_VERSION,
        "ok": False,
        "errors": [f"launch pack generation failed: {code}"],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code_from_exception(exc: Exception) -> str:
    message = ""
    if exc.args and isinstance(exc.args[0], str):
        message = exc.args[0]
    return _error_code(message)


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith(LAUNCH_PACK_RUN_PLAN_VALIDATION_ERROR):
        return "completion_audit_launch_pack_run_plan_invalid"
    if error == LAUNCH_PACK_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_launch_pack_output_path_directory"
    if error == LAUNCH_PACK_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_launch_pack_output_path_symlink"
    if error == LAUNCH_PACK_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_launch_pack_output_path_parent_symlink"
    return "completion_audit_launch_pack_generation_failed"


def _workflow_file(item: dict[str, Any]) -> str:
    workflow = ""
    workflow_execution = item.get("workflow_execution")
    if isinstance(workflow_execution, dict):
        workflow = _string(workflow_execution.get("workflow"))
    return workflow.replace("\\", "/").split("/")[-1]


def _artifact_token(item: dict[str, Any]) -> str:
    workflow_execution = item.get("workflow_execution")
    tokens = (
        workflow_execution.get("artifact_tokens")
        if isinstance(workflow_execution, dict)
        else []
    )
    if isinstance(tokens, list) and tokens:
        token = str(tokens[0])
        return token.replace("${{ github.run_id }}", "<run-id>")
    return "<artifact-name>"


def _diagnostic_artifact_token(item: dict[str, Any]) -> str:
    workflow_execution = item.get("workflow_execution")
    tokens = (
        workflow_execution.get("diagnostic_artifact_tokens")
        if isinstance(workflow_execution, dict)
        else []
    )
    if isinstance(tokens, list) and tokens:
        token = str(tokens[0])
        return token.replace("${{ github.run_id }}", "<run-id>")
    return "<preflight-artifact-name>"


def _acceptance_checks(item: dict[str, Any]) -> list[str]:
    acceptance = item.get("acceptance")
    if not isinstance(acceptance, dict):
        return []
    return _string_list(acceptance.get("accepted_when"))


def _operator_actions(item: dict[str, Any]) -> list[LaunchOperatorAction]:
    actions: list[LaunchOperatorAction] = []
    for action in item.get("required_operator_actions", []):
        if not isinstance(action, dict):
            continue
        actions.append(
            LaunchOperatorAction(
                token=_string(action.get("token")),
                category=_string(action.get("category")),
                instruction=_string(action.get("instruction")),
            )
        )
    return actions


def _preflight_source_file(item: dict[str, Any], fallback: str) -> str:
    preflight = item.get("preflight")
    if not isinstance(preflight, dict):
        return fallback
    source_file = _string(preflight.get("source_file"))
    return source_file or fallback


def _preflight(item: dict[str, Any]) -> dict[str, Any]:
    preflight = item.get("preflight")
    return preflight if isinstance(preflight, dict) else {}


def _launch_items_fingerprint(
    items: list[LaunchItem],
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
        "launch_items": [asdict(item) for item in items],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _launch_setup_fingerprint(
    items: list[LaunchItem],
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
                "conditional_github_secrets": item.conditional_github_secrets,
                "diagnostic_artifact_tokens": item.diagnostic_artifact_tokens,
                "preflight": {
                    "required_next": item.preflight_required_next,
                    "schema_version": item.preflight_schema_version,
                    "setup_contract": item.preflight_setup_contract,
                    "setup_contract_bindings": item.preflight_setup_contract_bindings,
                    "source_file": item.preflight_source_file,
                    "status": item.preflight_status,
                },
                "required_environment_variables": item.required_environment_variables,
                "required_github_inputs": item.required_github_inputs,
                "required_github_secrets": item.required_github_secrets,
                "required_github_vars": item.required_github_vars,
                "required_operator_action_tokens": item.required_operator_action_tokens,
                "required_operator_actions": [
                    asdict(action) for action in item.required_operator_actions
                ],
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


def _launch_acceptance_fingerprint(
    items: list[LaunchItem],
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
                "acceptance_checks": item.acceptance_checks,
                "expected_artifact": item.expected_artifact,
                "expected_schema_version": item.expected_schema_version,
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


def _launch_command_specs_fingerprint(
    items: list[LaunchItem],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_run_items_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_run_items_fingerprint_sha256": run_plan_run_items_fingerprint_sha256,
        "launch_command_specs": [
            {
                "command_specs": asdict(item.command_specs),
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


def _setup_contract_summary(value: dict[str, Any]) -> str:
    if not value:
        return "-"
    credential_slots = value.get("credential_slots_required")
    external_setup = value.get("external_setup_required")
    credential_slot_count = (
        len(credential_slots) if isinstance(credential_slots, list) else 0
    )
    external_setup_count = (
        len(external_setup) if isinstance(external_setup, list) else 0
    )
    return (
        f"{value.get('version', '-')}:"
        f"dispatch_ready={_inline_bool(_boolean(value.get('dispatch_ready')))}:"
        f"credential_slots={credential_slot_count}:"
        f"external_setup={external_setup_count}"
    )


def _setup_binding_summary(value: dict[str, dict[str, list[str]]]) -> str:
    if not value:
        return "-"
    counts = []
    for field in (
        "workflow_inputs_required",
        "environment_flags_required",
        "credential_slots_required",
        "external_setup_required",
    ):
        bindings = value.get(field)
        counts.append(f"{field}={len(bindings) if isinstance(bindings, dict) else 0}")
    return ", ".join(counts)


def _verification_command_specs(value: Any) -> list[LaunchVerificationCommandSpec]:
    if not isinstance(value, list):
        return []
    specs: list[LaunchVerificationCommandSpec] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        specs.append(
            LaunchVerificationCommandSpec(
                step_id=_string(item.get("step_id")),
                working_directory=_string(item.get("working_directory")),
                argv=_string_list(item.get("argv")),
                uses_shell=_boolean(item.get("uses_shell")),
            )
        )
    return specs


def _verification_command_specs_fingerprint(
    specs: list[LaunchVerificationCommandSpec],
    *,
    schema_version: str = LAUNCH_PACK_SCHEMA_VERSION,
    run_plan_post_run_verification_command_specs_fingerprint_sha256: str = "",
) -> str:
    manifest = {
        "schema_version": schema_version,
        "run_plan_post_run_verification_command_specs_fingerprint_sha256": (
            run_plan_post_run_verification_command_specs_fingerprint_sha256
        ),
        "post_launch_verification_command_specs": [asdict(spec) for spec in specs],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _boolean(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _command_spec(working_directory: str, argv: list[str]) -> LaunchCommandSpec:
    return LaunchCommandSpec(
        working_directory=working_directory,
        argv=argv,
        uses_shell=False,
    )


def _render_argv(argv: list[str]) -> str:
    return " ".join(argv)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _inline_list(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def _inline_bool(value: bool) -> str:
    return "true" if value else "false"


def _validation_status(ok: bool, errors: list[str]) -> str:
    if ok and not errors:
        return "ok"
    if errors:
        return "fail: " + ", ".join(errors)
    return "not-validated"


if __name__ == "__main__":
    raise SystemExit(main())
