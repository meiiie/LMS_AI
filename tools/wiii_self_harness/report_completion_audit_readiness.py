#!/usr/bin/env python3
"""Report completion-audit readiness, including an explicit scoped view."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

import validate_runtime_evidence_bundle as bundle_validator  # noqa: E402
import validate_runtime_evidence_preflight as preflight_validator  # noqa: E402
from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
)


READINESS_REPORT_SCHEMA_VERSION = "wiii.completion_audit_readiness_report.v1"
READINESS_SCOPE_EMPTY_ERROR = "completion audit readiness scope must include at least one requirement"
PREFLIGHT_SCHEMA_REQUIREMENT_IDS = {
    "wiii.provider_runtime_preflight.v1": "provider-runtime-tool-loop",
    "wiii.proactive_channel_preflight.v1": "autonomy-proactive-channel",
    "wiii.connect_composio_acceptance_preflight.v1": (
        "wiii-connect-composio-acceptance"
    ),
    "wiii.lms_test_course_preflight.v1": "lms-test-course-replay",
}


@dataclass(frozen=True)
class ReadinessPreflightSummary:
    requirement_id: str
    schema_version: str
    status: str
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
class ReadinessRow:
    requirement_id: str
    artifact: str
    status: str
    included_in_scope: bool
    error_codes: list[str]


@dataclass(frozen=True)
class ReadinessDiagnosticUpload:
    artifact: str
    path: str
    artifact_tokens: list[str]
    if_no_files_found: str
    retention_days: int


@dataclass(frozen=True)
class ReadinessNextAction:
    requirement_id: str
    title: str
    layer: str
    artifact: str
    schema_version: str
    status: str
    workflow: str
    probe: str
    live_env_flags: list[str]
    live_guard_tokens: list[str]
    dispatch_or_schedule_gate_tokens: list[str]
    artifact_tokens: list[str]
    diagnostic_uploads: list[ReadinessDiagnosticUpload]
    error_codes: list[str]
    blocked_by_live_setup: bool
    preflight_status: str
    preflight_schema_version: str
    preflight_generated_at: str
    preflight_required_next: list[str]
    preflight_source_file: str


@dataclass(frozen=True)
class ReadinessReport:
    schema_version: str
    registry_name: str
    registry_version: int
    registry_fingerprint_sha256: str
    bundle_root: str
    bundle_fingerprint_sha256: str
    completion_audit_fingerprint_sha256: str
    self_harness_report_bundle_root: str | None
    self_harness_report_bundle_fingerprint_sha256: str | None
    self_harness_report_bundle_validation_schema_version: str | None
    full_completion_audit_ready: bool
    scoped_completion_audit_ready: bool
    full_requirement_count: int
    full_passed_count: int
    full_missing_count: int
    full_failed_count: int
    scoped_requirement_count: int
    scoped_passed_count: int
    scoped_missing_count: int
    scoped_failed_count: int
    excluded_requirement_ids: list[str]
    unknown_excluded_requirement_ids: list[str]
    full_missing_requirement_ids: list[str]
    full_failed_requirement_ids: list[str]
    scoped_missing_requirement_ids: list[str]
    scoped_failed_requirement_ids: list[str]
    full_live_setup_blocked_count: int
    full_live_setup_blocked_requirement_ids: list[str]
    scoped_live_setup_blocked_count: int
    scoped_live_setup_blocked_requirement_ids: list[str]
    readiness_blockers: list[str]
    scoped_readiness_blockers: list[str]
    scoped_next_action_count: int
    scoped_next_actions_fingerprint_sha256: str
    scoped_next_actions: list[ReadinessNextAction]
    preflight_summary_count: int
    preflight_summaries: list[ReadinessPreflightSummary]
    rows: list[ReadinessRow]
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


def build_readiness_report(
    *,
    registry: dict[str, Any],
    bundle_root: Path,
    excluded_requirement_ids: list[str] | None = None,
    as_of: datetime | None = None,
    report_bundle_link: bundle_validator.ReportBundleLink | None = None,
    preflight_summaries: dict[str, ReadinessPreflightSummary] | None = None,
) -> ReadinessReport:
    excluded_ids = sorted(set(excluded_requirement_ids or []))
    excluded_id_set = set(excluded_ids)
    requirements_by_id = _requirements_by_id(registry)
    bundle_report = bundle_validator.validate_bundle(
        registry=registry,
        bundle_root=bundle_root,
        as_of=as_of,
        report_bundle_link=report_bundle_link,
    )
    known_ids = {row.requirement_id for row in bundle_report.rows}
    unknown_excluded_ids = sorted(set(excluded_ids) - known_ids)
    included_rows = [
        row for row in bundle_report.rows if row.requirement_id not in excluded_id_set
    ]
    errors: list[str] = []
    if unknown_excluded_ids:
        errors.append(
            "unknown excluded completion audit requirement id(s): "
            + ", ".join(unknown_excluded_ids)
        )
    if not included_rows:
        errors.append(READINESS_SCOPE_EMPTY_ERROR)

    scoped_missing_rows = [row for row in included_rows if row.status == "missing"]
    scoped_failed_rows = [row for row in included_rows if row.status == "failed"]
    preflights = preflight_summaries or {}
    full_live_setup_blocked_requirement_ids = _live_setup_blocked_requirement_ids(
        rows=bundle_report.rows,
        preflight_summaries=preflights,
    )
    scoped_live_setup_blocked_requirement_ids = _live_setup_blocked_requirement_ids(
        rows=included_rows,
        preflight_summaries=preflights,
    )
    scoped_next_actions = _scoped_next_actions(
        rows=included_rows,
        requirements_by_id=requirements_by_id,
        preflight_summaries=preflights,
    )
    scoped_completion_audit_ready = (
        not errors
        and not scoped_missing_rows
        and not scoped_failed_rows
        and bundle_report.self_harness_report_bundle_root is not None
        and bundle_report.self_harness_report_bundle_fingerprint_sha256 is not None
        and bundle_report.self_harness_report_bundle_validation_schema_version is not None
    )

    return ReadinessReport(
        schema_version=READINESS_REPORT_SCHEMA_VERSION,
        registry_name=bundle_report.registry_name,
        registry_version=bundle_report.registry_version,
        registry_fingerprint_sha256=bundle_report.registry_fingerprint_sha256,
        bundle_root=bundle_report.bundle_root,
        bundle_fingerprint_sha256=bundle_report.bundle_fingerprint_sha256,
        completion_audit_fingerprint_sha256=(
            bundle_report.completion_audit_fingerprint_sha256
        ),
        self_harness_report_bundle_root=bundle_report.self_harness_report_bundle_root,
        self_harness_report_bundle_fingerprint_sha256=(
            bundle_report.self_harness_report_bundle_fingerprint_sha256
        ),
        self_harness_report_bundle_validation_schema_version=(
            bundle_report.self_harness_report_bundle_validation_schema_version
        ),
        full_completion_audit_ready=bundle_report.completion_audit_ready,
        scoped_completion_audit_ready=scoped_completion_audit_ready,
        full_requirement_count=bundle_report.requirement_count,
        full_passed_count=bundle_report.passed_count,
        full_missing_count=bundle_report.missing_count,
        full_failed_count=bundle_report.failed_count,
        scoped_requirement_count=len(included_rows),
        scoped_passed_count=sum(1 for row in included_rows if row.status == "passed"),
        scoped_missing_count=len(scoped_missing_rows),
        scoped_failed_count=len(scoped_failed_rows),
        excluded_requirement_ids=excluded_ids,
        unknown_excluded_requirement_ids=unknown_excluded_ids,
        full_missing_requirement_ids=_requirement_ids_with_status(
            bundle_report.rows,
            "missing",
        ),
        full_failed_requirement_ids=_requirement_ids_with_status(
            bundle_report.rows,
            "failed",
        ),
        scoped_missing_requirement_ids=[
            row.requirement_id for row in scoped_missing_rows
        ],
        scoped_failed_requirement_ids=[row.requirement_id for row in scoped_failed_rows],
        full_live_setup_blocked_count=len(full_live_setup_blocked_requirement_ids),
        full_live_setup_blocked_requirement_ids=(
            full_live_setup_blocked_requirement_ids
        ),
        scoped_live_setup_blocked_count=len(scoped_live_setup_blocked_requirement_ids),
        scoped_live_setup_blocked_requirement_ids=(
            scoped_live_setup_blocked_requirement_ids
        ),
        readiness_blockers=_readiness_blockers(
            rows=bundle_report.rows,
            self_harness_linked=bundle_report.completion_audit_ready
            or bundle_report.self_harness_report_bundle_root is not None,
        ),
        scoped_readiness_blockers=_readiness_blockers(
            rows=included_rows,
            self_harness_linked=bundle_report.self_harness_report_bundle_root
            is not None,
        ),
        scoped_next_action_count=len(scoped_next_actions),
        scoped_next_actions_fingerprint_sha256=_next_actions_fingerprint(
            scoped_next_actions
        ),
        scoped_next_actions=scoped_next_actions,
        preflight_summary_count=len(preflight_summaries or {}),
        preflight_summaries=sorted(
            list((preflight_summaries or {}).values()),
            key=lambda item: item.requirement_id,
        ),
        rows=[
            ReadinessRow(
                requirement_id=row.requirement_id,
                artifact=row.artifact,
                status=row.status,
                included_in_scope=row.requirement_id not in excluded_id_set,
                error_codes=bundle_validator._row_error_codes(row),
            )
            for row in bundle_report.rows
        ],
        errors=errors,
    )


def format_markdown(report: ReadinessReport) -> str:
    lines = [
        "# Wiii Completion Audit Readiness",
        "",
        f"- Report schema: `{report.schema_version}`",
        f"- Registry name: `{report.registry_name}`",
        f"- Registry version: `{report.registry_version}`",
        f"- Registry fingerprint SHA-256: `{report.registry_fingerprint_sha256}`",
        f"- Bundle root: `{report.bundle_root}`",
        f"- Bundle fingerprint SHA-256: `{report.bundle_fingerprint_sha256}`",
        f"- Completion audit fingerprint SHA-256: `{report.completion_audit_fingerprint_sha256}`",
        "- Self-harness report bundle: "
        f"`{report.self_harness_report_bundle_root or '-'}`",
        "- Self-harness report bundle fingerprint SHA-256: "
        f"`{report.self_harness_report_bundle_fingerprint_sha256 or '-'}`",
        "- Self-harness report bundle validation schema: "
        f"`{report.self_harness_report_bundle_validation_schema_version or '-'}`",
        f"- Full completion audit ready: `{str(report.full_completion_audit_ready).lower()}`",
        f"- Scoped completion audit ready: `{str(report.scoped_completion_audit_ready).lower()}`",
        "- Scope excluded requirement IDs: "
        f"`{', '.join(report.excluded_requirement_ids) or '-'}`",
        f"- Full counts: `passed={report.full_passed_count}, missing={report.full_missing_count}, failed={report.full_failed_count}, requirements={report.full_requirement_count}`",
        f"- Scoped counts: `passed={report.scoped_passed_count}, missing={report.scoped_missing_count}, failed={report.scoped_failed_count}, requirements={report.scoped_requirement_count}`",
        "- Full live setup blocked: "
        f"`{report.full_live_setup_blocked_count}`",
        "- Scoped live setup blocked: "
        f"`{report.scoped_live_setup_blocked_count}`",
        f"- Scoped next actions: `{report.scoped_next_action_count}`",
        "- Scoped next actions fingerprint SHA-256: "
        f"`{report.scoped_next_actions_fingerprint_sha256}`",
        f"- Report status: `{'PASS' if report.ok else 'FAIL'}`",
        f"- Error codes: `{', '.join(report.to_dict()['error_codes']) or '-'}`",
        "",
    ]
    if report.errors:
        lines.append("## Report Errors")
        lines.append("")
        lines.extend(f"- {error}" for error in report.errors)
        lines.append("")
    lines.extend(
        [
            "## Full Readiness Blockers",
            "",
            *[f"- {blocker}" for blocker in report.readiness_blockers],
            "",
            "## Scoped Readiness Blockers",
            "",
            *[f"- {blocker}" for blocker in report.scoped_readiness_blockers],
            "",
            "## Scoped Live Setup Blockers",
            "",
            *[
                f"- {requirement_id}"
                for requirement_id in (
                    report.scoped_live_setup_blocked_requirement_ids or ["-"]
                )
            ],
            "",
            "## Scoped Next Actions",
            "",
            "| Requirement | Status | Live Setup | Workflow | Probe | Gates | Artifact | Error Codes | Preflight |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for action in report.scoped_next_actions:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(action.requirement_id),
                    _cell(action.status),
                    "blocked" if action.blocked_by_live_setup else "-",
                    _cell(action.workflow),
                    _cell(action.probe),
                    _cell(
                        ", ".join(
                            [
                                *action.dispatch_or_schedule_gate_tokens,
                                *action.live_env_flags,
                                *action.live_guard_tokens,
                            ]
                        )
                        or "-"
                    ),
                    _cell(action.artifact),
                    _cell(", ".join(action.error_codes) or "-"),
                    _cell(
                        (
                            f"{action.preflight_status}: "
                            f"{', '.join(action.preflight_required_next) or '-'}"
                        )
                        if action.preflight_status
                        else "-"
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Preflight Summaries",
            "",
            "| Requirement | Status | Required Next | Setup Contract | Source | Validation |",
            "|---|---|---|---|---|---|",
        ]
    )
    for summary in report.preflight_summaries:
        setup_contract = summary.setup_contract
        setup_cell = "-"
        if setup_contract:
            setup_cell = (
                f"{setup_contract.get('version', '-')}:"
                f"dispatch_ready={str(setup_contract.get('dispatch_ready')).lower()}:"
                "credential_slots="
                f"{len(setup_contract.get('credential_slots_required') or [])}:"
                "external_setup="
                f"{len(setup_contract.get('external_setup_required') or [])}"
            )
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(summary.requirement_id),
                    _cell(summary.status),
                    _cell(", ".join(summary.required_next) or "-"),
                    _cell(setup_cell),
                    _cell(summary.source_file),
                    _cell(
                        (
                            f"{summary.source_validation_schema_version}:"
                            f"{str(summary.source_validation_ok).lower()}:"
                            f"{summary.source_file_sha256}"
                        )
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "## Rows",
            "",
            "| Requirement | Artifact | Status | Scope | Error Codes |",
            "|---|---|---|---|---|",
        ]
    )
    for row in report.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.requirement_id),
                    _cell(row.artifact),
                    _cell(row.status),
                    "included" if row.included_in_scope else "excluded",
                    _cell(", ".join(row.error_codes) or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _requirements_by_id(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requirements = registry.get("requirements")
    if not isinstance(requirements, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in requirements:
        if not isinstance(item, dict):
            continue
        requirement_id = item.get("id")
        if isinstance(requirement_id, str):
            result[requirement_id] = item
    return result


def load_preflight_summaries(
    preflight_dir: Path | None,
) -> dict[str, ReadinessPreflightSummary]:
    if preflight_dir is None:
        return {}
    if preflight_dir.is_symlink():
        raise ValueError(f"preflight directory must not be a symlink: {preflight_dir}")
    if not preflight_dir.exists():
        raise ValueError(f"preflight directory does not exist: {preflight_dir}")
    if not preflight_dir.is_dir():
        raise ValueError(f"preflight path must be a directory: {preflight_dir}")
    summaries: dict[str, ReadinessPreflightSummary] = {}
    for path in sorted(preflight_dir.glob("*.json")):
        if path.is_symlink():
            raise ValueError(f"preflight file must not be a symlink: {path}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError(f"preflight JSON must be an object: {path}")
        schema_version = payload.get("schema_version")
        if not isinstance(schema_version, str):
            continue
        requirement_id = PREFLIGHT_SCHEMA_REQUIREMENT_IDS.get(schema_version)
        if not requirement_id:
            continue
        validation = _validate_preflight_source(path, requirement_id)
        summary = _preflight_summary_from_payload(
            payload=payload,
            requirement_id=requirement_id,
            source_file=path.name,
            source_file_sha256=_sha256_file(path),
            validation=validation,
        )
        _merge_preflight_summary(summaries, summary)
    return summaries


def load_embedded_preflight_summaries(
    bundle_root: Path,
    registry: dict[str, Any],
) -> dict[str, ReadinessPreflightSummary]:
    """Load valid preflight diagnostics embedded in failed registered artifacts."""
    summaries: dict[str, ReadinessPreflightSummary] = {}
    requirements = registry.get("requirements")
    if not isinstance(requirements, list):
        return summaries
    for item in requirements:
        if not isinstance(item, dict):
            continue
        requirement_id = item.get("id")
        artifact = item.get("artifact")
        if not isinstance(requirement_id, str) or not isinstance(artifact, str):
            continue
        for artifact_path in _matching_registered_artifact_paths(
            bundle_root=bundle_root,
            artifact=artifact,
        ):
            payload = _load_json_object_or_none(artifact_path)
            if payload is None:
                continue
            for candidate_key in ("preflight", "preflight_summary"):
                candidate = payload.get(candidate_key)
                if not isinstance(candidate, dict):
                    continue
                schema_version = candidate.get("schema_version")
                if not isinstance(schema_version, str):
                    continue
                if PREFLIGHT_SCHEMA_REQUIREMENT_IDS.get(schema_version) != requirement_id:
                    continue
                validation = _validate_embedded_preflight_payload(
                    candidate,
                    requirement_id=requirement_id,
                )
                if not validation.ok:
                    continue
                summary = _preflight_summary_from_payload(
                    payload=candidate,
                    requirement_id=requirement_id,
                    source_file=f"{artifact_path.name}#{candidate_key}",
                    source_file_sha256=_sha256_file(artifact_path),
                    validation=validation,
                )
                _merge_preflight_summary(summaries, summary)
    return summaries


def _matching_registered_artifact_paths(
    *,
    bundle_root: Path,
    artifact: str,
) -> list[Path]:
    matches = sorted(bundle_root.rglob(artifact))
    paths: list[Path] = []
    for path in matches:
        if bundle_validator.validate_artifact_path(
            bundle_root=bundle_root,
            artifact_path=path,
        ):
            continue
        paths.append(path)
    return paths


def _load_json_object_or_none(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _validate_embedded_preflight_payload(
    payload: dict[str, Any],
    *,
    requirement_id: str,
) -> preflight_validator.PreflightValidationResult:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "embedded-preflight.json"
        safe_write_report_text(path, json.dumps(payload, sort_keys=True))
        return preflight_validator.validate_preflight(
            path,
            requirement_id=requirement_id,
        )


def _preflight_summary_from_payload(
    *,
    payload: dict[str, Any],
    requirement_id: str,
    source_file: str,
    source_file_sha256: str,
    validation: preflight_validator.PreflightValidationResult,
) -> ReadinessPreflightSummary:
    required_next = payload.get("required_next")
    safe_required_next = (
        [
            _safe_preflight_token(item)
            for item in required_next
            if isinstance(item, str)
        ]
        if isinstance(required_next, list)
        else []
    )
    status = _safe_preflight_token(payload.get("status"))
    return ReadinessPreflightSummary(
        requirement_id=requirement_id,
        schema_version=str(payload.get("schema_version") or ""),
        status=status,
        generated_at=str(payload.get("generated_at") or "")[:80],
        required_next=safe_required_next,
        source_file=source_file,
        source_file_sha256=source_file_sha256,
        source_validation_schema_version=validation.validation_schema_version,
        source_validation_ok=validation.ok,
        source_validation_error_codes=validation.to_dict()["error_codes"],
        raw_payload_included=False,
        setup_contract=_safe_setup_contract(
            payload.get("setup_contract"),
            requirement_id=requirement_id,
            required_next=safe_required_next,
            status=status,
        ),
    )


def _merge_preflight_summary(
    summaries: dict[str, ReadinessPreflightSummary],
    summary: ReadinessPreflightSummary,
) -> None:
    current = summaries.get(summary.requirement_id)
    if current is None or (
        summary.generated_at,
        summary.source_file,
    ) > (
        current.generated_at,
        current.source_file,
    ):
        summaries[summary.requirement_id] = summary


def _validate_preflight_source(
    path: Path,
    requirement_id: str,
) -> preflight_validator.PreflightValidationResult:
    result = preflight_validator.validate_preflight(
        path,
        requirement_id=requirement_id,
    )
    if not result.ok:
        raise ValueError(
            "preflight JSON failed validation: "
            f"{path}: {'; '.join(result.errors)}"
        )
    return result


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _scoped_next_actions(
    *,
    rows: list[bundle_validator.BundleRow],
    requirements_by_id: dict[str, dict[str, Any]],
    preflight_summaries: dict[str, ReadinessPreflightSummary],
) -> list[ReadinessNextAction]:
    actions: list[ReadinessNextAction] = []
    for row in rows:
        if row.status == "passed":
            continue
        requirement = requirements_by_id.get(row.requirement_id, {})
        preflight = preflight_summaries.get(row.requirement_id)
        actions.append(
            ReadinessNextAction(
                requirement_id=row.requirement_id,
                title=_string_field(requirement, "title"),
                layer=_string_field(requirement, "layer"),
                artifact=row.artifact,
                schema_version=_string_field(requirement, "schema_version"),
                status=row.status,
                workflow=_string_field(requirement, "workflow"),
                probe=_string_field(requirement, "probe"),
                live_env_flags=_string_list(requirement.get("live_env_flags")),
                live_guard_tokens=_string_list(requirement.get("live_guard_tokens")),
                dispatch_or_schedule_gate_tokens=_string_list(
                    requirement.get("dispatch_or_schedule_gate_tokens")
                ),
                artifact_tokens=_string_list(requirement.get("artifact_tokens")),
                diagnostic_uploads=_diagnostic_uploads(
                    requirement.get("diagnostic_uploads")
                ),
                error_codes=bundle_validator._row_error_codes(row),
                blocked_by_live_setup=_preflight_blocks_live_setup(preflight),
                preflight_status=preflight.status if preflight else "",
                preflight_schema_version=preflight.schema_version if preflight else "",
                preflight_generated_at=preflight.generated_at if preflight else "",
                preflight_required_next=preflight.required_next if preflight else [],
                preflight_source_file=preflight.source_file if preflight else "",
            )
        )
    return actions


def _live_setup_blocked_requirement_ids(
    *,
    rows: list[bundle_validator.BundleRow],
    preflight_summaries: dict[str, ReadinessPreflightSummary],
) -> list[str]:
    blocked_ids: list[str] = []
    for row in rows:
        if row.status == "passed":
            continue
        preflight = preflight_summaries.get(row.requirement_id)
        if _preflight_blocks_live_setup(preflight):
            blocked_ids.append(row.requirement_id)
    return blocked_ids


def _preflight_blocks_live_setup(
    preflight: ReadinessPreflightSummary | None,
) -> bool:
    return bool(
        preflight is not None
        and (
            preflight.status != "pass"
            or bool(preflight.required_next)
            or not preflight.source_validation_ok
            or preflight.raw_payload_included
        )
    )


def _next_actions_fingerprint(
    actions: list[ReadinessNextAction],
    *,
    schema_version: str = READINESS_REPORT_SCHEMA_VERSION,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "actions": [asdict(action) for action in actions],
    }
    encoded = json.dumps(
        manifest,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _string_field(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _diagnostic_uploads(value: Any) -> list[ReadinessDiagnosticUpload]:
    if not isinstance(value, list):
        return []
    uploads: list[ReadinessDiagnosticUpload] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        artifact = _string_field(item, "artifact")
        path = _string_field(item, "path")
        if_no_files_found = _string_field(item, "if_no_files_found")
        artifact_tokens = _string_list(item.get("artifact_tokens"))
        retention_days = item.get("retention_days")
        if (
            artifact
            and path
            and if_no_files_found
            and artifact_tokens
            and isinstance(retention_days, int)
            and not isinstance(retention_days, bool)
        ):
            uploads.append(
                ReadinessDiagnosticUpload(
                    artifact=artifact,
                    path=path,
                    artifact_tokens=artifact_tokens,
                    if_no_files_found=if_no_files_found,
                    retention_days=retention_days,
                )
            )
    return uploads


def _readiness_blockers(
    *,
    rows: list[bundle_validator.BundleRow],
    self_harness_linked: bool,
) -> list[str]:
    blockers: list[str] = []
    if not self_harness_linked:
        blockers.append("self_harness_report_bundle_link_missing")
    for row in rows:
        if row.status == "passed":
            continue
        blockers.append(f"{row.status}:{row.requirement_id}")
    return blockers or ["-"]


def _requirement_ids_with_status(
    rows: list[bundle_validator.BundleRow],
    status: str,
) -> list[str]:
    return [row.requirement_id for row in rows if row.status == status]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


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
    return "completion_audit_readiness_report_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report completion-audit readiness for a runtime evidence bundle.",
    )
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        default=None,
        help="Optional self-harness report bundle link used for readiness.",
    )
    parser.add_argument(
        "--exclude-requirement-id",
        action="append",
        default=[],
        help="Exclude one requirement from the scoped readiness view.",
    )
    parser.add_argument(
        "--require-scoped-ready",
        action="store_true",
        help="Return non-zero unless the scoped readiness view is ready.",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--as-of", default=None)
    parser.add_argument(
        "--preflight-dir",
        type=Path,
        default=None,
        help="Optional directory containing privacy-safe live-evidence preflight JSON files.",
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle_validator.validate_registry_input_path(
            bundle_root=args.bundle_root,
            registry_path=args.registry,
        )
        bundle_validator.validate_report_output_path(
            bundle_root=args.bundle_root,
            out_path=args.out,
        )
        registry = load_registry(args.registry)
        bundle_validator.require_valid_registry_contract(
            registry,
            registry_path=args.registry,
        )
        report_bundle_link = bundle_validator.require_registry_matches_report_bundle(
            registry,
            report_bundle_root=args.self_harness_report_bundle,
        )
        as_of = bundle_validator._parse_timestamp(args.as_of) if args.as_of else None
        preflight_summaries = load_embedded_preflight_summaries(
            args.bundle_root,
            registry,
        )
        if args.preflight_dir is not None:
            for summary in load_preflight_summaries(args.preflight_dir).values():
                _merge_preflight_summary(preflight_summaries, summary)
        report = build_readiness_report(
            registry=registry,
            bundle_root=args.bundle_root,
            excluded_requirement_ids=args.exclude_requirement_id,
            as_of=as_of,
            report_bundle_link=report_bundle_link,
            preflight_summaries=preflight_summaries,
        )
    except Exception as exc:  # noqa: BLE001
        error_payload = _json_error_payload(str(exc))
        if args.format == "json":
            print(json.dumps(error_payload, indent=2, sort_keys=True))
        else:
            print(f"Wiii Completion Audit Readiness: FAIL\n- {exc}", file=sys.stderr)
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
    if not report.ok or (args.require_scoped_ready and not report.scoped_completion_audit_ready):
        return 1
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": READINESS_REPORT_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


if __name__ == "__main__":
    raise SystemExit(main())
