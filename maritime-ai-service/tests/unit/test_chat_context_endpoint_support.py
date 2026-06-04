from unittest.mock import MagicMock


def test_load_recent_history_payload_handles_unavailable_repo():
    from app.api.v1.chat_context_endpoint_support import (
        load_recent_history_payload,
    )

    chat_history = MagicMock()
    chat_history.is_available.return_value = False

    result = load_recent_history_payload(
        chat_history=chat_history,
        session_id="session-1",
        user_id="user-1",
    )

    assert result == []


def test_load_recent_history_payload_maps_message_shape():
    from types import SimpleNamespace

    from app.api.v1.chat_context_endpoint_support import (
        load_recent_history_payload,
    )

    chat_history = MagicMock()
    chat_history.is_available.return_value = True
    chat_history.get_recent_messages.return_value = [
        SimpleNamespace(role="user", content="hello"),
        SimpleNamespace(role="assistant", content="hi"),
    ]

    result = load_recent_history_payload(
        chat_history=chat_history,
        session_id="session-1",
        user_id="user-1",
        organization_id="org-1",
    )

    assert result == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    chat_history.get_recent_messages.assert_called_once_with(
        "session-1",
        user_id="user-1",
        organization_id="org-1",
    )


def test_build_context_compacted_response_uses_standard_payload():
    import json

    from app.api.v1.chat_context_endpoint_support import (
        build_context_compacted_response,
    )

    response = build_context_compacted_response(
        session_id="session-1",
        summary="summary text",
        history_list=[{"role": "user", "content": "a"}] * 6,
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["status"] == "compacted"
    assert payload["summary_length"] == len("summary text")
    assert payload["messages_summarized"] == 2


def test_build_context_cleared_response_uses_standard_payload():
    import json

    from app.api.v1.chat_context_endpoint_support import (
        build_context_cleared_response,
    )

    response = build_context_cleared_response(session_id="session-1")

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload == {
        "status": "cleared",
        "session_id": "session-1",
        "message": "Context đã được xóa. Bắt đầu cuộc trò chuyện mới.",
    }


def test_build_context_info_response_wraps_info_payload():
    import json

    from app.api.v1.chat_context_endpoint_support import (
        build_context_info_response,
    )

    response = build_context_info_response(info={"session_id": "session-1"})

    assert response.status_code == 200
    assert json.loads(response.body) == {"session_id": "session-1"}
