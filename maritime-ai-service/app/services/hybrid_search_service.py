"""
Hybrid Search Service for Wiii.

Combines Dense Search (pgvector) and Sparse Search (PostgreSQL tsvector)
with RRF reranking for optimal retrieval.

Feature: hybrid-search, sparse-search-migration
Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 5.1, 5.2, 7.1, 7.2, 7.3, 7.4
"""

import asyncio
import logging
import re
from typing import List, Optional

from app.engine.embedding_runtime import EmbeddingBackendProtocol, get_embedding_backend
from app.engine.rrf_reranker import HybridSearchResult, RRFReranker
from app.repositories.dense_search_repository import get_dense_search_repository

logger = logging.getLogger(__name__)


class HybridSearchUnavailableError(RuntimeError):
    """Raised when every enabled retrieval path fails operationally."""


class HybridSearchService:
    """
    Main service for hybrid search combining Dense and Sparse search.
    
    Coordinates:
    1. Query preprocessing (extract keywords, rule numbers)
    2. Dense search via pgvector (semantic similarity)
    3. Sparse search via PostgreSQL tsvector (keyword matching)
    4. RRF reranking to merge results
    
    Feature: hybrid-search, sparse-search-migration
    Requirements: 1.1, 1.2, 1.3, 5.1, 5.2
    """
    
    # Default weights for search methods
    DEFAULT_DENSE_WEIGHT = 0.5
    DEFAULT_SPARSE_WEIGHT = 0.5
    
    def __init__(
        self,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        sparse_weight: float = DEFAULT_SPARSE_WEIGHT,
        rrf_k: int = 60,
        embedding_service: Optional[EmbeddingBackendProtocol] = None,
    ):
        """
        Initialize hybrid search service.
        
        Args:
            dense_weight: Weight for dense search results (0.0-1.0)
            sparse_weight: Weight for sparse search results (0.0-1.0)
            rrf_k: RRF constant k (default 60)
            
        Requirements: 5.1, 5.2
        """
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight
        
        # Initialize components (use singleton for dense repo)
        self._embeddings = embedding_service or get_embedding_backend()
        self._dense_repo = get_dense_search_repository()  # SINGLETON
        from app.repositories.sparse_search_repository import get_sparse_search_repository
        self._sparse_repo = get_sparse_search_repository()  # SINGLETON
        self._reranker = RRFReranker(k=rrf_k)
        
        logger.info(
            "HybridSearchService initialized with weights: "
            "dense=%s, sparse=%s, k=%d",
            dense_weight, sparse_weight, rrf_k,
        )
    
    @property
    def dense_weight(self) -> float:
        """Get dense search weight."""
        return self._dense_weight
    
    @property
    def sparse_weight(self) -> float:
        """Get sparse search weight."""
        return self._sparse_weight
    
    def _extract_rule_numbers(self, query: str) -> List[str]:
        """
        Extract rule numbers from query.
        
        Handles patterns like:
        - "Rule 15", "rule 15"
        - "Quy tắc 19", "quy tắc 19"
        - "Điều 15", "điều 15"
        - Just numbers: "15", "19"
        
        Args:
            query: Search query
            
        Returns:
            List of rule number strings
        """
        patterns = [
            r'[Rr]ule\s*(\d+)',
            r'[Qq]uy\s*tắc\s*(\d+)',
            r'[Đđ]iều\s*(\d+)',
            r'\b(\d+)\b'
        ]
        
        numbers = set()
        for pattern in patterns:
            matches = re.findall(pattern, query)
            numbers.update(matches)
        
        return list(numbers)
    
    async def _generate_query_embedding(self, query: str) -> List[float]:
        """
        Generate embedding for search query.
        
        Uses RETRIEVAL_QUERY task type for optimal search performance.
        
        Args:
            query: Search query text
            
        Returns:
            768-dim L2-normalized embedding vector
            
        Requirements: 2.3
        """
        return await self._embeddings.aembed_query(query)

    @staticmethod
    def _has_query_embedding(embedding: Optional[List[float]]) -> bool:
        return bool(embedding)
    
    async def search(
        self,
        query: str,
        limit: int = 5,
        domain_id: Optional[str] = None,
        org_id: Optional[str] = None,
        *,
        raise_on_total_failure: bool = False,
    ) -> List[HybridSearchResult]:
        """
        Perform hybrid search combining dense and sparse results.
        
        Implements graceful fallback when one method fails.
        
        Args:
            query: Search query text
            limit: Maximum number of results
            
        Returns:
            List of HybridSearchResult sorted by combined score
            
        Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 7.2, 7.3, 7.4
        """
        logger.info("Hybrid search for: %s", query)
        
        # Extract rule numbers for logging
        rule_numbers = self._extract_rule_numbers(query)
        if rule_numbers:
            logger.info("Detected rule numbers: %s", rule_numbers)
        
        dense_results = []
        sparse_results = []
        search_method = "hybrid"

        # Determine which searches to run
        run_dense = self._dense_weight > 0
        run_sparse = self._sparse_weight > 0

        # If both enabled, run in parallel for performance
        if run_dense and run_sparse:
            try:
                # Generate embedding first (needed for dense search)
                query_embedding = await self._generate_query_embedding(query)

                if not self._has_query_embedding(query_embedding):
                    logger.warning(
                        "Hybrid search query embedding unavailable; falling back to sparse search for query=%s",
                        query,
                    )
                    sparse_results = await self._sparse_repo.search(
                        query,
                        limit=limit * 2,
                        domain_id=domain_id,
                        org_id=org_id,
                    )
                    search_method = "sparse_only"
                    results = self._reranker.merge_single_source(
                        sparse_results,
                        "sparse",
                        limit=limit,
                    )
                    for r in results:
                        r.search_method = "sparse_only"
                    return results

                # Create tasks for parallel execution
                dense_task = self._dense_repo.search(query_embedding, limit=limit * 2, domain_id=domain_id, org_id=org_id)
                sparse_task = self._sparse_repo.search(query, limit=limit * 2, domain_id=domain_id, org_id=org_id)

                # Run in parallel
                results = await asyncio.gather(
                    dense_task,
                    sparse_task,
                    return_exceptions=True
                )

                dense_results, sparse_results = results

                # Handle failures gracefully
                if isinstance(dense_results, Exception):
                    logger.warning("Dense search failed: %s", dense_results)
                    dense_results = []
                    search_method = "sparse_only"
                else:
                    logger.info("Dense search returned %d results", len(dense_results))

                if isinstance(sparse_results, Exception):
                    logger.warning("Sparse search failed: %s", sparse_results)
                    sparse_results = []
                    if search_method == "sparse_only":
                        # Both failed
                        logger.critical("Both dense and sparse search failed!")
                        if raise_on_total_failure:
                            raise HybridSearchUnavailableError(
                                "dense and sparse retrieval both failed"
                            )
                        return []
                    search_method = "dense_only"
                else:
                    logger.info("Sparse search returned %d results", len(sparse_results))

            except Exception as e:
                if isinstance(e, HybridSearchUnavailableError):
                    raise
                logger.error("Parallel search failed: %s", e)
                if raise_on_total_failure:
                    raise HybridSearchUnavailableError(
                        "hybrid retrieval failed before a fallback completed"
                    ) from e
                return []

        # If only one enabled, run sequentially (fallback)
        elif run_dense:
            try:
                query_embedding = await self._generate_query_embedding(query)
                if not self._has_query_embedding(query_embedding):
                    logger.warning(
                        "Dense-only hybrid search skipped because query embedding is empty for query=%s",
                        query,
                    )
                    if raise_on_total_failure:
                        raise HybridSearchUnavailableError(
                            "dense retrieval could not produce a query embedding"
                        )
                    return []
                dense_results = await self._dense_repo.search(
                    query_embedding,
                    limit=limit * 2,
                    domain_id=domain_id,
                    org_id=org_id
                )
                logger.info("Dense search returned %d results", len(dense_results))
                search_method = "dense_only"
            except Exception as e:
                logger.error("Dense search failed: %s", e)
                if raise_on_total_failure:
                    raise HybridSearchUnavailableError(
                        "dense retrieval failed"
                    ) from e
                return []

        elif run_sparse:
            try:
                sparse_results = await self._sparse_repo.search(
                    query,
                    limit=limit * 2,
                    domain_id=domain_id,
                    org_id=org_id
                )
                logger.info("Sparse search returned %d results", len(sparse_results))
                search_method = "sparse_only"
            except Exception as e:
                logger.error("Sparse search failed: %s", e)
                if raise_on_total_failure:
                    raise HybridSearchUnavailableError(
                        "sparse retrieval failed"
                    ) from e
                return []

        else:
            # Neither enabled
            logger.warning("Both dense and sparse weights are 0, no search performed")
            if raise_on_total_failure:
                raise HybridSearchUnavailableError(
                    "no knowledge retrieval path is enabled"
                )
            return []
        
        # Merge results based on what succeeded
        if search_method == "hybrid":
            results = self._reranker.merge(
                dense_results,
                sparse_results,
                dense_weight=self._dense_weight,
                sparse_weight=self._sparse_weight,
                limit=limit,
                query=query,  # Pass query for title match boosting
                active_domain_id=domain_id  # Sprint 136: Cross-domain boost
            )
        elif search_method == "dense_only":
            results = self._reranker.merge_single_source(
                dense_results, 
                "dense", 
                limit=limit
            )
            # Update method flag
            for r in results:
                r.search_method = "dense_only"
        else:  # sparse_only
            results = self._reranker.merge_single_source(
                sparse_results, 
                "sparse", 
                limit=limit
            )
            # Update method flag
            for r in results:
                r.search_method = "sparse_only"
        
        logger.info(
            "Hybrid search completed: %d results, method=%s",
            len(results), search_method,
        )
        
        return results
    
    async def search_dense_only(
        self,
        query: str,
        limit: int = 5,
        domain_id: Optional[str] = None
    ) -> List[HybridSearchResult]:
        """
        Perform dense-only search (semantic similarity).

        Args:
            query: Search query
            limit: Maximum results
            domain_id: Filter by domain (multi-domain knowledge isolation)

        Returns:
            List of results from dense search only
        """
        try:
            query_embedding = await self._generate_query_embedding(query)
            if not self._has_query_embedding(query_embedding):
                logger.warning(
                    "Dense-only search skipped because query embedding is empty for query=%s",
                    query,
                )
                return []
            dense_results = await self._dense_repo.search(query_embedding, limit, domain_id=domain_id)
            return self._reranker.merge_single_source(dense_results, "dense", limit)
        except Exception as e:
            logger.error("Dense-only search failed: %s", e)
            return []

    async def search_sparse_only(
        self,
        query: str,
        limit: int = 5,
        domain_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> List[HybridSearchResult]:
        """
        Perform sparse-only search (keyword matching).

        Args:
            query: Search query
            limit: Maximum results
            domain_id: Filter by domain (multi-domain knowledge isolation)
            org_id: Organization ID for multi-tenant isolation (Sprint 175b)

        Returns:
            List of results from sparse search only
        """
        try:
            sparse_results = await self._sparse_repo.search(query, limit, domain_id=domain_id, org_id=org_id)
            return self._reranker.merge_single_source(sparse_results, "sparse", limit)
        except Exception as e:
            logger.error("Sparse-only search failed: %s", e)
            return []
    
    def is_available(self) -> bool:
        """Check if at least one search method is available."""
        return self._dense_repo.is_available() or self._sparse_repo.is_available()
    
    async def store_embedding(
        self,
        node_id: str,
        content: str
    ) -> bool:
        """
        Generate and store embedding for a knowledge node.
        
        Args:
            node_id: Knowledge node ID
            content: Text content to embed
            
        Returns:
            True if successful
            
        Requirements: 6.1
        """
        try:
            embedding = (await self._embeddings.aembed_documents([content]))[0]
            return await self._dense_repo.store_embedding(node_id, embedding)
        except Exception as e:
            logger.error("Failed to store embedding for %s: %s", node_id, e)
            return False
    
    async def delete_embedding(self, node_id: str) -> bool:
        """
        Delete embedding for a knowledge node.
        
        Args:
            node_id: Knowledge node ID
            
        Returns:
            True if successful
            
        Requirements: 6.3
        """
        return await self._dense_repo.delete_embedding(node_id)
    
    async def close(self):
        """Close all connections."""
        await self._dense_repo.close()
        await self._sparse_repo.close()
        logger.info("HybridSearchService closed")


# Singleton instance
_hybrid_search_service: Optional[HybridSearchService] = None


def get_hybrid_search_service() -> HybridSearchService:
    """Get or create singleton HybridSearchService instance."""
    global _hybrid_search_service
    
    if _hybrid_search_service is None:
        _hybrid_search_service = HybridSearchService()
    
    return _hybrid_search_service
