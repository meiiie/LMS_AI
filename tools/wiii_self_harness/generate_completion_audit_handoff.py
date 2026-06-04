#!/usr/bin/env python3
"""Generate the strict Wiii completion-audit handoff report bundle."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
)
import validate_runtime_evidence_bundle as bundle_validator  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_control_chain as control_chain_validator  # noqa: E402
import report_completion_audit_readiness as readiness_reporter  # noqa: E402
import validate_completion_audit_setup_gaps as setup_gap_validator  # noqa: E402


COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION = "wiii.completion_audit_handoff.v1"
HANDOFF_JSON_REPORT = "completion-audit-handoff.json"
HANDOFF_MARKDOWN_REPORT = "completion-audit-handoff.md"
RUNTIME_BUNDLE_JSON_REPORT = "runtime-evidence-bundle-report.json"
RUNTIME_BUNDLE_MARKDOWN_REPORT = "runtime-evidence-bundle-report.md"
EXPECTED_GENERATED_REPORTS = (
    HANDOFF_JSON_REPORT,
    HANDOFF_MARKDOWN_REPORT,
    RUNTIME_BUNDLE_JSON_REPORT,
    RUNTIME_BUNDLE_MARKDOWN_REPORT,
)
OUTPUT_DIR_NOT_EMPTY_ERROR = (
    "completion audit output directory must be empty before generation"
)
OUTPUT_DIR_NOT_DIRECTORY_ERROR = (
    "completion audit output path must be a directory"
)
OUTPUT_DIR_SYMLINK_ERROR = "completion audit output directory must not be a symlink"
OUTPUT_DIR_PARENT_SYMLINK_ERROR = (
    "completion audit output directory parent must not be a symlink"
)
OUTPUT_DIR_INSIDE_ARTIFACT_BUNDLE_ERROR = (
    "completion audit output directory must be outside artifact bundle root"
)
OUTPUT_DIR_INSIDE_SELF_HARNESS_BUNDLE_ERROR = (
    "completion audit output directory must be outside self-harness report bundle root"
)
GENERATED_HANDOFF_VALIDATION_ERROR = (
    "generated completion audit handoff failed validation"
)


@dataclass(frozen=True)
class CompletionAuditHandoffResult:
    handoff_root: Path
    artifact_bundle_root: Path
    self_harness_report_bundle_root: Path
    reports: tuple[str, ...]
    runtime_evidence_bundle_report: bundle_validator.BundleReport
    readiness_summary: dict[str, Any] | None = None
    control_chain_summary: dict[str, Any] | None = None
    setup_gap_summary: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.release_handoff_ready

    @property
    def release_handoff_ready(self) -> bool:
        ready = self.runtime_evidence_bundle_report.completion_audit_ready
        if self.control_chain_summary is not None:
            ready = (
                ready
                and bool(self.control_chain_summary.get("ok"))
                and bool(self.control_chain_summary.get("control_chain_ready"))
                and bool(self.control_chain_summary.get("dispatch_ready"))
            )
        if self.setup_gap_summary is not None:
            ready = (
                ready
                and bool(self.setup_gap_summary.get("ok"))
                and bool(self.setup_gap_summary.get("setup_diagnostics_consistent"))
                and self.setup_gap_summary.get("pending_setup_check_count") == 0
                and self.setup_gap_summary.get(
                    "diagnostic_present_setup_mismatch_count"
                )
                == 0
            )
        return ready

    def to_dict(self) -> dict[str, Any]:
        runtime_report = self.runtime_evidence_bundle_report
        runtime_blockers = _runtime_blockers(runtime_report)
        release_blockers = _release_blockers(
            completion_audit_ready=runtime_report.completion_audit_ready,
            runtime_error_codes=runtime_report.error_codes,
            runtime_blockers=runtime_blockers,
            readiness_summary=self.readiness_summary,
            control_chain_summary=self.control_chain_summary,
            setup_gap_summary=self.setup_gap_summary,
        )
        return {
            "schema_version": COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION,
            "ok": self.ok,
            "completion_audit_ready": (
                runtime_report.completion_audit_ready
            ),
            "release_handoff_ready": self.release_handoff_ready,
            "release_blocker_count": len(release_blockers),
            "release_blockers": release_blockers,
            "completion_audit_fingerprint_sha256": (
                runtime_report.completion_audit_fingerprint_sha256
            ),
            "runtime_evidence_bundle_fingerprint_sha256": (
                runtime_report.bundle_fingerprint_sha256
            ),
            "self_harness_report_bundle_fingerprint_sha256": (
                runtime_report.self_harness_report_bundle_fingerprint_sha256
            ),
            "handoff_root": str(self.handoff_root),
            "artifact_bundle_root": str(self.artifact_bundle_root),
            "self_harness_report_bundle_root": str(
                self.self_harness_report_bundle_root
            ),
            "reports": list(self.reports),
            "runtime_evidence_bundle_report": runtime_report.to_dict(),
            "runtime_blockers": runtime_blockers,
            "readiness_summary": self.readiness_summary,
            "control_chain_summary": self.control_chain_summary,
            "setup_gap_summary": self.setup_gap_summary,
        }


def generate_completion_audit_handoff(
    *,
    artifact_bundle_root: Path,
    self_harness_report_bundle_root: Path,
    out_dir: Path,
    registry_path: Path = DEFAULT_REGISTRY,
    as_of: str | None = None,
    readiness_report_path: Path | None = None,
    control_chain_report_path: Path | None = None,
    setup_gap_report_path: Path | None = None,
    setup_gap_markdown_report_path: Path | None = None,
) -> CompletionAuditHandoffResult:
    validate_output_directory_is_clean(
        out_dir,
        artifact_bundle_root=artifact_bundle_root,
        self_harness_report_bundle_root=self_harness_report_bundle_root,
    )
    bundle_validator.validate_registry_input_path(
        bundle_root=artifact_bundle_root,
        registry_path=registry_path,
    )

    registry = load_registry(registry_path)
    bundle_validator.require_valid_registry_contract(
        registry,
        registry_path=registry_path,
    )
    report_bundle_link = bundle_validator.require_registry_matches_report_bundle(
        registry,
        report_bundle_root=self_harness_report_bundle_root,
    )
    if report_bundle_link is None:
        raise ValueError(bundle_validator.COMPLETION_AUDIT_LINK_REQUIRED_ERROR)

    parsed_as_of = bundle_validator._parse_timestamp(as_of) if as_of else None
    runtime_report = bundle_validator.validate_bundle(
        registry=registry,
        bundle_root=artifact_bundle_root,
        as_of=parsed_as_of,
        report_bundle_link=report_bundle_link,
    )
    readiness_summary = _load_readiness_summary(readiness_report_path)
    control_chain_summary = _load_control_chain_summary(control_chain_report_path)
    setup_gap_summary = _load_setup_gap_summary(
        setup_gap_report_path,
        markdown_report_path=setup_gap_markdown_report_path,
    )
    _validate_optional_summary_sources(
        control_chain_summary=control_chain_summary,
        setup_gap_summary=setup_gap_summary,
    )

    result = CompletionAuditHandoffResult(
        handoff_root=out_dir,
        artifact_bundle_root=artifact_bundle_root,
        self_harness_report_bundle_root=self_harness_report_bundle_root,
        reports=EXPECTED_GENERATED_REPORTS,
        runtime_evidence_bundle_report=runtime_report,
        readiness_summary=readiness_summary,
        control_chain_summary=control_chain_summary,
        setup_gap_summary=setup_gap_summary,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / RUNTIME_BUNDLE_JSON_REPORT, runtime_report.to_dict())
    _write_text(
        out_dir / RUNTIME_BUNDLE_MARKDOWN_REPORT,
        bundle_validator.format_markdown(runtime_report),
    )
    _write_json(out_dir / HANDOFF_JSON_REPORT, result.to_dict())
    _write_text(out_dir / HANDOFF_MARKDOWN_REPORT, format_markdown(result))
    _validate_generated_handoff(out_dir)
    return result


def validate_output_directory_is_clean(
    out_dir: Path,
    *,
    artifact_bundle_root: Path,
    self_harness_report_bundle_root: Path,
) -> None:
    if _path_is_inside_directory(path=out_dir, directory=artifact_bundle_root):
        raise ValueError(OUTPUT_DIR_INSIDE_ARTIFACT_BUNDLE_ERROR)
    if _path_is_inside_directory(path=out_dir, directory=self_harness_report_bundle_root):
        raise ValueError(OUTPUT_DIR_INSIDE_SELF_HARNESS_BUNDLE_ERROR)
    if out_dir.is_symlink():
        raise ValueError(OUTPUT_DIR_SYMLINK_ERROR)
    for parent in out_dir.parents:
        if parent.is_symlink():
            raise ValueError(f"{OUTPUT_DIR_PARENT_SYMLINK_ERROR}: {parent}")
    if not out_dir.exists():
        return
    if not out_dir.is_dir():
        raise ValueError(OUTPUT_DIR_NOT_DIRECTORY_ERROR)
    existing_entries = sorted(path.name for path in out_dir.iterdir())
    if existing_entries:
        preview = ", ".join(existing_entries[:5])
        if len(existing_entries) > 5:
            preview += ", ..."
        raise ValueError(f"{OUTPUT_DIR_NOT_EMPTY_ERROR}: {preview}")


def format_summary(result: CompletionAuditHandoffResult) -> str:
    runtime_report = result.runtime_evidence_bundle_report
    lines = [
        "Wiii Completion Audit Handoff: " + ("PASS" if result.ok else "FAIL"),
        f"schema_version: {COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION}",
        f"handoff_root: {result.handoff_root}",
        f"artifact_bundle_root: {result.artifact_bundle_root}",
        f"self_harness_report_bundle_root: {result.self_harness_report_bundle_root}",
        f"completion_audit_ready: {str(runtime_report.completion_audit_ready).lower()}",
        f"release_handoff_ready: {str(result.release_handoff_ready).lower()}",
        "completion_audit_fingerprint_sha256: "
        f"{runtime_report.completion_audit_fingerprint_sha256}",
        "runtime_evidence_bundle_fingerprint_sha256: "
        f"{runtime_report.bundle_fingerprint_sha256}",
        "self_harness_report_bundle_fingerprint_sha256: "
        f"{runtime_report.self_harness_report_bundle_fingerprint_sha256 or '-'}",
        "reports: " + ", ".join(result.reports),
    ]
    return "\n".join(lines)


def format_markdown(result: CompletionAuditHandoffResult) -> str:
    runtime_report = result.runtime_evidence_bundle_report
    status = "PASS" if result.ok else "FAIL"
    runtime_blockers = _runtime_blockers(runtime_report)
    release_blockers = _release_blockers(
        completion_audit_ready=runtime_report.completion_audit_ready,
        runtime_error_codes=runtime_report.error_codes,
        runtime_blockers=runtime_blockers,
        readiness_summary=result.readiness_summary,
        control_chain_summary=result.control_chain_summary,
        setup_gap_summary=result.setup_gap_summary,
    )
    lines = [
        "# Wiii Completion Audit Handoff",
        "",
        f"- Schema version: `{COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION}`",
        f"- Status: `{status}`",
        "- Completion audit ready: "
        f"`{str(runtime_report.completion_audit_ready).lower()}`",
        f"- Release handoff ready: `{str(result.release_handoff_ready).lower()}`",
        f"- Release blocker count: `{len(release_blockers)}`",
        "- Release blockers: `"
        + (_format_release_blockers(release_blockers) or "-")
        + "`",
        "- Completion audit fingerprint SHA-256: "
        f"`{runtime_report.completion_audit_fingerprint_sha256}`",
        "- Runtime evidence bundle fingerprint SHA-256: "
        f"`{runtime_report.bundle_fingerprint_sha256}`",
        "- Self-harness report bundle fingerprint SHA-256: "
        f"`{runtime_report.self_harness_report_bundle_fingerprint_sha256 or '-'}`",
        f"- Handoff root: `{result.handoff_root}`",
        f"- Artifact bundle root: `{result.artifact_bundle_root}`",
        "- Self-harness report bundle root: "
        f"`{result.self_harness_report_bundle_root}`",
        f"- Runtime requirements: `{runtime_report.requirement_count}`",
        f"- Runtime passed: `{runtime_report.passed_count}`",
        f"- Runtime missing: `{runtime_report.missing_count}`",
        f"- Runtime failed: `{runtime_report.failed_count}`",
        f"- Runtime error codes: `{', '.join(runtime_report.error_codes) or '-'}`",
        *_readiness_markdown_lines(result.readiness_summary),
        f"- Runtime blocker count: `{len(runtime_blockers)}`",
        "- Runtime blockers: `"
        + (_format_runtime_blockers(runtime_blockers) or "-")
        + "`",
        *_control_chain_markdown_lines(result.control_chain_summary),
        *_setup_gap_markdown_lines(result.setup_gap_summary),
        "- Reports: `" + ", ".join(result.reports) + "`",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a strict Wiii completion-audit handoff report bundle from "
            "downloaded runtime evidence artifacts and a self-harness report bundle."
        ),
    )
    parser.add_argument("artifact_bundle_root", type=Path)
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        required=True,
        help="Downloaded self-harness report bundle to validate and link.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/wiii-completion-audit"),
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp used for freshness checks; defaults to now.",
    )
    parser.add_argument(
        "--readiness-report",
        type=Path,
        default=None,
        help=(
            "Optional report_completion_audit_readiness.py JSON report to bind "
            "runtime blockers to workflow/probe recovery actions."
        ),
    )
    parser.add_argument(
        "--control-chain-report",
        type=Path,
        default=None,
        help=(
            "Optional validate_completion_audit_control_chain.py JSON report to "
            "bind into the operator handoff summary."
        ),
    )
    parser.add_argument(
        "--setup-gap-report",
        type=Path,
        default=None,
        help=(
            "Optional report_completion_audit_setup_gaps.py JSON report to "
            "summarize pending external setup keys."
        ),
    )
    parser.add_argument(
        "--setup-gap-markdown-report",
        type=Path,
        default=None,
        help="Optional setup-gap Markdown report whose SHA-256 is bound into handoff.",
    )
    parser.add_argument(
        "--allow-not-ready",
        action="store_true",
        help=(
            "Return success for structurally valid handoff output even when "
            "release_handoff_ready is false."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = generate_completion_audit_handoff(
            artifact_bundle_root=args.artifact_bundle_root,
            self_harness_report_bundle_root=args.self_harness_report_bundle,
            out_dir=args.out_dir,
            registry_path=args.registry,
            as_of=args.as_of,
            readiness_report_path=args.readiness_report,
            control_chain_report_path=args.control_chain_report,
            setup_gap_report_path=args.setup_gap_report,
            setup_gap_markdown_report_path=args.setup_gap_markdown_report,
        )
    except Exception as exc:  # noqa: BLE001
        if args.json:
            print(json.dumps(_handoff_error_payload(str(exc)), indent=2, sort_keys=True))
        else:
            print(f"Wiii Completion Audit Handoff: FAIL\n- {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_summary(result))
    return 0 if result.ok or args.allow_not_ready else 1


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _write_text(path: Path, text: str) -> None:
    safe_write_report_text(path, text.rstrip("\n") + "\n")


def _runtime_blockers(
    runtime_report: bundle_validator.BundleReport,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    runtime_payload = runtime_report.to_dict()
    rows = runtime_payload.get("rows") if isinstance(runtime_payload, dict) else None
    if not isinstance(rows, list):
        return blockers
    for row in rows:
        if not isinstance(row, dict) or row.get("status") == "passed":
            continue
        blockers.append(
            {
                "requirement_id": row.get("requirement_id"),
                "artifact": row.get("artifact"),
                "status": row.get("status"),
                "error_codes": row.get("error_codes"),
            }
        )
    return blockers


def _format_runtime_blockers(blockers: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in blockers:
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


def _release_blockers(
    *,
    completion_audit_ready: bool,
    runtime_error_codes: list[str],
    runtime_blockers: list[dict[str, Any]],
    readiness_summary: dict[str, Any] | None,
    control_chain_summary: dict[str, Any] | None,
    setup_gap_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    recovery_actions = _readiness_recovery_actions_by_requirement(readiness_summary)
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
    if not completion_audit_ready and not runtime_blockers:
        blockers.append(
            {
                "kind": "runtime_readiness",
                "blocker_id": "completion_audit_ready",
                "status": "blocked",
                "error_codes": list(runtime_error_codes),
            }
        )
    if control_chain_summary is not None:
        control_error_codes = list(control_chain_summary["error_codes"])
        for field in ("ok", "control_chain_ready", "dispatch_ready"):
            if control_chain_summary[field] is not True:
                blockers.append(
                    {
                        "kind": "control_chain",
                        "blocker_id": "control_chain_ok"
                        if field == "ok"
                        else field,
                        "status": "blocked",
                        "error_codes": control_error_codes,
                    }
                )
    if setup_gap_summary is not None:
        setup_requirement_blockers = 0
        for item in setup_gap_summary["blocked_requirements"]:
            setup_requirement_blockers += 1
            blockers.append(
                {
                    "kind": "setup_gap",
                    "requirement_id": item["requirement_id"],
                    "pending_setup_check_count": item[
                        "pending_setup_check_count"
                    ],
                    "diagnostic_pending_setup_keys": list(
                        item["diagnostic_pending_setup_keys"]
                    ),
                    "non_diagnostic_pending_setup_keys": list(
                        item["non_diagnostic_pending_setup_keys"]
                    ),
                    "resolution_actions": [
                        dict(action) for action in item["resolution_actions"]
                    ],
                }
            )
        if setup_gap_summary["ok"] is not True:
            blockers.append(
                _setup_gap_summary_blocker(
                    setup_gap_summary,
                    blocker_id="setup_gap_ok",
                )
            )
        if (
            setup_gap_summary["diagnostic_present_setup_mismatch_count"] > 0
            or setup_gap_summary["setup_diagnostics_consistent"] is not True
        ):
            blockers.append(
                _setup_gap_summary_blocker(
                    setup_gap_summary,
                    blocker_id="setup_diagnostic_mismatch",
                )
            )
        if (
            setup_gap_summary["pending_setup_check_count"] > 0
            and setup_requirement_blockers == 0
        ):
            blockers.append(
                _setup_gap_summary_blocker(
                    setup_gap_summary,
                    blocker_id="pending_setup_checks",
                )
            )
    return blockers


def _setup_gap_summary_blocker(
    summary: dict[str, Any],
    *,
    blocker_id: str,
) -> dict[str, Any]:
    return {
        "kind": "setup_gap_summary",
        "blocker_id": blocker_id,
        "status": "blocked",
        "pending_setup_check_count": summary["pending_setup_check_count"],
        "diagnostic_present_setup_mismatch_count": summary[
            "diagnostic_present_setup_mismatch_count"
        ],
    }


def _format_release_blockers(blockers: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in blockers:
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


def _load_readiness_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    _require_regular_input_file(path, label="readiness report")
    payload = load_strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("readiness report JSON root must be an object")
    if payload.get("schema_version") != readiness_reporter.READINESS_REPORT_SCHEMA_VERSION:
        raise ValueError("readiness report schema_version mismatch")
    if not isinstance(payload.get("ok"), bool):
        raise ValueError("readiness report ok must be a boolean")
    if not isinstance(payload.get("scoped_completion_audit_ready"), bool):
        raise ValueError(
            "readiness report scoped_completion_audit_ready must be a boolean"
        )
    next_count = payload.get("scoped_next_action_count")
    if not isinstance(next_count, int) or isinstance(next_count, bool) or next_count < 0:
        raise ValueError(
            "readiness report scoped_next_action_count must be non-negative"
        )
    fingerprint = payload.get("scoped_next_actions_fingerprint_sha256")
    if not isinstance(fingerprint, str) or not _is_sha256(fingerprint):
        raise ValueError("readiness report scoped next-actions fingerprint invalid")
    actions = payload.get("scoped_next_actions")
    if not isinstance(actions, list):
        raise ValueError("readiness report scoped_next_actions must be a list")
    action_summaries = [_readiness_action_summary(action) for action in actions]
    if len(action_summaries) != next_count:
        raise ValueError("readiness report scoped_next_action_count must match actions")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "schema_version": payload["schema_version"],
        "ok": payload["ok"],
        "scoped_completion_audit_ready": payload["scoped_completion_audit_ready"],
        "scoped_next_action_count": next_count,
        "scoped_next_actions_fingerprint_sha256": fingerprint,
        "scoped_next_actions": action_summaries,
    }


def _readiness_action_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("readiness scoped_next_actions entries must be objects")
    result = {
        "requirement_id": _required_string(item, "requirement_id", "readiness action"),
        "artifact": _required_string(item, "artifact", "readiness action"),
        "status": _required_string(item, "status", "readiness action"),
        "workflow": _required_string(item, "workflow", "readiness action"),
        "probe": _required_string(item, "probe", "readiness action"),
        "blocked_by_live_setup": item.get("blocked_by_live_setup") is True,
        "live_env_flags": _required_string_list(item, "live_env_flags"),
        "live_guard_tokens": _required_string_list(item, "live_guard_tokens"),
        "dispatch_or_schedule_gate_tokens": _required_string_list(
            item,
            "dispatch_or_schedule_gate_tokens",
        ),
        "artifact_tokens": _required_string_list(item, "artifact_tokens"),
        "preflight_required_next": _required_string_list(
            item,
            "preflight_required_next",
        ),
        "error_codes": _required_string_list(item, "error_codes"),
    }
    return result


def _readiness_recovery_actions_by_requirement(
    summary: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if summary is None:
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


def _load_control_chain_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    _require_regular_input_file(path, label="control chain report")
    payload = load_strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("control chain report JSON root must be an object")
    if payload.get("validation_schema_version") != (
        control_chain_validator.CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION
    ):
        raise ValueError("control chain report validation_schema_version mismatch")
    for field in ("ok", "control_chain_ready", "dispatch_ready"):
        if not isinstance(payload.get(field), bool):
            raise ValueError(f"control chain report {field} must be a boolean")
    error_codes = payload.get("error_codes")
    if not _is_unique_string_list(error_codes):
        raise ValueError("control chain report error_codes must be a unique string list")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "validation_schema_version": payload["validation_schema_version"],
        "ok": payload["ok"],
        "control_chain_ready": payload["control_chain_ready"],
        "dispatch_ready": payload["dispatch_ready"],
        "setup_gap_report_path": _optional_string(
            payload.get("setup_gap_report_path")
        ),
        "setup_gap_markdown_report_path": _optional_string(
            payload.get("setup_gap_markdown_report_path")
        ),
        "dispatch_diagnostics_path": _optional_string(
            payload.get("dispatch_diagnostics_path")
        ),
        "error_codes": list(error_codes),
    }


def _load_setup_gap_summary(
    path: Path | None,
    *,
    markdown_report_path: Path | None,
) -> dict[str, Any] | None:
    if path is None:
        if markdown_report_path is not None:
            raise ValueError("setup gap markdown report requires setup gap JSON report")
        return None
    _require_regular_input_file(path, label="setup gap report")
    if markdown_report_path is not None:
        _require_regular_input_file(
            markdown_report_path,
            label="setup gap markdown report",
        )
    payload = load_strict_json_file(path)
    if not isinstance(payload, dict):
        raise ValueError("setup gap report JSON root must be an object")
    if payload.get("schema_version") != setup_gap_validator.SETUP_GAP_REPORT_SCHEMA_VERSION:
        raise ValueError("setup gap report schema_version mismatch")
    for field in ("ok", "setup_diagnostics_consistent"):
        if not isinstance(payload.get(field), bool):
            raise ValueError(f"setup gap report {field} must be a boolean")
    for field in (
        "requirement_count",
        "blocked_requirement_count",
        "pending_setup_check_count",
        "diagnostic_pending_setup_check_count",
        "non_diagnostic_pending_setup_check_count",
        "diagnostic_present_setup_mismatch_count",
    ):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"setup gap report {field} must be a non-negative integer")
    fingerprint = payload.get("setup_gap_report_fingerprint_sha256")
    if not isinstance(fingerprint, str) or not _is_sha256(fingerprint):
        raise ValueError("setup gap report fingerprint must be a SHA-256 hex string")
    privacy = payload.get("privacy")
    if not _is_privacy_summary(privacy):
        raise ValueError("setup gap report privacy summary must be closed booleans")
    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        raise ValueError("setup gap report requirements must be a list")
    blocked_requirements = [
        _setup_gap_requirement_summary(item)
        for item in requirements
        if isinstance(item, dict) and item.get("pending_setup_check_count", 0) > 0
    ]
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "markdown_path": str(markdown_report_path)
        if markdown_report_path is not None
        else None,
        "markdown_sha256": _sha256_file(markdown_report_path)
        if markdown_report_path is not None
        else None,
        "schema_version": payload["schema_version"],
        "ok": payload["ok"],
        "setup_gap_report_fingerprint_sha256": fingerprint,
        "setup_diagnostics_consistent": payload["setup_diagnostics_consistent"],
        "requirement_count": payload["requirement_count"],
        "blocked_requirement_count": payload["blocked_requirement_count"],
        "pending_setup_check_count": payload["pending_setup_check_count"],
        "diagnostic_pending_setup_check_count": payload[
            "diagnostic_pending_setup_check_count"
        ],
        "non_diagnostic_pending_setup_check_count": payload[
            "non_diagnostic_pending_setup_check_count"
        ],
        "diagnostic_present_setup_mismatch_count": payload[
            "diagnostic_present_setup_mismatch_count"
        ],
        "privacy": dict(privacy),
        "blocked_requirements": blocked_requirements,
    }


def _setup_gap_requirement_summary(item: dict[str, Any]) -> dict[str, Any]:
    requirement_id = item.get("requirement_id")
    pending_count = item.get("pending_setup_check_count")
    diagnostic_keys = item.get("diagnostic_pending_setup_keys")
    non_diagnostic_keys = item.get("non_diagnostic_pending_setup_keys")
    resolution_actions = item.get("pending_setup_checks")
    if not isinstance(requirement_id, str) or not requirement_id:
        raise ValueError("setup gap blocked requirement_id must be a non-empty string")
    if not isinstance(pending_count, int) or isinstance(pending_count, bool):
        raise ValueError("setup gap blocked pending count must be an integer")
    if pending_count <= 0:
        raise ValueError("setup gap blocked pending count must be positive")
    if not _is_unique_string_list(diagnostic_keys):
        raise ValueError(
            "setup gap blocked diagnostic_pending_setup_keys must be unique strings"
        )
    if not _is_unique_string_list(non_diagnostic_keys):
        raise ValueError(
            "setup gap blocked non_diagnostic_pending_setup_keys must be unique strings"
        )
    if not isinstance(resolution_actions, list):
        raise ValueError("setup gap blocked pending_setup_checks must be a list")
    actions = [
        _setup_gap_resolution_action(action)
        for action in resolution_actions
        if isinstance(action, dict)
    ]
    if len(actions) != pending_count:
        raise ValueError("setup gap blocked resolution_actions must match pending count")
    return {
        "requirement_id": requirement_id,
        "pending_setup_check_count": pending_count,
        "diagnostic_pending_setup_keys": list(diagnostic_keys),
        "non_diagnostic_pending_setup_keys": list(non_diagnostic_keys),
        "resolution_actions": actions,
    }


def _setup_gap_resolution_action(item: dict[str, Any]) -> dict[str, Any]:
    category = item.get("category")
    key = item.get("key")
    evidence_kind = item.get("evidence_kind")
    binding_count = item.get("binding_token_count")
    source_handle_options = item.get("source_handle_options")
    attestation_count = item.get("attestation_option_count")
    for field, value in (
        ("category", category),
        ("key", key),
        ("evidence_kind", evidence_kind),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"setup gap resolution action {field} must be non-empty")
    for field, value in (
        ("binding_token_count", binding_count),
        ("attestation_option_count", attestation_count),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"setup gap resolution action {field} must be non-negative"
            )
    if not _is_unique_string_list(source_handle_options):
        raise ValueError(
            "setup gap resolution action source_handle_options must be unique strings"
        )
    return {
        "category": category,
        "key": key,
        "evidence_kind": evidence_kind,
        "binding_token_count": binding_count,
        "source_handle_options": list(source_handle_options),
        "attestation_option_count": attestation_count,
    }


def _validate_optional_summary_sources(
    *,
    control_chain_summary: dict[str, Any] | None,
    setup_gap_summary: dict[str, Any] | None,
) -> None:
    if control_chain_summary is None or setup_gap_summary is None:
        return
    setup_gap_path = control_chain_summary.get("setup_gap_report_path")
    if isinstance(setup_gap_path, str) and setup_gap_path:
        if Path(setup_gap_path) != Path(str(setup_gap_summary["path"])):
            raise ValueError("control chain setup_gap_report_path must match setup gap report")
    setup_gap_markdown_path = control_chain_summary.get("setup_gap_markdown_report_path")
    if (
        isinstance(setup_gap_markdown_path, str)
        and setup_gap_markdown_path
        and setup_gap_summary.get("markdown_path") is not None
        and Path(setup_gap_markdown_path) != Path(str(setup_gap_summary["markdown_path"]))
    ):
        raise ValueError(
            "control chain setup_gap_markdown_report_path must match setup gap markdown report"
        )


def _control_chain_markdown_lines(summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return ["- Control chain report: `-`"]
    return [
        f"- Control chain report: `{summary['path']}`",
        f"- Control chain report SHA-256: `{summary['sha256']}`",
        f"- Control chain ok: `{str(summary['ok']).lower()}`",
        f"- Control chain ready: `{str(summary['control_chain_ready']).lower()}`",
        f"- Dispatch ready: `{str(summary['dispatch_ready']).lower()}`",
        "- Control chain error codes: `"
        + (", ".join(summary["error_codes"]) or "-")
        + "`",
    ]


def _setup_gap_markdown_lines(summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return ["- Setup gap report: `-`"]
    diagnostic_keys = _flatten_requirement_keys(
        summary["blocked_requirements"],
        "diagnostic_pending_setup_keys",
    )
    non_diagnostic_keys = _flatten_requirement_keys(
        summary["blocked_requirements"],
        "non_diagnostic_pending_setup_keys",
    )
    return [
        f"- Setup gap report: `{summary['path']}`",
        f"- Setup gap report SHA-256: `{summary['sha256']}`",
        "- Setup gap Markdown report: `" + (summary["markdown_path"] or "-") + "`",
        "- Setup gap Markdown SHA-256: `"
        + (summary["markdown_sha256"] or "-")
        + "`",
        "- Setup diagnostics consistent: "
        f"`{str(summary['setup_diagnostics_consistent']).lower()}`",
        f"- Blocked requirements: `{summary['blocked_requirement_count']}`",
        f"- Pending setup checks: `{summary['pending_setup_check_count']}`",
        "- Diagnostic pending setup checks: "
        f"`{summary['diagnostic_pending_setup_check_count']}`",
        "- Non-diagnostic pending setup checks: "
        f"`{summary['non_diagnostic_pending_setup_check_count']}`",
        "- Diagnostic present setup mismatches: "
        f"`{summary['diagnostic_present_setup_mismatch_count']}`",
        "- Setup gap diagnostic keys: `"
        + (", ".join(diagnostic_keys) or "-")
        + "`",
        "- Setup gap non-diagnostic keys: `"
        + (", ".join(non_diagnostic_keys) or "-")
        + "`",
    ]


def _readiness_markdown_lines(summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return ["- Readiness report: `-`"]
    return [
        f"- Readiness report: `{summary['path']}`",
        f"- Readiness report SHA-256: `{summary['sha256']}`",
        "- Readiness scoped completion audit ready: "
        f"`{str(summary['scoped_completion_audit_ready']).lower()}`",
        "- Readiness scoped next actions: "
        f"`{summary['scoped_next_action_count']}`",
        "- Readiness scoped next-actions SHA-256: "
        f"`{summary['scoped_next_actions_fingerprint_sha256']}`",
    ]


def _flatten_requirement_keys(
    requirements: list[dict[str, Any]],
    field: str,
) -> list[str]:
    keys: set[str] = set()
    for requirement in requirements:
        for key in requirement.get(field, []):
            keys.add(key)
    return sorted(keys)


def _require_regular_input_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    if not path.exists():
        raise ValueError(f"{label} does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"{label} must be a file: {path}")


def _sha256_file(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _is_unique_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
    )


def _required_string(item: dict[str, Any], field: str, label: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} {field} must be non-empty")
    return value


def _required_string_list(item: dict[str, Any], field: str) -> list[str]:
    value = item.get(field)
    if not _is_unique_string_list(value):
        raise ValueError(f"readiness action {field} must be unique strings")
    return list(value)


def _is_sha256(value: str) -> bool:
    import re

    return re.match(r"^[0-9a-f]{64}$", value) is not None


def _is_privacy_summary(value: Any) -> bool:
    expected_fields = {
        "secret_values_included",
        "credential_values_included",
        "raw_identifiers_included",
        "raw_payload_included",
    }
    return (
        isinstance(value, dict)
        and set(value) == expected_fields
        and all(isinstance(value[field], bool) for field in expected_fields)
    )


def _validate_generated_handoff(out_dir: Path) -> None:
    from validate_completion_audit_handoff import validate_handoff_bundle

    validation = validate_handoff_bundle(out_dir)
    if validation.ok:
        return
    error_codes = validation.to_dict().get("error_codes", [])
    rendered_codes = ", ".join(error_codes) if error_codes else "unknown_error"
    raise ValueError(f"{GENERATED_HANDOFF_VALIDATION_ERROR}: {rendered_codes}")


def _handoff_error_payload(error: str) -> dict[str, Any]:
    error_code = _handoff_error_code(error)
    return {
        "schema_version": COMPLETION_AUDIT_HANDOFF_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def _handoff_error_code(error: str) -> str:
    if error == OUTPUT_DIR_INSIDE_ARTIFACT_BUNDLE_ERROR:
        return "completion_audit_output_dir_inside_artifact_bundle"
    if error == OUTPUT_DIR_INSIDE_SELF_HARNESS_BUNDLE_ERROR:
        return "completion_audit_output_dir_inside_self_harness_bundle"
    if error == OUTPUT_DIR_SYMLINK_ERROR:
        return "completion_audit_output_dir_symlink"
    if error.startswith(OUTPUT_DIR_PARENT_SYMLINK_ERROR):
        return "completion_audit_output_dir_parent_symlink"
    if error == OUTPUT_DIR_NOT_DIRECTORY_ERROR:
        return "completion_audit_output_path_not_directory"
    if error.startswith(OUTPUT_DIR_NOT_EMPTY_ERROR):
        return "completion_audit_output_dir_not_empty"
    if error.startswith(GENERATED_HANDOFF_VALIDATION_ERROR):
        return "completion_audit_generated_handoff_invalid"
    mapped = bundle_validator._error_code(error)
    if mapped != "validation_error":
        return mapped
    return "completion_audit_handoff_generation_failed"


def _path_is_inside_directory(*, path: Path, directory: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(directory.resolve(strict=False))
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
