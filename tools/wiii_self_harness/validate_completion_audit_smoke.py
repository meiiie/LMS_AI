#!/usr/bin/env python3
"""Validate completion-audit smoke sidecar reports after generation."""

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

from generate_completion_audit_handoff import EXPECTED_GENERATED_REPORTS  # noqa: E402
from smoke_completion_audit_handoff import SMOKE_SCHEMA_VERSION  # noqa: E402
from strict_json import load_strict_json_file  # noqa: E402
from validate_completion_audit_handoff import validate_handoff_bundle  # noqa: E402


SMOKE_VALIDATION_SCHEMA_VERSION = "wiii.completion_audit_handoff_smoke_validation.v1"
REQUIRED_SMOKE_FIELDS = {
    "schema_version",
    "ok",
    "handoff_ok",
    "completion_audit_ready",
    "handoff_root",
    "artifact_bundle_root",
    "self_harness_report_bundle_root",
    "reports",
    "handoff_validation",
    "release_gate_validation",
    "runtime_evidence_bundle_report",
}
ALLOWED_SMOKE_FIELDS = REQUIRED_SMOKE_FIELDS
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SmokeValidationResult:
    validation_schema_version: str
    smoke_json_path: str
    release_gate_json_path: str
    structural_validation_json_path: str | None
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


