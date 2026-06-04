"""
Sprint 94: Character Reflection Engine — Self-Evolving Loop

Tests:
1. ReflectionEngine basics (counter, interval, stats)
2. Prompt building (blocks, experiences, formatting)
3. JSON parsing (valid, invalid, edge cases)
4. Update application (append, replace, invalid blocks)
5. Full reflection cycle (mock LLM)
6. Background task integration
7. Config feature gate
8. Edge cases (empty blocks, DB unavailable, LLM failure)
"""

import json
import sys
import types
import time
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

# Break circular import (graph → services → chat_service → graph)
_cs_key = "app.services.chat_service"
if _cs_key not in sys.modules:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs

from app.engine.character.models import (
    BlockLabel,
    CharacterBlock,
    CharacterExperience,
    CharacterExperienceCreate,
    ExperienceType,
    BLOCK_CHAR_LIMITS,
)


# =============================================================================
# Phase 1: ReflectionEngine basics
# =============================================================================

class TestReflectionEngineBasics:
    """Core mechanics: counter, interval, should_reflect."""

    def test_engine_creation(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        assert engine._conversation_counts.get("__global__", 0) == 0

    def test_increment_counter(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        assert engine.increment_conversation_count() == 1
        assert engine.increment_conversation_count() == 2
        assert engine.increment_conversation_count() == 3

    @patch("app.core.config.settings")
    def test_should_reflect_false_when_disabled(self, mock_settings):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = False
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 100
        assert not engine.should_reflect()

    @patch("app.core.config.settings")
    def test_should_reflect_false_below_interval(self, mock_settings):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 5.0
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 3
        assert not engine.should_reflect()

    @patch("app.core.config.settings")
    def test_should_reflect_true_at_importance_threshold(self, mock_settings):
        """Sprint 98: Triggers via importance_sum >= threshold."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 5.0
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 2
        engine._importance_sums["__global__"] = 5.0
        assert engine.should_reflect()

    @patch("app.core.config.settings")
    def test_should_reflect_true_at_2x_interval(self, mock_settings):
        """Sprint 98: Safety net triggers at 2x interval."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 100.0  # Very high
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 10  # 2 * 5
        assert engine.should_reflect()

    def test_reset_counter(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 10
        engine._importance_sums["__global__"] = 7.5
        engine.reset_counter()
        assert engine._conversation_counts.get("__global__", 0) == 0
        assert engine._importance_sums.get("__global__", 0.0) == 0.0
        assert engine._last_reflection_times.get("__global__", 0) > 0

    @patch("app.core.config.settings")
    def test_get_stats(self, mock_settings):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = True
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 5.0
        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 3
        engine._importance_sums["__global__"] = 2.5
        stats = engine.get_stats()
        assert stats["enabled"] is True
        assert stats["conversation_count"] == 3
        assert stats["importance_sum"] == 2.5
        assert stats["interval"] == 5
        assert stats["threshold"] == 5.0
        assert stats["conversations_until_reflection"] == 7  # 2*5 - 3

    @patch("app.core.config.settings")
    def test_get_stats_at_zero(self, mock_settings):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        mock_settings.enable_character_reflection = False
        mock_settings.character_reflection_interval = 5
        mock_settings.character_reflection_threshold = 5.0
        engine = CharacterReflectionEngine()
        stats = engine.get_stats()
        assert stats["enabled"] is False
        assert stats["conversations_until_reflection"] == 10  # 2*5


# =============================================================================
# Phase 2: Prompt building
# =============================================================================

class TestPromptBuilding:
    """Test _build_reflection_prompt with various inputs."""

    def _make_block(self, label, content="", char_limit=1000):
        return CharacterBlock(
            id=uuid4(),
            label=label,
            content=content,
            char_limit=char_limit,
            version=1,
        )

    def _make_experience(self, exp_type="learning", content="test"):
        return CharacterExperience(
            id=uuid4(),
            experience_type=exp_type,
            content=content,
            importance=0.5,
            created_at=datetime.now(),
        )

    def test_prompt_with_empty_blocks(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        prompt = engine._build_reflection_prompt(
            blocks={},
            experiences=[],
            last_user_message="Hello",
            last_response="Hi!",
        )
        assert "Character Blocks hiện tại" in prompt
        assert "(trống)" in prompt  # Empty blocks shown as (trống)
        assert "Hello" in prompt
        assert "Hi!" in prompt

    def test_prompt_with_filled_blocks(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        blocks = {
            "learned_lessons": self._make_block(
                "learned_lessons", "- Rule 15 hay được hỏi", 1500
            ),
        }
        prompt = engine._build_reflection_prompt(
            blocks=blocks,
            experiences=[],
            last_user_message="test",
            last_response="test",
        )
        assert "learned_lessons" in prompt
        assert "Rule 15 hay được hỏi" in prompt

    def test_prompt_with_experiences(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        experiences = [
            self._make_experience("learning", "User thích hỏi về COLREGs"),
            self._make_experience("milestone", "Lần đầu giải thích SOLAS"),
        ]
        prompt = engine._build_reflection_prompt(
            blocks={},
            experiences=experiences,
            last_user_message="test",
            last_response="test",
        )
        assert "COLREGs" in prompt
        assert "SOLAS" in prompt
        assert "[learning]" in prompt
        assert "[milestone]" in prompt

    def test_prompt_truncates_long_messages(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        long_msg = "x" * 1000
        prompt = engine._build_reflection_prompt(
            blocks={},
            experiences=[],
            last_user_message=long_msg,
            last_response=long_msg,
        )
        # Should be truncated to 500 chars
        assert "x" * 500 in prompt
        assert "x" * 600 not in prompt

    def test_prompt_has_json_format_instruction(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        prompt = engine._build_reflection_prompt(
            blocks={},
            experiences=[],
            last_user_message="test",
            last_response="test",
        )
        assert "should_update" in prompt
        assert "learned_lessons" in prompt
        assert "append" in prompt


# =============================================================================
# Phase 3: JSON parsing
# =============================================================================

class TestReflectionParsing:
    """Test _parse_reflection with various LLM outputs."""

    def _get_engine(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        return CharacterReflectionEngine()

    def test_parse_valid_json_with_updates(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "learned_lessons", "action": "append", "content": "Rule 15 hay được hỏi"},
                {"block": "favorite_topics", "action": "append", "content": "COLREGs"},
            ],
            "reflection_summary": "User hay hỏi về COLREGs",
        })
        result = engine._parse_reflection(raw)
        assert result is not None
        assert result["should_update"] is True
        assert len(result["updates"]) == 2

    def test_parse_valid_no_update(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": False,
            "updates": [],
            "reflection_summary": "Không có gì mới",
        })
        result = engine._parse_reflection(raw)
        assert result is not None
        assert result["should_update"] is False
        assert len(result["updates"]) == 0

    def test_parse_with_markdown_fences(self):
        engine = self._get_engine()
        raw = '```json\n{"should_update": false, "updates": [], "reflection_summary": "ok"}\n```'
        result = engine._parse_reflection(raw)
        assert result is not None
        assert result["should_update"] is False

    def test_parse_invalid_json(self):
        engine = self._get_engine()
        result = engine._parse_reflection("not json at all")
        assert result is None

    def test_parse_missing_should_update(self):
        engine = self._get_engine()
        raw = json.dumps({"updates": [], "summary": "ok"})
        result = engine._parse_reflection(raw)
        assert result is None

    def test_parse_filters_invalid_block_labels(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "invalid_block", "action": "append", "content": "test"},
                {"block": "learned_lessons", "action": "append", "content": "valid"},
            ],
            "reflection_summary": "test",
        })
        result = engine._parse_reflection(raw)
        assert len(result["updates"]) == 1
        assert result["updates"][0]["block"] == "learned_lessons"

    def test_parse_filters_invalid_actions(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "learned_lessons", "action": "delete", "content": "test"},
                {"block": "learned_lessons", "action": "append", "content": "valid"},
            ],
            "reflection_summary": "test",
        })
        result = engine._parse_reflection(raw)
        assert len(result["updates"]) == 1
        assert result["updates"][0]["action"] == "append"

    def test_parse_filters_empty_content(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "learned_lessons", "action": "append", "content": ""},
                {"block": "self_notes", "action": "replace", "content": "valid"},
            ],
            "reflection_summary": "test",
        })
        result = engine._parse_reflection(raw)
        assert len(result["updates"]) == 1
        assert result["updates"][0]["block"] == "self_notes"

    def test_parse_non_dict_updates_skipped(self):
        engine = self._get_engine()
        raw = json.dumps({
            "should_update": True,
            "updates": ["not a dict", 42],
            "reflection_summary": "test",
        })
        result = engine._parse_reflection(raw)
        assert len(result["updates"]) == 0

    def test_parse_returns_none_for_non_dict(self):
        engine = self._get_engine()
        result = engine._parse_reflection('"just a string"')
        assert result is None


