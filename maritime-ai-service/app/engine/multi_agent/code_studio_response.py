"""Code Studio chat-surface sanitization helpers."""

from __future__ import annotations

import re
from typing import Optional

from app.engine.multi_agent.code_studio_context import _last_inline_visual_title
from app.engine.multi_agent.code_studio_surface import (
    _DOCUMENT_STUDIO_TOOLS,
    _extract_code_studio_artifact_names,
    _is_document_studio_tool_error,
)
from app.engine.multi_agent.code_studio_patterns import (
    _CODE_STUDIO_ACTION_JSON_RE,
    _CODE_STUDIO_SANDBOX_IMAGE_RE,
    _CODE_STUDIO_SANDBOX_LINK_RE,
    _CODE_STUDIO_SANDBOX_PATH_RE,
)
from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.state import AgentState

_CODE_STUDIO_CHATTER_TOKENS = (
    "rat vui duoc gap",
    "minh la wiii",
    "toi la wiii",
    "bong",
    "meo ao",
    "meo meo",
    "catchphrase",
)

_CODE_DUMP_BOUNDARY_MARKERS = (
    "```",
    "<style",
    "<script",
    "<!doctype",
    "<html",
    "<svg",
    "<canvas",
    "<section",
    "<div",
)


def _is_code_studio_chatter_paragraph(paragraph: str) -> bool:
    """Detect social/persona chatter that should not lead a technical delivery."""
    normalized = _normalize_for_intent(paragraph)
    if not normalized:
        return False
    if any(token in normalized for token in _CODE_STUDIO_CHATTER_TOKENS):
        return True
    if normalized.startswith(("chao ", "xin chao", "hello ", "hi ", "alo ")):
        return True
    return False


