"""
Sprint 210d: SOTA LLM-Based Sentiment Analysis Tests

Tests for the LLM-based sentiment analyzer that replaces keyword matching.
Validates the full pipeline: LLM analysis → emotion engine → episodic memory.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Group 1: SentimentResult Model
# ============================================================================

class TestSentimentResult:
    """Test the SentimentResult Pydantic model."""

    def test_default_values(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        r = SentimentResult()
        assert r.user_sentiment == "neutral"
        assert r.intensity == 0.3
        assert r.life_event_type == "USER_CONVERSATION"
        assert r.importance == 0.3
        assert r.episode_summary == ""

    def test_positive_result(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        r = SentimentResult(
            user_sentiment="grateful",
            intensity=0.8,
            life_event_type="POSITIVE_FEEDBACK",
            importance=0.7,
            episode_summary="User thanked Wiii warmly.",
        )
        assert r.user_sentiment == "grateful"
        assert r.importance == 0.7
        assert r.life_event_type == "POSITIVE_FEEDBACK"

    def test_negative_result(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        r = SentimentResult(
            user_sentiment="frustrated",
            intensity=0.6,
            life_event_type="NEGATIVE_FEEDBACK",
            importance=0.6,
            episode_summary="User was unhappy with the answer.",
        )
        assert r.user_sentiment == "frustrated"

    def test_intensity_clamped(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        # Should clamp to 0-1
        with pytest.raises(Exception):
            SentimentResult(intensity=1.5)

    def test_from_json(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        data = {
            "user_sentiment": "excited",
            "intensity": 0.9,
            "life_event_type": "POSITIVE_FEEDBACK",
            "importance": 0.8,
            "episode_summary": "Great conversation!",
        }
        r = SentimentResult(**data)
        assert r.user_sentiment == "excited"
        assert r.importance == 0.8


# ============================================================================
# Group 2: SentimentAnalyzer — LLM Path
# ============================================================================

class TestSentimentAnalyzerLLM:
    """Test the LLM-based analysis path."""

    @pytest.fixture
    def analyzer(self):
        from app.engine.living_agent.sentiment_analyzer import SentimentAnalyzer
        return SentimentAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_returns_sentiment_result(self, analyzer):
        """analyze() always returns a SentimentResult, even on failure."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult
        # Mock LLM to return a valid structured result
        mock_result = SentimentResult(
            user_sentiment="grateful",
            intensity=0.7,
            life_event_type="POSITIVE_FEEDBACK",
            importance=0.7,
            episode_summary="User thanked Wiii.",
        )
        mock_llm = MagicMock()

        with patch.object(analyzer, '_get_llm', return_value=mock_llm), \
             patch("app.services.structured_invoke_service.StructuredInvokeService.ainvoke", new=AsyncMock(return_value=mock_result)):
            result = await analyzer.analyze("cam on nhieu lam!", "Khong co gi!", "admin")

        assert isinstance(result, SentimentResult)
        assert result.user_sentiment == "grateful"
        assert result.importance == 0.7

    @pytest.mark.asyncio
    async def test_analyze_timeout_returns_default(self, analyzer):
        """If LLM takes too long, return safe default."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        async def slow_llm(*args, **kwargs):
            await asyncio.sleep(100)  # Way longer than timeout

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = slow_llm
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)

        analyzer._TIMEOUT_SECONDS = 0.1  # Very short timeout for test
        with patch.object(analyzer, '_get_llm', return_value=mock_llm):
            result = await analyzer.analyze("test", "response", "user1")

        assert isinstance(result, SentimentResult)
        assert result.user_sentiment == "neutral"  # Default

    @pytest.mark.asyncio
    async def test_analyze_exception_returns_default(self, analyzer):
        """If LLM throws, return safe default."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(side_effect=Exception("LLM down"))
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured)
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM down"))

        with patch.object(analyzer, '_get_llm', return_value=mock_llm):
            result = await analyzer.analyze("test", "response", "user1")

        assert isinstance(result, SentimentResult)
        assert result.user_sentiment == "neutral"

    @pytest.mark.asyncio
    async def test_analyze_no_llm_returns_default(self, analyzer):
        """If no LLM available, return safe default."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        with patch.object(analyzer, '_get_llm', return_value=None):
            result = await analyzer.analyze("test", "response", "user1")

        assert isinstance(result, SentimentResult)
        assert result.user_sentiment == "neutral"

    @pytest.mark.asyncio
    async def test_analyze_short_banter_skips_llm(self, analyzer):
        """Tiny banter should not spend an extra LLM call in the background."""
        with patch.object(analyzer, "_get_llm") as mock_get_llm:
            result = await analyzer.analyze("hẹ hẹ", "He he~", "user1")

        assert result.user_sentiment == "positive"
        assert result.importance == pytest.approx(0.08)
        mock_get_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_short_reaction_uses_fast_path(self, analyzer):
        """Short reactions should map to a lightweight heuristic sentiment result."""
        with patch.object(analyzer, "_get_llm") as mock_get_llm:
            result = await analyzer.analyze("wow", "Woa~", "user1")

        assert result.user_sentiment == "excited"
        assert result.importance == pytest.approx(0.1)
        mock_get_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_raw_json_fallback(self, analyzer):
        """If structured output fails, try raw JSON parsing."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        raw_json = json.dumps({
            "user_sentiment": "curious",
            "intensity": 0.4,
            "life_event_type": "HELP_REQUEST",
            "importance": 0.4,
            "episode_summary": "User asked about COLREG.",
        })

        mock_llm = MagicMock()
        # raw invoke returns JSON string
        mock_response = MagicMock()
        mock_response.content = raw_json
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch.object(analyzer, '_get_llm', return_value=mock_llm), \
             patch(
                 "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
                 new_callable=AsyncMock,
                 side_effect=Exception("no structured"),
             ):
            result = await analyzer.analyze("COLREG la gi?", "COLREG la...", "student")

        assert isinstance(result, SentimentResult)
        assert result.user_sentiment == "curious"
        assert result.life_event_type == "HELP_REQUEST"


