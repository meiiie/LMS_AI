"""Direct node runtime extracted from the graph shell."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.document_preview_contract import (
    has_uploaded_document_context as _has_uploaded_document_context,
)
from app.engine.multi_agent.direct_node_document_preview_runtime import (
    execute_direct_node_document_preview_round,
)
from app.engine.multi_agent.direct_node_document_preflight import (
    build_document_preview_response_sanitizer,
    execute_direct_node_document_preview_preflight,
    record_uploaded_document_context_plan,
)
from app.engine.multi_agent.direct_node_fast_response_runtime import (
    resolve_direct_node_fast_response,
)
from app.engine.multi_agent.direct_node_event_sink import (
    build_direct_node_event_sink,
)
from app.engine.multi_agent.direct_node_host_timeout import (
    run_direct_node_execution_with_host_timeout,
)
from app.engine.multi_agent.direct_node_image_input_preflight import (
    execute_direct_node_image_input_preflight,
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
from app.engine.multi_agent.direct_intent import (
    _looks_emotional_support_turn,
)
from app.engine.multi_agent.direct_reasoning import (
    _is_codebase_analysis_query,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
    looks_like_search_placeholder_answer,
)
from app.engine.multi_agent.direct_node_exception_fallbacks import (
    handle_direct_node_generation_exception,
)
from app.engine.multi_agent.direct_node_final_state import finalize_direct_node_state
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
    _is_explicit_web_search_turn_for_direct,
    _looks_generic_direct_fallback_response,
    _strip_dsml_residue,
)
from app.engine.multi_agent.direct_node_thinking_effort import (
    _resolve_direct_thinking_effort,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_tool_selection import select_direct_node_tools
from app.engine.multi_agent.direct_node_turn_start import start_direct_node_turn
from app.engine.multi_agent.direct_node_uploaded_context import (
    _build_uploaded_document_context_fallback_answer,
    _build_uploaded_document_visual_guard_answer,
    _looks_uploaded_document_preview_request,
    _looks_uploaded_file_visual_inspection_query,
    _provider_likely_supports_image_blocks,
)
from app.engine.multi_agent.direct_node_visible_thought import (
    _compact_basic_identity_answer,
    _strip_direct_inline_private_asides,
)
from app.engine.runtime.runtime_metrics import inc_counter
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    record_thinking_snapshot,
)

logger = logging.getLogger(__name__)

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

    bus_id = state.get("_event_bus_id")
    event_sink = build_direct_node_event_sink(
        state=state,
        bus_id=bus_id,
        capture_public_thinking_event=capture_public_thinking_event,
        logger_obj=logger,
    )
    push_event = event_sink.push_event

    tracer = get_or_create_tracer(state)
    tracer.start_step(direct_response_step_name, "Tao phan hoi truc tiep")

    turn_start = start_direct_node_turn(
        query=query,
        state=state,
        enable_natural_conversation=(
            getattr(settings, "enable_natural_conversation", False) is True
        ),
        default_domain=settings.default_domain,
        get_domain_greetings=get_domain_greetings,
        record_thinking_snapshot_fn=record_thinking_snapshot,
    )
    query_lower = turn_start.query_lower
    response = turn_start.response
    response_type = turn_start.response_type
    explicit_web_search_turn = turn_start.explicit_web_search_turn

    ctx_for_preflight = state.get("context", {}) if isinstance(state.get("context"), dict) else {}
    has_uploaded_document_context = _has_uploaded_document_context(ctx_for_preflight)

    sanitize_document_preview_response = build_document_preview_response_sanitizer(
        query=query,
        sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
        sanitize_wiii_house_text=sanitize_wiii_house_text,
        strip_direct_inline_private_asides=_strip_direct_inline_private_asides,
        strip_dsml_residue=_strip_dsml_residue,
    )

    document_thinking = (
        "Mình nhận đây là lượt hỏi có tài liệu upload đã được parse thành Markdown, "
        "nên ưu tiên đối chiếu marker, bảng và các dòng trong document_context trước khi suy luận thêm. "
        "Nếu phần nào không có trong file, Wiii phải nói rõ thay vì bịa."
    )
    record_uploaded_document_context_plan(
        state=state,
        response_present=bool(response),
        has_uploaded_document_context=has_uploaded_document_context,
        document_thinking=document_thinking,
        record_thinking_snapshot_fn=record_thinking_snapshot,
    )
    document_preflight_result = await execute_direct_node_document_preview_preflight(
        query=query,
        state=state,
        ctx=ctx_for_preflight,
        bus_id=bus_id,
        response_present=bool(response),
        has_uploaded_document_context=has_uploaded_document_context,
        looks_uploaded_document_preview_request=_looks_uploaded_document_preview_request,
        push_event=push_event,
        build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
        execute_direct_tool_rounds=execute_direct_tool_rounds,
        extract_direct_response=extract_direct_response,
        sanitize_preview_response=sanitize_document_preview_response,
        fallback_response=(
            "Mình đã gửi bản preview bài học sang LMS. "
            "Giáo viên cần xem phần so sánh thay đổi và nguồn trích dẫn rồi bấm Áp dụng để cấp approval_token."
        ),
        logger_obj=logger,
    )
    if document_preflight_result is not None:
        response = document_preflight_result.response
        response_type = document_preflight_result.response_type

    image_preflight_result = await execute_direct_node_image_input_preflight(
        query=query,
        state=state,
        ctx=ctx_for_preflight,
        response_present=bool(response),
        has_uploaded_document_context=has_uploaded_document_context,
        record_thinking_snapshot_fn=record_thinking_snapshot,
    )
    if image_preflight_result is not None:
        response = image_preflight_result.response
        response_type = image_preflight_result.response_type

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
            fallback_result = await handle_direct_node_generation_exception(
                exc=exc,
                query=query,
                state=state,
                ctx_for_preflight=ctx_for_preflight,
                tools=tools,
                tool_call_events=tool_call_events,
                llm_response=llm_response,
                messages=messages,
                llm=llm,
                routing_intent=routing_intent,
                response_language=response_language,
                is_identity_turn=is_identity_turn,
                explicit_user_provider=explicit_user_provider,
                explicit_web_search_turn=explicit_web_search_turn,
                needs_web_search=needs_web_search,
                extract_direct_response=extract_direct_response,
                sanitize_structured_visual_answer_text=(
                    sanitize_structured_visual_answer_text
                ),
                sanitize_wiii_house_text=sanitize_wiii_house_text,
                build_search_template_fallback=build_search_template_fallback,
                build_uploaded_document_context_fallback_answer=(
                    _build_uploaded_document_context_fallback_answer
                ),
                build_codebase_analysis_fallback_answer=(
                    _build_codebase_analysis_fallback_answer
                ),
                build_codebase_analysis_fallback_thinking=(
                    _build_codebase_analysis_fallback_thinking
                ),
                get_phase_fallback=get_phase_fallback,
                record_direct_node_thinking_snapshot=(
                    record_direct_node_thinking_snapshot
                ),
                record_thinking_snapshot_fn=record_thinking_snapshot,
                tracer=tracer,
                push_event=push_event,
                inc_counter=inc_counter,
                logger_obj=logger,
            )
            response = fallback_result.response
            tool_call_events = fallback_result.tool_call_events

    from app.core.org_context import get_current_org_id

    finalize_direct_node_state(
        state=state,
        response=response,
        domain_name_vi=domain_name_vi,
        resolve_public_thinking_content=resolve_public_thinking_content,
        record_thinking_snapshot_fn=record_thinking_snapshot,
        enable_org_knowledge=settings.enable_org_knowledge,
        get_current_org_id_fn=get_current_org_id,
    )

    logger.info("[DIRECT] Response prepared, tracer passed to synthesizer")
    return state
