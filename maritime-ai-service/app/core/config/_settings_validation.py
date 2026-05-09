"""Validation and nested sync helpers for Settings."""

from __future__ import annotations

from typing import Optional

from app.core.config.cache import CacheConfig
from app.core.config.character import CharacterConfig
from app.core.config.database import DatabaseConfig
from app.core.config.living_agent import LivingAgentConfig
from app.core.config.llm import LLMConfig
from app.core.config.lms import LMSIntegrationConfig
from app.core.config.memory import MemoryConfig
from app.core.config.product_search import ProductSearchConfig
from app.core.config.rag import RAGConfig
from app.core.config.thinking import ThinkingConfig
from app.core.secret_validation import is_missing_or_placeholder_secret
from app.engine.llm_provider_registry import get_supported_provider_names
from app.engine.llm_timeout_policy import loads_timeout_provider_overrides


def validate_environment_value(v: str) -> str:
    allowed = ["development", "staging", "production"]
    if v not in allowed:
        raise ValueError(f"environment must be one of {allowed}")
    return v


def validate_log_level_value(v: str) -> str:
    allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if v.upper() not in allowed:
        raise ValueError(f"log_level must be one of {allowed}")
    return v.upper()


def validate_jwt_expire_value(v: int) -> int:
    if v <= 0:
        raise ValueError("jwt_expire_minutes must be positive")
    if v > 43200:
        raise ValueError("jwt_expire_minutes must not exceed 43200 (30 days)")
    return v


def validate_postgres_port_value(v: int) -> int:
    if not (1 <= v <= 65535):
        raise ValueError("postgres_port must be between 1 and 65535")
    return v


def validate_positive_value(field_name: str, v: int) -> int:
    if v <= 0:
        raise ValueError(f"{field_name} must be positive")
    return v


def validate_range_value(field_name: str, v: int, minimum: int, maximum: int) -> int:
    if not (minimum <= v <= maximum):
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return v


def validate_similarity_threshold_value(v: float) -> float:
    if not (0.0 <= v <= 1.0):
        raise ValueError("Similarity threshold must be between 0.0 and 1.0")
    return v


def validate_grading_threshold_value(v: float) -> float:
    if not (0.0 <= v <= 10.0):
        raise ValueError("Grading threshold must be between 0.0 and 10.0")
    return v


def validate_llm_provider_value(v: str) -> str:
    allowed = list(get_supported_provider_names())
    if v not in allowed:
        raise ValueError(f"llm_provider must be one of {allowed}")
    return v


def validate_choice_value(field_name: str, v: str, allowed: list[str]) -> str:
    if v not in allowed:
        raise ValueError(f"{field_name} must be one of {allowed}")
    return v


def validate_log_format_value(v: str) -> str:
    allowed = ["json", "text"]
    if v.lower() not in allowed:
        raise ValueError(f"log_format must be one of {allowed}")
    return v.lower()


def validate_embedding_dimensions_value(v: int) -> int:
    if not (128 <= v <= 4096):
        raise ValueError("embedding_dimensions must be between 128 and 4096")
    return v


def validate_url_field_value(v: Optional[str]) -> Optional[str]:
    if v and not v.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    return v