# ============================================================================
# Group 3: Singleton
# ============================================================================

class TestSentimentSingleton:
    """Test singleton pattern."""

    def test_get_sentiment_analyzer_returns_same_instance(self):
        from app.engine.living_agent.sentiment_analyzer import (
            get_sentiment_analyzer, _instance,
        )
        import app.engine.living_agent.sentiment_analyzer as mod
        mod._instance = None  # Reset
        a1 = get_sentiment_analyzer()
        a2 = get_sentiment_analyzer()
        assert a1 is a2
        mod._instance = None  # Cleanup


# ============================================================================
# Group 4: Integration — Sentiment → EmotionEngine
# ============================================================================

class TestSentimentToEmotion:
    """Test the full pipeline: LLM sentiment → emotion engine update."""

    @pytest.mark.asyncio
    async def test_creator_positive_triggers_process_event(self):
        """Creator + positive sentiment → process_event with POSITIVE_FEEDBACK."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        mock_result = SentimentResult(
            user_sentiment="grateful",
            intensity=0.8,
            life_event_type="POSITIVE_FEEDBACK",
            importance=0.8,
            episode_summary="Creator praised Wiii.",
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        with patch("app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer", return_value=mock_analyzer), \
             patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.emotion_engine.get_relationship_tier", return_value=0), \
             patch("app.core.database.get_shared_session_factory"):
            from app.services.chat_orchestrator import _analyze_and_process_sentiment
            await _analyze_and_process_sentiment(
                user_id="admin",
                user_role="admin",
                message="Cam on ban!",
                response_text="Khong co gi!",
            )

        mock_engine.process_event.assert_called_once()
        event = mock_engine.process_event.call_args[0][0]
        assert event.importance == 0.8

    @pytest.mark.asyncio
    async def test_student_positive_buffers_not_process_event(self):
        """Non-creator + positive sentiment → record_interaction, NOT process_event."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        mock_result = SentimentResult(
            user_sentiment="grateful",
            intensity=0.7,
            life_event_type="POSITIVE_FEEDBACK",
            importance=0.7,
            episode_summary="Student said thanks.",
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        with patch("app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer", return_value=mock_analyzer), \
             patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.emotion_engine.get_relationship_tier", return_value=2), \
             patch("app.core.database.get_shared_session_factory"):
            from app.services.chat_orchestrator import _analyze_and_process_sentiment
            await _analyze_and_process_sentiment(
                user_id="student-123",
                user_role="student",
                message="Cam on!",
                response_text="Da!",
            )

        mock_engine.process_event.assert_not_called()
        mock_engine.record_interaction.assert_called_once_with("student-123", "positive")

    @pytest.mark.asyncio
    async def test_sentiment_bucket_mapping(self):
        """Verify sentiment → bucket mapping: grateful=positive, frustrated=negative, etc."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        test_cases = [
            ("positive", "positive"),
            ("grateful", "positive"),
            ("excited", "positive"),
            ("negative", "negative"),
            ("frustrated", "negative"),
            ("dismissive", "negative"),
            ("neutral", "neutral"),
            ("curious", "neutral"),
            ("confused", "neutral"),
        ]

        for sentiment, expected_bucket in test_cases:
            mock_result = SentimentResult(
                user_sentiment=sentiment,
                intensity=0.5,
                life_event_type="USER_CONVERSATION",
                importance=0.5,
            )
            mock_analyzer = MagicMock()
            mock_analyzer.analyze = AsyncMock(return_value=mock_result)
            mock_engine = MagicMock()

            with patch("app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer", return_value=mock_analyzer), \
                 patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
                 patch("app.engine.living_agent.emotion_engine.get_relationship_tier", return_value=2), \
                 patch("app.core.database.get_shared_session_factory"):
                from app.services.chat_orchestrator import _analyze_and_process_sentiment
                await _analyze_and_process_sentiment(
                    user_id="student", user_role="student",
                    message="test", response_text="test",
                )

            mock_engine.record_interaction.assert_called_once_with("student", expected_bucket)


# ============================================================================
# Group 5: Episodic Memory from LLM
# ============================================================================

class TestEpisodicMemoryLLM:
    """Test that episodic memories use LLM-generated summaries."""

    @pytest.mark.asyncio
    async def test_creator_episode_uses_llm_summary(self):
        """Creator's episodic memory should use the LLM episode_summary, not a template."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        mock_result = SentimentResult(
            user_sentiment="grateful",
            intensity=0.8,
            life_event_type="POSITIVE_FEEDBACK",
            importance=0.8,
            episode_summary="Admin praised Wiii for explaining COLREG clearly. Felt warm and proud.",
        )

        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_result)
        mock_engine = MagicMock()

        mock_session = MagicMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer", return_value=mock_analyzer), \
             patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.emotion_engine.get_relationship_tier", return_value=0), \
             patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
            from app.services.chat_orchestrator import _analyze_and_process_sentiment
            await _analyze_and_process_sentiment(
                user_id="admin", user_role="admin",
                message="COLREG rat de hieu!", response_text="Cam on ban!",
            )

        # Check that the episode content is the LLM summary, not a template
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]  # Second positional arg = params dict
        assert "COLREG" in params["content"]
        assert "proud" in params["content"]

    @pytest.mark.asyncio
    async def test_other_tier_no_episode_low_importance(self):
        """TIER_OTHER with low importance (0.3) skips episodic memory.
        Sprint 210f: TIER_OTHER CAN create episodes when importance >= 0.5."""
        from app.engine.living_agent.sentiment_analyzer import SentimentResult

        mock_result = SentimentResult(
            user_sentiment="neutral", intensity=0.3,
            life_event_type="USER_CONVERSATION", importance=0.3,
        )
        mock_analyzer = MagicMock()
        mock_analyzer.analyze = AsyncMock(return_value=mock_result)
        mock_engine = MagicMock()
        mock_factory = MagicMock()

        with patch("app.engine.living_agent.sentiment_analyzer.get_sentiment_analyzer", return_value=mock_analyzer), \
             patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.emotion_engine.get_relationship_tier", return_value=2), \
             patch("app.core.database.get_shared_session_factory", return_value=mock_factory):
            from app.services.chat_orchestrator import _analyze_and_process_sentiment
            await _analyze_and_process_sentiment(
                user_id="stranger", user_role="student",
                message="hello", response_text="hi",
            )

        # session_factory should NOT be called (no episode for TIER_OTHER)
        mock_factory.assert_not_called()


