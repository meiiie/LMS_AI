from types import SimpleNamespace

import pytest

from app.engine.multi_agent.direct_tool_dispatch_runtime import (
    dispatch_direct_tool_call,
    normalize_tool_call,
)


def test_normalize_tool_call_preserves_dicts_and_provider_objects():
    raw = {"id": "call_1", "name": "tool_demo", "args": {"query": "abc"}}
    provider_call = SimpleNamespace(
        id="call_2",
        name="tool_other",
        arguments={"query": "xyz"},
    )

    assert normalize_tool_call(raw) is raw
    assert normalize_tool_call(provider_call) == {
        "id": "call_2",
        "name": "tool_other",
        "args": {"query": "xyz"},
    }


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_emits_stable_call_and_result_events():
    class FakeTool:
        name = "tool_web_search"

    events: list[dict] = []
    tool_call_events: list[dict] = []
    captured_invocation: dict[str, object] = {}
    tool_call = {
        "id": "call_1",
        "name": "tool_web_search",
        "args": {"query": "openai docs"},
    }

    async def push_event(event):
        events.append(event)

    def get_tool_by_name(tools, name):
        return next((tool for tool in tools if tool.name == name), None)

    async def invoke_tool_with_runtime(tool, args, **kwargs):
        captured_invocation.update({"tool": tool, "args": args, **kwargs})
        return {"answer": "ok"}

    result = await dispatch_direct_tool_call(
        tool_call=tool_call,
        tool_round=0,
        tools=[FakeTool()],
        query="Tìm nguồn chính thức OpenAI",
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=get_tool_by_name,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base={"request_id": "req_1"},
        is_search_tool_name=lambda name: name == "tool_web_search",
        prefer_official_query_for_known_docs=lambda args, _query: {
            **args,
            "query": "OpenAI API Reference",
        },
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert result.matched is True
    assert result.tool_call_id == "call_1"
    assert result.tool_name == "tool_web_search"
    assert result.tool_args == {"query": "OpenAI API Reference"}
    assert result.result == {"answer": "ok"}
    assert tool_call["args"] == {"query": "OpenAI API Reference"}
    assert tool_call_events == [
        {
            "type": "call",
            "name": "tool_web_search",
            "args": {"query": "OpenAI API Reference"},
            "id": "call_1",
        }
    ]
    assert [event["type"] for event in events] == ["tool_call", "tool_result"]
    assert events[0]["content"] == {
        "name": "tool_web_search",
        "args": {"query": "OpenAI API Reference"},
        "id": "call_1",
    }
    assert events[1]["content"] == {
        "name": "tool_web_search",
        "result": {"answer": "ok"},
        "id": "call_1",
    }
    assert captured_invocation["runtime_context_base"] == {"request_id": "req_1"}
    assert captured_invocation["tool_call_id"] == "call_1"
    assert captured_invocation["query_snippet"] == "OpenAI API Reference"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_returns_structured_unknown_tool_error():
    events: list[dict] = []
    tool_call_events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        raise AssertionError("Unknown tools must not be invoked")

    result = await dispatch_direct_tool_call(
        tool_call={"name": "tool_missing", "args": {"query": "abc"}},
        tool_round=3,
        tools=[],
        query="abc",
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=lambda _tools, _name: None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda _name: False,
        prefer_official_query_for_known_docs=lambda args, _query: args,
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert result.matched is False
    assert result.tool_call_id == "tc_3"
    assert "không tìm thấy tool `tool_missing`" in result.result
    assert tool_call_events == [
        {
            "type": "call",
            "name": "tool_missing",
            "args": {"query": "abc"},
            "id": "tc_3",
        }
    ]
    assert events[1]["content"]["result"] == result.result
