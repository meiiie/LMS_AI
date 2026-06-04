"""Response finalization after direct tool-round execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.direct_final_synthesis_runtime import (
    extract_direct_visible_text,
    run_direct_final_synthesis,
)
from app.engine.multi_agent.direct_tool_message_runtime import (
    build_assistant_message,
)
from app.engine.multi_agent.direct_web_search_policy import (
    _should_use_search_template_for_empty_response,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.external_app_action_runtime import (
    external_app_action_final_answer as _external_app_action_final_answer,
    facebook_direct_apply_final_answer as _facebook_direct_apply_final_answer,
)


@dataclass(slots=True)
class DirectToolResponseFinalization:
    """Final direct response state after tool evidence has been reconciled."""

    llm_response: Any
    messages: list[Any]
    resolved_provider: str | None

def facebook_direct_apply_final_answer(
    tool_call_events: list[dict[str, Any]],
) -> str:
    """Build a stable answer for host-action publish requests.

    The backend now prefers a core-owned Wiii Connect execution path and keeps
    the older host-action result envelope as a compatible fallback. Do not ask
    the model to reinterpret this intermediate JSON; it can contradict the
    audited connector state.
    """

    return _facebook_direct_apply_final_answer(tool_call_events)


def _record_final_answer_trace(
    state: dict[str, Any] | None,
    *,
    source: str,
    reason: str,
    status: str = "resolved",
) -> None:
    if not isinstance(state, dict):
        return
    state["_final_answer_trace"] = {
        "version": "final_answer_trace.v1",
        "source": source,
        "reason": reason,
        "status": status,
        "answer_present": True,
    }


async def finalize_direct_tool_response(
    *,
    llm_response: Any,
    messages: list[Any],
    tools: list[Any],
    tool_call_events: list[dict[str, Any]],
    query: str,
    state: dict[str, Any],
    push_event: Callable[[dict[str, Any]], Awaitable[Any]],
    native_tool_messages: bool,
    llm_base: Any,
    llm_auto: Any,
    llm_with_tools: Any,
    provider: str | None,
    resolved_provider: str | None,
    request_failover_mode: str,
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None,
    ainvoke_with_fallback: Callable[..., Awaitable[Any]],
    stream_direct_wait_heartbeats: Callable[..., Awaitable[Any]],
    remember_execution_target: Callable[..., tuple[str | None, str | None]],
    runtime_tier_for: Callable[..., str],
    inject_widget_blocks_from_tool_results: Callable[..., Any],
    structured_visuals_enabled: bool,
    logger_obj: logging.Logger | None = None,
) -> DirectToolResponseFinalization:
    """Finalize a post-tool response with search fallback, synthesis, and widgets."""
    log = logger_obj or logging.getLogger(__name__)
    next_response = llm_response
    next_messages = messages
    next_resolved_provider = resolved_provider

    remaining_tool_calls = bool(
        tools and hasattr(next_response, "tool_calls") and next_response.tool_calls
    )
    visible_response_text = extract_direct_visible_text(
        getattr(next_response, "content", "")
    )

    external_action_answer = _external_app_action_final_answer(
        tool_call_events,
    )
    if external_action_answer:
        _record_final_answer_trace(
            state,
            source="wiii_connect_action_result",
            reason="external_app_action_payload",
        )
        next_response = build_assistant_message(
            external_action_answer,
            native_tool_messages=native_tool_messages,
        )
        visible_response_text = external_action_answer
        remaining_tool_calls = False

    if (
        tool_call_events
        and not visible_response_text
        and _should_use_search_template_for_empty_response(
            query=query,
            state=state,
            tool_call_events=tool_call_events,
        )
    ):
        template_response = ""
        try:
            template_response = build_search_template_fallback(
                query=query,
                tool_call_events=tool_call_events,
            )
        except Exception as template_error:  # noqa: BLE001
            log.warning(
                "[DIRECT] Web-search empty-response template synthesis failed: %s",
                template_error,
            )
        if template_response:
            log.info(
                "[DIRECT] Web-search returning source-backed template "
                "without slow synthesis LLM (events=%d, len=%d)",
                len(tool_call_events),
                len(template_response),
            )
            next_response = build_assistant_message(
                template_response,
                native_tool_messages=native_tool_messages,
            )
            visible_response_text = template_response
            remaining_tool_calls = False

    if tool_call_events and (remaining_tool_calls or not visible_response_text):
        log.warning(
            "[DIRECT] Tool loop ended without final prose "
            "(remaining_tool_calls=%s, visible_len=%d) -> forcing no-tool synthesis",
            remaining_tool_calls,
            len(visible_response_text),
        )
        synthesis_result = await run_direct_final_synthesis(
            messages=next_messages,
            query=query,
            state=state,
            tool_call_events=tool_call_events,
            push_event=push_event,
            native_tool_messages=native_tool_messages,
            llm_base=llm_base,
            llm_auto=llm_auto,
            llm_with_tools=llm_with_tools,
            provider=provider,
            resolved_provider=next_resolved_provider,
            request_failover_mode=request_failover_mode,
            allowed_fallback_providers=allowed_fallback_providers,
            ainvoke_with_fallback=ainvoke_with_fallback,
            stream_direct_wait_heartbeats=stream_direct_wait_heartbeats,
            remember_execution_target=remember_execution_target,
            runtime_tier_for=runtime_tier_for,
        )
        next_response = synthesis_result.llm_response
        next_messages = synthesis_result.messages
        next_resolved_provider = synthesis_result.resolved_provider

    next_response = inject_widget_blocks_from_tool_results(
        next_response,
        tool_call_events,
        query=query,
        structured_visuals_enabled=structured_visuals_enabled,
    )

    return DirectToolResponseFinalization(
        llm_response=next_response,
        messages=next_messages,
        resolved_provider=next_resolved_provider,
    )
