from __future__ import annotations

import json

import pytest

from app.engine.runtime import runtime_metrics as rm
from app.engine.runtime.lifecycle import HookPoint, Lifecycle
from app.engine.runtime.session_event_log import InMemorySessionEventLog
from app.engine.semantic_memory.lifecycle_hooks import (
    SEMANTIC_MEMORY_LIFECYCLE_EVENT_TYPE,
    SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION,
    build_semantic_memory_lifecycle_event,
    register_semantic_memory_lifecycle_hooks,
)


@pytest.fixture(autouse=True)
def reset_runtime_metrics():
    rm._reset_for_tests()
    yield
    rm._reset_for_tests()


def test_build_semantic_memory_lifecycle_event_is_raw_content_free() -> None:
    assert SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION == (
        "wiii.semantic_memory_lifecycle.v1"
    )

    event = build_semantic_memory_lifecycle_event(
        point=HookPoint.ON_RUN_END,
        payload={
            "status": "success",
            "transport": "stream/v3",
            "duration_ms": 1_500,
            "user_id_hash": "sha256:user",
            "user_message": "PRIVATE PROMPT",
        },
    )

    assert event["schema_version"] == SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION
    assert event["lifecycle"] == {
        "point": "on_run_end",
        "status": "success",
        "transport": "stream/v3",
        "duration_bucket": "1s_5s",
        "error_present": False,
    }
    assert event["post_turn"]["observer_owner"] == "engine.semantic_memory"
    assert event["post_turn"]["raw_user_payload_available"] is False
    assert event["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "session_row_scope_only",
    }
    serialized = json.dumps(event, ensure_ascii=False)
    assert "PRIVATE PROMPT" not in serialized
    assert "sha256:user" not in serialized


@pytest.mark.asyncio
async def test_semantic_memory_lifecycle_hook_appends_sanitized_event(
    monkeypatch,
) -> None:
    lifecycle = Lifecycle()
    log = InMemorySessionEventLog()
    monkeypatch.setattr(
        "app.engine.runtime.session_event_log.get_session_event_log",
        lambda: log,
    )
    registrations = register_semantic_memory_lifecycle_hooks(lifecycle)
    register_semantic_memory_lifecycle_hooks(lifecycle)

    assert {
        (registration.owner, registration.name)
        for registration in registrations
    } == {
        ("engine.semantic_memory", "_record_semantic_memory_run_end_hook"),
        ("engine.semantic_memory", "_record_semantic_memory_run_error_hook"),
    }
    assert len(lifecycle.registrations_at(HookPoint.ON_RUN_END)) == 1
    assert len(lifecycle.registrations_at(HookPoint.ON_RUN_ERROR)) == 1

    await lifecycle.fire(
        HookPoint.ON_RUN_END,
        {
            "session_id": "session-private",
            "org_id": "org-A",
            "status": "success",
            "transport": "stream/v3",
            "duration_ms": 250,
            "user_id": "raw-user-id",
            "user_message": "PRIVATE PROMPT",
        },
    )

    events = await log.get_events(session_id="session-private", org_id="org-A")
    assert len(events) == 1
    assert events[0].event_type == SEMANTIC_MEMORY_LIFECYCLE_EVENT_TYPE
    assert events[0].payload["schema_version"] == (
        SEMANTIC_MEMORY_LIFECYCLE_EVENT_VERSION
    )
    assert events[0].payload["lifecycle"]["point"] == "on_run_end"
    assert events[0].payload["lifecycle"]["status"] == "success"
    assert events[0].payload["lifecycle"]["duration_bucket"] == "lt_1s"
    assert events[0].payload["privacy"]["raw_content_included"] is False

    serialized = json.dumps(events[0].payload, ensure_ascii=False)
    assert "raw-user-id" not in serialized
    assert "PRIVATE PROMPT" not in serialized
    assert "session-private" not in serialized
    snap = rm.snapshot()
    observed_labels = (
        ("point", "on_run_end"),
        ("status", "success"),
        ("transport", "stream/v3"),
    )
    append_labels = (
        ("point", "on_run_end"),
        ("reason", "appended"),
        ("status", "success"),
    )
    assert (
        snap["counters"]["runtime.semantic_memory.lifecycle.observed"][
            observed_labels
        ]
        == 1
    )
    assert (
        snap["counters"]["runtime.semantic_memory.lifecycle.event_appends"][
            append_labels
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_semantic_memory_lifecycle_hook_skips_missing_session_id() -> None:
    lifecycle = Lifecycle()
    register_semantic_memory_lifecycle_hooks(lifecycle)

    await lifecycle.fire(
        HookPoint.ON_RUN_ERROR,
        {
            "error": "provider failed",
            "transport": "chat",
        },
    )

    snap = rm.snapshot()
    observed_labels = (
        ("point", "on_run_error"),
        ("status", "error"),
        ("transport", "chat"),
    )
    append_labels = (
        ("point", "on_run_error"),
        ("reason", "missing_session_id"),
        ("status", "skipped"),
    )
    assert (
        snap["counters"]["runtime.semantic_memory.lifecycle.observed"][
            observed_labels
        ]
        == 1
    )
    assert (
        snap["counters"]["runtime.semantic_memory.lifecycle.event_appends"][
            append_labels
        ]
        == 1
    )
