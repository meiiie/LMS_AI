import json
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.schemas import UserRole
from app.core.exceptions import (
    ProviderStreamInterruptedError,
    ProviderUnavailableError,
)
from app.engine.multi_agent.runtime_flow_ledger import RUNTIME_FLOW_LEDGER_SCHEMA_VERSION
from app.engine.multi_agent.runtime_contracts import WiiiStreamEvent, WiiiTurnRequest
from app.services.chat_runtime_lifecycle import (
    CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION,
    ChatLifecycleName,
)
from app.services.chat_orchestrator import AgentType
from app.services.chat_orchestrator import RequestScope
from app.services.output_processor import ProcessingResult
from app.services.chat_stream_coordinator import generate_stream_v3_events


def _make_request(**overrides):
    base = {
        "user_id": "user-1",
        "message": "Explain Rule 5",
        "role": UserRole.STUDENT,
        "show_previews": False,
        "preview_types": [],
        "preview_max_count": 0,
        "thinking_effort": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _event_payloads(chunks, event_name):
    payloads = []
    marker = f"event: {event_name}"
    for chunk in chunks:
        if marker not in chunk:
            continue
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line.removeprefix("data: ")))
                break
    return payloads


def _event_names(chunks):
    names = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("event: "):
                names.append(line.removeprefix("event: "))
                break
    return names


def _lifecycle_payloads(chunks):
    return _event_payloads(chunks, "chat_lifecycle")


def _runtime_flow_ledgers(chunks):
    return [
        payload["runtime_flow_ledger"]
        for payload in _event_payloads(chunks, "metadata")
        if isinstance(payload, dict) and "runtime_flow_ledger" in payload
    ]


def _all_runtime_flow_ledgers(chunks):
    ledgers = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            if isinstance(payload, dict) and "runtime_flow_ledger" in payload:
                ledgers.append(payload["runtime_flow_ledger"])
            break
    return ledgers


def _terminal_runtime_flow_ledger(chunks):
    ledgers = _all_runtime_flow_ledgers(chunks)
    assert ledgers
    return ledgers[-1]


def _runtime_flow_traces(chunks):
    return [
        payload["runtime_flow_trace"]
        for payload in _event_payloads(chunks, "metadata")
        if isinstance(payload, dict) and "runtime_flow_trace" in payload
    ]


def _post_turn_lifecycle_summary():
    return {
        "schema_version": "wiii.post_turn_lifecycle.v1",
        "status": "scheduled",
        "reason": "post_turn_background_tasks_scheduled",
        "semantic_memory_policy": "extract_facts",
        "background_tasks_scheduled": True,
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_blocked_sequence():
    orchestrator = MagicMock()
    orchestrator.prepare_turn = AsyncMock(
        return_value=SimpleNamespace(
            request_scope=RequestScope("org-1", "maritime"),
            session_id="session-1",
            validation=SimpleNamespace(
                blocked=True,
                blocked_response=SimpleNamespace(
                    message="Blocked",
                    metadata={"blocked": True},
                ),
            ),
            chat_context=None,
        )
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
    ):
        chunks.append(chunk)

    assert chunks[0] == "retry: 3000\n\n"
    events = _event_names(chunks)
    assert events[0] == "status"
    assert "chat_lifecycle" in events
    assert "answer" in events
    assert "metadata" in events
    assert events[-1] == "done"
    lifecycle_names = [
        payload["event_name"] for payload in _lifecycle_payloads(chunks)
    ]
    assert lifecycle_names[:4] == [
        ChatLifecycleName.CHAT_ACCEPTED,
        ChatLifecycleName.TURN_PREPARED,
        ChatLifecycleName.PATH_SELECTED,
        ChatLifecycleName.CAPABILITY_CHECKED,
    ]
    assert _lifecycle_payloads(chunks)[2]["lane"] == "blocked"
    ledgers = _runtime_flow_ledgers(chunks)
    assert ledgers
    assert ledgers[0]["schema_version"] == RUNTIME_FLOW_LEDGER_SCHEMA_VERSION
    generated_request_id = ledgers[0]["request"]["request_id"]
    assert generated_request_id.startswith("req_")
    lifecycle_request_ids = {
        payload["request_id"]
        for payload in _lifecycle_payloads(chunks)
        if payload.get("request_id")
    }
    assert lifecycle_request_ids == {generated_request_id}
    assert ledgers[0]["route"]["lane"] == "blocked"


@pytest.mark.asyncio
async def test_generate_stream_v3_events_finalizes_answer_after_stream():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(return_value=(
        SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
        )
    ))

    async def fake_stream_fn(**kwargs):
        assert kwargs["query"] == "Explain Rule 5"
        yield SimpleNamespace(type="answer", content="Hello ")
        yield SimpleNamespace(type="answer", content="world")
        yield SimpleNamespace(type="done", content={"processing_time": 0.5})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    assert any("event: answer" in chunk for chunk in chunks)
    assert any("event: done" in chunk for chunk in chunks)
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["response_text"]
        == "Hello world"
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs[
            "include_lms_insights"
        ]
        is True
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs[
            "transport_type"
        ]
        == "stream"
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs[
            "save_response_immediately"
        ]
        is False
    )
    finalize_request_id = orchestrator.finalize_response_turn.call_args.kwargs[
        "request_id"
    ]
    assert finalize_request_id.startswith("req_")


