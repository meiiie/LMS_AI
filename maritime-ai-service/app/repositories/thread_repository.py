"""
Thread Repository — Server-side conversation index for Wiii

Sprint 16: Virtual Agent-per-User Architecture
Provides CRUD operations for thread_views with ownership checks.

Thread views track all user conversations for:
- Multi-device sync (desktop → mobile)
- Conversation listing/resume
- Session summary storage
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)
_THREAD_REPOSITORY_MISSING_ORG_WARNING = "thread_repository_blocked_missing_org_context"
_THREAD_ORG_FILTER = " AND organization_id = :org_id"

# Sprint 194b (M1): Thread ID segment sanitizer — prevents injection via
# composite thread IDs (org_{X}__user_{Y}__session_{Z}).
_THREAD_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_\-.]")


def _sanitize_thread_segment(segment: str, max_len: int = 128) -> str:
    """Remove characters that could break thread ID format or enable injection."""
    return _THREAD_SEGMENT_RE.sub("", segment)[:max_len]


@dataclass(frozen=True)
class ThreadOrgScope:
    org_id: Optional[str]
    state: str
    warnings: list[str]
    write_allowed: bool


class ThreadRepository:
    """
    Repository for thread_views table CRUD operations.

    Uses the shared database engine (singleton pattern).
    All operations include ownership checks — users can only access their own threads.
    """

    TABLE_NAME = "thread_views"

    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy initialization using shared database engine."""
        if not self._initialized:
            try:
                from app.core.database import get_shared_engine, get_shared_session_factory
                self._engine = get_shared_engine()
                self._session_factory = get_shared_session_factory()
                self._initialized = True
            except Exception as e:
                logger.error("ThreadRepository init failed: %s", e)

    def is_available(self) -> bool:
        """Check if the repository is initialized (no live DB round-trip)."""
        try:
            self._ensure_initialized()
            return self._session_factory is not None
        except Exception as e:
            logger.debug("ThreadRepository availability check failed: %s", e)
            return False

    def _org_scope(
        self,
        organization_id: Optional[str] = None,
        *,
        write: bool = False,
    ) -> tuple[ThreadOrgScope, Optional[str], dict[str, object]]:
        scope = self._resolve_thread_org_scope(
            organization_id=organization_id,
            write=write,
        )
        if not scope.write_allowed or not scope.org_id:
            return scope, None, {}
        return scope, _THREAD_ORG_FILTER, {"org_id": scope.org_id}

    def _resolve_thread_org_scope(
        self,
        *,
        organization_id: Optional[str] = None,
        write: bool = False,
    ) -> ThreadOrgScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return ThreadOrgScope(
                org_id=organization_id.strip(),
                state="explicit",
                warnings=[],
                write_allowed=True,
            )

        from app.engine.semantic_memory.write_audit import (
            resolve_memory_read_scope,
            resolve_memory_write_scope,
        )

        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        return ThreadOrgScope(
            org_id=scope.org_id,
            state=scope.state,
            warnings=list(scope.warnings),
            write_allowed=scope.write_allowed,
        )

    def _log_thread_scope_blocked(
        self,
        operation: str,
        scope: ThreadOrgScope,
        *,
        user_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_THREAD_REPOSITORY_MISSING_ORG_WARNING)
        logger.warning(
            "[THREAD_REPO] %s blocked user_hash=%s thread_hash=%s org_hash=%s "
            "org_scope=%s warnings=%s",
            operation,
            _hash_memory_identifier(user_id),
            _hash_memory_identifier(thread_id),
            _hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    def upsert_thread(
        self,
        thread_id: str,
        user_id: str,
        domain_id: str = "maritime",
        title: Optional[str] = None,
        message_count_increment: int = 1,
        extra_data: Optional[dict] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Create or update a thread view.

        Called after every process_with_multi_agent() to keep the index current.

        Args:
            thread_id: Composite thread ID (user_{id}__session_{id})
            user_id: Owner user ID
            domain_id: Domain plugin ID
            title: Conversation title (auto-generated if None)
            message_count_increment: Number of new messages to add to count
            extra_data: Additional JSONB data (e.g., summary)
            organization_id: Organization ID for multi-tenant isolation (Sprint 24)

        Returns:
            Dict with thread data, or None on failure
        """
        self._ensure_initialized()
        if not self._session_factory:
            return None

        # Sprint 194b (M1): Sanitize user-provided segments in thread_id
        thread_id = _sanitize_thread_segment(thread_id, max_len=512)
        user_id = _sanitize_thread_segment(user_id)

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_thread_scope_blocked(
                "upsert_thread",
                scope,
                user_id=user_id,
                thread_id=thread_id,
            )
            return None

        now = datetime.now(timezone.utc)

        try:
            with self._session_factory() as session:
                # Check if thread exists
                result = session.execute(
                    text(
                        f"SELECT thread_id, message_count, extra_data "
                        f"FROM {self.TABLE_NAME} "
                        f"WHERE thread_id = :thread_id AND user_id = :user_id"
                        f"{org_filter}"
                    ),
                    {"thread_id": thread_id, "user_id": user_id, **org_params},
                ).fetchone()

                if result:
                    # Update existing thread
                    import json as _json
                    current_count = result[1] or 0
                    current_extra = result[2] or {}
                    if isinstance(current_extra, str):
                        try:
                            current_extra = _json.loads(current_extra)
                        except (ValueError, TypeError):
                            current_extra = {}

                    if extra_data:
                        current_extra.update(extra_data)

                    # Build UPDATE — conditional title clause
                    update_sql = (
                        f"UPDATE {self.TABLE_NAME} SET "
                        f"message_count = :count, "
                        f"last_message_at = :now, "
                        f"updated_at = :now, "
                        f"extra_data = CAST(:extra AS jsonb)"
                    )
                    if title:
                        update_sql += ", title = :title"
                    update_sql += (
                        " WHERE thread_id = :thread_id AND user_id = :user_id"
                        f"{org_filter}"
                    )

                    session.execute(
                        text(update_sql),
                        {
                            "thread_id": thread_id,
                            "user_id": user_id,
                            "count": current_count + message_count_increment,
                            "now": now,
                            "extra": _json.dumps(current_extra, ensure_ascii=False),
                            **({"title": title} if title else {}),
                            **org_params,
                        },
                    )
                else:
                    # Insert new thread
                    import json
                    session.execute(
                        text(
                            f"INSERT INTO {self.TABLE_NAME} "
                            f"(thread_id, user_id, domain_id, title, message_count, "
                            f"last_message_at, created_at, updated_at, extra_data, "
                            f"organization_id) "
                            f"VALUES (:thread_id, :user_id, :domain_id, :title, "
                            f":count, :now, :now, :now, CAST(:extra AS jsonb), :org_id)"
                        ),
                        {
                            "thread_id": thread_id,
                            "user_id": user_id,
                            "domain_id": domain_id,
                            "title": title or "Cuộc trò chuyện mới",
                            "count": message_count_increment,
                            "now": now,
                            "extra": json.dumps(extra_data or {}),
                            **org_params,
                        },
                    )

                session.commit()

                # Sprint 79: Include message_count for milestone detection
                if result:
                    new_count = (result[1] or 0) + message_count_increment
                else:
                    new_count = message_count_increment

                return {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "domain_id": domain_id,
                    "title": title or "Cuộc trò chuyện mới",
                    "message_count": new_count,
                }

        except Exception as e:
            logger.error("Thread upsert failed: %s", e)
            return None

    def list_threads(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
        organization_id: Optional[str] = None,
    ) -> list[dict]:
        """
        List threads for a user, ordered by last_message_at DESC.

        Args:
            user_id: Owner user ID (ownership filter)
            limit: Max threads to return (default 50)
            offset: Pagination offset
            include_deleted: Whether to include soft-deleted threads
            organization_id: Filter by org (Sprint 24, multi-tenant)

        Returns:
            List of thread view dicts
        """
        self._ensure_initialized()
        if not self._session_factory:
            return []
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_thread_scope_blocked(
                "list_threads",
                scope,
                user_id=user_id,
            )
            return []

        try:
            with self._session_factory() as session:
                where_clause = "WHERE user_id = :user_id"
                params: dict = {
                    "user_id": user_id,
                    "limit": limit,
                    "offset": offset,
                    **org_params,
                }
                if not include_deleted:
                    where_clause += " AND (is_deleted = false OR is_deleted IS NULL)"
                where_clause += org_filter

                result = session.execute(
                    text(
                        f"SELECT thread_id, user_id, domain_id, title, "
                        f"message_count, last_message_at, created_at, updated_at, "
                        f"extra_data, is_deleted "
                        f"FROM {self.TABLE_NAME} "
                        f"{where_clause} "
                        f"ORDER BY COALESCE(last_message_at, created_at) DESC "
                        f"LIMIT :limit OFFSET :offset"
                    ),
                    params,
                ).fetchall()

                return [self._row_to_dict(row) for row in result]

        except Exception as e:
            logger.error("Thread list failed: %s", e)
            return []

    def get_thread(
        self,
        thread_id: str,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Get a single thread by ID, optionally with ownership check.

        Args:
            thread_id: Thread ID to retrieve
            user_id: User ID for ownership verification (None = no ownership filter)
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            Thread dict, or None if not found
        """
        self._ensure_initialized()
        if not self._session_factory:
            return None

        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_thread_scope_blocked(
                "get_thread",
                scope,
                user_id=user_id,
                thread_id=thread_id,
            )
            return None

        try:
            with self._session_factory() as session:
                if user_id is not None:
                    query = text(
                        f"SELECT thread_id, user_id, domain_id, title, "
                        f"message_count, last_message_at, created_at, updated_at, "
                        f"extra_data, is_deleted "
                        f"FROM {self.TABLE_NAME} "
                        f"WHERE thread_id = :thread_id AND user_id = :user_id"
                        f"{org_filter}"
                    )
                    params: dict = {
                        "thread_id": thread_id,
                        "user_id": user_id,
                        **org_params,
                    }
                else:
                    query = text(
                        f"SELECT thread_id, user_id, domain_id, title, "
                        f"message_count, last_message_at, created_at, updated_at, "
                        f"extra_data, is_deleted "
                        f"FROM {self.TABLE_NAME} "
                        f"WHERE thread_id = :thread_id"
                        f"{org_filter}"
                    )
                    params = {"thread_id": thread_id, **org_params}
                result = session.execute(query, params).fetchone()

                if not result:
                    return None

                return self._row_to_dict(result)

        except Exception as e:
            logger.error("Thread get failed: %s", e)
            return None

    def delete_thread(
        self,
        thread_id: str,
        user_id: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """
        Soft-delete a thread (set is_deleted=true).

        Args:
            thread_id: Thread ID to delete
            user_id: User ID for ownership verification
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            True if deleted, False if not found or not owned
        """
        self._ensure_initialized()
        if not self._session_factory:
            return False

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_thread_scope_blocked(
                "delete_thread",
                scope,
                user_id=user_id,
                thread_id=thread_id,
            )
            return False

        try:
            with self._session_factory() as session:
                params: dict = {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "now": datetime.now(timezone.utc),
                    **org_params,
                }

                result = session.execute(
                    text(
                        f"UPDATE {self.TABLE_NAME} "
                        f"SET is_deleted = true, updated_at = :now "
                        f"WHERE thread_id = :thread_id AND user_id = :user_id "
                        f"AND (is_deleted = false OR is_deleted IS NULL)"
                        f"{org_filter}"
                    ),
                    params,
                )
                session.commit()
                return result.rowcount > 0

        except Exception as e:
            logger.error("Thread delete failed: %s", e)
            return False

    def rename_thread(
        self,
        thread_id: str,
        user_id: str,
        title: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """
        Rename a thread with ownership check.

        Args:
            thread_id: Thread ID to rename
            user_id: User ID for ownership verification
            title: New title
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            True if renamed, False if not found or not owned
        """
        self._ensure_initialized()
        if not self._session_factory:
            return False

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_thread_scope_blocked(
                "rename_thread",
                scope,
                user_id=user_id,
                thread_id=thread_id,
            )
            return False

        try:
            with self._session_factory() as session:
                params: dict = {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "title": title,
                    "now": datetime.now(timezone.utc),
                    **org_params,
                }

                result = session.execute(
                    text(
                        f"UPDATE {self.TABLE_NAME} "
                        f"SET title = :title, updated_at = :now "
                        f"WHERE thread_id = :thread_id AND user_id = :user_id"
                        f"{org_filter}"
                    ),
                    params,
                )
                session.commit()
                return result.rowcount > 0

        except Exception as e:
            logger.error("Thread rename failed: %s", e)
            return False

    def update_extra_data(
        self,
        thread_id: str,
        user_id: str,
        extra_data: dict,
        organization_id: Optional[str] = None,
    ) -> bool:
        """
        Merge extra_data into a thread's JSONB field.

        Used for storing session summaries (Phase 2).

        Args:
            thread_id: Thread ID
            user_id: User ID for ownership verification
            extra_data: Dict to merge into existing extra_data
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            True if updated
        """
        self._ensure_initialized()
        if not self._session_factory:
            return False

        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_thread_scope_blocked(
                "update_extra_data",
                scope,
                user_id=user_id,
                thread_id=thread_id,
            )
            return False

        try:
            import json
            with self._session_factory() as session:
                params: dict = {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "extra": json.dumps(extra_data),
                    "now": datetime.now(timezone.utc),
                    **org_params,
                }

                result = session.execute(
                    text(
                        f"UPDATE {self.TABLE_NAME} "
                        f"SET extra_data = COALESCE(extra_data, '{{}}'::jsonb) || CAST(:extra AS jsonb), "
                        f"updated_at = :now "
                        f"WHERE thread_id = :thread_id AND user_id = :user_id"
                        f"{org_filter}"
                    ),
                    params,
                )
                session.commit()
                return result.rowcount > 0

        except Exception as e:
            logger.error("Thread extra_data update failed: %s", e)
            return False

    def get_threads_with_summaries(
        self,
        user_id: str,
        limit: int = 15,
        organization_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Get recent threads that have summaries (for Layer 3 context).

        Used by SessionSummarizer.get_recent_summaries().

        Args:
            user_id: Owner user ID
            limit: Max threads to return
            organization_id: Organization ID for multi-tenant isolation

        Returns:
            List of dicts with thread_id, title, summary, last_message_at
        """
        self._ensure_initialized()
        if not self._session_factory:
            return []

        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_thread_scope_blocked(
                "get_threads_with_summaries",
                scope,
                user_id=user_id,
            )
            return []

        try:
            with self._session_factory() as session:
                params: dict = {"user_id": user_id, "limit": limit, **org_params}

                result = session.execute(
                    text(
                        f"SELECT thread_id, title, "
                        f"extra_data->>'summary' as summary, "
                        f"last_message_at "
                        f"FROM {self.TABLE_NAME} "
                        f"WHERE user_id = :user_id "
                        f"AND extra_data ? 'summary' "
                        f"AND (is_deleted = false OR is_deleted IS NULL)"
                        f"{org_filter} "
                        f"ORDER BY last_message_at DESC "
                        f"LIMIT :limit"
                    ),
                    params,
                ).fetchall()

                return [
                    {
                        "thread_id": row[0],
                        "title": row[1],
                        "summary": row[2],
                        "last_message_at": str(row[3]) if row[3] else None,
                    }
                    for row in result
                ]

        except Exception as e:
            logger.error("Thread summaries retrieval failed: %s", e)
            return []

    def count_threads(
        self,
        user_id: str,
        organization_id: Optional[str] = None,
    ) -> int:
        """Count active (non-deleted) threads for a user."""
        self._ensure_initialized()
        if not self._session_factory:
            return 0

        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_thread_scope_blocked(
                "count_threads",
                scope,
                user_id=user_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                params: dict = {"user_id": user_id, **org_params}

                result = session.execute(
                    text(
                        f"SELECT COUNT(*) FROM {self.TABLE_NAME} "
                        f"WHERE user_id = :user_id "
                        f"AND (is_deleted = false OR is_deleted IS NULL)"
                        f"{org_filter}"
                    ),
                    params,
                ).scalar()
                return result or 0

        except Exception as e:
            logger.error("Thread count failed: %s", e)
            return 0

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a database row to a dict."""
        return {
            "thread_id": row[0],
            "user_id": row[1],
            "domain_id": row[2],
            "title": row[3],
            "message_count": row[4],
            "last_message_at": str(row[5]) if row[5] else None,
            "created_at": str(row[6]) if row[6] else None,
            "updated_at": str(row[7]) if row[7] else None,
            "extra_data": row[8] if row[8] else {},
            "is_deleted": row[9] if len(row) > 9 else False,
        }


# =============================================================================
# Singleton
# =============================================================================

_thread_repo: Optional[ThreadRepository] = None


def get_thread_repository() -> ThreadRepository:
    """Get or create the global ThreadRepository singleton."""
    global _thread_repo
    if _thread_repo is None:
        _thread_repo = ThreadRepository()
    return _thread_repo


def _hash_memory_identifier(value) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)
