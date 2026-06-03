"""Subagent execution wrapper with timeout, retry, and fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Tuple

from app.engine.multi_agent.subagents.config import FallbackBehavior, SubagentConfig
from app.engine.multi_agent.subagents.handoff_context import (
    build_subagent_handoff_boundary_summary,
    project_kwargs_for_subagent,
    project_state_for_subagent,
)
from app.engine.multi_agent.subagents.result_boundary import (
    build_subagent_result_boundary_summary,
    sanitize_subagent_result_for_executor,
)
from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus
from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text

logger = logging.getLogger(__name__)

_PARALLEL_UNEXPECTED_ERROR_MESSAGE = "Subagent execution error"
_PARALLEL_UNSUPPORTED_RESULT_MESSAGE = "Subagent returned unsupported result"
_SUBAGENT_EXECUTION_BOUNDARY_SCHEMA_VERSION = "wiii.subagent_execution_boundary.v1"


def _safe_subagent_name(value: Any) -> str:
    name = redact_runtime_secret_text(str(value or "")[:128]).strip()
    return name or "unknown"


def _with_execution_boundary(
    *,
    raw_result: SubagentResult,
    sanitized_result: SubagentResult,
    handoff_boundary: dict[str, Any],
) -> SubagentResult:
    result_boundary = build_subagent_result_boundary_summary(
        raw_result,
        sanitized_result,
    )
    warning_codes = sorted(
        {
            *(handoff_boundary.get("warning_codes") or []),
            *(result_boundary.get("warning_codes") or []),
        }
    )
    sanitized_result.boundary = {
        "schema_version": _SUBAGENT_EXECUTION_BOUNDARY_SCHEMA_VERSION,
        "handoff": handoff_boundary,
        "result": result_boundary,
        "raw_content_included": False,
        "warning_codes": warning_codes,
    }
    return sanitized_result


async def execute_subagent(
    func: Callable,
    config: SubagentConfig,
    state: Dict[str, Any],
    **kwargs: Any,
) -> SubagentResult:
    """Execute a subagent coroutine with timeout and retry.

    Parameters
    ----------
    func:
        An ``async def`` accepting ``(state, **kwargs)`` and returning
        either a :class:`SubagentResult` or a plain ``dict``/``str``.
    config:
        Subagent-specific timeout, retry, and fallback settings.
    state:
        The current agent state (or subset thereof).

    Returns
    -------
    SubagentResult
        Always returns a result — never raises unless
        ``config.fallback_behavior == RAISE_ERROR``.
    """
    last_error: str | None = None
    start = time.monotonic()
    safe_config_name = _safe_subagent_name(config.name)
    last_handoff_boundary: dict[str, Any] = {}

    for attempt in range(config.max_retries + 1):
        attempt_start = time.monotonic()
        child_state = project_state_for_subagent(state)
        child_kwargs = project_kwargs_for_subagent(kwargs)
        last_handoff_boundary = build_subagent_handoff_boundary_summary(
            parent_state=state,
            child_state=child_state,
            parent_kwargs=kwargs,
            child_kwargs=child_kwargs,
        )
        try:
            raw = await asyncio.wait_for(
                func(child_state, **child_kwargs),
                timeout=config.timeout_seconds,
            )

            duration = int((time.monotonic() - attempt_start) * 1000)

            if isinstance(raw, SubagentResult):
                raw.duration_ms = duration
                sanitized = sanitize_subagent_result_for_executor(raw)
                return _with_execution_boundary(
                    raw_result=raw,
                    sanitized_result=sanitized,
                    handoff_boundary=last_handoff_boundary,
                )

            # Wrap a plain dict / str into a SubagentResult
            raw_result = SubagentResult(
                status=SubagentStatus.SUCCESS,
                output=str(raw) if isinstance(raw, str) else "",
                data=raw if isinstance(raw, dict) else {},
                duration_ms=duration,
            )
            sanitized = sanitize_subagent_result_for_executor(raw_result)
            return _with_execution_boundary(
                raw_result=raw_result,
                sanitized_result=sanitized,
                handoff_boundary=last_handoff_boundary,
            )

        except asyncio.TimeoutError:
            last_error = (
                f"Timeout after {config.timeout_seconds}s "
                f"(attempt {attempt + 1}/{config.max_retries + 1})"
            )
            logger.warning("Subagent %s: %s", safe_config_name, last_error)

        except Exception as _exc:
            last_error = "Subagent processing error"
            logger.error(
                "Subagent %s error (attempt %d): %s",
                safe_config_name,
                attempt + 1,
                last_error,
            )

    # All retries exhausted -----------------------------------------------
    total_duration = int((time.monotonic() - start) * 1000)

    if config.fallback_behavior == FallbackBehavior.RAISE_ERROR:
        raise RuntimeError(f"Subagent {safe_config_name} failed: {last_error}")

    is_timeout = last_error is not None and "Timeout" in last_error
    raw_result = SubagentResult(
        status=SubagentStatus.TIMEOUT if is_timeout else SubagentStatus.ERROR,
        error_message=last_error,
        duration_ms=total_duration,
    )
    sanitized = sanitize_subagent_result_for_executor(raw_result)
    return _with_execution_boundary(
        raw_result=raw_result,
        sanitized_result=sanitized,
        handoff_boundary=last_handoff_boundary,
    )


async def execute_parallel_subagents(
    tasks: List[Tuple[Callable, SubagentConfig, Dict[str, Any], Dict[str, Any]]],
    max_concurrent: int = 5,
) -> List[SubagentResult]:
    """Execute multiple subagent tasks in parallel.

    Parameters
    ----------
    tasks:
        A list of ``(func, config, state, kwargs)`` tuples.
    max_concurrent:
        Concurrency limit (semaphore).

    Returns
    -------
    list[SubagentResult]
        One result per input task, in the same order.  Exceptions inside
        individual tasks are caught and returned as ``SubagentResult``
        with ``status=ERROR``.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _guarded(
        func: Callable,
        config: SubagentConfig,
        state: Dict[str, Any],
        kwargs: Dict[str, Any],
    ) -> SubagentResult:
        async with semaphore:
            return await execute_subagent(func, config, state, **kwargs)

    coros = [_guarded(f, c, s, kw) for f, c, s, kw in tasks]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    # Ensure every entry is a SubagentResult (wrap unexpected exceptions)
    results: List[SubagentResult] = []
    for task, r in zip(tasks, raw_results):
        _, config, _, _ = task
        if isinstance(r, SubagentResult):
            results.append(sanitize_subagent_result_for_executor(r))
        elif isinstance(r, Exception):
            logger.error(
                "Subagent %s failed outside guarded execution: %s",
                _safe_subagent_name(config.name),
                type(r).__name__,
            )
            results.append(
                sanitize_subagent_result_for_executor(SubagentResult(
                    status=SubagentStatus.ERROR,
                    error_message=_PARALLEL_UNEXPECTED_ERROR_MESSAGE,
                ))
            )
        else:
            logger.error(
                "Subagent %s returned unsupported parallel result type: %s",
                _safe_subagent_name(config.name),
                type(r).__name__,
            )
            results.append(
                sanitize_subagent_result_for_executor(SubagentResult(
                    status=SubagentStatus.ERROR,
                    error_message=_PARALLEL_UNSUPPORTED_RESULT_MESSAGE,
                ))
            )
    return results
