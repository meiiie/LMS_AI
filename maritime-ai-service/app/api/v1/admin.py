"""
Admin API Router - Wiii platform administration surfaces.

These endpoints are controlled by canonical Wiii platform admin access.
Host-local LMS roles remain overlays and do not define global admin authority.
"""

import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Optional
from uuid import uuid4
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)

from app.api.v1.admin_llm_runtime import (
    build_model_catalog_response_impl,
    build_provider_catalog_capabilities_impl,
    build_provider_runtime_statuses_impl,
    serialize_llm_runtime_impl,
    update_llm_runtime_config_impl,
)
from app.api.v1.admin_ingestion_support import (
    cleanup_old_jobs_impl,
    run_ingestion_background_impl,
)
from app.api.v1.admin_domain_support import (
    get_domain_detail_impl,
    list_domain_skills_impl,
    list_domains_impl,
)
from app.api.v1.admin_schemas import (
    AgentRuntimeProfileConfig,
    DomainDetail,
    DomainSummary,
    DocumentInfo,
    DocumentStatus,
    DocumentUploadResponse,
    EmbeddingMigrationPreview,
    EmbeddingProviderRuntimeStatus,
    EmbeddingSpaceMigrationPlanRequest,
    EmbeddingSpaceMigrationPlanResponse,
    EmbeddingSpaceMigrationPromoteRequest,
    EmbeddingSpaceMigrationRunRequest,
    EmbeddingSpaceMigrationRunResponse,
    EmbeddingSpaceStatusSummary,
    LlmRuntimeAuditRefreshRequest,
    LlmRuntimeConfigResponse,
    LlmRuntimeConfigUpdate,
    LlmTimeoutProfilesConfig,
    LlmTimeoutProviderOverride,
    ModelCatalogEntry,
    ModelCatalogResponse,
    ProviderCatalogCapability,
    ProviderRuntimeStatus,
    SkillDetail,
    VisionProviderRuntimeStatus,
)
from app.api.deps import RequireAuth, RequireAdmin
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import is_platform_admin
from app.engine.multi_agent.runtime_flow_doctor import (
    build_runtime_flow_doctor_history_from_session_log,
    build_recent_runtime_flow_doctor_report_from_session_log,
    build_runtime_flow_doctor_report_from_session_log,
)
from app.engine.runtime.session_event_log import get_session_event_log
from app.engine.semantic_memory.write_doctor import (
    build_recent_semantic_memory_write_doctor_report_from_session_log,
    build_semantic_memory_write_doctor_history_from_session_log,
)
from app.services.embedding_selectability_service import get_embedding_selectability_snapshot
from app.services.embedding_space_runtime_service import (
    build_embedding_migration_previews,
    build_embedding_space_status_snapshot,
)
from app.services.embedding_space_migration_service import (
    migrate_embedding_space_rows,
    plan_embedding_space_migration,
    promote_embedding_space_shadow,
)
from app.services.llm_selectability_service import get_llm_selectability_snapshot
from app.services.vision_runtime_audit_service import (
    build_vision_runtime_audit_summary,
    build_vision_runtime_provider_statuses,
    run_live_vision_capability_probes,
)
from app.services.vision_selectability_service import get_vision_selectability_snapshot
from app.api.v1.admin_runtime_bindings import (
    DEFAULT_EMBEDDING_MODEL,
    GOOGLE_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL_ADVANCED,
    build_timeout_profiles_snapshot,
    create_provider,
    dumps_agent_runtime_profiles,
    dumps_timeout_provider_overrides,
    get_chat_model_metadata,
    get_default_embedding_model_for_provider,
    get_domain_registry,
    get_embedding_dimensions,
    get_embedding_model_metadata,
    get_ingestion_service,
    get_persisted_llm_runtime_policy,
    get_runtime_provider_preset,
    get_shared_session_factory,
    get_supported_provider_names,
    get_user_graph_repository,
    is_known_default_provider_chain,
    is_supported_provider,
    loads_timeout_provider_overrides,
    resolve_openai_catalog_provider,
    sanitize_agent_runtime_profiles,
    should_apply_openrouter_defaults,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


def _resolve_admin_document_org(auth: RequireAdmin) -> Optional[str]:
    """Resolve the admin's active org for direct knowledge document SQL."""
    if not settings.enable_multi_tenant:
        return None
    org_id = getattr(auth, "organization_id", None)
    if isinstance(org_id, str) and org_id.strip():
        return org_id.strip()
    raise HTTPException(
        status_code=403,
        detail="Active organization is required for document administration.",
    )


def _hash_admin_identifier(value) -> str | None:
    try:
        from app.engine.semantic_memory.privacy import hash_memory_identifier

        return hash_memory_identifier(value)
    except Exception as exc:
        logger.debug("Admin identifier hashing unavailable: %s", exc)
        return None


def _can_manage_llm_runtime(auth) -> bool:
    if is_platform_admin(auth):
        return True
    return (
        settings.environment != "production"
        and auth.auth_method == "api_key"
    )


def _normalize_provider_name(provider: Optional[str]) -> Optional[str]:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if not is_supported_provider(normalized):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider: {provider}",
        )
    return normalized


