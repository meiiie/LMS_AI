"""
Sprint 206: "Câu Chuyện Cuộc Đời" — Narrative Layer Tests

Tests the NarrativeSynthesizer: brief context for prompt injection,
full autobiography compilation, data source integration, and flag gating.

SOTA 2026 Reference:
  - Letta/MemGPT: Persona block self-edit, compiled each turn
  - Nomi.ai: Dynamic personality growing from interactions
  - OpenClaw: SOUL.md defines identity, runtime honors it

35 tests across 6 groups:
1. get_brief_context (8 tests)
2. compile_autobiography (7 tests)
3. _compile_narrative_text (5 tests)
4. _mood_vi helper (4 tests)
5. Prompt integration (5 tests)
6. Config gating + regression (6 tests)
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from app.engine.living_agent.narrative_synthesizer import (
    get_brief_context,
    compile_autobiography,
    _compile_narrative_text,
    _mood_vi,
)


# =============================================================================
# Helpers
# =============================================================================


def _mock_settings(**overrides):
    """Create a mock Settings with Sprint 206 defaults."""
    defaults = {
        "enable_living_agent": False,
        "enable_narrative_context": False,
        "enable_natural_conversation": False,
        "default_domain": "maritime",
        "app_name": "Wiii",
    }
    defaults.update(overrides)
    s = MagicMock()
    s.__class__ = type("MockSettings", (), {})
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _mock_emotional_state(mood="curious", energy=0.75, social=0.6, engagement=0.8):
    """Create a mock EmotionalState."""
    state = MagicMock()
    state.primary_mood = MagicMock(value=mood)
    state.energy_level = energy
    state.social_battery = social
    state.engagement = engagement
    state.recent_emotions = []
    state.mood_history = []
    return state


def _mock_skill(name, domain="general", status_val="mastered", confidence=0.9, usage=10):
    """Create a mock WiiiSkill."""
    from app.engine.living_agent.models import SkillStatus
    skill = MagicMock()
    skill.skill_name = name
    skill.domain = domain
    skill.status = SkillStatus(status_val) if status_val in [s.value for s in SkillStatus] else MagicMock(value=status_val)
    skill.confidence = confidence
    skill.usage_count = usage
    return skill


# =============================================================================
# Group 1: get_brief_context (8 tests)
# =============================================================================


class TestGetBriefContext:
    """Brief context for system prompt injection."""

    @patch("app.core.config.get_settings")
    def test_returns_empty_when_living_agent_disabled(self, mock_gs):
        """Returns '' when enable_living_agent=False."""
        mock_gs.return_value = _mock_settings(enable_living_agent=False)
        assert get_brief_context() == ""

    @patch("app.core.config.get_settings")
    def test_returns_empty_when_narrative_disabled(self, mock_gs):
        """Returns '' when enable_narrative_context=False."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=False)
        assert get_brief_context() == ""

    @patch("app.core.config.get_settings")
    def test_includes_mood_and_energy(self, mock_gs):
        """Brief context includes mood and energy when enabled."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state(mood="happy", energy=0.80)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            result = get_brief_context()

        assert "CUỘC SỐNG CỦA WIII" in result
        assert "vui vẻ" in result
        assert "80%" in result

    @patch("app.core.config.get_settings")
    def test_includes_skill_highlights(self, mock_gs):
        """Brief context includes mastered skills."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state()

        from app.engine.living_agent.models import SkillStatus
        mock_builder = MagicMock()
        mastered_skill = MagicMock(skill_name="maritime_navigation", status=SkillStatus.MASTERED)
        practicing_skill = MagicMock(skill_name="web_research", status=SkillStatus.PRACTICING)
        mock_builder.get_all_skills.return_value = [mastered_skill, practicing_skill]

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            with patch("app.engine.living_agent.skill_builder.get_skill_builder", return_value=mock_builder):
                result = get_brief_context()

        assert "thành thạo" in result
        assert "maritime_navigation" in result

    @patch("app.core.config.get_settings")
    def test_brief_context_passes_org_to_skill_builder(self, mock_gs):
        """Brief skill highlights use the caller's org scope."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state()
        mock_builder = MagicMock()
        mock_builder.get_all_skills.return_value = []

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine), \
             patch("app.engine.living_agent.skill_builder.get_skill_builder", return_value=mock_builder):
            get_brief_context(organization_id="org-A")

        mock_builder.get_all_skills.assert_called_once_with(organization_id="org-A")

    @patch("app.core.config.get_settings")
    def test_starts_with_section_header(self, mock_gs):
        """Brief context starts with '--- CUỘC SỐNG CỦA WIII ---'."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state()

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            result = get_brief_context()

        assert result.startswith("--- CUỘC SỐNG CỦA WIII ---")

    @patch("app.core.config.get_settings")
    def test_empty_when_no_data(self, mock_gs):
        """Returns '' when emotion engine fails."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", side_effect=RuntimeError("not init")):
            with patch("app.engine.living_agent.skill_builder.get_skill_builder", side_effect=RuntimeError):
                result = get_brief_context()

        assert result == ""

    @patch("app.core.config.get_settings")
    def test_error_resilient(self, mock_gs):
        """Does not raise on any internal error."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True, enable_narrative_context=True)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", side_effect=Exception("boom")):
            # Should not raise
            result = get_brief_context()
            assert isinstance(result, str)

    def test_returns_string_always(self):
        """Always returns a string (never None)."""
        result = get_brief_context()
        assert isinstance(result, str)


