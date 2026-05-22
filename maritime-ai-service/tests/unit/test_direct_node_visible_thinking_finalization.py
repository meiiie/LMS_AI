from __future__ import annotations

from typing import Any

import pytest

from app.engine.multi_agent.direct_node_visible_thinking_finalization import (
    finalize_direct_node_visible_thinking,
)


def _record_snapshot(
    *,
    state: dict[str, Any],
    thinking: Any,
    provenance: str,
    record_thinking_snapshot_fn,
) -> str:
    text = str(thinking or "").strip()
    if text:
        state["thinking"] = text
        state["thinking_content"] = text
    record_thinking_snapshot_fn(state, text, provenance=provenance)
    return text


@pytest.mark.asyncio
async def test_finalize_visible_thinking_records_safe_aligned_thought() -> None:
    state: dict[str, Any] = {}
    snapshots: list[tuple[str, str]] = []

    async def align_thought(*_args: Any, **_kwargs: Any) -> str:
        return "minh nghe va tra loi gon"

    async def build_rescue(**_kwargs: Any) -> str:
        return ""

    await finalize_direct_node_visible_thinking(
        query="xin chao",
        state=state,
        response="Chao cau",
        thinking_content="raw thought",
        routing_intent="social",
        response_language="vi",
        llm=None,
        tools_used=[],
        build_direct_reasoning_summary=lambda **_kwargs: "",
        record_direct_node_thinking_snapshot=_record_snapshot,
        record_thinking_snapshot_fn=lambda _state, thinking, **kwargs: snapshots.append(
            (thinking, kwargs["provenance"])
        ),
        should_surface_direct_visible_thought_fn=lambda *_args, **_kwargs: True,
        align_direct_visible_thought_fn=align_thought,
        contains_direct_internal_thought_leak_fn=lambda _value: False,
        should_align_visible_thinking_language_fn=lambda *_args, **_kwargs: False,
        build_emotional_rescue_visible_thought_fn=build_rescue,
    )

    assert state["thinking_content"] == "minh nghe va tra loi gon"
    assert snapshots == [("minh nghe va tra loi gon", "aligned_cleanup")]


@pytest.mark.asyncio
async def test_finalize_visible_thinking_clears_unsafe_thought_then_records_rescue() -> None:
    state: dict[str, Any] = {"thinking": "old", "thinking_content": "old"}

    async def align_thought(*_args: Any, **_kwargs: Any) -> str:
        return "internal plan leak"

    async def build_rescue(**kwargs: Any) -> str:
        return f"rescue with {len(kwargs['tool_names'])} tool"

    await finalize_direct_node_visible_thinking(
        query="minh met qua",
        state=state,
        response="Minh o day",
        thinking_content="private chain",
        routing_intent="emotional_support",
        response_language="vi",
        llm=None,
        tools_used=[{"name": "tool_web_search"}],
        build_direct_reasoning_summary=lambda **_kwargs: "summary",
        record_direct_node_thinking_snapshot=_record_snapshot,
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        should_surface_direct_visible_thought_fn=lambda *_args, **_kwargs: True,
        align_direct_visible_thought_fn=align_thought,
        contains_direct_internal_thought_leak_fn=lambda _value: True,
        should_align_visible_thinking_language_fn=lambda *_args, **_kwargs: False,
        build_emotional_rescue_visible_thought_fn=build_rescue,
    )

    assert state["thinking_content"] == "rescue with 1 tool"
    assert state["thinking"] == "rescue with 1 tool"


@pytest.mark.asyncio
async def test_finalize_visible_thinking_leaves_state_clear_when_no_rescue() -> None:
    state: dict[str, Any] = {"thinking": "old", "thinking_content": "old"}

    async def build_rescue(**_kwargs: Any) -> str:
        return ""

    await finalize_direct_node_visible_thinking(
        query="ok",
        state=state,
        response="Ok",
        thinking_content="",
        routing_intent="social",
        response_language="vi",
        llm=None,
        tools_used=[],
        build_direct_reasoning_summary=lambda **_kwargs: "",
        record_direct_node_thinking_snapshot=_record_snapshot,
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        should_surface_direct_visible_thought_fn=lambda *_args, **_kwargs: False,
        build_emotional_rescue_visible_thought_fn=build_rescue,
    )

    assert "thinking" not in state
    assert state["thinking_content"] == ""
