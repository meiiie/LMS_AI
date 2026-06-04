"""
Per-agent provider configuration registry with grouped runtime profiles.

Default runtime policy is now layered:
  1. grouped admin-managed agent profiles
  2. legacy per-node JSON overrides (backward compatibility)
  3. explicit per-request provider pinning
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.config import settings
from app.engine.multi_agent.agent_runtime_profiles import (
    get_default_agent_runtime_profiles,
    resolve_agent_runtime_profile_group,
    sanitize_agent_runtime_profiles,
)
from app.engine.model_catalog import NVIDIA_DEFAULT_MODEL

logger = logging.getLogger(__name__)


@dataclass
class AgentNodeConfig:
    """Configuration for a single WiiiRunner node."""

    node_id: str
    provider: str = ""
    model: Optional[str] = None
    tier: str = "moderate"
    temperature: float = 0.5
    max_agentic_steps: int = 5
    enable_thinking: bool = True
    enable_agentic_loop: bool = False


_DEFAULT_CONFIGS: Dict[str, AgentNodeConfig] = {
    "tutor_agent": AgentNodeConfig("tutor_agent", tier="moderate", enable_agentic_loop=True),
    "rag_agent": AgentNodeConfig("rag_agent", tier="moderate", enable_agentic_loop=True),
    "supervisor": AgentNodeConfig("supervisor", tier="light", temperature=0.3),
    "guardian": AgentNodeConfig("guardian", tier="light", temperature=0.0),
    "grader": AgentNodeConfig("grader", tier="moderate"),
    "memory": AgentNodeConfig("memory", tier="light", temperature=0.5),
    "direct": AgentNodeConfig("direct", tier="light", enable_agentic_loop=True),
    "direct_chatter": AgentNodeConfig(
        "direct_chatter",
        provider="nvidia",
        model=NVIDIA_DEFAULT_MODEL,
        tier="light",
        temperature=0.7,
    ),
    "direct_identity": AgentNodeConfig("direct_identity", tier="deep"),
    "code_studio_agent": AgentNodeConfig(
        "code_studio_agent",
        model="gemini-3.1-pro-preview",
        tier="deep",
        enable_agentic_loop=True,
    ),
    "synthesizer": AgentNodeConfig("synthesizer", tier="moderate"),
}


class AgentConfigRegistry:
    """Singleton registry for per-node and grouped LLM configuration."""

    _configs: Dict[str, AgentNodeConfig] = {}
    _group_profiles: dict[str, dict[str, Any]] = {}
    _initialized: bool = False
    _model_llm_cache: Dict[str, object] = {}

    @classmethod
    def initialize(
        cls,
        overrides_json: str = "{}",
        agent_profiles: Any = None,
    ) -> None:
        """Initialize with defaults + grouped profiles + optional node overrides."""
        cls._configs = {
            key: AgentNodeConfig(
                node_id=value.node_id,
                provider=value.provider,
                model=value.model,
                tier=value.tier,
                temperature=value.temperature,
                max_agentic_steps=value.max_agentic_steps,
                enable_thinking=value.enable_thinking,
                enable_agentic_loop=value.enable_agentic_loop,
            )
            for key, value in _DEFAULT_CONFIGS.items()
        }
        cls._group_profiles = sanitize_agent_runtime_profiles(
            agent_profiles
            if agent_profiles is not None
            else getattr(settings, "agent_runtime_profiles", "{}")
        )

        try:
            overrides = json.loads(overrides_json) if overrides_json else {}
        except (json.JSONDecodeError, TypeError):
            logger.warning("[AGENT_CONFIG] Invalid JSON overrides, using defaults")
            overrides = {}

        for node_id, node_overrides in overrides.items():
            if not isinstance(node_overrides, dict):
                continue
            config = cls._configs.get(node_id, AgentNodeConfig(node_id))
            cls._configs[node_id] = config
            for key, value in node_overrides.items():
                if hasattr(config, key) and key != "node_id":
                    setattr(config, key, value)

        cls._initialized = True
        logger.info(
            "[AGENT_CONFIG] Initialized %d node configs + %d grouped profiles",
            len(cls._configs),
            len(cls._group_profiles),
        )

    @classmethod
    def _ensure_initialized(cls) -> None:
        if not cls._initialized:
            cls.initialize(
                getattr(settings, "agent_provider_configs", "{}"),
                getattr(settings, "agent_runtime_profiles", "{}"),
            )

    @classmethod
    def get_config(cls, node_id: str) -> AgentNodeConfig:
        """Get raw node config, falling back to defaults."""
        cls._ensure_initialized()
        return cls._configs.get(node_id, AgentNodeConfig(node_id))

    @classmethod
    def get_group_profiles(cls) -> dict[str, dict[str, Any]]:
        cls._ensure_initialized()
        return copy.deepcopy(cls._group_profiles or get_default_agent_runtime_profiles())

    @classmethod
    def _get_group_profile(cls, node_id: str) -> dict[str, Any]:
        cls._ensure_initialized()
        group_name = resolve_agent_runtime_profile_group(node_id)
        if not group_name:
            return {}
        return copy.deepcopy(cls._group_profiles.get(group_name, {}))

    @classmethod
    def _resolve_auto_provider(cls, preferred_provider: str) -> str:
        normalized_preferred = str(preferred_provider or "").strip().lower() or "google"
        try:
            from app.engine.llm_pool import LLMPool
            from app.services.llm_selectability_service import (
                choose_best_runtime_provider,
                get_llm_selectability_snapshot,
            )

            best = choose_best_runtime_provider(
                preferred_provider=normalized_preferred,
                provider_order=LLMPool._get_request_provider_chain(),
                allow_degraded_fallback=False,
            )
            if best is not None:
                return best.provider

            degraded_best = choose_best_runtime_provider(
                preferred_provider=normalized_preferred,
                provider_order=LLMPool._get_request_provider_chain(),
                allow_degraded_fallback=True,
            )
            if degraded_best is not None:
                return degraded_best.provider

            snapshot = get_llm_selectability_snapshot()
            if snapshot:
                selectable_preferred = next(
                    (
                        item
                        for item in snapshot
                        if item.provider == normalized_preferred
                        and item.state == "selectable"
                        and item.configured
                        and item.request_selectable
                    ),
                    None,
                )
                if selectable_preferred is not None:
                    return selectable_preferred.provider

                selectable_any = next(
                    (
                        item
                        for item in snapshot
                        if item.state == "selectable"
                        and item.configured
                        and item.request_selectable
                    ),
                    None,
                )
                if selectable_any is not None:
                    return selectable_any.provider
        except Exception as exc:
            logger.debug("[AGENT_CONFIG] Selectability-aware auto provider skipped: %s", exc)
        return normalized_preferred

    @classmethod
    def _resolve_effective_runtime(
        cls,
        node_id: str,
        *,
        provider_override: Optional[str] = None,
    ) -> tuple[AgentNodeConfig, dict[str, Any], str, str, Optional[str]]:
        config = cls.get_config(node_id)
        group_profile = cls._get_group_profile(node_id)
        effective_tier = str(group_profile.get("tier") or config.tier or "moderate").lower()
        preferred_provider = str(
            group_profile.get("default_provider") or config.provider or settings.llm_provider or "google"
        ).lower()

        explicit_provider = (
            str(provider_override).strip().lower()
            if provider_override and provider_override != "auto"
            else None
        )
        effective_provider = explicit_provider or cls._resolve_auto_provider(preferred_provider)

        provider_models = group_profile.get("provider_models", {})
        if not isinstance(provider_models, dict):
            provider_models = {}

        model_override = provider_models.get(effective_provider)
        if model_override is None and config.model:
            config_provider = str(config.provider or "").strip().lower()
            if explicit_provider:
                if config_provider == explicit_provider:
                    model_override = config.model
            elif effective_provider == config_provider:
                model_override = config.model

        return config, group_profile, effective_provider, effective_tier, model_override

    @classmethod
    def get_llm(
        cls,
        node_id: str,
        effort_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        requested_model: Optional[str] = None,
        *,
        strict_provider_pin: bool = True,
    ):
        """Get the LLM for one node after applying grouped profiles and pinning."""
        from app.engine.llm_factory import ThinkingTier
        from app.engine.llm_pool import get_llm_deep, get_llm_light, get_llm_moderate

        normalized_requested_model = (
            str(requested_model).strip()
            if requested_model is not None and str(requested_model).strip()
            else None
        )

        if not strict_provider_pin and provider_override and provider_override != "auto":
            config = cls.get_config(node_id)
            group_profile = cls._get_group_profile(node_id)
            effective_tier = str(group_profile.get("tier") or config.tier or "moderate").lower()
            effective_provider = cls._resolve_auto_provider(provider_override)
            provider_models = group_profile.get("provider_models", {})
            if not isinstance(provider_models, dict):
                provider_models = {}
            model_override = provider_models.get(effective_provider)
            config_provider = str(config.provider or "").strip().lower()
            if model_override is None and config.model and effective_provider == config_provider:
                model_override = config.model
        else:
            config, group_profile, effective_provider, effective_tier, model_override = (
                cls._resolve_effective_runtime(
                    node_id,
                    provider_override=provider_override,
                )
            )

        if normalized_requested_model and provider_override and provider_override != "auto":
            model_override = normalized_requested_model

        tier_map = {
            "deep": ThinkingTier.DEEP,
            "moderate": ThinkingTier.MODERATE,
            "light": ThinkingTier.LIGHT,
        }
        default_tier = tier_map.get(effective_tier, ThinkingTier.MODERATE)
        explicit_provider = strict_provider_pin and provider_override and provider_override != "auto"

        if explicit_provider:
            from app.engine.llm_pool import get_llm_for_provider

            if model_override:
                return cls._get_or_create_model_llm_for_provider(
                    effective_provider,
                    model_override,
                    default_tier,
                    node_id=node_id,
                    strict_pin=True,
                )
            return get_llm_for_provider(
                effective_provider,
                effort=effort_override,
                default_tier=default_tier,
                strict_pin=True,
            )

        if model_override:
            return cls._get_or_create_model_llm_for_provider(
                effective_provider,
                model_override,
                default_tier,
                node_id=node_id,
                strict_pin=False,
            )

        if effort_override:
            from app.engine.llm_pool import get_llm_for_effort, get_llm_for_provider

            if effective_provider != getattr(settings, "llm_provider", "google"):
                return get_llm_for_provider(
                    effective_provider,
                    effort=effort_override,
                    default_tier=default_tier,
                )
            return get_llm_for_effort(effort_override, default_tier=default_tier)

        if effective_provider != getattr(settings, "llm_provider", "google"):
            from app.engine.llm_pool import get_llm_for_provider

            return get_llm_for_provider(
                effective_provider,
                default_tier=default_tier,
            )

        return {
            "deep": get_llm_deep,
            "moderate": get_llm_moderate,
            "light": get_llm_light,
        }.get(effective_tier, get_llm_moderate)()

    @classmethod
    def get_native_llm(
        cls,
        node_id: str,
        effort_override: Optional[str] = None,
        provider_override: Optional[str] = None,
        requested_model: Optional[str] = None,
    ):
        """Resolve a framework-free provider/model handle for native chat calls."""
        from app.engine.multi_agent.openai_stream_runtime import (
            _supports_native_answer_streaming_impl,
        )
        from app.engine.native_chat_runtime import NativeChatModelHandle

        config, _group_profile, effective_provider, effective_tier, model_override = (
            cls._resolve_effective_runtime(
                node_id,
                provider_override=provider_override,
            )
        )
        if not _supports_native_answer_streaming_impl(effective_provider):
            return None

        tier_key = str(effort_override or effective_tier or "moderate").strip().lower()
        if tier_key not in {"deep", "moderate", "light"}:
            tier_key = effective_tier if effective_tier in {"deep", "moderate", "light"} else "moderate"

        normalized_requested_model = (
            str(requested_model).strip()
            if requested_model is not None and str(requested_model).strip()
            else None
        )
        model_name = (
            normalized_requested_model
            or model_override
            or cls._resolve_native_model_name(effective_provider, tier_key)
        )
        if not model_name:
            return None

        return NativeChatModelHandle(
            _wiii_provider_name=effective_provider,
            _wiii_requested_provider=provider_override,
            _wiii_model_name=str(model_name),
            _wiii_tier_key=tier_key,
            temperature=config.temperature,
        )

    @staticmethod
    def _resolve_native_model_name(provider_name: str, tier_key: str) -> str | None:
        """Resolve native model names without constructing LangChain provider objects."""
        normalized = str(provider_name or "").strip().lower()
        if normalized == "nvidia":
            from app.engine.openai_compatible_credentials import (
                resolve_nvidia_model,
                resolve_nvidia_model_advanced,
            )
            from app.engine.llm_model_health import is_model_degraded

            base = str(resolve_nvidia_model(settings) or "").strip()
            advanced = str(resolve_nvidia_model_advanced(settings) or "").strip()
            if tier_key == "deep":
                selected = advanced
                fallback = base
            else:
                selected = base
                fallback = advanced
            if (
                selected
                and fallback
                and selected != fallback
                and is_model_degraded("nvidia", selected)
                and not is_model_degraded("nvidia", fallback)
            ):
                logger.warning(
                    "[AGENT_CONFIG] NVIDIA native model %s is degraded; selecting %s for %s tier",
                    selected,
                    fallback,
                    tier_key,
                )
                return fallback
            return selected or fallback or None
        if normalized == "google":
            if tier_key == "deep":
                return getattr(settings, "google_model_advanced", settings.google_model)
            return settings.google_model
        if normalized == "zhipu":
            if tier_key == "deep":
                return settings.zhipu_model_advanced
            return settings.zhipu_model
        if normalized == "openrouter":
            return getattr(settings, "openrouter_model", None) or settings.openai_model
        if normalized == "openai":
            if tier_key == "deep":
                return settings.openai_model_advanced
            return settings.openai_model
        return None

    @classmethod
    def _get_or_create_model_llm_for_provider(
        cls,
        provider_name: str,
        model_name: str,
        tier,
        *,
        node_id: str,
        strict_pin: bool,
    ):
        cache_key = f"{provider_name}:{model_name}:{getattr(tier, 'value', tier)}"
        if cache_key in cls._model_llm_cache:
            return cls._model_llm_cache[cache_key]

        try:
            from app.engine.llm_pool import LLMPool

            llm = LLMPool.create_llm_with_model_for_provider(
                provider_name,
                model_name,
                tier,
            )
            if llm:
                cls._model_llm_cache[cache_key] = llm
                logger.info(
                    "[AGENT_CONFIG] Created dedicated LLM for %s: provider=%s model=%s tier=%s",
                    node_id,
                    provider_name,
                    model_name,
                    getattr(tier, "value", tier),
                )
                return llm
        except Exception as exc:
            logger.warning(
                "[AGENT_CONFIG] Failed to create dedicated model LLM for %s (%s/%s): %s",
                node_id,
                provider_name,
                model_name,
                exc,
            )

        from app.engine.llm_factory import ThinkingTier
        from app.engine.llm_pool import get_llm_for_provider

        tier_value = getattr(tier, "value", str(tier))
        tier_map = {
            "deep": ThinkingTier.DEEP,
            "moderate": ThinkingTier.MODERATE,
            "light": ThinkingTier.LIGHT,
        }
        return get_llm_for_provider(
            provider_name,
            default_tier=tier_map.get(tier_value, ThinkingTier.MODERATE),
            strict_pin=strict_pin,
        )

    @classmethod
    def reset(cls) -> None:
        """Reset registry (for testing)."""
        cls._configs = {}
        cls._group_profiles = {}
        cls._model_llm_cache = {}
        cls._initialized = False
