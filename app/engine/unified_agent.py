"""
Unified Agent - LLM-driven Orchestration (ReAct Pattern)

CHỈ THỊ KỸ THUẬT SỐ 13: KIẾN TRÚC UNIFIED AGENT (TOOL-USE ARCHITECTURE)
CHỈ THỊ KỸ THUẬT SỐ 15: NÂNG CẤP DEPENDENCIES (SOTA STACK)

Sử dụng LangGraph 0.2.x với create_react_agent để:
- Gemini 2.5 Flash tự quyết định khi nào cần gọi Tool
- Không cần IntentClassifier cứng nhắc
- ReAct pattern: Reason -> Act -> Observe -> Repeat

Architecture:
    User Message -> Gemini (Super Agent) -> Tự suy nghĩ (ReAct)
                                         -> Quyết định gọi Tool hay trả lời trực tiếp
                                         -> Response

Tools:
    - tool_maritime_search: Tra cứu luật hàng hải (RAG)
    - tool_save_user_info: Lưu thông tin user (Memory)
    - tool_get_user_info: Lấy thông tin user đã lưu

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 13, 15**
"""

import logging
import re
from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

# ============================================================================
# SYSTEM PROMPT - "Nhân cách" của Agent
# ============================================================================

SYSTEM_PROMPT = """Bạn là Maritime AI Tutor - Trợ lý ảo chuyên về Hàng hải.

NHIỆM VỤ CỦA BẠN:
1. Trả lời câu hỏi của sinh viên/giáo viên một cách tự nhiên.
2. SỬ DỤNG CÔNG CỤ (TOOLS) KHI CẦN:
   - Nếu user hỏi về kiến thức chuyên môn (luật hàng hải, quy tắc tránh va, tàu biển...) -> BẮT BUỘC gọi tool `tool_maritime_search`. ĐỪNG tự bịa ra kiến thức.
   - Nếu user giới thiệu tên/tuổi/trường/nghề -> Gọi tool `tool_save_user_info` để ghi nhớ.
   - Nếu cần biết tên user để cá nhân hóa -> Gọi tool `tool_get_user_info`.
   - Nếu user chỉ chào hỏi xã giao -> Trả lời trực tiếp, thân thiện. KHÔNG cần gọi tool.

QUY TẮC ỨNG XỬ:
- KHÔNG lặp lại "Bạn hỏi hay quá", "Câu hỏi tuyệt vời". Đi thẳng vào vấn đề.
- KHÔNG bắt đầu mọi câu bằng "Chào [tên]". Chỉ chào ở tin nhắn đầu tiên.
- Nếu biết tên user, gọi tên họ tự nhiên trong ngữ cảnh phù hợp.
- Trả lời bằng tiếng Việt nếu user dùng tiếng Việt.
- Dịch thuật ngữ tiếng Anh: starboard = mạn phải, port = mạn trái, give-way = nhường đường.

VÍ DỤ CÁCH XỬ LÝ:
- "Xin chào, tôi là Minh, sinh viên hàng hải" -> Gọi tool_save_user_info, rồi chào lại thân thiện.
- "Quy tắc 15 là gì?" -> Gọi tool_maritime_search("Quy tắc 15 COLREGs"), rồi tổng hợp trả lời.
- "Vậy tàu nào phải tránh?" -> Nhìn lịch sử chat, gọi tool_maritime_search với query đầy đủ ngữ cảnh.
- "Cảm ơn bạn" -> Trả lời trực tiếp, không cần tool."""


# ============================================================================
# TOOL DEFINITIONS (LangChain @tool decorator)
# ============================================================================

# Global references to be set during initialization
_rag_agent = None
_semantic_memory = None
_chat_history = None
_user_cache: Dict[str, Dict[str, Any]] = {}


@tool
async def tool_maritime_search(query: str) -> str:
    """
    Tra cứu các quy tắc, luật lệ hàng hải (COLREGs, SOLAS, MARPOL) hoặc thông tin kỹ thuật về tàu biển.
    CHỈ gọi khi user hỏi về kiến thức chuyên môn hàng hải.
    
    Args:
        query: Câu hỏi cần tra cứu, nên viết đầy đủ ngữ cảnh. VD: 'Quy tắc 15 COLREGs về tình huống cắt hướng'
    
    Returns:
        Kết quả tra cứu từ Knowledge Base
    """
    global _rag_agent
    
    if not _rag_agent:
        return "Lỗi: RAG Agent không khả dụng. Không thể tra cứu kiến thức."
    
    try:
        logger.info(f"[TOOL] Maritime Search: {query}")
        response = await _rag_agent.query(query, user_role="student")
        
        # Format result
        result = response.content
        if response.citations:
            sources = [f"- {c.title}" for c in response.citations[:3]]
            result += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources)
        
        return result
        
    except Exception as e:
        logger.error(f"Maritime search error: {e}")
        return f"Lỗi khi tra cứu: {str(e)}"


