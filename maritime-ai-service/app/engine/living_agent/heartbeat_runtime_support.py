"""Runtime support helpers for HeartbeatScheduler.

Extracts persistence, scheduling-window checks, and notification side effects
out of ``heartbeat.py`` while keeping the public class API stable.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from app.engine.living_agent.heartbeat_runtime_state import (
    set_current_heartbeat_count,
)
from app.engine.living_agent.models import ActionType, HeartbeatAction, HeartbeatResult
from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_VN_OFFSET = timedelta(hours=7)
_HEARTBEAT_MISSING_ORG_WARNING = "heartbeat_runtime_blocked_missing_org_context"
_ACTION_TYPE_LABELS = {action_type.value for action_type in ActionType}


def _action_type_metric_label(action: HeartbeatAction) -> str:
    value = getattr(action.action_type, "value", None)
    if value in _ACTION_TYPE_LABELS:
        return str(value)
    return "unknown"


def _emit_action_queue_metric(action: HeartbeatAction) -> None:
    inc_counter(
        "runtime.living_agent.heartbeat.actions",
        labels={
            "action_type": _action_type_metric_label(action),
            "status": "queued",
        },
    )


def _heartbeat_cycle_status(result: HeartbeatResult) -> str:
    if result.error:
        return "error"
    if result.is_noop:
        return "noop"
    return "success"


def _emit_heartbeat_cycle_metric(result: HeartbeatResult) -> None:
    labels = {"status": _heartbeat_cycle_status(result)}
    inc_counter("runtime.living_agent.heartbeat.cycles", labels=labels)
    record_latency_ms(
        "runtime.living_agent.heartbeat.duration_ms",
        float(result.duration_ms),
        labels=labels,
    )


async def save_emotional_snapshot_impl(engine: Any) -> None:
    """Persist the current emotional state snapshot."""
    try:
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        state = engine.state
        repo.save_snapshot(
            primary_mood=state.primary_mood.value,
            energy_level=state.energy_level,
            social_battery=state.social_battery,
            engagement=state.engagement,
            trigger_event="heartbeat_cycle",
            state_json=engine.to_dict(),
        )
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("[HEARTBEAT] Failed to save emotional snapshot: %s", exc)


async def queue_pending_actions_impl(actions: list[HeartbeatAction]) -> None:
    """Queue actions for human approval with org scoping."""
    scope = resolve_memory_write_scope()
    if not _scope_allows_heartbeat(scope):
        _log_heartbeat_scope_blocked("queue_pending_actions", scope)
        return

    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            for action in actions:
                session.execute(
                    text(
                        """
                            INSERT INTO wiii_pending_actions
                            (id, action_type, target, priority, metadata, status,
                             organization_id, created_at)
                            VALUES (:id, :action_type, :target, :priority, :metadata,
                                    'pending', :org_id, NOW())
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "action_type": action.action_type.value,
                        "target": action.target,
                        "priority": action.priority,
                        "metadata": json.dumps(action.metadata, ensure_ascii=False),
                        "org_id": scope.org_id,
                    },
                )
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("[HEARTBEAT] Failed to queue pending actions: %s", exc)


async def load_pending_action_impl(action_id: str) -> Optional[dict]:
    """Load an approved pending action, respecting org isolation."""
    scope = resolve_memory_read_scope()
    if not _scope_allows_heartbeat(scope):
        _log_heartbeat_scope_blocked("load_pending_action", scope, action_id=action_id)
        return None

    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            query = """
                SELECT action_type, target, priority, metadata
                FROM wiii_pending_actions
                WHERE id = :id AND status = 'approved'
                AND organization_id = :org_id
            """
            params: dict[str, Any] = {"id": action_id, "org_id": scope.org_id}

            row = session.execute(text(query), params).fetchone()
            if row:
                return {
                    "action_type": row[0],
                    "target": row[1],
                    "priority": row[2],
                    "metadata": row[3],
                }
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("[HEARTBEAT] Failed to load pending action: %s", exc)
    return None


