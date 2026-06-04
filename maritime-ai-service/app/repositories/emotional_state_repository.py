"""
Emotional State Repository — Persistence for Wiii's emotional snapshots.

Sprint 170: "Linh Hồn Sống"
Sprint 210+: Org scope now uses fail-closed memory read/write resolvers.

Stores and retrieves emotional state snapshots from PostgreSQL.
Uses the shared database engine (singleton pattern from database.py).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from app.core.database import get_shared_session_factory
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)
_EMOTIONAL_REPO_MISSING_ORG_WARNING = "emotional_state_repository_blocked_missing_org_context"


class EmotionalStateRepository:
    """CRUD operations for wiii_emotional_snapshots table."""

    def save_snapshot(
        self,
        primary_mood: str,
        energy_level: float,
        social_battery: float,
        engagement: float,
        trigger_event: Optional[str] = None,
        state_json: Optional[dict] = None,
        organization_id: Optional[str] = None,
    ) -> str:
        """Save an emotional state snapshot.

        Returns:
            The snapshot ID.
        """
        from sqlalchemy import text

        snapshot_id = str(uuid4())
        scope = self._resolve_scope(organization_id, write=True)
        if not self._scope_allows_repo(scope):
            self._log_scope_blocked("save_snapshot", scope)
            return ""

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                session.execute(
                    text("""
                        INSERT INTO wiii_emotional_snapshots
                        (id, primary_mood, energy_level, social_battery, engagement,
                         trigger_event, snapshot_at, organization_id, state_json)
                        VALUES (:id, :mood, :energy, :social, :engagement,
                                :trigger, :snapshot_at, :org_id, :state)
                    """),
                    {
                        "id": snapshot_id,
                        "mood": primary_mood,
                        "energy": energy_level,
                        "social": social_battery,
                        "engagement": engagement,
                        "trigger": trigger_event,
                        "snapshot_at": datetime.now(timezone.utc),
                        "org_id": scope.org_id,
                        "state": json.dumps(state_json or {}, ensure_ascii=False),
                    },
                )
                session.commit()
                logger.debug(
                    "[EMOTION_REPO] Saved snapshot: mood=%s org_hash=%s",
                    primary_mood,
                    hash_memory_identifier(scope.org_id),
                )
                return snapshot_id

        except Exception as e:
            logger.error("[EMOTION_REPO] Failed to save snapshot: %s", e)
            raise

    def get_latest(self, organization_id: Optional[str] = None) -> Optional[Dict]:
        """Get the most recent emotional snapshot.

        Returns:
            Dict with snapshot data, or None if no snapshots exist.
        """
        from sqlalchemy import text

        scope = self._resolve_scope(organization_id, write=False)
        if not self._scope_allows_repo(scope):
            self._log_scope_blocked("get_latest", scope)
            return None

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                result = session.execute(
                    text("""
                        SELECT id, primary_mood, energy_level, social_battery, engagement,
                               trigger_event, snapshot_at, state_json
                        FROM wiii_emotional_snapshots
                        WHERE organization_id = :org_id
                        ORDER BY snapshot_at DESC
                        LIMIT 1
                    """),
                    {"org_id": scope.org_id},
                ).fetchone()
                if not result:
                    return None

                return {
                    "id": result[0],
                    "primary_mood": result[1],
                    "energy_level": result[2],
                    "social_battery": result[3],
                    "engagement": result[4],
                    "trigger_event": result[5],
                    "snapshot_at": result[6].isoformat() if result[6] else None,
                    "state_json": json.loads(result[7]) if result[7] else {},
                }

        except Exception as e:
            logger.error("[EMOTION_REPO] Failed to get latest snapshot: %s", e)
            return None

    def get_history(
        self,
        hours: int = 24,
        organization_id: Optional[str] = None,
    ) -> List[Dict]:
        """Get emotional snapshots from the last N hours.

        Args:
            hours: Number of hours to look back.
            organization_id: Optional org filter.

        Returns:
            List of snapshot dicts, ordered by time ascending.
        """
        from sqlalchemy import text

        scope = self._resolve_scope(organization_id, write=False)
        if not self._scope_allows_repo(scope):
            self._log_scope_blocked("get_history", scope)
            return []

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                results = session.execute(
                    text("""
                        SELECT id, primary_mood, energy_level, social_battery, engagement,
                               trigger_event, snapshot_at
                        FROM wiii_emotional_snapshots
                        WHERE snapshot_at >= NOW() - INTERVAL '1 hour' * :hours
                        AND organization_id = :org_id
                        ORDER BY snapshot_at ASC
                    """),
                    {"hours": hours, "org_id": scope.org_id},
                ).fetchall()
                return [
                    {
                        "id": row[0],
                        "primary_mood": row[1],
                        "energy_level": row[2],
                        "social_battery": row[3],
                        "engagement": row[4],
                        "trigger_event": row[5],
                        "snapshot_at": row[6].isoformat() if row[6] else None,
                    }
                    for row in results
                ]

        except Exception as e:
            logger.error("[EMOTION_REPO] Failed to get history: %s", e)
            return []

    def cleanup_old_snapshots(
        self,
        keep_days: int = 30,
        organization_id: Optional[str] = None,
    ) -> int:
        """Delete emotional snapshots older than N days.

        Returns:
            Number of deleted rows.
        """
        from sqlalchemy import text

        scope = self._resolve_scope(organization_id, write=True)
        if not self._scope_allows_repo(scope):
            self._log_scope_blocked("cleanup_old_snapshots", scope)
            return 0

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                result = session.execute(
                    text("""
                        DELETE FROM wiii_emotional_snapshots
                        WHERE snapshot_at < NOW() - INTERVAL '1 day' * :keep_days
                        AND organization_id = :org_id
                    """),
                    {"keep_days": keep_days, "org_id": scope.org_id},
                )
                session.commit()
                count = result.rowcount
                if count > 0:
                    logger.info(
                        "[EMOTION_REPO] Cleaned up %d old snapshots org_hash=%s",
                        count,
                        hash_memory_identifier(scope.org_id),
                    )
                return count

        except Exception as e:
            logger.error("[EMOTION_REPO] Failed to cleanup: %s", e)
            return 0

    def _resolve_scope(
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

    def _scope_allows_repo(self, scope: MemoryWriteScope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_scope_blocked(self, operation: str, scope: MemoryWriteScope) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_EMOTIONAL_REPO_MISSING_ORG_WARNING)
        logger.warning(
            "[EMOTION_REPO] %s blocked org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )
