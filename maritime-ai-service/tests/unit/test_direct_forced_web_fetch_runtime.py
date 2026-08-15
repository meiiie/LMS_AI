import pytest

from app.engine.multi_agent.direct_forced_web_search_runtime import (
    _build_forced_fetch_response,
    execute_forced_web_search_shortcut,
)


class _FakeTool:
    name = "tool_fetch_url"


def _get_tool_by_name(tools, name):
    for tool in tools:
        if getattr(tool, "name", "") == name:
            return tool
    return None


def _summarize_tool_result(_tool_name, result):
    return result


def test_h1_fetch_response_prefers_structured_h1_over_title():
    response = _build_forced_fetch_response(
        query="Dung web_fetch doc H1 cua https://example.test/about roi tra loi mot dong.",
        result=(
            "# https://example.test/about\n"
            "_(via httpx)_\n\n"
            "Title: Fixture\n\n"
            "H1: About us\n\n"
            "About us\n"
            "Harness fixture."
        ),
        tool_call_events=[],
    )

    assert response == "H1: About us"


@pytest.mark.asyncio
async def test_explicit_web_fetch_runs_deterministically_without_planner_llm():
    events = []
    tool_call_events = []

    async def _push_event(event):
        events.append(event)

    async def _invoke_tool_with_runtime(tool, args, **kwargs):
        assert tool.name == "tool_fetch_url"
        assert args == {"url": "https://www.iana.org/about"}
        assert kwargs["tool_name"] == "tool_fetch_url"
        return (
            "# https://www.iana.org/about\n"
            "_(via httpx)_\n\n"
            "Title: About us\n\n"
            "IANA coordinates identifiers."
        )

    response = await execute_forced_web_search_shortcut(
        query="Dung web_fetch doc H1 cua https://www.iana.org/about roi tra loi mot dong.",
        state={},
        tools=[_FakeTool()],
        messages=[],
        tool_call_events=tool_call_events,
        push_event=_push_event,
        native_tool_messages=False,
        runtime_context_base=None,
        get_tool_by_name=_get_tool_by_name,
        invoke_tool_with_runtime=_invoke_tool_with_runtime,
        summarize_tool_result_for_stream=_summarize_tool_result,
    )

    assert response is not None
    assert response.content == "H1: About us"
    assert [event["type"] for event in events] == [
        "tool_call",
        "tool_result",
        "sources",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
    ]
    assert tool_call_events[0]["name"] == "tool_fetch_url"
    assert tool_call_events[0]["args"] == {"url": "https://www.iana.org/about"}
    assert tool_call_events[1]["type"] == "result"
