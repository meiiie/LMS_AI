"""Explicit web-search policy for direct tool rounds.

The direct runtime uses these helpers to decide when web-search results are
rich enough to synthesize from tool evidence, when to force source-backed
templates, and how to clean explicit @web-search user turns.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.engine.multi_agent.state import AgentState


FORCED_WEB_SEARCH_TOOL_NAMES = (
    "tool_web_search",
    "web_search",
)
_RICH_SEARCH_RESULT_CHAR_FLOOR = 1200


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
        and str(event.get("result") or "").strip()
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


def _prefer_official_query_for_known_docs(args: Any, user_query: str) -> dict:
    normalized_args = dict(args or {}) if isinstance(args, dict) else {}
    current_query = str(normalized_args.get("query") or normalized_args.get("q") or "")
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
    routing_meta = state.get("routing_metadata") if isinstance(state, dict) else {}
    routing_intent = str((routing_meta or {}).get("intent") or "").strip().lower()
    explicit_web = routing_intent == "web_search" or _looks_explicit_web_search_query(query)
    if not explicit_web:
        return False
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
    routing_meta = state.get("routing_metadata") if isinstance(state, dict) else {}
    routing_intent = str((routing_meta or {}).get("intent") or "").strip().lower()
    return (
        "web-search" in _force_skills_for_turn(state)
        or routing_intent == "web_search"
        or _looks_explicit_web_search_query(query)
    )


def _should_use_search_template_for_empty_response(
    *,
    query: str,
    state: AgentState | None,
    tool_call_events: list[dict],
) -> bool:
    return (
        _is_explicit_web_search_turn(query, state)
        and _has_search_tool_result(tool_call_events)
    )


def _clean_forced_web_search_query(query: str) -> str:
    """Convert an explicit @web-search turn into a clean tool query."""
    text = str(query or "").strip()
    text = re.sub(r"(?i)@web-search\b", "", text).strip()
    text = re.split(
        r"(?i)\b(?:trả\s+lời|tra\s+loi|answer|respond|reply)\b",
        text,
        maxsplit=1,
    )[0].strip()
    text = text.strip(" .:-–—")
    return text or str(query or "").strip()
