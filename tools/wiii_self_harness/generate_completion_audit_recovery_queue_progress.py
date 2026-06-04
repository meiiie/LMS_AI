#!/usr/bin/env python3
"""Generate a progressed recovery queue from work-order status evidence."""

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
import validate_completion_audit_recovery_plan as plan_validator  # noqa: E402
import validate_completion_audit_recovery_queue as queue_validator  # noqa: E402
import validate_completion_audit_recovery_work_order_status as status_validator  # noqa: E402


QUEUE_PROGRESS_SCHEMA_VERSION = "wiii.completion_audit_recovery_queue_progress.v1"
QUEUE_PROGRESS_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery queue progress output path must not be a directory"
)
QUEUE_PROGRESS_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery queue progress output path must not be a symlink"
)
QUEUE_PROGRESS_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery queue progress output path parent must not be a symlink"
)


@dataclass(frozen=True)
class RecoveryQueueProgressReport:
    schema_version: str
    ok: bool
    mode: str
    dry_run: bool
    source_recovery_queue_path: str
    source_recovery_queue_sha256: str
    source_recovery_queue_schema_version: str
    source_recovery_queue_group_status_fingerprint_sha256: str
    recovery_plan_path: str
    recovery_plan_sha256: str
    recovery_plan_schema_version: str
    recovery_plan_action_items_fingerprint_sha256: str
    recovery_plan_execution_groups_fingerprint_sha256: str
    work_order_status_path: str
    work_order_status_sha256: str
    work_order_status_schema_version: str
    work_order_status_task_status_fingerprint_sha256: str
    recovery_work_order_path: str
    handoff_json_path: str
    handoff_json_sha256: str
    previous_queue_state: str
    queue_state: str
    completed_group_ids: list[str]
    pending_group_ids: list[str]
    selected_group_complete: bool
    advancement_applied: bool
    execution_group_count: int
    ready_group_count: int
    blocked_group_count: int
    blocked_by_external_setup_count: int
    blocked_by_dependency_count: int
    complete_group_count: int
    ready_for_autonomous_dispatch_count: int
    next_group_ids: list[str]
    group_status_fingerprint_sha256: str
    queue_progress_fingerprint_sha256: str
    group_statuses: list[queue_runner.RecoveryQueueGroupStatus]
    privacy: dict[str, bool]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["error_codes"] = _error_codes(self.errors)
        data["error_code_counts"] = _error_code_counts(self.errors)
        return data


