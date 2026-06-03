def test_tool_capability_registry_records_policy_groups():
    from app.engine.tools.tool_capability_registry import (
        lookup_tool_capability,
        tool_capability_metadata_for_names,
    )

    weather = lookup_tool_capability("tool_current_weather")
    assert weather is not None
    assert weather.group == "weather"
    assert weather.required_connection == "weather"
    assert weather.expose_when_connection_inactive is True

    pointy = lookup_tool_capability("tool_pointy_show")
    assert pointy is not None
    assert pointy.group == "pointy"
    assert pointy.permission == "host_control"

    visual = lookup_tool_capability("tool_create_visual_code")
    assert visual is not None
    assert visual.group == "visual"
    assert "code_studio" in visual.surface_scopes

    metadata = tool_capability_metadata_for_names(
        {
            "tool_current_weather",
            "tool_pointy_show",
            "tool_create_visual_code",
            "unknown_tool",
        }
    )
    assert set(metadata) == {
        "tool_current_weather",
        "tool_pointy_show",
        "tool_create_visual_code",
    }


def test_tool_capability_registry_records_product_search_tools():
    from app.engine.tools.tool_capability_registry import (
        PRODUCT_SEARCH_TOOL_NAMES,
        lookup_tool_capability,
        tool_capability_metadata_for_names,
    )

    assert "tool_search_websosanh" in PRODUCT_SEARCH_TOOL_NAMES
    search_tool = lookup_tool_capability("tool_search_websosanh")
    assert search_tool is not None
    assert search_tool.group == "product_search"
    assert search_tool.surface_scopes == ("product_search",)

    report_tool = lookup_tool_capability("tool_generate_product_report")
    assert report_tool is not None
    assert report_tool.group == "product_search"
    assert report_tool.permission == "write"

    metadata = tool_capability_metadata_for_names(
        {"tool_search_websosanh", "tool_generate_product_report"}
    )
    assert metadata["tool_search_websosanh"]["group"] == "product_search"
    assert metadata["tool_generate_product_report"]["permission"] == "write"


def test_tool_capability_registry_handles_dynamic_host_actions():
    from app.engine.tools.tool_capability_registry import (
        host_action_name_from_tool_name,
        host_action_requires_approval_token,
        host_action_tool_name,
        lookup_tool_capability,
        tool_requires_inactive_connection,
    )

    preview_tool_name = host_action_tool_name("authoring.preview_lesson_patch")
    assert preview_tool_name == "host_action__authoring__preview_lesson_patch"
    assert host_action_name_from_tool_name(preview_tool_name) == "authoring.preview_lesson_patch"

    preview = lookup_tool_capability(preview_tool_name)
    assert preview is not None
    assert preview.group == "lms_authoring"
    assert preview.required_connection == "lms_authoring"
    assert preview.requires_approval is False

    apply_tool_name = host_action_tool_name("authoring.apply_lesson_patch")
    assert host_action_requires_approval_token("authoring.apply_lesson_patch") is True
    apply_tool = lookup_tool_capability(apply_tool_name)
    assert apply_tool is not None
    assert apply_tool.mutates_state is True
    assert apply_tool.requires_approval is True

    generic_host_tool = lookup_tool_capability("host_action__dashboard__focus_widget")
    assert generic_host_tool is not None
    assert generic_host_tool.group == "host_action"
    assert generic_host_tool.required_connection == "host_actions"
    assert tool_requires_inactive_connection(
        "host_action__dashboard__focus_widget",
        {"host_actions": {"active": False}},
    ) is True


def test_wiii_connect_facebook_direct_apply_requires_agent_ready_connection():
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        WIII_CONNECT_LIST_ACTIONS_TOOL,
        lookup_tool_capability,
        tool_requires_inactive_connection,
    )

    capability = lookup_tool_capability(WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL)
    assert capability is not None
    assert capability.required_connection == "facebook"
    assert capability.requires_agent_ready is True

    assert tool_requires_inactive_connection(
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        {"facebook": {"active": True, "agent_ready": False}},
    ) is True
    assert tool_requires_inactive_connection(
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        {"facebook": {"active": True, "agent_ready": True}},
    ) is False

    delegate = lookup_tool_capability(WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL)
    assert delegate is not None
    assert delegate.group == "external_app_action"
    assert delegate.permission == "write"
    assert delegate.mutates_state is True
    assert delegate.surface_scopes == ("direct_chat",)

    list_actions = lookup_tool_capability(WIII_CONNECT_LIST_ACTIONS_TOOL)
    assert list_actions is not None
    assert list_actions.surface_scopes == ("direct_chat",)

    execute_action = lookup_tool_capability(WIII_CONNECT_EXECUTE_ACTION_TOOL)
    assert execute_action is not None
    assert execute_action.surface_scopes == ("diagnostic",)
    assert "direct_chat" not in execute_action.surface_scopes
