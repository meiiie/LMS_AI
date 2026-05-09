"""Regression tests for Sprint 35c DIRECT source-backed template fallback.

This module is the deterministic graceful-degradation path Wiii uses when
the synthesis LLM call times out after a successful tool round (Perplexity
Pro Search 2026 + Anthropic Computer Use 2026 evidence-pool pattern).

Tests pin down:
- snippet/URL extraction from typical web_search/search_news outputs
- markdown citation contract (`[Title](url)` chips, source URLs preserved)
- empty-input safety: tool_call_events without usable data returns ""
- format-preserving output ready for the SSE answer field
"""

from __future__ import annotations

from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
    looks_like_search_placeholder_answer,
)


# ---------------------------------------------------------------------------
# Helpers — synthesise representative tool_call_events shapes
# ---------------------------------------------------------------------------


def _search_result(text: str, *, name: str = "tool_web_search", call_id: str = "c1") -> list[dict]:
    return [
        {"type": "call", "id": call_id, "name": name, "args": {"query": "x"}},
        {"type": "result", "id": call_id, "name": name, "result": text},
    ]


def _fetch_result(url: str, body: str, *, call_id: str = "f1") -> list[dict]:
    return [
        {"type": "call", "id": call_id, "name": "tool_fetch_url", "args": {"url": url}},
        {"type": "result", "id": call_id, "name": "tool_fetch_url", "result": body},
    ]


_SAMPLE_SEARCH = """
1. Iran fires missiles at US warship in Strait of Hormuz, US denies hit
URL: https://reuters.com/markets/oil-iran-2026-05-05
Reuters reports Iran's Revolutionary Guard claimed an attack on USS Eisenhower
near the Hormuz Strait. The Pentagon has denied any vessel was struck.

2. OPEC+ meets emergency session on Monday amid Iran tensions
URL: https://bloomberg.com/news/articles/opec-iran-emergency
Saudi Arabia and UAE call for an emergency OPEC+ meeting after the Iran
incident pushed Brent crude above $115 per barrel briefly.

3. Trump skeptical of Iran 14-point peace agreement
URL: https://cnbc.com/2026/05/04/trump-iran-deal
Former president skeptical following the maritime incident.
"""

_FORMATTED_SEARCH = """
**OpenAI enhances security for AI agent systems - Laodong.vn** (Tue, 10 Mar 2026 07:00:00 GMT) [google_news]
<a href="https://news.google.com/rss/articles/example" target="_blank">OpenAI enhances security for AI agent systems</a>
URL: https://news.google.com/rss/articles/example?oc=5

---

**Introducing GPT-5.5 - OpenAI**
Apr 23, 2026 · OpenAI is releasing GPT-5.5, its smartest and most intuitive model yet.

[Nội dung chi tiết từ https://openai.com/index/introducing-gpt-5-5/]
Title: Introducing GPT-5.5

URL Source: https://openai.com/index/introducing-gpt-5-5/

Markdown Content:
# Introducing GPT-5.5 | OpenAI
"""


# ---------------------------------------------------------------------------
# Output contract — citations, structure, length
# ---------------------------------------------------------------------------


def test_search_only_events_produce_citations() -> None:
    events = _search_result(_SAMPLE_SEARCH)
    out = build_search_template_fallback("tin tức thế giới hôm nay", events)
    assert out, "non-empty events should produce non-empty output"
    # Inline `[Title](url)` markdown chips per the SKILL Citations contract.
    assert "](https://reuters.com" in out
    assert "](https://bloomberg.com" in out
    assert "](https://cnbc.com" in out


def test_output_uses_vietnamese_voice() -> None:
    events = _search_result(_SAMPLE_SEARCH)
    out = build_search_template_fallback("tin tức hôm nay", events)
    # Wiii primary language — must address the user in Vietnamese, not English.
    assert "Mình" in out, f"output missing Vietnamese 'Mình': {out!r}"
    assert "kết quả" in out or "nguồn" in out


