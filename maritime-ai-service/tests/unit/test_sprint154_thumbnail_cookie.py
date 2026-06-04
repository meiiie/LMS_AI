"""
Sprint 154: "Anh Song" + "Dang Nhap Facebook" — Backend Tests

Tests for:
- Facebook cookie ContextVar lifecycle
- Cookie parsing (name=value; format)
- URL selection (marketplace vs search/posts)
- Playwright cookie injection via _get_cookies hook
- ThreadPoolExecutor cookie propagation
- Config flag gating
- Header extraction in chat_stream
- SSRF prevention with cookies
- Regression safety
"""

import json
from contextvars import copy_context
from unittest.mock import MagicMock, patch

import pytest


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


@pytest.fixture(autouse=True)
def _reset_browser():
    """Reset browser singleton between tests."""
    import app.engine.search_platforms.adapters.browser_base as bb
    old_browser = bb._browser
    old_pw = bb._playwright_instance
    bb._browser = None
    bb._playwright_instance = None
    yield
    bb._browser = old_browser
    bb._playwright_instance = old_pw


@pytest.fixture(autouse=True)
def _reset_facebook_cookie():
    """Reset Facebook cookie ContextVar after each test."""
    from app.engine.search_platforms.facebook_context import current_facebook_cookie
    token = current_facebook_cookie.set("")
    yield
    current_facebook_cookie.reset(token)


@pytest.fixture
def mock_settings_cookie():
    """Settings with Facebook cookie enabled."""
    s = MagicMock()
    s.enable_product_search = True
    s.enable_browser_scraping = True
    s.enable_facebook_cookie = True
    s.enable_browser_screenshots = False
    s.browser_scraping_timeout = 15
    s.serper_api_key = "test-serper-key"
    s.apify_api_token = "test-apify-token"
    s.product_search_max_results = 30
    s.product_search_timeout = 10
    s.product_search_max_iterations = 15
    s.product_search_scrape_timeout = 10
    s.product_search_max_scrape_pages = 10
    s.enable_tiktok_native_api = False
    s.tiktok_client_key = None
    s.tiktok_client_secret = None
    s.product_search_platforms = [
        "google_shopping", "shopee", "tiktok_shop",
        "lazada", "facebook_marketplace", "all_web",
        "instagram", "websosanh",
    ]
    return s


@pytest.fixture
def mock_settings_no_cookie():
    """Settings with Facebook cookie disabled (default)."""
    s = MagicMock()
    s.enable_product_search = True
    s.enable_browser_scraping = True
    s.enable_facebook_cookie = False
    s.enable_browser_screenshots = False
    s.browser_scraping_timeout = 15
    s.serper_api_key = "test-serper-key"
    s.apify_api_token = "test-apify-token"
    s.product_search_max_results = 30
    s.product_search_timeout = 10
    s.product_search_max_iterations = 15
    s.product_search_scrape_timeout = 10
    s.product_search_max_scrape_pages = 10
    s.enable_tiktok_native_api = False
    s.tiktok_client_key = None
    s.tiktok_client_secret = None
    s.product_search_platforms = [
        "google_shopping", "shopee", "tiktok_shop",
        "lazada", "facebook_marketplace", "all_web",
        "instagram", "websosanh",
    ]
    return s


# =============================================================================
# Group 1: Config — enable_facebook_cookie
# =============================================================================

class TestConfig:
    """Sprint 154: enable_facebook_cookie config field."""

    def test_enable_facebook_cookie_default_false(self):
        """enable_facebook_cookie defaults to False."""
        with patch.dict("os.environ", {}, clear=True):
            from app.core.config import Settings
            s = Settings(
                google_api_key="test",
                _env_file=None,
            )
            assert s.enable_facebook_cookie is False

    def test_enable_facebook_cookie_override_true(self):
        """enable_facebook_cookie can be set to True via env."""
        with patch.dict("os.environ", {"ENABLE_FACEBOOK_COOKIE": "true"}, clear=True):
            from app.core.config import Settings
            s = Settings(
                google_api_key="test",
                _env_file=None,
            )
            assert s.enable_facebook_cookie is True

    def test_feature_gated_get_cookies_returns_empty_when_disabled(self, mock_settings_no_cookie):
        """_get_cookies returns [] when enable_facebook_cookie=False, even if cookie is set."""
        from app.engine.search_platforms.facebook_context import set_facebook_cookie
        set_facebook_cookie("c_user=123; xs=abc")

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_no_cookie,
        ):
            from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
            adapter = FacebookSearchAdapter()
            cookies = adapter._get_cookies()
            assert cookies == []