@pytest.mark.asyncio
async def test_generate_stream_v3_events_clears_facebook_cookie_scope(monkeypatch):
    """Stream request without a Facebook header must not inherit stale cookies."""
    from app.engine.search_platforms.facebook_context import (
        get_facebook_cookie,
        reset_facebook_cookie,
        set_facebook_cookie,
    )
    from app.services import chat_stream_coordinator as coordinator

    monkeypatch.setattr(coordinator.settings, "enable_facebook_cookie", True, raising=False)
    outer_token = set_facebook_cookie("outer=1")
    observed_cookie = None

    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(return_value=(
        SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
        )
    ))

    async def fake_stream_fn(**_kwargs):
        nonlocal observed_cookie
        observed_cookie = get_facebook_cookie()
        yield SimpleNamespace(type="done", content={"processing_time": 0.01})

    try:
        async for _chunk in generate_stream_v3_events(
            chat_request=_make_request(),
            request_headers={},
            background_save=MagicMock(),
            start_time=0.0,
            orchestrator=orchestrator,
            stream_fn=fake_stream_fn,
        ):
            pass

        assert observed_cookie == ""
        assert get_facebook_cookie() == "outer=1"
    finally:
        reset_facebook_cookie(outer_token)


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_typed_lifecycle_for_native_path():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "general"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="short chat",
            user_id="user-1",
            session_id="session-1",
            context={
                "conversation_history": "",
                "source_refs": [],
                "memories": [],
            },
            domain_id="general",
            thinking_effort=None,
            provider="nvidia",
            model="qwen/qwen3-next-80b-a3b-instruct",
        )
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Xin chào.")
        yield SimpleNamespace(type="metadata", content={"provider": "nvidia"})
        yield SimpleNamespace(type="done", content={"processing_time": 0.2})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(
            message="short chat",
            user_context={"host_context": {"surface": "desktop_chat"}},
        ),
        request_headers={"X-Request-ID": "req-lifecycle"},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    lifecycle = _lifecycle_payloads(chunks)
    names = [payload["event_name"] for payload in lifecycle]
    assert names == [
        ChatLifecycleName.CHAT_ACCEPTED,
        ChatLifecycleName.TURN_PREPARED,
        ChatLifecycleName.PATH_SELECTED,
        ChatLifecycleName.CAPABILITY_CHECKED,
        ChatLifecycleName.FINALIZATION_COMPLETED,
        ChatLifecycleName.CHAT_DONE,
    ]
    assert all(
        payload["schema_version"] == CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION
        for payload in lifecycle
    )
    path_payload = lifecycle[2]
    assert path_payload["lane"] == "native_turn"
    assert path_payload["reason"] == "multi_agent_stream"
    capability_payload = lifecycle[3]
    assert capability_payload["capabilities"]["host_surface"] == "desktop_chat"
    assert "host_action" in capability_payload["capabilities"]["suppressed_tools"]
    assert capability_payload["capabilities"]["observed_tools"] == []
    assert lifecycle[-1]["status"] == "complete"

    lifecycle_json = json.dumps(lifecycle, ensure_ascii=False)
    assert "short chat" not in lifecycle_json
    assert "user-1" not in lifecycle_json


