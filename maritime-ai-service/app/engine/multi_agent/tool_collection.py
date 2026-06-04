"""Tool collection and selection helpers for multi-agent graph.

Extracted from graph.py — collects available tools based on query intent,
user role, and domain context.
"""

from __future__ import annotations

from importlib import import_module
import logging
from types import SimpleNamespace
from typing import Any, Optional

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    filter_lms_authoring_capability_tools as _filter_lms_authoring_capability_tools,
    looks_uploaded_document_course_request as _contract_looks_uploaded_document_course_request,
    looks_uploaded_document_lesson_preview_request as _contract_looks_uploaded_document_lesson_preview_request,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.turn_path_governor import (
    TurnPathDecision,
    TurnPathSignals,
    resolve_turn_path_decision,
)
from app.engine.multi_agent.tool_policy_session import (
    build_tool_policy_session,
    filter_tools_for_policy_session,
    finalize_tool_policy_visible_tools,
    record_tool_policy_session,
)
from app.engine.multi_agent.external_app_action_runtime import (
    record_external_app_action_plan,
    resolve_external_app_action_plan,
)
from app.engine.multi_agent.wiii_connect_intent import (
    looks_wiii_connect_external_app_action_request,
    looks_wiii_connect_external_app_action_request_for_state,
    looks_wiii_connect_facebook_post_request,
    looks_wiii_connect_facebook_post_request_for_state,
    resolve_wiii_connect_status_provider_slugs,
)
from app.engine.tools.tool_capability_registry import (
    DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL,
    DOCUMENT_PREVIEW_CAPABILITY_NAMES,
    HOST_ACTION_PREFIX,
    POINTY_TOOL_PREFIX,
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
)
from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot

logger = logging.getLogger(__name__)

_CHARACTER_MEMORY_FACT_MARKERS: tuple[str, ...] = (
    "goi toi la",
    "goi minh la",
    "minh ten la",
    "my name is",
    "ten cua minh la",
    "ten cua toi la",
    "ten minh la",
    "ten toi la",
    "toi ten la",
)


def _load_attr(module_name: str, attr_name: str):
    """Load a helper lazily to reduce static tool-collection coupling."""
    return getattr(import_module(module_name), attr_name)


def _normalize_for_intent(query: str) -> str:
    return _load_attr("app.engine.multi_agent.direct_intent", "_normalize_for_intent")(query)


def _looks_uploaded_document_course_request(query: str) -> bool:
    return _contract_looks_uploaded_document_course_request(query)


def _looks_uploaded_document_lesson_preview_request(query: str) -> bool:
    return _contract_looks_uploaded_document_lesson_preview_request(query)


def _needs_web_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_web_search")(query)


def _needs_weather_lookup(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_weather_lookup")(query)


def _weather_provider_configured() -> bool:
    return bool(
        getattr(settings, "living_agent_enable_weather", False)
        and str(getattr(settings, "living_agent_weather_api_key", "") or "").strip()
    )


def _needs_datetime(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_datetime")(query)


def _needs_news_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_news_search")(query)


def _needs_legal_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_legal_search")(query)


def _needs_maritime_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_maritime_search")(query)


def _looks_wiii_connect_facebook_post_request(
    query: str,
    state: Optional[AgentState] = None,
) -> bool:
    """Detect explicit requests to create/publish a Facebook post via Wiii Connect."""

    if state is not None:
        return looks_wiii_connect_facebook_post_request_for_state(query, state)
    return looks_wiii_connect_facebook_post_request(query)


def _looks_wiii_connect_external_app_action_request(
    query: str,
    state: Optional[AgentState] = None,
) -> bool:
    """Detect explicit external app actions routed through Wiii Connect."""

    if state is not None:
        return looks_wiii_connect_external_app_action_request_for_state(query, state)
    return looks_wiii_connect_external_app_action_request(query)


def _wiii_connect_agent_ready_provider_slugs(
    state: Optional[AgentState],
    query: str,
) -> tuple[str, ...]:
    """Return connected external providers that may be exposed to the model."""

    if not getattr(settings, "enable_wiii_connect_composio", False):
        return ()
    try:
        snapshot = build_wiii_connect_snapshot(
            state=state if isinstance(state, dict) else {},
            query=query,
        )
        return snapshot.agent_ready_external_provider_slugs()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Wiii Connect readiness snapshot unavailable: %s", exc)
        return ()


def _wiii_connect_facebook_post_preview_capability() -> dict[str, Any]:
    """Synthetic preview-only action exposed to chat through the host-action pipe."""

    return {
        "name": WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
        "description": (
            "Create a Wiii Connect preview for a Facebook Page post. Use this "
            "only when the user explicitly asks Wiii to create, draft, publish, "
            "or post content to Facebook. Draft the `message` as the exact post "
            "copy. If the user attached an image, set `image_policy` to "
            "`use_latest_user_image`; do not place raw image bytes in the tool call. "
            "This is preview-first: the frontend will require an explicit user "
            "confirmation before the apply action posts to Facebook."
        ),
        "surface": "wiii_connect",
        "requires_confirmation": False,
        "mutates_state": False,
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The final Facebook post copy to preview.",
                },
                "image_policy": {
                    "type": "string",
                    "enum": ["none", "use_latest_user_image"],
                    "default": "none",
                },
            },
            "required": ["message"],
        },
    }


def _wiii_connect_facebook_post_direct_apply_capability() -> dict[str, Any]:
    """Synthetic direct publish action exposed through Wiii Connect policy."""

    return {
        "name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        "description": (
            "Publish a Facebook Page post through Wiii Connect for an explicit "
            "user request to post or publish to Facebook. Draft the `message` as "
            "the exact post copy. If the user says any content is acceptable "
            "or asks for a random post, write a short original safe post "
            "yourself instead of leaving `message` empty. If the user attached an image, set "
            "`image_policy` to `use_latest_user_image`; do not place raw image "
            "bytes in the tool call. The desktop host will resolve the connected "
            "account/page and call the audited Wiii Connect preview/apply gateway "
            "before Composio execution."
        ),
        "surface": "wiii_connect",
        "requires_confirmation": False,
        "mutates_state": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The final Facebook post copy to publish.",
                },
                "image_policy": {
                    "type": "string",
                    "enum": ["none", "use_latest_user_image"],
                    "default": "none",
                },
            },
            "required": ["message"],
        },
    }


