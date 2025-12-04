"""
Semantic Memory Repository for Maritime AI Tutor v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Repository for semantic memory operations with pgvector on Supabase.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""
import json
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.semantic_memory import (
    MemoryType,
    SemanticMemory,
    SemanticMemoryCreate,
    SemanticMemorySearchResult,
)

logger = logging.getLogger(__name__)


class SemanticMemoryRepository:
    """
    Repository for semantic memory CRUD operations with pgvector.
    
    Uses Supabase PostgreSQL with pgvector extension for vector similarity search.
    Implements cosine similarity search with HNSW index.
    
    Requirements: 2.1, 2.2, 2.3, 2.4
    """
    
    TABLE_NAME = "semantic_memories"
    DEFAULT_SEARCH_LIMIT = 5
    DEFAULT_SIMILARITY_THRESHOLD = 0.7
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize repository with database connection.
        
        Args:
            database_url: PostgreSQL connection URL (defaults to settings)
        """
        self._database_url = database_url or settings.postgres_url_sync
        self._engine = None
        self._session_factory = None
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """Lazy initialization of database connection."""
        if not self._initialized:
            try:
                self._engine = create_engine(
                    self._database_url,
                    echo=settings.debug,
                    pool_pre_ping=True,
                    pool_size=3,        # Limit connections for Supabase Free Tier
                    max_overflow=0,     # No extra connections
                    pool_timeout=30,    # Wait 30s for connection
                    pool_recycle=1800   # Recycle connections after 30 minutes
                )
                self._session_factory = sessionmaker(bind=self._engine)
                self._initialized = True
                logger.info("SemanticMemoryRepository initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize SemanticMemoryRepository: {e}")
                raise
    
    def _format_embedding(self, embedding: List[float]) -> str:
        """Format embedding list as pgvector string."""
        return f"[{','.join(str(x) for x in embedding)}]"
    
    def save_memory(
        self,
        memory: SemanticMemoryCreate
    ) -> Optional[SemanticMemory]:
        """
        Save a new semantic memory to the database.
        
        Args:
            memory: SemanticMemoryCreate object with content and embedding
            
        Returns:
            Created SemanticMemory object or None on failure
            
        Requirements: 2.1
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                embedding_str = self._format_embedding(memory.embedding)
                metadata_json = json.dumps(memory.metadata)
                
                query = text(f"""
                    INSERT INTO {self.TABLE_NAME} 
                    (user_id, content, embedding, memory_type, importance, metadata, session_id)
                    VALUES 
                    (:user_id, :content, CAST(:embedding AS vector), :memory_type, :importance, CAST(:metadata AS jsonb), :session_id)
                    RETURNING id, user_id, content, memory_type, importance, metadata, session_id, created_at, updated_at
                """)
                
                result = session.execute(query, {
                    "user_id": memory.user_id,
                    "content": memory.content,
                    "embedding": embedding_str,
                    "memory_type": memory.memory_type.value,
                    "importance": memory.importance,
                    "metadata": metadata_json,
                    "session_id": memory.session_id
                })
                
                row = result.fetchone()
                session.commit()
                
                if row:
                    logger.debug(f"Saved memory {row.id} for user {memory.user_id}")
                    return SemanticMemory(
                        id=row.id,
                        user_id=row.user_id,
                        content=row.content,
                        embedding=memory.embedding,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        metadata=row.metadata or {},
                        session_id=row.session_id,
                        created_at=row.created_at,
                        updated_at=row.updated_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return None
    
    def search_similar(
        self,
        user_id: str,
        query_embedding: List[float],
        limit: int = DEFAULT_SEARCH_LIMIT,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        memory_types: Optional[List[MemoryType]] = None,
        include_all_sessions: bool = True
    ) -> List[SemanticMemorySearchResult]:
        """
        Search for similar memories using cosine similarity.
        
        Cross-session Memory Persistence (v0.2.1):
        - By default, searches across ALL sessions for the user_id
        - Uses pgvector's <=> operator for cosine distance
        - Results are ordered by similarity (descending)
        
        Args:
            user_id: User ID to filter memories
            query_embedding: Query vector (768 dimensions)
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0.0 - 1.0)
            memory_types: Optional filter by memory types
            include_all_sessions: If True (default), search across all sessions
            
        Returns:
            List of SemanticMemorySearchResult ordered by similarity
            
        Requirements: 2.2, 2.3, 2.4, 4.2
        **Feature: cross-session-memory, Property 6: Search Across All Sessions**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                embedding_str = self._format_embedding(query_embedding)
                
                # Build type filter if specified
                type_filter = ""
                params = {
                    "user_id": user_id,
                    "embedding": embedding_str,
                    "threshold": threshold,
                    "limit": limit
                }
                
                if memory_types:
                    type_values = [t.value for t in memory_types]
                    type_filter = "AND memory_type = ANY(:memory_types)"
                    params["memory_types"] = type_values
                
                # Cosine similarity = 1 - cosine distance
                # pgvector <=> returns cosine distance
                query = text(f"""
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
                      AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :threshold
                      {type_filter}
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                """)
                
                result = session.execute(query, params)
                rows = result.fetchall()
                
                memories = []
                for row in rows:
                    # Handle NaN similarity (can happen with zero vectors)
                    similarity = float(row.similarity) if row.similarity is not None else 0.0
                    import math
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
                
                logger.debug(f"Found {len(memories)} similar memories for user {user_id}")
                return memories
                
        except Exception as e:
            logger.error(f"Failed to search similar memories: {e}")
            return []
    
    def get_user_facts(
        self,
        user_id: str,
        limit: int = 20,
        deduplicate: bool = True
    ) -> List[SemanticMemorySearchResult]:
        """
        Get all user facts for personalization across ALL sessions.
        
        Cross-session Memory Persistence (v0.2.1):
        - Queries by user_id ONLY (no session_id filter)
        - Deduplicates facts by fact_type (keeps most recent)
        - Orders by importance DESC, created_at DESC
        
        Args:
            user_id: User ID
            limit: Maximum number of facts to return
            deduplicate: If True, keep only most recent fact per fact_type
            
        Returns:
            List of user facts ordered by importance and recency
            
        Requirements: 1.1, 1.2, 2.3
        **Feature: cross-session-memory**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                # Query ALL user facts for this user_id (no session_id filter)
                # This ensures cross-session persistence
                query = text(f"""
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
                    ORDER BY importance DESC, created_at DESC
                    LIMIT :limit
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "limit": limit * 3 if deduplicate else limit  # Fetch more for deduplication
                })
                
                rows = result.fetchall()
                
                facts = []
                for row in rows:
                    facts.append(SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    ))
                
                # Deduplicate by fact_type if requested
                if deduplicate and facts:
                    facts = self._deduplicate_facts(facts)
                
                # Apply final limit after deduplication
                facts = facts[:limit]
                
                logger.debug(f"Found {len(facts)} user facts for user {user_id} (deduplicate={deduplicate})")
                return facts
                
        except Exception as e:
            logger.error(f"Failed to get user facts: {e}")
            return []
    
    def _deduplicate_facts(
        self,
        facts: List[SemanticMemorySearchResult]
    ) -> List[SemanticMemorySearchResult]:
        """
        Deduplicate facts by fact_type, keeping the most recent one.
        
        For each fact_type (name, job, preference, etc.), keeps only the
        fact with the highest created_at timestamp.
        
        Args:
            facts: List of facts (already ordered by importance, created_at DESC)
            
        Returns:
            Deduplicated list of facts
            
        Requirements: 2.3
        **Feature: cross-session-memory, Property 4: Fact Deduplication by Type**
        """
        if not facts:
            return []
        
        # Group by fact_type from metadata
        seen_types: dict[str, SemanticMemorySearchResult] = {}
        
        for fact in facts:
            # Extract fact_type from metadata
            fact_type = fact.metadata.get("fact_type", "unknown")
            
            if fact_type not in seen_types:
                # First occurrence of this type - keep it (already sorted by recency)
                seen_types[fact_type] = fact
            else:
                # Compare created_at timestamps
                existing = seen_types[fact_type]
                if fact.created_at > existing.created_at:
                    seen_types[fact_type] = fact
        
        # Return deduplicated facts, maintaining importance order
        deduplicated = list(seen_types.values())
        deduplicated.sort(key=lambda f: (f.importance, f.created_at), reverse=True)
        
        logger.debug(f"Deduplicated {len(facts)} facts to {len(deduplicated)} unique types")
        return deduplicated
    
    def get_by_id(
        self,
        memory_id: UUID,
        user_id: str
    ) -> Optional[SemanticMemory]:
        """
        Get a specific memory by ID.
        
        Args:
            memory_id: Memory UUID
            user_id: User ID (for RLS verification)
            
        Returns:
            SemanticMemory or None if not found
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    SELECT 
                        id, user_id, content, memory_type, importance, 
                        metadata, session_id, created_at, updated_at
                    FROM {self.TABLE_NAME}
                    WHERE id = :memory_id AND user_id = :user_id
                """)
                
                result = session.execute(query, {
                    "memory_id": str(memory_id),
                    "user_id": user_id
                })
                
                row = result.fetchone()
                
                if row:
                    return SemanticMemory(
                        id=row.id,
                        user_id=row.user_id,
                        content=row.content,
                        embedding=[],  # Don't fetch embedding for simple get
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        metadata=row.metadata or {},
                        session_id=row.session_id,
                        created_at=row.created_at,
                        updated_at=row.updated_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to get memory by ID: {e}")
            return None
    
    def delete_by_session(
        self,
        user_id: str,
        session_id: str
    ) -> int:
        """
        Delete all memories for a session (used after summarization).
        
        Args:
            user_id: User ID
            session_id: Session ID
            
        Returns:
            Number of deleted memories
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id 
                      AND session_id = :session_id
                      AND memory_type = :memory_type
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "session_id": session_id,
                    "memory_type": MemoryType.MESSAGE.value
                })
                
                deleted = len(result.fetchall())
                session.commit()
                
                logger.info(f"Deleted {deleted} messages for session {session_id}")
                return deleted
                
        except Exception as e:
            logger.error(f"Failed to delete session memories: {e}")
            return 0
    
    def count_user_memories(
        self,
        user_id: str,
        memory_type: Optional[MemoryType] = None
    ) -> int:
        """
        Count memories for a user.
        
        Args:
            user_id: User ID
            memory_type: Optional filter by type
            
        Returns:
            Count of memories
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                type_filter = ""
                params = {"user_id": user_id}
                
                if memory_type:
                    type_filter = "AND memory_type = :memory_type"
                    params["memory_type"] = memory_type.value
                
                query = text(f"""
                    SELECT COUNT(*) as count
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id {type_filter}
                """)
                
                result = session.execute(query, params)
                row = result.fetchone()
                
                return row.count if row else 0
                
        except Exception as e:
            logger.error(f"Failed to count memories: {e}")
            return 0
    
    def is_available(self) -> bool:
        """
        Check if the repository is available and connected.
        
        Returns:
            True if database is accessible
        """
        try:
            self._ensure_initialized()
            with self._session_factory() as session:
                session.execute(text("SELECT 1"))
                return True
        except Exception as e:
            logger.warning(f"SemanticMemoryRepository not available: {e}")
            return False


# Factory function
def get_semantic_memory_repository() -> SemanticMemoryRepository:
    """Get a configured SemanticMemoryRepository instance."""
    return SemanticMemoryRepository()
