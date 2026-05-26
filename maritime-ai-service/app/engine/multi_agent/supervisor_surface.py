"""Supervisor surface helpers for routing-visible reasoning and stream events."""

from __future__ import annotations

import logging
from typing import Optional

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor_hint_runtime import (
    _looks_like_artifact_payload_impl,
    _needs_code_studio_impl,
    _normalize_router_text_impl,
)

logger = logging.getLogger(__name__)


def _summarize_routing_turn_content_impl(content: object, *, speaker: str, limit: int) -> str:
    raw = str(content or "").strip()
    if not raw:
        return ""
    normalized = " ".join(raw.split())
    lowered = normalized.lower()
    if _looks_like_artifact_payload_impl(raw):
        if speaker == "user":
            if any(marker in lowered for marker in ("mo phong", "simulation", "canvas", "widget", "artifact", "<svg")):
                return "[Người dùng vừa nhắc hoặc dán một yêu cầu visual/mô phỏng.]"
            return "[Người dùng vừa đưa một nội dung kỹ thuật hoặc đoạn mã khá dài.]"
        if any(marker in lowered for marker in ("mo phong", "simulation", "canvas", "widget", "artifact", "<svg", "visual")):
            return "[AI vừa mở hoặc bàn về một visual/mô phỏng liên quan.]"
        return "[AI vừa tạo một đầu ra kỹ thuật hoặc artifact có mã dài.]"
    if len(normalized) > limit:
        return f"{normalized[: max(0, limit - 1)].rstrip()}…"
    return normalized


def _build_recent_turns_for_routing_impl(lc_messages: list, *, turn_window: int, turn_limit: int) -> str:
    lines: list[str] = []
    for message in lc_messages[-turn_window:]:
        is_user = getattr(message, "type", "") == "human"
        speaker = "User" if is_user else "AI"
        summarized = _summarize_routing_turn_content_impl(
            getattr(message, "content", ""),
            speaker="user" if is_user else "assistant",
            limit=turn_limit,
        )
        if summarized:
            lines.append(f"{speaker}: {summarized}")
    return "\n".join(lines)


def _quote_query_for_visible_reasoning_impl(query: str, max_len: int = 84) -> str:
    compact = " ".join((query or "").split())
    lowered = compact.lower()
    if not compact:
        return "câu này"
    if any(marker in lowered for marker in ("mô phỏng", "mo phong", "simulation", "canvas", "widget", "artifact")):
        return "yêu cầu mô phỏng này"
    if any(marker in lowered for marker in ("visual", "biểu đồ", "bieu do", "chart", "thống kê", "thong ke")):
        return "yêu cầu trực quan này"
    if len(compact.split()) <= 8:
        return "nhịp này"
    if len(compact) > max_len:
        compact = f"{compact[: max_len - 1].rstrip()}…"
    return "điều bạn vừa hỏi"


def _get_supervisor_stream_queue_impl(state: AgentState):
    bus_id = state.get("_event_bus_id")
    if not bus_id:
        return None
    try:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        return _get_event_queue(str(bus_id))
    except Exception as exc:
        logger.debug("[SUPERVISOR] Event queue unavailable: %s", exc)
        return None


def _push_supervisor_stream_event_impl(queue, event: dict) -> None:
    if queue is None:
        return
    try:
        queue.put_nowait(event)
    except Exception as exc:
        logger.debug("[SUPERVISOR] Event queue push failed: %s", exc)


