"""Shared uploaded-document preview/course contract for direct runtimes."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Any

DOC_PREVIEW_HOST_ACTION_TOOL = "host_action__authoring__preview_lesson_patch"
DOC_COURSE_HOST_ACTION_TOOL = "host_action__authoring__generate_course_from_document"

DOCUMENT_PREVIEW_CAPABILITY_NAMES = {
    "authoring.preview_lesson_patch",
    "authoring.generate_course_from_document",
}

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


def normalize_document_contract_text(value: Any) -> str:
    text = str(value or "").replace("\\_", "_")
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
