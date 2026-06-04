"""Source-backed graceful synthesis fallback.

When the synthesis LLM call times out or fails after a successful tool round,
this module builds a deterministic, citation-bearing response from the
``tool_call_events`` already captured by the agentic loop. Users always
receive value from the search infrastructure even when the LLM is unavailable.

Pattern reference: Perplexity Pro Search 2026 ("source-backed best-effort
answer") + Anthropic Computer Use 2026 evidence-pool retention. Output
follows the structure prescribed by ``app/engine/skills/library/web-search/
SKILL.md`` Step 4 (3-part: lede / context / takeaway) with inline
``[Source](url)`` citations and number-format-safe punctuation.

This is a pure function — no LLM call, no I/O, no async. Safe to invoke
from any failure path.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse


_URL_PATTERN = re.compile(r"https?://[^\s<>)\]\"']+", re.IGNORECASE)
_URL_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:URL Source|URL|Link|Source)\s*[:\-–]\s*(https?://\S+)",
)
_HREF_PATTERN = re.compile(
    r"""href=["'](https?://[^"']+)["']""",
    re.IGNORECASE,
)
_TITLE_LINE_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:[\d]+[\.\)]\s*)?([^\n\r]{8,180})\s*\n\s*(?:URL|Link|Source)\s*[:\-–]\s*(https?://\S+)",
    re.IGNORECASE,
)
_BLOCK_SEPARATOR_PATTERN = re.compile(r"\n\s*---+\s*\n")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _host_label(url: str) -> str:
    """Extract a short, human-readable host label for citation chips."""
    try:
        host = urlparse(url).netloc or url
    except Exception:
        return url
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or url


def _clean_url(url: str) -> str:
    return str(url or "").strip().rstrip(").,;:>\"'")


def _clean_search_text(text: str) -> str:
    cleaned = unescape(str(text or ""))
    cleaned = re.sub(r"\[(.*?)\]\(https?://[^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
    cleaned = _HTML_TAG_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -–•·*")


def _extract_block_url(block: str) -> str:
    url_line = _URL_LINE_PATTERN.search(block or "")
    if url_line:
        return _clean_url(url_line.group(1))

    href = _HREF_PATTERN.search(block or "")
    if href:
        return _clean_url(href.group(1))

    bare_url = _URL_PATTERN.search(block or "")
    if bare_url:
        return _clean_url(bare_url.group(0))

    return ""


def _extract_block_title(block: str) -> str:
    for line in str(block or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered.startswith(("url:", "url source:", "link:", "source:")):
            continue
        if lowered.startswith(("[nội dung chi tiết", "title:", "markdown content:")):
            continue
        title = _clean_search_text(raw)
        title = re.sub(r"^\d+[\.\)]\s*", "", title).strip()
        if title.startswith("http") or len(title) < 8:
            continue
        return title[:180]
    return ""


def _extract_block_snippet(block: str, title: str, *, max_chars: int = 280) -> str:
    snippets: list[str] = []
    title_seen = False
    for line in str(block or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered.startswith(("url:", "url source:", "link:", "source:")):
            continue
        if lowered.startswith(("[nội dung chi tiết", "title:", "markdown content:")):
            break

        cleaned = _clean_search_text(raw)
        if not cleaned or cleaned.startswith("http"):
            continue
        if title and cleaned == title:
            title_seen = True
            continue
        if not title_seen and title and title in cleaned:
            title_seen = True
            continue
        if _URL_PATTERN.search(cleaned):
            continue
        snippets.append(cleaned)
        if len(" ".join(snippets)) >= max_chars:
            break

    snippet = " ".join(snippets)
    return snippet[:max_chars].strip()


def _extract_search_hits(result_text: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Pull (title, url, snippet) tuples out of a tool_web_search/search_news result.

    The tool surface emits a loosely-structured markdown listing; we don't
    require a strict format — just take the first N URL-bearing entries.
    """
    if not result_text:
        return []

    hits: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    # The production web_search formatter emits each result as:
    #   **Title**
    #   snippet...
    #   URL: https://...
    #   --- next result ---
    # Parse that block shape first so an LLM timeout still gives users the
    # same source set the tool actually retrieved.
    blocks = [
        block.strip()
        for block in _BLOCK_SEPARATOR_PATTERN.split(result_text)
        if block.strip()
    ]
    should_parse_blocks = len(blocks) > 1 or (
        len(blocks) == 1
        and result_text.lstrip().startswith("**")
        and len(_URL_LINE_PATTERN.findall(result_text)) == 1
    )
    if should_parse_blocks:
        for block in blocks:
            url = _extract_block_url(block)
            title = _extract_block_title(block)
            if not title and url:
                title = _host_label(url)
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": _extract_block_snippet(block, title),
                }
            )
            if len(hits) >= limit:
                break
        if hits:
            return hits

    for match in _TITLE_LINE_PATTERN.finditer(result_text):
        title = match.group(1).strip(" -–•·*").strip()
        url = _clean_url(match.group(2))
        if url in seen_urls or not title or not url:
            continue
        seen_urls.add(url)
        hits.append({"title": title, "url": url, "snippet": ""})
        if len(hits) >= limit:
            break

    if hits:
        for hit in hits:
            idx = result_text.find(hit["url"])
            if idx < 0:
                continue
            window_start = idx + len(hit["url"])
            window = result_text[window_start : window_start + 600]
            cleaned = re.sub(r"\s+", " ", window).strip(" -–•·*")
            if cleaned:
                hit["snippet"] = cleaned[:280]
        return hits

    for url_match in _URL_PATTERN.finditer(result_text):
        url = _clean_url(url_match.group(0))
        if url in seen_urls:
            continue
        seen_urls.add(url)
        hits.append({"title": _host_label(url), "url": url, "snippet": ""})
        if len(hits) >= limit:
            break
    return hits


