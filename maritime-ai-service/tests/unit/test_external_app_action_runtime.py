from types import SimpleNamespace


FACEBOOK_APPLY_ALLOWLIST = {
    "facebook": ("FACEBOOK_CREATE_POST", "FACEBOOK_CREATE_PHOTO_POST")
}


def test_external_app_action_plan_selects_facebook_direct_apply():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai viet len Facebook giup toi",
        state={
            "context": {
                "host_context": {
                    "page": {
                        "metadata": {
                            "wiii_connect": {
                                "provider_slug": "facebook",
                                "status": "connected",
                                "connection_count": 1,
                                "active_connection_count": 1,
                                "connection_state": "connected",
                            }
                        }
                    }
                }
            }
        },
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider=FACEBOOK_APPLY_ALLOWLIST,
    )

    assert plan.ready is True
    assert plan.kind == "facebook_post_direct_apply"
    assert plan.provider_slug == "facebook"
    assert plan.action_slug == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION
    assert plan.forced_tool_name == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    assert plan.allowed_tool_names == (WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,)


def test_external_app_integration_lane_prefers_backend_owner_for_duplicate_direct_tool():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
        select_tools_for_external_app_integration_lane,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai viet len Facebook giup toi",
        state={"context": {}},
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider=FACEBOOK_APPLY_ALLOWLIST,
    )
    lane = external_app_integration_lane_from_plan(plan)
    host_tool = SimpleNamespace(
        name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        wiii_connect_action_owner="host_action_bridge",
    )
    backend_tool = SimpleNamespace(
        name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        wiii_connect_action_owner="backend_gateway",
    )

    selected, forced = select_tools_for_external_app_integration_lane(
        tools=[host_tool, backend_tool],
        lane=lane,
    )

    assert selected == [backend_tool]
    assert forced == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL


def test_external_app_integration_lane_blocks_closed_for_blocked_plan():
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
        select_tools_for_external_app_integration_lane,
    )
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail tu giao vien giup toi",
        state={"context": {}},
        ready_provider_slugs=("gmail",),
    )
    lane = external_app_integration_lane_from_plan(plan)

    selected, forced = select_tools_for_external_app_integration_lane(
        tools=[SimpleNamespace(name="tool_web_search")],
        lane=lane,
    )

    assert plan.status == "blocked"
    assert lane.status == "blocked"
    assert selected == []
    assert forced is None


def test_external_app_action_plan_blocks_facebook_without_agent_ready_provider():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai Facebook bat ky di",
        state={"context": {}},
        ready_provider_slugs=(),
    )

    assert plan.status == "blocked"
    assert plan.kind == "facebook_post_direct_apply"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.provider_slug == "facebook"


def test_external_app_action_plan_blocks_facebook_without_visible_post_action():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai Facebook bat ky di",
        state={"context": {}},
        ready_provider_slugs=("facebook",),
    )

    assert plan.status == "blocked"
    assert plan.kind == "facebook_post_direct_apply"
    assert plan.reason == "no_agent_ready_actions"
    assert plan.provider_slug == "facebook"
    assert "effective action inventory" in plan.unavailable_answer


def test_external_app_action_plan_blocks_providerless_facebook_continuation():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query='dang bai: "xin chao minh la AI" la duoc',
        state={
            "context": {},
            "messages": [
                {
                    "role": "user",
                    "content": "Wiii co the dang bai len Facebook khong?",
                },
                {
                    "role": "assistant",
                    "content": "Facebook chua agent-ready trong Wiii Connect.",
                },
            ],
        },
        ready_provider_slugs=(),
    )

    assert plan.status == "blocked"
    assert plan.kind == "facebook_post_direct_apply"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.provider_slug == "facebook"
    assert plan.requested_provider_slugs == ("facebook",)