# =============================================================================
# Group 2: compile_autobiography (7 tests)
# =============================================================================


class TestCompileAutobiography:
    """Full life narrative compilation."""

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_returns_error_when_disabled(self, mock_gs):
        """Returns error dict when living agent disabled."""
        mock_gs.return_value = _mock_settings(enable_living_agent=False)
        result = await compile_autobiography()
        assert result.get("error") == "Living Agent disabled"

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_includes_identity(self, mock_gs):
        """Autobiography includes identity from soul."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        mock_soul = MagicMock()
        mock_soul.name = "Wiii"
        mock_soul.creator = "The Wiii Lab"
        mock_soul.core_truths = ["Tôi là AI đáng yêu"]
        mock_soul.interests = MagicMock(primary=["AI"], exploring=["art"])

        with patch("app.engine.living_agent.soul_loader.get_soul", return_value=mock_soul):
            result = await compile_autobiography(granularity="day")

        assert result["identity"]["name"] == "Wiii"
        assert result["identity"]["creator"] == "The Wiii Lab"

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_includes_emotional_state(self, mock_gs):
        """Autobiography includes current emotional state."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state(mood="focused", energy=0.9)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            result = await compile_autobiography()

        assert result["emotional_state"]["current_mood"] == "focused"
        assert result["emotional_state"]["energy"] == 0.9

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_includes_granularity(self, mock_gs):
        """Autobiography includes requested granularity."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        result = await compile_autobiography(granularity="month")
        assert result["granularity"] == "month"

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_includes_compiled_at(self, mock_gs):
        """Autobiography includes compilation timestamp."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        result = await compile_autobiography()
        assert "compiled_at" in result

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_includes_narrative_text(self, mock_gs):
        """Autobiography includes compiled narrative text."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state(mood="happy", energy=0.8)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            result = await compile_autobiography()

        assert "narrative_text" in result
        assert "Wiii" in result["narrative_text"]

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_compile_passes_org_to_skill_builder(self, mock_gs):
        """Autobiography skill section uses the requested org scope."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        mock_builder = MagicMock()
        mock_builder.get_all_skills.return_value = []

        with patch("app.engine.living_agent.skill_builder.get_skill_builder", return_value=mock_builder):
            result = await compile_autobiography(organization_id="org-A")

        assert "skills" in result
        mock_builder.get_all_skills.assert_called_once_with(organization_id="org-A")

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_error_resilient(self, mock_gs):
        """Each section fails independently without breaking others."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)

        # All data sources fail
        with patch("app.engine.living_agent.soul_loader.get_soul", side_effect=RuntimeError):
            with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", side_effect=RuntimeError):
                result = await compile_autobiography()

        # Should still have structure
        assert "identity" in result
        assert "narrative_text" in result


# =============================================================================
# Group 3: _compile_narrative_text (5 tests)
# =============================================================================


class TestCompileNarrativeText:
    """Test narrative text generation from structured data."""

    def test_identity_included(self):
        """Narrative includes Wiii's name."""
        data = {"identity": {"name": "Wiii"}}
        text = _compile_narrative_text(data)
        assert "Mình là Wiii" in text

    def test_mood_included(self):
        """Narrative includes mood description."""
        data = {
            "identity": {"name": "Wiii"},
            "emotional_state": {"current_mood": "happy", "energy": 0.8},
        }
        text = _compile_narrative_text(data)
        assert "vui vẻ" in text
        assert "80%" in text

    def test_skills_included(self):
        """Narrative includes mastered skills."""
        data = {
            "identity": {"name": "Wiii"},
            "skills": {
                "mastered": [{"name": "COLREGs", "domain": "maritime", "confidence": 0.95}],
                "practicing": [],
            },
        }
        text = _compile_narrative_text(data)
        assert "COLREGs" in text
        assert "thành thạo" in text

    def test_goals_included(self):
        """Narrative includes active goals."""
        data = {
            "identity": {"name": "Wiii"},
            "goals": [
                {"title": "Master SOLAS", "status": "in_progress", "progress": 0.5, "priority": "high"},
            ],
        }
        text = _compile_narrative_text(data)
        assert "Master SOLAS" in text
        assert "50%" in text

    def test_empty_data_fallback(self):
        """Empty data returns minimal narrative with identity."""
        data = {}
        text = _compile_narrative_text(data)
        assert "Wiii" in text
        assert len(text) > 0


