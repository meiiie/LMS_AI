import logging
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.direct_tool_dispatch_runtime import (
    DirectToolDispatchResult,
    normalize_tool_call,
)
from app.engine.multi_agent.direct_tool_post_dispatch_runtime import (
    DirectToolPostDispatchState,
)
from app.engine.multi_agent.direct_tool_round_execution_runtime import (
    execute_direct_tool_round,
)


@pytest.mark.asyncio
async def test_execute_direct_tool_round_dispatches_and_commits_visuals() -> None:
    llm_response = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(id="call-1", name="tool_demo", arguments={"query": "x"})
        ]
    )
    messages: list = []
    tool_call_events: list[dict] = []
    captured: dict = {}

    async def push_event(event: dict) -> None:
        return None

    async def dispatch_tool_call(**kwargs):
        captured["dispatch_tool_call"] = kwargs["tool_call"]
        return DirectToolDispatchResult(
            tool_call_id="call-1",
            tool_name="tool_demo",
            tool_args={"query": "x"},
            result="demo result",
            matched=True,
        )

    async def process_post_dispatch(**kwargs):
        captured["post_tool_name"] = kwargs["tool_name"]
        captured["post_active_visuals"] = kwargs["active_visual_session_ids"]
        kwargs["visual_session_ids"].append("vs-1")
        messages.append({"role": "tool", "content": kwargs["result"]})
        tool_call_events.append({"type": "result", "name": kwargs["tool_name"]})
        return DirectToolPostDispatchState(
            result=kwargs["result"],
            active_visual_session_ids=["vs-1"],
            visual_emitted_any=True,
        )

    async def emit_visual_commit_events(**kwargs):
        captured["committed_visuals"] = kwargs["visual_session_ids"]

    result = await execute_direct_tool_round(
        llm_response=llm_response,
        tool_round=0,
        tools=[object()],
        query="demo",
        state={},
        messages=messages,
        tool_call_events=tool_call_events,
        push_event=push_event,
        native_tool_messages=False,
        visual_emitted_any=False,
        runtime_context_base={"request_id": "req-1"},
        handoffs_enabled=True,
        get_tool_by_name=lambda tools, name: object(),
        invoke_tool_with_runtime=lambda *args, **kwargs: None,
        is_search_tool_name=lambda name: False,
        prefer_official_query_for_known_docs=lambda args, query: args,
        summarize_tool_result_for_stream=lambda name, value: value,
        maybe_emit_host_action_event=lambda **kwargs: None,
        maybe_emit_visual_event=lambda **kwargs: ([], []),
        emit_visual_commit_events=emit_visual_commit_events,
        build_direct_tool_reflection=lambda state, name, value: "",
        push_status_only_progress=lambda *args, **kwargs: None,
        build_tool_result_message=lambda content, **kwargs: content,
        normalize_tool_call=normalize_tool_call,
        infer_direct_reasoning_cue=lambda query, state, names: f"cue:{','.join(names)}",
        collect_active_visual_session_ids=lambda state: ["active-before"],
        dispatch_direct_tool_call=dispatch_tool_call,
        process_direct_tool_post_dispatch=process_post_dispatch,
        logger_obj=logging.getLogger(__name__),
    )

    assert result.round_tool_names == ["tool_demo"]
    assert result.round_cue == "cue:tool_demo"
    assert result.visual_emitted_any is True
    assert messages[0] is llm_response
    assert messages[1] == {"role": "tool", "content": "demo result"}
    assert captured["dispatch_tool_call"] == {
        "id": "call-1",
        "name": "tool_demo",
        "args": {"query": "x"},
    }
    assert captured["post_tool_name"] == "tool_demo"
    assert captured["post_active_visuals"] == ["active-before"]
    assert captured["committed_visuals"] == ["vs-1"]


@pytest.mark.asyncio
async def test_execute_direct_tool_round_preserves_existing_visual_emission_state() -> None:
    llm_response = SimpleNamespace(tool_calls=[{"id": "call-1", "name": "tool_demo"}])

    async def push_event(event: dict) -> None:
        return None

    async def dispatch_tool_call(**kwargs):
        return DirectToolDispatchResult(
            tool_call_id="call-1",
            tool_name="tool_demo",
            tool_args={},
            result="demo result",
            matched=True,
        )

    async def process_post_dispatch(**kwargs):
        return DirectToolPostDispatchState(
            result=kwargs["result"],
            active_visual_session_ids=[],
            visual_emitted_any=kwargs["visual_emitted_any"],
        )

    async def emit_visual_commit_events(**kwargs):
        return None

    result = await execute_direct_tool_round(
        llm_response=llm_response,
        tool_round=1,
        tools=[object()],
        query="demo",
        state={},
        messages=[],
        tool_call_events=[],
        push_event=push_event,
        native_tool_messages=False,
        visual_emitted_any=True,
        runtime_context_base={},
        handoffs_enabled=True,
        get_tool_by_name=lambda tools, name: object(),
        invoke_tool_with_runtime=lambda *args, **kwargs: None,
        is_search_tool_name=lambda name: False,
        prefer_official_query_for_known_docs=lambda args, query: args,
        summarize_tool_result_for_stream=lambda name, value: value,
        maybe_emit_host_action_event=lambda **kwargs: None,
        maybe_emit_visual_event=lambda **kwargs: ([], []),
        emit_visual_commit_events=emit_visual_commit_events,
        build_direct_tool_reflection=lambda state, name, value: "",
        push_status_only_progress=lambda *args, **kwargs: None,
        build_tool_result_message=lambda content, **kwargs: content,
        normalize_tool_call=normalize_tool_call,
        infer_direct_reasoning_cue=lambda query, state, names: "cue",
        collect_active_visual_session_ids=lambda state: [],
        dispatch_direct_tool_call=dispatch_tool_call,
        process_direct_tool_post_dispatch=process_post_dispatch,
        logger_obj=logging.getLogger(__name__),
    )

    assert result.visual_emitted_any is True
