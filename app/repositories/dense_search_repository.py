"""
Dense Search Repository for Hybrid Search.

Uses pgvector for vector similarity search with Gemini embeddings.

Feature: hybrid-search
Requirements: 2.1, 2.5, 6.1, 6.2, 6.3
"""

import logging
from dataclasses import dataclass
from typing import List, Optional
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DenseSearchResult:
    """Result from dense (vector) search."""
    node_id: str
    similarity: float  # Cosine similarity score (0-1)
    content: str = ""  # Content from knowledge_embeddings table
    
    def __post_init__(self):
        # Ensure similarity is in valid range
        self.similarity = max(0.0, min(1.0, self.similarity))


class DenseSearchRepository:
    """
    Repository for vector-based semantic search using pgvector.
    
    Stores and searches 768-dimensional Gemini embeddings
    using cosine similarity.
    
    Feature: hybrid-search
    Requirements: 2.1, 2.5, 6.1, 6.2, 6.3
    """
    
    def __init__(self):
        """Initialize repository with database connection."""
        self._pool = None
        self._available = False
        self._init_pool()
    
    def _init_pool(self):
        """Initialize async connection pool."""
        try:
            import asyncpg
            # Will be initialized on first use
            self._available = True
            logger.info("DenseSearchRepository initialized")
        except ImportError:
            logger.warning("asyncpg not installed. Dense search unavailable.")
            self._available = False
    
    async def _get_pool(self):
        """Get or create connection pool (MINIMAL for Supabase Free Tier)."""
        if self._pool is None:
            try:
                import asyncpg
                self._pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=1,
                    max_size=1  # MINIMAL: Only 1 connection for async operations
                )
                logger.info("Created asyncpg connection pool (min=1, max=1)")
            except Exception as e:
                logger.error(f"Failed to create connection pool: {e}")
                self._available = False
                raise
        return self._pool
    
    def is_available(self) -> bool:
        """Check if dense search is available."""
        return self._available
    
    async def search(
        self,
        query_embedding: List[float],
        limit: int = 10
    ) -> List[DenseSearchResult]:
        """
        Search for similar documents using cosine similarity.
        
        Args:
            query_embedding: 768-dim normalized query vector
            limit: Maximum results to return
            
        Returns:
            List of DenseSearchResult sorted by similarity (descending)
            
        Requirements: 2.5
        """
        if not self._available:
            logger.warning("Dense search not available")
            return []
        
        try:
            pool = await self._get_pool()
            
            # Convert embedding to pgvector format
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            
            async with pool.acquire() as conn:
                # Use cosine similarity (1 - cosine_distance)
                # pgvector's <=> operator returns cosine distance
                rows = await conn.fetch(
                    """
                    SELECT 
                        node_id,
                        content,
                        1 - (embedding <=> $1::vector) as similarity
                    FROM knowledge_embeddings
                    ORDER BY embedding <=> $1::vector
                    LIMIT $2
                    """,
                    embedding_str,
                    limit
                )
                
                results = [
                    DenseSearchResult(
                        node_id=row["node_id"],
                        similarity=float(row["similarity"]),
                        content=row["content"] or ""
                    )
                    for row in rows
                ]
                
                logger.info(f"Dense search returned {len(results)} results")
                return results
                
        except Exception as e:
            logger.error(f"Dense search failed: {e}")
            return []
    
    async def store_embedding(
        self,
        node_id: str,
        embedding: List[float]
    ) -> bool:
        """
        Store embedding vector for a knowledge node.
        
        Uses UPSERT to handle both insert and update cases.
        
        Args:
            node_id: Knowledge node ID from Neo4j
            embedding: 768-dim L2-normalized vector
            
        Returns:
            True if successful, False otherwise
            
        Requirements: 6.1, 6.2
        """
        if not self._available:
            logger.warning("Dense search not available for storing")
            return False
        
        if len(embedding) != 768:
            logger.error(f"Invalid embedding dimensions: {len(embedding)}, expected 768")
            return False
        
        try:
            pool = await self._get_pool()
            
            # Convert embedding to pgvector format
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            
            async with pool.acquire() as conn:
                # UPSERT: insert or update if exists
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings (node_id, embedding)
                    VALUES ($1, $2::vector)
                    ON CONFLICT (node_id) 
                    DO UPDATE SET 
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """,
                    node_id,
                    embedding_str
                )
                
                logger.debug(f"Stored embedding for node: {node_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to store embedding for {node_id}: {e}")
            return False
    
    async def upsert_embedding(
        self,
        node_id: str,
        content: str,
        embedding: List[float]
    ) -> bool:
        """
        Upsert embedding with content for a knowledge node.
        
        Args:
            node_id: Knowledge node ID from Neo4j
            content: Text content (truncated to 500 chars)
            embedding: 768-dim L2-normalized vector
            
        Returns:
            True if successful, False otherwise
            
        Requirements: 6.1, 6.2
        """
        if not self._available:
            logger.warning("Dense search not available for storing")
            return False
        
        if len(embedding) != 768:
            logger.error(f"Invalid embedding dimensions: {len(embedding)}, expected 768")
            return False
        
        try:
            pool = await self._get_pool()
            
            # Convert embedding to pgvector format
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings (node_id, content, embedding)
                    VALUES ($1, $2, $3::vector)
                    ON CONFLICT (node_id) 
                    DO UPDATE SET 
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """,
                    node_id,
                    content[:500],
                    embedding_str
                )
                
                logger.debug(f"Upserted embedding for node: {node_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to upsert embedding for {node_id}: {e}")
            return False

    async def delete_embedding(self, node_id: str) -> bool:
        """
        Delete embedding vector for a knowledge node.
        
        Args:
            node_id: Knowledge node ID to delete
            
        Returns:
            True if deleted (or didn't exist), False on error
            
        Requirements: 6.3
        """
        if not self._available:
            logger.warning("Dense search not available for deletion")
            return False
        
        try:
            pool = await self._get_pool()
            
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM knowledge_embeddings WHERE node_id = $1",
                    node_id
                )
                
                # result format: "DELETE n"
                deleted = int(result.split()[-1]) if result else 0
                logger.debug(f"Deleted {deleted} embedding(s) for node: {node_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete embedding for {node_id}: {e}")
            return False
    
    async def get_embedding(self, node_id: str) -> Optional[List[float]]:
        """
        Get embedding vector for a knowledge node.
        
        Args:
            node_id: Knowledge node ID
            
        Returns:
            Embedding vector if exists, None otherwise
        """
        if not self._available:
            return None
        
        try:
            pool = await self._get_pool()
            
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT embedding FROM knowledge_embeddings WHERE node_id = $1",
                    node_id
                )
                
                if row and row["embedding"]:
                    # pgvector returns string like "[0.1,0.2,...]"
                    embedding_str = str(row["embedding"])
                    # Parse the vector string
                    values = embedding_str.strip("[]").split(",")
                    return [float(v) for v in values]
                
                return None
                
        except Exception as e:
            logger.error(f"Failed to get embedding for {node_id}: {e}")
            return None
    
    async def count_embeddings(self) -> int:
        """Get total count of stored embeddings."""
        if not self._available:
            return 0
        
        try:
            pool = await self._get_pool()
            
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as count FROM knowledge_embeddings"
                )
                return row["count"] if row else 0
                
        except Exception as e:
            logger.error(f"Failed to count embeddings: {e}")
            return 0
    
    async def close(self):
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Closed DenseSearchRepository connection pool")
