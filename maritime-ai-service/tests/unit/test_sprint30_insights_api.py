"""
Tests for Sprint 30: Insights API endpoint functional coverage.

Sprint 28 already has structural tests (auth param, source inspection).
This adds functional tests: successful retrieval, category filtering,
ownership, empty results, error handling.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from uuid import uuid4


# =============================================================================
# Helpers
# =============================================================================

def _make_request():
    """Create a real starlette Request for rate-limited endpoints."""
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "GET", "path": "/api/v1/insights/user-1",
        "headers": [], "query_string": b"", "root_path": "",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def _make_auth(user_id="user-1", role="student"):
    auth = MagicMock()
    auth.user_id = user_id
    auth.role = role
    auth.__bool__ = lambda self: True
    return auth


def _make_insight(
    insight_id=None,
    category="learning_style",
    content="Visual learner",
    confidence=0.9,
    sub_topic=None,
):
    insight = MagicMock()
    insight.id = insight_id or uuid4()
    insight.content = content
    insight.metadata = {
        "insight_category": category,
        "confidence": confidence,
        "sub_topic": sub_topic,
        "evolution_notes": [],
    }
    insight.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    insight.updated_at = None
    return insight


# =============================================================================
# GET /{user_id} — List insights
# =============================================================================


class TestGetUserInsights:
    """Test get_user_insights endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.v1.insights import get_user_insights

        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.total == 0
        assert result.data == []
        assert result.categories == {}

    @pytest.mark.asyncio
    async def test_returns_insights(self):
        from app.api.v1.insights import get_user_insights

        insights = [
            _make_insight(category="learning_style", content="Visual"),
            _make_insight(category="knowledge_gap", content="COLREGs weak"),
        ]
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = insights

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.total == 2
        assert len(result.data) == 2
        assert result.categories == {"learning_style": 1, "knowledge_gap": 1}

    @pytest.mark.asyncio
    async def test_filters_by_category(self):
        from app.api.v1.insights import get_user_insights

        insights = [
            _make_insight(category="learning_style"),
            _make_insight(category="knowledge_gap"),
            _make_insight(category="learning_style"),
        ]
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = insights

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(
                request=_make_request(), user_id="user-1", auth=_make_auth("user-1"), category="learning_style"
            )

        assert result.total == 2
        assert all(item.category == "learning_style" for item in result.data)

    @pytest.mark.asyncio
    async def test_category_filter_no_match(self):
        from app.api.v1.insights import get_user_insights

        insights = [_make_insight(category="learning_style")]
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = insights

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(
                request=_make_request(), user_id="user-1", auth=_make_auth("user-1"), category="nonexistent"
            )

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_insight_item_fields(self):
        from app.api.v1.insights import get_user_insights

        uid = uuid4()
        insights = [_make_insight(
            insight_id=uid,
            category="habit",
            content="Studies at night",
            confidence=0.85,
            sub_topic="study_time",
        )]
        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = insights

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        item = result.data[0]
        assert item.id == str(uid)
        assert item.category == "habit"
        assert item.content == "Studies at night"
        assert item.confidence == 0.85
        assert item.sub_topic == "study_time"

    @pytest.mark.asyncio
    async def test_ownership_check_forbids_other_users(self):
        from app.api.v1.insights import get_user_insights
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_user_insights(request=_make_request(), user_id="user-2", auth=_make_auth("user-1", "student"))

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_other_users(self):
        from app.api.v1.insights import get_user_insights

        mock_repo = MagicMock()
        mock_repo.get_user_insights.return_value = []

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_insights(request=_make_request(), user_id="user-2", auth=_make_auth("admin-1", "admin"))

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_null_auth_returns_401(self):
        """Defensive check: if auth is somehow None, return 401."""
        from app.api.v1.insights import get_user_insights
        from fastapi import HTTPException

        fake_auth = MagicMock()
        fake_auth.__bool__ = lambda self: False  # Simulates "if not auth"

        with pytest.raises(HTTPException) as exc_info:
            await get_user_insights(request=_make_request(), user_id="user-1", auth=fake_auth)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_repository_error_returns_500(self):
        from app.api.v1.insights import get_user_insights
        from fastapi import HTTPException

        mock_repo = MagicMock()
        mock_repo.get_user_insights.side_effect = RuntimeError("DB error")

        with patch("app.api.v1.insights.SemanticMemoryRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_insights(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert exc_info.value.status_code == 500
        assert "DB error" not in exc_info.value.detail  # No internal leak

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_read(
        self,
        monkeypatch,
    ):
        from app.api.v1.insights import get_user_insights
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from fastapi import HTTPException

        mock_repo = MagicMock()
        repo_factory = MagicMock(return_value=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        token = current_org_id.set(None)
        try:
            with patch(
                "app.api.v1.insights.SemanticMemoryRepository",
                repo_factory,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await get_user_insights(
                        request=_make_request(),
                        user_id="user-private-123",
                        auth=_make_auth("user-private-123"),
                    )
        finally:
            current_org_id.reset(token)

        assert exc_info.value.status_code == 403
        assert "Organization context required for memory access" in exc_info.value.detail
        repo_factory.assert_not_called()
        mock_repo.get_user_insights.assert_not_called()
