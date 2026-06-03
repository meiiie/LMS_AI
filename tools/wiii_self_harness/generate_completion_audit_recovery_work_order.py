#!/usr/bin/env python3
"""Generate a source-bound work order from a recovery queue."""

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

from generate_completion_audit_recovery_plan import (  # noqa: E402
    ACTION_ITEM_FIELDS,
    RECOVERY_PLAN_SCHEMA_VERSION,
)
from strict_json import load_strict_json_file  # noqa: E402
import run_completion_audit_recovery_queue as queue_runner  # noqa: E402
import validate_completion_audit_recovery_plan as plan_validator  # noqa: E402
import validate_completion_audit_recovery_queue as queue_validator  # noqa: E402


RECOVERY_WORK_ORDER_SCHEMA_VERSION = "wiii.completion_audit_recovery_work_order.v1"
WORK_ORDER_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery work order output path must not be a directory"
)
WORK_ORDER_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery work order output path must not be a symlink"
)
WORK_ORDER_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery work order output path parent must not be a symlink"
)
WORK_ORDER_STATES = {
    "invalid",
    "empty",
    "release_ready",
    "operator_setup_required",
    "autonomous_dispatch_ready",
    "blocked_by_dependency",
    "blocked",
}
WORK_ORDER_TASK_FIELDS = ACTION_ITEM_FIELDS | {
    "group_id",
    "safe_to_execute_autonomously",
    "operator_setup_required",
    "next_instruction",
}


@dataclass(frozen=True)
class RecoveryWorkOrderTask:
    item_id: str
    group_id: str
    kind: str
    action_type: str
    requirement_id: str
    blocker_id: str
    artifact: str
    status: str
    error_codes: list[str]
    workflow: str
    probe: str
    live_env_flags: list[str]
    live_guard_tokens: list[str]
    dispatch_or_schedule_gate_tokens: list[str]
    artifact_tokens: list[str]
    preflight_required_next: list[str]
    setup_category: str
    setup_key: str
    setup_evidence_kind: str
    source_handle_options: list[str]
    binding_token_count: int
    attestation_option_count: int
    pending_setup_check_count: int
    diagnostic_pending_setup_keys: list[str]
    non_diagnostic_pending_setup_keys: list[str]
    gate_reason: str
    safe_to_execute_autonomously: bool
    operator_setup_required: bool
    next_instruction: str


