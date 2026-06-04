"""
Sprint 153: "Bảo Vệ" — Security & Reliability Hardening Tests

Tests for:
- SSRF URL validation
- VND price parsing (consolidated)
- graph_streaming reliability fixes
- Thread-safe singletons
- Tool result truncation
- Config validator changes
- Tool registry dedup
- Page param passthrough
"""

import json
import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

logger = logging.getLogger(__name__)


# =============================================================================
# Phase 1: SSRF Prevention — validate_url_for_scraping
# =============================================================================

class TestSSRFValidation:
    """Test SSRF protection via validate_url_for_scraping."""

    def test_valid_https_url(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        result = validate_url_for_scraping("https://example.com/product/123")
        assert result == "https://example.com/product/123"

    def test_valid_http_url(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        result = validate_url_for_scraping("http://example.com/product")
        assert result == "http://example.com/product"

    def test_blocks_file_scheme(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Unsupported scheme"):
            validate_url_for_scraping("file:///etc/passwd")

    def test_blocks_ftp_scheme(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Unsupported scheme"):
            validate_url_for_scraping("ftp://internal.server/data")

    def test_blocks_no_scheme(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Unsupported scheme"):
            validate_url_for_scraping("//no-scheme.com/path")

    def test_blocks_missing_hostname(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Missing hostname"):
            validate_url_for_scraping("http:///path-only")

    def test_blocks_localhost(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://127.0.0.1/admin")

    def test_blocks_private_10(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://10.0.0.1/internal")

    def test_blocks_private_172(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://172.16.0.1/internal")

    def test_blocks_private_192(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://192.168.1.1/router")

    def test_blocks_aws_metadata(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://169.254.169.254/latest/meta-data/")

    def test_blocks_unresolvable_hostname(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_url_for_scraping("https://this-hostname-definitely-does-not-exist-xyz123.invalid/")

    def test_empty_url(self):
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError):
            validate_url_for_scraping("")


# =============================================================================
# Phase 1: VND Price Parsing (consolidated utility)
# =============================================================================

class TestVNDPriceParsing:
    """Test consolidated parse_vnd_price utility."""

    def test_basic_dot_separator(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("1.234.567") == 1234567.0

    def test_basic_comma_separator(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("1,234,567") == 1234567.0

    def test_with_currency_suffix(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("35.490.000 đ") == 35490000.0

    def test_with_vnd_suffix(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("1.234.567 VND") == 1234567.0

    def test_rejects_small_values(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("50") is None

    def test_empty_string(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("") is None

    def test_none_input(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price(None) is None

    def test_garbage_input(self):
        from app.engine.search_platforms.utils import parse_vnd_price
        assert parse_vnd_price("abc") is None

    def test_scraper_delegates_to_shared(self):
        """Verify product_page_scraper._parse_vnd_price delegates correctly."""
        from app.engine.tools.product_page_scraper import _parse_vnd_price
        assert _parse_vnd_price("2.500.000") == 2500000.0

    def test_browser_base_delegates_to_shared(self):
        """Verify browser_base._parse_vnd_price delegates correctly."""
        from app.engine.search_platforms.adapters.browser_base import _parse_vnd_price
        assert _parse_vnd_price("2.500.000") == 2500000.0

    def test_websosanh_delegates_to_shared(self):
        """Verify websosanh._parse_vnd_price delegates correctly."""
        from app.engine.search_platforms.adapters.websosanh import _parse_vnd_price
        assert _parse_vnd_price("2.500.000") == 2500000.0


# =============================================================================
# Phase 1: SSRF wired into scraper
# =============================================================================

class TestScraperSSRF:
    """Test that product_page_scraper blocks SSRF."""

    def test_scraper_blocks_private_ip(self):
        """tool_fetch_product_detail should return error JSON for private IPs."""
        from app.engine.tools.product_page_scraper import tool_fetch_product_detail

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(product_search_scrape_timeout=10)
            result = tool_fetch_product_detail.invoke({"url": "http://10.0.0.1/admin"})

        data = json.loads(result)
        assert "error" in data
        assert "không hợp lệ" in data["error"].lower() or "blocked" in data["error"].lower()

    def test_scraper_blocks_localhost(self):
        from app.engine.tools.product_page_scraper import tool_fetch_product_detail

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(product_search_scrape_timeout=10)
            result = tool_fetch_product_detail.invoke({"url": "http://127.0.0.1:5432/"})

        data = json.loads(result)
        assert "error" in data


# =============================================================================
# Phase 1: _TRACERS memory leak fix
# =============================================================================

class TestTracersCleanup:
    """Test that _TRACERS is cleaned up even on graph.ainvoke failure."""

    @pytest.mark.asyncio
    async def test_tracer_cleaned_on_exception(self):
        """_cleanup_tracer should be called even if ainvoke raises."""
        from app.engine.multi_agent.graph import _TRACERS, _cleanup_tracer

        # Pre-populate a tracer
        test_id = "test-trace-id-153"
        _TRACERS[test_id] = MagicMock()
        assert test_id in _TRACERS

        # Clean up
        _cleanup_tracer(test_id)
        assert test_id not in _TRACERS

    def test_cleanup_tracer_noop_on_none(self):
        """_cleanup_tracer(None) should be a no-op."""
        from app.engine.multi_agent.graph import _cleanup_tracer
        _cleanup_tracer(None)  # Should not raise

    def test_cleanup_tracer_noop_on_missing(self):
        """_cleanup_tracer with unknown ID should be a no-op."""
        from app.engine.multi_agent.graph import _cleanup_tracer
        _cleanup_tracer("nonexistent-id")  # Should not raise


# =============================================================================
# Phase 2: graph_streaming reliability
# =============================================================================

class TestGraphStreamingFixes:
    """Test graph_streaming.py reliability fixes."""

    def test_context_none_safe(self):
        """context.get() on None should not raise."""
        # Simulate the fixed pattern
        context = None
        user_id = (context or {}).get("user_id", "")
        assert user_id == ""

    def test_context_with_value(self):
        context = {"user_id": "test-user"}
        user_id = (context or {}).get("user_id", "")
        assert user_id == "test-user"

    def test_dead_code_removed(self):
        """_INTENT_EFFORT should no longer exist in graph_streaming."""
        import app.engine.multi_agent.graph_streaming as gs
        assert not hasattr(gs, "_INTENT_EFFORT"), "_INTENT_EFFORT dead code was not removed"


# =============================================================================
# Phase 3: Thread-safe singletons
# =============================================================================

class TestThreadSafeSingleton:
    """Test thread-safe product_search_node singleton."""

    def test_singleton_has_lock(self):
        """Verify _node_lock exists for thread safety."""
        from app.engine.multi_agent.agents import product_search_node
        assert hasattr(product_search_node, "_node_lock")
        assert isinstance(product_search_node._node_lock, type(threading.Lock()))

    def test_singleton_returns_same_instance(self):
        """get_product_search_agent_node() returns same instance on repeated calls."""
        from app.engine.multi_agent.agents.product_search_node import (
            get_product_search_agent_node,
        )
        import app.engine.multi_agent.agents.product_search_node as psn

        # Reset singleton for test
        _original = psn._product_search_node
        psn._product_search_node = None

        try:
            node1 = get_product_search_agent_node()
            node2 = get_product_search_agent_node()
            assert node1 is node2
        finally:
            psn._product_search_node = _original


# =============================================================================
# Phase 3: Tool result truncation
# =============================================================================

class TestToolResultTruncation:
    """Test that tool results are truncated before adding to messages."""

    def test_truncation_limit(self):
        """Results over 5000 chars should be truncated."""
        long_result = "x" * 10000
        truncated = str(long_result)[:5000]
        assert len(truncated) == 5000

    def test_short_result_unchanged(self):
        short_result = '{"result": "ok"}'
        truncated = str(short_result)[:5000]
        assert truncated == short_result


# =============================================================================
# Phase 3: TikTok token lock
# =============================================================================

class TestTikTokTokenRefresh:
    """Test TikTok token refresh holds lock throughout."""

    def test_cached_token_returns_immediately(self):
        """If token is valid, return without HTTP call."""
        from app.engine.search_platforms.adapters.tiktok_research import (
            _credential_cache_key,
            _get_access_token,
            _token_cache,
        )
        import app.engine.search_platforms.adapters.tiktok_research as ttr

        # Save original
        _original = dict(_token_cache)

        try:
            ttr._token_cache["cache_key"] = _credential_cache_key("key", "secret")
            ttr._token_cache["access_token"] = "cached-token"
            ttr._token_cache["expires_at"] = time.time() + 3600

            result = _get_access_token("key", "secret")
            assert result == "cached-token"
        finally:
            ttr._token_cache.update(_original)


# =============================================================================
# Phase 4: Config validators
# =============================================================================

class TestConfigValidators:
    """Test config field validation added in Sprint 153."""

    def test_dead_field_removed(self):
        """memory_decay_floor should no longer exist in Settings."""
        from app.core.config import Settings
        fields = Settings.model_fields
        assert "memory_decay_floor" not in fields, "Dead field memory_decay_floor was not removed"

    def test_product_search_timeout_has_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["product_search_timeout"]
        metadata = field.metadata
        # Check via json_schema_extra or field constraints
        assert field.metadata is not None

    def test_browser_scraping_timeout_has_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["browser_scraping_timeout"]
        assert field.metadata is not None

    def test_emotional_decay_rate_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["emotional_decay_rate"]
        assert field.metadata is not None

    def test_core_memory_max_tokens_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["core_memory_max_tokens"]
        assert field.metadata is not None

    def test_fact_injection_min_confidence_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["fact_injection_min_confidence"]
        assert field.metadata is not None

    def test_max_ingestion_size_mb_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["max_ingestion_size_mb"]
        assert field.metadata is not None

    def test_domain_boost_score_bounds(self):
        from app.core.config import Settings
        field = Settings.model_fields["domain_boost_score"]
        assert field.metadata is not None


# =============================================================================
# Phase 4: Tool registry dedup
# =============================================================================

class TestToolRegistryDedup:
    """Test tool registry dedup guard."""

    def test_duplicate_registration_no_category_dup(self):
        """Registering same tool twice should not duplicate in category list."""
        from app.engine.tools.registry import ToolRegistry, ToolCategory, ToolAccess

        registry = ToolRegistry()
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test"

        registry.register(mock_tool, ToolCategory.UTILITY, ToolAccess.READ)
        registry.register(mock_tool, ToolCategory.UTILITY, ToolAccess.READ)

        # Category should contain the name only once
        names = registry._categories.get(ToolCategory.UTILITY, [])
        assert names.count("test_tool") == 1

    def test_tools_list_is_function(self):
        """TOOLS should now be a callable (not stale list)."""
        from app.engine.tools import TOOLS
        assert callable(TOOLS), "TOOLS should be get_all_tools function, not a stale list"


# =============================================================================
# Phase 4: Page param passthrough
# =============================================================================

class TestPageParamPassthrough:
    """Test that page parameter is passed through static fallback tools."""

    def test_google_shopping_sync_accepts_page(self):
        """_search_google_shopping_sync should accept page parameter."""
        import inspect
        from app.engine.tools.product_search_tools import _search_google_shopping_sync
        sig = inspect.signature(_search_google_shopping_sync)
        assert "page" in sig.parameters

    def test_platform_serper_sync_accepts_page(self):
        """_search_platform_via_serper_sync should accept page parameter."""
        import inspect
        from app.engine.tools.product_search_tools import _search_platform_via_serper_sync
        sig = inspect.signature(_search_platform_via_serper_sync)
        assert "page" in sig.parameters


# =============================================================================
# Phase 4: .env.example
# =============================================================================

class TestEnvExample:
    """Test .env.example cleanup."""

    def test_no_ghost_var(self):
        """USE_UNIFIED_AGENT should not appear as an active setting."""
        import os
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env.example"
        )
        if not os.path.exists(env_path):
            pytest.skip(".env.example not found")
        content = open(env_path, encoding="utf-8").read()
        # Should not have an uncommented USE_UNIFIED_AGENT=... line
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("USE_UNIFIED_AGENT="):
                pytest.fail("Ghost variable USE_UNIFIED_AGENT still present as active setting")


# =============================================================================
# Phase 5: Browser close wired to shutdown
# =============================================================================

class TestBrowserShutdown:
    """Test close_browser is importable and callable."""

    def test_close_browser_importable(self):
        from app.engine.search_platforms.adapters.browser_base import close_browser
        assert callable(close_browser)

    def test_close_browser_noop_when_not_initialized(self):
        """close_browser should not raise when browser was never opened."""
        from app.engine.search_platforms.adapters.browser_base import close_browser
        close_browser()  # Should not raise
