#!/usr/bin/env python3
"""Generate a privacy-safe setup-handle plan from completion-audit setup state."""

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
import validate_completion_audit_setup_state as setup_validator  # noqa: E402


SETUP_HANDLE_PLAN_SCHEMA_VERSION = "wiii.completion_audit_setup_handle_plan.v1"
PLAN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit setup handle plan output path must not be a directory"
)
PLAN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit setup handle plan output path must not be a symlink"
)
PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit setup handle plan output path parent must not be a symlink"
)


@dataclass(frozen=True)
class SetupHandlePlanCheck:
    category: str
    key: str
    binding_tokens: list[str]
    present: bool
    source_handle: str
    recommended_handle_specs: list[str]
    recommended_evidence_kinds: list[str]
    recommended_attestation_specs: list[str]


@dataclass(frozen=True)
class SetupHandlePlanItem:
    requirement_id: str
    title: str
    setup_status: str
    dispatch_ready: bool
    setup_checks: list[SetupHandlePlanCheck]


@dataclass(frozen=True)
class CompletionAuditSetupHandlePlan:
    schema_version: str
    ok: bool
    setup_state_path: str
    setup_state_sha256: str
    setup_state_schema_version: str
    setup_state_fingerprint_sha256: str
    setup_handle_plan_fingerprint_sha256: str
    requirement_count: int
    ready_requirement_count: int
    blocked_requirement_count: int
    ready_setup_check_count: int
    pending_setup_check_count: int
    plan_items: list[SetupHandlePlanItem]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_setup_handle_plan(
    setup_state_path: Path,
    *,
    launch_pack_path: Path | None = None,
) -> CompletionAuditSetupHandlePlan:
    validation = setup_validator.validate_setup_state(
        setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not validation.ok:
        raise ValueError(
            "completion audit setup handle plan setup state failed validation: "
            + "; ".join(validation.errors)
        )
    setup_payload = load_strict_json_file(setup_state_path)
    if not isinstance(setup_payload, dict):
        raise ValueError("completion audit setup state root must be an object")

    plan_items = [
        _plan_item(requirement)
        for requirement in setup_payload.get("requirements", [])
        if isinstance(requirement, dict)
    ]
    plan_dicts = [asdict(item) for item in plan_items]
    ready_checks = 0
    pending_checks = 0
    for item in plan_dicts:
        for check in item["setup_checks"]:
            if check["present"]:
                ready_checks += 1
            else:
                pending_checks += 1
    errors: list[str] = []
    return CompletionAuditSetupHandlePlan(
        schema_version=SETUP_HANDLE_PLAN_SCHEMA_VERSION,
        ok=True,
        setup_state_path=str(setup_state_path),
        setup_state_sha256=_sha256_file(setup_state_path),
        setup_state_schema_version=str(setup_payload.get("schema_version") or ""),
        setup_state_fingerprint_sha256=str(
            setup_payload.get("setup_state_fingerprint_sha256") or ""
        ),
        setup_handle_plan_fingerprint_sha256=_setup_handle_plan_fingerprint(
            plan_dicts
        ),
        requirement_count=len(plan_items),
        ready_requirement_count=int(setup_payload.get("ready_requirement_count") or 0),
        blocked_requirement_count=int(
            setup_payload.get("blocked_requirement_count") or 0
        ),
        ready_setup_check_count=ready_checks,
        pending_setup_check_count=pending_checks,
        plan_items=plan_items,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_identifiers_included": False,
            "raw_payload_included": False,
        },
        errors=errors,
    )


def _plan_item(requirement: dict[str, Any]) -> SetupHandlePlanItem:
    requirement_id = _string(requirement.get("requirement_id"))
    return SetupHandlePlanItem(
        requirement_id=requirement_id,
        title=_string(requirement.get("title")),
        setup_status=_string(requirement.get("setup_status")),
        dispatch_ready=bool(requirement.get("dispatch_ready")),
        setup_checks=[
            _plan_check(requirement_id, check)
            for check in requirement.get("setup_checks", [])
            if isinstance(check, dict)
        ],
    )


def _plan_check(requirement_id: str, check: dict[str, Any]) -> SetupHandlePlanCheck:
    category = _string(check.get("category"))
    key = _string(check.get("key"))
    tokens = _string_list(check.get("binding_tokens"))
    present = check.get("present") is True
    evidence_kind = _recommended_evidence_kind(requirement_id, category, key)
    return SetupHandlePlanCheck(
        category=category,
        key=key,
        binding_tokens=tokens,
        present=present,
        source_handle=_string(check.get("source_handle")),
        recommended_handle_specs=(
            [] if present else [f"{requirement_id}:{category}:{key}={token}" for token in tokens]
        ),
        recommended_evidence_kinds=[] if present else [evidence_kind],
        recommended_attestation_specs=(
            []
            if present
            else [
                (
                    f"{requirement_id}:{category}:{key}={token}"
                    f"@{evidence_kind}:{token}"
                )
                for token in tokens
            ]
        ),
    )


def _recommended_evidence_kind(requirement_id: str, category: str, key: str) -> str:
    if category == "workflow_inputs_required":
        return "workflow_input_bound"
    if category == "environment_flags_required":
        return "environment_flag_bound"
    if category == "credential_slots_required":
        if (
            requirement_id == "autonomy-proactive-channel"
            and key == "selected_channel_credential"
        ):
            return "runtime_channel_credential_validated"
        return "github_secret_present"
    if category == "external_setup_required":
        if (
            requirement_id == "autonomy-proactive-channel"
            and key == "selected_channel_enabled"
        ):
            return "runtime_channel_enabled"
        return {
            "approved_recipient": "operator_approved_recipient",
            "staging_or_live_backend": "backend_health_checked",
            "connected_provider_account": "provider_account_connected",
            "readonly_action_schema": "readonly_schema_validated",
            "execution_gateway_scope_policy": "execution_policy_validated",
        }.get(key, "operator_approved_recipient")
    return "operator_approved_recipient"


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(PLAN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(PLAN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.is_symlink():
            raise ValueError(PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a privacy-safe setup-handle plan from a validated "
            "completion-audit setup state."
        ),
    )
    parser.add_argument("setup_state", type=Path)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        plan = generate_completion_audit_setup_handle_plan(
            args.setup_state,
            launch_pack_path=args.launch_pack,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True))
        return 1
    rendered = json.dumps(plan.to_dict(), indent=2, sort_keys=True)
    if args.out:
        safe_write_report_text(args.out, rendered.rstrip("\n") + "\n")
    else:
        print(rendered)
    return 0


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": SETUP_HANDLE_PLAN_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def _setup_handle_plan_fingerprint(plan_items: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        plan_items,
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


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "setup state failed validation" in error:
        return "completion_audit_setup_handle_plan_setup_state_invalid"
    if error == PLAN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_setup_handle_plan_output_path_directory"
    if error == PLAN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_setup_handle_plan_output_path_symlink"
    if error == PLAN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_setup_handle_plan_output_path_parent_symlink"
    return "completion_audit_setup_handle_plan_generation_failed"


if __name__ == "__main__":
    raise SystemExit(main())
