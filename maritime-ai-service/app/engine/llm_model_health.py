"""In-memory per-provider/model health state for LLM routing.

This is intentionally process-local. Persistent provider audit remains the
source of truth for admin UI/history, while this module protects the hot path:
when a concrete model times out or rate-limits, the next request can avoid that
model immediately without waiting for a full provider-level probe cycle.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_DEGRADED_TTL_SECONDS = 300.0
_DEGRADING_REASON_CODES = {
    "timeout",
    "rate_limit",
    "server_error",
    "provider_unavailable",
    "host_down",
    "auth_error",
    "provider_stream_interrupted",
}


@dataclass
class ModelHealthRecord:
    provider: str
    model: str
    state: str
    last_reason_code: str | None = None
    last_error_type: str | None = None
    last_error_detail: str | None = None
    last_timeout_seconds: float | None = None
    last_failure_at: float | None = None
    last_success_at: float | None = None
    degraded_until: float | None = None


_MODEL_HEALTH: dict[tuple[str, str], ModelHealthRecord] = {}
_MODEL_HEALTH_LOCK = threading.RLock()


def _normalize_provider(provider: str | None) -> str | None:
    if not isinstance(provider, str):
        return None
    normalized = provider.strip().lower()
    return normalized or None


def _normalize_model(model: str | None) -> str | None:
    if not isinstance(model, str):
        return None
    normalized = model.strip()
    return normalized or None


def _compact_detail(value: Any, *, max_length: int = 180) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def _get_record(provider: str, model: str) -> ModelHealthRecord:
    with _MODEL_HEALTH_LOCK:
        key = (provider, model)
        record = _MODEL_HEALTH.get(key)
        if record is None:
            record = ModelHealthRecord(provider=provider, model=model, state="healthy")
            _MODEL_HEALTH[key] = record
        return record


def _is_still_degraded(record: ModelHealthRecord, *, now: float) -> bool:
    if record.state != "degraded":
        return False
    if record.degraded_until is None:
        return True
    if record.degraded_until > now:
        return True
    record.state = "healthy"
    record.degraded_until = None
    return False


def record_model_success(provider: str | None, model: str | None) -> None:
    """Mark a concrete model healthy after a successful invocation."""
    normalized_provider = _normalize_provider(provider)
    normalized_model = _normalize_model(model)
    if not normalized_provider or not normalized_model:
        return
    with _MODEL_HEALTH_LOCK:
        record = _get_record(normalized_provider, normalized_model)
        record.state = "healthy"
        record.last_success_at = time.time()
        record.degraded_until = None


def record_model_failure(
    provider: str | None,
    model: str | None,
    *,
    reason_code: str | None = None,
    error: Exception | None = None,
    timeout_seconds: float | None = None,
    degraded_for_seconds: float | None = DEFAULT_DEGRADED_TTL_SECONDS,
) -> None:
    """Record a model failure and temporarily degrade retry-worthy failures."""
    normalized_provider = _normalize_provider(provider)
    normalized_model = _normalize_model(model)
    if not normalized_provider or not normalized_model:
        return

    with _MODEL_HEALTH_LOCK:
        now = time.time()
        normalized_reason = (reason_code or "").strip().lower() or None
        record = _get_record(normalized_provider, normalized_model)
        record.last_reason_code = normalized_reason
        record.last_error_type = type(error).__name__ if error is not None else None
        record.last_error_detail = _compact_detail(error)
        record.last_timeout_seconds = timeout_seconds
        record.last_failure_at = now

        should_degrade = (
            degraded_for_seconds is not None
            and degraded_for_seconds > 0
            and (
                timeout_seconds is not None
                or normalized_reason in _DEGRADING_REASON_CODES
            )
        )
        if not should_degrade:
            return

        record.state = "degraded"
        record.degraded_until = now + degraded_for_seconds


def is_model_degraded(provider: str | None, model: str | None) -> bool:
    """Return True while a model is inside its temporary degraded window."""
    normalized_provider = _normalize_provider(provider)
    normalized_model = _normalize_model(model)
    if not normalized_provider or not normalized_model:
        return False
    with _MODEL_HEALTH_LOCK:
        record = _MODEL_HEALTH.get((normalized_provider, normalized_model))
        if record is None:
            return False
        return _is_still_degraded(record, now=time.time())


def get_model_health_snapshot() -> dict[str, dict[str, dict[str, Any]]]:
    """Expose model health for diagnostics and LLMPool stats."""
    with _MODEL_HEALTH_LOCK:
        now = time.time()
        snapshot: dict[str, dict[str, dict[str, Any]]] = {}
        for record in list(_MODEL_HEALTH.values()):
            _is_still_degraded(record, now=now)
            provider_bucket = snapshot.setdefault(record.provider, {})
            provider_bucket[record.model] = {
                "state": record.state,
                "last_reason_code": record.last_reason_code,
                "last_error_type": record.last_error_type,
                "last_timeout_seconds": record.last_timeout_seconds,
                "last_failure_at": record.last_failure_at,
                "last_success_at": record.last_success_at,
                "degraded_until": record.degraded_until,
            }
        return snapshot


def reset_model_health_state() -> None:
    """Clear health state, primarily for tests."""
    with _MODEL_HEALTH_LOCK:
        _MODEL_HEALTH.clear()
