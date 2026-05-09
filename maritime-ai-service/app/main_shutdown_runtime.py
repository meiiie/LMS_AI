"""Shutdown runtime helpers for the FastAPI application."""

from __future__ import annotations

import asyncio
import logging
from importlib import import_module

from app.core.config import settings
from app.main_runtime_contracts import AppRuntimeResources


def _load_attr(module_name: str, attr_name: str):
    """Resolve a shutdown dependency lazily at the application boundary."""
    return getattr(import_module(module_name), attr_name)


def _close_neo4j(resources: AppRuntimeResources, logger_: logging.Logger) -> None:
    if resources.neo4j_repo is None:
        return
    try:
        resources.neo4j_repo.close()
        logger_.info("[OK] Neo4j driver closed successfully")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.error("[FAIL] Failed to close Neo4j driver: %s", exc)


async def _stop_scheduled_executor(resources: AppRuntimeResources, logger_: logging.Logger) -> None:
    if resources.scheduled_executor is None:
        return
    try:
        await resources.scheduled_executor.shutdown(timeout=10)
        logger_.info("Scheduled task executor stopped")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Executor shutdown failed: %s", exc)


async def _cancel_background_task(
    task_name: str, task: asyncio.Task | None, logger_: logging.Logger
) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger_.info("%s task cancelled", task_name)
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("%s shutdown failed: %s", task_name, exc)


async def _stop_heartbeat(resources: AppRuntimeResources, logger_: logging.Logger) -> None:
    if resources.heartbeat is None:
        return
    try:
        await resources.heartbeat.stop()
        logger_.info("Living Agent heartbeat stopped")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Heartbeat shutdown failed: %s", exc)


async def _persist_emotion_state(logger_: logging.Logger) -> None:
    if not settings.enable_living_agent:
        return
    try:
        get_emotion_engine = _load_attr(
            "app.engine.living_agent.emotion_engine",
            "get_emotion_engine",
        )

        await get_emotion_engine().save_state_to_db()
        logger_.info("Emotion state persisted on shutdown")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Emotion persist on shutdown failed: %s", exc)


async def _stop_soul_bridge(resources: AppRuntimeResources, logger_: logging.Logger) -> None:
    if resources.soul_bridge is None:
        return
    try:
        await resources.soul_bridge.shutdown()
        logger_.info("SoulBridge stopped")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("SoulBridge shutdown failed: %s", exc)


async def _shutdown_mcp_client(logger_: logging.Logger) -> None:
    if not settings.enable_mcp_client:
        return
    try:
        MCPToolManager = _load_attr("app.mcp.client", "MCPToolManager")

        await MCPToolManager.shutdown()
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("MCP Client shutdown failed: %s", exc)


async def _close_magic_link_session_store(logger_: logging.Logger) -> None:
    """Cancel any in-flight Valkey subscriber tasks and close the Valkey client.

    Issue #106 — without this, ValkeySessionStore relies on event-loop close
    to terminate per-session subscriber tasks, which can leak pubsub
    subscriptions and Valkey connections. Idempotent and never raises.
    """
    try:
        get_session_store = _load_attr(
            "app.auth.magic_link_session_store", "get_session_store"
        )
        store = get_session_store()
        if store is None:
            return
        await store.aclose()
        logger_.info("Magic link session store closed cleanly")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Magic link session store close failed: %s", exc)


async def _close_sources_pool(logger_: logging.Logger) -> None:
    try:
        close_pool = _load_attr("app.api.v1.sources", "close_pool")

        await close_pool()
    except Exception as exc:  # pragma: no cover - logging path
        logger_.warning("Sources pool close failed: %s", exc)


async def _close_course_generation_pool(logger_: logging.Logger) -> None:
    try:
        get_course_gen_repo = _load_attr(
            "app.repositories.course_generation_repository",
            "get_course_gen_repo",
        )

        await get_course_gen_repo().close()
        logger_.info("Course generation pool closed")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.debug("Course generation pool close skipped: %s", exc)


async def _close_search_pools(logger_: logging.Logger) -> None:
    try:
        get_dense_search_repository = _load_attr(
            "app.repositories.dense_search_repository",
            "get_dense_search_repository",
        )

        await get_dense_search_repository().close()
        logger_.info("Dense search pool closed")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.debug("Dense search pool close skipped: %s", exc)
    try:
        get_sparse_search_repository = _load_attr(
            "app.repositories.sparse_search_repository",
            "get_sparse_search_repository",
        )

        await get_sparse_search_repository().close()
        logger_.info("Sparse search pool closed")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.debug("Sparse search pool close skipped: %s", exc)


def _close_playwright_browser(logger_: logging.Logger) -> None:
    try:
        close_browser = _load_attr(
            "app.engine.search_platforms.adapters.browser_base",
            "close_browser",
        )

        close_browser()
        logger_.info("Playwright browser closed")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.debug("Browser close skipped: %s", exc)


def _close_shared_database_engine(logger_: logging.Logger) -> None:
    try:
        close_shared_engine = _load_attr("app.core.database", "close_shared_engine")

        close_shared_engine()
        logger_.info("Shared database engine closed successfully")
    except Exception as exc:  # pragma: no cover - logging path
        logger_.error("Failed to close shared database engine: %s", exc)


async def shutdown_application(resources: AppRuntimeResources, logger_: logging.Logger) -> None:
    """Run shutdown sequence for collected startup resources."""

    logger_.info("Shutting down %s...", settings.app_name)
    _close_neo4j(resources, logger_)
    await _stop_scheduled_executor(resources, logger_)
    await _cancel_background_task(
        "runtime audit refresh", resources.runtime_audit_task, logger_
    )
    await _cancel_background_task(
        "runtime audit loop", resources.runtime_audit_loop_task, logger_
    )
    await _cancel_background_task(
        "model health probe", resources.model_health_probe_task, logger_
    )
    await _cancel_background_task(
        "model health probe loop", resources.model_health_probe_loop_task, logger_
    )
    await _cancel_background_task(
        "magic link cleanup", resources.magic_link_cleanup_task, logger_
    )
    await _cancel_background_task(
        "magic link session reaper", resources.magic_link_reaper_task, logger_
    )
    await _close_magic_link_session_store(logger_)
    await _stop_heartbeat(resources, logger_)
    await _persist_emotion_state(logger_)
    await _stop_soul_bridge(resources, logger_)
    await _shutdown_mcp_client(logger_)
    await _close_sources_pool(logger_)
    await _close_course_generation_pool(logger_)
    await _close_search_pools(logger_)
    _close_playwright_browser(logger_)
    _close_shared_database_engine(logger_)
    logger_.info("[SHUTDOWN] %s shutdown complete", settings.app_name)