def _needs_pointy(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_pointy")(query)


def _force_skills_from_state(state: Optional["AgentState"]) -> set[str]:
    """Extract `force_skills` từ AgentState (Wiii Pointy v2.8 @ mention).

    Returns empty set nếu không có. Force_skills được set qua ChatRequest
    → ChatContext → graph_context dict (NOT top-level state). Threading:

      ChatRequest.force_skills (Pydantic)
      → input_processor_context_runtime.py sets context.force_skills
      → chat_orchestrator_multi_agent.build_multi_agent_context_impl
        sets graph_context["force_skills"] = list(...)
      → graph_stream_runtime initial_state["context"] = graph_context
      → state["context"]["force_skills"]  ← READ FROM HERE

    v3.0 F3 fix (2026-05-06): previously read state["force_skills"]
    directly which is always None — caused chip rendering correctly but
    `[DIRECT] tools=0, force=False` log entries even when @ mention was
    typed. Now read from state["context"]["force_skills"] và fallback
    state["force_skills"] for backward compat.
    """
    if not state:
        return set()
    if not isinstance(state, dict):
        return set()
    force_skills = state.get("force_skills")
    if not force_skills:
        ctx = state.get("context")
        if isinstance(ctx, dict):
            force_skills = ctx.get("force_skills")
    if not force_skills:
        return set()
    if isinstance(force_skills, (list, tuple, set)):
        return {str(s).strip().lower() for s in force_skills if s}
    return set()


def _needs_analysis_tool(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_analysis_tool")(query)


def _needs_lms_query(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_lms_query")(query)


def _needs_direct_knowledge_search(query: str) -> bool:
    return _load_attr(
        "app.engine.multi_agent.direct_intent",
        "_needs_direct_knowledge_search",
    )(query)


def _looks_reasoning_safety_meta_turn(query: str) -> bool:
    try:
        normalized = _normalize_for_intent(query)
        return _load_attr(
            "app.engine.multi_agent.supervisor_runtime_support",
            "_looks_reasoning_safety_meta_turn",
        )(normalized)
    except Exception:
        return False


def _looks_wiii_pipeline_meta_turn(query: str) -> bool:
    try:
        normalized = _normalize_for_intent(query)
        return _load_attr(
            "app.engine.multi_agent.supervisor_runtime_support",
            "_looks_wiii_pipeline_meta_turn",
        )(normalized)
    except Exception:
        return False


def _looks_character_memory_tool_turn(query: str) -> bool:
    try:
        normalized = _normalize_for_intent(query)
    except Exception:
        normalized = str(query or "").lower().strip()
    if not normalized:
        return False
    if any(marker in normalized for marker in _CHARACTER_MEMORY_FACT_MARKERS):
        return True
    try:
        support = "app.engine.multi_agent.supervisor_runtime_support"
        return bool(
            _load_attr(support, "_looks_memory_write_turn")(normalized)
            or _load_attr(support, "_looks_session_memory_write_turn")(normalized)
        )
    except Exception:
        return False


def _infer_direct_thinking_mode(
    query: str,
    state: Optional[AgentState] = None,
    tool_names: list[str] | None = None,
) -> str:
    return _load_attr(
        "app.engine.multi_agent.direct_reasoning",
        "_infer_direct_thinking_mode",
    )(query, state or {}, tool_names or [])


def _should_strip_visual_tools_from_direct(query: str, visual_decision) -> bool:
    return _load_attr(
        "app.engine.multi_agent.direct_intent",
        "_should_strip_visual_tools_from_direct",
    )(query, visual_decision)


def resolve_visual_intent(query: str):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "resolve_visual_intent",
    )(query)


def filter_tools_for_visual_intent(tools, visual_decision, *, structured_visuals_enabled: bool):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "filter_tools_for_visual_intent",
    )(
        tools,
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )


def build_visual_tool_requirement(visual_decision, *, structured_visuals_enabled: bool):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "build_visual_tool_requirement",
    )(
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )


def required_visual_tool_names(visual_decision):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "required_visual_tool_names",
    )(visual_decision)


def visual_tool_capability_names(*, include_legacy: bool = True):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "visual_tool_capability_names",
    )(include_legacy=include_legacy)


def detect_visual_patch_request(query: str) -> bool:
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "detect_visual_patch_request",
    )(query)


def merge_quality_profile(base_profile, override_profile):
    return _load_attr(
        "app.engine.multi_agent.visual_intent_resolver",
        "merge_quality_profile",
    )(base_profile, override_profile)


def build_visual_tool_runtime_intent(*, query: str, visual_decision):
    return _load_attr(
        "app.engine.multi_agent.visual_runtime_metadata_contract",
        "build_visual_tool_runtime_intent",
    )(query=query, visual_decision=visual_decision)


def _log_visual_telemetry(event_name: str, **kwargs) -> None:
    return _load_attr(
        "app.engine.multi_agent.visual_events",
        "_log_visual_telemetry",
    )(event_name, **kwargs)


def filter_tools_for_role(tools, user_role: str):
    return _load_attr(
        "app.engine.tools.runtime_context",
        "filter_tools_for_role",
    )(tools, user_role)


def _should_strip_visual_tools_for_analytical_text_turn(
    query: str,
    visual_decision,
    *,
    thinking_mode: str,
) -> bool:
    """Keep analytical text turns on text/data tools unless visual intent is explicit."""
    if not str(thinking_mode or "").strip().lower().startswith("analytical_"):
        return False
    return getattr(visual_decision, "presentation_intent", "text") == "text"


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def _strip_visual_tool_capabilities(
    tools: list[Any],
    *,
    keep_names: tuple[str, ...] = (),
) -> list[Any]:
    """Drop known visual tools while preserving non-visual tool capabilities."""

    visual_names = set(visual_tool_capability_names(include_legacy=True))
    keep_name_set = set(keep_names)
    return [
        tool for tool in tools
        if _tool_name(tool) not in visual_names or _tool_name(tool) in keep_name_set
    ]


def _tools_matching_visual_requirement(tools: list[Any], visual_requirement: Any) -> list[Any]:
    return _tools_matching_names(
        tools,
        getattr(visual_requirement, "required_tool_names", ()) or (),
    )


def _tools_matching_names(tools: list[Any], tool_names: list[str] | tuple[str, ...]) -> list[Any]:
    required_names = [
        str(name or "").strip()
        for name in tool_names
        if str(name or "").strip()
    ]
    if not required_names:
        return []

    tools_by_name: dict[str, Any] = {}
    for tool in tools:
        name = _tool_name(tool)
        if name and name not in tools_by_name:
            tools_by_name[name] = tool

    return [tools_by_name[name] for name in required_names if name in tools_by_name]


_POINTY_OUTPUT_REQUEST_CUES: tuple[str, ...] = (
    "tao code",
    "viet code",
    "chay code",
    "code python",
    "code javascript",
    "tao visual",
    "ve visual",
    "tao minh hoa",
    "ve minh hoa",
    "ve bieu do",
    "tao bieu do",
    "mo phong",
    "simulation",
    "tao app",
    "tao widget",
    "tao artifact",
    "tao bai hoc",
    "tao bai giang",
    "tao khoa hoc",
    "tao course",
    "tao lesson",
    "create code",
    "write code",
    "run code",
    "create visual",
    "make visual",
    "draw chart",
    "create chart",
    "build app",
    "build widget",
    "create artifact",
    "create lesson",
    "generate lesson",
    "create course",
    "generate course",
    "course draft",
)


def _should_suppress_pointy_for_output_request(query: str) -> bool:
    """Keep Pointy out of code, visual, app, artifact, and simulation output turns."""

    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    return any(cue in normalized for cue in _POINTY_OUTPUT_REQUEST_CUES)


