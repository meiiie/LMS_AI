"""Run-state machine for chat dispatch.

Phase 25 of the runtime migration epic (issue #207). The legacy chat
path goes ``request → orchestrator.process → response`` as a flat call;
``native_chat_dispatch`` (Phase 19) added durable logging + metrics +
tracing around it but keeps the same flat shape. That's fine for a
single-shot turn, but it leaves three things implicit:

1. **State transitions.** A run goes through several stages even today
   (received → processing → completing → done/error), but nothing in
   the code names them. Debugging "stuck at processing" is impossible
   when the state isn't observable.
2. **Retry policy.** Provider 5xx → retry sometimes makes sense (rate
   limit), other times not (4xx invalid request). Today this is
   scattered across ``LLMPool`` + ``WiiiChatModel`` + scattered try/
   except blocks.
3. **Hook points.** Phase 27 (lifecycle hooks) needs explicit attach
   points; without a state machine the hooks have nowhere to register.

This module ships the explicit state machine. ``RunStateMachine``
manages a run from PENDING through to SUCCEEDED/FAILED with named
transitions, retry hooks, and a structured snapshot at every step.

Out of scope today:
- Orchestrator refactor — native_chat_dispatch and ChatOrchestrator
  stay as-is. They can opt into the state machine in a follow-up
  phase when retry policy or lifecycle hooks need to be enforced.
- Distributed runs — single-process today. When the runtime spans
  workers, ``RunStateMachine`` becomes a Postgres-backed entity.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Optional

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)

logger = logging.getLogger(__name__)


class RunState(StrEnum):
    """Lifecycle states a single chat run goes through."""

    PENDING = "pending"
    """Request received but not yet picked up."""

    DISPATCHING = "dispatching"
    """Routing decision made, about to call the inner runtime."""

    RUNNING = "running"
    """Inner runtime executing (LLM call, tool calls, RAG, etc.)."""

    COMPLETING = "completing"
    """Inner runtime returned; finalising response shape, writing logs."""

    SUCCEEDED = "succeeded"
    """Terminal: clean response delivered to caller."""

    FAILED = "failed"
    """Terminal: irrecoverable error after retries exhausted."""

    RETRYING = "retrying"
    """Transient failure observed; about to re-enter DISPATCHING."""


_VALID_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.DISPATCHING, RunState.FAILED}),
    RunState.DISPATCHING: frozenset(
        {RunState.RUNNING, RunState.RETRYING, RunState.FAILED}
    ),
    RunState.RUNNING: frozenset(
        {RunState.COMPLETING, RunState.RETRYING, RunState.FAILED}
    ),
    RunState.COMPLETING: frozenset({RunState.SUCCEEDED, RunState.FAILED}),
    RunState.RETRYING: frozenset({RunState.DISPATCHING, RunState.FAILED}),
    RunState.SUCCEEDED: frozenset(),  # terminal
    RunState.FAILED: frozenset(),  # terminal
}


class IllegalTransitionError(RuntimeError):
    """Raised when ``transition_to`` is called with an unreachable state."""


@dataclass(slots=True)
class RunSnapshot:
    """Frozen-at-a-point view of a run's progress, for telemetry / log."""

    run_id: str
    state: RunState
    attempt: int
    started_at: float
    last_transition_at: float
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRetryPolicy:
    """How many transient retries before failing the run."""

    max_attempts: int = 3
    """Total attempts including the first. ``max_attempts=1`` disables retry."""

    backoff_base_seconds: float = 0.5
    """First retry waits this long; subsequent retries multiply by 2."""

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def backoff_for(self, attempt: int) -> float:
        # Exponential backoff: attempt 1 → base, 2 → 2*base, 3 → 4*base.
        return self.backoff_base_seconds * (2 ** max(0, attempt - 1))


# ── transition listener ──

TransitionListener = Callable[[RunState, RunState, "RunStateMachine"], Awaitable[None]]


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


class RunStateMachine:
    """Tracks a single chat run through its lifecycle.

    Usage::

        sm = RunStateMachine(retry_policy=RunRetryPolicy(max_attempts=3))
        await sm.transition_to(RunState.DISPATCHING)
        try:
            response = await dispatcher(request)
            await sm.transition_to(RunState.RUNNING)
            ...
            await sm.transition_to(RunState.COMPLETING)
            await sm.transition_to(RunState.SUCCEEDED)
        except TransientError:
            if sm.retry_policy.should_retry(sm.attempt):
                await sm.transition_to(RunState.RETRYING)
                ...
            else:
                await sm.transition_to(RunState.FAILED, error=str(e))

    Listeners receive ``(prev, next, machine)`` on every transition.
    Phase 27 lifecycle hooks register here. Listener exceptions are
    logged but never block the transition itself.
    """

    def __init__(
        self,
        *,
        run_id: Optional[str] = None,
        retry_policy: Optional[RunRetryPolicy] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:16]}"
        self.retry_policy = retry_policy or RunRetryPolicy()
        self.metadata: dict[str, Any] = _safe_metadata(metadata)
        self._state = RunState.PENDING
        self._attempt = 1
        self._error: Optional[str] = None
        self._started_at = time.monotonic()
        self._last_transition_at = self._started_at
        self._listeners: list[TransitionListener] = []
        self._lock = asyncio.Lock()

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def is_terminal(self) -> bool:
        return self._state in (RunState.SUCCEEDED, RunState.FAILED)

    def add_listener(self, listener: TransitionListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: TransitionListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    async def transition_to(
        self,
        target: RunState,
        *,
        error: Optional[str] = None,
    ) -> None:
        """Move the run to ``target`` if the transition is legal.

        Side effects (in order):
        1. Update ``_state``, ``_attempt`` (RETRYING bumps it),
           ``_error``, ``_last_transition_at``.
        2. Fire every registered listener with ``(prev, target, self)``.
        3. Listener exceptions are logged at debug; they never block.

        Concurrency: a single asyncio.Lock guards the whole step so two
        concurrent transitions cannot interleave the listener fan-out.
        """
        async with self._lock:
            prev = self._state
            allowed = _VALID_TRANSITIONS.get(prev, frozenset())
            if target not in allowed:
                raise IllegalTransitionError(
                    f"cannot transition {prev.value} → {target.value}"
                )

            self._state = target
            self._last_transition_at = time.monotonic()
            if error:
                self._error = redact_runtime_secret_text(error)
            if target == RunState.RETRYING:
                self._attempt += 1
                # Clear the error string when we're going back into the
                # retry loop — the next attempt is fresh.
                self._error = None

            for listener in list(self._listeners):
                try:
                    await listener(prev, target, self)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "[RunStateMachine] listener %s raised: %s",
                        listener.__name__ if hasattr(listener, "__name__") else "?",
                        exc,
                    )

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            run_id=self.run_id,
            state=self._state,
            attempt=self._attempt,
            started_at=self._started_at,
            last_transition_at=self._last_transition_at,
            error=self._error,
            metadata=_safe_metadata(self.metadata),
        )


__all__ = [
    "RunState",
    "RunSnapshot",
    "RunRetryPolicy",
    "RunStateMachine",
    "IllegalTransitionError",
]
