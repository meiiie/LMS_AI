import logging

import pytest

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.direct_node_exception_fallback_contract import (
    DirectNodeExceptionFallbackDependencies,
    DirectNodeExceptionFallbackRequest,
)
from app.engine.multi_agent.direct_node_exception_fallbacks import (
    _emit_synthetic_tool_events,
    handle_direct_node_generation_exception,
)


class _Tracer:
    def __init__(self):
        self.steps = []

    def end_step(self, **kwargs):
        self.steps.append(kwargs)


def _record_snapshot(*, state, thinking, provenance, record_thinking_snapshot_fn):
    state["thinking_content"] = thinking
    state["_thinking_provenance"] = provenance
    record_thinking_snapshot_fn(state, thinking)
    return thinking


def _base_request(**overrides):
    tracer = overrides.pop("tracer", _Tracer())

    async def _push_event(_event):
        return None

    values = {
        "exc": RuntimeError("boom"),
        "query": "gia dau hom nay",
        "state": {},
        "ctx_for_preflight": {},
        "tools": [],
        "tool_call_events": [],
        "llm_response": None,
        "messages": [],
        "llm": None,
        "routing_intent": "general",
        "response_language": "vi",
        "is_identity_turn": False,
        "explicit_user_provider": None,
        "explicit_web_search_turn": False,
        "tracer": tracer,
        "push_event": _push_event,
    }
    values.update(overrides)
    return DirectNodeExceptionFallbackRequest(**values)


def _base_dependencies(**overrides):
    async def _no_salvage(**_kwargs):
        return None

    values = {
        "needs_web_search": lambda _query: False,
        "extract_direct_response": lambda *_args, **_kwargs: ("", "", []),
        "sanitize_structured_visual_answer_text": lambda text, **_kwargs: text,
        "sanitize_wiii_house_text": lambda text, **_kwargs: text,
        "build_search_template_fallback": lambda **_kwargs: "",
        "build_uploaded_document_context_fallback_answer": lambda *_args, **_kwargs: "",
        "build_codebase_analysis_fallback_answer": lambda _query: "codebase fallback",
        "build_codebase_analysis_fallback_thinking": lambda _query: "codebase thinking",
        "get_phase_fallback": lambda _state: "phase fallback",
        "record_direct_node_thinking_snapshot": _record_snapshot,
        "record_thinking_snapshot_fn": lambda *_args, **_kwargs: None,
        "inc_counter": lambda *_args, **_kwargs: None,
        "logger_obj": logging.getLogger("test.direct_node_exception_fallbacks"),
        "salvage_direct_turn_from_final_result_fn": _no_salvage,
    }
    values.update(overrides)
    return DirectNodeExceptionFallbackDependencies(**values)


@pytest.mark.asyncio
async def test_exception_fallback_records_salvaged_final_result():
    state = {}
    tracer = _Tracer()

    async def _salvage(**_kwargs):
        return "Recovered answer", "Recovered thinking", [{"name": "tool_x"}]

    result = await handle_direct_node_generation_exception(
        request=_base_request(
            state=state,
            tracer=tracer,
        ),
        dependencies=_base_dependencies(
            salvage_direct_turn_from_final_result_fn=_salvage,
        ),
    )

    assert result.response == "Recovered answer"
    assert state["tools_used"] == [{"name": "tool_x"}]
    assert state["thinking_content"] == "Recovered thinking"
    assert state["_thinking_provenance"] == "final_snapshot"
    assert tracer.steps[-1]["details"]["response_type"] == "llm_salvaged"


@pytest.mark.asyncio
async def test_provider_unavailable_with_tool_events_returns_source_template():
    state = {}
    events = [
        {"type": "call", "name": "tool_web_search", "id": "1"},
        {"type": "result", "name": "tool_web_search", "id": "1", "result": "oil"},
    ]

    result = await handle_direct_node_generation_exception(
        request=_base_request(
            exc=ProviderUnavailableError(
                provider="nvidia",
                reason_code="busy",
                message="busy",
            ),
            state=state,
            tool_call_events=events,
        ),
        dependencies=_base_dependencies(
            build_search_template_fallback=lambda **_kwargs: "Source-backed answer",
        ),
    )

    assert result.response == "Source-backed answer"
    assert result.tool_call_events == events
    assert state["tools_used"] == [{"name": "tool_web_search"}]


@pytest.mark.asyncio
async def test_explicit_provider_web_failure_runs_emergency_search_and_emits_events():
    state = {}
    emitted = []
    emergency_events = [
        {"type": "call", "name": "tool_web_search", "id": "emergency-1"},
        {
            "type": "result",
            "name": "tool_web_search",
            "id": "emergency-1",
            "result": "oil",
        },
    ]

    async def _emergency(**_kwargs):
        return emergency_events

    async def _emit(events, *, push_event):
        emitted.extend(events)
        await push_event({"type": "synthetic"})

    result = await handle_direct_node_generation_exception(
        request=_base_request(
            explicit_user_provider="nvidia",
            state=state,
        ),
        dependencies=_base_dependencies(
            needs_web_search=lambda _query: True,
            emergency_search_fallback_fn=_emergency,
            emit_synthetic_tool_events_fn=_emit,
            build_search_template_fallback=lambda **_kwargs: "Emergency answer",
        ),
    )

    assert result.response == "Emergency answer"
    assert result.tool_call_events == emergency_events
    assert state["tool_call_events"] == emergency_events
    assert state["tools_used"] == [{"name": "tool_web_search"}]
    assert emitted == emergency_events


@pytest.mark.asyncio
async def test_emit_synthetic_tool_events_redacts_public_args():
    emitted = []

    async def push_event(event):
        emitted.append(event)

    await _emit_synthetic_tool_events(
        [
            {
                "type": "call",
                "name": "tool_web_search",
                "id": "emergency-1",
                "args": {
                    "query": "lookup",
                    "connection_ref": "wcn_secret_connection",
                    "page_id": "private_page",
                },
            }
        ],
        push_event=push_event,
    )

    public_args = emitted[0]["content"]["args"]
    assert public_args["query"] == "lookup"
    assert public_args["connection_ref"] == "[redacted]"
    assert public_args["page_id"] == "[redacted]"


@pytest.mark.asyncio
async def test_default_generation_failure_preserves_plain_fallback_when_natural_mode_off(monkeypatch):
    monkeypatch.setattr(settings, "enable_natural_conversation", False)

    result = await handle_direct_node_generation_exception(
        request=_base_request(
            query="hello",
        ),
        dependencies=_base_dependencies(
            build_codebase_analysis_fallback_answer=lambda _query: "",
        ),
    )

    assert result.response == "Xin chao! Toi co the giup gi cho ban?"
