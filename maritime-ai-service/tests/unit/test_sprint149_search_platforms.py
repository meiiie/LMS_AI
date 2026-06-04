"""
Tests for Sprint 149: "Cắm & Chạy" — Search Platform Plugin Architecture

Covers:
- ABC & data models (BackendType, PlatformConfig, ProductSearchResult)
- SearchPlatformRegistry singleton (register, get, get_all_enabled, list_ids)
- PerPlatformCircuitBreaker (open/close, isolation, recovery, reset)
- SerperShoppingAdapter (success, no key, HTTP error, config)
- SerperSiteAdapter (Shopee/Lazada/TikTok/FB/IG site filters)
- SerperAllWebAdapter (excludes platforms, config)
- TikTokResearchAdapter (native search, fallback, token auth)
- ApifyGenericAdapter (actor run, dataset fetch, normalization)
- Tool auto-generation (name, output format, CB integration)
- init_search_platforms() flow (registry population, platform filtering, TikTok mode)
- Config additions (product_search_platforms, tiktok_*, oauth_*)
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.engine.search_platforms.base import (
    BackendType,
    PlatformConfig,
    ProductSearchResult,
    SearchPlatformAdapter,
)
from app.engine.search_platforms.registry import (
    SearchPlatformRegistry,
    get_search_platform_registry,
)
from app.engine.search_platforms.circuit_breaker import PerPlatformCircuitBreaker


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry singleton between tests."""
    import app.engine.search_platforms.registry as reg_mod
    old = reg_mod._registry_instance
    reg_mod._registry_instance = None
    yield
    reg_mod._registry_instance = old


@pytest.fixture
def mock_settings():
    """Settings with product search enabled and all platforms."""
    s = MagicMock()
    s.enable_product_search = True
    s.serper_api_key = "test-serper-key"
    s.apify_api_token = "test-apify-token"
    s.product_search_max_results = 30
    s.product_search_timeout = 10
    s.enable_tiktok_native_api = False
    s.tiktok_client_key = None
    s.tiktok_client_secret = None
    s.enable_browser_scraping = False
    s.product_search_platforms = [
        "google_shopping", "shopee", "tiktok_shop",
        "lazada", "facebook_marketplace", "all_web", "instagram",
    ]
    return s


@pytest.fixture
def mock_settings_tiktok_native(mock_settings):
    """Settings with TikTok native API enabled."""
    mock_settings.enable_tiktok_native_api = True
    mock_settings.tiktok_client_key = "test-tiktok-key"
    mock_settings.tiktok_client_secret = "test-tiktok-secret"
    return mock_settings


class _DummyAdapter(SearchPlatformAdapter):
    """Concrete adapter for testing ABC."""
    def __init__(self, platform_id="dummy", enabled=True):
        self._id = platform_id
        self._enabled = enabled

    def get_config(self):
        return PlatformConfig(
            id=self._id, display_name=f"Dummy {self._id}",
            backend=BackendType.CUSTOM, enabled=self._enabled,
        )

    def search_sync(self, query, max_results=20, page=1):
        return [ProductSearchResult(platform=f"Dummy {self._id}", title=f"Result for {query}")]


# =============================================================================
# 1. ABC & Data Models
# =============================================================================


class TestBackendType:
    def test_all_backend_types_exist(self):
        assert BackendType.SERPER.value == "serper"
        assert BackendType.SERPER_SITE.value == "serper_site"
        assert BackendType.NATIVE_API.value == "native_api"
        assert BackendType.APIFY.value == "apify"
        assert BackendType.CUSTOM.value == "custom"


class TestPlatformConfig:
    def test_config_defaults(self):
        c = PlatformConfig(id="test", display_name="Test", backend=BackendType.SERPER)
        assert c.id == "test"
        assert c.enabled is True
        assert c.requires_auth is False
        assert c.fallback_backend is None
        assert c.max_results_default == 20

    def test_config_with_site_filter(self):
        c = PlatformConfig(
            id="shopee", display_name="Shopee",
            backend=BackendType.SERPER_SITE, site_filter="site:shopee.vn",
        )
        assert c.site_filter == "site:shopee.vn"


