"""Phase 19 native chat dispatch — Runtime Migration #207.

Locks the contract:
- ``user_message`` event before the inner call.
- ``assistant_message`` event after, with text + tool_calls + duration.
- One ``tool_result`` event per declared tool call.
- Metrics recorded with status label (success / error).
- Exception path still emits an ``assistant_message`` (status=error)
  so wake() / replay see a clean closure.
- org_id propagates to every event.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.engine.runtime.lifecycle import get_lifecycle
from app.engine.runtime.native_dispatch import (
    _serialise_tool_calls,
    native_chat_dispatch,
)
from app.engine.runtime.session_event_log import InMemorySessionEventLog


@pytest.fixture(autouse=True)
def reset_metrics():
    rm._reset_for_tests()
    get_lifecycle().reset()
    yield
    rm._reset_for_tests()
    get_lifecycle().reset()


@pytest.fixture
def log() -> InMemorySessionEventLog:
    return InMemorySessionEventLog()


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


def _make_request(
    *,
    user_id: str = "user-1",
    session_id: str = "sess-1",
    message: str = "Chào Wiii",
    org_id: str = "org-A",
    role: str = "student",
    domain_id: str = "maritime",
):
    return SimpleNamespace(
        user_id=user_id,
        session_id=session_id,
        message=message,
        organization_id=org_id,
        role=SimpleNamespace(value=role),
        domain_id=domain_id,
    )


def _make_response(
    message: str = "Trả lời",
    metadata=None,
    agent_type: str = "rag",
):
    return SimpleNamespace(
        message=message,
        metadata=metadata or {"latency_ms": 100},
        agent_type=SimpleNamespace(value=agent_type),
    )


# ── _serialise_tool_calls ──

def test_serialise_tool_calls_prefers_tool_calls_shape():
    metadata = {
        "tool_calls": [{"id": "c1", "name": "search", "args": {"q": "x"}}],
        "tools_used": [{"name": "ignore"}],
    }
    out = _serialise_tool_calls(metadata)
    assert out == [{"id": "c1", "name": "search", "args": {"q": "x"}}]


def test_serialise_tool_calls_falls_back_to_tools_used():
    out = _serialise_tool_calls({"tools_used": [{"name": "search"}]})
    assert out == [{"name": "search"}]


def test_serialise_tool_calls_handles_non_dict_entries():
    out = _serialise_tool_calls({"tool_calls": ["raw-string"]})
    assert out == [{"raw": "raw-string"}]


def test_serialise_tool_calls_sanitizes_secret_args_and_json_results():
    out = _serialise_tool_calls(
        {
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "host_action",
                    "args": {
                        "message": "hello",
                        "access_token": "raw-access-token",
                    },
                    "result": (
                        '{"status":"ok","approval_token":"raw-approval-token",'
                        '"data":{"safe_id":"post-1","provider_payload":{"id":"raw"}}}'
                    ),
                }
            ]
        }
    )

    assert out[0]["args"]["message"] == "hello"
    assert out[0]["result"]["status"] == "ok"
    assert out[0]["result"]["data"]["safe_id"] == "post-1"
    serialized = str(out)
    assert "raw-access-token" not in serialized
    assert "raw-approval-token" not in serialized
    assert "provider_payload" not in serialized


def test_serialise_tool_calls_returns_empty_for_no_metadata():
    assert _serialise_tool_calls(None) == []
    assert _serialise_tool_calls({}) == []
    assert _serialise_tool_calls({"tool_calls": []}) == []


# ── happy path ──

async def test_native_dispatch_logs_user_then_assistant_event(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=_make_response("Câu trả lời"))
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        request = _make_request()
        result = await native_chat_dispatch(request, event_log=log)

    assert result.message == "Câu trả lời"
    events = await log.get_events(session_id="sess-1")
    assert [e.event_type for e in events] == ["user_message", "assistant_message"]
    user_payload = events[0].payload
    assert user_payload["text"] == "Chào Wiii"
    assert user_payload["user_id_hash"].startswith("sha256:")
    assert user_payload["role"] == "student"
    assert user_payload["domain_id"] == "maritime"
    assistant_payload = events[1].payload
    assert assistant_payload["text"] == "Câu trả lời"
    assert assistant_payload["status"] == "success"
    assert assistant_payload["agent_type"] == "rag"
    assert assistant_payload["duration_ms"] >= 0


async def test_native_dispatch_emits_tool_result_per_declared_call(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(
            return_value=_make_response(
                "answered",
                metadata={
                    "tool_calls": [
                        {"id": "c1", "name": "search", "result": "doc-A"},
                        {"id": "c2", "name": "lookup", "result": "doc-B"},
                    ]
                },
            )
        )
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(_make_request(), event_log=log)

    events = await log.get_events(session_id="sess-1")
    types = [e.event_type for e in events]
    assert types == [
        "user_message",
        "assistant_message",
        "tool_result",
        "tool_result",
    ]
    assert events[2].payload["tool_call_id"] == "c1"
    assert events[2].payload["content"] == "doc-A"
    assert events[3].payload["tool_call_id"] == "c2"


async def test_native_dispatch_propagates_org_id_to_every_event(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(
            return_value=_make_response(
                metadata={"tool_calls": [{"id": "c1", "name": "x", "result": "y"}]}
            )
        )
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(
            _make_request(org_id="org-A"), event_log=log
        )

    org_events = await log.get_events(session_id="sess-1", org_id="org-A")
    assert len(org_events) == 3  # user + assistant + tool_result
    assert all(e.org_id == "org-A" for e in org_events)
    other_org_events = await log.get_events(
        session_id="sess-1", org_id="other-org"
    )
    assert other_org_events == []


# ── error path ──

async def test_native_dispatch_emits_assistant_error_on_inner_exception(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(side_effect=RuntimeError("provider down"))
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError, match="provider down"):
            await native_chat_dispatch(_make_request(), event_log=log)

    events = await log.get_events(session_id="sess-1")
    assert [e.event_type for e in events] == [
        "user_message",
        "assistant_message",
    ]
    assistant = events[1].payload
    assert assistant["status"] == "error"
    assert "provider down" in assistant["error"]
    assert assistant["text"] == ""


async def test_native_dispatch_redacts_secret_text_in_error_event(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(
            side_effect=RuntimeError(
                "provider failed Bearer raw-bearer-token-123 "
                "access_token=raw-access-token-inline"
            )
        )
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError):
            await native_chat_dispatch(_make_request(), event_log=log)

    events = await log.get_events(session_id="sess-1")
    assistant = events[1].payload
    serialized = str(assistant)
    assert "<redacted-secret>" in assistant["error"]
    assert "raw-bearer-token-123" not in serialized
    assert "raw-access-token-inline" not in serialized
    assert "access_token" not in serialized


# ── metrics ──

async def test_native_dispatch_records_success_metric(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=_make_response())
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(_make_request(), event_log=log)

    snap = rm.snapshot()
    assert (
        snap["counters"]["runtime.native_dispatch.runs"][
            (("status", "success"),)
        ]
        == 1
    )
    durations = snap["histograms"]["runtime.native_dispatch.duration_ms"][
        (("status", "success"),)
    ]
    assert len(durations) == 1
    assert durations[0] >= 0
    finalization_labels = (
        ("run_status", "success"),
        ("stage", "assistant_message_append"),
        ("status", "success"),
        ("transport", "chat"),
    )
    assert (
        snap["counters"]["runtime.native_dispatch.finalization"][
            finalization_labels
        ]
        == 1
    )


async def test_native_dispatch_records_error_metric(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(side_effect=RuntimeError("boom"))
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError):
            await native_chat_dispatch(_make_request(), event_log=log)

    snap = rm.snapshot()
    assert (
        snap["counters"]["runtime.native_dispatch.runs"][
            (("status", "error"),)
        ]
        == 1
    )
    finalization_labels = (
        ("run_status", "error"),
        ("stage", "assistant_message_append"),
        ("status", "success"),
        ("transport", "chat"),
    )
    assert (
        snap["counters"]["runtime.native_dispatch.finalization"][
            finalization_labels
        ]
        == 1
    )


async def test_native_dispatch_records_tool_result_finalization_metric(log):
    fake_service = SimpleNamespace(
        process_message=AsyncMock(
            return_value=_make_response(
                metadata={"tool_calls": [{"id": "c1", "name": "x", "result": "y"}]}
            )
        )
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(_make_request(), event_log=log)

    snap = rm.snapshot()
    labels = (
        ("run_status", "success"),
        ("stage", "tool_result_append"),
        ("status", "success"),
        ("transport", "chat"),
    )
    assert snap["counters"]["runtime.native_dispatch.finalization"][labels] == 1


async def test_native_dispatch_finalization_append_failure_records_metric():
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=_make_response("done"))
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError, match="session event log unavailable"):
            await native_chat_dispatch(
                _make_request(),
                event_log=FailingAssistantAppendLog(),
            )

    snap = rm.snapshot()
    labels = (
        ("run_status", "success"),
        ("stage", "assistant_message_append"),
        ("status", "error"),
        ("transport", "chat"),
    )
    assert snap["counters"]["runtime.native_dispatch.finalization"][labels] == 1


# ── session_id fallback ──

async def test_native_dispatch_falls_back_to_native_user_when_no_session_id(
    log,
):
    request = _make_request(session_id=None)
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=_make_response())
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        await native_chat_dispatch(request, event_log=log)

    events = await log.get_events(session_id="native::user-1")
    assert len(events) == 2
