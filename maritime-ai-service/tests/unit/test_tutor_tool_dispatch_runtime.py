import json
import logging
from types import SimpleNamespace

import pytest

from app.engine.multi_agent.agents.tutor_tool_dispatch_runtime import (
    dispatch_tutor_tool_call,
)
from app.engine.tools.visual_tools import tool_generate_visual


def _tool_name(tool):
    return getattr(tool, "name", getattr(tool, "__name__", ""))


@pytest.mark.asyncio
async def test_tutor_visual_tool_dispatch_emits_lifecycle_events():
    events = []
    tools_used = []
    messages = []

    async def push(event):
        events.append(event)

    async def invoke_tool_with_runtime(tool, tool_args, **_kwargs):
        return tool.invoke(tool_args)

    async def noop_thinking(_text):
        return None

    async def noop_acknowledgment(**_kwargs):
        return ""

    result = await dispatch_tutor_tool_call(
        tool_call={
            "name": "tool_generate_visual",
            "args": {
                "visual_type": "comparison",
                "spec_json": json.dumps(
                    {
                        "left": {"title": "Softmax attention"},
                        "right": {"title": "Linear attention"},
                    }
                ),
                "title": "Softmax vs Linear",
                "summary": "Quick comparison",
            },
            "id": "vis-1",
        },
        query="Create a compact inline visual comparing soft attention and linear attention.",
        context={},
        iteration=0,
        tools_used=tools_used,
        tools=[tool_generate_visual],
        messages=messages,
        runtime_context_base={},
        push=push,
        push_thinking_deltas=noop_thinking,
        iteration_beat_fn=lambda **_kwargs: SimpleNamespace(
            label="",
            summary="",
            phase="",
            fragments=[],
        ),
        tool_acknowledgment_fn=noop_acknowledgment,
        get_tool_by_name_fn=lambda runtime_tools, name: next(
            (tool for tool in runtime_tools if _tool_name(tool) == name),
            None,
        ),
        invoke_tool_with_runtime_fn=invoke_tool_with_runtime,
        get_last_confidence_fn=lambda: (0.0, False),
        knowledge_tool=None,
        calculator_tool=None,
        datetime_tool=None,
        web_search_tool=None,
        max_iterations=2,
        max_phase_transitions=2,
        phase_transition_count=0,
        logger_obj=logging.getLogger(__name__),
    )

    event_types = [event["type"] for event in events]
    assert "visual_open" in event_types
    assert "visual_commit" in event_types
    assert event_types.index("visual_open") < event_types.index("visual_commit")
    assert event_types[-1] == "tool_result"
    assert "VISUAL_PAYLOAD" not in events[-1]["content"]["result"]
    assert tools_used[0]["name"] == "tool_generate_visual"
    assert result.tool_result_text
