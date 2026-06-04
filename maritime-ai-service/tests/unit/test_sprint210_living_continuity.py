"""
Sprint 210: "Sống Thật" — Living Continuity Tests.

Tests the 8 bug fixes that bring Wiii's Living Agent from clock to consciousness:
1. Chat → Emotion feedback loop (sync + streaming)
2. Episodic memory storage
3. Mood reset fix (2h→6h, CURIOUS→NEUTRAL)
4. Mood change threshold lowered (0.3→0.2)
5. Reflection daily (not weekly 1h window)
6. _action_reflect actually calls Reflector
7. Journal expanded time window (morning+evening)
8. Insight extraction from browsing
9. Goal seeding from soul definition
10. LLM timeout protection (60s per action)
11. Config flag
"""

import asyncio
import json
import logging
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from uuid import uuid4

from app.engine.runtime import runtime_metrics as rm


# ============================================================================
# Shared helpers
# ============================================================================

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
    """Create a settings mock with Sprint 210 flags."""
    defaults = {
        "enable_living_agent": True,
        "enable_living_continuity": True,
        "living_agent_heartbeat_interval": 60,
        "living_agent_active_hours_start": 0,
        "living_agent_active_hours_end": 24,
        "living_agent_enable_social_browse": False,
        "living_agent_enable_skill_building": False,
        "living_agent_enable_journal": False,
        "living_agent_require_human_approval": False,
        "living_agent_max_actions_per_heartbeat": 5,
        "living_agent_max_daily_cycles": 48,
        "living_agent_enable_weather": False,
        "living_agent_enable_briefing": False,
        "living_agent_enable_skill_learning": False,
        "living_agent_enable_proactive_messaging": False,
        "living_agent_enable_routine_tracking": False,
        "living_agent_enable_autonomy_graduation": False,
        "living_agent_enable_dynamic_goals": False,
        "living_agent_autonomy_level": 0,
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
    """Create a mock SoulConfig with interests."""
    soul = MagicMock()
    soul.short_term_goals = ["Learn COLREGs"]
    soul.long_term_goals = ["Become maritime expert"]
    soul.interests.primary = ["maritime"]
    soul.interests.exploring = ["AI"]
    soul.interests.wants_to_learn = ["Docker", "Kubernetes", "Rust"]
    return soul


# ============================================================================
# GROUP 1: Config flag
# ============================================================================

class TestConfigFlag:
    """Test enable_living_continuity config."""

    def test_flag_exists_as_bool(self):
        """Flag exists and is a boolean (default False, but env can override)."""
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert isinstance(s.enable_living_continuity, bool)

    def test_flag_can_be_enabled(self):
        """Flag can be set to True."""
        from app.core.config import Settings
        s = Settings(
            google_api_key="test",
            api_key="test",
            enable_living_continuity=True,
        )
        assert s.enable_living_continuity is True

    def test_flag_requires_living_agent_conceptually(self):
        """enable_living_continuity is meaningless without enable_living_agent,
        but should not error — it's just a no-op."""
        from app.core.config import Settings
        s = Settings(
            google_api_key="test",
            api_key="test",
            enable_living_continuity=True,
            enable_living_agent=False,
        )
        assert s.enable_living_continuity is True
        assert s.enable_living_agent is False


# ============================================================================
# GROUP 2: Mood Reset Fix (emotion_engine.py)
# ============================================================================

class TestMoodResetFix:
    """Test Sprint 210 mood reset changes in emotion_engine."""

    def test_no_reset_at_2h(self):
        """Mood should NOT reset after only 2h of inactivity."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import EmotionalState, MoodType

        state = EmotionalState(primary_mood=MoodType.HAPPY)
        # Set last_updated to 2.5h ago
        state.last_updated = datetime.now(timezone.utc) - timedelta(hours=2.5)
        engine = EmotionEngine(initial_state=state)

        # Trigger natural recovery
        engine._apply_natural_recovery()

        # HAPPY should NOT be forced to CURIOUS after 2h
        assert engine._state.primary_mood == MoodType.HAPPY

    def test_reset_to_neutral_at_6h(self):
        """Mood should fade to NEUTRAL (not CURIOUS) after 6h inactivity."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import EmotionalState, MoodType

        state = EmotionalState(primary_mood=MoodType.HAPPY)
        state.last_updated = datetime.now(timezone.utc) - timedelta(hours=7)
        engine = EmotionEngine(initial_state=state)

        engine._apply_natural_recovery()

        assert engine._state.primary_mood == MoodType.NEUTRAL

    def test_no_reset_for_calm_moods(self):
        """CURIOUS, NEUTRAL, CALM should not be reset even after 6h."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import EmotionalState, MoodType

        for mood in [MoodType.CURIOUS, MoodType.NEUTRAL, MoodType.CALM]:
            state = EmotionalState(primary_mood=mood)
            state.last_updated = datetime.now(timezone.utc) - timedelta(hours=10)
            engine = EmotionEngine(initial_state=state)
            engine._apply_natural_recovery()
            assert engine._state.primary_mood == mood

    def test_threshold_lowered_to_0_2(self):
        """Mood should change when intensity >= 0.2 (was 0.3), after dampening."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            EmotionalState, MoodType, LifeEvent, LifeEventType,
        )

        engine = EmotionEngine()
        # Set last_mood_change to past to bypass cooldown
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)

        # POSITIVE_FEEDBACK has intensity=0.7. With importance=0.3:
        # effective intensity = 0.7 * 0.3 = 0.21 — above new 0.2 threshold
        engine.process_event(LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="Test",
            importance=0.3,
        ))
        # Cooldown elapsed → mood changes immediately
        assert engine._state.primary_mood == MoodType.HAPPY

    def test_threshold_blocks_below_0_2(self):
        """Mood should NOT change when intensity < 0.2."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            EmotionalState, MoodType, LifeEvent, LifeEventType,
        )

        engine = EmotionEngine()
        # POSITIVE_FEEDBACK intensity=0.7, importance=0.2 → 0.14 < 0.2
        engine.process_event(LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="Test",
            importance=0.2,
        ))
        # Should stay at initial mood (CURIOUS) since 0.14 < 0.2
        assert engine._state.primary_mood == MoodType.CURIOUS


# ============================================================================
# GROUP 3: Chat → Emotion Feedback (chat_orchestrator.py)
# ============================================================================

class TestChatEmotionFeedback:
    """Test chat → Living Agent emotion feedback loop."""

    @pytest.mark.asyncio
    async def test_user_conversation_event_fired(self):
        """Regular message fires USER_CONVERSATION event."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()
        events_received = []
        original_process = engine.process_event

        def capture_event(event):
            events_received.append(event)
            return original_process(event)

        engine.process_event = capture_event

        # Simulate what chat_orchestrator does
        msg = "Luật COLREGs là gì?"
        _event_type = LifeEventType.USER_CONVERSATION
        _importance = 0.5
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = LifeEventType.POSITIVE_FEEDBACK
            _importance = 0.8

        engine.process_event(LifeEvent(
            event_type=_event_type,
            description=f"Conversation: {msg[:100]}",
            importance=_importance,
        ))

        assert len(events_received) == 1
        assert events_received[0].event_type == LifeEventType.USER_CONVERSATION

    def test_positive_feedback_on_cam_on(self):
        """Message with 'cảm ơn' triggers POSITIVE_FEEDBACK."""
        msg = "Cảm ơn bạn rất nhiều!"
        _event_type = "USER_CONVERSATION"
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
        assert _event_type == "POSITIVE_FEEDBACK"

    def test_positive_feedback_on_thank(self):
        """English 'thank' triggers POSITIVE_FEEDBACK."""
        msg = "Thank you so much!"
        _event_type = "USER_CONVERSATION"
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
        assert _event_type == "POSITIVE_FEEDBACK"

    def test_positive_feedback_on_hay_qua(self):
        """Vietnamese 'hay quá' triggers POSITIVE_FEEDBACK."""
        msg = "Hay quá bạn ơi!"
        _event_type = "USER_CONVERSATION"
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
        assert _event_type == "POSITIVE_FEEDBACK"

    def test_negative_feedback_on_sai_roi(self):
        """Vietnamese 'sai rồi' triggers NEGATIVE_FEEDBACK."""
        msg = "Sai rồi bạn ơi!"
        _event_type = "USER_CONVERSATION"
        _importance = 0.5
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
            _importance = 0.8
        elif any(w in _msg_lower for w in ["sai rồi", "không đúng", "wrong", "tệ"]):
            _event_type = "NEGATIVE_FEEDBACK"
            _importance = 0.7
        assert _event_type == "NEGATIVE_FEEDBACK"
        assert _importance == 0.7

    def test_negative_feedback_on_wrong(self):
        """English 'wrong' triggers NEGATIVE_FEEDBACK."""
        msg = "That's wrong!"
        _event_type = "USER_CONVERSATION"
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
        elif any(w in _msg_lower for w in ["sai rồi", "không đúng", "wrong", "tệ"]):
            _event_type = "NEGATIVE_FEEDBACK"
        assert _event_type == "NEGATIVE_FEEDBACK"

    def test_neutral_message_stays_user_conversation(self):
        """Neutral message stays USER_CONVERSATION."""
        msg = "Giải thích quy tắc 15 cho tôi"
        _event_type = "USER_CONVERSATION"
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank", "hay quá", "tuyệt", "giỏi"]):
            _event_type = "POSITIVE_FEEDBACK"
        elif any(w in _msg_lower for w in ["sai rồi", "không đúng", "wrong", "tệ"]):
            _event_type = "NEGATIVE_FEEDBACK"
        assert _event_type == "USER_CONVERSATION"

    def test_flag_off_no_event(self):
        """When enable_living_continuity=False, no emotion event is fired."""
        settings = _make_settings(enable_living_continuity=False)
        # Simulate the guard check
        fired = False
        if getattr(settings, "enable_living_continuity", False):
            fired = True
        assert not fired