def validate_completion_audit_smoke_sidecars(
    *,
    smoke_json_path: Path,
    release_gate_json_path: Path,
    structural_validation_json_path: Path | None = None,
    require_handoff_root_source: bool = False,
) -> SmokeValidationResult:
    errors: list[str] = []
    smoke_payload = _load_json_object(
        smoke_json_path,
        label="smoke JSON",
        errors=errors,
    )
    release_gate_payload = _load_json_object(
        release_gate_json_path,
        label="release-gate JSON",
        errors=errors,
    )
    structural_validation_payload: dict[str, Any] | None = None
    if structural_validation_json_path is not None:
        structural_validation_payload = _load_json_object(
            structural_validation_json_path,
            label="structural validation JSON",
            errors=errors,
        )

    if smoke_payload is not None:
        _validate_smoke_payload(smoke_payload, errors)
        embedded_release_gate = smoke_payload.get("release_gate_validation")
        if release_gate_payload is not None and release_gate_payload != embedded_release_gate:
            errors.append("release-gate sidecar JSON must match smoke payload")
        embedded_structural = smoke_payload.get("handoff_validation")
        if (
            structural_validation_payload is not None
            and structural_validation_payload != embedded_structural
        ):
            errors.append("structural validation sidecar JSON must match smoke payload")
        if require_handoff_root_source:
            _validate_handoff_root_source(smoke_payload, errors)

    return SmokeValidationResult(
        validation_schema_version=SMOKE_VALIDATION_SCHEMA_VERSION,
        smoke_json_path=str(smoke_json_path),
        release_gate_json_path=str(release_gate_json_path),
        structural_validation_json_path=(
            str(structural_validation_json_path)
            if structural_validation_json_path is not None
            else None
        ),
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
        errors.append(f"{label} is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} root must be an object")
        return None
    return payload


def _validate_smoke_payload(payload: dict[str, Any], errors: list[str]) -> None:
    fields = set(payload)
    missing = sorted(REQUIRED_SMOKE_FIELDS - fields)
    extra = sorted(fields - ALLOWED_SMOKE_FIELDS)
    if missing:
        errors.append("smoke JSON missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("smoke JSON has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != SMOKE_SCHEMA_VERSION:
        errors.append(f"smoke schema_version must be {SMOKE_SCHEMA_VERSION!r}")
    if payload.get("ok") is not True:
        errors.append("smoke ok must be true")
    if payload.get("handoff_ok") is not False:
        errors.append("smoke handoff_ok must be false")
    if payload.get("completion_audit_ready") is not False:
        errors.append("smoke completion_audit_ready must be false")
    if payload.get("reports") != list(EXPECTED_GENERATED_REPORTS):
        errors.append("smoke reports must match expected generated reports")

    handoff_validation = payload.get("handoff_validation")
    release_gate_validation = payload.get("release_gate_validation")
    runtime_report = payload.get("runtime_evidence_bundle_report")
    if not isinstance(handoff_validation, dict):
        errors.append("smoke handoff_validation must be an object")
    if not isinstance(release_gate_validation, dict):
        errors.append("smoke release_gate_validation must be an object")
    if not isinstance(runtime_report, dict):
        errors.append("smoke runtime_evidence_bundle_report must be an object")
    if isinstance(handoff_validation, dict) and isinstance(release_gate_validation, dict):
        _validate_validation_pair(handoff_validation, release_gate_validation, errors)
    if isinstance(runtime_report, dict):
        _validate_runtime_report(runtime_report, errors)


def _validate_validation_pair(
    handoff_validation: dict[str, Any],
    release_gate_validation: dict[str, Any],
    errors: list[str],
) -> None:
    if handoff_validation.get("ok") is not True:
        errors.append("smoke handoff_validation.ok must be true")
    if handoff_validation.get("require_completion_audit_ready") is not False:
        errors.append(
            "smoke handoff_validation.require_completion_audit_ready must be false"
        )
    if release_gate_validation.get("ok") is not False:
        errors.append("smoke release_gate_validation.ok must be false")
    if release_gate_validation.get("require_completion_audit_ready") is not True:
        errors.append(
            "smoke release_gate_validation.require_completion_audit_ready must be true"
        )
    error_codes = release_gate_validation.get("error_codes")
    if not isinstance(error_codes, list) or not all(
        isinstance(item, str) for item in error_codes
    ):
        errors.append("smoke release_gate_validation.error_codes must be a string list")
    elif "handoff_completion_audit_not_ready" not in error_codes:
        errors.append(
            "smoke release_gate_validation.error_codes must include "
            "handoff_completion_audit_not_ready"
        )

    structural_fingerprint = handoff_validation.get("bundle_fingerprint_sha256")
    release_gate_fingerprint = release_gate_validation.get("bundle_fingerprint_sha256")
    if not _is_fingerprint(structural_fingerprint):
        errors.append(
            "smoke handoff_validation.bundle_fingerprint_sha256 must be a SHA-256 "
            "hex string"
        )
    if not _is_fingerprint(release_gate_fingerprint):
        errors.append(
            "smoke release_gate_validation.bundle_fingerprint_sha256 must be a "
            "SHA-256 hex string"
        )
    if (
        _is_fingerprint(structural_fingerprint)
        and _is_fingerprint(release_gate_fingerprint)
        and structural_fingerprint == release_gate_fingerprint
    ):
        errors.append("smoke validation fingerprints must differ by policy mode")


def _validate_runtime_report(
    runtime_report: dict[str, Any],
    errors: list[str],
) -> None:
    if runtime_report.get("ok") is not False:
        errors.append("smoke runtime_evidence_bundle_report.ok must be false")
    if runtime_report.get("completion_audit_ready") is not False:
        errors.append(
            "smoke runtime_evidence_bundle_report.completion_audit_ready must be false"
        )
    if runtime_report.get("error_codes") != ["missing_artifact"]:
        errors.append(
            "smoke runtime_evidence_bundle_report.error_codes must be "
            "['missing_artifact']"
        )
    requirement_count = runtime_report.get("requirement_count")
    missing_count = runtime_report.get("missing_count")
    if not _is_positive_int(requirement_count):
        errors.append(
            "smoke runtime_evidence_bundle_report.requirement_count must be positive"
        )
    if (
        not isinstance(missing_count, int)
        or isinstance(missing_count, bool)
        or missing_count < 0
    ):
        errors.append(
            "smoke runtime_evidence_bundle_report.missing_count must be non-negative"
        )
    elif _is_positive_int(requirement_count) and missing_count != requirement_count:
        errors.append(
            "smoke runtime_evidence_bundle_report.missing_count must match "
            "requirement_count"
        )


def _validate_handoff_root_source(
    smoke_payload: dict[str, Any],
    errors: list[str],
) -> None:
    handoff_root = smoke_payload.get("handoff_root")
    if not isinstance(handoff_root, str) or not handoff_root:
        errors.append("smoke handoff_root must be a non-empty string")
        return
    try:
        structural_validation = validate_handoff_bundle(Path(handoff_root)).to_dict()
        release_gate_validation = validate_handoff_bundle(
            Path(handoff_root),
            require_completion_audit_ready=True,
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"smoke handoff_root source validation failed: {exc}")
        return
    if structural_validation != smoke_payload.get("handoff_validation"):
        errors.append(
            "structural validation sidecar JSON must match current handoff root"
        )
    if release_gate_validation != smoke_payload.get("release_gate_validation"):
        errors.append("release-gate sidecar JSON must match current handoff root")


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return counts


def _error_code(error: str) -> str:
    if error.startswith("smoke JSON is invalid"):
        return "smoke_json_invalid"
    if error == "smoke JSON root must be an object":
        return "smoke_json_root_invalid"
    if error == "smoke JSON path must be a regular file":
        return "smoke_json_path_invalid"
    if error.startswith("release-gate JSON is invalid"):
        return "release_gate_json_invalid"
    if error == "release-gate JSON root must be an object":
        return "release_gate_json_root_invalid"
    if error == "release-gate JSON path must be a regular file":
        return "release_gate_json_path_invalid"
    if error.startswith("structural validation JSON is invalid"):
        return "structural_validation_json_invalid"
    if error == "structural validation JSON root must be an object":
        return "structural_validation_json_root_invalid"
    if error == "structural validation JSON path must be a regular file":
        return "structural_validation_json_path_invalid"
    if error.startswith("smoke JSON missing required field"):
        return "smoke_json_missing_required_fields"
    if error.startswith("smoke JSON has unsupported field"):
        return "smoke_json_unsupported_fields"
    if error.startswith("smoke schema_version must be"):
        return "smoke_schema_mismatch"
    if error == "smoke ok must be true":
        return "smoke_ok_false"
    if error == "smoke handoff_ok must be false":
        return "smoke_handoff_ok_not_false"
    if error == "smoke completion_audit_ready must be false":
        return "smoke_completion_audit_ready_not_false"
    if error == "smoke reports must match expected generated reports":
        return "smoke_reports_mismatch"
    if error == "smoke handoff_validation must be an object":
        return "smoke_handoff_validation_invalid"
    if error == "smoke release_gate_validation must be an object":
        return "smoke_release_gate_validation_invalid"
    if error == "smoke runtime_evidence_bundle_report must be an object":
        return "smoke_runtime_report_invalid"
    if error == "smoke handoff_validation.ok must be true":
        return "smoke_structural_validation_not_ok"
    if error.endswith("require_completion_audit_ready must be false"):
        return "smoke_structural_policy_mode_mismatch"
    if error == "smoke release_gate_validation.ok must be false":
        return "smoke_release_gate_validation_ok"
    if error.endswith("require_completion_audit_ready must be true"):
        return "smoke_release_gate_policy_mode_mismatch"
    if "release_gate_validation.error_codes" in error:
        return "smoke_release_gate_error_codes_invalid"
    if "bundle_fingerprint_sha256 must be a SHA-256" in error:
        return "smoke_validation_fingerprint_invalid"
    if error == "smoke validation fingerprints must differ by policy mode":
        return "smoke_validation_fingerprint_policy_mismatch"
    if error.startswith("smoke runtime_evidence_bundle_report."):
        return "smoke_runtime_report_mismatch"
    if error == "release-gate sidecar JSON must match smoke payload":
        return "smoke_release_gate_sidecar_mismatch"
    if error == "structural validation sidecar JSON must match smoke payload":
        return "smoke_structural_sidecar_mismatch"
    if error == "smoke handoff_root must be a non-empty string":
        return "smoke_handoff_root_invalid"
    if error.startswith("smoke handoff_root source validation failed"):
        return "smoke_handoff_root_source_invalid"
    if error == "release-gate sidecar JSON must match current handoff root":
        return "smoke_release_gate_source_mismatch"
    if error == "structural validation sidecar JSON must match current handoff root":
        return "smoke_structural_source_mismatch"
    return "completion_audit_smoke_validation_error"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate completion-audit smoke JSON sidecars after generation.",
    )
    parser.add_argument("smoke_json", type=Path)
    parser.add_argument("--release-gate-json", type=Path, required=True)
    parser.add_argument("--structural-validation-json", type=Path, default=None)
    parser.add_argument(
        "--require-handoff-root-source",
        action="store_true",
        help=(
            "Rerun structural and release-gate validation against smoke.handoff_root "
            "and require both embedded sidecars to match the current bundle."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_completion_audit_smoke_sidecars(
        smoke_json_path=args.smoke_json,
        release_gate_json_path=args.release_gate_json,
        structural_validation_json_path=args.structural_validation_json,
        require_handoff_root_source=args.require_handoff_root_source,
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
        print("Wiii Completion Audit Smoke Sidecars: PASS")
    else:
        print(
            "Wiii Completion Audit Smoke Sidecars: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