def _normalize_chain(chain: Optional[list[str]]) -> Optional[list[str]]:
    if chain is None:
        return None
    normalized: list[str] = []
    for item in chain:
        provider = _normalize_provider_name(item)
        if provider and provider not in normalized:
            normalized.append(provider)
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="llm_failover_chain cannot be empty",
        )
    return normalized


def _normalize_embedding_provider_name(provider: Optional[str]) -> Optional[str]:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if normalized == "auto":
        return normalized
    return _normalize_provider_name(normalized)


def _normalize_embedding_chain(chain: Optional[list[str]]) -> Optional[list[str]]:
    if chain is None:
        return None
    normalized: list[str] = []
    for item in chain:
        provider = _normalize_embedding_provider_name(item)
        if provider == "auto":
            raise HTTPException(
                status_code=422,
                detail="embedding_failover_chain cannot contain 'auto'",
            )
        if provider and provider not in normalized:
            normalized.append(provider)
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="embedding_failover_chain cannot be empty",
        )
    return normalized


def _normalize_vision_provider_name(provider: Optional[str]) -> Optional[str]:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if normalized == "auto":
        return normalized
    return _normalize_provider_name(normalized)


def _normalize_vision_chain(chain: Optional[list[str]]) -> Optional[list[str]]:
    if chain is None:
        return None
    normalized: list[str] = []
    for item in chain:
        provider = _normalize_vision_provider_name(item)
        if provider == "auto":
            raise HTTPException(
                status_code=422,
                detail="vision_failover_chain cannot contain 'auto'",
            )
        if provider and provider not in normalized:
            normalized.append(provider)
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="vision_failover_chain cannot be empty",
        )
    return normalized


def _normalize_string_list(values: Optional[list[str]]) -> Optional[list[str]]:
    if values is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = item.strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _normalize_optional_choice(
    value: Optional[str],
    *,
    allowed: set[str],
    field_name: str,
) -> Optional[str]:
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be one of {sorted(allowed)}",
        )
    return normalized


_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "google": "Google Gemini",
    "openai": "OpenAI-Compatible",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA NIM",
    "ollama": "Ollama",
    "zhipu": "Zhipu GLM",
}
_ADMIN_CONFIGURABLE_PROVIDERS = frozenset(
    {"google", "openai", "openrouter", "nvidia", "ollama", "zhipu"}
)


def _get_provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider.replace("_", " ").title())


def _build_provider_runtime_statuses(stats: dict) -> list[ProviderRuntimeStatus]:
    return build_provider_runtime_statuses_impl(
        stats,
        settings_obj=settings,
        get_supported_provider_names_fn=get_supported_provider_names,
        create_provider_fn=create_provider,
        get_provider_display_name_fn=_get_provider_display_name,
        get_llm_selectability_snapshot_fn=get_llm_selectability_snapshot,
        provider_runtime_status_cls=ProviderRuntimeStatus,
        configurable_providers=_ADMIN_CONFIGURABLE_PROVIDERS,
        logger=logger,
    )


def _build_provider_catalog_capabilities(
    provider_status: list[ProviderRuntimeStatus],
    *,
    providers_out: dict[str, list[ModelCatalogEntry]],
    provider_metadata: dict[str, dict],
    runtime_audit: Mapping[str, Any] | None = None,
) -> dict[str, ProviderCatalogCapability]:
    return build_provider_catalog_capabilities_impl(
        provider_status,
        providers_out=providers_out,
        provider_metadata=provider_metadata,
        runtime_audit=runtime_audit,
        settings_obj=settings,
        get_runtime_provider_preset_fn=get_runtime_provider_preset,
        provider_catalog_capability_cls=ProviderCatalogCapability,
        google_default_model=GOOGLE_DEFAULT_MODEL,
        openai_default_model=OPENAI_DEFAULT_MODEL,
        openai_default_model_advanced=OPENAI_DEFAULT_MODEL_ADVANCED,
    )


