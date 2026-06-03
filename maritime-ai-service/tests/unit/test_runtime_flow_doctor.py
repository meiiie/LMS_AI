from __future__ import annotations

import json

from app.engine.multi_agent.runtime_flow_doctor import (
    POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION,
    RUNTIME_FLOW_DOCTOR_HISTORY_VERSION,
    RUNTIME_FLOW_DOCTOR_VERSION,
    build_runtime_flow_alert_trend_from_events,
    build_runtime_flow_doctor_history_from_events,
    build_runtime_flow_doctor_history_from_session_log,
    build_recent_runtime_flow_doctor_report_from_session_log,
    build_runtime_flow_doctor_report,
    build_runtime_flow_doctor_report_from_session_log,
    runtime_flow_ledgers_from_events,
)
from app.engine.runtime.session_event_log import InMemorySessionEventLog


def _ledger(
    *,
    route: str,
    request_id: str | None = "req-private-raw",
    done_seen: bool = True,
    uploaded_documents: int = 0,
    source_refs: int = 0,
    memory_contexts: int = 0,
    warnings: list[str] | None = None,
    suppressed: list[str] | None = None,
    observed: list[str] | None = None,
    subagents: dict[str, object] | None = None,
    provider_call_correlation: dict[str, object] | None = None,
    finalization_status: str = "saved",
    post_turn_lifecycle: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "request": {
            "request_id": request_id,
            "session_id": "session-private-raw",
            "user_id_hash": "sha256:user",
        },
        "route": {
            "lane": route,
            "turn_path_decision": {"path": route},
        },
        "context": {
            "uploaded_document_count": uploaded_documents,
            "source_ref_count": source_refs,
            "memory_context_count": memory_contexts,
            "context_provenance": {
                "warnings": warnings or [],
                "privacy": {
                    "raw_content_included": False,
                    "identifier_strategy": "hash_or_count_only",
                },
                "documents": {"raw_document_markdown": "PRIVATE DOCUMENT BODY"},
            },
        },
        "tools": {
            "observed": observed or [],
            "suppressed": suppressed or [],
        },
        "stream": {
            "transport": "sse_v3",
            "event_counts": {"answer": 1, "metadata": 1, "done": 1},
            "metadata_seen": True,
            "done_seen": done_seen,
        },
        "external_app": {
            "action_trace": {
                "provider_call_correlation": provider_call_correlation or {},
            },
        },
        "subagents": subagents or {},
        "finalization": {
            "status": finalization_status,
            "post_turn_lifecycle": post_turn_lifecycle,
        },
    }


