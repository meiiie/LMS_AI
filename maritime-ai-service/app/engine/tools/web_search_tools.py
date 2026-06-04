"""
Web Search Tools - Serper.dev (Sprint 198) + DuckDuckGo fallback for AI agents.

SOTA 2026: Agents need web search with resilience (circuit breaker + timeout).
Sprint 198: Primary backend is Serper.dev (Google search API) for reliable
Vietnamese search. Falls back to DuckDuckGo when Serper unavailable.

Sprint 102: Enhanced Vietnamese search — news (RSS + Serper News),
legal (site-restricted), maritime (site-restricted).
"""

import logging
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from app.engine.tools.native_tool import tool

from app.engine.tools.registry import (
    ToolCategory,
    ToolAccess,
    get_tool_registry,
)

logger = logging.getLogger(__name__)

# Timeout for DuckDuckGo calls (seconds)
WEB_SEARCH_TIMEOUT = 10.0

# Thread pool for running sync DuckDuckGo in background
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="web_search")

# Per-tool circuit breaker state (avoids importing resilience.py which is async)
# Sprint audit: Changed from single global CB to per-tool isolation
# to prevent one tool's failures from blocking unrelated tools.
_CB_THRESHOLD = 3
_CB_RECOVERY_SECONDS = 120
_cb_lock = threading.Lock()
_cb_states: dict = {}  # {tool_name: {"failures": int, "last_failure": float}}


# =============================================================================
# Sprint 102: Site restriction constants
# =============================================================================

_LEGAL_SITES = [
    "thuvienphapluat.vn", "vanban.chinhphu.vn",
    "luatvietnam.vn", "congbao.chinhphu.vn",
]

_NEWS_SITES = [
    "vnexpress.net", "tuoitre.vn",
    "thanhnien.vn", "dantri.com.vn",
]

_MARITIME_SITES = [
    "imo.org", "safety4sea.com", "maritime-executive.com",
    "splash247.com", "vinamarine.gov.vn", "mt.gov.vn",
]

_NEWS_RSS_FEEDS = {
    "vnexpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "tuoitre": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "thanhnien": "https://thanhnien.vn/rss/home.rss",
    "dantri": "https://dantri.com.vn/rss/home.rss",
}


# =============================================================================
# SOTA relevance filter — align with Perplexity / Gemini Deep Research
# =============================================================================

# Vietnamese + English function words that should not count as content matches.
# Without this filter, queries like "giá dầu hôm nay" match every trending
# article that contains "hôm nay" — producing noise instead of relevance.
_VI_EN_STOPWORDS = frozenset({
    # Vietnamese common fillers
    "là", "của", "và", "cho", "với", "các", "những", "một", "tôi", "bạn", "mình",
    "hôm", "nay", "qua", "mai", "đang", "sẽ", "có", "không", "được", "rồi",
    "thì", "mà", "như", "để", "từ", "trong", "ngoài", "ở", "đến", "theo",
    "hay", "hoặc", "nhưng", "này", "kia", "đó", "ai", "gì", "sao", "nào",
    "mới", "cũ", "lại", "đã", "chỉ", "cũng", "thêm", "nữa", "ra", "vào",
    "về", "trên", "dưới", "trước", "sau", "giữa", "bên", "lúc", "khi",
    "tại", "bởi", "do", "nên", "vì", "nếu", "thì",
    # English
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "what", "when", "where", "who", "how", "why", "i", "you", "we", "they",
    "today", "now", "current", "latest", "today's",
})


def _content_words(query: str) -> list[str]:
    """Tokenize a query into content-carrying lowercase words (≥2 chars, non-stopword)."""
    raw = [w.strip(".,!?;:\"'()[]{}").lower() for w in (query or "").split()]
    return [w for w in raw if len(w) >= 2 and w not in _VI_EN_STOPWORDS]


def _relevance_score(query: str, result: dict) -> float:
    """Fraction of query content words found in result title+body. 0.0 to 1.0."""
    words = _content_words(query)
    if not words:
        return 1.0
    title = str(result.get("title", ""))
    body = str(result.get("body") or result.get("snippet") or result.get("summary") or "")
    text = f"{title} {body}".lower()
    matches = sum(1 for w in words if w in text)
    return matches / len(words)


def _filter_by_relevance(query: str, results: list, *, threshold: float = 0.5) -> list:
    """Keep results whose content-word overlap with query is ≥ threshold.

    SOTA research agents (Perplexity, Gemini Deep Research) always post-filter
    retrieval — blindly forwarding search output to the LLM pollutes grounding.
    We require ≥50% of content words to appear in title+body by default.
    """
    if not results:
        return results
    scored = [(r, _relevance_score(query, r)) for r in results]
    kept = [r for (r, s) in scored if s >= threshold]
    if not kept:
        # Fallback: keep top-N by score even if all below threshold, so the
        # agent still has something to work from rather than an empty set.
        scored.sort(key=lambda pair: pair[1], reverse=True)
        kept = [r for (r, s) in scored[: min(3, len(scored))] if s > 0]
    return kept


# Finance-specific site list for price/market queries.
_FINANCE_SITES = [
    "tradingview.com", "investing.com", "bloomberg.com",
    "reuters.com", "cnbc.com", "ft.com",
    "vietstock.vn", "cafef.vn", "vneconomy.vn", "ndh.vn",
]

_FINANCE_KEYWORDS = (
    "giá dầu", "giá vàng", "giá xăng", "chứng khoán", "cổ phiếu", "tỷ giá",
    "lãi suất", "trái phiếu", "chỉ số", "vn-index", "vnindex",
    "bitcoin", "ethereum", "crypto", "tiền ảo",
    "brent", "wti", "gold", "oil price", "stock", "forex",
    "usd/vnd", "eur/vnd", "jpy/vnd",
)


def _is_finance_query(query: str) -> bool:
    q = (query or "").lower()
    return any(kw in q for kw in _FINANCE_KEYWORDS)


def _fold_search_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.replace("đ", "d").split())


def _is_weather_search_query(query: str) -> bool:
    folded = _fold_search_text(query)
    return any(
        marker in folded
        for marker in (
            "thoi tiet",
            "nhiet do",
            "du bao thoi tiet",
            "weather",
            "forecast",
            "temperature",
        )
    )


# =============================================================================
# Circuit breaker helpers
# =============================================================================

def _cb_is_open(tool_name: str = "default") -> bool:
    """Check if circuit breaker is open for a specific tool."""
    with _cb_lock:
        state = _cb_states.get(tool_name)
        if not state:
            return False
        if state["failures"] >= _CB_THRESHOLD:
            if time.time() - state["last_failure"] < _CB_RECOVERY_SECONDS:
                return True
            # Recovery period passed — reset
            state["failures"] = 0
        return False


def _cb_record_failure(tool_name: str = "default"):
    """Record a failure for a specific tool's circuit breaker."""
    with _cb_lock:
        if tool_name not in _cb_states:
            _cb_states[tool_name] = {"failures": 0, "last_failure": 0.0}
        _cb_states[tool_name]["failures"] += 1
        _cb_states[tool_name]["last_failure"] = time.time()


def _cb_record_success(tool_name: str = "default"):
    """Record success — reset failure count for a specific tool."""
    with _cb_lock:
        if tool_name in _cb_states:
            _cb_states[tool_name]["failures"] = 0


# =============================================================================
# Sync search helpers (run in ThreadPoolExecutor)
# =============================================================================

