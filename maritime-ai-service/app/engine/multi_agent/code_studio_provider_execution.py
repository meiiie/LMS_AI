"""Typed provider-backed execution contract for Code Studio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    record_thinking_snapshot,
    resolve_visible_thinking_from_lifecycle,
)


@dataclass(frozen=True, slots=True)
class CodeStudioProviderExecutionRequest:
    """Per-turn state required for provider-backed Code Studio execution."""

    effective_query: str
    state: AgentState
    ctx: dict[str, Any]
    domain_name_vi: str
    explicit_provider: str | None
    tools: list[Any]
    force_tools: bool
    runtime_context_base: Any | None
    event_queue_present: bool
    push_event: Callable[[dict[str, Any]], Any]
    settings_obj: Any
    requested_model: str | None


@dataclass(frozen=True, slots=True)
class CodeStudioProviderExecutionDependencies:
    """Injected app contracts used by provider-backed Code Studio execution."""

    bind_direct_tools: Callable[..., tuple[Any, Any, Any]]
    build_direct_system_messages: Callable[..., list[Any]]
    build_code_studio_tools_context: Callable[..., str]
    execute_code_studio_tool_rounds: Callable[..., Any]
    extract_direct_response: Callable[..., tuple[str, str, list[Any]]]
    build_code_studio_stream_summary_messages: Callable[..., list[Any]]
    stream_answer_with_fallback: Callable[..., Any]
    sanitize_code_studio_response: Callable[..., str]
    build_code_studio_reasoning_summary: Callable[..., Any]
    direct_tool_names: Callable[[list[Any]], list[str]]
    logger_obj: logging.Logger
    get_agent_llm: Callable[..., Any] | None = None
    get_summary_llm_for_provider: Callable[..., Any] | None = None
    record_thinking_snapshot_fn: Callable[..., Any] = record_thinking_snapshot
    resolve_visible_thinking_fn: Callable[..., str] = (
        resolve_visible_thinking_from_lifecycle
    )


@dataclass(slots=True)
class CodeStudioProviderExecutionResult:
    """Resolved Code Studio response after provider/tool/summary execution."""

    response: str
    tool_call_events: list[dict[str, Any]]
    tools_used: list[Any]
    streamed_delivery: bool
    bound_provider: str | None
    bound_model: str | None


def _resolve_agent_llm(dependencies: CodeStudioProviderExecutionDependencies):
    if dependencies.get_agent_llm is not None:
        return dependencies.get_agent_llm
    from app.engine.multi_agent.agent_config import AgentConfigRegistry

    return AgentConfigRegistry.get_llm


def _resolve_summary_llm_provider(
    dependencies: CodeStudioProviderExecutionDependencies,
):
    if dependencies.get_summary_llm_for_provider is not None:
        return dependencies.get_summary_llm_for_provider
    from app.engine.llm_pool import get_llm_for_provider

    return get_llm_for_provider


async def execute_code_studio_provider_execution(
    *,
    request: CodeStudioProviderExecutionRequest,
    dependencies: CodeStudioProviderExecutionDependencies,
) -> CodeStudioProviderExecutionResult:
    """Run the provider-backed Code Studio tool loop and final response cleanup."""

    state = request.state
    thinking_effort = state.get("thinking_effort")
    get_agent_llm = _resolve_agent_llm(dependencies)
    llm = get_agent_llm(
        "code_studio_agent",
        effort_override=thinking_effort,
        provider_override=request.explicit_provider,
        requested_model=request.requested_model,
    )
    if (
        llm
        and getattr(request.settings_obj, "enable_natural_conversation", False) is True
    ):
        presence_penalty = getattr(request.settings_obj, "llm_presence_penalty", 0.0)
        frequency_penalty = getattr(request.settings_obj, "llm_frequency_penalty", 0.0)
        if presence_penalty or frequency_penalty:
            try:
                llm = llm.bind(
                    presence_penalty=presence_penalty,
                    frequency_penalty=frequency_penalty,
                )
            except Exception:
                pass
    if not llm:
        raise RuntimeError("Code Studio provider returned no LLM")

    bound_provider = getattr(llm, "_wiii_provider_name", None) or state.get("provider")
    bound_model = (
        getattr(llm, "_wiii_model_name", None)
        or getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
    )
    if bound_provider and str(bound_provider).strip().lower() != "auto":
        state["_execution_provider"] = str(bound_provider)
    if bound_model:
        state["_execution_model"] = str(bound_model)
        state["model"] = str(bound_model)

    llm_with_tools, llm_auto, forced_tool_choice = dependencies.bind_direct_tools(
        llm,
        request.tools,
        request.force_tools,
        provider=bound_provider,
        include_forced_choice=True,
    )
    messages = dependencies.build_direct_system_messages(
        state,
        request.effective_query,
        request.domain_name_vi,
        role_name="code_studio_agent",
        tools_context_override=dependencies.build_code_studio_tools_context(
            request.settings_obj,
            request.ctx.get("user_role", "student"),
            request.effective_query,
        ),
    )
    llm_response, messages, tool_call_events = (
        await dependencies.execute_code_studio_tool_rounds(
            llm_with_tools,
            llm_auto,
            messages,
            request.tools,
            request.push_event,
            runtime_context_base=request.runtime_context_base,
            query=request.effective_query,
            state=state,
            provider=state.get("provider"),
            runtime_provider=bound_provider,
            forced_tool_choice=forced_tool_choice,
        )
    )

    if tool_call_events:
        state["tool_call_events"] = tool_call_events

    response, _thinking_content, tools_used = dependencies.extract_direct_response(
        llm_response,
        messages,
    )
    streamed_code_studio_answer = False
    if request.event_queue_present and tool_call_events:
        try:
            summary_provider = (
                bound_provider
                if bound_provider and str(bound_provider).strip().lower() != "auto"
                else state.get("provider")
            )
            from app.engine.llm_pool import ThinkingTier

            summary_llm = _resolve_summary_llm_provider(dependencies)(
                summary_provider,
                default_tier=ThinkingTier.MODERATE,
                strict_pin=bool(
                    summary_provider
                    and str(summary_provider).strip().lower() != "auto"
                ),
            )
            summary_messages = dependencies.build_code_studio_stream_summary_messages(
                state,
                request.effective_query,
                request.domain_name_vi,
                tool_call_events=tool_call_events,
            )
            streamed_summary_response, streamed_code_studio_answer = (
                await dependencies.stream_answer_with_fallback(
                    summary_llm,
                    summary_messages,
                    request.push_event,
                    provider=summary_provider,
                    node="code_studio_agent",
                )
            )
            streamed_response, _summary_thinking, _summary_tools = (
                dependencies.extract_direct_response(
                    streamed_summary_response,
                    summary_messages,
                )
            )
            if streamed_response:
                response = streamed_response
        except Exception as summary_error:
            dependencies.logger_obj.warning(
                "[CODE_STUDIO] Final streamed delivery summary failed, "
                "using buffered response: %s",
                summary_error,
            )
    response = dependencies.sanitize_code_studio_response(
        response,
        tool_call_events,
        state,
    )

    safe_thinking = await dependencies.build_code_studio_reasoning_summary(
        request.effective_query,
        state,
        dependencies.direct_tool_names(tools_used),
    )
    if safe_thinking:
        state["thinking_content"] = dependencies.resolve_visible_thinking_fn(
            state,
            fallback=safe_thinking,
            default_node="code_studio_agent",
        )
        if state.get("thinking_content"):
            dependencies.record_thinking_snapshot_fn(
                state,
                state.get("thinking_content"),
                node="code_studio_agent",
                provenance="aligned_cleanup",
            )

    if tools_used:
        state["tools_used"] = tools_used

    return CodeStudioProviderExecutionResult(
        response=response,
        tool_call_events=tool_call_events,
        tools_used=tools_used,
        streamed_delivery=streamed_code_studio_answer,
        bound_provider=str(bound_provider) if bound_provider else None,
        bound_model=str(bound_model) if bound_model else None,
    )
