"""Semantic-memory lifecycle observers.

These hooks make post-turn memory/audit ownership visible at the runtime
lifecycle boundary without moving raw memory writes into generic hooks.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from app.engine.runtime.lifecycle import (
    HookCallable,
    HookPoint,
    HookRegistration,
    Lifecycle,
    get_lifecycle,
)
from app.engine.runtime.runtime_metrics import inc_counter

logger = logging.getLogger(__name__)

SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION = "wiii.semantic_memory_lifecycle.v1"
SEMANTIC_MEMORY_LIFECYCLE_EVENT_TYPE = "semantic_memory_lifecycle"
SEMANTIC_MEMORY_LIFECYCLE_HOOK_OWNER = "engine.semantic_memory"
_SAFE_LABEL_RE = re.compile(r"[^a-z0-9._:/-]+")


def _safe_label(value: Any, *, fallback: str = "unknown") -> str:
    label = str(value or "").strip().casefold()
    label = _SAFE_LABEL_RE.sub("_", label).strip("_")
    return (label or fallback)[:96]


def _duration_bucket(duration_ms: Any) -> str:
    if type(duration_ms) is not int or duration_ms < 0:
        return "unknown"
    if duration_ms < 1_000:
        return "lt_1s"
    if duration_ms < 5_000:
        return "1s_5s"
    if duration_ms < 30_000:
        return "5s_30s"
    return "gte_30s"


def _status_from_payload(payload: Mapping[str, Any]) -> str:
    return _safe_label(
        payload.get("status") or ("error" if payload.get("error") else "unknown")
    )


def build_semantic_memory_lifecycle_event(
    *,
    point: HookPoint,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a raw-content-free lifecycle event for post-turn memory observers."""

    status = _status_from_payload(payload)
    return {
        "schema_version": SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION,
        "lifecycle": {
            "point": point.value,
            "status": status,
            "transport": _safe_label(payload.get("transport")),
            "duration_bucket": _duration_bucket(payload.get("duration_ms")),
            "error_present": bool(payload.get("error")),
        },
        "post_turn": {
            "observer_owner": SEMANTIC_MEMORY_LIFECYCLE_HOOK_OWNER,
            "write_path": "background_runner",
            "maintenance_path": "background_runner_or_taskiq",
            "raw_user_payload_available": False,
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "session_row_scope_only",
        },
    }


def _emit_observed_metric(*, point: HookPoint, payload: Mapping[str, Any]) -> None:
    inc_counter(
        "runtime.semantic_memory.lifecycle.observed",
        labels={
            "point": point.value,
            "status": _status_from_payload(payload),
            "transport": _safe_label(payload.get("transport")),
        },
    )


def _emit_append_metric(*, point: HookPoint, status: str, reason: str) -> None:
    inc_counter(
        "runtime.semantic_memory.lifecycle.event_appends",
        labels={
            "point": point.value,
            "status": _safe_label(status),
            "reason": _safe_label(reason),
        },
    )


async def append_semantic_memory_lifecycle_event(
    *,
    point: HookPoint,
    payload: Mapping[str, Any],
) -> bool:
    """Append sanitized semantic-memory lifecycle evidence to the session log."""

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        _emit_append_metric(point=point, status="skipped", reason="missing_session_id")
        return False

    org_id_value = payload.get("org_id")
    org_id = str(org_id_value).strip() if org_id_value else None
    event_payload = build_semantic_memory_lifecycle_event(
        point=point,
        payload=payload,
    )
    try:
        from app.engine.runtime.session_event_log import get_session_event_log

        await get_session_event_log().append(
            session_id=session_id,
            event_type=SEMANTIC_MEMORY_LIFECYCLE_EVENT_TYPE,
            payload=event_payload,
            org_id=org_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Semantic memory lifecycle append skipped: %s", exc)
        _emit_append_metric(point=point, status="error", reason="append_failed")
        return False

    _emit_append_metric(point=point, status="success", reason="appended")
    return True


async def _record_semantic_memory_run_end_hook(payload: dict[str, Any]) -> None:
    _emit_observed_metric(point=HookPoint.ON_RUN_END, payload=payload)
    await append_semantic_memory_lifecycle_event(
        point=HookPoint.ON_RUN_END,
        payload=payload,
    )


async def _record_semantic_memory_run_error_hook(payload: dict[str, Any]) -> None:
    _emit_observed_metric(point=HookPoint.ON_RUN_ERROR, payload=payload)
    await append_semantic_memory_lifecycle_event(
        point=HookPoint.ON_RUN_ERROR,
        payload=payload,
    )


_SEMANTIC_MEMORY_LIFECYCLE_HOOKS: tuple[tuple[HookPoint, HookCallable], ...] = (
    (HookPoint.ON_RUN_END, _record_semantic_memory_run_end_hook),
    (HookPoint.ON_RUN_ERROR, _record_semantic_memory_run_error_hook),
)


def register_semantic_memory_lifecycle_hooks(
    lifecycle: Lifecycle | None = None,
) -> list[HookRegistration]:
    """Install semantic-memory owned lifecycle observers."""

    target = lifecycle or get_lifecycle()
    semantic_hooks = {hook for _, hook in _SEMANTIC_MEMORY_LIFECYCLE_HOOKS}
    for point, hook in _SEMANTIC_MEMORY_LIFECYCLE_HOOKS:
        target.register(point, hook, owner=SEMANTIC_MEMORY_LIFECYCLE_HOOK_OWNER)

    registrations: list[HookRegistration] = []
    for point, _ in _SEMANTIC_MEMORY_LIFECYCLE_HOOKS:
        registrations.extend(
            registration
            for registration in target.registrations_at(point)
            if registration.hook in semantic_hooks
            and registration.owner == SEMANTIC_MEMORY_LIFECYCLE_HOOK_OWNER
        )
    return registrations


__all__ = [
    "SEMANTIC_MEMORY_LIFECYCLE_EVENT_TYPE",
    "SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION",
    "SEMANTIC_MEMORY_LIFECYCLE_HOOK_OWNER",
    "append_semantic_memory_lifecycle_event",
    "build_semantic_memory_lifecycle_event",
    "register_semantic_memory_lifecycle_hooks",
]
