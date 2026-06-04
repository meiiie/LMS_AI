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
from app.engine.tools.tool_capability_registry import (
    WEATHER_TOOL_NAME,
    tool_capability_metadata_for_names,
)
from app.engine.wiii_connect.provider_registry import (
    list_wiii_connect_provider_registry,
)
from app.engine.wiii_connect.connection_lifecycle import (
    build_connection_lifecycle_decision,
)
from app.engine.wiii_connect.backend_action_executor import (
    authenticated_user_from_state,
    connection_storage_ready,
    owner_organization_id,
    storage_status_metadata,
)
from app.engine.wiii_connect.composio_adapter import (
    build_composio_adapter_config,
    build_composio_execution_enabled_entry,
    build_composio_provider_adapter_capability,
)
from app.engine.wiii_connect.persistent_storage import (
    get_wiii_connect_persistent_storage,
)


WIII_CONNECT_SNAPSHOT_VERSION = "wiii_connect_snapshot.v0"
WIII_CONNECT_DOCTOR_VERSION = "wiii_connect_doctor.v0"

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
    "delegate_to_integrations_agent",
]
PathDoctorStatus = Literal["ready", "guarded", "blocked"]
DoctorStatus = Literal["ready", "degraded", "blocked"]
ProviderDoctorStatus = Literal["ready", "guarded", "blocked"]
ProviderDoctorStageStatus = Literal["ready", "pending", "blocked"]


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
            "connection_lifecycle": _runtime_connection_lifecycle(self).to_public_metadata(),
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
            "connection_lifecycle": _runtime_connection_lifecycle(self).to_public_metadata(),
        }
        for key, value in self.details.items():
            if _is_safe_scalar_or_count(value):
                payload[key] = value
        return payload


def _runtime_connection_lifecycle(connection: WiiiConnectionRecord):
    connection_count = _safe_int_detail(connection, "connection_count")
    return build_connection_lifecycle_decision(
        provider_slug=connection.slug,
        status=connection.status,
        reason=connection.reason,
        connection_present=bool(
            connection.active
            or connection.status not in {"not_connected", "disabled"}
            or connection_count > 0
        ),
        active=connection.active,
        agent_ready=connection.agent_ready,
        ready_to_connect=bool(connection.details.get("adapter_authorization_ready")),
        ready_to_execute_action=connection.agent_ready,
    )


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
class WiiiPathDoctorRecord:
    """Read-only path readiness diagnosis derived from one snapshot."""

    path: str
    status: PathDoctorStatus
    reason: str
    required_connection_slugs: tuple[str, ...] = ()
    missing_connection_slugs: tuple[str, ...] = ()
    blocked_connection_reasons: tuple[str, ...] = ()
    mutation_policy: MutationPolicy = "none"
    delegation_policy: DelegationPolicy = "direct_only"
    agent_ready_connection_slugs: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "status": self.status,
            "reason": self.reason,
            "required_connection_slugs": list(self.required_connection_slugs),
            "missing_connection_slugs": list(self.missing_connection_slugs),
            "blocked_connection_reasons": list(self.blocked_connection_reasons),
            "mutation_policy": self.mutation_policy,
            "delegation_policy": self.delegation_policy,
            "agent_ready_connection_slugs": list(self.agent_ready_connection_slugs),
        }


@dataclass(frozen=True, slots=True)
class WiiiProviderDoctorStageRecord:
    """One provider-readiness stage, modeled after OpenHuman Connections."""

    key: str
    status: ProviderDoctorStageStatus
    reason: str
    required_next: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status,
            "reason": self.reason,
            "required_next": list(self.required_next),
        }