async def mark_action_completed_impl(action_id: str) -> None:
    """Mark a pending action as completed with org filtering."""
    scope = resolve_memory_write_scope()
    if not _scope_allows_heartbeat(scope):
        _log_heartbeat_scope_blocked("mark_action_completed", scope, action_id=action_id)
        return

    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            query = """
                UPDATE wiii_pending_actions
                SET status = 'completed', resolved_at = NOW()
                WHERE id = :id
                AND organization_id = :org_id
            """
            params: dict[str, Any] = {"id": action_id, "org_id": scope.org_id}

            session.execute(text(query), params)
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("[HEARTBEAT] Failed to mark action completed: %s", exc)


async def save_heartbeat_audit_impl(
    heartbeat_count: int,
    result: HeartbeatResult,
) -> None:
    """Persist a heartbeat audit row with org isolation."""
    scope = resolve_memory_write_scope()
    if not _scope_allows_heartbeat(scope):
        _log_heartbeat_scope_blocked(
            "save_heartbeat_audit",
            scope,
            action_id=str(result.cycle_id),
        )
        return

    try:
        from sqlalchemy import text

        from app.core.database import get_shared_session_factory

        actions_json = json.dumps(
            [
                {"action_type": action.action_type.value, "target": action.target}
                for action in result.actions_taken
            ],
            ensure_ascii=False,
        )

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            session.execute(
                text(
                    """
                        INSERT INTO wiii_heartbeat_audit
                        (id, cycle_number, actions_taken, insights_gained, duration_ms,
                         error, organization_id, created_at)
                        VALUES (:id, :cycle_number, :actions_taken, :insights_gained,
                                :duration_ms, :error, :org_id, NOW())
                    """
                ),
                {
                    "id": str(result.cycle_id),
                    "cycle_number": heartbeat_count,
                    "actions_taken": actions_json,
                    "insights_gained": result.insights_gained,
                    "duration_ms": result.duration_ms,
                    "error": result.error,
                    "org_id": scope.org_id,
                },
            )
            session.commit()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("[HEARTBEAT] Failed to save audit record: %s", exc)


def _scope_allows_heartbeat(scope: MemoryWriteScope) -> bool:
    return bool(scope.write_allowed and scope.org_id)


def _log_heartbeat_scope_blocked(
    operation: str,
    scope: MemoryWriteScope,
    *,
    action_id: Optional[str] = None,
) -> None:
    warnings = list(scope.warnings)
    if "missing_org_context" in warnings:
        warnings.append(_HEARTBEAT_MISSING_ORG_WARNING)
    logger.warning(
        "[HEARTBEAT] %s blocked action_hash=%s org_hash=%s org_scope=%s warnings=%s",
        operation,
        hash_memory_identifier(action_id),
        hash_memory_identifier(scope.org_id),
        scope.state,
        sorted(set(warnings)),
    )


def check_daily_limit_impl(scheduler: Any) -> bool:
    """Check and reset the daily cycle counter in UTC+7."""
    from app.core.config import settings

    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    today_str = now_vn.strftime("%Y-%m-%d")

    if scheduler._daily_reset_date != today_str:
        scheduler._daily_reset_date = today_str
        scheduler._daily_cycle_count = 0

    return scheduler._daily_cycle_count < settings.living_agent_max_daily_cycles


def is_active_hours_impl() -> bool:
    """Return whether the current time is within configured active hours."""
    from app.core.config import settings

    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    hour = now_vn.hour
    start = settings.living_agent_active_hours_start
    end = settings.living_agent_active_hours_end

    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def is_journal_time_impl() -> bool:
    """Return whether the current time is inside journal windows."""
    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    return (8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22)


def is_morning_impl() -> bool:
    """Return whether the current time is inside the morning weather window."""
    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    return 5 <= now_vn.hour < 7


