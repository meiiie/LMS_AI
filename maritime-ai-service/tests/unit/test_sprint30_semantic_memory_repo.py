"""
Tests for Sprint 30: SemanticMemoryRepository coverage.

Covers:
- _format_embedding: vector string formatting
- save_memory: insert + return
- get_by_id: by ID lookup
- delete_by_session: session cleanup
- count_user_memories: with/without type filter
- is_available: connection check
- get_memories_by_type: type-based query (Sprint 27)
- delete_memories_by_keyword: keyword match delete (Sprint 26)
- delete_all_user_memories: factory reset (Sprint 26)
- delete_oldest_insights: FIFO eviction (Sprint 26)
- delete_memory: single memory delete
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from app.models.semantic_memory import MemoryType


# =============================================================================
# Helpers
# =============================================================================


def _make_repo():
    """Create a SemanticMemoryRepository with mocked DB."""
    from app.repositories.semantic_memory_repository import SemanticMemoryRepository

    repo = SemanticMemoryRepository.__new__(SemanticMemoryRepository)
    repo._engine = MagicMock()
    repo._session_factory = MagicMock()
    repo._initialized = True
    return repo


_SENTINEL = object()


def _mock_session(repo, rows=None, fetchone=_SENTINEL, rowcount=0):
    """Set up mock session on repo."""
    mock_session = MagicMock()
    mock_result = MagicMock()

    if rows is not None:
        mock_result.fetchall.return_value = rows
    if fetchone is not _SENTINEL:
        mock_result.fetchone.return_value = fetchone
    mock_result.rowcount = rowcount

    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    repo._session_factory.return_value = mock_session
    return mock_session


# =============================================================================
# _format_embedding
# =============================================================================


class TestFormatEmbedding:
    """Test embedding vector formatting."""

    def test_formats_list_to_pgvector_string(self):
        repo = _make_repo()
        result = repo._format_embedding([0.1, 0.2, 0.3])
        assert result == "[0.1,0.2,0.3]"

    def test_empty_list(self):
        repo = _make_repo()
        result = repo._format_embedding([])
        assert result == "[]"

    def test_none_returns_empty(self):
        repo = _make_repo()
        result = repo._format_embedding(None)
        assert result == "[]"

    def test_single_element(self):
        repo = _make_repo()
        result = repo._format_embedding([0.5])
        assert result == "[0.5]"


# =============================================================================
# save_memory
# =============================================================================


class TestSaveMemory:
    """Test memory saving."""

    def test_successful_save(self, monkeypatch):
        from app.repositories import semantic_memory_repository_runtime as runtime_mod

        repo = _make_repo()

        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.user_id = "user-1"
        mock_row.content = "test"
        mock_row.memory_type = "message"
        mock_row.importance = 0.5
        mock_row.metadata = {}
        mock_row.session_id = None
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = None

        mock_session = _mock_session(repo, fetchone=mock_row)
        inline_space = SimpleNamespace(
            storage_kind="inline",
            provider="google",
            model="models/gemini-embedding-001",
            dimensions=768,
            space_fingerprint="google:models/gemini-embedding-001:768",
        )
        source_contract = SimpleNamespace(
            provider="google",
            model="models/gemini-embedding-001",
            dimensions=768,
            fingerprint="google:models/gemini-embedding-001:768",
        )
        monkeypatch.setattr(
            runtime_mod,
            "get_embedding_write_spaces",
            lambda *_args, **_kwargs: (inline_space,),
        )
        monkeypatch.setattr(
            runtime_mod,
            "get_active_embedding_space_contract",
            lambda: source_contract,
        )
        monkeypatch.setattr(
            runtime_mod,
            "build_shadow_embedding_sync",
            lambda **kwargs: list(kwargs["source_embedding"]),
        )

        from app.models.semantic_memory import SemanticMemoryCreate
        memory = SemanticMemoryCreate(
            user_id="user-1",
            content="test",
            embedding=[0.1, 0.2],
            memory_type=MemoryType.MESSAGE,
            importance=0.5,
        )

        result = repo.save_memory(memory)
        assert result is not None
        assert result.user_id == "user-1"
        params = mock_session.execute.call_args[0][1]
        metadata_payload = json.loads(params["metadata"])
        assert metadata_payload["embedding_space_fingerprint"] == "google:models/gemini-embedding-001:768"

    def test_returns_none_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("DB error")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        from app.models.semantic_memory import SemanticMemoryCreate
        memory = SemanticMemoryCreate(
            user_id="user-1", content="test",
            embedding=[0.1], memory_type=MemoryType.MESSAGE, importance=0.5,
        )
        result = repo.save_memory(memory)
        assert result is None

    def test_empty_embedding_uses_null_vector(self):
        repo = _make_repo()

        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.user_id = "user-1"
        mock_row.content = "test"
        mock_row.memory_type = "message"
        mock_row.importance = 0.5
        mock_row.metadata = {}
        mock_row.session_id = None
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = None

        mock_session = _mock_session(repo, fetchone=mock_row)

        from app.models.semantic_memory import SemanticMemoryCreate
        memory = SemanticMemoryCreate(
            user_id="user-1",
            content="test",
            embedding=[],
            memory_type=MemoryType.MESSAGE,
            importance=0.5,
        )

        result = repo.save_memory(memory)
        assert result is not None
        query = mock_session.execute.call_args[0][0]
        params = mock_session.execute.call_args[0][1]
        assert "NULL" in query.text
        assert "embedding" not in params


# =============================================================================
# get_by_id
# =============================================================================


class TestGetById:
    """Test memory lookup by ID."""

    def test_found(self):
        repo = _make_repo()
        uid = uuid4()
        mock_row = MagicMock()
        mock_row.id = uid
        mock_row.user_id = "user-1"
        mock_row.content = "content"
        mock_row.memory_type = "message"
        mock_row.importance = 0.5
        mock_row.metadata = {}
        mock_row.session_id = None
        mock_row.created_at = datetime.now(timezone.utc)
        mock_row.updated_at = None

        _mock_session(repo, fetchone=mock_row)

        result = repo.get_by_id(uid, "user-1")
        assert result is not None
        assert result.id == uid

    def test_not_found(self):
        repo = _make_repo()
        _mock_session(repo, fetchone=None)
        result = repo.get_by_id(uuid4(), "user-1")
        assert result is None

    def test_returns_none_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("DB error")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.get_by_id(uuid4(), "user-1")
        assert result is None


# =============================================================================
# delete_by_session
# =============================================================================


class TestDeleteBySession:
    """Test session message cleanup."""

    def test_deletes_messages(self):
        repo = _make_repo()
        _mock_session(repo, rows=[MagicMock(), MagicMock(), MagicMock()])

        result = repo.delete_by_session("user-1", "session-1")
        assert result == 3

    def test_no_messages_to_delete(self):
        repo = _make_repo()
        _mock_session(repo, rows=[])

        result = repo.delete_by_session("user-1", "session-1")
        assert result == 0

    def test_returns_zero_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.delete_by_session("user-1", "session-1")
        assert result == 0


# =============================================================================
# count_user_memories
# =============================================================================


class TestCountUserMemories:
    """Test memory counting."""

    def test_counts_all_types(self):
        repo = _make_repo()
        mock_row = MagicMock()
        mock_row.count = 42
        _mock_session(repo, fetchone=mock_row)

        result = repo.count_user_memories("user-1")
        assert result == 42

    def test_counts_by_type(self):
        repo = _make_repo()
        mock_row = MagicMock()
        mock_row.count = 10
        _mock_session(repo, fetchone=mock_row)

        result = repo.count_user_memories("user-1", memory_type=MemoryType.INSIGHT)
        assert result == 10

    def test_returns_zero_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.count_user_memories("user-1")
        assert result == 0


# =============================================================================
# is_available
# =============================================================================


class TestIsAvailable:
    """Test availability check."""

    def test_available(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        assert repo.is_available() is True

    def test_not_available(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("DB down")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        assert repo.is_available() is False


# =============================================================================
# get_memories_by_type (Sprint 27)
# =============================================================================


class TestGetMemoriesByType:
    """Test type-based memory retrieval without cosine similarity."""

    def test_returns_results(self):
        repo = _make_repo()
        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.content = "test message"
        mock_row.memory_type = "message"
        mock_row.importance = 0.5
        mock_row.metadata = {}
        mock_row.created_at = datetime.now(timezone.utc)

        _mock_session(repo, rows=[mock_row])

        result = repo.get_memories_by_type("user-1", MemoryType.MESSAGE)
        assert len(result) == 1
        assert result[0].content == "test message"

    def test_empty_result(self):
        repo = _make_repo()
        _mock_session(repo, rows=[])

        result = repo.get_memories_by_type("user-1", MemoryType.MESSAGE)
        assert result == []

    def test_with_session_filter(self):
        repo = _make_repo()
        _mock_session(repo, rows=[])

        result = repo.get_memories_by_type("user-1", MemoryType.MESSAGE, session_id="sess-1")
        assert result == []
        # Verify session_id was passed in params
        call_args = repo._session_factory.return_value.__enter__.return_value.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert "sess-1" in str(params)

    def test_returns_empty_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.get_memories_by_type("user-1", MemoryType.MESSAGE)
        assert result == []


# =============================================================================
# delete_memories_by_keyword (Sprint 26)
# =============================================================================


class TestDeleteMemoriesByKeyword:
    """Test keyword-based memory deletion."""

    def test_deletes_matching(self):
        repo = _make_repo()
        _mock_session(repo, rows=[MagicMock(), MagicMock()])

        result = repo.delete_memories_by_keyword("user-1", "COLREGs")
        assert result == 2

    def test_no_match(self):
        repo = _make_repo()
        _mock_session(repo, rows=[])

        result = repo.delete_memories_by_keyword("user-1", "nonexistent")
        assert result == 0

    def test_delete_log_hashes_keyword_and_user(self, caplog):
        repo = _make_repo()
        _mock_session(repo, rows=[MagicMock()])
        caplog.set_level(logging.INFO)

        result = repo.delete_memories_by_keyword("user-private-123", "PRIVATE KEYWORD")

        assert result == 1
        assert "keyword_ref=sha256:" in caplog.text
        assert "user_hash=sha256:" in caplog.text
        assert "PRIVATE KEYWORD" not in caplog.text
        assert "user-private-123" not in caplog.text

    def test_returns_zero_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.delete_memories_by_keyword("user-1", "test")
        assert result == 0


# =============================================================================
# delete_all_user_memories (Sprint 26)
# =============================================================================


class TestDeleteAllUserMemories:
    """Test factory reset deletion."""

    def test_deletes_all(self):
        repo = _make_repo()
        _mock_session(repo, rows=[MagicMock()] * 10)

        result = repo.delete_all_user_memories("user-1")
        assert result == 10

    def test_returns_zero_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.delete_all_user_memories("user-1")
        assert result == 0


# =============================================================================
# delete_oldest_insights (Sprint 26)
# =============================================================================


class TestDeleteOldestInsights:
    """Test FIFO eviction of oldest insights."""

    def test_deletes_count(self):
        repo = _make_repo()
        _mock_session(repo, rows=[MagicMock()] * 5)

        result = repo.delete_oldest_insights("user-1", 5)
        assert result == 5

    def test_zero_count_returns_zero(self):
        repo = _make_repo()
        result = repo.delete_oldest_insights("user-1", 0)
        assert result == 0

    def test_negative_count_returns_zero(self):
        repo = _make_repo()
        result = repo.delete_oldest_insights("user-1", -3)
        assert result == 0

    def test_returns_zero_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.delete_oldest_insights("user-1", 5)
        assert result == 0


# =============================================================================
# delete_memory
# =============================================================================


class TestDeleteMemory:
    """Test single memory deletion."""

    def test_successful_delete(self):
        repo = _make_repo()
        _mock_session(repo, fetchone=MagicMock())

        result = repo.delete_memory("user-1", str(uuid4()))
        assert result is True

    def test_not_found(self):
        repo = _make_repo()
        _mock_session(repo, fetchone=None)

        result = repo.delete_memory("user-1", str(uuid4()))
        assert result is False

    def test_returns_false_on_error(self):
        repo = _make_repo()
        mock_session = MagicMock()
        mock_session.execute.side_effect = RuntimeError("fail")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        repo._session_factory.return_value = mock_session

        result = repo.delete_memory("user-1", str(uuid4()))
        assert result is False
