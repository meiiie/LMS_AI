"""
Persisted runtime discovery + live capability audit for admin LLM policy.

This layer keeps operational facts separate from the runtime policy itself:
  - discovery timestamps and success/failure
  - live capability probe results
  - degraded provider annotations for admin UX
"""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel

from app.core.config import settings
from app.engine.llm_runtime_state import (
    get_llm_runtime_request_selectable_providers,
)
from app.engine.llm_provider_registry import create_provider, get_supported_provider_names
from app.engine.model_catalog import (
    ChatModelMetadata,
    GOOGLE_DEFAULT_MODEL,
    ModelCatalogService,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL_ADVANCED,
    ZHIPU_DEFAULT_MODEL,
    ZHIPU_DEFAULT_MODEL_ADVANCED,
    get_provider_chat_model_metadata,
    resolve_openai_catalog_provider,
)
from app.repositories.admin_runtime_settings_repository import (
    get_admin_runtime_settings_repository,
)
from app.services.llm_runtime_audit_snapshot_support import (
    apply_metadata_hints_impl,
    get_selected_models_impl,
    lookup_selected_model_metadata_impl,
    record_runtime_discovery_snapshot_impl,
    refresh_degraded_state_impl,
)
from app.services.llm_selectability_cache_token import (
    bump_llm_selectability_cache_generation,
)
from app.services.llm_runtime_audit_probe_support import (
    build_runtime_audit_summary_impl,
    can_probe_provider_impl,
    close_async_iterator_impl,
    probe_google_runtime_health_impl,
    probe_ollama_context_window_impl,
    probe_openai_compatible_structured_output_impl,
    probe_provider_capabilities_impl,
    probe_streaming_impl,
    probe_structured_output_impl,
    probe_tool_calling_impl,
    resolve_openai_compatible_probe_config_impl,
    run_live_capability_probes_impl,
    summarize_probe_error_impl,
)

logger = logging.getLogger(__name__)

LLM_RUNTIME_AUDIT_KEY = "llm_runtime_audit"
LLM_RUNTIME_AUDIT_DESCRIPTION = "Persisted LLM runtime discovery and capability audit"
LLM_RUNTIME_AUDIT_SCHEMA_VERSION = 1
LIVE_PROBE_TIMEOUT_SECONDS = 10.0


def reset_ollama_availability_cache() -> None:
    from app.engine.llm_providers.ollama_provider import (
        reset_ollama_availability_cache,
    )

    reset_ollama_availability_cache()


def check_ollama_host_reachable(*args: Any, **kwargs: Any) -> Any:
    from app.engine.llm_providers.ollama_provider import check_ollama_host_reachable

    return check_ollama_host_reachable(*args, **kwargs)

_PROVIDER_EXPECTED_CAPABILITIES: dict[str, dict[str, bool]] = {
    "google": {
        "tool_calling": True,
        "structured_output": True,
        "streaming": True,
    },
    "openai": {
        "tool_calling": True,
        "structured_output": True,
        "streaming": True,
    },
    "openrouter": {
        "streaming": True,
    },
    "nvidia": {
        "streaming": True,
    },
    "zhipu": {
        "tool_calling": True,
        "structured_output": True,
        "streaming": True,
    },
    "ollama": {
        "streaming": True,
    },
}

_PROVIDER_STR_FIELDS = frozenset(
    {
        "provider",
        "selected_model",
        "selected_model_advanced",
        "probe_model",
        "catalog_source",
        "last_discovery_attempt_at",
        "last_discovery_success_at",
        "last_discovery_error",
        "last_live_probe_attempt_at",
        "last_live_probe_success_at",
        "last_live_probe_error",
        "live_probe_note",
        "last_runtime_observation_at",
        "last_runtime_success_at",
        "last_runtime_error",
        "last_runtime_note",
        "last_runtime_source",
        "tool_calling_source",
        "structured_output_source",
        "streaming_source",
        "context_window_source",
        "max_output_source",
    }
)
_PROVIDER_BOOL_FIELDS = frozenset(
    {
        "runtime_discovery_enabled",
        "runtime_discovery_succeeded",
        "degraded",
    }
)
_PROVIDER_OPTIONAL_BOOL_FIELDS = frozenset(
    {
        "selected_model_in_catalog",
        "selected_model_advanced_in_catalog",
        "tool_calling_supported",
        "structured_output_supported",
        "streaming_supported",
    }
)
_PROVIDER_INT_FIELDS = frozenset(
    {
        "model_count",
        "discovered_model_count",
        "context_window_tokens",
        "max_output_tokens",
    }
)


