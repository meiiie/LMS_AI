"""
RAG Tools - Knowledge Retrieval Tools for Maritime AI Tutor

Category: RAG (Knowledge Retrieval)
Access: READ (safe, no mutations)
"""

import logging
import re
from typing import List, Dict, Optional, Any

from langchain_core.tools import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level state (will be initialized by UnifiedAgent)
# =============================================================================

_rag_agent = None
_last_retrieved_sources: List[Dict[str, str]] = []
# CHỈ THỊ SỐ 29 v9: Store native thinking for SOTA reasoning transparency
_last_native_thinking: Optional[str] = None
# CHỈ THỊ SỐ 31: Store reasoning_trace from CRAG for trace merge
_last_reasoning_trace: Optional[Any] = None


def init_rag_tools(rag_agent):
    """Initialize RAG tools with the RAG agent."""
    global _rag_agent
    _rag_agent = rag_agent
    logger.info("RAG tools initialized")


def get_last_retrieved_sources() -> List[Dict[str, str]]:
    """Get the last retrieved sources for API response."""
    return _last_retrieved_sources


def get_last_native_thinking() -> Optional[str]:
    """
    Get the last native thinking from RAG for SOTA reasoning transparency.
    
    CHỈ THỊ SỐ 29 v9: Option B+ - Tool-level thinking propagation.
    This allows tutor_node to capture RAGAgent's thinking and propagate to state.
    
    Returns:
        Native thinking string from Gemini, or None if not available
    """
    return _last_native_thinking


def get_last_reasoning_trace():
    """
    Get the last reasoning_trace from RAG for SOTA trace merge.
    
    CHỈ THỊ SỐ 31: Option C - Priority merge pattern.
    This allows tutor_node/synthesizer to merge CRAG's rich trace with graph trace.
    
    Returns:
        ReasoningTrace object from CorrectiveRAG, or None if not available
    """
    return _last_reasoning_trace


def clear_retrieved_sources():
    """Clear the retrieved sources, native thinking, and reasoning trace."""
    global _last_retrieved_sources, _last_native_thinking, _last_reasoning_trace
    _last_retrieved_sources = []
    _last_native_thinking = None
    _last_reasoning_trace = None


# =============================================================================
# RAG TOOLS
# =============================================================================

@tool(description="""
Tra cứu các quy tắc, luật lệ hàng hải (COLREGs, SOLAS, MARPOL) hoặc thông tin kỹ thuật về tàu biển.
CHỈ gọi khi user hỏi về kiến thức chuyên môn hàng hải.
""")
async def tool_maritime_search(query: str) -> str:
    """Search maritime regulations and knowledge base.
    
    CHỈ THỊ SỐ 31 v3 SOTA: Uses CorrectiveRAG for full 8-step trace.
    Following DeepSeek R1 pattern: consistent trace from all RAG calls.
    """
    global _rag_agent, _last_retrieved_sources, _last_native_thinking, _last_reasoning_trace
    
    # Import CorrectiveRAG for SOTA trace generation
    from app.engine.agentic_rag.corrective_rag import get_corrective_rag
    
    if not _rag_agent:
        return "Lỗi: RAG Agent không khả dụng. Không thể tra cứu kiến thức."
    
    try:
        logger.info(f"[TOOL] Maritime Search (CRAG): {query}")
        
        # CHỈ THỊ SỐ 31 v3 SOTA: Use CorrectiveRAG for full trace
        # This follows DeepSeek R1 pattern: ALL RAG calls produce consistent traces
        crag = get_corrective_rag(_rag_agent)
        crag_result = await crag.process(query, context={})
        
        result = crag_result.answer
        
        # CHỈ THỊ SỐ 31 v3: Store CRAG trace for propagation
        _last_reasoning_trace = crag_result.reasoning_trace
        if _last_reasoning_trace:
            logger.info(f"[TOOL] CRAG trace captured: {_last_reasoning_trace.total_steps} steps")
        
        # CHỈ THỊ SỐ 29 v9: Capture native thinking for SOTA reasoning transparency
        _last_native_thinking = crag_result.thinking
        if _last_native_thinking:
            logger.info(f"[TOOL] Native thinking captured: {len(_last_native_thinking)} chars")
        
        # CHỈ THỊ KỸ THUẬT SỐ 16: Store sources for API response
        # CHỈ THỊ 26: Include image_url for evidence images
        # Feature: source-highlight-citation - Include bounding_boxes
        if crag_result.sources:
            _last_retrieved_sources = [
                {
                    "node_id": src.get("node_id", ""),
                    "title": src.get("title", ""),
                    "content": src.get("content", "")[:500] if src.get("content") else "",
                    "image_url": src.get("image_url"),
                    "page_number": src.get("page_number"),
                    "document_id": src.get("document_id"),
                    "bounding_boxes": src.get("bounding_boxes")
                }
                for src in crag_result.sources[:5]  # Top 5 sources
            ]
            # Debug: Log source details for troubleshooting
            for i, src in enumerate(_last_retrieved_sources[:2]):
                logger.info(f"[TOOL] Source {i+1}: page={src.get('page_number')}, doc={src.get('document_id')}, bbox={bool(src.get('bounding_boxes'))}")
            logger.info(f"[TOOL] Saved {len(_last_retrieved_sources)} sources for API response")
            
            # Also append to text for LLM context
            sources_text = [f"- {src.get('title', 'Unknown')}" for src in crag_result.sources[:3]]
            result += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources_text)
        else:
            _last_retrieved_sources = []
        
        return result
        
    except Exception as e:
        logger.error(f"Maritime search error: {e}")
        _last_retrieved_sources = []
        _last_native_thinking = None
        _last_reasoning_trace = None
        return f"Lỗi khi tra cứu: {str(e)}"


# =============================================================================
# REGISTER TOOLS
# =============================================================================

def register_rag_tools():
    """Register all RAG tools with the registry."""
    registry = get_tool_registry()
    
    registry.register(
        tool=tool_maritime_search,
        category=ToolCategory.RAG,
        access=ToolAccess.READ,
        description="Search maritime regulations (COLREGs, SOLAS, MARPOL)"
    )
    
    logger.info("RAG tools registered")


# Auto-register on import
register_rag_tools()
