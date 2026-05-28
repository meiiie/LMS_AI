"""Large feature-field groups extracted from the settings shell."""

from typing import Optional

from pydantic import Field


class FeatureSettingsMixin:
    """Feature-heavy settings groups kept separate from validators/runtime helpers."""

    # Living Memory System
    enable_core_memory_block: bool = Field(default=True, description="Compile structured user profile for all agents")
    core_memory_max_tokens: int = Field(default=800, ge=100, le=5000, description="Max tokens for core memory profile block")
    core_memory_cache_ttl: int = Field(default=300, ge=10, le=3600, description="Core memory cache TTL in seconds")
    enable_memory_decay: bool = Field(default=True, description="Enable Ebbinghaus importance decay on facts")
    enable_enhanced_extraction: bool = Field(default=True, description="Enable Mem0-style 15-type fact extraction")

    # Sprint 122: Configurable memory constants
    max_user_facts: int = Field(default=50, ge=1, le=500, description="Maximum user facts per user before eviction")
    character_cache_ttl: int = Field(default=60, ge=5, le=3600, description="Character block cache TTL in seconds")
    memory_prune_threshold: float = Field(default=0.1, ge=0.0, le=1.0, description="Prune facts with effective importance below this")
    fact_injection_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Minimum confidence for fact injection into prompt")
    max_injected_facts: int = Field(default=5, ge=1, le=50, description="Maximum facts injected into system prompt")
    enable_memory_pruning: bool = Field(default=True, description="Enable active memory pruning during extraction")

    # Character Reflection Engine
    enable_character_reflection: bool = Field(default=True, description="Enable periodic character self-reflection")
    character_reflection_interval: int = Field(default=5, ge=1, le=50, description="Reflect after every N conversations")
    enable_character_tools: bool = Field(default=True, description="Enable character self-editing tools")
    character_reflection_threshold: float = Field(default=5.0, description="Importance sum threshold for early reflection")
    character_experience_retention_days: int = Field(default=90, description="Delete experiences older than N days")
    character_experience_keep_min: int = Field(default=100, description="Always keep at least N most recent experiences")

    # Stanford Generative Agents Memory Retrieval
    stanford_recency_weight: float = Field(default=0.3, description="Weight for recency in Stanford memory ranking")
    stanford_importance_weight: float = Field(default=0.3, description="Weight for importance in Stanford memory ranking")
    stanford_relevance_weight: float = Field(default=0.4, description="Weight for relevance in Stanford memory ranking")

    # SOTA Personality System
    identity_anchor_interval: int = Field(default=6, ge=3, le=50, description="Re-inject identity anchor every N responses")
    enable_emotional_state: bool = Field(default=False, description="Enable 2D mood state machine")
    emotional_decay_rate: float = Field(default=0.15, ge=0.0, le=1.0, description="Rate of mood decay toward neutral")

    # Soul Emotion
    enable_soul_emotion: bool = Field(default=False, description="Enable LLM inline emotion tags for avatar")
    soul_emotion_buffer_bytes: int = Field(default=512, ge=256, le=2048, description="Max bytes to buffer for soul emotion extraction")

    # Pointy Voice (ElevenLabs)
    enable_pointy_voice: bool = Field(
        default=True,
        description="Enable optional Pointy voice synthesis through the backend voice proxy",
    )
    elevenlabs_api_key: Optional[str] = Field(
        default=None,
        description="ElevenLabs API key for backend-proxied text-to-speech",
        repr=False,
    )
    elevenlabs_voice_id: str = Field(
        default="JBFqnCBsd6RMkjVDRZzb",
        description="ElevenLabs voice id used for Pointy captions",
    )
    elevenlabs_model_id: str = Field(
        default="eleven_flash_v2_5",
        description="ElevenLabs TTS model id; Flash v2.5 is tuned for low-latency UI speech",
    )
    elevenlabs_output_format: str = Field(
        default="mp3_22050_32",
        description="ElevenLabs output format for short Pointy captions",
    )

    # Knowledge Management
    cross_domain_search: bool = Field(default=True, description="Search all domains with soft boost")
    domain_boost_score: float = Field(default=0.15, ge=0.0, le=1.0, description="RRF boost for same-domain results")
    enable_text_ingestion: bool = Field(default=True, description="Allow text/markdown ingestion via API")
    max_ingestion_size_mb: int = Field(default=50, ge=1, le=500, description="Maximum file size for ingestion in MB")

    # Semantic Fact Retrieval
    enable_semantic_fact_retrieval: bool = Field(default=True, description="Use embedding similarity for fact retrieval")
    fact_retrieval_alpha: float = Field(default=0.3, description="Importance weight in combined fact scoring")
    fact_retrieval_beta: float = Field(default=0.5, description="Cosine similarity weight in combined fact scoring")
    fact_retrieval_gamma: float = Field(default=0.2, description="Recency weight in combined fact scoring")
    fact_min_similarity: float = Field(default=0.3, description="Minimum cosine similarity for semantic fact retrieval")

    # LangSmith Observability
    enable_langsmith: bool = Field(default=False, description="Enable LangSmith tracing")
    langsmith_api_key: Optional[str] = Field(default=None, description="LangSmith API key", repr=False)
    langsmith_project: str = Field(default="wiii", description="LangSmith project name")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com", description="LangSmith API endpoint")

    # Multi-Phase Thinking Chain
    enable_thinking_chain: bool = Field(default=False, description="Enable multi-phase thinking chain")

    # Living Agent System (Sprint 170)
    enable_living_agent: bool = Field(default=False, description="Enable Wiii's autonomous living agent system")
    living_agent_heartbeat_interval: int = Field(default=1800, ge=300, le=86400, description="Heartbeat interval in seconds (default 30 min)")
    living_agent_active_hours_start: int = Field(default=8, ge=0, le=23, description="Start hour for active period (UTC+7)")
    living_agent_active_hours_end: int = Field(default=23, ge=0, le=23, description="End hour for active period (UTC+7)")
    living_agent_local_model: str = Field(
        default="qwen3:4b-instruct-2507-q4_K_M",
        description="Local Ollama model for autonomous tasks",
    )
    living_agent_max_browse_items: int = Field(default=10, ge=1, le=50, description="Max items to process per browsing session")
    living_agent_enable_social_browse: bool = Field(default=False, description="Allow Wiii to browse social media autonomously")
    living_agent_enable_skill_building: bool = Field(default=False, description="Allow Wiii to learn new skills autonomously")
    living_agent_enable_journal: bool = Field(default=True, description="Enable daily journal writing")
    living_agent_require_human_approval: bool = Field(default=True, description="Require human approval for external actions")
    living_agent_max_actions_per_heartbeat: int = Field(default=3, ge=1, le=10, description="Max actions per heartbeat cycle")
    living_agent_max_skills_per_week: int = Field(default=5, ge=1, le=20, description="Max new skills to discover per week")
    living_agent_max_searches_per_heartbeat: int = Field(default=3, ge=1, le=10, description="Max web searches per heartbeat cycle")
    living_agent_max_daily_cycles: int = Field(default=48, ge=1, le=200, description="Max heartbeat cycles per 24h")
    living_agent_callmebot_api_key: Optional[str] = Field(default=None, description="CallMeBot API key for Facebook Messenger notifications", repr=False)
    living_agent_notification_channel: str = Field(default="websocket", description="Notification channel for heartbeat discoveries (websocket, telegram, messenger)")

    # Soul AGI: Weather (Phase 1B)
    living_agent_enable_weather: bool = Field(default=False, description="Enable weather awareness via OpenWeatherMap")
    living_agent_weather_api_key: Optional[str] = Field(default=None, description="OpenWeatherMap API key", repr=False)
    living_agent_weather_city: str = Field(default="Ho Chi Minh City", description="Default city for weather queries")

    # Soul AGI: Briefing (Phase 2A)
    living_agent_enable_briefing: bool = Field(default=False, description="Enable scheduled briefings (morning/midday/evening)")
    living_agent_briefing_channels: str = Field(default='["messenger"]', description="JSON list of channels for briefing delivery")
    living_agent_briefing_users: str = Field(default="[]", description="JSON list of user_ids to receive briefings")

    # Soul AGI: Routine Tracking (Phase 3B)
    living_agent_enable_routine_tracking: bool = Field(default=False, description="Track user behavior patterns for personalization")

    # Soul AGI: Dynamic Goals (Phase 4B)
    living_agent_enable_dynamic_goals: bool = Field(default=False, description="Enable evolving goal management")

    # Soul AGI: Proactive Messaging (Phase 5A)
    living_agent_enable_proactive_messaging: bool = Field(default=False, description="Allow Wiii to send messages proactively")
    living_agent_max_proactive_per_day: int = Field(default=3, ge=0, le=10, description="Max unsolicited messages per day per user")
    living_agent_proactive_quiet_start: int = Field(default=23, ge=0, le=23, description="Quiet hours start (UTC+7, no proactive messages)")
    living_agent_proactive_quiet_end: int = Field(default=5, ge=0, le=23, description="Quiet hours end (UTC+7)")

    # Soul AGI: Autonomy Graduation (Phase 5B)
    living_agent_autonomy_level: int = Field(default=0, ge=0, le=3, description="Current autonomy level (0=supervised, 3=full trust)")
    living_agent_enable_autonomy_graduation: bool = Field(default=False, description="Enable automatic trust level graduation")

    # Sprint 210: Living Continuity — conversations feed into Living Agent emotion/memory/episodes
    enable_living_continuity: bool = Field(default=False, description="Chat conversations feed into Living Agent emotion/memory/episodes (requires enable_living_agent)")

    # Sprint 210c: Relationship Tiers — emotion impact weighted by user closeness
    living_agent_creator_user_ids: str = Field(default="", description="Comma-separated user IDs treated as Tier 0 (creator). Plus anyone with role=admin")
    living_agent_known_user_threshold: int = Field(default=50, ge=5, le=1000, description="Minimum total_messages to qualify as Tier 1 (known user)")

    # Sprint 219: Adaptive Preference Learning — auto-infer learning preferences from conversation
    enable_adaptive_preferences: bool = Field(default=False, description="Enable behavioral inference rules in FactExtractor to auto-learn user preferences from conversation patterns")

    # Sprint 177: Real Skill Learning via Browsing
    living_agent_enable_skill_learning: bool = Field(default=False, description="Enable browsing→skill learning pipeline with SM-2 spaced repetition")
    living_agent_quiz_questions_per_session: int = Field(default=3, ge=1, le=10, description="Number of quiz questions per practice session")
    living_agent_review_confidence_weight: float = Field(default=0.3, ge=0.0, le=1.0, description="EMA alpha weight for quiz→confidence updates")

    # Sprint 177: Cross-Platform Memory Sync
    enable_cross_platform_memory: bool = Field(default=False, description="Enable memory merge on OTP link + cross-platform context injection")
    cross_platform_context_max_items: int = Field(default=3, ge=1, le=10, description="Max items in cross-platform activity summary")

    # Facebook Messenger (for webhooks)
    facebook_verify_token: Optional[str] = Field(default=None, description="Facebook webhook verification token", repr=False)
    facebook_page_access_token: Optional[str] = Field(default=None, description="Facebook Page access token for Send API", repr=False)
    facebook_graph_api_version: str = Field(default="v22.0", description="Facebook Graph API version (Sprint 188)")

    # Zalo OA
    zalo_oa_access_token: Optional[str] = Field(default=None, description="Zalo OA access token", repr=False)
    zalo_oa_secret_key: Optional[str] = Field(default=None, description="Zalo OA secret key for MAC verification", repr=False)

    # Preview System (Sprint 166)
    enable_preview: bool = Field(default=True, description="Rich preview cards in streaming responses")

    # Artifact System (Sprint 167)
    enable_artifacts: bool = Field(default=True, description="Interactive artifacts (code execution, file preview)")

    # Product Search Agent
    enable_product_search: bool = Field(default=True, description="Enable product search agent")
    serper_api_key: Optional[str] = Field(default=None, description="Serper.dev API key", repr=False)
    apify_api_token: Optional[str] = Field(default=None, description="Apify API token", repr=False)
    brave_api_key: Optional[str] = Field(default=None, description="Brave Search API key (free 2k/mo, more reliable than DDG)", repr=False)
    searxng_url: Optional[str] = Field(
        default="http://searxng:8080",
        description="SearXNG meta-search base URL (self-hosted, AGPL-3.0). "
                    "Empty disables SearXNG primary; falls back to Brave/DDG.",
    )

    # Phase 35 — per-provider client-side RPM throttle. 0 disables.
    nvidia_rpm_limit: int = Field(
        default=0, ge=0, le=10000,
        description="Cap NVIDIA NIM requests per minute (0=disabled). "
                    "Recommended 30-60 for free tier to avoid 429.",
    )
    google_rpm_limit: int = Field(
        default=0, ge=0, le=10000,
        description="Cap Google Gemini requests per minute (0=disabled).",
    )

    # Site Playbooks (Firecrawl pattern)
    enable_site_playbooks: bool = Field(default=True, description="Enable YAML-driven site playbooks for scraping config")
    playbooks_hot_reload: bool = Field(default=False, description="Reload playbooks on every request (dev only)")

    # Data Completeness Guard (Firecrawl pattern)
    enable_completeness_guard: bool = Field(default=True, description="Check result completeness before product search synthesis")
    completeness_min_results: int = Field(default=3, ge=1, le=20, description="Minimum results for completeness pass")
    completeness_min_platforms: int = Field(default=2, ge=1, le=10, description="Minimum distinct platforms for completeness")
    completeness_max_extra_rounds: int = Field(default=2, ge=0, le=5, description="Max extra search rounds from guard")

    # Skill Export (Firecrawl pattern)
    enable_skill_export: bool = Field(default=True, description="Auto-generate YAML skills from successful conversations")
    skill_export_min_tool_calls: int = Field(default=2, ge=1, le=10, description="Min tool calls to trigger skill export")
    skill_export_max_per_day: int = Field(default=5, ge=0, le=50, description="Max auto-generated skills per day")
    product_search_max_results: int = Field(default=30, ge=1, le=100, description="Max results per platform search")
    product_search_timeout: int = Field(default=30, ge=5, le=120, description="Timeout for each platform search")

    # Sprint 149: Search Platform Plugin Architecture
    product_search_platforms: list = Field(
        default=["google_shopping", "shopee", "tiktok_shop", "lazada", "facebook_marketplace", "all_web", "instagram", "websosanh"],
        description="List of enabled search platform IDs",
    )
    enable_tiktok_native_api: bool = Field(default=False, description="Enable TikTok Research API")
    tiktok_client_key: Optional[str] = Field(default=None, description="TikTok Developer Portal client key")
    tiktok_client_secret: Optional[str] = Field(default=None, description="TikTok Developer Portal client secret", repr=False)

    # Sprint 150: Deep Product Search
    product_search_max_iterations: int = Field(default=15, ge=5, le=30, description="Max ReAct iterations")
    product_search_scrape_timeout: int = Field(default=10, ge=3, le=30, description="Timeout for scraping product pages")
    product_search_max_scrape_pages: int = Field(default=10, ge=1, le=30, description="Max pages to scrape per session")

    # Browser Scraping
    enable_browser_scraping: bool = Field(default=False, description="Enable Playwright headless browser")
    browser_scraping_timeout: int = Field(default=15, ge=3, le=60, description="Timeout for browser page load")

    # Browser Screenshots
    enable_browser_screenshots: bool = Field(default=False, description="Stream browser screenshots to UI")
    browser_screenshot_quality: int = Field(default=40, description="JPEG quality for screenshots (10-90)")

    # Facebook Cookie Login (Sprint 154)
    enable_facebook_cookie: bool = Field(default=False, description="Allow Facebook cookie injection for logged-in search")

    # Facebook Group Search (Sprint 155)
    facebook_group_max_scrolls: int = Field(default=10, ge=3, le=20, description="Max scroll iterations for FB group search")
    facebook_group_scroll_delay: float = Field(default=2.5, ge=1.0, le=5.0, description="Delay between scrolls in group search (seconds)")
    facebook_scroll_max_scrolls: int = Field(default=8, ge=3, le=20, description="Max scroll iterations for general FB search (upgraded from 3)")

    # Network Interception (Sprint 156)
    enable_network_interception: bool = Field(default=True, description="Intercept GraphQL responses for structured product data")
    network_interception_max_response_size: int = Field(default=5_000_000, ge=100_000, le=50_000_000, description="Skip responses larger than this (bytes)")

    # Auto Group Discovery (Sprint 157)
    enable_auto_group_discovery: bool = Field(default=False, description="Auto-discover and search FB groups by product category")
    facebook_auto_group_max_groups: int = Field(default=3, ge=1, le=5, description="Max groups to auto-search per query")

    # Sprint 190: Enhanced Scraping Backends
    enable_crawl4ai: bool = Field(default=False, description="Enable Crawl4AI scraping backend (general web crawling + AI extraction)")
    crawl4ai_headless: bool = Field(default=True, description="Run Crawl4AI browser in headless mode")
    crawl4ai_use_llm_extraction: bool = Field(default=False, description="Use LLM extraction in Crawl4AI (costs tokens)")
    enable_scrapling: bool = Field(default=False, description="Enable Scrapling stealth scraping backend (anti-bot bypass)")
    scrapling_stealth_mode: bool = Field(default=True, description="Enable Scrapling TLS fingerprint spoofing for Cloudflare bypass")
    # Sprint 195: Jina Reader fallback
    enable_jina_reader: bool = Field(default=False, description="Enable Jina AI Reader as lightweight web-to-markdown fallback")

    # Sprint 196: Professional Product Sourcing
    enable_dealer_search: bool = Field(default=False, description="Enable dealer/distributor discovery via DuckDuckGo + Jina Reader")
    enable_contact_extraction: bool = Field(default=False, description="Enable contact info extraction from web pages (phone, Zalo, email)")
    enable_international_search: bool = Field(default=False, description="Enable international product search with USD→VND conversion")
    enable_advanced_excel_report: bool = Field(default=False, description="Enable 3-sheet Excel reports with dealer contacts and recommendations")
    usd_vnd_exchange_rate: float = Field(default=25500.0, description="USD to VND exchange rate for international price conversion")
    exchange_rate_overrides: dict = Field(
        default_factory=dict,
        description="Override exchange rates. Keys=ISO currency, values=to-USD factor. E.g. {'EUR': 1.10}",
    )

    # Sprint 200: Product Preview Cards (carousel in UI)
    enable_product_preview_cards: bool = Field(
        default=True,
        description="Emit SSE preview events for product search results (card carousel in UI)",
    )
    product_preview_max_cards: int = Field(
        default=20, ge=1, le=50,
        description="Max product preview cards emitted per search session",
    )

    # Sprint 200: Visual Product Search (image → product identification)
    enable_visual_product_search: bool = Field(
        default=False,
        description="Enable Vision LLM product identification from uploaded images",
    )
    visual_product_search_provider: str = Field(
        default="google",
        description="Vision provider for product identification: google, openai (extensible via _PROVIDER_REGISTRY)",
    )
    visual_product_search_model: str = Field(
        default="",
        description=(
            "Vision model for product identification. "
            "Empty = provider default. "
            "Google options: gemini-3.1-flash-lite-preview (default, latest 3.1 preview), "
            "gemini-3-flash-preview (3.0 general), gemini-3-pro-preview (3.0 quality). "
            "OpenAI options: gpt-5.4-mini (default), gpt-5.4."
        ),
    )

    # Sprint 201: Product Image Enrichment (Google-cached thumbnails for Serper site-filtered results)
    enable_product_image_enrichment: bool = Field(
        default=False,
        description="Enrich product search results with Google-cached thumbnail images via Serper /images API",
    )
    image_enrichment_timeout: int = Field(
        default=8, ge=2, le=30,
        description="Timeout in seconds for Serper /images API call",
    )
    image_enrichment_min_similarity: float = Field(
        default=0.4, ge=0.0, le=1.0,
        description="Minimum Jaccard title similarity for image-to-product matching (Sprint 201b: raised from 0.25 to reduce wrong matches)",
    )

    # Sprint 202: LLM-Curated Product Cards ("Kết Quả Sạch")
    enable_curated_product_cards: bool = Field(
        default=False,
        description="Suppress raw preview cards; emit only LLM-curated top picks after aggregation",
    )
    curated_product_max_cards: int = Field(
        default=8, ge=3, le=15,
        description="Max curated product cards to show (3-15)",
    )
    curated_product_llm_tier: str = Field(
        default="light",
        description="LLM tier for product curation: light (fast) / moderate / deep",
    )

    # Sprint 203: Natural Conversation (SOTA 2026)
    enable_natural_conversation: bool = Field(
        default=False,
        description="Phase-aware natural conversation — no canned greetings, positive framing, no word limits",
    )
    llm_presence_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0,
        description="LLM presence penalty for response diversity (Gemini/OpenAI)",
    )
    llm_frequency_penalty: float = Field(
        default=0.0, ge=-2.0, le=2.0,
        description="LLM frequency penalty against repetition (Gemini/OpenAI)",
    )

    # Sprint 199: Chinese Platform Search (1688, Taobao, AliExpress)
    enable_chinese_platform_search: bool = Field(
        default=True,
        description="Include Chinese platforms (1688, Taobao, AliExpress) in international search",
    )

    # Sprint 198: Serper.dev for web/B2B search (replaces DuckDuckGo)
    enable_serper_web_search: bool = Field(default=True, description="Use Serper.dev for web/B2B search (requires SERPER_API_KEY, falls back to DuckDuckGo)")

    # Sprint 197: LLM Query Planner
    enable_query_planner: bool = Field(default=False, description="LLM query planning before product search (optimizes search queries for Vietnamese/B2B)")

    # Unified Skill Architecture (Sprint 191)
    enable_unified_skill_index: bool = Field(default=False, description="Enable unified skill index across all skill/tool systems")
    enable_skill_metrics: bool = Field(default=False, description="Track per-tool/skill execution metrics (latency, success, cost)")
    skill_metrics_flush_interval_seconds: int = Field(default=60, description="Seconds between DB flushes for skill metrics")

    # Skill ↔ Tool Bridge (Sprint 205)
    enable_skill_tool_bridge: bool = Field(default=False, description="Bridge tool execution to Living Agent skill advancement (DISCOVER→MASTER)")

    # Narrative Context (Sprint 206)
    enable_narrative_context: bool = Field(default=False, description="Inject Wiii's life narrative into system prompt (requires enable_living_agent)")

    # Identity Core (Sprint 207)
    enable_identity_core: bool = Field(default=False, description="Self-evolving identity layer — Wiii learns about itself from reflections (requires enable_living_agent)")

    # Conservative Evolution (2026-03-19)
    enable_living_core_contract: bool = Field(
        default=False,
        description="Compile and inject LivingContextBlockV1 across agents without rewriting the graph",
    )
    enable_memory_blocks: bool = Field(
        default=False,
        description="Expose MemoryBlockV1 taxonomy in prompt context for living-memory turns",
    )
    enable_deliberate_reasoning: bool = Field(
        default=False,
        description="Apply ReasoningPolicyV1 deliberation floors before agent execution",
    )
    enable_living_visual_cognition: bool = Field(
        default=False,
        description="Add living visual cognition guidance for SVG-first figures and Canvas-first simulations",
    )
    enable_conservative_fast_routing: bool = Field(
        default=False,
        description=(
            "Allow obvious social/web/product/code turns to skip supervisor LLM "
            "with narrow guardrails; opt in per deployment after rollout approval"
        ),
    )

    # Wiii Connect external provider adapters
    enable_wiii_connect_composio: bool = Field(
        default=False,
        description="Enable the Wiii-owned Composio provider adapter configuration path",
    )
    composio_api_key: Optional[str] = Field(
        default=None,
        description="Composio project API key for backend-only adapter calls",
        repr=False,
    )
    composio_base_url: str = Field(
        default="https://backend.composio.dev",
        description="Composio backend base URL",
    )
    composio_api_version: str = Field(
        default="v3.1",
        description="Composio backend API version used by connect-link calls",
    )
    composio_auth_config_map: str = Field(
        default="",
        description=(
            "JSON object or comma list mapping provider slug to Composio auth_config_id"
        ),
    )
    enable_wiii_connect_composio_readonly_execute: bool = Field(
        default=False,
        description=(
            "Enable read-only Composio action execution after Wiii Connect "
            "gateway, curated catalog, schema verification, and audit checks pass"
        ),
    )
    composio_readonly_action_allowlist: str = Field(
        default="",
        description=(
            "Comma-separated curated Composio read-only action slugs allowed "
            "through Wiii Connect execution gateway"
        ),
    )
    enable_wiii_connect_composio_apply_execute: bool = Field(
        default=False,
        description=(
            "Enable Composio apply-style mutations after Wiii Connect preview, "
            "approval token, scoped connection, schema verification, and audit checks pass"
        ),
    )
    composio_apply_action_allowlist: str = Field(
        default="",
        description=(
            "Comma-separated curated Composio apply action slugs allowed through "
            "Wiii Connect execution gateway"
        ),
    )

    # SoulBridge (Sprint 213)
    enable_soul_bridge: bool = Field(default=False, description="Enable cross-service soul-to-soul communication bridge (WebSocket + HTTP)")
    soul_bridge_peers: str = Field(default="", description="Comma-separated peer entries: 'peer_id=url' or 'url' (e.g., 'bro=http://localhost:8001')")
    soul_bridge_heartbeat_interval: int = Field(default=30, ge=5, description="SoulBridge peer heartbeat ping interval in seconds")
    soul_bridge_reconnect_max: int = Field(default=60, ge=5, description="Max reconnect backoff delay in seconds")
    soul_bridge_ws_path: str = Field(default="/api/v1/soul-bridge/ws", description="WebSocket path on peer service")
    soul_bridge_bridge_events: str = Field(default="ESCALATION,STATUS_UPDATE,MOOD_CHANGE,DISCOVERY,DAILY_REPORT,CONSULTATION,CONSULTATION_REPLY", description="Comma-separated event types to forward across bridge")

    # Cross-Soul Query Routing (Sprint 215)
    enable_cross_soul_query: bool = Field(default=False, description="Enable cross-soul consultation routing — admin asks Wiii, Wiii asks Bro")
    cross_soul_query_timeout: float = Field(default=15.0, ge=1.0, le=60.0, description="Timeout in seconds for cross-soul query response")
    cross_soul_query_peer_id: str = Field(default="bro", description="Default peer soul ID for cross-soul consultation")

    # Intelligent Tool Selection (Sprint 192)
    enable_intelligent_tool_selection: bool = Field(default=False, description="Enable intelligent tool selection (4-step pipeline)")
    tool_selection_strategy: str = Field(default="hybrid", description="Tool selection strategy: all, category, semantic, metrics, hybrid")
    tool_selection_max_candidates: int = Field(default=15, description="Maximum tools to select per query")

    # OAuth skeleton
    enable_oauth_token_store: bool = Field(default=False, description="Enable OAuth token store")
    oauth_encryption_key: Optional[str] = Field(default=None, description="Fernet encryption key for OAuth tokens", repr=False)

    # Quality & Model Config
    quality_skip_threshold: float = Field(default=0.85, description="Skip grader when confidence >= this")
    rag_model_version: str = Field(default="agentic-rag-v3", description="RAG model version string")
    insight_duplicate_threshold: float = Field(default=0.85, description="Duplicate insight detection threshold")
    insight_contradiction_threshold: float = Field(default=0.70, description="Contradiction detection threshold")

    # Security
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")
    cors_origin_regex: str = Field(default="", description="Regex pattern for CORS origin matching (e.g. r'https://.*\\.holilihu\\.online')")

    # Sprint 175: Subdomain → Org routing
    subdomain_base_domain: str = Field(default="", description="Base domain for subdomain org extraction (e.g. 'holilihu.online')")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")
    mask_pii: bool = Field(default=True, description="Mask PII in logs")
