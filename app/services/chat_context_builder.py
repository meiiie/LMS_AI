"""
Chat Context Builder - Memory and Context Operations

Extracts context building logic from ChatService for cleaner code organization.

**Validates: Requirements 2.1, 2.2, 2.3**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 06 - Semantic Memory v0.3**
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.engine.semantic_memory.core import SemanticMemoryEngine
    from app.services.learning_graph_service import LearningGraphService

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """Result of context building operation."""
    semantic_context: str = ""
    conversation_history: str = ""
    user_name: Optional[str] = None
    insights_count: int = 0
    facts_count: int = 0
    memories_count: int = 0


class ChatContextBuilder:
    """
    Builds context for chat processing.
    
    Handles:
    - Semantic memory retrieval (insights, facts, memories)
    - Learning graph context
    - Conversation history formatting
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    def __init__(
        self,
        semantic_memory: Optional["SemanticMemoryEngine"] = None,
        learning_graph: Optional["LearningGraphService"] = None
    ):
        """Initialize with optional memory engines."""
        self._semantic_memory = semantic_memory
        self._learning_graph = learning_graph
    
    async def build_context(
        self,
        user_id: str,
        message: str,
        insight_limit: int = 10,
        search_limit: int = 5,
        similarity_threshold: float = None
    ) -> ContextResult:
        """
        Build full context for a chat message.
        
        Args:
            user_id: User identifier
            message: Current user message
            insight_limit: Max insights to retrieve
            search_limit: Max memories to search
            similarity_threshold: Min similarity for memories
            
        Returns:
            ContextResult with semantic context and metadata
        """
        # Use settings default if not provided
        if similarity_threshold is None:
            similarity_threshold = settings.similarity_threshold
        
        result = ContextResult()
        
        # Step 1: Retrieve Semantic Memory context
        if self._semantic_memory is not None:
            try:
                result = await self._retrieve_semantic_context(
                    user_id=user_id,
                    message=message,
                    insight_limit=insight_limit,
                    search_limit=search_limit,
                    similarity_threshold=similarity_threshold
                )
            except Exception as e:
                logger.warning(f"Semantic memory retrieval failed: {e}")
        
        # Step 2: Add Learning Graph context
        if self._learning_graph is not None and self._learning_graph.is_available():
            try:
                graph_context = await self._retrieve_learning_graph_context(user_id)
                if graph_context:
                    result.semantic_context = f"{result.semantic_context}\n\n{graph_context}".strip() if result.semantic_context else graph_context
            except Exception as e:
                logger.warning(f"Learning graph retrieval failed: {e}")
        
        return result
    
    async def _retrieve_semantic_context(
        self,
        user_id: str,
        message: str,
        insight_limit: int,
        search_limit: int,
        similarity_threshold: float
    ) -> ContextResult:
        """Retrieve context from semantic memory."""
        result = ContextResult()
        
        # Retrieve prioritized insights (CHỈ THỊ 23 CẢI TIẾN)
        insights = await self._semantic_memory.retrieve_insights_prioritized(
            user_id=user_id,
            query=message,
            limit=insight_limit
        )
        
        if insights:
            insight_lines = []
            for insight in insights[:5]:
                insight_lines.append(f"- [{insight.category.value}] {insight.content}")
            insights_text = "\n".join(insight_lines)
            result.semantic_context = f"=== Behavioral Insights ===\n{insights_text}"
            result.insights_count = len(insights)
            logger.info(f"[INSIGHT ENGINE] Retrieved {len(insights)} prioritized insights for user {user_id}")
        
        # Get traditional context (facts + memories)
        context = await self._semantic_memory.retrieve_context(
            user_id=user_id,
            query=message,
            search_limit=search_limit,
            similarity_threshold=similarity_threshold,
            include_user_facts=True
        )
        
        traditional_context = context.to_prompt_context()
        result.memories_count = len(context.relevant_memories)
        result.facts_count = len(context.user_facts)
        
        # Combine insights with traditional context
        if traditional_context:
            result.semantic_context = f"{result.semantic_context}\n\n{traditional_context}" if result.semantic_context else traditional_context
        
        return result
    
    async def _retrieve_learning_graph_context(self, user_id: str) -> str:
        """Retrieve context from learning graph."""
        graph_context = await self._learning_graph.get_user_learning_context(user_id)
        context_parts = []
        
        # Format learning path
        if graph_context.get("learning_path"):
            path_items = [f"- {m['title']}" for m in graph_context["learning_path"][:5]]
            context_parts.append(f"=== Learning Path ===\n" + "\n".join(path_items))
        
        # Format knowledge gaps
        if graph_context.get("knowledge_gaps"):
            gap_items = [f"- {g['topic_name']}" for g in graph_context["knowledge_gaps"][:5]]
            context_parts.append(f"=== Knowledge Gaps ===\n" + "\n".join(gap_items))
        
        if context_parts:
            logger.info(f"[LEARNING GRAPH] Added graph context for {user_id}")
            return "\n\n".join(context_parts)
        
        return ""


# Singleton instance
_context_builder: Optional[ChatContextBuilder] = None


def get_chat_context_builder(
    semantic_memory=None,
    learning_graph=None
) -> ChatContextBuilder:
    """Get or create ChatContextBuilder singleton."""
    global _context_builder
    if _context_builder is None:
        _context_builder = ChatContextBuilder(
            semantic_memory=semantic_memory,
            learning_graph=learning_graph
        )
    return _context_builder
