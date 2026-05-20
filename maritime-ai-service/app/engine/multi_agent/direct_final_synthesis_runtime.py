"""Final synthesis helpers for direct tool-round execution."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
)
from app.engine.multi_agent.state import AgentState


def extract_direct_visible_text(content: Any) -> str:
    """Return the answer text that would be visible to the user."""
    try:
        from app.services.output_processor import extract_thinking_from_response

        text_content, _thinking_content = extract_thinking_from_response(content)
        return str(text_content or "").strip()
    except Exception:
        return str(content or "").strip()


def build_direct_final_synthesis_instruction(
    query: str,
    state: AgentState,
    tool_names: list[str],
) -> str:
    """Build a mode-aware final synthesis instruction after tool rounds."""
    thinking_mode = _infer_direct_thinking_mode(query, state, tool_names)
    axes = _build_direct_analytical_axes(query, state, tool_names)
    plan = _build_direct_evidence_plan(query, state, tool_names)

    base = (
        "Du lieu da du cho luot nay. Khong goi them cong cu. "
        "Hay tong hop ngay thanh cau tra loi cuoi cung bang tieng Viet, "
        "dua tren cac ket qua cong cu da co."
    )

    if thinking_mode == "analytical_market":
        return (
            base
            + " Mo dau bang mot cau thesis ve mat bang thi truong hien tai, sau do tach cac luc keo chinh "
            + "(cung-cau, OPEC+, ton kho, dia chinh tri) thay vi liet ke tin tuc. "
            + "Neu cac tin hieu xung nhau, hay noi ro truc nao dang giu mat bang gia va truc nao chi tao nhieu ngan han. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan neu can tach watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###, va KHONG dung bullet/bold kieu ban tin tong hop. "
            + "Ket bang takeaway hoac dieu can theo doi tiep theo."
        )
    if thinking_mode == "analytical_math":
        return (
            base
            + " Mo dau bang mot cau thesis ve mo hinh dang dung, roi trinh bay theo nhip mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly. "
            + "Noi ro cac gia dinh nhu "
            + (", ".join(axes[:3]) if axes else "mo hinh, goc nho, va phuong trinh")
            + ". Neu ket luan phu thuoc gan dung, noi ro pham vi ma gan dung do con hop le. "
            + "Mac dinh uu tien 2-3 doan chat; KHONG dung heading Markdown nhu #, ##, ### neu user khong yeu cau."
        )
    if thinking_mode == "analytical_general":
        plan_hint = (
            ", ".join(plan[:2])
            if plan
            else "cac bien so chinh va chung cu manh nhat"
        )
        return (
            base
            + " Mo dau bang mot cau thesis co the kiem cheo, di thang vao luan diem, tach dieu chac khoi dieu con nhieu, va neo lai "
            + plan_hint
            + ". Neu co tin hieu trai chieu, noi ro cai nao dang nang ky hon. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan khi user can tach checklist/watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###."
        )
    return base