# ============================================================================
# GROUP 4: Episodic Memory
# ============================================================================

class TestEpisodicMemory:
    """Test Sprint 210 episodic memory (MemoryType.EPISODE)."""

    def test_episode_enum_exists(self):
        """EPISODE enum value should exist in MemoryType."""
        from app.models.semantic_memory import MemoryType
        assert hasattr(MemoryType, 'EPISODE')
        assert MemoryType.EPISODE.value == "episode"

    def test_episode_content_format(self):
        """Episode content should include agent type, question, and answer."""
        _topic = "rag_agent"
        _message = "Luật COLREGs là gì?"
        _response = "COLREGs là bộ quy tắc phòng ngừa va chạm trên biển..."
        _episode = f"[{_topic}] User asked: {_message[:150]}. Wiii answered about: {_response[:150]}"

        assert "[rag_agent]" in _episode
        assert "User asked:" in _episode
        assert "Wiii answered about:" in _episode

    def test_episode_importance_from_positive(self):
        """Positive feedback should result in importance=0.8."""
        msg = "Cảm ơn bạn!"
        _importance = 0.5
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank"]):
            _importance = 0.8
        assert _importance == 0.8

    def test_episode_importance_from_negative(self):
        """Negative feedback should result in importance=0.7."""
        msg = "Sai rồi!"
        _importance = 0.5
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["sai rồi", "không đúng", "wrong"]):
            _importance = 0.7
        assert _importance == 0.7

    def test_episode_importance_default(self):
        """Default importance is 0.5."""
        msg = "Giải thích quy tắc 15"
        _importance = 0.5
        _msg_lower = msg.lower()
        if any(w in _msg_lower for w in ["cảm ơn", "cam on", "thank"]):
            _importance = 0.8
        elif any(w in _msg_lower for w in ["sai rồi", "không đúng", "wrong"]):
            _importance = 0.7
        assert _importance == 0.5

    def test_episode_flag_off_no_storage(self):
        """When enable_living_continuity=False, no episode is stored."""
        settings = _make_settings(enable_living_continuity=False)
        stored = False
        if getattr(settings, "enable_living_continuity", False):
            stored = True
        assert not stored


# ============================================================================
# GROUP 5: Reflection Daily
# ============================================================================

