"""Tool collection and selection helpers for multi-agent graph.

Extracted from graph.py — collects available tools based on query intent,
user role, and domain context.
"""

from __future__ import annotations

from importlib import import_module
import logging
from typing import Any, Optional

from app.core.config import settings
from app.engine.multi_agent.state import AgentState
logger = logging.getLogger(__name__)


def _load_attr(module_name: str, attr_name: str):
    """Load a helper lazily to reduce static tool-collection coupling."""
    return getattr(import_module(module_name), attr_name)


def _normalize_for_intent(query: str) -> str:
    return _load_attr("app.engine.multi_agent.direct_intent", "_normalize_for_intent")(query)


def _needs_web_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_web_search")(query)


def _needs_datetime(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_datetime")(query)


def _needs_news_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_news_search")(query)


def _needs_legal_search(query: str) -> bool:
    return _load_attr("app.engine.multi_agent.direct_intent", "_needs_legal_search")(query)


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
    normalized = _normalize_for_intent(query)
    return any(
        marker in normalized
        for marker in (
            "preview",
            "xem truoc",
            "ban xem truoc",
            "ban nhap",
            "draft",
            "cap nhat bai hoc",
            "lap bai giang",
            "soan bai giang",
            "soan giao an",
            "tao bai giang",
            "tao giao an",
            "tao hoc lieu",
            "tao bai hoc",
            "tao khoa hoc",
            "thiet ke bai giang",
            "thiet ke khoa hoc",
            "xay dung bai giang",
            "cau truc khoa hoc",
            "toan bo khoa",
            "cay khoa",
            "chia khoa",
            "course architect",
            "course outline",
            "course syllabus",
            "curriculum",
            "de cuong khoa",
            "de cuong mon",
            "giao trinh",
            "ke hoach giang day",
            "learning path",
            "lo trinh hoc",
            "syllabus",
            "generate_course_from_document",
            "lesson patch",
            "preview_lesson_patch",
            "source_references",
            "citation",
            "trich dan",
            "nguon",
        )
    )


def _looks_like_document_course_preview_request(query: str, state: Optional[AgentState]) -> bool:
    if not _has_uploaded_document_context_state(state):
        return False
    normalized = _normalize_for_intent(query)
    if any(
        marker in normalized
        for marker in (
            "preview_lesson_patch",
            "lesson patch",
            "bai hoc hien tai",
            "cap nhat bai hoc",
        )
    ):
        return False
    return any(
        marker in normalized
        for marker in (
            "generate_course_from_document",
            "lap bai giang",
            "soan bai giang",
            "soan giao an",
            "tao bai giang",
            "tao giao an",
            "tao hoc lieu",
            "course architect",
            "course outline",
            "course syllabus",
            "curriculum",
            "full course",
            "toan bo khoa",
            "cay khoa",
            "chia khoa",
            "chia thanh bai",
            "chia thanh chuong",
            "chuong trinh dao tao",
            "de cuong khoa",
            "de cuong mon",
            "giao trinh",
            "ke hoach giang day",
            "khoa dao tao",
            "khoa day du",
            "khoa hoan chinh",
            "learning path",
            "lo trinh hoc",
            "lo trinh khoa",
            "nhieu bai hoc",
            "nhieu chuong",
            "phan chia bai hoc",
            "syllabus",
            "tao khoa hoc",
            "thiet ke bai giang",
            "thiet ke khoa hoc",
            "xay dung bai giang",
            "cau truc khoa hoc",
            "chuong/bai",
            "chuong bai",
            "module",
            "outline",
        )
    )


def _document_preview_host_action_tools(tools: list[Any]) -> list[Any]:
    course_tools = [
        tool
        for tool in tools
        if _tool_name(tool).lower() == "host_action__authoring__generate_course_from_document"
    ]
    lesson_tools = [
        tool
        for tool in tools
        if _tool_name(tool).lower() == "host_action__authoring__preview_lesson_patch"
    ]
    return course_tools + lesson_tools


def _preferred_document_preview_host_action_tools(
    tools: list[Any],
    query: str,
    state: Optional[AgentState],
) -> list[Any]:
    preferred = "host_action__authoring__generate_course_from_document" if (
        _looks_like_document_course_preview_request(query, state)
    ) else "host_action__authoring__preview_lesson_patch"
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
        if str(tool.get("name") or "").strip().lower()
        in {
            "authoring.preview_lesson_patch",
            "authoring.generate_course_from_document",
        }
    ]


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
    if force_tools:
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
    allowed_prefixes = ("host_action__", "tool_pointy_")
    return [tool for tool in tools if _tool_name(tool).startswith(allowed_prefixes)]


