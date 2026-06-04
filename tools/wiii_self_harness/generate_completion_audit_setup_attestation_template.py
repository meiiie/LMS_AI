#!/usr/bin/env python3
"""Generate a pending operator attestation template from setup-handle plans."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_report_output import safe_write_report_text  # noqa: E402

from strict_json import load_strict_json_file  # noqa: E402
import validate_completion_audit_setup_handle_plan as plan_validator  # noqa: E402


SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION = (
    "wiii.completion_audit_setup_attestation_template.v1"
)
TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup attestation template output path must not be a directory"
)
TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup attestation template output path must not be a symlink"
)
TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup attestation template output path parent must not be a symlink"
)


@dataclass(frozen=True)
class AttestationTemplateCheck:
    category: str
    key: str
    evidence_kind: str
    source_handle_options: list[str]
    attestation_spec_options: list[str]
    selected_attestation_spec: str
    operator_evidence_ref_handle: str
    status: str


@dataclass(frozen=True)
class AttestationTemplateRequirement:
    requirement_id: str
    title: str
    pending_setup_check_count: int
    setup_checks: list[AttestationTemplateCheck]


@dataclass(frozen=True)
class CompletionAuditSetupAttestationTemplate:
    schema_version: str
    ok: bool
    setup_handle_plan_path: str
    setup_handle_plan_sha256: str
    setup_handle_plan_schema_version: str
    setup_handle_plan_fingerprint_sha256: str
    setup_attestation_template_fingerprint_sha256: str
    requirement_count: int
    pending_setup_check_count: int
    attestation_option_count: int
    requirements: list[AttestationTemplateRequirement]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_setup_attestation_template(
    setup_handle_plan_path: Path,
    *,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> CompletionAuditSetupAttestationTemplate:
    validation = plan_validator.validate_setup_handle_plan(
        setup_handle_plan_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not validation.ok:
        raise ValueError(
            "completion audit setup attestation template setup-handle plan failed "
            "validation: "
            + "; ".join(validation.errors)
        )
    payload = load_strict_json_file(setup_handle_plan_path)
    if not isinstance(payload, dict):
        raise ValueError("completion audit setup handle plan root must be an object")

    requirements = [
        requirement
        for requirement in (
            _template_requirement(item)
            for item in payload.get("plan_items", [])
            if isinstance(item, dict)
        )
        if requirement.pending_setup_check_count > 0
    ]
    requirement_dicts = [asdict(item) for item in requirements]
    pending_check_count = sum(
        item.pending_setup_check_count for item in requirements
    )
    option_count = sum(
        len(check.attestation_spec_options)
        for requirement in requirements
        for check in requirement.setup_checks
    )
    return CompletionAuditSetupAttestationTemplate(
        schema_version=SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION,
        ok=True,
        setup_handle_plan_path=str(setup_handle_plan_path),
        setup_handle_plan_sha256=_sha256_file(setup_handle_plan_path),
        setup_handle_plan_schema_version=str(payload.get("schema_version") or ""),
        setup_handle_plan_fingerprint_sha256=str(
            payload.get("setup_handle_plan_fingerprint_sha256") or ""
        ),
        setup_attestation_template_fingerprint_sha256=_template_fingerprint(
            requirement_dicts
        ),
        requirement_count=len(requirements),
        pending_setup_check_count=pending_check_count,
        attestation_option_count=option_count,
        requirements=requirements,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        errors=[],
    )


def _template_requirement(item: dict[str, Any]) -> AttestationTemplateRequirement:
    checks = [
        _template_check(check)
        for check in item.get("setup_checks", [])
        if isinstance(check, dict) and check.get("present") is not True
    ]
    return AttestationTemplateRequirement(
        requirement_id=_string(item.get("requirement_id")),
        title=_string(item.get("title")),
        pending_setup_check_count=len(checks),
        setup_checks=checks,
    )


def _template_check(check: dict[str, Any]) -> AttestationTemplateCheck:
    return AttestationTemplateCheck(
        category=_string(check.get("category")),
        key=_string(check.get("key")),
        evidence_kind=_first_string(check.get("recommended_evidence_kinds")),
        source_handle_options=_source_handle_options(check),
        attestation_spec_options=_string_list(
            check.get("recommended_attestation_specs")
        ),
        selected_attestation_spec="",
        operator_evidence_ref_handle="",
        status="pending_operator_attestation",
    )


def _source_handle_options(check: dict[str, Any]) -> list[str]:
    specs = _string_list(check.get("recommended_handle_specs"))
    result: list[str] = []
    for spec in specs:
        if "=" not in spec:
            continue
        handle = spec.split("=", 1)[1]
        if handle:
            result.append(handle)
    return result


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a privacy-safe pending setup attestation template from a "
            "validated completion-audit setup-handle plan."
        ),
    )
    parser.add_argument("setup_handle_plan", type=Path)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        template = generate_completion_audit_setup_attestation_template(
            args.setup_handle_plan,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(template.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _template_fingerprint(requirements: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        requirements,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _first_string(value: Any) -> str:
    strings = _string_list(value)
    return strings[0] if strings else ""


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_ATTESTATION_TEMPLATE_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _error_code(error: str) -> str:
    if "setup-handle plan failed validation" in error:
        return "completion_audit_setup_attestation_template_plan_invalid"
    if error == TEMPLATE_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_attestation_template_output_path_directory"
    if error == TEMPLATE_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_template_output_path_symlink"
    if error == TEMPLATE_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_attestation_template_output_path_parent_symlink"
    return "completion_audit_setup_attestation_template_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
