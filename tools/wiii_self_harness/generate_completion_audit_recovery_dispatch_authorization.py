#!/usr/bin/env python3
"""Authorize recovery runtime dispatch from progressed queue evidence."""

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
import run_completion_audit_recovery_queue as queue_runner  # noqa: E402
import validate_completion_audit_dispatch_gate as dispatch_gate_validator  # noqa: E402
import validate_completion_audit_recovery_plan as plan_validator  # noqa: E402
import validate_completion_audit_recovery_queue_progress as progress_validator  # noqa: E402


RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_dispatch_authorization.v1"
)
RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery dispatch authorization output path must not be a directory"
)
RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery dispatch authorization output path must not be a symlink"
)
RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery dispatch authorization output path parent must not be a symlink"
)
RUNTIME_EXECUTION_MODE = "workflow_dispatch_or_local_probe"
AUTHORIZATION_STATES = {
    "invalid",
    "empty",
    "blocked_by_queue",
    "no_runtime_dispatch_ready",
    "blocked_by_recovery_contract",
    "blocked_by_dispatch_gate",
    "authorized",
}
DISPATCH_GATE_STATUSES = {
    "not_supplied",
    "matched_ready",
    "matched_blocked",
    "not_matched",
}


@dataclass(frozen=True)
class RecoveryDispatchAuthorizationItem:
    item_id: str
    group_id: str
    requirement_id: str
    workflow: str
    probe: str
    expected_artifact: str
    recovery_status: str
    error_codes: list[str]
    live_env_flags: list[str]
    live_guard_tokens: list[str]
    dispatch_or_schedule_gate_tokens: list[str]
    artifact_tokens: list[str]
    preflight_required_next: list[str]
    recovery_contract_ready: bool
    dispatch_gate_status: str
    dispatch_gate_ready: bool
    authorization_ready: bool
    unlocked_live_command_specs: dict[str, Any]
    blocked_reasons: list[str]


