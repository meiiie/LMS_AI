"""Wiii Connect activation readiness projection.

This module aggregates existing Wiii Connect gates into one privacy-safe
operator/UI contract. It performs no provider network calls and must not create
authorization sessions, issue Connect Links, mutate connection rows, or expose
provider secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .action_catalog import WiiiConnectCuratedAction
from .adapter_v1 import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectProviderRegistryEntry,
)
from .connection_lifecycle import build_connection_lifecycle_decision
from .execution_gateway import WiiiConnectExecutionGatewayDecision
from .provider_adapters import WiiiConnectProviderAdapterCapability
from .vault import WiiiConnectVaultCapability


WIII_CONNECT_ACTIVATION_READINESS_VERSION = "wiii_connect_activation_readiness.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectActivationGate:
    """One activation gate in the external-provider readiness ladder."""

    key: str
    ready: bool
    reason: str = "ready"
    required_next: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "key": _safe_key(self.key),
            "ready": self.ready,
            "reason": _safe_reason(self.reason),
            "required_next": [_safe_key(value) for value in self.required_next],
            "metadata": _safe_metadata(self.metadata),
        }


def build_activation_readiness_metadata(
    *,
    provider_slug: str,
    connect_entry: WiiiConnectProviderRegistryEntry | None,
    execution_entry: WiiiConnectProviderRegistryEntry | None,
    adapter_capability: WiiiConnectProviderAdapterCapability,
    vault_capability: WiiiConnectVaultCapability,
    storage_metadata: dict[str, Any],
    action: WiiiConnectCuratedAction | None,
    action_runtime_enabled: bool,
    connection: WiiiConnectConnectionRecordV1 | None,
    execution_gateway: WiiiConnectExecutionGatewayDecision | None,
) -> dict[str, Any]:
    """Return a single privacy-safe readiness projection for one provider."""

    provider_registered = connect_entry is not None
    provider_kind = (
        connect_entry.provider_kind
        if connect_entry is not None
        else adapter_capability.provider_kind
    )
    storage_ready = _storage_ready(storage_metadata)
    audit_ready = bool(
        storage_metadata.get("persistent")
        and storage_metadata.get("audit_ledger_ready")
    )
    action_ready = bool(action is not None and action_runtime_enabled)
    connection_ready = bool(connection is not None and connection.active)
    gateway_allowed = bool(execution_gateway is not None and execution_gateway.allowed)
    ready_to_connect = bool(
        provider_registered
        and connect_entry is not None
        and connect_entry.enabled
        and adapter_capability.authorization_ready
        and vault_capability.can_store_external_secret
        and storage_ready
        and audit_ready
    )
    ready_to_execute_action = bool(
        ready_to_connect
        and action_ready
        and connection_ready
        and gateway_allowed
    )
    ready_to_execute_readonly = bool(
        ready_to_execute_action and action is not None and action.mutation == "read"
    )
    gates = (
        _provider_gate(connect_entry),
        _adapter_gate(adapter_capability),
        _vault_gate(vault_capability),
        _storage_gate(storage_metadata),
        _audit_gate(storage_metadata),
        _connect_policy_gate(connect_entry),
        _action_gate(action, runtime_enabled=action_runtime_enabled),
        _connection_gate(connection),
        _execution_gateway_gate(execution_gateway),
    )
    lifecycle_reason = (
        _safe_reason(connection.reason)
        if connection is not None and connection.reason
        else _first_blocked_gate_reason(gates)
    )
    connection_lifecycle = build_connection_lifecycle_decision(
        provider_slug=provider_slug,
        connection=connection,
        reason=lifecycle_reason,
        agent_ready=bool(execution_entry is not None and execution_entry.agent_ready),
        ready_to_connect=ready_to_connect,
        ready_to_execute_action=ready_to_execute_action,
    )
    return {
        "version": WIII_CONNECT_ACTIVATION_READINESS_VERSION,
        "status": "ready" if ready_to_execute_action else "blocked",
        "provider_slug": _safe_key(provider_slug),
        "provider_kind": provider_kind,
        "ready_to_connect": ready_to_connect,
        "ready_to_execute_action": ready_to_execute_action,
        "ready_to_execute_readonly": ready_to_execute_readonly,
        "gates": [gate.to_public_metadata() for gate in gates],
        "provider": connect_entry.to_public_metadata() if connect_entry else None,
        "execution_provider": (
            execution_entry.to_public_metadata() if execution_entry else None
        ),
        "adapter": adapter_capability.to_public_metadata(),
        "vault": vault_capability.to_public_metadata(),
        "storage": _safe_storage_metadata(storage_metadata),
        "action": _action_metadata(action, runtime_enabled=action_runtime_enabled),
        "connection": _connection_metadata(connection),
        "connection_lifecycle": connection_lifecycle.to_public_metadata(),
        "execution_gateway": (
            execution_gateway.to_public_metadata() if execution_gateway else None
        ),
    }


def _provider_gate(
    entry: WiiiConnectProviderRegistryEntry | None,
) -> WiiiConnectActivationGate:
    if entry is None:
        return WiiiConnectActivationGate(
            key="provider_registered",
            ready=False,
            reason="unknown_provider",
            required_next=("register_provider",),
        )
    if entry.provider_kind != "composio":
        return WiiiConnectActivationGate(
            key="provider_registered",
            ready=False,
            reason="provider_kind_not_composio",
            required_next=("select_composio_provider",),
            metadata={"provider_kind": entry.provider_kind},
        )
    return WiiiConnectActivationGate(
        key="provider_registered",
        ready=True,
        metadata={"provider_kind": entry.provider_kind},
    )


def _adapter_gate(
    capability: WiiiConnectProviderAdapterCapability,
) -> WiiiConnectActivationGate:
    return WiiiConnectActivationGate(
        key="provider_adapter",
        ready=capability.authorization_ready,
        reason=capability.reason,
        required_next=()
        if capability.authorization_ready
        else ("configure_composio_adapter",),
        metadata={
            "bound": capability.bound,
            "configured": capability.configured,
            "can_create_authorization_url": capability.can_create_authorization_url,
            "can_execute_actions": capability.can_execute_actions,
        },
    )


def _vault_gate(capability: WiiiConnectVaultCapability) -> WiiiConnectActivationGate:
    return WiiiConnectActivationGate(
        key="vault",
        ready=capability.can_store_external_secret,
        reason=capability.reason,
        required_next=()
        if capability.can_store_external_secret
        else ("configure_provider_managed_vault",),
        metadata={
            "backend": capability.backend,
            "provider_managed": capability.provider_managed,
        },
    )


def _storage_gate(storage: dict[str, Any]) -> WiiiConnectActivationGate:
    ready = _storage_ready(storage)
    return WiiiConnectActivationGate(
        key="persistent_storage",
        ready=ready,
        reason=str(storage.get("reason") or ("ready" if ready else "storage_not_ready")),
        required_next=() if ready else ("apply_wiii_connect_storage_migration",),
        metadata={
            "persistent": bool(storage.get("persistent")),
            "connection_table_ready": bool(storage.get("connection_table_ready")),
            "audit_ledger_ready": bool(storage.get("audit_ledger_ready")),
        },
    )


def _audit_gate(storage: dict[str, Any]) -> WiiiConnectActivationGate:
    ready = bool(storage.get("persistent") and storage.get("audit_ledger_ready"))
    return WiiiConnectActivationGate(
        key="audit_ledger",
        ready=ready,
        reason=str(storage.get("reason") or ("ready" if ready else "audit_not_ready")),
        required_next=() if ready else ("configure_persistent_audit_ledger",),
        metadata={
            "persistent": bool(storage.get("persistent")),
            "audit_ledger_ready": bool(storage.get("audit_ledger_ready")),
        },
    )


def _connect_policy_gate(
    entry: WiiiConnectProviderRegistryEntry | None,
) -> WiiiConnectActivationGate:
    ready = bool(entry is not None and entry.enabled)
    return WiiiConnectActivationGate(
        key="connect_policy",
        ready=ready,
        reason="ready" if ready else "provider_disabled",
        required_next=() if ready else ("enable_connect_policy",),
        metadata={
            "agent_ready": bool(entry.agent_ready) if entry is not None else False,
            "connect_requirements": list(entry.connection_requirements())
            if entry is not None
            else [],
            "agent_ready_requirements": list(entry.agent_ready_requirements)
            if entry is not None
            else [],
        },
    )


def _action_gate(
    action: WiiiConnectCuratedAction | None,
    *,
    runtime_enabled: bool,
) -> WiiiConnectActivationGate:
    if action is None:
        return WiiiConnectActivationGate(
            key="curated_action",
            ready=False,
            reason="action_not_curated",
            required_next=("curate_action",),
        )
    ready = bool(runtime_enabled)
    reason = "ready" if ready else "action_not_runtime_enabled"
    required_next = () if ready else ("enable_action_allowlist",)
    return WiiiConnectActivationGate(
        key="curated_readonly_action" if action.mutation == "read" else "curated_action",
        ready=ready,
        reason=reason,
        required_next=required_next,
        metadata={
            "action_slug": action.slug,
            "mutation": action.mutation,
            "runtime_enabled": runtime_enabled,
            "requires_preview": action.requires_preview,
            "requires_approval": action.requires_approval,
        },
    )


def _connection_gate(
    connection: WiiiConnectConnectionRecordV1 | None,
) -> WiiiConnectActivationGate:
    if connection is None:
        return WiiiConnectActivationGate(
            key="local_connection",
            ready=False,
            reason="connection_missing",
            required_next=("complete_provider_oauth",),
        )
    ready = connection.active
    return WiiiConnectActivationGate(
        key="local_connection",
        ready=ready,
        reason="ready" if ready else "connection_not_connected",
        required_next=() if ready else ("refresh_or_reconnect_provider_account",),
        metadata=_connection_metadata(connection),
    )


def _execution_gateway_gate(
    gateway: WiiiConnectExecutionGatewayDecision | None,
) -> WiiiConnectActivationGate:
    if gateway is None:
        return WiiiConnectActivationGate(
            key="execution_gateway",
            ready=False,
            reason="gateway_not_evaluated",
            required_next=("evaluate_execution_gateway",),
        )
    return WiiiConnectActivationGate(
        key="execution_gateway",
        ready=gateway.allowed,
        reason=gateway.reason,
        required_next=gateway.required_next,
        metadata={
            "connection_present": gateway.connection_present,
            "audit_persistent": gateway.audit_persistent,
        },
    )


def _storage_ready(storage: dict[str, Any]) -> bool:
    return bool(
        storage.get("persistent")
        and storage.get("connection_table_ready")
        and storage.get("audit_ledger_ready")
    )


def _action_metadata(
    action: WiiiConnectCuratedAction | None,
    *,
    runtime_enabled: bool,
) -> dict[str, Any] | None:
    if action is None:
        return None
    metadata = action.to_public_metadata()
    metadata["runtime_enabled"] = runtime_enabled
    return _safe_metadata(metadata)


def _connection_metadata(
    connection: WiiiConnectConnectionRecordV1 | None,
) -> dict[str, Any]:
    if connection is None:
        return {
            "present": False,
            "state": "missing",
            "active": False,
            "vault_ref_present": False,
            "scopes": {},
            "reason": "connection_missing",
            "warnings": [],
        }
    return {
        "present": True,
        "provider_slug": _safe_key(connection.provider_slug),
        "state": connection.state,
        "active": connection.active,
        "scopes": connection.scopes.to_metadata(),
        "vault_ref_present": connection.vault_ref is not None,
        "account_label_present": bool(connection.account_label),
        "external_account_ref_present": bool(connection.external_account_ref),
        "last_checked_at_present": bool(connection.last_checked_at),
        "reason": _safe_reason(connection.reason),
        "warnings": [_safe_reason(warning) for warning in connection.warnings],
    }


def _first_blocked_gate_reason(gates: tuple[WiiiConnectActivationGate, ...]) -> str:
    for gate in gates:
        if not gate.ready:
            return gate.reason
    return "connected"


def _safe_storage_metadata(storage: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "version",
        "enabled",
        "persistent",
        "backend",
        "connection_table_ready",
        "audit_ledger_ready",
        "reason",
        "warnings",
    }
    return {
        key: _safe_metadata(value)
        for key, value in storage.items()
        if key in allowed
    }


_SENSITIVE_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "client_key",
    "private_key",
    "authorization_code",
    "oauth_code",
)


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _safe_key(raw_key)
            if any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS):
                result["redacted_sensitive_field"] = "[redacted]"
                continue
            result[key] = _safe_metadata(raw_value)
        return result
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value)
    return value


def _safe_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:120] or "unknown"


def _safe_reason(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if any(marker in text for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_value"
    return text[:160] or "ready"


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    if any(marker in text.lower() for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_value"
    return text[:240]


__all__ = [
    "WIII_CONNECT_ACTIVATION_READINESS_VERSION",
    "WiiiConnectActivationGate",
    "build_activation_readiness_metadata",
]
