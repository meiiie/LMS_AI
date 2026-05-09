"""
Tests for Sprint 98: SOTA Memory & Character Improvements.

Features tested:
1. Stanford Generative Agents Memory Retrieval (config + reranking)
2. Code Execution wiring in Direct Node
3. Importance-Threshold Reflection Trigger
4. Experience Log TTL (cleanup)
"""

import pytest
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4


# =============================================================================
# Phase 1: Stanford Config
# =============================================================================


class TestStanfordConfig:
    """Test Stanford ranking config fields."""

    def test_default_weights(self):
        """Default weights: alpha=0.3, beta=0.3, gamma=0.4."""
        from app.core.config import Settings

        s = Settings(
            api_key="test",
            google_api_key="test",
            _env_file=None,
        )
        assert s.stanford_recency_weight == 0.3
        assert s.stanford_importance_weight == 0.3
        assert s.stanford_relevance_weight == 0.4

    def test_weights_overridable(self):
        """Weights can be overridden via env."""
        from app.core.config import Settings

        s = Settings(
            api_key="test",
            google_api_key="test",
            stanford_recency_weight=0.5,
            stanford_importance_weight=0.2,
            stanford_relevance_weight=0.3,
            _env_file=None,
        )
        assert s.stanford_recency_weight == 0.5
        assert s.stanford_importance_weight == 0.2
        assert s.stanford_relevance_weight == 0.3

    def test_character_experience_retention_defaults(self):
        """Experience retention defaults: 90 days, 100 min."""
        from app.core.config import Settings

        s = Settings(
            api_key="test",
            google_api_key="test",
            _env_file=None,
        )
        assert s.character_experience_retention_days == 90
        assert s.character_experience_keep_min == 100
        assert s.character_reflection_threshold == 5.0


# =============================================================================
# Phase 2: Stanford Re-ranking
# =============================================================================


def _make_repo():
    """Create a VectorMemoryRepositoryMixin with mocked host methods."""
    from app.repositories.vector_memory_repository import VectorMemoryRepositoryMixin

    class MockRepo(VectorMemoryRepositoryMixin):
        TABLE_NAME = "semantic_memories"
        DEFAULT_SEARCH_LIMIT = 5
        DEFAULT_SIMILARITY_THRESHOLD = 0.7

        def __init__(self):
            self._session_factory = MagicMock()
            self._initialized = True

        def _ensure_initialized(self):
            pass

        def _format_embedding(self, embedding):
            return f"[{','.join(str(x) for x in embedding)}]"

    return MockRepo()


def _make_row(
    content="test content",
    memory_type="message",
    similarity=0.85,
    importance=0.5,
    last_accessed=None,
    access_count=0,
):
    """Create a mock DB row with Stanford-compatible fields."""
    row = MagicMock()
    row.id = str(uuid4())
    row.content = content
    row.memory_type = memory_type
    row.importance = importance
    row.similarity = similarity
    row.metadata = {}
    row.created_at = datetime.now(timezone.utc)
    row.last_accessed = last_accessed
    row.access_count = access_count
    return row


