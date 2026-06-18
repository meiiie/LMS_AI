"""Bootstrap/runtime helpers extracted from LLMPool."""

from __future__ import annotations

from typing import Any, Optional


from app.engine.llm_model_health import is_model_degraded
from app.engine.llm_same_provider_runtime import extract_runtime_model_name_impl


def _cached_llm_is_degraded(provider_name: str, llm: Any | None) -> bool:
    model_name = extract_runtime_model_name_impl(llm)
    return is_model_degraded(provider_name, model_name)


def _drop_cached_tier(cls_ref, provider_name: str, tier_key: str) -> None:
    cls_ref._provider_pools.get(provider_name, {}).pop(tier_key, None)
    if provider_name == cls_ref._active_provider:
        cls_ref._pool.pop(tier_key, None)
    if provider_name == cls_ref._fallback_provider:
        cls_ref._fallback_pool.pop(tier_key, None)


def create_provider_instance_impl(
    *,
    cls_ref,
    provider_name: str,
    tier_key: str,
    requested_provider: Optional[str] = None,
) -> Any | None:
    """Create and cache a provider-specific LLM instance on demand."""
    provider = cls_ref._ensure_provider(provider_name)
    if provider is None or not provider.is_configured():
        return None

    provider_cache = cls_ref._provider_pools.setdefault(provider_name, {})
    if tier_key in provider_cache:
        cached_llm = provider_cache[tier_key]
        if not _cached_llm_is_degraded(provider_name, cached_llm):
            return cached_llm
        _drop_cached_tier(cls_ref, provider_name, tier_key)
        provider_cache = cls_ref._provider_pools.setdefault(provider_name, {})

    thinking_budget, include_thoughts = cls_ref._thinking_budget_for_tier(tier_key)
    llm = provider.create_instance(
        tier=tier_key,
        thinking_budget=thinking_budget,
        include_thoughts=include_thoughts,
        temperature=0.5,
    )
    cls_ref._attach_tracking_callback(llm, f"{provider_name}_{tier_key}")
    llm = cls_ref._tag_runtime_metadata(
        llm,
        provider_name=provider_name,
        tier_key=tier_key,
        requested_provider=requested_provider,
    )
    provider_cache[tier_key] = llm
    return llm


def get_provider_instance_impl(
    *,
    cls_ref,
    provider_name: Optional[str],
    tier=None,
    allow_unavailable: bool = False,
    requested_provider: Optional[str] = None,
    logger_obj,
) -> Any | None:
    """Return a provider-specific instance, creating one lazily when needed."""
    normalized_provider = cls_ref._normalize_provider(provider_name)
    if not normalized_provider:
        return None

    tier_key = cls_ref._normalize_tier_key(tier or cls_ref._thinking_tier.MODERATE)
    provider = cls_ref._ensure_provider(normalized_provider)
    if provider is None:
        return None
    if not allow_unavailable and not provider.is_available():
        return None

    if normalized_provider == cls_ref._active_provider and tier_key in cls_ref._pool:
        llm = cls_ref._pool[tier_key]
        if _cached_llm_is_degraded(normalized_provider, llm):
            _drop_cached_tier(cls_ref, normalized_provider, tier_key)
        else:
            cls_ref._provider_pools.setdefault(normalized_provider, {})[tier_key] = llm
            return cls_ref._tag_runtime_metadata(
                llm,
                provider_name=normalized_provider,
                tier_key=tier_key,
                requested_provider=requested_provider,
            )

    if normalized_provider == cls_ref._fallback_provider and tier_key in cls_ref._fallback_pool:
        llm = cls_ref._fallback_pool[tier_key]
        if _cached_llm_is_degraded(normalized_provider, llm):
            _drop_cached_tier(cls_ref, normalized_provider, tier_key)
        else:
            cls_ref._provider_pools.setdefault(normalized_provider, {})[tier_key] = llm
            return cls_ref._tag_runtime_metadata(
                llm,
                provider_name=normalized_provider,
                tier_key=tier_key,
                requested_provider=requested_provider,
            )

    provider_cache = cls_ref._provider_pools.get(normalized_provider, {})
    if tier_key in provider_cache:
        llm = provider_cache[tier_key]
        if not _cached_llm_is_degraded(normalized_provider, llm):
            return cls_ref._tag_runtime_metadata(
                llm,
                provider_name=normalized_provider,
                tier_key=tier_key,
                requested_provider=requested_provider,
            )
        _drop_cached_tier(cls_ref, normalized_provider, tier_key)

    try:
        return cls_ref._create_provider_instance(
            normalized_provider,
            tier_key,
            requested_provider=requested_provider,
        )
    except Exception as exc:
        logger_obj.warning(
            "[LLM_POOL] Provider-specific instance failed (%s/%s): %s",
            normalized_provider,
            tier_key,
            exc,
        )
        return None


