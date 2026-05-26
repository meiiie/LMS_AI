"""Shared uploaded-document preview/course contract for direct runtimes."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Any

from app.engine.tools.tool_capability_registry import (
    DOC_COURSE_HOST_ACTION_TOOL,
    DOC_PREVIEW_HOST_ACTION_TOOL,
    DOCUMENT_PREVIEW_CAPABILITY_NAMES,
    LMS_AUTHORING_CAPABILITY_NAMES,
)

_COURSE_REQUEST_BLOCKERS = (
    "preview_lesson_patch",
    "lesson patch",
    "bai hoc hien tai",
    "cap nhat bai hoc",
)

_COURSE_REQUEST_MARKERS = (
    "generate_course_from_document",
    "course architect",
    "course plan",
    "course outline",
    "course syllabus",
    "curriculum",
    "full course",
    "lap bai giang",
    "soan bai giang",
    "soan giao an",
    "tao bai giang",
    "tao giao an",
    "tao hoc lieu",
    "toan bo khoa",
    "cay khoa",
    "chia khoa",
    "chia thanh bai",
    "chia thanh chuong",
    "chuong trinh dao tao",
    "de cuong khoa",
    "de cuong mon",
    "giao trinh",
    "ke hoach giang day",
    "khoa dao tao",
    "khoa day du",
    "khoa hoan chinh",
    "learning path",
    "lo trinh hoc",
    "lo trinh khoa",
    "nhieu bai hoc",
    "nhieu chuong",
    "phan chia bai hoc",
    "syllabus",
    "tao khoa hoc",
    "thiet ke bai giang",
    "thiet ke khoa hoc",
    "xay dung bai giang",
    "cau truc khoa hoc",
    "chuong/bai",
    "chuong bai",
    "module",
    "outline",
)

_LESSON_AUTHORING_EXCLUSION_MARKERS = (
    "bai tap",
    "bai kiem tra",
    "cau hoi",
    "kiem tra",
    "quiz",
)

_LESSON_AUTHORING_VERBS = (
    "build",
    "create",
    "lam",
    "lap",
    "soan",
    "tao",
    "thiet ke",
    "viet",
    "write",
    "xay dung",
)

_LESSON_PREVIEW_REQUEST_MARKERS = (
    "approval_token",
    "ban nhap",
    "ban xem truoc",
    "cap nhat bai hoc",
    "citation",
    "diff",
    "draft",
    "lesson patch",
    "preview",
    "preview_lesson_patch",
    "source references",
    "source_references",
    "tao ban xem truoc",
    "trich dan",
    "xem truoc",
)


def normalize_document_contract_text(value: Any) -> str:
    text = str(value or "").replace("\\_", "_")
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()


def as_plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(exclude_none=True)
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "dict"):
        try:
            dumped = value.dict(exclude_none=True)
            return dumped if isinstance(dumped, dict) else {}
        except Exception:
            return {}
    return {}


def _merge_plain_mappings(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in reversed(values):
        mapping = as_plain_mapping(value)
        for key, item in mapping.items():
            if item is not None and item != "":
                merged[key] = item
    return merged


def _plain_state_context(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    return as_plain_mapping(state.get("context"))


def _normalized_connection_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _normalized_connection_key(value: Any) -> str:
    return _normalized_connection_value(value).lower()


def lms_authoring_connection_status(
    state: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return fail-closed LMS authoring connection status for this turn.

    Host capabilities only describe what a page can do. For LMS authoring
    actions, Wiii also needs an active LMS host session: LMS host type,
    connector id, and a linked host/user identity. This mirrors external
    integration gating: unconnected services should not expose live tools.
    """

    ctx = as_plain_mapping(ctx)
    state_context = _plain_state_context(state)
    state_map = state if isinstance(state, dict) else {}

    host_context = _merge_plain_mappings(
        ctx.get("host_context"),
        state_context.get("host_context"),
        state_map.get("host_context"),
    )
    host_capabilities = _merge_plain_mappings(
        ctx.get("host_capabilities"),
        state_context.get("host_capabilities"),
        state_map.get("host_capabilities"),
    )

    host_type = _normalized_connection_key(
        host_context.get("host_type") or host_capabilities.get("host_type")
    )
    if host_type != "lms":
        return {
            "active": False,
            "reason": "missing_lms_host",
            "host_type": host_type or None,
        }

    connector_id = _normalized_connection_value(
        host_context.get("connector_id")
        or host_capabilities.get("connector_id")
        or ctx.get("lms_connector_id")
        or state_context.get("lms_connector_id")
    )
    if not connector_id:
        return {
            "active": False,
            "reason": "missing_lms_connector",
            "host_type": host_type,
        }

    host_user_id = _normalized_connection_value(
        host_context.get("host_user_id")
        or ctx.get("lms_external_id")
        or state_context.get("lms_external_id")
    )
    if not host_user_id:
        return {
            "active": False,
            "reason": "missing_lms_identity",
            "host_type": host_type,
            "connector_id": connector_id,
        }

    return {
        "active": True,
        "reason": "active",
        "host_type": host_type,
        "connector_id": connector_id,
        "host_user_id_present": True,
    }


