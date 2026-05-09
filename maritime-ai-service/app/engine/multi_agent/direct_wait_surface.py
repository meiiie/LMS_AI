"""Compact wait-surface helpers for direct and Code Studio lanes.

These helpers generate short public-facing wait beats and labels without
touching execution state, tool orchestration, or streaming control flow.
"""

from __future__ import annotations

from typing import Optional

from app.engine.multi_agent.direct_intent import _looks_identity_selfhood_turn, _normalize_for_intent


def _compact_visible_query(query: str, max_len: int = 72) -> str:
    compact = " ".join((query or "").split())
    lowered = compact.lower()
    if not compact:
        return "câu này"
    if any(marker in lowered for marker in ("mo phong", "simulation", "canvas", "widget", "artifact")):
        return "yêu cầu mô phỏng này"
    if any(marker in lowered for marker in ("visual", "bieu do", "chart", "thong ke")):
        return "yêu cầu trực quan này"
    if len(compact.split()) <= 8:
        return "nhịp này"
    if len(compact) > max_len:
        compact = f"{compact[: max_len - 1].rstrip()}..."
    return "điều bạn vừa hỏi"


def _build_direct_wait_heartbeat_text(
    *,
    query: str,
    phase: str,
    cue: str,
    beat_index: int,
    elapsed_sec: float,
    tool_names: Optional[list[str]] = None,
) -> str:
    """Return a compact, beat-progressive heartbeat that tells the user what
    Wiii is currently doing — not just that it's "thinking".

    Phase 35 redesign: Cursor IDE / Claude artifact pattern. Each beat
    advances the perceived phase even when no real backend signal is
    available, so users never see the same message twice in a row.

    Phase mapping:
      - "ground"   → tools just executed; LLM is reading results
      - "verify"   → cross-check + integrate
      - "synthesize" → composing prose answer
      - default → unknown phase, generic but progressive
    """
    del elapsed_sec  # tracked client-side via StreamingTimer

    normalized_query = _normalize_for_intent(query)

    # Identity/personal turns — keep the calm tone (no progress chatter).
    if cue == "identity" or _looks_identity_selfhood_turn(query):
        if beat_index <= 1:
            return "Mình đang nghĩ kỹ về câu này để đáp thành thật."
        return "Mình giữ nhịp thật gần để câu sau ra đúng với bạn hơn."

    if cue in {"social", "personal", "off_topic"}:
        # Match keys MUST be diacritic-less because we compare against
        # `_normalize_for_intent(query)` which strips diacritics + lowercases.
        # Source-of-truth lives in direct_intent._EMOTIONAL_SUPPORT_MARKERS;
        # we import to avoid drift.
        from app.engine.multi_agent.direct_intent import _EMOTIONAL_SUPPORT_MARKERS
        if any(t in normalized_query for t in _EMOTIONAL_SUPPORT_MARKERS):
            return "Mình đang giữ nhịp đáp chậm và thật, không vội."
        if beat_index <= 1:
            return "Mình đang nhớ lại nhịp trò chuyện hiện tại."
        return "Sắp đáp xong rồi, chờ mình một nhịp nữa."

    # Tool name hint — derive concrete domain from invoked tools.
    tool_hint = ""
    if tool_names:
        names_lc = [str(t or "").lower() for t in tool_names]
        if any("fetch_url" in n for n in names_lc):
            tool_hint = "đọc nội dung trang"
        elif any("search_news" in n or "web_search" in n for n in names_lc):
            tool_hint = "đọc kết quả tìm kiếm"
        elif any("knowledge" in n or "rag" in n for n in names_lc):
            tool_hint = "rà tài liệu nội bộ"
        elif any("calculator" in n for n in names_lc):
            tool_hint = "tính toán lại"
        elif any("datetime" in n for n in names_lc):
            tool_hint = "đối chiếu mốc thời gian"

    # Phase-progressive messaging (the same beat_index never repeats).
    phase_lc = (phase or "").lower()
    if phase_lc in {"ground", "round_0", "tool_dispatch"}:
        if beat_index == 1:
            return f"Mình vừa {tool_hint or 'gom dữ kiện'}, đang sắp lại các điểm chính."
        if beat_index == 2:
            return "Mình đang đối chiếu vài nguồn để chắc chắn số liệu khớp."
        if beat_index == 3:
            return "Đang lọc bớt phần nhiễu, giữ lại điều quan trọng nhất."
        return f"Vẫn đang {tool_hint or 'làm việc với dữ liệu'} — sắp xong rồi."

    if phase_lc in {"verify", "round_1", "convergence"}:
        if beat_index == 1:
            return "Mình kiểm tra lại xem số liệu đã đủ chưa."
        if beat_index == 2:
            return "Đang quyết xem có cần tra thêm hay đáp luôn được."
        return "Phần xương sống đã rõ, đang gọt cho gọn."

    if phase_lc in {"synthesize", "synth", "compose", "round_final"}:
        if beat_index == 1:
            return "Mình đang dệt các mảnh thành một câu trả lời mạch lạc."
        if beat_index == 2:
            return "Đang viết phần bối cảnh để câu trả lời không cụt."
        if beat_index == 3:
            return "Sắp ra rồi — đang chốt số liệu chính."
        if beat_index <= 5:
            return "Đang gọt câu cuối cho gọn và đúng nhịp."
        return "Mình giữ thêm chút để câu ra tử tế nhé, sắp xong."

    # Unknown phase — still progressive (different per beat).
    if cue in {"visual", "web", "news", "legal", "analysis", "operator"}:
        if beat_index == 1:
            return f"Mình đang {tool_hint or 'rà nguồn'} để có cơ sở chắc."
        if beat_index == 2:
            return "Đang gắn các mảnh lại với nhau cho khớp."
        return "Sắp xong, mình giữ thêm một nhịp để chính xác."
    if cue in {"datetime", "memory", "lms"}:
        if beat_index == 1:
            return "Mình đang chốt lại các sự kiện có thể xác minh."
        return "Sắp ra rồi, đang gọt phần ngữ cảnh cuối."
    if beat_index == 1:
        return "Mình đang gạn điều chính yếu cho câu trả lời."
    if beat_index == 2:
        return "Đang sắp lại các ý cho mạch lạc."
    return "Sắp xong, giữ thêm một nhịp ngắn."


