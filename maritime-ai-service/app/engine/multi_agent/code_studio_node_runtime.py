"""Runtime implementation for graph code_studio_node."""

from __future__ import annotations

from app.engine.multi_agent.code_studio_provider_execution import (
    CodeStudioProviderExecutionDependencies,
    CodeStudioProviderExecutionRequest,
    execute_code_studio_provider_execution,
)
from app.engine.multi_agent.code_studio_node_preflight import (
    CodeStudioNodePreflightDependencies,
    CodeStudioNodePreflightRequest,
    execute_code_studio_node_preflight,
)
from app.engine.multi_agent.code_studio_node_events import (
    CodeStudioNodeEventSinkRequest,
    create_code_studio_node_event_sink,
)
from app.engine.multi_agent.code_studio_node_final_state import (
    CodeStudioNodeFinalStateDependencies,
    CodeStudioNodeFinalStateRequest,
    apply_code_studio_node_final_state,
)
from app.engine.multi_agent.code_studio_scaffold_fallback_policy import (
    resolve_code_studio_scaffold_fallback,
)
from app.engine.multi_agent.code_studio_tool_setup import (
    prepare_code_studio_tool_setup,
)
from app.engine.multi_agent.state import AgentState
from app.engine.runtime.runtime_metrics import inc_counter


