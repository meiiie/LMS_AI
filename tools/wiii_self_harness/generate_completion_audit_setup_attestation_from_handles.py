#!/usr/bin/env python3
"""Generate setup attestations from privacy-safe setup handle evidence."""

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

import generate_completion_audit_setup_attestation as attestation_generator  # noqa: E402
from generate_completion_audit_setup_attestation import (  # noqa: E402
    ATTESTATION_EVIDENCE_KINDS,
    setup_handle_patch_from_attestation,
)
from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_handle_plan as plan_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_handle_evidence.v1"
)
HANDLE_EVIDENCE_TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_handle_plan_sha256",
    "setup_handle_plan_schema_version",
    "setup_handle_plan_fingerprint_sha256",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "handle_count",
    "handles",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
HANDLE_EVIDENCE_FIELDS = {
    "requirement_id",
    "category",
    "key",
    "source_handle",
    "evidence_kind",
    "evidence_ref",
}
HANDLE_EVIDENCE_PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}


def generate_completion_audit_setup_attestation_from_handles(
    setup_handle_plan_path: Path,
    handle_evidence_path: Path,
    *,
    setup_state_path: Path,
    launch_pack_path: Path | None = None,
) -> dict[str, Any]:
    plan_validation = plan_validator.validate_setup_handle_plan(
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not plan_validation.ok:
        raise ValueError(
            "completion audit setup handle evidence plan failed validation: "
            + "; ".join(plan_validation.errors)
        )
    plan_payload = load_strict_json_file(setup_handle_plan_path)
    evidence_payload = load_strict_json_file(handle_evidence_path)
    if not isinstance(plan_payload, dict):
        raise ValueError("completion audit setup handle plan root must be an object")
    if not isinstance(evidence_payload, dict):
        raise ValueError("completion audit setup handle evidence root must be an object")

    errors = _handle_evidence_errors(
        evidence_payload,
        plan_payload=plan_payload,
        setup_handle_plan_path=setup_handle_plan_path,
    )
    if errors:
        raise ValueError(
            "completion audit setup handle evidence failed validation: "
            + "; ".join(errors)
        )
    attest_specs = _attest_specs_from_handle_evidence(
        evidence_payload,
        plan_payload=plan_payload,
    )
    return attestation_generator.generate_completion_audit_setup_attestation(
        setup_state_path,
        attest_specs,
        launch_pack_path=launch_pack_path,
    )


def _handle_evidence_errors(
    payload: dict[str, Any],
    *,
    plan_payload: dict[str, Any],
    setup_handle_plan_path: Path,
) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(HANDLE_EVIDENCE_TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - HANDLE_EVIDENCE_TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "setup handle evidence missing required field(s): " + ", ".join(missing)
        )
    if extra:
        errors.append(
            "setup handle evidence has unsupported field(s): " + ", ".join(extra)
        )
    if payload.get("schema_version") != SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION:
        errors.append(
            "setup handle evidence schema_version must be "
            f"{SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION!r}"
        )
    if payload.get("ok") is not True:
        errors.append("setup handle evidence ok must be true")
    source_expected = {
        "setup_handle_plan_sha256": attestation_generator._sha256_file(
            setup_handle_plan_path
        ),
        "setup_handle_plan_schema_version": plan_payload.get("schema_version"),
        "setup_handle_plan_fingerprint_sha256": plan_payload.get(
            "setup_handle_plan_fingerprint_sha256"
        ),
        "setup_state_sha256": plan_payload.get("setup_state_sha256"),
        "setup_state_schema_version": plan_payload.get("setup_state_schema_version"),
        "setup_state_fingerprint_sha256": plan_payload.get(
            "setup_state_fingerprint_sha256"
        ),
    }
    for field, expected in source_expected.items():
        if payload.get(field) != expected:
            errors.append(f"setup handle evidence {field} must match source plan")
    for field in (
        "setup_handle_plan_sha256",
        "setup_handle_plan_fingerprint_sha256",
        "setup_state_sha256",
        "setup_state_fingerprint_sha256",
    ):
        if not setup_validator._is_fingerprint(payload.get(field)):
            errors.append(f"setup handle evidence {field} must be a SHA-256 hex string")
    handle_errors, handles = _handle_item_errors(payload.get("handles"))
    errors.extend(handle_errors)
    if isinstance(payload.get("handle_count"), int) and not isinstance(
        payload.get("handle_count"), bool
    ):
        if payload["handle_count"] != len(handles):
            errors.append("setup handle evidence handle_count must match handles")
    else:
        errors.append("setup handle evidence handle_count must be an integer")
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not handle_errors:
        errors.extend(_handle_binding_errors(handles, plan_payload=plan_payload))
    return errors


def _handle_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    handles: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup handle evidence handles must be a non-empty list"], handles
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            errors.append("setup handle evidence entries must be objects")
            continue
        handles.append(item)
        if set(item) != HANDLE_EVIDENCE_FIELDS:
            errors.append("setup handle evidence item fields must match contract")
        for field in (
            "requirement_id",
            "category",
            "key",
            "source_handle",
            "evidence_ref",
        ):
            value = item.get(field)
            if not isinstance(value, str) or not value:
                errors.append(
                    f"setup handle evidence item {field} must be a non-empty string"
                )
            elif not setup_validator._is_safe_binding_handle(value):
                errors.append(f"setup handle evidence item {field} must be safe")
        if item.get("evidence_kind") not in ATTESTATION_EVIDENCE_KINDS:
            errors.append("setup handle evidence item evidence_kind must be allowlisted")
        identity = (item.get("requirement_id"), item.get("category"), item.get("key"))
        if all(isinstance(part, str) for part in identity):
            typed_identity = (str(identity[0]), str(identity[1]), str(identity[2]))
            if typed_identity in seen:
                errors.append("setup handle evidence must not duplicate setup checks")
            seen.add(typed_identity)
    return errors, handles


def _handle_binding_errors(
    handles: list[dict[str, Any]],
    *,
    plan_payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    index = _pending_check_index(plan_payload)
    for item in handles:
        identity = (
            item.get("requirement_id"),
            item.get("category"),
            item.get("key"),
        )
        if not all(isinstance(part, str) for part in identity):
            continue
        check = index.get((str(identity[0]), str(identity[1]), str(identity[2])))
        if check is None:
            errors.append("setup handle evidence references unknown pending setup check")
            continue
        source_handle = item.get("source_handle")
        if source_handle not in check.get("binding_tokens", []):
            errors.append(
                "setup handle evidence source_handle must match a binding token"
            )
        evidence_kind = item.get("evidence_kind")
        if evidence_kind not in check.get("recommended_evidence_kinds", []):
            errors.append(
                "setup handle evidence evidence_kind must match recommended kind"
            )
    return errors


def _pending_check_index(
    plan_payload: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in plan_payload.get("plan_items", []):
        if not isinstance(item, dict):
            continue
        requirement_id = item.get("requirement_id")
        checks = item.get("setup_checks")
        if not isinstance(requirement_id, str) or not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict) or check.get("present") is True:
                continue
            category = check.get("category")
            key = check.get("key")
            if isinstance(category, str) and isinstance(key, str):
                index[(requirement_id, category, key)] = check
    return index


def _attest_specs_from_handle_evidence(
    payload: dict[str, Any],
    *,
    plan_payload: dict[str, Any],
) -> list[str]:
    index = _pending_check_index(plan_payload)
    specs: list[str] = []
    for item in payload["handles"]:
        identity = (item["requirement_id"], item["category"], item["key"])
        if identity not in index:
            continue
        specs.append(
            f"{item['requirement_id']}:{item['category']}:{item['key']}="
            f"{item['source_handle']}@{item['evidence_kind']}:{item['evidence_ref']}"
        )
    return specs


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup handle evidence privacy must be an object"]
    errors: list[str] = []
    if set(value) != HANDLE_EVIDENCE_PRIVACY_FIELDS:
        errors.append("setup handle evidence privacy fields must match contract")
    for field in HANDLE_EVIDENCE_PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup handle evidence privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    if payload.get("errors") != []:
        return ["setup handle evidence errors must be empty"]
    if payload.get("error_codes") != []:
        return ["setup handle evidence error_codes must be empty"]
    if payload.get("error_code_counts") != {}:
        return ["setup handle evidence error_code_counts must be empty"]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a setup attestation from source-bound, privacy-safe setup "
            "handle evidence."
        )
    )
    parser.add_argument("setup_handle_plan", type=Path)
    parser.add_argument("handle_evidence", type=Path)
    parser.add_argument("--setup-state", type=Path, required=True)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--patch-out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        attestation_generator.validate_output_path(args.out)
        attestation_generator.validate_output_path(args.patch_out)
        attestation = generate_completion_audit_setup_attestation_from_handles(
            args.setup_handle_plan,
            args.handle_evidence,
            setup_state_path=args.setup_state,
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


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_HANDLE_EVIDENCE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "plan failed validation" in error:
        return "completion_audit_setup_handle_evidence_plan_invalid"
    if "root must be an object" in error:
        return "completion_audit_setup_handle_evidence_root_invalid"
    if "schema_version" in error:
        return "completion_audit_setup_handle_evidence_schema_mismatch"
    if "must match source plan" in error:
        return "completion_audit_setup_handle_evidence_source_mismatch"
    if "SHA-256" in error:
        return "completion_audit_setup_handle_evidence_fingerprint_invalid"
    if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
        return "completion_audit_setup_handle_evidence_privacy_invalid"
    if "must be safe" in error:
        return "completion_audit_setup_handle_evidence_unsafe_token"
    if "duplicate setup checks" in error:
        return "completion_audit_setup_handle_evidence_duplicate_check"
    if "unknown pending setup check" in error:
        return "completion_audit_setup_handle_evidence_unknown_check"
    if "binding token" in error:
        return "completion_audit_setup_handle_evidence_unbound_handle"
    if "evidence_kind" in error or "recommended kind" in error:
        return "completion_audit_setup_handle_evidence_kind_invalid"
    if "handle_count" in error:
        return "completion_audit_setup_handle_evidence_count_invalid"
    return "completion_audit_setup_handle_evidence_invalid"


if __name__ == "__main__":
    raise SystemExit(main())
