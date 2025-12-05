"""
Unified Agent - LLM-driven Orchestration (ReAct Pattern)

CHỈ THỊ KỸ THUẬT SỐ 13: KIẾN TRÚC UNIFIED AGENT (TOOL-USE ARCHITECTURE)
CHỈ THỊ KỸ THUẬT SỐ 15: NÂNG CẤP DEPENDENCIES (SOTA STACK)

Cập nhật theo LangChain 1.x Documentation (Tháng 12/2025):
- Sử dụng Manual ReAct với model.bind_tools() (API ổn định nhất)
- @tool decorator từ langchain_core.tools
- Async tools được hỗ trợ đầy đủ
- SystemMessage cho system prompt

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
from typing import Any, Dict, List, Optional

# LangChain 1.x imports
try:
    from langchain.tools import tool
except ImportError:
    from langchain_core.tools import tool

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

# ============================================================================
# SYSTEM PROMPT - "Nhân cách" của Agent
# CHỈ THỊ KỸ THUẬT SỐ 16: HUMANIZATION - Tự nhiên hơn, ít máy móc
# ============================================================================

SYSTEM_PROMPT = """Bạn là Maritime AI Tutor - người bạn đồng hành am hiểu về Hàng hải.

GIỌNG VĂN:
- Thân thiện, như một người bạn lớn tuổi am hiểu
- Không dùng kính ngữ quá trang trọng
- Biết đùa nhẹ nhàng khi user than vãn
- Giải thích thuật ngữ bằng ngôn ngữ đời thường

SỬ DỤNG CÔNG CỤ (TOOLS):
- Hỏi về luật hàng hải, quy tắc, tàu biển -> BẮT BUỘC gọi `tool_maritime_search`. ĐỪNG bịa.
- User giới thiệu tên/tuổi/trường/nghề -> Gọi `tool_save_user_info` để ghi nhớ.
- Cần biết tên user -> Gọi `tool_get_user_info`.
- Chào hỏi xã giao, than vãn -> Trả lời trực tiếp, KHÔNG cần tool.

QUY TẮC ỨNG XỬ:
- KHÔNG lặp lại "Bạn hỏi hay quá", "Câu hỏi tuyệt vời". Đi thẳng vào vấn đề.
- KHÔNG bắt đầu mọi câu bằng "Chào [tên]". Chỉ chào ở tin nhắn đầu tiên.
- KHÔNG nhồi nhét tên user vào mỗi câu. Gọi tên tự nhiên khi cần nhấn mạnh.
- Nếu user than mệt/đói: Chia sẻ cảm xúc trước (Empathy First), rồi mới gợi ý.
- Dịch thuật ngữ: starboard = mạn phải, port = mạn trái, give-way = nhường đường.

VÍ DỤ CÁCH TRẢ LỜI:
[User than mệt/đói]
User: "Tôi đói quá"
AI: "Học hành vất vả thế cơ à? Xuống bếp kiếm gì bỏ bụng đi đã, có thực mới vực được đạo chứ!"

[User hỏi về luật]
User: "Giải thích Rule 5"
AI: "Ok, Rule 5 về Cảnh giới. Tưởng tượng thế này nhé: Bạn đang lái xe, phải luôn quan sát xung quanh đúng không? Trên tàu cũng vậy..."

[User chào hỏi]
User: "Xin chào, tôi là Minh"
AI: "Chào Minh! Rất vui được làm quen. Hôm nay bạn muốn tìm hiểu về chủ đề gì?"

[User cảm ơn]
User: "Cảm ơn bạn"
AI: "Không có gì! Học vui nhé, có gì thắc mắc cứ hỏi."

