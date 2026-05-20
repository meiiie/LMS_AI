import logging

from app.engine.multi_agent.direct_handoff_runtime import record_direct_handoff_request


def test_record_direct_handoff_request_sets_valid_target() -> None:
    state: dict = {}

    target = record_direct_handoff_request(
        state=state,
        tool_name="handoff_to_agent",
        tool_args={"target_agent": "rag_agent"},
        enabled=True,
        logger_obj=logging.getLogger(__name__),
    )

    assert target == "rag_agent"
    assert state["_handoff_target"] == "rag_agent"


def test_record_direct_handoff_request_ignores_disabled_handoffs() -> None:
    state: dict = {}

    target = record_direct_handoff_request(
        state=state,
        tool_name="handoff_to_agent",
        tool_args={"target_agent": "rag_agent"},
        enabled=False,
        logger_obj=logging.getLogger(__name__),
    )

    assert target is None
    assert "_handoff_target" not in state


def test_record_direct_handoff_request_ignores_non_handoff_tool() -> None:
    state: dict = {}

    target = record_direct_handoff_request(
        state=state,
        tool_name="tool_web_search",
        tool_args={"target_agent": "rag_agent"},
        enabled=True,
        logger_obj=logging.getLogger(__name__),
    )

    assert target is None
    assert "_handoff_target" not in state


def test_record_direct_handoff_request_ignores_invalid_target() -> None:
    state: dict = {}

    target = record_direct_handoff_request(
        state=state,
        tool_name="handoff_to_agent",
        tool_args={"target_agent": "unknown_agent"},
        enabled=True,
        logger_obj=logging.getLogger(__name__),
    )

    assert target is None
    assert "_handoff_target" not in state
