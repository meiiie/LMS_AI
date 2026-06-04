from types import SimpleNamespace

import pytest


def test_turn_path_governor_marks_plain_greeting_as_no_tool_chat():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(normalized_query="xin chao wiii")
    )

    assert decision.path == "casual_chat"
    assert decision.bind_tools is False
    assert decision.force_tools is False


@pytest.mark.parametrize(
    "query",
    [
        "noi de",
        "sao lai z",
        "sao lo lung ?",
        "the ngu di",
    ],
)
def test_turn_path_governor_marks_short_social_followup_as_no_tool_chat(query):
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(TurnPathSignals(normalized_query=query))

    assert decision.path == "casual_chat"
    assert decision.bind_tools is False
    assert decision.force_tools is False


def test_turn_path_governor_does_not_treat_task_query_as_social_followup():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="sao lai colreg rule 15 ap dung",
            needs_maritime_search=True,
        )
    )

    assert decision.path == "maritime_search"
    assert decision.bind_tools is True
    assert decision.force_tools is True


def test_turn_path_governor_defaults_plain_direct_prose_to_no_tool():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(normalized_query="giai thich ngan ve cach hoc tot hon")
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "default_direct_prose_no_tool"
    assert decision.bind_tools is False
    assert decision.allow_agent_handoff is False


def test_turn_path_governor_keeps_low_signal_noise_off_tool_path():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query=(
                "flow noi chuyen thuong van bi keo sang search tool "
                + ("r" * 128)
            )
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "low_signal_noise_no_tool"
    assert decision.bind_tools is False


def test_turn_path_governor_marks_wiii_pipeline_meta_as_no_tool_direct_prose():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="wiii flow noi chuyen sai route, kiem tra pipeline",
            looks_wiii_pipeline_meta=True,
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "wiii_pipeline_meta_no_tool"
    assert decision.bind_tools is False


def test_turn_path_governor_scopes_character_memory_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="ten toi la an",
            needs_character_memory_tool=True,
        )
    )

    assert decision.path == "direct_prose"
    assert decision.reason == "character_memory_tool_request"
    assert decision.bind_tools is True
    assert decision.force_tools is False
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_character_note") is True
    assert decision.should_keep_tool_name("tool_web_search") is False


def test_turn_path_governor_narrows_visual_app_to_required_tool():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="mo phong vat ly con lac",
            visual_force_tool=True,
            visual_mode="app",
            visual_presentation_intent="code_studio_app",
            visual_required_tool_names=("tool_create_visual_code",),
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "visual_generation"
    assert decision.force_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_create_visual_code") is True
    assert decision.should_keep_tool_name("tool_generate_visual") is False
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_governor_keeps_visual_app_ahead_of_domain_search():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="tao mini app mo phong colreg rule 15",
            visual_force_tool=True,
            visual_mode="app",
            visual_presentation_intent="code_studio_app",
            visual_required_tool_names=("tool_create_visual_code",),
            needs_maritime_search=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "visual_generation"
    assert decision.reason == "visual_intent_code_studio_app"
    assert decision.should_keep_tool_name("tool_create_visual_code") is True
    assert decision.should_keep_tool_name("tool_search_maritime") is False


def test_turn_path_governor_web_search_force_beats_visual_drift():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="research ui-tars desktop pipeline and ux steps",
            force_skills=frozenset({"web-search"}),
            web_search_forced=True,
            needs_web_search=True,
            visual_force_tool=True,
            visual_mode="template",
            visual_presentation_intent="chart_runtime",
            visual_required_tool_names=("tool_generate_visual",),
        )
    )

    assert decision.path == "web_search"
    assert decision.force_tools is True
    assert decision.should_keep_tool_name("tool_web_search") is True
    assert decision.should_keep_tool_name("tool_fetch_url") is True
    assert decision.should_keep_tool_name("tool_generate_visual") is False


def test_turn_path_governor_treats_supervisor_web_intent_as_tool_signal():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="topic that keyword detectors missed",
            routing_intent="web_search",
        )
    )

    assert decision.path == "web_search"
    assert decision.force_tools is True
    assert decision.should_keep_tool_name("tool_web_search") is True
    assert decision.should_keep_tool_name("tool_fetch_url") is True
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_governor_code_execution_beats_visual_drift():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="chay python de ve bieu do demo",
            prefers_code_execution_lane=True,
            needs_analysis_tool=True,
            visual_force_tool=True,
            visual_mode="template",
            visual_presentation_intent="chart_runtime",
            visual_required_tool_names=("tool_generate_visual",),
        )
    )

    assert decision.path == "code_execution"
    assert decision.bind_tools is False
    assert decision.should_keep_tool_name("tool_generate_visual") is False


