from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engine.multi_agent.agents.tutor_request_runtime import prepare_tutor_request


class _Tool:
    def __init__(self, name: str):
        self.name = name


def test_prepare_tutor_request_only_forces_knowledge_search_by_default():
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=llm)

    tools = [
        _Tool("tool_knowledge_search"),
        _Tool("tool_think"),
        _Tool("tool_report_progress"),
        _Tool("tool_generate_visual"),
    ]

    with patch(
        "app.engine.multi_agent.agents.tutor_request_runtime.filter_tools_for_role",
        side_effect=lambda runtime_tools, _role: list(runtime_tools),
    ), patch(
        "app.engine.multi_agent.agents.tutor_request_runtime.filter_tools_for_visual_intent",
        side_effect=lambda runtime_tools, _visual_decision, structured_visuals_enabled=False: list(runtime_tools),
    ), patch(
        "app.engine.skills.skill_recommender.select_runtime_tools",
        return_value=[
            _Tool("tool_knowledge_search"),
            _Tool("tool_generate_visual"),
        ],
    ) as mock_select:
        result = prepare_tutor_request(
            state={"query": "Giai thich Rule 15", "routing_metadata": {"intent": "learning"}},
            context={"user_role": "student"},
            learning_context={},
            default_llm=llm,
            base_tools=tools,
            settings_obj=SimpleNamespace(enable_structured_visuals=True),
            logger_obj=MagicMock(),
            resolve_visual_intent_fn=lambda _query: SimpleNamespace(force_tool=False),
            required_visual_tool_names_fn=lambda _decision: [],
            get_effective_provider_fn=lambda _state: None,
            get_llm_fn=lambda *_args, **_kwargs: llm,
            resolve_tool_choice_fn=lambda *_args, **_kwargs: "auto",
        )

    assert mock_select.call_args.kwargs["must_include"] == ["tool_knowledge_search"]
    assert [tool.name for tool in result.active_tools] == [
        "tool_knowledge_search",
        "tool_generate_visual",
    ]


def test_prepare_tutor_request_copies_runtime_metadata_to_bound_llm():
    llm = MagicMock()
    llm._wiii_provider_name = "zhipu"
    llm._wiii_model_name = "glm-5"
    bound_llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=bound_llm)

    result = prepare_tutor_request(
        state={"query": "Giai thich Rule 15", "routing_metadata": {"intent": "learning"}},
        context={"user_role": "student"},
        learning_context={},
        default_llm=llm,
        base_tools=[_Tool("tool_knowledge_search")],
        settings_obj=SimpleNamespace(enable_structured_visuals=False),
        logger_obj=MagicMock(),
        resolve_visual_intent_fn=lambda _query: SimpleNamespace(force_tool=False),
        required_visual_tool_names_fn=lambda _decision: [],
        get_effective_provider_fn=lambda _state: None,
        get_llm_fn=lambda *_args, **_kwargs: llm,
        resolve_tool_choice_fn=lambda *_args, **_kwargs: "auto",
    )

    assert getattr(result.llm_with_tools_for_request, "_wiii_provider_name", None) == "zhipu"
    assert getattr(result.llm_with_tools_for_request, "_wiii_model_name", None) == "glm-5"


def test_prepare_tutor_request_forces_visual_tool_for_learning_intent():
    llm = MagicMock()
    bound_llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=bound_llm)

    tools = [
        _Tool("tool_knowledge_search"),
        _Tool("tool_generate_visual"),
        _Tool("tool_report_progress"),
    ]

    visual_decision = SimpleNamespace(force_tool=True, presentation_intent="article_figure")

    with patch(
        "app.engine.multi_agent.agents.tutor_request_runtime.filter_tools_for_role",
        side_effect=lambda runtime_tools, _role: list(runtime_tools),
    ), patch(
        "app.engine.multi_agent.agents.tutor_request_runtime.filter_tools_for_visual_intent",
        side_effect=lambda runtime_tools, _visual_decision, structured_visuals_enabled=False: list(runtime_tools),
    ), patch(
        "app.engine.skills.skill_recommender.select_runtime_tools",
        return_value=[
            _Tool("tool_knowledge_search"),
            _Tool("tool_generate_visual"),
        ],
    ):
        result = prepare_tutor_request(
            state={
                "query": "Create a compact inline visual comparing soft attention and linear attention.",
                "routing_metadata": {"intent": "learning"},
            },
            context={"user_role": "student"},
            learning_context={},
            default_llm=llm,
            base_tools=tools,
            settings_obj=SimpleNamespace(enable_structured_visuals=True),
            logger_obj=MagicMock(),
            resolve_visual_intent_fn=lambda _query: visual_decision,
            required_visual_tool_names_fn=lambda _decision: ["tool_generate_visual"],
            get_effective_provider_fn=lambda _state: None,
            get_llm_fn=lambda *_args, **_kwargs: llm,
            resolve_tool_choice_fn=lambda _force, selected_tools, _provider: selected_tools[0].name,
        )

    assert result.llm_with_tools_for_request is bound_llm
    bind_args, bind_kwargs = llm.bind_tools.call_args
    assert [tool.name for tool in bind_args[0]] == ["tool_generate_visual"]
    assert bind_kwargs["tool_choice"] == "tool_generate_visual"
