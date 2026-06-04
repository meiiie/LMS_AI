"""
Proactive Messenger — Wiii's initiative communication system.

Sprint 176: "Wiii Soul AGI" — Phase 5A

Sends proactive messages when Wiii has something valuable to share:
- Morning/evening briefings
- Interesting discoveries
- Weather alerts
- Skill mastery celebrations
- Re-engagement after inactivity

Design:
    - Hard anti-spam limits (max 3/day, min 4h between, quiet hours)
    - User opt-out via "dung nhan nua" command
    - Trigger-based with priority scoring
    - Feature-gated: living_agent_enable_proactive_messaging
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from app.engine.living_agent.models import ProactiveMessage
from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_VN_OFFSET = timedelta(hours=7)
_PROACTIVE_MISSING_ORG_WARNING = "proactive_message_blocked_missing_org_context"


def _emit_can_send_metric(*, status: str, reason: str) -> None:
    inc_counter(
        "runtime.living_agent.proactive.can_send",
        labels={"status": status, "reason": reason},
    )


def _emit_send_metric(*, status: str, started: float) -> None:
    labels = {"status": status}
    inc_counter("runtime.living_agent.proactive.sends", labels=labels)
    record_latency_ms(
        "runtime.living_agent.proactive.send_duration_ms",
        (time.monotonic() - started) * 1000.0,
        labels=labels,
    )


class ProactiveMessenger:
    """Sends proactive messages with anti-spam guardrails.

    Usage:
        messenger = ProactiveMessenger()
        if await messenger.can_send(user_id):
            await messenger.send(user_id, "messenger", content, trigger="briefing")
    """

    def __init__(self):
        # In-memory tracking (per-session, backed by DB for persistence)
        self._daily_counts: Dict[str, int] = {}
        self._last_sent: Dict[str, datetime] = {}
        self._daily_reset_date: str = ""

    async def can_send(
        self,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> bool:
        """Check if we can send a proactive message to this user.

        Checks:
        1. Feature flag enabled
        2. Within quiet hours (23:00-05:00 = no send)
        3. Daily limit not exceeded
        4. Cooloff period since last message
        5. User hasn't opted out
        """
        from app.core.config import settings

        if not settings.living_agent_enable_proactive_messaging:
            _emit_can_send_metric(status="blocked", reason="feature_disabled")
            return False

        # Quiet hours check
        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        quiet_start = settings.living_agent_proactive_quiet_start
        quiet_end = settings.living_agent_proactive_quiet_end
        hour = now_vn.hour

        if quiet_start > quiet_end:
            # Wraps midnight (e.g. 23-05)
            if hour >= quiet_start or hour < quiet_end:
                _emit_can_send_metric(status="blocked", reason="quiet_hours")
                return False
        elif quiet_start <= hour < quiet_end:
            _emit_can_send_metric(status="blocked", reason="quiet_hours")
            return False

        scope = scope or resolve_memory_read_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("can_send", user_id, scope)
            _emit_can_send_metric(status="blocked", reason="missing_org_context")
            return False

        # Daily limit check
        self._reset_daily_if_needed()
        counter_key = self._counter_key(user_id, scope)
        count = self._daily_counts.get(counter_key, 0)
        if count >= settings.living_agent_max_proactive_per_day:
            _emit_can_send_metric(status="blocked", reason="daily_limit")
            return False

        # Cooloff check (min 4 hours between proactive messages)
        last = self._last_sent.get(counter_key)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < 4 * 3600:
            _emit_can_send_metric(status="blocked", reason="cooloff")
            return False

        # Opt-out check
        if await self._is_opted_out(user_id, scope=scope):
            _emit_can_send_metric(status="blocked", reason="opted_out")
            return False

        _emit_can_send_metric(status="allowed", reason="allowed")
        return True

    async def send(
        self,
        user_id: str,
        channel: str,
        content: str,
        trigger: str = "general",
        priority: float = 0.5,
    ) -> bool:
        """Send a proactive message if allowed.

        Returns:
            True if message was delivered successfully.
        """
        started = time.monotonic()
        scope = resolve_memory_write_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("send", user_id, scope)
            _emit_send_metric(status="blocked_missing_org_context", started=started)
            return False

        if not await self.can_send(user_id, scope=scope):
            logger.debug(
                "[PROACTIVE] Blocked for user_hash=%s (limits/opt-out, org_scope=%s)",
                hash_memory_identifier(user_id),
                scope.state,
            )
            _emit_send_metric(status="blocked_guardrail", started=started)
            return False

        # Deliver
        success = await self._deliver(
            user_id,
            channel,
            content,
            trigger=trigger,
            organization_id=scope.org_id,
        )
        if not success:
            _emit_send_metric(status="delivery_failed", started=started)
            return False

        # Track
        counter_key = self._counter_key(user_id, scope)
        self._daily_counts[counter_key] = self._daily_counts.get(counter_key, 0) + 1
        self._last_sent[counter_key] = datetime.now(timezone.utc)

        # Persist
        msg = ProactiveMessage(
            user_id=user_id,
            channel=channel,
            content=content,
            trigger=trigger,
            priority=priority,
            delivered=True,
            delivered_at=datetime.now(timezone.utc),
            organization_id=scope.org_id,
        )
        await self._save_message(msg, scope=scope)

        logger.info(
            "[PROACTIVE] Sent to user_hash=%s via %s (trigger=%s, daily=%d, org_scope=%s)",
            hash_memory_identifier(user_id),
            channel,
            trigger,
            self._daily_counts[counter_key],
            scope.state,
        )
        _emit_send_metric(status="delivered", started=started)
        return True

    async def opt_out(self, user_id: str) -> None:
        """Opt user out of proactive messages."""
        scope = resolve_memory_write_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("opt_out", user_id, scope)
            return

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_proactive_preferences
                            (organization_id, user_id, opted_out, updated_at)
                        VALUES (:org_id, :uid, true, NOW())
                        ON CONFLICT (organization_id, user_id)
                        DO UPDATE SET opted_out = true, updated_at = NOW()
                    """),
                    {"org_id": scope.org_id, "uid": user_id},
                )
                session.commit()
            logger.info(
                "[PROACTIVE] User opted out user_hash=%s org_hash=%s",
                hash_memory_identifier(user_id),
                hash_memory_identifier(scope.org_id),
            )
        except Exception as e:
            logger.warning("[PROACTIVE] Failed to opt out: %s", e)

    async def opt_in(self, user_id: str) -> None:
        """Opt user back in to proactive messages."""
        scope = resolve_memory_write_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("opt_in", user_id, scope)
            return

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_proactive_preferences
                            (organization_id, user_id, opted_out, updated_at)
                        VALUES (:org_id, :uid, false, NOW())
                        ON CONFLICT (organization_id, user_id)
                        DO UPDATE SET opted_out = false, updated_at = NOW()
                    """),
                    {"org_id": scope.org_id, "uid": user_id},
                )
                session.commit()
        except Exception as e:
            logger.warning("[PROACTIVE] Failed to opt in: %s", e)

    async def get_daily_stats(self) -> Dict[str, int]:
        """Get today's proactive message counts per user."""
        self._reset_daily_if_needed()
        return dict(self._daily_counts)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _deliver(
        self,
        user_id: str,
        channel: str,
        content: str,
        *,
        trigger: str = "general",
        organization_id: str | None = None,
    ) -> bool:
        """Deliver message via channel_sender (Sprint 188: DRY shared sender).

        Also emits PROACTIVE_MESSAGE life event on success.
        """
        try:
            if channel in {"websocket", "telegram"}:
                from app.services.notification_dispatcher import (
                    get_notification_dispatcher,
                )

                message = content
                if channel == "websocket":
                    message = json.dumps(
                        {
                            "type": "proactive_message",
                            "content": content,
                            "trigger": trigger,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )

                result = await get_notification_dispatcher().notify_user(
                    user_id=user_id,
                    message=message,
                    channel=channel,
                    metadata={
                        "organization_id": organization_id,
                        "notification_type": "proactive_message",
                        "trigger": trigger,
                    },
                )
                delivered = bool(result.get("delivered"))
                if delivered:
                    self._record_delivery_life_event(channel)
                return delivered

            from app.engine.living_agent.channel_sender import send_to_channel

            result = await send_to_channel(channel, user_id, content)
            if result.success:
                self._record_delivery_life_event(channel)
            return result.success
        except Exception as e:
            logger.warning("[PROACTIVE] Delivery failed: %s", e)
            return False

    def _record_delivery_life_event(self, channel: str) -> None:
        """Emit a low-importance life event after a successful proactive send."""
        try:
            from app.engine.living_agent.emotion_engine import get_emotion_engine
            from app.engine.living_agent.models import LifeEvent, LifeEventType

            get_emotion_engine().process_event(
                LifeEvent(
                    event_type=LifeEventType.USER_CONVERSATION,
                    description=f"Proactive message sent via {channel}",
                    importance=0.3,
                )
            )
        except Exception:
            pass

    async def _is_opted_out(
        self,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> bool:
        """Check if user has opted out of proactive messages."""
        scope = scope or resolve_memory_read_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("opt_out_read", user_id, scope)
            return True

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                row = session.execute(
                    text("""
                        SELECT opted_out
                        FROM wiii_proactive_preferences
                        WHERE user_id = :uid
                          AND organization_id = :org_id
                    """),
                    {"uid": user_id, "org_id": scope.org_id},
                ).fetchone()
                return bool(row and row[0])
        except Exception as e:
            logger.warning(
                "[PROACTIVE] Opt-out lookup failed for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                e,
            )
            return True

    async def _save_message(
        self,
        msg: ProactiveMessage,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Save proactive message record."""
        scope = scope or resolve_memory_write_scope()
        if not self._scope_allows_proactive(scope):
            self._log_scope_blocked("save_message", msg.user_id, scope)
            return

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_proactive_messages
                        (id, organization_id, user_id, channel, content, trigger, priority,
                         delivered, delivered_at, created_at)
                        VALUES (:id, :org_id, :uid, :channel, :content, :trigger, :priority,
                                :delivered, :delivered_at, NOW())
                    """),
                    {
                        "id": str(msg.id),
                        "org_id": scope.org_id,
                        "uid": msg.user_id,
                        "channel": msg.channel,
                        "content": msg.content[:2000],
                        "trigger": msg.trigger,
                        "priority": msg.priority,
                        "delivered": msg.delivered,
                        "delivered_at": msg.delivered_at,
                    },
                )
                session.commit()
        except Exception as e:
            logger.warning("[PROACTIVE] Failed to save message: %s", e)

    def _counter_key(self, user_id: str, scope: MemoryWriteScope | None) -> str:
        """Scope in-memory anti-spam counters when a request org is proven."""
        if scope and scope.state == "request_scoped" and scope.org_id:
            return f"{scope.org_id}:{user_id}"
        return user_id

    def _scope_allows_proactive(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        user_id: str,
        scope: MemoryWriteScope,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_PROACTIVE_MISSING_ORG_WARNING)
        logger.warning(
            "[PROACTIVE] %s blocked user_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(user_id),
            scope.state,
            sorted(set(warnings)),
        )

    def _reset_daily_if_needed(self) -> None:
        """Reset daily counters at midnight UTC+7."""
        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        today = now_vn.strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_reset_date = today
            self._daily_counts.clear()


# =============================================================================
# Singleton
# =============================================================================

_messenger_instance: Optional[ProactiveMessenger] = None


def get_proactive_messenger() -> ProactiveMessenger:
    """Get the singleton ProactiveMessenger instance."""
    global _messenger_instance
    if _messenger_instance is None:
        _messenger_instance = ProactiveMessenger()
    return _messenger_instance
