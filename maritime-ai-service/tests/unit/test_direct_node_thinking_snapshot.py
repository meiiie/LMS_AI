def test_record_direct_node_thinking_snapshot_stores_state_and_snapshot():
    from app.engine.multi_agent.direct_node_thinking_snapshot import (
        record_direct_node_thinking_snapshot,
    )

    state: dict = {}
    calls: list[dict] = []

    def record_snapshot(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})

    result = record_direct_node_thinking_snapshot(
        state=state,
        thinking="  dang doi chieu nguon  ",
        provenance="deterministic_test",
        record_thinking_snapshot_fn=record_snapshot,
    )

    assert result == "dang doi chieu nguon"
    assert state["thinking"] == "dang doi chieu nguon"
    assert state["thinking_content"] == "dang doi chieu nguon"
    assert calls == [
        {
            "args": (state, "dang doi chieu nguon"),
            "kwargs": {"node": "direct", "provenance": "deterministic_test"},
        }
    ]


def test_record_direct_node_thinking_snapshot_ignores_empty_thinking():
    from app.engine.multi_agent.direct_node_thinking_snapshot import (
        record_direct_node_thinking_snapshot,
    )

    state: dict = {"thinking": "old", "thinking_content": "old"}
    calls: list[dict] = []

    result = record_direct_node_thinking_snapshot(
        state=state,
        thinking="  ",
        provenance="deterministic_test",
        record_thinking_snapshot_fn=lambda *args, **kwargs: calls.append(
            {"args": args, "kwargs": kwargs}
        ),
    )

    assert result == ""
    assert state == {"thinking": "old", "thinking_content": "old"}
    assert calls == []
