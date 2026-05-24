from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.engine.multi_agent.direct_node_pre_llm_pipeline import (
    execute_direct_node_pre_llm_pipeline,
)


@pytest.mark.asyncio
async def test_pre_llm_pipeline_preserves_document_then_image_order():
    state = {"context": {"document_context": {"documents": [{"id": "doc-1"}]}}}
    calls: list[str] = []
    tracer = MagicMock()

    def start_turn_fn(**_kwargs):
        calls.append("start")
        return SimpleNamespace(
            query_lower="tao bai hoc",
            response=None,
            response_type="",
            explicit_web_search_turn=False,
        )

    def build_preview_sanitizer_fn(**_kwargs):
        calls.append("build_sanitizer")
        return lambda text, _events: f"clean:{text}"

    def record_document_plan_fn(**kwargs):
        calls.append("record_plan")
        assert kwargs["has_uploaded_document_context"] is True
        assert "Wiii" in kwargs["document_thinking"]

    async def document_preview_preflight_fn(**kwargs):
        calls.append("document")
        assert kwargs["response_present"] is False
        assert kwargs["sanitize_preview_response"]("ok", []) == "clean:ok"
        return SimpleNamespace(
            response="Preview da gui.",
            response_type="document_preview_host_action",
        )

    async def image_input_preflight_fn(**kwargs):
        calls.append("image")
        assert kwargs["response_present"] is True
        return None

    def fast_response_fn(**_kwargs):
        raise AssertionError("fast response should not run after document preview")

    result = await execute_direct_node_pre_llm_pipeline(
        query="tao bai hoc",
        state=state,
        bus_id="bus-1",
        push_event=lambda *_args, **_kwargs: None,
        tracer=tracer,
        enable_natural_conversation=True,
        default_domain="maritime",
        get_domain_greetings=lambda _domain: {},
        normalize_for_intent=lambda text: text,
        needs_web_search=lambda _text: False,
        needs_datetime=lambda _text: False,
        build_visual_tool_runtime_metadata=lambda *_args, **_kwargs: {},
        execute_direct_tool_rounds=lambda *_args, **_kwargs: None,
        extract_direct_response=lambda *_args, **_kwargs: "",
        sanitize_structured_visual_answer_text=lambda text, *_args, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, *_args, **_kwargs: text,
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        logger_obj=MagicMock(),
        start_turn_fn=start_turn_fn,
        has_uploaded_document_context_fn=lambda _ctx: True,
        build_preview_sanitizer_fn=build_preview_sanitizer_fn,
        record_document_plan_fn=record_document_plan_fn,
        document_preview_preflight_fn=document_preview_preflight_fn,
        image_input_preflight_fn=image_input_preflight_fn,
        fast_response_fn=fast_response_fn,
    )

    assert result.response == "Preview da gui."
    assert result.response_type == "document_preview_host_action"
    assert result.has_uploaded_document_context is True
    assert result.domain_name_vi == "Hang hai"
    assert calls == ["start", "build_sanitizer", "record_plan", "document", "image"]
    tracer.end_step.assert_called_once()
    assert tracer.end_step.call_args.kwargs["details"]["response_type"] == (
        "document_preview_host_action"
    )


@pytest.mark.asyncio
async def test_pre_llm_pipeline_uses_fast_response_when_preflights_do_not_answer():
    tracer = MagicMock()

    async def no_document_answer(**_kwargs):
        return None

    async def no_image_answer(**_kwargs):
        return None

    result = await execute_direct_node_pre_llm_pipeline(
        query="wiii pipeline la gi",
        state={"context": {}, "domain_id": "custom_domain"},
        bus_id=None,
        push_event=lambda *_args, **_kwargs: None,
        tracer=tracer,
        enable_natural_conversation=True,
        default_domain="maritime",
        get_domain_greetings=lambda _domain: {},
        normalize_for_intent=lambda text: text,
        needs_web_search=lambda _text: False,
        needs_datetime=lambda _text: False,
        build_visual_tool_runtime_metadata=lambda *_args, **_kwargs: {},
        execute_direct_tool_rounds=lambda *_args, **_kwargs: None,
        extract_direct_response=lambda *_args, **_kwargs: "",
        sanitize_structured_visual_answer_text=lambda text, *_args, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, *_args, **_kwargs: text,
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        logger_obj=MagicMock(),
        start_turn_fn=lambda **_kwargs: SimpleNamespace(
            query_lower="wiii pipeline la gi",
            response=None,
            response_type="",
            explicit_web_search_turn=True,
        ),
        has_uploaded_document_context_fn=lambda _ctx: False,
        record_document_plan_fn=lambda **_kwargs: None,
        document_preview_preflight_fn=no_document_answer,
        image_input_preflight_fn=no_image_answer,
        fast_response_fn=lambda **_kwargs: SimpleNamespace(
            response="Fast answer.",
            response_type="wiii_pipeline_meta",
        ),
    )

    assert result.response == "Fast answer."
    assert result.response_type == "wiii_pipeline_meta"
    assert result.explicit_web_search_turn is True
    assert result.domain_name_vi == "custom_domain"
    tracer.end_step.assert_called_once()
    assert tracer.end_step.call_args.kwargs["details"] == {
        "response_type": "wiii_pipeline_meta",
        "query": "wiii pipeline la gi",
    }
