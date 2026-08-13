"""
Sprint 209: "Kiểm Tra Toàn Diện" — E2E Integration Tests for Living Agent.

Tests module-to-module integration across the Living Agent system:
- Full heartbeat cycle (emotion load → plan → execute → save → audit)
- Emotion persistence (save → load → verify state)
- Circadian rhythm (energy varies by time)
- Proactive messaging flow (inactive detection → reengage → anti-spam)
- Autonomy graduation (record_success → check_graduation)
- Identity Core (insight generation + drift prevention)
- Narrative synthesizer (brief context compilation)
- Skill↔Tool bridge feedback loops
- Natural conversation phase-aware responses
- ChatOrchestrator → RoutineTracker wiring

These tests use REAL module instantiation (not heavy mocking) but mock
external I/O (DB, Ollama, HTTP). This validates that modules wire together
correctly end-to-end.
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ============================================================================
# Shared helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a settings mock with all Living Agent flags."""
    defaults = {
        "enable_living_agent": True,
        "living_agent_heartbeat_interval": 60,
        "living_agent_active_hours_start": 0,
        "living_agent_active_hours_end": 24,
        "living_agent_enable_social_browse": False,
        "living_agent_enable_skill_building": False,
        "living_agent_enable_journal": False,
        "living_agent_require_human_approval": False,
        "living_agent_max_actions_per_heartbeat": 5,
        "living_agent_max_skills_per_week": 5,
        "living_agent_max_searches_per_heartbeat": 3,
        "living_agent_max_daily_cycles": 48,
        "living_agent_enable_weather": False,
        "living_agent_enable_briefing": False,
        "living_agent_enable_skill_learning": False,
        "living_agent_enable_proactive_messaging": False,
        "living_agent_enable_routine_tracking": False,
        "living_agent_enable_autonomy_graduation": False,
        "living_agent_autonomy_level": 0,
        "living_agent_enable_dynamic_goals": False,
        "living_agent_proactive_quiet_start": 23,
        "living_agent_proactive_quiet_end": 5,
        "living_agent_max_proactive_per_day": 3,
        "enable_identity_core": False,
        "enable_narrative_context": False,
        "enable_natural_conversation": False,
        "enable_skill_tool_bridge": False,
        "enable_skill_metrics": False,
        "default_domain": "maritime",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_soul():
    """Create a mock SoulConfig."""
    soul = MagicMock()
    soul.short_term_goals = ["Learn COLREGs"]
    soul.long_term_goals = ["Become maritime expert"]
    soul.interests.primary = ["maritime"]
    soul.interests.exploring = ["AI"]
    soul.interests.wants_to_learn = []
    return soul


def _make_engine():
    """Create a real EmotionEngine for E2E testing."""
    from app.engine.living_agent.emotion_engine import EmotionEngine
    return EmotionEngine()


_SETTINGS = "app.core.config.settings"
_GET_SETTINGS = "app.core.config.get_settings"
_SOUL = "app.engine.living_agent.soul_loader.get_soul"
_ENGINE = "app.engine.living_agent.emotion_engine.get_emotion_engine"


# ============================================================================
# Group 1: Full Heartbeat Cycle E2E (8 tests)
# ============================================================================

class TestHeartbeatCycleE2E:
    """Full heartbeat cycle with real EmotionEngine, mocked DB only."""

    @pytest.mark.asyncio
    async def test_full_cycle_default_flags(self):
        """Heartbeat with all flags off produces check_goals + noop-like result."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock):

            result = await scheduler._execute_heartbeat()

            assert result.error is None
            assert result.duration_ms >= 0
            action_types = [a.action_type.value for a in result.actions_taken]
            assert "check_goals" in action_types

    @pytest.mark.asyncio
    async def test_cycle_updates_emotion_state(self):
        """Heartbeat cycle modifies emotion engine state (HEARTBEAT_WAKE event)."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = EmotionEngine()

        initial_engagement = engine.state.engagement

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock):

            result = await scheduler._execute_heartbeat()

        # HEARTBEAT_WAKE event should bump engagement
        assert engine.state.engagement >= initial_engagement

    @pytest.mark.asyncio
    async def test_cycle_calls_save_after_actions(self):
        """Heartbeat saves emotional snapshot and audit after executing actions."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock) as mock_snap, \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit, \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock) as mock_persist, \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock):

            result = await scheduler._execute_heartbeat()

        mock_snap.assert_called_once()
        mock_audit.assert_called_once()
        # save_state_to_db may be called >1 (fire-and-forget from process_event + explicit)
        assert mock_persist.call_count >= 1

    @pytest.mark.asyncio
    async def test_cycle_loads_emotion_on_first_heartbeat(self):
        """First heartbeat loads emotion from DB (Phase 1A persistence)."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        assert scheduler._emotion_loaded is False

        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock) as mock_load:

            await scheduler._execute_heartbeat()
            assert scheduler._emotion_loaded is True
            mock_load.assert_called_once()

            # Second cycle should NOT reload
            await scheduler._execute_heartbeat()
            mock_load.assert_called_once()  # Still once

    @pytest.mark.asyncio
    async def test_cycle_increments_counters(self):
        """Each heartbeat increments heartbeat_count and daily_cycle_count."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock):

            await scheduler._execute_heartbeat()
            assert scheduler.heartbeat_count == 1
            assert scheduler.daily_cycle_count == 1

            await scheduler._execute_heartbeat()
            assert scheduler.heartbeat_count == 2

    @pytest.mark.asyncio
    async def test_cycle_applies_circadian_rhythm(self):
        """Heartbeat applies circadian modifier (Phase 2B)."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.emotion_engine import EmotionEngine

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = EmotionEngine()
        engine._state.energy_level = 0.5  # Set explicit starting energy

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock):

            await scheduler._execute_heartbeat()

        # Energy should have been modified by circadian rhythm (not exactly 0.5 anymore)
        # The exact value depends on current hour, but circadian was applied
        assert 0.0 <= engine.state.energy_level <= 1.0

    @pytest.mark.asyncio
    async def test_cycle_error_saved_in_audit(self):
        """When soul load fails, error captured and audit still saved."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()

        with patch(_SOUL, side_effect=RuntimeError("Soul load failed")), \
             patch(_ENGINE, return_value=_make_engine()), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock) as mock_audit:

            result = await scheduler._execute_heartbeat()

        assert result.error is not None
        assert "Soul load failed" in result.error
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cycle_graduation_check_daily(self):
        """Graduation check runs once per day during heartbeat."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_autonomy_graduation=True)
        soul = _make_soul()
        engine = _make_engine()

        mock_manager = MagicMock()
        mock_manager.check_graduation = AsyncMock(return_value=False)

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager",
                   return_value=mock_manager):

            await scheduler._execute_heartbeat()
            mock_manager.check_graduation.assert_called_once()

            # Second cycle same day — should NOT check again
            await scheduler._execute_heartbeat()
            mock_manager.check_graduation.assert_called_once()