def _post_turn_lifecycle(
    *,
    status: str = "scheduled",
    reason: str = "post_turn_background_tasks_scheduled",
    semantic_memory_policy: str = "extract_facts",
    background_tasks_scheduled: bool = True,
    task_count: int = 2,
    groups: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if groups is None:
        groups = [
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
        ]
    return {
        "schema_version": "wiii.post_turn_lifecycle.v1",
        "status": status,
        "reason": reason,
        "semantic_memory_policy": semantic_memory_policy,
        "background_tasks_scheduled": background_tasks_scheduled,
        "background_schedule": {
            "schema_version": "wiii.background_task_schedule.v1",
            "task_count": task_count,
            "groups": groups,
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        },
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }


def test_runtime_flow_doctor_summarizes_recent_ledgers_without_raw_content() -> None:
    report = build_runtime_flow_doctor_report(
        [
            _ledger(
                route="casual_chat",
                suppressed=["pointy_action", "visual_runtime", "code_studio"],
            ),
            _ledger(
                route="lms_document_preview",
                uploaded_documents=1,
                source_refs=3,
                memory_contexts=2,
                warnings=["document_context_truncated"],
                observed=["host_action_preview"],
                subagents={
                    "schema_version": "wiii.subagent_boundary_trace.v1",
                    "report_count": 1,
                    "raw_content_included": False,
                    "warning_codes": ["state_top_level_keys_dropped"],
                    "reports": [
                        {
                            "agent_name": "rag",
                            "state_projected_key_count": 4,
                            "state_dropped_key_count": 6,
                            "source_count": 2,
                            "tool_count": 1,
                            "thinking_dropped": True,
                            "raw_child_output": "PRIVATE CHILD OUTPUT",
                        }
                    ],
                },
                finalization_status="saved",
            ),
        ]
    )

    assert report["version"] == RUNTIME_FLOW_DOCTOR_VERSION
    assert report["status"] == "degraded"
    assert [alert["code"] for alert in report["alerts"]] == [
        "context_warning",
        "subagent_boundary_warning",
    ]
    assert report["summary"]["turn_count"] == 2
    assert report["summary"]["done_seen_count"] == 2
    assert report["summary"]["uploaded_document_turns"] == 1
    assert report["summary"]["memory_context_turns"] == 1
    assert report["summary"]["source_ref_total"] == 3
    assert report["routes"] == {"casual_chat": 1, "lms_document_preview": 1}
    assert report["suppressed_tools"]["pointy_action"] == 1
    assert report["observed_tools"]["host_action_preview"] == 1
    assert report["context_warnings"] == {"document_context_truncated": 1}
    assert report["subagents"] == {
        "turn_count": 1,
        "report_count": 1,
        "state_projected_key_count": 4,
        "state_dropped_key_count": 6,
        "source_count": 2,
        "tool_count": 1,
        "thinking_dropped_count": 1,
        "raw_content_flag_count": 0,
        "warning_count": 1,
        "warnings": {"state_top_level_keys_dropped": 1},
        "identifier_strategy": "aggregate_counts_only",
    }
    assert report["request_correlation"]["request_id_present_count"] == 2
    assert report["request_correlation"]["missing_request_id_count"] == 0
    assert report["request_correlation"]["provider_call_turn_count"] == 0
    assert report["privacy"]["identifier_strategy"] == "aggregate_counts_only"

    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE DOCUMENT BODY" not in serialized
    assert "PRIVATE CHILD OUTPUT" not in serialized
    assert "session-private-raw" not in serialized
    assert "req-private-raw" not in serialized


def test_runtime_flow_doctor_summarizes_durable_post_turn_lifecycle() -> None:
    assert POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION == (
        "wiii.post_turn_lifecycle_ledger.v1"
    )

    report = build_runtime_flow_doctor_report(
        [
            _ledger(
                route="casual_chat",
                post_turn_lifecycle=_post_turn_lifecycle(
                    groups=[
                        {
                            "group": "semantic_memory_interaction",
                            "status": "scheduled",
                            "reason": "extract_facts",
                        },
                        {
                            "group": "PRIVATE GROUP SHOULD NOT APPEAR",
                            "status": "PRIVATE STATUS SHOULD NOT APPEAR",
                            "reason": "PRIVATE REASON SHOULD NOT APPEAR",
                        },
                    ],
                ),
            ),
            _ledger(
                route="ephemeral_direct",
                post_turn_lifecycle=_post_turn_lifecycle(
                    status="skipped",
                    reason="ephemeral_direct_turn",
                    semantic_memory_policy="not_applicable",
                    background_tasks_scheduled=False,
                    task_count=0,
                    groups=[],
                ),
            ),
            _ledger(route="legacy_ledger_without_lifecycle"),
        ]
    )

    lifecycle = report["post_turn_lifecycle_ledger"]
    assert lifecycle["version"] == POST_TURN_LIFECYCLE_LEDGER_REPORT_VERSION
    assert lifecycle["event_count"] == 2
    assert lifecycle["missing_count"] == 1
    assert lifecycle["background_tasks_scheduled_count"] == 1
    assert lifecycle["background_tasks_skipped_count"] == 1
    assert lifecycle["status_counts"] == {"scheduled": 1, "skipped": 1}
    assert lifecycle["semantic_memory_policy_counts"] == {
        "extract_facts": 1,
        "not_applicable": 1,
    }
    assert lifecycle["background_schedule"]["event_count"] == 2
    assert lifecycle["background_schedule"]["task_count"] == 2
    assert lifecycle["background_schedule"]["group_counts"][
        "semantic_memory_interaction"
    ] == 1
    assert report["summary"]["post_turn_lifecycle_event_count"] == 2
    assert report["summary"]["post_turn_lifecycle_missing_count"] == 1
    assert lifecycle["privacy"] == {
        "raw_content_included": False,
        "identifier_strategy": "aggregate_counts_only",
    }

    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE GROUP SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE STATUS SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE REASON SHOULD NOT APPEAR" not in serialized
    assert "unknown_hash:" in serialized


def test_runtime_flow_doctor_alerts_on_subagent_boundary_raw_flag() -> None:
    report = build_runtime_flow_doctor_report(
        [
            _ledger(
                route="parallel_dispatch",
                subagents={
                    "schema_version": "wiii.subagent_boundary_trace.v1",
                    "report_count": 1,
                    "raw_content_included": True,
                    "warning_codes": ["subagent_result_boundary_warning"],
                    "reports": [
                        {
                            "agent_name": "PRIVATE CHILD AGENT SHOULD NOT APPEAR",
                            "state_projected_key_count": 2,
                            "state_dropped_key_count": 3,
                            "source_count": 1,
                            "tool_count": 0,
                            "thinking_dropped": False,
                        }
                    ],
                },
            )
        ]
    )

    assert report["status"] == "degraded"
    assert {alert["code"] for alert in report["alerts"]} == {
        "subagent_boundary_raw_content_flag",
        "subagent_boundary_warning",
    }
    assert report["subagents"]["raw_content_flag_count"] == 1
    assert report["subagents"]["warning_count"] == 1
    assert report["subagents"]["state_dropped_key_count"] == 3

    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE CHILD AGENT SHOULD NOT APPEAR" not in serialized


def test_runtime_flow_doctor_reports_blocked_without_ledgers() -> None:
    report = build_runtime_flow_doctor_report([])

    assert report["status"] == "blocked"
    assert report["alerts"] == [
        {
            "code": "runtime_flow_ledger_missing",
            "severity": "critical",
            "count": 0,
            "threshold": "turn_count==0",
        }
    ]
    assert report["summary"]["turn_count"] == 0
    assert report["summary"]["missing_done_count"] == 0
    assert report["request_correlation"]["request_id_present_count"] == 0


def test_runtime_flow_doctor_degrades_when_done_missing_or_raw_flagged() -> None:
    ledger = _ledger(route="casual_chat", done_seen=False)
    ledger["context"]["context_provenance"]["privacy"]["raw_content_included"] = True

    report = build_runtime_flow_doctor_report([ledger])

    assert report["status"] == "degraded"
    assert {alert["code"] for alert in report["alerts"]} == {
        "missing_done_event",
        "raw_content_flag",
    }
    assert report["summary"]["missing_done_count"] == 1
    assert report["summary"]["raw_content_flag_count"] == 1


def test_runtime_flow_doctor_hashes_unsafe_counter_tokens() -> None:
    report = build_runtime_flow_doctor_report(
        [
            _ledger(
                route="PRIVATE ROUTE SHOULD NOT APPEAR",
                warnings=["PRIVATE WARNING SHOULD NOT APPEAR"],
                suppressed=["PRIVATE TOOL SHOULD NOT APPEAR"],
                observed=["PRIVATE OBSERVED TOOL SHOULD NOT APPEAR"],
            )
        ]
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE ROUTE SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE WARNING SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE TOOL SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE OBSERVED TOOL SHOULD NOT APPEAR" not in serialized
    assert "unknown_hash:" in serialized


def test_runtime_flow_doctor_reports_request_correlation_without_raw_ids() -> None:
    report = build_runtime_flow_doctor_report(
        [
            _ledger(
                route="external_app_action",
                request_id="req-private-correlated",
                provider_call_correlation={
                    "provider_call_seen": True,
                    "request_id_present": True,
                    "stage_count": 2,
                    "stage_request_id_present_count": 2,
                    "stage_request_id_missing_count": 0,
                    "stage_request_id_match_count": 2,
                    "stage_request_id_mismatch_count": 0,
                },
            ),
            _ledger(
                route="external_app_action",
                request_id="req-private-partial",
                provider_call_correlation={
                    "provider_call_seen": True,
                    "request_id_present": True,
                    "stage_count": 2,
                    "stage_request_id_present_count": 1,
                    "stage_request_id_missing_count": 1,
                    "stage_request_id_match_count": 1,
                    "stage_request_id_mismatch_count": 0,
                },
            ),
            _ledger(route="casual_chat", request_id=""),
        ]
    )

    assert report["status"] == "degraded"
    assert {alert["code"] for alert in report["alerts"]} == {
        "missing_request_id",
        "provider_call_stage_request_id_missing",
    }
    assert report["request_correlation"] == {
        "request_id_present_count": 2,
        "missing_request_id_count": 1,
        "provider_call_turn_count": 2,
        "provider_call_correlated_turn_count": 1,
        "provider_call_uncorrelated_turn_count": 1,
        "provider_call_stage_count": 4,
        "provider_call_stage_request_id_present_count": 3,
        "provider_call_stage_request_id_missing_count": 1,
        "provider_call_stage_request_id_match_count": 3,
        "provider_call_stage_request_id_mismatch_count": 0,
        "identifier_strategy": "presence_counts_only",
    }

    serialized = json.dumps(report, ensure_ascii=False)
    assert "req-private-correlated" not in serialized
    assert "req-private-partial" not in serialized


def test_runtime_flow_doctor_extracts_ledgers_from_session_events() -> None:
    direct = _ledger(route="casual_chat")
    nested = _ledger(route="document_preview", uploaded_documents=1)

    ledgers = runtime_flow_ledgers_from_events(
        [
            {"payload": {"text": "raw prompt should be ignored"}},
            {"payload": {"runtime_flow_ledger": direct}},
            {"payload": {"content": {"runtime_flow_ledger": nested}}},
        ]
    )

    assert [ledger["route"]["lane"] for ledger in ledgers] == [
        "casual_chat",
        "document_preview",
    ]


def test_runtime_flow_doctor_alert_trend_buckets_recent_alert_codes() -> None:
    events = [
        {
            "created_at": "2026-05-31T10:15:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="external_app_action",
                    request_id="req-private-trend-a",
                    provider_call_correlation={
                        "provider_call_seen": True,
                        "request_id_present": True,
                        "stage_count": 1,
                        "stage_request_id_present_count": 0,
                        "stage_request_id_missing_count": 1,
                        "stage_request_id_match_count": 0,
                        "stage_request_id_mismatch_count": 0,
                    },
                )
            },
        },
        {
            "created_at": "2026-05-31T10:45:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="casual_chat",
                    request_id="",
                )
            },
        },
        {
            "created_at": "2026-05-31T11:01:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="casual_chat",
                    post_turn_lifecycle=_post_turn_lifecycle(),
                )
            },
        },
    ]

    trend = build_runtime_flow_alert_trend_from_events(events)

    assert trend["bucket_strategy"] == "event_created_at_hour"
    assert trend["identifier_strategy"] == "aggregate_counts_only"
    buckets = {bucket["bucket_start"]: bucket for bucket in trend["buckets"]}
    assert buckets["2026-05-31T10:00:00+00:00"]["turn_count"] == 2
    assert buckets["2026-05-31T10:00:00+00:00"]["alert_counts"] == {
        "missing_request_id": 1,
        "provider_call_stage_request_id_missing": 1,
    }
    assert buckets["2026-05-31T10:00:00+00:00"]["status_counts"] == {
        "degraded": 2
    }
    assert buckets["2026-05-31T11:00:00+00:00"]["alert_counts"] == {}

    serialized = json.dumps(trend, ensure_ascii=False)
    assert "req-private-trend-a" not in serialized