@dataclass(frozen=True)
class RecoveryWorkOrder:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    recovery_queue_path: str
    recovery_queue_sha256: str
    recovery_queue_schema_version: str
    recovery_queue_group_status_fingerprint_sha256: str
    recovery_plan_path: str
    recovery_plan_sha256: str
    recovery_plan_schema_version: str
    recovery_plan_action_items_fingerprint_sha256: str
    recovery_plan_execution_groups_fingerprint_sha256: str
    handoff_json_path: str
    handoff_json_sha256: str
    queue_state: str
    work_order_state: str
    selected_group_ids: list[str]
    selected_action_item_count: int
    setup_task_count: int
    runtime_task_count: int
    gate_task_count: int
    autonomous_dispatch_allowed: bool
    operator_setup_required: bool
    blocked_dependency_group_ids: list[str]
    work_order_fingerprint_sha256: str
    tasks: list[RecoveryWorkOrderTask]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_recovery_work_order(
    recovery_queue_path: Path,
    *,
    recovery_plan_path: Path,
    handoff_json_path: Path | None = None,
) -> RecoveryWorkOrder:
    errors: list[str] = []
    queue_payload: dict[str, Any] = {}
    plan_payload: dict[str, Any] = {}
    queue_validation = queue_validator.validate_recovery_queue(
        recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not queue_validation.ok:
        errors.append(
            "completion audit recovery work order queue failed validation: "
            + "; ".join(queue_validation.errors)
        )
    else:
        loaded_queue = load_strict_json_file(recovery_queue_path)
        if isinstance(loaded_queue, dict):
            queue_payload = loaded_queue
        else:
            errors.append("completion audit recovery work order queue root invalid")
    plan_validation = plan_validator.validate_recovery_plan(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not plan_validation.ok:
        errors.append(
            "completion audit recovery work order recovery plan failed validation: "
            + "; ".join(plan_validation.errors)
        )
    else:
        loaded_plan = load_strict_json_file(recovery_plan_path)
        if isinstance(loaded_plan, dict):
            plan_payload = loaded_plan
        else:
            errors.append("completion audit recovery work order recovery plan root invalid")
    tasks = _tasks(queue_payload, plan_payload, errors)
    return _report(
        recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
        queue_payload=queue_payload,
        plan_payload=plan_payload,
        tasks=tasks,
        errors=errors,
    )


def _tasks(
    queue_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    errors: list[str],
) -> list[RecoveryWorkOrderTask]:
    selected_group_ids = _string_list(queue_payload.get("next_group_ids"))
    group_statuses = _group_statuses_by_id(queue_payload.get("group_statuses"), errors)
    execution_groups = _execution_groups_by_id(plan_payload.get("execution_groups"), errors)
    action_items = _action_items_by_id(plan_payload.get("action_items"), errors)
    tasks: list[RecoveryWorkOrderTask] = []
    for group_id in selected_group_ids:
        group_status = group_statuses.get(group_id)
        execution_group = execution_groups.get(group_id)
        if group_status is None or execution_group is None:
            errors.append(
                "completion audit recovery work order selected group must exist in sources"
            )
            continue
        for item_id in _string_list(execution_group.get("item_ids")):
            item = action_items.get(item_id)
            if item is None:
                errors.append(
                    "completion audit recovery work order selected item must exist in recovery plan"
                )
                continue
            tasks.append(_task(group_id, group_status, item))
    return tasks


def _task(
    group_id: str,
    group_status: dict[str, Any],
    item: dict[str, Any],
) -> RecoveryWorkOrderTask:
    action_type = _string(item.get("action_type"))
    safe_to_execute = (
        group_status.get("status") == queue_runner.READY_STATUS
        and group_status.get("ready_for_autonomous_dispatch") is True
        and action_type == "workflow_probe_recovery"
    )
    operator_setup_required = action_type == "setup_resolution"
    task = RecoveryWorkOrderTask(
        item_id=_string(item.get("item_id")),
        group_id=group_id,
        kind=_string(item.get("kind")),
        action_type=action_type,
        requirement_id=_string(item.get("requirement_id")),
        blocker_id=_string(item.get("blocker_id")),
        artifact=_string(item.get("artifact")),
        status=_string(item.get("status")),
        error_codes=_string_list(item.get("error_codes")),
        workflow=_string(item.get("workflow")),
        probe=_string(item.get("probe")),
        live_env_flags=_string_list(item.get("live_env_flags")),
        live_guard_tokens=_string_list(item.get("live_guard_tokens")),
        dispatch_or_schedule_gate_tokens=_string_list(
            item.get("dispatch_or_schedule_gate_tokens")
        ),
        artifact_tokens=_string_list(item.get("artifact_tokens")),
        preflight_required_next=_string_list(item.get("preflight_required_next")),
        setup_category=_string(item.get("setup_category")),
        setup_key=_string(item.get("setup_key")),
        setup_evidence_kind=_string(item.get("setup_evidence_kind")),
        source_handle_options=_string_list(item.get("source_handle_options")),
        binding_token_count=_non_negative_int(item.get("binding_token_count")),
        attestation_option_count=_non_negative_int(
            item.get("attestation_option_count")
        ),
        pending_setup_check_count=_non_negative_int(
            item.get("pending_setup_check_count")
        ),
        diagnostic_pending_setup_keys=_string_list(
            item.get("diagnostic_pending_setup_keys")
        ),
        non_diagnostic_pending_setup_keys=_string_list(
            item.get("non_diagnostic_pending_setup_keys")
        ),
        gate_reason=_string(item.get("gate_reason")),
        safe_to_execute_autonomously=safe_to_execute,
        operator_setup_required=operator_setup_required,
        next_instruction=_next_instruction(item, safe_to_execute=safe_to_execute),
    )
    _assert_task_schema(task)
    return task


def _next_instruction(item: dict[str, Any], *, safe_to_execute: bool) -> str:
    action_type = _string(item.get("action_type"))
    if action_type == "setup_resolution":
        handles = _string_list(item.get("source_handle_options"))
        handle_text = ", ".join(handles) if handles else "a privacy-safe handle"
        return (
            "Bind "
            f"{_string(item.get('setup_category'))}:{_string(item.get('setup_key'))} "
            f"using {handle_text} and attest {_string(item.get('setup_evidence_kind'))}"
        )
    if safe_to_execute:
        return (
            "Dispatch "
            f"{_string(item.get('workflow'))} or run {_string(item.get('probe'))} "
            "with required live guard tokens and preflight evidence"
        )
    if action_type == "workflow_probe_recovery":
        return "wait until the recovery queue marks this runtime group ready"
    if action_type == "gate_dependency":
        return "clear release gate dependency: " + _string(item.get("gate_reason"))
    return "manual review required"


def _report(
    recovery_queue_path: Path,
    *,
    recovery_plan_path: Path,
    handoff_json_path: Path | None,
    queue_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    tasks: list[RecoveryWorkOrderTask],
    errors: list[str],
) -> RecoveryWorkOrder:
    task_dicts = [asdict(task) for task in tasks]
    selected_group_ids = _string_list(queue_payload.get("next_group_ids"))
    blocked_dependency_group_ids = _blocked_dependency_group_ids(
        queue_payload.get("group_statuses"),
        selected_group_ids=selected_group_ids,
    )
    autonomous_dispatch_allowed = bool(tasks) and all(
        task.safe_to_execute_autonomously for task in tasks
    )
    operator_setup_required = any(task.operator_setup_required for task in tasks)
    work_order_state = _work_order_state(
        queue_payload,
        tasks,
        errors,
        autonomous_dispatch_allowed=autonomous_dispatch_allowed,
        operator_setup_required=operator_setup_required,
        blocked_dependency_group_ids=blocked_dependency_group_ids,
    )
    handoff_source_path = (
        str(handoff_json_path)
        if handoff_json_path is not None
        else _string(queue_payload.get("handoff_json_path"))
    )
    return RecoveryWorkOrder(
        schema_version=RECOVERY_WORK_ORDER_SCHEMA_VERSION,
        ok=not errors,
        mode="dry_run",
        dry_run=True,
        recovery_queue_path=str(recovery_queue_path),
        recovery_queue_sha256=_regular_file_sha(recovery_queue_path),
        recovery_queue_schema_version=_string(queue_payload.get("schema_version")),
        recovery_queue_group_status_fingerprint_sha256=_string(
            queue_payload.get("group_status_fingerprint_sha256")
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
        handoff_json_path=handoff_source_path,
        handoff_json_sha256=(
            _regular_file_sha(handoff_json_path)
            if handoff_json_path is not None
            else _string(queue_payload.get("handoff_json_sha256"))
        ),
        queue_state=_string(queue_payload.get("queue_state")),
        work_order_state=work_order_state,
        selected_group_ids=selected_group_ids,
        selected_action_item_count=len(tasks),
        setup_task_count=sum(1 for task in tasks if task.action_type == "setup_resolution"),
        runtime_task_count=sum(
            1 for task in tasks if task.action_type == "workflow_probe_recovery"
        ),
        gate_task_count=sum(1 for task in tasks if task.action_type == "gate_dependency"),
        autonomous_dispatch_allowed=autonomous_dispatch_allowed,
        operator_setup_required=operator_setup_required,
        blocked_dependency_group_ids=blocked_dependency_group_ids,
        work_order_fingerprint_sha256=_work_order_fingerprint(
            work_order_state=work_order_state,
            selected_group_ids=selected_group_ids,
            tasks=task_dicts,
            autonomous_dispatch_allowed=autonomous_dispatch_allowed,
            operator_setup_required=operator_setup_required,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
        ),
        tasks=tasks,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _work_order_state(
    queue_payload: dict[str, Any],
    tasks: list[RecoveryWorkOrderTask],
    errors: list[str],
    *,
    autonomous_dispatch_allowed: bool,
    operator_setup_required: bool,
    blocked_dependency_group_ids: list[str],
) -> str:
    if errors:
        return "invalid"
    queue_state = _string(queue_payload.get("queue_state"))
    if queue_state == "empty":
        return "empty"
    if queue_state == "release_ready":
        return "release_ready"
    if blocked_dependency_group_ids:
        return "blocked_by_dependency"
    if operator_setup_required:
        return "operator_setup_required"
    if autonomous_dispatch_allowed:
        return "autonomous_dispatch_ready"
    if not tasks:
        return "blocked"
    return "blocked"


def _group_statuses_by_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        if value is not None:
            errors.append("completion audit recovery work order group_statuses invalid")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for status in value:
        if not isinstance(status, dict):
            errors.append("completion audit recovery work order group_status invalid")
            continue
        group_id = _string(status.get("group_id"))
        if group_id:
            result[group_id] = status
    return result


def _execution_groups_by_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        if value is not None:
            errors.append("completion audit recovery work order execution_groups invalid")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for group in value:
        if not isinstance(group, dict):
            errors.append("completion audit recovery work order execution_group invalid")
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
            errors.append("completion audit recovery work order action_items invalid")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            errors.append("completion audit recovery work order action_item invalid")
            continue
        item_id = _string(item.get("item_id"))
        if item_id:
            result[item_id] = item
    return result


def _blocked_dependency_group_ids(
    group_statuses: Any,
    *,
    selected_group_ids: list[str],
) -> list[str]:
    if not isinstance(group_statuses, list):
        return []
    result: list[str] = []
    for status in group_statuses:
        if not isinstance(status, dict):
            continue
        if status.get("group_id") not in selected_group_ids:
            continue
        for group_id in _string_list(status.get("blocked_dependency_group_ids")):
            if group_id not in result:
                result.append(group_id)
    return result


def _assert_task_schema(task: RecoveryWorkOrderTask) -> None:
    fields = set(asdict(task))
    missing = WORK_ORDER_TASK_FIELDS - fields
    extra = fields - WORK_ORDER_TASK_FIELDS
    if missing or extra:
        raise AssertionError("recovery work order task schema drift")


def _work_order_fingerprint(
    *,
    work_order_state: str,
    selected_group_ids: list[str],
    tasks: list[dict[str, Any]],
    autonomous_dispatch_allowed: bool,
    operator_setup_required: bool,
    blocked_dependency_group_ids: list[str],
) -> str:
    encoded = json.dumps(
        {
            "autonomous_dispatch_allowed": autonomous_dispatch_allowed,
            "blocked_dependency_group_ids": blocked_dependency_group_ids,
            "operator_setup_required": operator_setup_required,
            "selected_group_ids": selected_group_ids,
            "tasks": tasks,
            "work_order_state": work_order_state,
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
        raise ValueError(WORK_ORDER_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(WORK_ORDER_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(WORK_ORDER_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _non_negative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if error.startswith("completion audit recovery work order queue failed validation"):
        return "completion_audit_recovery_work_order_queue_invalid"
    if error.startswith(
        "completion audit recovery work order recovery plan failed validation"
    ):
        return "completion_audit_recovery_work_order_plan_invalid"
    if "selected group" in error or "group_status" in error or "execution_group" in error:
        return "completion_audit_recovery_work_order_group_invalid"
    if "selected item" in error or "action_item" in error:
        return "completion_audit_recovery_work_order_task_invalid"
    if error == WORK_ORDER_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_work_order_output_path_directory"
    if error == WORK_ORDER_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_work_order_output_path_symlink"
    if error == WORK_ORDER_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_work_order_output_path_parent_symlink"
    return "completion_audit_recovery_work_order_failed"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": RECOVERY_WORK_ORDER_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a dry-run recovery work order from a validated recovery "
            "queue and recovery plan."
        ),
    )
    parser.add_argument("recovery_queue", type=Path)
    parser.add_argument("--recovery-plan", type=Path, required=True)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        work_order = generate_completion_audit_recovery_work_order(
            args.recovery_queue,
            recovery_plan_path=args.recovery_plan,
            handoff_json_path=args.handoff_json,
        )
        text = json.dumps(work_order.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 0 if work_order.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
