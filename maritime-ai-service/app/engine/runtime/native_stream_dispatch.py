"""Streaming counterpart to ``native_chat_dispatch`` for SSE chat paths.

Phase 30 of the runtime migration epic (issue #207). Phase 19 wired
``/v1/chat/completions`` (single-shot) through ``native_chat_dispatch``
so every edge-endpoint chat got durable session events + metrics +
tracing + lifecycle hooks. The UI's primary path —
``POST /api/v1/chat/stream/v3`` — is an SSE generator and was left on
the legacy track because the flat-call wrapper does not fit a stream.

This module ships the streaming variant. The flow:

1. Caller hands us a chat_request + an inner async generator that
   produces SSE byte chunks.
2. We open a span, fire ``on_run_start``, append the ``user_message``
   event to the durable log — all BEFORE the first yield.
3. Every chunk from the inner generator passes through unchanged so
   the SSE wire shape stays exactly what the UI expects.
4. We accumulate the assistant text by parsing ``event: answer``
   chunks (best-effort; failure to parse falls back to "").
5. After the generator exhausts (or raises), we append the
   ``assistant_message`` event, fire ``on_run_end`` (and
   ``on_run_error`` if applicable), record metrics + close the span.

Critical design:
- **Pass-through is sacred.** Every chunk from the inner generator
  yields exactly once. We do NOT re-encode, re-batch, or re-order.
  Anything else and the SSE keepalive + presenter contract breaks.
- **Telemetry never breaks the stream.** Log appends, metric writes,
  hook fires, span ends — every one wrapped to swallow exceptions
  at debug. A bad processor cannot crash the user's chat.
- **Feature-gated.** ``enable_native_stream_dispatch`` controls
  whether the coordinator routes through this wrapper. Default off
  so existing UI flow stays untouched until the team flips the flag.

The same pattern as Phase 19 ``native_chat_dispatch``, just adapted
to async generators.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import AsyncGenerator, Optional

from app.engine.multi_agent.runtime_flow_doctor import build_runtime_flow_doctor_report
from app.engine.runtime.lifecycle import HookPoint, get_lifecycle
from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text
from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms
from app.engine.runtime.session_event_log import (
    SessionEventLog,
    get_session_event_log,
)
from app.engine.runtime.tracing import span as trace_span

logger = logging.getLogger(__name__)


# SSE chunk pattern — `event: <name>\ndata: <json>\n\n` style.
_EVENT_LINE = re.compile(r"^event:\s*(\S+)", re.MULTILINE)
_DATA_LINE = re.compile(r"^data:\s*(.+)$", re.MULTILINE)


def _extract_answer_token(chunk: str) -> Optional[str]:
    """Pull the assistant-token text out of an ``event: answer`` SSE chunk.

    Returns None for any chunk that is not an answer event or cannot be
    parsed. Non-fatal — accumulation is best-effort and feeds the
    ``assistant_message`` payload only.
    """
    if not isinstance(chunk, str):
        return None
    event_match = _EVENT_LINE.search(chunk)
    if event_match is None or event_match.group(1) != "answer":
        return None
    data_match = _DATA_LINE.search(chunk)
    if data_match is None:
        return None
    raw = data_match.group(1).strip()
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    content = body.get("content") if isinstance(body, dict) else None
    if isinstance(content, str) and content:
        return content
    return None


def _extract_runtime_flow_ledger(chunk: str) -> Optional[dict]:
    """Pull a sanitized RuntimeFlowLedger payload out of an SSE chunk."""

    if not isinstance(chunk, str):
        return None
    event_match = _EVENT_LINE.search(chunk)
    if event_match is None or event_match.group(1) not in {"metadata", "done"}:
        return None
    data_match = _DATA_LINE.search(chunk)
    if data_match is None:
        return None
    raw = data_match.group(1).strip()
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    ledger = body.get("runtime_flow_ledger")
    return ledger if isinstance(ledger, dict) else None


def _emit_finalization_metric(
    *,
    stage: str,
    status: str,
    stream_status: str,
    transport: str = "stream/v3",
) -> None:
    inc_counter(
        "runtime.native_stream_dispatch.finalization",
        labels={
            "stage": str(stage or "unknown"),
            "status": str(status or "unknown"),
            "stream_status": str(stream_status or "unknown"),
            "transport": str(transport or "unknown"),
        },
    )


async def _append_assistant_message_event(
    log: SessionEventLog,
    *,
    session_id: str,
    org_id: Optional[str],
    payload: dict,
    stream_status: str,
) -> bool:
    try:
        await log.append(
            session_id=session_id,
            event_type="assistant_message",
            payload=payload,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_finalization_metric(
            stage="assistant_message_append",
            status="error",
            stream_status=stream_status,
        )
        logger.debug(
            "[native_stream_dispatch] assistant_message append skipped: %s",
            exc,
        )
        return False
    _emit_finalization_metric(
        stage="assistant_message_append",
        status="success",
        stream_status=stream_status,
    )
    return True


async def _append_runtime_flow_ledger_event(
    log: SessionEventLog,
    *,
    session_id: str,
    org_id: Optional[str],
    ledger: dict,
    status: str,
    duration_ms: int,
) -> None:
    _emit_runtime_flow_ledger_metrics(
        ledger,
        status=status,
        transport="stream/v3",
    )
    try:
        await log.append(
            session_id=session_id,
            event_type="runtime_flow_ledger",
            payload={
                "runtime_flow_ledger": ledger,
                "status": status,
                "duration_ms": duration_ms,
                "transport": "stream/v3",
            },
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_finalization_metric(
            stage="runtime_flow_ledger_append",
            status="error",
            stream_status=status,
        )
        logger.debug(
            "[native_stream_dispatch] runtime_flow_ledger append skipped: %s",
            exc,
        )
        return
    _emit_finalization_metric(
        stage="runtime_flow_ledger_append",
        status="success",
        stream_status=status,
    )


def _emit_runtime_flow_ledger_metrics(
    ledger: dict,
    *,
    status: str,
    transport: str,
) -> None:
    """Forward aggregate runtime-flow doctor alert codes to metrics."""

    try:
        report = build_runtime_flow_doctor_report([ledger])
        doctor_status = str(report.get("status") or "unknown")
        inc_counter(
            "runtime.runtime_flow_ledger.events",
            labels={
                "status": str(status or "unknown"),
                "doctor_status": doctor_status,
                "transport": str(transport or "unknown"),
            },
        )
        for alert in report.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            code = str(alert.get("code") or "unknown")[:96]
            severity = str(alert.get("severity") or "warning")[:32]
            count = alert.get("count")
            by = count if type(count) is int and count > 0 else 1
            inc_counter(
                "runtime.runtime_flow_ledger.alerts",
                labels={
                    "code": code,
                    "severity": severity,
                    "status": str(status or "unknown"),
                    "transport": str(transport or "unknown"),
                },
                by=by,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[native_stream_dispatch] runtime_flow_ledger metrics skipped: %s",
            exc,
        )


async def native_stream_dispatch(
    chat_request,
    inner: AsyncGenerator[str, None],
    *,
    event_log: Optional[SessionEventLog] = None,
) -> AsyncGenerator[str, None]:
    """Wrap an SSE chat generator with durable + instrumented dispatch.

    The contract mirrors ``native_chat_dispatch`` (Phase 19) for the
    streaming path: same event types in the durable log, same metric
    names (``runtime.native_stream_dispatch.*``), same lifecycle hooks
    fired in the same order.
    """
    log = event_log or get_session_event_log()
    session_id = (
        getattr(chat_request, "session_id", None)
        or f"native-stream::{getattr(chat_request, 'user_id', 'unknown')}"
    )
    org_id = getattr(chat_request, "organization_id", None)
    user_message_text = getattr(chat_request, "message", "") or ""
    lifecycle = get_lifecycle()

    # ── pre-stream side effects ──

    await lifecycle.fire(
        HookPoint.ON_RUN_START,
        {
            "session_id": session_id,
            "org_id": org_id,
            "user_id": getattr(chat_request, "user_id", None),
            "user_message": user_message_text,
            "transport": "stream/v3",
        },
    )
    await log.append(
        session_id=session_id,
        event_type="user_message",
        payload={
            "text": user_message_text,
            "user_id": getattr(chat_request, "user_id", None),
            "role": (
                getattr(getattr(chat_request, "role", None), "value", None)
                or str(getattr(chat_request, "role", ""))
            ),
            "domain_id": getattr(chat_request, "domain_id", None),
            "transport": "stream/v3",
        },
        org_id=org_id,
    )

    started = time.monotonic()
    accumulated_text_parts: list[str] = []
    latest_runtime_flow_ledger: Optional[dict] = None
    error_str: Optional[str] = None

    span_ctx = trace_span(
        "native_stream_dispatch.run",
        attributes={
            "session_id": session_id,
            "org_id": org_id,
            "user_id": getattr(chat_request, "user_id", None),
            "transport": "stream/v3",
        },
    )

    try:
        with span_ctx:
            try:
                async for chunk in inner:
                    # Pass through every chunk EXACTLY. Telemetry never
                    # mutates the byte stream the UI consumes.
                    token = _extract_answer_token(chunk)
                    if token:
                        accumulated_text_parts.append(token)
                    runtime_flow_ledger = _extract_runtime_flow_ledger(chunk)
                    if runtime_flow_ledger is not None:
                        latest_runtime_flow_ledger = runtime_flow_ledger
                    yield chunk
            except Exception as exc:  # noqa: BLE001
                error_str = redact_runtime_secret_text(
                    f"{type(exc).__name__}: {exc}"
                )
                raise
    except Exception:
        # Span context already recorded status=error before re-raise;
        # we still need to drive the durable log + metric writes below
        # so wake() / SLO alerts see the closure.
        pass

    duration_ms = int((time.monotonic() - started) * 1000)
    accumulated_text = "".join(accumulated_text_parts)

    if error_str is None:
        await _append_assistant_message_event(
            log,
            session_id=session_id,
            payload={
                "text": accumulated_text,
                "status": "success",
                "duration_ms": duration_ms,
                "transport": "stream/v3",
            },
            org_id=org_id,
            stream_status="success",
        )
        inc_counter(
            "runtime.native_stream_dispatch.runs",
            labels={"status": "success"},
        )
        record_latency_ms(
            "runtime.native_stream_dispatch.duration_ms",
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
                "transport": "stream/v3",
            },
        )
        if latest_runtime_flow_ledger is not None:
            await _append_runtime_flow_ledger_event(
                log,
                session_id=session_id,
                org_id=org_id,
                ledger=latest_runtime_flow_ledger,
                status="success",
                duration_ms=duration_ms,
            )
        return

    # Error path — same shape as the success path, but status=error.
    await _append_assistant_message_event(
        log,
        session_id=session_id,
        payload={
            "text": accumulated_text,
            "status": "error",
            "error": error_str,
            "duration_ms": duration_ms,
            "transport": "stream/v3",
        },
        org_id=org_id,
        stream_status="error",
    )
    inc_counter(
        "runtime.native_stream_dispatch.runs", labels={"status": "error"}
    )
    record_latency_ms(
        "runtime.native_stream_dispatch.duration_ms",
        float(duration_ms),
        labels={"status": "error"},
    )
    await lifecycle.fire(
        HookPoint.ON_RUN_ERROR,
        {
            "session_id": session_id,
            "org_id": org_id,
            "duration_ms": duration_ms,
            "error": error_str,
            "transport": "stream/v3",
        },
    )
    await lifecycle.fire(
        HookPoint.ON_RUN_END,
        {
            "session_id": session_id,
            "org_id": org_id,
            "duration_ms": duration_ms,
            "status": "error",
            "transport": "stream/v3",
        },
    )
    if latest_runtime_flow_ledger is not None:
        await _append_runtime_flow_ledger_event(
            log,
            session_id=session_id,
            org_id=org_id,
            ledger=latest_runtime_flow_ledger,
            status="error",
            duration_ms=duration_ms,
        )
    # Re-raise the original exception so the SSE caller's error handler
    # still kicks in (e.g. ``emit_internal_error_sse_events``).
    raise RuntimeError(error_str)


__all__ = [
    "native_stream_dispatch",
    "_extract_answer_token",
    "_extract_runtime_flow_ledger",
]
