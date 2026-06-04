"""
Tests for Sprint 52: Memory Tools coverage.

Tests memory tools including ContextVar state management:
- MemoryToolState dataclass
- _get_state, init_memory_tools, set_current_user, get_user_cache
- tool_save_user_info (with/without semantic memory, dedup, error)
- tool_get_user_info (all/key, cache/semantic, error)
- tool_remember (cache, semantic, error)
- tool_forget (cache, semantic, error)
- tool_list_memories (cache, semantic, empty)
- tool_clear_all_memories (cache, semantic, error)
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import unicodedata


# ============================================================================
# Helpers
# ============================================================================


def _reset_module_state():
    """Reset module-level state for clean tests."""
    import app.engine.tools.memory_tools as mod
    mod._semantic_memory = None
    # Reset ContextVar by setting None
    mod._memory_tool_state.set(None)


def _plain(text: str) -> str:
    """Return lowercase text without Vietnamese accents for stable assertions."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    ).lower()


# ============================================================================
# MemoryToolState and state management
# ============================================================================


class TestMemoryToolState:
    """Test state dataclass and accessors."""

    def setup_method(self):
        _reset_module_state()

    def test_defaults(self):
        from app.engine.tools.memory_tools import MemoryToolState
        state = MemoryToolState()
        assert state.user_id == "current_user"
        assert state.user_cache == {}

    def test_get_state_creates_new(self):
        from app.engine.tools.memory_tools import _get_state
        state = _get_state()
        assert state.user_id == "current_user"

    def test_get_state_returns_same(self):
        from app.engine.tools.memory_tools import _get_state
        s1 = _get_state()
        s2 = _get_state()
        assert s1 is s2


class TestInitMemoryTools:
    """Test init_memory_tools."""

    def setup_method(self):
        _reset_module_state()

    def test_sets_semantic_memory(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mod.init_memory_tools(mock_engine)
        assert mod._semantic_memory is mock_engine

    def test_sets_user_id(self):
        import app.engine.tools.memory_tools as mod
        mod.init_memory_tools(MagicMock(), user_id="user-123")
        state = mod._get_state()
        assert state.user_id == "user-123"

    def test_resets_cache_when_user_changes(self):
        import app.engine.tools.memory_tools as mod
        mod.init_memory_tools(MagicMock(), user_id="user-a")
        mod._get_state().user_cache["name"] = "Alice"

        mod.init_memory_tools(MagicMock(), user_id="user-b")
        state = mod._get_state()

        assert state.user_id == "user-b"
        assert state.user_cache == {}

    def test_preserves_cache_for_same_user(self):
        import app.engine.tools.memory_tools as mod
        engine = MagicMock()
        mod.init_memory_tools(engine, user_id="user-a")
        mod._get_state().user_cache["name"] = "Alice"

        mod.init_memory_tools(engine, user_id="user-a")

        assert mod._get_state().user_cache["name"] == "Alice"

    def test_no_user_id(self):
        import app.engine.tools.memory_tools as mod
        mod.init_memory_tools(MagicMock())
        state = mod._get_state()
        assert state.user_id == "current_user"


class TestSetCurrentUser:
    """Test set_current_user."""

    def setup_method(self):
        _reset_module_state()

    def test_sets_user(self):
        from app.engine.tools.memory_tools import set_current_user, _get_state
        set_current_user("user-456")
        assert _get_state().user_id == "user-456"

    def test_set_current_user_resets_previous_cache(self):
        from app.engine.tools.memory_tools import set_current_user, _get_state

        set_current_user("user-a")
        _get_state().user_cache["name"] = "Alice"
        set_current_user("user-b")

        assert _get_state().user_id == "user-b"
        assert _get_state().user_cache == {}

    def test_runtime_context_identity_isolates_cache(self):
        from app.engine.tools.memory_tools import _get_state
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )

        ctx_a = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="session-a",
        )
        ctx_b = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-b",
            session_id="session-a",
        )

        with tool_runtime_scope(ctx_a):
            _get_state().user_cache["name"] = "Alice"
            assert _get_state().user_cache["name"] == "Alice"

        with tool_runtime_scope(ctx_b):
            assert _get_state().user_cache == {}
            _get_state().user_cache["name"] = "Bob"

        with tool_runtime_scope(ctx_a):
            assert _get_state().user_cache == {}