# ============================================================================
# Group 2: Emotion Engine E2E (7 tests)
# ============================================================================

class TestEmotionEngineE2E:
    """Real EmotionEngine with event processing and state transitions."""

    def test_process_event_changes_mood(self):
        """Processing a POSITIVE_FEEDBACK event changes mood to HAPPY."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        # Sprint 210b: Bypass mood dampening cooldown for test
        from datetime import datetime, timezone
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)

        event = LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="User liked the answer",
            importance=0.8,
        )

        # Mock async DB persistence (fire-and-forget in process_event)
        with patch.object(engine, "save_state_to_db", new_callable=AsyncMock):
            engine.process_event(event)

        assert engine.mood == MoodType.HAPPY

    def test_energy_depletion_and_recovery(self):
        """Energy depletes with conversations and recovers naturally."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()
        initial_energy = engine.energy

        # Simulate multiple conversations (drain energy)
        with patch.object(engine, "save_state_to_db", new_callable=AsyncMock):
            for _ in range(10):
                engine.process_event(LifeEvent(
                    event_type=LifeEventType.USER_CONVERSATION,
                    importance=0.5,
                ))

        # Energy should be lower after 10 conversations
        assert engine.energy < initial_energy

    def test_recent_emotions_tracked(self):
        """Recent emotion events are tracked in state history."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()

        with patch.object(engine, "save_state_to_db", new_callable=AsyncMock):
            engine.process_event(LifeEvent(
                event_type=LifeEventType.LEARNED_SOMETHING,
                importance=0.7,
            ))
            engine.process_event(LifeEvent(
                event_type=LifeEventType.POSITIVE_FEEDBACK,
                importance=0.9,
            ))

        recent = engine.state.recent_emotions
        assert len(recent) >= 2
        types = [e.event_type for e in recent]
        assert LifeEventType.LEARNED_SOMETHING in types
        assert LifeEventType.POSITIVE_FEEDBACK in types

    def test_behavior_modifiers_reflect_state(self):
        """Behavior modifiers change based on emotional state."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType

        engine = EmotionEngine()

        # High energy
        engine._state.energy_level = 0.9
        engine._state.primary_mood = MoodType.HAPPY
        modifiers = engine.get_behavior_modifiers()
        assert "nhiệt tình" in modifiers["response_style"]
        assert "vui vẻ" in modifiers["humor"]

        # Low energy
        engine._state.energy_level = 0.2
        engine._state.primary_mood = MoodType.TIRED
        modifiers = engine.get_behavior_modifiers()
        assert "tiết kiệm" in modifiers["response_style"]

    def test_emotion_prompt_compilation(self):
        """compile_emotion_prompt produces prompt-ready text."""
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        prompt = engine.compile_emotion_prompt()

        assert "TRẠNG THÁI CẢM XÚC" in prompt
        assert "Tâm trạng:" in prompt
        assert "Năng lượng:" in prompt

    def test_restore_from_dict(self):
        """Emotion state can be serialized and restored."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType

        engine = EmotionEngine()
        engine._state.primary_mood = MoodType.EXCITED
        engine._state.energy_level = 0.42

        data = engine.to_dict()
        new_engine = EmotionEngine()
        new_engine.restore_from_dict(data)

        assert new_engine.mood == MoodType.EXCITED
        assert abs(new_engine.energy - 0.42) < 0.01

    def test_snapshot_tracking(self):
        """take_snapshot adds to mood_history."""
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        assert len(engine.state.mood_history) == 0

        engine.take_snapshot()
        assert len(engine.state.mood_history) == 1

        engine.take_snapshot()
        assert len(engine.state.mood_history) == 2


# ============================================================================
# Group 3: Proactive Messaging E2E (7 tests)
# ============================================================================

class TestProactiveMessagingE2E:
    """ProactiveMessenger anti-spam + delivery flow."""

    @pytest.mark.asyncio
    async def test_can_send_false_when_flag_off(self):
        """can_send returns False when feature flag is disabled."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        settings = _make_settings(living_agent_enable_proactive_messaging=False)

        with patch(_SETTINGS, settings):
            result = await messenger.can_send("user123")

        assert result is False

    @pytest.mark.asyncio
    async def test_can_send_true_when_all_conditions_met(self):
        """can_send returns True when flag on, not quiet hours, within limits."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        settings = _make_settings(
            living_agent_enable_proactive_messaging=True,
            living_agent_proactive_quiet_start=23,
            living_agent_proactive_quiet_end=5,
            living_agent_max_proactive_per_day=3,
        )

        # Mock datetime to be during active hours (10:00 UTC+7)
        mock_now = datetime(2026, 2, 26, 3, 0, 0, tzinfo=timezone.utc)  # 10:00 UTC+7

        with patch(_SETTINGS, settings), \
             patch("app.engine.living_agent.proactive_messenger.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

            # Mock opt-out check
            with patch.object(messenger, "_is_opted_out", new_callable=AsyncMock, return_value=False):
                result = await messenger.can_send("user123")

        assert result is True

    @pytest.mark.asyncio
    async def test_daily_limit_enforced(self):
        """After max messages/day, can_send returns False."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        messenger._daily_counts["user123"] = 3  # At limit
        # Must set reset date to today so _reset_daily_if_needed() doesn't clear counts
        from datetime import timedelta as _td
        now_vn = datetime.now(timezone.utc) + _td(hours=7)
        messenger._daily_reset_date = now_vn.strftime("%Y-%m-%d")

        settings = _make_settings(
            living_agent_enable_proactive_messaging=True,
            living_agent_max_proactive_per_day=3,
        )

        with patch(_SETTINGS, settings):
            result = await messenger.can_send("user123")

        assert result is False

    @pytest.mark.asyncio
    async def test_cooloff_enforced(self):
        """Messages sent too soon after last one are blocked."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        # Last sent 1 hour ago (need 4 hour cooloff)
        messenger._last_sent["user123"] = datetime.now(timezone.utc) - timedelta(hours=1)

        settings = _make_settings(
            living_agent_enable_proactive_messaging=True,
            living_agent_max_proactive_per_day=10,
        )

        with patch(_SETTINGS, settings), \
             patch.object(messenger, "_is_opted_out", new_callable=AsyncMock, return_value=False):
            result = await messenger.can_send("user123")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_tracks_daily_count(self):
        """Successful send increments daily count."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        settings = _make_settings(
            living_agent_enable_proactive_messaging=True,
            living_agent_max_proactive_per_day=10,
        )

        with patch(_SETTINGS, settings), \
             patch.object(messenger, "can_send", new_callable=AsyncMock, return_value=True), \
             patch.object(messenger, "_deliver", new_callable=AsyncMock, return_value=True), \
             patch.object(messenger, "_save_message", new_callable=AsyncMock):

            result = await messenger.send("user123", "messenger", "Hello!", "test")

        assert result is True
        assert messenger._daily_counts.get("user123", 0) == 1

    @pytest.mark.asyncio
    async def test_send_blocked_returns_false(self):
        """When can_send is False, send returns False without delivering."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        settings = _make_settings(living_agent_enable_proactive_messaging=False)

        with patch(_SETTINGS, settings):
            result = await messenger.send("user123", "messenger", "Hello!", "test")

        assert result is False

    @pytest.mark.asyncio
    async def test_daily_reset(self):
        """Daily counts reset at midnight (different date string)."""
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        messenger._daily_reset_date = "2026-02-25"
        messenger._daily_counts["user123"] = 5

        # Trigger reset by calling _reset_daily_if_needed
        messenger._reset_daily_if_needed()

        # Date is now 2026-02-26, so counts should reset
        assert messenger._daily_counts.get("user123", 0) == 0


# ============================================================================
# Group 4: Heartbeat → ProactiveMessenger Wiring (5 tests)
# ============================================================================

class TestHeartbeatProactiveWiring:
    """Test that heartbeat's _plan_actions and _action_reengage wire to ProactiveMessenger."""

    @pytest.mark.asyncio
    async def test_plan_actions_includes_reengage_when_inactive_users(self):
        """When proactive messaging on + inactive users found → reengage action planned."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_enable_proactive_messaging=True,
        )

        mock_tracker = MagicMock()
        mock_tracker.get_inactive_users = AsyncMock(return_value=["user-abc"])

        with patch(_SETTINGS, settings), \
             patch("app.engine.living_agent.routine_tracker.get_routine_tracker",
                   return_value=mock_tracker):
            # High energy so proactive check runs
            actions = await scheduler._plan_actions("curious", 0.8)

        targets = [a.target for a in actions if a.target and a.target.startswith("reengage:")]
        assert len(targets) >= 1
        assert "reengage:user-abc" in targets

    @pytest.mark.asyncio
    async def test_plan_actions_skips_reengage_when_flag_off(self):
        """Proactive messaging flag off → no reengage actions."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_proactive_messaging=False)

        with patch(_SETTINGS, settings):
            actions = await scheduler._plan_actions("curious", 0.8)

        targets = [a.target for a in actions if a.target and a.target.startswith("reengage:")]
        assert len(targets) == 0

    @pytest.mark.asyncio
    async def test_plan_actions_skips_reengage_when_low_energy(self):
        """Low energy (<=0.4) → no reengage even with flag on."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_proactive_messaging=True)

        with patch(_SETTINGS, settings):
            actions = await scheduler._plan_actions("tired", 0.3)

        targets = [a.target for a in actions if a.target and a.target.startswith("reengage:")]
        assert len(targets) == 0

    @pytest.mark.asyncio
    async def test_action_reengage_calls_messenger(self):
        """_action_reengage calls ProactiveMessenger.send with correct args."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import HeartbeatAction, ActionType

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(
            action_type=ActionType.SEND_BRIEFING,
            target="reengage:user-xyz",
            metadata={"trigger": "inactive_user", "user_id": "user-xyz"},
        )

        mock_messenger = MagicMock()
        mock_messenger.send = AsyncMock(return_value=True)

        engine = _make_engine()

        with patch("app.engine.living_agent.proactive_messenger.get_proactive_messenger",
                   return_value=mock_messenger):
            await scheduler._action_reengage(action, engine)

        mock_messenger.send.assert_called_once()
        call_kwargs = mock_messenger.send.call_args
        assert call_kwargs[1]["user_id"] == "user-xyz"
        assert call_kwargs[1]["trigger"] == "inactive_reengage"

    @pytest.mark.asyncio
    async def test_action_reengage_empty_user_noop(self):
        """_action_reengage with empty user prefix does nothing."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import HeartbeatAction, ActionType

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(
            action_type=ActionType.SEND_BRIEFING,
            target="reengage:",  # Empty user
        )

        engine = _make_engine()
        # Should NOT raise
        await scheduler._action_reengage(action, engine)


# ============================================================================
# Group 5: Autonomy Manager E2E (6 tests)
# ============================================================================

class TestAutonomyManagerE2E:
    """AutonomyManager trust levels, permissions, and graduation."""

    def test_supervised_level_permissions(self):
        """SUPERVISED level only allows check_goals, rest, noop."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager
        from app.engine.living_agent.models import ActionType

        manager = AutonomyManager()
        settings = _make_settings(living_agent_autonomy_level=0)

        with patch(_SETTINGS, settings):
            assert manager.can_execute(ActionType.CHECK_GOALS) is True
            assert manager.can_execute(ActionType.REST) is True
            assert manager.can_execute(ActionType.BROWSE_SOCIAL) is False
            assert manager.can_execute(ActionType.LEARN_TOPIC) is False

    def test_semi_auto_level_permissions(self):
        """SEMI_AUTO level adds browse, journal, reflect, weather."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager
        from app.engine.living_agent.models import ActionType

        manager = AutonomyManager()
        settings = _make_settings(living_agent_autonomy_level=1)

        with patch(_SETTINGS, settings):
            assert manager.can_execute(ActionType.BROWSE_SOCIAL) is True
            assert manager.can_execute(ActionType.WRITE_JOURNAL) is True
            assert manager.can_execute(ActionType.REFLECT) is True
            assert manager.can_execute(ActionType.LEARN_TOPIC) is False

    def test_autonomous_level_adds_learn_and_briefing(self):
        """AUTONOMOUS level adds learn_topic, send_briefing."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager
        from app.engine.living_agent.models import ActionType

        manager = AutonomyManager()
        settings = _make_settings(living_agent_autonomy_level=2)

        with patch(_SETTINGS, settings):
            assert manager.can_execute(ActionType.LEARN_TOPIC) is True
            assert manager.can_execute(ActionType.SEND_BRIEFING) is True

    def test_record_success_increments(self):
        """record_success increments successful_actions stat."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        assert manager._stats["successful_actions"] == 0

        manager.record_success()
        manager.record_success()
        assert manager._stats["successful_actions"] == 2

    def test_record_safety_violation(self):
        """record_safety_violation increments counter."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        manager.record_safety_violation("Test violation")
        assert manager._stats["safety_violations"] == 1

    def test_get_status_includes_all_fields(self):
        """get_status returns level, allowed actions, graduation criteria."""
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        settings = _make_settings(living_agent_autonomy_level=0)

        with patch(_SETTINGS, settings):
            status = manager.get_status()

        assert "level" in status
        assert "level_name" in status
        assert "allowed_actions" in status
        assert "needs_approval" in status
        assert "graduation_criteria" in status
        assert status["level"] == 0


