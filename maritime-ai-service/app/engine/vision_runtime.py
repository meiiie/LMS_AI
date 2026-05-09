"""Provider-agnostic vision runtime for image understanding workflows.

This module becomes the single authority for image understanding across:
- query-time Visual RAG enrichment
- document vision extraction during ingestion
- visual memory captioning

It intentionally mirrors the architecture direction of embedding_runtime:
- provider-neutral contract
- capability-aware routing
- graceful failover/degrade behavior
- honest availability gating
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from app.core.config import settings
from app.engine.openai_compatible_credentials import (
    openrouter_credentials_available,
    resolve_nvidia_api_key,
    resolve_nvidia_base_url,
    resolve_nvidia_vision_model,
    resolve_openai_api_key,
    resolve_openai_base_url,
    resolve_openai_model,
    resolve_openai_model_advanced,
    resolve_openrouter_api_key,
    resolve_openrouter_base_url,
    resolve_openrouter_model,
    resolve_openrouter_model_advanced,
)
from app.engine.llm_failover_runtime import classify_failover_reason_impl

logger = logging.getLogger(__name__)


class VisionCapability(str, Enum):
    OCR_EXTRACT = "ocr_extract"
    VISUAL_DESCRIBE = "visual_describe"
    GROUNDED_VISUAL_ANSWER = "grounded_visual_answer"


_CAPABILITY_PROVIDER_FIELDS: dict[VisionCapability, str] = {
    VisionCapability.VISUAL_DESCRIBE: "vision_describe_provider",
    VisionCapability.OCR_EXTRACT: "vision_ocr_provider",
    VisionCapability.GROUNDED_VISUAL_ANSWER: "vision_grounded_provider",
}

_CAPABILITY_MODEL_FIELDS: dict[VisionCapability, str] = {
    VisionCapability.VISUAL_DESCRIBE: "vision_describe_model",
    VisionCapability.OCR_EXTRACT: "vision_ocr_model",
    VisionCapability.GROUNDED_VISUAL_ANSWER: "vision_grounded_model",
}


@dataclass(frozen=True)
class VisionProviderStatus:
    provider: str
    available: bool
    model_name: str | None = None
    lane_fit: str | None = None
    lane_fit_label: str | None = None
    reason_code: str | None = None
    reason_label: str | None = None
    resolved_base_url: str | None = None


@dataclass
class VisionResult:
    text: str = ""
    success: bool = False
    provider: str | None = None
    model_name: str | None = None
    capability: VisionCapability = VisionCapability.VISUAL_DESCRIBE
    error: str | None = None
    reason_code: str | None = None
    reason_label: str | None = None
    resolved_base_url: str | None = None
    total_time_ms: float = 0.0
    attempted_providers: list[dict[str, Any]] = field(default_factory=list)


VISION_IMAGE_FETCH_TIMEOUT_SECONDS = 10.0
VISION_RUNTIME_DEFAULT_TIMEOUT_SECONDS = 30.0
OLLAMA_VISION_PROBE_CACHE_TTL_SECONDS = 15.0
VISION_RUNTIME_DEMOTION_CACHE_TTL_SECONDS = 15.0
VISION_PROVIDER_RECOVERY_COOLDOWN_SECONDS = 120.0
VISION_OCR_SPECIALIST_RECOVERY_COOLDOWN_SECONDS = 300.0

_SECRET_REDACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("sk-", "sk-REDACTED"),
    ("Bearer ", "Bearer [REDACTED]"),
)


@dataclass(frozen=True)
class _RecentVisionFailure:
    failed_at: float
    reason_code: str | None = None


_recent_vision_failures: dict[tuple[str, str], _RecentVisionFailure] = {}
_vision_audit_demotion_cache: tuple[float, dict[tuple[str, str], str | None]] | None = None


def _sanitize_error_for_log(value: object) -> str:
    text = str(value or "")
    for marker, replacement in _SECRET_REDACTION_PATTERNS:
        if marker in text:
            head, _, _ = text.partition(marker)
            text = f"{head}{replacement}"
    return text


def _compact_repeated_vision_text(text: str) -> str:
    """Trim exact repeated sentence/line loops from provider vision output."""
    normalized = re.sub(r"[ \t]+", " ", str(text or "").strip())
    normalized = re.sub(
        r"^\s*(?:\*\*)?\s*(?:answer|final answer|response)\s*:\s*(?:\*\*)?\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()
    normalized = re.sub(r"(?m)^\s*[-*]\s+", "", normalized).strip()
    if not normalized:
        return ""
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?<=[.!?。！？])\s+|\n+", normalized)
        if chunk.strip()
    ]
    if len(chunks) <= 2:
        return " ".join(chunks).strip()

    seen: set[str] = set()
    kept: list[str] = []
    for chunk in chunks:
        key = re.sub(r"\s+", " ", chunk).strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(chunk)
    return " ".join(kept).strip()


def _normalize_provider(provider: str | None) -> str | None:
    normalized = str(provider or "").strip().lower()
    return normalized or None


def _normalize_base_url(value: str | None) -> str | None:
    normalized = (value or "").strip().rstrip("/")
    return normalized or None


def _parse_iso8601(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _capability_provider_override(capability: VisionCapability) -> str | None:
    field_name = _CAPABILITY_PROVIDER_FIELDS.get(capability)
    if not field_name:
        return None
    value = _normalize_provider(getattr(settings, field_name, None))
    if not value or value == "auto":
        return None
    return value


def _capability_model_override(capability: VisionCapability) -> str | None:
    field_name = _CAPABILITY_MODEL_FIELDS.get(capability)
    if not field_name:
        return None
    value = getattr(settings, field_name, None)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_ollama_model_variants(model_name: str) -> set[str]:
    normalized = (model_name or "").strip()
    if not normalized:
        return set()
    variants = {normalized}
    if ":" in normalized:
        variants.add(normalized.split(":", 1)[0])
    else:
        variants.add(f"{normalized}:latest")
    return {item for item in variants if item}


def _build_ollama_base_url_candidates(base_url: str | None) -> list[str]:
    normalized = _normalize_base_url(base_url)
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


def _looks_like_openai_vision_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return normalized.startswith(("gpt-4.1", "gpt-4o", "gpt-5", "o4"))


def _looks_like_openrouter_vision_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    keywords = (
        "gpt-4.1",
        "gpt-4o",
        "gpt-5",
        "o4",
        "qwen2-vl",
        "qwen2.5-vl",
        "qwen2.5vl",
        "qwen25vl",
        "qwen-vl",
        "minicpm-v",
        "minicpmv",
        "llava",
        "pixtral",
        "glm-4.6v",
        "glm-4.5v",
        "glm-5v",
        "vision",
        "vl",
    )
    return any(keyword in normalized for keyword in keywords)


def _looks_like_nvidia_vision_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    # Keep this conservative: these markers are NVIDIA catalog multimodal IDs
    # that are documented and/or directly probed through the NVIDIA endpoint.
    keywords = (
        "vision",
        "vl",
        "neva",
        "paligemma",
        "gemma-3-",
        "gemma-3n-",
        "gemma-4-",
        "nemotron-nano-12b-v2-vl",
        "llama-3.1-nemotron-nano-vl",
        "llama-3.2-11b-vision",
        "llama-3.2-90b-vision",
        "llama-4-maverick",
        "phi-3-vision",
        "phi-3.5-vision",
        "phi-4-multimodal",
        "ministral-14b-instruct",
        "mistral-large-3",
        "mistral-medium-3",
        "mistral-small-4",
        "kimi-k2.6",
        "qwen3.5-",
    )
    return any(keyword in normalized for keyword in keywords)


def _looks_like_ollama_vision_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    keywords = (
        "gemma3",
        "llava",
        "bakllava",
        "minicpm-v",
        "minicpmv",
        "qwen2-vl",
        "qwen2.5-vl",
        "qwen2.5vl",
        "qwen25vl",
        "moondream",
        "vision",
        "vl",
    )
    return any(keyword in normalized for keyword in keywords)


def _extract_ollama_installed_models(payload: object) -> set[str]:
    installed: set[str] = set()
    models = payload.get("models", []) if isinstance(payload, dict) else []
    for item in models:
        if not isinstance(item, dict):
            continue
        for candidate in (item.get("name"), item.get("model")):
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            installed.add(candidate.strip())
    return installed


def _select_installed_ollama_vision_model(
    installed: set[str],
    capability: VisionCapability | None,
) -> str | None:
    if not installed:
        return None

    if capability == VisionCapability.GROUNDED_VISUAL_ANSWER:
        ordered_preferences = (
            "qwen2.5vl:72b",
            "qwen2.5-vl:72b",
            "qwen25vl:72b",
            "qwen2.5vl:32b",
            "qwen2.5-vl:32b",
            "qwen25vl:32b",
            "qwen2.5vl:7b",
            "qwen2.5-vl:7b",
            "qwen25vl:7b",
            "minicpm-v",
            "gemma3:27b",
            "gemma3:12b",
            "gemma3:4b",
            "qwen2.5vl:3b",
            "qwen2.5-vl:3b",
            "qwen25vl:3b",
            "llava",
        )
    else:
        ordered_preferences = (
            "qwen2.5vl:7b",
            "qwen2.5-vl:7b",
            "qwen25vl:7b",
            "minicpm-v",
            "gemma3:4b",
            "gemma3:12b",
            "gemma3:27b",
            "qwen2.5vl:3b",
            "qwen2.5-vl:3b",
            "qwen25vl:3b",
            "llava",
            "moondream",
        )

    lowered_installed = {item.lower(): item for item in installed}
    for preferred in ordered_preferences:
        preferred_exact = preferred.lower()
        if preferred_exact in lowered_installed:
            return lowered_installed[preferred_exact]
        preferred_variants = [item.lower() for item in _normalize_ollama_model_variants(preferred)]
        for variant in preferred_variants:
            if variant in lowered_installed:
                return lowered_installed[variant]
        if ":" not in preferred:
            preferred_stem = preferred.split(":", 1)[0]
            for lowered, original in lowered_installed.items():
                if lowered.startswith(f"{preferred_stem}:"):
                    return original
            for lowered, original in lowered_installed.items():
                if preferred_stem in lowered:
                    return original

    for original in sorted(installed):
        if _looks_like_ollama_vision_model(original):
            return original
    return None


def _looks_like_zhipu_vision_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return False
    return normalized.startswith(("glm-5v", "glm-4.6v", "glm-4.5v"))


def _looks_like_zhipu_ocr_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    return normalized == "glm-ocr"


def _infer_provider_from_capability_model(
    capability: VisionCapability,
    model_name: str | None,
) -> str | None:
    if capability == VisionCapability.OCR_EXTRACT and _looks_like_zhipu_ocr_model(model_name):
        return "zhipu"
    return None


def _provider_base_default_model(provider: str, capability: VisionCapability) -> str | None:
    if provider == "google":
        if capability == VisionCapability.OCR_EXTRACT:
            return getattr(settings, "google_model_advanced", None) or settings.google_model
        return settings.google_model
    if provider == "openai":
        if capability == VisionCapability.OCR_EXTRACT:
            return resolve_openai_model_advanced(settings)
        return resolve_openai_model(settings)
    if provider == "openrouter":
        if capability == VisionCapability.OCR_EXTRACT:
            return resolve_openrouter_model_advanced(settings)
        return resolve_openrouter_model(settings)
    if provider == "nvidia":
        return resolve_nvidia_vision_model(settings)
    if provider == "ollama":
        return settings.ollama_model
    if provider == "zhipu":
        if capability == VisionCapability.OCR_EXTRACT:
            return "glm-ocr"
        return getattr(settings, "zhipu_model", None)
    return None


def _provider_default_model(provider: str, capability: VisionCapability) -> str | None:
    capability_provider = _capability_provider_override(capability)
    capability_model = _capability_model_override(capability)
    inferred_provider = _infer_provider_from_capability_model(capability, capability_model)
    if capability_model and provider in {capability_provider, inferred_provider}:
        return capability_model
    if capability_provider and provider == capability_provider:
        return _provider_base_default_model(provider, capability)
    return _provider_base_default_model(provider, capability)


def _provider_lane_fit(
    provider: str,
    capability: VisionCapability,
    model_name: str | None = None,
) -> tuple[str | None, str | None]:
    normalized_provider = _normalize_provider(provider) or provider
    model = (model_name or "").strip() or _provider_default_model(normalized_provider, capability)

    if capability == VisionCapability.OCR_EXTRACT:
        if normalized_provider == "zhipu" and _looks_like_zhipu_ocr_model(model):
            return "specialist", "OCR specialist"
        if normalized_provider in {"google", "openai", "openrouter", "nvidia", "ollama", "zhipu"} and model:
            return "fallback", "OCR fallback"
        return None, None

    if normalized_provider in {"google", "openai", "openrouter", "nvidia", "ollama", "zhipu"} and model:
        return "general", "General vision"
    return None, None


def _lane_fit_priority(provider: str, capability: VisionCapability) -> int:
    lane_fit, _ = _provider_lane_fit(provider, capability)
    if capability == VisionCapability.OCR_EXTRACT:
        ranking = {
            "specialist": 0,
            "general": 1,
            "fallback": 2,
            None: 9,
        }
        return ranking.get(lane_fit, 9)
    ranking = {
        "general": 0,
        "specialist": 0,
        "fallback": 1,
        None: 9,
    }
    return ranking.get(lane_fit, 9)


def _vision_provider_status(
    *,
    provider: str,
    capability: VisionCapability,
    available: bool,
    model_name: str | None = None,
    reason_code: str | None = None,
    reason_label: str | None = None,
    resolved_base_url: str | None = None,
) -> VisionProviderStatus:
    lane_fit, lane_fit_label = _provider_lane_fit(provider, capability, model_name)
    return VisionProviderStatus(
        provider=provider,
        available=available,
        model_name=model_name,
        lane_fit=lane_fit,
        lane_fit_label=lane_fit_label,
        reason_code=reason_code,
        reason_label=reason_label,
        resolved_base_url=resolved_base_url,
    )


_ollama_probe_cache: dict[tuple[str, str], tuple[float, VisionProviderStatus]] = {}
OLLAMA_VISION_TAGS_PROBE_TIMEOUT_SECONDS = 0.5


def reset_vision_runtime_caches() -> None:
    _ollama_probe_cache.clear()
    _recent_vision_failures.clear()
    global _vision_audit_demotion_cache
    _vision_audit_demotion_cache = None


def _provider_recovery_cooldown_seconds(
    provider: str,
    capability: VisionCapability,
) -> float:
    if provider == "zhipu" and capability == VisionCapability.OCR_EXTRACT:
        return VISION_OCR_SPECIALIST_RECOVERY_COOLDOWN_SECONDS
    return VISION_PROVIDER_RECOVERY_COOLDOWN_SECONDS


def _record_recent_vision_failure(
    provider: str,
    capability: VisionCapability,
    *,
    reason_code: str | None,
) -> None:
    normalized_provider = _normalize_provider(provider)
    if not normalized_provider:
        return
    _recent_vision_failures[(normalized_provider, capability.value)] = _RecentVisionFailure(
        failed_at=time.monotonic(),
        reason_code=reason_code,
    )


def _record_recent_vision_success(provider: str, capability: VisionCapability) -> None:
    normalized_provider = _normalize_provider(provider)
    if not normalized_provider:
        return
    _recent_vision_failures.pop((normalized_provider, capability.value), None)


def _recent_runtime_demoted_providers(capability: VisionCapability) -> set[str]:
    now = time.monotonic()
    demoted: set[str] = set()
    expired: list[tuple[str, str]] = []
    for key, failure in _recent_vision_failures.items():
        provider, capability_name = key
        if capability_name != capability.value:
            continue
        cooldown = _provider_recovery_cooldown_seconds(provider, capability)
        if now - failure.failed_at < cooldown:
            demoted.add(provider)
        else:
            expired.append(key)
    for key in expired:
        _recent_vision_failures.pop(key, None)
    return demoted


def _load_recent_audit_demoted_providers(capability: VisionCapability) -> set[str]:
    global _vision_audit_demotion_cache

    if capability != VisionCapability.OCR_EXTRACT:
        return set()

    now = time.monotonic()
    if (
        _vision_audit_demotion_cache is not None
        and now - _vision_audit_demotion_cache[0] < VISION_RUNTIME_DEMOTION_CACHE_TTL_SECONDS
    ):
        cached = _vision_audit_demotion_cache[1]
    else:
        cached: dict[tuple[str, str], str | None] = {}
        try:
            from app.services.vision_runtime_audit_service import get_persisted_vision_runtime_audit

            record = get_persisted_vision_runtime_audit()
            payload = record.payload if record is not None else {}
            providers = payload.get("providers", {}) if isinstance(payload, dict) else {}
            for provider_name, provider_payload in providers.items():
                if not isinstance(provider_payload, dict):
                    continue
                capabilities = provider_payload.get("capabilities", {})
                capability_payload = (
                    capabilities.get(capability.value)
                    if isinstance(capabilities, dict)
                    else None
                )
                if not isinstance(capability_payload, dict):
                    continue
                error = str(capability_payload.get("last_probe_error") or "").strip()
                attempt_at = _parse_iso8601(capability_payload.get("last_probe_attempt_at"))
                success_at = _parse_iso8601(capability_payload.get("last_probe_success_at"))
                runtime_success_at = _parse_iso8601(
                    capability_payload.get("last_runtime_success_at")
                )
                if not error or attempt_at is None:
                    continue
                if success_at is not None and success_at >= attempt_at:
                    continue
                if runtime_success_at is not None and runtime_success_at >= attempt_at:
                    continue
                age_seconds = (datetime.now(timezone.utc) - attempt_at).total_seconds()
                cooldown = _provider_recovery_cooldown_seconds(str(provider_name), capability)
                if age_seconds < cooldown:
                    cached[(_normalize_provider(str(provider_name)) or str(provider_name), capability.value)] = error
        except Exception as exc:
            logger.debug(
                "[VisionRuntime] Could not load audit demotion hints: %s",
                _sanitize_error_for_log(exc),
            )
            cached = {}
        _vision_audit_demotion_cache = (now, cached)

    return {
        provider
        for (provider, capability_name), _error in cached.items()
        if capability_name == capability.value and provider
    }


def _temporarily_demoted_providers(capability: VisionCapability) -> set[str]:
    return _recent_runtime_demoted_providers(capability) | _load_recent_audit_demoted_providers(capability)


def _record_vision_runtime_observation(
    *,
    provider: str,
    capability: VisionCapability,
    success: bool,
    model_name: str | None,
    note: str | None = None,
    error: str | None = None,
) -> None:
    try:
        from app.services.vision_runtime_audit_service import record_vision_runtime_observation

        record_vision_runtime_observation(
            provider=provider,
            capability=capability,
            success=success,
            model_name=model_name,
            note=note,
            error=error,
            source="runtime_call",
        )
    except Exception as exc:
        logger.debug(
            "[VisionRuntime] Could not persist runtime observation for provider=%s capability=%s: %s",
            provider,
            capability.value,
            _sanitize_error_for_log(exc),
        )


def _probe_ollama_vision_status(
    model_name: str | None,
    *,
    capability: VisionCapability | None = None,
    allow_autoselect: bool = False,
) -> VisionProviderStatus:
    base_url = settings.ollama_base_url
    model = (model_name or "").strip()
    cache_key = (
        _normalize_base_url(base_url) or "",
        model or f"auto:{(capability.value if capability else 'vision')}",
    )
    now = time.monotonic()
    cached = _ollama_probe_cache.get(cache_key)
    if cached is not None and now - cached[0] < OLLAMA_VISION_PROBE_CACHE_TTL_SECONDS:
        return cached[1]

    if not base_url:
        status = _vision_provider_status(
            provider="ollama",
            capability=capability or VisionCapability.VISUAL_DESCRIBE,
            available=False,
            model_name=model or None,
            reason_code="no_base_url",
            reason_label="Chua cau hinh Ollama base URL cho vision runtime.",
        )
        _ollama_probe_cache[cache_key] = (now, status)
        return status

    payload = None
    installed: set[str] = set()
    last_error: str | None = None
    resolved_base_url: str | None = None
    for candidate_base_url in _build_ollama_base_url_candidates(base_url):
        url = f"{candidate_base_url}/api/tags"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=OLLAMA_VISION_TAGS_PROBE_TIMEOUT_SECONDS) as response:
                import json

                payload = json.load(response)
            resolved_base_url = candidate_base_url
            break
        except (URLError, TimeoutError, OSError) as exc:
            last_error = _sanitize_error_for_log(exc)
            continue
        except ValueError as exc:
            status = _vision_provider_status(
                provider="ollama",
                capability=capability or VisionCapability.VISUAL_DESCRIBE,
                available=False,
                model_name=model,
                reason_code="invalid_response",
                reason_label="Ollama tra ve payload probe khong hop le.",
                resolved_base_url=candidate_base_url,
            )
            _ollama_probe_cache[cache_key] = (now, status)
            return status

    if payload is None:
        status = _vision_provider_status(
            provider="ollama",
            capability=capability or VisionCapability.VISUAL_DESCRIBE,
            available=False,
            model_name=model,
            reason_code="host_down",
            reason_label="Ollama local hien chua san sang cho vision runtime.",
            resolved_base_url=None,
        )
        _ollama_probe_cache[cache_key] = (now, status)
        return status

    installed = _extract_ollama_installed_models(payload)

    selected_model = model
    if allow_autoselect and (not selected_model or not _looks_like_ollama_vision_model(selected_model)):
        autoselected = _select_installed_ollama_vision_model(installed, capability)
        if autoselected:
            selected_model = autoselected

    if not selected_model:
        status = _vision_provider_status(
            provider="ollama",
            capability=capability or VisionCapability.VISUAL_DESCRIBE,
            available=False,
            reason_code="model_missing",
            reason_label="Chua cau hinh model vision cho Ollama.",
            resolved_base_url=resolved_base_url,
        )
        _ollama_probe_cache[cache_key] = (now, status)
        return status

    if not _looks_like_ollama_vision_model(selected_model):
        status = _vision_provider_status(
            provider="ollama",
            capability=capability or VisionCapability.VISUAL_DESCRIBE,
            available=False,
            model_name=selected_model,
            reason_code="model_unverified",
            reason_label="Model Ollama hiện tại không có dấu hiệu là model vision.",
            resolved_base_url=resolved_base_url,
        )
        _ollama_probe_cache[cache_key] = (now, status)
        return status

    expected_variants = _normalize_ollama_model_variants(selected_model)
    if expected_variants & installed:
        status = _vision_provider_status(
            provider="ollama",
            capability=capability or VisionCapability.VISUAL_DESCRIBE,
            available=True,
            model_name=selected_model,
            resolved_base_url=resolved_base_url,
        )
        _ollama_probe_cache[cache_key] = (now, status)
        return status

    status = _vision_provider_status(
        provider="ollama",
        capability=capability or VisionCapability.VISUAL_DESCRIBE,
        available=False,
        model_name=selected_model,
        reason_code="model_missing",
        reason_label="Model vision local chua duoc cai tren Ollama.",
        resolved_base_url=resolved_base_url,
    )
    _ollama_probe_cache[cache_key] = (now, status)
    return status


def _provider_status(
    provider: str,
    capability: VisionCapability,
    model_name: str | None = None,
) -> VisionProviderStatus:
    model = model_name or _provider_default_model(provider, capability)

    if provider == "google":
        if not settings.google_api_key:
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="missing_api_key",
                reason_label="Google API key cho vision runtime dang thieu.",
            )
        return _vision_provider_status(
            provider=provider,
            capability=capability,
            available=True,
            model_name=model,
        )

    if provider == "openai":
        if not resolve_openai_api_key(settings):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="missing_api_key",
                reason_label="OpenAI API key cho vision runtime dang thieu.",
            )
        if not _looks_like_openai_vision_model(model):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="model_unverified",
                reason_label="Model OpenAI hien tai chua duoc xac nhan la vision-capable.",
            )
        return _vision_provider_status(
            provider=provider,
            capability=capability,
            available=True,
            model_name=model,
            resolved_base_url=_normalize_base_url(resolve_openai_base_url(settings)) or "https://api.openai.com/v1",
        )

    if provider == "openrouter":
        base_url = _normalize_base_url(resolve_openrouter_base_url(settings))
        if not openrouter_credentials_available(settings):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="missing_api_key",
                reason_label="OpenRouter dang thieu API key rieng hoac cau hinh legacy hop le.",
            )
        if not base_url or "openrouter.ai" not in base_url.lower():
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="base_url_mismatch",
                reason_label="OpenRouter chua duoc cau hinh base URL ro rang cho vision runtime.",
            )
        if not _looks_like_openrouter_vision_model(model):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="model_unverified",
                reason_label="Model OpenRouter hien tai chua duoc xac nhan la vision-capable.",
            )
        return _vision_provider_status(
            provider=provider,
            capability=capability,
            available=True,
            model_name=model,
            resolved_base_url=base_url,
        )

    if provider == "nvidia":
        base_url = _normalize_base_url(resolve_nvidia_base_url(settings))
        if not resolve_nvidia_api_key(settings):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="missing_api_key",
                reason_label="NVIDIA API key cho vision runtime dang thieu.",
                resolved_base_url=base_url,
            )
        if not _looks_like_nvidia_vision_model(model):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="model_unverified",
                reason_label="Model NVIDIA hien tai chua duoc xac nhan la VLM/image-capable.",
                resolved_base_url=base_url,
            )
        return _vision_provider_status(
            provider=provider,
            capability=capability,
            available=True,
            model_name=model,
            resolved_base_url=base_url,
        )

    if provider == "ollama":
        return _probe_ollama_vision_status(
            model,
            capability=capability,
            allow_autoselect=model_name is None,
        )

    if provider == "zhipu":
        if not getattr(settings, "zhipu_api_key", None):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="missing_api_key",
                reason_label="Zhipu API key cho vision runtime dang thieu.",
                resolved_base_url=_normalize_base_url(getattr(settings, "zhipu_base_url", None)),
            )
        if capability == VisionCapability.OCR_EXTRACT:
            if not _looks_like_zhipu_ocr_model(model):
                return _vision_provider_status(
                    provider=provider,
                    capability=capability,
                    available=False,
                    model_name=model,
                    reason_code="model_unverified",
                    reason_label="OCR runtime cho Zhipu hien chi bat contract GLM-OCR.",
                    resolved_base_url=_normalize_base_url(getattr(settings, "zhipu_base_url", None)),
                )
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=True,
                model_name=model,
                resolved_base_url=_normalize_base_url(getattr(settings, "zhipu_base_url", None)),
            )
        if not _looks_like_zhipu_vision_model(model):
            return _vision_provider_status(
                provider=provider,
                capability=capability,
                available=False,
                model_name=model,
                reason_code="model_unverified",
                reason_label="Zhipu vision hien chi bat cac model VLM ro contract nhu GLM-4.6V / GLM-5V.",
                resolved_base_url=_normalize_base_url(getattr(settings, "zhipu_base_url", None)),
            )
        return _vision_provider_status(
            provider=provider,
            capability=capability,
            available=True,
            model_name=model,
            resolved_base_url=_normalize_base_url(getattr(settings, "zhipu_base_url", None)),
        )

    return _vision_provider_status(
        provider=provider,
        capability=capability,
        available=False,
        model_name=model,
        reason_code="provider_unknown",
        reason_label="Provider vision khong duoc ho tro.",
    )


def _resolve_provider_order(
    *,
    capability: VisionCapability,
    preferred_provider: str | None = None,
) -> list[str]:
    preferred = _normalize_provider(preferred_provider)
    capability_provider = _capability_provider_override(capability)
    inferred_provider = _infer_provider_from_capability_model(
        capability,
        _capability_model_override(capability),
    )
    configured_provider = _normalize_provider(getattr(settings, "vision_provider", "auto"))
    configured_chain = list(getattr(settings, "vision_failover_chain", []) or [])
    fallback_chain = list(getattr(settings, "llm_failover_chain", []) or [])

    chain: list[str] = []
    if preferred and preferred != "auto":
        chain.append(preferred)
    elif capability_provider:
        chain.append(capability_provider)
    elif inferred_provider:
        chain.append(inferred_provider)
    elif configured_provider and configured_provider != "auto":
        chain.append(configured_provider)

    for item in configured_chain + fallback_chain + ["google", "openai", "openrouter", "nvidia", "ollama"]:
        normalized = _normalize_provider(item)
        if normalized and normalized not in chain:
            chain.append(normalized)

    # Keep explicit operator/user overrides authoritative.
    if preferred and preferred != "auto":
        return chain
    if capability_provider:
        return chain
    if configured_provider and configured_provider != "auto":
        return chain

    indexed_chain = list(enumerate(chain))
    indexed_chain.sort(key=lambda item: (_lane_fit_priority(item[1], capability), item[0]))
    chain = [provider for _, provider in indexed_chain]

    demoted = _temporarily_demoted_providers(capability)
    if not demoted:
        return chain

    prioritized = [provider for provider in chain if provider not in demoted]
    deferred = [provider for provider in chain if provider in demoted]
    return prioritized + deferred

    


async def fetch_image_as_base64(
    image_url: str,
    timeout: float = VISION_IMAGE_FETCH_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Fetch an image URL and return base64 contents."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(image_url)
            if response.status_code != 200:
                logger.warning(
                    "[VisionRuntime] Image fetch failed: HTTP %d for %s",
                    response.status_code,
                    image_url[:80],
                )
                return None
            content_type = response.headers.get("content-type", "image/jpeg")
            if "image" not in content_type:
                logger.warning(
                    "[VisionRuntime] URL returned non-image content-type: %s",
                    content_type,
                )
                return None
            return base64.b64encode(response.content).decode("utf-8")
    except Exception as exc:
        logger.warning("[VisionRuntime] Image fetch error: %s", _sanitize_error_for_log(exc))
        return None


def _pil_image_to_base64(image: Any, media_type: str = "image/jpeg") -> str:
    from PIL import Image

    if not isinstance(image, Image.Image):
        raise TypeError("image must be a PIL.Image.Image")

    image_format = "PNG" if media_type == "image/png" else "JPEG"
    buffer = io.BytesIO()
    save_kwargs = {"format": image_format}
    if image_format == "JPEG":
        save_kwargs["quality"] = 85
    image.save(buffer, **save_kwargs)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


async def _run_google_vision_request(
    *,
    model_name: str,
    prompt: str,
    image_base64: str,
    media_type: str,
    temperature: float,
    max_output_tokens: int,
) -> str:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.google_api_key)
    image_part = genai_types.Part.from_bytes(
        data=base64.b64decode(image_base64),
        mime_type=media_type,
    )
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model_name,
        contents=[prompt, image_part],
        config=genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    text = getattr(response, "text", None)
    return text.strip() if isinstance(text, str) else ""


async def _run_zhipu_layout_parsing_request(
    *,
    model_name: str,
    image_base64: str,
    media_type: str,
    timeout_seconds: float,
) -> str:
    import httpx

    base_url = _normalize_base_url(getattr(settings, "zhipu_base_url", None)) or "https://api.z.ai/api/paas/v4"
    endpoint = f"{base_url}/layout_parsing"
    payload = {
        "model": model_name,
        "file": _build_image_data_url(
            image_base64=image_base64,
            media_type=media_type,
        ),
        "request_id": f"wiii-ocr-{int(time.time() * 1000)}",
    }
    request_timeout = httpx.Timeout(
        timeout_seconds,
        connect=min(timeout_seconds, 8.0),
    )

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {getattr(settings, 'zhipu_api_key', '')}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    markdown = data.get("md_results") if isinstance(data, dict) else None
    if isinstance(markdown, str) and markdown.strip():
        return markdown.strip()

    if isinstance(data, dict):
        layout_details = data.get("layout_details")
        if isinstance(layout_details, list):
            fragments: list[str] = []
            for page in layout_details:
                if not isinstance(page, list):
                    continue
                for item in page:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content")
                    if isinstance(content, str) and content.strip():
                        fragments.append(content.strip())
            if fragments:
                return "\n".join(fragments)
    return ""


def _build_openai_image_content(
    *,
    prompt: str,
    image_base64: str,
    media_type: str,
) -> list[dict[str, Any]]:
    data_url = _build_image_data_url(
        image_base64=image_base64,
        media_type=media_type,
    )
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]


def _build_image_data_url(*, image_base64: str, media_type: str) -> str:
    normalized = (image_base64 or "").strip()
    if normalized.startswith("data:"):
        return normalized
    return f"data:{media_type};base64,{normalized}"


def _openai_vision_generation_kwargs(
    *,
    provider: str,
    model_name: str,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    normalized_model = str(model_name or "").strip().lower()
    # Newer OpenAI Chat Completions models reject legacy max_tokens. Keep this
    # scoped to the first-party OpenAI endpoint so OpenRouter/Zhipu/Ollama
    # compatibility layers continue receiving the parameter shape they expect.
    if provider == "openai" and normalized_model.startswith(("gpt-5", "o3", "o4")):
        return {"max_completion_tokens": max_output_tokens}
    return {
        "max_tokens": max_output_tokens,
        "temperature": temperature,
    }


async def _run_openai_compatible_vision_request(
    *,
    provider: str,
    model_name: str,
    prompt: str,
    image_base64: str,
    media_type: str,
    temperature: float,
    max_output_tokens: int,
    resolved_base_url: str | None,
) -> str:
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for vision runtime") from exc

    if provider == "ollama":
        api_key = settings.ollama_api_key or "ollama"
        base_url = (resolved_base_url or settings.ollama_base_url or "http://localhost:11434").rstrip("/") + "/v1"
    elif provider == "zhipu":
        api_key = getattr(settings, "zhipu_api_key", None)
        base_url = resolved_base_url or getattr(settings, "zhipu_base_url", None) or "https://open.bigmodel.cn/api/paas/v4"
    elif provider == "openrouter":
        api_key = resolve_openrouter_api_key(settings)
        base_url = resolved_base_url or resolve_openrouter_base_url(settings)
    elif provider == "nvidia":
        api_key = resolve_nvidia_api_key(settings)
        base_url = resolved_base_url or resolve_nvidia_base_url(settings)
    else:
        api_key = resolve_openai_api_key(settings)
        base_url = resolved_base_url or resolve_openai_base_url(settings) or "https://api.openai.com/v1"

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    request_kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": _build_openai_image_content(
                    prompt=prompt,
                    image_base64=image_base64,
                    media_type=media_type,
                ),
            }
        ],
        **_openai_vision_generation_kwargs(
            provider=provider,
            model_name=model_name,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        ),
    }
    response = await client.chat.completions.create(
        **request_kwargs,
    )
    choice = response.choices[0] if response.choices else None
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    return ""


async def run_vision_prompt(
    *,
    prompt: str,
    capability: VisionCapability,
    image_base64: str | None = None,
    image_url: str | None = None,
    media_type: str = "image/jpeg",
    preferred_provider: str | None = None,
    timeout_seconds: float | None = None,
    temperature: float = 0.2,
    max_output_tokens: int = 1024,
) -> VisionResult:
    """Run one image-understanding prompt through the shared vision authority."""
    start = time.time()
    result = VisionResult(capability=capability)

    resolved_image_base64 = image_base64
    if not resolved_image_base64 and image_url:
        resolved_image_base64 = await fetch_image_as_base64(image_url)
    if not resolved_image_base64:
        result.error = "Không có dữ liệu ảnh hợp lệ cho vision runtime."
        result.reason_code = "image_missing"
        result.reason_label = "Không lấy được dữ liệu ảnh."
        result.total_time_ms = (time.time() - start) * 1000
        return result

    provider_order = _resolve_provider_order(
        capability=capability,
        preferred_provider=preferred_provider,
    )
    timeout_value = timeout_seconds or getattr(
        settings,
        "vision_timeout_seconds",
        VISION_RUNTIME_DEFAULT_TIMEOUT_SECONDS,
    )

    for provider in provider_order:
        status = _provider_status(provider, capability)
        attempt: dict[str, Any] = {
            "provider": provider,
            "available": status.available,
            "model": status.model_name,
            "lane_fit": status.lane_fit,
            "lane_fit_label": status.lane_fit_label,
            "reason_code": status.reason_code,
        }
        result.attempted_providers.append(attempt)
        if not status.available or not status.model_name:
            continue

        try:
            async with asyncio.timeout(timeout_value):
                if provider == "google":
                    text = await _run_google_vision_request(
                        model_name=status.model_name,
                        prompt=prompt,
                        image_base64=resolved_image_base64,
                        media_type=media_type,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    )
                elif provider == "zhipu" and capability == VisionCapability.OCR_EXTRACT:
                    text = await _run_zhipu_layout_parsing_request(
                        model_name=status.model_name,
                        image_base64=resolved_image_base64,
                        media_type=media_type,
                        timeout_seconds=timeout_value,
                    )
                elif provider in {"openai", "openrouter", "nvidia", "ollama", "zhipu"}:
                    text = await _run_openai_compatible_vision_request(
                        provider=provider,
                        model_name=status.model_name,
                        prompt=prompt,
                        image_base64=resolved_image_base64,
                        media_type=media_type,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        resolved_base_url=status.resolved_base_url,
                    )
                else:
                    continue

            if text:
                cleaned_text = _compact_repeated_vision_text(text)
                result.success = True
                result.text = cleaned_text or text.strip()
                result.provider = provider
                result.model_name = status.model_name
                result.resolved_base_url = status.resolved_base_url
                result.total_time_ms = (time.time() - start) * 1000
                _record_recent_vision_success(provider, capability)
                _record_vision_runtime_observation(
                    provider=provider,
                    capability=capability,
                    success=True,
                    model_name=status.model_name,
                    note=result.text,
                )
                return result

            attempt["reason_code"] = "empty_output"
            _record_recent_vision_failure(
                provider,
                capability,
                reason_code="empty_output",
            )
            _record_vision_runtime_observation(
                provider=provider,
                capability=capability,
                success=False,
                model_name=status.model_name,
                error="Provider tra ve output rong cho vision runtime.",
            )
        except TimeoutError as exc:
            classified = classify_failover_reason_impl(
                error=exc,
                timeout_seconds=timeout_value,
            )
            attempt.update(classified)
            _record_recent_vision_failure(
                provider,
                capability,
                reason_code=classified.get("reason_code"),
            )
            _record_vision_runtime_observation(
                provider=provider,
                capability=capability,
                success=False,
                model_name=status.model_name,
                error=classified.get("reason_label") or classified.get("detail"),
            )
        except Exception as exc:
            classified = classify_failover_reason_impl(error=exc)
            attempt.update(classified)
            _record_recent_vision_failure(
                provider,
                capability,
                reason_code=classified.get("reason_code"),
            )
            _record_vision_runtime_observation(
                provider=provider,
                capability=capability,
                success=False,
                model_name=status.model_name,
                error=classified.get("reason_label") or classified.get("detail") or str(exc),
            )
            logger.warning(
                "[VisionRuntime] provider=%s capability=%s failed: %s",
                provider,
                capability.value,
                _sanitize_error_for_log(exc),
            )

    actionable_attempt = next(
        (
            attempt
            for attempt in result.attempted_providers
            if attempt.get("available") and attempt.get("reason_code")
        ),
        None,
    )
    last_attempt = actionable_attempt or (result.attempted_providers[-1] if result.attempted_providers else {})
    result.error = "Không có provider vision khả dụng cho request này."
    result.reason_code = last_attempt.get("reason_code") or "provider_unavailable"
    result.reason_label = last_attempt.get("reason_label")
    result.total_time_ms = (time.time() - start) * 1000
    return result


async def describe_image_content(
    *,
    image_base64: str,
    media_type: str = "image/jpeg",
    context_hint: str = "",
    preferred_provider: str | None = None,
) -> VisionResult:
    prompt = (
        "Mô tả chi tiết hình ảnh này bằng tiếng Việt. "
        "Nêu rõ: loại hình ảnh (biểu đồ/bảng/ảnh/sơ đồ/tài liệu), "
        "nội dung chính, các chi tiết quan trọng. "
        "Viết ngắn gọn (50-150 từ)."
    )
    if context_hint:
        prompt += f"\nNgữ cảnh: {context_hint}"
    return await run_vision_prompt(
        prompt=prompt,
        capability=VisionCapability.VISUAL_DESCRIBE,
        image_base64=image_base64,
        media_type=media_type,
        preferred_provider=preferred_provider,
        max_output_tokens=512,
        temperature=0.2,
    )


def _build_image_analysis_prompt(query: str) -> str:
    safe_query = str(query or "").strip()[:500] or "Briefly describe the image."
    return (
        "You are directly inspecting the attached image.\n"
        "Answer the user's visual question using only visible evidence.\n\n"
        f"User question: {safe_query}\n\n"
        "Rules:\n"
        "- Answer every explicit part of the user's question. If the user asks for both visible text and color, include both.\n"
        "- If the user asks to read text, marker, code, or label, copy the exact visible text verbatim.\n"
        "- If the user asks about color, name the visible color directly.\n"
        "- If the user asks about background color, mau nen, màu nền, or outer background, answer the background color, not the text color.\n"
        "- Do not explain the meaning of a marker; only report what is visible.\n"
        "- Do not say the image is unavailable if you can see it.\n"
        "- If a character or visual detail is uncertain, say so clearly instead of guessing.\n"
        "- Final answer must be in Vietnamese; keep exact OCR text inside quotes.\n"
        "- Do not include labels such as \"Answer:\" or markdown headings.\n"
        "- Do not use bullet points.\n"
        "- Answer in 1-3 short natural sentences, no checklist."
    )


async def analyze_image_for_query(
    *,
    image_base64: str,
    query: str,
    media_type: str = "image/jpeg",
    preferred_provider: str | None = None,
) -> VisionResult:
    prompt = _build_image_analysis_prompt(query)
    return await run_vision_prompt(
        prompt=prompt,
        capability=VisionCapability.GROUNDED_VISUAL_ANSWER,
        image_base64=image_base64,
        media_type=media_type,
        preferred_provider=preferred_provider,
        max_output_tokens=256,
        temperature=0.0,
    )


async def extract_document_markdown(
    *,
    image_base64: str | None = None,
    image_url: str | None = None,
    image: Any | None = None,
    media_type: str = "image/jpeg",
    prompt: str,
    preferred_provider: str | None = None,
) -> VisionResult:
    resolved_image_base64 = image_base64
    if not resolved_image_base64 and image is not None:
        resolved_image_base64 = _pil_image_to_base64(image, media_type=media_type)
    return await run_vision_prompt(
        prompt=prompt,
        capability=VisionCapability.OCR_EXTRACT,
        image_base64=resolved_image_base64,
        image_url=image_url,
        media_type=media_type,
        preferred_provider=preferred_provider,
        max_output_tokens=2048,
        temperature=0.1,
    )


__all__ = [
    "VisionCapability",
    "VisionProviderStatus",
    "VisionResult",
    "VISION_IMAGE_FETCH_TIMEOUT_SECONDS",
    "VISION_RUNTIME_DEFAULT_TIMEOUT_SECONDS",
    "analyze_image_for_query",
    "describe_image_content",
    "extract_document_markdown",
    "fetch_image_as_base64",
    "reset_vision_runtime_caches",
    "run_vision_prompt",
]
