"""
Dense Search Repository for Hybrid Search.

Uses pgvector for vector similarity search with Gemini embeddings.

Feature: hybrid-search
Requirements: 2.1, 2.5, 6.1, 6.2, 6.3

**SINGLETON PATTERN**: Only ONE instance to avoid exceeding Supabase connection limits.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

# =============================================================================
# SINGLETON INSTANCE
# =============================================================================
_dense_search_instance: Optional["DenseSearchRepository"] = None


def get_dense_search_repository() -> "DenseSearchRepository":
    """
    Get singleton DenseSearchRepository instance.
    
    This ensures only ONE asyncpg connection pool is created,
    avoiding Supabase Free Tier connection limit issues.
    """
    global _dense_search_instance
    
    if _dense_search_instance is None:
        _dense_search_instance = DenseSearchRepository()
        logger.info("Created singleton DenseSearchRepository instance")
    
    return _dense_search_instance


@dataclass
class DenseSearchResult:
    """Result from dense (vector) search with semantic chunking metadata."""
    node_id: str
    similarity: float  # Cosine similarity score (0-1)
    content: str = ""  # Content from knowledge_embeddings table
    # Semantic chunking fields
    content_type: str = "text"  # text, table, heading, diagram_reference, formula
    confidence_score: float = 1.0  # 0.0-1.0
    page_number: int = 0
    chunk_index: int = 0
    image_url: str = ""
    document_id: str = ""
    section_hierarchy: dict = None  # article, clause, point, rule
    # Source highlighting (Feature: source-highlight-citation)
    bounding_boxes: list = None  # Normalized coordinates for text highlighting
    
    def __post_init__(self):
        # Ensure similarity is in valid range
        self.similarity = max(0.0, min(1.0, self.similarity))
        if self.section_hierarchy is None:
            self.section_hierarchy = {}
        if self.bounding_boxes is None:
            self.bounding_boxes = []


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
    
    def _get_asyncpg_url(self) -> str:
        """Convert SQLAlchemy URL to asyncpg URL format."""
        url = settings.database_url or ""
        # asyncpg needs postgresql:// not postgresql+asyncpg://
        url = url.replace("postgresql+asyncpg://", "postgresql://")
        url = url.replace("postgres://", "postgresql://")
        return url
    
    async def _get_pool(self):
        """Get or create connection pool (MINIMAL for Supabase Free Tier)."""
        if self._pool is None:
            try:
                import asyncpg
                db_url = self._get_asyncpg_url()
                self._pool = await asyncpg.create_pool(
                    db_url,
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
        limit: int = 10,
        content_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None
    ) -> List[DenseSearchResult]:
        """
        Search for similar documents using cosine similarity with chunking filters.
        
        Args:
            query_embedding: 768-dim normalized query vector
            limit: Maximum results to return
            content_types: Filter by content types (text, table, heading, etc.)
            min_confidence: Minimum confidence score filter
            
        Returns:
            List of DenseSearchResult sorted by similarity (descending)
            
        Requirements: 2.5, 8.1, 8.2, 8.3
        **Feature: semantic-chunking**
        """
        if not self._available:
            logger.warning("Dense search not available")
            return []
        
        try:
            pool = await self._get_pool()
            
            # Convert embedding to pgvector format
            embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            
            async with pool.acquire() as conn:
                # Build query with optional filters
                # Note: Schema uses 'id' (UUID) not 'node_id'
                # Embedding is float8[] array, compute cosine similarity manually
                query = """
                    WITH query_emb AS (
                        SELECT $1::float8[] as emb
                    )
                    SELECT 
                        id::text as node_id,
                        content,
                        content_type,
                        confidence_score,
                        page_number,
                        chunk_index,
                        image_url,
                        document_id,
                        metadata,
                        bounding_boxes,
                        (
                            SELECT SUM(a * b) / (
                                SQRT(SUM(a * a)) * SQRT(SUM(b * b))
                            )
                            FROM UNNEST(embedding, (SELECT emb FROM query_emb)) AS t(a, b)
                        ) as similarity
                    FROM knowledge_embeddings
                    WHERE embedding IS NOT NULL
                """
                # Pass embedding as Python list (asyncpg converts to float8[])
                params = [query_embedding]
                param_idx = 2
                
                # Add content type filter
                if content_types:
                    query += f" AND content_type = ANY(${param_idx})"
                    params.append(content_types)
                    param_idx += 1
                
                # Add confidence filter
                if min_confidence is not None:
                    query += f" AND confidence_score >= ${param_idx}"
                    params.append(min_confidence)
                    param_idx += 1
                
                query += f"""
                    ORDER BY similarity DESC NULLS LAST
                    LIMIT ${param_idx}
                """
                params.append(limit)
                
                rows = await conn.fetch(query, *params)
                
                results = []
                for row in rows:
                    # Parse section hierarchy from metadata
                    metadata = row.get("metadata") or {}
                    if isinstance(metadata, str):
                        import json
                        try:
                            metadata = json.loads(metadata)
                        except:
                            metadata = {}
                    
                    section_hierarchy = metadata.get("section_hierarchy", {})
                    
                    # Parse bounding_boxes from JSONB
                    bounding_boxes = row.get("bounding_boxes")
                    if isinstance(bounding_boxes, str):
                        try:
                            bounding_boxes = json.loads(bounding_boxes)
                        except:
                            bounding_boxes = []
                    elif bounding_boxes is None:
                        bounding_boxes = []
                    
                    results.append(DenseSearchResult(
                        node_id=row["node_id"],
                        similarity=float(row["similarity"]),
                        content=row["content"] or "",
                        content_type=row.get("content_type") or "text",
                        confidence_score=float(row.get("confidence_score") or 1.0),
                        page_number=row.get("page_number") or 0,
                        chunk_index=row.get("chunk_index") or 0,
                        image_url=row.get("image_url") or "",
                        document_id=row.get("document_id") or "",
                        section_hierarchy=section_hierarchy,
                        bounding_boxes=bounding_boxes
                    ))
                
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

    async def store_document_chunk(
        self,
        node_id: str,
        content: str,
        embedding: List[float],
        document_id: str,
        page_number: int,
        chunk_index: int,
        content_type: str = "text",
        confidence_score: float = 1.0,
        image_url: str = "",
        metadata: dict = None
    ) -> bool:
        """
        Store a semantic chunk with full metadata.
        
        Args:
            node_id: Unique chunk identifier
            content: Text content
            embedding: 768-dim L2-normalized vector
            document_id: Parent document ID
            page_number: Page number in document
            chunk_index: Chunk index within page
            content_type: Content type (text, table, heading, etc.)
            confidence_score: Confidence score (0.0-1.0)
            image_url: URL to source image
            metadata: Additional metadata (section_hierarchy, etc.)
            
        Returns:
            True if successful, False otherwise
            
        Requirements: 8.1, 8.2, 8.3
        **Feature: semantic-chunking**
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
            
            # Convert metadata to JSON
            import json
            metadata_json = json.dumps(metadata) if metadata else '{}'
            
            async with pool.acquire() as conn:
                # UPSERT with all chunking fields
                await conn.execute(
                    """
                    INSERT INTO knowledge_embeddings (
                        node_id, content, embedding, document_id, page_number, 
                        chunk_index, content_type, confidence_score, image_url, metadata
                    )
                    VALUES ($1, $2, $3::vector, $4, $5, $6, $7, $8, $9, $10::jsonb)
                    ON CONFLICT (node_id) 
                    DO UPDATE SET 
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        document_id = EXCLUDED.document_id,
                        page_number = EXCLUDED.page_number,
                        chunk_index = EXCLUDED.chunk_index,
                        content_type = EXCLUDED.content_type,
                        confidence_score = EXCLUDED.confidence_score,
                        image_url = EXCLUDED.image_url,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    node_id,
                    content[:2000],  # Truncate content if too long
                    embedding_str,
                    document_id,
                    page_number,
                    chunk_index,
                    content_type,
                    confidence_score,
                    image_url,
                    metadata_json
                )
                
                logger.debug(
                    f"Stored chunk: {node_id}, type={content_type}, "
                    f"confidence={confidence_score}, page={page_number}"
                )
                return True
                
        except Exception as e:
            logger.error(f"Failed to store chunk {node_id}: {e}")
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