@dataclass(frozen=True, slots=True)
class WiiiProviderDoctorRecord:
    """Read-only provider readiness diagnosis derived from one snapshot."""

    provider_slug: str
    label: str
    provider_kind: ProviderKind
    status: ProviderDoctorStatus
    reason: str
    connection_status: ConnectionStatus
    active: bool = False
    agent_ready: bool = False
    connection_count: int = 0
    active_connection_count: int = 0
    action_count: int = 0
    scope_count: int = 0
    required_next: tuple[str, ...] = ()
    stages: tuple[WiiiProviderDoctorStageRecord, ...] = ()
    connection_lifecycle: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "status": self.status,
            "reason": self.reason,
            "connection_status": self.connection_status,
            "active": self.active,
            "agent_ready": self.agent_ready,
            "connection_count": self.connection_count,
            "active_connection_count": self.active_connection_count,
            "action_count": self.action_count,
            "scope_count": self.scope_count,
            "required_next": list(self.required_next),
            "stages": [stage.to_metadata() for stage in self.stages],
            "connection_lifecycle": dict(self.connection_lifecycle),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectDoctorReport:
    """Privacy-safe runtime doctor summary for Wiii Connect."""

    version: str
    generated_at: str
    surface: str
    status: DoctorStatus
    summary: dict[str, int]
    path_diagnostics: tuple[WiiiPathDoctorRecord, ...]
    provider_diagnostics: tuple[WiiiProviderDoctorRecord, ...] = ()
    top_blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generated_at": self.generated_at,
            "surface": self.surface,
            "status": self.status,
            "summary": dict(self.summary),
            "path_diagnostics": [
                diagnostic.to_metadata() for diagnostic in self.path_diagnostics
            ],
            "provider_diagnostics": [
                diagnostic.to_metadata() for diagnostic in self.provider_diagnostics
            ],
            "top_blockers": list(self.top_blockers),
            "warnings": list(self.warnings),
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
            "capability_summary": self.capability_summary(),
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

    def agent_ready_external_provider_slugs(self) -> tuple[str, ...]:
        """Return connected external providers safe for model-visible actions."""

        return tuple(
            connection.slug
                for connection in self.connections
            if connection.provider_kind != "wiii_native"
            and connection.status == "connected"
            and connection.agent_ready
        )

    def capability_summary(self) -> dict[str, Any]:
        """Return compact, privacy-safe connection and path readiness facts."""

        provider_connections = tuple(
            connection
            for connection in self.connections
            if connection.provider_kind != "wiii_native"
        )
        active_connections = tuple(
            connection for connection in self.connections if connection.active
        )
        agent_ready_connections = tuple(
            connection for connection in self.connections if connection.agent_ready
        )
        connected_providers = tuple(
            connection for connection in provider_connections if connection.active
        )
        agent_ready_providers = tuple(
            connection
            for connection in provider_connections
            if connection.status == "connected" and connection.agent_ready
        )
        connected_scope_names = tuple(
            sorted(
                {
                    scope_name
                    for connection in connected_providers
                    for scope_name, enabled in connection.scopes.to_metadata().items()
                    if enabled
                }
            )
        )
        suppressed_tool_groups = tuple(
            sorted(
                {
                    group
                    for path in self.path_capabilities
                    for group in path.forbidden_tool_groups
                    if group
                }
            )
        )
        connection_by_slug = {connection.slug: connection for connection in self.connections}
        external_ready = tuple(connection.slug for connection in agent_ready_providers)
        path_readiness = [
            _path_capability_summary(
                path,
                _path_doctor_record(
                    path,
                    connection_by_slug=connection_by_slug,
                    external_ready=external_ready,
                ),
            )
            for path in self.path_capabilities
        ]
        return {
            "active_connection_slugs": [
                connection.slug for connection in active_connections
            ],
            "agent_ready_connection_slugs": [
                connection.slug for connection in agent_ready_connections
            ],
            "connected_provider_slugs": [
                connection.slug for connection in connected_providers
            ],
            "agent_ready_provider_slugs": [
                connection.slug for connection in agent_ready_providers
            ],
            "connected_scope_names": list(connected_scope_names),
            "suppressed_tool_groups": list(suppressed_tool_groups),
            "path_readiness": path_readiness,
        }

    def provider_status(self, slug: str) -> dict[str, Any]:
        """Return one provider status payload without exposing provider secrets."""

        normalized = _safe_str(slug).lower().replace("-", "_")
        if not normalized:
            return {}
        for connection in self.connections:
            if connection.slug == normalized:
                return connection.to_connection_status()
        return {}

    def doctor_report(self) -> WiiiConnectDoctorReport:
        """Return an OpenClaw-style operator diagnosis for this snapshot."""

        return build_wiii_connect_doctor_report(self)


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
        *_external_provider_connections(state, context, now),
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