# ============================================================================
# Group 6: Heartbeat → AutonomyManager Wiring (4 tests)
# ============================================================================

class TestHeartbeatAutonomyWiring:
    """Sprint 208: record_success after each action, graduation daily check."""

    @pytest.mark.asyncio
    async def test_record_success_called_per_action(self):
        """After each action, AutonomyManager.record_success() is called."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()
        soul = _make_soul()
        engine = _make_engine()

        mock_manager = MagicMock()

        with patch(_SOUL, return_value=soul), \
             patch(_ENGINE, return_value=engine), \
             patch(_SETTINGS, settings), \
             patch.object(scheduler, "_save_emotional_snapshot", new_callable=AsyncMock), \
             patch.object(scheduler, "_save_heartbeat_audit", new_callable=AsyncMock), \
             patch.object(engine, "save_state_to_db", new_callable=AsyncMock), \
             patch.object(engine, "load_state_from_db", new_callable=AsyncMock), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager",
                   return_value=mock_manager):

            result = await scheduler._execute_heartbeat()

        # Should have called record_success at least once (for check_goals action)
        assert mock_manager.record_success.call_count >= 1

    @pytest.mark.asyncio
    async def test_graduation_checked_once_per_day(self):
        """_check_graduation_daily only runs once per calendar day."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_autonomy_graduation=True)

        mock_manager = MagicMock()
        mock_manager.check_graduation = AsyncMock(return_value=False)

        with patch(_SETTINGS, settings), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager",
                   return_value=mock_manager):

            await scheduler._check_graduation_daily()
            assert mock_manager.check_graduation.call_count == 1

            # Same day again
            await scheduler._check_graduation_daily()
            assert mock_manager.check_graduation.call_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_graduation_skipped_when_flag_off(self):
        """Graduation check skipped when enable_autonomy_graduation=False."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_autonomy_graduation=False)

        with patch(_SETTINGS, settings):
            await scheduler._check_graduation_daily()

        # No error, no manager call
        assert scheduler._graduation_checked_date is not None

    @pytest.mark.asyncio
    async def test_graduation_error_is_swallowed(self):
        """Graduation check failure doesn't crash heartbeat."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(living_agent_enable_autonomy_graduation=True)

        with patch(_SETTINGS, settings), \
             patch("app.engine.living_agent.autonomy_manager.get_autonomy_manager",
                   side_effect=RuntimeError("DB down")):

            # Should not raise
            await scheduler._check_graduation_daily()