def _build_code_studio_wait_heartbeat_text(
    *,
    query: str,
    beat_index: int,
    elapsed_sec: float,
    state: Optional[dict] = None,
) -> str:
    """Return a compact scene-minded wait beat for Code Studio turns."""
    del beat_index, elapsed_sec, state

    normalized_query = _normalize_for_intent(query)
    if any(token in normalized_query for token in ("mo phong", "3d", "canvas", "scene", "simulation")):
        return "Mình đang dựng khung mô phỏng và canvas trước, để khi mở ra bạn nhìn là thấy chuyển động ngay."
    if any(token in normalized_query for token in ("visual", "chart", "bieu do", "thong ke", "so sanh")):
        return "Mình đang dựng phần nhìn trước, để các con số và ý chính đi cùng nhau thay vì bị vỡ ra."
    return "Mình đang lên khung cho một artifact có thể mở ra dùng được ngay, rồi mới gọt tiếp những chi tiết sau."


def _contains_wait_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").strip().lower()
    return any(marker in lowered for marker in markers)


_VISIBLE_PERSONA_LABEL_MARKERS: tuple[str, ...] = (
    "Wiii suy nghĩ",
    "Wiii đang nghĩ",
    "Wiii đã nghĩ",
    "Hmm Wiii",
)


def _thinking_start_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if any(marker in text for marker in _VISIBLE_PERSONA_LABEL_MARKERS) else ""
