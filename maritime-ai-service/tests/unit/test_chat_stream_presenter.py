import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_chat_stream_presenter():
    path = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "chat_stream_presenter.py"
    spec = spec_from_file_location("chat_stream_presenter_test", path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_emit_blocked_sse_events_emits_answer_metadata_done():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    blocked_response = SimpleNamespace(
        message="Blocked message",
        metadata={"blocked": True},
    )

    chunks, counter = presenter.emit_blocked_sse_events(
        blocked_response=blocked_response,
        session_id="session-1",
        processing_time=0.25,
        event_counter=0,
    )

    assert counter == 3
    assert "event: answer" in chunks[0]
    assert "event: metadata" in chunks[1]
    assert "session-1" in chunks[1]
    assert "event: done" in chunks[2]


def test_format_sse_sanitizes_direct_wire_payload():
    presenter = _load_chat_stream_presenter()

    chunk = presenter.format_sse(
        "metadata",
        {
            "content": "Bearer raw-format-token-12345678",
            "access_token": "raw-access-token",
            "provider_payload": {"id": "raw-provider"},
            "nested": {"url": "https://example.com?token=raw-url-token"},
            "safe": "ok",
        },
        event_id=9,
    )

    data_line = next(line for line in chunk.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    serialized = json.dumps(payload, ensure_ascii=False)

    assert payload["safe"] == "ok"
    assert payload["content"] == "Bearer <redacted-secret>"
    assert "access_token" not in payload
    assert "provider_payload" not in payload
    assert "raw-format-token" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-provider" not in serialized
    assert "raw-url-token" not in serialized


def test_emit_blocked_sse_events_sanitizes_metadata_at_wire_boundary():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    blocked_response = SimpleNamespace(
        message="Blocked access_token=raw-blocked-answer-token",
        metadata={
            "blocked": True,
            "access_token": "raw-blocked-metadata-token",
            "provider_payload": {"id": "raw-provider"},
        },
    )

    chunks, _ = presenter.emit_blocked_sse_events(
        blocked_response=blocked_response,
        session_id="session-1",
        processing_time=0.25,
        event_counter=0,
        extra_metadata={"reason": "token=raw-extra-token"},
    )

    serialized = "\n".join(chunks)

    assert "Blocked <redacted-secret>" in serialized
    assert "raw-blocked-answer-token" not in serialized
    assert "raw-blocked-metadata-token" not in serialized
    assert "raw-provider" not in serialized
    assert "raw-extra-token" not in serialized


def test_serialize_stream_event_metadata_adds_streaming_version():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(type="metadata", content={"processing_time": 1.5})

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=4,
        enable_artifacts=True,
    )

    assert counter == 5
    assert should_stop is False
    data_line = next(
        line for line in chunks[0].split("\n") if line.startswith("data: ")
    )
    payload = json.loads(data_line[6:])
    assert payload["streaming_version"] == "v3-graph"


def test_serialize_stream_event_skips_artifact_when_disabled():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(
        type="artifact",
        content={"artifact_id": "a1"},
        node="tutor_agent",
    )

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=2,
        enable_artifacts=False,
    )

    assert chunks == []
    assert counter == 2
    assert should_stop is False


def test_serialize_stream_event_error_requests_stop():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(type="error", content={"message": "boom"})

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=7,
        enable_artifacts=True,
    )

    assert counter == 8
    assert should_stop is True
    assert "stream_error" in chunks[0]


def test_serialize_stream_event_error_preserves_provider_metadata():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(
        type="error",
        content={
            "message": "Provider tam thoi ban hoac da cham gioi han.",
            "provider": "google",
            "reason_code": "busy",
        },
    )

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=3,
        enable_artifacts=True,
    )

    assert counter == 4
    assert should_stop is True
    data_line = next(
        line for line in chunks[0].split("\n") if line.startswith("data: ")
    )
    payload = json.loads(data_line[6:])
    assert payload["provider"] == "google"
    assert payload["reason_code"] == "busy"


