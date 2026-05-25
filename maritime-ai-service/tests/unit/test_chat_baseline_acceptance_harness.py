import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.multi_agent.runtime_flow_ledger import RUNTIME_FLOW_LEDGER_SCHEMA_VERSION
from app.models.schemas import UserRole
from app.services.chat_orchestrator import RequestScope
from app.services.chat_stream_coordinator import generate_stream_v3_events


CHAT_BASELINE_HOST_CONTEXT = {
    "surface": "desktop_chat",
    "capabilities": [],
}

SUPPRESSED_CHAT_TOOLS = {
    "host_action",
    "pointy_action",
    "visual_runtime",
    "code_studio",
}

RAW_PAYLOAD_MARKERS = (
    '"tool_calls"',
    '"function_call"',
    '"host_action"',
    '"pointy_action"',
    '"visual_open"',
    '"code_open"',
    "<wiii-widget",
)


def _make_request(message: str):
    return SimpleNamespace(
        user_id="user-chat-baseline",
        message=message,
        role=UserRole.STUDENT,
        show_previews=False,
        preview_types=[],
        preview_max_count=0,
        thinking_effort=None,
        provider=None,
        model=None,
        user_context={
            "host_context": dict(CHAT_BASELINE_HOST_CONTEXT),
        },
    )


def _make_orchestrator(message: str):
    orchestrator = MagicMock()
    orchestrator._use_multi_agent = True
    orchestrator.prepare_turn = AsyncMock(
        return_value=SimpleNamespace(
            request_scope=RequestScope("org-chat-baseline", "general"),
            session_id="session-chat-baseline",
            validation=SimpleNamespace(blocked=False),
            chat_context=SimpleNamespace(user_name="Minh"),
        )
    )
    orchestrator.build_multi_agent_execution_input = AsyncMock(
        return_value=SimpleNamespace(
            query=message,
            user_id="user-chat-baseline",
            session_id="session-chat-baseline",
            context={
                "conversation_history": "",
                "source_refs": [],
                "memories": [],
            },
            domain_id="general",
            thinking_effort=None,
            provider=None,
            model=None,
        )
    )
    orchestrator.finalize_response_turn = MagicMock()
    return orchestrator


def _event_names(chunks: list[str]) -> list[str]:
    names: list[str] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("event: "):
                names.append(line.removeprefix("event: "))
                break
    return names


def _event_payloads(chunks: list[str], event_name: str) -> list[dict]:
    payloads: list[dict] = []
    marker = f"event: {event_name}"
    for chunk in chunks:
        if marker not in chunk:
            continue
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line.removeprefix("data: ")))
                break
    return payloads


def _answer_text(chunks: list[str]) -> str:
    return "".join(
        str(payload.get("content") or "")
        for payload in _event_payloads(chunks, "answer")
    )


def _terminal_runtime_flow_ledger(chunks: list[str]) -> dict:
    done_payloads = _event_payloads(chunks, "done")
    assert done_payloads, "baseline stream must finish with a done event"
    ledger = done_payloads[-1].get("runtime_flow_ledger")
    assert isinstance(ledger, dict), "terminal done event must carry runtime_flow_ledger"
    return ledger


def _patch_fast_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_visual_fast_path(_chat_request):
        return None

    monkeypatch.setattr(
        "app.services.chat_stream_visual_fast_path.build_visual_fast_path_result",
        no_visual_fast_path,
    )
    monkeypatch.setattr(
        "app.engine.context.pointy_fast_path.build_pointy_fast_path_action",
        lambda *_args, **_kwargs: None,
    )


async def _collect_chat_baseline_chunks(
    *,
    message: str,
    orchestrator,
    stream_fn,
) -> list[str]:
    chunks: list[str] = []
    async for chunk in generate_stream_v3_events(
        chat_request=_make_request(message),
        request_headers={"X-Request-ID": "req-chat-baseline"},
        background_save=MagicMock(),
        start_time=time.time(),
        orchestrator=orchestrator,
        stream_fn=stream_fn,
    ):
        chunks.append(chunk)
    return chunks