def _build_embedding_provider_runtime_statuses(
    *,
    allow_local_probe: bool = False,
) -> list[EmbeddingProviderRuntimeStatus]:
    return [
        EmbeddingProviderRuntimeStatus(**item.to_dict())
        for item in get_embedding_selectability_snapshot(allow_local_probe=allow_local_probe)
    ]


def _build_vision_provider_runtime_statuses(
    *,
    allow_local_probe: bool = False,
) -> list[VisionProviderRuntimeStatus]:
    return [
        VisionProviderRuntimeStatus(**item)
        for item in build_vision_runtime_provider_statuses(
            get_vision_selectability_snapshot(allow_local_probe=allow_local_probe)
        )
    ]


def _build_embedding_space_status() -> EmbeddingSpaceStatusSummary:
    return EmbeddingSpaceStatusSummary(**build_embedding_space_status_snapshot().to_dict())


def _build_embedding_migration_previews() -> list[EmbeddingMigrationPreview]:
    return [
        EmbeddingMigrationPreview(**item.to_dict())
        for item in build_embedding_migration_previews()
    ]


def _embedding_migration_http_exception(exc: RuntimeError) -> HTTPException:
    detail = str(exc) or "Embedding migration failed."
    normalized = detail.lower()
    status_code = 422 if "khong hop le" in normalized else 409
    return HTTPException(status_code=status_code, detail=detail)


def _serialize_llm_runtime(
    warnings: list[str] | None = None,
    *,
    runtime_policy_persisted: bool = False,
    runtime_policy_updated_at: Optional[str] = None,
    allow_local_probe: bool = False,
) -> LlmRuntimeConfigResponse:
    if warnings is None:
        warnings = []
    try:
        from app.services.embedding_space_guard import build_runtime_embedding_space_warnings

        warnings = list(warnings) + build_runtime_embedding_space_warnings(
            current_model=getattr(settings, "embedding_model", None),
            current_dimensions=getattr(settings, "embedding_dimensions", None),
        )
    except Exception as exc:
        logger.debug("Embedding space warnings unavailable during admin serialization: %s", exc)
    return serialize_llm_runtime_impl(
        warnings=warnings,
        runtime_policy_persisted=runtime_policy_persisted,
        runtime_policy_updated_at=runtime_policy_updated_at,
        settings_obj=settings,
        build_provider_runtime_statuses_fn=_build_provider_runtime_statuses,
        logger=logger,
        google_default_model=GOOGLE_DEFAULT_MODEL,
        get_chat_model_metadata_fn=get_chat_model_metadata,
        get_embedding_model_metadata_fn=get_embedding_model_metadata,
        default_embedding_model=DEFAULT_EMBEDDING_MODEL,
        sanitize_agent_runtime_profiles_fn=sanitize_agent_runtime_profiles,
        agent_runtime_profile_config_cls=AgentRuntimeProfileConfig,
        build_timeout_profiles_snapshot_fn=build_timeout_profiles_snapshot,
        llm_timeout_profiles_config_cls=LlmTimeoutProfilesConfig,
        loads_timeout_provider_overrides_fn=loads_timeout_provider_overrides,
        llm_timeout_provider_override_cls=LlmTimeoutProviderOverride,
        llm_runtime_config_response_cls=LlmRuntimeConfigResponse,
        get_embedding_dimensions_fn=get_embedding_dimensions,
        build_vision_provider_runtime_statuses_fn=lambda: _build_vision_provider_runtime_statuses(
            allow_local_probe=allow_local_probe
        ),
        build_vision_runtime_audit_summary_fn=build_vision_runtime_audit_summary,
        build_embedding_provider_runtime_statuses_fn=lambda: _build_embedding_provider_runtime_statuses(
            allow_local_probe=allow_local_probe
        ),
        build_embedding_space_status_fn=_build_embedding_space_status,
        build_embedding_migration_previews_fn=_build_embedding_migration_previews,
    )


