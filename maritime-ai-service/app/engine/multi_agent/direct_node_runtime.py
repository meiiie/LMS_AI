"""Direct node runtime extracted from the graph shell."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.engine.multi_agent.direct_node_event_sink import (
    build_direct_node_event_sink,
)
from app.engine.multi_agent.direct_node_final_state import finalize_direct_node_state
from app.engine.multi_agent.direct_node_llm_pipeline import (
    DirectNodeLlmPipelineDependencies,
    DirectNodeLlmPipelineRequest,
    execute_direct_node_llm_pipeline,
)
from app.engine.multi_agent.direct_node_pre_llm_pipeline import (
    DirectNodePreLlmPipelineDependencies,
    DirectNodePreLlmPipelineRequest,
    execute_direct_node_pre_llm_pipeline,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.tool_collection import ensure_direct_turn_policy_metadata
from app.engine.reasoning import (
    record_thinking_snapshot,
)

logger = logging.getLogger(__name__)

_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS = 45.0  # Phase F3 (2026-05-06): bumped 24->45s. Tool-heavy pointy turns regularly hit 25-35s; 24s caused canned fallback even when LLM was actively succeeding.


def _user_role_for_turn_policy(state: AgentState) -> str:
    ctx = state.get("context") if isinstance(state.get("context"), dict) else {}
    role = str(ctx.get("user_role") or state.get("role") or "student").strip()
    return role or "student"


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
    user_role = _user_role_for_turn_policy(state)
    ensure_direct_turn_policy_metadata(
        query=query,
        state=state,
        user_role=user_role,
    )

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
        llm_pipeline = await execute_direct_node_llm_pipeline(
            request=DirectNodeLlmPipelineRequest(
                query=query,
                state=state,
                bus_id=bus_id,
                push_event=push_event,
                tracer=tracer,
                ctx_for_preflight=ctx_for_preflight,
                has_uploaded_document_context=has_uploaded_document_context,
                domain_name_vi=domain_name_vi,
                sanitize_document_preview_response=(
                    sanitize_document_preview_response
                ),
                explicit_web_search_turn=explicit_web_search_turn,
                enable_natural_conversation=(
                    getattr(settings, "enable_natural_conversation", False) is True
                ),
                requested_model=state.get("model"),
                llm_presence_penalty=getattr(settings, "llm_presence_penalty", 0.0),
                llm_frequency_penalty=getattr(settings, "llm_frequency_penalty", 0.0),
                direct_max_rounds=getattr(settings, "direct_agent_max_tool_rounds", 12),
                host_ui_total_timeout_seconds=_HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS,
            ),
            dependencies=DirectNodeLlmPipelineDependencies(
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
                collect_direct_tools=collect_direct_tools,
                direct_required_tool_names=direct_required_tool_names,
                resolve_direct_answer_timeout_profile=(
                    resolve_direct_answer_timeout_profile
                ),
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
                get_phase_fallback=get_phase_fallback,
                record_thinking_snapshot_fn=record_thinking_snapshot,
                logger_obj=logger,
            ),
        )
        response = llm_pipeline.response
    elif not state.get("tool_call_events") and not state.get("tools_used"):
        ensure_direct_turn_policy_metadata(
            query=query,
            state=state,
            user_role=user_role,
            record_empty_policy=True,
        )

    if (
        not isinstance(state.get("_tool_policy_session"), dict)
        and not state.get("tool_call_events")
        and not state.get("tools_used")
    ):
        ensure_direct_turn_policy_metadata(
            query=query,
            state=state,
            user_role=user_role,
            record_empty_policy=True,
        )

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
