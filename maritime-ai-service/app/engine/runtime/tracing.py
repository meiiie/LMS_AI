"""Distributed tracing primitives for the Wiii runtime.

Phase 24 of the runtime migration epic (issue #207). Phase 13 shipped
flat counters / histograms; that's enough for SLO targets and
dashboard tiles. It is NOT enough to debug a latency spike that crosses
``edge endpoint → native_dispatch → ChatService → SubagentRunner →
LLM call → tool call``. When the on-call asks "where did 6 seconds
go?", flat metrics make them grep logs by request id; spans make
them open one trace and see the whole tree.

The reference (openai-agents-python ``tracing/``) decomposes this into:
- **Span** — a single timed operation with attributes and a parent.
- **Trace** — the collection of spans for one root operation, sharing a
  ``trace_id``.
- **Provider/processor** — pluggable backends (console, OTLP, JSON
  files) that consume completed spans.

This module ships the same shape, scoped surgically:
- Pure-Python primitives. No hard dependency on ``opentelemetry-api``.
- ContextVar-based propagation, mirroring Phase 11c's ``replay_context``.
- Two built-in processors: ``InMemoryProcessor`` (tests + /admin) and
  ``LoggingProcessor`` (structured JSON to logger).
- A façade integration with the Phase 13 metrics — when a span ends,
  its duration also lands in the metrics histogram so the existing
  Prometheus scrape sees both.

Out of scope for this phase:
- OTLP gRPC export (one external lib away when the team is ready).
- Sampling strategies (today: 100%; sampling lives at the processor).
- Span linking across thread/process boundaries (Wiii is single-process).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Generator, Optional, Protocol

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.engine.runtime.runtime_metrics import record_latency_ms

logger = logging.getLogger(__name__)


def sanitize_trace_attributes(
    attributes: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return attributes safe for span processors and external telemetry."""

    safe_attributes = sanitize_runtime_payload(attributes or {})
    return dict(safe_attributes) if isinstance(safe_attributes, dict) else {}


def _merge_trace_attributes(
    target: dict[str, Any],
    safe_attributes: dict[str, Any],
) -> None:
    redacted_count = safe_attributes.pop("redacted_secret_count", 0)
    if redacted_count:
        target["redacted_secret_count"] = (
            int(target.get("redacted_secret_count") or 0) + int(redacted_count)
        )
    target.update(safe_attributes)


# ── data ──


@dataclass(slots=True)
class Span:
    """One timed operation in a trace.

    ``end()`` is idempotent: calling twice keeps the first end time.
    Spans are mutable while open (callers can ``set_attribute`` mid-flight)
    but must be considered frozen once ended.
    """

    name: str
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    started_at_ns: int = field(default_factory=time.monotonic_ns)
    ended_at_ns: Optional[int] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "unset"
    """``unset`` | ``ok`` | ``error``."""
    error: Optional[str] = None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.ended_at_ns is None:
            return None
        return (self.ended_at_ns - self.started_at_ns) / 1_000_000.0

    def set_attribute(self, key: str, value: Any) -> None:
        key_text = str(key)
        safe_attributes = sanitize_trace_attributes({key_text: value})
        self.attributes.pop(key_text, None)
        _merge_trace_attributes(self.attributes, safe_attributes)

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        self.status = status
        if error:
            self.error = redact_runtime_secret_text(error)

    def end(self) -> None:
        if self.ended_at_ns is None:
            self.ended_at_ns = time.monotonic_ns()


# ── processors ──


class SpanProcessor(Protocol):
    """Backend that consumes a span when it ends."""

    def on_end(self, span: Span) -> None: ...


