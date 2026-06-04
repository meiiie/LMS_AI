"""
Tests for Sprint 53: summarize_tasks coverage.

Tests background summarization:
- summarize_thread_background (success, error, none-summary)
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ============================================================================
# summarize_thread_background
# ============================================================================


class TestSummarizeThreadBackground:
    """Test background summarization task."""

    @pytest.mark.asyncio
    async def test_success(self):
        mock_summarizer = MagicMock()
        mock_summarizer.summarize_thread = AsyncMock(return_value="User discussed SOLAS chapter III")

        with patch("app.services.session_summarizer.get_session_summarizer",
                    return_value=mock_summarizer):
            from app.tasks.summarize_tasks import summarize_thread_background
            result = await summarize_thread_background(
                "thread-1",
                "user-1",
                organization_id="org-active",
            )

        assert result["thread_id"] == "thread-1"
        assert result["summary"] == "User discussed SOLAS chapter III"
        assert result["success"] is True
        mock_summarizer.summarize_thread.assert_awaited_once_with(
            thread_id="thread-1",
            user_id="user-1",
            organization_id="org-active",
        )

    @pytest.mark.asyncio
    async def test_none_summary(self):
        mock_summarizer = MagicMock()
        mock_summarizer.summarize_thread = AsyncMock(return_value=None)

        with patch("app.services.session_summarizer.get_session_summarizer",
                    return_value=mock_summarizer):
            from app.tasks.summarize_tasks import summarize_thread_background
            result = await summarize_thread_background("thread-1", "user-1")

        assert result["thread_id"] == "thread-1"
        assert result["summary"] is None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_error(self):
        with patch("app.services.session_summarizer.get_session_summarizer",
                    side_effect=Exception("Summarizer unavailable")):
            from app.tasks.summarize_tasks import summarize_thread_background
            result = await summarize_thread_background("thread-1", "user-1")

        assert result["thread_id"] == "thread-1"
        assert result["success"] is False
        assert "error" in result
        assert "Summarizer unavailable" in result["error"]

    @pytest.mark.asyncio
    async def test_summarize_thread_error(self):
        mock_summarizer = MagicMock()
        mock_summarizer.summarize_thread = AsyncMock(side_effect=Exception("DB timeout"))

        with patch("app.services.session_summarizer.get_session_summarizer",
                    return_value=mock_summarizer):
            from app.tasks.summarize_tasks import summarize_thread_background
            result = await summarize_thread_background("thread-2", "user-2")

        assert result["thread_id"] == "thread-2"
        assert result["success"] is False
        assert "DB timeout" in result["error"]
