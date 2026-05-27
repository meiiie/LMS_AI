"""Admin-managed grouped runtime profiles for multi-agent workloads."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Mapping

from app.engine.llm_provider_registry import is_supported_provider

logger = logging.getLogger(__name__)

AGENT_RUNTIME_PROFILE_GROUPS = (
    "routing",
    "safety",
    "knowledge",
    "utility",
    "evaluation",
    "creative",
)
_VALID_TIERS = frozenset({"deep", "moderate", "light"})

AGENT_RUNTIME_GROUP_NODES: dict[str, tuple[str, ...]] = {
    "routing": ("supervisor",),
    "safety": ("guardian",),
    "knowledge": ("rag_agent", "tutor_agent", "synthesizer"),
    "utility": ("direct", "direct_chatter", "memory"),
    "evaluation": (
        "grader",
        "retrieval_grader",
        "query_planner",
        "curation",
        "aggregator",
        "reasoning_narrator",
        "sentiment_analyzer",
        "kg_builder_agent",
    ),
    "creative": ("code_studio_agent", "course_generation", "direct_identity"),
}
AGENT_NODE_TO_GROUP = {
    node_id: group_name
    for group_name, node_ids in AGENT_RUNTIME_GROUP_NODES.items()
    for node_id in node_ids
}

DEFAULT_AGENT_RUNTIME_PROFILES: dict[str, dict[str, Any]] = {
    "routing": {
        "tier": "light",
        "provider_models": {},
    },
    "safety": {
        "tier": "light",
        "provider_models": {},
    },
    "knowledge": {
        "tier": "moderate",
        "provider_models": {},
    },
    "utility": {
        "tier": "light",
        "provider_models": {},
    },
    "evaluation": {
        "tier": "moderate",
        "provider_models": {},
    },
    "creative": {
        "tier": "deep",
        "provider_models": {
            "google": "gemini-3.1-pro-preview",
            "zhipu": "glm-5",
        },
    },
}


def get_default_agent_runtime_profiles() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DEFAULT_AGENT_RUNTIME_PROFILES)


def resolve_agent_runtime_profile_group(node_id: str) -> str | None:
    return AGENT_NODE_TO_GROUP.get(node_id)


def _sanitize_provider_models(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    provider_models: dict[str, str] = {}
    for provider_name, model_name in value.items():
        if not isinstance(provider_name, str) or not isinstance(model_name, str):
            continue
        normalized_provider = provider_name.strip().lower()
        normalized_model = model_name.strip()
        if not normalized_provider or not normalized_model:
            continue
        if not is_supported_provider(normalized_provider):
            logger.warning(
                "Ignoring unsupported provider '%s' in agent profile provider_models",
                normalized_provider,
            )
            continue
        provider_models[normalized_provider] = normalized_model
    return provider_models


def sanitize_agent_runtime_profiles(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except Exception:
            logger.warning("Invalid agent runtime profiles JSON, using defaults")
            value = {}

    sanitized = get_default_agent_runtime_profiles()
    if not isinstance(value, Mapping):
        return sanitized

    for group_name in AGENT_RUNTIME_PROFILE_GROUPS:
        raw_profile = value.get(group_name)
        if not isinstance(raw_profile, Mapping):
            continue

        profile = sanitized[group_name]
        default_provider = raw_profile.get("default_provider")
        if isinstance(default_provider, str):
            normalized_provider = default_provider.strip().lower()
            if is_supported_provider(normalized_provider):
                profile["default_provider"] = normalized_provider

        tier = raw_profile.get("tier")
        if isinstance(tier, str):
            normalized_tier = tier.strip().lower()
            if normalized_tier in _VALID_TIERS:
                profile["tier"] = normalized_tier

        if "provider_models" in raw_profile:
            provider_models = _sanitize_provider_models(raw_profile.get("provider_models"))
            if provider_models:
                profile["provider_models"] = provider_models
            else:
                profile["provider_models"] = copy.deepcopy(
                    DEFAULT_AGENT_RUNTIME_PROFILES[group_name].get("provider_models", {})
                )

    return sanitized


def dumps_agent_runtime_profiles(value: Any) -> str:
    return json.dumps(
        sanitize_agent_runtime_profiles(value),
        ensure_ascii=False,
        sort_keys=True,
    )