@pytest.mark.asyncio
async def test_generate_stream_v3_events_does_not_finalize_interrupted_provider_stream():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider="nvidia",
            model="qwen/qwen3-next-80b-a3b-instruct",
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="À... vì mình thấy cậu đang")
        raise ProviderStreamInterruptedError(
            provider="nvidia",
            model="qwen/qwen3-next-80b-a3b-instruct",
            partial_chars=27,
            details="peer closed connection without sending complete message body",
        )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={"X-Request-ID": "req-provider-interrupt"},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "event: answer" in joined
    assert "À... vì mình thấy cậu đang" in joined
    assert "event: error" in joined
    error_payloads = _event_payloads(chunks, "error")
    assert len(error_payloads) == 1
    assert error_payloads[0]["type"] == "provider_stream_interrupted"
    assert error_payloads[0]["provider"] == "nvidia"
    assert error_payloads[0]["model"] == "qwen/qwen3-next-80b-a3b-instruct"
    assert error_payloads[0]["reason_code"] == "provider_stream_interrupted"
    assert error_payloads[0]["partial_chars"] == 27
    assert error_payloads[0]["recoverable"] is True
    assert "event: done" not in joined
    orchestrator.finalize_response_turn.assert_not_called()


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_flow_ledger_when_runtime_omits_metadata():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider="nvidia",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Hello")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={"X-Request-ID": "req-ledger-native"},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    ledgers = _runtime_flow_ledgers(chunks)
    assert ledgers
    ledger = ledgers[0]
    assert ledger["schema_version"] == RUNTIME_FLOW_LEDGER_SCHEMA_VERSION
    assert ledger["request"]["request_id"] == "req-ledger-native"
    assert ledger["request"]["session_id"] == "session-1"
    assert ledger["request"]["user_id_hash"].startswith("sha256:")
    assert ledger["route"]["lane"] == "native_turn"
    assert ledger["runtime"]["provider"] == "nvidia"
    assert ledger["runtime"]["model"] == "deepseek-ai/deepseek-v4-flash"
    assert ledger["stream"]["event_counts"]["answer"] == 1
    assert ledger["stream"]["metadata_seen"] is True
    assert ledger["finalization"]["status"] == "saved"
    assert ledger["finalization"]["post_turn_lifecycle"] == _post_turn_lifecycle_summary()
    assert "Explain Rule 5" not in json.dumps(ledger, ensure_ascii=False)


@pytest.mark.asyncio
async def test_generate_stream_v3_events_flow_ledger_omits_uploaded_document_body():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Create a lesson",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Lesson draft preview")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(
            message="Tao cho minh bai hoc",
            user_context={
                "host_context": {
                    "surface": "lms_course_editor",
                    "capabilities": ["lms", "host_action"],
                },
                "document_context": {
                    "attachments": [
                        {
                            "name": "private.docx",
                            "markdown": "SECRET DOCUMENT BODY ABOUT RULE 5",
                        }
                    ]
                },
            },
        ),
        request_headers={"X-Request-ID": "req-ledger-doc"},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    ledger = _runtime_flow_ledgers(chunks)[0]
    assert ledger["context"]["document_context_present"] is True
    assert ledger["context"]["uploaded_document_count"] == 1
    assert ledger["host_actions"]["preview_required"] is True
    terminal_ledger = _terminal_runtime_flow_ledger(chunks)
    assert (
        terminal_ledger["finalization"]["post_turn_lifecycle"]
        == _post_turn_lifecycle_summary()
    )
    ledger_json = json.dumps(ledger, ensure_ascii=False)
    assert "SECRET DOCUMENT BODY" not in ledger_json
    assert "Tao cho minh bai hoc" not in ledger_json
    wiii_connect_snapshots = [
        payload["capabilities"].get("wiii_connect")
        for payload in _lifecycle_payloads(chunks)
        if isinstance(payload.get("capabilities"), dict)
        and isinstance(payload["capabilities"].get("wiii_connect"), dict)
    ]
    assert wiii_connect_snapshots
    snapshot_json = json.dumps(wiii_connect_snapshots, ensure_ascii=False)
    assert "wiii_connect_snapshot.v0" in snapshot_json
    assert "document_corpus" in snapshot_json
    assert "SECRET DOCUMENT BODY" not in snapshot_json
    assert "private.docx" not in snapshot_json
    assert "Tao cho minh bai hoc" not in snapshot_json


