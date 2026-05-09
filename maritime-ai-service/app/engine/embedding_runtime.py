"""Provider-agnostic embedding runtime for semantic memory and retrieval."""

from __future__ import annotations

import logging
import json
import re
import time
from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable
from urllib.parse import urlparse, urlunparse
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np

from app.core.config import settings
from app.engine.model_catalog import (
    OPENAI_DEFAULT_BASE_URL,
    OPENROUTER_DEFAULT_BASE_URL,
    embedding_model_supports_dimension_override,
    get_default_embedding_model_for_provider,
    get_embedding_dimensions,
    get_embedding_provider,
    provider_can_serve_embedding_model,
)
from app.engine.openai_compatible_credentials import (
    openrouter_credentials_available,
    resolve_openai_api_key,
    resolve_openai_base_url,
    resolve_openrouter_api_key,
    resolve_openrouter_base_url,
)

logger = logging.getLogger(__name__)
OLLAMA_EMBEDDING_PROBE_CACHE_TTL_SECONDS = 15.0
OLLAMA_EMBEDDING_PROBE_TIMEOUT_SECONDS = 0.5
_SECRET_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_-]+"), "sk-REDACTED"),
    (re.compile(r"(?i)(api key provided:\s*)([^\s,'\"}]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_ -]?key\s*[=:]\s*)([^\s,'\"}]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._-]+)"), r"\1[REDACTED]"),
)


@dataclass
class _OllamaEmbeddingProbeCacheEntry:
    created_at: float
    result: "OllamaEmbeddingProbeResult"


_ollama_embedding_probe_cache: dict[tuple[str, str], _OllamaEmbeddingProbeCacheEntry] = {}


def _sanitize_error_for_log(value: object) -> str:
    text = str(value)
    for pattern, replacement in _SECRET_REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass(frozen=True)
class OllamaEmbeddingProbeResult:
    """Inspection result for a local Ollama embedding candidate."""

    available: bool
    reason_code: str | None = None
    reason_label: str | None = None
    installed_models: tuple[str, ...] = ()
    error: str | None = None
    resolved_base_url: str | None = None


def _build_ollama_tags_url(base_url: str) -> str:
    normalized = (base_url or "").rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/api/tags"


def _normalize_ollama_model_variants(model_name: str) -> set[str]:
    normalized = (model_name or "").strip()
    if not normalized:
        return set()
    variants = {normalized}
    if ":" in normalized:
        base_name = normalized.split(":", 1)[0]
        variants.add(base_name)
        if normalized.endswith(":latest"):
            variants.add(base_name)
    else:
        variants.add(f"{normalized}:latest")
    return {item for item in variants if item}


