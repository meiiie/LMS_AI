"""
TikTok Research API Adapter — Native TikTok Shop search

Sprint 149: "Cắm & Chạy" — TikTok Research API v2

Uses Client Access Token (no user login needed!) for:
- Product search: POST /v2/research/tts/product/query/
- Shop search: (future enhancement)

Data quality far exceeds Serper site: filter:
- Exact prices, real product links, ratings, sold counts, seller info

Auth flow:
    POST https://open.tiktokapis.com/v2/oauth/token/
    grant_type=client_credentials&client_key=KEY&client_secret=SECRET
    → {"access_token": "clt.xxx", "expires_in": 7200}

Fallback: If native API fails or credentials missing → Serper site:tiktok.com/shop
"""

import hashlib
import logging
import threading
import time
from typing import List, Optional

from app.engine.search_platforms.base import (
    BackendType,
    PlatformConfig,
    ProductSearchResult,
    SearchPlatformAdapter,
)

logger = logging.getLogger(__name__)

# Token cache (in-memory, thread-safe). The cache key is a non-reversible
# fingerprint of the active credential pair so rotated credentials never reuse
# a previous provider token.
_token_cache: dict = {"cache_key": None, "access_token": None, "expires_at": 0.0}
_token_lock = threading.Lock()
_TOKEN_CACHE_NAMESPACE = "wiii.tiktok_research.token_cache.v1"


def _credential_cache_key(client_key: str, client_secret: str) -> str:
    digest = hashlib.sha256()
    digest.update(_TOKEN_CACHE_NAMESPACE.encode("utf-8"))
    digest.update(b"\0")
    digest.update(client_key.encode("utf-8"))
    digest.update(b"\0")
    digest.update(client_secret.encode("utf-8"))
    return digest.hexdigest()


def _get_access_token(client_key: str, client_secret: str) -> str:
    """Get or refresh TikTok Client Access Token (thread-safe)."""
    global _token_cache

    cache_key = _credential_cache_key(client_key, client_secret)

    # Sprint 153: Hold lock through entire refresh to prevent thundering herd
    with _token_lock:
        cached_token = _token_cache.get("access_token")
        expires_at = float(_token_cache.get("expires_at") or 0.0)
        if (
            _token_cache.get("cache_key") == cache_key
            and cached_token
            and time.time() < expires_at - 60
        ):
            return str(cached_token)

        import httpx
        resp = httpx.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        access_token = data.get("access_token")
        if not access_token:
            raise ValueError(f"TikTok token error: {data.get('message', 'no access_token')}")

        expires_in = data.get("expires_in", 7200)

        _token_cache = {
            "cache_key": cache_key,
            "access_token": access_token,
            "expires_at": time.time() + expires_in,
        }

        logger.debug("TikTok access token refreshed (expires in %ds)", expires_in)
        return access_token


class TikTokResearchAdapter(SearchPlatformAdapter):
    """
    TikTok Shop search via Research API v2 (native, free).

    Falls back to Serper site: filter when:
    - Credentials not configured
    - Native API returns error
    """

    def __init__(self, serper_fallback: Optional[SearchPlatformAdapter] = None):
        """
        Args:
            serper_fallback: Optional Serper site adapter for TikTok Shop fallback.
        """
        self._serper_fallback = serper_fallback

    def get_config(self) -> PlatformConfig:
        return PlatformConfig(
            id="tiktok_shop",
            display_name="TikTok Shop",
            backend=BackendType.NATIVE_API,
            fallback_backend=BackendType.SERPER_SITE,
            tool_description_vi=(
                "Search TikTok Shop Vietnam for products. "
                "Returns product listings with titles, exact prices, ratings, sold counts, and links.\n\n"
                "Args:\n"
                "    query: Product search query (e.g., \"dây điện 3x2.5mm\")\n"
                "    max_results: Maximum number of results (default 20)"
            ),
        )

    def validate_credentials(self) -> bool:
        from app.core.config import get_settings
        settings = get_settings()
        return bool(settings.tiktok_client_key and settings.tiktok_client_secret)

    def search_sync(self, query: str, max_results: int = 20, page: int = 1) -> List[ProductSearchResult]:
        from app.core.config import get_settings
        settings = get_settings()

        # Check native API availability
        if not settings.enable_tiktok_native_api or not self.validate_credentials():
            return self._fallback_search(query, max_results, page)

        try:
            return self._native_search(query, max_results, settings)
        except Exception as e:
            logger.warning("[TIKTOK_RESEARCH] Native API error, falling back to Serper: %s", e)
            return self._fallback_search(query, max_results, page)

    def _native_search(
        self, query: str, max_results: int, settings
    ) -> List[ProductSearchResult]:
        """Search via TikTok Research API v2."""
        import httpx

        token = _get_access_token(settings.tiktok_client_key, settings.tiktok_client_secret)
        timeout = settings.product_search_timeout

        resp = httpx.post(
            "https://open.tiktokapis.com/v2/research/tts/product/query/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "max_count": min(max_results, 50),
                "region_code": "VN",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        products = data.get("data", {}).get("products", [])
        results = []
        for item in products[:max_results]:
            # Price handling: TikTok returns price in cents or full value
            price_info = item.get("price", {})
            if isinstance(price_info, dict):
                price_str = price_info.get("formatted_price", "")
                price_value = price_info.get("price", 0)
            else:
                price_str = str(price_info) if price_info else ""
                price_value = None

            results.append(ProductSearchResult(
                platform="TikTok Shop",
                title=item.get("title", ""),
                price=price_str,
                extracted_price=float(price_value) if price_value else None,
                link=item.get("product_url", ""),
                seller=item.get("shop_name", ""),
                rating=item.get("rating"),
                sold_count=item.get("sold_count"),
                image=item.get("cover_image_url", ""),
            ))

        logger.info("[TIKTOK_RESEARCH] Native API: %d results for '%s'", len(results), query[:50])
        return results

    def _fallback_search(self, query: str, max_results: int, page: int = 1) -> List[ProductSearchResult]:
        """Fallback to Serper site: filter."""
        if self._serper_fallback:
            logger.debug("[TIKTOK_RESEARCH] Using Serper fallback for TikTok Shop")
            return self._serper_fallback.search_sync(query, max_results, page)
        raise ValueError("TikTok native API not available and no Serper fallback configured")
