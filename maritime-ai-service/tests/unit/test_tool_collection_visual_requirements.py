from types import SimpleNamespace


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _tool_names(tools):
    return [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]


def _patch_visual_collection_modules(monkeypatch, module):
    from app.engine.tools import agent_tools
    from app.engine.tools import chart_tools
    from app.engine.tools import output_generation_tools
    from app.engine.tools import utility_tools
    from app.engine.tools import visual_tools
    from app.engine.tools import web_fetch_tool
    from app.engine.tools import web_search_tools

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            enable_agent_handoffs=False,
            enable_browser_agent=False,
            enable_character_tools=False,
            enable_code_execution=False,
            enable_host_actions=False,
            enable_lms_integration=False,
            enable_privileged_sandbox=False,
            enable_structured_visuals=True,
            sandbox_allow_browser_workloads=False,
            sandbox_provider="disabled",
        ),
    )
    monkeypatch.setattr(utility_tools, "tool_current_datetime", _tool("tool_current_datetime"))
    monkeypatch.setattr(web_search_tools, "tool_web_search", _tool("tool_web_search"))
    monkeypatch.setattr(web_search_tools, "tool_search_news", _tool("tool_search_news"))
    monkeypatch.setattr(web_search_tools, "tool_search_legal", _tool("tool_search_legal"))
    monkeypatch.setattr(web_search_tools, "tool_search_maritime", _tool("tool_search_maritime"))
    monkeypatch.setattr(web_fetch_tool, "tool_fetch_url", _tool("tool_fetch_url"))
    monkeypatch.setattr(agent_tools, "RAG_KNOWLEDGE_TOOL", _tool("tool_rag_knowledge"))
    monkeypatch.setattr(
        chart_tools,
        "get_chart_tools",
        lambda: [
            _tool("tool_generate_mermaid"),
            _tool("tool_generate_chart"),
            _tool("tool_generate_interactive_chart"),
        ],
    )
    monkeypatch.setattr(
        visual_tools,
        "get_visual_tools",
        lambda: [
            _tool("tool_generate_visual"),
            _tool("tool_create_visual_code"),
        ],
    )
    monkeypatch.setattr(
        output_generation_tools,
        "get_output_generation_tools",
        lambda: [
            _tool("tool_generate_html_file"),
            _tool("tool_generate_excel_file"),
            _tool("tool_generate_word_document"),
        ],
    )


def test_collect_direct_tools_web_search_force_strips_visual_capabilities(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.tools import agent_tools
    from app.engine.tools import chart_tools
    from app.engine.tools import utility_tools
    from app.engine.tools import visual_tools
    from app.engine.tools import web_fetch_tool
    from app.engine.tools import web_search_tools

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            enable_agent_handoffs=False,
            enable_character_tools=False,
            enable_code_execution=False,
            enable_host_actions=False,
            enable_lms_integration=False,
            enable_structured_visuals=True,
            enable_browser_agent=False,
            enable_privileged_sandbox=False,
            sandbox_provider="disabled",
            sandbox_allow_browser_workloads=False,
        ),
    )
    monkeypatch.setattr(utility_tools, "tool_current_datetime", _tool("tool_current_datetime"))
    monkeypatch.setattr(web_search_tools, "tool_web_search", _tool("tool_web_search"))
    monkeypatch.setattr(web_search_tools, "tool_search_news", _tool("tool_search_news"))
    monkeypatch.setattr(web_search_tools, "tool_search_legal", _tool("tool_search_legal"))
    monkeypatch.setattr(web_search_tools, "tool_search_maritime", _tool("tool_search_maritime"))
    monkeypatch.setattr(web_fetch_tool, "tool_fetch_url", _tool("tool_fetch_url"))
    monkeypatch.setattr(agent_tools, "RAG_KNOWLEDGE_TOOL", _tool("tool_rag_knowledge"))
    monkeypatch.setattr(
        chart_tools,
        "get_chart_tools",
        lambda: [
            _tool("tool_generate_mermaid"),
            _tool("tool_generate_chart"),
            _tool("tool_generate_interactive_chart"),
        ],
    )
    monkeypatch.setattr(
        visual_tools,
        "get_visual_tools",
        lambda: [
            _tool("tool_generate_visual"),
            _tool("tool_create_visual_code"),
        ],
    )

    tools, force_tools = module._collect_direct_tools(
        "Search the web and make a chart about current oil prices.",
        user_role="student",
        state={
            "context": {"force_skills": ["web-search"]},
            "routing_metadata": {"intent": "general"},
        },
    )

    names = _tool_names(tools)
    assert force_tools is True
    assert "tool_web_search" in names
    assert "tool_fetch_url" in names
    assert "tool_generate_visual" not in names
    assert "tool_create_visual_code" not in names
    assert "tool_generate_mermaid" not in names
    assert "tool_generate_chart" not in names
    assert "tool_generate_interactive_chart" not in names


def test_collect_direct_tools_suppresses_pointy_for_visual_output_request(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    _patch_visual_collection_modules(monkeypatch, module)

    tools, force_tools = module._collect_direct_tools(
        "Huong dan minh tao minh hoa so sanh softmax attention va linear attention",
        user_role="student",
        state={"routing_metadata": {"intent": "general"}, "context": {}},
    )

    names = _tool_names(tools)
    assert force_tools is True
    assert "tool_generate_visual" in names
    assert "tool_create_visual_code" not in names
    assert "tool_pointy_show" not in names
    assert "tool_pointy_clear" not in names
    assert "tool_pointy_inventory" not in names


def test_collect_direct_tools_suppresses_forced_pointy_for_simulation_output_request(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    _patch_visual_collection_modules(monkeypatch, module)

    tools, force_tools = module._collect_direct_tools(
        "@wiii-pointy huong dan minh mo phong vat ly con lac bang canvas",
        user_role="student",
        state={
            "routing_metadata": {"intent": "general"},
            "context": {"force_skills": ["wiii-pointy"]},
        },
    )

    names = _tool_names(tools)
    assert force_tools is True
    assert "tool_create_visual_code" in names
    assert "tool_generate_visual" not in names
    assert "tool_pointy_show" not in names
    assert "tool_pointy_clear" not in names
    assert "tool_pointy_inventory" not in names
    assert names == ["tool_create_visual_code"]


def test_collect_direct_tools_suppresses_forced_pointy_for_lesson_output_request(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    _patch_visual_collection_modules(monkeypatch, module)

    tools, force_tools = module._collect_direct_tools(
        "@wiii-pointy tao bai hoc ngan ve ky nang hoc tap",
        user_role="teacher",
        state={
            "routing_metadata": {"intent": "general"},
            "context": {"force_skills": ["wiii-pointy"]},
        },
    )

    assert tools == []
    assert force_tools is False


def test_collect_code_studio_tools_uses_visual_requirement_for_simulation(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    _patch_visual_collection_modules(monkeypatch, module)

    tools, force_tools = module._collect_code_studio_tools(
        "Hay mo phong vat ly con lac co keo tha chuot",
        user_role="student",
    )

    assert force_tools is True
    assert _tool_names(tools) == ["tool_create_visual_code"]


def test_collect_code_studio_tools_keeps_required_html_file_tool(monkeypatch):
    from app.engine.multi_agent import tool_collection as module

    _patch_visual_collection_modules(monkeypatch, module)

    tools, force_tools = module._collect_code_studio_tools(
        "Tao landing page HTML cho san pham de nhung LMS",
        user_role="student",
    )

    assert force_tools is True
    assert _tool_names(tools) == [
        "tool_generate_html_file",
        "tool_create_visual_code",
    ]
