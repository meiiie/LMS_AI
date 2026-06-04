#!/usr/bin/env python3
"""Validate completion-audit setup-handle plan artifacts."""

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

from generate_completion_audit_setup_handle_plan import (  # noqa: E402
    SETUP_HANDLE_PLAN_SCHEMA_VERSION,
    _setup_handle_plan_fingerprint,
    generate_completion_audit_setup_handle_plan,
)
from strict_json import load_strict_json_file  # noqa: E402


SETUP_HANDLE_PLAN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_handle_plan_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_state_path",
    "setup_state_sha256",
    "setup_state_schema_version",
    "setup_state_fingerprint_sha256",
    "setup_handle_plan_fingerprint_sha256",
    "requirement_count",
    "ready_requirement_count",
    "blocked_requirement_count",
    "ready_setup_check_count",
    "pending_setup_check_count",
    "plan_items",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
PLAN_ITEM_FIELDS = {
    "requirement_id",
    "title",
    "setup_status",
    "dispatch_ready",
    "setup_checks",
}
CHECK_FIELDS = {
    "category",
    "key",
    "binding_tokens",
    "present",
    "source_handle",
    "recommended_handle_specs",
    "recommended_evidence_kinds",
    "recommended_attestation_specs",
}
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
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}


@dataclass(frozen=True)
class SetupHandlePlanValidationResult:
    validation_schema_version: str
    setup_handle_plan_path: str
    setup_state_path: str | None
    launch_pack_path: str | None
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


