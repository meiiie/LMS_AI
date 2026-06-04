"""Typed policy metadata for Wiii tool capabilities.

This registry is intentionally about policy metadata, not tool construction.
Runtime collectors can still build tools from their native modules, while path
policy and execution guards share one source of truth for connection and
approval requirements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ToolCapabilityGroup = Literal[
    "utility",
    "web_search",
    "weather",
    "knowledge_search",
    "lms_query",
    "lms_authoring",
    "external_app_action",
    "host_action",
    "pointy",
    "product_search",
    "visual",
    "code_studio_output",
]
ToolPermissionLevel = Literal["read", "write", "host_control"]
ToolConnectionName = Literal["lms_authoring", "weather", "host_actions", "facebook"]
ToolSurfaceScope = Literal[
    "direct_chat",
    "diagnostic",
    "tutor",
    "code_studio",
    "host",
    "lms",
    "product_search",
    "visual",
]

TOOL_CAPABILITY_REGISTRY_VERSION = "tool_capability_registry.v1"

HOST_ACTION_PREFIX = "host_action__"
POINTY_TOOL_PREFIX = "tool_pointy_"
LMS_AUTHORING_PREFIX = f"{HOST_ACTION_PREFIX}authoring__"
WEATHER_TOOL_NAME = "tool_current_weather"
WEATHER_TOOL_NAMES = frozenset({WEATHER_TOOL_NAME})

DOC_PREVIEW_HOST_ACTION_TOOL = "host_action__authoring__preview_lesson_patch"
DOC_COURSE_HOST_ACTION_TOOL = "host_action__authoring__generate_course_from_document"
DOC_APPLY_LESSON_PATCH_TOOL = "host_action__authoring__apply_lesson_patch"
DOC_APPLY_COURSE_PLAN_TOOL = "host_action__authoring__apply_course_plan"
WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION = "wiii_connect.facebook_post.preview"
WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION = "wiii_connect.facebook_post.apply"
WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION = (
    "wiii_connect.facebook_post.direct_apply"
)
WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL = (
    "host_action__wiii_connect__facebook_post__preview"
)
WIII_CONNECT_FACEBOOK_POST_APPLY_TOOL = "host_action__wiii_connect__facebook_post__apply"
WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL = (
    "host_action__wiii_connect__facebook_post__direct_apply"
)
WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL = (
    "tool_wiii_connect_delegate_to_integration"
)
WIII_CONNECT_LIST_ACTIONS_TOOL = "tool_wiii_connect_list_actions"
WIII_CONNECT_EXECUTE_ACTION_TOOL = "tool_wiii_connect_execute_action"

DOCUMENT_PREVIEW_CAPABILITY_NAMES = frozenset(
    {
        "authoring.preview_lesson_patch",
        "authoring.generate_course_from_document",
    }
)
LMS_AUTHORING_APPLY_CAPABILITY_NAMES = frozenset(
    {
        "authoring.apply_lesson_patch",
        "authoring.apply_course_plan",
    }
)
LMS_AUTHORING_CAPABILITY_NAMES = (
    DOCUMENT_PREVIEW_CAPABILITY_NAMES | LMS_AUTHORING_APPLY_CAPABILITY_NAMES
)
LMS_DOCUMENT_PREVIEW_TOOL_NAMES = frozenset(
    {
        DOC_PREVIEW_HOST_ACTION_TOOL,
        DOC_COURSE_HOST_ACTION_TOOL,
    }
)
PRODUCT_SEARCH_TOOL_NAMES = frozenset(
    {
        "tool_search_google_shopping",
        "tool_search_shopee",
        "tool_search_tiktok_shop",
        "tool_search_lazada",
        "tool_search_facebook_marketplace",
        "tool_search_instagram_shopping",
        "tool_search_facebook_search",
        "tool_search_facebook_group",
        "tool_search_facebook_groups_auto",
        "tool_search_websosanh",
        "tool_search_all_web",
        "tool_fetch_product_detail",
        "tool_identify_product_from_image",
        "tool_dealer_search",
        "tool_international_search",
        "tool_extract_contacts",
        "tool_generate_product_report",
    }
)


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Policy-facing metadata for a tool name or dynamic tool family."""

    name: str
    group: ToolCapabilityGroup
    permission: ToolPermissionLevel = "read"
    required_connection: ToolConnectionName | None = None
    requires_agent_ready: bool = False
    expose_when_connection_inactive: bool = False
    mutates_state: bool = False
    requires_approval: bool = False
    surface_scopes: tuple[ToolSurfaceScope, ...] = ("direct_chat",)
    dynamic: bool = False
    host_action_name: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "permission": self.permission,
            "required_connection": self.required_connection,
            "requires_agent_ready": self.requires_agent_ready,
            "expose_when_connection_inactive": self.expose_when_connection_inactive,
            "mutates_state": self.mutates_state,
            "requires_approval": self.requires_approval,
            "surface_scopes": list(self.surface_scopes),
            "dynamic": self.dynamic,
            "host_action_name": self.host_action_name,
        }