def test_fetch_url_summary_appears_above_source_list() -> None:
    """Fetched articles get their own summary section before the source list,
    matching the SKILL Step 4 3-part structure (lede → context → takeaway).
    """
    fetched_body = (
        "(via Crawl4AI) Reuters — World — May 5, 2026\n\n"
        "Iran's IRGC claimed responsibility for two anti-ship missile strikes "
        "on USS Eisenhower in the Strait of Hormuz. Brent crude futures spiked "
        "$4.20 to settle at $115.30/barrel."
    )
    events = (
        _search_result(_SAMPLE_SEARCH)
        + _fetch_result(
            "https://reuters.com/markets/oil-iran-2026-05-05",
            fetched_body,
            call_id="f1",
        )
    )
    out = build_search_template_fallback("giá dầu hôm nay", events)
    assert "$115" in out or "Brent" in out, "fetched body should surface in output"
    assert "reuters.com" in out


# ---------------------------------------------------------------------------
# Empty / failure handling
# ---------------------------------------------------------------------------


def test_empty_events_returns_empty_string() -> None:
    """Caller treats empty string as "no salvage available — fall through"
    so the canned greeting can engage instead of an unhelpful bullet list.
    """
    assert build_search_template_fallback("anything", []) == ""


def test_failed_tools_without_urls_returns_empty_string() -> None:
    events = _search_result("Tool unavailable")
    assert build_search_template_fallback("anything", events) == ""


def test_handles_arbitrary_url_without_structured_title() -> None:
    """A bare URL list (no title/snippet pairs) should still produce a
    minimum-viable citation so the user can verify the search ran.
    """
    raw = "https://example.com/news/article-2026 https://other.example.com/q?id=42"
    events = _search_result(raw)
    out = build_search_template_fallback("query", events)
    assert "https://example.com" in out
    assert "https://other.example.com" in out


def test_multiple_search_tools_dedup_by_url() -> None:
    """When ``tool_web_search`` and ``tool_search_news`` both return the
    same URL, the fallback should not list the same source twice.
    """
    events = (
        _search_result(_SAMPLE_SEARCH, call_id="c1")
        + _search_result(_SAMPLE_SEARCH, name="tool_search_news", call_id="c2")
    )
    out = build_search_template_fallback("dup test", events)
    occurrences = out.count("https://reuters.com/markets/oil-iran-2026-05-05")
    assert occurrences == 1, f"expected 1 occurrence, got {occurrences}"


def test_formatted_web_search_blocks_preserve_official_source() -> None:
    events = _search_result(_FORMATTED_SEARCH)
    out = build_search_template_fallback("OpenAI latest model announcement 2026", events)
    assert "Introducing GPT-5.5" in out
    assert "https://openai.com/index/introducing-gpt-5-5/" in out
    assert "OpenAI is releasing GPT-5.5" in out


def test_placeholder_answer_detection_for_search_salvage() -> None:
    assert looks_like_search_placeholder_answer(
        "Xin lỗi, mình chưa xử lý được yêu cầu này nha~ (˶˃ ᵕ ˂˶)"
    )
    assert not looks_like_search_placeholder_answer(
        "Mình đã tìm được 2 nguồn liên quan và tổng hợp nhanh bên dưới."
    )


def test_force_skill_prefix_removed_from_display_query() -> None:
    events = _search_result(_FORMATTED_SEARCH)
    out = build_search_template_fallback(
        "@web-search OpenAI latest model announcement 2026. Trả lời 2 ý ngắn và nêu nguồn.",
        events,
    )
    assert "**OpenAI latest model announcement 2026**" in out
    assert "@web-search" not in out
    assert "Trả lời 2 ý" not in out


def test_fetch_summary_skips_navigation_and_keeps_endpoint_evidence() -> None:
    events = _fetch_result(
        "https://developers.openai.com/api/reference/responses",
        """
        # https://developers.openai.com/api/reference/responses
        Skip to content
        No results
        Models
        API
        Pricing
        Create a model response
        POST /v1/responses
        Creates a model response. Provide text or image inputs to generate text or JSON outputs.
        """,
    )

    out = build_search_template_fallback(
        "OpenAI Responses API hiện tại có endpoint nào?",
        events,
    )

    assert "POST /v1/responses" in out
    assert "Skip to content" not in out
    assert "No results" not in out


