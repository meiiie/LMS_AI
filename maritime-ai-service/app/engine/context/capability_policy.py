"""Org-aware capability filtering for host actions.

Keeps the host/plugin contract reusable across hosts while letting Wiii
respect org-level permissions before exposing or invoking mutating actions.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.org_settings import get_org_permissions


_PERMISSION_ALIASES = {
    "course.author": "manage:courses",
    "course.manage": "manage:courses",
    "course.write": "manage:courses",
    "lms.course.author": "manage:courses",
    "lms.course.manage": "manage:courses",
    "lms.course.write": "manage:courses",
}


def _normalize_permission_token(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    return _PERMISSION_ALIASES.get(token.lower(), token)


def _normalize_permissions(tool_def: dict[str, Any]) -> list[str]:
    permissions = tool_def.get("required_permissions")
    if isinstance(permissions, list):
        return [
            normalized
            for item in permissions
            if (normalized := _normalize_permission_token(item))
        ]

    permission = _normalize_permission_token(tool_def.get("permission"))
    if permission:
        return [permission]

    action_name = str(tool_def.get("name") or "").strip().lower()
    if not action_name:
        return []

    if action_name.startswith("navigation.") or action_name == "capture_screenshot":
        return ["use:tools"]
    if action_name.startswith("authoring."):
        return ["manage:courses"]
    if action_name.startswith("assessment."):
        return ["manage:courses"]
    if action_name.startswith("publish."):
        return ["manage:courses"]
    if action_name.startswith("analytics."):
        return ["read:analytics", "read:org_analytics", "read:org_dashboard"]
    if action_name.startswith("governance."):
        return ["manage:settings", "manage:org_settings", "manage:members", "manage:knowledge", "manage:branding"]

    return []


def _resolve_org_role(user_id: Optional[str], organization_id: Optional[str]) -> Optional[str]:
    if not user_id or not organization_id:
        return None

    try:
        from app.repositories.organization_repository import get_organization_repository

        return get_organization_repository().get_user_org_role(user_id, organization_id)
    except Exception:
        return None


def is_host_action_allowed(
    tool_def: dict[str, Any],
    *,
    user_role: Optional[str],
    organization_id: Optional[str],
    user_id: Optional[str],
) -> bool:
    role = str(user_role or "").strip() or "student"
    roles = tool_def.get("roles")
    if isinstance(roles, list) and roles and role not in [str(item).strip() for item in roles]:
        return False
    required_permissions = _normalize_permissions(tool_def)
    if not required_permissions:
        return True

    org_role = _resolve_org_role(user_id, organization_id)
    granted = set(get_org_permissions(organization_id, role, org_role=org_role))
    return any(permission in granted for permission in required_permissions)


def filter_host_actions_for_org(
    actions: list[dict[str, Any]] | None,
    *,
    user_role: Optional[str],
    organization_id: Optional[str],
    user_id: Optional[str],
) -> list[dict[str, Any]]:
    if not actions:
        return []

    result: list[dict[str, Any]] = []
    for raw_action in actions:
        action = raw_action if isinstance(raw_action, dict) else dict(raw_action)
        if is_host_action_allowed(
            action,
            user_role=user_role,
            organization_id=organization_id,
            user_id=user_id,
        ):
            result.append(action)
    return result


def filter_host_capabilities_for_org(
    raw_caps: dict[str, Any] | None,
    *,
    user_role: Optional[str],
    organization_id: Optional[str],
    user_id: Optional[str],
) -> dict[str, Any]:
    if not isinstance(raw_caps, dict):
        return raw_caps or {}

    tools = raw_caps.get("tools")
    filtered_tools = filter_host_actions_for_org(
        tools if isinstance(tools, list) else [],
        user_role=user_role,
        organization_id=organization_id,
        user_id=user_id,
    )
    return {
        **raw_caps,
        "tools": filtered_tools,
    }