class InMemoryProcessor:
    """Buffer ended spans in memory for inspection (tests + /admin)."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def on_end(self, span: Span) -> None:
        self.spans.append(span)

    def reset(self) -> None:
        self.spans.clear()

    def by_trace(self, trace_id: str) -> list[Span]:
        return [s for s in self.spans if s.trace_id == trace_id]


class LoggingProcessor:
    """Emit one structured JSON line per ended span via the standard logger.

    Production-grade until the team adopts OTLP. Logs are already
    request-id correlated; adding ``trace_id`` + ``span_id`` lets the
    same log pipeline reconstruct trees.
    """

    def __init__(self, level: int = logging.INFO) -> None:
        self._level = level

    def on_end(self, span: Span) -> None:
        payload = {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id,
            "name": span.name,
            "duration_ms": span.duration_ms,
            "status": span.status,
            "attributes": span.attributes,
        }
        if span.error:
            payload["error"] = span.error
        logger.log(self._level, "span %s", json.dumps(payload, default=str))


class MetricsForwarder:
    """Bridge ended spans into the Phase 13 metrics façade.

    Every span's duration lands in
    ``runtime.span.duration_ms{name="<span_name>",status="<...>"}``
    so Prometheus already sees the data without an OTLP exporter.
    """

    def on_end(self, span: Span) -> None:
        if span.duration_ms is None:
            return
        record_latency_ms(
            "runtime.span.duration_ms",
            span.duration_ms,
            labels={"name": span.name, "status": span.status},
        )


# ── tracer + propagation ──


_current_span: ContextVar[Optional[Span]] = ContextVar(
    "wiii_current_span", default=None
)
_current_trace_id: ContextVar[Optional[str]] = ContextVar(
    "wiii_current_trace_id", default=None
)


class Tracer:
    """Singleton-ish tracer that creates spans + dispatches to processors."""

    def __init__(self) -> None:
        self._processors: list[SpanProcessor] = []

    def add_processor(self, processor: SpanProcessor) -> None:
        if processor not in self._processors:
            self._processors.append(processor)

    def remove_processor(self, processor: SpanProcessor) -> None:
        if processor in self._processors:
            self._processors.remove(processor)

    def reset_processors(self) -> None:
        self._processors.clear()

    def start_span(
        self,
        name: str,
        *,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        """Create a new span, parented on the current span if any.

        The new span becomes the current span only when used inside
        ``span(...)`` — calling start_span directly does NOT mutate the
        ContextVar (the caller takes responsibility for end()).
        """
        parent = _current_span.get()
        trace_id = _current_trace_id.get() or _new_trace_id()
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=_new_span_id(),
            parent_span_id=parent.span_id if parent else None,
            attributes=sanitize_trace_attributes(attributes),
        )
        return span

    def end_span(self, span: Span) -> None:
        span.end()
        span.attributes = sanitize_trace_attributes(span.attributes)
        if span.error:
            span.error = redact_runtime_secret_text(span.error)
        for processor in list(self._processors):
            try:
                processor.on_end(span)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "[tracing] processor %s raised on_end: %s",
                    type(processor).__name__,
                    exc,
                )


_tracer = Tracer()


def get_tracer() -> Tracer:
    return _tracer


# ── public helpers ──


def _new_trace_id() -> str:
    return uuid.uuid4().hex


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


@contextmanager
def span(
    name: str,
    *,
    attributes: Optional[dict[str, Any]] = None,
) -> Generator[Span, None, None]:
    """Open a span for the duration of a ``with`` block.

    Auto-parents on the active span via ContextVar. Sets status="error"
    if the block raises, then re-raises. Calls ``end_span`` always so
    processors see every span.
    """
    s = _tracer.start_span(name, attributes=attributes)
    span_token: Token = _current_span.set(s)
    trace_token: Optional[Token] = None
    if _current_trace_id.get() is None:
        trace_token = _current_trace_id.set(s.trace_id)
    try:
        yield s
        if s.status == "unset":
            s.set_status("ok")
    except Exception as exc:  # noqa: BLE001
        s.set_status("error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _tracer.end_span(s)
        _current_span.reset(span_token)
        if trace_token is not None:
            _current_trace_id.reset(trace_token)


def current_span() -> Optional[Span]:
    return _current_span.get()


def current_trace_id() -> Optional[str]:
    return _current_trace_id.get()


def _reset_for_tests() -> None:
    """Drop processors + cleat the singletons. Tests only."""
    _tracer.reset_processors()


__all__ = [
    "Span",
    "SpanProcessor",
    "InMemoryProcessor",
    "LoggingProcessor",
    "MetricsForwarder",
    "Tracer",
    "sanitize_trace_attributes",
    "get_tracer",
    "span",
    "current_span",
    "current_trace_id",
]
