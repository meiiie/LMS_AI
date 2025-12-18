"""
Cache Manager - Unified Cache Interface.

Provides single entry point for all cache tiers with fallback.

Tiers:
- L1: Response Cache (full answers)
- L2: Retrieval Cache (document sets) - Future
- L3: Embedding Cache (query vectors) - Future

Features:
- Unified get/set interface
- Circuit breaker for resilience
- Metrics collection

Feature: semantic-cache
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.cache.models import CacheConfig, CacheLookupResult, CacheStats, CacheTier
from app.cache.semantic_cache import SemanticResponseCache, get_semantic_cache
from app.cache.invalidation import CacheInvalidationManager, get_invalidation_manager

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """State for circuit breaker pattern."""
    failure_count: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False
    
    # Configuration
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds
    
    def record_failure(self) -> None:
        """Record a failure and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                f"Circuit breaker OPENED after {self.failure_count} failures"
            )
    
    def record_success(self) -> None:
        """Record success and reset failure count."""
        self.failure_count = 0
        if self.is_open:
            self.is_open = False
            logger.info("Circuit breaker CLOSED")
    
    def is_closed(self) -> bool:
        """Check if circuit allows operations."""
        if not self.is_open:
            return True
        
        # Check if recovery timeout has passed
        if time.time() - self.last_failure_time > self.recovery_timeout:
            # Half-open: allow one request to test
            logger.info("Circuit breaker half-open, allowing test request")
            return True
        
        return False


class CacheManager:
    """
    SOTA: Unified cache interface with fallback mechanisms.
    
    Coordinates all cache tiers and provides resilient access.
    
    Usage:
        cache = CacheManager()
        
        # Look up in cache (checks L1 → L2 → L3)
        result = await cache.get(query, embedding)
        if result.hit:
            return result.value
        
        # Store response
        await cache.set(query, embedding, response, doc_ids)
    
    **Feature: semantic-cache**
    """
    
    def __init__(self, config: Optional[CacheConfig] = None):
        """
        Initialize cache manager with all tiers.
        
        Args:
            config: Optional cache configuration
        """
        self._config = config or CacheConfig()
        
        # Initialize cache tiers
        self._response_cache = get_semantic_cache(self._config)
        self._invalidation_manager = get_invalidation_manager()
        
        # Register invalidation handler
        self._invalidation_manager.register_handler(
            "response",
            self._response_cache.invalidate_by_document
        )
        
        # Circuit breaker for resilience
        self._circuit = CircuitBreakerState()
        
        # Metrics
        self._total_requests = 0
        self._cache_bypasses = 0
        
        logger.info("CacheManager initialized with response cache tier")
    
    async def get(
        self,
        query: str,
        query_embedding: List[float]
    ) -> CacheLookupResult:
        """
        Look up query in cache tiers.
        
        Currently checks L1 (response cache) only.
        Future: L2 (retrieval) and L3 (embedding) caches.
        
        Args:
            query: Original query text
            query_embedding: Query embedding vector
            
        Returns:
            CacheLookupResult with hit status and value
        """
        self._total_requests += 1
        
        # Check circuit breaker
        if not self._circuit.is_closed():
            self._cache_bypasses += 1
            logger.debug("Cache bypassed due to circuit breaker")
            return CacheLookupResult(hit=False)
        
        try:
            # L1: Response cache
            result = await self._response_cache.get(query, query_embedding)
            
            if result.hit:
                self._circuit.record_success()
                return result
            
            # Future: Check L2, L3
            
            self._circuit.record_success()
            return result
            
        except Exception as e:
            self._circuit.record_failure()
            logger.error(f"Cache lookup failed: {e}")
            return CacheLookupResult(hit=False)
    
    async def set(
        self,
        query: str,
        embedding: List[float],
        response: Any,
        document_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store response in cache.
        
        Args:
            query: Original query text
            embedding: Query embedding vector
            response: Response to cache
            document_ids: Document IDs used (for invalidation)
            metadata: Additional metadata
            
        Returns:
            True if stored successfully
        """
        # Check circuit breaker
        if not self._circuit.is_closed():
            logger.debug("Cache set bypassed due to circuit breaker")
            return False
        
        try:
            await self._response_cache.set(
                query=query,
                embedding=embedding,
                response=response,
                document_ids=document_ids,
                metadata=metadata
            )
            self._circuit.record_success()
            return True
            
        except Exception as e:
            self._circuit.record_failure()
            logger.error(f"Cache set failed: {e}")
            return False
    
    async def invalidate_document(self, document_id: str) -> Dict[str, int]:
        """
        Invalidate all cache entries related to a document.
        
        Args:
            document_id: Document ID that was updated/deleted
            
        Returns:
            Dict mapping tier to invalidation count
        """
        return await self._invalidation_manager.on_document_updated(
            document_id, 
            ""  # Empty content triggers full invalidation
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics.
        
        Returns:
            Dictionary with all stats
        """
        response_stats = self._response_cache.get_stats()
        invalidation_health = self._invalidation_manager.get_health()
        
        return {
            "total_requests": self._total_requests,
            "cache_bypasses": self._cache_bypasses,
            "circuit_breaker": {
                "is_open": self._circuit.is_open,
                "failure_count": self._circuit.failure_count
            },
            "response_cache": response_stats.to_dict(),
            "invalidation": invalidation_health
        }
    
    @property
    def is_enabled(self) -> bool:
        """Check if caching is enabled."""
        return self._config.enabled
    
    @property
    def circuit_is_open(self) -> bool:
        """Check if circuit breaker is open."""
        return self._circuit.is_open


# Singleton
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(config: Optional[CacheConfig] = None) -> CacheManager:
    """Get or create CacheManager singleton."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(config)
    return _cache_manager