class TestProductSearchResult:
    def test_result_to_dict_omits_empty(self):
        r = ProductSearchResult(platform="Test", title="Widget", price="100₫", link="https://example.com")
        d = r.to_dict()
        assert d["platform"] == "Test"
        assert d["title"] == "Widget"
        assert d["price"] == "100₫"
        assert d["link"] == "https://example.com"
        assert "seller" not in d
        assert "rating" not in d

    def test_result_to_dict_keeps_platform_title_even_if_empty(self):
        r = ProductSearchResult(platform="", title="")
        d = r.to_dict()
        assert "platform" in d
        assert "title" in d

    def test_result_full_fields(self):
        r = ProductSearchResult(
            platform="Shopee", title="Dây điện", price="450k",
            extracted_price=450000.0, link="https://shopee.vn/123",
            seller="Shop ABC", rating=4.8, sold_count=120,
            reviews=50, image="https://img.shopee.vn/1.jpg",
        )
        d = r.to_dict()
        assert d["extracted_price"] == 450000.0
        assert d["rating"] == 4.8
        assert d["sold_count"] == 120


class TestSearchPlatformAdapterABC:
    def test_adapter_tool_name(self):
        adapter = _DummyAdapter("shopee")
        assert adapter.get_tool_name() == "tool_search_shopee"

    def test_adapter_default_credentials_valid(self):
        adapter = _DummyAdapter()
        assert adapter.validate_credentials() is True


# =============================================================================
# 2. Registry
# =============================================================================


class TestSearchPlatformRegistry:
    def test_register_and_get(self):
        registry = SearchPlatformRegistry()
        adapter = _DummyAdapter("shopee")
        registry.register(adapter)
        assert registry.get("shopee") is adapter
        assert registry.get("nonexistent") is None

    def test_list_ids(self):
        registry = SearchPlatformRegistry()
        registry.register(_DummyAdapter("shopee"))
        registry.register(_DummyAdapter("lazada"))
        assert set(registry.list_ids()) == {"shopee", "lazada"}

    def test_get_all_enabled(self):
        registry = SearchPlatformRegistry()
        registry.register(_DummyAdapter("enabled1", enabled=True))
        registry.register(_DummyAdapter("disabled1", enabled=False))
        registry.register(_DummyAdapter("enabled2", enabled=True))
        enabled = registry.get_all_enabled()
        assert len(enabled) == 2
        ids = [a.get_config().id for a in enabled]
        assert "enabled1" in ids
        assert "enabled2" in ids

    def test_clear(self):
        registry = SearchPlatformRegistry()
        registry.register(_DummyAdapter("x"))
        assert len(registry) == 1
        registry.clear()
        assert len(registry) == 0

    def test_overwrite(self):
        registry = SearchPlatformRegistry()
        a1 = _DummyAdapter("shopee")
        a2 = _DummyAdapter("shopee")
        registry.register(a1)
        registry.register(a2)
        assert registry.get("shopee") is a2

    def test_singleton(self):
        r1 = get_search_platform_registry()
        r2 = get_search_platform_registry()
        assert r1 is r2


# =============================================================================
# 3. Circuit Breaker
# =============================================================================


class TestPerPlatformCircuitBreaker:
    def test_closed_by_default(self):
        cb = PerPlatformCircuitBreaker()
        assert not cb.is_open("shopee")

    def test_opens_after_threshold(self):
        cb = PerPlatformCircuitBreaker(threshold=3, recovery_seconds=120)
        for _ in range(3):
            cb.record_failure("shopee")
        assert cb.is_open("shopee")
        assert not cb.is_open("lazada")  # Isolation

    def test_resets_on_success(self):
        cb = PerPlatformCircuitBreaker(threshold=3)
        cb.record_failure("tiktok")
        cb.record_failure("tiktok")
        cb.record_success("tiktok")
        cb.record_failure("tiktok")
        assert not cb.is_open("tiktok")

    def test_recovery_after_timeout(self):
        cb = PerPlatformCircuitBreaker(threshold=2, recovery_seconds=0.1)
        cb.record_failure("fb")
        cb.record_failure("fb")
        assert cb.is_open("fb")
        time.sleep(0.15)
        assert not cb.is_open("fb")  # Recovery period elapsed

    def test_reset_all(self):
        cb = PerPlatformCircuitBreaker(threshold=1)
        cb.record_failure("a")
        cb.record_failure("b")
        cb.reset()
        assert not cb.is_open("a")
        assert not cb.is_open("b")

    def test_reset_specific(self):
        cb = PerPlatformCircuitBreaker(threshold=1)
        cb.record_failure("a")
        cb.record_failure("b")
        cb.reset("a")
        assert not cb.is_open("a")
        assert cb.is_open("b")

    def test_get_failure_count(self):
        cb = PerPlatformCircuitBreaker()
        assert cb.get_failure_count("x") == 0
        cb.record_failure("x")
        cb.record_failure("x")
        assert cb.get_failure_count("x") == 2


