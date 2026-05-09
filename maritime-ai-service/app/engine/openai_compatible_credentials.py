"""Credential and model helpers for OpenAI-compatible providers.

This keeps OpenAI and OpenRouter as separate runtime plugs while preserving
legacy compatibility for older configs that pointed the shared OpenAI slot at
OpenRouter via ``openai_base_url``.
"""

from __future__ import annotations

from typing import Any

from app.engine.model_catalog import (
    NVIDIA_DEFAULT_BASE_URL,
    NVIDIA_DEFAULT_MODEL,
    NVIDIA_DEFAULT_MODEL_ADVANCED,
    NVIDIA_DEFAULT_VISION_MODEL,
    OPENAI_DEFAULT_BASE_URL,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL_ADVANCED,
    OPENROUTER_DEFAULT_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_DEFAULT_MODEL_ADVANCED,
)


def _is_openrouter_base_url(base_url: Any) -> bool:
    text = _normalize_text(base_url)
    return bool(text and "openrouter.ai" in text.lower())


def _normalize_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def resolve_openai_api_key(settings_obj: Any) -> str | None:
    return _normalize_text(getattr(settings_obj, "openai_api_key", None))


def resolve_openai_base_url(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "openai_base_url", None)) or OPENAI_DEFAULT_BASE_URL


def resolve_openai_model(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "openai_model", None)) or OPENAI_DEFAULT_MODEL


def resolve_openai_model_advanced(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "openai_model_advanced", None)) or OPENAI_DEFAULT_MODEL_ADVANCED


def resolve_openrouter_api_key(settings_obj: Any) -> str | None:
    explicit = _normalize_text(getattr(settings_obj, "openrouter_api_key", None))
    if explicit:
        return explicit

    legacy_openai_key = _normalize_text(getattr(settings_obj, "openai_api_key", None))
    legacy_base_url = _normalize_text(getattr(settings_obj, "openai_base_url", None))
    if legacy_openai_key and _is_openrouter_base_url(legacy_base_url):
        return legacy_openai_key
    return None


def resolve_openrouter_base_url(settings_obj: Any) -> str:
    explicit_base_url = _normalize_text(getattr(settings_obj, "openrouter_base_url", None))
    if explicit_base_url:
        return explicit_base_url
    legacy_base_url = _normalize_text(getattr(settings_obj, "openai_base_url", None))
    if _is_openrouter_base_url(legacy_base_url):
        return legacy_base_url or OPENROUTER_DEFAULT_BASE_URL
    return OPENROUTER_DEFAULT_BASE_URL


def resolve_openrouter_model(settings_obj: Any) -> str:
    explicit_model = _normalize_text(getattr(settings_obj, "openrouter_model", None))
    if explicit_model:
        return explicit_model
    legacy_base_url = _normalize_text(getattr(settings_obj, "openai_base_url", None))
    legacy_model = _normalize_text(getattr(settings_obj, "openai_model", None))
    if legacy_model and _is_openrouter_base_url(legacy_base_url):
        return legacy_model
    return OPENROUTER_DEFAULT_MODEL


def resolve_openrouter_model_advanced(settings_obj: Any) -> str:
    explicit_model = _normalize_text(getattr(settings_obj, "openrouter_model_advanced", None))
    if explicit_model:
        return explicit_model
    legacy_base_url = _normalize_text(getattr(settings_obj, "openai_base_url", None))
    legacy_model = _normalize_text(getattr(settings_obj, "openai_model_advanced", None))
    if legacy_model and _is_openrouter_base_url(legacy_base_url):
        return legacy_model
    return OPENROUTER_DEFAULT_MODEL_ADVANCED


def openrouter_credentials_available(settings_obj: Any) -> bool:
    return bool(resolve_openrouter_api_key(settings_obj))


# NVIDIA NIM resolvers (Issue #110) — OpenAI-compatible endpoint at
# integrate.api.nvidia.com. Each resolver mirrors the OpenAI/OpenRouter
# pattern: explicit setting first, fall back to the catalogued default.

def resolve_nvidia_api_key(settings_obj: Any) -> str | None:
    return _normalize_text(getattr(settings_obj, "nvidia_api_key", None))


def resolve_nvidia_base_url(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "nvidia_base_url", None)) or NVIDIA_DEFAULT_BASE_URL


def resolve_nvidia_model(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "nvidia_model", None)) or NVIDIA_DEFAULT_MODEL


def resolve_nvidia_model_advanced(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "nvidia_model_advanced", None)) or NVIDIA_DEFAULT_MODEL_ADVANCED


def resolve_nvidia_vision_model(settings_obj: Any) -> str:
    return _normalize_text(getattr(settings_obj, "nvidia_vision_model", None)) or NVIDIA_DEFAULT_VISION_MODEL


def nvidia_credentials_available(settings_obj: Any) -> bool:
    return bool(resolve_nvidia_api_key(settings_obj))


def is_openrouter_legacy_slot_configured(settings_obj: Any) -> bool:
    explicit_openrouter_key = _normalize_text(getattr(settings_obj, "openrouter_api_key", None))
    if explicit_openrouter_key:
        return False
    legacy_openai_key = _normalize_text(getattr(settings_obj, "openai_api_key", None))
    legacy_base_url = _normalize_text(getattr(settings_obj, "openai_base_url", None))
    return bool(legacy_openai_key and _is_openrouter_base_url(legacy_base_url))
