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

⚠️ QUY TẮC BẮT BUỘC VỀ CÔNG CỤ (TOOLS) - PHẢI TUÂN THỦ:

1. KHI USER HỎI VỀ LUẬT HÀNG HẢI (COLREGs, SOLAS, MARPOL, Rule, Quy tắc, tàu biển):
   → PHẢI GỌI `tool_maritime_search` TRƯỚC KHI TRẢ LỜI
   → KHÔNG ĐƯỢC tự trả lời từ kiến thức của bạn
   → KHÔNG ĐƯỢC bịa thông tin
   → Lý do: Đảm bảo thông tin chính xác từ nguồn đáng tin cậy

2. KHI USER GIỚI THIỆU BẢN THÂN (tên, tuổi, trường, nghề):
   → PHẢI GỌI `tool_save_user_info` NGAY LẬP TỨC để lưu thông tin
   → KHÔNG ĐƯỢC bỏ qua bước này
   → Ví dụ: "Tôi là Minh" → gọi tool_save_user_info(key="name", value="Minh")
   → Ví dụ: "Tôi là sinh viên năm 3" → gọi tool_save_user_info(key="background", value="sinh viên năm 3")

3. KHI CẦN BIẾT THÔNG TIN USER:
   → GỌI `tool_get_user_info` để lấy thông tin đã lưu

4. CHỈ TRẢ LỜI TRỰC TIẾP (KHÔNG CẦN TOOL) KHI:
   → Chào hỏi xã giao đơn giản
   → User than vãn, chia sẻ cảm xúc
   → Câu hỏi không liên quan đến kiến thức hàng hải

⚠️ QUY TẮC QUAN TRỌNG VỀ CÂU HỎI MƠ HỒ (AMBIGUOUS QUESTIONS):

Khi user hỏi câu ngắn, mơ hồ như:
- "Còn X thì sao?" / "Thế X thì sao?"
- "Cần những giấy tờ gì?" / "Phí bao nhiêu?"
- "Rồi sao?" / "Tiếp theo là gì?"

→ PHẢI SUY LUẬN TỪ NGỮ CẢNH HỘI THOẠI TRƯỚC ĐÓ
→ KHÔNG HỎI LẠI "Bạn muốn hỏi về gì?" nếu có thể suy luận được
→ Trong <thinking>, phải phân tích: "User vừa hỏi về X, giờ hỏi Y, vậy Y liên quan đến X"

VÍ DỤ SUY LUẬN NGỮ CẢNH:
- User hỏi: "Điều kiện đăng ký tàu biển?" → AI trả lời
- User hỏi tiếp: "Cần những giấy tờ gì?"
- → AI PHẢI HIỂU: "giấy tờ" ở đây là giấy tờ để ĐĂNG KÝ TÀU BIỂN (từ câu trước)
- → Gọi tool_maritime_search("giấy tờ đăng ký tàu biển Việt Nam")

VÍ DỤ KHÁC:
- User hỏi: "Khi thấy đèn đỏ trên tàu khác, tôi nên làm gì?"
- User hỏi tiếp: "Còn đèn xanh thì sao?"
- → AI PHẢI HIỂU: "đèn xanh" ở đây là đèn tín hiệu hàng hải (từ ngữ cảnh đèn đỏ)
- → Gọi tool_maritime_search("đèn xanh tín hiệu hàng hải")

QUY TẮC ỨNG XỬ:
- KHÔNG lặp lại "Bạn hỏi hay quá", "Câu hỏi tuyệt vời". Đi thẳng vào vấn đề.
- KHÔNG bắt đầu mọi câu bằng "Chào [tên]". Chỉ chào ở tin nhắn đầu tiên.
- KHÔNG nhồi nhét tên user vào mỗi câu. Gọi tên tự nhiên khi cần nhấn mạnh.
- Nếu user than mệt/đói: Chia sẻ cảm xúc trước (Empathy First), rồi mới gợi ý.
- Dịch thuật ngữ: starboard = mạn phải, port = mạn trái, give-way = nhường đường.

