"""Runtime preparation helpers for tutor node orchestration."""

from dataclasses import dataclass
import logging
from typing import Any, Callable, Sequence

from app.engine.tools.runtime_context import (
    build_tool_runtime_context,
    filter_tools_for_role,
)
from app.engine.multi_agent.graph_runtime_helpers import _copy_runtime_metadata
from app.engine.multi_agent.tool_policy_session import (
    build_visible_tool_policy_session,
    record_tool_policy_session,
)
from app.engine.multi_agent.visual_intent_resolver import (
    filter_tools_for_visual_intent,
)


@dataclass(slots=True)
class PreparedTutorRequest:
    """Resolved runtime artifacts for one tutor request."""

    thinking_effort: str | None
    llm_for_request: Any
    llm_with_tools_for_request: Any
    provider_override: str | None
    merged_context: dict[str, Any]
    visual_decision: Any
    active_tools: list[Any]
    runtime_context_base: Any


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def build_tutor_tools(
    *,
    base_tools: Sequence[Any],
    settings_obj: Any,
    logger_obj: logging.Logger,
) -> tuple[list[Any], bool]:
    """Build the tutor toolset with optional runtime-gated tools."""
    tools = list(base_tools)
    character_tools_enabled = False

    try:
        if settings_obj.enable_character_tools:
            from app.engine.character.character_tools import get_character_tools

            char_tools = get_character_tools()
            tools.extend(char_tools)
            character_tools_enabled = True
            logger_obj.info("[TUTOR_AGENT] Character tools enabled: %d tools", len(char_tools))
    except Exception as exc:
        logger_obj.debug("[TUTOR_AGENT] Character tools not available: %s", exc)

    optional_tool_specs: list[tuple[str, str]] = [
        ("app.engine.tools.chart_tools", "get_chart_tools"),
        ("app.engine.tools.visual_tools", "get_visual_tools"),
        ("app.engine.tools.output_generation_tools", "get_output_generation_tools"),
    ]
    for module_name, factory_name in optional_tool_specs:
        try:
            module = __import__(module_name, fromlist=[factory_name])
            factory = getattr(module, factory_name)
            extra_tools = factory()
            if extra_tools:
                tools.extend(extra_tools)
                logger_obj.info(
                    "[TUTOR_AGENT] %s enabled: %d tools",
                    factory_name.replace("get_", "").replace("_", " "),
                    len(extra_tools),
                )
        except Exception as exc:
            logger_obj.debug("[TUTOR_AGENT] %s not available: %s", factory_name, exc)

    try:
        if (
            settings_obj.enable_browser_agent
            and settings_obj.enable_privileged_sandbox
            and settings_obj.sandbox_provider == "opensandbox"
            and settings_obj.sandbox_allow_browser_workloads
        ):
            from app.engine.tools.browser_sandbox_tools import get_browser_sandbox_tools

            browser_tools = get_browser_sandbox_tools()
            if browser_tools:
                tools.extend(browser_tools)
                logger_obj.info(
                    "[TUTOR_AGENT] Browser sandbox tools enabled: %d tools",
                    len(browser_tools),
                )
    except Exception as exc:
        logger_obj.debug("[TUTOR_AGENT] Browser sandbox tools not available: %s", exc)

    return tools, character_tools_enabled


def _merge_tutor_context(
    *,
    state: dict[str, Any],
    context: dict[str, Any],
    learning_context: dict[str, Any],
    thinking_effort: str | None,
) -> dict[str, Any]:
    """Merge shared graph context into the tutor request context."""
    merged_context = {**context, **learning_context}
    for state_key, context_key in (
        ("skill_context", "skill_context"),
        ("capability_context", "capability_context"),
        ("host_context_prompt", "host_context_prompt"),
        ("host_capabilities_prompt", "host_capabilities_prompt"),
        ("operator_context_prompt", "operator_context_prompt"),
        ("living_context_prompt", "living_context_prompt"),
        ("widget_feedback_prompt", "widget_feedback_prompt"),
    ):
        value = state.get(state_key)
        if value:
            merged_context[context_key] = value
    if thinking_effort:
        merged_context["thinking_effort"] = thinking_effort
    return merged_context