def _strip_code_studio_chatter(cleaned: str) -> str:
    """Remove greeting/lore paragraphs when better technical paragraphs exist."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if not paragraphs:
        return cleaned

    filtered = [part for part in paragraphs if not _is_code_studio_chatter_paragraph(part)]
    if filtered and len(filtered) < len(paragraphs):
        return "\n\n".join(filtered).strip()
    return cleaned


def _ensure_code_studio_delivery_lede(cleaned: str, tool_call_events: list[dict] | None = None) -> str:
    """Ensure the answer starts from the artifact/result, not from social filler."""
    artifact_names = _extract_code_studio_artifact_names(tool_call_events)
    if not artifact_names:
        return cleaned

    first_paragraph = next((part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()), "")
    normalized_first = _normalize_for_intent(first_paragraph)
    normalized_artifact = _normalize_for_intent(artifact_names[0])
    if any(
        token in normalized_first
        for token in ("da tao", "da hoan thanh", "da xac nhan", "artifact", normalized_artifact)
    ):
        return cleaned

    lede = f"Minh da tao xong `{artifact_names[0]}` va gan kem artifact ngay ben duoi."
    return f"{lede}\n\n{cleaned}".strip()


def _looks_like_raw_code_dump(cleaned: str) -> bool:
    stripped = (cleaned or "").lstrip()
    if not stripped:
        return False
    if stripped.startswith(("```html", "```tsx", "```jsx", "```javascript", "```js", "```css", "```")):
        return True
    if stripped.startswith(("<style", "<html", "<!doctype", "<div", "<script", "<svg", "<section")):
        return True
    html_marker_hits = sum(
        1 for marker in ("<div", "<style", "<script", "<canvas", "<section", "<svg")
        if marker in stripped[:1200].lower()
    )
    return html_marker_hits >= 2


def _truncate_before_code_dump(text: str) -> str:
    """Keep only the user-facing prose prefix before raw code begins."""
    raw = text or ""
    if not raw:
        return ""
    lowered = raw.lower()
    cut_points = [
        lowered.find(marker)
        for marker in _CODE_DUMP_BOUNDARY_MARKERS
        if lowered.find(marker) >= 0
    ]
    if not cut_points:
        return raw
    return raw[: min(cut_points)].rstrip()


def _tool_events_include_visual_code(tool_call_events: list[dict] | None) -> bool:
    for event in tool_call_events or []:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "result":
            continue
        if str(event.get("name", "")).strip() == "tool_create_visual_code":
            return True
    return False


def _collapse_code_studio_source_dump(
    cleaned: str,
    tool_call_events: list[dict] | None = None,
    state: Optional[AgentState] = None,
) -> str:
    """Keep raw source inside Code Studio when an active session already exists."""
    has_inline_code_boundary = _truncate_before_code_dump(cleaned) != (cleaned or "")
    if not _looks_like_raw_code_dump(cleaned) and not (
        _tool_events_include_visual_code(tool_call_events) and has_inline_code_boundary
    ):
        return cleaned

    if _tool_events_include_visual_code(tool_call_events):
        title = _last_inline_visual_title(state) or "visual nay"
        lede = f"Mình đã dựng xong `{title}` và ghim phần trực quan ngay bên trên."
        body = (
            "Phần mã đầy đủ mình giữ trong Code Studio để khung chat vẫn gọn, còn bạn thì vẫn có thể mở hoặc patch tiếp trên cùng session."
        )
        next_step = (
            "Nếu muốn, mình có thể chỉnh tiếp ánh sáng, bố cục, chuyển động, hoặc sắc thái cảm xúc của cảnh này."
        )
        return f"{lede}\n\n{body}\n\n{next_step}".strip()

    ctx = ((state or {}).get("context") or {}) if isinstance(state, dict) else {}
    if not isinstance(ctx, dict):
        return cleaned

    raw_studio = ctx.get("code_studio_context")
    if not isinstance(raw_studio, dict) or not raw_studio:
        return cleaned

    active_session = raw_studio.get("active_session")
    if not isinstance(active_session, dict) or not active_session:
        return cleaned

    title = str(active_session.get("title") or "artifact hien tai").strip()
    requested_view = str(raw_studio.get("requested_view") or "").strip().lower()

    lede = (
        f"Mình đã mở Code Studio ở tab Code cho `{title}`."
        if requested_view == "code"
        else f"Code đầy đủ cho `{title}` đang nằm trong Code Studio."
    )
    body = (
        "Mình giữ phần chat gọn để dễ đọc: bên trong đó hiện tại có 3 lớp chính là render surface,"
        " controls, và logic trạng thái/tương tác."
    )
    next_step = "Nếu cần, mình có thể giải thích từng phần code hoặc patch tiếp ngay trên cùng session này."
    return f"{lede}\n\n{body}\n\n{next_step}".strip()


def _sanitize_code_studio_response(
    response: str,
    tool_call_events: list[dict] | None = None,
    state: Optional[AgentState] = None,
) -> str:
    cleaned = response or ""
    had_raw_payload = False

    for pattern in (
        _CODE_STUDIO_ACTION_JSON_RE,
        _CODE_STUDIO_SANDBOX_IMAGE_RE,
        _CODE_STUDIO_SANDBOX_LINK_RE,
        _CODE_STUDIO_SANDBOX_PATH_RE,
    ):
        updated = pattern.sub("", cleaned)
        if updated != cleaned:
            had_raw_payload = True
            cleaned = updated

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    cleaned = _strip_code_studio_chatter(cleaned)
    cleaned = _ensure_code_studio_delivery_lede(cleaned, tool_call_events)
    cleaned = _collapse_code_studio_source_dump(cleaned, tool_call_events, state)

    if had_raw_payload:
        artifact_names = _extract_code_studio_artifact_names(tool_call_events)
        note = (
            f"File `{artifact_names[0]}` da duoc tao va gan kem trong artifact ngay ben duoi."
            if artifact_names
            else "Artifact ky thuat da duoc tao va gan kem ngay ben duoi."
        )
        if note not in cleaned:
            cleaned = f"{cleaned}\n\n{note}".strip()

    return cleaned


def _is_terminal_code_studio_tool_error(tool_name: str, result: object) -> bool:
    """Detect tool failures that should stop the code-studio loop immediately."""
    normalized_name = str(tool_name or "").strip().lower()

    normalized_result = _normalize_for_intent(str(result or ""))
    if not normalized_result:
        return False

    if "tool unavailable" in normalized_result and normalized_name in {
        "tool_execute_python",
        "tool_browser_snapshot_url",
        "tool_create_visual_code",
    }:
        return True

    if normalized_name in {"tool_execute_python", "tool_browser_snapshot_url"}:
        return (
            "opensandbox execution failed" in normalized_result
            and "network connectivity error" in normalized_result
        )

    if normalized_name in _DOCUMENT_STUDIO_TOOLS:
        return _is_document_studio_tool_error(normalized_name, result)

    return False
