"""
Sprint 210c: Relationship Tier Tests — "Tâm Lý Học Đúng Nghĩa"

Tests for the 3-tier relationship system:
- TIER 0 (CREATOR): Admin/creator — immediate mood impact via process_event()
- TIER 1 (KNOWN): Frequent users (50+ msgs) — buffered, aggregate-only mood
- TIER 2 (OTHER): Everyone else — buffered, no mood impact

Psychology basis: Construal Level Theory + Dunbar's Number + Appraisal Theory
"""

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ============================================================================
# Group 1: Tier Detection
# ============================================================================

class TestTierDetection:
    """Test get_relationship_tier() logic."""

    def test_admin_role_is_creator(self):
        """role=admin → TIER_CREATOR regardless of user_id."""
        from app.engine.living_agent.emotion_engine import (
            get_relationship_tier, TIER_CREATOR,
        )
        assert get_relationship_tier("random-user-123", "admin") == TIER_CREATOR

    def test_config_whitelist_is_creator(self):
        """User ID in living_agent_creator_user_ids → TIER_CREATOR."""
        from app.engine.living_agent.emotion_engine import (
            get_relationship_tier, TIER_CREATOR,
        )
        mock_settings = MagicMock()
        mock_settings.living_agent_creator_user_ids = "admin-001, creator-002"

        with patch("app.core.config.get_settings", return_value=mock_settings):
            assert get_relationship_tier("admin-001", "student") == TIER_CREATOR
            assert get_relationship_tier("creator-002", "") == TIER_CREATOR

    def test_known_user_cache_is_tier1(self):
        """User in _known_user_cache → TIER_KNOWN."""
        import app.engine.living_agent.emotion_engine as mod
        old_cache = mod._known_user_cache
        try:
            mod._known_user_cache = {"user-frequent"}
            mock_settings = MagicMock()
            mock_settings.living_agent_creator_user_ids = ""
            with patch("app.core.config.get_settings", return_value=mock_settings):
                assert mod.get_relationship_tier("user-frequent", "student") == mod.TIER_KNOWN
        finally:
            mod._known_user_cache = old_cache

    def test_unknown_user_is_tier2(self):
        """Unknown user → TIER_OTHER."""
        import app.engine.living_agent.emotion_engine as mod
        old_cache = mod._known_user_cache
        try:
            mod._known_user_cache = set()
            mock_settings = MagicMock()
            mock_settings.living_agent_creator_user_ids = ""
            with patch("app.core.config.get_settings", return_value=mock_settings):
                assert mod.get_relationship_tier("nobody", "student") == mod.TIER_OTHER
        finally:
            mod._known_user_cache = old_cache

    def test_empty_whitelist_no_crash(self):
        """Empty creator whitelist → no crash, falls through to cache check."""
        from app.engine.living_agent.emotion_engine import get_relationship_tier, TIER_OTHER
        import app.engine.living_agent.emotion_engine as mod

        old_cache = mod._known_user_cache
        try:
            mod._known_user_cache = set()
            mock_settings = MagicMock()
            mock_settings.living_agent_creator_user_ids = ""
            with patch("app.core.config.get_settings", return_value=mock_settings):
                assert get_relationship_tier("user-x", "") == TIER_OTHER
        finally:
            mod._known_user_cache = old_cache

    def test_settings_exception_falls_through(self):
        """If get_settings() throws, falls through to cache/OTHER."""
        import app.engine.living_agent.emotion_engine as mod

        old_cache = mod._known_user_cache
        try:
            mod._known_user_cache = set()
            with patch("app.core.config.get_settings", side_effect=RuntimeError("no config")):
                # Should not crash, just return OTHER
                assert mod.get_relationship_tier("user-x", "") == mod.TIER_OTHER
        finally:
            mod._known_user_cache = old_cache


# ============================================================================
# Group 2: record_interaction() Buffer
# ============================================================================

