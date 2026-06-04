#!/usr/bin/env python3
"""Validate completion-audit readiness report artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from report_completion_audit_readiness import (  # noqa: E402
    PREFLIGHT_SCHEMA_REQUIREMENT_IDS,
    READINESS_REPORT_SCHEMA_VERSION,
    READINESS_SCOPE_EMPTY_ERROR,
    ReadinessDiagnosticUpload,
    ReadinessNextAction,
    ReadinessPreflightSummary,
    ReadinessReport,
    ReadinessRow,
    format_markdown,
)
from strict_json import load_strict_json_file, loads_strict_json  # noqa: E402
from validate_runtime_evidence_preflight import (  # noqa: E402
    PREFLIGHT_VALIDATION_SCHEMA_VERSION,
    SETUP_CONTRACT_VERSION,
)
import validate_runtime_evidence_preflight as preflight_validator  # noqa: E402
from validate_self_harness_report_bundle import (  # noqa: E402
    REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
    validate_report_bundle,
)


FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FIELDS = {
    "schema_version",
    "registry_name",
    "registry_version",
    "registry_fingerprint_sha256",
    "bundle_root",
    "bundle_fingerprint_sha256",
    "completion_audit_fingerprint_sha256",
    "self_harness_report_bundle_root",
    "self_harness_report_bundle_fingerprint_sha256",
    "self_harness_report_bundle_validation_schema_version",
    "full_completion_audit_ready",
    "scoped_completion_audit_ready",
    "full_requirement_count",
    "full_passed_count",
    "full_missing_count",
    "full_failed_count",
    "scoped_requirement_count",
    "scoped_passed_count",
    "scoped_missing_count",
    "scoped_failed_count",
    "excluded_requirement_ids",
    "unknown_excluded_requirement_ids",
    "full_missing_requirement_ids",
    "full_failed_requirement_ids",
    "scoped_missing_requirement_ids",
    "scoped_failed_requirement_ids",
    "full_live_setup_blocked_count",
    "full_live_setup_blocked_requirement_ids",
    "scoped_live_setup_blocked_count",
    "scoped_live_setup_blocked_requirement_ids",
    "readiness_blockers",
    "scoped_readiness_blockers",
    "scoped_next_action_count",
    "scoped_next_actions_fingerprint_sha256",
    "scoped_next_actions",
    "preflight_summary_count",
    "preflight_summaries",
    "rows",
    "errors",
    "ok",
    "error_codes",
    "error_code_counts",
}
ALLOWED_FIELDS = REQUIRED_FIELDS
REQUIRED_ROW_FIELDS = {
    "requirement_id",
    "artifact",
    "status",
    "included_in_scope",
    "error_codes",
}
ALLOWED_ROW_FIELDS = REQUIRED_ROW_FIELDS
REQUIRED_ACTION_FIELDS = {
    "requirement_id",
    "title",
    "layer",
    "artifact",
    "schema_version",
    "status",
    "workflow",
    "probe",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gate_tokens",
    "artifact_tokens",
    "error_codes",
    "blocked_by_live_setup",
    "preflight_status",
    "preflight_schema_version",
    "preflight_generated_at",
    "preflight_required_next",
    "preflight_source_file",
}
ALLOWED_ACTION_FIELDS = REQUIRED_ACTION_FIELDS | {"diagnostic_uploads"}
DIAGNOSTIC_UPLOAD_FIELDS = {
    "artifact",
    "path",
    "artifact_tokens",
    "if_no_files_found",
    "retention_days",
}
REQUIRED_PREFLIGHT_FIELDS = {
    "requirement_id",
    "schema_version",
    "status",
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
ALLOWED_PREFLIGHT_FIELDS = REQUIRED_PREFLIGHT_FIELDS
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
STATUS_VALUES = {"passed", "missing", "failed"}
PREFLIGHT_STATUS_VALUES = {"pass", "fail"}


@dataclass(frozen=True)
class ReadinessValidationResult:
    validation_schema_version: str
    report_path: str
    markdown_report_path: str | None
    self_harness_report_bundle_path: str | None
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


def validate_readiness_report(
    report_path: Path,
    *,
    preflight_dir: Path | None = None,
    preflight_dirs: list[Path] | None = None,
    markdown_report_path: Path | None = None,
    self_harness_report_bundle_path: Path | None = None,
) -> ReadinessValidationResult:
    errors: list[str] = []
    source_dirs = _combined_preflight_dirs(preflight_dir, preflight_dirs)
    payload = _load_report_payload(report_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if source_dirs:
            errors.extend(_preflight_source_consistency_errors(payload, source_dirs))
        if markdown_report_path is not None:
            errors.extend(_markdown_report_errors(payload, markdown_report_path))
        if self_harness_report_bundle_path is not None:
            errors.extend(
                _self_harness_report_bundle_source_errors(
                    payload,
                    self_harness_report_bundle_path,
                )
            )
    return ReadinessValidationResult(
        validation_schema_version="wiii.completion_audit_readiness_validation.v1",
        report_path=str(report_path),
        markdown_report_path=(
            str(markdown_report_path) if markdown_report_path is not None else None
        ),
        self_harness_report_bundle_path=(
            str(self_harness_report_bundle_path)
            if self_harness_report_bundle_path is not None
            else None
        ),
        errors=errors,
    )


def _load_report_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit readiness report path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit readiness report JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit readiness report root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(REQUIRED_FIELDS - fields)
    extra = sorted(fields - ALLOWED_FIELDS)
    if missing:
        errors.append("readiness report missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("readiness report has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != READINESS_REPORT_SCHEMA_VERSION:
        errors.append(
            f"readiness report schema_version must be {READINESS_REPORT_SCHEMA_VERSION!r}"
        )
    _append_string_field_errors(payload, errors)
    _append_fingerprint_errors(payload, errors)
    _append_boolean_errors(payload, errors)
    _append_count_errors(payload, errors)
    _append_string_list_errors(payload, errors)
    row_errors, rows = _row_errors(payload.get("rows"))
    action_errors, actions = _action_errors(payload.get("scoped_next_actions"))
    preflight_errors, preflight_summaries = _preflight_summary_errors(
        payload.get("preflight_summaries")
    )
    errors.extend(row_errors)
    errors.extend(action_errors)
    errors.extend(preflight_errors)
    if not row_errors and not action_errors and not preflight_errors:
        errors.extend(
            _summary_consistency_errors(payload, rows, actions, preflight_summaries)
        )
    return errors


def _append_string_field_errors(payload: dict[str, Any], errors: list[str]) -> None:
    for field in ("registry_name", "bundle_root"):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"readiness report {field} must be a non-empty string")
    for field in (
        "self_harness_report_bundle_root",
        "self_harness_report_bundle_validation_schema_version",
    ):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            errors.append(f"readiness report {field} must be a non-empty string or null")
    schema = payload.get("self_harness_report_bundle_validation_schema_version")
    if (
        schema is not None
        and schema != REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
    ):
        errors.append(
            "readiness report self_harness_report_bundle_validation_schema_version "
            f"must be {REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION!r}"
        )


def _append_fingerprint_errors(payload: dict[str, Any], errors: list[str]) -> None:
    for field in (
        "registry_fingerprint_sha256",
        "bundle_fingerprint_sha256",
        "completion_audit_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"readiness report {field} must be a SHA-256 hex string")
    self_harness_fingerprint = payload.get(
        "self_harness_report_bundle_fingerprint_sha256"
    )
    if self_harness_fingerprint is not None and not _is_fingerprint(
        self_harness_fingerprint
    ):
        errors.append(
            "readiness report self_harness_report_bundle_fingerprint_sha256 "
            "must be a SHA-256 hex string or null"
        )
    if not _is_fingerprint(payload.get("scoped_next_actions_fingerprint_sha256")):
        errors.append(
            "readiness report scoped_next_actions_fingerprint_sha256 must be a "
            "SHA-256 hex string"
        )


def _append_boolean_errors(payload: dict[str, Any], errors: list[str]) -> None:
    for field in ("full_completion_audit_ready", "scoped_completion_audit_ready", "ok"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"readiness report {field} must be a boolean")


def _append_count_errors(payload: dict[str, Any], errors: list[str]) -> None:
    for field in (
        "registry_version",
        "full_requirement_count",
        "full_passed_count",
        "full_missing_count",
        "full_failed_count",
        "scoped_requirement_count",
        "scoped_passed_count",
        "scoped_missing_count",
        "scoped_failed_count",
        "full_live_setup_blocked_count",
        "scoped_live_setup_blocked_count",
        "scoped_next_action_count",
        "preflight_summary_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"readiness report {field} must be a non-negative integer")
    if _is_non_negative_int(payload.get("registry_version")) and payload[
        "registry_version"
    ] < 1:
        errors.append("readiness report registry_version must be >= 1")


def _append_string_list_errors(payload: dict[str, Any], errors: list[str]) -> None:
    for field in (
        "excluded_requirement_ids",
        "unknown_excluded_requirement_ids",
        "full_missing_requirement_ids",
        "full_failed_requirement_ids",
        "scoped_missing_requirement_ids",
        "scoped_failed_requirement_ids",
        "full_live_setup_blocked_requirement_ids",
        "scoped_live_setup_blocked_requirement_ids",
        "readiness_blockers",
        "scoped_readiness_blockers",
        "errors",
        "error_codes",
    ):
        if not _is_string_list(payload.get(field)):
            errors.append(f"readiness report {field} must be a string list")
    for field in (
        "excluded_requirement_ids",
        "unknown_excluded_requirement_ids",
        "error_codes",
    ):
        value = payload.get(field)
        if _is_string_list(value) and value != sorted(set(value)):
            errors.append(f"readiness report {field} must be sorted and unique")
    error_code_counts = payload.get("error_code_counts")
    if not isinstance(error_code_counts, dict) or not all(
        isinstance(key, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        for key, value in (
            error_code_counts.items() if isinstance(error_code_counts, dict) else ()
        )
    ):
        errors.append(
            "readiness report error_code_counts must map string codes to positive integers"
        )


def _row_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["readiness report rows must be a list"], rows
    for row in value:
        if not isinstance(row, dict):
            errors.append("readiness report row entries must be objects")
            continue
        rows.append(row)
        fields = set(row)
        missing = sorted(REQUIRED_ROW_FIELDS - fields)
        extra = sorted(fields - ALLOWED_ROW_FIELDS)
        if missing:
            errors.append("readiness report row missing required field(s): " + ", ".join(missing))
        if extra:
            errors.append("readiness report row has unsupported field(s): " + ", ".join(extra))
        if not isinstance(row.get("requirement_id"), str):
            errors.append("readiness report row requirement_id must be a string")
        if not isinstance(row.get("artifact"), str):
            errors.append("readiness report row artifact must be a string")
        if row.get("status") not in STATUS_VALUES:
            errors.append("readiness report row status must be passed, missing, or failed")
        if not isinstance(row.get("included_in_scope"), bool):
            errors.append("readiness report row included_in_scope must be a boolean")
        error_codes = row.get("error_codes")
        if not _is_string_list(error_codes):
            errors.append("readiness report row error_codes must be a string list")
        elif len(error_codes) != len(set(error_codes)):
            errors.append("readiness report row error_codes must not contain duplicates")
    return errors, rows


def _action_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    actions: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["readiness report scoped_next_actions must be a list"], actions
    for action in value:
        if not isinstance(action, dict):
            errors.append("readiness report next action entries must be objects")
            continue
        actions.append(action)
        fields = set(action)
        missing = sorted(REQUIRED_ACTION_FIELDS - fields)
        extra = sorted(fields - ALLOWED_ACTION_FIELDS)
        if missing:
            errors.append(
                "readiness report next action missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "readiness report next action has unsupported field(s): "
                + ", ".join(extra)
            )
        for field in (
            "requirement_id",
            "title",
            "layer",
            "artifact",
            "schema_version",
            "status",
            "workflow",
            "probe",
        ):
            if not isinstance(action.get(field), str) or not action.get(field):
                errors.append(
                    f"readiness report next action {field} must be a non-empty string"
                )
        if action.get("status") not in {"missing", "failed"}:
            errors.append("readiness report next action status must be missing or failed")
        if not isinstance(action.get("blocked_by_live_setup"), bool):
            errors.append(
                "readiness report next action blocked_by_live_setup must be a boolean"
            )
        for field in (
            "live_env_flags",
            "live_guard_tokens",
            "dispatch_or_schedule_gate_tokens",
            "artifact_tokens",
            "error_codes",
            "preflight_required_next",
        ):
            if not _is_string_list(action.get(field)):
                errors.append(
                    f"readiness report next action {field} must be a string list"
                )
        errors.extend(_diagnostic_upload_errors(action.get("diagnostic_uploads")))
        _append_action_preflight_field_errors(action, errors)
    return errors, actions


def _diagnostic_upload_errors(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return ["readiness report next action diagnostic_uploads must be a list"]
    errors: list[str] = []
    for upload in value:
        if not isinstance(upload, dict):
            errors.append("readiness report diagnostic_upload entries must be objects")
            continue
        if set(upload) != DIAGNOSTIC_UPLOAD_FIELDS:
            errors.append("readiness report diagnostic_upload fields must match contract")
        for field in ("artifact", "path", "if_no_files_found"):
            if not isinstance(upload.get(field), str) or not upload.get(field):
                errors.append(
                    f"readiness report diagnostic_upload {field} must be a non-empty string"
                )
        if not _is_string_list(upload.get("artifact_tokens")):
            errors.append(
                "readiness report diagnostic_upload artifact_tokens must be a string list"
            )
        retention_days = upload.get("retention_days")
        if not _is_non_negative_int(retention_days) or retention_days == 0:
            errors.append(
                "readiness report diagnostic_upload retention_days must be an integer >= 1"
            )
        if upload.get("if_no_files_found") != "warn":
            errors.append(
                "readiness report diagnostic_upload if_no_files_found must be warn"
            )
    return errors


def _append_action_preflight_field_errors(
    action: dict[str, Any],
    errors: list[str],
) -> None:
    preflight_status = action.get("preflight_status")
    if preflight_status != "" and preflight_status not in PREFLIGHT_STATUS_VALUES:
        errors.append(
            "readiness report next action preflight_status must be empty, pass, or fail"
        )
    for field in (
        "preflight_schema_version",
        "preflight_generated_at",
        "preflight_source_file",
    ):
        value = action.get(field)
        if not isinstance(value, str):
            errors.append(f"readiness report next action {field} must be a string")
    if preflight_status:
        schema_version = action.get("preflight_schema_version")
        source_file = action.get("preflight_source_file")
        generated_at = action.get("preflight_generated_at")
        if schema_version not in PREFLIGHT_SCHEMA_REQUIREMENT_IDS:
            errors.append(
                "readiness report next action preflight_schema_version must be a "
                "known preflight schema when preflight_status is set"
            )
        if not source_file:
            errors.append(
                "readiness report next action preflight_source_file must be non-empty "
                "when preflight_status is set"
            )
        if not generated_at:
            errors.append(
                "readiness report next action preflight_generated_at must be non-empty "
                "when preflight_status is set"
            )


def _preflight_summary_errors(
    value: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    summaries: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["readiness report preflight_summaries must be a list"], summaries
    for summary in value:
        if not isinstance(summary, dict):
            errors.append("readiness report preflight summary entries must be objects")
            continue
        summaries.append(summary)
        fields = set(summary)
        missing = sorted(REQUIRED_PREFLIGHT_FIELDS - fields)
        extra = sorted(fields - ALLOWED_PREFLIGHT_FIELDS)
        if missing:
            errors.append(
                "readiness report preflight summary missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "readiness report preflight summary has unsupported field(s): "
                + ", ".join(extra)
            )
        _append_preflight_summary_field_errors(summary, errors)
    return errors, summaries


def _append_preflight_summary_field_errors(
    summary: dict[str, Any],
    errors: list[str],
) -> None:
    requirement_id = summary.get("requirement_id")
    schema_version = summary.get("schema_version")
    if not isinstance(requirement_id, str) or not requirement_id:
        errors.append("readiness report preflight summary requirement_id must be a non-empty string")
    if schema_version not in PREFLIGHT_SCHEMA_REQUIREMENT_IDS:
        errors.append(
            "readiness report preflight summary schema_version must be a known "
            "preflight schema"
        )
    elif requirement_id != PREFLIGHT_SCHEMA_REQUIREMENT_IDS[schema_version]:
        errors.append(
            "readiness report preflight summary requirement_id must match schema_version"
        )
    if summary.get("status") not in PREFLIGHT_STATUS_VALUES:
        errors.append("readiness report preflight summary status must be pass or fail")
    for field in ("generated_at", "source_file"):
        value = summary.get(field)
        if not isinstance(value, str) or not value:
            errors.append(
                f"readiness report preflight summary {field} must be a non-empty string"
            )
    if not _is_fingerprint(summary.get("source_file_sha256")):
        errors.append(
            "readiness report preflight summary source_file_sha256 must be a "
            "SHA-256 hex string"
        )
    if (
        summary.get("source_validation_schema_version")
        != PREFLIGHT_VALIDATION_SCHEMA_VERSION
    ):
        errors.append(
            "readiness report preflight summary source_validation_schema_version "
            f"must be {PREFLIGHT_VALIDATION_SCHEMA_VERSION!r}"
        )
    if summary.get("source_validation_ok") is not True:
        errors.append(
            "readiness report preflight summary source_validation_ok must be true"
        )
    if summary.get("source_validation_error_codes") != []:
        errors.append(
            "readiness report preflight summary source_validation_error_codes "
            "must be an empty list"
        )
    source_file = summary.get("source_file")
    if isinstance(source_file, str) and ("/" in source_file or "\\" in source_file):
        errors.append("readiness report preflight summary source_file must be a file name")
    required_next = summary.get("required_next")
    if not _is_string_list(required_next):
        errors.append("readiness report preflight summary required_next must be a string list")
    elif any(not item for item in required_next):
        errors.append(
            "readiness report preflight summary required_next must not contain empty strings"
        )
    if summary.get("raw_payload_included") is not False:
        errors.append(
            "readiness report preflight summary raw_payload_included must be false"
        )
    errors.extend(_setup_contract_errors(summary))


def _setup_contract_errors(summary: dict[str, Any]) -> list[str]:
    value = summary.get("setup_contract")
    if not isinstance(value, dict):
        return ["readiness report preflight summary setup_contract must be an object"]
    if not value:
        return []
    errors: list[str] = []
    if set(value) != SETUP_CONTRACT_FIELDS:
        errors.append(
            "readiness report preflight summary setup_contract fields must match contract"
        )
    if value.get("version") != SETUP_CONTRACT_VERSION:
        errors.append(
            "readiness report preflight summary setup_contract.version must match contract"
        )
    if value.get("requirement_id") != summary.get("requirement_id"):
        errors.append(
            "readiness report preflight summary setup_contract.requirement_id must match summary"
        )
    if value.get("required_next") != summary.get("required_next"):
        errors.append(
            "readiness report preflight summary setup_contract.required_next must match summary"
        )
    for field in (
        "workflow_inputs_required",
        "environment_flags_required",
        "credential_slots_required",
        "external_setup_required",
    ):
        items = value.get(field)
        if not _is_string_list(items):
            errors.append(
                f"readiness report preflight summary setup_contract.{field} "
                "must be a string list"
            )
        elif len(items) != len(set(items)):
            errors.append(
                f"readiness report preflight summary setup_contract.{field} "
                "must not contain duplicates"
            )
        elif any(not item for item in items):
            errors.append(
                f"readiness report preflight summary setup_contract.{field} "
                "must not contain empty strings"
            )
    dispatch_ready = value.get("dispatch_ready")
    if not isinstance(dispatch_ready, bool):
        errors.append(
            "readiness report preflight summary setup_contract.dispatch_ready "
            "must be a boolean"
        )
    elif dispatch_ready != (summary.get("status") == "pass"):
        errors.append(
            "readiness report preflight summary setup_contract.dispatch_ready "
            "must match status"
        )
    rendered = json.dumps(value, sort_keys=True)
    forbidden = (
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
    )
    if any(token in rendered for token in forbidden):
        errors.append(
            "readiness report preflight summary setup_contract must not include "
            "credential names"
        )
    return errors


def _summary_consistency_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    report_errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if _is_string_list(report_errors):
        expected_error_codes = _error_codes(report_errors)
        expected_error_code_counts = _error_code_counts(report_errors)
        if payload.get("ok") != (not report_errors):
            errors.append("readiness report ok must match report errors")
        if _is_string_list(error_codes) and error_codes != expected_error_codes:
            errors.append("readiness report error_codes must match report errors")
        if (
            isinstance(error_code_counts, dict)
            and error_code_counts != expected_error_code_counts
        ):
            errors.append("readiness report error_code_counts must match report errors")

    excluded_ids = payload.get("excluded_requirement_ids")
    if not _is_string_list(excluded_ids):
        return errors
    row_ids = [row.get("requirement_id") for row in rows]
    expected_unknown_excluded = sorted(set(excluded_ids) - set(row_ids))
    if payload.get("unknown_excluded_requirement_ids") != expected_unknown_excluded:
        errors.append(
            "readiness report unknown_excluded_requirement_ids must match rows"
        )
    expected_report_errors: list[str] = []
    if expected_unknown_excluded:
        expected_report_errors.append(
            "unknown excluded completion audit requirement id(s): "
            + ", ".join(expected_unknown_excluded)
        )
    expected_included_flags = [
        isinstance(row.get("requirement_id"), str)
        and row["requirement_id"] not in set(excluded_ids)
        for row in rows
    ]
    for row, expected in zip(rows, expected_included_flags, strict=True):
        if row.get("included_in_scope") != expected:
            errors.append(
                "readiness report row included_in_scope must match excluded requirements"
            )
            break
    included_rows = [
        row for row, included in zip(rows, expected_included_flags, strict=True) if included
    ]
    if not included_rows:
        expected_report_errors.append(READINESS_SCOPE_EMPTY_ERROR)
    if _is_string_list(report_errors) and report_errors != expected_report_errors:
        errors.append("readiness report errors must match scope errors")
    errors.extend(
        _count_consistency_errors(
            payload,
            rows,
            included_rows,
            preflight_summaries,
        )
    )
    errors.extend(
        _list_consistency_errors(
            payload,
            rows,
            included_rows,
            preflight_summaries,
        )
    )
    errors.extend(
        _next_action_consistency_errors(
            payload,
            included_rows,
            actions,
            preflight_summaries,
        )
    )
    errors.extend(_preflight_summary_consistency_errors(payload, preflight_summaries))
    errors.extend(_readiness_consistency_errors(payload, rows, included_rows))
    return errors


def _count_consistency_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    included_rows: list[dict[str, Any]],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("full_requirement_count") != _registered_row_count(rows):
        errors.append("readiness report full_requirement_count must match registered rows")
    for prefix, target_rows in (("full", rows), ("scoped", included_rows)):
        for status in STATUS_VALUES:
            expected = sum(1 for row in target_rows if row.get("status") == status)
            if payload.get(f"{prefix}_{status}_count") != expected:
                errors.append(
                    f"readiness report {prefix}_{status}_count must match rows"
                )
        if prefix == "scoped" and payload.get("scoped_requirement_count") != len(
            included_rows
        ):
            errors.append(
                "readiness report scoped_requirement_count must match included rows"
            )
    setup_blocked = {
        "full_live_setup_blocked_count": _live_setup_blocked_requirement_ids(
            rows,
            preflight_summaries,
        ),
        "scoped_live_setup_blocked_count": _live_setup_blocked_requirement_ids(
            included_rows,
            preflight_summaries,
        ),
    }
    for field, expected_ids in setup_blocked.items():
        if payload.get(field) != len(expected_ids):
            errors.append(f"readiness report {field} must match preflight blockers")
    return errors


def _list_consistency_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    included_rows: list[dict[str, Any]],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    expected_lists = {
        "full_missing_requirement_ids": _row_ids_with_status(rows, "missing"),
        "full_failed_requirement_ids": _row_ids_with_status(rows, "failed"),
        "scoped_missing_requirement_ids": _row_ids_with_status(
            included_rows,
            "missing",
        ),
        "scoped_failed_requirement_ids": _row_ids_with_status(included_rows, "failed"),
        "full_live_setup_blocked_requirement_ids": (
            _live_setup_blocked_requirement_ids(rows, preflight_summaries)
        ),
        "scoped_live_setup_blocked_requirement_ids": (
            _live_setup_blocked_requirement_ids(included_rows, preflight_summaries)
        ),
    }
    for field, expected in expected_lists.items():
        if payload.get(field) != expected:
            errors.append(f"readiness report {field} must match rows")
    expected_full_blockers = _expected_blockers(
        rows,
        self_harness_linked=payload.get("self_harness_report_bundle_root") is not None,
    )
    expected_scoped_blockers = _expected_blockers(
        included_rows,
        self_harness_linked=payload.get("self_harness_report_bundle_root") is not None,
    )
    if payload.get("readiness_blockers") != expected_full_blockers:
        errors.append("readiness report readiness_blockers must match rows")
    if payload.get("scoped_readiness_blockers") != expected_scoped_blockers:
        errors.append("readiness report scoped_readiness_blockers must match rows")
    return errors


def _readiness_consistency_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    included_rows: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    self_harness_linked = _self_harness_link_present(payload)
    expected_full_ready = (
        self_harness_linked
        and not any(row.get("status") in {"missing", "failed"} for row in rows)
    )
    expected_scoped_ready = (
        self_harness_linked
        and not payload.get("errors")
        and bool(included_rows)
        and not any(row.get("status") in {"missing", "failed"} for row in included_rows)
    )
    if payload.get("full_completion_audit_ready") != expected_full_ready:
        errors.append(
            "readiness report full_completion_audit_ready must match rows and link"
        )
    if payload.get("scoped_completion_audit_ready") != expected_scoped_ready:
        errors.append(
            "readiness report scoped_completion_audit_ready must match scope and link"
        )
    return errors


def _next_action_consistency_errors(
    payload: dict[str, Any],
    included_rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    expected_rows = [row for row in included_rows if row.get("status") != "passed"]
    preflight_by_requirement = _preflight_by_requirement(preflight_summaries)
    if payload.get("scoped_next_action_count") != len(actions):
        errors.append("readiness report scoped_next_action_count must match actions")
    if payload.get("scoped_next_actions_fingerprint_sha256") != _next_actions_fingerprint(
        actions
    ):
        errors.append(
            "readiness report scoped_next_actions_fingerprint_sha256 must match actions"
        )
    if len(actions) != len(expected_rows):
        errors.append("readiness report scoped_next_actions must match scoped blockers")
        return errors
    for row, action in zip(expected_rows, actions, strict=True):
        expected_error_codes = row.get("error_codes")
        if (
            action.get("requirement_id") != row.get("requirement_id")
            or action.get("artifact") != row.get("artifact")
            or action.get("status") != row.get("status")
            or action.get("error_codes") != expected_error_codes
        ):
            errors.append(
                "readiness report scoped_next_actions must match scoped blocker rows"
            )
            break
        expected_preflight = preflight_by_requirement.get(action.get("requirement_id"))
        if not _action_preflight_matches_summary(action, expected_preflight):
            errors.append(
                "readiness report next action preflight fields must match "
                "preflight summaries"
            )
            break
        if action.get("blocked_by_live_setup") != _preflight_blocks_live_setup(
            expected_preflight
        ):
            errors.append(
                "readiness report next action blocked_by_live_setup must match "
                "preflight summaries"
            )
            break
    return errors


def _preflight_summary_consistency_errors(
    payload: dict[str, Any],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if payload.get("preflight_summary_count") != len(preflight_summaries):
        errors.append("readiness report preflight_summary_count must match summaries")
    requirement_ids = [
        summary.get("requirement_id")
        for summary in preflight_summaries
        if isinstance(summary.get("requirement_id"), str)
    ]
    if requirement_ids != sorted(requirement_ids):
        errors.append(
            "readiness report preflight summaries must be sorted by requirement_id"
        )
    if len(requirement_ids) != len(set(requirement_ids)):
        errors.append(
            "readiness report preflight summaries must not duplicate requirement_id"
        )
    return errors


def _preflight_source_consistency_errors(
    payload: dict[str, Any],
    preflight_dirs: list[Path],
) -> list[str]:
    errors: list[str] = []
    source_dirs = _resolved_preflight_dirs(preflight_dirs, errors)
    if not source_dirs:
        return errors
    summaries = payload.get("preflight_summaries")
    if not isinstance(summaries, list):
        return errors
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        errors.extend(_single_preflight_source_errors(summary, source_dirs))
    return errors


def _single_preflight_source_errors(
    summary: dict[str, Any],
    preflight_dirs: list[Path],
) -> list[str]:
    source_file = summary.get("source_file")
    requirement_id = summary.get("requirement_id")
    if not isinstance(source_file, str) or not source_file:
        return []
    if source_file.count("#") > 1:
        return ["readiness report preflight source_file must be a file name"]
    source_name, separator, source_fragment = source_file.partition("#")
    if not source_name or "/" in source_name or "\\" in source_name:
        return ["readiness report preflight source_file must be a file name"]
    errors: list[str] = []
    path = _find_preflight_source_path(
        source_name,
        source_file_sha256=summary.get("source_file_sha256"),
        preflight_dirs=preflight_dirs,
        errors=errors,
    )
    if path is None:
        if errors:
            return errors
        return [f"readiness report preflight source file must be regular: {source_file}"]
    source_sha = _sha256_file(path)
    if source_sha != summary.get("source_file_sha256"):
        errors.append(
            "readiness report preflight source_file_sha256 must match source file"
        )
    raw_payload = _load_preflight_source_payload(
        path,
        errors,
        source_file,
        source_fragment=source_fragment if separator else "",
    )
    if isinstance(requirement_id, str) and isinstance(raw_payload, dict):
        _append_preflight_source_validation_errors(
            raw_payload,
            requirement_id=requirement_id,
            summary=summary,
            errors=errors,
        )
    if isinstance(raw_payload, dict):
        errors.extend(_preflight_summary_matches_source_errors(summary, raw_payload))
    return errors


def _combined_preflight_dirs(
    preflight_dir: Path | None,
    preflight_dirs: list[Path] | None,
) -> list[Path]:
    combined: list[Path] = []
    if preflight_dir is not None:
        combined.append(preflight_dir)
    combined.extend(preflight_dirs or [])
    return combined


def _resolved_preflight_dirs(
    preflight_dirs: list[Path],
    errors: list[str],
) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for preflight_dir in preflight_dirs:
        if preflight_dir.is_symlink():
            errors.append(
                f"readiness report preflight_dir must not be a symlink: {preflight_dir}"
            )
            continue
        if not preflight_dir.exists():
            errors.append(
                f"readiness report preflight_dir does not exist: {preflight_dir}"
            )
            continue
        if not preflight_dir.is_dir():
            errors.append(
                f"readiness report preflight_dir must be a directory: {preflight_dir}"
            )
            continue
        resolved = preflight_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def _find_preflight_source_path(
    source_name: str,
    *,
    source_file_sha256: Any,
    preflight_dirs: list[Path],
    errors: list[str],
) -> Path | None:
    candidates: list[Path] = []
    for preflight_dir in preflight_dirs:
        path = preflight_dir / source_name
        if not path.exists():
            continue
        if path.is_symlink():
            errors.append(
                f"readiness report preflight source file must not be a symlink: {source_name}"
            )
            return None
        if not path.is_file():
            errors.append(
                f"readiness report preflight source file must be regular: {source_name}"
            )
            return None
        candidates.append(path)
    if not candidates:
        return None
    if isinstance(source_file_sha256, str) and FINGERPRINT_RE.match(source_file_sha256):
        for candidate in candidates:
            if _sha256_file(candidate) == source_file_sha256:
                return candidate
    return candidates[0]


def _load_preflight_source_payload(
    path: Path,
    errors: list[str],
    source_file: str,
    *,
    source_fragment: str,
) -> dict[str, Any] | None:
    try:
        payload = loads_strict_json(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"readiness report preflight source JSON is invalid: {source_file}: {exc}"
        )
        return None
    if not isinstance(payload, dict):
        return None
    if not source_fragment:
        return payload
    candidate = payload.get(source_fragment)
    if not isinstance(candidate, dict):
        errors.append(
            "readiness report preflight source fragment must be an object: "
            f"{source_file}"
        )
        return None
    return candidate


def _append_preflight_source_validation_errors(
    payload: dict[str, Any],
    *,
    requirement_id: str,
    summary: dict[str, Any],
    errors: list[str],
) -> None:
    result = _validate_preflight_payload(payload, requirement_id=requirement_id)
    result_payload = result.to_dict()
    if result.validation_schema_version != summary.get("source_validation_schema_version"):
        errors.append(
            "readiness report preflight source_validation_schema_version "
            "must match source validation"
        )
    if result.ok != summary.get("source_validation_ok"):
        errors.append(
            "readiness report preflight source_validation_ok must match "
            "source validation"
        )
    if result_payload["error_codes"] != summary.get("source_validation_error_codes"):
        errors.append(
            "readiness report preflight source_validation_error_codes "
            "must match source validation"
        )
    if not result.ok:
        errors.append(
            "readiness report preflight source validation must pass: "
            + "; ".join(result.errors)
        )


def _validate_preflight_payload(
    payload: dict[str, Any],
    *,
    requirement_id: str,
) -> preflight_validator.PreflightValidationResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "preflight.json"
        safe_write_report_text(
            path,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        return preflight_validator.validate_preflight(path, requirement_id=requirement_id)


def _preflight_summary_matches_source_errors(
    summary: dict[str, Any],
    source: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in ("schema_version", "status", "generated_at"):
        if summary.get(field) != source.get(field):
            errors.append(
                f"readiness report preflight summary {field} must match source"
            )
    required_next = source.get("required_next")
    safe_required_next = (
        [_safe_preflight_token(item) for item in required_next if isinstance(item, str)]
        if isinstance(required_next, list)
        else []
    )
    if summary.get("required_next") != safe_required_next:
        errors.append(
            "readiness report preflight summary required_next must match source"
        )
    expected_setup = _safe_setup_contract(
        source.get("setup_contract"),
        requirement_id=str(summary.get("requirement_id") or ""),
        required_next=safe_required_next,
        status=str(summary.get("status") or ""),
    )
    if summary.get("setup_contract") != expected_setup:
        errors.append(
            "readiness report preflight summary setup_contract must match source"
        )
    return errors


def _safe_preflight_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    safe = []
    for char in token[:120]:
        safe.append(char if char.isalnum() or char in {"_", "-", ".", ":"} else "_")
    return "".join(safe)


def _safe_setup_contract(
    value: Any,
    *,
    requirement_id: str,
    required_next: list[str],
    status: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "version": _safe_preflight_token(value.get("version")),
        "requirement_id": requirement_id,
        "required_next": required_next,
        "workflow_inputs_required": _safe_preflight_list(
            value.get("workflow_inputs_required")
        ),
        "environment_flags_required": _safe_preflight_list(
            value.get("environment_flags_required")
        ),
        "credential_slots_required": _safe_preflight_list(
            value.get("credential_slots_required")
        ),
        "external_setup_required": _safe_preflight_list(
            value.get("external_setup_required")
        ),
        "dispatch_ready": status == "pass" and not required_next,
    }


def _safe_preflight_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    safe = [_safe_preflight_token(item) for item in value if isinstance(item, str)]
    return [item for item in safe if item]


def _markdown_report_errors(
    payload: dict[str, Any],
    markdown_report_path: Path,
) -> list[str]:
    if not markdown_report_path.is_file() or markdown_report_path.is_symlink():
        return [
            "completion audit readiness markdown report path must be a regular file"
        ]
    expected_markdown = format_markdown(_report_from_payload(payload))
    actual_markdown = markdown_report_path.read_text(encoding="utf-8")
    if actual_markdown.rstrip("\n") != expected_markdown.rstrip("\n"):
        return ["readiness markdown report must match readiness JSON"]
    return []


def _self_harness_report_bundle_source_errors(
    payload: dict[str, Any],
    report_bundle_path: Path,
) -> list[str]:
    result = validate_report_bundle(
        report_bundle_path,
        require_self_validation=True,
    )
    if not result.ok:
        error_codes = result.to_dict().get("error_codes", [])
        rendered_codes = ", ".join(error_codes) if error_codes else "unknown_error"
        return [
            "readiness report self-harness report bundle source validation "
            f"must pass: {rendered_codes}"
        ]
    errors: list[str] = []
    if (
        payload.get("self_harness_report_bundle_fingerprint_sha256")
        != result.bundle_fingerprint_sha256
    ):
        errors.append(
            "readiness report self_harness_report_bundle_fingerprint_sha256 "
            "must match self-harness report bundle source"
        )
    if (
        payload.get("self_harness_report_bundle_validation_schema_version")
        != result.validation_schema_version
    ):
        errors.append(
            "readiness report self_harness_report_bundle_validation_schema_version "
            "must match self-harness report bundle source"
        )
    return errors


def _report_from_payload(payload: dict[str, Any]) -> ReadinessReport:
    return ReadinessReport(
        schema_version=str(payload.get("schema_version") or ""),
        registry_name=str(payload.get("registry_name") or ""),
        registry_version=int(payload.get("registry_version") or 0),
        registry_fingerprint_sha256=str(
            payload.get("registry_fingerprint_sha256") or ""
        ),
        bundle_root=str(payload.get("bundle_root") or ""),
        bundle_fingerprint_sha256=str(payload.get("bundle_fingerprint_sha256") or ""),
        completion_audit_fingerprint_sha256=str(
            payload.get("completion_audit_fingerprint_sha256") or ""
        ),
        self_harness_report_bundle_root=payload.get(
            "self_harness_report_bundle_root"
        ),
        self_harness_report_bundle_fingerprint_sha256=payload.get(
            "self_harness_report_bundle_fingerprint_sha256"
        ),
        self_harness_report_bundle_validation_schema_version=payload.get(
            "self_harness_report_bundle_validation_schema_version"
        ),
        full_completion_audit_ready=bool(payload.get("full_completion_audit_ready")),
        scoped_completion_audit_ready=bool(
            payload.get("scoped_completion_audit_ready")
        ),
        full_requirement_count=int(payload.get("full_requirement_count") or 0),
        full_passed_count=int(payload.get("full_passed_count") or 0),
        full_missing_count=int(payload.get("full_missing_count") or 0),
        full_failed_count=int(payload.get("full_failed_count") or 0),
        scoped_requirement_count=int(payload.get("scoped_requirement_count") or 0),
        scoped_passed_count=int(payload.get("scoped_passed_count") or 0),
        scoped_missing_count=int(payload.get("scoped_missing_count") or 0),
        scoped_failed_count=int(payload.get("scoped_failed_count") or 0),
        excluded_requirement_ids=_string_list(payload.get("excluded_requirement_ids")),
        unknown_excluded_requirement_ids=_string_list(
            payload.get("unknown_excluded_requirement_ids")
        ),
        full_missing_requirement_ids=_string_list(
            payload.get("full_missing_requirement_ids")
        ),
        full_failed_requirement_ids=_string_list(
            payload.get("full_failed_requirement_ids")
        ),
        scoped_missing_requirement_ids=_string_list(
            payload.get("scoped_missing_requirement_ids")
        ),
        scoped_failed_requirement_ids=_string_list(
            payload.get("scoped_failed_requirement_ids")
        ),
        full_live_setup_blocked_count=int(
            payload.get("full_live_setup_blocked_count") or 0
        ),
        full_live_setup_blocked_requirement_ids=_string_list(
            payload.get("full_live_setup_blocked_requirement_ids")
        ),
        scoped_live_setup_blocked_count=int(
            payload.get("scoped_live_setup_blocked_count") or 0
        ),
        scoped_live_setup_blocked_requirement_ids=_string_list(
            payload.get("scoped_live_setup_blocked_requirement_ids")
        ),
        readiness_blockers=_string_list(payload.get("readiness_blockers")),
        scoped_readiness_blockers=_string_list(
            payload.get("scoped_readiness_blockers")
        ),
        scoped_next_action_count=int(payload.get("scoped_next_action_count") or 0),
        scoped_next_actions_fingerprint_sha256=str(
            payload.get("scoped_next_actions_fingerprint_sha256") or ""
        ),
        scoped_next_actions=[
            _next_action_from_payload(action)
            for action in payload.get("scoped_next_actions", [])
            if isinstance(action, dict)
        ],
        preflight_summary_count=int(payload.get("preflight_summary_count") or 0),
        preflight_summaries=[
            _preflight_summary_from_payload(summary)
            for summary in payload.get("preflight_summaries", [])
            if isinstance(summary, dict)
        ],
        rows=[
            _row_from_payload(row)
            for row in payload.get("rows", [])
            if isinstance(row, dict)
        ],
        errors=_string_list(payload.get("errors")),
    )


def _next_action_from_payload(action: dict[str, Any]) -> ReadinessNextAction:
    return ReadinessNextAction(
        requirement_id=str(action.get("requirement_id") or ""),
        title=str(action.get("title") or ""),
        layer=str(action.get("layer") or ""),
        artifact=str(action.get("artifact") or ""),
        schema_version=str(action.get("schema_version") or ""),
        status=str(action.get("status") or ""),
        workflow=str(action.get("workflow") or ""),
        probe=str(action.get("probe") or ""),
        live_env_flags=_string_list(action.get("live_env_flags")),
        live_guard_tokens=_string_list(action.get("live_guard_tokens")),
        dispatch_or_schedule_gate_tokens=_string_list(
            action.get("dispatch_or_schedule_gate_tokens")
        ),
        artifact_tokens=_string_list(action.get("artifact_tokens")),
        diagnostic_uploads=[
            _diagnostic_upload_from_payload(upload)
            for upload in action.get("diagnostic_uploads", [])
            if isinstance(upload, dict)
        ],
        error_codes=_string_list(action.get("error_codes")),
        blocked_by_live_setup=bool(action.get("blocked_by_live_setup")),
        preflight_status=str(action.get("preflight_status") or ""),
        preflight_schema_version=str(action.get("preflight_schema_version") or ""),
        preflight_generated_at=str(action.get("preflight_generated_at") or ""),
        preflight_required_next=_string_list(action.get("preflight_required_next")),
        preflight_source_file=str(action.get("preflight_source_file") or ""),
    )


def _diagnostic_upload_from_payload(
    upload: dict[str, Any],
) -> ReadinessDiagnosticUpload:
    return ReadinessDiagnosticUpload(
        artifact=str(upload.get("artifact") or ""),
        path=str(upload.get("path") or ""),
        artifact_tokens=_string_list(upload.get("artifact_tokens")),
        if_no_files_found=str(upload.get("if_no_files_found") or ""),
        retention_days=int(upload.get("retention_days") or 0),
    )


def _preflight_summary_from_payload(
    summary: dict[str, Any],
) -> ReadinessPreflightSummary:
    return ReadinessPreflightSummary(
        requirement_id=str(summary.get("requirement_id") or ""),
        schema_version=str(summary.get("schema_version") or ""),
        status=str(summary.get("status") or ""),
        generated_at=str(summary.get("generated_at") or ""),
        required_next=_string_list(summary.get("required_next")),
        source_file=str(summary.get("source_file") or ""),
        source_file_sha256=str(summary.get("source_file_sha256") or ""),
        source_validation_schema_version=str(
            summary.get("source_validation_schema_version") or ""
        ),
        source_validation_ok=bool(summary.get("source_validation_ok")),
        source_validation_error_codes=_string_list(
            summary.get("source_validation_error_codes")
        ),
        raw_payload_included=bool(summary.get("raw_payload_included")),
        setup_contract=(
            summary.get("setup_contract")
            if isinstance(summary.get("setup_contract"), dict)
            else {}
        ),
    )


def _row_from_payload(row: dict[str, Any]) -> ReadinessRow:
    return ReadinessRow(
        requirement_id=str(row.get("requirement_id") or ""),
        artifact=str(row.get("artifact") or ""),
        status=str(row.get("status") or ""),
        included_in_scope=bool(row.get("included_in_scope")),
        error_codes=_string_list(row.get("error_codes")),
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _action_preflight_matches_summary(
    action: dict[str, Any],
    summary: dict[str, Any] | None,
) -> bool:
    if summary is None:
        return (
            action.get("preflight_status") == ""
            and action.get("preflight_schema_version") == ""
            and action.get("preflight_generated_at") == ""
            and action.get("preflight_required_next") == []
            and action.get("preflight_source_file") == ""
        )
    return (
        action.get("preflight_status") == summary.get("status")
        and action.get("preflight_schema_version") == summary.get("schema_version")
        and action.get("preflight_generated_at") == summary.get("generated_at")
        and action.get("preflight_required_next") == summary.get("required_next")
        and action.get("preflight_source_file") == summary.get("source_file")
    )


def _preflight_by_requirement(
    preflight_summaries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        summary["requirement_id"]: summary
        for summary in preflight_summaries
        if isinstance(summary.get("requirement_id"), str)
    }


def _live_setup_blocked_requirement_ids(
    rows: list[dict[str, Any]],
    preflight_summaries: list[dict[str, Any]],
) -> list[str]:
    preflight_by_requirement = _preflight_by_requirement(preflight_summaries)
    blocked_ids: list[str] = []
    for row in rows:
        requirement_id = row.get("requirement_id")
        if row.get("status") == "passed" or not isinstance(requirement_id, str):
            continue
        if _preflight_blocks_live_setup(preflight_by_requirement.get(requirement_id)):
            blocked_ids.append(requirement_id)
    return blocked_ids


def _preflight_blocks_live_setup(summary: dict[str, Any] | None) -> bool:
    return bool(
        summary is not None
        and (
            summary.get("status") != "pass"
            or bool(summary.get("required_next"))
            or summary.get("source_validation_ok") is not True
            or summary.get("raw_payload_included") is not False
        )
    )


def _next_actions_fingerprint(
    actions: list[dict[str, Any]],
    *,
    schema_version: str = READINESS_REPORT_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "actions": actions,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _registered_row_count(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if "unexpected_unregistered_artifact" not in (row.get("error_codes") or [])
    )


def _row_ids_with_status(rows: list[dict[str, Any]], status: str) -> list[str]:
    return [
        row["requirement_id"]
        for row in rows
        if row.get("status") == status and isinstance(row.get("requirement_id"), str)
    ]


def _expected_blockers(
    rows: list[dict[str, Any]],
    *,
    self_harness_linked: bool,
) -> list[str]:
    blockers: list[str] = []
    if not self_harness_linked:
        blockers.append("self_harness_report_bundle_link_missing")
    for row in rows:
        status = row.get("status")
        requirement_id = row.get("requirement_id")
        if status != "passed" and isinstance(requirement_id, str):
            blockers.append(f"{status}:{requirement_id}")
    return blockers or ["-"]


def _self_harness_link_present(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("self_harness_report_bundle_root"), str)
        and _is_fingerprint(payload.get("self_harness_report_bundle_fingerprint_sha256"))
        and payload.get("self_harness_report_bundle_validation_schema_version")
        == REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
    )


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
    return counts


def _error_code(error: str) -> str:
    if error.startswith("unknown excluded completion audit requirement id"):
        return "completion_audit_unknown_excluded_requirement"
    if error == READINESS_SCOPE_EMPTY_ERROR:
        return "completion_audit_readiness_scope_empty"
    if error == "completion audit readiness report path must be a regular file":
        return "completion_audit_readiness_path_invalid"
    if error.startswith("completion audit readiness report JSON is invalid"):
        return "completion_audit_readiness_json_invalid"
    if error == "completion audit readiness report root must be an object":
        return "completion_audit_readiness_root_invalid"
    if "markdown report" in error:
        return "completion_audit_readiness_markdown_invalid"
    if "self-harness report bundle source validation must pass" in error:
        return "completion_audit_readiness_self_harness_bundle_invalid"
    if "self-harness report bundle source" in error:
        return "completion_audit_readiness_self_harness_bundle_mismatch"
    if error.startswith("readiness report missing required field"):
        return "completion_audit_readiness_missing_required_fields"
    if error.startswith("readiness report has unsupported field"):
        return "completion_audit_readiness_unsupported_fields"
    if error.startswith("readiness report schema_version must be"):
        return "completion_audit_readiness_schema_mismatch"
    if (
        "preflight summary" in error
        or "preflight_summaries" in error
        or "preflight_summary" in error
        or "preflight source" in error
        or "preflight_dir" in error
    ):
        return "completion_audit_readiness_preflight_invalid"
    if "next action" in error or "scoped_next_action" in error:
        return "completion_audit_readiness_next_actions_invalid"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_readiness_fingerprint_invalid"
    if error.endswith("must be a boolean"):
        return "completion_audit_readiness_boolean_invalid"
    if error.endswith("must be a non-negative integer") or error.endswith("must be >= 1"):
        return "completion_audit_readiness_count_invalid"
    if error.endswith("must be a string list"):
        return "completion_audit_readiness_string_list_invalid"
    if error.endswith("must be sorted and unique"):
        return "completion_audit_readiness_string_list_order_invalid"
    if "error_code_counts" in error:
        return "completion_audit_readiness_error_code_counts_invalid"
    if error.startswith("readiness report row"):
        return "completion_audit_readiness_row_invalid"
    if "must match" in error:
        return "completion_audit_readiness_consistency_mismatch"
    return "completion_audit_readiness_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit readiness report artifact.",
    )
    parser.add_argument("report_path", type=Path)
    parser.add_argument(
        "--preflight-dir",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional directory containing raw or embedded preflight JSON sources "
            "referenced by the report. May be supplied more than once."
        ),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=None,
        help="Optional Markdown readiness report that must match the JSON report.",
    )
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        default=None,
        help=(
            "Optional self-harness report bundle source whose validated "
            "fingerprint/schema must match the readiness JSON."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_readiness_report(
        args.report_path,
        preflight_dirs=args.preflight_dir,
        markdown_report_path=args.markdown_report,
        self_harness_report_bundle_path=args.self_harness_report_bundle,
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
        print("Wiii Completion Audit Readiness Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Readiness Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
