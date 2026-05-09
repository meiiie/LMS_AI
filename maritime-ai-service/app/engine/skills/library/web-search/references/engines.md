# Search Engines — Index Comparison

> Read this file when: debugging "no results" failures, optimizing engine
> ordering, or evaluating whether to add a new engine.

## Tier 1: SearXNG (default primary)

**Self-hosted at `http://searxng:8080`. AGPL-3.0. Aggregates 70+ engines.**

Active engines (default config):
- Google (web search)
- Startpage (Google proxy)
- DuckDuckGo (Bing-based)
- Qwant (European)
- Brave Search (free public mirror)
- Mojeek (independent index)

Strengths:
- Free forever, no API key, no rate limit (we are sole client)
- Multiple indexes = resilience to one engine going down
- Supports `language=vi`/`language=en` per query
- Supports `time_range=day|week|month|year` for fresh content

Weaknesses:
- Aggregation latency: ~5-8s per query (vs Brave API ~2s)
- Some engines randomly fail (Google bot detection) → SearXNG silently drops them
- Container needs ~512MB RAM steady

When to bypass: if SearXNG container down or query times out >10s.

## Tier 2: Brave Search API (optional)

**Free 2k queries/month with API key registration. Set `BRAVE_API_KEY`.**

Strengths:
- Independent index (not Google) → news coverage different from SearXNG
- Faster (~2s typical)
- Better Vietnamese coverage than DDG

Weaknesses:
- Requires API key signup
- Quota limit (2k/mo free) → not infinite

When active: Wiii uses Brave AS PRIMARY when `BRAVE_API_KEY` is set; falls
back to SearXNG when quota exceeded.

## Tier 3: DuckDuckGo (last resort)

**No key, but flaky. Random empty-result rate ~10-20%.**

Used only when SearXNG + Brave both unavailable. We retry once on empty
to absorb DDG's flakiness.

## News Engines (separate path)

Time-sensitive queries trigger `_merge_news_into_search` which queries:

1. **Google News RSS** (Vietnamese): `news.google.com/rss/search?hl=vi&gl=VN`
2. **Google News RSS** (English): `news.google.com/rss/search?hl=en&gl=US`
   — only for finance queries (translated via `_translate_finance_query_en`)
3. **SearXNG news category**: `categories=news&time_range=week`
4. **DDG.news**: last resort

Bilingual interleaving: 1 vi + 1 en + 1 vi + 1 en pattern at top of
search results. Critical for catching breaking events Vietnamese press hasn't
covered yet (e.g. Iran/Hormuz incidents).

## Diagnostic commands

```bash
# Test SearXNG inside container
docker exec maritime-ai-service-app-1 curl -s "http://searxng:8080/search?q=test&format=json" | jq '.number_of_results'

# Test Google News RSS
docker exec maritime-ai-service-app-1 python -c "
from app.engine.tools.web_search_tools import _google_news_rss_sync
print(len(_google_news_rss_sync('giá dầu', max_results=5)))
"

# Cache hit-rate check
docker exec wiii-valkey valkey-cli KEYS 'wiii:web_search:v1:*' | wc -l
```
