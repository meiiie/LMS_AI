"""Direct-node tool execution preparation."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.engine.multi_agent.direct_response_runtime import (
    resolve_direct_answer_primary_timeout_impl,
    resolve_direct_fallback_provider_allowlist_impl_wrapper,
)
from app.engine.multi_agent.graph_runtime_helpers import (
    _extract_runtime_target,
    _is_native_runtime_handle,
)
from app.engine.multi_agent.state import AgentState
from app.engine.tools.runtime_context import build_tool_runtime_context


@dataclass(slots=True)
class DirectNodePreparedExecution:
    force_tools: bool
    bound_provider: str | None
    bound_model: str | None
    direct_answer_timeout_profile: Any
    direct_answer_primary_timeout: Any
    direct_allowed_fallback_providers: Any
    llm_with_tools: Any
    llm_auto: Any
    forced_tool_choice: Any
    native_direct_messages: bool
    messages: list[Any]
    runtime_context_base: Any


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", getattr(tool, "__name__", "")) or "")


def _append_force_skill(state: AgentState, skill: str) -> None:
    skills = state.get("force_skills")
    if isinstance(skills, list):
        if skill not in skills:
            skills.append(skill)
        return
    state["force_skills"] = [skill]


def prepare_direct_node_tool_execution(
    *,
    llm: Any,
    tools: list[Any],
    force_tools: bool,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    bus_id: str | None,
    domain_name_vi: str,
    role_name: str,
    tools_context_override: str | None,
    visual_decision: Any,
    history_limit: int,
    routing_intent: str,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    direct_provider_override: str | None,
    preferred_provider: str | None,
    explicit_user_provider: str | None,
    needs_web_search: Callable[[str], bool],
    needs_datetime: Callable[[str], bool],
    resolve_direct_answer_timeout_profile: Callable[..., Any],
    bind_direct_tools: Callable[..., tuple[Any, Any, Any]],
    build_direct_system_messages: Callable[..., list[Any]],
    build_visual_tool_runtime_metadata: Callable[..., dict[str, Any]],
    logger_obj: logging.Logger,
    extract_runtime_target: Callable[[Any | None], tuple[str | None, str | None]] = _extract_runtime_target,
    is_native_runtime_handle: Callable[[Any | None], bool] = _is_native_runtime_handle,
    build_tool_runtime_context_fn: Callable[..., Any] = build_tool_runtime_context,
) -> DirectNodePreparedExecution:
    """Prepare a direct-node tool loop without executing the provider call."""

    if (
        getattr(visual_decision, "force_tool", False)
        and not force_tools
        and routing_intent not in ("learning", "lookup")
    ):
        has_visual_tool = any(_tool_name(tool) == "tool_generate_visual" for tool in tools)
        if has_visual_tool:
            force_tools = True
            logger_obj.info(
                "[DIRECT] Visual intent -> force tool_choice='any' (visual_type=%s)",
                getattr(visual_decision, "visual_type", None),
            )
        else:
            logger_obj.warning(
                "[DIRECT] Visual intent detected but tool_generate_visual not in tools list",
            )

    if routing_intent == "web_search" and not force_tools:
        has_web_search_tool = any(_tool_name(tool) == "tool_web_search" for tool in tools)
        if has_web_search_tool:
            force_tools = True
            _append_force_skill(state, "web-search")
            logger_obj.info("[DIRECT] Web-search routing intent -> force tool_choice='any'")

    bound_provider, bound_model = extract_runtime_target(llm)
    bound_provider = bound_provider or state.get("provider")
    if bound_provider and str(bound_provider).strip().lower() != "auto":
        state["_execution_provider"] = str(bound_provider)
    if bound_model:
        state["_execution_model"] = str(bound_model)
        state["model"] = str(bound_model)

    provider_for_policy = bound_provider or direct_provider_override or preferred_provider
    direct_answer_timeout_profile = resolve_direct_answer_timeout_profile(
        provider_name=provider_for_policy,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=bool(tools),
    )
    direct_answer_primary_timeout = resolve_direct_answer_primary_timeout_impl(
        provider_name=provider_for_policy,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=bool(tools),
    )
    direct_allowed_fallback_providers = None
    if not explicit_user_provider:
        direct_allowed_fallback_providers = (
            resolve_direct_fallback_provider_allowlist_impl_wrapper(
                provider_name=provider_for_policy,
                query=query,
                state=state,
                is_identity_turn=is_identity_turn,
                is_short_house_chatter=is_short_house_chatter,
                use_house_voice_direct=use_house_voice_direct,
                tools_bound=bool(tools),
            )
        )

    llm_with_tools, llm_auto, forced_tool_choice = bind_direct_tools(
        llm,
        tools,
        force_tools,
        provider=bound_provider,
        include_forced_choice=True,
    )
    if force_tools:
        logger_obj.info(
            "[DIRECT] Forced tool_choice=%r (web=%s, dt=%s, visual=%s)",
            forced_tool_choice,
            needs_web_search(query),
            needs_datetime(query),
            getattr(visual_decision, "force_tool", False),
        )

    native_direct_messages = is_native_runtime_handle(llm)
    messages = build_direct_system_messages(
        state,
        query,
        domain_name_vi,
        role_name=role_name,
        tools_context_override=tools_context_override,
        visual_decision=visual_decision,
        history_limit=history_limit,
        native_messages=native_direct_messages,
    )
    runtime_context_base = build_tool_runtime_context_fn(
        event_bus_id=bus_id,
        request_id=ctx.get("request_id"),
        session_id=state.get("session_id"),
        organization_id=state.get("organization_id"),
        user_id=state.get("user_id"),
        user_role=ctx.get("user_role", "student"),
        node="direct",
        source="agentic_loop",
        metadata=build_visual_tool_runtime_metadata(state, query),
    )

    return DirectNodePreparedExecution(
        force_tools=force_tools,
        bound_provider=bound_provider,
        bound_model=bound_model,
        direct_answer_timeout_profile=direct_answer_timeout_profile,
        direct_answer_primary_timeout=direct_answer_primary_timeout,
        direct_allowed_fallback_providers=direct_allowed_fallback_providers,
        llm_with_tools=llm_with_tools,
        llm_auto=llm_auto,
        forced_tool_choice=forced_tool_choice,
        native_direct_messages=native_direct_messages,
        messages=messages,
        runtime_context_base=runtime_context_base,
    )
