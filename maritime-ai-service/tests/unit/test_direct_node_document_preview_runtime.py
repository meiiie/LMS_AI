from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_execute_direct_node_document_preview_round_updates_state_and_routing():
    from app.engine.multi_agent.direct_node_document_preview_runtime import (
        execute_direct_node_document_preview_round,
    )

    state: dict = {
        "session_id": "session-preview",
        "organization_id": "org-1",
        "user_id": "user-1",
        "routing_metadata": {},
    }
    ctx = {"request_id": "req-1", "user_role": "teacher"}
    tools = [SimpleNamespace(name="host_action__authoring__preview_lesson_patch")]
    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs["forced_tool_choice"]
        captured["tool_names"] = [tool.name for tool in args[3]]
        return (
            SimpleNamespace(content="Preview sent."),
            ["preview-message"],
            [
                {
                    "type": "host_action",
                    "name": "host_action__authoring__preview_lesson_patch",
                }
            ],
        )

    result = await execute_direct_node_document_preview_round(
        query="tao preview_lesson_patch tu tai lieu vua upload",
        state=state,
        ctx=ctx,
        bus_id="bus-1",
        tools=tools,
        force_tools=True,
        messages=[],
        push_event=lambda _event: None,
        build_visual_tool_runtime_metadata=lambda _state, _query: {"surface": "lms"},
        execute_direct_tool_rounds=fake_execute_direct_tool_rounds,
        extract_direct_response=lambda *_args, **_kwargs: (
            "  Preview sent.  ",
            "preview thinking",
            [],
        ),
        sanitize_preview_response=lambda text, _events: text.strip(),
        debug={"source": "capability_rebind"},
        routing_metadata_key="doc_preview_preflight",
        success_status="executed",
        failure_status="execution_failed",
    )

    assert result is not None
    assert result.response == "Preview sent."
    assert result.thinking_content == "preview thinking"
    assert result.messages == ["preview-message"]
    assert captured["forced_tool_choice"] == "host_action__authoring__preview_lesson_patch"
    assert captured["tool_names"] == ["host_action__authoring__preview_lesson_patch"]
    assert state["tool_call_events"][0]["type"] == "host_action"
    assert state["tools_used"] == [
        {"name": "host_action__authoring__preview_lesson_patch"}
    ]
    assert state["routing_metadata"]["doc_preview_preflight"] == {
        "source": "capability_rebind",
        "status": "executed",
        "tool_count": 1,
        "force_tools": True,
    }


@pytest.mark.asyncio
async def test_execute_direct_node_document_preview_round_records_failure_metadata():
    from app.engine.multi_agent.direct_node_document_preview_runtime import (
        execute_direct_node_document_preview_round,
    )

    state: dict = {"routing_metadata": {}}
    tools = [SimpleNamespace(name="host_action__authoring__preview_lesson_patch")]

    async def fake_execute_direct_tool_rounds(*_args, **_kwargs):
        raise RuntimeError("preview unavailable")

    result = await execute_direct_node_document_preview_round(
        query="tao preview_lesson_patch",
        state=state,
        ctx={"user_role": "teacher"},
        bus_id=None,
        tools=tools,
        force_tools=False,
        messages=[],
        push_event=lambda _event: None,
        build_visual_tool_runtime_metadata=lambda _state, _query: {},
        execute_direct_tool_rounds=fake_execute_direct_tool_rounds,
        extract_direct_response=lambda *_args, **_kwargs: ("", "", []),
        sanitize_preview_response=lambda text, _events: text,
        debug={"source": "capability_rebind"},
        routing_metadata_key="doc_preview_preflight",
        success_status="executed",
        failure_status="execution_failed",
    )

    assert result is None
    assert state["routing_metadata"]["doc_preview_preflight"] == {
        "source": "capability_rebind",
        "status": "execution_failed",
        "error": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_execute_direct_node_document_preview_round_ignores_non_preview_tools():
    from app.engine.multi_agent.direct_node_document_preview_runtime import (
        execute_direct_node_document_preview_round,
    )

    async def fake_execute_direct_tool_rounds(*_args, **_kwargs):
        raise AssertionError("non-preview tools must not execute")

    state: dict = {}
    result = await execute_direct_node_document_preview_round(
        query="tao preview_lesson_patch",
        state=state,
        ctx={},
        bus_id=None,
        tools=[SimpleNamespace(name="tool_web_search")],
        force_tools=True,
        messages=[],
        push_event=lambda _event: None,
        build_visual_tool_runtime_metadata=lambda _state, _query: {},
        execute_direct_tool_rounds=fake_execute_direct_tool_rounds,
        extract_direct_response=lambda *_args, **_kwargs: ("", "", []),
        sanitize_preview_response=lambda text, _events: text,
    )

    assert result is None
    assert state == {}
