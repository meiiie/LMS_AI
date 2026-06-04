#!/usr/bin/env python3
"""Validate downloaded Wiii completion-audit handoff report bundles."""

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

from generate_completion_audit_handoff import (  # noqa: E402
    COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION,
    EXPECTED_GENERATED_REPORTS,
    HANDOFF_JSON_REPORT,
    HANDOFF_MARKDOWN_REPORT,
    RUNTIME_BUNDLE_JSON_REPORT,
    RUNTIME_BUNDLE_MARKDOWN_REPORT,
)
from strict_json import loads_strict_json  # noqa: E402
from validate_runtime_evidence_bundle import (  # noqa: E402
    BUNDLE_REPORT_SCHEMA_VERSION,
    REGISTRY_NAME,
    _error_code as runtime_bundle_error_code,
    _parse_timestamp as parse_runtime_timestamp,
)
from validate_self_harness_report_bundle import (  # noqa: E402
    REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
)


HANDOFF_VALIDATION_SCHEMA_VERSION = "wiii.completion_audit_handoff_validation.v1"
HANDOFF_REPORT_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit handoff validation output path must not be a directory"
)
HANDOFF_REPORT_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit handoff validation output path must not be a symlink"
)
HANDOFF_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit handoff validation output path parent must not be a symlink"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
EXPECTED_REPORT_NAMES = set(EXPECTED_GENERATED_REPORTS)
HANDOFF_JSON_REQUIRED_FIELDS = {
    "schema_version",
    "ok",
    "completion_audit_ready",
    "release_handoff_ready",
    "release_blocker_count",
    "release_blockers",
    "completion_audit_fingerprint_sha256",
    "runtime_evidence_bundle_fingerprint_sha256",
    "self_harness_report_bundle_fingerprint_sha256",
    "handoff_root",
    "artifact_bundle_root",
    "self_harness_report_bundle_root",
    "reports",
    "runtime_evidence_bundle_report",
    "runtime_blockers",
    "readiness_summary",
    "control_chain_summary",
    "setup_gap_summary",
}
HANDOFF_JSON_ALLOWED_FIELDS = HANDOFF_JSON_REQUIRED_FIELDS
RUNTIME_BLOCKER_FIELDS = {
    "requirement_id",
    "artifact",
    "status",
    "error_codes",
}
RELEASE_BLOCKER_KINDS = {
    "runtime_evidence",
    "runtime_readiness",
    "control_chain",
    "setup_gap",
    "setup_gap_summary",
}
RELEASE_RUNTIME_BLOCKER_FIELDS = {
    "kind",
    "requirement_id",
    "artifact",
    "status",
    "error_codes",
    "recovery_action",
}
RUNTIME_RECOVERY_ACTION_FIELDS = {
    "requirement_id",
    "artifact",
    "status",
    "workflow",
    "probe",
    "blocked_by_live_setup",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gate_tokens",
    "artifact_tokens",
    "preflight_required_next",
    "error_codes",
}
RELEASE_RUNTIME_READINESS_BLOCKER_FIELDS = {
    "kind",
    "blocker_id",
    "status",
    "error_codes",
}
RELEASE_CONTROL_BLOCKER_FIELDS = {
    "kind",
    "blocker_id",
    "status",
    "error_codes",
}
RELEASE_SETUP_GAP_BLOCKER_FIELDS = {
    "kind",
    "requirement_id",
    "pending_setup_check_count",
    "diagnostic_pending_setup_keys",
    "non_diagnostic_pending_setup_keys",
    "resolution_actions",
}
RELEASE_SETUP_GAP_ACTION_FIELDS = {
    "category",
    "key",
    "evidence_kind",
    "binding_token_count",
    "source_handle_options",
    "attestation_option_count",
}
RELEASE_SETUP_GAP_SUMMARY_BLOCKER_FIELDS = {
    "kind",
    "blocker_id",
    "status",
    "pending_setup_check_count",
    "diagnostic_present_setup_mismatch_count",
}
CONTROL_CHAIN_BLOCKER_IDS = {
    "control_chain_ok",
    "control_chain_ready",
    "dispatch_ready",
}
SETUP_GAP_SUMMARY_BLOCKER_IDS = {
    "setup_gap_ok",
    "setup_diagnostic_mismatch",
    "pending_setup_checks",
}
CONTROL_CHAIN_SUMMARY_FIELDS = {
    "path",
    "sha256",
    "validation_schema_version",
    "ok",
    "control_chain_ready",
    "dispatch_ready",
    "setup_gap_report_path",
    "setup_gap_markdown_report_path",
    "dispatch_diagnostics_path",
    "error_codes",
}
READINESS_SUMMARY_FIELDS = {
    "path",
    "sha256",
    "schema_version",
    "ok",
    "scoped_completion_audit_ready",
    "scoped_next_action_count",
    "scoped_next_actions_fingerprint_sha256",
    "scoped_next_actions",
}
SETUP_GAP_SUMMARY_FIELDS = {
    "path",
    "sha256",
    "markdown_path",
    "markdown_sha256",
    "schema_version",
    "ok",
    "setup_gap_report_fingerprint_sha256",
    "setup_diagnostics_consistent",
    "requirement_count",
    "blocked_requirement_count",
    "pending_setup_check_count",
    "diagnostic_pending_setup_check_count",
    "non_diagnostic_pending_setup_check_count",
    "diagnostic_present_setup_mismatch_count",
    "privacy",
    "blocked_requirements",
}
SETUP_GAP_BLOCKED_REQUIREMENT_FIELDS = {
    "requirement_id",
    "pending_setup_check_count",
    "diagnostic_pending_setup_keys",
    "non_diagnostic_pending_setup_keys",
    "resolution_actions",
}
SETUP_GAP_PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}
RUNTIME_JSON_ALLOWED_FIELDS = {
    "schema_version",
    "registry_name",
    "registry_version",
    "bundle_root",
    "validated_at",
    "registry_fingerprint_sha256",
    "bundle_fingerprint_sha256",
    "completion_audit_fingerprint_sha256",
    "self_harness_report_bundle_root",
    "self_harness_report_bundle_fingerprint_sha256",
    "self_harness_report_bundle_validation_schema_version",
    "requirement_count",
    "row_count",
    "passed_count",
    "missing_count",
    "failed_count",
    "unexpected_count",
    "error_codes",
    "error_code_counts",
    "rows",
    "ok",
    "completion_audit_ready",
}
RUNTIME_JSON_REQUIRED_FIELDS = RUNTIME_JSON_ALLOWED_FIELDS
RUNTIME_ROW_ALLOWED_FIELDS = {
    "requirement_id",
    "artifact",
    "status",
    "path",
    "artifact_sha256",
    "checks_passed",
    "generated_at",
    "max_age_hours",
    "age_hours",
    "errors",
    "error_codes",
}
RUNTIME_ROW_REQUIRED_FIELDS = RUNTIME_ROW_ALLOWED_FIELDS


@dataclass(frozen=True)
class HandoffValidationRow:
    file_name: str
    status: str
    report_sha256: str | None
    errors: list[str]


@dataclass(frozen=True)
class HandoffValidationResult:
    validation_schema_version: str
    require_completion_audit_ready: bool
    bundle_root: str
    report_count: int
    fingerprinted_report_count: int
    bundle_fingerprint_sha256: str
    completion_audit_ready: bool | None
    release_handoff_ready: bool | None
    completion_audit_fingerprint_sha256: str | None
    runtime_evidence_bundle_fingerprint_sha256: str | None
    self_harness_report_bundle_fingerprint_sha256: str | None
    passed_count: int
    failed_count: int
    unexpected_count: int
    rows: list[HandoffValidationRow]
    error_code_counts: dict[str, int]

    @property
    def ok(self) -> bool:
        return self.failed_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["error_codes"] = list(self.error_code_counts.keys())
        data["rows"] = [
            {**row_data, "error_codes": _row_error_codes(row)}
            for row_data, row in zip(data["rows"], self.rows, strict=True)
        ]
        return data


def validate_handoff_bundle(
    bundle_root: Path,
    *,
    require_completion_audit_ready: bool = False,
) -> HandoffValidationResult:
    if not bundle_root.exists():
        raise ValueError(f"completion audit handoff bundle root does not exist: {bundle_root}")
    if bundle_root.is_symlink():
        raise ValueError(
            f"completion audit handoff bundle root must not be a symlink: {bundle_root}"
        )
    if not bundle_root.is_dir():
        raise ValueError(
            f"completion audit handoff bundle root must be a directory: {bundle_root}"
        )

    handoff_payload: dict[str, Any] | None = None
    runtime_payload: dict[str, Any] | None = None
    rows: list[HandoffValidationRow] = []
    for report_name in EXPECTED_GENERATED_REPORTS:
        path = bundle_root / report_name
        row_errors: list[str] = []
        report_sha256: str | None = None
        payload: Any = None
        text: str | None = None
        if not path.exists():
            row_errors.append(f"missing handoff report file {report_name!r}")
        elif path.is_symlink():
            row_errors.append(f"handoff report file must not be a symlink: {report_name}")
        elif not path.is_file():
            row_errors.append(f"handoff report path must be a file: {report_name}")
        else:
            report_sha256 = _sha256_file(path)
            text = path.read_text(encoding="utf-8")
            if report_name.endswith(".json"):
                try:
                    payload = loads_strict_json(text)
                except Exception as exc:  # noqa: BLE001
                    row_errors.append(f"handoff report JSON is invalid: {exc}")
                if not isinstance(payload, dict):
                    row_errors.append("handoff report JSON root must be an object")
            else:
                row_errors.extend(
                    _markdown_report_errors(report_name=report_name, text=text)
                )
        if report_name == HANDOFF_JSON_REPORT and isinstance(payload, dict):
            handoff_payload = payload
            row_errors.extend(_handoff_json_errors(payload))
        elif report_name == RUNTIME_BUNDLE_JSON_REPORT and isinstance(payload, dict):
            runtime_payload = payload
            row_errors.extend(_runtime_json_errors(payload))

        rows.append(
            HandoffValidationRow(
                file_name=report_name,
                status="passed" if not row_errors else "failed",
                report_sha256=report_sha256,
                errors=row_errors,
            )
        )

    rows.extend(_unexpected_report_rows(bundle_root))
    cross_errors = _cross_report_errors(
        handoff_payload=handoff_payload,
        runtime_payload=runtime_payload,
        bundle_root=bundle_root,
    )
    if cross_errors:
        rows.append(
            HandoffValidationRow(
                file_name=HANDOFF_JSON_REPORT,
                status="failed",
                report_sha256=_sha256_file(bundle_root / HANDOFF_JSON_REPORT)
                if (bundle_root / HANDOFF_JSON_REPORT).is_file()
                and not (bundle_root / HANDOFF_JSON_REPORT).is_symlink()
                else None,
                errors=cross_errors,
            )
        )
    completion_audit_ready = (
        handoff_payload.get("completion_audit_ready")
        if isinstance(handoff_payload, dict)
        and isinstance(handoff_payload.get("completion_audit_ready"), bool)
        else None
    )
    release_handoff_ready = (
        handoff_payload.get("release_handoff_ready")
        if isinstance(handoff_payload, dict)
        and isinstance(handoff_payload.get("release_handoff_ready"), bool)
        else None
    )
    if require_completion_audit_ready and release_handoff_ready is not True:
        rows.append(
            HandoffValidationRow(
                file_name=HANDOFF_JSON_REPORT,
                status="failed",
                report_sha256=_sha256_file(bundle_root / HANDOFF_JSON_REPORT)
                if (bundle_root / HANDOFF_JSON_REPORT).is_file()
                and not (bundle_root / HANDOFF_JSON_REPORT).is_symlink()
                else None,
                errors=["completion audit handoff is not ready"],
            )
        )

    passed_count = sum(1 for row in rows if row.status == "passed")
    failed_count = sum(1 for row in rows if row.status == "failed")
    unexpected_count = sum(1 for row in rows if row.file_name not in EXPECTED_REPORT_NAMES)
    error_code_counts = _error_code_counts(rows)
    return HandoffValidationResult(
        validation_schema_version=HANDOFF_VALIDATION_SCHEMA_VERSION,
        require_completion_audit_ready=require_completion_audit_ready,
        bundle_root=str(bundle_root),
        report_count=len(rows),
        fingerprinted_report_count=sum(1 for row in rows if row.report_sha256),
        bundle_fingerprint_sha256=_bundle_fingerprint(
            rows,
            validation_schema_version=HANDOFF_VALIDATION_SCHEMA_VERSION,
            require_completion_audit_ready=require_completion_audit_ready,
        ),
        completion_audit_ready=completion_audit_ready,
        release_handoff_ready=release_handoff_ready,
        completion_audit_fingerprint_sha256=_string_field(
            handoff_payload,
            "completion_audit_fingerprint_sha256",
        ),
        runtime_evidence_bundle_fingerprint_sha256=_string_field(
            handoff_payload,
            "runtime_evidence_bundle_fingerprint_sha256",
        ),
        self_harness_report_bundle_fingerprint_sha256=_string_field(
            handoff_payload,
            "self_harness_report_bundle_fingerprint_sha256",
        ),
        passed_count=passed_count,
        failed_count=failed_count,
        unexpected_count=unexpected_count,
        rows=rows,
        error_code_counts=error_code_counts,
    )


