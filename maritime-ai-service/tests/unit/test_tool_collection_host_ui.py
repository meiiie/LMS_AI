from types import SimpleNamespace


_DEFAULT_VISIBLE_ACTIONS_BY_PROVIDER = {
    "facebook": ("FACEBOOK_CREATE_POST", "FACEBOOK_CREATE_PHOTO_POST"),
    "gmail": ("GMAIL_FETCH_EMAILS",),
}


def _patch_wiii_connect_ready_providers(
    monkeypatch,
    module,
    providers,
    action_allowlists_by_provider=None,
):
    from app.engine.multi_agent import tool_policy_session as policy_module
    from app.engine.multi_agent import external_app_action_runtime as action_runtime

    provider_tuple = tuple(providers)
    visible_actions = (
        {
            provider: _DEFAULT_VISIBLE_ACTIONS_BY_PROVIDER[provider]
            for provider in provider_tuple
            if provider in _DEFAULT_VISIBLE_ACTIONS_BY_PROVIDER
        }
        if action_allowlists_by_provider is None
        else {
            str(provider): tuple(actions)
            for provider, actions in action_allowlists_by_provider.items()
        }
    )

    class FakeSnapshot:
        def agent_ready_external_provider_slugs(self):
            return provider_tuple

        def connection_status_map(self):
            return {
                provider: {
                    "active": True,
                    "status": "connected",
                    "agent_ready": True,
                }
                for provider in provider_tuple
            }

    fake_snapshot = FakeSnapshot()
    monkeypatch.setattr(
        module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: fake_snapshot,
    )
    monkeypatch.setattr(
        policy_module,
        "build_wiii_connect_snapshot",
        lambda **_kwargs: fake_snapshot,
    )
    monkeypatch.setattr(
        action_runtime,
        "_action_allowlists_for_providers",
        lambda provider_slugs, **_kwargs: {
            provider: tuple(visible_actions[provider])
            for provider in provider_slugs
            if provider in visible_actions
        },
    )


def test_host_ui_route_without_host_caps_does_not_force_generic_tools(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", True, raising=False)

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("lms_tools") and attr_name == "get_all_lms_tools":
            return lambda role="student": [SimpleNamespace(name="tool_lms_courses")]
        if module_name.endswith("direct_intent"):
            mapping = {
                "_normalize_for_intent": lambda query: str(query).lower(),
                "_needs_direct_knowledge_search": lambda _query: False,
            }
            return mapping[attr_name]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Wiii oi, nut Kham pha khoa hoc o dau?",
        state={"routing_metadata": {"intent": "host_ui_navigation"}, "context": {}},
    )

    assert tools == []
    assert force_tools is False