def is_briefing_time_impl() -> bool:
    """Return whether the current time is inside any briefing window."""
    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    hour = now_vn.hour
    return (5 <= hour < 7) or (11 <= hour < 13) or (17 <= hour < 19)


def is_reflection_time_impl() -> bool:
    """Return whether the current time is inside the daily reflection window."""
    now_vn = datetime.now(timezone.utc) + _VN_OFFSET
    return 21 <= now_vn.hour <= 22


async def check_graduation_daily_impl(scheduler: Any) -> None:
    """Run the autonomy graduation check at most once per UTC+7 day."""
    try:
        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        today = now_vn.strftime("%Y-%m-%d")
        if scheduler._graduation_checked_date == today:
            return

        scheduler._graduation_checked_date = today

        from app.core.config import settings

        if not getattr(settings, "living_agent_enable_autonomy_graduation", False):
            return

        from app.engine.living_agent.autonomy_manager import get_autonomy_manager

        manager = get_autonomy_manager()
        upgraded = await manager.check_graduation()
        if upgraded:
            logger.info("[HEARTBEAT] Autonomy graduation proposed")
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.debug("[HEARTBEAT] Graduation check failed: %s", exc)


async def execute_heartbeat_cycle_impl(
    *,
    scheduler: Any,
    approval_required_actions,
    logger_obj,
) -> HeartbeatResult:
    """Execute one heartbeat cycle while keeping the scheduler shell thin."""
    from app.core.config import settings
    from app.engine.living_agent.emotion_engine import get_emotion_engine
    from app.engine.living_agent.soul_loader import get_soul
    from app.engine.living_agent.models import LifeEvent, LifeEventType

    start_time = scheduler._time_monotonic()
    scheduler._heartbeat_count += 1
    set_current_heartbeat_count(scheduler._heartbeat_count)
    scheduler._daily_cycle_count += 1

    result = HeartbeatResult()

    try:
        soul = get_soul()
        engine = get_emotion_engine()

        if not scheduler._emotion_loaded:
            await engine.load_state_from_db()
            scheduler._emotion_loaded = True

        engine.apply_circadian_modifier()

        if getattr(settings, "enable_living_continuity", False):
            try:
                from app.engine.living_agent.emotion_engine import refresh_known_user_cache

                refresh_known_user_cache()
            except Exception as exc:
                logger_obj.debug("[HEARTBEAT] Known user cache refresh failed: %s", exc)

            try:
                agg_stats = engine.process_aggregate()
                if agg_stats.get("total_interactions", 0) > 0:
                    logger_obj.info(
                        "[HEARTBEAT] Aggregate: %d interactions, %d unique users, ratio=%.2f",
                        int(agg_stats["total_interactions"]),
                        int(agg_stats["unique_users"]),
                        agg_stats["positive_ratio"],
                    )
            except Exception as exc:
                logger_obj.debug("[HEARTBEAT] Aggregate processing failed: %s", exc)

        engine.process_event(
            LifeEvent(
                event_type=LifeEventType.HEARTBEAT_WAKE,
                description="Heartbeat wake-up",
                importance=0.2,
            )
        )

        actions = await scheduler._plan_actions(engine.mood.value, engine.energy)
        if not actions:
            result.is_noop = True
            result.duration_ms = int((scheduler._time_monotonic() - start_time) * 1000)
            await scheduler._save_heartbeat_audit(result)
            _emit_heartbeat_cycle_metric(result)
            return result

        require_approval = settings.living_agent_require_human_approval
        auto_actions = []
        pending_actions = []

        for action in actions:
            if require_approval and action.action_type in approval_required_actions:
                pending_actions.append(action)
            else:
                auto_actions.append(action)

        if pending_actions:
            await scheduler._queue_pending_actions(pending_actions)
            for action in pending_actions:
                _emit_action_queue_metric(action)
            logger_obj.info(
                "[HEARTBEAT] Queued %d actions for human approval: %s",
                len(pending_actions),
                [a.action_type.value for a in pending_actions],
            )

        for action in auto_actions:
            try:
                await scheduler._execute_action(action, soul, engine)
                result.actions_taken.append(action)
                try:
                    from app.engine.living_agent.autonomy_manager import get_autonomy_manager

                    get_autonomy_manager().record_success()
                except Exception as exc:
                    logger_obj.debug(
                        "[HEARTBEAT] Autonomy success recording failed: %s",
                        exc,
                    )
            except Exception as exc:
                logger_obj.warning(
                    "[HEARTBEAT] Action %s failed: %s",
                    action.action_type.value,
                    exc,
                )

        engine.take_snapshot()
        await scheduler._save_emotional_snapshot(engine)
        await engine.save_state_to_db()
        await scheduler._broadcast_soul_bridge(engine, result)
        await scheduler._check_graduation_daily()

    except Exception as exc:
        result.error = str(exc)
        logger_obj.error("[HEARTBEAT] Cycle failed: %s", exc, exc_info=True)

    result.duration_ms = int((scheduler._time_monotonic() - start_time) * 1000)
    await scheduler._save_heartbeat_audit(result)
    _emit_heartbeat_cycle_metric(result)
    return result


