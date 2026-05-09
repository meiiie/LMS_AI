"""URL → markdown cache backed by Valkey/Redis.

Pattern: Cursor / Windsurf 2026 — aggressive 1h TTL cache cho mọi URL extraction.
Prevents re-fetching same page across queries (e.g. petrolimex.com.vn for every
"giá xăng" question over the course of a day).

Key design:
- SHA-256(url) hash → 32-char prefix → fits Valkey key length budget.
- Different TTL per URL type:
    * News domains: 5 min (volatile)
    * Static / docs: 1 hour (default)
- Best-effort: cache failures NEVER break the fetch. Pipeline degrades gracefully
  to re-fetch on every miss — just slower.
- Sync Redis client (valkey-py compat) — simpler than async for the dispatch
  patterns we already use (ThreadPoolExecutor for tool execution).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_PREFIX = "wiii:web_fetch:v1:"
DEFAULT_TTL_SECONDS = 3600           # 1 hour
NEWS_TTL_SECONDS = 300               # 5 min for time-sensitive
LONG_TTL_SECONDS = 86_400            # 24 h for static docs

_NEWS_DOMAINS = (
    "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "dantri.com.vn",
    "vietnamnet.vn", "tienphong.vn", "laodong.vn",
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "cnbc.com",
)

_STATIC_DOMAINS = (
    "wikipedia.org", "imo.org", "ssa.gov", "vanban.chinhphu.vn",
    "thuvienphapluat.vn", "github.com", "docs.python.org",
)


_client = None
_init_attempted = False


def _get_client():
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True
    try:
        import redis

        from app.core.config import settings

        url = (
            getattr(settings, "valkey_url", None)
            or "redis://valkey:6379/0"
        )
        client = redis.Redis.from_url(
            url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            decode_responses=False,
        )
        client.ping()
        _client = client
        logger.info("[WEB_FETCH_CACHE] Connected to %s", url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WEB_FETCH_CACHE] Valkey unavailable, cache disabled: %s", exc)
        _client = None
    return _client


def _key(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()
    return f"{CACHE_PREFIX}{digest[:32]}"


def _ttl_for(url: str) -> int:
    lower = url.lower()
    for domain in _NEWS_DOMAINS:
        if domain in lower:
            return NEWS_TTL_SECONDS
    for domain in _STATIC_DOMAINS:
        if domain in lower:
            return LONG_TTL_SECONDS
    return DEFAULT_TTL_SECONDS


def get_cached(url: str) -> Optional[str]:
    """Return cached markdown for URL, or None on miss/error."""
    if not url:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(_key(url))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[WEB_FETCH_CACHE] get failed for %s: %s", url[:60], exc)
        return None


def set_cached(url: str, content: str) -> None:
    """Best-effort cache set. Silent on failure."""
    if not url or not content:
        return
    client = _get_client()
    if client is None:
        return
    try:
        ttl = _ttl_for(url)
        client.setex(_key(url), ttl, content)
        logger.debug(
            "[WEB_FETCH_CACHE] stored %d chars (ttl=%ds) for %s",
            len(content), ttl, url[:60],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[WEB_FETCH_CACHE] set failed for %s: %s", url[:60], exc)
