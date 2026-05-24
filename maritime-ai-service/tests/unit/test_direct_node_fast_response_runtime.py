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