def validate_setup_handle_plan(
    setup_handle_plan_path: Path,
    *,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> SetupHandlePlanValidationResult:
    errors: list[str] = []
    payload = _load_payload(setup_handle_plan_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if setup_state_path is not None:
            errors.extend(
                _setup_state_source_errors(
                    payload,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
    return SetupHandlePlanValidationResult(
        validation_schema_version=SETUP_HANDLE_PLAN_VALIDATION_SCHEMA_VERSION,
        setup_handle_plan_path=str(setup_handle_plan_path),
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append("completion audit setup handle plan path must be a regular file")
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"completion audit setup handle plan JSON is invalid: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup handle plan root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append("setup handle plan missing required field(s): " + ", ".join(missing))
    if extra:
        errors.append("setup handle plan has unsupported field(s): " + ", ".join(extra))
    if payload.get("schema_version") != SETUP_HANDLE_PLAN_SCHEMA_VERSION:
        errors.append(
            f"setup handle plan schema_version must be {SETUP_HANDLE_PLAN_SCHEMA_VERSION!r}"
        )
    for field in (
        "setup_state_path",
        "setup_state_schema_version",
        "setup_state_fingerprint_sha256",
        "setup_handle_plan_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"setup handle plan {field} must be a non-empty string")
    for field in (
        "setup_state_sha256",
        "setup_state_fingerprint_sha256",
        "setup_handle_plan_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"setup handle plan {field} must be a SHA-256 hex string")
    if payload.get("ok") is not True:
        errors.append("setup handle plan ok must be true")
    for field in (
        "requirement_count",
        "ready_requirement_count",
        "blocked_requirement_count",
        "ready_setup_check_count",
        "pending_setup_check_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"setup handle plan {field} must be a non-negative integer")
    plan_errors, plan_items = _plan_item_errors(payload.get("plan_items"))
    errors.extend(plan_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not plan_errors:
        errors.extend(_summary_errors(payload, plan_items))
    return errors


def _plan_item_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup handle plan plan_items must be a non-empty list"], items
    for item in value:
        if not isinstance(item, dict):
            errors.append("setup handle plan item entries must be objects")
            continue
        items.append(item)
        if set(item) != PLAN_ITEM_FIELDS:
            errors.append("setup handle plan item fields must match contract")
        for field in ("requirement_id", "title", "setup_status"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"setup handle plan item {field} must be a non-empty string")
        if item.get("setup_status") not in {"pending", "ready"}:
            errors.append("setup handle plan item setup_status must be pending or ready")
        if not isinstance(item.get("dispatch_ready"), bool):
            errors.append("setup handle plan item dispatch_ready must be a boolean")
        check_errors, checks = _check_errors(item.get("setup_checks"))
        errors.extend(check_errors)
        if not check_errors:
            ready = all(check.get("present") is True for check in checks)
            if item.get("dispatch_ready") != ready:
                errors.append("setup handle plan item dispatch_ready must match checks")
            expected_status = "ready" if ready else "pending"
            if item.get("setup_status") != expected_status:
                errors.append("setup handle plan item setup_status must match checks")
    return errors, items


def _check_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup handle plan setup_checks must be a non-empty list"], checks
    for check in value:
        if not isinstance(check, dict):
            errors.append("setup handle plan check entries must be objects")
            continue
        checks.append(check)
        if set(check) != CHECK_FIELDS:
            errors.append("setup handle plan check fields must match contract")
        for field in ("category", "key"):
            if not isinstance(check.get(field), str) or not check.get(field):
                errors.append(f"setup handle plan check {field} must be a non-empty string")
        tokens = check.get("binding_tokens")
        if not _is_string_list(tokens) or not tokens:
            errors.append("setup handle plan check binding_tokens must be a non-empty string list")
        specs = check.get("recommended_handle_specs")
        if not _is_string_list(specs):
            errors.append("setup handle plan check recommended_handle_specs must be a string list")
        evidence_kinds = check.get("recommended_evidence_kinds")
        if not _is_string_list(evidence_kinds):
            errors.append("setup handle plan check recommended_evidence_kinds must be a string list")
        elif any(kind not in ATTESTATION_EVIDENCE_KINDS for kind in evidence_kinds):
            errors.append(
                "setup handle plan check recommended_evidence_kinds must be allowlisted"
            )
        attestation_specs = check.get("recommended_attestation_specs")
        if not _is_string_list(attestation_specs):
            errors.append("setup handle plan check recommended_attestation_specs must be a string list")
        if not isinstance(check.get("present"), bool):
            errors.append("setup handle plan check present must be a boolean")
        source_handle = check.get("source_handle")
        if not isinstance(source_handle, str):
            errors.append("setup handle plan check source_handle must be a string")
        if check.get("present") is True:
            if specs:
                errors.append(
                    "setup handle plan ready check recommended_handle_specs must be empty"
                )
            if evidence_kinds:
                errors.append(
                    "setup handle plan ready check recommended_evidence_kinds must be empty"
                )
            if attestation_specs:
                errors.append(
                    "setup handle plan ready check recommended_attestation_specs must be empty"
                )
        elif _is_string_list(tokens) and _is_string_list(specs):
            if not _is_string_list(evidence_kinds) or len(evidence_kinds) != 1:
                errors.append(
                    "setup handle plan pending check must have exactly one recommended evidence kind"
                )
            for token in tokens:
                suffix = f"={token}"
                if not any(spec.endswith(suffix) for spec in specs):
                    errors.append(
                        "setup handle plan pending check must include a handle spec for each binding token"
                    )
                    break
            if (
                _is_string_list(evidence_kinds)
                and _is_string_list(attestation_specs)
                and evidence_kinds
            ):
                errors.extend(
                    _attestation_spec_errors(
                        check,
                        tokens=tokens,
                        evidence_kind=evidence_kinds[0],
                        attestation_specs=attestation_specs,
                    )
                )
    return errors, checks


def _attestation_spec_errors(
    check: dict[str, Any],
    *,
    tokens: list[str],
    evidence_kind: str,
    attestation_specs: list[str],
) -> list[str]:
    errors: list[str] = []
    category = check.get("category")
    key = check.get("key")
    if not isinstance(category, str) or not isinstance(key, str):
        return errors
    for token in tokens:
        expected_suffix = f"{category}:{key}={token}@{evidence_kind}:{token}"
        if not any(spec.endswith(expected_suffix) for spec in attestation_specs):
            errors.append(
                "setup handle plan pending check must include an attestation spec for each binding token"
            )
            break
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup handle plan privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("setup handle plan privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup handle plan privacy.{field} must be false")
    return errors


def _summary_errors(
    payload: dict[str, Any],
    plan_items: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    ready_requirements = sum(1 for item in plan_items if item.get("dispatch_ready"))
    ready_checks = 0
    pending_checks = 0
    for item in plan_items:
        for check in item.get("setup_checks", []):
            if check.get("present") is True:
                ready_checks += 1
            else:
                pending_checks += 1
    if payload.get("requirement_count") != len(plan_items):
        errors.append("setup handle plan requirement_count must match plan_items")
    if payload.get("ready_requirement_count") != ready_requirements:
        errors.append("setup handle plan ready_requirement_count must match plan_items")
    if payload.get("blocked_requirement_count") != len(plan_items) - ready_requirements:
        errors.append("setup handle plan blocked_requirement_count must match plan_items")
    if payload.get("ready_setup_check_count") != ready_checks:
        errors.append("setup handle plan ready_setup_check_count must match plan_items")
    if payload.get("pending_setup_check_count") != pending_checks:
        errors.append("setup handle plan pending_setup_check_count must match plan_items")
    if payload.get("setup_handle_plan_fingerprint_sha256") != _setup_handle_plan_fingerprint(
        plan_items
    ):
        errors.append(
            "setup handle plan setup_handle_plan_fingerprint_sha256 must match plan_items"
        )
    return errors


def _setup_state_source_errors(
    payload: dict[str, Any],
    *,
    setup_state_path: Path,
    launch_pack_path: Path | None,
) -> list[str]:
    expected = generate_completion_audit_setup_handle_plan(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    errors: list[str] = []
    for field in (
        "setup_state_sha256",
        "setup_state_schema_version",
        "setup_state_fingerprint_sha256",
        "setup_handle_plan_fingerprint_sha256",
        "requirement_count",
        "ready_requirement_count",
        "blocked_requirement_count",
        "ready_setup_check_count",
        "pending_setup_check_count",
    ):
        if payload.get(field) != expected.get(field):
            errors.append(f"setup handle plan source mismatch: {field} must match setup state")
            return errors
    if payload.get("plan_items") != expected.get("plan_items"):
        errors.append("setup handle plan source mismatch: plan_items must match setup state")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if not _is_string_list(errors):
        return []
    expected_codes = _error_codes(errors)
    expected_counts = _error_code_counts(errors)
    result: list[str] = []
    if _is_string_list(error_codes) and error_codes != expected_codes:
        result.append("setup handle plan error_codes must match errors")
    if error_code_counts != expected_counts:
        result.append("setup handle plan error_code_counts must match errors")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit setup-handle plan artifact.",
    )
    parser.add_argument("setup_handle_plan", type=Path)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_handle_plan(
        args.setup_handle_plan,
        setup_state_path=args.setup_state,
        launch_pack_path=args.launch_pack,
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
        print("Wiii Completion Audit Setup Handle Plan Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Handle Plan Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and FINGERPRINT_RE.match(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit setup handle plan path must be a regular file":
        return "completion_audit_setup_handle_plan_path_invalid"
    if error.startswith("completion audit setup handle plan JSON is invalid"):
        return "completion_audit_setup_handle_plan_json_invalid"
    if error == "completion audit setup handle plan root must be an object":
        return "completion_audit_setup_handle_plan_root_invalid"
    if "source mismatch" in error:
        return "completion_audit_setup_handle_plan_source_mismatch"
    if error.startswith("setup handle plan missing required field"):
        return "completion_audit_setup_handle_plan_missing_required_fields"
    if error.startswith("setup handle plan has unsupported field"):
        return "completion_audit_setup_handle_plan_unsupported_fields"
    if "schema_version" in error:
        return "completion_audit_setup_handle_plan_schema_mismatch"
    if "SHA-256" in error or "fingerprint" in error:
        return "completion_audit_setup_handle_plan_fingerprint_invalid"
    if "privacy" in error:
        return "completion_audit_setup_handle_plan_privacy_invalid"
    if "recommended_handle_specs" in error or "setup_checks" in error or "check" in error:
        return "completion_audit_setup_handle_plan_check_invalid"
    if "plan_items" in error or "item" in error or "requirement" in error:
        return "completion_audit_setup_handle_plan_item_invalid"
    if "non-negative integer" in error:
        return "completion_audit_setup_handle_plan_count_invalid"
    if "error_codes" in error or "error_code_counts" in error:
        return "completion_audit_setup_handle_plan_error_summary_invalid"
    return "completion_audit_setup_handle_plan_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