def test_collect_direct_tools_routes_code_studio_app_to_visual_lane():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}, "messages": []}
    tools, force_tools = module._collect_direct_tools(
        (
            "Tao mot mini app Code Studio mo phong COLREG Rule 15 "
            "co slider va canvas tuong tac."
        ),
        user_role="student",
        state=state,
    )

    visible = state["_tool_policy_session"]["visible_tool_names"]
    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "visual_generation"
    assert "tool_create_visual_code" in visible
    assert all(
        (getattr(tool, "name", None) or getattr(tool, "__name__", ""))
        == "tool_create_visual_code"
        for tool in tools
    )


def test_turn_path_governor_routes_weather_to_weather_with_live_lookup_fallback():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="y la thoi tiet nong do ban biet nay bao do khong",
            needs_weather_lookup=True,
            needs_web_search=True,
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "weather_lookup"
    assert decision.force_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name("tool_current_weather") is True
    assert decision.should_keep_tool_name("tool_web_search") is True
    assert decision.should_keep_tool_name("tool_fetch_url") is False
    assert decision.should_keep_tool_name("tool_current_datetime") is True
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_governor_forces_wiii_connect_facebook_post_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
        WIII_CONNECT_LIST_ACTIONS_TOOL,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="wiii dang bai len facebook giup minh",
            needs_external_app_action=True,
            pointy_requested=True,
            suppress_pointy_for_output=True,
        )
    )

    assert decision.path == "external_app_action"
    assert decision.force_tools is True
    assert decision.bind_tools is True
    assert decision.allow_all_tools is False
    assert decision.should_keep_tool_name(WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL) is True
    assert decision.should_keep_tool_name(WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL) is True
    assert decision.should_keep_tool_name(WIII_CONNECT_LIST_ACTIONS_TOOL) is True
    assert decision.should_keep_tool_name(WIII_CONNECT_EXECUTE_ACTION_TOOL) is False
    assert decision.should_keep_tool_name("host_action__ui_click") is False
    assert decision.should_keep_tool_name("tool_pointy_show") is False


def test_turn_path_governor_marks_connection_status_as_no_tool_control_path():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="wiii co ket noi duoc facebook khong",
            routing_intent="off_topic",
            needs_external_connection_status=True,
        )
    )

    assert decision.path == "external_connection_status"
    assert decision.reason == "wiii_connect_provider_status_request"
    assert decision.bind_tools is False
    assert decision.allow_agent_handoff is False


def test_turn_path_filter_keeps_only_lms_document_preview_tools():
    from app.engine.multi_agent.turn_path_governor import (
        TurnPathSignals,
        filter_tools_for_turn_path,
        resolve_turn_path_decision,
    )

    decision = resolve_turn_path_decision(
        TurnPathSignals(
            normalized_query="tao cho minh bai hoc",
            looks_document_preview=True,
        )
    )
    tools = [
        SimpleNamespace(name="host_action__authoring__preview_lesson_patch"),
        SimpleNamespace(name="host_action__authoring__apply_lesson_patch"),
        SimpleNamespace(name="tool_web_search"),
    ]

    filtered = filter_tools_for_turn_path(
        tools,
        decision,
        tool_name=lambda tool: tool.name,
    )

    assert decision.path == "lms_document_preview"
    assert [tool.name for tool in filtered] == [
        "host_action__authoring__preview_lesson_patch"
    ]


def test_collect_direct_tools_uses_governor_for_plain_greeting():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Xin chào Wiii",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


def test_collect_direct_tools_keeps_daily_status_off_search_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Hôm nay mình ăn cơm rồi",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


def test_collect_direct_tools_keeps_short_social_followup_off_tool_path():
    from app.engine.multi_agent import tool_collection as module

    state = {
        "context": {},
        "routing_metadata": {
            "intent": "unknown",
        },
    }
    tools, force_tools = module._collect_direct_tools(
        "sao lơ lửng ?",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "casual_chat"


@pytest.mark.parametrize(
    "query",
    [
        "flow noi chuyen thuong van bi keo sang search/tool",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "sao lai z " + ("R" * 256),
    ],
)
def test_collect_direct_tools_keeps_plain_meta_and_noise_off_tool_path(query):
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        query,
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "direct_prose"
    assert state["_turn_path_decision"]["bind_tools"] is False
    assert state["_tool_policy_session"]["visible_tool_names"] == []


def test_collect_direct_tools_marks_wiii_pipeline_meta_as_no_tool():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii flow noi chuyen bi sai route, kiem tra pipeline tool policy.",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "direct_prose"
    assert state["_turn_path_decision"]["reason"] == "wiii_pipeline_meta_no_tool"


def test_collect_direct_tools_records_connection_status_control_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}, "routing_metadata": {"intent": "off_topic"}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii co ket noi duoc facebook khong?",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "external_connection_status"
    assert state["_tool_policy_session"]["visible_tool_names"] == []


