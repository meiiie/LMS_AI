"""Canonical runtime model metadata shared across active backend paths."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.model_catalog_runtime_support import (
    coerce_optional_bool,
    coerce_optional_int,
    extract_openai_compatible_capabilities,
    extract_openai_compatible_limits,
    hash_secret,
    looks_like_chat_model,
    merge_catalog,
    normalize_google_model_name,
    normalize_openai_compatible_base_url,
    run_cached_discovery,
)
from app.engine.model_catalog_service_runtime import (
    discover_google_models_impl,
    discover_ollama_models_impl,
    discover_ollama_models_result_impl,
    discover_openai_compatible_models_impl,
    fetch_google_models_impl,
    fetch_openai_compatible_models_impl,
    get_full_catalog_impl,
    reset_cache_impl,
)

_catalog_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatModelMetadata:
    provider: str
    model_name: str
    display_name: str
    status: str
    released_on: str | None = None
    supports_tool_calling: bool | None = None
    supports_structured_output: bool | None = None
    supports_streaming: bool | None = None
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    capability_source: str | None = None


@dataclass(frozen=True)
class EmbeddingModelMetadata:
    model_name: str
    display_name: str
    dimensions: int
    status: str
    released_on: str | None = None
    production_default: bool = False
    provider: str = "google"
    supports_dimension_override: bool = False


GOOGLE_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
GOOGLE_LEGACY_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
)
GOOGLE_DEEP_MODEL = "gemini-3.1-pro-preview"
ZHIPU_DEFAULT_MODEL = "glm-4.5-air"
ZHIPU_DEFAULT_MODEL_ADVANCED = "glm-5"

OPENAI_DEFAULT_MODEL = "gpt-5.4-mini"
OPENAI_DEFAULT_MODEL_ADVANCED = "gpt-5.4"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-oss-20b:free"
OPENROUTER_DEFAULT_MODEL_ADVANCED = "openai/gpt-oss-120b:free"
ZHIPU_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"

# NVIDIA NIM — OpenAI-compatible endpoint (Issue #110)
# Free tier available with NGC API key from build.nvidia.com.
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_QWEN_INSTRUCT_MODEL = "qwen/qwen3-next-80b-a3b-instruct"
NVIDIA_QWEN_THINKING_MODEL = "qwen/qwen3-next-80b-a3b-thinking"
NVIDIA_DEEPSEEK_FLASH_MODEL = "deepseek-ai/deepseek-v4-flash"
NVIDIA_DEEPSEEK_PRO_MODEL = "deepseek-ai/deepseek-v4-pro"
NVIDIA_DEFAULT_MODEL = NVIDIA_QWEN_INSTRUCT_MODEL
NVIDIA_DEFAULT_MODEL_ADVANCED = NVIDIA_QWEN_THINKING_MODEL
NVIDIA_DEFAULT_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"
# Phase 32a (#207): Qwen3 thinking model emits ``reasoning_content`` deltas
# that Wiii's existing thinking-stream extractor already understands.
# The default NVIDIA profile stays on Qwen for both normal and deep turns so
# Wiii does not silently fall back to DeepSeek when env overrides are absent.
NVIDIA_THINKING_MODEL = NVIDIA_QWEN_THINKING_MODEL

GOOGLE_CHAT_MODELS: dict[str, ChatModelMetadata] = {
    GOOGLE_DEFAULT_MODEL: ChatModelMetadata(
        provider="google",
        model_name=GOOGLE_DEFAULT_MODEL,
        display_name="Gemini 3.1 Flash-Lite Preview",
        status="current",
        released_on="2026-03-03",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    GOOGLE_DEEP_MODEL: ChatModelMetadata(
        provider="google",
        model_name=GOOGLE_DEEP_MODEL,
        display_name="Gemini 3.1 Pro Preview",
        status="current",
        released_on="2026-03-03",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    "gemini-2.5-flash": ChatModelMetadata(
        provider="google",
        model_name="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        status="legacy",
    ),
    "gemini-2.5-pro": ChatModelMetadata(
        provider="google",
        model_name="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        status="legacy",
    ),
    "gemini-2.0-flash": ChatModelMetadata(
        provider="google",
        model_name="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        status="legacy",
    ),
    "gemini-2.0-flash-exp": ChatModelMetadata(
        provider="google",
        model_name="gemini-2.0-flash-exp",
        display_name="Gemini 2.0 Flash Experimental",
        status="legacy",
    ),
}

OPENAI_CHAT_MODELS: dict[str, ChatModelMetadata] = {
    OPENAI_DEFAULT_MODEL_ADVANCED: ChatModelMetadata(
        provider="openai",
        model_name=OPENAI_DEFAULT_MODEL_ADVANCED,
        display_name="GPT-5.4",
        status="current",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    OPENAI_DEFAULT_MODEL: ChatModelMetadata(
        provider="openai",
        model_name=OPENAI_DEFAULT_MODEL,
        display_name="GPT-5.4 Mini",
        status="current",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    "gpt-5.4-nano": ChatModelMetadata(
        provider="openai",
        model_name="gpt-5.4-nano",
        display_name="GPT-5.4 Nano",
        status="current",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    "gpt-5.1": ChatModelMetadata(
        provider="openai",
        model_name="gpt-5.1",
        display_name="GPT-5.1",
        status="available",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    "gpt-5-mini": ChatModelMetadata(
        provider="openai",
        model_name="gpt-5-mini",
        display_name="GPT-5 Mini",
        status="available",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
    "gpt-5": ChatModelMetadata(
        provider="openai",
        model_name="gpt-5",
        display_name="GPT-5",
        status="available",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        capability_source="static",
    ),
}

DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_BENCHMARK_CANDIDATE = "gemini-embedding-2-preview"
OPENAI_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_LARGE_EMBEDDING_MODEL = "text-embedding-3-large"
OLLAMA_DEFAULT_EMBEDDING_MODEL = "embeddinggemma"

EMBEDDING_MODELS: dict[str, EmbeddingModelMetadata] = {
    DEFAULT_EMBEDDING_MODEL: EmbeddingModelMetadata(
        model_name=DEFAULT_EMBEDDING_MODEL,
        display_name="Gemini Embedding 001",
        dimensions=768,
        status="stable",
        production_default=True,
        provider="google",
        supports_dimension_override=True,
    ),
    EMBEDDING_BENCHMARK_CANDIDATE: EmbeddingModelMetadata(
        model_name=EMBEDDING_BENCHMARK_CANDIDATE,
        display_name="Gemini Embedding 2 Preview",
        dimensions=3072,
        status="preview",
        released_on="2026-03-10",
        provider="google",
        supports_dimension_override=True,
    ),
    OPENAI_DEFAULT_EMBEDDING_MODEL: EmbeddingModelMetadata(
        model_name=OPENAI_DEFAULT_EMBEDDING_MODEL,
        display_name="OpenAI Text Embedding 3 Small",
        dimensions=1536,
        status="current",
        provider="openai",
        supports_dimension_override=True,
    ),
    OPENAI_LARGE_EMBEDDING_MODEL: EmbeddingModelMetadata(
        model_name=OPENAI_LARGE_EMBEDDING_MODEL,
        display_name="OpenAI Text Embedding 3 Large",
        dimensions=3072,
        status="current",
        provider="openai",
        supports_dimension_override=True,
    ),
    OLLAMA_DEFAULT_EMBEDDING_MODEL: EmbeddingModelMetadata(
        model_name=OLLAMA_DEFAULT_EMBEDDING_MODEL,
        display_name="EmbeddingGemma",
        dimensions=768,
        status="available",
        provider="ollama",
    ),
}


def get_chat_model_metadata(model_name: str | None) -> ChatModelMetadata | None:
    if not model_name:
        return None
    return GOOGLE_CHAT_MODELS.get(model_name)


def get_provider_chat_model_metadata(
    provider: str | None,
    model_name: str | None,
) -> ChatModelMetadata | None:
    if not provider or not model_name:
        return None
    return get_all_static_chat_models().get(provider, {}).get(model_name)


def get_embedding_model_metadata(model_name: str | None) -> EmbeddingModelMetadata | None:
    if not model_name:
        return None
    return EMBEDDING_MODELS.get(model_name)


def get_embedding_dimensions(model_name: str | None) -> int:
    metadata = get_embedding_model_metadata(model_name)
    if metadata is None:
        return EMBEDDING_MODELS[DEFAULT_EMBEDDING_MODEL].dimensions
    return metadata.dimensions


def get_embedding_provider(model_name: str | None) -> str:
    metadata = get_embedding_model_metadata(model_name)
    if metadata is not None:
        return metadata.provider
    normalized = (model_name or "").strip().lower()
    if normalized.startswith("models/gemini-") or normalized.startswith("gemini-embedding-"):
        return "google"
    if normalized.startswith("text-embedding-"):
        return "openai"
    if normalized.startswith(("embeddinggemma", "qwen3-embedding", "all-minilm", "nomic-embed")):
        return "ollama"
    return "google"


def embedding_model_supports_dimension_override(model_name: str | None) -> bool:
    metadata = get_embedding_model_metadata(model_name)
    if metadata is not None:
        return metadata.supports_dimension_override
    normalized = (model_name or "").strip().lower()
    return normalized.startswith("text-embedding-3")


def get_default_embedding_model_for_provider(provider: str | None) -> str | None:
    if provider == "openai":
        return OPENAI_DEFAULT_EMBEDDING_MODEL
    if provider == "openrouter":
        return OPENAI_DEFAULT_EMBEDDING_MODEL
    if provider == "ollama":
        return OLLAMA_DEFAULT_EMBEDDING_MODEL
    if provider == "zhipu":
        return None
    return DEFAULT_EMBEDDING_MODEL


def provider_can_serve_embedding_model(
    provider: str | None,
    model_name: str | None,
) -> bool:
    """Return True when a transport/provider can serve the configured embedding space."""
    normalized_provider = (provider or "").strip().lower()
    if not normalized_provider or not model_name:
        return False

    model_provider = get_embedding_provider(model_name)
    if normalized_provider == model_provider:
        return True

    # OpenRouter can proxy OpenAI embedding models while preserving model-space.
    if normalized_provider == "openrouter" and model_provider == "openai":
        return True

    return False


def is_legacy_google_model(model_name: str | None) -> bool:
    metadata = get_chat_model_metadata(model_name)
    return metadata is not None and metadata.status == "legacy"


def get_current_google_chat_models() -> tuple[str, ...]:
    return tuple(
        model.model_name
        for model in GOOGLE_CHAT_MODELS.values()
        if model.status == "current"
    )


# ---------------------------------------------------------------------------
# Multi-provider static catalogs
# ---------------------------------------------------------------------------

OPENROUTER_CHAT_MODELS: dict[str, ChatModelMetadata] = {
    "openai/gpt-oss-20b:free": ChatModelMetadata(
        provider="openrouter",
        model_name="openai/gpt-oss-20b:free",
        display_name="GPT-OSS 20B (Free)",
        status="preset",
        supports_streaming=True,
        capability_source="static",
    ),
    "openai/gpt-oss-120b:free": ChatModelMetadata(
        provider="openrouter",
        model_name="openai/gpt-oss-120b:free",
        display_name="GPT-OSS 120B (Free)",
        status="preset",
        supports_streaming=True,
        capability_source="static",
    ),
}

ZHIPU_CHAT_MODELS: dict[str, ChatModelMetadata] = {
    ZHIPU_DEFAULT_MODEL: ChatModelMetadata(
        provider="zhipu",
        model_name=ZHIPU_DEFAULT_MODEL,
        display_name="GLM-4.5 Air (Zhipu AI)",
        status="current",
        released_on="2025-08-09",
        supports_streaming=True,
        capability_source="static",
    ),
    "glm-4.7-flash": ChatModelMetadata(
        provider="zhipu",
        model_name="glm-4.7-flash",
        display_name="GLM-4.7 Flash (Zhipu AI)",
        status="available",
        supports_streaming=True,
        capability_source="static",
    ),
    "glm-5": ChatModelMetadata(
        provider="zhipu",
        model_name="glm-5",
        display_name="GLM-5 (Zhipu AI)",
        status="current",
        released_on="2026-03",
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_streaming=True,
        context_window_tokens=200000,
        max_output_tokens=128000,
        capability_source="static",
    ),
    "glm-4.7": ChatModelMetadata(
        provider="zhipu",
        model_name="glm-4.7",
        display_name="GLM-4.7 (Zhipu AI)",
        status="legacy",
    ),
}

OLLAMA_KNOWN_MODELS: dict[str, ChatModelMetadata] = {
    "qwen3:4b-instruct-2507-q4_K_M": ChatModelMetadata(
        provider="ollama",
        model_name="qwen3:4b-instruct-2507-q4_K_M",
        display_name="Qwen3 4B Instruct (Q4_K_M)",
        status="preset",
        supports_streaming=True,
        capability_source="static",
    ),
    "qwen3:8b": ChatModelMetadata(
        provider="ollama",
        model_name="qwen3:8b",
        display_name="Qwen3 8B",
        status="preset",
        supports_streaming=True,
        capability_source="static",
    ),
}

NVIDIA_CHAT_MODELS: dict[str, ChatModelMetadata] = {
    NVIDIA_DEFAULT_MODEL: ChatModelMetadata(
        provider="nvidia",
        model_name=NVIDIA_DEFAULT_MODEL,
        display_name="Qwen3 Next 80B Instruct (NVIDIA NIM)",
        status="current",
        supports_streaming=True,
        supports_structured_output=False,
        capability_source="static",
    ),
    NVIDIA_DEFAULT_MODEL_ADVANCED: ChatModelMetadata(
        provider="nvidia",
        model_name=NVIDIA_DEFAULT_MODEL_ADVANCED,
        display_name="Qwen3 80B Thinking (NVIDIA NIM)",
        status="current",
        supports_streaming=True,
        supports_structured_output=False,
        capability_source="static",
    ),
    NVIDIA_DEEPSEEK_FLASH_MODEL: ChatModelMetadata(
        provider="nvidia",
        model_name=NVIDIA_DEEPSEEK_FLASH_MODEL,
        display_name="DeepSeek V4 Flash (NVIDIA NIM)",
        status="legacy",
        supports_streaming=True,
        supports_structured_output=False,
        capability_source="static",
    ),
    NVIDIA_DEEPSEEK_PRO_MODEL: ChatModelMetadata(
        provider="nvidia",
        model_name=NVIDIA_DEEPSEEK_PRO_MODEL,
        display_name="DeepSeek V4 Pro (NVIDIA NIM)",
        status="legacy",
        supports_streaming=True,
        supports_structured_output=False,
        capability_source="static",
    ),
}


# ---------------------------------------------------------------------------
# Multi-provider helper functions
# ---------------------------------------------------------------------------

def get_all_static_chat_models() -> dict[str, dict[str, ChatModelMetadata]]:
    """Return all static chat models grouped by provider."""
    return {
        "google": dict(GOOGLE_CHAT_MODELS),
        "openai": dict(OPENAI_CHAT_MODELS),
        "openrouter": dict(OPENROUTER_CHAT_MODELS),
        "nvidia": dict(NVIDIA_CHAT_MODELS),
        "ollama": dict(OLLAMA_KNOWN_MODELS),
        "zhipu": dict(ZHIPU_CHAT_MODELS),
    }


def is_known_model(provider: str, model_name: str) -> bool:
    """Check if a model exists in any static catalog."""
    all_models = get_all_static_chat_models()
    provider_models = all_models.get(provider, {})
    return model_name in provider_models


def resolve_openai_catalog_provider(
    *,
    active_provider: str | None,
    openai_base_url: str | None,
) -> str:
    normalized_base_url = (openai_base_url or "").strip().lower()
    if "openrouter.ai" in normalized_base_url:
        return "openrouter"
    if active_provider == "openrouter":
        return "openrouter"
    return "openai"


# ---------------------------------------------------------------------------
# ModelCatalogService - aggregates static + runtime-discovered models
# ---------------------------------------------------------------------------

class ModelCatalogService:
    """Aggregates static catalogs with runtime-discovered models."""

    _ollama_cache: list[ChatModelMetadata] = []
    _ollama_cache_ts: float = 0.0
    _ollama_cache_ttl: float = 60.0
    _provider_cache: dict[str, tuple[float, list[ChatModelMetadata]]] = {}
    _provider_cache_ttl: float = 120.0

    @classmethod
    async def _fetch_google_models(cls, api_key: str) -> list[ChatModelMetadata]:
        import httpx

        return await fetch_google_models_impl(
            api_key=api_key,
            httpx_module=httpx,
            normalize_google_model_name_fn=normalize_google_model_name,
            google_chat_models=GOOGLE_CHAT_MODELS,
            chat_model_metadata_cls=ChatModelMetadata,
            coerce_optional_int_fn=coerce_optional_int,
        )

    @classmethod
    async def discover_google_models(cls, api_key: str) -> list[ChatModelMetadata]:
        return await discover_google_models_impl(
            cls=cls,
            api_key=api_key,
            hash_secret_fn=hash_secret,
            run_cached_discovery_fn=run_cached_discovery,
            logger=_catalog_logger,
        )

    @classmethod
    async def _fetch_openai_compatible_models(
        cls,
        *,
        provider: str,
        base_url: str,
        api_key: str,
    ) -> list[ChatModelMetadata]:
        import httpx

        return await fetch_openai_compatible_models_impl(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            httpx_module=httpx,
            normalize_openai_compatible_base_url_fn=normalize_openai_compatible_base_url,
            default_base_url=OPENAI_DEFAULT_BASE_URL,
            get_all_static_chat_models_fn=get_all_static_chat_models,
            looks_like_chat_model_fn=looks_like_chat_model,
            extract_openai_compatible_limits_fn=extract_openai_compatible_limits,
            extract_openai_compatible_capabilities_fn=extract_openai_compatible_capabilities,
            chat_model_metadata_cls=ChatModelMetadata,
        )

    @classmethod
    async def discover_openai_compatible_models(
        cls,
        *,
        provider: str,
        base_url: str,
        api_key: str,
    ) -> list[ChatModelMetadata]:
        return await discover_openai_compatible_models_impl(
            cls=cls,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            normalize_openai_compatible_base_url_fn=normalize_openai_compatible_base_url,
            default_base_url=OPENAI_DEFAULT_BASE_URL,
            hash_secret_fn=hash_secret,
            run_cached_discovery_fn=run_cached_discovery,
            logger=_catalog_logger,
        )

    @classmethod
    async def _discover_ollama_models_result(
        cls,
        base_url: str,
    ) -> tuple[list[ChatModelMetadata], bool]:
        import httpx

        return await discover_ollama_models_result_impl(
            cls=cls,
            base_url=base_url,
            httpx_module=httpx,
            chat_model_metadata_cls=ChatModelMetadata,
            logger=_catalog_logger,
        )

    @classmethod
    async def discover_ollama_models(cls, base_url: str) -> list[ChatModelMetadata]:
        """Query Ollama /api/tags and return discovered models."""
        return await discover_ollama_models_impl(
            cls=cls,
            base_url=base_url,
        )

    @classmethod
    async def get_full_catalog(
        cls,
        ollama_base_url: str | None = None,
        *,
        active_provider: str | None = None,
        google_api_key: str | None = None,
        openai_base_url: str | None = None,
        openai_api_key: str | None = None,
        openrouter_base_url: str | None = None,
        openrouter_api_key: str | None = None,
        nvidia_base_url: str | None = None,
        nvidia_api_key: str | None = None,
        zhipu_base_url: str | None = None,
        zhipu_api_key: str | None = None,
    ) -> dict:
        """Return complete model catalog grouped by provider."""
        return await get_full_catalog_impl(
            cls=cls,
            ollama_base_url=ollama_base_url,
            active_provider=active_provider,
            google_api_key=google_api_key,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            openrouter_base_url=openrouter_base_url,
            openrouter_api_key=openrouter_api_key,
            nvidia_base_url=nvidia_base_url,
            nvidia_api_key=nvidia_api_key,
            zhipu_base_url=zhipu_base_url,
            zhipu_api_key=zhipu_api_key,
            get_all_static_chat_models_fn=get_all_static_chat_models,
            hash_secret_fn=hash_secret,
            run_cached_discovery_fn=run_cached_discovery,
            resolve_openai_catalog_provider_fn=resolve_openai_catalog_provider,
            normalize_openai_compatible_base_url_fn=normalize_openai_compatible_base_url,
            openai_default_base_url=OPENAI_DEFAULT_BASE_URL,
            openrouter_default_base_url=OPENROUTER_DEFAULT_BASE_URL,
            nvidia_default_base_url=NVIDIA_DEFAULT_BASE_URL,
            zhipu_default_base_url=ZHIPU_DEFAULT_BASE_URL,
            embedding_models=EMBEDDING_MODELS,
            logger=_catalog_logger,
        )

    @classmethod
    def reset_cache(cls) -> None:
        reset_cache_impl(cls=cls)
