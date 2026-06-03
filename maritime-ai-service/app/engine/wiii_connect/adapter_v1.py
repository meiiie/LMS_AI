"""Wiii Connect Adapter V1 policy contract.

This module defines the backend-side contract Wiii must enforce before any
external connector such as Composio can execute on behalf of a user. It is
intentionally provider-neutral and performs no network calls.

The execution gateway is fail-closed: connected account state is not enough.
The provider must be enabled, agent-ready, path-allowed, action-curated, scoped,
and carrying the required approval evidence before execution can proceed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text

from .argument_key_policy import safe_public_argument_key
from .connection_lifecycle import build_connection_lifecycle_decision


WIII_CONNECT_ADAPTER_VERSION = "wiii_connect_adapter.v1"
WIII_CONNECT_PUBLIC_CONNECTION_REF_PREFIX = "wcn_"

ProviderKind = Literal[
    "wiii_native",
    "composio",
    "mcp",
    "custom_oauth",
    "workflow",
]
AuthMode = Literal["none", "oauth2", "api_key", "mcp", "delegated"]
ConnectionLifecycleState = Literal[
    "disconnected",
    "authorizing",
    "waiting",
    "connected",
    "expired",
    "error",
    "disabled",
]
ScopeName = Literal["read", "preview", "write", "apply", "admin"]
ActionMutation = Literal["read", "preview", "write", "apply", "admin"]
DecisionOutcome = Literal["allowed", "denied"]
ExecutionDenyReason = Literal[
    "allowed",
    "provider_disabled",
    "provider_not_agent_ready",
    "provider_adapter_mismatch",
    "provider_adapter_not_bound",
    "provider_adapter_not_configured",
    "provider_adapter_cannot_execute",
    "audit_ledger_not_persistent",
    "connection_selection_required",
    "connection_missing",
    "connection_provider_mismatch",
    "connection_not_connected",
    "path_not_allowed",
    "action_not_allowed",
    "missing_scope",
    "scope_policy_denied",
    "missing_preview_evidence",
    "missing_approval_token",
]
AuditEventStage = Literal["requested", "denied", "started", "succeeded", "failed"]


@dataclass(frozen=True, slots=True)
class WiiiConnectScopeGrant:
    """User-approved scope gates for a connected provider account."""

    read: bool = False
    preview: bool = False
    write: bool = False
    apply: bool = False
    admin: bool = False

    def allows(self, scope: ScopeName) -> bool:
        return bool(getattr(self, scope))

    def enabled_scopes(self) -> tuple[ScopeName, ...]:
        scopes: list[ScopeName] = []
        for scope in ("read", "preview", "write", "apply", "admin"):
            if self.allows(scope):
                scopes.append(scope)
        return tuple(scopes)

    def to_metadata(self) -> dict[str, bool]:
        return {
            "read": self.read,
            "preview": self.preview,
            "write": self.write,
            "apply": self.apply,
            "admin": self.admin,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectRequiredField:
    """One provider-specific input required before starting authorization."""

    key: str
    label: str
    required: bool = True
    secret: bool = False
    help_text: str = ""

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "required": self.required,
            "secret": self.secret,
            "help_text": self.help_text,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectProviderRegistryEntry:
    """Static provider registration exposed to UI and runtime policy."""

    slug: str
    label: str
    provider_kind: ProviderKind
    auth_mode: AuthMode
    enabled: bool = False
    agent_ready: bool = False
    category: str = "integration"
    description: str = ""
    allowed_paths: tuple[str, ...] = ("external_app_action",)
    action_allowlist: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    connect_requirements: tuple[str, ...] = ()
    agent_ready_requirements: tuple[str, ...] = ()
    required_fields: tuple[WiiiConnectRequiredField, ...] = ()
    default_scopes: WiiiConnectScopeGrant = field(default_factory=WiiiConnectScopeGrant)
    source: str = "wiii_connect_registry"
    warnings: tuple[str, ...] = ()

    def connection_requirements(self) -> tuple[str, ...]:
        """Return prerequisites that block starting OAuth/Connect Link."""

        if self.connect_requirements:
            return self.connect_requirements
        if self.agent_ready_requirements:
            return ()
        return self.requirements

    def all_requirements(self) -> tuple[str, ...]:
        """Return stable public requirements without duplicating entries."""

        result: list[str] = []
        for requirement in (
            self.requirements
            or self.connect_requirements + self.agent_ready_requirements
        ):
            if requirement and requirement not in result:
                result.append(requirement)
        return tuple(result)

    def allows_action(self, action_slug: str) -> bool:
        """Return true when an action is in the curated allowlist.

        Patterns ending in ``*`` are treated as conservative prefix grants. An
        empty allowlist allows nothing.
        """

        action = action_slug.strip().upper()
        if not action:
            return False
        for pattern in self.action_allowlist:
            normalized = pattern.strip().upper()
            if not normalized:
                continue
            if normalized.endswith("*"):
                prefix = normalized[:-1]
                if prefix and action.startswith(prefix):
                    return True
                continue
            if action == normalized:
                return True
        return False

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ADAPTER_VERSION,
            "slug": self.slug,
            "label": self.label,
            "provider_kind": self.provider_kind,
            "auth_mode": self.auth_mode,
            "enabled": self.enabled,
            "agent_ready": self.agent_ready,
            "category": self.category,
            "description": self.description,
            "allowed_paths": list(self.allowed_paths),
            "action_count": len(self.action_allowlist),
            "requirements": list(self.all_requirements()),
            "connect_requirements": list(self.connection_requirements()),
            "agent_ready_requirements": list(self.agent_ready_requirements),
            "required_fields": [
                field.to_public_metadata() for field in self.required_fields
            ],
            "default_scopes": self.default_scopes.to_metadata(),
            "source": self.source,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectVaultSecretRef:
    """Opaque reference to credentials held outside chat/runtime metadata."""

    provider_slug: str
    connection_id: str
    vault_key_id: str
    secret_version: str = ""

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "provider_slug": self.provider_slug,
            "connection_ref_present": bool(self.connection_id),
            "vault_ref_present": bool(self.vault_key_id),
            "secret_version": self.secret_version,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectConnectionRecordV1:
    """One resolved connection row after OAuth/session reconciliation."""

    connection_id: str
    provider_slug: str
    state: ConnectionLifecycleState = "disconnected"
    scopes: WiiiConnectScopeGrant = field(default_factory=WiiiConnectScopeGrant)
    vault_ref: WiiiConnectVaultSecretRef | None = None
    account_label: str = ""
    external_account_ref: str = ""
    last_checked_at: str | None = None
    reason: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return self.state == "connected"

    @property
    def connection_ref(self) -> str:
        return public_connection_ref(self.provider_slug, self.connection_id)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ADAPTER_VERSION,
            "connection_ref": self.connection_ref,
            "connection_ref_present": bool(self.connection_ref),
            "provider_slug": self.provider_slug,
            "state": self.state,
            "active": self.active,
            "scopes": self.scopes.to_metadata(),
            "vault_ref_present": self.vault_ref is not None,
            "account_label": self.account_label,
            "external_account_ref_present": bool(self.external_account_ref),
            "last_checked_at": self.last_checked_at,
            "reason": self.reason,
            "warnings": list(self.warnings),
            "connection_lifecycle": build_connection_lifecycle_decision(
                provider_slug=self.provider_slug,
                connection=self,
            ).to_public_metadata(),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectExecutionRequest:
    """Runtime request entering the Wiii Connect execution gateway."""

    provider_slug: str
    action_slug: str
    path: str
    mutation: ActionMutation = "read"
    approval_token_present: bool = False
    preview_evidence_id: str | None = None
    preview_evidence_required: bool = False
    argument_keys: tuple[str, ...] = ()
    request_id: str = ""

    def to_audit_metadata(self) -> dict[str, Any]:
        metadata = {
            "provider_slug": self.provider_slug,
            "action_slug": self.action_slug,
            "path": self.path,
            "mutation": self.mutation,
            "approval_token_present": self.approval_token_present,
            "preview_evidence_present": bool(self.preview_evidence_id),
            "argument_keys": [_safe_audit_key(key) for key in self.argument_keys],
        }
        request_id = _safe_request_id(self.request_id)
        if request_id:
            metadata["request_id"] = request_id
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectExecutionDecision:
    """Fail-closed decision returned before a provider action can run."""

    outcome: DecisionOutcome
    reason: ExecutionDenyReason
    provider_slug: str
    action_slug: str
    path: str
    required_scopes: tuple[ScopeName, ...] = ()
    audit_tags: tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.outcome == "allowed"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ADAPTER_VERSION,
            "outcome": self.outcome,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "action_slug": self.action_slug,
            "path": self.path,
            "required_scopes": list(self.required_scopes),
            "audit_tags": list(self.audit_tags),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectAuditEvent:
    """Privacy-safe ledger event around a provider execution attempt."""

    stage: AuditEventStage
    request: WiiiConnectExecutionRequest
    decision: WiiiConnectExecutionDecision
    connection_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ADAPTER_VERSION,
            "stage": self.stage,
            "created_at": self.created_at,
            "connection_ref_present": bool(self.connection_id),
            "request": self.request.to_audit_metadata(),
            "decision": self.decision.to_metadata(),
        }


def normalize_connection_state(status: str | None) -> ConnectionLifecycleState:
    """Normalize provider-specific connection statuses into Wiii states."""

    normalized = str(status or "").strip().upper()
    if normalized in {"ACTIVE", "CONNECTED"}:
        return "connected"
    if normalized in {"AUTHORIZING"}:
        return "authorizing"
    if normalized in {"PENDING", "INITIATED", "INITIALIZING"}:
        return "waiting"
    if normalized == "EXPIRED":
        return "expired"
    if normalized in {"FAILED", "ERROR"}:
        return "error"
    if normalized == "DISABLED":
        return "disabled"
    return "disconnected"


def public_connection_ref(provider_slug: str, connection_id: str) -> str:
    """Return an opaque stable reference for UI/backend connection selection."""

    provider = str(provider_slug or "").strip().lower().replace("-", "_")
    raw_id = str(connection_id or "").strip()
    if not provider or not raw_id:
        return ""
    digest = hashlib.sha256(f"{provider}:{raw_id}".encode("utf-8")).hexdigest()
    return f"{WIII_CONNECT_PUBLIC_CONNECTION_REF_PREFIX}{digest[:24]}"


def connection_ref_matches(
    *,
    provider_slug: str,
    connection_id: str,
    candidate: str,
) -> bool:
    """Return true when a public ref belongs to one provider connection id."""

    normalized_candidate = str(candidate or "").strip()
    if not normalized_candidate:
        return False
    return normalized_candidate == public_connection_ref(provider_slug, connection_id)


def is_connection_baseline_ready(
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
) -> bool:
    """Return true when registry and live connection pass baseline readiness.

    This is not a final execution decision. Call ``decide_external_execution``
    with the active path/action request before exposing a provider action to an
    agent.
    """

    return bool(
        entry.enabled
        and entry.agent_ready
        and connection is not None
        and connection.provider_slug == entry.slug
        and connection.active
    )


def decide_external_execution(
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    request: WiiiConnectExecutionRequest,
) -> WiiiConnectExecutionDecision:
    """Decide whether Wiii may execute one external provider action."""

    if not entry.enabled:
        return _deny(entry, request, "provider_disabled")
    if not entry.agent_ready:
        return _deny(entry, request, "provider_not_agent_ready")
    if connection is None:
        return _deny(entry, request, "connection_missing")
    if connection.provider_slug != entry.slug or request.provider_slug != entry.slug:
        return _deny(entry, request, "connection_provider_mismatch")
    if not connection.active:
        return _deny(entry, request, "connection_not_connected")
    if request.path not in entry.allowed_paths:
        return _deny(entry, request, "path_not_allowed")
    if not entry.allows_action(request.action_slug):
        return _deny(entry, request, "action_not_allowed")

    required_scope = _required_scope_for_mutation(request.mutation)
    if not connection.scopes.allows(required_scope):
        return _deny(
            entry,
            request,
            "missing_scope",
            required_scopes=(required_scope,),
        )
    if request.preview_evidence_required and not request.preview_evidence_id:
        return _deny(entry, request, "missing_preview_evidence")
    if request.mutation == "apply" and not request.approval_token_present:
        return _deny(
            entry,
            request,
            "missing_approval_token",
            required_scopes=("apply",),
        )

    return WiiiConnectExecutionDecision(
        outcome="allowed",
        reason="allowed",
        provider_slug=entry.slug,
        action_slug=request.action_slug,
        path=request.path,
        required_scopes=(required_scope,),
        audit_tags=(
            f"provider:{entry.provider_kind}",
            f"auth:{entry.auth_mode}",
            f"mutation:{request.mutation}",
        ),
    )


def _required_scope_for_mutation(mutation: ActionMutation) -> ScopeName:
    if mutation == "admin":
        return "admin"
    if mutation == "apply":
        return "apply"
    if mutation == "write":
        return "write"
    if mutation == "preview":
        return "preview"
    return "read"


def _deny(
    entry: WiiiConnectProviderRegistryEntry,
    request: WiiiConnectExecutionRequest,
    reason: ExecutionDenyReason,
    *,
    required_scopes: tuple[ScopeName, ...] = (),
) -> WiiiConnectExecutionDecision:
    return WiiiConnectExecutionDecision(
        outcome="denied",
        reason=reason,
        provider_slug=entry.slug,
        action_slug=request.action_slug,
        path=request.path,
        required_scopes=required_scopes,
        audit_tags=(
            f"provider:{entry.provider_kind}",
            f"auth:{entry.auth_mode}",
            f"deny:{reason}",
        ),
    )


def _safe_audit_key(key: str) -> str:
    return safe_public_argument_key(key)


def _safe_request_id(value: Any) -> str:
    text = redact_runtime_secret_text(value, max_length=160)
    text = " ".join(text.split())
    return text[:96]
