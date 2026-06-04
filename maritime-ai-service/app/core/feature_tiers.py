"""Feature-flag tier registry for architectural simplification.

This module gives the codebase one place to answer a basic question:
is a feature part of the core product path, a supported optional surface,
an active experiment, or a dormant expansion zone?
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from app.core.config import Settings


class FeatureTier(StrEnum):
    FOUNDATIONAL = "foundational"
    PRODUCTION_SUPPORTED = "production_supported"
    EXPERIMENTAL = "experimental"
    DORMANT = "dormant"


TIER_DESCRIPTIONS: Final[dict[FeatureTier, str]] = {
    FeatureTier.FOUNDATIONAL: (
        "Core execution path and baseline safety features."
    ),
    FeatureTier.PRODUCTION_SUPPORTED: (
        "Supported non-core capabilities with an active product role."
    ),
    FeatureTier.EXPERIMENTAL: (
        "Active bets that are useful but not yet architectural defaults."
    ),
    FeatureTier.DORMANT: (
        "Legacy, low-exercise, or intentionally deferred surfaces."
    ),
}


def _settings_feature_flags() -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in Settings.model_fields
            if (
                name.startswith("enable_")
                or name.startswith("living_agent_enable_")
            )
        )
    )


FEATURE_FLAGS: Final[tuple[str, ...]] = _settings_feature_flags()

FEATURE_TIER_GROUPS: Final[dict[FeatureTier, frozenset[str]]] = {
    FeatureTier.FOUNDATIONAL: frozenset(
        {
            "enable_agent_handoffs",
            "enable_agentic_loop",
            "enable_answer_verification",
            "enable_artifacts",
            "enable_auth_audit",
            "enable_character_reflection",
            "enable_character_tools",
            "enable_core_memory_block",
            "enable_corrective_rag",
            "enable_enhanced_extraction",
            "enable_llm_failover",
            "enable_llm_model_health_probes",
            "enable_memory_decay",
            "enable_memory_pruning",
            "enable_network_interception",
            "enable_org_membership_check",
            "enable_preview",
            "enable_reranker_grading",
            "enable_runner_hooks",
            "enable_semantic_fact_retrieval",
            "enable_serper_web_search",
            "enable_structured_outputs",
            "enable_text_ingestion",
            "enable_websocket",
        }
    ),
    FeatureTier.PRODUCTION_SUPPORTED: frozenset(
        {
            "enable_admin_module",
            "enable_code_gen_visuals",
            "enable_code_studio_streaming",
            "enable_completeness_guard",
            "enable_cross_platform_identity",
            "enable_distributed_magic_link_sessions",
            "enable_google_oauth",
            "enable_host_actions",
            "enable_host_context",
            "enable_host_skills",
            "enable_knowledge_visualization",
            "enable_living_agent",
            "enable_living_continuity",
            "enable_llm_code_gen_visuals",
            "enable_lms_integration",
            "enable_lms_token_exchange",
            "enable_magic_link_auth",
            "enable_mcp_client",
            "enable_mcp_server",
            "enable_mcp_tool_server",
            "enable_multi_tenant",
            "enable_org_admin",
            "enable_org_knowledge",
            "enable_pointy_voice",
            "enable_real_code_streaming",
            "enable_site_playbooks",
            "enable_structured_visuals",
            "living_agent_enable_journal",
        }
    ),
    FeatureTier.EXPERIMENTAL: frozenset(
        {
            "enable_adaptive_preferences",
            "enable_adaptive_rag",
            "enable_advanced_excel_report",
            "enable_background_tasks",
            "enable_browser_agent",
            "enable_browser_scraping",
            "enable_browser_screenshots",
            "enable_chart_tools",
            "enable_chinese_platform_search",
            "enable_code_execution",
            "enable_concurrent_tool_execution",
            "enable_conservative_fast_routing",
            "enable_contact_extraction",
            "enable_crawl4ai",
            "enable_cross_platform_memory",
            "enable_curated_product_cards",
            "enable_dealer_search",
            "enable_deliberate_reasoning",
            "enable_dev_login",
            "enable_emotional_state",
            "enable_facebook_cookie",
            "enable_filesystem_tools",
            "enable_graph_rag",
            "enable_hyde",
            "enable_identity_core",
            "enable_intelligent_tool_selection",
            "enable_international_search",
            "enable_jina_reader",
            "enable_jti_denylist",
            "enable_langsmith",
            "enable_living_core_contract",
            "enable_living_visual_cognition",
            "enable_memory_blocks",
            "enable_narrative_context",
            "enable_natural_conversation",
            "enable_privileged_sandbox",
            "enable_product_image_enrichment",
            "enable_product_preview_cards",
            "enable_product_search",
            "enable_query_planner",
            "enable_rich_page_context",
            "enable_rls",
            "enable_scheduler",
            "enable_scrapling",
            "enable_eval_recording",
            "enable_casual_fast_path",
            "enable_episodic_retrieval",
            "enable_native_runtime",
            "enable_native_stream_dispatch",
            "enable_otlp_export",
            "enable_stream_smoother",
            "enable_prometheus_metrics",
            "enable_session_event_log",
            "enable_subagent_isolation",
            "enable_skill_creation",
            "enable_skill_export",
            "enable_skill_metrics",
            "enable_skill_tool_bridge",
            "enable_soul_bridge",
            "enable_soul_emotion",
            "enable_temporal_memory",
            "enable_thinking_chain",
            "enable_tiktok_native_api",
            "enable_unified_client",
            "enable_unified_skill_index",
            "enable_vision",
            "enable_visual_memory",
            "enable_visual_page_capture",
            "enable_visual_product_search",
            "enable_visual_rag",
            "enable_wiii_connect_composio",
            "enable_wiii_connect_composio_apply_execute",
            "enable_wiii_connect_composio_readonly_execute",
            "living_agent_enable_autonomy_graduation",
            "living_agent_enable_briefing",
            "living_agent_enable_dynamic_goals",
            "living_agent_enable_proactive_messaging",
            "living_agent_enable_routine_tracking",
            "living_agent_enable_skill_building",
            "living_agent_enable_skill_learning",
            "living_agent_enable_social_browse",
            "living_agent_enable_weather",
        }
    ),
    FeatureTier.DORMANT: frozenset(
        {
            "enable_auto_group_discovery",
            "enable_cross_soul_query",
            "enable_messenger_webhook",
            "enable_neo4j",
            "enable_oauth_token_store",
            "enable_subagent_architecture",
            "enable_telegram",
            "enable_zalo",
            "enable_zalo_webhook",
        }
    ),
}


FEATURE_TIER_BY_FLAG: Final[dict[str, FeatureTier]] = {
    flag: tier
    for tier, flags in FEATURE_TIER_GROUPS.items()
    for flag in flags
}


def get_feature_tier(flag_name: str) -> FeatureTier | None:
    """Return the architectural tier for a feature flag."""
    return FEATURE_TIER_BY_FLAG.get(flag_name)


def flags_for_tier(tier: FeatureTier) -> tuple[str, ...]:
    """Return sorted flag names for a tier."""
    return tuple(sorted(FEATURE_TIER_GROUPS[tier]))


def get_unclassified_feature_flags() -> tuple[str, ...]:
    """Return any feature flags in Settings that do not yet have a tier."""
    return tuple(sorted(set(FEATURE_FLAGS) - set(FEATURE_TIER_BY_FLAG)))


def get_duplicate_feature_classifications(
) -> dict[str, tuple[FeatureTier, ...]]:
    """Return flags assigned to more than one tier."""
    seen: dict[str, list[FeatureTier]] = {}
    for tier, flags in FEATURE_TIER_GROUPS.items():
        for flag in flags:
            seen.setdefault(flag, []).append(tier)

    return {
        flag: tuple(tiers)
        for flag, tiers in seen.items()
        if len(tiers) > 1
    }


def summarize_feature_tiers() -> dict[str, tuple[str, ...]]:
    """Return a stable summary that can be used by docs or admin tooling."""
    return {
        tier.value: flags_for_tier(tier)
        for tier in FeatureTier
    }
