#!/usr/bin/env python3
"""Generate the CI handoff bundle for Wiii Self-Harness reports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from report_runtime_evidence_coverage import (  # noqa: E402
    build_report as build_coverage_report,
    format_markdown as format_coverage_markdown,
)
from run_wiii_self_harness import (  # noqa: E402
    DEFAULT_MANIFEST,
    HARNESS_VALIDATION_SCHEMA_VERSION,
    REPO_ROOT,
    _error_code as self_harness_error_code,
    load_manifest,
    validate_manifest,
)
from validate_runtime_evidence_registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    REGISTRY_VALIDATION_SCHEMA_VERSION,
    normalize_registry_error_code,
    load_registry,
    validate_registry,
)
from validate_self_harness_report_bundle import (  # noqa: E402
    SELF_VALIDATION_REPORT_NAME,
    ReportBundleResult,
    format_summary as format_bundle_summary,
    validate_report_bundle,
)


SELF_HARNESS_REPORT = "self-harness-validation.json"
RUNTIME_REGISTRY_REPORT = "runtime-evidence-registry-validation.json"
RUNTIME_COVERAGE_JSON_REPORT = "runtime-evidence-coverage.json"
RUNTIME_COVERAGE_MARKDOWN_REPORT = "runtime-evidence-coverage.md"
EXPECTED_GENERATED_REPORTS = (
    SELF_HARNESS_REPORT,
    RUNTIME_REGISTRY_REPORT,
    RUNTIME_COVERAGE_JSON_REPORT,
    RUNTIME_COVERAGE_MARKDOWN_REPORT,
    SELF_VALIDATION_REPORT_NAME,
)
OUTPUT_DIR_NOT_EMPTY_ERROR = "report bundle output directory must be empty before generation"
OUTPUT_DIR_NOT_DIRECTORY_ERROR = "report bundle output path must be a directory"
OUTPUT_DIR_SYMLINK_ERROR = "report bundle output directory must not be a symlink"
OUTPUT_DIR_PARENT_SYMLINK_ERROR = (
    "report bundle output directory parent must not be a symlink"
)


@dataclass(frozen=True)
class ReportBundleGenerationResult:
    bundle_root: Path
    reports: tuple[str, ...]
    pre_self_validation: ReportBundleResult
    final_validation: ReportBundleResult

    @property
    def ok(self) -> bool:
        return self.final_validation.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_root": str(self.bundle_root),
            "reports": list(self.reports),
            "ok": self.ok,
            "pre_self_validation": self.pre_self_validation.to_dict(),
            "final_validation": self.final_validation.to_dict(),
        }


def generate_report_bundle(
    out_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    registry_path: Path = DEFAULT_REGISTRY,
    require_no_synthetic_gaps: bool = False,
    require_credentialed_external_contracts: bool = False,
) -> ReportBundleGenerationResult:
    validate_output_directory_is_clean(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    self_harness_payload = _build_self_harness_payload(
        repo_root=repo_root,
        manifest_path=manifest_path,
    )
    _write_json(out_dir / SELF_HARNESS_REPORT, self_harness_payload)

    registry_payload, registry_data = _build_registry_payload(
        repo_root=repo_root,
        registry_path=registry_path,
    )
    _write_json(out_dir / RUNTIME_REGISTRY_REPORT, registry_payload)

    coverage_json, coverage_markdown = _build_coverage_reports(
        registry_data,
        repo_root=repo_root,
        registry_path=registry_path,
        require_no_synthetic_gaps=require_no_synthetic_gaps,
        require_credentialed_external_contracts=(
            require_credentialed_external_contracts
        ),
    )
    _write_json(out_dir / RUNTIME_COVERAGE_JSON_REPORT, coverage_json)
    _write_text(out_dir / RUNTIME_COVERAGE_MARKDOWN_REPORT, coverage_markdown)

    pre_self_validation = validate_report_bundle(
        out_dir,
        require_no_synthetic_gaps=require_no_synthetic_gaps,
        require_credentialed_external_contracts=(
            require_credentialed_external_contracts
        ),
    )
    if not pre_self_validation.ok:
        return ReportBundleGenerationResult(
            bundle_root=out_dir,
            reports=EXPECTED_GENERATED_REPORTS[:-1],
            pre_self_validation=pre_self_validation,
            final_validation=pre_self_validation,
        )
    self_validation_path = _write_self_validation_report(
        out_dir=out_dir,
        payload=pre_self_validation.to_dict(),
    )
    if self_validation_path.name != SELF_VALIDATION_REPORT_NAME:
        raise RuntimeError("self-validation report was written to an unexpected name")
    final_validation = validate_report_bundle(
        out_dir,
        require_self_validation=True,
        require_no_synthetic_gaps=require_no_synthetic_gaps,
        require_credentialed_external_contracts=(
            require_credentialed_external_contracts
        ),
    )
    return ReportBundleGenerationResult(
        bundle_root=out_dir,
        reports=EXPECTED_GENERATED_REPORTS,
        pre_self_validation=pre_self_validation,
        final_validation=final_validation,
    )


def validate_output_directory_is_clean(out_dir: Path) -> None:
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


def _build_self_harness_payload(
    *,
    repo_root: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    try:
        manifest = load_manifest(manifest_path)
        return validate_manifest(
            manifest,
            repo_root=repo_root,
            manifest_path=manifest_path,
            enforce_default_scenarios=True,
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        return _self_harness_error_payload(str(exc))


def _build_registry_payload(
    *,
    repo_root: Path,
    registry_path: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        registry = load_registry(registry_path)
        return (
            validate_registry(
                registry,
                repo_root=repo_root,
                registry_path=registry_path,
            ).to_dict(),
            registry,
        )
    except Exception as exc:  # noqa: BLE001
        return _registry_error_payload(str(exc)), None


def _build_coverage_reports(
    registry_data: dict[str, Any] | None,
    *,
    repo_root: Path,
    registry_path: Path,
    require_no_synthetic_gaps: bool = False,
    require_credentialed_external_contracts: bool = False,
) -> tuple[dict[str, Any], str]:
    if registry_data is None:
        return (
            _coverage_error_payload("runtime evidence registry could not be loaded"),
            "# Wiii Runtime Evidence Coverage\n\n- Status: `FAIL`\n",
        )
    try:
        report = build_coverage_report(
            registry_data,
            repo_root=repo_root,
            registry_path=registry_path,
            require_no_synthetic_gaps=require_no_synthetic_gaps,
            require_credentialed_external_contracts=(
                require_credentialed_external_contracts
            ),
        )
        return report.to_dict(), format_coverage_markdown(report)
    except Exception as exc:  # noqa: BLE001
        return (
            _coverage_error_payload(str(exc)),
            f"# Wiii Runtime Evidence Coverage\n\n- Status: `FAIL`\n- Error: `{exc}`\n",
        )


def _write_self_validation_report(*, out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir_parent = out_dir.parent
    out_dir_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=out_dir_parent,
        prefix="self-harness-report-bundle-validation-",
        suffix=".json",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    final_path = out_dir / SELF_VALIDATION_REPORT_NAME
    temp_path.replace(final_path)
    return final_path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    _write_text(path, rendered)


def _write_text(path: Path, text: str) -> None:
    safe_write_report_text(path, text.rstrip("\n") + "\n")


def _self_harness_error_payload(error: str) -> dict[str, Any]:
    error_code = self_harness_error_code(error)
    return {
        "validation_schema_version": HARNESS_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def _registry_error_payload(error: str) -> dict[str, Any]:
    error_code = normalize_registry_error_code(error)
    return {
        "validation_schema_version": REGISTRY_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def _coverage_error_payload(error: str) -> dict[str, Any]:
    error_code = "coverage_generation_failed"
    return {
        "schema_version": "wiii.runtime_evidence_coverage_report.v1",
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def format_summary(result: ReportBundleGenerationResult) -> str:
    lines = [
        "Wiii Self-Harness Report Bundle Generation: "
        + ("PASS" if result.ok else "FAIL"),
        f"bundle_root: {result.bundle_root}",
        "reports: " + ", ".join(result.reports),
        "",
        format_bundle_summary(result.final_validation),
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and validate Wiii Self-Harness report bundle artifacts.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/wiii-self-harness"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    parser.add_argument(
        "--require-no-synthetic-gaps",
        action="store_true",
        help="Fail generation before self-validation when coverage has synthetic external gaps.",
    )
    parser.add_argument(
        "--require-credentialed-external-contracts",
        action="store_true",
        help=(
            "Fail generation before self-validation when credentialed external "
            "coverage rows lack required guard, gate, privacy, or identifier proof."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = generate_report_bundle(
            args.out_dir,
            repo_root=args.repo_root,
            manifest_path=args.manifest,
            registry_path=args.registry,
            require_no_synthetic_gaps=args.require_no_synthetic_gaps,
            require_credentialed_external_contracts=(
                args.require_credentialed_external_contracts
            ),
        )
    except Exception as exc:  # noqa: BLE001
        if args.json:
            print(json.dumps(_generation_error_payload(str(exc)), indent=2, sort_keys=True))
        else:
            print(f"Wiii Self-Harness Report Bundle Generation: FAIL\n- {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_summary(result))
    return 0 if result.ok else 1


def _generation_error_payload(error: str) -> dict[str, Any]:
    error_code = _generation_error_code(error)
    return {
        "ok": False,
        "errors": [error],
        "error_codes": [error_code],
        "error_code_counts": {error_code: 1},
    }


def _generation_error_code(error: str) -> str:
    if error == OUTPUT_DIR_SYMLINK_ERROR:
        return "report_bundle_output_dir_symlink"
    if error.startswith(OUTPUT_DIR_PARENT_SYMLINK_ERROR):
        return "report_bundle_output_dir_parent_symlink"
    if error == OUTPUT_DIR_NOT_DIRECTORY_ERROR:
        return "report_bundle_output_path_not_directory"
    if error.startswith(OUTPUT_DIR_NOT_EMPTY_ERROR):
        return "report_bundle_output_dir_not_empty"
    return "report_bundle_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
