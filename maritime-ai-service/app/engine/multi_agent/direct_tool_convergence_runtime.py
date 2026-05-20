"""Post-tool convergence hints for direct tool-round execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.direct_tool_message_runtime import (
    build_user_instruction_message,
)

logger = logging.getLogger(__name__)

_SEARCH_TOOL_NAMES = {
    "tool_web_search",
    "tool_search_news",
    "tool_search_legal",
    "tool_search_maritime",
    "tool_fetch_url",
}


@dataclass(slots=True)
class DirectToolConvergenceHintResult:
    """Metadata for a convergence hint inserted after a tool round."""

    inserted: bool
    total_result_chars: int = 0
    kind: str | None = None


def append_direct_tool_convergence_hint(
    *,
    messages: list[Any],
    tool_round: int,
    tool_call_events: list[dict[str, Any]],
    requires_visual_commit: bool,
    native_tool_messages: bool,
    logger_obj: logging.Logger | None = None,
) -> DirectToolConvergenceHintResult:
    """Append the round-0 search convergence hint when the tool evidence needs it."""
    if tool_round != 0 or not tool_call_events or requires_visual_commit:
        return DirectToolConvergenceHintResult(inserted=False)

    had_search_tool = any(
        str(event.get("name") or "").strip() in _SEARCH_TOOL_NAMES
        for event in tool_call_events
        if event.get("type") == "call"
    )
    total_result_chars = sum(
        len(str(event.get("result") or ""))
        for event in tool_call_events
        if event.get("type") == "result"
    )
    if not had_search_tool:
        return DirectToolConvergenceHintResult(
            inserted=False,
            total_result_chars=total_result_chars,
        )

    target_logger = logger_obj or logger
    if total_result_chars < 2500:
        messages.append(
            build_user_instruction_message(
                "Đánh giá nhanh kết quả vừa rồi:\n"
                "- Số liệu cụ thể (giá / con số / ngày): ĐỦ hay THIẾU?\n"
                "- Bối cảnh / lý do biến động: ĐỦ hay THIẾU?\n"
                "- Tin nóng địa chính trị (Iran, OPEC+, Hormuz, Fed) "
                "có liên quan: đã search chưa?\n\n"
                "Nếu THIẾU mục nào → gọi 1 tool bổ sung (tool_search_news "
                "với query KHÁC, hoặc tool_fetch_url trên URL hứa hẹn nhất).\n"
                "Nếu ĐỦ → trả lời NGAY với cấu trúc: số liệu chính (bold) + "
                "bối cảnh 2-3 câu + takeaway 1-2 câu. KHÔNG search lại.\n\n"
                "Định dạng số: '110.01' KHÔNG '110, 01'; '13:18' KHÔNG '13: 18'.",
                native_tool_messages=native_tool_messages,
            )
        )
        target_logger.info(
            "[DIRECT] Convergence self-eval injected (round 0 sparse: %d chars)",
            total_result_chars,
        )
        return DirectToolConvergenceHintResult(
            inserted=True,
            total_result_chars=total_result_chars,
            kind="sparse_self_eval",
        )

    messages.append(
        build_user_instruction_message(
            "Kết quả search đã đủ phong phú. Trả lời NGAY (KHÔNG gọi "
            "thêm tool) với cấu trúc: số liệu chính (bold) + bối cảnh "
            "2-3 câu + takeaway 1-2 câu.\n"
            "Định dạng số: '110.01' KHÔNG '110, 01'; '13:18' KHÔNG '13: 18'.",
            native_tool_messages=native_tool_messages,
        )
    )
    target_logger.info(
        "[DIRECT] Convergence STOP-hint injected (round 0 rich: %d chars)",
        total_result_chars,
    )
    return DirectToolConvergenceHintResult(
        inserted=True,
        total_result_chars=total_result_chars,
        kind="rich_stop_hint",
    )