def _build_ollama_base_url_candidates(base_url: str) -> list[str]:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return []

    candidates = [normalized]
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"host.docker.internal", "localhost", "127.0.0.1"}:
        for alternate_host in ("localhost", "127.0.0.1", "host.docker.internal"):
            if alternate_host == hostname:
                continue
            netloc = alternate_host
            if parsed.port:
                netloc = f"{alternate_host}:{parsed.port}"
            candidates.append(
                urlunparse(
                    (
                        parsed.scheme or "http",
                        netloc,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                ).rstrip("/")
            )

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _normalize_base_url(value: str | None) -> str | None:
    normalized = (value or "").strip().rstrip("/")
    return normalized or None


def reset_ollama_embedding_probe_cache() -> None:
    _ollama_embedding_probe_cache.clear()


def openrouter_embedding_credentials_available() -> bool:
    """Return True only when runtime config clearly intends OpenRouter embeddings."""
    return openrouter_credentials_available(settings)


def probe_ollama_embedding_model(base_url: str, model_name: str) -> OllamaEmbeddingProbeResult:
    """Inspect whether the configured Ollama embedding model is present locally."""
    cache_key = (_normalize_base_url(base_url) or "", (model_name or "").strip())
    cached = _ollama_embedding_probe_cache.get(cache_key)
    now = time.monotonic()
    if (
        cached is not None
        and now - cached.created_at < OLLAMA_EMBEDDING_PROBE_CACHE_TTL_SECONDS
    ):
        return cached.result

    if not base_url:
        result = OllamaEmbeddingProbeResult(
            available=False,
            reason_code="no_base_url",
            reason_label="Chua cau hinh Ollama base URL cho embeddings.",
        )
        _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
            created_at=now,
            result=result,
        )
        return result
    if not model_name:
        result = OllamaEmbeddingProbeResult(
            available=False,
            reason_code="model_missing",
            reason_label="Chua cau hinh model embedding cho Ollama.",
        )
        _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
            created_at=now,
            result=result,
        )
        return result

    payload = None
    installed: list[str] = []
    last_error: str | None = None
    resolved_base_url: str | None = None
    for candidate_base_url in _build_ollama_base_url_candidates(base_url):
        url = _build_ollama_tags_url(candidate_base_url)
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=OLLAMA_EMBEDDING_PROBE_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
            resolved_base_url = candidate_base_url
            break
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning(
                "Embedding provider probe failed: provider=ollama url=%s error=%s",
                url,
                _sanitize_error_for_log(exc),
            )
            last_error = str(exc)
            continue
        except ValueError as exc:
            logger.warning(
                "Embedding provider probe failed: provider=ollama url=%s invalid_payload=%s",
                url,
                _sanitize_error_for_log(exc),
            )
            result = OllamaEmbeddingProbeResult(
                available=False,
                reason_code="invalid_response",
                reason_label="Ollama tra ve payload probe khong hop le.",
                error=_sanitize_error_for_log(exc),
                resolved_base_url=candidate_base_url,
            )
            _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
                created_at=now,
                result=result,
            )
            return result

    if payload is None:
        result = OllamaEmbeddingProbeResult(
            available=False,
            reason_code="host_down",
            reason_label="Ollama local hien chua san sang.",
            error=last_error,
        )
        _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
            created_at=now,
            result=result,
        )
        return result

    models = payload.get("models", []) if isinstance(payload, dict) else []
    installed = sorted(
        {
            candidate
            for item in models
            if isinstance(item, dict)
            for candidate in (item.get("name"), item.get("model"))
            if candidate
        }
    )
    expected_variants = _normalize_ollama_model_variants(model_name)
    if expected_variants & set(installed):
        result = OllamaEmbeddingProbeResult(
            available=True,
            installed_models=tuple(installed),
            resolved_base_url=resolved_base_url,
        )
        _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
            created_at=now,
            result=result,
        )
        return result

    logger.warning(
        "Embedding provider skipped: provider=ollama model=%s not installed locally",
        model_name,
    )
    result = OllamaEmbeddingProbeResult(
        available=False,
        reason_code="model_missing",
        reason_label="Model embedding local chua duoc cai tren Ollama.",
        installed_models=tuple(installed),
        resolved_base_url=resolved_base_url,
    )
    _ollama_embedding_probe_cache[cache_key] = _OllamaEmbeddingProbeCacheEntry(
        created_at=now,
        result=result,
    )
    return result


def _ollama_model_is_available(base_url: str, model_name: str) -> bool:
    """Return True when the configured Ollama model is present locally."""
    return probe_ollama_embedding_model(base_url, model_name).available


