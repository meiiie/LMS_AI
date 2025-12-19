"""
Tutor Agent Node - Teaching Specialist (SOTA ReAct Pattern)

Handles educational interactions with tool-enabled RAG retrieval.

**SOTA 2025 Pattern:** 
- Tool-Enabled Agent with ReAct Loop
- RAG-First approach via system prompt
- Uses CorrectiveRAG internally via tool_maritime_search

**Integrated with agents/ framework for config and tracing.**
"""

import logging
from typing import Optional, List, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from app.core.config import settings
from app.engine.llm_factory import create_tutor_llm
from app.services.output_processor import extract_thinking_from_response
from app.engine.multi_agent.state import AgentState
from app.engine.agents import TUTOR_AGENT_CONFIG, AgentConfig
from app.engine.tools.rag_tools import (
    tool_maritime_search,
    get_last_retrieved_sources,
    get_last_native_thinking,  # CHỈ THỊ SỐ 29 v9: Option B+ thinking propagation
    get_last_reasoning_trace,  # CHỈ THỊ SỐ 31 v3: CRAG trace propagation
    clear_retrieved_sources
)

logger = logging.getLogger(__name__)


# =============================================================================
# SOTA SYSTEM PROMPT - Force RAG-First Pattern
# =============================================================================

TUTOR_SYSTEM_PROMPT = """Bạn là Maritime Tutor - chuyên gia giảng dạy hàng hải.

## QUY TẮC BẮT BUỘC (CRITICAL):

1. **LUÔN LUÔN** sử dụng tool `tool_maritime_search` để tìm kiếm kiến thức **TRƯỚC KHI** trả lời bất kỳ câu hỏi nào về:
   - Quy tắc hàng hải (COLREGs, SOLAS, MARPOL, ISM Code)
   - Thuật ngữ chuyên môn hàng hải
   - Quy trình, thủ tục an toàn
   - Bất kỳ kiến thức maritime nào

2. **KHÔNG BAO GIỜ** trả lời từ kiến thức riêng mà không tìm kiếm trước

3. Sau khi tìm kiếm, giảng dạy **DỰA TRÊN** kết quả tìm được

4. **TRÍCH DẪN nguồn** trong câu trả lời (ví dụ: "Theo Rule 15 COLREGs...")

## Phong cách giảng dạy:
- Giải thích từ đơn giản đến phức tạp
- Dùng ví dụ thực tế từ tình huống hàng hải
- Khuyến khích và động viên học viên
- Dịch thuật ngữ tiếng Anh sang tiếng Việt khi cần
- Sử dụng markdown formatting cho dễ đọc

## Ngữ cảnh học viên:
{context}

## Yêu cầu:
{query}
"""


