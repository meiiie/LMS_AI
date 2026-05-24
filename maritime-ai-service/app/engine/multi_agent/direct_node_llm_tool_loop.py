"""Direct-node LLM tool-loop lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.direct_node_execution_prep import (
    prepare_direct_node_tool_execution,
)
from app.engine.multi_agent.direct_node_host_timeout import (
    run_direct_node_execution_with_host_timeout,
)
from app.engine.multi_agent.direct_node_llm_execution_finalization import (
    finalize_direct_node_llm_execution,
)
from app.engine.multi_agent.state import AgentState


@dataclass(slots=True)
class DirectNodeLlmToolLoopResult:
    """Typed state returned after a provider-backed direct-node tool loop."""

    response: str
    messages: list[Any]
    tool_call_events: list[dict[str, Any]]
    force_tools: bool


async def execute_direct_node_llm_tool_loop(
    *,
    llm: Any,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    bus_id: str | None,
    domain_name_vi: str,
    role_name: str,
    tools: list[Any],
    force_tools: bool,
    tools_context_override: str | None,
    visual_decision: Any,
    history_limit: int,
    routing_intent: str,
    response_language: str,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    direct_provider_override: str | None,
    preferred_provider: str | None,
    explicit_user_provider: str | None,
    explicit_web_search_turn: bool,
    push_event: Callable[..., Any],
    needs_web_search: Callable[[str], bool],
    needs_datetime: Callable[[str], bool],
    resolve_direct_answer_timeout_profile: Callable[..., Any],
    bind_direct_tools: Callable[..., tuple[Any, Any, Any]],
    build_direct_system_messages: Callable[..., list[Any]],
    build_visual_tool_runtime_metadata: Callable[..., dict[str, Any]],
    execute_direct_tool_rounds: Callable[..., Any],
    extract_direct_response: Callable[..., Any],
    sanitize_structured_visual_answer_text: Callable[..., str],
    sanitize_wiii_house_text: Callable[..., str],
    build_direct_reasoning_summary: Callable[..., str],
    tracer: Any,
    logger_obj: logging.Logger,
    direct_max_rounds: int,
    host_ui_total_timeout_seconds: float,
    prepare_tool_execution_fn: Callable[..., Any] = prepare_direct_node_tool_execution,
    run_with_host_timeout_fn: Callable[..., Any] = run_direct_node_execution_with_host_timeout,
    finalize_llm_execution_fn: Callable[..., Any] = finalize_direct_node_llm_execution,
) -> DirectNodeLlmToolLoopResult:
    """Execute and finalize the provider-backed direct-node tool loop."""

    logger_obj.warning(
        "[DIRECT] tools=%d, force=%s, web=%s, dt=%s, query='%s'",
        len(tools),
        force_tools,
        needs_web_search(query),
        needs_datetime(query),
        query[:60],
    )

    execution_prep = prepare_tool_execution_fn(
        llm=llm,
        tools=tools,
        force_tools=force_tools,
        query=query,
        state=state,
        ctx=ctx,
        bus_id=bus_id,
        domain_name_vi=domain_name_vi,
        role_name=role_name,
        tools_context_override=tools_context_override,
        visual_decision=visual_decision,
        history_limit=history_limit,
        routing_intent=routing_intent,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        direct_provider_override=direct_provider_override,
        preferred_provider=preferred_provider,
        explicit_user_provider=explicit_user_provider,
        needs_web_search=needs_web_search,
        needs_datetime=needs_datetime,
        resolve_direct_answer_timeout_profile=resolve_direct_answer_timeout_profile,
        bind_direct_tools=bind_direct_tools,
        build_direct_system_messages=build_direct_system_messages,
        build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
        logger_obj=logger_obj,
    )

    force_tools = execution_prep.force_tools
    native_direct_messages = execution_prep.native_direct_messages
    messages = execution_prep.messages

    direct_execution = execute_direct_tool_rounds(
        execution_prep.llm_with_tools,
        execution_prep.llm_auto,
        messages,
        tools,
        push_event,
        runtime_context_base=execution_prep.runtime_context_base,
        max_rounds=direct_max_rounds,
        query=query,
        state=state,
        provider=explicit_user_provider,
        forced_tool_choice=execution_prep.forced_tool_choice,
        llm_base=llm,
        direct_answer_timeout_profile=execution_prep.direct_answer_timeout_profile,
        direct_answer_primary_timeout=execution_prep.direct_answer_primary_timeout,
        allowed_fallback_providers=(
            execution_prep.direct_allowed_fallback_providers
        ),
        native_tool_messages=native_direct_messages,
    )
    llm_response, messages, tool_call_events = await run_with_host_timeout_fn(
        direct_execution=direct_execution,
        routing_intent=routing_intent,
        state=state,
        messages=messages,
        push_event=push_event,
        timeout_seconds=host_ui_total_timeout_seconds,
        logger_obj=logger_obj,
    )

    try:
        llm_finalization = await finalize_llm_execution_fn(
            query=query,
            state=state,
            llm_response=llm_response,
            messages=messages,
            tool_call_events=tool_call_events,
            llm=llm,
            routing_intent=routing_intent,
            response_language=response_language,
            is_identity_turn=is_identity_turn,
            explicit_web_search_turn=explicit_web_search_turn,
            extract_direct_response=extract_direct_response,
            sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
            sanitize_wiii_house_text=sanitize_wiii_house_text,
            build_direct_reasoning_summary=build_direct_reasoning_summary,
            logger_obj=logger_obj,
        )
    except Exception as exc:
        setattr(exc, "_direct_node_llm_response", llm_response)
        setattr(exc, "_direct_node_messages", messages)
        setattr(exc, "_direct_node_tool_call_events", tool_call_events)
        raise
    response = llm_finalization.response

    tracer.end_step(
        result=f"Phan hoi LLM: {len(response)} chars",
        confidence=0.85,
        details={
            "response_type": "llm_generated",
            "tools_bound": len(tools),
            "force_tools": force_tools,
        },
    )

    return DirectNodeLlmToolLoopResult(
        response=response,
        messages=messages,
        tool_call_events=tool_call_events,
        force_tools=force_tools,
    )