@dataclass(frozen=True)
class LlmRuntimeAuditRecord:
    payload: dict[str, Any]
    updated_at: Optional[datetime]
    persisted: bool = False
    warnings: tuple[str, ...] = ()


class _StructuredProbeResult(BaseModel):
    status: str
    detail: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _provider_recovered_since_probe(state: Mapping[str, Any]) -> bool:
    probe_attempt_at = _parse_iso(state.get("last_live_probe_attempt_at"))
    runtime_observation_at = _parse_iso(state.get("last_runtime_observation_at"))
    runtime_success_at = _parse_iso(state.get("last_runtime_success_at"))
    probe_success_at = _parse_iso(state.get("last_live_probe_success_at"))
    probe_error = str(state.get("last_live_probe_error") or "").strip()
    if runtime_success_at is None or runtime_observation_at is None or probe_attempt_at is None:
        return False
    if runtime_success_at < probe_attempt_at:
        return False
    if runtime_success_at < runtime_observation_at:
        return False
    if probe_success_at is not None and probe_success_at >= runtime_success_at:
        return False
    return bool(probe_error)


def _coerce_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, Mapping):
                return dumped
        except Exception:
            return None
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            if isinstance(dumped, Mapping):
                return dumped
        except Exception:
            return None
    return None


def infer_runtime_completion_degraded_reason(metadata: Mapping[str, Any] | Any | None) -> str | None:
    root = _coerce_mapping(metadata)
    if root is None:
        return None
    reasoning_trace = root.get("reasoning_trace", root)
    trace_mapping = _coerce_mapping(reasoning_trace)
    if trace_mapping is None:
        return None
    steps = trace_mapping.get("steps")
    if not isinstance(steps, list):
        return None

    for raw_step in steps:
        step = _coerce_mapping(raw_step)
        if step is None:
            continue
        details = _coerce_mapping(step.get("details")) or {}
        response_type = str(details.get("response_type") or "").strip().lower()
        result = str(step.get("result") or "").strip()
        lowered_result = result.lower()
        if response_type == "fallback":
            if "llm generation error" in lowered_result:
                return "fallback response (LLM generation error)"
            return "fallback response"
        if "fallback (llm generation error)" in lowered_result:
            return "fallback response (LLM generation error)"
        if lowered_result.startswith("fallback"):
            return "fallback response"
    return None


def _truncate_runtime_note(value: Any, *, limit: int = 220) -> str | None:
    compact = " ".join(str(value or "").split()).strip()
    if not compact:
        return None
    return compact[:limit]


def _normalize_provider_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _default_provider_state(provider: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "selected_model": None,
        "selected_model_advanced": None,
        "selected_model_in_catalog": None,
        "selected_model_advanced_in_catalog": None,
        "probe_model": None,
        "catalog_source": "static",
        "runtime_discovery_enabled": False,
        "runtime_discovery_succeeded": False,
        "model_count": 0,
        "discovered_model_count": 0,
        "last_discovery_attempt_at": None,
        "last_discovery_success_at": None,
        "last_discovery_error": None,
        "last_live_probe_attempt_at": None,
        "last_live_probe_success_at": None,
        "last_live_probe_error": None,
        "live_probe_note": None,
        "last_runtime_observation_at": None,
        "last_runtime_success_at": None,
        "last_runtime_error": None,
        "last_runtime_note": None,
        "last_runtime_source": None,
        "degraded": False,
        "degraded_reasons": [],
        "tool_calling_supported": None,
        "tool_calling_source": None,
        "structured_output_supported": None,
        "structured_output_source": None,
        "streaming_supported": None,
        "streaming_source": None,
        "context_window_tokens": None,
        "context_window_source": None,
        "max_output_tokens": None,
        "max_output_source": None,
    }


def _default_audit_payload() -> dict[str, Any]:
    return {
        "schema_version": LLM_RUNTIME_AUDIT_SCHEMA_VERSION,
        "audit_updated_at": None,
        "last_live_probe_at": None,
        "providers": {
            provider: _default_provider_state(provider)
            for provider in get_supported_provider_names()
        },
    }