def host_action_tool_name(action_name: str) -> str:
    """Map a host action name to the OpenAI-safe tool name Wiii binds."""

    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "__", str(action_name or "").strip())
    normalized = normalized.strip("_") or "host_action"
    return f"{HOST_ACTION_PREFIX}{normalized}"


def host_action_name_from_tool_name(tool_name: str) -> str:
    """Recover a dotted host action name from a generated host action tool."""

    name = _normalize_tool_name(tool_name)
    if not name.startswith(HOST_ACTION_PREFIX):
        return ""
    return name.removeprefix(HOST_ACTION_PREFIX).replace("__", ".")


def host_action_requires_approval_token(action_name: str) -> bool:
    """Return whether a host action needs host-issued approval evidence."""

    return _normalize_action_name(action_name) in LMS_AUTHORING_APPLY_CAPABILITY_NAMES


def lookup_tool_capability(tool_name: Any) -> ToolCapability | None:
    """Return policy metadata for a tool name, including dynamic host actions."""

    name = _normalize_tool_name(tool_name)
    if not name:
        return None
    static = TOOL_CAPABILITIES.get(name)
    if static is not None:
        return static
    if name.startswith(HOST_ACTION_PREFIX):
        return _dynamic_host_action_capability(name)
    if name.startswith(POINTY_TOOL_PREFIX):
        return ToolCapability(
            name=name,
            group="pointy",
            permission="host_control",
            surface_scopes=("direct_chat", "host"),
            dynamic=True,
        )
    return None


def is_lms_authoring_tool(tool_name: Any) -> bool:
    capability = lookup_tool_capability(tool_name)
    return bool(capability and capability.group == "lms_authoring")


def tool_requires_approval(tool_name: Any) -> bool:
    capability = lookup_tool_capability(tool_name)
    return bool(capability and capability.requires_approval)