def build_wiii_connect_doctor_report(
    snapshot: WiiiConnectionSnapshot,
) -> WiiiConnectDoctorReport:
    """Build a read-only path/connection readiness summary from a snapshot."""

    connection_by_slug = {connection.slug: connection for connection in snapshot.connections}
    provider_diagnostics = _provider_doctor_diagnostics(snapshot)
    external_ready = tuple(
        connection.slug
        for connection in snapshot.connections
        if connection.provider_kind != "wiii_native"
        and connection.status == "connected"
        and connection.agent_ready
    )
    diagnostics = tuple(
        _path_doctor_record(
            path,
            connection_by_slug=connection_by_slug,
            external_ready=external_ready,
        )
        for path in snapshot.path_capabilities
    )
    ready_count = sum(1 for item in diagnostics if item.status == "ready")
    guarded_count = sum(1 for item in diagnostics if item.status == "guarded")
    blocked_count = sum(1 for item in diagnostics if item.status == "blocked")
    server_ready = bool(connection_by_slug.get("server") and connection_by_slug["server"].agent_ready)
    status: DoctorStatus = (
        "blocked"
        if not server_ready
        else "degraded"
        if blocked_count > 0 or snapshot.warnings
        else "ready"
    )
    top_blockers = _doctor_top_blockers(diagnostics, snapshot.warnings)
    summary = {
        "total_paths": len(diagnostics),
        "ready_paths": ready_count,
        "guarded_paths": guarded_count,
        "blocked_paths": blocked_count,
        "total_connections": len(snapshot.connections),
        "agent_ready_connections": sum(
            1 for connection in snapshot.connections if connection.agent_ready
        ),
        "external_provider_connections": sum(
            1 for connection in snapshot.connections if connection.provider_kind != "wiii_native"
        ),
        "external_agent_ready_connections": len(external_ready),
        "warning_count": len(snapshot.warnings),
    }
    return WiiiConnectDoctorReport(
        version=WIII_CONNECT_DOCTOR_VERSION,
        generated_at=snapshot.generated_at,
        surface=snapshot.surface,
        status=status,
        summary=summary,
        path_diagnostics=diagnostics,
        provider_diagnostics=provider_diagnostics,
        top_blockers=top_blockers,
        warnings=tuple(dict.fromkeys(snapshot.warnings)),
    )


def _path_capability_summary(
    path: WiiiPathCapabilityRecord,
    diagnosis: WiiiPathDoctorRecord,
) -> dict[str, Any]:
    return {
        "path": diagnosis.path,
        "status": diagnosis.status,
        "reason": diagnosis.reason,
        "required_connection_slugs": list(diagnosis.required_connection_slugs),
        "missing_connection_slugs": list(diagnosis.missing_connection_slugs),
        "agent_ready_connection_slugs": list(diagnosis.agent_ready_connection_slugs),
        "allowed_tool_groups": list(path.allowed_tool_groups),
        "suppressed_tool_groups": list(path.forbidden_tool_groups),
        "mutation_policy": diagnosis.mutation_policy,
        "delegation_policy": diagnosis.delegation_policy,
    }


def _provider_doctor_diagnostics(
    snapshot: WiiiConnectionSnapshot,
) -> tuple[WiiiProviderDoctorRecord, ...]:
    diagnostics: list[WiiiProviderDoctorRecord] = []
    for connection in snapshot.connections:
        if connection.provider_kind == "wiii_native":
            continue
        diagnostics.append(_provider_doctor_record(connection))
    return tuple(
        sorted(diagnostics, key=lambda item: (item.provider_kind, item.provider_slug))
    )


