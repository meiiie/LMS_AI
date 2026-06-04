"""Phase 24 distributed tracing — Runtime Migration #207.

Locks the contract: spans auto-parent via ContextVar; ``end()`` is
idempotent; processors see every ended span; status='error' set on
exception then re-raised; concurrent tasks get isolated trees.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.engine.runtime import tracing


@pytest.fixture(autouse=True)
def reset_state():
    tracing._reset_for_tests()
    rm._reset_for_tests()
    yield
    tracing._reset_for_tests()
    rm._reset_for_tests()


@pytest.fixture
def in_memory():
    p = tracing.InMemoryProcessor()
    tracing.get_tracer().add_processor(p)
    yield p
    tracing.get_tracer().remove_processor(p)


# ── Span model ──

def test_span_duration_is_none_until_end():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    assert s.duration_ms is None


def test_span_duration_set_after_end():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.end()
    assert s.duration_ms is not None
    assert s.duration_ms >= 0


def test_span_end_is_idempotent():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.end()
    first = s.ended_at_ns
    s.end()
    assert s.ended_at_ns == first


def test_span_set_attribute_overwrites():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.set_attribute("a", 1)
    s.set_attribute("a", 2)
    assert s.attributes["a"] == 2


def test_span_set_attribute_sanitizes_identity_and_secrets():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.set_attribute("user_id", "raw-user-id")
    s.set_attribute("access_token", "raw-access-token")

    serialized = str(s.attributes)
    assert s.attributes["user_id_hash"].startswith("sha256:")
    assert s.attributes["redacted_secret_count"] == 1
    assert "user_id" not in s.attributes
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized


def test_span_set_status_records_error():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.set_status("error", error="provider down")
    assert s.status == "error"
    assert s.error == "provider down"


def test_span_set_status_redacts_secret_like_error_text():
    s = tracing.Span(name="x", trace_id="t", span_id="s")
    s.set_status(
        "error",
        error=(
            "provider failed Authorization: Bearer raw-bearer-token-123 "
            "refresh_token=raw-refresh-token-inline"
        ),
    )

    assert "<redacted-secret>" in (s.error or "")
    assert "raw-bearer-token-123" not in (s.error or "")
    assert "raw-refresh-token-inline" not in (s.error or "")


# ── span() context manager ──

def test_span_context_records_one_span(in_memory):
    with tracing.span("op.simple"):
        pass
    assert len(in_memory.spans) == 1
    assert in_memory.spans[0].name == "op.simple"
    assert in_memory.spans[0].status == "ok"


def test_span_context_marks_status_unset_to_ok(in_memory):
    with tracing.span("op.x") as s:
        assert s.status == "unset"
    assert in_memory.spans[0].status == "ok"


def test_span_context_records_error_on_exception(in_memory):
    with pytest.raises(RuntimeError, match="boom"):
        with tracing.span("op.fail"):
            raise RuntimeError("boom")
    assert len(in_memory.spans) == 1
    assert in_memory.spans[0].status == "error"
    assert "RuntimeError: boom" in in_memory.spans[0].error


def test_span_context_redacts_exception_secret_text(in_memory):
    with pytest.raises(RuntimeError, match="raw-bearer-token-123"):
        with tracing.span("op.fail"):
            raise RuntimeError(
                "provider failed Bearer raw-bearer-token-123 "
                "api_key=raw-api-key-inline"
            )

    error = in_memory.spans[0].error or ""
    assert "<redacted-secret>" in error
    assert "raw-bearer-token-123" not in error
    assert "raw-api-key-inline" not in error


def test_nested_spans_set_parent_id(in_memory):
    with tracing.span("parent"):
        with tracing.span("child"):
            pass
    parent = next(s for s in in_memory.spans if s.name == "parent")
    child = next(s for s in in_memory.spans if s.name == "child")
    assert child.parent_span_id == parent.span_id
    assert parent.parent_span_id is None
    # Same trace.
    assert child.trace_id == parent.trace_id


def test_nested_three_levels_chain_correctly(in_memory):
    with tracing.span("a"):
        with tracing.span("b"):
            with tracing.span("c"):
                pass
    by_name = {s.name: s for s in in_memory.spans}
    assert by_name["a"].parent_span_id is None
    assert by_name["b"].parent_span_id == by_name["a"].span_id
    assert by_name["c"].parent_span_id == by_name["b"].span_id


def test_attributes_propagate_to_recorded_span(in_memory):
    with tracing.span("op", attributes={"a": 1, "org_id": "org-A"}):
        pass
    assert in_memory.spans[0].attributes == {"a": 1, "org_id": "org-A"}


def test_attributes_are_sanitized_before_processors(in_memory):
    with tracing.span(
        "op",
        attributes={
            "user_id": "raw-user-id",
            "access_token": "raw-access-token",
            "nested": {
                "safe_id": "page-1",
                "provider_payload": {"id": "raw-provider"},
            },
        },
    ) as s:
        s.attributes["refresh_token"] = "late-raw-token"
        s.set_attribute("api_key", "raw-api-key")

    attrs = in_memory.spans[0].attributes
    assert attrs["user_id_hash"].startswith("sha256:")
    assert attrs["nested"]["safe_id"] == "page-1"
    assert attrs["redacted_secret_count"] >= 2
    serialized = str(attrs)
    assert "user_id" not in attrs
    assert "raw-user-id" not in serialized
    assert "raw-access-token" not in serialized
    assert "late-raw-token" not in serialized
    assert "raw-api-key" not in serialized
    assert "provider_payload" not in serialized


def test_set_attribute_inside_span_block(in_memory):
    with tracing.span("op") as s:
        s.set_attribute("dynamic", "value")
    assert in_memory.spans[0].attributes["dynamic"] == "value"


# ── ContextVar isolation ──

def test_current_span_is_none_outside_block():
    assert tracing.current_span() is None


def test_current_span_is_active_inside_block():
    with tracing.span("op") as s:
        assert tracing.current_span() is s


def test_current_span_restored_after_nested(in_memory):
    with tracing.span("outer") as outer:
        with tracing.span("inner"):
            pass
        assert tracing.current_span() is outer
    assert tracing.current_span() is None


@pytest.mark.asyncio
async def test_concurrent_tasks_get_separate_trees(in_memory):
    async def worker(label: str) -> str:
        with tracing.span(f"task.{label}"):
            await asyncio.sleep(0)
            return tracing.current_trace_id()

    a, b = await asyncio.gather(worker("a"), worker("b"))
    assert a != b  # ContextVar copy semantics gives each task its own root.


# ── processors ──

def test_logging_processor_emits_one_log_per_end(caplog):
    p = tracing.LoggingProcessor()
    tracing.get_tracer().add_processor(p)
    with caplog.at_level(logging.INFO, logger="app.engine.runtime.tracing"):
        with tracing.span("op.logged"):
            pass
    span_lines = [r for r in caplog.records if r.message.startswith("span ")]
    assert len(span_lines) == 1
    assert "op.logged" in span_lines[0].message


def test_metrics_forwarder_records_duration():
    p = tracing.MetricsForwarder()
    tracing.get_tracer().add_processor(p)
    with tracing.span("op.metric"):
        pass
    snap = rm.snapshot()
    durations = snap["histograms"]["runtime.span.duration_ms"]
    # Each bucket key is a sorted tuple of (label_key, label_value) pairs.
    assert any(
        dict(label_tuple).get("name") == "op.metric"
        and dict(label_tuple).get("status") == "ok"
        for label_tuple in durations
    )


def test_metrics_forwarder_labels_error_status():
    p = tracing.MetricsForwarder()
    tracing.get_tracer().add_processor(p)
    with pytest.raises(RuntimeError):
        with tracing.span("op.fail"):
            raise RuntimeError("fail")
    snap = rm.snapshot()
    durations = snap["histograms"]["runtime.span.duration_ms"]
    assert any(
        dict(label_tuple).get("name") == "op.fail"
        and dict(label_tuple).get("status") == "error"
        for label_tuple in durations
    )


def test_processor_exception_does_not_break_span(in_memory, caplog):
    """A faulty processor must not crash the request — log and continue."""

    class Boom:
        def on_end(self, span):
            raise RuntimeError("processor exploded")

    tracing.get_tracer().add_processor(Boom())
    with caplog.at_level(logging.DEBUG, logger="app.engine.runtime.tracing"):
        with tracing.span("op.protected"):
            pass
    # in_memory still got the span — the bad processor didn't poison the chain.
    assert len(in_memory.spans) == 1


# ── by_trace helper ──

def test_in_memory_by_trace_filters_correctly(in_memory):
    with tracing.span("op.a"):
        with tracing.span("op.b"):
            pass
    trace_id = in_memory.spans[0].trace_id
    assert {s.name for s in in_memory.by_trace(trace_id)} == {"op.a", "op.b"}
    assert in_memory.by_trace("nonexistent") == []