def test_serialize_stream_event_visual_emits_sse_chunk():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(
        type="visual",
        content={
            "id": "visual-1",
            "visual_session_id": "vs-1",
            "type": "comparison",
            "runtime": "svg",
            "title": "A vs B",
            "summary": "Quick compare",
            "spec": {"left": {"title": "A"}, "right": {"title": "B"}},
        },
        node="direct",
    )

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=1,
        enable_artifacts=False,
    )

    assert should_stop is False
    assert counter == 2
    assert len(chunks) == 1
    assert "event: visual" in chunks[0]
    data_line = next(
        line for line in chunks[0].split("\n") if line.startswith("data: ")
    )
    payload = json.loads(data_line[6:])
    assert payload["display_role"] == "artifact"
    assert payload["presentation"] == "compact"


def test_serialize_stream_event_visual_lifecycle_chunks():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    events = [
        SimpleNamespace(
            type="visual_open",
            content={
                "id": "visual-2",
                "visual_session_id": "vs-2",
                "type": "process",
                "runtime": "svg",
                "title": "Pipeline",
                "summary": "Quick process",
                "spec": {"steps": [{"title": "Start"}, {"title": "End"}]},
            },
            node="direct",
        ),
        SimpleNamespace(
            type="visual_commit",
            content={"visual_session_id": "vs-2", "status": "committed"},
            node="direct",
        ),
        SimpleNamespace(
            type="visual_dispose",
            content={"visual_session_id": "vs-2", "status": "disposed", "reason": "reset"},
            node="direct",
        ),
    ]

    counter = 2
    emitted = []
    for event in events:
        chunks, counter, should_stop = presenter.serialize_stream_event(
            event=event,
            event_counter=counter,
            enable_artifacts=False,
        )
        assert should_stop is False
        emitted.extend(chunks)

    assert any("event: visual_open" in chunk for chunk in emitted)
    assert any("event: visual_commit" in chunk for chunk in emitted)
    assert any("event: visual_dispose" in chunk for chunk in emitted)


def test_serialize_stream_event_code_studio_chunks():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    events = [
        SimpleNamespace(
            type="code_open",
            content={
                "session_id": "vs-code-1",
                "title": "Pendulum App",
                "language": "html",
                "version": 1,
                "studio_lane": "app",
                "artifact_kind": "html_app",
            },
            node="code_studio_agent",
        ),
        SimpleNamespace(
            type="code_delta",
            content={
                "session_id": "vs-code-1",
                "chunk": "<div>",
                "chunk_index": 0,
                "total_bytes": 1024,
            },
            node="code_studio_agent",
        ),
        SimpleNamespace(
            type="code_complete",
            content={
                "session_id": "vs-code-1",
                "full_code": "<div>done</div>",
                "language": "html",
                "version": 1,
            },
            node="code_studio_agent",
        ),
    ]

    counter = 0
    emitted = []
    for event in events:
        chunks, counter, should_stop = presenter.serialize_stream_event(
            event=event,
            event_counter=counter,
            enable_artifacts=True,
        )
        assert should_stop is False
        emitted.extend(chunks)

    assert any("event: code_open" in chunk for chunk in emitted)
    assert any("event: code_delta" in chunk for chunk in emitted)
    assert any("event: code_complete" in chunk for chunk in emitted)

    code_open_data = next(chunk for chunk in emitted if "event: code_open" in chunk)
    data_line = next(line for line in code_open_data.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[6:])
    assert payload["display_role"] == "artifact"
    assert payload["presentation"] == "compact"


def test_emit_internal_error_sse_events_can_include_done():
    presenter = _load_chat_stream_presenter()

    chunks, counter = presenter.emit_internal_error_sse_events(
        processing_time=1.25,
        event_counter=3,
    )

    assert counter == 5
    assert "event: error" in chunks[0]
    assert "Internal processing error" in chunks[0]
    assert "event: done" in chunks[1]


def test_emit_internal_error_sse_events_supports_single_error_chunk():
    presenter = _load_chat_stream_presenter()

    chunks, counter = presenter.emit_internal_error_sse_events()

    assert counter is None
    assert len(chunks) == 1
    assert "event: error" in chunks[0]


