"""
Tool Registry Module - Centralized Tool Management

SOTA 2025 Pattern: Tool Registry with Categories

Usage:
    from app.engine.tools import get_tool_registry, TOOLS
    
    # Get all tools
    tools = get_tool_registry().get_all()
    
    # Get by category
    rag_tools = get_tool_registry().get_by_category(ToolCategory.RAG)
    memory_tools = get_tool_registry().get_by_category(ToolCategory.MEMORY)
"""

import logging

# Import registry first
from app.engine.tools.registry import (
    ToolRegistry,
    ToolCategory,
    ToolAccess,
    ToolInfo,
    get_tool_registry,
    register_tool
)

# Import and register tools
from app.engine.tools.rag_tools import (
    tool_maritime_search,
    init_rag_tools,
    get_last_retrieved_sources,
    clear_retrieved_sources
)

from app.engine.tools.memory_tools import (
    tool_save_user_info,
    tool_get_user_info,
    tool_remember,
    tool_forget,
    tool_list_memories,
    tool_clear_all_memories,
    init_memory_tools,
    set_current_user,
    get_user_cache
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

def get_all_tools() -> list:
    """Get all registered tools."""
    return get_tool_registry().get_all()


def init_all_tools(rag_agent=None, semantic_memory=None, user_id: str = None):
    """
    Initialize all tools with required dependencies.
    
    Args:
        rag_agent: RAG agent for knowledge retrieval
        semantic_memory: Semantic memory engine for user facts
        user_id: Current user ID
    """
    if rag_agent:
        init_rag_tools(rag_agent)
    
    if semantic_memory:
        init_memory_tools(semantic_memory, user_id)
    
    registry = get_tool_registry()
    summary = registry.summary()
    logger.info(f"Tool Registry initialized: {summary}")


# Backward compatibility: TOOLS list
TOOLS = get_all_tools()


__all__ = [
    # Registry
    "ToolRegistry",
    "ToolCategory",
    "ToolAccess",
    "ToolInfo",
    "get_tool_registry",
    "register_tool",
    
    # RAG Tools
    "tool_maritime_search",
    "init_rag_tools",
    "get_last_retrieved_sources",
    "clear_retrieved_sources",
    
    # Memory Tools
    "tool_save_user_info",
    "tool_get_user_info",
    "tool_remember",
    "tool_forget",
    "tool_list_memories",
    "tool_clear_all_memories",
    "init_memory_tools",
    "set_current_user",
    "get_user_cache",
    
    # Convenience
    "get_all_tools",
    "init_all_tools",
    "TOOLS"
]
