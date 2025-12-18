"""
Semantic Response Cache - SOTA RAG Latency Optimization.

L1 Cache: Stores full RAG responses with semantic matching.

Features:
- Cosine similarity matching (threshold configurable)
- TTL-based expiration
- LRU eviction when full
- Metrics collection

References:
- HuggingFace Semantic Cache
- AllThingsOpen 2024 - 65x latency reduction

Feature: semantic-cache
"""

import logging
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.cache.models import (
    CacheConfig,
    CacheEntry,
    CacheLookupResult,
    CacheStats,
    CacheTier,
)

logger = logging.getLogger(__name__)


class SemanticResponseCache:
    """
    SOTA 2025: Semantic response caching for RAG.
    
    Instead of exact query matching, uses embedding similarity
    to serve cached responses for semantically similar queries.
    
    Usage:
        cache = SemanticResponseCache()
        
        # Check cache first
        result = await cache.get(query, query_embedding)
        if result.hit:
            return result.value
        
        # Generate response...
        response = await generate_response(query)
        
        # Store in cache
        await cache.set(query, query_embedding, response)
    
    **Feature: semantic-cache**
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        """
        Initialize semantic response cache.
        
        Args:
            config: Optional cache configuration
        """
        self._config = config or CacheConfig()
        
        # Use OrderedDict for LRU eviction
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        
        # Statistics
        self._stats = CacheStats(tier=CacheTier.RESPONSE)
        
        # Lock for thread safety (simple implementation)
        self._initialized = True
        
        logger.info(
            f"SemanticResponseCache initialized: "
            f"threshold={self._config.similarity_threshold}, "
            f"ttl={self._config.response_ttl}s, "
            f"max_entries={self._config.max_response_entries}"
        )
    
    async def get(
        self, 
        query: str, 
        query_embedding: List[float]
    ) -> CacheLookupResult:
        """
        Find semantically similar cached response.
        
        Args:
            query: Original query text
            query_embedding: Query embedding vector (768-dim)
            
        Returns:
            CacheLookupResult with hit status and cached value if found
        """
        if not self._config.enabled:
            return CacheLookupResult(hit=False, tier=CacheTier.RESPONSE)
        
        start_time = time.time()
        best_match: Optional[Tuple[CacheEntry, float]] = None
        
        # Convert query embedding to numpy for fast computation
        query_vec = np.array(query_embedding)
        
        # Search for similar entries
        for key, entry in list(self._cache.items()):
            # Skip expired entries
            if entry.is_expired():
                self._cache.pop(key, None)
                self._stats.evictions += 1
                continue
            
            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_vec, np.array(entry.embedding))
            
            if similarity >= self._config.similarity_threshold:
                if best_match is None or similarity > best_match[1]:
                    best_match = (entry, similarity)
        
        lookup_time = (time.time() - start_time) * 1000
        
        if best_match:
            entry, similarity = best_match
            entry.touch()  # Update access time
            
            # Move to end for LRU
            self._cache.move_to_end(entry.key)
            
            self._stats.hits += 1
            self._update_avg_similarity(similarity)
            
            if self._config.log_cache_operations:
                logger.info(
                    f"[CACHE] HIT query='{query[:50]}...' "
                    f"similarity={similarity:.3f} "
                    f"age={entry.age_seconds:.0f}s"
                )
            
            return CacheLookupResult(
                hit=True,
                entry=entry,
                similarity=similarity,
                tier=CacheTier.RESPONSE,
                lookup_time_ms=lookup_time
            )
        
        self._stats.misses += 1
        
        if self._config.log_cache_operations:
            logger.debug(f"[CACHE] MISS query='{query[:50]}...'")
        
        return CacheLookupResult(
            hit=False,
            tier=CacheTier.RESPONSE,
            lookup_time_ms=lookup_time
        )
    
    async def set(
        self,
        query: str,
        embedding: List[float],
        response: Any,
        document_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store response with semantic key.
        
        Args:
            query: Original query text
            embedding: Query embedding vector
            response: Full response to cache
            document_ids: List of document IDs used (for invalidation)
            metadata: Additional metadata
        """
        if not self._config.enabled:
            return
        
        # Evict if at capacity
        while len(self._cache) >= self._config.max_response_entries:
            # Remove oldest (first item in OrderedDict)
            oldest_key = next(iter(self._cache))
            self._cache.pop(oldest_key)
            self._stats.evictions += 1
            logger.debug(f"[CACHE] Evicted LRU entry: {oldest_key[:30]}...")
        
        # Create entry
        entry = CacheEntry(
            key=query,
            embedding=embedding,
            value=response,
            tier=CacheTier.RESPONSE,
            ttl=self._config.response_ttl,
            document_ids=document_ids or [],
            metadata=metadata or {}
        )
        
        self._cache[query] = entry
        self._stats.total_entries = len(self._cache)
        
        if self._config.log_cache_operations:
            logger.info(
                f"[CACHE] SET query='{query[:50]}...' "
                f"docs={len(entry.document_ids)} "
                f"ttl={entry.ttl}s"
            )
    
    async def invalidate_by_document(self, document_id: str) -> int:
        """
        Invalidate all cache entries that used a specific document.
        
        Called when document content changes.
        
        Args:
            document_id: ID of updated document
            
        Returns:
            Number of entries invalidated
        """
        invalidated = 0
        keys_to_remove = []
        
        for key, entry in self._cache.items():
            if document_id in entry.document_ids:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            self._cache.pop(key, None)
            invalidated += 1
        
        self._stats.invalidations += invalidated
        self._stats.total_entries = len(self._cache)
        
        if invalidated > 0:
            logger.info(f"[CACHE] Invalidated {invalidated} entries for doc: {document_id}")
        
        return invalidated
    
    async def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        self._stats.total_entries = 0
        logger.info(f"[CACHE] Cleared {count} entries")
        return count
    
    def get_stats(self) -> CacheStats:
        """Get current cache statistics."""
        self._stats.total_entries = len(self._cache)
        return self._stats
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def _update_avg_similarity(self, new_similarity: float) -> None:
        """Update running average of similarity on hits."""
        if self._stats.hits == 1:
            self._stats.avg_similarity_on_hit = new_similarity
        else:
            # Exponential moving average
            alpha = 0.1
            self._stats.avg_similarity_on_hit = (
                alpha * new_similarity + 
                (1 - alpha) * self._stats.avg_similarity_on_hit
            )


# Singleton
_semantic_cache: Optional[SemanticResponseCache] = None


def get_semantic_cache(config: Optional[CacheConfig] = None) -> SemanticResponseCache:
    """Get or create SemanticResponseCache singleton."""
    global _semantic_cache
    if _semantic_cache is None:
        _semantic_cache = SemanticResponseCache(config)
    return _semantic_cache