def test_runtime_flow_doctor_history_buckets_reports_without_raw_ids() -> None:
    events = [
        {
            "created_at": "2026-05-31T10:15:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="external_app_action",
                    request_id="req-private-history-a",
                    provider_call_correlation={
                        "provider_call_seen": True,
                        "request_id_present": True,
                        "stage_count": 1,
                        "stage_request_id_present_count": 0,
                        "stage_request_id_missing_count": 1,
                        "stage_request_id_match_count": 0,
                        "stage_request_id_mismatch_count": 0,
                    },
                )
            },
        },
        {
            "created_at": "2026-05-31T10:45:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="PRIVATE ROUTE SHOULD NOT APPEAR",
                    request_id="",
                    warnings=["PRIVATE WARNING SHOULD NOT APPEAR"],
                    subagents={
                        "schema_version": "wiii.subagent_boundary_trace.v1",
                        "report_count": 1,
                        "raw_content_included": False,
                        "warning_codes": ["state_top_level_keys_dropped"],
                        "reports": [
                            {
                                "agent_name": "PRIVATE CHILD AGENT",
                                "state_projected_key_count": 2,
                                "state_dropped_key_count": 3,
                                "source_count": 1,
                                "tool_count": 1,
                                "thinking_dropped": True,
                            }
                        ],
                    },
                )
            },
        },
        {
            "created_at": "2026-05-31T11:01:00+00:00",
            "payload": {
                "runtime_flow_ledger": _ledger(
                    route="casual_chat",
                    post_turn_lifecycle=_post_turn_lifecycle(),
                )
            },
        },
        {
            "created_at": "2026-05-31T11:05:00+00:00",
            "payload": {"text": "PRIVATE USER PROMPT"},
        },
    ]

    history = build_runtime_flow_doctor_history_from_events(events, bucket_limit=12)

    assert history["version"] == RUNTIME_FLOW_DOCTOR_HISTORY_VERSION
    assert history["bucket_strategy"] == "event_created_at_hour"
    assert history["identifier_strategy"] == "aggregate_counts_only"
    assert history["privacy"]["raw_content_included"] is False
    assert history["source"] == {
        "session_event_count": 4,
        "runtime_flow_ledger_event_count": 3,
        "bucket_count": 2,
        "bucket_limit": 12,
    }
    assert [bucket["bucket_start"] for bucket in history["buckets"]] == [
        "2026-05-31T11:00:00+00:00",
        "2026-05-31T10:00:00+00:00",
    ]
    latest, previous = history["buckets"]
    assert latest["status"] == "ready"
    assert latest["summary"]["turn_count"] == 1
    assert latest["routes"] == {"casual_chat": 1}
    assert latest["post_turn_lifecycle_ledger"]["event_count"] == 1
    assert history["post_turn_lifecycle_ledger"]["event_count"] == 1
    assert previous["status"] == "degraded"
    assert previous["summary"]["turn_count"] == 2
    assert previous["request_correlation"]["missing_request_id_count"] == 1
    assert previous["subagents"]["report_count"] == 1
    assert previous["subagents"]["state_dropped_key_count"] == 3
    assert previous["subagents"]["thinking_dropped_count"] == 1
    assert {alert["code"] for alert in previous["alerts"]} == {
        "missing_request_id",
        "provider_call_stage_request_id_missing",
        "context_warning",
        "subagent_boundary_warning",
    }

    serialized = json.dumps(history, ensure_ascii=False)
    assert "PRIVATE USER PROMPT" not in serialized
    assert "req-private-history-a" not in serialized
    assert "PRIVATE ROUTE SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE WARNING SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE CHILD AGENT" not in serialized


