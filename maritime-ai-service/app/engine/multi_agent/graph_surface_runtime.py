"""Surface/runtime helper implementations extracted from graph.py."""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from app.engine.multi_agent.graph_support import _build_recent_conversation_context
from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator
from app.engine.reasoning.reasoning_narrator import build_tool_context_summary


_HOUSE_CJK_CHAR_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)
_HOUSE_CJK_REQUEST_MARKERS = (
    "tieng trung",
    "ti\u1ebfng trung",
    "chinese",
    "han ngu",
    "hanzi",
    "tieng nhat",
    "ti\u1ebfng nh\u1eadt",
    "japanese",
    "tieng han",
    "ti\u1ebfng h\u00e0n",
    "korean",
    "\u4e2d\u6587",
    "\u65e5\u672c\u8a9e",
    "\ud55c\uad6d\uc5b4",
)
_HOUSE_LITERAL_REPLACEMENTS = (
    ("\u5728\u8fd9\u513f", "\u1edf \u0111\u00e2y"),
    ("\u5728\u8fd9\u91cc", "\u1edf \u0111\u00e2y"),
    ("C\u00f2n b\u1ea1n\u5462", "C\u00f2n b\u1ea1n nh\u1ec9"),
    ("c\u00f2n b\u1ea1n\u5462", "c\u00f2n b\u1ea1n nh\u1ec9"),
    ("B\u1ea1n\u5462", "B\u1ea1n nh\u1ec9"),
    ("b\u1ea1n\u5462", "b\u1ea1n nh\u1ec9"),
    ("\u5462?", " nh\u1ec9?"),
    ("\u5462!", " nh\u1ec9!"),
    ("\u5462.", " nh\u1ec9."),
    ("\u5462,", " nh\u1ec9,"),
    ("\u5462", " nh\u1ec9"),
)
_BROKEN_SOUL_PREFIX_MARKERS = (
    "mouthcurve",
    "eyeshape",
    "eyeopenness",
    "blush",
    "intensity",
)
_BROKEN_SOUL_PREFIX_RE = re.compile(r"^\s*.{0,1400}?-->\s*", re.DOTALL)


def _strip_broken_soul_prefix(value: str) -> str:
    """Remove truncated WIII_SOUL emotion JSON leaked at the start of text.

    Complete tags are stripped at the SSE layer. This catches tail-only leaks
    such as `"face": {"mouthCurve": ...}-->` that can appear after chunking.
    """
    prefix = str(value or "")[:1400].lower()
    if "-->" not in prefix:
        return value
    if not any(marker in prefix for marker in _BROKEN_SOUL_PREFIX_MARKERS):
        return value
    return _BROKEN_SOUL_PREFIX_RE.sub("", value, count=1)


def get_effective_provider_impl(state) -> Optional[str]:
    user = str(state.get("provider") or "").strip().lower()
    if user and user != "auto":
        return user
    house = str(state.get("_house_routing_provider") or "").strip().lower()
    if house and house != "auto":
        return house
    return None


def get_explicit_user_provider_impl(state) -> Optional[str]:
    user = str(state.get("provider") or "").strip().lower()
    if user and user != "auto":
        return user
    return None


def build_reasoning_render_request_impl(
    *,
    state,
    node: str,
    phase: str,
    intent: str = "",
    cue: str = "",
    next_action: str = "",
    tool_names=None,
    result=None,
    observations=None,
    confidence: float = 0.0,
    visibility_mode: str = "rich",
    style_tags=None,
    thinking_mode: str = "",
    topic_hint: str = "",
    evidence_plan=None,
    analytical_axes=None,
) -> ReasoningRenderRequest:
    ctx = state.get("context", {}) or {}
    living_block = state.get("living_context_block") or ctx.get("living_context_block") or {}
    if not isinstance(living_block, dict):
        living_block = {}
    return ReasoningRenderRequest(
        node=node,
        phase=phase,
        intent=intent or str((state.get("routing_metadata") or {}).get("intent", "")),
        cue=cue,
        user_goal=state.get("query", ""),
        conversation_context=_build_recent_conversation_context(state),
        memory_context=str(state.get("memory_output") or ""),
        capability_context=str(state.get("capability_context") or ""),
        tool_context=build_tool_context_summary(tool_names, result=result),
        confidence=confidence,
        thinking_mode=thinking_mode,
        topic_hint=topic_hint,
        evidence_plan=[item for item in (evidence_plan or []) if item],
        analytical_axes=[item for item in (analytical_axes or []) if item],
        next_action=next_action,
        visibility_mode=visibility_mode,
        organization_id=state.get("organization_id") or ctx.get("organization_id"),
        user_id=state.get("user_id", "__global__"),
        personality_mode=ctx.get("personality_mode"),
        mood_hint=ctx.get("mood_hint"),
        current_state=[
            str(item).strip()
            for item in (living_block.get("current_state") or [])
            if str(item).strip()
        ],
        narrative_state=[
            str(item).strip()
            for item in (living_block.get("narrative_state") or [])
            if str(item).strip()
        ],
        relationship_memory=[
            str(item).strip()
            for item in (living_block.get("relationship_memory") or [])
            if str(item).strip()
        ],
        observations=[item for item in (observations or []) if item],
        style_tags=style_tags or [],
        provider=state.get("provider"),
    )


