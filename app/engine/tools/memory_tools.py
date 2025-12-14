"""
Memory Tools - User Memory Management for Maritime AI Tutor

Category: MEMORY (User data storage)
Access: Mixed (READ and WRITE)

Includes:
- Basic memory tools (save/get user info)
- Phase 10: Explicit memory control (remember/forget/list/clear)
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from langchain_core.tools import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level state (will be initialized by UnifiedAgent)
# =============================================================================

_user_cache: Dict[str, Dict[str, Any]] = {}
_semantic_memory = None
_current_user_id: Optional[str] = None


def init_memory_tools(semantic_memory, user_id: Optional[str] = None):
    """Initialize memory tools with semantic memory engine."""
    global _semantic_memory, _current_user_id
    _semantic_memory = semantic_memory
    _current_user_id = user_id
    logger.info(f"Memory tools initialized (user_id={user_id})")


def set_current_user(user_id: str):
    """Set the current user ID for memory operations."""
    global _current_user_id
    _current_user_id = user_id


def get_user_cache() -> Dict[str, Dict[str, Any]]:
    """Get the user cache for external access."""
    return _user_cache


# =============================================================================
# BASIC MEMORY TOOLS
# =============================================================================

@tool(description="""
Lưu thông tin cá nhân của người dùng khi họ giới thiệu bản thân.
Gọi khi user nói tên, nghề nghiệp, trường học.
""")
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
                await _semantic_memory.store_user_fact_upsert(
                    user_id=user_id,
                    fact_content=fact_content,
                    fact_type=fact_type,
                    confidence=0.95
                )
                return f"Đã ghi nhớ: {key} = {value}"
            except Exception as e:
                logger.warning(f"Memory Manager failed: {e}, using direct save")
                await _semantic_memory.store_user_fact_upsert(
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


@tool(description="""
Lấy thông tin đã lưu về người dùng.
Gọi khi cần biết tên hoặc thông tin user để cá nhân hóa câu trả lời.
""")
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


# =============================================================================
# PHASE 10: EXPLICIT MEMORY CONTROL TOOLS
# =============================================================================

@tool(description="""
Lưu một thông tin quan trọng mà người dùng YÊU CẦU ghi nhớ.
Chỉ gọi khi user nói rõ: "hãy nhớ", "ghi nhớ", "remember", "lưu lại".
Ví dụ: "Hãy nhớ rằng tôi đang học STCW" → gọi tool này.
""")
async def tool_remember(information: str, category: str = "general") -> str:
    """
    Explicitly save information user asked to remember.
    
    Args:
        information: The information to remember
        category: Category (general, learning, preference, goal)
    """
    global _user_cache, _semantic_memory
    
    try:
        logger.info(f"[TOOL] Remember: '{information}' (category={category})")
        
        user_id = "current_user"
        
        # Save to cache
        if user_id not in _user_cache:
            _user_cache[user_id] = {}
        
        if "memories" not in _user_cache[user_id]:
            _user_cache[user_id]["memories"] = []
        
        memory_entry = {
            "content": information,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "explicit": True  # User explicitly asked to remember
        }
        
        _user_cache[user_id]["memories"].append(memory_entry)
        
        # Also save to semantic memory if available
        if _semantic_memory:
            try:
                await _semantic_memory.store_insight(
                    user_id=user_id,
                    insight=f"[EXPLICIT MEMORY] {information}",
                    category=category
                )
            except Exception as e:
                logger.warning(f"Semantic memory storage failed: {e}")
        
        return f"✅ Đã ghi nhớ: '{information}'"
        
    except Exception as e:
        logger.error(f"Remember error: {e}")
        return f"Lỗi khi ghi nhớ: {str(e)}"


@tool(description="""
Xóa/quên một thông tin cụ thể mà người dùng yêu cầu.
Gọi khi user nói: "quên đi", "xóa", "đừng nhớ", "forget", "delete".
Ví dụ: "Quên đi thông tin về sở thích của tôi" → gọi tool này.
""")
async def tool_forget(information_keyword: str) -> str:
    """
    Explicitly forget/delete information user asked to remove.
    
    Args:
        information_keyword: Keyword to match and delete
    """
    global _user_cache, _semantic_memory
    
    try:
        logger.info(f"[TOOL] Forget: '{information_keyword}'")
        
        user_id = "current_user"
        deleted_count = 0
        
        # Remove from cache
        if user_id in _user_cache:
            # Remove from memories list
            if "memories" in _user_cache[user_id]:
                original_len = len(_user_cache[user_id]["memories"])
                _user_cache[user_id]["memories"] = [
                    m for m in _user_cache[user_id]["memories"]
                    if information_keyword.lower() not in m.get("content", "").lower()
                ]
                deleted_count += original_len - len(_user_cache[user_id]["memories"])
            
            # Remove from direct keys
            keys_to_delete = [
                k for k in _user_cache[user_id] 
                if k != "memories" and information_keyword.lower() in str(_user_cache[user_id][k]).lower()
            ]
            for key in keys_to_delete:
                del _user_cache[user_id][key]
                deleted_count += 1
        
        # Also try to remove from semantic memory
        if _semantic_memory and hasattr(_semantic_memory, 'delete_memory'):
            try:
                await _semantic_memory.delete_memory(
                    user_id=user_id,
                    keyword=information_keyword
                )
            except Exception as e:
                logger.warning(f"Semantic memory deletion failed: {e}")
        
        if deleted_count > 0:
            return f"✅ Đã xóa {deleted_count} thông tin liên quan đến '{information_keyword}'"
        else:
            return f"Không tìm thấy thông tin về '{information_keyword}' để xóa."
        
    except Exception as e:
        logger.error(f"Forget error: {e}")
        return f"Lỗi khi xóa: {str(e)}"


@tool(description="""
Liệt kê tất cả thông tin mà AI đang nhớ về người dùng.
Gọi khi user hỏi: "bạn nhớ gì về tôi?", "xem memory", "list memories", "thông tin của tôi".
""")
async def tool_list_memories() -> str:
    """
    List all memories/information saved about the user.
    Provides transparency about what AI knows.
    """
    global _user_cache, _semantic_memory
    
    try:
        logger.info("[TOOL] List Memories")
        
        user_id = "current_user"
        result_parts = []
        
        # Get from cache
        if user_id in _user_cache:
            user_data = _user_cache[user_id]
            
            # Direct facts
            direct_facts = {k: v for k, v in user_data.items() if k != "memories"}
            if direct_facts:
                result_parts.append("**Thông tin cơ bản:**")
                for key, value in direct_facts.items():
                    result_parts.append(f"  - {key}: {value}")
            
            # Explicit memories
            memories = user_data.get("memories", [])
            if memories:
                result_parts.append("\n**Điều bạn yêu cầu tôi nhớ:**")
                for m in memories[-10:]:  # Last 10
                    result_parts.append(f"  - {m.get('content', '')} ({m.get('category', 'general')})")
        
        # Also get from semantic memory
        if _semantic_memory:
            try:
                context = await _semantic_memory.retrieve_context(
                    user_id=user_id,
                    query="user information preferences goals",
                    include_user_facts=True
                )
                if context.user_facts:
                    result_parts.append("\n**Insights từ hội thoại:**")
                    for fact in context.user_facts[:5]:
                        result_parts.append(f"  - {fact}")
            except Exception as e:
                logger.warning(f"Semantic memory retrieval failed: {e}")
        
        if result_parts:
            return "\n".join(result_parts)
        else:
            return "Tôi chưa lưu thông tin gì về bạn. Bạn có thể nói 'Hãy nhớ rằng...' để tôi ghi nhớ."
        
    except Exception as e:
        logger.error(f"List memories error: {e}")
        return f"Lỗi khi liệt kê: {str(e)}"


@tool(description="""
Xóa TẤT CẢ thông tin về người dùng (factory reset).
CHỈ gọi khi user nói rõ ràng: "xóa hết dữ liệu", "xóa tất cả", "reset", "clear all".
CẢNH BÁO: Hành động này không thể hoàn tác!
""")
async def tool_clear_all_memories() -> str:
    """
    Delete ALL user data. Requires explicit confirmation.
    """
    global _user_cache
    
    try:
        logger.info("[TOOL] Clear All Memories (DANGEROUS)")
        
        user_id = "current_user"
        
        # Clear cache
        if user_id in _user_cache:
            _user_cache[user_id] = {}
        
        return "⚠️ Đã xóa tất cả thông tin của bạn. AI sẽ bắt đầu từ đầu."
        
    except Exception as e:
        logger.error(f"Clear all error: {e}")
        return f"Lỗi: {str(e)}"


# =============================================================================
# REGISTER TOOLS
# =============================================================================

def register_memory_tools():
    """Register all memory tools with the registry."""
    registry = get_tool_registry()
    
    # Basic memory tools
    registry.register(
        tool=tool_save_user_info,
        category=ToolCategory.MEMORY,
        access=ToolAccess.WRITE,
        description="Save user information (name, background, etc.)"
    )
    
    registry.register(
        tool=tool_get_user_info,
        category=ToolCategory.MEMORY,
        access=ToolAccess.READ,
        description="Get saved user information"
    )
    
    # Phase 10: Explicit memory control
    registry.register(
        tool=tool_remember,
        category=ToolCategory.MEMORY_CONTROL,
        access=ToolAccess.WRITE,
        description="Explicitly remember information user requested"
    )
    
    registry.register(
        tool=tool_forget,
        category=ToolCategory.MEMORY_CONTROL,
        access=ToolAccess.WRITE,
        description="Forget/delete information user requested"
    )
    
    registry.register(
        tool=tool_list_memories,
        category=ToolCategory.MEMORY_CONTROL,
        access=ToolAccess.READ,
        description="List all memories about the user"
    )
    
    registry.register(
        tool=tool_clear_all_memories,
        category=ToolCategory.MEMORY_CONTROL,
        access=ToolAccess.WRITE,
        description="Clear all user data (factory reset)"
    )
    
    logger.info("Memory tools registered (6 tools)")


# Auto-register on import
register_memory_tools()