async def test_runtime_flow_doctor_history_from_session_log_is_org_scoped() -> None:
    class FakeLog:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def get_recent_events(self, **kwargs):
            self.calls.append(kwargs)
            return [
                {
                    "created_at": "2026-05-31T10:15:00+00:00",
                    "payload": {"runtime_flow_ledger": _ledger(route="casual_chat")},
                }
            ]

    log = FakeLog()

    history = await build_runtime_flow_doctor_history_from_session_log(
        log,
        org_id="org-private-history",
        limit=25,
        bucket_limit=3,
    )

    assert log.calls == [
        {
            "org_id": "org-private-history",
            "event_type": "runtime_flow_ledger",
            "limit": 25,
        }
    ]
    assert history["source"]["window"] == "recent_runtime_flow_ledger_history"
    assert history["source"]["org_scoped"] is True
    assert history["source"]["limit"] == 25
    assert history["source"]["bucket_count"] == 1
    serialized = json.dumps(history, ensure_ascii=False)
    assert "org-private-history" not in serialized


async def test_runtime_flow_doctor_report_from_session_log_is_org_scoped() -> None:
    log = InMemorySessionEventLog()
    await log.append(
        session_id="session-private-raw",
        org_id="org-A",
        event_type="user_message",
        payload={"text": "PRIVATE USER PROMPT"},
    )
    await log.append(
        session_id="session-private-raw",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger(route="casual_chat")},
    )
    await log.append(
        session_id="session-private-raw",
        org_id="org-B",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger(route="lms_document_preview")},
    )

    report = await build_runtime_flow_doctor_report_from_session_log(
        log,
        session_id="session-private-raw",
        org_id="org-A",
    )

    assert report["summary"]["turn_count"] == 1
    assert report["routes"] == {"casual_chat": 1}
    assert report["source"] == {
        "session_event_count": 2,
        "runtime_flow_ledger_event_count": 1,
        "since_seq": None,
        "org_scoped": True,
    }
    assert report["alert_trend"]["bucket_strategy"] == "event_created_at_hour"
    assert report["alert_trend"]["buckets"][0]["turn_count"] == 1
    serialized = json.dumps(report, ensure_ascii=False)
    assert "PRIVATE USER PROMPT" not in serialized
    assert "session-private-raw" not in serialized


