"""Shared Wiii Connect intent helpers.

Keep external-app routing predicates in one place so path governance, tool
binding, deterministic shortcuts, and image preflight agree on the same turns.
"""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_intent import _normalize_for_intent


def looks_wiii_connect_facebook_post_request(query: str) -> bool:
    """Detect explicit requests to create or publish a Facebook post."""

    normalized = _normalize_for_intent(query)
    if not any(token in normalized for token in ("facebook", "fb", "meta")):
        return False
    post_markers = (
        "dang bai",
        "dang len",
        "dang thang",
        "dang luon",
        "post",
        "publish",
        "tao bai viet",
        "viet bai",
        "viet post",
        "chia se",
        "len facebook",
        "facebook post",
        "bai viet tren facebook",
    )
    return any(marker in normalized for marker in post_markers)


def looks_wiii_connect_facebook_status_request(query: str) -> bool:
    """Detect questions about whether Wiii is connected to Facebook."""

    normalized = _normalize_for_intent(query)
    if not any(token in normalized for token in ("facebook", "fb", "meta")):
        return False
    status_markers = (
        "ket noi",
        "connected",
        "connect",
        "co dung duoc",
        "dung duoc",
        "truy cap",
        "co quyen",
        "da noi",
        "co facebook",
    )
    return any(marker in normalized for marker in status_markers)


def wiii_connect_facebook_snapshot_from_state(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the frontend-provided Facebook connection snapshot, if present."""

    if not isinstance(state, dict):
        return {}
    context = state.get("context")
    if not isinstance(context, dict):
        context = {}
    host_context = (
        state.get("host_context")
        if isinstance(state.get("host_context"), dict)
        else context.get("host_context")
    )
    if not isinstance(host_context, dict):
        return {}
    page = host_context.get("page")
    if not isinstance(page, dict):
        return {}
    metadata = page.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    snapshot = metadata.get("wiii_connect")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def build_wiii_connect_facebook_status_answer(
    state: dict[str, Any] | None,
) -> str:
    """Build a deterministic answer for Facebook connection status turns."""

    snapshot = wiii_connect_facebook_snapshot_from_state(state)
    status = str(snapshot.get("status") or "").strip().lower()
    page_names = snapshot.get("page_names")
    page_label = ""
    if isinstance(page_names, list):
        names = [str(name).strip() for name in page_names if str(name).strip()]
        if names:
            page_label = ", ".join(names[:3])
    active_count = snapshot.get("active_connection_count")
    page_count = snapshot.get("page_count")

    if status == "connected":
        details: list[str] = []
        if isinstance(active_count, int):
            details.append(f"{active_count} account đang active")
        if isinstance(page_count, int):
            details.append(f"{page_count} page")
        if page_label:
            details.append(f"page: {page_label}")
        suffix = " (" + "; ".join(details) + ")" if details else ""
        return (
            f"Có. Facebook đang được kết nối qua Wiii Connect{suffix}. "
            "Nếu cậu muốn đăng bài, hãy gửi nội dung/ảnh rồi nói rõ “đăng lên Facebook”; "
            "Wiii sẽ tạo bản xem trước để cậu xác nhận trước khi publish."
        )

    if status in {"not_connected", "unavailable"}:
        return (
            "Hiện Wiii chưa thấy Facebook ở trạng thái sẵn sàng trong runtime chat này. "
            "Mở Wiii Connect, kiểm tra Facebook đã connected và có page hợp lệ rồi thử lại."
        )

    return (
        "Mình chưa nhận được snapshot Wiii Connect cho Facebook trong lượt chat này, "
        "nên không nên đoán trạng thái kết nối. Hãy mở Wiii Connect hoặc refresh lại Wiii rồi thử lại."
    )


def facebook_post_message_from_query(query: str) -> str:
    """Create a compact fallback post body for deterministic preview requests."""

    raw = " ".join(str(query or "").strip().split())
    if not raw:
        return "Một khoảnh khắc mới được chia sẻ từ Wiii."

    normalized = _normalize_for_intent(raw)
    generic_anything = any(
        marker in normalized
        for marker in (
            "bai nao cung duoc",
            "gi cung duoc",
            "noi dung nao cung duoc",
            "tuy y",
        )
    )
    if generic_anything:
        return (
            "Một bài đăng thử nghiệm từ Wiii Connect. "
            "Mọi thứ đang được chuẩn bị trực tiếp từ cuộc trò chuyện với Wiii."
        )

    prefixes = (
        "wiii",
        "tao",
        "tạo",
        "viet",
        "viết",
        "dang",
        "đăng",
        "hay",
        "hãy",
        "giup",
        "giúp",
        "minh",
        "mình",
        "toi",
        "tôi",
    )
    cleaned = raw
    for prefix in prefixes:
        cleaned = cleaned.removeprefix(prefix).strip(" ,:;-")
    if len(cleaned) < 12:
        return "Một khoảnh khắc mới được chia sẻ từ Wiii."
    return cleaned[:800]


def facebook_post_uses_latest_user_image(state: dict[str, Any] | None) -> bool:
    """Return true when the current chat turn carries image input."""

    if not isinstance(state, dict):
        return False
    context = state.get("context")
    if not isinstance(context, dict):
        context = {}
    images = context.get("images") or state.get("images")
    return isinstance(images, list) and any(images)
