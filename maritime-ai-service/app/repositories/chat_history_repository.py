"""Chat history repository backed only by ``chat_history``.

This repository is the canonical storage path for session/message history.
Legacy ``chat_sessions`` and ``chat_messages`` tables are no longer used.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Union
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from sqlalchemy import inspect, select, text

from app.core.config import settings
from app.models.database import Base, ChatHistoryModel

logger = logging.getLogger(__name__)
_CHAT_HISTORY_MISSING_ORG_WARNING = "chat_history_blocked_missing_org_context"
_CHAT_HISTORY_ORG_FILTER = " AND organization_id = :org_id"


def _normalize_session_id(session_id: Union[str, UUID]) -> UUID:
    """Normalize any session identifier to a stable UUID."""
    if isinstance(session_id, UUID):
        return session_id
    try:
        return UUID(str(session_id))
    except (ValueError, AttributeError):
        return uuid5(NAMESPACE_DNS, str(session_id))


@dataclass
class ChatMessage:
    """Repository DTO for a single chat message."""

    id: UUID
    session_id: UUID
    role: str
    content: str
    created_at: datetime
    is_blocked: bool = False
    block_reason: Optional[str] = None


@dataclass
class ChatSession:
    """Repository DTO for a chat session."""

    session_id: UUID
    user_id: str
    user_name: Optional[str]
    created_at: datetime
    messages: List[ChatMessage]


@dataclass(frozen=True)
class ChatHistoryOrgScope:
    org_id: Optional[str]
    state: str
    warnings: list[str]
    write_allowed: bool


class ChatHistoryRepository:
    """CRUD access to the ``chat_history`` table."""

    WINDOW_SIZE = getattr(settings, "context_window_size", 50)

    def __init__(self, database_url: Optional[str] = None):
        self._engine = None
        self._session_factory = None
        self._available = False
        self._has_chat_history = False
        self._init_connection()

    def _init_connection(self) -> None:
        """Initialize database connection using the shared engine."""
        try:
            from app.core.database import (
                get_shared_engine,
                get_shared_session_factory,
            )

            self._engine = get_shared_engine()
            self._session_factory = get_shared_session_factory()

            with self._session_factory() as session:
                session.execute(select(1))

            self._has_chat_history = inspect(self._engine).has_table("chat_history")
            if self._has_chat_history:
                logger.info("Chat history repository bound to chat_history")
            else:
                logger.warning(
                    "chat_history table is missing; legacy chat schema is unsupported"
                )

            self._available = True
            logger.info("Chat history repository using shared database engine")
        except Exception as exc:
            logger.warning("Chat history repository connection failed: %s", exc)
            try:
                from app.core.database import mark_shared_database_unavailable

                mark_shared_database_unavailable(exc)
            except Exception:
                pass
            self._available = False

    def is_available(self) -> bool:
        """Check if the repository can talk to the database."""
        return self._available

    def ensure_tables(self) -> None:
        """Create/upgrade the canonical chat_history table if needed."""
        if not self._available:
            return

        try:
            Base.metadata.create_all(
                self._engine,
                tables=[ChatHistoryModel.__table__],
            )
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE chat_history "
                        "ADD COLUMN IF NOT EXISTS user_name TEXT"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chat_history_session_id "
                        "ON chat_history (session_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chat_history_user_id "
                        "ON chat_history (user_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_chat_history_org_id "
                        "ON chat_history (organization_id)"
                    )
                )
            self._has_chat_history = True
            logger.info("Chat history tables created/verified")
        except Exception as exc:
            logger.error("Failed to create/verify chat_history table: %s", exc)

    def _ensure_chat_history_ready(self) -> bool:
        """Ensure the canonical table exists before running queries."""
        if not self._available:
            return False
        if self._has_chat_history:
            return True

        self.ensure_tables()
        if self._has_chat_history:
            return True
        try:
            self._has_chat_history = inspect(self._engine).has_table("chat_history")
        except Exception as exc:
            logger.error("Failed to re-check chat_history table: %s", exc)
            self._has_chat_history = False
        return self._has_chat_history

    @staticmethod
    def _row_session_id(row_value: Union[str, UUID]) -> UUID:
        if isinstance(row_value, UUID):
            return row_value
        return UUID(str(row_value))

    def _org_scope(
        self,
        organization_id: Optional[str] = None,
        *,
        write: bool = False,
    ) -> tuple[ChatHistoryOrgScope, Optional[str], dict[str, object]]:
        scope = self._resolve_chat_history_org_scope(
            organization_id=organization_id,
            write=write,
        )
        if not scope.write_allowed or not scope.org_id:
            return scope, None, {}
        params: dict[str, object] = {}
        params["org_id"] = scope.org_id
        return scope, _CHAT_HISTORY_ORG_FILTER, params

    def _resolve_chat_history_org_scope(
        self,
        *,
        organization_id: Optional[str] = None,
        write: bool = False,
    ) -> ChatHistoryOrgScope:
        if isinstance(organization_id, str) and organization_id.strip():
            return ChatHistoryOrgScope(
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
        return ChatHistoryOrgScope(
            org_id=scope.org_id,
            state=scope.state,
            warnings=list(scope.warnings),
            write_allowed=scope.write_allowed,
        )

    def _log_chat_history_scope_blocked(
        self,
        operation: str,
        scope: ChatHistoryOrgScope,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_CHAT_HISTORY_MISSING_ORG_WARNING)
        logger.warning(
            "[CHAT_HISTORY] %s blocked user_hash=%s session_hash=%s org_hash=%s "
            "org_scope=%s warnings=%s",
            operation,
            _hash_memory_identifier(user_id),
            _hash_memory_identifier(session_id),
            _hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    def _rows_to_messages(self, rows, fallback_session_id: UUID) -> List[ChatMessage]:
        return [
            ChatMessage(
                id=self._row_session_id(row[0]),
                session_id=(
                    self._row_session_id(row[2])
                    if row[2] is not None
                    else fallback_session_id
                ),
                role=row[3],
                content=row[4],
                created_at=row[5],
                is_blocked=bool(row[6]) if len(row) > 6 else False,
                block_reason=row[7] if len(row) > 7 else None,
            )
            for row in reversed(rows)
        ]

    def get_or_create_session(
        self,
        user_id: str,
        organization_id: Optional[str] = None,
    ) -> Optional[ChatSession]:
        """Return the latest session for the user or a fresh transient session."""
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "get_or_create_session",
                scope,
                user_id=user_id,
            )
            return None
        if not self._ensure_chat_history_ready():
            return None

        try:
            params = {"user_id": user_id, **org_params}

            with self._session_factory() as session:
                row = session.execute(
                    text(
                        f"""
                        SELECT session_id, MAX(created_at) AS created_at
                        FROM chat_history
                        WHERE user_id = :user_id
                        {org_filter}
                        GROUP BY session_id
                        ORDER BY MAX(created_at) DESC
                        LIMIT 1
                        """
                    ),
                    params,
                ).fetchone()

            if row:
                return ChatSession(
                    session_id=self._row_session_id(row[0]),
                    user_id=user_id,
                    user_name=None,
                    created_at=row[1] or datetime.now(timezone.utc),
                    messages=[],
                )

            return ChatSession(
                session_id=uuid4(),
                user_id=user_id,
                user_name=None,
                created_at=datetime.now(timezone.utc),
                messages=[],
            )
        except Exception as exc:
            logger.error("Failed to get/create session: %s", exc)
            return None

    def save_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        is_blocked: bool = False,
        block_reason: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> Optional[ChatMessage]:
        """Persist a message into chat_history."""
        norm_session_id = _normalize_session_id(session_id)
        effective_user_id = user_id or str(norm_session_id)
        scope, _, org_params = self._org_scope(organization_id, write=True)
        if not org_params.get("org_id"):
            self._log_chat_history_scope_blocked(
                "save_message",
                scope,
                user_id=effective_user_id,
                session_id=str(norm_session_id),
            )
            return None
        if not self._ensure_chat_history_ready():
            return None

        try:
            msg_id = uuid4()
            created_at = datetime.now(timezone.utc)
            with self._session_factory() as session:
                session.execute(
                    text(
                        """
                        INSERT INTO chat_history (
                            id,
                            user_id,
                            session_id,
                            role,
                            content,
                            created_at,
                            is_blocked,
                            block_reason,
                            organization_id
                        )
                        VALUES (
                            :id,
                            :user_id,
                            :session_id,
                            :role,
                            :content,
                            :created_at,
                            :is_blocked,
                            :block_reason,
                            :org_id
                        )
                        """
                    ),
                    {
                        "id": str(msg_id),
                        "user_id": effective_user_id,
                        "session_id": str(norm_session_id),
                        "role": role,
                        "content": content,
                        "created_at": created_at,
                        "is_blocked": is_blocked,
                        "block_reason": block_reason,
                        "org_id": org_params.get("org_id"),
                    },
                )
                session.commit()

            return ChatMessage(
                id=msg_id,
                session_id=norm_session_id,
                role=role,
                content=content,
                created_at=created_at,
                is_blocked=is_blocked,
                block_reason=block_reason,
            )
        except Exception as exc:
            logger.error("Failed to save message: %s", exc)
            return None

    def get_recent_messages(
        self,
        session_id: UUID,
        limit: Optional[int] = None,
        user_id: Optional[str] = None,
        include_blocked: bool = False,
        organization_id: Optional[str] = None,
    ) -> List[ChatMessage]:
        """Return recent messages in chronological order."""
        norm_session_id = _normalize_session_id(session_id)
        limit = limit or self.WINDOW_SIZE
        blocked_filter = (
            ""
            if include_blocked
            else "AND (is_blocked = FALSE OR is_blocked IS NULL)"
        )
        query_field = "user_id" if user_id else "session_id"
        query_value = user_id if user_id else str(norm_session_id)
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "get_recent_messages",
                scope,
                user_id=user_id,
                session_id=str(norm_session_id),
            )
            return []
        if not self._ensure_chat_history_ready():
            return []

        try:
            params = {
                "query_value": query_value,
                "limit": limit,
                **org_params,
            }

            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT id, user_id, session_id, role, content, created_at,
                               COALESCE(is_blocked, FALSE) AS is_blocked, block_reason
                        FROM chat_history
                        WHERE {query_field} = :query_value
                        {blocked_filter}
                        {org_filter}
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                ).fetchall()

            return self._rows_to_messages(rows, norm_session_id)
        except Exception as exc:
            logger.error("Failed to get messages: %s", exc)
            return []

    def get_session_history(
        self,
        session_id: UUID,
        limit: int = 100,
        offset: int = 0,
        include_blocked: bool = False,
        organization_id: Optional[str] = None,
    ) -> tuple[List[ChatMessage], int]:
        """Get paginated history for a session."""
        norm_session_id = _normalize_session_id(session_id)
        blocked_filter = (
            ""
            if include_blocked
            else "AND (is_blocked = FALSE OR is_blocked IS NULL)"
        )
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "get_session_history",
                scope,
                session_id=str(norm_session_id),
            )
            return [], 0
        if not self._ensure_chat_history_ready():
            return [], 0

        try:
            count_params = {"session_id": str(norm_session_id), **org_params}
            query_params = {
                "session_id": str(norm_session_id),
                "limit": limit,
                "offset": offset,
                **org_params,
            }

            with self._session_factory() as session:
                total = (
                    session.execute(
                        text(
                            f"""
                            SELECT COUNT(*)
                            FROM chat_history
                            WHERE session_id = :session_id
                            {blocked_filter}
                            {org_filter}
                            """
                        ),
                        count_params,
                    ).scalar()
                    or 0
                )

                rows = session.execute(
                    text(
                        f"""
                        SELECT id, user_id, session_id, role, content, created_at,
                               COALESCE(is_blocked, FALSE) AS is_blocked, block_reason
                        FROM chat_history
                        WHERE session_id = :session_id
                        {blocked_filter}
                        {org_filter}
                        ORDER BY created_at DESC
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    query_params,
                ).fetchall()

            return self._rows_to_messages(rows, norm_session_id), total
        except Exception as exc:
            logger.error("Failed to get session history: %s", exc)
            return [], 0

    def update_user_name(
        self,
        session_id: UUID,
        user_name: str,
        organization_id: Optional[str] = None,
    ) -> bool:
        """Persist the discovered user name on existing rows of a session."""
        norm_session_id = _normalize_session_id(session_id)
        scope, org_filter, org_params = self._org_scope(
            organization_id,
            write=True,
        )
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "update_user_name",
                scope,
                session_id=str(norm_session_id),
            )
            return False
        if not self._ensure_chat_history_ready():
            return False

        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"""
                        UPDATE chat_history
                        SET user_name = :user_name
                        WHERE session_id = :session_id
                        {org_filter}
                        """
                    ),
                    {
                        "session_id": str(norm_session_id),
                        "user_name": user_name,
                        **org_params,
                    },
                )
                session.commit()

            updated = (result.rowcount or 0) > 0
            if updated:
                logger.info(
                    "Updated user name for session_hash=%s",
                    _hash_memory_identifier(str(norm_session_id)),
                )
            return updated
        except Exception as exc:
            logger.error("Failed to update user name: %s", exc)
            return False

    def get_user_name(
        self,
        session_id: UUID,
        organization_id: Optional[str] = None,
    ) -> Optional[str]:
        """Read the latest non-empty user name stored for a session."""
        norm_session_id = _normalize_session_id(session_id)
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "get_user_name",
                scope,
                session_id=str(norm_session_id),
            )
            return None
        if not self._ensure_chat_history_ready():
            return None

        try:
            with self._session_factory() as session:
                return session.execute(
                    text(
                        f"""
                        SELECT user_name
                        FROM chat_history
                        WHERE session_id = :session_id
                        AND NULLIF(user_name, '') IS NOT NULL
                        {org_filter}
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "session_id": str(norm_session_id),
                        **org_params,
                    },
                ).scalar_one_or_none()
        except Exception as exc:
            logger.error("Failed to get user name: %s", exc)
            return None

    def format_history_for_prompt(self, messages: List[ChatMessage]) -> str:
        """Format chat history for prompt injection."""
        if not messages:
            return ""

        lines = []
        for msg in messages:
            role_label = "User" if msg.role == "user" else "AI"
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    def delete_user_history(
        self,
        user_id: str,
        organization_id: Optional[str] = None,
    ) -> int:
        """Delete all chat_history rows for a user in the current org scope."""
        scope, org_filter, org_params = self._org_scope(organization_id, write=True)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "delete_user_history",
                scope,
                user_id=user_id,
            )
            return 0
        if not self._ensure_chat_history_ready():
            return 0

        try:
            with self._session_factory() as session:
                result = session.execute(
                    text(
                        f"""
                        DELETE FROM chat_history
                        WHERE user_id = :user_id
                        {org_filter}
                        """
                    ),
                    {
                        "user_id": user_id,
                        **org_params,
                    },
                )
                session.commit()

            deleted_count = result.rowcount or 0
            logger.info(
                "Deleted %d messages for user_hash=%s",
                deleted_count,
                _hash_memory_identifier(user_id),
            )
            return deleted_count
        except Exception as exc:
            logger.error("Failed to delete user history: %s", exc)
            return 0

    def get_user_history(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        organization_id: Optional[str] = None,
    ) -> tuple[List[ChatMessage], int]:
        """Get paginated history for a user."""
        scope, org_filter, org_params = self._org_scope(organization_id)
        if org_filter is None:
            self._log_chat_history_scope_blocked(
                "get_user_history",
                scope,
                user_id=user_id,
            )
            return [], 0
        if not self._ensure_chat_history_ready():
            return [], 0

        try:
            count_params = {"user_id": user_id, **org_params}
            query_params = {
                "user_id": user_id,
                "limit": limit,
                "offset": offset,
                **org_params,
            }

            with self._session_factory() as session:
                total = (
                    session.execute(
                        text(
                            f"""
                            SELECT COUNT(*)
                            FROM chat_history
                            WHERE user_id = :user_id
                            {org_filter}
                            """
                        ),
                        count_params,
                    ).scalar()
                    or 0
                )

                rows = session.execute(
                    text(
                        f"""
                        SELECT id, user_id, session_id, role, content, created_at,
                               COALESCE(is_blocked, FALSE) AS is_blocked, block_reason
                        FROM chat_history
                        WHERE user_id = :user_id
                        {org_filter}
                        ORDER BY created_at DESC
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    query_params,
                ).fetchall()

            return self._rows_to_messages(rows, uuid4()), total
        except Exception as exc:
            logger.error("Failed to get user history: %s", exc)
            return [], 0


_chat_history_repo: Optional[ChatHistoryRepository] = None


def get_chat_history_repository() -> ChatHistoryRepository:
    """Get or create the repository singleton."""
    global _chat_history_repo
    if _chat_history_repo is None:
        _chat_history_repo = ChatHistoryRepository()
    return _chat_history_repo


def _hash_memory_identifier(value) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)