[User hỏi tiếp]
User: "Vậy tàu nào phải tránh?"
AI: "Trong tình huống cắt hướng, tàu nhìn thấy tàu kia ở mạn phải phải nhường đường. Dễ nhớ: 'Thấy đèn đỏ - Dừng lại'."
"""


# ============================================================================
# GLOBAL REFERENCES (set during initialization)
# ============================================================================
_rag_agent = None
_semantic_memory = None
_chat_history = None
_user_cache: Dict[str, Dict[str, Any]] = {}

# CHỈ THỊ KỸ THUẬT SỐ 16: Lưu sources từ tool_maritime_search
# Để API có thể trả về sources trong response
_last_retrieved_sources: List[Dict[str, str]] = []


# ============================================================================
# TOOL DEFINITIONS (LangChain @tool decorator)
# ============================================================================

@tool(description="Tra cứu các quy tắc, luật lệ hàng hải (COLREGs, SOLAS, MARPOL) hoặc thông tin kỹ thuật về tàu biển. CHỈ gọi khi user hỏi về kiến thức chuyên môn hàng hải.")
async def tool_maritime_search(query: str) -> str:
    """Search maritime regulations and knowledge base."""
    global _rag_agent, _last_retrieved_sources
    
    if not _rag_agent:
        return "Lỗi: RAG Agent không khả dụng. Không thể tra cứu kiến thức."
    
    try:
        logger.info(f"[TOOL] Maritime Search: {query}")
        response = await _rag_agent.query(query, user_role="student")
        
        result = response.content
        
        # CHỈ THỊ KỸ THUẬT SỐ 16: Lưu sources để API trả về
        if response.citations:
            _last_retrieved_sources = [
                {
                    "node_id": c.node_id,
                    "title": c.title,
                    "content": c.source[:500] if c.source else ""  # Truncate for API
                }
                for c in response.citations[:5]  # Top 5 sources
            ]
            logger.info(f"[TOOL] Saved {len(_last_retrieved_sources)} sources for API response")
            
            # Also append to text for LLM context
            sources_text = [f"- {c.title}" for c in response.citations[:3]]
            result += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources_text)
        else:
            _last_retrieved_sources = []
        
        return result
        
    except Exception as e:
        logger.error(f"Maritime search error: {e}")
        _last_retrieved_sources = []
        return f"Lỗi khi tra cứu: {str(e)}"


@tool(description="Lưu thông tin cá nhân của người dùng khi họ giới thiệu bản thân. Gọi khi user nói tên, nghề nghiệp, trường học.")
async def tool_save_user_info(key: str, value: str) -> str:
    """Save user personal information."""
    global _user_cache, _semantic_memory
    
    try:
        logger.info(f"[TOOL] Save User Info: {key}={value}")
        
        user_id = "current_user"
        if user_id not in _user_cache:
            _user_cache[user_id] = {}
        _user_cache[user_id][key] = value
        
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


@tool(description="Lấy thông tin đã lưu về người dùng. Gọi khi cần biết tên hoặc thông tin user để cá nhân hóa câu trả lời.")
async def tool_get_user_info(key: str = "all") -> str:
    """Get saved user information."""
    global _user_cache, _semantic_memory
    
    try:
        logger.info(f"[TOOL] Get User Info: {key}")
        
        user_id = "current_user"
        user_data = _user_cache.get(user_id, {})
        
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
            return f"Thông tin user: {user_data}" if user_data else "Chưa có thông tin user."
        else:
            value = user_data.get(key)
            return f"{key}: {value}" if value else f"Chưa có thông tin về {key}."
            
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        return f"Lỗi khi lấy thông tin: {str(e)}"


TOOLS = [tool_maritime_search, tool_save_user_info, tool_get_user_info]


# ============================================================================
# UNIFIED AGENT CLASS
# ============================================================================

class UnifiedAgent:
    """
    Unified Agent using Manual ReAct Pattern with LangChain 1.x.
    
    CHỈ THỊ SỐ 13: LLM-driven orchestration (ReAct pattern)
    CHỈ THỊ SỐ 15: Sử dụng LangChain 1.x API (bind_tools + manual loop)
    
    Approach: Manual ReAct với model.bind_tools() - API ổn định nhất
    """
    
    def __init__(self, rag_agent=None, semantic_memory=None, chat_history=None):
        global _rag_agent, _semantic_memory, _chat_history
        
        _rag_agent = rag_agent
        _semantic_memory = semantic_memory
        _chat_history = chat_history
        
        self._llm = self._init_llm()
        self._llm_with_tools = self._init_llm_with_tools()
        
        logger.info("UnifiedAgent initialized (Manual ReAct)")
    
    def _init_llm(self):
        """Initialize Gemini LLM."""
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            
            if not settings.google_api_key:
                logger.warning("No Google API key")
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
    
    def _init_llm_with_tools(self):
        """Initialize LLM with tools bound (LangChain 1.x API)."""
        if not self._llm:
            return None
        
        try:
            llm_with_tools = self._llm.bind_tools(TOOLS)
            logger.info(f"✅ LLM bound with {len(TOOLS)} tools")
            return llm_with_tools
        except Exception as e:
            logger.error(f"Failed to bind tools: {e}")
            return None
    
    async def process(
        self,
        message: str,
        user_id: str,
        session_id: str,
        conversation_history: List[Dict] = None,
        user_role: str = "student"
    ) -> Dict[str, Any]:
        """Process a message using Manual ReAct pattern."""
        global _user_cache
        
        # Set current user context for tools
        _user_cache["current_user"] = _user_cache.get(user_id, {})
        
        if not self._llm_with_tools:
            return {
                "content": "Xin lỗi, hệ thống AI đang không khả dụng.",
                "agent_type": "unified",
                "tools_used": [],
                "error": "LLM not available"
            }
        
        try:
            messages = self._build_messages(message, conversation_history)
            return await self._manual_react(messages, user_id)
                
        except Exception as e:
            logger.error(f"UnifiedAgent error: {e}")
            return {
                "content": f"Xin lỗi, đã có lỗi xảy ra: {str(e)}",
                "agent_type": "unified",
                "tools_used": [],
                "error": str(e)
            }
    
    def _build_messages(self, message: str, conversation_history: List[Dict] = None) -> List:
        """Build message list with SystemMessage for ReAct."""
        messages = [SystemMessage(content=SYSTEM_PROMPT)]
        
        if conversation_history:
            for msg in conversation_history[-10:]:
                role, content = msg.get("role", ""), msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        messages.append(HumanMessage(content=message))
        return messages
    
    async def _manual_react(self, messages: List, user_id: str, max_iterations: int = 5) -> Dict[str, Any]:
        """
        Manual ReAct implementation (LangChain 1.x API).
        
        Loop: LLM -> Check tool_calls -> Execute tools -> Repeat until no tool_calls
        """
        tools_used = []
        tools_map = {t.name: t for t in TOOLS}
        
        for iteration in range(max_iterations):
            logger.info(f"[ReAct] Iteration {iteration + 1}")
            
            # Call LLM with tools
            response = await self._llm_with_tools.ainvoke(messages)
            tool_calls = getattr(response, 'tool_calls', [])
            
            logger.debug(f"[ReAct] Tool calls: {len(tool_calls)}")
            
            # No tool calls = final answer
            if not tool_calls:
                content = self._extract_content(response)
                return {
                    "content": content,
                    "agent_type": "unified",
                    "tools_used": tools_used,
                    "method": "manual_react",
                    "iterations": iteration + 1
                }
            
            # Execute tools
            messages.append(response)
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")
                
                logger.info(f"[ReAct] Calling: {tool_name}({tool_args})")
                
                # Execute tool
                if tool_name in tools_map:
                    try:
                        result = await tools_map[tool_name].ainvoke(tool_args)
                    except Exception as e:
                        logger.error(f"Tool {tool_name} error: {e}")
                        result = f"Error executing tool: {e}"
                else:
                    result = f"Tool '{tool_name}' not found"
                
                tools_used.append({"name": tool_name, "args": tool_args, "result": str(result)[:100]})
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))
        
        # Max iterations reached
        logger.warning(f"[ReAct] Max iterations ({max_iterations}) reached")
        return {
            "content": "Xin lỗi, tôi gặp khó khăn khi xử lý yêu cầu này. Vui lòng thử lại.",
            "agent_type": "unified",
            "tools_used": tools_used,
            "method": "manual_react",
            "error": "Max iterations reached"
        }
    
    def _extract_content(self, response) -> str:
        """Extract text content from AIMessage (handles list format)."""
        content = response.content
        
        # Gemini sometimes returns content as list
        if isinstance(content, list):
            if content and isinstance(content[0], dict):
                return content[0].get('text', str(content))
            return str(content)
        
        return content if content else ""
    
    def is_available(self) -> bool:
        """Check if agent is ready to process messages."""
        return self._llm_with_tools is not None


# Singleton
_unified_agent: Optional[UnifiedAgent] = None

def get_unified_agent(rag_agent=None, semantic_memory=None, chat_history=None) -> UnifiedAgent:
    global _unified_agent
    if _unified_agent is None:
        _unified_agent = UnifiedAgent(rag_agent=rag_agent, semantic_memory=semantic_memory, chat_history=chat_history)
    return _unified_agent


def get_last_retrieved_sources() -> List[Dict[str, str]]:
    """
    Get sources from the last tool_maritime_search call.
    
    CHỈ THỊ KỸ THUẬT SỐ 16: Trả về sources cho API response.
    
    Returns:
        List of source dicts with node_id, title, content
    """
    global _last_retrieved_sources
    return _last_retrieved_sources.copy()


def clear_retrieved_sources() -> None:
    """
    Clear the last retrieved sources.
    
    Should be called at the start of each request to avoid stale data.
    """
    global _last_retrieved_sources
    _last_retrieved_sources = []