class TestGetUserCache:
    """Test get_user_cache."""

    def setup_method(self):
        _reset_module_state()

    def test_returns_cache(self):
        from app.engine.tools.memory_tools import get_user_cache, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        assert get_user_cache()["name"] == "Minh"


# ============================================================================
# tool_save_user_info
# ============================================================================


class TestToolSaveUserInfo:
    """Test save user info tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_cache_only(self):
        from app.engine.tools.memory_tools import tool_save_user_info, _get_state
        result = await tool_save_user_info.coroutine(key="name", value="Minh")
        assert "cache only" in result
        assert _get_state().user_cache["name"] == "Minh"

    @pytest.mark.asyncio
    async def test_with_semantic_memory_success(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.store_user_fact_upsert = AsyncMock(return_value=True)
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_save_user_info.coroutine(key="name", value="Minh")
        assert "ghi nho" in _plain(result)
        mock_engine.store_user_fact_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_semantic_memory_failure(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.store_user_fact_upsert = AsyncMock(return_value=False)
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_save_user_info.coroutine(key="name", value="Minh")
        assert "khong luu" in _plain(result)

    @pytest.mark.asyncio
    async def test_error(self):
        import app.engine.tools.memory_tools as mod
        # Force error by making _get_state raise
        mod._memory_tool_state.set(None)
        with patch("app.engine.tools.memory_tools._get_state", side_effect=Exception("State error")):
            result = await mod.tool_save_user_info.coroutine(key="name", value="Minh")
            assert "loi" in _plain(result)


# ============================================================================
# tool_get_user_info
# ============================================================================


class TestToolGetUserInfo:
    """Test get user info tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_all_empty(self):
        from app.engine.tools.memory_tools import tool_get_user_info
        result = await tool_get_user_info.coroutine(key="all")
        assert "chua co" in _plain(result)

    @pytest.mark.asyncio
    async def test_all_from_cache(self):
        from app.engine.tools.memory_tools import tool_get_user_info, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        result = await tool_get_user_info.coroutine(key="all")
        assert "Minh" in result

    @pytest.mark.asyncio
    async def test_specific_key(self):
        from app.engine.tools.memory_tools import tool_get_user_info, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        result = await tool_get_user_info.coroutine(key="name")
        assert "Minh" in result

    @pytest.mark.asyncio
    async def test_key_not_found(self):
        from app.engine.tools.memory_tools import tool_get_user_info
        result = await tool_get_user_info.coroutine(key="school")
        assert "chua co" in _plain(result)

    @pytest.mark.asyncio
    async def test_fetches_from_semantic(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.get_user_facts = AsyncMock(return_value={"name": "Minh"})
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_get_user_info.coroutine(key="all")
        assert "Minh" in result

    @pytest.mark.asyncio
    async def test_semantic_error(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.get_user_facts = AsyncMock(side_effect=Exception("DB error"))
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_get_user_info.coroutine(key="all")
        assert "chua co" in _plain(result)


# ============================================================================
# tool_remember
# ============================================================================


class TestToolRemember:
    """Test remember tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_cache_only(self):
        from app.engine.tools.memory_tools import tool_remember, _get_state
        result = await tool_remember.coroutine(information="I study STCW")
        assert "ghi nho" in _plain(result)
        assert len(_get_state().user_cache.get("memories", [])) == 1

    @pytest.mark.asyncio
    async def test_with_semantic_memory(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.store_explicit_insight = AsyncMock()
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_remember.coroutine(information="I study STCW", category="learning")
        assert "ghi nho" in _plain(result)
        mock_engine.store_explicit_insight.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_error_falls_back(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.store_explicit_insight = AsyncMock(side_effect=Exception("DB error"))
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_remember.coroutine(information="I study STCW")
        assert "cache" in result.lower()


# ============================================================================
# tool_forget
# ============================================================================


class TestToolForget:
    """Test forget tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_nothing_to_forget(self):
        from app.engine.tools.memory_tools import tool_forget
        result = await tool_forget.coroutine(information_keyword="nonexistent")
        assert "khong tim thay" in _plain(result)

    @pytest.mark.asyncio
    async def test_forgets_from_memories_cache(self):
        from app.engine.tools.memory_tools import tool_forget, _get_state
        state = _get_state()
        state.user_cache["memories"] = [
            {"content": "I study STCW", "category": "learning"},
            {"content": "I like reading", "category": "preference"},
        ]
        result = await tool_forget.coroutine(information_keyword="STCW")
        assert "xoa" in _plain(result)
        assert len(state.user_cache["memories"]) == 1

    @pytest.mark.asyncio
    async def test_forgets_from_direct_keys(self):
        from app.engine.tools.memory_tools import tool_forget, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        result = await tool_forget.coroutine(information_keyword="Minh")
        assert "xoa" in _plain(result)
        assert "name" not in state.user_cache

    @pytest.mark.asyncio
    async def test_forgets_from_semantic(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.delete_memory_by_keyword = AsyncMock(return_value=2)
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_forget.coroutine(information_keyword="STCW")
        assert "xoa" in _plain(result)
        assert "2" in result


# ============================================================================
# tool_list_memories
# ============================================================================


class TestToolListMemories:
    """Test list memories tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_empty(self):
        from app.engine.tools.memory_tools import tool_list_memories
        result = await tool_list_memories.coroutine()
        assert "chua" in _plain(result)

    @pytest.mark.asyncio
    async def test_with_direct_facts(self):
        from app.engine.tools.memory_tools import tool_list_memories, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        result = await tool_list_memories.coroutine()
        assert "Minh" in result

    @pytest.mark.asyncio
    async def test_with_explicit_memories(self):
        from app.engine.tools.memory_tools import tool_list_memories, _get_state
        state = _get_state()
        state.user_cache["memories"] = [
            {"content": "I study STCW", "category": "learning"},
        ]
        result = await tool_list_memories.coroutine()
        assert "STCW" in result

    @pytest.mark.asyncio
    async def test_with_semantic_memory(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.get_user_facts = AsyncMock(return_value={"name": "Minh"})
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_list_memories.coroutine()
        assert "Minh" in result


# ============================================================================
# tool_clear_all_memories
# ============================================================================


class TestToolClearAllMemories:
    """Test clear all memories tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_cache_only(self):
        from app.engine.tools.memory_tools import tool_clear_all_memories, _get_state
        state = _get_state()
        state.user_cache["name"] = "Minh"
        result = await tool_clear_all_memories.coroutine()
        assert "xoa" in _plain(result)
        assert len(state.user_cache) == 0

    @pytest.mark.asyncio
    async def test_with_semantic_memory(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.delete_all_user_memories = AsyncMock(return_value=5)
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_clear_all_memories.coroutine()
        assert "5" in result
        mock_engine.delete_all_user_memories.assert_called_once()

    @pytest.mark.asyncio
    async def test_semantic_error(self):
        import app.engine.tools.memory_tools as mod
        mock_engine = MagicMock()
        mock_engine.delete_all_user_memories = AsyncMock(side_effect=Exception("DB error"))
        mod._semantic_memory = mock_engine
        mod._memory_tool_state.set(None)

        result = await mod.tool_clear_all_memories.coroutine()
        assert "xoa" in _plain(result)
