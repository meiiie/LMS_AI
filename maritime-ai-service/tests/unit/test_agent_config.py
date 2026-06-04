"""
Tests for AgentConfigRegistry — Sprint 69: Per-Agent Provider Config.

Tests cover:
- AgentNodeConfig defaults and custom values
- AgentConfigRegistry initialization, get_config, get_llm, reset
- JSON overrides parsing
- All default node configs present
"""

import json
import sys
import types
from types import SimpleNamespace
import pytest
from unittest.mock import patch, MagicMock

# Break circular import: multi_agent.__init__ → graph → agents → tutor_node
# → services.__init__ → chat_service → multi_agent.graph
_cs_key = "app.services.chat_service"
_svc_key = "app.services"
_had_cs = _cs_key in sys.modules
_had_svc = _svc_key in sys.modules
_orig_cs = sys.modules.get(_cs_key)
if not _had_cs:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs

from app.engine.multi_agent.agent_config import (
    AgentNodeConfig,
    AgentConfigRegistry,
    _DEFAULT_CONFIGS,
)

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# =============================================================================
# TestAgentNodeConfig
# =============================================================================


class TestAgentNodeConfig:
    """Tests for AgentNodeConfig dataclass."""

    def test_defaults(self):
        config = AgentNodeConfig("test_node")
        assert config.node_id == "test_node"
        assert config.provider == ""
        assert config.model is None
        assert config.tier == "moderate"
        assert config.temperature == 0.5
        assert config.max_agentic_steps == 5
        assert config.enable_thinking is True
        assert config.enable_agentic_loop is False

    def test_custom_provider(self):
        config = AgentNodeConfig("test", provider="openai")
        assert config.provider == "openai"

    def test_custom_tier(self):
        config = AgentNodeConfig("test", tier="deep")
        assert config.tier == "deep"

    def test_enable_agentic_loop(self):
        config = AgentNodeConfig("test", enable_agentic_loop=True)
        assert config.enable_agentic_loop is True

    def test_custom_temperature(self):
        config = AgentNodeConfig("test", temperature=0.0)
        assert config.temperature == 0.0

    def test_custom_model(self):
        config = AgentNodeConfig("test", model="gemini-3.1-flash-lite-preview")
        assert config.model == "gemini-3.1-flash-lite-preview"

    def test_custom_max_steps(self):
        config = AgentNodeConfig("test", max_agentic_steps=10)
        assert config.max_agentic_steps == 10


# =============================================================================
# TestAgentConfigRegistry
# =============================================================================


