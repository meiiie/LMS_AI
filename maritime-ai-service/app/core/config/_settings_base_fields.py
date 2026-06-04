"""Base flat settings fields extracted from Settings for maintainability."""

from typing import Optional

from pydantic import Field

from app.core.config._settings_runtime import (
    append_connect_timeout,
    build_asyncpg_url,
    build_postgres_url,
    build_postgres_url_sync,
    remove_connect_timeout,
    resolve_neo4j_username,
)
from app.engine.model_catalog import (
    DEFAULT_EMBEDDING_MODEL,
    GOOGLE_DEEP_MODEL,
    GOOGLE_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL_ADVANCED,
    OPENROUTER_DEFAULT_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_DEFAULT_MODEL_ADVANCED,
    NVIDIA_DEFAULT_BASE_URL,
    NVIDIA_DEFAULT_MODEL,
    NVIDIA_DEFAULT_MODEL_ADVANCED,
    NVIDIA_DEFAULT_VISION_MODEL,
    ZHIPU_DEFAULT_MODEL,
    ZHIPU_DEFAULT_MODEL_ADVANCED,
    get_embedding_dimensions,
)


class BaseSettingsFieldsMixin:
    # Application
    app_name: str = Field(default="Wiii", description="Application name")
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    environment: str = Field(default="development", description="Environment: development, staging, production")

    # API Settings
    api_v1_prefix: str = Field(default="/api/v1", description="API version 1 prefix")
    api_key: Optional[str] = Field(default=None, description="API Key for authentication", repr=False)
    jwt_secret_key: str = Field(default="change-me-in-production", description="JWT secret key", repr=False)
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expire_minutes: int = Field(default=15, description="JWT token expiration in minutes")

    # Google OAuth (Sprint 157: Đăng Nhập)
    enable_google_oauth: bool = Field(default=False, description="Enable Google OAuth login")
    google_oauth_client_id: Optional[str] = Field(default=None, description="Google OAuth 2.0 client ID")
    google_oauth_client_secret: Optional[str] = Field(default=None, description="Google OAuth 2.0 client secret", repr=False)
    oauth_redirect_base_url: Optional[str] = Field(default=None, description="Base URL for OAuth callbacks (e.g. https://api.wiii.app)")
    session_secret_key: str = Field(default="change-session-secret-in-production", description="Session middleware secret for OAuth CSRF state", repr=False)
    # Sprint 193: Allowed redirect origins for web OAuth (comma-separated whitelist)
    oauth_allowed_redirect_origins: str = Field(
        default="http://localhost:1420,http://localhost:1421",
        description="Comma-separated whitelist of allowed origins for web OAuth redirect_uri",
    )
    jwt_refresh_expire_days: int = Field(default=30, ge=1, le=365, description="Refresh token expiration in days")

    # LMS Token Exchange (Sprint 159: Cầu Nối Trực Tiếp)
    enable_lms_token_exchange: bool = Field(default=False, description="Enable LMS backend → Wiii JWT token exchange")
    lms_token_exchange_max_age: int = Field(default=300, ge=30, le=600, description="Max request age for replay protection (seconds)")

    # Local Dev Login (Issue #88): frictionless one-click JWT for localhost
    # development. Hard-refused in production by build_validate_production_security.
    enable_dev_login: bool = Field(
        default=False,
        description="Enable POST /auth/dev-login endpoint for local development. "
        "Forbidden in production (validator hard-fails).",
    )
    dev_login_default_email: str = Field(
        default="dev@localhost",
        description="Email used when /auth/dev-login is called without a body",
    )
    dev_login_default_role: str = Field(
        default="admin",
        description="Default role granted by /auth/dev-login (typically 'admin' for local convenience)",
    )

    # Magic Link Email Auth (Sprint 224)
    enable_magic_link_auth: bool = Field(default=False, description="Enable Magic Link email authentication")
    resend_api_key: str = Field(default="", description="Resend API key for sending magic link emails", repr=False)
    magic_link_base_url: str = Field(default="http://localhost:8000", description="Base URL for magic link verification endpoint")
    magic_link_expires_seconds: int = Field(default=600, ge=60, le=3600, description="Magic link token expiry (default 10 min)")
    magic_link_from_email: str = Field(default="Wiii <noreply@wiii.app>", description="Sender email for magic links")
    magic_link_ws_timeout_seconds: int = Field(default=900, ge=60, le=3600, description="WebSocket session timeout (default 15 min)")
    magic_link_resend_cooldown_seconds: int = Field(default=45, ge=15, le=120, description="Cooldown between resend attempts")
    magic_link_max_per_hour: int = Field(default=5, ge=1, le=20, description="Max magic links per email per hour")
    magic_link_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400, description="Periodic cleanup of expired magic_link_tokens rows (default 1h)")
    magic_link_cleanup_grace_hours: int = Field(default=24, ge=0, le=168, description="Grace period before deleting expired magic-link rows (hours)")
    magic_link_session_reaper_interval_seconds: int = Field(default=60, ge=15, le=3600, description="Interval for reaping stale in-memory WS sessions")
    enable_distributed_magic_link_sessions: bool = Field(default=False, description="Use Valkey-backed magic link session store for restart safety + multi-worker support")

    # Sentry — Error Tracking (Production Hardening)
    sentry_dsn: str = Field(default="", description="Sentry DSN — empty disables Sentry")
    sentry_environment: str = Field(default="development", description="Sentry environment tag")
    sentry_traces_sample_rate: float = Field(default=0.2, ge=0.0, le=1.0, description="Sentry performance sampling rate")

    # Rate Limiting
    rate_limit_requests: int = Field(default=100, description="Max requests per window")
    rate_limit_window_seconds: int = Field(default=60, description="Rate limit window in seconds")

    # Database - PostgreSQL (Local Docker)
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5433, description="PostgreSQL port (Docker maps to 5433)")
    postgres_user: str = Field(default="wiii", description="PostgreSQL user")
    postgres_password: str = Field(default="wiii_secret", description="PostgreSQL password", repr=False)
    postgres_db: str = Field(default="wiii_ai", description="PostgreSQL database name")

    # Database - Cloud (Production) - CHỈ THỊ 19: Now using Neon
    database_url: Optional[str] = Field(default=None, description="Full database URL (Neon/Cloud)")

    # AsyncPG Connection Pool Settings
    async_pool_min_size: int = Field(default=10, description="Minimum async connection pool size")
    async_pool_max_size: int = Field(default=50, description="Maximum async connection pool size")

    # PostgreSQL Safety (Sprint 171: CIS Benchmark 5.4)
    postgres_statement_timeout_ms: int = Field(default=30000, ge=1000, le=300000, description="Query timeout in ms (default 30s)")
    postgres_idle_in_transaction_timeout_ms: int = Field(default=60000, ge=10000, le=600000, description="Idle transaction timeout in ms (default 60s)")
    postgres_connect_timeout_seconds: int = Field(default=5, ge=1, le=60, description="Connection timeout in seconds for PostgreSQL clients")

    # Object Storage (MinIO / S3-compatible)
    minio_endpoint: Optional[str] = Field(default=None, description="MinIO endpoint (host:port, no scheme)")
    minio_external_endpoint: Optional[str] = Field(default=None, description="MinIO endpoint for browser-facing presigned URLs (defaults to minio_endpoint)")
    minio_access_key: Optional[str] = Field(default=None, description="MinIO access key", repr=False)
    minio_secret_key: Optional[str] = Field(default=None, description="MinIO secret key", repr=False)
    minio_bucket: str = Field(default="wiii-docs", description="Storage bucket for document images")
    minio_secure: bool = Field(default=False, description="Use HTTPS for MinIO connection")

    # LMS API Key (for authentication from LMS)
    lms_api_key: Optional[str] = Field(default=None, description="API Key for LMS integration", repr=False)

    # LMS Callback Configuration (AI-LMS Integration v2.0)
    lms_callback_url: Optional[str] = Field(default=None, description="LMS callback URL for AI events")
    lms_callback_secret: Optional[str] = Field(default=None, description="Shared secret for callback authentication", repr=False)

    # LMS Integration (Sprint 155: Cầu Nối — inbound from LMS)
    enable_lms_integration: bool = Field(default=False, description="Enable LMS webhook + API integration")
    lms_base_url: Optional[str] = Field(default=None, description="LMS REST API base URL (single-LMS compat)")
    lms_service_token: Optional[str] = Field(default=None, description="Service account token for LMS API (single-LMS compat)", repr=False)
    lms_webhook_secret: Optional[str] = Field(default=None, description="HMAC-SHA256 secret for incoming webhooks (single-LMS compat)", repr=False)
    lms_api_timeout: int = Field(default=10, ge=3, le=60, description="LMS API call timeout (seconds)")

    # Course Generation (design spec v2.0, 2026-03-22)
    use_docling_for_course_gen: bool = Field(default=False, description="Use Docling for document conversion (requires pip install docling)")
    document_context_parser_mode: str = Field(default="auto", description="Document upload parser mode: auto, fast, or precision")
    markitdown_enable_plugins: bool = Field(default=False, description="Enable MarkItDown third-party plugins for document conversion")
    docling_vlm_backend: str = Field(default="none", description="VLM backend for scanned pages: 'gemini', 'ollama', 'none'")
    docling_vlm_api_url: Optional[str] = Field(default=None, description="VLM API URL for Docling scanned page extraction")
    docling_vlm_api_key: Optional[str] = Field(default=None, description="VLM API key for Docling", repr=False)
    docling_vlm_model: str = Field(default="gemini-3.1-flash-lite", description="VLM model for Docling scanned pages")
    course_gen_max_concurrent_chapters: int = Field(default=3, ge=1, le=10, description="Max parallel chapter expansions")
    course_gen_chapter_timeout_seconds: int = Field(default=120, ge=30, le=600, description="Timeout per chapter expansion")

    # Sprint 155b: Multi-LMS connector list (JSON array — takes precedence over flat fields above)
    lms_connectors: str = Field(
        default="[]",
        description='JSON list of LMS connectors: [{"id":"maritime-lms","backend_type":"spring_boot","base_url":"...","webhook_secret":"..."}]'
    )

    # Sprint 222: Universal Host Context Engine
    enable_host_context: bool = False       # Master gate for v2 host context
    enable_host_actions: bool = False       # Bidirectional host actions
    enable_host_skills: bool = False        # Dynamic YAML skill loading

    # Sprint 223: Hybrid Visual Context Engine
    enable_rich_page_context: bool = False  # Path A: structured data in host_context
    enable_visual_page_capture: bool = False  # Path B: on-demand screenshot + Vision
    visual_capture_timeout: float = 10.0  # Screenshot capture timeout (seconds)
    visual_capture_max_size: int = 1048576  # Max screenshot size (1MB)

    # Sprint 222b Phase 7: Standalone Browser Agent (Playwright MCP)
    enable_browser_agent: bool = False
    browser_agent_mcp_command: str = "npx"
    browser_agent_mcp_args: list = ["@playwright/mcp", "--headless"]
    browser_agent_timeout: int = 120  # seconds per browser session
    browser_agent_max_sessions_per_hour: int = 10

    # Code Studio streaming
    enable_code_studio_streaming: bool = Field(
        default=False,
        description="Emit chunked code_delta SSE events for Code Studio streaming display",
    )
    enable_real_code_streaming: bool = Field(
        default=False,
        description="Use astream for real token-by-token code generation (replaces fake chunking)",
    )
    # Code Studio resilience timeouts (Sprint 35d) — operator-tunable so the
    # graceful HTML scaffold can engage well before user-facing HTTP timeouts.
    code_studio_stream_overall_timeout_seconds: float = Field(
        default=90.0,
        ge=15.0,
        le=600.0,
        description="Hard ceiling for the streaming code-gen pass; cancels astream + engages topic-aware scaffold when exceeded.",
    )
    code_studio_chunk_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
        description="Per-chunk timeout when waiting on the next astream token; small enough to break out of NVIDIA NIM heartbeat-only streams.",
    )
    code_studio_code_done_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=180.0,
        description="Grace period after code_html is fully extracted to wait for the matching tool_call to land before forcing the round complete.",
    )
    code_studio_llm_hard_timeout_seconds: float = Field(
        default=90.0,
        ge=15.0,
        le=600.0,
        description="Hard ceiling for the non-streaming planning ainvoke call; engages graceful scaffold on exceeded.",
    )
    code_studio_fallback_ainvoke_timeout_seconds: float = Field(
        default=60.0,
        ge=10.0,
        le=300.0,
        description="Timeout for the moderate-tier fallback ainvoke after the primary planning call fails; kept tight so the scaffold can engage quickly.",
    )
    code_studio_post_tool_synthesis_timeout_seconds: float = Field(
        default=90.0,
        ge=15.0,
        le=600.0,
        description="Hard ceiling for the synthesizer LLM call invoked AFTER tool execution. Without this cap the graceful-scaffold path stretched to 17+ minutes when NVIDIA NIM stalled mid-stream; capping at 90s lets the canned scaffold caption engage instead.",
    )

    # Wiii Pointy v2.6 — agentic loop safety caps. Modern SOTA agents
    # (Anthropic Computer Use 2026 ref, Manus AI, Cursor 3.0, Ralph)
    # exit naturally when LLM stops calling tools; the cap is a runaway
    # protection, not a target. Default 12 rounds matches Anthropic
    # Computer Use ref impl (10) + a small margin for multi-step pointy
    # tours (5-button guide needs 5 pointy rounds + 1 synthesis).
    direct_agent_max_tool_rounds: int = Field(
        default=12,
        ge=1,
        le=30,
        description="Safety cap on the DIRECT agent's tool-calling loop. Loop exits naturally when LLM emits no more tool_calls; this is the upper bound to prevent runaway. Bump for power-users / autonomous flows; lower for cost control. Pre-v2.6 default was 3 (too tight for multi-step pointy tours).",
    )
    code_studio_max_tool_rounds: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Safety cap on Code Studio tool-calling loop. Lower than DIRECT because each Code Studio round invokes NVIDIA NIM with full canvas spec (~60s) — runaway cost is higher.",
    )

    postgres_url = property(build_postgres_url)
    asyncpg_url = property(build_asyncpg_url)
    postgres_url_sync = property(build_postgres_url_sync)
    _append_connect_timeout = append_connect_timeout
    _remove_connect_timeout = remove_connect_timeout

    # Database - Neo4j (Local Docker)
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j connection URI (local or Aura)")
    neo4j_user: str = Field(default="neo4j", description="Neo4j user")
    neo4j_username: Optional[str] = Field(default=None, description="Neo4j username (Aura format)")
    neo4j_password: str = Field(default="neo4j_secret", description="Neo4j password", repr=False)

    neo4j_username_resolved = property(resolve_neo4j_username)

    # LLM Settings - OpenAI/OpenRouter (legacy)
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key", repr=False)
    openai_base_url: Optional[str] = Field(default=None, description="OpenAI API base URL")
    openrouter_api_key: Optional[str] = Field(default=None, description="OpenRouter API key", repr=False)
    openrouter_base_url: Optional[str] = Field(default=OPENROUTER_DEFAULT_BASE_URL, description="OpenRouter API base URL")
    openai_model: str = Field(default=OPENAI_DEFAULT_MODEL, description="OpenAI model for general tasks")
    openai_model_advanced: str = Field(default=OPENAI_DEFAULT_MODEL_ADVANCED, description="OpenAI model for complex tasks")
    openrouter_model: str = Field(default=OPENROUTER_DEFAULT_MODEL, description="OpenRouter model for general tasks")
    openrouter_model_advanced: str = Field(default=OPENROUTER_DEFAULT_MODEL_ADVANCED, description="OpenRouter model for complex tasks")

    # NVIDIA NIM (Issue #110) — OpenAI-compatible endpoint at integrate.api.nvidia.com.
    # NGC API key from build.nvidia.com unlocks Llama 3.1 405B, Nemotron 70B, etc.
    nvidia_api_key: Optional[str] = Field(default=None, description="NVIDIA NIM (NGC) API key", repr=False)
    nvidia_base_url: Optional[str] = Field(default=NVIDIA_DEFAULT_BASE_URL, description="NVIDIA NIM API base URL")
    nvidia_model: str = Field(default=NVIDIA_DEFAULT_MODEL, description="NVIDIA model for general tasks")
    nvidia_model_advanced: str = Field(default=NVIDIA_DEFAULT_MODEL_ADVANCED, description="NVIDIA model for complex tasks")
    nvidia_vision_model: str = Field(
        default=NVIDIA_DEFAULT_VISION_MODEL,
        description="NVIDIA NIM VLM model for image understanding tasks",
    )
    enable_llm_model_health_probes: bool = Field(
        default=True,
        description="Run background model-level probes so degraded models are skipped before user traffic.",
    )
    llm_model_health_probe_timeout_seconds: float = Field(
        default=8.0,
        ge=1.0,
        le=60.0,
        description="Per-model live probe timeout for model health checks.",
    )
    llm_model_health_probe_interval_seconds: float = Field(
        default=300.0,
        ge=0.0,
        le=86400.0,
        description="Periodic model health probe interval; 0 disables the periodic loop.",
    )
    llm_model_health_degraded_ttl_seconds: float = Field(
        default=300.0,
        ge=0.0,
        le=86400.0,
        description="How long a failed model health probe keeps that model degraded.",
    )
    openrouter_model_fallbacks: list[str] = Field(
        default_factory=list,
        description="Ordered fallback models for OpenRouter requests",
    )
    openrouter_provider_order: list[str] = Field(
        default_factory=list,
        description="Preferred OpenRouter providers in priority order",
    )
    openrouter_allowed_providers: list[str] = Field(
        default_factory=list,
        description="Restrict OpenRouter requests to these providers",
    )
    openrouter_ignored_providers: list[str] = Field(
        default_factory=list,
        description="Providers OpenRouter should avoid",
    )
    openrouter_allow_fallbacks: Optional[bool] = Field(
        default=None,
        description="Override OpenRouter provider fallback behavior",
    )
    openrouter_require_parameters: Optional[bool] = Field(
        default=None,
        description="Only choose OpenRouter providers that support all request params",
    )
    openrouter_data_collection: Optional[str] = Field(
        default=None,
        description="OpenRouter data collection policy: allow | deny",
    )
    openrouter_zdr: Optional[bool] = Field(
        default=None,
        description="Require Zero Data Retention providers on OpenRouter",
    )
    openrouter_provider_sort: Optional[str] = Field(
        default=None,
        description="OpenRouter provider sort: price | latency | throughput",
    )

    # LLM Settings - Google Gemini (cloud fallback)
    google_api_key: Optional[str] = Field(default=None, description="Google Gemini API key", repr=False)
    google_model: str = Field(
        default=GOOGLE_DEFAULT_MODEL,
        description="Google Gemini model (default: gemini-3.1-flash-lite-preview, current March 2026 default)",
    )
    google_model_advanced: str = Field(
        default=GOOGLE_DEEP_MODEL,
        description="Google Gemini model for complex/deep tasks (default: gemini-3.1-pro-preview)",
    )
    llm_provider: str = Field(
        default="zhipu",
        description="LLM provider: google, zhipu, openai, openrouter, nvidia, ollama",
    )

    # LLM Settings - Ollama (local/self-hosted)
    ollama_api_key: Optional[str] = Field(
        default=None,
        description="Ollama Cloud API key for direct access to https://ollama.com/api",
        repr=False,
    )
    ollama_base_url: Optional[str] = Field(default="http://localhost:11434", description="Ollama API base URL")
    ollama_model: str = Field(
        default="qwen3:4b-instruct-2507-q4_K_M",
        description="Ollama model name (explicit Qwen3 instruct default)",
    )
    ollama_keep_alive: Optional[str] = Field(
        default="30m",
        description="How long Ollama should keep the active model loaded in memory",
    )
    ollama_thinking_models: list[str] = Field(
        default=["qwen3", "deepseek-r1", "qwq"],
        description="Models supporting thinking mode via Ollama (matched by prefix)"
    )

    # LLM Settings - Zhipu AI / GLM (cloud fallback)
    # Vertex AI (separate from Google AI Studio — independent quota)
    vertex_api_key: Optional[str] = Field(default=None, description="Vertex AI API key (format: AQ.xxx)", repr=False)
    vertex_model: Optional[str] = Field(default=None, description="Vertex AI model (defaults to google_model if not set)")

    zhipu_api_key: Optional[str] = Field(default=None, description="Zhipu AI (GLM) API key", repr=False)
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4",
        description="Zhipu AI API base URL (OpenAI-compatible)",
    )
    zhipu_model: str = Field(default=ZHIPU_DEFAULT_MODEL, description="Zhipu model for general tasks")
    zhipu_model_advanced: str = Field(default=ZHIPU_DEFAULT_MODEL_ADVANCED, description="Zhipu model for complex tasks")

    # Multi-Provider Failover (Sprint 11: OpenClaw-inspired)
    llm_failover_chain: list[str] = Field(
        default=["google", "zhipu", "ollama", "openrouter"],
        description="LLM provider failover chain (try in order)"
    )
    enable_llm_failover: bool = Field(default=True, description="Enable automatic LLM provider failover")
    llm_primary_timeout_light_seconds: float = Field(
        default=12.0,
        ge=0,
        le=600,
        description="First-response timeout for LIGHT interactive LLM calls (0 disables timeout)",
    )
    llm_primary_timeout_moderate_seconds: float = Field(
        default=25.0,
        ge=0,
        le=900,
        description="First-response timeout for MODERATE interactive LLM calls (0 disables timeout)",
    )
    llm_primary_timeout_deep_seconds: float = Field(
        default=45.0,
        ge=0,
        le=1800,
        description="First-response timeout for DEEP interactive LLM calls (0 disables timeout)",
    )
    llm_primary_timeout_structured_seconds: float = Field(
        default=60.0,
        ge=0,
        le=1800,
        description="First-response timeout for structured-output calls (0 disables timeout)",
    )
    llm_primary_timeout_background_seconds: float = Field(
        default=0.0,
        ge=0,
        le=3600,
        description="First-response timeout for background workflows such as long course generation (0 disables timeout)",
    )
    llm_stream_keepalive_interval_seconds: float = Field(
        default=15.0,
        ge=1,
        le=300,
        description="SSE keepalive heartbeat interval in seconds",
    )
    llm_stream_idle_timeout_seconds: float = Field(
        default=0.0,
        ge=0,
        le=3600,
        description="Abort stalled SSE streams after this many seconds without inner chunks (0 disables idle timeout)",
    )
    llm_timeout_provider_overrides: str = Field(
        default="{}",
        description=(
            "JSON provider/model timeout overrides: "
            '{"google": {"light_seconds": 12}, '
            '"nvidia": {"models": {"deepseek-ai/deepseek-v4-flash": {"moderate_seconds": 8}}}}'
        ),
    )
    llm_runtime_audit_refresh_interval_seconds: float = Field(
        default=300.0,
        ge=0,
        le=86400,
        description=(
            "Periodic background refresh interval for request-selectable "
            "LLM runtime audit snapshots (0 disables periodic refresh)"
        ),
    )

    # Semantic Memory Settings (v0.3 - Vector Embeddings)
    embedding_provider: str = Field(
        default="google",
        description="Semantic embedding provider: google, openai, openrouter, ollama, zhipu, or auto",
    )
    embedding_failover_chain: list[str] = Field(
        default_factory=lambda: ["google", "openai", "ollama", "openrouter"],
        description="Embedding provider failover chain used when embedding_provider=auto",
    )
    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL,
        description="Embedding model for the configured semantic embedding provider",
    )
    embedding_dimensions: int = Field(
        default=get_embedding_dimensions(DEFAULT_EMBEDDING_MODEL),
        description="Canonical embedding vector dimensions for semantic memory and pgvector search",
    )
    vision_provider: str = Field(
        default="auto",
        description="Vision/image-understanding provider: google, openai, openrouter, ollama, zhipu, or auto",
    )
    vision_describe_provider: str = Field(
        default="auto",
        description="Provider override for visual_describe capability: google, openai, openrouter, ollama, zhipu, or auto",
    )
    vision_describe_model: Optional[str] = Field(
        default=None,
        description="Capability-specific model override for visual_describe",
    )
    vision_ocr_provider: str = Field(
        default="auto",
        description="Provider override for ocr_extract capability: google, openai, openrouter, ollama, zhipu, or auto",
    )
    vision_ocr_model: Optional[str] = Field(
        default="glm-ocr",
        description="Capability-specific OCR model override (defaults to GLM-OCR specialist lane)",
    )
    vision_grounded_provider: str = Field(
        default="auto",
        description="Provider override for grounded_visual_answer capability: google, openai, openrouter, ollama, zhipu, or auto",
    )
    vision_grounded_model: Optional[str] = Field(
        default=None,
        description="Capability-specific model override for grounded_visual_answer",
    )
    vision_failover_chain: list[str] = Field(
        default_factory=lambda: ["google", "openai", "openrouter", "ollama"],
        description="Vision provider failover chain used when vision_provider=auto",
    )
    vision_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout for one vision runtime request including provider failover",
    )
    semantic_memory_enabled: bool = Field(default=True, description="Enable semantic memory v0.3")
    summarization_token_threshold: int = Field(default=2000, description="Token threshold for summarization")

    # Deep Reasoning Settings (CHỈ THỊ KỸ THUẬT SỐ 21)
    deep_reasoning_enabled: bool = Field(default=True, description="Enable Deep Reasoning with <thinking> tags")
    context_window_size: int = Field(default=50, description="Number of messages to include in context window")

    # Multi-Agent System Settings (Phase 8: SOTA 2025)
    use_multi_agent: bool = Field(default=True, description="Use Multi-Agent System (SOTA 2025) - recommended")
    multi_agent_grading_threshold: float = Field(default=6.0, description="Minimum grader score to accept response")
    enable_corrective_rag: bool = Field(default=True, description="Enable Corrective RAG with self-correction")
    retrieval_grade_threshold: float = Field(default=7.0, description="Minimum score for retrieval grading")
    enable_answer_verification: bool = Field(default=True, description="Enable hallucination checking")

    # RAG Quality Settings
    rag_quality_mode: str = Field(
        default="balanced",
        description="RAG quality mode: 'speed' (fast, less accurate), 'balanced' (default), 'quality' (slow, high accuracy)"
    )
    rag_confidence_high: float = Field(default=0.70, description="HIGH confidence threshold")
    rag_confidence_medium: float = Field(default=0.60, description="MEDIUM confidence threshold")
    rag_max_iterations: int = Field(default=2, description="Soft limit on CRAG iterations")
    rag_enable_reflection: bool = Field(default=True, description="Enable Self-RAG reflection tokens")
    rag_early_exit_on_high_confidence: bool = Field(default=True, description="Exit iteration loop early if HIGH confidence")
    enable_reranker_grading: bool = Field(default=True, description="Use lightweight reranker instead of LLM grading (skip MiniJudge + LLM batch)")

    # Gemini Thinking Level
    gemini_thinking_level: str = Field(default="medium", description="Gemini 3.0 thinking level")

    # Thinking Configuration (4-Tier Strategy)
    thinking_enabled: bool = Field(default=True, description="Enable Gemini native thinking globally")
    include_thought_summaries: bool = Field(default=True, description="Include thinking summaries in API response")
    thinking_budget_deep: int = Field(default=8192, description="DEEP tier budget")
    thinking_budget_moderate: int = Field(default=4096, description="MODERATE tier budget")
    thinking_budget_light: int = Field(default=1024, description="LIGHT tier budget")
    thinking_budget_minimal: int = Field(default=512, description="MINIMAL tier budget")

    # Similarity Thresholds
    similarity_threshold: float = Field(default=0.7, description="Default similarity threshold for semantic search")
    fact_similarity_threshold: float = Field(default=0.90, description="Similarity threshold for fact deduplication")
    memory_duplicate_threshold: float = Field(default=0.90, description="Similarity threshold for memory duplicates")
    memory_related_threshold: float = Field(default=0.75, description="Similarity threshold for related memories")

    # Rate Limits (Configurable)
    chat_rate_limit: str = Field(default="30/minute", description="Rate limit for chat endpoint")
    default_history_limit: int = Field(default=20, description="Default chat history limit")
    max_history_limit: int = Field(default=100, description="Maximum chat history limit")

    # Contextual RAG Settings
    contextual_rag_enabled: bool = Field(default=True, description="Enable Contextual RAG for chunk enrichment")
    contextual_rag_batch_size: int = Field(default=5, description="Number of chunks to enrich concurrently")

    # Document KG Entity Extraction Settings
    entity_extraction_enabled: bool = Field(default=True, description="Enable entity extraction during ingestion")
    entity_extraction_batch_size: int = Field(default=3, description="Chunks to process concurrently for extraction")

    # Semantic Cache Settings
    semantic_cache_enabled: bool = Field(default=True, description="Enable semantic response caching")
    cache_similarity_threshold: float = Field(default=0.92, description="Similarity threshold for cache hits")
    cache_response_ttl: int = Field(default=7200, description="Base response cache TTL in seconds")
    cache_retrieval_ttl: int = Field(default=1800, description="Retrieval cache TTL in seconds")
    cache_embedding_ttl: int = Field(default=3600, description="Embedding cache TTL in seconds")
    cache_max_response_entries: int = Field(default=10000, description="Maximum response cache entries")
    cache_log_operations: bool = Field(default=True, description="Log cache hit/miss operations")
    cache_adaptive_ttl: bool = Field(default=True, description="Enable adaptive TTL")
    cache_adaptive_ttl_max_multiplier: float = Field(default=3.0, description="Maximum TTL multiplier for hot queries")

    # Semantic Chunking Settings
    chunk_size: int = Field(default=800, description="Target chunk size in characters")
    chunk_overlap: int = Field(default=100, description="Overlap between consecutive chunks")
    min_chunk_size: int = Field(default=50, description="Minimum chunk size to avoid tiny fragments")
    dpi_optimized: int = Field(default=100, description="Optimized DPI for PDF to image conversion")
    vision_max_dimension: int = Field(default=1024, description="Max dimension for vision API images")
    vision_image_quality: int = Field(default=85, description="JPEG quality for vision API images")

    # Hybrid Text/Vision Detection Settings
    hybrid_detection_enabled: bool = Field(default=True, description="Enable hybrid text/vision detection")
    min_text_length_for_direct: int = Field(default=100, description="Minimum text length for direct extraction")
    force_vision_mode: bool = Field(default=False, description="Force Vision extraction for all pages")

    # Domain Plugin System (Wiii)
    active_domains: list[str] = Field(default=["maritime", "traffic_law"], description="List of active domain plugin IDs")
    default_domain: str = Field(default="maritime", description="Default domain when not specified")

    # Multi-Channel Gateway
    enable_websocket: bool = Field(default=True, description="Enable WebSocket chat endpoint")
    enable_telegram: bool = Field(default=False, description="Enable Telegram bot integration")
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram Bot API token", repr=False)
    telegram_webhook_url: Optional[str] = Field(default=None, description="Telegram webhook callback URL")
    enable_messenger_webhook: bool = Field(default=False, description="Enable Facebook Messenger Platform webhook")
    facebook_app_id: Optional[str] = Field(default=None, description="Facebook App ID")
    facebook_app_secret: Optional[str] = Field(default=None, description="Facebook App Secret for X-Hub-Signature verification", repr=False)
    facebook_page_id: Optional[str] = Field(default=None, description="Facebook Page ID")
    enable_zalo: bool = Field(default=False, description="Enable Zalo OA notification channel")
    zalo_oa_refresh_token: Optional[str] = Field(default=None, description="Zalo OA refresh token", repr=False)
    zalo_oa_app_id: Optional[str] = Field(default=None, description="Zalo OA application ID")

    # Sprint 174b: OTP Identity Linking
    otp_link_expiry_seconds: int = Field(default=300, ge=60, le=900, description="OTP code expiry in seconds (default 5 min)")

    # Sprint 174: Cross-Platform Identity + Dual Personality
    enable_cross_platform_identity: bool = Field(default=False, description="Enable canonical identity resolution across platforms")
    enable_zalo_webhook: bool = Field(default=False, description="Enable Zalo OA incoming message webhook")
    zalo_webhook_token: Optional[str] = Field(default=None, description="Verify token for Zalo webhook handshake", repr=False)
    default_personality_mode: str = Field(default="professional", description="Default personality mode: professional or soul")
    channel_personality_map: str = Field(
        default='{"web":"professional","desktop":"professional","messenger":"soul","zalo":"soul","telegram":"professional"}',
        description="JSON map of channel_type → personality mode",
    )

    # Sprint 176: Auth Hardening
    enable_auth_audit: bool = Field(default=True, description="Log auth events to auth_events table")

    # Sprint 192: Auth Hardening — "Khiên Sắt"
    enable_org_membership_check: bool = Field(default=True, description="Validate org membership on X-Organization-ID header")
    enable_jti_denylist: bool = Field(default=False, description="Enable in-memory JTI denylist for token revocation")
    jwt_audience: str = Field(default="wiii", description="JWT audience claim value")
    enforce_api_key_role_restriction: bool = Field(default=True, description="Block admin role via API key auth in production")
    otp_max_generate_per_window: int = Field(default=5, ge=1, le=20, description="Max OTP codes per user per window")
    otp_generate_window_minutes: int = Field(default=15, ge=1, le=60, description="OTP generation rate limit window (minutes)")
    otp_max_verify_attempts: int = Field(default=5, ge=1, le=10, description="Max failed OTP verify attempts before lockout")

    # Sprint 178: Admin Module
    enable_admin_module: bool = Field(default=False, description="Enable admin dashboard, audit, analytics")

    # Sprint 181: Org-Level Admin
    enable_org_admin: bool = Field(default=False, description="Enable org-level admin for org admins/owners")
    admin_ip_allowlist: str = Field(default="", description="Comma-separated IP allowlist for admin routes (empty=allow all)")
    admin_rate_limit: str = Field(default="30/minute", description="Rate limit for admin endpoints")

    # Sprint 190: Org Knowledge Management
    enable_org_knowledge: bool = Field(default=False, description="Enable org-level knowledge base management (upload/list/delete)")
    org_knowledge_max_file_size_mb: int = Field(default=50, ge=1, le=200, description="Max PDF file size in MB for org knowledge upload")
    org_knowledge_rate_limit: str = Field(default="5/minute", description="Per-org upload rate limit")

    # Sprint 191: Knowledge Visualization
    enable_knowledge_visualization: bool = Field(default=False, description="Enable knowledge base visualization (scatter, graph, RAG flow)")

    # Sprint 179: Multimodal Vision Input
    enable_vision: bool = Field(default=False, description="Enable vision/image understanding in chat")
    vision_max_images_per_request: int = Field(default=5, ge=1, le=20, description="Max images per chat request")
    vision_default_detail: str = Field(default="auto", description="Default vision detail level (low/auto/high)")
    vision_max_file_size_mb: int = Field(default=10, ge=1, le=50, description="Max image file size in MB")

    # Sprint 179: Chart/Diagram Generation
    enable_chart_tools: bool = Field(default=True, description="Enable Mermaid diagram and chart generation tools")
    enable_structured_visuals: bool = Field(
        default=True,
        description="Enable streaming-first structured inline visuals (VisualPayload v1 + SSE visual events)",
    )
    enable_code_gen_visuals: bool = Field(
        default=True,
        description="Route explanatory visuals to inline_html (code-gen) instead of template (card layout)",
    )
    enable_llm_code_gen_visuals: bool = Field(
        default=True,
        description="Allow LLM to write custom HTML/CSS/SVG via code_html param (Claude Artifacts style)",
    )

    # Sprint 179+: Visual RAG — understand charts/tables in documents
    enable_visual_rag: bool = Field(default=False, description="Enable visual context enrichment during RAG retrieval")
    visual_rag_max_images: int = Field(default=3, ge=1, le=10, description="Max images to analyze per RAG query")
    visual_rag_timeout: float = Field(default=15.0, ge=5.0, le=60.0, description="Timeout for image fetch + analysis (seconds)")

    # Sprint 182: Graph RAG — entity-aware knowledge graph retrieval
    enable_graph_rag: bool = Field(default=False, description="Enable entity extraction + graph context in RAG pipeline")
    graph_rag_max_entities: int = Field(default=5, ge=1, le=20, description="Max entities to extract per query")

    # Sprint 184: Temporal Knowledge Graph Memory
    enable_temporal_memory: bool = Field(default=False, description="Enable temporal knowledge graph for memory (entity-relation-episode)")

    # Sprint 186: Visual Memory — remember images users send
    enable_visual_memory: bool = Field(default=False, description="Enable image memory storage and retrieval")
    visual_memory_max_per_user: int = Field(default=100, ge=10, le=500, description="Max image memories per user")
    visual_memory_context_max_items: int = Field(default=3, ge=1, le=10, description="Max visual memories injected into context")

    # Sprint 187: Advanced RAG — HyDE + Adaptive RAG
    enable_hyde: bool = Field(default=False, description="Enable Hypothetical Document Embeddings for improved retrieval")
    hyde_blend_alpha: float = Field(default=0.5, ge=0.0, le=1.0, description="HyDE embedding blend weight (0=query only, 1=HyDE only)")
    enable_adaptive_rag: bool = Field(default=False, description="Enable adaptive routing to different retrieval strategies")

    # Sprint 176: Embed iframe support
    embed_allowed_origins: str = Field(
        default="",
        description="Space-separated list of allowed origins for iframe embedding (CSP frame-ancestors). Empty = 'self' only.",
    )

    # Background Infrastructure
    valkey_url: str = Field(default="redis://localhost:6379/0", description="Valkey/Redis broker URL")
    enable_background_tasks: bool = Field(default=False, description="Enable background task processing via Taskiq")
    enable_scheduler: bool = Field(default=False, description="Enable scheduled task execution (proactive agent)")

    # Scheduler Execution
    scheduler_poll_interval: int = Field(default=60, description="Seconds between scheduler polls (10-3600)")
    scheduler_max_concurrent: int = Field(default=5, description="Max concurrent task executions (1-20)")
    scheduler_agent_timeout: int = Field(default=120, description="Timeout for agent invocation in seconds")

    # Extended Tools
    workspace_root: str = Field(default="~/.wiii/workspace", description="Root directory for workspace operations")
    enable_filesystem_tools: bool = Field(default=False, description="Enable sandboxed filesystem tools")
    enable_code_execution: bool = Field(default=False, description="Enable sandboxed Python execution")
    code_execution_timeout: int = Field(default=30, description="Code execution timeout in seconds")
    enable_privileged_sandbox: bool = Field(default=False, description="Enable dedicated privileged sandbox executor for remote code/browser workloads")
    sandbox_provider: str = Field(default="disabled", description="Privileged sandbox provider: disabled, local_subprocess, opensandbox")
    sandbox_default_timeout_seconds: int = Field(default=120, ge=5, le=3600, description="Default timeout for remote sandbox workloads in seconds")
    sandbox_allow_browser_workloads: bool = Field(default=False, description="Allow browser-class workloads to use the privileged sandbox executor")
    opensandbox_base_url: Optional[str] = Field(default=None, description="Base URL for OpenSandbox control plane")
    opensandbox_api_key: Optional[str] = Field(default=None, description="API key for OpenSandbox control plane", repr=False)
    opensandbox_healthcheck_path: str = Field(default="/health", description="Health check path for OpenSandbox control plane")
    opensandbox_code_template: str = Field(default="opensandbox/code-interpreter:v1.0.1", description="Default OpenSandbox runtime image for Python or command execution")
    opensandbox_browser_template: str = Field(default="opensandbox/playwright:latest", description="Default OpenSandbox runtime image for browser automation workloads")
    opensandbox_network_mode: str = Field(default="egress", description="OpenSandbox network mode: disabled, bridge, egress")
    opensandbox_keepalive_seconds: int = Field(default=600, ge=30, le=86400, description="How long an OpenSandbox session may stay alive for reuse before cleanup")
    enable_skill_creation: bool = Field(default=False, description="Enable runtime skill creation")

    # Unified LLM Client
    enable_unified_client: bool = Field(default=True, description="Enable UnifiedLLMClient (AsyncOpenAI SDK)")

    # Runtime Migration Epic (#207) — feature gate for the lane-first /
    # harness-split / native-message runtime built in Phases 0–7. Phase 0
    # ships scaffold only; flipping this on becomes meaningful from
    # Phase 4 onward. Kept default False so the existing path is canonical
    # until per-org canary rollout in Phase 7.
    enable_native_runtime: bool = Field(
        default=False,
        description="Enable lane-first native runtime (Runtime Migration Epic #207).",
    )

    enable_session_event_log: bool = Field(
        default=False,
        description=(
            "Enable durable session event log (Phase 5 of #207). When False, "
            "the in-memory fallback is used and events are lost on restart."
        ),
    )

    session_event_log_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description=(
            "Default retention window for admin-triggered session_events pruning. "
            "Pruning is never automatic; operators must call the admin prune endpoint."
        ),
    )

    enable_eval_recording: bool = Field(
        default=False,
        description=(
            "Record per-turn EvalRecord JSONL for nightly replay (Phase 6 of #207). "
            "Default OFF; opt-in per environment to avoid storage costs."
        ),
    )

    eval_recording_dir: str = Field(
        default="eval_recordings",
        description="Base directory for JSONL eval records when enable_eval_recording=True.",
    )

    enable_subagent_isolation: bool = Field(
        default=False,
        description=(
            "Enable Anthropic-style Task subagent isolation (Phase 12 of #207). "
            "When True, SubagentRunner spawns child agents in their own session "
            "scope so the parent context window only sees the summary, not the "
            "subagent's working messages."
        ),
    )

    subagent_default_max_steps: int = Field(
        default=10,
        description="Default cap on subagent ReAct steps (Phase 12 of #207).",
        ge=1,
        le=100,
    )

    sandbox_snapshot_dir: Optional[str] = Field(
        default=None,
        description=(
            "Filesystem path for SandboxSnapshot store (Phase 23 of #207). "
            "When set, ``get_snapshot_store()`` returns a "
            "FilesystemSnapshotStore rooted here; otherwise it falls back "
            "to in-memory (suitable for tests + dev)."
        ),
    )

    native_runtime_org_allowlist: list[str] = Field(
        default_factory=list,
        description=(
            "Per-org canary rollout for the lane-first native runtime "
            "(Phase 14 of #207). Orgs in this list see the native edge "
            "endpoints / runtime even when ``enable_native_runtime=False`` "
            "globally. Case-sensitive exact match against ``X-Organization-ID``."
        ),
    )

    enable_native_stream_dispatch: bool = Field(
        default=False,
        description=(
            "Wrap /api/v1/chat/stream/v3 with native_stream_dispatch "
            "(Phase 30 of #207). When True, the SSE pipeline records "
            "user_message + assistant_message events to the durable "
            "session log around every stream, fires lifecycle hooks, "
            "and lands runtime.native_stream_dispatch.* metrics. "
            "Pass-through preserves the SSE wire shape exactly."
        ),
    )

    enable_stream_smoother: bool = Field(
        default=False,
        description=(
            "Route answer_delta events through the boundary-aware "
            "StreamSmoother (Phase 33a/34 of #207). When True, raw "
            "provider chunks are batched at sentence/punctuation "
            "boundaries so the UI repaints with even cadence. Default "
            "off so the legacy direct-emit path is preserved until "
            "the team flips the flag for canary."
        ),
    )

    enable_casual_fast_path: bool = Field(
        default=False,
        description=(
            "When the casual_intent classifier scores >= 0.85 AND no "
            "tools are explicitly requested, skip multi-agent (guardian "
            "+ supervisor) and call light-tier LLM directly (Phase 33b/34 "
            "of #207). Cuts TTFT 22-30s -> ~5s for casual greetings."
        ),
    )

    enable_episodic_retrieval: bool = Field(
        default=False,
        description=(
            "Surface keyword-matching prior turns from the same user's "
            "session_events into the system prompt as a 'Trí nhớ từ "
            "các phiên trước' block (Phase 33c/34 of #207). Cross-"
            "session episodic recall."
        ),
    )

    enable_otlp_export: bool = Field(
        default=False,
        description=(
            "Forward Phase 24 spans to an OTLP gRPC collector "
            "(Phase 29 of #207). Requires "
            "``opentelemetry-exporter-otlp-proto-grpc`` installed; if "
            "the lib is missing the processor degrades to no-op + logs "
            "a startup warning. Default off."
        ),
    )

    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description=(
            "Target OTLP gRPC endpoint when ``enable_otlp_export=True`` "
            "(Phase 29 of #207). Defaults to a local collector — change "
            "this for production (e.g. https://traces.example.com:4317)."
        ),
    )

    otlp_service_name: str = Field(
        default="wiii-runtime",
        description=(
            "Resource attribute ``service.name`` reported on every "
            "exported span. Useful when several Wiii services share one "
            "OTLP backend."
        ),
    )

    enable_prometheus_metrics: bool = Field(
        default=False,
        description=(
            "Expose ``GET /metrics`` in Prometheus text format (Phase 16 "
            "of #207). Drains the runtime_metrics façade snapshot. Default "
            "off so unconfigured deployments don't accidentally publish "
            "internal metric names."
        ),
    )

    # Issue #206 — bound sync supervisor structured-route call.
    supervisor_route_sync_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Bound (s) for sync SupervisorAgent._route_structured before falling back to rule-based routing.",
    )

    # Google Gemini OpenAI-compatible endpoint URL
    google_openai_compat_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        description="Google Gemini OpenAI-compatible endpoint URL"
    )

    # Agentic Loop
    enable_agentic_loop: bool = Field(default=True, description="Enable generalized agentic loop")
    agentic_loop_max_steps: int = Field(default=8, ge=1, le=20, description="Max tool-calling steps per agentic loop")

    # Per-Agent Provider Config
    agent_provider_configs: str = Field(
        default="{}",
        description='JSON per-node overrides: {"tutor_agent": {"tier": "moderate", "provider": "google"}}'
    )
    agent_runtime_profiles: str = Field(
        default="{}",
        description='JSON grouped runtime profiles: {"routing": {"default_provider": "google", "tier": "light", "provider_models": {}}}',
    )

    # Neo4j (Legacy — reserved for future Learning Graph)
    enable_neo4j: bool = Field(default=False, description="Enable Neo4j graph database (legacy, reserved for Learning Graph)")

    # Subagent Architecture (Sprint 163)
    enable_subagent_architecture: bool = Field(default=True, description="Enable subagent/subgraph architecture")
    subagent_default_timeout: int = Field(default=60, ge=10, le=300, description="Default subagent timeout (seconds)")
    subagent_max_parallel: int = Field(default=5, ge=1, le=10, description="Max parallel subagent executions")

    # WiiiRunner (custom orchestration runtime)
    enable_runner_hooks: bool = Field(default=True, description="Enable lifecycle hooks (logging + metrics) in WiiiRunner")

    # Agent Handoffs (inspired by OpenAI Agents SDK)
    enable_agent_handoffs: bool = Field(default=True, description="Enable agent-to-agent handoffs via tool calls")
    agent_handoff_max_count: int = Field(default=2, ge=1, le=5, description="Max handoffs per request to prevent ping-pong")

    # Concurrent Tool Execution (inspired by Claude Code)
    enable_concurrent_tool_execution: bool = Field(default=False, description="Execute read-only tool calls concurrently within a single LLM turn")
    concurrent_tool_max_workers: int = Field(default=10, ge=1, le=20, description="Max concurrent read-only tool executions")

    # MCP Support
    enable_mcp_server: bool = Field(default=False, description="Enable MCP Server")
    enable_mcp_client: bool = Field(default=False, description="Enable MCP Client")
    mcp_server_configs: str = Field(default="[]", description="JSON list of external MCP server configs")

    # MCP Tool Server (Sprint 193)
    enable_mcp_tool_server: bool = Field(default=False, description="Expose individual tools as MCP tool definitions")
    mcp_auto_register_external: bool = Field(default=False, description="Auto-register MCP external tools into ToolRegistry")

    # Structured Outputs
    enable_structured_outputs: bool = Field(default=True, description="Enable structured outputs")

    # Multi-Tenant
    enable_multi_tenant: bool = Field(default=False, description="Enable multi-organization support")
    default_organization_id: str = Field(default="default", description="Default org for unauthenticated users")
    enable_rls: bool = Field(default=False, description="Enable PostgreSQL Row-Level Security (requires enable_multi_tenant)")
