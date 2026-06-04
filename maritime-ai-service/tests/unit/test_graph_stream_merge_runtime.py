import asyncio
from unittest.mock import patch

import pytest

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.graph_stream_merge_runtime import (
    drain_pending_bus_events_impl,
    forward_bus_events_impl,
    forward_graph_events_impl,
    handle_bus_message_impl,
)


class _ExplodingGraph:
    def __init__(self, exc):
        self._exc = exc

    async def astream(self, *_args, **_kwargs):
        raise self._exc
        yield  # pragma: no cover


class _ExplodingRunner:
    def __init__(self, exc):
        self._exc = exc

    async def run_streaming(self, *_args, **_kwargs):
        raise self._exc


@pytest.mark.asyncio
async def test_forward_graph_events_preserves_provider_unavailable():
    merged_queue: asyncio.Queue = asyncio.Queue()
    exc = ProviderUnavailableError(
        provider="google",
        reason_code="rate_limit",
        message="Provider tam thoi bi gioi han.",
    )

    with patch(
        "app.engine.multi_agent.runner.get_wiii_runner",
        return_value=_ExplodingRunner(exc),
    ):
        await forward_graph_events_impl(
            initial_state={},
            merged_queue=merged_queue,
        )

    msg_type, payload = await merged_queue.get()
    assert msg_type == "provider_unavailable"
    assert payload is exc

    done_type, done_payload = await merged_queue.get()
    assert done_type == "graph_done"
    assert done_payload is None


async def _identity_event(payload):
    return payload


async def _unused_event(*_args, **_kwargs):
    raise AssertionError("unexpected event factory call")


@pytest.mark.asyncio
async def test_forward_bus_events_sanitizes_payload_before_merge():
    event_queue: asyncio.Queue = asyncio.Queue()
    merged_queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    event_queue.put_nowait(
        {
            "type": "tool_call",
            "node": "direct",
            "connection_ref": "vault_raw_ref",
            "content": {
                "name": "external_tool",
                "id": "tc_1",
                "args": {
                    "access_token": "raw-access-token-123456",
                    "query": "Bearer raw-query-token-12345678",
                },
            },
        }
    )
    event_queue.put_nowait(sentinel)

    await forward_bus_events_impl(
        event_queue=event_queue,
        merged_queue=merged_queue,
        sentinel=sentinel,
        bus_streamed_nodes=set(),
        bus_answer_nodes=set(),
        lifecycle_state={},
    )

    msg_type, payload = await merged_queue.get()
    serialized = str(payload)

    assert msg_type == "bus"
    assert payload["content"]["args"]["query"] == "Bearer <redacted-secret>"
    assert "access_token" not in payload["content"]["args"]
    assert "connection_ref" not in payload
    assert "raw-access-token" not in serialized
    assert "raw-query-token" not in serialized
    assert "vault_raw_ref" not in serialized


@pytest.mark.asyncio
async def test_handle_bus_message_sanitizes_payload_before_conversion():
    events, *_ = await handle_bus_message_impl(
        payload={
            "type": "tool_result",
            "node": "direct",
            "content": {
                "name": "external_tool",
                "id": "tc_1",
                "result": '{"ok": true, "access_token": "raw-result-token-123456"}',
            },
        },
        settings_enable_soul_emotion=False,
        soul_buffer=None,
        soul_emotion_emitted=False,
        supervisor_status_emitted=False,
        supervisor_thinking_open=False,
        convert_bus_event=_identity_event,
        create_emotion_event=_unused_event,
        create_answer_event=_unused_event,
    )

    serialized = str(events)

    assert events[0]["content"]["result"]["ok"] is True
    assert "access_token" not in events[0]["content"]["result"]
    assert "raw-result-token" not in serialized


@pytest.mark.asyncio
async def test_drain_pending_bus_events_sanitizes_residual_payloads():
    merged_queue: asyncio.Queue = asyncio.Queue()
    event_queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    merged_queue.put_nowait(
        (
            "bus",
            {
                "type": "tool_result",
                "node": "direct",
                "content": {
                    "name": "external_tool",
                    "id": "tc_1",
                    "result": '{"provider_payload": {"token": "raw-provider-token-123456"}, "ok": true}',
                },
            },
        )
    )
    event_queue.put_nowait(
        {
            "type": "answer_delta",
            "node": "direct",
            "content": "Bearer raw-answer-token-12345678",
        }
    )

    events, answer_emitted = await drain_pending_bus_events_impl(
        merged_queue=merged_queue,
        event_queue=event_queue,
        convert_bus_event=_identity_event,
        answer_emitted=False,
        sentinel=sentinel,
    )

    serialized = str(events)

    assert answer_emitted is True
    assert events[0]["content"]["result"]["ok"] is True
    assert "provider_payload" not in events[0]["content"]["result"]
    assert events[1]["content"] == "Bearer <redacted-secret>"
    assert "raw-provider-token" not in serialized
    assert "raw-answer-token" not in serialized
