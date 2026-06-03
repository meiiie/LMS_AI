"""
Goal Manager — Wiii's dynamic goal lifecycle.

Sprint 176: "Wiii Soul AGI" — Phase 4B

Manages evolving goals based on reflections, user interactions, and skill progress.
Goals flow: PROPOSED → ACTIVE → IN_PROGRESS → COMPLETED / ABANDONED.

Design:
    - Goals auto-proposed from weekly reflections
    - Manual goal creation via API
    - Progress tracked through milestones
    - Feature-gated: living_agent_enable_dynamic_goals
    - Stored in wiii_goals table
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)
from app.engine.living_agent.models import (
    GoalPriority,
    GoalStatus,
    WiiiGoal,
)

logger = logging.getLogger(__name__)
_GOAL_MISSING_ORG_WARNING = "goal_manager_blocked_missing_org_context"


class GoalManager:
    """Manages Wiii's dynamic goals with lifecycle tracking.

    Usage:
        manager = GoalManager()
        goal = await manager.create_goal("Learn Docker", priority="high")
        await manager.update_progress(goal.id, 0.5, milestone="Built first image")
        goals = await manager.get_active_goals()
    """

    async def seed_initial_goals(
        self,
        soul,
        organization_id: Optional[str] = None,
    ) -> int:
        """Create initial goals from soul definition if none exist.

        Sprint 210: Seeds goals from soul.interests.wants_to_learn so
        Wiii starts with aspirations instead of 0 goals. Idempotent.

        Args:
            soul: Soul object with interests.wants_to_learn list.

        Returns:
            Number of goals seeded (0 if already has goals).
        """
        scope = self._resolve_goal_scope(organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("seed_initial_goals", scope)
            return 0
        org_id = scope.org_id

        existing = await self.get_active_goals(org_id)
        if existing:
            return 0  # Already has goals

        seeded = 0
        wants_to_learn = getattr(getattr(soul, 'interests', None), 'wants_to_learn', None) or []
        for topic in wants_to_learn[:3]:
            try:
                goal = await self.create_goal(
                    title=f"Học về: {topic}",
                    description=f"Tìm hiểu và nắm vững kiến thức về {topic}",
                    priority="medium",
                    source="soul_seed",
                    organization_id=org_id,
                )
                if goal:
                    seeded += 1
            except Exception as e:
                logger.debug(
                    "[GOALS] Failed to seed goal topic_hash=%s: %s",
                    hash_memory_identifier(topic),
                    e,
                )

        # One meta-goal from soul identity
        try:
            goal = await self.create_goal(
                title="Giúp đỡ sinh viên hàng hải tốt hơn mỗi ngày",
                description="Mục tiêu dài hạn: trở thành người bạn đồng hành đáng tin cậy cho sinh viên hàng hải Việt Nam",
                priority="high",
                source="soul_seed",
                organization_id=org_id,
            )
            if goal:
                seeded += 1
        except Exception as e:
            logger.debug("[GOALS] Failed to seed meta-goal: %s", e)

        if seeded:
            logger.info("[GOALS] Seeded %d initial goals from soul definition", seeded)
        return seeded

    async def create_goal(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        source: str = "reflection",
        milestones: Optional[List[str]] = None,
        target_date: Optional[datetime] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[WiiiGoal]:
        """Create a new goal.

        New goals start as PROPOSED and need activation.
        """
        scope = self._resolve_goal_scope(organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("create_goal", scope)
            return None

        goal = WiiiGoal(
            title=title,
            description=description,
            status=GoalStatus.PROPOSED,
            priority=GoalPriority(priority) if priority in GoalPriority.__members__.values() else GoalPriority.MEDIUM,
            source=source,
            milestones=milestones or [],
            target_date=target_date,
            organization_id=scope.org_id,
        )

        await self._save_goal(goal)
        logger.info(
            "[GOALS] Created goal title_hash=%s (priority=%s)",
            hash_memory_identifier(title),
            priority,
        )
        return goal

    async def activate_goal(
        self,
        goal_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Move goal from PROPOSED to ACTIVE."""
        return await self._update_status(goal_id, GoalStatus.ACTIVE, organization_id)

    async def start_progress(
        self,
        goal_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Move goal from ACTIVE to IN_PROGRESS."""
        return await self._update_status(goal_id, GoalStatus.IN_PROGRESS, organization_id)

    async def complete_goal(
        self,
        goal_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Mark goal as COMPLETED."""
        return await self._update_status(goal_id, GoalStatus.COMPLETED, organization_id)

    async def abandon_goal(
        self,
        goal_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Mark goal as ABANDONED."""
        return await self._update_status(goal_id, GoalStatus.ABANDONED, organization_id)

    async def update_progress(
        self,
        goal_id: str,
        progress: float,
        milestone: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Update goal progress and optionally record a milestone."""
        scope = self._resolve_goal_scope(organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("update_progress", scope, goal_id=goal_id)
            return False

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                params = {
                    "id": goal_id,
                    "org_id": scope.org_id,
                    "progress": max(0.0, min(1.0, progress)),
                }

                if milestone:
                    # Append milestone to completed list
                    session.execute(
                        text("""
                            UPDATE wiii_goals
                            SET progress = :progress,
                                completed_milestones = completed_milestones || :milestone::jsonb,
                                status = CASE WHEN :progress >= 1.0 THEN 'completed' ELSE status END,
                                completed_at = CASE WHEN :progress >= 1.0 THEN NOW() ELSE completed_at END,
                                updated_at = NOW()
                            WHERE id = :id
                            AND organization_id = :org_id
                        """),
                        {**params, "milestone": json.dumps([milestone])},
                    )
                else:
                    session.execute(
                        text("""
                            UPDATE wiii_goals
                            SET progress = :progress,
                                status = CASE WHEN :progress >= 1.0 THEN 'completed' ELSE status END,
                                completed_at = CASE WHEN :progress >= 1.0 THEN NOW() ELSE completed_at END,
                                updated_at = NOW()
                            WHERE id = :id
                            AND organization_id = :org_id
                        """),
                        params,
                    )
                session.commit()

            if progress >= 1.0:
                logger.info(
                    "[GOALS] Goal completed goal_hash=%s",
                    hash_memory_identifier(goal_id),
                )
            return True
        except Exception as e:
            logger.warning("[GOALS] Failed to update progress: %s", e)
            return False

    async def get_active_goals(
        self,
        organization_id: Optional[str] = None,
    ) -> List[WiiiGoal]:
        """Get all non-terminal goals (proposed, active, in_progress)."""
        return await self._query_goals(
            statuses=["proposed", "active", "in_progress"],
            organization_id=organization_id,
        )

    async def get_all_goals(
        self,
        organization_id: Optional[str] = None,
    ) -> List[WiiiGoal]:
        """Get all goals including completed and abandoned."""
        return await self._query_goals(organization_id=organization_id)

    async def propose_from_reflection(
        self,
        reflection_goals: List[str],
        organization_id: Optional[str] = None,
    ) -> List[WiiiGoal]:
        """Create goals from a weekly reflection's goal list.

        Deduplicates against existing active goals by title similarity.
        """
        existing = await self.get_active_goals(organization_id)
        existing_titles = {g.title.lower() for g in existing}

        created = []
        for goal_text in reflection_goals[:5]:  # Max 5 goals per reflection
            if goal_text.lower() in existing_titles:
                continue
            goal = await self.create_goal(
                title=goal_text,
                source="weekly_reflection",
                organization_id=organization_id,
            )
            if goal:
                created.append(goal)

        if created:
            logger.info("[GOALS] Proposed %d goals from reflection", len(created))
        return created

    async def review_stale_goals(
        self,
        stale_days: int = 14,
        organization_id: Optional[str] = None,
    ) -> int:
        """Auto-abandon goals with no progress for N days.

        Returns number of abandoned goals.
        """
        scope = self._resolve_goal_scope(organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("review_stale_goals", scope)
            return 0

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                result = session.execute(
                    text("""
                        UPDATE wiii_goals
                        SET status = 'abandoned', updated_at = NOW()
                        WHERE status IN ('proposed', 'active', 'in_progress')
                        AND updated_at < NOW() - INTERVAL '1 day' * :days
                        AND progress < 0.1
                        AND organization_id = :org_id
                    """),
                    {"days": stale_days, "org_id": scope.org_id},
                )
                session.commit()
                count = result.rowcount
                if count > 0:
                    logger.info("[GOALS] Auto-abandoned %d stale goals", count)
                return count
        except Exception as e:
            logger.warning("[GOALS] Failed to review stale goals: %s", e)
            return 0

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _update_status(
        self,
        goal_id: str,
        new_status: GoalStatus,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Update goal status."""
        scope = self._resolve_goal_scope(organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("update_status", scope, goal_id=goal_id)
            return False

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                params = {
                    "id": goal_id,
                    "org_id": scope.org_id,
                    "status": new_status.value,
                }
                extra = ""
                if new_status == GoalStatus.COMPLETED:
                    extra = ", completed_at = NOW(), progress = 1.0"

                session.execute(
                    text(f"""
                        UPDATE wiii_goals
                        SET status = :status, updated_at = NOW(){extra}
                        WHERE id = :id
                        AND organization_id = :org_id
                    """),
                    params,
                )
                session.commit()
            return True
        except Exception as e:
            logger.warning("[GOALS] Failed to update status: %s", e)
            return False

    async def _query_goals(
        self,
        statuses: Optional[List[str]] = None,
        organization_id: Optional[str] = None,
    ) -> List[WiiiGoal]:
        """Query goals with optional filters."""
        scope = self._resolve_goal_scope(organization_id, write=False)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("query_goals", scope)
            return []
        org_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                query = """
                    SELECT id, title, description, status, priority, progress,
                           source, milestones, completed_milestones,
                           created_at, target_date, completed_at, organization_id
                    FROM wiii_goals WHERE 1=1
                """
                params = {}
                if statuses:
                    query += " AND status = ANY(:statuses)"
                    params["statuses"] = statuses
                query += " AND organization_id = :org_id"
                params["org_id"] = org_id
                query += " ORDER BY created_at DESC"

                rows = session.execute(text(query), params).fetchall()
                return [
                    WiiiGoal(
                        id=row[0],
                        title=row[1],
                        description=row[2] or "",
                        status=GoalStatus(row[3]),
                        priority=GoalPriority(row[4]) if row[4] else GoalPriority.MEDIUM,
                        progress=float(row[5]) if row[5] else 0.0,
                        source=row[6] or "reflection",
                        milestones=json.loads(row[7]) if row[7] else [],
                        completed_milestones=json.loads(row[8]) if row[8] else [],
                        created_at=row[9],
                        target_date=row[10],
                        completed_at=row[11],
                        organization_id=row[12],
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.warning("[GOALS] Failed to query goals: %s", e)
            return []

    async def _save_goal(self, goal: WiiiGoal) -> None:
        """Insert a new goal into the database."""
        scope = self._resolve_goal_scope(goal.organization_id, write=True)
        if not self._scope_allows_goals(scope):
            self._log_scope_blocked("save_goal", scope, goal_id=str(goal.id))
            return
        goal.organization_id = scope.org_id

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_goals
                        (id, title, description, status, priority, progress,
                         source, milestones, completed_milestones,
                         created_at, target_date, organization_id, updated_at)
                        VALUES (:id, :title, :desc, :status, :priority, :progress,
                                :source, :milestones, :completed, NOW(), :target, :org_id, NOW())
                    """),
                    {
                        "id": str(goal.id),
                        "title": goal.title,
                        "desc": goal.description,
                        "status": goal.status.value,
                        "priority": goal.priority.value,
                        "progress": goal.progress,
                        "source": goal.source,
                        "milestones": json.dumps(goal.milestones, ensure_ascii=False),
                        "completed": json.dumps(goal.completed_milestones, ensure_ascii=False),
                        "target": goal.target_date,
                        "org_id": goal.organization_id,
                    },
                )
                session.commit()
        except Exception as e:
            logger.warning("[GOALS] Failed to save goal: %s", e)

    def _resolve_goal_scope(
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

    def _scope_allows_goals(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(
        self,
        operation: str,
        scope: MemoryWriteScope,
        *,
        goal_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_GOAL_MISSING_ORG_WARNING)
        logger.warning(
            "[GOALS] %s blocked goal_hash=%s org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(goal_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )


# =============================================================================
# Singleton
# =============================================================================

_manager_instance: Optional[GoalManager] = None


def get_goal_manager() -> GoalManager:
    """Get the singleton GoalManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = GoalManager()
    return _manager_instance
