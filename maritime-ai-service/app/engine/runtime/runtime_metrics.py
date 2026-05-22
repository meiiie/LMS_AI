"""Lightweight metrics façade for the runtime hot paths.

Phase 13 of the runtime migration epic (issue #207). LangSmith was the
opaque observability backstop pre-Phase-9c; removing it left a gap.
Rather than reinvent half a metrics stack, this module gives the runtime
three primitives — ``record_latency_ms``, ``inc_counter``, ``set_gauge``
— and routes them to whatever backend is wired in:

1. **OpenTelemetry meter** if ``opentelemetry.metrics`` is importable —
   the SOTA path for Anthropic-grade infra.
2. **In-memory accumulator** otherwise — snapshot-able by tests and
   /admin endpoints, never explodes if observability libs are missing.

The façade has no Prometheus dependency by design. When the team is
ready, an exporter can drain the in-memory accumulator OR the OTel
metrics provider can route to a Prometheus-compatible OTLP backend
without any call-site change.

Usage::

    from app.engine.runtime.runtime_metrics import (
        record_latency_ms, inc_counter, time_block,
    )

    with time_block("subagent.run.duration_ms", labels={"status": "success"}):
        await runner.run(task)

    inc_counter("session_event_log.append", labels={"backend": "postgres"})

Latency is always milliseconds. Labels stay flat (``dict[str, str]``)
for cheap aggregation. Metric names follow the
``<subsystem>.<verb>.<unit>`` convention.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Generator, Mapping, Optional

logger = logging.getLogger(__name__)


# ── label hashing ──

LabelDict = Mapping[str, str]


def _label_key(labels: Optional[LabelDict]) -> tuple:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


# ── in-memory accumulator (always available, tests rely on it) ──


class _InMemorySink:
    """Process-local metrics buffer.

    Fully thread-safe for the sync path; the runtime is async but
    metrics calls happen across thread pools too (DB drivers, etc.).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, dict[tuple, int]] = {}
        self.gauges: dict[str, dict[tuple, float]] = {}
        self.histograms: dict[str, dict[tuple, list[float]]] = {}

    def inc(self, name: str, labels: Optional[LabelDict], by: int) -> None:
        key = _label_key(labels)
        with self._lock:
            bucket = self.counters.setdefault(name, {})
            bucket[key] = bucket.get(key, 0) + by

    def set(self, name: str, labels: Optional[LabelDict], value: float) -> None:
        key = _label_key(labels)
        with self._lock:
            bucket = self.gauges.setdefault(name, {})
            bucket[key] = value

    def observe(
        self, name: str, labels: Optional[LabelDict], value: float
    ) -> None:
        key = _label_key(labels)
        with self._lock:
            bucket = self.histograms.setdefault(name, {})
            bucket.setdefault(key, []).append(value)

    def snapshot(self) -> dict:
        """Return a deep copy of the current metric state.

        Tests use this to assert specific recordings; an /admin endpoint
        could expose it for live introspection without forcing a
        Prometheus scrape pipeline.
        """
        with self._lock:
            return {
                "counters": {
                    name: dict(buckets) for name, buckets in self.counters.items()
                },
                "gauges": {
                    name: dict(buckets) for name, buckets in self.gauges.items()
                },
                "histograms": {
                    name: {k: list(v) for k, v in buckets.items()}
                    for name, buckets in self.histograms.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.counters.clear()
            self.gauges.clear()
            self.histograms.clear()


_sink = _InMemorySink()


# ── OTel forwarder (optional) ──

_otel_meter = None
_otel_instruments: dict[str, object] = {}


def _otel_get_meter():
    """Cache and return an OTel meter, or None if metrics SDK is unavailable.

    OTel's ``opentelemetry.metrics`` lives in the same package as
    tracing; if tracing is initialized, metrics are usually available
    too. If not, we degrade silently to in-memory only.
    """
    global _otel_meter
    if _otel_meter is not None:
        return _otel_meter
    try:
        from opentelemetry import metrics  # type: ignore
    except ImportError:
        return None
    try:
        _otel_meter = metrics.get_meter("wiii.runtime")
    except Exception as exc:  # noqa: BLE001
        logger.debug("[runtime_metrics] OTel meter unavailable: %s", exc)
        return None
    return _otel_meter


def _otel_counter(name: str):
    inst = _otel_instruments.get(f"counter:{name}")
    if inst is not None:
        return inst
    meter = _otel_get_meter()
    if meter is None:
        return None
    try:
        inst = meter.create_counter(name)
    except Exception:  # noqa: BLE001
        return None
    _otel_instruments[f"counter:{name}"] = inst
    return inst


def _otel_histogram(name: str):
    inst = _otel_instruments.get(f"histogram:{name}")
    if inst is not None:
        return inst
    meter = _otel_get_meter()
    if meter is None:
        return None
    try:
        inst = meter.create_histogram(name, unit="ms")
    except Exception:  # noqa: BLE001
        return None
    _otel_instruments[f"histogram:{name}"] = inst
    return inst


# ── public API ──


def inc_counter(
    name: str, *, labels: Optional[LabelDict] = None, by: int = 1
) -> None:
    """Increment a named counter, optionally tagged with labels."""
    _sink.inc(name, labels, by)
    inst = _otel_counter(name)
    if inst is not None:
        try:
            inst.add(by, attributes=dict(labels) if labels else {})
        except Exception:  # noqa: BLE001 — never let metrics break a request
            logger.debug("[runtime_metrics] OTel counter add failed", exc_info=True)


def set_gauge(
    name: str, value: float, *, labels: Optional[LabelDict] = None
) -> None:
    """Set the value of a named gauge."""
    _sink.set(name, labels, float(value))


def record_latency_ms(
    name: str, value_ms: float, *, labels: Optional[LabelDict] = None
) -> None:
    """Record a latency observation in milliseconds."""
    _sink.observe(name, labels, float(value_ms))
    inst = _otel_histogram(name)
    if inst is not None:
        try:
            inst.record(value_ms, attributes=dict(labels) if labels else {})
        except Exception:  # noqa: BLE001
            logger.debug(
                "[runtime_metrics] OTel histogram record failed", exc_info=True
            )


@contextmanager
def time_block(
    name: str, *, labels: Optional[LabelDict] = None
) -> Generator[None, None, None]:
    """Context manager that records the duration of the block in ms."""
    started_ns = time.perf_counter_ns()
    try:
        yield
    finally:
        elapsed = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        record_latency_ms(name, elapsed, labels=labels)


def snapshot() -> dict:
    """Return a deep copy of the in-memory sink. Tests + /admin only."""
    return _sink.snapshot()


def _reset_for_tests() -> None:
    """Clear all in-memory metrics. Tests + fixtures only."""
    _sink.reset()


__all__ = [
    "inc_counter",
    "set_gauge",
    "record_latency_ms",
    "time_block",
    "snapshot",
]