@pytest.mark.asyncio
async def test_generate_stream_v3_events_bypasses_context_build_for_pointy_highlight():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        side_effect=AssertionError("pointy highlight should not build full context")
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    request = _make_request(
        message="Pointy hãy chỉ vào nút Gửi tin nhắn.",
        user_context=SimpleNamespace(
            host_context={
                "page": {
                    "metadata": {
                        "available_targets": [
                            {
                                "id": "chat-send-button",
                                "selector": '[data-wiii-id="chat-send-button"]',
                                "label": "Gửi tin nhắn",
                                "visible": True,
                                "click_safe": False,
                            }
                        ]
                    }
                }
            },
            page_context=None,
            host_action_feedback=None,
        ),
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=request,
        request_headers={},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
    ):
        chunks.append(chunk)

    assert any("event: pointy_action" in chunk for chunk in chunks)
    assert any("event: answer" in chunk for chunk in chunks)
    assert any("event: done" in chunk for chunk in chunks)
    assert any("v3-pointy_fast_path" in chunk for chunk in chunks)
    ledgers = _runtime_flow_ledgers(chunks)
    assert ledgers
    assert ledgers[0]["route"]["lane"] == "pointy_fast_path"
    assert "ui.highlight" in ledgers[0]["tools"]["observed"]
    terminal_ledger = _terminal_runtime_flow_ledger(chunks)
    assert (
        terminal_ledger["finalization"]["post_turn_lifecycle"]
        == _post_turn_lifecycle_summary()
    )
    orchestrator.build_multi_agent_execution_input.assert_not_called()
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["current_agent"]
        == "pointy_fast_path"
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs[
            "include_lms_insights"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_bypasses_provider_for_visual_fast_path():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        side_effect=AssertionError("visual fast path should not build full context")
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    request = _make_request(
        message=(
            "Create a compact inline visual comparing soft attention and linear attention. "
            "Use structured visual lifecycle."
        ),
        user_context=SimpleNamespace(document_context=None),
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=request,
        request_headers={},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
    ):
        chunks.append(chunk)

    assert any("event: visual_open" in chunk for chunk in chunks)
    assert any("event: visual_commit" in chunk for chunk in chunks)
    assert any("v3-visual_fast_path" in chunk for chunk in chunks)
    ledgers = _runtime_flow_ledgers(chunks)
    assert ledgers
    assert ledgers[0]["route"]["lane"] == "visual_generation"
    assert "visual_runtime" in ledgers[0]["tools"]["observed"]
    terminal_ledger = _terminal_runtime_flow_ledger(chunks)
    assert (
        terminal_ledger["finalization"]["post_turn_lifecycle"]
        == _post_turn_lifecycle_summary()
    )
    traces = _runtime_flow_traces(chunks)
    assert traces
    assert traces[0]["version"] == "wiii.runtime_flow_trace.v1"
    assert traces[0]["turn_path_decision"]["path"] == "visual_generation"
    assert "tool_generate_visual" in traces[0]["tool_policy_session"]["visible_tool_names"]
    orchestrator.build_multi_agent_execution_input.assert_not_called()
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["current_agent"]
        == "visual_fast_path"
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs[
            "include_lms_insights"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_forwards_metadata_agent_to_finalize():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name=None),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(return_value=(
        SimpleNamespace(
            query="Remember this",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
        )
    ))

    async def fake_stream_fn(**kwargs):
        yield SimpleNamespace(type="answer", content="Saved.")
        yield SimpleNamespace(
            type="metadata",
            content={
                "agent_type": "memory_agent",
                "routing_metadata": {"final_agent": "memory_agent"},
            },
        )
        yield SimpleNamespace(type="done", content={"processing_time": 0.2})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(message="Remember this"),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    assert any("event: metadata" in chunk for chunk in chunks)
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["current_agent"]
        == "memory_agent"
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_social_turn_invokes_native_llm_stream():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="hello",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider="nvidia",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )

    captured = {}

    async def fake_native_stream_fn(request):
        captured["request"] = request
        yield WiiiStreamEvent(event_type="answer", payload="LLM says hello")
        yield WiiiStreamEvent(
            event_type="metadata",
            payload={
                "provider": "nvidia",
                "model": "deepseek-ai/deepseek-v4-flash",
                "llm_invoked": True,
            },
        )
        yield WiiiStreamEvent(
            event_type="done",
            payload={"status": "complete", "total_time": 0.5},
        )

    chunks = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.llm_selectability_service.ensure_provider_is_selectable",
            lambda _provider: None,
        )
        async for chunk in generate_stream_v3_events(
            chat_request=_make_request(
                message="hello",
                provider="nvidia",
                model="deepseek-ai/deepseek-v4-flash",
            ),
            request_headers={"X-Request-ID": "req-fast-social"},
            background_save=MagicMock(),
            start_time=time.time(),
            orchestrator=orchestrator,
            stream_fn=fake_native_stream_fn,
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "event: answer" in joined
    assert "LLM says hello" in joined
    assert '"v3-fast-social"' not in joined
    assert '"llm_invoked": false' not in joined
    assert '"transport_fast_social_path"' not in joined
    assert '"llm_invoked": true' in joined
    assert isinstance(captured["request"], WiiiTurnRequest)
    assert captured["request"].query == "hello"
    orchestrator.build_multi_agent_execution_input.assert_awaited_once()
    assert (
        orchestrator.build_multi_agent_execution_input.call_args.kwargs["request_id"]
        == "req-fast-social"
    )
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["request_id"]
        == "req-fast-social"
    )
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["response_text"]
        == "LLM says hello"
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_does_not_fast_path_pointy_questions():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Wiii oi, nut Kham pha khoa hoc o dau?",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )

    async def fake_stream_fn(**kwargs):
        assert kwargs["query"] == "Wiii oi, nut Kham pha khoa hoc o dau?"
        yield SimpleNamespace(type="answer", content="Tool path stays active")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(
            message="Wiii oi, nut Kham pha khoa hoc o dau?"
        ),
        request_headers={},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "Wiii đang gom ngữ cảnh và trí nhớ" in joined
    assert any("Tool path stays active" in chunk for chunk in chunks)
    orchestrator.build_multi_agent_execution_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_stream_v3_events_defaults_to_native_wiii_turn_stream():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort="medium",
            provider="nvidia",
            model="deepseek-ai/deepseek-v3.1",
        )
    )

    captured = {}

    async def fake_stream_wiii_turn(request):
        captured["request"] = request
        yield WiiiStreamEvent(event_type="answer", payload="Native hello")
        yield WiiiStreamEvent(
            event_type="done",
            payload={"status": "complete", "total_time": 0.5},
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.llm_selectability_service.ensure_provider_is_selectable",
            lambda _provider: None,
        )
        mp.setattr(
            "app.engine.multi_agent.streaming_runtime.stream_wiii_turn",
            fake_stream_wiii_turn,
        )
        chunks = []
        async for chunk in generate_stream_v3_events(
            chat_request=_make_request(
                provider="nvidia",
                model="deepseek-ai/deepseek-v3.1",
                thinking_effort="medium",
            ),
            request_headers={},
            background_save=MagicMock(),
            start_time=0.0,
            orchestrator=orchestrator,
        ):
            chunks.append(chunk)

    turn_request = captured["request"]
    assert isinstance(turn_request, WiiiTurnRequest)
    assert turn_request.query == "Explain Rule 5"
    assert turn_request.run_context.user_id == "user-1"
    assert turn_request.run_context.session_id == "session-1"
    assert turn_request.run_context.domain_id == "maritime"
    assert turn_request.run_context.organization_id == "org-1"
    assert turn_request.run_context.thinking_effort == "medium"
    assert turn_request.run_context.provider == "nvidia"
    assert turn_request.run_context.model == "deepseek-ai/deepseek-v3.1"
    assert any("Native hello" in chunk for chunk in chunks)
    orchestrator.finalize_response_turn.assert_called_once()
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["response_text"]
        == "Native hello"
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_accepts_injected_native_wiii_turn_stream():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )

    captured = {}

    async def fake_native_stream_fn(request):
        captured["request"] = request
        yield WiiiStreamEvent(event_type="answer", payload="Injected native")
        yield WiiiStreamEvent(
            event_type="done",
            payload={"status": "complete", "total_time": 0.5},
        )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_native_stream_fn,
    ):
        chunks.append(chunk)

    assert isinstance(captured["request"], WiiiTurnRequest)
    assert any("Injected native" in chunk for chunk in chunks)
    assert (
        orchestrator.finalize_response_turn.call_args.kwargs["response_text"]
        == "Injected native"
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_done_when_stream_omits_final_event():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(return_value=(
        SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
        )
    ))

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Hello without explicit done")

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    assert sum(1 for chunk in chunks if "event: done" in chunk) == 1
    orchestrator.finalize_response_turn.assert_called_once()


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_prepare_heartbeat_when_turn_setup_is_slow():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )

    async def slow_prepare_turn(**_kwargs):
        await asyncio.sleep(0.01)
        return prepared_turn

    orchestrator.prepare_turn = AsyncMock(side_effect=slow_prepare_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Ready after setup")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    chunks = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.chat_stream_coordinator._STAGE_HEARTBEAT_FIRST_AFTER_SEC",
            0.001,
        )
        mp.setattr(
            "app.services.chat_stream_coordinator._STAGE_HEARTBEAT_INTERVAL_SEC",
            0.001,
        )
        async for chunk in generate_stream_v3_events(
            chat_request=_make_request(),
            request_headers={"X-Request-ID": "req-slow-prepare"},
            background_save=MagicMock(),
            start_time=time.time(),
            orchestrator=orchestrator,
            stream_fn=fake_stream_fn,
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert '"stage": "prepare_turn"' in joined
    assert '"heartbeat_index": 1' in joined
    assert '"request_id": "req-slow-prepare"' in joined
    assert "Ready after setup" in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_runtime_heartbeats_and_latency_metadata():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Explain Rule 5",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider="nvidia",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )

    async def slow_native_stream_fn(_request):
        await asyncio.sleep(0.01)
        yield WiiiStreamEvent(event_type="answer", payload="Slow runtime hello")
        await asyncio.sleep(0.01)
        yield WiiiStreamEvent(
            event_type="metadata",
            payload={"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-flash"},
        )
        yield WiiiStreamEvent(
            event_type="done",
            payload={"status": "complete", "total_time": 0.1},
        )

    chunks = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.chat_stream_coordinator._RUNTIME_FIRST_EVENT_HEARTBEAT_AFTER_SEC",
            0.001,
        )
        mp.setattr(
            "app.services.chat_stream_coordinator._RUNTIME_IDLE_HEARTBEAT_INTERVAL_SEC",
            0.001,
        )
        async for chunk in generate_stream_v3_events(
            chat_request=_make_request(),
            request_headers={"X-Request-ID": "req-slow-runtime"},
            background_save=MagicMock(),
            start_time=time.time(),
            orchestrator=orchestrator,
            stream_fn=slow_native_stream_fn,
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert '"stage": "runtime_first_event"' in joined
    assert '"stage": "runtime_idle"' in joined
    assert '"stream_latency": {' in joined
    assert '"timeline": [' in joined
    assert "Slow runtime hello" in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_uses_sync_fallback_when_multi_agent_disabled():
    orchestrator = MagicMock()
    orchestrator._use_multi_agent = False
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(
            user_name="Minh",
            user_id="user-1",
            message="Explain Rule 5",
            user_role=UserRole.STUDENT,
            session_id="session-1",
        ),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.process_without_multi_agent = AsyncMock(
        return_value=ProcessingResult(
            message="Fast local fallback response",
            agent_type=AgentType.DIRECT,
            metadata={
                "mode": "local_direct_llm",
                "model": "qwen3:4b-instruct-2507-q4_K_M",
                "failover": {
                    "switched": True,
                    "switch_count": 1,
                    "initial_provider": "google",
                    "final_provider": "zhipu",
                    "last_reason_code": "auth_error",
                    "last_reason_category": "auth_error",
                    "last_reason_label": "Xac thuc provider that bai.",
                    "route": [
                        {
                            "from_provider": "google",
                            "to_provider": "zhipu",
                            "reason_code": "auth_error",
                            "reason_category": "auth_error",
                            "reason_label": "Xac thuc provider that bai.",
                        }
                    ],
                },
            },
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(),
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
    ):
        chunks.append(chunk)

    joined = "\n".join(chunks)
    orchestrator.process_without_multi_agent.assert_awaited_once()
    orchestrator.build_multi_agent_execution_input.assert_not_called()
    assert "Wiii đang mở đường trả lời nhanh" in joined
    assert any("Fast local fallback response" in chunk for chunk in chunks)
    assert any('"streaming_version": "v3-local_direct_llm"' in chunk for chunk in chunks)
    assert any('"last_reason_code": "auth_error"' in chunk for chunk in chunks)
    orchestrator.finalize_response_turn.assert_called_once()
    terminal_ledger = _terminal_runtime_flow_ledger(chunks)
    assert (
        terminal_ledger["finalization"]["post_turn_lifecycle"]
        == _post_turn_lifecycle_summary()
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_includes_request_id_and_routing_metadata_in_fallback_metadata():
    orchestrator = MagicMock()
    orchestrator._use_multi_agent = False
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(
            user_name="Minh",
            user_id="user-1",
            message="Explain Rule 5",
            user_role=UserRole.STUDENT,
            session_id="session-1",
        ),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.process_without_multi_agent = AsyncMock(
        return_value=ProcessingResult(
            message="Hẹ hẹ~ chào bạn nè.",
            agent_type=AgentType.DIRECT,
            metadata={
                "mode": "local_direct_llm",
                "model": "glm-5",
                "routing_metadata": {
                    "method": "fallback_direct_path",
                    "intent": "teaching",
                },
            },
        )
    )
    orchestrator.finalize_response_turn = MagicMock(
        return_value=_post_turn_lifecycle_summary()
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(message="Explain Rule 5"),
        request_headers={"X-Request-ID": "req-fast-social"},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
    ):
        chunks.append(chunk)

    metadata_chunks = [chunk for chunk in chunks if "event: metadata" in chunk]
    assert metadata_chunks
    metadata_chunk = metadata_chunks[0]
    assert '"request_id": "req-fast-social"' in metadata_chunk
    assert '"routing_metadata": {' in metadata_chunk
    assert '"fallback_direct_path"' in metadata_chunk
    ledgers = _runtime_flow_ledgers(chunks)
    assert ledgers
    assert ledgers[0]["route"]["lane"] == "fallback"
    assert ledgers[0]["runtime"]["fallback_used"] is True
    assert ledgers[0]["runtime"]["model"] == "glm-5"
    terminal_ledger = _terminal_runtime_flow_ledger(chunks)
    assert (
        terminal_ledger["finalization"]["post_turn_lifecycle"]
        == _post_turn_lifecycle_summary()
    )


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_model_switch_prompt_for_unavailable_provider():
    chunks = []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.llm_selectability_service.ensure_provider_is_selectable",
            lambda _provider: (_ for _ in ()).throw(
                ProviderUnavailableError(
                    provider="google",
                    reason_code="rate_limit",
                    message="Provider tam thoi ban hoac da cham gioi han.",
                )
            ),
        )
        mp.setattr(
            "app.services.chat_stream_coordinator.build_model_switch_prompt_for_unavailable",
            lambda **_kwargs: {
                "trigger": "provider_unavailable",
                "recommended_provider": "zhipu",
            },
        )

        async for chunk in generate_stream_v3_events(
            chat_request=_make_request(provider="google"),
            request_headers={},
            background_save=MagicMock(),
            start_time=0.0,
            orchestrator=MagicMock(),
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "event: error" in joined
    assert '"model_switch_prompt"' in joined
    assert '"recommended_provider"' in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_defers_provider_gate_for_uploaded_context():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Video nay dai bao lau?",
            user_id="user-1",
            session_id="session-1",
            context={"conversation_history": ""},
            domain_id="maritime",
            thinking_effort=None,
            provider="google",
            model=None,
        )
    )

    async def fake_stream_fn(**kwargs):
        assert kwargs["provider"] == "google"
        yield SimpleNamespace(type="answer", content="Video dai khoang 4 giay.")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    request = _make_request(
        provider="google",
        message="Video nay dai bao lau?",
        user_context=SimpleNamespace(
            document_context={
                "source": "desktop_upload",
                "attachments": [
                    {
                        "file_name": "lesson.mp4",
                        "media_kind": "video",
                        "markdown": "# Video Context\n\n- Duration: 0:04 (4.20s)",
                    }
                ],
            },
            host_context=None,
            page_context=None,
            host_action_feedback=None,
        ),
    )

    chunks = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.llm_selectability_service.ensure_provider_is_selectable",
            lambda _provider: (_ for _ in ()).throw(
                ProviderUnavailableError(
                    provider="google",
                    reason_code="verifying",
                    message="Provider dang duoc xac minh.",
                )
            ),
        )
        async for chunk in generate_stream_v3_events(
            chat_request=request,
            request_headers={},
            background_save=MagicMock(),
            start_time=0.0,
            orchestrator=orchestrator,
            stream_fn=fake_stream_fn,
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "event: error" not in joined
    assert "Video dai khoang 4 giay." in joined
    assert request.provider == "auto"
    orchestrator.build_multi_agent_execution_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_stream_v3_events_emits_context_thinking_before_answer_for_uploaded_context():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Tom tat tai lieu upload",
            user_id="user-1",
            session_id="session-1",
            context={"document_context": {"attachments": [{"markdown": "# Brief"}]}},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Tai lieu noi ve Wiii.")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    request = _make_request(
        message="Tom tat tai lieu upload",
        user_context=SimpleNamespace(
            document_context={
                "source": "desktop_upload",
                "attachments": [
                    {
                        "file_name": "brief.md",
                        "media_kind": "document",
                        "markdown": "# Brief\n\nPointy can quet DOM truoc.",
                    }
                ],
            },
            host_context=None,
            page_context=None,
            host_action_feedback=None,
        ),
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=request,
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    thinking_start_index = next(
        index for index, chunk in enumerate(chunks) if "event: thinking_start" in chunk
    )
    thinking_delta_index = next(
        index for index, chunk in enumerate(chunks) if "event: thinking_delta" in chunk
    )
    answer_index = next(
        index for index, chunk in enumerate(chunks) if "event: answer" in chunk
    )
    joined = "\n".join(chunks)
    assert thinking_start_index < thinking_delta_index < answer_index
    assert "Wiii đang đọc bối cảnh đính kèm" in joined
    assert "tài liệu đính kèm" in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_suppresses_late_duplicate_context_thinking():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Tom tat tai lieu upload",
            user_id="user-1",
            session_id="session-1",
            context={"document_context": {"attachments": [{"markdown": "# Brief"}]}},
            domain_id="maritime",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="answer", content="Tai lieu noi ve Wiii.")
        yield SimpleNamespace(type="thinking_start", content="Late", node="direct")
        yield SimpleNamespace(type="thinking_delta", content="Late duplicate", node="direct")
        yield SimpleNamespace(type="thinking_end", content="", node="direct")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    request = _make_request(
        message="Tom tat tai lieu upload",
        user_context=SimpleNamespace(
            document_context={
                "source": "desktop_upload",
                "attachments": [
                    {
                        "file_name": "brief.md",
                        "media_kind": "document",
                        "markdown": "# Brief\n\nPointy can quet DOM truoc.",
                    }
                ],
            },
            host_context=None,
            page_context=None,
            host_action_feedback=None,
        ),
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=request,
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    joined = "\n".join(chunks)
    assert joined.count("event: thinking_start") == 1
    assert joined.count("event: thinking_delta") == 1
    assert "Late duplicate" not in joined
    assert "Tai lieu noi ve Wiii." in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_suppresses_pre_answer_duplicate_image_thinking():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Anh nay co gi?",
            user_id="user-1",
            session_id="session-1",
            context={"images": [{"type": "base64", "data": "abc"}]},
            domain_id="maritime",
            thinking_effort=None,
            provider="auto",
            model=None,
        )
    )

    async def fake_stream_fn(**_kwargs):
        yield SimpleNamespace(type="thinking_start", content="Runtime vision", node="direct")
        yield SimpleNamespace(type="thinking_delta", content="Runtime duplicate", node="direct")
        yield SimpleNamespace(type="thinking_end", content="", node="direct")
        yield SimpleNamespace(type="answer", content="Da nhan anh.")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    request = _make_request(
        message="Anh nay co gi?",
        images=[{"type": "base64", "data": "abc", "media_type": "image/png"}],
    )

    chunks = []
    async for chunk in generate_stream_v3_events(
        chat_request=request,
        request_headers={},
        background_save=MagicMock(),
        start_time=0.0,
        orchestrator=orchestrator,
        stream_fn=fake_stream_fn,
    ):
        chunks.append(chunk)

    joined = "\n".join(chunks)
    assert joined.count("event: thinking_start") == 1
    assert joined.count("event: thinking_delta") == 1
    assert "ảnh đính kèm" in joined
    assert "Runtime duplicate" not in joined
    assert "Da nhan anh." in joined