def test_collect_direct_tools_routes_providerless_facebook_action_continuation():
    from app.engine.multi_agent import tool_collection as module

    state = {
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
    }
    tools, force_tools = module._collect_direct_tools(
        'dang bai: "xin chao minh la AI" la duoc',
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert state["_external_app_action_plan"]["provider_slug"] == "facebook"
    assert state["_tool_policy_session"]["external_app_action_plan"][
        "provider_slug"
    ] == "facebook"


def test_collect_direct_tools_routes_providerless_gmail_action_continuation():
    from app.engine.multi_agent import tool_collection as module

    state = {
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
    }
    tools, force_tools = module._collect_direct_tools(
        "doc email moi nhat di",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["provider_slug"] == "gmail"
    assert state["_tool_policy_session"]["external_app_action_plan"][
        "provider_slug"
    ] == "gmail"


def test_collect_direct_tools_routes_missing_provider_external_action():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}, "messages": []}
    tools, force_tools = module._collect_direct_tools(
        "dang bai len mang xa hoi di",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert force_tools is False
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["reason"] == "missing_provider_target"
    assert state["_external_app_action_plan"]["provider_slug"] == ""
    assert state["_tool_policy_session"]["external_app_action_plan"][
        "reason"
    ] == "missing_provider_target"


def test_collect_direct_tools_keeps_explicit_web_search_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "hom nay co gi hot?",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "web_search"
    assert "tool_web_search" in names
    assert "tool_current_weather" not in names


def test_collect_direct_tools_honors_supervisor_web_search_intent():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}, "routing_metadata": {"intent": "web_search"}}
    tools, force_tools = module._collect_direct_tools(
        "topic that local intent detectors missed",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "web_search"
    assert "tool_web_search" in names
    assert "tool_fetch_url" in names
    assert "tool_current_weather" not in names


def test_collect_direct_tools_scopes_personal_fact_to_character_tools():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Ten toi la An",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is False
    assert state["_turn_path_decision"]["reason"] == "character_memory_tool_request"
    assert "tool_character_note" in names
    assert "tool_character_log_experience" in names
    assert "tool_web_search" not in names


def test_collect_direct_tools_routes_weather_followup_to_weather_tool(monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(settings, "living_agent_enable_weather", True)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "test-weather-key")

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "weather_lookup"
    assert "tool_current_weather" in names
    assert "tool_web_search" in names
    assert "tool_fetch_url" not in names
    assert "tool_current_datetime" in names


def test_collect_direct_tools_keeps_weather_path_with_web_search_when_provider_missing(monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(settings, "living_agent_enable_weather", False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", None)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "thời tiết Hải Phòng hôm nay thế nào",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "weather_lookup"
    assert "tool_web_search" in names
    assert "tool_current_weather" not in names


@pytest.mark.parametrize(
    "query",
    [
        "nay thoi tiet nong nhi",
        "hom nay troi nong nhi",
        "hom nay bao nhieu do",
        "troi co mua khong",
    ],
)
def test_collect_direct_tools_routes_weather_turns_to_weather_tool(query, monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(settings, "living_agent_enable_weather", True)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "test-weather-key")

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        query,
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "weather_lookup"
    assert "tool_current_weather" in names
    assert "tool_web_search" in names
    assert "tool_fetch_url" not in names


def test_collect_direct_tools_keeps_maritime_tool_on_maritime_path():
    from app.engine.multi_agent import tool_collection as module

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Tra cứu quy định COLREG mới nhất",
        user_role="student",
        state=state,
    )
    names = {getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools}

    assert force_tools is True
    assert state["_turn_path_decision"]["path"] == "maritime_search"
    assert "tool_search_maritime" in names
    assert "tool_current_weather" not in names


def test_direct_required_tool_names_weather_prefers_weather_over_web(monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    monkeypatch.setattr(settings, "living_agent_enable_weather", True)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "test-weather-key")

    required = _direct_required_tool_names(
        "ý là thời tiết nóng đó. Bạn biết nay bao độ không",
        user_role="student",
    )

    assert "tool_current_weather" in required
    assert "tool_web_search" in required
    assert "tool_fetch_url" not in required
    assert "tool_current_datetime" in required


def test_direct_required_tool_names_temperature_question_prefers_weather_over_web(monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    monkeypatch.setattr(settings, "living_agent_enable_weather", True)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", "test-weather-key")

    required = _direct_required_tool_names(
        "hom nay bao nhieu do",
        user_role="student",
    )

    assert required == [
        "tool_current_weather",
        "tool_web_search",
        "tool_current_datetime",
    ]


def test_direct_required_tool_names_weather_falls_back_to_web_search(monkeypatch):
    from app.core.config import settings
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names

    monkeypatch.setattr(settings, "living_agent_enable_weather", False)
    monkeypatch.setattr(settings, "living_agent_weather_api_key", None)

    required = _direct_required_tool_names(
        "hom nay bao nhieu do",
        user_role="student",
    )

    assert required == ["tool_web_search"]


def test_direct_required_tool_names_includes_wiii_connect_facebook_direct_apply():
    from app.engine.multi_agent.tool_collection import _direct_required_tool_names
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    required = _direct_required_tool_names(
        "Wiii tao bai viet Facebook ve lop hoc hom nay",
        user_role="student",
    )

    assert WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL in required