def test_external_app_action_plan_selects_generic_provider_tools():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        WIII_CONNECT_LIST_ACTIONS_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail tu giao vien giup toi",
        state={"context": {}},
        ready_provider_slugs=("gmail",),
        action_allowlists_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    assert plan.ready is True
    assert plan.kind == "provider_action"
    assert plan.provider_slug == "gmail"
    assert plan.requested_provider_slugs == ("gmail",)
    assert plan.allowed_tool_names == (WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,)
    assert plan.action_allowlists_by_provider == {
        "gmail": ("GMAIL_FETCH_EMAILS",)
    }
    assert plan.to_metadata()["action_allowlists_by_provider"] == {
        "gmail": ["GMAIL_FETCH_EMAILS"]
    }


def test_external_app_action_plan_blocks_generic_provider_without_visible_action():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail tu giao vien giup toi",
        state={"context": {}},
        ready_provider_slugs=("gmail",),
    )

    assert plan.status == "blocked"
    assert plan.kind == "provider_action"
    assert plan.provider_slug == "gmail"
    assert plan.reason == "no_agent_ready_actions"
    assert plan.action_allowlists_by_provider == {}
    assert "action hiệu lực" in plan.unavailable_answer


def test_external_app_action_plan_blocks_providerless_generic_provider_continuation():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="doc email moi nhat di",
        state={
            "context": {},
            "messages": [
                {
                    "role": "user",
                    "content": "Wiii co the doc Gmail khong?",
                },
                {
                    "role": "assistant",
                    "content": "Gmail chua agent-ready trong Wiii Connect.",
                },
            ],
        },
        ready_provider_slugs=(),
    )

    assert plan.status == "blocked"
    assert plan.kind == "provider_action"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.provider_slug == "gmail"
    assert plan.requested_provider_slugs == ("gmail",)
    assert "Gmail" in plan.unavailable_answer


def test_external_app_action_plan_blocks_missing_provider_target():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="dang bai len mang xa hoi di",
        state={"context": {}, "messages": []},
        ready_provider_slugs=(),
    )

    assert plan.status == "blocked"
    assert plan.kind == "provider_action"
    assert plan.reason == "missing_provider_target"
    assert plan.provider_slug == ""
    assert plan.requested_provider_slugs == ()
    assert "provider" in plan.unavailable_answer
    assert "Wiii Connect" in plan.unavailable_answer


def test_external_app_action_plan_round_trips_effective_inventory():
    from app.engine.multi_agent.external_app_action_runtime import (
        external_app_action_plan_from_state,
        record_external_app_action_plan,
        resolve_external_app_action_plan,
    )

    state = {}
    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail tu giao vien giup toi",
        state=state,
        ready_provider_slugs=("gmail",),
        action_allowlists_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    record_external_app_action_plan(state, plan)
    restored = external_app_action_plan_from_state(state)

    assert restored is not None
    assert restored.kind == "provider_action"
    assert restored.provider_slug == "gmail"
    assert restored.requested_provider_slugs == ("gmail",)
    assert restored.action_allowlists_by_provider == {
        "gmail": ("GMAIL_FETCH_EMAILS",)
    }


def test_external_app_action_plan_blocks_requested_provider_when_only_other_provider_ready():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail moi nhat giup toi",
        state={"context": {}},
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider={"facebook": ("FACEBOOK_CREATE_POST",)},
    )

    assert plan.status == "blocked"
    assert plan.kind == "provider_action"
    assert plan.provider_slug == "gmail"
    assert plan.requested_provider_slugs == ("gmail",)
    assert plan.ready_provider_slugs == ("facebook",)
    assert plan.allowed_tool_names == ()
    assert plan.action_allowlists_by_provider == {}
    assert "Gmail" in plan.unavailable_answer