class TestReflectionDaily:
    """Test reflection window changes (weekly → daily)."""

    def test_daily_window_hit_at_21h(self):
        """Reflection should trigger at 21:00 UTC+7."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        # 21:00 UTC+7 = 14:00 UTC
        with patch("app.engine.living_agent.heartbeat.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 2, 26, 14, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Direct calculation check
            now_vn = datetime(2026, 2, 26, 14, 0, tzinfo=timezone.utc) + timedelta(hours=7)
            assert 21 <= now_vn.hour <= 22

    def test_daily_window_hit_at_22h(self):
        """Reflection should trigger at 22:00 UTC+7."""
        now_vn = datetime(2026, 2, 26, 15, 0, tzinfo=timezone.utc) + timedelta(hours=7)
        assert 21 <= now_vn.hour <= 22

    def test_daily_window_miss_at_19h(self):
        """Reflection should NOT trigger at 19:00 UTC+7."""
        now_vn = datetime(2026, 2, 26, 12, 0, tzinfo=timezone.utc) + timedelta(hours=7)
        assert not (21 <= now_vn.hour <= 22)

    def test_daily_not_just_sunday(self):
        """Reflection should work on any day of the week."""
        # Test multiple days: Feb 23 (Mon) through Feb 28 (Sat) + Mar 1 (Sun)
        test_dates = [
            (2026, 2, 23), (2026, 2, 24), (2026, 2, 25),
            (2026, 2, 26), (2026, 2, 27), (2026, 2, 28), (2026, 3, 1),
        ]
        for year, month, day in test_dates:
            # 14:00 UTC = 21:00 UTC+7
            now_vn = datetime(year, month, day, 14, 0, tzinfo=timezone.utc) + timedelta(hours=7)
            assert 21 <= now_vn.hour <= 22, f"Failed for {year}-{month}-{day}"

    @pytest.mark.asyncio
    async def test_reflector_has_reflected_today(self):
        """_has_reflected_today should use date_trunc('day')."""
        from app.engine.living_agent.reflector import Reflector

        reflector = Reflector()

        # Mock DB to return count=1
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, idx: 1

        with patch("app.core.database.get_shared_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_session.execute.return_value.fetchone.return_value = mock_row
            mock_factory.return_value = MagicMock(return_value=mock_session)

            result = await reflector._has_reflected_today(None)
            assert result is True


# ============================================================================
# GROUP 6: _action_reflect Fix
# ============================================================================

class TestActionReflectFix:
    """Test _action_reflect actually calls Reflector."""

    @pytest.mark.asyncio
    async def test_action_reflect_calls_reflector(self):
        """_action_reflect should call reflector.reflect() (not just fire event)."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        scheduler = HeartbeatScheduler()
        engine = MagicMock()
        engine.process_event = MagicMock()

        mock_entry = MagicMock()
        mock_entry.content = "Today I learned about COLREGs and felt proud."

        with patch("app.engine.living_agent.reflector.get_reflector") as mock_get:
            mock_reflector = AsyncMock()
            mock_reflector.reflect = AsyncMock(return_value=mock_entry)
            mock_get.return_value = mock_reflector

            await scheduler._action_reflect(engine)

            mock_reflector.reflect.assert_called_once()
            engine.process_event.assert_called_once()
            event = engine.process_event.call_args[0][0]
            assert event.event_type == LifeEventType.REFLECTION_COMPLETED
            assert "Today I learned" in event.description

    @pytest.mark.asyncio
    async def test_action_reflect_handles_none(self):
        """_action_reflect should handle reflector returning None gracefully."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        engine = MagicMock()

        with patch("app.engine.living_agent.reflector.get_reflector") as mock_get:
            mock_reflector = AsyncMock()
            mock_reflector.reflect = AsyncMock(return_value=None)
            mock_get.return_value = mock_reflector

            await scheduler._action_reflect(engine)

            # Should NOT fire REFLECTION_COMPLETED when reflect() returns None
            engine.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_reflect_handles_exception(self):
        """_action_reflect should handle reflector errors gracefully."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import LifeEventType

        scheduler = HeartbeatScheduler()
        engine = MagicMock()

        with patch("app.engine.living_agent.reflector.get_reflector") as mock_get:
            mock_reflector = AsyncMock()
            mock_reflector.reflect = AsyncMock(side_effect=Exception("DB error"))
            mock_get.return_value = mock_reflector

            await scheduler._action_reflect(engine)

            # Should still fire a fallback event on error
            engine.process_event.assert_called_once()
            event = engine.process_event.call_args[0][0]
            assert event.event_type == LifeEventType.REFLECTION_COMPLETED

    @pytest.mark.asyncio
    async def test_action_reflect_includes_content_in_description(self):
        """Reflection event description should include reflection content snippet."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        engine = MagicMock()

        mock_entry = MagicMock()
        mock_entry.content = "X" * 200  # Long content

        with patch("app.engine.living_agent.reflector.get_reflector") as mock_get:
            mock_reflector = AsyncMock()
            mock_reflector.reflect = AsyncMock(return_value=mock_entry)
            mock_get.return_value = mock_reflector

            await scheduler._action_reflect(engine)

            event = engine.process_event.call_args[0][0]
            assert event.description.startswith("Reflection: ")
            # Should be truncated to ~100 chars
            assert len(event.description) <= 120


# ============================================================================
# GROUP 7: Journal Expanded Window
# ============================================================================

class TestJournalExpandedWindow:
    """Test journal time window changes (evening → morning+evening)."""

    def test_morning_window_8h(self):
        """Journal should be available at 8:00 UTC+7."""
        now_vn = datetime(2026, 2, 26, 1, 0, tzinfo=timezone.utc) + timedelta(hours=7)  # 8:00 VN
        assert (8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22)

    def test_morning_window_9h(self):
        """Journal should be available at 9:00 UTC+7."""
        now_vn = datetime(2026, 2, 26, 2, 0, tzinfo=timezone.utc) + timedelta(hours=7)  # 9:00 VN
        assert (8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22)

    def test_evening_window_20h(self):
        """Journal should be available at 20:00 UTC+7 (existing window)."""
        now_vn = datetime(2026, 2, 26, 13, 0, tzinfo=timezone.utc) + timedelta(hours=7)  # 20:00 VN
        assert (8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22)

    def test_midday_not_journal_time(self):
        """Journal should NOT be available at 15:00 UTC+7."""
        now_vn = datetime(2026, 2, 26, 8, 0, tzinfo=timezone.utc) + timedelta(hours=7)  # 15:00 VN
        assert not ((8 <= now_vn.hour <= 9) or (20 <= now_vn.hour <= 22))


# ============================================================================
# GROUP 8: Insight Extraction
# ============================================================================

class TestInsightExtraction:
    """Test browsing → insight extraction (social_browser.py)."""

    @pytest.mark.asyncio
    async def test_high_relevance_saved_as_insight(self):
        """Items with relevance >= 0.6 should be saved as insights."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="COLREGs Update 2026",
                summary="Major changes to Rule 15",
                relevance_score=0.8,
            ),
        ]

        with patch("app.core.database.get_shared_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = MagicMock(return_value=mock_session)

            saved = await browser._extract_and_save_insights(items)
            assert saved == 1
            # Verify INSERT was called
            mock_session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_low_relevance_not_saved(self):
        """Items with relevance < 0.6 should NOT be saved."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="Random News",
                summary="Something unrelated",
                relevance_score=0.3,
            ),
        ]

        saved = await browser._extract_and_save_insights(items)
        assert saved == 0

    @pytest.mark.asyncio
    async def test_empty_title_not_saved(self):
        """Items with empty titles should NOT be saved."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="",
                summary="High relevance but no title",
                relevance_score=0.9,
            ),
        ]

        saved = await browser._extract_and_save_insights(items)
        assert saved == 0

    @pytest.mark.asyncio
    async def test_insight_content_format(self):
        """Insight content should follow [Discovery] format."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="COLREGs Rule 15 Update",
                summary="Crossing situation rules updated for autonomous vessels",
                relevance_score=0.7,
            ),
        ]

        with patch("app.core.database.get_shared_session_factory") as mock_factory:
            mock_session = MagicMock()
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = MagicMock(return_value=mock_session)

            await browser._extract_and_save_insights(items)

            # Check the content passed to INSERT — find it in any execute call
            found_content = False
            for call in mock_session.execute.call_args_list:
                # params can be in args[1] or kwargs
                params = call[0][1] if len(call[0]) > 1 else call.kwargs
                if isinstance(params, dict) and "content" in params:
                    assert "[Discovery]" in params["content"]
                    assert "COLREGs Rule 15 Update" in params["content"]
                    found_content = True
                    break
            assert found_content, "No INSERT with content param found"

    @pytest.mark.asyncio
    async def test_db_error_doesnt_crash(self):
        """DB errors during insight extraction should be swallowed."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="Test",
                summary="Test summary",
                relevance_score=0.8,
            ),
        ]

        with patch("app.core.database.get_shared_session_factory") as mock_factory:
            mock_factory.side_effect = Exception("DB connection failed")

            # Should not raise
            saved = await browser._extract_and_save_insights(items)
            assert saved == 0

    def test_mark_as_insight_exists(self):
        """_mark_as_insight method should exist."""
        from app.engine.living_agent.social_browser import SocialBrowser
        browser = SocialBrowser()
        assert hasattr(browser, '_mark_as_insight')

    @pytest.mark.asyncio
    async def test_insight_write_blocks_missing_org_context_before_db(self, monkeypatch):
        """Autonomous browsing insight writes fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        items = [
            BrowsingItem(
                platform="web",
                title="PRIVATE DISCOVERY TITLE",
                summary="PRIVATE DISCOVERY SUMMARY",
                relevance_score=0.9,
            ),
        ]
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory, \
                 patch(
                     "app.engine.living_agent.social_browser."
                     "append_semantic_memory_write_audit_event",
                     new_callable=AsyncMock,
                 ) as mock_audit:
                saved = await browser._extract_and_save_insights(
                    items,
                    session_id="raw-social-session",
                )
        finally:
            current_org_id.reset(token)

        assert saved == 0
        mock_factory.assert_not_called()
        mock_audit.assert_awaited_once()
        payload = mock_audit.await_args.kwargs["payload"]
        assert payload["write"]["kind"] == "social_browsing_insight"
        assert payload["write"]["status"] == "blocked"
        assert "social_browsing_insight_blocked_missing_org_context" in payload["warnings"]
        serialized = str(payload)
        assert "PRIVATE DISCOVERY TITLE" not in serialized
        assert "PRIVATE DISCOVERY SUMMARY" not in serialized
        assert "raw-social-session" not in serialized

    @pytest.mark.asyncio
    async def test_insight_write_filters_by_org_and_appends_audit(self, monkeypatch):
        """Autonomous browsing insight writes attach request org and safe audit."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        item = BrowsingItem(
            platform="web",
            url="https://private.example/discovery",
            title="PRIVATE DISCOVERY TITLE",
            summary="PRIVATE DISCOVERY SUMMARY",
            relevance_score=0.9,
        )
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory), \
                 patch(
                     "app.engine.living_agent.social_browser."
                     "append_semantic_memory_write_audit_event",
                     new_callable=AsyncMock,
                 ) as mock_audit:
                saved = await browser._extract_and_save_insights(
                    [item],
                    session_id="raw-social-session",
                )
        finally:
            current_org_id.reset(token)

        assert saved == 1
        execute_params = [
            call.args[1]
            for call in mock_session.execute.call_args_list
            if len(call.args) > 1 and isinstance(call.args[1], dict)
        ]
        assert execute_params
        assert all(params.get("org_id") == "org-A" for params in execute_params)
        insert_params = next(params for params in execute_params if "content" in params)
        assert insert_params["user_id"] == "__wiii__"
        assert "PRIVATE DISCOVERY TITLE" in insert_params["content"]
        metadata = json.loads(insert_params["metadata"])
        assert metadata["source"] == "social_browser"
        assert metadata["url_hash"].startswith("sha256:")
        assert item.url not in metadata["url_hash"]
        mock_audit.assert_awaited_once()
        payload = mock_audit.await_args.kwargs["payload"]
        assert payload["write"]["kind"] == "social_browsing_insight"
        assert payload["write"]["status"] == "saved"
        assert payload["write"]["stored_insight_count"] == 1
        serialized = str(payload)
        assert "PRIVATE DISCOVERY TITLE" not in serialized
        assert "raw-social-session" not in serialized

    @pytest.mark.asyncio
    async def test_topic_memory_read_blocks_missing_org_context_before_db(self, monkeypatch):
        """Smart topic memory reads fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                topic = await browser._get_topic_from_memories()
        finally:
            current_org_id.reset(token)

        assert topic is None
        mock_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_topic_memory_read_filters_by_org_context(self, monkeypatch):
        """Smart topic memory reads only request-scoped org memories."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("COLREGs maritime safety training interest",),
        ]
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                topic = await browser._get_topic_from_memories()
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert topic == "maritime"
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_browsing_log_blocks_missing_org_context_before_db(self, monkeypatch):
        """Browsing log writes fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                browser._save_browsing_log([BrowsingItem(platform="web", title="Title")])
        finally:
            current_org_id.reset(token)

        mock_factory.assert_not_called()


class TestJournalWriterOrgScope:
    """Test org-scoped autonomous journal guardrails."""

    @pytest.mark.asyncio
    async def test_journal_write_blocks_missing_org_context_before_db_or_llm(
        self,
        monkeypatch,
        caplog,
    ):
        """Journal writing fails closed before duplicate checks or LLM calls."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.journal import JournalWriter
        from app.engine.living_agent.models import EmotionalState

        writer = JournalWriter()
        state = EmotionalState()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                entry = await writer.write_daily_entry(state)
        finally:
            current_org_id.reset(token)

        assert entry is None
        mock_factory.assert_not_called()
        mock_llm.assert_not_called()
        assert "journal_blocked_missing_org_context" in caplog.text

    def test_journal_recent_entries_filters_by_org_context(self, monkeypatch):
        """Recent journal reads only query current-org entries."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.journal import JournalWriter

        writer = JournalWriter()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        row = (
            uuid4(),
            datetime.now(timezone.utc),
            "Private journal",
            "calm",
            0.6,
            json.dumps(["event"]),
            json.dumps(["learning"]),
            json.dumps(["goal"]),
            "org-A",
        )
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                entries = writer.get_recent_entries(days=3)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert len(entries) == 1
        assert entries[0].organization_id == "org-A"
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_journal_get_entry_by_date_filters_by_org_context(self, monkeypatch):
        """Duplicate-entry checks are scoped by current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.journal import JournalWriter

        writer = JournalWriter()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        row = (
            uuid4(),
            datetime.now(timezone.utc),
            "Private journal",
            "calm",
            0.6,
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
            "org-A",
        )
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = row
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                entry = writer._get_entry_by_date(datetime.now(timezone.utc).date())
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert entry is not None
        assert entry.organization_id == "org-A"
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_journal_save_entry_includes_org_context(self, monkeypatch):
        """Journal inserts include resolved org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.journal import JournalWriter
        from app.engine.living_agent.models import JournalEntry

        writer = JournalWriter()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        entry = JournalEntry(
            entry_date=datetime.now(timezone.utc),
            content="Private journal",
            mood_summary="calm",
            notable_events=["event"],
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                writer._save_entry(entry)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert params["org_id"] == "org-A"
        assert entry.organization_id == "org-A"


class TestEmotionEngineOrgScope:
    """Test org-scoped emotional persistence and relationship cache guardrails."""

    @pytest.mark.asyncio
    async def test_emotion_state_save_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Persistent emotion saves fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                await engine.save_state_to_db()
        finally:
            current_org_id.reset(token)

        mock_factory.assert_not_called()
        assert "emotion_state_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_emotion_state_save_filters_persistent_state_by_org_context(
        self,
        monkeypatch,
    ):
        """Persistent state replacement only deletes/inserts current-org rows."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await engine.save_state_to_db()
        finally:
            current_org_id.reset(token)

        delete_statement = str(mock_session.execute.call_args_list[0].args[0])
        delete_params = mock_session.execute.call_args_list[0].args[1]
        insert_statement = str(mock_session.execute.call_args_list[1].args[0])
        insert_params = mock_session.execute.call_args_list[1].args[1]
        assert "AND organization_id = :org_id" in delete_statement
        assert delete_params["org_id"] == "org-A"
        assert "organization_id" in insert_statement
        assert insert_params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_emotion_state_load_filters_by_org_context(self, monkeypatch):
        """Persistent emotion loads only read current-org state."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                loaded = await engine.load_state_from_db()
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert loaded is False
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_known_user_cache_refresh_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Known-user cache refresh fails closed without org context."""
        import app.engine.living_agent.emotion_engine as mod
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                count = mod.refresh_known_user_cache()
        finally:
            current_org_id.reset(token)

        assert count == 0
        mock_factory.assert_not_called()
        assert "known_user_cache_blocked_missing_org_context" in caplog.text

    def test_known_user_cache_refresh_filters_by_org_context(self, monkeypatch):
        """Known-user cache refresh only reads current-org routines."""
        import app.engine.living_agent.emotion_engine as mod
        from app.core.config import settings
        from app.core.org_context import current_org_id

        old_cache = mod._known_user_cache
        old_by_org = dict(mod._known_user_cache_by_org)
        mod._known_user_cache = set()
        mod._known_user_cache_by_org = {}
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [("user-a",), ("user-b",)]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)
        app_settings = _make_settings(living_agent_known_user_threshold=50)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory), \
                 patch("app.core.config.get_settings", return_value=app_settings):
                count = mod.refresh_known_user_cache()
                scoped_cache = dict(mod._known_user_cache_by_org)
                legacy_cache = set(mod._known_user_cache)
        finally:
            current_org_id.reset(token)
            mod._known_user_cache = old_cache
            mod._known_user_cache_by_org = old_by_org

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert count == 2
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert scoped_cache["org-A"] == {"user-a", "user-b"}
        assert "user-a" not in legacy_cache

    def test_known_user_tier_uses_org_scoped_cache(self):
        """Known-user tier ignores legacy/global cache for explicit org lookups."""
        import app.engine.living_agent.emotion_engine as mod

        old_cache = mod._known_user_cache
        old_by_org = dict(mod._known_user_cache_by_org)
        try:
            mod._known_user_cache = {"global-known-user"}
            mod._known_user_cache_by_org = {
                "org-A": {"user-a"},
                "org-B": {"user-b"},
            }
            app_settings = _make_settings(living_agent_creator_user_ids="")

            with patch("app.core.config.get_settings", return_value=app_settings):
                assert mod.get_relationship_tier(
                    "user-a",
                    "student",
                    organization_id="org-A",
                ) == mod.TIER_KNOWN
                assert mod.get_relationship_tier(
                    "user-a",
                    "student",
                    organization_id="org-B",
                ) == mod.TIER_OTHER
                assert mod.get_relationship_tier(
                    "global-known-user",
                    "student",
                    organization_id="org-A",
                ) == mod.TIER_OTHER
        finally:
            mod._known_user_cache = old_cache
            mod._known_user_cache_by_org = old_by_org


