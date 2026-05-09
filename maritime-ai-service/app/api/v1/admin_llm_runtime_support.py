"""Runtime support for admin LLM runtime helper shells."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from app.engine.openai_compatible_credentials import (
    resolve_nvidia_model,
    resolve_openrouter_base_url,
    resolve_openrouter_model,
    resolve_openrouter_model_advanced,
)


async def build_model_catalog_response_runtime_impl(
    *,
    run_live_probe: bool = False,
    probe_providers: Optional[list[str]] = None,
    settings_obj,
    build_provider_runtime_statuses_fn,
    build_provider_catalog_capabilities_fn,
    model_catalog_entry_cls,
    model_catalog_response_cls,
    resolve_openai_catalog_provider_fn,
    get_supported_provider_names_fn,
) -> Any:
    from app.engine.llm_pool import LLMPool
    from app.engine.model_catalog import ModelCatalogService
    from app.services.llm_runtime_audit_service import (
        build_runtime_audit_summary,
        get_persisted_llm_runtime_audit,
        record_runtime_discovery_snapshot,
        run_live_capability_probes,
    )
    from app.services.llm_selectability_service import invalidate_llm_selectability_cache

    # Keep the read-only catalog endpoint fast. Expensive provider discovery
    # belongs to the explicit "Probe capability" action, not initial UI load.
    discovery_enabled = bool(run_live_probe)
    catalog = await ModelCatalogService.get_full_catalog(
        ollama_base_url=(
            settings_obj.ollama_base_url
            if discovery_enabled and settings_obj.ollama_base_url
            else None
        ),
        active_provider=settings_obj.llm_provider,
        google_api_key=settings_obj.google_api_key if discovery_enabled else None,
        openai_base_url=settings_obj.openai_base_url,
        openai_api_key=settings_obj.openai_api_key if discovery_enabled else None,
        openrouter_base_url=getattr(settings_obj, "openrouter_base_url", None),
        openrouter_api_key=(
            getattr(settings_obj, "openrouter_api_key", None)
            if discovery_enabled
            else None
        ),
        nvidia_base_url=getattr(settings_obj, "nvidia_base_url", None),
        nvidia_api_key=(
            getattr(settings_obj, "nvidia_api_key", None)
            if discovery_enabled
            else None
        ),
        zhipu_base_url=getattr(settings_obj, "zhipu_base_url", None),
        zhipu_api_key=(
            getattr(settings_obj, "zhipu_api_key", None)
            if discovery_enabled
            else None
        ),
    )

    discovery_record = record_runtime_discovery_snapshot(catalog)
    audit_record = discovery_record
    if run_live_probe:
        audit_record = await run_live_capability_probes(
            catalog,
            providers=probe_providers,
        ) or discovery_record
    if audit_record is None:
        audit_record = get_persisted_llm_runtime_audit()

    provider_status = build_provider_runtime_statuses_fn(LLMPool.get_stats())

    providers_out: dict[str, list] = {}
    openai_catalog_provider = resolve_openai_catalog_provider_fn(
        active_provider=settings_obj.llm_provider,
        openai_base_url=settings_obj.openai_base_url,
    )
    provider_names = list(get_supported_provider_names_fn())
    for provider in catalog["providers"].keys():
        if provider not in provider_names:
            provider_names.append(provider)

    for provider in provider_names:
        models = catalog["providers"].get(provider, {})
        entries = []
        for model_name, meta in models.items():
            is_default = False
            if provider == "google" and model_name == settings_obj.google_model:
                is_default = True
            elif (
                provider == "openai"
                and openai_catalog_provider == "openai"
                and model_name == settings_obj.openai_model
            ):
                is_default = True
            elif (
                provider == "openrouter"
                and model_name == resolve_openrouter_model(settings_obj)
            ):
                is_default = True
            elif provider == "nvidia" and model_name == resolve_nvidia_model(settings_obj):
                is_default = True
            elif provider == "zhipu" and model_name == getattr(settings_obj, "zhipu_model", ""):
                is_default = True
            elif provider == "ollama" and model_name == settings_obj.ollama_model:
                is_default = True
            entries.append(
                model_catalog_entry_cls(
                    provider=meta.provider,
                    model_name=meta.model_name,
                    display_name=meta.display_name,
                    status=meta.status,
                    released_on=meta.released_on,
                    is_default=is_default,
                )
            )
        status_order = {"current": 0, "available": 1, "preset": 2, "legacy": 3}
        entries.sort(key=lambda entry: (status_order.get(entry.status, 9), entry.model_name))
        providers_out[provider] = entries

    provider_capabilities = build_provider_catalog_capabilities_fn(
        provider_status,
        providers_out=providers_out,
        provider_metadata=catalog.get("provider_metadata", {}),
        runtime_audit=(audit_record.payload if audit_record else None),
    )

    embedding_entries = []
    for model_name, meta in catalog.get("embedding_models", {}).items():
        embedding_entries.append(
            model_catalog_entry_cls(
                provider=meta.provider,
                model_name=meta.model_name,
                display_name=meta.display_name,
                status=meta.status,
                released_on=meta.released_on,
                is_default=(model_name == settings_obj.embedding_model),
            )
        )

    audit_summary = build_runtime_audit_summary(audit_record)
    invalidate_llm_selectability_cache()
    return model_catalog_response_cls(
        providers=providers_out,
        embedding_models=embedding_entries,
        provider_capabilities=provider_capabilities,
        ollama_discovered=catalog.get("ollama_discovered", False),
        audit_updated_at=audit_summary.get("audit_updated_at"),
        last_live_probe_at=audit_summary.get("last_live_probe_at"),
        degraded_providers=list(audit_summary.get("degraded_providers", [])),
        audit_persisted=bool(audit_summary.get("audit_persisted", False)),
        audit_warnings=list(audit_summary.get("audit_warnings", [])),
        timestamp=catalog["timestamp"],
    )


async def update_llm_runtime_config_runtime_impl(
    request,
    body,
    auth,
    *,
    can_manage_llm_runtime_fn,
    normalize_provider_name_fn,
    normalize_chain_fn,
    normalize_string_list_fn,
    normalize_optional_choice_fn,
    serialize_llm_runtime_fn,
    build_model_catalog_response_fn,
    settings_obj,
    logger,
    get_runtime_provider_preset_fn,
    is_known_default_provider_chain_fn,
    should_apply_openrouter_defaults_fn,
    dumps_agent_runtime_profiles_fn,
    dumps_timeout_provider_overrides_fn,
    normalize_vision_provider_name_fn,
    normalize_vision_chain_fn,
    normalize_embedding_provider_name_fn,
    normalize_embedding_chain_fn,
    get_default_embedding_model_for_provider_fn,
    get_embedding_dimensions_fn,
    get_embedding_model_metadata_fn,
    resolve_openai_catalog_provider_fn,
) -> Any:
    if not can_manage_llm_runtime_fn(auth):
        raise HTTPException(
            status_code=403,
            detail="Admin or local developer access required.",
        )

    provider = normalize_provider_name_fn(body.provider) if body.provider is not None else None
    chain = normalize_chain_fn(body.llm_failover_chain)
    vision_provider = (
        normalize_vision_provider_name_fn(body.vision_provider)
        if body.vision_provider is not None
        else None
    )
    vision_describe_provider = (
        normalize_vision_provider_name_fn(body.vision_describe_provider)
        if body.vision_describe_provider is not None
        else None
    )
    vision_ocr_provider = (
        normalize_vision_provider_name_fn(body.vision_ocr_provider)
        if body.vision_ocr_provider is not None
        else None
    )
    vision_grounded_provider = (
        normalize_vision_provider_name_fn(body.vision_grounded_provider)
        if body.vision_grounded_provider is not None
        else None
    )
    vision_chain = normalize_vision_chain_fn(body.vision_failover_chain)
    embedding_provider = (
        normalize_embedding_provider_name_fn(body.embedding_provider)
        if body.embedding_provider is not None
        else None
    )
    embedding_chain = normalize_embedding_chain_fn(body.embedding_failover_chain)
    openrouter_model_fallbacks = normalize_string_list_fn(body.openrouter_model_fallbacks)
    openrouter_provider_order = normalize_string_list_fn(body.openrouter_provider_order)
    openrouter_allowed_providers = normalize_string_list_fn(body.openrouter_allowed_providers)
    openrouter_ignored_providers = normalize_string_list_fn(body.openrouter_ignored_providers)
    openrouter_data_collection = normalize_optional_choice_fn(
        body.openrouter_data_collection,
        allowed={"allow", "deny"},
        field_name="openrouter_data_collection",
    )
    openrouter_provider_sort = normalize_optional_choice_fn(
        body.openrouter_provider_sort,
        allowed={"price", "latency", "throughput"},
        field_name="openrouter_provider_sort",
    )
    embedding_model = body.embedding_model.strip() if body.embedding_model is not None else None
    embedding_model_metadata = (
        get_embedding_model_metadata_fn(embedding_model) if embedding_model is not None else None
    )
    if embedding_model is not None and not embedding_model_metadata:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported embedding_model: {body.embedding_model}",
        )

    target_embedding_provider = (
        embedding_provider
        if embedding_provider is not None
        else (getattr(settings_obj, "embedding_provider", None) or "auto")
    )
    target_embedding_provider = (target_embedding_provider or "auto").strip().lower()
    if (
        embedding_model_metadata is not None
        and target_embedding_provider != "auto"
        and not (
            target_embedding_provider in {"openai", "openrouter"}
            and embedding_model_metadata.provider in {"openai", "openrouter"}
        )
        and embedding_model_metadata.provider != target_embedding_provider
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Embedding model {embedding_model_metadata.model_name} belongs to "
                f"{embedding_model_metadata.provider}, not {target_embedding_provider}"
            ),
        )

    from app.services.llm_runtime_policy_service import (
        apply_llm_runtime_policy_snapshot,
        get_persisted_llm_runtime_policy,
        persist_current_llm_runtime_policy,
        redact_llm_runtime_policy_snapshot,
        snapshot_current_llm_runtime_policy,
    )

    previous_snapshot = snapshot_current_llm_runtime_policy()

    if provider is not None:
        settings_obj.llm_provider = provider
        preset = get_runtime_provider_preset_fn(provider)
        if provider == "google":
            if body.google_model is None and not settings_obj.google_model:
                settings_obj.google_model = preset.google_model or settings_obj.google_model
        if provider == "openai":
            if body.openai_base_url is None and settings_obj.openai_base_url:
                settings_obj.openai_base_url = settings_obj.openai_base_url.strip() or None
            if body.openai_model is None and not settings_obj.openai_model:
                settings_obj.openai_model = preset.openai_model or settings_obj.openai_model
            if body.openai_model_advanced is None and not settings_obj.openai_model_advanced:
                settings_obj.openai_model_advanced = (
                    preset.openai_model_advanced or settings_obj.openai_model_advanced
                )
        if provider == "openrouter":
            if body.openrouter_base_url is None and not getattr(settings_obj, "openrouter_base_url", None):
                settings_obj.openrouter_base_url = preset.openrouter_base_url
            if body.openrouter_model is None and should_apply_openrouter_defaults_fn(getattr(settings_obj, "openrouter_model", None)):
                settings_obj.openrouter_model = preset.openrouter_model or settings_obj.openrouter_model
            if body.openrouter_model_advanced is None and should_apply_openrouter_defaults_fn(getattr(settings_obj, "openrouter_model_advanced", None)):
                settings_obj.openrouter_model_advanced = (
                    preset.openrouter_model_advanced or settings_obj.openrouter_model_advanced
                )
        if provider == "nvidia":
            if not body.nvidia_base_url and not getattr(settings_obj, "nvidia_base_url", None):
                settings_obj.nvidia_base_url = preset.nvidia_base_url
            if body.nvidia_model is None and not getattr(settings_obj, "nvidia_model", None):
                settings_obj.nvidia_model = preset.nvidia_model or settings_obj.nvidia_model
            if body.nvidia_model_advanced is None and not getattr(settings_obj, "nvidia_model_advanced", None):
                settings_obj.nvidia_model_advanced = (
                    preset.nvidia_model_advanced or settings_obj.nvidia_model_advanced
                )
        if provider == "zhipu":
            if not body.zhipu_base_url and not getattr(settings_obj, "zhipu_base_url", None):
                settings_obj.zhipu_base_url = preset.zhipu_base_url
            if body.zhipu_model is None and not getattr(settings_obj, "zhipu_model", None):
                settings_obj.zhipu_model = preset.zhipu_model or settings_obj.zhipu_model
            if body.zhipu_model_advanced is None and not getattr(settings_obj, "zhipu_model_advanced", None):
                settings_obj.zhipu_model_advanced = (
                    preset.zhipu_model_advanced or settings_obj.zhipu_model_advanced
                )
        if provider == "ollama":
            if not body.ollama_base_url and not settings_obj.ollama_base_url:
                settings_obj.ollama_base_url = preset.ollama_base_url
            if body.ollama_model is None and not settings_obj.ollama_model:
                settings_obj.ollama_model = preset.ollama_model or settings_obj.ollama_model
            if body.ollama_keep_alive is None and not getattr(settings_obj, "ollama_keep_alive", None):
                settings_obj.ollama_keep_alive = preset.ollama_keep_alive
        if chain is None and is_known_default_provider_chain_fn(getattr(settings_obj, "llm_failover_chain", None)):
            settings_obj.llm_failover_chain = list(preset.failover_chain)

    if embedding_provider is not None:
        settings_obj.embedding_provider = embedding_provider
        if body.embedding_model is None:
            current_embedding_model = getattr(settings_obj, "embedding_model", None)
            current_embedding_metadata = get_embedding_model_metadata_fn(current_embedding_model)
            target_provider = None if embedding_provider == "auto" else embedding_provider
            if target_provider is None:
                if not current_embedding_model:
                    default_embedding_model = get_default_embedding_model_for_provider_fn("google")
                    if default_embedding_model:
                        settings_obj.embedding_model = default_embedding_model
            elif current_embedding_metadata is None or not (
                current_embedding_metadata.provider == target_provider
                or (
                    target_provider in {"openai", "openrouter"}
                    and current_embedding_metadata.provider in {"openai", "openrouter"}
                )
            ):
                default_embedding_model = get_default_embedding_model_for_provider_fn(target_provider)
                if default_embedding_model:
                    settings_obj.embedding_model = default_embedding_model

    if vision_provider is not None:
        settings_obj.vision_provider = vision_provider
    if vision_describe_provider is not None:
        settings_obj.vision_describe_provider = vision_describe_provider
    if vision_ocr_provider is not None:
        settings_obj.vision_ocr_provider = vision_ocr_provider
    if vision_grounded_provider is not None:
        settings_obj.vision_grounded_provider = vision_grounded_provider

    if body.use_multi_agent is not None:
        settings_obj.use_multi_agent = body.use_multi_agent
    if body.google_api_key is not None:
        settings_obj.google_api_key = body.google_api_key.strip() or None
    elif body.clear_google_api_key:
        settings_obj.google_api_key = None
    if body.google_model is not None:
        settings_obj.google_model = body.google_model.strip()
    if body.openai_api_key is not None:
        settings_obj.openai_api_key = body.openai_api_key.strip() or None
    elif body.clear_openai_api_key:
        settings_obj.openai_api_key = None
    if body.openrouter_api_key is not None:
        settings_obj.openrouter_api_key = body.openrouter_api_key.strip() or None
    elif body.clear_openrouter_api_key:
        settings_obj.openrouter_api_key = None
    if body.nvidia_api_key is not None:
        settings_obj.nvidia_api_key = body.nvidia_api_key.strip() or None
    elif body.clear_nvidia_api_key:
        settings_obj.nvidia_api_key = None
    if body.zhipu_api_key is not None:
        settings_obj.zhipu_api_key = body.zhipu_api_key.strip() or None
    elif body.clear_zhipu_api_key:
        settings_obj.zhipu_api_key = None
    if body.ollama_api_key is not None:
        settings_obj.ollama_api_key = body.ollama_api_key.strip() or None
    elif body.clear_ollama_api_key:
        settings_obj.ollama_api_key = None
    if body.openai_base_url is not None:
        settings_obj.openai_base_url = body.openai_base_url.strip() or None
    if body.openai_model is not None:
        settings_obj.openai_model = body.openai_model.strip()
    if body.openai_model_advanced is not None:
        settings_obj.openai_model_advanced = body.openai_model_advanced.strip()
    if body.openrouter_base_url is not None:
        settings_obj.openrouter_base_url = body.openrouter_base_url.strip() or None
    if body.openrouter_model is not None:
        settings_obj.openrouter_model = body.openrouter_model.strip()
    if body.openrouter_model_advanced is not None:
        settings_obj.openrouter_model_advanced = body.openrouter_model_advanced.strip()
    if body.nvidia_base_url is not None:
        settings_obj.nvidia_base_url = body.nvidia_base_url.strip() or None
    if body.nvidia_model is not None:
        settings_obj.nvidia_model = body.nvidia_model.strip()
    if body.nvidia_model_advanced is not None:
        settings_obj.nvidia_model_advanced = body.nvidia_model_advanced.strip()
    if body.zhipu_base_url is not None:
        settings_obj.zhipu_base_url = body.zhipu_base_url.strip() or None
    if body.zhipu_model is not None:
        settings_obj.zhipu_model = body.zhipu_model.strip()
    if body.zhipu_model_advanced is not None:
        settings_obj.zhipu_model_advanced = body.zhipu_model_advanced.strip()
    if openrouter_model_fallbacks is not None:
        settings_obj.openrouter_model_fallbacks = openrouter_model_fallbacks
    if openrouter_provider_order is not None:
        settings_obj.openrouter_provider_order = openrouter_provider_order
    if openrouter_allowed_providers is not None:
        settings_obj.openrouter_allowed_providers = openrouter_allowed_providers
    if openrouter_ignored_providers is not None:
        settings_obj.openrouter_ignored_providers = openrouter_ignored_providers
    if "openrouter_allow_fallbacks" in body.model_fields_set:
        settings_obj.openrouter_allow_fallbacks = body.openrouter_allow_fallbacks
    if "openrouter_require_parameters" in body.model_fields_set:
        settings_obj.openrouter_require_parameters = body.openrouter_require_parameters
    if "openrouter_data_collection" in body.model_fields_set:
        settings_obj.openrouter_data_collection = openrouter_data_collection
    if "openrouter_zdr" in body.model_fields_set:
        settings_obj.openrouter_zdr = body.openrouter_zdr
    if "openrouter_provider_sort" in body.model_fields_set:
        settings_obj.openrouter_provider_sort = openrouter_provider_sort
    if body.ollama_base_url is not None:
        settings_obj.ollama_base_url = body.ollama_base_url.strip() or None
    if body.ollama_model is not None:
        settings_obj.ollama_model = body.ollama_model.strip()
    if body.ollama_keep_alive is not None:
        settings_obj.ollama_keep_alive = body.ollama_keep_alive.strip() or None
    if body.vision_describe_model is not None:
        settings_obj.vision_describe_model = body.vision_describe_model.strip()
    if body.vision_ocr_model is not None:
        settings_obj.vision_ocr_model = body.vision_ocr_model.strip()
    if body.vision_grounded_model is not None:
        settings_obj.vision_grounded_model = body.vision_grounded_model.strip()
    if "vision_timeout_seconds" in body.model_fields_set and body.vision_timeout_seconds is not None:
        settings_obj.vision_timeout_seconds = float(body.vision_timeout_seconds)
    if vision_chain is not None:
        settings_obj.vision_failover_chain = vision_chain
    from app.engine.model_catalog import embedding_model_supports_dimension_override

    if embedding_model is not None:
        settings_obj.embedding_model = embedding_model
    if body.embedding_dimensions is not None:
        settings_obj.embedding_dimensions = int(body.embedding_dimensions)
    else:
        effective_embedding_model = getattr(settings_obj, "embedding_model", None)
        if effective_embedding_model:
            if not embedding_model_supports_dimension_override(effective_embedding_model):
                settings_obj.embedding_dimensions = get_embedding_dimensions_fn(
                    effective_embedding_model
                )
            elif not getattr(settings_obj, "embedding_dimensions", None):
                settings_obj.embedding_dimensions = get_embedding_dimensions_fn(
                    effective_embedding_model
                )
    if embedding_chain is not None:
        settings_obj.embedding_failover_chain = embedding_chain
    if body.enable_llm_failover is not None:
        settings_obj.enable_llm_failover = body.enable_llm_failover
    if chain is not None:
        settings_obj.llm_failover_chain = chain
    if body.agent_profiles is not None:
        settings_obj.agent_runtime_profiles = dumps_agent_runtime_profiles_fn(
            {name: profile.model_dump() for name, profile in body.agent_profiles.items()}
        )
    if body.timeout_profiles is not None:
        timeout_profiles = body.timeout_profiles.model_dump()
        settings_obj.llm_primary_timeout_light_seconds = timeout_profiles["light_seconds"]
        settings_obj.llm_primary_timeout_moderate_seconds = timeout_profiles["moderate_seconds"]
        settings_obj.llm_primary_timeout_deep_seconds = timeout_profiles["deep_seconds"]
        settings_obj.llm_primary_timeout_structured_seconds = timeout_profiles["structured_seconds"]
        settings_obj.llm_primary_timeout_background_seconds = timeout_profiles["background_seconds"]
        settings_obj.llm_stream_keepalive_interval_seconds = timeout_profiles["stream_keepalive_interval_seconds"]
        settings_obj.llm_stream_idle_timeout_seconds = timeout_profiles["stream_idle_timeout_seconds"]
    if "timeout_provider_overrides" in body.model_fields_set:
        settings_obj.llm_timeout_provider_overrides = dumps_timeout_provider_overrides_fn(
            {
                name: override.model_dump(exclude_none=True)
                for name, override in (body.timeout_provider_overrides or {}).items()
            }
        )
    settings_obj.refresh_nested_views()

    from app.services.embedding_space_guard import (
        build_runtime_embedding_space_warnings,
        validate_embedding_space_transition,
    )

    embedding_transition = validate_embedding_space_transition(
        current_model=previous_snapshot.get("embedding_model"),
        current_dimensions=previous_snapshot.get("embedding_dimensions"),
        target_model=getattr(settings_obj, "embedding_model", None),
        target_dimensions=getattr(settings_obj, "embedding_dimensions", None),
    )
    if not embedding_transition.allowed:
        apply_llm_runtime_policy_snapshot(previous_snapshot)
        raise HTTPException(
            status_code=409,
            detail=embedding_transition.detail or "Unsafe embedding-space transition rejected.",
        )

    persisted_record = persist_current_llm_runtime_policy()
    if persisted_record is None:
        apply_llm_runtime_policy_snapshot(previous_snapshot)
        logger.error("Failed to persist LLM runtime policy; rolled back in-memory update")
        raise HTTPException(
            status_code=503,
            detail="Failed to persist runtime policy. No changes were applied.",
        )

    from app.engine.llm_pool import LLMPool
    from app.engine.embedding_runtime import reset_embedding_backend
    from app.engine.vision_runtime import reset_vision_runtime_caches
    from app.engine.multi_agent.agent_config import AgentConfigRegistry
    from app.services.chat_service import reset_chat_service
    from app.services.embedding_selectability_service import (
        invalidate_embedding_selectability_cache,
    )
    from app.services.llm_selectability_service import invalidate_llm_selectability_cache
    from app.services.vision_selectability_service import (
        invalidate_vision_selectability_cache,
    )

    LLMPool.reset()
    reset_embedding_backend()
    reset_vision_runtime_caches()
    try:
        AgentConfigRegistry.initialize(
            getattr(settings_obj, "agent_provider_configs", "{}"),
            getattr(settings_obj, "agent_runtime_profiles", "{}"),
        )
    except Exception as exc:
        logger.warning("[ADMIN] Agent config re-initialize failed after policy save: %s", exc)
    reset_chat_service()
    invalidate_llm_selectability_cache()
    invalidate_embedding_selectability_cache()
    invalidate_vision_selectability_cache()
    try:
        from app.cache.invalidation import get_invalidation_manager

        if embedding_transition.target_contract is not None:
            await get_invalidation_manager().on_embeddings_refreshed(
                embedding_transition.target_contract.fingerprint,
                None,
            )
    except Exception as exc:
        logger.warning("[ADMIN] Embedding cache version refresh failed: %s", exc)
    logger.info(
        "[ADMIN] Updated LLM runtime config: provider=%s multi_agent=%s failover=%s chain=%s vision_provider=%s vision_describe=%s/%s vision_ocr=%s/%s vision_grounded=%s/%s vision_chain=%s embedding_provider=%s embedding_model=%s openai_base=%s openrouter_base=%s",
        settings_obj.llm_provider,
        getattr(settings_obj, "use_multi_agent", True),
        settings_obj.enable_llm_failover,
        settings_obj.llm_failover_chain,
        getattr(settings_obj, "vision_provider", "auto"),
        getattr(settings_obj, "vision_describe_provider", "auto"),
        getattr(settings_obj, "vision_describe_model", None),
        getattr(settings_obj, "vision_ocr_provider", "auto"),
        getattr(settings_obj, "vision_ocr_model", None),
        getattr(settings_obj, "vision_grounded_provider", "auto"),
        getattr(settings_obj, "vision_grounded_model", None),
        getattr(settings_obj, "vision_failover_chain", []),
        getattr(settings_obj, "embedding_provider", "auto"),
        getattr(settings_obj, "embedding_model", None),
        settings_obj.openai_base_url,
        getattr(settings_obj, "openrouter_base_url", None),
    )

    try:
        from app.services.admin_audit import extract_audit_context, log_admin_action

        ctx = extract_audit_context(request)
        await log_admin_action(
            actor_id=auth.user_id,
            action="llm_runtime.update",
            target_type="llm_runtime_policy",
            target_id="system",
            old_value=redact_llm_runtime_policy_snapshot(previous_snapshot),
            new_value=redact_llm_runtime_policy_snapshot(
                snapshot_current_llm_runtime_policy()
            ),
            **ctx,
        )
    except Exception as exc:
        logger.warning("Failed to write LLM runtime audit event: %s", exc)

    warnings = list(embedding_transition.warnings)
    from app.engine.model_catalog import is_known_model, is_legacy_google_model

    if body.google_model is not None:
        gm = body.google_model.strip()
        if is_legacy_google_model(gm):
            warnings.append(f"google_model '{gm}' is legacy. Consider a current model.")
        elif not is_known_model("google", gm):
            warnings.append(f"google_model '{gm}' is not in the known catalog.")
    if body.zhipu_model is not None:
        zm = body.zhipu_model.strip()
        if not is_known_model("zhipu", zm):
            warnings.append(f"zhipu_model '{zm}' is not in the known catalog.")
    if body.ollama_model is not None:
        om = body.ollama_model.strip()
        if not is_known_model("ollama", om):
            warnings.append(f"ollama_model '{om}' is not in the known catalog.")
    if body.openai_model is not None:
        oam = body.openai_model.strip()
        openai_catalog_provider = resolve_openai_catalog_provider_fn(
            active_provider=settings_obj.llm_provider,
            openai_base_url=settings_obj.openai_base_url,
        )
        if not is_known_model(openai_catalog_provider, oam):
            warnings.append(
                f"openai_model '{oam}' is not in the known {openai_catalog_provider} catalog."
            )
    if body.openrouter_model is not None:
        orm = body.openrouter_model.strip()
        if not is_known_model("openrouter", orm):
            warnings.append(
                f"openrouter_model '{orm}' is not in the known openrouter catalog."
            )
    if body.nvidia_model is not None:
        nm = body.nvidia_model.strip()
        if not is_known_model("nvidia", nm):
            warnings.append(
                f"nvidia_model '{nm}' is not in the known nvidia catalog."
            )
    warnings.extend(
        build_runtime_embedding_space_warnings(
            current_model=getattr(settings_obj, "embedding_model", None),
            current_dimensions=getattr(settings_obj, "embedding_dimensions", None),
        )
    )

    try:
        await build_model_catalog_response_fn(
            run_live_probe=True,
            probe_providers=LLMPool.get_request_selectable_providers(),
        )
        invalidate_llm_selectability_cache()
    except Exception as exc:
        warnings.append("Runtime audit refresh failed after saving policy.")
        logger.warning("[ADMIN] Runtime audit refresh after policy save failed: %s", exc)

    latest_persisted = persisted_record or get_persisted_llm_runtime_policy()
    return serialize_llm_runtime_fn(
        warnings=warnings,
        runtime_policy_persisted=bool(latest_persisted and latest_persisted.payload),
        runtime_policy_updated_at=(
            latest_persisted.updated_at.isoformat()
            if latest_persisted and latest_persisted.updated_at
            else None
        ),
    )