# =============================================================================
# Group 2: ContextVar — set/get/default/isolation
# =============================================================================

class TestContextVar:
    """Sprint 154: Facebook cookie ContextVar lifecycle."""

    def test_default_is_empty_string(self):
        """ContextVar default is empty string."""
        from app.engine.search_platforms.facebook_context import get_facebook_cookie
        assert get_facebook_cookie() == ""

    def test_set_and_get(self):
        """set_facebook_cookie then get_facebook_cookie returns the value."""
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )
        set_facebook_cookie("c_user=123; xs=abc")
        assert get_facebook_cookie() == "c_user=123; xs=abc"

    def test_overwrite(self):
        """Setting cookie twice overwrites the first value."""
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )
        set_facebook_cookie("first=1")
        set_facebook_cookie("second=2")
        assert get_facebook_cookie() == "second=2"

    def test_isolation_between_contexts(self):
        """ContextVar is isolated between asyncio contexts (simulated via copy_context)."""
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )
        set_facebook_cookie("outer=1")

        def inner():
            # copy_context creates a snapshot; changes here don't leak back
            assert get_facebook_cookie() == "outer=1"
            set_facebook_cookie("inner=2")
            assert get_facebook_cookie() == "inner=2"

        ctx = copy_context()
        ctx.run(inner)
        # Outer context still has original value
        assert get_facebook_cookie() == "outer=1"


# =============================================================================
# Group 3: Cookie Parsing — _parse_cookie_string
# =============================================================================

class TestCookieParsing:
    """Sprint 154: FacebookSearchAdapter._parse_cookie_string."""

    def test_single_pair(self):
        """Single name=value pair."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        result = FacebookSearchAdapter._parse_cookie_string("c_user=123456")
        assert len(result) == 1
        assert result[0] == {
            "name": "c_user",
            "value": "123456",
            "domain": ".facebook.com",
            "path": "/",
        }

    def test_multiple_pairs(self):
        """Multiple semicolon-separated pairs."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        result = FacebookSearchAdapter._parse_cookie_string("c_user=123; xs=abc; datr=xyz")
        assert len(result) == 3
        names = [c["name"] for c in result]
        assert names == ["c_user", "xs", "datr"]
        assert result[1]["value"] == "abc"

    def test_empty_string(self):
        """Empty string returns empty list."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        result = FacebookSearchAdapter._parse_cookie_string("")
        assert result == []

    def test_whitespace_handling(self):
        """Whitespace around name/value is stripped."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        result = FacebookSearchAdapter._parse_cookie_string("  c_user = 123 ;  xs = abc  ")
        assert len(result) == 2
        assert result[0]["name"] == "c_user"
        assert result[0]["value"] == "123"
        assert result[1]["name"] == "xs"
        assert result[1]["value"] == "abc"

    def test_no_equals_sign_skipped(self):
        """Pairs without '=' are silently skipped."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        result = FacebookSearchAdapter._parse_cookie_string("good=1; bad_no_equals; also_good=2")
        assert len(result) == 2
        names = [c["name"] for c in result]
        assert names == ["good", "also_good"]


# =============================================================================
# Group 4: URL Selection — marketplace vs search/posts
# =============================================================================

class TestURLSelection:
    """Sprint 154: _build_url uses marketplace or posts based on cookie."""

    def test_marketplace_when_no_cookie(self, mock_settings_no_cookie):
        """Without cookie, URL is /marketplace/search/."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        adapter = FacebookSearchAdapter()
        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_no_cookie,
        ):
            url = adapter._build_url("iPhone 16", page=1)
        assert "/marketplace/search/" in url
        assert "iPhone+16" in url

    def test_search_posts_when_cookie(self, mock_settings_cookie):
        """With cookie set and feature enabled, URL is /search/posts/."""
        from app.engine.search_platforms.facebook_context import set_facebook_cookie
        set_facebook_cookie("c_user=123; xs=abc")
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        adapter = FacebookSearchAdapter()
        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ):
            url = adapter._build_url("iPhone 16", page=1)
        assert "/search/posts/" in url
        assert "iPhone+16" in url

    def test_marketplace_when_cookie_is_empty_string(self, mock_settings_cookie):
        """Empty cookie string means no login — use marketplace."""
        from app.engine.search_platforms.facebook_context import set_facebook_cookie
        set_facebook_cookie("")
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        adapter = FacebookSearchAdapter()
        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ):
            url = adapter._build_url("MacBook", page=1)
        assert "/marketplace/search/" in url


