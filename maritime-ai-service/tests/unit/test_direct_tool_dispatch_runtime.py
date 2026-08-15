import json
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.direct_tool_dispatch_runtime import (
    dispatch_direct_tool_call,
    normalize_tool_call,
)
from app.engine.multi_agent.direct_tool_event_metadata import (
    build_tool_result_event_metadata,
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


def test_build_tool_result_event_metadata_classifies_weather_provider_gap():
    metadata = build_tool_result_event_metadata(
        "current_weather",
        json.dumps(
            {
                "status": "error",
                "reason_code": "provider_unconfigured",
                "message": "Weather provider is not configured.",
            }
        ),
    )

    assert metadata == {
        "schema_version": "tool_result_metadata.v1",
        "status": "unavailable",
        "result_kind": "weather",
        "reason_code": "provider_unconfigured",
    }


def test_build_tool_result_event_metadata_preserves_weather_validation_failure():
    metadata = build_tool_result_event_metadata(
        "current_weather",
        json.dumps(
            {
                "status": "validation_failed",
                "missing_fields": "city",
            }
        ),
    )

    assert metadata == {
        "schema_version": "tool_result_metadata.v1",
        "status": "validation_failed",
        "result_kind": "validation",
        "reason_code": "schema_validation",
        "missing_fields": ["city"],
    }


def test_build_tool_result_event_metadata_preserves_terminal_weather_statuses():
    failed_metadata = build_tool_result_event_metadata(
        "current_weather",
        "Tool unavailable",
    )
    blocked_metadata = build_tool_result_event_metadata(
        "current_weather",
        "Sunny",
        policy={"allowed": False, "reason": "not_allowed_by_path_policy"},
    )

    assert failed_metadata == {
        "schema_version": "tool_result_metadata.v1",
        "status": "failed",
        "result_kind": "weather",
        "reason_code": "tool_unavailable",
    }
    assert blocked_metadata == {
        "schema_version": "tool_result_metadata.v1",
        "status": "blocked",
        "result_kind": "policy",
        "policy": {
            "allowed": False,
            "reason": "not_allowed_by_path_policy",
        },
        "reason_code": "not_allowed_by_path_policy",
    }


def test_build_tool_result_event_metadata_classifies_search_no_sources():
    metadata = build_tool_result_event_metadata(
        "tool_web_search",
        "No web results found for this query.",
        sources=[],
    )

    assert metadata == {
        "schema_version": "tool_result_metadata.v1",
        "status": "unavailable",
        "result_kind": "web_sources",
        "reason_code": "no_sources",
        "source_count": 0,
        "domains": [],
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
        "metadata": {
            "schema_version": "tool_result_metadata.v1",
            "status": "completed",
            "result_kind": "text",
        },
    }
    assert captured_invocation["runtime_context_base"] == {"request_id": "req_1"}
    assert captured_invocation["tool_call_id"] == "call_1"
    assert captured_invocation["query_snippet"] == "OpenAI API Reference"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_normalizes_search_args_before_policy_denial():
    events: list[dict] = []
    tool_call_events: list[dict] = []
    tool_call = {
        "id": "call_denied_search",
        "name": "tool_web_search",
        "args": {"q": "Hai Phong"},
    }

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        raise AssertionError("Policy-denied tools must not be invoked")

    result = await dispatch_direct_tool_call(
        tool_call=tool_call,
        tool_round=0,
        tools=[],
        query="thoi tiet Hai Phong hom nay",
        state={
            "_turn_path_decision": {
                "path": "weather_lookup",
                "reason": "unit_test",
                "bind_tools": True,
                "force_tools": False,
                "allow_all_tools": False,
                "allowed_tool_names": [],
            }
        },
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=lambda _tools, _name: None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda name: name == "tool_web_search",
        prefer_official_query_for_known_docs=lambda _args, _query: {
            "query": "thoi tiet Hai Phong hom nay 2026-06-05"
        },
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    expected_args = {"query": "thoi tiet Hai Phong hom nay 2026-06-05"}
    assert result.matched is False
    assert result.tool_args == expected_args
    assert tool_call["args"] == expected_args
    assert events[0]["content"]["args"] == expected_args
    assert tool_call_events[0]["args"] == expected_args
    assert events[1]["content"]["metadata"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_enriches_weather_web_search_args(monkeypatch):
    from app.engine.multi_agent import direct_web_search_policy as policy

    monkeypatch.setattr(policy, "_today_vietnam", lambda: "2026-06-05")

    class FakeTool:
        name = "tool_web_search"

    events: list[dict] = []
    tool_call_events: list[dict] = []
    captured_invocation: dict[str, object] = {}
    tool_call = {
        "id": "call_weather",
        "name": "tool_web_search",
        "args": {"query": "Hai Phong"},
    }

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(tool, args, **kwargs):
        captured_invocation.update({"tool": tool, "args": args, **kwargs})
        return "weather source"

    result = await dispatch_direct_tool_call(
        tool_call=tool_call,
        tool_round=0,
        tools=[FakeTool()],
        query="thoi tiet Hai Phong hom nay the nao",
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=lambda tools, name: tools[0] if name == "tool_web_search" else None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda name: name == "tool_web_search",
        prefer_official_query_for_known_docs=policy._prefer_official_query_for_known_docs,
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    expected_args = {"query": "thoi tiet Hai Phong hom nay 2026-06-05"}
    assert result.tool_args == expected_args
    assert tool_call["args"] == expected_args
    assert captured_invocation["args"] == expected_args
    assert events[0]["content"]["args"] == expected_args
    assert tool_call_events[0]["args"] == expected_args


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_emits_sources_for_web_search_results():
    class FakeTool:
        name = "tool_web_search"

    events: list[dict] = []
    tool_call_events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(_tool, _args, **_kwargs):
        return (
            "**Weather Hải Phòng today**\n"
            "Cloudy and warm.\n"
            "URL: https://weather.example/hai-phong"
        )

    result = await dispatch_direct_tool_call(
        tool_call={
            "id": "call_sources",
            "name": "tool_web_search",
            "args": {"query": "thời tiết Hải Phòng hôm nay"},
        },
        tool_round=0,
        tools=[FakeTool()],
        query="thời tiết Hải Phòng hôm nay",
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=lambda tools, name: tools[0] if name == "tool_web_search" else None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda name: name == "tool_web_search",
        prefer_official_query_for_known_docs=lambda args, _query: args,
        summarize_tool_result_for_stream=lambda _name, value: "Tìm được 1 nguồn",
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert result.matched is True
    assert [event["type"] for event in events] == [
        "tool_call",
        "tool_result",
        "sources",
    ]
    assert events[1]["content"]["metadata"]["status"] == "completed"
    assert events[1]["content"]["metadata"]["result_kind"] == "web_sources"
    assert events[1]["content"]["metadata"]["source_count"] == 1
    assert events[1]["content"]["metadata"]["domains"] == ["weather.example"]
    assert events[2]["details"] == {
        "tool_call_id": "call_sources",
        "tool_name": "tool_web_search",
    }
    assert events[2]["content"] == [
        {
            "title": "Weather Hải Phòng today",
            "content": "Cloudy and warm.",
            "url": "https://weather.example/hai-phong",
            "source_type": "web",
        }
    ]


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_returns_structured_unknown_tool_error():
    events: list[dict] = []
    tool_call_events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        raise AssertionError("Unknown tools must not be invoked")

    result = await dispatch_direct_tool_call(
        tool_call={"id": "", "name": "tool_missing", "args": {"query": "abc"}},
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
    assert events[1]["content"]["metadata"]["status"] == "failed"
    assert events[1]["content"]["metadata"]["reason_code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_redacts_event_args_but_invokes_raw_args():
    class FakeTool:
        name = "tool_demo"

    events: list[dict] = []
    tool_call_events: list[dict] = []
    captured_invocation: dict[str, object] = {}
    raw_args = {
        "query": "run demo",
        "connection_ref": "wcn_secret_connection",
        "page_id": "page_secret",
        "nested": {
            "access_token": "Bearer provider-token",
            "items": [{"image_base64": "raw_image_payload"}],
            "safe": "ok",
        },
    }

    async def push_event(event):
        events.append(event)

    async def invoke_tool_with_runtime(tool, args, **kwargs):
        captured_invocation.update({"tool": tool, "args": args, **kwargs})
        return {"status": "ok"}

    result = await dispatch_direct_tool_call(
        tool_call={"id": "call-sensitive", "name": "tool_demo", "args": raw_args},
        tool_round=0,
        tools=[FakeTool()],
        query="run demo",
        push_event=push_event,
        tool_call_events=tool_call_events,
        get_tool_by_name=lambda tools, name: tools[0] if name == "tool_demo" else None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda _name: False,
        prefer_official_query_for_known_docs=lambda args, _query: args,
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )

    assert result.matched is True
    assert result.tool_args["connection_ref"] == "wcn_secret_connection"
    assert captured_invocation["args"]["connection_ref"] == "wcn_secret_connection"
    public_args = events[0]["content"]["args"]
    assert public_args["query"] == "run demo"
    assert public_args["connection_ref"] == "[redacted]"
    assert public_args["page_id"] == "[redacted]"
    assert public_args["nested"]["access_token"] == "[redacted]"
    assert public_args["nested"]["items"][0]["image_base64"] == "[redacted]"
    assert public_args["nested"]["safe"] == "ok"
    assert tool_call_events[0]["args"] == public_args
    public_payload = json.dumps([events, tool_call_events], ensure_ascii=False)
    assert "wcn_secret_connection" not in public_payload
    assert "page_secret" not in public_payload
    assert "raw_image_payload" not in public_payload
