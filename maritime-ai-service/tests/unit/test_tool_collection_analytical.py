from types import SimpleNamespace


class _FakeTool:
    def __init__(self, name: str):
        self.name = name


def test_collect_direct_tools_strips_visual_tools_for_analytical_text_turn(monkeypatch):
    from app.engine.multi_agent import tool_collection as module
    from app.engine.multi_agent.visual_intent_resolver import (
        build_visual_tool_requirement,
        required_visual_tool_names,
        visual_tool_capability_names,
    )

    monkeypatch.setattr(module.settings, "enable_character_tools", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_lms_integration", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_host_actions", False, raising=False)
    monkeypatch.setattr(module.settings, "enable_structured_visuals", True, raising=False)

    def fake_load_attr(_module_name: str, attr_name: str):
        mapping = {
            "tool_current_datetime": _FakeTool("tool_current_datetime"),
            "tool_web_search": _FakeTool("tool_web_search"),
            "tool_fetch_url": _FakeTool("tool_fetch_url"),
            "tool_search_news": _FakeTool("tool_search_news"),
            "tool_search_legal": _FakeTool("tool_search_legal"),
            "tool_search_maritime": _FakeTool("tool_search_maritime"),
            "RAG_KNOWLEDGE_TOOL": _FakeTool("tool_rag_knowledge"),
            "get_chart_tools": lambda: [_FakeTool("tool_generate_interactive_chart")],
            "get_visual_tools": lambda: [
                _FakeTool("tool_generate_visual"),
                _FakeTool("tool_generate_mermaid"),
            ],
            "filter_tools_for_role": lambda tools, _user_role: tools,
            "resolve_visual_intent": lambda _query: SimpleNamespace(
                mode="text",
                force_tool=False,
                presentation_intent="text",
                preferred_tool=None,
                visual_type=None,
            ),
            "build_visual_tool_requirement": build_visual_tool_requirement,
            "required_visual_tool_names": required_visual_tool_names,
            "visual_tool_capability_names": visual_tool_capability_names,
            "filter_tools_for_visual_intent": lambda tools, _decision, structured_visuals_enabled: tools,
            "_should_strip_visual_tools_from_direct": lambda _query, _decision: False,
            "_normalize_for_intent": lambda text: text.lower(),
            "_needs_web_search": lambda _query: False,
            "_needs_datetime": lambda _query: False,
            "_needs_news_search": lambda _query: False,
            "_needs_legal_search": lambda _query: False,
            "_needs_analysis_tool": lambda _query: False,
            "_needs_lms_query": lambda _query: False,
            "_needs_direct_knowledge_search": lambda _query: False,
            "_infer_direct_thinking_mode": lambda _query, _state, _tool_names: "analytical_market",
            "_log_visual_telemetry": lambda *args, **kwargs: None,
        }
        return mapping[attr_name]

    monkeypatch.setattr(module, "_load_attr", fake_load_attr)

    tools, force_tools = module._collect_direct_tools("phân tích giá dầu")
    tool_names = {tool.name for tool in tools}

    assert "tool_web_search" in tool_names
    assert "tool_generate_visual" not in tool_names
    assert "tool_generate_mermaid" not in tool_names
    assert "tool_generate_interactive_chart" not in tool_names
    assert force_tools is False
