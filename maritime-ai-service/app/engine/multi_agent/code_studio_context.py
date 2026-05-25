"""Code Studio context and policy helpers extracted from graph.py."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.code_studio_surface import _extract_code_studio_artifact_names
from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.direct_prompt_tool_binding import _tool_name
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent


def _get_active_code_studio_session(state: AgentState) -> dict[str, Any]:
    context = state.get("context") or {}
    code_studio_ctx = context.get("code_studio_context") or {}
    if not isinstance(code_studio_ctx, dict):
        return {}
    active_session = code_studio_ctx.get("active_session") or {}
    if not isinstance(active_session, dict):
        return {}
    return active_session


def _active_code_studio_session(state: Optional[AgentState]) -> dict[str, Any]:
    context = ((state or {}).get("context") or {}) if isinstance(state, dict) else {}
    if not isinstance(context, dict):
        return {}
    raw_studio = context.get("code_studio_context")
    if not isinstance(raw_studio, dict):
        return {}
    active_session = raw_studio.get("active_session")
    return active_session if isinstance(active_session, dict) else {}


def _active_visual_context(state: Optional[AgentState]) -> dict[str, Any]:
    context = ((state or {}).get("context") or {}) if isinstance(state, dict) else {}
    if not isinstance(context, dict):
        return {}
    raw_visual = context.get("visual_context")
    return raw_visual if isinstance(raw_visual, dict) else {}


def _last_inline_visual_title(state: Optional[AgentState]) -> str:
    visual_ctx = _active_visual_context(state)
    last_title = str(visual_ctx.get("last_visual_title") or "").strip()
    if last_title:
        return last_title

    active_items = visual_ctx.get("active_inline_visuals")
    if isinstance(active_items, list):
        for item in active_items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("visual_title") or "").strip()
            if title:
                return title
    return ""


def _ground_simulation_query_from_visual_context(
    query: str,
    state: Optional[AgentState] = None,
) -> str:
    if not _looks_like_ambiguous_simulation_request(query, state):
        return ""

    last_title = _last_inline_visual_title(state)
    if not last_title:
        return ""

    return (
        f"Hay tao mot mo phong tuong tac inline bang canvas cho `{last_title}`. "
        "Day la follow-up tu visual ngay truoc do, vi vay hay bam sat chu de nay thay vi hoi lai. "
        "Mo phong can co state model ro rang, controls toi thieu, live readout, va note ngan giai thich "
        "dieu gi dang thay doi theo thoi gian. Uu tien mo phong that hon la animation demo."
    )


def _build_code_studio_progress_messages(
    query: str,
    state: Optional[AgentState] = None,
) -> list[str]:
    visual_decision = resolve_visual_intent(query)
    last_title = _last_inline_visual_title(state)
    subject = f" cho `{last_title}`" if last_title else ""

    if visual_decision.visual_type == "simulation":
        return [
            f"Mình đang phác state model cho mô phỏng{subject}...",
            f"Mình đang dựng canvas loop và chuyển động chính{subject}...",
            "Mình đang nối controls, readout, và cấu trúc patch tiếp theo...",
            "Mình đang rà soát để mô phỏng này là một hệ thống sống, chứ không chỉ là animation demo...",
            "Mình vẫn đang làm việc và sẽ báo ngay khi preview thật sự sẵn sàng...",
        ]

    if getattr(visual_decision, "app_category", "") == "quiz":
        return [
            "Mình đang dựng luồng câu hỏi, lựa chọn trả lời, và trạng thái điểm...",
            "Mình đang nối submit/reset cùng phản hồi đúng sai...",
            "Mình đang rà lại để quiz có thể tương tác thật trong Code Studio...",
            "Mình vẫn đang hoàn thiện preview quiz...",
        ]

    if getattr(visual_decision, "app_category", "") == "dashboard":
        return [
            "Mình đang dựng data model, metric cards, và bộ lọc chính...",
            "Mình đang nối trạng thái filter/view toggle với phần hiển thị...",
            "Mình đang rà lại để dashboard không thành biểu đồ giả hoặc card rỗng...",
            "Mình vẫn đang hoàn thiện preview dashboard...",
        ]

    if visual_decision.presentation_intent == "artifact":
        return [
            "Mình đang lên bộ khung artifact và quy ước nhúng...",
            "Mình đang viết mã nguồn và kiểm tra bố cục chính...",
            "Mình đang làm sạch scaffold để bạn có thể patch tiếp...",
            "Mình vẫn đang hoàn thiện artifact này...",
        ]

    return [
        "Mình đang phân tích yêu cầu kỹ thuật...",
        "Mình đang lên kế hoạch code...",
        "Mình đang viết mã nguồn...",
        "Mình đang tối ưu logic...",
        "Mình đang hoàn thiện chi tiết...",
    ]


def _format_code_studio_progress_message(message: str, elapsed_seconds: float) -> str:
    if elapsed_seconds <= 0:
        return message
    elapsed = int(max(1, round(elapsed_seconds)))
    return f"{message} (đã {elapsed}s)"


def _build_code_studio_retry_status(
    query: str,
    state: Optional[AgentState] = None,
    *,
    elapsed_seconds: float = 0.0,
) -> str:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.visual_type == "simulation":
        base = (
            "Lượt dựng đầu tiên đang chậm hơn dự kiến. "
            "Mình vẫn đang tiếp tục và thử lại với cấu hình nhẹ hơn để lấy preview thật"
        )
    else:
        base = "Lượt dựng đầu tiên đang chậm hơn dự kiến. Mình đang thử lại với cấu hình nhẹ hơn"
    return _format_code_studio_progress_message(base + "...", elapsed_seconds)


def _looks_like_ambiguous_simulation_request(query: str, state: Optional[AgentState] = None) -> bool:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.presentation_intent != "code_studio_app":
        return False
    if visual_decision.visual_type != "simulation":
        return False
    if _active_code_studio_session(state):
        return False

    normalized_query = _normalize_for_intent(query)
    if not normalized_query:
        return False
    if any(
        token in normalized_query
        for token in ("show code", "xem code", "xem ma", "view code", "hien code")
    ):
        return False
    if any(
        token in normalized_query
        for token in (
            "pendulum",
            "con lac",
            "dao dong",
            "colreg",
            "quy tac 15",
            "rule 15",
            "crossing situation",
            "cat huong",
            "drag",
            "keo tha",
            "gravity",
            "trong luc",
            "damping",
            "ma sat",
            "friction",
            "particle",
            "field",
            "timeline",
            "tau",
            "ship",
            "kimi",
            "linear attention",
        )
    ):
        return False

    generic_tokens = {
        "wiii",
        "tao",
        "lam",
        "dung",
        "build",
        "create",
        "cho",
        "minh",
        "duoc",
        "chu",
        "khong",
        "nhe",
        "nha",
        "voi",
        "giup",
        "co",
        "the",
        "mot",
        "duocchu",
        "simulation",
        "simulate",
        "simulator",
        "mo",
        "phong",
    }
    remaining_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalized_query)
        if token and token not in generic_tokens
    ]
    return len(remaining_tokens) == 0 and any(
        token in normalized_query for token in ("mo phong", "simulation", "simulate", "simulator")
    )


def _build_ambiguous_simulation_clarifier(state: Optional[AgentState] = None) -> str:
    last_title = _last_inline_visual_title(state)
    if last_title:
        return (
            f"Mình dựng được mô phỏng chứ. Chỉ là ở câu này, mình cần chốt xem bạn muốn mô phỏng "
            f"`{last_title}` vừa rồi hay một hiện tượng khác. Nếu muốn bám theo chủ đề vừa rồi, "
            f"bạn chỉ cần nhắn `Mô phỏng {last_title}` là mình mở canvas ngay."
        )
    return (
        "Mình dựng được mô phỏng chứ, nhưng câu này chưa nói rõ hiện tượng nào. "
        "Bạn chỉ cần gọi tên cơ chế hoặc chủ đề, mình sẽ mở canvas ngay."
    )


def _build_code_studio_terminal_failure_response(
    query: str,
    tool_call_events: list[dict] | None = None,
) -> str:
    """Create a short, delivery-first answer when sandbox execution is terminally unavailable."""
    artifact_names = _extract_code_studio_artifact_names(tool_call_events)
    normalized = _normalize_for_intent(query)
    is_chart_request = any(
        token in normalized for token in ("bieu do", "chart", "plot", "png", "matplotlib", "seaborn")
    )

    if artifact_names:
        return (
            f"Mình đã bắt đầu chuẩn bị `{artifact_names[0]}`, nhưng sandbox đang gặp lỗi kết nối nên chưa thể "
            "hoàn tất artifact này ở turn hiện tại. Khi kênh thực thi ổn định trở lại, mình có thể chạy lại và "
            "gửi kết quả ngay."
        )

    if is_chart_request:
        return (
            "Mình chưa thể tạo file PNG thật lúc này vì sandbox đang gặp lỗi kết nối. "
            "Khi kênh thực thi ổn định trở lại, mình có thể chạy lại và gửi cho cậu artifact biểu đồ ngay."
        )

    return (
        "Mình đã đến bước thực thi, nhưng sandbox đang gặp lỗi kết nối nên chưa thể tạo kết quả thật ngay lúc này. "
        "Khi kênh này ổn định trở lại, mình có thể chạy lại và giao artifact hoàn chỉnh cho cậu."
    )


def _build_code_studio_missing_tool_response(
    query: str,
    state: Optional[AgentState] = None,
    *,
    timed_out: bool = False,
) -> str:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.presentation_intent == "code_studio_app" and visual_decision.visual_type == "simulation":
        if _looks_like_ambiguous_simulation_request(query, state):
            return _build_ambiguous_simulation_clarifier(state)

        last_title = _last_inline_visual_title(state)
        if timed_out and last_title:
            return (
                f"Mình đã mở đúng lane mô phỏng rồi, nhưng lượt này model chưa dựng kịp app thật. "
                f"Để mình vào lại gọn hơn, bạn hãy nói rõ hơn một chút, ví dụ `Mô phỏng {last_title}`."
            )
        if timed_out:
            return (
                "Mình đã mở đúng lane mô phỏng rồi, nhưng lượt này model chưa dựng kịp app thật. "
                "Bạn hãy nói rõ hiện tượng cần mô phỏng hơn một chút, mình sẽ mở canvas theo đúng chủ đề đó."
            )
        return (
            "Mình đã mở đúng lane mô phỏng rồi, nhưng ở lượt này model mới chỉ mô tả ý định "
            "mà chưa dựng app thật. Bạn hãy nói rõ hiện tượng hoặc cơ chế cần mô phỏng hơn một chút, "
            "mình sẽ vào canvas ngay."
        )

    return _build_code_studio_terminal_failure_response(query)


def _requires_code_studio_visual_delivery(query: str, tools: list) -> bool:
    visual_decision = resolve_visual_intent(query)
    if not visual_decision.force_tool:
        return False
    if visual_decision.preferred_tool != "tool_create_visual_code":
        return False

    tool_names = {_tool_name(tool) for tool in tools}
    return "tool_create_visual_code" in tool_names


def _should_use_pendulum_code_studio_fast_path(query: str, state: Optional[AgentState] = None) -> bool:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.presentation_intent != "code_studio_app":
        return False
    if str(visual_decision.preferred_tool or "") != "tool_create_visual_code":
        return False

    context = ((state or {}).get("context") or {}) if isinstance(state, dict) else {}
    raw_studio = context.get("code_studio_context") if isinstance(context, dict) else {}
    requested_view = ""
    if isinstance(raw_studio, dict):
        requested_view = str(raw_studio.get("requested_view") or "").strip().lower()
    if requested_view == "code":
        return False

    normalized_query = _normalize_for_intent(query)
    if any(
        token in normalized_query
        for token in ("show code", "xem code", "xem ma", "hien code", "view code")
    ):
        return False

    active_session = _active_code_studio_session(state)
    active_title = _normalize_for_intent(str(active_session.get("title") or ""))
    haystack = " ".join(part for part in (normalized_query, active_title) if part)

    pendulum_signals = ("pendulum", "con lac", "dao dong")
    if any(token in haystack for token in pendulum_signals):
        return True

    patch_signals = ("gravity", "trong luc", "damping", "ma sat", "friction", "theta", "omega")
    return bool(active_title) and any(token in active_title for token in pendulum_signals) and any(
        token in normalized_query for token in patch_signals
    )


def _infer_pendulum_fast_path_title(query: str, state: Optional[AgentState] = None) -> str:
    active_session = _active_code_studio_session(state)
    active_title = str(active_session.get("title") or "").strip()
    if active_title:
        return active_title
    normalized_query = _normalize_for_intent(query)
    if "con lac" in normalized_query:
        return "Mô phỏng con lắc"
    return "Mini Pendulum Physics App"


def _should_use_colreg_code_studio_fast_path(query: str, state: Optional[AgentState] = None) -> bool:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.presentation_intent != "code_studio_app":
        return False
    if str(visual_decision.preferred_tool or "") != "tool_create_visual_code":
        return False
    normalized_query = _normalize_for_intent(query)
    return any(
        token in normalized_query
        for token in ("colreg", "quy tac 15", "rule 15", "crossing situation", "cat huong")
    )


def _infer_colreg_fast_path_title(query: str, state: Optional[AgentState] = None) -> str:
    active_session = _active_code_studio_session(state)
    active_title = str(active_session.get("title") or "").strip()
    if active_title:
        return active_title
    return "COLREGs Rule 15 Simulation"


def _should_use_artifact_code_studio_fast_path(query: str, state: Optional[AgentState] = None) -> bool:
    visual_decision = resolve_visual_intent(query)
    if visual_decision.presentation_intent != "artifact":
        return False
    if str(visual_decision.preferred_tool or "") != "tool_create_visual_code":
        return False
    normalized_query = _normalize_for_intent(query)
    if any(token in normalized_query for token in ("show code", "xem code", "view code")):
        return False
    return any(
        token in normalized_query
        for token in ("mini app", "html app", "nhung", "embed", "landing page", "microsite")
    )


def _infer_artifact_fast_path_title(query: str, state: Optional[AgentState] = None) -> str:
    active_session = _active_code_studio_session(state)
    active_title = str(active_session.get("title") or "").strip()
    if active_title:
        return active_title
    return "Mini HTML App"