# =============================================================================
# 4. Serper Shopping Adapter
# =============================================================================


class TestSerperShoppingAdapter:
    def test_config(self):
        from app.engine.search_platforms.adapters.serper_shopping import SerperShoppingAdapter
        adapter = SerperShoppingAdapter()
        config = adapter.get_config()
        assert config.id == "google_shopping"
        assert config.backend == BackendType.SERPER
        assert adapter.get_tool_name() == "tool_search_google_shopping"

    def test_search_success(self, mock_settings):
        from app.engine.search_platforms.adapters.serper_shopping import SerperShoppingAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "shopping": [
                {"title": "Dây điện 2.5mm", "price": "450,000₫", "extracted_price": 450000,
                 "source": "shopee.vn", "rating": 4.8, "ratingCount": 120,
                 "link": "https://shopee.vn/123", "imageUrl": "https://img/1.jpg", "delivery": "Free"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("httpx.post", return_value=mock_response):
            adapter = SerperShoppingAdapter()
            results = adapter.search_sync("dây điện", 10)

        assert len(results) == 1
        assert results[0].platform == "Google Shopping"
        assert results[0].extracted_price == 450000
        assert results[0].title == "Dây điện 2.5mm"

    def test_search_no_api_key(self):
        s = MagicMock()
        s.serper_api_key = None

        from app.engine.search_platforms.adapters.serper_shopping import SerperShoppingAdapter
        with patch("app.core.config.get_settings", return_value=s):
            adapter = SerperShoppingAdapter()
            with pytest.raises(ValueError, match="SERPER_API_KEY"):
                adapter.search_sync("test")

    def test_search_http_error(self, mock_settings):
        from app.engine.search_platforms.adapters.serper_shopping import SerperShoppingAdapter
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("httpx.post", return_value=mock_response):
            adapter = SerperShoppingAdapter()
            with pytest.raises(httpx.HTTPStatusError):
                adapter.search_sync("test")


# =============================================================================
# 5. Serper Site Adapter (Shopee/Lazada/etc.)
# =============================================================================


class TestSerperSiteAdapter:
    def test_shopee_config(self):
        from app.engine.search_platforms.adapters.serper_site import create_shopee_adapter
        adapter = create_shopee_adapter()
        config = adapter.get_config()
        assert config.id == "shopee"
        assert config.site_filter == "site:shopee.vn"
        assert adapter.get_tool_name() == "tool_search_shopee"

    def test_lazada_config(self):
        from app.engine.search_platforms.adapters.serper_site import create_lazada_adapter
        adapter = create_lazada_adapter()
        assert adapter.get_config().site_filter == "site:lazada.vn"

    def test_tiktok_serper_config(self):
        from app.engine.search_platforms.adapters.serper_site import create_tiktok_shop_serper_adapter
        adapter = create_tiktok_shop_serper_adapter()
        assert adapter.get_config().site_filter == "site:tiktok.com/shop"

    def test_search_includes_site_filter(self, mock_settings):
        from app.engine.search_platforms.adapters.serper_site import create_shopee_adapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [{"title": "Test", "link": "https://shopee.vn/123", "snippet": "..."}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("httpx.post", return_value=mock_response) as mock_post:
            adapter = create_shopee_adapter()
            results = adapter.search_sync("dây điện")

        assert len(results) == 1
        assert results[0].platform == "Shopee"
        body = mock_post.call_args[1]["json"]
        assert "site:shopee.vn" in body["q"]

    def test_instagram_config(self):
        from app.engine.search_platforms.adapters.serper_site import create_instagram_adapter
        adapter = create_instagram_adapter()
        assert adapter.get_config().id == "instagram"
        assert adapter.get_config().site_filter == "site:instagram.com"


# =============================================================================
# 6. All Web Adapter
# =============================================================================


class TestSerperAllWebAdapter:
    def test_config(self):
        from app.engine.search_platforms.adapters.serper_all_web import SerperAllWebAdapter
        adapter = SerperAllWebAdapter()
        config = adapter.get_config()
        assert config.id == "all_web"
        assert config.display_name == "Web (all)"

    def test_excludes_major_platforms(self, mock_settings):
        from app.engine.search_platforms.adapters.serper_all_web import SerperAllWebAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {"organic": []}
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("httpx.post", return_value=mock_response) as mock_post:
            adapter = SerperAllWebAdapter()
            adapter.search_sync("dây điện")

        body = mock_post.call_args[1]["json"]
        assert "-site:shopee.vn" in body["q"]
        assert "-site:lazada.vn" in body["q"]
        assert "-site:tiki.vn" in body["q"]

    def test_returns_web_platform(self, mock_settings):
        from app.engine.search_platforms.adapters.serper_all_web import SerperAllWebAdapter

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "organic": [{"title": "Shop ABC", "link": "https://abc.vn/123"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("httpx.post", return_value=mock_response):
            adapter = SerperAllWebAdapter()
            results = adapter.search_sync("test")

        assert results[0].platform == "Web"


# =============================================================================
# 7. TikTok Research Adapter
# =============================================================================


class TestTikTokResearchAdapter:
    def test_config(self):
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter
        adapter = TikTokResearchAdapter()
        config = adapter.get_config()
        assert config.id == "tiktok_shop"
        assert config.backend == BackendType.NATIVE_API

    def test_fallback_when_not_enabled(self, mock_settings):
        """Uses Serper fallback when enable_tiktok_native_api=False."""
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter

        mock_fallback = MagicMock()
        mock_fallback.search_sync.return_value = [
            ProductSearchResult(platform="TikTok Shop", title="Via Serper")
        ]

        with patch("app.core.config.get_settings", return_value=mock_settings):
            adapter = TikTokResearchAdapter(serper_fallback=mock_fallback)
            results = adapter.search_sync("test")

        assert len(results) == 1
        assert results[0].title == "Via Serper"
        mock_fallback.search_sync.assert_called_once()

    def test_fallback_when_no_credentials(self, mock_settings_tiktok_native):
        """Falls back when credentials missing despite flag enabled."""
        mock_settings_tiktok_native.tiktok_client_key = None
        mock_settings_tiktok_native.tiktok_client_secret = None

        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter

        mock_fallback = MagicMock()
        mock_fallback.search_sync.return_value = [
            ProductSearchResult(platform="TikTok Shop", title="Fallback")
        ]

        with patch("app.core.config.get_settings", return_value=mock_settings_tiktok_native):
            adapter = TikTokResearchAdapter(serper_fallback=mock_fallback)
            results = adapter.search_sync("test")

        assert results[0].title == "Fallback"

    def test_native_search_success(self, mock_settings_tiktok_native):
        """Native API returns structured product data."""
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter
        import app.engine.search_platforms.adapters.tiktok_research as tt_mod

        # Reset token cache
        tt_mod._token_cache = {"access_token": None, "expires_at": 0.0}

        # Mock token response
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = {
            "access_token": "clt.test123", "expires_in": 7200,
        }
        mock_token_resp.raise_for_status = MagicMock()

        # Mock product search response
        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = {
            "data": {
                "products": [
                    {
                        "title": "Dây điện TikTok",
                        "price": {"formatted_price": "450,000₫", "price": 450000},
                        "product_url": "https://tiktok.com/shop/p/123",
                        "shop_name": "Shop ABC",
                        "rating": 4.9,
                        "sold_count": 500,
                        "cover_image_url": "https://img.tiktok.com/1.jpg",
                    }
                ]
            }
        }
        mock_search_resp.raise_for_status = MagicMock()

        def mock_post(url, **kwargs):
            if "oauth/token" in url:
                return mock_token_resp
            return mock_search_resp

        with patch("app.core.config.get_settings", return_value=mock_settings_tiktok_native), \
             patch("httpx.post", side_effect=mock_post):
            adapter = TikTokResearchAdapter()
            results = adapter.search_sync("dây điện", 10)

        assert len(results) == 1
        assert results[0].platform == "TikTok Shop"
        assert results[0].title == "Dây điện TikTok"
        assert results[0].extracted_price == 450000
        assert results[0].seller == "Shop ABC"
        assert results[0].rating == 4.9
        assert results[0].sold_count == 500

    def test_native_api_error_triggers_fallback(self, mock_settings_tiktok_native):
        """When native API throws, falls back to Serper."""
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter
        import app.engine.search_platforms.adapters.tiktok_research as tt_mod

        tt_mod._token_cache = {"access_token": None, "expires_at": 0.0}

        mock_fallback = MagicMock()
        mock_fallback.search_sync.return_value = [
            ProductSearchResult(platform="TikTok Shop", title="Serper fallback")
        ]

        with patch("app.core.config.get_settings", return_value=mock_settings_tiktok_native), \
             patch("httpx.post", side_effect=Exception("API down")):
            adapter = TikTokResearchAdapter(serper_fallback=mock_fallback)
            results = adapter.search_sync("test")

        assert results[0].title == "Serper fallback"

    def test_no_fallback_raises(self, mock_settings):
        """Raises when no fallback and native not available."""
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter

        with patch("app.core.config.get_settings", return_value=mock_settings):
            adapter = TikTokResearchAdapter(serper_fallback=None)
            with pytest.raises(ValueError, match="not available"):
                adapter.search_sync("test")

    def test_validate_credentials(self, mock_settings_tiktok_native):
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter
        with patch("app.core.config.get_settings", return_value=mock_settings_tiktok_native):
            adapter = TikTokResearchAdapter()
            assert adapter.validate_credentials() is True

    def test_token_caching(self, mock_settings_tiktok_native):
        """Token is cached and reused on subsequent calls."""
        from app.engine.search_platforms.adapters.tiktok_research import _get_access_token
        import app.engine.search_platforms.adapters.tiktok_research as tt_mod

        tt_mod._token_cache = {"access_token": None, "expires_at": 0.0}

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "clt.cached", "expires_in": 7200}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            token1 = _get_access_token("key", "secret")
            token2 = _get_access_token("key", "secret")

        assert token1 == "clt.cached"
        assert token2 == "clt.cached"
        assert mock_post.call_count == 1  # Only one HTTP call (cached)

    def test_token_cache_is_bound_to_credentials(self):
        """Cached token is not reused after client credentials change."""
        from app.engine.search_platforms.adapters.tiktok_research import _get_access_token
        import app.engine.search_platforms.adapters.tiktok_research as tt_mod

        tt_mod._token_cache = {"cache_key": None, "access_token": None, "expires_at": 0.0}

        first_resp = MagicMock()
        first_resp.json.return_value = {"access_token": "clt.first", "expires_in": 7200}
        first_resp.raise_for_status = MagicMock()
        second_resp = MagicMock()
        second_resp.json.return_value = {"access_token": "clt.second", "expires_in": 7200}
        second_resp.raise_for_status = MagicMock()

        with patch("httpx.post", side_effect=[first_resp, second_resp]) as mock_post:
            first = _get_access_token("key-a", "secret-a")
            second = _get_access_token("key-b", "secret-b")

        assert first == "clt.first"
        assert second == "clt.second"
        assert mock_post.call_count == 2
        assert mock_post.call_args_list[0].kwargs["data"]["client_secret"] == "secret-a"
        assert mock_post.call_args_list[1].kwargs["data"]["client_secret"] == "secret-b"
        assert tt_mod._token_cache["access_token"] == "clt.second"
        assert "secret-b" not in str(tt_mod._token_cache["cache_key"])
        assert "key-b" not in str(tt_mod._token_cache["cache_key"])




# =============================================================================
# 9. Tool Auto-Generation
# =============================================================================


class TestToolGeneration:
    def test_build_platform_tool_name(self):
        from app.engine.tools.product_search_tools import _build_platform_tool
        adapter = _DummyAdapter("shopee")
        cb = PerPlatformCircuitBreaker()
        t = _build_platform_tool(adapter, cb)
        assert t.name == "tool_search_shopee"

    def test_build_platform_tool_output_format(self):
        from app.engine.tools.product_search_tools import _build_platform_tool
        adapter = _DummyAdapter("shopee")
        cb = PerPlatformCircuitBreaker()
        t = _build_platform_tool(adapter, cb)
        result = json.loads(t.invoke({"query": "test", "max_results": 5}))
        assert "platform" in result
        assert "results" in result
        assert "count" in result
        assert result["count"] >= 1

    def test_build_platform_tool_circuit_breaker(self):
        from app.engine.tools.product_search_tools import _build_platform_tool
        adapter = _DummyAdapter("test_cb")
        cb = PerPlatformCircuitBreaker(threshold=1)
        cb.record_failure("test_cb")
        t = _build_platform_tool(adapter, cb)
        result = json.loads(t.invoke({"query": "test"}))
        assert "error" in result
        assert "không khả dụng" in result["error"]

    def test_build_platform_tool_error_records_failure(self):
        """Tool records CB failure on adapter exception."""
        from app.engine.tools.product_search_tools import _build_platform_tool

        class FailAdapter(SearchPlatformAdapter):
            def get_config(self):
                return PlatformConfig(id="fail", display_name="Fail", backend=BackendType.CUSTOM)
            def search_sync(self, query, max_results=20):
                raise RuntimeError("API error")

        cb = PerPlatformCircuitBreaker()
        t = _build_platform_tool(FailAdapter(), cb)
        result = json.loads(t.invoke({"query": "test"}))
        assert "error" in result
        assert cb.get_failure_count("fail") == 1

    def test_generated_tools_count(self, mock_settings):
        """Auto-generates correct number of tools from registry."""
        from app.engine.search_platforms import init_search_platforms
        from app.engine.tools.product_search_tools import _build_platform_tool

        with patch("app.core.config.get_settings", return_value=mock_settings):
            registry = init_search_platforms()

        cb = PerPlatformCircuitBreaker()
        tools = [_build_platform_tool(a, cb) for a in registry.get_all_enabled()]
        assert len(tools) == 7  # All 7 platforms

    def test_tool_names_match_sprint148(self, mock_settings):
        """Tool names are backward compatible with Sprint 148."""
        from app.engine.search_platforms import init_search_platforms
        from app.engine.tools.product_search_tools import _build_platform_tool

        with patch("app.core.config.get_settings", return_value=mock_settings):
            registry = init_search_platforms()

        cb = PerPlatformCircuitBreaker()
        tool_names = {_build_platform_tool(a, cb).name for a in registry.get_all_enabled()}
        expected = {
            "tool_search_google_shopping", "tool_search_shopee", "tool_search_tiktok_shop",
            "tool_search_lazada", "tool_search_facebook_marketplace",
            "tool_search_all_web", "tool_search_instagram",
        }
        assert tool_names == expected


# =============================================================================
# 10. init_search_platforms()
# =============================================================================


class TestInitSearchPlatforms:
    def test_registers_all_platforms(self, mock_settings):
        from app.engine.search_platforms import init_search_platforms

        with patch("app.core.config.get_settings", return_value=mock_settings):
            registry = init_search_platforms()

        assert len(registry) == 7
        assert set(registry.list_ids()) == {
            "google_shopping", "shopee", "tiktok_shop",
            "lazada", "facebook_marketplace", "all_web", "instagram",
        }

    def test_respects_platform_filter(self, mock_settings):
        """Only registers platforms in product_search_platforms list."""
        mock_settings.product_search_platforms = ["google_shopping", "shopee"]

        from app.engine.search_platforms import init_search_platforms

        with patch("app.core.config.get_settings", return_value=mock_settings):
            registry = init_search_platforms()

        assert len(registry) == 2
        assert "lazada" not in registry.list_ids()

    def test_tiktok_native_mode(self, mock_settings_tiktok_native):
        """TikTok uses native adapter when enabled."""
        from app.engine.search_platforms import init_search_platforms
        from app.engine.search_platforms.adapters.tiktok_research import TikTokResearchAdapter

        with patch("app.core.config.get_settings", return_value=mock_settings_tiktok_native):
            registry = init_search_platforms()

        adapter = registry.get("tiktok_shop")
        assert isinstance(adapter, TikTokResearchAdapter)
        assert adapter.get_config().backend == BackendType.NATIVE_API

    def test_tiktok_serper_mode(self, mock_settings):
        """TikTok uses Serper site: filter when native disabled."""
        from app.engine.search_platforms import init_search_platforms
        from app.engine.search_platforms.adapters.serper_site import SerperSiteAdapter

        with patch("app.core.config.get_settings", return_value=mock_settings):
            registry = init_search_platforms()

        adapter = registry.get("tiktok_shop")
        assert isinstance(adapter, SerperSiteAdapter)
        assert adapter.get_config().backend == BackendType.SERPER_SITE


# =============================================================================
# 11. Config Additions
# =============================================================================


class TestConfigAdditions:
    def test_sprint149_config_fields_exist(self):
        from app.core.config import Settings
        fields = Settings.model_fields
        assert "product_search_platforms" in fields
        assert "enable_tiktok_native_api" in fields
        assert "tiktok_client_key" in fields
        assert "tiktok_client_secret" in fields
        assert "enable_oauth_token_store" in fields
        assert "oauth_encryption_key" in fields

    def test_sprint149_config_defaults(self):
        from app.core.config import Settings
        assert Settings.model_fields["enable_tiktok_native_api"].default is False
        assert Settings.model_fields["enable_oauth_token_store"].default is False
        assert "google_shopping" in Settings.model_fields["product_search_platforms"].default


# =============================================================================
# 12. OAuth Token Store (Skeleton)
# =============================================================================


class TestOAuthTokenStore:
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self):
        from app.engine.search_platforms.oauth.token_store import OAuthTokenStore, OAuthToken
        store = OAuthTokenStore()
        token = OAuthToken(user_id="u1", platform_id="shopee", access_token="abc123")
        await store.store_token(token)
        retrieved = await store.get_token("u1", "shopee")
        assert retrieved is not None
        assert retrieved.access_token == "abc123"

    @pytest.mark.asyncio
    async def test_delete_token(self):
        from app.engine.search_platforms.oauth.token_store import OAuthTokenStore, OAuthToken
        store = OAuthTokenStore()
        token = OAuthToken(user_id="u1", platform_id="lazada", access_token="xyz")
        await store.store_token(token)
        deleted = await store.delete_token("u1", "lazada")
        assert deleted is True
        assert await store.get_token("u1", "lazada") is None

    @pytest.mark.asyncio
    async def test_has_valid_token(self):
        import time
        from app.engine.search_platforms.oauth.token_store import OAuthTokenStore, OAuthToken
        store = OAuthTokenStore()

        # Valid token
        token = OAuthToken(
            user_id="u1", platform_id="shopee",
            access_token="abc", expires_at=time.time() + 3600,
        )
        await store.store_token(token)
        assert await store.has_valid_token("u1", "shopee") is True

        # Expired token
        expired = OAuthToken(
            user_id="u2", platform_id="shopee",
            access_token="old", expires_at=time.time() - 1,
        )
        await store.store_token(expired)
        assert await store.has_valid_token("u2", "shopee") is False

    @pytest.mark.asyncio
    async def test_nonexistent_token(self):
        from app.engine.search_platforms.oauth.token_store import OAuthTokenStore
        store = OAuthTokenStore()
        assert await store.has_valid_token("nobody", "nothing") is False
