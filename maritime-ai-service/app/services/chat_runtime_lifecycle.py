"""Typed lifecycle events for the SSE V3 chat runtime.

These events are additive observability: they let clients and harnesses follow
the turn path without parsing Vietnamese status copy or waiting for terminal
metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.engine.multi_agent.stream_utils import StreamEvent


CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION = "wiii.chat_runtime_lifecycle.v1"
CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE = "chat_lifecycle"


class ChatLifecycleName:
    """Stable lifecycle names emitted on the SSE wire."""

    CHAT_ACCEPTED = "chat.accepted"
    TURN_PREPARED = "turn.prepared"
    PATH_SELECTED = "path.selected"
    CAPABILITY_CHECKED = "capability.checked"
    FINALIZATION_COMPLETED = "finalization.completed"
    FINALIZATION_FAILED = "finalization.failed"
    CHAT_DONE = "chat.done"
    CHAT_ERROR = "chat.error"


_MAX_ITEMS = 24
_MAX_STRING_LENGTH = 128
_ELLIPSIS = "..."
_ALLOWED_METADATA_KEYS = {
    "bound_tools",
    "domain_id",
    "error_type",
    "fallback_used",
    "model",
    "organization_id_present",
    "provider",
    "reason_code",
    "recoverable",
    "transport",
}


def _safe_string(value: Any, *, max_length: int = _MAX_STRING_LENGTH) -> str | None:
    if max_length <= 0:
        return None
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = " ".join(text.split())
    if len(text) > max_length:
        if max_length <= len(_ELLIPSIS):
            return _ELLIPSIS[:max_length]
        return text[: max_length - len(_ELLIPSIS)] + _ELLIPSIS
    return text


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    output: list[str] = []
    for item in value:
        text = _safe_string(item)
        if text and text not in output:
            output.append(text)
        if len(output) >= _MAX_ITEMS:
            break
    return output


def _safe_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _safe_metadata_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return _safe_string(value)
    if isinstance(value, (list, tuple, set)):
        return _safe_string_list(value)
    return "<redacted>"


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if key_text not in _ALLOWED_METADATA_KEYS or value is None:
            continue
        safe_value = _safe_metadata_value(value)
        if safe_value is not None:
            safe[key_text] = safe_value
    return safe


_ALLOWED_WIII_CONNECT_CONNECTION_KEYS = {
    "id",
    "provider_kind",
    "slug",
    "label",
    "status",
    "active",
    "agent_ready",
    "scopes",
    "capabilities",
    "required_for_paths",
    "source",
    "last_checked_at",
    "reason",
    "warnings",
    "host_type",
    "connector_id",
    "resource_count",
    "surface_count",
    "tool_count",
    "mutating_tool_count",
    "attachment_count",
    "document_count",
    "source_ref_count",
    "target_count",
    "fail_closed_tool",
    "default_city",
}
_ALLOWED_WIII_CONNECT_PATH_KEYS = {
    "path",
    "allowed_connection_slugs",
    "required_connection_slugs",
    "allowed_tool_groups",
    "forbidden_tool_groups",
    "mutation_policy",
    "delegation_policy",
}
_WIII_CONNECT_SCOPE_KEYS = {"read", "preview", "write", "apply", "admin"}


def _safe_bool_mapping(value: Any, allowed_keys: set[str]) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: bool(value.get(key))
        for key in allowed_keys
        if isinstance(value.get(key), bool)
    }


def _safe_wiii_connect_record(
    value: Any,
    *,
    allowed_keys: set[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    record: dict[str, Any] = {}
    for key in allowed_keys:
        raw_value = value.get(key)
        if raw_value is None:
            continue
        if key == "scopes":
            scopes = _safe_bool_mapping(raw_value, _WIII_CONNECT_SCOPE_KEYS)
            if scopes:
                record[key] = scopes
            continue
        if isinstance(raw_value, bool | int | float):
            record[key] = raw_value
            continue
        if isinstance(raw_value, str):
            text = _safe_string(raw_value)
            if text:
                record[key] = text
            continue
        strings = _safe_string_list(raw_value)
        if strings:
            record[key] = strings
    return record if record else None


def _safe_wiii_connect_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    snapshot: dict[str, Any] = {}
    for key in ("version", "generated_at", "surface"):
        text = _safe_string(value.get(key))
        if text:
            snapshot[key] = text

    connections = value.get("connections")
    if isinstance(connections, (list, tuple)):
        safe_connections: list[dict[str, Any]] = []
        for item in connections:
            record = _safe_wiii_connect_record(
                item,
                allowed_keys=_ALLOWED_WIII_CONNECT_CONNECTION_KEYS,
            )
            if record:
                safe_connections.append(record)
            if len(safe_connections) >= _MAX_ITEMS:
                break
        if safe_connections:
            snapshot["connections"] = safe_connections

    path_capabilities = value.get("path_capabilities")
    if isinstance(path_capabilities, (list, tuple)):
        safe_paths: list[dict[str, Any]] = []
        for item in path_capabilities:
            record = _safe_wiii_connect_record(
                item,
                allowed_keys=_ALLOWED_WIII_CONNECT_PATH_KEYS,
            )
            if record:
                safe_paths.append(record)
            if len(safe_paths) >= _MAX_ITEMS:
                break
        if safe_paths:
            snapshot["path_capabilities"] = safe_paths

    warnings = _safe_string_list(value.get("warnings"))
    if warnings:
        snapshot["warnings"] = warnings

    return snapshot if snapshot else None


def capability_snapshot_from_ledger_payload(
    ledger_payload: Mapping[str, Any],
    *,
    wiii_connect_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the lifecycle-safe capability/tool subset from a flow ledger."""

    request = _safe_mapping(ledger_payload.get("request"))
    tools = _safe_mapping(ledger_payload.get("tools"))
    host_actions = _safe_mapping(ledger_payload.get("host_actions"))
    payload: dict[str, Any] = {
        "host_surface": _safe_string(request.get("host_surface")) or "unknown",
        "host_capabilities": _safe_string_list(request.get("host_capabilities")),
        "observed_tools": _safe_string_list(tools.get("observed")),
        "suppressed_tools": _safe_string_list(tools.get("suppressed")),
        "preview_required": bool(host_actions.get("preview_required")),
        "preview_emitted": bool(host_actions.get("preview_emitted")),
        "approval_token_present": bool(host_actions.get("approval_token_present")),
        "apply_attempted": bool(host_actions.get("apply_attempted")),
    }
    safe_wiii_connect = _safe_wiii_connect_snapshot(wiii_connect_snapshot)
    if safe_wiii_connect:
        payload["wiii_connect"] = safe_wiii_connect
    return payload


