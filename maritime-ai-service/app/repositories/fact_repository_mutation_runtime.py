"""Mutation/runtime mixin for fact repository operations."""

import json
import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import text

from app.models.semantic_memory import MemoryType

logger = logging.getLogger(__name__)
_FACT_REPOSITORY_MISSING_ORG_WARNING = "fact_repository_blocked_missing_org_context"
_FACT_ORG_FILTER = " AND organization_id = :org_id"


class FactRepositoryMutationRuntimeMixin:
    """
    Update/delete operations for fact-oriented semantic memory access.

    Requires the host class to provide:
    - self._ensure_initialized()
    - self._session_factory
    - self._format_embedding()
    - self.TABLE_NAME
    """

    def _resolve_fact_org_scope(self, *, write: bool = False):
        from app.engine.semantic_memory.write_audit import (
            resolve_memory_read_scope,
            resolve_memory_write_scope,
        )

        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        if not self._scope_allows_facts(scope):
            return scope, None
        return scope, _FACT_ORG_FILTER

    def _scope_allows_facts(self, scope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_fact_scope_blocked(
        self,
        operation: str,
        scope,
        *,
        user_id: Optional[str] = None,
    ) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_FACT_REPOSITORY_MISSING_ORG_WARNING)
        logger.warning(
            "[FACTS] %s blocked user_hash=%s org_hash=%s org_scope=%s warnings=%s",
            operation,
            _hash_memory_identifier(user_id),
            _hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    def _load_existing_metadata(
        self,
        *,
        session,
        fact_id: UUID,
        user_id: Optional[str],
        org_filter: str,
        org_id: str,
    ) -> dict:
        if user_id:
            query = text(
                f"""
                SELECT metadata
                FROM {self.TABLE_NAME}
                WHERE id = :fact_id AND user_id = :user_id
                {org_filter}
                LIMIT 1
                """
            )
            params = {"fact_id": str(fact_id), "user_id": user_id}
        else:
            query = text(
                f"""
                SELECT metadata
                FROM {self.TABLE_NAME}
                WHERE id = :fact_id
                {org_filter}
                LIMIT 1
                """
            )
            params = {"fact_id": str(fact_id)}
        params["org_id"] = org_id
        row = session.execute(query, params).fetchone()
        return dict((row.metadata or {}) if row else {})

    def update_fact(
        self,
        fact_id: UUID,
        content: str,
        embedding: List[float],
        metadata: dict,
        user_id: Optional[str] = None,
    ) -> bool:
        """Update content, embedding, and metadata for an existing fact."""
        if embedding is None or len(embedding) == 0:
            raise ValueError(
                "embedding is required for update_fact(). "
                "Use update_metadata_only() for metadata-only updates."
            )

        self._ensure_initialized()
        scope, org_filter = self._resolve_fact_org_scope(write=True)
        if org_filter is None:
            self._log_fact_scope_blocked("update_fact", scope, user_id=user_id)
            return False

        try:
            with self._session_factory() as session:
                from app.services.embedding_space_guard import stamp_embedding_metadata

                query, params = self._build_update_fact_statement(
                    fact_id=fact_id,
                    user_id=user_id,
                    content=content,
                    embedding=embedding,
                    metadata=stamp_embedding_metadata(metadata),
                    org_filter=org_filter,
                )
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                if row:
                    logger.debug("Updated fact %s", fact_id)
                    return True
                return False
        except ValueError:
            raise
        except Exception as exc:
            logger.error("Failed to update fact: %s", exc)
            return False

    def _build_update_fact_statement(
        self,
        *,
        fact_id: UUID,
        user_id: Optional[str],
        content: str,
        embedding: List[float],
        metadata: dict,
        org_filter: str,
    ):
        embedding_str = self._format_embedding(embedding)
        metadata_json = json.dumps(metadata)

        if user_id:
            query = text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET content = :content,
                    embedding = CAST(:embedding AS vector),
                    metadata = CAST(:metadata AS jsonb),
                    importance = :importance,
                    updated_at = NOW()
                WHERE id = :fact_id AND user_id = :user_id
                {org_filter}
                RETURNING id
                """
            )
            params = {
                "fact_id": str(fact_id),
                "user_id": user_id,
                "content": content,
                "embedding": embedding_str,
                "metadata": metadata_json,
                "importance": metadata.get("confidence", 0.5),
            }
        else:
            query = text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET content = :content,
                    embedding = CAST(:embedding AS vector),
                    metadata = CAST(:metadata AS jsonb),
                    importance = :importance,
                    updated_at = NOW()
                WHERE id = :fact_id
                {org_filter}
                RETURNING id
                """
            )
            params = {
                "fact_id": str(fact_id),
                "content": content,
                "embedding": embedding_str,
                "metadata": metadata_json,
                "importance": metadata.get("confidence", 0.5),
            }
        return query, params

    def update_fact_preserve_embedding(
        self,
        fact_id: UUID,
        content: str,
        metadata: dict,
        user_id: Optional[str] = None,
    ) -> bool:
        """Update fact content/metadata while preserving the existing embedding."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_fact_org_scope(write=True)
        if org_filter is None:
            self._log_fact_scope_blocked(
                "update_fact_preserve_embedding",
                scope,
                user_id=user_id,
            )
            return False

        try:
            with self._session_factory() as session:
                from app.services.embedding_space_guard import preserve_embedding_space_metadata

                existing_metadata = self._load_existing_metadata(
                    session=session,
                    fact_id=fact_id,
                    user_id=user_id,
                    org_filter=org_filter,
                    org_id=scope.org_id,
                )
                metadata_json = json.dumps(
                    preserve_embedding_space_metadata(metadata, existing_metadata)
                )
                if user_id:
                    query = text(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET content = :content,
                            metadata = CAST(:metadata AS jsonb),
                            importance = :importance,
                            updated_at = NOW()
                        WHERE id = :fact_id AND user_id = :user_id
                        {org_filter}
                        RETURNING id
                        """
                    )
                    params = {
                        "fact_id": str(fact_id),
                        "user_id": user_id,
                        "content": content,
                        "metadata": metadata_json,
                        "importance": metadata.get("confidence", 0.5),
                    }
                else:
                    query = text(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET content = :content,
                            metadata = CAST(:metadata AS jsonb),
                            importance = :importance,
                            updated_at = NOW()
                        WHERE id = :fact_id
                        {org_filter}
                        RETURNING id
                        """
                    )
                    params = {
                        "fact_id": str(fact_id),
                        "content": content,
                        "metadata": metadata_json,
                        "importance": metadata.get("confidence", 0.5),
                    }

                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                if row:
                    logger.debug("Updated fact %s while preserving embedding", fact_id)
                    return True
                return False
        except Exception as exc:
            logger.error("Failed to update fact while preserving embedding: %s", exc)
            return False

    def update_metadata_only(
        self,
        fact_id: UUID,
        metadata: dict,
        user_id: Optional[str] = None,
    ) -> bool:
        """Update only metadata while preserving content and embedding."""
        self._ensure_initialized()

        if fact_id is None or str(fact_id) in ("None", "", "null"):
            logger.warning("[BUGFIX] Invalid fact_id: %s, skipping metadata update", fact_id)
            return False

        scope, org_filter = self._resolve_fact_org_scope(write=True)
        if org_filter is None:
            self._log_fact_scope_blocked("update_metadata_only", scope, user_id=user_id)
            return False

        try:
            with self._session_factory() as session:
                from app.services.embedding_space_guard import preserve_embedding_space_metadata

                existing_metadata = self._load_existing_metadata(
                    session=session,
                    fact_id=fact_id,
                    user_id=user_id,
                    org_filter=org_filter,
                    org_id=scope.org_id,
                )
                query, params = self._build_update_metadata_statement(
                    fact_id=fact_id,
                    user_id=user_id,
                    metadata=preserve_embedding_space_metadata(metadata, existing_metadata),
                    org_filter=org_filter,
                )
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                if row:
                    logger.debug("Updated metadata for fact %s", fact_id)
                    return True
                return False
        except Exception as exc:
            logger.error("Failed to update metadata: %s", exc)
            return False

    def _build_update_metadata_statement(
        self,
        *,
        fact_id: UUID,
        user_id: Optional[str],
        metadata: dict,
        org_filter: str,
    ):
        metadata_json = json.dumps(metadata)

        if user_id:
            query = text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = CAST(:metadata AS jsonb),
                    updated_at = NOW()
                WHERE id = :fact_id AND user_id = :user_id
                {org_filter}
                RETURNING id
                """
            )
            params = {
                "fact_id": str(fact_id),
                "user_id": user_id,
                "metadata": metadata_json,
            }
        else:
            query = text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = CAST(:metadata AS jsonb),
                    updated_at = NOW()
                WHERE id = :fact_id
                {org_filter}
                RETURNING id
                """
            )
            params = {
                "fact_id": str(fact_id),
                "metadata": metadata_json,
            }
        return query, params

    def delete_oldest_facts(
        self,
        user_id: str,
        count: int,
    ) -> int:
        """Delete the oldest USER_FACT entries for a user."""
        self._ensure_initialized()

        if count <= 0:
            return 0

        scope, org_filter = self._resolve_fact_org_scope(write=True)
        if org_filter is None:
            self._log_fact_scope_blocked("delete_oldest_facts", scope, user_id=user_id)
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
                    "memory_type": MemoryType.USER_FACT.value,
                    "count": count,
                }
                params["org_id"] = scope.org_id

                deleted_count = len(session.execute(query, params).fetchall())
                session.commit()
                if deleted_count > 0:
                    logger.info(
                        "Deleted %d oldest facts for user %s (FIFO eviction)",
                        deleted_count,
                        user_id,
                    )
                return deleted_count
        except Exception as exc:
            logger.error("Failed to delete oldest facts: %s", exc)
            return 0


def _hash_memory_identifier(value) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)
