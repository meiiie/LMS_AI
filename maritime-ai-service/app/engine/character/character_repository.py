"""
Character Repository — CRUD for Wiii's living character state.

Sprint 93: PostgreSQL storage for character blocks and experiences.
Follows existing repository patterns (lazy init, shared engine, session factory).

Sprint 124: Per-user isolation — all block queries now filter by user_id.
Each user gets their own set of character blocks. Default '__global__' for
backward compatibility.

Tables:
    wiii_character_blocks  — Self-editable memory blocks (per-user, Sprint 124)
    wiii_experiences       — Experience log (milestone, learning, feedback)
"""

import logging
import time
from typing import List, Optional

from sqlalchemy import text

from app.engine.character.models import (
    BLOCK_CHAR_LIMITS,
    CharacterBlock,
    CharacterBlockCreate,
    CharacterBlockUpdate,
    CharacterExperience,
    CharacterExperienceCreate,
)

logger = logging.getLogger(__name__)

_DB_RETRY_COOLDOWN_SECONDS = 30.0


class CharacterRepository:
    """Repository for Wiii's character state (blocks + experiences)."""

    BLOCKS_TABLE = "wiii_character_blocks"
    EXPERIENCES_TABLE = "wiii_experiences"

    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._initialized = False
        self._unavailable_until = 0.0
        self._last_unavailable_log_at = 0.0

    def _is_temporarily_unavailable(self) -> bool:
        try:
            from app.core.database import is_shared_database_temporarily_unavailable

            if is_shared_database_temporarily_unavailable():
                return True
        except Exception:
            pass
        return time.monotonic() < self._unavailable_until

    def _mark_unavailable(self, exc: Exception | str) -> None:
        now = time.monotonic()
        self._unavailable_until = max(
            self._unavailable_until,
            now + _DB_RETRY_COOLDOWN_SECONDS,
        )
        try:
            from app.core.database import mark_shared_database_unavailable

            mark_shared_database_unavailable(
                exc,
                cooldown_seconds=_DB_RETRY_COOLDOWN_SECONDS,
            )
        except Exception:
            pass
        if now - self._last_unavailable_log_at > 15:
            logger.warning(
                "CharacterRepository DB temporarily unavailable; using empty living state for %.0fs: %s",
                _DB_RETRY_COOLDOWN_SECONDS,
                exc,
            )
            self._last_unavailable_log_at = now

    def is_available(self) -> bool:
        """Best-effort availability signal without forcing a live DB round-trip."""
        return bool(self._session_factory) and not self._is_temporarily_unavailable()

    def _can_query(self) -> bool:
        if self._is_temporarily_unavailable():
            return False
        self._ensure_initialized()
        return bool(self._session_factory) and not self._is_temporarily_unavailable()

    def _ensure_initialized(self) -> None:
        """Lazy init — load shared engine on first use."""
        if self._initialized:
            return
        try:
            from app.core.database import get_shared_engine, get_shared_session_factory
            self._engine = get_shared_engine()
            self._session_factory = get_shared_session_factory()
            self._initialized = True
            logger.info("CharacterRepository initialized with shared engine")
        except Exception as e:
            logger.warning("CharacterRepository init failed (DB may not be running): %s", e)
            self._mark_unavailable(e)

    # =========================================================================
    # CHARACTER BLOCKS — CRUD
    # =========================================================================

    def get_all_blocks(self, user_id: str = "__global__") -> List[CharacterBlock]:
        """Get all character blocks for a specific user.

        Args:
            user_id: User ID to filter by. Defaults to '__global__' for backward compat.
        """
        if not self._can_query():
            return []

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()
        org_filter = org_where_clause(eff_org_id)

        try:
            with self._session_factory() as session:
                params: dict = {"user_id": user_id}
                if eff_org_id is not None:
                    params["org_id"] = eff_org_id

                result = session.execute(
                    text(f"""
                        SELECT id, label, content, char_limit, version,
                               metadata, created_at, updated_at
                        FROM {self.BLOCKS_TABLE}
                        WHERE user_id = :user_id{org_filter}
                        ORDER BY label
                    """),
                    params,
                )
                rows = result.fetchall()
                return [
                    CharacterBlock(
                        id=row.id,
                        label=row.label,
                        content=row.content,
                        char_limit=row.char_limit,
                        version=row.version,
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error("Failed to get character blocks for user '%s': %s", user_id, e)
            self._mark_unavailable(e)
            return []

    def get_block(self, label: str, user_id: str = "__global__") -> Optional[CharacterBlock]:
        """Get a specific character block by label and user.

        Args:
            label: Block label (learned_lessons, etc.)
            user_id: User ID to filter by. Defaults to '__global__'.
        """
        if not self._can_query():
            return None

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()
        org_filter = org_where_clause(eff_org_id)

        try:
            with self._session_factory() as session:
                params: dict = {"label": label, "user_id": user_id}
                if eff_org_id is not None:
                    params["org_id"] = eff_org_id

                result = session.execute(
                    text(f"""
                        SELECT id, label, content, char_limit, version,
                               metadata, created_at, updated_at
                        FROM {self.BLOCKS_TABLE}
                        WHERE label = :label AND user_id = :user_id{org_filter}
                    """),
                    params,
                )
                row = result.fetchone()
                if not row:
                    return None
                return CharacterBlock(
                    id=row.id,
                    label=row.label,
                    content=row.content,
                    char_limit=row.char_limit,
                    version=row.version,
                    metadata=row.metadata if isinstance(row.metadata, dict) else {},
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
        except Exception as e:
            logger.error("Failed to get block '%s' for user '%s': %s", label, user_id, e)
            self._mark_unavailable(e)
            return None

    def create_block(self, create: CharacterBlockCreate, user_id: str = "__global__") -> Optional[CharacterBlock]:
        """Create a new character block for a specific user.

        Args:
            create: Block creation schema
            user_id: User ID. Defaults to '__global__'.
        """
        if not self._can_query():
            return None

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id
        eff_org_id = get_effective_org_id()

        try:
            with self._session_factory() as session:
                params: dict = {
                    "label": create.label,
                    "content": create.content[:create.char_limit],
                    "char_limit": create.char_limit,
                    "metadata": "{}",
                    "user_id": user_id,
                }
                insert_cols = "label, content, char_limit, metadata, user_id"
                insert_vals = ":label, :content, :char_limit, CAST(:metadata AS jsonb), :user_id"
                if eff_org_id is not None:
                    insert_cols += ", organization_id"
                    insert_vals += ", :org_id"
                    params["org_id"] = eff_org_id

                result = session.execute(
                    text(f"""
                        INSERT INTO {self.BLOCKS_TABLE}
                            ({insert_cols})
                        VALUES ({insert_vals})
                        ON CONFLICT (user_id, label) DO UPDATE
                            SET content = EXCLUDED.content,
                                char_limit = EXCLUDED.char_limit,
                                metadata = EXCLUDED.metadata,
                                updated_at = NOW()
                        RETURNING id, label, content, char_limit, version,
                                  metadata, created_at, updated_at
                    """),
                    params,
                )
                session.commit()
                row = result.fetchone()
                if row:
                    return CharacterBlock(
                        id=row.id,
                        label=row.label,
                        content=row.content,
                        char_limit=row.char_limit,
                        version=row.version,
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
        except Exception as e:
            logger.error("Failed to create block '%s' for user '%s': %s", create.label, user_id, e)
            self._mark_unavailable(e)
        return None

    def update_block(
        self,
        label: str,
        update: CharacterBlockUpdate,
        expected_version: Optional[int] = None,
        user_id: str = "__global__",
    ) -> Optional[CharacterBlock]:
        """Update a character block with optional optimistic locking.

        Args:
            label: Block label
            update: New content or append text
            expected_version: If set, only update if current version matches
            user_id: User ID to scope the update. Defaults to '__global__'.
        """
        if not self._can_query():
            return None

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()
        org_filter = org_where_clause(eff_org_id)

        try:
            with self._session_factory() as session:
                base_params: dict = {"label": label, "user_id": user_id}
                if eff_org_id is not None:
                    base_params["org_id"] = eff_org_id

                # Build update query
                if update.content is not None:
                    # Replace mode
                    char_limit = BLOCK_CHAR_LIMITS.get(label, 1000)
                    new_content = update.content[:char_limit]
                    if expected_version is not None:
                        result = session.execute(
                            text(f"""
                                UPDATE {self.BLOCKS_TABLE}
                                SET content = :content,
                                    version = version + 1,
                                    updated_at = NOW()
                                WHERE label = :label AND user_id = :user_id AND version = :version{org_filter}
                                RETURNING id, label, content, char_limit, version,
                                          metadata, created_at, updated_at
                            """),
                            {**base_params, "content": new_content, "version": expected_version},
                        )
                    else:
                        result = session.execute(
                            text(f"""
                                UPDATE {self.BLOCKS_TABLE}
                                SET content = :content,
                                    version = version + 1,
                                    updated_at = NOW()
                                WHERE label = :label AND user_id = :user_id{org_filter}
                                RETURNING id, label, content, char_limit, version,
                                          metadata, created_at, updated_at
                            """),
                            {**base_params, "content": new_content},
                        )
                elif update.append is not None:
                    # Append mode — respect char_limit
                    result = session.execute(
                        text(f"""
                            UPDATE {self.BLOCKS_TABLE}
                            SET content = LEFT(content || :append, char_limit),
                                version = version + 1,
                                updated_at = NOW()
                            WHERE label = :label AND user_id = :user_id{org_filter}
                            RETURNING id, label, content, char_limit, version,
                                      metadata, created_at, updated_at
                        """),
                        {**base_params, "append": update.append},
                    )
                else:
                    return self.get_block(label, user_id=user_id)

                session.commit()
                row = result.fetchone()
                if row:
                    return CharacterBlock(
                        id=row.id,
                        label=row.label,
                        content=row.content,
                        char_limit=row.char_limit,
                        version=row.version,
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                elif expected_version is not None:
                    logger.warning(
                        "Optimistic lock failed for block '%s' user '%s' (expected version %d)",
                        label, user_id, expected_version,
                    )
        except Exception as e:
            logger.error("Failed to update block '%s' for user '%s': %s", label, user_id, e)
            self._mark_unavailable(e)
        return None

    # =========================================================================
    # EXPERIENCES — Log and query
    # =========================================================================

    def log_experience(self, create: CharacterExperienceCreate) -> Optional[CharacterExperience]:
        """Log a new experience event."""
        if not self._can_query():
            return None

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id
        eff_org_id = get_effective_org_id()

        try:
            with self._session_factory() as session:
                insert_cols = "experience_type, content, importance, user_id, metadata"
                insert_vals = ":type, :content, :importance, :user_id, CAST(:metadata AS jsonb)"
                params: dict = {
                    "type": create.experience_type,
                    "content": create.content,
                    "importance": create.importance,
                    "user_id": create.user_id,
                    "metadata": "{}",
                }
                if eff_org_id is not None:
                    insert_cols += ", organization_id"
                    insert_vals += ", :org_id"
                    params["org_id"] = eff_org_id

                result = session.execute(
                    text(f"""
                        INSERT INTO {self.EXPERIENCES_TABLE}
                            ({insert_cols})
                        VALUES ({insert_vals})
                        RETURNING id, experience_type, content, importance,
                                  user_id, metadata, created_at
                    """),
                    params,
                )
                session.commit()
                row = result.fetchone()
                if row:
                    return CharacterExperience(
                        id=row.id,
                        experience_type=row.experience_type,
                        content=row.content,
                        importance=row.importance,
                        user_id=row.user_id,
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        created_at=row.created_at,
                    )
        except Exception as e:
            logger.error("Failed to log experience: %s", e)
            self._mark_unavailable(e)
        return None

    def get_recent_experiences(
        self,
        limit: int = 20,
        experience_type: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[CharacterExperience]:
        """Get recent experiences, optionally filtered by type and user.

        Sprint 125: Added user_id filter for per-user isolation.
        """
        if not self._can_query():
            return []

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()

        try:
            with self._session_factory() as session:
                # Build WHERE conditions dynamically
                conditions = []
                params: dict = {"limit": limit}

                if experience_type:
                    conditions.append("experience_type = :type")
                    params["type"] = experience_type
                if user_id:
                    conditions.append("user_id = :user_id")
                    params["user_id"] = user_id

                # Add org filter
                org_clause = org_where_clause(eff_org_id)
                if org_clause:
                    # Strip leading " AND " and add as a condition
                    conditions.append(org_clause.lstrip(" AND "))
                    params["org_id"] = eff_org_id

                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
                result = session.execute(
                    text(f"""
                        SELECT id, experience_type, content, importance,
                               user_id, metadata, created_at
                        FROM {self.EXPERIENCES_TABLE}
                        {where_clause}
                        ORDER BY created_at DESC
                        LIMIT :limit
                    """),
                    params,
                )
                rows = result.fetchall()
                return [
                    CharacterExperience(
                        id=row.id,
                        experience_type=row.experience_type,
                        content=row.content,
                        importance=row.importance,
                        user_id=row.user_id,
                        metadata=row.metadata if isinstance(row.metadata, dict) else {},
                        created_at=row.created_at,
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error("Failed to get experiences: %s", e)
            self._mark_unavailable(e)
            return []

    def count_experiences(self) -> int:
        """Count total logged experiences."""
        if not self._can_query():
            return 0

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()
        org_filter = org_where_clause(eff_org_id)

        try:
            with self._session_factory() as session:
                params: dict = {}
                if eff_org_id is not None:
                    params["org_id"] = eff_org_id

                where = f"WHERE 1=1{org_filter}" if org_filter else ""
                result = session.execute(
                    text(f"SELECT COUNT(*) FROM {self.EXPERIENCES_TABLE} {where}"),
                    params,
                )
                return result.scalar() or 0
        except Exception as e:
            logger.error("Failed to count experiences: %s", e)
            self._mark_unavailable(e)
            return 0

    def cleanup_old_experiences(
        self,
        max_age_days: int = 90,
        keep_min: int = 100,
        user_id: Optional[str] = None,
    ) -> int:
        """Delete old experiences while keeping at least keep_min most recent.

        Sprint 98: Experience Log TTL — prevents unbounded growth of
        wiii_experiences table.
        Sprint 125: Added user_id scope for per-user isolation.

        Args:
            max_age_days: Delete experiences older than this many days
            keep_min: Always keep at least this many most recent experiences
            user_id: Scope cleanup to specific user (None = all users)

        Returns:
            Number of deleted experiences
        """
        if not self._can_query():
            return 0

        # Sprint 160b: Org-scoped filtering
        from app.core.org_filter import get_effective_org_id, org_where_clause
        eff_org_id = get_effective_org_id()
        org_filter = org_where_clause(eff_org_id)

        try:
            with self._session_factory() as session:
                # Build user filter
                user_filter = "AND user_id = :user_id" if user_id else ""
                params: dict = {"days": str(max_age_days), "keep_min": keep_min}
                if user_id:
                    params["user_id"] = user_id
                if eff_org_id is not None:
                    params["org_id"] = eff_org_id

                # Check total count first
                total = session.execute(
                    text(f"SELECT COUNT(*) FROM {self.EXPERIENCES_TABLE} WHERE 1=1 {user_filter}{org_filter}"),
                    params,
                ).scalar() or 0

                if total <= keep_min:
                    logger.debug(
                        "[CLEANUP] Only %d experiences (min=%d), skipping",
                        total, keep_min,
                    )
                    return 0

                # Delete old experiences, but always keep the most recent keep_min
                result = session.execute(
                    text(f"""
                        DELETE FROM {self.EXPERIENCES_TABLE}
                        WHERE created_at < NOW() - CAST(:days || ' days' AS INTERVAL)
                          {user_filter}{org_filter}
                          AND id NOT IN (
                              SELECT id FROM {self.EXPERIENCES_TABLE}
                              WHERE 1=1 {user_filter}{org_filter}
                              ORDER BY created_at DESC
                              LIMIT :keep_min
                          )
                    """),
                    params,
                )
                session.commit()
                deleted = result.rowcount or 0

                if deleted > 0:
                    logger.info(
                        "[CLEANUP] Deleted %d old experiences (older than %d days, kept min %d, user=%s)",
                        deleted, max_age_days, keep_min, user_id or "all",
                    )
                return deleted

        except Exception as e:
            logger.error("Failed to cleanup old experiences: %s", e)
            self._mark_unavailable(e)
            return 0


# =============================================================================
# Singleton
# =============================================================================

_character_repo: Optional[CharacterRepository] = None


def get_character_repository() -> CharacterRepository:
    """Get or create CharacterRepository singleton."""
    global _character_repo
    if _character_repo is None:
        _character_repo = CharacterRepository()
    return _character_repo
