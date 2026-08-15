"""
Tests for LLM Multi-Provider Failover Chain.

Sprint 11: Tests failover logic in LLMPool._create_instance():
- Primary fails → secondary kicks in
- All providers fail → RuntimeError
- Circuit breaker per provider
- Failover disabled → legacy path
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock, call

from app.engine.llm_providers.wiii_chat_model import WiiiChatModel
from app.engine.llm_pool import (
    FAILOVER_MODE_AUTO,
    FAILOVER_MODE_PINNED,
    LLMPool,
    ProviderUnavailableError,
    ResolvedLLMRoute,
    ThinkingTier,
    ainvoke_with_failover,
    get_llm_for_provider,
    resolve_primary_timeout_seconds,
)
from app.engine.llm_providers.base import LLMProvider


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset LLMPool state between tests."""
    LLMPool.reset()
    yield
    LLMPool.reset()


def _make_mock_provider(name: str, configured: bool = True, available: bool = True, fail: bool = False):
    """Create a mock LLM provider for testing.

    Note: We use MagicMock() without spec=LLMProvider because the concrete
    providers have extra methods (get_circuit_breaker, record_success, record_failure)
    not defined on the ABC.
    """
    provider = MagicMock()
    provider.name = name
    provider.is_configured.return_value = configured
    provider.is_available.return_value = available
    if fail:
        provider.create_instance.side_effect = Exception(f"{name} provider failed")
    else:
        mock_llm = MagicMock(spec=WiiiChatModel)
        mock_llm._provider_name = name  # Tag for identification
        provider.create_instance.return_value = mock_llm
    provider.get_circuit_breaker.return_value = None
    provider.record_success = AsyncMock()
    provider.record_failure = AsyncMock()
    return provider


# ============================================================================
# Failover Chain Tests
# ============================================================================


