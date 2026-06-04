"""
LLM Provider Status Endpoint — Per-Request Provider Selection.

Exposes available LLM providers and their health status for the
frontend model switcher UI.
"""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.core.config import settings
from app.engine.model_catalog import ModelCatalogService
from app.engine.openai_compatible_credentials import (
    resolve_nvidia_model,
    resolve_openrouter_model,
)
from app.services.llm_selectability_service import get_llm_selectability_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm"])

PROVIDER_DISPLAY_NAMES = {
    "google": "Gemini",
    "zhipu": "Zhipu GLM",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA NIM",
    "ollama": "Ollama",
}


def _selected_model_for_provider(provider: str) -> str | None:
    if provider == "google":
        return settings.google_model
    if provider == "openai":
        return settings.openai_model
    if provider == "openrouter":
        return resolve_openrouter_model(settings)
    if provider == "nvidia":
        return resolve_nvidia_model(settings)
    if provider == "zhipu":
        return getattr(settings, "zhipu_model", None)
    if provider == "ollama":
        return settings.ollama_model
    return None


async def _get_model_options_by_provider() -> dict[str, list[dict[str, Any]]]:
    """Return provider model options for the chat selector.

    This intentionally lives behind the include_models query flag because
    OpenAI-compatible discovery may touch remote /models endpoints on a cold
    cache. The model catalog service caches those responses.
    """
    try:
        catalog = await ModelCatalogService.get_full_catalog(
            ollama_base_url=settings.ollama_base_url,
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
    except Exception as exc:
        logger.warning("[LLM_STATUS] Could not load model options: %s", exc)
        return {}

    options_by_provider: dict[str, list[dict[str, Any]]] = {}
    for provider, models in (catalog.get("providers") or {}).items():
        selected_model = _selected_model_for_provider(provider)
        options = []
        for model_name, meta in models.items():
            options.append(
                {
                    "provider": getattr(meta, "provider", provider),
                    "model_name": getattr(meta, "model_name", model_name),
                    "display_name": getattr(meta, "display_name", model_name),
                    "status": getattr(meta, "status", "available"),
                    "released_on": getattr(meta, "released_on", None),
                    "is_default": model_name == selected_model,
                }
            )
        options.sort(
            key=lambda item: (
                0 if item.get("is_default") else 1,
                0 if item.get("status") in {"current", "available"} else 1,
                str(item.get("model_name") or ""),
            )
        )
        options_by_provider[provider] = options
    return options_by_provider


@router.get("/llm/status")
async def get_llm_status(
    include_models: bool = Query(
        default=False,
        description="Include cached/discovered model options for chat selector UI.",
    ),
):
    """Return available LLM providers and their status."""
    model_options_by_provider = (
        await _get_model_options_by_provider() if include_models else {}
    )
    providers = []
    for item in get_llm_selectability_snapshot():
        payload = {
            "id": item.provider,
            "display_name": item.display_name or PROVIDER_DISPLAY_NAMES.get(item.provider, item.provider),
            "available": item.available,
            "is_primary": item.is_primary,
            "is_fallback": item.is_fallback,
            "state": item.state,
            "reason_code": item.reason_code,
            "reason_label": item.reason_label,
            "selected_model": item.selected_model,
            "strict_pin": item.strict_pin,
            "verified_at": item.verified_at,
        }
        if include_models:
            payload["model_options"] = model_options_by_provider.get(item.provider, [])
        providers.append(payload)
    return {"providers": providers}
