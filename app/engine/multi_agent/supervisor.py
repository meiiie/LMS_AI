"""
Supervisor Agent - Phase 8.2

Coordinator agent that routes queries to specialized agents.

Pattern: LangGraph Supervisor with tool-based handoffs

**Integrated with agents/ framework for config and tracing.**
"""

import logging
from typing import Optional, Dict, Any, List
from enum import Enum

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.llm_pool import get_llm_light  # SOTA: Shared LLM Pool
from app.engine.multi_agent.state import AgentState
from app.engine.agents import SUPERVISOR_AGENT_CONFIG, AgentConfig

logger = logging.getLogger(__name__)


class AgentType(str, Enum):
    """Available agent types."""
    RAG = "rag_agent"
    TUTOR = "tutor_agent"
    MEMORY = "memory_agent"
    KG_BUILDER = "kg_builder"  # Feature: document-kg
    DIRECT = "direct"


ROUTING_PROMPT = """Bạn là Supervisor Agent cho hệ thống Maritime AI.

Phân tích query và quyết định agent phù hợp nhất:

**Agents:**
- RAG_AGENT: Tra cứu quy định hàng hải (COLREGs, SOLAS, MARPOL), luật, thủ tục
- TUTOR_AGENT: Yêu cầu học tập, giải thích chi tiết, làm quiz, bài tập
- MEMORY_AGENT: Câu hỏi về ngữ cảnh cá nhân, lịch sử học, preferences
- DIRECT: Chào hỏi đơn giản, câu hỏi không liên quan đến hàng hải

**Query:** {query}

**User Context:** {context}

**Quyết định (chỉ trả về một trong: RAG_AGENT, TUTOR_AGENT, MEMORY_AGENT, DIRECT):**"""


SYNTHESIS_PROMPT = """Tổng hợp các outputs từ agents thành câu trả lời cuối cùng:

Query gốc: {query}

Outputs:
{outputs}

Tạo câu trả lời tự nhiên, mạch lạc:"""


class SupervisorAgent:
    """
    Supervisor Agent - Coordinates specialized agents.
    
    Implements agents/ framework integration.
    
    Responsibilities:
    - Analyze query intent
    - Route to appropriate agent
    - Synthesize final response
    - Quality control
    """
    
    def __init__(self):
        """Initialize Supervisor Agent."""
        self._llm = None
        self._init_llm()
        logger.info("SupervisorAgent initialized")
    
    def _init_llm(self):
        """Initialize LLM from shared pool for routing decisions."""
        try:
            # SOTA: Use shared LLM from pool (memory optimized)
            self._llm = get_llm_light()
            logger.info(f"SupervisorAgent initialized with shared LIGHT tier LLM")
        except Exception as e:
            logger.error(f"Failed to initialize Supervisor LLM: {e}")
            self._llm = None
    
    async def route(self, state: AgentState) -> str:
        """
        Determine which agent should handle the query.
        
        Args:
            state: Current agent state
            
        Returns:
            Agent name to route to
        """
        query = state.get("query", "")
        context = state.get("context", {})
        
        if not self._llm:
            return self._rule_based_route(query)
        
        try:
            messages = [
                SystemMessage(content="You are a query router. Return only the agent name."),
                HumanMessage(content=ROUTING_PROMPT.format(
                    query=query,
                    context=str(context)[:500]
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            decision = text_content.strip().upper()
            
            # Parse response
            if "RAG" in decision:
                return AgentType.RAG.value
            elif "TUTOR" in decision:
                return AgentType.TUTOR.value
            elif "MEMORY" in decision:
                return AgentType.MEMORY.value
            else:
                return AgentType.DIRECT.value
                
        except Exception as e:
            logger.warning(f"LLM routing failed: {e}")
            return self._rule_based_route(query)
    
    def _rule_based_route(self, query: str) -> str:
        """Fallback rule-based routing."""
        query_lower = query.lower()
        
        # Check for maritime keywords → RAG
        maritime_keywords = [
            "colregs", "solas", "marpol", "điều", "rule", 
            "quy tắc", "quy định", "tàu", "thuyền", "hàng hải"
        ]
        for kw in maritime_keywords:
            if kw in query_lower:
                return AgentType.RAG.value
        
        # Check for learning keywords → TUTOR
        learning_keywords = [
            "giải thích", "explain", "học", "learn", "quiz",
            "bài tập", "exercise", "ví dụ", "example"
        ]
        for kw in learning_keywords:
            if kw in query_lower:
                return AgentType.TUTOR.value
        
        # Check for personal keywords → MEMORY
        personal_keywords = [
            "tôi", "tên tôi", "my name", "nhớ", "remember",
            "lần trước", "last time", "history"
        ]
        for kw in personal_keywords:
            if kw in query_lower:
                return AgentType.MEMORY.value
        
        # Default to RAG for most queries
        if len(query) > 20:
            return AgentType.RAG.value
        
        return AgentType.DIRECT.value
    
    async def synthesize(self, state: AgentState) -> str:
        """
        Synthesize final response from agent outputs.
        
        Args:
            state: State with agent outputs
            
        Returns:
            Final synthesized response
        """
        outputs = state.get("agent_outputs", {})
        
        # If only one output, return it directly
        if len(outputs) == 1:
            return list(outputs.values())[0]
        
        # If no outputs, return error
        if not outputs:
            return "Xin lỗi, tôi không thể xử lý yêu cầu này."
        
        # Synthesize multiple outputs
        if not self._llm:
            # Simple concatenation
            return "\n\n".join(outputs.values())
        
        try:
            output_text = "\n---\n".join([
                f"[{k}]: {v}" for k, v in outputs.items()
            ])
            
            messages = [
                HumanMessage(content=SYNTHESIS_PROMPT.format(
                    query=state.get("query", ""),
                    outputs=output_text
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            
            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            from app.services.output_processor import extract_thinking_from_response
            text_content, _ = extract_thinking_from_response(response.content)
            return text_content.strip()
            
        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            return list(outputs.values())[0]  # Return first output
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process state as supervisor node.
        
        Args:
            state: Current state
            
        Returns:
            Updated state with routing decision
        """
        # Route to appropriate agent
        next_agent = await self.route(state)
        
        state["next_agent"] = next_agent
        state["current_agent"] = "supervisor"
        
        logger.info(f"[SUPERVISOR] Routing to: {next_agent}")
        
        return state
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_supervisor: Optional[SupervisorAgent] = None

def get_supervisor_agent() -> SupervisorAgent:
    """Get or create SupervisorAgent singleton."""
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor
