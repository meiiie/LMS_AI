"""
Scheduled Task Executor — Periodic poll loop for proactive agent tasks.

Sprint 20: Proactive Agent Activation.
Polls the scheduled_tasks table at configured intervals, executes due tasks
(notification or agent-invoke mode), and delivers results via NotificationDispatcher.

Uses asyncio.Task — no external worker dependencies (Taskiq/Celery).
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.engine.runtime.runtime_metrics import inc_counter, record_latency_ms

logger = logging.getLogger(__name__)


_TASK_MODE_LABELS = {"agent", "notification"}


def _task_mode_label(task: dict) -> str:
    extra = task.get("extra_data") or {}
    if isinstance(extra, dict) and extra.get("agent_invoke"):
        return "agent"
    return "notification"


def _result_mode_label(value: object, *, fallback: str) -> str:
    mode = str(value or fallback).strip().lower()
    return mode if mode in _TASK_MODE_LABELS else "unknown"


def _emit_poll_metric(status: str) -> None:
    inc_counter("runtime.scheduled_tasks.polls", labels={"status": status})


def _emit_due_metric(count: int) -> None:
    if count > 0:
        inc_counter("runtime.scheduled_tasks.due", by=count)


def _emit_task_run_metric(
    *,
    mode: str,
    status: str,
    started_ns: int,
) -> None:
    labels = {"mode": mode, "status": status}
    inc_counter("runtime.scheduled_tasks.runs", labels=labels)
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
    record_latency_ms("runtime.scheduled_tasks.duration_ms", elapsed_ms, labels=labels)


def _emit_delivery_metric(*, mode: str, delivered: bool) -> None:
    inc_counter(
        "runtime.scheduled_tasks.delivery",
        labels={
            "mode": mode,
            "status": "delivered" if delivered else "not_delivered",
        },
    )


class ScheduledTaskExecutor:
    """
    Periodic executor for scheduled tasks.

    Polls get_due_tasks() every scheduler_poll_interval seconds,
    executes tasks concurrently (up to scheduler_max_concurrent),
    and delivers results to users via NotificationDispatcher.
    """

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the periodic poll loop as a background asyncio task."""
        if self._running:
            logger.warning("[EXECUTOR] Already running, skipping start")
            return

        self._shutdown_event.clear()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[EXECUTOR] Scheduled task executor started")

    async def _poll_loop(self) -> None:
        """Main loop: poll for due tasks, execute, then wait for interval."""
        from app.core.config import settings

        while not self._shutdown_event.is_set():
            try:
                await self._execute_due_tasks()
            except Exception as e:
                logger.error("[EXECUTOR] Poll error: %s", e, exc_info=True)

            # Wait for interval or shutdown signal
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=settings.scheduler_poll_interval,
                )
                break  # Shutdown signalled
            except asyncio.TimeoutError:
                pass  # Interval elapsed, continue polling

        self._running = False
        logger.info("[EXECUTOR] Poll loop exited")

    async def _execute_due_tasks(self) -> None:
        """Fetch and execute all due tasks up to max_concurrent."""
        from app.core.config import settings
        from app.repositories.scheduler_repository import get_scheduler_repository
        from app.services.notification_dispatcher import get_notification_dispatcher

        try:
            repo = get_scheduler_repository()
            dispatcher = get_notification_dispatcher()
            due_tasks = repo.get_due_tasks(
                limit=settings.scheduler_max_concurrent,
                allow_all_orgs=True,
            )
        except Exception:
            _emit_poll_metric("error")
            raise

        _emit_poll_metric("success")
        _emit_due_metric(len(due_tasks))
        if not due_tasks:
            return

        logger.info("[EXECUTOR] Found %d due task(s)", len(due_tasks))

        for task in due_tasks:
            await self._execute_due_task_with_observability(
                task,
                repo=repo,
                dispatcher=dispatcher,
            )

    async def _execute_due_task_with_observability(
        self,
        task: dict,
        *,
        repo,
        dispatcher,
    ) -> dict:
        """Execute one due task through the worker side-effect pipeline."""
        task_id_short = task["id"][:8] if task.get("id") else "unknown"
        mode_label = _task_mode_label(task)
        started_ns = time.perf_counter_ns()
        try:
            result = await self._execute_single_task(task)
            mode_label = _result_mode_label(
                result.get("mode"),
                fallback=mode_label,
            )

            # Notify user
            delivery = await dispatcher.notify_task_result(task, result)
            _emit_delivery_metric(
                mode=mode_label,
                delivered=isinstance(delivery, dict)
                and delivery.get("delivered") is True,
            )
            logger.info(
                "[EXECUTOR] Task %s completed: "
                "mode=%s, delivered=%s",
                task_id_short, result.get('mode'), delivery.get('delivered'),
            )

            # Mark executed and calculate next_run for recurring
            next_run = (
                self._calculate_next_run(task)
                if task.get("schedule_type") != "once"
                else None
            )
            repo.mark_executed(
                task["id"],
                next_run=next_run,
                organization_id=task.get("organization_id"),
            )
            _emit_task_run_metric(
                mode=mode_label,
                status="success",
                started_ns=started_ns,
            )
            return {
                "status": "success",
                "mode": mode_label,
                "result": result,
                "delivery": delivery,
                "next_run": next_run.isoformat() if next_run else None,
            }

        except asyncio.TimeoutError:
            logger.error("[EXECUTOR] Task %s timed out", task_id_short)
            _emit_task_run_metric(
                mode=mode_label,
                status="timeout",
                started_ns=started_ns,
            )
            repo.mark_failed(
                task["id"],
                "timeout",
                organization_id=task.get("organization_id"),
            )
            return {
                "status": "timeout",
                "mode": mode_label,
                "result": None,
                "delivery": None,
                "error_type": "timeout",
            }
        except Exception as e:
            logger.error(
                "[EXECUTOR] Task %s execution failed: %s",
                task_id_short, e,
                exc_info=True,
            )
            _emit_task_run_metric(
                mode=mode_label,
                status="error",
                started_ns=started_ns,
            )
            repo.mark_failed(
                task["id"],
                str(e)[:200],
                organization_id=task.get("organization_id"),
            )
            return {
                "status": "error",
                "mode": mode_label,
                "result": None,
                "delivery": None,
                "error_type": type(e).__name__,
            }

    async def _execute_single_task(self, task: dict) -> dict:
        """
        Execute a single scheduled task.

        Two modes:
        - agent_invoke: Run through the multi-agent graph
        - notification (default): Just send the description as a reminder
        """
        from app.core.config import settings

        extra = task.get("extra_data") or {}

        if extra.get("agent_invoke"):
            # Agent mode: invoke the WiiiRunner-backed multi-agent runtime.
            from app.engine.multi_agent.runtime import run_wiii_turn
            from app.engine.multi_agent.runtime_contracts import (
                WiiiRunContext,
                WiiiTurnRequest,
            )

            turn_result = await asyncio.wait_for(
                run_wiii_turn(
                    WiiiTurnRequest(
                        query=task["description"],
                        run_context=WiiiRunContext(
                            user_id=task["user_id"],
                            session_id=f"scheduled_{task['id'][:8]}",
                            domain_id=task.get("domain_id", "maritime"),
                            organization_id=task.get("organization_id"),
                        ),
                    )
                ),
                timeout=settings.scheduler_agent_timeout,
            )
            result = turn_result.payload
            return {
                "mode": "agent",
                "response": result.get("response", ""),
            }
        else:
            # Notification mode (default): send description as reminder
            return {
                "mode": "notification",
                "response": task["description"],
            }

    @staticmethod
    def _calculate_next_run(task: dict) -> Optional[datetime]:
        """
        Calculate next_run for recurring tasks.

        For "recurring": parse interval from schedule_expr (e.g., "1h", "30m", "1d"),
        add to current time.
        For "cron": not yet supported, returns None (marks as completed).
        """
        schedule_type = task.get("schedule_type", "once")
        schedule_expr = task.get("schedule_expr", "")

        if schedule_type == "recurring" and schedule_expr:
            delta = _parse_interval(schedule_expr)
            if delta:
                return datetime.now(timezone.utc) + delta

        # Unknown type or unparseable expr → complete the task
        return None

    async def shutdown(self, timeout: float = 10) -> None:
        """Signal shutdown and wait for the poll loop to finish."""
        if not self._running:
            return

        logger.info("[EXECUTOR] Shutdown requested")
        self._shutdown_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
                logger.warning("[EXECUTOR] Forced cancel after timeout")

        self._running = False
        logger.info("[EXECUTOR] Shutdown complete")


def _parse_interval(expr: str) -> Optional[timedelta]:
    """
    Parse a human-readable interval string into a timedelta.

    Supported formats: "30m", "1h", "2d", "90s", "1h30m"
    """
    import re

    total = timedelta()
    pattern = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
    matches = pattern.findall(expr)

    if not matches:
        return None

    for value, unit in matches:
        v = int(value)
        if unit in ("s", "S"):
            total += timedelta(seconds=v)
        elif unit in ("m", "M"):
            total += timedelta(minutes=v)
        elif unit in ("h", "H"):
            total += timedelta(hours=v)
        elif unit in ("d", "D"):
            total += timedelta(days=v)

    return total if total > timedelta() else None


# =============================================================================
# Singleton
# =============================================================================

_executor: Optional[ScheduledTaskExecutor] = None


def get_scheduled_task_executor() -> ScheduledTaskExecutor:
    """Get or create the ScheduledTaskExecutor singleton."""
    global _executor
    if _executor is None:
        _executor = ScheduledTaskExecutor()
    return _executor