class TestFailoverChain:
    """Test the multi-provider failover chain logic."""

    @patch("app.engine.llm_pool.settings")
    def test_primary_provider_succeeds(self, mock_settings):
        """When primary provider works, use it directly."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai", "ollama"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google")
        openai = _make_mock_provider("openai")

        LLMPool._providers = {"google": google, "openai": openai}
        llm = LLMPool._create_instance("deep")

        assert llm is not None
        google.create_instance.assert_called_once()
        openai.create_instance.assert_not_called()
        assert LLMPool._active_provider == "google"

    @patch("app.engine.llm_pool.settings")
    def test_failover_to_secondary(self, mock_settings):
        """When primary fails, try secondary."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai", "ollama"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google", fail=True)
        openai = _make_mock_provider("openai")

        LLMPool._providers = {"google": google, "openai": openai}
        llm = LLMPool._create_instance("moderate")

        assert llm is not None
        google.create_instance.assert_called_once()
        openai.create_instance.assert_called_once()
        assert LLMPool._active_provider == "openai"

    @patch("app.engine.llm_pool.settings")
    def test_failover_to_tertiary(self, mock_settings):
        """When primary + secondary fail, try tertiary."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai", "ollama"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google", fail=True)
        openai = _make_mock_provider("openai", fail=True)
        ollama = _make_mock_provider("ollama")

        LLMPool._providers = {"google": google, "openai": openai, "ollama": ollama}
        llm = LLMPool._create_instance("light")

        assert llm is not None
        assert LLMPool._active_provider == "ollama"

    @patch("app.engine.llm_pool.settings")
    def test_all_providers_fail_raises_error(self, mock_settings):
        """When ALL providers fail, raise RuntimeError."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google", fail=True)
        openai = _make_mock_provider("openai", fail=True)

        LLMPool._providers = {"google": google, "openai": openai}

        with pytest.raises(RuntimeError, match="All providers failed"):
            LLMPool._create_instance("deep")

    @patch("app.engine.llm_pool.settings")
    def test_skip_unavailable_provider(self, mock_settings):
        """Skip providers where is_available() returns False (circuit open)."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google", available=False)
        openai = _make_mock_provider("openai")

        LLMPool._providers = {"google": google, "openai": openai}
        llm = LLMPool._create_instance("moderate")

        google.create_instance.assert_not_called()
        openai.create_instance.assert_called_once()
        assert LLMPool._active_provider == "openai"

    @patch("app.engine.llm_pool.settings")
    def test_no_providers_available_raises_error(self, mock_settings):
        """When no providers are available at all, raise RuntimeError."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google", available=False)
        LLMPool._providers = {"google": google}

        with pytest.raises(RuntimeError, match="no providers available"):
            LLMPool._create_instance("light")

    @patch("app.engine.llm_pool.settings")
    def test_cached_instance_returned(self, mock_settings):
        """If tier already in pool, return cached instance."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        cached_llm = MagicMock(spec=WiiiChatModel)
        LLMPool._pool["deep"] = cached_llm

        result = LLMPool._create_instance("deep")
        assert result is cached_llm


# ============================================================================
# Legacy Path Tests (Failover Disabled)
# ============================================================================


class TestLegacyPath:
    """Test behavior when failover is disabled."""

    @patch("app.engine.llm_pool.create_provider")
    @patch("app.engine.llm_pool.settings")
    def test_legacy_creates_google_provider_instance(self, mock_settings, mock_create_provider):
        """With failover disabled, create the Google provider instance."""
        mock_settings.enable_llm_failover = False
        mock_settings.llm_provider = "google"
        mock_settings.google_api_key = "test-key"
        mock_settings.google_model = "gemini-3-flash-preview"
        mock_settings.thinking_enabled = True
        mock_settings.llm_failover_chain = ["google"]
        google = _make_mock_provider("google")
        mock_create_provider.return_value = google

        LLMPool._providers = {}  # Empty providers
        llm = LLMPool._create_instance("moderate")

        assert llm is not None
        mock_create_provider.assert_called_once_with("google")
        google.create_instance.assert_called_once()
        assert LLMPool._active_provider == "google"

    @patch("app.engine.llm_pool.create_provider")
    @patch("app.engine.llm_pool.settings")
    def test_legacy_uses_provider_thinking_contract(self, mock_settings, mock_create_provider):
        mock_settings.enable_llm_failover = False
        mock_settings.llm_provider = "google"
        mock_settings.google_api_key = "test-key"
        mock_settings.google_model = "gemini-3-flash-preview"
        mock_settings.thinking_enabled = False
        mock_settings.llm_failover_chain = ["google"]
        google = _make_mock_provider("google")
        mock_create_provider.return_value = google

        LLMPool._providers = {}
        LLMPool._create_instance("light")

        call_kwargs = google.create_instance.call_args.kwargs
        assert call_kwargs["tier"] == "light"
        assert call_kwargs["thinking_budget"] == 1024
        assert call_kwargs["include_thoughts"] is True

    @patch("app.engine.llm_pool.create_provider")
    @patch("app.engine.llm_pool.settings")
    def test_legacy_failure_raises(self, mock_settings, mock_create_provider):
        mock_settings.enable_llm_failover = False
        mock_settings.llm_provider = "google"
        mock_settings.google_api_key = "test-key"
        mock_settings.google_model = "gemini-3-flash-preview"
        mock_settings.thinking_enabled = True
        mock_settings.llm_failover_chain = ["google"]
        google = _make_mock_provider("google")
        google.create_instance.side_effect = Exception("API key invalid")
        mock_create_provider.return_value = google

        LLMPool._providers = {}

        with pytest.raises(Exception, match="API key invalid"):
            LLMPool._create_instance("deep")


# ============================================================================
# Circuit Breaker per Provider Tests
# ============================================================================


class TestPerProviderCircuitBreaker:
    """Test circuit breaker integration per provider."""

    @patch("app.engine.llm_pool.settings")
    def test_provider_with_open_circuit_skipped(self, mock_settings):
        """Provider with open circuit breaker is skipped."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai"]
        mock_settings.thinking_enabled = True

        google = _make_mock_provider("google")
        google.is_available.return_value = False  # Circuit open
        openai = _make_mock_provider("openai")

        LLMPool._providers = {"google": google, "openai": openai}
        llm = LLMPool._create_instance("moderate")

        google.create_instance.assert_not_called()
        openai.create_instance.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_record_success_delegates_to_active_provider(self, mock_settings):
        """record_success() delegates to the active provider."""
        mock_settings.enable_llm_failover = True

        provider = _make_mock_provider("openai")
        LLMPool._providers = {"openai": provider}
        LLMPool._active_provider = "openai"

        await LLMPool.record_success()
        provider.record_success.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_record_failure_delegates_to_active_provider(self, mock_settings):
        """record_failure() delegates to the active provider."""
        mock_settings.enable_llm_failover = True

        provider = _make_mock_provider("google")
        LLMPool._providers = {"google": provider}
        LLMPool._active_provider = "google"

        await LLMPool.record_failure()
        provider.record_failure.assert_awaited_once()


# ============================================================================
# is_available() with Multiple Providers
# ============================================================================


class TestIsAvailableMultiProvider:
    """Test is_available with multiple providers."""

    @patch("app.engine.llm_pool.settings")
    def test_any_provider_available_returns_true(self, mock_settings):
        mock_settings.enable_llm_failover = True

        google = _make_mock_provider("google", available=False)
        openai = _make_mock_provider("openai", available=True)

        LLMPool._providers = {"google": google, "openai": openai}
        assert LLMPool.is_available() is True

    @patch("app.engine.llm_pool.settings")
    def test_no_provider_available_returns_false(self, mock_settings):
        mock_settings.enable_llm_failover = True

        google = _make_mock_provider("google", available=False)
        openai = _make_mock_provider("openai", available=False)

        LLMPool._providers = {"google": google, "openai": openai}
        assert LLMPool.is_available() is False

    @patch("app.engine.llm_pool._gemini_cb", None)
    @patch("app.engine.llm_pool.settings")
    def test_legacy_no_cb_returns_true(self, mock_settings):
        mock_settings.enable_llm_failover = False
        LLMPool._providers = {}
        assert LLMPool.is_available() is True