def test_host_ui_route_scopes_to_host_action_tools(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", True, raising=False)

    host_tools = [
        SimpleNamespace(name="host_action__ui_highlight"),
        SimpleNamespace(name="host_action__ui_click"),
    ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("lms_tools") and attr_name == "get_all_lms_tools":
            return lambda role="student": [SimpleNamespace(name="tool_lms_courses")]
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return lambda *args, **kwargs: host_tools
        if module_name.endswith("direct_intent"):
            mapping = {
                "_normalize_for_intent": lambda query: str(query).lower(),
                "_needs_direct_knowledge_search": lambda _query: False,
            }
            return mapping[attr_name]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Wiii oi, nut Kham pha khoa hoc o dau?",
        state={
            "routing_metadata": {"intent": "host_ui_navigation"},
            "context": {},
            "host_capabilities": {"tools": [{"name": "ui.highlight"}]},
        },
    )

    assert [tool.name for tool in tools] == [
        "host_action__ui_highlight",
        "host_action__ui_click",
    ]
    assert force_tools is True


def test_host_ui_route_binds_pointy_tools_without_keyword_match(monkeypatch):
    """Supervisor host_ui_navigation intent is enough to keep Pointy deterministic."""
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("pointy_tools") and attr_name == "extract_inventory_pairs_from_state":
            return lambda state: []
        if module_name.endswith("pointy_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("direct_intent"):
            mapping = {
                "_normalize_for_intent": lambda query: str(query).lower(),
                "_needs_news_search": lambda _query: False,
                "_needs_legal_search": lambda _query: False,
                "_needs_pointy": lambda _query: False,
                "_needs_maritime_search": lambda _query: False,
                "_needs_direct_knowledge_search": lambda _query: False,
            }
            return mapping[attr_name]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Chi vao nut Gui tin nhan giup minh.",
        state={"routing_metadata": {"intent": "host_ui_navigation"}, "context": {}},
    )

    assert {tool.name for tool in tools} == {
        "tool_pointy_show",
        "tool_pointy_clear",
        "tool_pointy_inventory",
    }
    assert force_tools is True


# ─────────────────────────────────────────────────────────────────────────
# Phase F3 (2026-05-06) — _force_skills_from_state state shape regression.
# ─────────────────────────────────────────────────────────────────────────


def test_uploaded_document_preview_request_forces_preview_host_action(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    host_tools = [
        SimpleNamespace(name="host_action__authoring__preview_lesson_patch"),
        SimpleNamespace(name="host_action__authoring__apply_lesson_patch"),
    ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return lambda *args, **kwargs: host_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Dua tren tai lieu vua upload, hay tao preview_lesson_patch co source_references.",
        user_role="teacher",
        state={
            "routing_metadata": {"intent": "uploaded_file_context"},
            "context": {
                "lms_connector_id": "maritime-lms",
                "lms_external_id": "teacher-1",
                "host_context": {
                    "host_type": "lms",
                    "connector_id": "maritime-lms",
                    "host_user_id": "teacher-1",
                },
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_123\nNguon trang 4.",
                        }
                    ]
                }
            },
            "host_capabilities": {
                "host_type": "lms",
                "connector_id": "maritime-lms",
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "authoring.apply_lesson_patch"},
                ]
            },
        },
    )

    assert [tool.name for tool in tools] == ["host_action__authoring__preview_lesson_patch"]
    assert force_tools is True


def test_uploaded_document_preview_binds_safe_preview_when_global_host_actions_disabled(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    generated_from: list[dict] = []

    def fake_generate_host_action_tools(capabilities_tools, *_args, **_kwargs):
        generated_from.extend(capabilities_tools)
        return [
            SimpleNamespace(
                name="host_action__"
                + str(tool["name"]).replace(".", "__")
            )
            for tool in capabilities_tools
        ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return fake_generate_host_action_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Tao ban preview_lesson_patch tu Word vua upload, co citation va source_references.",
        user_role="teacher",
        state={
            "routing_metadata": {"intent": "uploaded_file_context"},
            "context": {
                "lms_connector_id": "maritime-lms",
                "lms_external_id": "teacher-1",
                "host_context": {
                    "host_type": "lms",
                    "connector_id": "maritime-lms",
                    "host_user_id": "teacher-1",
                },
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_456\nNguon trang 2.",
                        }
                    ]
                }
            },
            "host_capabilities": {
                "host_type": "lms",
                "connector_id": "maritime-lms",
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "authoring.apply_lesson_patch"},
                    {"name": "course.publish"},
                ]
            },
        },
    )

    assert [tool.name for tool in tools] == ["host_action__authoring__preview_lesson_patch"]
    assert [tool["name"] for tool in generated_from] == ["authoring.preview_lesson_patch"]
    assert force_tools is True


def test_wiii_connect_facebook_post_request_binds_direct_apply_host_action(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    )

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(monkeypatch, module, ("facebook",))
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    generated_from: list[dict] = []

    def fake_generate_host_action_tools(capabilities_tools, *_args, **_kwargs):
        generated_from.extend(capabilities_tools)
        return [
            SimpleNamespace(
                name="host_action__" + str(tool["name"]).replace(".", "__")
            )
            for tool in capabilities_tools
        ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            assert attr_name == "make_wiii_connect_facebook_post_direct_apply_tool"
            return lambda **_kwargs: SimpleNamespace(
                name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
            )
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return fake_generate_host_action_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii tao bai viet Facebook ve lop hoc hom nay",
        user_role="student",
        state=state,
    )

    assert [tool.name for tool in tools] == [WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL]
    assert generated_from == []
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert state["_external_app_action_plan"]["status"] == "ready"
    assert force_tools is True