def _get_ddgs():
    """Import DDGS with fallback."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    return DDGS


def _search_sync(query: str, max_results: int = 5) -> list:
    """DDG search w/ Valkey cache + region fallback + 1-retry on flake.

    DDG's text() endpoint randomly returns empty results (~10-20% of calls),
    so we retry once on empty and cache the result for 3 minutes per query.
    """
    cache_key = f"ddg:{max_results}:{query.strip().lower()}"

    try:
        from app.engine.tools.web_fetch_cache import _get_client
        import json as _json

        valkey = _get_client()
        if valkey is not None:
            cached_raw = valkey.get(f"wiii:web_search:v1:{cache_key}")
            if cached_raw:
                try:
                    return _json.loads(
                        cached_raw.decode("utf-8") if isinstance(cached_raw, bytes) else str(cached_raw)
                    ) or []
                except Exception:  # noqa: BLE001
                    pass
    except ImportError:
        valkey = None

    DDGS = _get_ddgs()

    # Try vn-vi first, fallback to wt-wt if empty; retry once for DDG flake.
    results: list = []
    last_error: Exception | None = None
    for attempt in range(2):
        for region in ("vn-vi", "wt-wt"):
            try:
                hit = DDGS().text(
                    query,
                    region=region,
                    safesearch="moderate",
                    max_results=max_results,
                    backend="auto",
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug("[DDG] attempt %d region=%s failed: %s", attempt, region, exc)
                continue
            if hit:
                results = hit
                break
        if results:
            break

    if not results and last_error is not None:
        raise last_error

    if results and valkey is not None:
        try:
            import json as _json
            valkey.setex(
                f"wiii:web_search:v1:{cache_key}",
                180,  # 3-min TTL — fresh enough but absorbs DDG flake
                _json.dumps(results),
            )
        except Exception:  # noqa: BLE001
            pass

    return results


def _search_sync_with_timeout(query: str, max_results: int = 5) -> list:
    """Run DDG last-resort search behind the public timeout budget."""
    result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put(("ok", _search_sync(query, max_results)), block=False)
        except Exception as exc:  # noqa: BLE001
            result_queue.put(("error", exc), block=False)

    thread = threading.Thread(
        target=_runner,
        name="web_search_ddg_timeout",
        daemon=True,
    )
    thread.start()

    try:
        status, payload = result_queue.get(timeout=WEB_SEARCH_TIMEOUT)
    except queue.Empty as exc:
        raise TimeoutError("Tìm kiếm web quá thời gian chờ.") from exc
    if status == "error":
        raise payload  # type: ignore[misc]
    return payload if isinstance(payload, list) else []


def _search_site_restricted_sync(query: str, sites: list, max_results: int = 5) -> list:
    """Search DuckDuckGo with site: restriction.

    Sprint 102: Builds "site:a OR site:b" query prefix for domain-specific search.
    Falls back to general search if site-restricted returns nothing.
    """
    DDGS = _get_ddgs()

    site_filter = " OR ".join(f"site:{s}" for s in sites)
    restricted_query = f"({site_filter}) {query}"

    results = DDGS().text(
        restricted_query,
        region="vn-vi",
        safesearch="moderate",
        max_results=max_results,
        backend="auto",
    )
    if results:
        return results

    # Fallback: general search without site restriction
    return DDGS().text(
        query,
        region="vn-vi",
        safesearch="moderate",
        max_results=max_results,
        backend="auto",
    ) or []


def _news_search_sync(query: str, max_results: int = 5) -> list:
    """Search DuckDuckGo News with Vietnamese region.

    Sprint 102: Uses DDGS().news() for news-specific results.
    """
    DDGS = _get_ddgs()
    return DDGS().news(
        query,
        region="vn-vi",
        safesearch="moderate",
        max_results=max_results,
    ) or []


def _rss_fetch_sync(query: str, max_results: int = 5) -> list:
    """Fetch Vietnamese news from RSS feeds, filtered by query keywords.

    Sprint 102: Uses feedparser for RSS aggregation. Graceful on ImportError.
    SOTA filter: require ≥60% of content words to match; reject stopword-only
    matches (e.g. "hôm nay" matching every trending article).
    """
    try:
        import feedparser
    except ImportError:
        return []

    content_query_words = _content_words(query)
    if not content_query_words:
        return []

    results = []
    for source, url in _NEWS_RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = (entry.get("title") or "")
                summary = (entry.get("summary") or "")
                text = f"{title} {summary}".lower()
                matches = sum(1 for w in content_query_words if w in text)
                if matches / max(len(content_query_words), 1) >= 0.6:
                    results.append({
                        "title": title,
                        "body": summary[:300],
                        "href": entry.get("link", ""),
                        "source": source,
                        "date": entry.get("published", ""),
                    })
        except Exception as e:
            logger.debug("[RSS] Failed to parse %s: %s", source, e)

    # Deduplicate by URL
    seen = set()
    deduped = []
    for r in results:
        if r["href"] not in seen:
            seen.add(r["href"])
            deduped.append(r)

    return deduped[:max_results]


# =============================================================================
# Format helpers
# =============================================================================

# =============================================================================
# Phase 35 — Auto deep-fetch (mirror product-search ChainedAdapter pattern).
#
# DDG/Serper trả snippet ngắn (~150 chars). Cho deep queries (giá, phân tích,
# tin tức), snippet không đủ data để LLM trả lời chính xác. Pattern Perplexity
# / Tavily 2026: search trả URLs nhanh → top URL được fetch sâu (Jina/Crawl4AI)
# → augment vào snippet đầu tiên.
# =============================================================================

_DEEP_QUERY_KEYWORDS = (
    # Giá / tài chính / thị trường
    "giá", "price", "tỷ giá", "lãi suất", "brent", "wti", "vàng", "usd", "eur",
    "chứng khoán", "stock", "vn-index", "hsx", "bitcoin", "btc", "eth",
    # Phân tích / so sánh / chi tiết
    "phân tích", "đánh giá", "review", "so sánh", "compare", "chi tiết",
    "tại sao", "why", "ý nghĩa", "khác biệt",
    # Sự kiện hôm nay / mới nhất (cần timestamp + detail)
    "hôm nay", "today", "mới nhất", "latest", "vừa qua", "recent",
)

_DEEP_FETCH_KEYWORDS = (
    # Giá / tài chính / thị trường benefit from full-page detail.
    "giá", "price", "tỷ giá", "lãi suất", "brent", "wti", "vàng", "usd", "eur",
    "chứng khoán", "stock", "vn-index", "hsx", "bitcoin", "btc", "eth",
    # Explicit analysis/detail requests.
    "phân tích", "đánh giá", "review", "so sánh", "compare", "chi tiết",
    "tại sao", "why", "ý nghĩa", "khác biệt",
)

_OFFICIAL_SOURCE_HINTS = (
    "official",
    "chính thức",
    "chinh thuc",
    "trang chủ",
    "trang chu",
    "homepage",
    "blog",
)

_ORG_HOST_HINTS = {
    "openai": "openai.com",
    "anthropic": "anthropic.com",
    "claude": "anthropic.com",
    "google": "google.com",
    "gemini": "google.com",
    "microsoft": "microsoft.com",
    "github": "github.com",
    "nvidia": "nvidia.com",
}

_MONTH_SCORE = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _is_deep_query(query: str) -> bool:
    q = (query or "").lower()
    return any(kw in q for kw in _DEEP_QUERY_KEYWORDS)


def _should_deep_fetch(query: str) -> bool:
    q = (query or "").lower()
    return any(kw in q for kw in _DEEP_FETCH_KEYWORDS)


def _result_url(result: dict) -> str:
    return str(result.get("href") or result.get("url") or result.get("link") or "")


def _has_requested_official_source(query: str, results: list) -> bool:
    q = (query or "").lower()
    if not _requests_official_source(query):
        return False

    expected_hosts = [
        host
        for token, host in _ORG_HOST_HINTS.items()
        if token in q
    ]
    if not expected_hosts:
        return False

    for result in results or []:
        url = _result_url(result)
        try:
            host = urlparse(url).netloc.lower()
        except Exception:  # noqa: BLE001
            host = ""
        if any(host == expected or host.endswith("." + expected) for expected in expected_hosts):
            return True
    return False


def _requests_official_source(query: str) -> bool:
    q = (query or "").lower()
    return any(hint in q for hint in _OFFICIAL_SOURCE_HINTS)


def _official_hosts_for_query(query: str) -> list[str]:
    q = (query or "").lower()
    hosts: list[str] = []
    for token, host in _ORG_HOST_HINTS.items():
        if token in q and host not in hosts:
            hosts.append(host)
    return hosts


def _normalise_model_text(text: str) -> str:
    normalised = str(text or "").lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014"):
        normalised = normalised.replace(dash, "-")
    return normalised


def _extract_gpt_version(text: str) -> float:
    match = re.search(
        r"\bgpt\s*-?\s*(\d+(?:\.\d+)?)\b",
        _normalise_model_text(text),
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def _score_official_result(query: str, result: dict, host: str) -> float:
    title = str(result.get("title") or "")
    body = str(result.get("body") or result.get("summary") or result.get("snippet") or "")
    url = _result_url(result)
    text = f"{title} {body} {url}".lower()
    score = _relevance_score(query, result)
    try:
        parsed_host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        parsed_host = ""
    if parsed_host == host or parsed_host.endswith("." + host):
        score += 2.0
    if f"{host}/index/" in url.lower() or "/index/" in url.lower():
        score += 0.8
    if any(marker in text for marker in ("introducing", "release", "releasing", "announces", "announcement")):
        score += 0.8
    if any(marker in text for marker in ("gpt", "model", "frontier", "codex")):
        score += 0.4
    title_lc = _normalise_model_text(title)
    if "gpt" in title_lc:
        score += 2.0
    if "introducing" in title_lc:
        score += 1.2
    if any(marker in title_lc for marker in ("retiring", "privacy filter")):
        score -= 4.0
    for year in re.findall(r"\b20\d{2}\b", query or ""):
        if year in text:
            score += 0.6
    if any(marker in (query or "").lower() for marker in ("latest", "recent", "mới nhất", "moi nhat")):
        gpt_version = _extract_gpt_version(title)
        if gpt_version:
            score += gpt_version * 4.0
        if "introducing gpt" in title_lc:
            score += 1.0
        date_match = re.search(
            r"\b("
            + "|".join(sorted(_MONTH_SCORE, key=len, reverse=True))
            + r")\.?\s+(\d{1,2}),\s+(20\d{2})\b",
            text,
            flags=re.IGNORECASE,
        )
        if date_match:
            month = _MONTH_SCORE.get(date_match.group(1).lower().rstrip("."), 0)
            day = int(date_match.group(2))
            year = int(date_match.group(3))
            score += ((year - 2020) * 12 + month) + (day / 31.0)
    return score


def _official_site_search_sync(query: str, *, max_results: int = 5) -> list:
    """Fast path for user-requested official/blog sources.

    Local SearXNG may be unavailable during Docker restarts; for official
    source turns, a direct site-restricted DDG query is both faster and less
    noisy than waiting for generic multi-engine/news merging.
    """
    if not _requests_official_source(query):
        return []

    hosts = _official_hosts_for_query(query)
    if not hosts:
        return []

    merged: list[dict] = []
    seen_urls: set[str] = set()
    for host in hosts[:2]:
        site_scope = f"site:{host}/index" if host == "openai.com" else f"site:{host}"
        official_query = f"{site_scope} {query}"
        try:
            results = _search_sync_with_timeout(official_query, max_results=max_results) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("[WEB_SEARCH] Official site search failed for %s: %s", host, exc)
            continue

        for result in results:
            url = _result_url(result)
            if not url or url in seen_urls:
                continue
            try:
                parsed_host = urlparse(url).netloc.lower()
            except Exception:  # noqa: BLE001
                parsed_host = ""
            if parsed_host != host and not parsed_host.endswith("." + host):
                continue
            seen_urls.add(url)
            copied = dict(result)
            copied["_official_score"] = _score_official_result(query, copied, host)
            merged.append(copied)

    merged.sort(key=lambda item: float(item.get("_official_score") or 0.0), reverse=True)
    for item in merged:
        item.pop("_official_score", None)
    return merged[:max_results]


def _augment_top_result_with_deep_fetch(
    results: list,
    query: str,
    *,
    max_chars: int = 1500,
    top_k: int = 2,
    deadline_s: float = 6.0,
) -> list:
    """Parallel deep-fetch top-K URLs and merge markdown into snippets.

    SOTA pattern (Perplexity / Tavily 2026):
    - search engine returns URLs + snippets fast (~1s)
    - top-K URLs fetched IN PARALLEL via asyncio.gather (~5-12s for 3 URLs)
    - failed fetches are silently skipped (graceful degradation)
    - Valkey cache hit makes repeat queries near-instant
    - whole batch capped by `deadline_s` — ranks > completeness

    No-op when:
    - results empty
    - query is casual/conversational
    - query only asks for recency/latest headlines and snippets are enough
    - no http(s) URLs in top-K
    """
    if not results or not _should_deep_fetch(query):
        return results

    candidates: list[tuple[int, str]] = []
    for idx, item in enumerate(results[:top_k]):
        url = item.get("href") or item.get("url") or item.get("link")
        if (
            isinstance(url, str)
            and (url.startswith("http://") or url.startswith("https://"))
            and "news.google.com/rss/" not in url.lower()
        ):
            candidates.append((idx, url))

    if not candidates:
        return results

    try:
        from app.engine.tools.web_fetch_tool import (
            _crawl4ai_async,
            _try_jina,
            _run_async_in_thread,
        )
        from app.engine.tools.web_fetch_cache import get_cached, set_cached
    except ImportError:
        return results

    import asyncio

    async def _fetch_one(idx: int, url: str) -> tuple[int, str | None]:
        # 1. cache hit — instant return
        cached = get_cached(url)
        if cached:
            return idx, cached
        # 2. Try Jina first (cloud, ~3-8s typical)
        loop = asyncio.get_event_loop()
        jina_content = await loop.run_in_executor(None, _try_jina, url)
        if jina_content:
            set_cached(url, jina_content)
            return idx, jina_content
        # 3. Fallback Crawl4AI (local, ~10-15s — slower but no rate limit)
        c4_content = await _crawl4ai_async(url)
        if c4_content:
            set_cached(url, c4_content)
            return idx, c4_content
        return idx, None

    async def _fetch_all() -> list[tuple[int, str | None]]:
        tasks = [_fetch_one(i, u) for i, u in candidates]
        try:
            return await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=deadline_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[WEB_SEARCH] Deep-fetch deadline %ss exceeded; returning partial",
                deadline_s,
            )
            return []

    try:
        fetched = _run_async_in_thread(_fetch_all(), deadline_s + 3.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WEB_SEARCH] Parallel fetch failed: %s", exc)
        return results

    augmented_count = 0
    for entry in fetched:
        if isinstance(entry, BaseException) or entry is None:
            continue
        try:
            idx, content = entry
        except (TypeError, ValueError):
            continue
        if not content or len(content) < 200:
            continue

        trimmed = content.strip()[:max_chars]
        existing = str(results[idx].get("body") or "").strip()
        url_hint = (
            results[idx].get("href")
            or results[idx].get("url")
            or results[idx].get("link")
            or ""
        )
        results[idx]["body"] = (
            f"{existing}\n\n"
            f"[Nội dung chi tiết từ {url_hint}]\n{trimmed}"
        )
        augmented_count += 1

    if augmented_count > 0:
        logger.info(
            "[WEB_SEARCH] Augmented %d/%d top results in parallel (deadline=%ss)",
            augmented_count, len(candidates), deadline_s,
        )
    return results


def _searxng_search_sync(
    query: str,
    *,
    max_results: int = 8,
    categories: str = "general",
    time_range: str | None = None,
    language: str = "vi",
) -> list:
    """SearXNG meta-search — aggregates Google + Bing + Brave + DDG + Qwant + ...

    Pattern (Open WebUI / LiteLLM / Cherry Studio 2026): self-hosted SearXNG
    is the open-source equivalent of SerpAPI. AGPL-3.0, no API key, no rate
    limit — Wiii is the sole client. JSON output enabled in settings.yml.

    Returns DDG-shape dicts so callers transparently use it as a drop-in.
    Empty list on error — caller falls through to next engine.
    """
    try:
        from app.core.config import settings
        # Default to internal docker network address; override via env if external.
        configured_url = getattr(settings, "searxng_url", None)
    except Exception:  # noqa: BLE001
        configured_url = None

    try:
        import httpx
        params = {
            "q": query,
            "format": "json",
            "categories": categories,
            "language": language,
            "pageno": 1,
            "safesearch": 0,
        }
        if time_range:
            params["time_range"] = time_range  # day | week | month | year
        for index, base_url in enumerate(_searxng_base_url_candidates(configured_url)):
            try:
                resp = httpx.get(
                    f"{base_url.rstrip('/')}/search",
                    params=params,
                    timeout=8.0 if index == 0 else 3.0,
                    follow_redirects=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[SEARXNG] %s failed: %s", base_url, exc)
                continue
            if resp.status_code != 200:
                logger.debug(
                    "[SEARXNG] HTTP %d via %s for: %s",
                    resp.status_code,
                    base_url,
                    query[:60],
                )
                continue
            data = resp.json() or {}
            results = data.get("results") or []
            normalized = [
                {
                    "title": str(r.get("title", ""))[:200],
                    "body": r.get("content") or r.get("description", ""),
                    "href": r.get("url", ""),
                    "date": r.get("publishedDate", ""),
                    "source": r.get("engine", "searxng"),
                }
                for r in results[:max_results]
                if r.get("url")
            ]
            if normalized:
                logger.info(
                    "[SEARXNG] %s returned %d results for: %s",
                    base_url,
                    len(normalized),
                    query[:60],
                )
                return normalized
        return []
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SEARXNG] failed: %s", exc)
        return []


def _searxng_base_url_candidates(configured_url: str | None) -> list[str]:
    base_url = (configured_url or "http://searxng:8080").strip().rstrip("/")
    candidates = [base_url]
    if base_url == "http://searxng:8080":
        candidates.extend(
            [
                "http://host.docker.internal:8080",
                "http://127.0.0.1:8080",
            ]
        )
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


_FINANCE_QUERY_TO_EN: tuple[tuple[str, str], ...] = (
    # Vietnamese finance terms → English equivalent for international news
    ("giá dầu", "oil price"),
    ("giá vàng", "gold price"),
    ("giá xăng", "gasoline price"),
    ("giá đô", "USD exchange rate"),
    ("tỷ giá", "exchange rate"),
    ("chứng khoán", "stock market"),
    ("bitcoin", "bitcoin price"),
    ("brent", "Brent crude"),
    ("wti", "WTI crude"),
    ("opec", "OPEC"),
    ("fed", "Fed interest rate"),
    ("hôm nay", "today"),
    ("mới nhất", "latest"),
)


# Phase 35 — Topic-aware breaking-news anchor (DYNAMIC).
#
# DESIGN RATIONALE:
# Hardcoding event names ("Iran Hormuz Middle East") works today but drifts
# out of date as news cycles shift. Professional pattern (Reuters, Bloomberg,
# Perplexity, Tavily 2026) is two-pass:
#
#   Pass 1: search the STABLE domain seed (e.g. "oil energy market" — never
#           changes for finance queries about oil) → recent headlines.
#   Pass 2: extract the most-frequent proper-noun ENTITIES from those
#           headlines (Iran, OPEC, Hormuz, UAE, Russia, ...) → use them
#           as the breaking-news anchor for a follow-up targeted search.
#
# This way the anchor adapts to whatever's currently driving the market.
# Six months from now if Russia/Ukraine becomes the dominant oil driver,
# entity extraction will surface "Russia Ukraine" automatically — no code
# change needed. The static piece is only the DOMAIN ROUTING (oil ↔ energy
# market), which is stable across decades.

# Stable domain seeds — these capture the topic, not the event.
# Selected to be both descriptive and search-engine friendly.
_DOMAIN_SEED_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("giá dầu", "dầu thô", "dầu mỏ", "brent", "wti", "crude", "oil", "petroleum"),
     "oil market price today"),
    (("giá vàng", "vàng", "gold", "xau"),
     "gold price market today"),
    (("giá usd", "tỷ giá", "dollar", "dxy", "đô la", "ngoại tệ"),
     "currency exchange rate today"),
    (("chứng khoán", "vn-index", "vnindex", "stock", "equity", "cổ phiếu"),
     "stock market today"),
    (("bitcoin", "btc", "crypto", "ether", "eth", "tiền số"),
     "cryptocurrency market today"),
    (("lãi suất", "fed", "lạm phát", "inflation", "interest rate"),
     "Federal Reserve interest rate inflation today"),
    (("opec", "opec+"),
     "OPEC oil production today"),
)

# Stop-words for entity extraction. Common English/news vocabulary that
# isn't a useful entity even when capitalized. Carefully curated to NOT
# filter out the names that drive markets (Iran, Trump, OPEC, etc).
_ENTITY_STOPWORDS: frozenset[str] = frozenset({
    # Articles/prepositions
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "to",
    "of", "in", "on", "at", "by", "as", "is", "are", "was", "were",
    "this", "that", "these", "those", "it", "its", "after", "before",
    # Time
    "today", "yesterday", "tomorrow",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    # News headline boilerplate
    "live", "updates", "report", "reports", "reuters", "factbox",
    "factcheck", "explainer", "video", "watch", "analysis", "exclusive",
    "breaking", "alert",
    # Speech verbs
    "say", "says", "said", "tells", "told", "claims", "claim", "asks",
    # Generic finance terms (NOT entity-worthy — they're the ROUTING signal,
    # not the discovered driver. Drop so they don't crowd out actual events.)
    "stock", "stocks", "market", "markets", "index", "cap", "fund",
    "funds", "sector", "sectors", "trading", "exchange", "rate", "rates",
    "price", "prices", "growth", "loss", "losses", "gain", "gains",
    # Specific stock-index names (Indian/US/EU) — useful for stock queries
    # but POLLUTING for oil/gold/crypto queries when SearXNG cross-pollinates
    "nifty", "sensex", "gift", "dow", "nasdaq", "ftse", "dax", "nikkei",
    "sgx", "kospi", "hsi", "asx", "ibex",
    # Common qualifiers
    "high", "low", "level", "amid", "ahead", "after", "near", "over",
    "rises", "falls", "drops", "jumps", "soars", "plunges", "tumbles",
    "rises", "rallies", "extends",
    # News outlet names — they're SOURCES, not events
    "cnbc", "bloomberg", "wsj", "bbc", "ft", "ap", "afp", "vnexpress",
    "tuoitre", "thanhnien", "vov", "vietnamnet",
})

# Domain co-occurrence filter: a headline is "on-topic" only when it
# contains at least one domain-anchor word. Prevents Indian-stocks news
# from polluting oil entity extraction.
_DOMAIN_COOCCUR: dict[str, tuple[str, ...]] = {
    "oil market price today": ("oil", "crude", "brent", "wti", "petroleum",
                                "barrel", "opec", "refinery"),
    "gold price market today": ("gold", "bullion", "xau", "ounce"),
    "currency exchange rate today": ("dollar", "currency", "exchange",
                                       "fx", "forex", "yuan", "yen", "euro"),
    "stock market today": ("stock", "share", "equity", "market", "wall",
                            "index", "nasdaq", "s&p"),
    "cryptocurrency market today": ("bitcoin", "btc", "ethereum", "crypto",
                                      "blockchain", "altcoin"),
    "Federal Reserve interest rate inflation today": ("fed", "powell",
        "inflation", "rate", "treasury", "yield"),
    "OPEC oil production today": ("opec", "oil", "barrel", "saudi",
                                   "crude", "production"),
}


def _domain_seed_for(query: str) -> str | None:
    """Return the stable domain seed for the query topic, or None when no
    finance/market topic is detected. Routing is deliberately conservative —
    only routes when at least one explicit keyword matches."""
    q_lower = (query or "").lower()
    for triggers, seed in _DOMAIN_SEED_KEYWORDS:
        if any(t in q_lower for t in triggers):
            return seed
    return None


def _extract_news_entities(
    headlines: list[dict],
    *,
    domain_seed: str | None = None,
    max_entities: int = 6,
    min_freq: int = 2,
) -> list[str]:
    """Extract frequent proper-noun entities from news headline titles.

    Pure heuristic (no NER model dependency):
      - Filter headlines by domain co-occurrence (e.g. for oil seed, headline
        must contain "oil"/"crude"/"brent" — drops cross-pollinated stock
        index news that SearXNG mixes in)
      - Tokenize each on-topic headline title
      - Keep tokens that look like proper nouns (start uppercase, len >= 3)
      - Drop stop-words (months, days, headline boilerplate, generic finance,
        news outlet names, stock-index names)
      - Drop pure-numeric and ALL-CAPS abbreviations < 4 chars (tickers)
      - Count frequency across on-topic headlines, return top-N

    Real-world validation: for today's oil headlines this surfaces
    {"Iran", "Hormuz", "OPEC", "UAE", "Trump", "Saudi"} — the actual drivers.
    """
    import re as _re
    from collections import Counter

    cooccur_terms = _DOMAIN_COOCCUR.get(domain_seed) if domain_seed else None

    counter: Counter = Counter()
    on_topic_count = 0
    for h in headlines:
        title = str(h.get("title") or "")
        if not title:
            continue
        # Domain co-occurrence pre-filter: skip headlines that aren't about
        # the requested topic (e.g. drop "Sensex closes flat" when looking
        # for oil entities). Without this filter, generic stock news
        # crowds out market drivers.
        if cooccur_terms:
            title_lower = title.lower()
            if not any(t in title_lower for t in cooccur_terms):
                continue
        on_topic_count += 1
        # Token: 3+ alphanumeric or accented chars
        for tok in _re.findall(r"[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9'’\-]{2,}", title):
            t = tok.strip()
            t_lower = t.lower()
            if t_lower in _ENTITY_STOPWORDS:
                continue
            # Require uppercase first letter (proper-noun-ish)
            if not t[0].isupper():
                continue
            # Drop short ALL-CAPS (likely tickers like AAPL)
            if t.isupper() and len(t) < 4:
                continue
            counter[t] += 1

    if cooccur_terms and on_topic_count == 0:
        # Co-occurrence filter dropped everything → fall back to no filter
        # rather than return zero entities (avoids breaking unfamiliar topics).
        return _extract_news_entities(
            headlines,
            domain_seed=None,
            max_entities=max_entities,
            min_freq=min_freq,
        )

    return [
        word for word, freq in counter.most_common(max_entities * 2)
        if freq >= min_freq
    ][:max_entities]


# Cache: (domain_seed) → (entities, expires_at). News cycle moves fast —
# 5 min freshness is the sweet spot between API load and freshness.
_BREAKING_ENTITY_CACHE: dict[str, tuple[list[str], float]] = {}
_BREAKING_ENTITY_TTL_SEC = 300.0


def _dynamic_breaking_anchor(query: str) -> str | None:
    """Return a domain-aware breaking-news anchor built from CURRENT headlines.

    Two-pass discovery:
      1. Map query → stable domain seed via `_domain_seed_for` (never drifts).
      2. Search SearXNG news for that seed (time_range=day) → headlines.
      3. Extract top proper-noun entities → form anchor as
         `{seed} {entity1} {entity2} ...`.

    Result: "oil market price today Iran OPEC Hormuz UAE" rather than the
    hardcoded "Iran Hormuz Middle East oil tension OPEC". When the next
    geopolitical shock displaces Iran from headlines, the anchor adapts.

    Returns None when no domain match — the caller skips breaking-anchor
    fetch entirely (saves time on non-finance queries).
    """
    seed = _domain_seed_for(query)
    if not seed:
        return None

    import time
    cached = _BREAKING_ENTITY_CACHE.get(seed)
    now = time.time()
    if cached and cached[1] > now:
        entities = cached[0]
    else:
        try:
            headlines = _searxng_search_sync(
                seed,
                max_results=15,
                categories="news",
                time_range="day",
                language="en",
            ) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("[BREAKING_ANCHOR] seed-search failed: %s", exc)
            headlines = []
        entities = _extract_news_entities(headlines, domain_seed=seed)
        _BREAKING_ENTITY_CACHE[seed] = (entities, now + _BREAKING_ENTITY_TTL_SEC)
        logger.info(
            "[BREAKING_ANCHOR] seed=%r → top entities=%s",
            seed[:40], entities[:6],
        )

    if not entities:
        # No entities extracted (e.g. SearXNG empty). Fall back to seed alone.
        return seed
    # Combine seed + top entities. Cap at 8 tokens total to stay within
    # SearXNG's optimal query length.
    return " ".join([seed] + entities[:5])[:200]


# Backward-compat alias kept so external callers (and tests) don't break.
_topic_breaking_anchor = _dynamic_breaking_anchor


def _translate_finance_query_en(query: str) -> str | None:
    """Lightweight Vietnamese-finance → English query bridge.

    Pattern: avoid LLM round-trip for translation. For known finance terms,
    substitute keywords directly. Returns None if no finance terms detected
    (caller should skip English search to avoid noise).
    """
    q_lower = (query or "").lower()
    matches = [
        en for vi, en in _FINANCE_QUERY_TO_EN if vi in q_lower
    ]
    if not matches:
        return None
    # Build English query from substitutions; preserve numbers/dates from original.
    import re as _re
    nums = _re.findall(r"\d{1,4}[/\-.]?\d{0,2}[/\-.]?\d{0,4}", query)
    return " ".join(matches + nums + ["news"])[:200]


def _google_news_rss_sync(query: str, *, max_results: int = 5, hl: str = "vi", gl: str = "VN") -> list:
    """Google News RSS — free, no API key, breaking-news index.

    Uses Google News public RSS endpoint:
        https://news.google.com/rss/search?q=<query>&hl=vi&gl=VN&ceid=VN:vi

    Pattern: zero-config breaking news source. Indexed by Google = freshest
    available. Complements SearXNG (general) + DDG.news (privacy).
    """
    try:
        from urllib.parse import quote_plus
        import feedparser
    except ImportError:
        return []

    try:
        ceid = f"{gl}:{hl}"
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
        )
        feed = feedparser.parse(url)
        results = []
        for entry in (feed.entries or [])[:max_results]:
            results.append({
                "title": str(entry.get("title", ""))[:200],
                "body": str(entry.get("summary", ""))[:600],
                "href": entry.get("link", ""),
                "date": entry.get("published", ""),
                "source": "google_news",
            })
        return results
    except Exception as exc:  # noqa: BLE001
        logger.debug("[GNEWS_RSS] failed: %s", exc)
        return []


def _brave_search_sync(query: str, max_results: int = 8) -> list:
    """Brave Search API (free tier 2k/month). Optional — only runs if BRAVE_API_KEY set.

    Pattern: multi-engine resilience. Brave offers higher quality + better
    freshness than DDG. Free tier: 2k searches/month, 1 RPS rate limit.
    Returns DDG-shape results so callers can transparently substitute.

    Sign up: https://brave.com/search/api/ → free tier "Data for Search".
    """
    try:
        from app.core.config import settings
        api_key = getattr(settings, "brave_api_key", "") or ""
    except Exception:  # noqa: BLE001
        api_key = ""
    if not api_key:
        return []

    try:
        import httpx
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results, "country": "VN"},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            timeout=8.0,
        )
        if resp.status_code != 200:
            logger.debug("[BRAVE_SEARCH] HTTP %d for: %s", resp.status_code, query[:60])
            return []
        data = resp.json() or {}
        web = (data.get("web") or {}).get("results") or []
        return [
            {
                "title": r.get("title", "")[:200],
                "body": r.get("description", ""),
                "href": r.get("url", ""),
                "date": r.get("age", ""),
                "source": "brave",
            }
            for r in web
            if r.get("url")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("[BRAVE_SEARCH] failed: %s", exc)
        return []


def _merge_news_into_search(
    results: list, query: str, *, news_quota: int = 3, deadline_s: float = 8.0
) -> list:
    """Inject FRESH news at top for time-sensitive queries.

    Pattern (Perplexity / Tavily): mix engines.
    - Google News RSS: fresh-indexed articles from major outlets (free, no key)
    - SearXNG news category: fallback (aggregates Google News + Bing News +
      Reuters + AP via 70-engine pool)
    - DDG news: last resort

    Dedup by URL. News results placed at top because they're time-fresh —
    critical for "hôm nay" queries to surface breaking events
    (e.g. Iran/Hormuz escalation for oil-price queries).
    """
    if not _is_deep_query(query) or not results:
        return results

    # SOTA pattern (Perplexity / Tavily): query MULTIPLE news sources in
    # PARALLEL and interleave by perspective, NOT sequential fallback.
    # - Google News RSS bilingual (VN + EN press)
    # - SearXNG news category (Bing News + Reuters + Yahoo News + Brave News)
    # - DDG news (last resort if both above quiet)
    #
    # Why parallel: Vietnamese press lags wire services on breaking events
    # (e.g. Iran-US Hormuz escalation indexed by Reuters within minutes,
    # by VnExpress hours-to-days later). Sequential fallback never touched
    # SearXNG news because Google News RSS rarely returns empty.
    import concurrent.futures
    en_query = _translate_finance_query_en(query)

    def _fetch_gnews_vi() -> list[dict]:
        try:
            return _google_news_rss_sync(query, max_results=news_quota, hl="vi", gl="VN") or []
        except Exception:  # noqa: BLE001
            return []

    def _fetch_gnews_en() -> list[dict]:
        if not en_query:
            return []
        try:
            return _google_news_rss_sync(en_query, max_results=news_quota, hl="en", gl="US") or []
        except Exception:  # noqa: BLE001
            return []

    def _fetch_searxng_news() -> list[dict]:
        try:
            return _searxng_search_sync(
                query, max_results=news_quota * 2,
                categories="news", time_range="week",
            ) or []
        except Exception:  # noqa: BLE001
            return []

    def _fetch_searxng_news_en() -> list[dict]:
        if not en_query:
            return []
        try:
            return _searxng_search_sync(
                en_query, max_results=news_quota * 2,
                categories="news", time_range="day", language="en",
            ) or []
        except Exception:  # noqa: BLE001
            return []

    # Phase 35 — topic-aware breaking-news anchor.
    # For oil/gold/crypto queries, ALSO search the domain-specific anchor
    # ("Iran Hormuz Middle East oil tension OPEC" for oil) → surfaces wire
    # service articles about the actual market mover, not just price recaps.
    breaking_anchor = _topic_breaking_anchor(query)

    def _fetch_breaking_anchor() -> list[dict]:
        if not breaking_anchor:
            return []
        try:
            return _searxng_search_sync(
                breaking_anchor, max_results=news_quota * 2,
                categories="news", time_range="day", language="en",
            ) or []
        except Exception:  # noqa: BLE001
            return []

    def _fetch_breaking_gnews() -> list[dict]:
        if not breaking_anchor:
            return []
        try:
            return _google_news_rss_sync(
                breaking_anchor, max_results=news_quota,
                hl="en", gl="US",
            ) or []
        except Exception:  # noqa: BLE001
            return []

    news_hits: list[dict] = []
    seen_titles: set[str] = set()

    # Use as_completed + global deadline. Per-future timeouts cascade-fail
    # when ANY future is slow (SearXNG news can take 15s while GNews RSS
    # returns in 4s). With as_completed, slow tasks just get skipped.
    vi_hits: list[dict] = []
    en_hits: list[dict] = []
    sx_hits: list[dict] = []
    sx_en_hits: list[dict] = []
    breaking_hits: list[dict] = []
    breaking_gnews_hits: list[dict] = []

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
    try:
        future_map = {
            pool.submit(_fetch_gnews_vi): "vi",
            pool.submit(_fetch_gnews_en): "en",
            pool.submit(_fetch_searxng_news): "sx",
            pool.submit(_fetch_searxng_news_en): "sx_en",
            pool.submit(_fetch_breaking_anchor): "breaking_sx",
            pool.submit(_fetch_breaking_gnews): "breaking_gn",
        }
        try:
            for fut in concurrent.futures.as_completed(
                future_map.keys(), timeout=deadline_s
            ):
                tag = future_map[fut]
                try:
                    result_list = fut.result(timeout=0.1) or []
                except Exception:  # noqa: BLE001
                    result_list = []
                if tag == "vi":
                    vi_hits = result_list
                elif tag == "en":
                    en_hits = result_list
                elif tag == "sx":
                    sx_hits = result_list
                elif tag == "sx_en":
                    sx_en_hits = result_list
                elif tag == "breaking_sx":
                    breaking_hits = result_list
                elif tag == "breaking_gn":
                    breaking_gnews_hits = result_list
        except concurrent.futures.TimeoutError:
            logger.debug(
                "[NEWS_MERGE] some fetchers exceeded %.1fs deadline; using partial",
                deadline_s,
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if breaking_anchor:
        logger.info(
            "[NEWS_MERGE] breaking-anchor=%r → SearXNG=%d + GNews=%d hits",
            breaking_anchor[:50], len(breaking_hits), len(breaking_gnews_hits),
        )

    # Interleave by source for diverse perspective.
    # PRIORITY 1: breaking-anchor news (event-specific, e.g. "Iran missile US warship")
    # PRIORITY 2: English wire services (Reuters/Bing News on the topic)
    # PRIORITY 3: Vietnamese press
    # PRIORITY 4: Generic Google News (fallback)
    interleave_pools = [
        breaking_hits,        # Topic-specific event news first (Iran/Hormuz/OPEC for oil)
        breaking_gnews_hits,  # Same anchor via GNews RSS (different index)
        sx_en_hits,           # English wire services on literal query
        vi_hits,              # Vietnamese press
        sx_hits,              # Bing News / Reuters Vietnamese
        en_hits,              # Google News English on literal query
    ]
    cap = news_quota * 2
    for i in range(max(len(p) for p in interleave_pools) if any(interleave_pools) else 0):
        for pool_hits in interleave_pools:
            if i >= len(pool_hits):
                continue
            hit = pool_hits[i]
            title_key = (hit.get("title") or "")[:60].lower()
            if title_key and title_key not in seen_titles:
                news_hits.append(hit)
                seen_titles.add(title_key)
            if len(news_hits) >= cap:
                break
        if len(news_hits) >= cap:
            break

    # Last resort: DDG news (only if all above empty)
    if not news_hits:
        try:
            news_hits = _news_search_sync(query, max_results=news_quota) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("[NEWS_MERGE] ddg news failed: %s", exc)
            news_hits = []

    if not news_hits:
        return results

    # Normalize news shape into search shape (url → href, body via excerpt).
    normalized: list[dict] = []
    seen_urls = {
        str(r.get("href") or r.get("url") or "").lower()
        for r in results
    }
    for hit in news_hits[:news_quota]:
        url = hit.get("url") or hit.get("href") or hit.get("link")
        if not url or str(url).lower() in seen_urls:
            continue
        normalized.append({
            "title": hit.get("title", "")[:200],
            "body": hit.get("body") or hit.get("excerpt", ""),
            "href": url,
            "date": hit.get("date") or hit.get("published", ""),
            "source": hit.get("source", "news"),
        })

    if not normalized:
        return results

    logger.info(
        "[WEB_SEARCH] Merged %d fresh news hits at top of %d search results",
        len(normalized), len(results),
    )
    return normalized + results


def _format_results(results: list, tag: str = "WEB_SEARCH") -> str:
    """Format search results into readable text."""
    formatted = []
    for r in results:
        title = r.get("title", "Không có tiêu đề")
        body = r.get("body", r.get("summary", ""))
        href = r.get("href", r.get("url", r.get("link", "")))
        date = r.get("date", r.get("published", ""))
        source = r.get("source", "")
        line = f"**{title}**"
        if date:
            line += f" ({date})"
        if source:
            line += f" [{source}]"
        line += f"\n{body}"
        if href:
            line += f"\nURL: {href}"
        formatted.append(line)

    logger.info("[%s] Found %d results", tag, len(results))
    return "\n\n---\n\n".join(formatted)


# =============================================================================
# Tool: General web search (existing)
# =============================================================================

@tool(description="Tìm kiếm thông tin trên web. Hữu ích khi cần thông tin mới nhất, tin tức, hoặc kiến thức không có trong cơ sở dữ liệu nội bộ.")
def tool_web_search(query: str) -> str:
    """Search the web for current information. Uses Serper.dev (Sprint 198) with DuckDuckGo fallback."""
    _CB_NAME = "web_search"
    if _cb_is_open(_CB_NAME):
        logger.warning("[WEB_SEARCH] Circuit breaker OPEN — skipping search")
        return "Tìm kiếm web tạm thời không khả dụng. Vui lòng thử lại sau."

    try:
        # Sprint 198: Try Serper first
        from app.engine.tools.serper_web_search import is_serper_available, _serper_search

        if is_serper_available():
            # SOTA finance routing: for price/market queries, restrict to
            # dedicated financial sites first (TradingView, Bloomberg, Reuters,
            # VietStock, CafeF) — generic Google returns noise for real-time prices.
            if _is_finance_query(query):
                site_filter = " OR ".join(f"site:{s}" for s in _FINANCE_SITES)
                finance_q = f"({site_filter}) {query}"
                finance_results = _serper_search(finance_q, max_results=5)
                finance_results = _filter_by_relevance(query, finance_results, threshold=0.4)
                if finance_results:
                    _cb_record_success(_CB_NAME)
                    logger.info("[WEB_SEARCH] Finance-site branch returned %d results", len(finance_results))
                    finance_results = _augment_top_result_with_deep_fetch(finance_results, query)
                    return _format_results(finance_results, "WEB_SEARCH")

            results = _serper_search(query, max_results=8)
            results = _filter_by_relevance(query, results, threshold=0.5)
            if results:
                _cb_record_success(_CB_NAME)
                results = _augment_top_result_with_deep_fetch(results[:5], query)
                return _format_results(results, "WEB_SEARCH")
            # Serper returned empty — fall through to DuckDuckGo

        official_results = _official_site_search_sync(query, max_results=5)
        if official_results:
            _cb_record_success(_CB_NAME)
            logger.info(
                "[WEB_SEARCH] Official-site branch returned %d results",
                len(official_results),
            )
            return _format_results(official_results, "WEB_SEARCH")

        # Phase 35 — SOTA layered open-source search:
        # Tier 1: SearXNG self-hosted (aggregates Google + Bing + Brave + DDG +
        #         70 more engines; AGPL-3.0; 60k★) — primary, free forever.
        # Tier 2: Brave Search API (free 2k/month, only if BRAVE_API_KEY set).
        # Tier 3: DDG direct (last resort, flake-prone).
        results = _searxng_search_sync(query, max_results=8) or []
        if results:
            logger.info("[WEB_SEARCH] SearXNG returned %d results for: %s", len(results), query[:60])

        if not results:
            results = _brave_search_sync(query, max_results=8) or []
            if results:
                logger.info("[WEB_SEARCH] Brave returned %d results for: %s", len(results), query[:60])

        # DDG last resort — keep it behind the same timeout/circuit breaker
        # budget as the rest of the search stack.
        if not results:
            results = _search_sync_with_timeout(query) or []
            if not results:
                results = _search_sync_with_timeout(query) or []  # 1-retry on flake
        results = _filter_by_relevance(query, results, threshold=0.4)

        if not results:
            return "Không tìm thấy kết quả trên web."

        _cb_record_success(_CB_NAME)
        # Phase 35 — multi-engine merge: news endpoint at top for time queries.
        # If the user explicitly asks for an official source and search already
        # found that host, keep the official result set instead of spending
        # 10-20s merging generic news wrappers above it.
        if not _requests_official_source(query) and not _is_weather_search_query(query):
            results = _merge_news_into_search(results, query)
        results = _augment_top_result_with_deep_fetch(results[:5], query)
        return _format_results(results, "WEB_SEARCH")

    except ImportError:
        return "Lỗi: Chưa cài đặt duckduckgo-search. Chạy: pip install duckduckgo-search"

    except Exception as e:
        _cb_record_failure(_CB_NAME)
        logger.warning("[WEB_SEARCH] Failed: %s", e)
        return f"Lỗi tìm kiếm: {e}"


# =============================================================================
# Sprint 102: Tool — Vietnamese news search
# =============================================================================

# Sprint 204: Neutral description — guidance is in system prompt, not tool metadata
@tool(description=(
    "Tìm kiếm TIN TỨC Việt Nam — tin tức, thời sự, sự kiện, bản tin, báo chí. "
    "Nguồn: VnExpress, Tuổi Trẻ, Thanh Niên, Dân Trí + RSS feeds."
))
def tool_search_news(query: str) -> str:
    """Search Vietnamese news using Serper.dev News (Sprint 198) + RSS feeds."""
    _CB_NAME = "search_news"
    if _cb_is_open(_CB_NAME):
        logger.warning("[NEWS_SEARCH] Circuit breaker OPEN — skipping search")
        return "Tìm kiếm tin tức tạm thời không khả dụng. Vui lòng thử lại sau."

    try:
        import concurrent.futures

        # Sprint 198: Try Serper news + RSS in parallel
        from app.engine.tools.serper_web_search import is_serper_available, _serper_news_search

        serper_results = []
        rss_results = []

        if is_serper_available():
            serper_results = _serper_news_search(query, max_results=5, gl="vn", hl="vi")
        else:
            # DuckDuckGo News fallback
            news_future = _executor.submit(_news_search_sync, query, 5)
            try:
                serper_results = news_future.result(timeout=WEB_SEARCH_TIMEOUT)
            except concurrent.futures.TimeoutError:
                logger.warning("[NEWS_SEARCH] DuckDuckGo news timeout")

        # RSS always runs (independent source)
        rss_future = _executor.submit(_rss_fetch_sync, query, 5)
        try:
            rss_results = rss_future.result(timeout=WEB_SEARCH_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.warning("[NEWS_SEARCH] RSS fetch timeout")

        # Merge and deduplicate by URL
        all_results = []
        seen_urls = set()
        for r in serper_results + rss_results:
            url = r.get("href", r.get("url", r.get("link", "")))
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

        # SOTA relevance gate: reject articles whose title+body doesn't
        # actually cover the query content words. Without this, RSS and Serper
        # feed trending noise (e.g. vnexpress trending articles for "giá dầu").
        all_results = _filter_by_relevance(query, all_results, threshold=0.5)

        if not all_results:
            return "Không tìm thấy tin tức liên quan."

        _cb_record_success(_CB_NAME)
        all_results = _augment_top_result_with_deep_fetch(all_results[:8], query)
        return _format_results(all_results, "NEWS_SEARCH")

    except ImportError:
        return "Lỗi: Chưa cài đặt duckduckgo-search. Chạy: pip install duckduckgo-search"

    except Exception as e:
        _cb_record_failure(_CB_NAME)
        logger.warning("[NEWS_SEARCH] Failed: %s", e)
        return f"Lỗi tìm kiếm tin tức: {e}"


# =============================================================================
# Sprint 102: Tool — Vietnamese legal search
# =============================================================================

# Sprint 204: Neutral description — guidance is in system prompt, not tool metadata
@tool(description=(
    "Tìm kiếm VĂN BẢN PHÁP LUẬT Việt Nam — luật, nghị định, thông tư, quy định, mức phạt, bộ luật. "
    "Nguồn: Thư viện Pháp luật, Cổng TTĐT Chính phủ, Luật Việt Nam, Công báo."
))
def tool_search_legal(query: str) -> str:
    """Search Vietnamese legal documents using site-restricted Serper.dev (Sprint 198)."""
    _CB_NAME = "search_legal"
    if _cb_is_open(_CB_NAME):
        logger.warning("[LEGAL_SEARCH] Circuit breaker OPEN — skipping search")
        return "Tìm kiếm pháp luật tạm thời không khả dụng. Vui lòng thử lại sau."

    try:
        # Sprint 198: Serper supports site: natively via Google
        from app.engine.tools.serper_web_search import is_serper_available, _serper_search

        if is_serper_available():
            site_filter = " OR ".join(f"site:{s}" for s in _LEGAL_SITES)
            restricted_query = f"({site_filter}) {query}"
            results = _serper_search(restricted_query, max_results=7, gl="vn", hl="vi")
            if results:
                _cb_record_success(_CB_NAME)
                return _format_results(results, "LEGAL_SEARCH")
            # Serper returned empty — try without site restriction
            results = _serper_search(query, max_results=7, gl="vn", hl="vi")
            if results:
                _cb_record_success(_CB_NAME)
                return _format_results(results, "LEGAL_SEARCH")

        # DuckDuckGo fallback
        import concurrent.futures

        future = _executor.submit(
            _search_site_restricted_sync, query, _LEGAL_SITES, 7
        )
        results = future.result(timeout=WEB_SEARCH_TIMEOUT)

        if not results:
            return "Không tìm thấy văn bản pháp luật liên quan."

        _cb_record_success(_CB_NAME)
        return _format_results(results, "LEGAL_SEARCH")

    except concurrent.futures.TimeoutError:
        _cb_record_failure(_CB_NAME)
        logger.warning("[LEGAL_SEARCH] Timeout for: %s", query[:50])
        return "Tìm kiếm pháp luật quá thời gian chờ. Vui lòng thử lại."

    except ImportError:
        return "Lỗi: Chưa cài đặt duckduckgo-search. Chạy: pip install duckduckgo-search"

    except Exception as e:
        _cb_record_failure(_CB_NAME)
        logger.warning("[LEGAL_SEARCH] Failed: %s", e)
        return f"Lỗi tìm kiếm pháp luật: {e}"


# =============================================================================
# Sprint 102: Tool — International maritime search
# =============================================================================

@tool(description=(
    "Tìm kiếm thông tin HÀNG HẢI quốc tế trên web. Dùng khi user hỏi về IMO, "
    "quy định hàng hải quốc tế, tin tức shipping, DNV, classification societies, "
    "hoặc thông tin từ Cục Hàng hải Việt Nam. "
    "Nguồn: IMO, Safety4Sea, Maritime Executive, VINAMARINE."
))
def tool_search_maritime(query: str) -> str:
    """Search international maritime information using site-restricted Serper.dev (Sprint 198)."""
    _CB_NAME = "search_maritime"
    if _cb_is_open(_CB_NAME):
        logger.warning("[MARITIME_SEARCH] Circuit breaker OPEN — skipping search")
        return "Tìm kiếm hàng hải tạm thời không khả dụng. Vui lòng thử lại sau."

    try:
        # Sprint 198: Serper supports site: natively via Google
        from app.engine.tools.serper_web_search import is_serper_available, _serper_search

        if is_serper_available():
            site_filter = " OR ".join(f"site:{s}" for s in _MARITIME_SITES)
            restricted_query = f"({site_filter}) {query}"
            results = _serper_search(restricted_query, max_results=7, gl="vn", hl="vi")
            if results:
                _cb_record_success(_CB_NAME)
                return _format_results(results, "MARITIME_SEARCH")
            # Serper returned empty — try without site restriction
            results = _serper_search(query, max_results=7, gl="vn", hl="vi")
            if results:
                _cb_record_success(_CB_NAME)
                return _format_results(results, "MARITIME_SEARCH")

        # DuckDuckGo fallback
        import concurrent.futures

        future = _executor.submit(
            _search_site_restricted_sync, query, _MARITIME_SITES, 7
        )
        results = future.result(timeout=WEB_SEARCH_TIMEOUT)

        if not results:
            return "Không tìm thấy thông tin hàng hải liên quan."

        _cb_record_success(_CB_NAME)
        return _format_results(results, "MARITIME_SEARCH")

    except concurrent.futures.TimeoutError:
        _cb_record_failure(_CB_NAME)
        logger.warning("[MARITIME_SEARCH] Timeout for: %s", query[:50])
        return "Tìm kiếm hàng hải quá thời gian chờ. Vui lòng thử lại."

    except ImportError:
        return "Lỗi: Chưa cài đặt duckduckgo-search. Chạy: pip install duckduckgo-search"

    except Exception as e:
        _cb_record_failure(_CB_NAME)
        logger.warning("[MARITIME_SEARCH] Failed: %s", e)
        return f"Lỗi tìm kiếm hàng hải: {e}"


# =============================================================================
# Registration
# =============================================================================

def init_web_search_tools() -> None:
    """Register web search tools with the global registry."""
    registry = get_tool_registry()

    for tool_fn, desc in [
        (tool_web_search, "Web search via Serper.dev (DuckDuckGo fallback)"),
        (tool_search_news, "Vietnamese news search (Serper News + RSS)"),
        (tool_search_legal, "Vietnamese legal document search (site-restricted Serper)"),
        (tool_search_maritime, "Maritime international search (site-restricted Serper)"),
    ]:
        registry.register(
            tool_fn,
            category=ToolCategory.UTILITY,
            access=ToolAccess.READ,
            description=desc,
        )

    logger.info("Web search tools registered: web_search, search_news, search_legal, search_maritime")
