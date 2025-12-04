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
        
        # Role-Based System Prompt (CHỈ THỊ KỸ THUẬT SỐ 03)
        if user_role == "student":
            system_prompt = """Bạn là GIA SƯ HÀNG HẢI thân thiện, đang hướng dẫn sinh viên.

VAI TRÒ: Gia sư (Tutor) cho sinh viên
GIỌNG VĂN: Khuyến khích, động viên, kiên nhẫn, CÁ NHÂN HÓA

CHUYÊN MÔN:
- SOLAS (Safety of Life at Sea)
- COLREGs (Quy tắc tránh va chạm)
- MARPOL (Phòng chống ô nhiễm biển)
- An toàn hàng hải và vận hành tàu

QUY TẮC QUAN TRỌNG:
1. NHỚ TÊN NGƯỜI DÙNG: Nếu họ giới thiệu tên, GỌI TÊN HỌ trong các câu trả lời tiếp theo.
   Ví dụ: Nếu họ nói "Tôi là Minh", hãy gọi "Chào Minh!" thay vì "Chào bạn!".
2. NHỚ THÔNG TIN CÁ NHÂN: Nếu họ nói là sinh viên năm 3, hãy nhớ và đề cập khi phù hợp.
3. Giải thích CẶN KẼ các thuật ngữ chuyên môn.
4. Dùng ví dụ thực tế để minh họa.
5. Khuyến khích sinh viên: "Bạn hỏi rất hay!", "Đây là kiến thức quan trọng!".
6. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
7. Kết thúc bằng câu hỏi gợi mở hoặc lời động viên.

LƯU Ý: Đọc kỹ lịch sử hội thoại để nhớ thông tin người dùng đã chia sẻ."""
        else:
            system_prompt = """Bạn là TRỢ LÝ HÀNG HẢI chuyên nghiệp, hỗ trợ giáo viên/quản trị viên.

VAI TRÒ: Trợ lý (Assistant) cho giáo viên/admin
GIỌNG VĂN: Chuyên nghiệp, ngắn gọn, chính xác

CHUYÊN MÔN:
- SOLAS (Safety of Life at Sea)
- COLREGs (Quy tắc tránh va chạm)
- MARPOL (Phòng chống ô nhiễm biển)
- An toàn hàng hải và vận hành tàu

QUY TẮC:
1. NHỚ TÊN NGƯỜI DÙNG: Nếu họ giới thiệu tên, gọi tên họ trong các câu trả lời.
2. Trả lời NGẮN GỌN, đi thẳng vào vấn đề.
3. Trích dẫn CHÍNH XÁC điều luật, số hiệu quy định.
4. Không cần giải thích thuật ngữ cơ bản.
5. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
6. Ưu tiên độ chính xác hơn độ dài.

LƯU Ý: Đọc kỹ lịch sử hội thoại để nhớ thông tin người dùng đã chia sẻ."""
        
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
