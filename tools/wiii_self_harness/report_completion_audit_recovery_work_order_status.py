#!/usr/bin/env python3
"""Report execution status for a completion-audit recovery work order."""

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
import validate_completion_audit_recovery_work_order as work_order_validator  # noqa: E402
import validate_completion_audit_setup_state as setup_state_validator  # noqa: E402


WORK_ORDER_STATUS_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_work_order_status.v1"
)
WORK_ORDER_STATUS_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery work order status output path must not be a directory"
)
WORK_ORDER_STATUS_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery work order status output path must not be a symlink"
)
WORK_ORDER_STATUS_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery work order status output path parent must not be a symlink"
)
TASK_STATUS_FIELDS = {
    "item_id",
    "group_id",
    "requirement_id",
    "action_type",
    "status",
    "setup_category",
    "setup_key",
    "setup_evidence_kind",
    "source_handle",
    "operator_setup_required",
    "safe_to_execute_autonomously",
    "next_action",
}
STATUS_STATES = {
    "invalid",
    "empty",
    "release_ready",
    "operator_setup_evidence_missing",
    "operator_setup_pending",
    "operator_setup_complete",
    "autonomous_dispatch_ready",
    "blocked",
}
TASK_STATUSES = {
    "satisfied",
    "pending",
    "ready_for_dispatch",
    "blocked_by_missing_setup_state",
    "blocked",
}


@dataclass(frozen=True)
class RecoveryWorkOrderTaskStatus:
    item_id: str
    group_id: str
    requirement_id: str
    action_type: str
    status: str
    setup_category: str
    setup_key: str
    setup_evidence_kind: str
    source_handle: str
    operator_setup_required: bool
    safe_to_execute_autonomously: bool
    next_action: str


