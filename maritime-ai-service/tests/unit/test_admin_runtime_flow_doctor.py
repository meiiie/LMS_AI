from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.engine.runtime.session_event_log import InMemorySessionEventLog
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    build_semantic_memory_write_audit,
)


@pytest.fixture(autouse=True)
def reset_lifecycle_hooks():
    from app.engine.runtime import lifecycle as lifecycle_mod
    from app.engine.runtime import runtime_metrics as rm
    from app.engine.runtime.lifecycle import register_default_lifecycle_hooks
    from app.engine.semantic_memory.lifecycle_hooks import (
        register_semantic_memory_lifecycle_hooks,
    )

    rm._reset_for_tests()
    lifecycle_mod._reset_for_tests()
    register_default_lifecycle_hooks()
    register_semantic_memory_lifecycle_hooks()
    yield
    lifecycle_mod._reset_for_tests()
    rm._reset_for_tests()


def _ledger(route: str) -> dict[str, object]:
    return {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "request": {
            "request_id": "raw-request-id",
            "session_id": "raw-session-id",
            "user_id_hash": "sha256:user",
        },
        "route": {"lane": route},
        "context": {
            "context_provenance": {
                "warnings": [],
                "privacy": {"raw_content_included": False},
            }
        },
        "tools": {"observed": [], "suppressed": []},
        "stream": {"done_seen": True, "metadata_seen": True, "event_counts": {"done": 1}},
        "finalization": {
            "status": "saved",
            "post_turn_lifecycle": {
                "schema_version": "wiii.post_turn_lifecycle.v1",
                "status": "scheduled",
                "reason": "post_turn_background_tasks_scheduled",
                "semantic_memory_policy": "extract_facts",
                "background_tasks_scheduled": True,
                "background_schedule": {
                    "schema_version": "wiii.background_task_schedule.v1",
                    "task_count": 2,
                    "groups": [
                        {
                            "group": "semantic_memory_interaction",
                            "status": "scheduled",
                            "reason": "extract_facts",
                        },
                        {
                            "group": "semantic_memory_maintenance",
                            "status": "scheduled",
                            "reason": "after_interaction_write",
                        },
                    ],
                    "privacy": {
                        "raw_content_included": False,
                        "identifier_strategy": "status_only",
                    },
                },
                "privacy": {
                    "raw_content_included": False,
                    "identifier_strategy": "status_only",
                },
            },
        },
    }


async def test_admin_runtime_flow_doctor_returns_aggregate_session_report(
    monkeypatch,
) -> None:
    from app.api.v1 import admin
    from app.engine.runtime import runtime_metrics as rm

    log = InMemorySessionEventLog()
    await log.append(
        session_id="session-private-raw",
        org_id="org-A",
        event_type="user_message",
        payload={"text": "PRIVATE PROMPT"},
    )
    await log.append(
        session_id="session-private-raw",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("casual_chat")},
    )
    rm.inc_counter(
        "runtime.post_turn.lifecycle.scheduling",
        labels={
            "status": "scheduled",
            "reason": "post_turn_background_tasks_scheduled",
            "transport": "sync",
            "semantic_memory_policy": "extract_facts",
        },
    )
    rm.inc_counter(
        "runtime.background_tasks.scheduling",
        labels={
            "group": "semantic_memory_interaction",
            "status": "scheduled",
            "reason": "extract_facts",
        },
    )
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.get_runtime_flow_doctor(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        session_id="session-private-raw",
        org_id="org-A",
        since_seq=None,
    )

    assert report["status"] == "ready"
    assert report["alerts"] == []
    assert report["routes"] == {"casual_chat": 1}
    assert report["source"]["session_event_count"] == 2
    assert report["request_correlation"]["request_id_present_count"] == 1
    assert report["request_correlation"]["missing_request_id_count"] == 0
    assert report["alert_trend"]["bucket_strategy"] == "event_created_at_hour"
    assert report["alert_trend"]["buckets"][0]["turn_count"] == 1
    assert report["runtime_config"] == {
        "native_stream_dispatch_enabled": False,
        "session_event_log_backend": "in_memory",
        "lifecycle_hook_total": 4,
        "lifecycle_hook_owner_count": 2,
        "lifecycle_on_run_end_hook_count": 2,
        "lifecycle_on_run_error_hook_count": 2,
    }
    assert report["lifecycle_registrations"]["version"] == (
        "wiii.runtime_lifecycle_registrations.v1"
    )
    assert report["lifecycle_registrations"]["default_runtime_hooks"][
        "installed"
    ] is True
    assert report["lifecycle_registrations"]["owner_counts"][
        "engine.semantic_memory"
    ] == 2
    assert report["lifecycle_registrations"]["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "code_metadata_only",
    }
    assert report["post_turn_lifecycle"]["version"] == (
        "wiii.post_turn_lifecycle_metrics.v1"
    )
    assert report["post_turn_lifecycle"]["post_turn"]["status_counts"] == {
        "scheduled": 1,
    }
    assert report["post_turn_lifecycle"]["background_tasks"]["group_counts"] == {
        "semantic_memory_interaction": 1,
    }
    assert report["post_turn_lifecycle_ledger"]["version"] == (
        "wiii.post_turn_lifecycle_ledger.v1"
    )
    assert report["post_turn_lifecycle_ledger"]["event_count"] == 1
    assert report["post_turn_lifecycle_ledger"]["background_schedule"][
        "group_counts"
    ] == {
        "semantic_memory_interaction": 1,
        "semantic_memory_maintenance": 1,
    }
    assert report["post_turn_lifecycle"]["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "aggregate_counts_only",
    }
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE PROMPT" not in serialized
    assert "session-private-raw" not in serialized
    assert "raw-request-id" not in serialized


