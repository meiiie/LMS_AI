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
    Predicate,
    SemanticMemory,
    SemanticMemoryCreate,
    SemanticMemorySearchResult,
    SemanticTriple,
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
        Initialize repository with SHARED database connection.
        
        Args:
            database_url: Ignored - uses shared engine for connection pooling
        """
        self._engine = None
        self._session_factory = None
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """Lazy initialization using SHARED database engine."""
        if not self._initialized:
            try:
                # Use SHARED engine to minimize connections (Supabase Free Tier)
                from app.core.database import get_shared_engine, get_shared_session_factory
                
                self._engine = get_shared_engine()
                self._session_factory = get_shared_session_factory()
                self._initialized = True
                logger.info("SemanticMemoryRepository using SHARED database engine")
            except Exception as e:
                logger.error(f"Failed to initialize SemanticMemoryRepository: {e}")
                raise
    
    def _format_embedding(self, embedding: List[float]) -> str:
        """Format embedding list as pgvector string."""
        if embedding is None or len(embedding) == 0:
            # Return empty vector array - pgvector will handle as null or empty
            logger.warning("Received None or empty embedding, using empty vector")
            return "[]"
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
    
    # ========== Semantic Triples v1 (MemoriLabs Pattern) ==========
    
    def save_triple(
        self,
        triple: SemanticTriple,
        generate_embedding: bool = True
    ) -> Optional[SemanticMemory]:
        """
        Save a Semantic Triple to database.
        
        Converts triple to SemanticMemoryCreate format for storage.
        
        Args:
            triple: SemanticTriple to save
            generate_embedding: If True and no embedding, generate one
            
        Returns:
            Created SemanticMemory or None on failure
            
        Feature: semantic-triples-v1
        """
        self._ensure_initialized()
        
        try:
            # If no embedding, try to generate one
            embedding = triple.embedding
            if not embedding and generate_embedding:
                try:
                    from app.engine.semantic_memory.embeddings import get_embedding_generator
                    generator = get_embedding_generator()
                    if generator.is_available():
                        embedding = generator.generate(triple.object)
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for triple: {e}")
                    embedding = []
            
            # Convert triple to SemanticMemoryCreate
            memory = SemanticMemoryCreate(
                user_id=triple.subject,
                content=triple.to_content(),
                embedding=embedding,
                memory_type=MemoryType.USER_FACT,
                importance=triple.confidence,
                metadata=triple.to_metadata(),
                session_id=None  # Triples are cross-session
            )
            
            return self.save_memory(memory)
            
        except Exception as e:
            logger.error(f"Failed to save triple: {e}")
            return None
    
    def find_by_predicate(
        self,
        user_id: str,
        predicate: Predicate
    ) -> Optional[SemanticMemorySearchResult]:
        """
        Find existing triple by user_id and predicate.
        
        Used for upsert logic - check if triple with same predicate exists.
        
        Args:
            user_id: User ID (subject)
            predicate: Predicate type
            
        Returns:
            SemanticMemorySearchResult or None if not found
            
        Feature: semantic-triples-v1
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
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
                      AND (
                          metadata->>'predicate' = :predicate
                          OR metadata->>'fact_type' = :fact_type
                      )
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                
                # Map predicate to fact_type for backward compatibility
                fact_type_map = {
                    Predicate.HAS_NAME: "name",
                    Predicate.HAS_ROLE: "role",
                    Predicate.HAS_LEVEL: "level",
                    Predicate.HAS_GOAL: "goal",
                    Predicate.PREFERS: "preference",
                    Predicate.WEAK_AT: "weakness",
                }
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "predicate": predicate.value,
                    "fact_type": fact_type_map.get(predicate, predicate.value)
                })
                
                row = result.fetchone()
                
                if row:
                    return SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to find by predicate: {e}")
            return None
    
    def upsert_triple(
        self,
        triple: SemanticTriple
    ) -> Optional[SemanticMemory]:
        """
        Upsert a Semantic Triple (insert or update if exists).
        
        Logic:
        1. Find existing triple by predicate
        2. If exists: update content and metadata
        3. If not exists: insert new triple
        
        Args:
            triple: SemanticTriple to upsert
            
        Returns:
            Created/Updated SemanticMemory or None on failure
            
        Feature: semantic-triples-v1
        """
        existing = self.find_by_predicate(triple.subject, triple.predicate)
        
        if existing:
            # Update existing
            return self.update_memory_content(
                memory_id=existing.id,
                user_id=triple.subject,
                new_content=triple.to_content(),
                new_metadata=triple.to_metadata()
            )
        else:
            # Insert new
            return self.save_triple(triple, generate_embedding=True)
    
    # ========== v0.4 Methods (CHỈ THỊ 23) ==========
    
    def find_fact_by_type(
        self,
        user_id: str,
        fact_type: str
    ) -> Optional[SemanticMemorySearchResult]:
        """
        Find existing fact by user_id and fact_type.
        
        Used for upsert logic - check if fact of same type exists.
        
        Args:
            user_id: User ID
            fact_type: Type of fact (name, role, level, etc.)
            
        Returns:
            SemanticMemorySearchResult or None if not found
            
        **Validates: Requirements 2.1, 2.2**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
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
                      AND metadata->>'fact_type' = :fact_type
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "fact_type": fact_type
                })
                
                row = result.fetchone()
                
                if row:
                    return SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to find fact by type: {e}")
            return None
    
    def find_similar_fact_by_embedding(
        self,
        user_id: str,
        embedding: List[float],
        similarity_threshold: float = 0.90,
        memory_type: MemoryType = MemoryType.USER_FACT
    ) -> Optional[SemanticMemorySearchResult]:
        """
        SOTA: Find semantically similar fact using embedding cosine similarity.
        
        This enables detecting duplicate facts even when fact_type differs
        but content is semantically the same.
        
        Args:
            user_id: User ID
            embedding: Query embedding vector
            similarity_threshold: Minimum similarity (default: 0.90 for facts)
            memory_type: Type of memory to search
            
        Returns:
            SemanticMemorySearchResult if found, None otherwise
            
        **SOTA Enhancement: Semantic duplicate detection**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
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
                      AND memory_type = :memory_type
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT 1
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": memory_type.value,
                    "embedding": str(embedding)
                })
                
                row = result.fetchone()
                
                if row and row.similarity >= similarity_threshold:
                    logger.debug(
                        f"Found similar fact with similarity {row.similarity:.3f} "
                        f"(threshold: {similarity_threshold})"
                    )
                    return SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type),
                        importance=row.importance,
                        similarity=row.similarity,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    )
                return None
                
        except Exception as e:
            logger.error(f"Failed to find similar fact by embedding: {e}")
            return None
    
    def update_fact(
        self,
        fact_id: UUID,
        content: str,
        embedding: List[float],
        metadata: dict
    ) -> bool:
        """
        Full update of fact content, embedding, and metadata.
        
        SOTA Pattern: Explicit API - requires all fields for full update.
        For metadata-only updates (preserving embedding), use update_metadata_only().
        
        Args:
            fact_id: UUID of the fact to update
            content: New content (required)
            embedding: New embedding vector (REQUIRED, must be non-empty)
            metadata: New metadata (required)
            
        Returns:
            True if update successful
            
        Raises:
            ValueError: If embedding is None or empty
            
        **Validates: Requirements 2.2, 2.4**
        """
        # SOTA: Explicit validation - fail fast with clear error
        if embedding is None or len(embedding) == 0:
            raise ValueError(
                "embedding is required for update_fact(). "
                "Use update_metadata_only() for metadata-only updates."
            )
        
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                embedding_str = self._format_embedding(embedding)
                metadata_json = json.dumps(metadata)
                
                query = text(f"""
                    UPDATE {self.TABLE_NAME}
                    SET content = :content,
                        embedding = CAST(:embedding AS vector),
                        metadata = CAST(:metadata AS jsonb),
                        updated_at = NOW()
                    WHERE id = :fact_id
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "fact_id": str(fact_id),
                    "content": content,
                    "embedding": embedding_str,
                    "metadata": metadata_json
                })
                
                row = result.fetchone()
                session.commit()
                
                if row:
                    logger.debug(f"Updated fact {fact_id}")
                    return True
                return False
                
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Failed to update fact: {e}")
            return False
    
    def update_metadata_only(
        self,
        fact_id: UUID,
        metadata: dict
    ) -> bool:
        """
        Update ONLY metadata, preserving content and embedding.
        
        SOTA Pattern: Explicit API for partial updates.
        Use this when merging insights or updating confidence without
        re-generating embeddings.
        
        Args:
            fact_id: UUID of the fact to update
            metadata: New metadata to set (will replace existing metadata)
            
        Returns:
            True if update successful
            
        **Feature: SOTA-explicit-api**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                metadata_json = json.dumps(metadata)
                
                query = text(f"""
                    UPDATE {self.TABLE_NAME}
                    SET metadata = CAST(:metadata AS jsonb),
                        updated_at = NOW()
                    WHERE id = :fact_id
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "fact_id": str(fact_id),
                    "metadata": metadata_json
                })
                
                row = result.fetchone()
                session.commit()
                
                if row:
                    logger.debug(f"Updated metadata for fact {fact_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to update metadata: {e}")
            return False
    
    def delete_oldest_facts(
        self,
        user_id: str,
        count: int
    ) -> int:
        """
        Delete N oldest USER_FACT entries for user (FIFO eviction).
        
        Used for memory capping - when user exceeds MAX_USER_FACTS.
        
        Args:
            user_id: User ID
            count: Number of oldest facts to delete
            
        Returns:
            Number of facts actually deleted
            
        **Validates: Requirements 1.2**
        """
        self._ensure_initialized()
        
        if count <= 0:
            return 0
        
        try:
            with self._session_factory() as session:
                # Delete oldest facts using subquery
                query = text(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE id IN (
                        SELECT id FROM {self.TABLE_NAME}
                        WHERE user_id = :user_id
                          AND memory_type = :memory_type
                        ORDER BY created_at ASC
                        LIMIT :count
                    )
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value,
                    "count": count
                })
                
                deleted_ids = result.fetchall()
                session.commit()
                
                deleted_count = len(deleted_ids)
                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} oldest facts for user {user_id} (FIFO eviction)")
                
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to delete oldest facts: {e}")
            return 0
    
    def get_all_user_facts(
        self,
        user_id: str
    ) -> List[SemanticMemorySearchResult]:
        """
        Get all facts for user (for API endpoint).
        
        Returns all USER_FACT entries without deduplication.
        
        Args:
            user_id: User ID
            
        Returns:
            List of all user facts ordered by created_at DESC
            
        **Validates: Requirements 3.1**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
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
                    ORDER BY created_at DESC
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.USER_FACT.value
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
                
                logger.debug(f"Retrieved {len(facts)} total facts for user {user_id}")
                return facts
                
        except Exception as e:
            logger.error(f"Failed to get all user facts: {e}")
            return []

    def get_user_insights(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[SemanticMemorySearchResult]:
        """
        Get all insights for user (for API endpoint).
        
        Returns all INSIGHT type entries.
        
        Args:
            user_id: User ID
            limit: Maximum number of insights
            
        Returns:
            List of all user insights ordered by created_at DESC
            
        **Validates: Requirements 4.3, 4.4**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    SELECT 
                        id,
                        content,
                        memory_type,
                        importance,
                        metadata,
                        created_at,
                        updated_at,
                        1.0 AS similarity
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND memory_type = :memory_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.INSIGHT.value if hasattr(MemoryType, 'INSIGHT') else 'insight',
                    "limit": limit
                })
                
                rows = result.fetchall()
                
                insights = []
                for row in rows:
                    insights.append(SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType.INSIGHT if hasattr(MemoryType, 'INSIGHT') else MemoryType.USER_FACT,
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at,
                        updated_at=row.updated_at
                    ))
                
                logger.debug(f"Retrieved {len(insights)} insights for user {user_id}")
                return insights
                
        except Exception as e:
            logger.error(f"Failed to get user insights: {e}")
            return []

    # ========== v0.5 Methods (CHỈ THỊ 23 CẢI TIẾN - Insight Engine) ==========
    
    def update_last_accessed(self, memory_id: UUID) -> bool:
        """
        Update last_accessed timestamp for a memory.
        
        Args:
            memory_id: UUID of the memory
            
        Returns:
            True if update successful
            
        **Validates: Requirements 3.3**
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    UPDATE {self.TABLE_NAME}
                    SET last_accessed = NOW()
                    WHERE id = :memory_id
                    RETURNING id
                """)
                
                result = session.execute(query, {"memory_id": str(memory_id)})
                row = result.fetchone()
                session.commit()
                
                return row is not None
                
        except Exception as e:
            logger.error(f"Failed to update last_accessed: {e}")
            return False
    
    def delete_user_insights(self, user_id: str) -> int:
        """
        Delete all INSIGHT type memories for a user.
        
        Used during consolidation to replace old insights with consolidated ones.
        
        Args:
            user_id: User ID
            
        Returns:
            Number of deleted insights
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND memory_type = :memory_type
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "memory_type": MemoryType.INSIGHT.value if hasattr(MemoryType, 'INSIGHT') else 'insight'
                })
                
                deleted = len(result.fetchall())
                session.commit()
                
                logger.info(f"Deleted {deleted} insights for user {user_id}")
                return deleted
                
        except Exception as e:
            logger.error(f"Failed to delete user insights: {e}")
            return 0
    
    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """
        Delete a specific memory by ID.
        
        Args:
            user_id: User ID who owns the memory (for RLS verification)
            memory_id: UUID of the memory to delete
            
        Returns:
            True if deletion successful
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    DELETE FROM {self.TABLE_NAME}
                    WHERE id = :memory_id AND user_id = :user_id
                    RETURNING id
                """)
                
                result = session.execute(query, {
                    "memory_id": str(memory_id),
                    "user_id": user_id
                })
                row = result.fetchone()
                session.commit()
                
                return row is not None
                
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False
    
    def get_insights_by_category(
        self,
        user_id: str,
        category: str,
        limit: int = 10
    ) -> List[SemanticMemorySearchResult]:
        """
        Get insights filtered by category.
        
        Args:
            user_id: User ID
            category: Insight category (learning_style, knowledge_gap, etc.)
            limit: Maximum number of results
            
        Returns:
            List of insights for the category
        """
        self._ensure_initialized()
        
        try:
            with self._session_factory() as session:
                query = text(f"""
                    SELECT 
                        id,
                        content,
                        memory_type,
                        importance,
                        metadata,
                        created_at,
                        last_accessed,
                        1.0 AS similarity
                    FROM {self.TABLE_NAME}
                    WHERE user_id = :user_id
                      AND metadata->>'insight_category' = :category
                    ORDER BY last_accessed DESC NULLS LAST, created_at DESC
                    LIMIT :limit
                """)
                
                result = session.execute(query, {
                    "user_id": user_id,
                    "category": category,
                    "limit": limit
                })
                
                rows = result.fetchall()
                
                insights = []
                for row in rows:
                    insights.append(SemanticMemorySearchResult(
                        id=row.id,
                        content=row.content,
                        memory_type=MemoryType(row.memory_type) if row.memory_type in [m.value for m in MemoryType] else MemoryType.USER_FACT,
                        importance=row.importance,
                        similarity=1.0,
                        metadata=row.metadata or {},
                        created_at=row.created_at
                    ))
                
                return insights
                
        except Exception as e:
            logger.error(f"Failed to get insights by category: {e}")
            return []


# Factory function
def get_semantic_memory_repository() -> SemanticMemoryRepository:
    """Get a configured SemanticMemoryRepository instance."""
    return SemanticMemoryRepository()
