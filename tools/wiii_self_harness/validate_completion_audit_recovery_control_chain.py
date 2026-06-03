#!/usr/bin/env python3
"""Validate the source-bound completion-audit recovery control chain."""

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
import validate_completion_audit_recovery_dispatch_authorization as authorization_validator  # noqa: E402
import validate_completion_audit_recovery_dispatch_run as dispatch_run_validator  # noqa: E402
import validate_completion_audit_recovery_plan as plan_validator  # noqa: E402
import validate_completion_audit_recovery_queue as queue_validator  # noqa: E402
import validate_completion_audit_recovery_queue_progress as progress_validator  # noqa: E402
import validate_completion_audit_recovery_work_order as work_order_validator  # noqa: E402
import validate_completion_audit_recovery_work_order_status as status_validator  # noqa: E402


RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION = (
    "wiii.completion_audit_recovery_control_chain_validation.v1"
)
RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR = (
    "completion audit recovery control chain output path must not be a directory"
)
RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR = (
    "completion audit recovery control chain output path must not be a symlink"
)
RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR = (
    "completion audit recovery control chain output path parent must not be a symlink"
)
CHAIN_STATES = {
    "invalid",
    "operator_setup_required",
    "ready_for_recovery_dispatch",
    "recovery_dispatch_executed",
    "release_ready",
    "blocked_by_authorization",
    "blocked_by_missing_live_command_specs",
    "blocked_by_dependency",
    "blocked",
}


@dataclass(frozen=True)
class RecoveryControlChainValidationResult:
    validation_schema_version: str
    recovery_plan_path: str
    recovery_queue_path: str
    recovery_work_order_path: str
    recovery_work_order_status_path: str
    recovery_queue_progress_path: str
    recovery_dispatch_authorization_path: str
    recovery_dispatch_run_path: str
    handoff_json_path: str | None
    setup_state_path: str | None
    dispatch_gate_path: str | None
    launch_pack_path: str | None
    chain_state: str
    recovery_chain_ready: bool
    release_gate_ready: bool
    operator_setup_required: bool
    autonomous_dispatch_allowed: bool
    queue_state: str
    work_order_state: str
    status_state: str
    authorization_state: str
    dispatch_run_state: str
    next_group_ids: list[str]
    completed_group_ids: list[str]
    pending_group_ids: list[str]
    authorized_group_ids: list[str]
    blocked_group_ids: list[str]
    command_count: int
    chain_fingerprint_sha256: str
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