def _prefers_code_execution_lane_from_normalized(normalized_query: str) -> bool:
    return any(
        token in normalized_query
        for token in (
            "python",
            "code python",
            "chay python",
            "chay code",
            "viet code",
            "doan code",
            "sandbox",
            "pandas",
            "xlsx",
            "excel bang python",
            "matplotlib",
        )
    )


def _is_host_ui_navigation_route(state: Optional[AgentState]) -> bool:
    if not isinstance(state, dict):
        return False
    metadata = state.get("routing_metadata")
    if not isinstance(metadata, dict):
        return False
    return str(metadata.get("intent") or "").strip().lower() == "host_ui_navigation"


def _routing_intent(state: Optional[AgentState]) -> str:
    if not isinstance(state, dict):
        return ""
    metadata = state.get("routing_metadata")
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("intent") or "").strip().lower()


def _has_uploaded_document_context_state(state: Optional[AgentState]) -> bool:
    if not isinstance(state, dict):
        return False
    context = state.get("context")
    if not isinstance(context, dict):
        return False
    document_context = context.get("document_context")
    if not isinstance(document_context, dict):
        return False
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("markdown") or "").strip()
        for item in attachments
    )


def _looks_like_document_preview_request(query: str, state: Optional[AgentState]) -> bool:
    if not _has_uploaded_document_context_state(state):
        return False
    return _looks_uploaded_document_course_request(
        query
    ) or _looks_uploaded_document_lesson_preview_request(
        query
    )


def _looks_like_document_course_preview_request(query: str, state: Optional[AgentState]) -> bool:
    if not _has_uploaded_document_context_state(state):
        return False
    return _looks_uploaded_document_course_request(query)


def _document_preview_host_action_tools(tools: list[Any]) -> list[Any]:
    course_tools = [
        tool
        for tool in tools
        if _tool_name(tool).lower() == DOC_COURSE_HOST_ACTION_TOOL
    ]
    lesson_tools = [
        tool
        for tool in tools
        if _tool_name(tool).lower() == DOC_PREVIEW_HOST_ACTION_TOOL
    ]
    return course_tools + lesson_tools


def _preferred_document_preview_host_action_tools(
    tools: list[Any],
    query: str,
    state: Optional[AgentState],
) -> list[Any]:
    preferred = DOC_COURSE_HOST_ACTION_TOOL if (
        _looks_like_document_course_preview_request(query, state)
    ) else DOC_PREVIEW_HOST_ACTION_TOOL
    return [
        tool
        for tool in tools
        if _tool_name(tool).lower() == preferred
    ]


def _host_capability_tools_from_state(state: Optional[AgentState]) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    raw_caps = state.get("host_capabilities")
    if not raw_caps:
        context = state.get("context")
        if isinstance(context, dict):
            raw_caps = context.get("host_capabilities") or {}
    if not isinstance(raw_caps, dict):
        return []
    capabilities_tools = raw_caps.get("tools")
    if not isinstance(capabilities_tools, list):
        return []
    return [tool for tool in capabilities_tools if isinstance(tool, dict)]


