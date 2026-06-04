"""
Memory Tools - User Memory Management for Wiii

Category: MEMORY (User data storage)
Access: Mixed (READ and WRITE)

Sprint 26: Migrated from module-level globals to contextvars for
async-safe per-request state isolation. Fixed all tool implementations
to actually use SemanticMemoryEngine for persistent storage.

Includes:
- Basic memory tools (save/get user info)
- Phase 10: Explicit memory control (remember/forget/list/clear)
"""

import contextvars
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Any

from app.engine.tools.native_tool import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# ASYNC-SAFE STATE (contextvars for per-request isolation)
# Sprint 26: Replaces unsafe module-level globals
# =============================================================================

@dataclass
class MemoryToolState:
    """Per-request state for memory tools. Isolated between concurrent requests."""
    user_id: str = "current_user"
    user_cache: Dict[str, Any] = field(default_factory=dict)
    identity_key: Optional[str] = None


# ContextVar: each async request gets its own MemoryToolState
_memory_tool_state: contextvars.ContextVar[Optional[MemoryToolState]] = contextvars.ContextVar(
    '_memory_tool_state', default=None
)

# Semantic memory engine is a singleton (shared across requests) - safe as module-level
_semantic_memory = None


def _tool_identity(user_id: Optional[str] = None) -> tuple[str, str, bool]:
    """Resolve the current tool identity without exposing raw metadata in logs."""
    runtime_user_id = None
    runtime_org_id = ""
    runtime_session_id = ""
    identity_available = bool(user_id)

    try:
        from app.engine.tools.runtime_context import get_current_tool_runtime_context

        runtime = get_current_tool_runtime_context()
        if runtime:
            runtime_user_id = runtime.user_id
            runtime_org_id = str(runtime.organization_id or "").strip()
            runtime_session_id = str(runtime.session_id or "").strip()
            identity_available = identity_available or bool(
                runtime_user_id or runtime_org_id or runtime_session_id
            )
    except Exception:
        pass

    if not runtime_org_id:
        try:
            from app.core.org_context import get_current_org_id

            runtime_org_id = str(get_current_org_id() or "").strip()
            identity_available = identity_available or bool(runtime_org_id)
        except Exception:
            pass

    resolved_user_id = str(user_id or runtime_user_id or "current_user").strip() or "current_user"
    identity_key = (
        f"user={resolved_user_id}|org={runtime_org_id}|session={runtime_session_id}"
    )
    return identity_key, resolved_user_id, identity_available


def _new_state(user_id: Optional[str] = None) -> MemoryToolState:
    identity_key, resolved_user_id, _ = _tool_identity(user_id)
    return MemoryToolState(user_id=resolved_user_id, identity_key=identity_key)


def _get_state(user_id: Optional[str] = None) -> MemoryToolState:
    """Get or create identity-scoped memory tool state."""
    identity_key, resolved_user_id, identity_available = _tool_identity(user_id)
    state = _memory_tool_state.get(None)
    if state is None:
        state = _new_state(user_id)
        _memory_tool_state.set(state)
    elif identity_available and state.identity_key != identity_key:
        state = _new_state(user_id)
        _memory_tool_state.set(state)
    elif state.identity_key is None:
        state.identity_key = identity_key
        state.user_id = resolved_user_id
    return state


def init_memory_tools(semantic_memory, user_id: Optional[str] = None):
    """Initialize memory tools with semantic memory engine."""
    global _semantic_memory
    _semantic_memory = semantic_memory
    if user_id:
        _get_state(user_id)
    logger.info("Memory tools initialized (user_id=%s)", user_id)


def set_current_user(user_id: str):
    """Set the current user ID for memory operations (per-request)."""
    _get_state(user_id)


def get_user_cache() -> Dict[str, Any]:
    """Get the user cache for external access (per-request)."""
    return _get_state().user_cache