async def test_admin_recent_runtime_flow_doctor_does_not_require_session_id(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    log = InMemorySessionEventLog()
    await log.append(
        session_id="session-private-a",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("casual_chat")},
    )
    await log.append(
        session_id="session-private-b",
        org_id="org-B",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("lms_document_preview")},
    )
    await log.append(
        session_id="session-private-c",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("document_preview")},
    )
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.get_recent_runtime_flow_doctor(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        org_id="org-A",
        limit=50,
    )

    assert report["status"] == "ready"
    assert report["alerts"] == []
    assert report["routes"] == {"document_preview": 1, "casual_chat": 1}
    assert report["source"]["window"] == "recent_runtime_flow_ledger_events"
    assert report["request_correlation"]["request_id_present_count"] == 2
    assert sum(
        bucket["turn_count"] for bucket in report["alert_trend"]["buckets"]
    ) == 2
    assert report["runtime_config"]["session_event_log_backend"] == "in_memory"
    assert report["runtime_config"]["lifecycle_hook_total"] >= 2
    assert report["runtime_config"]["lifecycle_on_run_end_hook_count"] >= 1
    assert report["post_turn_lifecycle"]["version"] == (
        "wiii.post_turn_lifecycle_metrics.v1"
    )
    assert report["post_turn_lifecycle_ledger"]["event_count"] == 2
    serialized = json.dumps(report, ensure_ascii=False)
    assert "session-private-a" not in serialized
    assert "session-private-b" not in serialized
    assert "session-private-c" not in serialized


async def test_admin_runtime_flow_doctor_history_is_aggregate_only(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    log = InMemorySessionEventLog()
    await log.append(
        session_id="session-private-a",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("casual_chat")},
    )
    await log.append(
        session_id="session-private-b",
        org_id="org-B",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("lms_document_preview")},
    )
    await log.append(
        session_id="session-private-c",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger("document_preview")},
    )
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.get_runtime_flow_doctor_history(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        org_id="org-A",
        limit=50,
        bucket_limit=12,
    )

    assert report["version"] == "wiii.runtime_flow_doctor_history.v1"
    assert report["bucket_strategy"] == "event_created_at_hour"
    assert report["identifier_strategy"] == "aggregate_counts_only"
    assert report["source"]["window"] == "recent_runtime_flow_ledger_history"
    assert report["source"]["runtime_flow_ledger_event_count"] == 2
    assert report["source"]["org_scoped"] is True
    assert report["source"]["bucket_limit"] == 12
    assert report["buckets"][0]["summary"]["turn_count"] == 2
    assert report["runtime_config"]["session_event_log_backend"] == "in_memory"
    assert report["runtime_config"]["lifecycle_hook_total"] >= 2
    assert report["runtime_config"]["lifecycle_on_run_error_hook_count"] >= 1
    assert report["post_turn_lifecycle"]["version"] == (
        "wiii.post_turn_lifecycle_metrics.v1"
    )
    assert report["post_turn_lifecycle_ledger"]["event_count"] == 2
    assert report["buckets"][0]["post_turn_lifecycle_ledger"]["event_count"] == 2
    serialized = json.dumps(report, ensure_ascii=False)
    assert "org-A" not in serialized
    assert "session-private-a" not in serialized
    assert "session-private-b" not in serialized
    assert "session-private-c" not in serialized
    assert "raw-request-id" not in serialized


