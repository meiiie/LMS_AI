from app.engine.multi_agent.direct_node_turn_start import start_direct_node_turn


def test_routing_web_search_intent_is_not_user_explicit_web_search():
    from app.engine.multi_agent.direct_node_operational_fast_paths import (
        _is_explicit_web_search_turn_for_direct,
    )

    assert (
        _is_explicit_web_search_turn_for_direct(
            "hom nay co gi hot",
            {"routing_metadata": {"intent": "web_search"}},
        )
        is False
    )
    assert (
        _is_explicit_web_search_turn_for_direct(
            "tim tren web hom nay co gi hot",
            {"routing_metadata": {"intent": "web_search"}},
        )
        is True
    )


def test_start_direct_node_turn_resolves_greeting_when_natural_conversation_disabled():
    state = {"domain_id": "maritime"}
    result = start_direct_node_turn(
        query="Xin Chao",
        state=state,
        enable_natural_conversation=False,
        default_domain="default",
        get_domain_greetings=lambda domain_id: {
            "xin chao": f"hello from {domain_id}",
        },
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
    )

    assert result.query_lower == "xin chao"
    assert result.response == "hello from maritime"
    assert result.response_type == "greeting"
    assert result.explicit_web_search_turn is False


def test_start_direct_node_turn_skips_greeting_when_natural_conversation_enabled():
    state = {"domain_id": "maritime"}
    result = start_direct_node_turn(
        query="Xin chao",
        state=state,
        enable_natural_conversation=True,
        default_domain="default",
        get_domain_greetings=lambda _domain_id: {
            "xin chao": "should not be used",
        },
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
    )

    assert result.response is None
    assert result.response_type == ""


def test_start_direct_node_turn_records_codebase_fast_path_snapshot():
    state: dict = {}
    snapshots: list[dict] = []

    def record_snapshot(*args, **kwargs):
        snapshots.append({"args": args, "kwargs": kwargs})

    result = start_direct_node_turn(
        query="Bao cao source notes ve jwt auth trong codebase",
        state=state,
        enable_natural_conversation=True,
        default_domain="default",
        get_domain_greetings=lambda _domain_id: {},
        record_thinking_snapshot_fn=record_snapshot,
    )

    assert result.response
    assert result.response_type == "codebase_source_backed_fast"
    assert result.explicit_web_search_turn is False
    assert "thinking_content" in state
    assert snapshots[0]["args"][0] is state
    assert snapshots[0]["kwargs"] == {
        "node": "direct",
        "provenance": "codebase_source_backed_plan",
    }


def test_start_direct_node_turn_does_not_fast_answer_explicit_web_search():
    state = {"routing_metadata": {"intent": "web_search"}}
    snapshots: list[object] = []

    result = start_direct_node_turn(
        query="@web-search Bao cao source notes ve jwt auth trong codebase",
        state=state,
        enable_natural_conversation=True,
        default_domain="default",
        get_domain_greetings=lambda _domain_id: {},
        record_thinking_snapshot_fn=lambda *args, **kwargs: snapshots.append(
            (args, kwargs)
        ),
    )

    assert result.response is None
    assert result.response_type == ""
    assert result.explicit_web_search_turn is True
    assert snapshots == []
