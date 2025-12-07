"""
Context Retrieval Module for Semantic Memory
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

Handles context and insights retrieval from semantic memory.
Extracted from semantic_memory.py for better modularity.

Requirements: 2.2, 2.4, 4.3, 4.4
"""
import logging
from typing import List, Optional
from datetime import datetime

from app.models.semantic_memory import (
    InsightCategory,
    MemoryType,
    SemanticContext,
    SemanticMemorySearchResult,
    Insight,
)
from app.repositories.semantic_memory_repository import SemanticMemoryRepository
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings

logger = logging.getLogger(__name__)


class ContextRetriever:
    """
    Handles context retrieval operations for semantic memory.
    
    Responsibilities:
    - Retrieve relevant context for queries
    - Get user facts with deduplication
    - Retrieve prioritized insights
    
    Requirements: 2.2, 2.4
    """
    
    # Configuration
    DEFAULT_SEARCH_LIMIT = 5
    DEFAULT_SIMILARITY_THRESHOLD = 0.7
    DEFAULT_USER_FACTS_LIMIT = 10
    
    # Priority categories for retrieval
    PRIORITY_CATEGORIES = [InsightCategory.KNOWLEDGE_GAP, InsightCategory.LEARNING_STYLE]
    
    def __init__(
        self,
        embeddings: GeminiOptimizedEmbeddings,
        repository: SemanticMemoryRepository
    ):
        """
        Initialize ContextRetriever.
        
        Args:
            embeddings: GeminiOptimizedEmbeddings instance
            repository: SemanticMemoryRepository instance
        """
        self._embeddings = embeddings
        self._repository = repository
        logger.debug("ContextRetriever initialized")
    
    async def retrieve_context(
        self,
        user_id: str,
        query: str,
        search_limit: int = None,
        similarity_threshold: float = None,
        include_user_facts: bool = True,
        deduplicate_facts: bool = True
    ) -> SemanticContext:
        """
        Retrieve relevant context for a query.
        
        Cross-session Memory Persistence (v0.2.1):
        - Retrieves user facts from ALL sessions (deduplicated by fact_type)
        - Searches relevant memories across ALL sessions
        - Combines into SemanticContext for LLM prompt
        
        Args:
            user_id: User ID
            query: Query text to find similar memories
            search_limit: Maximum similar memories to return
            similarity_threshold: Minimum similarity score
            include_user_facts: Whether to include user facts
            deduplicate_facts: If True, deduplicate facts by fact_type
            
        Returns:
            SemanticContext with relevant memories and user facts
            
        Requirements: 1.1, 2.2, 2.4, 4.3
        **Feature: cross-session-memory, Property 5: Context Includes User Facts**
        """
        search_limit = search_limit or self.DEFAULT_SEARCH_LIMIT
        similarity_threshold = similarity_threshold or self.DEFAULT_SIMILARITY_THRESHOLD
        
        try:
            # Generate query embedding
            query_embedding = self._embeddings.embed_query(query)
            
            # Search for similar memories across ALL sessions (excluding user_facts)
            relevant_memories = self._repository.search_similar(
                user_id=user_id,
                query_embedding=query_embedding,
                limit=search_limit,
                threshold=similarity_threshold,
                memory_types=[MemoryType.MESSAGE, MemoryType.SUMMARY],
                include_all_sessions=True  # Cross-session search
            )
            
            # Get user facts from ALL sessions (deduplicated)
            user_facts = []
            if include_user_facts:
                user_facts = self._repository.get_user_facts(
                    user_id=user_id,
                    limit=self.DEFAULT_USER_FACTS_LIMIT,
                    deduplicate=deduplicate_facts  # Deduplicate by fact_type
                )
            
            context = SemanticContext(
                relevant_memories=relevant_memories,
                user_facts=user_facts,
                recent_messages=[],  # Will be filled by ChatService if needed
                total_tokens=self._estimate_tokens(relevant_memories, user_facts)
            )
            
            logger.debug(
                f"Retrieved context for user {user_id}: "
                f"{len(relevant_memories)} memories, {len(user_facts)} facts"
            )
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to retrieve context: {e}")
            return SemanticContext()
    
    async def retrieve_insights_prioritized(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        update_last_accessed_callback=None
    ) -> List[Insight]:
        """
        Retrieve insights with category prioritization.
        
        Prioritizes knowledge_gap and learning_style categories.
        
        Args:
            user_id: User ID
            query: Query for context
            limit: Maximum insights to return
            update_last_accessed_callback: Optional callback to update last_accessed
            
        Returns:
            List of prioritized Insight objects
            
        **Validates: Requirements 4.3, 4.4**
        """
        try:
            # Get all insights
            all_insights = await self._get_user_insights(user_id)
            
            if not all_insights:
                return []
            
            # Separate by priority
            priority_insights = []
            other_insights = []
            
            for insight in all_insights:
                if insight.category in self.PRIORITY_CATEGORIES:
                    priority_insights.append(insight)
                else:
                    other_insights.append(insight)
            
            # Sort each group by last_accessed (most recent first)
            priority_insights.sort(
                key=lambda x: x.last_accessed or x.created_at or datetime.min,
                reverse=True
            )
            other_insights.sort(
                key=lambda x: x.last_accessed or x.created_at or datetime.min,
                reverse=True
            )
            
            # Combine with priority first
            result = priority_insights + other_insights
            
            # Update last_accessed for retrieved insights
            if update_last_accessed_callback:
                for insight in result[:limit]:
                    if insight.id:
                        await update_last_accessed_callback(insight.id)
            
            return result[:limit]
            
        except Exception as e:
            logger.error(f"Failed to retrieve prioritized insights: {e}")
            return []
    
    async def _get_user_insights(self, user_id: str) -> List[Insight]:
        """Get all insights for a user."""
        try:
            # Get insight memories from repository
            insight_memories = self._repository.search_similar(
                user_id=user_id,
                query_embedding=[0.0] * 768,  # Dummy embedding
                limit=100,
                threshold=0.0,
                memory_types=[MemoryType.INSIGHT]
            )
            
            # Convert to Insight objects
            insights = []
            for mem in insight_memories:
                try:
                    insight = Insight(
                        id=mem.id,
                        user_id=user_id,
                        content=mem.content,
                        category=InsightCategory(mem.metadata.get("category", "general")),
                        confidence=mem.metadata.get("confidence", 0.5),
                        created_at=mem.created_at,
                        last_accessed=mem.metadata.get("last_accessed")
                    )
                    insights.append(insight)
                except Exception as e:
                    logger.debug(f"Skipping invalid insight: {e}")
                    continue
            
            return insights
            
        except Exception as e:
            logger.error(f"Failed to get user insights: {e}")
            return []
    
    def _estimate_tokens(
        self,
        memories: List[SemanticMemorySearchResult],
        facts: List[SemanticMemorySearchResult]
    ) -> int:
        """Estimate token count for context."""
        total_chars = sum(len(m.content) for m in memories)
        total_chars += sum(len(f.content) for f in facts)
        # Rough estimate: 1 token ≈ 4 characters for Vietnamese/English mix
        return total_chars // 4
