"""Web fetch tool — pull full URL content as clean markdown.

Pattern: Anthropic Claude `web_fetch` (Sonnet 4.5+) — separate from `web_search`.
LLM tự quyết định khi snippet từ search không đủ → escalate sang fetch.

3-tier scrape chain (SOTA layered, ref Perplexity / Tavily 2026):
1. **Crawl4AI** (local, Playwright-backed) — primary, free, full anti-bot
2. **Jina Reader r.jina.ai** (cloud, free reader) — fallback when local blocked
3. **httpx + plaintext** — last resort if both above fail

Why two layers (not one):
- Crawl4AI bị Cloudflare một số trang → Jina vượt qua (fingerprint khác)
- Jina free quota throttle ở heavy use → Crawl4AI không giới hạn
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import Optional

from app.engine.tools.native_tool import tool

logger = logging.getLogger(__name__)

# Cap output for LLM context — 3500 chars ≈ 900 tokens
_MAX_CONTENT_CHARS = 3500
_CRAWL4AI_TIMEOUT_S = 25.0
_JINA_TIMEOUT_S = 15.0
_HTTPX_TIMEOUT_S = 8.0


def _truncate(text: str, source_label: str, url: str) -> str:
    text = text.strip()
    if len(text) > _MAX_CONTENT_CHARS:
        text = text[:_MAX_CONTENT_CHARS] + "\n\n[…truncated]"
    return f"# {url}\n_(via {source_label})_\n\n{text}"


def _run_async_in_thread(coro, timeout: float):
    """Run an async coroutine in a dedicated thread with its own event loop.

    Same pattern as crawl4ai_adapter._run_async_in_thread — avoids greenlet
    'Cannot switch to a different task' errors when called from FastAPI's loop.
    """
    result_future: Future = Future()

    def _target():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_future.set_result(loop.run_until_complete(coro))
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            result_future.set_exception(exc)

    thread = threading.Thread(target=_target, daemon=True, name="web-fetch")
    thread.start()
    thread.join(timeout=timeout + 2.0)

    if not result_future.done():
        raise TimeoutError(f"web_fetch timed out after {timeout}s")
    return result_future.result()


async def _crawl4ai_async(url: str) -> Optional[str]:
    try:
        from crawl4ai import AsyncWebCrawler
    except ImportError:
        return None

    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url)
            if result.success and result.markdown:
                return str(result.markdown)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[FETCH_URL] crawl4ai exc url=%s err=%s", url, exc)
    return None


def _try_crawl4ai(url: str) -> Optional[str]:
    try:
        return _run_async_in_thread(_crawl4ai_async(url), _CRAWL4AI_TIMEOUT_S)
    except TimeoutError:
        logger.warning("[FETCH_URL] crawl4ai timeout (%ss): %s", _CRAWL4AI_TIMEOUT_S, url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FETCH_URL] crawl4ai failed: %s", exc)
    return None


def _try_jina(url: str) -> Optional[str]:
    try:
        import httpx

        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            timeout=_JINA_TIMEOUT_S,
            follow_redirects=True,
        )
        if resp.status_code == 200 and resp.text:
            return resp.text
        logger.debug("[FETCH_URL] jina status=%d url=%s", resp.status_code, url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FETCH_URL] jina failed: %s", exc)
    return None


def _try_scrapling(url: str) -> Optional[str]:
    """Adaptive scraper with Cloudflare/anti-bot bypass (BSD-3, 43.8k★).

    Used as fallback when Crawl4AI hits anti-bot wall. Scrapling has stealth
    fetcher that bypasses Cloudflare Turnstile/Interstitial. Slow init (~2s)
    so only invoked after Crawl4AI fails.

    No-op if scrapling not installed.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    try:
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=20_000,  # ms
        )
        if page and page.status == 200 and page.body:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(page.body, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            if text and len(text) > 200:
                return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("[FETCH_URL] scrapling failed: %s", exc)
    return None


def _try_httpx(url: str) -> Optional[str]:
    try:
        import httpx

        resp = httpx.get(url, timeout=_HTTPX_TIMEOUT_S, follow_redirects=True)
        if resp.status_code == 200 and resp.text:
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                return soup.get_text(separator="\n", strip=True)
            except ImportError:
                return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FETCH_URL] httpx failed: %s", exc)
    return None


@tool(
    description=(
        "Lấy nội dung đầy đủ của một URL dưới dạng markdown sạch. "
        "Dùng khi snippet từ tool_web_search KHÔNG đủ thông tin "
        "(ví dụ: bảng giá chi tiết, bài phân tích dài, bài viết kỹ thuật). "
        "Input là URL hoàn chỉnh (http:// hoặc https://). "
        "Trả về tối đa ~3500 ký tự markdown, bị cắt nếu dài hơn."
    )
)
def tool_fetch_url(url: str) -> str:
    """Fetch a single URL → clean markdown via 3-tier chain (cached)."""
    if not url or not isinstance(url, str):
        return "Lỗi: URL trống hoặc không phải chuỗi."

    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return f"Lỗi: URL không hợp lệ ({url}). Cần bắt đầu bằng http:// hoặc https://"

    # Tier 0: Valkey cache hit (Cursor / Windsurf pattern — 1h TTL).
    try:
        from app.engine.tools.web_fetch_cache import get_cached, set_cached
        cached = get_cached(url)
        if cached:
            logger.info("[FETCH_URL] cache HIT url=%s len=%d", url, len(cached))
            return _truncate(cached, "Cache", url)
    except ImportError:
        get_cached = None
        set_cached = None

    # Tier 1: Crawl4AI (local, Playwright, fast for non-protected pages)
    content = _try_crawl4ai(url)
    if content:
        logger.info("[FETCH_URL] crawl4ai OK url=%s len=%d", url, len(content))
        if set_cached is not None:
            set_cached(url, content)
        return _truncate(content, "Crawl4AI", url)

    # Tier 2: Scrapling stealth (local, bypasses Cloudflare/Turnstile)
    content = _try_scrapling(url)
    if content:
        logger.info("[FETCH_URL] scrapling OK url=%s len=%d", url, len(content))
        if set_cached is not None:
            set_cached(url, content)
        return _truncate(content, "Scrapling", url)

    # Tier 3: Jina Reader (cloud, free)
    content = _try_jina(url)
    if content:
        logger.info("[FETCH_URL] jina OK url=%s len=%d", url, len(content))
        if set_cached is not None:
            set_cached(url, content)
        return _truncate(content, "Jina Reader", url)

    # Tier 4: plain httpx + BeautifulSoup (last resort)
    content = _try_httpx(url)
    if content:
        logger.info("[FETCH_URL] httpx OK url=%s len=%d", url, len(content))
        if set_cached is not None:
            set_cached(url, content)
        return _truncate(content, "httpx", url)

    return (
        f"Không thể lấy nội dung từ {url} sau 3 tier (Crawl4AI / Jina Reader / httpx). "
        "Trang có thể đang bị chặn anti-bot mạnh hoặc không tồn tại."
    )


def get_web_fetch_tools() -> list:
    """Return all web-fetch tools for registration."""
    return [tool_fetch_url]
