"""Phase 30 native stream dispatch — Runtime Migration #207.

Locks the contract:
- All chunks pass through unchanged (SSE wire shape preserved).
- user_message event recorded BEFORE first chunk.
- assistant_message event recorded AFTER stream exhausts, with
  accumulated answer text.
- Status=success on clean exit, status=error on inner generator raise.
- Metrics + lifecycle hooks fire in the right order.
- _extract_answer_token parses ``event: answer`` SSE chunks.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import AsyncGenerator

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.engine.runtime.lifecycle import HookPoint, get_lifecycle
from app.engine.runtime.native_stream_dispatch import (
    _extract_answer_token,
    _extract_runtime_flow_ledger,
    native_stream_dispatch,
)
from app.engine.runtime.session_event_log import InMemorySessionEventLog


@pytest.fixture(autouse=True)
def reset_state():
    rm._reset_for_tests()
    get_lifecycle().reset()
    yield
    rm._reset_for_tests()
    get_lifecycle().reset()


def _make_request(
    *, session_id="stream-1", user_id="user-1", message="hello", org_id="org-A"
):
    return SimpleNamespace(
        user_id=user_id,
        session_id=session_id,
        message=message,
        organization_id=org_id,
        role=SimpleNamespace(value="student"),
        domain_id="maritime",
    )


async def _make_sse_generator(chunks: list[str]) -> AsyncGenerator[str, None]:
    for chunk in chunks:
        yield chunk


class FailingAssistantAppendLog(InMemorySessionEventLog):
    async def append(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict,
        org_id: str | None = None,
    ):
        if event_type == "assistant_message":
            raise RuntimeError("session event log unavailable")
        return await super().append(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            org_id=org_id,
        )


# ── _extract_answer_token ──

def test_extract_answer_token_parses_answer_event():
    chunk = 'event: answer\ndata: {"content": "hello"}\n\n'
    assert _extract_answer_token(chunk) == "hello"


def test_extract_answer_token_returns_none_for_other_events():
    assert _extract_answer_token('event: status\ndata: {"step": "x"}\n\n') is None
    assert _extract_answer_token('event: done\ndata: {}\n\n') is None
    assert _extract_answer_token('event: sources\ndata: {"sources": []}\n\n') is None


def test_extract_answer_token_handles_malformed_json():
    assert _extract_answer_token('event: answer\ndata: not-json\n\n') is None


def test_extract_answer_token_handles_missing_content():
    assert _extract_answer_token('event: answer\ndata: {"foo": "bar"}\n\n') is None


def test_extract_answer_token_handles_empty_content():
    assert _extract_answer_token('event: answer\ndata: {"content": ""}\n\n') is None


def test_extract_answer_token_returns_none_for_non_string():
    assert _extract_answer_token(None) is None  # type: ignore[arg-type]
    assert _extract_answer_token(12345) is None  # type: ignore[arg-type]


def test_extract_runtime_flow_ledger_parses_terminal_sse_event():
    ledger = {"schema_version": "wiii.runtime_flow_ledger.v1"}
    chunk = (
        "event: done\n"
        f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n"
    )

    assert _extract_runtime_flow_ledger(chunk) == ledger


def test_extract_runtime_flow_ledger_ignores_non_terminal_events():
    ledger = {"schema_version": "wiii.runtime_flow_ledger.v1"}
    chunk = (
        "event: answer\n"
        f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n"
    )

    assert _extract_runtime_flow_ledger(chunk) is None


# ── pass-through ──

async def test_all_chunks_pass_through_unchanged():
    log = InMemorySessionEventLog()
    chunks = [
        "retry: 3000\n\n",
        "event: status\ndata: {\"step\": \"prep\"}\n\n",
        'event: answer\ndata: {"content": "hello"}\n\n',
        'event: answer\ndata: {"content": " world"}\n\n',
        "event: done\ndata: {}\n\n",
    ]
    inner = _make_sse_generator(chunks)
    wrapped = native_stream_dispatch(_make_request(), inner, event_log=log)
    received = [c async for c in wrapped]
    assert received == chunks  # exact pass-through, no re-encoding


# ── durable log ──

async def test_user_message_event_recorded_before_assistant():
    log = InMemorySessionEventLog()
    chunks = ['event: answer\ndata: {"content": "hi"}\n\n', "event: done\ndata: {}\n\n"]
    wrapped = native_stream_dispatch(
        _make_request(message="trigger"),
        _make_sse_generator(chunks),
        event_log=log,
    )
    async for _ in wrapped:
        pass
    events = await log.get_events(session_id="stream-1")
    assert [e.event_type for e in events] == [
        "user_message",
        "assistant_message",
    ]
    assert events[0].payload["text"] == "trigger"
    assert events[0].payload["transport"] == "stream/v3"


async def test_assistant_text_accumulated_from_answer_chunks():
    log = InMemorySessionEventLog()
    chunks = [
        "event: status\ndata: {\"step\": \"prep\"}\n\n",
        'event: answer\ndata: {"content": "Hello"}\n\n',
        'event: answer\ndata: {"content": " "}\n\n',
        'event: answer\ndata: {"content": "Wiii"}\n\n',
        "event: done\ndata: {}\n\n",
    ]
    wrapped = native_stream_dispatch(
        _make_request(), _make_sse_generator(chunks), event_log=log
    )
    async for _ in wrapped:
        pass
    events = await log.get_events(session_id="stream-1")
    assistant = events[1].payload
    assert assistant["text"] == "Hello Wiii"
    assert assistant["status"] == "success"
    assert assistant["transport"] == "stream/v3"


async def test_org_id_propagated_to_both_events():
    log = InMemorySessionEventLog()
    chunks = ['event: answer\ndata: {"content": "x"}\n\n']
    wrapped = native_stream_dispatch(
        _make_request(org_id="org-B"),
        _make_sse_generator(chunks),
        event_log=log,
    )
    async for _ in wrapped:
        pass
    events_b = await log.get_events(session_id="stream-1", org_id="org-B")
    assert len(events_b) == 2
    events_other = await log.get_events(session_id="stream-1", org_id="org-other")
    assert events_other == []


async def test_runtime_flow_ledger_event_recorded_when_present():
    log = InMemorySessionEventLog()
    ledger = {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "route": {"lane": "casual_chat"},
        "stream": {"done_seen": True, "event_counts": {"done": 1}},
    }
    chunks = [
        'event: answer\ndata: {"content": "ok"}\n\n',
        "event: done\n"
        f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n",
    ]
    wrapped = native_stream_dispatch(
        _make_request(), _make_sse_generator(chunks), event_log=log
    )
    received = [chunk async for chunk in wrapped]

    assert received == chunks
    events = await log.get_events(session_id="stream-1")
    assert [event.event_type for event in events] == [
        "user_message",
        "assistant_message",
        "runtime_flow_ledger",
    ]
    ledger_event = events[2].payload
    assert ledger_event["runtime_flow_ledger"]["route"]["lane"] == "casual_chat"
    assert ledger_event["status"] == "success"
    assert ledger_event["transport"] == "stream/v3"


# ── error path ──

async def test_inner_generator_raise_records_error_assistant_event():
    log = InMemorySessionEventLog()

    async def bad_gen() -> AsyncGenerator[str, None]:
        yield 'event: answer\ndata: {"content": "partial"}\n\n'
        raise RuntimeError("provider hung up")

    wrapped = native_stream_dispatch(_make_request(), bad_gen(), event_log=log)
    received = []
    with pytest.raises(RuntimeError, match="provider hung up"):
        async for chunk in wrapped:
            received.append(chunk)
    # First chunk passed through before the raise.
    assert received == ['event: answer\ndata: {"content": "partial"}\n\n']
    events = await log.get_events(session_id="stream-1")
    assert [e.event_type for e in events] == [
        "user_message",
        "assistant_message",
    ]
    assistant = events[1].payload
    assert assistant["status"] == "error"
    assert "provider hung up" in assistant["error"]
    # Even on error, the partially-accumulated text is preserved.
    assert assistant["text"] == "partial"


async def test_runtime_flow_ledger_alerts_forward_to_metrics():
    log = InMemorySessionEventLog()
    ledger = {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "request": {"request_id": ""},
        "route": {"lane": "external_app_action"},
        "context": {
            "context_provenance": {
                "warnings": [],
                "privacy": {"raw_content_included": False},
            }
        },
        "tools": {"observed": [], "suppressed": []},
        "stream": {
            "done_seen": True,
            "metadata_seen": True,
            "event_counts": {"done": 1},
        },
        "finalization": {"status": "saved"},
    }
    chunks = [
        'event: answer\ndata: {"content": "ok"}\n\n',
        "event: done\n"
        f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n",
    ]
    wrapped = native_stream_dispatch(
        _make_request(),
        _make_sse_generator(chunks),
        event_log=log,
    )
    async for _ in wrapped:
        pass

    snap = rm.snapshot()
    event_labels = (
        ("doctor_status", "degraded"),
        ("status", "success"),
        ("transport", "stream/v3"),
    )
    alert_labels = (
        ("code", "missing_request_id"),
        ("severity", "warning"),
        ("status", "success"),
        ("transport", "stream/v3"),
    )
    assert snap["counters"]["runtime.runtime_flow_ledger.events"][event_labels] == 1
    assert snap["counters"]["runtime.runtime_flow_ledger.alerts"][alert_labels] == 1
    ledger_append_labels = (
        ("stage", "runtime_flow_ledger_append"),
        ("status", "success"),
        ("stream_status", "success"),
        ("transport", "stream/v3"),
    )
    assert (
        snap["counters"]["runtime.native_stream_dispatch.finalization"][
            ledger_append_labels
        ]
        == 1
    )


async def test_runtime_flow_ledger_event_recorded_on_error_when_seen():
    log = InMemorySessionEventLog()
    ledger = {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "route": {"lane": "provider_stream_interrupted"},
        "stream": {"metadata_seen": True, "done_seen": False},
    }

    async def bad_gen() -> AsyncGenerator[str, None]:
        yield (
            "event: metadata\n"
            f"data: {json.dumps({'runtime_flow_ledger': ledger})}\n\n"
        )
        raise RuntimeError("provider hung up")

    wrapped = native_stream_dispatch(_make_request(), bad_gen(), event_log=log)
    with pytest.raises(RuntimeError, match="provider hung up"):
        async for _ in wrapped:
            pass

    events = await log.get_events(session_id="stream-1")
    assert [event.event_type for event in events] == [
        "user_message",
        "assistant_message",
        "runtime_flow_ledger",
    ]
    ledger_event = events[2].payload
    assert ledger_event["status"] == "error"
    assert (
        ledger_event["runtime_flow_ledger"]["route"]["lane"]
        == "provider_stream_interrupted"
    )


async def test_inner_generator_error_redacts_secret_text_before_reraise():
    log = InMemorySessionEventLog()

    async def bad_gen() -> AsyncGenerator[str, None]:
        yield 'event: answer\ndata: {"content": "partial"}\n\n'
        raise RuntimeError(
            "provider failed Bearer raw-bearer-token-123 "
            "api_key=raw-api-key-inline"
        )

    wrapped = native_stream_dispatch(_make_request(), bad_gen(), event_log=log)
    with pytest.raises(RuntimeError) as exc_info:
        async for _ in wrapped:
            pass

    raised = str(exc_info.value)
    assert "<redacted-secret>" in raised
    assert "raw-bearer-token-123" not in raised
    assert "raw-api-key-inline" not in raised
    assert "api_key" not in raised
    events = await log.get_events(session_id="stream-1")
    assistant = events[1].payload
    serialized = str(assistant)
    assert "<redacted-secret>" in assistant["error"]
    assert "raw-bearer-token-123" not in serialized
    assert "raw-api-key-inline" not in serialized


# ── metrics ──

async def test_success_run_records_metrics():
    log = InMemorySessionEventLog()
    chunks = ['event: answer\ndata: {"content": "ok"}\n\n']
    wrapped = native_stream_dispatch(
        _make_request(), _make_sse_generator(chunks), event_log=log
    )
    async for _ in wrapped:
        pass
    snap = rm.snapshot()
    assert (
        snap["counters"]["runtime.native_stream_dispatch.runs"][
            (("status", "success"),)
        ]
        == 1
    )
    durations = snap["histograms"][
        "runtime.native_stream_dispatch.duration_ms"
    ][(("status", "success"),)]
    assert len(durations) == 1
    assert durations[0] >= 0
    finalization_labels = (
        ("stage", "assistant_message_append"),
        ("status", "success"),
        ("stream_status", "success"),
        ("transport", "stream/v3"),
    )
    assert (
        snap["counters"]["runtime.native_stream_dispatch.finalization"][
            finalization_labels
        ]
        == 1
    )


async def test_error_run_records_error_metric():
    log = InMemorySessionEventLog()

    async def bad_gen():
        if False:
            yield ""
        raise RuntimeError("boom")

    wrapped = native_stream_dispatch(_make_request(), bad_gen(), event_log=log)
    with pytest.raises(RuntimeError):
        async for _ in wrapped:
            pass
    snap = rm.snapshot()
    assert (
        snap["counters"]["runtime.native_stream_dispatch.runs"][
            (("status", "error"),)
        ]
        == 1
    )


async def test_finalization_append_failure_records_metric_without_breaking_stream():
    log = FailingAssistantAppendLog()
    chunks = ['event: answer\ndata: {"content": "ok"}\n\n']
    wrapped = native_stream_dispatch(
        _make_request(), _make_sse_generator(chunks), event_log=log
    )

    received = [chunk async for chunk in wrapped]

    assert received == chunks
    snap = rm.snapshot()
    finalization_labels = (
        ("stage", "assistant_message_append"),
        ("status", "error"),
        ("stream_status", "success"),
        ("transport", "stream/v3"),
    )
    assert (
        snap["counters"]["runtime.native_stream_dispatch.finalization"][
            finalization_labels
        ]
        == 1
    )
    assert (
        snap["counters"]["runtime.native_stream_dispatch.runs"][
            (("status", "success"),)
        ]
        == 1
    )


# ── lifecycle hooks ──

async def test_lifecycle_fires_run_start_then_run_end_on_success():
    log = InMemorySessionEventLog()
    captured: list[HookPoint] = []
    lc = get_lifecycle()

    async def on_start(payload):
        captured.append(HookPoint.ON_RUN_START)

    async def on_end(payload):
        captured.append(HookPoint.ON_RUN_END)

    lc.register(HookPoint.ON_RUN_START, on_start)
    lc.register(HookPoint.ON_RUN_END, on_end)

    chunks = ['event: answer\ndata: {"content": "ok"}\n\n']
    wrapped = native_stream_dispatch(
        _make_request(), _make_sse_generator(chunks), event_log=log
    )
    async for _ in wrapped:
        pass
    assert captured == [HookPoint.ON_RUN_START, HookPoint.ON_RUN_END]


async def test_lifecycle_fires_error_then_end_on_failure():
    log = InMemorySessionEventLog()
    captured: list[HookPoint] = []
    lc = get_lifecycle()

    async def record(point):
        async def hook(payload):
            captured.append(point)

        return hook

    lc.register(HookPoint.ON_RUN_START, await record(HookPoint.ON_RUN_START))
    lc.register(HookPoint.ON_RUN_ERROR, await record(HookPoint.ON_RUN_ERROR))
    lc.register(HookPoint.ON_RUN_END, await record(HookPoint.ON_RUN_END))

    async def bad_gen():
        if False:
            yield ""
        raise RuntimeError("nope")

    wrapped = native_stream_dispatch(_make_request(), bad_gen(), event_log=log)
    with pytest.raises(RuntimeError):
        async for _ in wrapped:
            pass
    assert captured == [
        HookPoint.ON_RUN_START,
        HookPoint.ON_RUN_ERROR,
        HookPoint.ON_RUN_END,
    ]


# ── session_id fallback ──

async def test_session_id_falls_back_when_request_omits_it():
    log = InMemorySessionEventLog()
    request = _make_request(session_id=None, user_id="bob")
    chunks = ['event: answer\ndata: {"content": "x"}\n\n']
    wrapped = native_stream_dispatch(
        request, _make_sse_generator(chunks), event_log=log
    )
    async for _ in wrapped:
        pass
    events = await log.get_events(session_id="native-stream::bob")
    assert len(events) == 2
