"""Audited Wiii Connect execution gateway boundary.

This module is the provider-neutral policy step immediately before any
third-party action could run. It performs no provider network calls; adapter
implementations remain responsible for execution after this gateway allows a
request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapter_v1 import (
    WIII_CONNECT_ADAPTER_VERSION,
    ExecutionDenyReason,
    ScopeName,
    WiiiConnectConnectionRecordV1,
    WiiiConnectExecutionDecision,
    WiiiConnectExecutionRequest,
    WiiiConnectProviderRegistryEntry,
    decide_external_execution,
)
from .provider_adapters import (
    WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
    WiiiConnectProviderAdapterCapability,
    default_provider_adapter_capability,
)
from .scope_policy import (
    WIII_CONNECT_SCOPE_POLICY_VERSION,
    WiiiConnectScopePolicy,
    WiiiConnectScopePolicyDecision,
    decide_scope_policy,
)


WIII_CONNECT_EXECUTION_GATEWAY_VERSION = "wiii_connect_execution_gateway.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectExecutionGatewayDecision:
    """Gateway preflight result before provider action execution."""

    decision: WiiiConnectExecutionDecision
    adapter: WiiiConnectProviderAdapterCapability
    connection_present: bool = False
    audit_persistent: bool = False
    scope_policy: WiiiConnectScopePolicyDecision | None = None
    required_next: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    @property
    def status(self) -> str:
        return "allowed" if self.allowed else "blocked"

    @property
    def reason(self) -> str:
        return self.decision.reason

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_EXECUTION_GATEWAY_VERSION,
            "adapter_version": WIII_CONNECT_PROVIDER_ADAPTER_VERSION,
            "policy_version": WIII_CONNECT_ADAPTER_VERSION,
            "status": self.status,
            "reason": self.reason,
            "connection_present": self.connection_present,
            "audit_persistent": self.audit_persistent,
            "scope_policy_version": WIII_CONNECT_SCOPE_POLICY_VERSION,
            "scope_policy": (
                self.scope_policy.to_public_metadata()
                if self.scope_policy is not None
                else None
            ),
            "decision": self.decision.to_metadata(),
            "adapter": self.adapter.to_public_metadata(),
            "required_next": list(self.required_next),
            "metadata": _safe_metadata(self.metadata),
        }


def decide_execution_gateway(
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    request: WiiiConnectExecutionRequest,
    *,
    adapter_capability: WiiiConnectProviderAdapterCapability | None = None,
    audit_ledger_metadata: dict[str, Any] | None = None,
    require_persistent_audit: bool = True,
    connection_selection_required: bool = False,
    scope_policy: WiiiConnectScopePolicy | None = None,
) -> WiiiConnectExecutionGatewayDecision:
    """Return the fail-closed decision before a provider action may run."""

    adapter = adapter_capability or default_provider_adapter_capability(
        entry.provider_kind,
    )
    audit_persistent = bool((audit_ledger_metadata or {}).get("persistent"))
    scope_policy_decision = (
        decide_scope_policy(scope_policy, request)
        if scope_policy is not None
        else None
    )

    base = (
        _gateway_deny(entry, request, "connection_selection_required")
        if connection_selection_required
        else decide_external_execution(entry, connection, request)
    )
    if not base.allowed:
        return WiiiConnectExecutionGatewayDecision(
            decision=base,
            adapter=adapter,
            connection_present=connection is not None,
            audit_persistent=audit_persistent,
            scope_policy=scope_policy_decision,
            required_next=_required_next_for_reason(base.reason),
            metadata=_metadata_for_request(request, scope_policy_decision),
        )

    if scope_policy_decision is not None and not scope_policy_decision.allowed:
        decision = _gateway_deny(
            entry,
            request,
            "scope_policy_denied",
            required_scopes=scope_policy_decision.required_scopes,
        )
    elif adapter.provider_kind != entry.provider_kind:
        decision = _gateway_deny(entry, request, "provider_adapter_mismatch")
    elif not adapter.bound:
        decision = _gateway_deny(entry, request, "provider_adapter_not_bound")
    elif not adapter.configured:
        decision = _gateway_deny(entry, request, "provider_adapter_not_configured")
    elif not adapter.can_execute_actions:
        decision = _gateway_deny(entry, request, "provider_adapter_cannot_execute")
    elif require_persistent_audit and not audit_persistent:
        decision = _gateway_deny(entry, request, "audit_ledger_not_persistent")
    else:
        decision = base

    return WiiiConnectExecutionGatewayDecision(
        decision=decision,
        adapter=adapter,
        connection_present=connection is not None,
        audit_persistent=audit_persistent,
        scope_policy=scope_policy_decision,
        required_next=_required_next_for_reason(decision.reason),
        metadata=_metadata_for_request(request, scope_policy_decision),
    )


def _gateway_deny(
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


def _required_next_for_reason(reason: str) -> tuple[str, ...]:
    if reason == "allowed":
        return ()
    mapping: dict[str, tuple[str, ...]] = {
        "provider_disabled": ("enable_provider_registry_entry",),
        "provider_not_agent_ready": (
            "enable_curated_action_catalog",
            "enable_provider_agent_policy",
        ),
        "provider_adapter_mismatch": ("bind_matching_provider_adapter",),
        "provider_adapter_not_bound": ("bind_provider_adapter",),
        "provider_adapter_not_configured": ("configure_provider_adapter",),
        "provider_adapter_cannot_execute": ("implement_provider_action_adapter",),
        "audit_ledger_not_persistent": ("configure_persistent_audit_ledger",),
        "connection_selection_required": ("select_provider_connection",),
        "connection_missing": ("connect_provider_account",),
        "connection_provider_mismatch": ("select_matching_connection",),
        "connection_not_connected": ("refresh_or_reconnect_provider_account",),
        "path_not_allowed": ("select_allowed_product_path",),
        "action_not_allowed": ("curate_action_for_provider",),
        "missing_scope": ("grant_required_scope",),
        "scope_policy_denied": ("grant_required_scope_policy",),
        "missing_preview_evidence": ("create_preview_evidence",),
        "missing_approval_token": ("collect_approval_token",),
    }
    return mapping.get(reason, ("inspect_execution_policy",))


def _metadata_for_request(
    request: WiiiConnectExecutionRequest,
    scope_policy: WiiiConnectScopePolicyDecision | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"request": request.to_audit_metadata()}
    if scope_policy is not None:
        metadata["scope_policy"] = scope_policy.to_public_metadata()
    return metadata


_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")


def _safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS):
                result["redacted_sensitive_field"] = "[redacted]"
                continue
            result[key] = _safe_metadata(raw_value)
        return result
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_metadata(item) for item in value]
    return value


__all__ = [
    "WIII_CONNECT_EXECUTION_GATEWAY_VERSION",
    "WiiiConnectExecutionGatewayDecision",
    "decide_execution_gateway",
]