def validate_recovery_control_chain(
    *,
    recovery_plan_path: Path,
    recovery_queue_path: Path,
    recovery_work_order_path: Path,
    recovery_work_order_status_path: Path,
    recovery_queue_progress_path: Path,
    recovery_dispatch_authorization_path: Path,
    recovery_dispatch_run_path: Path,
    handoff_json_path: Path | None = None,
    setup_state_path: Path | None = None,
    dispatch_gate_path: Path | None = None,
    launch_pack_path: Path | None = None,
    repo_root: Path = Path("."),
) -> RecoveryControlChainValidationResult:
    errors: list[str] = []
    errors.extend(
        _validator_errors(
            "recovery plan",
            plan_validator.validate_recovery_plan(
                recovery_plan_path,
                handoff_json_path=handoff_json_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery queue",
            queue_validator.validate_recovery_queue(
                recovery_queue_path,
                recovery_plan_path=recovery_plan_path,
                handoff_json_path=handoff_json_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery work order",
            work_order_validator.validate_recovery_work_order(
                recovery_work_order_path,
                recovery_queue_path=recovery_queue_path,
                recovery_plan_path=recovery_plan_path,
                handoff_json_path=handoff_json_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery work-order status",
            status_validator.validate_recovery_work_order_status(
                recovery_work_order_status_path,
                recovery_work_order_path=recovery_work_order_path,
                recovery_queue_path=recovery_queue_path,
                recovery_plan_path=recovery_plan_path,
                handoff_json_path=handoff_json_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery queue progress",
            progress_validator.validate_recovery_queue_progress(
                recovery_queue_progress_path,
                source_recovery_queue_path=recovery_queue_path,
                recovery_plan_path=recovery_plan_path,
                work_order_status_path=recovery_work_order_status_path,
                recovery_work_order_path=recovery_work_order_path,
                handoff_json_path=handoff_json_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery dispatch authorization",
            authorization_validator.validate_recovery_dispatch_authorization(
                recovery_dispatch_authorization_path,
                recovery_queue_progress_path=recovery_queue_progress_path,
                recovery_plan_path=recovery_plan_path,
                dispatch_gate_path=dispatch_gate_path,
                source_recovery_queue_path=recovery_queue_path,
                work_order_status_path=recovery_work_order_status_path,
                recovery_work_order_path=recovery_work_order_path,
                handoff_json_path=handoff_json_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
            ),
        )
    )
    errors.extend(
        _validator_errors(
            "recovery dispatch run",
            dispatch_run_validator.validate_recovery_dispatch_run(
                recovery_dispatch_run_path,
                recovery_dispatch_authorization_path=(
                    recovery_dispatch_authorization_path
                ),
                recovery_queue_progress_path=recovery_queue_progress_path,
                recovery_plan_path=recovery_plan_path,
                dispatch_gate_path=dispatch_gate_path,
                source_recovery_queue_path=recovery_queue_path,
                work_order_status_path=recovery_work_order_status_path,
                recovery_work_order_path=recovery_work_order_path,
                handoff_json_path=handoff_json_path,
                setup_state_path=setup_state_path,
                launch_pack_path=launch_pack_path,
                repo_root=repo_root,
            ),
        )
    )
    payloads = _load_chain_payloads(
        recovery_plan_path=recovery_plan_path,
        recovery_queue_path=recovery_queue_path,
        recovery_work_order_path=recovery_work_order_path,
        recovery_work_order_status_path=recovery_work_order_status_path,
        recovery_queue_progress_path=recovery_queue_progress_path,
        recovery_dispatch_authorization_path=recovery_dispatch_authorization_path,
        recovery_dispatch_run_path=recovery_dispatch_run_path,
        errors=errors,
    )
    if payloads:
        errors.extend(
            _chain_consistency_errors(
                payloads,
                recovery_plan_path=recovery_plan_path,
                recovery_queue_path=recovery_queue_path,
                recovery_work_order_path=recovery_work_order_path,
                recovery_work_order_status_path=recovery_work_order_status_path,
                recovery_queue_progress_path=recovery_queue_progress_path,
                recovery_dispatch_authorization_path=(
                    recovery_dispatch_authorization_path
                ),
                handoff_json_path=handoff_json_path,
            )
        )
    return _result(
        recovery_plan_path=recovery_plan_path,
        recovery_queue_path=recovery_queue_path,
        recovery_work_order_path=recovery_work_order_path,
        recovery_work_order_status_path=recovery_work_order_status_path,
        recovery_queue_progress_path=recovery_queue_progress_path,
        recovery_dispatch_authorization_path=recovery_dispatch_authorization_path,
        recovery_dispatch_run_path=recovery_dispatch_run_path,
        handoff_json_path=handoff_json_path,
        setup_state_path=setup_state_path,
        dispatch_gate_path=dispatch_gate_path,
        launch_pack_path=launch_pack_path,
        payloads=payloads,
        errors=errors,
    )


def _result(
    *,
    recovery_plan_path: Path,
    recovery_queue_path: Path,
    recovery_work_order_path: Path,
    recovery_work_order_status_path: Path,
    recovery_queue_progress_path: Path,
    recovery_dispatch_authorization_path: Path,
    recovery_dispatch_run_path: Path,
    handoff_json_path: Path | None,
    setup_state_path: Path | None,
    dispatch_gate_path: Path | None,
    launch_pack_path: Path | None,
    payloads: dict[str, dict[str, Any]],
    errors: list[str],
) -> RecoveryControlChainValidationResult:
    queue = payloads.get("recovery_queue", {})
    work_order = payloads.get("recovery_work_order", {})
    status = payloads.get("recovery_work_order_status", {})
    progress = payloads.get("recovery_queue_progress", {})
    authorization = payloads.get("recovery_dispatch_authorization", {})
    dispatch_run = payloads.get("recovery_dispatch_run", {})
    queue_state = _string(progress.get("queue_state")) or _string(queue.get("queue_state"))
    work_order_state = _string(work_order.get("work_order_state"))
    status_state = _string(status.get("status_state"))
    authorization_state = _string(authorization.get("authorization_state"))
    dispatch_run_state = _string(dispatch_run.get("run_state"))
    chain_state = _chain_state(
        errors,
        queue_state=queue_state,
        work_order_state=work_order_state,
        status_state=status_state,
        authorization_state=authorization_state,
        dispatch_run_state=dispatch_run_state,
    )
    recovery_chain_ready = chain_state in {
        "ready_for_recovery_dispatch",
        "recovery_dispatch_executed",
        "release_ready",
    }
    release_gate_ready = queue_state == "release_ready"
    return RecoveryControlChainValidationResult(
        validation_schema_version=RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
        recovery_plan_path=str(recovery_plan_path),
        recovery_queue_path=str(recovery_queue_path),
        recovery_work_order_path=str(recovery_work_order_path),
        recovery_work_order_status_path=str(recovery_work_order_status_path),
        recovery_queue_progress_path=str(recovery_queue_progress_path),
        recovery_dispatch_authorization_path=str(recovery_dispatch_authorization_path),
        recovery_dispatch_run_path=str(recovery_dispatch_run_path),
        handoff_json_path=str(handoff_json_path) if handoff_json_path else None,
        setup_state_path=str(setup_state_path) if setup_state_path else None,
        dispatch_gate_path=str(dispatch_gate_path) if dispatch_gate_path else None,
        launch_pack_path=str(launch_pack_path) if launch_pack_path else None,
        chain_state=chain_state,
        recovery_chain_ready=recovery_chain_ready,
        release_gate_ready=release_gate_ready,
        operator_setup_required=chain_state == "operator_setup_required",
        autonomous_dispatch_allowed=(
            authorization.get("autonomous_dispatch_allowed") is True
        ),
        queue_state=queue_state,
        work_order_state=work_order_state,
        status_state=status_state,
        authorization_state=authorization_state,
        dispatch_run_state=dispatch_run_state,
        next_group_ids=_string_list(progress.get("next_group_ids"))
        or _string_list(queue.get("next_group_ids")),
        completed_group_ids=_string_list(progress.get("completed_group_ids")),
        pending_group_ids=_string_list(progress.get("pending_group_ids"))
        or _string_list(status.get("pending_group_ids")),
        authorized_group_ids=_string_list(authorization.get("authorized_group_ids")),
        blocked_group_ids=_string_list(authorization.get("blocked_group_ids"))
        or _string_list(dispatch_run.get("blocked_group_ids")),
        command_count=_int(dispatch_run.get("command_count")),
        chain_fingerprint_sha256=_chain_fingerprint(
            queue_state=queue_state,
            work_order_state=work_order_state,
            status_state=status_state,
            authorization_state=authorization_state,
            dispatch_run_state=dispatch_run_state,
            next_group_ids=_string_list(progress.get("next_group_ids")),
            completed_group_ids=_string_list(progress.get("completed_group_ids")),
            authorized_group_ids=_string_list(authorization.get("authorized_group_ids")),
            blocked_group_ids=_string_list(authorization.get("blocked_group_ids")),
            command_count=_int(dispatch_run.get("command_count")),
        ),
        errors=errors,
    )


def _chain_state(
    errors: list[str],
    *,
    queue_state: str,
    work_order_state: str,
    status_state: str,
    authorization_state: str,
    dispatch_run_state: str,
) -> str:
    if errors:
        return "invalid"
    if queue_state == "release_ready":
        return "release_ready"
    if dispatch_run_state == "executed":
        return "recovery_dispatch_executed"
    if dispatch_run_state == "ready":
        return "ready_for_recovery_dispatch"
    if dispatch_run_state == "blocked_by_missing_live_command_specs":
        return "blocked_by_missing_live_command_specs"
    if dispatch_run_state == "blocked_by_authorization":
        if (
            queue_state == "blocked_on_external_setup"
            or work_order_state == "operator_setup_required"
            or status_state in {"operator_setup_pending", "operator_setup_evidence_missing"}
        ):
            return "operator_setup_required"
        return "blocked_by_authorization"
    if queue_state == "blocked_on_dependencies":
        return "blocked_by_dependency"
    if authorization_state in {"blocked_by_dispatch_gate", "blocked_by_queue"}:
        return "blocked_by_authorization"
    return "blocked"


def _validator_errors(label: str, result: Any) -> list[str]:
    if result.ok:
        return []
    return [
        f"completion audit recovery control chain {label} failed validation: {error}"
        for error in result.errors
    ]


def _load_chain_payloads(
    *,
    recovery_plan_path: Path,
    recovery_queue_path: Path,
    recovery_work_order_path: Path,
    recovery_work_order_status_path: Path,
    recovery_queue_progress_path: Path,
    recovery_dispatch_authorization_path: Path,
    recovery_dispatch_run_path: Path,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    paths = {
        "recovery_plan": recovery_plan_path,
        "recovery_queue": recovery_queue_path,
        "recovery_work_order": recovery_work_order_path,
        "recovery_work_order_status": recovery_work_order_status_path,
        "recovery_queue_progress": recovery_queue_progress_path,
        "recovery_dispatch_authorization": recovery_dispatch_authorization_path,
        "recovery_dispatch_run": recovery_dispatch_run_path,
    }
    payloads: dict[str, dict[str, Any]] = {}
    for key, path in paths.items():
        try:
            payload = load_strict_json_file(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"completion audit recovery control chain {key} JSON is invalid: {exc}"
            )
            return {}
        if not isinstance(payload, dict):
            errors.append(
                f"completion audit recovery control chain {key} root must be an object"
            )
            return {}
        payloads[key] = payload
    return payloads


def _chain_consistency_errors(
    payloads: dict[str, dict[str, Any]],
    *,
    recovery_plan_path: Path,
    recovery_queue_path: Path,
    recovery_work_order_path: Path,
    recovery_work_order_status_path: Path,
    recovery_queue_progress_path: Path,
    recovery_dispatch_authorization_path: Path,
    handoff_json_path: Path | None,
) -> list[str]:
    errors: list[str] = []
    plan = payloads["recovery_plan"]
    queue = payloads["recovery_queue"]
    work_order = payloads["recovery_work_order"]
    status = payloads["recovery_work_order_status"]
    progress = payloads["recovery_queue_progress"]
    authorization = payloads["recovery_dispatch_authorization"]
    dispatch_run = payloads["recovery_dispatch_run"]
    expected_hashes = {
        "recovery queue recovery_plan_sha256": (
            queue.get("recovery_plan_sha256"),
            _sha256_file(recovery_plan_path),
        ),
        "recovery work order recovery_queue_sha256": (
            work_order.get("recovery_queue_sha256"),
            _sha256_file(recovery_queue_path),
        ),
        "recovery work order recovery_plan_sha256": (
            work_order.get("recovery_plan_sha256"),
            _sha256_file(recovery_plan_path),
        ),
        "work-order status recovery_work_order_sha256": (
            status.get("recovery_work_order_sha256"),
            _sha256_file(recovery_work_order_path),
        ),
        "queue progress source_recovery_queue_sha256": (
            progress.get("source_recovery_queue_sha256"),
            _sha256_file(recovery_queue_path),
        ),
        "queue progress recovery_plan_sha256": (
            progress.get("recovery_plan_sha256"),
            _sha256_file(recovery_plan_path),
        ),
        "queue progress work_order_status_sha256": (
            progress.get("work_order_status_sha256"),
            _sha256_file(recovery_work_order_status_path),
        ),
        "dispatch authorization recovery_queue_progress_sha256": (
            authorization.get("recovery_queue_progress_sha256"),
            _sha256_file(recovery_queue_progress_path),
        ),
        "dispatch authorization recovery_plan_sha256": (
            authorization.get("recovery_plan_sha256"),
            _sha256_file(recovery_plan_path),
        ),
        "dispatch run recovery_dispatch_authorization_sha256": (
            dispatch_run.get("recovery_dispatch_authorization_sha256"),
            _sha256_file(recovery_dispatch_authorization_path),
        ),
    }
    if handoff_json_path is not None:
        expected_hashes["recovery plan handoff_sha256"] = (
            plan.get("handoff_sha256"),
            _sha256_file(handoff_json_path),
        )
        expected_hashes["recovery queue handoff_json_sha256"] = (
            queue.get("handoff_json_sha256"),
            _sha256_file(handoff_json_path),
        )
        expected_hashes["queue progress handoff_json_sha256"] = (
            progress.get("handoff_json_sha256"),
            _sha256_file(handoff_json_path),
        )
    for label, (actual, expected) in expected_hashes.items():
        if actual != expected:
            errors.append(
                f"completion audit recovery control chain {label} must match source"
            )
    fingerprint_pairs = {
        "queue action-items fingerprint": (
            queue.get("recovery_plan_action_items_fingerprint_sha256"),
            plan.get("action_items_fingerprint_sha256"),
        ),
        "queue execution-groups fingerprint": (
            queue.get("recovery_plan_execution_groups_fingerprint_sha256"),
            plan.get("execution_groups_fingerprint_sha256"),
        ),
        "work-order queue group-status fingerprint": (
            work_order.get("recovery_queue_group_status_fingerprint_sha256"),
            queue.get("group_status_fingerprint_sha256"),
        ),
        "work-order status work-order fingerprint": (
            status.get("recovery_work_order_fingerprint_sha256"),
            work_order.get("work_order_fingerprint_sha256"),
        ),
        "progress source queue group-status fingerprint": (
            progress.get("source_recovery_queue_group_status_fingerprint_sha256"),
            queue.get("group_status_fingerprint_sha256"),
        ),
        "progress work-order-status task fingerprint": (
            progress.get("work_order_status_task_status_fingerprint_sha256"),
            status.get("task_status_fingerprint_sha256"),
        ),
        "authorization queue-progress fingerprint": (
            authorization.get("queue_progress_fingerprint_sha256"),
            progress.get("queue_progress_fingerprint_sha256"),
        ),
        "dispatch-run authorization fingerprint": (
            dispatch_run.get("authorization_fingerprint_sha256"),
            authorization.get("authorization_fingerprint_sha256"),
        ),
    }
    for label, (actual, expected) in fingerprint_pairs.items():
        if actual != expected:
            errors.append(
                f"completion audit recovery control chain {label} must match"
            )
    if queue.get("next_group_ids") != work_order.get("selected_group_ids"):
        errors.append(
            "completion audit recovery control chain queue next groups must match work-order selection"
        )
    if status.get("completed_group_ids") != progress.get("completed_group_ids"):
        errors.append(
            "completion audit recovery control chain completed groups must match progress"
        )
    if progress.get("next_group_ids") != authorization.get("next_group_ids"):
        errors.append(
            "completion audit recovery control chain progress next groups must match authorization"
        )
    if authorization.get("authorization_state") != dispatch_run.get("authorization_state"):
        errors.append(
            "completion audit recovery control chain authorization state must match dispatch run"
        )
    if authorization.get("autonomous_dispatch_allowed") != dispatch_run.get(
        "autonomous_dispatch_allowed"
    ):
        errors.append(
            "completion audit recovery control chain autonomous dispatch flag must match dispatch run"
        )
    if authorization.get("blocked_group_ids") != dispatch_run.get("blocked_group_ids"):
        errors.append(
            "completion audit recovery control chain blocked groups must match dispatch run"
        )
    if progress.get("queue_state") != authorization.get("queue_state"):
        errors.append(
            "completion audit recovery control chain progress queue_state must match authorization"
        )
    if progress.get("queue_state") != work_order.get("queue_state"):
        if work_order.get("queue_state") != queue.get("queue_state"):
            errors.append(
                "completion audit recovery control chain work-order queue_state must match source queue"
            )
    if progress.get("queue_state") != "ready_for_autonomous_dispatch":
        if authorization.get("autonomous_dispatch_allowed") is not False:
            errors.append(
                "completion audit recovery control chain blocked queue cannot allow autonomous dispatch"
            )
        if dispatch_run.get("command_count") != 0:
            errors.append(
                "completion audit recovery control chain blocked queue cannot materialize commands"
            )
    if authorization.get("autonomous_dispatch_allowed") is not True:
        if dispatch_run.get("run_state") != "blocked_by_authorization":
            errors.append(
                "completion audit recovery control chain blocked authorization must block dispatch run"
            )
    if (
        authorization.get("autonomous_dispatch_allowed") is True
        and authorization.get("live_command_specs_included") is not True
    ):
        if dispatch_run.get("run_state") != "blocked_by_missing_live_command_specs":
            errors.append(
                "completion audit recovery control chain missing live specs must block dispatch run"
            )
    if dispatch_run.get("command_count", 0) > 0:
        if authorization.get("live_command_specs_included") is not True:
            errors.append(
                "completion audit recovery control chain commands require live command specs"
            )
        if authorization.get("autonomous_dispatch_allowed") is not True:
            errors.append(
                "completion audit recovery control chain commands require autonomous dispatch"
            )
    return errors


def _chain_fingerprint(
    *,
    queue_state: str,
    work_order_state: str,
    status_state: str,
    authorization_state: str,
    dispatch_run_state: str,
    next_group_ids: list[str],
    completed_group_ids: list[str],
    authorized_group_ids: list[str],
    blocked_group_ids: list[str],
    command_count: int,
) -> str:
    encoded = json.dumps(
        {
            "authorization_state": authorization_state,
            "authorized_group_ids": authorized_group_ids,
            "blocked_group_ids": blocked_group_ids,
            "command_count": command_count,
            "completed_group_ids": completed_group_ids,
            "dispatch_run_state": dispatch_run_state,
            "next_group_ids": next_group_ids,
            "queue_state": queue_state,
            "status_state": status_state,
            "work_order_state": work_order_state,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path | None) -> str:
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
        raise ValueError(RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR)
    if out_path.is_symlink():
        raise ValueError(RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR)
    for parent in out_path.parents:
        if parent.exists() and parent.is_symlink():
            raise ValueError(RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _error_codes(errors: list[str]) -> list[str]:
    return sorted({_error_code(error) for error in errors})


def _error_code_counts(errors: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in (_error_code(error) for error in errors):
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _error_code(error: str) -> str:
    if "failed validation" in error:
        return "completion_audit_recovery_control_chain_child_invalid"
    if "JSON is invalid" in error or "root must be an object" in error:
        return "completion_audit_recovery_control_chain_child_invalid"
    if "must match source" in error or "must match source queue" in error:
        return "completion_audit_recovery_control_chain_source_mismatch"
    if "fingerprint" in error:
        return "completion_audit_recovery_control_chain_fingerprint_mismatch"
    if "state" in error or "queue" in error or "dispatch" in error:
        return "completion_audit_recovery_control_chain_state_mismatch"
    if error == RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_DIRECTORY_ERROR:
        return "completion_audit_recovery_control_chain_output_path_directory"
    if error == RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_SYMLINK_ERROR:
        return "completion_audit_recovery_control_chain_output_path_symlink"
    if error == RECOVERY_CONTROL_CHAIN_OUTPUT_PATH_PARENT_SYMLINK_ERROR:
        return "completion_audit_recovery_control_chain_output_path_parent_symlink"
    return "completion_audit_recovery_control_chain_validation_error"


def _json_error_payload(error: str) -> dict[str, Any]:
    code = _error_code(error)
    return {
        "validation_schema_version": RECOVERY_CONTROL_CHAIN_VALIDATION_SCHEMA_VERSION,
        "ok": False,
        "errors": [error],
        "error_codes": [code],
        "error_code_counts": {code: 1},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the source-bound completion-audit recovery control chain.",
    )
    parser.add_argument("--recovery-plan", type=Path, required=True)
    parser.add_argument("--recovery-queue", type=Path, required=True)
    parser.add_argument("--recovery-work-order", type=Path, required=True)
    parser.add_argument("--work-order-status", type=Path, required=True)
    parser.add_argument("--queue-progress", type=Path, required=True)
    parser.add_argument("--recovery-dispatch-authorization", type=Path, required=True)
    parser.add_argument("--recovery-dispatch-run", type=Path, required=True)
    parser.add_argument("--handoff-json", type=Path, default=None)
    parser.add_argument("--setup-state", type=Path, default=None)
    parser.add_argument("--dispatch-gate", type=Path, default=None)
    parser.add_argument("--launch-pack", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_output_path(args.out)
        result = validate_recovery_control_chain(
            recovery_plan_path=args.recovery_plan,
            recovery_queue_path=args.recovery_queue,
            recovery_work_order_path=args.recovery_work_order,
            recovery_work_order_status_path=args.work_order_status,
            recovery_queue_progress_path=args.queue_progress,
            recovery_dispatch_authorization_path=args.recovery_dispatch_authorization,
            recovery_dispatch_run_path=args.recovery_dispatch_run,
            handoff_json_path=args.handoff_json,
            setup_state_path=args.setup_state,
            dispatch_gate_path=args.dispatch_gate,
            launch_pack_path=args.launch_pack,
            repo_root=args.repo_root,
        )
        if args.json or args.out:
            text = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
        elif result.ok:
            text = "Wiii Completion Audit Recovery Control Chain Validation: PASS\n"
        else:
            text = (
                "Wiii Completion Audit Recovery Control Chain Validation: FAIL\n"
                + "\n".join(f"- {error}" for error in result.errors)
                + "\n"
            )
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
        return 0 if result.ok else 1
    except Exception as exc:  # noqa: BLE001
        text = json.dumps(_json_error_payload(str(exc)), indent=2, sort_keys=True) + "\n"
        if args.out:
            try:
                safe_write_report_text(args.out, text)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        else:
            print(text, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
