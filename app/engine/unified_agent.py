"""
Unified Agent - LLM-driven Orchestration (ReAct Pattern)

CHỈ THỊ KỸ THUẬT SỐ 13: KIẾN TRÚC UNIFIED AGENT (TOOL-USE ARCHITECTURE)

Thay vì dùng IntentClassifier cứng nhắc (rule-based), 
chúng ta để Gemini 2.5 Flash tự quyết định khi nào cần gọi Tool.

Architecture:
    User Message -> Gemini (Super Agent) -> Tự suy nghĩ (ReAct)
                                         -> Quyết định gọi Tool hay trả lời trực tiếp
                                         -> Response

Tools:
    - tool_maritime_search: Tra cứu luật hàng hải (RAG)
    - tool_save_user_info: Lưu thông tin user (Memory)
    - tool_get_user_info: Lấy thông tin user đã lưu

**Feature: maritime-ai-tutor**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 13**
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from app.core.config import settings

logger = logging.getLogger(__name__)

# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    data: Any
    error: Optional[str] = None


class MaritimeTools:
    """
    Collection of tools that Gemini can call.
    
    Tools are functions that the LLM can invoke to:
    - Search maritime knowledge (RAG)
    - Save/retrieve user information (Memory)
    """
    
    def __init__(self, rag_agent=None, semantic_memory=None, chat_history=None):
        """
        Initialize tools with dependencies.
        
        Args:
            rag_agent: RAG Agent for maritime knowledge search
            semantic_memory: Semantic Memory Engine for user facts
            chat_history: Chat History Repository
        """
        self._rag_agent = rag_agent
        self._semantic_memory = semantic_memory
        self._chat_history = chat_history
        self._user_cache: Dict[str, Dict[str, Any]] = {}  # In-memory cache
    
    def get_tool_definitions(self) -> List[Dict]:
        """
        Get tool definitions in OpenAI function calling format.
        
        Returns:
            List of tool definitions for LLM
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "tool_maritime_search",
                    "description": "Tra cứu các quy tắc, luật lệ hàng hải (COLREGs, SOLAS, MARPOL) hoặc thông tin kỹ thuật về tàu biển. CHỈ gọi khi user hỏi về kiến thức chuyên môn hàng hải.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Câu hỏi cần tra cứu, nên viết đầy đủ ngữ cảnh. VD: 'Quy tắc 15 COLREGs về tình huống cắt hướng'"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "tool_save_user_info",
                    "description": "Lưu thông tin cá nhân của người dùng khi họ giới thiệu bản thân. Gọi khi user nói tên, nghề nghiệp, trường học, v.v.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "enum": ["name", "role", "school", "year", "interest"],
                                "description": "Loại thông tin: name (tên), role (vai trò/nghề), school (trường), year (năm học), interest (sở thích)"
                            },
                            "value": {
                                "type": "string",
                                "description": "Giá trị của thông tin"
                            }
                        },
                        "required": ["key", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "tool_get_user_info",
                    "description": "Lấy thông tin đã lưu về người dùng. Gọi khi cần biết tên hoặc thông tin user để cá nhân hóa câu trả lời.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {
                                "type": "string",
                                "enum": ["name", "role", "school", "year", "interest", "all"],
                                "description": "Loại thông tin cần lấy, hoặc 'all' để lấy tất cả"
                            }
                        },
                        "required": ["key"]
                    }
                }
            }
        ]
    
    async def execute_tool(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any],
        user_id: str,
        conversation_history: str = ""
    ) -> ToolResult:
        """
        Execute a tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            user_id: User ID for context
            conversation_history: Conversation history for RAG context
            
        Returns:
            ToolResult with execution result
        """
        try:
            if tool_name == "tool_maritime_search":
                return await self._execute_maritime_search(
                    arguments.get("query", ""),
                    conversation_history
                )
            elif tool_name == "tool_save_user_info":
                return await self._execute_save_user_info(
                    user_id,
                    arguments.get("key", ""),
                    arguments.get("value", "")
                )
            elif tool_name == "tool_get_user_info":
                return await self._execute_get_user_info(
                    user_id,
                    arguments.get("key", "all")
                )
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Unknown tool: {tool_name}"
                )
        except Exception as e:
            logger.error(f"Tool execution error: {tool_name} - {e}")
            return ToolResult(
                success=False,
                data=None,
                error=str(e)
            )
    
    async def _execute_maritime_search(
        self, 
        query: str,
        conversation_history: str = ""
    ) -> ToolResult:
        """Execute maritime knowledge search (RAG)."""
        if not self._rag_agent:
            return ToolResult(
                success=False,
                data=None,
                error="RAG Agent not available"
            )
        
        try:
            logger.info(f"[TOOL] Maritime Search: {query}")
            response = await self._rag_agent.query(
                query,
                conversation_history=conversation_history,
                user_role="student"
            )
            
            # Format result for LLM
            result = {
                "content": response.content,
                "sources": [
                    {"title": c.title, "source": c.source}
                    for c in response.citations[:3]
                ] if response.citations else [],
                "is_fallback": response.is_fallback
            }
            
            return ToolResult(success=True, data=result)
            
        except Exception as e:
            logger.error(f"Maritime search error: {e}")
            return ToolResult(success=False, data=None, error=str(e))
    
    async def _execute_save_user_info(
        self, 
        user_id: str, 
        key: str, 
        value: str
    ) -> ToolResult:
        """Save user information to memory."""
        try:
            logger.info(f"[TOOL] Save User Info: {user_id} - {key}={value}")
            
            # Save to in-memory cache
            if user_id not in self._user_cache:
                self._user_cache[user_id] = {}
            self._user_cache[user_id][key] = value
            
            # Save to Semantic Memory if available
            if self._semantic_memory:
                fact = f"User's {key} is {value}"
                await self._semantic_memory.store_user_fact(user_id, fact)
            
            # Save to Chat History if available
            if self._chat_history and key == "name":
                session = self._chat_history.get_or_create_session(user_id)
                if session:
                    self._chat_history.update_user_name(session.session_id, value)
            
            return ToolResult(
                success=True,
                data={"saved": {key: value}}
            )
            
        except Exception as e:
            logger.error(f"Save user info error: {e}")
            return ToolResult(success=False, data=None, error=str(e))
    
    async def _execute_get_user_info(
        self, 
        user_id: str, 
        key: str
    ) -> ToolResult:
        """Get user information from memory."""
        try:
            logger.info(f"[TOOL] Get User Info: {user_id} - {key}")
            
            # Try in-memory cache first
            user_data = self._user_cache.get(user_id, {})
            
            # Try Semantic Memory if not in cache
            if not user_data and self._semantic_memory:
                try:
                    context = await self._semantic_memory.retrieve_context(
                        user_id=user_id,
                        query="user information",
                        include_user_facts=True
                    )
                    if context.user_facts:
                        # Parse facts into structured data
                        for fact in context.user_facts:
                            if "name is" in fact.lower():
                                match = re.search(r"name is (\w+)", fact, re.IGNORECASE)
                                if match:
                                    user_data["name"] = match.group(1)
                            elif "role is" in fact.lower() or "sinh viên" in fact.lower():
                                user_data["role"] = fact
                except Exception as e:
                    logger.warning(f"Semantic memory retrieval failed: {e}")
            
            # Try Chat History for name
            if "name" not in user_data and self._chat_history:
                session = self._chat_history.get_or_create_session(user_id)
                if session:
                    name = self._chat_history.get_user_name(session.session_id)
                    if name:
                        user_data["name"] = name
            
            if key == "all":
                return ToolResult(success=True, data=user_data)
            else:
                value = user_data.get(key)
                return ToolResult(
                    success=True,
                    data={key: value} if value else {}
                )
                
        except Exception as e:
            logger.error(f"Get user info error: {e}")
            return ToolResult(success=False, data=None, error=str(e))