# =============================================================================
# Phase 4: Update application
# =============================================================================

class TestUpdateApplication:
    """Test _apply_updates with mock state manager."""

    def _get_engine(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        return CharacterReflectionEngine()

    def test_apply_append_update(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        mock_manager.update_block.return_value = MagicMock()

        updates = [
            {"block": "learned_lessons", "action": "append", "content": "Rule 15 test"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 1
        mock_manager.update_block.assert_called_once()
        call_kwargs = mock_manager.update_block.call_args
        assert call_kwargs[1]["label"] == "learned_lessons"
        assert "Rule 15 test" in call_kwargs[1]["append"]

    def test_apply_replace_update(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        mock_manager.update_block.return_value = MagicMock()

        updates = [
            {"block": "self_notes", "action": "replace", "content": "New content"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 1
        call_kwargs = mock_manager.update_block.call_args
        assert call_kwargs[1]["content"] == "New content"

    def test_apply_multiple_updates(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        mock_manager.update_block.return_value = MagicMock()

        updates = [
            {"block": "learned_lessons", "action": "append", "content": "Lesson 1"},
            {"block": "favorite_topics", "action": "append", "content": "COLREGs"},
            {"block": "self_notes", "action": "replace", "content": "New notes"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 3
        assert mock_manager.update_block.call_count == 3

    def test_apply_update_failure_counted(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        mock_manager.update_block.return_value = None  # DB failure

        updates = [
            {"block": "learned_lessons", "action": "append", "content": "test"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 0

    def test_apply_update_exception_handled(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        mock_manager.update_block.side_effect = Exception("DB error")

        updates = [
            {"block": "learned_lessons", "action": "append", "content": "test"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 0

    def test_apply_empty_updates(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        count = engine._apply_updates(mock_manager, [])
        assert count == 0
        mock_manager.update_block.assert_not_called()

    def test_apply_unknown_action_skipped(self):
        engine = self._get_engine()
        mock_manager = MagicMock()
        updates = [
            {"block": "learned_lessons", "action": "delete", "content": "test"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 0


# =============================================================================
# Phase 5: Full reflection cycle (async)
# =============================================================================

class TestFullReflectionCycle:
    """Test the complete reflect() method with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_reflect_with_updates(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_block = CharacterBlock(
            id=uuid4(), label="learned_lessons", content="- Old lesson",
            char_limit=1500, version=1,
        )
        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {"learned_lessons": mock_block}
        mock_manager.update_block.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []
        mock_repo.log_experience.return_value = MagicMock()

        llm_response = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "learned_lessons", "action": "append", "content": "New lesson"},
            ],
            "reflection_summary": "Learned something new",
        })

        with patch("app.engine.character.character_state.get_character_state_manager",
                    return_value=mock_manager), \
             patch("app.engine.character.character_repository.get_character_repository",
                    return_value=mock_repo), \
             patch.object(engine, "_call_llm", new_callable=AsyncMock,
                         return_value=llm_response):
            result = await engine.reflect(
                last_user_message="Rule 15 là gì?",
                last_response="Rule 15 quy định...",
                user_id="test-user",
            )

        assert result is not None
        assert result["should_update"] is True
        assert result["applied_count"] == 1
        mock_manager.update_block.assert_called_once()
        mock_repo.log_experience.assert_called_once()
        assert engine._conversation_counts.get("test-user", 0) == 0  # Reset after reflection

    @pytest.mark.asyncio
    async def test_reflect_no_updates(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        engine._conversation_counts["__global__"] = 5

        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []
        mock_repo.log_experience.return_value = MagicMock()

        llm_response = json.dumps({
            "should_update": False,
            "updates": [],
            "reflection_summary": "Nothing new",
        })

        with patch("app.engine.character.character_state.get_character_state_manager",
                    return_value=mock_manager), \
             patch("app.engine.character.character_repository.get_character_repository",
                    return_value=mock_repo), \
             patch.object(engine, "_call_llm", new_callable=AsyncMock,
                         return_value=llm_response):
            result = await engine.reflect(
                last_user_message="test",
                last_response="test",
            )

        assert result is not None
        assert result["should_update"] is False
        assert result["applied_count"] == 0
        mock_manager.update_block.assert_not_called()
        # Still logs reflection experience
        mock_repo.log_experience.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflect_llm_returns_none(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []

        with patch("app.engine.character.character_state.get_character_state_manager",
                    return_value=mock_manager), \
             patch("app.engine.character.character_repository.get_character_repository",
                    return_value=mock_repo), \
             patch.object(engine, "_call_llm", new_callable=AsyncMock,
                         return_value=None):
            result = await engine.reflect(
                last_user_message="test",
                last_response="test",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_reflect_llm_returns_invalid_json(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []

        with patch("app.engine.character.character_state.get_character_state_manager",
                    return_value=mock_manager), \
             patch("app.engine.character.character_repository.get_character_repository",
                    return_value=mock_repo), \
             patch.object(engine, "_call_llm", new_callable=AsyncMock,
                         return_value="not valid json"):
            result = await engine.reflect(
                last_user_message="test",
                last_response="test",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_reflect_exception_handled(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        with patch("app.engine.character.character_state.get_character_state_manager",
                    side_effect=Exception("DB down")):
            result = await engine.reflect(
                last_user_message="test",
                last_response="test",
            )

        assert result is None  # Graceful failure


# =============================================================================
# Phase 6: Background task integration
# =============================================================================

class TestBackgroundTaskIntegration:
    """Test trigger_character_reflection() entry point."""

    @pytest.mark.asyncio
    async def test_trigger_increments_counter(self):
        from app.engine.character.reflection_engine import (
            CharacterReflectionEngine,
            get_reflection_engine,
            trigger_character_reflection,
        )

        engine = CharacterReflectionEngine()
        engine._conversation_counts["test"] = 0

        with patch("app.engine.character.reflection_engine.get_reflection_engine",
                    return_value=engine), \
             patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_character_reflection = True
            mock_settings.character_reflection_interval = 10

            await trigger_character_reflection(
                user_id="test",
                message="hello",
                response="hi",
            )

        assert engine._conversation_counts.get("test", 0) == 1

    @pytest.mark.asyncio
    async def test_trigger_skips_when_not_interval(self):
        from app.engine.character.reflection_engine import (
            CharacterReflectionEngine,
            trigger_character_reflection,
        )

        engine = CharacterReflectionEngine()
        engine._conversation_counts["test"] = 2

        with patch("app.engine.character.reflection_engine.get_reflection_engine",
                    return_value=engine), \
             patch("app.core.config.settings") as mock_settings, \
             patch.object(engine, "reflect", new_callable=AsyncMock) as mock_reflect:
            mock_settings.enable_character_reflection = True
            mock_settings.character_reflection_interval = 10

            await trigger_character_reflection(
                user_id="test",
                message="hello",
                response="hi",
            )

        mock_reflect.assert_not_called()
        assert engine._conversation_counts.get("test", 0) == 3

    @pytest.mark.asyncio
    async def test_trigger_calls_reflect_at_importance_threshold(self):
        """Sprint 98: trigger via importance_sum >= threshold."""
        from app.engine.character.reflection_engine import (
            CharacterReflectionEngine,
            trigger_character_reflection,
        )

        engine = CharacterReflectionEngine()
        engine._conversation_counts["test-user"] = 4  # Will become 5
        engine._importance_sums["test-user"] = 5.0  # At threshold → triggers

        with patch("app.engine.character.reflection_engine.get_reflection_engine",
                    return_value=engine), \
             patch("app.core.config.settings") as mock_settings, \
             patch.object(engine, "reflect", new_callable=AsyncMock,
                         return_value={"should_update": False}) as mock_reflect:
            mock_settings.enable_character_reflection = True
            mock_settings.character_reflection_interval = 5
            mock_settings.character_reflection_threshold = 5.0

            await trigger_character_reflection(
                user_id="test-user",
                message="Rule 15?",
                response="Rule 15 is...",
            )

            mock_reflect.assert_called_once_with(
                last_user_message="Rule 15?",
                last_response="Rule 15 is...",
                user_id="test-user",
                organization_id=None,
            )

    @pytest.mark.asyncio
    async def test_trigger_exception_handled(self):
        from app.engine.character.reflection_engine import trigger_character_reflection

        with patch("app.engine.character.reflection_engine.get_reflection_engine",
                    side_effect=Exception("catastrophic")):
            # Should not raise
            await trigger_character_reflection(
                user_id="test",
                message="hello",
                response="hi",
            )


# =============================================================================
# Phase 7: Config feature gate
# =============================================================================

class TestConfigFeatureGate:
    """Test config flags for character reflection."""

    def test_config_has_enable_flag(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert hasattr(s, "enable_character_reflection")
        assert s.enable_character_reflection is True  # Sprint 97: Default on

    def test_config_has_interval_flag(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test")
        assert hasattr(s, "character_reflection_interval")
        assert s.character_reflection_interval == 5  # Default 5

    def test_config_interval_min_1(self):
        from app.core.config import Settings
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Settings(
                google_api_key="test",
                api_key="test",
                character_reflection_interval=0,
            )

    def test_config_interval_max_50(self):
        from app.core.config import Settings
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Settings(
                google_api_key="test",
                api_key="test",
                character_reflection_interval=100,
            )

    def test_config_interval_valid_range(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test",
            api_key="test",
            character_reflection_interval=10,
        )
        assert s.character_reflection_interval == 10


# =============================================================================
# Phase 8: BackgroundTaskRunner integration
# =============================================================================

class TestBackgroundRunnerWiring:
    """Test that BackgroundTaskRunner.schedule_all() calls reflection."""

    def test_schedule_all_calls_reflection_when_enabled(self):
        from app.services.background_tasks import BackgroundTaskRunner
        runner = BackgroundTaskRunner()
        mock_bg_save = MagicMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_character_reflection = True
            runner.schedule_all(
                background_save=mock_bg_save,
                user_id="test-user",
                session_id="test-session",
                message="hello",
                response="hi",
            )

        # Should have at least one call for reflection
        calls = mock_bg_save.call_args_list
        call_funcs = [c[0][0].__name__ if callable(c[0][0]) else str(c[0][0]) for c in calls]
        assert "_trigger_reflection" in call_funcs

    def test_schedule_all_skips_reflection_when_disabled(self):
        from app.services.background_tasks import BackgroundTaskRunner
        runner = BackgroundTaskRunner()
        mock_bg_save = MagicMock()

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.enable_character_reflection = False
            runner.schedule_all(
                background_save=mock_bg_save,
                user_id="test-user",
                session_id="test-session",
                message="hello",
                response="hi",
            )

        calls = mock_bg_save.call_args_list
        call_funcs = [c[0][0].__name__ if callable(c[0][0]) else str(c[0][0]) for c in calls]
        assert "_trigger_reflection" not in call_funcs


# =============================================================================
# Phase 9: Singleton
# =============================================================================

class TestSingleton:
    """Test singleton pattern for reflection engine."""

    def test_get_reflection_engine_returns_same_instance(self):
        import app.engine.character.reflection_engine as mod
        old = mod._reflection_engine
        try:
            mod._reflection_engine = None
            e1 = mod.get_reflection_engine()
            e2 = mod.get_reflection_engine()
            assert e1 is e2
        finally:
            mod._reflection_engine = old

    def test_singleton_preserves_counter(self):
        import app.engine.character.reflection_engine as mod
        old = mod._reflection_engine
        try:
            mod._reflection_engine = None
            e1 = mod.get_reflection_engine()
            e1.increment_conversation_count()
            e2 = mod.get_reflection_engine()
            assert e2._conversation_counts.get("__global__", 0) == 1
        finally:
            mod._reflection_engine = old


# =============================================================================
# Phase 10: LLM call
# =============================================================================

class TestLLMCall:
    """Test _call_llm with mocked LLM pool."""

    @pytest.mark.asyncio
    async def test_call_llm_success_prefers_auto_provider(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        mock_result = MagicMock()
        mock_result.content = '{"should_update": false}'

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_result

        with patch("app.engine.llm_pool.get_llm_for_provider", return_value=mock_llm) as mock_get_auto, \
             patch("app.engine.llm_pool.get_llm_light") as mock_get_light:
            result = await engine._call_llm("test prompt")

        assert result == '{"should_update": false}'
        mock_llm.ainvoke.assert_called_once()
        mock_get_auto.assert_called_once()
        mock_get_light.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_llm_falls_back_to_shared_light_instance(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        mock_result = MagicMock()
        mock_result.content = '{"should_update": false}'
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_result

        with patch("app.engine.llm_pool.get_llm_for_provider", side_effect=Exception("busy")) as mock_get_auto, \
             patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm) as mock_get_light:
            result = await engine._call_llm("test prompt")

        assert result == '{"should_update": false}'
        mock_get_auto.assert_called_once()
        mock_get_light.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_llm_no_content_attr(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()
        mock_result = "raw string result"

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = mock_result

        with patch("app.engine.llm_pool.get_llm_for_provider", return_value=mock_llm):
            result = await engine._call_llm("test prompt")

        assert result == "raw string result"

    @pytest.mark.asyncio
    async def test_call_llm_returns_none_when_all_routes_fail(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        with patch("app.engine.llm_pool.get_llm_for_provider", side_effect=Exception("busy")), \
             patch("app.engine.llm_pool.get_llm_light", side_effect=Exception("No API key")):
            result = await engine._call_llm("test prompt")

        assert result is None


# =============================================================================
# Phase 11: Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge cases and error handling."""

    def test_parse_reflection_with_extra_fields(self):
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        raw = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "self_notes", "action": "replace", "content": "test"},
            ],
            "reflection_summary": "ok",
            "extra_field": "ignored",
        })
        result = engine._parse_reflection(raw)
        assert result is not None
        assert result["should_update"] is True

    def test_apply_updates_partial_failure(self):
        """Some updates succeed, some fail."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()

        mock_manager = MagicMock()
        # First call succeeds, second fails
        mock_manager.update_block.side_effect = [MagicMock(), None]

        updates = [
            {"block": "learned_lessons", "action": "append", "content": "ok"},
            {"block": "self_notes", "action": "replace", "content": "fail"},
        ]
        count = engine._apply_updates(mock_manager, updates)
        assert count == 1  # Only first succeeded

    @pytest.mark.asyncio
    async def test_reflect_with_all_four_blocks(self):
        """Reflection with updates to all 4 blocks."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine

        engine = CharacterReflectionEngine()

        mock_manager = MagicMock()
        mock_manager.get_blocks.return_value = {}
        mock_manager.update_block.return_value = MagicMock()

        mock_repo = MagicMock()
        mock_repo.get_recent_experiences.return_value = []
        mock_repo.log_experience.return_value = MagicMock()

        llm_response = json.dumps({
            "should_update": True,
            "updates": [
                {"block": "learned_lessons", "action": "append", "content": "L1"},
                {"block": "favorite_topics", "action": "append", "content": "T1"},
                {"block": "user_patterns", "action": "append", "content": "P1"},
                {"block": "self_notes", "action": "replace", "content": "N1"},
            ],
            "reflection_summary": "Full update",
        })

        with patch("app.engine.character.character_state.get_character_state_manager",
                    return_value=mock_manager), \
             patch("app.engine.character.character_repository.get_character_repository",
                    return_value=mock_repo), \
             patch.object(engine, "_call_llm", new_callable=AsyncMock,
                         return_value=llm_response):
            result = await engine.reflect(
                last_user_message="test",
                last_response="test",
            )

        assert result["applied_count"] == 4

    def test_engine_default_interval_without_config(self):
        """Engine should have reasonable default if config import fails."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        # Simulate config module not available
        with patch.dict(sys.modules, {"app.core.config": None}):
            interval = engine._get_interval()
        assert interval == 5  # Fallback

    def test_engine_disabled_without_config(self):
        """Engine should be disabled if config import fails."""
        from app.engine.character.reflection_engine import CharacterReflectionEngine
        engine = CharacterReflectionEngine()
        with patch.dict(sys.modules, {"app.core.config": None}):
            assert not engine._is_enabled()
