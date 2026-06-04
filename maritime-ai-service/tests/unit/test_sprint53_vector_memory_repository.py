"""
Tests for Sprint 53: VectorMemoryRepositoryMixin coverage.

Tests vector similarity search:
- search_similar (basic, NaN/Inf handling, type filter, threshold, error)
"""

import math
import logging
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from app.models.semantic_memory import MemoryType, SemanticMemorySearchResult


# ============================================================================
# Helpers
# ============================================================================


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


def _make_row(content="test content", memory_type="message", similarity=0.85):
    """Create a mock DB row."""
    row = MagicMock()
    row.id = str(uuid4())
    row.content = content
    row.memory_type = memory_type
    row.importance = 0.5
    row.similarity = similarity
    row.metadata = {}
    row.created_at = datetime.now(timezone.utc)
    row.last_accessed = None  # Sprint 98: Stanford ranking fields
    row.access_count = 0
    return row


# ============================================================================
# search_similar
# ============================================================================


class TestSearchSimilar:
    """Test cosine similarity search."""

    def test_search_similar_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = _make_repo()
        repo._format_embedding = MagicMock(return_value="[0.1]")
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            results = repo.search_similar("PRIVATE-USER", [0.1] * 768)
        finally:
            current_org_id.reset(token)

        assert results == []
        repo._format_embedding.assert_not_called()
        repo._session_factory.assert_not_called()
        assert "vector_memory_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_search_similar_text_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = _make_repo()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            results = repo.search_similar_text("PRIVATE-USER", "private query")
        finally:
            current_org_id.reset(token)

        assert results == []
        repo._session_factory.assert_not_called()
        assert "vector_memory_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_basic_search(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row("SOLAS chapter III", "message", 0.92)
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar(
            user_id="user1",
            query_embedding=[0.1] * 768,
        )

        assert len(results) == 1
        assert isinstance(results[0], SemanticMemorySearchResult)
        assert results[0].content == "SOLAS chapter III"
        assert results[0].similarity == 0.92

    def test_empty_results(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        results = repo.search_similar("user1", [0.1] * 768)
        assert results == []

    def test_nan_similarity_clamped(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row(similarity=float('nan'))
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar("user1", [0.0] * 768)
        assert len(results) == 1
        assert results[0].similarity == 0.0  # NaN → 0.0

    def test_inf_similarity_clamped(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row(similarity=float('inf'))
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar("user1", [0.1] * 768)
        assert len(results) == 1
        assert results[0].similarity == 0.0  # inf → reset to 0.0 (isinf check before clamp)

    def test_negative_similarity_clamped(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row(similarity=-0.5)
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar("user1", [0.1] * 768)
        assert results[0].similarity == 0.0  # Negative → clamped to 0.0

    def test_none_similarity(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row(similarity=None)
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar("user1", [0.1] * 768)
        assert results[0].similarity == 0.0  # None → 0.0

    def test_with_memory_type_filter(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        repo.search_similar(
            "user1", [0.1] * 768,
            memory_types=[MemoryType.MESSAGE, MemoryType.SUMMARY]
        )

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert "memory_types" in params
        assert params["memory_types"] == ["message", "summary"]

    def test_custom_limit_and_threshold(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        repo.search_similar("user1", [0.1] * 768, limit=20, threshold=0.3)

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["limit"] == 20
        assert params["threshold"] == 0.3

    def test_error_returns_empty(self):
        repo = _make_repo()
        repo._session_factory.return_value.__enter__ = MagicMock(
            side_effect=Exception("DB connection error")
        )

        results = repo.search_similar("user1", [0.1] * 768)
        assert results == []

    def test_empty_query_embedding_short_circuits(self):
        repo = _make_repo()
        results = repo.search_similar("user1", [])
        assert results == []

    def test_search_similar_text_fallback(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row("Quy tắc 15 là tình huống cắt ngang", "message", 0.0)
        row.lexical_hits = 2
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar_text(
            "user1",
            "Quy tắc 15 là gì",
            memory_types=[MemoryType.MESSAGE],
        )

        assert len(results) == 1
        assert results[0].content == "Quy tắc 15 là tình huống cắt ngang"
        assert results[0].similarity > 0

    def test_multiple_results(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        rows = [
            _make_row("Result 1", "message", 0.95),
            _make_row("Result 2", "summary", 0.80),
            _make_row("Result 3", "insight", 0.75),
        ]
        mock_session.execute.return_value.fetchall.return_value = rows

        results = repo.search_similar("user1", [0.1] * 768)
        assert len(results) == 3
        assert results[0].similarity == 0.95
        assert results[1].similarity == 0.80
        assert results[2].memory_type == MemoryType.INSIGHT

    def test_metadata_none_defaults_to_empty_dict(self):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)

        row = _make_row()
        row.metadata = None
        mock_session.execute.return_value.fetchall.return_value = [row]

        results = repo.search_similar("user1", [0.1] * 768)
        assert results[0].metadata == {}

    def test_shadow_space_query_uses_side_table(self, monkeypatch):
        repo = _make_repo()
        mock_session = MagicMock()
        repo._session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        repo._session_factory.return_value.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []

        shadow_space = SimpleNamespace(
            storage_kind="shadow",
            space_fingerprint="openai:text-embedding-3-small:1536",
            dimensions=1536,
        )
        monkeypatch.setattr(
            "app.repositories.vector_memory_repository.get_active_embedding_read_space",
            lambda *_args, **_kwargs: shadow_space,
        )

        repo.search_similar("user1", [0.1] * 1536)

        query = mock_session.execute.call_args[0][0].text
        params = mock_session.execute.call_args[0][1]
        assert "semantic_memory_vectors" in query
        assert params["space_fingerprint"] == "openai:text-embedding-3-small:1536"