@runtime_checkable
class EmbeddingBackendProtocol(Protocol):
    """Common embedding contract shared across provider adapters."""

    provider: str
    model_name: str

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed one or more documents."""

    def embed_query(self, text: str) -> List[float]:
        """Embed a search query."""

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """Async embed for multiple documents."""

    async def aembed_query(self, text: str) -> List[float]:
        """Async embed for a single query."""

    @property
    def dimensions(self) -> int:
        """Resolved output dimensions."""


class OpenAICompatibleEmbeddings:
    """Embedding adapter for OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        model_name: str,
        dimensions: int,
        base_url: str | None = None,
    ):
        self.provider = provider
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url or OPENAI_DEFAULT_BASE_URL
        self._dimensions = dimensions
        self._sync_client = None
        self._async_client = None
        self._supports_dimension_override = embedding_model_supports_dimension_override(model_name)

    @property
    def client(self):
        if self._sync_client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError("openai package is required for OpenAI-compatible embeddings") from exc
            self._sync_client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._sync_client

    @property
    def async_client(self):
        if self._async_client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("openai package is required for OpenAI-compatible embeddings") from exc
            self._async_client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._async_client

    @staticmethod
    def _normalize(vector: List[float]) -> List[float]:
        arr = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            return (arr / norm).tolist()
        return vector

    def _request_dimensions(self) -> int | None:
        if self._supports_dimension_override:
            return self._dimensions
        return None

    def _coerce_embedding(self, vector: List[float]) -> List[float]:
        normalized = self._normalize(vector)
        if len(normalized) != self._dimensions:
            raise ValueError(
                f"Embedding dimension mismatch for {self.provider}:{self.model_name}: "
                f"expected {self._dimensions}, got {len(normalized)}"
            )
        return normalized

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        kwargs = {
            "model": self.model_name,
            "input": texts,
        }
        request_dimensions = self._request_dimensions()
        if request_dimensions is not None:
            kwargs["dimensions"] = request_dimensions
        response = self.client.embeddings.create(**kwargs)
        return [self._coerce_embedding(item.embedding) for item in response.data]

    def embed_query(self, text: str) -> List[float]:
        if not text:
            return []
        kwargs = {
            "model": self.model_name,
            "input": text,
        }
        request_dimensions = self._request_dimensions()
        if request_dimensions is not None:
            kwargs["dimensions"] = request_dimensions
        response = self.client.embeddings.create(**kwargs)
        return self._coerce_embedding(response.data[0].embedding)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        kwargs = {
            "model": self.model_name,
            "input": texts,
        }
        request_dimensions = self._request_dimensions()
        if request_dimensions is not None:
            kwargs["dimensions"] = request_dimensions
        response = await self.async_client.embeddings.create(**kwargs)
        return [self._coerce_embedding(item.embedding) for item in response.data]

    async def aembed_query(self, text: str) -> List[float]:
        if not text:
            return []
        kwargs = {
            "model": self.model_name,
            "input": text,
        }
        request_dimensions = self._request_dimensions()
        if request_dimensions is not None:
            kwargs["dimensions"] = request_dimensions
        response = await self.async_client.embeddings.create(**kwargs)
        return self._coerce_embedding(response.data[0].embedding)

    @property
    def dimensions(self) -> int:
        return self._dimensions


def _resolve_provider_order() -> list[str]:
    configured_provider = (getattr(settings, "embedding_provider", "") or "").strip().lower()
    configured_model = getattr(settings, "embedding_model", None)
    inferred_provider = get_embedding_provider(configured_model)

    if configured_provider and configured_provider != "auto":
        return [configured_provider]

    ordered: list[str] = []
    for provider in [inferred_provider, *getattr(settings, "embedding_failover_chain", [])]:
        normalized = (provider or "").strip().lower()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered or ["google"]


def _resolve_model_for_provider(provider: str) -> str | None:
    configured_model = getattr(settings, "embedding_model", None)
    if configured_model:
        if provider_can_serve_embedding_model(provider, configured_model):
            return configured_model
        return None
    return get_default_embedding_model_for_provider(provider)


def _resolve_dimensions_for_model(model_name: str) -> int:
    configured_dimensions = getattr(settings, "embedding_dimensions", None)
    if configured_dimensions:
        return configured_dimensions
    return get_embedding_dimensions(model_name)


def resolve_embedding_provider_order() -> list[str]:
    """Public wrapper for the current embedding runtime provider order."""
    return list(_resolve_provider_order())


def resolve_embedding_model_for_provider(provider: str) -> str | None:
    """Public wrapper for provider-specific embedding model resolution."""
    return _resolve_model_for_provider(provider)


def resolve_embedding_dimensions_for_model(model_name: str) -> int:
    """Public wrapper for provider-aware embedding dimension resolution."""
    return _resolve_dimensions_for_model(model_name)