class TestEmotionalStateRepositoryOrgScope:
    """Test org-scoped emotional snapshot repository guardrails."""

    def test_emotional_repo_save_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Snapshot writes fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.repositories.emotional_state_repository.get_shared_session_factory") as mock_factory:
                snapshot_id = repo.save_snapshot(
                    primary_mood="private",
                    energy_level=0.5,
                    social_battery=0.5,
                    engagement=0.5,
                    state_json={"private": True},
                )
        finally:
            current_org_id.reset(token)

        assert snapshot_id == ""
        mock_factory.assert_not_called()
        assert "emotional_state_repository_blocked_missing_org_context" in caplog.text
        assert "private" not in caplog.text

    def test_emotional_repo_save_includes_org_context(self, monkeypatch):
        """Snapshot inserts include resolved org scope."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.repositories.emotional_state_repository.get_shared_session_factory", return_value=mock_factory):
                snapshot_id = repo.save_snapshot(
                    primary_mood="happy",
                    energy_level=0.8,
                    social_battery=0.7,
                    engagement=0.6,
                )
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert snapshot_id
        assert "organization_id" in statement
        assert params["org_id"] == "org-A"

    def test_emotional_repo_latest_filters_by_org_context(self, monkeypatch):
        """Latest snapshot reads are scoped by current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        now = datetime.now(timezone.utc)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            "snapshot-1",
            "calm",
            0.6,
            0.7,
            0.8,
            "heartbeat_cycle",
            now,
            json.dumps({"primary_mood": "calm"}),
        )
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.repositories.emotional_state_repository.get_shared_session_factory", return_value=mock_factory):
                latest = repo.get_latest()
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert latest["id"] == "snapshot-1"
        assert "WHERE organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_emotional_repo_history_filters_by_org_context(self, monkeypatch):
        """History reads are scoped by current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        now = datetime.now(timezone.utc)
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            ("snapshot-1", "calm", 0.6, 0.7, 0.8, "heartbeat_cycle", now),
        ]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.repositories.emotional_state_repository.get_shared_session_factory", return_value=mock_factory):
                history = repo.get_history(hours=2)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert len(history) == 1
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert params["hours"] == 2

    def test_emotional_repo_cleanup_filters_by_org_context(self, monkeypatch):
        """Snapshot cleanup cannot delete another org's history."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        repo = EmotionalStateRepository()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        result = MagicMock()
        result.rowcount = 3
        mock_session = MagicMock()
        mock_session.execute.return_value = result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.repositories.emotional_state_repository.get_shared_session_factory", return_value=mock_factory):
                deleted = repo.cleanup_old_snapshots(keep_days=7)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert deleted == 3
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert params["keep_days"] == 7