async def broadcast_soul_bridge_impl(
    heartbeat_count: int,
    engine: Any,
    result: HeartbeatResult,
) -> None:
    """Broadcast heartbeat status to connected peer souls."""
    try:
        from app.core.config import settings

        if not getattr(settings, "enable_soul_bridge", False):
            return

        from app.engine.soul_bridge import get_soul_bridge

        bridge = get_soul_bridge()
        if not bridge.is_initialized:
            return

        payload = {
            "cycle": heartbeat_count,
            "mood": engine.mood.value if hasattr(engine.mood, "value") else str(engine.mood),
            "energy": engine.energy,
            "actions_taken": len(result.actions_taken),
            "duration_ms": result.duration_ms,
        }
        await bridge.broadcast_status(payload)
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.debug("[HEARTBEAT] SoulBridge broadcast failed: %s", exc)


async def notify_discovery_impl(items: list, topic: str) -> None:
    """Notify the owner about high-relevance discoveries."""
    try:
        from app.core.config import settings

        channel = settings.living_agent_notification_channel
        if channel == "websocket" and not settings.enable_websocket:
            return
        scope = resolve_memory_write_scope()
        if not _scope_allows_heartbeat(scope):
            _log_heartbeat_scope_blocked("notify_discovery", scope)
            return

        lines = [f"Wiii tìm thấy {len(items)} nội dung thú vị về {topic}:"]
        for item in items[:3]:
            title = item.title[:100] if item.title else "Không có tiêu đề"
            url = item.url or ""
            score = f" ({item.relevance_score:.0%})" if item.relevance_score else ""
            lines.append(f"• {title}{score}")
            if url:
                lines.append(f"  {url}")
        from app.engine.living_agent.heartbeat_action_runtime import (
            _format_discovery_notification_message,
        )

        message = _format_discovery_notification_message(items, topic)
        payload = json.dumps(
            {
                "type": "proactive_message",
                "trigger": "heartbeat_discovery",
                "content": message,
                "topic": topic,
                "item_count": len(items),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

        from app.services.notification_dispatcher import get_notification_dispatcher

        dispatcher = get_notification_dispatcher()
        result = await dispatcher.notify_user(
            user_id="wiii_owner",
            message=payload if channel == "websocket" else message,
            channel=channel,
            metadata={
                "organization_id": scope.org_id,
                "notification_type": "proactive_message",
                "trigger": "heartbeat_discovery",
            },
        )

        if result.get("delivered"):
            logger.info("[HEARTBEAT] Discovery notification sent via %s", channel)
        else:
            logger.debug(
                "[HEARTBEAT] Discovery notification not delivered: %s",
                result.get("detail", "unknown"),
            )
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.debug("[HEARTBEAT] Discovery notification failed: %s", exc)