class TutorAgentNode:
    """
    Tutor Agent - Teaching specialist with SOTA ReAct pattern.
    
    Responsibilities:
    - Explain concepts clearly with RAG-backed knowledge
    - Create quizzes and exercises
    - Adapt to learner level
    - Always cite sources
    
    SOTA Pattern: Tool-Enabled Agent with RAG-First approach
    """
    
    def __init__(self):
        """Initialize Tutor Agent with tools."""
        self._llm = None
        self._llm_with_tools = None
        self._config = TUTOR_AGENT_CONFIG
        self._tools = [tool_maritime_search]
        self._init_llm()
        logger.info(f"TutorAgentNode initialized with config: {self._config.id}, tools: {len(self._tools)}")
    
    def _init_llm(self):
        """Initialize teaching LLM with tools and native thinking."""
        try:
            # CHỈ THỊ SỐ 28: Use DEEP tier thinking (8192 tokens) for teaching
            self._llm = create_tutor_llm(temperature=0.7)
            # Bind tools to LLM (SOTA pattern)
            self._llm_with_tools = self._llm.bind_tools(self._tools)
            logger.info(f"[TUTOR_AGENT] LLM with DEEP thinking bound with {len(self._tools)} tools")
        except Exception as e:
            logger.error(f"Failed to initialize Tutor LLM: {e}")
            self._llm = None
            self._llm_with_tools = None
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process educational request with ReAct pattern.
        
        SOTA Pattern: Think → Act → Observe → Repeat
        
        CHỈ THỊ SỐ 29 v9: Option B+ - Propagates thinking to state for API transparency.
        Combines thinking from:
        1. RAG tool (via get_last_native_thinking)
        2. Tutor LLM response (extracted in _react_loop)
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with tutor output, sources, tools_used, and thinking
        """
        query = state.get("query", "")
        context = state.get("context", {})
        learning_context = state.get("learning_context", {})
        
        try:
            # Execute ReAct loop - now returns thinking
            response, sources, tools_used, thinking = await self._react_loop(
                query=query,
                context={**context, **learning_context}
            )
            
            # Update state with results
            state["tutor_output"] = response
            state["sources"] = sources
            state["tools_used"] = tools_used
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["tutor"] = response
            state["agent_outputs"]["tutor_tools_used"] = tools_used  # SOTA: Track tool usage
            state["current_agent"] = "tutor_agent"
            
            # CHỈ THỊ SỐ 29 v9: Set thinking in state for SOTA reasoning transparency
            # This follows the same pattern as rag_node.py
            if thinking:
                state["thinking"] = thinking
                logger.info(f"[TUTOR_AGENT] Thinking propagated to state: {len(thinking)} chars")
            
            # CHỈ THỊ SỐ 31 v3 SOTA: Propagate CRAG trace for synthesizer merge
            # This follows LangGraph shared state pattern
            crag_trace = get_last_reasoning_trace()
            if crag_trace:
                state["reasoning_trace"] = crag_trace
                logger.info(f"[TUTOR_AGENT] CRAG trace propagated: {crag_trace.total_steps} steps")
            
            logger.info(f"[TUTOR_AGENT] ReAct complete: {len(tools_used)} tool calls, {len(sources)} sources")
            
        except Exception as e:
            logger.error(f"[TUTOR_AGENT] Error: {e}")
            state["tutor_output"] = f"Xin lỗi, tôi gặp lỗi khi tạo bài giảng: {e}"
            state["error"] = str(e)
            state["sources"] = []
            state["tools_used"] = []
        
        return state
    
    async def _react_loop(
        self, 
        query: str, 
        context: dict
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Execute ReAct loop: Think → Act → Observe.
        
        SOTA Pattern from OpenAI Agents SDK / Anthropic Claude.
        
        CHỈ THỊ SỐ 29 v9: Now returns thinking for SOTA reasoning transparency.
        Combines thinking from:
        1. RAG tool (get_last_native_thinking) 
        2. Tutor LLM final response (extract_thinking_from_response)
        
        Args:
            query: User query
            context: Additional context
            
        Returns:
            Tuple of (response, sources, tools_used, thinking)
        """
        if not self._llm_with_tools:
            return self._fallback_response(query), [], [], None
        
        # Clear previous sources (also clears thinking)
        clear_retrieved_sources()
        
        # Build context string
        context_str = "\n".join([
            f"- {k}: {v}" for k, v in context.items() if v
        ]) or "Không có thông tin bổ sung"
        
        # Initialize messages
        messages = [
            SystemMessage(content=TUTOR_SYSTEM_PROMPT.format(
                query=query,
                context=context_str
            )),
            HumanMessage(content=query)
        ]
        
        tools_used = []
        max_iterations = 3
        final_response = ""
        llm_thinking = None  # Thinking from final LLM response
        
        # ReAct Loop
        for iteration in range(max_iterations):
            logger.info(f"[TUTOR_AGENT] ReAct iteration {iteration + 1}/{max_iterations}")
            
            # THINK: LLM reasons and decides action
            response = await self._llm_with_tools.ainvoke(messages)
            
            # Check if LLM wants to call tools
            if not response.tool_calls:
                # No tool calls = LLM is done, extract final response AND thinking
                final_response, llm_thinking = self._extract_content_with_thinking(response.content)
                logger.info(f"[TUTOR_AGENT] No more tool calls, generating final response")
                break
            
            # ACT: Execute tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                tool_id = tool_call.get("id", f"call_{iteration}")
                
                logger.info(f"[TUTOR_AGENT] Calling tool: {tool_name} with args: {tool_args}")
                
                if tool_name == "tool_maritime_search":
                    try:
                        # Execute the tool
                        search_query = tool_args.get("query", query)
                        result = await tool_maritime_search.ainvoke({"query": search_query})
                        
                        tools_used.append({
                            "name": tool_name,
                            "args": tool_args,
                            "description": f"Tra cứu: {search_query[:60]}..." if len(search_query) > 60 else f"Tra cứu: {search_query}",
                            "iteration": iteration + 1
                        })
                        
                        # OBSERVE: Add result to conversation
                        messages.append(AIMessage(content="", tool_calls=[tool_call]))
                        messages.append(ToolMessage(
                            content=str(result),
                            tool_call_id=tool_id
                        ))
                        
                        logger.info(f"[TUTOR_AGENT] Tool result length: {len(str(result))}")
                        
                    except Exception as e:
                        logger.error(f"[TUTOR_AGENT] Tool error: {e}")
                        messages.append(AIMessage(content="", tool_calls=[tool_call]))
                        messages.append(ToolMessage(
                            content=f"Error: {str(e)}",
                            tool_call_id=tool_id
                        ))
        
        # If we exhausted iterations without final response, generate one
        if not final_response:
            try:
                final_msg = await self._llm.ainvoke(messages)
                final_response, llm_thinking = self._extract_content_with_thinking(final_msg.content)
            except Exception as e:
                logger.error(f"[TUTOR_AGENT] Final generation error: {e}")
                final_response = "Đã xảy ra lỗi khi tạo câu trả lời."
        
        # Get sources from tool calls
        sources = get_last_retrieved_sources()
        
        # CHỈ THỊ SỐ 29 v9: Get RAG thinking from tool (Option B+)
        rag_thinking = get_last_native_thinking()
        
        # Combine thinking: prioritize RAG thinking (deeper analysis) 
        # but include LLM thinking if RAG thinking unavailable
        combined_thinking = None
        if rag_thinking and llm_thinking:
            combined_thinking = f"[RAG Analysis]\n{rag_thinking}\n\n[Teaching Process]\n{llm_thinking}"
        elif rag_thinking:
            combined_thinking = rag_thinking
        elif llm_thinking:
            combined_thinking = llm_thinking
        
        if combined_thinking:
            logger.info(f"[TUTOR_AGENT] Combined thinking: {len(combined_thinking)} chars (rag={bool(rag_thinking)}, llm={bool(llm_thinking)})")
        
        return final_response, sources, tools_used, combined_thinking
    
    def _fallback_response(self, query: str) -> str:
        """Fallback when LLM unavailable."""
        return f"""Tôi sẽ giúp bạn với: "{query}"

Để học hiệu quả, bạn nên:
1. Đọc quy định gốc (COLREGs, SOLAS)
2. Xem các ví dụ thực tế
3. Làm bài tập thực hành

Bạn muốn tôi giải thích khái niệm nào cụ thể?"""
    
    def _extract_content(self, content) -> str:
        """
        Safely extract text from LLM response content.
        
        CHỈ THỊ SỐ 28: Uses shared utility for Gemini thinking format.
        
        Returns:
            Extracted text as string
        """
        text, thinking = extract_thinking_from_response(content)
        
        # Log thinking if extracted (for debugging)
        if thinking:
            logger.debug(f"[TUTOR] Thinking extracted: {len(thinking)} chars")
        
        return text.strip() if text else ""
    
    def _extract_content_with_thinking(self, content) -> tuple[str, Optional[str]]:
        """
        Extract text AND thinking from LLM response content.
        
        CHỈ THỊ SỐ 29 v9: Option B+ - Returns thinking for state propagation.
        This is the SOTA pattern for reasoning transparency (Anthropic/OpenAI).
        
        Args:
            content: Response content from LLM
            
        Returns:
            Tuple of (text, thinking) where thinking may be None
        """
        text, thinking = extract_thinking_from_response(content)
        
        # Log thinking if extracted
        if thinking:
            logger.info(f"[TUTOR] Native thinking extracted: {len(thinking)} chars")
        
        return text.strip() if text else "", thinking
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None and self._llm_with_tools is not None


# Singleton
_tutor_node: Optional[TutorAgentNode] = None

def get_tutor_agent_node() -> TutorAgentNode:
    """Get or create TutorAgentNode singleton."""
    global _tutor_node
    if _tutor_node is None:
        _tutor_node = TutorAgentNode()
    return _tutor_node