@tool
async def tool_save_user_info(key: str, value: str) -> str:
    """
    Lưu thông tin cá nhân của người dùng khi họ giới thiệu bản thân.
    Gọi khi user nói tên, nghề nghiệp, trường học, v.v.
    
    Args:
        key: Loại thông tin (name, role, school, year, interest)
        value: Giá trị của thông tin
    
    Returns:
        Xác nhận đã lưu
    """
    global _user_cache, _semantic_memory, _chat_history
    
    try:
        logger.info(f"[TOOL] Save User Info: {key}={value}")
        
        # Save to in-memory cache (use a default user_id for now)
        user_id = "current_user"
        if user_id not in _user_cache:
            _user_cache[user_id] = {}
        _user_cache[user_id][key] = value
        
        # Save to Semantic Memory if available
        if _semantic_memory:
            try:
                fact = f"User's {key} is {value}"
                await _semantic_memory.store_user_fact(user_id, fact)
            except Exception as e:
                logger.warning(f"Failed to save to semantic memory: {e}")
        
        return f"Đã ghi nhớ: {key} = {value}"
        
    except Exception as e:
        logger.error(f"Save user info error: {e}")
        return f"Lỗi khi lưu thông tin: {str(e)}"


@tool
async def tool_get_user_info(key: str = "all") -> str:
    """
    Lấy thông tin đã lưu về người dùng.
    Gọi khi cần biết tên hoặc thông tin user để cá nhân hóa câu trả lời.
    
    Args:
        key: Loại thông tin cần lấy (name, role, school, year, interest, all)
    
    Returns:
        Thông tin user đã lưu
    """
    global _user_cache, _semantic_memory, _chat_history
    
    try:
        logger.info(f"[TOOL] Get User Info: {key}")
        
        user_id = "current_user"
        user_data = _user_cache.get(user_id, {})
        
        # Try Semantic Memory if not in cache
        if not user_data and _semantic_memory:
            try:
                context = await _semantic_memory.retrieve_context(
                    user_id=user_id,
                    query="user information",
                    include_user_facts=True
                )
                if context.user_facts:
                    for fact in context.user_facts:
                        if "name is" in fact.lower():
                            match = re.search(r"name is (\w+)", fact, re.IGNORECASE)
                            if match:
                                user_data["name"] = match.group(1)
            except Exception as e:
                logger.warning(f"Semantic memory retrieval failed: {e}")
        
        if key == "all":
            if user_data:
                return f"Thông tin user: {user_data}"
            return "Chưa có thông tin user nào được lưu."
        else:
            value = user_data.get(key)
            if value:
                return f"{key}: {value}"
            return f"Chưa có thông tin về {key}."
            
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        return f"Lỗi khi lấy thông tin: {str(e)}"


# List of tools for the agent
TOOLS = [tool_maritime_search, tool_save_user_info, tool_get_user_info]


# ============================================================================
# UNIFIED AGENT CLASS
# ============================================================================

