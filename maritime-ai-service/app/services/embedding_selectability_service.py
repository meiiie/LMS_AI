"""Runtime selectability snapshot for embedding backends."""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass
from typing import Literal

from app.core.config import settings
from app.engine.embedding_runtime import (
    openrouter_embedding_credentials_available,
    peek_semantic_embedding_backend,
    probe_ollama_embedding_model,
    resolve_embedding_dimensions_for_model,
    resolve_embedding_model_for_provider,
    resolve_embedding_provider_order,
)
from app.engine.model_catalog import (
    embedding_model_supports_dimension_override,
    get_embedding_dimensions,
    provider_can_serve_embedding_model,
)

EmbeddingProviderState = Literal["selectable", "disabled"]
EmbeddingDisabledReasonCode = Literal[
    "missing_api_key",
    "no_base_url",
    "host_down",
    "model_missing",
    "model_unverified",
    "space_mismatch",
    "dimension_mismatch",
    "invalid_response",
]

SELECTABILITY_CACHE_TTL_SECONDS = 15.0
SUPPORTED_EMBEDDING_PROVIDERS: tuple[str, ...] = (
    "google",
    "openai",
    "openrouter",
    "ollama",
    "zhipu",
)
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "google": "Gemini Embeddings",
    "openai": "OpenAI Embeddings",
    "openrouter": "OpenRouter Embeddings",
    "ollama": "Ollama Embeddings",
    "zhipu": "Zhipu Embeddings",
}


@dataclass(frozen=True)
class EmbeddingProviderSelectability:
    provider: str
    display_name: str
    state: EmbeddingProviderState
    configured: bool
    available: bool
    in_failover_chain: bool
    is_default: bool
    is_active: bool
    selected_model: str | None
    selected_dimensions: int | None
    supports_dimension_override: bool
    reason_code: EmbeddingDisabledReasonCode | None
    reason_label: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _CacheEntry:
    created_at: float
    snapshot: list[EmbeddingProviderSelectability]


_selectability_cache: _CacheEntry | None = None


def invalidate_embedding_selectability_cache() -> None:
    global _selectability_cache
    _selectability_cache = None


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider.replace("_", " ").title())


def _provider_is_configured(provider: str) -> bool:
    if provider == "google":
        return bool(getattr(settings, "google_api_key", None))
    if provider == "openai":
        return bool(getattr(settings, "openai_api_key", None))
    if provider == "openrouter":
        return openrouter_embedding_credentials_available()
    if provider == "ollama":
        return bool(getattr(settings, "ollama_base_url", None))
    if provider == "zhipu":
        return bool(getattr(settings, "zhipu_api_key", None))
    return False


def _missing_config_reason(provider: str) -> tuple[EmbeddingDisabledReasonCode, str]:
    if provider == "ollama":
        return ("no_base_url", "Chua cau hinh Ollama base URL cho embeddings.")
    if provider == "openrouter":
        return (
            "missing_api_key",
            "OpenRouter embeddings can cau hinh ro rang (API key + OpenRouter base URL).",
        )
    if provider == "zhipu":
        return ("missing_api_key", "Chua cau hinh Zhipu API key cho embeddings.")
    if provider == "google":
        return ("missing_api_key", "Chua cau hinh Google API key cho embeddings.")
    return ("missing_api_key", "Chua cau hinh API key cho embedding provider nay.")


def _build_snapshot_uncached(
    *,
    allow_local_probe: bool = True,
) -> list[EmbeddingProviderSelectability]:
    provider_order = resolve_embedding_provider_order()
    in_chain = set(provider_order)
    configured_model = getattr(settings, "embedding_model", None)

    cached_backend = peek_semantic_embedding_backend()
    active_provider: str | None = None
    if cached_backend is not None:
        is_available = getattr(cached_backend, "is_available", None)
        backend_available = bool(is_available()) if callable(is_available) else True
        if backend_available:
            active_provider = getattr(cached_backend, "provider", None)

    snapshot: list[EmbeddingProviderSelectability] = []
    default_provider = provider_order[0] if provider_order else None

    for provider in SUPPORTED_EMBEDDING_PROVIDERS:
        configured = _provider_is_configured(provider)
        selected_model = resolve_embedding_model_for_provider(provider)
        selected_dimensions = (
            resolve_embedding_dimensions_for_model(selected_model)
            if selected_model
            else None
        )
        supports_dimension_override = embedding_model_supports_dimension_override(selected_model)
        canonical_dimensions = (
            get_embedding_dimensions(selected_model) if selected_model else None
        )

        reason_code: EmbeddingDisabledReasonCode | None = None
        reason_label: str | None = None
        available = False

        if not configured:
            reason_code, reason_label = _missing_config_reason(provider)
        elif configured_model and not provider_can_serve_embedding_model(provider, configured_model):
            reason_code = "space_mismatch"
            reason_label = (
                f"Provider nay khong the phuc vu cung embedding-space hien tai ({configured_model})."
            )
        elif not selected_model:
            reason_code = "model_unverified"
            reason_label = "Provider nay chua co embedding model contract duoc xac nhan."
        elif (
            canonical_dimensions is not None
            and selected_dimensions is not None
            and not supports_dimension_override
            and canonical_dimensions != selected_dimensions
        ):
            reason_code = "dimension_mismatch"
            reason_label = (
                f"Model {selected_model} chi ho tro {canonical_dimensions}d, "
                f"nhung runtime dang yeu cau {selected_dimensions}d."
            )
        elif provider == "ollama" and not allow_local_probe:
            reason_code = "host_down"
            reason_label = (
                "Ollama local chua duoc probe trong luot tai nhanh. "
                "Chay Probe capability de kiem tra live."
            )
        elif provider == "ollama":
            probe = probe_ollama_embedding_model(
                getattr(settings, "ollama_base_url", None) or "",
                selected_model,
            )
            available = probe.available
            reason_code = probe.reason_code
            reason_label = probe.reason_label
        elif provider == "zhipu":
            reason_code = "model_unverified"
            reason_label = "Zhipu embeddings chua duoc bat cho toi khi catalog co contract ro rang."
        else:
            available = True

        snapshot.append(
            EmbeddingProviderSelectability(
                provider=provider,
                display_name=_provider_display_name(provider),
                state="selectable" if available else "disabled",
                configured=configured,
                available=available,
                in_failover_chain=provider in in_chain,
                is_default=provider == default_provider,
                is_active=provider == active_provider,
                selected_model=selected_model,
                selected_dimensions=selected_dimensions,
                supports_dimension_override=supports_dimension_override,
                reason_code=reason_code,
                reason_label=reason_label,
            )
        )

    return snapshot


def get_embedding_selectability_snapshot(
    *,
    force_refresh: bool = False,
    allow_local_probe: bool = True,
) -> list[EmbeddingProviderSelectability]:
    global _selectability_cache

    now = time.monotonic()
    if (
        not force_refresh
        and _selectability_cache is not None
        and now - _selectability_cache.created_at < SELECTABILITY_CACHE_TTL_SECONDS
    ):
        return copy.deepcopy(_selectability_cache.snapshot)

    snapshot = _build_snapshot_uncached(allow_local_probe=allow_local_probe)
    _selectability_cache = _CacheEntry(
        created_at=now,
        snapshot=copy.deepcopy(snapshot),
    )
    return snapshot