def sanitize_llm_runtime_audit_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    clean = _default_audit_payload()
    if not isinstance(payload, Mapping):
        return clean

    audit_updated_at = payload.get("audit_updated_at")
    if isinstance(audit_updated_at, str) and audit_updated_at.strip():
        clean["audit_updated_at"] = audit_updated_at.strip()
    last_live_probe_at = payload.get("last_live_probe_at")
    if isinstance(last_live_probe_at, str) and last_live_probe_at.strip():
        clean["last_live_probe_at"] = last_live_probe_at.strip()

    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, Mapping):
        return clean

    for provider in get_supported_provider_names():
        raw_state = raw_providers.get(provider)
        if not isinstance(raw_state, Mapping):
            continue
        state = clean["providers"][provider]

        for field_name in _PROVIDER_STR_FIELDS:
            value = raw_state.get(field_name)
            if isinstance(value, str):
                state[field_name] = value.strip() or None

        for field_name in _PROVIDER_BOOL_FIELDS:
            value = raw_state.get(field_name)
            if isinstance(value, bool):
                state[field_name] = value

        for field_name in _PROVIDER_OPTIONAL_BOOL_FIELDS:
            value = raw_state.get(field_name)
            if value is None or isinstance(value, bool):
                state[field_name] = value

        for field_name in _PROVIDER_INT_FIELDS:
            value = raw_state.get(field_name)
            if isinstance(value, int):
                state[field_name] = value

        degraded_reasons = raw_state.get("degraded_reasons")
        if isinstance(degraded_reasons, list):
            state["degraded_reasons"] = [
                str(reason).strip()
                for reason in degraded_reasons
                if str(reason).strip()
            ]

    return clean


def get_persisted_llm_runtime_audit() -> Optional[LlmRuntimeAuditRecord]:
    repo = get_admin_runtime_settings_repository()
    record = repo.get_settings(LLM_RUNTIME_AUDIT_KEY)
    if record is None:
        return None
    return LlmRuntimeAuditRecord(
        payload=sanitize_llm_runtime_audit_payload(record.settings),
        updated_at=record.updated_at,
        persisted=True,
    )


def persist_llm_runtime_audit_snapshot(snapshot: Mapping[str, Any]) -> Optional[LlmRuntimeAuditRecord]:
    repo = get_admin_runtime_settings_repository()
    clean = sanitize_llm_runtime_audit_payload(snapshot)
    record = repo.upsert_settings(
        LLM_RUNTIME_AUDIT_KEY,
        clean,
        description=LLM_RUNTIME_AUDIT_DESCRIPTION,
    )
    if record is None:
        return LlmRuntimeAuditRecord(
            payload=clean,
            updated_at=_utcnow(),
            persisted=False,
            warnings=(
                "Could not persist LLM runtime audit to admin_runtime_settings. "
                "Run the admin runtime settings migration to enable durable audit history.",
            ),
        )
    return LlmRuntimeAuditRecord(
        payload=sanitize_llm_runtime_audit_payload(record.settings),
        updated_at=record.updated_at,
        persisted=True,
    )


def _get_current_audit_payload() -> dict[str, Any]:
    existing = get_persisted_llm_runtime_audit()
    if existing and existing.payload:
        return copy.deepcopy(existing.payload)
    return _default_audit_payload()


def _get_selected_models() -> dict[str, dict[str, str | None]]:
    return get_selected_models_impl(
        settings_obj=settings,
        resolve_openai_catalog_provider_fn=resolve_openai_catalog_provider,
        google_default_model=GOOGLE_DEFAULT_MODEL,
        openai_default_model=OPENAI_DEFAULT_MODEL,
        openai_default_model_advanced=OPENAI_DEFAULT_MODEL_ADVANCED,
        zhipu_default_model=ZHIPU_DEFAULT_MODEL,
        zhipu_default_model_advanced=ZHIPU_DEFAULT_MODEL_ADVANCED,
    )


def _lookup_selected_model_metadata(
    catalog: Mapping[str, Any],
    provider: str,
    model_name: str | None,
) -> ChatModelMetadata | None:
    return lookup_selected_model_metadata_impl(
        catalog=catalog,
        provider=provider,
        model_name=model_name,
        get_provider_chat_model_metadata_fn=get_provider_chat_model_metadata,
    )