def _collect_direct_tools(query: str, user_role: str = "student", state: Optional[AgentState] = None):
    """Collect tools for direct response node and determine forced calling.

    Sprint 154: Extracted from direct_response_node.

    Returns:
        tuple: (tools_list, llm_with_tools_factory, llm_auto_factory, force_tools)
            - tools_list: List of available tools
            - force_tools: Whether to force tool calling (intent detected)
    """
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
        _direct_tools = [*_direct_tools, tool_current_datetime,
                         tool_web_search, tool_fetch_url]
        # v2.8: force-bind via @web-search mention overrides news/legal gates.
        web_search_forced = "web-search" in _force_skills_from_state(state)
        if _needs_news_search(query) or web_search_forced:
            _direct_tools.append(tool_search_news)
        if _needs_legal_search(query) or web_search_forced:
            _direct_tools.append(tool_search_legal)
        # Wiii Pointy — bind cursor-control tools either via keyword
        # intent (`_needs_pointy`) HOẶC explicit `@wiii-pointy` mention
        # (force_skills override, v2.8). Force-bind bypasses keyword
        # gates → user controls invocation explicitly.
        force_skills = _force_skills_from_state(state)
        pointy_forced = "wiii-pointy" in force_skills
        host_ui_navigation = _is_host_ui_navigation_route(state)
        if pointy_forced or host_ui_navigation or _needs_pointy(query):
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
            _needs_maritime = _load_attr(
                "app.engine.multi_agent.direct_intent",
                "_needs_maritime_search",
            )
            if _needs_maritime(query):
                _direct_tools.append(tool_search_maritime)
        except Exception:  # noqa: BLE001
            # If helper missing, default to including maritime (safe for domain).
            _direct_tools.append(tool_search_maritime)
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
    if "tool_knowledge_search" not in _bound_tool_names:
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
                            "host_action_feedback": ((state.get("context") or {}).get("host_action_feedback") or {}),
                        },
                    )
                )
    except Exception as _e:
        logger.debug("[DIRECT] Host action tools unavailable: %s", _e)

    if _is_host_ui_navigation_route(state):
        scoped_host_tools = _host_action_tools(_direct_tools)
        return scoped_host_tools, bool(scoped_host_tools)

    if _looks_like_document_preview_request(query, state):
        preview_tools = _preferred_document_preview_host_action_tools(_direct_tools, query, state)
        if preview_tools:
            logger.info(
                "[DIRECT] Forcing LMS document preview host action for uploaded document context"
            )
            return preview_tools[:1], True

    if _looks_reasoning_safety_meta_turn(query) and _routing_intent(state) in {
        "general",
        "off_topic",
        "personal",
        "social",
    }:
        return [], False

    force_skills = _force_skills_from_state(state)
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

    visual_decision = resolve_visual_intent(query)
    thinking_mode = _infer_direct_thinking_mode(query, state, [])
    normalized_query = _normalize_for_intent(query)
    _prefers_code_execution_lane = any(
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
    _direct_tools = filter_tools_for_role(_direct_tools, user_role)
    _direct_tools = filter_tools_for_visual_intent(
        _direct_tools,
        visual_decision,
        structured_visuals_enabled=getattr(settings, "enable_structured_visuals", False),
    )
    if web_search_forced:
        # Explicit @web-search is a stronger user contract than visual intent.
        # Research prompts often mention charts, pipelines, or summaries; those
        # words must not narrow the tool bundle to visual generation.
        _direct_tools = [
            tool
            for tool in _direct_tools
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
            not in {
                "tool_create_visual_code",
                "tool_generate_visual",
                "tool_generate_mermaid",
                "tool_generate_interactive_chart",
            }
        ]
    if _should_strip_visual_tools_from_direct(query, visual_decision):
        _direct_tools = [
            tool for tool in _direct_tools
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
            not in {
                "tool_create_visual_code",
                "tool_generate_visual",
                "tool_generate_mermaid",
                "tool_generate_interactive_chart",
            }
        ]
    if _should_strip_visual_tools_for_analytical_text_turn(
        query,
        visual_decision,
        thinking_mode=thinking_mode,
    ):
        _direct_tools = [
            tool for tool in _direct_tools
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "")
            not in {
                "tool_create_visual_code",
                "tool_generate_visual",
                "tool_generate_mermaid",
                "tool_generate_interactive_chart",
            }
        ]
    # Clear inline article/chart requests should stay tightly on the visual lane.
    # If there is no competing web/legal/news/datetime/LMS intent, bind only the
    # preferred visual tool so the first tool call is deterministic and the
    # direct lane does not waste latency on unrelated tool options.
    if (
        visual_decision.force_tool
        and visual_decision.preferred_tool
        and visual_decision.presentation_intent in {"article_figure", "chart_runtime"}
        and not (
            _needs_web_search(query)
            or _needs_datetime(query)
            or _needs_news_search(query)
            or _needs_legal_search(query)
            or _needs_lms_query(query)
            or web_search_forced
        )
    ):
        preferred_name = visual_decision.preferred_tool
        preferred_tools = [
            tool
            for tool in _direct_tools
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "") == preferred_name
        ]
        if preferred_tools:
            _direct_tools = preferred_tools
    _needs_visual_tool = (
        not _prefers_code_execution_lane
        and
        visual_decision.force_tool
        and visual_decision.mode in {"template", "inline_html", "app", "mermaid"}
        and (
            visual_decision.presentation_intent in {"article_figure", "chart_runtime"}
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
        return [], False

    # Agent handoff tool (Phase 3)
    if getattr(settings, "enable_agent_handoffs", True) and not force_tools:
        try:
            from app.engine.multi_agent.handoff_tools import handoff_to_agent
            _direct_tools.append(handoff_to_agent)
        except Exception:
            pass

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
    _tools = filter_tools_for_role(_tools, user_role)
    _tools = filter_tools_for_visual_intent(
        _tools,
        visual_decision,
        structured_visuals_enabled=getattr(settings, "enable_structured_visuals", False),
    )

    # Clear app/artifact requests should not drift across a broad tool bundle.
    # Once the resolver has locked a preferred tool for the studio lane, we
    # narrow the bound tools to that target so the first tool call is
    # deterministic and faster to emit in streaming.
    if (
        visual_decision.force_tool
        and visual_decision.preferred_tool
        and visual_decision.presentation_intent in {"code_studio_app", "artifact"}
    ):
        preferred_name = visual_decision.preferred_tool
        preferred_tools = [
            tool
            for tool in _tools
            if str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "") == preferred_name
        ]
        if preferred_tools:
            _tools = preferred_tools

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

    if _needs_datetime(query):
        required.append("tool_current_datetime")
    if _needs_news_search(query):
        required.append("tool_search_news")
    if _needs_legal_search(query):
        required.append("tool_search_legal")
    if _needs_web_search(query):
        if any(
            signal in normalized
            for signal in ("imo", "shipping", "maritime", "hang hai", "vinamarine", "cuc hang hai")
        ):
            required.append("tool_search_maritime")
        else:
            required.append("tool_web_search")
    if _needs_direct_knowledge_search(query):
        required.append("tool_knowledge_search")
    # WAVE-001: browser_snapshot and execute_python removed from direct.
    # These capabilities now live exclusively in code_studio_agent.

    if visual_decision.force_tool and not _needs_analysis_tool(query):
        _structured = getattr(settings, "enable_structured_visuals", False)
        if visual_decision.mode == "mermaid" and _structured:
            required.append("tool_generate_mermaid")
        elif visual_decision.preferred_tool:
            required.append(visual_decision.preferred_tool)
        elif _structured:
            # Structured mode: ALL visual intents → multi-figure tool
            required.append("tool_generate_visual")

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

    if visual_decision.force_tool and visual_decision.preferred_tool:
        required.append(visual_decision.preferred_tool)
        deduped: list[str] = []
        for tool_name in required:
            if tool_name not in deduped:
                deduped.append(tool_name)
        return deduped

    if visual_decision.force_tool:
        _structured = getattr(settings, "enable_structured_visuals", False)
        _llm_code_gen = getattr(settings, "enable_llm_code_gen_visuals", False)
        if visual_decision.mode == "mermaid" and _structured:
            required.append("tool_generate_mermaid")
        elif _structured and _llm_code_gen:
            if visual_decision.presentation_intent in {"article_figure", "chart_runtime"}:
                required.append("tool_generate_visual")
            else:
                required.append("tool_create_visual_code")
        elif _structured:
            required.append("tool_generate_visual")

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
