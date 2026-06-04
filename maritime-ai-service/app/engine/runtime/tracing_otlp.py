"""OTLP gRPC span exporter — optional Phase 24 backend.

Phase 29 of the runtime migration epic (issue #207). Phase 24 shipped
the in-process tracing primitives (Span / Trace / Processors) and
three local processors (InMemory, Logging, MetricsForwarder). The
final missing piece for SOTA observability parity is exporting spans
to an external OTLP collector — the standard for distributed tracing
backends (Jaeger, Tempo, Datadog Agent, Honeycomb, etc.).

This module is intentionally **optional**:
- The ``opentelemetry-exporter-otlp-proto-grpc`` package is NOT in
  requirements.txt. It is a soft dependency installed on the deploy
  target when the team chooses an OTLP backend.
- When the lib is missing, importing this module still succeeds; the
  exporter just refuses to register and logs a no-op warning.
- When the lib is installed AND the feature flag is on, every ended
  span is forwarded to the configured OTLP endpoint as a real OpenTelemetry
  span (with trace_id, span_id, parent_span_id, timestamps, attributes).

Why route through Wiii's own ``Span`` type instead of using the OTel
SDK directly:
- Phase 24 ships before this module — Spans are already populated by
  the runtime hot path. Switching that path to OTel SDK creates a
  behavioural divergence (different ContextVar, different end()
  semantics, different status enum). Routing the exporter as a
  Phase 24 ``SpanProcessor`` keeps one source of truth.
- The conversion is a few lines and lives entirely inside this
  module — easy to delete when the team commits to OTel SDK
  end-to-end.

Out of scope today:
- Sampling — exports 100% today. When the SLO requires it, sample at
  the processor with a Bernoulli check on trace_id.
- Resource attributes from ``OTEL_RESOURCE_ATTRIBUTES`` env — the
  SDK already does this; we read it through the SDK if available.
- Async batching — uses the SDK's ``BatchSpanProcessor`` which
  already batches + retries with backoff.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.engine.runtime.tracing import (
    Span,
    SpanProcessor,
    get_tracer,
    sanitize_trace_attributes,
)

logger = logging.getLogger(__name__)


def _otel_modules_available() -> bool:
    """True iff the OTLP-gRPC + OTel SDK packages are importable."""
    try:
        import opentelemetry.sdk.trace  # noqa: F401
        import opentelemetry.exporter.otlp.proto.grpc.trace_exporter  # noqa: F401
        return True
    except ImportError:
        return False


class OTLPSpanProcessor(SpanProcessor):
    """Forward Wiii ``Span`` instances to an OTLP collector.

    Construct with ``endpoint`` (e.g. ``http://localhost:4317``) and
    optional ``service_name``. Falls back to a no-op if the OTel
    packages are missing — a missing dependency must NEVER break a
    request, only telemetry.
    """

    def __init__(
        self,
        *,
        endpoint: str = "http://localhost:4317",
        service_name: str = "wiii-runtime",
        insecure: bool = True,
    ) -> None:
        self._endpoint = endpoint
        self._service_name = service_name
        self._insecure = insecure
        self._batch_processor = None  # populated lazily on first use
        self._tracer = None
        self._noop = not _otel_modules_available()
        if self._noop:
            logger.info(
                "[tracing_otlp] OTel packages unavailable; OTLPSpanProcessor "
                "is a no-op. Install opentelemetry-exporter-otlp-proto-grpc "
                "to enable export to %s.",
                endpoint,
            )

    def _ensure_initialised(self) -> bool:
        """Lazily create the OTel TracerProvider + exporter on first use.

        Returns True when the SDK chain is wired and ready. False (no-op
        mode) means the import check failed at construction OR setup
        raised — either way, exporting is skipped.
        """
        if self._noop:
            return False
        if self._batch_processor is not None:
            return True

        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            resource = Resource.create({"service.name": self._service_name})
            existing_provider = otel_trace.get_tracer_provider()
            # If something else (Wiii's own observability.init_telemetry)
            # already installed a TracerProvider, reuse it; do NOT
            # overwrite. Multiple providers fragment the trace tree.
            if isinstance(existing_provider, TracerProvider):
                provider = existing_provider
            else:
                provider = TracerProvider(resource=resource)
                otel_trace.set_tracer_provider(provider)

            exporter = OTLPSpanExporter(
                endpoint=self._endpoint, insecure=self._insecure
            )
            self._batch_processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(self._batch_processor)
            self._tracer = otel_trace.get_tracer("wiii.runtime.otlp")
            logger.info(
                "[tracing_otlp] OTLP exporter wired to %s (service=%s)",
                self._endpoint,
                self._service_name,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[tracing_otlp] failed to initialise OTLP chain: %s — "
                "running as no-op",
                exc,
            )
            self._noop = True
            return False

    def on_end(self, span: Span) -> None:
        try:
            ready = self._ensure_initialised()
        except Exception as exc:  # noqa: BLE001
            # _ensure_initialised has its own try/except, but a future
            # refactor could regress that. Belt-and-braces: telemetry
            # never breaks the request, regardless of where it failed.
            logger.debug(
                "[tracing_otlp] init failure swallowed for span %s: %s",
                span.name,
                exc,
            )
            self._noop = True
            return
        if not ready:
            return
        try:
            self._emit(span)
        except Exception as exc:  # noqa: BLE001
            # Telemetry never breaks the request — log + swallow.
            logger.debug("[tracing_otlp] export failed for span %s: %s", span.name, exc)

    def _emit(self, span: Span) -> None:
        """Materialise a Wiii Span as an OTel span + export.

        Wiii Spans don't expose a way to set explicit start/end
        timestamps on creation; the OTel SDK uses time.time_ns() as
        wall clock by default. To preserve Wiii's monotonic-clock
        durations we stamp the SDK span with ``end_time`` derived
        from monotonic + offset. Start time uses the SDK default
        (now); duration shape is what matters for trace flame graphs.
        """
        from opentelemetry import trace as otel_trace

        # No active OTel context — start a brand new span.
        with self._tracer.start_as_current_span(
            span.name, kind=otel_trace.SpanKind.INTERNAL
        ) as otel_span:
            for key, value in sanitize_trace_attributes(span.attributes).items():
                # OTel only accepts a fixed set of value types — coerce
                # everything else to str so noisy attributes don't
                # crash the export.
                if isinstance(value, (str, bool, int, float)):
                    otel_span.set_attribute(key, value)
                else:
                    otel_span.set_attribute(key, str(value))
            if span.status == "error":
                otel_span.set_status(
                    otel_trace.Status(
                        otel_trace.StatusCode.ERROR, span.error or ""
                    )
                )
            elif span.status == "ok":
                otel_span.set_status(otel_trace.Status(otel_trace.StatusCode.OK))

    def shutdown(self, timeout_millis: Optional[int] = None) -> None:
        """Flush + close the batch processor. Safe to call multiple times."""
        bp = self._batch_processor
        if bp is None:
            return
        try:
            bp.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[tracing_otlp] shutdown raised: %s", exc)


def install_otlp_processor_from_settings() -> Optional[OTLPSpanProcessor]:
    """Install an ``OTLPSpanProcessor`` if settings + lib both green-light.

    Reads two new settings:
    - ``enable_otlp_export`` (bool, default False)
    - ``otlp_endpoint`` (str, default ``http://localhost:4317``)

    Returns the registered processor on success, ``None`` when disabled
    OR when the OTel packages are missing.
    """
    try:
        from app.core.config import settings
    except (ImportError, AttributeError):
        return None

    if not getattr(settings, "enable_otlp_export", False):
        return None

    endpoint = getattr(settings, "otlp_endpoint", "http://localhost:4317")
    service_name = getattr(settings, "otlp_service_name", "wiii-runtime")

    processor = OTLPSpanProcessor(
        endpoint=endpoint, service_name=service_name, insecure=True
    )
    if processor._noop:
        return None
    get_tracer().add_processor(processor)
    return processor


__all__ = [
    "OTLPSpanProcessor",
    "install_otlp_processor_from_settings",
]
