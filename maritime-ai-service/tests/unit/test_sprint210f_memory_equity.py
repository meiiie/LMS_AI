"""
Sprint 210f: "Ký Ức Công Bằng" — Memory Equity for All Users.

Fixes critical gap: TIER_OTHER users got ZERO episodic memories.
Now all users get episodes (with tier-based importance thresholds).

Also fixes: TIER_KNOWN users only had bucket counts, no emotion events.
Now TIER_KNOWN users get real emotion events with 0.6× importance.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call
from uuid import uuid4

# Patch targets — these are imported INSIDE _analyze_and_process_sentiment
_PATCH_ANALYZER = "app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer"
_PATCH_ENGINE = "app.engine.living_agent.emotion_engine.get_emotion_engine"
_PATCH_TIER = "app.engine.living_agent.emotion_engine.get_relationship_tier"
_PATCH_DB = "app.core.database.get_shared_session_factory"


def _mock_result(importance=0.5, sentiment="neutral", episode=None, event_type="USER_CONVERSATION"):
    """Helper to create a mock SentimentResult."""
    r = MagicMock()
    r.life_event_type = event_type
    r.episode_summary = episode
    r.importance = importance
    r.user_sentiment = sentiment
    return r


def _mock_db_session():
    """Helper to create mock DB session factory."""
    factory = MagicMock()
    session = MagicMock()
    factory.return_value.__enter__ = MagicMock(return_value=session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory, session


# ============================================================================
# GROUP 1: Episodic memory now stored for ALL tiers
# ============================================================================


class TestEpisodicMemoryAllTiers:
    """Verify episodes are created for Creator, Known, AND Other users."""

    @pytest.mark.asyncio
    async def test_tier_creator_always_stores_episode(self):
        """TIER_CREATOR always creates an episode regardless of importance."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.3))
        factory, session = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=0), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("admin", "admin", "What is Rule 5?", "Rule 5 is...")

        session.execute.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_tier_known_stores_episode_at_04_importance(self):
        """TIER_KNOWN creates episodes when importance >= 0.4 (lowered from 0.6)."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.45))
        factory, session = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("known-user", "student", "Tell me about SOLAS", "SOLAS is...")

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tier_known_skips_episode_below_04(self):
        """TIER_KNOWN does NOT create episode when importance < 0.4."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.3))

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB) as mock_db:
            await _analyze_and_process_sentiment("known-user", "student", "hello", "Xin chào!")

        # DB factory should NOT be called (no episode to store)
        mock_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier_other_stores_episode_at_05_importance(self):
        """TIER_OTHER (anonymous users) creates episodes when importance >= 0.5.

        THIS WAS THE CRITICAL BUG: TIER_OTHER previously got ZERO episodes.
        """
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.55))
        factory, session = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=2), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("anon-12345", "student", "Explain Rule 13", "Rule 13...")

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tier_other_skips_episode_below_05(self):
        """TIER_OTHER does NOT create episode when importance < 0.5."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.4))

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=2), \
             patch(_PATCH_DB) as mock_db:
            await _analyze_and_process_sentiment("anon-12345", "student", "hello", "Xin chào!")

        mock_db.assert_not_called()


# ============================================================================
# GROUP 2: TIER_KNOWN gets real emotion events (not just bucket counts)
# ============================================================================


class TestKnownUserEmotionEvents:
    """TIER_KNOWN now gets LifeEvent with 0.6× importance (not just bucket)."""

    @pytest.mark.asyncio
    async def test_tier_known_gets_process_event(self):
        """TIER_KNOWN users get engine.process_event() instead of record_interaction()."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.7, sentiment="positive"))
        mock_engine = MagicMock()
        factory, _ = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("known-student", "student", "Tell me about MARPOL", "MARPOL...")

        mock_engine.process_event.assert_called_once()
        mock_engine.record_interaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier_known_importance_reduced_by_06(self):
        """TIER_KNOWN events have importance × 0.6 to avoid overwhelming mood."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.8, sentiment="grateful"))
        mock_engine = MagicMock()
        factory, _ = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("known-student", "student", "Cảm ơn!", "Rất vui!")

        event = mock_engine.process_event.call_args[0][0]
        assert abs(event.importance - 0.48) < 0.01  # 0.8 * 0.6 = 0.48

    @pytest.mark.asyncio
    async def test_tier_other_still_uses_bucket(self):
        """TIER_OTHER users still use record_interaction (bucket count)."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.3, sentiment="neutral"))
        mock_engine = MagicMock()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=2):
            await _analyze_and_process_sentiment("anon-xyz", "student", "Hello", "Xin chào!")

        mock_engine.record_interaction.assert_called_once_with("anon-xyz", "neutral")
        mock_engine.process_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_tier_creator_full_importance(self):
        """TIER_CREATOR events have full importance (no reduction)."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.9, sentiment="grateful", event_type="POSITIVE_FEEDBACK"))
        mock_engine = MagicMock()
        factory, _ = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=0), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("admin", "admin", "Giỏi lắm!", "Cảm ơn!")

        event = mock_engine.process_event.call_args[0][0]
        assert event.importance == 0.9  # No reduction


# ============================================================================
# GROUP 3: Edge cases and error resilience
# ============================================================================


class TestMemoryEquityEdgeCases:
    """Edge cases for tier-based episode creation."""

    @pytest.mark.asyncio
    async def test_episode_boundary_tier_known_exactly_04(self):
        """TIER_KNOWN at exactly 0.4 importance STORES episode (>=, not >)."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.4))
        factory, session = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("known-user", "student", "test", "response")

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_episode_boundary_tier_other_exactly_05(self):
        """TIER_OTHER at exactly 0.5 importance STORES episode (>=, not >)."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.5))
        factory, session = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=MagicMock()), \
             patch(_PATCH_TIER, return_value=2), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("anon-boundary", "student", "test", "response")

        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_crash(self):
        """If episode DB insert fails, function continues gracefully."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.9))
        mock_engine = MagicMock()

        factory = MagicMock()
        factory.return_value.__enter__ = MagicMock(side_effect=Exception("DB connection lost"))
        factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=0), \
             patch(_PATCH_DB, return_value=factory):
            # Should NOT raise
            await _analyze_and_process_sentiment("admin", "admin", "test crash", "response")

        # Emotion event still fired (before DB)
        mock_engine.process_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_sentiment_analyzer_failure_swallowed(self):
        """If sentiment analyzer fails, entire function swallows error."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(side_effect=RuntimeError("LLM down"))

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer):
            # Should NOT raise
            await _analyze_and_process_sentiment("user1", "student", "test", "response")


# ============================================================================
# GROUP 4: Code inspection — verify tier logic in source
# ============================================================================




# ============================================================================
# GROUP 5: Regression — existing tier behaviors unchanged
# ============================================================================


class TestTierRegressions:
    """Ensure existing behaviors for Creator and bucket counts still work."""

    @pytest.mark.asyncio
    async def test_creator_event_description_includes_creator_prefix(self):
        """TIER_CREATOR events have 'Creator' prefix in description."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.5, episode=None))
        mock_engine = MagicMock()
        factory, _ = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=0), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("admin", "admin", "Test message", "Response")

        event = mock_engine.process_event.call_args[0][0]
        assert "Creator" in event.description

    @pytest.mark.asyncio
    async def test_known_event_description_includes_user_prefix(self):
        """TIER_KNOWN events have 'User' prefix (not 'Creator')."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.5, episode=None))
        mock_engine = MagicMock()
        factory, _ = _mock_db_session()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=1), \
             patch(_PATCH_DB, return_value=factory):
            await _analyze_and_process_sentiment("known-student", "student", "Test", "Response")

        event = mock_engine.process_event.call_args[0][0]
        assert "User" in event.description
        assert "Creator" not in event.description

    @pytest.mark.asyncio
    async def test_other_positive_sentiment_bucket(self):
        """TIER_OTHER positive sentiment → 'positive' bucket."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.3, sentiment="grateful"))
        mock_engine = MagicMock()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=2):
            await _analyze_and_process_sentiment("anon-123", "student", "Thanks!", "Welcome!")

        mock_engine.record_interaction.assert_called_once_with("anon-123", "positive")

    @pytest.mark.asyncio
    async def test_other_negative_sentiment_bucket(self):
        """TIER_OTHER negative sentiment → 'negative' bucket."""
        from app.services.chat_orchestrator import _analyze_and_process_sentiment

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_mock_result(importance=0.3, sentiment="frustrated"))
        mock_engine = MagicMock()

        with patch(_PATCH_ANALYZER, return_value=mock_analyzer), \
             patch(_PATCH_ENGINE, return_value=mock_engine), \
             patch(_PATCH_TIER, return_value=2):
            await _analyze_and_process_sentiment("anon-123", "student", "Wrong", "Let me correct...")

        mock_engine.record_interaction.assert_called_once_with("anon-123", "negative")