def build_embedding_backend_for_provider_model(
    provider: str,
    model_name: str,
    *,
    dimensions: int | None = None,
) -> EmbeddingBackendProtocol | None:
    """Build a provider-specific embedding backend without mutating runtime policy."""

    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model_name or "").strip()
    if not normalized_provider or not normalized_model:
        return None
    if not provider_can_serve_embedding_model(normalized_provider, normalized_model):
        logger.warning(
            "Embedding provider skipped: provider=%s cannot serve requested embedding space model=%s",
            normalized_provider,
            normalized_model,
        )
        return None
    resolved_dimensions = dimensions or _resolve_dimensions_for_model(normalized_model)

    if normalized_provider == "google":
        api_key = getattr(settings, "google_api_key", None)
        if not api_key:
            return None
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings

        return GeminiOptimizedEmbeddings(
            api_key=api_key,
            model_name=normalized_model,
            dimensions=resolved_dimensions,
        )

    if normalized_provider == "openai":
        api_key = resolve_openai_api_key(settings)
        if not api_key:
            return None
        base_url = resolve_openai_base_url(settings) or OPENAI_DEFAULT_BASE_URL
        return OpenAICompatibleEmbeddings(
            provider="openai",
            api_key=api_key,
            base_url=base_url,
            model_name=normalized_model,
            dimensions=resolved_dimensions,
        )

    if normalized_provider == "openrouter":
        if not openrouter_embedding_credentials_available():
            return None
        return OpenAICompatibleEmbeddings(
            provider="openrouter",
            api_key=resolve_openrouter_api_key(settings),
            base_url=resolve_openrouter_base_url(settings) or OPENROUTER_DEFAULT_BASE_URL,
            model_name=normalized_model,
            dimensions=resolved_dimensions,
        )

    if normalized_provider == "ollama":
        base_url = getattr(settings, "ollama_base_url", None)
        if not base_url:
            return None
        probe = probe_ollama_embedding_model(base_url, normalized_model)
        if not probe.available:
            return None
        normalized_base_url = (probe.resolved_base_url or base_url).rstrip("/")
        if not normalized_base_url.endswith("/v1"):
            normalized_base_url = normalized_base_url + "/v1"
        return OpenAICompatibleEmbeddings(
            provider="ollama",
            api_key=getattr(settings, "ollama_api_key", None) or "ollama",
            base_url=normalized_base_url,
            model_name=normalized_model,
            dimensions=resolved_dimensions,
        )

    if normalized_provider == "zhipu":
        api_key = getattr(settings, "zhipu_api_key", None)
        if not api_key:
            return None
        logger.warning(
            "Embedding provider skipped: provider=zhipu is not enabled until an explicit verified embedding model is cataloged"
        )
        return None

    return None