@dataclass(frozen=True)
class RecoveryWorkOrderStatusReport:
    schema_version: str
    ok: bool
    recovery_work_order_path: str
    recovery_work_order_sha256: str
    recovery_work_order_schema_version: str
    recovery_work_order_fingerprint_sha256: str
    recovery_queue_path: str
    recovery_plan_path: str
    handoff_json_path: str
    setup_state_path: str
    setup_state_sha256: str
    setup_state_schema_version: str
    setup_state_fingerprint_sha256: str
    work_order_state: str
    status_state: str
    selected_group_ids: list[str]
    selected_group_complete: bool
    completed_group_ids: list[str]
    pending_group_ids: list[str]
    task_status_count: int
    satisfied_task_count: int
    pending_task_count: int
    setup_task_satisfied_count: int
    autonomous_task_ready_count: int
    task_status_fingerprint_sha256: str
    task_statuses: list[RecoveryWorkOrderTaskStatus]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def report_completion_audit_recovery_work_order_status(
    recovery_work_order_path: Path,
    *,
    recovery_queue_path: Path | None = None,
    recovery_plan_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> RecoveryWorkOrderStatusReport:
    errors: list[str] = []
    work_order_payload: dict[str, Any] = {}
    setup_state_payload: dict[str, Any] = {}
    work_order_validation = work_order_validator.validate_recovery_work_order(
        recovery_work_order_path,
        recovery_queue_path=recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not work_order_validation.ok:
        errors.append(
            "completion audit recovery work order status work order failed validation: "
            + "; ".join(work_order_validation.errors)
        )
    else:
        loaded_work_order = load_strict_json_file(recovery_work_order_path)
        if isinstance(loaded_work_order, dict):
            work_order_payload = loaded_work_order
        else:
            errors.append(
                "completion audit recovery work order status work order root invalid"
            )
    if setup_state_path is not None:
        setup_validation = setup_state_validator.validate_setup_state(
            setup_state_path,
            launch_pack_path=launch_pack_path,
        )
        if not setup_validation.ok:
            errors.append(
                "completion audit recovery work order status setup state failed validation: "
                + "; ".join(setup_validation.errors)
            )
        else:
            loaded_setup_state = load_strict_json_file(setup_state_path)
            if isinstance(loaded_setup_state, dict):
                setup_state_payload = loaded_setup_state
            else:
                errors.append(
                    "completion audit recovery work order status setup state root invalid"
                )
    task_statuses = _task_statuses(
        work_order_payload.get("tasks"),
        setup_state_payload=setup_state_payload,
    )
    return _report(
        recovery_work_order_path,
        recovery_queue_path=recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        work_order_payload=work_order_payload,
        setup_state_payload=setup_state_payload,
        task_statuses=task_statuses,
        errors=errors,
    )


def _task_statuses(
    tasks: Any,
    *,
    setup_state_payload: dict[str, Any],
) -> list[RecoveryWorkOrderTaskStatus]:
    if not isinstance(tasks, list):
        return []
    setup_index = _setup_check_index(setup_state_payload)
    statuses: list[RecoveryWorkOrderTaskStatus] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_status = _task_status(task, setup_index=setup_index)
        _assert_task_status_schema(task_status)
        statuses.append(task_status)
    return statuses


def _task_status(
    task: dict[str, Any],
    *,
    setup_index: dict[tuple[str, str, str], dict[str, Any]],
) -> RecoveryWorkOrderTaskStatus:
    action_type = _string(task.get("action_type"))
    requirement_id = _string(task.get("requirement_id"))
    setup_category = _string(task.get("setup_category"))
    setup_key = _string(task.get("setup_key"))
    source_handle = ""
    if action_type == "setup_resolution":
        if not setup_index:
            status = "blocked_by_missing_setup_state"
            next_action = "provide a validated setup-state artifact"
        else:
            check = setup_index.get((requirement_id, setup_category, setup_key))
            if isinstance(check, dict) and check.get("present") is True:
                status = "satisfied"
                source_handle = _string(check.get("source_handle"))
                next_action = "setup evidence satisfied"
            else:
                status = "pending"
                next_action = _string(task.get("next_instruction"))
    elif task.get("safe_to_execute_autonomously") is True:
        status = "ready_for_dispatch"
        next_action = _string(task.get("next_instruction"))
    else:
        status = "blocked"
        next_action = _string(task.get("next_instruction"))
    return RecoveryWorkOrderTaskStatus(
        item_id=_string(task.get("item_id")),
        group_id=_string(task.get("group_id")),
        requirement_id=requirement_id,
        action_type=action_type,
        status=status,
        setup_category=setup_category,
        setup_key=setup_key,
        setup_evidence_kind=_string(task.get("setup_evidence_kind")),
        source_handle=source_handle,
        operator_setup_required=task.get("operator_setup_required") is True,
        safe_to_execute_autonomously=task.get("safe_to_execute_autonomously") is True,
        next_action=next_action,
    )


def _report(
    recovery_work_order_path: Path,
    *,
    recovery_queue_path: Path | None,
    recovery_plan_path: Path | None,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    work_order_payload: dict[str, Any],
    setup_state_payload: dict[str, Any],
    task_statuses: list[RecoveryWorkOrderTaskStatus],
    errors: list[str],
) -> RecoveryWorkOrderStatusReport:
    task_status_dicts = [asdict(status) for status in task_statuses]
    selected_group_ids = _string_list(work_order_payload.get("selected_group_ids"))
    completed_group_ids = _completed_group_ids(task_statuses, selected_group_ids)
    pending_group_ids = [
        group_id for group_id in selected_group_ids if group_id not in completed_group_ids
    ]
    selected_group_complete = bool(selected_group_ids) and not pending_group_ids
    status_state = _status_state(
        work_order_payload,
        task_statuses,
        errors,
        selected_group_complete=selected_group_complete,
        setup_state_present=bool(setup_state_payload),
    )
    return RecoveryWorkOrderStatusReport(
        schema_version=WORK_ORDER_STATUS_SCHEMA_VERSION,
        ok=not errors,
        recovery_work_order_path=str(recovery_work_order_path),
        recovery_work_order_sha256=_regular_file_sha(recovery_work_order_path),
        recovery_work_order_schema_version=_string(
            work_order_payload.get("schema_version")
        ),
        recovery_work_order_fingerprint_sha256=_string(
            work_order_payload.get("work_order_fingerprint_sha256")
        ),
        recovery_queue_path=(
            str(recovery_queue_path)
            if recovery_queue_path is not None
            else _string(work_order_payload.get("recovery_queue_path"))
        ),
        recovery_plan_path=(
            str(recovery_plan_path)
            if recovery_plan_path is not None
            else _string(work_order_payload.get("recovery_plan_path"))
        ),
        handoff_json_path=(
            str(handoff_json_path)
            if handoff_json_path is not None
            else _string(work_order_payload.get("handoff_json_path"))
        ),
        setup_state_path=str(setup_state_path) if setup_state_path else "",
        setup_state_sha256=_regular_file_sha(setup_state_path),
        setup_state_schema_version=_string(setup_state_payload.get("schema_version")),
        setup_state_fingerprint_sha256=_string(
            setup_state_payload.get("setup_state_fingerprint_sha256")
        ),
        work_order_state=_string(work_order_payload.get("work_order_state")),
        status_state=status_state,
        selected_group_ids=selected_group_ids,
        selected_group_complete=selected_group_complete,
        completed_group_ids=completed_group_ids,
        pending_group_ids=pending_group_ids,
        task_status_count=len(task_statuses),
        satisfied_task_count=sum(
            1 for status in task_statuses if status.status == "satisfied"
        ),
        pending_task_count=sum(
            1 for status in task_statuses if status.status in _pending_statuses()
        ),
        setup_task_satisfied_count=sum(
            1
            for status in task_statuses
            if status.operator_setup_required and status.status == "satisfied"
        ),
        autonomous_task_ready_count=sum(
            1 for status in task_statuses if status.status == "ready_for_dispatch"
        ),
        task_status_fingerprint_sha256=_task_status_fingerprint(task_status_dicts),
        task_statuses=task_statuses,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _status_state(
    work_order_payload: dict[str, Any],
    task_statuses: list[RecoveryWorkOrderTaskStatus],
    errors: list[str],
    *,
    selected_group_complete: bool,
    setup_state_present: bool,
) -> str:
    if errors:
        return "invalid"
    work_order_state = _string(work_order_payload.get("work_order_state"))
    if work_order_state == "empty":
        return "empty"
    if work_order_state == "release_ready":
        return "release_ready"
    if work_order_state == "operator_setup_required":
        if not setup_state_present:
            return "operator_setup_evidence_missing"
        return "operator_setup_complete" if selected_group_complete else "operator_setup_pending"
    if work_order_state == "autonomous_dispatch_ready":
        return "autonomous_dispatch_ready"
    return "blocked"


def _completed_group_ids(
    task_statuses: list[RecoveryWorkOrderTaskStatus],
    selected_group_ids: list[str],
) -> list[str]:
    result: list[str] = []
    for group_id in selected_group_ids:
        group_statuses = [
            status for status in task_statuses if status.group_id == group_id
        ]
        if group_statuses and all(status.status == "satisfied" for status in group_statuses):
            result.append(group_id)
    return result


def _setup_check_index(
    setup_state_payload: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    requirements = setup_state_payload.get("requirements")
    if not isinstance(requirements, list):
        return result
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = _string(requirement.get("requirement_id"))
        checks = requirement.get("setup_checks")
        if not requirement_id or not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict):
                continue
            category = _string(check.get("category"))
            key = _string(check.get("key"))
            if category and key:
                result[(requirement_id, category, key)] = check
    return result


def _pending_statuses() -> set[str]:
    return {"pending", "blocked_by_missing_setup_state", "blocked"}


def _assert_task_status_schema(status: RecoveryWorkOrderTaskStatus) -> None:
    fields = set(asdict(status))
    missing = TASK_STATUS_FIELDS - fields
    extra = fields - TASK_STATUS_FIELDS
    if missing or extra:
        raise AssertionError("recovery work order status task schema drift")


def _task_status_fingerprint(task_statuses: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        task_statuses,
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
        raise ValueError(WORK_ORDER_STATUS_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(WORK_ORDER_STATUS_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(WORK_ORDER_STATUS_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


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
        "completion audit recovery work order status work order failed validation"
    ):
        return "completion_audit_recovery_work_order_status_work_order_invalid"
    if error.startswith(
        "completion audit recovery work order status setup state failed validation"
    ):
        return "completion_audit_recovery_work_order_status_setup_state_invalid"
    if "root invalid" in error:
        return "completion_audit_recovery_work_order_status_root_invalid"
    if error == WORK_ORDER_STATUS_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_work_order_status_output_path_directory"
    if error == WORK_ORDER_STATUS_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_work_order_status_output_path_symlink"
    if error == WORK_ORDER_STATUS_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_work_order_status_output_path_parent_symlink"
    return "completion_audit_recovery_work_order_status_failed"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": WORK_ORDER_STATUS_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report whether a recovery work order is satisfied by privacy-safe "
            "setup state evidence."
        ),
    )
    parser.add_argument("recovery_work_order", type=Path)
    parser.add_argument("--recovery-queue", type=Path, default=None)
    parser.add_argument("--recovery-plan", type=Path, default=None)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        report = report_completion_audit_recovery_work_order_status(
            args.recovery_work_order,
            recovery_queue_path=args.recovery_queue,
            recovery_plan_path=args.recovery_plan,
            handoff_json_path=args.handoff_json,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
        )
        text = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 0 if report.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