class _FakeAsyncLLM:
    def __init__(
        self,
        *,
        result=None,
        error: Exception | None = None,
        sleep_seconds: float = 0.0,
    ):
        self._result = result
        self._error = error
        self._sleep_seconds = sleep_seconds

    async def ainvoke(self, _messages):
        if self._sleep_seconds > 0:
            import asyncio

            await asyncio.sleep(self._sleep_seconds)
        if self._error is not None:
            raise self._error
        return self._result


class TestPrimaryTimeoutProfiles:
    @patch("app.engine.llm_pool.settings")
    def test_resolve_primary_timeout_seconds_uses_tier_settings(self, mock_settings):
        mock_settings.llm_primary_timeout_light_seconds = 11.0
        mock_settings.llm_primary_timeout_moderate_seconds = 26.0
        mock_settings.llm_primary_timeout_deep_seconds = 51.0

        assert resolve_primary_timeout_seconds(tier="light") == 11.0
        assert resolve_primary_timeout_seconds(tier="moderate") == 26.0
        assert resolve_primary_timeout_seconds(tier=ThinkingTier.DEEP.value) == 51.0

    @patch("app.engine.llm_pool.settings")
    def test_resolve_primary_timeout_seconds_honors_profiles(self, mock_settings):
        mock_settings.llm_primary_timeout_structured_seconds = 64.0
        mock_settings.llm_primary_timeout_background_seconds = 0.0
        mock_settings.llm_timeout_provider_overrides = "{}"

        assert resolve_primary_timeout_seconds(timeout_profile="structured") == 64.0
        assert resolve_primary_timeout_seconds(timeout_profile="background") is None

    @patch("app.engine.llm_pool.settings")
    def test_resolve_primary_timeout_seconds_honors_provider_override(self, mock_settings):
        mock_settings.llm_primary_timeout_deep_seconds = 45.0
        mock_settings.llm_timeout_provider_overrides = '{"google":{"deep_seconds":88}}'

        assert resolve_primary_timeout_seconds(
            tier="deep",
            provider="google",
        ) == 88.0

    @patch("app.engine.llm_pool.settings")
    def test_resolve_primary_timeout_seconds_honors_model_override(self, mock_settings):
        mock_settings.llm_primary_timeout_moderate_seconds = 25.0
        mock_settings.llm_timeout_provider_overrides = (
            '{"nvidia":{"moderate_seconds":22,'
            '"models":{"deepseek-ai/deepseek-v4-flash":{"moderate_seconds":7}}}}'
        )

        assert resolve_primary_timeout_seconds(
            tier="moderate",
            provider="nvidia",
            model_name="deepseek-ai/deepseek-v4-flash",
        ) == 7.0
        assert resolve_primary_timeout_seconds(
            tier="moderate",
            provider="nvidia",
            model_name="deepseek-ai/deepseek-v4-pro",
        ) == 22.0

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_ainvoke_with_failover_uses_structured_timeout_profile(self, mock_settings):
        mock_settings.llm_primary_timeout_structured_seconds = 77.0
        mock_settings.llm_timeout_provider_overrides = "{}"
        llm = _FakeAsyncLLM(result="ok")
        route = ResolvedLLMRoute(provider="google", llm=llm)
        observed: dict[str, float] = {}

        async def fake_wait_for(awaitable, timeout):
            observed["timeout"] = timeout
            return await awaitable

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
            patch("asyncio.wait_for", new=fake_wait_for),
        ):
            result = await ainvoke_with_failover(
                llm,
                ["hello"],
                timeout_profile="structured",
            )

        assert result == "ok"
        assert observed["timeout"] == 77.0

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_ainvoke_with_failover_background_profile_disables_wait_for(self, mock_settings):
        mock_settings.llm_primary_timeout_background_seconds = 0.0
        mock_settings.llm_timeout_provider_overrides = "{}"
        llm = _FakeAsyncLLM(result="ok")
        route = ResolvedLLMRoute(provider="google", llm=llm)

        async def fail_wait_for(*_args, **_kwargs):
            raise AssertionError("wait_for should not be used for background timeout profile")

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
            patch("asyncio.wait_for", new=fail_wait_for),
        ):
            result = await ainvoke_with_failover(
                llm,
                ["hello"],
                timeout_profile="background",
            )

        assert result == "ok"