def init_providers_impl(*, cls_ref, settings_obj, is_supported_provider_fn, create_provider_fn, logger_obj) -> None:
    """Initialize provider instances from the failover chain config."""
    if cls_ref._providers:
        return

    chain = cls_ref._get_provider_chain()
    logger_obj.info(
        "[LLM_POOL] Initializing provider chain: %s (preferred=%s, failover=%s)",
        chain,
        getattr(settings_obj, "llm_provider", "?"),
        getattr(settings_obj, "llm_failover_chain", "?"),
    )
    for name in chain:
        if not is_supported_provider_fn(name):
            logger_obj.warning("[LLM_POOL] Skipping unsupported provider in chain: %s", name)
            continue
        try:
            cls_ref._providers[name] = create_provider_fn(name)
            logger_obj.info("[LLM_POOL] Registered provider: %s", name)
        except Exception as exc:
            logger_obj.warning("[LLM_POOL] Failed to register provider %s: %s", name, exc)

    logger_obj.info(
        "[LLM_POOL] Provider chain: %s (failover=%s)",
        list(cls_ref._providers.keys()),
        "enabled" if settings_obj.enable_llm_failover else "disabled",
    )


def create_primary_instance_impl(*, cls_ref, tier, settings_obj, logger_obj, thinking_budgets) -> Any:
    """Create the shared primary LLM instance for one tier."""
    tier_key = cls_ref._resolve_tier(tier)

    if tier_key in cls_ref._pool:
        cached_llm = cls_ref._pool[tier_key]
        cached_provider = getattr(cached_llm, "_wiii_provider_name", None) or cls_ref._active_provider
        if cached_provider and _cached_llm_is_degraded(cached_provider, cached_llm):
            _drop_cached_tier(cls_ref, cached_provider, tier_key)
        else:
            return cached_llm

    thinking_budget, include_thoughts = cls_ref._thinking_budget_for_tier(tier_key)
    should_use_provider_chain = cls_ref._providers and (
        settings_obj.enable_llm_failover or settings_obj.llm_provider != "google"
    )

    if should_use_provider_chain:
        chain = cls_ref._get_provider_chain()
        errors = []

        for provider_name in chain:
            provider = cls_ref._providers.get(provider_name)
            if provider is None:
                continue
            if not provider.is_available():
                logger_obj.debug("[LLM_POOL] Provider %s not available, skipping", provider_name)
                continue

            try:
                llm = provider.create_instance(
                    tier=tier_key,
                    thinking_budget=thinking_budget,
                    include_thoughts=include_thoughts,
                    temperature=0.5,
                )
                cls_ref._attach_tracking_callback(llm, tier_key)
                llm = cls_ref._tag_runtime_metadata(
                    llm,
                    provider_name=provider_name,
                    tier_key=tier_key,
                )
                cls_ref._pool[tier_key] = llm
                cls_ref._provider_pools.setdefault(provider_name, {})[tier_key] = llm
                cls_ref._active_provider = provider_name
                logger_obj.info(
                    "[LLM_POOL] Created %s via %s (budget=%d, thoughts=%s)",
                    tier_key.upper(),
                    provider_name,
                    thinking_budget,
                    include_thoughts,
                )
                return llm
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")
                logger_obj.warning(
                    "[LLM_POOL] Provider %s failed for %s: %s",
                    provider_name,
                    tier_key,
                    exc,
                )
                continue

        error_detail = "; ".join(errors) if errors else "no providers available"
        raise RuntimeError(
            f"[LLM_POOL] All providers failed for tier {tier_key}: {error_detail}"
        )

    return cls_ref._create_instance_legacy(tier_key, thinking_budget, include_thoughts)


def create_fallback_instances_impl(*, cls_ref, settings_obj, logger_obj, thinking_tier, thinking_budgets) -> None:
    """Pre-create fallback LLM instances from the next available provider."""
    if not settings_obj.enable_llm_failover or not cls_ref._providers:
        return

    chain = cls_ref._get_provider_chain()

    for name in chain:
        if name == cls_ref._active_provider:
            continue
        provider = cls_ref._providers.get(name)
        if provider is None or not provider.is_available():
            continue

        created = 0
        for tier in [thinking_tier.DEEP, thinking_tier.MODERATE, thinking_tier.LIGHT]:
            tier_key = tier.value
            thinking_budget, include_thoughts = cls_ref._thinking_budget_for_tier(tier_key)
            try:
                llm = provider.create_instance(
                    tier=tier_key,
                    thinking_budget=thinking_budget,
                    include_thoughts=include_thoughts,
                    temperature=0.5,
                )
                cls_ref._attach_tracking_callback(llm, f"fallback_{tier_key}")
                llm = cls_ref._tag_runtime_metadata(
                    llm,
                    provider_name=name,
                    tier_key=tier_key,
                )
                cls_ref._fallback_pool[tier_key] = llm
                cls_ref._provider_pools.setdefault(name, {})[tier_key] = llm
                created += 1
            except Exception as exc:
                logger_obj.warning(
                    "[LLM_POOL] Fallback %s/%s failed: %s",
                    name,
                    tier_key,
                    exc,
                )

        if created > 0:
            cls_ref._fallback_provider = name
            logger_obj.info(
                "[LLM_POOL] Pre-created %d fallback instances via %s",
                created,
                name,
            )
            return