def approval_required_tool_names_for(
    tool_names: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> frozenset[str]:
    return frozenset(
        _normalize_tool_name(name)
        for name in tool_names
        if _normalize_tool_name(name) and tool_requires_approval(name)
    )


def tool_requires_inactive_connection(
    tool_name: Any,
    connection_status: dict[str, dict[str, Any]] | None,
) -> bool:
    """Return True when a tool must be hidden because its connection is inactive."""

    capability = lookup_tool_capability(tool_name)
    if capability is None or capability.required_connection is None:
        return False
    if capability.expose_when_connection_inactive:
        return False
    status_map = connection_status if isinstance(connection_status, dict) else {}
    status = status_map.get(capability.required_connection)
    if not isinstance(status, dict):
        return True
    if capability.requires_agent_ready:
        return not bool(status.get("agent_ready"))
    return not bool(status.get("active"))


def tool_capability_metadata_for_names(
    tool_names: list[str] | tuple[str, ...] | set[str] | frozenset[str],
) -> dict[str, dict[str, Any]]:
    """Return serializable metadata for known tools in a candidate set."""

    metadata: dict[str, dict[str, Any]] = {}
    for raw_name in tool_names:
        name = _normalize_tool_name(raw_name)
        if not name:
            continue
        capability = lookup_tool_capability(name)
        if capability is not None:
            metadata[name] = capability.to_metadata()
    return metadata


def capability_names_for_group(group: ToolCapabilityGroup) -> frozenset[str]:
    return frozenset(
        name for name, capability in TOOL_CAPABILITIES.items()
        if capability.group == group
    )


def _dynamic_host_action_capability(tool_name: str) -> ToolCapability:
    action_name = host_action_name_from_tool_name(tool_name)
    if _normalize_action_name(action_name) in LMS_AUTHORING_CAPABILITY_NAMES:
        requires_approval = host_action_requires_approval_token(action_name)
        return ToolCapability(
            name=tool_name,
            group="lms_authoring",
            permission="write" if requires_approval else "host_control",
            required_connection="lms_authoring",
            mutates_state=requires_approval,
            requires_approval=requires_approval,
            surface_scopes=("direct_chat", "host", "lms"),
            dynamic=True,
            host_action_name=action_name,
        )
    return ToolCapability(
        name=tool_name,
        group="host_action",
        permission="host_control",
        required_connection="host_actions",
        mutates_state=True,
        surface_scopes=("direct_chat", "host"),
        dynamic=True,
        host_action_name=action_name or None,
    )


def _normalize_tool_name(value: Any) -> str:
    return str(value or "").strip()


def _normalize_action_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _capability(
    name: str,
    group: ToolCapabilityGroup,
    *,
    permission: ToolPermissionLevel = "read",
    required_connection: ToolConnectionName | None = None,
    requires_agent_ready: bool = False,
    expose_when_connection_inactive: bool = False,
    mutates_state: bool = False,
    requires_approval: bool = False,
    surface_scopes: tuple[ToolSurfaceScope, ...] = ("direct_chat",),
    host_action_name: str | None = None,
) -> ToolCapability:
    return ToolCapability(
        name=name,
        group=group,
        permission=permission,
        required_connection=required_connection,
        requires_agent_ready=requires_agent_ready,
        expose_when_connection_inactive=expose_when_connection_inactive,
        mutates_state=mutates_state,
        requires_approval=requires_approval,
        surface_scopes=surface_scopes,
        host_action_name=host_action_name,
    )


TOOL_CAPABILITIES: dict[str, ToolCapability] = {
    "tool_calculator": _capability("tool_calculator", "utility"),
    "tool_current_datetime": _capability("tool_current_datetime", "utility"),
    WEATHER_TOOL_NAME: _capability(
        WEATHER_TOOL_NAME,
        "weather",
        required_connection="weather",
        expose_when_connection_inactive=True,
    ),
    "tool_web_search": _capability("tool_web_search", "web_search"),
    "tool_search_news": _capability("tool_search_news", "web_search"),
    "tool_search_legal": _capability("tool_search_legal", "web_search"),
    "tool_search_maritime": _capability("tool_search_maritime", "web_search"),
    "tool_fetch_url": _capability("tool_fetch_url", "web_search"),
    "tool_knowledge_search": _capability("tool_knowledge_search", "knowledge_search"),
    "tool_rag_knowledge": _capability("tool_rag_knowledge", "knowledge_search"),
    "tool_check_student_grades": _capability("tool_check_student_grades", "lms_query"),
    "tool_list_upcoming_assignments": _capability("tool_list_upcoming_assignments", "lms_query"),
    "tool_check_course_progress": _capability("tool_check_course_progress", "lms_query"),
    "tool_get_class_overview": _capability("tool_get_class_overview", "lms_query"),
    "tool_find_at_risk_students": _capability("tool_find_at_risk_students", "lms_query"),
    **{
        name: _capability(
            name,
            "product_search",
            permission="write" if name == "tool_generate_product_report" else "read",
            surface_scopes=("product_search",),
        )
        for name in sorted(PRODUCT_SEARCH_TOOL_NAMES)
    },
    "tool_pointy_show": _capability(
        "tool_pointy_show",
        "pointy",
        permission="host_control",
        surface_scopes=("direct_chat", "host"),
    ),
    "tool_pointy_clear": _capability(
        "tool_pointy_clear",
        "pointy",
        permission="host_control",
        surface_scopes=("direct_chat", "host"),
    ),
    "tool_pointy_inventory": _capability(
        "tool_pointy_inventory",
        "pointy",
        permission="read",
        surface_scopes=("direct_chat", "host"),
    ),
    "tool_generate_visual": _capability(
        "tool_generate_visual",
        "visual",
        surface_scopes=("direct_chat", "visual"),
    ),
    "tool_create_visual_code": _capability(
        "tool_create_visual_code",
        "visual",
        surface_scopes=("direct_chat", "code_studio", "visual"),
    ),
    "tool_generate_mermaid": _capability(
        "tool_generate_mermaid",
        "visual",
        surface_scopes=("direct_chat", "visual"),
    ),
    "tool_generate_chart": _capability(
        "tool_generate_chart",
        "visual",
        surface_scopes=("direct_chat", "visual"),
    ),
    "tool_generate_interactive_chart": _capability(
        "tool_generate_interactive_chart",
        "visual",
        surface_scopes=("direct_chat", "visual"),
    ),
    "tool_generate_html_file": _capability(
        "tool_generate_html_file",
        "code_studio_output",
        permission="write",
        mutates_state=False,
        surface_scopes=("code_studio",),
    ),
    "tool_generate_excel_file": _capability(
        "tool_generate_excel_file",
        "code_studio_output",
        permission="write",
        mutates_state=False,
        surface_scopes=("code_studio",),
    ),
    "tool_generate_word_document": _capability(
        "tool_generate_word_document",
        "code_studio_output",
        permission="write",
        mutates_state=False,
        surface_scopes=("code_studio",),
    ),
    DOC_PREVIEW_HOST_ACTION_TOOL: _capability(
        DOC_PREVIEW_HOST_ACTION_TOOL,
        "lms_authoring",
        permission="host_control",
        required_connection="lms_authoring",
        surface_scopes=("direct_chat", "host", "lms"),
        host_action_name="authoring.preview_lesson_patch",
    ),
    DOC_COURSE_HOST_ACTION_TOOL: _capability(
        DOC_COURSE_HOST_ACTION_TOOL,
        "lms_authoring",
        permission="host_control",
        required_connection="lms_authoring",
        surface_scopes=("direct_chat", "host", "lms"),
        host_action_name="authoring.generate_course_from_document",
    ),
    DOC_APPLY_LESSON_PATCH_TOOL: _capability(
        DOC_APPLY_LESSON_PATCH_TOOL,
        "lms_authoring",
        permission="write",
        required_connection="lms_authoring",
        mutates_state=True,
        requires_approval=True,
        surface_scopes=("direct_chat", "host", "lms"),
        host_action_name="authoring.apply_lesson_patch",
    ),
    DOC_APPLY_COURSE_PLAN_TOOL: _capability(
        DOC_APPLY_COURSE_PLAN_TOOL,
        "lms_authoring",
        permission="write",
        required_connection="lms_authoring",
        mutates_state=True,
        requires_approval=True,
        surface_scopes=("direct_chat", "host", "lms"),
        host_action_name="authoring.apply_course_plan",
    ),
    WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL: _capability(
        WIII_CONNECT_FACEBOOK_POST_PREVIEW_TOOL,
        "external_app_action",
        permission="host_control",
        mutates_state=False,
        requires_approval=False,
        surface_scopes=("direct_chat", "host"),
        host_action_name=WIII_CONNECT_FACEBOOK_POST_PREVIEW_ACTION,
    ),
    WIII_CONNECT_FACEBOOK_POST_APPLY_TOOL: _capability(
        WIII_CONNECT_FACEBOOK_POST_APPLY_TOOL,
        "external_app_action",
        permission="write",
        mutates_state=True,
        requires_approval=True,
        surface_scopes=("direct_chat", "host"),
        host_action_name=WIII_CONNECT_FACEBOOK_POST_APPLY_ACTION,
    ),
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL: _capability(
        WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        "external_app_action",
        permission="write",
        required_connection="facebook",
        requires_agent_ready=True,
        mutates_state=True,
        requires_approval=False,
        surface_scopes=("direct_chat", "host"),
        host_action_name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    ),
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL: _capability(
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        "external_app_action",
        permission="write",
        mutates_state=True,
        requires_approval=True,
        surface_scopes=("direct_chat",),
    ),
    WIII_CONNECT_LIST_ACTIONS_TOOL: _capability(
        WIII_CONNECT_LIST_ACTIONS_TOOL,
        "external_app_action",
        permission="read",
        mutates_state=False,
        requires_approval=False,
        surface_scopes=("direct_chat",),
    ),
    WIII_CONNECT_EXECUTE_ACTION_TOOL: _capability(
        WIII_CONNECT_EXECUTE_ACTION_TOOL,
        "external_app_action",
        permission="write",
        mutates_state=True,
        requires_approval=True,
        surface_scopes=("diagnostic",),
    ),
}
