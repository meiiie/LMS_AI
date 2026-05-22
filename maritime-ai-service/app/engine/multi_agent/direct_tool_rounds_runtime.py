"""Tool-round runtime extracted from direct_execution."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Optional

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    DOC_COURSE_HOST_ACTION_TOOL as _DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL as _DOC_PREVIEW_HOST_ACTION_TOOL,
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
from app.engine.multi_agent.direct_final_synthesis_runtime import (
    build_direct_final_synthesis_instruction,
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
    DocumentHostActionShortcut,
    execute_requested_document_host_action_shortcut,
)
from app.engine.multi_agent.direct_document_preview_payloads import (
    _DOC_PREVIEW_LOW_VALUE_LABELS,
    _looks_uploaded_doc_course_request,
    _normalize_doc_preview_text,
    _is_doc_preview_scaffold_line,
    _is_doc_preview_low_value_line,
    _find_doc_preview_host_action_tool,
    _find_doc_course_host_action_tool,
    _should_request_uploaded_doc_course_preview,
    _should_request_uploaded_doc_preview,
    _first_nonempty_line,
    _select_doc_preview_title_line,
    _score_doc_preview_title_candidate,
    _is_doc_preview_cover_metadata_line,
    _clean_doc_preview_line,
    _extract_marker,
    _strip_doc_preview_goal_label,
    _is_doc_preview_ordered_action_line,
    _strip_doc_preview_ordered_action_prefix,
    _is_doc_preview_admonition_line,
    _repair_doc_preview_common_truncations,
    _clip_doc_preview_line,
    _shape_doc_preview_learning_goal,
    _supplement_doc_preview_learning_goals,
    _extract_relevant_lines,
    _extract_doc_preview_title_from_query,
    _polish_doc_preview_vietnamese_title,
    _is_low_value_doc_preview_title,
    _focus_doc_preview_markdown,
    _extract_source_pages,
    _resolve_doc_preview_lesson_id,
    _resolve_doc_preview_course_id,
    _extend_doc_context_id_candidates,
    _extract_doc_course_title_from_query,
    _doc_source_reference,
    _extract_doc_section_references,
    _match_doc_refs,
    _looks_holilihu_lms_manual_document,
    _looks_maritime_vessel_management_document,
    _looks_maritime_training_lms_document,
    _dedupe_doc_refs,
    _top_course_source_references,
    _lms_manual_lesson,
    _build_lms_manual_course_plan,
    _build_maritime_vessel_management_course_plan,
    _build_maritime_training_lms_course_plan,
    _extract_doc_headings,
    _section_candidate_markers,
    _copy_doc_refs_with_indices,
    _document_course_section_candidates,
    _cluster_document_course_sections,
    _select_lesson_section_candidates,
    _cluster_title,
    _lesson_refs_for_candidate,
    _classify_uploaded_document_course_domain,
    _build_document_course_quality_report,
    _build_generic_document_course_plan,
    _build_uploaded_doc_course_params,
    _build_uploaded_doc_preview_params,
)
from app.engine.multi_agent.direct_pointy_runtime import (
    _format_pointy_inventory,  # noqa: F401 - compatibility alias
    _validate_pointy_selector,  # noqa: F401 - compatibility alias
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_call_text_parser import (
    extract_raw_tool_calls_from_text,
    tool_names_from_tools,
)
from app.engine.multi_agent.direct_web_search_policy import (
    _has_search_tool_result,  # noqa: F401 - compatibility alias
    _is_search_tool_name,
    _prefer_official_query_for_known_docs,
    _should_return_search_template_after_tool_round,  # noqa: F401 - compatibility alias
    _should_use_search_template_for_empty_response,  # noqa: F401 - compatibility alias
)
from app.engine.multi_agent.visual_events import (
    _collect_active_visual_session_ids,
    _emit_visual_commit_events,
    _maybe_emit_host_action_event,
    _maybe_emit_visual_event,
    _summarize_tool_result_for_stream,
)

logger = logging.getLogger(__name__)

# Compatibility alias for older tests and graph imports while synthesis helpers move out.
_build_direct_final_synthesis_instruction = build_direct_final_synthesis_instruction

_DIRECT_DOCUMENT_PREVIEW_PAYLOAD_COMPAT_EXPORTS = (
    _DOC_PREVIEW_LOW_VALUE_LABELS,
    _looks_uploaded_doc_course_request,
    _normalize_doc_preview_text,
    _is_doc_preview_scaffold_line,
    _is_doc_preview_low_value_line,
    _find_doc_preview_host_action_tool,
    _find_doc_course_host_action_tool,
    _should_request_uploaded_doc_course_preview,
    _should_request_uploaded_doc_preview,
    _first_nonempty_line,
    _select_doc_preview_title_line,
    _score_doc_preview_title_candidate,
    _is_doc_preview_cover_metadata_line,
    _clean_doc_preview_line,
    _extract_marker,
    _strip_doc_preview_goal_label,
    _is_doc_preview_ordered_action_line,
    _strip_doc_preview_ordered_action_prefix,
    _is_doc_preview_admonition_line,
    _repair_doc_preview_common_truncations,
    _clip_doc_preview_line,
    _shape_doc_preview_learning_goal,
    _supplement_doc_preview_learning_goals,
    _extract_relevant_lines,
    _extract_doc_preview_title_from_query,
    _polish_doc_preview_vietnamese_title,
    _is_low_value_doc_preview_title,
    _focus_doc_preview_markdown,
    _extract_source_pages,
    _resolve_doc_preview_lesson_id,
    _resolve_doc_preview_course_id,
    _extend_doc_context_id_candidates,
    _extract_doc_course_title_from_query,
    _doc_source_reference,
    _extract_doc_section_references,
    _match_doc_refs,
    _looks_holilihu_lms_manual_document,
    _looks_maritime_vessel_management_document,
    _looks_maritime_training_lms_document,
    _dedupe_doc_refs,
    _top_course_source_references,
    _lms_manual_lesson,
    _build_lms_manual_course_plan,
    _build_maritime_vessel_management_course_plan,
    _build_maritime_training_lms_course_plan,
    _extract_doc_headings,
    _section_candidate_markers,
    _copy_doc_refs_with_indices,
    _document_course_section_candidates,
    _cluster_document_course_sections,
    _select_lesson_section_candidates,
    _cluster_title,
    _lesson_refs_for_candidate,
    _classify_uploaded_document_course_domain,
    _build_document_course_quality_report,
    _build_generic_document_course_plan,
    _build_uploaded_doc_course_params,
    _build_uploaded_doc_preview_params,
)

_DOC_COURSE_HOST_ACTION_SHORTCUT = DocumentHostActionShortcut(
    tool_name=_DOC_COURSE_HOST_ACTION_TOOL,
    tool_call_id="forced_doc_course_preview_0",
    thinking=(
        "Mình nhận đây là flow tạo cấu trúc khóa học từ tài liệu upload. "
        "Vì thao tác này có thể sinh nhiều chương/bài trong LMS, mình dựng "
        "course_plan có nguồn trích dẫn trước và chỉ gửi host action preview; LMS sẽ "
        "yêu cầu giáo viên bấm Áp dụng để cấp approval_token trước khi ghi dữ liệu."
    ),
    thinking_summary="Tạo cây khóa học từ tài liệu",
    thinking_provenance="deterministic_document_course_host_action",
    response=(
        "Mình đã gửi bản thiết kế khóa học từ tài liệu sang LMS. "
        "Bạn xem cây chương/bài và nguồn trích dẫn trong hộp xem trước, rồi chỉ bấm Áp dụng "
        "nếu muốn LMS tạo các chương/bài draft tương ứng."
    ),
    failure_log_message="[DIRECT] Deterministic document course host action failed: %s",
)

_DOC_PREVIEW_HOST_ACTION_SHORTCUT = DocumentHostActionShortcut(
    tool_name=_DOC_PREVIEW_HOST_ACTION_TOOL,
    tool_call_id="forced_doc_preview_0",
    thinking=(
        "Mình nhận đây là flow upload tài liệu -> tạo preview bài học. "
        "Vì đây là đường ghi LMS có ràng buộc an toàn, mình không chờ model tự gọi tool; "
        "mình dựng payload preview từ document_context và gửi host action preview-only để LMS mở phần so sánh thay đổi và nguồn trích dẫn trước."
    ),
    thinking_summary="Tao preview bai hoc tu tai lieu",
    thinking_provenance="deterministic_document_preview_host_action",
    response=(
        "Mình đã gửi bản preview từ tài liệu sang LMS. "
        "Bạn kiểm tra phần so sánh thay đổi và nguồn trích dẫn trong hộp xem trước, rồi chỉ bấm Áp dụng nếu nội dung đúng."
    ),
    failure_log_message="[DIRECT] Deterministic document preview host action failed: %s",
)

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
        _extract_runtime_target,
        _inject_widget_blocks_from_tool_results,
        _remember_runtime_target,
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
    request_failover_mode = (
        FAILOVER_MODE_PINNED
        if provider and str(provider).strip().lower() != "auto"
        else FAILOVER_MODE_AUTO
    )
    resolved_provider = _extract_runtime_target(llm_base or llm_auto or llm_with_tools)[0]
    graph_module = sys.modules.get("app.engine.multi_agent.graph")
    graph_ainvoke_with_fallback = getattr(
        graph_module,
        "_ainvoke_with_fallback",
        ainvoke_with_fallback,
    )
    graph_stream_direct_answer_with_fallback = getattr(
        graph_module,
        "_stream_direct_answer_with_fallback",
        stream_direct_answer_with_fallback,
    )
    graph_stream_direct_wait_heartbeats = getattr(
        graph_module,
        "_stream_direct_wait_heartbeats",
        stream_direct_wait_heartbeats,
    )
    graph_build_direct_tool_reflection = getattr(
        graph_module,
        "_build_direct_tool_reflection",
        _build_direct_tool_reflection,
    )
    graph_maybe_emit_host_action_event = getattr(
        graph_module,
        "_maybe_emit_host_action_event",
        _maybe_emit_host_action_event,
    )
    graph_maybe_emit_visual_event = getattr(
        graph_module,
        "_maybe_emit_visual_event",
        _maybe_emit_visual_event,
    )
    graph_emit_visual_commit_events = getattr(
        graph_module,
        "_emit_visual_commit_events",
        _emit_visual_commit_events,
    )
    graph_get_tool_by_name = getattr(
        graph_module,
        "get_tool_by_name",
        _get_tool_by_name_impl,
    )
    graph_invoke_tool_with_runtime = getattr(
        graph_module,
        "invoke_tool_with_runtime",
        _invoke_tool_with_runtime_impl,
    )

    def remember_execution_target(
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> tuple[str | None, str | None]:
        provider_name, model_name = _remember_runtime_target(state, candidate_llm)
        if (not provider_name or not model_name) and fallback_source is not None:
            fallback_provider, fallback_model = _remember_runtime_target(
                state,
                fallback_source,
            )
            provider_name = provider_name or fallback_provider
            model_name = model_name or fallback_model
        return provider_name, model_name

    def runtime_tier_for(
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> str:
        for source in (candidate_llm, fallback_source, llm_base, llm_auto, llm_with_tools):
            tier_value = getattr(source, "_wiii_tier_key", None) if source is not None else None
            if isinstance(tier_value, str) and tier_value.strip():
                return tier_value.strip().lower()
        return "moderate"

    opening_cue, direct_thinking_stop, initial_heartbeat, opening_thinking_started = await start_direct_opening_phase_impl(
        query=query,
        state=state,
        push_event=push_event,
        infer_direct_reasoning_cue=_infer_direct_reasoning_cue,
        stream_direct_wait_heartbeats=graph_stream_direct_wait_heartbeats,
    )
    streamed_direct_answer = False
    try:
        forced_web_response = await execute_forced_web_search_shortcut(
            query=query,
            state=state,
            tools=tools,
            messages=messages,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            runtime_context_base=runtime_context_base,
            get_tool_by_name=graph_get_tool_by_name,
            invoke_tool_with_runtime=graph_invoke_tool_with_runtime,
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
            invoke_tool_with_runtime=graph_invoke_tool_with_runtime,
            maybe_emit_host_action_event=graph_maybe_emit_host_action_event,
            summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
            should_request_course_preview=_should_request_uploaded_doc_course_preview,
            find_course_host_action_tool=_find_doc_course_host_action_tool,
            build_course_params=_build_uploaded_doc_course_params,
            course_shortcut=_DOC_COURSE_HOST_ACTION_SHORTCUT,
            should_request_lesson_preview=_should_request_uploaded_doc_preview,
            find_lesson_host_action_tool=_find_doc_preview_host_action_tool,
            build_lesson_params=_build_uploaded_doc_preview_params,
            lesson_shortcut=_DOC_PREVIEW_HOST_ACTION_SHORTCUT,
            build_assistant_message=_build_assistant_message,
            uploaded_document_attachments_from_state=_uploaded_document_attachments_from_state,
            logger_obj=logger,
        )
        if document_shortcut_response is not None:
            return document_shortcut_response, messages, tool_call_events

        if tools and forced_tool_choice:
            # Forced tool choice — use ainvoke to ensure tool calls happen
            candidate_provider, _candidate_model = remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response = await graph_ainvoke_with_fallback(
                llm_with_tools,
                messages,
                tools=tools,
                tool_choice=forced_tool_choice,
                tier=runtime_tier_for(llm_with_tools, llm_base),
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=request_failover_mode,
                push_event=push_event,
                timeout_profile=initial_timeout_profile,
                state=state,
                allowed_fallback_providers=allowed_fallback_providers,
            )
        else:
            candidate_provider, _candidate_model = remember_execution_target(
                llm_with_tools,
                fallback_source=llm_base,
            )
            resolved_provider = candidate_provider or resolved_provider
            llm_response, streamed_direct_answer = await graph_stream_direct_answer_with_fallback(
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
            get_tool_by_name=graph_get_tool_by_name,
            invoke_tool_with_runtime=graph_invoke_tool_with_runtime,
            is_search_tool_name=_is_search_tool_name,
            prefer_official_query_for_known_docs=_prefer_official_query_for_known_docs,
            summarize_tool_result_for_stream=_summarize_tool_result_for_stream,
            maybe_emit_host_action_event=graph_maybe_emit_host_action_event,
            maybe_emit_visual_event=graph_maybe_emit_visual_event,
            emit_visual_commit_events=graph_emit_visual_commit_events,
            build_direct_tool_reflection=graph_build_direct_tool_reflection,
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
            ainvoke_with_fallback=graph_ainvoke_with_fallback,
            stream_direct_wait_heartbeats=graph_stream_direct_wait_heartbeats,
            remember_execution_target=remember_execution_target,
            runtime_tier_for=runtime_tier_for,
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
        ainvoke_with_fallback=graph_ainvoke_with_fallback,
        stream_direct_wait_heartbeats=graph_stream_direct_wait_heartbeats,
        remember_execution_target=remember_execution_target,
        runtime_tier_for=runtime_tier_for,
        inject_widget_blocks_from_tool_results=_inject_widget_blocks_from_tool_results,
        structured_visuals_enabled=visual_policy.structured_visuals_enabled,
        logger_obj=logger,
    )

    return finalization.llm_response, finalization.messages, tool_call_events