class SemanticEmbeddingBackend:
    """Single authority for semantic-memory embeddings across providers."""

    def __init__(self):
        self._provider_order = _resolve_provider_order()
        self._backends: dict[str, EmbeddingBackendProtocol] = {}
        self._active_provider: str | None = None
        self._initialize_backends()

    def _initialize_backends(self) -> None:
        for provider in self._provider_order:
            backend = self._build_backend(provider)
            if backend is not None:
                self._backends[provider] = backend
                if self._active_provider is None:
                    self._active_provider = provider
        if self._active_provider:
            logger.info(
                "Semantic embedding backend initialized: provider=%s model=%s dims=%s",
                self._active_provider,
                self._backends[self._active_provider].model_name,
                self._backends[self._active_provider].dimensions,
            )
        else:
            logger.warning("Semantic embedding backend unavailable for providers=%s", self._provider_order)

    def _build_backend(self, provider: str) -> EmbeddingBackendProtocol | None:
        model_name = _resolve_model_for_provider(provider)
        if not model_name:
            configured_model = getattr(settings, "embedding_model", None)
            if configured_model and not provider_can_serve_embedding_model(provider, configured_model):
                logger.warning(
                    "Embedding provider skipped: provider=%s cannot serve current embedding space model=%s",
                    provider,
                    configured_model,
                )
                return None
            logger.warning(
                "Embedding provider skipped: provider=%s has no verified embedding model contract",
                provider,
            )
            return None
        return build_embedding_backend_for_provider_model(
            provider,
            model_name,
            dimensions=_resolve_dimensions_for_model(model_name),
        )

    def _ordered_backends(self) -> list[EmbeddingBackendProtocol]:
        if not self._backends:
            return []
        providers = []
        if self._active_provider and self._active_provider in self._backends:
            providers.append(self._active_provider)
        providers.extend(
            provider
            for provider in self._provider_order
            if provider in self._backends and provider not in providers
        )
        return [self._backends[provider] for provider in providers]

    def _promote_backend(self, provider: str) -> None:
        if provider != self._active_provider:
            logger.info("Semantic embedding failover promoted provider=%s", provider)
            self._active_provider = provider

    def is_available(self) -> bool:
        return bool(self._backends)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        for backend in self._ordered_backends():
            try:
                result = backend.embed_documents(texts)
                self._promote_backend(backend.provider)
                return result
            except Exception as exc:
                logger.warning(
                    "Semantic embedding provider failed: provider=%s model=%s error=%s",
                    backend.provider,
                    backend.model_name,
                    _sanitize_error_for_log(exc),
                )
        return [[] for _ in texts]

    def embed_query(self, text: str) -> List[float]:
        for backend in self._ordered_backends():
            try:
                result = backend.embed_query(text)
                self._promote_backend(backend.provider)
                return result
            except Exception as exc:
                logger.warning(
                    "Semantic embedding provider failed: provider=%s model=%s error=%s",
                    backend.provider,
                    backend.model_name,
                    _sanitize_error_for_log(exc),
                )
        return []

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        for backend in self._ordered_backends():
            try:
                result = await backend.aembed_documents(texts)
                self._promote_backend(backend.provider)
                return result
            except Exception as exc:
                logger.warning(
                    "Semantic embedding provider failed: provider=%s model=%s error=%s",
                    backend.provider,
                    backend.model_name,
                    _sanitize_error_for_log(exc),
                )
        return [[] for _ in texts]

    async def aembed_query(self, text: str) -> List[float]:
        for backend in self._ordered_backends():
            try:
                result = await backend.aembed_query(text)
                self._promote_backend(backend.provider)
                return result
            except Exception as exc:
                logger.warning(
                    "Semantic embedding provider failed: provider=%s model=%s error=%s",
                    backend.provider,
                    backend.model_name,
                    _sanitize_error_for_log(exc),
                )
        return []

    @property
    def dimensions(self) -> int:
        active = self.active_backend
        if active is None:
            return _resolve_dimensions_for_model(_resolve_model_for_provider("google"))
        return active.dimensions

    @property
    def active_backend(self) -> EmbeddingBackendProtocol | None:
        if self._active_provider and self._active_provider in self._backends:
            return self._backends[self._active_provider]
        return None

    @property
    def provider(self) -> str | None:
        backend = self.active_backend
        return backend.provider if backend else None

    @property
    def model_name(self) -> str | None:
        backend = self.active_backend
        return backend.model_name if backend else None


_semantic_embedding_backend: SemanticEmbeddingBackend | None = None


def get_semantic_embedding_backend() -> SemanticEmbeddingBackend:
    """Return the singleton semantic embedding backend."""
    global _semantic_embedding_backend
    if _semantic_embedding_backend is None:
        _semantic_embedding_backend = SemanticEmbeddingBackend()
    return _semantic_embedding_backend


def peek_semantic_embedding_backend() -> SemanticEmbeddingBackend | None:
    """Return the cached embedding backend without initializing providers."""
    return _semantic_embedding_backend


def reset_semantic_embedding_backend() -> None:
    """Reset singleton backend for tests and runtime reconfiguration."""
    global _semantic_embedding_backend
    _semantic_embedding_backend = None
    reset_ollama_embedding_probe_cache()


def get_embedding_backend() -> SemanticEmbeddingBackend:
    """Return the shared embedding backend authority for retrieval/storage paths."""
    return get_semantic_embedding_backend()


def reset_embedding_backend() -> None:
    """Reset the shared embedding backend authority."""
    reset_semantic_embedding_backend()