# ============================================================================
# Group 6: No Keywords in Production Code
# ============================================================================

class TestNoKeywords:
    """Verify keyword matching has been fully removed from production paths."""

    def test_chat_orchestrator_no_keywords(self):
        """chat_orchestrator.py should NOT contain keyword arrays."""
        import inspect
        from app.services import chat_orchestrator
        source = inspect.getsource(chat_orchestrator)
        assert '_pos = [' not in source
        assert '_neg = [' not in source
        assert '"sai rồi"' not in source
        assert '"cảm ơn"' not in source

    def test_chat_stream_no_keywords(self):
        """chat_stream.py should NOT contain keyword arrays."""
        import inspect
        from app.api.v1 import chat_stream
        source = inspect.getsource(chat_stream)
        assert '_pos = [' not in source
        assert '_neg = [' not in source
        assert '"sai rồi"' not in source
        assert '"cảm ơn"' not in source

    def test_orchestrator_uses_llm_sentiment(self):
        """chat_orchestrator.py should use _analyze_and_process_sentiment."""
        import inspect
        from app.services import chat_orchestrator
        source = inspect.getsource(chat_orchestrator)
        assert "_analyze_and_process_sentiment" in source
        assert "SentimentAnalyzer" in source or "get_sentiment_analyzer" in source

    def test_stream_uses_llm_sentiment(self):
        """chat_stream.py should delegate to _analyze_and_process_sentiment."""
        import inspect
        from app.api.v1 import chat_stream
        source = inspect.getsource(chat_stream)
        assert "_analyze_and_process_sentiment" in source