def prepare_tutor_request(
    *,
    state: dict[str, Any],
    context: dict[str, Any],
    learning_context: dict[str, Any],
    default_llm: Any,
    base_tools: Sequence[Any],
    settings_obj: Any,
    logger_obj: logging.Logger,
    resolve_visual_intent_fn: Callable[[str], Any],
    required_visual_tool_names_fn: Callable[[Any], list[str]],
    get_effective_provider_fn: Callable[[dict[str, Any]], str | None],
    get_llm_fn: Callable[..., Any],
    resolve_tool_choice_fn: Callable[[bool, Sequence[Any], str | None], Any],
) -> PreparedTutorRequest:
    """Resolve provider, tools, visual intent, and runtime context for one request."""
    query = state.get("query", "")
    thinking_effort = state.get("thinking_effort")
    llm_for_request = default_llm
    implicit_visual_thinking_floor = False
    visual_decision = resolve_visual_intent_fn(query)
    if visual_decision.force_tool and not thinking_effort:
        thinking_effort = "high"
        implicit_visual_thinking_floor = True
        logger_obj.info("[TUTOR_AGENT] Visual intent detected -> upgrade to high effort")

    provider_override = get_effective_provider_fn(state)
    if provider_override or (thinking_effort and not implicit_visual_thinking_floor):
        llm_for_request = get_llm_fn(
            "tutor_agent",
            effort_override=thinking_effort,
            provider_override=provider_override,
            requested_model=state.get("model"),
        )
        logger_obj.info(
            "[TUTOR_AGENT] LLM override: effort=%s provider=%s",
            thinking_effort,
            provider_override,
        )

    merged_context = _merge_tutor_context(
        state=state,
        context=context,
        learning_context=learning_context,
        thinking_effort=thinking_effort,
    )

    active_tools = filter_tools_for_role(
        list(base_tools),
        merged_context.get("user_role", "student"),
    )
    active_tools = filter_tools_for_visual_intent(
        active_tools,
        visual_decision,
        structured_visuals_enabled=getattr(settings_obj, "enable_structured_visuals", False),
    )
    candidate_tool_names = [_tool_name(tool) for tool in active_tools]

    try:
        from app.engine.skills.skill_recommender import select_runtime_tools

        must_include = [
            "tool_knowledge_search",
        ]
        must_include.extend(required_visual_tool_names_fn(visual_decision))
        selected_tools = select_runtime_tools(
            active_tools,
            query=query,
            intent=(state.get("routing_metadata") or {}).get("intent") or "learning",
            user_role=merged_context.get("user_role", "student"),
            max_tools=min(len(active_tools), 6),
            must_include=must_include,
        )
        if selected_tools:
            active_tools = filter_tools_for_visual_intent(
                selected_tools,
                visual_decision,
                structured_visuals_enabled=getattr(settings_obj, "enable_structured_visuals", False),
            )
            logger_obj.info(
                "[TUTOR_AGENT] Runtime-selected tools: %s",
                [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in active_tools],
            )
    except Exception as exc:
        logger_obj.debug("[TUTOR_AGENT] Runtime tool selection skipped: %s", exc)

    llm_with_tools_for_request = None
    visible_tools_for_policy = list(active_tools)
    if llm_for_request:
        if visual_decision.force_tool:
            required_visual_names = set(required_visual_tool_names_fn(visual_decision))
            visual_tools_only = [
                tool
                for tool in active_tools
                if getattr(tool, "name", "") in required_visual_names
            ]
            if visual_tools_only:
                visible_tools_for_policy = list(visual_tools_only)
                forced_choice = resolve_tool_choice_fn(True, visual_tools_only, provider_override)
                llm_with_tools_for_request = _copy_runtime_metadata(
                    llm_for_request,
                    llm_for_request.bind_tools(
                        visual_tools_only,
                        tool_choice=forced_choice,
                    ),
                )
                logger_obj.info(
                    "[TUTOR_AGENT] Visual intent -> force tool_choice=%r for %s",
                    forced_choice,
                    sorted(required_visual_names),
                )
            else:
                llm_with_tools_for_request = _copy_runtime_metadata(
                    llm_for_request,
                    llm_for_request.bind_tools(active_tools),
                )
        else:
            llm_with_tools_for_request = (
                _copy_runtime_metadata(llm_for_request, llm_for_request.bind_tools(active_tools))
                if active_tools
                else llm_for_request
            )

    runtime_context_base = build_tool_runtime_context(
        event_bus_id=state.get("_event_bus_id"),
        request_id=state.get("_event_bus_id") or state.get("session_id"),
        session_id=state.get("session_id"),
        organization_id=state.get("organization_id"),
        user_id=state.get("user_id"),
        user_role=merged_context.get("user_role", "student"),
        node="tutor_agent",
        source="agentic_loop",
    )

    policy_session = build_visible_tool_policy_session(
        path="tutor",
        reason="tutor_tool_setup",
        state=state,
        query=query,
        candidate_tool_names=candidate_tool_names,
        visible_tool_names=[_tool_name(tool) for tool in visible_tools_for_policy],
        force_tools=bool(getattr(visual_decision, "force_tool", False)),
    )
    record_tool_policy_session(state, policy_session)

    return PreparedTutorRequest(
        thinking_effort=thinking_effort,
        llm_for_request=llm_for_request,
        llm_with_tools_for_request=llm_with_tools_for_request,
        provider_override=provider_override,
        merged_context=merged_context,
        visual_decision=visual_decision,
        active_tools=active_tools,
        runtime_context_base=runtime_context_base,
    )