def test_wiii_connect_facebook_post_request_uses_backend_owner_when_host_declares_same_action(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
    )

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(monkeypatch, module, ("facebook",))
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    generated_from: list[dict] = []

    def fake_generate_host_action_tools(capabilities_tools, *_args, **_kwargs):
        generated_from.extend(capabilities_tools)
        return [
            SimpleNamespace(
                name="host_action__" + str(tool["name"]).replace(".", "__"),
                wiii_connect_action_owner="host_action_bridge",
            )
            for tool in capabilities_tools
        ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            assert attr_name == "make_wiii_connect_facebook_post_direct_apply_tool"
            return lambda **_kwargs: SimpleNamespace(
                name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
                wiii_connect_action_owner="backend_gateway",
            )
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return fake_generate_host_action_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {
        "context": {},
        "host_capabilities": {
            "tools": [
                {"name": WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION},
                {"name": WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION},
                {"name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION},
                {"name": "ui.highlight"},
            ]
        },
    }
    tools, force_tools = module._collect_direct_tools(
        "Wiii dang mot bai tho ngan len Facebook di",
        user_role="student",
        state=state,
    )

    assert [tool["name"] for tool in generated_from] == ["ui.highlight"]
    assert [tool.name for tool in tools] == [WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL]
    assert tools[0].wiii_connect_action_owner == "backend_gateway"
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert state["_external_app_integration_lane"]["executor"] == "specialized_direct_tool"
    assert force_tools is True


def test_wiii_connect_external_action_filters_legacy_host_bridge_capabilities():
    from app.engine.multi_agent import tool_collection as module
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
    )

    filtered = module._filter_host_capability_tools_for_external_action_plan(
        [
            {"name": WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION},
            {"name": WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION},
            {"name": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION},
            {"name": "ui.highlight"},
        ],
        SimpleNamespace(kind="provider_action"),
    )

    assert filtered == [{"name": "ui.highlight"}]


def test_wiii_connect_synthetic_host_capabilities_hide_account_binding_fields():
    from app.engine.multi_agent import tool_collection as module

    preview = module._wiii_connect_facebook_post_preview_capability()
    direct_apply = module._wiii_connect_facebook_post_direct_apply_capability()

    for capability in (preview, direct_apply):
        properties = capability["input_schema"]["properties"]
        assert set(properties) == {"message", "image_policy"}
        assert "connection_ref" not in properties
        assert "provider_slug" not in properties
        assert "page_id" not in properties
        assert "image_base64" not in properties
        assert "image_url" not in properties


def test_wiii_connect_facebook_post_request_fails_closed_without_backend_tool(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(monkeypatch, module, ("facebook",))
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    generated_from: list[dict] = []

    def fake_generate_host_action_tools(capabilities_tools, *_args, **_kwargs):
        generated_from.extend(capabilities_tools)
        return [
            SimpleNamespace(
                name="host_action__" + str(tool["name"]).replace(".", "__")
            )
            for tool in capabilities_tools
        ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            raise RuntimeError("backend tool unavailable")
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return fake_generate_host_action_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii tao bai viet Facebook ve lop hoc hom nay",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert generated_from == []
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "facebook_post_direct_apply"
    assert state["_external_app_action_plan"]["status"] == "ready"
    assert force_tools is False


def test_wiii_connect_provider_action_request_binds_integration_delegate(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        WIII_CONNECT_LIST_ACTIONS_TOOL,
    )

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(monkeypatch, module, ("facebook", "gmail"))
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    list_kwargs = {}
    delegate_kwargs = {}

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            if attr_name == "make_wiii_connect_list_actions_tool":
                def make_list(**kwargs):
                    list_kwargs.update(kwargs)
                    return SimpleNamespace(name=WIII_CONNECT_LIST_ACTIONS_TOOL)

                return make_list
            if attr_name == "make_wiii_connect_delegate_to_integration_tool":
                def make_delegate(**kwargs):
                    delegate_kwargs.update(kwargs)
                    return SimpleNamespace(name=WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL)

                return make_delegate
            raise AssertionError(f"Unexpected Wiii Connect tool: {attr_name}")
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii đọc Gmail từ giáo viên giúp tôi",
        user_role="student",
        state=state,
    )

    assert [tool.name for tool in tools] == [
        WIII_CONNECT_LIST_ACTIONS_TOOL,
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    ]
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["provider_slug"] == "gmail"
    assert state["_external_app_action_plan"]["status"] == "ready"
    plan_allowlists = state["_external_app_action_plan"]["action_allowlists_by_provider"]
    assert list_kwargs["allowed_provider_slugs"] == ("gmail",)
    assert {
        provider: list(actions)
        for provider, actions in list_kwargs["allowed_action_slugs_by_provider"].items()
    } == plan_allowlists
    assert delegate_kwargs["allowed_provider_slugs"] == ("gmail",)
    assert {
        provider: list(actions)
        for provider, actions in delegate_kwargs[
            "allowed_action_slugs_by_provider"
        ].items()
    } == plan_allowlists
    assert force_tools is True


def test_wiii_connect_external_action_does_not_bind_without_agent_ready_provider(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(monkeypatch, module, ())
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            raise AssertionError("Wiii Connect tools must not bind without agent-ready provider")
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii đọc Gmail từ giáo viên giúp tôi",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["status"] == "blocked"
    assert force_tools is False


def test_wiii_connect_external_action_does_not_bind_without_visible_action_inventory(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_wiii_connect_composio", True, raising=False)
    _patch_wiii_connect_ready_providers(
        monkeypatch,
        module,
        ("gmail",),
        action_allowlists_by_provider={},
    )
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_needs_weather_lookup", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("wiii_connect_tools"):
            raise AssertionError("Wiii Connect tools must not bind without visible action inventory")
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    state = {"context": {}}
    tools, force_tools = module._collect_direct_tools(
        "Wiii đọc Gmail từ giáo viên giúp tôi",
        user_role="student",
        state=state,
    )

    assert tools == []
    assert state["_turn_path_decision"]["path"] == "external_app_action"
    assert state["_external_app_action_plan"]["kind"] == "provider_action"
    assert state["_external_app_action_plan"]["provider_slug"] == "gmail"
    assert state["_external_app_action_plan"]["status"] == "blocked"
    assert state["_external_app_action_plan"]["reason"] == "no_agent_ready_actions"
    assert state["_external_app_integration_lane"]["status"] == "blocked"
    assert state["_external_app_integration_lane"]["visible_tool_names"] == []
    assert force_tools is False


def test_uploaded_document_preview_does_not_bind_lms_authoring_without_connection(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.multi_agent.visual_intent_resolver import build_visual_tool_requirement

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", True, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_needs_pointy", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_should_strip_visual_tools_from_direct", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "_should_strip_visual_tools_for_analytical_text_turn", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(module, "build_visual_tool_requirement", build_visual_tool_requirement)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )

    generated_from: list[dict] = []

    def fake_generate_host_action_tools(capabilities_tools, *_args, **_kwargs):
        generated_from.extend(capabilities_tools)
        return [
            SimpleNamespace(
                name="host_action__"
                + str(tool["name"]).replace(".", "__")
            )
            for tool in capabilities_tools
        ]

    def fake_load_attr(module_name: str, attr_name: str):
        if module_name.endswith("utility_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_search_tools"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("web_fetch_tool"):
            return SimpleNamespace(name=attr_name)
        if module_name.endswith("agent_tools") and attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if module_name.endswith("action_tools") and attr_name == "generate_host_action_tools":
            return fake_generate_host_action_tools
        if module_name.endswith("direct_intent") and attr_name == "_needs_maritime_search":
            return lambda _query: False
        if module_name.endswith("direct_intent") and attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        raise AssertionError(f"Unexpected load: {module_name}.{attr_name}")

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Tao ban preview_lesson_patch tu Word vua upload, co citation va source_references.",
        user_role="teacher",
        state={
            "routing_metadata": {"intent": "uploaded_file_context"},
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_789\nNguon trang 5.",
                        }
                    ]
                }
            },
            "host_capabilities": {
                "tools": [
                    {"name": "authoring.preview_lesson_patch"},
                    {"name": "authoring.apply_lesson_patch"},
                    {"name": "ui.highlight"},
                ]
            },
        },
    )

    assert [tool["name"] for tool in generated_from] == ["ui.highlight"]
    assert "host_action__authoring__preview_lesson_patch" not in [
        tool.name for tool in tools
    ]
    assert force_tools is False


def test_uploaded_document_course_wording_prefers_course_plan_host_action():
    from app.engine.multi_agent import tool_collection as module

    state = {
        "context": {
            "document_context": {
                "attachments": [
                    {
                        "file_name": "manual.docx",
                        "markdown": "# Huong dan LMS\n## Soan cau truc chuong va bai",
                    }
                ]
            }
        }
    }
    query = (
        "Tu file Word nay, lap chuong trinh dao tao hoan chinh: de cuong khoa, "
        "lo trinh hoc, chia thanh chuong va nhieu bai hoc co citation."
    )

    assert module._looks_like_document_preview_request(query, state)
    assert module._looks_like_document_course_preview_request(query, state)


def test_force_skills_reads_from_state_context_dict():
    """v3.0 F3 fix: state['context']['force_skills'] is the canonical
    location (NOT state['force_skills']) per graph_stream_runtime
    initial_state shape."""
    from app.engine.multi_agent.tool_collection import _force_skills_from_state

    state = {'context': {'force_skills': ['wiii-pointy', 'web-search']}}
    result = _force_skills_from_state(state)
    assert result == {'wiii-pointy', 'web-search'}


def test_force_skills_top_level_state_fallback():
    """Backward compat: if some caller stuffs force_skills at top level,
    still pick it up."""
    from app.engine.multi_agent.tool_collection import _force_skills_from_state

    state = {'force_skills': ['wiii-pointy']}
    result = _force_skills_from_state(state)
    assert result == {'wiii-pointy'}


def test_force_skills_empty_when_neither_path_set():
    from app.engine.multi_agent.tool_collection import _force_skills_from_state

    state = {'context': {}}
    assert _force_skills_from_state(state) == set()
    assert _force_skills_from_state({}) == set()
    assert _force_skills_from_state(None) == set()


def test_force_skills_normalises_case_and_whitespace():
    from app.engine.multi_agent.tool_collection import _force_skills_from_state

    state = {'context': {'force_skills': ['  Wiii-Pointy  ', 'WEB-SEARCH']}}
    assert _force_skills_from_state(state) == {'wiii-pointy', 'web-search'}



def test_host_action_tools_filter_allows_pointy_tools():
    """v3.0 F4 regression: standalone Wiii desktop có host_ui_navigation
    routing nhưng KHÔNG có host_action__ tools (no LMS bridge). Pointy
    tools là path chính để cursor phản hồi 'where is X' queries.

    _host_action_tools previously stripped them → AI generated prose
    without invoking tool_pointy_show. Now both prefixes allowed.
    """
    from app.engine.multi_agent.tool_collection import _host_action_tools
    from types import SimpleNamespace

    tools = [
        SimpleNamespace(name='host_action__ui_click'),
        SimpleNamespace(name='host_action__ui_navigate'),
        SimpleNamespace(name='tool_pointy_show'),
        SimpleNamespace(name='tool_pointy_clear'),
        SimpleNamespace(name='tool_pointy_inventory'),
        SimpleNamespace(name='tool_web_search'),  # should be excluded
        SimpleNamespace(name='tool_search_news'),  # should be excluded
    ]
    result = _host_action_tools(tools)
    names = {t.name for t in result}
    assert 'host_action__ui_click' in names
    assert 'host_action__ui_navigate' in names
    assert 'tool_pointy_show' in names
    assert 'tool_pointy_clear' in names
    assert 'tool_pointy_inventory' in names
    assert 'tool_web_search' not in names
    assert 'tool_search_news' not in names


def test_host_action_tools_pointy_only_when_no_host_actions_present():
    """On standalone Wiii (no LMS host bridge → no host_action__ tools),
    pointy tools alone should still be retained — not filtered to empty.
    """
    from app.engine.multi_agent.tool_collection import _host_action_tools
    from types import SimpleNamespace

    tools = [
        SimpleNamespace(name='tool_pointy_show'),
        SimpleNamespace(name='tool_pointy_inventory'),
        SimpleNamespace(name='tool_web_search'),
    ]
    result = _host_action_tools(tools)
    assert {t.name for t in result} == {'tool_pointy_show', 'tool_pointy_inventory'}


def test_off_topic_direct_prose_does_not_bind_heavy_tools(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.multi_agent.visual_intent_resolver import build_visual_tool_requirement

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", False, raising=False)
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=False,
            mode="text",
            visual_type=None,
            preferred_tool=None,
            presentation_intent="text",
        ),
    )
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(module, "build_visual_tool_requirement", build_visual_tool_requirement)

    def fake_load_attr(_module_name: str, attr_name: str):
        if attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "_should_strip_visual_tools_from_direct":
            return lambda *_args, **_kwargs: False
        if attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        if attr_name == "handoff_to_agent":
            return SimpleNamespace(name="handoff_to_agent")
        return SimpleNamespace(name=attr_name)

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Hay phan tich ngan vi sao pipeline Pointy Thinking memory de sai route.",
        state={"routing_metadata": {"intent": "off_topic"}, "context": {}},
    )

    assert tools == []
    assert force_tools is False