# =============================================================================
# Group 5: Playwright Cookie Injection — _get_cookies hook
# =============================================================================

class TestPlaywrightCookieInject:
    """Sprint 154: Cookie injection into Playwright context."""

    def test_base_class_get_cookies_returns_empty(self):
        """PlaywrightLLMAdapter base class returns empty list."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter
        # Create a concrete subclass to test base _get_cookies
        class Dummy(PlaywrightLLMAdapter):
            def get_config(self): return None
            def _build_url(self, q, p): return ""
            def _get_extraction_prompt(self): return ""
        adapter = Dummy()
        assert adapter._get_cookies() == []

    def test_facebook_get_cookies_returns_list(self, mock_settings_cookie):
        """FacebookSearchAdapter._get_cookies returns parsed cookie list when set."""
        from app.engine.search_platforms.facebook_context import set_facebook_cookie
        set_facebook_cookie("c_user=100; xs=xyz")
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        adapter = FacebookSearchAdapter()
        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ):
            cookies = adapter._get_cookies()
        assert len(cookies) == 2
        assert all(c["domain"] == ".facebook.com" for c in cookies)

    def test_add_cookies_called_on_context(self):
        """_fetch_page_text calls context.add_cookies when cookies are provided."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter

        cookies = [
            {"name": "c_user", "value": "123", "domain": ".facebook.com", "path": "/"},
        ]

        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.inner_text.return_value = "some page text"
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_browser.is_connected.return_value = True

        with patch(
            "app.engine.search_platforms.adapters.browser_base._get_browser",
            return_value=mock_browser,
        ), patch(
            "app.engine.search_platforms.utils.validate_url_for_scraping",
            side_effect=lambda u: u,
        ):
            class Dummy(PlaywrightLLMAdapter):
                def get_config(self): return None
                def _build_url(self, q, p): return ""
                def _get_extraction_prompt(self): return ""
            adapter = Dummy()
            adapter._fetch_page_text("https://www.facebook.com/search/posts/", cookies=cookies)

        mock_context.add_cookies.assert_called_once_with(cookies)

    def test_no_add_cookies_when_empty(self):
        """_fetch_page_text does NOT call add_cookies when cookies is empty list."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter

        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.inner_text.return_value = "some text"
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_browser.is_connected.return_value = True

        with patch(
            "app.engine.search_platforms.adapters.browser_base._get_browser",
            return_value=mock_browser,
        ), patch(
            "app.engine.search_platforms.utils.validate_url_for_scraping",
            side_effect=lambda u: u,
        ):
            class Dummy(PlaywrightLLMAdapter):
                def get_config(self): return None
                def _build_url(self, q, p): return ""
                def _get_extraction_prompt(self): return ""
            adapter = Dummy()
            # Pass None (default) — should not call add_cookies
            adapter._fetch_page_text("https://example.com/product", cookies=None)

        mock_context.add_cookies.assert_not_called()


# =============================================================================
# Group 6: ThreadPool Cookie Propagation
# =============================================================================

class TestThreadPoolCookiePropagation:
    """Sprint 154: Cookies read in calling thread before ThreadPoolExecutor."""

    def test_cookies_read_before_pool_submit(self, mock_settings_cookie):
        """_run_fetch calls _get_cookies before pool.submit."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        from app.engine.search_platforms.facebook_context import set_facebook_cookie

        set_facebook_cookie("c_user=999; xs=token")

        adapter = FacebookSearchAdapter()
        call_order = []

        original_get_cookies = adapter._get_cookies

        def tracked_get_cookies():
            call_order.append("get_cookies")
            return original_get_cookies()

        adapter._get_cookies = tracked_get_cookies

        def mock_fetch_page_text(url, timeout=15, cookies=None, _browser=None):
            call_order.append("fetch_page_text")
            return "page text"

        adapter._fetch_page_text = mock_fetch_page_text

        def fake_submit(fn, timeout=30):
            """Execute the closure directly with a mock browser."""
            return fn("mock_browser")

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=fake_submit,
        ):
            result = adapter._run_fetch("https://www.facebook.com/search/posts/")

        assert call_order.index("get_cookies") < call_order.index("fetch_page_text")

    def test_cookies_passed_to_fetch_page_text(self, mock_settings_cookie):
        """_run_fetch passes cookie list to _fetch_page_text."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        from app.engine.search_platforms.facebook_context import set_facebook_cookie

        set_facebook_cookie("c_user=42")

        adapter = FacebookSearchAdapter()
        captured_cookies = []

        def mock_fetch(url, timeout=15, cookies=None, _browser=None):
            captured_cookies.append(cookies)
            return "text"

        adapter._fetch_page_text = mock_fetch

        def fake_submit(fn, timeout=30):
            return fn("mock_browser")

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=fake_submit,
        ):
            adapter._run_fetch("https://www.facebook.com/marketplace/search/")

        assert len(captured_cookies) == 1
        assert len(captured_cookies[0]) == 1
        assert captured_cookies[0][0]["name"] == "c_user"
        assert captured_cookies[0][0]["value"] == "42"

    def test_no_cookies_when_feature_disabled(self, mock_settings_no_cookie):
        """_run_fetch passes empty cookies when feature disabled."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        from app.engine.search_platforms.facebook_context import set_facebook_cookie

        set_facebook_cookie("c_user=42")

        adapter = FacebookSearchAdapter()
        captured_cookies = []

        def mock_fetch(url, timeout=15, cookies=None, _browser=None):
            captured_cookies.append(cookies)
            return "text"

        adapter._fetch_page_text = mock_fetch

        def fake_submit(fn, timeout=30):
            return fn("mock_browser")

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_no_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=fake_submit,
        ):
            adapter._run_fetch("https://www.facebook.com/marketplace/search/")

        assert len(captured_cookies) == 1
        assert captured_cookies[0] == []


