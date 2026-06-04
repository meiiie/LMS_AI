#!/usr/bin/env python3
"""Promote validated runtime evidence into a completion-audit dispatch dry-run."""

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

import apply_completion_audit_setup_attestation as attestation_applier  # noqa: E402
import generate_completion_audit_dispatch_gate as dispatch_generator  # noqa: E402
import generate_completion_audit_setup_attestation_from_handles as attestation_from_handles  # noqa: E402
import probe_completion_audit_setup_handle_evidence as handle_probe  # noqa: E402
import run_completion_audit_dispatch_gate as dispatch_runner  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402


PROMOTION_SCHEMA_VERSION = "wiii.completion_audit_runtime_evidence_promotion.v1"
PROMOTION_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit runtime evidence promotion output path must not be a directory"
)
PROMOTION_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit runtime evidence promotion output path must not be a symlink"
)
PROMOTION_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit runtime evidence promotion output path parent must not be a symlink"
)
PROMOTION_OUT_DIR_SYMLINK_ERROR = (
    "completion audit runtime evidence promotion out-dir must not be a symlink"
)
PROMOTION_OUT_DIR_PARENT_SYMLINK_ERROR = (
    "completion audit runtime evidence promotion out-dir parent must not be a symlink"
)
PROMOTION_OUT_DIR_RUNTIME_BUNDLE_ERROR = (
    "completion audit runtime evidence promotion out-dir must be outside runtime evidence dir"
)


@dataclass(frozen=True)
class PromotionArtifacts:
    runtime_evidence_bundle_report: str
    setup_handle_evidence: str
    setup_attestation: str
    setup_state_attested: str
    dispatch_gate_attested: str
    dispatch_run_attested: str


