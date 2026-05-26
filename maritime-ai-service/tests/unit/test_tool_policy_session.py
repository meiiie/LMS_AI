from types import SimpleNamespace

import pytest


def test_tool_policy_session_records_visible_weather_tool_only():
    from app.engine.multi_agent.tool_policy_session import (
        build_tool_policy_session,
        filter_tools_for_policy_session,
        finalize_tool_policy_visible_tools,
        record_tool_policy_session,
        tool_policy_session_from_state,
    )
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="thoi tiet hom nay bao do",
            needs_weather_lookup=True,
            needs_web_search=True,
        )
    )
    state = {"context": {}}
    tools = [
        SimpleNamespace(name="tool_current_weather"),
        SimpleNamespace(name="tool_web_search"),
        SimpleNamespace(name="tool_pointy_show"),
    ]
    session = build_tool_policy_session(
        decision=decision,
        state=state,
        query="thời tiết hôm nay bao độ",
        user_role="student",
        candidate_tool_names=[tool.name for tool in tools],
    )
    record_tool_policy_session(state, session)

    filtered = filter_tools_for_policy_session(
        tools,
        session,
        tool_name=lambda tool: tool.name,
    )
    finalize_tool_policy_visible_tools(
        state,
        filtered,
        tool_name=lambda tool: tool.name,
    )
    final_session = tool_policy_session_from_state(state)

    assert [tool.name for tool in filtered] == ["tool_current_weather"]
    assert final_session is not None
    assert final_session.path == "weather_lookup"
    assert final_session.visible_tool_names == frozenset({"tool_current_weather"})
    assert final_session.tool_capabilities is not None
    assert final_session.tool_capabilities["tool_current_weather"]["group"] == "weather"
    assert final_session.decision_for("tool_current_weather").allowed is True
    assert final_session.decision_for("tool_web_search").allowed is False


def test_tool_policy_session_denies_lms_authoring_without_connection():
    from app.engine.multi_agent.tool_policy_session import build_tool_policy_session
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="tao bai hoc tu tai lieu",
            looks_document_preview=True,
        )
    )
    session = build_tool_policy_session(
        decision=decision,
        state={"context": {}},
        query="tạo bài học từ tài liệu",
        user_role="teacher",
        candidate_tool_names=[
            "host_action__authoring__preview_lesson_patch",
            "host_action__authoring__apply_lesson_patch",
        ],
    )

    assert session.connection_status is not None
    assert session.connection_status["lms_authoring"]["active"] is False
    assert session.tool_capabilities is not None
    assert (
        session.tool_capabilities["host_action__authoring__apply_lesson_patch"][
            "requires_approval"
        ]
        is True
    )
    assert session.should_expose_tool("host_action__authoring__preview_lesson_patch") is False
    assert "host_action__authoring__apply_lesson_patch" in session.approval_required_tool_names


def test_tool_policy_session_denies_generic_host_action_without_connection():
    from app.engine.multi_agent.tool_policy_session import ToolPolicySession

    session = ToolPolicySession(
        version="tool_policy_session.v1",
        path="host_ui_navigation",
        reason="routing_intent_host_ui_navigation",
        bind_tools=True,
        force_tools=True,
        allow_all_tools=False,
        allowed_tool_prefixes=("host_action__",),
        candidate_tool_names=frozenset({"host_action__dashboard__focus_widget"}),
        connection_status={"host_actions": {"active": False}},
    )

    assert session.should_expose_tool("host_action__dashboard__focus_widget") is False
    decision = session.decision_for("host_action__dashboard__focus_widget")
    assert decision.allowed is False
    assert decision.reason == "not_allowed_by_path_policy"


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_denies_tool_not_visible_in_policy():
    from app.engine.multi_agent.direct_tool_dispatch_runtime import (
        dispatch_direct_tool_call,
    )

    emitted: list[dict] = []
    tool_events: list[dict] = []
    invoked = False
    state = {
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "weather_lookup",
            "reason": "weather_current_conditions_request",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": ["tool_current_weather"],
            "allowed_tool_prefixes": [],
            "forbidden_tool_names": [],
            "forbidden_tool_prefixes": ["tool_pointy_"],
            "candidate_tool_names": ["tool_current_weather", "tool_web_search"],
            "visible_tool_names": ["tool_current_weather"],
            "connection_status": {},
            "approval_required_tool_names": [],
        }
    }

    async def push_event(event):
        emitted.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("denied tool must not be invoked")

    result = await dispatch_direct_tool_call(
        tool_call={
            "id": "tc-denied",
            "name": "tool_web_search",
            "args": {"query": "weather today"},
        },
        tool_round=0,
        tools=[SimpleNamespace(name="tool_web_search")],
        query="thời tiết hôm nay bao độ",
        state=state,
        push_event=push_event,
        tool_call_events=tool_events,
        get_tool_by_name=lambda tools, name: tools[0] if name == "tool_web_search" else None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda name: name == "tool_web_search",
        prefer_official_query_for_known_docs=lambda args, _query: args,
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )

    assert invoked is False
    assert result.matched is False
    assert result.tool_name == "tool_web_search"
    assert "Tool bị chặn bởi chính sách" in result.result
    assert emitted[0]["content"]["policy"]["allowed"] is False
    assert emitted[1]["type"] == "tool_result"
    assert tool_events[0]["policy"]["reason"] == "not_allowed_by_path_policy"
