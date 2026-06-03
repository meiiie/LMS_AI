"""Privacy-safe connection lifecycle decisions for Wiii Connect."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


WIII_CONNECT_CONNECTION_LIFECYCLE_VERSION = "wiii_connect_connection_lifecycle.v1"

ConnectionFlowStatus = Literal[
    "disconnected",
    "authorizing",
    "waiting",
    "connected",
    "expired",
    "error",
]


@dataclass(frozen=True, slots=True)
class WiiiConnectConnectionLifecycleDecision:
    """One provider account lifecycle state, without provider identifiers."""

    provider_slug: str
    status: ConnectionFlowStatus
    reason: str
    active: bool = False
    connection_present: bool = False
    agent_ready: bool = False
    ready_to_connect: bool = False
    ready_to_execute_action: bool = False
    required_next: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_CONNECTION_LIFECYCLE_VERSION,
            "provider_slug": _safe_key(self.provider_slug),
            "status": self.status,
            "reason": _safe_key(self.reason),
            "active": self.active,
            "connection_present": self.connection_present,
            "agent_ready": self.agent_ready,
            "ready_to_connect": self.ready_to_connect,
            "ready_to_execute_action": self.ready_to_execute_action,
            "required_next": [_safe_key(item) for item in self.required_next],
        }


def build_connection_lifecycle_decision(
    *,
    provider_slug: str,
    connection: Any | None = None,
    status: str | None = None,
    reason: str = "",
    connection_present: bool | None = None,
    active: bool | None = None,
    agent_ready: bool = False,
    ready_to_connect: bool = False,
    ready_to_execute_action: bool = False,
    required_next: tuple[str, ...] | None = None,
) -> WiiiConnectConnectionLifecycleDecision:
    """Build the canonical OpenHuman-style connection flow projection."""

    raw_state = status
    if connection is not None:
        raw_state = str(getattr(connection, "state", raw_state or "") or raw_state or "")
    resolved_active = bool(
        getattr(connection, "active", False) if active is None else active
    )
    resolved_present = (
        connection is not None if connection_present is None else connection_present
    )
    resolved_status = normalize_connection_flow_status(
        raw_state,
        active=resolved_active,
    )
    resolved_reason = _safe_key(
        reason
        or str(getattr(connection, "reason", "") if connection is not None else "")
        or _default_reason_for_status(resolved_status, ready_to_connect=ready_to_connect)
    )
    return WiiiConnectConnectionLifecycleDecision(
        provider_slug=provider_slug,
        status=resolved_status,
        reason=resolved_reason,
        active=resolved_active,
        connection_present=resolved_present,
        agent_ready=agent_ready,
        ready_to_connect=ready_to_connect,
        ready_to_execute_action=ready_to_execute_action,
        required_next=(
            tuple(_safe_key(item) for item in required_next)
            if required_next is not None
            else _required_next_for_lifecycle(
                resolved_status,
                resolved_reason,
                agent_ready=agent_ready,
                ready_to_connect=ready_to_connect,
                ready_to_execute_action=ready_to_execute_action,
            )
        ),
    )


def sanitize_connection_lifecycle_metadata(value: Any) -> dict[str, Any]:
    """Return the public connection lifecycle contract from arbitrary metadata."""

    if not isinstance(value, Mapping):
        return {}
    allowed = {
        "version",
        "provider_slug",
        "status",
        "reason",
        "active",
        "connection_present",
        "agent_ready",
        "ready_to_connect",
        "ready_to_execute_action",
        "required_next",
    }
    safe: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key)
        if key not in allowed or item is None:
            continue
        if isinstance(item, bool):
            safe[key] = item
        elif isinstance(item, (list, tuple, set, frozenset)):
            safe[key] = [
                token
                for token in (
                    _safe_public_lifecycle_token(entry) for entry in item
                )
                if token
            ][:8]
        else:
            token = _safe_public_lifecycle_token(item)
            if token:
                safe[key] = token
    return safe


def normalize_connection_flow_status(
    value: str | None,
    *,
    active: bool = False,
) -> ConnectionFlowStatus:
    """Normalize storage/provider/UI status words into one lifecycle enum."""

    if active:
        return "connected"
    normalized = _safe_key(value)
    if normalized in {"connected", "active", "preview"}:
        return "connected"
    if normalized == "authorizing":
        return "authorizing"
    if normalized in {"waiting", "pending", "initiated", "initializing"}:
        return "waiting"
    if normalized == "expired":
        return "expired"
    if normalized in {"error", "failed"}:
        return "error"
    return "disconnected"


def _default_reason_for_status(
    status: ConnectionFlowStatus,
    *,
    ready_to_connect: bool,
) -> str:
    if status == "connected":
        return "connected"
    if status == "authorizing":
        return "authorization_started"
    if status == "waiting":
        return "waiting_for_oauth"
    if status == "expired":
        return "connection_expired"
    if status == "error":
        return "connection_error"
    return "ready_to_connect" if ready_to_connect else "connection_missing"


def _required_next_for_lifecycle(
    status: ConnectionFlowStatus,
    reason: str,
    *,
    agent_ready: bool,
    ready_to_connect: bool,
    ready_to_execute_action: bool,
) -> tuple[str, ...]:
    if status == "connected":
        if ready_to_execute_action:
            return ()
        if agent_ready:
            return ("select_action_and_evaluate_gateway",)
        return ("inspect_provider_readiness",)
    if status in {"authorizing", "waiting"}:
        return ("complete_provider_oauth",)
    if status == "expired":
        return ("reconnect_provider_account",)
    if status == "error":
        return ("inspect_provider_connection_error",)
    mapping: dict[str, tuple[str, ...]] = {
        "connection_storage_unavailable": ("configure_wiii_connect_storage",),
        "provider_adapter_disabled": ("configure_composio_adapter",),
        "provider_adapter_not_bound": ("bind_provider_adapter",),
        "provider_adapter_not_configured": ("configure_provider_adapter",),
        "provider_disabled": ("enable_provider_registry_entry",),
    }
    if reason in mapping:
        return mapping[reason]
    return ("complete_provider_oauth",) if ready_to_connect else ("connect_provider_account",)


def _safe_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch == "_")[:96]


def _safe_public_lifecycle_token(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch in {"_", "."})[:96]
