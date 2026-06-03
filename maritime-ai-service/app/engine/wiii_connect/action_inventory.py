"""Effective Wiii Connect action inventory.

OpenHuman keeps the model-facing tool list behind a connection/toolkit policy
gate. This module is Wiii's provider-scoped equivalent: it turns the curated
catalog, runtime allowlist, selected connection, scope policy, and execution
gateway into one privacy-safe inventory before any tool schema is exposed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from .argument_key_policy import (
    WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
    hidden_model_argument_key_count,
    model_visible_argument_keys,
    safe_public_argument_key,
)
from .action_catalog import (
    WiiiConnectCuratedAction,
    list_wiii_connect_curated_actions,
)
from .adapter_v1 import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectExecutionRequest,
    WiiiConnectProviderRegistryEntry,
)
from .execution_gateway import (
    WiiiConnectExecutionGatewayDecision,
    decide_execution_gateway,
)
from .provider_adapters import WiiiConnectProviderAdapterCapability
from .scope_policy import WiiiConnectScopePolicy, scope_policy_for_provider_entry


WIII_CONNECT_ACTION_INVENTORY_VERSION = "wiii_connect_action_inventory.v1"

ActionInventoryStageStatus = Literal["ready", "pending", "blocked"]
ActionInventoryActionStatus = Literal["ready", "guarded", "blocked"]
ActionInventoryStatus = Literal["ready", "guarded", "blocked"]

_GATEWAY_GUARDED_REASONS = frozenset(
    {
        "missing_preview_evidence",
        "missing_approval_token",
    }
)


@dataclass(frozen=True, slots=True)
class WiiiConnectEffectiveActionStage:
    """One readiness stage for a provider action."""

    key: str
    status: ActionInventoryStageStatus
    reason: str
    required_next: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status,
            "reason": self.reason,
            "required_next": list(self.required_next),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectEffectiveActionRecord:
    """One effective action row safe for UI/runtime diagnostics."""

    slug: str
    provider_slug: str
    label: str
    mutation: str
    path: str
    status: ActionInventoryActionStatus
    reason: str
    runtime_enabled: bool = False
    visible_to_agent: bool = False
    executable_now: bool = False
    requires_preview: bool = False
    requires_approval: bool = False
    required_scopes: tuple[str, ...] = ()
    argument_keys: tuple[str, ...] = ()
    hidden_argument_count: int = 0
    stages: tuple[WiiiConnectEffectiveActionStage, ...] = ()
    gateway: WiiiConnectExecutionGatewayDecision | None = None
    warnings: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ACTION_INVENTORY_VERSION,
            "slug": self.slug,
            "provider_slug": self.provider_slug,
            "label": self.label,
            "mutation": self.mutation,
            "path": self.path,
            "status": self.status,
            "reason": self.reason,
            "runtime_enabled": self.runtime_enabled,
            "visible_to_agent": self.visible_to_agent,
            "executable_now": self.executable_now,
            "requires_preview": self.requires_preview,
            "requires_approval": self.requires_approval,
            "required_scopes": list(self.required_scopes),
            "argument_policy_version": WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
            "argument_keys": list(self.argument_keys),
            "model_argument_keys": list(self.argument_keys),
            "hidden_argument_count": self.hidden_argument_count,
            "stages": [stage.to_public_metadata() for stage in self.stages],
            "gateway": self.gateway.to_public_metadata() if self.gateway else None,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectEffectiveActionInventory:
    """Provider-scoped effective action inventory."""

    version: str
    provider_slug: str
    provider_kind: str
    status: ActionInventoryStatus
    reason: str
    connection_ref_present: bool = False
    connection_present: bool = False
    connection_active: bool = False
    selected_connection_required: bool = False
    catalog_action_count: int = 0
    runtime_enabled_action_count: int = 0
    visible_action_count: int = 0
    executable_action_count: int = 0
    actions: tuple[WiiiConnectEffectiveActionRecord, ...] = ()
    storage: Mapping[str, Any] | None = None

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "provider_slug": self.provider_slug,
            "provider_kind": self.provider_kind,
            "status": self.status,
            "reason": self.reason,
            "connection_ref_present": self.connection_ref_present,
            "connection_present": self.connection_present,
            "connection_active": self.connection_active,
            "selected_connection_required": self.selected_connection_required,
            "catalog_action_count": self.catalog_action_count,
            "runtime_enabled_action_count": self.runtime_enabled_action_count,
            "visible_action_count": self.visible_action_count,
            "executable_action_count": self.executable_action_count,
            "actions": [action.to_public_metadata() for action in self.actions],
            "storage": _safe_storage_metadata(self.storage or {}),
        }


def build_wiii_connect_effective_action_inventory(
    *,
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    adapter_capability: WiiiConnectProviderAdapterCapability,
    runtime_enabled_action_slugs: Iterable[str],
    audit_ledger_metadata: Mapping[str, Any] | None = None,
    connection_ref_present: bool = False,
    connection_selection_required: bool = False,
    storage_metadata: Mapping[str, Any] | None = None,
    scope_policy: WiiiConnectScopePolicy | None = None,
) -> WiiiConnectEffectiveActionInventory:
    """Build the effective provider action inventory without provider I/O."""

    enabled_slugs = _action_slug_set(runtime_enabled_action_slugs)
    scope_policy = scope_policy if scope_policy is not None else scope_policy_for_provider_entry(entry)
    actions = tuple(
        _effective_action_record(
            action,
            entry=entry,
            connection=connection,
            adapter_capability=adapter_capability,
            runtime_enabled=action.slug in enabled_slugs,
            audit_ledger_metadata=audit_ledger_metadata or {},
            connection_selection_required=connection_selection_required,
            scope_policy=scope_policy,
        )
        for action in list_wiii_connect_curated_actions(provider_slug=entry.slug)
    )
    visible_count = sum(1 for action in actions if action.visible_to_agent)
    executable_count = sum(1 for action in actions if action.executable_now)
    if executable_count > 0:
        status: ActionInventoryStatus = "ready"
        reason = "ready"
    elif visible_count > 0:
        status = "guarded"
        reason = "preview_or_approval_required"
    else:
        status = "blocked"
        reason = _inventory_block_reason(
            entry=entry,
            connection=connection,
            connection_selection_required=connection_selection_required,
            actions=actions,
        )
    return WiiiConnectEffectiveActionInventory(
        version=WIII_CONNECT_ACTION_INVENTORY_VERSION,
        provider_slug=entry.slug,
        provider_kind=entry.provider_kind,
        status=status,
        reason=reason,
        connection_ref_present=connection_ref_present,
        connection_present=connection is not None,
        connection_active=bool(connection and connection.active),
        selected_connection_required=connection_selection_required,
        catalog_action_count=len(actions),
        runtime_enabled_action_count=sum(1 for action in actions if action.runtime_enabled),
        visible_action_count=visible_count,
        executable_action_count=executable_count,
        actions=actions,
        storage=storage_metadata,
    )


def _effective_action_record(
    action: WiiiConnectCuratedAction,
    *,
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    adapter_capability: WiiiConnectProviderAdapterCapability,
    runtime_enabled: bool,
    audit_ledger_metadata: Mapping[str, Any],
    connection_selection_required: bool,
    scope_policy: WiiiConnectScopePolicy,
) -> WiiiConnectEffectiveActionRecord:
    request = WiiiConnectExecutionRequest(
        provider_slug=entry.slug,
        action_slug=action.slug,
        path=action.path,
        mutation=action.mutation,
        preview_evidence_required=action.requires_preview,
        approval_token_present=False,
        argument_keys=action.argument_keys,
    )
    gateway = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=adapter_capability,
        audit_ledger_metadata=dict(audit_ledger_metadata),
        connection_selection_required=connection_selection_required,
        scope_policy=scope_policy,
    )
    scope_visible = _required_scope_granted(action, connection)
    visible_to_agent = bool(
        runtime_enabled
        and entry.enabled
        and entry.agent_ready
        and connection is not None
        and connection.active
        and scope_visible
    )
    executable_now = bool(runtime_enabled and gateway.allowed)
    if executable_now:
        status: ActionInventoryActionStatus = "ready"
        reason = "ready"
    elif visible_to_agent and gateway.reason in _GATEWAY_GUARDED_REASONS:
        status = "guarded"
        reason = gateway.reason
    else:
        status = "blocked"
        reason = _action_block_reason(
            runtime_enabled=runtime_enabled,
            gateway_reason=gateway.reason,
        )
    return WiiiConnectEffectiveActionRecord(
        slug=action.slug,
        provider_slug=action.provider_slug,
        label=action.label,
        mutation=action.mutation,
        path=action.path,
        status=status,
        reason=reason,
        runtime_enabled=runtime_enabled,
        visible_to_agent=visible_to_agent,
        executable_now=executable_now,
        requires_preview=action.requires_preview,
        requires_approval=action.requires_approval,
        required_scopes=action.required_scopes,
        argument_keys=model_visible_argument_keys(
            provider_slug=action.provider_slug,
            action_slug=action.slug,
            argument_keys=action.argument_keys,
        ),
        hidden_argument_count=hidden_model_argument_key_count(
            provider_slug=action.provider_slug,
            action_slug=action.slug,
            argument_keys=action.argument_keys,
        ),
        stages=_action_stages(
            runtime_enabled=runtime_enabled,
            entry=entry,
            connection=connection,
            scope_visible=scope_visible,
            gateway=gateway,
        ),
        gateway=gateway,
        warnings=action.warnings,
    )


def _action_stages(
    *,
    runtime_enabled: bool,
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    scope_visible: bool,
    gateway: WiiiConnectExecutionGatewayDecision,
) -> tuple[WiiiConnectEffectiveActionStage, ...]:
    account_reason = (
        "connected"
        if connection is not None and connection.active
        else "connection_not_connected"
        if connection is not None
        else "connection_missing"
    )
    return (
        WiiiConnectEffectiveActionStage(
            key="catalog",
            status="ready",
            reason="curated",
        ),
        WiiiConnectEffectiveActionStage(
            key="runtime_enablement",
            status="ready" if runtime_enabled else "blocked",
            reason="enabled" if runtime_enabled else "action_not_runtime_enabled",
            required_next=() if runtime_enabled else ("enable_action_runtime_allowlist",),
        ),
        WiiiConnectEffectiveActionStage(
            key="account",
            status="ready"
            if connection is not None and connection.active
            else "pending"
            if connection is not None
            else "blocked",
            reason=account_reason,
            required_next=()
            if connection is not None and connection.active
            else ("refresh_or_reconnect_provider_account",)
            if connection is not None
            else ("connect_provider_account",),
        ),
        WiiiConnectEffectiveActionStage(
            key="agent_policy",
            status="ready" if entry.enabled and entry.agent_ready and scope_visible else "blocked",
            reason="agent_ready"
            if entry.enabled and entry.agent_ready and scope_visible
            else "missing_scope"
            if entry.enabled and entry.agent_ready
            else "provider_not_agent_ready",
            required_next=()
            if entry.enabled and entry.agent_ready and scope_visible
            else ("grant_required_scope",)
            if entry.enabled and entry.agent_ready
            else ("enable_provider_agent_policy",),
        ),
        WiiiConnectEffectiveActionStage(
            key="gateway",
            status="ready"
            if gateway.allowed
            else "pending"
            if gateway.reason in _GATEWAY_GUARDED_REASONS
            else "blocked",
            reason=gateway.reason,
            required_next=tuple(gateway.required_next),
        ),
    )


def _inventory_block_reason(
    *,
    entry: WiiiConnectProviderRegistryEntry,
    connection: WiiiConnectConnectionRecordV1 | None,
    connection_selection_required: bool,
    actions: tuple[WiiiConnectEffectiveActionRecord, ...],
) -> str:
    if not entry.enabled or not entry.agent_ready:
        return "provider_not_agent_ready"
    if connection_selection_required:
        return "connection_selection_required"
    if connection is None:
        return "connection_missing"
    if not connection.active:
        return "connection_not_connected"
    if actions and all(not action.runtime_enabled for action in actions):
        return "no_runtime_enabled_actions"
    if actions and all(action.reason == "missing_scope" for action in actions):
        return "missing_scope"
    return actions[0].reason if actions else "no_curated_actions"


def _action_block_reason(*, runtime_enabled: bool, gateway_reason: str) -> str:
    if not runtime_enabled:
        return "action_not_runtime_enabled"
    return gateway_reason or "blocked"


def _required_scope_granted(
    action: WiiiConnectCuratedAction,
    connection: WiiiConnectConnectionRecordV1 | None,
) -> bool:
    if connection is None:
        return False
    scopes = action.required_scopes or ("read",)
    return all(connection.scopes.allows(scope) for scope in scopes)


def _action_slug_set(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        str(value or "").strip().upper().replace("-", "_")
        for value in values
        if str(value or "").strip()
    )


def _safe_public_key(value: str) -> str:
    return safe_public_argument_key(value)


def _safe_storage_metadata(storage: Mapping[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "version",
        "enabled",
        "persistent",
        "connection_table_ready",
        "audit_ledger_ready",
        "backend",
        "reason",
    }
    return {
        key: value
        for key, value in storage.items()
        if key in allowed_keys and (value is None or isinstance(value, (str, int, float, bool)))
    }


__all__ = [
    "WIII_CONNECT_ACTION_INVENTORY_VERSION",
    "WiiiConnectEffectiveActionInventory",
    "WiiiConnectEffectiveActionRecord",
    "WiiiConnectEffectiveActionStage",
    "build_wiii_connect_effective_action_inventory",
]
