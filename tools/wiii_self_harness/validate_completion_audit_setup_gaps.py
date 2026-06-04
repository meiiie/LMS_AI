#!/usr/bin/env python3
"""Validate completion-audit setup gap reports."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from report_completion_audit_setup_gaps import (  # noqa: E402
    SETUP_GAP_REPORT_SCHEMA_VERSION,
    _report_fingerprint,
    _sha256_file,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_handle_plan as plan_validator  # noqa: E402


SETUP_GAP_REPORT_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_gap_report_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_handle_plan_path",
    "setup_handle_plan_sha256",
    "setup_handle_plan_schema_version",
    "setup_handle_plan_fingerprint_sha256",
    "setup_gap_report_fingerprint_sha256",
    "requirement_count",
    "blocked_requirement_count",
    "pending_setup_check_count",
    "diagnostic_pending_setup_check_count",
    "non_diagnostic_pending_setup_check_count",
    "diagnostic_requirement_count",
    "diagnostic_present_setup_mismatch_count",
    "setup_diagnostics_consistent",
    "requirements",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
REQUIREMENT_FIELDS = {
    "requirement_id",
    "title",
    "setup_status",
    "dispatch_ready",
    "pending_setup_check_count",
    "diagnostic_pending_setup_check_count",
    "non_diagnostic_pending_setup_check_count",
    "diagnostic_pending_setup_keys",
    "non_diagnostic_pending_setup_keys",
    "ready_setup_check_count",
    "pending_setup_checks",
    "diagnostic_available",
    "diagnostic_artifact",
    "diagnostic_artifact_sha256",
    "diagnostic_status",
    "diagnostic_schema_version",
    "diagnostic_preflight_schema_version",
    "diagnostic_setup_contract_dispatch_ready",
    "diagnostic_required_next",
    "diagnostic_required_next_mapped_checks",
    "diagnostic_present_setup_mismatches",
    "diagnostic_unmapped_required_next",
}
PENDING_CHECK_FIELDS = {
    "category",
    "key",
    "present",
    "evidence_kind",
    "binding_token_count",
    "source_handle_present",
    "source_handle_options",
    "attestation_option_count",
}
MAPPING_FIELDS = {"required_next", "category", "key", "present"}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}


@dataclass(frozen=True)
class SetupGapReportValidationResult:
    validation_schema_version: str
    setup_gap_report_path: str
    setup_handle_plan_path: str | None
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


def validate_setup_gap_report(
    setup_gap_report_path: Path,
    *,
    setup_handle_plan_path: Path | None = None,
    markdown_report_path: Path | None = None,
) -> SetupGapReportValidationResult:
    errors: list[str] = []
    payload = _load_payload(setup_gap_report_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if setup_handle_plan_path is not None:
            errors.extend(
                _source_errors(payload, setup_handle_plan_path=setup_handle_plan_path)
            )
        if markdown_report_path is not None:
            errors.extend(_markdown_errors(payload, markdown_report_path))
    return SetupGapReportValidationResult(
        validation_schema_version=SETUP_GAP_REPORT_VALIDATION_SCHEMA_VERSION,
        setup_gap_report_path=str(setup_gap_report_path),
        setup_handle_plan_path=(
            str(setup_handle_plan_path) if setup_handle_plan_path else None
        ),
        markdown_report_path=str(markdown_report_path) if markdown_report_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup gap report path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup gap report JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup gap report root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "setup gap report missing required field(s): " + ", ".join(missing)
        )
    if extra:
        errors.append(
            "setup gap report has unsupported field(s): " + ", ".join(extra)
        )
    if payload.get("schema_version") != SETUP_GAP_REPORT_SCHEMA_VERSION:
        errors.append(
            f"setup gap report schema_version must be {SETUP_GAP_REPORT_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("setup gap report ok must be true")
    for field in (
        "setup_handle_plan_path",
        "setup_handle_plan_schema_version",
        "setup_handle_plan_fingerprint_sha256",
        "setup_gap_report_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"setup gap report {field} must be a non-empty string")
    for field in (
        "setup_handle_plan_sha256",
        "setup_handle_plan_fingerprint_sha256",
        "setup_gap_report_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"setup gap report {field} must be a SHA-256 hex string")
    for field in (
        "requirement_count",
        "blocked_requirement_count",
        "pending_setup_check_count",
        "diagnostic_requirement_count",
        "diagnostic_present_setup_mismatch_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"setup gap report {field} must be a non-negative integer")
    if not isinstance(payload.get("setup_diagnostics_consistent"), bool):
        errors.append("setup gap report setup_diagnostics_consistent must be a boolean")
    requirement_errors, requirements = _requirement_errors(payload.get("requirements"))
    errors.extend(requirement_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not requirement_errors:
        errors.extend(_summary_errors(payload, requirements))
    return errors


def _requirement_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    requirements: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup gap report requirements must be a non-empty list"], requirements
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            errors.append("setup gap report requirement entries must be objects")
            continue
        requirements.append(item)
        if set(item) != REQUIREMENT_FIELDS:
            errors.append("setup gap report requirement fields must match contract")
        requirement_id = item.get("requirement_id")
        if not isinstance(requirement_id, str) or not requirement_id:
            errors.append("setup gap report requirement_id must be a non-empty string")
        elif requirement_id in seen_ids:
            errors.append("setup gap report requirement_id values must be unique")
        else:
            seen_ids.add(requirement_id)
        for field in ("title", "setup_status"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"setup gap report requirement {field} must be non-empty")
        if item.get("setup_status") not in {"pending", "ready"}:
            errors.append("setup gap report requirement setup_status must be pending or ready")
        for field in ("dispatch_ready", "diagnostic_available"):
            if not isinstance(item.get(field), bool):
                errors.append(f"setup gap report requirement {field} must be a boolean")
        for field in (
            "pending_setup_check_count",
            "diagnostic_pending_setup_check_count",
            "non_diagnostic_pending_setup_check_count",
            "ready_setup_check_count",
        ):
            if not _is_non_negative_int(item.get(field)):
                errors.append(
                    f"setup gap report requirement {field} must be a non-negative integer"
                )
        pending_errors, pending_checks = _pending_check_errors(
            item.get("pending_setup_checks")
        )
        errors.extend(pending_errors)
        for field in (
            "diagnostic_artifact",
            "diagnostic_artifact_sha256",
            "diagnostic_status",
            "diagnostic_schema_version",
            "diagnostic_preflight_schema_version",
        ):
            if not isinstance(item.get(field), str):
                errors.append(f"setup gap report requirement {field} must be a string")
        if item.get("diagnostic_available") is True:
            if not item.get("diagnostic_artifact"):
                errors.append(
                    "setup gap report diagnostic_available requires diagnostic_artifact"
                )
            if not _is_fingerprint(item.get("diagnostic_artifact_sha256")):
                errors.append(
                    "setup gap report diagnostic_available requires diagnostic artifact SHA-256"
                )
            for field in ("diagnostic_status", "diagnostic_schema_version"):
                if not item.get(field):
                    errors.append(
                        f"setup gap report diagnostic_available requires {field}"
                    )
        if not isinstance(item.get("diagnostic_setup_contract_dispatch_ready"), bool):
            errors.append(
                "setup gap report diagnostic_setup_contract_dispatch_ready must be a boolean"
            )
        for field in ("diagnostic_required_next", "diagnostic_unmapped_required_next"):
            if not _is_unique_string_list(item.get(field)):
                errors.append(f"setup gap report requirement {field} must be a unique string list")
        for field in (
            "diagnostic_pending_setup_keys",
            "non_diagnostic_pending_setup_keys",
        ):
            if not _is_unique_string_list(item.get(field)):
                errors.append(
                    f"setup gap report requirement {field} must be a unique string list"
                )
        mapped_errors, mapped = _mapping_errors(
            item.get("diagnostic_required_next_mapped_checks")
        )
        errors.extend(mapped_errors)
        mismatch_errors, mismatches = _mapping_errors(
            item.get("diagnostic_present_setup_mismatches")
        )
        errors.extend(mismatch_errors)
        if not pending_errors and item.get("pending_setup_check_count") != len(
            pending_checks
        ):
            errors.append(
                "setup gap report pending_setup_check_count must match pending checks"
            )
        if not pending_errors and not mapped_errors:
            diagnostic_pending_keys = {
                (str(mapping.get("category") or ""), str(mapping.get("key") or ""))
                for mapping in mapped
                if mapping.get("present") is False
            }
            diagnostic_pending_key_list = _setup_key_list(diagnostic_pending_keys)
            non_diagnostic_pending_key_list = _setup_key_list(
                {
                    (str(check.get("category") or ""), str(check.get("key") or ""))
                    for check in pending_checks
                    if (
                        str(check.get("category") or ""),
                        str(check.get("key") or ""),
                    )
                    not in diagnostic_pending_keys
                }
            )
            if item.get("diagnostic_pending_setup_check_count") != len(
                diagnostic_pending_key_list
            ):
                errors.append(
                    "setup gap report diagnostic_pending_setup_check_count must match diagnostic mappings"
                )
            if item.get("non_diagnostic_pending_setup_check_count") != (
                len(non_diagnostic_pending_key_list)
            ):
                errors.append(
                    "setup gap report non_diagnostic_pending_setup_check_count must match pending checks"
                )
            if item.get("diagnostic_pending_setup_keys") != diagnostic_pending_key_list:
                errors.append(
                    "setup gap report diagnostic_pending_setup_keys must match diagnostic mappings"
                )
            if (
                item.get("non_diagnostic_pending_setup_keys")
                != non_diagnostic_pending_key_list
            ):
                errors.append(
                    "setup gap report non_diagnostic_pending_setup_keys must match pending checks"
                )
        if not mapped_errors and not mismatch_errors:
            errors.extend(_diagnostic_mapping_consistency_errors(item, mapped, mismatches))
    return errors, requirements


def _pending_check_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["setup gap report pending_setup_checks must be a list"], checks
    for check in value:
        if not isinstance(check, dict):
            errors.append("setup gap report pending check entries must be objects")
            continue
        checks.append(check)
        if set(check) != PENDING_CHECK_FIELDS:
            errors.append("setup gap report pending check fields must match contract")
        for field in ("category", "key", "evidence_kind"):
            if not isinstance(check.get(field), str):
                errors.append(f"setup gap report pending check {field} must be a string")
        if check.get("present") is not False:
            errors.append("setup gap report pending check present must be false")
        if not _is_non_negative_int(check.get("binding_token_count")):
            errors.append(
                "setup gap report pending check binding_token_count must be non-negative"
            )
        if not isinstance(check.get("source_handle_present"), bool):
            errors.append(
                "setup gap report pending check source_handle_present must be boolean"
            )
        if check.get("source_handle_present") is not False:
            errors.append(
                "setup gap report pending check source_handle_present must be false"
            )
        if not _is_string_list(check.get("source_handle_options")):
            errors.append(
                "setup gap report pending check source_handle_options must be a string list"
            )
        if not _is_non_negative_int(check.get("attestation_option_count")):
            errors.append(
                "setup gap report pending check attestation_option_count must be non-negative"
            )
    return errors, checks


def _mapping_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    mappings: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["setup gap report diagnostic mappings must be a list"], mappings
    for mapping in value:
        if not isinstance(mapping, dict):
            errors.append("setup gap report diagnostic mapping entries must be objects")
            continue
        mappings.append(mapping)
        if set(mapping) != MAPPING_FIELDS:
            errors.append("setup gap report diagnostic mapping fields must match contract")
        for field in ("required_next", "category", "key"):
            if not isinstance(mapping.get(field), str) or not mapping.get(field):
                errors.append(f"setup gap report diagnostic mapping {field} must be non-empty")
        if not isinstance(mapping.get("present"), bool):
            errors.append("setup gap report diagnostic mapping present must be boolean")
    return errors, mappings


def _diagnostic_mapping_consistency_errors(
    item: dict[str, Any],
    mapped: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    required_next = item.get("diagnostic_required_next")
    if not isinstance(required_next, list):
        return errors
    mapped_tokens = {
        mapping.get("required_next")
        for mapping in mapped
        if isinstance(mapping.get("required_next"), str)
    }
    expected_unmapped = sorted(
        token for token in required_next if token not in mapped_tokens
    )
    if sorted(item.get("diagnostic_unmapped_required_next") or []) != expected_unmapped:
        errors.append(
            "setup gap report diagnostic_unmapped_required_next must match mappings"
        )
    expected_mismatches = [
        mapping for mapping in mapped if mapping.get("present") is True
    ]
    if sorted(_mapping_key(mapping) for mapping in mismatches) != sorted(
        _mapping_key(mapping) for mapping in expected_mismatches
    ):
        errors.append(
            "setup gap report diagnostic_present_setup_mismatches must match present mappings"
        )
    return errors


def _setup_key_list(keys: set[tuple[str, str]]) -> list[str]:
    return sorted(f"{category}:{key}" for category, key in keys if category and key)


def _summary_errors(
    payload: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    blocked = sum(1 for item in requirements if item.get("dispatch_ready") is not True)
    pending_checks = sum(
        int(item.get("pending_setup_check_count") or 0) for item in requirements
    )
    diagnostic_pending_checks = sum(
        int(item.get("diagnostic_pending_setup_check_count") or 0)
        for item in requirements
    )
    non_diagnostic_pending_checks = sum(
        int(item.get("non_diagnostic_pending_setup_check_count") or 0)
        for item in requirements
    )
    diagnostic_count = sum(
        1 for item in requirements if item.get("diagnostic_available") is True
    )
    mismatch_count = sum(
        len(item.get("diagnostic_present_setup_mismatches") or [])
        for item in requirements
    )
    if payload.get("requirement_count") != len(requirements):
        errors.append("setup gap report requirement_count must match requirements")
    if payload.get("blocked_requirement_count") != blocked:
        errors.append("setup gap report blocked_requirement_count must match requirements")
    if payload.get("pending_setup_check_count") != pending_checks:
        errors.append("setup gap report pending_setup_check_count must match requirements")
    if payload.get("diagnostic_pending_setup_check_count") != diagnostic_pending_checks:
        errors.append(
            "setup gap report diagnostic_pending_setup_check_count must match requirements"
        )
    if (
        payload.get("non_diagnostic_pending_setup_check_count")
        != non_diagnostic_pending_checks
    ):
        errors.append(
            "setup gap report non_diagnostic_pending_setup_check_count must match requirements"
        )
    if diagnostic_pending_checks + non_diagnostic_pending_checks != pending_checks:
        errors.append(
            "setup gap report diagnostic and non-diagnostic pending counts must sum to pending_setup_check_count"
        )
    if payload.get("diagnostic_requirement_count") != diagnostic_count:
        errors.append("setup gap report diagnostic_requirement_count must match requirements")
    if payload.get("diagnostic_present_setup_mismatch_count") != mismatch_count:
        errors.append(
            "setup gap report diagnostic_present_setup_mismatch_count must match requirements"
        )
    if payload.get("setup_diagnostics_consistent") != (mismatch_count == 0):
        errors.append(
            "setup gap report setup_diagnostics_consistent must match mismatch count"
        )
    if mismatch_count:
        errors.append(
            "setup gap report setup_diagnostics_consistent must be true; "
            "resolve diagnostic_present_setup_mismatches before control-chain validation"
        )
    if payload.get("setup_gap_report_fingerprint_sha256") != _report_fingerprint(
        requirements
    ):
        errors.append("setup gap report fingerprint must match requirements")
    return errors


def _source_errors(
    payload: dict[str, Any],
    *,
    setup_handle_plan_path: Path,
) -> list[str]:
    errors: list[str] = []
    validation = plan_validator.validate_setup_handle_plan(setup_handle_plan_path)
    if not validation.ok:
        return [
            "setup gap report setup-handle plan source failed validation: "
            + "; ".join(validation.errors)
        ]
    try:
        plan_payload = load_strict_json_file(setup_handle_plan_path)
    except Exception as exc:  # noqa: BLE001
        return [f"setup gap report setup-handle plan source JSON invalid: {exc}"]
    if not isinstance(plan_payload, dict):
        return ["setup gap report setup-handle plan source root must be an object"]
    if payload.get("setup_handle_plan_sha256") != _sha256_file(setup_handle_plan_path):
        errors.append("setup gap report setup_handle_plan_sha256 must match source")
    if payload.get("setup_handle_plan_schema_version") != plan_payload.get(
        "schema_version"
    ):
        errors.append(
            "setup gap report setup_handle_plan_schema_version must match source"
        )
    if payload.get("setup_handle_plan_fingerprint_sha256") != plan_payload.get(
        "setup_handle_plan_fingerprint_sha256"
    ):
        errors.append(
            "setup gap report setup_handle_plan_fingerprint_sha256 must match source"
        )
    plan_items = [
        item for item in plan_payload.get("plan_items", []) if isinstance(item, dict)
    ]
    by_id = {str(item.get("requirement_id") or ""): item for item in plan_items}
    requirements = [
        item for item in payload.get("requirements", []) if isinstance(item, dict)
    ]
    if set(by_id) != {str(item.get("requirement_id") or "") for item in requirements}:
        errors.append("setup gap report requirement ids must match setup-handle plan")
        return errors
    for item in requirements:
        plan_item = by_id[str(item.get("requirement_id") or "")]
        errors.extend(_requirement_source_errors(item, plan_item))
    return errors


def _requirement_source_errors(
    item: dict[str, Any],
    plan_item: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in ("title", "setup_status", "dispatch_ready"):
        if item.get(field) != plan_item.get(field):
            errors.append(f"setup gap report requirement {field} must match source")
    checks = [
        check
        for check in plan_item.get("setup_checks", [])
        if isinstance(check, dict)
    ]
    pending = [check for check in checks if check.get("present") is not True]
    ready_count = sum(1 for check in checks if check.get("present") is True)
    if item.get("pending_setup_check_count") != len(pending):
        errors.append(
            "setup gap report requirement pending_setup_check_count must match source"
        )
    if item.get("ready_setup_check_count") != ready_count:
        errors.append(
            "setup gap report requirement ready_setup_check_count must match source"
        )
    expected_pending_keys = sorted(
        (str(check.get("category") or ""), str(check.get("key") or ""))
        for check in pending
    )
    actual_pending_keys = sorted(
        (str(check.get("category") or ""), str(check.get("key") or ""))
        for check in item.get("pending_setup_checks", [])
        if isinstance(check, dict)
    )
    if actual_pending_keys != expected_pending_keys:
        errors.append(
            "setup gap report pending_setup_checks must match source pending checks"
        )
    return errors


def _markdown_errors(payload: dict[str, Any], markdown_report_path: Path) -> list[str]:
    if not markdown_report_path.is_file() or markdown_report_path.is_symlink():
        return ["setup gap report markdown path must be a regular file"]
    try:
        text = markdown_report_path.read_text(encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        return [f"setup gap report markdown could not be read: {exc}"]
    errors: list[str] = []
    required_lines = [
        "# Wiii Completion Audit Setup Gap Report",
        "- setup_diagnostics_consistent: "
        + str(payload.get("setup_diagnostics_consistent")).lower(),
        f"- blocked_requirement_count: {payload.get('blocked_requirement_count')}",
        f"- pending_setup_check_count: {payload.get('pending_setup_check_count')}",
        "- diagnostic_pending_setup_check_count: "
        f"{payload.get('diagnostic_pending_setup_check_count')}",
        "- non_diagnostic_pending_setup_check_count: "
        f"{payload.get('non_diagnostic_pending_setup_check_count')}",
        "- diagnostic_present_setup_mismatch_count: "
        f"{payload.get('diagnostic_present_setup_mismatch_count')}",
    ]
    for line in required_lines:
        if line not in text:
            errors.append("setup gap report markdown summary must match JSON")
            break
    for item in payload.get("requirements", []):
        if not isinstance(item, dict):
            continue
        for line in _requirement_markdown_lines(item):
            if line not in text:
                errors.append("setup gap report markdown requirements must match JSON")
                return errors
    return errors


def _requirement_markdown_lines(item: dict[str, Any]) -> list[str]:
    required_next = item.get("diagnostic_required_next")
    if not isinstance(required_next, list):
        required_next = []
    diagnostic_pending_keys = item.get("diagnostic_pending_setup_keys")
    if not isinstance(diagnostic_pending_keys, list):
        diagnostic_pending_keys = []
    non_diagnostic_pending_keys = item.get("non_diagnostic_pending_setup_keys")
    if not isinstance(non_diagnostic_pending_keys, list):
        non_diagnostic_pending_keys = []
    mismatches = item.get("diagnostic_present_setup_mismatches")
    if not isinstance(mismatches, list):
        mismatches = []
    mismatch_text = ", ".join(
        f"{mapping.get('required_next')}->{mapping.get('category')}:{mapping.get('key')}"
        for mapping in mismatches
        if isinstance(mapping, dict)
    )
    return [
        f"## {item.get('requirement_id')}",
        f"- dispatch_ready: {str(item.get('dispatch_ready')).lower()}",
        f"- pending_setup_check_count: {item.get('pending_setup_check_count')}",
        "- diagnostic_pending_setup_check_count: "
        f"{item.get('diagnostic_pending_setup_check_count')}",
        "- diagnostic_pending_setup_keys: "
        + (", ".join(diagnostic_pending_keys) or "none"),
        "- non_diagnostic_pending_setup_check_count: "
        f"{item.get('non_diagnostic_pending_setup_check_count')}",
        "- non_diagnostic_pending_setup_keys: "
        + (", ".join(non_diagnostic_pending_keys) or "none"),
        f"- diagnostic_status: {item.get('diagnostic_status') or 'missing'}",
        "- diagnostic_required_next: " + (", ".join(required_next) or "none"),
        "- diagnostic_present_setup_mismatches: " + (mismatch_text or "none"),
    ]


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup gap report privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("setup gap report privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup gap report privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    raw_errors = payload.get("errors")
    if not isinstance(raw_errors, list) or not all(
        isinstance(item, str) for item in raw_errors
    ):
        errors.append("setup gap report errors must be a string list")
        raw_errors = []
    expected_codes = _error_codes(raw_errors)
    if payload.get("error_codes") != expected_codes:
        errors.append("setup gap report error_codes must match errors")
    if payload.get("error_code_counts") != _error_code_counts(raw_errors):
        errors.append("setup gap report error_code_counts must match errors")
    if payload.get("ok") is True and raw_errors:
        errors.append("setup gap report successful report must not contain errors")
    return errors


def _mapping_key(mapping: dict[str, Any]) -> tuple[str, str, str, bool]:
    return (
        str(mapping.get("required_next") or ""),
        str(mapping.get("category") or ""),
        str(mapping.get("key") or ""),
        mapping.get("present") is True,
    )


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and bool(FINGERPRINT_RE.match(value))


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_unique_string_list(value: Any) -> bool:
    return _is_string_list(value) and len(value) == len(set(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate completion-audit setup gap reports.",
    )
    parser.add_argument("setup_gap_report", type=Path)
    parser.add_argument("--setup-handle-plan", type=Path, default=None)
    parser.add_argument("--markdown-report", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_gap_report(
        args.setup_gap_report,
        setup_handle_plan_path=args.setup_handle_plan,
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
        print("Wiii Completion Audit Setup Gap Report Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Gap Report Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "JSON is invalid" in error:
        return "completion_audit_setup_gap_report_json_invalid"
    if "root must be an object" in error:
        return "completion_audit_setup_gap_report_root_invalid"
    if "path must be a regular file" in error:
        return "completion_audit_setup_gap_report_path_invalid"
    if "markdown" in error:
        return "completion_audit_setup_gap_report_markdown_mismatch"
    if "source failed validation" in error:
        return "completion_audit_setup_gap_report_source_invalid"
    if "must match source" in error or "must match setup-handle plan" in error:
        return "completion_audit_setup_gap_report_source_mismatch"
    if "fingerprint" in error:
        return "completion_audit_setup_gap_report_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_setup_gap_report_privacy_invalid"
    if "setup_diagnostics_consistent must be true" in error:
        return "completion_audit_setup_gap_report_diagnostic_inconsistent"
    if "count" in error:
        return "completion_audit_setup_gap_report_count_invalid"
    if "mapping" in error or "unmapped" in error or "mismatch" in error:
        return "completion_audit_setup_gap_report_mapping_invalid"
    if "requirement" in error or "pending check" in error:
        return "completion_audit_setup_gap_report_requirement_invalid"
    if "field" in error or "schema_version" in error or "ok must be true" in error:
        return "completion_audit_setup_gap_report_contract_invalid"
    return "completion_audit_setup_gap_report_validation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