# ============================================================================
# Group 7: Prompt Quality
# ============================================================================

class TestPromptQuality:
    """Verify the sentiment analysis prompt is well-structured."""

    def test_system_prompt_exists(self):
        from app.engine.living_agent.sentiment_analyzer import _SYSTEM_PROMPT
        assert len(_SYSTEM_PROMPT) > 100
        assert "Vietnamese" in _SYSTEM_PROMPT
        assert "diacritics" in _SYSTEM_PROMPT or "without diacritics" in _SYSTEM_PROMPT

    def test_system_prompt_covers_sentiments(self):
        from app.engine.living_agent.sentiment_analyzer import _SYSTEM_PROMPT
        for sentiment in ["positive", "negative", "neutral", "curious", "frustrated", "grateful"]:
            assert sentiment in _SYSTEM_PROMPT

    def test_user_template_has_placeholders(self):
        from app.engine.living_agent.sentiment_analyzer import _USER_TEMPLATE
        assert "{user_message}" in _USER_TEMPLATE
        assert "{ai_response}" in _USER_TEMPLATE
        assert "{user_id}" in _USER_TEMPLATE

    def test_prompt_asks_for_episode_summary(self):
        from app.engine.living_agent.sentiment_analyzer import _SYSTEM_PROMPT
        assert "episode_summary" in _SYSTEM_PROMPT
        assert "Vietnamese" in _SYSTEM_PROMPT