def _provider_doctor_record(
    connection: WiiiConnectionRecord,
) -> WiiiProviderDoctorRecord:
    reason = connection.reason or connection.status
    if connection.agent_ready:
        status: ProviderDoctorStatus = "guarded"
        reason = "agent_ready_gateway_required"
    elif connection.active:
        status = "guarded"
    else:
        status = "blocked"
    return WiiiProviderDoctorRecord(
        provider_slug=connection.slug,
        label=connection.label,
        provider_kind=connection.provider_kind,
        status=status,
        reason=reason,
        connection_status=connection.status,
        active=connection.active,
        agent_ready=connection.agent_ready,
        connection_count=_safe_int_detail(connection, "connection_count"),
        active_connection_count=_safe_int_detail(connection, "active_connection_count"),
        action_count=_safe_int_detail(connection, "action_count"),
        scope_count=_safe_int_detail(connection, "scope_count"),
        required_next=_required_next_for_provider_reason(reason),
        stages=_provider_doctor_stages(connection),
        connection_lifecycle=_runtime_connection_lifecycle(
            connection,
        ).to_public_metadata(),
    )


def _provider_doctor_stages(
    connection: WiiiConnectionRecord,
) -> tuple[WiiiProviderDoctorStageRecord, ...]:
    registry_ready = True
    adapter_ready = bool(connection.details.get("adapter_authorization_ready"))
    adapter_reason = _safe_str(connection.details.get("adapter_reason")) or (
        "ready" if adapter_ready else "provider_adapter_not_bound"
    )
    account_ready = connection.active or _safe_int_detail(connection, "active_connection_count") > 0
    account_pending = connection.status == "pending"
    agent_policy_ready = connection.agent_ready
    return (
        WiiiProviderDoctorStageRecord(
            key="registry",
            status="ready",
            reason="registered",
        ),
        WiiiProviderDoctorStageRecord(
            key="adapter",
            status="ready" if adapter_ready else "blocked",
            reason=adapter_reason,
            required_next=()
            if adapter_ready
            else _required_next_for_provider_reason(adapter_reason),
        ),
        WiiiProviderDoctorStageRecord(
            key="account",
            status="ready" if account_ready else ("pending" if account_pending else "blocked"),
            reason="connected" if account_ready else connection.reason or connection.status,
            required_next=()
            if account_ready
            else _required_next_for_provider_reason(connection.reason or connection.status),
        ),
        WiiiProviderDoctorStageRecord(
            key="agent_policy",
            status="ready" if agent_policy_ready else ("pending" if not account_ready else "blocked"),
            reason=(
                "agent_ready"
                if agent_policy_ready
                else ("account_required" if not account_ready else connection.reason or "not_agent_ready")
            ),
            required_next=()
            if agent_policy_ready
            else _required_next_for_provider_reason(
                "provider_not_connected" if not account_ready else connection.reason
            ),
        ),
        WiiiProviderDoctorStageRecord(
            key="gateway",
            status="pending" if agent_policy_ready else "blocked",
            reason="per_action_gateway_required"
            if agent_policy_ready
            else "agent_policy_not_ready",
            required_next=("select_action_and_evaluate_gateway",)
            if agent_policy_ready
            else _required_next_for_provider_reason(connection.reason),
        ),
    )


def _required_next_for_provider_reason(reason: str) -> tuple[str, ...]:
    normalized = _safe_str(reason)
    mapping: dict[str, tuple[str, ...]] = {
        "agent_ready_gateway_required": ("select_action_and_evaluate_gateway",),
        "per_action_gateway_required": ("select_action_and_evaluate_gateway",),
        "provider_adapter_disabled": ("configure_composio_adapter",),
        "provider_adapter_not_bound": ("bind_provider_adapter",),
        "provider_adapter_not_configured": ("configure_provider_adapter",),
        "provider_adapter_cannot_execute": ("implement_provider_action_adapter",),
        "provider_disabled": ("enable_provider_registry_entry",),
        "connection_storage_unavailable": ("configure_wiii_connect_storage",),
        "provider_not_connected": ("complete_provider_oauth",),
        "not_connected": ("complete_provider_oauth",),
        "pending": ("complete_provider_oauth",),
        "expired": ("reconnect_provider_account",),
        "error": ("inspect_provider_connection_error",),
        "connected_provider_not_agent_ready": (
            "enable_provider_agent_policy",
            "enable_curated_action_catalog",
        ),
        "connected_missing_scope_grant": ("grant_required_scope_policy",),
        "connected_not_agent_ready": ("inspect_provider_readiness",),
        "provider_not_agent_ready": (
            "enable_provider_agent_policy",
            "enable_curated_action_catalog",
        ),
        "account_required": ("connect_provider_account",),
        "agent_policy_not_ready": ("enable_provider_agent_policy",),
    }
    return mapping.get(normalized, ("inspect_provider_readiness",))