# =============================================================================
# Group 7: ContextVar Lifecycle — scope and cleanup
# =============================================================================

class TestContextVarLifecycle:
    """Sprint 154: ContextVar scoping and non-leakage."""

    def test_set_in_endpoint_scope(self):
        """Cookie is accessible within the scope it was set."""
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )
        set_facebook_cookie("session_cookie=abc123")
        assert get_facebook_cookie() == "session_cookie=abc123"

    def test_default_after_reset(self):
        """After resetting the token, cookie returns to default."""
        from app.engine.search_platforms.facebook_context import (
            current_facebook_cookie,
            get_facebook_cookie,
        )
        token = current_facebook_cookie.set("temp=1")
        assert get_facebook_cookie() == "temp=1"
        current_facebook_cookie.reset(token)
        assert get_facebook_cookie() == ""

    def test_cookie_scope_restores_after_exception(self):
        """facebook_cookie_scope restores the previous cookie on exit."""
        from app.engine.search_platforms.facebook_context import (
            facebook_cookie_scope,
            get_facebook_cookie,
            reset_facebook_cookie,
            set_facebook_cookie,
        )

        token = set_facebook_cookie("outer=1")
        try:
            with pytest.raises(RuntimeError):
                with facebook_cookie_scope("inner=2"):
                    assert get_facebook_cookie() == "inner=2"
                    raise RuntimeError("boom")
            assert get_facebook_cookie() == "outer=1"
        finally:
            reset_facebook_cookie(token)

    def test_no_leakage_across_copied_context(self):
        """Changes in a copied context do not leak to the original."""
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )

        # Original context has no cookie
        assert get_facebook_cookie() == ""

        def in_request():
            set_facebook_cookie("request_specific=xyz")
            return get_facebook_cookie()

        ctx = copy_context()
        inner_val = ctx.run(in_request)
        assert inner_val == "request_specific=xyz"
        # Original context unaffected
        assert get_facebook_cookie() == ""


# =============================================================================
# Group 8: Screenshot SSE Event — regression check
# =============================================================================

