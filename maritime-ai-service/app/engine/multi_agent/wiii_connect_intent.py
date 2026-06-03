"""Shared Wiii Connect intent helpers.

Keep external-app routing predicates in one place so path governance, tool
binding, and image preflight agree on the same turns.
"""

from __future__ import annotations

import re
from typing import Any

from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.wiii_connect.connection_lifecycle import (
    sanitize_connection_lifecycle_metadata,
)
from app.engine.wiii_connect.provider_registry import (
    list_wiii_connect_provider_registry,
)
from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot


_FACEBOOK_POST_ACTION_MARKERS: tuple[str, ...] = (
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

_EXTERNAL_ACTION_MARKERS: tuple[str, ...] = (
    "dang",
    "dang bai",
    "post",
    "publish",
    "chia se",
    "gui",
    "send",
    "doc",
    "read",
    "fetch",
    "lay",
    "tim",
    "search",
    "tao",
    "create",
    "cap nhat",
    "update",
    "xoa",
    "delete",
    "len lich",
    "schedule",
    "them",
    "add",
)

_PROVIDER_STATUS_MARKERS: tuple[str, ...] = (
    "ket noi",
    "connected",
    "connect",
    "trang thai",
    "status",
    "ready",
    "agent ready",
    "agent-ready",
    "co dung duoc",
    "dung duoc",
    "truy cap",
    "co quyen",
    "da noi",
    "da lien ket",
    "lien ket",
    "co facebook",
)

_PROVIDER_CONTEXT_MARKERS: tuple[str, ...] = (
    *_PROVIDER_STATUS_MARKERS,
    "wiii connect",
    "agent ready",
    "agent-ready",
    "action",
    "gateway",
    "oauth",
    "scope",
    "policy",
    "allowlist",
    "dang bai",
    "publish",
    "post",
)

_PROVIDERLESS_EXTERNAL_SURFACE_MARKERS: tuple[str, ...] = (
    "app",
    "application",
    "connector",
    "connection",
    "integration",
    "mang xa hoi",
    "nen tang",
    "platform",
    "social",
    "social media",
    "ung dung",
)

_VISUAL_APP_CREATION_MARKERS: tuple[str, ...] = (
    "code studio",
    "mini app",
    "web app",
    "widget",
    "mo phong",
    "simulation",
    "slider",
    "canvas",
    "html",
    "javascript",
    "tuong tac",
    "interactive",
)


def looks_wiii_connect_facebook_post_request(query: str) -> bool:
    """Detect explicit requests to create or publish a Facebook post."""

    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    if _looks_provider_action_capability_question(normalized):
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

    if _contains_facebook_post_action_marker(normalized):
        return True
    post_patterns = (
        r"\b(dang|post|publish|chia se)\b.+\b(bai|post|facebook|fb|meta)\b",
        r"\b(tao|viet)\b.+\b(bai|bai viet|post)\b",
        r"\b(bai|bai viet|post)\b.+\b(facebook|fb|meta)\b",
    )
    return any(re.search(pattern, normalized) for pattern in post_patterns)


def looks_wiii_connect_facebook_status_request(query: str) -> bool:
    """Detect questions about whether Wiii is connected to Facebook."""

    return "facebook" in resolve_wiii_connect_status_provider_slugs(query)


def resolve_wiii_connect_status_provider_slugs(query: str) -> tuple[str, ...]:
    """Return provider slugs for connection/readiness status questions."""

    normalized = _normalize_for_intent(query)
    if not normalized:
        return ()
    if not any(marker in normalized for marker in _PROVIDER_STATUS_MARKERS) and not (
        _looks_provider_action_capability_question(normalized)
    ):
        return ()
    return resolve_wiii_connect_target_provider_slugs(query)


def looks_wiii_connect_external_app_action_request(query: str) -> bool:
    """Detect explicit external provider action requests for Wiii Connect."""

    if resolve_wiii_connect_status_provider_slugs(query):
        return False
    if looks_wiii_connect_facebook_post_request(query):
        return True
    normalized = _normalize_for_intent(query)
    if not normalized:
        return False
    if _looks_visual_or_code_studio_creation_request(query, normalized):
        return False
    if not _contains_external_action_marker(normalized):
        return False
    if _contains_registered_provider_marker(normalized):
        return True
    return _looks_providerless_external_action_request(normalized)


def _looks_visual_or_code_studio_creation_request(
    query: str,
    normalized: str,
) -> bool:
    if not any(marker in normalized for marker in _VISUAL_APP_CREATION_MARKERS):
        return False
    try:
        from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

        decision = resolve_visual_intent(query)
    except Exception:
        return False
    return decision.presentation_intent in {
        "article_figure",
        "chart_runtime",
        "code_studio_app",
        "artifact",
    }


def looks_wiii_connect_facebook_post_request_for_state(
    query: str,
    state: dict[str, Any] | None,
) -> bool:
    """Detect Facebook publish requests, including providerless continuations."""

    if looks_wiii_connect_facebook_post_request(query):
        return True
    normalized = _normalize_for_intent(query)
    if not normalized or _looks_provider_action_capability_question(normalized):
        return False
    providers = resolve_wiii_connect_target_provider_slugs_for_state(query, state)
    return providers == ("facebook",) and _contains_facebook_post_action_marker(
        normalized
    )


def looks_wiii_connect_external_app_action_request_for_state(
    query: str,
    state: dict[str, Any] | None,
) -> bool:
    """Detect provider actions with explicit or recent Wiii Connect context."""

    if resolve_wiii_connect_status_provider_slugs(query):
        return False
    if looks_wiii_connect_facebook_post_request_for_state(query, state):
        return True
    if looks_wiii_connect_external_app_action_request(query):
        return True
    normalized = _normalize_for_intent(query)
    if not normalized or not _contains_external_action_marker(normalized):
        return False
    if _looks_visual_or_code_studio_creation_request(query, normalized):
        return False
    if resolve_wiii_connect_target_provider_slugs_for_state(query, state):
        return True
    return _looks_providerless_external_action_request(normalized)


_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "facebook": ("facebook", "fb", "meta", "fanpage", "page facebook"),
    "gmail": ("gmail", "google mail", "email", "mail"),
    "google_calendar": ("google calendar", "calendar", "lich google"),
    "google_drive": ("google drive", "drive", "gdrive"),
    "github": ("github", "git hub"),
    "slack": ("slack",),
    "notion": ("notion",),
    "airtable": ("airtable",),
    "asana": ("asana",),
}