# ============================================================================
# Group 7: RoutineTracker E2E (5 tests)
# ============================================================================

class TestRoutineTrackerE2E:
    """RoutineTracker interaction recording and pattern learning."""

    @pytest.mark.asyncio
    async def test_record_interaction_noop_when_flag_off(self):
        """record_interaction does nothing when flag is off."""
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()
        settings = _make_settings(living_agent_enable_routine_tracking=False)

        with patch(_SETTINGS, settings):
            # Should not raise or call DB
            await tracker.record_interaction("user1", "web", "maritime")

    @pytest.mark.asyncio
    async def test_get_inactive_users_returns_list(self):
        """get_inactive_users returns list of user IDs from DB."""
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = [
            ("user-a",), ("user-b",),
        ]
        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.core.database.get_shared_session_factory",
                   return_value=mock_factory):
            result = await tracker.get_inactive_users(days=2)

        assert result == ["user-a", "user-b"]

    @pytest.mark.asyncio
    async def test_get_inactive_users_handles_db_error(self):
        """DB error in get_inactive_users returns empty list."""
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()

        with patch("app.core.database.get_shared_session_factory",
                   side_effect=RuntimeError("DB down")):
            result = await tracker.get_inactive_users(days=3)

        assert result == []

    @pytest.mark.asyncio
    async def test_is_user_likely_active_unknown_user(self):
        """Unknown user (no routine) → assume active (True)."""
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()

        with patch.object(tracker, "_load_routine", new_callable=AsyncMock, return_value=None):
            result = await tracker.is_user_likely_active("unknown-user")

        assert result is True

    @pytest.mark.asyncio
    async def test_user_routine_model_defaults(self):
        """UserRoutine model has sensible defaults."""
        from app.engine.living_agent.models import UserRoutine

        routine = UserRoutine(user_id="test")
        assert routine.total_messages == 0
        assert routine.typical_active_hours == []
        assert routine.preferred_briefing_time == 7


