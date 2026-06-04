"""
Tests for Sprint 30: InsightProvider coverage.

Covers:
- update_last_accessed: timestamp update
- _get_user_insights: INSIGHT type retrieval + conversion
- _store_insight: embedding + save
- _merge_insight: metadata-only update
- _update_insight_with_evolution: re-embed + update
- enforce_hard_limit: count check + consolidation/eviction
- _fifo_eviction: oldest deletion
- extract_and_store_insights: full pipeline
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone


# =============================================================================
# Helpers
# =============================================================================


def _make_provider(repo=None, embeddings=None):
    """Create InsightProvider with mocked dependencies."""
    from app.engine.semantic_memory.insight_provider import InsightProvider

    mock_embeddings = embeddings or MagicMock()
    mock_repo = repo or MagicMock()
    provider = InsightProvider(embeddings=mock_embeddings, repository=mock_repo)
    return provider


def _make_insight(user_id="user-1", content="Visual learner", category="learning_style", confidence=0.85):
    """Create a mock Insight object."""
    from app.models.semantic_memory import Insight, InsightCategory
    return Insight(
        id=uuid4(),
        user_id=user_id,
        content=content,
        category=InsightCategory(category),
        confidence=confidence,
        source_messages=[content],
        created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        evolution_notes=[],
    )


def _make_search_result(content="Visual learner", category="learning_style", confidence=0.85):
    """Create a mock SemanticMemorySearchResult."""
    result = MagicMock()
    result.id = uuid4()
    result.content = content
    result.metadata = {
        "insight_category": category,
        "confidence": confidence,
        "sub_topic": None,
        "source_messages": [],
        "evolution_notes": [],
    }
    result.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return result


# =============================================================================
# update_last_accessed
# =============================================================================


class TestUpdateLastAccessed:
    """Test last_accessed timestamp update."""

    @pytest.mark.asyncio
    async def test_delegates_to_repository(self):
        mock_repo = MagicMock()
        mock_repo.update_last_accessed.return_value = True
        provider = _make_provider(repo=mock_repo)

        result = await provider.update_last_accessed(uuid4())
        assert result is True
        mock_repo.update_last_accessed.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        mock_repo = MagicMock()
        mock_repo.update_last_accessed.side_effect = RuntimeError("DB error")
        provider = _make_provider(repo=mock_repo)

        result = await provider.update_last_accessed(uuid4())
        assert result is False


# =============================================================================
# _get_user_insights
# =============================================================================


class TestGetUserInsights:
    """Test insight retrieval and conversion."""

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []
        provider = _make_provider(repo=mock_repo)

        result = await provider._get_user_insights("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_converts_search_results_to_insights(self):
        sr = _make_search_result(content="Learns visually", category="learning_style")
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = [sr]
        provider = _make_provider(repo=mock_repo)

        result = await provider._get_user_insights("user-1")
        assert len(result) == 1
        assert result[0].content == "Learns visually"

    @pytest.mark.asyncio
    async def test_skips_invalid_categories(self):
        sr = _make_search_result()
        sr.metadata["insight_category"] = "invalid_cat"
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = [sr]
        provider = _make_provider(repo=mock_repo)

        result = await provider._get_user_insights("user-1")
        assert len(result) == 0  # Invalid category skipped

    @pytest.mark.asyncio
    async def test_skips_missing_category(self):
        sr = MagicMock()
        sr.id = uuid4()
        sr.content = "something"
        sr.metadata = {}  # No insight_category key
        sr.created_at = datetime.now(timezone.utc)
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = [sr]
        provider = _make_provider(repo=mock_repo)

        result = await provider._get_user_insights("user-1")
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        mock_repo = MagicMock()
        mock_repo.get_user_insights.side_effect = RuntimeError("DB error")
        provider = _make_provider(repo=mock_repo)

        result = await provider._get_user_insights("user-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_repo(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        mock_repo = MagicMock()
        provider = _make_provider(repo=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            result = await provider._get_user_insights("user-private-123")
        finally:
            current_org_id.reset(token)

        assert result == []
        mock_repo.get_user_insights.assert_not_called()


# =============================================================================
# _store_insight
# =============================================================================


class TestStoreInsight:
    """Test insight storage."""

    @pytest.mark.asyncio
    async def test_embeds_and_saves(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)
        insight = _make_insight()

        result = await provider._store_insight(insight, session_id="sess-1")
        assert result is True
        mock_embeddings.aembed_documents.assert_called_once()
        mock_repo.save_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        mock_repo = MagicMock()
        mock_repo.save_memory.side_effect = RuntimeError("fail")
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)
        result = await provider._store_insight(_make_insight())
        assert result is False

    @pytest.mark.asyncio
    async def test_blocks_direct_store_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )
        mock_repo = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)
        insight = _make_insight(
            user_id="user-private-123",
            content="PRIVATE INSIGHT access_token=raw-insight-token-12345",
        )

        token = current_org_id.set(None)
        try:
            result = await provider._store_insight(
                insight,
                session_id="session-private-123",
            )
        finally:
            current_org_id.reset(token)

        assert result is False
        mock_embeddings.aembed_documents.assert_not_awaited()
        mock_repo.save_memory.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "insight_store"
        assert payload["write"]["status"] == "blocked"
        assert payload["write"]["stored_insight_count"] == 0
        assert payload["scope"]["write_allowed"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        serialized = str(payload)
        assert "PRIVATE INSIGHT" not in serialized
        assert "raw-insight-token" not in serialized
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized


# =============================================================================
# _merge_insight
# =============================================================================


class TestMergeInsight:
    """Test insight merging (metadata-only update)."""

    @pytest.mark.asyncio
    async def test_averages_confidence(self):
        mock_repo = MagicMock()
        mock_repo.update_metadata_only.return_value = True
        provider = _make_provider(repo=mock_repo)

        existing = _make_insight(confidence=0.8)
        new = _make_insight(confidence=0.6)

        result = await provider._merge_insight(new, existing)
        assert result is True

        # Check averaged confidence
        call_kwargs = mock_repo.update_metadata_only.call_args[1]
        assert call_kwargs["metadata"]["confidence"] == 0.7  # (0.8 + 0.6) / 2

    @pytest.mark.asyncio
    async def test_appends_evolution_note(self):
        mock_repo = MagicMock()
        mock_repo.update_metadata_only.return_value = True
        provider = _make_provider(repo=mock_repo)

        existing = _make_insight()
        new = _make_insight(content="Updated insight text")

        await provider._merge_insight(new, existing)
        call_kwargs = mock_repo.update_metadata_only.call_args[1]
        notes = call_kwargs["metadata"]["evolution_notes"]
        assert len(notes) == 1
        assert "Merged" in notes[0]
        assert "content_ref=sha256:" in notes[0]
        assert "Updated insight text" not in notes[0]

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        mock_repo = MagicMock()
        mock_repo.update_metadata_only.side_effect = RuntimeError("fail")
        provider = _make_provider(repo=mock_repo)
        result = await provider._merge_insight(_make_insight(), _make_insight())
        assert result is False


# =============================================================================
# _update_insight_with_evolution
# =============================================================================


class TestUpdateInsightWithEvolution:
    """Test insight update (contradictions)."""

    @pytest.mark.asyncio
    async def test_re_embeds_and_updates(self):
        mock_repo = MagicMock()
        mock_repo.update_fact.return_value = True
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.2] * 768])

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)
        existing = _make_insight(content="Old insight")
        new = _make_insight(content="New contradicting insight")

        result = await provider._update_insight_with_evolution(new, existing)
        assert result is True
        mock_embeddings.aembed_documents.assert_called_once()
        mock_repo.update_fact.assert_called_once()

    @pytest.mark.asyncio
    async def test_evolution_note_uses_old_content_reference(self):
        mock_repo = MagicMock()
        mock_repo.update_fact.return_value = True
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.2] * 768])

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)
        existing = _make_insight(content="Visual learner")
        new = _make_insight(content="Kinesthetic learner")

        await provider._update_insight_with_evolution(new, existing)
        call_kwargs = mock_repo.update_fact.call_args[1]
        notes = call_kwargs["metadata"]["evolution_notes"]
        assert "Updated from: content_ref=sha256:" in notes[0]
        assert "Visual learner" not in notes[0]


# =============================================================================
# enforce_hard_limit
# =============================================================================


class TestEnforceHardLimit:
    """Test hard limit enforcement."""

    @pytest.mark.asyncio
    async def test_returns_true_when_under_limit(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.return_value = 30
        provider = _make_provider(repo=mock_repo)

        result = await provider.enforce_hard_limit("user-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_triggers_consolidation_when_over_limit(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.return_value = 55  # > MAX_INSIGHTS (50)
        mock_repo.get_user_insights.return_value = []

        provider = _make_provider(repo=mock_repo)
        provider._check_and_consolidate = AsyncMock(return_value=True)
        provider._fifo_eviction = AsyncMock(return_value=0)

        result = await provider.enforce_hard_limit("user-1")
        assert result is True
        provider._check_and_consolidate.assert_called_once_with("user-1")

    @pytest.mark.asyncio
    async def test_falls_back_to_fifo_when_consolidation_fails(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.return_value = 55

        provider = _make_provider(repo=mock_repo)
        provider._check_and_consolidate = AsyncMock(return_value=False)
        provider._fifo_eviction = AsyncMock(return_value=5)

        result = await provider.enforce_hard_limit("user-1")
        assert result is True
        provider._fifo_eviction.assert_called_once_with("user-1")

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.side_effect = RuntimeError("DB fail")
        provider = _make_provider(repo=mock_repo)

        result = await provider.enforce_hard_limit("user-1")
        assert result is False


# =============================================================================
# _fifo_eviction
# =============================================================================


class TestFifoEviction:
    """Test FIFO eviction of oldest insights."""

    @pytest.mark.asyncio
    async def test_no_eviction_under_limit(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.return_value = 40
        provider = _make_provider(repo=mock_repo)

        result = await provider._fifo_eviction("user-1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_evicts_excess(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.return_value = 55
        mock_repo.delete_oldest_insights.return_value = 5
        provider = _make_provider(repo=mock_repo)

        result = await provider._fifo_eviction("user-1")
        assert result == 5
        mock_repo.delete_oldest_insights.assert_called_once_with("user-1", 5)

    @pytest.mark.asyncio
    async def test_returns_zero_on_error(self):
        mock_repo = MagicMock()
        mock_repo.count_user_memories.side_effect = RuntimeError("fail")
        provider = _make_provider(repo=mock_repo)

        result = await provider._fifo_eviction("user-1")
        assert result == 0


# =============================================================================
# extract_and_store_insights — full pipeline
# =============================================================================


class TestExtractAndStoreInsights:
    """Test the full insight extraction pipeline."""

    @pytest.mark.asyncio
    async def test_returns_empty_without_extractor(self):
        """If InsightExtractor is unavailable, returns empty list."""
        import sys

        provider = _make_provider()
        provider._insight_extractor = None

        # Lazy import inside function body — mock entire module to simulate ImportError
        mock_module = MagicMock()
        mock_module.InsightExtractor = MagicMock(side_effect=ImportError("no module"))

        with patch.dict(sys.modules, {"app.engine.insight_extractor": mock_module}):
            result = await provider.extract_and_store_insights("user-1", "test message")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_insights_extracted(self):
        mock_extractor = MagicMock()
        mock_extractor.extract_insights = AsyncMock(return_value=[])

        provider = _make_provider()
        provider._insight_extractor = mock_extractor

        result = await provider.extract_and_store_insights("user-1", "hello world")
        assert result == []

    @pytest.mark.asyncio
    async def test_stores_without_validator(self):
        """When no validator, insights are stored directly."""
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []
        mock_repo.save_memory.return_value = MagicMock()
        mock_repo.count_user_memories.return_value = 5  # Under threshold

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)

        insight = _make_insight()
        mock_extractor = MagicMock()
        mock_extractor.extract_insights = AsyncMock(return_value=[insight])
        provider._insight_extractor = mock_extractor
        # Use False (not None) to prevent lazy init while staying falsy
        provider._insight_validator = False  # Skip validator
        provider._memory_consolidator = False  # Skip consolidator

        result = await provider.extract_and_store_insights("user-1", "I learn visually")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_only_returns_successfully_written_insights(self):
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []
        mock_repo.save_memory.side_effect = RuntimeError("db down")

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)

        insight = _make_insight()
        mock_extractor = MagicMock()
        mock_extractor.extract_insights = AsyncMock(return_value=[insight])
        provider._insight_extractor = mock_extractor
        provider._insight_validator = False
        provider._memory_consolidator = False

        result = await provider.extract_and_store_insights("user-1", "I learn visually")

        assert result == []

    @pytest.mark.asyncio
    async def test_appends_privacy_safe_insight_write_audit(self, monkeypatch):
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []
        mock_repo.save_memory.return_value = MagicMock()

        provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)

        insight = _make_insight(content="PRIVATE INSIGHT CONTENT")
        mock_extractor = MagicMock()
        mock_extractor.extract_insights = AsyncMock(return_value=[insight])
        provider._insight_extractor = mock_extractor
        provider._insight_validator = False
        provider._memory_consolidator = False

        result = await provider.extract_and_store_insights(
            "user-private-123",
            "PRIVATE USER MESSAGE access_token=raw-insight-token-12345",
            session_id="session-private-123",
        )

        assert len(result) == 1
        events = await log.get_events(session_id="session-private-123")
        assert [event.event_type for event in events] == [
            "semantic_memory_write"
        ]
        payload = events[0].payload
        assert payload["write"]["kind"] == "insight_extraction"
        assert payload["write"]["stored_insight_count"] == 1
        assert payload["write"]["stored_fact_count"] == 0
        serialized = str(payload)
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized
        assert "PRIVATE USER MESSAGE" not in serialized
        assert "raw-insight-token" not in serialized
        assert "PRIVATE INSIGHT CONTENT" not in serialized

    @pytest.mark.asyncio
    async def test_blocks_insight_write_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.runtime.session_event_log import InMemorySessionEventLog

        log = InMemorySessionEventLog()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )
        token = current_org_id.set(None)
        try:
            mock_repo = MagicMock()
            mock_embeddings = MagicMock()
            provider = _make_provider(repo=mock_repo, embeddings=mock_embeddings)

            result = await provider.extract_and_store_insights(
                "user-private-123",
                "PRIVATE USER MESSAGE",
                session_id="session-private-123",
            )
        finally:
            current_org_id.reset(token)

        assert result == []
        mock_repo.save_memory.assert_not_called()
        mock_embeddings.aembed_documents.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "insight_extraction"
        assert payload["write"]["status"] == "blocked"
        assert payload["scope"]["write_allowed"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        assert "PRIVATE USER MESSAGE" not in str(payload)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        provider = _make_provider()
        mock_extractor = MagicMock()
        mock_extractor.extract_insights = AsyncMock(side_effect=RuntimeError("LLM fail"))
        provider._insight_extractor = mock_extractor

        result = await provider.extract_and_store_insights("user-1", "test")
        assert result == []
