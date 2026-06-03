"""Lifecycle hooks — formalised attach points for the runtime.

Phase 27 of the runtime migration epic (issue #207). Phase 25 shipped
the run-state machine; Phase 13/24 the metrics + tracing façades.
This module ties them together: a single ``Lifecycle`` registry where
extensions register hooks at named points, fired by the dispatcher /
SubagentRunner / native_dispatch when events of interest occur.

Hook points (named after the openai-agents-python convention):

- ``on_run_start`` — chat run begins, before any provider call.
- ``on_run_end`` — chat run completes (success or final failure).
- ``on_run_error`` — exception raised mid-run, BEFORE retry decision.
- ``on_tool_start`` — about to dispatch a tool call (after guardrails).
- ``on_tool_end`` — tool returned (success or error).
- ``on_subagent_start`` — SubagentRunner spawned a child.
- ``on_subagent_end`` — child returned, parent has the SubagentResult.

Design points:
- **Async hooks**. Hooks may want to write to the durable session log,
  forward telemetry, etc. Sync would force them to use threads.
- **Faulty hook does not break the request**. Each hook runs inside
  its own try/except; exceptions are logged at debug, never raised.
- **Order of registration is preserved** but two hooks at the same
  point are independent — one's failure doesn't skip the other.
- **Idempotent registration** — adding the same hook twice no-ops.
- **Per-hook-point unregister** keeps the registry tidy.

Out of scope today:
- Hook priority ordering — registration order is good enough.
- Conditional hooks (fire only for org X) — hooks themselves can
  filter on context; no need to bake it in.
- Persistent hook state — hooks are stateless or own their own state.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable, Optional

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload
from app.engine.runtime.runtime_metrics import inc_counter

logger = logging.getLogger(__name__)
LIFECYCLE_REGISTRATION_REPORT_VERSION = "wiii.runtime_lifecycle_registrations.v1"
_HOOK_OWNER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DEFAULT_RUNTIME_HOOK_OWNER = "engine.runtime"


class HookPoint(StrEnum):
    """Named events the runtime fires at."""

    ON_RUN_START = "on_run_start"
    ON_RUN_END = "on_run_end"
    ON_RUN_ERROR = "on_run_error"
    ON_TOOL_START = "on_tool_start"
    ON_TOOL_END = "on_tool_end"
    ON_SUBAGENT_START = "on_subagent_start"
    ON_SUBAGENT_END = "on_subagent_end"


HookCallable = Callable[[dict], Awaitable[None]]
"""Hook signature: receives a single ``payload`` dict, returns nothing.

Payloads are documented per hook point at the call site (the
dispatcher); the registry doesn't validate shape because that would
slow the hot path. Hooks should treat the payload as read-only.
"""


@dataclass(frozen=True, slots=True)
class HookRegistration:
    """Metadata for one registered lifecycle hook."""

    hook: HookCallable
    owner: str
    name: str
    module: str


def _infer_hook_owner(hook: HookCallable) -> str:
    """Return a bounded subsystem label for hook-failure metrics."""

    module = str(getattr(hook, "__module__", "") or "")
    if module.startswith("app.engine."):
        parts = module.split(".")
        return f"engine.{parts[2]}" if len(parts) > 2 else "engine"
    if module.startswith("app.services."):
        return "services"
    if module.startswith("app.api."):
        return "api"
    if module.startswith("app.repositories."):
        return "repositories"
    if module.startswith("app."):
        parts = module.split(".")
        return parts[1] if len(parts) > 1 else "app"
    if module.startswith("tests.") or module.startswith("test_"):
        return "tests"
    return "external"


def _normalize_hook_owner(owner: str | None, hook: HookCallable) -> str:
    candidate = str(owner or "").strip().casefold()
    if candidate and _HOOK_OWNER_RE.fullmatch(candidate):
        return candidate
    inferred = _infer_hook_owner(hook)
    if _HOOK_OWNER_RE.fullmatch(inferred):
        return inferred
    return "external"


def _normalize_metric_label(value: Any, *, fallback: str = "unknown") -> str:
    candidate = str(value or "").strip().casefold()
    candidate = re.sub(r"[^a-z0-9._-]+", "_", candidate).strip("_")
    if not candidate:
        return fallback
    return candidate[:64]


def _hook_registration(
    hook: HookCallable,
    *,
    owner: str | None = None,
) -> HookRegistration:
    return HookRegistration(
        hook=hook,
        owner=_normalize_hook_owner(owner, hook),
        name=str(getattr(hook, "__name__", hook.__class__.__name__) or "hook"),
        module=str(getattr(hook, "__module__", "") or ""),
    )


class Lifecycle:
    """Registry of async hooks attached to ``HookPoint`` events."""

    def __init__(self) -> None:
        self._hooks: dict[HookPoint, list[HookRegistration]] = {
            point: [] for point in HookPoint
        }

    def register(
        self,
        point: HookPoint,
        hook: HookCallable,
        *,
        owner: str | None = None,
    ) -> None:
        """Add ``hook`` at ``point``. No-op if already registered."""
        bucket = self._hooks[point]
        if not any(registration.hook == hook for registration in bucket):
            bucket.append(_hook_registration(hook, owner=owner))

    def unregister(self, point: HookPoint, hook: HookCallable) -> bool:
        """Remove ``hook`` at ``point``. Returns True if anything was removed."""
        bucket = self._hooks[point]
        for index, registration in enumerate(bucket):
            if registration.hook == hook:
                del bucket[index]
                return True
        return False

    def hooks_at(self, point: HookPoint) -> list[HookCallable]:
        """Return a copy of the hooks registered at ``point``."""
        return [registration.hook for registration in self._hooks[point]]

    def registrations_at(self, point: HookPoint) -> list[HookRegistration]:
        """Return a copy of hook registrations with explicit owner metadata."""

        return list(self._hooks[point])

    @staticmethod
    def sanitize_payload(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Return the hook-safe payload shape delivered to lifecycle hooks."""

        safe_payload = sanitize_runtime_payload(payload or {})
        return dict(safe_payload) if isinstance(safe_payload, dict) else {}

    async def fire(
        self, point: HookPoint, payload: Optional[dict[str, Any]] = None
    ) -> None:
        """Run every hook registered at ``point`` with ``payload``.

        Each hook runs in its own try/except so one bad hook cannot
        break the dispatcher. Hook exceptions are logged at debug —
        the request continues. If the dispatcher needs to KNOW a hook
        failed, register a wrapper that tracks success itself.
        """
        bucket = self._hooks[point]
        if not bucket:
            return
        data = self.sanitize_payload(payload)
        for registration in list(bucket):
            try:
                await registration.hook(data)
            except Exception as exc:  # noqa: BLE001
                inc_counter(
                    "runtime.lifecycle.hook_failures",
                    labels={
                        "owner": registration.owner,
                        "point": point.value,
                    },
                )
                logger.debug(
                    "[lifecycle] hook %s at %s raised: %s",
                    registration.name,
                    point.value,
                    exc,
                )

    def reset(self) -> None:
        """Drop every registered hook. Tests + reload only."""
        for bucket in self._hooks.values():
            bucket.clear()