async def _build_model_catalog_response(
    *,
    run_live_probe: bool = False,
    probe_providers: Optional[list[str]] = None,
) -> ModelCatalogResponse:
    return await build_model_catalog_response_impl(
        run_live_probe=run_live_probe,
        probe_providers=probe_providers,
        settings_obj=settings,
        build_provider_runtime_statuses_fn=_build_provider_runtime_statuses,
        build_provider_catalog_capabilities_fn=_build_provider_catalog_capabilities,
        model_catalog_entry_cls=ModelCatalogEntry,
        model_catalog_response_cls=ModelCatalogResponse,
        resolve_openai_catalog_provider_fn=resolve_openai_catalog_provider,
        get_supported_provider_names_fn=get_supported_provider_names,
    )


# =============================================================================
# In-memory job tracking (replace with DB in production)
# =============================================================================

_ingestion_jobs: dict = {}  # job_id -> DocumentStatus
_MAX_TRACKED_JOBS = 100  # Prevent unbounded memory growth


def _cleanup_old_jobs():
    """Remove oldest completed/failed jobs when limit exceeded."""
    cleanup_old_jobs_impl(
        ingestion_jobs=_ingestion_jobs,
        max_tracked_jobs=_MAX_TRACKED_JOBS,
    )


@router.get("/llm-runtime", response_model=LlmRuntimeConfigResponse)
async def get_llm_runtime_config(auth: RequireAuth):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(
            status_code=403,
            detail="Admin or local developer access required.",
        )

    persisted = get_persisted_llm_runtime_policy()
    return _serialize_llm_runtime(
        runtime_policy_persisted=bool(persisted and persisted.payload),
        runtime_policy_updated_at=(
            persisted.updated_at.isoformat()
            if persisted and persisted.updated_at
            else None
        ),
    )


@router.get("/model-catalog", response_model=ModelCatalogResponse)
async def get_model_catalog(auth: RequireAuth):
    """Return available models from all providers (static + Ollama discovery)."""
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin or local developer access required.")
    return await _build_model_catalog_response()


@router.post("/llm-runtime/audit", response_model=ModelCatalogResponse)
async def refresh_llm_runtime_audit(
    body: LlmRuntimeAuditRefreshRequest,
    auth: RequireAuth,
):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin or local developer access required.")

    providers = None
    if body.providers is not None:
        providers = []
        for provider in body.providers:
            normalized = _normalize_provider_name(provider)
            if normalized and normalized not in providers:
                providers.append(normalized)

    return await _build_model_catalog_response(
        run_live_probe=True,
        probe_providers=providers,
    )


@router.post("/llm-runtime/vision-audit", response_model=LlmRuntimeConfigResponse)
async def refresh_vision_runtime_audit(
    body: LlmRuntimeAuditRefreshRequest,
    auth: RequireAuth,
):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin or local developer access required.")

    providers = None
    if body.providers is not None:
        providers = []
        for provider in body.providers:
            normalized = _normalize_provider_name(provider)
            if normalized and normalized not in providers:
                providers.append(normalized)

    await run_live_vision_capability_probes(providers=providers)
    persisted = get_persisted_llm_runtime_policy()
    return _serialize_llm_runtime(
        runtime_policy_persisted=bool(persisted and persisted.payload),
        runtime_policy_updated_at=(
            persisted.updated_at.isoformat()
            if persisted and persisted.updated_at
            else None
        ),
        allow_local_probe=True,
    )