def _assert_safe_chat_baseline(
    *,
    chunks: list[str],
    orchestrator,
    expected_answer: str,
) -> None:
    events = _event_names(chunks)
    assert events[-1] == "done"
    assert not ({"host_action", "pointy_action", "visual", "visual_open", "code_open"} & set(events))
    assert _event_payloads(chunks, "metadata")

    answer_text = _answer_text(chunks)
    assert answer_text == expected_answer
    for marker in RAW_PAYLOAD_MARKERS:
        assert marker not in answer_text

    orchestrator.finalize_response_turn.assert_called_once()
    finalize_kwargs = orchestrator.finalize_response_turn.call_args.kwargs
    assert finalize_kwargs["response_text"] == expected_answer
    assert finalize_kwargs["transport_type"] == "stream"
    assert finalize_kwargs["save_response_immediately"] is False

    ledger = _terminal_runtime_flow_ledger(chunks)
    assert ledger["schema_version"] == RUNTIME_FLOW_LEDGER_SCHEMA_VERSION
    assert ledger["request"]["host_surface"] == "desktop_chat"
    assert ledger["request"]["host_capabilities"] == []
    assert ledger["context"]["document_context_present"] is False
    assert ledger["context"]["uploaded_document_count"] == 0
    assert ledger["context"]["source_ref_count"] == 0
    assert ledger["route"]["lane"] == "native_turn"
    assert ledger["tools"]["observed"] == []
    assert SUPPRESSED_CHAT_TOOLS.issubset(set(ledger["tools"]["suppressed"]))
    assert ledger["stream"]["metadata_seen"] is True
    assert ledger["stream"]["done_seen"] is True
    assert ledger["stream"]["event_sequence_tail"][-1] == "done"
    assert ledger["host_actions"]["preview_required"] is False
    assert ledger["host_actions"]["preview_emitted"] is False
    assert ledger["host_actions"]["approval_token_present"] is False
    assert ledger["host_actions"]["apply_attempted"] is False
    assert ledger["finalization"]["status"] == "saved"

    done_payload = _event_payloads(chunks, "done")[-1]
    latency = done_payload.get("stream_latency")
    assert isinstance(latency, dict)
    assert isinstance(latency.get("elapsed_ms"), int)
    assert isinstance(latency.get("latency_ms_by_stage"), dict)
    assert isinstance(latency.get("timeline"), list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario_name", "message", "answer"),
    [
        pytest.param(
            "vietnamese_greeting",
            "xin chào Wiii, hôm nay bạn thế nào?",
            "Chào bạn, mình vẫn ở đây và sẵn sàng cùng bạn làm tiếp.",
            id="vietnamese_greeting",
        ),
        pytest.param(
            "simple_factual_chat",
            "giải thích ngắn gọn sự khác nhau giữa API và SDK",
            "API là giao diện để phần mềm gọi nhau; SDK là bộ công cụ giúp lập trình viên dùng API đó dễ hơn.",
            id="simple_factual_chat",
        ),
        pytest.param(
            "inline_code_explanation",
            "cho mình ví dụ nhỏ về Promise trong JavaScript",
            "Ví dụ nhỏ:\n\n```javascript\nPromise.resolve('x').then(console.log);\n```\n\nPromise giữ kết quả bất đồng bộ và gọi `.then` khi hoàn tất.",
            id="inline_code_explanation",
        ),
        pytest.param(
            "no_uploaded_document_request",
            "tóm tắt tài liệu mình đã tải lên",
            "Mình chưa thấy tài liệu nào được tải lên trong lượt này. Bạn gửi tài liệu hoặc đoạn nội dung cần tóm tắt nhé.",
            id="no_uploaded_document_request",
        ),
        pytest.param(
            "lms_intent_without_lms_surface",
            "tạo cho mình bài học",
            "Mình cần tài liệu hoặc yêu cầu bài học cụ thể trước. Khi bạn gửi nội dung, mình sẽ tạo bản nháp để bạn duyệt trước khi áp dụng.",
            id="lms_intent_without_lms_surface",
        ),
    ],
)
async def test_chat_baseline_acceptance_scenarios_stay_on_safe_chat_lane(
    monkeypatch,
    scenario_name: str,
    message: str,
    answer: str,
):
    _patch_fast_paths(monkeypatch)
    orchestrator = _make_orchestrator(message)

    async def baseline_stream_fn(turn_request):
        assert turn_request.query == message
        yield SimpleNamespace(type="answer", content=answer)
        yield SimpleNamespace(type="done", content={"status": "complete"})

    chunks = await _collect_chat_baseline_chunks(
        message=message,
        orchestrator=orchestrator,
        stream_fn=baseline_stream_fn,
    )

    assert scenario_name
    _assert_safe_chat_baseline(
        chunks=chunks,
        orchestrator=orchestrator,
        expected_answer=answer,
    )


@pytest.mark.asyncio
async def test_chat_baseline_acceptance_records_slow_stream_heartbeat(monkeypatch):
    _patch_fast_paths(monkeypatch)
    message = "xin chào Wiii, phản hồi chậm một chút cũng được"
    answer_parts = ["Slow runtime hello", " sau heartbeat."]
    orchestrator = _make_orchestrator(message)

    async def slow_native_stream_fn(turn_request):
        assert turn_request.query == message
        await asyncio.sleep(0.03)
        yield SimpleNamespace(type="answer", content=answer_parts[0])
        await asyncio.sleep(0.03)
        yield SimpleNamespace(type="answer", content=answer_parts[1])
        yield SimpleNamespace(type="done", content={"status": "complete"})

    monkeypatch.setattr(
        "app.services.chat_stream_coordinator._RUNTIME_FIRST_EVENT_HEARTBEAT_AFTER_SEC",
        0.001,
    )
    monkeypatch.setattr(
        "app.services.chat_stream_coordinator._RUNTIME_IDLE_HEARTBEAT_INTERVAL_SEC",
        0.001,
    )

    chunks = await _collect_chat_baseline_chunks(
        message=message,
        orchestrator=orchestrator,
        stream_fn=slow_native_stream_fn,
    )

    status_stages = [
        payload.get("details", {}).get("stage")
        for payload in _event_payloads(chunks, "status")
    ]
    assert "runtime_first_event" in status_stages
    assert "runtime_idle" in status_stages
    _assert_safe_chat_baseline(
        chunks=chunks,
        orchestrator=orchestrator,
        expected_answer="".join(answer_parts),
    )
