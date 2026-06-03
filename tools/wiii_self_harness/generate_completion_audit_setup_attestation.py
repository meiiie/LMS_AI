#!/usr/bin/env python3
"""Generate source-bound completion-audit setup attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from apply_completion_audit_setup_state import (  # noqa: E402
    SETUP_HANDLE_PATCH_SCHEMA_VERSION,
    _patch_binding_errors,
    _patch_errors,
    _patch_source_errors,
    _sha256_file,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_ATTESTATION_SCHEMA_VERSION = "wiii.completion_audit_setup_attestation.v1"
ATTESTATION_EVIDENCE_KINDS = {
    "workflow_input_bound",
    "environment_flag_bound",
    "github_secret_present",
    "github_variable_present",
    "operator_approved_recipient",
    "runtime_channel_credential_validated",
    "runtime_channel_enabled",
    "provider_account_connected",
    "backend_health_checked",
    "readonly_schema_validated",
    "execution_policy_validated",
}
ATTESTATION_TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "setup_attestation_fingerprint_sha256",
    "attestation_count",
    "attestations",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
ATTESTATION_FIELDS = {
    "requirement_id",
    "category",
    "key",
    "source_handle",
    "evidence_kind",
    "evidence_ref",
}
ATTESTATION_PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}
ATTESTATION_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup attestation output path must not be a directory"
)
ATTESTATION_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup attestation output path must not be a symlink"
)
ATTESTATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation output path parent must not be a symlink"
)


def generate_completion_audit_setup_attestation(
    setup_state_path: Path,
    attest_specs: list[str],
    *,
    launch_pack_path: Path | None = None,
) -> dict[str, Any]:
    setup_validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not setup_validation.ok:
        raise ValueError(
            "completion audit setup attestation source setup state failed validation: "
            + "; ".join(setup_validation.errors)
        )
    setup_payload = load_strict_json_file(setup_state_path)
    if not isinstance(setup_payload, dict):
        raise ValueError("completion audit setup state root must be an object")
    attestations = [_parse_attest_spec(spec) for spec in attest_specs]
    payload = {
        "schema_version": SETUP_ATTESTATION_SCHEMA_VERSION,
        "ok": True,
        "setup_state_sha256": _sha256_file(setup_state_path),
        "setup_state_schema_version": setup_payload.get("schema_version"),
        "setup_state_fingerprint_sha256": setup_payload.get(
            "setup_state_fingerprint_sha256"
        ),
        "setup_attestation_fingerprint_sha256": _attestation_fingerprint(
            attestations
        ),
        "attestation_count": len(attestations),
        "attestations": attestations,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        "errors": [],
    }
    payload["error_codes"] = _error_codes(payload["errors"])
    payload["error_code_counts"] = _error_code_counts(payload["errors"])
    errors = _attestation_errors(payload)
    if not errors:
        errors.extend(
            _attestation_source_errors(
                payload,
                setup_payload=setup_payload,
                setup_state_path=setup_state_path,
            )
        )
        patch = setup_handle_patch_from_attestation(payload)
        errors.extend(_patch_errors(patch))
        if not errors:
            errors.extend(
                _patch_source_errors(
                    patch,
                    setup_payload=setup_payload,
                    setup_state_path=setup_state_path,
                )
            )
            errors.extend(_patch_binding_errors(setup_payload, patch))
    if errors:
        raise ValueError(
            "completion audit setup attestation generation failed validation: "
            + "; ".join(errors)
        )
    return payload


def setup_handle_patch_from_attestation(payload: dict[str, Any]) -> dict[str, Any]:
    checks = [
        {
            "requirement_id": item["requirement_id"],
            "category": item["category"],
            "key": item["key"],
            "source_handle": item["source_handle"],
        }
        for item in payload.get("attestations", [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": SETUP_HANDLE_PATCH_SCHEMA_VERSION,
        "ok": True,
        "setup_state_sha256": payload.get("setup_state_sha256"),
        "setup_state_schema_version": payload.get("setup_state_schema_version"),
        "setup_state_fingerprint_sha256": payload.get(
            "setup_state_fingerprint_sha256"
        ),
        "checks": checks,
        "privacy": {
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
        },
    }


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(ATTESTATION_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(ATTESTATION_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(ATTESTATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a source-bound setup attestation and optional "
            "setup-handle patch without writing secret values or raw identifiers."
        ),
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument(
        "--attest",
        action="append",
        default=[],
        help=(
            "Attestation as requirement_id:category:key=source_handle"
            "@evidence_kind:evidence_ref. Repeat for each setup check."
        ),
    )
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--patch-out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        validate_output_path(args.patch_out)
        attestation = generate_completion_audit_setup_attestation(
            args.setup_state,
            args.attest,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(attestation, indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    if args.patch_out:
        patch = setup_handle_patch_from_attestation(attestation)
        safe_write_report_text(
            args.patch_out,
            json.dumps(patch, indent=2, sort_keys=True).rstrip("\n") + "\n",
        )
    return 0


def _parse_attest_spec(value: str) -> dict[str, str]:
    if "=" not in value or "@" not in value:
        raise ValueError(
            "completion audit setup attestation spec must be "
            "requirement_id:category:key=source_handle@evidence_kind:evidence_ref"
        )
    left, right = value.split("=", 1)
    source_handle, evidence = right.split("@", 1)
    if ":" not in evidence:
        raise ValueError(
            "completion audit setup attestation spec must be "
            "requirement_id:category:key=source_handle@evidence_kind:evidence_ref"
        )
    evidence_kind, evidence_ref = evidence.split(":", 1)
    parts = left.split(":")
    if (
        len(parts) != 3
        or not all(parts)
        or not source_handle
        or not evidence_kind
        or not evidence_ref
    ):
        raise ValueError(
            "completion audit setup attestation spec must be "
            "requirement_id:category:key=source_handle@evidence_kind:evidence_ref"
        )
    requirement_id, category, key = parts
    return {
        "requirement_id": requirement_id,
        "category": category,
        "key": key,
        "source_handle": source_handle,
        "evidence_kind": evidence_kind,
        "evidence_ref": evidence_ref,
    }


def _attestation_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(ATTESTATION_TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - ATTESTATION_TOP_LEVEL_FIELDS)
    if missing:
        errors.append("setup attestation missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("setup attestation has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != SETUP_ATTESTATION_SCHEMA_VERSION:
        errors.append(
            "setup attestation schema_version must be "
            f"{SETUP_ATTESTATION_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("setup attestation ok must be true")
    for field in (
        "setup_state_sha256",
        "setup_state_fingerprint_sha256",
        "setup_attestation_fingerprint_sha256",
    ):
        if not setup_validator._is_fingerprint(payload.get(field)):
            errors.append(f"setup attestation {field} must be a SHA-256 hex string")
    if payload.get("setup_state_schema_version") != setup_validator.SETUP_STATE_SCHEMA_VERSION:
        errors.append(
            "setup attestation setup_state_schema_version must be "
            f"{setup_validator.SETUP_STATE_SCHEMA_VERSION!r}"
        )
    attestations = payload.get("attestations")
    if not isinstance(attestations, list) or not attestations:
        errors.append("setup attestation attestations must be a non-empty list")
    elif not all(isinstance(item, dict) for item in attestations):
        errors.append("setup attestation entries must be objects")
    else:
        seen: set[tuple[str, str, str]] = set()
        for item in attestations:
            errors.extend(_attestation_item_errors(item))
            identity = (
                item.get("requirement_id"),
                item.get("category"),
                item.get("key"),
            )
            if all(isinstance(value, str) for value in identity):
                typed_identity = (str(identity[0]), str(identity[1]), str(identity[2]))
                if typed_identity in seen:
                    errors.append("setup attestation must not duplicate setup checks")
                seen.add(typed_identity)
    if isinstance(attestations, list) and payload.get("attestation_count") != len(
        attestations
    ):
        errors.append("setup attestation attestation_count must match attestations")
    if isinstance(attestations, list) and payload.get(
        "setup_attestation_fingerprint_sha256"
    ) != _attestation_fingerprint([item for item in attestations if isinstance(item, dict)]):
        errors.append(
            "setup attestation setup_attestation_fingerprint_sha256 must match attestations"
        )
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    return errors


def _attestation_item_errors(item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(item) != ATTESTATION_FIELDS:
        errors.append("setup attestation item fields must match contract")
    for field in ("requirement_id", "category", "key", "source_handle", "evidence_ref"):
        value = item.get(field)
        if not isinstance(value, str) or not value:
            errors.append(f"setup attestation item {field} must be a non-empty string")
        elif not setup_validator._is_safe_binding_handle(value):
            errors.append(f"setup attestation item {field} must be a safe token handle")
    evidence_kind = item.get("evidence_kind")
    if evidence_kind not in ATTESTATION_EVIDENCE_KINDS:
        errors.append("setup attestation item evidence_kind must be allowlisted")
    return errors


def _attestation_source_errors(
    payload: dict[str, Any],
    *,
    setup_payload: dict[str, Any],
    setup_state_path: Path,
) -> list[str]:
    errors: list[str] = []
    expected = {
        "setup_state_sha256": _sha256_file(setup_state_path),
        "setup_state_schema_version": setup_payload.get("schema_version"),
        "setup_state_fingerprint_sha256": setup_payload.get(
            "setup_state_fingerprint_sha256"
        ),
    }
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            errors.append(f"setup attestation {field} must match setup state source")
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup attestation privacy must be an object"]
    errors: list[str] = []
    if set(value) != ATTESTATION_PRIVACY_FIELDS:
        errors.append("setup attestation privacy fields must match contract")
    for field in ATTESTATION_PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup attestation privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        return ["setup attestation errors must be a string list"]
    result: list[str] = []
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    if error_codes != expected_codes:
        result.append("setup attestation error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("setup attestation error_code_counts must match errors")
    return result


def _attestation_fingerprint(attestations: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        attestations,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_ATTESTATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "source setup state failed validation" in error:
        return "completion_audit_setup_attestation_source_invalid"
    if "spec must be" in error:
        return "completion_audit_setup_attestation_spec_invalid"
    if "source_handle must match a binding token" in error:
        return "completion_audit_setup_attestation_unbound_handle"
    if "unknown setup check" in error:
        return "completion_audit_setup_attestation_unknown_check"
    if "duplicate setup checks" in error:
        return "completion_audit_setup_attestation_duplicate_check"
    if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
        return "completion_audit_setup_attestation_privacy_invalid"
    if "must match setup state source" in error:
        return "completion_audit_setup_attestation_source_mismatch"
    if "safe token handle" in error:
        return "completion_audit_setup_attestation_unsafe_token"
    if "evidence_kind" in error:
        return "completion_audit_setup_attestation_evidence_kind_invalid"
    if error == ATTESTATION_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_attestation_output_path_directory"
    if error == ATTESTATION_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_output_path_symlink"
    if error == ATTESTATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_output_path_parent_symlink"
    return "completion_audit_setup_attestation_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