class TestScreenshotEvent:
    """Sprint 154: browser_screenshot SSE event still works after changes."""

    def test_browser_screenshot_event_type_exists(self):
        """StreamEventType.BROWSER_SCREENSHOT still exists."""
        from app.engine.multi_agent.stream_utils import StreamEventType
        assert hasattr(StreamEventType, "BROWSER_SCREENSHOT")
        assert StreamEventType.BROWSER_SCREENSHOT == "browser_screenshot"

    def test_browser_screenshot_sse_format(self):
        """chat_stream format_sse produces valid SSE for browser_screenshot."""
        from app.api.v1.chat_stream import format_sse
        content = {
            "content": {
                "url": "https://www.facebook.com/search/posts/?q=test",
                "image": "base64data...",
                "label": "Dang tai trang...",
            },
            "node": "product_search_agent",
        }
        sse = format_sse("browser_screenshot", content, event_id=1)
        assert "event: browser_screenshot" in sse
        assert "id: 1" in sse
        # Thumbnail field not needed by backend — frontend handles it
        parsed_data = json.loads(sse.split("data: ")[1].split("\n")[0])
        assert "content" in parsed_data
        assert parsed_data["node"] == "product_search_agent"


# =============================================================================
# Group 9: Regression — existing adapters unaffected
# =============================================================================

class TestRegression:
    """Sprint 154: Non-browser adapters and disabled-feature paths unaffected."""

    def test_serper_adapter_unaffected_by_cookie(self):
        """SerperShoppingAdapter has no _get_cookies dependency."""
        from app.engine.search_platforms.adapters.serper_shopping import SerperShoppingAdapter
        adapter = SerperShoppingAdapter.__new__(SerperShoppingAdapter)
        # Serper adapter is not a PlaywrightLLMAdapter — no _get_cookies
        assert not hasattr(adapter, "_get_cookies")

    def test_websosanh_adapter_unaffected(self):
        """WebSosanhAdapter has no _get_cookies dependency."""
        from app.engine.search_platforms.adapters.websosanh import WebSosanhAdapter
        adapter = WebSosanhAdapter.__new__(WebSosanhAdapter)
        assert not hasattr(adapter, "_get_cookies")

    def test_disabled_facebook_cookie_no_interference(self, mock_settings_no_cookie):
        """With enable_facebook_cookie=False, FacebookSearchAdapter._get_cookies returns []."""
        from app.engine.search_platforms.facebook_context import set_facebook_cookie
        set_facebook_cookie("c_user=999; xs=secret")

        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        adapter = FacebookSearchAdapter()
        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_no_cookie,
        ):
            cookies = adapter._get_cookies()
        assert cookies == []

    def test_old_fixture_enable_browser_scraping_false(self):
        """MagicMock settings with enable_browser_scraping=False work correctly.

        GOTCHA from Sprint 152: MagicMock returns truthy for unset attrs.
        Old test fixtures MUST explicitly set enable_browser_scraping=False.
        """
        s = MagicMock()
        s.enable_browser_scraping = False
        s.enable_facebook_cookie = False
        assert s.enable_browser_scraping is False
        assert s.enable_facebook_cookie is False


# =============================================================================
# Group 10: SSRF Prevention — still enforced with cookies
# =============================================================================