_lifecycle = Lifecycle()


def get_lifecycle() -> Lifecycle:
    """Return the process-global ``Lifecycle`` registry."""
    return _lifecycle


def _record_lifecycle_hook_run(point: HookPoint, payload: dict[str, Any]) -> None:
    status = payload.get("status") or ("error" if payload.get("error") else "unknown")
    inc_counter(
        "runtime.lifecycle.hook_runs",
        labels={
            "owner": _DEFAULT_RUNTIME_HOOK_OWNER,
            "point": point.value,
            "status": _normalize_metric_label(status),
        },
    )


async def _record_run_end_hook(payload: dict[str, Any]) -> None:
    _record_lifecycle_hook_run(HookPoint.ON_RUN_END, payload)


async def _record_run_error_hook(payload: dict[str, Any]) -> None:
    _record_lifecycle_hook_run(HookPoint.ON_RUN_ERROR, payload)


_DEFAULT_RUNTIME_HOOKS: tuple[tuple[HookPoint, HookCallable], ...] = (
    (HookPoint.ON_RUN_END, _record_run_end_hook),
    (HookPoint.ON_RUN_ERROR, _record_run_error_hook),
)


def register_default_lifecycle_hooks(
    lifecycle: Lifecycle | None = None,
) -> list[HookRegistration]:
    """Install Wiii-owned lifecycle hooks used in production startup."""

    target = lifecycle or get_lifecycle()
    default_hooks = {hook for _, hook in _DEFAULT_RUNTIME_HOOKS}
    for point, hook in _DEFAULT_RUNTIME_HOOKS:
        target.register(point, hook, owner=_DEFAULT_RUNTIME_HOOK_OWNER)

    registrations: list[HookRegistration] = []
    for point, _ in _DEFAULT_RUNTIME_HOOKS:
        registrations.extend(
            registration
            for registration in target.registrations_at(point)
            if registration.hook in default_hooks
            and registration.owner == _DEFAULT_RUNTIME_HOOK_OWNER
        )
    return registrations


def build_lifecycle_registration_report(
    lifecycle: Lifecycle | None = None,
) -> dict[str, Any]:
    """Return aggregate, privacy-safe metadata about registered hooks."""

    target = lifecycle or get_lifecycle()
    owner_counts: Counter[str] = Counter()
    point_counts: dict[str, int] = {}
    registrations: list[dict[str, str]] = []

    for point in HookPoint:
        point_registrations = target.registrations_at(point)
        point_counts[point.value] = len(point_registrations)
        for registration in point_registrations:
            owner_counts[registration.owner] += 1
            registrations.append(
                {
                    "point": point.value,
                    "owner": registration.owner,
                    "name": registration.name,
                }
            )

    default_hooks: list[dict[str, Any]] = []
    for point, hook in _DEFAULT_RUNTIME_HOOKS:
        registered = any(
            registration.hook == hook
            and registration.owner == _DEFAULT_RUNTIME_HOOK_OWNER
            for registration in target.registrations_at(point)
        )
        default_hooks.append(
            {
                "point": point.value,
                "owner": _DEFAULT_RUNTIME_HOOK_OWNER,
                "name": str(getattr(hook, "__name__", "hook") or "hook"),
                "registered": registered,
            }
        )

    registered_default_count = sum(
        1 for default_hook in default_hooks if default_hook["registered"]
    )
    return {
        "version": LIFECYCLE_REGISTRATION_REPORT_VERSION,
        "registration_count": len(registrations),
        "owner_counts": dict(owner_counts.most_common()),
        "point_counts": point_counts,
        "registrations": registrations,
        "default_runtime_hooks": {
            "owner": _DEFAULT_RUNTIME_HOOK_OWNER,
            "required_count": len(default_hooks),
            "registered_count": registered_default_count,
            "installed": registered_default_count == len(default_hooks),
            "hooks": default_hooks,
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "code_metadata_only",
        },
    }


def _reset_for_tests() -> None:
    """Clear every hook on the singleton — test fixtures only."""
    _lifecycle.reset()


__all__ = [
    "HookPoint",
    "HookCallable",
    "HookRegistration",
    "LIFECYCLE_REGISTRATION_REPORT_VERSION",
    "Lifecycle",
    "build_lifecycle_registration_report",
    "get_lifecycle",
    "register_default_lifecycle_hooks",
]