async def render_reasoning_impl(**kwargs):
    request = build_reasoning_render_request_impl(**kwargs)
    return await get_reasoning_narrator().render(request)


async def render_reasoning_fast_impl(**kwargs):
    request = build_reasoning_render_request_impl(**kwargs)
    try:
        asyncio.get_running_loop()
        return get_reasoning_narrator().render_fast(request)
    except RuntimeError:
        narrator = get_reasoning_narrator()
        return narrator.render_fast(request)


def query_allows_cjk_surface_impl(query: str) -> bool:
    compact = str(query or "").strip()
    lowered = compact.lower()
    if any(marker in lowered for marker in _HOUSE_CJK_REQUEST_MARKERS):
        return True
    return bool(_HOUSE_CJK_CHAR_RE.search(compact))


_HOUSE_LINKISH_RE = re.compile(
    r"https?://[^\s<>)\]\"']+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>)\]\"']*)?",
    re.IGNORECASE,
)


def sanitize_wiii_house_text_impl(
    value: str,
    *,
    query: str = "",
    query_allows_cjk_surface_fn,
) -> str:
    cleaned = str(value or "")
    if not cleaned:
        return cleaned
    cleaned = _strip_broken_soul_prefix(cleaned)
    protected_urls: list[str] = []

    def _protect_url(match: re.Match[str]) -> str:
        protected_urls.append(match.group(0))
        return f"__WIII_URL_{len(protected_urls) - 1}__"

    cleaned = _HOUSE_LINKISH_RE.sub(_protect_url, cleaned)
    if query_allows_cjk_surface_fn(query):
        for index, url in enumerate(protected_urls):
            cleaned = cleaned.replace(f"__WIII_URL_{index}__", url)
        return cleaned.strip()

    for old, new in _HOUSE_LITERAL_REPLACEMENTS:
        cleaned = cleaned.replace(old, new)

    cleaned = _HOUSE_CJK_CHAR_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    # Insert space after punctuation, but PRESERVE numeric formats: "110.01",
    # "13:18", "1,480", "0,96%". Negative lookbehind/lookahead skips when
    # punctuation sits between two digits (Vietnamese/finance number format).
    cleaned = re.sub(r"(?<!\d)([,.;:!?])(?!\d)([^\s])", r"\1 \2", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Phase 35 — strip DeepSeek native tool-call markup that leaks through
    # NVIDIA NIM (`<｜DSML｜tool_calls>...</｜DSML｜tool_calls>`). When parser
    # misses these and they reach final synthesis, user sees raw XML.
    # Strip the entire DSML block (open + content + close).
    cleaned = re.sub(
        r"<｜DSML｜tool_calls>.*?</｜DSML｜tool_calls>",
        "", cleaned, flags=re.DOTALL,
    )
    # Also strip stray opening or closing DSML tags (asymmetric leak).
    cleaned = re.sub(r"</?｜DSML｜[^>]*>", "", cleaned)
    cleaned = re.sub(r"</?\|DSML\|[^>]*>", "", cleaned)  # ASCII variant
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    for index, url in enumerate(protected_urls):
        cleaned = cleaned.replace(f"__WIII_URL_{index}__", url)
    return cleaned


async def build_direct_round_label_impl(
    *,
    state,
    tool_names,
    round_index: int,
    infer_direct_reasoning_cue_fn,
    render_reasoning_fast_fn,
) -> str:
    cue = infer_direct_reasoning_cue_fn("", {}, tool_names)
    beat = await render_reasoning_fast_fn(
        state=state,
        node="direct",
        phase="verify" if round_index > 0 else "ground",
        cue=cue,
        tool_names=tool_names,
    )
    return beat.label


async def build_direct_synthesis_summary_impl(
    *,
    query: str,
    state,
    tool_names,
    infer_direct_reasoning_cue_fn,
    render_reasoning_fast_fn,
) -> str:
    cue = infer_direct_reasoning_cue_fn(query, state, tool_names)
    beat = await render_reasoning_fast_fn(
        state=state,
        node="direct",
        phase="synthesize",
        cue=cue,
        tool_names=tool_names,
        style_tags=["direct", "summary"],
    )
    return beat.summary