@pytest.mark.asyncio
async def test_generate_stream_v3_events_defers_provider_gate_for_image_input():
    orchestrator = MagicMock()
    prepared_turn = SimpleNamespace(
        request_scope=RequestScope("org-1", "maritime"),
        session_id="session-1",
        validation=SimpleNamespace(blocked=False),
        chat_context=SimpleNamespace(user_name="Minh"),
    )
    orchestrator.prepare_turn = AsyncMock(return_value=prepared_turn)
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query="Anh nay co gi?",
            user_id="user-1",
            session_id="session-1",
            context={"images": [{"type": "base64", "data": "abc"}]},
            domain_id="maritime",
            thinking_effort=None,
            provider="auto",
            model=None,
        )
    )

    async def fake_stream_fn(**kwargs):
        assert kwargs["provider"] == "auto"
        yield SimpleNamespace(type="answer", content="Vision runtime chua san sang.")
        yield SimpleNamespace(type="done", content={"processing_time": 0.1})

    request = _make_request(
        provider="google",
        message="Anh nay co gi?",
        images=[{"type": "base64", "data": "abc", "media_type": "image/png"}],
    )

    chunks = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.llm_selectability_service.ensure_provider_is_selectable",
            lambda _provider: (_ for _ in ()).throw(
                ProviderUnavailableError(
                    provider="google",
                    reason_code="verifying",
                    message="Provider dang duoc xac minh.",
                )
            ),
        )
        async for chunk in generate_stream_v3_events(
            chat_request=request,
            request_headers={},
            background_save=MagicMock(),
            start_time=0.0,
            orchestrator=orchestrator,
            stream_fn=fake_stream_fn,
        ):
            chunks.append(chunk)

    joined = "\n".join(chunks)
    assert "event: error" not in joined
    assert "Vision runtime chua san sang." in joined
    assert request.provider == "auto"
    assert orchestrator.build_multi_agent_execution_input.call_args.kwargs["provider"] == "auto"
