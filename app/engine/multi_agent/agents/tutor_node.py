"""
Tutor Agent Node - Teaching Specialist

Handles educational interactions, explanations, and quizzes.

**Integrated with agents/ framework for config and tracing.**
"""

import logging
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.multi_agent.state import AgentState
from app.engine.agents import TUTOR_AGENT_CONFIG, AgentConfig

logger = logging.getLogger(__name__)


TUTOR_PROMPT = """Bạn là Maritime Tutor - chuyên gia giảng dạy về hàng hải.

**Vai trò:** Giảng viên thân thiện, kiên nhẫn, giải thích dễ hiểu

**Phong cách:**
- Giải thích từ đơn giản đến phức tạp
- Dùng ví dụ thực tế
- Khuyến khích học viên
- Dịch thuật ngữ tiếng Anh sang tiếng Việt

**Ngữ cảnh học viên:**
{context}

**Yêu cầu:**
{query}

**Hướng dẫn:**
- Nếu là câu hỏi kiến thức: Giải thích chi tiết với ví dụ
- Nếu yêu cầu quiz: Tạo câu hỏi trắc nghiệm
- Nếu cần bài tập: Đưa bài tập và hướng dẫn

Trả lời:"""


class TutorAgentNode:
    """
    Tutor Agent - Teaching specialist.
    
    Responsibilities:
    - Explain concepts clearly
    - Create quizzes and exercises
    - Adapt to learner level
    
    Implements agents/ framework integration.
    """
    
    def __init__(self):
        """Initialize Tutor Agent."""
        self._llm = None
        self._config = TUTOR_AGENT_CONFIG
        self._init_llm()
        logger.info(f"TutorAgentNode initialized with config: {self._config.id}")
    
    def _init_llm(self):
        """Initialize teaching LLM."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model=settings.google_model,
                google_api_key=settings.google_api_key,
                temperature=0.7,  # Some creativity for teaching
                max_output_tokens=2000
            )
        except Exception as e:
            logger.error(f"Failed to initialize Tutor LLM: {e}")
            self._llm = None
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process educational request.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with tutor output
        """
        query = state.get("query", "")
        context = state.get("context", {})
        learning_context = state.get("learning_context", {})
        
        try:
            response = await self._generate_teaching(query, {**context, **learning_context})
            
            state["tutor_output"] = response
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["tutor"] = response
            state["current_agent"] = "tutor_agent"
            
            logger.info(f"[TUTOR_AGENT] Generated teaching response")
            
        except Exception as e:
            logger.error(f"[TUTOR_AGENT] Error: {e}")
            state["tutor_output"] = f"Xin lỗi, tôi gặp lỗi khi tạo bài giảng: {e}"
            state["error"] = str(e)
        
        return state
    
    async def _generate_teaching(self, query: str, context: dict) -> str:
        """Generate teaching response."""
        if not self._llm:
            return self._fallback_response(query)
        
        try:
            context_str = "\n".join([
                f"- {k}: {v}" for k, v in context.items() if v
            ]) or "Không có thông tin"
            
            messages = [
                HumanMessage(content=TUTOR_PROMPT.format(
                    query=query,
                    context=context_str
                ))
            ]
            
            response = await self._llm.ainvoke(messages)
            return response.content.strip()
            
        except Exception as e:
            logger.warning(f"Teaching generation failed: {e}")
            return self._fallback_response(query)
    
    def _fallback_response(self, query: str) -> str:
        """Fallback when LLM unavailable."""
        return f"""Tôi sẽ giúp bạn với: "{query}"

Để học hiệu quả, bạn nên:
1. Đọc quy định gốc (COLREGs, SOLAS)
2. Xem các ví dụ thực tế
3. Làm bài tập thực hành

Bạn muốn tôi giải thích khái niệm nào cụ thể?"""
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_tutor_node: Optional[TutorAgentNode] = None

def get_tutor_agent_node() -> TutorAgentNode:
    """Get or create TutorAgentNode singleton."""
    global _tutor_node
    if _tutor_node is None:
        _tutor_node = TutorAgentNode()
    return _tutor_node
