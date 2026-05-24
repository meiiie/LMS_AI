from types import SimpleNamespace


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _tool_names(tools):
    return [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]


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