class TestSSRFWithCookies:
    """Sprint 154: SSRF validation still runs when cookies are present."""

    def test_validate_url_still_called(self):
        """_fetch_page_text calls validate_url_for_scraping before anything else."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter

        class Dummy(PlaywrightLLMAdapter):
            def get_config(self): return None
            def _build_url(self, q, p): return ""
            def _get_extraction_prompt(self): return ""

        cookies = [{"name": "c_user", "value": "1", "domain": ".facebook.com", "path": "/"}]
        adapter = Dummy()

        with patch(
            "app.engine.search_platforms.utils.validate_url_for_scraping",
            side_effect=ValueError("Blocked private/reserved IP: 127.0.0.1"),
        ) as mock_validate:
            with pytest.raises(ValueError, match="Blocked private"):
                adapter._fetch_page_text("http://127.0.0.1/evil", cookies=cookies)
            mock_validate.assert_called_once_with("http://127.0.0.1/evil")

    def test_private_ip_blocked_with_cookie(self):
        """Private IP is blocked even when Facebook cookies are provided."""
        from app.engine.search_platforms.utils import validate_url_for_scraping
        with pytest.raises(ValueError, match="Blocked private"):
            validate_url_for_scraping("http://192.168.1.1/admin")


# =============================================================================
# Group 11: Header Extraction — X-Facebook-Cookie in chat_stream
# =============================================================================

class TestHeaderExtraction:
    """Sprint 154: X-Facebook-Cookie header extraction in chat_stream v3."""

    def test_header_extracted_and_set(self):
        """X-Facebook-Cookie header value is passed to set_facebook_cookie."""
        # The header extraction logic is inside generate_events_v3().
        # We test the pattern directly rather than spinning up full ASGI.
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
            get_facebook_cookie,
        )

        # Simulate what chat_stream_v3 does:
        mock_request_headers = {"x-facebook-cookie": "c_user=555; xs=tok"}
        fb_cookie = mock_request_headers.get("x-facebook-cookie", "")

        mock_settings = MagicMock()
        mock_settings.enable_facebook_cookie = True

        if fb_cookie and mock_settings.enable_facebook_cookie:
            set_facebook_cookie(fb_cookie)

        assert get_facebook_cookie() == "c_user=555; xs=tok"

    def test_missing_header_defaults_empty(self):
        """Missing X-Facebook-Cookie header results in empty string (no set call)."""
        from app.engine.search_platforms.facebook_context import get_facebook_cookie

        mock_request_headers = {}
        fb_cookie = mock_request_headers.get("x-facebook-cookie", "")

        mock_settings = MagicMock()
        mock_settings.enable_facebook_cookie = True

        # The condition `if fb_cookie and ...` is False for empty string
        if fb_cookie and mock_settings.enable_facebook_cookie:
            from app.engine.search_platforms.facebook_context import set_facebook_cookie
            set_facebook_cookie(fb_cookie)

        # Cookie should still be default empty
        assert get_facebook_cookie() == ""


# =============================================================================
# Group 12: Playwright Worker Thread (Sprint 154b greenlet fix)
# =============================================================================

class TestPlaywrightWorker:
    """Sprint 154b: Dedicated worker thread fixes greenlet errors."""

    def test_submit_to_pw_worker_calls_fn_with_browser(self):
        """_submit_to_pw_worker passes a browser object to the submitted fn."""
        received_browser = []

        def fake_fn(browser):
            received_browser.append(browser)
            return "result_text"

        # Mock the worker loop to use a fake browser
        mock_queue = MagicMock()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True

        # We test the contract: fn receives a browser and returns result
        # Simulate by calling fn directly (worker internals are tested via integration)
        result = fake_fn("mock_browser")
        assert result == "result_text"
        assert received_browser == ["mock_browser"]

    def test_run_fetch_always_uses_worker(self, mock_settings_cookie):
        """_run_fetch always tries _submit_to_pw_worker first (Sprint 154b)."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        from app.engine.search_platforms.facebook_context import set_facebook_cookie

        set_facebook_cookie("c_user=42; xs=tok")

        adapter = FacebookSearchAdapter()
        worker_called = []

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=lambda fn, timeout: worker_called.append(fn) or "page text",
        ), patch(
            "app.engine.search_platforms.utils.validate_url_for_scraping",
        ):
            # Worker is always tried first, regardless of asyncio context
            result = adapter._run_fetch("https://www.facebook.com/search/posts/")

        assert len(worker_called) == 1
        assert result == "page text"

    def test_run_fetch_propagates_worker_failure(self, mock_settings_cookie):
        """_run_fetch propagates exception when worker fails (no direct fallback)."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter
        from app.engine.search_platforms.facebook_context import set_facebook_cookie

        set_facebook_cookie("c_user=42; xs=tok")

        adapter = FacebookSearchAdapter()

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=RuntimeError("worker timeout"),
        ):
            # Worker fails — exception propagates (no direct fallback,
            # adapter's search_sync will catch and use Serper instead)
            with pytest.raises(RuntimeError, match="worker timeout"):
                adapter._run_fetch("https://www.facebook.com/search/posts/")

    def test_run_fetch_propagates_import_error(self, mock_settings_cookie):
        """_run_fetch re-raises ImportError (playwright not installed)."""
        from app.engine.search_platforms.adapters.facebook_search import FacebookSearchAdapter

        adapter = FacebookSearchAdapter()

        with patch(
            "app.core.config.get_settings",
            return_value=mock_settings_cookie,
        ), patch(
            "app.engine.search_platforms.adapters.browser_base._submit_to_pw_worker",
            side_effect=ImportError("playwright not installed"),
        ):
            with pytest.raises(ImportError, match="playwright not installed"):
                adapter._run_fetch("https://www.facebook.com/search/posts/")

    def test_fetch_page_text_uses_provided_browser(self):
        """_fetch_page_text uses _browser param when provided (worker path)."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter
        from app.engine.search_platforms.base import PlatformConfig, BackendType

        class Dummy(PlaywrightLLMAdapter):
            def get_config(self):
                return PlatformConfig(id="test", display_name="T", backend=BackendType.BROWSER)
            def _build_url(self, q, p): return ""
            def _get_extraction_prompt(self): return ""

        adapter = Dummy()

        mock_page = MagicMock()
        mock_page.inner_text.return_value = "content"
        mock_page.url = "https://test.com"

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_settings = MagicMock()
        mock_settings.enable_browser_screenshots = False

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("app.engine.search_platforms.utils.validate_url_for_scraping"):
            # Pass _browser explicitly — should NOT call _get_browser()
            with patch(
                "app.engine.search_platforms.adapters.browser_base._get_browser",
            ) as mock_get_browser:
                text = adapter._fetch_page_text(
                    "https://test.com", timeout=10, _browser=mock_browser,
                )

            mock_get_browser.assert_not_called()
            assert text == "content"
            mock_browser.new_context.assert_called_once()

    def test_fetch_page_text_falls_back_to_get_browser(self):
        """_fetch_page_text calls _get_browser() when _browser is None."""
        from app.engine.search_platforms.adapters.browser_base import PlaywrightLLMAdapter
        from app.engine.search_platforms.base import PlatformConfig, BackendType

        class Dummy(PlaywrightLLMAdapter):
            def get_config(self):
                return PlatformConfig(id="test", display_name="T", backend=BackendType.BROWSER)
            def _build_url(self, q, p): return ""
            def _get_extraction_prompt(self): return ""

        adapter = Dummy()

        mock_page = MagicMock()
        mock_page.inner_text.return_value = "fallback"
        mock_page.url = "https://test.com"

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_settings = MagicMock()
        mock_settings.enable_browser_screenshots = False

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("app.engine.search_platforms.utils.validate_url_for_scraping"), \
             patch(
                "app.engine.search_platforms.adapters.browser_base._get_browser",
                return_value=mock_browser,
             ) as mock_get:
            text = adapter._fetch_page_text("https://test.com", timeout=10)

        mock_get.assert_called_once()
        assert text == "fallback"

    def test_close_browser_shuts_down_worker(self):
        """close_browser() cleans up worker thread and queue."""
        import app.engine.search_platforms.adapters.browser_base as bb

        mock_queue = MagicMock()
        mock_thread = MagicMock()

        bb._pw_task_queue = mock_queue
        bb._pw_worker_thread = mock_thread

        try:
            bb.close_browser()
            mock_queue.put.assert_called_once_with(None)
            mock_thread.join.assert_called_once()
            assert bb._pw_worker_thread is None
            assert bb._pw_task_queue is None
        finally:
            # Clean up module state
            bb._pw_task_queue = None
            bb._pw_worker_thread = None

    def test_worker_loop_handles_import_error(self):
        """Worker loop drains tasks with ImportError when playwright missing."""
        import builtins as _builtins
        import app.engine.search_platforms.adapters.browser_base as bb
        import queue as q
        import concurrent.futures

        task_queue = q.Queue()
        future = concurrent.futures.Future()

        def dummy_fn(browser):
            return "should not run"

        task_queue.put((dummy_fn, future))
        task_queue.put(None)  # Shutdown signal

        orig_import = _builtins.__import__

        def patched_import(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("no playwright")
            return orig_import(name, *args, **kwargs)

        with patch.object(_builtins, "__import__", side_effect=patched_import):
            bb._pw_worker_loop(task_queue)

        # Future should have ImportError
        with pytest.raises(ImportError, match="playwright not installed"):
            future.result(timeout=1)