@router.patch("/llm-runtime", response_model=LlmRuntimeConfigResponse)
async def update_llm_runtime_config(
    request: Request,
    body: LlmRuntimeConfigUpdate,
    auth: RequireAuth,
):
    return await update_llm_runtime_config_impl(
        request,
        body,
        auth,
        can_manage_llm_runtime_fn=_can_manage_llm_runtime,
        normalize_provider_name_fn=_normalize_provider_name,
        normalize_chain_fn=_normalize_chain,
        normalize_string_list_fn=_normalize_string_list,
        normalize_optional_choice_fn=_normalize_optional_choice,
        serialize_llm_runtime_fn=_serialize_llm_runtime,
        build_model_catalog_response_fn=_build_model_catalog_response,
        settings_obj=settings,
        logger=logger,
        get_runtime_provider_preset_fn=get_runtime_provider_preset,
        is_known_default_provider_chain_fn=is_known_default_provider_chain,
        should_apply_openrouter_defaults_fn=should_apply_openrouter_defaults,
        dumps_agent_runtime_profiles_fn=dumps_agent_runtime_profiles,
        dumps_timeout_provider_overrides_fn=dumps_timeout_provider_overrides,
        normalize_vision_provider_name_fn=_normalize_vision_provider_name,
        normalize_vision_chain_fn=_normalize_vision_chain,
        normalize_embedding_provider_name_fn=_normalize_embedding_provider_name,
        normalize_embedding_chain_fn=_normalize_embedding_chain,
        get_default_embedding_model_for_provider_fn=get_default_embedding_model_for_provider,
        get_embedding_dimensions_fn=get_embedding_dimensions,
        get_embedding_model_metadata_fn=get_embedding_model_metadata,
        resolve_openai_catalog_provider_fn=resolve_openai_catalog_provider,
    )


@router.post(
    "/llm-runtime/embedding-space/plan",
    response_model=EmbeddingSpaceMigrationPlanResponse,
)
async def plan_embedding_space_migration_route(
    body: EmbeddingSpaceMigrationPlanRequest,
    auth: RequireAuth,
):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    try:
        plan = plan_embedding_space_migration(
            target_model=body.target_model,
            target_dimensions=body.target_dimensions,
            tables=body.tables,
        )
    except RuntimeError as exc:
        raise _embedding_migration_http_exception(exc) from exc
    return EmbeddingSpaceMigrationPlanResponse(**plan.to_dict())


@router.post(
    "/llm-runtime/embedding-space/migrate",
    response_model=EmbeddingSpaceMigrationRunResponse,
)
async def run_embedding_space_migration_route(
    body: EmbeddingSpaceMigrationRunRequest,
    auth: RequireAuth,
):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    try:
        result = migrate_embedding_space_rows(
            target_model=body.target_model,
            target_dimensions=body.target_dimensions,
            dry_run=body.dry_run,
            batch_size=body.batch_size,
            limit_per_table=body.limit_per_table,
            tables=body.tables,
            acknowledge_maintenance_window=body.acknowledge_maintenance_window,
        )
    except RuntimeError as exc:
        raise _embedding_migration_http_exception(exc) from exc
    return EmbeddingSpaceMigrationRunResponse(**result.to_dict())


@router.post(
    "/llm-runtime/embedding-space/promote",
    response_model=EmbeddingSpaceMigrationRunResponse,
)
async def promote_embedding_space_shadow_route(
    body: EmbeddingSpaceMigrationPromoteRequest,
    auth: RequireAuth,
):
    if not _can_manage_llm_runtime(auth):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    try:
        result = promote_embedding_space_shadow(
            target_model=body.target_model,
            target_dimensions=body.target_dimensions,
            tables=body.tables,
            acknowledge_maintenance_window=body.acknowledge_maintenance_window,
        )
    except RuntimeError as exc:
        raise _embedding_migration_http_exception(exc) from exc
    return EmbeddingSpaceMigrationRunResponse(**result.to_dict())


# =============================================================================
# Background Ingestion Task
# =============================================================================

async def _run_ingestion_background(
    job_id: str,
    document_id: str,
    pdf_path: str,
    create_neo4j_module: bool = True
):
    """
    Background task for document ingestion.
    
    Steps:
    1. Update job status to "processing"
    2. Run multimodal ingestion
    3. Create Module node in Neo4j (if enabled)
    4. Update job status to "completed" or "failed"
    """
    await run_ingestion_background_impl(
        job_id=job_id,
        document_id=document_id,
        pdf_path=pdf_path,
        create_neo4j_module=create_neo4j_module,
        ingestion_jobs=_ingestion_jobs,
        cleanup_old_jobs=_cleanup_old_jobs,
        get_ingestion_service_fn=get_ingestion_service,
        get_user_graph_repository_fn=get_user_graph_repository,
        logger_obj=logger,
    )


def _runtime_lifecycle_registration_report() -> dict[str, Any]:
    """Return operator-safe lifecycle hook registration metadata."""

    from app.engine.runtime.lifecycle import build_lifecycle_registration_report

    return build_lifecycle_registration_report()