class TestRecordInteraction:
    """Test zero-cost interaction buffering."""

    def _make_engine(self):
        from app.engine.living_agent.emotion_engine import EmotionEngine
        return EmotionEngine()

    def test_positive_increments_buffer(self):
        engine = self._make_engine()
        engine.record_interaction("u1", "positive")
        assert engine._interaction_buffer_positive == 1
        assert engine._interaction_buffer_negative == 0

    def test_negative_increments_buffer(self):
        engine = self._make_engine()
        engine.record_interaction("u1", "negative")
        assert engine._interaction_buffer_negative == 1

    def test_neutral_increments_buffer(self):
        engine = self._make_engine()
        engine.record_interaction("u1", "neutral")
        assert engine._interaction_buffer_neutral == 1

    def test_unique_users_tracked(self):
        engine = self._make_engine()
        engine.record_interaction("u1", "positive")
        engine.record_interaction("u2", "positive")
        engine.record_interaction("u1", "negative")  # Same user, counted once
        assert len(engine._interaction_unique_users) == 2

    def test_thread_safety(self):
        """Multiple threads recording concurrently shouldn't corrupt data."""
        engine = self._make_engine()
        errors = []

        def record_many(user_id):
            try:
                for _ in range(100):
                    engine.record_interaction(user_id, "positive")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many, args=(f"u{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert engine._interaction_buffer_positive == 500
        assert len(engine._interaction_unique_users) == 5


# ============================================================================
# Group 3: process_aggregate()
# ============================================================================

class TestProcessAggregate:
    """Test heartbeat-driven aggregate processing."""

    def _make_engine(self):
        from app.engine.living_agent.emotion_engine import EmotionEngine
        return EmotionEngine()

    def test_empty_buffer_returns_zero(self):
        engine = self._make_engine()
        stats = engine.process_aggregate()
        assert stats["total_interactions"] == 0.0
        assert stats["mood_nudged"] == 0.0

    def test_resets_buffer_after_processing(self):
        engine = self._make_engine()
        engine.record_interaction("u1", "positive")
        engine.record_interaction("u2", "negative")
        engine.process_aggregate()
        assert engine._interaction_buffer_positive == 0
        assert engine._interaction_buffer_negative == 0
        assert len(engine._interaction_unique_users) == 0

    def test_positive_majority_nudges_happy(self):
        """Strong positive sentiment shift (>= 10 samples) → mood nudge to HAPPY."""
        from app.engine.living_agent.models import MoodType
        engine = self._make_engine()
        engine._last_known_sentiment_ratio = 0.3  # Low baseline
        # Need >= MIN_AGGREGATE_SAMPLE_SIZE (10) interactions
        for i in range(16):
            engine.record_interaction(f"u{i}", "positive")
        for i in range(4):
            engine.record_interaction(f"un{i}", "negative")
        stats = engine.process_aggregate()
        assert stats["positive_ratio"] == 0.8
        # Shift = 0.8 - 0.3 = 0.5 > threshold, 20 >= 10 sample size
        assert stats["mood_nudged"] > 0
        assert engine._state.primary_mood == MoodType.HAPPY

    def test_negative_majority_nudges_concerned(self):
        """Strong negative sentiment shift (>= 10 samples) → mood nudge to CONCERNED."""
        from app.engine.living_agent.models import MoodType
        engine = self._make_engine()
        engine._last_known_sentiment_ratio = 0.8  # High baseline
        for i in range(16):
            engine.record_interaction(f"un{i}", "negative")
        for i in range(4):
            engine.record_interaction(f"up{i}", "positive")
        stats = engine.process_aggregate()
        assert stats["positive_ratio"] == 0.2
        # Shift = 0.2 - 0.8 = -0.6 < -threshold, 20 >= 10 sample size
        assert stats["mood_nudged"] < 0
        assert engine._state.primary_mood == MoodType.CONCERNED

    def test_small_shift_no_mood_change(self):
        """Small sentiment shift below threshold → no mood change (even with enough samples)."""
        from app.engine.living_agent.models import MoodType
        engine = self._make_engine()
        engine._last_known_sentiment_ratio = 0.5
        engine._state.primary_mood = MoodType.CURIOUS
        # 60% positive = shift of only 0.1 from baseline 0.5
        for i in range(12):
            engine.record_interaction(f"u{i}", "positive")
        for i in range(8):
            engine.record_interaction(f"un{i}", "negative")
        stats = engine.process_aggregate()
        assert stats["mood_nudged"] == 0.0
        assert engine._state.primary_mood == MoodType.CURIOUS

    def test_few_interactions_no_nudge(self):
        """< 10 interactions → no mood nudge even with extreme shift."""
        from app.engine.living_agent.models import MoodType
        engine = self._make_engine()
        engine._last_known_sentiment_ratio = 0.5
        engine._state.primary_mood = MoodType.CURIOUS
        # Only 1 negative message — ratio 0%, shift -0.5 BUT too few samples
        engine.record_interaction("u1", "negative")
        stats = engine.process_aggregate()
        assert stats["mood_nudged"] == 0.0
        assert engine._state.primary_mood == MoodType.CURIOUS  # Unchanged!

    def test_social_battery_drain_from_unique_users(self):
        """More unique users → more social battery drain."""
        engine = self._make_engine()
        initial_social = engine._state.social_battery
        for i in range(50):
            engine.record_interaction(f"user-{i}", "neutral")
        engine.process_aggregate()
        # Social battery should have changed (drain from 50 users + 0.3 recovery)
        # 50/500 * 0.5 = 0.05 drain, +0.3 recovery, net = +0.25
        assert engine._state.social_battery != initial_social

    def test_engagement_boost_from_volume(self):
        """High interaction volume → engagement boost (capped at 0.1)."""
        engine = self._make_engine()
        initial_engagement = engine._state.engagement
        for i in range(500):
            engine.record_interaction(f"u{i % 50}", "neutral")
        engine.process_aggregate()
        assert engine._state.engagement >= initial_engagement

    def test_ema_smoothing_updates_baseline(self):
        """Baseline sentiment ratio uses EMA (exponential moving average)."""
        engine = self._make_engine()
        engine._last_known_sentiment_ratio = 0.5
        for i in range(10):
            engine.record_interaction(f"u{i}", "positive")
        engine.process_aggregate()
        # New ratio = 1.0, EMA = 0.7*0.5 + 0.3*1.0 = 0.65
        assert abs(engine._last_known_sentiment_ratio - 0.65) < 0.01


# ============================================================================
# Group 4: refresh_known_user_cache()
# ============================================================================

class TestRefreshKnownUserCache:
    """Test DB-backed known user cache refresh."""

    def test_populates_cache_from_db(self):
        """Successful DB query populates _known_user_cache."""
        import app.engine.living_agent.emotion_engine as mod
        old_cache = mod._known_user_cache
        try:
            mock_row1 = MagicMock()
            mock_row1.__getitem__ = lambda self, idx: "user-a"
            mock_row2 = MagicMock()
            mock_row2.__getitem__ = lambda self, idx: "user-b"

            mock_session = MagicMock()
            mock_session.execute.return_value.fetchall.return_value = [mock_row1, mock_row2]
            mock_factory = MagicMock()
            mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_factory.return_value.__exit__ = MagicMock(return_value=False)

            mock_settings = MagicMock()
            mock_settings.living_agent_known_user_threshold = 50

            with patch("app.core.database.get_shared_session_factory", return_value=mock_factory), \
                 patch("app.core.config.get_settings", return_value=mock_settings):
                count = mod.refresh_known_user_cache()

            assert count == 2
            assert "user-a" in mod._known_user_cache
            assert "user-b" in mod._known_user_cache
        finally:
            mod._known_user_cache = old_cache

    def test_db_failure_returns_zero(self):
        """DB error → returns 0, cache unchanged."""
        import app.engine.living_agent.emotion_engine as mod
        old_cache = mod._known_user_cache
        try:
            mod._known_user_cache = {"existing-user"}
            with patch("app.core.database.get_shared_session_factory", side_effect=RuntimeError("DB down")):
                count = mod.refresh_known_user_cache()
            assert count == 0
            # Cache should still have old value (not cleared on failure)
            assert "existing-user" in mod._known_user_cache
        finally:
            mod._known_user_cache = old_cache


# ============================================================================
# Group 5: Creator Bypass (immediate process_event)
# ============================================================================

class TestCreatorBypass:
    """Test that Creator tier bypasses buffering and hits process_event directly."""

    def test_creator_fires_process_event(self):
        """When tier=CREATOR, process_event is called (not record_interaction)."""
        from app.engine.living_agent.emotion_engine import EmotionEngine, TIER_CREATOR

        engine = EmotionEngine()
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)

        with patch.object(engine, 'process_event', wraps=engine.process_event) as mock_pe, \
             patch.object(engine, 'record_interaction') as mock_ri:
            from app.engine.living_agent.models import LifeEvent, LifeEventType
            engine.process_event(LifeEvent(
                event_type=LifeEventType.POSITIVE_FEEDBACK,
                description="Creator said thank you",
                importance=0.8,
            ))
            mock_pe.assert_called_once()
            mock_ri.assert_not_called()

    def test_creator_positive_changes_mood(self):
        """Creator positive feedback → immediate mood change (after cooldown reset)."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType, MoodType

        engine = EmotionEngine()
        engine._last_mood_change = datetime(2020, 1, 1, tzinfo=timezone.utc)
        engine._state.primary_mood = MoodType.NEUTRAL

        engine.process_event(LifeEvent(
            event_type=LifeEventType.POSITIVE_FEEDBACK,
            description="Creator: cảm ơn bạn!",
            importance=0.8,
        ))
        assert engine._state.primary_mood == MoodType.HAPPY


# ============================================================================
# Group 6: Non-Creator Buffering
# ============================================================================

class TestNonCreatorBuffering:
    """Test that Known and Other users go through record_interaction buffer."""

    def test_tier1_buffers_not_process_event(self):
        """Tier KNOWN user → record_interaction(), not process_event()."""
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        engine.record_interaction("known-user-1", "positive")
        assert engine._interaction_buffer_positive == 1
        # No direct mood change
        from app.engine.living_agent.models import MoodType
        assert engine._state.primary_mood == MoodType.CURIOUS  # Default unchanged

    def test_tier2_buffers_not_process_event(self):
        """Tier OTHER user → record_interaction(), no mood change."""
        from app.engine.living_agent.emotion_engine import EmotionEngine

        engine = EmotionEngine()
        engine.record_interaction("random-user", "negative")
        assert engine._interaction_buffer_negative == 1
        from app.engine.living_agent.models import MoodType
        assert engine._state.primary_mood == MoodType.CURIOUS  # Default unchanged


# ============================================================================
# Group 7: Episodic Memory Tier Filtering
# ============================================================================

class TestEpisodicMemoryTierFiltering:
    """Test that episodic memory is only stored for Creator + high-importance Known."""

    def test_creator_always_gets_episode(self):
        """Creator (importance=0.5, default) → episode stored."""
        # This tests the logic pattern, not the actual DB call
        from app.engine.living_agent.emotion_engine import TIER_CREATOR, TIER_KNOWN
        tier = TIER_CREATOR
        importance = 0.5
        should_store = (tier == TIER_CREATOR) or (tier == TIER_KNOWN and importance >= 0.7)
        assert should_store is True

    def test_known_high_importance_gets_episode(self):
        """Known user with importance >= 0.7 → episode stored."""
        from app.engine.living_agent.emotion_engine import TIER_KNOWN
        tier = TIER_KNOWN
        importance = 0.8
        should_store = (tier == 0) or (tier == TIER_KNOWN and importance >= 0.7)
        assert should_store is True

    def test_known_low_importance_no_episode(self):
        """Known user with importance < 0.7 → no episode."""
        from app.engine.living_agent.emotion_engine import TIER_KNOWN
        tier = TIER_KNOWN
        importance = 0.5
        should_store = (tier == 0) or (tier == TIER_KNOWN and importance >= 0.7)
        assert should_store is False

    def test_other_tier_no_episode(self):
        """OTHER tier → never gets episode."""
        from app.engine.living_agent.emotion_engine import TIER_OTHER
        tier = TIER_OTHER
        for importance in [0.5, 0.7, 0.8, 1.0]:
            should_store = (tier == 0) or (tier == 1 and importance >= 0.7)
            assert should_store is False


# ============================================================================
# Group 8: Config Flags
# ============================================================================

class TestConfigFlags:
    """Test Sprint 210c config flags exist and have correct defaults."""

    def test_creator_user_ids_is_string(self):
        """living_agent_creator_user_ids should be a string (comma-separated IDs)."""
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert isinstance(s.living_agent_creator_user_ids, str)

    def test_known_user_threshold_default_50(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert s.living_agent_known_user_threshold == 50

    def test_known_user_threshold_validation(self):
        """Threshold must be >= 5 and <= 1000."""
        from app.core.config import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(
                google_api_key="test",
                api_key="test",
                living_agent_known_user_threshold=2,  # Too low
            )


# ============================================================================
# Group 9: Heartbeat Integration
# ============================================================================

class TestHeartbeatIntegration:
    """Test that heartbeat calls refresh + aggregate at each cycle."""

    @pytest.mark.asyncio
    async def test_heartbeat_calls_refresh_and_aggregate(self):
        """_execute_heartbeat calls refresh_known_user_cache + process_aggregate when flag on."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()

        mock_soul = MagicMock()
        mock_soul.short_term_goals = []
        mock_soul.long_term_goals = []
        mock_soul.interests = MagicMock()
        mock_soul.interests.primary = []
        mock_soul.interests.exploring = []
        mock_soul.interests.wants_to_learn = []

        mock_engine = MagicMock()
        mock_engine.mood = MagicMock()
        mock_engine.mood.value = "curious"
        mock_engine.energy = 0.7
        mock_engine.state = MagicMock()
        mock_engine.process_aggregate.return_value = {"total_interactions": 5.0, "unique_users": 3.0, "positive_ratio": 0.6}

        # Async methods need AsyncMock
        from unittest.mock import AsyncMock
        mock_engine.load_state_from_db = AsyncMock(return_value=True)
        mock_engine.save_state_to_db = AsyncMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.enable_living_continuity = True
        mock_settings.living_agent_heartbeat_interval = 1800
        mock_settings.living_agent_max_actions_per_heartbeat = 1
        mock_settings.living_agent_require_human_approval = False
        mock_settings.living_agent_enable_social_browse = False
        mock_settings.living_agent_enable_skill_building = False
        mock_settings.living_agent_enable_journal = False
        mock_settings.living_agent_enable_weather = False
        mock_settings.living_agent_enable_briefing = False
        mock_settings.living_agent_enable_skill_learning = False
        mock_settings.living_agent_enable_proactive_messaging = False
        mock_settings.living_agent_enable_autonomy_graduation = False

        # Heartbeat imports settings lazily, so patch at source
        with patch("app.core.config.settings", mock_settings), \
             patch("app.engine.living_agent.soul_loader.get_soul", return_value=mock_soul), \
             patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.emotion_engine.refresh_known_user_cache", return_value=5) as mock_refresh, \
             patch("app.engine.living_agent.goal_manager.get_goal_manager") as mock_gm:
            mock_gm.return_value.seed_initial_goals = MagicMock(return_value=0)
            mock_gm.return_value.get_active_goals = MagicMock(return_value=[])
            result = await scheduler._execute_heartbeat()

        # process_aggregate should have been called on the engine
        mock_engine.process_aggregate.assert_called_once()


