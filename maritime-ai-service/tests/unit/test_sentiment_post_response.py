"""Tests for Living sentiment post-response scheduling helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.living_continuity import PostResponseContinuityContext
from app.services.sentiment_post_response import (
    schedule_living_sentiment_continuity,
)


def _make_context() -> PostResponseContinuityContext:
    return PostResponseContinuityContext(
        user_id="user-1",
        user_role="student",
        message="Explain Rule 5",
        response_text="Rule 5 is lookout.",
        session_id="session-1",
        domain_id="maritime",
        organization_id="org-1",
        channel="web",
    )


def _consume_scheduled_coroutine(coroutine):
    coroutine.close()
    return MagicMock()


def _close_then_raise(coroutine):
    coroutine.close()
    raise RuntimeError("boom")


def test_sentiment_post_response_respects_feature_flag():
    analyzer = AsyncMock()

    with patch(
        "app.services.sentiment_post_response.settings",
        MagicMock(enable_living_continuity=False),
    ), patch(
        "app.services.sentiment_post_response.asyncio.ensure_future",
        side_effect=_consume_scheduled_coroutine,
    ) as mock_ensure_future:
        scheduled = schedule_living_sentiment_continuity(
            _make_context(),
            analyze_and_process_sentiment=analyzer,
        )

    assert scheduled is False
    mock_ensure_future.assert_not_called()
    analyzer.assert_not_called()


def test_sentiment_post_response_schedules_analysis_when_enabled():
    analyzer = AsyncMock()

    with patch(
        "app.services.sentiment_post_response.settings",
        MagicMock(enable_living_continuity=True),
    ), patch(
        "app.services.sentiment_post_response.asyncio.ensure_future",
        side_effect=_consume_scheduled_coroutine,
    ) as mock_ensure_future:
        scheduled = schedule_living_sentiment_continuity(
            _make_context(),
            analyze_and_process_sentiment=analyzer,
        )

    assert scheduled is True
    analyzer.assert_called_once_with(
        user_id="user-1",
        user_role="student",
        message="Explain Rule 5",
        response_text="Rule 5 is lookout.",
        organization_id="org-1",
        session_id="session-1",
    )
    mock_ensure_future.assert_called_once()


def test_sentiment_post_response_skips_low_value_ephemeral_turns():
    analyzer = AsyncMock()
    context = PostResponseContinuityContext(
        user_id="user-1",
        user_role="student",
        message="đói phết nữa",
        response_text="Kiếm gì dễ ăn trong 5-10 phút trước nha.",
        domain_id="maritime",
        organization_id="org-1",
        channel="web",
    )

    with patch(
        "app.services.sentiment_post_response.settings",
        MagicMock(enable_living_continuity=True),
    ), patch(
        "app.services.sentiment_post_response.asyncio.ensure_future",
        side_effect=_consume_scheduled_coroutine,
    ) as mock_ensure_future:
        scheduled = schedule_living_sentiment_continuity(
            context,
            analyze_and_process_sentiment=analyzer,
        )

    assert scheduled is False
    analyzer.assert_not_called()
    mock_ensure_future.assert_not_called()


def test_sentiment_post_response_swallows_schedule_errors():
    analyzer = AsyncMock()

    with patch(
        "app.services.sentiment_post_response.settings",
        MagicMock(enable_living_continuity=True),
    ), patch(
        "app.services.sentiment_post_response.asyncio.ensure_future",
        side_effect=_close_then_raise,
    ):
        scheduled = schedule_living_sentiment_continuity(
            _make_context(),
            analyze_and_process_sentiment=analyzer,
        )

    assert scheduled is False
    analyzer.assert_called_once_with(
        user_id="user-1",
        user_role="student",
        message="Explain Rule 5",
        response_text="Rule 5 is lookout.",
        organization_id="org-1",
        session_id="session-1",
    )
