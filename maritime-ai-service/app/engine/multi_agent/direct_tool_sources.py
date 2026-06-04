"""Source extraction for direct tool results.

Direct web-search tools return markdown-ish text because the full result still
needs to go back to the model. The UI, however, needs structured source items
so search feels like an evidence-gathering step instead of a raw tool dump.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse


_BLOCK_SEPARATOR_PATTERN = re.compile(r"\n\s*---\s*\n")
_MARKDOWN_TITLE_PATTERN = re.compile(r"^\s*\*\*(.+?)\*\*", re.MULTILINE)
_URL_LINE_PATTERN = re.compile(r"^\s*URL:\s*(https?://\S+)", re.IGNORECASE | re.MULTILINE)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_URL_PATTERN = re.compile(r"https?://[^\s)>\]}\"']+")

_SOURCE_BACKED_TOOL_MARKERS = (
    "web_search",
    "search_news",
    "search_legal",
    "search_maritime",
)


def is_source_backed_tool_name(tool_name: str) -> bool:
    lowered = str(tool_name or "").strip().lower()
    return any(marker in lowered for marker in _SOURCE_BACKED_TOOL_MARKERS)


def extract_source_infos_from_tool_result(
    tool_name: str,
    result: Any,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return public web sources from a direct search tool result."""

    if not is_source_backed_tool_name(tool_name):
        return []
    text = str(result or "").strip()
    if not text:
        return []

    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def add(title: str, url: str, content: str = "") -> None:
        cleaned_url = _clean_url(url)
        if not cleaned_url or cleaned_url in seen_urls or len(sources) >= limit:
            return
        seen_urls.add(cleaned_url)
        safe_title = _clean_title(title) or _host_label(cleaned_url)
        safe_content = _clean_content(content) or cleaned_url
        sources.append(
            {
                "title": safe_title[:220],
                "content": safe_content[:700],
                "url": cleaned_url,
                "source_type": "web",
            }
        )

    parsed = _parse_json(text)
    if parsed is not None:
        for item in _iter_json_source_items(parsed):
            add(
                str(item.get("title") or ""),
                str(item.get("url") or item.get("href") or item.get("link") or ""),
                str(
                    item.get("snippet")
                    or item.get("body")
                    or item.get("summary")
                    or item.get("content")
                    or ""
                ),
            )
            if len(sources) >= limit:
                return sources

    for block in _split_result_blocks(text):
        url = _extract_block_url(block)
        if not url:
            continue
        title = _extract_block_title(block) or _host_label(url)
        add(title, url, _extract_block_snippet(block, title))
        if len(sources) >= limit:
            return sources

    for match in _MARKDOWN_LINK_PATTERN.finditer(text):
        add(match.group(1), match.group(2))
        if len(sources) >= limit:
            return sources

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        match = _URL_PATTERN.search(line)
        if not match:
            continue
        url = match.group(0)
        title = ""
        if index > 0 and not _URL_PATTERN.search(lines[index - 1]):
            title = lines[index - 1]
        add(title, url)
        if len(sources) >= limit:
            return sources

    return sources


def _parse_json(text: str) -> Any | None:
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _iter_json_source_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("results", "items", "sources", "data"):
        item = value.get(key)
        if isinstance(item, list):
            return [entry for entry in item if isinstance(entry, dict)]
    if any(key in value for key in ("url", "href", "link")):
        return [value]
    return []


def _split_result_blocks(text: str) -> list[str]:
    blocks = [
        block.strip()
        for block in _BLOCK_SEPARATOR_PATTERN.split(text)
        if block.strip()
    ]
    if blocks:
        return blocks
    return [text.strip()] if text.strip() else []


def _extract_block_url(block: str) -> str:
    line_match = _URL_LINE_PATTERN.search(block)
    if line_match:
        return _clean_url(line_match.group(1))
    generic_match = _URL_PATTERN.search(block)
    return _clean_url(generic_match.group(0)) if generic_match else ""


def _extract_block_title(block: str) -> str:
    title_match = _MARKDOWN_TITLE_PATTERN.search(block)
    if title_match:
        return _clean_title(title_match.group(1))
    for line in block.splitlines():
        cleaned = _clean_title(line)
        if cleaned and not _URL_PATTERN.search(cleaned) and not cleaned.lower().startswith("url:"):
            return cleaned
    return ""


def _extract_block_snippet(block: str, title: str) -> str:
    snippets: list[str] = []
    title_seen = False
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not title_seen and title and title in line:
            title_seen = True
            continue
        if _URL_PATTERN.search(line) or line.lower().startswith("url:"):
            continue
        snippets.append(line)
        if len(" ".join(snippets)) >= 700:
            break
    return _clean_content(" ".join(snippets))


def _clean_title(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .strip("-*•· ")
        .replace("**", "")
        .strip()
    )


def _clean_content(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip(".,;:)>]}'\"")


def _host_label(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
    except Exception:
        host = ""
    return host or "Web source"


__all__ = [
    "extract_source_infos_from_tool_result",
    "is_source_backed_tool_name",
]