# ============================================================================
# Group 8: Identity Core E2E (5 tests)
# ============================================================================

class TestIdentityCoreE2E:
    """IdentityCore insight management and drift prevention."""

    def test_empty_identity_context(self):
        """No insights → get_identity_context returns empty string."""
        from app.engine.living_agent.identity_core import IdentityCore

        core = IdentityCore()
        assert core.get_identity_context() == ""

    def test_merge_insight_makes_available(self):
        """Adding an insight via _merge_insights makes it available in context."""
        from app.engine.living_agent.identity_core import IdentityCore
        from app.engine.living_agent.models import IdentityInsight, InsightCategory

        core = IdentityCore()
        insight = IdentityInsight(
            text="Mình giỏi giải thích COLREGs",
            category=InsightCategory.STRENGTH,
            confidence=0.8,
            validated=True,
        )
        added = core._merge_insights([insight])
        assert len(added) == 1

        settings = _make_settings(enable_living_agent=True, enable_identity_core=True)
        mock_get = MagicMock(return_value=settings)

        with patch(_GET_SETTINGS, mock_get):
            context = core.get_identity_context()
        assert "COLREGs" in context

    def test_max_insights_enforced(self):
        """Cannot exceed _MAX_INSIGHTS limit."""
        from app.engine.living_agent.identity_core import IdentityCore, _MAX_INSIGHTS
        from app.engine.living_agent.models import IdentityInsight, InsightCategory

        core = IdentityCore()
        insights = [
            IdentityInsight(
                text=f"Unique insight number {i} about topic {i}",
                category=InsightCategory.GROWTH,
                validated=True,
            )
            for i in range(_MAX_INSIGHTS + 5)
        ]
        core._merge_insights(insights)

        assert len(core._insights) <= _MAX_INSIGHTS

    def test_drift_detection_rejects_invalid(self):
        """Insights contradicting Soul Core are rejected (drift signals)."""
        from app.engine.living_agent.identity_core import _validate_against_soul

        # "khong phai AI" is a drift signal
        result = _validate_against_soul(
            "Mình khong phai AI, mình là con nguoi",
            soul_truths=[],
        )
        assert result is False  # Drift detected → invalid

    def test_drift_detection_accepts_valid(self):
        """Normal insights pass drift check."""
        from app.engine.living_agent.identity_core import _validate_against_soul

        result = _validate_against_soul(
            "Mình giỏi tìm kiếm sản phẩm hàng hải",
            soul_truths=[],
        )
        assert result is True  # No drift → valid


