"""
Pytest Configuration and Fixtures for Wiii Tests

Sprint 154: Expanded with shared factory fixtures to reduce mock duplication.
16 test files previously redefined mock_settings independently — now shared.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from hypothesis import settings as hypothesis_settings

# Configure Hypothesis profiles
hypothesis_settings.register_profile("ci", max_examples=100, deadline=None)
hypothesis_settings.register_profile("dev", max_examples=50, deadline=5000)
hypothesis_settings.load_profile("dev")


@pytest.fixture
def sample_user_id():
    """Sample user ID for testing"""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def sample_chat_message():
    """Sample chat message for testing"""
    return "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng"


@pytest.fixture
def mock_settings():
    """Mock Settings with sensible defaults.

    All feature flags default to False to prevent side effects.
    Use this instead of creating MagicMock() per test file.
    """
    s = MagicMock()
    # Feature flags — all off by default
    s.enable_product_search = False
    s.enable_browser_scraping = False
    s.enable_browser_screenshots = False
    s.enable_soul_emotion = False
    s.enable_thinking_chain = False
    s.enable_tiktok_native_api = False
    s.enable_character_tools = True
    s.enable_character_reflection = True
    s.enable_code_execution = False
    s.enable_corrective_rag = True
    s.enable_agentic_loop = True
    s.enable_structured_outputs = True
    s.enable_core_memory_block = True
    s.enable_memory_decay = True
    s.enable_memory_pruning = True
    s.enable_semantic_fact_retrieval = True
    s.enable_enhanced_extraction = True
    s.enable_langsmith = False
    s.enable_websocket = False
    s.enable_telegram = False
    s.enable_multi_tenant = False
    s.enable_lms_integration = False
    s.lms_base_url = None
    s.lms_service_token = None
    s.lms_webhook_secret = None
    s.lms_api_timeout = 10
    s.lms_connectors = "[]"
    s.thinking_enabled = True
    s.semantic_memory_enabled = True
    s.deep_reasoning_enabled = True
    s.use_multi_agent = True

    # LLM
    s.google_api_key = "test-key"
    s.llm_provider = "google"
    s.google_model = "gemini-3-flash-preview"
    s.openai_api_key = None
    s.openai_model = "gpt-4o-mini"
    s.openai_model_advanced = "gpt-4o"
    s.openai_base_url = None
    s.openrouter_model_fallbacks = []
    s.openrouter_provider_order = []
    s.openrouter_allowed_providers = []
    s.openrouter_ignored_providers = []
    s.openrouter_allow_fallbacks = None
    s.openrouter_require_parameters = None
    s.openrouter_data_collection = None
    s.openrouter_zdr = None
    s.openrouter_provider_sort = None
    s.ollama_model = "qwen3:8b"
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_thinking_models = ["qwen3", "deepseek-r1", "qwq"]
    s.llm_failover_chain = ["google", "openai", "ollama"]
    s.enable_llm_failover = True

    # Embeddings
    s.embedding_provider = "google"
    s.embedding_failover_chain = ["google", "openai", "ollama", "openrouter"]
    s.embedding_model = "models/gemini-embedding-001"
    s.embedding_dimensions = 768

    # RAG
    s.rag_confidence_high = 0.70
    s.rag_confidence_medium = 0.60
    s.rag_quality_mode = "balanced"
    s.rag_max_iterations = 2
    s.rag_enable_reflection = True
    s.rag_early_exit_on_high_confidence = True
    s.multi_agent_grading_threshold = 6.0
    s.retrieval_grade_threshold = 7.0
    s.enable_answer_verification = True
    s.quality_skip_threshold = 0.85

    # Thinking
    s.thinking_budget_deep = 8192
    s.thinking_budget_moderate = 4096
    s.thinking_budget_light = 1024
    s.thinking_budget_minimal = 512
    s.gemini_thinking_level = "medium"
    s.include_thought_summaries = True

    # Memory
    s.max_user_facts = 50
    s.max_injected_facts = 5
    s.fact_injection_min_confidence = 0.5
    s.core_memory_max_tokens = 800
    s.core_memory_cache_ttl = 300
    s.character_cache_ttl = 60
    s.memory_prune_threshold = 0.1
    s.fact_retrieval_alpha = 0.3
    s.fact_retrieval_beta = 0.5
    s.fact_retrieval_gamma = 0.2
    s.fact_min_similarity = 0.3

    # Character
    s.character_reflection_interval = 5
    s.character_reflection_threshold = 5.0
    s.character_experience_retention_days = 90
    s.character_experience_keep_min = 100
    s.enable_emotional_state = False
    s.emotional_decay_rate = 0.15

    # Product search
    s.serper_api_key = None
    s.apify_api_token = None
    s.product_search_max_results = 30
    s.product_search_timeout = 30
    s.product_search_platforms = [
        "google_shopping", "shopee", "tiktok_shop", "lazada",
        "facebook_marketplace", "all_web", "instagram", "websosanh",
    ]
    s.product_search_max_iterations = 15
    s.product_search_scrape_timeout = 10
    s.product_search_max_scrape_pages = 10
    s.browser_scraping_timeout = 15
    s.browser_screenshot_quality = 40

    # Domain
    s.default_domain = "maritime"
    s.active_domains = ["maritime", "traffic_law"]

    # Agentic loop
    s.agentic_loop_max_steps = 8

    # Cache
    s.semantic_cache_enabled = True
    s.cache_similarity_threshold = 0.92

    # App
    s.environment = "development"
    s.debug = False
    s.api_key = "test-api-key"
    s.log_level = "INFO"

    return s


@pytest.fixture
def mock_llm():
    """Mock LangChain LLM (no spec — ABC restricts methods)."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="test response"))
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def mock_embeddings():
    """Mock embedding model returning fixed-dimension vectors."""
    embeddings = MagicMock()
    embeddings.embed_query = MagicMock(return_value=[0.1] * 768)
    embeddings.embed_documents = MagicMock(return_value=[[0.1] * 768])
    return embeddings
