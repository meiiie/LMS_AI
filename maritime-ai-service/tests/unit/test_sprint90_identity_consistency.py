"""
Sprint 90 Tests — Identity Consistency

Changes verified:
1. All agent YAML names unified to "Wiii"
2. Memory agent loads identity from YAML (not hardcoded)
3. tutor.yaml must_not → avoid (suggestion-based)
4. Anti-repetition rules deduplicated (single source in wiii_identity.yaml)
5. RAG "Bông" fix — avoid list includes pet name confusion
6. _shared.yaml common_directives uses "avoid" not "must_not"
"""

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch


# =========================================================================
# Paths
# =========================================================================
PROMPTS_DIR = Path(__file__).parent.parent.parent / "app" / "prompts"
MARITIME_DIR = Path(__file__).parent.parent.parent / "app" / "domains" / "maritime" / "prompts"


# =========================================================================
# TestUnifiedAgentNames — All agents named "Wiii"
# =========================================================================

class TestUnifiedAgentNames:
    """Sprint 90: All agent YAML files must use name 'Wiii'."""

    @pytest.fixture
    def platform_yamls(self):
        """Load all platform agent YAML files."""
        agents_dir = PROMPTS_DIR / "agents"
        result = {}
        for f in agents_dir.glob("*.yaml"):
            with open(f, "r", encoding="utf-8") as fh:
                result[f.stem] = yaml.safe_load(fh)
        return result

    @pytest.fixture
    def maritime_yamls(self):
        """Load all maritime overlay YAML files."""
        agents_dir = MARITIME_DIR / "agents"
        result = {}
        for f in agents_dir.glob("*.yaml"):
            with open(f, "r", encoding="utf-8") as fh:
                result[f.stem] = yaml.safe_load(fh)
        return result

    def test_platform_tutor_name_is_wiii(self, platform_yamls):
        assert platform_yamls["tutor"]["agent"]["name"] == "Wiii"

    def test_platform_rag_name_is_wiii(self, platform_yamls):
        assert platform_yamls["rag"]["agent"]["name"] == "Wiii"

    def test_platform_memory_name_is_wiii(self, platform_yamls):
        assert platform_yamls["memory"]["agent"]["name"] == "Wiii"

    def test_platform_assistant_name_is_wiii(self, platform_yamls):
        assert platform_yamls["assistant"]["agent"]["name"] == "Wiii"

    def test_maritime_tutor_name_is_wiii(self, maritime_yamls):
        assert maritime_yamls["tutor"]["agent"]["name"] == "Wiii"

    def test_maritime_rag_name_is_wiii(self, maritime_yamls):
        assert maritime_yamls["rag"]["agent"]["name"] == "Wiii"

    def test_maritime_memory_name_is_wiii(self, maritime_yamls):
        assert maritime_yamls["memory"]["agent"]["name"] == "Wiii"

    def test_maritime_assistant_name_is_wiii(self, maritime_yamls):
        assert maritime_yamls["assistant"]["agent"]["name"] == "Wiii"

    def test_no_captain_ai_in_any_yaml(self, platform_yamls, maritime_yamls):
        """Ensure 'Captain AI' is completely removed."""
        all_yamls = {**platform_yamls, **maritime_yamls}
        for name, config in all_yamls.items():
            agent_name = config.get("agent", {}).get("name", "")
            assert "Captain" not in agent_name, f"{name} still has 'Captain' in name"

    def test_no_maritime_knowledge_agent(self, maritime_yamls):
        """Ensure 'Maritime Knowledge Agent' is completely removed."""
        for name, config in maritime_yamls.items():
            agent_name = config.get("agent", {}).get("name", "")
            assert "Knowledge Agent" not in agent_name, f"{name} still has old name"


# =========================================================================
# TestMemoryAgentYAMLLoading — Memory agent loads from identity YAML
# =========================================================================

def _setup_memory_agent_imports():
    """Set up sys.modules to allow importing memory_agent without circular deps.

    Must be called at module level (before class methods) so that the
    mock is available when pytest first tries to import.
    """
    import sys
    import types
    from unittest.mock import MagicMock

    svc_key = "app.services.chat_service"
    if svc_key not in sys.modules:
        mock_mod = types.ModuleType(svc_key)
        mock_mod.ChatService = MagicMock
        mock_mod.get_chat_service = MagicMock()
        sys.modules[svc_key] = mock_mod


# Run BEFORE any test class that imports memory_agent
_setup_memory_agent_imports()


