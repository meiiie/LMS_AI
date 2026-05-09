from unittest.mock import patch

import pytest

from app.engine.multi_agent.graph_streaming import process_with_multi_agent_streaming


def _pointy_context():
    return {
        "host_context": {
            "page": {
                "type": "chat",
                "metadata": {
                    "available_targets": [
                        {
                            "id": "chat-send-button",
                            "selector": '[data-wiii-id="chat-send-button"]',
                            "label": "Gửi tin nhắn",
                            "visible": True,
                            "click_safe": False,
                        }
                    ],
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_pointy_highlight_stream_finishes_without_graph_or_llm():
    with patch(
        "app.engine.multi_agent.graph_streaming.build_stream_bootstrap_impl",
        side_effect=AssertionError("safe pointy highlight should not start the graph"),
    ):
        events = [
            event
            async for event in process_with_multi_agent_streaming(
                "Pointy hãy chỉ vào nút Gửi tin nhắn.",
                user_id="u1",
                session_id="s1",
                context=_pointy_context(),
            )
        ]

    event_types = [event.type for event in events]

    assert event_types == [
        "status",
        "pointy_action",
        "thinking_start",
        "thinking_delta",
        "thinking_end",
        "answer",
        "metadata",
        "done",
    ]
    assert events[1].content["params"]["selector"] == "chat-send-button"
    assert events[5].content == "Đây là Gửi tin nhắn. Wiii trỏ vào để bạn thấy ngay."
    assert events[6].content["provider"] == "deterministic"
    assert events[6].content["routing_metadata"]["method"] == "pointy_fast_path"
