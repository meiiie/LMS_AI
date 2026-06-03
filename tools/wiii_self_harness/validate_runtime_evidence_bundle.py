#!/usr/bin/env python3
"""Validate a directory of downloaded Wiii runtime evidence artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402
from strict_json import loads_strict_json  # noqa: E402
from validate_runtime_evidence_artifact import (  # noqa: E402
    normalize_artifact_error_code,
    validate_artifact,
)
from validate_runtime_evidence_registry import (  # noqa: E402
    ARTIFACT_NAME_RE,
    DEFAULT_REGISTRY,
    REGISTRY_NAME,
    load_registry,
    validate_registry as validate_registry_contract,
)
from validate_self_harness_report_bundle import (  # noqa: E402
    validate_report_bundle as validate_self_harness_report_bundle_contract,
)


BUNDLE_REPORT_SCHEMA_VERSION = "wiii.runtime_evidence_bundle_report.v1"
BUNDLE_REPORT_OUTPUT_PATH_DIRECTORY_ERROR = (
    "bundle report output path must not be a directory"
)
BUNDLE_REPORT_OUTPUT_PATH_SYMLINK_ERROR = (
    "bundle report output path must not be a symlink"
)
BUNDLE_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "bundle report output path parent must not be a symlink"
)
COMPLETION_AUDIT_LINK_REQUIRED_ERROR = (
    "completion audit requires --self-harness-report-bundle"
)


@dataclass(frozen=True)
class BundleRow:
    requirement_id: str
    artifact: str
    status: str
    path: str | None
    artifact_sha256: str | None
    checks_passed: int
    generated_at: str | None
    max_age_hours: int | None
    age_hours: float | None
    errors: list[str]


@dataclass(frozen=True)
class ReportBundleLink:
    bundle_root: str
    bundle_fingerprint_sha256: str
    validation_schema_version: str


@dataclass(frozen=True)
class BundleReport:
    schema_version: str
    registry_name: str
    registry_version: int
    bundle_root: str
    validated_at: str
    registry_fingerprint_sha256: str
    bundle_fingerprint_sha256: str
    completion_audit_fingerprint_sha256: str
    self_harness_report_bundle_root: str | None
    self_harness_report_bundle_fingerprint_sha256: str | None
    self_harness_report_bundle_validation_schema_version: str | None
    requirement_count: int
    row_count: int
    passed_count: int
    missing_count: int
    failed_count: int
    unexpected_count: int
    error_codes: list[str]
    error_code_counts: dict[str, int]
    rows: list[BundleRow]

    @property
    def ok(self) -> bool:
        return self.missing_count == 0 and self.failed_count == 0

    @property
    def completion_audit_ready(self) -> bool:
        return (
            self.ok
            and self.self_harness_report_bundle_root is not None
            and self.self_harness_report_bundle_fingerprint_sha256 is not None
            and self.self_harness_report_bundle_validation_schema_version is not None
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["completion_audit_ready"] = self.completion_audit_ready
        data["rows"] = [
            {
                **row_data,
                "error_codes": _row_error_codes(row),
            }
            for row_data, row in zip(data["rows"], self.rows, strict=True)
        ]
        return data


def validate_bundle(
    *,
    registry: dict[str, Any],
    bundle_root: Path,
    as_of: datetime | None = None,
    report_bundle_link: ReportBundleLink | None = None,
) -> BundleReport:
    if registry.get("registry") != REGISTRY_NAME:
        raise ValueError(f"registry `registry` must be {REGISTRY_NAME!r}")
    version = registry.get("version")
    if not _is_positive_int(version):
        raise ValueError("registry `version` must be an integer >= 1")
    requirements = registry.get("requirements")
    if not isinstance(requirements, list):
        raise ValueError("registry `requirements` must be a list")
    if not requirements:
        raise ValueError("registry `requirements` must be a non-empty list")
    if not bundle_root.exists():
        raise ValueError(f"bundle root does not exist: {bundle_root}")
    if bundle_root.is_symlink():
        raise ValueError(f"bundle root must not be a symlink: {bundle_root}")
    if not bundle_root.is_dir():
        raise ValueError(f"bundle root must be a directory: {bundle_root}")

    effective_as_of = as_of or datetime.now(timezone.utc)
    if effective_as_of.tzinfo is None:
        effective_as_of = effective_as_of.replace(tzinfo=timezone.utc)
    else:
        effective_as_of = effective_as_of.astimezone(timezone.utc)

    requirement_id_counts: dict[str, int] = {}
    artifact_counts: dict[str, int] = {}
    registered_artifact_names: set[str] = set()
    for item in requirements:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("id") or "")
        artifact = str(item.get("artifact") or "")
        if requirement_id:
            requirement_id_counts[requirement_id] = (
                requirement_id_counts.get(requirement_id, 0) + 1
            )
        if ARTIFACT_NAME_RE.match(artifact):
            registered_artifact_names.add(artifact)
            artifact_counts[artifact] = artifact_counts.get(artifact, 0) + 1

    rows: list[BundleRow] = []
    for item in requirements:
        if not isinstance(item, dict):
            rows.append(
                BundleRow(
                    requirement_id="",
                    artifact="",
                    status="failed",
                    path=None,
                    artifact_sha256=None,
                    checks_passed=0,
                    generated_at=None,
                    max_age_hours=None,
                    age_hours=None,
                    errors=["registry requirement must be an object"],
                )
            )
            continue
        requirement_id = str(item.get("id") or "")
        artifact = str(item.get("artifact") or "")
        contract_errors: list[str] = []
        if requirement_id and requirement_id_counts.get(requirement_id, 0) > 1:
            contract_errors.append(f"duplicate requirement id {requirement_id!r}")
        if not ARTIFACT_NAME_RE.match(artifact):
            contract_errors.append(
                "unsafe artifact name; expected lowercase kebab-case JSON file name"
            )
        elif artifact_counts.get(artifact, 0) > 1:
            contract_errors.append(f"duplicate artifact name {artifact!r}")
        if contract_errors:
            rows.append(
                BundleRow(
                    requirement_id=requirement_id,
                    artifact=artifact,
                    status="failed",
                    path=None,
                    artifact_sha256=None,
                    checks_passed=0,
                    generated_at=None,
                    max_age_hours=_freshness_max_age(item),
                    age_hours=None,
                    errors=contract_errors,
                )
            )
            continue
        matches = sorted(bundle_root.rglob(artifact))
        if not matches:
            rows.append(
                BundleRow(
                    requirement_id=requirement_id,
                    artifact=artifact,
                    status="missing",
                    path=None,
                    artifact_sha256=None,
                    checks_passed=0,
                    generated_at=None,
                    max_age_hours=_freshness_max_age(item),
                    age_hours=None,
                    errors=[f"missing artifact {artifact!r}"],
                )
            )
            continue
        if len(matches) > 1:
            duplicate_sha256, duplicate_path_errors = _matching_artifacts_manifest(
                bundle_root=bundle_root,
                artifact_paths=matches,
            )
            rows.append(
                BundleRow(
                    requirement_id=requirement_id,
                    artifact=artifact,
                    status="failed",
                    path=None,
                    artifact_sha256=duplicate_sha256,
                    checks_passed=0,
                    generated_at=None,
                    max_age_hours=_freshness_max_age(item),
                    age_hours=None,
                    errors=[
                        "multiple matching artifacts: "
                        + ", ".join(str(path) for path in matches),
                        *duplicate_path_errors,
                    ],
                )
            )
            continue

        artifact_path = matches[0]
        path_errors = validate_artifact_path(
            bundle_root=bundle_root,
            artifact_path=artifact_path,
        )
        if path_errors:
            rows.append(
                BundleRow(
                    requirement_id=requirement_id,
                    artifact=artifact,
                    status="failed",
                    path=str(artifact_path),
                    artifact_sha256=None,
                    checks_passed=0,
                    generated_at=None,
                    max_age_hours=_freshness_max_age(item),
                    age_hours=None,
                    errors=path_errors,
                )
            )
            continue
        artifact_sha256 = _sha256_file(artifact_path)
        result = validate_artifact(
            registry=registry,
            artifact_path=artifact_path,
            requirement_id=requirement_id,
            as_of=effective_as_of,
            enforce_freshness=False,
        )
        freshness = validate_freshness(
            requirement=item,
            artifact_path=artifact_path,
            as_of=effective_as_of,
        )
        errors = [*result.errors, *freshness["errors"]]
        if artifact_sha256 is None:
            errors.append("could not compute artifact sha256")
        rows.append(
            BundleRow(
                requirement_id=requirement_id,
                artifact=artifact,
                status="passed" if not errors else "failed",
                path=str(artifact_path),
                artifact_sha256=artifact_sha256,
                checks_passed=result.passed_checks,
                generated_at=freshness["generated_at"],
                max_age_hours=freshness["max_age_hours"],
                age_hours=freshness["age_hours"],
                errors=errors,
            )
        )

    rows.extend(
        _unexpected_artifact_rows(
            bundle_root=bundle_root,
            registered_artifact_names=registered_artifact_names,
        )
    )
    passed_count = sum(1 for row in rows if row.status == "passed")
    missing_count = sum(1 for row in rows if row.status == "missing")
    failed_count = sum(1 for row in rows if row.status == "failed")
    unexpected_count = sum(1 for row in rows if _is_unexpected_artifact_row(row))
    error_code_counts = _error_code_counts(rows)
    registry_fingerprint_sha256 = _registry_fingerprint(registry)
    validated_at = _format_utc_timestamp(effective_as_of)
    bundle_fingerprint_sha256 = _bundle_fingerprint(
        rows,
        bundle_root=bundle_root,
        registry_fingerprint_sha256=registry_fingerprint_sha256,
        schema_version=BUNDLE_REPORT_SCHEMA_VERSION,
        validated_at=validated_at,
    )
    return BundleReport(
        schema_version=BUNDLE_REPORT_SCHEMA_VERSION,
        registry_name=REGISTRY_NAME,
        registry_version=version,
        bundle_root=str(bundle_root),
        validated_at=validated_at,
        registry_fingerprint_sha256=registry_fingerprint_sha256,
        bundle_fingerprint_sha256=bundle_fingerprint_sha256,
        completion_audit_fingerprint_sha256=_completion_audit_fingerprint(
            bundle_fingerprint_sha256=bundle_fingerprint_sha256,
            report_bundle_link=report_bundle_link,
        ),
        self_harness_report_bundle_root=(
            None if report_bundle_link is None else report_bundle_link.bundle_root
        ),
        self_harness_report_bundle_fingerprint_sha256=(
            None
            if report_bundle_link is None
            else report_bundle_link.bundle_fingerprint_sha256
        ),
        self_harness_report_bundle_validation_schema_version=(
            None
            if report_bundle_link is None
            else report_bundle_link.validation_schema_version
        ),
        requirement_count=len(requirements),
        row_count=len(rows),
        passed_count=passed_count,
        missing_count=missing_count,
        failed_count=failed_count,
        unexpected_count=unexpected_count,
        error_codes=list(error_code_counts.keys()),
        error_code_counts=error_code_counts,
        rows=rows,
    )


def require_valid_registry_contract(registry: dict[str, Any], *, registry_path: Path) -> None:
    result = validate_registry_contract(registry, registry_path=registry_path)
    if result.ok:
        return
    codes = ", ".join(result.to_dict()["error_codes"])
    preview = "; ".join(result.errors[:3])
    if len(result.errors) > 3:
        preview = f"{preview}; ... {len(result.errors) - 3} more"
    raise ValueError(f"registry validation failed ({codes}): {preview}")


def require_registry_matches_report_bundle(
    registry: dict[str, Any],
    *,
    report_bundle_root: Path | None,
) -> ReportBundleLink | None:
    if report_bundle_root is None:
        return None
    if not report_bundle_root.exists():
        raise ValueError(
            f"self-harness report bundle root does not exist: {report_bundle_root}"
        )
    if report_bundle_root.is_symlink():
        raise ValueError(
            f"self-harness report bundle root must not be a symlink: {report_bundle_root}"
        )
    if not report_bundle_root.is_dir():
        raise ValueError(
            f"self-harness report bundle root must be a directory: {report_bundle_root}"
        )
    report_bundle_link = require_valid_self_harness_report_bundle(report_bundle_root)

    coverage_path = report_bundle_root / "runtime-evidence-coverage.json"
    if not coverage_path.exists():
        raise ValueError(
            "runtime-evidence-coverage.json report file is missing from "
            f"self-harness report bundle: {report_bundle_root}"
        )
    if coverage_path.is_symlink():
        raise ValueError(
            "runtime-evidence-coverage.json report file must not be a symlink"
        )
    if not coverage_path.is_file():
        raise ValueError("runtime-evidence-coverage.json report path must be a file")
    try:
        coverage_payload = loads_strict_json(coverage_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"report bundle coverage JSON is invalid: {exc}") from exc
    if not isinstance(coverage_payload, dict):
        raise ValueError("report bundle coverage root must be a JSON object")

    expected_fingerprint = _registry_fingerprint(registry)
    observed_fingerprint = coverage_payload.get("registry_fingerprint_sha256")
    if observed_fingerprint != expected_fingerprint:
        raise ValueError(
            "report bundle coverage registry_fingerprint_sha256 must match "
            f"runtime evidence registry {expected_fingerprint}, got "
            f"{observed_fingerprint!r}"
        )

    expected_version = registry.get("version")
    if coverage_payload.get("registry_version") != expected_version:
        raise ValueError(
            "report bundle coverage registry_version must match runtime evidence "
            f"registry {expected_version}, got {coverage_payload.get('registry_version')!r}"
        )

    requirements = registry.get("requirements")
    expected_count = len(requirements) if isinstance(requirements, list) else None
    if coverage_payload.get("requirement_count") != expected_count:
        raise ValueError(
            "report bundle coverage requirement_count must match runtime evidence "
            f"registry {expected_count}, got {coverage_payload.get('requirement_count')!r}"
        )
    return report_bundle_link


def require_valid_self_harness_report_bundle(
    report_bundle_root: Path,
) -> ReportBundleLink:
    result = validate_self_harness_report_bundle_contract(
        report_bundle_root,
        require_self_validation=True,
        require_no_synthetic_gaps=True,
        require_credentialed_external_contracts=True,
    )
    payload = result.to_dict()
    if result.ok:
        bundle_fingerprint = payload.get("bundle_fingerprint_sha256")
        validation_schema = payload.get("validation_schema_version")
        if not isinstance(bundle_fingerprint, str) or not bundle_fingerprint:
            raise ValueError(
                "self-harness report bundle validation result is missing "
                "bundle_fingerprint_sha256"
            )
        if not isinstance(validation_schema, str) or not validation_schema:
            raise ValueError(
                "self-harness report bundle validation result is missing "
                "validation_schema_version"
            )
        return ReportBundleLink(
            bundle_root=str(report_bundle_root),
            bundle_fingerprint_sha256=bundle_fingerprint,
            validation_schema_version=validation_schema,
        )
    codes = ", ".join(payload.get("error_codes") or ["validation_error"])
    errors = _report_bundle_validation_errors(payload)
    preview = "; ".join(errors[:3])
    if len(errors) > 3:
        preview = f"{preview}; ... {len(errors) - 3} more"
    raise ValueError(
        f"self-harness report bundle validation failed ({codes}): {preview}"
    )


def _report_bundle_validation_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        row_errors = row.get("errors")
        if isinstance(row_errors, list):
            errors.extend(error for error in row_errors if isinstance(error, str))
    if errors:
        return errors
    top_level_errors = payload.get("errors")
    if isinstance(top_level_errors, list):
        errors.extend(error for error in top_level_errors if isinstance(error, str))
    return errors or ["self-harness report bundle is invalid"]


def format_markdown(report: BundleReport) -> str:
    status = "PASS" if report.ok else "FAIL"
    lines = [
        "# Wiii Runtime Evidence Bundle",
        "",
        f"- Schema version: `{report.schema_version}`",
        f"- Registry name: `{report.registry_name}`",
        f"- Registry version: `{report.registry_version}`",
        f"- Bundle root: `{report.bundle_root}`",
        f"- Validated at: `{report.validated_at}`",
        f"- Registry fingerprint SHA-256: `{report.registry_fingerprint_sha256}`",
        f"- Bundle fingerprint SHA-256: `{report.bundle_fingerprint_sha256}`",
        "- Completion audit fingerprint SHA-256: "
        f"`{report.completion_audit_fingerprint_sha256}`",
        "- Self-harness report bundle: "
        f"`{report.self_harness_report_bundle_root or '-'}`",
        "- Self-harness report bundle fingerprint SHA-256: "
        f"`{report.self_harness_report_bundle_fingerprint_sha256 or '-'}`",
        "- Self-harness report bundle validation schema: "
        f"`{report.self_harness_report_bundle_validation_schema_version or '-'}`",
        f"- Completion audit ready: `{str(report.completion_audit_ready).lower()}`",
        f"- Status: `{status}`",
        f"- Requirements: `{report.requirement_count}`",
        f"- Rows: `{report.row_count}`",
        f"- Passed: `{report.passed_count}`",
        f"- Missing: `{report.missing_count}`",
        f"- Failed: `{report.failed_count}`",
        f"- Unexpected: `{report.unexpected_count}`",
        f"- Error codes: `{', '.join(report.error_codes) or '-'}`",
        f"- Error code counts: `{_format_error_code_counts(report.error_code_counts)}`",
        "",
        "| Requirement | Artifact | SHA-256 | Status | Checks | Freshness | Path | Error codes | Errors |",
        "|---|---|---|---|---:|---|---|---|---|",
    ]
    for row in report.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.requirement_id),
                    _cell(row.artifact),
                    _cell(row.artifact_sha256 or ""),
                    _cell(row.status),
                    str(row.checks_passed),
                    _cell(_freshness_cell(row)),
                    _cell(row.path or ""),
                    _cell(", ".join(_row_error_codes(row))),
                    _cell("; ".join(row.errors)),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def validate_artifact_path(*, bundle_root: Path, artifact_path: Path) -> list[str]:
    errors: list[str] = []
    if artifact_path.is_symlink():
        errors.append(f"artifact path must not be a symlink: {artifact_path}")
    try:
        artifact_path.resolve().relative_to(bundle_root.resolve())
    except ValueError:
        errors.append(f"artifact path escapes bundle root: {artifact_path}")
    if not artifact_path.is_file():
        errors.append(f"artifact path must be a file: {artifact_path}")
    return errors


def _cell(value: str) -> str:
    normalized = " ".join(value.replace("|", "\\|").split())
    return normalized or "-"


def _sha256_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _matching_artifacts_manifest(
    *,
    bundle_root: Path,
    artifact_paths: list[Path],
) -> tuple[str, list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in artifact_paths:
        path_errors = validate_artifact_path(
            bundle_root=bundle_root,
            artifact_path=path,
        )
        errors.extend(path_errors)
        entries.append(
            {
                "path": _bundle_relative_path(bundle_root=bundle_root, path=path),
                "artifact_sha256": None if path_errors else _sha256_file(path),
                "error_codes": [_error_code(error) for error in path_errors],
            }
        )
    encoded = json.dumps(
        entries,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), errors


def _bundle_relative_path(*, bundle_root: Path, path: Path) -> str:
    try:
        return Path(os.path.abspath(path)).relative_to(
            Path(os.path.abspath(bundle_root))
        ).as_posix()
    except ValueError:
        return str(path)


def _unexpected_artifact_rows(
    *,
    bundle_root: Path,
    registered_artifact_names: set[str],
) -> list[BundleRow]:
    rows: list[BundleRow] = []
    for path in sorted(bundle_root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        if path.name in registered_artifact_names:
            continue
        path_errors = validate_artifact_path(
            bundle_root=bundle_root,
            artifact_path=path,
        )
        rows.append(
            BundleRow(
                requirement_id="",
                artifact=path.name,
                status="failed",
                path=str(path),
                artifact_sha256=None if path_errors else _sha256_file(path),
                checks_passed=0,
                generated_at=None,
                max_age_hours=None,
                age_hours=None,
                errors=[
                    f"unexpected unregistered artifact {path.name!r}",
                    *path_errors,
                ],
            )
        )
    return rows


def _is_unexpected_artifact_row(row: BundleRow) -> bool:
    return any(error.startswith("unexpected unregistered artifact ") for error in row.errors)


def _registry_fingerprint(registry: dict[str, Any]) -> str:
    contract = {
        "registry": registry.get("registry"),
        "version": registry.get("version"),
        "requirements": registry.get("requirements"),
    }
    encoded = json.dumps(
        contract,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bundle_fingerprint(
    rows: list[BundleRow],
    *,
    bundle_root: Path,
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
                "requirement_id": row.requirement_id,
                "artifact": row.artifact,
                "artifact_sha256": row.artifact_sha256,
                "errors": row.errors,
                "error_codes": _row_error_codes(row),
                "path": _row_fingerprint_path(bundle_root=bundle_root, row=row),
                "status": row.status,
                "checks_passed": row.checks_passed,
                "generated_at": row.generated_at,
                "max_age_hours": row.max_age_hours,
                "age_hours": row.age_hours,
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


def _completion_audit_fingerprint(
    *,
    bundle_fingerprint_sha256: str,
    report_bundle_link: ReportBundleLink | None,
) -> str:
    report_bundle_manifest = None
    if report_bundle_link is not None:
        report_bundle_manifest = {
            "bundle_fingerprint_sha256": (
                report_bundle_link.bundle_fingerprint_sha256
            ),
            "validation_schema_version": report_bundle_link.validation_schema_version,
        }
    manifest = {
        "runtime_evidence_bundle_fingerprint_sha256": bundle_fingerprint_sha256,
        "self_harness_report_bundle": report_bundle_manifest,
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_fingerprint_path(*, bundle_root: Path, row: BundleRow) -> str | None:
    if row.path is None:
        return None
    return _bundle_relative_path(bundle_root=bundle_root, path=Path(row.path))


def _row_error_codes(row: BundleRow) -> list[str]:
    return sorted({_error_code(error) for error in row.errors})


def _error_code_counts(rows: list[BundleRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for error_code in _row_error_codes(row):
            counts[error_code] = counts.get(error_code, 0) + 1
    return dict(sorted(counts.items()))


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def _error_code(error: str) -> str:
    artifact_code = normalize_artifact_error_code(error)
    if artifact_code != "validation_error":
        return artifact_code
    if error == "registry requirement must be an object":
        return "registry_requirement_not_object"
    if error.startswith("duplicate requirement id "):
        return "duplicate_requirement_id"
    if error.startswith("registry validation failed "):
        return "registry_contract_invalid"
    if error.startswith("duplicate artifact name "):
        return "duplicate_artifact_name"
    if error.startswith("unsafe artifact name;"):
        return "unsafe_artifact_name"
    if error.startswith("missing artifact "):
        return "missing_artifact"
    if error.startswith("multiple matching artifacts:"):
        return "multiple_matching_artifacts"
    if error.startswith("unexpected unregistered artifact "):
        return "unexpected_unregistered_artifact"
    if error.startswith("artifact path must not be a symlink:"):
        return "artifact_path_symlink"
    if error.startswith("artifact path escapes bundle root:"):
        return "artifact_path_escapes_bundle_root"
    if error.startswith("artifact path must be a file:"):
        return "artifact_path_not_file"
    if error == "missing freshness policy":
        return "missing_freshness_policy"
    if error == "freshness timestamp_path is missing":
        return "freshness_timestamp_path_missing"
    if error == "freshness max_age_hours is missing":
        return "freshness_max_age_hours_missing"
    if error.startswith("could not read artifact for freshness:"):
        return "freshness_artifact_read_failed"
    if error.startswith("freshness timestamp ") and error.endswith(" is missing"):
        return "freshness_timestamp_missing"
    if error.startswith("freshness timestamp is not ISO-8601:"):
        return "freshness_timestamp_invalid_iso8601"
    if error.startswith("freshness timestamp must include timezone:"):
        return "freshness_timestamp_missing_timezone"
    if error.startswith("artifact timestamp ") and error.endswith(" is in the future"):
        return "freshness_timestamp_future"
    if error.startswith("artifact is stale:"):
        return "freshness_stale"
    if error == "could not compute artifact sha256":
        return "artifact_sha256_unavailable"
    if error.startswith("registry `registry` must be "):
        return "registry_identity_mismatch"
    if error == "registry `version` must be an integer >= 1":
        return "registry_version_invalid"
    if error == "registry `requirements` must be a list":
        return "registry_requirements_not_list"
    if error == "registry `requirements` must be a non-empty list":
        return "registry_requirements_empty"
    if error.startswith("bundle root does not exist:"):
        return "bundle_root_missing"
    if error.startswith("bundle root must not be a symlink:"):
        return "bundle_root_symlink"
    if error.startswith("bundle root must be a directory:"):
        return "bundle_root_not_directory"
    if error == "bundle registry path must be outside bundle root":
        return "bundle_registry_path_inside_bundle_root"
    if error == COMPLETION_AUDIT_LINK_REQUIRED_ERROR:
        return "completion_audit_link_missing"
    if error.startswith("self-harness report bundle root does not exist:"):
        return "self_harness_report_bundle_root_missing"
    if error.startswith("self-harness report bundle root must not be a symlink:"):
        return "self_harness_report_bundle_root_symlink"
    if error.startswith("self-harness report bundle root must be a directory:"):
        return "self_harness_report_bundle_root_not_directory"
    if error.startswith("self-harness report bundle validation failed "):
        return "self_harness_report_bundle_invalid"
    if error.startswith("runtime-evidence-coverage.json report file is missing"):
        return "report_bundle_coverage_missing"
    if error == "runtime-evidence-coverage.json report file must not be a symlink":
        return "report_bundle_coverage_symlink"
    if error == "runtime-evidence-coverage.json report path must be a file":
        return "report_bundle_coverage_not_file"
    if error.startswith("report bundle coverage JSON is invalid:"):
        return "report_bundle_coverage_invalid"
    if error == "report bundle coverage root must be a JSON object":
        return "report_bundle_coverage_root_not_object"
    if "coverage registry_fingerprint_sha256 must match runtime evidence registry" in error:
        return "report_bundle_registry_fingerprint_mismatch"
    if "coverage registry_version must match runtime evidence registry" in error:
        return "report_bundle_registry_version_mismatch"
    if "coverage requirement_count must match runtime evidence registry" in error:
        return "report_bundle_requirement_count_mismatch"
    if error == "bundle report output path must be outside bundle root":
        return "bundle_report_output_path_inside_bundle_root"
    if error == BUNDLE_REPORT_OUTPUT_PATH_SYMLINK_ERROR:
        return "bundle_report_output_path_symlink"
    if error == BUNDLE_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "bundle_report_output_path_parent_symlink"
    if error == BUNDLE_REPORT_OUTPUT_PATH_DIRECTORY_ERROR:
        return "bundle_report_output_path_directory"
    return "validation_error"


def validate_freshness(
    *,
    requirement: dict[str, Any],
    artifact_path: Path,
    as_of: datetime,
) -> dict[str, Any]:
    freshness = requirement.get("freshness")
    max_age_hours = _freshness_max_age(requirement)
    result: dict[str, Any] = {
        "generated_at": None,
        "max_age_hours": max_age_hours,
        "age_hours": None,
        "errors": [],
    }
    if not isinstance(freshness, dict):
        result["errors"].append("missing freshness policy")
        return result

    timestamp_path = freshness.get("timestamp_path")
    if not isinstance(timestamp_path, str) or not timestamp_path:
        result["errors"].append("freshness timestamp_path is missing")
        return result
    if max_age_hours is None:
        result["errors"].append("freshness max_age_hours is missing")
        return result

    try:
        payload = loads_strict_json(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"could not read artifact for freshness: {exc}")
        return result
    generated_at = _get_path(payload, timestamp_path)
    result["generated_at"] = generated_at if isinstance(generated_at, str) else None
    if not isinstance(generated_at, str) or not generated_at.strip():
        result["errors"].append(f"freshness timestamp {timestamp_path!r} is missing")
        return result

    try:
        generated_dt = _parse_timestamp(generated_at)
    except ValueError as exc:
        result["errors"].append(str(exc))
        return result
    age_hours = (as_of - generated_dt).total_seconds() / 3600
    result["age_hours"] = round(age_hours, 3)
    if age_hours < 0:
        result["errors"].append(
            f"artifact timestamp {generated_at!r} is in the future"
        )
    elif age_hours > max_age_hours:
        result["errors"].append(
            f"artifact is stale: age_hours={age_hours:.2f} max_age_hours={max_age_hours}"
        )
    return result


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"freshness timestamp is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"freshness timestamp must include timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _freshness_max_age(requirement: dict[str, Any]) -> int | None:
    freshness = requirement.get("freshness")
    if not isinstance(freshness, dict):
        return None
    max_age_hours = freshness.get("max_age_hours")
    return max_age_hours if _is_positive_int(max_age_hours) else None


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _get_path(payload: Any, raw_path: str) -> Any:
    value = payload
    for part in raw_path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
        else:
            return None
    return value


def _freshness_cell(row: BundleRow) -> str:
    if row.generated_at is None:
        return "-"
    age = "-" if row.age_hours is None else f"{row.age_hours:.2f}h"
    max_age = "-" if row.max_age_hours is None else f"{row.max_age_hours}h"
    return f"{age} / {max_age}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate downloaded Wiii runtime evidence artifacts.",
    )
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        default=None,
        help=(
            "Require this downloaded self-harness report bundle's coverage JSON "
            "to match the runtime evidence registry contract."
        ),
    )
    parser.add_argument(
        "--require-completion-audit-link",
        action="store_true",
        help=(
            "Fail unless --self-harness-report-bundle is provided, validated, "
            "and linked into the runtime evidence bundle report."
        ),
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp used for freshness checks; defaults to now.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if (
            args.require_completion_audit_link
            and args.self_harness_report_bundle is None
        ):
            raise ValueError(COMPLETION_AUDIT_LINK_REQUIRED_ERROR)
        validate_registry_input_path(
            bundle_root=args.bundle_root,
            registry_path=args.registry,
        )
        validate_report_output_path(
            bundle_root=args.bundle_root,
            out_path=args.out,
        )
        registry = load_registry(args.registry)
        require_valid_registry_contract(registry, registry_path=args.registry)
        report_bundle_link = require_registry_matches_report_bundle(
            registry,
            report_bundle_root=args.self_harness_report_bundle,
        )
        as_of = _parse_timestamp(args.as_of) if args.as_of else None
        report = validate_bundle(
            registry=registry,
            bundle_root=args.bundle_root,
            as_of=as_of,
            report_bundle_link=report_bundle_link,
        )
    except Exception as exc:  # noqa: BLE001
        if args.format == "json":
            print(
                json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True),
                file=sys.stdout,
            )
        else:
            print(f"Wiii Runtime Evidence Bundle: FAIL\n- {exc}", file=sys.stderr)
        return 1

    rendered = (
        json.dumps(report.to_dict(), indent=2, sort_keys=True)
        if args.format == "json"
        else format_markdown(report)
    )
    if args.out is not None:
        safe_write_report_text(args.out, rendered + "\n")
    else:
        print(rendered)
    return 0 if report.ok else 1


def _json_error_payload(error: str) -> dict[str, Any]:
    error_code = _error_code(error)
    return {
        "schema_version": BUNDLE_REPORT_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def validate_registry_input_path(*, bundle_root: Path, registry_path: Path) -> None:
    if not _path_is_inside_directory(
        path=registry_path,
        directory=bundle_root,
        resolve_symlinks=False,
    ) and not _path_is_inside_directory(
        path=registry_path,
        directory=bundle_root,
        resolve_symlinks=True,
    ):
        return
    raise ValueError("bundle registry path must be outside bundle root")


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
            raise ValueError(BUNDLE_REPORT_OUTPUT_PATH_SYMLINK_ERROR)
        if _path_has_symlink_parent(out_path):
            raise ValueError(BUNDLE_REPORT_OUTPUT_PATH_PARENT_SYMLINK_ERROR)
        if out_path.exists() and out_path.is_dir():
            raise ValueError(BUNDLE_REPORT_OUTPUT_PATH_DIRECTORY_ERROR)
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
