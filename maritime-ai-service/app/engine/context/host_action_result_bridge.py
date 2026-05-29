"""Runtime-local bridge for host action results.

This is the backend half of Wiii's host-action continuation loop. The agent
emits a host action request over SSE, the frontend executes the action, then
posts the sanitized result back by ``request_id`` so the same chat turn can
finalize from real execution evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.engine.multi_agent.direct_reasoning import _DIRECT_HOST_ACTION_PREFIX
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
)

logger = logging.getLogger(__name__)

HOST_ACTION_RESULT_BRIDGE_VERSION = "host_action_result_bridge.v1"
DEFAULT_HOST_ACTION_RESULT_TIMEOUT_SECONDS = 28.0
MAX_PENDING_HOST_ACTION_RESULTS = 256
PENDING_TTL_SECONDS = 120.0

_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "authorization",
        "approval_token",
        "image_base64",
    }
)

_WAIT_FOR_RESULT_ACTIONS = frozenset({WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION})

PublicationStatus = Literal[
    "accepted",
    "not_pending",
    "action_mismatch",
    "identity_mismatch",
    "expired",
]


@dataclass(frozen=True, slots=True)
class HostActionRequestPayload:
    request_id: str
    action: str
    params: dict[str, Any]


@dataclass(slots=True)
class HostActionResultTicket:
    request_id: str
    action: str
    user_id: str | None
    organization_id: str | None
    created_at: float
    future: asyncio.Future[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class HostActionResultPublication:
    status: PublicationStatus
    request_id: str
    action: str
    reason: str | None = None


_pending: dict[str, HostActionResultTicket] = {}


def parse_host_action_request_result(tool_name: str, result: object) -> HostActionRequestPayload | None:
    """Parse the JSON returned by a generated host-action tool."""

    if not str(tool_name).startswith(_DIRECT_HOST_ACTION_PREFIX):
        return None
    try:
        parsed = json.loads(str(result or "{}"))
    except Exception:
        return None
    if parsed.get("status") != "action_requested":
        return None
    request_id = str(parsed.get("request_id") or "").strip()
    action_name = str(parsed.get("action") or "").strip()
    if not request_id or not action_name:
        return None
    params = parsed.get("params")
    return HostActionRequestPayload(
        request_id=request_id,
        action=action_name,
        params=params if isinstance(params, dict) else {},
    )


def should_wait_for_host_action_result(action: str) -> bool:
    """Return whether a host action should resume the same backend turn."""

    return str(action or "").strip() in _WAIT_FOR_RESULT_ACTIONS


def _prune_pending(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    expired = [
        request_id
        for request_id, ticket in _pending.items()
        if current - ticket.created_at > PENDING_TTL_SECONDS or ticket.future.done()
    ]
    for request_id in expired:
        _pending.pop(request_id, None)
    if len(_pending) <= MAX_PENDING_HOST_ACTION_RESULTS:
        return
    overflow = len(_pending) - MAX_PENDING_HOST_ACTION_RESULTS
    for request_id, _ticket in sorted(
        _pending.items(),
        key=lambda item: item[1].created_at,
    )[:overflow]:
        _pending.pop(request_id, None)


def register_host_action_result_request(
    *,
    request_id: str,
    action: str,
    user_id: str | None = None,
    organization_id: str | None = None,
) -> HostActionResultTicket:
    """Register a short-lived waiter for a host action result."""

    _prune_pending()
    loop = asyncio.get_running_loop()
    ticket = HostActionResultTicket(
        request_id=request_id,
        action=action,
        user_id=str(user_id).strip() if user_id else None,
        organization_id=str(organization_id).strip() if organization_id else None,
        created_at=time.monotonic(),
        future=loop.create_future(),
    )
    _pending[request_id] = ticket
    return ticket


def _same_identity(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual:
        return True
    return expected == actual


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_KEYS:
                cleaned[key_text] = "[redacted]"
            else:
                cleaned[key_text] = _redact_value(item)
        return cleaned
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def sanitize_host_action_result_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """Redact secrets before storing a result in runtime state."""

    if not isinstance(data, dict):
        return {}
    return _redact_value(data)


def build_host_action_result_payload(
    *,
    request_id: str,
    action: str,
    success: bool,
    summary: str | None = None,
    error: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a frontend host-action result into tool-loop evidence."""

    return {
        "version": HOST_ACTION_RESULT_BRIDGE_VERSION,
        "status": "action_completed" if success else "action_failed",
        "request_id": request_id,
        "action": action,
        "success": bool(success),
        "summary": str(summary or "").strip() or None,
        "error": str(error or "").strip() or None,
        "data": sanitize_host_action_result_data(data),
    }


def publish_host_action_result(
    *,
    request_id: str,
    action: str,
    success: bool,
    summary: str | None = None,
    error: str | None = None,
    data: dict[str, Any] | None = None,
    user_id: str | None = None,
    organization_id: str | None = None,
) -> HostActionResultPublication:
    """Resolve a pending host action waiter from an API submission."""

    _prune_pending()
    ticket = _pending.get(request_id)
    if ticket is None:
        return HostActionResultPublication(
            status="not_pending",
            request_id=request_id,
            action=action,
            reason="request_not_pending",
        )
    if time.monotonic() - ticket.created_at > PENDING_TTL_SECONDS:
        _pending.pop(request_id, None)
        return HostActionResultPublication(
            status="expired",
            request_id=request_id,
            action=action,
            reason="request_expired",
        )
    if ticket.action != action:
        return HostActionResultPublication(
            status="action_mismatch",
            request_id=request_id,
            action=action,
            reason="action_mismatch",
        )
    if not (
        _same_identity(ticket.user_id, user_id)
        and _same_identity(ticket.organization_id, organization_id)
    ):
        return HostActionResultPublication(
            status="identity_mismatch",
            request_id=request_id,
            action=action,
            reason="identity_mismatch",
        )

    payload = build_host_action_result_payload(
        request_id=request_id,
        action=action,
        success=success,
        summary=summary,
        error=error,
        data=data,
    )
    _pending.pop(request_id, None)
    if not ticket.future.done():
        ticket.future.get_loop().call_soon_threadsafe(ticket.future.set_result, payload)
    return HostActionResultPublication(
        status="accepted",
        request_id=request_id,
        action=action,
    )


async def wait_for_host_action_result(
    ticket: HostActionResultTicket,
    *,
    timeout_seconds: float = DEFAULT_HOST_ACTION_RESULT_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Wait for a registered host action result without cancelling the waiter."""

    try:
        return await asyncio.wait_for(asyncio.shield(ticket.future), timeout=timeout_seconds)
    except TimeoutError:
        _pending.pop(ticket.request_id, None)
        logger.info(
            "[HOST_ACTION_RESULT] Timed out waiting for %s (%s)",
            ticket.action,
            ticket.request_id,
        )
        return None


def pending_host_action_result_count() -> int:
    _prune_pending()
    return len(_pending)