class TestModelHealthRuntime:
    def test_model_failure_with_non_positive_window_does_not_degrade(self):
        from app.engine.llm_model_health import (
            is_model_degraded,
            record_model_failure,
        )

        record_model_failure(
            "nvidia",
            "deepseek-ai/deepseek-v4-flash",
            reason_code="timeout",
            timeout_seconds=0.01,
            degraded_for_seconds=0,
        )

        assert (
            is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-flash") is False
        )

    def test_model_health_snapshot_omits_raw_error_detail(self):
        from app.engine.llm_model_health import (
            get_model_health_snapshot,
            record_model_failure,
        )

        record_model_failure(
            "nvidia",
            "deepseek-ai/deepseek-v4-pro",
            reason_code="server_error",
            error=RuntimeError("provider payload with secret-token"),
        )

        entry = get_model_health_snapshot()["nvidia"]["deepseek-ai/deepseek-v4-pro"]
        assert entry["last_error_type"] == "RuntimeError"
        assert "last_error_detail" not in entry

    def test_create_custom_model_uses_provider_healthy_alternative(self):
        from app.engine.llm_model_health import record_model_failure

        provider = _make_mock_provider("nvidia")
        provider._select_healthy_model = MagicMock(
            return_value="deepseek-ai/deepseek-v4-flash"
        )
        LLMPool._providers = {"nvidia": provider}
        record_model_failure(
            "nvidia",
            "deepseek-ai/deepseek-v4-pro",
            reason_code="timeout",
            timeout_seconds=0.01,
        )

        result = LLMPool.create_llm_with_model_for_provider(
            "nvidia",
            "deepseek-ai/deepseek-v4-pro",
            ThinkingTier.DEEP,
        )

        assert result is provider.create_instance.return_value
        provider.create_instance.assert_called_once()
        assert provider.create_instance.call_args.kwargs["model_name"] == (
            "deepseek-ai/deepseek-v4-flash"
        )

    def test_custom_model_tags_runtime_model_for_metadata_contract(self):
        provider = _make_mock_provider("nvidia")
        requested_model = "nvidia/nemotron-3-ultra-550b-a55b"
        provider.create_instance.return_value.model_name = "qwen/qwen3-next-80b-a3b-instruct"
        LLMPool._providers = {"nvidia": provider}

        result = LLMPool.create_llm_with_model_for_provider(
            "nvidia",
            requested_model,
            ThinkingTier.LIGHT,
        )

        assert result is provider.create_instance.return_value
        assert provider.create_instance.call_args.kwargs["model_name"] == requested_model
        assert getattr(result, "_wiii_provider_name") == "nvidia"
        assert getattr(result, "_wiii_requested_provider") == "nvidia"
        assert getattr(result, "_wiii_model_name") == requested_model

    def test_cached_custom_model_is_retagged_with_requested_runtime_model(self):
        provider = _make_mock_provider("nvidia")
        requested_model = "nvidia/nemotron-3-ultra-550b-a55b"
        LLMPool._providers = {"nvidia": provider}

        first = LLMPool.create_llm_with_model_for_provider(
            "nvidia",
            requested_model,
            ThinkingTier.LIGHT,
        )
        first._wiii_model_name = "qwen/qwen3-next-80b-a3b-instruct"

        second = LLMPool.create_llm_with_model_for_provider(
            "nvidia",
            requested_model,
            ThinkingTier.LIGHT,
        )

        assert second is first
        assert provider.create_instance.call_count == 1
        assert getattr(second, "_wiii_model_name") == requested_model