def _post_turn_lifecycle_metrics_report() -> dict[str, Any]:
    """Return aggregate post-turn/background scheduling metrics."""

    from app.services.post_turn_lifecycle import (
        build_post_turn_lifecycle_metrics_report,
    )

    return build_post_turn_lifecycle_metrics_report()


def _runtime_flow_runtime_config(
    lifecycle_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return operator-safe runtime-flow configuration and hook health."""

    report = lifecycle_report or _runtime_lifecycle_registration_report()
    hook_counts = report.get("point_counts", {})
    owner_counts = report.get("owner_counts", {})
    return {
        "native_stream_dispatch_enabled": bool(
            settings.enable_native_stream_dispatch
        ),
        "session_event_log_backend": (
            "postgres" if settings.enable_session_event_log else "in_memory"
        ),
        "lifecycle_hook_total": report.get("registration_count", 0),
        "lifecycle_hook_owner_count": len(owner_counts),
        "lifecycle_on_run_end_hook_count": hook_counts.get("on_run_end", 0),
        "lifecycle_on_run_error_hook_count": hook_counts.get("on_run_error", 0),
    }


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/runtime-flow/doctor")
@limiter.limit("60/minute")
async def get_runtime_flow_doctor(
    request: Request,
    auth: RequireAdmin,
    session_id: str = Query(..., min_length=1),
    org_id: Optional[str] = Query(None, min_length=1),
    since_seq: Optional[int] = Query(None, ge=0),
) -> dict[str, Any]:
    """Return privacy-safe runtime-flow diagnostics for one session window."""

    report = await build_runtime_flow_doctor_report_from_session_log(
        get_session_event_log(),
        session_id=session_id,
        org_id=org_id,
        since_seq=since_seq,
    )
    lifecycle_report = _runtime_lifecycle_registration_report()
    report["runtime_config"] = _runtime_flow_runtime_config(lifecycle_report)
    report["lifecycle_registrations"] = lifecycle_report
    report["post_turn_lifecycle"] = _post_turn_lifecycle_metrics_report()
    return report


@router.get("/runtime-flow/doctor/recent")
@limiter.limit("60/minute")
async def get_recent_runtime_flow_doctor(
    request: Request,
    auth: RequireAdmin,
    org_id: Optional[str] = Query(None, min_length=1),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return aggregate runtime-flow diagnostics for recent session events."""

    report = await build_recent_runtime_flow_doctor_report_from_session_log(
        get_session_event_log(),
        org_id=org_id,
        limit=limit,
    )
    lifecycle_report = _runtime_lifecycle_registration_report()
    report["runtime_config"] = _runtime_flow_runtime_config(lifecycle_report)
    report["lifecycle_registrations"] = lifecycle_report
    report["post_turn_lifecycle"] = _post_turn_lifecycle_metrics_report()
    return report


@router.get("/runtime-flow/doctor/history")
@limiter.limit("60/minute")
async def get_runtime_flow_doctor_history(
    request: Request,
    auth: RequireAdmin,
    org_id: Optional[str] = Query(None, min_length=1),
    limit: int = Query(500, ge=1, le=500),
    bucket_limit: int = Query(24, ge=1, le=48),
) -> dict[str, Any]:
    """Return bucketed aggregate runtime-flow diagnostics over recent events."""

    report = await build_runtime_flow_doctor_history_from_session_log(
        get_session_event_log(),
        org_id=org_id,
        limit=limit,
        bucket_limit=bucket_limit,
    )
    lifecycle_report = _runtime_lifecycle_registration_report()
    report["runtime_config"] = _runtime_flow_runtime_config(lifecycle_report)
    report["lifecycle_registrations"] = lifecycle_report
    report["post_turn_lifecycle"] = _post_turn_lifecycle_metrics_report()
    return report


@router.post("/runtime-flow/session-events/prune")
@limiter.limit("10/minute")
async def prune_runtime_flow_session_events(
    request: Request,
    auth: RequireAdmin,
    retention_days: Optional[int] = Query(None, ge=1, le=3650),
    org_id: Optional[str] = Query(None, min_length=1),
    event_type: Optional[str] = Query(None, min_length=1, max_length=96),
    dry_run: bool = Query(True),
) -> dict[str, Any]:
    """Prune old session_events with aggregate-only operator evidence."""

    days = retention_days or settings.session_event_log_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    matched_count = await get_session_event_log().prune_older_than(
        cutoff=cutoff,
        org_id=org_id,
        event_type=event_type,
        dry_run=dry_run,
    )
    return {
        "schema": "wiii.session_event_log_prune.v1",
        "status": "dry_run" if dry_run else "pruned",
        "matched_count": matched_count,
        "deleted_count": 0 if dry_run else matched_count,
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "dry_run": dry_run,
        "org_scoped": org_id is not None,
        "event_type_filter_applied": event_type is not None,
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "aggregate_counts_only",
        },
        "runtime_config": {
            "session_event_log_backend": (
                "postgres" if settings.enable_session_event_log else "in_memory"
            ),
        },
    }