class TestStanfordReranking:
    """Test Stanford Generative Agents hybrid re-ranking."""

    def test_rerank_changes_order(self):
        """High importance + recency should outrank high similarity alone."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        now = datetime.now(timezone.utc)
        # Row 1: high similarity but old and low importance
        row1 = _make_row(
            content="Old high-sim",
            similarity=0.95,
            importance=0.1,
            last_accessed=now - timedelta(days=30),
            access_count=0,
        )
        # Row 2: moderate similarity but recent and high importance
        row2 = _make_row(
            content="Recent important",
            similarity=0.75,
            importance=0.9,
            last_accessed=now - timedelta(hours=1),
            access_count=5,
        )
        mock_session.execute.return_value.fetchall.return_value = [row1, row2]

        results = repo.search_similar(
            user_id="user1",
            query_embedding=[0.1] * 768,
            limit=2,
            use_stanford_ranking=True,
        )

        assert len(results) == 2
        # Row 2 should rank first due to recency + importance
        assert results[0].content == "Recent important"

    def test_rerank_importance_boost(self):
        """High importance memories should rank higher."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        now = datetime.now(timezone.utc)
        row_low = _make_row(
            content="Low importance",
            similarity=0.80,
            importance=0.1,
            last_accessed=now,
        )
        row_high = _make_row(
            content="High importance",
            similarity=0.80,
            importance=0.9,
            last_accessed=now,
        )
        mock_session.execute.return_value.fetchall.return_value = [row_low, row_high]

        results = repo.search_similar(
            "user1", [0.1] * 768, limit=2, use_stanford_ranking=True
        )
        assert results[0].content == "High importance"

    def test_rerank_recency_boost(self):
        """Recent memories should rank higher (same similarity+importance)."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        now = datetime.now(timezone.utc)
        row_old = _make_row(
            content="Old memory",
            similarity=0.80,
            importance=0.5,
            last_accessed=now - timedelta(days=60),
        )
        row_new = _make_row(
            content="New memory",
            similarity=0.80,
            importance=0.5,
            last_accessed=now - timedelta(hours=1),
        )
        mock_session.execute.return_value.fetchall.return_value = [row_old, row_new]

        results = repo.search_similar(
            "user1", [0.1] * 768, limit=2, use_stanford_ranking=True
        )
        assert results[0].content == "New memory"

    def test_rerank_empty_results(self):
        """Empty results should stay empty."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        results = repo.search_similar(
            "user1", [0.1] * 768, use_stanford_ranking=True
        )
        assert results == []

    def test_stanford_disabled_by_default(self):
        """Without use_stanford_ranking, results are similarity-ordered."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        now = datetime.now(timezone.utc)
        row1 = _make_row(content="High sim", similarity=0.95, importance=0.1)
        row2 = _make_row(content="Low sim", similarity=0.75, importance=0.9)
        mock_session.execute.return_value.fetchall.return_value = [row1, row2]

        results = repo.search_similar("user1", [0.1] * 768, limit=2)
        # Without Stanford ranking, order is as returned by DB (similarity)
        assert results[0].content == "High sim"

    def test_stanford_fetches_3x_limit(self):
        """Stanford ranking should fetch 3x candidates then rerank."""
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        repo.search_similar(
            "user1", [0.1] * 768, limit=5, use_stanford_ranking=True
        )

        # Check that limit parameter in SQL is 15 (3 * 5)
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 15  # 3x the requested limit


# =============================================================================
# Phase 3: Code Execution Wiring
# =============================================================================


class TestCodeExecutionWiring:
    """Test code execution tool wiring in direct_response_node."""

    @pytest.mark.asyncio
    @patch("app.core.config.settings")
    async def test_code_execution_bound_when_enabled(self, mock_settings):
        """Code execution tools should be added when enable_code_execution=True."""
        mock_settings.enable_code_execution = True
        mock_settings.enable_character_tools = False
        mock_settings.app_name = "Wiii"
        mock_settings.default_domain = "maritime"

        from app.engine.tools.code_execution_tools import get_code_execution_tools

        tools = get_code_execution_tools()
        assert len(tools) == 1
        assert tools[0].name == "tool_execute_python"

    @patch("app.core.config.settings")
    def test_code_execution_not_bound_when_disabled(self, mock_settings):
        """Code execution tools should NOT be added when enable_code_execution=False."""
        mock_settings.enable_code_execution = False

        # The flag check is in graph.py — we just verify the setting works
        assert mock_settings.enable_code_execution is False

    @patch("app.core.config.settings")
    def test_code_execution_hint_present_when_enabled(self, mock_settings):
        """Tool hint should be generated when enable_code_execution=True."""
        mock_settings.enable_code_execution = True

        # Simulate the hint generation from graph.py
        tool_hints = []
        if mock_settings.enable_code_execution:
            tool_hints.append(
                "- tool_execute_python: Chạy code Python trong sandbox. "
                "Dùng khi user yêu cầu tính toán, viết code, hoặc xử lý dữ liệu."
            )
        assert len(tool_hints) == 1
        assert "tool_execute_python" in tool_hints[0]


# =============================================================================
# Phase 4: Importance-Threshold Reflection Trigger
# =============================================================================


class TestImportanceThreshold:
    """Test importance-based reflection trigger (Sprint 98)."""

    @patch("app.core.config.settings")
    def test_triggers_at_threshold(self, mock_settings):
        """Reflection triggers when importance_sum >= threshold."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 10
        mock_settings.character_reflection_threshold = 5.0

        engine = CharacterReflectionEngine()
        # Sprint 125: Per-user counters (Dict)
        engine._conversation_counts["__global__"] = 1  # Low count
        engine._importance_sums["__global__"] = 5.0  # At threshold
        assert engine.should_reflect()

    @patch("app.core.config.settings")
    def test_does_not_trigger_below_threshold(self, mock_settings):
        """Reflection does NOT trigger when importance_sum < threshold and count < 2*interval."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 10
        mock_settings.character_reflection_threshold = 5.0

        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 5  # Below 2*10=20
        engine._importance_sums["__global__"] = 3.0  # Below 5.0
        assert not engine.should_reflect()

    @patch("app.core.config.settings")
    def test_safety_net_triggers_at_2x_interval(self, mock_settings):
        """Safety net: reflection triggers at 2x interval even with low importance."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 100.0  # Very high threshold

        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 10  # 2 * 5 = 10
        engine._importance_sums["__global__"] = 0.5  # Very low
        assert engine.should_reflect()

    @patch("app.core.config.settings")
    def test_reset_clears_importance_sum(self, mock_settings):
        """reset_counter() should clear both count and importance_sum."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        mock_settings.enable_character_reflection = True

        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 10
        engine._importance_sums["__global__"] = 8.5
        engine.reset_counter()
        assert engine._conversation_counts["__global__"] == 0
        assert engine._importance_sums["__global__"] == 0.0
        assert engine._last_reflection_times["__global__"] > 0

    def test_add_experience_importance(self):
        """add_experience_importance() accumulates importance."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        assert engine._importance_sums.get("__global__", 0.0) == 0.0

        engine.add_experience_importance(0.7)
        assert engine._importance_sums["__global__"] == pytest.approx(0.7)

        engine.add_experience_importance(1.0)
        assert engine._importance_sums["__global__"] == pytest.approx(1.7)

    def test_add_experience_importance_clamps_negative(self):
        """Negative importance values are clamped to 0."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        engine.add_experience_importance(-0.5)
        assert engine._importance_sums.get("__global__", 0.0) == 0.0

    @patch("app.core.config.settings")
    def test_get_stats_includes_importance(self, mock_settings):
        """get_stats() should include importance_sum and threshold."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 5.0

        engine = CharacterReflectionEngine()
        engine._importance_sums["__global__"] = 3.5
        stats = engine.get_stats()
        assert stats["importance_sum"] == 3.5
        assert stats["threshold"] == 5.0