class TestRequestScopedRouting:
    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_pinned_provider_failure_updates_only_requested_provider(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu"]
        mock_settings.llm_provider = "google"

        google = _make_mock_provider("google")
        zhipu = _make_mock_provider("zhipu")

        google_llm = _FakeAsyncLLM(result="google-fallback")
        zhipu_llm = _FakeAsyncLLM(error=TimeoutError("zhipu timeout"))

        google.create_instance.return_value = google_llm
        zhipu.create_instance.return_value = zhipu_llm

        LLMPool._providers = {"google": google, "zhipu": zhipu}
        LLMPool._active_provider = "google"

        with pytest.raises(TimeoutError):
            await ainvoke_with_failover(
                zhipu_llm,
                ["hello"],
                tier="moderate",
                provider="zhipu",
                failover_mode=FAILOVER_MODE_PINNED,
            )

        zhipu.record_failure.assert_awaited_once()
        google.record_failure.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_auto_mode_still_cross_provider_fails_over(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu"]
        mock_settings.llm_provider = "google"

        google = _make_mock_provider("google")
        zhipu = _make_mock_provider("zhipu")

        google_llm = _FakeAsyncLLM(result="google-fallback")
        zhipu_llm = _FakeAsyncLLM(error=TimeoutError("zhipu timeout"))

        google.create_instance.return_value = google_llm
        zhipu.create_instance.return_value = zhipu_llm

        LLMPool._providers = {"google": google, "zhipu": zhipu}
        LLMPool._active_provider = "google"

        result = await ainvoke_with_failover(
            zhipu_llm,
            ["hello"],
            tier="moderate",
            provider="zhipu",
        )

        assert result == "google-fallback"
        zhipu.record_failure.assert_awaited_once()
        google.record_failure.assert_not_awaited()

    @patch("app.engine.llm_pool.settings")
    def test_get_llm_for_provider_creates_requested_provider_instance(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu", "ollama"]
        mock_settings.llm_provider = "google"

        google = _make_mock_provider("google")
        zhipu = _make_mock_provider("zhipu")
        ollama = _make_mock_provider("ollama")

        LLMPool._providers = {"google": google, "zhipu": zhipu, "ollama": ollama}
        LLMPool._active_provider = "google"
        LLMPool._pool = {"moderate": google.create_instance.return_value}

        result = get_llm_for_provider("ollama", default_tier=ThinkingTier.MODERATE)

        assert result is ollama.create_instance.return_value
        google.create_instance.assert_not_called()
        ollama.create_instance.assert_called_once()

    @patch("app.engine.llm_pool.settings")
    def test_request_selectable_providers_hide_openai_in_openrouter_mode(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai", "openrouter"]
        mock_settings.llm_provider = "google"
        mock_settings.openai_api_key = "legacy-openrouter-key"
        mock_settings.openai_base_url = "https://openrouter.ai/api/v1"

        google = _make_mock_provider("google")
        openai = _make_mock_provider("openai")
        openrouter = _make_mock_provider("openrouter")

        LLMPool._providers = {
            "google": google,
            "openai": openai,
            "openrouter": openrouter,
        }

        providers = LLMPool.get_request_selectable_providers()

        assert "google" in providers
        assert "openrouter" in providers
        assert "openai" not in providers

    @patch("app.engine.llm_pool.settings")
    def test_resolve_runtime_route_pinned_has_no_fallback(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu"]
        mock_settings.llm_provider = "google"

        google = _make_mock_provider("google")
        zhipu = _make_mock_provider("zhipu")

        LLMPool._providers = {"google": google, "zhipu": zhipu}

        route = LLMPool.resolve_runtime_route(
            "zhipu",
            ThinkingTier.MODERATE,
            failover_mode=FAILOVER_MODE_PINNED,
        )

        assert route.provider == "zhipu"
        assert route.fallback_provider is None
        assert route.fallback_llm is None

    @patch("app.services.llm_selectability_service.get_llm_selectability_snapshot")
    @patch("app.engine.llm_pool.settings")
    def test_resolve_runtime_route_auto_prefers_selectable_provider(
        self,
        mock_settings,
        mock_selectability,
    ):
        from app.services.llm_selectability_service import ProviderSelectability

        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu", "ollama"]
        mock_settings.llm_provider = "google"
        mock_settings.openai_base_url = None

        google = _make_mock_provider("google", available=True)
        zhipu = _make_mock_provider("zhipu", available=True)
        ollama = _make_mock_provider("ollama", available=False)

        LLMPool._providers = {"google": google, "zhipu": zhipu, "ollama": ollama}
        LLMPool._active_provider = "google"

        mock_selectability.return_value = [
            ProviderSelectability(
                provider="google",
                display_name="Gemini",
                state="disabled",
                reason_code="busy",
                reason_label="busy",
                selected_model="gemini-3.1-flash-lite-preview",
                strict_pin=True,
                verified_at="2026-03-23T10:00:00+00:00",
                available=False,
                configured=True,
                request_selectable=True,
                is_primary=True,
                is_fallback=False,
            ),
            ProviderSelectability(
                provider="zhipu",
                display_name="GLM-5",
                state="selectable",
                reason_code=None,
                reason_label=None,
                selected_model="glm-5",
                strict_pin=True,
                verified_at="2026-03-23T10:00:00+00:00",
                available=True,
                configured=True,
                request_selectable=True,
                is_primary=False,
                is_fallback=True,
            ),
        ]

        route = LLMPool.resolve_runtime_route(None, ThinkingTier.MODERATE)

        assert route.provider == "zhipu"
        assert route.fallback_provider is None or route.fallback_provider != "google"

    @patch("app.services.llm_selectability_service.get_llm_selectability_snapshot")
    @patch("app.engine.llm_pool.settings")
    def test_resolve_runtime_route_auto_raises_when_no_provider_is_selectable(
        self,
        mock_settings,
        mock_selectability,
    ):
        from app.services.llm_selectability_service import ProviderSelectability

        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "zhipu"]
        mock_settings.llm_provider = "google"

        google = _make_mock_provider("google", available=True)
        zhipu = _make_mock_provider("zhipu", available=True)

        LLMPool._providers = {"google": google, "zhipu": zhipu}
        LLMPool._active_provider = "google"

        mock_selectability.return_value = [
            ProviderSelectability(
                provider="google",
                display_name="Gemini",
                state="disabled",
                reason_code="busy",
                reason_label="busy",
                selected_model="gemini-3.1-flash-lite-preview",
                strict_pin=True,
                verified_at="2026-03-25T09:00:00+00:00",
                available=False,
                configured=True,
                request_selectable=True,
                is_primary=True,
                is_fallback=False,
            ),
            ProviderSelectability(
                provider="zhipu",
                display_name="Zhipu",
                state="disabled",
                reason_code="capability_missing",
                reason_label="capability_missing",
                selected_model="glm-4.5-air",
                strict_pin=True,
                verified_at="2026-03-25T09:00:00+00:00",
                available=False,
                configured=True,
                request_selectable=True,
                is_primary=False,
                is_fallback=True,
            ),
        ]

        with pytest.raises(ProviderUnavailableError) as exc_info:
            LLMPool.resolve_runtime_route(None, ThinkingTier.MODERATE)

        assert exc_info.value.provider == "auto"
        assert exc_info.value.reason_code == "busy"

    @patch("app.services.llm_selectability_service.get_llm_selectability_snapshot")
    @patch("app.engine.llm_pool.settings")
    def test_resolve_runtime_route_primary_prefers_selectable_fallback_when_requested(
        self,
        mock_settings,
        mock_selectability,
    ):
        from app.services.llm_selectability_service import ProviderSelectability

        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["zhipu", "google", "ollama"]
        mock_settings.llm_provider = "google"
        mock_settings.openai_base_url = None

        zhipu = _make_mock_provider("zhipu", available=True)
        google = _make_mock_provider("google", available=True)
        ollama = _make_mock_provider("ollama", available=True)

        LLMPool._providers = {"zhipu": zhipu, "google": google, "ollama": ollama}
        LLMPool._active_provider = "google"

        mock_selectability.return_value = [
            ProviderSelectability(
                provider="zhipu",
                display_name="Zhipu",
                state="selectable",
                reason_code=None,
                reason_label=None,
                selected_model="glm-5",
                strict_pin=True,
                verified_at="2026-03-25T09:00:00+00:00",
                available=True,
                configured=True,
                request_selectable=True,
                is_primary=False,
                is_fallback=True,
            ),
            ProviderSelectability(
                provider="google",
                display_name="Gemini",
                state="disabled",
                reason_code="busy",
                reason_label="busy",
                selected_model="gemini-3.1-flash-lite-preview",
                strict_pin=True,
                verified_at="2026-03-25T09:00:00+00:00",
                available=False,
                configured=True,
                request_selectable=True,
                is_primary=True,
                is_fallback=False,
            ),
            ProviderSelectability(
                provider="ollama",
                display_name="Ollama",
                state="disabled",
                reason_code="host_down",
                reason_label="host_down",
                selected_model="qwen3:4b-instruct-2507-q4_K_M",
                strict_pin=True,
                verified_at="2026-03-25T09:00:00+00:00",
                available=False,
                configured=True,
                request_selectable=True,
                is_primary=False,
                is_fallback=True,
            ),
        ]

        route = LLMPool.resolve_runtime_route(
            "zhipu",
            ThinkingTier.MODERATE,
            failover_mode=FAILOVER_MODE_AUTO,
            prefer_selectable_fallback=True,
        )

        assert route.provider == "zhipu"
        assert route.fallback_provider is None
        assert route.fallback_llm is None

    @patch("app.engine.llm_pool.settings")
    def test_resolve_runtime_route_honors_allowed_fallback_providers(self, mock_settings):
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["zhipu", "openrouter", "ollama"]
        mock_settings.llm_provider = "zhipu"
        mock_settings.openai_base_url = "https://openrouter.ai/api/v1"

        zhipu = _make_mock_provider("zhipu", available=True)
        openrouter = _make_mock_provider("openrouter", available=True)
        ollama = _make_mock_provider("ollama", available=True)

        LLMPool._providers = {
            "zhipu": zhipu,
            "openrouter": openrouter,
            "ollama": ollama,
        }

        route = LLMPool.resolve_runtime_route(
            "zhipu",
            ThinkingTier.DEEP,
            failover_mode=FAILOVER_MODE_AUTO,
            allowed_fallback_providers={"ollama"},
        )

        assert route.provider == "zhipu"
        assert route.fallback_provider == "ollama"
        assert route.fallback_llm is ollama.create_instance.return_value

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_uses_on_primary_for_auto_routed_provider(self):
        google_llm = _FakeAsyncLLM(result="google")
        zhipu_llm = _FakeAsyncLLM(result="zhipu")
        wrapped_zhipu = _FakeAsyncLLM(result="wrapped-zhipu")

        route = ResolvedLLMRoute(
            provider="zhipu",
            llm=zhipu_llm,
            circuit_breaker=None,
            fallback_provider=None,
            fallback_llm=None,
        )

        with patch.object(LLMPool, "resolve_runtime_route", return_value=route):
            result = await ainvoke_with_failover(
                google_llm,
                ["hello"],
                tier="moderate",
                on_primary=lambda primary: wrapped_zhipu,
                primary_timeout=1.0,
            )

        assert result == "wrapped-zhipu"

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_falls_over_on_invalid_api_key_error(self):
        google_llm = _FakeAsyncLLM(error=RuntimeError("401 invalid API key"))
        zhipu_llm = _FakeAsyncLLM(result="glm-ok")

        route = ResolvedLLMRoute(
            provider="google",
            llm=google_llm,
            circuit_breaker=None,
            fallback_provider="zhipu",
            fallback_llm=zhipu_llm,
        )

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()) as mock_failure,
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                google_llm,
                ["hello"],
                tier="moderate",
                provider="google",
                primary_timeout=None,
            )

        assert result == "glm-ok"
        mock_failure.assert_awaited_once_with("google")

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_reports_structured_auth_failover_event(self):
        google_llm = _FakeAsyncLLM(error=RuntimeError("401 invalid API key"))
        zhipu_llm = _FakeAsyncLLM(result="glm-ok")
        failover_events: list[dict[str, object]] = []

        route = ResolvedLLMRoute(
            provider="google",
            llm=google_llm,
            circuit_breaker=None,
            fallback_provider="zhipu",
            fallback_llm=zhipu_llm,
        )

        async def _capture_failover(event: dict[str, object]) -> None:
            failover_events.append(event)

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                google_llm,
                ["hello"],
                tier="moderate",
                provider="google",
                on_failover=_capture_failover,
                primary_timeout=None,
            )

        assert result == "glm-ok"
        assert len(failover_events) == 1
        assert failover_events[0]["from_provider"] == "google"
        assert failover_events[0]["to_provider"] == "zhipu"
        assert failover_events[0]["reason_code"] == "auth_error"
        assert failover_events[0]["reason_category"] == "auth_error"
        assert failover_events[0]["reason_label"] == "Xác thực provider thất bại."

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_reports_timeout_failover_event(self):
        google_llm = _FakeAsyncLLM(sleep_seconds=0.05, result="slow-google")
        zhipu_llm = _FakeAsyncLLM(result="glm-ok")
        failover_events: list[dict[str, object]] = []

        route = ResolvedLLMRoute(
            provider="google",
            llm=google_llm,
            circuit_breaker=None,
            fallback_provider="zhipu",
            fallback_llm=zhipu_llm,
        )

        async def _capture_failover(event: dict[str, object]) -> None:
            failover_events.append(event)

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                google_llm,
                ["hello"],
                tier="moderate",
                provider="google",
                on_failover=_capture_failover,
                primary_timeout=0.001,
            )

        assert result == "glm-ok"
        assert len(failover_events) == 1
        assert failover_events[0]["reason_code"] == "timeout"
        assert failover_events[0]["reason_category"] == "timeout"
        assert failover_events[0]["timeout_seconds"] == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_records_cross_provider_fallback_failure(self):
        from app.engine.llm_model_health import is_model_degraded

        google_llm = _FakeAsyncLLM(error=RuntimeError("503 google unavailable"))
        nvidia_llm = _FakeAsyncLLM(error=RuntimeError("503 nvidia unavailable"))
        setattr(nvidia_llm, "model_name", "deepseek-ai/deepseek-v4-pro")

        route = ResolvedLLMRoute(
            provider="google",
            llm=google_llm,
            circuit_breaker=None,
            fallback_provider="nvidia",
            fallback_llm=nvidia_llm,
        )
        mock_failure = AsyncMock()

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(LLMPool, "record_failure_for_provider", new=mock_failure),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            with pytest.raises(RuntimeError, match="nvidia unavailable"):
                await ainvoke_with_failover(
                    google_llm,
                    ["hello"],
                    tier="moderate",
                    provider="google",
                    primary_timeout=None,
                )

        mock_failure.assert_has_awaits([call("google"), call("nvidia")])
        assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-pro") is True

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_uses_same_provider_model_fallback_before_cross_provider(self):
        zhipu_primary = _FakeAsyncLLM(sleep_seconds=0.05, result="slow-glm5")
        setattr(zhipu_primary, "model_name", "glm-5")
        zhipu_fast = _FakeAsyncLLM(result="glm-air-ok")
        openrouter_llm = _FakeAsyncLLM(result="openrouter-ok")
        failover_events: list[dict[str, object]] = []

        route = ResolvedLLMRoute(
            provider="zhipu",
            llm=zhipu_primary,
            circuit_breaker=None,
            fallback_provider="openrouter",
            fallback_llm=openrouter_llm,
        )

        async def _capture_failover(event: dict[str, object]) -> None:
            failover_events.append(event)

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(
                LLMPool,
                "resolve_same_provider_model_fallback",
                return_value={
                    "provider": "zhipu",
                    "from_model": "glm-5",
                    "to_model": "glm-4.5-air",
                    "from_tier": "deep",
                    "to_tier": "moderate",
                },
            ),
            patch.object(
                LLMPool,
                "create_llm_with_model_for_provider",
                return_value=zhipu_fast,
            ) as mock_create_fallback,
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                zhipu_primary,
                ["hello"],
                tier="deep",
                provider="zhipu",
                on_failover=_capture_failover,
                primary_timeout=0.001,
            )

        assert result == "glm-air-ok"
        mock_create_fallback.assert_called_once_with(
            "zhipu",
            "glm-4.5-air",
            ThinkingTier.MODERATE,
        )
        assert len(failover_events) == 1
        assert failover_events[0]["fallback_scope"] == "same_provider_model"
        assert failover_events[0]["from_provider"] == "zhipu"
        assert failover_events[0]["to_provider"] == "zhipu"
        assert failover_events[0]["from_model"] == "glm-5"
        assert failover_events[0]["to_model"] == "glm-4.5-air"

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_falls_back_cross_provider_when_same_provider_model_fails(self):
        zhipu_primary = _FakeAsyncLLM(sleep_seconds=0.05, result="slow-glm5")
        setattr(zhipu_primary, "model_name", "glm-5")
        zhipu_fast = _FakeAsyncLLM(error=RuntimeError("429 RESOURCE_EXHAUSTED"))
        openrouter_llm = _FakeAsyncLLM(result="openrouter-ok")

        route = ResolvedLLMRoute(
            provider="zhipu",
            llm=zhipu_primary,
            circuit_breaker=None,
            fallback_provider="openrouter",
            fallback_llm=openrouter_llm,
        )

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(
                LLMPool,
                "resolve_same_provider_model_fallback",
                return_value={
                    "provider": "zhipu",
                    "from_model": "glm-5",
                    "to_model": "glm-4.5-air",
                    "from_tier": "deep",
                    "to_tier": "moderate",
                },
            ),
            patch.object(
                LLMPool,
                "create_llm_with_model_for_provider",
                return_value=zhipu_fast,
            ),
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                zhipu_primary,
                ["hello"],
                tier="deep",
                provider="zhipu",
                primary_timeout=0.001,
            )

        assert result == "openrouter-ok"

    @pytest.mark.asyncio
    async def test_ainvoke_with_failover_reports_same_provider_failure_when_no_cross_provider_exists(self):
        zhipu_primary = _FakeAsyncLLM(sleep_seconds=0.05, result="slow-glm5")
        setattr(zhipu_primary, "model_name", "glm-5")
        zhipu_fast = _FakeAsyncLLM(error=TimeoutError("glm air timeout"))

        route = ResolvedLLMRoute(
            provider="zhipu",
            llm=zhipu_primary,
            circuit_breaker=None,
            fallback_provider=None,
            fallback_llm=None,
        )

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(
                LLMPool,
                "resolve_same_provider_model_fallback",
                return_value={
                    "provider": "zhipu",
                    "from_model": "glm-5",
                    "to_model": "glm-4.5-air",
                    "from_tier": "deep",
                    "to_tier": "moderate",
                },
            ),
            patch.object(
                LLMPool,
                "create_llm_with_model_for_provider",
                return_value=zhipu_fast,
            ),
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            with pytest.raises(TimeoutError, match="same-provider fallback also failed"):
                await ainvoke_with_failover(
                    zhipu_primary,
                    ["hello"],
                    tier="deep",
                    provider="zhipu",
                    primary_timeout=0.001,
                )

    @pytest.mark.asyncio
    @patch("app.engine.llm_pool.settings")
    async def test_nvidia_flash_timeout_marks_model_degraded_and_falls_back_to_pro(
        self,
        mock_settings,
    ):
        from app.engine.llm_model_health import is_model_degraded

        mock_settings.nvidia_model = "deepseek-ai/deepseek-v4-flash"
        mock_settings.nvidia_model_advanced = "deepseek-ai/deepseek-v4-pro"
        mock_settings.llm_primary_timeout_deep_seconds = 45.0
        mock_settings.llm_timeout_provider_overrides = "{}"

        nvidia_flash = _FakeAsyncLLM(sleep_seconds=0.05, result="slow-flash")
        setattr(nvidia_flash, "model_name", "deepseek-ai/deepseek-v4-flash")
        nvidia_pro = _FakeAsyncLLM(result="pro-ok")
        route = ResolvedLLMRoute(
            provider="nvidia",
            llm=nvidia_flash,
            circuit_breaker=None,
            fallback_provider=None,
            fallback_llm=None,
        )
        failover_events: list[dict[str, object]] = []

        async def _capture_failover(event: dict[str, object]) -> None:
            failover_events.append(event)

        with (
            patch.object(LLMPool, "resolve_runtime_route", return_value=route),
            patch.object(
                LLMPool,
                "create_llm_with_model_for_provider",
                return_value=nvidia_pro,
            ) as mock_create_fallback,
            patch.object(LLMPool, "record_failure_for_provider", new=AsyncMock()),
            patch.object(LLMPool, "record_success_for_provider", new=AsyncMock()),
        ):
            result = await ainvoke_with_failover(
                nvidia_flash,
                ["hello"],
                tier="moderate",
                provider="nvidia",
                on_failover=_capture_failover,
                primary_timeout=0.001,
            )

        assert result == "pro-ok"
        assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-flash") is True
        assert is_model_degraded("nvidia", "deepseek-ai/deepseek-v4-pro") is False
        mock_create_fallback.assert_called_once_with(
            "nvidia",
            "deepseek-ai/deepseek-v4-pro",
            ThinkingTier.DEEP,
        )
        assert failover_events[0]["fallback_scope"] == "same_provider_model"
        assert failover_events[0]["from_model"] == "deepseek-ai/deepseek-v4-flash"
        assert failover_events[0]["to_model"] == "deepseek-ai/deepseek-v4-pro"

    @patch("app.engine.llm_pool.settings")
    def test_nvidia_same_provider_fallback_skips_degraded_target(self, mock_settings):
        from app.engine.llm_model_health import (
            record_model_failure,
            reset_model_health_state,
        )

        mock_settings.nvidia_model = "deepseek-ai/deepseek-v4-flash"
        mock_settings.nvidia_model_advanced = "deepseek-ai/deepseek-v4-pro"
        try:
            record_model_failure(
                "nvidia",
                "deepseek-ai/deepseek-v4-pro",
                reason_code="timeout",
                timeout_seconds=0.01,
            )

            assert (
                LLMPool.resolve_same_provider_model_fallback(
                    "nvidia",
                    "moderate",
                    current_model_name="deepseek-ai/deepseek-v4-flash",
                )
                is None
            )
        finally:
            reset_model_health_state()
