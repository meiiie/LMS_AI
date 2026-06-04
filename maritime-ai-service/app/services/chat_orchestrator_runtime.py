"""Runtime helpers for the chat orchestrator shell."""

from __future__ import annotations

from typing import Any

from app.core.constants import MAX_CONTENT_SNIPPET_LENGTH
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.engine.multi_agent.runtime_flow_ledger import sanitize_runtime_flow_trace
from app.engine.multi_agent.runtime_contracts import WiiiRunContext, WiiiTurnRequest
from app.models.schemas import ChatRequest, Source


async def prepare_turn_impl(
    *,
    request: Any,
    background_save: Any,
    persist_user_message_immediately: bool,
    normalize_thread_id_fn: Any,
    resolve_request_scope_fn: Any,
    session_manager: Any,
    maybe_summarize_previous_session_fn: Any,
    load_pronoun_style_from_facts_fn: Any,
    validate_request_fn: Any,
    persist_chat_message_fn: Any,
    input_processor: Any,
    semantic_memory: Any,
    persist_pronoun_style_fn: Any,
    prepared_turn_cls: Any,
    detect_pronoun_style_fn: Any,
) -> Any:
    from app.prompts.prompt_context_utils import resolve_response_language
    from app.engine.personality_mode import resolve_personality_mode

    user_id = str(request.user_id)
    message = request.message

    thread_id = normalize_thread_id_fn(request)
    request_scope = await resolve_request_scope_fn(request)

    session = session_manager.get_or_create_session(
        user_id,
        thread_id,
        organization_id=request_scope.organization_id,
    )
    session_id = session.session_id

    if session.state.is_first_message and background_save:
        maybe_summarize_previous_session_fn(
            background_save,
            user_id,
            request_scope.organization_id,
        )
    if session.state.is_first_message and session.state.pronoun_style is None:
        load_pronoun_style_from_facts_fn(session, user_id)

    validation = await validate_request_fn(
        request=request,
        session_id=session_id,
    )
    if validation.blocked:
        return prepared_turn_cls(
            request_scope=request_scope,
            session=session,
            session_id=session_id,
            validation=validation,
        )

    persist_chat_message_fn(
        session_id=session_id,
        role="user",
        content=message,
        user_id=user_id,
        organization_id=request_scope.organization_id,
        background_save=background_save,
        immediate=persist_user_message_immediately,
    )
    session_manager.append_message(
        session_id=session_id,
        role="user",
        content=message,
        organization_id=request_scope.organization_id,
    )

    context = await input_processor.build_context(
        request=request,
        session_id=session_id,
        user_name=session.user_name,
        recent_history_fallback=session_manager.get_recent_messages(
            session_id,
            organization_id=request_scope.organization_id,
        ),
    )
    context.organization_id = request_scope.organization_id

    raw_host_context = getattr(getattr(request, "user_context", None), "host_context", None)
    host_language = None
    if isinstance(raw_host_context, dict):
        host_language = raw_host_context.get("language")
    elif raw_host_context is not None:
        host_language = getattr(raw_host_context, "language", None)

    resolved_response_language = resolve_response_language(
        message,
        session_language=getattr(session.state, "response_language", None),
        host_language=host_language,
        user_language=getattr(getattr(request, "user_context", None), "language", None),
    )
    session.state.update_response_language(resolved_response_language)
    context.response_language = resolved_response_language
    context.personality_mode = resolve_personality_mode("web")

    if not session.user_name:
        extracted_name = input_processor.extract_user_name(message)
        if extracted_name:
            session_manager.update_user_name(
                session_id,
                extracted_name,
                organization_id=request_scope.organization_id,
            )
            context.user_name = extracted_name

    effective_pronoun = detect_pronoun_style_fn(message)
    if effective_pronoun:
        session.state.update_pronoun_style(effective_pronoun)
    else:
        effective_pronoun = await input_processor.validate_pronoun_request(
            message=message,
            current_style=session.state.pronoun_style,
        )
        if effective_pronoun:
            session.state.update_pronoun_style(effective_pronoun)

    if effective_pronoun and semantic_memory and background_save:
        persist_pronoun_style_fn(background_save, user_id, effective_pronoun)

    return prepared_turn_cls(
        request_scope=request_scope,
        session=session,
        session_id=session_id,
        validation=validation,
        chat_context=context,
    )


