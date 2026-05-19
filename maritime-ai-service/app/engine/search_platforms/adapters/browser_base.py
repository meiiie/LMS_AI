"""
Playwright + LLM Extraction - Base Class for Browser-Based Adapters

Sprint 152: "Trinh Duyet Thong Minh"
Sprint 154b: Dedicated worker thread (fixes greenlet "Cannot switch" errors)

Uses Playwright headless Chromium to fetch pages (bypasses anti-bot),
then Gemini Flash LLM to extract structured product data from visible text.

Advantages over CSS selectors:
- Self-healing: LLM reads semantics, not brittle class names
- Works on any website without per-site selector maintenance
- Facebook/Instagram change CSS frequently - LLM adapts automatically

Subclasses implement:
- get_config() -> PlatformConfig
- _build_url(query, page) -> str
- _get_extraction_prompt() -> str
- _post_navigate(page) -> None (optional: dismiss modals, scroll)
"""

import concurrent.futures
import json
import logging
import queue as _queue_mod
import threading
from abc import abstractmethod
from typing import List, Optional

from app.engine.search_platforms.adapters.browser_product_mapping import (
    _GROUP_POST_INDICATOR_FIELDS,
    _MIN_GROUP_POST_MATCH,
    _MIN_INDICATOR_MATCH,
    _PRODUCT_INDICATOR_FIELDS,
    dig_image_uri as _dig_image_uri,
    extract_group_post_product as _extract_group_post_product_impl,
    extract_image_from_attachments as _extract_image_from_attachments,
    extract_json_array as _extract_json_array,
    extract_marketplace_product as _extract_marketplace_product_impl,
    extract_price_from_text as _extract_price_from_text,
    extract_product_from_node as _extract_product_from_node_impl,
    map_intercepted_to_result as _map_intercepted_to_result_impl,
    map_llm_item_to_result as _map_to_result_impl,
    parse_vnd_price as _parse_vnd_price,
    scan_for_products as _scan_for_products_impl,
)
from app.engine.search_platforms.adapters.browser_fetch_runtime import (
    fetch_page_text_impl,
    fetch_page_text_with_scroll_impl,
    fetch_page_with_interception_impl,
    llm_extract_impl,
    run_fetch_impl,
    run_fetch_with_interception_impl,
    run_fetch_with_scroll_impl,
)
from app.engine.search_platforms.base import (
    ProductSearchResult,
    SearchPlatformAdapter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy browser singleton - used in non-asyncio path (tests, CLI).
# Production asyncio path uses the dedicated worker thread instead.
# ---------------------------------------------------------------------------
_browser = None
_playwright_instance = None
_browser_lock = threading.Lock()

# Max page text sent to LLM (chars)
_MAX_PAGE_TEXT = 50000
# Max text in LLM prompt (chars) - leave room for prompt template
_MAX_PROMPT_TEXT = 30000
# Sprint 153: Max screenshots per search
_MAX_SCREENSHOTS = 5

# ---------------------------------------------------------------------------
# Sprint 156: Network Interception - GraphQL structured data capture
# ---------------------------------------------------------------------------
_FOR_LOOP_PREFIX = "for (;;);"
_GRAPHQL_ENDPOINT = "/api/graphql/"
_INTERCEPTION_FALLBACK_THRESHOLD = 3

# Sprint 157b: Group post indicator fields - distinct from marketplace

# Sprint 157b: Enhanced scroll JS - extracts post links (pfbid + /posts/ + /permalink/)
# and first product image from each article element.
_SCROLL_EXTRACT_JS = """() => {
    const els = document.querySelectorAll('div[role="article"]');
    if (els.length === 0) return [];
    const STATIC_PREFIXES = [
        'https://static.xx.fbcdn.net/rsrc.php/',
        'data:image/',
        'https://scontent',
    ];
    return Array.from(els).map(a => {
        // Extract post links: /posts/, /permalink/, pfbid, /marketplace/item/
        const links = Array.from(a.querySelectorAll('a[href]'))
            .map(l => l.href)
            .filter(h => h && (
                (h.includes('/groups/') && (
                    h.includes('/posts/') || h.includes('/permalink/') || h.includes('pfbid')
                ))
                || h.includes('/marketplace/item/')
            ));
        const uniqueLink = links.length > 0 ? links[0] : '';

        // Extract first meaningful image (skip emoji/static)
        let postImage = '';
        const imgs = a.querySelectorAll('img[src]');
        for (const img of imgs) {
            const src = img.src || '';
            if (!src) continue;
            const w = img.naturalWidth || img.width || 0;
            if (w > 0 && w < 33) continue;  // Skip tiny emoji images
            const isStatic = STATIC_PREFIXES.some(p => src.startsWith(p));
            if (isStatic) continue;
            postImage = src;
            break;
        }

        return {text: a.innerText, link: uniqueLink, image: postImage};
    });
}"""

# ---------------------------------------------------------------------------
# Dedicated Playwright worker thread (Sprint 154b)
# ---------------------------------------------------------------------------
# Playwright sync API uses greenlets internally. The browser singleton is
# bound to the greenlet of the thread that created it. ThreadPoolExecutor's
# submit() runs each task in a potentially different greenlet context, causing
# "Cannot switch to a different thread" on subsequent calls. This dedicated
# worker keeps the browser + greenlet alive across all calls.
_pw_task_queue: Optional[_queue_mod.Queue] = None
_pw_worker_thread: Optional[threading.Thread] = None
_pw_worker_lock = threading.Lock()


def _pw_worker_loop(task_queue: _queue_mod.Queue) -> None:
    """Dedicated thread: creates Playwright browser once, processes tasks.

    All Playwright operations run in THIS thread's main greenlet, ensuring
    the browser singleton can be reused across multiple calls without
    "Cannot switch to a different thread" errors.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # Playwright not installed - drain tasks with ImportError
        while True:
            item = task_queue.get()
            if item is None:
                break
            _, result_future = item
            if not result_future.cancelled():
                result_future.set_exception(
                    ImportError("playwright not installed")
                )
        return

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    logger.info("[BROWSER] Playwright worker started, browser launched")

    try:
        while True:
            item = task_queue.get()
            if item is None:  # Shutdown signal
                break
            fn, result_future = item
            try:
                # Auto-reconnect if browser died
                if not browser.is_connected():
                    logger.info("[BROWSER] Reconnecting browser...")
                    browser = pw.chromium.launch(
                        headless=True,
                        args=[
                            "--no-sandbox",
                            "--disable-blink-features=AutomationControlled",
                        ],
                    )
                result = fn(browser)
                if not result_future.cancelled():
                    result_future.set_result(result)
            except Exception as e:
                if not result_future.cancelled():
                    result_future.set_exception(e)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        logger.info("[BROWSER] Playwright worker stopped")


def _ensure_pw_worker() -> _queue_mod.Queue:
    """Start the Playwright worker thread if not running. Returns task queue."""
    global _pw_task_queue, _pw_worker_thread
    with _pw_worker_lock:
        if _pw_worker_thread is None or not _pw_worker_thread.is_alive():
            _pw_task_queue = _queue_mod.Queue()
            _pw_worker_thread = threading.Thread(
                target=_pw_worker_loop,
                args=(_pw_task_queue,),
                daemon=True,
                name="playwright-worker",
            )
            _pw_worker_thread.start()
    return _pw_task_queue


def _submit_to_pw_worker(fn, timeout: float = 30):
    """Submit fn(browser) to Playwright worker. Blocks until result ready."""
    q = _ensure_pw_worker()
    future = concurrent.futures.Future()
    q.put((fn, future))
    return future.result(timeout=timeout)


def _get_browser():
    """Get or create shared headless Chromium browser (thread-safe singleton).

    Used in non-asyncio path (tests, CLI). Production asyncio path uses
    the dedicated worker thread instead - see _submit_to_pw_worker().
    """
    global _browser, _playwright_instance
    with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        from playwright.sync_api import sync_playwright
        _playwright_instance = sync_playwright().start()
        _browser = _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        return _browser


def close_browser():
    """Cleanup browser and worker thread - call at app shutdown."""
    global _browser, _playwright_instance, _pw_worker_thread, _pw_task_queue
    # Legacy singleton cleanup (tests, non-asyncio path)
    with _browser_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright_instance is not None:
            try:
                _playwright_instance.stop()
            except Exception:
                pass
            _playwright_instance = None
    # Worker thread shutdown (production asyncio path)
    with _pw_worker_lock:
        if _pw_task_queue is not None:
            _pw_task_queue.put(None)  # Shutdown signal
        if _pw_worker_thread is not None:
            _pw_worker_thread.join(timeout=5)
            _pw_worker_thread = None
        _pw_task_queue = None


class PlaywrightLLMAdapter(SearchPlatformAdapter):
    """
    Base class for Playwright + LLM extraction adapters.

    Subclasses must implement:
    - get_config() -> PlatformConfig
    - _build_url(query, page) -> str
    - _get_extraction_prompt() -> str

    Optional override:
    - _post_navigate(page) -> None (dismiss modals, scroll, etc.)
    """

    def __init__(self):
        self._last_screenshots: list = []

    def _get_cookies(self) -> list:
        """Override in subclass to provide cookies for Playwright context.

        Returns list of Playwright cookie dicts: [{name, value, domain, path}]
        Called in the calling thread (asyncio) before worker thread submission.
        """
        return []

    def _capture_screenshot(self, page, label: str) -> None:
        """Sprint 153: Capture JPEG screenshot if browser_screenshots enabled."""
        try:
            from app.core.config import get_settings
            settings = get_settings()
            if not settings.enable_browser_screenshots:
                return
            if len(self._last_screenshots) >= _MAX_SCREENSHOTS:
                return

            import base64
            import time
            quality = settings.browser_screenshot_quality

            raw = page.screenshot(type="jpeg", quality=quality)
            b64 = base64.b64encode(raw).decode("ascii")

            self._last_screenshots.append({
                "label": label,
                "image": b64,
                "url": page.url,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.debug("[BROWSER] Screenshot failed: %s", e)

    def get_last_screenshots(self) -> list:
        """Sprint 153: Return and clear accumulated screenshots."""
        shots = self._last_screenshots[:]
        self._last_screenshots = []
        return shots

    def _fetch_page_text(self, url: str, timeout: int = 15,
                         cookies: list | None = None,
                         _browser=None) -> str:
        """Navigate to URL via headless Chromium, return visible page text.

        Args:
            url: Target URL (validated for SSRF).
            timeout: Page load timeout in seconds.
            cookies: Sprint 154 - Playwright cookie dicts to inject.
            _browser: Sprint 154b - Browser from worker thread. When None,
                      uses legacy _get_browser() singleton (tests/CLI).
        """
        return fetch_page_text_impl(
            self,
            url,
            timeout=timeout,
            cookies=cookies,
            _browser=_browser,
            get_browser=_get_browser,
            max_page_text=_MAX_PAGE_TEXT,
        )

    def _post_navigate(self, page) -> None:
        """Override in subclass for platform-specific actions."""
        pass

    # ------------------------------------------------------------------
    # Sprint 155: Scroll-and-extract for virtual-scrolling pages
    # ------------------------------------------------------------------

    def _fetch_page_text_with_scroll(
        self,
        url: str,
        timeout: int = 15,
        cookies: list | None = None,
        _browser=None,
        max_scrolls: int = 8,
        scroll_delay: float = 2.5,
        scroll_distance: int = 800,
    ) -> str:
        """Navigate + scroll-and-extract for virtual scrolling pages."""
        return fetch_page_text_with_scroll_impl(
            self,
            url,
            timeout=timeout,
            cookies=cookies,
            _browser=_browser,
            max_scrolls=max_scrolls,
            scroll_delay=scroll_delay,
            scroll_distance=scroll_distance,
            get_browser=_get_browser,
            max_page_text=_MAX_PAGE_TEXT,
            scroll_extract_js=_SCROLL_EXTRACT_JS,
        )

    def _run_fetch_with_scroll(
        self,
        url: str,
        max_scrolls: int = 8,
        scroll_delay: float = 2.5,
        scroll_distance: int = 800,
    ) -> str:
        """Submit scroll-and-extract to Playwright worker thread.

        Like _run_fetch() but uses _fetch_page_text_with_scroll() instead
        of _fetch_page_text(). Extended timeout to account for scrolling.
        """
        return run_fetch_with_scroll_impl(
            self,
            url,
            max_scrolls=max_scrolls,
            scroll_delay=scroll_delay,
            scroll_distance=scroll_distance,
            submit_to_pw_worker=_submit_to_pw_worker,
        )

    # ------------------------------------------------------------------
    # Sprint 156: Network Interception - GraphQL structured data
    # ------------------------------------------------------------------

    _scan_for_products = staticmethod(_scan_for_products_impl)
    _extract_product_from_node = staticmethod(_extract_product_from_node_impl)
    _extract_marketplace_product = staticmethod(_extract_marketplace_product_impl)
    _extract_group_post_product = staticmethod(_extract_group_post_product_impl)

    def _fetch_page_with_interception(
        self,
        url: str,
        timeout: int = 15,
        cookies: list | None = None,
        _browser=None,
        max_scrolls: int = 8,
        scroll_delay: float = 2.5,
        scroll_distance: int = 800,
        max_response_size: int = 5_000_000,
    ) -> tuple:
        """Navigate + scroll with GraphQL response interception.

        Like _fetch_page_text_with_scroll but also captures structured
        product data from Facebook's GraphQL API responses.

        Returns (dom_text: str, intercepted_products: list[dict])
        """
        return fetch_page_with_interception_impl(
            self,
            url,
            timeout=timeout,
            cookies=cookies,
            _browser=_browser,
            max_scrolls=max_scrolls,
            scroll_delay=scroll_delay,
            scroll_distance=scroll_distance,
            max_response_size=max_response_size,
            get_browser=_get_browser,
            max_page_text=_MAX_PAGE_TEXT,
            scroll_extract_js=_SCROLL_EXTRACT_JS,
            graphql_endpoint=_GRAPHQL_ENDPOINT,
            for_loop_prefix=_FOR_LOOP_PREFIX,
            scan_for_products=PlaywrightLLMAdapter._scan_for_products,
            extract_product_from_node=PlaywrightLLMAdapter._extract_product_from_node,
            logger=logger,
        )

    def _run_fetch_with_interception(
        self,
        url: str,
        max_scrolls: int = 8,
        scroll_delay: float = 2.5,
        scroll_distance: int = 800,
        max_response_size: int = 5_000_000,
    ) -> tuple:
        """Submit scroll-with-interception to Playwright worker thread.

        Returns (dom_text, intercepted_products).
        """
        return run_fetch_with_interception_impl(
            self,
            url,
            max_scrolls=max_scrolls,
            scroll_delay=scroll_delay,
            scroll_distance=scroll_distance,
            max_response_size=max_response_size,
            submit_to_pw_worker=_submit_to_pw_worker,
        )

    def _map_intercepted_to_result(self, item: dict) -> ProductSearchResult:
        """Map intercepted GraphQL product dict to ProductSearchResult."""
        return _map_intercepted_to_result_impl(
            self.get_config().display_name,
            item,
        )

    def _llm_extract(self, page_text: str, max_results: int) -> List[ProductSearchResult]:
        """Use Gemini Flash to extract structured product data from page text."""
        return llm_extract_impl(
            self,
            page_text,
            max_results,
            max_prompt_text=_MAX_PROMPT_TEXT,
            extract_json_array=_extract_json_array,
        )

    def _map_to_result(self, item: dict) -> ProductSearchResult:
        """Map LLM-extracted dict to ProductSearchResult."""
        return _map_to_result_impl(
            self.get_config().display_name,
            item,
        )

    @abstractmethod
    def _build_url(self, query: str, page: int) -> str:
        """Build search URL for the platform."""
        ...

    @abstractmethod
    def _get_extraction_prompt(self) -> str:
        """Return LLM prompt template with {text} and {max_results} placeholders."""
        ...

    def search_sync(self, query: str, max_results: int = 20, page: int = 1) -> List[ProductSearchResult]:
        """Fetch page via Playwright, extract products via LLM.

        Playwright sync API cannot run inside an asyncio event loop, so we
        offload to a dedicated worker thread when called from async context.
        """
        if not query or not query.strip():
            return []

        url = self._build_url(query.strip(), page)
        try:
            text = self._run_fetch(url)
            if not text or len(text) < 100:
                return []
            return self._llm_extract(text, max_results)
        except ImportError:
            logger.warning("[BROWSER] playwright not installed - cannot scrape")
            return []
        except Exception as e:
            logger.warning("[BROWSER] Error scraping %s: %s", url, e)
            return []

    def _run_fetch(self, url: str) -> str:
        """Fetch page text via dedicated Playwright worker thread.

        Sprint 154: Read cookies via _get_cookies() BEFORE thread submission.
        ContextVar does NOT propagate to other threads.

        Sprint 154b: ALWAYS uses dedicated worker thread with persistent queue.
        The worker creates Playwright + browser in its own greenlet and reuses
        them across all tasks - no "Cannot switch to a different thread" errors.

        Note: LangChain tools run on sync thread pool threads (not the asyncio
        event loop thread), so checking asyncio.get_running_loop() is wrong -
        it would always fall through to the direct path in production.
        """
        return run_fetch_impl(
            self,
            url,
            submit_to_pw_worker=_submit_to_pw_worker,
        )

    def _get_timeout(self) -> int:
        """Get browser timeout from config."""
        try:
            from app.core.config import get_settings
            return get_settings().browser_scraping_timeout
        except Exception:
            return 15
