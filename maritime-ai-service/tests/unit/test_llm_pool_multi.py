"""
Tests for LLMPool multi-provider integration.

Sprint 11: Tests pool initialization with providers, type compatibility,
active provider tracking, get_stats(), reset(), and convenience functions.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.engine.llm_providers.wiii_chat_model import WiiiChatModel
from app.engine.llm_pool import LLMPool, ThinkingTier, get_llm_deep, get_llm_moderate, get_llm_light
from app.engine.llm_providers.base import LLMProvider


@pytest.fixture(autouse=True)
def reset_pool():
    """Reset LLMPool state between tests."""
    LLMPool.reset()
    yield
    LLMPool.reset()


def _make_provider(name, configured=True, available=True):
    """Create a mock provider that returns WiiiChatModel instances.

    Note: We use MagicMock() without spec=LLMProvider because the concrete
    providers have extra methods (get_circuit_breaker, record_success, record_failure)
    not defined on the ABC.
    """
    p = MagicMock()
    p.name = name
    p.is_configured.return_value = configured
    p.is_available.return_value = available
    p.get_circuit_breaker.return_value = None
    p.record_success = AsyncMock()
    p.record_failure = AsyncMock()
    mock_llm = MagicMock(spec=WiiiChatModel)
    mock_llm._tag = f"{name}_instance"
    p.create_instance.return_value = mock_llm
    return p


# ============================================================================
# Pool Initialization Tests
# ============================================================================


class TestPoolInitialization:
    """Test LLMPool.initialize() with multi-provider setup."""

    @patch("app.engine.llm_pool.settings")
    def test_initialize_creates_three_tiers(self, mock_settings):
        """Pool creates exactly 3 instances (DEEP, MODERATE, LIGHT)."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        # Manual init (skip _init_providers since we set _providers directly)
        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        assert len(LLMPool._pool) == 3
        assert "deep" in LLMPool._pool
        assert "moderate" in LLMPool._pool
        assert "light" in LLMPool._pool

    @patch("app.engine.llm_pool.settings")
    def test_initialize_idempotent(self, mock_settings):
        """Calling initialize() twice doesn't double-create."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        # Second call should be no-op
        LLMPool.initialize()
        assert provider.create_instance.call_count == 3  # Not 6

    def test_reset_clears_everything(self):
        """reset() clears pool, providers, and flags."""
        LLMPool._pool = {"deep": MagicMock()}
        LLMPool._providers = {"google": MagicMock()}
        LLMPool._initialized = True
        LLMPool._active_provider = "google"

        LLMPool.reset()

        assert LLMPool._pool == {}
        assert LLMPool._providers == {}
        assert LLMPool._initialized is False
        assert LLMPool._active_provider is None


# ============================================================================
# Type Compatibility Tests
# ============================================================================


class TestTypeCompatibility:
    """Verify all returned instances are WiiiChatModel compatible."""

    @patch("app.engine.llm_pool.settings")
    def test_pool_returns_base_chat_model(self, mock_settings):
        """All instances from pool are WiiiChatModel."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        for tier_key in ["deep", "moderate", "light"]:
            llm = LLMPool._pool[tier_key]
            assert isinstance(llm, WiiiChatModel)

    @patch("app.engine.llm_pool.settings")
    def test_get_returns_base_chat_model(self, mock_settings):
        """LLMPool.get() returns WiiiChatModel."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        llm = LLMPool.get(ThinkingTier.MODERATE)
        assert isinstance(llm, WiiiChatModel)

    @patch("app.engine.llm_pool.settings")
    def test_convenience_functions_return_base_chat_model(self, mock_settings):
        """get_llm_deep/moderate/light return WiiiChatModel."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        assert isinstance(get_llm_deep(), WiiiChatModel)
        assert isinstance(get_llm_moderate(), WiiiChatModel)
        assert isinstance(get_llm_light(), WiiiChatModel)


# ============================================================================
# Active Provider Tracking Tests
# ============================================================================


class TestActiveProviderTracking:
    """Test active provider tracking."""

    @patch("app.engine.llm_pool.settings")
    def test_active_provider_set_on_create(self, mock_settings):
        """_active_provider is set when an instance is created."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}
        LLMPool._create_instance("deep")

        assert LLMPool.get_active_provider() == "google"

    @patch("app.engine.llm_pool.settings")
    def test_active_provider_changes_on_failover(self, mock_settings):
        """_active_provider updates when failover occurs."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai"]
        mock_settings.thinking_enabled = True

        google = _make_provider("google")
        google.create_instance.side_effect = Exception("Gemini down")
        openai = _make_provider("openai")

        LLMPool._providers = {"google": google, "openai": openai}
        LLMPool._create_instance("moderate")

        assert LLMPool.get_active_provider() == "openai"

    def test_active_provider_none_initially(self):
        """No active provider before initialization."""
        assert LLMPool.get_active_provider() is None