def _safe_int_detail(connection: WiiiConnectionRecord, key: str) -> int:
    value = connection.details.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def _path_doctor_record(
    path: WiiiPathCapabilityRecord,
    *,
    connection_by_slug: dict[str, WiiiConnectionRecord],
    external_ready: tuple[str, ...],
) -> WiiiPathDoctorRecord:
    if path.path == "external_app_action":
        if not external_ready:
            return WiiiPathDoctorRecord(
                path=path.path,
                status="blocked",
                reason="no_agent_ready_external_provider",
                mutation_policy=path.mutation_policy,
                delegation_policy=path.delegation_policy,
            )
        return WiiiPathDoctorRecord(
            path=path.path,
            status="guarded",
            reason="provider_worker_gateway_required",
            mutation_policy=path.mutation_policy,
            delegation_policy=path.delegation_policy,
            agent_ready_connection_slugs=external_ready,
        )

    missing: list[str] = []
    blocked_reasons: list[str] = []
    ready_required: list[str] = []
    for slug in path.required_connection_slugs:
        connection = connection_by_slug.get(slug)
        if connection is None:
            missing.append(slug)
            blocked_reasons.append(f"{slug}:missing_connection")
            continue
        if not connection.agent_ready:
            missing.append(slug)
            reason = connection.reason or connection.status or "not_agent_ready"
            blocked_reasons.append(f"{slug}:{reason}")
            continue
        ready_required.append(slug)

    if missing:
        return WiiiPathDoctorRecord(
            path=path.path,
            status="blocked",
            reason="missing_required_connection",
            required_connection_slugs=path.required_connection_slugs,
            missing_connection_slugs=tuple(missing),
            blocked_connection_reasons=tuple(blocked_reasons),
            mutation_policy=path.mutation_policy,
            delegation_policy=path.delegation_policy,
            agent_ready_connection_slugs=tuple(ready_required),
        )

    guarded = path.mutation_policy in {
        "preview_only",
        "approval_token_required",
        "explicit_user_confirmation_required",
    }
    return WiiiPathDoctorRecord(
        path=path.path,
        status="guarded" if guarded else "ready",
        reason=(
            "runtime_approval_gate_required"
            if guarded
            else "ready"
        ),
        required_connection_slugs=path.required_connection_slugs,
        mutation_policy=path.mutation_policy,
        delegation_policy=path.delegation_policy,
        agent_ready_connection_slugs=tuple(ready_required),
    )


