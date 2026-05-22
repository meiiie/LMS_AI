"""Direct-node host UI timeout handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.state import AgentState


async def run_direct_node_execution_with_host_timeout(
    *,
    direct_execution: Awaitable[tuple[Any, list[Any], list[dict[str, Any]]]],
    routing_intent: str,
    state: AgentState,
    messages: list[Any],
    push_event: Callable[[dict[str, Any]], Awaitable[None]],
    timeout_seconds: float,
    logger_obj: logging.Logger,
) -> tuple[Any, list[Any], list[dict[str, Any]]]:
    if routing_intent != "host_ui_navigation":
        return await direct_execution

    try:
        return await asyncio.wait_for(direct_execution, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        from app.engine.native_chat_runtime import make_assistant_message

        logger_obj.warning(
            "[DIRECT] Host UI navigation answer exceeded %.1fs; returning bounded fallback",
            timeout_seconds,
        )
        host_ctx = state.get("host_context") if isinstance(state, dict) else None
        host_type = (host_ctx or {}).get("host_type", "") if isinstance(host_ctx, dict) else ""
        is_standalone = host_type in ("wiii-desktop", "wiii-web")
        if is_standalone:
            fallback_answer = (
                "Mình đã thử trỏ chuột vào element rồi. Nếu chưa thấy "
                "cursor di chuyển, bạn thử gửi lại câu hỏi nhé - "
                "đôi khi LLM cần thêm chút thời gian xử lý."
            )
        else:
            fallback_answer = (
                "Mình đã nhận yêu cầu trỏ trên giao diện rồi. "
                "Nếu Wiii chưa highlight ngay, hãy thử mở lại panel Wiii hoặc làm mới trang LMS nhé."
            )
        await push_event(
            {
                "type": "answer_delta",
                "content": fallback_answer,
                "node": "direct",
            }
        )
        return make_assistant_message(fallback_answer), messages, []
