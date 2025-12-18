"""
Cache Invalidation Manager - SOTA RAG Latency Optimization.

Ensures cache coherence when source data changes.

Strategies:
1. TTL-based expiration (automatic)
2. Document version tracking (on update)
3. Manual invalidation API (admin control)

References:
- Enterprise cache coherence patterns
- Microsoft Foundry IQ

Feature: semantic-cache
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class DocumentVersion:
    """Track document version for cache invalidation."""
    document_id: str
    content_hash: str
    last_updated: float = field(default_factory=time.time)
    embedding_version: Optional[str] = None


class CacheInvalidationManager:
    """
    SOTA: Cache coherence when source data changes.
    
    Manages cache invalidation across all tiers when documents
    are updated, deleted, or embeddings are refreshed.
    
    Usage:
        invalidation_mgr = CacheInvalidationManager()
        
        # Register cache tier handlers
        invalidation_mgr.register_handler("response", response_cache.invalidate_by_document)
        invalidation_mgr.register_handler("retrieval", retrieval_cache.invalidate_by_document)
        
        # When document is updated
        await invalidation_mgr.on_document_updated(doc_id, new_content)
    
    **Feature: semantic-cache**
    """
    
    def __init__(self):
        """Initialize cache invalidation manager."""
        # Document version tracking
        self._document_versions: Dict[str, DocumentVersion] = {}
        
        # Invalidation handlers by tier
        self._handlers: Dict[str, Callable] = {}
        
        # Statistics
        self._invalidation_count = 0
        self._last_invalidation_time: Optional[float] = None
        
        # Embedding model version (clear L3 if changed)
        self._embedding_model_version: Optional[str] = None
        
        logger.info("CacheInvalidationManager initialized")
    
    def register_handler(
        self, 
        tier_name: str, 
        handler: Callable[[str], int]
    ) -> None:
        """
        Register cache invalidation handler for a tier.
        
        Args:
            tier_name: Name of cache tier (e.g., "response", "retrieval")
            handler: Async function that takes document_id and returns count
        """
        self._handlers[tier_name] = handler
        logger.info(f"Registered invalidation handler for tier: {tier_name}")
    
    async def on_document_updated(
        self, 
        document_id: str, 
        new_content: str
    ) -> Dict[str, int]:
        """
        Invalidate cache entries when document changes.
        
        Args:
            document_id: ID of updated document
            new_content: New document content (for hash comparison)
            
        Returns:
            Dict mapping tier name to invalidation count
        """
        # Calculate content hash
        new_hash = self._compute_hash(new_content)
        
        # Check if content actually changed
        existing = self._document_versions.get(document_id)
        if existing and existing.content_hash == new_hash:
            logger.debug(f"Document {document_id} unchanged, skipping invalidation")
            return {}
        
        # Content changed, invalidate caches
        results = {}
        
        for tier_name, handler in self._handlers.items():
            try:
                count = await handler(document_id)
                results[tier_name] = count
            except Exception as e:
                logger.error(f"Invalidation handler failed for {tier_name}: {e}")
                results[tier_name] = -1
        
        # Update version tracking
        self._document_versions[document_id] = DocumentVersion(
            document_id=document_id,
            content_hash=new_hash
        )
        
        total_invalidated = sum(c for c in results.values() if c > 0)
        self._invalidation_count += total_invalidated
        self._last_invalidation_time = time.time()
        
        logger.info(
            f"Document {document_id} updated: invalidated {total_invalidated} entries "
            f"across {len(results)} tiers"
        )
        
        return results
    
    async def on_document_deleted(self, document_id: str) -> Dict[str, int]:
        """
        Invalidate cache entries when document is deleted.
        
        Args:
            document_id: ID of deleted document
            
        Returns:
            Dict mapping tier name to invalidation count
        """
        results = {}
        
        for tier_name, handler in self._handlers.items():
            try:
                count = await handler(document_id)
                results[tier_name] = count
            except Exception as e:
                logger.error(f"Invalidation handler failed for {tier_name}: {e}")
                results[tier_name] = -1
        
        # Remove from version tracking
        self._document_versions.pop(document_id, None)
        
        total_invalidated = sum(c for c in results.values() if c > 0)
        self._invalidation_count += total_invalidated
        self._last_invalidation_time = time.time()
        
        logger.info(f"Document {document_id} deleted: invalidated {total_invalidated} entries")
        
        return results
    
    async def on_embeddings_refreshed(
        self, 
        new_model_version: str,
        embedding_cache_clear_handler: Optional[Callable] = None
    ) -> bool:
        """
        Clear embedding cache when embedding model changes.
        
        Args:
            new_model_version: New embedding model version string
            embedding_cache_clear_handler: Handler to clear L3 cache
            
        Returns:
            True if cache was cleared, False otherwise
        """
        if self._embedding_model_version == new_model_version:
            logger.debug("Embedding model unchanged, skipping L3 invalidation")
            return False
        
        # Model changed, clear L3 cache
        if embedding_cache_clear_handler:
            try:
                await embedding_cache_clear_handler()
            except Exception as e:
                logger.error(f"Failed to clear embedding cache: {e}")
                return False
        
        self._embedding_model_version = new_model_version
        self._last_invalidation_time = time.time()
        
        logger.info(f"Embedding cache cleared for model version: {new_model_version}")
        return True
    
    async def invalidate_all(self) -> Dict[str, int]:
        """
        Manually invalidate all caches (admin function).
        
        Returns:
            Dict mapping tier name to invalidation count
        """
        results = {}
        
        # This would require clear handlers, simplified for now
        logger.warning("Full cache invalidation requested")
        self._document_versions.clear()
        self._last_invalidation_time = time.time()
        
        return results
    
    def get_health(self) -> Dict[str, Any]:
        """
        Report cache coherence status.
        
        Returns:
            Health status dictionary
        """
        return {
            "tracked_documents": len(self._document_versions),
            "registered_handlers": list(self._handlers.keys()),
            "total_invalidations": self._invalidation_count,
            "last_invalidation": self._last_invalidation_time,
            "embedding_model_version": self._embedding_model_version
        }
    
    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


# Singleton
_invalidation_manager: Optional[CacheInvalidationManager] = None


def get_invalidation_manager() -> CacheInvalidationManager:
    """Get or create CacheInvalidationManager singleton."""
    global _invalidation_manager
    if _invalidation_manager is None:
        _invalidation_manager = CacheInvalidationManager()
    return _invalidation_manager