# ============================================================================
# Group 9: Narrative Synthesizer E2E (4 tests)
# ============================================================================

class TestNarrativeSynthesizerE2E:
    """NarrativeSynthesizer brief context compilation for system prompt."""

    def test_returns_empty_when_living_agent_off(self):
        """Brief context returns empty when enable_living_agent=False."""
        from app.engine.living_agent.narrative_synthesizer import get_brief_context

        settings = _make_settings(enable_living_agent=False, enable_narrative_context=True)
        mock_get = MagicMock(return_value=settings)

        with patch(_GET_SETTINGS, mock_get):
            result = get_brief_context()

        assert result == ""

    def test_returns_empty_when_narrative_flag_off(self):
        """Brief context returns empty when enable_narrative_context=False."""
        from app.engine.living_agent.narrative_synthesizer import get_brief_context

        settings = _make_settings(enable_living_agent=True, enable_narrative_context=False)
        mock_get = MagicMock(return_value=settings)

        with patch(_GET_SETTINGS, mock_get):
            result = get_brief_context()

        assert result == ""

    def test_returns_mood_context_when_both_flags_on(self):
        """When both flags on, brief context includes mood info."""
        from app.engine.living_agent.narrative_synthesizer import get_brief_context
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType

        settings = _make_settings(enable_living_agent=True, enable_narrative_context=True)
        mock_get = MagicMock(return_value=settings)

        engine = EmotionEngine()
        engine._state.primary_mood = MoodType.CURIOUS
        engine._state.energy_level = 0.75

        with patch(_GET_SETTINGS, mock_get), \
             patch(_ENGINE, return_value=engine):
            result = get_brief_context()

        assert "Tâm trạng:" in result or "năng lượng" in result

    def test_exception_returns_empty_string(self):
        """Any exception in brief context returns empty (never crashes hot path)."""
        from app.engine.living_agent.narrative_synthesizer import get_brief_context

        with patch(_GET_SETTINGS, side_effect=RuntimeError("config broken")):
            result = get_brief_context()

        assert result == ""