def _apply_metadata_hints(
    state: dict[str, Any],
    metadata: ChatModelMetadata | None,
) -> None:
    apply_metadata_hints_impl(
        state=state,
        metadata=metadata,
    )


def _refresh_degraded_state(provider: str, state: dict[str, Any]) -> None:
    refresh_degraded_state_impl(
        provider=provider,
        state=state,
        expected_capabilities=_PROVIDER_EXPECTED_CAPABILITIES,
    )


def _apply_provider_runtime_observation(
    *,
    payload: dict[str, Any],
    provider: str,
    success: bool,
    model_name: str | None,
    note: str | None,
    error: str | None,
    source: str,
    now_iso: str,
) -> None:
    normalized_provider = _normalize_provider_name(provider)
    if normalized_provider not in get_supported_provider_names():
        return
    provider_payload = payload["providers"].setdefault(
        normalized_provider,
        _default_provider_state(normalized_provider),
    )
    normalized_model_name = str(model_name or "").strip() or None
    if normalized_model_name:
        if provider_payload.get("selected_model") != normalized_model_name:
            provider_payload["selected_model_in_catalog"] = None
            provider_payload["selected_model_advanced_in_catalog"] = None
        provider_payload["selected_model"] = normalized_model_name
        provider_payload["probe_model"] = normalized_model_name
    provider_payload["last_runtime_observation_at"] = now_iso
    provider_payload["last_runtime_source"] = source
    provider_payload["last_runtime_note"] = _truncate_runtime_note(note)
    if success:
        provider_payload["last_runtime_success_at"] = now_iso
        provider_payload["last_runtime_error"] = None
    else:
        provider_payload["last_runtime_error"] = (
            _truncate_runtime_note(error)
            or _truncate_runtime_note(note)
            or "LLM runtime call failed."
        )
    _refresh_degraded_state(normalized_provider, provider_payload)


def record_llm_runtime_observation(
    *,
    provider: str | None,
    success: bool,
    model_name: str | None = None,
    note: str | None = None,
    error: str | None = None,
    source: str = "chat_runtime",
    failover: Mapping[str, Any] | None = None,
    degraded_reason: str | None = None,
) -> Optional[LlmRuntimeAuditRecord]:
    payload = _get_current_audit_payload()
    now_iso = _iso(_utcnow())
    if not now_iso:
        return get_persisted_llm_runtime_audit()

    normalized_provider = _normalize_provider_name(provider)
    failover_route = failover.get("route") if isinstance(failover, Mapping) else None
    if isinstance(failover_route, list):
        for event in failover_route:
            if not isinstance(event, Mapping):
                continue
            from_provider = _normalize_provider_name(event.get("from_provider"))
            to_provider = _normalize_provider_name(event.get("to_provider"))
            if not from_provider:
                continue
            detail = (
                event.get("reason_label")
                or event.get("detail")
                or event.get("reason_code")
            )
            failover_note = _truncate_runtime_note(
                f"{source}: failover {from_provider}"
                f"{f' -> {to_provider}' if to_provider and to_provider != from_provider else ''}"
                f"{f' ({detail})' if detail else ''}."
            )
            _apply_provider_runtime_observation(
                payload=payload,
                provider=from_provider,
                success=False,
                model_name=None,
                note=failover_note,
                error=detail,
                source=f"{source}:failover",
                now_iso=now_iso,
            )
            if normalized_provider is None and to_provider:
                normalized_provider = to_provider

    if normalized_provider:
        runtime_note = note
        if success and not runtime_note:
            if isinstance(failover_route, list) and failover_route:
                first_event = next(
                    (
                        event for event in failover_route
                        if isinstance(event, Mapping)
                        and _normalize_provider_name(event.get("from_provider"))
                    ),
                    None,
                )
                from_provider = (
                    _normalize_provider_name(first_event.get("from_provider"))
                    if isinstance(first_event, Mapping)
                    else None
                )
                last_event = next(
                    (
                        event for event in reversed(failover_route)
                        if isinstance(event, Mapping)
                    ),
                    None,
                )
                reason = (
                    last_event.get("reason_label")
                    or last_event.get("reason_code")
                    if isinstance(last_event, Mapping)
                    else None
                )
                runtime_note = _truncate_runtime_note(
                    f"{source}: completed via {normalized_provider}"
                    f"{f'/{model_name}' if model_name else ''}"
                    f"{f' after failover from {from_provider}' if from_provider and from_provider != normalized_provider else ''}"
                    f"{f' ({reason})' if reason else ''}."
                )
            else:
                runtime_note = _truncate_runtime_note(
                    f"{source}: completed via {normalized_provider}"
                    f"{f'/{model_name}' if model_name else ''}."
                )
        if success and degraded_reason:
            runtime_note = _truncate_runtime_note(
                f"{str(runtime_note or '').strip()} Completion degraded: {degraded_reason}.".strip()
            )
        _apply_provider_runtime_observation(
            payload=payload,
            provider=normalized_provider,
            success=success,
            model_name=model_name,
            note=runtime_note,
            error=error,
            source=source,
            now_iso=now_iso,
        )

    payload["audit_updated_at"] = now_iso
    record = persist_llm_runtime_audit_snapshot(payload)
    bump_llm_selectability_cache_generation()
    return record


