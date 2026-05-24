"""Exception fallback lifecycle for the direct response node."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_failover_runtime import classify_failover_reason_impl
from app.engine.multi_agent.direct_node_emergency_fallbacks import (
    _emergency_search_fallback,
    _emit_synthetic_tool_events,
    _salvage_direct_turn_from_final_result,
)
from app.engine.multi_agent.direct_node_exception_fallback_contract import (
    DirectNodeExceptionFallbackDependencies,
    DirectNodeExceptionFallbackRequest,
    DirectNodeExceptionFallbackResult,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.state import AgentState

logger = logging.getLogger(__name__)


async def handle_direct_node_generation_exception(
    *,
    request: DirectNodeExceptionFallbackRequest,
    dependencies: DirectNodeExceptionFallbackDependencies,
) -> DirectNodeExceptionFallbackResult:
    """Recover or re-raise after direct-node LLM/tool generation fails."""

    exc = request.exc
    query = request.query
    state = request.state
    ctx_for_preflight = request.ctx_for_preflight
    tools = request.tools
    tool_call_events = request.tool_call_events
    llm_response = request.llm_response
    messages = request.messages
    llm = request.llm
    routing_intent = request.routing_intent
    response_language = request.response_language
    is_identity_turn = request.is_identity_turn
    explicit_user_provider = request.explicit_user_provider
    explicit_web_search_turn = request.explicit_web_search_turn
    tracer = request.tracer
    push_event = request.push_event

    log = dependencies.logger_obj or logger
    salvage_direct_turn = (
        dependencies.salvage_direct_turn_from_final_result_fn
        or _salvage_direct_turn_from_final_result
    )
    emergency_search = (
        dependencies.emergency_search_fallback_fn or _emergency_search_fallback
    )
    emit_synthetic_events = (
        dependencies.emit_synthetic_tool_events_fn or _emit_synthetic_tool_events
    )
    classify_failover_reason = (
        dependencies.classify_failover_reason_fn or classify_failover_reason_impl
    )

    salvaged = await salvage_direct_turn(
        llm_response=llm_response,
        messages=messages,
        extract_direct_response=dependencies.extract_direct_response,
        sanitize_structured_visual_answer_text=(
            dependencies.sanitize_structured_visual_answer_text
        ),
        sanitize_wiii_house_text=dependencies.sanitize_wiii_house_text,
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
            dependencies.record_direct_node_thinking_snapshot(
                state=state,
                thinking=salvaged_thinking,
                provenance="final_snapshot",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
        log.warning(
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
        return DirectNodeExceptionFallbackResult(
            response=response,
            tool_call_events=tool_call_events,
        )

    uploaded_fallback = ""
    if isinstance(exc, ProviderUnavailableError):
        uploaded_fallback = dependencies.build_uploaded_document_context_fallback_answer(
            query,
            ctx_for_preflight,
        )
    if isinstance(exc, ProviderUnavailableError) and uploaded_fallback:
        response = uploaded_fallback
        log.info(
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
        return DirectNodeExceptionFallbackResult(
            response=response,
            tool_call_events=tool_call_events,
        )

    if isinstance(exc, ProviderUnavailableError) and tool_call_events:
        template_response = _build_template_response(
            query=query,
            tool_call_events=tool_call_events,
            build_search_template_fallback=dependencies.build_search_template_fallback,
            log=log,
            warning_message="[DIRECT] Provider unavailable and search fallback build failed: %s",
        )
        if not template_response:
            raise exc
        template_tools = _record_template_tools(
            state=state,
            tool_call_events=tool_call_events,
        )
        log.info(
            "[DIRECT] Provider unavailable after tools; returning "
            "source-backed fallback (tools=%d, len=%d)",
            len(template_tools),
            len(template_response),
        )
        tracer.end_step(
            result="Source-backed fallback (provider unavailable after tools)",
            confidence=0.6,
            details={
                "response_type": "search_template_fallback",
                "tools_used_count": len(template_tools),
                "response_length": len(template_response),
            },
        )
        return DirectNodeExceptionFallbackResult(
            response=template_response,
            tool_call_events=tool_call_events,
        )

    if isinstance(exc, ProviderUnavailableError) and dependencies.needs_web_search(query):
        fallback_events = await _run_emergency_search(
            query=query,
            tools=tools,
            emergency_search=emergency_search,
            log=log,
            warning_message="[DIRECT] Provider unavailable and emergency search failed: %s",
        )
        template_response = ""
        if fallback_events:
            try:
                await emit_synthetic_events(
                    fallback_events,
                    push_event=push_event,
                )
                state["tool_call_events"] = fallback_events
                template_response = dependencies.build_search_template_fallback(
                    query=query,
                    tool_call_events=fallback_events,
                )
            except Exception as template_error:
                log.warning(
                    "[DIRECT] Emergency search template fallback failed: %s",
                    template_error,
                )
                template_response = ""
        if not template_response:
            raise exc
        template_tools = _record_template_tools(
            state=state,
            tool_call_events=fallback_events,
        )
        log.info(
            "[DIRECT] Provider unavailable before tool planning; "
            "returned emergency source-backed fallback (tools=%d, len=%d)",
            len(template_tools),
            len(template_response),
        )
        tracer.end_step(
            result="Source-backed fallback (provider unavailable before tools)",
            confidence=0.55,
            details={
                "response_type": "search_template_fallback",
                "tools_used_count": len(template_tools),
                "response_length": len(template_response),
            },
        )
        return DirectNodeExceptionFallbackResult(
            response=template_response,
            tool_call_events=fallback_events,
        )

    if explicit_user_provider and dependencies.needs_web_search(query):
        return await _handle_explicit_provider_web_failure(
            exc=exc,
            query=query,
            state=state,
            tools=tools,
            tool_call_events=tool_call_events,
            explicit_user_provider=explicit_user_provider,
            build_search_template_fallback=dependencies.build_search_template_fallback,
            emergency_search=emergency_search,
            emit_synthetic_events=emit_synthetic_events,
            push_event=push_event,
            classify_failover_reason=classify_failover_reason,
            tracer=tracer,
            log=log,
        )

    if explicit_user_provider:
        uploaded_fallback = dependencies.build_uploaded_document_context_fallback_answer(
            query,
            ctx_for_preflight,
        )
        if uploaded_fallback:
            response = uploaded_fallback
            log.info(
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
            return DirectNodeExceptionFallbackResult(
                response=response,
                tool_call_events=tool_call_events,
            )
        if isinstance(exc, ProviderUnavailableError):
            raise exc
        provider_error = _provider_unavailable_from_exception(
            exc=exc,
            explicit_user_provider=explicit_user_provider,
            classify_failover_reason=classify_failover_reason,
        )
        raise provider_error from exc

    log.warning("[DIRECT] LLM generation failed: %s", exc)
    log.info(
        "[DIRECT] Template fallback consideration - "
        "tool_call_events count=%d, types=%s",
        len(tool_call_events) if tool_call_events else 0,
        [
            f"{event.get('type')}:{event.get('name')}"
            for event in (tool_call_events or [])[:6]
        ],
    )
    return await _handle_default_generation_failure(
        exc=exc,
        query=query,
        state=state,
        ctx_for_preflight=ctx_for_preflight,
        tools=tools,
        tool_call_events=tool_call_events,
        explicit_web_search_turn=explicit_web_search_turn,
        needs_web_search=dependencies.needs_web_search,
        build_search_template_fallback=dependencies.build_search_template_fallback,
        build_uploaded_document_context_fallback_answer=(
            dependencies.build_uploaded_document_context_fallback_answer
        ),
        build_codebase_analysis_fallback_answer=(
            dependencies.build_codebase_analysis_fallback_answer
        ),
        build_codebase_analysis_fallback_thinking=(
            dependencies.build_codebase_analysis_fallback_thinking
        ),
        get_phase_fallback=dependencies.get_phase_fallback,
        record_direct_node_thinking_snapshot=(
            dependencies.record_direct_node_thinking_snapshot
        ),
        record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
        emergency_search=emergency_search,
        inc_counter=dependencies.inc_counter,
        tracer=tracer,
        log=log,
    )


async def _handle_explicit_provider_web_failure(
    *,
    exc: Exception,
    query: str,
    state: AgentState,
    tools: list[Any],
    tool_call_events: list[dict[str, Any]],
    explicit_user_provider: str,
    build_search_template_fallback: Callable[..., str],
    emergency_search: Callable[..., Any],
    emit_synthetic_events: Callable[..., Any],
    push_event: Callable[..., Any],
    classify_failover_reason: Callable[..., dict[str, Any]],
    tracer: Any,
    log: logging.Logger,
) -> DirectNodeExceptionFallbackResult:
    fallback_events = list(tool_call_events or [])
    if not fallback_events:
        log.info(
            "[DIRECT] Explicit provider web turn failed before tool "
            "evidence - engaging LLM-free emergency search"
        )
        fallback_events = await _run_emergency_search(
            query=query,
            tools=tools,
            emergency_search=emergency_search,
            log=log,
            warning_message="[DIRECT] Explicit-provider emergency search failed: %s",
        )

    template_response = ""
    if fallback_events:
        try:
            if not tool_call_events:
                await emit_synthetic_events(
                    fallback_events,
                    push_event=push_event,
                )
                state["tool_call_events"] = fallback_events
            template_response = build_search_template_fallback(
                query=query,
                tool_call_events=fallback_events,
            )
        except Exception as template_error:
            log.warning(
                "[DIRECT] Explicit-provider template fallback failed: %s",
                template_error,
            )
            template_response = ""
    if not template_response:
        provider_error = _provider_unavailable_from_exception(
            exc=exc,
            explicit_user_provider=explicit_user_provider,
            classify_failover_reason=classify_failover_reason,
        )
        raise provider_error from exc

    if fallback_events and not tool_call_events:
        tool_call_events = fallback_events
    template_tools = _record_template_tools(
        state=state,
        tool_call_events=fallback_events,
    )
    log.info(
        "[DIRECT] Explicit provider failed on web turn; returned "
        "source-backed emergency fallback (tools=%d, len=%d)",
        len(template_tools),
        len(template_response),
    )
    tracer.end_step(
        result="Source-backed fallback (explicit provider web failure)",
        confidence=0.55,
        details={
            "response_type": "search_template_fallback",
            "tools_used_count": len(template_tools),
            "response_length": len(template_response),
        },
    )
    return DirectNodeExceptionFallbackResult(
        response=template_response,
        tool_call_events=tool_call_events,
    )


async def _handle_default_generation_failure(
    *,
    exc: Exception,
    query: str,
    state: AgentState,
    ctx_for_preflight: dict[str, Any],
    tools: list[Any],
    tool_call_events: list[dict[str, Any]],
    explicit_web_search_turn: bool,
    needs_web_search: Callable[[str], bool],
    build_search_template_fallback: Callable[..., str],
    build_uploaded_document_context_fallback_answer: Callable[..., str],
    build_codebase_analysis_fallback_answer: Callable[[str], str],
    build_codebase_analysis_fallback_thinking: Callable[[str], str],
    get_phase_fallback: Callable[[AgentState], str],
    record_direct_node_thinking_snapshot: Callable[..., str],
    record_thinking_snapshot_fn: Callable[..., Any],
    emergency_search: Callable[..., Any],
    inc_counter: Callable[..., Any],
    tracer: Any,
    log: logging.Logger,
) -> DirectNodeExceptionFallbackResult:
    fallback_events = list(tool_call_events or [])
    if not fallback_events and needs_web_search(query):
        log.info(
            "[DIRECT] Round-0 timeout with empty tool history - "
            "engaging LLM-free emergency search"
        )
        fallback_events = await _run_emergency_search(
            query=query,
            tools=tools,
            emergency_search=emergency_search,
            log=log,
            warning_message="[DIRECT] Emergency search failed: %s",
            success_message="[DIRECT] Emergency search produced %d synthetic events",
        )

    template_response = _build_template_response(
        query=query,
        tool_call_events=fallback_events,
        build_search_template_fallback=build_search_template_fallback,
        log=log,
        success_message="[DIRECT] Template fallback build returned len=%d",
        warning_message="[DIRECT] Template fallback build failed: %s",
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
        template_tools = _record_template_tools(
            state=state,
            tool_call_events=tool_call_events,
        )
        log.info(
            "[DIRECT] Source-backed template fallback engaged "
            "(synthesis LLM unavailable, tools=%d, len=%d)",
            len(template_tools),
            len(template_response),
        )
        tracer.end_step(
            result="Source-backed fallback (synthesis LLM unavailable)",
            confidence=0.6,
            details={
                "response_type": "search_template_fallback",
                "tools_used_count": len(template_tools),
                "response_length": len(template_response),
            },
        )
        return DirectNodeExceptionFallbackResult(
            response=template_response,
            tool_call_events=tool_call_events,
        )

    codebase_fallback = (
        build_codebase_analysis_fallback_answer(query)
        if _is_codebase_analysis_query(query) and not explicit_web_search_turn
        else ""
    )
    uploaded_fallback = build_uploaded_document_context_fallback_answer(
        query,
        ctx_for_preflight,
    )
    if isinstance(exc, ProviderUnavailableError) and not uploaded_fallback and not codebase_fallback:
        raise exc

    if uploaded_fallback:
        response = uploaded_fallback
    elif codebase_fallback:
        response = codebase_fallback
        codebase_thinking = build_codebase_analysis_fallback_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=codebase_thinking,
            provenance="deterministic_codebase_fallback",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
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
    return DirectNodeExceptionFallbackResult(
        response=response,
        tool_call_events=tool_call_events,
    )


async def _run_emergency_search(
    *,
    query: str,
    tools: list[Any],
    emergency_search: Callable[..., Any],
    log: logging.Logger,
    warning_message: str,
    success_message: str | None = None,
) -> list[dict[str, Any]]:
    try:
        fallback_events = await emergency_search(
            query=query,
            tools=tools,
            timeout_seconds=30.0,
        )
        if success_message:
            log.info(success_message, len(fallback_events))
        return fallback_events
    except Exception as emergency_error:
        log.warning(warning_message, emergency_error)
        return []


def _build_template_response(
    *,
    query: str,
    tool_call_events: list[dict[str, Any]],
    build_search_template_fallback: Callable[..., str],
    log: logging.Logger,
    warning_message: str,
    success_message: str | None = None,
) -> str:
    template_response = ""
    try:
        template_response = build_search_template_fallback(
            query=query,
            tool_call_events=tool_call_events,
        )
        if success_message:
            log.info(success_message, len(template_response or ""))
    except Exception as template_error:
        log.warning(warning_message, template_error)
    return template_response


def _record_template_tools(
    *,
    state: AgentState,
    tool_call_events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    template_tool_names = sorted({
        str(event.get("name") or "")
        for event in tool_call_events
        if event.get("type") == "result" and event.get("name")
    })
    template_tools = [{"name": name} for name in template_tool_names if name]
    if template_tools:
        state["tools_used"] = template_tools
    return template_tools


def _provider_unavailable_from_exception(
    *,
    exc: Exception,
    explicit_user_provider: str,
    classify_failover_reason: Callable[..., dict[str, Any]],
) -> ProviderUnavailableError:
    classified = classify_failover_reason(error=exc)
    return ProviderUnavailableError(
        provider=str(explicit_user_provider).strip().lower(),
        reason_code=str(classified.get("reason_code") or "provider_unavailable"),
        message="Provider được chọn hiện không sẵn sàng để xử lý yêu cầu này.",
        details=classified.get("detail"),
    )
