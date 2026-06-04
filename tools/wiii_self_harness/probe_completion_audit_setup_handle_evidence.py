#!/usr/bin/env python3
"""Probe privacy-safe setup handle evidence from the local environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

import generate_completion_audit_setup_attestation as attestation_generator  # noqa: E402
import generate_completion_audit_setup_attestation_from_handles as handle_generator  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_handle_plan as plan_validator  # noqa: E402


SETUP_HANDLE_EVIDENCE_PROBE_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_handle_evidence_probe.v1"
)
COMPOSIO_ACCEPTANCE_SCHEMA_VERSION = "wiii.live_wiii_connect_composio_acceptance.v1"
COMPOSIO_ACCEPTANCE_LEGACY_SCHEMA = "wiii_connect_composio_acceptance_evidence.v1"
COMPOSIO_ACCEPTANCE_REQUIREMENT_ID = "wiii-connect-composio-acceptance"
COMPOSIO_ACCEPTANCE_ARTIFACT_NAME = "wiii-connect-composio-acceptance-evidence.json"
COMPOSIO_HANDLE_TOKEN_PREFERENCES = {
    "connected_provider_account": ["--expect-connected", "provider"],
    "execution_gateway_scope_policy": ["--require-execution-ready"],
    "readonly_action_schema": ["--execute-readonly", "action"],
}
COMPOSIO_HANDLE_EVIDENCE_KINDS = {
    "connected_provider_account": "provider_account_connected",
    "execution_gateway_scope_policy": "execution_policy_validated",
    "readonly_action_schema": "readonly_schema_validated",
}
PROACTIVE_CHANNEL_SCHEMA_VERSION = "wiii.live_proactive_channel_probe.v1"
PROACTIVE_CHANNEL_REQUIREMENT_ID = "autonomy-proactive-channel"
PROACTIVE_CHANNEL_ARTIFACT_NAME = "autonomy-proactive-channel-evidence.json"
RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION = "wiii.runtime_evidence_bundle_report.v1"
PROACTIVE_CHANNEL_ENABLE_TOKENS = {
    "telegram": "ENABLE_TELEGRAM",
    "zalo": "ENABLE_ZALO",
}
PROACTIVE_HANDLE_TOKEN_PREFERENCES = {
    "approved_recipient": ["proactive_recipient_id", "WIII_PROACTIVE_PROBE_RECIPIENT_ID"],
}
PROACTIVE_HANDLE_EVIDENCE_KINDS = {
    "selected_channel_credential": "runtime_channel_credential_validated",
    "approved_recipient": "operator_approved_recipient",
    "selected_channel_enabled": "runtime_channel_enabled",
}


def probe_completion_audit_setup_handle_evidence(
    setup_handle_plan_path: Path,
    *,
    allow_env_read: bool = False,
    allow_network: bool = False,
    timeout_seconds: float = 5.0,
    runtime_evidence_dir: Path | None = None,
    runtime_evidence_bundle_report_path: Path | None = None,
    proactive_channel_evidence_path: Path | None = None,
    composio_acceptance_evidence_path: Path | None = None,
) -> dict[str, Any]:
    validation = plan_validator.validate_setup_handle_plan(setup_handle_plan_path)
    if not validation.ok:
        raise ValueError(
            "completion audit setup handle evidence probe plan failed validation: "
            + "; ".join(validation.errors)
        )
    plan_payload = load_strict_json_file(setup_handle_plan_path)
    if not isinstance(plan_payload, dict):
        raise ValueError("completion audit setup handle plan root must be an object")
    if (
        runtime_evidence_dir is not None
        and (runtime_evidence_dir.is_symlink() or not runtime_evidence_dir.is_dir())
    ):
        raise ValueError("completion audit runtime evidence dir must be a directory")
    validated_artifact_sha256 = (
        _validated_bundle_artifact_sha256(runtime_evidence_bundle_report_path)
        if runtime_evidence_bundle_report_path is not None
        else None
    )
    handles = (
        _handles_from_environment(
            plan_payload,
            allow_network=allow_network,
            timeout_seconds=timeout_seconds,
        )
        if allow_env_read
        else []
    )
    if (
        composio_acceptance_evidence_path is None
        and runtime_evidence_dir is not None
    ):
        composio_acceptance_evidence_path = _runtime_evidence_file(
            runtime_evidence_dir,
            COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
            validated_artifact_sha256=validated_artifact_sha256,
        )
    if proactive_channel_evidence_path is None and runtime_evidence_dir is not None:
        proactive_channel_evidence_path = _runtime_evidence_file(
            runtime_evidence_dir,
            PROACTIVE_CHANNEL_ARTIFACT_NAME,
            validated_artifact_sha256=validated_artifact_sha256,
        )
    if composio_acceptance_evidence_path is not None:
        handles.extend(
            _handles_from_composio_acceptance_evidence(
                plan_payload,
                composio_acceptance_evidence_path,
            )
        )
    if proactive_channel_evidence_path is not None:
        handles.extend(
            _handles_from_proactive_channel_evidence(
                plan_payload,
                proactive_channel_evidence_path,
            )
        )
    handles = _dedupe_handles(handles)
    evidence = _evidence_payload(
        plan_payload,
        setup_handle_plan_path=setup_handle_plan_path,
        handles=handles,
    )
    errors = handle_generator._handle_evidence_errors(
        evidence,
        plan_payload=plan_payload,
        setup_handle_plan_path=setup_handle_plan_path,
    )
    if errors:
        raise ValueError(
            "completion audit setup handle evidence probe found no valid handles: "
            + "; ".join(errors)
        )
    return evidence


def _runtime_evidence_file(
    runtime_evidence_dir: Path,
    name: str,
    *,
    validated_artifact_sha256: dict[str, str] | None = None,
) -> Path | None:
    matches = sorted(
        path
        for path in runtime_evidence_dir.rglob(name)
        if path.name == name and path.is_file()
    )
    if len(matches) > 1:
        raise ValueError(
            "completion audit runtime evidence artifact matched multiple files: "
            + ", ".join(str(path) for path in matches)
        )
    if not matches:
        return None
    path = matches[0]
    if path.is_symlink() or _path_has_symlink_parent(path, stop_at=runtime_evidence_dir):
        raise ValueError(
            "completion audit runtime evidence artifact path must not be a symlink"
        )
    if validated_artifact_sha256 is not None:
        expected_sha256 = validated_artifact_sha256.get(name)
        if not expected_sha256:
            raise ValueError(
                "completion audit runtime evidence artifact is not passed in "
                f"bundle report: {name}"
            )
        observed_sha256 = attestation_generator._sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise ValueError(
                "completion audit runtime evidence artifact sha256 does not "
                f"match bundle report for {name}"
            )
    return path


def _validated_bundle_artifact_sha256(report_path: Path) -> dict[str, str]:
    payload = load_strict_json_file(report_path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit runtime evidence bundle report root must be an object")
    if payload.get("schema_version") != RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION:
        raise ValueError(
            "completion audit runtime evidence bundle report schema_version "
            f"must be {RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION}"
        )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("completion audit runtime evidence bundle report rows must be a list")
    artifact_sha256: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        artifact = row.get("artifact")
        if artifact not in {
            COMPOSIO_ACCEPTANCE_ARTIFACT_NAME,
            PROACTIVE_CHANNEL_ARTIFACT_NAME,
        }:
            continue
        if artifact in artifact_sha256:
            raise ValueError(
                "completion audit runtime evidence bundle report contains "
                f"duplicate artifact row: {artifact}"
            )
        if row.get("status") != "passed":
            continue
        row_sha256 = row.get("artifact_sha256")
        if not isinstance(row_sha256, str) or not row_sha256:
            raise ValueError(
                "completion audit runtime evidence bundle report passed row is "
                f"missing artifact_sha256: {artifact}"
            )
        artifact_sha256[artifact] = row_sha256
    return artifact_sha256


def _path_has_symlink_parent(path: Path, *, stop_at: Path) -> bool:
    try:
        stop = stop_at.resolve()
    except OSError:
        stop = stop_at.absolute()
    for parent in path.parents:
        try:
            if parent.resolve() == stop:
                return False
        except OSError:
            pass
        if parent.is_symlink():
            return True
    return False


def _handles_from_environment(
    plan_payload: dict[str, Any],
    *,
    allow_network: bool,
    timeout_seconds: float,
) -> list[dict[str, str]]:
    handles: list[dict[str, str]] = []
    for item in plan_payload.get("plan_items", []):
        if not isinstance(item, dict):
            continue
        requirement_id = item.get("requirement_id")
        checks = item.get("setup_checks")
        if not isinstance(requirement_id, str) or not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict) or check.get("present") is True:
                continue
            evidence_kinds = check.get("recommended_evidence_kinds")
            if not isinstance(evidence_kinds, list) or len(evidence_kinds) != 1:
                continue
            evidence_kind = evidence_kinds[0]
            if not isinstance(evidence_kind, str):
                continue
            source_handle = _source_handle_from_env(
                evidence_kind,
                check,
                allow_network=allow_network,
                timeout_seconds=timeout_seconds,
            )
            if not source_handle:
                continue
            handles.append(
                {
                    "requirement_id": requirement_id,
                    "category": str(check.get("category") or ""),
                    "key": str(check.get("key") or ""),
                    "source_handle": source_handle,
                    "evidence_kind": evidence_kind,
                    "evidence_ref": f"{evidence_kind}:{source_handle}",
                }
            )
    return handles


def _handles_from_proactive_channel_evidence(
    plan_payload: dict[str, Any],
    evidence_path: Path,
) -> list[dict[str, str]]:
    payload = load_strict_json_file(evidence_path)
    if not isinstance(payload, dict) or not _is_proactive_channel_pass(payload):
        return []
    artifact_sha256 = attestation_generator._sha256_file(evidence_path)
    handles: list[dict[str, str]] = []
    for item in plan_payload.get("plan_items", []):
        if not isinstance(item, dict):
            continue
        if item.get("requirement_id") != PROACTIVE_CHANNEL_REQUIREMENT_ID:
            continue
        checks = item.get("setup_checks")
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict) or check.get("present") is True:
                continue
            category = str(check.get("category") or "")
            key = str(check.get("key") or "")
            if key not in PROACTIVE_HANDLE_EVIDENCE_KINDS:
                continue
            evidence_kinds = check.get("recommended_evidence_kinds")
            if not isinstance(evidence_kinds, list) or len(evidence_kinds) != 1:
                continue
            evidence_kind = evidence_kinds[0]
            if evidence_kind != PROACTIVE_HANDLE_EVIDENCE_KINDS.get(key):
                continue
            source_handle = _proactive_source_handle(payload, check, category, key)
            if not source_handle:
                continue
            handles.append(
                {
                    "requirement_id": PROACTIVE_CHANNEL_REQUIREMENT_ID,
                    "category": category,
                    "key": key,
                    "source_handle": source_handle,
                    "evidence_kind": str(evidence_kind),
                    "evidence_ref": (
                        f"{evidence_kind}:{source_handle}:"
                        f"proactive_channel_sha256:{artifact_sha256}"
                    ),
                }
            )
    return handles


def _is_proactive_channel_pass(payload: dict[str, Any]) -> bool:
    if payload.get("schema_version") != PROACTIVE_CHANNEL_SCHEMA_VERSION:
        return False
    if payload.get("status") != "pass" or payload.get("delivered") is not True:
        return False
    if not _proactive_privacy_safe(payload):
        return False
    checks = (
        _truthy(payload, "recipient_id_hash_present")
        and _truthy(payload, "organization_id_hash_present")
        and _truthy(payload, "message_hash_present")
        and _truthy(payload, "evidence_contract", "single_outbound_send")
        and _truthy(payload, "evidence_contract", "uses_proactive_messenger")
        and _truthy(payload, "evidence_contract", "requires_live_channel_credentials")
        and _truthy(payload, "evidence_contract", "requires_database_guardrail")
        and _truthy(payload, "database", "connection_verified")
        and _truthy(payload, "database", "opt_out_scope_request_org")
        and _truthy(payload, "database", "send_audit_scope_request_org")
        and _truthy(payload, "org_scope", "context_token_set")
        and _truthy(payload, "operator_approval", "allow_send_acknowledged")
        and _truthy(payload, "operator_approval", "approved_recipient_hash_present")
        and _falsey(payload, "operator_approval", "raw_recipient_identifier_included")
        and _falsey(payload, "operator_approval", "raw_message_included")
        and _truthy(payload, "guardrail", "allowed")
        and _truthy(payload, "guardrail", "reason_allowed")
        and _truthy(payload, "guardrail", "database_opt_out_check_used")
        and _truthy(payload, "delivery", "delivered")
        and _truthy(payload, "delivery", "channel_matches_request")
        and _truthy(payload, "delivery", "duration_observed")
        and _falsey(payload, "delivery", "raw_delivery_payload_included")
        and _truthy(payload, "send_attempt", "single_send_attempt")
        and _truthy(payload, "send_attempt", "recipient_id_hash_present")
        and _truthy(payload, "send_attempt", "channel_supported")
        and _truthy(payload, "channel_contract", "requested_channel_supported")
        and _truthy(payload, "channel_contract", "requested_channel_matches_delivery")
        and _falsey(payload, "channel_contract", "credential_value_included")
        and _falsey(payload, "channel_contract", "credential_name_value_pair_included")
        and _truthy(payload, "channel_config", "supported")
        and _truthy(payload, "channel_config", "enabled")
        and _truthy(payload, "channel_config", "credential_present")
        and _falsey(payload, "channel_config", "credential_value_included")
        and _truthy(payload, "metrics", "can_send_allowed_seen")
        and _truthy(payload, "metrics", "send_delivered_seen")
        and _truthy(payload, "metrics", "send_duration_observed")
        and _truthy(payload, "metrics", "duration_metric_label_status_delivered_seen")
        and _falsey(payload, "metrics", "metric_labels_include_identifiers")
        and _falsey(payload, "metrics", "raw_metric_payload_included")
    )
    if not checks:
        return False
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    if int(metrics.get("can_send_allowed_count") or 0) < 1:
        return False
    if int(metrics.get("send_delivered_count") or 0) < 1:
        return False
    if int(metrics.get("send_duration_count") or 0) < 1:
        return False
    return metrics.get("metric_label_strategy") == "bounded_status_reason_channel_only"


def _proactive_privacy_safe(payload: dict[str, Any]) -> bool:
    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        return False
    unsafe_fields = {
        "raw_content_included",
        "raw_message_included",
        "raw_recipient_identifier_included",
        "raw_organization_identifier_included",
        "raw_channel_credentials_included",
        "raw_delivery_payload_included",
        "raw_metric_payload_included",
        "credential_name_value_pair_included",
        "raw_trigger_target_included",
        "metric_labels_include_identifiers",
    }
    return all(privacy.get(field) is False for field in unsafe_fields)


def _proactive_source_handle(
    payload: dict[str, Any],
    check: dict[str, Any],
    category: str,
    key: str,
) -> str:
    if category == "credential_slots_required" and key == "selected_channel_credential":
        credential_name = _nested_string(payload, "channel_config", "credential_name")
        return credential_name if _binding_token_present(check, credential_name) else ""
    if category == "external_setup_required" and key == "approved_recipient":
        return _preferred_binding_token(
            check,
            PROACTIVE_HANDLE_TOKEN_PREFERENCES["approved_recipient"],
        )
    if category == "external_setup_required" and key == "selected_channel_enabled":
        channel = str(payload.get("channel") or "").strip().lower()
        token = PROACTIVE_CHANNEL_ENABLE_TOKENS.get(channel, "")
        return token if _binding_token_present(check, token) else ""
    return ""


def _truthy(payload: dict[str, Any], *path: str) -> bool:
    return _nested_value(payload, *path) is True


def _falsey(payload: dict[str, Any], *path: str) -> bool:
    return _nested_value(payload, *path) is False


def _nested_string(payload: dict[str, Any], *path: str) -> str:
    value = _nested_value(payload, *path)
    return value if isinstance(value, str) and value else ""


def _nested_value(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _binding_token_present(check: dict[str, Any], token: str) -> bool:
    tokens = check.get("binding_tokens")
    return isinstance(tokens, list) and token in tokens


def _handles_from_composio_acceptance_evidence(
    plan_payload: dict[str, Any],
    evidence_path: Path,
) -> list[dict[str, str]]:
    payload = load_strict_json_file(evidence_path)
    if not isinstance(payload, dict) or not _is_composio_acceptance_pass(payload):
        return []
    artifact_sha256 = attestation_generator._sha256_file(evidence_path)
    proof_by_key = {
        "connected_provider_account": _proves_composio_connected_provider_account(
            payload
        ),
        "execution_gateway_scope_policy": _proves_composio_execution_policy(payload),
        "readonly_action_schema": _proves_composio_readonly_schema(payload),
    }
    handles: list[dict[str, str]] = []
    for item in plan_payload.get("plan_items", []):
        if not isinstance(item, dict):
            continue
        if item.get("requirement_id") != COMPOSIO_ACCEPTANCE_REQUIREMENT_ID:
            continue
        checks = item.get("setup_checks")
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict) or check.get("present") is True:
                continue
            category = str(check.get("category") or "")
            key = str(check.get("key") or "")
            if category != "external_setup_required" or proof_by_key.get(key) is not True:
                continue
            evidence_kinds = check.get("recommended_evidence_kinds")
            if not isinstance(evidence_kinds, list) or len(evidence_kinds) != 1:
                continue
            evidence_kind = evidence_kinds[0]
            if not isinstance(evidence_kind, str):
                continue
            if evidence_kind != COMPOSIO_HANDLE_EVIDENCE_KINDS.get(key):
                continue
            source_handle = _preferred_binding_token(
                check,
                COMPOSIO_HANDLE_TOKEN_PREFERENCES.get(key, []),
            )
            if not source_handle:
                continue
            handles.append(
                {
                    "requirement_id": COMPOSIO_ACCEPTANCE_REQUIREMENT_ID,
                    "category": category,
                    "key": key,
                    "source_handle": source_handle,
                    "evidence_kind": evidence_kind,
                    "evidence_ref": (
                        f"{evidence_kind}:{source_handle}:"
                        f"composio_acceptance_sha256:{artifact_sha256}"
                    ),
                }
            )
    return handles


def _is_composio_acceptance_pass(payload: dict[str, Any]) -> bool:
    if payload.get("schema_version") != COMPOSIO_ACCEPTANCE_SCHEMA_VERSION:
        return False
    if payload.get("schema") != COMPOSIO_ACCEPTANCE_LEGACY_SCHEMA:
        return False
    if payload.get("status") != "pass":
        return False
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("success") is not True:
        return False
    if summary.get("failed") not in (0, None):
        return False
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return False
    if runtime.get("path") != "external_app_action" or runtime.get("mutation") != "read":
        return False
    return _composio_privacy_safe(payload)


def _composio_privacy_safe(payload: dict[str, Any]) -> bool:
    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        return False
    unsafe_fields = {
        "raw_content_included",
        "opaque_connection_included",
        "provider_payload_included",
        "provider_arguments_included",
        "provider_response_included",
        "raw_schema_included",
        "connect_link_included",
        "bearer_value_included",
        "bearer_env_name_included",
        "raw_connection_locator_included",
        "raw_backend_url_included",
    }
    return all(privacy.get(field) is not True for field in unsafe_fields)


def _proves_composio_connected_provider_account(payload: dict[str, Any]) -> bool:
    flags = payload.get("flags")
    contract = payload.get("evidence_contract")
    connection = payload.get("connection_selection")
    if not isinstance(flags, dict) or flags.get("expect_connected") is not True:
        return False
    if (
        not isinstance(contract, dict)
        or contract.get("requires_connected_account") is not True
    ):
        return False
    if not isinstance(connection, dict):
        return False
    return (
        _check_passed(payload, "connection_listing")
        and connection.get("list_status") == "ready"
        and connection.get("active_connection_found") is True
        and connection.get("selected_connection_hash_present") is True
        and connection.get("opaque_connection_included") is False
    )


def _proves_composio_execution_policy(payload: dict[str, Any]) -> bool:
    flags = payload.get("flags")
    activation = payload.get("activation")
    execution_gateway = payload.get("execution_gateway")
    if (
        not isinstance(flags, dict)
        or flags.get("require_execution_ready") is not True
    ):
        return False
    if not isinstance(activation, dict) or not isinstance(execution_gateway, dict):
        return False
    activation_execution = activation.get("execution")
    if not isinstance(activation_execution, dict):
        return False
    gateway_scope = execution_gateway.get("scope_policy")
    activation_scope = activation_execution.get("scope_policy")
    return (
        _check_passed(payload, "activation_readiness_execution")
        and _check_passed(payload, "execution_gateway_allowed")
        and activation_execution.get("ready_to_execute_readonly") is True
        and activation_execution.get("selected_connection_hash_present") is True
        and _read_scope_allowed(activation_scope)
        and execution_gateway.get("status") == "allowed"
        and execution_gateway.get("selected_connection_hash_present") is True
        and execution_gateway.get("provider_execution_attempted") is False
        and _read_scope_allowed(gateway_scope)
    )


def _proves_composio_readonly_schema(payload: dict[str, Any]) -> bool:
    flags = payload.get("flags")
    contract = payload.get("evidence_contract")
    readonly = payload.get("readonly_execution")
    if not isinstance(flags, dict) or flags.get("execute_readonly") is not True:
        return False
    if (
        not isinstance(contract, dict)
        or contract.get("requires_readonly_execution") is not True
    ):
        return False
    if not isinstance(readonly, dict):
        return False
    schema = readonly.get("schema")
    execution = readonly.get("execution")
    if not isinstance(schema, dict) or not isinstance(execution, dict):
        return False
    return (
        _check_passed(payload, "read_only_provider_execution")
        and readonly.get("status") == "succeeded"
        and readonly.get("provider_payload_included") is False
        and schema.get("status") == "ready"
        and schema.get("schema_present") is True
        and schema.get("required_argument_keys_present") is True
        and schema.get("raw_schema_included") is False
        and execution.get("status") == "succeeded"
        and execution.get("successful") is True
        and execution.get("provider_response_included") is False
    )


def _check_passed(payload: dict[str, Any], key: str) -> bool:
    statuses = payload.get("check_statuses")
    if isinstance(statuses, dict) and statuses.get(key) == "passed":
        return True
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return False
    return any(
        isinstance(record, dict)
        and _check_status_key(record.get("name")) == key
        and record.get("status") == "passed"
        for record in checks
    )


def _check_status_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    safe = "".join(char if char.isalnum() else "_" for char in text)
    return "_".join(part for part in safe.split("_") if part)[:80] or "unknown"


def _read_scope_allowed(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") == "allowed"
        and value.get("reason") == "allowed"
        and value.get("read_required") is True
        and value.get("read_allowed") is True
    )


def _preferred_binding_token(
    check: dict[str, Any],
    preferences: list[str],
) -> str:
    tokens = check.get("binding_tokens")
    if not isinstance(tokens, list):
        return ""
    safe_tokens = [token for token in tokens if isinstance(token, str) and token]
    for token in preferences:
        if token in safe_tokens:
            return token
    return safe_tokens[0] if safe_tokens else ""


def _dedupe_handles(handles: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in handles:
        identity = (item["requirement_id"], item["category"], item["key"])
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(item)
    return deduped


def _source_handle_from_env(
    evidence_kind: str,
    check: dict[str, Any],
    *,
    allow_network: bool,
    timeout_seconds: float,
) -> str:
    tokens = check.get("binding_tokens")
    if not isinstance(tokens, list):
        return ""
    safe_tokens = [token for token in tokens if isinstance(token, str) and token]
    if evidence_kind in {
        "github_secret_present",
        "operator_approved_recipient",
        "runtime_channel_credential_validated",
    }:
        return _first_nonempty_env_token(safe_tokens)
    if evidence_kind in {
        "environment_flag_bound",
        "github_variable_present",
        "runtime_channel_enabled",
    }:
        return _first_truthy_env_token(safe_tokens)
    if evidence_kind == "backend_health_checked" and allow_network:
        for token in safe_tokens:
            value = os.getenv(token)
            if value and _backend_health_check(value, timeout_seconds=timeout_seconds):
                return token
    return ""


def _first_nonempty_env_token(tokens: list[str]) -> str:
    for token in tokens:
        if os.getenv(token):
            return token
    return ""


def _first_truthy_env_token(tokens: list[str]) -> str:
    for token in tokens:
        value = os.getenv(token)
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return token
    return ""


def _backend_health_check(raw_url: str, *, timeout_seconds: float) -> bool:
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    for suffix in ("/api/v1/health", "/health"):
        url = _join_url(raw_url, suffix)
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                if 200 <= int(response.status) < 500:
                    return True
        except (OSError, urllib.error.URLError, ValueError):
            continue
    return False


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _evidence_payload(
    plan_payload: dict[str, Any],
    *,
    setup_handle_plan_path: Path,
    handles: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": handle_generator.SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION,
        "ok": True,
        "setup_handle_plan_sha256": attestation_generator._sha256_file(
            setup_handle_plan_path
        ),
        "setup_handle_plan_schema_version": plan_payload.get("schema_version"),
        "setup_handle_plan_fingerprint_sha256": plan_payload.get(
            "setup_handle_plan_fingerprint_sha256"
        ),
        "setup_state_sha256": plan_payload.get("setup_state_sha256"),
        "setup_state_schema_version": plan_payload.get("setup_state_schema_version"),
        "setup_state_fingerprint_sha256": plan_payload.get(
            "setup_state_fingerprint_sha256"
        ),
        "handle_count": len(handles),
        "handles": handles,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        "errors": [],
        "error_codes": [],
        "error_code_counts": {},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe source-bound, privacy-safe completion-audit setup handle "
            "evidence from environment presence without writing env values."
        )
    )
    parser.add_argument("setup_handle_plan", type=Path)
    parser.add_argument(
        "--allow-env-read",
        action="store_true",
        help="Permit checking local env var presence without emitting values.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Permit backend health checks for backend_health_checked handles.",
    )
    parser.add_argument(
        "--composio-acceptance-evidence",
        type=Path,
        default=None,
        help=(
            "Optional sanitized wiii-connect-composio-acceptance pass artifact "
            "used to prove connected provider, execution policy, and readonly "
            "schema setup handles."
        ),
    )
    parser.add_argument(
        "--runtime-evidence-dir",
        type=Path,
        default=None,
        help=(
            "Optional runtime evidence bundle directory. The probe reads only "
            "canonical proactive and Composio evidence artifact names from this "
            "directory when explicit artifact paths are not supplied."
        ),
    )
    parser.add_argument(
        "--runtime-evidence-bundle-report",
        type=Path,
        default=None,
        help=(
            "Optional validate_runtime_evidence_bundle.py JSON report. When "
            "provided with --runtime-evidence-dir, canonical pass artifacts "
            "must have passed bundle rows with matching SHA-256."
        ),
    )
    parser.add_argument(
        "--proactive-channel-evidence",
        type=Path,
        default=None,
        help=(
            "Optional sanitized autonomy-proactive-channel pass artifact used "
            "to prove runtime channel credential, approved recipient, and "
            "selected channel setup handles."
        ),
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        attestation_generator.validate_output_path(args.out)
        payload = probe_completion_audit_setup_handle_evidence(
            args.setup_handle_plan,
            allow_env_read=args.allow_env_read,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout,
            runtime_evidence_dir=args.runtime_evidence_dir,
            runtime_evidence_bundle_report_path=args.runtime_evidence_bundle_report,
            proactive_channel_evidence_path=args.proactive_channel_evidence,
            composio_acceptance_evidence_path=args.composio_acceptance_evidence,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_HANDLE_EVIDENCE_PROBE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "plan failed validation" in error:
        return "completion_audit_setup_handle_evidence_probe_plan_invalid"
    if "root must be an object" in error:
        return "completion_audit_setup_handle_evidence_probe_root_invalid"
    if "found no valid handles" in error:
        return "completion_audit_setup_handle_evidence_probe_no_handles"
    if "runtime evidence dir must be a directory" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_dir_invalid"
    if "runtime evidence artifact matched multiple files" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_artifact_duplicate"
    if "runtime evidence artifact path must not be a symlink" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_artifact_symlink"
    if "artifact is not passed in bundle report" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_artifact_unvalidated"
    if "artifact sha256 does not match bundle report" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_artifact_sha_mismatch"
    if "runtime evidence bundle report" in error:
        return "completion_audit_setup_handle_evidence_probe_runtime_bundle_report_invalid"
    if "output path must not be a directory" in error:
        return "completion_audit_setup_handle_evidence_probe_output_path_directory"
    if "output path must not be a symlink" in error:
        return "completion_audit_setup_handle_evidence_probe_output_path_symlink"
    if "output path parent must not be a symlink" in error:
        return "completion_audit_setup_handle_evidence_probe_output_path_parent_symlink"
    return "completion_audit_setup_handle_evidence_probe_failed"


if __name__ == "__main__":
    raise SystemExit(main())
