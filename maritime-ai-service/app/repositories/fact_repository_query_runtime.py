"""Query/runtime mixin for fact repository operations."""

import logging
from typing import List, Optional

from sqlalchemy import text

from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult

logger = logging.getLogger(__name__)
_FACT_REPOSITORY_MISSING_ORG_WARNING = "fact_repository_blocked_missing_org_context"
_FACT_ORG_FILTER = " AND organization_id = :org_id"


class FactRepositoryQueryRuntimeMixin:
    """
    Read/query operations for fact-oriented semantic memory access.

    Requires the host class to provide:
    - self._ensure_initialized()
    - self._session_factory
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

    def _log_fact_scope_blocked(self, operation: str, scope, *, user_id: Optional[str] = None) -> None:
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

    def _row_to_search_result(self, row, *, similarity: Optional[float] = None):
        return SemanticMemorySearchResult(
            id=row.id,
            content=row.content,
            memory_type=MemoryType(row.memory_type),
            importance=row.importance,
            similarity=1.0 if similarity is None else similarity,
            metadata=row.metadata or {},
            created_at=row.created_at,
            updated_at=getattr(row, "updated_at", None),
        )

    def get_user_facts(
        self,
        user_id: str,
        limit: int = 20,
        deduplicate: bool = True,
        apply_decay: bool = True,
    ) -> List[SemanticMemorySearchResult]:
        """Get user facts across all sessions for personalization."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_fact_org_scope()
        if org_filter is None:
            self._log_fact_scope_blocked("get_user_facts", scope, user_id=user_id)
            return []

        try:
            with self._session_factory() as session:
                if deduplicate:
                    query = text(
                        f"""
                        SELECT DISTINCT ON (metadata->>'fact_type')
                            id,
                            content,
                            memory_type,
                            importance,
                            metadata,
                            created_at,
                            updated_at,
                            last_accessed,
                            1.0 AS similarity
                        FROM {self.TABLE_NAME}
                        WHERE user_id = :user_id
                          AND memory_type = :memory_type
                          {org_filter}
                        ORDER BY metadata->>'fact_type', COALESCE(updated_at, created_at) DESC, created_at DESC
                        """
                    )
                else:
                    query = text(
                        f"""
                        SELECT
                            id,
                            content,
                            memory_type,
                            importance,
                            metadata,
                            created_at,
                            updated_at,
                            last_accessed,
                            1.0 AS similarity
                        FROM {self.TABLE_NAME}
                        WHERE user_id = :user_id
                          AND memory_type = :memory_type
                          {org_filter}
                        ORDER BY importance DESC, COALESCE(updated_at, created_at) DESC, created_at DESC
                        LIMIT :limit
                        """
                    )

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                }
                params["org_id"] = scope.org_id
                if not deduplicate:
                    params["limit"] = limit

                rows = session.execute(query, params).fetchall()
                facts = [self._row_to_search_result(row) for row in rows]

                if apply_decay and facts:
                    facts = self._apply_importance_decay(facts)

                facts = facts[:limit]
                logger.debug(
                    "Found %d user facts for user %s (deduplicate=%s, decay=%s)",
                    len(facts),
                    user_id,
                    deduplicate,
                    apply_decay,
                )
                return facts
        except Exception as exc:
            logger.error("Failed to get user facts: %s", exc)
            return []

    def _apply_importance_decay(
        self,
        facts: List[SemanticMemorySearchResult],
    ) -> List[SemanticMemorySearchResult]:
        """Apply FadeMem/Ebbinghaus-style decay and resort facts."""
        try:
            from app.engine.semantic_memory.importance_decay import (
                calculate_effective_importance_from_timestamps,
            )
        except ImportError:
            return facts

        for fact in facts:
            fact_type = (fact.metadata or {}).get("fact_type", "unknown")
            access_count = (fact.metadata or {}).get("access_count", 0)
            last_accessed = (fact.metadata or {}).get("last_accessed")

            effective = calculate_effective_importance_from_timestamps(
                base_importance=fact.importance,
                fact_type=fact_type,
                last_accessed=last_accessed,
                created_at=fact.created_at,
                access_count=access_count,
            )
            fact.similarity = effective

        facts.sort(key=lambda fact: fact.similarity, reverse=True)
        return facts

    def search_relevant_facts(
        self,
        user_id: str,
        query_embedding: List[float],
        limit: int = 5,
        min_similarity: float = 0.3,
    ) -> List[SemanticMemorySearchResult]:
        """Search user facts by semantic similarity to a query embedding."""
        self._ensure_initialized()
        if not query_embedding:
            logger.warning(
                "Skipping fact semantic search for user %s because query embedding is empty",
                user_id,
            )
            return []

        try:
            from app.core.config import settings

            alpha = settings.fact_retrieval_alpha
            beta = settings.fact_retrieval_beta
            gamma = settings.fact_retrieval_gamma
        except Exception:
            alpha, beta, gamma = 0.3, 0.5, 0.2

        scope, org_filter = self._resolve_fact_org_scope()
        if org_filter is None:
            self._log_fact_scope_blocked("search_relevant_facts", scope, user_id=user_id)
            return []

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
                        updated_at,
                        last_accessed,
                        1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND memory_type = :memory_type
                      AND embedding IS NOT NULL
                      AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                      {org_filter}
                    ORDER BY similarity DESC
                    LIMIT :fetch_limit
                    """
                )

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "embedding": str(query_embedding),
                    "min_similarity": min_similarity,
                    "fetch_limit": limit * 3,
                }
                params["org_id"] = scope.org_id

                rows = session.execute(query, params).fetchall()
                if not rows:
                    logger.debug("No similar facts found for user %s", user_id)
                    return []

                facts = []
                now = None
                try:
                    from datetime import datetime, timezone

                    now = datetime.now(timezone.utc)
                except Exception:
                    pass

                for row in rows:
                    similarity = float(row.similarity)
                    metadata = row.metadata or {}
                    fact_type = metadata.get("fact_type", "unknown")
                    access_count = metadata.get("access_count", 0)

                    effective_importance = float(row.importance)
                    try:
                        from app.engine.semantic_memory.importance_decay import (
                            calculate_effective_importance_from_timestamps,
                        )

                        effective_importance = (
                            calculate_effective_importance_from_timestamps(
                                base_importance=row.importance,
                                fact_type=fact_type,
                                last_accessed=metadata.get("last_accessed"),
                                created_at=row.created_at,
                                access_count=access_count,
                            )
                        )
                    except ImportError:
                        pass

                    recency_score = 0.5
                    if now and row.created_at:
                        try:
                            created = row.created_at
                            if created.tzinfo is None:
                                from datetime import timezone

                                created = created.replace(tzinfo=timezone.utc)
                            hours_ago = (now - created).total_seconds() / 3600
                            recency_score = 0.995 ** min(hours_ago, 2000)
                        except Exception:
                            recency_score = 0.5

                    combined_score = (
                        alpha * effective_importance
                        + beta * similarity
                        + gamma * recency_score
                    )
                    facts.append(
                        self._row_to_search_result(row, similarity=combined_score)
                    )

                facts.sort(key=lambda fact: fact.similarity, reverse=True)
                facts = facts[:limit]
                logger.debug(
                    "Semantic fact search returned %d facts for user %s "
                    "(alpha=%.1f, beta=%.1f, gamma=%.1f)",
                    len(facts),
                    user_id,
                    alpha,
                    beta,
                    gamma,
                )
                return facts
        except Exception as exc:
            logger.error("Semantic fact search failed: %s", exc)
            return []

    def get_all_user_facts(
        self,
        user_id: str,
    ) -> List[SemanticMemorySearchResult]:
        """Get all user facts for API endpoints and eviction logic."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_fact_org_scope()
        if org_filter is None:
            self._log_fact_scope_blocked("get_all_user_facts", scope, user_id=user_id)
            return []

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
                      {org_filter}
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                )

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                }
                params["org_id"] = scope.org_id

                rows = session.execute(query, params).fetchall()
                facts = [self._row_to_search_result(row) for row in rows]
                logger.debug("Retrieved %d total facts for user %s", len(facts), user_id)
                return facts
        except Exception as exc:
            logger.error("Failed to get all user facts: %s", exc)
            return []

    def find_fact_by_type(
        self,
        user_id: str,
        fact_type: str,
    ) -> Optional[SemanticMemorySearchResult]:
        """Find an existing fact by user and fact_type for upsert logic."""
        self._ensure_initialized()
        scope, org_filter = self._resolve_fact_org_scope()
        if org_filter is None:
            self._log_fact_scope_blocked("find_fact_by_type", scope, user_id=user_id)
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
                      AND metadata->>'fact_type' = :fact_type
                      {org_filter}
                    ORDER BY COALESCE(updated_at, created_at) DESC, created_at DESC
                    LIMIT 1
                    """
                )

                params = {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "fact_type": fact_type,
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                return self._row_to_search_result(row) if row else None
        except Exception as exc:
            logger.error("Failed to find fact by type: %s", exc)
            return None

    def find_similar_fact_by_embedding(
        self,
        user_id: str,
        embedding: List[float],
        similarity_threshold: float = 0.90,
        memory_type: MemoryType = MemoryType.USER_FACT,
    ) -> Optional[SemanticMemorySearchResult]:
        """Find semantically similar fact using embedding cosine similarity."""
        self._ensure_initialized()
        if not embedding:
            logger.warning(
                "Skipping similar fact lookup for user %s because embedding is empty",
                user_id,
            )
            return None
        scope, org_filter = self._resolve_fact_org_scope()
        if org_filter is None:
            self._log_fact_scope_blocked("find_similar_fact_by_embedding", scope, user_id=user_id)
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
                        1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND memory_type = :memory_type
                      AND embedding IS NOT NULL
                      {org_filter}
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT 1
                    """
                )

                params = {
                    "user_id": user_id,
                    "memory_type": memory_type.value,
                    "embedding": str(embedding),
                }
                params["org_id"] = scope.org_id

                row = session.execute(query, params).fetchone()
                if row and row.similarity >= similarity_threshold:
                    logger.debug(
                        "Found similar fact with similarity %.3f (threshold: %s)",
                        row.similarity,
                        similarity_threshold,
                    )
                    return self._row_to_search_result(
                        row,
                        similarity=float(row.similarity),
                    )
                return None
        except Exception as exc:
            logger.error("Failed to find similar fact by embedding: %s", exc)
            return None


def _hash_memory_identifier(value) -> str | None:
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(value)
