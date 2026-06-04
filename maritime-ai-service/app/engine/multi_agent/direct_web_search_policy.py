"""Explicit web-search policy for direct tool rounds.

The direct runtime uses these helpers to decide when web-search results are
rich enough to synthesize from tool evidence, when to force source-backed
templates, and how to clean explicit @web-search user turns.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from app.engine.multi_agent.state import AgentState


FORCED_WEB_SEARCH_TOOL_NAMES = (
    "tool_web_search",
    "web_search",
)
_RICH_SEARCH_RESULT_CHAR_FLOOR = 1200
_WEATHER_QUERY_MARKERS = (
    "thoi tiet",
    "nhiet do",
    "weather",
    "forecast",
)
_WEATHER_CURRENT_MARKERS = (
    "hom nay",
    "hien tai",
    "bay gio",
    "luc nay",
    "today",
    "current",
    "currently",
    "right now",
)
_WEATHER_NON_CURRENT_TEMPORAL_MARKERS = (
    "ngay mai",
    "toi mai",
    "mai",
    "ngay kia",
    "hom qua",
    "tuan sau",
    "tuan toi",
    "thang sau",
    "cuoi tuan",
    "thu hai",
    "thu ba",
    "thu tu",
    "thu nam",
    "thu sau",
    "thu bay",
    "chu nhat",
    "tomorrow",
    "yesterday",
    "next week",
    "next month",
    "weekend",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEATHER_LOCATION_STOPWORDS = {
    "a",
    "ban",
    "bao",
    "bay",
    "biet",
    "cho",
    "co",
    "do",
    "du",
    "duoc",
    "giup",
    "gio",
    "hien",
    "hom",
    "kiem",
    "la",
    "lai",
    "luc",
    "minh",
    "mua",
    "nao",
    "nay",
    "nhieu",
    "nhiet",
    "nong",
    "khong",
    "ra",
    "sao",
    "the",
    "thoi",
    "tiet",
    "tra",
    "troi",
    "ua",
    "xem",
    "current",
    "currently",
    "forecast",
    "now",
    "right",
    "today",
    "weather",
}


def _force_skills_for_turn(state: AgentState | None) -> set[str]:
    if not isinstance(state, dict):
        return set()
    force_skills = state.get("force_skills")
    if not force_skills:
        ctx = state.get("context")
        if isinstance(ctx, dict):
            force_skills = ctx.get("force_skills")
    if isinstance(force_skills, (list, tuple, set)):
        return {str(skill).strip().lower() for skill in force_skills if skill}
    return set()


def _has_search_tool_result(tool_call_events: list[dict]) -> bool:
    search_tool_names = {
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
        "tool_search_legal",
        "search_legal",
        "tool_search_maritime",
        "search_maritime",
    }
    return any(
        event.get("type") == "result"
        and str(event.get("name") or "").strip().lower() in search_tool_names
        and (
            str(event.get("result") or "").strip()
            or _metadata_marks_no_source_search_result(event)
        )
        for event in tool_call_events or []
    )


def _metadata_marks_no_source_search_result(event: dict) -> bool:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return False
    status = str(metadata.get("status") or "").strip().lower()
    reason = str(metadata.get("reason_code") or "").strip().lower()
    result_kind = str(metadata.get("result_kind") or "").strip().lower()
    return reason == "no_sources" or (
        result_kind == "web_sources"
        and metadata.get("source_count") == 0
        and status in {"unavailable", "completed", "failed"}
    )


def _has_no_source_search_tool_result(tool_call_events: list[dict]) -> bool:
    return any(
        event.get("type") == "result"
        and _is_search_tool_name(str(event.get("name") or ""))
        and _metadata_marks_no_source_search_result(event)
        for event in tool_call_events or []
    )


def _has_fetch_tool_result(tool_call_events: list[dict]) -> bool:
    return any(
        event.get("type") == "result"
        and str(event.get("name") or "").strip().lower() in {"tool_fetch_url", "fetch_url"}
        and str(event.get("result") or "").strip()
        for event in tool_call_events or []
    )


def _fold_tool_round_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.lower().replace("đ", "d").split())


def _today_vietnam() -> str:
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")


def _has_calendar_anchor(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]20\d{2})\b",
            str(value or ""),
        )
    )


def _contains_folded_marker(folded: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if " " in marker:
            if marker in folded:
                return True
            continue
        if re.search(rf"\b{re.escape(marker)}\b", folded):
            return True
    return False


def _has_non_current_weather_temporal_anchor(value: str) -> bool:
    return _has_calendar_anchor(value) or _contains_folded_marker(
        _fold_tool_round_text(value),
        _WEATHER_NON_CURRENT_TEMPORAL_MARKERS,
    )


def _has_weather_temporal_anchor(value: str) -> bool:
    folded = _fold_tool_round_text(value)
    return (
        _has_calendar_anchor(value)
        or _contains_folded_marker(folded, _WEATHER_CURRENT_MARKERS)
        or _contains_folded_marker(folded, _WEATHER_NON_CURRENT_TEMPORAL_MARKERS)
    )


def _looks_weather_search_text(value: str) -> bool:
    folded = _fold_tool_round_text(value)
    return any(marker in folded for marker in _WEATHER_QUERY_MARKERS)


def _looks_current_weather_text(value: str) -> bool:
    folded = _fold_tool_round_text(value)
    return _looks_weather_search_text(value) or any(
        marker in folded for marker in _WEATHER_CURRENT_MARKERS
    )


def _has_weather_location_hint(value: str) -> bool:
    folded = _fold_tool_round_text(value)
    if not folded:
        return False
    tokens = re.findall(r"[a-z0-9]+", folded)
    remaining = [
        token
        for token in tokens
        if len(token) > 1 and token not in _WEATHER_LOCATION_STOPWORDS
    ]
    return bool(remaining)


def _weather_default_city() -> str:
    try:
        from app.core.config import settings

        return str(getattr(settings, "living_agent_weather_city", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _clean_search_query_text(value: str) -> str:
    text = _strip_vietnamese_discourse_prefix(str(value or "").strip())
    text = _strip_vietnamese_polite_suffix(text)
    text = re.sub(r"(?i)^\s*(?:ua|a|wiii\s+oi|ban\s+oi)[,\s]+", "", text)
    text = re.sub(
        r"(?i)\s+(?:nhu\s+the\s+nao|the\s+nao|ra\s+sao|sao)\s*$",
        "",
        text,
    )
    return text.strip(" .,:;!?-")


def _enrich_current_weather_search_query(
    *,
    candidate_query: str,
    user_query: str,
    today: str | None = None,
    default_city: str | None = None,
) -> str:
    """Return an Odysseus-style web query for live weather fallback.

    Weather without a configured provider should behave like a normal current
    web lookup: one clear query with subject, temporal anchor, and date. The
    model may emit a thin argument such as {"query": "Hai Phong"}, which is
    valid for a weather API but weak for web search.
    """

    today = today or _today_vietnam()
    if default_city is None:
        default_city = _weather_default_city()
    default_city = str(default_city or "").strip()
    candidate = _clean_search_query_text(candidate_query)
    user = _clean_search_query_text(user_query)

    if (
        _has_weather_location_hint(candidate)
        and not (
            _has_weather_temporal_anchor(user)
            and _has_weather_location_hint(user)
        )
    ):
        base = candidate
    elif _has_weather_location_hint(user):
        base = user
    elif default_city:
        base = f"thoi tiet {default_city}"
    else:
        base = candidate or user or "Vietnam"

    if not _looks_weather_search_text(base):
        base = f"thoi tiet {base}".strip()

    if not _has_weather_temporal_anchor(base):
        base = f"{base} hom nay"

    if (
        today
        and not _has_calendar_anchor(base)
        and not _has_non_current_weather_temporal_anchor(base)
    ):
        base = f"{base} {today}"

    return " ".join(base.split())


def _strip_vietnamese_discourse_prefix(text: str) -> str:
    cleaned = str(text or "").strip()
    prefix_pattern = re.compile(
        r"(?i)^\s*(?:"
        r"ý\s+là|y\s+la|ý\s+mình\s+là|y\s+minh\s+la|"
        r"ý\s+tôi\s+là|y\s+toi\s+la|tức\s+là|tuc\s+la|"
        r"nói\s+chung\s+là|noi\s+chung\s+la"
        r")\s+"
    )
    previous = None
    while cleaned and previous != cleaned:
        previous = cleaned
        cleaned = prefix_pattern.sub("", cleaned).strip()
    return cleaned


def _strip_vietnamese_polite_suffix(text: str) -> str:
    """Remove request politeness that hurts search recall but carries no topic."""

    cleaned = str(text or "").strip()
    suffix_pattern = re.compile(
        r"(?i)(?:"
        r"\s+(?:cho|giúp|giup)\s+(?:mình|minh|tôi|toi|em|anh|chị|chi|mình\s+nhé|minh\s+nhe)"
        r"|\s+(?:cho|giúp|giup)\s+(?:mình|minh)?"
        r"|\s+(?:nhé|nhe|nha|ạ|a)\s*"
        r")\s*[.!?]*$"
    )
    previous = None
    while cleaned and previous != cleaned:
        previous = cleaned
        cleaned = suffix_pattern.sub("", cleaned).strip()
    return cleaned


def _looks_explicit_web_search_query(query: str) -> bool:
    folded = _fold_tool_round_text(query)
    if not folded:
        return False
    if "@web-search" in folded or "@web_search" in folded:
        return True
    if "web" in folded and any(marker in folded for marker in ("tim", "search", "tra cuu")):
        return True
    return any(
        marker in folded
        for marker in (
            "tim tren mang",
            "tim kiem tren mang",
            "search the web",
            "look up online",
        )
    )


def _is_search_tool_name(name: str) -> bool:
    return str(name or "").strip().lower() in {
        "tool_web_search",
        "web_search",
        "tool_search_news",
        "search_news",
        "tool_search_legal",
        "search_legal",
        "tool_search_maritime",
        "search_maritime",
    }


def _is_weather_lookup_query(query: str) -> bool:
    try:
        from app.engine.multi_agent.direct_intent import _needs_weather_lookup

        return bool(_needs_weather_lookup(query))
    except Exception:  # noqa: BLE001
        return False


def _prefer_official_query_for_known_docs(args: Any, user_query: str) -> dict:
    normalized_args = dict(args or {}) if isinstance(args, dict) else {}
    current_query = str(normalized_args.get("query") or normalized_args.get("q") or "")
    if _is_weather_lookup_query(user_query):
        normalized_args["query"] = _enrich_current_weather_search_query(
            candidate_query=current_query,
            user_query=user_query,
        )
        normalized_args.pop("q", None)
        return normalized_args

    folded = _fold_tool_round_text(f"{user_query} {current_query}")
    if "openai" in folded and "responses api" in folded:
        normalized_args["query"] = (
            "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
        )
    return normalized_args


def _should_return_search_template_after_tool_round(
    *,
    query: str,
    state: AgentState | None,
    tool_call_events: list[dict],
    tool_round: int,
) -> bool:
    if not _has_search_tool_result(tool_call_events):
        return False
    if _is_weather_lookup_query(query):
        return False
    if not _looks_explicit_web_search_query(query):
        return False
    if _has_no_source_search_tool_result(tool_call_events):
        return True
    search_result_chars = sum(
        len(str(event.get("result") or ""))
        for event in tool_call_events or []
        if event.get("type") == "result" and _is_search_tool_name(str(event.get("name") or ""))
    )
    return (
        _has_fetch_tool_result(tool_call_events)
        or tool_round >= 1
        or search_result_chars >= _RICH_SEARCH_RESULT_CHAR_FLOOR
    )


def _is_explicit_web_search_turn(query: str, state: AgentState | None) -> bool:
    return (
        "web-search" in _force_skills_for_turn(state)
        or _looks_explicit_web_search_query(query)
    )


def _should_use_search_template_for_empty_response(
    *,
    query: str,
    state: AgentState | None,
    tool_call_events: list[dict],
) -> bool:
    if _is_weather_lookup_query(query):
        return False
    return (
        _is_explicit_web_search_turn(query, state)
        and _has_search_tool_result(tool_call_events)
    )


def _clean_forced_web_search_query(query: str) -> str:
    """Convert an explicit @web-search turn into a clean tool query."""
    text = str(query or "").strip()
    text = re.sub(r"(?i)@web-search\b", "", text).strip()
    text = _strip_vietnamese_discourse_prefix(text)
    text = re.split(
        r"(?i)\b(?:trả\s+lời|tra\s+loi|answer|respond|reply)\b",
        text,
        maxsplit=1,
    )[0].strip()
    text = _strip_vietnamese_polite_suffix(text)
    text = text.strip(" .:-–—")
    return text or str(query or "").strip()