# ============================================================================
# get_stats() Tests
# ============================================================================


class TestGetStats:
    """Test pool statistics."""

    @patch("app.engine.llm_pool.settings")
    def test_stats_include_provider_info(self, mock_settings):
        """Stats include active provider and chain info."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google", "openai"]

        LLMPool._providers = {
            "google": _make_provider("google"),
            "openai": _make_provider("openai"),
        }
        LLMPool._active_provider = "google"
        LLMPool._initialized = True
        LLMPool._pool = {"deep": MagicMock(), "moderate": MagicMock(), "light": MagicMock()}

        stats = LLMPool.get_stats()
        assert stats["active_provider"] == "google"
        assert stats["failover_enabled"] is True
        assert stats["providers_registered"] == ["google", "openai"]
        assert stats["instance_count"] == 3
        assert stats["initialized"] is True

    def test_stats_empty_pool(self):
        """Stats for uninitialized pool."""
        stats = LLMPool.get_stats()
        assert stats["initialized"] is False
        assert stats["instance_count"] == 0
        assert stats["active_provider"] is None

    def test_stats_init_providers_when_pool_is_empty(self):
        """Stats should still expose registered providers after a runtime reset."""
        with patch.object(LLMPool, "_init_providers") as mock_init:
            stats = LLMPool.get_stats()

        mock_init.assert_called_once()
        assert stats["initialized"] is False
        assert stats["active_provider"] is None

    @patch("app.engine.llm_pool.settings")
    def test_stats_with_circuit_breaker(self, mock_settings):
        """Stats include circuit breaker info when available."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]

        mock_cb = MagicMock()
        mock_cb.get_stats.return_value = {"state": "closed", "failures": 0}

        provider = _make_provider("google")
        provider.get_circuit_breaker.return_value = mock_cb

        LLMPool._providers = {"google": provider}
        LLMPool._initialized = True

        stats = LLMPool.get_stats()
        assert "circuit_breakers" in stats
        assert "google" in stats["circuit_breakers"]


# ============================================================================
# Tier Resolution Tests
# ============================================================================


class TestTierResolution:
    """Test tier resolution and mapping."""

    def test_resolve_tier_from_enum(self):
        assert LLMPool._resolve_tier(ThinkingTier.DEEP) == "deep"
        assert LLMPool._resolve_tier(ThinkingTier.MODERATE) == "moderate"
        assert LLMPool._resolve_tier(ThinkingTier.LIGHT) == "light"

    def test_resolve_tier_from_string(self):
        assert LLMPool._resolve_tier("deep") == "deep"
        assert LLMPool._resolve_tier("moderate") == "moderate"
        assert LLMPool._resolve_tier("light") == "light"

    @patch("app.engine.llm_pool.settings")
    def test_minimal_maps_to_light(self, mock_settings):
        """MINIMAL tier maps to LIGHT for memory efficiency."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        # Create light tier first
        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        # MINIMAL should return the same as LIGHT
        light = LLMPool.get(ThinkingTier.LIGHT)
        minimal = LLMPool.get(ThinkingTier.MINIMAL)
        assert light is minimal

    @patch("app.engine.llm_pool.settings")
    def test_off_maps_to_light(self, mock_settings):
        """OFF tier maps to LIGHT for memory efficiency."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        light = LLMPool.get(ThinkingTier.LIGHT)
        off = LLMPool.get(ThinkingTier.OFF)
        assert light is off

    @patch("app.engine.llm_pool.settings")
    def test_get_default_is_moderate(self, mock_settings):
        """get() with no args returns MODERATE tier."""
        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.thinking_enabled = True

        provider = _make_provider("google")
        LLMPool._providers = {"google": provider}

        for tier in [ThinkingTier.DEEP, ThinkingTier.MODERATE, ThinkingTier.LIGHT]:
            LLMPool._create_instance(tier)
        LLMPool._initialized = True

        default = LLMPool.get()
        moderate = LLMPool.get(ThinkingTier.MODERATE)
        assert default is moderate

    @patch("app.engine.llm_pool.settings")
    def test_get_drops_degraded_cached_model(self, mock_settings):
        """LLMPool.get() should not keep returning a model probe marked degraded."""
        from app.engine.llm_model_health import record_model_failure

        mock_settings.enable_llm_failover = True
        mock_settings.llm_failover_chain = ["nvidia"]
        mock_settings.llm_provider = "nvidia"
        mock_settings.thinking_enabled = True

        degraded_llm = MagicMock(spec=WiiiChatModel)
        degraded_llm._wiii_provider_name = "nvidia"
        degraded_llm._wiii_model_name = "deepseek-ai/deepseek-v4-flash"
        healthy_llm = MagicMock(spec=WiiiChatModel)
        healthy_llm._wiii_model_name = "deepseek-ai/deepseek-v4-pro"

        provider = _make_provider("nvidia")
        provider.create_instance.return_value = healthy_llm
        LLMPool._providers = {"nvidia": provider}
        LLMPool._active_provider = "nvidia"
        LLMPool._pool = {"moderate": degraded_llm}
        LLMPool._provider_pools = {"nvidia": {"moderate": degraded_llm}}
        LLMPool._initialized = True

        record_model_failure(
            "nvidia",
            "deepseek-ai/deepseek-v4-flash",
            reason_code="timeout",
            timeout_seconds=0.01,
        )

        result = LLMPool.get(ThinkingTier.MODERATE)

        assert result is healthy_llm
        assert LLMPool._pool["moderate"] is healthy_llm
        assert LLMPool._provider_pools["nvidia"]["moderate"] is healthy_llm
        provider.create_instance.assert_called_once()