def resolve_wiii_connect_target_provider_slugs(query: str) -> tuple[str, ...]:
    """Return provider slugs explicitly named by the user.

    This is the Wiii equivalent of OpenHuman requiring a concrete toolkit before
    spawning the integrations agent. It is intentionally registry-driven and
    privacy-safe: it returns only provider slugs, never prompts or payloads.
    """

    normalized = _normalize_for_intent(query)
    if not normalized:
        return ()
    result: list[str] = []
    for entry in list_wiii_connect_provider_registry():
        markers = {
            entry.slug.replace("_", " "),
            entry.slug.replace("_", "-"),
            _normalize_for_intent(entry.label),
            *(_PROVIDER_ALIASES.get(entry.slug, ())),
        }
        if any(_marker_matches(normalized, marker) for marker in markers):
            result.append(entry.slug)
    return tuple(dict.fromkeys(result))


def resolve_wiii_connect_target_provider_slugs_for_state(
    query: str,
    state: dict[str, Any] | None,
) -> tuple[str, ...]:
    """Return explicit provider slugs, or a safe recent Wiii Connect provider.

    This mirrors OpenHuman's toolkit-before-actions discipline for follow-up
    turns. A providerless action may inherit a provider only when recent chat
    context contains exactly one provider inside a Wiii Connect/action/status
    exchange. Otherwise the caller gets no inferred provider and must fail
    closed or ask for clarification.
    """

    explicit = resolve_wiii_connect_target_provider_slugs(query)
    if explicit:
        return explicit
    normalized = _normalize_for_intent(query)
    if not normalized or not _contains_external_action_marker(normalized):
        return ()
    return _recent_wiii_connect_provider_slugs_from_state(state)


def _contains_registered_provider_marker(normalized_query: str) -> bool:
    return bool(resolve_wiii_connect_target_provider_slugs(normalized_query))


def _contains_external_action_marker(normalized_query: str) -> bool:
    return any(marker in normalized_query for marker in _EXTERNAL_ACTION_MARKERS)


def _contains_facebook_post_action_marker(normalized_query: str) -> bool:
    return any(marker in normalized_query for marker in _FACEBOOK_POST_ACTION_MARKERS)


def _looks_providerless_external_action_request(normalized_query: str) -> bool:
    return any(
        marker in normalized_query
        for marker in _PROVIDERLESS_EXTERNAL_SURFACE_MARKERS
    )


