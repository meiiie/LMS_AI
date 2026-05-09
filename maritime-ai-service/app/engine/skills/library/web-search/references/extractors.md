# Deep-Fetch Extractors — 4-Tier Chain

> Read this file when: investigating why a URL returned empty content,
> deciding whether to add a new extractor, or tuning timeouts.

## Pipeline order (tried in sequence; first success wins)

| # | Extractor | License | Strengths | Cost |
|---|-----------|---------|-----------|------|
| 0 | **Valkey cache** | OSS | Instant if hit | 0ms |
| 1 | **Crawl4AI** (Playwright) | MIT | LLM-ready markdown, no boilerplate | 8-15s cold, 3-5s warm |
| 2 | **Scrapling** (stealth) | BSD-3 | Bypasses Cloudflare/Turnstile/anti-bot | 5-12s |
| 3 | **Jina Reader** (cloud) | free reader API | Different fingerprint, handles paywalls | 3-8s |
| 4 | **httpx + BeautifulSoup** | OSS | Last resort, no JS execution | 1-3s |

All successful fetches write back to Valkey cache (TTL by URL category):
- News domains → 5 min
- Default → 1 hour
- Static docs (Wikipedia, IMO, gov.vn) → 24 hour

## When each tier wins

### Crawl4AI wins on
- Standard websites without aggressive anti-bot
- Sites with heavy JS that need rendering (Vue/React SPAs)
- Sites where you want clean markdown vs raw HTML

### Scrapling wins on
- Sites with Cloudflare Turnstile / interstitial challenges
- Heavily-protected e-commerce sites
- When Crawl4AI's Playwright fingerprint gets blocked

### Jina Reader wins on
- Paywalled news sites (Jina has special access agreements with some)
- Sites where local Playwright IP is blocked but Jina cloud IPs aren't
- When Crawl4AI + Scrapling both fail (Jina is the cloud safety net)

### httpx wins on
- Static HTML sites (gov.vn, Wikipedia, RSS)
- API endpoints returning HTML/text
- Last resort for everything else

## Common failure patterns

**Symptom**: Crawl4AI returns 200 but `markdown` is empty
- **Cause**: Site is SPA loaded entirely via fetch() after page load
- **Fix**: Increase `arun(...)` `wait_for` parameter, or skip to Scrapling

**Symptom**: Scrapling raises ImportError
- **Cause**: Playwright browser not installed for stealth fetcher
- **Fix**: `docker exec ... scrapling install` (downloads patched chromium)

**Symptom**: Jina returns 429
- **Cause**: Free tier rate limit (~20 RPM without API key)
- **Fix**: Skip to httpx tier; quota refreshes per-minute

**Symptom**: httpx returns 200 but content is empty
- **Cause**: Page entirely rendered client-side; no SSR
- **Fix**: Mark URL as "needs Playwright" — re-queue with Crawl4AI

## Diagnostic commands

```bash
# Test individual tier on a URL
docker exec -w /app -e PYTHONPATH=/app maritime-ai-service-app-1 python -c "
from app.engine.tools.web_fetch_tool import _try_crawl4ai, _try_scrapling, _try_jina, _try_httpx
url = 'https://vneconomy.vn'
print('crawl4ai:', len(_try_crawl4ai(url) or ''))
print('jina    :', len(_try_jina(url) or ''))
print('httpx   :', len(_try_httpx(url) or ''))
"

# Cache stats
docker exec wiii-valkey valkey-cli INFO stats | grep -E 'keyspace_(hits|misses)'
```

## Cache eviction policy

Valkey runs with default LRU + 256MB cap. Web fetch keys are:
- `wiii:web_fetch:v1:{sha256(url)[:32]}` — TTL per category
- `wiii:web_search:v1:ddg:{n}:{query_lower}` — 3min TTL

To clear cache (during development):
```bash
docker exec wiii-valkey valkey-cli --pattern 'wiii:web_*' DEL 0
```
