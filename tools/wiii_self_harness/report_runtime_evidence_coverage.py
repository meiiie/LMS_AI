#!/usr/bin/env python3
"""Render operator-readable coverage for Wiii runtime evidence."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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
    REPO_ROOT,
    load_registry,
    normalize_registry_error_code,
    validate_registry,
)


COVERAGE_REPORT_SCHEMA_VERSION = "wiii.runtime_evidence_coverage_report.v1"
SYNTHETIC_EXTERNAL_GAP_FLAGS = {
    "external_lms_write_disabled",
    "synthetic_host_side_replay",
}
CREDENTIALED_EXTERNAL_FLAGS = {
    "credentialed_provider_call_required",
    "external_provider_execution",
    "requires_connected_account",
    "requires_live_channel_credentials",
}


@dataclass(frozen=True)
class CoverageRow:
    requirement_id: str
    title: str
    layer: str
    artifact: str
    artifact_tokens: list[str]
    diagnostic_upload_count: int
    diagnostic_upload_artifacts: list[str]
    diagnostic_upload_paths: list[str]
    schema_version: str
    workflow: str
    probe: str
    contract_tests: int
    payload_checks: int
    raw_content_absence_checks: int
    identifier_strategy_checks: int
    identifier_strategies: list[str]
    external_evidence_mode: str
    synthetic_gap_flags: list[str]
    credentialed_external_flags: list[str]
    freshness_hours: int | None
    forbidden_tokens: int
    forbidden_regexes: int
    live_env_flags: list[str]
    live_guard_tokens: list[str]
    dispatch_or_schedule_gates: list[str]
    coverage_target_met: bool


@dataclass(frozen=True)
class CoverageReport:
    schema_version: str
    registry_name: str
    registry_version: int | None
    registry_path: str
    registry_fingerprint_sha256: str
    ok: bool
    error_codes: list[str]
    error_code_counts: dict[str, int]
    validation_errors: list[str]
    validation_error_codes: list[str]
    coverage_errors: list[str]
    coverage_error_codes: list[str]
    requirement_count: int
    synthetic_external_gap_count: int
    credentialed_external_count: int
    local_or_backend_count: int
    layers: list[str]
    rows: list[CoverageRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_name": self.registry_name,
            "registry_version": self.registry_version,
            "registry_path": self.registry_path,
            "registry_fingerprint_sha256": self.registry_fingerprint_sha256,
            "ok": self.ok,
            "error_codes": self.error_codes,
            "error_code_counts": self.error_code_counts,
            "validation_errors": self.validation_errors,
            "validation_error_codes": self.validation_error_codes,
            "coverage_errors": self.coverage_errors,
            "coverage_error_codes": self.coverage_error_codes,
            "requirement_count": self.requirement_count,
            "synthetic_external_gap_count": self.synthetic_external_gap_count,
            "credentialed_external_count": self.credentialed_external_count,
            "local_or_backend_count": self.local_or_backend_count,
            "layers": self.layers,
            "rows": [asdict(row) for row in self.rows],
        }


def build_report(
    registry: dict[str, Any],
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    repo_root: Path = REPO_ROOT,
    require_no_synthetic_gaps: bool = False,
    require_credentialed_external_contracts: bool = False,
) -> CoverageReport:
    validation = validate_registry(registry, repo_root=repo_root, registry_path=registry_path)
    requirements = registry.get("requirements")
    if not isinstance(requirements, list):
        requirements = []

    rows: list[CoverageRow] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        payload_checks = _payload_checks(item)
        freshness_hours = _freshness_hours(item)
        rows.append(
            CoverageRow(
                requirement_id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                layer=str(item.get("layer") or ""),
                artifact=str(item.get("artifact") or ""),
                artifact_tokens=_string_list(item.get("artifact_tokens")),
                diagnostic_upload_count=len(_diagnostic_uploads(item)),
                diagnostic_upload_artifacts=_diagnostic_upload_values(item, "artifact"),
                diagnostic_upload_paths=_diagnostic_upload_values(item, "path"),
                schema_version=str(item.get("schema_version") or ""),
                workflow=str(item.get("workflow") or ""),
                probe=str(item.get("probe") or ""),
                contract_tests=len(item.get("contract_tests") or []),
                payload_checks=len(payload_checks),
                raw_content_absence_checks=_raw_content_absence_check_count(item),
                identifier_strategy_checks=_identifier_strategy_check_count(item),
                identifier_strategies=_identifier_strategies(item),
                external_evidence_mode=_external_evidence_mode(item),
                synthetic_gap_flags=_synthetic_gap_flags(item),
                credentialed_external_flags=_credentialed_external_flags(item),
                freshness_hours=freshness_hours,
                forbidden_tokens=len(item.get("forbidden_payload_tokens") or []),
                forbidden_regexes=len(item.get("forbidden_payload_regexes") or []),
                live_env_flags=_string_list(item.get("live_env_flags")),
                live_guard_tokens=_string_list(item.get("live_guard_tokens")),
                dispatch_or_schedule_gates=_string_list(
                    item.get("dispatch_or_schedule_gate_tokens")
                ),
                coverage_target_met=_coverage_target_met(
                    payload_checks=len(payload_checks),
                    freshness_hours=freshness_hours,
                ),
            )
        )

    external_mode_counts = _external_evidence_mode_counts(rows)
    coverage_errors = _coverage_gate_errors(rows)
    if require_no_synthetic_gaps:
        coverage_errors.extend(_synthetic_external_gap_errors(rows))
    if require_credentialed_external_contracts:
        coverage_errors.extend(_credentialed_external_contract_errors(rows))
    validation_error_codes = validation.to_dict()["error_codes"]
    coverage_error_codes = _coverage_error_codes(coverage_errors)
    error_code_counts = _error_code_counts(
        validation_errors=validation.errors,
        coverage_errors=coverage_errors,
    )
    return CoverageReport(
        schema_version=COVERAGE_REPORT_SCHEMA_VERSION,
        registry_name=validation.registry,
        registry_version=validation.registry_version,
        registry_path=str(registry_path),
        registry_fingerprint_sha256=validation.registry_fingerprint_sha256,
        ok=validation.ok and not coverage_errors,
        error_codes=_report_error_codes(validation_error_codes, coverage_error_codes),
        error_code_counts=error_code_counts,
        validation_errors=validation.errors,
        validation_error_codes=validation_error_codes,
        coverage_errors=coverage_errors,
        coverage_error_codes=coverage_error_codes,
        requirement_count=len(rows),
        synthetic_external_gap_count=external_mode_counts["synthetic_external_gap"],
        credentialed_external_count=external_mode_counts["credentialed_external"],
        local_or_backend_count=external_mode_counts["local_or_backend"],
        layers=sorted({row.layer for row in rows if row.layer}),
        rows=rows,
    )


def format_markdown(report: CoverageReport) -> str:
    lines = [
        "# Wiii Runtime Evidence Coverage",
        "",
        f"- Report schema: `{report.schema_version}`",
        f"- Registry name: `{report.registry_name}`",
        f"- Registry version: `{report.registry_version if report.registry_version is not None else '-'}`",
        f"- Registry: `{report.registry_path}`",
        f"- Registry fingerprint SHA-256: `{report.registry_fingerprint_sha256}`",
        "- Artifact validator: `tools/wiii_self_harness/validate_runtime_evidence_artifact.py`",
        f"- Status: `{'PASS' if report.ok else 'FAIL'}`",
        f"- Error codes: `{', '.join(report.error_codes) or '-'}`",
        f"- Error code counts: `{_format_error_code_counts(report.error_code_counts)}`",
        f"- Requirements: `{report.requirement_count}`",
        f"- Layers: `{', '.join(report.layers)}`",
        "- External evidence: "
        f"`credentialed_external={report.credentialed_external_count}, "
        f"synthetic_external_gap={report.synthetic_external_gap_count}, "
        f"local_or_backend={report.local_or_backend_count}`",
        "- Coverage gate: `payload_checks >= freshness_hours` for every registered artifact",
        "",
    ]
    if report.validation_errors:
        lines.append("## Validation Errors")
        lines.append("")
        lines.append(f"Error codes: `{', '.join(report.validation_error_codes) or '-'}`")
        lines.append("")
        lines.extend(f"- {error}" for error in report.validation_errors)
        lines.append("")
    if report.coverage_errors:
        lines.append("## Coverage Gate Errors")
        lines.append("")
        lines.append(f"Error codes: `{', '.join(report.coverage_error_codes) or '-'}`")
        lines.append("")
        lines.extend(f"- {error}" for error in report.coverage_errors)
        lines.append("")

    lines.extend(
        [
            "## Coverage",
            "",
            "| Requirement | Layer | Artifact | Uploads | Schema | Workflow | Probe | Tests | Payload/Freshness | Privacy/Provenance | External Mode | Guards | Gates |",
            "|---|---|---|---|---|---|---|---:|---:|---|---|---|---|",
        ]
    )
    for row in report.rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row.requirement_id),
                    _cell(row.layer),
                    _cell(row.artifact),
                    _cell(
                        f"run:{', '.join(row.artifact_tokens) or '-'}; "
                        f"diagnostic:{row.diagnostic_upload_count} "
                        f"{', '.join(row.diagnostic_upload_artifacts) or '-'}"
                    ),
                    _cell(row.schema_version),
                    _cell(row.workflow),
                    _cell(row.probe),
                    str(row.contract_tests),
                    f"{row.payload_checks} / {row.freshness_hours or '-'}h",
                    _cell(
                        f"raw:{row.raw_content_absence_checks}; "
                        f"id:{row.identifier_strategy_checks} "
                        f"({', '.join(row.identifier_strategies) or '-'})"
                    ),
                    _cell(
                        f"{row.external_evidence_mode}; "
                        f"credentialed:{', '.join(row.credentialed_external_flags) or '-'}; "
                        f"synthetic:{', '.join(row.synthetic_gap_flags) or '-'}"
                    ),
                    _cell(", ".join([*row.live_env_flags, *row.live_guard_tokens])),
                    _cell(", ".join(row.dispatch_or_schedule_gates)),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(
        "This report is generated from the registry; it is not a substitute for "
        "the live evidence artifacts uploaded by the individual workflows."
    )
    return "\n".join(lines)


def _cell(value: str) -> str:
    normalized = " ".join(value.replace("|", "\\|").split())
    return normalized or "-"


def _freshness_hours(item: dict[str, Any]) -> int | None:
    freshness = item.get("freshness")
    if not isinstance(freshness, dict):
        return None
    max_age_hours = freshness.get("max_age_hours")
    return max_age_hours if _is_positive_int(max_age_hours) else None


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _payload_checks(item: dict[str, Any]) -> list[dict[str, Any]]:
    checks = item.get("payload_checks")
    if not isinstance(checks, list):
        return []
    return [check for check in checks if isinstance(check, dict)]


def _raw_content_absence_check_count(item: dict[str, Any]) -> int:
    return sum(
        1
        for check in _payload_checks(item)
        if "raw_content_included" in str(check.get("path") or "")
        and check.get("equals") is False
    )


def _identifier_strategy_check_count(item: dict[str, Any]) -> int:
    return sum(
        1
        for check in _payload_checks(item)
        if "identifier_strategy" in str(check.get("path") or "")
    )


def _identifier_strategies(item: dict[str, Any]) -> list[str]:
    strategies = {
        str(check.get("equals"))
        for check in _payload_checks(item)
        if "identifier_strategy" in str(check.get("path") or "")
        and isinstance(check.get("equals"), str)
    }
    return sorted(strategies)


def _diagnostic_uploads(item: dict[str, Any]) -> list[dict[str, Any]]:
    uploads = item.get("diagnostic_uploads")
    if not isinstance(uploads, list):
        return []
    return [upload for upload in uploads if isinstance(upload, dict)]


def _diagnostic_upload_values(item: dict[str, Any], field: str) -> list[str]:
    values = {
        value.strip()
        for upload in _diagnostic_uploads(item)
        if isinstance(value := upload.get(field), str) and value.strip()
    }
    return sorted(values)


def _external_evidence_mode(item: dict[str, Any]) -> str:
    if _synthetic_gap_flags(item):
        return "synthetic_external_gap"
    if _credentialed_external_flags(item):
        return "credentialed_external"
    return "local_or_backend"


def _synthetic_gap_flags(item: dict[str, Any]) -> list[str]:
    return _evidence_contract_true_flags(item, SYNTHETIC_EXTERNAL_GAP_FLAGS)


def _credentialed_external_flags(item: dict[str, Any]) -> list[str]:
    return _evidence_contract_true_flags(item, CREDENTIALED_EXTERNAL_FLAGS)


def _external_evidence_mode_counts(rows: list[CoverageRow]) -> dict[str, int]:
    counts = {
        "synthetic_external_gap": 0,
        "credentialed_external": 0,
        "local_or_backend": 0,
    }
    for row in rows:
        if row.external_evidence_mode in counts:
            counts[row.external_evidence_mode] += 1
    return counts


def _evidence_contract_true_flags(
    item: dict[str, Any],
    allowed_flags: set[str],
) -> list[str]:
    flags: set[str] = set()
    for check in _payload_checks(item):
        path = str(check.get("path") or "")
        if not path.startswith("evidence_contract.") or check.get("equals") is not True:
            continue
        flag = path.removeprefix("evidence_contract.")
        if flag in allowed_flags:
            flags.add(flag)
    return sorted(flags)


def _coverage_target_met(*, payload_checks: int, freshness_hours: int | None) -> bool:
    if freshness_hours is None:
        return False
    return payload_checks >= freshness_hours


def _coverage_gate_errors(rows: list[CoverageRow]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        if row.coverage_target_met:
            continue
        freshness = "-" if row.freshness_hours is None else f"{row.freshness_hours}h"
        errors.append(
            f"{row.requirement_id}: payload_checks={row.payload_checks} "
            f"must be >= freshness_hours={freshness}"
        )
    return errors


def _synthetic_external_gap_errors(rows: list[CoverageRow]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        if row.external_evidence_mode != "synthetic_external_gap":
            continue
        flags = ", ".join(row.synthetic_gap_flags) or "-"
        errors.append(f"{row.requirement_id}: synthetic external gap remains ({flags})")
    return errors


def _credentialed_external_contract_errors(rows: list[CoverageRow]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        if row.external_evidence_mode != "credentialed_external":
            continue
        missing: list[str] = []
        if not row.credentialed_external_flags:
            missing.append("credentialed_external_flags")
        if row.synthetic_gap_flags:
            missing.append("synthetic_gap_flags_absent")
        if not row.live_env_flags:
            missing.append("live_env_flags")
        if not row.live_guard_tokens:
            missing.append("live_guard_tokens")
        if len(row.dispatch_or_schedule_gates) < 2:
            missing.append("manual_and_scheduled_gates")
        if row.raw_content_absence_checks < 1:
            missing.append("raw_content_absence_checks")
        if row.identifier_strategy_checks < 1:
            missing.append("identifier_strategy_checks")
        if missing:
            errors.append(
                f"{row.requirement_id}: credentialed external contract incomplete "
                f"({', '.join(missing)})"
            )
    return errors


def _coverage_error_codes(errors: list[str]) -> list[str]:
    return sorted({_coverage_error_code(error) for error in errors})


def _error_code_counts(
    *,
    validation_errors: list[str],
    coverage_errors: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for error in validation_errors:
        code = normalize_registry_error_code(error)
        counts[code] = counts.get(code, 0) + 1
    for error in coverage_errors:
        code = _coverage_error_code(error)
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _format_error_code_counts(error_code_counts: dict[str, int]) -> str:
    if not error_code_counts:
        return "-"
    return ", ".join(
        f"{error_code}={count}" for error_code, count in error_code_counts.items()
    )


def _report_error_codes(
    validation_error_codes: list[str],
    coverage_error_codes: list[str],
) -> list[str]:
    return sorted({*validation_error_codes, *coverage_error_codes})


def _coverage_error_code(error: str) -> str:
    if " must be >= freshness_hours=" in error:
        return "coverage_payload_checks_below_freshness"
    if "synthetic external gap remains" in error:
        return "coverage_synthetic_external_gap_present"
    if "credentialed external contract incomplete" in error:
        return "coverage_credentialed_external_contract_incomplete"
    return "coverage_error"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render Wiii runtime evidence coverage.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--require-no-synthetic-gaps",
        action="store_true",
        help="Fail when any runtime evidence row remains a synthetic external gap.",
    )
    parser.add_argument(
        "--require-credentialed-external-contracts",
        action="store_true",
        help=(
            "Fail when credentialed external rows lack env flags, guard tokens, "
            "dispatch gates, privacy checks, or identifier checks."
        ),
    )
    return parser


def validate_report_output_path(*, registry_path: Path, out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.resolve() == registry_path.resolve():
        raise ValueError("coverage report output path must not overwrite registry")
    if out_path.is_symlink():
        raise ValueError("coverage report output path must not be a symlink")
    if _path_has_symlink_parent(out_path):
        raise ValueError("coverage report output path parent must not be a symlink")
    if out_path.exists() and out_path.is_dir():
        raise ValueError("coverage report output path must not be a directory")


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def normalize_coverage_cli_error_code(error: str) -> str:
    if error == "coverage report output path must not overwrite registry":
        return "coverage_report_output_path_overwrites_registry"
    if error == "coverage report output path must not be a symlink":
        return "coverage_report_output_path_symlink"
    if error == "coverage report output path parent must not be a symlink":
        return "coverage_report_output_path_parent_symlink"
    if error == "coverage report output path must not be a directory":
        return "coverage_report_output_path_directory"
    return normalize_registry_error_code(error)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_report_output_path(registry_path=args.registry, out_path=args.out)
        registry = load_registry(args.registry)
        report = build_report(
            registry,
            registry_path=args.registry,
            repo_root=args.repo_root,
            require_no_synthetic_gaps=args.require_no_synthetic_gaps,
            require_credentialed_external_contracts=(
                args.require_credentialed_external_contracts
            ),
        )
    except Exception as exc:  # noqa: BLE001
        if args.format == "json":
            error_code = normalize_coverage_cli_error_code(str(exc))
            print(
                json.dumps(
                    {
                        "schema_version": COVERAGE_REPORT_SCHEMA_VERSION,
                        "ok": False,
                        "errors": [str(exc)],
                        "error_codes": [error_code],
                        "error_code_counts": {error_code: 1},
                    },
                    indent=2,
                    sort_keys=True,
                ),
                file=sys.stdout,
            )
        else:
            print(f"Wiii Runtime Evidence Coverage: FAIL\n- {exc}", file=sys.stderr)
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


if __name__ == "__main__":
    raise SystemExit(main())