@dataclass(frozen=True)
class PromotionReport:
    schema_version: str
    ok: bool
    promotion_ready: bool
    runtime_evidence_dir: str
    runtime_evidence_bundle_report_path: str
    setup_handle_plan_path: str
    setup_state_path: str
    launch_pack_path: str
    out_dir: str
    artifacts: PromotionArtifacts
    setup_handle_count: int
    attestation_count: int
    setup_state_ready_count: int
    setup_state_pending_count: int
    dispatch_ready: bool
    dispatch_run_ok: bool
    blocked_dispatch_item_count: int
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def promote_completion_audit_runtime_evidence(
    runtime_evidence_dir: Path,
    runtime_evidence_bundle_report_path: Path,
    setup_handle_plan_path: Path,
    *,
    setup_state_path: Path,
    launch_pack_path: Path,
    out_dir: Path,
    repo_root: Path = Path("."),
    allow_env_read: bool = False,
    allow_network: bool = False,
) -> PromotionReport:
    validate_output_dir(out_dir, runtime_evidence_dir=runtime_evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = _promotion_artifacts(out_dir)
    _copy_bundle_report_pointer(
        runtime_evidence_bundle_report_path,
        artifacts.runtime_evidence_bundle_report,
    )

    errors = _bundle_report_gate_errors(runtime_evidence_bundle_report_path)
    if errors:
        return _report(
            runtime_evidence_dir,
            runtime_evidence_bundle_report_path,
            setup_handle_plan_path,
            setup_state_path=setup_state_path,
            launch_pack_path=launch_pack_path,
            out_dir=out_dir,
            artifacts=artifacts,
            errors=errors,
        )

    try:
        handle_evidence = handle_probe.probe_completion_audit_setup_handle_evidence(
            setup_handle_plan_path,
            allow_env_read=allow_env_read,
            allow_network=allow_network,
            runtime_evidence_dir=runtime_evidence_dir,
            runtime_evidence_bundle_report_path=runtime_evidence_bundle_report_path,
        )
        _write_json(Path(artifacts.setup_handle_evidence), handle_evidence)

        attestation = (
            attestation_from_handles.generate_completion_audit_setup_attestation_from_handles(
                setup_handle_plan_path,
                Path(artifacts.setup_handle_evidence),
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            )
        )
        _write_json(Path(artifacts.setup_attestation), attestation)

        setup_state_attested = (
            attestation_applier.apply_completion_audit_setup_attestation(
                setup_state_path,
                Path(artifacts.setup_attestation),
                launch_pack_path=launch_pack_path,
            )
        )
        _write_json(Path(artifacts.setup_state_attested), setup_state_attested)

        dispatch_gate = dispatch_generator.generate_completion_audit_dispatch_gate(
            launch_pack_path,
            Path(artifacts.setup_state_attested),
        ).to_dict()
        _write_json(Path(artifacts.dispatch_gate_attested), dispatch_gate)

        dispatch_run = dispatch_runner.run_completion_audit_dispatch_gate(
            Path(artifacts.dispatch_gate_attested),
            launch_pack_path=launch_pack_path,
            setup_state_path=Path(artifacts.setup_state_attested),
            repo_root=repo_root,
            execute=False,
            allow_live_dispatch=False,
        ).to_dict()
        _write_json(Path(artifacts.dispatch_run_attested), dispatch_run)
    except Exception as exc:  # noqa: BLE001
        return _report(
            runtime_evidence_dir,
            runtime_evidence_bundle_report_path,
            setup_handle_plan_path,
            setup_state_path=setup_state_path,
            launch_pack_path=launch_pack_path,
            out_dir=out_dir,
            artifacts=artifacts,
            errors=[str(exc)],
        )

    promotion_errors: list[str] = []
    if dispatch_gate.get("dispatch_ready") is not True:
        promotion_errors.append("completion audit promoted dispatch gate is not ready")
    if dispatch_run.get("ok") is not True:
        promotion_errors.append("completion audit promoted dispatch dry-run failed")
    return _report(
        runtime_evidence_dir,
        runtime_evidence_bundle_report_path,
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
        out_dir=out_dir,
        artifacts=artifacts,
        setup_handle_evidence=handle_evidence,
        setup_attestation=attestation,
        setup_state_attested=setup_state_attested,
        dispatch_gate=dispatch_gate,
        dispatch_run=dispatch_run,
        errors=promotion_errors,
    )


def _bundle_report_gate_errors(report_path: Path) -> list[str]:
    payload = load_strict_json_file(report_path)
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["completion audit runtime evidence bundle report root must be an object"]
    if (
        payload.get("schema_version")
        != handle_probe.RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION
    ):
        errors.append(
            "completion audit runtime evidence bundle report schema_version "
            f"must be {handle_probe.RUNTIME_EVIDENCE_BUNDLE_REPORT_SCHEMA_VERSION}"
        )
    if payload.get("ok") is not True:
        errors.append("completion audit runtime evidence bundle report ok must be true")
    if payload.get("completion_audit_ready") is not True:
        errors.append(
            "completion audit runtime evidence bundle report completion_audit_ready "
            "must be true"
        )
    return errors


def _promotion_artifacts(out_dir: Path) -> PromotionArtifacts:
    return PromotionArtifacts(
        runtime_evidence_bundle_report=str(out_dir / "runtime-evidence-bundle-report.json"),
        setup_handle_evidence=str(out_dir / "setup-handle-evidence.json"),
        setup_attestation=str(out_dir / "setup-attestation.json"),
        setup_state_attested=str(out_dir / "setup-state-attested.json"),
        dispatch_gate_attested=str(out_dir / "dispatch-gate-attested.json"),
        dispatch_run_attested=str(out_dir / "dispatch-run-attested.json"),
    )


def _copy_bundle_report_pointer(source: Path, destination: str) -> None:
    payload = load_strict_json_file(source)
    _write_json(Path(destination), payload)


def _report(
    runtime_evidence_dir: Path,
    runtime_evidence_bundle_report_path: Path,
    setup_handle_plan_path: Path,
    *,
    setup_state_path: Path,
    launch_pack_path: Path,
    out_dir: Path,
    artifacts: PromotionArtifacts,
    errors: list[str],
    setup_handle_evidence: dict[str, Any] | None = None,
    setup_attestation: dict[str, Any] | None = None,
    setup_state_attested: dict[str, Any] | None = None,
    dispatch_gate: dict[str, Any] | None = None,
    dispatch_run: dict[str, Any] | None = None,
) -> PromotionReport:
    return PromotionReport(
        schema_version=PROMOTION_SCHEMA_VERSION,
        ok=not errors,
        promotion_ready=not errors
        and dispatch_gate is not None
        and dispatch_gate.get("dispatch_ready") is True
        and dispatch_run is not None
        and dispatch_run.get("ok") is True,
        runtime_evidence_dir=str(runtime_evidence_dir),
        runtime_evidence_bundle_report_path=str(runtime_evidence_bundle_report_path),
        setup_handle_plan_path=str(setup_handle_plan_path),
        setup_state_path=str(setup_state_path),
        launch_pack_path=str(launch_pack_path),
        out_dir=str(out_dir),
        artifacts=artifacts,
        setup_handle_count=_int_from(setup_handle_evidence, "handle_count"),
        attestation_count=_int_from(setup_attestation, "attestation_count"),
        setup_state_ready_count=_int_from(setup_state_attested, "ready_setup_check_count"),
        setup_state_pending_count=_int_from(
            setup_state_attested,
            "pending_setup_check_count",
        ),
        dispatch_ready=dispatch_gate is not None
        and dispatch_gate.get("dispatch_ready") is True,
        dispatch_run_ok=dispatch_run is not None and dispatch_run.get("ok") is True,
        blocked_dispatch_item_count=_int_from(
            dispatch_gate,
            "blocked_dispatch_item_count",
        ),
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
            "raw_output_included": False,
        },
        errors=errors,
    )


