"""
Vector Memory Repository Mixin for Semantic Memory
Extracted from semantic_memory_repository.py for modularity.

Contains vector search operations:
- search_similar (cosine similarity search via pgvector)
- _stanford_rerank (Sprint 98: Stanford Generative Agents hybrid re-ranking)

Requirements: 2.2, 2.3, 2.4, 4.2
"""
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.models.semantic_memory import (
    MemoryType,
    SemanticMemorySearchResult,
)
from app.services.embedding_space_registry_service import get_active_embedding_read_space

logger = logging.getLogger(__name__)
_VECTOR_MEMORY_REPOSITORY_MISSING_ORG_WARNING = (
    "vector_memory_repository_blocked_missing_org_context"
)
_VECTOR_MEMORY_ORG_FILTER = " AND organization_id = :org_id"

_TEXT_SEARCH_STOPWORDS = {
    "la",
    "là",
    "va",
    "và",
    "cho",
    "cua",
    "của",
    "the",
    "what",
    "is",
    "are",
    "and",
    "hay",
    "hoi",
    "hỏi",
    "gi",
    "gì",
    "minh",
    "mình",
    "toi",
    "tôi",
    "ban",
    "bạn",
}


class VectorMemoryRepositoryMixin:
    """
    Mixin class providing vector search operations for SemanticMemoryRepository.

    Requires the host class to provide:
    - self._ensure_initialized() -> None
    - self._session_factory -> sessionmaker
    - self._format_embedding(embedding) -> str
    - self.TABLE_NAME -> str
    - self.DEFAULT_SEARCH_LIMIT -> int
    - self.DEFAULT_SIMILARITY_THRESHOLD -> float
    """

    def _resolve_vector_memory_org_scope(self):
        from app.engine.semantic_memory.write_audit import resolve_memory_read_scope

        scope = resolve_memory_read_scope()
        if not self._scope_allows_vector_memory(scope):
            return scope, None
        return scope, _VECTOR_MEMORY_ORG_FILTER

    def _scope_allows_vector_memory(self, scope) -> bool:
        return bool(scope.write_allowed and scope.org_id)

    def _log_vector_memory_scope_blocked(self, operation: str, scope, *, user_id: str) -> None:
        warnings = list(scope.warnings)
        if "missing_org_context" in warnings:
            warnings.append(_VECTOR_MEMORY_REPOSITORY_MISSING_ORG_WARNING)
        logger.warning(
            "[VECTOR_MEMORY] %s blocked user_hash=%s org_hash=%s org_scope=%s warnings=%s",
            operation,
            hash_memory_identifier(user_id),
            hash_memory_identifier(scope.org_id),
            scope.state,
            sorted(set(warnings)),
        )

    def _extract_text_search_terms(self, query_text: str) -> List[str]:
        raw_terms = re.findall(r"\w+", (query_text or "").lower(), flags=re.UNICODE)
        terms: list[str] = []
        seen: set[str] = set()
        for term in raw_terms:
            clean = term.strip()
            if len(clean) < 2 or clean in _TEXT_SEARCH_STOPWORDS:
                continue
            if clean in seen:
                continue
            seen.add(clean)
            terms.append(clean)
        return terms[:8]

    def search_similar(
        self,
        user_id: str,
        query_embedding: List[float],
        limit: int = 5,
        threshold: float = 0.7,
        memory_types: Optional[List[MemoryType]] = None,
        include_all_sessions: bool = True,
        use_stanford_ranking: bool = False,
    ) -> List[SemanticMemorySearchResult]:
        """
        Search for similar memories using cosine similarity.

        Cross-session Memory Persistence (v0.2.1):
        - By default, searches across ALL sessions for the user_id
        - Uses pgvector's <=> operator for cosine distance
        - Results are ordered by similarity (descending)

        Sprint 98: Stanford Generative Agents re-ranking
        - When use_stanford_ranking=True, fetches 3x candidates
        - Re-ranks by weighted sum: alpha*recency + beta*importance + gamma*relevance
        - Uses Ebbinghaus retention from importance_decay.py

        Args:
            user_id: User ID to filter memories
            query_embedding: Query vector (768 dimensions)
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0.0 - 1.0)
            memory_types: Optional filter by memory types
            include_all_sessions: If True (default), search across all sessions
            use_stanford_ranking: If True, apply Stanford hybrid re-ranking

        Returns:
            List of SemanticMemorySearchResult ordered by similarity (or Stanford score)

        Requirements: 2.2, 2.3, 2.4, 4.2
        **Feature: cross-session-memory, Property 6: Search Across All Sessions**
        """
        self._ensure_initialized()

        if not query_embedding:
            logger.warning(
                "search_similar called with empty query embedding for user_hash=%s",
                hash_memory_identifier(user_id),
            )
            return []

        scope, org_filter = self._resolve_vector_memory_org_scope()
        if org_filter is None:
            self._log_vector_memory_scope_blocked(
                "search_similar",
                scope,
                user_id=user_id,
            )
            return []

        # Stanford ranking fetches more candidates for re-ranking
        fetch_limit = limit * 3 if use_stanford_ranking else limit

        try:
            with self._session_factory() as session:
                embedding_str = self._format_embedding(query_embedding)
                active_space = get_active_embedding_read_space("semantic_memories")

                # Build type filter if specified
                type_filter = ""
                params = {
                    "user_id": user_id,
                    "embedding": embedding_str,
                    "threshold": threshold,
                    "limit": fetch_limit
                }
                params["org_id"] = scope.org_id

                if memory_types:
                    type_values = [t.value for t in memory_types]
                    type_filter = "AND memory_type = ANY(:memory_types)"
                    params["memory_types"] = type_values

                if active_space is not None and active_space.storage_kind == "shadow":
                    safe_dims = max(1, int(active_space.dimensions))
                    query = text(f"""
                        SELECT
                            sm.id,
                            sm.content,
                            sm.memory_type,
                            sm.importance,
                            sm.metadata,
                            sm.created_at,
                            sm.last_accessed,
                            sm.access_count,
                            1 - ((sv.embedding::vector({safe_dims})) <=> CAST(:embedding AS vector({safe_dims}))) AS similarity
                        FROM {self.TABLE_NAME} sm
                        JOIN semantic_memory_vectors sv
                          ON sv.memory_id = sm.id
                         AND sv.space_fingerprint = :space_fingerprint
                         AND sv.dimensions = {safe_dims}
                        WHERE sm.user_id = :user_id
                          AND 1 - ((sv.embedding::vector({safe_dims})) <=> CAST(:embedding AS vector({safe_dims}))) >= :threshold
                          {type_filter.replace('memory_type', 'sm.memory_type')}
                          {org_filter.replace('organization_id', 'sm.organization_id')}
                        ORDER BY (sv.embedding::vector({safe_dims})) <=> CAST(:embedding AS vector({safe_dims}))
                        LIMIT :limit
                    """)
                    params["space_fingerprint"] = active_space.space_fingerprint
                else:
                    # Cosine similarity = 1 - cosine distance
                    # pgvector <=> returns cosine distance
                    # Sprint 98: Also fetch last_accessed, access_count for Stanford ranking
                    query = text(f"""
                        SELECT
                            id,
                            content,
                            memory_type,
                            importance,
                            metadata,
                            created_at,
                            last_accessed,
                            access_count,
                            1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
                        FROM {self.TABLE_NAME}
                        WHERE user_id = :user_id
                          AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :threshold
                          {type_filter}
                          {org_filter}
                        ORDER BY embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                    """)

                result = session.execute(query, params)
                rows = result.fetchall()

                memories = []
                for row in rows:
                    # Handle NaN similarity (can happen with zero vectors)
                    similarity = float(row.similarity) if row.similarity is not None else 0.0
                    if math.isnan(similarity) or math.isinf(similarity):
                        similarity = 0.0
                    # Clamp to valid range [0, 1]
                    similarity = max(0.0, min(1.0, similarity))

                    memories.append(SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=similarity,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    ))

                # Sprint 98: Stanford Generative Agents hybrid re-ranking
                if use_stanford_ranking and memories:
                    # Build row data for reranking (need last_accessed, access_count)
                    row_data = []
                    for i, row in enumerate(rows):
                        last_accessed = getattr(row, "last_accessed", None)
                        access_count = getattr(row, "access_count", None) or 0
                        row_data.append({
                            "last_accessed": last_accessed,
                            "access_count": access_count,
                        })
                    memories = self._stanford_rerank(memories, row_data, limit)

                logger.debug(
                    "Found %d similar memories for user_hash=%s",
                    len(memories),
                    hash_memory_identifier(user_id),
                )
                return memories

        except Exception as e:
            logger.error("Failed to search similar memories: %s", e)
            return []

    def search_similar_text(
        self,
        user_id: str,
        query_text: str,
        limit: int = 5,
        memory_types: Optional[List[MemoryType]] = None,
    ) -> List[SemanticMemorySearchResult]:
        """
        Fallback lexical recall when semantic embeddings are unavailable.

        This keeps memory recall alive during embedding provider outages without
        pretending the result is semantic-similarity quality.
        """
        self._ensure_initialized()

        terms = self._extract_text_search_terms(query_text)
        if not terms:
            return []

        scope, org_filter = self._resolve_vector_memory_org_scope()
        if org_filter is None:
            self._log_vector_memory_scope_blocked(
                "search_similar_text",
                scope,
                user_id=user_id,
            )
            return []

        try:
            with self._session_factory() as session:
                type_filter = ""
                params: Dict[str, Any] = {
                    "user_id": user_id,
                    "limit": limit,
                }
                params["org_id"] = scope.org_id

                if memory_types:
                    params["memory_types"] = [item.value for item in memory_types]
                    type_filter = "AND memory_type = ANY(:memory_types)"

                score_clauses = []
                match_clauses = []
                for index, term in enumerate(terms):
                    pattern_key = f"pattern_{index}"
                    params[pattern_key] = f"%{term}%"
                    score_clauses.append(
                        f"CASE WHEN LOWER(content) LIKE :{pattern_key} THEN 1 ELSE 0 END"
                    )
                    match_clauses.append(f"LOWER(content) LIKE :{pattern_key}")

                query = text(
                    f"""
                    SELECT
                        id,
                        content,
                        memory_type,
                        importance,
                        metadata,
                        created_at,
                        ({' + '.join(score_clauses)}) AS lexical_hits
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      {type_filter}
                      AND ({' OR '.join(match_clauses)})
                      {org_filter}
                    ORDER BY lexical_hits DESC, importance DESC, created_at DESC
                    LIMIT :limit
                    """
                )

                rows = session.execute(query, params).fetchall()
                memories: List[SemanticMemorySearchResult] = []
                normalizer = max(len(terms), 1)
                for row in rows:
                    hits = int(getattr(row, "lexical_hits", 0) or 0)
                    similarity = max(0.0, min(1.0, hits / normalizer))
                    memories.append(
                        SemanticMemorySearchResult(
                            id=row.id,
                            content=row.content,
                            memory_type=MemoryType(row.memory_type),
                            importance=row.importance,
                            similarity=similarity,
                            metadata=row.metadata or {},
                            created_at=row.created_at,
                        )
                    )

                logger.debug(
                    "Fallback text recall found %d memories for user_hash=%s",
                    len(memories),
                    hash_memory_identifier(user_id),
                )
                return memories
        except Exception as exc:
            logger.error(
                "Failed fallback text recall for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                exc,
            )
            return []

    def _stanford_rerank(
        self,
        memories: List[SemanticMemorySearchResult],
        row_data: List[Dict[str, Any]],
        limit: int,
    ) -> List[SemanticMemorySearchResult]:
        """
        Re-rank memories using Stanford Generative Agents formula.

        score = alpha * recency + beta * importance + gamma * relevance

        Recency uses Ebbinghaus forgetting curve from importance_decay.py.
        All components normalized to [0, 1].

        Args:
            memories: Candidate memories from similarity search
            row_data: Parallel list with last_accessed, access_count per memory
            limit: Final number of results to return

        Returns:
            Top `limit` memories sorted by Stanford composite score
        """
        try:
            from app.core.config import settings
            alpha = settings.stanford_recency_weight
            beta = settings.stanford_importance_weight
            gamma = settings.stanford_relevance_weight
        except Exception:
            alpha, beta, gamma = 0.3, 0.3, 0.4

        try:
            from app.engine.semantic_memory.importance_decay import calculate_retention, get_stability_hours
        except ImportError:
            # Fallback: skip reranking if decay module unavailable
            return memories[:limit]

        now = datetime.now(timezone.utc)
        scored = []

        for i, mem in enumerate(memories):
            # Relevance = similarity (already 0-1)
            relevance = mem.similarity

            # Importance (already 0-1)
            importance = mem.importance

            # Recency via Ebbinghaus retention
            data = row_data[i] if i < len(row_data) else {}
            last_accessed = data.get("last_accessed")
            access_count = data.get("access_count", 0) or 0

            reference_time = last_accessed or mem.created_at
            if reference_time is not None:
                if reference_time.tzinfo is None:
                    reference_time = reference_time.replace(tzinfo=timezone.utc)
                hours_elapsed = max((now - reference_time).total_seconds() / 3600.0, 0.0)
            else:
                hours_elapsed = 0.0

            # Get fact_type from metadata for stability calculation
            fact_type = mem.metadata.get("fact_type", "preference")
            stability = get_stability_hours(fact_type)
            recency = calculate_retention(hours_elapsed, stability, access_count)

            score = alpha * recency + beta * importance + gamma * relevance
            scored.append((score, mem))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [mem for _, mem in scored[:limit]]
