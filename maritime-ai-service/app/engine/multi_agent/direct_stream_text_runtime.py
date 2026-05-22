"""Visible text helpers for direct answer streaming."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any

from app.engine.multi_agent.direct_visible_thinking_cleanup import (
    looks_like_direct_selfhood_answer_draft_paragraph,
    looks_like_direct_selfhood_english_meta_paragraph,
    looks_like_direct_selfhood_meta_heading,
    looks_like_direct_selfhood_meta_intro,
    strip_direct_selfhood_filler_prefix,
)
from app.engine.reasoning import (
    align_visible_thinking_language,
    sanitize_visible_reasoning_text,
    should_align_visible_thinking_language,
)

_DIRECT_VISIBLE_THINKING_PLANNER_MARKERS = (
    "my response to this inquiry",
    "reflecting on the response",
    "reflecting on this response",
    "reflecting on the inquiry",
    "my response to this question",
    "my approach to this question",
    "my approach to answering",
    "here's my take on those thoughts",
    "tailored for an expert audience",
    "for an expert audience",
    "i will attempt a few kaomoji",
    "dash of personality and charm",
    "let's begin",
    "lets begin",
    "day la cach minh thu tom tat lai nhung suy nghi do",
    "nham den doi tuong chuyen gia",
    "xung o ngoi thu nhat, nhu ban yeu cau",
    "to make it easier for them",
    "i will break this down",
    "i can't resist",
    "i cant resist",
    "signature wiii style",
    "final polished version",
    "i will greet",
)

def _strip_incomplete_thinking_blocks(text: str) -> str:
    """Remove complete or partial <thinking> blocks from cumulative streamed text."""
    clean = str(text or "")
    lowered = clean.lower()
    start = lowered.find("<thinking>")
    while start >= 0:
        end = lowered.find("</thinking>", start + len("<thinking>"))
        if end < 0:
            clean = clean[:start]
            break
        clean = clean[:start] + clean[end + len("</thinking>"):]
        lowered = clean.lower()
        start = lowered.find("<thinking>")
    clean = re.sub(r"</thinking\s*>?", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"</thinking$", "", clean, flags=re.IGNORECASE)
    return clean


def _extract_stream_chunk_parts(content: Any) -> tuple[str, str]:
    """Extract per-chunk native reasoning and visible answer text."""
    if isinstance(content, list):
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    answer_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type") or "").strip().lower()
            if block_type == "thinking":
                thinking_text = str(item.get("thinking") or "").strip()
                if thinking_text:
                    reasoning_parts.append(thinking_text)
                continue
            if block_type == "text":
                text_value = str(item.get("text") or "").strip()
                if text_value:
                    answer_parts.append(text_value)
                continue
            text_value = str(item.get("text") or item.get("content") or "").strip()
            if text_value:
                answer_parts.append(text_value)
        return "".join(reasoning_parts), "".join(answer_parts)
    if isinstance(content, str):
        return "", content
    return "", str(content or "")


def _extract_message_text(content: Any) -> str:
    """Flatten a message payload into plain text for intent/alignment checks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text_value = str(
                item.get("text")
                or item.get("content")
                or item.get("thinking")
                or ""
            ).strip()
            if text_value:
                parts.append(text_value)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _normalize_stream_compare_text(value: str) -> str:
    """Normalize answer text for duplicate/replay comparison."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _compute_visible_answer_delta(*, emitted_text: str, visible_text: str) -> str:
    """Return only the genuinely new visible answer text for SSE streaming.

    Some providers emit incremental text chunks and then replay a near-identical
    full answer near the end of the stream. We want to keep real incremental
    growth while skipping those replays.
    """
    candidate = str(visible_text or "")
    emitted = str(emitted_text or "")
    if not candidate:
        return ""
    if not emitted:
        return candidate
    if candidate == emitted:
        return ""
    if candidate.startswith(emitted):
        return candidate[len(emitted):]
    if emitted.startswith(candidate):
        return ""

    normalized_candidate = _normalize_stream_compare_text(candidate)
    normalized_emitted = _normalize_stream_compare_text(emitted)
    if normalized_candidate and normalized_candidate == normalized_emitted:
        return ""

    max_overlap = min(len(candidate), len(emitted))
    for overlap in range(max_overlap, 0, -1):
        if emitted.endswith(candidate[:overlap]):
            return candidate[overlap:]

    if len(normalized_candidate) >= 80 and len(normalized_emitted) >= 80:
        similarity = SequenceMatcher(None, normalized_candidate, normalized_emitted).ratio()
        if similarity >= 0.985:
            return ""

    return candidate


def _split_visible_thinking_chunks(text: str) -> list[str]:
    """Break a thinking block into stable SSE-sized paragraphs without rewriting it."""
    clean = sanitize_visible_reasoning_text(str(text or "")).strip()
    if not clean:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    if paragraphs:
        return paragraphs

    return [clean]


def _fold_direct_marker_text(text: str) -> str:
    lowered = str(text or "").strip().lower()
    lowered = lowered.replace("đ", "d").replace("Đ", "d")
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(ch)
    )


async def _normalize_direct_visible_thinking_impl(
    text: str,
    *,
    response_language: str,
    alignment_mode: str | None,
    llm: Any,
    align_visible_thinking_language_fn=align_visible_thinking_language,
    should_align_visible_thinking_language_fn=should_align_visible_thinking_language,
    sanitize_visible_reasoning_text_fn=sanitize_visible_reasoning_text,
) -> str:
    clean = sanitize_visible_reasoning_text_fn(str(text or "")).strip()
    if not clean:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    if not paragraphs:
        paragraphs = [clean]

    kept: list[str] = []
    for paragraph in paragraphs:
        lowered = paragraph.lower().strip()
        folded = _fold_direct_marker_text(paragraph)
        if alignment_mode == "direct_selfhood":
            if (
                looks_like_direct_selfhood_meta_heading(paragraph)
                or looks_like_direct_selfhood_meta_intro(paragraph)
                or looks_like_direct_selfhood_answer_draft_paragraph(paragraph)
            ):
                continue
        if any(
            marker in lowered or marker in folded
            for marker in _DIRECT_VISIBLE_THINKING_PLANNER_MARKERS
        ):
            continue

        normalized = paragraph
        if alignment_mode == "direct_selfhood":
            if looks_like_direct_selfhood_english_meta_paragraph(normalized):
                continue
            normalized = strip_direct_selfhood_filler_prefix(normalized)
        if should_align_visible_thinking_language_fn(
            normalized,
            target_language=response_language,
        ):
            try:
                aligned = await align_visible_thinking_language_fn(
                    normalized,
                    target_language=response_language,
                    alignment_mode=alignment_mode,
                    llm=llm,
                )
            except Exception:
                aligned = None
            if aligned and not should_align_visible_thinking_language_fn(
                aligned,
                target_language=response_language,
            ):
                normalized = aligned.strip()

        if should_align_visible_thinking_language_fn(
            normalized,
            target_language=response_language,
        ):
            continue

        normalized = sanitize_visible_reasoning_text_fn(normalized).strip()
        if alignment_mode == "direct_selfhood":
            if (
                looks_like_direct_selfhood_meta_heading(normalized)
                or looks_like_direct_selfhood_meta_intro(normalized)
                or looks_like_direct_selfhood_english_meta_paragraph(normalized)
                or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
            ):
                continue
            normalized = strip_direct_selfhood_filler_prefix(normalized)
            if should_align_visible_thinking_language_fn(
                normalized,
                target_language=response_language,
            ):
                continue
        if normalized:
            kept.append(normalized)

    return "\n\n".join(kept).strip()


def _split_visible_answer_chunks(text: str, *, target_size: int = 160) -> list[str]:
    """Chunk a completed answer for pseudo-stream playback without changing content."""
    clean = str(text or "").strip()
    if not clean:
        return []
    if len(clean) <= target_size:
        return [clean]

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + target_size)
        if end < len(clean):
            search_start = max(start + 1, end - 40)
            boundary = -1
            for index in range(end, search_start, -1):
                if clean[index - 1].isspace():
                    boundary = index
                    break
            if boundary > start:
                end = boundary
        chunks.append(clean[start:end])
        start = end
    return chunks or [clean]
