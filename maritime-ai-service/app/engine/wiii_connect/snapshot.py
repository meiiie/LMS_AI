"""Privacy-safe Wiii Connect capability snapshot.

This module is the V0 backend contract for Wiii Connect. It normalizes current
runtime connection facts into one serializable shape before tool policy consumes
them. It must never include secrets, raw document text, raw prompts, provider
payloads, or approval tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    lms_authoring_connection_status,
)


WIII_CONNECT_SNAPSHOT_VERSION = "wiii_connect_snapshot.v0"

ProviderKind = Literal[
    "wiii_native",
    "composio",
    "mcp",
    "custom_oauth",
    "workflow",
]
ConnectionStatus = Literal[
    "connected",
    "not_connected",
    "pending",
    "expired",
    "error",
    "preview",
    "disabled",
]
MutationPolicy = Literal[
    "none",
    "preview_only",
    "approval_token_required",
    "explicit_user_confirmation_required",
]
DelegationPolicy = Literal[
    "direct_only",
    "delegate_to_path_agent",
    "delegate_to_integration_agent",
]


@dataclass(frozen=True, slots=True)
class WiiiConnectionScopes:
    """Permission flags for one Wiii Connect connection."""

    read: bool = False
    preview: bool = False
    write: bool = False
    apply: bool = False
    admin: bool = False

    def to_metadata(self) -> dict[str, bool]:
        return {
            "read": self.read,
            "preview": self.preview,
            "write": self.write,
            "apply": self.apply,
            "admin": self.admin,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectionRecord:
    """One connection/capability row in the Wiii Connect snapshot."""

    slug: str
    label: str
    provider_kind: ProviderKind = "wiii_native"
    status: ConnectionStatus = "not_connected"
    agent_ready: bool = False
    scopes: WiiiConnectionScopes = field(default_factory=WiiiConnectionScopes)
    capabilities: tuple[str, ...] = ()
    required_for_paths: tuple[str, ...] = ()
    source: str = "runtime"
    reason: str = ""
    id: str | None = None
    last_checked_at: str | None = None
    warnings: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return self.status in {"connected", "preview"}

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "provider_kind": self.provider_kind,
            "slug": self.slug,
            "label": self.label,
            "status": self.status,
            "active": self.active,
            "agent_ready": self.agent_ready,
            "scopes": self.scopes.to_metadata(),
            "capabilities": list(self.capabilities),
            "required_for_paths": list(self.required_for_paths),
            "source": self.source,
            "last_checked_at": self.last_checked_at,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }
        for key, value in self.details.items():
            if key not in payload and _is_safe_scalar_or_count(value):
                payload[key] = value
        return payload

    def to_connection_status(self) -> dict[str, Any]:
        payload = {
            "active": self.active,
            "reason": self.reason,
            "status": self.status,
            "agent_ready": self.agent_ready,
            "scopes": self.scopes.to_metadata(),
            "capabilities": list(self.capabilities),
            "warnings": list(self.warnings),
        }
        for key, value in self.details.items():
            if _is_safe_scalar_or_count(value):
                payload[key] = value
        return payload


@dataclass(frozen=True, slots=True)
class WiiiPathCapabilityRecord:
    """Path-level policy summary for Wiii Connect V0."""

    path: str
    allowed_connection_slugs: tuple[str, ...] = ()
    required_connection_slugs: tuple[str, ...] = ()
    allowed_tool_groups: tuple[str, ...] = ()
    forbidden_tool_groups: tuple[str, ...] = ()
    mutation_policy: MutationPolicy = "none"
    delegation_policy: DelegationPolicy = "direct_only"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "allowed_connection_slugs": list(self.allowed_connection_slugs),
            "required_connection_slugs": list(self.required_connection_slugs),
            "allowed_tool_groups": list(self.allowed_tool_groups),
            "forbidden_tool_groups": list(self.forbidden_tool_groups),
            "mutation_policy": self.mutation_policy,
            "delegation_policy": self.delegation_policy,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectionSnapshot:
    """Serializable Wiii Connect snapshot for one runtime turn."""

    version: str
    generated_at: str
    surface: str
    connections: tuple[WiiiConnectionRecord, ...]
    path_capabilities: tuple[WiiiPathCapabilityRecord, ...]
    warnings: tuple[str, ...] = ()
    runtime_status: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "surface": self.surface,
            "connections": [connection.to_metadata() for connection in self.connections],
            "path_capabilities": [item.to_metadata() for item in self.path_capabilities],
            "warnings": list(self.warnings),
        }

    def connection_status_map(self) -> dict[str, dict[str, Any]]:
        """Return the legacy-compatible status map consumed by tool policy."""

        status = {
            connection.slug: connection.to_connection_status()
            for connection in self.connections
        }
        status.update({key: dict(value) for key, value in self.runtime_status.items()})
        return status


def build_wiii_connect_snapshot(
    *,
    state: dict[str, Any] | None,
    query: str = "",
    surface: str | None = None,
) -> WiiiConnectionSnapshot:
    """Build a privacy-safe Wiii Connect snapshot from current runtime state."""

    now = datetime.now(UTC).isoformat()
    context = _context_from_state(state)
    host_context = _host_context(state, context)
    host_capabilities = _host_capabilities(state, context)
    document_context = _document_context(state, context)

    connections = (
        _server_connection(now),
        _host_connection(host_context, host_capabilities, now),
        _host_actions_connection(host_capabilities, now),
        _lms_authoring_connection(state, context, now),
        _document_corpus_connection(document_context, now),
        _pointy_connection(host_context, host_capabilities, now),
        _web_search_connection(now),
        _weather_connection(now),
        _visual_runtime_connection(now),
        _code_studio_connection(now),
    )
    warnings = tuple(
        warning
        for connection in connections
        for warning in connection.warnings
    )
    runtime_status = {
        "query": {
            "active": bool(str(query or "").strip()),
            "reason": "present" if str(query or "").strip() else "missing_query",
        }
    }
    return WiiiConnectionSnapshot(
        version=WIII_CONNECT_SNAPSHOT_VERSION,
        generated_at=now,
        surface=surface or _surface_from_host(host_context),
        connections=connections,
        path_capabilities=_PATH_CAPABILITIES,
        warnings=warnings,
        runtime_status=runtime_status,
    )


def _server_connection(now: str) -> WiiiConnectionRecord:
    return WiiiConnectionRecord(
        slug="server",
        label="Wiii backend",
        status="connected",
        agent_ready=True,
        scopes=WiiiConnectionScopes(read=True),
        capabilities=("server.health",),
        source="runtime",
        reason="backend_runtime",
        last_checked_at=now,
    )


def _host_connection(
    host_context: dict[str, Any],
    host_capabilities: dict[str, Any],
    now: str,
) -> WiiiConnectionRecord:
    active = bool(host_context or host_capabilities)
    host_type = _safe_str(host_context.get("host_type") or host_capabilities.get("host_type"))
    capability_names = _capability_names(host_capabilities)
    return WiiiConnectionRecord(
        slug="host",
        label="Host context",
        status="connected" if active else "not_connected",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active),
        capabilities=capability_names,
        required_for_paths=("host_ui_action", "pointy_guidance"),
        source="host_context",
        reason="active" if active else "missing_host_context",
        last_checked_at=now,
        details={
            "host_type": host_type or None,
            "capability_count": len(capability_names),
        },
    )


def _host_actions_connection(
    host_capabilities: dict[str, Any],
    now: str,
) -> WiiiConnectionRecord:
    tools = host_capabilities.get("tools")
    tool_count = len(tools) if isinstance(tools, list) else 0
    active = tool_count > 0
    return WiiiConnectionRecord(
        slug="host_actions",
        label="Host actions",
        status="connected" if active else "not_connected",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active, preview=active, write=active),
        capabilities=("host.actions",) if active else (),
        required_for_paths=("host_ui_action",),
        source="host_capabilities",
        reason="active" if active else "missing_host_tools",
        last_checked_at=now,
        details={"tool_count": tool_count},
    )


def _lms_authoring_connection(
    state: dict[str, Any] | None,
    context: dict[str, Any],
    now: str,
) -> WiiiConnectionRecord:
    status = lms_authoring_connection_status(state, context)
    active = bool(status.get("active"))
    details = {
        key: value
        for key, value in status.items()
        if key != "active" and _is_safe_scalar_or_count(value)
    }
    return WiiiConnectionRecord(
        slug="lms_authoring",
        label="LMS authoring",
        status="connected" if active else "not_connected",
        agent_ready=active,
        scopes=WiiiConnectionScopes(
            read=active,
            preview=active,
            write=active,
            apply=active,
        ),
        capabilities=(
            "authoring.preview_lesson_patch",
            "authoring.generate_course_from_document",
            "authoring.apply_lesson_patch",
            "authoring.apply_course_plan",
        ) if active else (),
        required_for_paths=("lms_document_preview", "lms_document_apply"),
        source="lms_host_context",
        reason=_safe_str(status.get("reason")) or "missing_lms_host",
        last_checked_at=now,
        details=details,
    )


def _document_corpus_connection(
    document_context: dict[str, Any],
    now: str,
) -> WiiiConnectionRecord:
    attachments = document_context.get("attachments")
    documents = document_context.get("documents") or document_context.get("document_ids")
    source_refs = (
        document_context.get("source_refs")
        or document_context.get("sourceReferences")
        or document_context.get("source_references")
    )
    attachment_count = len(attachments) if isinstance(attachments, list) else 0
    document_count = len(documents) if isinstance(documents, list) else 0
    source_ref_count = len(source_refs) if isinstance(source_refs, list) else 0
    active = bool(document_context) and (attachment_count > 0 or document_count > 0)
    warnings = (
        ("document_context_without_source_refs",)
        if active and source_ref_count == 0
        else ()
    )
    return WiiiConnectionRecord(
        slug="document_corpus",
        label="Document corpus",
        status="connected" if active else "not_connected",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active),
        capabilities=("document.read", "document.cite") if active else (),
        required_for_paths=("document_grounded_answer", "lms_document_preview"),
        source="document_context",
        reason="active" if active else "missing_document_context",
        last_checked_at=now,
        warnings=warnings,
        details={
            "attachment_count": attachment_count,
            "document_count": document_count,
            "source_ref_count": source_ref_count,
        },
    )


def _pointy_connection(
    host_context: dict[str, Any],
    host_capabilities: dict[str, Any],
    now: str,
) -> WiiiConnectionRecord:
    targets = _pointy_targets(host_context)
    tools = host_capabilities.get("tools")
    tool_names: list[str] = []
    if isinstance(tools, list):
        tool_names = [
            _safe_str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and _safe_str(tool.get("name"))
        ]
    pointy_tool_count = len(
        [
            name for name in tool_names
            if name.startswith("pointy.") or name.startswith("tool_pointy_")
        ]
    )
    target_count = len(targets)
    active = target_count > 0 or pointy_tool_count > 0
    return WiiiConnectionRecord(
        slug="pointy",
        label="Pointy",
        status="connected" if active else "not_connected",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active, preview=active),
        capabilities=("pointy.highlight", "pointy.inventory") if active else (),
        required_for_paths=("pointy_guidance",),
        source="host_context",
        reason="active" if active else "missing_pointy_targets",
        last_checked_at=now,
        details={
            "target_count": target_count,
            "tool_count": pointy_tool_count,
        },
    )


def _web_search_connection(now: str) -> WiiiConnectionRecord:
    return WiiiConnectionRecord(
        slug="web_search",
        label="Web search",
        status="connected",
        agent_ready=True,
        scopes=WiiiConnectionScopes(read=True),
        capabilities=("web.search", "web.fetch"),
        required_for_paths=("web_search",),
        source="tool_registry",
        reason="native_available",
        last_checked_at=now,
    )


def _weather_connection(now: str) -> WiiiConnectionRecord:
    enabled = bool(getattr(settings, "living_agent_enable_weather", False))
    has_provider = bool(str(getattr(settings, "living_agent_weather_api_key", "") or "").strip())
    active = enabled and has_provider
    return WiiiConnectionRecord(
        slug="weather",
        label="Weather",
        status="connected" if active else "disabled",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active),
        capabilities=("weather.current",) if active else (),
        required_for_paths=("weather_lookup",),
        source="settings",
        reason="active" if active else "missing_weather_provider",
        last_checked_at=now,
        details={
            "fail_closed_tool": True,
            "default_city": _safe_str(getattr(settings, "living_agent_weather_city", "")) or None,
        },
    )


def _visual_runtime_connection(now: str) -> WiiiConnectionRecord:
    return WiiiConnectionRecord(
        slug="visual_runtime",
        label="Visual runtime",
        status="connected",
        agent_ready=True,
        scopes=WiiiConnectionScopes(read=True, preview=True, write=True),
        capabilities=("visual.inline", "visual.chart", "visual.mermaid"),
        required_for_paths=("visual_generation",),
        source="tool_registry",
        reason="native_available",
        last_checked_at=now,
    )


def _code_studio_connection(now: str) -> WiiiConnectionRecord:
    return WiiiConnectionRecord(
        slug="code_studio",
        label="Code Studio",
        status="connected",
        agent_ready=True,
        scopes=WiiiConnectionScopes(read=True, preview=True, write=True),
        capabilities=("code_studio.app", "code_studio.artifact"),
        required_for_paths=("code_studio_output",),
        source="tool_registry",
        reason="native_available",
        last_checked_at=now,
    )


def _context_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    context = state.get("context")
    return dict(context) if isinstance(context, dict) else {}


def _host_context(
    state: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(state, dict) and isinstance(state.get("host_context"), dict):
        return dict(state["host_context"])
    value = context.get("host_context")
    return dict(value) if isinstance(value, dict) else {}


def _host_capabilities(
    state: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(state, dict) and isinstance(state.get("host_capabilities"), dict):
        return dict(state["host_capabilities"])
    value = context.get("host_capabilities")
    return dict(value) if isinstance(value, dict) else {}


def _document_context(
    state: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(state, dict) and isinstance(state.get("document_context"), dict):
        return dict(state["document_context"])
    value = context.get("document_context")
    return dict(value) if isinstance(value, dict) else {}


def _surface_from_host(host_context: dict[str, Any]) -> str:
    return _safe_str(host_context.get("host_type")) or "unknown"


def _capability_names(host_capabilities: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for key in ("capabilities", "surfaces"):
        value = host_capabilities.get(key)
        if isinstance(value, list):
            names.extend(_safe_str(item) for item in value if _safe_str(item))
    tools = host_capabilities.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                name = _safe_str(tool.get("name"))
                if name:
                    names.append(name)
    return tuple(sorted(set(names)))


def _pointy_targets(host_context: dict[str, Any]) -> list[Any]:
    metadata = host_context.get("metadata")
    if not isinstance(metadata, dict):
        return []
    for key in ("pointyTargets", "pointy_targets", "targets"):
        value = metadata.get(key)
        if isinstance(value, list):
            return value
    pointy = metadata.get("pointy")
    if isinstance(pointy, dict) and isinstance(pointy.get("targets"), list):
        return pointy["targets"]
    return []


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _is_safe_scalar_or_count(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


_PATH_CAPABILITIES: tuple[WiiiPathCapabilityRecord, ...] = (
    WiiiPathCapabilityRecord(path="casual_chat"),
    WiiiPathCapabilityRecord(
        path="weather_lookup",
        required_connection_slugs=("weather",),
        allowed_tool_groups=("weather",),
    ),
    WiiiPathCapabilityRecord(
        path="web_search",
        required_connection_slugs=("web_search",),
        allowed_tool_groups=("web_search",),
    ),
    WiiiPathCapabilityRecord(
        path="document_grounded_answer",
        required_connection_slugs=("document_corpus",),
        allowed_tool_groups=("knowledge_search",),
    ),
    WiiiPathCapabilityRecord(
        path="lms_document_preview",
        required_connection_slugs=("lms_authoring",),
        allowed_tool_groups=("lms_authoring",),
        mutation_policy="preview_only",
    ),
    WiiiPathCapabilityRecord(
        path="lms_document_apply",
        required_connection_slugs=("lms_authoring",),
        allowed_tool_groups=("lms_authoring",),
        mutation_policy="approval_token_required",
    ),
    WiiiPathCapabilityRecord(
        path="host_ui_action",
        required_connection_slugs=("host_actions",),
        allowed_tool_groups=("host_action", "pointy"),
        mutation_policy="explicit_user_confirmation_required",
    ),
    WiiiPathCapabilityRecord(
        path="pointy_guidance",
        required_connection_slugs=("pointy",),
        allowed_tool_groups=("pointy",),
    ),
    WiiiPathCapabilityRecord(
        path="visual_generation",
        required_connection_slugs=("visual_runtime",),
        allowed_tool_groups=("visual",),
        forbidden_tool_groups=("pointy",),
        delegation_policy="delegate_to_path_agent",
    ),
    WiiiPathCapabilityRecord(
        path="code_studio_output",
        required_connection_slugs=("code_studio",),
        allowed_tool_groups=("code_studio_output", "visual"),
        forbidden_tool_groups=("pointy",),
        delegation_policy="delegate_to_path_agent",
    ),
    WiiiPathCapabilityRecord(
        path="external_app_action",
        allowed_tool_groups=("external_app",),
        delegation_policy="delegate_to_integration_agent",
    ),
)
