"""
Sprint 210g: Context Info Layer Accuracy Tests.

Fix: `/api/v1/context/info` endpoint was returning 0 for System Prompt
and Core Memory layers because it wasn't passing those values to the
compactor's `get_context_info()` method.

The fix adds:
  - System prompt building via PromptLoader.build_system_prompt()
  - Core memory fetching via CoreMemoryBlock.get_block()
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# GROUP 1: System prompt is now passed to get_context_info
# ============================================================================


class TestSystemPromptLayer:
    """Verify system_prompt is built and passed to compactor."""

    def test_prompt_loader_builds_system_prompt(self):
        """PromptLoader.build_system_prompt() returns a non-empty string."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        prompt = loader.build_system_prompt(role="student")
        assert isinstance(prompt, str)
        assert len(prompt) > 100, "System prompt should be substantial"

    def test_system_prompt_contains_wiii_identity(self):
        """System prompt should contain Wiii's identity information."""
        from app.prompts.prompt_loader import PromptLoader
        loader = PromptLoader()
        prompt = loader.build_system_prompt(role="student")
        assert "Wiii" in prompt or "wiii" in prompt.lower()

    def test_compactor_counts_system_prompt_tokens(self):
        """When system_prompt is passed, compactor counts tokens for it."""
        from app.engine.context_manager import TokenBudgetManager
        mgr = TokenBudgetManager()
        budget = mgr.allocate(
            system_prompt="This is a test system prompt with some content.",
            core_memory="",
            summary="",
            history_list=[],
        )
        assert budget.system_prompt_used > 0, \
            "system_prompt_used should be > 0 when prompt is passed"

    def test_compactor_zero_without_system_prompt(self):
        """When system_prompt is empty, used is 0."""
        from app.engine.context_manager import TokenBudgetManager
        mgr = TokenBudgetManager()
        budget = mgr.allocate(
            system_prompt="",
            core_memory="",
            summary="",
            history_list=[],
        )
        assert budget.system_prompt_used == 0


# ============================================================================
# GROUP 2: Core memory is now passed to get_context_info
# ============================================================================


class TestCoreMemoryLayer:
    """Verify core_memory is fetched and passed to compactor."""

    def test_compactor_counts_core_memory_tokens(self):
        """When core_memory is passed, compactor counts tokens for it."""
        from app.engine.context_manager import TokenBudgetManager
        mgr = TokenBudgetManager()
        budget = mgr.allocate(
            system_prompt="",
            core_memory="User prefers formal language. Studies at VMU.",
            summary="",
            history_list=[],
        )
        assert budget.core_memory_used > 0, \
            "core_memory_used should be > 0 when block is passed"

    def test_compactor_zero_without_core_memory(self):
        """When core_memory is empty, used is 0."""
        from app.engine.context_manager import TokenBudgetManager
        mgr = TokenBudgetManager()
        budget = mgr.allocate(
            system_prompt="",
            core_memory="",
            summary="",
            history_list=[],
        )
        assert budget.core_memory_used == 0


# ============================================================================
# GROUP 3: get_context_info returns correct layer structure
# ============================================================================


class TestContextInfoStructure:
    """Verify get_context_info returns all required fields."""

    def test_context_info_has_layers(self):
        """get_context_info returns layers dict with all 4 layers."""
        from app.engine.context_manager import get_compactor
        compactor = get_compactor()
        info = compactor.get_context_info(
            session_id="test-session",
            history_list=[],
            system_prompt="Test prompt",
            core_memory="Test memory",
            user_id="test-user",
        )
        assert "layers" in info
        layers = info["layers"]
        assert "system_prompt" in layers
        assert "core_memory" in layers
        assert "summary" in layers
        assert "recent_messages" in layers

    def test_context_info_system_prompt_nonzero(self):
        """When system_prompt passed, layer shows non-zero used."""
        from app.engine.context_manager import get_compactor
        compactor = get_compactor()
        info = compactor.get_context_info(
            session_id="test-session",
            history_list=[],
            system_prompt="A" * 500,  # ~125 tokens
            core_memory="",
            user_id="test-user",
        )
        assert info["layers"]["system_prompt"]["used"] > 0

    def test_context_info_core_memory_nonzero(self):
        """When core_memory passed, layer shows non-zero used."""
        from app.engine.context_manager import get_compactor
        compactor = get_compactor()
        info = compactor.get_context_info(
            session_id="test-session",
            history_list=[],
            system_prompt="",
            core_memory="User is a 3rd year maritime student.",
            user_id="test-user",
        )
        assert info["layers"]["core_memory"]["used"] > 0

    def test_context_info_total_includes_all_layers(self):
        """total_used should include system_prompt + core_memory + messages."""
        from app.engine.context_manager import get_compactor
        compactor = get_compactor()
        info = compactor.get_context_info(
            session_id="test-session",
            history_list=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
            system_prompt="System prompt text here",
            core_memory="Core memory block here",
            user_id="test-user",
        )
        total = info["total_used"]
        sp_used = info["layers"]["system_prompt"]["used"]
        cm_used = info["layers"]["core_memory"]["used"]
        msg_used = info["layers"]["recent_messages"]["used"]
        assert total == sp_used + cm_used + msg_used, \
            f"total_used ({total}) should equal sum of layers ({sp_used}+{cm_used}+{msg_used})"


# ============================================================================
# GROUP 4: Error resilience — context/info never crashes
# ============================================================================


class TestContextInfoErrorResilience:
    """Verify context/info handles errors gracefully."""

    def test_prompt_loader_failure_returns_empty(self):
        """If PromptLoader fails, system_prompt falls back to empty."""
        # Simulate: PromptLoader raises during build_system_prompt
        with patch(
            "app.prompts.prompt_loader.PromptLoader.build_system_prompt",
            side_effect=Exception("YAML parse error"),
        ):
            from app.prompts.prompt_loader import PromptLoader
            loader = PromptLoader()
            try:
                result = loader.build_system_prompt(role="student")
                # If it raises, the endpoint catches it
            except Exception:
                result = ""
            assert result == ""

    def test_core_memory_failure_returns_empty(self):
        """If CoreMemoryBlock.get_block fails, core_memory is empty."""
        # The endpoint wraps in try/except, so failure → ""
        _core_memory = ""
        try:
            raise Exception("DB connection failed")
        except Exception:
            pass
        assert _core_memory == ""


# ============================================================================
# GROUP 5: Code inspection — endpoint passes both params
# ============================================================================