async def test_admin_runtime_flow_session_event_prune_is_aggregate_only(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    class FakeLog:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def prune_older_than(self, **kwargs):
            self.calls.append(kwargs)
            return 3

    log = FakeLog()
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.prune_runtime_flow_session_events(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        retention_days=7,
        org_id="org-private-prune",
        event_type="runtime_flow_ledger",
        dry_run=True,
    )

    assert report["schema"] == "wiii.session_event_log_prune.v1"
    assert report["status"] == "dry_run"
    assert report["matched_count"] == 3
    assert report["deleted_count"] == 0
    assert report["retention_days"] == 7
    assert report["dry_run"] is True
    assert report["org_scoped"] is True
    assert report["event_type_filter_applied"] is True
    assert report["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "aggregate_counts_only",
    }
    assert log.calls[0]["org_id"] == "org-private-prune"
    assert log.calls[0]["event_type"] == "runtime_flow_ledger"
    assert log.calls[0]["dry_run"] is True
    serialized = json.dumps(report, ensure_ascii=False)
    assert "org-private-prune" not in serialized
    assert "runtime_flow_ledger" not in serialized


async def test_admin_recent_semantic_memory_doctor_is_aggregate_only(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    log = InMemorySessionEventLog()
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-memory",
        message="PRIVATE MEMORY MESSAGE",
        response="PRIVATE MEMORY RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-A",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=3,
        status="saved",
    )
    await log.append(
        session_id="session-private-memory",
        org_id="org-A",
        event_type="semantic_memory_write",
        payload=payload,
    )
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.get_recent_semantic_memory_doctor(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        org_id="org-A",
        limit=50,
    )

    assert report["status"] == "ready"
    assert report["summary"]["stored_fact_total"] == 3
    assert report["summary"]["stored_insight_total"] == 0
    assert report["write_kinds"] == {"interaction": 1}
    assert report["source"]["window"] == "recent_semantic_memory_write_events"
    assert report["runtime_config"]["session_event_log_backend"] == "in_memory"
    serialized = json.dumps(report, ensure_ascii=False)
    assert "session-private-memory" not in serialized
    assert "user-private-123" not in serialized
    assert "PRIVATE MEMORY MESSAGE" not in serialized
    assert "PRIVATE MEMORY RESPONSE" not in serialized


async def test_admin_semantic_memory_doctor_history_is_aggregate_only(
    monkeypatch,
) -> None:
    from app.api.v1 import admin

    log = InMemorySessionEventLog()
    payload = build_semantic_memory_write_audit(
        user_id="user-private-123",
        session_id="session-private-memory",
        message="PRIVATE MEMORY HISTORY MESSAGE",
        response="PRIVATE MEMORY HISTORY RESPONSE",
        scope=MemoryWriteScope(
            org_id="org-A",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=3,
        status="saved",
    )
    other_org_payload = build_semantic_memory_write_audit(
        user_id="user-private-456",
        session_id="session-private-other",
        message="PRIVATE MEMORY OTHER ORG",
        response="PRIVATE MEMORY OTHER ORG",
        scope=MemoryWriteScope(
            org_id="org-B",
            state="request_scoped",
            warnings=[],
        ),
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=7,
        status="saved",
    )
    await log.append(
        session_id="session-private-memory",
        org_id="org-A",
        event_type="semantic_memory_write",
        payload=payload,
    )
    await log.append(
        session_id="session-private-other",
        org_id="org-B",
        event_type="semantic_memory_write",
        payload=other_org_payload,
    )
    monkeypatch.setattr(admin, "get_session_event_log", lambda: log)

    report = await admin.get_semantic_memory_doctor_history(
        request=SimpleNamespace(),
        auth=SimpleNamespace(platform_role="platform_admin"),
        org_id="org-A",
        limit=50,
        bucket_limit=12,
    )

    assert report["version"] == "wiii.semantic_memory_write_doctor_history.v1"
    assert report["bucket_strategy"] == "event_created_at_hour"
    assert report["source"]["semantic_memory_write_event_count"] == 1
    assert report["source"]["org_scoped"] is True
    assert report["source"]["bucket_limit"] == 12
    assert report["source"]["window"] == "recent_semantic_memory_write_history"
    assert report["buckets"][0]["summary"]["stored_fact_total"] == 3
    assert report["runtime_config"]["session_event_log_backend"] == "in_memory"
    serialized = json.dumps(report, ensure_ascii=False)
    assert "session-private-memory" not in serialized
    assert "session-private-other" not in serialized
    assert "user-private-123" not in serialized
    assert "org-A" not in serialized
    assert "PRIVATE MEMORY HISTORY MESSAGE" not in serialized
    assert "PRIVATE MEMORY OTHER ORG" not in serialized
