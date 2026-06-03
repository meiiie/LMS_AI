"""Semantic triple helpers for the fact repository."""

from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text

from app.models.semantic_memory import (
    MemoryType,
    Predicate,
    SemanticMemory,
    SemanticMemoryCreate,
    SemanticMemorySearchResult,
    SemanticTriple,
)

logger = logging.getLogger(__name__)
_TRIPLE_REPOSITORY_MISSING_ORG_WARNING = "triple_repository_blocked_missing_org_context"
_TRIPLE_ORG_FILTER = " AND organization_id = :org_id"


class FactRepositoryTripleMixin:
    """Semantic triple operations for SemanticMemoryRepository."""

    def _resolve_triple_org_scope(self, *, write: bool = False):
        from app.engine.semantic_memory.write_audit import (
            resolve_memory_read_scope,
            resolve_memory_write_scope,
        )

        scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
        if not self._scope_allows_triples(scope):
            return scope, None
        return scope, _TRIPLE_ORG_FILTER

    def _scope_allows_triples(self, scope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_triple_scope_blocked(self, operation: str, scope, *, user_id: str) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_TRIPLE_REPOSITORY_MISSING_ORG_WARNING)
        logger.warning(
            "[TRIPLES] %s blocked user_hash=%s org_hash=%s org_scope=%s warnings=%s",
            operation,
            _hash_memory_identifier(user_id),
            _hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    def save_triple(
        self,
        triple: SemanticTriple,
        generate_embedding: bool = True,
    ) -> Optional[SemanticMemory]:
        self._ensure_initialized()
        scope, org_filter = self._resolve_triple_org_scope(write=True)
        if org_filter is None:
            self._log_triple_scope_blocked(
                "save_triple",
                scope,
                user_id=triple.subject,
            )
            return None

        try:
            embedding = triple.embedding
            if not embedding and generate_embedding:
                try:
                    from app.engine.semantic_memory.embeddings import get_embedding_generator

                    generator = get_embedding_generator()
                    if generator.is_available():
                        embedding = generator.generate(triple.object)
                except Exception as exc:
                    logger.warning("Failed to generate embedding for triple: %s", exc)
                    embedding = []

            memory = SemanticMemoryCreate(
                user_id=triple.subject,
                content=triple.to_content(),
                embedding=embedding,
                memory_type=MemoryType.USER_FACT,
                importance=triple.confidence,
                metadata=triple.to_metadata(),
                session_id=None,
            )
            return self.save_memory(memory)
        except Exception as exc:
            logger.error("Failed to save triple: %s", exc)
            return None

    def find_by_predicate(
        self,
        user_id: str,
        predicate: Predicate,
    ) -> Optional[SemanticMemorySearchResult]:
        self._ensure_initialized()
        scope, org_filter = self._resolve_triple_org_scope()
        if org_filter is None:
            self._log_triple_scope_blocked(
                "find_by_predicate",
                scope,
                user_id=user_id,
            )
            return None

        try:
            with self._session_factory() as session:
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
                      AND (
                          metadata->>'predicate' = :predicate
                          OR metadata->>'fact_type' = :fact_type
                      )
                      {org_filter}
                    ORDER BY created_at DESC
                    LIMIT 1
                """
                )

                fact_type_map = {
                    Predicate.HAS_NAME: "name",
                    Predicate.HAS_ROLE: "role",
                    Predicate.HAS_LEVEL: "level",
                    Predicate.HAS_GOAL: "goal",
                    Predicate.PREFERS: "preference",
                    Predicate.WEAK_AT: "weakness",
                }

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "predicate": predicate.value,
                    "fact_type": fact_type_map.get(predicate, predicate.value),
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                if not row:
                    return None
                return SemanticMemorySearchResult(
                    id=row.id,
                    content=row.content,
                    memory_type=MemoryType(row.memory_type),
                    importance=row.importance,
                    similarity=1.0,
                    metadata=row.metadata or {},
                    created_at=row.created_at,
                )
        except Exception as exc:
            logger.error("Failed to find by predicate: %s", exc)
            return None

    def update_memory_content(
        self,
        memory_id: UUID,
        user_id: str,
        new_content: str,
        new_metadata: dict,
    ) -> Optional[SemanticMemory]:
        self._ensure_initialized()
        scope, org_filter = self._resolve_triple_org_scope(write=True)
        if org_filter is None:
            self._log_triple_scope_blocked(
                "update_memory_content",
                scope,
                user_id=user_id,
            )
            return None

        try:
            embedding = []
            try:
                from app.engine.semantic_memory.embeddings import get_embedding_generator

                generator = get_embedding_generator()
                if generator.is_available():
                    embedding = generator.generate(new_content)
            except Exception as exc:
                logger.warning("Failed to generate embedding for update: %s", exc)

            if not embedding:
                success = self.update_fact_preserve_embedding(
                    fact_id=memory_id,
                    content=new_content,
                    metadata=new_metadata,
                    user_id=user_id,
                )
                if success:
                    return self.get_by_id(memory_id, user_id)
                return None

            embedding_str = self._format_embedding(embedding)
            from app.services.embedding_space_guard import stamp_embedding_metadata

            metadata_json = json.dumps(stamp_embedding_metadata(new_metadata))

            with self._session_factory() as session:
                query = text(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET content = :content,
                        embedding = CAST(:embedding AS vector),
                        metadata = CAST(:metadata AS jsonb),
                        importance = :importance,
                        updated_at = NOW()
                    WHERE id = :memory_id AND user_id = :user_id
                    {org_filter}
                    RETURNING id, user_id, content, memory_type, importance,
                              metadata, session_id, created_at, updated_at
                """
                )

                params = {
                    "memory_id": str(memory_id),
                    "user_id": user_id,
                    "content": new_content,
                    "embedding": embedding_str,
                    "metadata": metadata_json,
                    "importance": new_metadata.get("confidence", 0.5),
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                session.commit()
                if not row:
                    return None
                logger.debug("Updated memory content %s", memory_id)
                return SemanticMemory(
                    id=row.id,
                    user_id=row.user_id,
                    content=row.content,
                    embedding=embedding,
                    memory_type=MemoryType(row.memory_type),
                    importance=row.importance,
                    metadata=row.metadata or {},
                    session_id=row.session_id,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
        except Exception as exc:
            logger.error("Failed to update memory content %s: %s", memory_id, exc)
            return None

    def upsert_triple(
        self,
        triple: SemanticTriple,
    ) -> Optional[SemanticMemory]:
        existing = self.find_by_predicate(triple.subject, triple.predicate)
        if existing:
            return self.update_memory_content(
                memory_id=existing.id,
                user_id=triple.subject,
                new_content=triple.to_content(),
                new_metadata=triple.to_metadata(),
            )
        return self.save_triple(triple, generate_embedding=True)


def _hash_memory_identifier(value) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)
