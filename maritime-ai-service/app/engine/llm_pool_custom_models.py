"""Custom model helpers for LLMPool."""

from __future__ import annotations

from app.engine.llm_model_health import is_model_degraded


def create_llm_with_model_for_provider_impl(
    *,
    provider_name: str,
    model_name: str,
    tier,
    pool,
    thinking_budgets,
    thinking_tier_cls,
    normalize_provider,
    ensure_provider,
    tag_runtime_metadata,
    logger_obj,
):
    normalized_provider = normalize_provider(provider_name)
    if not normalized_provider:
        return None

    def tag_custom_runtime(llm, resolved_model_name: str):
        return tag_runtime_metadata(
            llm,
            provider_name=normalized_provider,
            tier_key=tier.value,
            requested_provider=normalized_provider,
            model_name=resolved_model_name,
        )

    requested_cache_key = f"_custom_{normalized_provider}_{model_name}_{tier.value}"
    if requested_cache_key in pool:
        if not is_model_degraded(normalized_provider, model_name):
            return tag_custom_runtime(pool[requested_cache_key], model_name)
        pool.pop(requested_cache_key, None)

    thinking_budget = thinking_budgets.get(tier.value, 4096)
    include_thoughts = tier in (
        thinking_tier_cls.DEEP,
        thinking_tier_cls.MODERATE,
    )

    try:
        provider = ensure_provider(normalized_provider)
        if provider is None or not provider.is_configured():
            return None

        selected_model_name = model_name
        if is_model_degraded(normalized_provider, model_name):
            model_selector = getattr(provider, "_select_healthy_model", None)
            if callable(model_selector):
                selected = model_selector(tier=tier.value, model=model_name)
                if isinstance(selected, str) and selected.strip():
                    selected_model_name = selected.strip()

            if (
                selected_model_name == model_name
                or is_model_degraded(normalized_provider, selected_model_name)
            ):
                logger_obj.warning(
                    "[LLM_POOL] Refusing degraded custom model without healthy "
                    "alternative: provider=%s model=%s tier=%s",
                    normalized_provider,
                    model_name,
                    tier.value,
                )
                return None

            logger_obj.info(
                "[LLM_POOL] Custom model %s/%s is degraded; using healthy alternative %s",
                normalized_provider,
                model_name,
                selected_model_name,
            )

        cache_key = f"_custom_{normalized_provider}_{selected_model_name}_{tier.value}"
        if cache_key in pool:
            return tag_custom_runtime(pool[cache_key], selected_model_name)

        llm = provider.create_instance(
            tier=tier.value,
            thinking_budget=thinking_budget,
            include_thoughts=include_thoughts,
            temperature=0.5,
            model_name=selected_model_name,
        )
        llm = tag_custom_runtime(llm, selected_model_name)
        pool[cache_key] = llm
        logger_obj.info(
            "[LLM_POOL] Created custom model LLM: provider=%s model=%s tier=%s budget=%d",
            normalized_provider,
            selected_model_name,
            tier.value,
            thinking_budget,
        )
        return llm
    except Exception as exc:
        logger_obj.warning(
            "[LLM_POOL] Custom model %s/%s failed: %s",
            normalized_provider,
            model_name,
            exc,
        )
        return None
