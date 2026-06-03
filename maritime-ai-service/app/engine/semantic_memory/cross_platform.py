"""
Cross-Platform Memory Sync — Memory merge on OTP link + cross-platform context.

Sprint 177: "Học Thật — Nhớ Sâu" — Feature B

Handles:
    1. Memory merge when OTP links a messaging identity to a canonical user
    2. Conflict resolution (higher confidence wins, tie-break by recency)
    3. Cross-platform activity summary for context injection
    4. Platform activity tracking for proactive messaging decisions

Design:
    - Singleton pattern (get_cross_platform_memory())
    - Uses UPDATE on existing semantic_memories rows (no migration needed)
    - Merge provenance stored in metadata JSON
    - Feature-gated: enable_cross_platform_memory=False
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)


class CrossPlatformMemory:
    """Manages memory merge + cross-platform context injection.

    Usage:
        merger = get_cross_platform_memory()
        # On OTP link:
        result = await merger.merge_memories("canonical-uuid", "messenger_12345", "messenger")
        # In input_processor:
        summary = await merger.get_cross_platform_summary("user-uuid", "desktop")
    """

    async def merge_memories(
        self,
        canonical_user_id: str,
        legacy_user_id: str,
        channel_type: str = "",
        session_id: str | None = None,
    ) -> Dict[str, int]:
        """Merge semantic memories from legacy user ID to canonical user ID.

        Called after OTP identity linking succeeds. Updates user_id on all
        semantic_memories rows belonging to legacy_user_id.

        Handles duplicate facts by keeping the one with higher confidence
        (importance). Tie-break by recency (updated_at/created_at).

        Args:
            canonical_user_id: The canonical (real) user UUID.
            legacy_user_id: The platform-specific ID (e.g., "messenger_12345").
            channel_type: Source channel for merge provenance.
            session_id: Optional session ID for privacy-safe write audit events.

        Returns:
            {"migrated": N, "duplicates_resolved": M}
        """
        from sqlalchemy import text
        from app.core.database import get_shared_session_factory

        result = {"migrated": 0, "duplicates_resolved": 0}
        scope = resolve_memory_write_scope()
        canonical_hash = hash_memory_identifier(canonical_user_id)
        legacy_hash = hash_memory_identifier(legacy_user_id)

        if not scope.write_allowed or not scope.org_id:
            await self._append_merge_audit(
                canonical_user_id=canonical_user_id,
                session_id=session_id,
                scope=scope,
                result=result,
                status="blocked",
                warnings=["cross_platform_merge_blocked_missing_org_context"],
            )
            logger.warning(
                "[XP_MEMORY] Merge blocked for canonical_hash=%s legacy_hash=%s scope=%s",
                canonical_hash,
                legacy_hash,
                scope.state,
            )
            return result

        try:
            session_factory = get_shared_session_factory()
            with session_factory() as session:
                # 1. Get all legacy memories
                legacy_rows = session.execute(
                    text("""
                        SELECT id, content, importance, memory_type, metadata, created_at
                        FROM semantic_memories
                        WHERE user_id = :legacy_id
                          AND organization_id = :org_id
                    """),
                    {"legacy_id": legacy_user_id, "org_id": scope.org_id},
                ).fetchall()

                if not legacy_rows:
                    await self._append_merge_audit(
                        canonical_user_id=canonical_user_id,
                        session_id=session_id,
                        scope=scope,
                        result=result,
                        status="skipped",
                        warnings=["cross_platform_merge_no_legacy_memories"],
                    )
                    logger.debug(
                        "[XP_MEMORY] No memories to merge for legacy_hash=%s",
                        legacy_hash,
                    )
                    return result

                # 2. Get canonical memories for conflict detection
                canonical_rows = session.execute(
                    text("""
                        SELECT id, content, importance, memory_type, metadata, created_at
                        FROM semantic_memories
                        WHERE user_id = :canonical_id
                          AND organization_id = :org_id
                    """),
                    {"canonical_id": canonical_user_id, "org_id": scope.org_id},
                ).fetchall()

                canonical_contents = {}
                for row in canonical_rows:
                    content = (row[1] or "").strip().lower()
                    if content:
                        canonical_contents[content] = {
                            "id": str(row[0]),
                            "importance": row[2] or 0.5,
                            "created_at": row[5],
                        }

                # 3. Process each legacy memory
                for row in legacy_rows:
                    legacy_id = str(row[0])
                    content = (row[1] or "").strip()
                    importance = row[2] or 0.5
                    metadata = row[4] or {}
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except (json.JSONDecodeError, TypeError):
                            metadata = {}

                    content_key = content.lower()

                    if content_key in canonical_contents:
                        # Conflict — resolve
                        canonical_info = canonical_contents[content_key]
                        resolved = self.resolve_fact_conflict(
                            canonical_importance=canonical_info["importance"],
                            incoming_importance=importance,
                            canonical_created=canonical_info["created_at"],
                            incoming_created=row[5],
                        )

                        if resolved == "incoming":
                            # Incoming wins — update canonical row with incoming data
                            merge_history = metadata.get("merge_history", [])
                            merge_history.append({
                                "from_hash": legacy_hash,
                                "channel": channel_type,
                                "action": "replaced",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            metadata["merge_history"] = merge_history

                            session.execute(
                                text("""
                                    UPDATE semantic_memories SET
                                        importance = :importance,
                                        metadata = :metadata,
                                        updated_at = NOW()
                                    WHERE id = :id
                                      AND organization_id = :org_id
                                """),
                                {
                                    "id": canonical_info["id"],
                                    "org_id": scope.org_id,
                                    "importance": importance,
                                    "metadata": json.dumps(metadata, ensure_ascii=False),
                                },
                            )
                            # Delete incoming duplicate
                            session.execute(
                                text("""
                                    DELETE FROM semantic_memories
                                    WHERE id = :id
                                      AND organization_id = :org_id
                                """),
                                {"id": legacy_id, "org_id": scope.org_id},
                            )
                        else:
                            # Canonical wins — just delete incoming
                            session.execute(
                                text("""
                                    DELETE FROM semantic_memories
                                    WHERE id = :id
                                      AND organization_id = :org_id
                                """),
                                {"id": legacy_id, "org_id": scope.org_id},
                            )

                        result["duplicates_resolved"] += 1
                    else:
                        # No conflict — migrate by updating user_id
                        merge_history = metadata.get("merge_history", [])
                        merge_history.append({
                            "from_hash": legacy_hash,
                            "channel": channel_type,
                            "action": "migrated",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        metadata["merge_history"] = merge_history

                        session.execute(
                            text("""
                                UPDATE semantic_memories SET
                                    user_id = :canonical_id,
                                    organization_id = :org_id,
                                    metadata = :metadata,
                                    updated_at = NOW()
                                WHERE id = :id
                                  AND organization_id = :org_id
                            """),
                            {
                                "id": legacy_id,
                                "canonical_id": canonical_user_id,
                                "org_id": scope.org_id,
                                "metadata": json.dumps(metadata, ensure_ascii=False),
                            },
                        )
                        result["migrated"] += 1

                session.commit()

            logger.info(
                "[XP_MEMORY] Merged %d memories (%d duplicates resolved) "
                "from legacy_hash=%s to canonical_hash=%s",
                result["migrated"], result["duplicates_resolved"],
                legacy_hash, canonical_hash,
            )
            await self._append_merge_audit(
                canonical_user_id=canonical_user_id,
                session_id=session_id,
                scope=scope,
                result=result,
                status="saved",
            )
        except Exception as e:
            logger.error(
                "[XP_MEMORY] Memory merge failed for canonical_hash=%s legacy_hash=%s: %s",
                canonical_hash,
                legacy_hash,
                e,
            )
            await self._append_merge_audit(
                canonical_user_id=canonical_user_id,
                session_id=session_id,
                scope=scope,
                result=result,
                status="failed",
                warnings=["cross_platform_merge_failed"],
            )

        return result

    async def _append_merge_audit(
        self,
        *,
        canonical_user_id: str,
        session_id: str | None,
        scope: MemoryWriteScope,
        result: Dict[str, int],
        status: str,
        warnings: list[str] | None = None,
    ) -> None:
        """Append a privacy-safe audit summary for cross-platform merges."""

        payload = build_semantic_memory_write_audit(
            user_id=canonical_user_id,
            session_id=session_id,
            message="",
            response="",
            scope=scope,
            write_kind="cross_platform_memory_merge",
            message_saved=False,
            response_saved=False,
            extract_facts=False,
            stored_fact_count=result.get("migrated", 0),
            stored_insight_count=result.get("duplicates_resolved", 0),
            status=status,
            warnings=warnings,
        )
        await append_semantic_memory_write_audit_event(
            session_id=session_id,
            org_id=scope.org_id,
            payload=payload,
        )

    @staticmethod
    def resolve_fact_conflict(
        canonical_importance: float,
        incoming_importance: float,
        canonical_created: Optional[datetime] = None,
        incoming_created: Optional[datetime] = None,
    ) -> str:
        """Resolve conflicting facts between canonical and incoming memories.

        Higher confidence (importance) wins. Tie-break by recency.

        Returns:
            "canonical" or "incoming" — which version to keep.
        """
        if incoming_importance > canonical_importance:
            return "incoming"
        elif incoming_importance < canonical_importance:
            return "canonical"

        # Tie-break by recency
        if incoming_created and canonical_created:
            if incoming_created > canonical_created:
                return "incoming"
        return "canonical"

    async def get_cross_platform_summary(
        self,
        user_id: str,
        current_channel: str,
        max_items: int = 0,
    ) -> str:
        """Get a summary of recent activity on OTHER platforms.

        Queries recent semantic_memories/sessions on platforms different
        from current_channel, formats as Vietnamese context string.

        Args:
            user_id: Canonical user ID.
            current_channel: Current platform (e.g., "desktop", "messenger").
            max_items: Override for max items (0 = use config default).

        Returns:
            Vietnamese-formatted activity summary, or empty string if none.
        """
        from app.core.config import settings

        if max_items <= 0:
            max_items = settings.cross_platform_context_max_items

        scope = resolve_memory_read_scope()
        user_hash = hash_memory_identifier(user_id)
        if not scope.write_allowed or not scope.org_id:
            logger.warning(
                "[XP_MEMORY] Cross-platform summary blocked for user_hash=%s scope=%s",
                user_hash,
                scope.state,
            )
            return ""

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                # Get recent memories with session_id containing channel info
                rows = session.execute(
                    text("""
                        SELECT content, session_id, memory_type, created_at
                        FROM semantic_memories
                        WHERE user_id = :user_id
                          AND organization_id = :org_id
                          AND session_id IS NOT NULL
                          AND session_id != ''
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    {"user_id": user_id, "org_id": scope.org_id, "limit": max_items * 5},
                ).fetchall()

            if not rows:
                return ""

            # Filter to other platforms
            channel_labels = {
                "messenger": "Messenger",
                "zalo": "Zalo",
                "desktop": "Desktop",
                "web": "Web",
                "telegram": "Telegram",
            }

            other_platform_items = []
            for row in rows:
                content = row[0] or ""
                session_id = row[1] or ""
                created_at = row[3]

                # Extract channel from session_id prefix
                detected_channel = _detect_channel(session_id)
                if not detected_channel or detected_channel == current_channel:
                    continue

                # Format time difference
                time_ago = self._format_time_ago(created_at)
                channel_label = channel_labels.get(detected_channel, detected_channel)

                other_platform_items.append(
                    f"Trên {channel_label}: {content[:100]} ({time_ago})"
                )

                if len(other_platform_items) >= max_items:
                    break

            if not other_platform_items:
                return ""

            return "\n".join(other_platform_items)

        except Exception as e:
            logger.debug(
                "[XP_MEMORY] Cross-platform summary failed for user_hash=%s: %s",
                user_hash,
                e,
            )
            return ""

    async def get_platform_activity(self, user_id: str) -> Dict[str, int]:
        """Get per-platform activity counts for proactive messaging decisions.

        Returns:
            Dict mapping channel → message count.
        """
        scope = resolve_memory_read_scope()
        user_hash = hash_memory_identifier(user_id)
        if not scope.write_allowed or not scope.org_id:
            logger.warning(
                "[XP_MEMORY] Platform activity blocked for user_hash=%s scope=%s",
                user_hash,
                scope.state,
            )
            return {}

        try:
            from sqlalchemy import text
            from app.core.database import get_shared_session_factory

            session_factory = get_shared_session_factory()
            with session_factory() as session:
                rows = session.execute(
                    text("""
                        SELECT session_id, COUNT(*) as cnt
                        FROM semantic_memories
                        WHERE user_id = :user_id
                          AND organization_id = :org_id
                          AND session_id IS NOT NULL
                        GROUP BY session_id
                    """),
                    {"user_id": user_id, "org_id": scope.org_id},
                ).fetchall()

            activity: Dict[str, int] = {}
            for row in rows:
                session_id = row[0] or ""
                count = row[1] or 0
                channel = _detect_channel(session_id)
                if channel:
                    activity[channel] = activity.get(channel, 0) + count

            return activity
        except Exception as e:
            logger.debug(
                "[XP_MEMORY] Platform activity query failed for user_hash=%s: %s",
                user_hash,
                e,
            )
            return {}

    @staticmethod
    def _format_time_ago(dt: Optional[datetime]) -> str:
        """Format a datetime as Vietnamese relative time string."""
        if not dt:
            return ""

        # Always compare in UTC to avoid timezone offset errors
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        diff = now - dt
        minutes = int(diff.total_seconds() / 60)

        if minutes < 60:
            return f"{minutes} phút trước"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h trước"
        days = hours // 24
        return f"{days} ngày trước"


def _detect_channel(session_id: str) -> str:
    """Extract channel from session_id prefix.

    Convention:
        - "messenger_xxx" → "messenger"
        - "zalo_xxx" → "zalo"
        - "telegram_xxx" → "telegram"
        - "user_xxx__session_yyy" → "desktop" (default desktop format)
        - Other → ""
    """
    if not session_id:
        return ""

    known_prefixes = ["messenger", "zalo", "telegram"]
    for prefix in known_prefixes:
        if session_id.startswith(f"{prefix}_"):
            return prefix

    # Default desktop/web format: "user_xxx__session_yyy" or "org_xxx__user_yyy__session_zzz"
    if session_id.startswith("user_"):
        return "desktop"
    if "__user_" in session_id and "__session_" in session_id:
        return "desktop"

    return ""


# =============================================================================
# Singleton
# =============================================================================

_xp_memory_instance: Optional[CrossPlatformMemory] = None


def get_cross_platform_memory() -> CrossPlatformMemory:
    """Get the singleton CrossPlatformMemory instance."""
    global _xp_memory_instance
    if _xp_memory_instance is None:
        _xp_memory_instance = CrossPlatformMemory()
    return _xp_memory_instance
