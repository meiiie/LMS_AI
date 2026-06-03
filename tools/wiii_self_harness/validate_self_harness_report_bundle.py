#!/usr/bin/env python3
"""Validate downloaded Wiii Self-Harness report artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402
from report_runtime_evidence_coverage import (  # noqa: E402
    COVERAGE_REPORT_SCHEMA_VERSION,
    CREDENTIALED_EXTERNAL_FLAGS,
    SYNTHETIC_EXTERNAL_GAP_FLAGS,
)
from run_wiii_self_harness import (  # noqa: E402
    DEFAULT_MANIFEST,
    HARNESS_VALIDATION_SCHEMA_VERSION,
    _manifest_fingerprint,
    load_manifest,
)
from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    REGISTRY_VALIDATION_SCHEMA_VERSION,
    _registry_fingerprint,
    load_registry,
)
from strict_json import loads_strict_json  # noqa: E402


REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION = "wiii.self_harness_report_bundle_validation.v1"
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
SELF_VALIDATION_REPORT_NAME = "self-harness-report-bundle-validation.json"
REPORT_OUTPUT_PATH_DIRECTORY_ERROR = "bundle report output path must not be a directory"
REPORT_OUTPUT_PATH_SYMLINK_ERROR = "bundle report output path must not be a symlink"
REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "bundle report output path parent must not be a symlink"
)

EXPECTED_JSON_REPORTS = {
    "self-harness-validation.json": {
        "schema_field": "validation_schema_version",
        "schema_version": HARNESS_VALIDATION_SCHEMA_VERSION,
        "required_fields": {
            "ok",
            "error_codes",
            "error_code_counts",
            "manifest_version",
            "manifest_fingerprint_sha256",
        },
        "allowed_fields": {
            "validation_schema_version",
            "harness",
            "manifest_version",
            "manifest_path",
            "manifest_fingerprint_sha256",
            "scenario_count",
            "evidence_count",
            "passed_checks",
            "warnings",
            "errors",
            "ok",
            "error_codes",
            "error_code_counts",
        },
        "fingerprint_fields": {"manifest_fingerprint_sha256"},
        "version_fields": {"manifest_version"},
    },
    "runtime-evidence-registry-validation.json": {
        "schema_field": "validation_schema_version",
        "schema_version": REGISTRY_VALIDATION_SCHEMA_VERSION,
        "required_fields": {
            "ok",
            "error_codes",
            "error_code_counts",
            "registry_version",
            "registry_fingerprint_sha256",
        },
        "allowed_fields": {
            "validation_schema_version",
            "registry",
            "registry_version",
            "registry_path",
            "registry_fingerprint_sha256",
            "requirement_count",
            "passed_checks",
            "errors",
            "ok",
            "error_codes",
            "error_code_counts",
        },
        "fingerprint_fields": {"registry_fingerprint_sha256"},
        "version_fields": {"registry_version"},
    },
    "runtime-evidence-coverage.json": {
        "schema_field": "schema_version",
        "schema_version": COVERAGE_REPORT_SCHEMA_VERSION,
        "required_fields": {
            "ok",
            "error_codes",
            "error_code_counts",
            "validation_error_codes",
            "coverage_error_codes",
            "registry_version",
            "registry_fingerprint_sha256",
            "synthetic_external_gap_count",
            "credentialed_external_count",
            "local_or_backend_count",
        },
        "allowed_fields": {
            "schema_version",
            "registry_name",
            "registry_version",
            "registry_path",
            "registry_fingerprint_sha256",
            "ok",
            "error_codes",
            "error_code_counts",
            "validation_errors",
            "validation_error_codes",
            "coverage_errors",
            "coverage_error_codes",
            "requirement_count",
            "synthetic_external_gap_count",
            "credentialed_external_count",
            "local_or_backend_count",
            "layers",
            "rows",
        },
        "fingerprint_fields": {"registry_fingerprint_sha256"},
        "version_fields": {"registry_version"},
    },
}
EXPECTED_MARKDOWN_REPORTS = {
    "runtime-evidence-coverage.md": (
        "# Wiii Runtime Evidence Coverage",
        "Report schema:",
        "Registry fingerprint SHA-256",
        "Error codes:",
    )
}
EXPECTED_REPORT_NAMES = set(EXPECTED_JSON_REPORTS) | set(EXPECTED_MARKDOWN_REPORTS)
ALLOWED_REPORT_NAMES = EXPECTED_REPORT_NAMES | {SELF_VALIDATION_REPORT_NAME}
SELF_VALIDATION_REPORT_FIELDS = {
    "validation_schema_version",
    "bundle_root",
    "report_count",
    "fingerprinted_report_count",
    "self_validation_report_present",
    "bundle_fingerprint_sha256",
    "passed_count",
    "failed_count",
    "unexpected_count",
    "rows",
    "ok",
    "error_codes",
    "error_code_counts",
}
SELF_VALIDATION_ROW_FIELDS = {
    "file_name",
    "status",
    "schema_version",
    "report_sha256",
    "errors",
    "error_codes",
}
INTERNAL_ERROR_LIST_FIELDS = (
    "errors",
    "validation_errors",
    "coverage_errors",
    "validation_error_codes",
    "coverage_error_codes",
)
COVERAGE_REPORT_ROW_FIELDS = {
    "requirement_id",
    "title",
    "layer",
    "artifact",
    "artifact_tokens",
    "diagnostic_upload_count",
    "diagnostic_upload_artifacts",
    "diagnostic_upload_paths",
    "schema_version",
    "workflow",
    "probe",
    "contract_tests",
    "payload_checks",
    "raw_content_absence_checks",
    "identifier_strategy_checks",
    "identifier_strategies",
    "external_evidence_mode",
    "synthetic_gap_flags",
    "credentialed_external_flags",
    "freshness_hours",
    "forbidden_tokens",
    "forbidden_regexes",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gates",
    "coverage_target_met",
}
COVERAGE_REPORT_ROW_STRING_FIELDS = {
    "requirement_id",
    "title",
    "layer",
    "artifact",
    "schema_version",
    "workflow",
    "probe",
    "external_evidence_mode",
}
COVERAGE_REPORT_ROW_INT_FIELDS = {
    "contract_tests",
    "payload_checks",
    "diagnostic_upload_count",
    "raw_content_absence_checks",
    "identifier_strategy_checks",
    "forbidden_tokens",
    "forbidden_regexes",
}
COVERAGE_REPORT_ROW_STRING_LIST_FIELDS = {
    "identifier_strategies",
    "artifact_tokens",
    "diagnostic_upload_artifacts",
    "diagnostic_upload_paths",
    "synthetic_gap_flags",
    "credentialed_external_flags",
    "live_env_flags",
    "live_guard_tokens",
    "dispatch_or_schedule_gates",
}
JSON_REPORT_TOP_LEVEL_STRING_FIELDS = {
    "self-harness-validation.json": {
        "validation_schema_version",
        "harness",
        "manifest_path",
    },
    "runtime-evidence-registry-validation.json": {
        "validation_schema_version",
        "registry",
        "registry_path",
    },
    "runtime-evidence-coverage.json": {
        "schema_version",
        "registry_name",
        "registry_path",
    },
}
JSON_REPORT_TOP_LEVEL_NON_NEGATIVE_INT_FIELDS = {
    "self-harness-validation.json": {
        "scenario_count",
        "evidence_count",
        "passed_checks",
    },
    "runtime-evidence-registry-validation.json": {
        "requirement_count",
        "passed_checks",
    },
    "runtime-evidence-coverage.json": {
        "requirement_count",
        "synthetic_external_gap_count",
        "credentialed_external_count",
        "local_or_backend_count",
    },
}
JSON_REPORT_TOP_LEVEL_STRING_LIST_FIELDS = {
    "self-harness-validation.json": {
        "warnings",
        "errors",
    },
    "runtime-evidence-registry-validation.json": {
        "errors",
    },
    "runtime-evidence-coverage.json": {
        "validation_errors",
        "validation_error_codes",
        "coverage_errors",
        "coverage_error_codes",
        "layers",
    },
}


@dataclass(frozen=True)
class ReportBundleRow:
    file_name: str
    status: str
    schema_version: str | None
    report_sha256: str | None
    errors: list[str]


@dataclass(frozen=True)
class ReportBundleResult:
    validation_schema_version: str
    bundle_root: str
    report_count: int
    fingerprinted_report_count: int
    self_validation_report_present: bool
    bundle_fingerprint_sha256: str
    passed_count: int
    failed_count: int
    unexpected_count: int
    rows: list[ReportBundleRow]

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and self.unexpected_count == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        errors = _all_errors(self.rows)
        data["ok"] = self.ok
        data["error_codes"] = _error_codes(errors)
        data["error_code_counts"] = _error_code_counts(self.rows)
        data["rows"] = [
            {
                **row_data,
                "error_codes": _error_codes(row.errors),
            }
            for row_data, row in zip(data["rows"], self.rows, strict=True)
        ]
        return data


def validate_report_bundle(
    bundle_root: Path,
    *,
    require_self_validation: bool = False,
    require_no_synthetic_gaps: bool = False,
    require_credentialed_external_contracts: bool = False,
) -> ReportBundleResult:
    rows: list[ReportBundleRow] = []
    root_errors = _validate_bundle_root(bundle_root)
    if root_errors:
        rows.append(
            ReportBundleRow(
                file_name="",
                status="failed",
                schema_version=None,
                report_sha256=None,
                errors=root_errors,
            )
        )
        return _build_result(bundle_root=bundle_root, rows=rows)

    for file_name, spec in EXPECTED_JSON_REPORTS.items():
        rows.append(_validate_json_report(bundle_root / file_name, file_name, spec))
    for file_name, tokens in EXPECTED_MARKDOWN_REPORTS.items():
        rows.append(_validate_markdown_report(bundle_root / file_name, file_name, tokens))
    _validate_current_contract_fingerprints(bundle_root, rows)
    _validate_cross_report_consistency(bundle_root, rows)
    if require_no_synthetic_gaps:
        _validate_no_synthetic_external_gaps(bundle_root, rows)
    if require_credentialed_external_contracts:
        _validate_credentialed_external_contracts(bundle_root, rows)
    _validate_coverage_rows_match_current_registry(bundle_root, rows)
    rows.extend(_unexpected_report_rows(bundle_root))
    self_validation_path = bundle_root / SELF_VALIDATION_REPORT_NAME
    if (
        require_self_validation
        or self_validation_path.exists()
        or self_validation_path.is_symlink()
    ):
        rows.append(
            _validate_self_validation_report(
                self_validation_path,
                expected_rows=rows,
                expected_bundle_fingerprint=_bundle_fingerprint(rows),
            )
        )

    return _build_result(bundle_root=bundle_root, rows=rows)


def _build_result(*, bundle_root: Path, rows: list[ReportBundleRow]) -> ReportBundleResult:
    return ReportBundleResult(
        validation_schema_version=REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
        bundle_root=str(bundle_root),
        report_count=len(rows),
        fingerprinted_report_count=len(_fingerprinted_rows(rows)),
        self_validation_report_present=any(
            row.file_name == SELF_VALIDATION_REPORT_NAME
            and row.report_sha256 is not None
            for row in rows
        ),
        bundle_fingerprint_sha256=_bundle_fingerprint(rows),
        passed_count=sum(1 for row in rows if row.status == "passed"),
        failed_count=sum(1 for row in rows if row.status == "failed"),
        unexpected_count=sum(
            1
            for row in rows
            if _is_unexpected_report_row(row)
        ),
        rows=rows,
    )


def _validate_bundle_root(bundle_root: Path) -> list[str]:
    if not bundle_root.exists():
        return [f"bundle root does not exist: {bundle_root}"]
    if bundle_root.is_symlink():
        return [f"bundle root must not be a symlink: {bundle_root}"]
    if not bundle_root.is_dir():
        return [f"bundle root must be a directory: {bundle_root}"]
    return []


def _validate_current_contract_fingerprints(
    bundle_root: Path,
    rows: list[ReportBundleRow],
) -> None:
    self_harness_payload = _load_json_report_payload_if_object(
        bundle_root / "self-harness-validation.json"
    )
    if (
        self_harness_payload is not None
        and not _row_has_errors(rows, "self-harness-validation.json")
    ):
        expected_manifest_fingerprint = _manifest_fingerprint(
            load_manifest(DEFAULT_MANIFEST)
        )
        if (
            self_harness_payload.get("manifest_fingerprint_sha256")
            != expected_manifest_fingerprint
        ):
            _append_row_errors(
                rows,
                "self-harness-validation.json",
                [
                    "self-harness-validation.json: manifest_fingerprint_sha256 "
                    "must match current Wiii Self-Harness manifest "
                    f"{expected_manifest_fingerprint}"
                ],
            )

    registry_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-registry-validation.json"
    )
    if (
        registry_payload is not None
        and not _row_has_errors(rows, "runtime-evidence-registry-validation.json")
    ):
        expected_registry_fingerprint = _registry_fingerprint(
            load_registry(DEFAULT_REGISTRY)
        )
        if (
            registry_payload.get("registry_fingerprint_sha256")
            != expected_registry_fingerprint
        ):
            _append_row_errors(
                rows,
                "runtime-evidence-registry-validation.json",
                [
                    "runtime-evidence-registry-validation.json: "
                    "registry_fingerprint_sha256 must match current runtime "
                    f"evidence registry {expected_registry_fingerprint}"
                ],
            )


def _validate_cross_report_consistency(
    bundle_root: Path,
    rows: list[ReportBundleRow],
) -> None:
    coverage_markdown = _read_text_report_if_file(
        bundle_root / "runtime-evidence-coverage.md"
    )
    registry_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-registry-validation.json"
    )
    coverage_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-coverage.json"
    )
    if (
        coverage_payload is None
        or _row_has_errors(rows, "runtime-evidence-coverage.json")
    ):
        return

    if registry_payload is not None and not _row_has_errors(
        rows,
        "runtime-evidence-registry-validation.json",
    ):
        mismatched_fields: list[str] = []
        for registry_field, coverage_field in (
            ("registry", "registry_name"),
            ("registry_path", "registry_path"),
            ("registry_fingerprint_sha256", "registry_fingerprint_sha256"),
            ("registry_version", "registry_version"),
            ("requirement_count", "requirement_count"),
        ):
            if registry_payload.get(registry_field) != coverage_payload.get(coverage_field):
                mismatched_fields.append(coverage_field)
        if mismatched_fields:
            _append_row_errors(
                rows,
                "runtime-evidence-coverage.json",
                [
                    "runtime-evidence-coverage.json: coverage report must match "
                    "runtime-evidence-registry-validation.json for "
                    f"{', '.join(mismatched_fields)}"
                ],
            )

    if coverage_markdown is not None and not _row_has_errors(
        rows,
        "runtime-evidence-coverage.md",
    ):
        _validate_coverage_markdown_matches_json(
            coverage_payload,
            coverage_markdown,
            rows,
        )


def _validate_coverage_rows_match_current_registry(
    bundle_root: Path,
    rows: list[ReportBundleRow],
) -> None:
    coverage_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-coverage.json"
    )
    if (
        coverage_payload is None
        or _row_has_errors(rows, "runtime-evidence-coverage.json")
    ):
        return
    row_values = coverage_payload.get("rows")
    if not isinstance(row_values, list):
        return

    registry = load_registry(DEFAULT_REGISTRY)
    registry_requirements = {
        item["id"]: item
        for item in registry.get("requirements", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    mismatches: list[str] = []
    seen_requirement_ids: set[str] = set()
    for row in row_values:
        if not isinstance(row, dict):
            continue
        requirement_id = row.get("requirement_id")
        if not isinstance(requirement_id, str) or not requirement_id.strip():
            continue
        seen_requirement_ids.add(requirement_id)
        requirement = registry_requirements.get(requirement_id)
        if requirement is None:
            mismatches.append(f"{requirement_id}: requirement missing from registry")
            continue
        fields = _coverage_row_registry_mismatched_fields(row, requirement)
        if fields:
            mismatches.append(f"{requirement_id}: {', '.join(fields)}")
    missing_rows = sorted(set(registry_requirements) - seen_requirement_ids)
    if missing_rows:
        mismatches.append(f"missing coverage row(s): {', '.join(missing_rows)}")
    if not mismatches:
        return
    _append_row_errors(
        rows,
        "runtime-evidence-coverage.json",
        [
            "runtime-evidence-coverage.json: coverage rows must match current "
            "runtime evidence registry for "
            f"{'; '.join(mismatches)}"
        ],
    )


def _coverage_row_registry_mismatched_fields(
    row: dict[str, Any],
    requirement: dict[str, Any],
) -> list[str]:
    expected = {
        "title": str(requirement.get("title") or ""),
        "layer": str(requirement.get("layer") or ""),
        "artifact": str(requirement.get("artifact") or ""),
        "artifact_tokens": _string_list_allow_empty(requirement.get("artifact_tokens")),
        "diagnostic_upload_count": len(_diagnostic_uploads(requirement)),
        "diagnostic_upload_artifacts": _diagnostic_upload_values(
            requirement,
            "artifact",
        ),
        "diagnostic_upload_paths": _diagnostic_upload_values(requirement, "path"),
        "schema_version": str(requirement.get("schema_version") or ""),
        "workflow": str(requirement.get("workflow") or ""),
        "probe": str(requirement.get("probe") or ""),
        "contract_tests": len(_string_list_allow_empty(requirement.get("contract_tests"))),
        "payload_checks": len(_payload_check_dicts(requirement)),
        "raw_content_absence_checks": _raw_content_absence_check_count(requirement),
        "identifier_strategy_checks": _identifier_strategy_check_count(requirement),
        "identifier_strategies": _identifier_strategies(requirement),
        "external_evidence_mode": _external_evidence_mode(requirement),
        "synthetic_gap_flags": _synthetic_gap_flags(requirement),
        "credentialed_external_flags": _credentialed_external_flags(requirement),
        "freshness_hours": _registry_freshness_hours(requirement),
        "forbidden_tokens": len(requirement.get("forbidden_payload_tokens") or []),
        "forbidden_regexes": len(requirement.get("forbidden_payload_regexes") or []),
        "live_env_flags": _string_list_allow_empty(requirement.get("live_env_flags")),
        "live_guard_tokens": _string_list_allow_empty(requirement.get("live_guard_tokens")),
        "dispatch_or_schedule_gates": _string_list_allow_empty(
            requirement.get("dispatch_or_schedule_gate_tokens")
        ),
    }
    return [
        field
        for field, expected_value in expected.items()
        if row.get(field) != expected_value
    ]


def _payload_check_dicts(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    payload_checks = requirement.get("payload_checks")
    if not isinstance(payload_checks, list):
        return []
    return [check for check in payload_checks if isinstance(check, dict)]


def _raw_content_absence_check_count(requirement: dict[str, Any]) -> int:
    return sum(
        1
        for check in _payload_check_dicts(requirement)
        if "raw_content_included" in str(check.get("path") or "")
        and check.get("equals") is False
    )


def _identifier_strategy_check_count(requirement: dict[str, Any]) -> int:
    return sum(
        1
        for check in _payload_check_dicts(requirement)
        if "identifier_strategy" in str(check.get("path") or "")
    )


def _identifier_strategies(requirement: dict[str, Any]) -> list[str]:
    strategies = {
        str(check.get("equals"))
        for check in _payload_check_dicts(requirement)
        if "identifier_strategy" in str(check.get("path") or "")
        and isinstance(check.get("equals"), str)
    }
    return sorted(strategies)


def _external_evidence_mode(requirement: dict[str, Any]) -> str:
    if _synthetic_gap_flags(requirement):
        return "synthetic_external_gap"
    if _credentialed_external_flags(requirement):
        return "credentialed_external"
    return "local_or_backend"


def _synthetic_gap_flags(requirement: dict[str, Any]) -> list[str]:
    return _evidence_contract_true_flags(requirement, SYNTHETIC_EXTERNAL_GAP_FLAGS)


def _credentialed_external_flags(requirement: dict[str, Any]) -> list[str]:
    return _evidence_contract_true_flags(requirement, CREDENTIALED_EXTERNAL_FLAGS)


def _evidence_contract_true_flags(
    requirement: dict[str, Any],
    allowed_flags: set[str],
) -> list[str]:
    flags: set[str] = set()
    for check in _payload_check_dicts(requirement):
        path = str(check.get("path") or "")
        if not path.startswith("evidence_contract.") or check.get("equals") is not True:
            continue
        flag = path.removeprefix("evidence_contract.")
        if flag in allowed_flags:
            flags.add(flag)
    return sorted(flags)


def _registry_freshness_hours(requirement: dict[str, Any]) -> int | None:
    freshness = requirement.get("freshness")
    if not isinstance(freshness, dict):
        return None
    max_age_hours = freshness.get("max_age_hours")
    return max_age_hours if _is_positive_int(max_age_hours) else None


def _diagnostic_uploads(requirement: dict[str, Any]) -> list[dict[str, Any]]:
    uploads = requirement.get("diagnostic_uploads")
    if not isinstance(uploads, list):
        return []
    return [upload for upload in uploads if isinstance(upload, dict)]


def _diagnostic_upload_values(requirement: dict[str, Any], field: str) -> list[str]:
    values = {
        value.strip()
        for upload in _diagnostic_uploads(requirement)
        if isinstance(value := upload.get(field), str) and value.strip()
    }
    return sorted(values)


def _string_list_allow_empty(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _validate_no_synthetic_external_gaps(
    bundle_root: Path,
    rows: list[ReportBundleRow],
) -> None:
    coverage_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-coverage.json"
    )
    if (
        coverage_payload is None
        or _row_has_errors(rows, "runtime-evidence-coverage.json")
    ):
        return
    gap_count = coverage_payload.get("synthetic_external_gap_count")
    if not _is_non_negative_int(gap_count) or gap_count == 0:
        return
    requirement_ids = _synthetic_external_gap_requirement_ids(coverage_payload)
    summary = ", ".join(requirement_ids) if requirement_ids else f"{gap_count} row(s)"
    _append_row_errors(
        rows,
        "runtime-evidence-coverage.json",
        [
            "runtime-evidence-coverage.json: synthetic external gaps remain "
            f"when --require-no-synthetic-gaps is set: {summary}"
        ],
    )


def _validate_credentialed_external_contracts(
    bundle_root: Path,
    rows: list[ReportBundleRow],
) -> None:
    coverage_payload = _load_json_report_payload_if_object(
        bundle_root / "runtime-evidence-coverage.json"
    )
    if (
        coverage_payload is None
        or _row_has_errors(rows, "runtime-evidence-coverage.json")
    ):
        return
    errors = _coverage_credentialed_external_contract_errors(coverage_payload)
    if not errors:
        return
    _append_row_errors(
        rows,
        "runtime-evidence-coverage.json",
        [
            "runtime-evidence-coverage.json: credentialed external contract "
            "incomplete when --require-credentialed-external-contracts is set: "
            f"{'; '.join(errors)}"
        ],
    )


def _coverage_credentialed_external_contract_errors(
    coverage_payload: dict[str, Any],
) -> list[str]:
    rows = coverage_payload.get("rows")
    if not isinstance(rows, list):
        return []
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("external_evidence_mode") != "credentialed_external":
            continue
        requirement_id = row.get("requirement_id")
        requirement = (
            requirement_id
            if isinstance(requirement_id, str) and requirement_id.strip()
            else "<unknown>"
        )
        missing: list[str] = []
        if not _is_non_empty_string_list(row.get("credentialed_external_flags")):
            missing.append("credentialed_external_flags")
        if _is_non_empty_string_list(row.get("synthetic_gap_flags")):
            missing.append("synthetic_gap_flags_absent")
        if not _is_non_empty_string_list(row.get("live_env_flags")):
            missing.append("live_env_flags")
        if not _is_non_empty_string_list(row.get("live_guard_tokens")):
            missing.append("live_guard_tokens")
        gates = row.get("dispatch_or_schedule_gates")
        if not _is_string_list_allow_empty(gates) or len(gates) < 2:
            missing.append("manual_and_scheduled_gates")
        if not _positive_row_count(row.get("raw_content_absence_checks")):
            missing.append("raw_content_absence_checks")
        if not _positive_row_count(row.get("identifier_strategy_checks")):
            missing.append("identifier_strategy_checks")
        if missing:
            errors.append(f"{requirement} ({', '.join(missing)})")
    return errors


def _synthetic_external_gap_requirement_ids(
    coverage_payload: dict[str, Any],
) -> list[str]:
    rows = coverage_payload.get("rows")
    if not isinstance(rows, list):
        return []
    requirement_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("external_evidence_mode") != "synthetic_external_gap":
            continue
        requirement_id = row.get("requirement_id")
        if isinstance(requirement_id, str) and requirement_id.strip():
            requirement_ids.append(requirement_id)
    return sorted(requirement_ids)


def _load_json_report_payload_if_object(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.is_symlink() or not path.is_file():
        return None
    try:
        loaded = _load_json_report(path)
    except (ValueError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _read_text_report_if_file(path: Path) -> str | None:
    if not path.exists() or path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _validate_coverage_markdown_matches_json(
    coverage_payload: dict[str, Any],
    markdown: str,
    rows: list[ReportBundleRow],
) -> None:
    missing_tokens: list[str] = []
    for token in _coverage_markdown_tokens_from_json(coverage_payload):
        if token not in markdown:
            missing_tokens.append(token)

    json_rows = coverage_payload.get("rows")
    markdown_rows = _coverage_markdown_data_rows(markdown)
    if isinstance(json_rows, list) and len(markdown_rows) != len(json_rows):
        missing_tokens.append(
            f"coverage table row count {len(markdown_rows)} must match JSON rows "
            f"{len(json_rows)}"
        )
        expected_row_lines = []
    else:
        expected_row_lines = _coverage_markdown_row_lines_from_json(json_rows)
    markdown_row_set = set(markdown_rows)
    for requirement_id, expected_line in expected_row_lines:
        if expected_line not in markdown_row_set:
            missing_tokens.append(f"coverage table row mismatch for {requirement_id}")

    if not missing_tokens:
        return
    _append_row_errors(
        rows,
        "runtime-evidence-coverage.md",
        [
            "runtime-evidence-coverage.md: coverage Markdown must match "
            "runtime-evidence-coverage.json for "
            f"{', '.join(missing_tokens)}"
        ],
    )


def _coverage_markdown_tokens_from_json(payload: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    token_specs = (
        ("schema_version", "- Report schema: `{}`"),
        ("registry_name", "- Registry name: `{}`"),
        ("registry_version", "- Registry version: `{}`"),
        ("registry_path", "- Registry: `{}`"),
        ("registry_fingerprint_sha256", "- Registry fingerprint SHA-256: `{}`"),
        ("requirement_count", "- Requirements: `{}`"),
    )
    for field, template in token_specs:
        value = payload.get(field)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            tokens.append(template.format(value))

    ok_value = payload.get("ok")
    if isinstance(ok_value, bool):
        tokens.append(f"- Status: `{'PASS' if ok_value else 'FAIL'}`")

    error_codes = payload.get("error_codes")
    if _is_string_list_allow_empty(error_codes):
        tokens.append(f"- Error codes: `{', '.join(error_codes) or '-'}`")

    error_code_counts = payload.get("error_code_counts")
    if _is_error_code_counts(error_code_counts):
        tokens.append(f"- Error code counts: `{_format_error_code_counts(error_code_counts)}`")

    layers = payload.get("layers")
    if _is_string_list_allow_empty(layers):
        tokens.append(f"- Layers: `{', '.join(layers)}`")
    external_counts = (
        payload.get("credentialed_external_count"),
        payload.get("synthetic_external_gap_count"),
        payload.get("local_or_backend_count"),
    )
    if all(_is_non_negative_int(count) for count in external_counts):
        credentialed_count, synthetic_count, local_count = external_counts
        tokens.append(
            "- External evidence: "
            f"`credentialed_external={credentialed_count}, "
            f"synthetic_external_gap={synthetic_count}, "
            f"local_or_backend={local_count}`"
        )
    return tokens


def _coverage_markdown_data_row_count(markdown: str) -> int:
    return len(_coverage_markdown_data_rows(markdown))


def _coverage_markdown_data_rows(markdown: str) -> list[str]:
    rows: list[str] = []
    in_coverage_table = False
    for line in markdown.splitlines():
        if line.startswith("|---|"):
            in_coverage_table = True
            continue
        if not in_coverage_table:
            continue
        if not line.strip():
            break
        if line.startswith("| "):
            rows.append(line)
    return rows


def _coverage_markdown_row_lines_from_json(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    expected_rows: list[tuple[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            return []
        line = _coverage_markdown_row_line_from_json(row)
        requirement_id = row.get("requirement_id")
        if line is not None and isinstance(requirement_id, str):
            expected_rows.append((requirement_id, line))
    return expected_rows


def _coverage_markdown_row_line_from_json(row: dict[str, Any]) -> str | None:
    string_fields = (
        "requirement_id",
        "layer",
        "artifact",
        "schema_version",
        "workflow",
        "probe",
        "external_evidence_mode",
    )
    if any(not isinstance(row.get(field), str) for field in string_fields):
        return None
    int_fields = (
        "contract_tests",
        "payload_checks",
        "diagnostic_upload_count",
        "raw_content_absence_checks",
        "identifier_strategy_checks",
    )
    if any(not _is_non_negative_int(row.get(field)) for field in int_fields):
        return None
    freshness_hours = row.get("freshness_hours")
    if freshness_hours is not None and not _is_non_negative_int(freshness_hours):
        return None
    list_fields = (
        "artifact_tokens",
        "diagnostic_upload_artifacts",
        "diagnostic_upload_paths",
        "identifier_strategies",
        "credentialed_external_flags",
        "synthetic_gap_flags",
        "live_env_flags",
        "live_guard_tokens",
        "dispatch_or_schedule_gates",
    )
    if any(not _is_string_list_allow_empty(row.get(field)) for field in list_fields):
        return None
    cells = [
        _coverage_markdown_cell(row["requirement_id"]),
        _coverage_markdown_cell(row["layer"]),
        _coverage_markdown_cell(row["artifact"]),
        _coverage_markdown_cell(
            f"run:{_coverage_markdown_join(row['artifact_tokens']) or '-'}; "
            f"diagnostic:{row['diagnostic_upload_count']} "
            f"{_coverage_markdown_join(row['diagnostic_upload_artifacts']) or '-'}"
        ),
        _coverage_markdown_cell(row["schema_version"]),
        _coverage_markdown_cell(row["workflow"]),
        _coverage_markdown_cell(row["probe"]),
        str(row["contract_tests"]),
        f"{row['payload_checks']} / {freshness_hours or '-'}h",
        _coverage_markdown_cell(
            f"raw:{row['raw_content_absence_checks']}; "
            f"id:{row['identifier_strategy_checks']} "
            f"({_coverage_markdown_join(row['identifier_strategies']) or '-'})"
        ),
        _coverage_markdown_cell(
            f"{row['external_evidence_mode']}; "
            f"credentialed:{_coverage_markdown_join(row['credentialed_external_flags']) or '-'}; "
            f"synthetic:{_coverage_markdown_join(row['synthetic_gap_flags']) or '-'}"
        ),
        _coverage_markdown_cell(
            _coverage_markdown_join([*row["live_env_flags"], *row["live_guard_tokens"]])
        ),
        _coverage_markdown_cell(_coverage_markdown_join(row["dispatch_or_schedule_gates"])),
    ]
    return "| " + " | ".join(cells) + " |"


def _coverage_markdown_join(value: list[str]) -> str:
    return ", ".join(value)


def _coverage_markdown_cell(value: str) -> str:
    normalized = " ".join(value.replace("|", "\\|").split())
    return normalized or "-"


def _append_row_errors(
    rows: list[ReportBundleRow],
    file_name: str,
    errors: list[str],
) -> None:
    for index, row in enumerate(rows):
        if row.file_name == file_name:
            rows[index] = replace(
                row,
                status="failed",
                errors=[*row.errors, *errors],
            )
            return


def _row_has_errors(rows: list[ReportBundleRow], file_name: str) -> bool:
    return any(row.file_name == file_name and row.errors for row in rows)


def _validate_json_report(
    path: Path,
    file_name: str,
    spec: dict[str, Any],
) -> ReportBundleRow:
    errors = _validate_report_path(path, file_name)
    payload: dict[str, Any] | None = None
    if not errors:
        try:
            loaded = _load_json_report(path)
        except ValueError as exc:
            errors.append(f"{file_name}: report JSON is invalid: {exc}")
        except UnicodeDecodeError as exc:
            errors.append(f"{file_name}: report file is not valid UTF-8: {exc}")
        else:
            if not isinstance(loaded, dict):
                errors.append(f"{file_name}: report root must be a JSON object")
            else:
                payload = loaded

    schema_version = None
    if payload is not None:
        schema_field = str(spec["schema_field"])
        schema_version = payload.get(schema_field)
        if schema_version != spec["schema_version"]:
            errors.append(
                f"{file_name}: {schema_field} must be {spec['schema_version']!r}, "
                f"got {schema_version!r}"
            )
        for field in sorted(spec["required_fields"]):
            if field not in payload:
                errors.append(f"{file_name}: missing required field {field!r}")
        unsupported_fields = sorted(set(payload) - set(spec["allowed_fields"]))
        if unsupported_fields:
            errors.append(
                f"{file_name}: top-level fields contain unsupported fields: "
                f"{', '.join(unsupported_fields)}"
            )
        _validate_json_report_top_level_value_types(payload, file_name, errors)
        if "ok" in payload and not isinstance(payload.get("ok"), bool):
            errors.append(f"{file_name}: `ok` must be boolean")
        if "error_codes" in payload and not _is_string_list(payload.get("error_codes")):
            errors.append(f"{file_name}: `error_codes` must be a string list")
        if "error_code_counts" in payload and not _is_error_code_counts(
            payload.get("error_code_counts")
        ):
            errors.append(
                f"{file_name}: `error_code_counts` must map string codes "
                "to non-negative integers"
            )
        _validate_report_error_code_summary_fields(payload, file_name, errors)
        if file_name == "runtime-evidence-coverage.json":
            _validate_coverage_report_rows(payload, file_name, errors)
        _validate_report_success_fields(payload, file_name, errors)
        for field in sorted(spec["fingerprint_fields"]):
            value = payload.get(field)
            if not isinstance(value, str) or not FINGERPRINT_RE.fullmatch(value):
                errors.append(f"{file_name}: `{field}` must be a SHA-256 hex digest")
        for field in sorted(spec["version_fields"]):
            value = payload.get(field)
            if not _is_positive_int(value):
                errors.append(f"{file_name}: `{field}` must be an integer >= 1")

    return ReportBundleRow(
        file_name=file_name,
        status="passed" if not errors else "failed",
        schema_version=schema_version if isinstance(schema_version, str) else None,
        report_sha256=_sha256_file(path) if path.is_file() and not path.is_symlink() else None,
        errors=errors,
    )


def _validate_markdown_report(
    path: Path,
    file_name: str,
    tokens: tuple[str, ...],
) -> ReportBundleRow:
    errors = _validate_report_path(path, file_name)
    if not errors:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{file_name}: report file is not valid UTF-8: {exc}")
        else:
            for token in tokens:
                if token not in text:
                    errors.append(f"{file_name}: missing token {token!r}")
    return ReportBundleRow(
        file_name=file_name,
        status="passed" if not errors else "failed",
        schema_version=None,
        report_sha256=_sha256_file(path) if path.is_file() and not path.is_symlink() else None,
        errors=errors,
    )


def _validate_self_validation_report(
    path: Path,
    *,
    expected_rows: list[ReportBundleRow],
    expected_bundle_fingerprint: str,
) -> ReportBundleRow:
    errors = _validate_report_path(path, SELF_VALIDATION_REPORT_NAME)
    payload: dict[str, Any] | None = None
    if not errors:
        try:
            loaded = _load_json_report(path)
        except ValueError as exc:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: report JSON is invalid: {exc}"
            )
        except UnicodeDecodeError as exc:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: report file is not valid UTF-8: {exc}"
            )
        else:
            if not isinstance(loaded, dict):
                errors.append(
                    f"{SELF_VALIDATION_REPORT_NAME}: report root must be a JSON object"
                )
            else:
                payload = loaded

    schema_version = None
    if payload is not None:
        _validate_self_validation_report_fields(payload, errors)
        schema_version = payload.get("validation_schema_version")
        if schema_version != REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: validation_schema_version must be "
                f"{REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION!r}, got {schema_version!r}"
            )
        bundle_fingerprint = payload.get("bundle_fingerprint_sha256")
        if bundle_fingerprint != expected_bundle_fingerprint:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: bundle_fingerprint_sha256 must be "
                f"{expected_bundle_fingerprint!r}, got {bundle_fingerprint!r}"
            )
        if "ok" in payload and not isinstance(payload.get("ok"), bool):
            errors.append(f"{SELF_VALIDATION_REPORT_NAME}: `ok` must be boolean")
        if "error_codes" in payload and not _is_string_list(payload.get("error_codes")):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: `error_codes` must be a string list"
            )
        if "error_code_counts" in payload and not _is_error_code_counts(
            payload.get("error_code_counts")
        ):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: `error_code_counts` must map "
                "string codes to non-negative integers"
            )
        _validate_report_error_code_summary_fields(
            payload,
            SELF_VALIDATION_REPORT_NAME,
            errors,
        )
        _validate_report_success_fields(
            payload,
            SELF_VALIDATION_REPORT_NAME,
            errors,
        )
        fingerprinted_count = payload.get("fingerprinted_report_count")
        if fingerprinted_count != len(EXPECTED_REPORT_NAMES):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: fingerprinted_report_count must be "
                f"{len(EXPECTED_REPORT_NAMES)}, got {fingerprinted_count!r}"
            )
        report_count = payload.get("report_count")
        if report_count != len(EXPECTED_REPORT_NAMES):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: report_count must be "
                f"{len(EXPECTED_REPORT_NAMES)}, got {report_count!r}"
            )
        self_validation_present = payload.get("self_validation_report_present")
        if self_validation_present is not False:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: self_validation_report_present "
                f"must be false, got {self_validation_present!r}"
            )
        _validate_self_validation_counts(payload, expected_rows, errors)
        _validate_self_validation_rows(payload, expected_rows, errors)

    return ReportBundleRow(
        file_name=SELF_VALIDATION_REPORT_NAME,
        status="passed" if not errors else "failed",
        schema_version=schema_version if isinstance(schema_version, str) else None,
        report_sha256=_sha256_file(path) if path.is_file() and not path.is_symlink() else None,
        errors=errors,
    )


def _validate_self_validation_report_fields(
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    actual_fields = set(payload)
    if actual_fields != SELF_VALIDATION_REPORT_FIELDS:
        missing = sorted(SELF_VALIDATION_REPORT_FIELDS - actual_fields)
        extra = sorted(actual_fields - SELF_VALIDATION_REPORT_FIELDS)
        errors.append(
            f"{SELF_VALIDATION_REPORT_NAME}: top-level fields must match "
            f"the self-validation report schema; missing={missing} extra={extra}"
        )


def _validate_self_validation_counts(
    payload: dict[str, Any],
    expected_rows: list[ReportBundleRow],
    errors: list[str],
) -> None:
    expected_passed = sum(1 for row in expected_rows if row.status == "passed")
    expected_failed = sum(1 for row in expected_rows if row.status == "failed")
    expected_unexpected = sum(
        1 for row in expected_rows if _is_unexpected_report_row(row)
    )
    expected_counts = {
        "passed_count": expected_passed,
        "failed_count": expected_failed,
        "unexpected_count": expected_unexpected,
    }
    for field, expected in expected_counts.items():
        value = payload.get(field)
        if value != expected:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: {field} must be "
                f"{expected}, got {value!r}"
            )
    error_code_counts = payload.get("error_code_counts")
    if error_code_counts != _error_code_counts(expected_rows):
        errors.append(
            f"{SELF_VALIDATION_REPORT_NAME}: error_code_counts must match "
            "the canonical pre-self report rows"
        )


def _validate_self_validation_rows(
    payload: dict[str, Any],
    expected_rows: list[ReportBundleRow],
    errors: list[str],
) -> None:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        errors.append(f"{SELF_VALIDATION_REPORT_NAME}: `rows` must be a list")
        return

    row_by_name: dict[str, dict[str, Any]] = {}
    actual_names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: `rows` entries must be objects"
            )
            return
        extra_fields = sorted(set(row) - SELF_VALIDATION_ROW_FIELDS)
        if extra_fields:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: `rows` entries contain "
                f"unsupported fields: {extra_fields}"
            )
            return
        file_name = row.get("file_name")
        if not isinstance(file_name, str) or not file_name:
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: `rows` entries must have file_name"
            )
            return
        actual_names.append(file_name)
        row_by_name[file_name] = row

    expected_by_name = {row.file_name: row for row in expected_rows}
    expected_names = [row.file_name for row in expected_rows]
    if set(row_by_name) != set(expected_by_name):
        errors.append(
            f"{SELF_VALIDATION_REPORT_NAME}: `rows` must describe exactly "
            "the canonical pre-self reports"
        )
        return
    if actual_names != expected_names:
        errors.append(
            f"{SELF_VALIDATION_REPORT_NAME}: `rows` must use "
            "canonical pre-self report order"
        )
        return

    for file_name, expected in expected_by_name.items():
        row = row_by_name[file_name]
        expected_error_codes = _error_codes(expected.errors)
        if (
            row.get("status") != expected.status
            or row.get("schema_version") != expected.schema_version
            or row.get("report_sha256") != expected.report_sha256
            or row.get("errors") != expected.errors
            or row.get("error_codes") != expected_error_codes
        ):
            errors.append(
                f"{SELF_VALIDATION_REPORT_NAME}: row {file_name!r} does not "
                "match the canonical pre-self report manifest"
            )
            return


def _validate_report_path(path: Path, file_name: str) -> list[str]:
    if not path.exists():
        return [f"{file_name}: report file is missing"]
    if path.is_symlink():
        return [f"{file_name}: report file must not be a symlink"]
    if not path.is_file():
        return [f"{file_name}: report path must be a file"]
    return []


def _validate_report_error_code_summary_fields(
    payload: dict[str, Any],
    file_name: str,
    errors: list[str],
) -> None:
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not (_is_string_list(error_codes) and _is_error_code_counts(error_code_counts)):
        return
    if len(set(error_codes)) != len(error_codes):
        errors.append(f"{file_name}: `error_codes` must not contain duplicate entries")
    if sorted(error_code_counts) != sorted(error_codes):
        errors.append(
            f"{file_name}: `error_code_counts` keys must match `error_codes`"
        )
    non_positive_codes = sorted(
        code for code, count in error_code_counts.items() if count <= 0
    )
    if non_positive_codes:
        rendered = ", ".join(repr(code) for code in non_positive_codes)
        errors.append(
            f"{file_name}: `error_code_counts` values must be positive for "
            f"listed error codes: {rendered}"
        )


def _validate_json_report_top_level_value_types(
    payload: dict[str, Any],
    file_name: str,
    errors: list[str],
) -> None:
    invalid_fields: list[str] = []
    for field in sorted(JSON_REPORT_TOP_LEVEL_STRING_FIELDS.get(file_name, set())):
        value = payload.get(field)
        if field in payload and (not isinstance(value, str) or not value.strip()):
            invalid_fields.append(field)
    for field in sorted(
        JSON_REPORT_TOP_LEVEL_NON_NEGATIVE_INT_FIELDS.get(file_name, set())
    ):
        if field in payload and not _is_non_negative_int(payload.get(field)):
            invalid_fields.append(field)
    for field in sorted(
        JSON_REPORT_TOP_LEVEL_STRING_LIST_FIELDS.get(file_name, set())
    ):
        if field in payload and not _is_string_list_allow_empty(payload.get(field)):
            invalid_fields.append(field)
    if invalid_fields:
        errors.append(
            f"{file_name}: top-level fields have invalid types or ranges: "
            f"{', '.join(sorted(invalid_fields))}"
        )


def _validate_coverage_report_rows(
    payload: dict[str, Any],
    file_name: str,
    errors: list[str],
) -> None:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        errors.append(f"{file_name}: `rows` must be a list")
        return

    requirement_count = payload.get("requirement_count")
    if (
        isinstance(requirement_count, int)
        and not isinstance(requirement_count, bool)
        and requirement_count >= 0
        and len(rows) != requirement_count
    ):
        errors.append(
            f"{file_name}: `rows` length must match requirement_count "
            f"{requirement_count}, got {len(rows)}"
        )

    _validate_coverage_external_mode_counts(payload, rows, file_name, errors)
    _validate_coverage_layer_summary(payload, rows, file_name, errors)

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{file_name}: `rows[{index}]` must be an object")
            continue
        missing_fields = sorted(COVERAGE_REPORT_ROW_FIELDS - set(row))
        unsupported_fields = sorted(set(row) - COVERAGE_REPORT_ROW_FIELDS)
        if missing_fields or unsupported_fields:
            details: list[str] = []
            if missing_fields:
                details.append(f"missing {', '.join(missing_fields)}")
            if unsupported_fields:
                details.append(f"unsupported {', '.join(unsupported_fields)}")
            errors.append(
                f"{file_name}: `rows[{index}]` fields must match coverage row "
                f"schema ({'; '.join(details)})"
            )
            continue
        _validate_coverage_report_row_values(row, file_name, index, errors)


def _validate_coverage_external_mode_counts(
    payload: dict[str, Any],
    rows: list[Any],
    file_name: str,
    errors: list[str],
) -> None:
    expected = {
        "synthetic_external_gap_count": 0,
        "credentialed_external_count": 0,
        "local_or_backend_count": 0,
    }
    mode_to_field = {
        "synthetic_external_gap": "synthetic_external_gap_count",
        "credentialed_external": "credentialed_external_count",
        "local_or_backend": "local_or_backend_count",
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = mode_to_field.get(row.get("external_evidence_mode"))
        if field is not None:
            expected[field] += 1

    mismatches: list[str] = []
    for field, expected_count in expected.items():
        value = payload.get(field)
        if _is_non_negative_int(value) and value != expected_count:
            mismatches.append(f"{field}={value} expected {expected_count}")
    if mismatches:
        errors.append(
            f"{file_name}: external evidence mode counts must match coverage rows "
            f"({', '.join(mismatches)})"
        )


def _validate_coverage_layer_summary(
    payload: dict[str, Any],
    rows: list[Any],
    file_name: str,
    errors: list[str],
) -> None:
    layers = payload.get("layers")
    if not _is_string_list_allow_empty(layers):
        return
    expected_layers = sorted(
        {
            layer
            for row in rows
            if isinstance(row, dict)
            and isinstance(layer := row.get("layer"), str)
            and layer.strip()
        }
    )
    if layers == expected_layers:
        return
    errors.append(
        f"{file_name}: layers summary must match coverage row layers "
        f"(layers={layers!r} expected {expected_layers!r})"
    )


def _validate_coverage_report_row_values(
    row: dict[str, Any],
    file_name: str,
    index: int,
    errors: list[str],
) -> None:
    invalid_fields: list[str] = []
    for field in sorted(COVERAGE_REPORT_ROW_STRING_FIELDS):
        if not isinstance(row.get(field), str) or not row.get(field):
            invalid_fields.append(field)
    for field in sorted(COVERAGE_REPORT_ROW_INT_FIELDS):
        value = row.get(field)
        if not _is_non_negative_int(value):
            invalid_fields.append(field)
    for field in sorted(COVERAGE_REPORT_ROW_STRING_LIST_FIELDS):
        if not _is_string_list_allow_empty(row.get(field)):
            invalid_fields.append(field)
    freshness_hours = row.get("freshness_hours")
    if freshness_hours is not None and not _is_non_negative_int(freshness_hours):
        invalid_fields.append("freshness_hours")
    if not isinstance(row.get("coverage_target_met"), bool):
        invalid_fields.append("coverage_target_met")
    elif (
        _is_non_negative_int(row.get("payload_checks"))
        and _is_non_negative_int(freshness_hours)
        and row["coverage_target_met"] != (row["payload_checks"] >= freshness_hours)
    ):
        invalid_fields.append("coverage_target_met")
    if invalid_fields:
        errors.append(
            f"{file_name}: `rows[{index}]` values have invalid types or ranges: "
            f"{', '.join(sorted(invalid_fields))}"
        )


def _validate_report_success_fields(
    payload: dict[str, Any],
    file_name: str,
    errors: list[str],
) -> None:
    ok_value = payload.get("ok")
    if isinstance(ok_value, bool) and not ok_value:
        errors.append(f"{file_name}: `ok` must be true")
    error_codes = payload.get("error_codes")
    if _is_string_list(error_codes) and error_codes:
        errors.append(f"{file_name}: `error_codes` must be empty when bundled")
    error_code_counts = payload.get("error_code_counts")
    if _is_error_code_counts(error_code_counts) and error_code_counts:
        errors.append(
            f"{file_name}: `error_code_counts` must be empty when bundled"
        )
    for field in INTERNAL_ERROR_LIST_FIELDS:
        value = payload.get(field)
        if _is_string_list_allow_empty(value) and value:
            errors.append(f"{file_name}: `{field}` must be empty when bundled")


def _unexpected_report_rows(bundle_root: Path) -> list[ReportBundleRow]:
    rows: list[ReportBundleRow] = []
    candidates = sorted(
        item
        for item in bundle_root.rglob("*")
        if item.is_file() or item.is_dir() or item.is_symlink()
    )
    for path in candidates:
        try:
            relative = path.relative_to(bundle_root).as_posix()
        except ValueError:
            relative = str(path)
        if relative in ALLOWED_REPORT_NAMES:
            continue
        is_directory = path.is_dir() and not path.is_symlink()
        errors = [
            f"unexpected report {'directory' if is_directory else 'file'} "
            f"{relative!r}"
        ]
        if path.is_symlink():
            errors.append(f"{relative}: report file must not be a symlink")
        rows.append(
            ReportBundleRow(
                file_name=relative,
                status="failed",
                schema_version=None,
                report_sha256=_sha256_file(path) if path.is_file() and not path.is_symlink() else None,
                errors=errors,
            )
        )
    return rows


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _bundle_fingerprint(rows: list[ReportBundleRow]) -> str:
    manifest = [
        {
            "file_name": row.file_name,
            "status": row.status,
            "schema_version": row.schema_version,
            "report_sha256": row.report_sha256,
            "error_codes": _error_codes(row.errors),
        }
        for row in _fingerprinted_rows(rows)
    ]
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_unexpected_report_row(row: ReportBundleRow) -> bool:
    return any(
        error.startswith("unexpected report file ")
        or error.startswith("unexpected report directory ")
        for error in row.errors
    )


def _fingerprinted_rows(rows: list[ReportBundleRow]) -> list[ReportBundleRow]:
    return [row for row in rows if row.file_name != SELF_VALIDATION_REPORT_NAME]


def _all_errors(rows: list[ReportBundleRow]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        errors.extend(row.errors)
    return errors


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(rows: list[ReportBundleRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for error_code in _error_codes(row.errors):
            counts[error_code] = counts.get(error_code, 0) + 1
    return dict(sorted(counts.items()))


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def _error_code(error: str) -> str:
    if error.startswith("bundle root does not exist:"):
        return "bundle_root_missing"
    if error.startswith("bundle root must not be a symlink:"):
        return "bundle_root_symlink"
    if error.startswith("bundle root must be a directory:"):
        return "bundle_root_not_directory"
    if error == "bundle report output path must be outside bundle root":
        return "report_bundle_output_path_inside_bundle_root"
    if error == REPORT_OUTPUT_PATH_SYMLINK_ERROR:
        return "report_bundle_output_path_symlink"
    if error == REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "report_bundle_output_path_parent_symlink"
    if error == REPORT_OUTPUT_PATH_DIRECTORY_ERROR:
        return "report_bundle_output_path_directory"
    if error == f"{SELF_VALIDATION_REPORT_NAME}: report file is missing":
        return "self_validation_report_missing"
    if "report file is missing" in error:
        return "report_file_missing"
    if "report file must not be a symlink" in error:
        return "report_file_symlink"
    if "report path must be a file" in error:
        return "report_path_not_file"
    if "report file is not valid UTF-8" in error:
        return "report_file_not_utf8"
    if "report JSON is invalid" in error:
        return "report_json_invalid"
    if "report root must be a JSON object" in error:
        return "report_root_not_object"
    if "schema_version must be " in error or "validation_schema_version must be " in error:
        return "report_schema_mismatch"
    if "missing required field" in error:
        return "report_required_field_missing"
    if "`ok` must be boolean" in error:
        return "report_ok_invalid"
    if "`ok` must be true" in error:
        return "report_ok_false"
    if "`error_codes` must be a string list" in error:
        return "report_error_codes_invalid"
    if "`error_code_counts` must map string codes to non-negative integers" in error:
        return "report_error_code_counts_invalid"
    if "`error_codes` must not contain duplicate entries" in error:
        return "report_error_codes_duplicate"
    if "`error_code_counts` keys must match `error_codes`" in error:
        return "report_error_code_counts_key_mismatch"
    if "`error_code_counts` values must be positive for listed error codes" in error:
        return "report_error_code_counts_non_positive"
    if "`rows` must be a list" in error:
        return "report_rows_invalid"
    if "`rows[" in error and "must be an object" in error:
        return "report_coverage_rows_invalid"
    if "`rows` length must match requirement_count" in error:
        return "report_coverage_rows_mismatch"
    if "external evidence mode counts must match coverage rows" in error:
        return "report_coverage_external_mode_counts_mismatch"
    if "layers summary must match coverage row layers" in error:
        return "report_coverage_layers_mismatch"
    if "synthetic external gaps remain when --require-no-synthetic-gaps is set" in error:
        return "report_coverage_synthetic_external_gap_present"
    if (
        "credentialed external contract incomplete when "
        "--require-credentialed-external-contracts is set" in error
    ):
        return "report_coverage_credentialed_external_contract_incomplete"
    if "fields must match coverage row schema" in error:
        return "report_coverage_rows_invalid"
    if "top-level fields have invalid types or ranges" in error:
        return "report_top_level_field_values_invalid"
    if "values have invalid types or ranges" in error:
        return "report_coverage_row_values_invalid"
    if "`error_code_counts` must be empty when bundled" in error:
        return "report_error_code_counts_not_empty"
    if "`error_codes` must be empty when bundled" in error:
        return "report_error_codes_not_empty"
    if "must be empty when bundled" in error:
        return "report_internal_error_lists_not_empty"
    if "must be a SHA-256 hex digest" in error:
        return "report_fingerprint_invalid"
    if "manifest_fingerprint_sha256 must match current Wiii Self-Harness manifest" in error:
        return "report_current_manifest_fingerprint_mismatch"
    if "registry_fingerprint_sha256 must match current runtime evidence registry" in error:
        return "report_current_registry_fingerprint_mismatch"
    if "coverage report must match runtime-evidence-registry-validation.json" in error:
        return "report_registry_coverage_mismatch"
    if "coverage rows must match current runtime evidence registry" in error:
        return "report_registry_coverage_row_mismatch"
    if "coverage Markdown must match runtime-evidence-coverage.json" in error:
        return "report_coverage_markdown_mismatch"
    if "bundle_fingerprint_sha256 must be " in error:
        return "report_bundle_fingerprint_mismatch"
    if "fingerprinted_report_count must be " in error:
        return "report_fingerprinted_count_mismatch"
    if "report_count must be " in error:
        return "report_count_mismatch"
    if "self_validation_report_present must be false" in error:
        return "report_self_validation_presence_mismatch"
    if "top-level fields must match " in error:
        return "report_top_level_fields_invalid"
    if "top-level fields contain unsupported fields:" in error:
        return "report_top_level_fields_invalid"
    if (
        "passed_count must be " in error
        or "failed_count must be " in error
        or "unexpected_count must be " in error
    ):
        return "report_summary_count_mismatch"
    if "error_code_counts must match " in error:
        return "report_error_code_counts_mismatch"
    if "`rows` must be " in error or "`rows` entries must " in error:
        return "report_rows_invalid"
    if "`rows` must describe exactly " in error:
        return "report_rows_mismatch"
    if "`rows` must use canonical " in error:
        return "report_rows_order_mismatch"
    if "`rows` entries contain unsupported fields" in error:
        return "report_row_fields_invalid"
    if "does not match the canonical pre-self report manifest" in error:
        return "report_rows_mismatch"
    if "must be an integer >= 1" in error:
        return "report_version_invalid"
    if "missing token " in error:
        return "report_markdown_token_missing"
    if error.startswith("unexpected report file "):
        return "unexpected_report_file"
    if error.startswith("unexpected report directory "):
        return "unexpected_report_directory"
    return "validation_error"


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _is_string_list_allow_empty(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _positive_row_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_non_empty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _load_json_report(path: Path) -> Any:
    return loads_strict_json(path.read_text(encoding="utf-8"))


def _is_error_code_counts(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and key.strip()
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
        for key, count in value.items()
    )


def format_summary(result: ReportBundleResult) -> str:
    status = "PASS" if result.ok else "FAIL"
    lines = [
        f"Wiii Self-Harness Report Bundle: {status}",
        f"validation_schema: {result.validation_schema_version}",
        f"bundle_root: {result.bundle_root}",
        f"fingerprinted_reports: {result.fingerprinted_report_count}",
        f"self_validation_report_present: {str(result.self_validation_report_present).lower()}",
        f"bundle_fingerprint_sha256: {result.bundle_fingerprint_sha256}",
        f"reports: {result.report_count}",
        f"passed: {result.passed_count}",
        f"failed: {result.failed_count}",
        f"unexpected: {result.unexpected_count}",
    ]
    errors = _all_errors(result.rows)
    if errors:
        lines.append("")
        lines.append(f"Error codes: {', '.join(_error_codes(errors)) or '-'}")
        lines.append(
            f"Error code counts: {_format_error_code_counts(_error_code_counts(result.rows))}"
        )
        lines.append("Errors:")
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate downloaded Wiii Self-Harness report artifacts.",
    )
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    parser.add_argument("--out", type=Path, default=None, help="Write output to this UTF-8 file.")
    parser.add_argument(
        "--require-self-validation",
        action="store_true",
        help="Fail unless the bundle includes its self-validation JSON report.",
    )
    parser.add_argument(
        "--require-no-synthetic-gaps",
        action="store_true",
        help="Fail when bundled runtime evidence coverage still has synthetic external gaps.",
    )
    parser.add_argument(
        "--require-credentialed-external-contracts",
        action="store_true",
        help=(
            "Fail when bundled credentialed external coverage rows lack guard, "
            "gate, privacy, or identifier proof."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_report_output_path(bundle_root=args.bundle_root, out_path=args.out)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        if args.json:
            print(json.dumps(_json_error_payload(error), indent=2, sort_keys=True))
        else:
            print(f"Wiii Self-Harness Report Bundle: FAIL\n- {error}", file=sys.stderr)
        return 1
    result = validate_report_bundle(
        args.bundle_root,
        require_self_validation=args.require_self_validation,
        require_no_synthetic_gaps=args.require_no_synthetic_gaps,
        require_credentialed_external_contracts=(
            args.require_credentialed_external_contracts
        ),
    )
    rendered = (
        json.dumps(result.to_dict(), indent=2, sort_keys=True)
        if args.json
        else format_summary(result)
    )
    if args.out is not None:
        safe_write_report_text(args.out, rendered + "\n")
    else:
        print(rendered)
    return 0 if result.ok else 1


def _json_error_payload(error: str) -> dict[str, Any]:
    error_code = _error_code(error)
    return {
        "validation_schema_version": REPORT_BUNDLE_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def validate_report_output_path(*, bundle_root: Path, out_path: Path | None) -> None:
    if out_path is None:
        return
    if not _path_is_inside_directory(
        path=out_path,
        directory=bundle_root,
        resolve_symlinks=False,
    ) and not _path_is_inside_directory(
        path=out_path,
        directory=bundle_root,
        resolve_symlinks=True,
    ):
        if out_path.is_symlink():
            raise ValueError(REPORT_OUTPUT_PATH_SYMLINK_ERROR)
        if _path_has_symlink_parent(out_path):
            raise ValueError(REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)
        if out_path.exists() and out_path.is_dir():
            raise ValueError(REPORT_OUTPUT_PATH_DIRECTORY_ERROR)
        return
    raise ValueError("bundle report output path must be outside bundle root")


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def _path_is_inside_directory(
    *,
    path: Path,
    directory: Path,
    resolve_symlinks: bool,
) -> bool:
    if resolve_symlinks:
        candidate = path.resolve()
        root = directory.resolve()
    else:
        candidate = Path(os.path.abspath(path))
        root = Path(os.path.abspath(directory))
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
