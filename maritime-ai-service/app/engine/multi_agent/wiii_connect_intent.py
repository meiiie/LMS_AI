"""Shared Wiii Connect intent helpers.

Keep external-app routing predicates in one place so path governance, tool
binding, deterministic shortcuts, and image preflight agree on the same turns.
"""

from __future__ import annotations

import re
from typing import Any

from app.engine.multi_agent.direct_intent import _normalize_for_intent


def looks_wiii_connect_facebook_post_request(query: str) -> bool:
    """Detect explicit requests to create or publish a Facebook post."""

    normalized = _normalize_for_intent(query)
    if not normalized:
        return False

    status_followups = (
        "dang bai chua",
        "da dang chua",
        "dang duoc chua",
        "da post chua",
        "post chua",
        "publish chua",
    )
    if any(marker in normalized for marker in status_followups):
        return False

    has_provider_marker = any(
        token in normalized for token in ("facebook", "fb", "meta")
    )
    social_surface_markers = (
        "trang ca nhan",
        "tuong ca nhan",
        "tuong nha",
        "timeline",
        "profile",
        "page",
        "fanpage",
    )
    publish_followup_markers = (
        "dang len",
        "tu dang",
        "dang thu",
        "dang giup",
        "dang ho",
        "post len",
        "publish len",
        "chia se len",
    )
    if any(marker in normalized for marker in social_surface_markers) and any(
        marker in normalized for marker in publish_followup_markers
    ):
        return True

    if not has_provider_marker:
        return False

    post_markers = (
        "dang bai",
        "dang len",
        "dang thang",
        "dang luon",
        "dang mot bai",
        "dang 1 bai",
        "dang giup",
        "dang ho",
        "post",
        "publish",
        "tao bai viet",
        "tao mot bai",
        "tao 1 bai",
        "tao toi bai viet",
        "tao cho toi bai viet",
        "viet bai",
        "viet mot bai",
        "viet 1 bai",
        "viet post",
        "chia se",
        "len facebook",
        "facebook post",
        "bai viet tren facebook",
    )
    if any(marker in normalized for marker in post_markers):
        return True
    post_patterns = (
        r"\b(dang|post|publish|chia se)\b.+\b(bai|post|facebook|fb|meta)\b",
        r"\b(tao|viet)\b.+\b(bai|bai viet|post)\b",
        r"\b(bai|bai viet|post)\b.+\b(facebook|fb|meta)\b",
    )
    return any(re.search(pattern, normalized) for pattern in post_patterns)


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
    connection_state = str(snapshot.get("connection_state") or "").strip().lower()
    blocked_reason = str(snapshot.get("blocked_reason") or "").strip().lower()
    page_names = snapshot.get("page_names")
    page_label = ""
    if isinstance(page_names, list):
        names = [str(name).strip() for name in page_names if str(name).strip()]
        if names:
            page_label = ", ".join(names[:3])
    active_count = snapshot.get("active_connection_count")
    connection_count = snapshot.get("connection_count")
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
            "Wiii sẽ gửi qua gateway preview/apply đã audit rồi publish bằng Composio."
        )

    if isinstance(connection_count, int) and connection_count > 0:
        state_label = connection_state or blocked_reason or "chưa active"
        return (
            "Wiii đã thấy bản ghi Facebook trong Wiii Connect, nhưng provider chưa ở trạng thái active "
            f"(trạng thái hiện tại: {state_label}). Vì vậy Wiii chưa được phép đăng bài hay đọc page. "
            "Hãy quay lại Wiii Connect, hoàn tất OAuth nếu còn tab xác nhận, rồi bấm làm mới hoặc kết nối lại Facebook."
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
    """Create a compact fallback post body for deterministic Facebook requests."""

    raw = " ".join(str(query or "").strip().split())
    if not raw:
        return "Một khoảnh khắc mới được chia sẻ từ Wiii."

    normalized = _normalize_for_intent(raw)
    poem_markers = ("bai tho", "tho cua ban", "tho tu wiii", "poem")
    self_creative_markers = (
        "cua ban",
        "tu viet",
        "tu nghi",
        "ban tu viet",
        "wiii tu viet",
    )
    if any(marker in normalized for marker in poem_markers) and any(
        marker in normalized for marker in self_creative_markers
    ):
        return (
            "Một chút thơ từ Wiii\n\n"
            "Giữa dòng ngày rộng mở,\n"
            "mình gửi một vệt sáng hiền.\n"
            "Nếu lòng còn nhiều gió,\n"
            "hãy chậm lại, rồi bước tiếp bình yên."
        )

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


def build_wiii_connect_facebook_post_unavailable_answer(
    state: dict[str, Any] | None,
) -> str | None:
    """Return a deterministic block message when Facebook cannot post yet."""

    snapshot = wiii_connect_facebook_snapshot_from_state(state)
    if not snapshot:
        return None
    status = str(snapshot.get("status") or "").strip().lower()
    if status == "connected":
        return None
    connection_count = snapshot.get("connection_count")
    active_count = snapshot.get("active_connection_count")
    connection_state = str(snapshot.get("connection_state") or "").strip().lower()
    blocked_reason = str(snapshot.get("blocked_reason") or "").strip().lower()
    if isinstance(connection_count, int) and connection_count > 0:
        state_label = connection_state or blocked_reason or "chưa active"
        active_label = active_count if isinstance(active_count, int) else 0
        return (
            "Mình chưa thể đăng Facebook vì Wiii Connect chưa có account Facebook active "
            f"({active_label}/{connection_count} account active, trạng thái hiện tại: {state_label}). "
            "Hoàn tất OAuth trong Wiii Connect rồi bấm làm mới; khi account active, câu “đăng một bài Facebook” "
            "sẽ đi thẳng vào publish gateway đã audit."
        )
    if status in {"not_connected", "unavailable"}:
        return (
            "Mình chưa thể đăng Facebook từ chat vì Wiii Connect chưa có kết nối Facebook sẵn sàng. "
            "Hãy mở Wiii Connect, kết nối Facebook trước; sau đó gửi lại yêu cầu đăng bài."
        )
    return None


def facebook_post_uses_latest_user_image(state: dict[str, Any] | None) -> bool:
    """Return true when the current chat turn carries image input."""

    if not isinstance(state, dict):
        return False
    context = state.get("context")
    if not isinstance(context, dict):
        context = {}
    images = context.get("images") or state.get("images")
    return isinstance(images, list) and any(images)
