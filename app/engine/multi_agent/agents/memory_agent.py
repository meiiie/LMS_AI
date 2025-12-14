"""
Memory Agent Node - Context Specialist

Retrieves and manages user context and memory.

**Integrated with agents/ framework for config and tracing.**
"""

import logging
from typing import Optional

from app.engine.multi_agent.state import AgentState
from app.engine.agents import MEMORY_AGENT_CONFIG, AgentConfig

logger = logging.getLogger(__name__)


class MemoryAgentNode:
    """
    Memory Agent - User context specialist.
    
    Responsibilities:
    - Retrieve user facts and preferences
    - Inject learning history
    - Personalize responses
    
    Implements agents/ framework integration.
    """
    
    def __init__(self, semantic_memory=None, learning_graph=None):
        """
        Initialize Memory Agent.
        
        Args:
            semantic_memory: SemanticMemoryEngine instance
            learning_graph: LearningGraphService instance
        """
        self._semantic_memory = semantic_memory
        self._learning_graph = learning_graph
        self._config = MEMORY_AGENT_CONFIG
        logger.info(f"MemoryAgentNode initialized with config: {self._config.id}")
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Enrich state with user context.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with memory context
        """
        user_id = state.get("user_id", "")
        
        try:
            # Get user facts
            user_facts = await self._get_user_facts(user_id)
            
            # Get learning progress
            learning_progress = await self._get_learning_progress(user_id)
            
            # Update state
            state["user_context"] = user_facts
            state["learning_context"] = learning_progress
            state["memory_output"] = self._format_context(user_facts, learning_progress)
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["memory"] = state["memory_output"]
            state["current_agent"] = "memory_agent"
            
            logger.info(f"[MEMORY_AGENT] Retrieved context for user {user_id}")
            
        except Exception as e:
            logger.error(f"[MEMORY_AGENT] Error: {e}")
            state["memory_output"] = ""
            state["error"] = str(e)
        
        return state
    
    async def _get_user_facts(self, user_id: str) -> dict:
        """Get user facts from semantic memory."""
        if not self._semantic_memory:
            return {}
        
        try:
            # Get facts about user
            facts = await self._semantic_memory.get_user_facts(user_id)
            return {
                "name": facts.get("name"),
                "role": facts.get("role"),
                "preferences": facts.get("preferences", []),
                "interests": facts.get("interests", [])
            }
        except Exception as e:
            logger.warning(f"Failed to get user facts: {e}")
            return {}
    
    async def _get_learning_progress(self, user_id: str) -> dict:
        """Get learning progress from learning graph."""
        if not self._learning_graph:
            return {}
        
        try:
            # Get studied topics
            progress = await self._learning_graph.get_user_progress(user_id)
            return {
                "studied_topics": progress.get("studied", []),
                "weak_topics": progress.get("weak_at", []),
                "recommended": progress.get("recommended", [])
            }
        except Exception as e:
            logger.warning(f"Failed to get learning progress: {e}")
            return {}
    
    def _format_context(self, user_facts: dict, learning_progress: dict) -> str:
        """Format context for other agents."""
        parts = []
        
        if user_facts.get("name"):
            parts.append(f"Tên: {user_facts['name']}")
        
        if learning_progress.get("studied_topics"):
            topics = ", ".join(learning_progress["studied_topics"][:5])
            parts.append(f"Đã học: {topics}")
        
        if learning_progress.get("weak_topics"):
            weak = ", ".join(learning_progress["weak_topics"][:3])
            parts.append(f"Cần ôn tập: {weak}")
        
        return "\n".join(parts) if parts else "Không có thông tin về user"
    
    def is_available(self) -> bool:
        """Check if memory services are available."""
        return self._semantic_memory is not None or self._learning_graph is not None


# Singleton
_memory_node: Optional[MemoryAgentNode] = None

def get_memory_agent_node(semantic_memory=None, learning_graph=None) -> MemoryAgentNode:
    """Get or create MemoryAgentNode singleton."""
    global _memory_node
    if _memory_node is None:
        _memory_node = MemoryAgentNode(semantic_memory, learning_graph)
    return _memory_node