class TestMemoryAgentYAMLLoading:
    """Sprint 90: Memory agent loads identity from wiii_identity.yaml."""

    def test_build_memory_response_prompt_exists(self):
        """_build_memory_response_prompt function exists."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        assert callable(_build_memory_response_prompt)

    def test_build_memory_response_prompt_returns_string(self):
        """_build_memory_response_prompt returns a non-empty string."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        result = _build_memory_response_prompt()
        assert isinstance(result, str)
        assert len(result) > 50

    def test_build_memory_response_prompt_has_wiii(self):
        """Prompt includes 'Wiii' from identity YAML."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        result = _build_memory_response_prompt()
        assert "Wiii" in result

    def test_build_memory_response_prompt_has_emoji(self):
        """Prompt includes emoji guidance."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        result = _build_memory_response_prompt()
        assert "emoji" in result.lower() or "⚓" in result

    def test_build_memory_response_prompt_has_behavior_rules(self):
        """Prompt includes memory-specific behavior rules."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        result = _build_memory_response_prompt()
        assert "ghi nhớ" in result.lower() or "CỤ THỂ" in result

    def test_build_memory_response_prompt_no_greeting(self):
        """Prompt tells not to start with greeting."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        result = _build_memory_response_prompt()
        assert "KHÔNG bắt đầu bằng" in result

    def test_memory_behavior_rules_constant(self):
        """_MEMORY_BEHAVIOR_RULES constant exists and has key rules."""
        from app.engine.multi_agent.agents.memory_agent import _MEMORY_BEHAVIOR_RULES
        assert "CỤ THỂ" in _MEMORY_BEHAVIOR_RULES
        assert "CẬP NHẬT" in _MEMORY_BEHAVIOR_RULES
        assert "tiếng Việt" in _MEMORY_BEHAVIOR_RULES

    def test_build_prompt_fallback_on_import_error(self):
        """Falls back gracefully if PromptLoader unavailable."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        # Lazy import inside function body → patch at source module
        with patch(
            "app.prompts.prompt_loader.get_prompt_loader",
            side_effect=Exception("YAML unavailable"),
        ):
            result = _build_memory_response_prompt()
        # Should fallback to inline defaults
        assert "Wiii" in result
        assert isinstance(result, str)


# =========================================================================
# TestSuggestionBasedPrompts — must_not → avoid conversion
# =========================================================================

class TestSuggestionBasedPrompts:
    """Sprint 90: All YAML files use 'avoid' instead of 'must_not'."""

    def test_platform_tutor_uses_avoid(self):
        """Platform tutor.yaml uses 'avoid' not 'must_not'."""
        path = PROMPTS_DIR / "agents" / "tutor.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        directives = config.get("directives", {})
        assert "avoid" in directives, "tutor.yaml should have 'avoid' key"
        assert "must_not" not in directives, "tutor.yaml should NOT have 'must_not'"

    def test_maritime_tutor_no_must_not(self):
        """Maritime tutor.yaml (minimal overlay) should NOT have 'must_not'.
        Sprint 92: Directives inherited from platform via merge."""
        path = MARITIME_DIR / "agents" / "tutor.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        directives = config.get("directives", {})
        assert "must_not" not in directives

    def test_shared_yaml_uses_avoid(self):
        """_shared.yaml common_directives uses 'avoid' not 'must_not'."""
        path = PROMPTS_DIR / "base" / "_shared.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        directives = config.get("common_directives", {})
        assert "avoid" in directives, "_shared.yaml should have 'avoid'"
        assert "must_not" not in directives, "_shared.yaml should NOT have 'must_not'"

    def test_identity_yaml_avoid_has_pet_name_rule(self):
        """wiii_identity.yaml avoid list includes pet name confusion rule."""
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        avoid = config["identity"]["response_style"]["avoid"]
        pet_rule_found = any("thú cưng" in item for item in avoid)
        assert pet_rule_found, "Should have rule about not calling user by pet name"

    def test_identity_yaml_avoid_has_follow_up_rule(self):
        """wiii_identity.yaml avoid list includes follow-up greeting rule."""
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        avoid = config["identity"]["response_style"]["avoid"]
        followup_rule = any("follow-up" in item for item in avoid)
        assert followup_rule, "Should have rule about no greeting on follow-up"


# =========================================================================
# TestAntiRepetitionDedup — Rules not duplicated in prompt_loader
# =========================================================================

class TestAntiRepetitionDedup:
    """Sprint 90: Anti-repetition rules in ONE place only."""



    def test_identity_yaml_is_single_source(self):
        """wiii_identity.yaml has the avoid rules (single source of truth)."""
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        avoid = config["identity"]["response_style"]["avoid"]
        # Should have the "À," rule
        a_comma_rule = any("À," in item for item in avoid)
        assert a_comma_rule, "Identity YAML must have the 'À,' avoid rule"

    def test_build_system_prompt_still_has_identity_section(self):
        """build_system_prompt still injects identity YAML rules."""
        from app.prompts.prompt_loader import PromptLoader
        prompt = PromptLoader().build_system_prompt(role="student")
        assert "WIII LIVING CORE CARD" in prompt or "CỐT LÕI NHÂN VẬT" in prompt, \
            "Identity section must still be injected"
        assert "GIỌNG VĂN" in prompt or "CÁCH WIII HIỆN DIỆN" in prompt, \
            "Style guidance must still be injected"


# =========================================================================
# TestIdentityYAMLIntegrity — Overall identity file correctness
# =========================================================================

class TestIdentityYAMLIntegrity:
    """Verify wiii_identity.yaml has all required fields after Sprint 90."""

    @pytest.fixture
    def identity(self):
        path = PROMPTS_DIR / "wiii_identity.yaml"
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_has_name(self, identity):
        assert identity["identity"]["name"] == "Wiii"

    def test_has_personality_summary(self, identity):
        assert "đáng yêu" in identity["identity"]["personality"]["summary"].lower()

    def test_has_traits(self, identity):
        traits = identity["identity"]["personality"]["traits"]
        assert len(traits) >= 5

    def test_has_emoji_usage(self, identity):
        assert "emoji" in identity["identity"]["voice"]["emoji_usage"].lower()

    def test_has_suggestions(self, identity):
        suggestions = identity["identity"]["response_style"]["suggestions"]
        assert len(suggestions) >= 5

    def test_has_avoid_list(self, identity):
        avoid = identity["identity"]["response_style"]["avoid"]
        assert len(avoid) >= 7  # 5 original + 2 new (Sprint 90)

    def test_has_identity_anchor(self, identity):
        anchor = identity["identity"]["identity_anchor"]
        assert "Wiii" in anchor

    def test_avoid_count_is_current_contract(self, identity):
        """Avoid list can grow as identity quality improves, but core rules remain."""
        avoid = identity["identity"]["response_style"]["avoid"]
        assert len(avoid) >= 7
        assert any("thú cưng" in item for item in avoid)
        assert any("follow-up" in item for item in avoid)
