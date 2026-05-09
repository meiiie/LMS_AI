# Failure Modes — Diagnostic Reference

> Read this file when: a search returns nothing useful, latency spikes,
> or the answer is missing critical information the user knows exists.

## "I know X is in the news but Wiii didn't find it"

**Diagnosis flow:**

1. Was the query specific enough? Vague queries hit irrelevant sites.
2. Did Vietnamese press cover it yet? Bilingual merge fixes this — but
   only if `_translate_finance_query_en` recognized the topic.
3. Is the topic in our `_DEEP_QUERY_KEYWORDS` set? If not, news merge
   doesn't trigger. Add the keyword.
4. Did the LLM call only ONE tool? With NVIDIA DeepSeek this is common —
   the system prompt instructs parallel multi-tool, but the model
   sometimes ignores. Check logs: should see TWO `[WEB_SEARCH]` lines per
   round for finance queries.

**Mitigation:**
- Re-prompt user: "Anh có thông tin cụ thể nào về sự kiện này không?
  (tên người, địa điểm, ngày)" — gives a tighter query.
- Manually invoke `tool_fetch_url` on a known URL the user provides.

## Latency spike (>2 min for cold deep query)

**Top causes (in order of frequency):**

1. **NVIDIA NIM degraded** — provider-side throttle. Look for
   `[LLM_MODEL_FALLBACK] reason=timeout` in logs. Each failed round
   adds 60s+ before fallback.
2. **Crawl4AI cold start** — first Playwright launch in container
   takes 10-15s. Subsequent fetches reuse the browser ≈3s.
3. **Self-eval loop runaway** — if convergence guard misfires and LLM
   keeps adding tools, `max_rounds=2` caps but each round costs.
4. **Cache miss on every URL** — happens after force-recreate. Check
   `docker exec wiii-valkey valkey-cli DBSIZE`.

**Mitigation matrix:**

| Cause | Fix |
|-------|-----|
| NVIDIA degraded | Wait + retry; or set `LLM_PROVIDER=google` temporarily |
| Cold Playwright | Pre-warm: `docker exec ... python -c "from app.engine.tools.web_fetch_tool import _try_crawl4ai; _try_crawl4ai('https://example.com')"` |
| Self-eval runaway | Verify gate threshold (2500 chars) + `max_rounds=2` in `graph.py` |
| Cache miss | Run a few "warm-up" queries after fresh deploy |

## "Xin lỗi, mình chưa xử lý được" canned response

**This is the hard fallback.** Pipeline timed out completely or LLM
generation failed. Diagnostic:

```bash
docker logs maritime-ai-service-app-1 --since 5m | grep -E "ProviderUnavailable|generation failed|Pipeline end"
```

Look for:
- `[LLM_MODEL_FALLBACK] Same-provider fallback failed` → both flash + pro
  timed out → Google failover (if `enable_llm_failover=true`)
- `Error code: 429` → Google quota exceeded (free tier 20 RPD per model)
- `ProviderUnavailableError` → all providers exhausted

## Format leaks (DSML XML in answer)

NVIDIA DeepSeek occasionally emits tool calls in `<｜DSML｜tool_calls>...`
inside `content` instead of the structured `tool_calls` field. Wiii has
a parser in `messages_adapters.py:_parse_dsml_tool_calls` that:

1. Extracts the DSML block from content
2. Parses each `<｜DSML｜invoke>` into a `ToolCall` object
3. Strips the XML from the visible content

If you still see DSML in user-facing answers, either:
- The parser regex is incomplete (asymmetric tags? new variant?). Update
  `_parse_dsml_tool_calls` in `messages_adapters.py`.
- The DSML appeared during streaming (different code path). Check
  `app/engine/multi_agent/openai_stream_runtime.py`.

## "Không tìm thấy kết quả trên web"

Means all 4 search tiers returned empty. Rare but possible when:
- Query is in a language SearXNG engines don't index well
- All search engines have transient outage
- Query is too specific (zero matching pages)

User should rephrase. If persistent across rephrasings, check:
```bash
docker exec wiii-searxng curl -s "http://localhost:8080/search?q=test&format=json"
```
If SearXNG itself returns 0 results for "test", container is broken —
restart with `docker compose restart searxng`.

## Cache poisoning

If a stale article gets cached (e.g. URL changed but Valkey still has
old markdown), purge specifically:

```bash
# Compute key hash
URL="https://example.com/page"
HASH=$(echo -n "$URL" | sha256sum | head -c 32)
docker exec wiii-valkey valkey-cli DEL "wiii:web_fetch:v1:$HASH"
```

Or wipe all web caches:
```bash
docker exec wiii-valkey sh -c "valkey-cli --scan --pattern 'wiii:web_*' | xargs -r valkey-cli DEL"
```