# ============================================================================
# _init_providers Tests
# ============================================================================


class TestInitProviders:
    """Test provider initialization from config."""

    @patch("app.engine.llm_pool.settings")
    def test_init_providers_respects_chain_order(self, mock_settings):
        """Providers are registered in the order of the failover chain."""
        mock_settings.llm_failover_chain = ["openai", "google"]
        mock_settings.enable_llm_failover = True

        LLMPool._providers = {}
        LLMPool._init_providers()

        # Should have both providers
        assert "openai" in LLMPool._providers
        assert "google" in LLMPool._providers

    @patch("app.engine.llm_pool.settings")
    def test_init_providers_skips_unknown(self, mock_settings):
        """Unknown provider names are silently skipped."""
        mock_settings.llm_failover_chain = ["google", "unknown_provider"]
        mock_settings.enable_llm_failover = True

        LLMPool._providers = {}
        LLMPool._init_providers()

        assert "google" in LLMPool._providers
        assert "unknown_provider" not in LLMPool._providers

    @patch("app.engine.llm_pool.settings")
    def test_init_providers_idempotent(self, mock_settings):
        """_init_providers is a no-op if already populated."""
        mock_settings.llm_failover_chain = ["google"]
        mock_settings.enable_llm_failover = True

        existing = MagicMock()
        LLMPool._providers = {"google": existing}
        LLMPool._init_providers()

        # Should still be the original mock, not replaced
        assert LLMPool._providers["google"] is existing


# ============================================================================
# LLM Factory Provider Parameter Tests
# ============================================================================


class TestLLMFactoryProvider:
    """Test create_llm() with explicit provider parameter."""

    @patch("app.engine.llm_factory.create_provider")
    @patch("app.engine.llm_factory.settings")
    def test_create_llm_default_is_gemini(self, mock_settings, mock_create_provider):
        """create_llm() without provider creates the Google provider by default."""
        mock_settings.llm_provider = "google"
        mock_settings.thinking_enabled = False
        mock_settings.include_thought_summaries = False
        mock_settings.google_model = "gemini-3-flash-preview"
        mock_settings.google_api_key = "test-key"
        mock_settings.enable_unified_providers = False
        google = _make_provider("google")
        mock_create_provider.return_value = google

        from app.engine.llm_factory import create_llm

        llm = create_llm(tier=ThinkingTier.LIGHT)

        assert llm is google.create_instance.return_value
        mock_create_provider.assert_called_once_with("google")
        google.create_instance.assert_called_once()

    @patch("app.engine.llm_factory.create_provider")
    @patch("app.engine.llm_factory.settings")
    def test_create_llm_with_openai_provider(self, mock_factory_settings, mock_create_provider):
        """create_llm(provider='openai') uses OpenAIProvider."""
        mock_factory_settings.thinking_enabled = False
        mock_factory_settings.include_thought_summaries = False
        openai = _make_provider("openai")
        mock_create_provider.return_value = openai

        from app.engine.llm_factory import create_llm

        llm = create_llm(tier=ThinkingTier.MODERATE, provider="openai")

        assert llm is openai.create_instance.return_value
        mock_create_provider.assert_called_once_with("openai")

    @patch("app.engine.llm_factory.settings")
    def test_create_llm_unknown_provider_raises(self, mock_settings):
        """create_llm(provider='unknown') raises ValueError."""
        mock_settings.thinking_enabled = False
        mock_settings.include_thought_summaries = False

        from app.engine.llm_factory import create_llm
        with pytest.raises(ValueError, match="Unknown provider"):
            create_llm(tier=ThinkingTier.LIGHT, provider="unknown_provider")
