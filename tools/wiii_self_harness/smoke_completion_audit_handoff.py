#!/usr/bin/env python3
"""Smoke-test completion-audit handoff wiring with an empty evidence bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from generate_completion_audit_handoff import (  # noqa: E402
    EXPECTED_GENERATED_REPORTS,
    CompletionAuditHandoffResult,
    generate_completion_audit_handoff,
)
from validate_completion_audit_handoff import validate_handoff_bundle  # noqa: E402
from validate_runtime_evidence_registry import DEFAULT_REGISTRY  # noqa: E402


SMOKE_SCHEMA_VERSION = "wiii.completion_audit_handoff_smoke.v1"
SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR = (
    "completion audit smoke sidecar output path must be outside handoff, "
    "artifact, and self-harness bundles"
)
SMOKE_SIDECAR_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit smoke sidecar output path must not be a symlink"
)
SMOKE_SIDECAR_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit smoke sidecar output path parent must not be a symlink"
)
SMOKE_SIDECAR_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit smoke sidecar output path must not be a directory"
)
SMOKE_SIDECAR_OUTPUT_PATH_DUPLICATE_ERROR = (
    "completion audit smoke sidecar output paths must be distinct"
)


def run_completion_audit_handoff_smoke(
    *,
    self_harness_report_bundle_root: Path,
    artifact_bundle_root: Path,
    out_dir: Path,
    json_out: Path | None = None,
    release_gate_json_out: Path | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    as_of: str | None = None,
) -> dict[str, Any]:
    validate_sidecar_output_paths(
        handoff_bundle_root=out_dir,
        artifact_bundle_root=artifact_bundle_root,
        self_harness_report_bundle_root=self_harness_report_bundle_root,
        json_out=json_out,
        release_gate_json_out=release_gate_json_out,
    )
    artifact_bundle_root.mkdir(parents=True, exist_ok=True)
    result = generate_completion_audit_handoff(
        artifact_bundle_root=artifact_bundle_root,
        self_harness_report_bundle_root=self_harness_report_bundle_root,
        out_dir=out_dir,
        registry_path=registry_path,
        as_of=as_of,
    )
    validation = validate_handoff_bundle(out_dir)
    if not validation.ok:
        raise ValueError(
            "completion audit smoke generated an invalid handoff bundle: "
            + ", ".join(validation.to_dict()["error_codes"])
        )
    release_gate_validation = validate_handoff_bundle(
        out_dir,
        require_completion_audit_ready=True,
    )
    release_gate_validation_payload = release_gate_validation.to_dict()
    payload = _smoke_payload(
        result,
        handoff_validation=validation.to_dict(),
        release_gate_validation=release_gate_validation_payload,
    )
    _assert_expected_empty_evidence_smoke(payload)
    if json_out is not None:
        _write_json(json_out, payload)
    if release_gate_json_out is not None:
        _write_json(release_gate_json_out, release_gate_validation_payload)
    return payload


def validate_sidecar_output_paths(
    *,
    handoff_bundle_root: Path,
    artifact_bundle_root: Path,
    self_harness_report_bundle_root: Path,
    json_out: Path | None,
    release_gate_json_out: Path | None,
) -> None:
    paths = [path for path in (json_out, release_gate_json_out) if path is not None]
    _validate_distinct_sidecar_paths(paths)
    for path in paths:
        _validate_sidecar_output_path(
            path=path,
            bundle_roots=[
                handoff_bundle_root,
                artifact_bundle_root,
                self_harness_report_bundle_root,
            ],
        )


def _validate_distinct_sidecar_paths(paths: list[Path]) -> None:
    seen: set[Path] = set()
    for path in paths:
        for normalized in (path.absolute(), path.resolve(strict=False)):
            if normalized in seen:
                raise ValueError(SMOKE_SIDECAR_OUTPUT_PATH_DUPLICATE_ERROR)
        seen.add(path.absolute())
        seen.add(path.resolve(strict=False))


def _validate_sidecar_output_path(*, path: Path, bundle_roots: list[Path]) -> None:
    for bundle_root in bundle_roots:
        if _path_is_inside_directory(
            path=path,
            directory=bundle_root,
            resolve_symlinks=False,
        ) or _path_is_inside_directory(
            path=path,
            directory=bundle_root,
            resolve_symlinks=True,
        ):
            raise ValueError(SMOKE_SIDECAR_OUTPUT_PATH_INSIDE_BUNDLE_ERROR)
    if path.exists() and path.is_dir():
        raise ValueError(SMOKE_SIDECAR_OUTPUT_PATH_DIRECTORY_ERROR)
    if path.is_symlink():
        raise ValueError(SMOKE_SIDECAR_OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(path):
        raise ValueError(SMOKE_SIDECAR_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _smoke_payload(
    result: CompletionAuditHandoffResult,
    *,
    handoff_validation: dict[str, Any],
    release_gate_validation: dict[str, Any],
) -> dict[str, Any]:
    runtime_report = result.runtime_evidence_bundle_report.to_dict()
    return {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "ok": True,
        "handoff_ok": result.ok,
        "completion_audit_ready": runtime_report["completion_audit_ready"],
        "handoff_root": str(result.handoff_root),
        "artifact_bundle_root": str(result.artifact_bundle_root),
        "self_harness_report_bundle_root": str(
            result.self_harness_report_bundle_root
        ),
        "reports": list(result.reports),
        "handoff_validation": handoff_validation,
        "release_gate_validation": release_gate_validation,
        "runtime_evidence_bundle_report": runtime_report,
    }


def _assert_expected_empty_evidence_smoke(payload: dict[str, Any]) -> None:
    report = payload["runtime_evidence_bundle_report"]
    if payload["handoff_ok"] is not False:
        raise ValueError("completion audit smoke must fail handoff readiness")
    if payload["completion_audit_ready"] is not False:
        raise ValueError("completion audit smoke must not be ready")
    if report["ok"] is not False:
        raise ValueError("runtime evidence bundle smoke report must fail")
    if report["error_codes"] != ["missing_artifact"]:
        raise ValueError(
            f"completion audit smoke expected missing_artifact, got {report['error_codes']!r}"
        )
    if report["missing_count"] != report["requirement_count"]:
        raise ValueError("empty evidence smoke must mark every requirement missing")
    validation = payload["handoff_validation"]
    if validation["ok"] is not True:
        raise ValueError("completion audit smoke handoff validation must pass")
    if validation["require_completion_audit_ready"] is not False:
        raise ValueError(
            "completion audit smoke structural validation must not require readiness"
        )
    release_gate = payload["release_gate_validation"]
    if release_gate["require_completion_audit_ready"] is not True:
        raise ValueError(
            "completion audit release gate validation must require readiness"
        )
    if release_gate["ok"] is not False:
        raise ValueError("completion audit release gate must reject empty evidence")
    if "handoff_completion_audit_not_ready" not in release_gate["error_codes"]:
        raise ValueError(
            "completion audit release gate must report "
            "handoff_completion_audit_not_ready"
        )
    if (
        validation["bundle_fingerprint_sha256"]
        == release_gate["bundle_fingerprint_sha256"]
    ):
        raise ValueError(
            "completion audit release gate fingerprint must differ from structural validation"
        )
    handoff_root = Path(payload["handoff_root"])
    for report_name in EXPECTED_GENERATED_REPORTS:
        if not (handoff_root / report_name).is_file():
            raise ValueError(f"missing completion audit smoke report: {report_name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test the completion-audit handoff command using an empty "
            "runtime evidence directory and a strict self-harness report bundle."
        ),
    )
    parser.add_argument(
        "--self-harness-report-bundle",
        type=Path,
        required=True,
        help="Generated self-harness report bundle to validate and link.",
    )
    parser.add_argument(
        "--artifact-bundle-root",
        type=Path,
        default=Path("artifacts/runtime-evidence-empty"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("artifacts/wiii-completion-audit-smoke"),
    )
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--release-gate-json-out",
        type=Path,
        default=None,
        help=(
            "Optional path for the strict --require-completion-audit-ready "
            "validation result, expected to reject this empty-evidence smoke."
        ),
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO-8601 timestamp used for freshness checks; defaults to now.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_completion_audit_handoff_smoke(
            self_harness_report_bundle_root=args.self_harness_report_bundle,
            artifact_bundle_root=args.artifact_bundle_root,
            out_dir=args.out_dir,
            json_out=args.json_out,
            release_gate_json_out=args.release_gate_json_out,
            registry_path=args.registry,
            as_of=args.as_of,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Wiii Completion Audit Handoff Smoke: FAIL\n- {exc}", file=sys.stderr)
        return 1

    print(
        "Wiii Completion Audit Handoff Smoke: PASS\n"
        f"- missing_artifacts: {payload['runtime_evidence_bundle_report']['missing_count']}\n"
        f"- handoff_root: {payload['handoff_root']}"
    )
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    safe_write_report_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


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
    return any(parent.is_symlink() for parent in path.parents)


if __name__ == "__main__":
    raise SystemExit(main())
