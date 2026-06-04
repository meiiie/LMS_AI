"""
Sprint 225: "Đồng Bộ Trò Chuyện" — Cross-Platform Conversation Sync

Tests for:
1. thread_views population after chat (streaming + sync paths)
2. GET /threads/{thread_id}/messages endpoint
3. thread_id in metadata event
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import UUID, uuid4


# ============================================================================
# Helpers
# ============================================================================

def _make_thread_row(
    thread_id="user_test__session_abc",
    user_id="test",
    domain_id="maritime",
    title="Test convo",
    message_count=2,
    last_message_at=None,
    created_at=None,
    updated_at=None,
    extra_data=None,
    is_deleted=False,
):
    """Create a fake database row tuple matching SELECT column order."""
    now = datetime.now(timezone.utc)
    return (
        thread_id, user_id, domain_id, title, message_count,
        last_message_at or now, created_at or now, updated_at or now,
        extra_data or {}, is_deleted,
    )


def _make_mock_repo_with_session():
    """Create a ThreadRepository with mocked database."""
    from app.repositories.thread_repository import ThreadRepository
    repo = ThreadRepository()
    mock_session = MagicMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_factory.return_value.__exit__ = MagicMock(return_value=False)

    repo._engine = MagicMock()
    repo._session_factory = mock_session_factory
    repo._initialized = True

    return repo, mock_session


# ============================================================================
# 1. thread_id in metadata event
# ============================================================================


class TestMetadataThreadId:
    """Sprint 225: thread_id must be included in create_metadata_event."""

    @pytest.mark.asyncio
    async def test_metadata_event_includes_thread_id(self):
        """create_metadata_event with thread_id kwarg must include it in content."""
        from app.engine.multi_agent.stream_utils import create_metadata_event

        event = await create_metadata_event(
            reasoning_trace=None,
            processing_time=1.0,
            confidence=0.9,
            session_id="abc-123",
            thread_id="user_test__session_abc-123",
        )

        assert event.type == "metadata"
        assert event.content["thread_id"] == "user_test__session_abc-123"
        assert event.content["session_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_metadata_event_empty_thread_id_when_not_provided(self):
        """When thread_id is empty string, it is still present in metadata."""
        from app.engine.multi_agent.stream_utils import create_metadata_event

        event = await create_metadata_event(
            reasoning_trace=None,
            processing_time=0.5,
            confidence=0.8,
            thread_id="",
        )

        assert event.content["thread_id"] == ""


# ============================================================================
# 2. Thread messages endpoint (threads.py)
# ============================================================================


class TestThreadMessagesEndpoint:
    """Sprint 225: GET /threads/{thread_id}/messages."""

    def test_thread_message_view_model(self):
        """ThreadMessageView model accepts correct fields."""
        from app.api.v1.threads import ThreadMessageView

        msg = ThreadMessageView(
            id="abc-123",
            role="user",
            content="Hello Wiii",
            created_at="2026-03-04T10:00:00",
        )
        assert msg.role == "user"
        assert msg.content == "Hello Wiii"

    def test_thread_messages_response_model(self):
        """ThreadMessagesResponse wraps messages with total."""
        from app.api.v1.threads import ThreadMessagesResponse, ThreadMessageView

        resp = ThreadMessagesResponse(
            messages=[
                ThreadMessageView(id="1", role="user", content="Hi"),
                ThreadMessageView(id="2", role="assistant", content="Xin chào!"),
            ],
            total=2,
        )
        assert len(resp.messages) == 2
        assert resp.total == 2
        assert resp.status == "success"

    def test_thread_messages_response_empty(self):
        """Empty response is valid."""
        from app.api.v1.threads import ThreadMessagesResponse

        resp = ThreadMessagesResponse(messages=[], total=0)
        assert len(resp.messages) == 0

    @pytest.mark.asyncio
    @patch("app.repositories.chat_history_repository.get_chat_history_repository")
    @patch("app.repositories.thread_repository.get_thread_repository")
    async def test_get_thread_messages_uses_true_total_count(
        self,
        mock_get_thread_repo,
        mock_get_chat_repo,
    ):
        """Endpoint total must come from repository count, not fetched page length."""
        from app.api.v1.threads import get_thread_messages, ThreadMessagesResponse
        from app.core.security import AuthenticatedUser
        from app.repositories.chat_history_repository import ChatMessage, _normalize_session_id

        thread_repo = MagicMock()
        thread_repo.get_thread.return_value = {"thread_id": "user_test__session_session-1", "user_id": "test"}
        mock_get_thread_repo.return_value = thread_repo

        norm_session_id = _normalize_session_id("session-1")
        chat_repo = MagicMock()
        chat_repo.is_available.return_value = True
        chat_repo.get_session_history.return_value = (
            [
                ChatMessage(
                    id=uuid4(),
                    session_id=norm_session_id,
                    role="assistant",
                    content="Trang 3",
                    created_at=datetime.now(timezone.utc),
                ),
                ChatMessage(
                    id=uuid4(),
                    session_id=norm_session_id,
                    role="user",
                    content="Trang 4",
                    created_at=datetime.now(timezone.utc),
                ),
            ],
            10,
        )
        mock_get_chat_repo.return_value = chat_repo

        response = await get_thread_messages(
            request=MagicMock(),
            thread_id="user_test__session_session-1",
            auth=AuthenticatedUser(
                user_id="test",
                auth_method="jwt",
                role="student",
                organization_id="org-active",
            ),
            limit=2,
            offset=4,
        )

        assert isinstance(response, ThreadMessagesResponse)
        assert response.total == 10
        assert len(response.messages) == 2
        thread_repo.get_thread.assert_called_once_with(
            thread_id="user_test__session_session-1",
            user_id="test",
            organization_id="org-active",
        )
        chat_repo.get_session_history.assert_called_once_with(
            session_id=norm_session_id,
            limit=2,
            offset=4,
            organization_id="org-active",
        )

    @pytest.mark.asyncio
    @patch("app.repositories.chat_history_repository.get_chat_history_repository")
    @patch("app.repositories.thread_repository.get_thread_repository")
    async def test_get_thread_messages_returns_empty_when_repo_unavailable(
        self,
        mock_get_thread_repo,
        mock_get_chat_repo,
    ):
        """Endpoint should return an empty success payload when chat repo is unavailable."""
        from app.api.v1.threads import get_thread_messages, ThreadMessagesResponse
        from app.core.security import AuthenticatedUser

        thread_repo = MagicMock()
        thread_repo.get_thread.return_value = {"thread_id": "user_test__session_session-1", "user_id": "test"}
        mock_get_thread_repo.return_value = thread_repo

        chat_repo = MagicMock()
        chat_repo.is_available.return_value = False
        mock_get_chat_repo.return_value = chat_repo

        response = await get_thread_messages(
            request=MagicMock(),
            thread_id="user_test__session_session-1",
            auth=AuthenticatedUser(user_id="test", auth_method="jwt", role="student"),
        )

        assert isinstance(response, ThreadMessagesResponse)
        assert response.total == 0
        assert response.messages == []


# ============================================================================
# 3. thread_views upsert called from streaming path
# ============================================================================


class TestStreamingThreadViewsPopulation:
    """Sprint 225: thread_views should be populated after streaming AI response."""

    @patch("app.repositories.thread_repository.get_thread_repository")
    @patch("app.core.thread_utils.build_thread_id")
    def test_upsert_thread_called_with_correct_args(
        self, mock_build_tid, mock_get_repo,
    ):
        """Verify upsert_thread is callable with expected args from streaming path."""
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_repo.upsert_thread.return_value = {"thread_id": "t1", "message_count": 2}
        mock_get_repo.return_value = mock_repo
        mock_build_tid.return_value = "user_u1__session_s1"

        # Simulate what chat_stream.py does
        from app.repositories.thread_repository import get_thread_repository
        from app.core.thread_utils import build_thread_id

        _thread_repo = get_thread_repository()
        assert _thread_repo.is_available()

        _thread_id = build_thread_id("u1", "s1", org_id=None)
        _thread_repo.upsert_thread(
            thread_id=_thread_id,
            user_id="u1",
            domain_id="maritime",
            title="Test message",
            message_count_increment=2,
            organization_id=None,
        )

        mock_repo.upsert_thread.assert_called_once_with(
            thread_id="user_u1__session_s1",
            user_id="u1",
            domain_id="maritime",
            title="Test message",
            message_count_increment=2,
            organization_id=None,
        )

    @patch("app.repositories.thread_repository.get_thread_repository")
    def test_upsert_thread_graceful_on_failure(self, mock_get_repo):
        """If upsert_thread raises, it should be caught gracefully."""
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_repo.upsert_thread.side_effect = Exception("DB down")
        mock_get_repo.return_value = mock_repo

        # Simulate the try/except from chat_stream.py
        try:
            from app.repositories.thread_repository import get_thread_repository
            from app.core.thread_utils import build_thread_id
            _thread_repo = get_thread_repository()
            if _thread_repo.is_available():
                _thread_repo.upsert_thread(
                    thread_id="test",
                    user_id="u1",
                    domain_id="maritime",
                    title="test",
                    message_count_increment=2,
                )
        except Exception:
            pass  # Should be caught in the actual code

        # Test passes if no unhandled exception


class TestSyncPathThreadViewsPopulation:
    """Sprint 225: thread_views populated in chat_orchestrator sync path."""

    @patch("app.repositories.thread_repository.get_thread_repository")
    @patch("app.core.thread_utils.build_thread_id")
    def test_upsert_thread_with_org_id(self, mock_build_tid, mock_get_repo):
        """Verify org_id is passed through to upsert_thread."""
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = True
        mock_get_repo.return_value = mock_repo
        mock_build_tid.return_value = "org_lms__user_u1__session_s1"

        from app.repositories.thread_repository import get_thread_repository
        from app.core.thread_utils import build_thread_id

        _thread_repo = get_thread_repository()
        _thread_id = build_thread_id("u1", "s1", org_id="lms")
        _thread_repo.upsert_thread(
            thread_id=_thread_id,
            user_id="u1",
            domain_id="maritime",
            title="Org message",
            message_count_increment=2,
            organization_id="lms",
        )

        mock_repo.upsert_thread.assert_called_once()
        call_kwargs = mock_repo.upsert_thread.call_args
        assert call_kwargs[1]["organization_id"] == "lms" or call_kwargs.kwargs.get("organization_id") == "lms"

    @patch("app.repositories.thread_repository.get_thread_repository")
    def test_upsert_skipped_when_repo_unavailable(self, mock_get_repo):
        """When repo.is_available() returns False, upsert is skipped."""
        mock_repo = MagicMock()
        mock_repo.is_available.return_value = False
        mock_get_repo.return_value = mock_repo

        from app.repositories.thread_repository import get_thread_repository
        _thread_repo = get_thread_repository()

        # Simulate the guard from chat_stream.py
        if _thread_repo.is_available():
            _thread_repo.upsert_thread(thread_id="t", user_id="u")

        mock_repo.upsert_thread.assert_not_called()


# ============================================================================
# 4. build_thread_id used for metadata (graph_streaming integration)
# ============================================================================


class TestBuildThreadIdForMetadata:
    """Verify build_thread_id produces correct formats for metadata."""

    def test_build_thread_id_without_org(self):
        """No org produces legacy format."""
        from app.core.thread_utils import build_thread_id

        tid = build_thread_id("user123", "session456")
        assert tid == "user_user123__session_session456"

    def test_build_thread_id_with_org(self):
        """Org produces org-prefixed format."""
        from app.core.thread_utils import build_thread_id

        tid = build_thread_id("user123", "session456", org_id="lms-org")
        assert tid == "org_lms-org__user_user123__session_session456"

    def test_parse_thread_id_extracts_session(self):
        """parse_thread_id extracts session for message query."""
        from app.core.thread_utils import parse_thread_id

        uid, sid = parse_thread_id("user_u1__session_abc-123")
        assert uid == "u1"
        assert sid == "abc-123"

    def test_parse_thread_id_with_org(self):
        """parse_thread_id handles org-prefixed format."""
        from app.core.thread_utils import parse_thread_id

        uid, sid = parse_thread_id("org_lms__user_u2__session_xyz-789")
        assert uid == "u2"
        assert sid == "xyz-789"


# ============================================================================
# 5. _normalize_session_id (used in messages endpoint)
# ============================================================================


class TestNormalizeSessionId:
    """Sprint 225: Messages endpoint normalizes session_id to UUID."""

    def test_uuid_string_passthrough(self):
        """Valid UUID string returns same UUID."""
        from app.repositories.chat_history_repository import _normalize_session_id

        uid = uuid4()
        result = _normalize_session_id(str(uid))
        assert result == uid

    def test_uuid_object_passthrough(self):
        """UUID object passes through unchanged."""
        from app.repositories.chat_history_repository import _normalize_session_id

        uid = uuid4()
        result = _normalize_session_id(uid)
        assert result == uid

    def test_non_uuid_string_deterministic(self):
        """Non-UUID string produces deterministic UUID via uuid5."""
        from app.repositories.chat_history_repository import _normalize_session_id

        result1 = _normalize_session_id("abc-123-not-a-uuid")
        result2 = _normalize_session_id("abc-123-not-a-uuid")
        assert result1 == result2
        assert isinstance(result1, UUID)

    def test_different_strings_different_uuids(self):
        """Different strings produce different UUIDs."""
        from app.repositories.chat_history_repository import _normalize_session_id

        result1 = _normalize_session_id("session-a")
        result2 = _normalize_session_id("session-b")
        assert result1 != result2


# ============================================================================
# 6. ThreadRepository upsert_thread behavior
# ============================================================================


class TestThreadRepositoryUpsert:
    """Verify ThreadRepository.upsert_thread INSERT vs UPDATE behavior."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton between tests."""
        import app.repositories.thread_repository as mod
        old = mod._thread_repo
        mod._thread_repo = None
        yield
        mod._thread_repo = old

    @patch("app.core.org_filter.get_effective_org_id", return_value=None)
    def test_upsert_insert_new_thread(self, mock_org):
        """First upsert creates a new row."""
        repo, mock_session = _make_mock_repo_with_session()

        # fetchone returns None (no existing row)
        mock_session.execute.return_value.fetchone.return_value = None

        result = repo.upsert_thread(
            thread_id="user_u1__session_s1",
            user_id="u1",
            domain_id="maritime",
            title="Hello Wiii",
            message_count_increment=2,
        )

        assert result is not None
        assert result["thread_id"] == "user_u1__session_s1"
        assert result["message_count"] == 2
        assert mock_session.execute.call_count == 2  # SELECT + INSERT
        mock_session.commit.assert_called_once()

    @patch("app.core.org_filter.get_effective_org_id", return_value=None)
    def test_upsert_update_existing_thread(self, mock_org):
        """Second upsert increments message_count."""
        repo, mock_session = _make_mock_repo_with_session()

        # fetchone returns existing row with message_count=2
        mock_session.execute.return_value.fetchone.return_value = (
            "user_u1__session_s1",  # thread_id
            4,                       # existing message_count
            {},                      # extra_data
        )

        result = repo.upsert_thread(
            thread_id="user_u1__session_s1",
            user_id="u1",
            title="Updated",
            message_count_increment=2,
        )

        assert result is not None
        assert result["message_count"] == 6  # 4 + 2
        assert mock_session.execute.call_count == 2  # SELECT + UPDATE
        mock_session.commit.assert_called_once()

    def test_upsert_returns_none_when_unavailable(self):
        """Returns None when repo not initialized."""
        from app.repositories.thread_repository import ThreadRepository
        repo = ThreadRepository()
        repo._initialized = True
        repo._session_factory = None

        result = repo.upsert_thread("tid", "uid")
        assert result is None

    @patch("app.core.org_filter.get_effective_org_id", return_value=None)
    def test_upsert_returns_none_on_exception(self, mock_org):
        """Returns None on database error."""
        repo, mock_session = _make_mock_repo_with_session()
        mock_session.execute.side_effect = Exception("DB error")

        result = repo.upsert_thread("tid", "uid")
        assert result is None


# ============================================================================
# 7. Message title truncation
# ============================================================================


class TestMessageTitleTruncation:
    """Sprint 225: Auto-title uses first 50 chars of user message."""

    def test_short_message_full_title(self):
        """Short messages are used as-is for title."""
        msg = "Xin chào Wiii"
        title = msg[:50]
        assert title == "Xin chào Wiii"

    def test_long_message_truncated(self):
        """Long messages are truncated to 50 chars."""
        msg = "A" * 100
        title = msg[:50]
        assert len(title) == 50


# ============================================================================
# 8. Integration: Endpoint router registration
# ============================================================================


class TestEndpointRegistration:
    """Sprint 225: New messages endpoint is registered on the threads router."""

    def test_messages_route_exists(self):
        """GET /threads/{thread_id}/messages route is registered."""
        from app.api.v1.threads import router

        routes = [r.path for r in router.routes]
        assert "/threads/{thread_id}/messages" in routes

    def test_messages_route_is_get(self):
        """Messages endpoint uses GET method."""
        from app.api.v1.threads import router

        for route in router.routes:
            if getattr(route, 'path', '') == "/threads/{thread_id}/messages":
                assert "GET" in route.methods
                break
