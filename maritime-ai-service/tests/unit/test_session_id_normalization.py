"""Tests for session normalization and chat_history-only repository behavior."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest


class TestNormalizeSessionId:
    """Tests for the module-level _normalize_session_id helper."""

    def test_uuid_object_passes_through_unchanged(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        original = uuid4()
        assert _normalize_session_id(original) is original

    def test_valid_uuid_string_converted_to_uuid(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        uuid_str = "12345678-1234-5678-1234-567812345678"
        assert _normalize_session_id(uuid_str) == UUID(uuid_str)

    def test_non_uuid_string_gets_uuid5_mapping(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        session_str = "my-custom-session"
        assert _normalize_session_id(session_str) == uuid5(NAMESPACE_DNS, session_str)

    def test_deterministic_same_input_same_output(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        assert _normalize_session_id("test-session-abc") == _normalize_session_id(
            "test-session-abc"
        )

    def test_none_is_coerced_deterministically(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        assert _normalize_session_id(None) == uuid5(NAMESPACE_DNS, "None")

    def test_org_prefixed_thread_id_is_supported(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        thread_id = "org_lms-hang-hai__user_student-123__session_abc"
        assert _normalize_session_id(thread_id) == uuid5(NAMESPACE_DNS, thread_id)


def _make_repo(**overrides):
    with patch(
        "app.repositories.chat_history_repository.ChatHistoryRepository._init_connection"
    ):
        from app.repositories.chat_history_repository import ChatHistoryRepository

        repo = ChatHistoryRepository()

    repo._available = overrides.get("available", True)
    repo._has_chat_history = overrides.get("has_chat_history", True)
    repo._session_factory = overrides.get("session_factory", MagicMock())
    repo._engine = overrides.get("engine", MagicMock())
    repo.ensure_tables = MagicMock()
    return repo


def _mock_session_context(repo):
    mock_db_session = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_db_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    repo._session_factory = MagicMock(return_value=mock_ctx)
    return mock_db_session


class TestGetOrCreateSessionScoping:
    """Tests for org-aware session lookup in chat_history."""

    def test_get_or_create_session_filters_by_org(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        existing_session_id = uuid4()
        created_at = datetime.now(timezone.utc)
        mock_db.execute.return_value.fetchone.return_value = (
            str(existing_session_id),
            created_at,
        )

        with patch("app.core.config.settings.enable_multi_tenant", True):
            result = repo.get_or_create_session("user-1", organization_id="org-1")

        execute_call = mock_db.execute.call_args
        sql = str(execute_call[0][0])
        params = execute_call[0][1]

        assert "organization_id" in sql
        assert params["user_id"] == "user-1"
        assert params["org_id"] == "org-1"
        assert result is not None
        assert result.session_id == existing_session_id

    def test_get_or_create_session_creates_transient_session_when_empty(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        mock_db.execute.return_value.fetchone.return_value = None

        result = repo.get_or_create_session("user-1", organization_id="org-1")

        assert result is not None
        assert result.user_id == "user-1"
        assert isinstance(result.session_id, UUID)

    def test_get_or_create_session_attempts_table_bootstrap_when_missing(self):
        repo = _make_repo(has_chat_history=False)
        repo.ensure_tables.side_effect = lambda: setattr(repo, "_has_chat_history", True)
        mock_db = _mock_session_context(repo)
        mock_db.execute.return_value.fetchone.return_value = None

        result = repo.get_or_create_session("user-1")

        repo.ensure_tables.assert_called_once()
        assert result is not None


class TestSaveMessageNormalization:
    """Tests that save_message correctly normalizes session_id."""

    def test_save_message_normalizes_non_uuid_string(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        repo = _make_repo()
        _mock_session_context(repo)

        result = repo.save_message(
            session_id="test-sprint78-context",
            role="user",
            content="Hello",
            user_id="student-1",
        )

        assert result is not None
        assert result.session_id == _normalize_session_id("test-sprint78-context")

    def test_save_message_uses_normalized_uuid_in_insert(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        non_uuid_id = "user_123__session_abc"

        repo.save_message(
            session_id=non_uuid_id,
            role="assistant",
            content="Hi there",
            user_id="user_123",
        )

        params = mock_db.execute.call_args[0][1]
        assert params["session_id"] == str(_normalize_session_id(non_uuid_id))

    def test_save_message_passes_org_id(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)

        repo.save_message(
            uuid4(),
            "user",
            "hello",
            user_id="u1",
            organization_id="org-1",
        )

        params = mock_db.execute.call_args[0][1]
        assert params["org_id"] == "org-1"

    def test_save_message_includes_created_at_in_insert(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)

        repo.save_message(uuid4(), "user", "hello", user_id="u1")

        sql = str(mock_db.execute.call_args[0][0])
        params = mock_db.execute.call_args[0][1]
        assert "created_at" in sql
        assert isinstance(params["created_at"], datetime)

    def test_save_message_returns_none_when_unavailable(self):
        repo = _make_repo(available=False)

        assert repo.save_message("anything", "user", "Test") is None


class TestGetRecentMessagesNormalization:
    """Tests that get_recent_messages correctly normalizes session_id."""

    def test_get_recent_normalizes_non_uuid_session_id(self):
        from app.repositories.chat_history_repository import _normalize_session_id

        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        mock_db.execute.return_value.fetchall.return_value = []

        messages = repo.get_recent_messages(session_id="test-sprint78-context")

        assert messages == []
        params = mock_db.execute.call_args[0][1]
        assert params["query_value"] == str(
            _normalize_session_id("test-sprint78-context")
        )

    def test_get_recent_with_user_id_queries_by_user(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        mock_db.execute.return_value.fetchall.return_value = []

        repo.get_recent_messages(session_id="ignored", user_id="student-123")

        sql = str(mock_db.execute.call_args[0][0])
        params = mock_db.execute.call_args[0][1]
        assert "WHERE user_id = :query_value" in sql
        assert params["query_value"] == "student-123"

    def test_get_recent_excludes_blocked_by_default(self):
        repo = _make_repo()
        mock_db = _mock_session_context(repo)
        mock_db.execute.return_value.fetchall.return_value = []

        repo.get_recent_messages(session_id=uuid4())

        sql = str(mock_db.execute.call_args[0][0])
        assert "is_blocked = FALSE" in sql

    def test_get_recent_returns_empty_when_unavailable(self):
        repo = _make_repo(available=False)

        assert repo.get_recent_messages(session_id="anything") == []
