"""Issue #110 — NVIDIA NIM provider wiring.

Verifies the alias-based registration of NVIDIA NIM as an OpenAI-compatible
target without exercising the live network. Mirrors the OpenRouter alias
pattern that already ships in the runtime.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestNvidiaRegistry:
    def test_nvidia_appears_in_supported_provider_names(self):
        from app.engine.llm_provider_registry import (
            SUPPORTED_PROVIDER_NAMES,
            is_supported_provider,
        )
        assert "nvidia" in SUPPORTED_PROVIDER_NAMES
        assert is_supported_provider("nvidia") is True

    def test_create_provider_returns_openai_provider_with_nvidia_alias(self):
        from app.engine.llm_provider_registry import create_provider
        from app.engine.llm_providers import OpenAIProvider

        provider = create_provider("nvidia")
        assert isinstance(provider, OpenAIProvider)
        assert provider.name == "nvidia"


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

class TestNvidiaResolvers:
    def test_default_models_are_current_qwen_targets(self):
        from app.engine.model_catalog import (
            NVIDIA_DEFAULT_MODEL,
            NVIDIA_DEFAULT_MODEL_ADVANCED,
            get_all_static_chat_models,
        )

        assert NVIDIA_DEFAULT_MODEL == "qwen/qwen3-next-80b-a3b-instruct"
        assert NVIDIA_DEFAULT_MODEL_ADVANCED == "qwen/qwen3-next-80b-a3b-thinking"
        assert NVIDIA_DEFAULT_MODEL in get_all_static_chat_models()["nvidia"]
        assert NVIDIA_DEFAULT_MODEL_ADVANCED in get_all_static_chat_models()["nvidia"]

    def test_api_key_resolves_from_settings(self):
        from app.engine.openai_compatible_credentials import resolve_nvidia_api_key

        settings_obj = SimpleNamespace(nvidia_api_key="nvapi-test-key")
        assert resolve_nvidia_api_key(settings_obj) == "nvapi-test-key"

    def test_api_key_resolves_to_none_when_unset(self):
        from app.engine.openai_compatible_credentials import resolve_nvidia_api_key

        settings_obj = SimpleNamespace(nvidia_api_key=None)
        assert resolve_nvidia_api_key(settings_obj) is None

    def test_base_url_default_when_unset(self):
        from app.engine.model_catalog import NVIDIA_DEFAULT_BASE_URL
        from app.engine.openai_compatible_credentials import resolve_nvidia_base_url

        settings_obj = SimpleNamespace(nvidia_base_url=None)
        assert resolve_nvidia_base_url(settings_obj) == NVIDIA_DEFAULT_BASE_URL

    def test_base_url_explicit_override(self):
        from app.engine.openai_compatible_credentials import resolve_nvidia_base_url

        settings_obj = SimpleNamespace(
            nvidia_base_url="https://custom.nvidia.example.com/v1"
        )
        assert (
            resolve_nvidia_base_url(settings_obj)
            == "https://custom.nvidia.example.com/v1"
        )

    def test_model_defaults(self):
        from app.engine.model_catalog import (
            NVIDIA_DEFAULT_MODEL,
            NVIDIA_DEFAULT_MODEL_ADVANCED,
        )
        from app.engine.openai_compatible_credentials import (
            resolve_nvidia_model,
            resolve_nvidia_model_advanced,
        )

        settings_obj = SimpleNamespace(
            nvidia_model=None, nvidia_model_advanced=None
        )
        assert resolve_nvidia_model(settings_obj) == NVIDIA_DEFAULT_MODEL
        assert (
            resolve_nvidia_model_advanced(settings_obj)
            == NVIDIA_DEFAULT_MODEL_ADVANCED
        )

    def test_credentials_available_helper(self):
        from app.engine.openai_compatible_credentials import (
            nvidia_credentials_available,
        )

        assert nvidia_credentials_available(SimpleNamespace(nvidia_api_key="k")) is True
        assert nvidia_credentials_available(SimpleNamespace(nvidia_api_key=None)) is False

    def test_runtime_audit_selected_models_include_nvidia(self):
        from app.services.llm_runtime_audit_snapshot_support import (
            get_selected_models_impl,
        )

        settings_obj = SimpleNamespace(
            llm_provider="nvidia",
            openai_base_url=None,
            openai_model="gpt-test",
            openai_model_advanced="gpt-test-advanced",
            openrouter_model="router-test",
            openrouter_model_advanced="router-test-advanced",
            nvidia_model="deepseek-ai/deepseek-v4-flash",
            nvidia_model_advanced="deepseek-ai/deepseek-v4-pro",
            google_model="gemini-test",
            zhipu_model="glm-test",
            zhipu_model_advanced="glm-test-advanced",
            ollama_model="qwen-test",
        )

        selected = get_selected_models_impl(
            settings_obj=settings_obj,
            resolve_openai_catalog_provider_fn=lambda **_: "openai",
            google_default_model="gemini-default",
            openai_default_model="openai-default",
            openai_default_model_advanced="openai-advanced-default",
            zhipu_default_model="glm-default",
            zhipu_default_model_advanced="glm-advanced-default",
        )

        assert selected["nvidia"]["model"] == "deepseek-ai/deepseek-v4-flash"
        assert selected["nvidia"]["advanced"] == "deepseek-ai/deepseek-v4-pro"


class TestNvidiaNativeStreaming:
    def test_nvidia_is_supported_by_native_openai_compatible_streaming(self):
        from app.engine.multi_agent.openai_stream_runtime import (
            _supports_native_answer_streaming_impl,
        )

        assert _supports_native_answer_streaming_impl("nvidia") is True

    def test_nvidia_stream_model_resolves_flash_and_pro_by_tier(self):
        from app.engine.multi_agent import openai_stream_runtime

        llm = SimpleNamespace(_wiii_provider_name="nvidia")
        with patch.object(
            openai_stream_runtime,
            "settings",
            SimpleNamespace(
                nvidia_model="deepseek-ai/deepseek-v4-flash",
                nvidia_model_advanced="deepseek-ai/deepseek-v4-pro",
            ),
        ):
            assert (
                openai_stream_runtime._resolve_openai_stream_model_name_impl(
                    llm, "nvidia", "moderate"
                )
                == "deepseek-ai/deepseek-v4-flash"
            )
            assert (
                openai_stream_runtime._resolve_openai_stream_model_name_impl(
                    llm, "nvidia", "deep"
                )
                == "deepseek-ai/deepseek-v4-pro"
            )

    def test_nvidia_stream_client_uses_nvidia_credentials(self):
        from app.engine.multi_agent import openai_stream_runtime

        captured: dict = {}

        def _fake_async_openai(**kwargs):
            captured.update(kwargs)
            return object()

        with patch.object(
            openai_stream_runtime,
            "settings",
            SimpleNamespace(
                nvidia_api_key="nvapi-test-key",
                nvidia_base_url="https://nvidia.example.test/v1",
            ),
        ), patch("openai.AsyncOpenAI", new=_fake_async_openai):
            client = openai_stream_runtime._create_openai_compatible_stream_client_impl(
                "nvidia"
            )

        assert client is not None
        assert captured == {
            "api_key": "nvapi-test-key",
            "base_url": "https://nvidia.example.test/v1",
        }

    def test_direct_runtime_payload_wrapper_flattens_langchain_content(self):
        from app.engine.multi_agent import direct_runtime_bindings

        message = SimpleNamespace(
            type="human",
            content=[
                {"text": "Xin chao"},
                {"content": "Wiii"},
            ],
        )

        assert direct_runtime_bindings._langchain_message_to_openai_payload(message) == {
            "role": "user",
            "content": "Xin chao\nWiii",
        }


# ---------------------------------------------------------------------------
# OpenAIProvider — nvidia alias behavior
# ---------------------------------------------------------------------------

class TestOpenAIProviderWithNvidiaAlias:
    def test_is_configured_true_with_nvidia_api_key(self):
        from app.engine.llm_providers import OpenAIProvider

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(nvidia_api_key="nvapi-x"),
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            assert provider.is_configured() is True

    def test_is_configured_false_without_nvidia_api_key(self):
        from app.engine.llm_providers import OpenAIProvider

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(nvidia_api_key=None),
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            assert provider.is_configured() is False

    def test_is_configured_nvidia_alias_does_not_fall_back_to_openai_key(self):
        """Nvidia alias must NOT report configured just because openai_api_key is set."""
        from app.engine.llm_providers import OpenAIProvider

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(
                nvidia_api_key=None,
                openai_api_key="sk-openai-only",
                openrouter_api_key=None,
            ),
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            assert provider.is_configured() is False

    def test_create_instance_picks_nvidia_endpoint(self):
        """With alias=nvidia, the WiiiChatModel must be built with the NVIDIA URL + key + model."""
        from app.engine.llm_providers import OpenAIProvider
        from app.engine.model_catalog import (
            NVIDIA_DEFAULT_BASE_URL,
            NVIDIA_DEFAULT_MODEL,
        )

        captured: dict = {}

        def _fake_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(
                nvidia_api_key="nvapi-test-key",
                nvidia_base_url=None,
                nvidia_model=None,
                nvidia_model_advanced=None,
                openai_api_key=None,
                openai_base_url=None,
            ),
        ), patch(
            "app.engine.llm_providers.openai_provider.WiiiChatModel",
            new=_fake_chat_model,
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            provider.create_instance(tier="light")

        assert captured["model"] == NVIDIA_DEFAULT_MODEL
        assert captured["api_key"] == "nvapi-test-key"
        assert captured["base_url"] == NVIDIA_DEFAULT_BASE_URL

    def test_create_instance_picks_advanced_model_for_deep_tier(self):
        from app.engine.llm_providers import OpenAIProvider
        from app.engine.model_catalog import NVIDIA_DEFAULT_MODEL_ADVANCED

        captured: dict = {}

        def _fake_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(
                nvidia_api_key="nvapi-key",
                nvidia_base_url=None,
                nvidia_model=None,
                nvidia_model_advanced=None,
                openai_api_key=None,
                openai_base_url=None,
            ),
        ), patch(
            "app.engine.llm_providers.openai_provider.WiiiChatModel",
            new=_fake_chat_model,
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            provider.create_instance(tier="deep")

        assert captured["model"] == NVIDIA_DEFAULT_MODEL_ADVANCED

    def test_create_instance_does_not_emit_openrouter_extra_body(self):
        """NVIDIA path is plain OpenAI-compatible; openrouter_extra_body must not be added."""
        from app.engine.llm_providers import OpenAIProvider

        captured: dict = {}

        def _fake_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch.object(
            __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
            "settings",
            SimpleNamespace(
                nvidia_api_key="nvapi",
                nvidia_base_url=None,
                nvidia_model=None,
                nvidia_model_advanced=None,
                openai_api_key=None,
                openai_base_url=None,
            ),
        ), patch(
            "app.engine.llm_providers.openai_provider.WiiiChatModel",
            new=_fake_chat_model,
        ):
            provider = OpenAIProvider(provider_alias="nvidia")
            provider.create_instance(tier="moderate")

        # extra_body is only set for o-series models or openrouter routing
        model_kwargs = captured.get("model_kwargs", {})
        assert "extra_body" not in model_kwargs

    def test_create_instance_avoids_degraded_flash_model(self):
        from app.engine.llm_model_health import (
            record_model_failure,
            reset_model_health_state,
        )
        from app.engine.llm_providers import OpenAIProvider

        captured: dict = {}

        def _fake_chat_model(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        try:
            record_model_failure(
                "nvidia",
                "deepseek-ai/deepseek-v4-flash",
                reason_code="timeout",
                timeout_seconds=0.01,
            )
            with patch.object(
                __import__("app.engine.llm_providers.openai_provider", fromlist=["settings"]),
                "settings",
                SimpleNamespace(
                    nvidia_api_key="nvapi",
                    nvidia_base_url=None,
                    nvidia_model="deepseek-ai/deepseek-v4-flash",
                    nvidia_model_advanced="deepseek-ai/deepseek-v4-pro",
                    openai_api_key=None,
                    openai_base_url=None,
                ),
            ), patch(
                "app.engine.llm_providers.openai_provider.WiiiChatModel",
                new=_fake_chat_model,
            ):
                provider = OpenAIProvider(provider_alias="nvidia")
                provider.create_instance(tier="moderate")

            assert captured["model"] == "deepseek-ai/deepseek-v4-pro"
        finally:
            reset_model_health_state()

    def test_openai_compatible_aliases_use_distinct_circuit_breakers(self):
        from app.engine.llm_providers import OpenAIProvider

        with patch(
            "app.engine.llm_providers.openai_provider._get_openai_compatible_circuit_breaker",
            side_effect=lambda alias: f"cb:{alias}",
        ):
            assert OpenAIProvider(provider_alias="openai").get_circuit_breaker() == "cb:openai"
            assert OpenAIProvider(provider_alias="openrouter").get_circuit_breaker() == "cb:openrouter"
            assert OpenAIProvider(provider_alias="nvidia").get_circuit_breaker() == "cb:nvidia"


# ---------------------------------------------------------------------------
# Cross-cutting safety
# ---------------------------------------------------------------------------

class TestNoRegression:
    def test_existing_openai_alias_still_works(self):
        from app.engine.llm_provider_registry import create_provider

        provider = create_provider("openai")
        assert provider.name == "openai"

    def test_existing_openrouter_alias_still_works(self):
        from app.engine.llm_provider_registry import create_provider

        provider = create_provider("openrouter")
        assert provider.name == "openrouter"

    def test_unknown_provider_still_raises(self):
        from app.engine.llm_provider_registry import get_provider_class

        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_class("not-a-real-provider")