@dataclass(frozen=True)
class RecoveryDispatchAuthorizationReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    recovery_queue_progress_path: str
    recovery_queue_progress_sha256: str
    recovery_queue_progress_schema_version: str
    queue_progress_fingerprint_sha256: str
    recovery_plan_path: str
    recovery_plan_sha256: str
    recovery_plan_schema_version: str
    recovery_plan_action_items_fingerprint_sha256: str
    recovery_plan_execution_groups_fingerprint_sha256: str
    dispatch_gate_path: str
    dispatch_gate_sha256: str
    dispatch_gate_schema_version: str
    dispatch_gate_fingerprint_sha256: str
    queue_state: str
    next_group_ids: list[str]
    authorized_group_ids: list[str]
    blocked_group_ids: list[str]
    dispatch_gate_enforced: bool
    live_command_specs_included: bool
    authorization_state: str
    autonomous_dispatch_allowed: bool
    candidate_group_count: int
    authorization_item_count: int
    ready_dispatch_item_count: int
    blocked_dispatch_item_count: int
    authorization_fingerprint_sha256: str
    dispatch_items: list[RecoveryDispatchAuthorizationItem]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_recovery_dispatch_authorization(
    recovery_queue_progress_path: Path,
    *,
    recovery_plan_path: Path,
    dispatch_gate_path: Path | None = None,
    source_recovery_queue_path: Path | None = None,
    work_order_status_path: Path | None = None,
    recovery_work_order_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> RecoveryDispatchAuthorizationReport:
    errors: list[str] = []
    progress_payload: dict[str, Any] = {}
    plan_payload: dict[str, Any] = {}
    dispatch_gate_payload: dict[str, Any] = {}

    progress_validation_kwargs: dict[str, Path | None] = {}
    if source_recovery_queue_path is not None or work_order_status_path is not None:
        progress_validation_kwargs = {
            "source_recovery_queue_path": source_recovery_queue_path,
            "recovery_plan_path": recovery_plan_path,
            "work_order_status_path": work_order_status_path,
            "recovery_work_order_path": recovery_work_order_path,
            "handoff_json_path": handoff_json_path,
            "setup_state_path": setup_state_path,
            "launch_pack_path": launch_pack_path,
        }
    progress_validation = progress_validator.validate_recovery_queue_progress(
        recovery_queue_progress_path,
        **progress_validation_kwargs,
    )
    if not progress_validation.ok:
        errors.append(
            "completion audit recovery dispatch authorization queue progress failed validation: "
            + "; ".join(progress_validation.errors)
        )
    else:
        loaded_progress = load_strict_json_file(recovery_queue_progress_path)
        if isinstance(loaded_progress, dict):
            progress_payload = loaded_progress
        else:
            errors.append(
                "completion audit recovery dispatch authorization queue progress root invalid"
            )

    plan_validation = plan_validator.validate_recovery_plan(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not plan_validation.ok:
        errors.append(
            "completion audit recovery dispatch authorization recovery plan failed validation: "
            + "; ".join(plan_validation.errors)
        )
    else:
        loaded_plan = load_strict_json_file(recovery_plan_path)
        if isinstance(loaded_plan, dict):
            plan_payload = loaded_plan
        else:
            errors.append(
                "completion audit recovery dispatch authorization recovery plan root invalid"
            )

    if dispatch_gate_path is not None:
        gate_validation_kwargs: dict[str, Path] = {}
        if launch_pack_path is not None and setup_state_path is not None:
            gate_validation_kwargs = {
                "launch_pack_path": launch_pack_path,
                "setup_state_path": setup_state_path,
            }
        gate_validation = dispatch_gate_validator.validate_dispatch_gate(
            dispatch_gate_path,
            **gate_validation_kwargs,
        )
        if not gate_validation.ok:
            errors.append(
                "completion audit recovery dispatch authorization dispatch gate failed validation: "
                + "; ".join(gate_validation.errors)
            )
        else:
            loaded_gate = load_strict_json_file(dispatch_gate_path)
            if isinstance(loaded_gate, dict):
                dispatch_gate_payload = loaded_gate
            else:
                errors.append(
                    "completion audit recovery dispatch authorization dispatch gate root invalid"
                )

    dispatch_items = _dispatch_items(
        progress_payload,
        plan_payload,
        dispatch_gate_payload,
        dispatch_gate_enforced=dispatch_gate_path is not None,
        errors=errors,
    )
    return _report(
        recovery_queue_progress_path,
        recovery_plan_path=recovery_plan_path,
        dispatch_gate_path=dispatch_gate_path,
        progress_payload=progress_payload,
        plan_payload=plan_payload,
        dispatch_gate_payload=dispatch_gate_payload,
        dispatch_items=dispatch_items,
        errors=errors,
    )


def _dispatch_items(
    progress_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    dispatch_gate_payload: dict[str, Any],
    *,
    dispatch_gate_enforced: bool,
    errors: list[str],
) -> list[RecoveryDispatchAuthorizationItem]:
    if progress_payload.get("queue_state") != "ready_for_autonomous_dispatch":
        return []
    ready_group_statuses = _ready_runtime_group_statuses(progress_payload)
    execution_groups = _execution_groups_by_id(plan_payload.get("execution_groups"), errors)
    action_items = _action_items_by_id(plan_payload.get("action_items"), errors)
    dispatch_gate_items = _dispatch_gate_items_by_requirement_id(
        dispatch_gate_payload.get("dispatch_items"),
        errors,
    )
    items: list[RecoveryDispatchAuthorizationItem] = []
    for group_status in ready_group_statuses:
        group_id = _string(group_status.get("group_id"))
        execution_group = execution_groups.get(group_id)
        if execution_group is None:
            errors.append(
                "completion audit recovery dispatch authorization ready group missing from recovery plan"
            )
            continue
        for item_id in _string_list(execution_group.get("item_ids")):
            action_item = action_items.get(item_id)
            if action_item is None:
                errors.append(
                    "completion audit recovery dispatch authorization ready item missing from recovery plan"
                )
                continue
            items.append(
                _dispatch_item(
                    group_id,
                    action_item,
                    dispatch_gate_items,
                    dispatch_gate_enforced=dispatch_gate_enforced,
                )
            )
    return items


def _dispatch_item(
    group_id: str,
    action_item: dict[str, Any],
    dispatch_gate_items: dict[str, dict[str, Any]],
    *,
    dispatch_gate_enforced: bool,
) -> RecoveryDispatchAuthorizationItem:
    blocked_reasons = _recovery_contract_blocked_reasons(action_item)
    requirement_id = _string(action_item.get("requirement_id"))
    gate_item = dispatch_gate_items.get(requirement_id)
    dispatch_gate_status = _dispatch_gate_status(
        gate_item,
        dispatch_gate_enforced=dispatch_gate_enforced,
    )
    if dispatch_gate_status == "matched_blocked":
        blocked_reasons.append("dispatch_gate_not_ready")
    elif dispatch_gate_status == "not_matched":
        blocked_reasons.append("dispatch_gate_item_not_matched")
    recovery_contract_ready = not _recovery_contract_blocked_reasons(action_item)
    dispatch_gate_ready = dispatch_gate_status == "matched_ready"
    authorization_ready = (
        recovery_contract_ready
        and dispatch_gate_status in {"not_supplied", "matched_ready"}
    )
    unlocked_live_command_specs = (
        _dict_field(gate_item.get("unlocked_live_command_specs"))
        if dispatch_gate_ready and isinstance(gate_item, dict)
        else {}
    )
    return RecoveryDispatchAuthorizationItem(
        item_id=_string(action_item.get("item_id")),
        group_id=group_id,
        requirement_id=requirement_id,
        workflow=_string(action_item.get("workflow")),
        probe=_string(action_item.get("probe")),
        expected_artifact=_string(action_item.get("artifact")),
        recovery_status=_string(action_item.get("status")),
        error_codes=_string_list(action_item.get("error_codes")),
        live_env_flags=_string_list(action_item.get("live_env_flags")),
        live_guard_tokens=_string_list(action_item.get("live_guard_tokens")),
        dispatch_or_schedule_gate_tokens=_string_list(
            action_item.get("dispatch_or_schedule_gate_tokens")
        ),
        artifact_tokens=_string_list(action_item.get("artifact_tokens")),
        preflight_required_next=_string_list(action_item.get("preflight_required_next")),
        recovery_contract_ready=recovery_contract_ready,
        dispatch_gate_status=dispatch_gate_status,
        dispatch_gate_ready=dispatch_gate_ready,
        authorization_ready=authorization_ready,
        unlocked_live_command_specs=unlocked_live_command_specs,
        blocked_reasons=sorted(set(blocked_reasons)),
    )


def _ready_runtime_group_statuses(
    progress_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    next_group_ids = set(_string_list(progress_payload.get("next_group_ids")))
    statuses = progress_payload.get("group_statuses")
    if not isinstance(statuses, list):
        return []
    return [
        status
        for status in statuses
        if isinstance(status, dict)
        and _string(status.get("group_id")) in next_group_ids
        and _string(status.get("execution_mode")) == RUNTIME_EXECUTION_MODE
        and status.get("status") == queue_runner.READY_STATUS
        and status.get("ready_for_autonomous_dispatch") is True
    ]


def _recovery_contract_blocked_reasons(action_item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _string(action_item.get("action_type")) != "workflow_probe_recovery":
        reasons.append("unsupported_action_type")
    for field, reason in (
        ("requirement_id", "missing_requirement_id"),
        ("workflow", "missing_workflow"),
        ("probe", "missing_probe"),
        ("artifact", "missing_expected_artifact"),
    ):
        if not _string(action_item.get(field)):
            reasons.append(reason)
    for field, reason in (
        ("live_env_flags", "missing_live_env_flags"),
        ("live_guard_tokens", "missing_live_guard_tokens"),
        (
            "dispatch_or_schedule_gate_tokens",
            "missing_dispatch_or_schedule_gate_tokens",
        ),
        ("artifact_tokens", "missing_artifact_tokens"),
        ("preflight_required_next", "missing_preflight_required_next"),
    ):
        if not _string_list(action_item.get(field)):
            reasons.append(reason)
    return reasons


def _dispatch_gate_status(
    gate_item: dict[str, Any] | None,
    *,
    dispatch_gate_enforced: bool,
) -> str:
    if not dispatch_gate_enforced:
        return "not_supplied"
    if gate_item is None:
        return "not_matched"
    if gate_item.get("dispatch_ready") is True:
        return "matched_ready"
    return "matched_blocked"


def _report(
    recovery_queue_progress_path: Path,
    *,
    recovery_plan_path: Path,
    dispatch_gate_path: Path | None,
    progress_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    dispatch_gate_payload: dict[str, Any],
    dispatch_items: list[RecoveryDispatchAuthorizationItem],
    errors: list[str],
) -> RecoveryDispatchAuthorizationReport:
    item_dicts = [asdict(item) for item in dispatch_items]
    next_group_ids = _string_list(progress_payload.get("next_group_ids"))
    candidate_group_ids = sorted({item.group_id for item in dispatch_items})
    authorized_group_ids = _authorized_group_ids(dispatch_items)
    blocked_group_ids = _blocked_group_ids(
        next_group_ids=next_group_ids,
        candidate_group_ids=candidate_group_ids,
        authorized_group_ids=authorized_group_ids,
    )
    authorization_state = _authorization_state(
        progress_payload,
        dispatch_items,
        errors,
        candidate_group_ids=candidate_group_ids,
    )
    live_command_specs_included = any(
        bool(item.unlocked_live_command_specs) for item in dispatch_items
    )
    return RecoveryDispatchAuthorizationReport(
        schema_version=RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION,
        ok=not errors,
        mode="dry_run",
        dry_run=True,
        recovery_queue_progress_path=str(recovery_queue_progress_path),
        recovery_queue_progress_sha256=_regular_file_sha(recovery_queue_progress_path),
        recovery_queue_progress_schema_version=_string(
            progress_payload.get("schema_version")
        ),
        queue_progress_fingerprint_sha256=_string(
            progress_payload.get("queue_progress_fingerprint_sha256")
        ),
        recovery_plan_path=str(recovery_plan_path),
        recovery_plan_sha256=_regular_file_sha(recovery_plan_path),
        recovery_plan_schema_version=_string(plan_payload.get("schema_version")),
        recovery_plan_action_items_fingerprint_sha256=_string(
            plan_payload.get("action_items_fingerprint_sha256")
        ),
        recovery_plan_execution_groups_fingerprint_sha256=_string(
            plan_payload.get("execution_groups_fingerprint_sha256")
        ),
        dispatch_gate_path=str(dispatch_gate_path) if dispatch_gate_path else "",
        dispatch_gate_sha256=_regular_file_sha(dispatch_gate_path),
        dispatch_gate_schema_version=_string(dispatch_gate_payload.get("schema_version")),
        dispatch_gate_fingerprint_sha256=_string(
            dispatch_gate_payload.get("dispatch_gate_fingerprint_sha256")
        ),
        queue_state=_string(progress_payload.get("queue_state")),
        next_group_ids=next_group_ids,
        authorized_group_ids=authorized_group_ids,
        blocked_group_ids=blocked_group_ids,
        dispatch_gate_enforced=dispatch_gate_path is not None,
        live_command_specs_included=live_command_specs_included,
        authorization_state=authorization_state,
        autonomous_dispatch_allowed=authorization_state == "authorized",
        candidate_group_count=len(candidate_group_ids),
        authorization_item_count=len(dispatch_items),
        ready_dispatch_item_count=sum(
            1 for item in dispatch_items if item.authorization_ready
        ),
        blocked_dispatch_item_count=sum(
            1 for item in dispatch_items if not item.authorization_ready
        ),
        authorization_fingerprint_sha256=_authorization_fingerprint(
            authorization_state=authorization_state,
            authorized_group_ids=authorized_group_ids,
            blocked_group_ids=blocked_group_ids,
            dispatch_gate_enforced=dispatch_gate_path is not None,
            live_command_specs_included=live_command_specs_included,
            dispatch_items=item_dicts,
        ),
        dispatch_items=dispatch_items,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _authorization_state(
    progress_payload: dict[str, Any],
    dispatch_items: list[RecoveryDispatchAuthorizationItem],
    errors: list[str],
    *,
    candidate_group_ids: list[str],
) -> str:
    if errors:
        return "invalid"
    group_statuses = progress_payload.get("group_statuses")
    if isinstance(group_statuses, list) and not group_statuses:
        return "empty"
    if progress_payload.get("queue_state") != "ready_for_autonomous_dispatch":
        return "blocked_by_queue"
    if not candidate_group_ids or not dispatch_items:
        return "no_runtime_dispatch_ready"
    if any(not item.recovery_contract_ready for item in dispatch_items):
        return "blocked_by_recovery_contract"
    if any(
        item.dispatch_gate_status in {"matched_blocked", "not_matched"}
        for item in dispatch_items
    ):
        return "blocked_by_dispatch_gate"
    if all(item.authorization_ready for item in dispatch_items):
        return "authorized"
    return "blocked_by_recovery_contract"


def _authorized_group_ids(
    dispatch_items: list[RecoveryDispatchAuthorizationItem],
) -> list[str]:
    group_ids = sorted({item.group_id for item in dispatch_items})
    return [
        group_id
        for group_id in group_ids
        if any(item.group_id == group_id for item in dispatch_items)
        and all(
            item.authorization_ready
            for item in dispatch_items
            if item.group_id == group_id
        )
    ]


def _blocked_group_ids(
    *,
    next_group_ids: list[str],
    candidate_group_ids: list[str],
    authorized_group_ids: list[str],
) -> list[str]:
    authorized = set(authorized_group_ids)
    candidate = set(candidate_group_ids)
    blocked = [
        group_id
        for group_id in next_group_ids
        if group_id not in authorized
    ]
    for group_id in candidate:
        if group_id not in authorized and group_id not in blocked:
            blocked.append(group_id)
    return blocked


def _execution_groups_by_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        if value is not None:
            errors.append(
                "completion audit recovery dispatch authorization execution_groups invalid"
            )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for group in value:
        if not isinstance(group, dict):
            errors.append(
                "completion audit recovery dispatch authorization execution_group invalid"
            )
            continue
        group_id = _string(group.get("group_id"))
        if group_id:
            result[group_id] = group
    return result


def _action_items_by_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        if value is not None:
            errors.append(
                "completion audit recovery dispatch authorization action_items invalid"
            )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            errors.append(
                "completion audit recovery dispatch authorization action_item invalid"
            )
            continue
        item_id = _string(item.get("item_id"))
        if item_id:
            result[item_id] = item
    return result


def _dispatch_gate_items_by_requirement_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, list):
        errors.append(
            "completion audit recovery dispatch authorization dispatch gate items invalid"
        )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            errors.append(
                "completion audit recovery dispatch authorization dispatch gate item invalid"
            )
            continue
        requirement_id = _string(item.get("requirement_id"))
        if requirement_id:
            result[requirement_id] = item
    return result


def _authorization_fingerprint(
    *,
    authorization_state: str,
    authorized_group_ids: list[str],
    blocked_group_ids: list[str],
    dispatch_gate_enforced: bool,
    live_command_specs_included: bool,
    dispatch_items: list[dict[str, Any]],
) -> str:
    encoded = json.dumps(
        {
            "authorization_state": authorization_state,
            "authorized_group_ids": authorized_group_ids,
            "blocked_group_ids": blocked_group_ids,
            "dispatch_gate_enforced": dispatch_gate_enforced,
            "dispatch_items": dispatch_items,
            "live_command_specs_included": live_command_specs_included,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _regular_file_sha(path: Path | None) -> str:
    if path is None or not path.is_file() or path.is_symlink():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_output_path(out_path: Path | None) -> None:
    if out_path is None:
        return
    if out_path.exists() and out_path.is_dir():
        raise ValueError(RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(
                RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR
            )


def _dict_field(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
    if error.startswith(
        "completion audit recovery dispatch authorization queue progress failed validation"
    ):
        return "completion_audit_recovery_dispatch_authorization_progress_invalid"
    if error.startswith(
        "completion audit recovery dispatch authorization recovery plan failed validation"
    ):
        return "completion_audit_recovery_dispatch_authorization_plan_invalid"
    if error.startswith(
        "completion audit recovery dispatch authorization dispatch gate failed validation"
    ):
        return "completion_audit_recovery_dispatch_authorization_dispatch_gate_invalid"
    if "root invalid" in error:
        return "completion_audit_recovery_dispatch_authorization_root_invalid"
    if "execution_group" in error:
        return "completion_audit_recovery_dispatch_authorization_execution_group_invalid"
    if "action_item" in error or "action_items" in error:
        return "completion_audit_recovery_dispatch_authorization_action_item_invalid"
    if "dispatch gate item" in error:
        return "completion_audit_recovery_dispatch_authorization_dispatch_gate_item_invalid"
    if error == RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_dispatch_authorization_output_path_directory"
    if error == RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_dispatch_authorization_output_path_symlink"
    if error == RECOVERY_DISPATCH_AUTHORIZATION_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return (
            "completion_audit_recovery_dispatch_authorization_output_path_parent_symlink"
        )
    return "completion_audit_recovery_dispatch_authorization_failed"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": RECOVERY_DISPATCH_AUTHORIZATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Authorize recovery runtime dispatch from a progressed completion-audit "
            "queue, without executing live commands."
        ),
    )
    parser.add_argument("recovery_queue_progress", type=Path)
    parser.add_argument("--recovery-plan", type=Path, required=True)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--source-recovery-queue", type=Path, default=None)
    parser.add_argument("--work-order-status", type=Path, default=None)
    parser.add_argument("--recovery-work-order", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        authorization = generate_completion_audit_recovery_dispatch_authorization(
            args.recovery_queue_progress,
            recovery_plan_path=args.recovery_plan,
            dispatch_gate_path=args.dispatch_gate,
            source_recovery_queue_path=args.source_recovery_queue,
            work_order_status_path=args.work_order_status,
            recovery_work_order_path=args.recovery_work_order,
            handoff_json_path=args.handoff_json,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
        )
        text = json.dumps(authorization.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 0 if authorization.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
