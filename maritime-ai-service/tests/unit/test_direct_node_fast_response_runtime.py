from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.direct_node_pre_llm_stage_contract import (
    DirectNodeFastResponseDependencies,
    DirectNodeFastResponseRequest,
)


def _record_snapshot_calls():
    calls: list[dict] = []

    def record_snapshot(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})

    return calls, record_snapshot


def _resolve_fast_response(
    *,
    query: str,
    state: dict,
    ctx: dict,
    has_uploaded_document_context: bool,
    record_snapshot,
):
    from app.engine.multi_agent.direct_node_fast_response_runtime import (
        resolve_direct_node_fast_response,
    )

    return resolve_direct_node_fast_response(
        request=DirectNodeFastResponseRequest(
            query=query,
            state=state,
            ctx=ctx,
            has_uploaded_document_context=has_uploaded_document_context,
        ),
        dependencies=DirectNodeFastResponseDependencies(
            normalize_for_intent=_normalize_for_intent,
            needs_web_search=lambda _query: False,
            needs_datetime=lambda _query: False,
            record_thinking_snapshot_fn=record_snapshot,
        ),
    )


def test_fast_response_resolves_pointy_missing_inventory_without_llm():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {
        "force_skills": ["wiii-pointy"],
        "context": {"force_skills": ["wiii-pointy"]},
    }

    result = _resolve_fast_response(
        query="show send button",
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "pointy_missing_inventory"
    assert "host_context" in result.response
    assert "Pointy" in state["thinking_content"]
    assert calls[0]["kwargs"]["provenance"] == "deterministic_pointy_missing_inventory"


def test_fast_response_session_ack_sets_ack_flag_and_snapshot():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {
        "routing_metadata": {
            "method": "conservative_fast_path",
            "intent": "off_topic",
        }
    }
    query = (
        "Trong phien nay, hay nho uu tien A. "
        "Tra loi chi: Da ghi nhan."
    )

    result = _resolve_fast_response(
        query=query,
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "session_memory_ack"
    assert state["_direct_reply_only_ack"] is True
    assert result.response == "Da ghi nhan."
    assert calls[0]["kwargs"]["provenance"] == "deterministic_session_ack"


def test_fast_response_uploaded_document_fact_uses_document_context():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {"routing_metadata": {"intent": "uploaded_file_context"}}
    ctx = {
        "document_context": {
            "attachments": [
                {
                    "file_name": "lesson.docx",
                    "media_kind": "document",
                    "parser": "markitdown",
                    "markdown": (
                        "Marker: WIII_DOCX_MARKER_487\n"
                        "Priority: source-grounded preview only."
                    ),
                }
            ]
        }
    }

    result = _resolve_fast_response(
        query="Tai lieu vua upload co marker nao?",
        state=state,
        ctx=ctx,
        has_uploaded_document_context=True,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "uploaded_file_context_fact"
    assert "WIII_DOCX_MARKER_487" in result.response
    assert calls[0]["kwargs"]["provenance"] == "deterministic_uploaded_file_context_fact"


def test_fast_response_answers_facebook_connection_from_host_snapshot():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {
        "context": {
            "host_context": {
                "host_type": "wiii-desktop",
                "page": {
                    "type": "chat",
                    "metadata": {
                        "wiii_connect": {
                            "provider_slug": "facebook",
                            "provider_label": "Facebook",
                            "status": "connected",
                            "active_connection_count": 1,
                            "page_count": 1,
                            "page_names": ["Wiii"],
                        }
                    },
                },
            }
        }
    }

    result = _resolve_fast_response(
        query="Wiii có kết nối được Facebook không?",
        state=state,
        ctx=state["context"],
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "wiii_connect_facebook_status"
    assert "Facebook đang được kết nối" in result.response
    assert "Wiii" in result.response
    assert calls[0]["kwargs"]["provenance"] == "deterministic_wiii_connect_facebook_status"


def test_fast_response_answers_provider_connection_from_backend_snapshot(monkeypatch):
    from app.engine.multi_agent import wiii_connect_intent as intent_module

    class FakeSnapshot:
        def provider_status(self, provider_slug):
            assert provider_slug == "gmail"
            return {
                "status": "connected",
                "agent_ready": False,
                "reason": "connected_provider_not_agent_ready",
                "connection_count": 1,
                "active_connection_count": 1,
                "connection_state": "connected",
            }

    monkeypatch.setattr(
        intent_module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: FakeSnapshot(),
    )
    calls, record_snapshot = _record_snapshot_calls()

    result = _resolve_fast_response(
        query="Gmail đã kết nối chưa?",
        state={"context": {}},
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "wiii_connect_provider_status"
    assert "Gmail" in result.response
    assert "connected chưa đồng nghĩa agent-ready" in result.response
    assert calls[0]["kwargs"]["provenance"] == "deterministic_wiii_connect_provider_status"


def test_fast_response_blocks_providerless_facebook_action_continuation():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {
        "context": {},
        "messages": [
            {
                "role": "user",
                "content": "Wiii co the dang bai len Facebook khong?",
            },
            {
                "role": "assistant",
                "content": "Facebook chua agent-ready trong Wiii Connect.",
            },
        ],
    }

    result = _resolve_fast_response(
        query='dang bai: "xin chao minh la AI" la duoc',
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "wiii_connect_facebook_unavailable"
    assert state["_external_app_action_plan"]["provider_slug"] == "facebook"
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert calls[0]["kwargs"]["provenance"] == (
        "deterministic_wiii_connect_facebook_unavailable"
    )


def test_fast_response_blocks_missing_provider_external_action():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {"context": {}, "messages": []}

    result = _resolve_fast_response(
        query="dang bai len mang xa hoi di",
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "wiii_connect_external_app_action_unavailable"
    assert "provider" in result.response
    assert "Wiii Connect" in result.response
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["reason"] == "missing_provider_target"
    assert calls[0]["kwargs"]["provenance"] == (
        "deterministic_wiii_connect_external_app_action_unavailable"
    )


def test_fast_response_blocks_generic_provider_not_agent_ready():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {"context": {}, "messages": []}

    result = _resolve_fast_response(
        query="doc Gmail moi nhat di",
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is not None
    assert result.response_type == "wiii_connect_external_app_action_unavailable"
    assert "Gmail" in result.response
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["provider_slug"] == "gmail"
    assert state["_external_app_action_plan"]["reason"] == "provider_not_agent_ready"
    assert calls[0]["kwargs"]["provenance"] == (
        "deterministic_wiii_connect_external_app_action_unavailable"
    )


def test_fast_response_leaves_casual_chatter_for_provider_direct_path():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {
        "routing_metadata": {"method": "conservative_fast_path", "intent": "social"}
    }

    for query in ("đói phết", "trưa nay ăn cơm rồi"):
        result = _resolve_fast_response(
            query=query,
            state=state,
            ctx={},
            has_uploaded_document_context=False,
            record_snapshot=record_snapshot,
        )

        assert result is None

    assert calls == []


def test_fast_response_returns_none_for_regular_learning_turn():
    calls, record_snapshot = _record_snapshot_calls()
    state: dict = {"routing_metadata": {"intent": "learning"}}

    result = _resolve_fast_response(
        query="Giai thich quy tac COLREG 15",
        state=state,
        ctx={},
        has_uploaded_document_context=False,
        record_snapshot=record_snapshot,
    )

    assert result is None
    assert calls == []
