"""
Routine Tracker — Learn user behavior patterns.

Sprint 176: "Wiii Soul AGI" — Phase 3B

Tracks when users are active, what they ask about, and their mood trends.
Used to optimize briefing timing and personalize proactive messages.

Design:
    - Updates on every user interaction (via webhook handlers)
    - Stored per-user in wiii_user_routines table
    - Feature-gated: living_agent_enable_routine_tracking
    - No LLM cost — pure statistical tracking
"""

import json
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.engine.living_agent.models import UserRoutine
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)

_VN_OFFSET = timedelta(hours=7)
_ROUTINE_MISSING_ORG_WARNING = "routine_tracking_blocked_missing_org_context"


class RoutineTracker:
    """Tracks and learns user behavior patterns.

    Usage:
        tracker = RoutineTracker()
        await tracker.record_interaction(user_id, channel, topic)
        routine = await tracker.get_routine(user_id)
    """

    async def record_interaction(
        self,
        user_id: str,
        channel: str = "web",
        topic: str = "",
    ) -> None:
        """Record a user interaction for pattern learning.

        Called from webhook handlers and chat orchestrator.
        """
        from app.core.config import settings

        if not settings.living_agent_enable_routine_tracking:
            return

        scope = resolve_memory_write_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("record_interaction", user_id, scope)
            return

        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        hour = now_vn.hour

        try:
            routine = await self._load_routine(user_id, scope=scope)
            if routine is None:
                routine = UserRoutine(user_id=user_id, organization_id=scope.org_id)
            routine.organization_id = scope.org_id

            # Update active hours histogram
            if hour not in routine.typical_active_hours:
                routine.typical_active_hours.append(hour)
                # Keep sorted and deduplicated
                routine.typical_active_hours = sorted(set(routine.typical_active_hours))

            # Update topics
            if topic and topic not in routine.common_topics:
                routine.common_topics.append(topic)
                routine.common_topics = routine.common_topics[-20:]  # Keep last 20

            # Update counters
            routine.total_messages += 1
            routine.last_seen = datetime.now(timezone.utc)
            routine.updated_at = datetime.now(timezone.utc)

            # Compute preferred briefing time (hour with most interactions)
            if routine.typical_active_hours:
                hour_counts = Counter(routine.typical_active_hours)
                routine.preferred_briefing_time = hour_counts.most_common(1)[0][0]

            # Compute conversation frequency (messages per day, rolling 7-day window)
            routine.conversation_frequency = await self._compute_frequency(
                user_id,
                scope=scope,
            )

            await self._save_routine(routine, scope=scope)

        except Exception as e:
            logger.warning("[ROUTINE] Failed to record interaction: %s", e)

    async def get_routine(self, user_id: str) -> Optional[UserRoutine]:
        """Get learned routine for a user."""
        scope = resolve_memory_read_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("get_routine", user_id, scope)
            return None
        return await self._load_routine(user_id, scope=scope)

    async def get_inactive_users(self, days: int = 3) -> List[str]:
        """Find users who haven't interacted in N days."""
        scope = resolve_memory_read_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("get_inactive_users", "*", scope)
            return []

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT user_id FROM wiii_user_routines
                        WHERE last_seen < NOW() - INTERVAL '1 day' * :days
                        AND organization_id = :org_id
                        AND total_messages > 5
                        ORDER BY last_seen ASC
                    """),
                    {"days": days, "org_id": scope.org_id},
                ).fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.warning("[ROUTINE] Failed to query inactive users: %s", e)
            return []

    async def is_user_likely_active(self, user_id: str) -> bool:
        """Check if user is typically active at the current time."""
        scope = resolve_memory_read_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("is_user_likely_active", user_id, scope)
            return False

        routine = await self._load_routine(user_id, scope=scope)
        if not routine or not routine.typical_active_hours:
            return True  # Unknown — assume yes

        now_vn = datetime.now(timezone.utc) + _VN_OFFSET
        return now_vn.hour in routine.typical_active_hours

    async def _compute_frequency(
        self,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> float:
        """Compute average messages per day over the last 7 days."""
        scope = scope or resolve_memory_read_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("compute_frequency", user_id, scope)
            return 0.0

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                row = session.execute(
                    text("""
                        SELECT total_messages, created_at FROM wiii_user_routines
                        WHERE user_id = :uid
                        AND organization_id = :org_id
                    """),
                    {"uid": user_id, "org_id": scope.org_id},
                ).fetchone()

                if row:
                    total = row[0] or 0
                    created = row[1]
                    if created:
                        days_active = max(1, (datetime.now(timezone.utc) - created).days)
                        return round(total / days_active, 2)
        except Exception:
            pass
        return 0.0

    async def _load_routine(
        self,
        user_id: str,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> Optional[UserRoutine]:
        """Load user routine from database."""
        scope = scope or resolve_memory_read_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("load_routine", user_id, scope)
            return None

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                row = session.execute(
                    text("""
                        SELECT user_id, typical_active_hours, preferred_briefing_time,
                               conversation_frequency, common_topics, last_seen,
                               total_messages, updated_at, organization_id
                        FROM wiii_user_routines
                        WHERE user_id = :uid
                        AND organization_id = :org_id
                    """),
                    {"uid": user_id, "org_id": scope.org_id},
                ).fetchone()

                if row:
                    return UserRoutine(
                        user_id=row[0],
                        typical_active_hours=row[1] if isinstance(row[1], list) else [],
                        preferred_briefing_time=row[2] or 7,
                        conversation_frequency=float(row[3]) if row[3] else 0.0,
                        common_topics=row[4] if isinstance(row[4], list) else [],
                        last_seen=row[5],
                        total_messages=row[6] or 0,
                        updated_at=row[7] or datetime.now(timezone.utc),
                        organization_id=row[8] or scope.org_id,
                    )
        except Exception as e:
            logger.warning("[ROUTINE] Failed to load routine: %s", e)
        return None

    async def _save_routine(
        self,
        routine: UserRoutine,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Upsert user routine to database."""
        scope = scope or resolve_memory_write_scope()
        if not self._scope_allows_routine(scope):
            self._log_scope_blocked("save_routine", routine.user_id, scope)
            return

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_user_routines
                        (organization_id, user_id, typical_active_hours, preferred_briefing_time,
                         conversation_frequency, common_topics, last_seen,
                         total_messages, updated_at, created_at)
                        VALUES (:org_id, :uid, :hours, :briefing_time, :freq, :topics,
                                :last_seen, :total, NOW(), NOW())
                        ON CONFLICT (organization_id, user_id)
                        DO UPDATE SET
                            typical_active_hours = :hours,
                            preferred_briefing_time = :briefing_time,
                            conversation_frequency = :freq,
                            common_topics = :topics,
                            last_seen = :last_seen,
                            total_messages = :total,
                            updated_at = NOW()
                    """),
                    {
                        "org_id": scope.org_id,
                        "uid": routine.user_id,
                        "hours": json.dumps(routine.typical_active_hours),
                        "briefing_time": routine.preferred_briefing_time,
                        "freq": routine.conversation_frequency,
                        "topics": json.dumps(routine.common_topics, ensure_ascii=False),
                        "last_seen": routine.last_seen,
                        "total": routine.total_messages,
                    },
                )
                session.commit()
        except Exception as e:
            logger.warning("[ROUTINE] Failed to save routine: %s", e)

    def _scope_allows_routine(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        user_id: str,
        scope: MemoryWriteScope,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_ROUTINE_MISSING_ORG_WARNING)
        logger.warning(
            "[ROUTINE] %s blocked user_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(user_id),
            scope.state,
            sorted(set(warnings)),
        )


# =============================================================================
# Singleton
# =============================================================================

_tracker_instance: Optional[RoutineTracker] = None


def get_routine_tracker() -> RoutineTracker:
    """Get the singleton RoutineTracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = RoutineTracker()
    return _tracker_instance
