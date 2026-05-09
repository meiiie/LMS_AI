---
name: web-search
description: |
  Search the web for current real-time information using Wiii's multi-engine
  open-source pipeline (SearXNG aggregating Google/Bing/Brave + Google News
  bilingual VI/EN + Crawl4AI/Scrapling deep-fetch). USE THIS SKILL WHENEVER
  the user asks about real-time data, today's events, current prices, market
  movements, breaking news, weather, geopolitical situations, OR anything
  requiring information beyond knowledge cutoff. TRIGGER for queries containing
  'hôm nay', 'today', 'mới nhất', 'latest', 'breaking', 'giá', 'price', 'tin',
  'news', specific dates after 2024, or references to current world events —
  even if the user does not explicitly ask to "search the web". For finance/
  market queries (oil/gold/stocks/crypto/forex), ALWAYS launch a parallel
  geopolitical context search (Iran, OPEC+, Fed, Hormuz, war) — single-query
  searches reliably miss the most important breaking news that drives the price.
---

# Web Search & Deep Fetch

This skill orchestrates Wiii's open-source web-research pipeline. The pipeline
itself (SearXNG + Crawl4AI + Scrapling + Jina + Valkey cache + bilingual news
merge) is implemented in `app/engine/tools/web_search_tools.py` and
`app/engine/tools/web_fetch_tool.py` — you only need to know the **invocation
patterns** and **convergence checks** described below.

## When to use

Trigger this skill for:

1. **Real-time information** — prices, weather, news, sports scores, traffic.
2. **Current events** — anything happening "today" / "this week" / "right now".
3. **Market analysis** — oil, gold, currencies, crypto, equities — including
   the geopolitical context that's moving them.
4. **External knowledge** — comparisons, reviews, "best of" lists,
   technology releases, product launches.
5. **Verification** — when the user makes a factual claim about current world
   state that contradicts your training knowledge.

Do **NOT** use for:
- Domain knowledge already in Wiii (COLREGs, SOLAS, MARPOL, Vietnamese
  traffic law) → use `tool_rag_knowledge` instead.
- User-specific information (their name, preferences) → use memory tools.
- Pure computation (math, dates) → use `tool_calculator` /
  `tool_current_datetime`.

## Three tools available

```
tool_web_search(query: str) -> str
    SearXNG → Brave (if key) → DDG. Auto-merges Google News VI + EN.
    Auto-augments top-3 URLs via parallel deep-fetch when query is "deep".
    Cached in Valkey (3-min query / 1-hour URL).

tool_search_news(query: str) -> str
    News-specific endpoints (DDG.news + RSS feeds for VN press).

tool_fetch_url(url: str) -> str
    4-tier extractor: Crawl4AI (Playwright) → Scrapling (Cloudflare bypass)
    → Jina Reader → httpx. Returns ≤3500 chars of clean markdown. Cached.
```

## Workflow (imperative — follow this order)

### Step 1 — Compose 2 queries in parallel for finance/news

For any finance/market/breaking-news query, in your **first round** issue
TWO tool calls in parallel:

- **Query A — primary topic**: contains the asset and time
  - Example: `tool_web_search("giá dầu Brent WTI hôm nay 4/5/2026")`
- **Query B — geopolitical/macro context**: targets news that moves the asset
  - Example: `tool_search_news("Iran Mỹ Hormuz tin nóng OPEC+ hôm nay")`

For non-finance queries, a single `tool_web_search` is usually sufficient.

### Step 2 — Convergence check after round 0

After tools return, before answering, verify:

| Check | Pass criteria |
|-------|---------------|
| **Numbers**  | At least 2-3 specific figures (price, %, date) |
| **Context** | A sentence about WHY the price is moving (event, sentiment, technical) |
| **Recency** | Sources or content reference the actual day, not stale archives |

If ALL three pass → proceed to Step 4 (synthesize).
If ANY fail → Step 3 (escalate).

### Step 3 — Escalate when convergence fails

Pick the most promising URL from search results and call `tool_fetch_url(url)`
to read the full article. Choose URL by these heuristics:

1. Wire services (reuters.com, bloomberg.com, cnbc.com) > aggregators
2. Vietnamese tier-1 (vnexpress.net, vneconomy.vn) > tabloid
3. Date-stamped slugs (`/2026/05/04/...`) > undated home pages

Do NOT call more than 2 deep fetches per turn. NVIDIA NIM round latency
compounds — beyond 2 fetches the user waits >3 minutes.

### Step 4 — Synthesize with required structure

Output must follow this 3-part structure for finance/news queries:

```markdown
[Number-led lede with the headline figure]
**Brent**: $110.01/thùng (+0.96%)
**WTI**: $102.11/thùng

[Context paragraph — 2-3 sentences explaining WHAT moved the market]
Iran tuyên bố bắn 2 tên lửa vào tàu chiến Mỹ tại Hormuz — Mỹ phủ nhận.
CENTCOM khởi động "Project Freedom" với 15.000 quân + 100 aircraft hộ tống
tàu thương mại qua eo biển. Tháng 3 Brent từng vượt 119 USD do tấn công
hạ tầng dầu Saudi Arabia.

[Takeaway — 1-2 sentences with what to watch]
Vùng cân bằng tạm thời 105-115 USD. Theo dõi phản ứng OPEC+ và động thái
quân sự tại Hormuz trong các phiên tiếp theo.
```

For casual/conversational queries, ignore this structure.

## Citations (Anthropic / Perplexity 2026 pattern)

When mentioning a specific fact from a search result, **cite inline with a
markdown link** to the source URL. Frontend renders these as clickable
chips with favicon (Perplexity-style).