def test_serialize_stream_event_thinking_start_marks_summary_as_header_only():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()

    event = SimpleNamespace(
        type="thinking_start",
        content="Bat nhip cau hoi",
        node="direct",
        details={
            "summary": "Minh dang gom vai moc dang tin truoc khi chot cau tra loi.",
            "summary_mode": "header_only",
            "phase": "attune",
        },
    )

    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=9,
        enable_artifacts=True,
    )

    assert counter == 10
    assert should_stop is False
    data_line = next(
        line for line in chunks[0].split("\n") if line.startswith("data: ")
    )
    payload = json.loads(data_line[6:])
    assert payload["summary"] == "Minh dang gom vai moc dang tin truoc khi chot cau tra loi."
    assert payload["summary_mode"] == "header_only"
    assert payload["phase"] == "attune"


def test_serialize_stream_event_emits_pointy_action_through_sse_wire():
    """v3.0 F6 regression: pointy_action MUST be in the {tool_call,
    tool_result, host_action, ...} allowlist on line 399. Without it,
    backend dispatches the event correctly but presenter drops it
    silently — frontend onPointyAction never fires, cursor stays static.
    """
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()
    event = SimpleNamespace(
        type='pointy_action',
        content={
            'action': 'ui.highlight',
            'requestId': 'pointy-test-1',
            'request_id': 'pointy-test-1',
            'params': {'selector': 'chat-send-button', 'message': 'Đây.', 'duration_ms': 4500},
            'mode': 'highlight',
        },
        node='direct',
        step=None,
        details=None,
    )
    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=event,
        event_counter=0,
        enable_artifacts=True,
        presentation_state=None,
    )
    assert chunks, 'pointy_action must produce at least one SSE chunk'
    assert should_stop is False
    # SSE event line: 'event: pointy_action'
    assert any('event: pointy_action' in c for c in chunks), (
        f'pointy_action not emitted as SSE event. Got: {chunks!r}'
    )
    # Payload preserved.
    data_line = next(
        line for line in chunks[0].split('\n') if line.startswith('data: ')
    )
    payload = json.loads(data_line[6:])
    assert payload['content']['action'] == 'ui.highlight'
    assert payload['content']['params']['selector'] == 'chat-send-button'


def test_strip_soul_tags_handles_malformed_and_escaped_variants():
    presenter = _load_chat_stream_presenter()

    assert presenter._strip_soul_tags(
        '<!--WIII_SOUL: {"mood":"warm"}--> Nut gui tin nhan.'
    ) == "Nut gui tin nhan."
    assert presenter._strip_soul_tags(
        '<! -- WIII_SOUL: {"mood":"warm"} -- > Nut gui tin nhan.'
    ) == "Nut gui tin nhan."
    assert presenter._strip_soul_tags(
        '&lt;!-- WIII_SOUL: {"mood":"warm"} --&gt; Nut gui tin nhan.'
    ) == "Nut gui tin nhan."


def test_serialize_stream_event_strips_split_soul_tag_from_answer_delta():
    from types import SimpleNamespace

    presenter = _load_chat_stream_presenter()
    state = presenter.StreamPresentationState()

    first = SimpleNamespace(
        type="answer_delta",
        content='<! --WIII_SOUL: {"mood":"warm"',
        node="direct",
        details=None,
    )
    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=first,
        event_counter=0,
        enable_artifacts=True,
        presentation_state=state,
    )

    assert chunks == []
    assert counter == 1
    assert should_stop is False

    second = SimpleNamespace(
        type="answer_delta",
        content='}--> Nut gui tin nhan.',
        node="direct",
        details=None,
    )
    chunks, counter, should_stop = presenter.serialize_stream_event(
        event=second,
        event_counter=counter,
        enable_artifacts=True,
        presentation_state=state,
    )

    assert should_stop is False
    data_line = next(
        line for line in chunks[0].split("\n") if line.startswith("data: ")
    )
    payload = json.loads(data_line[6:])
    assert payload["content"] == "Nut gui tin nhan."
    assert "WIII_SOUL" not in chunks[0]
