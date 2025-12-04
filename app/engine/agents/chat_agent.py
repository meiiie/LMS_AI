"""
Chat Agent for general conversation.

This module implements the Chat Agent that handles general
conversation with users, integrating with Memory Engine.

**Feature: maritime-ai-tutor**
**Validates: Requirements 2.1, 3.3, 8.2**
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Union

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

# Google Gemini support
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    ChatGoogleGenerativeAI = None

from app.core.config import settings

logger = logging.getLogger(__name__)


# Maritime expert system prompt
MARITIME_EXPERT_PROMPT = """You are an expert maritime tutor with extensive knowledge of:
- SOLAS (Safety of Life at Sea) conventions
- COLREGs (International Regulations for Preventing Collisions at Sea)
- MARPOL (Marine Pollution) regulations
- Maritime safety procedures and best practices
- Ship operations and navigation

You communicate in a professional yet friendly manner, always prioritizing safety.
When discussing regulations, you cite specific chapters and rules when possible.
"""


@dataclass
class ChatResponse:
    """Response from Chat Agent."""
    content: str
    memory_used: bool = False
    personalization_reduced: bool = False


class ChatAgent:
    """
    Chat Agent for general maritime conversation.
    
    Personalization is handled by Semantic Memory v0.3 at ChatService level.
    
    **Validates: Requirements 2.1, 3.3, 8.2**
    """
    
    def __init__(self):
        """
        Initialize Chat Agent.
        
        Note: Personalization is handled by Semantic Memory v0.3 at ChatService level,
        not by legacy MemoriEngine.
        """
        self._system_prompt = MARITIME_EXPERT_PROMPT
        self._llm = self._init_llm()
    
    def _init_llm(self) -> Optional[Union[ChatOpenAI, "ChatGoogleGenerativeAI"]]:
        """
        Initialize LLM client.
        
        Supports multiple providers:
        - google: Google Gemini (primary, recommended)
        - openai: OpenAI GPT
        - openrouter: OpenRouter (OpenAI-compatible)
        """
        provider = getattr(settings, 'llm_provider', 'google')
        
        # Try Google Gemini first (primary)
        if provider == "google" or (not settings.openai_api_key and settings.google_api_key):
            if settings.google_api_key and GEMINI_AVAILABLE:
                try:
                    logger.info(f"Initializing Google Gemini: {settings.google_model}")
                    return ChatGoogleGenerativeAI(
                        google_api_key=settings.google_api_key,
                        model=settings.google_model,
                        temperature=0.7,
                        convert_system_message_to_human=True,  # Gemini doesn't support system messages directly
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize Google Gemini: {e}")
            elif not GEMINI_AVAILABLE:
                logger.warning("langchain-google-genai not installed, falling back to OpenAI")
        
        # Fallback to OpenAI/OpenRouter
        if not settings.openai_api_key:
            logger.warning("No LLM API key configured, using placeholder responses")
            return None
        
        try:
            llm_kwargs = {
                "api_key": settings.openai_api_key,
                "model": settings.openai_model,
                "temperature": 0.7,
            }
            if settings.openai_base_url:
                llm_kwargs["base_url"] = settings.openai_base_url
                logger.info(f"Initializing OpenRouter: {settings.openai_model}")
            else:
                logger.info(f"Initializing OpenAI: {settings.openai_model}")
            
            return ChatOpenAI(**llm_kwargs)
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return None
    
    async def process(
        self,
        message: str,
        user_id: str,
        conversation_history: Optional[List[dict]] = None,
        user_role: str = "student"
    ) -> ChatResponse:
        """
        Process a chat message.
        
        Args:
            message: User's message
            user_id: User's ID (for logging)
            conversation_history: Previous messages in conversation (from Semantic Memory v0.3)
            user_role: User role for role-based prompting (student/teacher/admin)
            
        Returns:
            ChatResponse with generated content
            
        **Validates: Requirements 2.1, 3.3, 8.2**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        
        Note: Personalization is handled by Semantic Memory v0.3 at ChatService level.
        conversation_history already contains semantic context.
        """
        # Generate response with role-based prompting
        # Memory context is already included in conversation_history from ChatService
        content = self._generate_response(
            message, 
            None,  # No legacy memory context
            conversation_history,
            user_role
        )
        
        return ChatResponse(
            content=content,
            memory_used=False,  # Legacy memory not used
            personalization_reduced=False  # Semantic Memory v0.3 handles personalization
        )

    
    def _generate_response(
        self,
        message: str,
        memory_context,  # Deprecated, kept for compatibility
        conversation_history: Optional[List[dict]],
        user_role: str = "student"
    ) -> str:
        """
        Generate response based on message and context.
        
        Uses LLM if available, otherwise returns placeholder.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        
        Note: memory_context is deprecated. Personalization is handled by Semantic Memory v0.3
        at ChatService level and passed via conversation_history.
        """
        # If no LLM, return placeholder
        if not self._llm:
            return f"As a maritime expert, I can help you with: {message}"
        
        # CHỈ THỊ KỸ THUẬT SỐ 12: System Prompt tối ưu
        if user_role == "student":
            system_prompt = """BẠN LÀ: Maritime AI Tutor - Một người bạn đồng hành am hiểu và thân thiện.