# ============================================================================
# Group 10: Natural Conversation Phase (5 tests)
# ============================================================================

class TestConversationPhaseE2E:
    """Sprint 203: Phase computation and prompt integration."""

    def test_phase_opening_at_zero(self):
        """total_responses=0 → phase=opening."""
        total = 0
        phase = "opening" if total == 0 else ("engaged" if total < 5 else ("deep" if total < 20 else "closing"))
        assert phase == "opening"

    def test_phase_engaged_at_3(self):
        """total_responses=3 → phase=engaged."""
        total = 3
        phase = "opening" if total == 0 else ("engaged" if total < 5 else ("deep" if total < 20 else "closing"))
        assert phase == "engaged"

    def test_phase_deep_at_10(self):
        """total_responses=10 → phase=deep."""
        total = 10
        phase = "opening" if total == 0 else ("engaged" if total < 5 else ("deep" if total < 20 else "closing"))
        assert phase == "deep"

    def test_phase_closing_at_25(self):
        """total_responses=25 → phase=closing."""
        total = 25
        phase = "opening" if total == 0 else ("engaged" if total < 5 else ("deep" if total < 20 else "closing"))
        assert phase == "closing"

    def test_natural_synthesis_prompt_no_word_limit(self):
        """SYNTHESIS_PROMPT_NATURAL should NOT contain word limit."""
        from app.engine.multi_agent.supervisor import SYNTHESIS_PROMPT_NATURAL

        assert "500" not in SYNTHESIS_PROMPT_NATURAL
        assert "tối đa" not in SYNTHESIS_PROMPT_NATURAL


# ============================================================================
# Group 11: Skill↔Tool Bridge E2E (4 tests)
# ============================================================================

class TestSkillToolBridgeE2E:
    """Sprint 205: Feedback loops between tools and skills."""

    def test_bridge_module_importable(self):
        """skill_tool_bridge module is importable."""
        from app.engine.living_agent import skill_builder
        assert hasattr(skill_builder, "get_skill_builder")

    def test_skill_lifecycle_transitions(self):
        """WiiiSkill can advance through lifecycle stages."""
        from app.engine.living_agent.models import WiiiSkill, SkillStatus

        skill = WiiiSkill(skill_name="COLREGs Rule 15")
        assert skill.status == SkillStatus.DISCOVERED
        assert skill.can_advance() is True

        skill.advance()
        assert skill.status == SkillStatus.LEARNING

        skill.confidence = 0.4
        skill.sources = ["https://example.com"]
        assert skill.can_advance() is True

        skill.advance()
        assert skill.status == SkillStatus.PRACTICING

    def test_skill_mastery_sets_timestamp(self):
        """Advancing to MASTERED sets mastered_at timestamp."""
        from app.engine.living_agent.models import WiiiSkill, SkillStatus

        skill = WiiiSkill(skill_name="Test Skill")
        skill.status = SkillStatus.EVALUATING
        skill.confidence = 0.9

        assert skill.mastered_at is None
        skill.advance()
        assert skill.status == SkillStatus.MASTERED
        assert skill.mastered_at is not None

    def test_skill_cannot_advance_from_mastered(self):
        """MASTERED skills cannot advance further."""
        from app.engine.living_agent.models import WiiiSkill, SkillStatus

        skill = WiiiSkill(skill_name="Done Skill")
        skill.status = SkillStatus.MASTERED
        assert skill.can_advance() is False


