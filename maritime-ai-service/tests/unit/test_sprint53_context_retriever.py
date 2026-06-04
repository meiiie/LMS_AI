"""
Tests for Sprint 53: ContextRetriever coverage.

Tests context retrieval from semantic memory:
- ContextRetriever init (stores deps, constants)
- retrieve_context (success, with-facts, no-facts, error)
- retrieve_insights_prioritized (empty, prioritized, callback, error)
- _get_user_insights (success, conversion, error)
- _estimate_tokens
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from app.engine.semantic_memory.context import ContextRetriever
from app.models.semantic_memory import (
    InsightCategory,
    MemoryType,
    SemanticContext,
    SemanticMemorySearchResult,
    Insight,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_retriever():
    mock_embeddings = MagicMock()
    mock_repo = MagicMock()
    return ContextRetriever(embeddings=mock_embeddings, repository=mock_repo)


def _make_search_result(content="test content", memory_type=MemoryType.MESSAGE, similarity=0.85):
    return SemanticMemorySearchResult(
        id=str(uuid4()),
        content=content,
        memory_type=memory_type,
        importance=0.5,
        similarity=similarity,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )


# ============================================================================
# Init
# ============================================================================


class TestContextRetrieverInit:
    """Test ContextRetriever initialization."""

    def test_stores_deps(self):
        mock_embed = MagicMock()
        mock_repo = MagicMock()
        retriever = ContextRetriever(embeddings=mock_embed, repository=mock_repo)
        assert retriever._embeddings is mock_embed
        assert retriever._repository is mock_repo

    def test_constants(self):
        assert ContextRetriever.DEFAULT_SEARCH_LIMIT == 5
        assert ContextRetriever.DEFAULT_SIMILARITY_THRESHOLD == 0.7
        assert ContextRetriever.DEFAULT_USER_FACTS_LIMIT == 20  # Sprint 88: raised for 15 fact types

    def test_priority_categories(self):
        assert InsightCategory.KNOWLEDGE_GAP in ContextRetriever.PRIORITY_CATEGORIES
        assert InsightCategory.LEARNING_STYLE in ContextRetriever.PRIORITY_CATEGORIES


# ============================================================================
# retrieve_context
# ============================================================================


class TestRetrieveContext:
    """Test context retrieval."""

    @pytest.mark.asyncio
    async def test_success_with_facts(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)

        memories = [_make_search_result("SOLAS chapter III")]
        facts = [_make_search_result("User is a student", MemoryType.USER_FACT)]
        retriever._repository.search_similar.return_value = memories
        retriever._repository.get_user_facts.return_value = facts

        result = await retriever.retrieve_context("user1", "What is SOLAS?")

        assert isinstance(result, SemanticContext)
        assert len(result.relevant_memories) == 1
        assert len(result.user_facts) == 1
        retriever._repository.search_similar.assert_called_once()
        retriever._repository.get_user_facts.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_user_facts(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        retriever._repository.search_similar.return_value = []

        result = await retriever.retrieve_context(
            "user1", "Query", include_user_facts=False
        )

        assert result.user_facts == []
        retriever._repository.get_user_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_limits(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        retriever._repository.search_similar.return_value = []
        retriever._repository.get_user_facts.return_value = []

        await retriever.retrieve_context(
            "user1", "Query", search_limit=10, similarity_threshold=0.5
        )

        call_args = retriever._repository.search_similar.call_args
        assert call_args.kwargs["limit"] == 10
        assert call_args.kwargs["threshold"] == 0.5

    @pytest.mark.asyncio
    async def test_default_params(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        retriever._repository.search_similar.return_value = []
        retriever._repository.get_user_facts.return_value = []

        await retriever.retrieve_context("user1", "Query")

        call_args = retriever._repository.search_similar.call_args
        assert call_args.kwargs["limit"] == 5
        assert call_args.kwargs["threshold"] == 0.7

    @pytest.mark.asyncio
    async def test_error_returns_empty_context(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(side_effect=Exception("Embedding error"))
        retriever._repository.search_similar_text.return_value = []
        retriever._repository.get_user_facts.return_value = []

        result = await retriever.retrieve_context("user1", "Query")

        assert isinstance(result, SemanticContext)
        assert result.relevant_memories == []

    @pytest.mark.asyncio
    async def test_embedding_failure_falls_back_to_text_recall(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(side_effect=Exception("Embedding error"))
        retriever._repository.search_similar_text.return_value = [
            _make_search_result("Quy tắc 15 là tình huống cắt ngang")
        ]
        retriever._repository.get_user_facts.return_value = []

        result = await retriever.retrieve_context("user1", "Quy tắc 15 là gì?")

        assert len(result.relevant_memories) == 1
        retriever._repository.search_similar.assert_not_called()
        retriever._repository.search_similar_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_query_embedding_falls_back_to_text_recall(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[])
        retriever._repository.search_similar_text.return_value = [
            _make_search_result("SOLAS chapter III")
        ]
        retriever._repository.get_user_facts.return_value = []

        result = await retriever.retrieve_context("user1", "What is SOLAS?")

        assert len(result.relevant_memories) == 1
        retriever._repository.search_similar.assert_not_called()
        retriever._repository.search_similar_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_estimation(self):
        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)

        memories = [_make_search_result("A" * 400)]  # 400 chars ≈ 100 tokens
        retriever._repository.search_similar.return_value = memories
        retriever._repository.get_user_facts.return_value = []

        result = await retriever.retrieve_context("user1", "Query")
        assert result.total_tokens == 100  # 400 chars / 4

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_embedding_or_repo(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        retriever = _make_retriever()
        retriever._embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            result = await retriever.retrieve_context(
                "user-private-123",
                "PRIVATE QUERY",
            )
        finally:
            current_org_id.reset(token)

        assert result.relevant_memories == []
        assert result.user_facts == []
        assert result.total_tokens == 0
        retriever._embeddings.aembed_query.assert_not_awaited()
        retriever._repository.search_similar.assert_not_called()
        retriever._repository.get_user_facts.assert_not_called()


# ============================================================================
# retrieve_insights_prioritized
# ============================================================================


class TestRetrieveInsightsPrioritized:
    """Test prioritized insight retrieval."""

    @pytest.mark.asyncio
    async def test_empty(self):
        retriever = _make_retriever()
        retriever._repository.get_user_insights.return_value = []

        result = await retriever.retrieve_insights_prioritized("user1", "Query")
        assert result == []

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_repo(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        retriever = _make_retriever()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            result = await retriever.retrieve_insights_prioritized(
                "user-private-123",
                "PRIVATE QUERY",
            )
        finally:
            current_org_id.reset(token)

        assert result == []
        retriever._repository.get_user_insights.assert_not_called()

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        retriever = _make_retriever()
        now = datetime.now(timezone.utc)

        # Create insights in repository format
        insight_memories = [
            _make_search_result("User has preference for visual learning"),
            _make_search_result("User confused about Rule 13"),
            _make_search_result("User studies at night"),
        ]
        # Set metadata for insight conversion
        insight_memories[0].metadata = {"category": "preference", "confidence": 0.7}
        insight_memories[0].created_at = now
        insight_memories[1].metadata = {"category": "knowledge_gap", "confidence": 0.9}
        insight_memories[1].created_at = now
        insight_memories[2].metadata = {"category": "habit", "confidence": 0.8}
        insight_memories[2].created_at = now

        retriever._repository.get_user_insights.return_value = insight_memories

        result = await retriever.retrieve_insights_prioritized("user1", "Query")

        # knowledge_gap should come first (priority category)
        assert len(result) == 3
        assert result[0].category == InsightCategory.KNOWLEDGE_GAP

    @pytest.mark.asyncio
    async def test_limit(self):
        retriever = _make_retriever()
        now = datetime.now(timezone.utc)

        insight_memories = []
        for i in range(5):
            mem = _make_search_result(f"Insight content number {i} for testing purposes")
            mem.metadata = {"category": "preference", "confidence": 0.7}
            mem.created_at = now
            insight_memories.append(mem)

        retriever._repository.get_user_insights.return_value = insight_memories

        result = await retriever.retrieve_insights_prioritized("user1", "Query", limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_callback(self):
        retriever = _make_retriever()
        now = datetime.now(timezone.utc)

        mem = _make_search_result("User has learning style insight content for test")
        mem.metadata = {"category": "learning_style", "confidence": 0.8}
        mem.created_at = now
        retriever._repository.get_user_insights.return_value = [mem]

        mock_callback = AsyncMock()
        result = await retriever.retrieve_insights_prioritized(
            "user1", "Query", update_last_accessed_callback=mock_callback
        )

        assert len(result) == 1
        # Callback should have been called for the insight
        assert mock_callback.call_count == 1

    @pytest.mark.asyncio
    async def test_error(self):
        retriever = _make_retriever()
        retriever._repository.get_user_insights.side_effect = Exception("DB error")

        result = await retriever.retrieve_insights_prioritized("user1", "Query")
        assert result == []


# ============================================================================
# _get_user_insights
# ============================================================================


class TestGetUserInsights:
    """Test user insights retrieval."""

    @pytest.mark.asyncio
    async def test_success(self):
        retriever = _make_retriever()
        now = datetime.now(timezone.utc)

        mem = _make_search_result("Knowledge gap in COLREGs", MemoryType.INSIGHT)
        mem.metadata = {"category": "knowledge_gap", "confidence": 0.9}
        mem.created_at = now
        retriever._repository.get_user_insights.return_value = [mem]

        result = await retriever._get_user_insights("user1")
        assert len(result) == 1
        assert isinstance(result[0], Insight)
        assert result[0].category == InsightCategory.KNOWLEDGE_GAP

    @pytest.mark.asyncio
    async def test_invalid_insight_skipped(self):
        retriever = _make_retriever()

        mem = _make_search_result("Bad insight")
        mem.metadata = {"category": "nonexistent_category"}
        retriever._repository.get_user_insights.return_value = [mem]

        result = await retriever._get_user_insights("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_error(self):
        retriever = _make_retriever()
        retriever._repository.get_user_insights.side_effect = Exception("DB error")

        result = await retriever._get_user_insights("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_empty(self):
        retriever = _make_retriever()
        retriever._repository.get_user_insights.return_value = []

        result = await retriever._get_user_insights("user1")
        assert result == []


# ============================================================================
# _estimate_tokens
# ============================================================================


class TestEstimateTokens:
    """Test token estimation."""

    def test_empty(self):
        retriever = _make_retriever()
        assert retriever._estimate_tokens([], []) == 0

    def test_calculation(self):
        retriever = _make_retriever()
        memories = [_make_search_result("A" * 100)]
        facts = [_make_search_result("B" * 200)]
        # (100 + 200) / 4 = 75
        assert retriever._estimate_tokens(memories, facts) == 75
