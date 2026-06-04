"""Tool-round runtime extracted from direct_execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    uploaded_document_attachments_from_state as _uploaded_document_attachments_from_state,
)
from app.engine.multi_agent.direct_opening_runtime import (
    finalize_direct_opening_phase_impl,
    start_direct_opening_phase_impl,
)
from app.engine.multi_agent.direct_tool_message_runtime import (
    build_assistant_message as _build_assistant_message,
    build_assistant_tool_call_message as _build_assistant_tool_call_message,
    build_tool_result_message as _build_tool_result_message,
)
from app.engine.multi_agent.direct_tool_post_dispatch_runtime import (
    process_direct_tool_post_dispatch,
)
from app.engine.multi_agent.direct_tool_call_response_runtime import (
    prepare_direct_tool_call_response,
)
from app.engine.multi_agent.direct_tool_round_execution_runtime import (
    execute_direct_tool_round,
)
from app.engine.multi_agent.direct_tool_dispatch_runtime import (
    dispatch_direct_tool_call,
    normalize_tool_call as _normalize_tool_call,
)
from app.engine.multi_agent.direct_tool_convergence_runtime import (
    append_direct_tool_convergence_hint,
)
from app.engine.multi_agent.direct_tool_followup_runtime import (
    invoke_direct_tool_followup,
)
from app.engine.multi_agent.direct_tool_response_finalization_runtime import (
    finalize_direct_tool_response,
)
from app.engine.multi_agent.direct_reasoning import (
    _build_direct_tool_reflection,
    _infer_direct_reasoning_cue,
)
from app.engine.multi_agent.direct_search_template_runtime import (
    build_direct_post_tool_search_template_response,
)
from app.engine.multi_agent.direct_forced_web_search_runtime import (
    execute_forced_web_search_shortcut,
)
from app.engine.multi_agent.direct_visual_tool_policy_runtime import (
    build_direct_visual_tool_policy,
)
from app.engine.multi_agent.direct_document_host_action_runtime import (
    execute_requested_document_host_action_shortcut,
)
from app.engine.multi_agent.direct_document_host_action_shortcuts import (
    DOC_COURSE_HOST_ACTION_SHORTCUT,
    DOC_PREVIEW_HOST_ACTION_SHORTCUT,
)
from app.engine.multi_agent.direct_document_preview_payloads import (
    _find_doc_preview_host_action_tool,
    _find_doc_course_host_action_tool,
    _should_request_uploaded_doc_course_preview,
    _should_request_uploaded_doc_preview,
    _build_uploaded_doc_course_params,
    _build_uploaded_doc_preview_params,
)
from app.engine.multi_agent.external_app_action_runtime import (
    external_app_action_final_answer,
    prepare_external_app_action_turn,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_call_text_parser import (
    extract_raw_tool_calls_from_text,
    tool_names_from_tools,
)
from app.engine.multi_agent.direct_web_search_policy import (
    _is_search_tool_name,
    _prefer_official_query_for_known_docs,
)
from app.engine.multi_agent.visual_events import (
    _collect_active_visual_session_ids,
    _emit_visual_commit_events,
    _maybe_emit_host_action_event,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)

logger = logging.getLogger(__name__)

async def execute_direct_tool_rounds_impl(
    llm_with_tools,
    llm_auto,
    messages: list,
    tools: list,
    push_event,
    *,
    runtime_context_base=None,
    max_rounds: int = 3,
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    forced_tool_choice: str | None = None,
    llm_base=None,
    direct_answer_timeout_profile: str | None = None,
    direct_answer_primary_timeout: float | None = None,
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None = None,
    ainvoke_with_fallback,
    stream_direct_answer_with_fallback,
    stream_direct_wait_heartbeats,
    push_status_only_progress,
    native_tool_messages: bool = False,
):
    """Execute multi-round tool calling loop for direct response."""
    from app.engine.tools.invocation import (
        get_tool_by_name as _get_tool_by_name_impl,
        invoke_tool_with_runtime as _invoke_tool_with_runtime_impl,
    )
    from app.engine.multi_agent.direct_runtime_bindings import (
        build_direct_tool_provider_policy,
        _inject_widget_blocks_from_tool_results,
        resolve_direct_tool_runtime_bindings,
    )
    from app.engine.llm_pool import (
        FAILOVER_MODE_AUTO,
        FAILOVER_MODE_PINNED,
        TIMEOUT_PROFILE_BACKGROUND,
        TIMEOUT_PROFILE_STRUCTURED,
    )

    tool_call_events: list[dict] = []
    state = state or {}
    direct_thinking_stop = asyncio.Event()
    visual_policy = build_direct_visual_tool_policy(
        query=query,
        settings_obj=settings,
        timeout_profile_structured=TIMEOUT_PROFILE_STRUCTURED,
        timeout_profile_background=TIMEOUT_PROFILE_BACKGROUND,
    )
    visual_decision = visual_policy.visual_decision
    requires_visual_commit = visual_policy.requires_visual_commit
    initial_timeout_profile = visual_policy.initial_timeout_profile
    followup_timeout_profile = visual_policy.followup_timeout_profile
    visual_emitted_any = False
    provider_policy = build_direct_tool_provider_policy(
        state=state,
        provider=provider,
        llm_base=llm_base,
        llm_auto=llm_auto,
        llm_with_tools=llm_with_tools,
        failover_mode_auto=FAILOVER_MODE_AUTO,
        failover_mode_pinned=FAILOVER_MODE_PINNED,
    )
    request_failover_mode = provider_policy.request_failover_mode
    resolved_provider = provider_policy.resolved_provider
    tool_runtime_bindings = resolve_direct_tool_runtime_bindings(
        ainvoke_with_fallback=ainvoke_with_fallback,
        stream_direct_answer_with_fallback=stream_direct_answer_with_fallback,
        stream_direct_wait_heartbeats=stream_direct_wait_heartbeats,
        build_direct_tool_reflection=_build_direct_tool_reflection,
        maybe_emit_host_action_event=_maybe_emit_host_action_event,
        maybe_emit_visual_event=_maybe_emit_visual_event,
        emit_visual_commit_events=_emit_visual_commit_events,
        get_tool_by_name=_get_tool_by_name_impl,
        invoke_tool_with_runtime=_invoke_tool_with_runtime_impl,
    )

    opening_cue, direct_thinking_stop, initial_heartbeat, opening_thinking_started = await start_direct_opening_phase_impl(
        query=query,
        state=state,
        push_event=push_event,
        infer_direct_reasoning_cue=_infer_direct_reasoning_cue,
        stream_direct_wait_heartbeats=tool_runtime_bindings.stream_direct_wait_heartbeats,
    )
    streamed_direct_answer = False
    try:
        external_action_preparation = prepare_external_app_action_turn(
            query=query,
            state=state,
            tools=tools,
            forced_tool_choice=forced_tool_choice,
            native_tool_messages=native_tool_messages,
            build_assistant_message=_build_assistant_message,
        )
        if external_action_preparation.preempted:
            return (
                external_action_preparation.preflight_response,
                messages,
                tool_call_events,
            )
        tools = external_action_preparation.tools
        forced_tool_choice = external_action_preparation.forced_tool_choice

        forced_web_response = await execute_forced_web_search_shortcut(
            query=query,
            state=state,
            tools=tools,
            messages=messages,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            runtime_context_base=runtime_context_base,
            get_tool_by_name=tool_runtime_bindings.get_tool_by_name,
            invoke_tool_with_runtime=tool_runtime_bindings.invoke_tool_with_runtime,
            summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
            logger_obj=logger,
        )
        if forced_web_response is not None:
            return forced_web_response, messages, tool_call_events

        document_shortcut_response = await execute_requested_document_host_action_shortcut(
            query=query,
            state=state,
            tools=tools,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            runtime_context_base=runtime_context_base,
            invoke_tool_with_runtime=tool_runtime_bindings.invoke_tool_with_runtime,
            maybe_emit_host_action_event=tool_runtime_bindings.maybe_emit_host_action_event,
            summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
            should_request_course_preview=_should_request_uploaded_doc_course_preview,
            find_course_host_action_tool=_find_doc_course_host_action_tool,
            build_course_params=_build_uploaded_doc_course_params,
            course_shortcut=DOC_COURSE_HOST_ACTION_SHORTCUT,
            should_request_lesson_preview=_should_request_uploaded_doc_preview,
            find_lesson_host_action_tool=_find_doc_preview_host_action_tool,
            build_lesson_params=_build_uploaded_doc_preview_params,
            lesson_shortcut=DOC_PREVIEW_HOST_ACTION_SHORTCUT,
            build_assistant_message=_build_assistant_message,
            uploaded_document_attachments_from_state=_uploaded_document_attachments_from_state,
            logger_obj=logger,
        )
        if document_shortcut_response is not None:
            return document_shortcut_response, messages, tool_call_events

        if tools and forced_tool_choice:
            # Forced tool choice — use ainvoke to ensure tool calls happen
            candidate_provider, _candidate_model = provider_policy.remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response = await tool_runtime_bindings.ainvoke_with_fallback(
                llm_with_tools,
                messages,
                tools=tools,
                tool_choice=forced_tool_choice,
                tier=provider_policy.runtime_tier_for(llm_with_tools, llm_base),
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                push_event=push_event,
                timeout_profile=initial_timeout_profile,
                state=state,
                allowed_fallback_providers=allowed_fallback_providers,
            )
        else:
            candidate_provider, _candidate_model = provider_policy.remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response, streamed_direct_answer = await tool_runtime_bindings.stream_direct_answer_with_fallback(
                llm_with_tools,
                messages,
                push_event,
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                thinking_stop_signal=direct_thinking_stop,
                thinking_block_opened=opening_thinking_started,
                state=state,
                primary_timeout=direct_answer_primary_timeout,
                timeout_profile=direct_answer_timeout_profile,
                allowed_fallback_providers=allowed_fallback_providers,
            )
    finally:
        await finalize_direct_opening_phase_impl(
            thinking_stop=direct_thinking_stop,
            heartbeat_task=initial_heartbeat,
            logger_obj=logger,
        )

    tool_call_response = prepare_direct_tool_call_response(
        llm_response=llm_response,
        tools=tools,
        native_tool_messages=native_tool_messages,
        extract_raw_tool_calls_from_text=extract_raw_tool_calls_from_text,
        tool_names_from_tools=tool_names_from_tools,
        build_assistant_tool_call_message=_build_assistant_tool_call_message,
        logger_obj=logger,
    )
    llm_response = tool_call_response.llm_response
    if not streamed_direct_answer and opening_thinking_started:
        await push_event({"type": "thinking_end", "content": "", "node": "direct"})

    # Phase 35 — normalize tool_call shapes. NVIDIA OpenAI-compat returns
    # raw dicts; Google compat + Anthropic adapter convert via
    # `from_openai_response` → pydantic `ToolCall(id, name, arguments)`.
    # Existing loop body assumes dict access (`tc.get("args")`). Normalize
    # here so both shapes work without rewriting 50+ lines downstream.
    for tool_round in range(max_rounds):
        if not (tools and hasattr(llm_response, "tool_calls") and llm_response.tool_calls):
            break
        round_execution = await execute_direct_tool_round(
            llm_response=llm_response,
            tool_round=tool_round,
            tools=tools,
            query=query,
            state=state,
            messages=messages,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            visual_emitted_any=visual_emitted_any,
            runtime_context_base=runtime_context_base,
            handoffs_enabled=settings.enable_agent_handoffs,
            get_tool_by_name=tool_runtime_bindings.get_tool_by_name,
            invoke_tool_with_runtime=tool_runtime_bindings.invoke_tool_with_runtime,
            is_search_tool_name=_is_search_tool_name,
            prefer_official_query_for_known_docs=_prefer_official_query_for_known_docs,
            summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
            maybe_emit_host_action_event=tool_runtime_bindings.maybe_emit_host_action_event,
            maybe_emit_visual_event=tool_runtime_bindings.maybe_emit_visual_event,
            emit_visual_commit_events=tool_runtime_bindings.emit_visual_commit_events,
            build_direct_tool_reflection=tool_runtime_bindings.build_direct_tool_reflection,
            push_status_only_progress=push_status_only_progress,
            build_tool_result_message=_build_tool_result_message,
            normalize_tool_call=_normalize_tool_call,
            infer_direct_reasoning_cue=_infer_direct_reasoning_cue,
            collect_active_visual_session_ids=_collect_active_visual_session_ids,
            dispatch_direct_tool_call=dispatch_direct_tool_call,
            process_direct_tool_post_dispatch=process_direct_tool_post_dispatch,
            logger_obj=logger,
        )
        round_tool_names = round_execution.round_tool_names
        round_cue = round_execution.round_cue
        visual_emitted_any = round_execution.visual_emitted_any

        search_template_response = build_direct_post_tool_search_template_response(
            query=query,
            state=state,
            tool_call_events=tool_call_events,
            tool_round=tool_round,
            native_tool_messages=native_tool_messages,
            logger_obj=logger,
        )
        if search_template_response is not None:
            return search_template_response, messages, tool_call_events

        external_action_answer = external_app_action_final_answer(
            tool_call_events,
        )
        if external_action_answer:
            state["_final_answer_trace"] = {
                "version": "final_answer_trace.v1",
                "source": "wiii_connect_action_result",
                "reason": "external_app_action_payload",
                "status": "resolved",
                "answer_present": True,
            }
            return (
                _build_assistant_message(
                    external_action_answer,
                    native_tool_messages=native_tool_messages,
                ),
                messages,
                tool_call_events,
            )

        # Phase 35 — convergence self-eval rubric injected after round 0.
        # SOTA Anthropic Claude tool-use pattern: explicit "is info sufficient?"
        # check between rounds. ONLY inject when round 0 returned sparse content
        # (< 2500 chars) — when search already rich, avoid extra NVIDIA round
        # (each round adds 30-60s on free tier).
        append_direct_tool_convergence_hint(
            messages=messages,
            tool_round=tool_round,
            tool_call_events=tool_call_events,
            requires_visual_commit=requires_visual_commit,
            native_tool_messages=native_tool_messages,
            logger_obj=logger,
        )
        followup_invocation = await invoke_direct_tool_followup(
            llm_auto=llm_auto,
            llm_base=llm_base,
            llm_with_tools=llm_with_tools,
            tools=tools,
            messages=messages,
            query=query,
            push_event=push_event,
            requires_visual_commit=requires_visual_commit,
            visual_emitted_any=visual_emitted_any,
            visual_decision=visual_decision,
            resolved_provider=resolved_provider,
            provider=provider,
            request_failover_mode=request_failover_mode,
            followup_timeout_profile=followup_timeout_profile,
            state=state,
            allowed_fallback_providers=allowed_fallback_providers,
            ainvoke_with_fallback=tool_runtime_bindings.ainvoke_with_fallback,
            stream_direct_wait_heartbeats=tool_runtime_bindings.stream_direct_wait_heartbeats,
            remember_execution_target=provider_policy.remember_execution_target,
            runtime_tier_for=provider_policy.runtime_tier_for,
            round_cue=round_cue,
            round_tool_names=round_tool_names,
            logger_obj=logger,
        )
        llm_response = followup_invocation.llm_response
        resolved_provider = followup_invocation.resolved_provider
    if streamed_direct_answer and not tool_call_events:
        state["_answer_streamed_via_bus"] = True
        return llm_response, messages, tool_call_events

    finalization = await finalize_direct_tool_response(
        llm_response=llm_response,
        messages=messages,
        tools=tools,
        tool_call_events=tool_call_events,
        query=query,
        state=state,
        push_event=push_event,
        native_tool_messages=native_tool_messages,
        llm_base=llm_base,
        llm_auto=llm_auto,
        llm_with_tools=llm_with_tools,
        provider=provider,
        resolved_provider=resolved_provider,
        request_failover_mode=request_failover_mode,
        allowed_fallback_providers=allowed_fallback_providers,
        ainvoke_with_fallback=tool_runtime_bindings.ainvoke_with_fallback,
        stream_direct_wait_heartbeats=tool_runtime_bindings.stream_direct_wait_heartbeats,
        remember_execution_target=provider_policy.remember_execution_target,
        runtime_tier_for=provider_policy.runtime_tier_for,
        inject_widget_blocks_from_tool_results=_inject_widget_blocks_from_tool_results,
        structured_visuals_enabled=visual_policy.structured_visuals_enabled,
        logger_obj=logger,
    )

    return finalization.llm_response, finalization.messages, tool_call_events
