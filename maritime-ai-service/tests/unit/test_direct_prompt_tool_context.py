from types import SimpleNamespace

from app.engine.multi_agent.direct_prompt_tool_binding import (
    _bind_direct_tools,
    _resolve_tool_choice,
    _tool_name,
)
from app.engine.multi_agent.direct_prompt_tool_context import (
    _build_code_studio_tools_context,
    _build_direct_tools_context,
)


class _DummySettings:
    enable_browser_agent = False
    enable_character_tools = False
    enable_code_execution = False
    enable_llm_code_gen_visuals = False
    enable_natural_conversation = False
    enable_privileged_sandbox = False
    enable_structured_visuals = False
    sandbox_allow_browser_workloads = False
    sandbox_provider = ""


class _Skill:
    def __init__(self, name: str):
        self.name = name

    def metadata_block(self) -> str:
        return f"### Skill `{self.name}`"

    def full_body(self) -> str:
        return f"## SKILL: {self.name}\n\nfull body"


class _DummyLLM:
    def __init__(self):
        self.bind_calls = []

    def bind_tools(self, tools, tool_choice=None):
        bound = _DummyLLM()
        bound.bind_calls = [*self.bind_calls, (tools, tool_choice)]
        return bound


def test_tool_name_prefers_named_runtime_objects():
    assert _tool_name(SimpleNamespace(name="tool_demo")) == "tool_demo"
    assert _tool_name(lambda: None) == "<lambda>"


def test_resolve_tool_choice_keeps_provider_specific_force_modes():
    tools = [SimpleNamespace(name="tool_a"), SimpleNamespace(name="tool_b")]

    assert _resolve_tool_choice(False, tools, provider="openai") is None
    assert _resolve_tool_choice(True, [SimpleNamespace(name="tool_exact")]) == "tool_exact"
    assert _resolve_tool_choice(True, tools, provider="openai") == "required"
    assert _resolve_tool_choice(True, tools, provider="google") == "any"


def test_bind_direct_tools_preserves_legacy_tuple_and_forced_choice():
    llm = _DummyLLM()
    tool = SimpleNamespace(name="tool_exact")

    llm_with_tools, llm_auto, forced_choice = _bind_direct_tools(
        llm,
        [tool],
        True,
        include_forced_choice=True,
    )

    assert forced_choice == "tool_exact"
    assert llm_auto.bind_calls == [([tool], None)]
    assert llm_with_tools.bind_calls == [([tool], "tool_exact")]


def test_direct_tools_context_omits_skill_inventory_without_turn_inputs(monkeypatch):
    from app.engine.skills import library_loader

    monkeypatch.setattr(
        library_loader,
        "load_library_skills",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not load skills")),
    )

    result = _build_direct_tools_context(_DummySettings(), "Hang hai")

    assert "tool_web_search" in result
    assert "Anthropic format" not in result


def test_direct_tools_context_uses_explicit_query_and_state_for_skill_injection(monkeypatch):
    from app.engine.multi_agent import tool_collection
    from app.engine.skills import library_loader

    skills = [_Skill("visual-code-gen"), _Skill("wiii-pointy"), _Skill("web-search")]
    monkeypatch.setattr(library_loader, "load_library_skills", lambda *args, **kwargs: skills)
    monkeypatch.setattr(library_loader, "match_skills_for_query", lambda query: [skills[0]])
    monkeypatch.setattr(tool_collection, "_force_skills_from_state", lambda state: {"wiii-pointy"})

    result = _build_direct_tools_context(
        _DummySettings(),
        "Hang hai",
        query="tao visual code",
        state={"context": {"force_skills": ["wiii-pointy"]}},
    )

    assert "## SKILL: visual-code-gen" in result
    assert "## SKILL: wiii-pointy" in result
    assert "### Skill `web-search`" in result


def test_code_studio_tools_context_stays_focused_for_admin_execution():
    settings = _DummySettings()
    settings.enable_code_execution = True

    result = _build_code_studio_tools_context(settings, user_role="admin")

    assert "tool_execute_python" in result
    assert "CODE STUDIO TOOLKIT" in result