@router.get("/semantic-memory/doctor/recent")
@limiter.limit("60/minute")
async def get_recent_semantic_memory_doctor(
    request: Request,
    auth: RequireAdmin,
    org_id: Optional[str] = Query(None, min_length=1),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Return aggregate diagnostics for recent semantic-memory writes."""

    report = await build_recent_semantic_memory_write_doctor_report_from_session_log(
        get_session_event_log(),
        org_id=org_id,
        limit=limit,
    )
    report["runtime_config"] = {
        "multi_tenant_enabled": bool(settings.enable_multi_tenant),
        "session_event_log_backend": (
            "postgres" if settings.enable_session_event_log else "in_memory"
        ),
    }
    return report


@router.get("/semantic-memory/doctor/history")
@limiter.limit("60/minute")
async def get_semantic_memory_doctor_history(
    request: Request,
    auth: RequireAdmin,
    org_id: Optional[str] = Query(None, min_length=1),
    limit: int = Query(500, ge=1, le=1000),
    bucket_limit: int = Query(24, ge=1, le=48),
) -> dict[str, Any]:
    """Return aggregate semantic-memory write diagnostics by recent time bucket."""

    report = await build_semantic_memory_write_doctor_history_from_session_log(
        get_session_event_log(),
        org_id=org_id,
        limit=limit,
        bucket_limit=bucket_limit,
    )
    report["runtime_config"] = {
        "multi_tenant_enabled": bool(settings.enable_multi_tenant),
        "session_event_log_backend": (
            "postgres" if settings.enable_session_event_log else "in_memory"
        ),
    }
    return report


@router.post("/documents", response_model=DocumentUploadResponse)
@limiter.limit("10/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    auth: RequireAdmin,  # LMS Integration: Admin only
    file: UploadFile = File(..., description="PDF file to ingest"),
    document_id: Optional[str] = Form(None, description="Document ID (auto-generated if not provided)"),
    create_module_node: bool = Form(True, description="Create Module node in Neo4j")
):
    """
    Upload and ingest a document into knowledge base.
    
    This endpoint:
    1. Saves the uploaded PDF
    2. Starts background ingestion
    3. Returns job_id for status tracking
    4. Optionally creates Module node in Neo4j
    
    Use GET /admin/documents/{job_id} to check progress.
    """
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Generate IDs
    job_id = str(uuid4())
    doc_id = document_id or file.filename.replace(".pdf", "").replace(" ", "_").lower()
    
    # Save file temporarily
    temp_dir = tempfile.gettempdir()
    pdf_path = os.path.join(temp_dir, f"{doc_id}.pdf")
    
    try:
        content = await file.read()
        with open(pdf_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.error("Failed to save uploaded file: %s", e)
        # Clean up temp file on save failure
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        raise HTTPException(status_code=500, detail="Failed to save file")
    
    # Initialize job status
    _ingestion_jobs[job_id] = {
        "job_id": job_id,
        "document_id": doc_id,
        "status": "pending",
        "progress_percent": 0.0,
        "total_pages": 0,
        "processed_pages": 0,
        "error": None
    }
    
    # Start background ingestion
    background_tasks.add_task(
        _run_ingestion_background,
        job_id=job_id,
        document_id=doc_id,
        pdf_path=pdf_path,
        create_neo4j_module=create_module_node
    )
    
    logger.info("[ADMIN] Document upload started: %s (job_id: %s)", doc_id, job_id)
    
    return DocumentUploadResponse(
        job_id=job_id,
        document_id=doc_id,
        status="pending",
        message=f"Ingestion started. Use GET /admin/documents/{job_id} to check status."
    )


@router.get("/documents/{job_id}", response_model=DocumentStatus)
@limiter.limit("60/minute")
async def get_document_status(request: Request, job_id: str, auth: RequireAdmin):  # LMS Integration
    """
    Check ingestion job status.
    
    Returns progress information for a document ingestion job.
    """
    if job_id not in _ingestion_jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job = _ingestion_jobs[job_id]
    return DocumentStatus(**job)


@router.get("/documents", response_model=list)
@limiter.limit("60/minute")
async def list_documents(request: Request, auth: RequireAdmin):  # LMS Integration
    """
    List all documents in knowledge base.
    
    Returns list of documents with their metadata.
    """
    from sqlalchemy import text
    
    try:
        org_id = _resolve_admin_document_org(auth)
        where_clause = ""
        params: dict[str, object] = {}
        if org_id:
            where_clause = "WHERE organization_id = :org_id"
            params["org_id"] = org_id

        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(text(f"""
                SELECT 
                    document_id,
                    COUNT(*) as total_chunks,
                    MIN(created_at) as created_at
                FROM knowledge_embeddings
                {where_clause}
                GROUP BY document_id
                ORDER BY document_id
            """), params)
            
            documents = []
            for row in result.fetchall():
                documents.append({
                    "document_id": row[0],
                    "total_chunks": row[1],
                    "created_at": str(row[2]) if row[2] else None
                })
            
            return documents
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ADMIN] Failed to list documents: %s", e)
        return []


@router.delete("/documents/{document_id}")
@limiter.limit("10/minute")
async def delete_document(request: Request, document_id: str, auth: RequireAdmin):  # LMS Integration: Admin only
    """
    Delete a document from knowledge base.
    
    Removes all chunks and embeddings for the specified document.
    Also removes Module node from Neo4j if exists.
    """
    from sqlalchemy import text
    
    try:
        org_id = _resolve_admin_document_org(auth)
        where_clause = "document_id = :doc_id"
        params: dict[str, object] = {"doc_id": document_id}
        if org_id:
            where_clause += " AND organization_id = :org_id"
            params["org_id"] = org_id

        # Delete from Neon
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(
                text(f"DELETE FROM knowledge_embeddings WHERE {where_clause}"),
                params,
            )
            deleted_count = result.rowcount
            session.commit()
        
        # Delete Module node from Neo4j
        user_graph = get_user_graph_repository()
        if user_graph.is_available():
            # Note: This would need a delete method in user_graph_repository
            logger.info(
                "[ADMIN] Module node deletion not implemented yet document_hash=%s",
                _hash_admin_identifier(document_id),
            )
        
        logger.info(
            "[ADMIN] Deleted %d chunks for document_hash=%s org_hash=%s",
            deleted_count,
            _hash_admin_identifier(document_id),
            _hash_admin_identifier(org_id),
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "deleted_chunks": deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "[ADMIN] Failed to delete document_hash=%s: %s",
            _hash_admin_identifier(document_id),
            e,
        )
        raise HTTPException(status_code=500, detail="Failed to delete document")


# =============================================================================
# Domain Management Endpoints
# =============================================================================

@router.get("/domains", response_model=list[DomainSummary])
@limiter.limit("60/minute")
async def list_domains(request: Request, auth: RequireAuth):
    """
    List all registered domain plugins.

    Returns summary of each active domain with skill count and status.
    """
    registry = get_domain_registry()
    return list_domains_impl(registry=registry, summary_cls=DomainSummary)


@router.get("/domains/{domain_id}", response_model=DomainDetail)
@limiter.limit("60/minute")
async def get_domain(request: Request, domain_id: str, auth: RequireAuth):
    """
    Get detailed information about a specific domain plugin.

    Returns config, keywords, triggers, skills, and feature flags.
    """
    registry = get_domain_registry()
    detail = get_domain_detail_impl(
        registry=registry,
        domain_id=domain_id,
        detail_cls=DomainDetail,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")
    return detail


@router.get("/domains/{domain_id}/skills", response_model=list[SkillDetail])
@limiter.limit("60/minute")
async def list_domain_skills(request: Request, domain_id: str, auth: RequireAuth):
    """
    List all skills for a specific domain.

    Returns skill manifests with trigger keywords and content size.
    """
    registry = get_domain_registry()
    skill_details = list_domain_skills_impl(
        registry=registry,
        domain_id=domain_id,
        skill_detail_cls=SkillDetail,
    )
    if skill_details is None:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_id}' not found")
    return skill_details
