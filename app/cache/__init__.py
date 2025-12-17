"""
Cache Module - SOTA RAG Latency Optimization.

Multi-tier semantic caching following enterprise patterns:
- L1: Response Cache (full answers, TTL 2h)
- L2: Retrieval Cache (document sets, TTL 30min)  
- L3: Embedding Cache (query vectors, TTL 1h)

References:
- Google RAGCache
- HuggingFace Semantic Cache
- Microsoft Foundry IQ

Feature: semantic-cache
"""

from app.cache.models import CacheEntry, CacheConfig, CacheTier
from app.cache.semantic_cache import SemanticResponseCache, get_semantic_cache
from app.cache.cache_manager import CacheManager, get_cache_manager
from app.cache.invalidation import CacheInvalidationManager, get_invalidation_manager

__all__ = [
    "CacheEntry",
    "CacheConfig", 
    "CacheTier",
    "SemanticResponseCache",
    "get_semantic_cache",
    "CacheManager",
    "get_cache_manager",
    "CacheInvalidationManager",
    "get_invalidation_manager",
]
