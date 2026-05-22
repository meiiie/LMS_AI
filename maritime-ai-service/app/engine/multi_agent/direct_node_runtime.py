"""Direct node runtime extracted from the graph shell."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_failover_runtime import classify_failover_reason_impl
from app.engine.multi_agent.document_preview_contract import (
    has_uploaded_document_context as _has_uploaded_document_context,
    uploaded_document_attachments_from_context as _uploaded_document_attachments,
)
from app.engine.multi_agent.direct_node_document_preview_runtime import (
    execute_direct_node_document_preview_round,
)
from app.engine.multi_agent.direct_node_fast_response_runtime import (
    resolve_direct_node_fast_response,
)
from app.engine.multi_agent.direct_node_host_timeout import (
    run_direct_node_execution_with_host_timeout,
)
from app.engine.multi_agent.direct_node_execution_prep import (
    prepare_direct_node_tool_execution,
)
from app.engine.multi_agent.direct_node_llm_preflight import (
    apply_direct_node_natural_conversation_penalties,
    maybe_build_uploaded_visual_guard,
    select_direct_node_llm,
)
from app.engine.multi_agent.direct_node_response_cleanup import (
    apply_source_backed_empty_response_fallback,
    clean_direct_node_llm_response,
)
from app.engine.multi_agent.direct_node_visible_thinking_finalization import (
    finalize_direct_node_visible_thinking,
)
from app.engine.multi_agent.direct_node_document_preview_rebind import (
    _direct_role_candidates,
    _rebind_document_preview_host_action_tool,
)
from app.engine.multi_agent.direct_intent import (
    _looks_emotional_support_turn,
    _normalize_for_intent,
)
from app.engine.multi_agent.direct_reasoning import (
    _is_codebase_analysis_query,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
    looks_like_search_placeholder_answer,
)
from app.engine.multi_agent.direct_session_memory_runtime import (
    _build_session_memory_write_answer,
    _build_session_memory_write_thinking,
    _extract_session_memory_items_from_text,
    _extract_session_memory_recall_answer,
    _with_requested_response_marker,
)
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.direct_node_chatter_runtime import (
    _build_hunger_chatter_answer,
    _build_hunger_chatter_thinking,
    _looks_hunger_chatter_turn,
)
from app.engine.multi_agent.direct_node_meta_fast_paths import (
    _build_reasoning_safety_meta_answer,
    _build_reasoning_safety_meta_thinking,
    _build_self_feeling_probe_answer,
    _build_self_feeling_probe_thinking,
    _build_wiii_capability_inventory_answer,
    _build_wiii_capability_inventory_thinking,
    _looks_self_feeling_probe_turn,
)
from app.engine.multi_agent.direct_node_emergency_fallbacks import (
    _emergency_search_fallback,
    _emit_synthetic_tool_events,
    _salvage_direct_turn_from_final_result,
)
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _DSML_BLOCK_RE,
    _DSML_STRAY_ASCII_RE,
    _DSML_STRAY_FULLWIDTH_RE,
    _GENERIC_DIRECT_FALLBACK_MARKERS,
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
    _build_image_input_thinking,
    _build_image_input_unavailable_answer,
    _build_image_input_unavailable_thinking,
    _build_pointy_fast_path_thinking,
    _build_pointy_missing_inventory_answer,
    _build_pointy_missing_inventory_thinking,
    _build_wiii_pipeline_meta_answer,
    _build_wiii_pipeline_meta_thinking,
    _clean_emergency_web_search_query,
    _extract_direct_reply_only_answer,
    _extract_pointy_fast_path_answer,
    _is_explicit_web_search_turn_for_direct,
    _looks_generic_direct_fallback_response,
    _pointy_requested_without_inventory,
    _should_use_codebase_source_note_fast_answer,
    _strip_dsml_residue,
)
from app.engine.multi_agent.direct_node_thinking_effort import (
    _DIRECT_ANALYTICAL_THINKING_MODES,
    _DIRECT_CANONICAL_THINKING_EFFORT_ALIASES,
    _canonicalize_direct_thinking_effort,
    _resolve_direct_thinking_effort,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_tool_selection import select_direct_node_tools
from app.engine.multi_agent.direct_node_uploaded_context import (
    _build_image_input_answer,
    _build_uploaded_document_context_fallback_answer,
    _build_uploaded_document_visual_guard_answer,
    _first_markdown_line,
    _image_payload_attr,
    _looks_uploaded_context_fact_query,
    _looks_uploaded_document_preview_request,
    _looks_uploaded_file_metadata_query,
    _looks_uploaded_file_visual_inspection_query,
    _plain_markdown_excerpt,
    _provider_likely_supports_image_blocks,
    _uploaded_context_has_video,
)
from app.engine.multi_agent.direct_node_visible_thought import (
    _DIRECT_ENGLISH_PLANNER_MARKERS,
    _DIRECT_INTERNAL_THOUGHT_MARKERS,
    _DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS,
    _DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL,
    _DIRECT_WOVEN_THOUGHT_INTENTS,
    _IDENTITY_LORE_MARKERS,
    _IDENTITY_ORIGIN_QUERY_MARKERS,
    _compact_basic_identity_answer,
    _extract_direct_woven_thought,
    _looks_like_direct_english_planner_thought,
    _strip_direct_inline_private_asides,
    _trim_direct_visible_thought_answer_draft,
)
from app.engine.runtime.runtime_metrics import inc_counter
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    align_visible_thinking_language,
    record_thinking_snapshot,
)
from app.engine.multi_agent.supervisor_runtime_support import (
    _looks_reasoning_safety_meta_turn,
    _looks_session_memory_ack_only_turn,
    _looks_session_memory_recall_turn,
    _looks_session_memory_write_turn,
    _looks_wiii_capability_inventory_turn,
    _looks_wiii_pipeline_meta_turn,
)

logger = logging.getLogger(__name__)

_DIRECT_SESSION_MEMORY_COMPAT_EXPORTS = (
    _build_session_memory_write_answer,
    _build_session_memory_write_thinking,
    _extract_session_memory_items_from_text,
    _extract_session_memory_recall_answer,
    _with_requested_response_marker,
)

_DIRECT_FAST_RESPONSE_COMPAT_EXPORTS = (
    _build_hunger_chatter_answer,
    _build_hunger_chatter_thinking,
    _build_pointy_fast_path_thinking,
    _build_pointy_missing_inventory_answer,
    _build_pointy_missing_inventory_thinking,
    _build_reasoning_safety_meta_answer,
    _build_reasoning_safety_meta_thinking,
    _build_self_feeling_probe_answer,
    _build_self_feeling_probe_thinking,
    _build_wiii_capability_inventory_answer,
    _build_wiii_capability_inventory_thinking,
    _build_wiii_pipeline_meta_answer,
    _build_wiii_pipeline_meta_thinking,
    _extract_direct_reply_only_answer,
    _extract_pointy_fast_path_answer,
    _fold_direct_text,
    _looks_hunger_chatter_turn,
    _looks_reasoning_safety_meta_turn,
    _looks_self_feeling_probe_turn,
    _looks_session_memory_ack_only_turn,
    _looks_session_memory_recall_turn,
    _looks_session_memory_write_turn,
    _looks_wiii_capability_inventory_turn,
    _looks_wiii_pipeline_meta_turn,
    _pointy_requested_without_inventory,
)

_DIRECT_VISIBLE_THOUGHT_COMPAT_EXPORTS = (
    align_visible_thinking_language,
    _DIRECT_ENGLISH_PLANNER_MARKERS,
    _DIRECT_INTERNAL_THOUGHT_MARKERS,
    _DIRECT_VISIBLE_THOUGHT_DRAFT_SPLITTERS,
    _DIRECT_VISIBLE_THOUGHT_TRAILING_SELF_EVAL,
    _DIRECT_WOVEN_THOUGHT_INTENTS,
    _IDENTITY_LORE_MARKERS,
    _extract_direct_woven_thought,
    _looks_like_direct_english_planner_thought,
    _trim_direct_visible_thought_answer_draft,
)

_DIRECT_UPLOADED_CONTEXT_COMPAT_EXPORTS = (
    _uploaded_document_attachments,
    _image_payload_attr,
    _first_markdown_line,
    _plain_markdown_excerpt,
    _uploaded_context_has_video,
    _build_uploaded_document_context_fallback_answer,
    _looks_uploaded_context_fact_query,
    _looks_uploaded_file_metadata_query,
    _looks_uploaded_file_visual_inspection_query,
    _provider_likely_supports_image_blocks,
)

_DIRECT_OPERATIONAL_FAST_PATH_COMPAT_EXPORTS = (
    _normalize_for_intent,
    _DSML_BLOCK_RE,
    _DSML_STRAY_ASCII_RE,
    _DSML_STRAY_FULLWIDTH_RE,
    _GENERIC_DIRECT_FALLBACK_MARKERS,
    _build_image_input_thinking,
    _clean_emergency_web_search_query,
    _strip_dsml_residue,
)

_DIRECT_THINKING_EFFORT_COMPAT_EXPORTS = (
    _DIRECT_ANALYTICAL_THINKING_MODES,
    _DIRECT_CANONICAL_THINKING_EFFORT_ALIASES,
    _IDENTITY_ORIGIN_QUERY_MARKERS,
    _canonicalize_direct_thinking_effort,
)

_DIRECT_DOCUMENT_PREVIEW_REBIND_COMPAT_EXPORTS = (
    _direct_role_candidates,
    _rebind_document_preview_host_action_tool,
)

_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS = 45.0  # Phase F3 (2026-05-06): bumped 24→45s. NVIDIA DeepSeek tool-heavy pointy turns (inventory + show + synthesis) regularly hit 25-35s; 24s caused canned fallback even when LLM was actively succeeding.

async def direct_response_node_impl(
    state: AgentState,
    *,
    direct_response_step_name,
    get_or_create_tracer,
    capture_public_thinking_event,
    get_domain_greetings,
    normalize_for_intent,
    looks_identity_selfhood_turn,
    needs_web_search,
    needs_datetime,
    resolve_visual_intent,
    recommended_visual_thinking_effort,
    get_active_code_studio_session,
    merge_thinking_effort,
    get_effective_provider,
    get_explicit_user_provider,
    collect_direct_tools,
    direct_required_tool_names,
    resolve_direct_answer_timeout_profile,
    bind_direct_tools,
    build_direct_system_messages,
    build_visual_tool_runtime_metadata,
    execute_direct_tool_rounds,
    extract_direct_response,
    sanitize_structured_visual_answer_text,
    sanitize_wiii_house_text,
    build_direct_reasoning_summary,
    direct_tool_names,
    should_surface_direct_thinking,
    resolve_public_thinking_content,
    get_phase_fallback,
) -> AgentState:
    """Direct response node - conversational responses without RAG."""
    query = state.get("query", "")

    event_queue = None
    bus_id = state.get("_event_bus_id")
    if bus_id:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        event_queue = _get_event_queue(bus_id)

    async def push_event(event: dict):
        capture_public_thinking_event(state, event)
        if event_queue:
            try:
                event_queue.put_nowait(event)
            except Exception as queue_error:
                logger.debug("[DIRECT] Event queue push failed: %s", queue_error)

    tracer = get_or_create_tracer(state)
    tracer.start_step(direct_response_step_name, "Tao phan hoi truc tiep")

    use_natural = getattr(settings, "enable_natural_conversation", False) is True
    if not use_natural:
        greetings = get_domain_greetings(state.get("domain_id", settings.default_domain))
        query_lower = query.lower().strip()
        response = greetings.get(query_lower)
    else:
        query_lower = query.lower().strip()
        response = None
    response_type = "greeting" if response else ""
    explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)
    if not response and _is_codebase_analysis_query(query) and not explicit_web_search_turn:
        codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=codebase_thinking,
            provenance="codebase_source_backed_plan",
            record_thinking_snapshot_fn=record_thinking_snapshot,
        )
        if _should_use_codebase_source_note_fast_answer(query):
            response = _build_codebase_analysis_fallback_answer(query)
            response_type = "codebase_source_backed_fast"

    ctx_for_preflight = state.get("context", {}) if isinstance(state.get("context"), dict) else {}
    has_uploaded_document_context = _has_uploaded_document_context(ctx_for_preflight)

    def sanitize_document_preview_response(
        preview_response: str,
        preview_tool_call_events: list[dict[str, Any]],
    ) -> str:
        preview_response = sanitize_structured_visual_answer_text(
            preview_response,
            tool_call_events=preview_tool_call_events,
        )
        preview_response = sanitize_wiii_house_text(preview_response, query=query)
        preview_response = _strip_direct_inline_private_asides(preview_response)
        return _strip_dsml_residue(preview_response).strip()

    if (
        not response
        and has_uploaded_document_context
        and not str(state.get("thinking_content") or "").strip()
    ):
        document_thinking = (
            "Mình nhận đây là lượt hỏi có tài liệu upload đã được parse thành Markdown, "
            "nên ưu tiên đối chiếu marker, bảng và các dòng trong document_context trước khi suy luận thêm. "
            "Nếu phần nào không có trong file, Wiii phải nói rõ thay vì bịa."
        )
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=document_thinking,
            provenance="document_context_plan",
            record_thinking_snapshot_fn=record_thinking_snapshot,
        )
    if (
        not response
        and has_uploaded_document_context
        and _looks_uploaded_document_preview_request(query)
    ):
        routing_meta = state.get("routing_metadata")
        if not isinstance(routing_meta, dict):
            routing_meta = {}
            state["routing_metadata"] = routing_meta
        preview_tools, preview_force_tools, doc_preview_debug = (
            _rebind_document_preview_host_action_tool(
                tools=[],
                force_tools=False,
                query=query,
                state=state,
                ctx=ctx_for_preflight,
            )
        )
        routing_meta["doc_preview_preflight"] = doc_preview_debug
        preview_result = await execute_direct_node_document_preview_round(
            query=query,
            state=state,
            ctx=ctx_for_preflight,
            bus_id=bus_id,
            tools=preview_tools,
            force_tools=preview_force_tools,
            messages=[],
            push_event=push_event,
            build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
            execute_direct_tool_rounds=execute_direct_tool_rounds,
            extract_direct_response=extract_direct_response,
            sanitize_preview_response=sanitize_document_preview_response,
            fallback_response=(
                "Mình đã gửi bản preview bài học sang LMS. "
                "Giáo viên cần xem phần so sánh thay đổi và nguồn trích dẫn rồi bấm Áp dụng để cấp approval_token."
            ),
            debug=doc_preview_debug,
            routing_metadata_key="doc_preview_preflight",
            success_status="executed",
            failure_status="execution_failed",
            failure_log_message="[DIRECT] Early document preview host action failed: %s",
            logger_obj=logger,
        )
        if preview_result is not None:
            response = preview_result.response
            response_type = "document_preview_host_action"
            logger.info(
                "[DIRECT] Executed LMS document preview host action before planner LLM"
            )
    if ctx_for_preflight.get("image_input_error") and has_uploaded_document_context:
        ctx_for_preflight["images"] = []
    if (
        not response
        and ctx_for_preflight.get("image_input_error")
        and not has_uploaded_document_context
    ):
        response = _build_image_input_unavailable_answer(query)
        response_type = "image_input_unavailable"
        fast_thinking = _build_image_input_unavailable_thinking()
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input_unavailable",
            record_thinking_snapshot_fn=record_thinking_snapshot,
        )
    elif not response and ctx_for_preflight.get("images") and not has_uploaded_document_context:
        response = await _build_image_input_answer(
            query,
            list(ctx_for_preflight.get("images") or []),
        )
        response_type = "image_input"
        fast_thinking = _build_image_input_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input",
            record_thinking_snapshot_fn=record_thinking_snapshot,
        )

    if not response:
        fast_response = resolve_direct_node_fast_response(
            query=query,
            state=state,
            ctx=ctx_for_preflight,
            has_uploaded_document_context=has_uploaded_document_context,
            normalize_for_intent=normalize_for_intent,
            needs_web_search=needs_web_search,
            needs_datetime=needs_datetime,
            record_thinking_snapshot_fn=record_thinking_snapshot,
            logger_obj=logger,
        )
        if fast_response is not None:
            response = fast_response.response
            response_type = fast_response.response_type

    domain_config = state.get("domain_config", {})
    domain_name_vi = domain_config.get("name_vi", "")
    if not domain_name_vi:
        domain_id = state.get("domain_id", settings.default_domain)
        domain_name_vi = {
            "maritime": "Hang hai",
            "traffic_law": "Luat Giao thong",
        }.get(domain_id, domain_id)

    if response:
        tracer.end_step(
            result=f"Direct fast response: {response[:50]}...",
            confidence=1.0,
            details={"response_type": response_type or "greeting", "query": query_lower},
        )
    else:
        explicit_user_provider: str | None = None
        llm = None
        llm_response = None
        messages: list[Any] = []
        tools: list[Any] = []
        tool_call_events: list[dict[str, Any]] = []
        response_language = "vi"
        routing_intent = ""
        is_identity_turn = False
        is_emotional_support_turn = False
        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry

            ctx = state.get("context", {})
            response_language = str(ctx.get("response_language") or "vi").strip() or "vi"
            thinking_effort = state.get("thinking_effort")
            routing_meta = state.get("routing_metadata") or {}
            routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
            routing_method = str(routing_meta.get("method") or "").strip().lower()
            routing_intent = str(routing_meta.get("intent") or "").strip().lower()
            hint_kind = str(routing_hint.get("kind") or "").strip().lower()
            hint_shape = str(routing_hint.get("shape") or "").strip().lower()
            normalized_query = normalize_for_intent(query)
            short_token_count = len([token for token in normalized_query.split() if token])
            is_identity_turn = (
                hint_kind == "identity_probe"
                or hint_kind == "selfhood_followup"
                or routing_intent in {"identity", "selfhood"}
                or looks_identity_selfhood_turn(query)
            )
            is_emotional_support_turn = _looks_emotional_support_turn(query)
            is_chatter_fast_path = (
                routing_method == "always_on_chatter_fast_path"
                or (hint_kind == "fast_chatter" and hint_shape in {"reaction", "vague_banter"})
            )
            is_social_fast_path = (
                routing_method == "always_on_social_fast_path"
                or (hint_kind == "fast_chatter" and hint_shape == "social")
            )
            visual_decision = resolve_visual_intent(query)
            is_short_house_chatter = (
                not is_identity_turn
                and (
                    is_chatter_fast_path
                    or is_social_fast_path
                    or (
                        routing_intent == "social"
                        and short_token_count <= 6
                        and not needs_web_search(query)
                        and not needs_datetime(query)
                        and not visual_decision.force_tool
                    )
                )
            )
            history_limit = 0 if is_short_house_chatter else 10
            tools_context_override = "" if is_short_house_chatter else None
            role_name = (
                "direct_chatter_agent"
                if (is_short_house_chatter or is_identity_turn)
                else "direct_agent"
            )
            if is_short_house_chatter:
                history_limit = 0
                tools_context_override = ""
            if is_identity_turn:
                history_limit = max(history_limit, 6)
            thinking_effort = _resolve_direct_thinking_effort(
                query=query,
                state=state,
                current_effort=thinking_effort,
                is_identity_turn=is_identity_turn,
                is_short_house_chatter=is_short_house_chatter,
            )

            visual_effort = recommended_visual_thinking_effort(
                query,
                active_code_session=get_active_code_studio_session(state),
            )
            if visual_effort:
                previous_effort = thinking_effort
                thinking_effort = merge_thinking_effort(
                    thinking_effort,
                    visual_effort,
                )
                if thinking_effort != previous_effort:
                    logger.info(
                        "[DIRECT] Visual intent detected -> upgrade thinking effort %s -> %s",
                        previous_effort or "default",
                        thinking_effort,
                    )

            preferred_provider = get_effective_provider(state)
            explicit_user_provider = get_explicit_user_provider(state)
            use_house_voice_direct = (
                routing_intent in {"social", "personal", "off_topic"}
                and not needs_web_search(query)
                and not needs_datetime(query)
                and not visual_decision.force_tool
            )
            direct_provider_override = explicit_user_provider or preferred_provider
            is_codebase_source_turn = _is_codebase_analysis_query(query) and not (
                has_uploaded_document_context
                and _looks_uploaded_document_preview_request(query)
            )
            explicit_web_search_turn = _is_explicit_web_search_turn_for_direct(query, state)

            tool_selection = select_direct_node_tools(
                query=query,
                state=state,
                ctx=ctx,
                routing_intent=routing_intent,
                is_short_house_chatter=is_short_house_chatter,
                is_identity_turn=is_identity_turn,
                is_emotional_support_turn=is_emotional_support_turn,
                is_codebase_source_turn=is_codebase_source_turn,
                explicit_web_search_turn=explicit_web_search_turn,
                has_uploaded_document_context=has_uploaded_document_context,
                needs_web_search=needs_web_search,
                collect_direct_tools=collect_direct_tools,
                direct_required_tool_names=direct_required_tool_names,
                logger_obj=logger,
            )
            tools = tool_selection.tools
            force_tools = tool_selection.force_tools
            if (
                not response
                and has_uploaded_document_context
                and _looks_uploaded_document_preview_request(query)
            ):
                preview_result = await execute_direct_node_document_preview_round(
                    query=query,
                    state=state,
                    ctx=ctx,
                    bus_id=bus_id,
                    tools=tools,
                    force_tools=force_tools,
                    messages=messages,
                    push_event=push_event,
                    build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
                    execute_direct_tool_rounds=execute_direct_tool_rounds,
                    extract_direct_response=extract_direct_response,
                    sanitize_preview_response=sanitize_document_preview_response,
                    failure_log_message=(
                        "[DIRECT] Deterministic document preview pre-LLM path failed: %s"
                    ),
                    logger_obj=logger,
                )
                if preview_result is not None:
                    response = preview_result.response
                    thinking_content = preview_result.thinking_content
                    tools_used = preview_result.tools_used
                    messages = preview_result.messages
                    tool_call_events = preview_result.tool_call_events
                    tracer.end_step(
                        result="Deterministic uploaded-document preview host action",
                        confidence=0.9,
                        details={
                            "response_type": "document_preview_host_action",
                            "tools_bound": len(tools),
                            "force_tools": force_tools,
                        },
                    )

            from app.engine.multi_agent.openai_stream_runtime import (
                _supports_native_answer_streaming_impl,
            )

            llm_selection = select_direct_node_llm(
                is_identity_turn=is_identity_turn,
                ctx=ctx,
                is_short_house_chatter=is_short_house_chatter,
                is_emotional_support_turn=is_emotional_support_turn,
                use_house_voice_direct=use_house_voice_direct,
                is_codebase_source_turn=is_codebase_source_turn,
                response_present=bool(response),
                thinking_effort=thinking_effort,
                direct_provider_override=direct_provider_override,
                requested_model=state.get("model"),
                get_native_llm=AgentConfigRegistry.get_native_llm,
                get_llm=AgentConfigRegistry.get_llm,
                supports_native_answer_streaming=_supports_native_answer_streaming_impl,
            )
            llm = llm_selection.llm

            visual_guard = maybe_build_uploaded_visual_guard(
                llm=llm,
                query=query,
                state=state,
                ctx_for_preflight=ctx_for_preflight,
                has_uploaded_document_context=has_uploaded_document_context,
                direct_provider_override=direct_provider_override,
                preferred_provider=preferred_provider,
                looks_uploaded_file_visual_inspection_query=(
                    _looks_uploaded_file_visual_inspection_query
                ),
                provider_likely_supports_image_blocks=(
                    _provider_likely_supports_image_blocks
                ),
                build_uploaded_document_visual_guard_answer=(
                    _build_uploaded_document_visual_guard_answer
                ),
            )
            if visual_guard is not None:
                response = visual_guard.response
                logger.info(
                    "[DIRECT] Uploaded video frame question routed to text-only provider; "
                    "returned visual guard fallback (provider=%s model=%s)",
                    visual_guard.provider,
                    visual_guard.model,
                )
                tracer.end_step(
                    result="Uploaded-file visual guard fallback (text-only provider)",
                    confidence=0.7,
                    details={
                        "response_type": "uploaded_file_visual_guard_fallback",
                        "provider": visual_guard.provider,
                        "model": visual_guard.model,
                    },
                )

            llm = apply_direct_node_natural_conversation_penalties(
                llm,
                response_present=bool(response),
                enable_natural_conversation=(
                    getattr(settings, "enable_natural_conversation", False) is True
                ),
                presence_penalty=getattr(settings, "llm_presence_penalty", 0.0),
                frequency_penalty=getattr(settings, "llm_frequency_penalty", 0.0),
            )

            if llm and not response:
                logger.warning(
                    "[DIRECT] tools=%d, force=%s, web=%s, dt=%s, query='%s'",
                    len(tools),
                    force_tools,
                    needs_web_search(query),
                    needs_datetime(query),
                    query[:60],
                )

                execution_prep = prepare_direct_node_tool_execution(
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
                    logger_obj=logger,
                )

                force_tools = execution_prep.force_tools
                direct_answer_timeout_profile = execution_prep.direct_answer_timeout_profile
                direct_answer_primary_timeout = execution_prep.direct_answer_primary_timeout
                direct_allowed_fallback_providers = (
                    execution_prep.direct_allowed_fallback_providers
                )
                llm_with_tools = execution_prep.llm_with_tools
                llm_auto = execution_prep.llm_auto
                forced_tool_choice = execution_prep.forced_tool_choice
                # v9.0 F18 (2026-05-07) — when pointy is force-bound, the
                # tool's selector is already enum-constrained at JSON-schema
                # layer (Literal[...] in tool_pointy_show args). That's
                # SeeAct's textual-choice grounding applied at argument
                # layer. We DON'T need to override tool_choice to specific
                # tool name (caused NVIDIA bind_tools incompat in early
                # tests) — the existing `_resolve_tool_choice("any")` is
                # sufficient because force_tools=True ensures SOME tool
                # is invoked, and the enum-constrained pointy tool wins
                # when query is UI-related (other tools have unrelated
                # signatures).
                native_direct_messages = execution_prep.native_direct_messages
                messages = execution_prep.messages
                runtime_context_base = execution_prep.runtime_context_base

                # Wiii Pointy v2.6 — adaptive max rounds. Loop tự exit
                # khi LLM ngừng gọi tool; cap chỉ là runaway protection.
                # Default 12 (Anthropic Computer Use ref dùng 10), settings
                # override cho power-users / autonomous flows.
                _direct_max_rounds = getattr(settings, "direct_agent_max_tool_rounds", 12)

                direct_execution = execute_direct_tool_rounds(
                    llm_with_tools,
                    llm_auto,
                    messages,
                    tools,
                    push_event,
                    runtime_context_base=runtime_context_base,
                    max_rounds=_direct_max_rounds,
                    query=query,
                    state=state,
                    provider=explicit_user_provider,
                    forced_tool_choice=forced_tool_choice,
                    llm_base=llm,
                    direct_answer_timeout_profile=direct_answer_timeout_profile,
                    direct_answer_primary_timeout=direct_answer_primary_timeout,
                    allowed_fallback_providers=direct_allowed_fallback_providers,
                    native_tool_messages=native_direct_messages,
                )
                llm_response, messages, tool_call_events = await run_direct_node_execution_with_host_timeout(
                    direct_execution=direct_execution,
                    routing_intent=routing_intent,
                    state=state,
                    messages=messages,
                    push_event=push_event,
                    timeout_seconds=_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS,
                    logger_obj=logger,
                )

                if tool_call_events:
                    state["tool_call_events"] = tool_call_events

                response, thinking_content, tools_used = extract_direct_response(llm_response, messages)
                cleaned_response = clean_direct_node_llm_response(
                    query=query,
                    state=state,
                    response=response,
                    thinking_content=thinking_content,
                    tools_used=tools_used,
                    tool_call_events=tool_call_events,
                    is_identity_turn=is_identity_turn,
                    is_codebase_analysis_turn=_is_codebase_analysis_query(query),
                    explicit_web_search_turn=explicit_web_search_turn,
                    sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
                    sanitize_wiii_house_text=sanitize_wiii_house_text,
                    strip_direct_inline_private_asides=_strip_direct_inline_private_asides,
                    strip_dsml_residue=_strip_dsml_residue,
                    compact_basic_identity_answer=_compact_basic_identity_answer,
                    looks_generic_direct_fallback_response=(
                        _looks_generic_direct_fallback_response
                    ),
                    build_codebase_analysis_fallback_answer=(
                        _build_codebase_analysis_fallback_answer
                    ),
                    build_codebase_analysis_fallback_thinking=(
                        _build_codebase_analysis_fallback_thinking
                    ),
                    record_direct_node_thinking_snapshot=record_direct_node_thinking_snapshot,
                    record_thinking_snapshot_fn=record_thinking_snapshot,
                )
                response = cleaned_response.response
                thinking_content = cleaned_response.thinking_content
                tools_used = cleaned_response.tools_used
                # Source-backed graceful synthesis: when the LLM returned an
                # empty body but tools captured real search results (Perplexity
                # 2026 / Anthropic Computer Use 2026 evidence-pool pattern),
                # build a citation-bearing answer directly from tool_call_events
                # instead of letting the user see nothing.
                source_fallback = apply_source_backed_empty_response_fallback(
                    query=query,
                    response=response,
                    tools_used=tools_used,
                    tool_call_events=tool_call_events,
                    looks_like_search_placeholder_answer=looks_like_search_placeholder_answer,
                    build_search_template_fallback=build_search_template_fallback,
                    inc_counter=inc_counter,
                    logger_obj=logger,
                )
                response = source_fallback.response
                tools_used = source_fallback.tools_used

                await finalize_direct_node_visible_thinking(
                    query=query,
                    state=state,
                    response=response,
                    thinking_content=thinking_content,
                    routing_intent=routing_intent,
                    response_language=response_language,
                    llm=llm,
                    tools_used=list(tools_used or []),
                    build_direct_reasoning_summary=build_direct_reasoning_summary,
                    record_direct_node_thinking_snapshot=record_direct_node_thinking_snapshot,
                    record_thinking_snapshot_fn=record_thinking_snapshot,
                )
                if tools_used:
                    state["tools_used"] = tools_used

                tracer.end_step(
                    result=f"Phan hoi LLM: {len(response)} chars",
                    confidence=0.85,
                    details={
                        "response_type": "llm_generated",
                        "tools_bound": len(tools),
                        "force_tools": force_tools,
                    },
                )
            elif not response:
                if explicit_user_provider:
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code="busy",
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                    )
                if _is_codebase_analysis_query(query) and not explicit_web_search_turn:
                    response = _build_codebase_analysis_fallback_answer(query)
                    codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                    record_direct_node_thinking_snapshot(
                        state=state,
                        thinking=codebase_thinking,
                        provenance="deterministic_codebase_fallback",
                        record_thinking_snapshot_fn=record_thinking_snapshot,
                    )
                else:
                    response = (
                        get_phase_fallback(state)
                        if getattr(settings, "enable_natural_conversation", False) is True
                        else "Xin chao! Toi co the giup gi cho ban?"
                    )
                tracer.end_step(
                    result="Fallback (LLM unavailable)",
                    confidence=0.5,
                    details={
                        "response_type": (
                            "codebase_source_backed_fallback"
                            if _is_codebase_analysis_query(query) and not explicit_web_search_turn
                            else "fallback"
                        )
                    },
                )
        except Exception as exc:
            salvaged = await _salvage_direct_turn_from_final_result(
                llm_response=llm_response,
                messages=messages,
                extract_direct_response=extract_direct_response,
                sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
                sanitize_wiii_house_text=sanitize_wiii_house_text,
                tool_call_events=tool_call_events,
                query=query,
                is_identity_turn=is_identity_turn,
                routing_intent=routing_intent,
                response_language=response_language,
                llm=llm,
            )
            if salvaged:
                response, salvaged_thinking, salvaged_tools = salvaged
                if salvaged_tools:
                    state["tools_used"] = salvaged_tools
                if salvaged_thinking:
                    record_direct_node_thinking_snapshot(
                        state=state,
                        thinking=salvaged_thinking,
                        provenance="final_snapshot",
                        record_thinking_snapshot_fn=record_thinking_snapshot,
                    )
                logger.warning(
                    "[DIRECT] Post-processing failed but salvaged final result: %s",
                    exc,
                )
                tracer.end_step(
                    result="Salvaged direct response after post-processing error",
                    confidence=0.7,
                    details={
                        "response_type": "llm_salvaged",
                        "error_type": type(exc).__name__,
                    },
                )
            elif (
                isinstance(exc, ProviderUnavailableError)
                and (
                    uploaded_fallback := _build_uploaded_document_context_fallback_answer(
                        query,
                        ctx_for_preflight,
                    )
                )
            ):
                response = uploaded_fallback
                logger.info(
                    "[DIRECT] Provider unavailable; returned uploaded-file context fallback (len=%d)",
                    len(response),
                )
                tracer.end_step(
                    result="Uploaded-file context fallback (provider unavailable)",
                    confidence=0.65,
                    details={
                        "response_type": "uploaded_file_context_fallback",
                        "error_type": type(exc).__name__,
                    },
                )
            elif isinstance(exc, ProviderUnavailableError) and tool_call_events:
                template_response = ""
                try:
                    template_response = build_search_template_fallback(
                        query=query,
                        tool_call_events=tool_call_events,
                    )
                except Exception as template_error:
                    logger.warning(
                        "[DIRECT] Provider unavailable and search fallback build failed: %s",
                        template_error,
                    )
                if not template_response:
                    raise
                response = template_response
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in tool_call_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Provider unavailable after tools; returning "
                    "source-backed fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (provider unavailable after tools)",
                    confidence=0.6,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif isinstance(exc, ProviderUnavailableError) and needs_web_search(query):
                fallback_events: list[dict[str, Any]] = []
                try:
                    fallback_events = await _emergency_search_fallback(
                        query=query,
                        tools=tools,
                        timeout_seconds=30.0,
                    )
                except Exception as emergency_error:
                    logger.warning(
                        "[DIRECT] Provider unavailable and emergency search failed: %s",
                        emergency_error,
                    )
                    fallback_events = []

                template_response = ""
                if fallback_events:
                    try:
                        await _emit_synthetic_tool_events(
                            fallback_events,
                            push_event=push_event,
                        )
                        state["tool_call_events"] = fallback_events
                        template_response = build_search_template_fallback(
                            query=query,
                            tool_call_events=fallback_events,
                        )
                    except Exception as template_error:
                        logger.warning(
                            "[DIRECT] Emergency search template fallback failed: %s",
                            template_error,
                        )
                        template_response = ""
                if not template_response:
                    raise
                response = template_response
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in fallback_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Provider unavailable before tool planning; "
                    "returned emergency source-backed fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (provider unavailable before tools)",
                    confidence=0.55,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif explicit_user_provider and needs_web_search(query):
                fallback_events = list(tool_call_events or [])
                if not fallback_events:
                    logger.info(
                        "[DIRECT] Explicit provider web turn failed before tool "
                        "evidence — engaging LLM-free emergency search"
                    )
                    try:
                        fallback_events = await _emergency_search_fallback(
                            query=query,
                            tools=tools,
                            timeout_seconds=30.0,
                        )
                    except Exception as emergency_error:
                        logger.warning(
                            "[DIRECT] Explicit-provider emergency search failed: %s",
                            emergency_error,
                        )
                        fallback_events = []

                template_response = ""
                if fallback_events:
                    try:
                        if not tool_call_events:
                            await _emit_synthetic_tool_events(
                                fallback_events,
                                push_event=push_event,
                            )
                            state["tool_call_events"] = fallback_events
                        template_response = build_search_template_fallback(
                            query=query,
                            tool_call_events=fallback_events,
                        )
                    except Exception as template_error:
                        logger.warning(
                            "[DIRECT] Explicit-provider template fallback failed: %s",
                            template_error,
                        )
                        template_response = ""
                if not template_response:
                    classified = classify_failover_reason_impl(error=exc)
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code=str(classified.get("reason_code") or "provider_unavailable"),
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                        details=classified.get("detail"),
                    ) from exc

                response = template_response
                if fallback_events and not tool_call_events:
                    tool_call_events = fallback_events
                template_tool_names = sorted({
                    str(event.get("name") or "")
                    for event in fallback_events
                    if event.get("type") == "result" and event.get("name")
                })
                template_tools = [
                    {"name": name} for name in template_tool_names if name
                ]
                if template_tools:
                    state["tools_used"] = template_tools
                logger.info(
                    "[DIRECT] Explicit provider failed on web turn; returned "
                    "source-backed emergency fallback (tools=%d, len=%d)",
                    len(template_tools),
                    len(response),
                )
                tracer.end_step(
                    result="Source-backed fallback (explicit provider web failure)",
                    confidence=0.55,
                    details={
                        "response_type": "search_template_fallback",
                        "tools_used_count": len(template_tools),
                        "response_length": len(response),
                    },
                )
            elif explicit_user_provider:
                uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                    query,
                    ctx_for_preflight,
                )
                if uploaded_fallback:
                    response = uploaded_fallback
                    logger.info(
                        "[DIRECT] Explicit provider failed; returned uploaded-file context fallback (len=%d)",
                        len(response),
                    )
                    tracer.end_step(
                        result="Uploaded-file context fallback (explicit provider failed)",
                        confidence=0.65,
                        details={
                            "response_type": "uploaded_file_context_fallback",
                            "error_type": type(exc).__name__,
                        },
                    )
                else:
                    if isinstance(exc, ProviderUnavailableError):
                        raise
                    classified = classify_failover_reason_impl(error=exc)
                    raise ProviderUnavailableError(
                        provider=str(explicit_user_provider).strip().lower(),
                        reason_code=str(classified.get("reason_code") or "provider_unavailable"),
                        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
                        details=classified.get("detail"),
                    ) from exc
            else:
                logger.warning("[DIRECT] LLM generation failed: %s", exc)
                logger.info(
                    "[DIRECT] Template fallback consideration — "
                    "tool_call_events count=%d, types=%s",
                    len(tool_call_events) if tool_call_events else 0,
                    [
                        f"{event.get('type')}:{event.get('name')}"
                        for event in (tool_call_events or [])[:6]
                    ],
                )
                fallback_events = list(tool_call_events or [])
                if not fallback_events and needs_web_search(query):
                    logger.info(
                        "[DIRECT] Round-0 timeout with empty tool history — "
                        "engaging LLM-free emergency search"
                    )
                    try:
                        fallback_events = await _emergency_search_fallback(
                            query=query,
                            tools=tools,
                            timeout_seconds=30.0,
                        )
                        logger.info(
                            "[DIRECT] Emergency search produced %d synthetic events",
                            len(fallback_events),
                        )
                    except Exception as emergency_error:
                        logger.warning(
                            "[DIRECT] Emergency search failed: %s",
                            emergency_error,
                        )
                        fallback_events = []
                template_response = ""
                try:
                    template_response = build_search_template_fallback(
                        query=query,
                        tool_call_events=fallback_events,
                    )
                    logger.info(
                        "[DIRECT] Template fallback build returned len=%d",
                        len(template_response or ""),
                    )
                except Exception as template_error:
                    logger.warning(
                        "[DIRECT] Template fallback build failed: %s",
                        template_error,
                    )
                if template_response:
                    if fallback_events and not tool_call_events:
                        tool_call_events = fallback_events
                        state["tool_call_events"] = fallback_events
                    try:
                        trigger_label = (
                            "emergency_search"
                            if not tool_call_events or fallback_events == tool_call_events
                            else "exception_with_tools"
                        )
                        inc_counter(
                            "wiii.direct.template_fallback.engaged",
                            labels={"trigger": trigger_label},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    response = template_response
                    template_tool_names = sorted({
                        str(event.get("name") or "")
                        for event in tool_call_events
                        if event.get("type") == "result" and event.get("name")
                    })
                    template_tools = [
                        {"name": name} for name in template_tool_names if name
                    ]
                    if template_tools:
                        state["tools_used"] = template_tools
                    logger.info(
                        "[DIRECT] Source-backed template fallback engaged "
                        "(synthesis LLM unavailable, tools=%d, len=%d)",
                        len(template_tools),
                        len(response),
                    )
                    tracer.end_step(
                        result="Source-backed fallback (synthesis LLM unavailable)",
                        confidence=0.6,
                        details={
                            "response_type": "search_template_fallback",
                            "tools_used_count": len(template_tools),
                            "response_length": len(response),
                        },
                    )
                else:
                    codebase_fallback = (
                        _build_codebase_analysis_fallback_answer(query)
                        if _is_codebase_analysis_query(query) and not explicit_web_search_turn
                        else ""
                    )
                    if isinstance(exc, ProviderUnavailableError):
                        uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                            query,
                            ctx_for_preflight,
                        )
                        if uploaded_fallback:
                            response = uploaded_fallback
                        elif codebase_fallback:
                            response = codebase_fallback
                            codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                            record_direct_node_thinking_snapshot(
                                state=state,
                                thinking=codebase_thinking,
                                provenance="deterministic_codebase_fallback",
                                record_thinking_snapshot_fn=record_thinking_snapshot,
                            )
                        else:
                            raise
                    else:
                        uploaded_fallback = _build_uploaded_document_context_fallback_answer(
                            query,
                            ctx_for_preflight,
                        )
                        if uploaded_fallback:
                            response = uploaded_fallback
                        elif codebase_fallback:
                            response = codebase_fallback
                            codebase_thinking = _build_codebase_analysis_fallback_thinking(query)
                            record_direct_node_thinking_snapshot(
                                state=state,
                                thinking=codebase_thinking,
                                provenance="deterministic_codebase_fallback",
                                record_thinking_snapshot_fn=record_thinking_snapshot,
                            )
                        else:
                            response = (
                                get_phase_fallback(state)
                                if getattr(settings, "enable_natural_conversation", False) is True
                                else "Xin chao! Toi co the giup gi cho ban?"
                            )
                    tracer.end_step(
                        result="Fallback (LLM generation error)",
                        confidence=0.5,
                        details={
                            "response_type": (
                                "uploaded_file_context_fallback"
                                if uploaded_fallback
                                else "codebase_source_backed_fallback"
                                if codebase_fallback
                                else "fallback"
                            )
                        },
                    )

    resolved_direct_thinking = resolve_public_thinking_content(
        state,
        fallback="",
    )
    if resolved_direct_thinking:
        state["thinking_content"] = resolved_direct_thinking
        record_thinking_snapshot(
            state,
            resolved_direct_thinking,
            node="direct",
            provenance=(
                "final_snapshot"
                if resolved_direct_thinking == str(state.get("thinking") or "").strip()
                else "aligned_cleanup"
            ),
        )

    state["final_response"] = response
    state["agent_outputs"] = {"direct": response}
    state["current_agent"] = "direct"

    routing_meta = state.get("routing_metadata", {})
    intent = routing_meta.get("intent", "") if routing_meta else ""
    if intent == "general":
        from app.core.config import settings as local_settings
        from app.core.org_context import get_current_org_id

        suppress = local_settings.enable_org_knowledge and bool(get_current_org_id())
        if not suppress:
            state["domain_notice"] = (
                f"Noi dung nay nam ngoai chuyen mon {domain_name_vi}. "
                f"De duoc ho tro chinh xac hon, hay hoi ve {domain_name_vi} nhe!"
            )

    logger.info("[DIRECT] Response prepared, tracer passed to synthesizer")
    return state