def _int_from(payload: dict[str, Any] | None, field: str) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get(field)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    validate_output_path(path)
    safe_write_report_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True).rstrip("\n") + "\n",
    )


def validate_output_dir(out_dir: Path, *, runtime_evidence_dir: Path) -> None:
    if out_dir.is_symlink():
        raise ValueError(PROMOTION_OUT_DIR_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_dir):
        raise ValueError(PROMOTION_OUT_DIR_PARENT_SYMLINK_ERROR)
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError("completion audit runtime evidence promotion out-dir must be a directory")
    if _path_is_inside_directory(path=out_dir, directory=runtime_evidence_dir):
        raise ValueError(PROMOTION_OUT_DIR_RUNTIME_BUNDLE_ERROR)


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(PROMOTION_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(PROMOTION_OUTPUT_PATH_SYMLINK_ERROR)
    if _path_has_symlink_parent(out_path):
        raise ValueError(PROMOTION_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _path_has_symlink_parent(path: Path) -> bool:
    return any(parent.is_symlink() for parent in path.parents)


def _path_is_inside_directory(*, path: Path, directory: Path) -> bool:
    try:
        Path(path.resolve()).relative_to(directory.resolve())
    except ValueError:
        return False
    return True


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "bundle report ok must be true" in error:
        return "completion_audit_runtime_evidence_promotion_bundle_not_ok"
    if "completion_audit_ready must be true" in error:
        return "completion_audit_runtime_evidence_promotion_bundle_not_ready"
    if "bundle report schema_version" in error:
        return "completion_audit_runtime_evidence_promotion_bundle_schema_invalid"
    if "bundle report root must be an object" in error:
        return "completion_audit_runtime_evidence_promotion_bundle_root_invalid"
    if "setup handle evidence" in error:
        return "completion_audit_runtime_evidence_promotion_setup_handle_invalid"
    if "setup attestation" in error:
        return "completion_audit_runtime_evidence_promotion_attestation_invalid"
    if "dispatch gate" in error:
        return "completion_audit_runtime_evidence_promotion_dispatch_gate_invalid"
    if "dispatch dry-run" in error:
        return "completion_audit_runtime_evidence_promotion_dispatch_run_invalid"
    if error == PROMOTION_OUT_DIR_RUNTIME_BUNDLE_ERROR:
        return "completion_audit_runtime_evidence_promotion_out_dir_inside_bundle"
    if error == PROMOTION_OUT_DIR_SYMLINK_ERROR:
        return "completion_audit_runtime_evidence_promotion_out_dir_symlink"
    if error == PROMOTION_OUT_DIR_PARENT_SYMLINK_ERROR:
        return "completion_audit_runtime_evidence_promotion_out_dir_parent_symlink"
    if error == PROMOTION_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_runtime_evidence_promotion_output_path_directory"
    if error == PROMOTION_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_runtime_evidence_promotion_output_path_symlink"
    if error == PROMOTION_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_runtime_evidence_promotion_output_path_parent_symlink"
    return "completion_audit_runtime_evidence_promotion_failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Promote validated runtime evidence into setup attestation, "
            "attested setup state, and a dispatch dry-run."
        ),
    )
    parser.add_argument("runtime_evidence_dir", type=Path)
    parser.add_argument("--runtime-evidence-bundle-report", type=Path, required=True)
    parser.add_argument("--setup-handle-plan", type=Path, required=True)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--launch-pack", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--allow-env-read", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = promote_completion_audit_runtime_evidence(
            args.runtime_evidence_dir,
            args.runtime_evidence_bundle_report,
            args.setup_handle_plan,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
            out_dir=args.out_dir,
            repo_root=args.repo_root,
            allow_env_read=args.allow_env_read,
            allow_network=args.allow_network,
        )
    except Exception as exc:  # noqa: BLE001
        report = _report(
            args.runtime_evidence_dir,
            args.runtime_evidence_bundle_report,
            args.setup_handle_plan,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
            out_dir=args.out_dir,
            artifacts=_promotion_artifacts(args.out_dir),
            errors=[str(exc)],
        )
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0 if report.ok and report.promotion_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