# ============================================================================
# UNIFIED AGENT (ReAct Pattern)
# ============================================================================

class UnifiedAgent:
    """
    Unified Agent using LLM-driven orchestration (ReAct pattern).
    
    Instead of rule-based intent classification, Gemini decides:
    - When to call tools (RAG, Memory)
    - When to respond directly
    - How to formulate queries for tools
    
    **Spec: CHỈ THỊ KỸ THUẬT SỐ 13**
    """
    
    # System prompt - The "personality" of the agent
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
- "Xin chào, tôi là Minh, sinh viên hàng hải" -> Gọi tool_save_user_info(name="Minh", role="sinh viên hàng hải"), rồi chào lại thân thiện.
- "Quy tắc 15 là gì?" -> Gọi tool_maritime_search("Quy tắc 15 COLREGs"), rồi tổng hợp trả lời.
- "Vậy tàu nào phải tránh?" -> Nhìn lịch sử chat, gọi tool_maritime_search với query đầy đủ ngữ cảnh.
- "Cảm ơn bạn" -> Trả lời trực tiếp, không cần tool."""

    def __init__(
        self,
        rag_agent=None,
        semantic_memory=None,
        chat_history=None
    ):
        """
        Initialize Unified Agent.
        
        Args:
            rag_agent: RAG Agent for maritime knowledge
            semantic_memory: Semantic Memory Engine
            chat_history: Chat History Repository
        """
        self._llm = self._init_llm()
        self._tools = MaritimeTools(
            rag_agent=rag_agent,
            semantic_memory=semantic_memory,
            chat_history=chat_history
        )
        
        logger.info("UnifiedAgent initialized with LLM-driven orchestration")
    
    def _init_llm(self):
        """Initialize Gemini LLM with function calling support."""
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            if not settings.google_api_key:
                logger.warning("No Google API key, UnifiedAgent will not work")
                return None
            
            llm = ChatGoogleGenerativeAI(
                google_api_key=settings.google_api_key,
                model=settings.google_model,
                temperature=0.7,
                convert_system_message_to_human=True,
            )
            
            logger.info(f"UnifiedAgent using Gemini: {settings.google_model}")
            return llm
            
        except Exception as e:
            logger.error(f"Failed to initialize LLM for UnifiedAgent: {e}")
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
        
        Flow:
        1. Build messages with system prompt + history + current message
        2. Call LLM with tool definitions
        3. If LLM wants to use tools -> Execute tools -> Feed results back to LLM
        4. Return final response
        
        Args:
            message: User's message
            user_id: User ID
            session_id: Session ID
            conversation_history: Previous messages
            user_role: User role (student/teacher/admin)
            
        Returns:
            Dict with response content and metadata
        """
        if not self._llm:
            return {
                "content": "Xin lỗi, hệ thống AI đang không khả dụng.",
                "agent_type": "unified",
                "tools_used": [],
                "error": "LLM not available"
            }
        
        try:
            # Build conversation messages
            messages = self._build_messages(message, conversation_history)
            
            # Get tool definitions
            tools = self._tools.get_tool_definitions()
            
            # ReAct loop: LLM -> Tool -> LLM -> ... -> Final Response
            tools_used = []
            max_iterations = 5  # Prevent infinite loops
            
            for iteration in range(max_iterations):
                logger.info(f"[ReAct] Iteration {iteration + 1}")
                
                # Call LLM with tools
                response = await self._call_llm_with_tools(messages, tools)
                
                # Check if LLM wants to use a tool
                tool_calls = self._extract_tool_calls(response)
                
                if not tool_calls:
                    # No tool calls - LLM is ready to respond
                    final_content = self._extract_content(response)
                    logger.info(f"[ReAct] Final response (no tools): {final_content[:100]}...")
                    
                    return {
                        "content": final_content,
                        "agent_type": "unified",
                        "tools_used": tools_used,
                        "iterations": iteration + 1
                    }
                
                # Execute tool calls
                messages.append(AIMessage(content="", additional_kwargs={"tool_calls": tool_calls}))
                
                for tool_call in tool_calls:
                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                    
                    try:
                        tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    logger.info(f"[ReAct] Calling tool: {tool_name}({tool_args})")
                    
                    # Execute tool
                    history_str = self._format_history_for_rag(conversation_history)
                    result = await self._tools.execute_tool(
                        tool_name,
                        tool_args,
                        user_id,
                        history_str
                    )
                    
                    tools_used.append({
                        "name": tool_name,
                        "args": tool_args,
                        "success": result.success
                    })
                    
                    # Add tool result to messages
                    tool_result_content = json.dumps(result.data, ensure_ascii=False) if result.success else f"Error: {result.error}"
                    messages.append(ToolMessage(
                        content=tool_result_content,
                        tool_call_id=tool_call.get("id", "")
                    ))
            
            # Max iterations reached
            logger.warning("[ReAct] Max iterations reached")
            return {
                "content": "Xin lỗi, tôi gặp khó khăn khi xử lý yêu cầu này. Vui lòng thử lại.",
                "agent_type": "unified",
                "tools_used": tools_used,
                "error": "Max iterations reached"
            }
            
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
        messages = [SystemMessage(content=self.SYSTEM_PROMPT)]
        
        # Add conversation history
        if conversation_history:
            for msg in conversation_history[-10:]:  # Last 10 messages
                role = msg.get("role", "")
                content = msg.get("content", "")
                
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # Add current message
        messages.append(HumanMessage(content=message))
        
        return messages
    
    async def _call_llm_with_tools(self, messages: List, tools: List[Dict]) -> Any:
        """Call LLM with tool definitions."""
        try:
            # Bind tools to LLM
            llm_with_tools = self._llm.bind(tools=tools)
            response = await llm_with_tools.ainvoke(messages)
            return response
        except Exception as e:
            logger.error(f"LLM call error: {e}")
            # Fallback: call without tools
            response = await self._llm.ainvoke(messages)
            return response
    
    def _extract_tool_calls(self, response) -> List[Dict]:
        """Extract tool calls from LLM response."""
        tool_calls = []
        
        # Check additional_kwargs for tool_calls
        if hasattr(response, 'additional_kwargs'):
            tool_calls = response.additional_kwargs.get('tool_calls', [])
        
        # Check tool_calls attribute directly
        if not tool_calls and hasattr(response, 'tool_calls'):
            tool_calls = response.tool_calls or []
        
        return tool_calls
    
    def _extract_content(self, response) -> str:
        """Extract text content from LLM response."""
        if hasattr(response, 'content'):
            return response.content
        return str(response)
    
    def _format_history_for_rag(self, conversation_history: List[Dict] = None) -> str:
        """Format conversation history for RAG context."""
        if not conversation_history:
            return ""
        
        lines = []
        for msg in conversation_history[-5:]:  # Last 5 messages
            role = "User" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "")[:200]  # Truncate
            lines.append(f"{role}: {content}")
        
        return "\n".join(lines)
    
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