def record_runtime_discovery_snapshot(catalog: Mapping[str, Any]) -> Optional[LlmRuntimeAuditRecord]:
    return record_runtime_discovery_snapshot_impl(
        catalog=catalog,
        get_current_audit_payload_fn=_get_current_audit_payload,
        get_selected_models_fn=_get_selected_models,
        supported_provider_names=get_supported_provider_names(),
        default_provider_state_fn=_default_provider_state,
        lookup_selected_model_metadata_fn=_lookup_selected_model_metadata,
        apply_metadata_hints_fn=_apply_metadata_hints,
        refresh_degraded_state_fn=_refresh_degraded_state,
        iso_fn=_iso,
        utcnow_fn=_utcnow,
        persist_snapshot_fn=persist_llm_runtime_audit_snapshot,
    )


async def _close_async_iterator(iterator: Any) -> None:
    await close_async_iterator_impl(iterator)


async def _probe_streaming(llm: Any) -> bool:
    return await probe_streaming_impl(
        llm=llm,
        timeout_seconds=LIVE_PROBE_TIMEOUT_SECONDS,
        close_async_iterator_fn=_close_async_iterator,
    )


async def _probe_tool_calling(provider: str, llm: Any) -> bool:
    return await probe_tool_calling_impl(
        provider=provider,
        llm=llm,
        timeout_seconds=LIVE_PROBE_TIMEOUT_SECONDS,
    )


def _resolve_openai_compatible_probe_config(
    provider: str,
    model_name: str | None,
) -> tuple[str | None, str | None, dict[str, str]]:
    del model_name
    return resolve_openai_compatible_probe_config_impl(
        provider=provider,
        settings_obj=settings,
    )


async def _probe_openai_compatible_structured_output(
    provider: str,
    model_name: str | None,
) -> bool:
    return await probe_openai_compatible_structured_output_impl(
        provider=provider,
        model_name=model_name,
        timeout_seconds=LIVE_PROBE_TIMEOUT_SECONDS,
        resolve_probe_config_fn=_resolve_openai_compatible_probe_config,
    )


async def _probe_google_runtime_health(model_name: str | None) -> None:
    await probe_google_runtime_health_impl(
        model_name=model_name,
        google_api_key=settings.google_api_key,
        timeout_seconds=LIVE_PROBE_TIMEOUT_SECONDS,
    )


async def _probe_structured_output(
    provider: str,
    llm: Any,
    model_name: str | None,
) -> bool:
    return await probe_structured_output_impl(
        provider=provider,
        llm=llm,
        model_name=model_name,
        timeout_seconds=LIVE_PROBE_TIMEOUT_SECONDS,
        structured_result_cls=_StructuredProbeResult,
        probe_openai_structured_output_fn=_probe_openai_compatible_structured_output,
    )


async def _probe_ollama_context_window(model_name: str | None) -> tuple[int | None, str | None]:
    return await probe_ollama_context_window_impl(
        model_name=model_name,
        ollama_base_url=settings.ollama_base_url,
        ollama_api_key=getattr(settings, "ollama_api_key", None),
    )


