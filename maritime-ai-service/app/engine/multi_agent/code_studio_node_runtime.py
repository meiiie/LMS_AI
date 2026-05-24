"""Runtime implementation for graph code_studio_node."""

from __future__ import annotations


from app.engine.multi_agent.code_studio_scaffold_fallback_policy import (
    resolve_code_studio_scaffold_fallback,
)
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    record_thinking_snapshot,
    resolve_visible_thinking_from_lifecycle,
)
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

    _event_queue = None
    _bus_id = state.get("_event_bus_id")
    if _bus_id:
        _event_queue = get_event_queue(_bus_id)

    async def _push_event(event: dict):
        capture_public_thinking_event(state, event)
        if _event_queue:
            try:
                _event_queue.put_nowait(event)
            except Exception as _qe:
                logger.debug("[CODE_STUDIO] Event queue push failed: %s", _qe)

    tracer = get_or_create_tracer(state)
    tracer.start_step(step_names.DIRECT_RESPONSE, "Che tac dau ra ky thuat")

    domain_config = state.get("domain_config", {})
    domain_name_vi = domain_config.get("name_vi", "")
    if not domain_name_vi:
        domain_id = state.get("domain_id", settings_obj.default_domain)
        domain_name_vi = {
            "maritime": "Hang hai",
            "traffic_law": "Luat Giao thong",
        }.get(domain_id, domain_id)

    try:
        _ctx = state.get("context", {})
        explicit_provider = get_effective_provider(state)
        response = ""
        tools: list = []
        force_tools = False
        runtime_context_base = None
        if looks_like_ambiguous_simulation_request(query, state):
            grounded_query = ground_simulation_query_from_visual_context(query, state)
            if grounded_query:
                effective_query = grounded_query
                state["thinking_content"] = (
                    "Mình đang bám theo visual hiện tại để tiếp tục mô phỏng, "
                    "vì turn này tuy ngắn nhưng đã có đủ ngữ cảnh để không cần hỏi lại."
                )
                await _push_event({
                    "type": "status",
                    "content": f"Mình đang nối mô phỏng vào chủ đề hiện tại: `{last_inline_visual_title(state)}`...",
                    "step": "code_generation",
                    "node": "code_studio_agent",
                    "details": {"visibility": "status_only"},
                })
            else:
                response = build_ambiguous_simulation_clarifier(state)
                state["thinking_content"] = (
                    "Mình cần chốt rõ chủ đề mô phỏng trước khi mở canvas, "
                    "để khỏi dựng sai hiện tượng hoặc tạo một app lệch mục tiêu."
                )
                tracer.end_step(
                    result="Code studio clarification before build",
                    confidence=0.9,
                    details={"response_type": "clarify", "reason": "ambiguous_simulation_request"},
                )
        if not response:
            tools, force_tools = collect_code_studio_tools(effective_query, _ctx.get("user_role", "student"))
            try:
                from app.engine.skills.skill_recommender import select_runtime_tools

                selected_tools = select_runtime_tools(
                    tools,
                    query=effective_query,
                    intent=(state.get("routing_metadata") or {}).get("intent"),
                    user_role=_ctx.get("user_role", "student"),
                    max_tools=min(len(tools), 8),
                    must_include=code_studio_required_tool_names(
                        effective_query,
                        _ctx.get("user_role", "student"),
                    ),
                )
                if selected_tools:
                    tools = selected_tools
                    logger.info(
                        "[CODE_STUDIO] Runtime-selected tools: %s",
                        [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in tools],
                    )
            except Exception as _selection_err:
                logger.debug("[CODE_STUDIO] Runtime tool selection skipped: %s", _selection_err)

            runtime_context_base = build_tool_runtime_context_fn(
                event_bus_id=_bus_id,
                request_id=_ctx.get("request_id"),
                session_id=state.get("session_id"),
                organization_id=state.get("organization_id"),
                user_id=state.get("user_id"),
                user_role=_ctx.get("user_role", "student"),
                node="code_studio_agent",
                source="agentic_loop",
                metadata=build_visual_tool_runtime_metadata(state, effective_query),
            )

            fast_path_result = await execute_code_studio_fast_path(
                state=state,
                query=effective_query,
                tools=tools,
                push_event=_push_event,
                runtime_context_base=runtime_context_base,
            )

            if fast_path_result:
                response = fast_path_result["response"]
                state["thinking_content"] = fast_path_result["thinking_content"]
                state["tool_call_events"] = fast_path_result["tool_call_events"]
                state["tools_used"] = fast_path_result["tools_used"]
                tracer.end_step(
                    result=f"Code studio fast path: {fast_path_result.get('fast_path', 'recipe_scaffold')}",
                    confidence=0.91,
                    details={
                        "response_type": "capability_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                        "fast_path": fast_path_result.get("fast_path", "recipe_scaffold"),
                    },
                )
            else:
                from app.engine.multi_agent.agent_config import AgentConfigRegistry

                thinking_effort = state.get("thinking_effort")
                llm = AgentConfigRegistry.get_llm(
                    "code_studio_agent",
                    effort_override=thinking_effort,
                    provider_override=explicit_provider,
                    requested_model=state.get("model"),
                )
                if llm and getattr(settings_obj, "enable_natural_conversation", False) is True:
                    _pp = getattr(settings_obj, "llm_presence_penalty", 0.0)
                    _fp = getattr(settings_obj, "llm_frequency_penalty", 0.0)
                    if _pp or _fp:
                        try:
                            llm = llm.bind(presence_penalty=_pp, frequency_penalty=_fp)
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
                llm_with_tools, llm_auto, forced_tool_choice = bind_direct_tools(
                    llm,
                    tools,
                    force_tools,
                    provider=bound_provider,
                    include_forced_choice=True,
                )
                messages = build_direct_system_messages(
                    state,
                    effective_query,
                    domain_name_vi,
                    role_name="code_studio_agent",
                    tools_context_override=build_code_studio_tools_context(
                        settings_obj,
                        _ctx.get("user_role", "student"),
                        effective_query,
                    ),
                )
                llm_response, messages, _tc_events = await execute_code_studio_tool_rounds(
                    llm_with_tools,
                    llm_auto,
                    messages,
                    tools,
                    _push_event,
                    runtime_context_base=runtime_context_base,
                    query=effective_query,
                    state=state,
                    provider=state.get("provider"),
                    runtime_provider=bound_provider,
                    forced_tool_choice=forced_tool_choice,
                )

                if _tc_events:
                    state["tool_call_events"] = _tc_events

                response, thinking_content, tools_used = extract_direct_response(llm_response, messages)
                streamed_code_studio_answer = False
                if _event_queue and _tc_events:
                    try:
                        summary_provider = (
                            bound_provider
                            if bound_provider and str(bound_provider).strip().lower() != "auto"
                            else state.get("provider")
                        )
                        from app.engine.llm_pool import (
                            ThinkingTier,
                            get_llm_for_provider,
                        )

                        summary_llm = get_llm_for_provider(
                            summary_provider,
                            default_tier=ThinkingTier.MODERATE,
                            strict_pin=bool(
                                summary_provider
                                and str(summary_provider).strip().lower() != "auto"
                            ),
                        )
                        summary_messages = build_code_studio_stream_summary_messages(
                            state,
                            effective_query,
                            domain_name_vi,
                            tool_call_events=_tc_events,
                        )
                        streamed_summary_response, streamed_code_studio_answer = await stream_answer_with_fallback(
                            summary_llm,
                            summary_messages,
                            _push_event,
                            provider=summary_provider,
                            node="code_studio_agent",
                        )
                        streamed_response, _summary_thinking, _summary_tools = extract_direct_response(
                            streamed_summary_response,
                            summary_messages,
                        )
                        if streamed_response:
                            response = streamed_response
                    except Exception as _summary_err:
                        logger.warning(
                            "[CODE_STUDIO] Final streamed delivery summary failed, using buffered response: %s",
                            _summary_err,
                        )
                response = sanitize_code_studio_response(response, _tc_events, state)

                _safe_thinking = await build_code_studio_reasoning_summary(
                    effective_query,
                    state,
                    direct_tool_names(tools_used),
                )
                if _safe_thinking:
                    state["thinking_content"] = resolve_visible_thinking_from_lifecycle(
                        state,
                        fallback=_safe_thinking,
                        default_node="code_studio_agent",
                    )
                    if state.get("thinking_content"):
                        record_thinking_snapshot(
                            state,
                            state.get("thinking_content"),
                            node="code_studio_agent",
                            provenance="aligned_cleanup",
                        )

                if tools_used:
                    state["tools_used"] = tools_used

                tracer.end_step(
                    result=f"Code studio response: {len(response)} chars",
                    confidence=0.88,
                    details={
                        "response_type": "capability_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                        "streamed_delivery": streamed_code_studio_answer,
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

    if not state.get("thinking_content"):
        state["thinking_content"] = resolve_visible_thinking_from_lifecycle(
            state,
            fallback=await build_code_studio_reasoning_summary(
                query,
                state,
                direct_tool_names(state.get("tools_used", [])),
            ),
            default_node="code_studio_agent",
        )
    if state.get("thinking_content"):
        record_thinking_snapshot(
            state,
            state.get("thinking_content"),
            node="code_studio_agent",
            provenance="final_snapshot",
        )

    state["final_response"] = response
    state["agent_outputs"] = {"code_studio_agent": response}
    state["current_agent"] = "code_studio_agent"

    logger.info("[CODE_STUDIO] Response prepared, tracer passed to synthesizer")

    return state