def build_wiii_turn_request(
    *,
    execution_input: Any,
    organization_id: str | None = None,
) -> WiiiTurnRequest:
    """Build the native WiiiRunner turn request from service execution input."""

    return WiiiTurnRequest(
        query=execution_input.query,
        run_context=WiiiRunContext(
            user_id=execution_input.user_id,
            session_id=execution_input.session_id,
            domain_id=execution_input.domain_id,
            organization_id=organization_id,
            context=execution_input.context,
            thinking_effort=execution_input.thinking_effort,
            provider=execution_input.provider,
            model=getattr(execution_input, "model", None),
        ),
    )


async def process_with_multi_agent_impl(
    *,
    context: Any,
    session: Any,
    domain_id: str | None,
    thinking_effort: str | None,
    provider: str | None,
    model: str | None,
    build_multi_agent_execution_input_fn: Any,
    request_scope_cls: Any,
    prepared_turn_cls: Any,
    processing_result_cls: Any,
    agent_type_map: dict[str, Any],
    default_agent_type: Any,
) -> Any:
    from app.engine.multi_agent.runtime import run_wiii_turn

    prepared_turn = prepared_turn_cls(
        request_scope=request_scope_cls(
            organization_id=getattr(context, "organization_id", None),
            domain_id=domain_id,
        ),
        session=session,
        session_id=context.session_id,
        validation=None,
        chat_context=context,
    )
    execution_input = await build_multi_agent_execution_input_fn(
        request=ChatRequest.model_construct(
            user_id=context.user_id,
            message=context.message,
            role=context.user_role,
            model=model,
            show_previews=False,
            preview_types=None,
            preview_max_count=None,
        ),
        prepared_turn=prepared_turn,
        thinking_effort=thinking_effort,
        provider=provider,
    )

    turn_result = await run_wiii_turn(
        build_wiii_turn_request(
            execution_input=execution_input,
            organization_id=getattr(context, "organization_id", None),
        )
    )
    result = dict(turn_result.payload)

    response_text = result.get("response", "")
    sources = result.get("sources", [])

    source_objects = []
    for s in sources:
        source_objects.append(
            Source(
                node_id=s.get("node_id", ""),
                title=s.get("title", ""),
                source_type="knowledge_graph",
                content_snippet=s.get("content", "")[:MAX_CONTENT_SNIPPET_LENGTH],
                image_url=s.get("image_url"),
                page_number=s.get("page_number"),
                document_id=s.get("document_id"),
                bounding_boxes=s.get("bounding_boxes"),
            )
        )

    tools_used = result.get("agent_outputs", {}).get("tutor_tools_used", [])
    if not tools_used:
        tools_used = result.get("tools_used", [])

    routed_agent = result.get("next_agent", "")
    agent_type = agent_type_map.get(routed_agent, default_agent_type)
    runtime_llm = resolve_runtime_llm_metadata(
        result
        or {
            "provider": execution_input.provider,
        }
    )
    runtime_flow_trace = result.get("runtime_flow_trace")
    runtime_flow_trace = (
        sanitize_runtime_flow_trace(runtime_flow_trace)
        if runtime_flow_trace
        else None
    )

    return processing_result_cls(
        message=response_text,
        agent_type=agent_type,
        sources=source_objects if source_objects else None,
        metadata={
            "multi_agent": True,
            **runtime_llm,
            "current_agent": result.get("current_agent", ""),
            "grader_score": result.get("grader_score", 0),
            "tools_used": tools_used,
            "reasoning_trace": result.get("reasoning_trace"),
            "thinking": result.get("thinking") or result.get("thinking_content"),
            "thinking_content": result.get("thinking_content"),
            "thinking_lifecycle": result.get("thinking_lifecycle"),
            "domain_notice": result.get("domain_notice"),
            "routing_metadata": result.get("routing_metadata"),
            "runtime_flow_trace": runtime_flow_trace,
        },
    )