async def test_recent_runtime_flow_doctor_report_is_org_scoped_without_ids() -> None:
    log = InMemorySessionEventLog()
    await log.append(
        session_id="session-private-a",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger(route="casual_chat")},
    )
    await log.append(
        session_id="session-private-b",
        org_id="org-B",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger(route="lms_document_preview")},
    )
    await log.append(
        session_id="session-private-c",
        org_id="org-A",
        event_type="runtime_flow_ledger",
        payload={"runtime_flow_ledger": _ledger(route="document_preview")},
    )

    report = await build_recent_runtime_flow_doctor_report_from_session_log(
        log,
        org_id="org-A",
        limit=10,
    )

    assert report["summary"]["turn_count"] == 2
    assert report["routes"] == {"document_preview": 1, "casual_chat": 1}
    assert report["source"] == {
        "session_event_count": 2,
        "runtime_flow_ledger_event_count": 2,
        "limit": 10,
        "org_scoped": True,
        "window": "recent_runtime_flow_ledger_events",
    }
    assert report["alert_trend"]["bucket_strategy"] == "event_created_at_hour"
    assert sum(
        bucket["turn_count"] for bucket in report["alert_trend"]["buckets"]
    ) == 2
    serialized = json.dumps(report, ensure_ascii=False)
    assert "session-private-a" not in serialized
    assert "session-private-b" not in serialized
    assert "session-private-c" not in serialized