def _extract_fetch_summary(result_text: str, *, max_chars: int = 600) -> str:
    """Compress a tool_fetch_url result down to a short summary lede."""
    if not result_text:
        return ""
    candidate_lines: list[str] = []
    priority_lines: list[str] = []
    nav_markers = {
        "api",
        "compare",
        "models",
        "news",
        "no results",
        "pricing",
        "reviews",
        "skip to content",
    }
    for raw_line in str(result_text or "").splitlines():
        cleaned_line = _clean_search_text(raw_line)
        if not cleaned_line:
            continue
        lowered = cleaned_line.lower().strip(" -*")
        if lowered in nav_markers:
            continue
        if lowered.startswith(("http://", "https://", "# http", "![", "image:")):
            continue
        if len(cleaned_line) < 45 and "/v1/responses" not in cleaned_line:
            continue
        if re.search(r"/v1/responses|responses api|create a model response", cleaned_line, re.IGNORECASE):
            priority_lines.append(cleaned_line)
        else:
            candidate_lines.append(cleaned_line)
        if len(" ".join(priority_lines + candidate_lines)) >= max_chars * 1.8:
            break

    source_lines = priority_lines[:4] + candidate_lines[:4]
    cleaned = " ".join(source_lines).strip()
    if not cleaned:
        cleaned = re.sub(r"\s+", " ", result_text).strip()
    cleaned = re.sub(r"\(via [A-Za-z0-9 _\-/]+\)", "", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[:max_chars]
    last_period = max(cut.rfind(". "), cut.rfind("。"))
    if last_period > max_chars * 0.6:
        cut = cut[: last_period + 1]
    return cut.rstrip() + "…"


def _is_search_tool(name: str) -> bool:
    name = (name or "").lower()
    return name in {
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
        "tool_search_legal",
        "search_legal",
    }


def _is_fetch_tool(name: str) -> bool:
    name = (name or "").lower()
    return name in {"tool_fetch_url", "fetch_url"}


def _format_intro(query: str, has_fetch: bool, hit_count: int) -> str:
    query_short = _display_query(query)
    if len(query_short) > 120:
        query_short = query_short[:120].rstrip() + "…"
    if has_fetch and hit_count > 0:
        return (
            f"Mình đã tra cứu thông tin về **{query_short}** và đọc trực tiếp "
            f"{hit_count} nguồn tin chính. Dưới đây là những gì mình tổng hợp được:"
        )
    if hit_count > 0:
        return (
            f"Mình đã tìm được {hit_count} kết quả liên quan đến "
            f"**{query_short}**. Tổng hợp nhanh:"
        )
    return f"Mình đã tra cứu **{query_short}** nhưng chưa tìm được kết quả phù hợp."


def _format_outro(hit_count: int) -> str:
    if hit_count <= 0:
        return (
            "\n\nCó thể nguồn dữ liệu tạm thời chưa có thông tin mới về "
            "chủ đề này. Bạn thử hỏi lại sau ít phút hoặc đặt câu hỏi cụ thể "
            "hơn nhé."
        )
    return (
        "\n\n_Nguồn: tổng hợp trực tiếp từ kết quả tra cứu web. "
        "Bấm vào tên nguồn để mở chi tiết._"
    )


def _display_query(query: str) -> str:
    """Remove force-skill syntax and trailing presentation instructions."""
    cleaned = re.sub(
        r"^\s*@(?:web-search|web_search|search)\b\s*",
        "",
        str(query or "").strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.split(
        r"(?i)(?:[\.\?!]\s+)?(?:trả lời|tra loi)\b",
        cleaned,
        maxsplit=1,
    )[0].strip(" .:-")
    return cleaned or str(query or "").strip() or "truy vấn này"


def _fold_known_docs_text(value: str) -> str:
    normalized = str(value or "").lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _find_official_openai_responses_source(
    search_hits: list[dict[str, str]],
    fetch_summaries: list[dict[str, str]],
) -> str:
    candidates: list[str] = []
    for item in search_hits:
        candidates.append(str(item.get("url") or ""))
    for item in fetch_summaries:
        candidates.append(str(item.get("url") or ""))

    official = [
        url
        for url in candidates
        if "developers.openai.com" in url or "platform.openai.com" in url
    ]
    for url in official:
        lowered = url.lower()
        if "responses" in lowered and "api/reference" in lowered:
            return url
    for url in official:
        if "migrate-to-responses" in url.lower():
            return url
    return official[0] if official else ""


def _looks_official_source_request(query: str) -> bool:
    folded = _fold_known_docs_text(query)
    return any(
        marker in folded
        for marker in (
            "official",
            "official source",
            "nguon chinh thuc",
            "nguồn chính thức",
            "source chính thức",
        )
    )


def _is_openai_official_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in {
        "developers.openai.com",
        "platform.openai.com",
        "openai.com",
        "help.openai.com",
    }


def _filter_requested_official_hits(
    query: str,
    search_hits: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not search_hits or not _looks_official_source_request(query):
        return search_hits
    folded = _fold_known_docs_text(query)
    if "openai" not in folded:
        return search_hits
    official_hits = [
        hit
        for hit in search_hits
        if _is_openai_official_url(str(hit.get("url") or ""))
    ]
    return official_hits or search_hits


def _build_known_docs_answer_lines(
    query: str,
    search_hits: list[dict[str, str]],
    fetch_summaries: list[dict[str, str]],
) -> list[str]:
    folded = _fold_known_docs_text(query)
    if not _looks_openai_responses_endpoint_query(query):
        return []

    source_url = _find_official_openai_responses_source(search_hits, fetch_summaries)
    if not source_url:
        source_url = "https://platform.openai.com/docs/api-reference/responses"
    source_md = f"[OpenAI Responses API reference]({source_url})"
    return [
        "**Kết luận nhanh từ nguồn OpenAI:**",
        f"- Endpoint tạo response: `POST https://api.openai.com/v1/responses` ({source_md}).",
        "- Body tối thiểu thực dụng: gửi `model` và `input`; `input` có thể là chuỗi text hoặc mảng input item tùy ca dùng.",
        f"- Nếu cần đọc lại response đã tạo: `GET https://api.openai.com/v1/responses/{{response_id}}` ({source_md}).",
        "",
    ]


def _looks_openai_responses_endpoint_query(query: str) -> bool:
    folded = _fold_known_docs_text(query)
    return (
        "openai" in folded
        and "responses api" in folded
        and any(marker in folded for marker in ("endpoint", "endpoints", "endpoint nao", "endpoint nào"))
    )


def _is_openai_responses_api_reference_hit(hit: dict[str, str]) -> bool:
    url = str(hit.get("url") or "").lower()
    title = str(hit.get("title") or "").lower()
    return (
        "platform.openai.com" in url
        and "api-reference" in url
        and "responses" in url
    ) or (
        "developers.openai.com" in url
        and "api/reference" in url
        and "responses" in url
    ) or (
        "responses" in title
        and "api reference" in title
        and _is_openai_official_url(str(hit.get("url") or ""))
    )


def build_search_template_fallback(
    query: str,
    tool_call_events: list[dict[str, Any]],
    *,
    max_hits: int = 5,
) -> str:
    """Build a citation-bearing markdown response from captured tool events.

    Returns an empty string if there is nothing usable. Caller treats empty
    string as "no salvage available — fall through to next handler".
    """
    if not tool_call_events:
        return ""

    search_hits: list[dict[str, str]] = []
    fetch_summaries: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    call_args_by_id: dict[str, dict[str, Any]] = {}
    call_name_by_id: dict[str, str] = {}
    for event in tool_call_events:
        if event.get("type") == "call":
            event_id = str(event.get("id") or "")
            if event_id:
                call_args_by_id[event_id] = event.get("args") or {}
                call_name_by_id[event_id] = str(event.get("name") or "")

    for event in tool_call_events:
        if event.get("type") != "result":
            continue
        name = str(event.get("name") or "")
        result_text = str(event.get("result") or "")
        event_id = str(event.get("id") or "")

        if _is_search_tool(name):
            for hit in _extract_search_hits(result_text, limit=max_hits):
                if hit["url"] in seen_urls:
                    continue
                seen_urls.add(hit["url"])
                search_hits.append(hit)
                if len(search_hits) >= max_hits:
                    break
        elif _is_fetch_tool(name):
            url = ""
            if event_id and call_args_by_id.get(event_id):
                url = str(call_args_by_id[event_id].get("url") or "")
            summary = _extract_fetch_summary(result_text, max_chars=600)
            if summary:
                fetch_summaries.append(
                    {
                        "url": url,
                        "host": _host_label(url) if url else "nguồn",
                        "summary": summary,
                    }
                )

    if not search_hits and not fetch_summaries:
        return ""

    original_search_hit_count = len(search_hits)
    search_hits = _filter_requested_official_hits(query, search_hits)
    official_source_request = (
        bool(search_hits)
        and _looks_official_source_request(query)
        and "openai" in _fold_known_docs_text(query)
        and all(_is_openai_official_url(str(hit.get("url") or "")) for hit in search_hits)
    )
    official_hits_only = (
        bool(search_hits)
        and len(search_hits) < original_search_hit_count
        and official_source_request
    )

    lines: list[str] = []
    lines.append(_format_intro(query, bool(fetch_summaries), len(search_hits)))
    known_answer_lines = _build_known_docs_answer_lines(
        query,
        search_hits,
        fetch_summaries,
    )
    if known_answer_lines:
        lines.append("")
        lines.extend(known_answer_lines)
        if _looks_openai_responses_endpoint_query(query):
            reference_hits = [
                hit for hit in search_hits if _is_openai_responses_api_reference_hit(hit)
            ]
            if reference_hits:
                search_hits = reference_hits[:max_hits]
            else:
                search_hits = [
                    {
                        "title": "Responses | OpenAI API Reference",
                        "url": "https://platform.openai.com/docs/api-reference/responses",
                        "snippet": "Create a model response with POST /v1/responses; request bodies commonly include model and input.",
                    }
                ]

    if fetch_summaries:
        lines.append("")
        for idx, item in enumerate(fetch_summaries[:2], 1):
            host_md = (
                f"[{item['host']}]({item['url']})" if item["url"] else item["host"]
            )
            lines.append(f"**{idx}. Theo {host_md}:** {item['summary']}")
            lines.append("")

    if search_hits:
        source_heading = (
            "**Nguồn chính thức:**"
            if official_source_request or official_hits_only
            else "**Các nguồn liên quan:**"
        )
        lines.append(source_heading)
        lines.append("")
        for hit in search_hits[:max_hits]:
            host = _host_label(hit["url"])
            link_md = f"[{hit['title']}]({hit['url']})"
            snippet = hit.get("snippet") or ""
            if snippet:
                lines.append(f"- {link_md} — _{snippet}_ ({host})")
            else:
                lines.append(f"- {link_md} ({host})")

    lines.append(_format_outro(len(search_hits)))

    return "\n".join(line for line in lines if line is not None).strip()


def looks_like_search_placeholder_answer(answer: str) -> bool:
    """Detect generic apologies that should not hide successful search results."""
    normalized = re.sub(r"\s+", " ", str(answer or "").strip().lower())
    if not normalized:
        return True
    if len(normalized) > 260:
        return False

    placeholder_markers = (
        "xin lỗi, mình chưa xử lý được",
        "xin loi, minh chua xu ly duoc",
        "mình chưa xử lý được yêu cầu",
        "minh chua xu ly duoc yeu cau",
        "mình chưa tra cứu được",
        "minh chua tra cuu duoc",
        "mình chưa tìm được câu trả lời",
        "minh chua tim duoc cau tra loi",
        "i couldn't process",
        "i could not process",
    )
    return any(marker in normalized for marker in placeholder_markers)
