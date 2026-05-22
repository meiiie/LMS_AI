from __future__ import annotations

import logging
from typing import Any

import pytest

from app.engine.multi_agent.direct_node_host_timeout import (
    run_direct_node_execution_with_host_timeout,
)


@pytest.mark.asyncio
async def test_run_direct_node_execution_without_host_timeout_returns_execution_result() -> None:
    async def direct_execution() -> tuple[str, list[Any], list[dict[str, Any]]]:
        return "ok", ["message"], [{"type": "result"}]

    async def push_event(_event: dict[str, Any]) -> None:
        raise AssertionError("non-host turns should not emit fallback events")

    result = await run_direct_node_execution_with_host_timeout(
        direct_execution=direct_execution(),
        routing_intent="chat",
        state={},
        messages=[],
        push_event=push_event,
        timeout_seconds=0.01,
        logger_obj=logging.getLogger(__name__),
    )

    assert result == ("ok", ["message"], [{"type": "result"}])


@pytest.mark.asyncio
async def test_run_direct_node_execution_host_timeout_emits_standalone_fallback() -> None:
    events: list[dict[str, Any]] = []

    async def direct_execution() -> tuple[str, list[Any], list[dict[str, Any]]]:
        import asyncio

        await asyncio.sleep(0.05)
        return "late", [], []

    async def push_event(event: dict[str, Any]) -> None:
        events.append(event)

    llm_response, messages, tool_events = await run_direct_node_execution_with_host_timeout(
        direct_execution=direct_execution(),
        routing_intent="host_ui_navigation",
        state={"host_context": {"host_type": "wiii-web"}},
        messages=["existing"],
        push_event=push_event,
        timeout_seconds=0.001,
        logger_obj=logging.getLogger(__name__),
    )

    content = getattr(llm_response, "content", "")
    assert "Mình đã thử trỏ chuột" in content
    assert "panel Wiii" not in content
    assert messages == ["existing"]
    assert tool_events == []
    assert events == [{"type": "answer_delta", "content": content, "node": "direct"}]
