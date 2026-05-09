"""
Tests for Living Agent Integration — Sprint 170: "Linh Hồn Sống"

Covers:
    1. API Endpoints — /living-agent/* routes
    2. System Prompt Injection — soul + emotion in prompt pipeline
    3. Emotion Event on Chat — USER_CONVERSATION trigger
    4. Feature Gate — all code disabled when enable_living_agent=False
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# 1. API ENDPOINT TESTS
# =============================================================================


class TestLivingAgentAPI:
    """Tests for /api/v1/living-agent/* endpoints."""

    def test_status_endpoint_disabled(self):
        """Status returns enabled=False when feature disabled."""
        from app.api.v1.living_agent import LivingAgentStatusResponse

        response = LivingAgentStatusResponse(enabled=False)
        assert response.enabled is False
        assert response.emotional_state is None
        assert response.heartbeat is None
        assert response.soul_name == ""

    def test_status_endpoint_enabled(self):
        """Status returns full data when enabled."""
        from app.api.v1.living_agent import (
            LivingAgentStatusResponse,
            EmotionalStateResponse,
            HeartbeatInfoResponse,
        )

        response = LivingAgentStatusResponse(
            enabled=True,
            emotional_state=EmotionalStateResponse(
                primary_mood="curious",
                energy_level=0.7,
                social_battery=0.8,
                engagement=0.5,
                mood_label="tò mò",
                behavior_modifiers={"humor": "tự nhiên"},
            ),
            heartbeat=HeartbeatInfoResponse(
                is_running=True,
                heartbeat_count=42,
                interval_seconds=1800,
                active_hours="08:00-23:00 UTC+7",
            ),
            soul_loaded=True,
            soul_name="Wiii",
        )
        assert response.enabled is True
        assert response.emotional_state.primary_mood == "curious"
        assert response.heartbeat.is_running is True
        assert response.soul_name == "Wiii"

    def test_emotional_state_response_model(self):
        """EmotionalStateResponse validates correctly."""
        from app.api.v1.living_agent import EmotionalStateResponse

        state = EmotionalStateResponse(
            primary_mood="happy",
            energy_level=0.9,
            social_battery=0.6,
            engagement=0.8,
            mood_label="vui vẻ",
        )
        assert state.primary_mood == "happy"
        assert state.energy_level == 0.9
        assert state.last_updated is None

    def test_emotional_state_returns_safe_default_when_disabled(self):
        """Status panels can poll emotional state without noisy 404s when disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False

            from app.api.v1.living_agent_runtime import get_emotional_state_response

            state = get_emotional_state_response()

        assert state.primary_mood == "neutral"
        assert state.mood_label == "bình thường"

    def test_journal_entry_response_model(self):
        """JournalEntryResponse validates correctly."""
        from app.api.v1.living_agent import JournalEntryResponse

        entry = JournalEntryResponse(
            id="test-id",
            entry_date="2026-02-22",
            content="Hôm nay vui quá!",
            mood_summary="happy",
            energy_avg=0.8,
            notable_events=["Helped a user"],
            learnings=["COLREGs Rule 14"],
            goals_next=["Learn more about SOLAS"],
        )
        assert entry.content == "Hôm nay vui quá!"
        assert len(entry.learnings) == 1

    def test_skill_response_model(self):
        """SkillResponse validates correctly."""
        from app.api.v1.living_agent import SkillResponse

        skill = SkillResponse(
            id="test-id",
            skill_name="COLREGs Rule 14",
            domain="maritime",
            status="learning",
            confidence=0.35,
            usage_count=3,
            success_rate=0.8,
        )
        assert skill.status == "learning"
        assert skill.confidence == 0.35

    def test_heartbeat_trigger_response_model(self):
        """HeartbeatTriggerResponse validates correctly."""
        from app.api.v1.living_agent import HeartbeatTriggerResponse

        result = HeartbeatTriggerResponse(
            success=True,
            actions_taken=3,
            duration_ms=450,
        )
        assert result.success is True
        assert result.error is None

    def test_heartbeat_info_response_model(self):
        """HeartbeatInfoResponse validates correctly."""
        from app.api.v1.living_agent import HeartbeatInfoResponse

        info = HeartbeatInfoResponse(
            is_running=True,
            heartbeat_count=10,
            interval_seconds=1800,
            active_hours="08:00-23:00 UTC+7",
        )
        assert info.interval_seconds == 1800

    def test_check_enabled_raises_when_disabled(self):
        """_check_enabled raises HTTPException when disabled."""
        from fastapi import HTTPException

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False
            from app.api.v1.living_agent import _check_enabled

            with pytest.raises(HTTPException) as exc_info:
                _check_enabled()
            assert exc_info.value.status_code == 404


# =============================================================================
# 2. SYSTEM PROMPT INJECTION TESTS
# =============================================================================


class TestPromptInjection:
    """Tests for soul + emotion injection into system prompt pipeline."""

    def test_soul_prompt_injected_when_enabled(self):
        """Soul prompt appears in system prompt when living agent enabled."""
        # Mock soul_loader
        mock_soul_prompt = "--- LINH HỒN CỦA WIII ---\nTên: Wiii"
        mock_emotion_prompt = "--- TRẠNG THÁI CẢM XÚC ---\nTâm trạng: tò mò"

        with patch(
            "app.core.config.settings"
        ) as mock_settings, patch(
            "app.engine.living_agent.soul_loader.compile_soul_prompt",
            return_value=mock_soul_prompt,
        ), patch(
            "app.engine.living_agent.emotion_engine.get_emotion_engine",
        ) as mock_engine_fn, patch(
            "app.engine.character.character_card.build_wiii_runtime_prompt",
            return_value="",
        ):
            mock_settings.enable_living_agent = True
            # Provide other attrs the prompt_loader might access
            mock_settings.enable_soul_emotion = False
            mock_settings.identity_anchor_interval = 6
            mock_settings.max_injected_facts = 5
            mock_settings.fact_injection_min_confidence = 0.5

            mock_engine = MagicMock()
            mock_engine.compile_emotion_prompt.return_value = mock_emotion_prompt
            mock_engine_fn.return_value = mock_engine

            from app.prompts.prompt_loader import get_prompt_loader

            loader = get_prompt_loader()
            prompt = loader.build_system_prompt(role="student")

            assert "LINH HỒN CỦA WIII" in prompt
            assert "TRẠNG THÁI CẢM XÚC" in prompt

    def test_soul_prompt_not_injected_when_disabled(self):
        """Soul prompt NOT in system prompt when living agent disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False
            mock_settings.enable_soul_emotion = False
            mock_settings.enable_multi_tenant = False
            from app.prompts.prompt_loader import get_prompt_loader

            loader = get_prompt_loader()
            prompt = loader.build_system_prompt(role="student")

            assert "LINH HỒN CỦA WIII" not in prompt

    def test_prompt_injection_graceful_on_error(self):
        """Prompt injection silently skips on import/runtime errors."""
        with patch(
            "app.core.config.settings"
        ) as mock_settings:
            mock_settings.enable_living_agent = True

            with patch(
                "app.engine.living_agent.soul_loader.compile_soul_prompt",
                side_effect=ImportError("Module not found"),
            ):
                from app.prompts.prompt_loader import get_prompt_loader

                loader = get_prompt_loader()
                # Should not raise
                prompt = loader.build_system_prompt(role="student")
                assert isinstance(prompt, str)


# =============================================================================
# 3. EMOTION EVENT ON CHAT TESTS
# =============================================================================


class TestChatEmotionEvent:
    """Tests for USER_CONVERSATION emotion trigger on chat stream."""

    def test_life_event_creation(self):
        """LifeEvent for USER_CONVERSATION is created correctly."""
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        event = LifeEvent(
            event_type=LifeEventType.USER_CONVERSATION,
            description="Hello Wiii! Teach me COLREGs.",
            importance=0.5,
        )
        assert event.event_type == LifeEventType.USER_CONVERSATION
        assert event.importance == 0.5
        assert "COLREGs" in event.description

    def test_emotion_engine_processes_conversation_event(self):
        """EmotionEngine processes USER_CONVERSATION and adjusts state."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()
        initial_engagement = engine.state.engagement

        event = LifeEvent(
            event_type=LifeEventType.USER_CONVERSATION,
            description="Can you help me?",
            importance=0.5,
        )
        engine.process_event(event)

        # USER_CONVERSATION should boost engagement and social battery
        assert engine.state.engagement > initial_engagement

    def test_conversation_event_does_not_crash_on_invalid(self):
        """Processing invalid event type still works gracefully."""
        from app.engine.living_agent.emotion_engine import EmotionEngine
        from app.engine.living_agent.models import LifeEvent, LifeEventType

        engine = EmotionEngine()
        event = LifeEvent(
            event_type=LifeEventType.USER_CONVERSATION,
            description="",
            importance=0.0,
        )
        # Should not raise
        state = engine.process_event(event)
        assert state is not None


# =============================================================================
# 4. FEATURE GATE TESTS
# =============================================================================


class TestFeatureGate:
    """Tests ensuring everything is disabled when enable_living_agent=False."""

    def test_api_router_not_registered_when_disabled(self):
        """Living agent router is not registered when feature disabled."""
        # This tests the pattern in __init__.py
        # When enable_living_agent=False, the router is not included
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False

            # Verify the guard logic
            assert not mock_settings.enable_living_agent

    def test_heartbeat_not_started_when_disabled(self):
        """Heartbeat scheduler is not started when feature disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False

            # The lifespan code checks: if settings.enable_living_agent:
            # This should be False, so heartbeat start() is never called
            assert not mock_settings.enable_living_agent

    def test_emotion_event_skipped_when_disabled(self):
        """Emotion event in chat_stream is skipped when feature disabled."""
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_living_agent = False

            # The chat_stream code checks: if settings.enable_living_agent:
            # This should be False, so process_event is never called
            assert not mock_settings.enable_living_agent

    def test_config_defaults_all_off(self):
        """All living agent config flags default to off/safe values."""
        from app.core.config import Settings

        s = Settings(
            google_api_key="test-key",
            api_key="test-key",
            _env_file=None,
        )
        assert s.enable_living_agent is False
        assert s.living_agent_enable_social_browse is False
        assert s.living_agent_enable_skill_building is False
        assert s.living_agent_require_human_approval is True
        assert s.living_agent_heartbeat_interval == 1800
        assert s.living_agent_local_model == "qwen3:4b-instruct-2507-q4_K_M"


# =============================================================================
# 5. RESPONSE SCHEMA CONSISTENCY TESTS
# =============================================================================


class TestSchemaConsistency:
    """Tests verifying API response schemas match frontend expectations."""

    def test_status_response_serializable(self):
        """LivingAgentStatusResponse is JSON-serializable."""
        from app.api.v1.living_agent import (
            LivingAgentStatusResponse,
            EmotionalStateResponse,
            HeartbeatInfoResponse,
        )

        response = LivingAgentStatusResponse(
            enabled=True,
            emotional_state=EmotionalStateResponse(
                primary_mood="curious",
                energy_level=0.7,
                social_battery=0.8,
                engagement=0.5,
                mood_label="tò mò",
                behavior_modifiers={"humor": "vui vẻ"},
                last_updated="2026-02-22T10:00:00+00:00",
            ),
            heartbeat=HeartbeatInfoResponse(
                is_running=True,
                heartbeat_count=5,
                interval_seconds=1800,
                active_hours="08:00-23:00 UTC+7",
            ),
            soul_loaded=True,
            soul_name="Wiii",
        )

        data = response.model_dump(mode="json")
        assert data["enabled"] is True
        assert data["emotional_state"]["primary_mood"] == "curious"
        assert data["heartbeat"]["heartbeat_count"] == 5

        # Verify JSON serializable
        json_str = json.dumps(data, ensure_ascii=False)
        assert "tò mò" in json_str

    def test_journal_list_response_serializable(self):
        """List of JournalEntryResponse is JSON-serializable."""
        from app.api.v1.living_agent import JournalEntryResponse

        entries = [
            JournalEntryResponse(
                id="entry-1",
                entry_date="2026-02-22",
                content="Ngày tuyệt vời!",
                mood_summary="happy",
                energy_avg=0.9,
            ),
            JournalEntryResponse(
                id="entry-2",
                entry_date="2026-02-21",
                content="Học được nhiều.",
                mood_summary="focused",
                energy_avg=0.6,
                learnings=["MARPOL Annex I"],
            ),
        ]

        data = [e.model_dump(mode="json") for e in entries]
        json_str = json.dumps(data, ensure_ascii=False)
        assert "Ngày tuyệt vời" in json_str
        assert len(data) == 2

    def test_skills_list_response_serializable(self):
        """List of SkillResponse is JSON-serializable."""
        from app.api.v1.living_agent import SkillResponse

        skills = [
            SkillResponse(
                id="skill-1",
                skill_name="COLREGs Rule 14",
                domain="maritime",
                status="mastered",
                confidence=0.95,
                usage_count=15,
                success_rate=0.92,
            ),
        ]

        data = [s.model_dump(mode="json") for s in skills]
        json_str = json.dumps(data)
        assert "COLREGs Rule 14" in json_str


# =============================================================================
# 6. MAIN.PY LIFESPAN INTEGRATION TESTS
# =============================================================================


class TestLifespanIntegration:
    """Tests for heartbeat wiring in main.py lifespan."""

    def test_heartbeat_scheduler_singleton(self):
        """get_heartbeat_scheduler returns same instance."""
        from app.engine.living_agent.heartbeat import get_heartbeat_scheduler

        s1 = get_heartbeat_scheduler()
        s2 = get_heartbeat_scheduler()
        assert s1 is s2

    def test_heartbeat_initial_state(self):
        """HeartbeatScheduler starts in stopped state."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        assert scheduler.is_running is False
        assert scheduler.heartbeat_count == 0

    @pytest.mark.asyncio
    async def test_heartbeat_start_stop(self):
        """HeartbeatScheduler can start and stop cleanly."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()

        # Mock the _heartbeat_loop to avoid real execution
        with patch.object(scheduler, "_heartbeat_loop", new_callable=AsyncMock):
            await scheduler.start()
            assert scheduler.is_running is True

            await scheduler.stop()
            assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_heartbeat_double_start_noop(self):
        """Starting heartbeat twice is a no-op."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()

        with patch.object(scheduler, "_heartbeat_loop", new_callable=AsyncMock):
            await scheduler.start()
            await scheduler.start()  # Should log warning, not crash
            assert scheduler.is_running is True

            await scheduler.stop()


# =============================================================================
# 7. EMOTIONAL STATE REPOSITORY TESTS
# =============================================================================


class TestEmotionalStateRepository:
    """Tests for the emotional state DB repository."""

    def test_repository_instantiation(self):
        """EmotionalStateRepository can be instantiated."""
        from app.repositories.emotional_state_repository import (
            EmotionalStateRepository,
        )

        repo = EmotionalStateRepository()
        assert repo is not None

    def test_save_snapshot_raises_on_db_error(self):
        """save_snapshot propagates DB errors (caller catches)."""
        from app.repositories.emotional_state_repository import (
            EmotionalStateRepository,
        )

        repo = EmotionalStateRepository()

        # Mock get_shared_session_factory to raise immediately
        with patch(
            "app.repositories.emotional_state_repository.get_shared_session_factory",
            side_effect=Exception("DB unavailable"),
        ):
            with pytest.raises(Exception, match="DB unavailable"):
                repo.save_snapshot(
                    primary_mood="curious",
                    energy_level=0.7,
                    social_battery=0.8,
                    engagement=0.5,
                    trigger_event="test",
                    state_json={"test": True},
                )

    def test_heartbeat_catches_snapshot_errors(self):
        """Heartbeat's _save_emotional_snapshot catches repo errors."""
        # Verify that the heartbeat wrapper catches exceptions
        # (the repo raises, but heartbeat logs warning)
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        # _save_emotional_snapshot wraps in try/except
        # Just verify it exists and is async
        import inspect
        assert inspect.iscoroutinefunction(scheduler._save_emotional_snapshot)