class UnifiedAgent:
    """
    Unified Agent using LangGraph's create_react_agent.
    
    CHỈ THỊ SỐ 13: LLM-driven orchestration (ReAct pattern)
    CHỈ THỊ SỐ 15: Sử dụng LangGraph 0.2.x với create_react_agent
    
    Instead of rule-based intent classification, Gemini decides:
    - When to call tools (RAG, Memory)
    - When to respond directly
    - How to formulate queries for tools
    """
    
    def __init__(
        self,
        rag_agent=None,
        semantic_memory=None,
        chat_history=None
    ):
        """
        Initialize Unified Agent with dependencies.
        
        Args:
            rag_agent: RAG Agent for maritime knowledge
            semantic_memory: Semantic Memory Engine
            chat_history: Chat History Repository
        """
        global _rag_agent, _semantic_memory, _chat_history
        
        # Set global references for tools
        _rag_agent = rag_agent
        _semantic_memory = semantic_memory
        _chat_history = chat_history
        
        # Initialize LLM and Agent
        self._llm = self._init_llm()
        self._agent = self._init_agent()
        
        logger.info("UnifiedAgent initialized with LangGraph ReAct pattern")
    
    def _init_llm(self):
        """Initialize Gemini LLM."""
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            if not settings.google_api_key:
                logger.warning("No Google API key, UnifiedAgent will not work")
                return None
            
            llm = ChatGoogleGenerativeAI(
                google_api_key=settings.google_api_key,
                model=settings.google_model,
                temperature=0.7,
            )
            
            logger.info(f"UnifiedAgent using Gemini: {settings.google_model}")
            return llm
            
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            return None
    
    def _init_agent(self):
        """
        Initialize ReAct Agent using LangGraph's create_react_agent.
        
        CHỈ THỊ SỐ 15: Sử dụng hàm có sẵn thay vì tự viết
        """
        if not self._llm:
            return None
        
        try:
            # Try to use LangGraph's create_react_agent (0.2.x)
            from langgraph.prebuilt import create_react_agent
            
            agent = create_react_agent(
                self._llm,
                TOOLS,
                state_modifier=SYSTEM_PROMPT
            )
            
            logger.info("✅ Using LangGraph create_react_agent (0.2.x)")
            return agent
            
        except ImportError as e:
            logger.warning(f"LangGraph 0.2.x not available: {e}")
            logger.info("Falling back to manual ReAct implementation")
            return None
        except Exception as e:
            logger.error(f"Failed to create ReAct agent: {e}")
            return None
    
    async def process(
        self,
        message: str,
        user_id: str,
        session_id: str,
        conversation_history: List[Dict] = None,
        user_role: str = "student"
    ) -> Dict[str, Any]:
        """
        Process a message using ReAct pattern.
        
        Args:
            message: User's message
            user_id: User ID
            session_id: Session ID
            conversation_history: Previous messages
            user_role: User role (student/teacher/admin)
            
        Returns:
            Dict with response content and metadata
        """
        global _user_cache
        
        # Set current user for tools
        _user_cache["current_user"] = _user_cache.get(user_id, {})
        
        if not self._llm:
            return {
                "content": "Xin lỗi, hệ thống AI đang không khả dụng.",
                "agent_type": "unified",
                "tools_used": [],
                "error": "LLM not available"
            }
        
        try:
            # Build input messages
            messages = self._build_messages(message, conversation_history)
            
            if self._agent:
                # Use LangGraph's create_react_agent
                result = await self._agent.ainvoke({"messages": messages})
                
                # Extract final response
                final_message = result.get("messages", [])[-1]
                content = final_message.content if hasattr(final_message, 'content') else str(final_message)
                
                return {
                    "content": content,
                    "agent_type": "unified",
                    "tools_used": [],  # TODO: Extract from result
                    "method": "langgraph_react"
                }
            else:
                # Fallback: Manual ReAct implementation
                return await self._manual_react(messages, user_id)
                
        except Exception as e:
            logger.error(f"UnifiedAgent error: {e}")
            return {
                "content": f"Xin lỗi, đã có lỗi xảy ra: {str(e)}",
                "agent_type": "unified",
                "tools_used": [],
                "error": str(e)
            }
    
    def _build_messages(
        self, 
        message: str, 
        conversation_history: List[Dict] = None
    ) -> List:
        """Build message list for LLM."""
        from langchain_core.messages import HumanMessage, AIMessage
        
        messages = []
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # Add current message
        messages.append(HumanMessage(content=message))
        
        return messages
    
    async def _manual_react(
        self, 
        messages: List, 
        user_id: str
    ) -> Dict[str, Any]:
        """
        Manual ReAct implementation for older LangGraph versions.
        
        This is a fallback when create_react_agent is not available.
        """
        from langchain_core.messages import AIMessage, ToolMessage
        import json
        
        tools_used = []
        max_iterations = 5
        
        # Bind tools to LLM
        llm_with_tools = self._llm.bind_tools(TOOLS)
        
        for iteration in range(max_iterations):
            logger.info(f"[Manual ReAct] Iteration {iteration + 1}")
            
            # Call LLM
            response = await llm_with_tools.ainvoke(messages)
            
            # Check for tool calls
            tool_calls = getattr(response, 'tool_calls', [])
            
            if not tool_calls:
                # No tool calls - return response
                return {
                    "content": response.content,
                    "agent_type": "unified",
                    "tools_used": tools_used,
                    "method": "manual_react",
                    "iterations": iteration + 1
                }
            
            # Execute tool calls
            messages.append(response)
            
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                
                logger.info(f"[Manual ReAct] Calling: {tool_name}({tool_args})")
                
                # Find and execute tool
                result = "Tool not found"
                for t in TOOLS:
                    if t.name == tool_name:
                        try:
                            result = await t.ainvoke(tool_args)
                        except Exception as e:
                            result = f"Error: {e}"
                        break
                
                tools_used.append({"name": tool_name, "args": tool_args})
                
                messages.append(ToolMessage(
                    content=str(result),
                    tool_call_id=tc.get("id", "")
                ))
        
        return {
            "content": "Xin lỗi, tôi gặp khó khăn khi xử lý yêu cầu này.",
            "agent_type": "unified",
            "tools_used": tools_used,
            "method": "manual_react",
            "error": "Max iterations reached"
        }
    
    def is_available(self) -> bool:
        """Check if UnifiedAgent is available."""
        return self._llm is not None


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_unified_agent: Optional[UnifiedAgent] = None


def get_unified_agent(
    rag_agent=None,
    semantic_memory=None,
    chat_history=None
) -> UnifiedAgent:
    """Get or create UnifiedAgent singleton."""
    global _unified_agent
    
    if _unified_agent is None:
        _unified_agent = UnifiedAgent(
            rag_agent=rag_agent,
            semantic_memory=semantic_memory,
            chat_history=chat_history
        )
    
    return _unified_agent
