"""
Tests for Sprint 51: FactRepositoryMixin coverage.

Tests fact repository operations including:
- get_user_facts (success, deduplicate, empty, error)
- get_all_user_facts (success, empty, error)
- find_fact_by_type (found, not found, error)
- find_similar_fact_by_embedding (found, below threshold, error)
- update_fact (success, empty embedding, error)
- update_metadata_only (success, invalid id, error)
- delete_oldest_facts (success, zero count, error)
- save_triple (success, error)
- find_by_predicate (found, not found, error)
- upsert_triple (insert, update)
"""

import pytest
import json
import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from app.models.semantic_memory import (
    MemoryType,
    SemanticMemorySearchResult,
    SemanticTriple,
    Predicate,
)
from app.repositories.fact_repository import FactRepositoryMixin


# ============================================================================
# Helpers
# ============================================================================


class MockRepo(FactRepositoryMixin):
    """Concrete class combining mixin with required host methods."""

    TABLE_NAME = "semantic_memories"

    def __init__(self):
        self._initialized = True
        self._session_factory = None

    def _ensure_initialized(self):
        pass

    def _format_embedding(self, embedding):
        return str(embedding)

    def save_memory(self, memory):
        return MagicMock(id=uuid4())

    def get_by_id(self, memory_id, user_id):
        return MagicMock(id=memory_id)

    def update_metadata_only(self, fact_id, metadata, user_id=None):
        return True


def _make_repo():
    """Create mock repo with mocked session."""
    repo = MockRepo()
    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)
    repo._session_factory = lambda: mock_session
    return repo, mock_session


def _make_fact_row(content="User is a student", fact_type="role", importance=0.8, created_at=None):
    """Create a mock row for fact queries."""
    row = MagicMock()
    row.id = uuid4()
    row.content = content
    row.memory_type = MemoryType.USER_FACT.value
    row.importance = importance
    row.metadata = {"fact_type": fact_type}
    row.created_at = created_at or datetime.now(timezone.utc)
    row.similarity = 1.0
    return row


def _make_search_result(content="test", fact_type="role", importance=0.8, created_at=None):
    """Create a SemanticMemorySearchResult for dedup tests."""
    return SemanticMemorySearchResult(
        id=uuid4(),
        content=content,
        memory_type=MemoryType.USER_FACT,
        importance=importance,
        similarity=1.0,
        metadata={"fact_type": fact_type},
        created_at=created_at or datetime.now(timezone.utc),
    )


# ============================================================================
# get_user_facts
# ============================================================================


