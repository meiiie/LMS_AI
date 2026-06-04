"""
Autonomy Manager — Wiii's trust-level governance.

Sprint 176: "Wiii Soul AGI" — Phase 5B

Manages Wiii's autonomy graduation through trust levels:
  Level 0 (SUPERVISED):  All actions need human approval (default)
  Level 1 (SEMI_AUTO):   Browse + journal auto, messaging needs approval
  Level 2 (AUTONOMOUS):  All auto, flag exceptions only
  Level 3 (FULL_TRUST):  Full self-governance (future goal)

Graduation based on: days active, successful actions, safety record.

Design:
    - Trust level stored in config (living_agent_autonomy_level)
    - Graduation criteria checked periodically
    - Safety violations reset trust
    - Feature-gated: living_agent_enable_autonomy_graduation
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from app.engine.living_agent.models import ActionType, AutonomyLevel
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
_AUTONOMY_MISSING_ORG_WARNING = "autonomy_manager_blocked_missing_org_context"

# Actions allowed at each trust level without approval
_LEVEL_PERMISSIONS: Dict[AutonomyLevel, set] = {
    AutonomyLevel.SUPERVISED: {
        ActionType.CHECK_GOALS,
        ActionType.REST,
        ActionType.NOOP,
    },
    AutonomyLevel.SEMI_AUTO: {
        ActionType.CHECK_GOALS,
        ActionType.REST,
        ActionType.NOOP,
        ActionType.BROWSE_SOCIAL,
        ActionType.WRITE_JOURNAL,
        ActionType.REFLECT,
        ActionType.DEEP_REFLECT,
        ActionType.CHECK_WEATHER,
    },
    AutonomyLevel.AUTONOMOUS: {
        ActionType.CHECK_GOALS,
        ActionType.REST,
        ActionType.NOOP,
        ActionType.BROWSE_SOCIAL,
        ActionType.WRITE_JOURNAL,
        ActionType.REFLECT,
        ActionType.DEEP_REFLECT,
        ActionType.CHECK_WEATHER,
        ActionType.LEARN_TOPIC,
        ActionType.PRACTICE_SKILL,
        ActionType.SEND_BRIEFING,
    },
    AutonomyLevel.FULL_TRUST: set(ActionType),  # Everything
}

# Graduation criteria
_GRADUATION_RULES = {
    0: {  # SUPERVISED → SEMI_AUTO
        "min_days_active": 14,
        "min_successful_actions": 50,
        "zero_safety_violations": True,
    },
    1: {  # SEMI_AUTO → AUTONOMOUS
        "min_days_at_level": 30,
        "min_successful_actions": 200,
        "zero_safety_violations": True,
    },
    2: {  # AUTONOMOUS → FULL_TRUST
        "min_days_at_level": 90,
        "zero_safety_violations": True,
    },
}


class AutonomyManager:
    """Manages Wiii's autonomy level and graduation.

    Usage:
        manager = AutonomyManager()
        if manager.can_execute(ActionType.BROWSE_SOCIAL):
            # Execute without approval
        else:
            # Queue for human approval

        # Periodic check
        if await manager.check_graduation():
            # Level upgraded
    """

    def __init__(self):
        self._stats = {
            "successful_actions": 0,
            "safety_violations": 0,
            "level_start_date": datetime.now(timezone.utc),
        }

    @property
    def current_level(self) -> AutonomyLevel:
        """Get current autonomy level from config."""
        from app.core.config import settings
        level = settings.living_agent_autonomy_level
        try:
            return AutonomyLevel(level)
        except ValueError:
            return AutonomyLevel.SUPERVISED

    def can_execute(self, action_type: ActionType) -> bool:
        """Check if an action can be executed without approval at current level."""
        allowed = _LEVEL_PERMISSIONS.get(self.current_level, set())
        return action_type in allowed

    def needs_approval(self, action_type: ActionType) -> bool:
        """Check if an action needs human approval at current level."""
        return not self.can_execute(action_type)

    def record_success(self) -> None:
        """Record a successfully executed action."""
        self._stats["successful_actions"] += 1

    def record_safety_violation(self, reason: str = "") -> None:
        """Record a safety violation — may reset trust level."""
        self._stats["safety_violations"] += 1
        logger.warning("[AUTONOMY] Safety violation: %s (total: %d)",
                       reason, self._stats["safety_violations"])

    async def check_graduation(self) -> bool:
        """Check if Wiii qualifies for the next trust level.

        Returns True if level was upgraded.
        """
        from app.core.config import settings

        if not settings.living_agent_enable_autonomy_graduation:
            return False

        scope = self._resolve_autonomy_scope(None, write=True)
        if not self._scope_allows_autonomy(scope):
            self._log_scope_blocked("check_graduation", scope)
            return False

        current = self.current_level.value

        if current >= AutonomyLevel.FULL_TRUST.value:
            return False  # Already max level

        rules = _GRADUATION_RULES.get(current)
        if not rules:
            return False

        # Check criteria
        stats = await self._load_stats(scope=scope)

        min_days = rules.get("min_days_active", 0) or rules.get("min_days_at_level", 0)
        days_active = stats.get("days_active", 0)
        if days_active < min_days:
            return False

        min_actions = rules.get("min_successful_actions", 0)
        if min_actions and stats.get("successful_actions", 0) < min_actions:
            return False

        if rules.get("zero_safety_violations") and stats.get("safety_violations", 0) > 0:
            return False

        # All criteria met — propose graduation (still needs human confirmation)
        logger.info(
            "[AUTONOMY] Graduation criteria met: level %d → %d (pending approval)",
            current, current + 1,
        )
        await self._propose_graduation(current, current + 1, stats, scope=scope)
        return True

    async def approve_graduation(
        self,
        to_level: int,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Approve a pending graduation (called from API).

        Note: This doesn't directly modify config. It stores the approved level
        and the heartbeat will respect it.
        """
        scope = self._resolve_autonomy_scope(organization_id, write=True)
        if not self._scope_allows_autonomy(scope):
            self._log_scope_blocked("approve_graduation", scope)
            return False

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_autonomy_state
                        (organization_id, key, value, updated_at)
                        VALUES (:org_id, 'current_level', :level, NOW())
                        ON CONFLICT (organization_id, key)
                        DO UPDATE SET value = :level, updated_at = NOW()
                    """),
                    {"org_id": scope.org_id, "level": str(to_level)},
                )
                session.commit()

            logger.info("[AUTONOMY] Graduation approved: → level %d", to_level)
            return True
        except Exception as e:
            logger.warning("[AUTONOMY] Failed to approve graduation: %s", e)
            return False

    def get_status(self) -> Dict:
        """Get current autonomy status for API response."""
        level = self.current_level
        allowed = _LEVEL_PERMISSIONS.get(level, set())

        level_names = {
            AutonomyLevel.SUPERVISED: "Giam sat hoan toan",
            AutonomyLevel.SEMI_AUTO: "Ban tu dong",
            AutonomyLevel.AUTONOMOUS: "Tu chu",
            AutonomyLevel.FULL_TRUST: "Hoan toan tu chu",
        }

        next_rules = _GRADUATION_RULES.get(level.value, {})

        return {
            "level": level.value,
            "level_name": level_names.get(level, "Khong xac dinh"),
            "allowed_actions": [a.value for a in allowed],
            "needs_approval": [a.value for a in ActionType if a not in allowed],
            "stats": self._stats,
            "graduation_criteria": next_rules,
        }

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _load_stats(
        self,
        organization_id: Optional[str] = None,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> Dict:
        """Load autonomy statistics from database."""
        scope = scope or self._resolve_autonomy_scope(organization_id, write=False)
        if not self._scope_allows_autonomy(scope):
            self._log_scope_blocked("load_stats", scope)
            return self._stats

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                # Count successful heartbeat cycles
                row = session.execute(
                    text("""
                        SELECT COUNT(*) as total,
                               MIN(created_at) as first_cycle,
                               COUNT(*) FILTER (WHERE error IS NOT NULL) as errors
                        FROM wiii_heartbeat_audit
                        WHERE organization_id = :org_id
                    """),
                    {"org_id": scope.org_id},
                ).fetchone()

                if row:
                    first_cycle = row[1]
                    days = (datetime.now(timezone.utc) - first_cycle).days if first_cycle else 0
                    return {
                        "successful_actions": (row[0] or 0) - (row[2] or 0),
                        "total_cycles": row[0] or 0,
                        "days_active": days,
                        "safety_violations": self._stats["safety_violations"],
                    }
        except Exception as e:
            logger.warning("[AUTONOMY] Failed to load stats: %s", e)
        return self._stats

    async def _propose_graduation(
        self,
        from_level: int,
        to_level: int,
        stats: Dict,
        organization_id: Optional[str] = None,
        *,
        scope: MemoryWriteScope | None = None,
    ) -> None:
        """Create a pending graduation proposal for human review."""
        scope = scope or self._resolve_autonomy_scope(organization_id, write=True)
        if not self._scope_allows_autonomy(scope):
            self._log_scope_blocked("propose_graduation", scope)
            return

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory
            import json

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_autonomy_state
                        (organization_id, key, value, updated_at)
                        VALUES (:org_id, 'pending_graduation', :data, NOW())
                        ON CONFLICT (organization_id, key)
                        DO UPDATE SET value = :data, updated_at = NOW()
                    """),
                    {
                        "org_id": scope.org_id,
                        "data": json.dumps({
                            "from_level": from_level,
                            "to_level": to_level,
                            "stats": stats,
                            "proposed_at": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False),
                    },
                )
                session.commit()
        except Exception as e:
            logger.warning("[AUTONOMY] Failed to propose graduation: %s", e)

    def _resolve_autonomy_scope(
        self,
        organization_id: Optional[str],
        *,
        write: bool,
    ) -> MemoryWriteScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return MemoryWriteScope(
                org_id=organization_id.strip(),
                state="explicit",
                warnings=[],
                write_allowed=True,
            )
        return resolve_memory_write_scope() if write else resolve_memory_read_scope()

    def _scope_allows_autonomy(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        scope: MemoryWriteScope,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_AUTONOMY_MISSING_ORG_WARNING)
        logger.warning(
            "[AUTONOMY] %s blocked org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


# =============================================================================
# Singleton
# =============================================================================

_manager_instance: Optional[AutonomyManager] = None


def get_autonomy_manager() -> AutonomyManager:
    """Get the singleton AutonomyManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = AutonomyManager()
    return _manager_instance
