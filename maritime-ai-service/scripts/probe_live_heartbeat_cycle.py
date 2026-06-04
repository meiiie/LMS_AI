"""Opt-in live heartbeat-cycle probe.

This probe runs a controlled heartbeat cycle through Wiii's living-agent
runtime and verifies durable, org-scoped side effects with hash/count-only
evidence. It is intentionally guarded because it can call the local living-agent
LLM and write journal, reflection, briefing, heartbeat-audit, emotional-state,
and optional proactive-message rows.

Example:
    WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1 python scripts/probe_live_heartbeat_cycle.py --allow-write --out autonomy-heartbeat-evidence.json

Optional proactive WebSocket side effect:
    WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1 python scripts/probe_live_heartbeat_cycle.py --allow-write --include-proactive-websocket --out autonomy-heartbeat-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


ENV_FLAG = "WIII_LIVE_HEARTBEAT_CYCLE_PROBE"
SCHEMA_VERSION = "wiii.live_heartbeat_cycle_probe.v1"
HEARTBEAT_CYCLES_METRIC = "runtime.living_agent.heartbeat.cycles"
HEARTBEAT_CYCLE_DURATION_METRIC = "runtime.living_agent.heartbeat.duration_ms"
HEARTBEAT_ACTIONS_METRIC = "runtime.living_agent.heartbeat.actions"
HEARTBEAT_ACTION_DURATION_METRIC = "runtime.living_agent.heartbeat.action_duration_ms"
PROACTIVE_CAN_SEND_METRIC = "runtime.living_agent.proactive.can_send"
PROACTIVE_SENDS_METRIC = "runtime.living_agent.proactive.sends"
DEFAULT_USER_ID = "live-heartbeat-probe-user"
DEFAULT_ORG_ID = f"live-heartbeat-probe-{uuid.uuid4().hex[:12]}"
DEFAULT_SESSION_ID = f"live-heartbeat-probe-session-{uuid.uuid4().hex[:12]}"
CORE_TABLES = (
    "wiii_heartbeat_audit",
    "wiii_emotional_snapshots",
    "wiii_journal",
    "wiii_reflections",
    "wiii_briefings",
)
PROACTIVE_TABLES = (
    "wiii_proactive_messages",
    "wiii_proactive_preferences",
)
COUNTED_TABLES = (*CORE_TABLES, "wiii_proactive_messages")
ALLOWED_TABLES = {*CORE_TABLES, *PROACTIVE_TABLES}
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    text = IDENTIFIER_RE.sub(
        lambda match: _fallback_hash(match.group(0)) or "<redacted-identifier>",
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
        "error_code": "heartbeat_cycle_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_action_target_included": False,
            "raw_action_metadata_values_included": False,
            "raw_briefing_content_included": False,
            "raw_socket_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_rows_included": False,
            "raw_emotional_state_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(token)


def _require_live_write(args: argparse.Namespace) -> None:
    if not args.allow_write:
        raise SystemExit(
            "--allow-write is required; this probe writes living-agent runtime rows"
        )
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live heartbeat-cycle probe")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to write to production without --allow-production")


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


def _action_contract_summary(
    *,
    planned_actions: list[Any],
    recorded_actions: list[Any],
    include_proactive_websocket: bool,
    skip_briefing_audit: bool,
) -> dict[str, Any]:
    planned_names = sorted(_action_type_names(planned_actions))
    recorded_names = sorted(_action_type_names(recorded_actions))
    required_names = {"reflect", "write_journal"}
    return {
        "schema_version": "wiii.heartbeat_lifecycle_contract.v1",
        "controlled_plan_used": True,
        "scheduler_execute_heartbeat_used": True,
        "prompt_patch_dependency": False,
        "required_actions_planned": required_names.issubset(set(planned_names)),
        "required_actions_recorded": required_names.issubset(set(recorded_names)),
        "planned_recorded_action_count_matches": len(planned_actions)
        == len(recorded_actions),
        "planned_recorded_action_types_match": planned_names == recorded_names,
        "briefing_audit_write_explicit": not skip_briefing_audit,
        "proactive_websocket_requires_explicit_flag": True,
        "proactive_websocket_requested": include_proactive_websocket,
        "hash_count_only_output": True,
        "raw_action_metadata_values_absent": True,
        "raw_action_targets_absent": True,
    }


def _database_scope_contract(
    *,
    scope: Any,
    required_tables: tuple[str, ...],
    counted_tables: tuple[str, ...],
    deltas: dict[str, dict[str, int]],
    include_proactive_websocket: bool,
) -> dict[str, Any]:
    counted_names = sorted(counted_tables)
    required_names = sorted(required_tables)
    proactive_delta = int(
        deltas.get("wiii_proactive_messages", {}).get("delta", 0)
    )
    return {
        "schema_version": "wiii.heartbeat_database_scope_contract.v1",
        "request_org_context_set": getattr(scope, "state", None) == "request_scoped",
        "required_table_count": len(required_names),
        "counted_table_count": len(counted_names),
        "counted_table_count_matches_deltas": len(counted_names) == len(deltas),
        "core_table_set_checked": all(table in required_names for table in CORE_TABLES),
        "heartbeat_audit_delta_observed": int(
            deltas.get("wiii_heartbeat_audit", {}).get("delta", 0)
        )
        >= 1,
        "briefing_delta_observed": int(
            deltas.get("wiii_briefings", {}).get("delta", 0)
        )
        >= 1,
        "reflection_scope_observed": int(
            deltas.get("wiii_reflections", {}).get("after", 0)
        )
        >= 1,
        "journal_scope_observed": int(deltas.get("wiii_journal", {}).get("after", 0))
        >= 1,
        "proactive_websocket_requested": include_proactive_websocket,
        "proactive_message_delta_observed_when_requested": (
            not include_proactive_websocket or proactive_delta >= 1
        ),
        "raw_table_rows_included": False,
        "raw_sql_payload_included": False,
    }


def _safe_action_summary(action: Any) -> dict[str, Any]:
    metadata = getattr(action, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    action_type = getattr(getattr(action, "action_type", None), "value", None)
    target = str(getattr(action, "target", "") or "")
    target_hash = _hash(target)
    return {
        "action_type": str(action_type or ""),
        "target_present": bool(target),
        "target_hash": target_hash,
        "target_hash_present": bool(target_hash),
        "priority": round(float(getattr(action, "priority", 0.0) or 0.0), 3),
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
        "metadata_key_count": len(metadata),
        "metadata_values_included": False,
        "raw_target_included": False,
    }


def _action_type_names(actions: list[Any]) -> list[str]:
    return [
        summary["action_type"]
        for summary in (_safe_action_summary(action) for action in actions)
        if summary["action_type"]
    ]


def _has_action_type(actions: list[Any], action_type: str) -> bool:
    return action_type in set(_action_type_names(actions))


def _assert_known_table(table: str) -> None:
    if table not in ALLOWED_TABLES:
        raise RuntimeError(f"Unexpected table name for heartbeat probe: {table!r}")


def _assert_tables(session_factory: Any, tables: tuple[str, ...]) -> None:
    missing: list[str] = []
    with session_factory() as session:
        for table in tables:
            _assert_known_table(table)
            exists = session.execute(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": f"public.{table}"},
            ).scalar()
            if exists is not True:
                missing.append(table)
    if missing:
        raise RuntimeError(
            "Missing living-agent tables; run migrations first: "
            + ", ".join(sorted(missing))
        )


def _count_table_rows(
    session_factory: Any,
    table: str,
    *,
    organization_id: str,
    user_id: str,
) -> int:
    _assert_known_table(table)
    where = "organization_id = :org_id"
    params: dict[str, Any] = {"org_id": organization_id}
    if table == "wiii_proactive_messages":
        where += " AND user_id = :user_id"
        params["user_id"] = user_id
    with session_factory() as session:
        return int(
            session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {where}"),
                params,
            ).scalar()
            or 0
        )


def _count_tables(
    session_factory: Any,
    *,
    organization_id: str,
    user_id: str,
    tables: tuple[str, ...] = COUNTED_TABLES,
) -> dict[str, int]:
    return {
        table: _count_table_rows(
            session_factory,
            table,
            organization_id=organization_id,
            user_id=user_id,
        )
        for table in tables
    }


def _table_deltas(
    before: dict[str, int],
    after: dict[str, int],
) -> dict[str, dict[str, int]]:
    return {
        table: {
            "before": int(before.get(table, 0)),
            "after": int(after.get(table, 0)),
            "delta": int(after.get(table, 0)) - int(before.get(table, 0)),
        }
        for table in sorted(set(before) | set(after))
    }


def _build_controlled_actions(args: argparse.Namespace) -> list[Any]:
    from app.engine.living_agent.models import ActionType, HeartbeatAction

    actions: list[Any] = []
    if not args.skip_reflection:
        actions.append(
            HeartbeatAction(
                action_type=ActionType.REFLECT,
                priority=0.9,
                metadata={"probe": "live_heartbeat_cycle"},
            )
        )
    if not args.skip_journal:
        actions.append(
            HeartbeatAction(
                action_type=ActionType.WRITE_JOURNAL,
                priority=0.8,
                metadata={"probe": "live_heartbeat_cycle"},
            )
        )
    if args.include_proactive_websocket:
        actions.append(
            HeartbeatAction(
                action_type=ActionType.SEND_BRIEFING,
                target=f"reengage:{args.user_id}",
                priority=0.7,
                metadata={
                    "channel": "websocket",
                    "probe": "live_heartbeat_cycle",
                },
            )
        )
    return actions


@contextlib.asynccontextmanager
async def _patched_websocket_delivery(
    args: argparse.Namespace,
    *,
    effective_org_id: str,
):
    if not args.include_proactive_websocket:
        yield None
        return

    from app.api.v1 import websocket as websocket_module
    from app.services import notification_dispatcher as dispatcher_module
    from app.services.notification_dispatcher import NotificationDispatcher
    from app.services.notifications.adapters.websocket import WebSocketAdapter
    from app.services.notifications.registry import NotificationChannelRegistry

    manager = websocket_module.ConnectionManager()
    socket = CapturingWebSocket()
    await manager.connect(socket, args.session_id)
    manager.register_user(args.session_id, args.user_id, effective_org_id)

    registry = NotificationChannelRegistry()
    registry.register(WebSocketAdapter())
    dispatcher = NotificationDispatcher()
    dispatcher._registry = registry

    old_manager = websocket_module.manager
    old_dispatcher = dispatcher_module._dispatcher
    try:
        websocket_module.manager = manager
        dispatcher_module._dispatcher = dispatcher
        yield socket
    finally:
        websocket_module.manager = old_manager
        dispatcher_module._dispatcher = old_dispatcher


def _assert_proactive_ready(args: argparse.Namespace) -> None:
    if not args.include_proactive_websocket:
        return
    from app.core.config import settings

    if not getattr(settings, "living_agent_enable_proactive_messaging", False):
        raise RuntimeError(
            "living_agent_enable_proactive_messaging is disabled; enable it or "
            "omit --include-proactive-websocket"
        )


async def _run_controlled_heartbeat(
    args: argparse.Namespace,
) -> tuple[Any, list[Any]]:
    from app.engine.living_agent.heartbeat import HeartbeatScheduler

    scheduler = HeartbeatScheduler()
    actions = _build_controlled_actions(args)
    old_plan_actions = scheduler._plan_actions

    async def controlled_plan_actions(mood: str, energy: float) -> list[Any]:
        return actions

    scheduler._plan_actions = controlled_plan_actions
    try:
        result = await asyncio.wait_for(
            scheduler._execute_heartbeat(),
            timeout=args.cycle_timeout,
        )
    finally:
        scheduler._plan_actions = old_plan_actions
    return result, actions


async def _compose_and_save_briefing(
    args: argparse.Namespace,
    *,
    effective_org_id: str,
) -> dict[str, Any]:
    if args.skip_briefing_audit:
        return {
            "status": "skipped",
            "reason": "briefing audit write disabled by --skip-briefing-audit",
        }

    from app.engine.living_agent.briefing_composer import get_briefing_composer
    from app.engine.living_agent.models import BriefingType
    from app.engine.semantic_memory.write_audit import MemoryWriteScope

    composer = get_briefing_composer()
    scope = MemoryWriteScope(
        org_id=effective_org_id,
        state="operator_probe_explicit",
        warnings=[],
        write_allowed=True,
    )
    briefing_type = BriefingType(args.briefing_type)
    if briefing_type == BriefingType.MORNING:
        compose = composer._compose_morning
    elif briefing_type == BriefingType.EVENING:
        compose = composer._compose_evening
    else:
        compose = composer._compose_midday

    briefing = await asyncio.wait_for(compose(scope=scope), timeout=args.action_timeout)
    if not briefing:
        raise RuntimeError("Briefing composer returned no briefing")
    briefing.organization_id = effective_org_id
    composer._save_briefing(briefing, scope=scope)
    content_hash = _hash(briefing.content)

    return {
        "status": "pass",
        "briefing_id_hash": _hash(str(briefing.id)),
        "briefing_id_hash_present": bool(_hash(str(briefing.id))),
        "briefing_type": briefing.briefing_type.value,
        "content_hash": content_hash,
        "content_hash_present": bool(content_hash),
        "content_char_count": len(briefing.content or ""),
        "weather_summary_char_count": len(briefing.weather_summary or ""),
        "news_highlight_count": len(briefing.news_highlights or []),
        "delivered_count": len(briefing.delivered_to or []),
        "raw_content_included": False,
    }


def _safe_socket_summary(socket: CapturingWebSocket | None) -> dict[str, Any]:
    if socket is None:
        return {
            "status": "skipped",
            "reason": "pass --include-proactive-websocket to exercise re-engagement delivery",
            "raw_content_included": False,
            "payload_raw_content_included": False,
        }
    payload: dict[str, Any] = {}
    if socket.sent_texts:
        try:
            parsed = json.loads(socket.sent_texts[-1])
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    content_hash = _hash(payload.get("content"))
    return {
        "status": "observed" if socket.sent_texts else "missing_delivery",
        "socket_accepted": bool(socket.accepted),
        "socket_message_count": len(socket.sent_texts),
        "payload_type": payload.get("type"),
        "payload_trigger": payload.get("trigger"),
        "payload_content_hash": content_hash,
        "payload_content_hash_present": bool(content_hash),
        "payload_content_char_count": len(str(payload.get("content") or "")),
        "raw_content_included": False,
        "payload_raw_content_included": False,
    }


def _assert_probe_evidence(summary: dict[str, Any], args: argparse.Namespace) -> None:
    deltas = summary["database"]["deltas"]
    if deltas["wiii_heartbeat_audit"]["delta"] < 1:
        raise RuntimeError("Heartbeat cycle did not persist a heartbeat audit row")
    if not args.skip_reflection and deltas["wiii_reflections"]["after"] < 1:
        raise RuntimeError("Reflection action did not leave org-scoped reflection evidence")
    if not args.skip_journal and deltas["wiii_journal"]["after"] < 1:
        raise RuntimeError("Journal action did not leave org-scoped journal evidence")
    if not args.skip_briefing_audit and deltas["wiii_briefings"]["delta"] < 1:
        raise RuntimeError("Briefing audit path did not persist a briefing row")
    if args.include_proactive_websocket:
        if deltas["wiii_proactive_messages"]["delta"] < 1:
            raise RuntimeError("Proactive WebSocket path did not persist a message row")
        if summary["proactive_websocket"]["socket_message_count"] < 1:
            raise RuntimeError("Proactive WebSocket path did not deliver to the probe socket")


def _get_path(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return current


def _assert_heartbeat_summary_contract(
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    errors: list[str] = []
    if summary.get("status") != "pass":
        errors.append("status")

    required_true_paths = (
        ("scope", "requested_organization_id_hash_present"),
        ("scope", "effective_organization_id_hash_present"),
        ("scope", "requested_matches_effective_org"),
        ("scope", "user_id_hash_present"),
        ("scope", "session_id_hash_present"),
        ("heartbeat_cycle", "cycle_id_hash_present"),
        ("heartbeat_cycle", "reflect_planned"),
        ("heartbeat_cycle", "write_journal_planned"),
        ("heartbeat_cycle", "reflect_recorded"),
        ("heartbeat_cycle", "write_journal_recorded"),
        ("briefing", "briefing_id_hash_present"),
        ("briefing", "content_hash_present"),
        ("metrics", "heartbeat_cycle_success_seen"),
        ("metrics", "heartbeat_cycle_duration_success_seen"),
        ("metrics", "heartbeat_reflect_success_seen"),
        ("metrics", "heartbeat_write_journal_success_seen"),
        ("metrics", "heartbeat_action_duration_success_seen"),
        ("metrics", "heartbeat_reflect_duration_success_seen"),
        ("metrics", "heartbeat_write_journal_duration_success_seen"),
    )
    for path in required_true_paths:
        if _get_path(summary, path) is not True:
            errors.append(".".join(path))

    false_paths = (
        ("heartbeat_cycle", "is_noop"),
        ("heartbeat_cycle", "error_present"),
        ("heartbeat_cycle", "raw_action_payload_included"),
        ("briefing", "raw_content_included"),
        ("proactive_websocket", "raw_content_included"),
        ("proactive_websocket", "payload_raw_content_included"),
    )
    for path in false_paths:
        if _get_path(summary, path) is not False:
            errors.append(".".join(path))

    if summary.get("scope", {}).get("organization_context") != "request_scoped":
        errors.append("scope.organization_context")
    if summary.get("scope", {}).get("warnings") != []:
        errors.append("scope.warnings")

    heartbeat = summary.get("heartbeat_cycle", {})
    if int(heartbeat.get("planned_action_count") or 0) < 2:
        errors.append("heartbeat_cycle.planned_action_count")
    if int(heartbeat.get("actions_recorded_count") or 0) < 2:
        errors.append("heartbeat_cycle.actions_recorded_count")
    for collection_key in ("planned_actions", "actions_recorded"):
        actions = heartbeat.get(collection_key)
        if not isinstance(actions, list) or not actions:
            errors.append(f"heartbeat_cycle.{collection_key}")
            continue
        for index, action in enumerate(actions):
            if action.get("metadata_values_included") is not False:
                errors.append(f"heartbeat_cycle.{collection_key}.{index}.metadata_values_included")
            if action.get("raw_target_included") is not False:
                errors.append(f"heartbeat_cycle.{collection_key}.{index}.raw_target_included")

    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    for key, minimum in (
        ("heartbeat_cycles_event_count", 1),
        ("heartbeat_cycle_success_count", 1),
        ("heartbeat_cycle_duration_event_count", 1),
        ("heartbeat_cycle_duration_success_count", 1),
        ("heartbeat_actions_event_count", 2),
        ("heartbeat_action_success_count", 2),
        ("heartbeat_action_duration_event_count", 2),
        ("heartbeat_action_duration_success_count", 2),
        ("heartbeat_reflect_success_count", 1),
        ("heartbeat_write_journal_success_count", 1),
        ("heartbeat_reflect_duration_success_count", 1),
        ("heartbeat_write_journal_duration_success_count", 1),
    ):
        if int(metrics.get(key) or 0) < minimum:
            errors.append(f"metrics.{key}")

    privacy = summary.get("privacy") if isinstance(summary.get("privacy"), dict) else {}
    for key in (
        "raw_content_included",
        "raw_user_identifier_included",
        "raw_session_identifier_included",
        "raw_organization_identifier_included",
        "raw_action_target_included",
        "raw_action_metadata_values_included",
        "raw_briefing_content_included",
        "raw_socket_payload_included",
        "raw_metric_payload_included",
        "raw_database_rows_included",
        "raw_emotional_state_included",
    ):
        if privacy.get(key) is not False:
            errors.append(f"privacy.{key}")
    if privacy.get("identifier_strategy") != "hash_or_count_only":
        errors.append("privacy.identifier_strategy")

    lifecycle_contract = summary.get("lifecycle_contract")
    if not isinstance(lifecycle_contract, dict):
        errors.append("lifecycle_contract")
    else:
        for key in (
            "controlled_plan_used",
            "scheduler_execute_heartbeat_used",
            "required_actions_planned",
            "required_actions_recorded",
            "planned_recorded_action_count_matches",
            "planned_recorded_action_types_match",
            "briefing_audit_write_explicit",
            "proactive_websocket_requires_explicit_flag",
            "hash_count_only_output",
            "raw_action_metadata_values_absent",
            "raw_action_targets_absent",
        ):
            if lifecycle_contract.get(key) is not True:
                errors.append(f"lifecycle_contract.{key}")
        if lifecycle_contract.get("prompt_patch_dependency") is not False:
            errors.append("lifecycle_contract.prompt_patch_dependency")

    database_contract = summary.get("database_scope_contract")
    if not isinstance(database_contract, dict):
        errors.append("database_scope_contract")
    else:
        for key in (
            "request_org_context_set",
            "counted_table_count_matches_deltas",
            "core_table_set_checked",
            "heartbeat_audit_delta_observed",
            "briefing_delta_observed",
            "reflection_scope_observed",
            "journal_scope_observed",
            "proactive_message_delta_observed_when_requested",
        ):
            if database_contract.get(key) is not True:
                errors.append(f"database_scope_contract.{key}")
        for key in ("raw_table_rows_included", "raw_sql_payload_included"):
            if database_contract.get(key) is not False:
                errors.append(f"database_scope_contract.{key}")

    if args.include_proactive_websocket:
        if _get_path(summary, ("proactive_websocket", "socket_accepted")) is not True:
            errors.append("proactive_websocket.socket_accepted")
        if int(_get_path(summary, ("proactive_websocket", "socket_message_count")) or 0) < 1:
            errors.append("proactive_websocket.socket_message_count")
        if _get_path(summary, ("proactive_websocket", "payload_content_hash_present")) is not True:
            errors.append("proactive_websocket.payload_content_hash_present")

    if errors:
        raise RuntimeError(f"Heartbeat evidence contract failed: {errors}")


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_write(args)

    from app.core.database import get_shared_session_factory, test_connection
    from app.core.org_context import current_org_id
    from app.engine.runtime import runtime_metrics as rm
    from app.engine.semantic_memory.write_audit import resolve_memory_write_scope

    if not test_connection():
        raise RuntimeError("Database connection failed")

    session_factory = get_shared_session_factory()
    required_tables = CORE_TABLES + (
        PROACTIVE_TABLES if args.include_proactive_websocket else ()
    )
    counted_tables = CORE_TABLES + (
        ("wiii_proactive_messages",) if args.include_proactive_websocket else ()
    )
    _assert_tables(session_factory, required_tables)
    _assert_proactive_ready(args)

    rm._reset_for_tests()
    started = time.monotonic()
    org_token = current_org_id.set(args.organization_id)
    try:
        scope = resolve_memory_write_scope()
        if not scope.write_allowed or not scope.org_id:
            raise RuntimeError(
                "Resolved heartbeat scope does not allow writes; "
                f"scope={scope.state} warnings={sorted(scope.warnings)}"
            )
        effective_org_id = scope.org_id
        before_counts = _count_tables(
            session_factory,
            organization_id=effective_org_id,
            user_id=args.user_id,
            tables=counted_tables,
        )

        async with _patched_websocket_delivery(
            args,
            effective_org_id=effective_org_id,
        ) as socket:
            heartbeat_result, planned_actions = await _run_controlled_heartbeat(args)
            briefing = await _compose_and_save_briefing(
                args,
                effective_org_id=effective_org_id,
            )

        after_counts = _count_tables(
            session_factory,
            organization_id=effective_org_id,
            user_id=args.user_id,
            tables=counted_tables,
        )
        metrics = rm.snapshot()
        heartbeat_cycle_success_count = _metric_label_count(
            metrics,
            HEARTBEAT_CYCLES_METRIC,
            expected={"status": "success"},
        )
        heartbeat_cycle_duration_success_count = _histogram_label_count(
            metrics,
            HEARTBEAT_CYCLE_DURATION_METRIC,
            expected={"status": "success"},
        )
        heartbeat_action_success_count = _metric_label_count(
            metrics,
            HEARTBEAT_ACTIONS_METRIC,
            expected={"status": "success"},
        )
        heartbeat_reflect_success_count = _metric_label_count(
            metrics,
            HEARTBEAT_ACTIONS_METRIC,
            expected={"action_type": "reflect", "status": "success"},
        )
        heartbeat_write_journal_success_count = _metric_label_count(
            metrics,
            HEARTBEAT_ACTIONS_METRIC,
            expected={"action_type": "write_journal", "status": "success"},
        )
        heartbeat_reflect_duration_success_count = _histogram_label_count(
            metrics,
            HEARTBEAT_ACTION_DURATION_METRIC,
            expected={"action_type": "reflect", "status": "success"},
        )
        heartbeat_write_journal_duration_success_count = _histogram_label_count(
            metrics,
            HEARTBEAT_ACTION_DURATION_METRIC,
            expected={"action_type": "write_journal", "status": "success"},
        )
        heartbeat_action_duration_success_count = _histogram_label_count(
            metrics,
            HEARTBEAT_ACTION_DURATION_METRIC,
            expected={"status": "success"},
        )
        requested_org_hash = _hash(args.organization_id)
        effective_org_hash = _hash(effective_org_id)
        user_hash = _hash(args.user_id)
        session_hash = _hash(args.session_id)
        deltas = _table_deltas(before_counts, after_counts)
        summary = {
            "status": "pass",
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "scope": {
                "requested_organization_id_hash": requested_org_hash,
                "requested_organization_id_hash_present": bool(requested_org_hash),
                "effective_organization_id_hash": effective_org_hash,
                "effective_organization_id_hash_present": bool(effective_org_hash),
                "requested_matches_effective_org": requested_org_hash == effective_org_hash,
                "organization_context": scope.state,
                "warnings": sorted(scope.warnings),
                "user_id_hash": user_hash,
                "user_id_hash_present": bool(user_hash),
                "session_id_hash": session_hash,
                "session_id_hash_present": bool(session_hash),
            },
            "heartbeat_cycle": {
                "cycle_id_hash": _hash(str(heartbeat_result.cycle_id)),
                "cycle_id_hash_present": bool(_hash(str(heartbeat_result.cycle_id))),
                "is_noop": bool(heartbeat_result.is_noop),
                "error_present": bool(heartbeat_result.error),
                "duration_ms": int(heartbeat_result.duration_ms or 0),
                "planned_action_count": len(planned_actions),
                "planned_action_type_names": sorted(_action_type_names(planned_actions)),
                "reflect_planned": _has_action_type(planned_actions, "reflect"),
                "write_journal_planned": _has_action_type(
                    planned_actions,
                    "write_journal",
                ),
                "planned_actions": [_safe_action_summary(action) for action in planned_actions],
                "actions_recorded_count": len(heartbeat_result.actions_taken),
                "actions_recorded_type_names": sorted(
                    _action_type_names(heartbeat_result.actions_taken)
                ),
                "reflect_recorded": _has_action_type(
                    heartbeat_result.actions_taken,
                    "reflect",
                ),
                "write_journal_recorded": _has_action_type(
                    heartbeat_result.actions_taken,
                    "write_journal",
                ),
                "actions_recorded": [
                    _safe_action_summary(action)
                    for action in heartbeat_result.actions_taken
                ],
                "raw_action_payload_included": False,
            },
            "lifecycle_contract": _action_contract_summary(
                planned_actions=planned_actions,
                recorded_actions=heartbeat_result.actions_taken,
                include_proactive_websocket=args.include_proactive_websocket,
                skip_briefing_audit=args.skip_briefing_audit,
            ),
            "briefing": briefing,
            "proactive_websocket": _safe_socket_summary(socket),
            "database": {
                "tables_checked": sorted(required_tables),
                "core_tables_checked": all(table in required_tables for table in CORE_TABLES),
                "counted_table_count": len(counted_tables),
                "deltas": deltas,
            },
            "database_scope_contract": _database_scope_contract(
                scope=scope,
                required_tables=required_tables,
                counted_tables=counted_tables,
                deltas=deltas,
                include_proactive_websocket=args.include_proactive_websocket,
            ),
            "metrics": {
                "heartbeat_cycles_event_count": _metric_event_count(
                    metrics,
                    HEARTBEAT_CYCLES_METRIC,
                ),
                "heartbeat_cycle_success_count": heartbeat_cycle_success_count,
                "heartbeat_cycle_success_seen": _metric_label_seen(
                    metrics,
                    HEARTBEAT_CYCLES_METRIC,
                    expected={"status": "success"},
                ),
                "heartbeat_cycle_duration_event_count": _histogram_event_count(
                    metrics,
                    HEARTBEAT_CYCLE_DURATION_METRIC,
                ),
                "heartbeat_cycle_duration_success_count": (
                    heartbeat_cycle_duration_success_count
                ),
                "heartbeat_cycle_duration_success_seen": _histogram_label_seen(
                    metrics,
                    HEARTBEAT_CYCLE_DURATION_METRIC,
                    expected={"status": "success"},
                ),
                "heartbeat_actions_event_count": _metric_event_count(
                    metrics,
                    HEARTBEAT_ACTIONS_METRIC,
                ),
                "heartbeat_action_success_count": heartbeat_action_success_count,
                "heartbeat_action_duration_event_count": _histogram_event_count(
                    metrics,
                    HEARTBEAT_ACTION_DURATION_METRIC,
                ),
                "heartbeat_action_duration_success_count": (
                    heartbeat_action_duration_success_count
                ),
                "heartbeat_action_duration_success_seen": (
                    heartbeat_action_duration_success_count >= 2
                ),
                "heartbeat_reflect_success_count": heartbeat_reflect_success_count,
                "heartbeat_reflect_success_seen": _metric_label_seen(
                    metrics,
                    HEARTBEAT_ACTIONS_METRIC,
                    expected={"action_type": "reflect", "status": "success"},
                ),
                "heartbeat_write_journal_success_count": (
                    heartbeat_write_journal_success_count
                ),
                "heartbeat_write_journal_success_seen": _metric_label_seen(
                    metrics,
                    HEARTBEAT_ACTIONS_METRIC,
                    expected={"action_type": "write_journal", "status": "success"},
                ),
                "heartbeat_reflect_duration_success_count": (
                    heartbeat_reflect_duration_success_count
                ),
                "heartbeat_reflect_duration_success_seen": _histogram_label_seen(
                    metrics,
                    HEARTBEAT_ACTION_DURATION_METRIC,
                    expected={"action_type": "reflect", "status": "success"},
                ),
                "heartbeat_write_journal_duration_success_count": (
                    heartbeat_write_journal_duration_success_count
                ),
                "heartbeat_write_journal_duration_success_seen": _histogram_label_seen(
                    metrics,
                    HEARTBEAT_ACTION_DURATION_METRIC,
                    expected={"action_type": "write_journal", "status": "success"},
                ),
                "proactive_can_send_event_count": _metric_event_count(
                    metrics,
                    PROACTIVE_CAN_SEND_METRIC,
                ),
                "proactive_sends_event_count": _metric_event_count(
                    metrics,
                    PROACTIVE_SENDS_METRIC,
                ),
                "heartbeat_cycles": _metric_counter_map(
                    metrics,
                    HEARTBEAT_CYCLES_METRIC,
                ),
                "heartbeat_actions": _metric_counter_map(
                    metrics,
                    HEARTBEAT_ACTIONS_METRIC,
                ),
                "proactive_can_send": _metric_counter_map(
                    metrics,
                    PROACTIVE_CAN_SEND_METRIC,
                ),
                "proactive_sends": _metric_counter_map(
                    metrics,
                    PROACTIVE_SENDS_METRIC,
                ),
                "metric_label_strategy": "bounded_status_and_action_type_only",
                "raw_metric_payload_included": False,
            },
            "privacy": {
                "raw_content_included": False,
                "raw_user_identifier_included": False,
                "raw_session_identifier_included": False,
                "raw_organization_identifier_included": False,
                "raw_action_target_included": False,
                "raw_action_metadata_values_included": False,
                "raw_briefing_content_included": False,
                "raw_socket_payload_included": False,
                "raw_metric_payload_included": False,
                "raw_database_rows_included": False,
                "raw_emotional_state_included": False,
                "metric_labels_include_identifiers": False,
                "identifier_strategy": "hash_or_count_only",
            },
        }
        _assert_probe_evidence(summary, args)
        _assert_heartbeat_summary_contract(summary, args)
        return summary
    finally:
        current_org_id.reset(org_token)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Opt-in live heartbeat-cycle probe through Wiii living-agent "
            "runtime abstractions."
        ),
    )
    parser.add_argument("--allow-write", action="store_true", help="Permit live DB writes.")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Permit running against settings.environment=production.",
    )
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--cycle-timeout", type=float, default=120.0)
    parser.add_argument("--action-timeout", type=float, default=90.0)
    parser.add_argument("--skip-reflection", action="store_true")
    parser.add_argument("--skip-journal", action="store_true")
    parser.add_argument("--skip-briefing-audit", action="store_true")
    parser.add_argument(
        "--briefing-type",
        choices=("morning", "midday", "evening"),
        default="midday",
        help="Briefing compose path to audit-write outside wall-clock windows.",
    )
    parser.add_argument(
        "--include-proactive-websocket",
        action="store_true",
        help=(
            "Also run a heartbeat re-engagement action through the real "
            "ProactiveMessenger -> NotificationDispatcher -> WebSocketAdapter path."
        ),
    )
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = await _run_probe(args)
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
