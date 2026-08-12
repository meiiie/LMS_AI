"""
LLM Singleton Pool - Multi-Provider Failover (Sprint 11, SOTA 2026)

Evolved from single-provider (Gemini-only) to multi-provider failover
inspired by OpenClaw's model-agnostic architecture.

Key Features:
- Creates only 3 LLM instances (DEEP, MODERATE, LIGHT) per provider
- Automatic failover: Google → OpenAI → Ollama (configurable chain)
- Per-provider circuit breakers for fast failure detection
- Backward compatible: all 18+ consumer files use ``.ainvoke()``/``.astream()``

Reference: MEMORY_OVERFLOW_SOTA_ANALYSIS.md, OpenClaw architecture
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional


from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_model_health import is_model_degraded, reset_model_health_state
from app.engine.llm_runtime_state import register_llm_runtime_access
from app.engine.llm_provider_registry import create_provider, is_supported_provider
from app.engine.llm_timeout_policy import (
    TIMEOUT_PROFILE_BY_NAME,
    TIMEOUT_PROFILE_SETTINGS,
    loads_timeout_provider_overrides,
)
from app.engine.llm_failover_runtime import (
    ainvoke_with_failover_impl,
    is_failover_eligible_error_impl,
    is_rate_limit_error_impl,
    resolve_primary_timeout_seconds_impl,
)
from app.engine.llm_pool_support import (
    get_provider_chain_impl,
    get_request_provider_chain_impl,
    get_selectable_provider_names_impl,
    normalize_failover_mode_impl,
    normalize_provider_impl,
    normalize_tier_key_impl,
    resolve_auto_primary_provider_impl,
    tag_runtime_metadata_impl,
    thinking_budget_for_tier_impl,
)
from app.engine.llm_pool_bootstrap_runtime import (
    create_fallback_instances_impl,
    create_primary_instance_impl,
    create_provider_instance_impl,
    get_provider_instance_impl,
    init_providers_impl,
)
from app.engine.llm_pool_monitoring import (
    get_circuit_breaker_for_provider_impl,
    get_request_selectable_providers_impl,
    get_stats_impl,
    is_available_impl,
    record_provider_failure_impl,
    record_provider_success_impl,
    reset_pool_state_impl,
)
from app.engine.openai_compatible_credentials import (
    is_openrouter_legacy_slot_configured,
)
from app.engine.llm_route_runtime import (
    get_fallback_for_provider_impl,
    resolve_runtime_route_impl,
)
from app.engine.llm_pool_legacy_runtime import (
    create_instance_legacy_impl,
)
from app.engine.llm_pool_custom_models import (
    create_llm_with_model_for_provider_impl,
)
from app.engine.llm_same_provider_runtime import (
    resolve_same_provider_model_fallback_impl,
)
from app.engine.llm_pool_facade_runtime import (
    get_fallback_impl,
    get_pool_llm_impl,
    get_provider_info_impl,
    get_stats_public_impl,
    initialize_pool_impl,
    is_available_public_impl,
)

try:
    from app.core.resilience import get_circuit_breaker
    _gemini_cb = get_circuit_breaker("gemini", failure_threshold=3, recovery_timeout=30)
except Exception:
    _gemini_cb = None

logger = logging.getLogger(__name__)


# Import ThinkingTier from canonical source (llm_factory.py)
from app.engine.llm_factory import ThinkingTier

# Thinking budget mapping (uses config values via get_thinking_budget)
THINKING_BUDGETS = {
    ThinkingTier.DEEP.value: 8192,
    ThinkingTier.MODERATE.value: 4096,
    ThinkingTier.LIGHT.value: 1024,
    ThinkingTier.MINIMAL.value: 512,
    ThinkingTier.OFF.value: 0,
}

FAILOVER_MODE_AUTO = "auto"
FAILOVER_MODE_PINNED = "pinned"


@dataclass
class ResolvedLLMRoute:
    """Resolved primary/fallback runtime objects for one request."""

    provider: Optional[str]
    llm: Any
    circuit_breaker: Any = None
    fallback_provider: Optional[str] = None
    fallback_llm: Optional[Any] = None


class LLMPool:
    """
    SOTA Pattern: Singleton LLM Pool with Multi-Provider Failover.

    Pre-creates 3 LLM instances (DEEP, MODERATE, LIGHT) at startup.
    All components share these instances via Any interface.

    Failover chain (configurable via settings.llm_failover_chain):
        Google Gemini → Zhipu GLM-5 → OpenAI/OpenRouter → Ollama (local)

    Runtime failover: When primary provider hits rate limits (429),
    get_fallback(tier) returns a pre-created fallback instance from
    the next available provider. No 60s SDK retry wait.

    Memory Impact:
    - Before: 15+ LLM instances = ~600MB
    - After: 3+3 LLM instances = ~240MB (primary + fallback)

    Usage:
        from app.engine.llm_pool import LLMPool, get_llm_moderate

        # Initialize at startup
        LLMPool.initialize()

        # Get shared instance in components
        llm = get_llm_moderate()

        # Runtime failover (in graph nodes)
        fallback = LLMPool.get_fallback("moderate")
    """

    _pool: Dict[str, Any] = {}
    _fallback_pool: Dict[str, Any] = {}
    _provider_pools: Dict[str, Dict[str, Any]] = {}
    _initialized: bool = False
    _active_provider: Optional[str] = None
    _fallback_provider: Optional[str] = None
    _providers: Dict[str, "LLMProvider"] = {}
    _thinking_tier = ThinkingTier

    @classmethod
    def _get_provider_chain(cls) -> list[str]:
        """Return the effective provider order with the selected provider first."""
        configured = list(
            getattr(settings, "llm_failover_chain", ["google", "zhipu", "ollama", "openrouter"])
        )
        preferred = getattr(settings, "llm_provider", "google")
        return get_provider_chain_impl(
            preferred_provider=preferred,
            configured_chain=configured,
        )

    @classmethod
    def _resolve_tier(cls, tier) -> str:
        """Resolve ThinkingTier enum or string to string value."""
        if isinstance(tier, ThinkingTier):
            return tier.value
        return tier

    @classmethod
    def _normalize_provider(cls, provider: Optional[str]) -> Optional[str]:
        """Normalize request provider names and collapse ``auto`` to None."""
        return normalize_provider_impl(provider)

    @classmethod
    def _normalize_failover_mode(cls, failover_mode: Optional[str]) -> str:
        return normalize_failover_mode_impl(
            failover_mode,
            auto_mode=FAILOVER_MODE_AUTO,
            pinned_mode=FAILOVER_MODE_PINNED,
        )

    @classmethod
    def _normalize_tier_key(cls, tier) -> str:
        """Map helper tiers to the shared pool keys."""
        return normalize_tier_key_impl(
            tier=tier,
            resolve_tier=cls._resolve_tier,
            thinking_tier=ThinkingTier,
        )

    @classmethod
    def _resolve_auto_primary_provider(cls) -> Optional[str]:
        """Prefer a provider that is currently selectable for auto mode.

        This lets auto-routing skip providers already known to be degraded
        (for example Google quota exhaustion) instead of spending multiple
        node hops timing out before failover finally engages.
        """
        return resolve_auto_primary_provider_impl(
            preferred_provider=getattr(settings, "llm_provider", None),
            active_provider=cls._active_provider,
            normalize_provider=cls._normalize_provider,
            get_request_provider_chain=cls._get_request_provider_chain,
            get_selectable_provider_names=cls._get_selectable_provider_names,
            ensure_provider=cls._ensure_provider,
            logger_obj=logger,
        )

    @classmethod
    def _get_selectable_provider_names(cls) -> Optional[set[str]]:
        """Return the current selectable providers from user-facing runtime truth."""
        return get_selectable_provider_names_impl(
            normalize_provider=cls._normalize_provider,
            logger_obj=logger,
        )

    @classmethod
    def _tag_runtime_metadata(
        cls,
        llm: Any,
        *,
        provider_name: str,
        tier_key: str,
        requested_provider: Optional[str] = None,
    ) -> Any:
        """Attach lightweight runtime metadata for downstream failover helpers."""
        return tag_runtime_metadata_impl(
            llm,
            provider_name=provider_name,
            tier_key=tier_key,
            requested_provider=requested_provider,
            logger_obj=logger,
        )

    @classmethod
    def _ensure_provider(cls, provider_name: Optional[str]):
        """Ensure a provider instance exists in the registry."""
        normalized = cls._normalize_provider(provider_name)
        if not normalized:
            return None
        if normalized in cls._providers:
            return cls._providers[normalized]
        if not is_supported_provider(normalized):
            return None
        try:
            provider = create_provider(normalized)
            cls._providers[normalized] = provider
            logger.debug("[LLM_POOL] Lazily registered provider: %s", normalized)
            return provider
        except Exception as exc:
            logger.warning("[LLM_POOL] Failed to lazily register provider %s: %s", normalized, exc)
            return None

    @classmethod
    def _get_request_provider_chain(cls, provider: Optional[str] = None) -> list[str]:
        """Build request-scoped provider order with the requested provider first."""
        return get_request_provider_chain_impl(
            provider=provider,
            active_provider=cls._active_provider,
            get_provider_chain=cls._get_provider_chain,
            ensure_provider=cls._ensure_provider,
            normalize_provider=cls._normalize_provider,
        )

    @classmethod
    def _thinking_budget_for_tier(cls, tier_key: str) -> tuple[int, bool]:
        """Return thinking budget + thought flag for one tier."""
        return thinking_budget_for_tier_impl(
            thinking_budgets=THINKING_BUDGETS,
            tier_key=tier_key,
        )

    @classmethod
    def _create_provider_instance(
        cls,
        provider_name: str,
        tier_key: str,
        *,
        requested_provider: Optional[str] = None,
    ) -> Any | None:
        return create_provider_instance_impl(
            cls_ref=cls,
            provider_name=provider_name,
            tier_key=tier_key,
            requested_provider=requested_provider,
        )

    @classmethod
    def get_provider_instance(
        cls,
        provider_name: Optional[str],
        tier=None,
        *,
        allow_unavailable: bool = False,
        requested_provider: Optional[str] = None,
    ) -> Any | None:
        return get_provider_instance_impl(
            cls_ref=cls,
            provider_name=provider_name,
            tier=tier,
            allow_unavailable=allow_unavailable,
            requested_provider=requested_provider,
            logger_obj=logger,
        )

    @classmethod
    def _init_providers(cls) -> None:
        init_providers_impl(
            cls_ref=cls,
            settings_obj=settings,
            is_supported_provider_fn=is_supported_provider,
            create_provider_fn=create_provider,
            logger_obj=logger,
        )

    @classmethod
    def initialize(cls) -> None:
        """Pre-warm all LLM tiers at application startup."""
        initialize_pool_impl(
            cls_ref=cls,
            settings_obj=settings,
            logger_obj=logger,
            thinking_tier=ThinkingTier,
        )

    @classmethod
    def _create_instance(cls, tier) -> Any:
        return create_primary_instance_impl(
            cls_ref=cls,
            tier=tier,
            settings_obj=settings,
            logger_obj=logger,
            thinking_budgets=THINKING_BUDGETS,
        )

    @classmethod
    def _create_fallback_instances(cls) -> None:
        create_fallback_instances_impl(
            cls_ref=cls,
            settings_obj=settings,
            logger_obj=logger,
            thinking_tier=ThinkingTier,
            thinking_budgets=THINKING_BUDGETS,
        )

    @classmethod
    def get_fallback(cls, tier=None) -> Optional[Any]:
        """Get the pre-created fallback LLM for runtime failover."""
        return get_fallback_impl(
            cls_ref=cls,
            tier=tier,
            thinking_tier=ThinkingTier,
        )

    @classmethod
    def _create_instance_legacy(
        cls, tier_key: str, thinking_budget: int, include_thoughts: bool
    ) -> Any:
        return create_instance_legacy_impl(
            cls_ref=cls,
            tier_key=tier_key,
            thinking_budget=thinking_budget,
            include_thoughts=include_thoughts,
            settings_obj=settings,
            create_provider_fn=create_provider,
            logger_obj=logger,
        )

    @classmethod
    def get_provider_info(cls, name: str):
        """Public API: get a registered provider by name."""
        return get_provider_info_impl(cls_ref=cls, name=name)

    @classmethod
    def get(cls, tier=None) -> Any:
        """Get a shared LLM instance for the specified tier."""
        return get_pool_llm_impl(
            cls_ref=cls,
            tier=tier,
            thinking_tier=ThinkingTier,
            logger_obj=logger,
        )

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the pool has been initialized."""
        return cls._initialized

    @classmethod
    def get_active_provider(cls) -> Optional[str]:
        """Get the name of the currently active provider."""
        return cls._active_provider

    @classmethod
    def get_request_selectable_providers(cls) -> list[str]:
        """Return providers that should be exposed in request-level switchers."""
        if not cls._providers:
            cls._init_providers()
        return get_request_selectable_providers_impl(
            providers=cls._providers,
            openrouter_legacy_slot=is_openrouter_legacy_slot_configured(settings),
            get_request_provider_chain=cls._get_request_provider_chain,
            ensure_provider=cls._ensure_provider,
        )

    @classmethod
    def get_fallback_for_provider(
        cls,
        provider_name: Optional[str],
        tier=None,
        *,
        failover_mode: str = FAILOVER_MODE_AUTO,
        prefer_selectable_only: bool = False,
        allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> tuple[Optional[str], Optional[Any]]:
        """Return the next available provider/LLM for one request route."""
        normalized_allowed_fallbacks: set[str] | None = None
        if allowed_fallback_providers:
            normalized_allowed_fallbacks = {
                normalized
                for raw_name in allowed_fallback_providers
                for normalized in [cls._normalize_provider(raw_name)]
                if normalized
            } or None
        return get_fallback_for_provider_impl(
            provider_name=provider_name,
            tier=tier,
            failover_mode=failover_mode,
            prefer_selectable_only=prefer_selectable_only,
            allowed_fallback_providers=normalized_allowed_fallbacks,
            auto_mode=FAILOVER_MODE_AUTO,
            pinned_mode=FAILOVER_MODE_PINNED,
            fallback_provider=cls._fallback_provider,
            active_provider=cls._active_provider,
            thinking_tier=ThinkingTier,
            normalize_failover_mode=cls._normalize_failover_mode,
            normalize_tier_key=cls._normalize_tier_key,
            normalize_provider=cls._normalize_provider,
            get_request_provider_chain=cls._get_request_provider_chain,
            get_selectable_provider_names=cls._get_selectable_provider_names,
            get_provider_instance=cls.get_provider_instance,
        )

    @classmethod
    def resolve_runtime_route(
        cls,
        provider_name: Optional[str],
        tier=None,
        *,
        failover_mode: str = FAILOVER_MODE_AUTO,
        prefer_selectable_fallback: bool = False,
        allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> ResolvedLLMRoute:
        """Resolve a request-scoped primary/fallback route for failover helpers."""
        normalized_allowed_fallbacks: set[str] | None = None
        if allowed_fallback_providers:
            normalized_allowed_fallbacks = {
                normalized
                for raw_name in allowed_fallback_providers
                for normalized in [cls._normalize_provider(raw_name)]
                if normalized
            } or None
        return resolve_runtime_route_impl(
            provider_name=provider_name,
            tier=tier or ThinkingTier.MODERATE,
            failover_mode=failover_mode,
            prefer_selectable_fallback=prefer_selectable_fallback,
            allowed_fallback_providers=normalized_allowed_fallbacks,
            auto_mode=FAILOVER_MODE_AUTO,
            resolved_route_cls=ResolvedLLMRoute,
            provider_unavailable_error_cls=ProviderUnavailableError,
            active_provider=cls._active_provider,
            normalize_tier_key=cls._normalize_tier_key,
            normalize_provider=cls._normalize_provider,
            normalize_failover_mode=cls._normalize_failover_mode,
            get_provider_instance=cls.get_provider_instance,
            get_fallback_for_provider=cls.get_fallback_for_provider,
            get_circuit_breaker_for_provider=cls.get_circuit_breaker_for_provider,
            resolve_auto_primary_provider=cls._resolve_auto_primary_provider,
            get_selectable_provider_names=cls._get_selectable_provider_names,
            get_default_llm=cls.get,
            logger_obj=logger,
        )

    @classmethod
    def get_stats(cls) -> dict:
        """Get pool statistics for monitoring."""
        return get_stats_public_impl(
            cls_ref=cls,
            settings_obj=settings,
            gemini_cb=_gemini_cb,
            logger_obj=logger,
        )

    @classmethod
    def _get_stats_core(cls, *, settings_obj, gemini_cb) -> dict:
        return get_stats_impl(
            initialized=cls._initialized,
            pool=cls._pool,
            fallback_pool=cls._fallback_pool,
            active_provider=cls._active_provider,
            fallback_provider=cls._fallback_provider,
            failover_enabled=settings_obj.enable_llm_failover,
            get_provider_chain=cls._get_provider_chain,
            providers=cls._providers,
            get_request_selectable_providers=cls.get_request_selectable_providers,
            gemini_cb=gemini_cb,
        )

    @classmethod
    def is_available(cls) -> bool:
        """Check if any LLM provider is likely available."""
        return is_available_public_impl(
            cls_ref=cls,
            settings_obj=settings,
            gemini_cb=_gemini_cb,
        )

    @classmethod
    def _is_available_core(cls, *, failover_enabled: bool, gemini_cb) -> bool:
        return is_available_impl(
            failover_enabled=failover_enabled,
            providers=cls._providers,
            gemini_cb=gemini_cb,
        )

    @classmethod
    async def record_success_for_provider(cls, provider_name: Optional[str]) -> None:
        """Record a successful call for a specific runtime provider."""
        await record_provider_success_impl(
            provider_name=provider_name,
            active_provider=cls._active_provider,
            providers=cls._providers,
            normalize_provider=cls._normalize_provider,
            gemini_cb=_gemini_cb,
        )

    @classmethod
    async def record_success(cls) -> None:
        """Record a successful API call for the active provider."""
        await cls.record_success_for_provider(cls._active_provider)

    @classmethod
    async def record_failure_for_provider(cls, provider_name: Optional[str]) -> None:
        """Record a failed call for a specific runtime provider."""
        await record_provider_failure_impl(
            provider_name=provider_name,
            active_provider=cls._active_provider,
            providers=cls._providers,
            normalize_provider=cls._normalize_provider,
            gemini_cb=_gemini_cb,
        )

    @classmethod
    async def record_failure(cls) -> None:
        """Record a failed API call for the active provider."""
        await cls.record_failure_for_provider(cls._active_provider)

    @classmethod
    def get_circuit_breaker_for_provider(cls, provider_name: Optional[str]):
        """Get the circuit breaker associated with a specific provider."""
        return get_circuit_breaker_for_provider_impl(
            provider_name=provider_name,
            active_provider=cls._active_provider,
            normalize_provider=cls._normalize_provider,
            ensure_provider=cls._ensure_provider,
            gemini_cb=_gemini_cb,
        )

    @classmethod
    def get_circuit_breaker(cls):
        """
        Get the circuit breaker for the active provider.

        Returns:
            CircuitBreaker instance or None
        """
        return cls.get_circuit_breaker_for_provider(cls._active_provider)

    @classmethod
    def create_llm_with_model_for_provider(
        cls,
        provider_name: str,
        model_name: str,
        tier: ThinkingTier,
    ) -> Any | None:
        """Create a dedicated provider-scoped LLM instance for a specific model name.

        Used for grouped admin profiles and per-agent model overrides.
        Caches by provider + model + tier to avoid re-creation.
        """
        return create_llm_with_model_for_provider_impl(
            provider_name=provider_name,
            model_name=model_name,
            tier=tier,
            pool=cls._pool,
            thinking_budgets=THINKING_BUDGETS,
            thinking_tier_cls=ThinkingTier,
            normalize_provider=cls._normalize_provider,
            ensure_provider=cls._ensure_provider,
            tag_runtime_metadata=cls._tag_runtime_metadata,
            logger_obj=logger,
        )

    @classmethod
    def create_llm_with_model(cls, model_name: str, tier: ThinkingTier) -> Any | None:
        """Backward-compatible helper for Google-only custom model overrides."""
        return cls.create_llm_with_model_for_provider("google", model_name, tier)

    @classmethod
    def resolve_same_provider_model_fallback(
        cls,
        provider_name: Optional[str],
        tier,
        *,
        current_model_name: Optional[str] = None,
    ) -> dict[str, str] | None:
        """Return a lower-latency same-provider fallback plan when safe."""
        return resolve_same_provider_model_fallback_impl(
            provider_name=provider_name,
            tier_key=cls._normalize_tier_key(tier),
            current_model_name=current_model_name,
            settings_obj=settings,
            thinking_tier_cls=ThinkingTier,
            normalize_provider=cls._normalize_provider,
            is_model_degraded_fn=is_model_degraded,
        )

    @classmethod
    def reset(cls) -> None:
        """
        Reset the pool state (for testing purposes).

        Clears all instances, providers, and resets initialization flag.
        """
        reset_pool_state_impl(
            pool=cls._pool,
            fallback_pool=cls._fallback_pool,
            provider_pools=cls._provider_pools,
            providers=cls._providers,
        )
        cls._initialized = False
        cls._active_provider = None
        cls._fallback_provider = None
        reset_model_health_state()


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================
_PRIMARY_TIMEOUT = 12.0

TIMEOUT_PROFILE_STRUCTURED = "structured"
TIMEOUT_PROFILE_BACKGROUND = "background"


def _effort_to_tier(effort: Optional[str], default_tier):
    mapping = {
        "low": ThinkingTier.LIGHT,
        "medium": ThinkingTier.MODERATE,
        "high": ThinkingTier.DEEP,
        "max": ThinkingTier.DEEP,
    }
    return mapping.get(effort or "", default_tier)


def get_llm_deep() -> Any:
    return LLMPool.get(ThinkingTier.DEEP)


def get_llm_moderate() -> Any:
    return LLMPool.get(ThinkingTier.MODERATE)


def get_llm_light() -> Any:
    return LLMPool.get(ThinkingTier.LIGHT)


def get_llm_for_effort(
    effort: Optional[str],
    default_tier=None,
) -> Any:
    resolved_default = default_tier or ThinkingTier.MODERATE
    if not effort:
        return LLMPool.get(resolved_default)
    return LLMPool.get(_effort_to_tier(effort, resolved_default))


def get_llm_for_provider(
    provider: Optional[str],
    effort: Optional[str] = None,
    default_tier=None,
    *,
    strict_pin: bool = False,
) -> Any:
    resolved_default = default_tier or ThinkingTier.MODERATE
    tier = _effort_to_tier(effort, resolved_default) if effort else resolved_default

    normalized_provider = LLMPool._normalize_provider(provider)
    if normalized_provider and not strict_pin:
        provider_llm = LLMPool.get_provider_instance(
            normalized_provider,
            tier,
            allow_unavailable=True,
            requested_provider=None,
        )
        if provider_llm is not None:
            return provider_llm

    route = LLMPool.resolve_runtime_route(
        provider,
        tier,
        failover_mode=FAILOVER_MODE_PINNED if strict_pin else FAILOVER_MODE_AUTO,
    )
    return route.llm


def get_llm_fallback(
    tier: Optional[str] = "moderate",
) -> Optional[Any]:
    return LLMPool.get_fallback(tier)


def is_rate_limit_error(error: Exception) -> bool:
    return is_rate_limit_error_impl(error)


def resolve_primary_timeout_seconds(
    *,
    tier: str = "moderate",
    timeout_profile: Optional[str] = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
) -> float | None:
    return resolve_primary_timeout_seconds_impl(
        tier=tier,
        timeout_profile=timeout_profile,
        provider=provider,
        settings_obj=settings,
        timeout_profile_by_name=TIMEOUT_PROFILE_BY_NAME,
        timeout_profile_settings=TIMEOUT_PROFILE_SETTINGS,
        loads_timeout_provider_overrides_fn=loads_timeout_provider_overrides,
        primary_timeout_default=_PRIMARY_TIMEOUT,
        pool_cls=LLMPool,
        timeout_profile_structured=TIMEOUT_PROFILE_STRUCTURED,
        timeout_profile_background=TIMEOUT_PROFILE_BACKGROUND,
        model_name=model_name,
    )


async def ainvoke_with_failover(
    llm,
    messages,
    *,
    tier: str = "moderate",
    provider: Optional[str] = None,
    failover_mode: str = "auto",
    prefer_selectable_fallback: bool = False,
    allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    on_primary=None,
    on_fallback=None,
    on_switch=None,
    on_failover=None,
    primary_timeout: Optional[float] = None,
    timeout_profile: Optional[str] = None,
):
    return await ainvoke_with_failover_impl(
        llm,
        messages,
        tier=tier,
        provider=provider,
        failover_mode=failover_mode,
        prefer_selectable_fallback=prefer_selectable_fallback,
        allowed_fallback_providers=allowed_fallback_providers,
        on_primary=on_primary,
        on_fallback=on_fallback,
        on_switch=on_switch,
        on_failover=on_failover,
        primary_timeout=primary_timeout,
        timeout_profile=timeout_profile,
        pool_cls=LLMPool,
        resolve_primary_timeout_seconds_fn=resolve_primary_timeout_seconds,
        is_rate_limit_error_fn=is_rate_limit_error,
        is_failover_eligible_error_fn=is_failover_eligible_error_impl,
        logger_obj=logger,
        failover_mode_pinned=FAILOVER_MODE_PINNED,
        provider_unavailable_error_cls=ProviderUnavailableError,
        resolve_same_provider_model_fallback_fn=LLMPool.resolve_same_provider_model_fallback,
        create_llm_with_model_for_provider_fn=LLMPool.create_llm_with_model_for_provider,
        thinking_tier_cls=ThinkingTier,
    )


register_llm_runtime_access(
    get_stats=LLMPool.get_stats,
    get_provider_info=LLMPool.get_provider_info,
    get_request_selectable_providers=LLMPool.get_request_selectable_providers,
)
