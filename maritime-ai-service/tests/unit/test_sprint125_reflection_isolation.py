"""
Tests for Sprint 125: Reflection Engine Per-User Isolation

Tests cover:
  1. Per-user counters — User A's count doesn't affect User B
  2. Per-user importance tracking
  3. Per-user should_reflect() evaluation
  4. reflect() passes user_id to all downstream calls
  5. _apply_updates() scopes to user
  6. trigger_character_reflection() passes user_id through
  7. get_recent_experiences() filters by user_id
  8. cleanup_old_experiences() scopes to user
  9. Backward compat — default "__global__" still works
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


# Patch targets — lazy imports in reflection_engine
_LLM_PATCH = "app.engine.llm_pool.get_llm_light"
_LLM_FOR_PROVIDER_PATCH = "app.engine.llm_pool.get_llm_for_provider"
_CHAR_STATE_PATCH = "app.engine.character.character_state.get_character_state_manager"
_CHAR_REPO_PATCH = "app.engine.character.character_repository.get_character_repository"


def _get_engine():
    """Create a fresh CharacterReflectionEngine (not singleton)."""
    from app.engine.character.reflection_engine import CharacterReflectionEngine
    return CharacterReflectionEngine()


# =============================================================================
# Per-user counters
# =============================================================================

class TestPerUserCounters:
    """Test that conversation counters are per-user."""

    def test_user_a_count_independent_of_user_b(self):
        engine = _get_engine()
        engine.increment_conversation_count(user_id="user-A")
        engine.increment_conversation_count(user_id="user-A")
        engine.increment_conversation_count(user_id="user-B")

        assert engine._conversation_counts["user-A"] == 2
        assert engine._conversation_counts["user-B"] == 1

    def test_importance_per_user(self):
        engine = _get_engine()
        engine.add_experience_importance(0.8, user_id="user-A")
        engine.add_experience_importance(0.3, user_id="user-B")

        assert engine._importance_sums["user-A"] == pytest.approx(0.8)
        assert engine._importance_sums["user-B"] == pytest.approx(0.3)

    def test_reset_only_affects_target_user(self):
        engine = _get_engine()
        engine.increment_conversation_count(user_id="user-A")
        engine.increment_conversation_count(user_id="user-B")
        engine.add_experience_importance(1.0, user_id="user-A")
        engine.add_experience_importance(1.0, user_id="user-B")

        engine.reset_counter(user_id="user-A")

        assert engine._conversation_counts["user-A"] == 0
        assert engine._importance_sums["user-A"] == 0.0
        # User B untouched
        assert engine._conversation_counts["user-B"] == 1
        assert engine._importance_sums["user-B"] == pytest.approx(1.0)

    def test_default_user_is_global(self):
        engine = _get_engine()
        count = engine.increment_conversation_count()  # no user_id
        assert count == 1
        assert engine._conversation_counts["__global__"] == 1


# =============================================================================
# should_reflect — per-user evaluation
# =============================================================================

class TestShouldReflectPerUser:
    """Test that should_reflect evaluates per-user."""

    def test_user_a_ready_user_b_not(self):
        engine = _get_engine()
        # Simulate user A hitting importance threshold
        engine.add_experience_importance(10.0, user_id="user-A")
        # User B has low importance
        engine.add_experience_importance(0.1, user_id="user-B")

        with patch.object(engine, "_is_enabled", return_value=True), \
             patch.object(engine, "_get_threshold", return_value=5.0):
            assert engine.should_reflect(user_id="user-A") is True
            assert engine.should_reflect(user_id="user-B") is False

    def test_safety_net_count_per_user(self):
        engine = _get_engine()
        # User A has 10 conversations
        for _ in range(10):
            engine.increment_conversation_count(user_id="user-A")
        # User B has 1 conversation
        engine.increment_conversation_count(user_id="user-B")

        with patch.object(engine, "_is_enabled", return_value=True), \
             patch.object(engine, "_get_threshold", return_value=100.0), \
             patch.object(engine, "_get_interval", return_value=5):
            # 2 * 5 = 10 → user A qualifies
            assert engine.should_reflect(user_id="user-A") is True
            assert engine.should_reflect(user_id="user-B") is False


# =============================================================================
# get_stats — per-user
# =============================================================================

class TestGetStatsPerUser:
    """Test that get_stats returns user-specific data."""

    def test_stats_per_user(self):
        engine = _get_engine()
        engine.increment_conversation_count(user_id="user-A")
        engine.increment_conversation_count(user_id="user-A")
        engine.add_experience_importance(2.5, user_id="user-A")

        stats_a = engine.get_stats(user_id="user-A")
        stats_b = engine.get_stats(user_id="user-B")

        assert stats_a["user_id"] == "user-A"
        assert stats_a["conversation_count"] == 2
        assert stats_a["importance_sum"] == pytest.approx(2.5)

        assert stats_b["user_id"] == "user-B"
        assert stats_b["conversation_count"] == 0
        assert stats_b["importance_sum"] == 0.0


# =============================================================================
# reflect() — user_id propagation
# =============================================================================

class TestReflectUserIsolation:
    """Test that reflect() passes user_id to all downstream calls."""

    @pytest.mark.asyncio
    async def test_reflect_passes_user_id_to_get_blocks(self):
        engine = _get_engine()
        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "should_update": False,
            "updates": [],
            "reflection_summary": "Nothing new",
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_CHAR_STATE_PATCH, return_value=mock_manager), \
             patch(_CHAR_REPO_PATCH, return_value=mock_repo), \
             patch(_LLM_FOR_PROVIDER_PATCH, return_value=None), \
             patch(_LLM_PATCH, return_value=mock_llm):
            await engine.reflect(
                "hello",
                "hi",
                user_id="test-user-42",
                organization_id="org-ref",
            )

        # Verify user_id was passed
        mock_manager.get_blocks.assert_called_once_with(
            user_id="test-user-42",
            organization_id="org-ref",
        )
        mock_repo.get_recent_experiences.assert_called_once_with(
            limit=10,
            user_id="test-user-42",
            organization_id="org-ref",
        )

    @pytest.mark.asyncio
    async def test_reflect_applies_updates_with_user_id(self):
        engine = _get_engine()
        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}
        mock_manager.update_block.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "self_notes", "action": "append", "content": "User likes COLREGs"},
            ],
            "reflection_summary": "Learned about user",
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_CHAR_STATE_PATCH, return_value=mock_manager), \
             patch(_CHAR_REPO_PATCH, return_value=mock_repo), \
             patch(_LLM_FOR_PROVIDER_PATCH, return_value=None), \
             patch(_LLM_PATCH, return_value=mock_llm), \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.character_experience_retention_days = 90
            mock_settings.character_experience_keep_min = 100
            result = await engine.reflect(
                "hello",
                "hi",
                user_id="user-X",
                organization_id="org-X",
            )

        # Verify update_block was called with user_id
        call_kwargs = mock_manager.update_block.call_args[1]
        assert call_kwargs["user_id"] == "user-X"
        assert call_kwargs["organization_id"] == "org-X"

        # Verify cleanup was called with user_id
        cleanup_kwargs = mock_repo.cleanup_old_experiences.call_args[1]
        assert cleanup_kwargs["user_id"] == "user-X"
        assert cleanup_kwargs["organization_id"] == "org-X"
        assert mock_repo.log_experience.call_args.kwargs["organization_id"] == "org-X"

    @pytest.mark.asyncio
    async def test_reflect_none_user_defaults_to_global(self):
        engine = _get_engine()
        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "should_update": False,
            "updates": [],
            "reflection_summary": "Nothing",
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch(_CHAR_STATE_PATCH, return_value=mock_manager), \
             patch(_CHAR_REPO_PATCH, return_value=mock_repo), \
             patch(_LLM_FOR_PROVIDER_PATCH, return_value=None), \
             patch(_LLM_PATCH, return_value=mock_llm):
            await engine.reflect("hi", "hello", user_id=None)

        mock_manager.get_blocks.assert_called_once_with(
            user_id="__global__",
            organization_id=None,
        )


# =============================================================================
# trigger_character_reflection — user_id pass-through
# =============================================================================

class TestTriggerReflection:
    """Test the background task entry point passes user_id."""

    @pytest.mark.asyncio
    async def test_trigger_increments_per_user(self):
        from app.engine.character import reflection_engine as mod

        engine = _get_engine()
        old_singleton = mod._reflection_engine
        mod._reflection_engine = engine

        try:
            with patch.object(engine, "_is_enabled", return_value=False):
                await mod.trigger_character_reflection(
                    user_id="trigger-user-1",
                    message="test",
                    response="resp",
                )
            assert engine._conversation_counts["trigger-user-1"] == 1

            with patch.object(engine, "_is_enabled", return_value=False):
                await mod.trigger_character_reflection(
                    user_id="trigger-user-2",
                    message="test",
                    response="resp",
                )
            assert engine._conversation_counts["trigger-user-2"] == 1
            # User 1 still at 1
            assert engine._conversation_counts["trigger-user-1"] == 1
        finally:
            mod._reflection_engine = old_singleton


# =============================================================================
# CharacterRepository — get_recent_experiences with user_id
# =============================================================================

class TestRepoExperiencesUserFilter:
    """Test that repository experience queries filter by user_id."""

    def test_get_recent_experiences_builds_user_filter(self):
        """Verify the SQL includes user_id filter when provided."""
        from app.engine.character.character_repository import CharacterRepository

        repo = CharacterRepository()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_session_factory
        repo._initialized = True

        result = repo.get_recent_experiences(limit=5, user_id="test-user")
        assert result == []

        # Verify the SQL includes user_id parameter
        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params.get("user_id") == "test-user"

    def test_get_recent_experiences_no_user_filter_when_none(self):
        """Without user_id, no user filter in SQL."""
        from app.engine.character.character_repository import CharacterRepository

        repo = CharacterRepository()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)

        repo._session_factory = mock_session_factory
        repo._initialized = True

        result = repo.get_recent_experiences(limit=5, user_id=None)
        assert result == []

        call_args = mock_session.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert "user_id" not in params


# =============================================================================
# Backward compatibility
# =============================================================================

class TestBackwardCompat:
    """Test that default behavior still works (no user_id = __global__)."""

    def test_increment_without_user_id(self):
        engine = _get_engine()
        count = engine.increment_conversation_count()
        assert count == 1
        assert "__global__" in engine._conversation_counts

    def test_add_importance_without_user_id(self):
        engine = _get_engine()
        engine.add_experience_importance(0.5)
        assert engine._importance_sums["__global__"] == pytest.approx(0.5)

    def test_should_reflect_without_user_id(self):
        engine = _get_engine()
        with patch.object(engine, "_is_enabled", return_value=True), \
             patch.object(engine, "_get_threshold", return_value=1.0):
            engine.add_experience_importance(2.0)
            assert engine.should_reflect() is True

    def test_reset_without_user_id(self):
        engine = _get_engine()
        engine.increment_conversation_count()
        engine.reset_counter()
        assert engine._conversation_counts["__global__"] == 0

    def test_get_stats_without_user_id(self):
        engine = _get_engine()
        stats = engine.get_stats()
        assert stats["user_id"] == "__global__"