def generate_completion_audit_recovery_queue_progress(
    source_recovery_queue_path: Path,
    *,
    recovery_plan_path: Path,
    work_order_status_path: Path,
    recovery_work_order_path: Path | None = None,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    launch_pack_path: Path | None = None,
) -> RecoveryQueueProgressReport:
    errors: list[str] = []
    queue_payload: dict[str, Any] = {}
    plan_payload: dict[str, Any] = {}
    status_payload: dict[str, Any] = {}
    queue_validation = queue_validator.validate_recovery_queue(
        source_recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not queue_validation.ok:
        errors.append(
            "completion audit recovery queue progress source queue failed validation: "
            + "; ".join(queue_validation.errors)
        )
    else:
        loaded_queue = load_strict_json_file(source_recovery_queue_path)
        if isinstance(loaded_queue, dict):
            queue_payload = loaded_queue
        else:
            errors.append("completion audit recovery queue progress source queue root invalid")
    plan_validation = plan_validator.validate_recovery_plan(
        recovery_plan_path,
        handoff_json_path=handoff_json_path,
    )
    if not plan_validation.ok:
        errors.append(
            "completion audit recovery queue progress recovery plan failed validation: "
            + "; ".join(plan_validation.errors)
        )
    else:
        loaded_plan = load_strict_json_file(recovery_plan_path)
        if isinstance(loaded_plan, dict):
            plan_payload = loaded_plan
        else:
            errors.append("completion audit recovery queue progress recovery plan root invalid")
    status_validation = status_validator.validate_recovery_work_order_status(
        work_order_status_path,
        recovery_work_order_path=recovery_work_order_path,
        recovery_queue_path=source_recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        launch_pack_path=launch_pack_path,
    )
    if not status_validation.ok:
        errors.append(
            "completion audit recovery queue progress work-order status failed validation: "
            + "; ".join(status_validation.errors)
        )
    else:
        loaded_status = load_strict_json_file(work_order_status_path)
        if isinstance(loaded_status, dict):
            status_payload = loaded_status
        else:
            errors.append(
                "completion audit recovery queue progress work-order status root invalid"
            )
    completed_group_ids = _string_list(status_payload.get("completed_group_ids"))
    group_statuses = _progressed_group_statuses(
        plan_payload,
        completed_group_ids=completed_group_ids,
        errors=errors,
    )
    return _report(
        source_recovery_queue_path,
        recovery_plan_path=recovery_plan_path,
        work_order_status_path=work_order_status_path,
        recovery_work_order_path=recovery_work_order_path,
        handoff_json_path=handoff_json_path,
        queue_payload=queue_payload,
        plan_payload=plan_payload,
        status_payload=status_payload,
        group_statuses=group_statuses,
        errors=errors,
    )


def _progressed_group_statuses(
    plan_payload: dict[str, Any],
    *,
    completed_group_ids: list[str],
    errors: list[str],
) -> list[queue_runner.RecoveryQueueGroupStatus]:
    execution_groups = plan_payload.get("execution_groups")
    action_items = _action_items_by_id(plan_payload.get("action_items"), errors)
    if not isinstance(execution_groups, list):
        if execution_groups is not None:
            errors.append("completion audit recovery queue progress execution_groups invalid")
        return []
    known_group_ids = {
        group.get("group_id")
        for group in execution_groups
        if isinstance(group, dict) and isinstance(group.get("group_id"), str)
    }
    completed = {group_id for group_id in completed_group_ids if group_id in known_group_ids}
    statuses: list[queue_runner.RecoveryQueueGroupStatus] = []
    for group in execution_groups:
        if not isinstance(group, dict):
            errors.append("completion audit recovery queue progress execution_group invalid")
            continue
        group_id = _string(group.get("group_id"))
        item_ids = _string_list(group.get("item_ids"))
        depends_on_group_ids = _string_list(group.get("depends_on_group_ids"))
        blocked_dependency_group_ids = [
            group_id
            for group_id in depends_on_group_ids
            if group_id in known_group_ids and group_id not in completed
        ]
        status = _status_for_group(
            group,
            group_id=group_id,
            item_ids=item_ids,
            completed_group_ids=completed,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
            action_items=action_items,
        )
        ready = _ready_for_autonomous_dispatch(group, status=status)
        blocked_external = status == queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
        group_status = queue_runner.RecoveryQueueGroupStatus(
            group_id=group_id,
            execution_mode=_string(group.get("execution_mode")),
            status=status,
            item_count=len(item_ids),
            depends_on_group_ids=depends_on_group_ids,
            blocked_dependency_group_ids=blocked_dependency_group_ids,
            blocked_by_external_setup=blocked_external,
            ready_for_autonomous_dispatch=ready,
            next_action=_next_action_for_group(
                group,
                status=status,
                blocked_dependency_group_ids=blocked_dependency_group_ids,
            ),
        )
        statuses.append(group_status)
    return statuses


def _status_for_group(
    group: dict[str, Any],
    *,
    group_id: str,
    item_ids: list[str],
    completed_group_ids: set[str],
    blocked_dependency_group_ids: list[str],
    action_items: dict[str, dict[str, Any]],
) -> str:
    if group_id in completed_group_ids:
        return queue_runner.COMPLETE_STATUS
    if blocked_dependency_group_ids:
        return queue_runner.BLOCKED_BY_DEPENDENCY_STATUS
    if not item_ids:
        return queue_runner.COMPLETE_STATUS
    execution_mode = _string(group.get("execution_mode"))
    if execution_mode == "operator_setup":
        return queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
    if _has_missing_recovery_action(item_ids, action_items):
        return queue_runner.BLOCKED_STATUS
    if execution_mode in {"workflow_dispatch_or_local_probe", "validation_gate"}:
        return queue_runner.READY_STATUS
    if group.get("ready_for_autonomous_dispatch") is True:
        return queue_runner.READY_STATUS
    if group.get("blocked_by_external_setup") is True:
        return queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
    return queue_runner.BLOCKED_STATUS


def _ready_for_autonomous_dispatch(
    group: dict[str, Any],
    *,
    status: str,
) -> bool:
    if status != queue_runner.READY_STATUS:
        return False
    return _string(group.get("execution_mode")) in {
        "workflow_dispatch_or_local_probe",
        "validation_gate",
    }


def _has_missing_recovery_action(
    item_ids: list[str],
    action_items: dict[str, dict[str, Any]],
) -> bool:
    return any(
        action_items.get(item_id, {}).get("action_type") == "missing_recovery_action"
        for item_id in item_ids
    )


def _next_action_for_group(
    group: dict[str, Any],
    *,
    status: str,
    blocked_dependency_group_ids: list[str],
) -> str:
    if status == queue_runner.COMPLETE_STATUS:
        return "no action required"
    if status == queue_runner.BLOCKED_BY_DEPENDENCY_STATUS:
        return (
            "wait for dependency groups to complete: "
            + ", ".join(blocked_dependency_group_ids)
        )
    title = _string(group.get("title"))
    return title or "manual review required"


def _report(
    source_recovery_queue_path: Path,
    *,
    recovery_plan_path: Path,
    work_order_status_path: Path,
    recovery_work_order_path: Path | None,
    handoff_json_path: Path | None,
    queue_payload: dict[str, Any],
    plan_payload: dict[str, Any],
    status_payload: dict[str, Any],
    group_statuses: list[queue_runner.RecoveryQueueGroupStatus],
    errors: list[str],
) -> RecoveryQueueProgressReport:
    group_status_dicts = [asdict(status) for status in group_statuses]
    completed_group_ids = _string_list(status_payload.get("completed_group_ids"))
    pending_group_ids = _string_list(status_payload.get("pending_group_ids"))
    next_group_ids = _next_group_ids(group_statuses)
    queue_state = _queue_state(group_statuses, errors)
    advancement_applied = bool(completed_group_ids)
    return RecoveryQueueProgressReport(
        schema_version=QUEUE_PROGRESS_SCHEMA_VERSION,
        ok=not errors,
        mode="dry_run",
        dry_run=True,
        source_recovery_queue_path=str(source_recovery_queue_path),
        source_recovery_queue_sha256=_regular_file_sha(source_recovery_queue_path),
        source_recovery_queue_schema_version=_string(queue_payload.get("schema_version")),
        source_recovery_queue_group_status_fingerprint_sha256=_string(
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
        work_order_status_path=str(work_order_status_path),
        work_order_status_sha256=_regular_file_sha(work_order_status_path),
        work_order_status_schema_version=_string(status_payload.get("schema_version")),
        work_order_status_task_status_fingerprint_sha256=_string(
            status_payload.get("task_status_fingerprint_sha256")
        ),
        recovery_work_order_path=(
            str(recovery_work_order_path)
            if recovery_work_order_path is not None
            else _string(status_payload.get("recovery_work_order_path"))
        ),
        handoff_json_path=(
            str(handoff_json_path)
            if handoff_json_path is not None
            else _string(status_payload.get("handoff_json_path"))
        ),
        handoff_json_sha256=_regular_file_sha(handoff_json_path),
        previous_queue_state=_string(queue_payload.get("queue_state")),
        queue_state=queue_state,
        completed_group_ids=completed_group_ids,
        pending_group_ids=pending_group_ids,
        selected_group_complete=status_payload.get("selected_group_complete") is True,
        advancement_applied=advancement_applied,
        execution_group_count=len(group_statuses),
        ready_group_count=sum(
            1 for status in group_statuses if status.status == queue_runner.READY_STATUS
        ),
        blocked_group_count=sum(
            1
            for status in group_statuses
            if status.status in queue_runner._blocked_statuses()
        ),
        blocked_by_external_setup_count=sum(
            1
            for status in group_statuses
            if status.status == queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
        ),
        blocked_by_dependency_count=sum(
            1
            for status in group_statuses
            if status.status == queue_runner.BLOCKED_BY_DEPENDENCY_STATUS
        ),
        complete_group_count=sum(
            1
            for status in group_statuses
            if status.status == queue_runner.COMPLETE_STATUS
        ),
        ready_for_autonomous_dispatch_count=sum(
            1
            for status in group_statuses
            if status.ready_for_autonomous_dispatch is True
        ),
        next_group_ids=next_group_ids,
        group_status_fingerprint_sha256=queue_runner._group_status_fingerprint(
            group_status_dicts
        ),
        queue_progress_fingerprint_sha256=_queue_progress_fingerprint(
            completed_group_ids=completed_group_ids,
            group_statuses=group_status_dicts,
            queue_state=queue_state,
            next_group_ids=next_group_ids,
        ),
        group_statuses=group_statuses,
        privacy={
            "secret_values_included": False,
            "credential_values_included": False,
            "raw_payload_included": False,
            "raw_identifiers_included": False,
        },
        errors=errors,
    )


def _next_group_ids(
    group_statuses: list[queue_runner.RecoveryQueueGroupStatus],
) -> list[str]:
    return [
        status.group_id
        for status in group_statuses
        if not status.blocked_dependency_group_ids
        and status.status
        in {
            queue_runner.READY_STATUS,
            queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS,
        }
    ]


def _queue_state(
    group_statuses: list[queue_runner.RecoveryQueueGroupStatus],
    errors: list[str],
) -> str:
    if errors:
        return "invalid"
    if not group_statuses:
        return "empty"
    if all(status.status == queue_runner.COMPLETE_STATUS for status in group_statuses):
        return "release_ready"
    if any(status.status == queue_runner.READY_STATUS for status in group_statuses):
        return "ready_for_autonomous_dispatch"
    if any(
        status.status == queue_runner.BLOCKED_BY_EXTERNAL_SETUP_STATUS
        for status in group_statuses
    ):
        return "blocked_on_external_setup"
    if any(
        status.status == queue_runner.BLOCKED_BY_DEPENDENCY_STATUS
        for status in group_statuses
    ):
        return "blocked_on_dependencies"
    return "blocked"


def _action_items_by_id(
    value: Any,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        if value is not None:
            errors.append("completion audit recovery queue progress action_items invalid")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            errors.append("completion audit recovery queue progress action_item invalid")
            continue
        item_id = _string(item.get("item_id"))
        if item_id:
            result[item_id] = item
    return result


def _queue_progress_fingerprint(
    *,
    completed_group_ids: list[str],
    group_statuses: list[dict[str, Any]],
    queue_state: str,
    next_group_ids: list[str],
) -> str:
    encoded = json.dumps(
        {
            "completed_group_ids": completed_group_ids,
            "group_statuses": group_statuses,
            "next_group_ids": next_group_ids,
            "queue_state": queue_state,
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
        raise ValueError(QUEUE_PROGRESS_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(QUEUE_PROGRESS_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(QUEUE_PROGRESS_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


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
        "completion audit recovery queue progress source queue failed validation"
    ):
        return "completion_audit_recovery_queue_progress_source_queue_invalid"
    if error.startswith(
        "completion audit recovery queue progress recovery plan failed validation"
    ):
        return "completion_audit_recovery_queue_progress_plan_invalid"
    if error.startswith(
        "completion audit recovery queue progress work-order status failed validation"
    ):
        return "completion_audit_recovery_queue_progress_status_invalid"
    if "root invalid" in error:
        return "completion_audit_recovery_queue_progress_root_invalid"
    if "execution_group" in error:
        return "completion_audit_recovery_queue_progress_execution_group_invalid"
    if "action_item" in error:
        return "completion_audit_recovery_queue_progress_action_item_invalid"
    if error == QUEUE_PROGRESS_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_queue_progress_output_path_directory"
    if error == QUEUE_PROGRESS_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_queue_progress_output_path_symlink"
    if error == QUEUE_PROGRESS_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_queue_progress_output_path_parent_symlink"
    return "completion_audit_recovery_queue_progress_failed"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "schema_version": QUEUE_PROGRESS_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a progressed recovery queue by applying validated "
            "work-order status evidence."
        ),
    )
    parser.add_argument("source_recovery_queue", type=Path)
    parser.add_argument("--recovery-plan", type=Path, required=True)
    parser.add_argument("--work-order-status", type=Path, required=True)
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
        progress = generate_completion_audit_recovery_queue_progress(
            args.source_recovery_queue,
            recovery_plan_path=args.recovery_plan,
            work_order_status_path=args.work_order_status,
            recovery_work_order_path=args.recovery_work_order,
            handoff_json_path=args.handoff_json,
            setup_state_path=args.setup_state,
            launch_pack_path=args.launch_pack,
        )
        text = json.dumps(progress.to_dict(), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 0 if progress.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            safe_write_report_text(args.out, text)
        else:
            print(text, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