def _handoff_json_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(HANDOFF_JSON_REQUIRED_FIELDS - fields)
    extra = sorted(fields - HANDOFF_JSON_ALLOWED_FIELDS)
    if missing:
        errors.append("handoff JSON missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("handoff JSON has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION:
        errors.append(
            "handoff schema_version must be "
            f"{COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION!r}"
        )
    for field in ("ok", "completion_audit_ready", "release_handoff_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"handoff {field} must be a boolean")
    for field in (
        "completion_audit_fingerprint_sha256",
        "runtime_evidence_bundle_fingerprint_sha256",
        "self_harness_report_bundle_fingerprint_sha256",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not FINGERPRINT_RE.match(value):
            errors.append(f"handoff {field} must be a SHA-256 hex string")
    for field in (
        "handoff_root",
        "artifact_bundle_root",
        "self_harness_report_bundle_root",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"handoff {field} must be a non-empty string")
    if payload.get("reports") != list(EXPECTED_GENERATED_REPORTS):
        errors.append("handoff reports must match expected generated reports")
    if not isinstance(payload.get("runtime_evidence_bundle_report"), dict):
        errors.append("handoff runtime_evidence_bundle_report must be an object")
    if not _is_non_negative_int(payload.get("release_blocker_count")):
        errors.append("handoff release_blocker_count must be non-negative")
    errors.extend(_release_blocker_errors(payload.get("release_blockers")))
    if (
        _is_non_negative_int(payload.get("release_blocker_count"))
        and isinstance(payload.get("release_blockers"), list)
        and payload["release_blocker_count"] != len(payload["release_blockers"])
    ):
        errors.append("handoff release_blocker_count must match release_blockers")
    errors.extend(_runtime_blocker_errors(payload.get("runtime_blockers")))
    errors.extend(_readiness_summary_errors(payload.get("readiness_summary")))
    errors.extend(_control_chain_summary_errors(payload.get("control_chain_summary")))
    errors.extend(_setup_gap_summary_errors(payload.get("setup_gap_summary")))
    return errors


def _release_blocker_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["handoff release_blockers must be a list"]
    errors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            errors.append("handoff release_blocker entries must be objects")
            continue
        kind = item.get("kind")
        if kind not in RELEASE_BLOCKER_KINDS:
            errors.append("handoff release_blocker kind is unsupported")
            continue
        if kind == "runtime_evidence":
            errors.extend(_release_runtime_blocker_errors(item))
        elif kind == "runtime_readiness":
            errors.extend(_release_runtime_readiness_blocker_errors(item))
        elif kind == "control_chain":
            errors.extend(_release_control_blocker_errors(item))
        elif kind == "setup_gap":
            errors.extend(_release_setup_gap_blocker_errors(item))
        elif kind == "setup_gap_summary":
            errors.extend(_release_setup_gap_summary_blocker_errors(item))
    return errors


def _release_runtime_blocker_errors(item: dict[str, Any]) -> list[str]:
    errors = _field_set_errors(
        item,
        required=RELEASE_RUNTIME_BLOCKER_FIELDS,
        label="handoff release_blocker runtime_evidence",
    )
    for field in ("requirement_id", "artifact", "status"):
        if not isinstance(item.get(field), str) or not item.get(field):
            errors.append(
                f"handoff release_blocker runtime_evidence {field} must be non-empty"
            )
    status = item.get("status")
    if isinstance(status, str) and status not in {"missing", "failed"}:
        errors.append(
            "handoff release_blocker runtime_evidence status must be missing or failed"
        )
    if not _is_unique_string_list(item.get("error_codes")):
        errors.append(
            "handoff release_blocker runtime_evidence error_codes must be unique strings"
        )
    errors.extend(
        _runtime_recovery_action_errors(
            item.get("recovery_action"),
            label="handoff release_blocker runtime_evidence",
            nullable=True,
        )
    )
    return errors


def _release_control_blocker_errors(item: dict[str, Any]) -> list[str]:
    errors = _field_set_errors(
        item,
        required=RELEASE_CONTROL_BLOCKER_FIELDS,
        label="handoff release_blocker control_chain",
    )
    blocker_id = item.get("blocker_id")
    if blocker_id not in CONTROL_CHAIN_BLOCKER_IDS:
        errors.append("handoff release_blocker control_chain blocker_id is unsupported")
    if item.get("status") != "blocked":
        errors.append("handoff release_blocker control_chain status must be blocked")
    if not _is_unique_string_list(item.get("error_codes")):
        errors.append(
            "handoff release_blocker control_chain error_codes must be unique strings"
        )
    return errors


def _release_runtime_readiness_blocker_errors(item: dict[str, Any]) -> list[str]:
    errors = _field_set_errors(
        item,
        required=RELEASE_RUNTIME_READINESS_BLOCKER_FIELDS,
        label="handoff release_blocker runtime_readiness",
    )
    if item.get("blocker_id") != "completion_audit_ready":
        errors.append(
            "handoff release_blocker runtime_readiness blocker_id is unsupported"
        )
    if item.get("status") != "blocked":
        errors.append("handoff release_blocker runtime_readiness status must be blocked")
    if not _is_unique_string_list(item.get("error_codes")):
        errors.append(
            "handoff release_blocker runtime_readiness error_codes must be unique strings"
        )
    return errors


def _release_setup_gap_blocker_errors(item: dict[str, Any]) -> list[str]:
    errors = _field_set_errors(
        item,
        required=RELEASE_SETUP_GAP_BLOCKER_FIELDS,
        label="handoff release_blocker setup_gap",
    )
    requirement_id = item.get("requirement_id")
    if not isinstance(requirement_id, str) or not requirement_id:
        errors.append("handoff release_blocker setup_gap requirement_id must be non-empty")
    pending_count = item.get("pending_setup_check_count")
    diagnostic_keys = item.get("diagnostic_pending_setup_keys")
    non_diagnostic_keys = item.get("non_diagnostic_pending_setup_keys")
    if not isinstance(pending_count, int) or isinstance(pending_count, bool):
        errors.append("handoff release_blocker setup_gap pending count must be an integer")
    elif pending_count <= 0:
        errors.append("handoff release_blocker setup_gap pending count must be positive")
    if not _is_unique_string_list(diagnostic_keys):
        errors.append(
            "handoff release_blocker setup_gap diagnostic keys must be unique strings"
        )
    if not _is_unique_string_list(non_diagnostic_keys):
        errors.append(
            "handoff release_blocker setup_gap non-diagnostic keys must be unique strings"
        )
    if (
        isinstance(pending_count, int)
        and not isinstance(pending_count, bool)
        and isinstance(diagnostic_keys, list)
        and isinstance(non_diagnostic_keys, list)
        and pending_count != len(diagnostic_keys) + len(non_diagnostic_keys)
    ):
        errors.append(
            "handoff release_blocker setup_gap pending count must match setup keys"
        )
    errors.extend(
        _setup_gap_resolution_action_errors(
            item.get("resolution_actions"),
            pending_count=pending_count,
            diagnostic_keys=diagnostic_keys,
            non_diagnostic_keys=non_diagnostic_keys,
            label="handoff release_blocker setup_gap",
        )
    )
    return errors


def _release_setup_gap_summary_blocker_errors(item: dict[str, Any]) -> list[str]:
    errors = _field_set_errors(
        item,
        required=RELEASE_SETUP_GAP_SUMMARY_BLOCKER_FIELDS,
        label="handoff release_blocker setup_gap_summary",
    )
    if item.get("blocker_id") not in SETUP_GAP_SUMMARY_BLOCKER_IDS:
        errors.append(
            "handoff release_blocker setup_gap_summary blocker_id is unsupported"
        )
    if item.get("status") != "blocked":
        errors.append("handoff release_blocker setup_gap_summary status must be blocked")
    for field in (
        "pending_setup_check_count",
        "diagnostic_present_setup_mismatch_count",
    ):
        if not _is_non_negative_int(item.get(field)):
            errors.append(
                f"handoff release_blocker setup_gap_summary {field} must be non-negative"
            )
    return errors


def _field_set_errors(
    item: dict[str, Any],
    *,
    required: set[str],
    label: str,
) -> list[str]:
    errors: list[str] = []
    fields = set(item)
    missing = sorted(required - fields)
    extra = sorted(fields - required)
    if missing:
        errors.append(f"{label} missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append(f"{label} has unsupported field(s): " + ", ".join(extra))
    return errors


def _runtime_blocker_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["handoff runtime_blockers must be a list"]
    errors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            errors.append("handoff runtime_blocker entries must be objects")
            continue
        fields = set(item)
        missing = sorted(RUNTIME_BLOCKER_FIELDS - fields)
        extra = sorted(fields - RUNTIME_BLOCKER_FIELDS)
        if missing:
            errors.append(
                "handoff runtime_blocker missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "handoff runtime_blocker has unsupported field(s): "
                + ", ".join(extra)
            )
        for field in ("requirement_id", "artifact", "status"):
            if not isinstance(item.get(field), str):
                errors.append(f"handoff runtime_blocker {field} must be a string")
        status = item.get("status")
        if isinstance(status, str) and status not in {"missing", "failed"}:
            errors.append("handoff runtime_blocker status must be missing or failed")
        if not _is_unique_string_list(item.get("error_codes")):
            errors.append(
                "handoff runtime_blocker error_codes must be a unique string list"
            )
    return errors


def _readiness_summary_errors(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return ["handoff readiness_summary must be an object or null"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(READINESS_SUMMARY_FIELDS - fields)
    extra = sorted(fields - READINESS_SUMMARY_FIELDS)
    if missing:
        errors.append(
            "handoff readiness_summary missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "handoff readiness_summary has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in ("path", "schema_version"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"handoff readiness_summary {field} must be non-empty")
    for field in ("sha256", "scoped_next_actions_fingerprint_sha256"):
        if not isinstance(value.get(field), str) or not FINGERPRINT_RE.match(
            value.get(field, "")
        ):
            errors.append(f"handoff readiness_summary {field} must be SHA-256")
    for field in ("ok", "scoped_completion_audit_ready"):
        if not isinstance(value.get(field), bool):
            errors.append(f"handoff readiness_summary {field} must be a boolean")
    if not _is_non_negative_int(value.get("scoped_next_action_count")):
        errors.append(
            "handoff readiness_summary scoped_next_action_count must be non-negative"
        )
    actions = value.get("scoped_next_actions")
    if not isinstance(actions, list):
        errors.append("handoff readiness_summary scoped_next_actions must be a list")
    else:
        if (
            _is_non_negative_int(value.get("scoped_next_action_count"))
            and value["scoped_next_action_count"] != len(actions)
        ):
            errors.append(
                "handoff readiness_summary scoped_next_action_count must match actions"
            )
        requirement_ids = [
            action.get("requirement_id")
            for action in actions
            if isinstance(action, dict)
            and isinstance(action.get("requirement_id"), str)
            and action.get("requirement_id")
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            errors.append(
                "handoff readiness_summary scoped_next_actions requirement_id values "
                "must be unique"
            )
        for action in actions:
            errors.extend(
                _runtime_recovery_action_errors(
                    action,
                    label="handoff readiness_summary scoped_next_action",
                    nullable=False,
                )
            )
    return errors


def _runtime_recovery_action_errors(
    value: Any,
    *,
    label: str,
    nullable: bool,
) -> list[str]:
    if value is None and nullable:
        return []
    if not isinstance(value, dict):
        return [f"{label} recovery_action must be an object or null"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(RUNTIME_RECOVERY_ACTION_FIELDS - fields)
    extra = sorted(fields - RUNTIME_RECOVERY_ACTION_FIELDS)
    if missing:
        errors.append(
            f"{label} recovery_action missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            f"{label} recovery_action has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in ("requirement_id", "artifact", "status", "workflow", "probe"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"{label} recovery_action {field} must be non-empty")
    if not isinstance(value.get("blocked_by_live_setup"), bool):
        errors.append(f"{label} recovery_action blocked_by_live_setup must be a boolean")
    for field in (
        "live_env_flags",
        "live_guard_tokens",
        "dispatch_or_schedule_gate_tokens",
        "artifact_tokens",
        "preflight_required_next",
        "error_codes",
    ):
        if not _is_unique_string_list(value.get(field)):
            errors.append(f"{label} recovery_action {field} must be unique strings")
    return errors


def _control_chain_summary_errors(value: Any) -> list[str]:
    if value is None:
        return []
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["handoff control_chain_summary must be an object or null"]
    fields = set(value)
    missing = sorted(CONTROL_CHAIN_SUMMARY_FIELDS - fields)
    extra = sorted(fields - CONTROL_CHAIN_SUMMARY_FIELDS)
    if missing:
        errors.append(
            "handoff control_chain_summary missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "handoff control_chain_summary has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in ("path", "validation_schema_version"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"handoff control_chain_summary {field} must be non-empty")
    if not isinstance(value.get("sha256"), str) or not FINGERPRINT_RE.match(
        value.get("sha256", "")
    ):
        errors.append("handoff control_chain_summary sha256 must be SHA-256")
    for field in ("ok", "control_chain_ready", "dispatch_ready"):
        if not isinstance(value.get(field), bool):
            errors.append(f"handoff control_chain_summary {field} must be a boolean")
    for field in (
        "setup_gap_report_path",
        "setup_gap_markdown_report_path",
        "dispatch_diagnostics_path",
    ):
        if value.get(field) is not None and not isinstance(value.get(field), str):
            errors.append(
                f"handoff control_chain_summary {field} must be a string or null"
            )
    if not _is_unique_string_list(value.get("error_codes")):
        errors.append(
            "handoff control_chain_summary error_codes must be a unique string list"
        )
    return errors


def _setup_gap_summary_errors(value: Any) -> list[str]:
    if value is None:
        return []
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["handoff setup_gap_summary must be an object or null"]
    fields = set(value)
    missing = sorted(SETUP_GAP_SUMMARY_FIELDS - fields)
    extra = sorted(fields - SETUP_GAP_SUMMARY_FIELDS)
    if missing:
        errors.append(
            "handoff setup_gap_summary missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "handoff setup_gap_summary has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in ("path", "schema_version"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"handoff setup_gap_summary {field} must be non-empty")
    for field in ("sha256", "setup_gap_report_fingerprint_sha256"):
        if not isinstance(value.get(field), str) or not FINGERPRINT_RE.match(
            value.get(field, "")
        ):
            errors.append(f"handoff setup_gap_summary {field} must be SHA-256")
    if value.get("markdown_path") is not None and not isinstance(
        value.get("markdown_path"),
        str,
    ):
        errors.append("handoff setup_gap_summary markdown_path must be string or null")
    if value.get("markdown_sha256") is not None and (
        not isinstance(value.get("markdown_sha256"), str)
        or not FINGERPRINT_RE.match(value.get("markdown_sha256", ""))
    ):
        errors.append("handoff setup_gap_summary markdown_sha256 must be SHA-256 or null")
    for field in ("ok", "setup_diagnostics_consistent"):
        if not isinstance(value.get(field), bool):
            errors.append(f"handoff setup_gap_summary {field} must be a boolean")
    for field in (
        "requirement_count",
        "blocked_requirement_count",
        "pending_setup_check_count",
        "diagnostic_pending_setup_check_count",
        "non_diagnostic_pending_setup_check_count",
        "diagnostic_present_setup_mismatch_count",
    ):
        if not _is_non_negative_int(value.get(field)):
            errors.append(f"handoff setup_gap_summary {field} must be non-negative")
    errors.extend(_setup_gap_privacy_errors(value.get("privacy")))
    errors.extend(_setup_gap_blocked_requirement_errors(value.get("blocked_requirements")))
    return errors


def _setup_gap_privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["handoff setup_gap_summary privacy must be an object"]
    errors: list[str] = []
    fields = set(value)
    missing = sorted(SETUP_GAP_PRIVACY_FIELDS - fields)
    extra = sorted(fields - SETUP_GAP_PRIVACY_FIELDS)
    if missing:
        errors.append(
            "handoff setup_gap_summary privacy missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "handoff setup_gap_summary privacy has unsupported field(s): "
            + ", ".join(extra)
        )
    for field in SETUP_GAP_PRIVACY_FIELDS:
        if not isinstance(value.get(field), bool):
            errors.append(f"handoff setup_gap_summary privacy {field} must be a boolean")
    return errors


def _setup_gap_blocked_requirement_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["handoff setup_gap_summary blocked_requirements must be a list"]
    errors: list[str] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            errors.append(
                "handoff setup_gap_summary blocked_requirements entries must be objects"
            )
            continue
        fields = set(item)
        missing = sorted(SETUP_GAP_BLOCKED_REQUIREMENT_FIELDS - fields)
        extra = sorted(fields - SETUP_GAP_BLOCKED_REQUIREMENT_FIELDS)
        if missing:
            errors.append(
                "handoff setup_gap_summary blocked requirement missing field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "handoff setup_gap_summary blocked requirement has unsupported field(s): "
                + ", ".join(extra)
            )
        requirement_id = item.get("requirement_id")
        if not isinstance(requirement_id, str) or not requirement_id:
            errors.append(
                "handoff setup_gap_summary blocked requirement_id must be non-empty"
            )
        elif requirement_id in seen_ids:
            errors.append(
                "handoff setup_gap_summary blocked requirement_id must be unique"
            )
        else:
            seen_ids.add(requirement_id)
        pending_count = item.get("pending_setup_check_count")
        if not isinstance(pending_count, int) or isinstance(pending_count, bool):
            errors.append(
                "handoff setup_gap_summary blocked pending count must be an integer"
            )
        elif pending_count <= 0:
            errors.append(
                "handoff setup_gap_summary blocked pending count must be positive"
            )
        for field in (
            "diagnostic_pending_setup_keys",
            "non_diagnostic_pending_setup_keys",
        ):
            if not _is_unique_string_list(item.get(field)):
                errors.append(
                    f"handoff setup_gap_summary blocked {field} must be unique strings"
                )
        errors.extend(
            _setup_gap_resolution_action_errors(
                item.get("resolution_actions"),
                pending_count=pending_count,
                diagnostic_keys=item.get("diagnostic_pending_setup_keys"),
                non_diagnostic_keys=item.get("non_diagnostic_pending_setup_keys"),
                label="handoff setup_gap_summary blocked",
            )
        )
    return errors


def _setup_gap_resolution_action_errors(
    value: Any,
    *,
    pending_count: Any,
    diagnostic_keys: Any,
    non_diagnostic_keys: Any,
    label: str,
) -> list[str]:
    if not isinstance(value, list):
        return [f"{label} resolution_actions must be a list"]
    errors: list[str] = []
    action_keys: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            errors.append(f"{label} resolution_actions entries must be objects")
            continue
        fields = set(item)
        missing = sorted(RELEASE_SETUP_GAP_ACTION_FIELDS - fields)
        extra = sorted(fields - RELEASE_SETUP_GAP_ACTION_FIELDS)
        if missing:
            errors.append(
                f"{label} resolution action missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                f"{label} resolution action has unsupported field(s): "
                + ", ".join(extra)
            )
        for field in ("category", "key", "evidence_kind"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"{label} resolution action {field} must be non-empty")
        for field in ("binding_token_count", "attestation_option_count"):
            if not _is_non_negative_int(item.get(field)):
                errors.append(f"{label} resolution action {field} must be non-negative")
        if not _is_unique_string_list(item.get("source_handle_options")):
            errors.append(
                f"{label} resolution action source_handle_options must be unique strings"
            )
        category = item.get("category")
        key = item.get("key")
        if isinstance(category, str) and isinstance(key, str) and category and key:
            action_keys.append(f"{category}:{key}")
    if isinstance(pending_count, int) and not isinstance(pending_count, bool):
        if len(value) != pending_count:
            errors.append(f"{label} resolution_actions must match pending count")
    if _is_unique_string_list(diagnostic_keys) and _is_unique_string_list(
        non_diagnostic_keys
    ):
        expected = sorted(list(diagnostic_keys) + list(non_diagnostic_keys))
        if sorted(action_keys) != expected:
            errors.append(f"{label} resolution_actions must match setup keys")
    if len(action_keys) != len(set(action_keys)):
        errors.append(f"{label} resolution action setup keys must be unique")
    return errors


def _runtime_json_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(RUNTIME_JSON_REQUIRED_FIELDS - fields)
    extra = sorted(fields - RUNTIME_JSON_ALLOWED_FIELDS)
    if missing:
        errors.append("runtime bundle JSON missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append(
            "runtime bundle JSON has unsupported field(s): " + ", ".join(extra)
        )
    if payload.get("schema_version") != BUNDLE_REPORT_SCHEMA_VERSION:
        errors.append(
            f"runtime bundle schema_version must be {BUNDLE_REPORT_SCHEMA_VERSION!r}"
        )
    if payload.get("registry_name") != REGISTRY_NAME:
        errors.append(f"runtime bundle registry_name must be {REGISTRY_NAME!r}")
    if not _is_positive_int(payload.get("registry_version")):
        errors.append("runtime bundle registry_version must be an integer >= 1")
    if (
        not isinstance(payload.get("validated_at"), str)
        or not UTC_TIMESTAMP_RE.match(payload["validated_at"])
    ):
        errors.append("runtime bundle validated_at must be a normalized UTC timestamp")
    if (
        payload.get("self_harness_report_bundle_validation_schema_version")
        != REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
    ):
        errors.append(
            "runtime bundle self_harness_report_bundle_validation_schema_version "
            f"must be {REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION!r}"
        )
    for field in ("ok", "completion_audit_ready"):
        if not isinstance(payload.get(field), bool):
            errors.append(f"runtime bundle {field} must be a boolean")
    for field in (
        "registry_fingerprint_sha256",
        "completion_audit_fingerprint_sha256",
        "bundle_fingerprint_sha256",
        "self_harness_report_bundle_fingerprint_sha256",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not FINGERPRINT_RE.match(value):
            errors.append(f"runtime bundle {field} must be a SHA-256 hex string")
    for field in (
        "bundle_root",
        "self_harness_report_bundle_root",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"runtime bundle {field} must be a non-empty string")
    for field in (
        "requirement_count",
        "row_count",
        "passed_count",
        "missing_count",
        "failed_count",
        "unexpected_count",
    ):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"runtime bundle {field} must be a non-negative integer")
    error_codes = payload.get("error_codes")
    if not isinstance(error_codes, list) or not all(
        isinstance(item, str) for item in error_codes
    ):
        errors.append("runtime bundle error_codes must be a string list")
    elif len(error_codes) != len(set(error_codes)):
        errors.append("runtime bundle error_codes must not contain duplicate entries")
    rows = payload.get("rows")
    row_objects: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        errors.append("runtime bundle rows must be a list")
    else:
        if isinstance(payload.get("row_count"), int) and payload["row_count"] != len(rows):
            errors.append("runtime bundle row_count must match rows length")
        for row in rows:
            if not isinstance(row, dict):
                errors.append("runtime bundle row entries must be objects")
            else:
                row_objects.append(row)
    error_code_counts = payload.get("error_code_counts")
    valid_error_code_counts = isinstance(error_code_counts, dict) and all(
        isinstance(key, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        for key, value in (
            error_code_counts.items() if isinstance(error_code_counts, dict) else ()
        )
    )
    if not isinstance(error_code_counts, dict) or not all(
        isinstance(key, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        for key, value in (
            error_code_counts.items() if isinstance(error_code_counts, dict) else ()
        )
    ):
        errors.append("runtime bundle error_code_counts must be a string-to-int map")
    elif isinstance(error_codes, list) and all(
        isinstance(item, str) for item in error_codes
    ):
        if set(error_code_counts) != set(error_codes):
            errors.append("runtime bundle error_code_counts keys must match error_codes")
        if any(value <= 0 for value in error_code_counts.values()):
            errors.append(
                "runtime bundle error_code_counts values must be positive for listed error codes"
            )
    if isinstance(rows, list) and len(row_objects) == len(rows):
        errors.extend(
            _runtime_row_summary_errors(
                payload,
                row_objects,
                error_code_counts if valid_error_code_counts else None,
            )
        )
        errors.extend(_runtime_row_freshness_errors(payload, row_objects))
        errors.extend(_runtime_row_path_errors(payload, row_objects))
        errors.extend(_runtime_fingerprint_errors(payload, row_objects))
    return errors


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_unique_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    )


def _flatten_summary_keys(
    requirements: list[Any],
    field: str,
) -> list[str]:
    keys: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        value = requirement.get(field)
        if not isinstance(value, list):
            continue
        for key in value:
            if isinstance(key, str):
                keys.add(key)
    return sorted(keys)


def _format_runtime_blockers(blockers: list[Any]) -> str:
    chunks: list[str] = []
    for item in blockers:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id") or "-")
        artifact = str(item.get("artifact") or "-")
        status = str(item.get("status") or "-")
        error_codes = item.get("error_codes")
        codes = (
            ",".join(error_codes)
            if isinstance(error_codes, list)
            and all(isinstance(code, str) for code in error_codes)
            else "-"
        )
        chunks.append(f"{requirement_id}/{artifact}:{status}:{codes or '-'}")
    return "; ".join(chunks)


def _format_release_blockers(blockers: list[Any]) -> str:
    chunks: list[str] = []
    for item in blockers:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "runtime_evidence":
            chunks.append(
                "runtime_evidence:"
                + _format_runtime_blockers([item])
                + ":recovery="
                + (_format_recovery_action(item.get("recovery_action")) or "-")
            )
            continue
        if kind == "control_chain":
            error_codes = item.get("error_codes")
            codes = (
                ",".join(error_codes)
                if isinstance(error_codes, list)
                and all(isinstance(code, str) for code in error_codes)
                else "-"
            )
            chunks.append(
                "control_chain:"
                f"{item.get('blocker_id') or '-'}:"
                f"{item.get('status') or '-'}:"
                f"{codes or '-'}"
            )
            continue
        if kind == "runtime_readiness":
            error_codes = item.get("error_codes")
            codes = (
                ",".join(error_codes)
                if isinstance(error_codes, list)
                and all(isinstance(code, str) for code in error_codes)
                else "-"
            )
            chunks.append(
                "runtime_readiness:"
                f"{item.get('blocker_id') or '-'}:"
                f"{item.get('status') or '-'}:"
                f"{codes or '-'}"
            )
            continue
        if kind == "setup_gap":
            diagnostic_keys = item.get("diagnostic_pending_setup_keys")
            non_diagnostic_keys = item.get("non_diagnostic_pending_setup_keys")
            diagnostic = (
                ",".join(diagnostic_keys)
                if isinstance(diagnostic_keys, list)
                and all(isinstance(key, str) for key in diagnostic_keys)
                else "-"
            )
            non_diagnostic = (
                ",".join(non_diagnostic_keys)
                if isinstance(non_diagnostic_keys, list)
                and all(isinstance(key, str) for key in non_diagnostic_keys)
                else "-"
            )
            chunks.append(
                "setup_gap:"
                f"{item.get('requirement_id') or '-'}:"
                f"pending={item.get('pending_setup_check_count') or '-'}:"
                f"diagnostic={diagnostic or '-'}:"
                f"non_diagnostic={non_diagnostic or '-'}:"
                f"actions={_format_resolution_actions(item.get('resolution_actions')) or '-'}"
            )
            continue
        if kind == "setup_gap_summary":
            chunks.append(
                "setup_gap_summary:"
                f"{item.get('blocker_id') or '-'}:"
                f"{item.get('status') or '-'}:"
                f"pending={item.get('pending_setup_check_count') or 0}:"
                "diagnostic_mismatches="
                f"{item.get('diagnostic_present_setup_mismatch_count') or 0}"
            )
    return "; ".join(chunks)


def _format_resolution_actions(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    chunks: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_handles = item.get("source_handle_options")
        handles = (
            ",".join(source_handles)
            if isinstance(source_handles, list)
            and all(isinstance(handle, str) for handle in source_handles)
            else "-"
        )
        chunks.append(
            f"{item.get('category') or '-'}:{item.get('key') or '-'}"
            f"@{item.get('evidence_kind') or '-'}"
            f"[handles={handles or '-'};"
            f"bindings={item.get('binding_token_count') or 0};"
            f"attestations={item.get('attestation_option_count') or 0}]"
        )
    return "|".join(chunks)


def _format_recovery_action(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    workflow = str(value.get("workflow") or "-")
    probe = str(value.get("probe") or "-")
    guard_tokens = value.get("live_guard_tokens")
    guards = (
        ",".join(guard_tokens)
        if isinstance(guard_tokens, list)
        and all(isinstance(token, str) for token in guard_tokens)
        else "-"
    )
    return f"{workflow}/{probe}[guards={guards or '-'}]"


def _runtime_fingerprint_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[str]:
    row_errors, fingerprint_rows = _runtime_fingerprint_rows(rows)
    if row_errors:
        return row_errors
    bundle_root = payload.get("bundle_root")
    registry_fingerprint = payload.get("registry_fingerprint_sha256")
    if not isinstance(bundle_root, str) or not bundle_root:
        return []
    if not isinstance(registry_fingerprint, str) or not FINGERPRINT_RE.match(
        registry_fingerprint
    ):
        return []
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        return []
    validated_at = payload.get("validated_at")
    if not isinstance(validated_at, str) or not validated_at:
        return []
    expected_bundle_fingerprint = _runtime_bundle_fingerprint(
        fingerprint_rows,
        bundle_root=bundle_root,
        registry_fingerprint_sha256=registry_fingerprint,
        schema_version=schema_version,
        validated_at=validated_at,
    )
    errors: list[str] = []
    if payload.get("bundle_fingerprint_sha256") != expected_bundle_fingerprint:
        errors.append(
            "runtime bundle bundle_fingerprint_sha256 must match canonical row manifest"
        )
    expected_completion_fingerprint = _runtime_completion_audit_fingerprint(
        bundle_fingerprint_sha256=expected_bundle_fingerprint,
        self_harness_report_bundle_fingerprint_sha256=payload.get(
            "self_harness_report_bundle_fingerprint_sha256"
        ),
        self_harness_report_bundle_validation_schema_version=payload.get(
            "self_harness_report_bundle_validation_schema_version"
        ),
    )
    if (
        expected_completion_fingerprint is not None
        and payload.get("completion_audit_fingerprint_sha256")
        != expected_completion_fingerprint
    ):
        errors.append(
            "runtime bundle completion_audit_fingerprint_sha256 must match "
            "canonical completion audit manifest"
        )
    return errors


def _runtime_fingerprint_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    for row in rows:
        fields = set(row)
        missing = sorted(RUNTIME_ROW_REQUIRED_FIELDS - fields)
        extra = sorted(fields - RUNTIME_ROW_ALLOWED_FIELDS)
        if missing:
            errors.append(
                "runtime bundle row JSON missing required field(s): "
                + ", ".join(missing)
            )
        if extra:
            errors.append(
                "runtime bundle row JSON has unsupported field(s): "
                + ", ".join(extra)
            )
        if any(
            not isinstance(row.get(field), str)
            for field in ("requirement_id", "artifact")
        ):
            errors.append(
                "runtime bundle row requirement_id and artifact must be strings"
            )
        for field in ("path", "artifact_sha256", "generated_at"):
            value = row.get(field)
            if value is not None and not isinstance(value, str):
                errors.append(f"runtime bundle row {field} must be a string or null")
        artifact_sha256 = row.get("artifact_sha256")
        if isinstance(artifact_sha256, str) and not FINGERPRINT_RE.match(
            artifact_sha256
        ):
            errors.append(
                "runtime bundle row artifact_sha256 must be a SHA-256 hex string or null"
            )
        checks_passed = row.get("checks_passed")
        if (
            not isinstance(checks_passed, int)
            or isinstance(checks_passed, bool)
            or checks_passed < 0
        ):
            errors.append(
                "runtime bundle row checks_passed must be a non-negative integer"
            )
        max_age_hours = row.get("max_age_hours")
        if (
            max_age_hours is not None
            and (
                not isinstance(max_age_hours, int)
                or isinstance(max_age_hours, bool)
                or max_age_hours < 0
            )
        ):
            errors.append(
                "runtime bundle row max_age_hours must be a non-negative integer or null"
            )
        age_hours = row.get("age_hours")
        if (
            age_hours is not None
            and (
                not isinstance(age_hours, (int, float))
                or isinstance(age_hours, bool)
                or age_hours < 0
            )
        ):
            errors.append(
                "runtime bundle row age_hours must be a non-negative number or null"
            )
        row_errors = row.get("errors")
        if not isinstance(row_errors, list) or not all(
            isinstance(item, str) for item in row_errors
        ):
            errors.append("runtime bundle row errors must be a string list")
        row_error_codes = row.get("error_codes")
        if not isinstance(row_error_codes, list) or not all(
            isinstance(item, str) for item in row_error_codes
        ):
            errors.append("runtime bundle row error_codes must be string lists")
    if errors:
        return errors, []
    return errors, rows


def _runtime_bundle_fingerprint(
    rows: list[dict[str, Any]],
    *,
    bundle_root: str,
    registry_fingerprint_sha256: str,
    schema_version: str,
    validated_at: str,
) -> str:
    manifest = {
        "registry_fingerprint_sha256": registry_fingerprint_sha256,
        "schema_version": schema_version,
        "validated_at": validated_at,
        "artifacts": [
            {
                "requirement_id": row["requirement_id"],
                "artifact": row["artifact"],
                "artifact_sha256": row["artifact_sha256"],
                "errors": row["errors"],
                "error_codes": row["error_codes"],
                "path": _runtime_row_fingerprint_path(
                    bundle_root=bundle_root,
                    path=row["path"],
                ),
                "status": row["status"],
                "checks_passed": row["checks_passed"],
                "generated_at": row["generated_at"],
                "max_age_hours": row["max_age_hours"],
                "age_hours": row["age_hours"],
            }
            for row in rows
        ],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_completion_audit_fingerprint(
    *,
    bundle_fingerprint_sha256: str,
    self_harness_report_bundle_fingerprint_sha256: Any,
    self_harness_report_bundle_validation_schema_version: Any,
) -> str | None:
    if not isinstance(
        self_harness_report_bundle_fingerprint_sha256,
        str,
    ) or not FINGERPRINT_RE.match(self_harness_report_bundle_fingerprint_sha256):
        return None
    if (
        self_harness_report_bundle_validation_schema_version
        != REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
    ):
        return None
    manifest = {
        "runtime_evidence_bundle_fingerprint_sha256": bundle_fingerprint_sha256,
        "self_harness_report_bundle": {
            "bundle_fingerprint_sha256": (
                self_harness_report_bundle_fingerprint_sha256
            ),
            "validation_schema_version": (
                self_harness_report_bundle_validation_schema_version
            ),
        },
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_row_fingerprint_path(*, bundle_root: str, path: Any) -> str | None:
    if path is None:
        return None
    try:
        return Path(Path(path).absolute()).relative_to(
            Path(Path(bundle_root).absolute())
        ).as_posix()
    except ValueError:
        return str(path)


def _runtime_row_summary_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    error_code_counts: dict[str, int] | None,
) -> list[str]:
    errors: list[str] = []
    allowed_statuses = {"passed", "missing", "failed"}
    status_counts = {status: 0 for status in allowed_statuses}
    row_error_code_counts: dict[str, int] = {}
    registered_artifact_counts: dict[str, int] = {}
    registered_requirement_id_counts: dict[str, int] = {}
    registered_row_count = 0
    unexpected_count = 0
    row_statuses_valid = True
    row_error_codes_valid = True
    registered_row_identity_valid = True
    for row in rows:
        status = row.get("status")
        if status not in allowed_statuses:
            row_statuses_valid = False
            errors.append("runtime bundle row status values must be passed, missing, or failed")
        else:
            status_counts[status] += 1
        row_error_codes = row.get("error_codes")
        if not isinstance(row_error_codes, list) or not all(
            isinstance(item, str) for item in row_error_codes
        ):
            row_error_codes_valid = False
            errors.append("runtime bundle row error_codes must be string lists")
            continue
        if len(row_error_codes) != len(set(row_error_codes)):
            row_error_codes_valid = False
            errors.append(
                "runtime bundle row error_codes must not contain duplicate entries"
            )
            continue
        row_errors = row.get("errors")
        if isinstance(row_errors, list) and all(
            isinstance(item, str) for item in row_errors
        ):
            expected_row_error_codes = sorted(
                {runtime_bundle_error_code(error) for error in row_errors}
            )
            if row_error_codes != expected_row_error_codes:
                row_error_codes_valid = False
                errors.append(
                    "runtime bundle row error_codes must match normalized row errors"
                )
                continue
            if status == "passed" and row_errors:
                errors.append("runtime bundle passed rows must not contain errors")
            if status in {"missing", "failed"} and not row_errors:
                errors.append("runtime bundle non-passed rows must contain errors")
        if status == "passed":
            if not (
                isinstance(row.get("path"), str)
                and row["path"]
                and isinstance(row.get("artifact_sha256"), str)
                and FINGERPRINT_RE.match(row["artifact_sha256"])
            ):
                errors.append(
                    "runtime bundle passed rows must carry artifact path and sha256"
                )
            if not (
                isinstance(row.get("generated_at"), str)
                and row["generated_at"]
                and isinstance(row.get("max_age_hours"), int)
                and not isinstance(row["max_age_hours"], bool)
                and row["max_age_hours"] >= 1
                and isinstance(row.get("age_hours"), (int, float))
                and not isinstance(row["age_hours"], bool)
            ):
                errors.append(
                    "runtime bundle passed rows must carry freshness proof fields"
                )
        if status == "missing" and (
            row.get("path") is not None
            or row.get("artifact_sha256") is not None
            or row.get("generated_at") is not None
            or row.get("age_hours") is not None
        ):
            errors.append("runtime bundle missing rows must not carry artifact proof")
        if "unexpected_unregistered_artifact" in row_error_codes:
            unexpected_count += 1
        else:
            registered_row_count += 1
            requirement_id = row.get("requirement_id")
            artifact = row.get("artifact")
            if (
                not isinstance(requirement_id, str)
                or not requirement_id
                or not isinstance(artifact, str)
                or not artifact
            ):
                registered_row_identity_valid = False
                errors.append(
                    "runtime bundle registered row requirement_id and artifact "
                    "must be non-empty"
                )
            else:
                registered_requirement_id_counts[requirement_id] = (
                    registered_requirement_id_counts.get(requirement_id, 0) + 1
                )
                registered_artifact_counts[artifact] = (
                    registered_artifact_counts.get(artifact, 0) + 1
                )
        for error_code in row_error_codes:
            row_error_code_counts[error_code] = (
                row_error_code_counts.get(error_code, 0) + 1
            )
    expected_counts = {
        "passed_count": status_counts["passed"],
        "missing_count": status_counts["missing"],
        "failed_count": status_counts["failed"],
    }
    if row_statuses_valid and any(
        payload.get(field) != expected for field, expected in expected_counts.items()
    ):
        errors.append("runtime bundle status counts must match rows")
    if row_statuses_valid:
        expected_ok = status_counts["missing"] == 0 and status_counts["failed"] == 0
        if payload.get("ok") != expected_ok:
            errors.append("runtime bundle ok must match row status counts")
        expected_completion_audit_ready = expected_ok and _runtime_self_harness_link_present(
            payload
        )
        if payload.get("completion_audit_ready") != expected_completion_audit_ready:
            errors.append(
                "runtime bundle completion_audit_ready must match runtime readiness fields"
            )
    if row_error_codes_valid and payload.get("unexpected_count") != unexpected_count:
        errors.append("runtime bundle unexpected_count must match unexpected rows")
    if row_error_codes_valid and payload.get("requirement_count") != registered_row_count:
        errors.append("runtime bundle requirement_count must match registered rows")
    if row_error_codes_valid and registered_row_identity_valid:
        if any(count > 1 for count in registered_requirement_id_counts.values()):
            errors.append(
                "runtime bundle registered requirement_id values must be unique"
            )
        if any(count > 1 for count in registered_artifact_counts.values()):
            errors.append("runtime bundle registered artifact values must be unique")
    if (
        row_error_codes_valid
        and error_code_counts is not None
        and error_code_counts != row_error_code_counts
    ):
        errors.append("runtime bundle error_code_counts values must match row error_codes")
    return errors


def _runtime_row_freshness_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[str]:
    validated_at = payload.get("validated_at")
    if not isinstance(validated_at, str):
        return []
    try:
        validated_dt = parse_runtime_timestamp(validated_at)
    except ValueError:
        return []
    errors: list[str] = []
    for row in rows:
        generated_at = row.get("generated_at")
        age_hours = row.get("age_hours")
        if generated_at is None:
            if age_hours is not None:
                errors.append(
                    "runtime bundle row age_hours must be null when generated_at is null"
                )
            continue
        if not isinstance(generated_at, str):
            continue
        try:
            generated_dt = parse_runtime_timestamp(generated_at)
        except ValueError:
            errors.append(
                "runtime bundle row generated_at must be ISO-8601 with timezone"
            )
            continue
        if not isinstance(age_hours, (int, float)) or isinstance(age_hours, bool):
            continue
        expected_age_hours = round(
            (validated_dt - generated_dt).total_seconds() / 3600,
            3,
        )
        if abs(float(age_hours) - expected_age_hours) > 0.001:
            errors.append(
                "runtime bundle row age_hours must match generated_at and validated_at"
            )
        row_error_codes = row.get("error_codes")
        if not isinstance(row_error_codes, list) or not all(
            isinstance(item, str) for item in row_error_codes
        ):
            continue
        if expected_age_hours < 0 and "freshness_timestamp_future" not in row_error_codes:
            errors.append(
                "runtime bundle future generated_at rows must carry "
                "freshness_timestamp_future"
            )
        max_age_hours = row.get("max_age_hours")
        if (
            isinstance(max_age_hours, int)
            and not isinstance(max_age_hours, bool)
            and expected_age_hours > max_age_hours
            and "freshness_stale" not in row_error_codes
        ):
            errors.append(
                "runtime bundle stale rows must carry freshness_stale"
            )
    return errors


def _runtime_row_path_errors(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[str]:
    bundle_root = payload.get("bundle_root")
    if not isinstance(bundle_root, str) or not bundle_root:
        return []
    errors: list[str] = []
    bundle_root_path = Path(bundle_root).absolute()
    for row in rows:
        path = row.get("path")
        if path is None:
            continue
        if not isinstance(path, str) or not path:
            continue
        artifact = row.get("artifact")
        if isinstance(artifact, str) and artifact and Path(path).name != artifact:
            errors.append("runtime bundle row path basename must match artifact")
        try:
            Path(path).absolute().relative_to(bundle_root_path)
        except ValueError:
            errors.append("runtime bundle row path must stay inside bundle_root")
    return errors


def _runtime_self_harness_link_present(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("self_harness_report_bundle_root"), str)
        and bool(payload["self_harness_report_bundle_root"])
        and isinstance(payload.get("self_harness_report_bundle_fingerprint_sha256"), str)
        and bool(
            FINGERPRINT_RE.match(
                payload["self_harness_report_bundle_fingerprint_sha256"]
            )
        )
        and payload.get("self_harness_report_bundle_validation_schema_version")
        == REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION
    )


def _cross_report_errors(
    *,
    handoff_payload: dict[str, Any] | None,
    runtime_payload: dict[str, Any] | None,
    bundle_root: Path,
) -> list[str]:
    if handoff_payload is None or runtime_payload is None:
        return []
    errors: list[str] = []
    nested = handoff_payload.get("runtime_evidence_bundle_report")
    if nested != runtime_payload:
        errors.append("handoff nested runtime evidence bundle report must match runtime JSON report")
    expected_runtime_blockers = _runtime_blockers_from_payload(runtime_payload)
    if (
        expected_runtime_blockers is not None
        and handoff_payload.get("runtime_blockers") != expected_runtime_blockers
    ):
        errors.append("handoff runtime_blockers must match runtime report")
    expected_release_blockers = _release_blockers_from_payload(
        runtime_blockers=expected_runtime_blockers,
        runtime_payload=runtime_payload,
        handoff_payload=handoff_payload,
    )
    if (
        expected_release_blockers is not None
        and handoff_payload.get("release_blockers") != expected_release_blockers
    ):
        errors.append(
            "handoff release_blockers must match runtime and setup summaries"
        )
    if (
        expected_release_blockers is not None
        and handoff_payload.get("release_blocker_count")
        != len(expected_release_blockers)
    ):
        errors.append("handoff release_blocker_count must match release_blockers")
    if handoff_payload.get("ok") != handoff_payload.get("release_handoff_ready"):
        errors.append("handoff ok must match release_handoff_ready")
    expected_release_ready = _expected_release_handoff_ready(
        handoff_payload,
        runtime_payload,
    )
    if (
        expected_release_ready is not None
        and handoff_payload.get("release_handoff_ready") != expected_release_ready
    ):
        errors.append(
            "handoff release_handoff_ready must match runtime and setup summaries"
        )
    if handoff_payload.get("completion_audit_ready") != runtime_payload.get(
        "completion_audit_ready"
    ):
        errors.append("handoff completion_audit_ready must match runtime report")
    if handoff_payload.get("completion_audit_fingerprint_sha256") != runtime_payload.get(
        "completion_audit_fingerprint_sha256"
    ):
        errors.append("handoff completion_audit_fingerprint_sha256 must match runtime report")
    if handoff_payload.get("runtime_evidence_bundle_fingerprint_sha256") != (
        runtime_payload.get("bundle_fingerprint_sha256")
    ):
        errors.append("handoff runtime_evidence_bundle_fingerprint_sha256 must match runtime report")
    if handoff_payload.get("self_harness_report_bundle_fingerprint_sha256") != (
        runtime_payload.get("self_harness_report_bundle_fingerprint_sha256")
    ):
        errors.append("handoff self_harness_report_bundle_fingerprint_sha256 must match runtime report")
    if handoff_payload.get("artifact_bundle_root") != runtime_payload.get("bundle_root"):
        errors.append("handoff artifact_bundle_root must match runtime bundle_root")
    if handoff_payload.get("self_harness_report_bundle_root") != (
        runtime_payload.get("self_harness_report_bundle_root")
    ):
        errors.append("handoff self_harness_report_bundle_root must match runtime report")
    errors.extend(
        _handoff_markdown_consistency_errors(
            handoff_payload=handoff_payload,
            bundle_root=bundle_root,
        )
    )
    errors.extend(
        _runtime_markdown_consistency_errors(
            runtime_payload=runtime_payload,
            bundle_root=bundle_root,
        )
    )
    return errors


def _runtime_blockers_from_payload(
    runtime_payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    rows = runtime_payload.get("rows")
    if not isinstance(rows, list):
        return None
    blockers: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        status = row.get("status")
        if status == "passed":
            continue
        if status not in {"missing", "failed"}:
            return None
        requirement_id = row.get("requirement_id")
        artifact = row.get("artifact")
        error_codes = row.get("error_codes")
        if (
            not isinstance(requirement_id, str)
            or not isinstance(artifact, str)
            or not _is_unique_string_list(error_codes)
        ):
            return None
        blockers.append(
            {
                "requirement_id": requirement_id,
                "artifact": artifact,
                "status": status,
                "error_codes": list(error_codes),
            }
        )
    return blockers


def _release_blockers_from_payload(
    *,
    runtime_blockers: list[dict[str, Any]] | None,
    runtime_payload: dict[str, Any],
    handoff_payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if runtime_blockers is None:
        return None
    recovery_actions = _readiness_recovery_actions_by_requirement(
        handoff_payload.get("readiness_summary")
    )
    blockers: list[dict[str, Any]] = [
        {
            "kind": "runtime_evidence",
            "requirement_id": item["requirement_id"],
            "artifact": item["artifact"],
            "status": item["status"],
            "error_codes": list(item["error_codes"]),
            "recovery_action": recovery_actions.get(item["requirement_id"]),
        }
        for item in runtime_blockers
    ]
    runtime_ready = runtime_payload.get("completion_audit_ready")
    runtime_error_codes = runtime_payload.get("error_codes")
    if not isinstance(runtime_ready, bool) or not _is_unique_string_list(
        runtime_error_codes
    ):
        return None
    if not runtime_ready and not runtime_blockers:
        blockers.append(
            {
                "kind": "runtime_readiness",
                "blocker_id": "completion_audit_ready",
                "status": "blocked",
                "error_codes": list(runtime_error_codes),
            }
        )
    control_summary = handoff_payload.get("control_chain_summary")
    if isinstance(control_summary, dict):
        error_codes = control_summary.get("error_codes")
        control_values = {
            "ok": control_summary.get("ok"),
            "control_chain_ready": control_summary.get("control_chain_ready"),
            "dispatch_ready": control_summary.get("dispatch_ready"),
        }
        if not _is_unique_string_list(error_codes) or not all(
            isinstance(value, bool) for value in control_values.values()
        ):
            return None
        for field in ("ok", "control_chain_ready", "dispatch_ready"):
            if control_values[field] is not True:
                blockers.append(
                    {
                        "kind": "control_chain",
                        "blocker_id": "control_chain_ok"
                        if field == "ok"
                        else field,
                        "status": "blocked",
                        "error_codes": list(error_codes),
                    }
                )
    elif control_summary is not None:
        return None
    setup_summary = handoff_payload.get("setup_gap_summary")
    if isinstance(setup_summary, dict):
        blocked_requirements = setup_summary.get("blocked_requirements")
        setup_ok = setup_summary.get("ok")
        setup_consistent = setup_summary.get("setup_diagnostics_consistent")
        summary_pending_count = setup_summary.get("pending_setup_check_count")
        summary_mismatch_count = setup_summary.get(
            "diagnostic_present_setup_mismatch_count"
        )
        if not isinstance(blocked_requirements, list):
            return None
        if (
            not isinstance(setup_ok, bool)
            or not isinstance(setup_consistent, bool)
            or not isinstance(summary_pending_count, int)
            or isinstance(summary_pending_count, bool)
            or summary_pending_count < 0
            or not isinstance(summary_mismatch_count, int)
            or isinstance(summary_mismatch_count, bool)
            or summary_mismatch_count < 0
        ):
            return None
        setup_requirement_blockers = 0
        for item in blocked_requirements:
            if not isinstance(item, dict):
                return None
            requirement_id = item.get("requirement_id")
            pending_count = item.get("pending_setup_check_count")
            diagnostic_keys = item.get("diagnostic_pending_setup_keys")
            non_diagnostic_keys = item.get("non_diagnostic_pending_setup_keys")
            resolution_actions = item.get("resolution_actions")
            if (
                not isinstance(requirement_id, str)
                or not requirement_id
                or not isinstance(pending_count, int)
                or isinstance(pending_count, bool)
                or pending_count <= 0
                or not _is_unique_string_list(diagnostic_keys)
                or not _is_unique_string_list(non_diagnostic_keys)
                or not isinstance(resolution_actions, list)
            ):
                return None
            setup_requirement_blockers += 1
            blockers.append(
                {
                    "kind": "setup_gap",
                    "requirement_id": requirement_id,
                    "pending_setup_check_count": pending_count,
                    "diagnostic_pending_setup_keys": list(diagnostic_keys),
                    "non_diagnostic_pending_setup_keys": list(non_diagnostic_keys),
                    "resolution_actions": [
                        dict(action)
                        for action in resolution_actions
                        if isinstance(action, dict)
                    ],
                }
            )
        if setup_ok is not True:
            blockers.append(
                _setup_gap_summary_blocker_from_payload(
                    pending_count=summary_pending_count,
                    mismatch_count=summary_mismatch_count,
                    blocker_id="setup_gap_ok",
                )
            )
        if summary_mismatch_count > 0 or setup_consistent is not True:
            blockers.append(
                _setup_gap_summary_blocker_from_payload(
                    pending_count=summary_pending_count,
                    mismatch_count=summary_mismatch_count,
                    blocker_id="setup_diagnostic_mismatch",
                )
            )
        if summary_pending_count > 0 and setup_requirement_blockers == 0:
            blockers.append(
                _setup_gap_summary_blocker_from_payload(
                    pending_count=summary_pending_count,
                    mismatch_count=summary_mismatch_count,
                    blocker_id="pending_setup_checks",
                )
            )
    elif setup_summary is not None:
        return None
    return blockers


def _readiness_recovery_actions_by_requirement(
    summary: Any,
) -> dict[str, dict[str, Any]]:
    if not isinstance(summary, dict):
        return {}
    actions = summary.get("scoped_next_actions")
    if not isinstance(actions, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        requirement_id = action.get("requirement_id")
        if isinstance(requirement_id, str) and requirement_id:
            result[requirement_id] = dict(action)
    return result


def _setup_gap_summary_blocker_from_payload(
    *,
    pending_count: int,
    mismatch_count: int,
    blocker_id: str,
) -> dict[str, Any]:
    return {
        "kind": "setup_gap_summary",
        "blocker_id": blocker_id,
        "status": "blocked",
        "pending_setup_check_count": pending_count,
        "diagnostic_present_setup_mismatch_count": mismatch_count,
    }


def _expected_release_handoff_ready(
    handoff_payload: dict[str, Any],
    runtime_payload: dict[str, Any],
) -> bool | None:
    runtime_ready = runtime_payload.get("completion_audit_ready")
    if not isinstance(runtime_ready, bool):
        return None
    ready = runtime_ready
    control_summary = handoff_payload.get("control_chain_summary")
    if isinstance(control_summary, dict):
        control_values = (
            control_summary.get("ok"),
            control_summary.get("control_chain_ready"),
            control_summary.get("dispatch_ready"),
        )
        if not all(isinstance(value, bool) for value in control_values):
            return None
        ready = ready and all(control_values)
    elif control_summary is not None:
        return None
    setup_summary = handoff_payload.get("setup_gap_summary")
    if isinstance(setup_summary, dict):
        setup_ok = setup_summary.get("ok")
        diagnostics_consistent = setup_summary.get("setup_diagnostics_consistent")
        pending_count = setup_summary.get("pending_setup_check_count")
        mismatch_count = setup_summary.get("diagnostic_present_setup_mismatch_count")
        if (
            not isinstance(setup_ok, bool)
            or not isinstance(diagnostics_consistent, bool)
            or not isinstance(pending_count, int)
            or isinstance(pending_count, bool)
            or not isinstance(mismatch_count, int)
            or isinstance(mismatch_count, bool)
        ):
            return None
        ready = (
            ready
            and setup_ok
            and diagnostics_consistent
            and pending_count == 0
            and mismatch_count == 0
        )
    elif setup_summary is not None:
        return None
    return ready


def _markdown_report_errors(*, report_name: str, text: str) -> list[str]:
    errors: list[str] = []
    if report_name == HANDOFF_MARKDOWN_REPORT:
        required_tokens = (
            "# Wiii Completion Audit Handoff",
            "Completion audit fingerprint SHA-256",
            "Release handoff ready",
            "Release blocker count",
            "Release blockers",
            "Runtime evidence bundle fingerprint SHA-256",
            "Self-harness report bundle fingerprint SHA-256",
            "Runtime blocker count",
            "Runtime blockers",
            "Readiness report",
            "Control chain report",
            "Setup gap report",
            "Reports:",
        )
    elif report_name == RUNTIME_BUNDLE_MARKDOWN_REPORT:
        required_tokens = (
            "# Wiii Runtime Evidence Bundle",
            "Completion audit fingerprint SHA-256",
            "Completion audit ready",
            "Error codes:",
        )
    else:
        required_tokens = ()
    for token in required_tokens:
        if token not in text:
            errors.append(f"{report_name} missing markdown token {token!r}")
    return errors


def _handoff_markdown_consistency_errors(
    *,
    handoff_payload: dict[str, Any],
    bundle_root: Path,
) -> list[str]:
    markdown_path = bundle_root / HANDOFF_MARKDOWN_REPORT
    if not markdown_path.is_file() or markdown_path.is_symlink():
        return []
    text = markdown_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if text.splitlines() != _expected_handoff_markdown_document_lines(
        handoff_payload
    ):
        errors.append("handoff markdown document must exactly match handoff JSON")
    rendered_lines = set(text.splitlines())
    for line in _expected_handoff_markdown_lines(handoff_payload):
        if line not in rendered_lines:
            errors.append(f"handoff markdown line mismatch: {line}")
    return errors


def _runtime_markdown_consistency_errors(
    *,
    runtime_payload: dict[str, Any],
    bundle_root: Path,
) -> list[str]:
    markdown_path = bundle_root / RUNTIME_BUNDLE_MARKDOWN_REPORT
    if not markdown_path.is_file() or markdown_path.is_symlink():
        return []
    text = markdown_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if text.splitlines() != _expected_runtime_markdown_document_lines(
        runtime_payload
    ):
        errors.append("runtime markdown document must exactly match runtime JSON")
    rendered_lines = set(text.splitlines())
    for line in _expected_runtime_markdown_lines(runtime_payload):
        if line not in rendered_lines:
            errors.append(f"runtime markdown line mismatch: {line}")
    runtime_rows = runtime_payload.get("rows")
    if isinstance(runtime_rows, list):
        markdown_rows = _runtime_markdown_data_rows(text)
        if len(markdown_rows) != len(runtime_rows):
            errors.append(
                "runtime markdown table row count must match runtime report rows"
            )
        else:
            expected_rows = _expected_runtime_markdown_row_lines(runtime_rows)
            if len(expected_rows) == len(runtime_rows):
                markdown_row_set = set(markdown_rows)
                for requirement_id, artifact, expected_line in expected_rows:
                    if expected_line not in markdown_row_set:
                        errors.append(
                            "runtime markdown table row mismatch for "
                            f"{requirement_id}/{artifact}"
                        )
    return errors


def _expected_handoff_markdown_document_lines(payload: dict[str, Any]) -> list[str]:
    return [
        "# Wiii Completion Audit Handoff",
        "",
        *_expected_handoff_markdown_lines(payload),
    ]


def _expected_runtime_markdown_document_lines(payload: dict[str, Any]) -> list[str]:
    runtime_rows = payload.get("rows")
    row_lines = [
        line for _requirement_id, _artifact, line in _expected_runtime_markdown_row_lines(
            runtime_rows
        )
    ]
    return [
        "# Wiii Runtime Evidence Bundle",
        "",
        *_expected_runtime_markdown_lines(payload),
        "",
        "| Requirement | Artifact | SHA-256 | Status | Checks | Freshness | Path | Error codes | Errors |",
        "|---|---|---|---|---:|---|---|---|---|",
        *row_lines,
    ]


def _expected_handoff_markdown_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    _append_markdown_value_line(
        lines,
        "Schema version",
        payload.get("schema_version"),
    )
    ok = payload.get("ok")
    if isinstance(ok, bool):
        _append_markdown_value_line(lines, "Status", "PASS" if ok else "FAIL")
    completion_ready = payload.get("completion_audit_ready")
    if isinstance(completion_ready, bool):
        _append_markdown_value_line(
            lines,
            "Completion audit ready",
            str(completion_ready).lower(),
        )
    release_ready = payload.get("release_handoff_ready")
    if isinstance(release_ready, bool):
        _append_markdown_value_line(
            lines,
            "Release handoff ready",
            str(release_ready).lower(),
        )
    if _is_non_negative_int(payload.get("release_blocker_count")):
        _append_markdown_value_line(
            lines,
            "Release blocker count",
            payload.get("release_blocker_count"),
        )
    release_blockers = payload.get("release_blockers")
    if isinstance(release_blockers, list):
        _append_markdown_value_line(
            lines,
            "Release blockers",
            _format_release_blockers(release_blockers) or "-",
        )
    _append_markdown_value_line(
        lines,
        "Completion audit fingerprint SHA-256",
        payload.get("completion_audit_fingerprint_sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Runtime evidence bundle fingerprint SHA-256",
        payload.get("runtime_evidence_bundle_fingerprint_sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Self-harness report bundle fingerprint SHA-256",
        payload.get("self_harness_report_bundle_fingerprint_sha256"),
    )
    _append_markdown_value_line(lines, "Handoff root", payload.get("handoff_root"))
    _append_markdown_value_line(
        lines,
        "Artifact bundle root",
        payload.get("artifact_bundle_root"),
    )
    _append_markdown_value_line(
        lines,
        "Self-harness report bundle root",
        payload.get("self_harness_report_bundle_root"),
    )
    runtime_payload = payload.get("runtime_evidence_bundle_report")
    if isinstance(runtime_payload, dict):
        _append_markdown_value_line(
            lines,
            "Runtime requirements",
            runtime_payload.get("requirement_count"),
        )
        _append_markdown_value_line(
            lines,
            "Runtime passed",
            runtime_payload.get("passed_count"),
        )
        _append_markdown_value_line(
            lines,
            "Runtime missing",
            runtime_payload.get("missing_count"),
        )
        _append_markdown_value_line(
            lines,
            "Runtime failed",
            runtime_payload.get("failed_count"),
        )
        _append_markdown_value_line(
            lines,
            "Runtime error codes",
            _format_markdown_error_codes(runtime_payload.get("error_codes")),
        )
    lines.extend(_expected_readiness_summary_markdown_lines(payload))
    runtime_blockers = payload.get("runtime_blockers")
    if isinstance(runtime_blockers, list):
        _append_markdown_value_line(
            lines,
            "Runtime blocker count",
            len(runtime_blockers),
        )
        _append_markdown_value_line(
            lines,
            "Runtime blockers",
            _format_runtime_blockers(runtime_blockers) or "-",
        )
    lines.extend(_expected_control_chain_summary_markdown_lines(payload))
    lines.extend(_expected_setup_gap_summary_markdown_lines(payload))
    reports = payload.get("reports")
    if isinstance(reports, list) and all(isinstance(report, str) for report in reports):
        _append_markdown_value_line(lines, "Reports", ", ".join(reports))
    return lines


def _expected_readiness_summary_markdown_lines(
    payload: dict[str, Any],
) -> list[str]:
    summary = payload.get("readiness_summary")
    if summary is None:
        return ["- Readiness report: `-`"]
    if not isinstance(summary, dict):
        return []
    lines: list[str] = []
    _append_markdown_value_line(lines, "Readiness report", summary.get("path"))
    _append_markdown_value_line(
        lines,
        "Readiness report SHA-256",
        summary.get("sha256"),
    )
    ready = summary.get("scoped_completion_audit_ready")
    if isinstance(ready, bool):
        _append_markdown_value_line(
            lines,
            "Readiness scoped completion audit ready",
            str(ready).lower(),
        )
    _append_markdown_value_line(
        lines,
        "Readiness scoped next actions",
        summary.get("scoped_next_action_count"),
    )
    _append_markdown_value_line(
        lines,
        "Readiness scoped next-actions SHA-256",
        summary.get("scoped_next_actions_fingerprint_sha256"),
    )
    return lines


def _expected_control_chain_summary_markdown_lines(
    payload: dict[str, Any],
) -> list[str]:
    summary = payload.get("control_chain_summary")
    if summary is None:
        return ["- Control chain report: `-`"]
    if not isinstance(summary, dict):
        return []
    lines: list[str] = []
    _append_markdown_value_line(lines, "Control chain report", summary.get("path"))
    _append_markdown_value_line(
        lines,
        "Control chain report SHA-256",
        summary.get("sha256"),
    )
    for label, field in (
        ("Control chain ok", "ok"),
        ("Control chain ready", "control_chain_ready"),
        ("Dispatch ready", "dispatch_ready"),
    ):
        value = summary.get(field)
        if isinstance(value, bool):
            _append_markdown_value_line(lines, label, str(value).lower())
    _append_markdown_value_line(
        lines,
        "Control chain error codes",
        _format_markdown_error_codes(summary.get("error_codes")),
    )
    return lines


def _expected_setup_gap_summary_markdown_lines(
    payload: dict[str, Any],
) -> list[str]:
    summary = payload.get("setup_gap_summary")
    if summary is None:
        return ["- Setup gap report: `-`"]
    if not isinstance(summary, dict):
        return []
    lines: list[str] = []
    _append_markdown_value_line(lines, "Setup gap report", summary.get("path"))
    _append_markdown_value_line(
        lines,
        "Setup gap report SHA-256",
        summary.get("sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Setup gap Markdown report",
        _markdown_optional_value(summary.get("markdown_path")),
    )
    _append_markdown_value_line(
        lines,
        "Setup gap Markdown SHA-256",
        _markdown_optional_value(summary.get("markdown_sha256")),
    )
    setup_consistent = summary.get("setup_diagnostics_consistent")
    if isinstance(setup_consistent, bool):
        _append_markdown_value_line(
            lines,
            "Setup diagnostics consistent",
            str(setup_consistent).lower(),
        )
    for label, field in (
        ("Blocked requirements", "blocked_requirement_count"),
        ("Pending setup checks", "pending_setup_check_count"),
        (
            "Diagnostic pending setup checks",
            "diagnostic_pending_setup_check_count",
        ),
        (
            "Non-diagnostic pending setup checks",
            "non_diagnostic_pending_setup_check_count",
        ),
        (
            "Diagnostic present setup mismatches",
            "diagnostic_present_setup_mismatch_count",
        ),
    ):
        _append_markdown_value_line(lines, label, summary.get(field))
    blocked_requirements = summary.get("blocked_requirements")
    if isinstance(blocked_requirements, list):
        _append_markdown_value_line(
            lines,
            "Setup gap diagnostic keys",
            ", ".join(
                _flatten_summary_keys(
                    blocked_requirements,
                    "diagnostic_pending_setup_keys",
                )
            )
            or "-",
        )
        _append_markdown_value_line(
            lines,
            "Setup gap non-diagnostic keys",
            ", ".join(
                _flatten_summary_keys(
                    blocked_requirements,
                    "non_diagnostic_pending_setup_keys",
                )
            )
            or "-",
        )
    return lines


def _expected_runtime_markdown_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    _append_markdown_value_line(lines, "Schema version", payload.get("schema_version"))
    _append_markdown_value_line(lines, "Registry name", payload.get("registry_name"))
    _append_markdown_value_line(
        lines,
        "Registry version",
        payload.get("registry_version"),
    )
    _append_markdown_value_line(lines, "Bundle root", payload.get("bundle_root"))
    _append_markdown_value_line(lines, "Validated at", payload.get("validated_at"))
    _append_markdown_value_line(
        lines,
        "Registry fingerprint SHA-256",
        payload.get("registry_fingerprint_sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Bundle fingerprint SHA-256",
        payload.get("bundle_fingerprint_sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Completion audit fingerprint SHA-256",
        payload.get("completion_audit_fingerprint_sha256"),
    )
    _append_markdown_value_line(
        lines,
        "Self-harness report bundle",
        _markdown_optional_value(payload.get("self_harness_report_bundle_root")),
    )
    _append_markdown_value_line(
        lines,
        "Self-harness report bundle fingerprint SHA-256",
        _markdown_optional_value(
            payload.get("self_harness_report_bundle_fingerprint_sha256")
        ),
    )
    _append_markdown_value_line(
        lines,
        "Self-harness report bundle validation schema",
        _markdown_optional_value(
            payload.get("self_harness_report_bundle_validation_schema_version")
        ),
    )
    completion_ready = payload.get("completion_audit_ready")
    if isinstance(completion_ready, bool):
        _append_markdown_value_line(
            lines,
            "Completion audit ready",
            str(completion_ready).lower(),
        )
    ok = payload.get("ok")
    if isinstance(ok, bool):
        _append_markdown_value_line(lines, "Status", "PASS" if ok else "FAIL")
    for label, field in (
        ("Requirements", "requirement_count"),
        ("Rows", "row_count"),
        ("Passed", "passed_count"),
        ("Missing", "missing_count"),
        ("Failed", "failed_count"),
        ("Unexpected", "unexpected_count"),
    ):
        _append_markdown_value_line(lines, label, payload.get(field))
    _append_markdown_value_line(
        lines,
        "Error codes",
        _format_markdown_error_codes(payload.get("error_codes")),
    )
    _append_markdown_value_line(
        lines,
        "Error code counts",
        _format_markdown_error_code_counts(payload.get("error_code_counts")),
    )
    return lines


def _append_markdown_value_line(lines: list[str], label: str, value: Any) -> None:
    if isinstance(value, bool):
        value = str(value).lower()
    if isinstance(value, (str, int)):
        lines.append(f"- {label}: `{value}`")


def _markdown_optional_value(value: Any) -> Any:
    if value is None:
        return "-"
    if isinstance(value, str) and not value:
        return "-"
    return value


def _format_markdown_error_codes(value: Any) -> str | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return ", ".join(value) or "-"


def _format_markdown_error_code_counts(value: Any) -> str | None:
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        for key, count in value.items()
    ):
        return None
    if not value:
        return "-"
    return ", ".join(f"{key}={count}" for key, count in sorted(value.items()))


def _runtime_markdown_data_rows(markdown: str) -> list[str]:
    rows: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("|---|"):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.strip():
            break
        if line.startswith("| "):
            rows.append(line)
    return rows


def _expected_runtime_markdown_row_lines(value: Any) -> list[tuple[str, str, str]]:
    if not isinstance(value, list):
        return []
    expected_rows: list[tuple[str, str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            return []
        line = _expected_runtime_markdown_row_line(row)
        requirement_id = row.get("requirement_id")
        artifact = row.get("artifact")
        if line is None:
            return []
        if isinstance(requirement_id, str) and isinstance(artifact, str):
            expected_rows.append((requirement_id, artifact, line))
    return expected_rows


def _expected_runtime_markdown_row_line(row: dict[str, Any]) -> str | None:
    if any(
        not isinstance(row.get(field), str)
        for field in ("requirement_id", "artifact", "status")
    ):
        return None
    checks_passed = row.get("checks_passed")
    if (
        not isinstance(checks_passed, int)
        or isinstance(checks_passed, bool)
        or checks_passed < 0
    ):
        return None
    for field in ("path", "artifact_sha256", "generated_at"):
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            return None
    max_age_hours = row.get("max_age_hours")
    if max_age_hours is not None and (
        not isinstance(max_age_hours, int)
        or isinstance(max_age_hours, bool)
        or max_age_hours < 0
    ):
        return None
    age_hours = row.get("age_hours")
    if age_hours is not None and (
        not isinstance(age_hours, (int, float))
        or isinstance(age_hours, bool)
        or age_hours < 0
    ):
        return None
    errors = row.get("errors")
    error_codes = row.get("error_codes")
    if not isinstance(errors, list) or not all(
        isinstance(item, str) for item in errors
    ):
        return None
    if not isinstance(error_codes, list) or not all(
        isinstance(item, str) for item in error_codes
    ):
        return None
    cells = [
        _markdown_table_cell(row["requirement_id"]),
        _markdown_table_cell(row["artifact"]),
        _markdown_table_cell(row.get("artifact_sha256") or ""),
        _markdown_table_cell(row["status"]),
        str(checks_passed),
        _markdown_table_cell(_runtime_freshness_cell(row)),
        _markdown_table_cell(row.get("path") or ""),
        _markdown_table_cell(", ".join(error_codes)),
        _markdown_table_cell("; ".join(errors)),
    ]
    return "| " + " | ".join(cells) + " |"


def _runtime_freshness_cell(row: dict[str, Any]) -> str:
    if row.get("generated_at") is None:
        return "-"
    age_hours = row.get("age_hours")
    max_age_hours = row.get("max_age_hours")
    age = "-" if age_hours is None else f"{age_hours:.2f}h"
    max_age = "-" if max_age_hours is None else f"{max_age_hours}h"
    return f"{age} / {max_age}"


def _markdown_table_cell(value: str) -> str:
    normalized = " ".join(value.replace("|", "\\|").split())
    return normalized or "-"


def _unexpected_report_rows(bundle_root: Path) -> list[HandoffValidationRow]:
    rows: list[HandoffValidationRow] = []
    for path in sorted(bundle_root.iterdir(), key=lambda item: item.name):
        if path.name in EXPECTED_REPORT_NAMES:
            continue
        if path.is_symlink():
            error = f"unexpected handoff report symlink {path.name!r}"
            report_sha256 = None
        elif path.is_dir():
            error = f"unexpected handoff report directory {path.name!r}"
            report_sha256 = None
        elif path.is_file():
            error = f"unexpected handoff report file {path.name!r}"
            report_sha256 = _sha256_file(path)
        else:
            error = f"unexpected handoff report entry {path.name!r}"
            report_sha256 = None
        rows.append(
            HandoffValidationRow(
                file_name=path.name,
                status="failed",
                report_sha256=report_sha256,
                errors=[error],
            )
        )
    return rows


def format_summary(result: HandoffValidationResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"Wiii Completion Audit Handoff Bundle: {status}",
        f"validation_schema: {result.validation_schema_version}",
        "require_completion_audit_ready: "
        f"{str(result.require_completion_audit_ready).lower()}",
        f"bundle_root: {result.bundle_root}",
        f"bundle_fingerprint_sha256: {result.bundle_fingerprint_sha256}",
        f"completion_audit_ready: {result.completion_audit_ready}",
        f"release_handoff_ready: {result.release_handoff_ready}",
        f"reports: {result.report_count}",
        f"passed: {result.passed_count}",
        f"failed: {result.failed_count}",
        f"unexpected: {result.unexpected_count}",
        "error_codes: " + (", ".join(result.error_code_counts) or "-"),
    ]
    for row in result.rows:
        if row.status == "failed":
            lines.append(f"- {row.file_name}: " + "; ".join(row.errors))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate downloaded Wiii completion-audit handoff artifacts.",
    )
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--require-completion-audit-ready",
        action="store_true",
        help="Fail unless the validated handoff reports completion_audit_ready=true.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_report_output_path(bundle_root=args.bundle_root, out_path=args.out)
        result = validate_handoff_bundle(
            args.bundle_root,
            require_completion_audit_ready=args.require_completion_audit_ready,
        )
    except Exception as exc:  # noqa: BLE001
        if args.json:
            print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        else:
            print(f"Wiii Completion Audit Handoff Bundle: FAIL\n- {exc}", file=sys.stderr)
        return 1
    rendered = (
        json.dumps(result.to_dict(), indent=2, sort_keys=True)
        if args.json
        else format_summary(result)
    )
    if args.out is not None:
        try:
            safe_write_report_text(args.out, rendered + "\n")
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        print(rendered)
    return 0 if result.ok else 1


def validate_report_output_path(*, bundle_root: Path, out_path: Path | None) -> None:
    if out_path is None:
        return
    if _path_is_inside_directory(
        path=out_path,
        directory=bundle_root,
        resolve_symlinks=False,
    ) or _path_is_inside_directory(
        path=out_path,
        directory=bundle_root,
        resolve_symlinks=True,
    ):
        raise ValueError("completion audit handoff validation output path must be outside bundle root")
    if out_path.exists() and out_path.is_dir():
        raise ValueError(HANDOFF_REPORT_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(HANDOFF_REPORT_OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_path):
        raise ValueError(HANDOFF_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _json_error_payload(error: str) -> dict[str, Any]:
    error_code = _error_code(error)
    return {
        "validation_schema_version": HANDOFF_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def _bundle_fingerprint(
    rows: list[HandoffValidationRow],
    *,
    validation_schema_version: str,
    require_completion_audit_ready: bool,
) -> str:
    manifest = {
        "validation_schema_version": validation_schema_version,
        "require_completion_audit_ready": require_completion_audit_ready,
        "rows": [
            {
                "file_name": row.file_name,
                "report_sha256": row.report_sha256,
                "status": row.status,
                "errors": row.errors,
                "error_codes": _row_error_codes(row),
            }
            for row in rows
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


def _row_error_codes(row: HandoffValidationRow) -> list[str]:
    return sorted({_error_code(error) for error in row.errors})


def _error_code_counts(rows: list[HandoffValidationRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for code in _row_error_codes(row):
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith("completion audit handoff bundle root does not exist:"):
        return "handoff_bundle_root_missing"
    if error.startswith("completion audit handoff bundle root must not be a symlink:"):
        return "handoff_bundle_root_symlink"
    if error.startswith("completion audit handoff bundle root must be a directory:"):
        return "handoff_bundle_root_not_directory"
    if error == "completion audit handoff validation output path must be outside bundle root":
        return "handoff_validation_output_path_inside_bundle_root"
    if error == HANDOFF_REPORT_OUTPUT_PATH_DIRECTORY_ERROR:
        return "handoff_validation_output_path_directory"
    if error == HANDOFF_REPORT_OUTPUT_PATH_SYMLINK_ERROR:
        return "handoff_validation_output_path_symlink"
    if error == HANDOFF_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "handoff_validation_output_path_parent_symlink"
    if error.startswith("missing handoff report file "):
        return "handoff_report_file_missing"
    if error.startswith("handoff report file must not be a symlink:"):
        return "handoff_report_file_symlink"
    if error.startswith("handoff report path must be a file:"):
        return "handoff_report_path_not_file"
    if error.startswith("handoff report JSON is invalid:"):
        return "handoff_report_json_invalid"
    if error == "handoff report JSON root must be an object":
        return "handoff_report_json_root_not_object"
    if error.startswith("handoff JSON missing required field(s):"):
        return "handoff_json_missing_required_fields"
    if error.startswith("handoff JSON has unsupported field(s):"):
        return "handoff_json_unsupported_fields"
    if error.startswith("handoff schema_version must be "):
        return "handoff_schema_mismatch"
    if error.startswith("handoff ") and error.endswith(" must be a boolean"):
        return "handoff_boolean_field_invalid"
    if error.startswith("handoff ") and error.endswith(" must be a SHA-256 hex string"):
        return "handoff_fingerprint_field_invalid"
    if error.startswith("handoff ") and error.endswith(" must be a non-empty string"):
        return "handoff_string_field_invalid"
    if error == "handoff reports must match expected generated reports":
        return "handoff_reports_mismatch"
    if error == "handoff runtime_evidence_bundle_report must be an object":
        return "handoff_runtime_report_not_object"
    if error == "handoff release_blockers must match runtime and setup summaries":
        return "handoff_release_blockers_mismatch"
    if error == "handoff release_blocker_count must match release_blockers":
        return "handoff_release_blockers_mismatch"
    if error == "handoff release_blockers must be a list":
        return "handoff_release_blockers_invalid"
    if error.startswith("handoff release_blocker"):
        return "handoff_release_blockers_invalid"
    if error == "handoff runtime_blockers must match runtime report":
        return "handoff_runtime_blockers_mismatch"
    if error.startswith("handoff runtime_blocker"):
        return "handoff_runtime_blockers_invalid"
    if error == "handoff runtime_blockers must be a list":
        return "handoff_runtime_blockers_invalid"
    if error == "handoff readiness_summary must be an object or null":
        return "handoff_readiness_summary_invalid"
    if error.startswith("handoff readiness_summary "):
        return "handoff_readiness_summary_invalid"
    if error == "handoff control_chain_summary must be an object or null":
        return "handoff_control_chain_summary_invalid"
    if error.startswith("handoff control_chain_summary "):
        return "handoff_control_chain_summary_invalid"
    if error == "handoff setup_gap_summary must be an object or null":
        return "handoff_setup_gap_summary_invalid"
    if error.startswith("handoff setup_gap_summary "):
        return "handoff_setup_gap_summary_invalid"
    if error.startswith("runtime bundle JSON missing required field(s):"):
        return "runtime_bundle_json_missing_required_fields"
    if error.startswith("runtime bundle JSON has unsupported field(s):"):
        return "runtime_bundle_json_unsupported_fields"
    if error.startswith("runtime bundle schema_version must be "):
        return "runtime_bundle_schema_mismatch"
    if error.startswith("runtime bundle registry_name must be "):
        return "runtime_bundle_registry_name_mismatch"
    if error == "runtime bundle registry_version must be an integer >= 1":
        return "runtime_bundle_registry_version_invalid"
    if error == "runtime bundle validated_at must be a normalized UTC timestamp":
        return "runtime_bundle_validated_at_invalid"
    if error.startswith(
        "runtime bundle self_harness_report_bundle_validation_schema_version must be "
    ):
        return "runtime_bundle_self_harness_validation_schema_mismatch"
    if error.startswith("runtime bundle ") and error.endswith(" must be a boolean"):
        return "runtime_bundle_boolean_field_invalid"
    if error.startswith("runtime bundle ") and error.endswith(" must be a SHA-256 hex string"):
        return "runtime_bundle_fingerprint_field_invalid"
    if error.startswith("runtime bundle ") and error.endswith(" must be a non-empty string"):
        return "runtime_bundle_string_field_invalid"
    if error.startswith("runtime bundle ") and error.endswith(" must be a non-negative integer"):
        return "runtime_bundle_integer_field_invalid"
    if error == "runtime bundle error_codes must be a string list":
        return "runtime_bundle_error_codes_invalid"
    if error == "runtime bundle error_codes must not contain duplicate entries":
        return "runtime_bundle_error_codes_duplicate"
    if error == "runtime bundle rows must be a list":
        return "runtime_bundle_rows_invalid"
    if error == "runtime bundle row_count must match rows length":
        return "runtime_bundle_row_count_mismatch"
    if error == "runtime bundle row entries must be objects":
        return "runtime_bundle_row_entries_invalid"
    if error.startswith("runtime bundle row JSON missing required field(s):"):
        return "runtime_bundle_row_json_missing_required_fields"
    if error.startswith("runtime bundle row JSON has unsupported field(s):"):
        return "runtime_bundle_row_json_unsupported_fields"
    if error == "runtime bundle row requirement_id and artifact must be strings":
        return "runtime_bundle_row_identity_fields_invalid"
    if error.startswith("runtime bundle row ") and error.endswith(
        " must be a string or null"
    ):
        return "runtime_bundle_row_nullable_string_field_invalid"
    if error == "runtime bundle row artifact_sha256 must be a SHA-256 hex string or null":
        return "runtime_bundle_row_artifact_fingerprint_invalid"
    if error == "runtime bundle row checks_passed must be a non-negative integer":
        return "runtime_bundle_row_checks_passed_invalid"
    if error == "runtime bundle row max_age_hours must be a non-negative integer or null":
        return "runtime_bundle_row_max_age_hours_invalid"
    if error == "runtime bundle row age_hours must be a non-negative number or null":
        return "runtime_bundle_row_age_hours_invalid"
    if error == "runtime bundle row errors must be a string list":
        return "runtime_bundle_row_errors_invalid"
    if error == "runtime bundle row status values must be passed, missing, or failed":
        return "runtime_bundle_row_status_invalid"
    if error == "runtime bundle row error_codes must be string lists":
        return "runtime_bundle_row_error_codes_invalid"
    if error == "runtime bundle row error_codes must not contain duplicate entries":
        return "runtime_bundle_row_error_codes_duplicate"
    if error == "runtime bundle row error_codes must match normalized row errors":
        return "runtime_bundle_row_error_codes_mismatch"
    if error == "runtime bundle passed rows must not contain errors":
        return "runtime_bundle_passed_row_errors_present"
    if error == "runtime bundle non-passed rows must contain errors":
        return "runtime_bundle_non_passed_row_errors_missing"
    if error == "runtime bundle passed rows must carry artifact path and sha256":
        return "runtime_bundle_passed_row_artifact_proof_missing"
    if error == "runtime bundle passed rows must carry freshness proof fields":
        return "runtime_bundle_passed_row_freshness_proof_missing"
    if error == "runtime bundle missing rows must not carry artifact proof":
        return "runtime_bundle_missing_row_artifact_proof_present"
    if error == "runtime bundle status counts must match rows":
        return "runtime_bundle_status_counts_mismatch"
    if error == "runtime bundle ok must match row status counts":
        return "runtime_bundle_ok_mismatch"
    if error == "runtime bundle completion_audit_ready must match runtime readiness fields":
        return "runtime_bundle_completion_audit_ready_mismatch"
    if error == "runtime bundle unexpected_count must match unexpected rows":
        return "runtime_bundle_unexpected_count_mismatch"
    if error == "runtime bundle requirement_count must match registered rows":
        return "runtime_bundle_requirement_count_mismatch"
    if (
        error == "runtime bundle registered row requirement_id and artifact "
        "must be non-empty"
    ):
        return "runtime_bundle_registered_row_identity_empty"
    if error == "runtime bundle registered requirement_id values must be unique":
        return "runtime_bundle_registered_requirement_id_duplicate"
    if error == "runtime bundle registered artifact values must be unique":
        return "runtime_bundle_registered_artifact_duplicate"
    if error == "runtime bundle error_code_counts values must match row error_codes":
        return "runtime_bundle_error_code_counts_value_mismatch"
    if (
        error
        == "runtime bundle row age_hours must be null when generated_at is null"
    ):
        return "runtime_bundle_row_age_hours_null_mismatch"
    if error == "runtime bundle row generated_at must be ISO-8601 with timezone":
        return "runtime_bundle_row_generated_at_invalid"
    if (
        error
        == "runtime bundle row age_hours must match generated_at and validated_at"
    ):
        return "runtime_bundle_row_age_hours_mismatch"
    if (
        error
        == "runtime bundle future generated_at rows must carry "
        "freshness_timestamp_future"
    ):
        return "runtime_bundle_future_freshness_code_missing"
    if error == "runtime bundle stale rows must carry freshness_stale":
        return "runtime_bundle_stale_freshness_code_missing"
    if error == "runtime bundle row path basename must match artifact":
        return "runtime_bundle_row_path_artifact_mismatch"
    if error == "runtime bundle row path must stay inside bundle_root":
        return "runtime_bundle_row_path_outside_bundle_root"
    if (
        error
        == "runtime bundle bundle_fingerprint_sha256 must match canonical row manifest"
    ):
        return "runtime_bundle_canonical_fingerprint_mismatch"
    if (
        error
        == "runtime bundle completion_audit_fingerprint_sha256 must match "
        "canonical completion audit manifest"
    ):
        return "runtime_bundle_completion_audit_fingerprint_mismatch"
    if error == "runtime bundle error_code_counts must be a string-to-int map":
        return "runtime_bundle_error_code_counts_invalid"
    if error == "runtime bundle error_code_counts keys must match error_codes":
        return "runtime_bundle_error_code_counts_key_mismatch"
    if (
        error
        == "runtime bundle error_code_counts values must be positive for listed error codes"
    ):
        return "runtime_bundle_error_code_counts_non_positive"
    if error == "handoff nested runtime evidence bundle report must match runtime JSON report":
        return "handoff_nested_runtime_report_mismatch"
    if error == "handoff ok must match release_handoff_ready":
        return "handoff_ok_mismatch"
    if (
        error
        == "handoff release_handoff_ready must match runtime and setup summaries"
    ):
        return "handoff_release_ready_mismatch"
    if error == "handoff completion_audit_ready must match runtime report":
        return "handoff_completion_audit_ready_mismatch"
    if error == "completion audit handoff is not ready":
        return "handoff_completion_audit_not_ready"
    if error == "handoff completion_audit_fingerprint_sha256 must match runtime report":
        return "handoff_completion_audit_fingerprint_mismatch"
    if error == "handoff runtime_evidence_bundle_fingerprint_sha256 must match runtime report":
        return "handoff_runtime_bundle_fingerprint_mismatch"
    if error == "handoff self_harness_report_bundle_fingerprint_sha256 must match runtime report":
        return "handoff_self_harness_bundle_fingerprint_mismatch"
    if error == "handoff artifact_bundle_root must match runtime bundle_root":
        return "handoff_artifact_bundle_root_mismatch"
    if error == "handoff self_harness_report_bundle_root must match runtime report":
        return "handoff_self_harness_bundle_root_mismatch"
    if "missing markdown token" in error:
        return "handoff_markdown_token_missing"
    if error.startswith("handoff markdown line mismatch:"):
        return "handoff_markdown_value_mismatch"
    if error == "handoff markdown document must exactly match handoff JSON":
        return "handoff_markdown_document_mismatch"
    if error.startswith("runtime markdown line mismatch:"):
        return "runtime_markdown_value_mismatch"
    if error == "runtime markdown document must exactly match runtime JSON":
        return "runtime_markdown_document_mismatch"
    if error == "runtime markdown table row count must match runtime report rows":
        return "runtime_markdown_row_count_mismatch"
    if error.startswith("runtime markdown table row mismatch for "):
        return "runtime_markdown_row_mismatch"
    if error.startswith("unexpected handoff report file "):
        return "unexpected_handoff_report_file"
    if error.startswith("unexpected handoff report directory "):
        return "unexpected_handoff_report_directory"
    if error.startswith("unexpected handoff report symlink "):
        return "unexpected_handoff_report_symlink"
    if error.startswith("unexpected handoff report entry "):
        return "unexpected_handoff_report_entry"
    return "handoff_validation_error"


def _string_field(payload: dict[str, Any] | None, field: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(field)
    return value if isinstance(value, str) else None


def _path_is_inside_directory(
    *,
    path: Path,
    directory: Path,
    resolve_symlinks: bool,
) -> bool:
    try:
        resolved_path = path.resolve(strict=False) if resolve_symlinks else path.absolute()
        resolved_directory = (
            directory.resolve(strict=False) if resolve_symlinks else directory.absolute()
        )
        resolved_path.relative_to(resolved_directory)
    except ValueError:
        return False
    return True


def _path_has_symlink_parent(path: Path) -> bool:
    for parent in path.parents:
        if parent.is_symlink():
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