@dataclass(frozen=True)
class ChatRuntimeLifecycleEvent:
    """Privacy-safe lifecycle event for streaming chat clients."""

    name: str
    phase: str
    status: str
    message: str
    request_id: str | None = None
    session_id: str | None = None
    lane: str | None = None
    reason: str | None = None
    node: str | None = None
    capabilities: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION,
            "event_name": self.name,
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
        }
        for key, value in (
            ("request_id", self.request_id),
            ("session_id", self.session_id),
            ("lane", self.lane),
            ("reason", self.reason),
            ("node", self.node),
        ):
            text = _safe_string(value)
            if text:
                payload[key] = text
        if self.capabilities is not None:
            payload["capabilities"] = dict(self.capabilities)
        if self.metadata:
            metadata = _safe_metadata(self.metadata)
            if metadata:
                payload["metadata"] = metadata
        return payload


def create_chat_lifecycle_event(
    lifecycle: ChatRuntimeLifecycleEvent,
) -> StreamEvent:
    """Wrap a typed lifecycle payload in the existing StreamEvent transport."""

    return StreamEvent(
        type=CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE,
        content=lifecycle.to_payload(),
        node=lifecycle.node,
        step=lifecycle.phase,
        details={"event_name": lifecycle.name},
    )


__all__ = [
    "CHAT_RUNTIME_LIFECYCLE_EVENT_TYPE",
    "CHAT_RUNTIME_LIFECYCLE_SCHEMA_VERSION",
    "ChatLifecycleName",
    "ChatRuntimeLifecycleEvent",
    "capability_snapshot_from_ledger_payload",
    "create_chat_lifecycle_event",
]
