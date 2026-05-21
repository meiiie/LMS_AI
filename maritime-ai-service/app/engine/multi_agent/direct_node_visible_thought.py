"""Visible-thought and identity cleanup helpers for the direct node."""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any

from app.engine.multi_agent.direct_intent import _looks_emotional_support_turn
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.direct_visible_thinking_cleanup import (
    looks_like_direct_selfhood_answer_draft_paragraph,
    looks_like_direct_selfhood_english_meta_paragraph,
    looks_like_direct_selfhood_meta_heading,
    looks_like_direct_selfhood_meta_intro,
    strip_direct_selfhood_filler_prefix,
)
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    align_visible_thinking_language,
    should_align_visible_thinking_language,
)

logger = logging.getLogger(__name__)

_IDENTITY_LORE_MARKERS = (
    "the wiii lab",
    "2024",
    "ra doi",
    "dem mua",
    "bong",
)
_IDENTITY_ORIGIN_QUERY_MARKERS = (
    "ra doi",
    "duoc tao",
    "duoc sinh ra",
    "sinh ra",
    "nguon goc",
    "the wiii lab",
    "creator",
    "created by",
    "ai tao",
)
_DIRECT_WOVEN_THOUGHT_INTENTS = {
    "social",
    "personal",
    "off_topic",
    "emotional",
    "identity",
    "selfhood",
}
_DIRECT_ENGLISH_PLANNER_MARKERS = (
    "the goal is",
    "i'm focusing on",
    "i am focusing on",
    "i've just refined",
    "ive just refined",
    "i opted for",
    "registered the user's input",
    "registered the users input",
    "processing the sentiment",
    "warm, empathetic response",
    "natural, conversational reply",
    "because it sounds the most natural",
)
_DIRECT_INTERNAL_THOUGHT_MARKERS = (
    "living core card",
    "wiii living core card",
    "system prompt",
    "promptloader",
    "persona yaml",
    "yaml persona",
    "house prompt",
    "developer instruction",
    "instruction block",
)
_DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS = (
    "đây là kết quả tôi đã thực hiện",
    "day la ket qua toi da thuc hien",
    "here's the final",
    "here is the final",
    "here is the result",
    "this is the result i produced",
)
_DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL = (
    "i think it sounds natural",
    "i'm excited for them to hear",
    "im excited for them to hear",
    "it follows the instructions",
    "it is not too robotic",
)
def _strip_direct_inline_private_asides(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return cleaned

    cleaned = re.sub(
        r"^\s*(\*{1,2})\s*(?:nghĩ thầm|nghi tham|visible thinking|suy nghĩ của wiii|suy nghi cua wiii)\s*:\s*",
        r"\1",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^\s*\((?:nghĩ thầm|nghi tham|visible thinking|suy nghĩ của wiii|suy nghi cua wiii)\s*:\s*",
        "(",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    changed = True
    while changed and cleaned:
        changed = False
        stripped = cleaned.lstrip()

        json_match = re.match(
            r"^\{\s*\"visible_thinking\"\s*:\s*\".*?\"\s*\}\s*",
            stripped,
            flags=re.DOTALL,
        )
        if json_match:
            cleaned = stripped[json_match.end() :].lstrip()
            changed = True
            continue

        if stripped.startswith("("):
            boundary = stripped.find(")\n\n")
            if boundary > 0 and boundary < 500:
                cleaned = stripped[boundary + 3 :].lstrip()
                changed = True
                continue

        if stripped.startswith("*"):
            boundary = stripped.find("*\n\n", 1)
            if boundary > 0 and boundary < 500:
                cleaned = stripped[boundary + 3 :].lstrip()
                changed = True
                continue
    return cleaned.strip()


def _compact_basic_identity_answer(value: str, *, query: str) -> str:
    cleaned = _strip_direct_inline_private_asides(value)
    if not cleaned:
        return cleaned

    folded_query = _fold_direct_text(query)
    if any(marker in folded_query for marker in _IDENTITY_ORIGIN_QUERY_MARKERS):
        return cleaned

    if len(cleaned) < 320 and not any(marker in _fold_direct_text(cleaned) for marker in _IDENTITY_LORE_MARKERS):
        return cleaned

    kept: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("*"):
            continue
        folded_line = _fold_direct_text(line)
        if any(marker in folded_line for marker in _IDENTITY_LORE_MARKERS):
            continue
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if part.strip()]
        for sentence in sentences:
            folded_sentence = _fold_direct_text(sentence)
            if any(marker in folded_sentence for marker in _IDENTITY_LORE_MARKERS):
                continue
            if sentence not in kept:
                kept.append(sentence)

    if not kept:
        return cleaned

    compact = " ".join(kept[:4]).strip()
    return compact or cleaned


def _extract_direct_woven_thought(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""

    italic_match = re.match(r"^\*{1,2}(?P<thought>.+?)\*{1,2}(?:\s+|$)", cleaned, flags=re.DOTALL)
    if italic_match:
        thought = italic_match.group("thought").strip()
        if 20 <= len(thought) <= 400:
            return thought

    paren_match = re.match(r"^\((?P<thought>.+?)\)(?:\s+|$)", cleaned, flags=re.DOTALL)
    if paren_match:
        thought = paren_match.group("thought").strip()
        if 20 <= len(thought) <= 400:
            return thought

    return ""


def _looks_like_direct_english_planner_thought(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if len(lowered) < 40:
        return False
    return any(marker in lowered for marker in _DIRECT_ENGLISH_PLANNER_MARKERS)


def _contains_direct_internal_thought_leak(value: str) -> bool:
    folded = _fold_direct_text(value)
    if not folded:
        return False
    return any(marker in folded for marker in _DIRECT_INTERNAL_THOUGHT_MARKERS)


def _trim_direct_visible_thought_answer_draft(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""

    lowered = clean.lower()
    cut_at = len(clean)
    for marker in _DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS:
        idx = lowered.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)

    trimmed = clean[:cut_at].rstrip(" :\n\t") if cut_at < len(clean) else clean
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    while paragraphs:
        folded_tail = _fold_direct_text(paragraphs[-1])
        if any(marker in folded_tail for marker in _DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL):
            paragraphs.pop()
            continue
        break
    return "\n\n".join(paragraphs).strip()


def _should_surface_direct_visible_thought(
    value: str,
    *,
    routing_intent: str = "",
    response: str = "",
) -> bool:
    clean = _strip_direct_inline_private_asides(value)
    if len(clean) < 20:
        return False
    normalized_intent = str(routing_intent or "").strip().lower()
    if normalized_intent not in _DIRECT_WOVEN_THOUGHT_INTENTS:
        return False
    if _extract_direct_woven_thought(response):
        return False
    if _contains_direct_internal_thought_leak(clean):
        return False
    if _looks_like_direct_english_planner_thought(clean):
        return False
    return True


async def _align_direct_visible_thought(
    value: str,
    *,
    response_language: str,
    llm,
) -> str:
    clean = _strip_direct_inline_private_asides(value)
    if not clean:
        return ""
    trimmed = _trim_direct_visible_thought_answer_draft(clean)
    if not trimmed:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        normalized = paragraph.strip()
        if (
            looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        normalized = strip_direct_selfhood_filler_prefix(normalized)
        if should_align_visible_thinking_language(
            normalized,
            target_language=response_language,
        ):
            aligned = await align_visible_thinking_language(
                normalized,
                target_language=response_language,
                llm=llm,
            )
            normalized = _strip_direct_inline_private_asides(aligned or normalized).strip()
            normalized = strip_direct_selfhood_filler_prefix(normalized)
        if (
            not normalized
            or looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        if should_align_visible_thinking_language(
            normalized,
            target_language=response_language,
        ):
            continue
        kept.append(normalized)
    return "\n\n".join(kept).strip()


def _best_effort_direct_visible_thought_raw(value: str) -> str:
    clean = _strip_direct_inline_private_asides(value)
    if not clean:
        return ""
    trimmed = _trim_direct_visible_thought_answer_draft(clean)
    if not trimmed:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", trimmed) if part.strip()]
    kept: list[str] = []
    for paragraph in paragraphs:
        normalized = paragraph.strip()
        if (
            not normalized
            or looks_like_direct_selfhood_meta_intro(normalized)
            or looks_like_direct_selfhood_meta_heading(normalized)
            or looks_like_direct_selfhood_english_meta_paragraph(normalized)
            or looks_like_direct_selfhood_answer_draft_paragraph(normalized)
        ):
            continue
        normalized = strip_direct_selfhood_filler_prefix(normalized)
        if not normalized or _contains_direct_internal_thought_leak(normalized):
            continue
        kept.append(normalized)
    return "\n\n".join(kept).strip()


async def _build_emotional_rescue_visible_thought(
    *,
    query: str,
    state: AgentState,
    response: str,
    response_language: str,
    llm: Any,
    build_direct_reasoning_summary,
    tool_names: list[str] | None = None,
) -> str:
    """Backfill a tiny public thought when emotional turns return no native thought."""
    if not _looks_emotional_support_turn(query):
        return ""
    if not str(response or "").strip():
        return ""

    try:
        fallback = build_direct_reasoning_summary(query, state, tool_names or [])
        if inspect.isawaitable(fallback):
            fallback = await fallback
    except Exception as exc:
        logger.debug("[DIRECT] Emotional rescue summary skipped: %s", exc)
        return ""

    clean = _strip_direct_inline_private_asides(str(fallback or "")).strip()
    if len(clean) < 20:
        return ""
    if _contains_direct_internal_thought_leak(clean):
        return ""
    if _looks_like_direct_english_planner_thought(clean):
        return ""

    aligned = await _align_direct_visible_thought(
        clean,
        response_language=response_language,
        llm=llm,
    )
    if aligned and not _contains_direct_internal_thought_leak(
        aligned
    ) and not should_align_visible_thinking_language(
        aligned,
        target_language=response_language,
    ):
        return aligned
    return _best_effort_direct_visible_thought_raw(clean)