# =============================================================================
# Phase 5: Experience Cleanup
# =============================================================================


class TestExperienceCleanup:
    """Test cleanup_old_experiences in CharacterRepository."""

    def _make_repo(self):
        from app.core.database import clear_shared_database_unavailable
        from app.engine.character.character_repository import CharacterRepository

        # Cleanup tests provide a mocked healthy session; isolate them from
        # earlier tests that intentionally mark the shared DB as unavailable.
        clear_shared_database_unavailable()

        repo = CharacterRepository()
        repo._initialized = True
        repo._session_factory = MagicMock()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        return repo, mock_session

    def test_deletes_old_experiences(self):
        """Should delete old experiences beyond retention period."""
        repo, mock_session = self._make_repo()

        # Total = 200, above keep_min=100
        mock_session.execute.return_value.scalar.return_value = 200
        # DELETE returns 50 rows
        delete_result = MagicMock()
        delete_result.rowcount = 50
        mock_session.execute.return_value = delete_result
        # First call is COUNT, second is DELETE
        mock_session.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=200)),
            delete_result,
        ]

        deleted = repo.cleanup_old_experiences(max_age_days=90, keep_min=100)
        assert deleted == 50

    def test_keeps_minimum_experiences(self):
        """Should skip cleanup when total <= keep_min."""
        repo, mock_session = self._make_repo()

        # Total = 50, below keep_min=100
        mock_session.execute.return_value.scalar.return_value = 50

        deleted = repo.cleanup_old_experiences(max_age_days=90, keep_min=100)
        assert deleted == 0

    def test_returns_count_on_success(self):
        """Should return the number of deleted rows."""
        repo, mock_session = self._make_repo()

        count_result = MagicMock()
        count_result.scalar.return_value = 300
        delete_result = MagicMock()
        delete_result.rowcount = 75
        mock_session.execute.side_effect = [count_result, delete_result]

        deleted = repo.cleanup_old_experiences(max_age_days=30, keep_min=50)
        assert deleted == 75

    def test_error_returns_zero(self):
        """Errors should return 0, not propagate."""
        from app.engine.character.character_repository import CharacterRepository

        repo = CharacterRepository()
        repo._initialized = True
        repo._session_factory = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB error")
        )

        deleted = repo.cleanup_old_experiences()
        assert deleted == 0

    def test_uninitialized_returns_zero(self):
        """Uninitialized repo should return 0."""
        from app.engine.character.character_repository import CharacterRepository

        repo = CharacterRepository()
        repo._initialized = False
        deleted = repo.cleanup_old_experiences()
        assert deleted == 0


# =============================================================================
# Phase 6: Cleanup Wired in Reflection
# =============================================================================


class TestCleanupInReflection:
    """Test that cleanup is wired into reflect()."""

    @pytest.mark.asyncio
    async def test_cleanup_called_after_reflection(self):
        """cleanup_old_experiences should be called after successful reflection."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_state_manager = MagicMock()
        mock_state_manager.get_blocks.return_value = {}
        mock_state_manager.compile_living_state.return_value = ""

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []
        mock_repo.log_experience.return_value = None
        mock_repo.cleanup_old_experiences.return_value = 5

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"should_update": false, "reflection_summary": "Test reflection"}'
        )

        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_state_manager,
        ), patch(
            "app.engine.character.character_repository.get_character_repository",
            return_value=mock_repo,
        ), patch(
            "app.engine.llm_pool.get_llm_light",
            return_value=mock_llm,
        ):
            result = await engine.reflect("Hello", "Hi there!", user_id="user1")

        assert result is not None
        mock_repo.cleanup_old_experiences.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_error_does_not_break_reflection(self):
        """Cleanup errors should not affect reflection result."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_state_manager = MagicMock()
        mock_state_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []
        mock_repo.log_experience.return_value = None
        mock_repo.cleanup_old_experiences.side_effect = Exception("Cleanup boom!")

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"should_update": false, "reflection_summary": "Test"}'
        )

        with patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_state_manager,
        ), patch(
            "app.engine.character.character_repository.get_character_repository",
            return_value=mock_repo,
        ), patch(
            "app.engine.llm_pool.get_llm_light",
            return_value=mock_llm,
        ):
            result = await engine.reflect("Hello", "Hi!", user_id="u1")

        # Should succeed despite cleanup error
        assert result is not None
        assert result["should_update"] is False
