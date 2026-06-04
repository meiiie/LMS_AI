"""
Core CRUD/runtime mixin for SemanticMemoryRepository.

Extracted from semantic_memory_repository.py so the facade can stay focused on
engine/session bootstrap while concrete memory operations live in a dedicated
module beside the existing fact/insight/vector mixins.
"""

import json
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text

from app.engine.semantic_memory.privacy import (
    hash_memory_identifier,
    memory_log_reference,
)
from app.models.semantic_memory import (
    MemoryType,
    SemanticMemory,
    SemanticMemoryCreate,
)
from app.services.embedding_shadow_vector_service import (
    build_shadow_embedding_sync,
    build_shadow_metadata,
    filter_shadow_spaces,
    format_pg_array_literal,
)
from app.services.embedding_space_guard import (
    get_active_embedding_space_contract,
    stamp_embedding_metadata,
)
from app.services.embedding_space_registry_service import get_embedding_write_spaces

logger = logging.getLogger(__name__)
_SEMANTIC_MEMORY_REPOSITORY_MISSING_ORG_WARNING = (
    "semantic_memory_repository_blocked_missing_org_context"
)
_SEMANTIC_MEMORY_ORG_FILTER = " AND organization_id = :org_id"


class SemanticMemoryRepositoryRuntimeMixin:
    """
    Core CRUD/runtime operations for SemanticMemoryRepository.

    Requires the host class to provide:
    - self._ensure_initialized()
    - self._session_factory
    - self._format_embedding()
    - self.TABLE_NAME
    """

    def _resolve_semantic_memory_org_scope(self, *, write: bool = False):
        from app.engine.semantic_memory.write_audit import (
            resolve_memory_read_scope,
            resolve_memory_write_scope,
        )

        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        if not self._scope_allows_semantic_memory(scope):
            return scope, None
        return scope, _SEMANTIC_MEMORY_ORG_FILTER

    def _scope_allows_semantic_memory(self, scope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_semantic_memory_scope_blocked(
        self,
        operation: str,
        scope,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_SEMANTIC_MEMORY_REPOSITORY_MISSING_ORG_WARNING)
        logger.warning(
            "[MEMORY_REPO] %s blocked user_hash=%s session_hash=%s org_hash=%s "
            "org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(user_id),
            hash_memory_identifier(session_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    @staticmethod
    def _has_embedding(embedding: Optional[List[float]]) -> bool:
        return bool(embedding)

    def _build_save_memory_statement(
        self,
        *,
        memory: SemanticMemoryCreate,
        inline_embedding: Optional[List[float]],
        metadata_json: str,
        effective_org_id: Optional[str],
    ):
        params = {
            "user_id": memory.user_id,
            "content": memory.content,
            "memory_type": memory.memory_type.value,
            "importance": memory.importance,
            "metadata": metadata_json,
            "session_id": memory.session_id,
            "org_id": effective_org_id,
        }

        embedding_sql = "NULL"
        if self._has_embedding(inline_embedding):
            params["embedding"] = self._format_embedding(inline_embedding)
            embedding_sql = "CAST(:embedding AS vector)"

        query = text(
            f"""
            INSERT INTO {self.TABLE_NAME}
            (user_id, content, embedding, memory_type, importance, metadata, session_id, organization_id)
            VALUES
            (:user_id, :content, {embedding_sql}, :memory_type, :importance, CAST(:metadata AS jsonb), :session_id, :org_id)
            RETURNING id, user_id, content, memory_type, importance, metadata, session_id, created_at, updated_at
            """
        )
        return query, params

    def _resolve_inline_embedding(
        self,
        *,
        memory: SemanticMemoryCreate,
    ) -> tuple[Optional[List[float]], str, tuple]:
        write_spaces = get_embedding_write_spaces("semantic_memories")
        source_contract = get_active_embedding_space_contract()
        inline_space = next(
            (space for space in write_spaces if space.storage_kind == "inline"),
            None,
        )

        inline_embedding: Optional[List[float]] = None
        metadata_payload = dict(memory.metadata or {})
        if not self._has_embedding(memory.embedding):
            return None, json.dumps(metadata_payload, ensure_ascii=False), write_spaces
        if inline_space is not None:
            try:
                inline_embedding = build_shadow_embedding_sync(
                    text_to_embed=memory.content,
                    space=inline_space,
                    source_embedding=memory.embedding,
                    source_contract=source_contract,
                )
                metadata_payload = stamp_embedding_metadata(
                    metadata_payload,
                    model_name=inline_space.model,
                    dimensions=inline_space.dimensions,
                )
            except Exception as exc:
                logger.warning(
                    "Inline embedding write degraded to base-row-only for semantic memory: %s",
                    exc,
                )

        return inline_embedding, json.dumps(metadata_payload, ensure_ascii=False), write_spaces

    def _store_shadow_vectors(
        self,
        *,
        session,
        memory_id: UUID,
        memory: SemanticMemoryCreate,
        write_spaces: tuple,
    ) -> None:
        source_contract = get_active_embedding_space_contract()
        if not self._has_embedding(memory.embedding):
            return
        for shadow_space in filter_shadow_spaces(write_spaces):
            try:
                shadow_embedding = build_shadow_embedding_sync(
                    text_to_embed=memory.content,
                    space=shadow_space,
                    source_embedding=memory.embedding,
                    source_contract=source_contract,
                )
            except Exception as exc:
                logger.warning(
                    "Shadow embedding write skipped for semantic memory %s [%s]: %s",
                    memory_id,
                    shadow_space.space_fingerprint,
                    exc,
                )
                continue

            session.execute(
                text(
                    """
                    INSERT INTO semantic_memory_vectors (
                        memory_id,
                        space_fingerprint,
                        provider,
                        model,
                        dimensions,
                        embedding,
                        metadata,
                        updated_at
                    )
                    VALUES (
                        CAST(:memory_id AS uuid),
                        :space_fingerprint,
                        :provider,
                        :model,
                        :dimensions,
                        CAST(:embedding AS double precision[]),
                        CAST(:metadata AS jsonb),
                        NOW()
                    )
                    ON CONFLICT (memory_id, space_fingerprint)
                    DO UPDATE SET
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        dimensions = EXCLUDED.dimensions,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """
                ),
                {
                    "memory_id": str(memory_id),
                    "space_fingerprint": shadow_space.space_fingerprint,
                    "provider": shadow_space.provider,
                    "model": shadow_space.model,
                    "dimensions": shadow_space.dimensions,
                    "embedding": format_pg_array_literal(shadow_embedding),
                    "metadata": build_shadow_metadata(
                        memory.metadata,
                        contract=shadow_space,
                    ),
                },
            )

    def save_memory(
        self,
        memory: SemanticMemoryCreate,
    ) -> Optional[SemanticMemory]:
        """Save a new semantic memory to the database."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "save_memory",
                scope,
                user_id=memory.user_id,
                session_id=memory.session_id,
            )
            return None

        try:
            with self._session_factory() as session:
                inline_embedding, metadata_json, write_spaces = self._resolve_inline_embedding(
                    memory=memory,
                )

                query, params = self._build_save_memory_statement(
                    memory=memory,
                    inline_embedding=inline_embedding,
                    metadata_json=metadata_json,
                    effective_org_id=scope.org_id,
                )

                result = session.execute(query, params)

                row = result.fetchone()
                if row:
                    self._store_shadow_vectors(
                        session=session,
                        memory_id=row.id,
                        memory=memory,
                        write_spaces=write_spaces,
                    )
                session.commit()

                if row:
                    logger.debug(
                        "Saved memory %s for user_hash=%s",
                        row.id,
                        hash_memory_identifier(memory.user_id),
                    )
                    return SemanticMemory(
                        id=row.id,
                        user_id=row.user_id,
                        content=row.content,
                        embedding=memory.embedding,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        metadata=row.metadata or {},
                        session_id=row.session_id,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                return None

        except Exception as exc:
            logger.error("Failed to save memory: %s", exc)
            return None

    def get_by_id(
        self,
        memory_id: UUID,
        user_id: str,
    ) -> Optional[SemanticMemory]:
        """Get a specific memory by ID."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope()
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "get_by_id",
                scope,
                user_id=user_id,
            )
            return None

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    SELECT
                        id, user_id, content, memory_type, importance,
                        metadata, session_id, created_at, updated_at
                    FROM {self.TABLE_NAME}
                    WHERE id = :memory_id AND user_id = :user_id
                    {org_filter}
                    """
                )

                params = {
                    "memory_id": str(memory_id),
                    "user_id": user_id,
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                if row:
                    return SemanticMemory(
                        id=row.id,
                        user_id=row.user_id,
                        content=row.content,
                        embedding=[],
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        metadata=row.metadata or {},
                        session_id=row.session_id,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                return None

        except Exception as exc:
            logger.error("Failed to get memory by ID: %s", exc)
            return None

    def delete_by_session(
        self,
        user_id: str,
        session_id: str,
    ) -> int:
        """Delete message memories for a specific session."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_by_session",
                scope,
                user_id=user_id,
                session_id=session_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND session_id = :session_id
                      AND memory_type = :memory_type
                      {org_filter}
                    RETURNING id
                    """
                )

                params = {
                    "user_id": user_id,
                    "session_id": session_id,
                    "memory_type": MemoryType.MESSAGE.value,
                }
                params["org_id"] = scope.org_id

                deleted = len(session.execute(query, params).fetchall())
                session.commit()
                logger.info("Deleted %d messages for session %s", deleted, session_id)
                return deleted

        except Exception as exc:
            logger.error("Failed to delete session memories: %s", exc)
            return 0

    def count_user_memories(
        self,
        user_id: str,
        memory_type: Optional[MemoryType] = None,
    ) -> int:
        """Count memories for a user."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope()
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "count_user_memories",
                scope,
                user_id=user_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                type_filter = ""
                params = {"user_id": user_id}

                if memory_type:
                    type_filter = "AND memory_type = :memory_type"
                    params["memory_type"] = memory_type.value

                params["org_id"] = scope.org_id

                query = text(
                    f"""
                    SELECT COUNT(*) as count
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id {type_filter}
                    {org_filter}
                    """
                )

                row = session.execute(query, params).fetchone()
                return row.count if row else 0

        except Exception as exc:
            logger.error("Failed to count memories: %s", exc)
            return 0

    def is_available(self) -> bool:
        """Check whether the shared repository connection is healthy."""
        try:
            self._ensure_initialized()
            with self._session_factory() as session:
                session.execute(text("SELECT 1"))
                return True
        except Exception as exc:
            logger.warning("SemanticMemoryRepository not available: %s", exc)
            try:
                from app.core.database import mark_shared_database_unavailable

                mark_shared_database_unavailable(exc)
            except Exception:
                pass
            return False

    def update_last_accessed(self, memory_id: UUID, user_id: Optional[str] = None) -> bool:
        """Update last_accessed timestamp and increment metadata.access_count."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "update_last_accessed",
                scope,
                user_id=user_id,
            )
            return False

        try:
            with self._session_factory() as session:
                if user_id:
                    query = text(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET last_accessed = NOW(),
                            metadata = jsonb_set(
                                COALESCE(metadata, '{{}}'::jsonb),
                                '{{access_count}}',
                                (COALESCE((metadata->>'access_count')::int, 0) + 1)::text::jsonb
                            )
                        WHERE id = :memory_id AND user_id = :user_id
                        {org_filter}
                        RETURNING id
                        """
                    )
                    params = {"memory_id": str(memory_id), "user_id": user_id}
                else:
                    query = text(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET last_accessed = NOW(),
                            metadata = jsonb_set(
                                COALESCE(metadata, '{{}}'::jsonb),
                                '{{access_count}}',
                                (COALESCE((metadata->>'access_count')::int, 0) + 1)::text::jsonb
                            )
                        WHERE id = :memory_id
                        {org_filter}
                        RETURNING id
                        """
                    )
                    params = {"memory_id": str(memory_id)}

                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                return row is not None

        except Exception as exc:
            logger.error("Failed to update last_accessed: %s", exc)
            return False

    def get_memories_by_type(
        self,
        user_id: str,
        memory_type: MemoryType,
        limit: int = 1000,
        session_id: Optional[str] = None,
    ) -> List["SemanticMemorySearchResult"]:
        """Get memories filtered by type without cosine similarity search."""
        from app.models.semantic_memory import SemanticMemorySearchResult

        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope()
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "get_memories_by_type",
                scope,
                user_id=user_id,
                session_id=session_id,
            )
            return []

        try:
            with self._session_factory() as session:
                session_filter = ""
                params = {
                    "user_id": user_id,
                    "memory_type": memory_type.value,
                    "limit": limit,
                }

                if session_id:
                    session_filter = "AND session_id = :session_id"
                    params["session_id"] = session_id

                params["org_id"] = scope.org_id

                query = text(
                    f"""
                    SELECT
                        id,
                        content,
                        memory_type,
                        importance,
                        metadata,
                        created_at,
                        1.0 AS similarity
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND memory_type = :memory_type
                      {session_filter}
                      {org_filter}
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                )

                rows = session.execute(query, params).fetchall()
                return [
                    SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at,
                    )
                    for row in rows
                ]

        except Exception as exc:
            logger.error("Failed to get memories by type: %s", exc)
            return []

    def delete_memories_by_keyword(
        self,
        user_id: str,
        keyword: str,
    ) -> int:
        """Delete memories matching a keyword in content for a user."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_memories_by_keyword",
                scope,
                user_id=user_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND LOWER(content) LIKE LOWER(:keyword_pattern)
                      {org_filter}
                    RETURNING id
                    """
                )

                params = {
                    "user_id": user_id,
                    "keyword_pattern": f"%{keyword}%",
                }
                params["org_id"] = scope.org_id

                deleted_count = len(session.execute(query, params).fetchall())
                session.commit()
                if deleted_count > 0:
                    logger.info(
                        "Deleted %d memories matching keyword_ref=%s for user_hash=%s",
                        deleted_count,
                        memory_log_reference(keyword),
                        hash_memory_identifier(user_id),
                    )
                return deleted_count

        except Exception as exc:
            logger.error("Failed to delete memories by keyword: %s", exc)
            return 0

    def delete_all_user_memories(self, user_id: str) -> int:
        """Delete all memories for a user."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_all_user_memories",
                scope,
                user_id=user_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                    {org_filter}
                    RETURNING id
                    """
                )

                params = {"user_id": user_id}
                params["org_id"] = scope.org_id

                deleted_count = len(session.execute(query, params).fetchall())
                session.commit()
                logger.info(
                    "Deleted ALL %d memories for user_hash=%s",
                    deleted_count,
                    hash_memory_identifier(user_id),
                )
                return deleted_count

        except Exception as exc:
            logger.error(
                "Failed to delete all memories for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                exc,
            )
            return 0

    def delete_oldest_insights(
        self,
        user_id: str,
        count: int,
    ) -> int:
        """Delete the N oldest insight entries for a user."""
        self._ensure_initialized()
        if count <= 0:
            return 0

        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_oldest_insights",
                scope,
                user_id=user_id,
            )
            return 0

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE id IN (
                        SELECT id FROM {self.TABLE_NAME}
                        WHERE user_id = :user_id
                          AND memory_type = :memory_type
                          {org_filter}
                        ORDER BY created_at ASC
                        LIMIT :count
                    )
                    RETURNING id
                    """
                )

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.INSIGHT.value,
                    "count": count,
                }
                params["org_id"] = scope.org_id

                deleted_count = len(session.execute(query, params).fetchall())
                session.commit()
                if deleted_count > 0:
                    logger.info(
                        "Deleted %d oldest insights for user_hash=%s (FIFO eviction)",
                        deleted_count,
                        hash_memory_identifier(user_id),
                    )
                return deleted_count

        except Exception as exc:
            logger.error("Failed to delete oldest insights: %s", exc)
            return 0

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """Delete a specific memory by ID."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_memory",
                scope,
                user_id=user_id,
            )
            return False

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE id = :memory_id AND user_id = :user_id
                    {org_filter}
                    RETURNING id
                    """
                )

                params = {
                    "memory_id": str(memory_id),
                    "user_id": user_id,
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                return row is not None

        except Exception as exc:
            logger.error("Failed to delete memory: %s", exc)
            return False

    def upsert_running_summary(self, session_id: str, summary: str) -> bool:
        """Upsert a running summary for a session."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "upsert_running_summary",
                scope,
                session_id=session_id,
            )
            return False

        try:
            with self._session_factory() as session:
                update_query = text(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET content = :content, updated_at = NOW()
                    WHERE session_id = :session_id
                      AND memory_type = :memory_type
                      {org_filter}
                    RETURNING id
                    """
                )

                update_params = {
                    "content": summary,
                    "session_id": session_id,
                    "memory_type": MemoryType.RUNNING_SUMMARY.value,
                }
                update_params["org_id"] = scope.org_id

                row = session.execute(update_query, update_params).fetchone()
                if row:
                    session.commit()
                    return True

                metadata = json.dumps(
                    {"content_type": "running_summary", "source": "repository"}
                )
                insert_query = text(
                    f"""
                    INSERT INTO {self.TABLE_NAME}
                    (user_id, content, embedding, memory_type, importance, metadata, session_id, organization_id)
                    VALUES
                    ('__system__', :content, NULL, :memory_type, :importance, CAST(:metadata AS jsonb), :session_id, :org_id)
                    RETURNING id
                    """
                )

                result = session.execute(
                    insert_query,
                    {
                        "content": summary,
                        "memory_type": MemoryType.RUNNING_SUMMARY.value,
                        "importance": 0.9,
                        "metadata": metadata,
                        "session_id": session_id,
                        "org_id": scope.org_id,
                    },
                )
                session.commit()
                return result.fetchone() is not None

        except Exception as exc:
            logger.error("Failed to upsert running summary: %s", exc)
            return False

    def get_running_summary(self, session_id: str) -> Optional[str]:
        """Load the most recent running summary for a session."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope()
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "get_running_summary",
                scope,
                session_id=session_id,
            )
            return None

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    SELECT content
                    FROM {self.TABLE_NAME}
                    WHERE session_id = :session_id
                      AND memory_type = :memory_type
                      {org_filter}
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 1
                    """
                )

                params = {
                    "session_id": session_id,
                    "memory_type": MemoryType.RUNNING_SUMMARY.value,
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                return row.content if row else None

        except Exception as exc:
            logger.error("Failed to get running summary: %s", exc)
            return None

    def delete_running_summary(self, session_id: str) -> bool:
        """Delete the running summary record for a session."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_semantic_memory_org_scope(write=True)
        if org_filter is None:
            self._log_semantic_memory_scope_blocked(
                "delete_running_summary",
                scope,
                session_id=session_id,
            )
            return False

        try:
            with self._session_factory() as session:
                query = text(
                    f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE session_id = :session_id
                      AND memory_type = :memory_type
                      {org_filter}
                    RETURNING id
                    """
                )

                params = {
                    "session_id": session_id,
                    "memory_type": MemoryType.RUNNING_SUMMARY.value,
                }
                params["org_id"] = scope.org_id

                result = session.execute(query, params)
                session.commit()
                return result.fetchone() is not None

        except Exception as exc:
            logger.error("Failed to delete running summary: %s", exc)
            return False
