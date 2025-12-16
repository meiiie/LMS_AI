"""
Hybrid Search Service for Maritime AI Tutor.

Combines Dense Search (pgvector) and Sparse Search (PostgreSQL tsvector)
with RRF reranking for optimal retrieval.

SOTA Dec 2025:
- Neural Reranker (BGE/Cohere) for +15-25% accuracy
- HyDE query enhancement for +20-30% on complex queries

Feature: hybrid-search, sparse-search-migration, neural-reranker, hyde
Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 5.1, 5.2, 7.1, 7.2, 7.3, 7.4
"""

import logging
import re
from typing import List, Optional

from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from app.engine.rrf_reranker import HybridSearchResult, RRFReranker
from app.repositories.dense_search_repository import get_dense_search_repository
from app.repositories.sparse_search_repository import SparseSearchRepository
from app.services.neural_reranker import get_neural_reranker, RerankedResult
from app.services.hyde_service import get_hyde_service

logger = logging.getLogger(__name__)


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
        rrf_k: int = 60
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
        self._embeddings = GeminiOptimizedEmbeddings()
        self._dense_repo = get_dense_search_repository()  # SINGLETON
        self._sparse_repo = SparseSearchRepository()
        self._reranker = RRFReranker(k=rrf_k)
        
        logger.info(
            f"HybridSearchService initialized with weights: "
            f"dense={dense_weight}, sparse={sparse_weight}, k={rrf_k}"
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
        return self._embeddings.embed_query(query)
    
    async def search(
        self,
        query: str,
        limit: int = 5
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
        logger.info(f"Hybrid search for: {query}")
        
        # Extract rule numbers for logging
        rule_numbers = self._extract_rule_numbers(query)
        if rule_numbers:
            logger.info(f"Detected rule numbers: {rule_numbers}")
        
        dense_results = []
        sparse_results = []
        search_method = "hybrid"
        
        # Try dense search
        dense_error = None
        if self._dense_weight > 0:
            try:
                query_embedding = await self._generate_query_embedding(query)
                dense_results = await self._dense_repo.search(
                    query_embedding, 
                    limit=limit * 2
                )
                logger.info(f"Dense search returned {len(dense_results)} results")
            except Exception as e:
                dense_error = e
                logger.error(f"Dense search failed: {e}")
                search_method = "sparse_only"
        else:
            search_method = "sparse_only"
        
        # Try sparse search
        sparse_error = None
        if self._sparse_weight > 0:
            try:
                sparse_results = await self._sparse_repo.search(
                    query, 
                    limit=limit * 2
                )
                logger.info(f"Sparse search returned {len(sparse_results)} results")
            except Exception as e:
                sparse_error = e
                logger.error(f"Sparse search failed: {e}")
                if search_method == "sparse_only":
                    # Both failed
                    logger.critical("Both dense and sparse search failed!")
                    return []
                search_method = "dense_only"
        else:
            if search_method == "hybrid":
                search_method = "dense_only"
        
        # Merge results based on what succeeded
        if search_method == "hybrid":
            results = self._reranker.merge(
                dense_results,
                sparse_results,
                dense_weight=self._dense_weight,
                sparse_weight=self._sparse_weight,
                limit=limit,
                query=query  # Pass query for title match boosting
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
            f"Hybrid search completed: {len(results)} results, method={search_method}"
        )
        
        return results
    
    async def search_dense_only(
        self,
        query: str,
        limit: int = 5
    ) -> List[HybridSearchResult]:
        """
        Perform dense-only search (semantic similarity).
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of results from dense search only
        """
        try:
            query_embedding = await self._generate_query_embedding(query)
            dense_results = await self._dense_repo.search(query_embedding, limit)
            return self._reranker.merge_single_source(dense_results, "dense", limit)
        except Exception as e:
            logger.error(f"Dense-only search failed: {e}")
            return []
    
    async def search_sparse_only(
        self,
        query: str,
        limit: int = 5
    ) -> List[HybridSearchResult]:
        """
        Perform sparse-only search (keyword matching).
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of results from sparse search only
        """
        try:
            sparse_results = await self._sparse_repo.search(query, limit)
            return self._reranker.merge_single_source(sparse_results, "sparse", limit)
        except Exception as e:
            logger.error(f"Sparse-only search failed: {e}")
            return []
    
    async def search_with_neural_rerank(
        self,
        query: str,
        limit: int = 5,
        rerank_top_k: int = 20
    ) -> List[RerankedResult]:
        """
        Perform hybrid search with neural reranking.
        
        SOTA Dec 2025: Two-stage retrieval:
        1. Hybrid search to get candidate pool
        2. Neural reranker (BGE/Cohere) for precision ranking
        
        This provides +15-25% accuracy improvement over RRF alone.
        
        Args:
            query: Search query text
            limit: Final number of results to return
            rerank_top_k: Number of candidates to rerank (more = better but slower)
            
        Returns:
            List of RerankedResult with neural rerank scores
            
        **Feature: neural-reranker**
        """
        # Stage 1: Hybrid search to get candidate pool
        candidates = await self.search(query, limit=rerank_top_k)
        
        if not candidates:
            return []
        
        # Convert to dict format for reranker
        docs = []
        for c in candidates:
            docs.append({
                'node_id': c.node_id,
                'content': c.content,
                'title': c.title,
                'score': c.rrf_score,
                'page_number': c.page_number,
                'document_id': c.document_id,
                'image_url': c.image_url,
                'bounding_boxes': c.bounding_boxes
            })
        
        # Stage 2: Neural reranking
        reranker = get_neural_reranker()
        reranked = await reranker.rerank(query, docs, top_k=limit)
        
        if reranked:
            logger.info(
                f"Neural rerank: {len(candidates)} candidates → {len(reranked)} results, "
                f"best={reranked[0].final_score:.3f}"
            )
        
        return reranked
    
    async def search_with_hyde(
        self,
        query: str,
        limit: int = 5,
        force_hyde: bool = False
    ) -> List[HybridSearchResult]:
        """
        Perform hybrid search with HyDE query enhancement.
        
        SOTA Dec 2025: Hypothetical Document Embeddings
        - Generate hypothetical answer using LLM
        - Search using hypothetical doc instead of query
        - +20-30% accuracy for vague/complex queries
        
        Args:
            query: Original search query
            limit: Maximum number of results
            force_hyde: If True, always use HyDE regardless of query type
            
        Returns:
            List of HybridSearchResult
            
        **Feature: hyde**
        """
        try:
            hyde_service = get_hyde_service()
            
            # Check if HyDE should be used for this query
            if force_hyde or hyde_service.should_use_hyde(query):
                # Generate hypothetical document
                enhanced_query = await hyde_service.enhance_query(query, force=force_hyde)
                
                if enhanced_query != query:
                    logger.info(
                        f"HyDE enhanced query: {len(query)} chars → {len(enhanced_query)} chars"
                    )
                    
                    # Use enhanced query for dense search
                    query_embedding = await self._generate_query_embedding(enhanced_query)
                    
                    # Dense-only search with HyDE (sparse may not benefit from HyDE)
                    dense_results = await self._dense_repo.search(
                        query_embedding, 
                        limit=limit * 2
                    )
                    
                    # Also run sparse with original query for keyword matching
                    sparse_results = await self._sparse_repo.search(query, limit=limit * 2)
                    
                    # Merge with RRF
                    results = self._reranker.merge(
                        dense_results,
                        sparse_results,
                        dense_weight=0.7,  # Favor dense (HyDE-enhanced)
                        sparse_weight=0.3,
                        limit=limit,
                        query=query
                    )
                    
                    logger.info(f"HyDE search completed: {len(results)} results")
                    return results
            
            # Fallback to standard hybrid search
            return await self.search(query, limit)
            
        except Exception as e:
            logger.warning(f"HyDE search failed, falling back to standard: {e}")
            return await self.search(query, limit)
    
    async def search_sota(
        self,
        query: str,
        limit: int = 5,
        use_hyde: bool = True,
        use_neural_rerank: bool = True
    ) -> List[RerankedResult]:
        """
        SOTA Dec 2025: Full pipeline search with all enhancements.
        
        Combines:
        1. HyDE query enhancement (for complex queries)
        2. Hybrid search (dense + sparse)
        3. Neural reranking (BGE/Cohere)
        
        Args:
            query: Search query
            limit: Final number of results
            use_hyde: Enable HyDE enhancement
            use_neural_rerank: Enable neural reranking
            
        Returns:
            List of RerankedResult with best accuracy
            
        **Feature: sota-search**
        """
        try:
            # Step 1: HyDE enhancement (if enabled and beneficial)
            search_query = query
            if use_hyde:
                hyde_service = get_hyde_service()
                if hyde_service.should_use_hyde(query):
                    search_query = await hyde_service.enhance_query(query)
                    logger.info(f"SOTA: HyDE enhanced query")
            
            # Step 2: Hybrid search candidates
            candidates = await self.search(search_query, limit=20)
            
            if not candidates:
                return []
            
            # Step 3: Neural reranking (if enabled)
            if use_neural_rerank:
                docs = [
                    {
                        'node_id': c.node_id,
                        'content': c.content,
                        'title': c.title,
                        'score': c.rrf_score,
                        'page_number': c.page_number,
                        'document_id': c.document_id,
                        'image_url': c.image_url,
                        'bounding_boxes': c.bounding_boxes
                    }
                    for c in candidates
                ]
                
                reranker = get_neural_reranker()
                results = await reranker.rerank(query, docs, top_k=limit)
                
                logger.info(f"SOTA search completed: HyDE={use_hyde}, Rerank={use_neural_rerank}")
                return results
            
            # Fallback: convert to RerankedResult without reranking
            return [
                RerankedResult(
                    node_id=c.node_id,
                    content=c.content,
                    title=c.title,
                    original_score=c.rrf_score,
                    rerank_score=c.rrf_score,
                    final_score=c.rrf_score,
                    page_number=c.page_number,
                    document_id=c.document_id,
                    image_url=c.image_url,
                    bounding_boxes=c.bounding_boxes
                )
                for c in candidates[:limit]
            ]
            
        except Exception as e:
            logger.error(f"SOTA search failed: {e}")
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
            embedding = self._embeddings.embed_documents([content])[0]
            return await self._dense_repo.store_embedding(node_id, embedding)
        except Exception as e:
            logger.error(f"Failed to store embedding for {node_id}: {e}")
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