class TestAgentConfigRegistry:
    """Tests for AgentConfigRegistry singleton."""

    def setup_method(self):
        AgentConfigRegistry.reset()

    def teardown_method(self):
        AgentConfigRegistry.reset()

    def test_initialize_loads_defaults(self):
        AgentConfigRegistry.initialize()
        assert AgentConfigRegistry._initialized is True
        assert len(AgentConfigRegistry._configs) == len(_DEFAULT_CONFIGS)

    def test_get_config_returns_matching(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.node_id == "tutor_agent"
        assert config.tier == "moderate"

    def test_get_unknown_fallback(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("unknown_node")
        assert config.node_id == "unknown_node"
        assert config.tier == "moderate"  # default

    def test_get_llm_delegates_to_pool(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[],
        ), patch(
            "app.engine.llm_pool.get_llm_moderate",
            return_value=mock_llm,
        ) as mock_get:
            result = AgentConfigRegistry.get_llm("tutor_agent")
            mock_get.assert_called_once()
            assert result == mock_llm

    def test_get_llm_light_for_supervisor(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[],
        ), patch(
            "app.engine.llm_pool.get_llm_light",
            return_value=mock_llm,
        ) as mock_get:
            result = AgentConfigRegistry.get_llm("supervisor")
            mock_get.assert_called_once()
            assert result == mock_llm

    def test_get_llm_moderate_for_rag(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[],
        ), patch(
            "app.engine.llm_pool.get_llm_moderate",
            return_value=mock_llm,
        ) as mock_get:
            result = AgentConfigRegistry.get_llm("rag_agent")
            mock_get.assert_called_once()
            assert result == mock_llm

    def test_reset_clears_state(self):
        AgentConfigRegistry.initialize()
        assert AgentConfigRegistry._initialized is True
        AgentConfigRegistry.reset()
        assert AgentConfigRegistry._initialized is False
        assert len(AgentConfigRegistry._configs) == 0

    def test_override_json_changes_tier(self):
        overrides = json.dumps({"tutor_agent": {"tier": "deep"}})
        AgentConfigRegistry.initialize(overrides)
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.tier == "deep"

    def test_override_json_changes_provider(self):
        overrides = json.dumps({"supervisor": {"provider": "openai"}})
        AgentConfigRegistry.initialize(overrides)
        config = AgentConfigRegistry.get_config("supervisor")
        assert config.provider == "openai"

    def test_invalid_json_fallback(self):
        AgentConfigRegistry.initialize("not valid json {{{")
        # Should still initialize with defaults
        assert AgentConfigRegistry._initialized is True
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.tier == "moderate"

    def test_all_defaults_present(self):
        AgentConfigRegistry.initialize()
        expected = {
            "tutor_agent", "rag_agent", "supervisor",
            "guardian", "grader", "memory", "direct", "direct_chatter",
            "direct_identity", "synthesizer",
            "code_studio_agent",
        }
        assert set(AgentConfigRegistry._configs.keys()) == expected

    def test_direct_chatter_uses_nvidia_default_model_when_nvidia_selected(self):
        from app.engine.model_catalog import NVIDIA_DEFAULT_MODEL

        mock_llm = MagicMock()
        AgentConfigRegistry.initialize()

        with patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_create:
            result = AgentConfigRegistry.get_llm(
                "direct_chatter",
                provider_override="nvidia",
            )

        assert result is mock_llm
        mock_create.assert_called_once()
        assert mock_create.call_args.args[0] == "nvidia"
        assert mock_create.call_args.args[1] == NVIDIA_DEFAULT_MODEL

    def test_direct_identity_uses_creative_profile_model_for_zhipu(self):
        mock_llm = MagicMock()
        AgentConfigRegistry.initialize()

        with patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_create:
            result = AgentConfigRegistry.get_llm(
                "direct_identity",
                provider_override="zhipu",
            )

        assert result is mock_llm
        mock_create.assert_called_once()
        assert mock_create.call_args.args[0] == "zhipu"
        assert mock_create.call_args.args[1] == "glm-5"

    def test_tutor_moderate_tier(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.tier == "moderate"
        assert config.enable_agentic_loop is True

    def test_supervisor_light_tier(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("supervisor")
        assert config.tier == "light"
        assert config.temperature == 0.3

    def test_guardian_temp_zero(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("guardian")
        assert config.temperature == 0.0
        assert config.tier == "light"

    def test_tutor_agentic_enabled(self):
        AgentConfigRegistry.initialize()
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.enable_agentic_loop is True

    def test_effort_override(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[],
        ), patch(
            "app.engine.llm_pool.get_llm_for_effort",
            return_value=mock_llm,
        ) as mock_effort:
            result = AgentConfigRegistry.get_llm("tutor_agent", effort_override="high")
            mock_effort.assert_called_once()
            assert result == mock_llm

    def test_effort_override_with_correct_default_tier(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[],
        ), patch(
            "app.engine.llm_pool.get_llm_for_effort",
            return_value=mock_llm,
        ) as mock_effort:
            AgentConfigRegistry.get_llm("direct", effort_override="medium")
            # Direct node has tier="light"
            call_args = mock_effort.call_args
            assert call_args[0][0] == "medium"
            # default_tier should be ThinkingTier.LIGHT
            from app.engine.llm_factory import ThinkingTier
            assert call_args[1]["default_tier"] == ThinkingTier.LIGHT

    def test_requested_model_uses_custom_model_factory_when_provider_is_explicit(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()

        with patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_custom:
            result = AgentConfigRegistry.get_llm(
                "direct",
                provider_override="openrouter",
                requested_model="qwen/qwen3.6-plus:free",
            )

        assert result == mock_llm
        assert mock_custom.call_args[0][:2] == ("openrouter", "qwen/qwen3.6-plus:free")

    def test_auto_provider_prefers_selectable_provider_when_default_is_disabled(self):
        from app.core.config import settings
        orig_provider = settings.llm_provider
        settings.llm_provider = "google"
        try:
            AgentConfigRegistry.initialize()
            mock_llm = MagicMock()
            with patch(
                "app.services.llm_selectability_service.get_llm_selectability_snapshot",
                return_value=[
                    SimpleNamespace(provider="google", state="disabled", configured=True, request_selectable=True, reason_code="busy"),
                    SimpleNamespace(provider="zhipu", state="selectable", configured=True, request_selectable=True, reason_code=None),
                ],
            ), patch(
                "app.engine.llm_pool.get_llm_for_provider",
                return_value=mock_llm,
            ) as mock_get_provider:
                result = AgentConfigRegistry.get_llm("direct")

            assert result == mock_llm
            assert mock_get_provider.call_args.args[0] == "zhipu"
        finally:
            settings.llm_provider = orig_provider

    def test_code_studio_auto_switches_to_zhipu_advanced_profile_when_google_is_disabled(self):
        AgentConfigRegistry.initialize()
        mock_llm = MagicMock()
        with patch(
            "app.services.llm_selectability_service.get_llm_selectability_snapshot",
            return_value=[
                SimpleNamespace(provider="google", state="disabled", configured=True, request_selectable=True, reason_code="busy"),
                SimpleNamespace(provider="zhipu", state="selectable", configured=True, request_selectable=True, reason_code=None),
            ],
        ), patch(
            "app.engine.llm_pool.get_llm_for_provider",
            return_value=mock_llm,
        ) as mock_get_provider, patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry._get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_custom:
            result = AgentConfigRegistry.get_llm("code_studio_agent")

        assert result == mock_llm
        mock_custom.assert_called_once()
        assert mock_custom.call_args.args[0] == "zhipu"
        assert mock_custom.call_args.args[1] == "glm-5"
        mock_get_provider.assert_not_called()

    def test_multiple_resets(self):
        AgentConfigRegistry.initialize()
        AgentConfigRegistry.reset()
        AgentConfigRegistry.reset()  # Should not error
        assert AgentConfigRegistry._initialized is False

    def test_auto_initialize_on_get_config(self):
        # Without explicit initialize, get_config should auto-initialize
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.node_id == "tutor_agent"
        assert AgentConfigRegistry._initialized is True

    def test_override_adds_new_node(self):
        overrides = json.dumps({"custom_node": {"tier": "deep", "provider": "ollama"}})
        AgentConfigRegistry.initialize(overrides)
        config = AgentConfigRegistry.get_config("custom_node")
        assert config.tier == "deep"
        assert config.provider == "ollama"

    def test_override_ignores_node_id_change(self):
        overrides = json.dumps({"tutor_agent": {"node_id": "hacked"}})
        AgentConfigRegistry.initialize(overrides)
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.node_id == "tutor_agent"  # Not changed

    def test_override_non_dict_values_ignored(self):
        overrides = json.dumps({"tutor_agent": "not_a_dict"})
        AgentConfigRegistry.initialize(overrides)
        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.tier == "moderate"  # Default preserved

    def test_empty_override_string(self):
        AgentConfigRegistry.initialize("")
        assert AgentConfigRegistry._initialized is True

    def test_none_override_string(self):
        AgentConfigRegistry.initialize(None)
        assert AgentConfigRegistry._initialized is True

    def test_provider_override_takes_priority_over_model_override(self):
        AgentConfigRegistry.initialize()
        mock_provider_llm = MagicMock()

        with patch(
            "app.engine.llm_pool.get_llm_for_provider",
            return_value=mock_provider_llm,
        ) as mock_get_provider, patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
        ) as mock_get_model:
            result = AgentConfigRegistry.get_llm(
                "code_studio_agent",
                provider_override="ollama",
            )

        assert result is mock_provider_llm
        mock_get_provider.assert_called_once()
        assert mock_get_provider.call_args.kwargs["strict_pin"] is True
        mock_get_model.assert_not_called()

    def test_group_profile_changes_default_provider_for_node(self):
        from app.core.config import settings
        orig_provider = settings.llm_provider
        settings.llm_provider = "google"
        try:
            mock_provider_llm = MagicMock()
            AgentConfigRegistry.initialize(
                "{}",
                {
                    "knowledge": {
                        "default_provider": "zhipu",
                        "tier": "moderate",
                        "provider_models": {},
                    }
                },
            )

            with patch(
                "app.services.llm_selectability_service.choose_best_runtime_provider",
                return_value=SimpleNamespace(provider="zhipu"),
            ), patch(
                "app.engine.llm_pool.get_llm_for_provider",
                return_value=mock_provider_llm,
            ) as mock_get_provider:
                result = AgentConfigRegistry.get_llm("tutor_agent")

            assert result is mock_provider_llm
            mock_get_provider.assert_called_once()
            assert mock_get_provider.call_args[0][0] == "zhipu"
        finally:
            settings.llm_provider = orig_provider

    def test_auto_provider_prefers_selectable_provider_before_degraded_fallback(self):
        from app.core.config import settings
        orig_provider = settings.llm_provider
        settings.llm_provider = "google"
        try:
            mock_provider_llm = MagicMock()
            AgentConfigRegistry.initialize(
                "{}",
                {
                    "knowledge": {
                        "default_provider": "google",
                        "tier": "moderate",
                        "provider_models": {},
                    }
                },
            )

            with patch(
                "app.services.llm_selectability_service.choose_best_runtime_provider",
                side_effect=[SimpleNamespace(provider="zhipu")],
            ) as mock_choose, patch(
                "app.engine.llm_pool.get_llm_for_provider",
                return_value=mock_provider_llm,
            ):
                result = AgentConfigRegistry.get_llm("tutor_agent")

            assert result is mock_provider_llm
            assert mock_choose.call_count == 1
            assert mock_choose.call_args.kwargs["allow_degraded_fallback"] is False
        finally:
            settings.llm_provider = orig_provider

    def test_auto_provider_only_uses_degraded_fallback_when_no_selectable_provider_exists(self):
        from app.core.config import settings
        orig_provider = settings.llm_provider
        settings.llm_provider = "google"
        try:
            mock_provider_llm = MagicMock()
            AgentConfigRegistry.initialize(
                "{}",
                {
                    "knowledge": {
                        "default_provider": "google",
                        "tier": "moderate",
                        "provider_models": {},
                    }
                },
            )

            with patch(
                "app.services.llm_selectability_service.choose_best_runtime_provider",
                side_effect=[None, SimpleNamespace(provider="zhipu")],
            ) as mock_choose, patch(
                "app.engine.llm_pool.get_llm_for_provider",
                return_value=mock_provider_llm,
            ):
                result = AgentConfigRegistry.get_llm("tutor_agent")

            assert result is mock_provider_llm
            assert mock_choose.call_count == 2
            assert mock_choose.call_args_list[0].kwargs["allow_degraded_fallback"] is False
            assert mock_choose.call_args_list[1].kwargs["allow_degraded_fallback"] is True
        finally:
            settings.llm_provider = orig_provider

    def test_non_strict_provider_override_keeps_provider_as_preference_not_pin(self):
        from app.core.config import settings
        orig_provider = settings.llm_provider
        settings.llm_provider = "google"
        try:
            mock_provider_llm = MagicMock()
            AgentConfigRegistry.initialize()

            with patch.object(
                AgentConfigRegistry,
                "_resolve_auto_provider",
                return_value="zhipu",
            ) as mock_resolve, patch(
                "app.engine.llm_pool.get_llm_for_provider",
                return_value=mock_provider_llm,
            ) as mock_get_provider:
                result = AgentConfigRegistry.get_llm(
                    "supervisor",
                    provider_override="zhipu",
                    strict_provider_pin=False,
                )

            assert result is mock_provider_llm
            mock_resolve.assert_called_once_with("zhipu")
            assert mock_get_provider.call_args.args[0] == "zhipu"
            assert mock_get_provider.call_args.kwargs.get("strict_pin", False) is False
        finally:
            settings.llm_provider = orig_provider

    def test_explicit_provider_pin_uses_group_specific_model_when_present(self):
        mock_llm = MagicMock()
        AgentConfigRegistry.initialize(
            "{}",
            {
                "creative": {
                    "default_provider": "google",
                    "tier": "deep",
                    "provider_models": {"zhipu": "glm-5"},
                }
            },
        )

        with patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_create:
            result = AgentConfigRegistry.get_llm(
                "code_studio_agent",
                provider_override="zhipu",
            )

        assert result is mock_llm
        mock_create.assert_called_once()
        assert mock_create.call_args.args[0] == "zhipu"
        assert mock_create.call_args.args[1] == "glm-5"

    def test_creative_defaults_keep_zhipu_advanced_mapping_when_profile_omits_provider_models(self):
        mock_llm = MagicMock()
        AgentConfigRegistry.initialize(
            "{}",
            {
                "creative": {
                    "default_provider": "google",
                    "tier": "deep",
                    "provider_models": {},
                }
            },
        )

        with patch.object(
            AgentConfigRegistry,
            "_get_or_create_model_llm_for_provider",
            return_value=mock_llm,
        ) as mock_create:
            result = AgentConfigRegistry.get_llm(
                "code_studio_agent",
                provider_override="zhipu",
            )

        assert result is mock_llm
        mock_create.assert_called_once()
        assert mock_create.call_args.args[0] == "zhipu"
        assert mock_create.call_args.args[1] == "glm-5"

    def test_explicit_provider_pin_falls_back_to_provider_default_when_group_model_missing(self):
        mock_provider_llm = MagicMock()
        AgentConfigRegistry.initialize(
            "{}",
            {
                "creative": {
                    "default_provider": "google",
                    "tier": "deep",
                    "provider_models": {},
                }
            },
        )

        with patch(
            "app.engine.llm_pool.get_llm_for_provider",
            return_value=mock_provider_llm,
        ) as mock_get_provider:
            result = AgentConfigRegistry.get_llm(
                "code_studio_agent",
                provider_override="ollama",
            )

        assert result is mock_provider_llm
        mock_get_provider.assert_called_once()
        assert mock_get_provider.call_args[0][0] == "ollama"