def _clean_supervisor_visible_reasoning_impl(text: object, *, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[:limit]
    for end in [". ", ".\n", "? ", "! "]:
        pos = truncated.rfind(end)
        if pos > limit * 0.6:
            return truncated[: pos + 1]
    last_space = truncated.rfind(" ")
    if last_space > limit * 0.5:
        return cleaned[:last_space]
    return cleaned[:limit]


def _render_supervisor_visible_reasoning_impl(
    state: AgentState,
    *,
    intent: str = "",
    cue: str = "",
    confidence: float = 0.0,
    next_action: str = "",
    observations: Optional[list[str]] = None,
):
    from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator

    query = state.get("query", "")
    context = state.get("context", {}) or {}
    routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
    resolved_intent = intent or str(routing_hint.get("intent") or "")
    resolved_cue = cue
    if not resolved_cue and (routing_hint.get("kind") == "capability_probe" or _needs_code_studio_impl(query)):
        resolved_cue = "code_studio_agent"

    narrator = get_reasoning_narrator()
    request = ReasoningRenderRequest(
        node="supervisor",
        phase="route",
        intent=resolved_intent,
        cue=resolved_cue,
        user_goal=query,
        conversation_context=str((context or {}).get("conversation_summary", "")),
        capability_context=str(state.get("capability_context") or ""),
        confidence=float(confidence or 0.0),
        next_action=next_action,
        observations=[item for item in (observations or []) if item],
        user_id=str(state.get("user_id") or ""),
        organization_id=(context or {}).get("organization_id"),
        personality_mode=(context or {}).get("personality_mode"),
        mood_hint=(context or {}).get("mood_hint"),
        visibility_mode="rich",
        style_tags=["routing", "visible_reasoning", "attuning", "house"],
    )
    return narrator._fallback(request, narrator._resolve_node_skill("supervisor"))


def _finalize_routing_reasoning_impl(
    *,
    raw_reasoning: str,
    method: str,
    chosen_agent: str,
    intent: str,
    query: str,
) -> str:
    cleaned_raw = " ".join((raw_reasoning or "").split()).strip()
    normalized_method = str(method or "").strip().lower()
    normalized_intent = str(intent or "").strip().lower()
    normalized_query = _normalize_router_text_impl(query)

    if normalized_method == "structured+capability_override":
        if chosen_agent == "code_studio_agent":
            return (
                "Câu này vẫn đang mang tín hiệu mô phỏng hoặc lane dựng app/visual, "
                "nên mình giữ nó ở Code Studio để Wiii có thể mở đúng không gian sáng tạo "
                "thay vì đáp tạm bằng lời."
            )
        if chosen_agent == "direct":
            return (
                "Phần intent thô ban đầu còn lửng, nhưng lane xử lý phù hợp nhất lúc này "
                "vẫn là trả lời trực tiếp để chốt thêm ý trước khi mở nhánh sâu hơn."
            )

    if normalized_method == "structured+visual_lane_override":
        return (
            "Đây nghiêng về một visual giải thích hoặc chart inline hơn là app hoàn chỉnh, "
            "nên mình giữ nó ở lane trực tiếp để Wiii còn phát visual đúng cách trong stream."
        )

    if normalized_method == "structured+visual_override":
        return (
            "Câu này cần một nhịp minh hoạ trực quan hơn là giảng bài thuần chữ, "
            "nên mình chuyển về direct lane để gọi visual đúng chỗ."
        )

    if normalized_method == "structured+intent_override":
        if chosen_agent == "code_studio_agent":
            return (
                "Ý chính ở đây là tạo hoặc dựng một thứ có thể chạy/hiện ra được, "
                "nên mình chốt route sang Code Studio thay vì để nó trôi ở lane trò chuyện."
            )
        if chosen_agent == "direct" and normalized_intent in {"off_topic", "web_search"}:
            return (
                "Câu này không cần kéo vào lane tri thức chuyên biệt; "
                "trả lời trực tiếp sẽ giữ nhịp trò chuyện đúng hơn."
            )

    if normalized_method == "structured+identity_override":
        return (
            "Câu này đang chạm thẳng vào phần tự thân của Wiii, nên mình giữ nó ở lane trực tiếp "
            "để Wiii tự lên tiếng về mình thay vì biến nó thành một lượt tra cứu."
        )

    if normalized_method == "structured+selfhood_followup_override":
        return (
            "Nhịp này đang nối tiếp đúng phần tự thân của Wiii, nên mình giữ nó ở lane trực tiếp "
            "để Bông, The Wiii Lab, và mạch origin không bị hiểu lạc thành một cái tên chung chung."
        )

    if normalized_method == "structured+visual_followup_override":
        return (
            "Đây là nhịp trực quan hóa đang nối tiếp một bài học còn dang dở, "
            "nên mình giữ nó ở tutor lane để Wiii giải thích vẫn liền mạch rồi mới gọi visual."
        )

    if normalized_method == "structured+domain_validation":
        return (
            "Mình không thấy đủ tín hiệu domain chuyên biệt trong câu này, "
            "nên không ép sang lane tra cứu/giảng dạy nặng."
        )

    if normalized_method == "structured+rule_override":
        return (
            "Phần phân loại ban đầu chưa đủ chắc, nên mình chốt lại theo guardrail an toàn hơn "
            "để tránh kéo bạn vào nhánh xử lý lệch."
        )

    if normalized_method == "always_on_social_fast_path":
        return "Đây là một nhịp xã giao rất rõ, nên mình đáp ngay để giữ cuộc trò chuyện tự nhiên."

    if normalized_method == "always_on_social_status_fast_path":
        return (
            "Đây là một cập nhật sinh hoạt rất ngắn, không có yêu cầu tra cứu hay công cụ, "
            "nên Wiii đáp trực tiếp."
        )

    if normalized_method == "always_on_chatter_fast_path":
        return "Đây là một nhịp trò chuyện rất ngắn và ít thông tin, nên mình giữ nó ở lane đáp trực tiếp."

    if normalized_intent == "social" and len(normalized_query.split()) <= 6:
        return (
            "Nhịp này thiên về xã giao hoặc bắt nhịp cảm xúc hơn là cần mở một lane xử lý nặng, "
            "nên mình giữ nó ngắn và gần."
        )

    return cleaned_raw
