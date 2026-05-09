"""Facade/runtime helpers extracted from llm_pool.py."""

from __future__ import annotations

from typing import Any, Optional

from app.engine.llm_model_health import is_model_degraded
from app.engine.llm_same_provider_runtime import extract_runtime_model_name_impl


def _cached_pool_llm_is_degraded(provider_name: str | None, llm: Any | None) -> bool:
    if not provider_name:
        return False
    return is_model_degraded(provider_name, extract_runtime_model_name_impl(llm))


def initialize_pool_impl(
    *,
    cls_ref,
    settings_obj,
    logger_obj,
    thinking_tier,
) -> None:
    """Initialize the shared pool once and pre-create primary/fallback tiers."""
    if cls_ref._initialized:
        logger_obj.info("[LLM_POOL] Already initialized, skipping")
        return

    cls_ref._init_providers()

    for tier in [thinking_tier.DEEP, thinking_tier.MODERATE, thinking_tier.LIGHT]:
        cls_ref._create_instance(tier)

    cls_ref._create_fallback_instances()
    cls_ref._initialized = True
    fallback_info = f", fallback={cls_ref._fallback_provider}" if cls_ref._fallback_provider else ""
    logger_obj.info(
        "[LLM_POOL] Initialized with %d primary + %d fallback instances "
        "(DEEP, MODERATE, LIGHT) -- provider=%s%s",
        len(cls_ref._pool),
        len(cls_ref._fallback_pool),
        cls_ref._active_provider,
        fallback_info,
    )


def get_fallback_impl(*, cls_ref, tier=None, thinking_tier=None):
    """Return the pre-created fallback LLM for one tier, if available."""
    if not cls_ref._fallback_pool:
        return None

    if tier is None:
        tier = thinking_tier.MODERATE

    tier_key = cls_ref._resolve_tier(tier)
    if tier_key in [thinking_tier.MINIMAL.value, thinking_tier.OFF.value]:
        tier_key = thinking_tier.LIGHT.value

    return cls_ref._fallback_pool.get(tier_key)


def get_provider_info_impl(*, cls_ref, name: str):
    """Public API: get a registered provider by name."""
    if not cls_ref._providers:
        cls_ref._init_providers()
    return cls_ref._providers.get(name)


def get_pool_llm_impl(*, cls_ref, tier=None, thinking_tier=None, logger_obj=None):
    """Return a shared pooled LLM instance for the requested tier."""
    if tier is None:
        tier = thinking_tier.MODERATE

    if not cls_ref._initialized:
        cls_ref.initialize()

    tier_key = cls_ref._resolve_tier(tier)
    if tier_key in [thinking_tier.MINIMAL.value, thinking_tier.OFF.value]:
        tier_key = thinking_tier.LIGHT.value

    if tier_key not in cls_ref._pool:
        logger_obj.warning("[LLM_POOL] Tier %s not in pool, creating on-demand", tier_key)
        cls_ref._create_instance(tier_key)
    else:
        cached_llm = cls_ref._pool[tier_key]
        cached_provider = getattr(cached_llm, "_wiii_provider_name", None) or cls_ref._active_provider
        if _cached_pool_llm_is_degraded(cached_provider, cached_llm):
            cls_ref._pool.pop(tier_key, None)
            cls_ref._provider_pools.get(cached_provider, {}).pop(tier_key, None)
            logger_obj.warning(
                "[LLM_POOL] Dropped degraded cached LLM for %s/%s",
                cached_provider,
                tier_key,
            )
            cls_ref._create_instance(tier_key)

    return cls_ref._pool[tier_key]


def get_stats_public_impl(*, cls_ref, settings_obj, gemini_cb, logger_obj):
    """Get monitoring statistics for the current pool."""
    if not cls_ref._providers:
        try:
            cls_ref._init_providers()
        except Exception as exc:
            logger_obj.debug("[LLM_POOL] get_stats() could not init providers: %s", exc)
    return cls_ref._get_stats_core(settings_obj=settings_obj, gemini_cb=gemini_cb)


def is_available_public_impl(*, cls_ref, settings_obj, gemini_cb):
    """Check whether any configured LLM provider is currently available."""
    return cls_ref._is_available_core(
        failover_enabled=settings_obj.enable_llm_failover,
        gemini_cb=gemini_cb,
    )
