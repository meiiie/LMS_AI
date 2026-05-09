"""Pydantic Settings entrypoint with backward-compatible flat fields and nested views."""
import logging
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config._settings_runtime import (
    refresh_nested_views_impl,
)
from app.core.config._settings_validation import (
    build_validate_cross_field_consistency,
    build_validate_production_security,
    normalize_string_list_values,
    sync_nested_groups_impl,
    validate_choice_value,
    validate_embedding_dimensions_value,
    validate_environment_value,
    validate_google_compat_url_value,
    validate_grading_threshold_value,
    validate_jwt_expire_value,
    validate_llm_provider_value,
    validate_log_format_value,
    validate_log_level_value,
    validate_openrouter_data_collection_value,
    validate_openrouter_provider_sort_value,
    validate_positive_value,
    validate_postgres_port_value,
    validate_range_value,
    validate_similarity_threshold_value,
    validate_url_field_value,
)
from app.core.config._settings_base_fields import BaseSettingsFieldsMixin
from app.core.config._settings_feature_fields import FeatureSettingsMixin
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
_config_logger = logging.getLogger(__name__)

class Settings(BaseSettingsFieldsMixin, FeatureSettingsMixin, BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # Sprint 154: Nested Config Groups (synced from flat fields)
    # =========================================================================
    # These provide structured access: settings.llm.google_api_key
    # Flat fields remain the source of truth for env var loading.
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, exclude=True)
    llm: LLMConfig = Field(default_factory=LLMConfig, exclude=True)
    rag: RAGConfig = Field(default_factory=RAGConfig, exclude=True)
    memory: MemoryConfig = Field(default_factory=MemoryConfig, exclude=True)
    product_search: ProductSearchConfig = Field(default_factory=ProductSearchConfig, exclude=True)
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig, exclude=True)
    character: CharacterConfig = Field(default_factory=CharacterConfig, exclude=True)
    cache: CacheConfig = Field(default_factory=CacheConfig, exclude=True)
    living_agent: LivingAgentConfig = Field(default_factory=LivingAgentConfig, exclude=True)
    lms: LMSIntegrationConfig = Field(default_factory=LMSIntegrationConfig, exclude=True)

    validate_environment = field_validator("environment")(validate_environment_value)
    validate_log_level = field_validator("log_level")(validate_log_level_value)
    validate_jwt_expire = field_validator("jwt_expire_minutes")(validate_jwt_expire_value)
    validate_port = field_validator("postgres_port")(validate_postgres_port_value)
    validate_rate_limit_requests = field_validator("rate_limit_requests")(
        lambda cls, v: validate_positive_value("rate_limit_requests", v)
    )
    validate_rate_limit_window = field_validator("rate_limit_window_seconds")(
        lambda cls, v: validate_positive_value("rate_limit_window_seconds", v)
    )
    validate_scheduler_poll_interval = field_validator("scheduler_poll_interval")(
        lambda cls, v: validate_range_value("scheduler_poll_interval", v, 10, 3600)
    )
    validate_scheduler_max_concurrent = field_validator("scheduler_max_concurrent")(
        lambda cls, v: validate_range_value("scheduler_max_concurrent", v, 1, 20)
    )
    validate_async_pool_min_size = field_validator("async_pool_min_size")(
        lambda cls, v: validate_range_value("async_pool_min_size", v, 1, 100)
    )
    validate_async_pool_max_size = field_validator("async_pool_max_size")(
        lambda cls, v: validate_range_value("async_pool_max_size", v, 1, 100)
    )
    validate_chunk_size = field_validator("chunk_size")(
        lambda cls, v: validate_range_value("chunk_size", v, 100, 10000)
    )
    validate_chunk_overlap = field_validator("chunk_overlap")(
        lambda cls, v: validate_range_value("chunk_overlap", v, 0, 5000)
    )
    validate_code_execution_timeout = field_validator("code_execution_timeout")(
        lambda cls, v: validate_range_value("code_execution_timeout", v, 1, 300)
    )
    validate_vision_image_quality = field_validator("vision_image_quality")(
        lambda cls, v: validate_range_value("vision_image_quality", v, 1, 100)
    )
    validate_similarity_thresholds = field_validator(
        "similarity_threshold",
        "fact_similarity_threshold",
        "memory_duplicate_threshold",
        "memory_related_threshold",
        "cache_similarity_threshold",
        "quality_skip_threshold",
        "insight_duplicate_threshold",
        "insight_contradiction_threshold",
        "rag_confidence_high",
        "rag_confidence_medium",
    )(validate_similarity_threshold_value)
    validate_grading_thresholds = field_validator(
        "multi_agent_grading_threshold",
        "retrieval_grade_threshold",
    )(validate_grading_threshold_value)

    validate_llm_provider = field_validator("llm_provider")(validate_llm_provider_value)
    validate_embedding_provider = field_validator("embedding_provider")(
        lambda cls, v: validate_choice_value(
            "embedding_provider",
            v,
            ["google", "openai", "openrouter", "ollama", "zhipu", "auto"],
        )
    )
    validate_vision_provider = field_validator("vision_provider")(
        lambda cls, v: validate_choice_value(
            "vision_provider",
            v,
            ["google", "openai", "openrouter", "nvidia", "ollama", "zhipu", "auto"],
        )
    )
    validate_vision_capability_provider = field_validator(
        "vision_describe_provider",
        "vision_ocr_provider",
        "vision_grounded_provider",
    )(
        lambda cls, v: validate_choice_value(
            "vision_capability_provider",
            v,
            ["google", "openai", "openrouter", "nvidia", "ollama", "zhipu", "auto"],
        )
    )
    validate_sandbox_provider = field_validator("sandbox_provider")(
        lambda cls, v: validate_choice_value(
            "sandbox_provider",
            v,
            ["disabled", "local_subprocess", "opensandbox"],
        )
    )
    validate_opensandbox_network_mode = field_validator("opensandbox_network_mode")(
        lambda cls, v: validate_choice_value(
            "opensandbox_network_mode",
            v,
            ["disabled", "bridge", "egress"],
        )
    )
    validate_rag_quality_mode = field_validator("rag_quality_mode")(
        lambda cls, v: validate_choice_value("rag_quality_mode", v, ["speed", "balanced", "quality"])
    )
    validate_gemini_thinking_level = field_validator("gemini_thinking_level")(
        lambda cls, v: validate_choice_value(
            "gemini_thinking_level",
            v,
            ["minimal", "low", "medium", "high"],
        )
    )
    validate_log_format = field_validator("log_format")(validate_log_format_value)
    validate_embedding_dimensions = field_validator("embedding_dimensions")(validate_embedding_dimensions_value)
    validate_cache_max_response_entries = field_validator("cache_max_response_entries")(
        lambda cls, v: validate_range_value("cache_max_response_entries", v, 100, 1_000_000)
    )
    validate_batch_sizes = field_validator("contextual_rag_batch_size", "entity_extraction_batch_size")(
        lambda cls, v: validate_range_value("batch_size", v, 1, 50)
    )
    validate_agentic_loop_max_steps = field_validator("agentic_loop_max_steps")(
        lambda cls, v: validate_range_value("agentic_loop_max_steps", v, 1, 20)
    )
    validate_rag_max_iterations = field_validator("rag_max_iterations")(
        lambda cls, v: validate_range_value("rag_max_iterations", v, 1, 10)
    )
    validate_url_fields = field_validator(
        "ollama_base_url",
        "openai_base_url",
        "openrouter_base_url",
        "nvidia_base_url",
    )(validate_url_field_value)

    normalize_string_lists = field_validator(
        "embedding_failover_chain",
        "vision_failover_chain",
        "openrouter_model_fallbacks",
        "openrouter_provider_order",
        "openrouter_allowed_providers",
        "openrouter_ignored_providers",
    )(normalize_string_list_values)
    validate_openrouter_data_collection = field_validator("openrouter_data_collection")(
        validate_openrouter_data_collection_value
    )
    validate_openrouter_provider_sort = field_validator("openrouter_provider_sort")(
        validate_openrouter_provider_sort_value
    )
    validate_google_compat_url = field_validator("google_openai_compat_url")(validate_google_compat_url_value)

    validate_production_security = model_validator(mode="after")(
        build_validate_production_security(_config_logger)
    )
    validate_cross_field_consistency = model_validator(mode="after")(
        build_validate_cross_field_consistency(_config_logger)
    )
    _sync_nested_groups = model_validator(mode="after")(sync_nested_groups_impl)
    refresh_nested_views = refresh_nested_views_impl


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export settings instance for convenience
settings = get_settings()
