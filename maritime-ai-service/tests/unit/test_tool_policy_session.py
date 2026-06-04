import json
from types import SimpleNamespace

import pytest


def test_tool_policy_session_records_visible_weather_with_live_lookup():
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

    assert [tool.name for tool in filtered] == [
        "tool_current_weather",
        "tool_web_search",
    ]
    assert final_session is not None
    assert final_session.path == "weather_lookup"
    assert final_session.visible_tool_names == frozenset(
        {"tool_current_weather", "tool_web_search"}
    )
    assert final_session.tool_capabilities is not None
    assert final_session.tool_capabilities["tool_current_weather"]["group"] == "weather"
    assert final_session.decision_for("tool_current_weather").allowed is True
    assert final_session.decision_for("tool_web_search").allowed is True


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


def test_tool_policy_session_records_external_integration_lane():
    from app.engine.multi_agent.tool_policy_session import (
        build_tool_policy_session,
    )
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    )

    state = {
        "context": {},
        "_external_app_action_plan": {
            "version": "external_app_action_plan.v1",
            "status": "ready",
            "kind": "provider_action",
            "provider_slug": "gmail",
            "requested_provider_slugs": ["gmail"],
            "allowed_tool_names": [
                WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
            ],
            "connection_lifecycle": {
                "version": "wiii_connect_connection_lifecycle.v1",
                "provider_slug": "gmail",
                "status": "expired",
                "reason": "oauth_token_expired",
                "connection_present": True,
                "ready_to_execute_action": False,
                "account_label": "private@example.test",
                "access_token": "raw-provider-token",
            },
        },
        "_external_app_integration_lane": {
            "version": "external_app_integration_lane.v1",
            "status": "ready",
            "executor": "provider_worker",
            "provider_slug": "gmail",
            "requested_provider_slugs": ["gmail"],
            "visible_tool_names": [
                WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
            ],
            "ui_activity_title": "Working with your gmail connection",
        },
    }
    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="doc gmail moi nhat",
            needs_external_app_action=True,
        )
    )

    session = build_tool_policy_session(
        decision=decision,
        state=state,
        query="đọc Gmail mới nhất",
        user_role="student",
        candidate_tool_names=[
            WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        ],
    )

    assert session.external_app_action_plan is not None
    assert session.external_app_action_plan["provider_slug"] == "gmail"
    assert session.external_app_action_plan["requested_provider_slugs"] == ["gmail"]
    assert session.external_app_action_plan["connection_lifecycle"]["status"] == (
        "expired"
    )
    assert "account_label" not in session.external_app_action_plan["connection_lifecycle"]
    assert "access_token" not in session.to_metadata()["external_app_action_plan"][
        "connection_lifecycle"
    ]
    assert session.external_app_integration_lane is not None
    assert session.external_app_integration_lane["executor"] == "provider_worker"
    assert session.external_app_integration_lane["requested_provider_slugs"] == [
        "gmail"
    ]
    assert session.external_app_integration_lane["visible_tool_names"] == [
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    ]


def test_tool_policy_session_denies_diagnostic_tool_surface_even_when_allow_all():
    from app.engine.multi_agent.tool_policy_session import build_tool_policy_session
    from app.engine.multi_agent.turn_path_governor import TurnPathDecision
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
    )

    session = build_tool_policy_session(
        decision=TurnPathDecision(
            path="external_app_action",
            reason="regression_allow_all_external_app_action",
            bind_tools=True,
            allow_all_tools=True,
        ),
        state={"context": {}},
        query="doc gmail",
        user_role="student",
        candidate_tool_names=[WIII_CONNECT_EXECUTE_ACTION_TOOL],
    )

    assert session.tool_capabilities is not None
    assert session.tool_capabilities[WIII_CONNECT_EXECUTE_ACTION_TOOL][
        "surface_scopes"
    ] == ["diagnostic"]
    assert session.should_expose_tool(WIII_CONNECT_EXECUTE_ACTION_TOOL) is False
    decision = session.decision_for(WIII_CONNECT_EXECUTE_ACTION_TOOL)
    assert decision.allowed is False
    assert decision.reason == "surface_scope_not_allowed"


