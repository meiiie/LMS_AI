"""
Shared multi-agent contract helpers for ChatOrchestrator.
"""

from __future__ import annotations


async def resolve_request_scope_impl(
    request,
    *,
    default_organization_id: str | None,
    enable_multi_tenant: bool,
    environment: str,
    get_current_org_id_fn,
    get_current_org_allowed_domains_fn,
    get_domain_router_fn,
    request_scope_cls,
):
    organization_id = (
        getattr(request, "organization_id", None)
        or get_current_org_id_fn()
    )
    if not organization_id and default_organization_id:
        if enable_multi_tenant and environment in ("production", "staging"):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403,
                detail="Organization context required for chat request scope",
            )
        organization_id = default_organization_id

    domain_router = get_domain_router_fn()
    org_allowed_domains = get_current_org_allowed_domains_fn()
    domain_id = await domain_router.resolve(
        query=request.message,
        explicit_domain_id=getattr(request, "domain_id", None),
        allowed_domains=org_allowed_domains,
    )
    return request_scope_cls(
        organization_id=organization_id,
        domain_id=domain_id,
    )


async def build_multi_agent_context_impl(
    context,
    session,
    *,
    resolve_lms_identity_fn,
) -> dict:
    lms_external_id, lms_connector_id = await resolve_lms_identity_fn(
        context.user_id,
        getattr(context, "organization_id", None),
    )
    user_facts = getattr(context, "user_facts", None)
    if user_facts is None:
        user_facts = []
    elif not isinstance(user_facts, list):
        user_facts = list(user_facts) if isinstance(user_facts, tuple) else [user_facts]

    return {
        "user_name": context.user_name,
        "user_role": context.user_role.value,
        "lms_course": context.lms_course_name,
        "lms_module": context.lms_module_id,
        "conversation_history": context.conversation_history,
        "semantic_context": context.semantic_context,
        "langchain_messages": context.langchain_messages,
        "history_list": context.history_list or [],
        "history_retrieval_summary": getattr(
            context,
            "history_retrieval_summary",
            {},
        )
        or {},
        "context_budget_summary": getattr(
            context,
            "context_budget_summary",
            {},
        )
        or {},
        "user_facts": user_facts,
        "pronoun_style": (
            getattr(context, "pronoun_style", None)
            or getattr(session.state, "pronoun_style", None)
        ),
        "conversation_summary": context.conversation_summary or "",
        "core_memory_block": context.core_memory_block,
        "is_follow_up": int(getattr(session.state, "total_responses", 0) or 0) > 0,
        "conversation_phase": (
            "opening"
            if session.state.total_responses == 0
            else ("engaged" if session.state.total_responses < 5 else ("deep" if session.state.total_responses < 20 else "closing"))
        ),
        "response_language": getattr(context, "response_language", None)
        or getattr(session.state, "response_language", "vi"),
        "personality_mode": getattr(context, "personality_mode", None),
        "total_responses": session.state.total_responses,
        "name_usage_count": session.state.name_usage_count,
        "recent_phrases": session.state.recent_phrases,
        "mood_hint": getattr(context, "mood_hint", "") or "",
        "organization_id": getattr(context, "organization_id", None),
        "images": [
            img.model_dump() if hasattr(img, "model_dump") else img
            for img in context.images
        ] if getattr(context, "images", None) else None,
        "image_input_error": getattr(context, "image_input_error", None),
        "lms_external_id": lms_external_id,
        "lms_connector_id": lms_connector_id,
        "page_context": getattr(context, "page_context", None),
        "student_state": getattr(context, "student_state", None),
        "available_actions": getattr(context, "available_actions", None),
        "host_context": getattr(context, "host_context", None),
        "host_capabilities": getattr(context, "host_capabilities", None),
        "host_action_feedback": getattr(context, "host_action_feedback", None),
        "_host_action_control_feedback": getattr(
            context,
            "host_action_control_feedback",
            None,
        ),
        "visual_context": getattr(context, "visual_context", None),
        "widget_feedback": getattr(context, "widget_feedback", None),
        "code_studio_context": getattr(context, "code_studio_context", None),
        "document_context": getattr(context, "document_context", None),
        # Wiii Pointy v2.8: explicit @ mention force-bind list.
        "force_skills": getattr(context, "force_skills", None),
        "pointy_mode": bool(getattr(context, "pointy_mode", False)),
    }


async def build_multi_agent_execution_input_impl(
    *,
    request,
    prepared_turn,
    include_streaming_fields: bool,
    thinking_effort: str | None,
    provider: str | None,
    request_id: str | None,
    build_multi_agent_context_fn,
    multi_agent_execution_input_cls,
    default_domain: str,
):
    context = prepared_turn.chat_context
    session = prepared_turn.session
    if context is None:
        raise ValueError("Prepared turn must include chat context")

    graph_context = await build_multi_agent_context_fn(context, session)
    if include_streaming_fields:
        graph_context.update(
            {
                "user_id": request.user_id,
                "show_previews": request.show_previews,
                "preview_types": request.preview_types,
                "preview_max_count": request.preview_max_count,
            }
        )
    if request_id:
        graph_context["request_id"] = request_id

    return multi_agent_execution_input_cls(
        query=context.message,
        user_id=context.user_id,
        session_id=str(prepared_turn.session_id),
        context=graph_context,
        domain_id=prepared_turn.request_scope.domain_id or default_domain,
        thinking_effort=thinking_effort,
        provider=provider,
        model=getattr(request, "model", None),
    )


def build_minimal_multi_agent_execution_input_impl(
    *,
    request,
    prepared_turn,
    thinking_effort: str | None,
    provider: str | None,
    request_id: str | None,
    multi_agent_execution_input_cls,
    default_domain: str,
):
    context = {
        "user_id": request.user_id,
        "user_role": request.role.value,
        "user_name": None,
        "conversation_history": "",
        "organization_id": prepared_turn.request_scope.organization_id,
        "response_language": getattr(getattr(prepared_turn, "chat_context", None), "response_language", None) or "vi",
    }
    if request_id:
        context["request_id"] = request_id

    return multi_agent_execution_input_cls(
        query=request.message,
        user_id=str(request.user_id),
        session_id=str(prepared_turn.session_id),
        context=context,
        domain_id=prepared_turn.request_scope.domain_id or default_domain,
        thinking_effort=thinking_effort,
        provider=provider,
        model=getattr(request, "model", None),
    )