HƯỚNG DẪN ỨNG XỬ (QUAN TRỌNG):
1. GỌI TÊN: Nếu biết tên người dùng từ lịch sử hội thoại, hãy gọi tên họ một cách tự nhiên (VD: "Chào Minh", "Đúng rồi đó Hùng"). Đừng gọi "bạn" chung chung.
2. KHÔNG LẶP LẠI: Tuyệt đối KHÔNG bắt đầu mọi câu trả lời bằng "Chào bạn" hoặc "Câu hỏi hay". Hãy đi thẳng vào vấn đề hoặc dùng câu dẫn khác như "Về câu hỏi này...", "Đây là một điểm quan trọng...", "Tiếp theo...".
3. PHONG CÁCH: Dùng giọng văn ân cần, giải thích dễ hiểu, ví dụ đời thường. Khuyến khích nhưng KHÔNG lặp lại cùng một câu khen.

CHUYÊN MÔN:
- SOLAS (Safety of Life at Sea)
- COLREGs (Quy tắc tránh va chạm)
- MARPOL (Phòng chống ô nhiễm biển)
- An toàn hàng hải và vận hành tàu

NHIỆM VỤ:
- Trả lời câu hỏi dựa trên Context và Lịch sử hội thoại.
- Nếu người dùng chào hỏi/giới thiệu: Hãy ghi nhớ thông tin đó và chào lại nồng nhiệt.
- Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt."""
        else:
            system_prompt = """BẠN LÀ: Maritime AI Assistant - Trợ lý chuyên nghiệp cho giáo viên/admin.

HƯỚNG DẪN ỨNG XỬ (QUAN TRỌNG):
1. GỌI TÊN: Nếu biết tên người dùng, gọi tên họ một cách chuyên nghiệp.
2. KHÔNG LẶP LẠI: Đi thẳng vào vấn đề, không cần câu dẫn dài dòng.
3. PHONG CÁCH: Dùng giọng văn báo cáo, súc tích, chuyên nghiệp.

CHUYÊN MÔN:
- SOLAS (Safety of Life at Sea)
- COLREGs (Quy tắc tránh va chạm)
- MARPOL (Phòng chống ô nhiễm biển)
- An toàn hàng hải và vận hành tàu

NHIỆM VỤ:
- Trả lời ngắn gọn, chính xác.
- Trích dẫn điều luật, số hiệu quy định khi cần.
- Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt."""
        
        # Build messages for LLM
        messages = [SystemMessage(content=system_prompt)]
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
        
        # Add current message
        messages.append(HumanMessage(content=message))
        
        try:
            response = self._llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return f"I apologize, but I'm having trouble processing your request. Error: {str(e)}"
    
    def is_available(self) -> bool:
        """Check if Chat Agent is available."""
        return True  # Always available