def normalize_string_list_values(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = item.strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def validate_openrouter_data_collection_value(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    normalized = v.strip().lower()
    allowed = {"allow", "deny"}
    if normalized not in allowed:
        raise ValueError(
            f"openrouter_data_collection must be one of {sorted(allowed)}"
        )
    return normalized


def validate_openrouter_provider_sort_value(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    normalized = v.strip().lower()
    allowed = {"price", "latency", "throughput"}
    if normalized not in allowed:
        raise ValueError(
            f"openrouter_provider_sort must be one of {sorted(allowed)}"
        )
    return normalized


def validate_google_compat_url_value(v: str) -> str:
    if not v.startswith(("http://", "https://")):
        raise ValueError("google_openai_compat_url must start with http:// or https://")
    return v


def build_validate_production_security(config_logger):
    def _validate(self):
        if self.environment == "production":
            if self.jwt_secret_key == "change-me-in-production":
                raise ValueError(
                    "SECURITY: jwt_secret_key must be changed from default "
                    "in production. Set JWT_SECRET_KEY environment variable."
                )
            if self.cors_origins == ["*"]:
                config_logger.warning(
                    "SECURITY WARNING: cors_origins=['*'] in production. "
                    "Set CORS_ORIGINS to specific allowed origins."
                )
            if self.api_key and len(self.api_key) < 16:
                raise ValueError(
                    "SECURITY: api_key must be at least 16 characters in production. "
                    "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
                )
            if getattr(
                self, "enable_magic_link_auth", False
            ) and is_missing_or_placeholder_secret(
                getattr(self, "resend_api_key", None)
            ):
                raise ValueError(
                    "SECURITY: enable_magic_link_auth=True requires a real "
                    "RESEND_API_KEY in production. Magic Link must fail closed "
                    "instead of exposing dev verification URLs."
                )
            if getattr(self, "enable_google_oauth", False) and (
                is_missing_or_placeholder_secret(
                    getattr(self, "google_oauth_client_id", None)
                )
                or is_missing_or_placeholder_secret(
                    getattr(self, "google_oauth_client_secret", None)
                )
            ):
                raise ValueError(
                    "SECURITY: enable_google_oauth=True requires real "
                    "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
                    "in production."
                )
            if (
                getattr(self, "enable_distributed_magic_link_sessions", False)
                and not getattr(self, "valkey_url", "")
            ):
                config_logger.warning(
                    "CONFIG: enable_distributed_magic_link_sessions=True but valkey_url is empty — "
                    "store will silently fall back to in-memory (single-process only). "
                    "Set VALKEY_URL to enable cross-worker handoff."
                )
            if getattr(self, "enable_dev_login", False):
                raise ValueError(
                    "SECURITY: enable_dev_login=True is forbidden in production. "
                    "The dev-login endpoint mints JWTs without verifying any credential "
                    "and must never be reachable in a production environment. "
                    "Unset ENABLE_DEV_LOGIN or set ENVIRONMENT=development."
                )
        return self

    return _validate


def build_validate_cross_field_consistency(config_logger):
    def _validate(self):
        if self.rag_confidence_high <= self.rag_confidence_medium:
            raise ValueError(
                f"rag_confidence_high ({self.rag_confidence_high}) must be > "
                f"rag_confidence_medium ({self.rag_confidence_medium})"
            )
        if self.async_pool_min_size > self.async_pool_max_size:
            raise ValueError(
                f"async_pool_min_size ({self.async_pool_min_size}) must be <= "
                f"async_pool_max_size ({self.async_pool_max_size})"
            )
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be < "
                f"chunk_size ({self.chunk_size})"
            )
        if self.enable_tiktok_native_api and not self.enable_product_search:
            config_logger.warning(
                "enable_tiktok_native_api=True requires enable_product_search=True — TikTok API will be unused"
            )
        if self.enable_browser_scraping and not self.enable_product_search:
            config_logger.warning(
                "enable_browser_scraping=True requires enable_product_search=True — browser scraping will be unused"
            )
        if self.enable_privileged_sandbox:
            if self.sandbox_provider == "disabled":
                config_logger.warning(
                    "enable_privileged_sandbox=True but sandbox_provider='disabled' — dedicated sandbox executor will be unused"
                )
            if self.sandbox_provider == "opensandbox" and not self.opensandbox_base_url:
                config_logger.warning(
                    "sandbox_provider='opensandbox' but opensandbox_base_url is not set — OpenSandbox executor will not connect"
                )
        if (
            self.sandbox_provider == "opensandbox"
            and self.enable_browser_agent
            and not self.sandbox_allow_browser_workloads
        ):
            config_logger.warning(
                "enable_browser_agent=True with sandbox_provider='opensandbox' but sandbox_allow_browser_workloads=False — browser workloads stay outside the privileged sandbox"
            )
        if self.enable_oauth_token_store and not self.oauth_encryption_key:
            config_logger.warning(
                "enable_oauth_token_store=True but oauth_encryption_key is not set — tokens will not be encrypted"
            )
        if "facebook_group" in self.product_search_platforms:
            if not self.enable_browser_scraping:
                config_logger.warning(
                    "facebook_group in product_search_platforms requires enable_browser_scraping=True — group search disabled"
                )
            if not self.enable_facebook_cookie:
                config_logger.warning(
                    "facebook_group in product_search_platforms requires enable_facebook_cookie=True — group search disabled"
                )
        if self.enable_auto_group_discovery:
            if not self.enable_browser_scraping:
                config_logger.warning(
                    "enable_auto_group_discovery=True requires enable_browser_scraping=True"
                )
            if not self.enable_facebook_cookie:
                config_logger.warning(
                    "enable_auto_group_discovery=True requires enable_facebook_cookie=True"
                )
            if "facebook_group" not in self.product_search_platforms:
                config_logger.warning(
                    "enable_auto_group_discovery=True but 'facebook_group' not in product_search_platforms"
                )
        blocked_secrets = {
            "change-session-secret-in-production",
            "secret",
            "changeme",
            "your-secret-here",
            "supersecret",
        }
        if self.session_secret_key.lower() in blocked_secrets and self.environment == "production":
            raise ValueError(
                "SECURITY: session_secret_key must not be a default value in production. "
                "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if len(self.session_secret_key) < 32 and self.environment == "production":
            raise ValueError(
                f"SECURITY: session_secret_key must be at least 32 characters in production "
                f"(got {len(self.session_secret_key)}). "
                "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if len(set(self.session_secret_key)) < 10 and self.environment == "production":
            raise ValueError(
                "SECURITY: session_secret_key has low entropy (too few unique characters). "
                "Use a cryptographically random value."
            )
        if len(self.session_secret_key) < 32 and self.environment != "production":
            config_logger.warning(
                "SECURITY: session_secret_key is %d chars — should be at least 32 for secure OAuth CSRF state",
                len(self.session_secret_key),
            )
        if self.enable_google_oauth:
            if not self.google_oauth_client_id or not self.google_oauth_client_secret:
                config_logger.warning(
                    "enable_google_oauth=True but google_oauth_client_id/secret not set — OAuth will not work"
                )
        if self.enable_lms_integration and not self.lms_webhook_secret:
            config_logger.warning(
                "enable_lms_integration=True but lms_webhook_secret not set — webhooks will accept unsigned requests"
            )
        alpha = self.fact_retrieval_alpha
        beta = self.fact_retrieval_beta
        gamma = self.fact_retrieval_gamma
        if abs(alpha + beta + gamma - 1.0) > 0.01:
            raise ValueError(
                f"fact_retrieval alpha+beta+gamma must sum to 1.0, got {alpha + beta + gamma:.3f}"
            )
        return self

    return _validate


def sync_nested_groups_impl(self):
    object.__setattr__(
        self,
        "database",
        DatabaseConfig(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password,
            db=self.postgres_db,
            database_url=self.database_url,
            async_pool_min_size=self.async_pool_min_size,
            async_pool_max_size=self.async_pool_max_size,
        ),
    )
    object.__setattr__(
        self,
        "llm",
        LLMConfig(
            provider=self.llm_provider,
            failover_chain=self.llm_failover_chain,
            enable_failover=self.enable_llm_failover,
            primary_timeout_light_seconds=self.llm_primary_timeout_light_seconds,
            primary_timeout_moderate_seconds=self.llm_primary_timeout_moderate_seconds,
            primary_timeout_deep_seconds=self.llm_primary_timeout_deep_seconds,
            primary_timeout_structured_seconds=self.llm_primary_timeout_structured_seconds,
            primary_timeout_background_seconds=self.llm_primary_timeout_background_seconds,
            stream_keepalive_interval_seconds=self.llm_stream_keepalive_interval_seconds,
            stream_idle_timeout_seconds=self.llm_stream_idle_timeout_seconds,
            timeout_provider_overrides=loads_timeout_provider_overrides(
                getattr(self, "llm_timeout_provider_overrides", "{}")
            ),
            google_api_key=self.google_api_key,
            google_model=self.google_model,
            openai_api_key=self.openai_api_key,
            openai_base_url=self.openai_base_url,
            openrouter_api_key=self.openrouter_api_key,
            openrouter_base_url=self.openrouter_base_url,
            nvidia_api_key=self.nvidia_api_key,
            nvidia_base_url=self.nvidia_base_url,
            openai_model=self.openai_model,
            openai_model_advanced=self.openai_model_advanced,
            openrouter_model=self.openrouter_model,
            openrouter_model_advanced=self.openrouter_model_advanced,
            nvidia_model=self.nvidia_model,
            nvidia_model_advanced=self.nvidia_model_advanced,
            openrouter_model_fallbacks=self.openrouter_model_fallbacks,
            openrouter_provider_order=self.openrouter_provider_order,
            openrouter_allowed_providers=self.openrouter_allowed_providers,
            openrouter_ignored_providers=self.openrouter_ignored_providers,
            openrouter_allow_fallbacks=self.openrouter_allow_fallbacks,
            openrouter_require_parameters=self.openrouter_require_parameters,
            openrouter_data_collection=self.openrouter_data_collection,
            openrouter_zdr=self.openrouter_zdr,
            openrouter_provider_sort=self.openrouter_provider_sort,
            ollama_api_key=self.ollama_api_key,
            ollama_base_url=self.ollama_base_url,
            ollama_model=self.ollama_model,
            ollama_keep_alive=self.ollama_keep_alive,
            ollama_thinking_models=self.ollama_thinking_models,
            zhipu_api_key=self.zhipu_api_key,
            zhipu_base_url=self.zhipu_base_url,
            zhipu_model=self.zhipu_model,
            zhipu_model_advanced=self.zhipu_model_advanced,
        ),
    )
    object.__setattr__(
        self,
        "rag",
        RAGConfig(
            enable_corrective_rag=self.enable_corrective_rag,
            quality_mode=self.rag_quality_mode,
            confidence_high=self.rag_confidence_high,
            confidence_medium=self.rag_confidence_medium,
            max_iterations=self.rag_max_iterations,
            enable_reflection=self.rag_enable_reflection,
            early_exit_on_high_confidence=self.rag_early_exit_on_high_confidence,
            grading_threshold=self.multi_agent_grading_threshold,
            retrieval_grade_threshold=self.retrieval_grade_threshold,
            enable_answer_verification=self.enable_answer_verification,
        ),
    )
    object.__setattr__(
        self,
        "memory",
        MemoryConfig(
            enable_core_memory_block=self.enable_core_memory_block,
            core_memory_max_tokens=self.core_memory_max_tokens,
            core_memory_cache_ttl=self.core_memory_cache_ttl,
            max_user_facts=self.max_user_facts,
            max_injected_facts=self.max_injected_facts,
            fact_injection_min_confidence=self.fact_injection_min_confidence,
            enable_memory_decay=self.enable_memory_decay,
            enable_memory_pruning=self.enable_memory_pruning,
            enable_semantic_fact_retrieval=self.enable_semantic_fact_retrieval,
            fact_retrieval_alpha=self.fact_retrieval_alpha,
            fact_retrieval_beta=self.fact_retrieval_beta,
            fact_retrieval_gamma=self.fact_retrieval_gamma,
        ),
    )
    object.__setattr__(
        self,
        "product_search",
        ProductSearchConfig(
            enable_product_search=self.enable_product_search,
            serper_api_key=self.serper_api_key,
            apify_api_token=self.apify_api_token,
            max_results=self.product_search_max_results,
            timeout=self.product_search_timeout,
            platforms=list(self.product_search_platforms),
            max_iterations=self.product_search_max_iterations,
            scrape_timeout=self.product_search_scrape_timeout,
            max_scrape_pages=self.product_search_max_scrape_pages,
            enable_tiktok_native_api=self.enable_tiktok_native_api,
            enable_browser_scraping=self.enable_browser_scraping,
            browser_scraping_timeout=self.browser_scraping_timeout,
            enable_browser_screenshots=self.enable_browser_screenshots,
            browser_screenshot_quality=self.browser_screenshot_quality,
            enable_network_interception=self.enable_network_interception,
            network_interception_max_response_size=self.network_interception_max_response_size,
            enable_auto_group_discovery=self.enable_auto_group_discovery,
            auto_group_max_groups=self.facebook_auto_group_max_groups,
        ),
    )
    object.__setattr__(
        self,
        "thinking",
        ThinkingConfig(
            enabled=self.thinking_enabled,
            include_summaries=self.include_thought_summaries,
            budget_deep=self.thinking_budget_deep,
            budget_moderate=self.thinking_budget_moderate,
            budget_light=self.thinking_budget_light,
            budget_minimal=self.thinking_budget_minimal,
            gemini_level=self.gemini_thinking_level,
            enable_chain=self.enable_thinking_chain,
        ),
    )
    object.__setattr__(
        self,
        "character",
        CharacterConfig(
            enable_reflection=self.enable_character_reflection,
            reflection_interval=self.character_reflection_interval,
            enable_tools=self.enable_character_tools,
            reflection_threshold=self.character_reflection_threshold,
            experience_retention_days=self.character_experience_retention_days,
            enable_emotional_state=self.enable_emotional_state,
            emotional_decay_rate=self.emotional_decay_rate,
            enable_soul_emotion=self.enable_soul_emotion,
        ),
    )
    object.__setattr__(
        self,
        "cache",
        CacheConfig(
            enabled=self.semantic_cache_enabled,
            similarity_threshold=self.cache_similarity_threshold,
            response_ttl=self.cache_response_ttl,
            retrieval_ttl=self.cache_retrieval_ttl,
            max_entries=self.cache_max_response_entries,
            adaptive_ttl=self.cache_adaptive_ttl,
        ),
    )
    object.__setattr__(
        self,
        "living_agent",
        LivingAgentConfig(
            enabled=self.enable_living_agent,
            heartbeat_interval=self.living_agent_heartbeat_interval,
            active_hours_start=self.living_agent_active_hours_start,
            active_hours_end=self.living_agent_active_hours_end,
            local_model=self.living_agent_local_model,
            max_browse_items=self.living_agent_max_browse_items,
            enable_social_browse=self.living_agent_enable_social_browse,
            enable_skill_building=self.living_agent_enable_skill_building,
            enable_journal=self.living_agent_enable_journal,
            require_human_approval=self.living_agent_require_human_approval,
            max_actions_per_heartbeat=self.living_agent_max_actions_per_heartbeat,
            max_skills_per_week=self.living_agent_max_skills_per_week,
            max_searches_per_heartbeat=self.living_agent_max_searches_per_heartbeat,
            max_daily_cycles=self.living_agent_max_daily_cycles,
            callmebot_api_key=self.living_agent_callmebot_api_key,
            notification_channel=self.living_agent_notification_channel,
            enable_skill_learning=self.living_agent_enable_skill_learning,
            quiz_questions_per_session=self.living_agent_quiz_questions_per_session,
            review_confidence_weight=self.living_agent_review_confidence_weight,
        ),
    )
    object.__setattr__(
        self,
        "lms",
        LMSIntegrationConfig(
            enabled=self.enable_lms_integration,
            base_url=self.lms_base_url,
            service_token=self.lms_service_token,
            webhook_secret=self.lms_webhook_secret,
            api_timeout=self.lms_api_timeout,
        ),
    )
    return self