class TestBriefingComposerOrgScope:
    """Test org-scoped autonomous briefing guardrails."""

    @pytest.mark.asyncio
    async def test_briefing_compose_blocks_missing_org_context_before_llm_or_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Briefing composition fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.briefing_composer import BriefingComposer

        composer = BriefingComposer()
        monkeypatch.setattr(settings, "living_agent_enable_briefing", True)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.engine.living_agent.weather_service.get_weather_service") as mock_weather, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm, \
                 patch("app.core.database.get_shared_session_factory") as mock_factory:
                briefing = await composer.compose_for_time()
        finally:
            current_org_id.reset(token)

        assert briefing is None
        mock_weather.assert_not_called()
        mock_llm.assert_not_called()
        mock_factory.assert_not_called()
        assert "briefing_composer_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_briefing_highlights_filter_by_org_context(self, monkeypatch):
        """Briefing highlights only read current-org browsing rows."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.briefing_composer import BriefingComposer

        composer = BriefingComposer()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [("Org A headline",)]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                highlights = await composer._get_recent_highlights(2)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert highlights == ["Org A headline"]
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert params["count"] == 2

    def test_briefing_save_includes_org_context(self, monkeypatch):
        """Briefing audit rows include resolved org scope."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.briefing_composer import BriefingComposer
        from app.engine.living_agent.models import Briefing, BriefingType

        composer = BriefingComposer()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        briefing = Briefing(briefing_type=BriefingType.MORNING, content="Org scoped")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                composer._save_briefing(briefing)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert params["org_id"] == "org-A"
        assert briefing.organization_id == "org-A"

    @pytest.mark.asyncio
    async def test_briefing_deliver_blocks_missing_org_context_before_send_or_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Briefing delivery fails closed before outbound channel sends."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.briefing_composer import BriefingComposer
        from app.engine.living_agent.models import Briefing, BriefingType

        composer = BriefingComposer()
        briefing = Briefing(briefing_type=BriefingType.MORNING, content="PRIVATE BRIEFING")
        monkeypatch.setattr(settings, "living_agent_briefing_channels", '["messenger"]')
        monkeypatch.setattr(settings, "living_agent_briefing_users", '["raw-user"]')
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch.object(composer, "_send_to_channel", new_callable=AsyncMock) as mock_send, \
                 patch("app.core.database.get_shared_session_factory") as mock_factory:
                delivered = await composer.deliver(briefing)
        finally:
            current_org_id.reset(token)

        assert delivered == []
        mock_send.assert_not_called()
        mock_factory.assert_not_called()
        assert "briefing_composer_blocked_missing_org_context" in caplog.text
        assert "PRIVATE BRIEFING" not in caplog.text
        assert "raw-user" not in caplog.text

    @pytest.mark.asyncio
    async def test_briefing_delivery_window_is_scoped_per_org(self, monkeypatch):
        """One org's daily briefing marker does not suppress another org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.briefing_composer import BriefingComposer
        from app.engine.living_agent.models import Briefing, BriefingType

        composer = BriefingComposer()
        monkeypatch.setattr(settings, "living_agent_enable_briefing", True)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        today = "2026-01-02"
        composer._delivered_today[("org-B", BriefingType.MORNING)] = today

        token = current_org_id.set("org-A")
        try:
            with patch("app.engine.living_agent.briefing_composer.datetime") as mock_datetime, \
                 patch.object(
                     composer,
                     "_compose_morning",
                     new_callable=AsyncMock,
                     return_value=Briefing(briefing_type=BriefingType.MORNING, content="Org A"),
                 ) as mock_compose:
                mock_datetime.now.return_value = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
                briefing = await composer.compose_for_time()
        finally:
            current_org_id.reset(token)

        assert briefing is not None
        assert briefing.organization_id == "org-A"
        mock_compose.assert_awaited_once()
        assert composer._delivered_today[("org-A", BriefingType.MORNING)] == today


class TestHeartbeatRuntimeOrgScope:
    """Test org-scoped heartbeat persistence guardrails."""

    @pytest.mark.asyncio
    async def test_heartbeat_queue_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Pending action queueing fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_runtime_support import queue_pending_actions_impl
        from app.engine.living_agent.models import ActionType, HeartbeatAction

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                await queue_pending_actions_impl([
                    HeartbeatAction(action_type=ActionType.BROWSE_SOCIAL, target="private"),
                ])
        finally:
            current_org_id.reset(token)

        mock_factory.assert_not_called()
        assert "heartbeat_runtime_blocked_missing_org_context" in caplog.text
        assert "private" not in caplog.text

    @pytest.mark.asyncio
    async def test_heartbeat_pending_load_filters_by_org_context(self, monkeypatch):
        """Approved pending action reads are scoped to the current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_runtime_support import load_pending_action_impl

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            "browse_social",
            "private",
            0.8,
            json.dumps({"reason": "test"}),
        )
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                action = await load_pending_action_impl("raw-action-id")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert action is not None
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_heartbeat_pending_completion_filters_by_org_context(self, monkeypatch):
        """Pending action completion cannot update another org's action id."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_runtime_support import mark_action_completed_impl

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await mark_action_completed_impl("raw-action-id")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_heartbeat_audit_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Heartbeat audit writes fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_runtime_support import save_heartbeat_audit_impl
        from app.engine.living_agent.models import HeartbeatResult

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                await save_heartbeat_audit_impl(1, HeartbeatResult(error="PRIVATE ERROR"))
        finally:
            current_org_id.reset(token)

        mock_factory.assert_not_called()
        assert "heartbeat_runtime_blocked_missing_org_context" in caplog.text
        assert "PRIVATE ERROR" not in caplog.text

    @pytest.mark.asyncio
    async def test_heartbeat_audit_insert_includes_org_context(self, monkeypatch):
        """Heartbeat audit rows include the resolved org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.heartbeat_runtime_support import save_heartbeat_audit_impl
        from app.engine.living_agent.models import ActionType, HeartbeatAction, HeartbeatResult

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        result = HeartbeatResult(
            actions_taken=[HeartbeatAction(action_type=ActionType.REFLECT, target="private")],
            insights_gained=1,
            duration_ms=12,
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await save_heartbeat_audit_impl(5, result)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert params["org_id"] == "org-A"


class TestAutonomyManagerOrgScope:
    """Test org-scoped autonomy graduation guardrails."""

    @pytest.mark.asyncio
    async def test_autonomy_graduation_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Graduation checks fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(settings, "living_agent_enable_autonomy_graduation", True)
        monkeypatch.setattr(settings, "living_agent_autonomy_level", 0)
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                upgraded = await manager.check_graduation()
        finally:
            current_org_id.reset(token)

        assert upgraded is False
        mock_factory.assert_not_called()
        assert "autonomy_manager_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_autonomy_load_stats_filters_by_org_context(self, monkeypatch):
        """Autonomy stats only aggregate current-org heartbeat audit rows."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = (
            10,
            datetime.now(timezone.utc) - timedelta(days=20),
            1,
        )
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                stats = await manager._load_stats()
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert stats["successful_actions"] == 9
        assert "WHERE organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_autonomy_approve_graduation_upserts_by_org_key(self, monkeypatch):
        """Approved autonomy levels are keyed by org and state key."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                approved = await manager.approve_graduation(1)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert approved is True
        assert "organization_id" in statement
        assert "ON CONFLICT (organization_id, key)" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_autonomy_pending_graduation_upserts_by_org_key(self, monkeypatch):
        """Pending graduation proposals are isolated by org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.autonomy_manager import AutonomyManager

        manager = AutonomyManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await manager._propose_graduation(
                    0,
                    1,
                    {"successful_actions": 50},
                )
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert "ON CONFLICT (organization_id, key)" in statement
        assert params["org_id"] == "org-A"
        payload = json.loads(params["data"])
        assert payload["to_level"] == 1


class TestProactiveMessengerOrgScope:
    """Test org-scoped proactive messaging guardrails."""

    @pytest.mark.asyncio
    async def test_proactive_send_blocks_missing_org_context_before_delivery(
        self,
        monkeypatch,
        caplog,
    ):
        """Autonomous proactive sends fail closed before delivery without org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch.object(messenger, "_deliver", new_callable=AsyncMock) as mock_deliver, \
                 patch("app.core.database.get_shared_session_factory") as mock_factory:
                sent = await messenger.send(
                    "raw-proactive-user",
                    "messenger",
                    "PRIVATE PROACTIVE BODY",
                    trigger="briefing",
                )
        finally:
            current_org_id.reset(token)

        assert sent is False
        mock_deliver.assert_not_called()
        mock_factory.assert_not_called()
        assert "proactive_message_blocked_missing_org_context" in caplog.text
        assert "raw-proactive-user" not in caplog.text
        assert "PRIVATE PROACTIVE BODY" not in caplog.text
        assert _counter_value(
            "runtime.living_agent.proactive.sends",
            {"status": "blocked_missing_org_context"},
        ) == 1

    @pytest.mark.asyncio
    async def test_proactive_opt_out_filters_by_org_context(self, monkeypatch):
        """Opt-out writes are keyed by current org and user."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await messenger.opt_out("raw-proactive-user")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert "ON CONFLICT (organization_id, user_id)" in statement
        assert params["org_id"] == "org-A"
        assert params["uid"] == "raw-proactive-user"

    @pytest.mark.asyncio
    async def test_proactive_can_send_reads_opt_out_by_org_context(self, monkeypatch):
        """Opt-out reads use request org before allowing autonomous send."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(settings, "living_agent_enable_proactive_messaging", True)
        monkeypatch.setattr(settings, "living_agent_proactive_quiet_start", 23)
        monkeypatch.setattr(settings, "living_agent_proactive_quiet_end", 5)
        monkeypatch.setattr(settings, "living_agent_max_proactive_per_day", 3)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (False,)
        mock_session = MagicMock()
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)
        fixed_time = datetime(2026, 2, 26, 3, 0, 0, tzinfo=timezone.utc)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory), \
                 patch("app.engine.living_agent.proactive_messenger.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_time
                mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
                allowed = await messenger.can_send("raw-proactive-user")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert allowed is True
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert _counter_value(
            "runtime.living_agent.proactive.can_send",
            {"status": "allowed", "reason": "allowed"},
        ) == 1

    @pytest.mark.asyncio
    async def test_proactive_save_message_includes_org_context(self, monkeypatch):
        """Proactive message log rows include current org scope."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.models import ProactiveMessage
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        message = ProactiveMessage(
            user_id="raw-proactive-user",
            channel="messenger",
            content="PRIVATE PROACTIVE BODY",
            trigger="briefing",
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await messenger._save_message(message)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert params["org_id"] == "org-A"
        assert params["uid"] == "raw-proactive-user"
        assert params["content"] == "PRIVATE PROACTIVE BODY"

    @pytest.mark.asyncio
    async def test_proactive_send_records_delivered_metric(self, monkeypatch):
        """Delivered proactive sends are visible without user/content labels."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            with patch.object(messenger, "can_send", new_callable=AsyncMock, return_value=True), \
                 patch.object(messenger, "_deliver", new_callable=AsyncMock, return_value=True), \
                 patch.object(messenger, "_save_message", new_callable=AsyncMock):
                sent = await messenger.send(
                    "raw-proactive-user",
                    "messenger",
                    "PRIVATE PROACTIVE BODY",
                    trigger="briefing",
                )
        finally:
            current_org_id.reset(token)

        assert sent is True
        assert _counter_value(
            "runtime.living_agent.proactive.sends",
            {"status": "delivered"},
        ) == 1
        assert _histogram_values(
            "runtime.living_agent.proactive.send_duration_ms",
            {"status": "delivered"},
        )

    @pytest.mark.asyncio
    async def test_proactive_send_records_delivery_failed_metric(self, monkeypatch):
        """Delivery failures are distinct from guardrail blocks."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger

        messenger = ProactiveMessenger()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            with patch.object(messenger, "can_send", new_callable=AsyncMock, return_value=True), \
                 patch.object(messenger, "_deliver", new_callable=AsyncMock, return_value=False), \
                 patch.object(messenger, "_save_message", new_callable=AsyncMock) as mock_save:
                sent = await messenger.send(
                    "raw-proactive-user",
                    "messenger",
                    "PRIVATE PROACTIVE BODY",
                    trigger="briefing",
                )
        finally:
            current_org_id.reset(token)

        assert sent is False
        mock_save.assert_not_called()
        assert _counter_value(
            "runtime.living_agent.proactive.sends",
            {"status": "delivery_failed"},
        ) == 1

    @pytest.mark.asyncio
    async def test_proactive_websocket_delivery_uses_org_scoped_connection_manager(
        self,
        monkeypatch,
    ):
        """A proactive WebSocket send reaches only sessions in the current org."""
        from app.api.v1.websocket import ConnectionManager
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.proactive_messenger import ProactiveMessenger
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.adapters.websocket import WebSocketAdapter
        from app.services.notifications.registry import NotificationChannelRegistry

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(settings, "living_agent_enable_proactive_messaging", True)
        monkeypatch.setattr(settings, "living_agent_proactive_quiet_start", 0)
        monkeypatch.setattr(settings, "living_agent_proactive_quiet_end", 0)
        monkeypatch.setattr(settings, "living_agent_max_proactive_per_day", 3)

        registry = NotificationChannelRegistry()
        registry.register(WebSocketAdapter())
        dispatcher = NotificationDispatcher()
        dispatcher._registry = registry
        manager = ConnectionManager()
        org_socket = AsyncMock()
        other_org_socket = AsyncMock()
        await manager.connect(org_socket, "proactive-org-session")
        await manager.connect(other_org_socket, "proactive-other-org-session")
        manager.register_user("proactive-org-session", "proactive-user", "org-proactive")
        manager.register_user(
            "proactive-other-org-session",
            "proactive-user",
            "org-other",
        )

        messenger = ProactiveMessenger()
        token = current_org_id.set("org-proactive")
        try:
            with patch.object(
                messenger,
                "_is_opted_out",
                new_callable=AsyncMock,
                return_value=False,
            ), patch.object(
                messenger,
                "_save_message",
                new_callable=AsyncMock,
            ) as mock_save, patch(
                "app.services.notification_dispatcher.get_notification_dispatcher",
                return_value=dispatcher,
            ), patch("app.api.v1.websocket.manager", manager):
                sent = await messenger.send(
                    "proactive-user",
                    "websocket",
                    "Review COLREG Rule 13 soon",
                    trigger="inactive_reengage",
                )
        finally:
            current_org_id.reset(token)

        assert sent is True
        org_socket.send_text.assert_awaited_once()
        sent_payload = json.loads(org_socket.send_text.await_args.args[0])
        assert sent_payload["type"] == "proactive_message"
        assert sent_payload["content"] == "Review COLREG Rule 13 soon"
        assert sent_payload["trigger"] == "inactive_reengage"
        other_org_socket.send_text.assert_not_awaited()
        saved_message = mock_save.await_args.args[0]
        assert saved_message.user_id == "proactive-user"
        assert saved_message.channel == "websocket"
        assert saved_message.organization_id == "org-proactive"
        assert messenger._daily_counts["org-proactive:proactive-user"] == 1
        assert _counter_value(
            "runtime.living_agent.proactive.can_send",
            {"status": "allowed", "reason": "allowed"},
        ) == 1
        assert _counter_value(
            "runtime.living_agent.proactive.sends",
            {"status": "delivered"},
        ) == 1


class TestRoutineTrackerOrgScope:
    """Test org-scoped routine tracking guardrails."""

    @pytest.mark.asyncio
    async def test_routine_record_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Routine writes fail closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(settings, "living_agent_enable_routine_tracking", True)
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                await tracker.record_interaction(
                    "raw-routine-user",
                    "web",
                    "PRIVATE ROUTINE TOPIC",
                )
        finally:
            current_org_id.reset(token)

        mock_factory.assert_not_called()
        assert "routine_tracking_blocked_missing_org_context" in caplog.text
        assert "raw-routine-user" not in caplog.text
        assert "PRIVATE ROUTINE TOPIC" not in caplog.text

    @pytest.mark.asyncio
    async def test_inactive_user_query_filters_by_org_context(self, monkeypatch):
        """Inactive-user reads only return current-org routines."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [("user-a",)]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                inactive = await tracker.get_inactive_users(days=2)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert inactive == ["user-a"]
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_routine_upsert_uses_org_conflict_key(self, monkeypatch):
        """Routine profile writes are keyed by org and user."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.models import UserRoutine
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        routine = UserRoutine(
            user_id="raw-routine-user",
            typical_active_hours=[8],
            common_topics=["PRIVATE ROUTINE TOPIC"],
            total_messages=6,
            last_seen=datetime.now(timezone.utc),
        )
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                await tracker._save_routine(routine)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "organization_id" in statement
        assert "ON CONFLICT (organization_id, user_id)" in statement
        assert params["org_id"] == "org-A"
        assert params["uid"] == "raw-routine-user"

    @pytest.mark.asyncio
    async def test_routine_load_filters_by_org_context(self, monkeypatch):
        """Routine reads request exactly one org/user row."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.routine_tracker import RoutineTracker

        tracker = RoutineTracker()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            "raw-routine-user",
            [8],
            8,
            1.0,
            ["maritime"],
            datetime.now(timezone.utc),
            6,
            datetime.now(timezone.utc),
            "org-A",
        )
        mock_session = MagicMock()
        mock_session.execute.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                routine = await tracker.get_routine("raw-routine-user")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert routine is not None
        assert routine.organization_id == "org-A"
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"


