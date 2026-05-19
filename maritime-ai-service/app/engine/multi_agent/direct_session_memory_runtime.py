"""Current-session memory fast-path helpers for the direct node."""

from __future__ import annotations

import re
from typing import Any

from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor_runtime_support import (
    _looks_memory_write_turn,
    _looks_session_memory_recall_turn,
)


def _message_content_from_any(value: Any) -> str:
    if isinstance(value, dict):
        content = value.get("content") or value.get("text") or value.get("message") or ""
    else:
        content = getattr(value, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "\n".join(part for part in parts if part.strip()).strip()
    return str(content or "").strip()


_SESSION_MEMORY_NOISE_RE = re.compile(
    r"(?:mã|ma)\s+(?:kiểm\s+thử|kiem\s+thu|test)\s+[A-Za-z0-9_.:]*-[A-Za-z0-9_.:-]+.*$",
    flags=re.IGNORECASE,
)


_SESSION_MEMORY_FIELD_MARKER_RE = re.compile(r"(\[[A-Z][A-Z0-9_.:-]{3,}\])")


def _clean_session_memory_fragment(value: str) -> str:
    cleaned = _SESSION_MEMORY_NOISE_RE.sub("", str(value or "")).strip()
    cleaned = re.sub(r"^(?:[-*]\s*)+", "", cleaned).strip()
    cleaned = re.split(
        r"\b(?:Hỏi\s+lại\s+ngay|Hoi\s+lai\s+ngay|Hỏi\s+lại|Hoi\s+lai)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return cleaned.strip(" .ã€‚")


def _extract_requested_response_marker(query: str) -> str:
    """Preserve explicit field-test markers when the user asks for them."""
    raw = str(query or "")
    folded = _fold_direct_text(raw)
    if not any(marker in folded for marker in ("bat dau bang", "begin with", "start with")):
        return ""
    match = _SESSION_MEMORY_FIELD_MARKER_RE.search(raw)
    return match.group(1) if match else ""


def _with_requested_response_marker(query: str, answer: str) -> str:
    marker = _extract_requested_response_marker(query)
    if not marker:
        return answer
    if answer.lstrip().startswith(marker):
        return answer
    if answer.lstrip().startswith("- "):
        return f"{marker}\n{answer}"
    return f"{marker} {answer}"


def _extract_session_memory_items_from_text(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    folded = _fold_direct_text(raw)
    if not _looks_memory_write_turn(folded):
        return []

    before_reply_directive = re.split(
        r"\b(?:trả\s+lời|tra\s+loi|chỉ\s+xác\s+nhận|chi\s+xac\s+nhan|answer\s+only|reply\s+only|respond\s+only)\b",
        raw,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    before_reply_directive = re.split(
        r"\b(?:không\s+(?:sử\s+dụng|dùng)\s+(?:web|rag|pointy|tool|công\s+cụ)|khong\s+(?:su\s+dung|dung)\s+(?:web|rag|pointy|tool|cong\s+cu)|do\s+not\s+use\s+(?:web|rag|pointy|tools?)|without\s+(?:web|rag|pointy|tools?))\b",
        before_reply_directive,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    marker_split = re.split(
        r"\b(?:hãy\s+nhớ|hay\s+nho|ghi\s+nhớ|ghi\s+nho|nhớ\s+trong|nho\s+trong|nhớ\s+giúp(?:\s+mình)?|nho\s+giup(?:\s+minh)?|nhớ\s+rằng|nho\s+rang|remember\s+that|please\s+remember|keep\s+in\s+mind|lưu\s+lại|luu\s+lai)\b",
        before_reply_directive,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    segment_source = marker_split[-1].strip(" :：") if len(marker_split) > 1 else before_reply_directive
    segment = re.split(r"[:：]", segment_source)[-1].strip()
    if not segment or segment == before_reply_directive:
        return []

    numbered_items = [
        _clean_session_memory_fragment(match.group(1).strip(" .)]"))
        for match in re.finditer(
            r"(?:^|\s)[\(\[]?\d+[\)\].]\s*(.*?)(?=\s+[\(\[]?\d+[\)\].]\s*|$)",
            segment,
            flags=re.DOTALL,
        )
        if len(_clean_session_memory_fragment(match.group(1).strip(" .)]"))) >= 4
    ]
    if len(numbered_items) >= 2:
        return numbered_items

    pieces = re.split(r"\s*(?:,|;|\n+|\s+và\s+|\s+va\s+|\s+and\s+)\s*", segment)
    items: list[str] = []
    for piece in pieces:
        item = re.sub(r"^(?:và|va|and)\s+", "", piece.strip(), flags=re.IGNORECASE)
        item = item.strip(" .。")
        item = _clean_session_memory_fragment(item)
        if len(item) < 4:
            continue
        if re.search(r"\b(?:trả\s+lời|tra\s+loi|chỉ\s+xác\s+nhận|chi\s+xac\s+nhan|answer\s+only|reply\s+only)\b", item, re.IGNORECASE):
            continue
        items.append(item)
    return _merge_session_priority_items(items)


def _merge_session_priority_items(items: list[str]) -> list[str]:
    """Keep labeled multi-part bundles as one recallable memory item."""
    merged: list[str] = []
    index = 0
    while index < len(items):
        item = items[index]
        folded = _fold_direct_text(item)
        is_anchor_fact = bool(re.search(r"\b[A-Z0-9_:-]*ANCHOR[A-Z0-9_:-]*\b", item))
        if merged and not is_anchor_fact and "anchor" in _fold_direct_text(merged[-1]):
            merged[-1] = f"{merged[-1]} va {item}"
            index += 1
            continue

        is_labeled_bundle = "uu tien" in folded or "tieu chi" in folded
        if not is_labeled_bundle:
            merged.append(item)
            index += 1
            continue

        priority_parts = [item]
        index += 1
        while index < len(items):
            next_item = items[index]
            next_folded = _fold_direct_text(next_item)
            starts_new_labeled_fact = (
                re.search(r"\b(?:ma|mau|color|code|token)\b", next_folded) is not None
                or re.search(r"^(?:tieu chi|uu tien|priority|criterion)\b", next_folded) is not None
                or " la " in f" {next_folded} "
                or "=" in next_item
            )
            if starts_new_labeled_fact:
                break
            priority_parts.append(next_item)
            index += 1
        merged.append("; ".join(priority_parts))
    return merged


def _build_session_memory_write_answer(query: str) -> str:
    """Acknowledge current-session memory without invoking durable memory."""
    items = _extract_session_memory_items_from_text(query)
    if not items:
        return (
            "Mình ghi nhớ điều này trong phiên hiện tại rồi. Nếu cậu hỏi lại trong đoạn chat này, "
            "mình sẽ dựa vào đó thay vì đoán mò."
        )
    if len(items) == 1:
        return (
            f"Mình ghi nhớ trong phiên này rồi: **{items[0]}**. "
            "Hỏi lại ngay trong đoạn chat này là mình nhắc được."
        )
    lines = "\n".join(f"- {item}" for item in items[:5])
    return f"Mình ghi nhớ trong phiên này rồi:\n{lines}\n\nHỏi lại ngay trong đoạn chat này là mình nhắc được."


def _build_session_memory_write_thinking(_query: str) -> str:
    return (
        "Mình hiểu đây là trí nhớ tạm trong phiên, không phải một fact dài hạn cần đẩy qua semantic memory. "
        "Cách đúng là xác nhận cụ thể điều vừa giữ, trả lời nhanh, rồi để chính lịch sử hội thoại làm nguồn cho lượt nhắc lại kế tiếp."
    )


_SESSION_RECALL_STOPWORDS = {
    "ban",
    "bao",
    "cau",
    "cho",
    "dung",
    "gi",
    "hoi",
    "la",
    "minh",
    "nao",
    "nho",
    "noi",
    "tra",
    "loi",
    "vua",
}


def _session_recall_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _fold_direct_text(value))
        if token and token not in _SESSION_RECALL_STOPWORDS and len(token) > 1
    }


def _requested_session_memory_list_count(query: str) -> int | None:
    folded = _fold_direct_text(query)
    if not folded:
        return None
    list_noun = (
        r"(?:uu\s+tien|tieu\s+chi|criteria|anchor|neo|moc(?:\s+neo)?|diem\s+neo|"
        r"y|muc|gach|dau\s+dong|bullet)"
    )
    digit_match = re.search(rf"\b([2-9])\s+{list_noun}", folded)
    if digit_match:
        return int(digit_match.group(1))
    if re.search(rf"\bba\s+{list_noun}", folded):
        return 3
    if re.search(rf"\bhai\s+{list_noun}", folded):
        return 2
    if (
        "cac uu tien" in folded
        or "nhung uu tien" in folded
        or "cac tieu chi" in folded
        or "cac anchor" in folded
        or "nhung anchor" in folded
        or "cac neo" in folded
        or "nhung neo" in folded
        or "cac moc" in folded
    ):
        return 99
    return None


def _format_session_memory_item_for_query(item: str, query: str) -> str:
    folded_query = _fold_direct_text(query)
    if any(marker in folded_query for marker in ("ma ", "ma kiem thu", "code", "token", "mau ", "color")):
        match = re.search(r"\b(?:là|la|=)\s+(.+)$", item, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .。")
            value = _clean_session_memory_fragment(value).strip("\"'“”‘’")
            if 1 <= len(value) <= 120:
                return value
    return _clean_session_memory_fragment(item)


def _select_session_memory_items_for_query(items: list[str], query: str) -> list[str]:
    if not items:
        return []
    requested_count = _requested_session_memory_list_count(query)
    if requested_count is not None and requested_count >= 2:
        return items[: min(requested_count, len(items))]

    query_tokens = _session_recall_tokens(query)
    if not query_tokens:
        return items

    scored: list[tuple[int, int, str]] = []
    for index, item in enumerate(items):
        item_tokens = _session_recall_tokens(item)
        score = len(query_tokens & item_tokens)
        if "ma" in query_tokens and "ma" in item_tokens:
            score += 3
        if "uu" in query_tokens and "tien" in query_tokens and {"uu", "tien"} <= item_tokens:
            score += 3
        scored.append((score, -index, item))

    best_score = max(score for score, _index, _item in scored)
    if best_score <= 0:
        return items
    return [item for score, _index, item in scored if score == best_score]


def _query_requests_session_memory_test_impact(query: str) -> bool:
    folded = _fold_direct_text(query)
    return any(
        marker in folded
        for marker in (
            "anh huong test",
            "tac dong test",
            "anh huong kiem thu",
            "tac dong kiem thu",
            "test wiii",
            "kiem thu wiii",
        )
    )


def _format_session_memory_item_with_test_impact(item: str) -> str:
    cleaned = _clean_session_memory_fragment(item)
    folded = _fold_direct_text(cleaned)
    if "pointy" in folded and "dom" in folded:
        impact = (
            "Test Pointy phải quét DOM/inventory mới nhất trước khi highlight, "
            "nếu selector lệch hoặc target bị stale thì fail ngay."
        )
    elif "voice" in folded:
        impact = (
            "Test voice phải opt-in, có nút bỏ qua/hủy rõ ràng, "
            "và không tự ép người dùng nghe TTS khi họ chỉ muốn đọc."
        )
    elif "document" in folded or "video" in folded or "context" in folded:
        impact = (
            "Test upload phải trả lời từ context đã parse và nguồn đính kèm, "
            "không được đoán khi thiếu vision/transcript hoặc khi parser chưa đủ dữ kiện."
        )
    else:
        impact = (
            "Test dùng anchor này như checkpoint hồi quy: Wiii phải nhắc đúng, "
            "giữ đúng ngữ cảnh phiên và không tự bịa thêm thông tin."
        )
    return f"{cleaned} -> {impact}"


def _extract_session_memory_recall_answer(state: AgentState, query: str) -> str:
    folded_query = _fold_direct_text(query)
    if not _looks_session_memory_recall_turn(folded_query):
        return ""

    messages = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(messages, list):
        return ""

    current_query_folded = _fold_direct_text(query)
    for message in reversed(messages):
        content = _message_content_from_any(message)
        folded_content = _fold_direct_text(content)
        if not content or folded_content == current_query_folded:
            continue
        if _looks_session_memory_recall_turn(folded_content):
            continue
        items = _extract_session_memory_items_from_text(content)
        selected_items = _select_session_memory_items_for_query(items, query)
        if len(selected_items) == 1:
            return _format_session_memory_item_for_query(selected_items[0], query)
        if len(selected_items) >= 2:
            formatted_items = [
                (
                    _format_session_memory_item_with_test_impact(item)
                    if _query_requests_session_memory_test_impact(query)
                    else _clean_session_memory_fragment(item)
                )
                for item in selected_items[:5]
            ]
            return "\n".join(f"- {item}" for item in formatted_items if item)
    return ""
