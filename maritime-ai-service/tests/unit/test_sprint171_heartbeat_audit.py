"""
Tests for Sprint 171: Heartbeat Audit Logging — persistence of every
heartbeat cycle result.

Sprint 171: "Quyền Tự Chủ" — Safety-first autonomous capabilities.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.runtime import runtime_metrics as rm


def _counter_value(name: str, labels: dict[str, str] | None = None) -> int:
    key = tuple(sorted((k, v) for k, v in (labels or {}).items()))
    return rm.snapshot()["counters"].get(name, {}).get(key, 0)


def _histogram_values(name: str, labels: dict[str, str]) -> list[float]:
    key = tuple(sorted(labels.items()))
    return rm.snapshot()["histograms"].get(name, {}).get(key, [])


@pytest.fixture(autouse=True)
def reset_runtime_metrics():
    rm._reset_for_tests()
    yield
    rm._reset_for_tests()


def _make_settings(**overrides):
    """Create a mock settings object with living_agent defaults."""
    defaults = {
        "enable_living_agent": True,
        "living_agent_heartbeat_interval": 1800,
        "living_agent_active_hours_start": 8,
        "living_agent_active_hours_end": 23,
        "living_agent_enable_social_browse": False,
        "living_agent_enable_skill_building": False,
        "living_agent_enable_journal": False,
        "living_agent_require_human_approval": False,
        "living_agent_max_actions_per_heartbeat": 3,
        "living_agent_max_skills_per_week": 5,
        "living_agent_max_searches_per_heartbeat": 3,
        "living_agent_max_daily_cycles": 48,
        # Flags added in later sprints (default off in tests)
        "living_agent_enable_weather": False,
        "living_agent_enable_briefing": False,
        "living_agent_enable_skill_learning": False,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_soul():
    """Create a mock SoulConfig."""
    soul = MagicMock()
    soul.short_term_goals = ["Learn Python"]
    soul.long_term_goals = ["Become expert"]
    soul.interests.primary = ["maritime"]
    soul.interests.exploring = ["AI"]
    soul.interests.wants_to_learn = []
    return soul


def _make_engine():
    """Create a mock EmotionEngine."""
    engine = MagicMock()
    engine.mood.value = "curious"
    engine.energy = 0.8
    engine.state.primary_mood.value = "curious"
    engine.state.energy_level = 0.8
    engine.state.social_battery = 0.7
    engine.state.engagement = 0.6
    engine.to_dict.return_value = {}
    # Async methods added in later sprints
    engine.load_state_from_db = AsyncMock()
    engine.save_state_to_db = AsyncMock()
    return engine


# Patch targets: lazy imports → patch at SOURCE module
_SOUL_PATCH = "app.engine.living_agent.soul_loader.get_soul"
_ENGINE_PATCH = "app.engine.living_agent.emotion_engine.get_emotion_engine"
_SETTINGS_PATCH = "app.core.config.settings"


class TestHeartbeatAudit:
    """Tests for heartbeat audit record persistence."""

    @pytest.mark.asyncio
    async def test_saves_audit_record(self):
        """Every heartbeat cycle should save an audit record."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL_PATCH, return_value=soul), \
             patch(_ENGINE_PATCH, return_value=engine), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit, \
             patch.object(scheduler, "_is_journal_time", return_value=False):

            result = await scheduler._execute_heartbeat()

            # Audit should be called exactly once
            mock_audit.assert_called_once()
            # The result passed to audit should match
            audit_result = mock_audit.call_args[0][0]
            assert audit_result.duration_ms >= 0
            assert _counter_value(
                "runtime.living_agent.heartbeat.cycles",
                {"status": "success"},
            ) == 1
            assert _histogram_values(
                "runtime.living_agent.heartbeat.duration_ms",
                {"status": "success"},
            )

    @pytest.mark.asyncio
    async def test_audit_includes_actions(self):
        """Audit record should include executed actions."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL_PATCH, return_value=soul), \
             patch(_ENGINE_PATCH, return_value=engine), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit, \
             patch.object(scheduler, "_is_journal_time", return_value=False):

            result = await scheduler._execute_heartbeat()

            audit_result = mock_audit.call_args[0][0]
            action_types = [a.action_type.value for a in audit_result.actions_taken]
            assert "check_goals" in action_types

    @pytest.mark.asyncio
    async def test_audit_includes_errors(self):
        """Audit record should include error when cycle fails."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()

        with patch(_SOUL_PATCH, side_effect=RuntimeError("Soul load failed")), \
             patch(_ENGINE_PATCH), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit:

            result = await scheduler._execute_heartbeat()

            assert result.error is not None
            assert "Soul load failed" in result.error
            mock_audit.assert_called_once()
            audit_result = mock_audit.call_args[0][0]
            assert audit_result.error is not None
            assert _counter_value(
                "runtime.living_agent.heartbeat.cycles",
                {"status": "error"},
            ) == 1

    @pytest.mark.asyncio
    async def test_audit_on_noop(self):
        """Audit record should be saved even for NOOP cycles."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL_PATCH, return_value=soul), \
             patch(_ENGINE_PATCH, return_value=engine), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_plan_actions", new_callable=AsyncMock, return_value=[]), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit:

            result = await scheduler._execute_heartbeat()

            assert result.is_noop is True
            mock_audit.assert_called_once()
            assert _counter_value(
                "runtime.living_agent.heartbeat.cycles",
                {"status": "noop"},
            ) == 1

    @pytest.mark.asyncio
    async def test_pending_action_queue_records_metric(self):
        """Approval-gated actions are counted as queued, not silently hidden."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_enable_social_browse=True,
            living_agent_require_human_approval=True,
        )
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL_PATCH, return_value=soul), \
             patch(_ENGINE_PATCH, return_value=engine), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_queue_pending_actions", new_callable=AsyncMock), \
             patch.object(scheduler, "_execute_action", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager", return_value=MagicMock()):

            await scheduler._execute_heartbeat()

        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "browse_social", "status": "queued"},
        ) == 1

    @pytest.mark.asyncio
    async def test_product_acceptance_records_heartbeat_action_outcomes(self):
        """A living heartbeat cycle executes core autonomous actions with metrics."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType, HeartbeatAction

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_require_human_approval=False,
            living_agent_max_actions_per_heartbeat=4,
        )
        soul = _make_soul()
        engine = _make_engine()
        actions = [
            HeartbeatAction(action_type=ActionType.REFLECT, priority=0.9),
            HeartbeatAction(action_type=ActionType.WRITE_JOURNAL, priority=0.8),
            HeartbeatAction(action_type=ActionType.SEND_BRIEFING, priority=0.7),
            HeartbeatAction(
                action_type=ActionType.SEND_BRIEFING,
                target="reengage:learner-1",
                priority=0.6,
            ),
        ]

        with patch(_SOUL_PATCH, return_value=soul), \
             patch(_ENGINE_PATCH, return_value=engine), \
             patch(_SETTINGS_PATCH, settings), \
             patch.object(scheduler, "_plan_actions", new_callable=AsyncMock, return_value=actions), \
             patch.object(scheduler, "_action_reflect", new_callable=AsyncMock) as mock_reflect, \
             patch.object(scheduler, "_action_journal", new_callable=AsyncMock) as mock_journal, \
             patch.object(scheduler, "_action_send_briefing", new_callable=AsyncMock) as mock_briefing, \
             patch.object(scheduler, "_action_reengage", new_callable=AsyncMock) as mock_reengage, \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit, \
             patch.object(scheduler, "_broadcast_soul_bridge", new_callable=AsyncMock), \
             patch.object(scheduler, "_check_graduation_daily", new_callable=AsyncMock), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager", return_value=MagicMock()) as mock_manager:

            result = await scheduler._execute_heartbeat()

        assert result.error is None
        assert [action.action_type for action in result.actions_taken] == [
            ActionType.REFLECT,
            ActionType.WRITE_JOURNAL,
            ActionType.SEND_BRIEFING,
            ActionType.SEND_BRIEFING,
        ]
        mock_reflect.assert_awaited_once()
        mock_journal.assert_awaited_once()
        mock_briefing.assert_awaited_once()
        mock_reengage.assert_awaited_once()
        assert mock_manager.return_value.record_success.call_count == 4
        audit_result = mock_audit.await_args.args[0]
        assert [action.action_type for action in audit_result.actions_taken] == [
            ActionType.REFLECT,
            ActionType.WRITE_JOURNAL,
            ActionType.SEND_BRIEFING,
            ActionType.SEND_BRIEFING,
        ]
        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "reflect", "status": "success"},
        ) == 1
        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "write_journal", "status": "success"},
        ) == 1
        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "send_briefing", "status": "success"},
        ) == 2
        assert _counter_value(
            "runtime.living_agent.heartbeat.cycles",
            {"status": "success"},
        ) == 1

    @pytest.mark.asyncio
    async def test_discovery_notification_uses_structured_org_scoped_websocket_payload(self):
        """Heartbeat discoveries are user-visible without crossing org sessions."""
        from app.api.v1.websocket import ConnectionManager
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_action_runtime import notify_discovery_impl
        from app.engine.living_agent.models import BrowsingItem
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.adapters.websocket import WebSocketAdapter
        from app.services.notifications.registry import NotificationChannelRegistry

        settings = _make_settings(
            enable_multi_tenant=True,
            environment="production",
            default_organization_id="default",
            enable_websocket=True,
            living_agent_notification_channel="websocket",
        )
        registry = NotificationChannelRegistry()
        registry.register(WebSocketAdapter())
        dispatcher = NotificationDispatcher()
        dispatcher._registry = registry
        manager = ConnectionManager()
        org_socket = AsyncMock()
        other_org_socket = AsyncMock()
        await manager.connect(org_socket, "heartbeat-org-session")
        await manager.connect(other_org_socket, "heartbeat-other-org-session")
        manager.register_user("heartbeat-org-session", "wiii_owner", "org-heartbeat")
        manager.register_user("heartbeat-other-org-session", "wiii_owner", "org-other")

        item = BrowsingItem(
            platform="web",
            title="COLREG Rule 13 refresher",
            url="https://example.test/colreg-13",
            relevance_score=0.92,
        )
        token = current_org_id.set("org-heartbeat")
        try:
            with patch(_SETTINGS_PATCH, settings), patch(
                "app.services.notification_dispatcher.get_notification_dispatcher",
                return_value=dispatcher,
            ), patch("app.api.v1.websocket.manager", manager):
                await notify_discovery_impl([item], "COLREG", MagicMock())
        finally:
            current_org_id.reset(token)

        org_socket.send_text.assert_awaited_once()
        other_org_socket.send_text.assert_not_awaited()
        payload = json.loads(org_socket.send_text.await_args.args[0])
        assert payload["type"] == "proactive_message"
        assert payload["trigger"] == "heartbeat_discovery"
        assert payload["topic"] == "COLREG"
        assert payload["item_count"] == 1
        assert "COLREG Rule 13 refresher" in payload["content"]

    @pytest.mark.asyncio
    async def test_discovery_notification_blocks_without_org_context(self):
        """Heartbeat discovery delivery fails closed before unscoped WebSocket send."""
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_action_runtime import notify_discovery_impl
        from app.engine.living_agent.models import BrowsingItem

        settings = _make_settings(
            enable_multi_tenant=True,
            environment="production",
            default_organization_id="default",
            enable_websocket=True,
            living_agent_notification_channel="websocket",
        )
        logger_obj = MagicMock()
        token = current_org_id.set(None)
        try:
            with patch(_SETTINGS_PATCH, settings), patch(
                "app.services.notification_dispatcher.get_notification_dispatcher",
            ) as mock_dispatcher:
                await notify_discovery_impl(
                    [BrowsingItem(platform="web", title="PRIVATE DISCOVERY")],
                    "private-topic",
                    logger_obj,
                )
        finally:
            current_org_id.reset(token)

        mock_dispatcher.assert_not_called()
        logger_obj.warning.assert_called_once()
        assert "heartbeat_runtime_blocked_missing_org_context" in str(
            logger_obj.warning.call_args.args
        )

    @pytest.mark.asyncio
    async def test_action_success_records_metric(self):
        """Action execution emits bounded action outcome metrics."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType, HeartbeatAction

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(action_type=ActionType.REFLECT, priority=0.5)

        with patch.object(scheduler, "_dispatch_action", new_callable=AsyncMock):
            await scheduler._execute_action(action, _make_soul(), _make_engine())

        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "reflect", "status": "success"},
        ) == 1
        assert _histogram_values(
            "runtime.living_agent.heartbeat.action_duration_ms",
            {"action_type": "reflect", "status": "success"},
        )

    @pytest.mark.asyncio
    async def test_action_error_records_metric(self):
        """Action errors are visible without leaking action targets."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType, HeartbeatAction

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(action_type=ActionType.LEARN_TOPIC, priority=0.5)

        with patch.object(
            scheduler,
            "_dispatch_action",
            new_callable=AsyncMock,
            side_effect=RuntimeError("tool unavailable"),
        ):
            await scheduler._execute_action(action, _make_soul(), _make_engine())

        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "learn_topic", "status": "error"},
        ) == 1

    @pytest.mark.asyncio
    async def test_action_timeout_records_metric(self):
        """Action timeouts are tagged separately from generic failures."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType, HeartbeatAction

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(action_type=ActionType.BROWSE_SOCIAL, priority=0.5)

        with patch.object(
            scheduler,
            "_dispatch_action",
            new_callable=AsyncMock,
            side_effect=TimeoutError(),
        ):
            await scheduler._execute_action(action, _make_soul(), _make_engine())

        assert _counter_value(
            "runtime.living_agent.heartbeat.actions",
            {"action_type": "browse_social", "status": "timeout"},
        ) == 1
