"""
RAG Agent Node - Knowledge Retrieval Specialist

Uses Corrective RAG for intelligent document retrieval and generation.

**Integrated with agents/ framework for config and tracing.**
"""

import logging
from typing import Optional

from app.engine.multi_agent.state import AgentState
from app.engine.agentic_rag.corrective_rag import CorrectiveRAG, get_corrective_rag
from app.engine.agents import RAG_AGENT_CONFIG, AgentConfig

logger = logging.getLogger(__name__)


class RAGAgentNode:
    """
    RAG Agent - Knowledge retrieval specialist.
    
    Uses Corrective RAG with self-correction loop.
    
    Implements agents/ framework integration:
    - config property from RAG_AGENT_CONFIG
    - agent_id from config
    """
    
    def __init__(self, rag_agent=None):
        """
        Initialize RAG Agent Node.
        
        Args:
            rag_agent: Optional base RAG agent for retrieval
        """
        self._corrective_rag = get_corrective_rag(rag_agent)
        self._config = RAG_AGENT_CONFIG
        logger.info(f"RAGAgentNode initialized with config: {self._config.id}")
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process state through RAG pipeline.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with RAG output
        """
        query = state.get("query", "")
        context = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            **state.get("context", {})
        }
        
        try:
            # Use Corrective RAG
            result = await self._corrective_rag.process(query, context)
            
            # Update state
            state["rag_output"] = result.answer
            state["sources"] = result.sources
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["rag"] = result.answer
            state["current_agent"] = "rag_agent"
            
            # Add metadata
            if result.grading_result:
                state["grader_score"] = result.grading_result.avg_score
            
            # CHỈ THỊ SỐ 28: Include reasoning_trace for SOTA transparency
            if result.reasoning_trace:
                state["reasoning_trace"] = result.reasoning_trace
            
            logger.info(f"[RAG_AGENT] Processed query with confidence={result.confidence:.0f}%")
            
        except Exception as e:
            logger.error(f"[RAG_AGENT] Error: {e}")
            state["rag_output"] = f"Lỗi khi tra cứu: {e}"
            state["error"] = str(e)
        
        return state
    
    @property
    def config(self) -> AgentConfig:
        """Get agent configuration."""
        return self._config
    
    @property
    def agent_id(self) -> str:
        """Get unique agent identifier."""
        return self._config.id
    
    def is_available(self) -> bool:
        """Check if RAG is available."""
        return self._corrective_rag.is_available()


# Singleton
_rag_node: Optional[RAGAgentNode] = None

def get_rag_agent_node(rag_agent=None) -> RAGAgentNode:
    """Get or create RAGAgentNode singleton."""
    global _rag_node
    if _rag_node is None:
        _rag_node = RAGAgentNode(rag_agent)
    return _rag_node