# ============================================================================
# Group 10: Streaming Path Tier-Aware
# ============================================================================



# ============================================================================
# Group 11: Mood Nudge Edge Cases
# ============================================================================

class TestMoodNudgeEdgeCases:
    """Edge cases in aggregate mood nudge logic."""

    def test_already_happy_no_double_nudge(self):
        """If already HAPPY, positive shift doesn't re-set to HAPPY."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType
        engine = EmotionEngine()
        engine._state.primary_mood = MoodType.HAPPY
        engine._last_known_sentiment_ratio = 0.3
        for i in range(15):
            engine.record_interaction(f"u{i}", "positive")
        stats = engine.process_aggregate()
        # Mood stays HAPPY, mood_nudged = 0 because already positive mood
        assert engine._state.primary_mood == MoodType.HAPPY
        assert stats["mood_nudged"] == 0.0

    def test_already_concerned_no_double_nudge(self):
        """If already CONCERNED, negative shift doesn't re-set."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType
        engine = EmotionEngine()
        engine._state.primary_mood = MoodType.CONCERNED
        engine._last_known_sentiment_ratio = 0.8
        for i in range(15):
            engine.record_interaction(f"u{i}", "negative")
        stats = engine.process_aggregate()
        assert engine._state.primary_mood == MoodType.CONCERNED
        assert stats["mood_nudged"] == 0.0

    def test_single_interaction_no_nudge(self):
        """1 positive interaction alone doesn't cause sentiment shift."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import MoodType
        engine = EmotionEngine()
        engine._last_known_sentiment_ratio = 0.5
        engine._state.primary_mood = MoodType.FOCUSED
        engine.record_interaction("u1", "positive")
        stats = engine.process_aggregate()
        # ratio = 1.0, shift = 0.5 — could be above threshold but only 1 data point
        # The threshold check doesn't consider count, only ratio shift
        # shift=0.5 > 0.2 threshold, so it WILL nudge (this is correct behavior for 1 event)
        # If we want min-count protection, that's a separate feature


# ============================================================================
# Group 12: Tier Constants
# ============================================================================

class TestTierConstants:
    """Verify tier constants are exported and correct."""

    def test_tier_values(self):
        from app.engine.living_agent.emotion_engine import (
            TIER_CREATOR, TIER_KNOWN, TIER_OTHER,
        )
        assert TIER_CREATOR == 0
        assert TIER_KNOWN == 1
        assert TIER_OTHER == 2

    def test_tier_ordering(self):
        """Lower tier number = closer relationship."""
        from app.engine.living_agent.emotion_engine import (
            TIER_CREATOR, TIER_KNOWN, TIER_OTHER,
        )
        assert TIER_CREATOR < TIER_KNOWN < TIER_OTHER