def test_external_app_action_plan_blocks_with_provider_status_snapshot(monkeypatch):
    from app.engine.multi_agent import external_app_action_runtime as module

    monkeypatch.setattr(
        module,
        "build_wiii_connect_provider_status_answer",
        lambda state, *, provider_slug: (
            "Wiii thấy Gmail đã có kết nối active, nhưng agent chưa được phép dùng provider này "
            "(lý do: connected_provider_not_agent_ready)."
        ),
    )

    plan = module.resolve_external_app_action_plan(
        query="Wiii đọc Gmail mới nhất giúp tôi",
        state={"context": {"user_id": "user-1", "organization_id": "org-1"}},
        ready_provider_slugs=(),
    )

    assert plan.status == "blocked"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.provider_slug == "gmail"
    assert "connected_provider_not_agent_ready" in plan.unavailable_answer
    assert "không mở action schema" in plan.unavailable_answer


def test_external_app_action_plan_records_sanitized_lifecycle_for_blocked_provider(
    monkeypatch,
):
    from app.engine.multi_agent import external_app_action_runtime as module

    monkeypatch.setattr(
        module,
        "build_wiii_connect_provider_status_answer",
        lambda state, *, provider_slug: (
            "Gmail is connected but the provider is not agent-ready."
        ),
    )
    monkeypatch.setattr(
        module,
        "wiii_connect_provider_connection_lifecycle_from_state",
        lambda state, provider_slug: {
            "version": "wiii_connect_connection_lifecycle.v1",
            "provider_slug": provider_slug,
            "status": "expired",
            "reason": "oauth_token_expired",
            "connection_present": True,
            "ready_to_execute_action": False,
            "required_next": ["reconnect_provider_account"],
            "account_label": "private@example.test",
            "access_token": "raw-provider-token",
        },
    )

    plan = module.resolve_external_app_action_plan(
        query="Wiii doc Gmail moi nhat giup toi",
        state={"context": {"user_id": "user-1", "organization_id": "org-1"}},
        ready_provider_slugs=(),
    )
    metadata = plan.to_metadata()

    assert plan.status == "blocked"
    assert plan.reason == "provider_not_agent_ready"
    assert plan.connection_lifecycle["status"] == "expired"
    assert metadata["connection_lifecycle"] == {
        "version": "wiii_connect_connection_lifecycle.v1",
        "provider_slug": "gmail",
        "status": "expired",
        "reason": "oauth_token_expired",
        "connection_present": True,
        "ready_to_execute_action": False,
        "required_next": ["reconnect_provider_account"],
    }
    assert "account_label" not in metadata["connection_lifecycle"]
    assert "access_token" not in metadata["connection_lifecycle"]


def test_external_app_action_plan_blocks_ambiguous_provider_target():
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail roi tao issue GitHub giup toi",
        state={"context": {}},
        ready_provider_slugs=("gmail", "github"),
        action_allowlists_by_provider={
            "gmail": ("GMAIL_FETCH_EMAILS",),
            "github": ("GITHUB_CREATE_ISSUE",),
        },
    )

    assert plan.status == "blocked"
    assert plan.kind == "provider_action"
    assert plan.provider_slug == ""
    assert set(plan.requested_provider_slugs) == {"gmail", "github"}
    assert plan.reason == "ambiguous_provider_target"


def test_external_app_action_plan_forces_only_planned_tool():
    from app.engine.multi_agent.external_app_action_runtime import (
        force_tools_for_external_app_action_plan,
        resolve_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii post len Facebook giup toi",
        state={
            "context": {
                "host_context": {
                    "page": {
                        "metadata": {
                            "wiii_connect": {
                                "provider_slug": "facebook",
                                "status": "connected",
                                "connection_count": 1,
                                "active_connection_count": 1,
                            }
                        }
                    }
                }
            }
        },
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider=FACEBOOK_APPLY_ALLOWLIST,
    )
    tools = [
        SimpleNamespace(name="tool_web_search"),
        SimpleNamespace(name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL),
    ]

    selected, forced = force_tools_for_external_app_action_plan(
        tools=tools,
        plan=plan,
    )

    assert [tool.name for tool in selected] == [
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    ]
    assert forced == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL


