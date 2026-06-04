from types import SimpleNamespace

from app.engine.multi_agent.direct_node_turn_policy import (
    resolve_direct_node_turn_policy,
)


def _base_policy_kwargs(**overrides):
    kwargs = {
        "query": "xin chao",
        "state": {
            "context": {"response_language": "vi"},
            "routing_metadata": {},
        },
        "has_uploaded_document_context": False,
        "normalize_for_intent": lambda text: text.lower(),
        "looks_identity_selfhood_turn": lambda _query: False,
        "needs_web_search": lambda _query: False,
        "needs_datetime": lambda _query: False,
        "resolve_visual_intent": lambda _query: SimpleNamespace(force_tool=False),
        "recommended_visual_thinking_effort": lambda *_args, **_kwargs: None,
        "get_active_code_studio_session": lambda _state: None,
        "merge_thinking_effort": lambda current, visual: visual or current,
        "get_effective_provider": lambda _state: "qwen",
        "get_explicit_user_provider": lambda _state: None,
        "looks_uploaded_document_preview_request": lambda _query: False,
        "logger_obj": None,
    }
    kwargs.update(overrides)
    return kwargs


def test_resolve_direct_node_turn_policy_short_social_chatter():
    state = {
        "context": {"response_language": "vi"},
        "routing_metadata": {"intent": "social"},
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(query="he nhe", state=state)
    )

    assert result.ctx is state["context"]
    assert result.response_language == "vi"
    assert result.routing_intent == "social"
    assert result.is_short_house_chatter is True
    assert result.history_limit == 0
    assert result.tools_context_override == ""
    assert result.role_name == "direct_chatter_agent"
    assert result.thinking_effort == "low"
    assert result.use_house_voice_direct is True
    assert result.direct_provider_override == "qwen"


def test_resolve_direct_node_turn_policy_forced_path_overrides_chatter():
    state = {
        "context": {"response_language": "vi"},
        "routing_metadata": {"intent": "social", "method": "always_on_social_fast_path"},
        "_turn_path_decision": {
            "path": "weather_lookup",
            "bind_tools": True,
            "force_tools": True,
        },
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(query="nay thoi tiet nong nhi", state=state)
    )

    assert result.is_short_house_chatter is False
    assert result.tools_context_override is None
    assert result.role_name == "direct_agent"
    assert result.use_house_voice_direct is False


def test_resolve_direct_node_turn_policy_social_followup_keeps_recent_history():
    state = {
        "context": {"response_language": "vi"},
        "routing_metadata": {"intent": "social", "method": "conservative_fast_path"},
        "_routing_hint": {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social_followup",
        },
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(query="sao lại z", state=state)
    )

    assert result.is_short_house_chatter is True
    assert result.history_limit == 4
    assert result.tools_context_override == ""
    assert result.role_name == "direct_chatter_agent"


def test_resolve_direct_node_turn_policy_social_followup_without_hint_uses_chatter():
    state = {
        "context": {"response_language": "vi"},
        "routing_metadata": {"intent": "unknown"},
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(query="sao lại z", state=state)
    )

    assert result.is_short_house_chatter is True
    assert result.history_limit == 4
    assert result.tools_context_override == ""
    assert result.role_name == "direct_chatter_agent"


def test_resolve_direct_node_turn_policy_hunger_and_status_hints_use_chatter():
    for shape, query in (
        ("hunger_chatter", "minh dang doi qua a ma nay nong dieng"),
        ("social_status", "trua nay an com roi"),
    ):
        state = {
            "context": {"response_language": "vi"},
            "routing_metadata": {"intent": "social", "method": "conservative_fast_path"},
            "_routing_hint": {
                "kind": "fast_chatter",
                "intent": "social",
                "shape": shape,
            },
        }

        result = resolve_direct_node_turn_policy(
            **_base_policy_kwargs(query=query, state=state)
        )

        assert result.is_short_house_chatter is True
        assert result.tools_context_override == ""
        assert result.role_name == "direct_chatter_agent"


def test_resolve_direct_node_turn_policy_identity_keeps_context_history():
    state = {
        "context": {"response_language": "vi"},
        "routing_metadata": {"intent": "social"},
        "_routing_hint": {"kind": "identity_probe"},
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(query="ban la ai", state=state)
    )

    assert result.is_identity_turn is True
    assert result.is_short_house_chatter is False
    assert result.history_limit == 10
    assert result.tools_context_override is None
    assert result.role_name == "direct_chatter_agent"
    assert result.thinking_effort == "high"


def test_resolve_direct_node_turn_policy_visual_effort_and_explicit_provider():
    state = {
        "context": {"response_language": "en"},
        "routing_metadata": {"intent": "general"},
        "thinking_effort": "low",
    }

    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(
            query="tao mo phong canvas",
            state=state,
            recommended_visual_thinking_effort=lambda *_args, **_kwargs: "high",
            get_explicit_user_provider=lambda _state: "openai",
            merge_thinking_effort=lambda current, visual: f"{current}+{visual}",
        )
    )

    assert result.response_language == "en"
    assert result.thinking_effort == "low+high"
    assert result.explicit_user_provider == "openai"
    assert result.direct_provider_override == "openai"


def test_resolve_direct_node_turn_policy_codebase_excludes_uploaded_preview():
    result = resolve_direct_node_turn_policy(
        **_base_policy_kwargs(
            query="Bao cao source notes ve jwt auth trong codebase",
            has_uploaded_document_context=True,
            looks_uploaded_document_preview_request=lambda _query: True,
        )
    )

    assert result.is_codebase_source_turn is False
    assert result.explicit_web_search_turn is False