def _looks_provider_action_capability_question(normalized_query: str) -> bool:
    if not _contains_registered_provider_marker(normalized_query):
        return False
    if not _contains_external_action_marker(normalized_query):
        return False
    return any(
        marker in normalized_query
        for marker in (
            "co the",
            "co lam duoc",
            "lam duoc khong",
            "duoc khong",
            "duoc chu",
            "khong",
        )
    )


def _recent_wiii_connect_provider_slugs_from_state(
    state: dict[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(state, dict):
        return ()
    messages = state.get("messages")
    if not isinstance(messages, list):
        return ()
    for text in _iter_recent_message_text(messages):
        normalized = _normalize_for_intent(text)
        if not normalized:
            continue
        providers = resolve_wiii_connect_target_provider_slugs(text)
        if not providers:
            continue
        if _contains_external_action_marker(normalized) or any(
            marker in normalized for marker in _PROVIDER_CONTEXT_MARKERS
        ):
            return providers
    return ()


def _iter_recent_message_text(messages: list[Any]) -> tuple[str, ...]:
    texts: list[str] = []
    for message in reversed(messages[-8:]):
        text = _message_text(message)
        if text:
            texts.append(text)
    return tuple(texts)


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return ""
    content = (
        message.get("content")
        or message.get("text")
        or message.get("message")
        or message.get("answer")
    )
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return " ".join(part.strip() for part in parts if part.strip())
    return ""


def _marker_matches(normalized_query: str, marker: str) -> bool:
    normalized_marker = _normalize_for_intent(marker)
    if not normalized_marker:
        return False
    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(normalized_marker).replace(r"\ ", r"\s+")
        + r"(?![a-z0-9])"
    )
    return bool(re.search(pattern, normalized_query))


def wiii_connect_facebook_snapshot_from_state(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the best known Facebook connection snapshot for the current turn."""

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
        return _backend_wiii_connect_provider_snapshot_from_state(state, "facebook")
    page = host_context.get("page")
    if not isinstance(page, dict):
        return _backend_wiii_connect_provider_snapshot_from_state(state, "facebook")
    metadata = page.get("metadata")
    if not isinstance(metadata, dict):
        return _backend_wiii_connect_provider_snapshot_from_state(state, "facebook")
    snapshot = metadata.get("wiii_connect")
    if isinstance(snapshot, dict):
        provider_slug = _provider_slug(str(snapshot.get("provider_slug") or "facebook"))
        if provider_slug and provider_slug != "facebook":
            return _backend_wiii_connect_provider_snapshot_from_state(
                state,
                "facebook",
            )
        return dict(snapshot)
    return _backend_wiii_connect_provider_snapshot_from_state(state, "facebook")


def wiii_connect_provider_snapshot_from_state(
    state: dict[str, Any] | None,
    provider_slug: str,
) -> dict[str, Any]:
    """Return a provider-scoped Wiii Connect snapshot without raw payloads."""

    slug = _provider_slug(provider_slug)
    if not slug:
        return {}
    if slug == "facebook":
        return wiii_connect_facebook_snapshot_from_state(state)
    if not isinstance(state, dict):
        return {}
    return _backend_wiii_connect_provider_snapshot_from_state(state, slug)


def wiii_connect_provider_connection_lifecycle_from_state(
    state: dict[str, Any] | None,
    provider_slug: str,
) -> dict[str, Any]:
    """Return the sanitized lifecycle governing one provider in this turn."""

    slug = _provider_slug(provider_slug)
    if not slug:
        return {}
    return _connection_lifecycle_from_snapshot(
        wiii_connect_provider_snapshot_from_state(state, slug)
    )


def _backend_wiii_connect_provider_snapshot_from_state(
    state: dict[str, Any],
    provider_slug: str,
) -> dict[str, Any]:
    """Build a backend-owned provider status fallback without leaking secrets."""

    try:
        status = build_wiii_connect_snapshot(
            state=state,
            query="",
        ).provider_status(provider_slug)
    except Exception:
        return {}
    if not status:
        return {}
    reason = str(status.get("reason") or "").strip()
    payload = {
        "provider_slug": provider_slug,
        "status": status.get("status"),
        "agent_ready": status.get("agent_ready"),
        "active_connection_count": status.get("active_connection_count"),
        "connection_count": status.get("connection_count"),
        "connection_state": status.get("connection_state"),
        "blocked_reason": reason,
        "reason": reason,
    }
    lifecycle = status.get("connection_lifecycle")
    if isinstance(lifecycle, dict):
        payload["connection_lifecycle"] = _safe_connection_lifecycle(lifecycle)
    return payload


def _safe_connection_lifecycle(value: dict[str, Any]) -> dict[str, Any]:
    return sanitize_connection_lifecycle_metadata(value)


def _connection_lifecycle_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    lifecycle = snapshot.get("connection_lifecycle")
    return _safe_connection_lifecycle(lifecycle) if isinstance(lifecycle, dict) else {}


def _facebook_snapshot_allows_post(snapshot: dict[str, Any]) -> bool:
    lifecycle = _connection_lifecycle_from_snapshot(snapshot)
    status = (
        str(lifecycle.get("status") or "").strip().lower()
        or str(snapshot.get("status") or "").strip().lower()
    )
    if status != "connected":
        return False
    if snapshot.get("agent_ready") is False:
        return False
    return True


def build_wiii_connect_facebook_status_answer(
    state: dict[str, Any] | None,
) -> str:
    """Build a deterministic answer for Facebook connection status turns."""

    return build_wiii_connect_provider_status_answer(state, provider_slug="facebook")


def build_wiii_connect_provider_status_answer(
    state: dict[str, Any] | None,
    *,
    provider_slug: str,
) -> str:
    """Build a deterministic answer for provider connection status turns."""

    slug = _provider_slug(provider_slug)
    label = _provider_label(slug)
    snapshot = wiii_connect_provider_snapshot_from_state(state, slug)
    lifecycle = _connection_lifecycle_from_snapshot(snapshot)
    lifecycle_status = str(lifecycle.get("status") or "").strip().lower()
    lifecycle_reason = str(lifecycle.get("reason") or "").strip().lower()
    status = lifecycle_status or str(snapshot.get("status") or "").strip().lower()
    connection_state = (
        lifecycle_status
        or str(snapshot.get("connection_state") or "").strip().lower()
    )
    blocked_reason = (
        lifecycle_reason
        or str(snapshot.get("blocked_reason") or "").strip().lower()
    )
    page_names = snapshot.get("page_names")
    page_label = ""
    if isinstance(page_names, list):
        names = [str(name).strip() for name in page_names if str(name).strip()]
        if names:
            page_label = ", ".join(names[:3])
    active_count = snapshot.get("active_connection_count")
    connection_count = snapshot.get("connection_count")
    page_count = snapshot.get("page_count")
    connection_present = lifecycle.get("connection_present") is True

    if status == "connected" and snapshot.get("agent_ready") is False:
        state_label = blocked_reason or connection_state or "policy_not_ready"
        return (
            f"Wiii thấy {label} đã có kết nối active, nhưng agent chưa được phép dùng provider này "
            f"(lý do: {state_label}). Đây là trạng thái fail-closed đúng: connected chưa đồng nghĩa agent-ready. "
            "Cần hoàn tất policy/gateway/action allowlist trong Wiii Connect trước khi chat được thao tác với provider này."
        )

    if status == "connected":
        details: list[str] = []
        if isinstance(active_count, int):
            details.append(f"{active_count} account đang active")
        if isinstance(page_count, int):
            details.append(f"{page_count} page")
        if page_label:
            details.append(f"page: {page_label}")
        suffix = " (" + "; ".join(details) + ")" if details else ""
        action_hint = (
            "Nếu cậu muốn đăng bài, hãy gửi nội dung/ảnh rồi nói rõ “đăng lên Facebook”; "
            "Wiii sẽ gửi qua gateway preview/apply đã audit rồi publish bằng Composio."
            if slug == "facebook"
            else (
                f"Nếu cậu muốn Wiii thao tác với {label}, hãy gửi yêu cầu cụ thể; "
                "Wiii sẽ đi qua provider gateway đã audit."
            )
        )
        return (
            f"Có. {label} đang được kết nối qua Wiii Connect{suffix}. "
            f"{action_hint}"
        )

    if connection_present or (isinstance(connection_count, int) and connection_count > 0):
        state_label = blocked_reason or connection_state or "chưa active"
        return (
            f"Wiii đã thấy bản ghi {label} trong Wiii Connect, nhưng provider chưa ở trạng thái active "
            f"(trạng thái hiện tại: {state_label}). Vì vậy Wiii chưa được phép thao tác với provider này. "
            f"Hãy quay lại Wiii Connect, hoàn tất OAuth nếu còn tab xác nhận, rồi bấm làm mới hoặc kết nối lại {label}."
        )

    if status in {"disabled", "error", "expired", "pending", "authorizing", "waiting"}:
        state_label = blocked_reason or connection_state or status
        return (
            f"Mình chưa thể dùng {label} từ chat vì provider chưa agent-ready trong Wiii Connect "
            f"(trạng thái: {state_label}). Hãy mở Wiii Connect, kiểm tra adapter/policy/gateway "
            f"và kết nối {label} trước khi yêu cầu thao tác."
        )
    if status in {"not_connected", "unavailable"}:
        return (
            f"Hiện Wiii chưa thấy {label} ở trạng thái sẵn sàng trong runtime chat này. "
            f"Mở Wiii Connect, kiểm tra {label} đã connected và có scope hợp lệ rồi thử lại."
        )

    return (
        f"Mình chưa nhận được snapshot Wiii Connect cho {label} trong lượt chat này, "
        "nên không nên đoán trạng thái kết nối. Hãy mở Wiii Connect hoặc refresh lại Wiii rồi thử lại."
    )


def build_wiii_connect_facebook_post_unavailable_answer(
    state: dict[str, Any] | None,
) -> str | None:
    """Return a deterministic block message when Facebook cannot post yet."""

    snapshot = wiii_connect_facebook_snapshot_from_state(state)
    if not snapshot:
        return None
    lifecycle = _connection_lifecycle_from_snapshot(snapshot)
    lifecycle_status = str(lifecycle.get("status") or "").strip().lower()
    lifecycle_reason = str(lifecycle.get("reason") or "").strip().lower()
    status = lifecycle_status or str(snapshot.get("status") or "").strip().lower()
    if _facebook_snapshot_allows_post(snapshot):
        return None
    connection_count = snapshot.get("connection_count")
    active_count = snapshot.get("active_connection_count")
    connection_state = (
        lifecycle_status
        or str(snapshot.get("connection_state") or "").strip().lower()
    )
    blocked_reason = (
        lifecycle_reason
        or str(snapshot.get("blocked_reason") or "").strip().lower()
    )
    if status == "connected" and snapshot.get("agent_ready") is False:
        state_label = blocked_reason or connection_state or "policy_not_ready"
        active_label = active_count if isinstance(active_count, int) else 0
        total_label = connection_count if isinstance(connection_count, int) else active_label
        return (
            "Wiii đã thấy Facebook có account active trong Wiii Connect, "
            "nhưng agent chưa được phép đăng từ chat "
            f"({active_label}/{total_label} account active, lý do: {state_label}). "
            "Đây là trạng thái fail-closed đúng: connected chưa đồng nghĩa agent-ready. "
            "Cần hoàn tất adapter/policy/gateway/action allowlist trước khi Wiii được publish lên Facebook."
        )
    if lifecycle.get("connection_present") is True or (
        isinstance(connection_count, int) and connection_count > 0
    ):
        state_label = blocked_reason or connection_state or "chưa active"
        active_label = active_count if isinstance(active_count, int) else 0
        return (
            "Mình chưa thể đăng Facebook vì Wiii Connect chưa có account Facebook active "
            f"({active_label}/{connection_count} account active, trạng thái hiện tại: {state_label}). "
            "Hoàn tất OAuth trong Wiii Connect rồi bấm làm mới; khi account active, câu “đăng một bài Facebook” "
            "sẽ đi thẳng vào publish gateway đã audit."
        )
    if status in {"disabled", "error", "expired", "pending", "authorizing", "waiting"}:
        state_label = blocked_reason or connection_state or status
        return (
            "Mình chưa thể đăng Facebook vì provider chưa agent-ready trong Wiii Connect "
            f"(trạng thái: {state_label}). Hãy mở Wiii Connect, kiểm tra adapter/policy/gateway "
            "và kết nối Facebook trước khi yêu cầu đăng bài."
        )
    if status in {"not_connected", "unavailable"}:
        return (
            "Mình chưa thể đăng Facebook từ chat vì Wiii Connect chưa có kết nối Facebook sẵn sàng. "
            "Hãy mở Wiii Connect, kết nối Facebook trước; sau đó gửi lại yêu cầu đăng bài."
        )
    return None


def _provider_slug(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _provider_label(provider_slug: str) -> str:
    slug = _provider_slug(provider_slug)
    for entry in list_wiii_connect_provider_registry():
        if entry.slug == slug:
            return entry.label or entry.slug
    return slug or "provider"