✅ Correct:
```
Theo [Reuters](https://reuters.com/markets/oil-2026), Brent đạt $115/thùng...
[CNBC](https://cnbc.com/2026/05/04/oil-iran) đưa tin về Project Freedom...
```

❌ Wrong (no citation):
```
Theo Reuters, Brent đạt $115/thùng... ← không có link, không thể verify
```

❌ Wrong (footnote-style only):
```
Brent $115/thùng [1]
[1]: reuters.com   ← LLM thường tạo nhầm số tham chiếu
```

**Rule**: cite at LEAST 1 link per fact paragraph. URLs come from `URL: ...`
lines in search result + the `(via Crawl4AI/Jina)` headers in fetch_url
output.

## Number formatting (CRITICAL)

Wiii has a sanitize regex that PRESERVES correct numeric formats. Write:

| ✅ Correct | ❌ Wrong |
|-----------|---------|
| `110.01 USD` | `110, 01 USD` |
| `13:18 GMT` | `13: 18 GMT` |
| `1.480 đồng/lít` | `1. 480 đồng/lít` |
| `0.96%` | `0, 96 %` |

## Anti-patterns — common mistakes to avoid

1. **Single-query searches for finance**. NEVER search just "giá dầu hôm nay"
   alone. ALWAYS pair with a geopolitical query. Vietnamese press lags
   English wire services on breaking events by hours-to-days; bilingual
   merge fixes this.

2. **Repeating near-identical queries**. After round 0, do NOT re-search
   with rephrasings of the same intent. Either fetch a URL or synthesize.

3. **Bibliographies of search results**. Do NOT dump all URLs into the
   answer. Cite at most 2-3 sources inline ("theo CNBC", "theo VnExpress")
   when mentioning specific facts.

4. **Hallucinating numbers**. If the search returned vague snippets without
   specific figures, say so explicitly: "Mình tra được thấy giá quanh vùng
   ~110 USD nhưng chưa có cập nhật real-time". Do NOT invent numbers to
   fill the structure.

5. **Treating no-result as final**. If `tool_web_search` returns empty,
   try `tool_search_news` or rephrase ONCE before giving up. The pipeline
   has 4 search engines; transient failures of one don't mean no data.

## Quality bar

- **Latency target**: <60s p95 (cold), <15s p95 (warm cache).
- **Number accuracy**: Exact match to source — no rounding without saying so.
- **Geopolitical coverage**: For finance queries, mention at least ONE
  current driver from {OPEC+, Fed, Iran, Trung Đông, Trung Quốc cầu, Trump
  tariff, AI demand, supply chain} when search results contain it.
- **Format**: Numbers preserved (110.01 not 110, 01); 3-part structure
  for analytical queries.

## Source-backed graceful fallback (Sprint 35c)

When the synthesis LLM call cannot complete after a successful tool round
(NVIDIA NIM timeout, DeepSeek connection error), Wiii engages a
deterministic fallback that **builds a citation-bearing answer directly
from `tool_call_events`** instead of returning a canned greeting. This is
the Perplexity Pro Search 2026 + Anthropic Computer Use 2026 evidence-pool
pattern — the search infrastructure already ran, so its output is shaped
into a Markdown response and shipped to the user.

### When the fallback engages

The fallback path is triggered at three points inside
`direct_node_runtime.py`:

| Trigger | Reason label (Prometheus) |
|---------|---------------------------|
| LLM returned empty body but `tool_call_events` has results | `empty_body` |
| Round-0 LLM timeout with empty `tool_call_events` (LLM-free emergency search via `tool_web_search`) | `emergency_search` |
| LLM raised exception with `tool_call_events` already populated | `exception_with_tools` |

Each engagement increments
`wiii.direct.template_fallback.engaged{trigger}` so operators can spot
provider-health regressions in Grafana.

### What the fallback delivers

`build_search_template_fallback(query, tool_call_events)` is a pure
function (no LLM, no async). It extracts (title, URL, snippet) tuples
from `tool_web_search` / `tool_search_news` results, summarizes any
`tool_fetch_url` content, and ships a Markdown response that obeys this
contract:

- **Inline `[Title](url)` citations** — same chip pattern Step 4 prescribes.
- **Vietnamese voice** — leads with "Mình đã tra cứu / tìm được…".
- **3-part structure when fetched data is present** — fetched-article
  summary first, then "Các nguồn liên quan" list, then the Vietnamese
  honesty footer ("AI synthesizer tạm chậm — mình tổng hợp trực tiếp…").
- **Degrade gracefully** — empty `tool_call_events` returns `""` so the
  caller's outer canned-greeting path engages instead of an unhelpful
  bullet list.

The user gets value from every search the runtime executed even when the
LLM is unavailable.

### Anti-pattern

Do **not** teach the model to imitate this fallback voice in normal
synthesis. The model's responsibility is to weave a true narrative answer
with inline citations; the template fallback is purely a deterministic
safety net for LLM-down conditions.

### Pattern reference

- `app/engine/multi_agent/direct_search_synthesis_fallback.py` — pure
  function module
- `tests/unit/test_direct_search_synthesis_fallback.py` — 7 regression
  tests including citation contract, Vietnamese voice, dedup, graceful
  empty handling
- Anthropic Computer Use 2026 evidence-pool retention + Perplexity Pro
  Search 2026 source-backed best-effort

## Reference files

For deeper background on the pipeline internals (when debugging or optimizing):
- `references/engines.md` — which search engines, what they index, fallback chain
- `references/extractors.md` — 4-tier deep-fetch chain, when each tier wins
- `references/failure_modes.md` — known failures + handlers
