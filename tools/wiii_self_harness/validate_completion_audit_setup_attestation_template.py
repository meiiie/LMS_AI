#!/usr/bin/env python3
"""Validate completion-audit setup attestation template artifacts."""

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

from generate_completion_audit_setup_attestation_template import (  # noqa: E402
    SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION,
    _sha256_file,
    _template_fingerprint,
    generate_completion_audit_setup_attestation_template,
)
from strict_json import load_strict_json_file  # noqa: E402
from validate_completion_audit_setup_handle_plan import (  # noqa: E402
    SETUP_HANDLE_PLAN_SCHEMA_VERSION,
    validate_setup_handle_plan,
)
from validate_completion_audit_setup_state import _is_safe_binding_handle  # noqa: E402


SETUP_ATTESTATION_TEMPLATE_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_attestation_template_validation.v1"
)
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_LEVEL_FIELDS = {
    "schema_version",
    "ok",
    "setup_handle_plan_path",
    "setup_handle_plan_sha256",
    "setup_handle_plan_schema_version",
    "setup_handle_plan_fingerprint_sha256",
    "setup_attestation_template_fingerprint_sha256",
    "requirement_count",
    "pending_setup_check_count",
    "attestation_option_count",
    "requirements",
    "privacy",
    "errors",
    "error_codes",
    "error_code_counts",
}
REQUIREMENT_FIELDS = {
    "requirement_id",
    "title",
    "pending_setup_check_count",
    "setup_checks",
}
CHECK_FIELDS = {
    "category",
    "key",
    "evidence_kind",
    "source_handle_options",
    "attestation_spec_options",
    "selected_attestation_spec",
    "operator_evidence_ref_handle",
    "status",
}
PRIVACY_FIELDS = {
    "secret_values_included",
    "credential_values_included",
    "raw_identifiers_included",
    "raw_payload_included",
}
ALLOWED_EVIDENCE_KINDS = {
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


@dataclass(frozen=True)
class SetupAttestationTemplateValidationResult:
    validation_schema_version: str
    setup_attestation_template_path: str
    setup_handle_plan_path: str | None
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


def validate_setup_attestation_template(
    template_path: Path,
    *,
    setup_handle_plan_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> SetupAttestationTemplateValidationResult:
    errors: list[str] = []
    payload = _load_payload(template_path, errors)
    if payload is not None:
        errors.extend(_payload_errors(payload))
        if setup_handle_plan_path is not None:
            errors.extend(
                _plan_source_errors(
                    payload,
                    setup_handle_plan_path=setup_handle_plan_path,
                    setup_state_path=setup_state_path,
                    launch_pack_path=launch_pack_path,
                )
            )
    return SetupAttestationTemplateValidationResult(
        validation_schema_version=SETUP_ATTESTATION_TEMPLATE_VALIDATION_SCHEMA_VERSION,
        setup_attestation_template_path=str(template_path),
        setup_handle_plan_path=(
            str(setup_handle_plan_path) if setup_handle_plan_path else None
        ),
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        errors=errors,
    )


def _load_payload(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file() or path.is_symlink():
        errors.append(
            "completion audit setup attestation template path must be a regular file"
        )
        return None
    try:
        payload = load_strict_json_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(
            f"completion audit setup attestation template JSON is invalid: {exc}"
        )
        return None
    if not isinstance(payload, dict):
        errors.append("completion audit setup attestation template root must be an object")
        return None
    return payload


def _payload_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fields = set(payload)
    missing = sorted(TOP_LEVEL_FIELDS - fields)
    extra = sorted(fields - TOP_LEVEL_FIELDS)
    if missing:
        errors.append(
            "setup attestation template missing required field(s): "
            + ", ".join(missing)
        )
    if extra:
        errors.append(
            "setup attestation template has unsupported field(s): "
            + ", ".join(extra)
        )
    if payload.get("schema_version") != SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION:
        errors.append(
            "setup attestation template schema_version must be "
            f"{SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION!r}"
        )
    if payload.get("setup_handle_plan_schema_version") != SETUP_HANDLE_PLAN_SCHEMA_VERSION:
        errors.append(
            "setup attestation template setup_handle_plan_schema_version must be "
            f"{SETUP_HANDLE_PLAN_SCHEMA_VERSION!r}"
        )
    for field in (
        "setup_handle_plan_path",
        "setup_handle_plan_schema_version",
        "setup_handle_plan_fingerprint_sha256",
        "setup_attestation_template_fingerprint_sha256",
    ):
        if not isinstance(payload.get(field), str) or not payload.get(field):
            errors.append(f"setup attestation template {field} must be a non-empty string")
    for field in (
        "setup_handle_plan_sha256",
        "setup_handle_plan_fingerprint_sha256",
        "setup_attestation_template_fingerprint_sha256",
    ):
        if not _is_fingerprint(payload.get(field)):
            errors.append(f"setup attestation template {field} must be a SHA-256 hex string")
    if payload.get("ok") is not True:
        errors.append("setup attestation template ok must be true")
    for field in (
        "requirement_count",
        "pending_setup_check_count",
        "attestation_option_count",
    ):
        if not _is_non_negative_int(payload.get(field)):
            errors.append(f"setup attestation template {field} must be a non-negative integer")
    requirement_errors, requirements = _requirement_errors(payload.get("requirements"))
    errors.extend(requirement_errors)
    errors.extend(_privacy_errors(payload.get("privacy")))
    errors.extend(_error_summary_errors(payload))
    if not requirement_errors:
        errors.extend(_summary_errors(payload, requirements))
    return errors


def _requirement_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    requirements: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return ["setup attestation template requirements must be a list"], requirements
    for requirement in value:
        if not isinstance(requirement, dict):
            errors.append("setup attestation template requirement entries must be objects")
            continue
        requirements.append(requirement)
        if set(requirement) != REQUIREMENT_FIELDS:
            errors.append("setup attestation template requirement fields must match contract")
        for field in ("requirement_id", "title"):
            if not isinstance(requirement.get(field), str) or not requirement.get(field):
                errors.append(
                    f"setup attestation template requirement {field} must be a non-empty string"
                )
        if not _is_non_negative_int(requirement.get("pending_setup_check_count")):
            errors.append(
                "setup attestation template requirement pending_setup_check_count "
                "must be a non-negative integer"
            )
        check_errors, checks = _check_errors(requirement.get("setup_checks"))
        errors.extend(check_errors)
        if not check_errors and requirement.get("pending_setup_check_count") != len(checks):
            errors.append(
                "setup attestation template requirement pending_setup_check_count "
                "must match setup_checks"
            )
    return errors, requirements


def _check_errors(value: Any) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if not isinstance(value, list) or not value:
        return ["setup attestation template setup_checks must be a non-empty list"], checks
    for check in value:
        if not isinstance(check, dict):
            errors.append("setup attestation template check entries must be objects")
            continue
        checks.append(check)
        if set(check) != CHECK_FIELDS:
            errors.append("setup attestation template check fields must match contract")
        for field in ("category", "key", "evidence_kind", "status"):
            if not isinstance(check.get(field), str) or not check.get(field):
                errors.append(f"setup attestation template check {field} must be a non-empty string")
        if check.get("evidence_kind") not in ALLOWED_EVIDENCE_KINDS:
            errors.append("setup attestation template check evidence_kind must be allowlisted")
        if check.get("status") != "pending_operator_attestation":
            errors.append(
                "setup attestation template check status must be "
                "pending_operator_attestation"
            )
        if check.get("selected_attestation_spec") != "":
            errors.append(
                "setup attestation template selected_attestation_spec must be empty"
            )
        if check.get("operator_evidence_ref_handle") != "":
            errors.append(
                "setup attestation template operator_evidence_ref_handle must be empty"
            )
        for field in ("source_handle_options", "attestation_spec_options"):
            values = check.get(field)
            if not _is_string_list(values) or not values:
                errors.append(
                    f"setup attestation template check {field} must be a non-empty string list"
                )
            elif any(not _is_safe_template_token(item) for item in values):
                errors.append(
                    f"setup attestation template check {field} must contain only safe handles"
                )
    return errors, checks


def _plan_source_errors(
    payload: dict[str, Any],
    *,
    setup_handle_plan_path: Path,
    setup_state_path: Path | None,
    launch_pack_path: Path | None,
) -> list[str]:
    validation = validate_setup_handle_plan(
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not validation.ok:
        return [
            "completion audit setup attestation template setup-handle plan failed "
            "validation: "
            + "; ".join(validation.errors)
        ]
    plan_payload = load_strict_json_file(setup_handle_plan_path)
    if not isinstance(plan_payload, dict):
        return ["completion audit setup handle plan root must be an object"]
    expected = generate_completion_audit_setup_attestation_template(
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    ).to_dict()
    errors: list[str] = []
    for field, expected_value in {
        "setup_handle_plan_sha256": _sha256_file(setup_handle_plan_path),
        "setup_handle_plan_schema_version": plan_payload.get("schema_version"),
        "setup_handle_plan_fingerprint_sha256": plan_payload.get(
            "setup_handle_plan_fingerprint_sha256"
        ),
    }.items():
        if payload.get(field) != expected_value:
            errors.append(f"setup attestation template {field} must match source plan")
    for field in (
        "requirements",
        "requirement_count",
        "pending_setup_check_count",
        "attestation_option_count",
        "setup_attestation_template_fingerprint_sha256",
    ):
        if payload.get(field) != expected.get(field):
            errors.append(
                "setup attestation template content must match source plan"
            )
            break
    return errors


def _privacy_errors(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["setup attestation template privacy must be an object"]
    errors: list[str] = []
    if set(value) != PRIVACY_FIELDS:
        errors.append("setup attestation template privacy fields must match contract")
    for field in PRIVACY_FIELDS:
        if value.get(field) is not False:
            errors.append(f"setup attestation template privacy.{field} must be false")
    return errors


def _error_summary_errors(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    error_codes = payload.get("error_codes")
    error_code_counts = payload.get("error_code_counts")
    if errors != []:
        return ["setup attestation template errors must be empty"]
    if error_codes != []:
        return ["setup attestation template error_codes must be empty"]
    if error_code_counts != {}:
        return ["setup attestation template error_code_counts must be empty"]
    return []


def _summary_errors(
    payload: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    check_count = sum(
        len(item.get("setup_checks", []))
        for item in requirements
        if isinstance(item.get("setup_checks"), list)
    )
    option_count = sum(
        len(check.get("attestation_spec_options", []))
        for item in requirements
        for check in item.get("setup_checks", [])
        if isinstance(check, dict) and isinstance(check.get("attestation_spec_options"), list)
    )
    if payload.get("requirement_count") != len(requirements):
        errors.append("setup attestation template requirement_count must match requirements")
    if payload.get("pending_setup_check_count") != check_count:
        errors.append(
            "setup attestation template pending_setup_check_count must match checks"
        )
    if payload.get("attestation_option_count") != option_count:
        errors.append(
            "setup attestation template attestation_option_count must match options"
        )
    if payload.get("setup_attestation_template_fingerprint_sha256") != _template_fingerprint(
        requirements
    ):
        errors.append("setup attestation template fingerprint must match requirements")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a completion-audit setup attestation template.",
    )
    parser.add_argument("template", type=Path)
    parser.add_argument("--setup-handle-plan", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_setup_attestation_template(
        args.template,
        setup_handle_plan_path=args.setup_handle_plan,
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
        print("Wiii Completion Audit Setup Attestation Template Validation: PASS")
    else:
        print(
            "Wiii Completion Audit Setup Attestation Template Validation: FAIL\n"
            + "\n".join(f"- {error}" for error in result.errors),
            file=sys.stderr,
        )
    return 0 if result.ok else 1


def _is_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and bool(FINGERPRINT_RE.match(value))


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_safe_template_token(value: str) -> bool:
    if "@" in value:
        left, right = value.split("@", 1)
        if ":" not in right:
            return False
        evidence_kind, evidence_ref = right.split(":", 1)
        return (
            _is_safe_attestation_left(left)
            and evidence_kind in ALLOWED_EVIDENCE_KINDS
            and _is_safe_binding_handle(evidence_ref)
        )
    return _is_safe_binding_handle(value)


def _is_safe_attestation_left(value: str) -> bool:
    if "=" not in value:
        return False
    left, source_handle = value.split("=", 1)
    parts = left.split(":")
    return (
        len(parts) == 3
        and all(_is_safe_binding_handle(part) for part in parts)
        and _is_safe_binding_handle(source_handle)
    )


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error == "completion audit setup attestation template path must be a regular file":
        return "completion_audit_setup_attestation_template_path_invalid"
    if error.startswith("completion audit setup attestation template JSON is invalid"):
        return "completion_audit_setup_attestation_template_json_invalid"
    if error == "completion audit setup attestation template root must be an object":
        return "completion_audit_setup_attestation_template_root_invalid"
    if "setup-handle plan failed validation" in error:
        return "completion_audit_setup_attestation_template_plan_invalid"
    if "must match source plan" in error or "content must match source plan" in error:
        return "completion_audit_setup_attestation_template_source_mismatch"
    if "selected_attestation_spec must be empty" in error:
        return "completion_audit_setup_attestation_template_selected_spec_not_empty"
    if "operator_evidence_ref_handle must be empty" in error:
        return "completion_audit_setup_attestation_template_evidence_ref_not_empty"
    if "safe handles" in error:
        return "completion_audit_setup_attestation_template_unsafe_token"
    if "privacy" in error or "secret_values" in error or "raw_identifiers" in error:
        return "completion_audit_setup_attestation_template_privacy_invalid"
    if "fingerprint" in error or "SHA-256" in error:
        return "completion_audit_setup_attestation_template_fingerprint_invalid"
    if "setup attestation template" in error:
        return "completion_audit_setup_attestation_template_invalid"
    return "completion_audit_setup_attestation_template_validation_error"


if __name__ == "__main__":
    raise SystemExit(main())