def _strip_memory_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Keep user-facing memory tools from exposing internal timestamp helper keys."""
    return {
        key: value
        for key, value in (data or {}).items()
        if not str(key).endswith("__updated_at")
    }


# =============================================================================
# BASIC MEMORY TOOLS
# =============================================================================

@tool(description="""
Luu thong tin ca nhan cua nguoi dung khi ho gioi thieu ban than.
Goi khi user noi ten, nghe nghiep, truong hoc.
""")
async def tool_save_user_info(key: str, value: str) -> str:
    """
    Save user personal information with semantic dedup.

    Uses store_user_fact_upsert() which handles:
    - Semantic duplicate detection via embedding similarity
    - Type-based fallback matching
    - Automatic upsert (update existing or insert new)
    - Memory cap enforcement (FIFO eviction at 50)
    """
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] Save User Info: %s=%s for user %s", key, value, user_id)

        # Update per-request cache
        state.user_cache[key] = value

        # Map key to fact_type
        fact_type_map = {
            "name": "name", "ten": "name",
            "job": "role", "nghe": "role",
            "school": "organization", "truong": "organization",
            "background": "role",
            "goal": "goal", "muc tieu": "goal",
            "interest": "interest", "quan tam": "interest",
            "weakness": "weakness", "yeu": "weakness",
            "hobby": "hobby", "preference": "preference",
        }
        fact_type = fact_type_map.get(key.lower(), "preference")
        fact_content = f"{key}: {value}"

        if _semantic_memory:
            success = await _semantic_memory.store_user_fact_upsert(
                user_id=user_id,
                fact_content=fact_content,
                fact_type=fact_type,
                confidence=0.95
            )
            if success:
                return f"Da ghi nho: {key} = {value}"
            return f"Khong luu duoc: {key} = {value}"

        return f"Da ghi nho (cache only): {key} = {value}"

    except Exception as e:
        logger.error("Save user info error: %s", e)
        return f"Lỗi khi lưu thông tin: {str(e)}"


@tool(description="""
Lay thong tin da luu ve nguoi dung.
Goi khi can biet ten hoac thong tin user de ca nhan hoa cau tra loi.
""")
async def tool_get_user_info(key: str = "all") -> str:
    """Get saved user information."""
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] Get User Info: %s for user %s", key, user_id)

        user_data = dict(state.user_cache)

        # Fetch from semantic memory if cache is empty
        if not user_data and _semantic_memory:
            try:
                facts = await _semantic_memory.get_user_facts(user_id=user_id)
                if facts:
                    user_data.update(_strip_memory_metadata(facts))
                    # Also populate cache for subsequent calls
                    state.user_cache.update(_strip_memory_metadata(facts))
            except Exception as e:
                logger.warning("Semantic memory retrieval failed: %s", e)

        if key == "all":
            return f"Thong tin user: {_strip_memory_metadata(user_data)}" if user_data else "Chua co thong tin user."
        else:
            value = user_data.get(key)
            return f"{key}: {value}" if value else f"Chua co thong tin ve {key}."

    except Exception as e:
        logger.error("Get user info error: %s", e)
        return f"Lỗi khi lấy thông tin: {str(e)}"


# =============================================================================
# PHASE 10: EXPLICIT MEMORY CONTROL TOOLS
# =============================================================================

@tool(description="""
Luu mot thong tin quan trong ma nguoi dung YEU CAU ghi nho.
Chi goi khi user noi ro: "hay nho", "ghi nho", "remember", "luu lai".
Vi du: "Hay nho rang toi dang hoc STCW" -> goi tool nay.
""")
async def tool_remember(information: str, category: str = "general") -> str:
    """
    Explicitly save information user asked to remember.

    Sprint 26 FIX: Now calls store_explicit_insight() which actually
    persists to PostgreSQL, instead of the non-existent store_insight().

    Args:
        information: The information to remember
        category: Category (general, learning, preference, goal)
    """
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] Remember: '%s' (category=%s)", information, category)

        # Save to per-request cache
        if "memories" not in state.user_cache:
            state.user_cache["memories"] = []

        memory_entry = {
            "content": information,
            "category": category,
            "timestamp": datetime.now().isoformat(),
            "explicit": True
        }
        state.user_cache["memories"].append(memory_entry)

        # Persist to semantic memory
        if _semantic_memory:
            try:
                # Map category string to InsightCategory
                category_map = {
                    "general": "preference",
                    "learning": "knowledge_gap",
                    "preference": "preference",
                    "goal": "goal_evolution",
                    "habit": "habit",
                }
                insight_category = category_map.get(category, "preference")

                await _semantic_memory.store_explicit_insight(
                    user_id=user_id,
                    insight_text=f"[EXPLICIT MEMORY] {information}",
                    category=insight_category
                )
                return f"Da ghi nho: '{information}'"
            except Exception as e:
                logger.warning("Semantic memory storage failed: %s", e)
                return f"Da ghi nho (cache): '{information}'"

        return f"Da ghi nho (cache only): '{information}'"

    except Exception as e:
        logger.error("Remember error: %s", e)
        return f"Lỗi khi ghi nhớ: {str(e)}"


@tool(description="""
Xoa/quen mot thong tin cu the ma nguoi dung yeu cau.
Goi khi user noi: "quen di", "xoa", "dung nho", "forget", "delete".
Vi du: "Quen di thong tin ve so thich cua toi" -> goi tool nay.
""")
async def tool_forget(information_keyword: str) -> str:
    """
    Explicitly forget/delete information user asked to remove.

    Sprint 26 FIX: Now calls delete_memory_by_keyword() which actually
    deletes from PostgreSQL, instead of checking for non-existent method.

    Args:
        information_keyword: Keyword to match and delete
    """
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] Forget: '%s' for user %s", information_keyword, user_id)

        deleted_count = 0

        # Remove from per-request cache
        if "memories" in state.user_cache:
            original_len = len(state.user_cache["memories"])
            state.user_cache["memories"] = [
                m for m in state.user_cache["memories"]
                if information_keyword.lower() not in m.get("content", "").lower()
            ]
            deleted_count += original_len - len(state.user_cache["memories"])

        # Remove from direct keys
        keys_to_delete = [
            k for k in state.user_cache
            if k != "memories" and information_keyword.lower() in str(state.user_cache[k]).lower()
        ]
        for key in keys_to_delete:
            del state.user_cache[key]
            deleted_count += 1

        # Delete from semantic memory (persistent storage)
        if _semantic_memory:
            try:
                semantic_deleted = await _semantic_memory.delete_memory_by_keyword(
                    user_id=user_id,
                    keyword=information_keyword
                )
                deleted_count += semantic_deleted
            except Exception as e:
                logger.warning("Semantic memory deletion failed: %s", e)

        if deleted_count > 0:
            return f"Da xoa {deleted_count} thong tin lien quan den '{information_keyword}'"
        else:
            return f"Khong tim thay thong tin ve '{information_keyword}' de xoa."

    except Exception as e:
        logger.error("Forget error: %s", e)
        return f"Lỗi khi xóa: {str(e)}"


@tool(description="""
Liet ke tat ca thong tin ma AI dang nho ve nguoi dung.
Goi khi user hoi: "ban nho gi ve toi?", "xem memory", "list memories", "thong tin cua toi".
""")
async def tool_list_memories() -> str:
    """
    List all memories/information saved about the user.
    Provides transparency about what AI knows.

    Sprint 26 FIX: Correctly handles SemanticMemorySearchResult objects
    by extracting .content attribute instead of calling str() on them.
    """
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] List Memories for user %s", user_id)

        result_parts = []

        # Get from per-request cache
        direct_facts = {k: v for k, v in state.user_cache.items() if k != "memories"}
        if direct_facts:
            result_parts.append("**Thong tin co ban:**")
            for key, value in direct_facts.items():
                result_parts.append(f"  - {key}: {value}")

        # Explicit memories from cache
        memories = state.user_cache.get("memories", [])
        if memories:
            result_parts.append("\n**Dieu ban yeu cau toi nho:**")
            for m in memories[-10:]:
                result_parts.append(f"  - {m.get('content', '')} ({m.get('category', 'general')})")

        # Get from semantic memory (persistent storage)
        if _semantic_memory:
            try:
                # Get user facts
                facts = await _semantic_memory.get_user_facts(user_id=user_id)
                if facts:
                    result_parts.append("\n**Thong tin da luu (persistent):**")
                    for fact_type, fact_value in list(_strip_memory_metadata(facts).items())[:10]:
                        result_parts.append(f"  - {fact_type}: {fact_value}")
            except Exception as e:
                logger.warning("Semantic memory retrieval failed: %s", e)

        if result_parts:
            return "\n".join(result_parts)
        else:
            return "Toi chua luu thong tin gi ve ban. Ban co the noi 'Hay nho rang...' de toi ghi nho."

    except Exception as e:
        logger.error("List memories error: %s", e)
        return f"Lỗi khi liệt kê: {str(e)}"


@tool(description="""
Xoa TAT CA thong tin ve nguoi dung (factory reset).
CHI goi khi user noi ro rang: "xoa het du lieu", "xoa tat ca", "reset", "clear all".
CANH BAO: Hanh dong nay khong the hoan tac!
""")
async def tool_clear_all_memories() -> str:
    """
    Delete ALL user data. Requires explicit confirmation.

    Sprint 26 FIX: Now calls delete_all_user_memories() which actually
    deletes from PostgreSQL, instead of only clearing ephemeral cache.
    """
    global _semantic_memory

    try:
        state = _get_state()
        user_id = state.user_id
        logger.info("[TOOL] Clear All Memories for user %s (DANGEROUS)", user_id)

        # Clear per-request cache
        state.user_cache.clear()

        deleted_count = 0

        # Delete from semantic memory (persistent storage)
        if _semantic_memory:
            try:
                deleted_count = await _semantic_memory.delete_all_user_memories(
                    user_id=user_id
                )
            except Exception as e:
                logger.error("Semantic memory full clear failed: %s", e)

        if deleted_count > 0:
            return (
                f"Da xoa tat ca {deleted_count} thong tin cua ban. "
                f"AI se bat dau tu dau."
            )
        return "Da xoa tat ca thong tin cua ban. AI se bat dau tu dau."

    except Exception as e:
        logger.error("Clear all error: %s", e)
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

    # Sprint 26: Factory reset restricted to admin only
    registry.register(
        tool=tool_clear_all_memories,
        category=ToolCategory.MEMORY_CONTROL,
        access=ToolAccess.WRITE,
        description="Clear all user data (factory reset)",
        roles=["admin"]
    )

    logger.info("Memory tools registered (6 tools)")


# Auto-register on import
register_memory_tools()