def has_active_lms_authoring_connection(
    state: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> bool:
    return bool(lms_authoring_connection_status(state, ctx).get("active"))


def filter_lms_authoring_capability_tools(
    capabilities_tools: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Drop LMS authoring tools when the current turn is not connected to LMS."""

    if not capabilities_tools:
        return []

    lms_authoring_tools = [
        tool
        for tool in capabilities_tools
        if str(tool.get("name") or "").strip().lower()
        in LMS_AUTHORING_CAPABILITY_NAMES
    ]
    if not lms_authoring_tools:
        return capabilities_tools

    if has_active_lms_authoring_connection(state, ctx):
        return capabilities_tools

    return [
        tool
        for tool in capabilities_tools
        if str(tool.get("name") or "").strip().lower()
        not in LMS_AUTHORING_CAPABILITY_NAMES
    ]


def uploaded_document_attachments_from_context(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = as_plain_mapping(ctx)
    document_context = as_plain_mapping(ctx.get("document_context"))
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return []

    parsed: list[dict[str, Any]] = []
    for item in attachments:
        attachment = as_plain_mapping(item)
        if attachment and str(attachment.get("markdown") or "").strip():
            parsed.append(attachment)
    return parsed


def has_uploaded_document_context(ctx: dict[str, Any]) -> bool:
    return bool(uploaded_document_attachments_from_context(ctx))


def uploaded_document_attachments_from_state(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    ctx = state.get("context")
    if not isinstance(ctx, dict):
        return []
    return uploaded_document_attachments_from_context(ctx)


def looks_uploaded_document_course_request(query: str) -> bool:
    normalized = normalize_document_contract_text(query)
    if any(marker in normalized for marker in _COURSE_REQUEST_BLOCKERS):
        return False
    return any(marker in normalized for marker in _COURSE_REQUEST_MARKERS)


def _looks_singular_lesson_authoring_request(normalized: str) -> bool:
    if not ("bai hoc" in normalized or "lesson" in normalized):
        return False
    if any(marker in normalized for marker in _LESSON_AUTHORING_EXCLUSION_MARKERS):
        return False
    return any(marker in normalized for marker in _LESSON_AUTHORING_VERBS)


def looks_uploaded_document_lesson_preview_request(query: str) -> bool:
    normalized = normalize_document_contract_text(query)
    if not normalized:
        return False
    return any(marker in normalized for marker in _LESSON_PREVIEW_REQUEST_MARKERS) or (
        _looks_singular_lesson_authoring_request(normalized)
    )


def _runtime_tool_name(
    tool: Any,
    *,
    tool_name_resolver: Callable[[Any], str] | None = None,
) -> str:
    if tool_name_resolver is not None:
        try:
            return str(tool_name_resolver(tool) or "").strip().lower()
        except Exception:
            return ""
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "")).strip().lower()


def find_document_host_action_tool(
    tools: list[Any],
    desired_tool_name: str,
    *,
    tool_name_resolver: Callable[[Any], str] | None = None,
) -> Any | None:
    desired = str(desired_tool_name or "").strip().lower()
    for tool in tools or []:
        if _runtime_tool_name(tool, tool_name_resolver=tool_name_resolver) == desired:
            return tool
    return None


def has_document_preview_host_action_tool(
    tools: list[Any],
    *,
    tool_name_resolver: Callable[[Any], str] | None = None,
) -> bool:
    return any(
        _runtime_tool_name(tool, tool_name_resolver=tool_name_resolver)
        in {DOC_PREVIEW_HOST_ACTION_TOOL, DOC_COURSE_HOST_ACTION_TOOL}
        for tool in tools or []
    )


def document_preview_forced_tool_choice(
    query: str,
    tools: list[Any],
    *,
    tool_name_resolver: Callable[[Any], str] | None = None,
) -> str:
    preferred = (
        DOC_COURSE_HOST_ACTION_TOOL
        if looks_uploaded_document_course_request(query)
        else DOC_PREVIEW_HOST_ACTION_TOOL
    )
    tool_names = {
        _runtime_tool_name(tool, tool_name_resolver=tool_name_resolver)
        for tool in tools or []
    }
    if preferred in tool_names:
        return preferred
    if DOC_PREVIEW_HOST_ACTION_TOOL in tool_names:
        return DOC_PREVIEW_HOST_ACTION_TOOL
    return DOC_COURSE_HOST_ACTION_TOOL


def extract_document_preview_capabilities(
    state: dict[str, Any],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    """Recover LMS preview capability definitions from raw runtime state."""

    state_context = state.get("context") if isinstance(state.get("context"), dict) else {}
    raw_sources = [
        state.get("host_capabilities"),
        ctx.get("host_capabilities"),
        state_context.get("host_capabilities") if isinstance(state_context, dict) else None,
    ]
    preview_capabilities: list[dict[str, Any]] = []
    for raw_caps in raw_sources:
        caps = as_plain_mapping(raw_caps)
        raw_tools = caps.get("tools")
        if not isinstance(raw_tools, list):
            continue
        for raw_tool in raw_tools:
            tool_def = as_plain_mapping(raw_tool)
            name = str(tool_def.get("name") or "").strip().lower()
            if name in DOCUMENT_PREVIEW_CAPABILITY_NAMES:
                preview_capabilities.append(tool_def)
    return preview_capabilities