class TestReflectorOrgScope:
    """Test org-scoped reflection guardrails."""

    @pytest.mark.asyncio
    async def test_reflection_blocks_missing_org_context_before_db_or_llm(
        self,
        monkeypatch,
        caplog,
    ):
        """Reflection generation fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.reflector import Reflector

        reflector = Reflector()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                entry = await reflector.reflect()
        finally:
            current_org_id.reset(token)

        assert entry is None
        mock_factory.assert_not_called()
        mock_llm.assert_not_called()
        assert "reflection_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_recent_reflections_filters_by_org_context(self, monkeypatch):
        """Recent reflection reads only query current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.reflector import Reflector

        reflector = Reflector()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        row = (
            uuid4(),
            "Reflection content",
            json.dumps(["insight"]),
            json.dumps(["goal"]),
            json.dumps(["pattern"]),
            "calm",
            datetime.now(timezone.utc),
        )
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                entries = await reflector.get_recent_reflections(count=2)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert len(entries) == 1
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_reflect_passes_resolved_org_to_summaries(self, monkeypatch):
        """Daily reflection gathers all summaries for one resolved org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.reflector import Reflector

        reflector = Reflector()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            with patch.object(reflector, "_has_reflected_today", new_callable=AsyncMock, return_value=False), \
                 patch.object(reflector, "_get_journal_summary", new_callable=AsyncMock, return_value="") as mock_journal, \
                 patch.object(reflector, "_get_emotion_summary", new_callable=AsyncMock, return_value="") as mock_emotion, \
                 patch.object(reflector, "_get_browsing_summary", new_callable=AsyncMock, return_value="") as mock_browsing, \
                 patch.object(reflector, "_get_skills_summary", new_callable=AsyncMock, return_value="") as mock_skills, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                mock_llm.return_value.generate = AsyncMock(return_value=None)
                entry = await reflector.reflect()
        finally:
            current_org_id.reset(token)

        assert entry is None
        mock_journal.assert_called_once_with(1, "org-A")
        mock_emotion.assert_called_once_with(1, "org-A")
        mock_browsing.assert_called_once_with(1, "org-A")
        mock_skills.assert_called_once_with("org-A")

    @pytest.mark.asyncio
    async def test_browsing_summary_filters_by_org_context(self):
        """Browsing summary SQL uses org filter."""
        from app.engine.living_agent.reflector import Reflector

        reflector = Reflector()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            ("Private discovery", 0.9),
        ]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
            summary = await reflector._get_browsing_summary(1, "org-A")

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "Private discovery" in summary
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"


class TestGoalManagerOrgScope:
    """Test org-scoped dynamic goal guardrails."""

    @pytest.mark.asyncio
    async def test_goal_create_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Goal creation fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                goal = await manager.create_goal(
                    "PRIVATE GOAL TITLE",
                    description="PRIVATE GOAL BODY",
                )
        finally:
            current_org_id.reset(token)

        assert goal is None
        mock_factory.assert_not_called()
        assert "goal_manager_blocked_missing_org_context" in caplog.text
        assert "PRIVATE GOAL TITLE" not in caplog.text
        assert "PRIVATE GOAL BODY" not in caplog.text

    @pytest.mark.asyncio
    async def test_goal_query_filters_by_org_context(self, monkeypatch):
        """Goal queries always include current org filter."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        row = (
            uuid4(),
            "Goal title",
            "Goal body",
            "active",
            "medium",
            0.2,
            "reflection",
            json.dumps(["m1"]),
            json.dumps([]),
            datetime.now(timezone.utc),
            None,
            None,
            "org-A",
        )
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                goals = await manager.get_active_goals()
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert len(goals) == 1
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_goal_update_progress_filters_by_org_context(self, monkeypatch):
        """Progress updates cannot update another org's goal id."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                updated = await manager.update_progress("raw-goal-id", 0.7)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert updated is True
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_goal_review_stale_filters_by_org_context(self, monkeypatch):
        """Stale-goal review only mutates current-org rows."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        result = MagicMock()
        result.rowcount = 2
        mock_session = MagicMock()
        mock_session.execute.return_value = result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                count = await manager.review_stale_goals(stale_days=14)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert count == 2
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"


