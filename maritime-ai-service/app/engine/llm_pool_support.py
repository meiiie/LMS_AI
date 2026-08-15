"""Support helpers for LLMPool normalization and provider selection."""

from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


def get_provider_chain_impl(*, preferred_provider: Optional[str], configured_chain: list[str]) -> list[str]:
    """Return the effective provider order with the selected provider first."""
    chain: list[str] = []
    if preferred_provider:
        chain.append(preferred_provider)

    for provider_name in configured_chain:
        if provider_name not in chain:
            chain.append(provider_name)

    return chain


def normalize_provider_impl(provider: Optional[str]) -> Optional[str]:
    """Normalize request provider names and collapse ``auto`` to None."""
    if not provider:
        return None
    normalized = str(provider).strip().lower()
    if not normalized or normalized == "auto":
        return None
    return normalized


def normalize_failover_mode_impl(failover_mode: Optional[str], *, auto_mode: str, pinned_mode: str) -> str:
    normalized = str(failover_mode or auto_mode).strip().lower()
    if normalized == pinned_mode:
        return pinned_mode
    return auto_mode


def normalize_tier_key_impl(*, tier, resolve_tier, thinking_tier) -> str:
    """Map helper tiers to the shared pool keys."""
    tier_key = resolve_tier(tier)
    if tier_key in [thinking_tier.MINIMAL.value, thinking_tier.OFF.value]:
        return thinking_tier.LIGHT.value
    return tier_key


def thinking_budget_for_tier_impl(*, thinking_budgets: dict, tier_key: str) -> tuple[int, bool]:
    """Return thinking budget + thought flag for one tier."""
    thinking_budget = thinking_budgets.get(tier_key, 1024)
    include_thoughts = thinking_budget > 0
    return thinking_budget, include_thoughts


def tag_runtime_metadata_impl(
    llm,
    *,
    provider_name: str,
    tier_key: str,
    requested_provider: Optional[str] = None,
    model_name: Optional[str] = None,
    logger_obj=None,
):
    """Attach lightweight runtime metadata for downstream failover helpers."""
    logger_ref = logger_obj or logger
    try:
        setattr(llm, "_wiii_provider_name", provider_name)
        setattr(llm, "_wiii_tier_key", tier_key)
        setattr(llm, "_wiii_requested_provider", requested_provider)
        if model_name:
            setattr(llm, "_wiii_model_name", model_name)
    except Exception:
        logger_ref.debug("[LLM_POOL] Could not tag runtime metadata for provider=%s", provider_name)
    return llm


def get_selectable_provider_names_impl(*, normalize_provider, logger_obj=None) -> Optional[set[str]]:
    """Return the current selectable providers from user-facing runtime truth."""
    logger_ref = logger_obj or logger
    try:
        from app.services.llm_selectability_service import (
            get_llm_selectability_snapshot,
        )

        return {
            provider
            for item in get_llm_selectability_snapshot()
            if item.state == "selectable"
            for provider in [normalize_provider(item.provider)]
            if provider
        }
    except Exception as exc:
        logger_ref.debug("[LLM_POOL] Selectable provider lookup skipped: %s", exc)
        return None


def get_request_provider_chain_impl(
    *,
    provider: Optional[str],
    active_provider: Optional[str],
    get_provider_chain,
    ensure_provider,
    normalize_provider,
) -> list[str]:
    """Build request-scoped provider order with the requested provider first."""
    configured: list[str] = []
    for name in get_provider_chain():
        if ensure_provider(name) is not None and name not in configured:
            configured.append(name)

    requested = normalize_provider(provider)
    primary = requested or active_provider

    chain: list[str] = []
    if primary and ensure_provider(primary) is not None:
        chain.append(primary)

    for name in configured:
        if name not in chain:
            chain.append(name)

    return chain


def resolve_auto_primary_provider_impl(
    *,
    preferred_provider: Optional[str],
    active_provider: Optional[str],
    normalize_provider,
    get_request_provider_chain,
    get_selectable_provider_names,
    ensure_provider,
    logger_obj=None,
) -> Optional[str]:
    """Prefer a provider that is currently selectable for auto mode."""
    logger_ref = logger_obj or logger
    try:
        from app.services.llm_selectability_service import (
            choose_best_runtime_provider,
        )

        best = choose_best_runtime_provider(
            preferred_provider=preferred_provider or active_provider,
            provider_order=get_request_provider_chain(),
            allow_degraded_fallback=False,
        )
        provider = normalize_provider(best.provider if best else None)
        if provider:
            return provider
    except Exception as exc:
        logger_ref.debug("[LLM_POOL] Auto provider preselection skipped: %s", exc)

    selectable_names = get_selectable_provider_names()
    chain = get_request_provider_chain()
    for provider_name in chain:
        normalized_name = normalize_provider(provider_name)
        if selectable_names is not None and normalized_name not in selectable_names:
            continue
        provider = ensure_provider(provider_name)
        if provider is None or not provider.is_configured() or not provider.is_available():
            continue
        return provider_name
    return None