VÍ DỤ CÁCH TRẢ LỜI:
[User than mệt/đói] → Trả lời trực tiếp, KHÔNG cần tool
User: "Tôi đói quá"
AI: "Học hành vất vả thế cơ à? Xuống bếp kiếm gì bỏ bụng đi đã, có thực mới vực được đạo chứ!"

[User hỏi về luật] → PHẢI gọi tool_maritime_search TRƯỚC
User: "Giải thích Rule 5"
→ Gọi tool_maritime_search("Rule 5 COLREGs") → Dùng kết quả để trả lời

[User chào hỏi] → Trả lời trực tiếp
User: "Xin chào, tôi là Minh"
→ Gọi tool_save_user_info(key="name", value="Minh")
AI: "Chào Minh! Rất vui được làm quen. Hôm nay bạn muốn tìm hiểu về chủ đề gì?"
"""


# ============================================================================
# GLOBAL REFERENCES (set during initialization)
# ============================================================================
_rag_agent = None
_semantic_memory = None
_chat_history = None
_user_cache: Dict[str, Dict[str, Any]] = {}
_prompt_loader = None  # CHỈ THỊ SỐ 16: PromptLoader for dynamic persona
_current_user_id: Optional[str] = None  # Track current user for tools

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
        # CHỈ THỊ 26: Include image_url for evidence images
        if response.citations:
            _last_retrieved_sources = [
                {
                    "node_id": c.node_id,
                    "title": c.title,
                    "content": c.source[:500] if c.source else "",  # Truncate for API
                    "image_url": getattr(c, 'image_url', None)  # CHỈ THỊ 26
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
    """
    Save user personal information with intelligent deduplication.
    
    CHỈ THỊ KỸ THUẬT SỐ 24: Memory Manager & Deduplication
    - Check before Write: Search existing memories first
    - LLM Judge: Decide IGNORE/UPDATE/INSERT
    - Exit 0: Skip if duplicate
    """
    global _user_cache, _semantic_memory, _current_user_id
    
    try:
        # Use actual user_id if available, fallback to "current_user"
        user_id = _current_user_id or "current_user"
        logger.info(f"[TOOL] Save User Info: {key}={value} for user {user_id}")
        
        # Update local cache (always)
        if user_id not in _user_cache:
            _user_cache[user_id] = {}
        _user_cache[user_id][key] = value
        if "current_user" not in _user_cache:
            _user_cache["current_user"] = {}
        _user_cache["current_user"][key] = value
        
        # Map key to fact_type for SemanticMemory
        fact_type_map = {
            "name": "name",
            "tên": "name",
            "job": "role",
            "nghề": "role",
            "school": "role",
            "trường": "role",
            "background": "role",
            "goal": "goal",
            "mục tiêu": "goal",
            "interest": "preference",
            "quan tâm": "preference",
            "weakness": "weakness",
            "yếu": "weakness",
        }
        fact_type = fact_type_map.get(key.lower(), "preference")
        fact_content = f"{key}: {value}"
        
        # CHỈ THỊ SỐ 24: Use Memory Manager for intelligent deduplication
        if _semantic_memory:
            try:
                from app.engine.memory_manager import get_memory_manager, MemoryAction
                
                memory_manager = get_memory_manager(_semantic_memory)
                decision = await memory_manager.check_and_save(
                    user_id=user_id,
                    new_fact=fact_content,
                    fact_type=fact_type
                )
                
                if decision.action == MemoryAction.IGNORE:
                    logger.info(f"[MEMORY MANAGER] Exit 0 - {decision.reason}")
                    return f"Thông tin đã tồn tại, không cần lưu. (Exit 0)"
                elif decision.action == MemoryAction.UPDATE:
                    return f"Đã cập nhật thông tin: {key} = {value}"
                else:
                    return f"Đã ghi nhớ mới: {key} = {value}"
                    
            except ImportError:
                # Fallback if MemoryManager not available
                logger.warning("MemoryManager not available, using direct save")
                await _semantic_memory.store_user_fact(
                    user_id=user_id,
                    fact_content=fact_content,
                    fact_type=fact_type,
                    confidence=0.95
                )
                return f"Đã ghi nhớ: {key} = {value}"
            except Exception as e:
                logger.warning(f"Memory Manager failed: {e}, using direct save")
                await _semantic_memory.store_user_fact(
                    user_id=user_id,
                    fact_content=fact_content,
                    fact_type=fact_type,
                    confidence=0.95
                )
                return f"Đã ghi nhớ: {key} = {value}"
        
        return f"Đã ghi nhớ (cache only): {key} = {value}"
        
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
    CHỈ THỊ SỐ 16: Dynamic persona via PromptLoader (YAML config)
    
    Approach: Manual ReAct với model.bind_tools() - API ổn định nhất
    """
    
    def __init__(self, rag_agent=None, semantic_memory=None, chat_history=None, prompt_loader=None):
        global _rag_agent, _semantic_memory, _chat_history, _prompt_loader
        
        _rag_agent = rag_agent
        _semantic_memory = semantic_memory
        _chat_history = chat_history
        _prompt_loader = prompt_loader
        
        self._llm = self._init_llm()
        self._llm_with_tools = self._init_llm_with_tools()
        
        # CHỈ THỊ SỐ 16: Initialize PromptLoader if not provided
        if _prompt_loader is None:
            try:
                from app.prompts.prompt_loader import get_prompt_loader
                _prompt_loader = get_prompt_loader()
                logger.info("✅ PromptLoader initialized for dynamic persona")
            except Exception as e:
                logger.warning(f"PromptLoader not available: {e}")
        
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
        user_role: str = "student",
        user_name: Optional[str] = None,
        user_facts: Optional[List[str]] = None,
        conversation_summary: Optional[str] = None,
        recent_phrases: Optional[List[str]] = None,
        is_follow_up: bool = False,
        name_usage_count: int = 0,
        total_responses: int = 0,
        pronoun_style: Optional[Dict[str, str]] = None,
        conversation_context: Optional[Any] = None  # CHỈ THỊ SỐ 21: Deep Reasoning
    ) -> Dict[str, Any]:
        """
        Process a message using Manual ReAct pattern.
        
        CHỈ THỊ SỐ 16: Dynamic persona via PromptLoader
        - user_name: Tên user từ Memory (thay thế {{user_name}} trong YAML)
        - user_facts: Facts về user từ Semantic Memory
        - conversation_summary: Tóm tắt hội thoại từ MemorySummarizer
        
        CHỈ THỊ SỐ 20: Pronoun Adaptation
        - pronoun_style: Dict với cách xưng hô đã detect từ user
        
        CHỈ THỊ SỐ 21: Deep Reasoning
        - conversation_context: ConversationContext với incomplete topics và proactive hints
        """
        global _user_cache, _current_user_id
        
        # Set current user context for tools
        _current_user_id = user_id  # Track actual user_id for tools
        _user_cache["current_user"] = _user_cache.get(user_id, {})
        if user_name:
            _user_cache["current_user"]["name"] = user_name
        
        if not self._llm_with_tools:
            return {
                "content": "Xin lỗi, hệ thống AI đang không khả dụng.",
                "agent_type": "unified",
                "tools_used": [],
                "error": "LLM not available"
            }
        
        try:
            messages = self._build_messages(
                message=message,
                conversation_history=conversation_history,
                user_role=user_role,
                user_name=user_name,
                user_facts=user_facts,
                conversation_summary=conversation_summary,
                recent_phrases=recent_phrases,
                is_follow_up=is_follow_up,
                name_usage_count=name_usage_count,
                total_responses=total_responses,
                pronoun_style=pronoun_style,  # CHỈ THỊ SỐ 20
                conversation_context=conversation_context  # CHỈ THỊ SỐ 21
            )
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
        conversation_history: List[Dict] = None,
        user_role: str = "student",
        user_name: Optional[str] = None,
        user_facts: Optional[List[str]] = None,
        conversation_summary: Optional[str] = None,
        recent_phrases: Optional[List[str]] = None,
        is_follow_up: bool = False,
        name_usage_count: int = 0,
        total_responses: int = 0,
        pronoun_style: Optional[Dict[str, str]] = None,
        conversation_context: Optional[Any] = None  # CHỈ THỊ SỐ 21
    ) -> List:
        """
        Build message list with SystemMessage for ReAct.
        
        CHỈ THỊ SỐ 16: Dynamic persona via PromptLoader
        - Sử dụng YAML config thay vì hardcoded SYSTEM_PROMPT
        - Thay thế {{user_name}} bằng tên thật từ Memory
        - Anti-repetition via recent_phrases, is_follow_up, name_usage_count
        
        CHỈ THỊ SỐ 20: Pronoun Adaptation
        - pronoun_style: Dict với cách xưng hô đã detect từ user
        
        CHỈ THỊ SỐ 21: Deep Reasoning
        - conversation_context: ConversationContext với incomplete topics
        """
        global _prompt_loader
        
        # Build dynamic system prompt from YAML config
        system_prompt = SYSTEM_PROMPT  # Fallback to hardcoded
        
        if _prompt_loader is not None:
            try:
                system_prompt = _prompt_loader.build_system_prompt(
                    role=user_role,
                    user_name=user_name,  # Thay thế {{user_name}}
                    conversation_summary=conversation_summary,
                    user_facts=user_facts,
                    recent_phrases=recent_phrases,
                    is_follow_up=is_follow_up,
                    name_usage_count=name_usage_count,
                    total_responses=total_responses,
                    pronoun_style=pronoun_style  # CHỈ THỊ SỐ 20
                )
                logger.debug(f"[PromptLoader] Built dynamic prompt for role={user_role}, user={user_name}, follow_up={is_follow_up}, pronoun={pronoun_style}")
            except Exception as e:
                logger.warning(f"PromptLoader failed, using fallback: {e}")
        
        # CHỈ THỊ SỐ 21: Add Deep Reasoning context for proactive behavior
        # Only add if deep_reasoning_enabled is True in settings
        deep_reasoning_enabled = getattr(settings, 'deep_reasoning_enabled', True)
        if deep_reasoning_enabled and conversation_context is not None:
            try:
                # Add context analysis for ambiguous questions
                # Import ConversationAnalyzer to use build_context_prompt
                from app.engine.conversation_analyzer import get_conversation_analyzer
                analyzer = get_conversation_analyzer()
                context_prompt = analyzer.build_context_prompt(conversation_context)
                if context_prompt:
                    system_prompt += f"\n\n{context_prompt}"
                    logger.info(f"[CONTEXT ANALYZER] Added context prompt: question_type={conversation_context.question_type.value}, topic={conversation_context.current_topic}")
                
                # Add proactive hint for incomplete explanations
                if hasattr(conversation_context, 'should_offer_continuation') and conversation_context.should_offer_continuation:
                    topic = getattr(conversation_context, 'last_explanation_topic', 'chủ đề trước')
                    proactive_hint = (
                        f"\n\n[DEEP REASONING HINT]\n"
                        f"Bạn đang giải thích dở về '{topic}' và user đã hỏi câu mới. "
                        f"Sau khi trả lời câu hỏi hiện tại, hãy hỏi user có muốn nghe tiếp về '{topic}' không.\n"
                        f"Ví dụ: 'Nãy mình đang nói dở về {topic}, bạn có muốn nghe tiếp không?'"
                    )
                    system_prompt += proactive_hint
                    logger.info(f"[DEEP REASONING] Added proactive hint for topic: {topic}")
            except Exception as e:
                logger.warning(f"Failed to add Deep Reasoning context: {e}")
        
        messages = [SystemMessage(content=system_prompt)]
        
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