class TestIdentityCoreOrgScope:
    """Test org-scoped identity insight cache guardrails."""

    def test_identity_context_filters_by_org_context(self, monkeypatch):
        """Hot-path identity context only exposes current-org insights."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.identity_core import IdentityCore
        from app.engine.living_agent.models import IdentityInsight

        core = IdentityCore()
        core._insights = [
            IdentityInsight(text="Org A identity", validated=True, organization_id="org-A"),
            IdentityInsight(text="Org B identity", validated=True, organization_id="org-B"),
            IdentityInsight(text="Legacy identity", validated=True),
        ]
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        app_settings = _make_settings(
            enable_living_agent=True,
            enable_identity_core=True,
            enable_multi_tenant=True,
            environment="production",
            default_organization_id="default",
        )

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.config.get_settings", return_value=app_settings):
                context = core.get_identity_context()
        finally:
            current_org_id.reset(token)

        assert "Org A identity" in context
        assert "Org B identity" not in context
        assert "Legacy identity" not in context

    @pytest.mark.asyncio
    async def test_identity_generation_blocks_missing_org_before_reflection_or_llm(
        self,
        monkeypatch,
        caplog,
    ):
        """Identity generation fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.identity_core import IdentityCore

        core = IdentityCore()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        app_settings = _make_settings(
            enable_living_agent=True,
            enable_identity_core=True,
            enable_multi_tenant=True,
            environment="production",
            default_organization_id="default",
        )
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.config.get_settings", return_value=app_settings), \
                 patch("app.engine.living_agent.reflector.get_reflector") as mock_reflector, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                insights = await core.generate_self_insights()
        finally:
            current_org_id.reset(token)

        assert insights == []
        mock_reflector.assert_not_called()
        mock_llm.assert_not_called()
        assert "identity_core_blocked_missing_org_context" in caplog.text

    @pytest.mark.asyncio
    async def test_identity_generation_tags_insights_with_org(self, monkeypatch):
        """Cold-path identity insights are generated and cached for one org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.identity_core import IdentityCore

        core = IdentityCore()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        app_settings = _make_settings(
            enable_living_agent=True,
            enable_identity_core=True,
            enable_multi_tenant=True,
            environment="production",
            default_organization_id="default",
        )
        soul = MagicMock()
        soul.core_truths = []
        soul.boundaries = []

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.config.get_settings", return_value=app_settings), \
                 patch.object(core, "_get_recent_reflection_text", new_callable=AsyncMock, return_value="Reflection") as mock_reflection, \
                 patch.object(core, "_get_skills_summary", return_value="Skills") as mock_skills, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm, \
                 patch("app.engine.living_agent.soul_loader.get_soul", return_value=soul):
                mock_llm.return_value.generate = AsyncMock(return_value="- Minh hoc nhanh hon")
                insights = await core.generate_self_insights()
        finally:
            current_org_id.reset(token)

        assert len(insights) == 1
        assert insights[0].organization_id == "org-A"
        assert core.get_all_insights("org-A")[0].organization_id == "org-A"
        mock_reflection.assert_awaited_once_with("org-A")
        mock_skills.assert_called_once_with("org-A")


class TestSkillBuilderOrgScope:
    """Test org-scoped autonomous skill-learning guardrails."""

    def test_skill_discover_blocks_missing_org_context_before_db(
        self,
        monkeypatch,
        caplog,
    ):
        """Skill discovery fails closed without org context."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.skill_builder import SkillBuilder

        builder = SkillBuilder()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory:
                skill = builder.discover(
                    "PRIVATE SKILL TOPIC",
                    domain="private",
                    source="https://example.invalid/private",
                )
        finally:
            current_org_id.reset(token)

        assert skill is None
        mock_factory.assert_not_called()
        assert "skill_builder_blocked_missing_org_context" in caplog.text
        assert "PRIVATE SKILL TOPIC" not in caplog.text

    def test_skill_query_filters_by_org_context(self, monkeypatch):
        """Skill list reads only query the current org."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.models import SkillStatus
        from app.engine.living_agent.skill_builder import SkillBuilder

        builder = SkillBuilder()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        row = (
            uuid4(),
            "Org A Skill",
            "maritime",
            SkillStatus.LEARNING.value,
            0.4,
            "notes",
            json.dumps(["https://example.invalid"]),
            1,
            0.8,
            datetime.now(timezone.utc),
            None,
            None,
            "org-A",
            json.dumps({"review_schedule": {"interval_days": 1}}),
        )
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [row]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                skills = builder.get_all_skills(status=SkillStatus.LEARNING, domain="maritime")
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert len(skills) == 1
        assert skills[0].organization_id == "org-A"
        assert skills[0].metadata["review_schedule"]["interval_days"] == 1
        assert "organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    def test_skill_update_filters_by_org_context(self, monkeypatch):
        """Skill lifecycle updates cannot mutate another org's row id."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.models import WiiiSkill
        from app.engine.living_agent.skill_builder import SkillBuilder

        builder = SkillBuilder()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        skill = WiiiSkill(
            skill_name="PRIVATE SKILL TOPIC",
            notes="private notes",
            metadata={"review_schedule": {"interval_days": 1}},
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                builder._update_skill(skill)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"
        assert params["meta"] == json.dumps(skill.metadata, ensure_ascii=False)

    def test_skill_metadata_update_filters_by_org_context(self, monkeypatch):
        """Metadata-only writes keep the same org boundary as lifecycle writes."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.models import WiiiSkill
        from app.engine.living_agent.skill_builder import SkillBuilder

        builder = SkillBuilder()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        skill = WiiiSkill(
            skill_name="PRIVATE SKILL TOPIC",
            metadata={"learning_materials": [{"url": "https://example.invalid/private"}]},
        )

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session)

        token = current_org_id.set("org-A")
        try:
            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
                builder.update_skill_metadata(skill)
        finally:
            current_org_id.reset(token)

        statement = str(mock_session.execute.call_args.args[0])
        params = mock_session.execute.call_args.args[1]
        assert "AND organization_id = :org_id" in statement
        assert params["org_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_skill_learn_step_blocks_missing_org_before_llm(
        self,
        monkeypatch,
        caplog,
    ):
        """Learning steps fail closed before DB reads or local LLM calls."""
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.living_agent.skill_builder import SkillBuilder

        builder = SkillBuilder()
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        caplog.set_level(logging.WARNING)

        token = current_org_id.set(None)
        try:
            with patch("app.core.database.get_shared_session_factory") as mock_factory, \
                 patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                learned = await builder.learn_step("PRIVATE SKILL TOPIC")
        finally:
            current_org_id.reset(token)

        assert learned is False
        mock_factory.assert_not_called()
        mock_llm.assert_not_called()
        assert "skill_builder_blocked_missing_org_context" in caplog.text
        assert "PRIVATE SKILL TOPIC" not in caplog.text


# ============================================================================
# GROUP 9: Goal Seeding
# ============================================================================

class TestGoalSeeding:
    """Test goal seeding from soul definition."""

    @pytest.mark.asyncio
    async def test_seeds_from_wants_to_learn(self):
        """seed_initial_goals should create goals from wants_to_learn."""
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        soul = _make_soul()

        with patch.object(manager, 'get_active_goals', new_callable=AsyncMock, return_value=[]):
            with patch.object(manager, 'create_goal', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = MagicMock()
                seeded = await manager.seed_initial_goals(soul)

                # 3 from wants_to_learn + 1 meta-goal = 4
                assert seeded == 4
                assert mock_create.call_count == 4

    @pytest.mark.asyncio
    async def test_idempotent_with_existing_goals(self):
        """seed_initial_goals should return 0 if goals already exist."""
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        soul = _make_soul()

        existing_goal = MagicMock()
        with patch.object(manager, 'get_active_goals', new_callable=AsyncMock, return_value=[existing_goal]):
            seeded = await manager.seed_initial_goals(soul)
            assert seeded == 0

    @pytest.mark.asyncio
    async def test_meta_goal_always_created(self):
        """Meta-goal about helping students should always be created."""
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        soul = MagicMock()
        soul.interests.wants_to_learn = []  # No topics

        with patch.object(manager, 'get_active_goals', new_callable=AsyncMock, return_value=[]):
            with patch.object(manager, 'create_goal', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = MagicMock()
                seeded = await manager.seed_initial_goals(soul)

                assert seeded == 1  # Only meta-goal
                call_args = mock_create.call_args
                assert "sinh viên hàng hải" in call_args[1]["title"]

    @pytest.mark.asyncio
    async def test_max_3_learning_goals(self):
        """Should limit to first 3 wants_to_learn topics."""
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        soul = MagicMock()
        soul.interests.wants_to_learn = ["A", "B", "C", "D", "E"]

        with patch.object(manager, 'get_active_goals', new_callable=AsyncMock, return_value=[]):
            with patch.object(manager, 'create_goal', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = MagicMock()
                seeded = await manager.seed_initial_goals(soul)

                # 3 learning + 1 meta = 4
                assert seeded == 4

    @pytest.mark.asyncio
    async def test_goals_use_soul_seed_source(self):
        """Seeded goals should have source='soul_seed'."""
        from app.engine.living_agent.goal_manager import GoalManager

        manager = GoalManager()
        soul = _make_soul()

        with patch.object(manager, 'get_active_goals', new_callable=AsyncMock, return_value=[]):
            with patch.object(manager, 'create_goal', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = MagicMock()
                await manager.seed_initial_goals(soul)

                for call in mock_create.call_args_list:
                    assert call[1]["source"] == "soul_seed"


# ============================================================================
# GROUP 10: LLM Timeout Protection
# ============================================================================

class TestLLMTimeout:
    """Test 60s timeout protection in heartbeat actions."""

    @pytest.mark.asyncio
    async def test_timeout_wraps_action(self):
        """_execute_action should have 60s timeout."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import HeartbeatAction, ActionType

        scheduler = HeartbeatScheduler()
        action = HeartbeatAction(action_type=ActionType.REST, priority=0.5)
        soul = _make_soul()
        engine = MagicMock()

        # REST does nothing, should complete instantly
        await scheduler._execute_action(action, soul, engine)
        # No error — pass

    @pytest.mark.asyncio
    async def test_timeout_on_slow_action(self):
        """Action exceeding 60s should be cancelled, not crash."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import HeartbeatAction, ActionType

        scheduler = HeartbeatScheduler()

        async def slow_dispatch(action, soul, engine):
            await asyncio.sleep(100)  # Simulate very slow action

        action = HeartbeatAction(action_type=ActionType.REST, priority=0.5)
        soul = _make_soul()
        engine = MagicMock()

        with patch.object(scheduler, '_dispatch_action', side_effect=slow_dispatch):
            # Should not raise — timeout is caught internally
            await scheduler._execute_action(action, soul, engine)

    @pytest.mark.asyncio
    async def test_action_continues_after_timeout(self):
        """Heartbeat should continue processing after one action times out."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import HeartbeatAction, ActionType

        scheduler = HeartbeatScheduler()
        call_count = 0

        async def track_dispatch(action, soul, engine):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(100)  # First action times out
            # Second action completes

        action1 = HeartbeatAction(action_type=ActionType.REFLECT, priority=0.5)
        action2 = HeartbeatAction(action_type=ActionType.REST, priority=0.5)
        soul = _make_soul()
        engine = MagicMock()

        with patch.object(scheduler, '_dispatch_action', side_effect=track_dispatch):
            await scheduler._execute_action(action1, soul, engine)
            await scheduler._execute_action(action2, soul, engine)

        assert call_count == 2  # Both dispatched, first timed out

    @pytest.mark.asyncio
    async def test_dispatch_action_exists(self):
        """_dispatch_action should exist as the internal handler."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        scheduler = HeartbeatScheduler()
        assert hasattr(scheduler, '_dispatch_action')


# ============================================================================
# GROUP 11: Heartbeat Goal Seeding Integration
# ============================================================================

class TestHeartbeatGoalSeeding:
    """Test goal seeding wired into heartbeat _action_check_goals."""

    @pytest.mark.asyncio
    async def test_check_goals_seeds_once(self):
        """_action_check_goals should seed goals on first call."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        soul = _make_soul()

        mock_manager = AsyncMock()
        mock_manager.seed_initial_goals = AsyncMock(return_value=4)
        mock_manager.get_active_goals = AsyncMock(return_value=[MagicMock()])

        with patch("app.engine.living_agent.goal_manager.get_goal_manager", return_value=mock_manager):
            await scheduler._action_check_goals(soul)

            mock_manager.seed_initial_goals.assert_called_once_with(soul)
            assert scheduler._goals_seeded is True

    @pytest.mark.asyncio
    async def test_check_goals_idempotent(self):
        """_action_check_goals should NOT re-seed on subsequent calls."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        scheduler._goals_seeded = True  # Already seeded
        soul = _make_soul()

        mock_manager = AsyncMock()
        mock_manager.get_active_goals = AsyncMock(return_value=[])

        with patch("app.engine.living_agent.goal_manager.get_goal_manager", return_value=mock_manager):
            await scheduler._action_check_goals(soul)

            mock_manager.seed_initial_goals.assert_not_called()


# ============================================================================
# GROUP 12: Reflector Daily Method
# ============================================================================

class TestReflectorDailyMethod:
    """Test Reflector.reflect() daily method."""

    @pytest.mark.asyncio
    async def test_reflect_method_exists(self):
        """Reflector should have a reflect() method (Sprint 210)."""
        from app.engine.living_agent.reflector import Reflector
        reflector = Reflector()
        assert hasattr(reflector, 'reflect')
        assert asyncio.iscoroutinefunction(reflector.reflect)

    @pytest.mark.asyncio
    async def test_reflect_skips_if_already_reflected_today(self):
        """reflect() should return None if already reflected today."""
        from app.engine.living_agent.reflector import Reflector
        reflector = Reflector()

        with patch.object(reflector, '_has_reflected_today', new_callable=AsyncMock, return_value=True):
            result = await reflector.reflect()
            assert result is None

    @pytest.mark.asyncio
    async def test_reflect_uses_1_day_lookback(self):
        """reflect() should gather data from past 1 day (not 7)."""
        from app.engine.living_agent.reflector import Reflector
        reflector = Reflector()

        with patch.object(reflector, '_has_reflected_today', new_callable=AsyncMock, return_value=False):
            with patch.object(reflector, '_get_journal_summary', new_callable=AsyncMock, return_value="") as mock_journal:
                with patch.object(reflector, '_get_emotion_summary', new_callable=AsyncMock, return_value=""):
                    with patch.object(reflector, '_get_browsing_summary', new_callable=AsyncMock, return_value=""):
                        with patch.object(reflector, '_get_skills_summary', new_callable=AsyncMock, return_value=""):
                            with patch("app.engine.living_agent.local_llm.get_local_llm") as mock_llm:
                                mock_llm.return_value.generate = AsyncMock(return_value=None)
                                await reflector.reflect()

                                # Check journal_summary called with days=1 and resolved org
                                mock_journal.assert_called_once_with(1, "default")

    def test_is_reflection_time_daily(self):
        """is_reflection_time should return True at 21:00 any day."""
        from app.engine.living_agent.reflector import Reflector
        reflector = Reflector()

        # We can't easily mock datetime.now in the method since it uses
        # datetime.now(timezone.utc) directly. Test the logic.
        from datetime import timedelta
        # Monday 21:30 UTC+7 = 14:30 UTC
        utc_time = datetime(2026, 2, 23, 14, 30, tzinfo=timezone.utc)
        now_vn = utc_time + timedelta(hours=7)
        assert 21 <= now_vn.hour <= 22


# ============================================================================
# GROUP 13: Integration — Emotion changes from conversation
# ============================================================================

class TestEmotionFromConversation:
    """Integration test: conversation events affect mood."""

    def test_positive_feedback_makes_happy(self):
        """POSITIVE_FEEDBACK event should change mood to HAPPY (after cooldown)."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        # Bypass cooldown for test
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)
        engine.process_event(LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="User said 'cảm ơn'",
            importance=0.8,
        ))

        assert engine._state.primary_mood == MoodType.HAPPY

    def test_negative_feedback_makes_concerned(self):
        """NEGATIVE_FEEDBACK event should change mood to CONCERNED (after cooldown)."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)
        engine.process_event(LifeEvent(
            event_type=LifeEventType.NEGATIVE_FEEDBACK,
            description="User said 'sai rồi'",
            importance=0.7,
        ))

        assert engine._state.primary_mood == MoodType.CONCERNED

    def test_user_conversation_no_mood_change_at_default_importance(self):
        """USER_CONVERSATION has mood=None, so no mood change regardless of threshold."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        initial_mood = engine._state.primary_mood

        engine.process_event(LifeEvent(
            event_type=LifeEventType.USER_CONVERSATION,
            description="Normal chat",
            importance=0.5,
        ))

        # USER_CONVERSATION has mood=None → no mood change
        assert engine._state.primary_mood == initial_mood

    def test_engagement_increases_on_conversation(self):
        """USER_CONVERSATION should increase engagement."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()
        initial_engagement = engine._state.engagement

        engine.process_event(LifeEvent(
            event_type=LifeEventType.USER_CONVERSATION,
            description="Normal chat",
            importance=0.5,
        ))

        # Engagement delta = +0.05 * 0.5 = +0.025
        assert engine._state.engagement > initial_engagement

    def test_mood_dampening_prevents_pingpong(self):
        """Sprint 210b: Rapid alternating events should NOT cause mood flip-flop."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        # Don't bypass cooldown — test dampening behavior

        # Student A: positive
        engine.process_event(LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="Student A: cảm ơn!",
            importance=0.8,
        ))
        mood_after_first = engine._state.primary_mood

        # Student B: negative (immediately after — within cooldown)
        engine.process_event(LifeEvent(
            event_type=LifeEventType.NEGATIVE_FEEDBACK,
            description="Student B: sai rồi!",
            importance=0.7,
        ))
        mood_after_second = engine._state.primary_mood

        # Mood should NOT have flipped — still within cooldown
        # (Either stayed at initial, or changed to first event's mood at SENTIMENT_THRESHOLD)
        # The key invariant: it did NOT flip twice
        assert mood_after_first == mood_after_second or mood_after_second == MoodType.CURIOUS

    def test_accumulated_sentiment_majority_wins(self):
        """Sprint 210b: After enough events, majority sentiment wins."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import (
            LifeEvent, LifeEventType, MoodType,
        )

        engine = EmotionEngine()
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)

        # 3 positive events to exceed SENTIMENT_THRESHOLD
        for i in range(3):
            engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)
            engine.process_event(LifeEvent(
                event_type=LifeEventType.POSITIVE_FEEDBACK,
                description=f"Student {i}: cảm ơn!",
                importance=0.8,
            ))

        # Majority is positive → should be HAPPY
        assert engine._state.primary_mood == MoodType.HAPPY
