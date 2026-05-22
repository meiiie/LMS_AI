"""Prompt contracts for Code Studio delivery turns."""

from __future__ import annotations

from app.engine.multi_agent.direct_intent import _normalize_for_intent


def _build_code_studio_delivery_contract(query: str) -> str:
    """Role-local answer contract for delivery-first technical responses."""

    normalized = _normalize_for_intent(query)
    is_chart_request = any(
        token in normalized
        for token in ("bieu do", "chart", "plot", "matplotlib", "seaborn", "png", "svg")
    )
    is_html_request = any(
        token in normalized
        for token in ("html", "landing page", "website", "web app", "microsite", "trang web")
    )

    lines = [
        "## CODE STUDIO DELIVERY CONTRACT:",
        "- Voi tac vu ky thuat, mo dau answer bang ket qua da tao hoac da xac nhan. Khong mo dau bang loi chao, tu gioi thieu, hay small talk.",
        "- Khi vua tao artifact, neu ro ten file, loai san pham, va dieu nguoi dung co the mo ra ngay luc nay.",
        "- Neu yeu cau chua du du lieu cu the, tao mot demo trung tinh phu hop voi task va noi ro do la demo. Khong bien no thanh lore ca nhan cua Wiii.",
        "- Khong dua nhan vat phu, thu cung ao, catchphrase, hay chi tiet de thuong khong lien quan vao output ky thuat neu user khong yeu cau.",
        "- Uu tien 3 phan theo thu tu: da tao gi, no dung de lam gi, nguoi dung co the lam gi tiep theo.",
    ]
    if is_chart_request:
        lines.append(
            "- Voi yeu cau bieu do/chart mo ho, uu tien tao mot chart demo trung tinh va giao lai file PNG that (neu co sandbox), hoac Mermaid SVG khi khong co sandbox."
        )
    if is_html_request:
        lines.append(
            "- Voi yeu cau landing page/HTML, tao file HTML that va mo ta ro nhung gi nguoi dung co the xem/mo ngay."
        )
    return "\n".join(lines)
