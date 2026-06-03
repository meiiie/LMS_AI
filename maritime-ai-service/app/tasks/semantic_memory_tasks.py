"""Broker-aware semantic memory maintenance tasks."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.runtime.runtime_metrics import inc_counter

logger = logging.getLogger(__name__)

_maintenance_task: Any | None = None
_maintenance_task_broker: Any | None = None


def _emit_maintenance_enqueue_metric(*, status: str, reason: str) -> None:
    inc_counter(
        "runtime.semantic_memory.maintenance.enqueue",
        labels={
            "status": str(status or "unknown"),
            "reason": str(reason or "unknown"),
        },
    )


def _emit_maintenance_run_metric(*, executor: str, status: str) -> None:
    inc_counter(
        "runtime.semantic_memory.maintenance.runs",
        labels={
            "executor": str(executor or "unknown"),
            "status": str(status or "unknown"),
        },
    )


async def run_semantic_memory_maintenance(
    user_id: str,
    session_id: str,
    org_id: str = "",
    semantic_memory: Any | None = None,
    executor: str = "taskiq",
) -> dict[str, Any]:
    """Run post-turn semantic memory maintenance with explicit org context.

    ``executor`` is a bounded metrics label: ``taskiq`` or ``local_fallback``.
    """

    _org_token = None
    if org_id:
        try:
            from app.core.org_context import current_org_id

            _org_token = current_org_id.set(org_id)
        except Exception:
            pass

    pruned_count = 0
    summarized = False
    try:
        try:
            from app.services.memory_lifecycle import prune_stale_memories

            pruned_count = await prune_stale_memories(
                user_id,
                session_id=session_id,
            )
        except Exception as exc:
            logger.debug("Semantic memory pruning maintenance skipped: %s", exc)

        engine = semantic_memory
        if engine is None:
            from app.engine.semantic_memory import get_semantic_memory_engine

            engine = get_semantic_memory_engine()

        available = bool(engine)
        if engine and hasattr(engine, "is_available"):
            available = engine.is_available()
            if inspect.isawaitable(available):
                available = await available
        if engine and available:
            summary = await engine.check_and_summarize(
                user_id=user_id,
                session_id=session_id,
            )
            summarized = summary is not None

        logger.debug(
            "Semantic memory maintenance completed for user_hash=%s",
            hash_memory_identifier(user_id),
        )
        _emit_maintenance_run_metric(executor=executor, status="success")
        if pruned_count > 0:
            inc_counter(
                "runtime.semantic_memory.maintenance.pruned",
                labels={"executor": str(executor or "unknown")},
                by=pruned_count,
            )
        if summarized:
            inc_counter(
                "runtime.semantic_memory.maintenance.summarized",
                labels={"executor": str(executor or "unknown")},
            )
        return {
            "success": True,
            "user_id_hash": hash_memory_identifier(user_id),
            "session_id_hash": hash_memory_identifier(session_id),
            "organization_id_hash": hash_memory_identifier(org_id),
            "pruned_count": pruned_count,
            "summarized": summarized,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to run semantic memory maintenance: %s", exc)
        _emit_maintenance_run_metric(executor=executor, status="error")
        return {
            "success": False,
            "user_id_hash": hash_memory_identifier(user_id),
            "session_id_hash": hash_memory_identifier(session_id),
            "organization_id_hash": hash_memory_identifier(org_id),
            "error": type(exc).__name__,
        }
    finally:
        if _org_token is not None:
            try:
                from app.core.org_context import current_org_id

                current_org_id.reset(_org_token)
            except Exception:
                pass


def _get_taskiq_maintenance_task() -> Any | None:
    """Return a lazily registered Taskiq task when the broker is available."""

    global _maintenance_task, _maintenance_task_broker

    try:
        from app.core.task_broker import get_broker

        broker = get_broker()
        if broker is None:
            return None
        if _maintenance_task is not None and _maintenance_task_broker is broker:
            return _maintenance_task

        register_task = getattr(broker, "task", None)
        if not callable(register_task):
            return None

        try:
            decorator = register_task(task_name="semantic_memory.maintenance")
            task = decorator(run_semantic_memory_maintenance)
        except TypeError:
            task = register_task(run_semantic_memory_maintenance)

        _maintenance_task = task
        _maintenance_task_broker = broker
        return task
    except Exception as exc:  # noqa: BLE001
        logger.debug("Semantic memory maintenance broker unavailable: %s", exc)
        return None


async def enqueue_semantic_memory_maintenance(
    *,
    user_id: str,
    session_id: str,
    org_id: str = "",
) -> bool:
    """Enqueue maintenance to Taskiq when enabled and available."""

    try:
        from app.core.config import settings

        if not settings.enable_background_tasks:
            _emit_maintenance_enqueue_metric(
                status="skipped",
                reason="disabled",
            )
            return False

        task = _get_taskiq_maintenance_task()
        enqueue = getattr(task, "kiq", None) if task is not None else None
        if not callable(enqueue):
            _emit_maintenance_enqueue_metric(
                status="skipped",
                reason="broker_unavailable",
            )
            return False

        result = enqueue(user_id=user_id, session_id=session_id, org_id=org_id)
        if inspect.isawaitable(result):
            await result
        logger.debug(
            "Enqueued semantic memory maintenance for user_hash=%s",
            hash_memory_identifier(user_id),
        )
        _emit_maintenance_enqueue_metric(status="enqueued", reason="taskiq")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic memory maintenance enqueue failed: %s", exc)
        _emit_maintenance_enqueue_metric(status="error", reason="exception")
        return False


__all__ = [
    "enqueue_semantic_memory_maintenance",
    "run_semantic_memory_maintenance",
]