def test_tool_policy_session_denies_diagnostic_tool_from_minimal_metadata():
    from app.engine.multi_agent.tool_policy_session import ToolPolicySession
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
    )

    session = ToolPolicySession.from_metadata(
        {
            "version": "tool_policy_session.v1",
            "path": "external_app_action",
            "reason": "legacy_minimal_policy_metadata",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": True,
            "candidate_tool_names": [WIII_CONNECT_EXECUTE_ACTION_TOOL],
            "visible_tool_names": [WIII_CONNECT_EXECUTE_ACTION_TOOL],
        }
    )

    assert session.tool_capabilities == {}
    assert session.should_expose_tool(WIII_CONNECT_EXECUTE_ACTION_TOOL) is False
    decision = session.decision_for(WIII_CONNECT_EXECUTE_ACTION_TOOL)
    assert decision.allowed is False
    assert decision.reason == "surface_scope_not_allowed"


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


@pytest.mark.asyncio
async def test_dispatch_direct_tool_call_redacts_policy_denied_sensitive_args():
    from app.engine.multi_agent.direct_tool_dispatch_runtime import (
        dispatch_direct_tool_call,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
    )

    emitted: list[dict] = []
    tool_events: list[dict] = []
    invoked = False
    state = {
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "external_app_action",
            "reason": "external_app_action_route",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": True,
            "candidate_tool_names": [WIII_CONNECT_EXECUTE_ACTION_TOOL],
            "visible_tool_names": [WIII_CONNECT_EXECUTE_ACTION_TOOL],
            "connection_status": {},
            "approval_required_tool_names": [],
        }
    }
    raw_args = {
        "provider_slug": "facebook",
        "connection_ref": "wcn_secret_connection",
        "page_id": "page_secret",
        "image_base64": "raw_image_payload",
        "nested": {"provider_payload": {"access_token": "Bearer provider-token"}},
        "safe": "ok",
    }

    async def push_event(event):
        emitted.append(event)

    async def invoke_tool_with_runtime(*_args, **_kwargs):
        nonlocal invoked
        invoked = True
        raise AssertionError("denied tool must not be invoked")

    result = await dispatch_direct_tool_call(
        tool_call={
            "id": "tc-denied-sensitive",
            "name": WIII_CONNECT_EXECUTE_ACTION_TOOL,
            "args": raw_args,
        },
        tool_round=0,
        tools=[SimpleNamespace(name=WIII_CONNECT_EXECUTE_ACTION_TOOL)],
        query="post to facebook",
        state=state,
        push_event=push_event,
        tool_call_events=tool_events,
        get_tool_by_name=lambda tools, name: tools[0]
        if name == WIII_CONNECT_EXECUTE_ACTION_TOOL
        else None,
        invoke_tool_with_runtime=invoke_tool_with_runtime,
        runtime_context_base=None,
        is_search_tool_name=lambda _name: False,
        prefer_official_query_for_known_docs=lambda args, _query: args,
        summarize_tool_result_for_stream=lambda _name, value: value,
        logger_obj=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )

    assert invoked is False
    assert result.matched is False
    assert result.tool_args["connection_ref"] == "wcn_secret_connection"
    assert emitted[0]["content"]["policy"]["reason"] == "surface_scope_not_allowed"
    public_args = emitted[0]["content"]["args"]
    assert public_args["provider_slug"] == "facebook"
    assert public_args["safe"] == "ok"
    assert public_args["connection_ref"] == "[redacted]"
    assert public_args["page_id"] == "[redacted]"
    assert public_args["image_base64"] == "[redacted]"
    assert public_args["nested"]["provider_payload"] == "[redacted]"
    assert tool_events[0]["args"] == public_args
    public_payload = json.dumps([emitted, tool_events], ensure_ascii=False)
    assert "wcn_secret_connection" not in public_payload
    assert "page_secret" not in public_payload
    assert "raw_image_payload" not in public_payload
    assert "provider-token" not in public_payload
