"""
Tests for the Threads API endpoints — app.api.v1.threads

Sprint 16: Virtual Agent-per-User Architecture
Tests cover: list_threads, get_thread, delete_thread, rename_thread,
and Pydantic schema validation for ThreadView / ThreadListResponse.

Approach: directly call the async endpoint functions with mocked
dependencies (get_thread_repository and auth), avoiding httpx ASGITransport
complexity. This is the established pattern in this codebase (see test_auth_ownership.py).
"""

import pytest
from unittest.mock import call, patch, MagicMock

from pydantic import ValidationError

from app.api.v1.threads import (
    ThreadView,
    ThreadListResponse,
    ThreadRenameRequest,
    ThreadActionResponse,
    list_threads,
    get_thread,
    delete_thread,
    rename_thread,
)
from app.core.security import AuthenticatedUser


# =============================================================================
# Helpers
# =============================================================================


def _make_request():
    """Create a real starlette Request for rate-limited endpoints."""
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "GET", "path": "/api/v1/threads",
        "headers": [], "query_string": b"", "root_path": "",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def _make_auth(
    user_id: str = "test-user",
    role: str = "student",
    organization_id: str | None = None,
) -> AuthenticatedUser:
    """Create a mock authenticated user."""
    return AuthenticatedUser(
        user_id=user_id,
        auth_method="api_key",
        role=role,
        organization_id=organization_id,
    )


def _sample_thread_dict(
    thread_id: str = "user_test-user__session_s1",
    user_id: str = "test-user",
    **overrides,
) -> dict:
    """Return a sample thread dict as the repository would return."""
    base = {
        "thread_id": thread_id,
        "user_id": user_id,
        "domain_id": "maritime",
        "title": "Test conversation",
        "message_count": 5,
        "last_message_at": "2026-02-09 10:00:00+00:00",
        "created_at": "2026-02-09 09:00:00+00:00",
        "updated_at": "2026-02-09 10:00:00+00:00",
        "extra_data": {},
    }
    base.update(overrides)
    return base


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestThreadViewSchema:
    """Test ThreadView Pydantic model."""

    def test_valid_thread_view(self):
        """ThreadView accepts a well-formed dict."""
        tv = ThreadView(**_sample_thread_dict())
        assert tv.thread_id == "user_test-user__session_s1"
        assert tv.user_id == "test-user"
        assert tv.domain_id == "maritime"
        assert tv.title == "Test conversation"
        assert tv.message_count == 5
        assert tv.extra_data == {}

    def test_thread_view_defaults(self):
        """ThreadView uses correct defaults for optional fields."""
        tv = ThreadView(thread_id="t1", user_id="u1")
        assert tv.domain_id == "maritime"
        assert tv.title is None
        assert tv.message_count == 0
        assert tv.last_message_at is None
        assert tv.created_at is None
        assert tv.updated_at is None
        assert tv.extra_data == {}

    def test_thread_view_missing_required_fields(self):
        """ThreadView rejects missing required fields."""
        with pytest.raises(ValidationError):
            ThreadView()  # missing thread_id, user_id


class TestThreadListResponseSchema:
    """Test ThreadListResponse Pydantic model."""

    def test_valid_list_response(self):
        """ThreadListResponse wraps threads and total."""
        resp = ThreadListResponse(
            threads=[ThreadView(**_sample_thread_dict())],
            total=1,
        )
        assert resp.status == "success"
        assert len(resp.threads) == 1
        assert resp.total == 1

    def test_empty_list_response(self):
        """ThreadListResponse defaults to empty list and zero total."""
        resp = ThreadListResponse()
        assert resp.threads == []
        assert resp.total == 0
        assert resp.status == "success"


class TestThreadRenameRequestSchema:
    """Test ThreadRenameRequest validation."""

    def test_valid_title(self):
        req = ThreadRenameRequest(title="My conversation")
        assert req.title == "My conversation"

    def test_empty_title_rejected(self):
        """Empty string violates min_length=1."""
        with pytest.raises(ValidationError):
            ThreadRenameRequest(title="")

    def test_long_title_rejected(self):
        """Titles longer than 200 chars are rejected."""
        with pytest.raises(ValidationError):
            ThreadRenameRequest(title="x" * 201)


# =============================================================================
# Endpoint Tests — list_threads
# =============================================================================


