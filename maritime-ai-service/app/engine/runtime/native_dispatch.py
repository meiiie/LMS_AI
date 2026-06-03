"""Native chat dispatch — durable + metric-instrumented chat path.

Phase 19 of the runtime migration epic (issue #207). Closes the most
load-bearing gap from the brutal-honest SOTA assessment: until now,
every chat-completion turn went through the legacy ChatService path
without any record landing in the Phase 5/10c durable session log. That
made wake() (Phase 11a) and replay (Phase 11b/c) read-only — the data
they wanted to consume was never produced.

This dispatcher wraps ``ChatService.process_message`` with three things
the legacy path skipped:

1. **Durable event logging.** ``user_message`` event before the call,
   ``assistant_message`` after, ``tool_result`` per declared tool call.
   Now wake() can replay the conversation and replay_eval can diff it.
2. **Per-call metrics.** ``runtime.native_dispatch.runs`` counter
   labeled by status, ``runtime.native_dispatch.duration_ms`` summary.
   p50/p99 fall out of the existing Phase 13 façade.
3. **Run-as-subagent affordance.** Internally it's the same ChatService,
   but the durable log records a self-contained, replay-able turn.
   Future work can swap the inner call for a real native runner without
   changing the dispatch interface.

Critical design choice: this is **observability + durability**, not a
rewrite. Same response shape, same latency profile (~1ms overhead for
the three log appends + metric calls). When the team is ready to swap
the inner call for a lane-resolved native runner, only the body of
``_invoke_inner`` changes.

The dispatcher is wired up by the edge endpoints when
``is_native_runtime_enabled_for(org_id)`` returns True (Phase 14
canary). Legacy ``/api/v1/chat`` callers stay on the bare ChatService
path — the migration is opt-in per org.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.engine.runtime.lifecycle import HookPoint, get_lifecycle
from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.engine.runtime.session_event_log import (
    SessionEventLog,
    get_session_event_log,
)
from app.engine.runtime.tracing import span as trace_span

logger = logging.getLogger(__name__)


def _serialise_tool_calls(metadata) -> list[dict]:
    """Pull a structured list of tool calls from response metadata.

    Accepts both the ``tools_used`` shape (LMS legacy: list of
    ``{name, description}``) and the ``tool_calls`` shape (native: list
    of ``{name, args, result}``). Returns whichever is non-empty as
    plain dicts safe to JSON-encode for the event payload.
    """
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("tool_calls")
    if isinstance(raw, list) and raw:
        return [
            sanitize_runtime_payload(c if isinstance(c, dict) else {"raw": str(c)})
            for c in raw
        ]
    raw = metadata.get("tools_used")
    if isinstance(raw, list) and raw:
        return [
            sanitize_runtime_payload(c if isinstance(c, dict) else {"name": str(c)})
            for c in raw
        ]
    return []


async def _invoke_inner(chat_request, background_save):
    """Call into the existing ChatService.

    Imported lazily so this module's import never pulls ChatService.
    The legacy path is used today; a native lane-resolved path can
    replace this body in a future phase without changing the dispatch
    surface.
    """
    from app.services.chat_service import get_chat_service

    return await get_chat_service().process_message(
        chat_request, background_save=background_save
    )


def _emit_finalization_metric(
    *,
    stage: str,
    status: str,
    run_status: str,
    transport: str = "chat",
) -> None:
    inc_counter(
        "runtime.native_dispatch.finalization",
        labels={
            "stage": str(stage or "unknown"),
            "status": str(status or "unknown"),
            "run_status": str(run_status or "unknown"),
            "transport": str(transport or "unknown"),
        },
    )


async def _append_finalization_event(
    log: SessionEventLog,
    *,
    session_id: str,
    org_id: Optional[str],
    event_type: str,
    payload: dict,
    stage: str,
    run_status: str,
) -> None:
    try:
        await log.append(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_finalization_metric(
            stage=stage,
            status="error",
            run_status=run_status,
        )
        logger.debug(
            "[native_dispatch] finalization append %s skipped: %s",
            event_type,
            exc,
        )
        raise
    _emit_finalization_metric(
        stage=stage,
        status="success",
        run_status=run_status,
    )


async def native_chat_dispatch(
    chat_request,
    *,
    background_save=None,
    event_log: Optional[SessionEventLog] = None,
):
    """Process ``chat_request`` with durable + metric-instrumented dispatch.

    Logs user_message + assistant_message events around the inner call
    so the conversation becomes wake()-able and replay-able. Tool
    invocations declared in the response metadata produce one
    tool_result event each.

    Returns the same ``InternalChatResponse`` that ChatService would
    have returned — callers (edge endpoints + legacy chat) can swap to
    this dispatcher with no shape change.
    """
    log = event_log or get_session_event_log()
    session_id = (
        getattr(chat_request, "session_id", None)
        or f"native::{getattr(chat_request, 'user_id', 'unknown')}"
    )
    org_id = getattr(chat_request, "organization_id", None)
    user_message = getattr(chat_request, "message", "") or ""

    lifecycle = get_lifecycle()
    await lifecycle.fire(
        HookPoint.ON_RUN_START,
        {
            "session_id": session_id,
            "org_id": org_id,
            "user_id": getattr(chat_request, "user_id", None),
            "user_message": user_message,
        },
    )

    await log.append(
        session_id=session_id,
        event_type="user_message",
        payload={
            "text": user_message,
            "user_id": getattr(chat_request, "user_id", None),
            "role": (
                getattr(getattr(chat_request, "role", None), "value", None)
                or str(getattr(chat_request, "role", ""))
            ),
            "domain_id": getattr(chat_request, "domain_id", None),
        },
        org_id=org_id,
    )

    started = time.monotonic()
    try:
        with trace_span(
            "native_dispatch.invoke_inner",
            attributes={
                "session_id": session_id,
                "org_id": org_id,
                "user_id": getattr(chat_request, "user_id", None),
            },
        ):
            response = await _invoke_inner(chat_request, background_save)
    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.monotonic() - started) * 1000)
        error_text = redact_runtime_secret_text(f"{type(exc).__name__}: {exc}")
        await _append_finalization_event(
            log,
            session_id=session_id,
            event_type="assistant_message",
            payload={
                "text": "",
                "status": "error",
                "error": error_text,
                "duration_ms": duration_ms,
            },
            org_id=org_id,
            stage="assistant_message_append",
            run_status="error",
        )
        inc_counter(
            "runtime.native_dispatch.runs", labels={"status": "error"}
        )
        record_latency_ms(
            "runtime.native_dispatch.duration_ms",
            float(duration_ms),
            labels={"status": "error"},
        )
        await lifecycle.fire(
            HookPoint.ON_RUN_ERROR,
            {
                "session_id": session_id,
                "org_id": org_id,
                "duration_ms": duration_ms,
                "error": error_text,
            },
        )
        await lifecycle.fire(
            HookPoint.ON_RUN_END,
            {
                "session_id": session_id,
                "org_id": org_id,
                "duration_ms": duration_ms,
                "status": "error",
            },
        )
        raise

    duration_ms = int((time.monotonic() - started) * 1000)
    metadata = getattr(response, "metadata", None) or {}
    tool_calls = _serialise_tool_calls(metadata)
    response_text = getattr(response, "message", "") or ""

    await _append_finalization_event(
        log,
        session_id=session_id,
        event_type="assistant_message",
        payload={
            "text": response_text,
            "status": "success",
            "tool_calls": tool_calls,
            "duration_ms": duration_ms,
            "agent_type": (
                getattr(getattr(response, "agent_type", None), "value", None)
                or str(getattr(response, "agent_type", ""))
            ),
        },
        org_id=org_id,
        stage="assistant_message_append",
        run_status="success",
    )
    for call in tool_calls:
        await _append_finalization_event(
            log,
            session_id=session_id,
            event_type="tool_result",
            payload={
                "tool_call_id": str(
                    call.get("id") or call.get("name") or "unknown"
                ),
                "name": call.get("name"),
                "content": str(call.get("result", call.get("description", ""))),
            },
            org_id=org_id,
            stage="tool_result_append",
            run_status="success",
        )

    inc_counter(
        "runtime.native_dispatch.runs", labels={"status": "success"}
    )
    record_latency_ms(
        "runtime.native_dispatch.duration_ms",
        float(duration_ms),
        labels={"status": "success"},
    )
    await lifecycle.fire(
        HookPoint.ON_RUN_END,
        {
            "session_id": session_id,
            "org_id": org_id,
            "duration_ms": duration_ms,
            "status": "success",
            "tool_call_count": len(tool_calls),
        },
    )
    return response


__all__ = ["native_chat_dispatch"]
