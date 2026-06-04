"""
Tests for Sprint 118: Block Consolidation (Letta pattern)

Tests cover:
  1. needs_consolidation — threshold detection
  2. consolidate_full_blocks — multi-block consolidation
  3. _consolidate_block_content — LLM summarization
  4. Integration: flush triggers consolidation
  5. Fail-safe behavior — errors don't break anything

NOTE: _consolidate_block_content uses lazy imports inside the function body.
      Patch at SOURCE module (e.g., app.engine.llm_pool.get_llm_light),
      NOT at consuming module.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# Patch targets — lazy imports resolved at source modules
_LLM_PATCH = "app.engine.llm_pool.get_llm_light"
_CHAR_STATE_PATCH = "app.engine.character.character_state.get_character_state_manager"


def _make_block(label="self_notes", content="", char_limit=1000, version=1):
    """Create a CharacterBlock for testing."""
    from app.engine.character.models import CharacterBlock
    return CharacterBlock(
        id=uuid4(),
        label=label,
        content=content,
        char_limit=char_limit,
        version=version,
    )


def _get_manager():
    """Get a fresh CharacterStateManager (not singleton)."""
    from app.engine.character.character_state import CharacterStateManager
    return CharacterStateManager()


def _seed_cache(manager, blocks, timestamp=1e18):
    """Seed manager cache using the runtime cache key."""
    cache_key = manager._cache_key()
    manager._cache = {cache_key: blocks}
    manager._cache_timestamp = {cache_key: timestamp}
    return cache_key


# =============================================================================
# needs_consolidation Tests
# =============================================================================


class TestNeedsConsolidation:
    """Test the threshold detection for block consolidation."""

    def test_empty_block_does_not_need_consolidation(self):
        manager = _get_manager()
        block = _make_block(content="", char_limit=1000)
        _seed_cache(manager, {"self_notes": block})  # far future = fresh cache

        assert not manager.needs_consolidation("self_notes")

    def test_block_at_50_percent_does_not_need(self):
        manager = _get_manager()
        content = "x" * 500  # 50% of 1000
        block = _make_block(content=content, char_limit=1000)
        _seed_cache(manager, {"self_notes": block})

        assert not manager.needs_consolidation("self_notes")

    def test_block_at_79_percent_does_not_need(self):
        manager = _get_manager()
        content = "x" * 790  # 79% of 1000
        block = _make_block(content=content, char_limit=1000)
        _seed_cache(manager, {"self_notes": block})

        assert not manager.needs_consolidation("self_notes")

    def test_block_at_80_percent_needs_consolidation(self):
        manager = _get_manager()
        content = "x" * 800  # 80% of 1000
        block = _make_block(content=content, char_limit=1000)
        _seed_cache(manager, {"self_notes": block})

        assert manager.needs_consolidation("self_notes")

    def test_block_at_100_percent_needs_consolidation(self):
        manager = _get_manager()
        content = "x" * 1000  # 100% of 1000
        block = _make_block(content=content, char_limit=1000)
        _seed_cache(manager, {"self_notes": block})

        assert manager.needs_consolidation("self_notes")

    def test_nonexistent_block_does_not_need(self):
        manager = _get_manager()
        _seed_cache(manager, {})

        assert not manager.needs_consolidation("nonexistent")

    def test_zero_char_limit_does_not_need(self):
        manager = _get_manager()
        block = _make_block(content="stuff", char_limit=0)
        _seed_cache(manager, {"self_notes": block})

        assert not manager.needs_consolidation("self_notes")


# =============================================================================
# _consolidate_block_content Tests
# =============================================================================


class TestConsolidateBlockContent:
    """Test the LLM-based block content consolidation."""

    @pytest.mark.asyncio
    async def test_returns_shorter_content(self):
        manager = _get_manager()
        block = _make_block(
            content="- Fact A\n- Fact B\n- Fact A (duplicate)\n- Fact C",
            char_limit=200,
        )

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "- Fact A\n- Fact B\n- Fact C"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_LLM_PATCH, return_value=mock_llm):
            result = await manager._consolidate_block_content(block)

        assert result is not None
        assert len(result) < len(block.content)
        assert "Fact A" in result

    @pytest.mark.asyncio
    async def test_returns_none_if_llm_returns_longer(self):
        """If LLM returns longer text, reject consolidation."""
        manager = _get_manager()
        block = _make_block(content="Short", char_limit=100)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "This is much longer than the original Short text"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_LLM_PATCH, return_value=mock_llm):
            result = await manager._consolidate_block_content(block)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_llm_returns_empty(self):
        manager = _get_manager()
        block = _make_block(content="- Fact A\n- Fact B", char_limit=100)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = ""
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_LLM_PATCH, return_value=mock_llm):
            result = await manager._consolidate_block_content(block)

        assert result is None

    @pytest.mark.asyncio
    async def test_prompt_includes_target_char_count(self):
        manager = _get_manager()
        block = _make_block(content="x" * 100, char_limit=200)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "x" * 50
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_LLM_PATCH, return_value=mock_llm):
            await manager._consolidate_block_content(block)

        # Check that prompt contains target chars (~60% of 200 = 120)
        # Phase 1 (#207): SEND-side now passes OpenAI-shaped dicts, not HumanMessage
        call_args = mock_llm.ainvoke.call_args[0][0]
        first_msg = call_args[0]
        prompt_text = first_msg["content"] if isinstance(first_msg, dict) else first_msg.content
        assert "120" in prompt_text  # 60% of 200


# =============================================================================
# consolidate_full_blocks Tests
# =============================================================================


class TestConsolidateFullBlocks:
    """Test the multi-block consolidation sweep."""

    @pytest.mark.asyncio
    async def test_consolidates_blocks_over_threshold(self):
        manager = _get_manager()
        full_block = _make_block(
            label="learned_lessons",
            content="- Lesson A\n- Lesson B (duplicate A)\n- Lesson C",
            char_limit=50,  # 50 chars, content is 49 → >80%
        )
        empty_block = _make_block(
            label="self_notes",
            content="",
            char_limit=1000,
        )
        _seed_cache(manager, {
            "learned_lessons": full_block,
            "self_notes": empty_block,
        })

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "- Lesson A\n- Lesson C"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_repo = MagicMock()
        mock_repo.update_block.return_value = _make_block(
            label="learned_lessons",
            content="- Lesson A\n- Lesson C",
            char_limit=50,
            version=2,
        )

        with patch(_LLM_PATCH, return_value=mock_llm), \
             patch.object(manager, "_get_repo", return_value=mock_repo):
            count = await manager.consolidate_full_blocks()

        assert count == 1
        mock_repo.update_block.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_blocks_under_threshold(self):
        manager = _get_manager()
        small_block = _make_block(
            label="self_notes",
            content="- Short note",
            char_limit=1000,  # Way under threshold
        )
        _seed_cache(manager, {"self_notes": small_block})

        with patch(_LLM_PATCH) as mock_get_llm:
            count = await manager.consolidate_full_blocks()

        assert count == 0
        mock_get_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_llm_error_per_block(self):
        """Error in one block should not affect others."""
        manager = _get_manager()
        block1 = _make_block(label="learned_lessons", content="x" * 90, char_limit=100)
        block2 = _make_block(label="self_notes", content="y" * 90, char_limit=100)
        _seed_cache(manager, {
            "learned_lessons": block1,
            "self_notes": block2,
        })

        call_count = 0

        async def side_effect(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("LLM error on first block")
            resp = MagicMock()
            resp.content = "y" * 50  # Shorter
            return resp

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=side_effect)

        mock_repo = MagicMock()
        mock_repo.update_block.return_value = _make_block(
            label="self_notes", content="y" * 50, char_limit=100, version=2,
        )

        with patch(_LLM_PATCH, return_value=mock_llm), \
             patch.object(manager, "_get_repo", return_value=mock_repo):
            count = await manager.consolidate_full_blocks()

        # First block failed, second succeeded
        assert count == 1

    @pytest.mark.asyncio
    async def test_no_blocks_returns_zero(self):
        manager = _get_manager()
        _seed_cache(manager, {})

        count = await manager.consolidate_full_blocks()
        assert count == 0


# =============================================================================
# Integration: Flush triggers consolidation
# =============================================================================


class TestFlushTriggersConsolidation:
    """Test that the flush calls consolidation after writing facts."""

    @pytest.mark.asyncio
    async def test_flush_calls_consolidate_after_writing(self):
        import json
        from app.engine.context_manager import ConversationCompactor, TokenBudgetManager

        compactor = ConversationCompactor(budget_manager=TokenBudgetManager())
        messages = [{"role": "user", "content": "test message"}]

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "facts": [{"block": "self_notes", "content": "Important note"}]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_manager = MagicMock()
        mock_manager.update_block.return_value = MagicMock()
        mock_manager.consolidate_full_blocks = AsyncMock(return_value=1)

        with patch(_LLM_PATCH, return_value=mock_llm), \
             patch(_CHAR_STATE_PATCH, return_value=mock_manager):
            await compactor._flush_memories_before_compaction(messages, user_id="u1")

        mock_manager.consolidate_full_blocks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_skips_consolidation_when_no_facts(self):
        import json
        from app.engine.context_manager import ConversationCompactor, TokenBudgetManager

        compactor = ConversationCompactor(budget_manager=TokenBudgetManager())
        messages = [{"role": "user", "content": "hello"}]

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"facts": []}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_manager = MagicMock()
        mock_manager.consolidate_full_blocks = AsyncMock(return_value=0)

        with patch(_LLM_PATCH, return_value=mock_llm), \
             patch(_CHAR_STATE_PATCH, return_value=mock_manager):
            await compactor._flush_memories_before_compaction(messages, user_id="u1")

        # No facts → consolidation should NOT be called
        mock_manager.consolidate_full_blocks.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_consolidation_failure_does_not_block_flush(self):
        import json
        from app.engine.context_manager import ConversationCompactor, TokenBudgetManager

        compactor = ConversationCompactor(budget_manager=TokenBudgetManager())
        messages = [{"role": "user", "content": "test"}]

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "facts": [{"block": "self_notes", "content": "Note"}]
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_manager = MagicMock()
        mock_manager.update_block.return_value = MagicMock()
        mock_manager.consolidate_full_blocks = AsyncMock(
            side_effect=RuntimeError("Consolidation exploded!")
        )

        with patch(_LLM_PATCH, return_value=mock_llm), \
             patch(_CHAR_STATE_PATCH, return_value=mock_manager):
            # Should NOT raise
            await compactor._flush_memories_before_compaction(messages, user_id="u1")

        # Flush still completed — update_block was called
        mock_manager.update_block.assert_called_once()


# =============================================================================
# Edge cases
# =============================================================================


class TestConsolidationEdgeCases:
    """Edge cases for block consolidation."""

    @pytest.mark.asyncio
    async def test_whitespace_only_block_not_consolidated(self):
        manager = _get_manager()
        block = _make_block(
            label="self_notes",
            content="   \n  \n   ",
            char_limit=10,  # Would be >80% if counted
        )
        _seed_cache(manager, {"self_notes": block})

        with patch(_LLM_PATCH) as mock_get_llm:
            count = await manager.consolidate_full_blocks()

        assert count == 0
        mock_get_llm.assert_not_called()

    def test_consolidation_threshold_is_080(self):
        """Verify threshold constant is 0.80."""
        manager = _get_manager()
        assert manager.CONSOLIDATION_THRESHOLD == 0.80

    def test_consolidation_target_is_060(self):
        """Verify target constant is 0.60."""
        manager = _get_manager()
        assert manager.CONSOLIDATION_TARGET == 0.60