class TestListThreads:
    """Test the GET /threads endpoint function."""

    @pytest.mark.asyncio
    async def test_returns_threads(self):
        """list_threads returns thread list from repository."""
        auth = _make_auth("student-1")
        thread_data = [_sample_thread_dict(user_id="student-1")]

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.list_threads.return_value = thread_data
            mock_repo.count_threads.return_value = 1
            mock_get_repo.return_value = mock_repo

            result = await list_threads(request=_make_request(), auth=auth, limit=50, offset=0)

            assert isinstance(result, ThreadListResponse)
            assert result.status == "success"
            assert len(result.threads) == 1
            assert result.threads[0].user_id == "student-1"
            assert result.total == 1

            mock_repo.list_threads.assert_called_once_with(
                user_id="student-1",
                limit=50,
                offset=0,
                organization_id=None,
            )
            mock_repo.count_threads.assert_called_once_with(
                user_id="student-1",
                organization_id=None,
            )

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        """list_threads returns empty response for user with no threads."""
        auth = _make_auth("new-user")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.list_threads.return_value = []
            mock_repo.count_threads.return_value = 0
            mock_get_repo.return_value = mock_repo

            result = await list_threads(request=_make_request(), auth=auth, limit=50, offset=0)

            assert isinstance(result, ThreadListResponse)
            assert result.threads == []
            assert result.total == 0

    @pytest.mark.asyncio
    async def test_passes_active_org_scope_to_repository(self):
        """list_threads keeps the conversation index inside the active org."""
        auth = _make_auth("student-1", organization_id="org-active")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.list_threads.return_value = []
            mock_repo.count_threads.return_value = 0
            mock_get_repo.return_value = mock_repo

            await list_threads(request=_make_request(), auth=auth, limit=25, offset=5)

            mock_repo.list_threads.assert_called_once_with(
                user_id="student-1",
                limit=25,
                offset=5,
                organization_id="org-active",
            )
            mock_repo.count_threads.assert_called_once_with(
                user_id="student-1",
                organization_id="org-active",
            )

    @pytest.mark.asyncio
    async def test_repo_exception_returns_500(self):
        """list_threads returns 500 JSONResponse when repo raises."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_get_repo.side_effect = RuntimeError("DB connection lost")

            result = await list_threads(request=_make_request(), auth=auth, limit=50, offset=0)

            # Should be a JSONResponse with 500 status
            assert result.status_code == 500
            assert result.body is not None


# =============================================================================
# Endpoint Tests — get_thread
# =============================================================================


class TestGetThread:
    """Test the GET /threads/{thread_id} endpoint function."""

    @pytest.mark.asyncio
    async def test_found_returns_thread(self):
        """get_thread returns ThreadView when thread exists."""
        auth = _make_auth("student-1")
        thread_data = _sample_thread_dict(
            thread_id="user_student-1__session_s1",
            user_id="student-1",
        )

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_thread.return_value = thread_data
            mock_get_repo.return_value = mock_repo

            result = await get_thread(
                request=_make_request(), thread_id="user_student-1__session_s1", auth=auth,
            )

            assert isinstance(result, ThreadView)
            assert result.thread_id == "user_student-1__session_s1"
            assert result.user_id == "student-1"

            mock_repo.get_thread.assert_called_once_with(
                thread_id="user_student-1__session_s1",
                user_id="student-1",
                organization_id=None,
            )

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        """get_thread returns 404 JSONResponse when thread is not found."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_thread.return_value = None
            mock_get_repo.return_value = mock_repo

            result = await get_thread(
                request=_make_request(), thread_id="nonexistent-thread", auth=auth,
            )

            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_fallback_keeps_active_org_scope(self):
        """Platform admin fallback does not drop the active org boundary."""
        auth = _make_auth("admin-1", role="admin", organization_id="org-active")
        thread_data = _sample_thread_dict(
            thread_id="user_other__session_s1",
            user_id="other",
        )

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.get_thread.side_effect = [None, thread_data]
            mock_get_repo.return_value = mock_repo

            result = await get_thread(
                request=_make_request(),
                thread_id="user_other__session_s1",
                auth=auth,
            )

            assert isinstance(result, ThreadView)
            mock_repo.get_thread.assert_has_calls(
                [
                    call(
                        thread_id="user_other__session_s1",
                        user_id="admin-1",
                        organization_id="org-active",
                    ),
                    call(
                        thread_id="user_other__session_s1",
                        organization_id="org-active",
                    ),
                ]
            )

    @pytest.mark.asyncio
    async def test_repo_exception_returns_500(self):
        """get_thread returns 500 JSONResponse when repo raises."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_get_repo.side_effect = RuntimeError("DB error")

            result = await get_thread(
                request=_make_request(), thread_id="some-thread", auth=auth,
            )

            assert result.status_code == 500


# =============================================================================
# Endpoint Tests — delete_thread
# =============================================================================


class TestDeleteThread:
    """Test the DELETE /threads/{thread_id} endpoint function."""

    @pytest.mark.asyncio
    async def test_success_returns_action_response(self):
        """delete_thread returns success when thread is deleted."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.delete_thread.return_value = True
            mock_get_repo.return_value = mock_repo

            result = await delete_thread(
                request=_make_request(), thread_id="user_student-1__session_s1", auth=auth,
            )

            assert isinstance(result, ThreadActionResponse)
            assert result.status == "success"
            assert "deleted" in result.message.lower()

            mock_repo.delete_thread.assert_called_once_with(
                thread_id="user_student-1__session_s1",
                user_id="student-1",
                organization_id=None,
            )

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        """delete_thread returns 404 when thread doesn't exist or already deleted."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.delete_thread.return_value = False
            mock_get_repo.return_value = mock_repo

            result = await delete_thread(
                request=_make_request(), thread_id="nonexistent", auth=auth,
            )

            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_passes_active_org_scope(self):
        """delete_thread binds mutations to the active org."""
        auth = _make_auth("student-1", organization_id="org-active")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.delete_thread.return_value = True
            mock_get_repo.return_value = mock_repo

            await delete_thread(
                request=_make_request(),
                thread_id="user_student-1__session_s1",
                auth=auth,
            )

            mock_repo.delete_thread.assert_called_once_with(
                thread_id="user_student-1__session_s1",
                user_id="student-1",
                organization_id="org-active",
            )

    @pytest.mark.asyncio
    async def test_repo_exception_returns_500(self):
        """delete_thread returns 500 when repo raises."""
        auth = _make_auth("student-1")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_get_repo.side_effect = RuntimeError("DB gone")

            result = await delete_thread(
                request=_make_request(), thread_id="some-thread", auth=auth,
            )

            assert result.status_code == 500


# =============================================================================
# Endpoint Tests — rename_thread
# =============================================================================


class TestRenameThread:
    """Test the PATCH /threads/{thread_id}/title endpoint function."""

    @pytest.mark.asyncio
    async def test_success_returns_action_response(self):
        """rename_thread returns success when thread is renamed."""
        auth = _make_auth("student-1")
        body = ThreadRenameRequest(title="My new title")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.rename_thread.return_value = True
            mock_get_repo.return_value = mock_repo

            result = await rename_thread(
                request=_make_request(), thread_id="user_student-1__session_s1",
                body=body,
                auth=auth,
            )

            assert isinstance(result, ThreadActionResponse)
            assert result.status == "success"
            assert "renamed" in result.message.lower()

            mock_repo.rename_thread.assert_called_once_with(
                thread_id="user_student-1__session_s1",
                user_id="student-1",
                title="My new title",
                organization_id=None,
            )

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        """rename_thread returns 404 when thread doesn't exist."""
        auth = _make_auth("student-1")
        body = ThreadRenameRequest(title="New title")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.rename_thread.return_value = False
            mock_get_repo.return_value = mock_repo

            result = await rename_thread(
                request=_make_request(), thread_id="nonexistent", body=body, auth=auth,
            )

            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_rename_passes_active_org_scope(self):
        """rename_thread binds mutations to the active org."""
        auth = _make_auth("student-1", organization_id="org-active")
        body = ThreadRenameRequest(title="Scoped title")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_repo.rename_thread.return_value = True
            mock_get_repo.return_value = mock_repo

            await rename_thread(
                request=_make_request(),
                thread_id="user_student-1__session_s1",
                body=body,
                auth=auth,
            )

            mock_repo.rename_thread.assert_called_once_with(
                thread_id="user_student-1__session_s1",
                user_id="student-1",
                title="Scoped title",
                organization_id="org-active",
            )

    @pytest.mark.asyncio
    async def test_repo_exception_returns_500(self):
        """rename_thread returns 500 when repo raises."""
        auth = _make_auth("student-1")
        body = ThreadRenameRequest(title="Title")

        with patch("app.repositories.thread_repository.get_thread_repository") as mock_get_repo:
            mock_get_repo.side_effect = RuntimeError("DB error")

            result = await rename_thread(
                request=_make_request(), thread_id="some-thread", body=body, auth=auth,
            )

            assert result.status_code == 500