class TestGetUserFacts:
    """Test user fact retrieval."""

    def test_success(self):
        repo, session = _make_repo()
        rows = [_make_fact_row("Name: Minh", "name"), _make_fact_row("Role: student", "role")]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session.execute.return_value = mock_result

        results = repo.get_user_facts("user1", deduplicate=False)
        assert len(results) == 2

    def test_empty(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute.return_value = mock_result

        results = repo.get_user_facts("user1")
        assert results == []

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")

        results = repo.get_user_facts("user1")
        assert results == []

    def test_dedup_uses_distinct_on(self):
        """Sprint 85: SQL DISTINCT ON handles dedup — no limit param in dedup query."""
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute.return_value = mock_result

        repo.get_user_facts("user1", limit=10, deduplicate=True)
        call_args = session.execute.call_args
        # SQL DISTINCT ON query does not pass limit (dedup at SQL level)
        assert "limit" not in call_args[0][1]


# ============================================================================
# get_all_user_facts
# ============================================================================


class TestGetAllUserFacts:
    """Test all facts retrieval."""

    def test_success(self):
        repo, session = _make_repo()
        rows = [_make_fact_row()]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session.execute.return_value = mock_result

        results = repo.get_all_user_facts("user1")
        assert len(results) == 1

    def test_empty(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session.execute.return_value = mock_result

        assert repo.get_all_user_facts("user1") == []

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        assert repo.get_all_user_facts("user1") == []


# ============================================================================
# find_fact_by_type
# ============================================================================


class TestFindFactByType:
    """Test fact lookup by type."""

    def test_found(self):
        repo, session = _make_repo()
        row = _make_fact_row("Name: Minh", "name")
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        session.execute.return_value = mock_result

        result = repo.find_fact_by_type("user1", "name")
        assert result is not None
        assert result.content == "Name: Minh"

    def test_not_found(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        assert repo.find_fact_by_type("user1", "nonexistent") is None

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        assert repo.find_fact_by_type("user1", "name") is None


# ============================================================================
# find_similar_fact_by_embedding
# ============================================================================


class TestFindSimilarFactByEmbedding:
    """Test semantic similarity search for facts."""

    def test_found_above_threshold(self):
        repo, session = _make_repo()
        row = _make_fact_row()
        row.similarity = 0.95
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        session.execute.return_value = mock_result

        result = repo.find_similar_fact_by_embedding("user1", [0.1] * 768)
        assert result is not None

    def test_below_threshold(self):
        repo, session = _make_repo()
        row = _make_fact_row()
        row.similarity = 0.50
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        session.execute.return_value = mock_result

        result = repo.find_similar_fact_by_embedding("user1", [0.1] * 768)
        assert result is None

    def test_no_results(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        result = repo.find_similar_fact_by_embedding("user1", [0.1] * 768)
        assert result is None

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        assert repo.find_similar_fact_by_embedding("user1", [0.1] * 768) is None

    def test_empty_embedding_returns_none_without_query(self):
        repo, session = _make_repo()
        result = repo.find_similar_fact_by_embedding("user1", [])
        assert result is None
        session.execute.assert_not_called()


# ============================================================================
# update_fact
# ============================================================================


class TestUpdateFact:
    """Test full fact update."""

    def test_success(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        session.execute.return_value = mock_result

        result = repo.update_fact(uuid4(), "New content", [0.1] * 768, {"fact_type": "name"})
        assert result is True

    def test_not_found(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        result = repo.update_fact(uuid4(), "Content", [0.1] * 768, {})
        assert result is False

    def test_empty_embedding_raises(self):
        repo, _ = _make_repo()
        with pytest.raises(ValueError, match="embedding is required"):
            repo.update_fact(uuid4(), "Content", [], {})

    def test_none_embedding_raises(self):
        repo, _ = _make_repo()
        with pytest.raises(ValueError, match="embedding is required"):
            repo.update_fact(uuid4(), "Content", None, {})

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        result = repo.update_fact(uuid4(), "Content", [0.1] * 768, {})
        assert result is False

    def test_preserve_embedding_updates_content_without_vector(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        session.execute.return_value = mock_result

        result = repo.update_fact_preserve_embedding(
            uuid4(),
            "New content",
            {"fact_type": "name", "confidence": 0.9},
        )

        assert result is True
        query = session.execute.call_args[0][0]
        params = session.execute.call_args[0][1]
        assert "embedding = CAST(:embedding AS vector)" not in query.text
        assert params["content"] == "New content"


# ============================================================================
# update_metadata_only (testing the mixin's actual method, not mock)
# ============================================================================


class TestUpdateMetadataOnly:
    """Test metadata-only update."""

    def test_success(self):
        # Use FactRepositoryMixin directly since MockRepo overrides it
        repo, session = _make_repo()
        # Call the mixin's real method via super
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        session.execute.return_value = mock_result

        result = FactRepositoryMixin.update_metadata_only(repo, uuid4(), {"key": "value"})
        assert result is True

    def test_invalid_id_none(self):
        repo, _ = _make_repo()
        result = FactRepositoryMixin.update_metadata_only(repo, None, {"key": "value"})
        assert result is False

    def test_invalid_id_empty(self):
        repo, _ = _make_repo()
        # The check is `str(fact_id) in ('None', '', 'null')`
        result = FactRepositoryMixin.update_metadata_only(repo, "", {"key": "value"})
        # Empty string converts to '' which matches the check
        assert result is False

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        result = FactRepositoryMixin.update_metadata_only(repo, uuid4(), {})
        assert result is False


# ============================================================================
# delete_oldest_facts
# ============================================================================


class TestDeleteOldestFacts:
    """Test FIFO fact deletion."""

    def test_success(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [MagicMock(), MagicMock()]
        session.execute.return_value = mock_result

        count = repo.delete_oldest_facts("user1", 2)
        assert count == 2
        session.commit.assert_called_once()

    def test_zero_count(self):
        repo, _ = _make_repo()
        count = repo.delete_oldest_facts("user1", 0)
        assert count == 0

    def test_negative_count(self):
        repo, _ = _make_repo()
        count = repo.delete_oldest_facts("user1", -1)
        assert count == 0

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        count = repo.delete_oldest_facts("user1", 5)
        assert count == 0


# ============================================================================
# save_triple
# ============================================================================


class TestSaveTriple:
    """Test triple saving."""

    def test_blocks_missing_org_context_before_embedding_or_save(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = MockRepo()
        repo._session_factory = MagicMock()
        repo.save_memory = MagicMock()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        triple = SemanticTriple(
            subject="PRIVATE-USER",
            predicate=Predicate.HAS_NAME,
            object="Minh",
        )

        token = current_org_id.set(None)
        try:
            result = repo.save_triple(triple, generate_embedding=True)
        finally:
            current_org_id.reset(token)

        assert result is None
        repo.save_memory.assert_not_called()
        repo._session_factory.assert_not_called()
        assert "triple_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_success_with_embedding(self):
        repo, _ = _make_repo()
        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_NAME,
            object="Minh",
            confidence=0.9,
            embedding=[0.1] * 768,
        )
        result = repo.save_triple(triple)
        assert result is not None

    def test_success_generates_embedding(self):
        import sys
        import types

        repo, _ = _make_repo()
        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_ROLE,
            object="student",
            confidence=0.8,
        )
        # The embeddings submodule doesn't exist — inject fake module into sys.modules
        mock_generator = MagicMock()
        mock_generator.is_available.return_value = True
        mock_generator.generate.return_value = [0.1] * 768

        fake_embeddings = types.ModuleType("app.engine.semantic_memory.embeddings")
        fake_embeddings.get_embedding_generator = MagicMock(return_value=mock_generator)

        with patch.dict(sys.modules, {"app.engine.semantic_memory.embeddings": fake_embeddings}):
            result = repo.save_triple(triple, generate_embedding=True)
            assert result is not None

    def test_generate_embedding_fallback_on_missing_module(self):
        """When embeddings module is unavailable, falls back to empty embedding."""
        repo, _ = _make_repo()
        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_ROLE,
            object="student",
            confidence=0.8,
        )
        # Without patching sys.modules, embeddings module doesn't exist
        # save_triple catches ImportError and falls back to empty embedding
        result = repo.save_triple(triple, generate_embedding=True)
        assert result is not None

    def test_error(self):
        repo, _ = _make_repo()
        repo.save_memory = MagicMock(side_effect=Exception("DB error"))
        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_NAME,
            object="Minh",
            embedding=[0.1] * 768,
        )
        result = repo.save_triple(triple)
        assert result is None


# ============================================================================
# find_by_predicate
# ============================================================================


class TestFindByPredicate:
    """Test predicate-based lookup."""

    def test_blocks_missing_org_context_before_db(self, monkeypatch, caplog):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = MockRepo()
        repo._session_factory = MagicMock()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.find_by_predicate("PRIVATE-USER", Predicate.HAS_NAME)
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._session_factory.assert_not_called()
        assert "triple_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_found(self):
        repo, session = _make_repo()
        row = _make_fact_row("Name: Minh", "name")
        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        session.execute.return_value = mock_result

        result = repo.find_by_predicate("user1", Predicate.HAS_NAME)
        assert result is not None

    def test_not_found(self):
        repo, session = _make_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        assert repo.find_by_predicate("user1", Predicate.HAS_GOAL) is None

    def test_error(self):
        repo, session = _make_repo()
        session.execute.side_effect = Exception("DB error")
        assert repo.find_by_predicate("user1", Predicate.HAS_NAME) is None


# ============================================================================
# upsert_triple
# ============================================================================


class TestUpsertTriple:
    """Test triple upsert logic."""

    def test_insert_new(self):
        repo, session = _make_repo()
        # find_by_predicate returns None → insert
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_NAME,
            object="Minh",
            embedding=[0.1] * 768,
        )
        result = repo.upsert_triple(triple)
        assert result is not None

    def test_update_existing(self):
        repo, session = _make_repo()
        # find_by_predicate returns existing → update
        existing_row = _make_fact_row("Name: Old", "name")
        mock_result_find = MagicMock()
        mock_result_find.fetchone.return_value = existing_row
        mock_result_existing_meta = MagicMock()
        existing_meta_row = MagicMock()
        existing_meta_row.metadata = {
            "embedding_space_fingerprint": "ollama:embeddinggemma:768"
        }
        mock_result_existing_meta.fetchone.return_value = existing_meta_row
        mock_result_update = MagicMock()
        update_row = MagicMock()
        update_row.id = existing_row.id
        update_row.user_id = "user1"
        update_row.content = "New Name"
        update_row.memory_type = MemoryType.USER_FACT.value
        update_row.importance = 0.5
        update_row.metadata = {"fact_type": "name"}
        update_row.session_id = "sess1"
        update_row.created_at = existing_row.created_at
        update_row.updated_at = existing_row.created_at
        mock_result_update.fetchone.return_value = update_row

        session.execute.side_effect = [
            mock_result_find,
            mock_result_existing_meta,
            mock_result_update,
        ]

        triple = SemanticTriple(
            subject="user1",
            predicate=Predicate.HAS_NAME,
            object="New Name",
            embedding=[0.1] * 768,
        )
        # update_memory_content will be called
        with patch(
            "app.engine.semantic_memory.embeddings.get_embedding_generator",
            side_effect=ImportError("not available"),
        ):
            result = repo.upsert_triple(triple)
        # Should have called find_by_predicate (which found existing), then update_memory_content
        assert result is not None


class TestUpdateMemoryContent:
    """Test content updates when embedding regeneration is unavailable."""

    def test_blocks_missing_org_context_before_embedding_or_db(
        self,
        monkeypatch,
        caplog,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        repo = MockRepo()
        repo._session_factory = MagicMock()
        repo._format_embedding = MagicMock(return_value="[0.1]")
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            result = repo.update_memory_content(
                memory_id=uuid4(),
                user_id="PRIVATE-USER",
                new_content="private update",
                new_metadata={"fact_type": "name"},
            )
        finally:
            current_org_id.reset(token)

        assert result is None
        repo._format_embedding.assert_not_called()
        repo._session_factory.assert_not_called()
        assert "triple_repository_blocked_missing_org_context" in caplog.text
        assert "PRIVATE-USER" not in caplog.text

    def test_preserves_existing_embedding_when_generator_unavailable(self):
        import sys
        import types

        repo, session = _make_repo()
        memory_id = uuid4()
        update_row = MagicMock()
        update_row.id = memory_id
        update_row.user_id = "user1"
        update_row.content = "Updated content"
        update_row.memory_type = MemoryType.USER_FACT.value
        update_row.importance = 0.7
        update_row.metadata = {"fact_type": "name", "confidence": 0.7}
        update_row.session_id = None
        update_row.created_at = datetime.now(timezone.utc)
        update_row.updated_at = datetime.now(timezone.utc)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = update_row
        session.execute.return_value = mock_result

        mock_generator = MagicMock()
        mock_generator.is_available.return_value = False

        fake_embeddings = types.ModuleType("app.engine.semantic_memory.embeddings")
        fake_embeddings.get_embedding_generator = MagicMock(return_value=mock_generator)

        with patch.dict(sys.modules, {"app.engine.semantic_memory.embeddings": fake_embeddings}):
            result = repo.update_memory_content(
                memory_id=memory_id,
                user_id="user1",
                new_content="Updated content",
                new_metadata={"fact_type": "name", "confidence": 0.7},
            )

        assert result is not None
        query = session.execute.call_args[0][0]
        assert "embedding = CAST(:embedding AS vector)" not in query.text