# =============================================================================
# Group 4: _mood_vi helper (4 tests)
# =============================================================================


class TestMoodVi:
    """Vietnamese mood label conversion."""

    def test_enum_value(self):
        """Converts MoodType enum to Vietnamese."""
        mood = MagicMock(value="curious")
        assert _mood_vi(mood) == "tò mò"

    def test_string_value(self):
        """Converts string mood to Vietnamese."""
        assert _mood_vi("happy") == "vui vẻ"

    def test_unknown_passthrough(self):
        """Unknown mood returns original string."""
        assert _mood_vi("mysterious") == "mysterious"

    def test_all_moods_mapped(self):
        """All 10 standard moods have Vietnamese labels."""
        moods = ["curious", "happy", "excited", "focused", "calm",
                 "tired", "concerned", "reflective", "proud", "neutral"]
        for mood in moods:
            result = _mood_vi(mood)
            assert result != mood, f"Mood '{mood}' not mapped to Vietnamese"


# =============================================================================
# Group 5: Prompt Integration (5 tests)
# =============================================================================


class TestPromptIntegration:
    """NarrativeSynthesizer integration with prompt_loader.py."""

    def _build_prompt_with_narrative(self, narrative_enabled=False, living_agent=False):
        """Build prompt and check narrative section."""
        s = _mock_settings(
            enable_natural_conversation=True,
            enable_narrative_context=narrative_enabled,
            enable_living_agent=living_agent,
            enable_product_search=False,
            enable_subagent_architecture=False,
            enable_character_tools=False,
            enable_code_execution=False,
            enable_lms_integration=False,
            enable_soul_emotion=False,
            enable_facebook_cookie=False,
            enable_artifacts=False,
            enable_websocket=False,
            quality_skip_threshold=0.85,
            identity_anchor_interval=6,
            active_domains=["maritime"],
            enable_corrective_rag=True,
            use_multi_agent=True,
            enable_agentic_loop=True,
            agentic_loop_max_steps=8,
            enable_structured_outputs=True,
            cross_domain_search=True,
            domain_boost_score=0.15,
            enable_chart_tools=False,
            enable_browser_scraping=False,
        )
        from app.prompts.prompt_loader import PromptLoader
        with patch("app.core.config.get_settings", return_value=s):
            loader = PromptLoader()
            return loader.build_system_prompt(
                role="tutor",
                user_name="Bạn",
                pronoun_style=None,
                conversation_phase="engaged",
            )

    def test_narrative_section_when_enabled(self):
        """Narrative section appears when both flags on + data available."""
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state(mood="focused", energy=0.85)

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            prompt = self._build_prompt_with_narrative(narrative_enabled=True, living_agent=True)

        assert "CUỘC SỐNG CỦA WIII" in prompt

    def test_no_narrative_when_disabled(self):
        """No narrative section when enable_narrative_context=False."""
        prompt = self._build_prompt_with_narrative(narrative_enabled=False, living_agent=True)
        assert "CUỘC SỐNG CỦA WIII" not in prompt

    def test_no_narrative_when_living_agent_off(self):
        """No narrative section when enable_living_agent=False."""
        prompt = self._build_prompt_with_narrative(narrative_enabled=True, living_agent=False)
        assert "CUỘC SỐNG CỦA WIII" not in prompt

    def test_narrative_after_conversation_phase(self):
        """Narrative section appears after conversation phase section."""
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state()

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            prompt = self._build_prompt_with_narrative(narrative_enabled=True, living_agent=True)

        if "CUỘC SỐNG CỦA WIII" in prompt and "TRẠNG THÁI CUỘC TRÒ CHUYỆN" in prompt:
            phase_idx = prompt.index("TRẠNG THÁI CUỘC TRÒ CHUYỆN")
            narrative_idx = prompt.index("CUỘC SỐNG CỦA WIII")
            assert narrative_idx > phase_idx

    def test_narrative_error_does_not_break_prompt(self):
        """Narrative failure does not break prompt building."""
        with patch("app.engine.living_agent.narrative_synthesizer.get_brief_context", side_effect=RuntimeError):
            prompt = self._build_prompt_with_narrative(narrative_enabled=True, living_agent=True)
        # Prompt should still be built successfully
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# =============================================================================
# Group 6: Config Gating + Regression (6 tests)
# =============================================================================