def _can_probe_provider(provider: str) -> tuple[bool, str | None]:
    return can_probe_provider_impl(
        provider=provider,
        settings_obj=settings,
        resolve_openai_catalog_provider_fn=resolve_openai_catalog_provider,
        create_provider_fn=create_provider,
        reset_ollama_availability_cache_fn=reset_ollama_availability_cache,
        check_ollama_host_reachable_fn=check_ollama_host_reachable,
        summarize_probe_error_fn=_summarize_probe_error,
    )


def _summarize_probe_error(label: str, exc: Exception) -> str:
    return summarize_probe_error_impl(label=label, exc=exc)


async def _probe_provider_capabilities(provider: str) -> dict[str, Any]:
    return await probe_provider_capabilities_impl(
        provider=provider,
        get_selected_models_fn=_get_selected_models,
        probe_google_runtime_health_fn=_probe_google_runtime_health,
        create_provider_fn=create_provider,
        summarize_probe_error_fn=_summarize_probe_error,
        probe_tool_calling_fn=_probe_tool_calling,
        probe_structured_output_fn=_probe_structured_output,
        probe_streaming_fn=_probe_streaming,
        probe_ollama_context_window_fn=_probe_ollama_context_window,
    )


async def run_live_capability_probes(
    catalog: Mapping[str, Any],
    providers: list[str] | None = None,
) -> Optional[LlmRuntimeAuditRecord]:
    return await run_live_capability_probes_impl(
        catalog=catalog,
        providers=providers,
        get_current_audit_payload_fn=_get_current_audit_payload,
        get_selected_models_fn=_get_selected_models,
        iso_now=_iso(_utcnow()),
        supported_provider_names=list(get_supported_provider_names()),
        lookup_selected_model_metadata_fn=_lookup_selected_model_metadata,
        apply_metadata_hints_fn=_apply_metadata_hints,
        can_probe_provider_fn=_can_probe_provider,
        refresh_degraded_state_fn=_refresh_degraded_state,
        probe_provider_capabilities_fn=_probe_provider_capabilities,
        summarize_probe_error_fn=_summarize_probe_error,
        persist_snapshot_fn=persist_llm_runtime_audit_snapshot,
    )


def build_runtime_audit_summary(
    audit_record: LlmRuntimeAuditRecord | None,
) -> dict[str, Any]:
    return build_runtime_audit_summary_impl(
        audit_record,
        sanitize_payload_fn=sanitize_llm_runtime_audit_payload,
    )


async def refresh_request_selectable_runtime_audit(
    *,
    run_live_probe: bool = True,
    providers: list[str] | None = None,
) -> Optional[LlmRuntimeAuditRecord]:
    """Refresh persisted runtime discovery/live probe for chat-selectable providers."""
    catalog = await ModelCatalogService.get_full_catalog(
        ollama_base_url=settings.ollama_base_url if settings.ollama_base_url else None,
        active_provider=settings.llm_provider,
        google_api_key=settings.google_api_key,
        openai_base_url=settings.openai_base_url,
        openai_api_key=settings.openai_api_key,
        openrouter_base_url=getattr(settings, "openrouter_base_url", None),
        openrouter_api_key=getattr(settings, "openrouter_api_key", None),
        nvidia_base_url=getattr(settings, "nvidia_base_url", None),
        nvidia_api_key=getattr(settings, "nvidia_api_key", None),
        zhipu_base_url=getattr(settings, "zhipu_base_url", None),
        zhipu_api_key=getattr(settings, "zhipu_api_key", None),
    )
    discovery_record = record_runtime_discovery_snapshot(catalog)
    targets = providers or get_llm_runtime_request_selectable_providers()
    audit_record = discovery_record
    if run_live_probe and targets:
        audit_record = await run_live_capability_probes(
            catalog,
            providers=targets,
        ) or discovery_record

    bump_llm_selectability_cache_generation()

    return audit_record


async def background_refresh_request_selectable_runtime_audit(
    run_live_probe: bool = True,
) -> None:
    """Best-effort background audit refresh triggered on startup."""
    try:
        await refresh_request_selectable_runtime_audit(run_live_probe=run_live_probe)
    except Exception as exc:
        logger.warning("Background LLM runtime audit refresh failed: %s", exc)