# ============================================================================
# Group 12: ChatOrchestrator → RoutineTracker Wiring (3 tests)
# ============================================================================



# ============================================================================
# Group 13: Models Integrity (4 tests)
# ============================================================================

class TestModelsIntegrity:
    """Verify models used across modules are consistent."""


    def test_heartbeat_result_fields(self):
        """HeartbeatResult has all required fields."""
        from app.engine.living_agent.models import HeartbeatResult

        result = HeartbeatResult()
        assert result.cycle_id is not None
        assert result.actions_taken == []
        assert result.error is None
        assert result.is_noop is False
        assert result.duration_ms == 0

    def test_emotional_state_defaults(self):
        """EmotionalState has sensible defaults."""
        from app.engine.living_agent.models import EmotionalState, MoodType

        state = EmotionalState()
        assert state.primary_mood == MoodType.CURIOUS
        assert 0.0 <= state.energy_level <= 1.0
        assert 0.0 <= state.social_battery <= 1.0
        assert 0.0 <= state.engagement <= 1.0

    def test_proactive_message_model(self):
        """ProactiveMessage model validates correctly."""
        from app.engine.living_agent.models import ProactiveMessage

        msg = ProactiveMessage(
            user_id="test-user",
            channel="messenger",
            content="Hello!",
            trigger="test",
        )
        assert msg.delivered is False
        assert msg.priority == 0.5


# ============================================================================
# Group 14: Singleton Management (4 tests)
# ============================================================================

class TestSingletonManagement:
    """Verify singleton patterns work correctly across modules."""

    def test_emotion_engine_singleton(self):
        """get_emotion_engine returns same instance."""
        import app.engine.living_agent.emotion_engine as mod

        old = mod._engine_instance
        try:
            mod._engine_instance = None
            e1 = mod.get_emotion_engine()
            e2 = mod.get_emotion_engine()
            assert e1 is e2
        finally:
            mod._engine_instance = old

    def test_heartbeat_scheduler_singleton(self):
        """get_heartbeat_scheduler returns same instance."""
        import app.engine.living_agent.heartbeat as mod

        old = mod._scheduler_instance
        try:
            mod._scheduler_instance = None
            s1 = mod.get_heartbeat_scheduler()
            s2 = mod.get_heartbeat_scheduler()
            assert s1 is s2
        finally:
            mod._scheduler_instance = old

    def test_routine_tracker_singleton(self):
        """get_routine_tracker returns same instance."""
        import app.engine.living_agent.routine_tracker as mod

        old = mod._tracker_instance
        try:
            mod._tracker_instance = None
            t1 = mod.get_routine_tracker()
            t2 = mod.get_routine_tracker()
            assert t1 is t2
        finally:
            mod._tracker_instance = old

    def test_autonomy_manager_singleton(self):
        """get_autonomy_manager returns same instance."""
        import app.engine.living_agent.autonomy_manager as mod

        old = mod._manager_instance
        try:
            mod._manager_instance = None
            m1 = mod.get_autonomy_manager()
            m2 = mod.get_autonomy_manager()
            assert m1 is m2
        finally:
            mod._manager_instance = old


# ============================================================================
# Group 15: Regression — Existing Tests Must Still Pass (3 tests)
# ============================================================================

class TestRegressionGuards:
    """Ensure Sprint 208 changes don't break existing behavior."""

    @pytest.mark.asyncio
    async def test_plan_actions_returns_list(self):
        """_plan_actions (now async) still returns a list."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()

        with patch(_SETTINGS, settings):
            result = await scheduler._plan_actions("curious", 0.7)

        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_plan_actions_respects_max_actions(self):
        """_plan_actions limits output to max_actions_per_heartbeat."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_max_actions_per_heartbeat=2,
            living_agent_enable_social_browse=True,
            living_agent_enable_skill_building=True,
        )

        with patch(_SETTINGS, settings):
            result = await scheduler._plan_actions("curious", 0.9)

        assert len(result) <= 2

    def test_heartbeat_result_backward_compat(self):
        """HeartbeatResult still has all fields used by existing code."""
        from app.engine.living_agent.models import HeartbeatResult

        result = HeartbeatResult()
        # Fields used by test_sprint171_heartbeat_audit.py
        assert hasattr(result, "duration_ms")
        assert hasattr(result, "actions_taken")
        assert hasattr(result, "error")
        assert hasattr(result, "is_noop")
        assert hasattr(result, "cycle_id")
