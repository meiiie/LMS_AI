#!/usr/bin/env python3
"""Validate completion-audit setup-attestation smoke sidecar reports."""

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

from smoke_completion_audit_setup_attestation import (  # noqa: E402
    SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_dispatch_gate as dispatch_gate_validator  # noqa: E402
import validate_completion_audit_dispatch_run as dispatch_run_validator  # noqa: E402
import validate_completion_audit_setup_attestation as attestation_validator  # noqa: E402
import validate_completion_audit_setup_attestation_template as template_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_state_validator  # noqa: E402


SETUP_ATTESTATION_SMOKE_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_attestation_smoke_validation.v1"
)
GENERATED_REPORTS = [
    "setup-attestation.json",
    "setup-handle-patch.json",
    "setup-state-attested.json",
    "dispatch-gate-attested.json",
    "dispatch-run-dry.json",
]
REQUIRED_SMOKE_FIELDS = {
    "schema_version",
    "ok",
    "dry_run_only",
    "source_paths",
    "out_dir",
    "generated_reports",
    "source_fingerprints",
    "template_pending_setup_check_count",
    "selected_attestation_count",
    "attestation_count",
    "attested_setup_dispatch_ready",
    "dispatch_gate_ready",
    "dispatch_run_ok",
    "dispatch_run_dry_run",
    "dispatch_run_command_count",
    "dispatch_run_executed_command_count",
    "validation",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
ALLOWED_SMOKE_FIELDS = REQUIRED_SMOKE_FIELDS
SOURCE_PATH_FIELDS = {
    "launch_pack",
    "setup_state",
    "setup_handle_plan",
    "setup_attestation_template",
}
VALIDATION_FIELDS = {
    "template",
    "setup_attestation",
    "attested_setup_state",
    "dispatch_gate",
    "dispatch_run",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
    "raw_output_included",
}
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SetupAttestationSmokeValidationResult:
    validation_schema_version: str
    smoke_json_path: str
    launch_pack_path: str | None
    setup_state_path: str | None
    setup_handle_plan_path: str | None
    template_path: str | None
    out_dir: str | None
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


def validate_completion_audit_setup_attestation_smoke(
    smoke_json_path: Path,
    *,
    launch_pack_path: Path | None = None,
    setup_state_path: Path | None = None,
    setup_handle_plan_path: Path | None = None,
    template_path: Path | None = None,
    out_dir: Path | None = None,
    repo_root: Path = Path("."),
) -> SetupAttestationSmokeValidationResult:
    errors: list[str] = []
    payload = _load_json_object(smoke_json_path, label="setup attestation smoke", errors=errors)
    if payload is not None:
        _payload_errors(payload, errors)
        if any(
            value is not None
            for value in (
                launch_pack_path,
                setup_state_path,
                setup_handle_plan_path,
                template_path,
                out_dir,
            )
        ):
            _source_errors(
                payload,
                errors,
                launch_pack_path=launch_pack_path,
                setup_state_path=setup_state_path,
                setup_handle_plan_path=setup_handle_plan_path,
                template_path=template_path,
                out_dir=out_dir,
                repo_root=repo_root,
            )
    return SetupAttestationSmokeValidationResult(
        validation_schema_version=SETUP_ATTESTATION_SMOKE_VALIDATION_SCHEMA_VERSION,
        smoke_json_path=str(smoke_json_path),
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        setup_handle_plan_path=(
            str(setup_handle_plan_path) if setup_handle_plan_path else None
        ),
        template_path=str(template_path) if template_path else None,
        out_dir=str(out_dir) if out_dir else None,
        errors=errors,
    )


def _load_json_object(
    path: Path,
    *,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append(f"{label} path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label} JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any], errors: list[str]) -> None:
    fields = set(payload)
    missing = sorted(REQUIRED_SMOKE_FIELDS - fields)
    extra = sorted(fields - ALLOWED_SMOKE_FIELDS)
    if missing:
        errors.append(
            "setup attestation smoke missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "setup attestation smoke has unsupported field(s): " + ", ".join(extra)
        )
    if payload.get("schema_version") != SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION:
        errors.append(
            "setup attestation smoke schema_version must be "
            f"{SETUP_ATTESTATION_SMOKE_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("setup attestation smoke ok must be true")
    if payload.get("dry_run_only") is not True:
        errors.append("setup attestation smoke dry_run_only must be true")
    if payload.get("generated_reports") != GENERATED_REPORTS:
        errors.append("setup attestation smoke generated_reports must match contract")
    _source_path_payload_errors(payload.get("source_paths"), errors)
    _fingerprint_payload_errors(payload.get("source_fingerprints"), errors)
    _count_payload_errors(payload, errors)
    _validation_payload_errors(payload.get("validation"), errors)
    _privacy_payload_errors(payload.get("privacy"), errors)
    if payload.get("errors") != []:
        errors.append("setup attestation smoke errors must be empty")
    if payload.get("error_codes") != []:
        errors.append("setup attestation smoke error_codes must be empty")
    if payload.get("error_code_counts") != {}:
        errors.append("setup attestation smoke error_code_counts must be empty")


def _source_path_payload_errors(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("setup attestation smoke source_paths must be an object")
        return
    if set(value) != SOURCE_PATH_FIELDS:
        errors.append("setup attestation smoke source_paths fields must match contract")
    for field in SOURCE_PATH_FIELDS:
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"setup attestation smoke source_paths.{field} must be set")


def _fingerprint_payload_errors(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("setup attestation smoke source_fingerprints must be an object")
        return
    for field, fingerprint in value.items():
        if not isinstance(field, str) or not _is_fingerprint(fingerprint):
            errors.append(
                "setup attestation smoke source_fingerprints values must be "
                "SHA-256 hex strings"
            )
            return


def _count_payload_errors(payload: dict[str, Any], errors: list[str]) -> None:
    pending = payload.get("template_pending_setup_check_count")
    selected = payload.get("selected_attestation_count")
    attestations = payload.get("attestation_count")
    command_count = payload.get("dispatch_run_command_count")
    executed = payload.get("dispatch_run_executed_command_count")
    for field in (
        "template_pending_setup_check_count",
        "selected_attestation_count",
        "attestation_count",
        "dispatch_run_command_count",
        "dispatch_run_executed_command_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"setup attestation smoke {field} must be a non-negative int")
    if _is_non_negative_int(pending) and pending <= 0:
        errors.append("setup attestation smoke must cover at least one pending check")
    if (
        _is_non_negative_int(pending)
        and _is_non_negative_int(selected)
        and pending != selected
    ):
        errors.append("setup attestation smoke selected count must match pending count")
    if (
        _is_non_negative_int(selected)
        and _is_non_negative_int(attestations)
        and selected != attestations
    ):
        errors.append(
            "setup attestation smoke attestation count must match selected count"
        )
    if payload.get("attested_setup_dispatch_ready") is not True:
        errors.append("setup attestation smoke attested setup must be dispatch-ready")
    if payload.get("dispatch_gate_ready") is not True:
        errors.append("setup attestation smoke dispatch gate must be ready")
    if payload.get("dispatch_run_ok") is not True:
        errors.append("setup attestation smoke dispatch run must be ok")
    if payload.get("dispatch_run_dry_run") is not True:
        errors.append("setup attestation smoke dispatch run must be dry-run")
    if _is_non_negative_int(command_count) and command_count <= 0:
        errors.append("setup attestation smoke must materialize commands")
    if _is_non_negative_int(executed) and executed != 0:
        errors.append("setup attestation smoke must not execute commands")


def _validation_payload_errors(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("setup attestation smoke validation must be an object")
        return
    if set(value) != VALIDATION_FIELDS:
        errors.append("setup attestation smoke validation fields must match contract")
    for field in VALIDATION_FIELDS:
        report = value.get(field)
        if not isinstance(report, dict):
            errors.append(f"setup attestation smoke validation.{field} must be object")
        elif report.get("ok") is not True:
            errors.append(f"setup attestation smoke validation.{field}.ok must be true")


def _privacy_payload_errors(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("setup attestation smoke privacy must be an object")
        return
    if set(value) != PRIVACY_FIELDS:
        errors.append("setup attestation smoke privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup attestation smoke privacy.{field} must be false")


def _source_errors(
    payload: dict[str, Any],
    errors: list[str],
    *,
    launch_pack_path: Path | None,
    setup_state_path: Path | None,
    setup_handle_plan_path: Path | None,
    template_path: Path | None,
    out_dir: Path | None,
    repo_root: Path,
) -> None:
    if (
        launch_pack_path is None
        or setup_state_path is None
        or setup_handle_plan_path is None
        or template_path is None
        or out_dir is None
    ):
        errors.append(
            "setup attestation smoke source validation requires launch-pack, "
            "setup-state, setup-handle-plan, template, and out-dir"
        )
        return
    _source_path_parity_errors(
        payload,
        errors,
        launch_pack_path=launch_pack_path,
        setup_state_path=setup_state_path,
        setup_handle_plan_path=setup_handle_plan_path,
        template_path=template_path,
        out_dir=out_dir,
    )
    paths = _generated_report_paths(out_dir, errors)
    if paths is None:
        return
    template_validation = template_validator.validate_setup_attestation_template(
        template_path,
        setup_handle_plan_path=setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    attestation_validation = attestation_validator.validate_setup_attestation(
        paths["setup-attestation.json"],
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
        patch_path=paths["setup-handle-patch.json"],
    ).to_dict()
    attested_setup_validation = setup_state_validator.validate_setup_state(
        paths["setup-state-attested.json"],
        launch_pack_path=launch_pack_path,
    ).to_dict()
    dispatch_gate_validation = dispatch_gate_validator.validate_dispatch_gate(
        paths["dispatch-gate-attested.json"],
        launch_pack_path=launch_pack_path,
        setup_state_path=paths["setup-state-attested.json"],
    ).to_dict()
    dispatch_run_validation = dispatch_run_validator.validate_dispatch_run(
        paths["dispatch-run-dry.json"],
        dispatch_gate_path=paths["dispatch-gate-attested.json"],
        launch_pack_path=launch_pack_path,
        setup_state_path=paths["setup-state-attested.json"],
        repo_root=repo_root,
    ).to_dict()
    expected_validation = {
        "template": template_validation,
        "setup_attestation": attestation_validation,
        "attested_setup_state": attested_setup_validation,
        "dispatch_gate": dispatch_gate_validation,
        "dispatch_run": dispatch_run_validation,
    }
    if payload.get("validation") != expected_validation:
        errors.append("setup attestation smoke embedded validation must match sources")
    _generated_report_summary_errors(payload, paths, errors)


def _source_path_parity_errors(
    payload: dict[str, Any],
    errors: list[str],
    *,
    launch_pack_path: Path,
    setup_state_path: Path,
    setup_handle_plan_path: Path,
    template_path: Path,
    out_dir: Path,
) -> None:
    source_paths = payload.get("source_paths")
    if isinstance(source_paths, dict):
        expected = {
            "launch_pack": str(launch_pack_path),
            "setup_state": str(setup_state_path),
            "setup_handle_plan": str(setup_handle_plan_path),
            "setup_attestation_template": str(template_path),
        }
        if source_paths != expected:
            errors.append("setup attestation smoke source_paths must match sources")
    if payload.get("out_dir") != str(out_dir):
        errors.append("setup attestation smoke out_dir must match source")


def _generated_report_paths(
    out_dir: Path,
    errors: list[str],
) -> dict[str, Path] | None:
    if not out_dir.is_dir() or out_dir.is_symlink():
        errors.append("setup attestation smoke out_dir must be a regular directory")
        return None
    paths = {name: out_dir / name for name in GENERATED_REPORTS}
    for name, path in paths.items():
        if not path.is_file() or path.is_symlink():
            errors.append(f"setup attestation smoke report missing: {name}")
    if any(error.startswith("setup attestation smoke report missing") for error in errors):
        return None
    return paths


def _generated_report_summary_errors(
    payload: dict[str, Any],
    paths: dict[str, Path],
    errors: list[str],
) -> None:
    attestation = load_strict_json_file(paths["setup-attestation.json"])
    attested_setup = load_strict_json_file(paths["setup-state-attested.json"])
    dispatch_gate = load_strict_json_file(paths["dispatch-gate-attested.json"])
    dispatch_run = load_strict_json_file(paths["dispatch-run-dry.json"])
    if not all(
        isinstance(item, dict)
        for item in (attestation, attested_setup, dispatch_gate, dispatch_run)
    ):
        errors.append("setup attestation smoke generated reports must be objects")
        return
    if payload.get("attestation_count") != attestation.get("attestation_count"):
        errors.append("setup attestation smoke attestation_count must match report")
    if payload.get("attested_setup_dispatch_ready") != attested_setup.get("dispatch_ready"):
        errors.append(
            "setup attestation smoke attested_setup_dispatch_ready must match report"
        )
    if payload.get("dispatch_gate_ready") != dispatch_gate.get("dispatch_ready"):
        errors.append("setup attestation smoke dispatch_gate_ready must match report")
    for field, report_field in (
        ("dispatch_run_ok", "ok"),
        ("dispatch_run_dry_run", "dry_run"),
        ("dispatch_run_command_count", "command_count"),
        ("dispatch_run_executed_command_count", "executed_command_count"),
    ):
        if payload.get(field) != dispatch_run.get(report_field):
            errors.append(f"setup attestation smoke {field} must match report")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a completion-audit setup-attestation smoke report and, "
            "when source paths are supplied, revalidate generated sidecar reports."
        ),
    )
    parser.add_argument("smoke_json", type=Path)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--setup-handle-plan", type=Path, default=None)
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_completion_audit_setup_attestation_smoke(
        args.smoke_json,
        launch_pack_path=args.launch_pack,
        setup_state_path=args.setup_state,
        setup_handle_plan_path=args.setup_handle_plan,
        template_path=args.template,
        out_dir=args.out_dir,
        repo_root=args.repo_root,
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
        print("Wiii Completion Audit Setup Attestation Smoke Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Attestation Smoke Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "setup attestation smoke path must be a regular file":
        return "setup_attestation_smoke_path_invalid"
    if error.startswith("setup attestation smoke JSON is invalid"):
        return "setup_attestation_smoke_json_invalid"
    if error == "setup attestation smoke root must be an object":
        return "setup_attestation_smoke_root_invalid"
    if error.startswith("setup attestation smoke missing required field"):
        return "setup_attestation_smoke_missing_required_fields"
    if error.startswith("setup attestation smoke has unsupported field"):
        return "setup_attestation_smoke_unsupported_fields"
    if "schema_version" in error:
        return "setup_attestation_smoke_schema_mismatch"
    if "source validation requires" in error:
        return "setup_attestation_smoke_source_args_missing"
    if "source_paths" in error or "out_dir must match" in error:
        return "setup_attestation_smoke_source_mismatch"
    if "source_fingerprints" in error or "SHA-256" in error:
        return "setup_attestation_smoke_fingerprint_invalid"
    if "generated_reports" in error or "report missing" in error:
        return "setup_attestation_smoke_report_invalid"
    if "embedded validation" in error or "validation." in error:
        return "setup_attestation_smoke_validation_mismatch"
    if "privacy" in error or "raw_" in error or "secret" in error:
        return "setup_attestation_smoke_privacy_invalid"
    if "count" in error or "pending" in error or "commands" in error:
        return "setup_attestation_smoke_count_invalid"
    if "dispatch" in error or "dry-run" in error or "execute" in error:
        return "setup_attestation_smoke_dispatch_state_invalid"
    if "errors must be empty" in error or "error_codes" in error:
        return "setup_attestation_smoke_error_summary_invalid"
    return "setup_attestation_smoke_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