def test_openai_responses_search_only_gives_endpoint_answer_before_sources() -> None:
    events = _search_result(
        """
        **Responses Overview | OpenAI API Reference**
        OpenAI's most advanced interface for generating model responses.
        URL: https://developers.openai.com/api/reference/responses/overview

        ---

        **Migrate to the Responses API | OpenAI API**
        Start by updating your generation endpoints from post /v1/chat/completions to post /v1/responses.
        URL: https://platform.openai.com/docs/guides/migrate-to-responses
        """
    )

    out = build_search_template_fallback(
        "Tìm trên web giúp mình: OpenAI Responses API hiện tại có endpoint nào?",
        events,
    )

    assert "**Kết luận nhanh từ nguồn OpenAI:**" in out
    assert "`POST https://api.openai.com/v1/responses`" in out
    assert "`model`" in out
    assert "`input`" in out
    assert "`GET https://api.openai.com/v1/responses/{response_id}`" in out
    assert out.index("`POST https://api.openai.com/v1/responses`") < out.index("**Các nguồn liên quan:**")


def test_official_openai_request_filters_third_party_sources() -> None:
    events = _search_result(
        """
        **Responses Overview | OpenAI API Reference**
        OpenAI's most advanced interface for generating model responses.
        URL: https://developers.openai.com/api/reference/responses/overview

        ---

        **Create a model response | OpenAI API Reference**
        Creates a model response.
        URL: https://developers.openai.com/api/reference/resources/responses/methods/create

        ---

        **OpenAI Responses API: Documentation and Examples**
        Third-party guide.
        URL: https://chatai.guide/api/responses-api/

        ---

        **Using OpenAI Responses API: Web Search, RAG & More - YouTube**
        Tutorial video.
        URL: https://www.youtube.com/watch?v=bKiUnvrQdSk
        """
    )

    out = build_search_template_fallback(
        "Tìm trên web nguồn chính thức: OpenAI Responses API endpoint hiện nay là gì?",
        events,
    )

    assert "**Nguồn chính thức:**" in out
    assert "developers.openai.com/api/reference/responses/overview" in out
    assert "developers.openai.com/api/reference/resources/responses/methods/create" in out
    assert "chatai.guide" not in out
    assert "youtube.com" not in out


def test_openai_responses_endpoint_uses_api_reference_when_search_returns_irrelevant_official_blogs() -> None:
    events = _search_result(
        """
        **Introducing Advanced Account Security | OpenAI**
        Account recovery details.
        URL: https://openai.com/index/advanced-account-security/

        ---

        **New tools for building agents | OpenAI**
        The Responses API is our new API primitive for leveraging OpenAI's built-in tools.
        URL: https://openai.com/index/new-tools-for-building-agents/
        """
    )

    out = build_search_template_fallback(
        "Tìm web từ nguồn chính thức OpenAI: Responses API endpoint hiện nay để tạo response là gì?",
        events,
    )

    assert "`POST https://api.openai.com/v1/responses`" in out
    assert "platform.openai.com/docs/api-reference/responses" in out
    assert "advanced-account-security" not in out
    assert "new-tools-for-building-agents" not in out


def test_forced_web_search_keeps_search_tool_over_visual_drift() -> None:
    from app.engine.multi_agent.direct_intent import _needs_web_search
    from app.engine.multi_agent.tool_collection import _collect_direct_tools

    query = (
        "@web-search Research UI-TARS Desktop pipeline and summarize source-backed "
        "lessons for Wiii planning, validator, UX steps, and prompt discipline."
    )
    assert _needs_web_search(query) is True

    tools, force_tools = _collect_direct_tools(
        query,
        "teacher",
        state={
            "force_skills": ["web-search"],
            "context": {"force_skills": ["web-search"]},
            "routing_metadata": {"intent": "web_search"},
        },
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert "tool_web_search" in names
    assert "tool_generate_visual" not in names