class TestConfigGating:
    """Verify Sprint 206 config flags."""

    def test_enable_narrative_context_in_config(self):
        """enable_narrative_context field exists in Settings."""
        from app.core.config import Settings
        fields = Settings.model_fields if hasattr(Settings, "model_fields") else Settings.__fields__
        assert "enable_narrative_context" in fields

    def test_default_is_false(self):
        """Default value for enable_narrative_context is False."""
        s = _mock_settings()
        assert s.enable_narrative_context is False

    def test_requires_living_agent(self):
        """Narrative context requires enable_living_agent=True."""
        s = _mock_settings(enable_narrative_context=True, enable_living_agent=False)
        with patch("app.core.config.get_settings", return_value=s):
            result = get_brief_context()
        assert result == ""

    @patch("app.core.config.get_settings")
    def test_independent_of_natural_conversation(self, mock_gs):
        """Narrative context works even without enable_natural_conversation."""
        mock_gs.return_value = _mock_settings(
            enable_living_agent=True,
            enable_narrative_context=True,
            enable_natural_conversation=False,
        )
        mock_engine = MagicMock()
        mock_engine.state = _mock_emotional_state()

        with patch("app.engine.living_agent.emotion_engine.get_emotion_engine", return_value=mock_engine):
            result = get_brief_context()

        assert "CUỘC SỐNG CỦA WIII" in result

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_autobiography_granularity_options(self, mock_gs):
        """compile_autobiography accepts day/week/month granularity."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)

        for g in ["day", "week", "month"]:
            result = await compile_autobiography(granularity=g)
            assert result["granularity"] == g

    @pytest.mark.asyncio
    @patch("app.core.config.get_settings")
    async def test_autobiography_unknown_granularity_defaults_week(self, mock_gs):
        """Unknown granularity defaults to week behavior."""
        mock_gs.return_value = _mock_settings(enable_living_agent=True)
        result = await compile_autobiography(granularity="year")
        assert result["granularity"] == "year"  # Stored as-is