async def code_studio_node_impl(
    state: AgentState,
    *,
    settings_obj,
    logger,
    get_event_queue,
    capture_public_thinking_event,
    get_or_create_tracer,
    step_names,
    get_effective_provider,
    looks_like_ambiguous_simulation_request,
    ground_simulation_query_from_visual_context,
    last_inline_visual_title,
    build_ambiguous_simulation_clarifier,
    collect_code_studio_tools,
    code_studio_required_tool_names,
    bind_direct_tools,
    build_direct_system_messages,
    build_code_studio_tools_context,
    build_tool_runtime_context_fn,
    build_visual_tool_runtime_metadata,
    execute_code_studio_fast_path,
    execute_code_studio_tool_rounds,
    extract_direct_response,
    build_code_studio_stream_summary_messages,
    stream_answer_with_fallback,
    sanitize_code_studio_response,
    build_code_studio_reasoning_summary,
    direct_tool_names,
    resolve_public_thinking_content,
) -> AgentState:
    """Capability subagent for Python, chart, HTML, and file-generation tasks."""
    query = state.get("query", "")
    effective_query = query

    _bus_id = state.get("_event_bus_id")
    event_sink = create_code_studio_node_event_sink(
        CodeStudioNodeEventSinkRequest(
            state=state,
            bus_id=_bus_id,
            get_event_queue=get_event_queue,
            capture_public_thinking_event=capture_public_thinking_event,
            logger=logger,
        )
    )

    tracer = get_or_create_tracer(state)
    tracer.start_step(step_names.DIRECT_RESPONSE, "Che tac dau ra ky thuat")

    try:
        _ctx = state.get("context", {})
        explicit_provider = get_effective_provider(state)
        preflight = await execute_code_studio_node_preflight(
            request=CodeStudioNodePreflightRequest(
                query=query,
                state=state,
                default_domain=settings_obj.default_domain,
                push_event=event_sink.push_event,
                tracer=tracer,
            ),
            dependencies=CodeStudioNodePreflightDependencies(
                looks_like_ambiguous_simulation_request=(
                    looks_like_ambiguous_simulation_request
                ),
                ground_simulation_query_from_visual_context=(
                    ground_simulation_query_from_visual_context
                ),
                last_inline_visual_title=last_inline_visual_title,
                build_ambiguous_simulation_clarifier=(
                    build_ambiguous_simulation_clarifier
                ),
            ),
        )
        effective_query = preflight.effective_query
        response = preflight.response
        domain_name_vi = preflight.domain_name_vi
        tools: list = []
        force_tools = False
        runtime_context_base = None
        if not response:
            tool_setup = prepare_code_studio_tool_setup(
                effective_query=effective_query,
                state=state,
                ctx=_ctx,
                bus_id=_bus_id,
                collect_code_studio_tools=collect_code_studio_tools,
                code_studio_required_tool_names=code_studio_required_tool_names,
                build_tool_runtime_context_fn=build_tool_runtime_context_fn,
                build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
                logger_obj=logger,
            )
            tools = tool_setup.tools
            force_tools = tool_setup.force_tools
            runtime_context_base = tool_setup.runtime_context_base

            fast_path_result = await execute_code_studio_fast_path(
                state=state,
                query=effective_query,
                tools=tools,
                push_event=event_sink.push_event,
                runtime_context_base=runtime_context_base,
            )

            if fast_path_result:
                response = fast_path_result.response
                state["thinking_content"] = fast_path_result.thinking_content
                state["tool_call_events"] = fast_path_result.tool_call_events
                state["tools_used"] = fast_path_result.tools_used
                tracer.end_step(
                    result=f"Code studio fast path: {fast_path_result.fast_path}",
                    confidence=0.91,
                    details={
                        "response_type": "capability_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                        "fast_path": fast_path_result.fast_path,
                    },
                )
            else:
                provider_execution = await execute_code_studio_provider_execution(
                    request=CodeStudioProviderExecutionRequest(
                        effective_query=effective_query,
                        state=state,
                        ctx=_ctx,
                        domain_name_vi=domain_name_vi,
                        explicit_provider=explicit_provider,
                        tools=tools,
                        force_tools=force_tools,
                        runtime_context_base=runtime_context_base,
                        event_queue_present=event_sink.event_queue_present,
                        push_event=event_sink.push_event,
                        settings_obj=settings_obj,
                        requested_model=state.get("model"),
                    ),
                    dependencies=CodeStudioProviderExecutionDependencies(
                        bind_direct_tools=bind_direct_tools,
                        build_direct_system_messages=build_direct_system_messages,
                        build_code_studio_tools_context=build_code_studio_tools_context,
                        execute_code_studio_tool_rounds=execute_code_studio_tool_rounds,
                        extract_direct_response=extract_direct_response,
                        build_code_studio_stream_summary_messages=(
                            build_code_studio_stream_summary_messages
                        ),
                        stream_answer_with_fallback=stream_answer_with_fallback,
                        sanitize_code_studio_response=sanitize_code_studio_response,
                        build_code_studio_reasoning_summary=(
                            build_code_studio_reasoning_summary
                        ),
                        direct_tool_names=direct_tool_names,
                        logger_obj=logger,
                    ),
                )
                response = provider_execution.response

                tracer.end_step(
                    result=f"Code studio response: {len(response)} chars",
                    confidence=0.88,
                    details={
                        "response_type": "capability_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                        "streamed_delivery": provider_execution.streamed_delivery,
                    },
                )
        elif not response:
            response = "Mình chưa khởi động được Code Studio lúc này. Bạn thử lại sau nhé."
            tracer.end_step(
                result="Fallback (code studio unavailable)",
                confidence=0.5,
                details={"response_type": "fallback"},
            )
    except Exception as e:
        logger.error("[CODE_STUDIO] Generation failed: %s", e, exc_info=True)
        # Even when the upstream tool-rounds path fails before it can make
        # its own decision, do not blindly ship the deterministic template:
        # the visual/runtime contract decides whether fallback is allowed.
        fallback_decision = resolve_code_studio_scaffold_fallback(
            query=query,
            state=state,
            reason=f"node_outer_{type(e).__name__}",
            allow_scaffold_delivery=False,
        )
        response = fallback_decision.response
        try:
            inc_counter(
                (
                    "wiii.code_studio.scaffold.engaged"
                    if fallback_decision.engage_scaffold
                    else "wiii.code_studio.scaffold.suppressed"
                ),
                labels=fallback_decision.metric_labels(),
            )
        except Exception:  # noqa: BLE001 — never let metrics break a request
            pass
        tracer.end_step(
            result=f"Fallback (code studio error: {type(e).__name__})",
            confidence=0.5,
            details={
                "response_type": fallback_decision.response_type,
                "fallback_policy_reason": fallback_decision.policy_reason,
                "error": str(e)[:200],
            },
        )

    await apply_code_studio_node_final_state(
        request=CodeStudioNodeFinalStateRequest(
            state=state,
            response=response,
            query=query,
        ),
        dependencies=CodeStudioNodeFinalStateDependencies(
            build_code_studio_reasoning_summary=build_code_studio_reasoning_summary,
            direct_tool_names=direct_tool_names,
        ),
    )

    logger.info("[CODE_STUDIO] Response prepared, tracer passed to synthesizer")

    return state
