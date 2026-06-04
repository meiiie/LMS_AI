"""Tests for the Core-to-Living post-response continuity contract."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.living_continuity import (
    HOOK_LIVING_CONTINUITY,
    HOOK_LMS_INSIGHTS,
    HOOK_ROUTINE_TRACKING,
    PostResponseContinuityContext,
    schedule_post_response_continuity,
)


def _make_context() -> PostResponseContinuityContext:
    return PostResponseContinuityContext(
        user_id="user-1",
        user_role="student",
        message="Explain Rule 5",
        response_text="Rule 5 is lookout.",
        domain_id="maritime",
        organization_id="org-1",
        channel="web",
    )


def _consume_scheduled_coroutine(coroutine):
    coroutine.close()
    return MagicMock()


def test_schedules_routine_tracking_when_enabled():
    with patch(
        "app.services.living_continuity.schedule_routine_tracking",
        return_value=True,
    ), patch(
        "app.services.living_continuity.schedule_living_sentiment_continuity",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_lms_insight_push",
        return_value=False,
    ):
        scheduled = schedule_post_response_continuity(_make_context())

    assert scheduled == (HOOK_ROUTINE_TRACKING,)


def test_schedules_living_continuity_when_enabled():
    with patch(
        "app.services.living_continuity.schedule_routine_tracking",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_living_sentiment_continuity",
        return_value=True,
    ), patch(
        "app.services.living_continuity.schedule_lms_insight_push",
        return_value=False,
    ):
        scheduled = schedule_post_response_continuity(_make_context())

    assert scheduled == (HOOK_LIVING_CONTINUITY,)


def test_lms_insights_can_be_skipped_per_caller():
    with patch(
        "app.services.living_continuity.schedule_routine_tracking",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_living_sentiment_continuity",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_lms_insight_push",
        return_value=False,
    ):
        scheduled = schedule_post_response_continuity(
            _make_context(),
            include_lms_insights=False,
        )

    assert scheduled == ()


def test_schedules_lms_insights_when_enabled_for_caller():
    with patch(
        "app.services.living_continuity.schedule_routine_tracking",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_living_sentiment_continuity",
        return_value=False,
    ), patch(
        "app.services.living_continuity.schedule_lms_insight_push",
        return_value=True,
    ):
        scheduled = schedule_post_response_continuity(_make_context())

    assert scheduled == (HOOK_LMS_INSIGHTS,)


def test_schedules_hooks_in_stable_contract_order():
    with patch(
        "app.services.living_continuity.schedule_routine_tracking",
        return_value=True,
    ), patch(
        "app.services.living_continuity.schedule_living_sentiment_continuity",
        return_value=True,
    ), patch(
        "app.services.living_continuity.schedule_lms_insight_push",
        return_value=True,
    ):
        scheduled = schedule_post_response_continuity(_make_context())

    assert scheduled == (
        HOOK_ROUTINE_TRACKING,
        HOOK_LIVING_CONTINUITY,
        HOOK_LMS_INSIGHTS,
    )


def _sentiment_result(importance: float = 0.9):
    result = MagicMock()
    result.life_event_type = "USER_CONVERSATION"
    result.episode_summary = "PRIVATE EPISODE SUMMARY"
    result.importance = importance
    result.user_sentiment = "neutral"
    return result


def _db_session_factory():
    factory = MagicMock()
    session = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory, session


@pytest.mark.asyncio
async def test_living_episode_write_blocks_without_org_context(monkeypatch):
    from app.core.config import settings
    from app.core.org_context import current_org_id
    from app.services.living_continuity import _analyze_and_process_sentiment

    analyzer = MagicMock()
    analyzer.analyze = AsyncMock(return_value=_sentiment_result())
    append_audit = AsyncMock(return_value=True)

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        with patch(
            "app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer",
            return_value=analyzer,
        ), patch(
            "app.engine.living_agent.emotion_engine.get_emotion_engine",
            return_value=MagicMock(),
        ), patch(
            "app.engine.living_agent.emotion_engine.get_relationship_tier",
            return_value=0,
        ), patch(
            "app.core.database.get_shared_session_factory"
        ) as db_factory, patch(
            "app.services.living_continuity.append_semantic_memory_write_audit_event",
            append_audit,
        ):
            await _analyze_and_process_sentiment(
                user_id="private-user",
                user_role="admin",
                message="PRIVATE USER MESSAGE",
                response_text="PRIVATE RESPONSE",
                session_id="session-1",
                organization_id=None,
            )
    finally:
        current_org_id.reset(token)

    db_factory.assert_not_called()
    append_audit.assert_awaited_once()
    audit_payload = append_audit.call_args.kwargs["payload"]
    assert audit_payload["write"]["kind"] == "living_episode"
    assert audit_payload["write"]["status"] == "blocked"
    assert audit_payload["scope"]["write_allowed"] is False
    assert "living_episode_blocked_missing_org_context" in audit_payload["warnings"]
    assert "PRIVATE" not in str(audit_payload)


@pytest.mark.asyncio
async def test_living_episode_write_sets_org_and_appends_audit(monkeypatch):
    from app.core.config import settings
    from app.core.org_context import current_org_id
    from app.services.living_continuity import _analyze_and_process_sentiment

    analyzer = MagicMock()
    analyzer.analyze = AsyncMock(return_value=_sentiment_result())
    factory, session = _db_session_factory()
    append_audit = AsyncMock(return_value=True)

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        with patch(
            "app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer",
            return_value=analyzer,
        ), patch(
            "app.engine.living_agent.emotion_engine.get_emotion_engine",
            return_value=MagicMock(),
        ), patch(
            "app.engine.living_agent.emotion_engine.get_relationship_tier",
            return_value=0,
        ), patch(
            "app.core.database.get_shared_session_factory",
            return_value=factory,
        ), patch(
            "app.services.living_continuity.append_semantic_memory_write_audit_event",
            append_audit,
        ):
            await _analyze_and_process_sentiment(
                user_id="private-user",
                user_role="admin",
                message="PRIVATE USER MESSAGE",
                response_text="PRIVATE RESPONSE",
                session_id="session-1",
                organization_id="org-A",
            )
    finally:
        current_org_id.reset(token)

    params = session.execute.call_args.args[1]
    assert params["organization_id"] == "org-A"
    assert params["session_id"] == "session-1"
    assert current_org_id.get() is None
    append_audit.assert_awaited_once()
    audit_payload = append_audit.call_args.kwargs["payload"]
    assert audit_payload["write"]["kind"] == "living_episode"
    assert audit_payload["write"]["status"] == "saved"
    assert audit_payload["scope"]["write_allowed"] is True
    assert audit_payload["privacy"]["raw_content_included"] is False
    assert "PRIVATE" not in str(audit_payload)
