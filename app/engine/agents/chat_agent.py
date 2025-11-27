"""
Chat Agent for general conversation.

This module implements the Chat Agent that handles general
conversation with users, integrating with Memory Engine.

**Feature: maritime-ai-tutor**
**Validates: Requirements 2.1, 3.3, 8.2**
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.core.config import settings
from app.engine.memory import MemoriEngine
from app.models.memory import Memory, MemoryContext, MemoryType

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
    
    Integrates with Memory Engine for personalized responses.
    
    **Validates: Requirements 2.1, 3.3, 8.2**
    """
    
    def __init__(
        self,
        memory_engine: Optional[MemoriEngine] = None
    ):
        """
        Initialize Chat Agent.
        
        Args:
            memory_engine: Memory engine for personalization
        """
        self._memory = memory_engine
        self._system_prompt = MARITIME_EXPERT_PROMPT
        self._llm = self._init_llm()
    
    def _init_llm(self) -> Optional[ChatOpenAI]:
        """Initialize LLM client."""
        if not settings.openai_api_key:
            logger.warning("No OpenAI API key configured, using placeholder responses")
            return None
        
        try:
            llm_kwargs = {
                "api_key": settings.openai_api_key,
                "model": settings.openai_model,
                "temperature": 0.7,
            }
            if settings.openai_base_url:
                llm_kwargs["base_url"] = settings.openai_base_url
            
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
            user_id: User's ID for memory retrieval
            conversation_history: Previous messages in conversation
            user_role: User role for role-based prompting (student/teacher/admin)
            
        Returns:
            ChatResponse with generated content
            
        **Validates: Requirements 2.1, 3.3, 8.2**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        """
        memory_context = None
        memory_used = False
        personalization_reduced = False
        
        # Try to get memory context
        if self._memory and self._memory.is_available():
            try:
                namespace = await self._memory.create_namespace(user_id)
                memory_context = await self._memory.get_memory_context(
                    namespace, 
                    message
                )
                memory_used = True
            except Exception as e:
                logger.warning(f"Memory retrieval failed: {e}")
                personalization_reduced = True
        else:
            personalization_reduced = True
            logger.info("Memory unavailable, proceeding without personalization")
        
        # Generate response with role-based prompting
        content = self._generate_response(
            message, 
            memory_context, 
            conversation_history,
            user_role
        )
        
        # Store interaction in memory
        if self._memory and memory_used:
            await self._store_interaction(user_id, message, content)
        
        return ChatResponse(
            content=content,
            memory_used=memory_used,
            personalization_reduced=personalization_reduced
        )

    
    def _generate_response(
        self,
        message: str,
        memory_context: Optional[MemoryContext],
        conversation_history: Optional[List[dict]],
        user_role: str = "student"
    ) -> str:
        """
        Generate response based on message and context.
        
        Uses LLM if available, otherwise returns placeholder.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        """
        # Build context from memory
        context_parts = []
        
        if memory_context and memory_context.summary:
            context_parts.append(f"Previous context: {memory_context.summary}")
        
        if memory_context and memory_context.memories:
            relevant = memory_context.memories[:3]
            for mem in relevant:
                context_parts.append(f"- {mem.content[:100]}")
        
        # If no LLM, return placeholder
        if not self._llm:
            response = f"As a maritime expert, I can help you with: {message}"
            if context_parts:
                response += "\n\nBased on our previous conversations, I remember:\n"
                response += "\n".join(context_parts)
            return response
        
        # Role-Based System Prompt (CHỈ THỊ KỸ THUẬT SỐ 03)
        if user_role == "student":
            system_prompt = """Bạn là GIA SƯ HÀNG HẢI thân thiện, đang hướng dẫn sinh viên.

VAI TRÒ: Gia sư (Tutor) cho sinh viên
GIỌNG VĂN: Khuyến khích, động viên, kiên nhẫn

CHUYÊN MÔN:
- SOLAS (Safety of Life at Sea)
- COLREGs (Quy tắc tránh va chạm)
- MARPOL (Phòng chống ô nhiễm biển)
- An toàn hàng hải và vận hành tàu

QUY TẮC:
1. Giải thích CẶN KẼ các thuật ngữ chuyên môn.
2. Dùng ví dụ thực tế để minh họa.
3. Khuyến khích sinh viên: "Bạn hỏi rất hay!", "Đây là kiến thức quan trọng!".
4. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
5. Kết thúc bằng câu hỏi gợi mở hoặc lời động viên."""
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
1. Trả lời NGẮN GỌN, đi thẳng vào vấn đề.
2. Trích dẫn CHÍNH XÁC điều luật, số hiệu quy định.
3. Không cần giải thích thuật ngữ cơ bản.
4. Trả lời bằng tiếng Việt nếu câu hỏi bằng tiếng Việt.
5. Ưu tiên độ chính xác hơn độ dài."""
        
        # Build messages for LLM
        messages = [SystemMessage(content=system_prompt)]
        
        # Add memory context to system message
        if context_parts:
            memory_info = "\n\nRelevant context from previous conversations:\n" + "\n".join(context_parts)
            messages[0] = SystemMessage(content=system_prompt + memory_info)
        
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
    
    async def _store_interaction(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str
    ) -> None:
        """Store the interaction in memory."""
        if not self._memory:
            return
        
        try:
            namespace = await self._memory.create_namespace(user_id)
            
            # Store as episodic memory
            memory = Memory(
                namespace=namespace,
                memory_type=MemoryType.EPISODIC,
                content=f"User asked: {user_message[:200]}. Assistant responded about maritime topics.",
                entities=[]
            )
            await self._memory.store_memory(namespace, memory)
        except Exception as e:
            logger.warning(f"Failed to store interaction: {e}")
    
    def is_available(self) -> bool:
        """Check if Chat Agent is available."""
        return True  # Always available, memory is optional
    
    def has_memory(self) -> bool:
        """Check if memory is available."""
        return self._memory is not None and self._memory.is_available()
