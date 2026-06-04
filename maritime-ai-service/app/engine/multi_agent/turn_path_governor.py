"""Typed turn-path decisions for chat tool binding.

The governor is intentionally pure: callers collect runtime signals, then this
module chooses the path and the tool-binding policy for that path. Tool
collection can then bind from the decision instead of mixing routing and
capability exposure in the same block.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Literal

from app.engine.multi_agent.social_followup_policy import (
    looks_short_social_followup_turn,
)
from app.engine.tools.tool_capability_registry import (
    HOST_ACTION_PREFIX,
    LMS_DOCUMENT_PREVIEW_TOOL_NAMES,
    POINTY_TOOL_PREFIX,
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    WIII_CONNECT_LIST_ACTIONS_TOOL,
    WEATHER_TOOL_NAMES,
)

TurnPathName = Literal[
    "casual_chat",
    "reasoning_safety",
    "host_ui_navigation",
    "pointy_guidance",
    "lms_document_preview",
    "external_connection_status",
    "external_app_action",
    "weather_lookup",
    "web_search",
    "datetime_lookup",
    "lms_query",
    "knowledge_search",
    "maritime_search",
    "visual_generation",
    "code_execution",
    "analytical_text",
    "direct_prose",
]


POINTY_TOOL_PREFIXES: tuple[str, ...] = (POINTY_TOOL_PREFIX,)
HOST_ACTION_TOOL_PREFIXES: tuple[str, ...] = (HOST_ACTION_PREFIX,)
CHARACTER_MEMORY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "tool_character_note",
        "tool_character_read",
        "tool_character_log_experience",
    }
)
LIVE_LOOKUP_READ_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "tool_current_datetime",
        "tool_web_search",
        "tool_fetch_url",
    }
)
# Weather turns should not fetch arbitrary URLs; keep URL reads on the explicit
# web/url lane until fetch_url has stronger SSRF guardrails.
WEATHER_LIVE_LOOKUP_TOOL_NAMES: frozenset[str] = WEATHER_TOOL_NAMES | (
    LIVE_LOOKUP_READ_TOOL_NAMES - frozenset({"tool_fetch_url"})
)
WEB_SEARCH_TOOL_NAMES: frozenset[str] = LIVE_LOOKUP_READ_TOOL_NAMES | frozenset(
    {
        "tool_search_news",
        "tool_search_legal",
        "tool_search_maritime",
    }
)


@dataclass(frozen=True, slots=True)
class TurnPathSignals:
    """Normalized input signals consumed by the turn path governor."""

    normalized_query: str = ""
    routing_intent: str = ""
    thinking_mode: str = ""
    force_skills: frozenset[str] = frozenset()
    web_search_forced: bool = False
    pointy_forced: bool = False
    host_ui_navigation: bool = False
    looks_document_preview: bool = False
    looks_reasoning_safety_meta: bool = False
    looks_wiii_pipeline_meta: bool = False
    needs_external_connection_status: bool = False
    needs_external_app_action: bool = False
    needs_weather_lookup: bool = False
    needs_web_search: bool = False
    needs_datetime: bool = False
    needs_news_search: bool = False
    needs_legal_search: bool = False
    needs_lms_query: bool = False
    needs_direct_knowledge_search: bool = False
    needs_character_memory_tool: bool = False
    needs_analysis_tool: bool = False
    prefers_code_execution_lane: bool = False
    needs_maritime_search: bool = False
    pointy_requested: bool = False
    suppress_pointy_for_output: bool = False
    visual_force_tool: bool = False
    visual_mode: str = "text"
    visual_presentation_intent: str = "text"
    visual_required_tool_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TurnPathDecision:
    """Authoritative path and tool policy for one chat turn."""

    path: TurnPathName
    reason: str
    bind_tools: bool = True
    force_tools: bool = False
    allow_all_tools: bool = True
    allowed_tool_names: frozenset[str] = frozenset()
    allowed_tool_prefixes: tuple[str, ...] = ()
    forbidden_tool_names: frozenset[str] = frozenset()
    forbidden_tool_prefixes: tuple[str, ...] = ()
    allow_agent_handoff: bool = True
    allow_rag_delegation: bool = False

    def should_keep_tool_name(self, tool_name: str) -> bool:
        name = str(tool_name or "").strip()
        if not name or not self.bind_tools:
            return False
        if name in self.forbidden_tool_names:
            return False
        if any(name.startswith(prefix) for prefix in self.forbidden_tool_prefixes):
            return False
        if self.allow_all_tools:
            return True
        if name in self.allowed_tool_names:
            return True
        return any(name.startswith(prefix) for prefix in self.allowed_tool_prefixes)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": "turn_path_decision.v1",
            "path": self.path,
            "reason": self.reason,
            "bind_tools": self.bind_tools,
            "force_tools": self.force_tools,
            "allow_all_tools": self.allow_all_tools,
            "allowed_tool_names": sorted(self.allowed_tool_names),
            "allowed_tool_prefixes": list(self.allowed_tool_prefixes),
            "forbidden_tool_names": sorted(self.forbidden_tool_names),
            "forbidden_tool_prefixes": list(self.forbidden_tool_prefixes),
            "allow_agent_handoff": self.allow_agent_handoff,
            "allow_rag_delegation": self.allow_rag_delegation,
        }


def filter_tools_for_turn_path(
    tools: list[Any],
    decision: TurnPathDecision,
    *,
    tool_name: Callable[[Any], str],
) -> list[Any]:
    """Apply a turn-path binding policy to an already available tool pool."""

    if not decision.bind_tools:
        return []
    return [
        tool
        for tool in tools
        if decision.should_keep_tool_name(tool_name(tool))
    ]


def resolve_turn_path_decision(signals: TurnPathSignals) -> TurnPathDecision:
    """Choose the active turn path before binding tools."""

    if signals.looks_reasoning_safety_meta:
        return TurnPathDecision(
            path="reasoning_safety",
            reason="reasoning_safety_meta_turn",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.looks_wiii_pipeline_meta:
        return TurnPathDecision(
            path="direct_prose",
            reason="wiii_pipeline_meta_no_tool",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.looks_document_preview:
        return TurnPathDecision(
            path="lms_document_preview",
            reason="uploaded_document_preview_request",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=LMS_DOCUMENT_PREVIEW_TOOL_NAMES,
            allow_agent_handoff=False,
        )

    if signals.needs_external_connection_status:
        return TurnPathDecision(
            path="external_connection_status",
            reason="wiii_connect_provider_status_request",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.needs_external_app_action:
        return TurnPathDecision(
            path="external_app_action",
            reason="wiii_connect_external_app_action_request",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=frozenset(
                {
                    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
                    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                    WIII_CONNECT_LIST_ACTIONS_TOOL,
                }
            ),
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if signals.host_ui_navigation:
        return TurnPathDecision(
            path="host_ui_navigation",
            reason="routing_intent_host_ui_navigation",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_prefixes=HOST_ACTION_TOOL_PREFIXES + POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if _looks_casual_chat(signals):
        return TurnPathDecision(
            path="casual_chat",
            reason="plain_casual_chat",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if not _has_tool_or_output_signal(signals) and _looks_low_signal_noise(
        signals.normalized_query
    ):
        return TurnPathDecision(
            path="direct_prose",
            reason="low_signal_noise_no_tool",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.prefers_code_execution_lane and not signals.web_search_forced:
        return TurnPathDecision(
            path="code_execution",
            reason="code_or_analysis_belongs_to_code_studio",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.visual_force_tool and not signals.web_search_forced:
        allowed_tool_names = frozenset(signals.visual_required_tool_names)
        strict_visual_lane = (
            signals.visual_presentation_intent
            in {"article_figure", "chart_runtime", "code_studio_app", "artifact"}
            and bool(allowed_tool_names)
        )
        return TurnPathDecision(
            path="visual_generation",
            reason=f"visual_intent_{signals.visual_presentation_intent or 'unknown'}",
            force_tools=True,
            allow_all_tools=not strict_visual_lane,
            allowed_tool_names=allowed_tool_names,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if signals.needs_weather_lookup and not signals.web_search_forced:
        return TurnPathDecision(
            path="weather_lookup",
            reason="weather_current_conditions_request",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=WEATHER_LIVE_LOOKUP_TOOL_NAMES,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if signals.needs_maritime_search and not signals.web_search_forced:
        return TurnPathDecision(
            path="maritime_search",
            reason="maritime_domain_lookup",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=WEB_SEARCH_TOOL_NAMES,
            allow_rag_delegation=True,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if (
        signals.web_search_forced
        or signals.routing_intent == "web_search"
        or signals.needs_web_search
        or signals.needs_news_search
        or signals.needs_legal_search
    ):
        return TurnPathDecision(
            path="web_search",
            reason="explicit_or_detected_web_search",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=WEB_SEARCH_TOOL_NAMES,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES
            if signals.suppress_pointy_for_output
            else (),
            allow_agent_handoff=False,
        )

    if signals.needs_datetime:
        return TurnPathDecision(
            path="datetime_lookup",
            reason="datetime_request",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_names=frozenset({"tool_current_datetime"}),
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if signals.needs_lms_query:
        return TurnPathDecision(
            path="lms_query",
            reason="lms_query_intent",
            force_tools=True,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES
            if signals.suppress_pointy_for_output
            else (),
            allow_agent_handoff=False,
        )

    if signals.needs_direct_knowledge_search:
        return TurnPathDecision(
            path="knowledge_search",
            reason="explicit_internal_knowledge_lookup",
            force_tools=True,
            allow_rag_delegation=True,
            forbidden_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if signals.needs_character_memory_tool:
        return TurnPathDecision(
            path="direct_prose",
            reason="character_memory_tool_request",
            allow_all_tools=False,
            allowed_tool_names=CHARACTER_MEMORY_TOOL_NAMES,
            allow_agent_handoff=False,
        )

    if signals.suppress_pointy_for_output:
        return TurnPathDecision(
            path="direct_prose",
            reason="output_request_without_tool_lane",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    if signals.pointy_requested and not signals.suppress_pointy_for_output:
        return TurnPathDecision(
            path="pointy_guidance",
            reason="pointy_requested",
            force_tools=True,
            allow_all_tools=False,
            allowed_tool_prefixes=POINTY_TOOL_PREFIXES,
            allow_agent_handoff=False,
        )

    if str(signals.thinking_mode or "").strip().lower().startswith("analytical_"):
        return TurnPathDecision(
            path="analytical_text",
            reason="analytical_text_mode",
            allow_rag_delegation=False,
        )

    if signals.routing_intent in {
        "general",
        "off_topic",
        "social",
        "personal",
        "emotional",
        "identity",
        "selfhood",
    }:
        return TurnPathDecision(
            path="casual_chat",
            reason=f"routing_intent_{signals.routing_intent}",
            bind_tools=False,
            allow_all_tools=False,
            allow_agent_handoff=False,
        )

    return TurnPathDecision(
        path="direct_prose",
        reason="default_direct_prose_no_tool",
        bind_tools=False,
        allow_all_tools=False,
        allow_agent_handoff=False,
        allow_rag_delegation=False,
    )


def _looks_casual_chat(signals: TurnPathSignals) -> bool:
    normalized = str(signals.normalized_query or "").strip()
    if not normalized:
        return True

    tokens = [token for token in normalized.split() if token]
    if len(tokens) > 12:
        return False

    exact_short_turns = {
        "hi",
        "hello",
        "hey",
        "xin chao",
        "chao",
        "chao ban",
        "chao wiii",
        "xin chao wiii",
        "cam on",
        "cam on ban",
        "ok",
        "oke",
        "uh",
        "uhm",
    }
    if normalized in exact_short_turns:
        return True

    casual_cues = (
        "hom nay minh an",
        "hom nay toi an",
        "minh an com",
        "an com roi",
        "trua nay an",
        "toi an",
        "moi an",
        "dang an",
        "minh vua",
        "toi vua",
        "hom qua minh",
        "hom qua toi",
    )
    if any(cue in normalized for cue in casual_cues):
        return True

    if not _has_tool_or_output_signal(signals) and looks_short_social_followup_turn(
        normalized
    ):
        return True

    if _has_tool_or_output_signal(signals):
        return False

    greeting_prefixes = ("xin chao", "chao", "hello", "hi ")
    action_cues = (
        "tim",
        "tra cuu",
        "search",
        "tao",
        "viet",
        "ve",
        "mo phong",
        "phan tich",
        "giai thich",
        "huong dan",
        "chi vao",
        "click",
    )
    return normalized.startswith(greeting_prefixes) and not any(
        cue in normalized for cue in action_cues
    )


def _looks_low_signal_noise(normalized_query: str) -> bool:
    """Detect repeated paste/key noise so it stays off broad tool binding."""
    normalized = str(normalized_query or "").strip()
    if not normalized:
        return False

    compact = re.sub(r"\s+", "", normalized)
    if len(compact) < 48:
        return False

    if re.search(r"([a-z0-9])\1{31,}", compact):
        return True

    tokens = [token for token in normalized.split() if token]
    if any(len(token) >= 48 and len(set(token)) <= 4 for token in tokens):
        return True

    alnum = [char for char in compact if char.isalnum()]
    return len(alnum) >= 160 and (len(set(alnum)) / len(alnum)) <= 0.08


def _has_tool_or_output_signal(signals: TurnPathSignals) -> bool:
    return any(
        (
            signals.web_search_forced,
            signals.routing_intent == "web_search",
            signals.pointy_forced,
            signals.host_ui_navigation,
            signals.looks_document_preview,
            signals.looks_reasoning_safety_meta,
            signals.needs_external_connection_status,
            signals.needs_external_app_action,
            signals.needs_weather_lookup,
            signals.needs_web_search,
            signals.needs_datetime,
            signals.needs_news_search,
            signals.needs_legal_search,
            signals.needs_lms_query,
            signals.needs_direct_knowledge_search,
            signals.needs_character_memory_tool,
            signals.needs_analysis_tool,
            signals.prefers_code_execution_lane,
            signals.needs_maritime_search,
            signals.pointy_requested,
            signals.visual_force_tool,
        )
    )