def _safe_document_preview_capability_tools(
    capabilities_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Allow a preview-only bridge even if the global host-action flag is off.

    This fallback is intentionally narrow: it binds only the non-mutating LMS
    preview action needed for uploaded document -> teacher preview flows. Apply,
    publish, delete, grading, payment, and other host mutations remain disabled
    unless `enable_host_actions` is explicitly enabled.
    """
    return [
        tool
        for tool in capabilities_tools
        if str(tool.get("name") or "").strip().lower() in DOCUMENT_PREVIEW_CAPABILITY_NAMES
    ]


def _filter_host_capability_tools_for_external_action_plan(
    capabilities_tools: list[dict[str, Any]],
    external_action_plan: Any | None,
) -> list[dict[str, Any]]:
    """Remove host-declared actions owned by a backend Wiii Connect lane.

    OpenHuman keeps external app execution behind one toolkit owner. Wiii should
    do the same: when the direct Facebook publish lane is active, the backend
    Wiii Connect gateway owns preview/apply/result synthesis. The host can still
    expose other actions, but it must not generate a same-name host action tool
    that shadows the backend gateway tool.
    """

    if str(getattr(external_action_plan, "kind", "") or "") not in {
        "facebook_post_direct_apply",
        "provider_action",
    }:
        return capabilities_tools
    backend_owned_actions = {
        WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
        WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    }
    return [
        tool
        for tool in capabilities_tools
        if str(tool.get("name") or "").strip() not in backend_owned_actions
    ]


def _safe_intent_flag(fn, query: str, *, default: bool = False) -> bool:
    try:
        return bool(fn(query))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Turn-path signal failed for %s: %s", getattr(fn, "__name__", fn), exc)
        return default


def _default_visual_decision() -> Any:
    return SimpleNamespace(
        force_tool=False,
        mode="text",
        visual_type=None,
        preferred_tool=None,
        presentation_intent="text",
    )


def _safe_resolve_visual_decision(query: str) -> Any:
    try:
        return resolve_visual_intent(query)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Visual intent unavailable for turn path: %s", exc)
        return _default_visual_decision()


def _safe_build_visual_requirement(
    visual_decision: Any,
    *,
    structured_visuals_enabled: bool,
) -> Any:
    try:
        return build_visual_tool_requirement(
            visual_decision,
            structured_visuals_enabled=structured_visuals_enabled,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Visual tool requirement unavailable for turn path: %s", exc)
        return SimpleNamespace(
            force_tool=False,
            mode=str(getattr(visual_decision, "mode", "text") or "text"),
            presentation_intent=str(
                getattr(visual_decision, "presentation_intent", "text") or "text"
            ),
            required_tool_names=(),
        )


def _resolve_direct_turn_path_decision(
    *,
    query: str,
    state: Optional[AgentState],
    visual_decision: Any,
    visual_requirement: Any,
    thinking_mode: str,
    force_skills: set[str],
) -> TurnPathDecision:
    normalized_query = ""
    try:
        normalized_query = _normalize_for_intent(query)
    except Exception:  # noqa: BLE001
        normalized_query = str(query or "").lower().strip()

    host_ui_navigation = _is_host_ui_navigation_route(state)
    pointy_forced = "wiii-pointy" in force_skills
    pointy_requested = (
        pointy_forced
        or host_ui_navigation
        or _safe_intent_flag(_needs_pointy, query)
    )
    needs_weather_lookup = _safe_intent_flag(_needs_weather_lookup, query)
    weather_uses_web_fallback = needs_weather_lookup and not _weather_provider_configured()
    signals = TurnPathSignals(
        normalized_query=normalized_query,
        routing_intent=_routing_intent(state),
        thinking_mode=thinking_mode,
        force_skills=frozenset(force_skills),
        web_search_forced="web-search" in force_skills,
        pointy_forced=pointy_forced,
        host_ui_navigation=host_ui_navigation,
        looks_document_preview=_looks_like_document_preview_request(query, state),
        looks_reasoning_safety_meta=_looks_reasoning_safety_meta_turn(query),
        looks_wiii_pipeline_meta=_looks_wiii_pipeline_meta_turn(query),
        needs_external_connection_status=bool(
            resolve_wiii_connect_status_provider_slugs(query)
        ),
        needs_external_app_action=_looks_wiii_connect_external_app_action_request(
            query,
            state,
        ),
        needs_weather_lookup=needs_weather_lookup,
        needs_web_search=(
            _safe_intent_flag(_needs_web_search, query) or weather_uses_web_fallback
        ),
        needs_datetime=_safe_intent_flag(_needs_datetime, query),
        needs_news_search=_safe_intent_flag(_needs_news_search, query),
        needs_legal_search=_safe_intent_flag(_needs_legal_search, query),
        needs_lms_query=_safe_intent_flag(_needs_lms_query, query),
        needs_direct_knowledge_search=_safe_intent_flag(
            _needs_direct_knowledge_search,
            query,
        ),
        needs_character_memory_tool=_looks_character_memory_tool_turn(query),
        needs_analysis_tool=_safe_intent_flag(_needs_analysis_tool, query),
        prefers_code_execution_lane=_prefers_code_execution_lane_from_normalized(
            normalized_query
        ),
        needs_maritime_search=_safe_intent_flag(_needs_maritime_search, query),
        pointy_requested=pointy_requested,
        suppress_pointy_for_output=_should_suppress_pointy_for_output_request(query),
        visual_force_tool=bool(getattr(visual_requirement, "force_tool", False)),
        visual_mode=str(
            getattr(visual_requirement, "mode", None)
            or getattr(visual_decision, "mode", "")
            or ""
        ),
        visual_presentation_intent=str(
            getattr(visual_requirement, "presentation_intent", "") or ""
        ),
        visual_required_tool_names=tuple(
            getattr(visual_requirement, "required_tool_names", ()) or ()
        ),
    )
    return resolve_turn_path_decision(signals)


def _record_turn_path_decision(
    state: Optional[AgentState],
    decision: TurnPathDecision,
) -> None:
    if isinstance(state, dict):
        state["_turn_path_decision"] = decision.to_metadata()


def _record_empty_tool_policy_session(
    *,
    state: Optional[AgentState],
    decision: TurnPathDecision,
    query: str,
    user_role: str,
) -> None:
    if not isinstance(state, dict):
        return
    record_tool_policy_session(
        state,
        build_tool_policy_session(
            decision=decision,
            state=state,
            query=query,
            user_role=user_role,
            candidate_tool_names=(),
        ),
    )


def ensure_direct_turn_policy_metadata(
    *,
    query: str,
    state: Optional[AgentState],
    user_role: str = "student",
    record_empty_policy: bool = False,
) -> TurnPathDecision | None:
    """Record direct-turn path facts even when no tool loop is entered.

    Direct fast paths and intentionally tool-less chat turns can bypass
    ``_collect_direct_tools``. Without this baseline, the public runtime ledger
    cannot explain why no tools were visible. This helper records the same
    governor decision used by the tool collector and, when requested, an empty
    policy session for a final no-tool turn.
    """

    if not isinstance(state, dict):
        return None

    force_skills = _force_skills_from_state(state)
    structured_visuals_enabled = getattr(settings, "enable_structured_visuals", False)
    visual_decision = _safe_resolve_visual_decision(query)
    visual_requirement = _safe_build_visual_requirement(
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )
    try:
        thinking_mode = _infer_direct_thinking_mode(query, state, [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Thinking mode unavailable for baseline turn path: %s", exc)
        thinking_mode = ""

    decision = _resolve_direct_turn_path_decision(
        query=query,
        state=state,
        visual_decision=visual_decision,
        visual_requirement=visual_requirement,
        thinking_mode=thinking_mode,
        force_skills=force_skills,
    )
    _record_turn_path_decision(state, decision)
    if record_empty_policy and not isinstance(state.get("_tool_policy_session"), dict):
        _record_empty_tool_policy_session(
            state=state,
            decision=decision,
            query=query,
            user_role=user_role,
        )
    return decision


def _apply_tool_policy_session(
    tools: list[Any],
    *,
    state: Optional[AgentState],
    decision: TurnPathDecision,
    query: str,
    user_role: str,
) -> list[Any]:
    if not isinstance(state, dict):
        return tools
    session = build_tool_policy_session(
        decision=decision,
        state=state,
        query=query,
        user_role=user_role,
        candidate_tool_names=[_tool_name(tool) for tool in tools],
    )
    record_tool_policy_session(state, session)
    filtered = filter_tools_for_policy_session(
        tools,
        session,
        tool_name=_tool_name,
    )
    finalize_tool_policy_visible_tools(state, filtered, tool_name=_tool_name)
    return filtered


def _should_use_no_tools_for_direct_prose(
    *,
    query: str,
    state: Optional[AgentState],
    visual_decision: Any,
    force_tools: bool,
) -> bool:
    """Keep plain prose direct turns off the heavy tool-schema path."""
    if _looks_reasoning_safety_meta_turn(query):
        return True
    if _looks_wiii_pipeline_meta_turn(query):
        return True
    if force_tools:
        return False
    if _looks_character_memory_tool_turn(query):
        return False
    if _routing_intent(state) not in {
        "general",
        "off_topic",
        "social",
        "personal",
        "emotional",
        "identity",
        "selfhood",
    }:
        return False
    if getattr(visual_decision, "force_tool", False):
        return False
    return not (
        _needs_web_search(query)
        or _needs_datetime(query)
        or _needs_news_search(query)
        or _needs_legal_search(query)
        or _needs_lms_query(query)
        or _needs_direct_knowledge_search(query)
    )


def _host_action_tools(tools: list[Any]) -> list[Any]:
    """Filter tools to those allowed during host_ui_navigation routing.

    Sprint 222 host_action__ tools are mutating capabilities the host
    page exposes (LMS embed, dashboards). Wiii Pointy v3.0 (2026-05-06)
    adds pointy tools to this allowlist because pointy is the primary
    way Wiii answers "where is X" / "click Y" questions on STANDALONE
    Wiii desktop / Wiii web — there is no host_action bridge there.
    """
    allowed_prefixes = (HOST_ACTION_PREFIX, POINTY_TOOL_PREFIX)
    return [tool for tool in tools if _tool_name(tool).startswith(allowed_prefixes)]


def _collect_direct_tools(query: str, user_role: str = "student", state: Optional[AgentState] = None):
    """Collect tools for direct response node and determine forced calling.

    Sprint 154: Extracted from direct_response_node.

    Returns:
        tuple: (tools_list, llm_with_tools_factory, llm_auto_factory, force_tools)
            - tools_list: List of available tools
            - force_tools: Whether to force tool calling (intent detected)
    """
    force_skills = _force_skills_from_state(state)
    structured_visuals_enabled = getattr(settings, "enable_structured_visuals", False)
    visual_decision = _safe_resolve_visual_decision(query)
    visual_requirement = _safe_build_visual_requirement(
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )
    try:
        thinking_mode = _infer_direct_thinking_mode(query, state, [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Thinking mode unavailable for turn path: %s", exc)
        thinking_mode = ""
    turn_path_decision = _resolve_direct_turn_path_decision(
        query=query,
        state=state,
        visual_decision=visual_decision,
        visual_requirement=visual_requirement,
        thinking_mode=thinking_mode,
        force_skills=force_skills,
    )
    _record_turn_path_decision(state, turn_path_decision)
    if not turn_path_decision.bind_tools:
        _record_empty_tool_policy_session(
            state=state,
            decision=turn_path_decision,
            query=query,
            user_role=user_role,
        )
        return [], False

    ready_wiii_connect_providers: tuple[str, ...] = ()
    external_action_plan: Any | None = None
    try:
        ready_wiii_connect_providers = _wiii_connect_agent_ready_provider_slugs(
            state,
            query,
        )
        external_action_plan = resolve_external_app_action_plan(
            query=query,
            state=state,
            ready_provider_slugs=ready_wiii_connect_providers,
        )
        record_external_app_action_plan(state, external_action_plan)
    except Exception as _e:
        logger.debug("[DIRECT] Wiii Connect action plan unavailable: %s", _e)

    _direct_tools = []
    try:
        if settings.enable_character_tools:
            get_character_tools = _load_attr(
                "app.engine.character.character_tools",
                "get_character_tools",
            )
            _direct_tools = get_character_tools()
    except Exception as _e:
        logger.debug("[DIRECT] Character tools unavailable: %s", _e)

    # WAVE-001: code_execution, browser_sandbox removed from direct.
    # These capabilities now live exclusively in code_studio_agent.
    # Boundary enforced at tool-binding level (LLM-first, not keyword).

    try:
        tool_current_datetime = _load_attr(
            "app.engine.tools.utility_tools",
            "tool_current_datetime",
        )
        tool_web_search = _load_attr(
            "app.engine.tools.web_search_tools",
            "tool_web_search",
        )
        tool_search_news = _load_attr(
            "app.engine.tools.web_search_tools",
            "tool_search_news",
        )
        tool_search_legal = _load_attr(
            "app.engine.tools.web_search_tools",
            "tool_search_legal",
        )
        tool_search_maritime = _load_attr(
            "app.engine.tools.web_search_tools",
            "tool_search_maritime",
        )
        tool_fetch_url = _load_attr(
            "app.engine.tools.web_fetch_tool",
            "tool_fetch_url",
        )
        # Phase 35 — intent-aware tool pruning. NVIDIA DeepSeek V4 with 8 tools
        # in prompt regularly times out (>45s). Bind only what query actually
        # needs. Always include datetime + general web_search + fetch_url
        # (cheap escalation). Specialty tools only when intent matches.
        _direct_tools = [
            *_direct_tools,
            tool_current_datetime,
            tool_web_search,
            tool_fetch_url,
        ]
        if turn_path_decision.path == "weather_lookup" and _weather_provider_configured():
            tool_current_weather = _load_attr(
                "app.engine.tools.utility_tools",
                "tool_current_weather",
            )
            _direct_tools.append(tool_current_weather)
        # v2.8: force-bind via @web-search mention overrides news/legal gates.
        web_search_forced = "web-search" in force_skills
        if _needs_news_search(query) or web_search_forced:
            _direct_tools.append(tool_search_news)
        if _needs_legal_search(query) or web_search_forced:
            _direct_tools.append(tool_search_legal)
        # Wiii Pointy — bind cursor-control tools either via keyword
        # intent (`_needs_pointy`) HOẶC explicit `@wiii-pointy` mention
        # (force_skills override, v2.8). Force-bind bypasses keyword
        # gates → user controls invocation explicitly.
        pointy_forced = "wiii-pointy" in force_skills
        host_ui_navigation = _is_host_ui_navigation_route(state)
        pointy_requested = pointy_forced or host_ui_navigation or _needs_pointy(query)
        if pointy_requested and not _should_suppress_pointy_for_output_request(query):
            try:
                # v9.0 F18 (2026-05-07) — SeeAct enum-constrained tool.
                # Build tool_pointy_show with `selector: Literal[<inventory>]`
                # so AI is JSON-schema-forced to pick from current page's
                # available_targets. NVIDIA DeepSeek + OpenAI compatible
                # APIs honor enum constraint at sampling time → kills
                # hallucinated id failure mode (14-43% in v8.3 → ~5-10% target).
                make_enum_tool = _load_attr(
                    "app.engine.tools.pointy_tools",
                    "make_pointy_show_with_enum",
                )
                extract_pairs = _load_attr(
                    "app.engine.tools.pointy_tools",
                    "extract_inventory_pairs_from_state",
                )
                inventory_pairs = extract_pairs(state) if state else []
                if inventory_pairs:
                    tool_pointy_show = make_enum_tool(inventory_pairs)
                    logger.info(
                        "[DIRECT] Pointy tool enum-bound (%d ids w/ labels): %s",
                        len(inventory_pairs),
                        ",".join(
                            f"{tid}={lbl[:24]!r}" for tid, lbl in inventory_pairs[:3]
                        ),
                    )
                else:
                    # Fallback: static tool (no inventory available).
                    tool_pointy_show = _load_attr(
                        "app.engine.tools.pointy_tools", "tool_pointy_show"
                    )
                tool_pointy_clear = _load_attr(
                    "app.engine.tools.pointy_tools", "tool_pointy_clear"
                )
                tool_pointy_inventory = _load_attr(
                    "app.engine.tools.pointy_tools", "tool_pointy_inventory"
                )
                _direct_tools.extend(
                    [tool_pointy_show, tool_pointy_clear, tool_pointy_inventory]
                )
                if pointy_forced:
                    logger.info("[DIRECT] Pointy tools force-bound via @wiii-pointy mention")
            except Exception as _e:
                logger.debug("[DIRECT] Pointy tools unavailable: %s", _e)
        # Maritime is the default domain — bind tool only when query mentions
        # maritime/COLREGs/SOLAS/ship terminology so generic queries stay light.
        try:
            if _needs_maritime_search(query):
                _direct_tools.append(tool_search_maritime)
        except Exception:  # noqa: BLE001
            logger.debug("[DIRECT] Maritime search intent unavailable")
    except Exception as _e:
        logger.debug("[DIRECT] Utility/web search tools unavailable: %s", _e)

    # Knowledge search is opt-in only for explicit retrieval turns.
    if _needs_direct_knowledge_search(query):
        try:
            tool_knowledge_search = _load_attr(
                "app.engine.tools.rag_tools",
                "tool_knowledge_search",
            )
            _direct_tools.append(tool_knowledge_search)
        except Exception as _e:
            logger.debug("[DIRECT] Knowledge search tool unavailable: %s", _e)

    # P3 Agent-as-Tool: RAG knowledge delegation.
    # When tool_knowledge_search is NOT already bound, provide the agent-level
    # delegation tool so the LLM can still query domain knowledge when needed.
    _bound_tool_names = {
        str(getattr(t, "name", "") or getattr(t, "__name__", ""))
        for t in _direct_tools
    }
    if (
        turn_path_decision.allow_rag_delegation
        and "tool_knowledge_search" not in _bound_tool_names
    ):
        try:
            tool_rag_knowledge = _load_attr(
                "app.engine.tools.agent_tools",
                "RAG_KNOWLEDGE_TOOL",
            )
            _direct_tools.append(tool_rag_knowledge)
        except Exception as _e:
            logger.debug("[DIRECT] RAG agent tool unavailable: %s", _e)

    # Sprint 175: LMS tools (role-aware)
    try:
        if settings.enable_lms_integration:
            get_all_lms_tools = _load_attr(
                "app.engine.tools.lms_tools",
                "get_all_lms_tools",
            )
            _direct_tools.extend(get_all_lms_tools(role="student"))
    except Exception as _e:
        logger.debug("[DIRECT] LMS tools unavailable: %s", _e)

    try:
        if state is not None:
            capabilities_tools = _host_capability_tools_from_state(state)
            state_context = state.get("context") if isinstance(state.get("context"), dict) else {}
            capabilities_tools = _filter_lms_authoring_capability_tools(
                capabilities_tools,
                state=state,
                ctx=state_context,
            )
            capabilities_tools = _filter_host_capability_tools_for_external_action_plan(
                capabilities_tools,
                external_action_plan,
            )
            host_actions_enabled = getattr(settings, "enable_host_actions", False)
            safe_doc_preview_fallback = (
                not host_actions_enabled
                and _looks_like_document_preview_request(query, state)
            )
            if safe_doc_preview_fallback:
                capabilities_tools = _safe_document_preview_capability_tools(
                    capabilities_tools
                )
            if capabilities_tools and (host_actions_enabled or safe_doc_preview_fallback):
                generate_host_action_tools = _load_attr(
                    "app.engine.context.action_tools",
                    "generate_host_action_tools",
                )

                _direct_tools.extend(
                    generate_host_action_tools(
                        capabilities_tools,
                        user_role,
                        event_bus_id=state.get("_event_bus_id") or state.get("session_id") or "",
                        approval_context={
                            "query": query,
                            "host_action_feedback": (
                                state.get("_host_action_control_feedback")
                                or ((state.get("context") or {}).get("host_action_feedback") or {})
                            ),
                        },
                    )
                )
    except Exception as _e:
        logger.debug("[DIRECT] Host action tools unavailable: %s", _e)

    try:
        if external_action_plan is not None and external_action_plan.ready:
            scoped_wiii_connect_providers = (
                (external_action_plan.provider_slug,)
                if external_action_plan.provider_slug
                else ready_wiii_connect_providers
            )
            if external_action_plan.kind == "provider_action":
                try:
                    make_list_actions_tool = _load_attr(
                        "app.engine.tools.wiii_connect_tools",
                        "make_wiii_connect_list_actions_tool",
                    )
                    make_delegate_tool = _load_attr(
                        "app.engine.tools.wiii_connect_tools",
                        "make_wiii_connect_delegate_to_integration_tool",
                    )
                    _direct_tools.append(
                        make_list_actions_tool(
                            state=state if isinstance(state, dict) else {},
                            allowed_provider_slugs=scoped_wiii_connect_providers,
                            allowed_action_slugs_by_provider=(
                                external_action_plan.action_allowlists_by_provider
                            ),
                        )
                    )
                    _direct_tools.append(
                        make_delegate_tool(
                            state=state if isinstance(state, dict) else {},
                            allowed_provider_slugs=scoped_wiii_connect_providers,
                            allowed_action_slugs_by_provider=(
                                external_action_plan.action_allowlists_by_provider
                            ),
                        )
                    )
                except Exception as backend_tool_error:  # noqa: BLE001
                    logger.debug(
                        "[DIRECT] Backend Wiii Connect integration delegate unavailable: %s",
                        backend_tool_error,
                    )
            if external_action_plan.kind == "facebook_post_direct_apply":
                try:
                    make_backend_facebook_tool = _load_attr(
                        "app.engine.tools.wiii_connect_tools",
                        "make_wiii_connect_facebook_post_direct_apply_tool",
                    )
                    _direct_tools.append(
                        make_backend_facebook_tool(
                            state=state if isinstance(state, dict) else {},
                        )
                    )
                except Exception as backend_tool_error:  # noqa: BLE001
                    logger.debug(
                        "[DIRECT] Backend Wiii Connect Facebook tool unavailable: %s",
                        backend_tool_error,
                    )
    except Exception as _e:
        logger.debug("[DIRECT] Wiii Connect Facebook post tool unavailable: %s", _e)

    if _is_host_ui_navigation_route(state):
        scoped_host_tools = _host_action_tools(_direct_tools)
        scoped_host_tools = _apply_tool_policy_session(
            scoped_host_tools,
            state=state,
            decision=turn_path_decision,
            query=query,
            user_role=user_role,
        )
        return scoped_host_tools, bool(scoped_host_tools)

    if _looks_like_document_preview_request(query, state):
        preview_tools = _preferred_document_preview_host_action_tools(_direct_tools, query, state)
        if preview_tools:
            logger.info(
                "[DIRECT] Forcing LMS document preview host action for uploaded document context"
            )
            preview_tools = _apply_tool_policy_session(
                preview_tools[:1],
                state=state,
                decision=turn_path_decision,
                query=query,
                user_role=user_role,
            )
            return preview_tools[:1], True

    if _looks_reasoning_safety_meta_turn(query) and _routing_intent(state) in {
        "general",
        "off_topic",
        "personal",
        "social",
    }:
        _record_empty_tool_policy_session(
            state=state,
            decision=turn_path_decision,
            query=query,
            user_role=user_role,
        )
        return [], False

    web_search_forced = "web-search" in force_skills

    # Structured visuals re-enable lightweight inline diagram/chart tools for direct,
    # but keep heavy artifact/file generation inside code_studio_agent.
    if getattr(settings, "enable_structured_visuals", False):
        try:
            get_chart_tools = _load_attr(
                "app.engine.tools.chart_tools",
                "get_chart_tools",
            )

            _direct_tools.extend(get_chart_tools())
        except Exception as _e:
            logger.debug("[DIRECT] Chart tools unavailable: %s", _e)

    # Sprint 229d: Re-add visual tools to direct agent so it can generate
    # rich visuals (comparison, process, quiz, etc.) without routing to code_studio.
    # This fixes the issue where direct agent writes raw JSON in widget blocks.
    try:
        get_visual_tools = _load_attr(
            "app.engine.tools.visual_tools",
            "get_visual_tools",
        )

        _direct_tools.extend(get_visual_tools())
    except Exception as _e:
        logger.debug("[DIRECT] Visual tools unavailable: %s", _e)

    normalized_query = _normalize_for_intent(query)
    _prefers_code_execution_lane = _prefers_code_execution_lane_from_normalized(
        normalized_query
    )
    _direct_tools = filter_tools_for_role(_direct_tools, user_role)
    _direct_tools = filter_tools_for_visual_intent(
        _direct_tools,
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )
    if web_search_forced:
        # Explicit @web-search is a stronger user contract than visual intent.
        # Research prompts often mention charts, pipelines, or summaries; those
        # words must not narrow the tool bundle to visual generation.
        _direct_tools = _strip_visual_tool_capabilities(_direct_tools)
    if _should_strip_visual_tools_from_direct(query, visual_decision):
        _direct_tools = _strip_visual_tool_capabilities(_direct_tools)
    if _should_strip_visual_tools_for_analytical_text_turn(
        query,
        visual_decision,
        thinking_mode=thinking_mode,
    ):
        _direct_tools = _strip_visual_tool_capabilities(_direct_tools)
    _direct_tools = _apply_tool_policy_session(
        _direct_tools,
        state=state,
        decision=turn_path_decision,
        query=query,
        user_role=user_role,
    )
    # Clear inline article/chart requests should stay tightly on the visual lane.
    # If there is no competing web/legal/news/datetime/LMS intent, bind only the
    # preferred visual tool so the first tool call is deterministic and the
    # direct lane does not waste latency on unrelated tool options.
    if (
        visual_requirement.force_tool
        and visual_requirement.required_tool_names
        and visual_requirement.presentation_intent in {"article_figure", "chart_runtime"}
        and not (
            _needs_web_search(query)
            or _needs_datetime(query)
            or _needs_news_search(query)
            or _needs_legal_search(query)
            or _needs_lms_query(query)
            or web_search_forced
        )
    ):
        preferred_tools = _tools_matching_visual_requirement(_direct_tools, visual_requirement)
        if preferred_tools:
            _direct_tools = preferred_tools
    _needs_visual_tool = (
        not _prefers_code_execution_lane
        and
        visual_requirement.force_tool
        and visual_requirement.mode in {"template", "inline_html", "app", "mermaid"}
        and (
            visual_requirement.presentation_intent in {"article_figure", "chart_runtime"}
            or not _needs_analysis_tool(query)
        )
    )
    if _needs_visual_tool:
        _log_visual_telemetry(
            "visual_requested",
            mode=visual_decision.mode,
            visual_type=visual_decision.visual_type,
            user_role=user_role,
            query=query[:180],
        )
    force_tools = bool(_direct_tools) and (
        turn_path_decision.force_tools
        or
        web_search_forced
        or _needs_web_search(query) or _needs_datetime(query)
        or _needs_news_search(query) or _needs_legal_search(query)
        or _needs_lms_query(query) or _needs_visual_tool
    )

    if _should_use_no_tools_for_direct_prose(
        query=query,
        state=state,
        visual_decision=visual_decision,
        force_tools=force_tools,
    ):
        _record_empty_tool_policy_session(
            state=state,
            decision=turn_path_decision,
            query=query,
            user_role=user_role,
        )
        return [], False

    # Agent handoff tool (Phase 3)
    if (
        turn_path_decision.allow_agent_handoff
        and getattr(settings, "enable_agent_handoffs", True)
        and not force_tools
    ):
        try:
            from app.engine.multi_agent.handoff_tools import handoff_to_agent
            _direct_tools.append(handoff_to_agent)
        except Exception:
            pass

    finalize_tool_policy_visible_tools(state, _direct_tools, tool_name=_tool_name)
    return _direct_tools, force_tools


def _collect_code_studio_tools(query: str, user_role: str = "student"):
    """Collect tools for the code studio capability lane."""
    _tools = []

    try:
        if settings.enable_code_execution and user_role == "admin":
            get_code_execution_tools = _load_attr(
                "app.engine.tools.code_execution_tools",
                "get_code_execution_tools",
            )

            _tools.extend(get_code_execution_tools())
    except Exception as _e:
        logger.debug("[CODE_STUDIO] Code execution tools unavailable: %s", _e)

    try:
        get_chart_tools = _load_attr(
            "app.engine.tools.chart_tools",
            "get_chart_tools",
        )

        _tools.extend(get_chart_tools())
    except Exception as _e:
        logger.debug("[CODE_STUDIO] Chart tools unavailable: %s", _e)

    try:
        get_visual_tools = _load_attr(
            "app.engine.tools.visual_tools",
            "get_visual_tools",
        )

        _tools.extend(get_visual_tools())
    except Exception as _e:
        logger.debug("[CODE_STUDIO] Visual tools unavailable: %s", _e)

    try:
        get_output_generation_tools = _load_attr(
            "app.engine.tools.output_generation_tools",
            "get_output_generation_tools",
        )

        _tools.extend(get_output_generation_tools())
    except Exception as _e:
        logger.debug("[CODE_STUDIO] Output generation tools unavailable: %s", _e)

    try:
        if (
            user_role == "admin"
            and settings.enable_browser_agent
            and settings.enable_privileged_sandbox
            and settings.sandbox_provider == "opensandbox"
            and settings.sandbox_allow_browser_workloads
        ):
            get_browser_sandbox_tools = _load_attr(
                "app.engine.tools.browser_sandbox_tools",
                "get_browser_sandbox_tools",
            )

            _tools.extend(get_browser_sandbox_tools())
    except Exception as _e:
        logger.debug("[CODE_STUDIO] Browser sandbox tools unavailable: %s", _e)

    visual_decision = resolve_visual_intent(query)
    structured_visuals_enabled = getattr(settings, "enable_structured_visuals", False)
    visual_requirement = build_visual_tool_requirement(
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )
    required_tool_names = _code_studio_required_tool_names(query, user_role)
    _tools = filter_tools_for_role(_tools, user_role)
    _tools = filter_tools_for_visual_intent(
        _tools,
        visual_decision,
        structured_visuals_enabled=structured_visuals_enabled,
    )

    # Clear app/artifact requests should not drift across a broad tool bundle.
    # Once the resolver has locked a preferred tool for the studio lane, we
    # narrow the bound tools to that target so the first tool call is
    # deterministic and faster to emit in streaming.
    if (
        visual_requirement.force_tool
        and visual_requirement.required_tool_names
        and visual_requirement.presentation_intent in {"code_studio_app", "artifact"}
    ):
        preferred_tools = _tools_matching_visual_requirement(_tools, visual_requirement)
        required_tools = _tools_matching_names(_tools, required_tool_names)
        narrowed_tools = [*required_tools]
        seen_names = {_tool_name(tool) for tool in narrowed_tools}
        for tool in preferred_tools:
            tool_name = _tool_name(tool)
            if tool_name in seen_names:
                continue
            narrowed_tools.append(tool)
            if tool_name:
                seen_names.add(tool_name)
        if narrowed_tools:
            _tools = narrowed_tools

    force_tools = bool(_tools)
    return _tools, force_tools


def _needs_browser_snapshot(query: str) -> bool:
    """Detect requests that should prefer the browser sandbox over plain web search."""
    lowered = query.lower()
    normalized = _normalize_for_intent(query)
    has_url = "http://" in lowered or "https://" in lowered or "www." in lowered
    screenshot_signal = any(
        signal in normalized
        for signal in (
            "anh chup man hinh",
            "chup man hinh",
            "screenshot",
            "browser sandbox",
            "duyet web",
            "xem trang",
            "mo trang",
            "open page",
        )
    )
    inspect_signal = has_url and any(
        signal in normalized
        for signal in (
            "mo",
            "open",
            "ghe qua",
            "vao",
            "noi gi",
            "hien thi gi",
            "render",
            "trang do",
        )
    )
    return screenshot_signal or inspect_signal


def _direct_required_tool_names(query: str, user_role: str = "student") -> list[str]:
    """Return must-have direct tools inferred from the current query."""
    required: list[str] = []
    normalized = _normalize_for_intent(query)
    visual_decision = resolve_visual_intent(query)

    if _needs_weather_lookup(query):
        if _weather_provider_configured():
            required.extend(
                [
                    "tool_current_weather",
                    "tool_web_search",
                    "tool_current_datetime",
                ]
            )
        else:
            required.append("tool_web_search")
    if _needs_datetime(query):
        required.append("tool_current_datetime")
    if _needs_news_search(query):
        required.append("tool_search_news")
    if _needs_legal_search(query):
        required.append("tool_search_legal")
    if _needs_web_search(query) and not _needs_weather_lookup(query):
        if any(
            signal in normalized
            for signal in ("imo", "shipping", "maritime", "hang hai", "vinamarine", "cuc hang hai")
        ):
            required.append("tool_search_maritime")
        else:
            required.append("tool_web_search")
    if _needs_direct_knowledge_search(query):
        required.append("tool_knowledge_search")
    if _needs_maritime_search(query):
        required.append("tool_search_maritime")
    if _looks_wiii_connect_facebook_post_request(query):
        required.append(WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL)
    elif _looks_wiii_connect_external_app_action_request(query):
        required.append(WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL)
    # WAVE-001: browser_snapshot and execute_python removed from direct.
    # These capabilities now live exclusively in code_studio_agent.

    if visual_decision.force_tool and not _needs_analysis_tool(query):
        required.extend(required_visual_tool_names(visual_decision))

    deduped: list[str] = []
    for tool_name in required:
        if tool_name not in deduped:
            deduped.append(tool_name)
    return deduped


def _code_studio_required_tool_names(query: str, user_role: str = "student") -> list[str]:
    """Return must-have tools inferred for the code studio capability."""
    normalized = _normalize_for_intent(query)
    required: list[str] = []
    visual_decision = resolve_visual_intent(query)

    if any(token in normalized for token in ("html", "landing page", "website", "web app", "microsite")):
        required.append("tool_generate_html_file")

    if any(token in normalized for token in ("excel", "xlsx", "spreadsheet")):
        required.append("tool_generate_excel_file")

    if any(token in normalized for token in ("word", "docx", "report", "memo", "proposal")):
        required.append("tool_generate_word_document")

    if user_role == "admin" and settings.enable_code_execution and _needs_analysis_tool(query):
        required.append("tool_execute_python")

    if (
        user_role == "admin"
        and settings.enable_browser_agent
        and settings.enable_privileged_sandbox
        and settings.sandbox_provider == "opensandbox"
        and settings.sandbox_allow_browser_workloads
        and _needs_browser_snapshot(query)
    ):
        required.append("tool_browser_snapshot_url")

    if visual_decision.force_tool:
        required.extend(required_visual_tool_names(visual_decision))

    deduped: list[str] = []
    for tool_name in required:
        if tool_name not in deduped:
            deduped.append(tool_name)
    return deduped


def _build_visual_tool_runtime_metadata(state: dict, query: str) -> dict[str, Any] | None:
    """Provide visual intent metadata and patch defaults to the tool runtime layer."""
    visual_decision = resolve_visual_intent(query)
    runtime_intent = build_visual_tool_runtime_intent(
        query=query,
        visual_decision=visual_decision,
    )
    metadata: dict[str, Any] = runtime_intent.to_metadata() if runtime_intent else {}

    if not detect_visual_patch_request(query):
        return metadata or None

    visual_ctx = ((state.get("context") or {}).get("visual_context") or {})
    if not isinstance(visual_ctx, dict):
        visual_ctx = {}

    preferred_session_id = str(visual_ctx.get("last_visual_session_id") or "").strip()
    preferred_visual_type = str(visual_ctx.get("last_visual_type") or "").strip()

    if not preferred_session_id:
        active_items = visual_ctx.get("active_inline_visuals")
        if isinstance(active_items, list):
            for item in active_items:
                if not isinstance(item, dict):
                    continue
                preferred_session_id = str(item.get("visual_session_id") or item.get("session_id") or "").strip()
                preferred_visual_type = preferred_visual_type or str(item.get("type") or "").strip()
                if preferred_session_id:
                    break

    code_studio_ctx = ((state.get("context") or {}).get("code_studio_context") or {})
    if not isinstance(code_studio_ctx, dict):
        code_studio_ctx = {}

    active_code_session = code_studio_ctx.get("active_session")
    if not isinstance(active_code_session, dict):
        active_code_session = {}
    requested_code_view = str(code_studio_ctx.get("requested_view") or "").strip().lower()
    if requested_code_view not in {"code", "preview"}:
        requested_code_view = ""

    prefers_code_studio_session = visual_decision.presentation_intent in {"code_studio_app", "artifact"}
    preferred_code_session_id = str(active_code_session.get("session_id") or "").strip()
    preferred_code_lane = str(active_code_session.get("studio_lane") or "").strip()
    preferred_code_artifact_kind = str(active_code_session.get("artifact_kind") or "").strip()
    preferred_code_quality = str(
        active_code_session.get("quality_profile")
        or active_code_session.get("qualityProfile")
        or ""
    ).strip()
    try:
        preferred_code_active_version = max(0, int(active_code_session.get("active_version") or 0))
    except Exception:
        preferred_code_active_version = 0

    if prefers_code_studio_session and preferred_code_session_id:
        preferred_session_id = preferred_code_session_id
        if preferred_code_lane:
            metadata["studio_lane"] = preferred_code_lane
        if preferred_code_artifact_kind:
            metadata["artifact_kind"] = preferred_code_artifact_kind
        metadata["quality_profile"] = merge_quality_profile(
            metadata.get("quality_profile"),
            preferred_code_quality,
        )
        if preferred_code_active_version > 0:
            metadata["code_studio_version"] = preferred_code_active_version + 1
        if requested_code_view:
            metadata["requested_view"] = requested_code_view

    if not preferred_session_id:
        return metadata or None

    metadata.update({
        "preferred_visual_operation": "patch",
        "preferred_visual_session_id": preferred_session_id,
        "preferred_visual_patch_hint": "followup-patch",
    })
    if prefers_code_studio_session:
        metadata["preferred_code_studio_session_id"] = preferred_session_id
    if preferred_visual_type:
        metadata["preferred_visual_type"] = preferred_visual_type

    # C3: Conversational editing — inject last visual HTML so LLM can modify
    last_visual_html = str(visual_ctx.get("last_visual_html") or "").strip()
    if not last_visual_html:
        # Try to find HTML from active visuals state_summary
        for item in (visual_ctx.get("active_inline_visuals") or []):
            if isinstance(item, dict) and str(item.get("visual_session_id", "")) == preferred_session_id:
                last_visual_html = str(item.get("state_summary") or "").strip()
                break
    if last_visual_html:
        metadata["last_visual_html"] = last_visual_html[:50000]  # cap at 50k chars

    return metadata or None
