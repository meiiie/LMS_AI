"""Direct node runtime extracted from the graph shell."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.engine.multi_agent.direct_node_document_preview_runtime import (
    execute_direct_node_document_preview_round,
)
from app.engine.multi_agent.direct_node_event_sink import (
    build_direct_node_event_sink,
)
from app.engine.multi_agent.direct_node_llm_preflight import (
    prepare_direct_node_llm_preflight,
)
from app.engine.multi_agent.direct_node_llm_tool_loop import (
    execute_direct_node_llm_tool_loop,
)
from app.engine.multi_agent.direct_node_llm_fallback import (
    resolve_direct_node_llm_unavailable_fallback,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.direct_node_exception_fallbacks import (
    handle_direct_node_generation_exception,
)
from app.engine.multi_agent.direct_node_final_state import finalize_direct_node_state
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_codebase_analysis_fallback_answer,
    _build_codebase_analysis_fallback_thinking,
)
from app.engine.multi_agent.direct_node_pre_llm_pipeline import (
    DirectNodePreLlmPipelineDependencies,
    DirectNodePreLlmPipelineRequest,
    execute_direct_node_pre_llm_pipeline,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_tool_selection import select_direct_node_tools
from app.engine.multi_agent.direct_node_turn_policy import resolve_direct_node_turn_policy
from app.engine.multi_agent.direct_node_uploaded_context import (
    _build_uploaded_document_context_fallback_answer,
    _build_uploaded_document_visual_guard_answer,
    _looks_uploaded_document_preview_request,
    _looks_uploaded_file_visual_inspection_query,
    _provider_likely_supports_image_blocks,
)
from app.engine.runtime.runtime_metrics import inc_counter
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    record_thinking_snapshot,
)

logger = logging.getLogger(__name__)

_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS = 45.0  # Phase F3 (2026-05-06): bumped 24->45s. Tool-heavy pointy turns regularly hit 25-35s; 24s caused canned fallback even when LLM was actively succeeding.

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

    pre_llm_pipeline = await execute_direct_node_pre_llm_pipeline(
        request=DirectNodePreLlmPipelineRequest(
            query=query,
            state=state,
            bus_id=bus_id,
            push_event=push_event,
            tracer=tracer,
            enable_natural_conversation=(
                getattr(settings, "enable_natural_conversation", False) is True
            ),
            default_domain=settings.default_domain,
        ),
        dependencies=DirectNodePreLlmPipelineDependencies(
            get_domain_greetings=get_domain_greetings,
            normalize_for_intent=normalize_for_intent,
            needs_web_search=needs_web_search,
            needs_datetime=needs_datetime,
            build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
            execute_direct_tool_rounds=execute_direct_tool_rounds,
            extract_direct_response=extract_direct_response,
            sanitize_structured_visual_answer_text=sanitize_structured_visual_answer_text,
            sanitize_wiii_house_text=sanitize_wiii_house_text,
            record_thinking_snapshot_fn=record_thinking_snapshot,
            logger_obj=logger,
        ),
    )
    response = pre_llm_pipeline.response
    explicit_web_search_turn = pre_llm_pipeline.explicit_web_search_turn
    ctx_for_preflight = pre_llm_pipeline.ctx_for_preflight
    has_uploaded_document_context = pre_llm_pipeline.has_uploaded_document_context
    domain_name_vi = pre_llm_pipeline.domain_name_vi
    sanitize_document_preview_response = (
        pre_llm_pipeline.sanitize_document_preview_response
    )

    if not response:
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

            turn_policy = resolve_direct_node_turn_policy(
                query=query,
                state=state,
                has_uploaded_document_context=has_uploaded_document_context,
                normalize_for_intent=normalize_for_intent,
                looks_identity_selfhood_turn=looks_identity_selfhood_turn,
                needs_web_search=needs_web_search,
                needs_datetime=needs_datetime,
                resolve_visual_intent=resolve_visual_intent,
                recommended_visual_thinking_effort=recommended_visual_thinking_effort,
                get_active_code_studio_session=get_active_code_studio_session,
                merge_thinking_effort=merge_thinking_effort,
                get_effective_provider=get_effective_provider,
                get_explicit_user_provider=get_explicit_user_provider,
                looks_uploaded_document_preview_request=(
                    _looks_uploaded_document_preview_request
                ),
                logger_obj=logger,
            )
            ctx = turn_policy.ctx
            response_language = turn_policy.response_language
            thinking_effort = turn_policy.thinking_effort
            routing_intent = turn_policy.routing_intent
            is_identity_turn = turn_policy.is_identity_turn
            is_emotional_support_turn = turn_policy.is_emotional_support_turn
            is_short_house_chatter = turn_policy.is_short_house_chatter
            visual_decision = turn_policy.visual_decision
            history_limit = turn_policy.history_limit
            tools_context_override = turn_policy.tools_context_override
            role_name = turn_policy.role_name
            preferred_provider = turn_policy.preferred_provider
            explicit_user_provider = turn_policy.explicit_user_provider
            use_house_voice_direct = turn_policy.use_house_voice_direct
            direct_provider_override = turn_policy.direct_provider_override
            is_codebase_source_turn = turn_policy.is_codebase_source_turn
            explicit_web_search_turn = turn_policy.explicit_web_search_turn

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

            llm_preflight = prepare_direct_node_llm_preflight(
                query=query,
                state=state,
                ctx=ctx,
                ctx_for_preflight=ctx_for_preflight,
                has_uploaded_document_context=has_uploaded_document_context,
                response=response,
                is_identity_turn=is_identity_turn,
                is_short_house_chatter=is_short_house_chatter,
                is_emotional_support_turn=is_emotional_support_turn,
                use_house_voice_direct=use_house_voice_direct,
                is_codebase_source_turn=is_codebase_source_turn,
                thinking_effort=thinking_effort,
                direct_provider_override=direct_provider_override,
                preferred_provider=preferred_provider,
                requested_model=state.get("model"),
                enable_natural_conversation=(
                    getattr(settings, "enable_natural_conversation", False) is True
                ),
                presence_penalty=getattr(settings, "llm_presence_penalty", 0.0),
                frequency_penalty=getattr(settings, "llm_frequency_penalty", 0.0),
                get_native_llm=AgentConfigRegistry.get_native_llm,
                get_llm=AgentConfigRegistry.get_llm,
                supports_native_answer_streaming=_supports_native_answer_streaming_impl,
                looks_uploaded_file_visual_inspection_query=(
                    _looks_uploaded_file_visual_inspection_query
                ),
                provider_likely_supports_image_blocks=(
                    _provider_likely_supports_image_blocks
                ),
                build_uploaded_document_visual_guard_answer=(
                    _build_uploaded_document_visual_guard_answer
                ),
                tracer=tracer,
                logger_obj=logger,
            )
            llm = llm_preflight.llm
            response = llm_preflight.response

            if llm and not response:
                llm_tool_loop = await execute_direct_node_llm_tool_loop(
                    llm=llm,
                    query=query,
                    state=state,
                    ctx=ctx,
                    bus_id=bus_id,
                    domain_name_vi=domain_name_vi,
                    role_name=role_name,
                    tools=tools,
                    force_tools=force_tools,
                    tools_context_override=tools_context_override,
                    visual_decision=visual_decision,
                    history_limit=history_limit,
                    routing_intent=routing_intent,
                    response_language=response_language,
                    is_identity_turn=is_identity_turn,
                    is_short_house_chatter=is_short_house_chatter,
                    use_house_voice_direct=use_house_voice_direct,
                    direct_provider_override=direct_provider_override,
                    preferred_provider=preferred_provider,
                    explicit_user_provider=explicit_user_provider,
                    explicit_web_search_turn=explicit_web_search_turn,
                    push_event=push_event,
                    needs_web_search=needs_web_search,
                    needs_datetime=needs_datetime,
                    resolve_direct_answer_timeout_profile=resolve_direct_answer_timeout_profile,
                    bind_direct_tools=bind_direct_tools,
                    build_direct_system_messages=build_direct_system_messages,
                    build_visual_tool_runtime_metadata=build_visual_tool_runtime_metadata,
                    execute_direct_tool_rounds=execute_direct_tool_rounds,
                    extract_direct_response=extract_direct_response,
                    sanitize_structured_visual_answer_text=(
                        sanitize_structured_visual_answer_text
                    ),
                    sanitize_wiii_house_text=sanitize_wiii_house_text,
                    build_direct_reasoning_summary=build_direct_reasoning_summary,
                    tracer=tracer,
                    logger_obj=logger,
                    direct_max_rounds=getattr(
                        settings, "direct_agent_max_tool_rounds", 12
                    ),
                    host_ui_total_timeout_seconds=(
                        _HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS
                    ),
                )

                response = llm_tool_loop.response
                messages = llm_tool_loop.messages
                tool_call_events = llm_tool_loop.tool_call_events
                force_tools = llm_tool_loop.force_tools
            elif not response:
                llm_fallback = resolve_direct_node_llm_unavailable_fallback(
                    query=query,
                    state=state,
                    explicit_user_provider=explicit_user_provider,
                    explicit_web_search_turn=explicit_web_search_turn,
                    enable_natural_conversation=(
                        getattr(settings, "enable_natural_conversation", False) is True
                    ),
                    get_phase_fallback=get_phase_fallback,
                    build_codebase_analysis_fallback_answer=(
                        _build_codebase_analysis_fallback_answer
                    ),
                    build_codebase_analysis_fallback_thinking=(
                        _build_codebase_analysis_fallback_thinking
                    ),
                    record_direct_node_thinking_snapshot=(
                        record_direct_node_thinking_snapshot
                    ),
                    record_thinking_snapshot_fn=record_thinking_snapshot,
                )
                response = llm_fallback.response
                tracer.end_step(
                    result="Fallback (LLM unavailable)",
                    confidence=0.5,
                    details={"response_type": llm_fallback.response_type},
                )
        except Exception as exc:
            llm_response = getattr(exc, "_direct_node_llm_response", llm_response)
            messages = getattr(exc, "_direct_node_messages", messages)
            tool_call_events = getattr(
                exc,
                "_direct_node_tool_call_events",
                tool_call_events,
            )
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