def _doctor_top_blockers(
    diagnostics: tuple[WiiiPathDoctorRecord, ...],
    warnings: tuple[str, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    for item in diagnostics:
        if item.status != "blocked":
            continue
        if item.missing_connection_slugs:
            missing = ",".join(item.missing_connection_slugs)
            blockers.append(f"path:{item.path}:missing:{missing}")
        else:
            blockers.append(f"path:{item.path}:{item.reason}")
        if len(blockers) >= 8:
            break
    for warning in warnings:
        token = _safe_str(warning)
        if token and f"warning:{token}" not in blockers:
            blockers.append(f"warning:{token}")
        if len(blockers) >= 12:
            break
    return tuple(blockers)


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
    provider_configured = enabled and has_provider
    runtime_tool_available = _weather_tool_runtime_available()
    active = provider_configured or runtime_tool_available
    reason = (
        "active"
        if provider_configured
        else "tool_runtime_available"
        if runtime_tool_available
        else "missing_weather_provider"
    )
    return WiiiConnectionRecord(
        slug="weather",
        label="Weather",
        status="connected" if active else "disabled",
        agent_ready=active,
        scopes=WiiiConnectionScopes(read=active),
        capabilities=("weather.current",) if active else (),
        required_for_paths=("weather_lookup",),
        source="settings" if provider_configured else "tool_capability_registry",
        reason=reason,
        last_checked_at=now,
        details={
            "provider_configured": provider_configured,
            "tool_runtime_available": runtime_tool_available,
            "default_city": _safe_str(getattr(settings, "living_agent_weather_city", "")) or None,
        },
    )


def _weather_tool_runtime_available() -> bool:
    metadata = tool_capability_metadata_for_names((WEATHER_TOOL_NAME,)).get(
        WEATHER_TOOL_NAME,
        {},
    )
    return bool(
        metadata.get("group") == "weather"
        and metadata.get("required_connection") == "weather"
        and metadata.get("expose_when_connection_inactive") is True
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


def _external_provider_connections(
    state: dict[str, Any] | None,
    context: dict[str, Any],
    now: str,
) -> tuple[WiiiConnectionRecord, ...]:
    records: list[WiiiConnectionRecord] = []
    runtime_state = dict(state or {})
    if "context" not in runtime_state:
        runtime_state["context"] = context
    current_user = authenticated_user_from_state(runtime_state)
    composio_config = build_composio_adapter_config()
    composio_adapter_capability = build_composio_provider_adapter_capability(
        composio_config
    )
    storage = storage_status_metadata()
    storage_ready = connection_storage_ready(storage)
    storage_warning = () if storage_ready else ("connection_storage_unavailable",)

    for raw_entry in list_wiii_connect_provider_registry():
        entry = build_composio_execution_enabled_entry(raw_entry, composio_config)
        adapter_reason = (
            composio_adapter_capability.reason
            if entry.provider_kind == "composio"
            else "provider_adapter_not_bound"
        )
        adapter_warnings = (
            composio_adapter_capability.warnings
            if entry.provider_kind == "composio"
            else ()
        )
        connection_records = _provider_connection_records(
            entry.slug,
            storage_ready=storage_ready,
            organization_id=owner_organization_id(current_user),
            user_id=current_user.user_id,
        )
        active_records = tuple(record for record in connection_records if record.active)
        selected_record = active_records[0] if active_records else (
            connection_records[0] if connection_records else None
        )
        status = _provider_status(storage_ready, selected_record)
        scopes = (
            _scopes_from_connection(selected_record)
            if selected_record is not None
            else WiiiConnectionScopes()
        )
        scope_count = (
            len(selected_record.scopes.enabled_scopes())
            if selected_record is not None
            else 0
        )
        has_required_scope = scope_count > 0 or bool(entry.default_scopes.enabled_scopes())
        agent_ready = bool(
            entry.enabled
            and entry.agent_ready
            and selected_record is not None
            and selected_record.active
            and has_required_scope
        )
        records.append(
            WiiiConnectionRecord(
                slug=entry.slug,
                label=entry.label,
                provider_kind=entry.provider_kind,
                status=status,
                agent_ready=agent_ready,
                scopes=scopes,
                capabilities=_provider_capabilities(entry.slug, selected_record, agent_ready),
                required_for_paths=tuple(entry.allowed_paths),
                source=(
                    "wiii_connect_persistent_storage"
                    if selected_record is not None
                    else "wiii_connect_provider_registry"
                ),
                reason=_provider_reason(
                    entry_enabled=entry.enabled,
                    entry_agent_ready=entry.agent_ready,
                    adapter_reason=adapter_reason,
                    storage_ready=storage_ready,
                    record=selected_record,
                    agent_ready=agent_ready,
                    has_required_scope=has_required_scope,
                ),
                last_checked_at=now,
                warnings=_merge_warnings(
                    tuple(entry.warnings),
                    adapter_warnings,
                    _provider_record_warnings(selected_record),
                    storage_warning,
                ),
                details={
                    "auth_mode": entry.auth_mode,
                    "category": entry.category,
                    "action_count": len(entry.action_allowlist),
                    "requirement_count": len(entry.all_requirements()),
                    "adapter_bound": composio_adapter_capability.bound
                    if entry.provider_kind == "composio"
                    else False,
                    "adapter_configured": composio_adapter_capability.configured
                    if entry.provider_kind == "composio"
                    else False,
                    "adapter_authorization_ready": (
                        composio_adapter_capability.authorization_ready
                        if entry.provider_kind == "composio"
                        else False
                    ),
                    "adapter_can_execute_actions": (
                        composio_adapter_capability.can_execute_actions
                        if entry.provider_kind == "composio"
                        else False
                    ),
                    "adapter_reason": adapter_reason,
                    "connection_count": len(connection_records),
                    "active_connection_count": len(active_records),
                    "connection_ref_present": bool(
                        selected_record.connection_ref if selected_record else ""
                    ),
                    "connection_state": selected_record.state if selected_record else None,
                    "scope_count": scope_count,
                    "vault_ref_present": (
                        selected_record.vault_ref is not None
                        if selected_record is not None
                        else False
                    ),
                    "account_label_present": bool(
                        selected_record.account_label if selected_record else ""
                    ),
                },
            )
        )
    return tuple(records)


def _provider_connection_records(
    provider_slug: str,
    *,
    storage_ready: bool,
    organization_id: str,
    user_id: str,
) -> tuple[Any, ...]:
    if not storage_ready:
        return ()
    try:
        return get_wiii_connect_persistent_storage().list_connection_records(
            organization_id=organization_id,
            user_id=user_id,
            provider_slug=provider_slug,
        )
    except Exception:
        return ()


def _provider_status(
    storage_ready: bool,
    record: Any | None,
) -> ConnectionStatus:
    if not storage_ready:
        return "not_connected"
    if record is None:
        return "not_connected"
    if getattr(record, "active", False):
        return "connected"
    state = _safe_str(getattr(record, "state", ""))
    if state in {"authorizing", "waiting"}:
        return "pending"
    if state in {"expired", "error", "disabled"}:
        return state  # type: ignore[return-value]
    return "not_connected"


def _provider_reason(
    *,
    entry_enabled: bool,
    entry_agent_ready: bool,
    adapter_reason: str,
    storage_ready: bool,
    record: Any | None,
    agent_ready: bool,
    has_required_scope: bool,
) -> str:
    if not storage_ready:
        return "connection_storage_unavailable"
    if record is None:
        if not entry_enabled:
            return _safe_str(adapter_reason) or "provider_disabled"
        return "provider_not_connected"
    if not getattr(record, "active", False):
        return _safe_str(getattr(record, "reason", "")) or f"connection_{getattr(record, 'state', 'inactive')}"
    if not entry_enabled:
        return _safe_str(adapter_reason) or "provider_disabled"
    if not entry_agent_ready:
        return "connected_provider_not_agent_ready"
    if not has_required_scope:
        return "connected_missing_scope_grant"
    if agent_ready:
        return "connected"
    return "connected_not_agent_ready"


def _scopes_from_connection(record: Any) -> WiiiConnectionScopes:
    scopes = getattr(record, "scopes", None)
    return WiiiConnectionScopes(
        read=bool(getattr(scopes, "read", False)),
        preview=bool(getattr(scopes, "preview", False)),
        write=bool(getattr(scopes, "write", False)),
        apply=bool(getattr(scopes, "apply", False)),
        admin=bool(getattr(scopes, "admin", False)),
    )


def _provider_capabilities(
    provider_slug: str,
    record: Any | None,
    agent_ready: bool,
) -> tuple[str, ...]:
    if record is None:
        return ()
    base = (f"wiii_connect.{provider_slug}.connected",)
    if agent_ready:
        return base + (f"wiii_connect.{provider_slug}.agent_ready",)
    return base


def _provider_record_warnings(record: Any | None) -> tuple[str, ...]:
    if record is None:
        return ()
    warnings = getattr(record, "warnings", ()) or ()
    if not isinstance(warnings, tuple):
        warnings = tuple(warnings)
    return tuple(_safe_str(warning) for warning in warnings if _safe_str(warning))


def _merge_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    for group in groups:
        for warning in group:
            normalized = _safe_str(warning)
            if normalized and normalized not in warnings:
                warnings.append(normalized)
    return tuple(warnings)


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
        delegation_policy="delegate_to_integrations_agent",
    ),
)