def test_reasoning_safety_meta_direct_prose_overrides_false_visual_force(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.multi_agent.visual_intent_resolver import build_visual_tool_requirement

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", True, raising=False)
    monkeypatch.setattr(module, "_needs_web_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_datetime", lambda _query: False)
    monkeypatch.setattr(module, "_needs_news_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_legal_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_lms_query", lambda _query: False)
    monkeypatch.setattr(module, "_needs_direct_knowledge_search", lambda _query: False)
    monkeypatch.setattr(module, "_needs_analysis_tool", lambda _query: False)
    monkeypatch.setattr(module, "_infer_direct_thinking_mode", lambda *_args, **_kwargs: "general")
    monkeypatch.setattr(module, "_looks_reasoning_safety_meta_turn", lambda _query: True)
    monkeypatch.setattr(
        module,
        "resolve_visual_intent",
        lambda _query: SimpleNamespace(
            force_tool=True,
            mode="inline_html",
            visual_type="comparison",
            preferred_tool="tool_generate_visual",
            presentation_intent="article_figure",
        ),
    )
    monkeypatch.setattr(module, "filter_tools_for_role", lambda tools, _role: tools)
    monkeypatch.setattr(module, "filter_tools_for_visual_intent", lambda tools, *_args, **_kwargs: tools)
    monkeypatch.setattr(module, "build_visual_tool_requirement", build_visual_tool_requirement)

    def fake_load_attr(_module_name: str, attr_name: str):
        if attr_name == "_normalize_for_intent":
            return lambda query: str(query).lower()
        if attr_name == "_should_strip_visual_tools_from_direct":
            return lambda *_args, **_kwargs: False
        if attr_name == "RAG_KNOWLEDGE_TOOL":
            return SimpleNamespace(name="tool_rag_knowledge")
        if attr_name == "get_visual_tools":
            return lambda: [SimpleNamespace(name="tool_generate_visual")]
        return SimpleNamespace(name=attr_name)

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools(
        "Giai thich su khac nhau giua visible thinking an toan va chain of thought noi bo.",
        state={"routing_metadata": {"intent": "off_topic"}, "context": {}},
    )

    assert tools == []
    assert force_tools is False
