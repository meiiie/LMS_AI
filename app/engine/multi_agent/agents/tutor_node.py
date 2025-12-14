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
from app.engine.multi_agent.state import AgentState
from app.engine.agents import TUTOR_AGENT_CONFIG, AgentConfig
from app.engine.tools.rag_tools import (
    tool_maritime_search,
    get_last_retrieved_sources,
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
        """Initialize teaching LLM with tools."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model=settings.google_model,
                google_api_key=settings.google_api_key,
                temperature=0.7,  # Some creativity for teaching
                max_output_tokens=2000
            )
            # Bind tools to LLM (SOTA pattern)
            self._llm_with_tools = self._llm.bind_tools(self._tools)
            logger.info(f"[TUTOR_AGENT] LLM bound with {len(self._tools)} tools")
        except Exception as e:
            logger.error(f"Failed to initialize Tutor LLM: {e}")
            self._llm = None
            self._llm_with_tools = None
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process educational request with ReAct pattern.
        
        SOTA Pattern: Think → Act → Observe → Repeat
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with tutor output, sources, and tools_used
        """
        query = state.get("query", "")
        context = state.get("context", {})
        learning_context = state.get("learning_context", {})
        
        try:
            # Execute ReAct loop
            response, sources, tools_used = await self._react_loop(
                query=query,
                context={**context, **learning_context}
            )
            
            # Update state with results
            state["tutor_output"] = response
            state["sources"] = sources
            state["tools_used"] = tools_used
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["tutor"] = response
            state["current_agent"] = "tutor_agent"
            
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
    ) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Execute ReAct loop: Think → Act → Observe.
        
        SOTA Pattern from OpenAI Agents SDK / Anthropic Claude.
        
        Args:
            query: User query
            context: Additional context
            
        Returns:
            Tuple of (response, sources, tools_used)
        """
        if not self._llm_with_tools:
            return self._fallback_response(query), [], []
        
        # Clear previous sources
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
        
        # ReAct Loop
        for iteration in range(max_iterations):
            logger.info(f"[TUTOR_AGENT] ReAct iteration {iteration + 1}/{max_iterations}")
            
            # THINK: LLM reasons and decides action
            response = await self._llm_with_tools.ainvoke(messages)
            
            # Check if LLM wants to call tools
            if not response.tool_calls:
                # No tool calls = LLM is done, extract final response
                final_response = response.content.strip() if response.content else ""
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
                final_response = final_msg.content.strip() if final_msg.content else ""
            except Exception as e:
                logger.error(f"[TUTOR_AGENT] Final generation error: {e}")
                final_response = "Đã xảy ra lỗi khi tạo câu trả lời."
        
        # Get sources from tool calls
        sources = get_last_retrieved_sources()
        
        return final_response, sources, tools_used
    
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
        return self._llm is not None and self._llm_with_tools is not None


# Singleton
_tutor_node: Optional[TutorAgentNode] = None

def get_tutor_agent_node() -> TutorAgentNode:
    """Get or create TutorAgentNode singleton."""
    global _tutor_node
    if _tutor_node is None:
        _tutor_node = TutorAgentNode()
    return _tutor_node
