"""Live scheduled-task replay against the real scheduler repository.

This probe is intentionally opt-in because it writes one row to the configured
Postgres database. It exercises the production repository/tool/executor pieces
without polling every due task in the environment.

Example:
    WIII_LIVE_SCHEDULER_REPLAY=1 python scripts/probe_live_scheduled_task_replay.py --allow-write --out autonomy-scheduler-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


TASK_ID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
ENV_FLAG = "WIII_LIVE_SCHEDULER_REPLAY"
SCHEMA_VERSION = "wiii.live_scheduler_replay_probe.v1"
POLL_METRIC = "runtime.scheduled_tasks.polls"
DUE_METRIC = "runtime.scheduled_tasks.due"
RUNS_METRIC = "runtime.scheduled_tasks.runs"
DELIVERY_METRIC = "runtime.scheduled_tasks.delivery"
DURATION_METRIC = "runtime.scheduled_tasks.duration_ms"


@dataclass
class CapturingWebSocket:
    accepted: bool = False
    sent_texts: list[str] = field(default_factory=list)

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        self.sent_texts.append(data)


def _json_print(payload: dict[str, Any]) -> None:
    emit_json_payload(payload)


def _redact_error(value: Any) -> str:
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        return redact_runtime_secret_text(str(value))
    except Exception:  # noqa: BLE001
        return str(value)


def _fallback_hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _safe_hash(value: Any) -> str | None:
    try:
        return _hash(value)
    except Exception:  # noqa: BLE001
        return _fallback_hash(value)


def _redact_failure_text(value: Any, args: argparse.Namespace | None = None) -> str:
    text = _redact_error(value)[:1000]
    text = TASK_ID_RE.sub(
        lambda match: _fallback_hash(match.group(0)) or "<redacted-task-id>",
        text,
    )
    replacements = {
        "access_token": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
        "authorization": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_identifier in (
            getattr(args, "user_id", None),
            getattr(args, "session_id", None),
            getattr(args, "organization_id", None),
            getattr(args, "description", None),
        ):
            if not raw_identifier:
                continue
            replacements[str(raw_identifier)] = (
                _safe_hash(raw_identifier) or "<redacted-value>"
            )
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def _failure_payload(exc: Exception, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error_code": "scheduler_replay_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_task_id_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_description_included": False,
            "raw_database_row_included": False,
            "raw_metric_payload_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _require_live_write(args: argparse.Namespace) -> None:
    if not args.allow_write:
        raise SystemExit("--allow-write is required; this probe writes one scheduled_tasks row")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live scheduler replay")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to write to production without --allow-production")


def _hash(value: Any) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    if value is None:
        return None
    return hash_memory_identifier(str(value))


def _safe_labels(labels: Any) -> str:
    try:
        return json.dumps(dict(labels), ensure_ascii=False, sort_keys=True)
    except Exception:  # noqa: BLE001
        return str(labels)


def _metric_counter_map(metrics: dict[str, Any], metric_name: str) -> dict[str, int]:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return {}
    return {
        _safe_labels(labels): int(count)
        for labels, count in counters.items()
    }


def _metric_event_count(metrics: dict[str, Any], metric_name: str) -> int:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return 0
    total = 0
    for count in counters.values():
        try:
            total += max(0, int(count))
        except (TypeError, ValueError):
            continue
    return total


def _metric_label_count(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> int:
    counters = metrics.get("counters", {}).get(metric_name, {})
    if not isinstance(counters, dict):
        return 0
    total = 0
    for labels, count in counters.items():
        try:
            label_map = dict(labels)
            numeric_count = int(count)
        except Exception:  # noqa: BLE001
            continue
        if all(label_map.get(key) == value for key, value in expected.items()):
            total += max(0, numeric_count)
    return total


def _metric_label_seen(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> bool:
    return _metric_label_count(metrics, metric_name, expected=expected) > 0


def _histogram_event_count(metrics: dict[str, Any], metric_name: str) -> int:
    histograms = metrics.get("histograms", {}).get(metric_name, {})
    if not isinstance(histograms, dict):
        return 0
    total = 0
    for values in histograms.values():
        if isinstance(values, list):
            total += len(values)
    return total


def _histogram_label_count(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> int:
    histograms = metrics.get("histograms", {}).get(metric_name, {})
    if not isinstance(histograms, dict):
        return 0
    total = 0
    for labels, values in histograms.items():
        try:
            label_map = dict(labels)
        except Exception:  # noqa: BLE001
            continue
        if all(label_map.get(key) == value for key, value in expected.items()):
            total += len(values) if isinstance(values, list) else 0
    return total


def _histogram_label_seen(
    metrics: dict[str, Any],
    metric_name: str,
    *,
    expected: dict[str, str],
) -> bool:
    return _histogram_label_count(metrics, metric_name, expected=expected) > 0


def _extract_task_id(tool_result: str) -> str:
    match = TASK_ID_RE.search(tool_result or "")
    if not match:
        raise RuntimeError(f"Could not parse task id from scheduler tool result: {tool_result!r}")
    return match.group(0)


def _assert_scheduler_table(session_factory) -> None:
    with session_factory() as session:
        exists = session.execute(
            text("SELECT to_regclass('public.scheduled_tasks') IS NOT NULL")
        ).scalar()
    if exists is not True:
        raise RuntimeError("public.scheduled_tasks table is missing; run migrations first")


def _load_task_row(session_factory, task_id: str) -> dict[str, Any] | None:
    with session_factory() as session:
        row = session.execute(
            text(
                "SELECT id, status, run_count, next_run, last_run, organization_id "
                "FROM scheduled_tasks WHERE id = :task_id"
            ),
            {"task_id": task_id},
        ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]) if row[0] else None,
        "status": row[1],
        "run_count": row[2],
        "next_run": str(row[3]) if row[3] else None,
        "last_run": str(row[4]) if row[4] else None,
        "organization_id": str(row[5]) if row[5] else None,
    }


def _delete_task_row(session_factory, task_id: str, organization_id: str) -> bool:
    with session_factory() as session:
        result = session.execute(
            text(
                "DELETE FROM scheduled_tasks "
                "WHERE id = :task_id AND organization_id = :organization_id"
            ),
            {"task_id": task_id, "organization_id": organization_id},
        )
        session.commit()
        return result.rowcount > 0


def _cleanup_summary(
    *,
    requested: bool,
    deleted: bool,
    task_id: str | None,
) -> dict[str, Any]:
    task_hash = _hash(task_id)
    return {
        "requested": requested,
        "deleted": deleted,
        "task_id_hash_present": bool(task_hash),
        "raw_task_id_included": False,
        "raw_organization_identifier_included": False,
        "identifier_strategy": "hash_only",
    }


def _replay_contract_summary() -> dict[str, Any]:
    return {
        "schema_version": "wiii.scheduler_replay_contract.v1",
        "uses_scheduler_tool": True,
        "uses_scoped_repository_poll": True,
        "executor_observability_path_used": True,
        "websocket_adapter_delivery_used": True,
        "single_created_task_executed": True,
        "cleanup_required_by_default": True,
        "hash_count_only_output": True,
        "raw_scheduler_tool_result_included": False,
    }


def _database_lifecycle_contract(
    *,
    created_row: dict[str, Any],
    completed_row: dict[str, Any] | None,
    organization_id: str,
) -> dict[str, Any]:
    completed_status = completed_row.get("status") if completed_row else None
    created_org_hash = _hash(created_row.get("organization_id"))
    completed_org_hash = _hash(completed_row.get("organization_id")) if completed_row else None
    return {
        "schema_version": "wiii.scheduler_database_lifecycle_contract.v1",
        "created_active_before_execution": created_row.get("status") == "active",
        "created_row_org_hash_present": bool(created_org_hash),
        "created_row_matches_scope": created_row.get("organization_id") == organization_id,
        "completed_row_present": completed_row is not None,
        "completed_status_final": completed_status == "completed",
        "created_to_completed_transition": (
            created_row.get("status") == "active" and completed_status == "completed"
        ),
        "completed_run_count_positive": int(
            (completed_row or {}).get("run_count") or 0
        )
        >= 1,
        "completed_last_run_present": bool(completed_row and completed_row.get("last_run")),
        "completed_next_run_is_null": (
            completed_row is not None and completed_row.get("next_run") is None
        ),
        "completed_org_hash_matches_created": bool(created_org_hash)
        and created_org_hash == completed_org_hash,
        "raw_database_row_included": False,
    }


def _delivery_contract(delivery_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wiii.scheduler_delivery_contract.v1",
        "websocket_channel_used": delivery_summary.get("channel") == "websocket",
        "scheduled_task_payload_used": delivery_summary.get("payload_type")
        == "scheduled_task",
        "notification_mode_used": delivery_summary.get("payload_mode")
        == "notification",
        "socket_delivery_count_positive": int(
            delivery_summary.get("socket_message_count") or 0
        )
        >= 1,
        "payload_task_hash_matches_created": delivery_summary.get(
            "payload_task_id_matches_created"
        )
        is True,
        "payload_content_hash_matches_response": delivery_summary.get(
            "payload_content_matches_response_hash"
        )
        is True,
        "raw_delivery_payload_included": False,
    }


def _get_path(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return current


def _assert_scheduler_replay_summary(summary: dict[str, Any]) -> None:
    errors: list[str] = []
    if summary.get("status") != "pass":
        errors.append("status")

    required_true_paths = (
        ("scope", "user_id_hash_present"),
        ("scope", "session_id_hash_present"),
        ("scope", "organization_id_hash_present"),
        ("scope", "request_org_context_set"),
        ("database", "task_id_hash_present"),
        ("database", "created_row_org_hash_present"),
        ("database", "created_row_matches_scope"),
        ("database", "completed_row_present"),
        ("database", "completed_last_run_present"),
        ("database", "completed_next_run_is_null"),
        ("clock", "due_poll_seen"),
        ("clock", "due_poll_scoped"),
        ("clock", "due_task_found_by_hash"),
        ("execution", "description_hash_present"),
        ("execution", "response_hash_present"),
        ("execution", "response_matches_description"),
        ("delivery", "delivered"),
        ("delivery", "socket_accepted"),
        ("delivery", "payload_task_id_hash_present"),
        ("delivery", "payload_task_id_matches_created"),
        ("delivery", "payload_content_hash_present"),
        ("delivery", "payload_content_matches_response_hash"),
        ("metrics", "poll_success_seen"),
        ("metrics", "run_success_seen"),
        ("metrics", "delivery_delivered_seen"),
        ("metrics", "duration_success_seen"),
        ("replay_contract", "uses_scheduler_tool"),
        ("replay_contract", "uses_scoped_repository_poll"),
        ("replay_contract", "executor_observability_path_used"),
        ("replay_contract", "websocket_adapter_delivery_used"),
        ("replay_contract", "single_created_task_executed"),
        ("replay_contract", "cleanup_required_by_default"),
        ("replay_contract", "hash_count_only_output"),
        ("database_lifecycle_contract", "created_active_before_execution"),
        ("database_lifecycle_contract", "created_row_org_hash_present"),
        ("database_lifecycle_contract", "created_row_matches_scope"),
        ("database_lifecycle_contract", "completed_row_present"),
        ("database_lifecycle_contract", "completed_status_final"),
        ("database_lifecycle_contract", "created_to_completed_transition"),
        ("database_lifecycle_contract", "completed_run_count_positive"),
        ("database_lifecycle_contract", "completed_last_run_present"),
        ("database_lifecycle_contract", "completed_next_run_is_null"),
        ("database_lifecycle_contract", "completed_org_hash_matches_created"),
        ("delivery_contract", "websocket_channel_used"),
        ("delivery_contract", "scheduled_task_payload_used"),
        ("delivery_contract", "notification_mode_used"),
        ("delivery_contract", "socket_delivery_count_positive"),
        ("delivery_contract", "payload_task_hash_matches_created"),
        ("delivery_contract", "payload_content_hash_matches_response"),
    )
    for path in required_true_paths:
        if _get_path(summary, path) is not True:
            errors.append(".".join(path))

    cleanup = summary.get("cleanup") if isinstance(summary.get("cleanup"), dict) else {}
    if cleanup.get("requested") is True and cleanup.get("deleted") is not True:
        errors.append("cleanup.deleted")
    for path in (
        ("clock", "due_poll_allow_all_orgs"),
        ("execution", "raw_description_included"),
        ("delivery", "payload_raw_content_included"),
        ("replay_contract", "raw_scheduler_tool_result_included"),
        ("database_lifecycle_contract", "raw_database_row_included"),
        ("delivery_contract", "raw_delivery_payload_included"),
        ("metrics", "raw_metric_payload_included"),
        ("cleanup", "raw_task_id_included"),
        ("cleanup", "raw_organization_identifier_included"),
    ):
        if _get_path(summary, path) is not False:
            errors.append(".".join(path))

    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    for key in (
        "poll_success_count",
        "due_event_count",
        "runs_event_count",
        "run_success_count",
        "delivery_event_count",
        "delivery_delivered_count",
        "duration_event_count",
        "duration_success_count",
    ):
        if int(metrics.get(key) or 0) < 1:
            errors.append(f"metrics.{key}")

    privacy = summary.get("privacy") if isinstance(summary.get("privacy"), dict) else {}
    for key in (
        "raw_content_included",
        "raw_task_id_included",
        "raw_user_identifier_included",
        "raw_session_identifier_included",
        "raw_organization_identifier_included",
        "raw_description_included",
        "raw_delivery_payload_included",
        "raw_metric_payload_included",
        "raw_database_row_included",
    ):
        if privacy.get(key) is not False:
            errors.append(f"privacy.{key}")
    if privacy.get("identifier_strategy") != "hash_or_count_only":
        errors.append("privacy.identifier_strategy")

    if errors:
        raise RuntimeError(f"Scheduler replay evidence contract failed: {errors}")


async def _run_replay(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_write(args)

    from app.api.v1 import websocket as websocket_module
    from app.core.config import settings
    from app.core.database import get_shared_session_factory, test_connection
    from app.core.org_context import current_org_id
    from app.engine.runtime import runtime_metrics as rm
    from app.engine.tools import scheduler_tools as scheduler_tools_module
    from app.engine.tools.scheduler_tools import set_scheduler_user, tool_schedule_reminder
    from app.repositories.scheduler_repository import get_scheduler_repository
    from app.services import notification_dispatcher as dispatcher_module
    from app.services import scheduled_task_executor as executor_module
    from app.services.notification_dispatcher import NotificationDispatcher
    from app.services.notifications.adapters.websocket import WebSocketAdapter
    from app.services.notifications.registry import NotificationChannelRegistry
    from app.services.scheduled_task_executor import ScheduledTaskExecutor

    if not test_connection():
        raise RuntimeError("Database connection failed")

    session_factory = get_shared_session_factory()
    _assert_scheduler_table(session_factory)
    rm._reset_for_tests()

    repo = get_scheduler_repository()
    executor = ScheduledTaskExecutor()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=args.delay_seconds)
    description = args.description

    manager = websocket_module.ConnectionManager()
    socket = CapturingWebSocket()
    await manager.connect(socket, args.session_id)
    manager.register_user(args.user_id, args.organization_id, args.organization_id)

    registry = NotificationChannelRegistry()
    registry.register(WebSocketAdapter())
    dispatcher = NotificationDispatcher()
    dispatcher._registry = registry

    old_manager = websocket_module.manager
    old_dispatcher = dispatcher_module._dispatcher
    org_token = current_org_id.set(args.organization_id)
    scheduler_tools_module._scheduler_tool_state.set(None)
    created_task_id: str | None = None
    cleaned_up = False
    summary: dict[str, Any] | None = None
    try:
        websocket_module.manager = manager
        dispatcher_module._dispatcher = dispatcher
        manager.register_user(args.session_id, args.user_id, args.organization_id)
        set_scheduler_user(args.user_id, args.domain_id)

        tool_result = tool_schedule_reminder.invoke(
            {
                "description": description,
                "when": run_at.isoformat(),
            }
        )
        created_task_id = _extract_task_id(str(tool_result))

        created_row = _load_task_row(session_factory, created_task_id)
        if created_row is None:
            raise RuntimeError("Scheduler tool returned a task id but no database row exists")
        if created_row["organization_id"] != args.organization_id:
            raise RuntimeError(
                "Created task did not persist the expected organization_id"
            )

        now = datetime.now(timezone.utc)
        if run_at > now:
            await asyncio.sleep((run_at - now).total_seconds() + args.settle_seconds)

        try:
            due_tasks = repo.get_due_tasks(
                limit=10,
                organization_id=args.organization_id,
                allow_all_orgs=False,
            )
        except Exception:
            executor_module._emit_poll_metric("error")
            raise
        executor_module._emit_poll_metric("success")
        executor_module._emit_due_metric(len(due_tasks))
        due_task = next((task for task in due_tasks if task.get("id") == created_task_id), None)
        if due_task is None:
            raise RuntimeError("Created task was not returned by scoped due-task poll")

        execution_outcome = await executor._execute_due_task_with_observability(
            due_task,
            repo=repo,
            dispatcher=dispatcher,
        )
        if execution_outcome.get("status") != "success":
            raise RuntimeError(f"Task execution failed: {execution_outcome!r}")
        result = execution_outcome.get("result") or {}
        delivery = execution_outcome.get("delivery") or {}

        completed_row = _load_task_row(session_factory, created_task_id)
        sent_payload = json.loads(socket.sent_texts[-1]) if socket.sent_texts else {}
        metrics = rm.snapshot()
        expected_mode = "notification"
        response_text = result.get("response") if isinstance(result, dict) else None
        payload_content = sent_payload.get("content")
        description_hash = _hash(description)
        response_hash = _hash(response_text)
        payload_content_hash = _hash(payload_content)
        poll_success_count = _metric_label_count(
            metrics,
            POLL_METRIC,
            expected={"status": "success"},
        )
        run_success_count = _metric_label_count(
            metrics,
            RUNS_METRIC,
            expected={"mode": expected_mode, "status": "success"},
        )
        delivery_delivered_count = _metric_label_count(
            metrics,
            DELIVERY_METRIC,
            expected={"mode": expected_mode, "status": "delivered"},
        )
        duration_success_count = _histogram_label_count(
            metrics,
            DURATION_METRIC,
            expected={"mode": expected_mode, "status": "success"},
        )
        summary = {
            "status": "pass",
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "replay_contract": _replay_contract_summary(),
            "scope": {
                "organization_context": "request_scoped",
                "request_org_context_set": current_org_id.get() == args.organization_id,
                "user_id_hash": _hash(args.user_id),
                "user_id_hash_present": bool(_hash(args.user_id)),
                "session_id_hash": _hash(args.session_id),
                "session_id_hash_present": bool(_hash(args.session_id)),
                "organization_id_hash": _hash(args.organization_id),
                "organization_id_hash_present": bool(_hash(args.organization_id)),
                "domain_id": args.domain_id,
            },
            "database": {
                "url_present": bool(
                    getattr(settings, "database_url", "")
                    or getattr(settings, "postgres_url_sync", "")
                ),
                "scheduled_tasks_table": "present",
                "task_id_hash": _hash(created_task_id),
                "task_id_hash_present": bool(_hash(created_task_id)),
                "created_status": created_row["status"],
                "created_row_org_hash": _hash(created_row.get("organization_id")),
                "created_row_org_hash_present": bool(
                    _hash(created_row.get("organization_id"))
                ),
                "created_row_matches_scope": (
                    created_row.get("organization_id") == args.organization_id
                ),
                "completed_row_present": completed_row is not None,
                "completed_status": completed_row["status"] if completed_row else None,
                "completed_run_count": completed_row["run_count"] if completed_row else None,
                "completed_last_run_present": bool(
                    completed_row and completed_row.get("last_run")
                ),
                "completed_next_run_is_null": (
                    completed_row is not None and completed_row.get("next_run") is None
                ),
                "organization_id_hash": _hash(args.organization_id),
                "organization_id_hash_present": bool(_hash(args.organization_id)),
            },
            "database_lifecycle_contract": _database_lifecycle_contract(
                created_row=created_row,
                completed_row=completed_row,
                organization_id=args.organization_id,
            ),
            "clock": {
                "scheduled_for": run_at.isoformat(),
                "due_poll_seen": True,
                "due_poll_scoped": True,
                "due_poll_allow_all_orgs": False,
                "due_poll_limit": 10,
                "due_task_count": len(due_tasks),
                "due_task_found_by_hash": any(
                    _hash(task.get("id")) == _hash(created_task_id)
                    for task in due_tasks
                ),
            },
            "execution": {
                "mode": result.get("mode"),
                "status": execution_outcome.get("status"),
                "description_hash": description_hash,
                "description_hash_present": bool(description_hash),
                "response_hash": response_hash,
                "response_hash_present": bool(response_hash),
                "response_char_count": len(str(response_text or "")),
                "response_matches_description": result.get("response") == description,
                "raw_description_included": False,
            },
            "delivery": {
                "delivered": delivery.get("delivered") is True,
                "channel": delivery.get("channel"),
                "socket_accepted": socket.accepted,
                "socket_message_count": len(socket.sent_texts),
                "payload_type": sent_payload.get("type"),
                "payload_mode": sent_payload.get("mode"),
                "payload_task_id_hash": _hash(sent_payload.get("task_id")),
                "payload_task_id_hash_present": bool(
                    _hash(sent_payload.get("task_id"))
                ),
                "payload_task_id_matches_created": (
                    _hash(sent_payload.get("task_id")) == _hash(created_task_id)
                ),
                "payload_content_hash": payload_content_hash,
                "payload_content_hash_present": bool(payload_content_hash),
                "payload_content_char_count": len(str(payload_content or "")),
                "payload_content_matches_response_hash": (
                    payload_content_hash == response_hash
                ),
                "payload_raw_content_included": False,
            },
            "delivery_contract": _delivery_contract(
                {
                    "channel": delivery.get("channel"),
                    "payload_type": sent_payload.get("type"),
                    "payload_mode": sent_payload.get("mode"),
                    "socket_message_count": len(socket.sent_texts),
                    "payload_task_id_matches_created": (
                        _hash(sent_payload.get("task_id")) == _hash(created_task_id)
                    ),
                    "payload_content_matches_response_hash": (
                        payload_content_hash == response_hash
                    ),
                }
            ),
            "metrics": {
                "counter_names_present": sorted(metrics.get("counters", {}).keys()),
                "histogram_names_present": sorted(metrics.get("histograms", {}).keys()),
                "polls": _metric_counter_map(metrics, POLL_METRIC),
                "due": _metric_counter_map(metrics, DUE_METRIC),
                "runs": _metric_counter_map(metrics, RUNS_METRIC),
                "delivery": _metric_counter_map(metrics, DELIVERY_METRIC),
                "poll_success_count": poll_success_count,
                "poll_success_seen": poll_success_count > 0,
                "due_event_count": _metric_event_count(metrics, DUE_METRIC),
                "runs_event_count": _metric_event_count(metrics, RUNS_METRIC),
                "run_success_count": run_success_count,
                "run_success_seen": _metric_label_seen(
                    metrics,
                    RUNS_METRIC,
                    expected={"mode": expected_mode, "status": "success"},
                ),
                "delivery_event_count": _metric_event_count(
                    metrics,
                    DELIVERY_METRIC,
                ),
                "delivery_delivered_count": delivery_delivered_count,
                "delivery_delivered_seen": _metric_label_seen(
                    metrics,
                    DELIVERY_METRIC,
                    expected={"mode": expected_mode, "status": "delivered"},
                ),
                "duration_event_count": _histogram_event_count(
                    metrics,
                    DURATION_METRIC,
                ),
                "duration_success_count": duration_success_count,
                "duration_success_seen": _histogram_label_seen(
                    metrics,
                    DURATION_METRIC,
                    expected={"mode": expected_mode, "status": "success"},
                ),
                "metric_label_strategy": "bounded_mode_status_only",
                "raw_metric_payload_included": False,
            },
            "privacy": {
                "raw_content_included": False,
                "raw_task_id_included": False,
                "raw_user_identifier_included": False,
                "raw_session_identifier_included": False,
                "raw_organization_identifier_included": False,
                "raw_description_included": False,
                "raw_delivery_payload_included": False,
                "raw_metric_payload_included": False,
                "raw_database_row_included": False,
                "identifier_strategy": "hash_or_count_only",
            },
        }

        if not summary["delivery"]["delivered"]:
            raise RuntimeError(f"Notification delivery failed: {delivery!r}")
        if completed_row is None or completed_row["status"] != "completed":
            raise RuntimeError(f"Task was not marked completed: {completed_row!r}")
    finally:
        scheduler_tools_module._scheduler_tool_state.set(None)
        current_org_id.reset(org_token)
        websocket_module.manager = old_manager
        dispatcher_module._dispatcher = old_dispatcher
        if created_task_id and not args.keep_task:
            cleaned_up = _delete_task_row(session_factory, created_task_id, args.organization_id)
            if args.verbose:
                _json_print({"cleanup": {"task_id_hash": _hash(created_task_id), "deleted": cleaned_up}})
        if summary is not None:
            summary["cleanup"] = _cleanup_summary(
                requested=not args.keep_task,
                deleted=cleaned_up,
                task_id=created_task_id,
            )

    if summary is None:
        raise RuntimeError("Scheduler replay did not produce summary")
    if created_task_id and not args.keep_task and not cleaned_up:
        raise RuntimeError("Scheduled task cleanup failed")
    _assert_scheduler_replay_summary(summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opt-in live scheduled-task replay using the real Postgres scheduler repository.",
    )
    parser.add_argument("--allow-write", action="store_true", help="Permit the probe to insert one scheduled task row.")
    parser.add_argument("--allow-production", action="store_true", help="Permit running against settings.environment=production.")
    parser.add_argument("--keep-task", action="store_true", help="Leave the completed task row in the database.")
    parser.add_argument("--verbose", action="store_true", help="Print cleanup details.")
    parser.add_argument("--user-id", default="scheduled-live-replay-user")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--domain-id", default="maritime")
    parser.add_argument("--session-id", default="scheduled-live-replay-session")
    parser.add_argument("--description", default="Live replay reminder from Wiii scheduler probe")
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = await _run_replay(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_json_payload(_failure_payload(exc, args), args.out)
        return 1
    emit_json_payload(result, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(list(argv or sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