def test_external_app_integration_lane_maps_facebook_to_specialized_tool():
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
    )
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai Facebook bat ky di",
        state={},
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider=FACEBOOK_APPLY_ALLOWLIST,
    )

    lane = external_app_integration_lane_from_plan(plan)

    assert lane.status == "ready"
    assert lane.executor == "specialized_direct_tool"
    assert lane.provider_slug == "facebook"
    assert lane.visible_tool_names == (WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,)
    assert lane.forced_tool_name == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    assert lane.to_metadata()["ui_activity_title"] == (
        "Working with your Facebook connection"
    )


def test_external_app_integration_lane_maps_generic_provider_to_worker_tools():
    from app.engine.multi_agent.external_app_integration_lane import (
        external_app_integration_lane_from_plan,
    )
    from app.engine.multi_agent.external_app_action_runtime import (
        resolve_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        WIII_CONNECT_LIST_ACTIONS_TOOL,
    )

    plan = resolve_external_app_action_plan(
        query="Wiii doc Gmail moi nhat giup toi",
        state={},
        ready_provider_slugs=("gmail",),
        action_allowlists_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )

    lane = external_app_integration_lane_from_plan(plan)

    assert lane.status == "ready"
    assert lane.executor == "provider_worker"
    assert lane.visible_tool_names == (
        WIII_CONNECT_LIST_ACTIONS_TOOL,
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    )
    assert lane.forced_tool_name == ""
    assert lane.action_allowlists_by_provider == {
        "gmail": ("GMAIL_FETCH_EMAILS",)
    }


def test_prepare_external_app_action_turn_preempts_blocked_facebook_request():
    from app.engine.multi_agent.external_app_action_runtime import (
        prepare_external_app_action_turn,
    )

    state = {"context": {}}

    def build_assistant_message(content: str, **kwargs):
        return {"content": content, "native_tool_messages": kwargs["native_tool_messages"]}

    preparation = prepare_external_app_action_turn(
        query="Wiii dang mot bai Facebook bat ky di",
        state=state,
        tools=[SimpleNamespace(name="tool_web_search")],
        forced_tool_choice="tool_web_search",
        native_tool_messages=True,
        build_assistant_message=build_assistant_message,
    )

    assert preparation.preempted is True
    assert preparation.preflight_response["native_tool_messages"] is True
    assert "Facebook" in preparation.preflight_response["content"]
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert state["_external_app_action_plan"]["forced_tool_name"] == ""
    assert state["_external_app_action_plan"]["allowed_tool_names"] == []
    assert state["_external_app_integration_lane"]["executor"] == (
        "specialized_direct_tool"
    )


def test_prepare_external_app_action_turn_forces_ready_facebook_tool():
    from app.engine.multi_agent.external_app_action_runtime import (
        prepare_external_app_action_turn,
        resolve_external_app_action_plan,
        record_external_app_action_plan,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    state = {}
    plan = resolve_external_app_action_plan(
        query="Wiii dang mot bai Facebook bat ky di",
        state=state,
        ready_provider_slugs=("facebook",),
        action_allowlists_by_provider=FACEBOOK_APPLY_ALLOWLIST,
    )
    record_external_app_action_plan(state, plan)

    preparation = prepare_external_app_action_turn(
        query="Wiii dang mot bai Facebook bat ky di",
        state=state,
        tools=[
            SimpleNamespace(name="tool_web_search"),
            SimpleNamespace(name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL),
        ],
        forced_tool_choice="tool_web_search",
        native_tool_messages=True,
        build_assistant_message=lambda content, **_kwargs: {"content": content},
    )

    assert preparation.preempted is False
    assert preparation.integration_lane.executor == "specialized_direct_tool"
    assert preparation.forced_tool_choice == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    assert [tool.name for tool in preparation.tools] == [
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
    ]
