"""Background model-level health probes for LLM routing."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.engine.llm_model_health import record_model_failure, record_model_success
from app.engine.openai_compatible_credentials import (
    resolve_nvidia_api_key,
    resolve_nvidia_base_url,
    resolve_nvidia_model,
    resolve_nvidia_model_advanced,
)

logger = logging.getLogger(__name__)


PostChatCompletion = Callable[
    [str, str, str, float],
    Awaitable[None],
]


@dataclass(frozen=True)
class ModelHealthProbeResult:
    provider: str
    model: str
    state: str
    reason_code: str | None = None
    latency_ms: float | None = None


def resolve_nvidia_probe_models(settings_obj: Any = settings) -> list[str]:
    """Return unique configured NVIDIA models in routing preference order."""
    models: list[str] = []
    for model in (
        resolve_nvidia_model(settings_obj),
        resolve_nvidia_model_advanced(settings_obj),
    ):
        normalized = str(model or "").strip()
        if normalized and normalized not in models:
            models.append(normalized)
    return models


def classify_model_probe_failure(exc: Exception) -> str:
    """Map probe exceptions to stable model-health reason codes."""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"

    class_name = exc.__class__.__name__.lower()
    detail = str(exc or "").lower()
    if "timeout" in class_name or "timeout" in detail:
        return "timeout"
    if "429" in detail or "rate" in detail or "quota" in detail:
        return "rate_limit"
    if any(marker in detail for marker in ("401", "403", "auth", "forbidden")):
        return "auth_error"
    if "404" in detail or "not found" in detail:
        return "provider_unavailable"
    if any(marker in detail for marker in ("500", "502", "503", "504")):
        return "server_error"
    return "provider_unavailable"


async def post_nvidia_chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> None:
    """Probe one NVIDIA OpenAI-compatible chat model with a tiny completion."""
    import httpx

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 8,
        "messages": [
            {"role": "user", "content": "Reply with exactly one token: OK"},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}")

    data = response.json()
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("empty choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("empty content")


async def run_nvidia_model_health_probe_once(
    *,
    settings_obj: Any = settings,
    timeout_seconds: float | None = None,
    degraded_for_seconds: float | None = None,
    post_chat_completion_fn: PostChatCompletion = post_nvidia_chat_completion,
    logger_obj: logging.Logger = logger,
) -> list[ModelHealthProbeResult]:
    """Probe configured NVIDIA models and update in-memory model health."""
    if not getattr(settings_obj, "enable_llm_model_health_probes", True):
        return []

    api_key = resolve_nvidia_api_key(settings_obj)
    base_url = resolve_nvidia_base_url(settings_obj)
    models = resolve_nvidia_probe_models(settings_obj)
    if not api_key or not base_url or not models:
        return []

    timeout_value = float(
        timeout_seconds
        if timeout_seconds is not None
        else getattr(settings_obj, "llm_model_health_probe_timeout_seconds", 8.0)
    )
    degraded_ttl = float(
        degraded_for_seconds
        if degraded_for_seconds is not None
        else getattr(settings_obj, "llm_model_health_degraded_ttl_seconds", 300.0)
    )

    results: list[ModelHealthProbeResult] = []
    for model in models:
        start = time.perf_counter()
        try:
            await post_chat_completion_fn(base_url, api_key, model, timeout_value)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            reason_code = classify_model_probe_failure(exc)
            record_model_failure(
                "nvidia",
                model,
                reason_code=reason_code,
                error=exc,
                timeout_seconds=timeout_value if reason_code == "timeout" else None,
                degraded_for_seconds=degraded_ttl,
            )
            logger_obj.warning(
                "[LLM_MODEL_PROBE] provider=nvidia model=%s state=degraded reason=%s latency_ms=%s",
                model,
                reason_code,
                latency_ms,
            )
            results.append(
                ModelHealthProbeResult(
                    provider="nvidia",
                    model=model,
                    state="degraded",
                    reason_code=reason_code,
                    latency_ms=latency_ms,
                )
            )
            continue

        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        record_model_success("nvidia", model)
        logger_obj.info(
            "[LLM_MODEL_PROBE] provider=nvidia model=%s state=healthy latency_ms=%s",
            model,
            latency_ms,
        )
        results.append(
            ModelHealthProbeResult(
                provider="nvidia",
                model=model,
                state="healthy",
                latency_ms=latency_ms,
            )
        )
    return results


async def run_nvidia_model_health_probe_loop(
    *,
    settings_obj: Any = settings,
    logger_obj: logging.Logger = logger,
) -> None:
    """Periodically refresh NVIDIA model health until cancelled."""
    while True:
        interval = float(
            getattr(settings_obj, "llm_model_health_probe_interval_seconds", 300.0)
            or 0.0
        )
        if interval <= 0:
            return
        await asyncio.sleep(max(interval, 60.0))
        await run_nvidia_model_health_probe_once(
            settings_obj=settings_obj,
            logger_obj=logger_obj,
        )
