from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[2] / "scripts" / "wiii_runtime_flow_acceptance.py"
)
SPEC = importlib.util.spec_from_file_location(
    "wiii_runtime_flow_acceptance",
    SCRIPT_PATH,
)
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
assert SPEC.loader is not None
SPEC.loader.exec_module(acceptance)


def sample_trace(
    *,
    path: str = "casual_chat",
    visible_tools: list[str] | None = None,
    external_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "turn_path_decision": {
            "path": path,
            "reason": "unit-test",
        },
        "tool_policy_session": {
            "path": path,
            "visible_tool_names": visible_tools or [],
        },
        "external_app_action_plan": external_plan or {},
    }


def sample_context_provenance(
    *,
    uploaded_document_count: int = 0,
    document_source_ref_count: int = 0,
    semantic_memory_count: int | None = None,
    relevant_memory_count: int | None = None,
    memory_retrieval_status: str = "unknown",
    user_fact_count: int = 0,
    host_context_present: bool = False,
    host_capability_names: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    has_documents = uploaded_document_count > 0
    capabilities = (
        host_capability_names
        if host_capability_names is not None
        else (["lms"] if host_context_present else [])
    )
    return {
        "schema_version": acceptance.CONTEXT_PROVENANCE_SCHEMA_VERSION,
        "conversation": {
            "history_present": False,
            "history_char_count": 0,
            "history_item_count": None,
            "langchain_message_count": None,
            "summary_present": False,
            "summary_char_count": 0,
        },
        "documents": {
            "present": has_documents,
            "attachment_count": uploaded_document_count,
            "usable_attachment_count": uploaded_document_count,
            "total_markdown_chars": 120 if has_documents else 0,
            "truncated_count": 0,
            "parser_names": ["markitdown"] if has_documents else [],
            "parser_chain_names": ["mammoth"] if has_documents else [],
            "media_kinds": ["document"] if has_documents else [],
            "provenance_levels": ["page"] if has_documents else [],
            "attachment_id_hashes": ["sha256:1234567890abcdef"] if has_documents else [],
            "source_ref_count": document_source_ref_count,
            "source_ref_kinds": ["heading"] if document_source_ref_count else [],
        },
        "memory": {
            "semantic_context_present": bool(semantic_memory_count),
            "semantic_context_char_count": 80 if semantic_memory_count else 0,
            "semantic_memory_count": semantic_memory_count,
            "semantic_memory_types": ["preference"] if semantic_memory_count else [],
            "retrieval_present": memory_retrieval_status != "unknown",
            "retrieval_status": memory_retrieval_status,
            "relevant_memory_count": relevant_memory_count,
            "insight_count": 0,
            "fact_type_names": [],
            "insight_category_names": [],
            "user_fact_count": user_fact_count,
            "core_memory_present": False,
            "core_memory_char_count": 0,
        },
        "host": {
            "host_context_present": host_context_present,
            "surface": "embed_lms" if host_context_present else "unknown",
            "capability_names": capabilities,
            "available_action_count": None,
            "host_capabilities_present": host_context_present,
        },
        "warnings": warnings or [],
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def sample_context_payload(
    *,
    uploaded_document_count: int = 0,
    source_ref_count: int = 0,
    memory_context_count: int | None = None,
    provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "document_context_present": uploaded_document_count > 0,
        "uploaded_document_count": uploaded_document_count,
        "source_ref_count": source_ref_count,
        "memory_context_count": memory_context_count,
        "context_provenance": provenance
        or sample_context_provenance(
            uploaded_document_count=uploaded_document_count,
            document_source_ref_count=source_ref_count,
            semantic_memory_count=memory_context_count,
        ),
    }


def sample_post_turn_lifecycle() -> dict[str, object]:
    return {
        "schema_version": acceptance.POST_TURN_LIFECYCLE_SUMMARY_VERSION,
        "status": "scheduled",
        "reason": "post_turn_background_tasks_scheduled",
        "semantic_memory_policy": "extract_facts",
        "background_tasks_scheduled": True,
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }


def sample_ledger(
    *,
    observed_tools: list[str] | None = None,
    suppressed_tools: list[str] | None = None,
    context: dict[str, object] | None = None,
    request: dict[str, object] | None = None,
    host_actions: dict[str, object] | None = None,
    subagents: dict[str, object] | None = None,
    stream: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": acceptance.RUNTIME_FLOW_LEDGER_SCHEMA_VERSION,
        "request": request
        or {
            "host_surface": "unknown",
            "host_capabilities": [],
        },
        "context": context or sample_context_payload(),
        "tools": {
            "observed": observed_tools or [],
            "suppressed": suppressed_tools or [],
            "policy_session": {
                "visible_tool_names": [],
            },
        },
        "stream": stream
        or {
            "transport": "sse_v3",
            "event_counts": {"answer": 1, "metadata": 1, "done": 1},
            "event_sequence_tail": ["answer", "metadata", "done"],
            "metadata_seen": True,
            "done_seen": True,
        },
        "host_actions": host_actions
        or {
            "preview_required": False,
            "apply_attempted": False,
        },
        "subagents": subagents or {},
        "finalization": {
            "status": "saved",
            "error_type": None,
            "save_response_immediately": False,
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }


def scenario_result(
    scenario: object,
    *,
    trace: dict[str, object] | None = None,
    ledger: dict[str, object] | None = None,
    answer: str = "ok",
    events: list[object] | None = None,
) -> object:
    return acceptance.ScenarioResult(
        scenario=scenario,
        event_names=["answer", "metadata", "done"],
        answer=answer,
        trace=trace or sample_trace(path=scenario.expected_path),
        ledger=ledger or sample_ledger(),
        first_event_seconds=0.1,
        first_answer_seconds=0.2,
        total_seconds=0.3,
        events=events or [],
    )


def sample_doctor_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "wiii_connect_doctor.v0",
        "generated_at": "2026-05-30T00:00:00+00:00",
        "surface": "desktop",
        "status": "degraded",
        "summary": {
            "total_paths": 5,
            "ready_paths": 2,
            "guarded_paths": 1,
            "blocked_paths": 2,
            "total_connections": 8,
            "agent_ready_connections": 2,
            "external_provider_connections": 1,
            "external_agent_ready_connections": 0,
            "warning_count": 1,
        },
        "path_diagnostics": [
            {
                "path": "casual_chat",
                "status": "ready",
                "reason": "no_connection_required",
            },
            {
                "path": "weather_lookup",
                "status": "ready",
                "reason": "ready",
            },
            {
                "path": "external_app_action",
                "status": "blocked",
                "reason": "no_agent_ready_external_provider",
            },
            {
                "path": "lms_document_preview",
                "status": "blocked",
                "reason": "missing_required_connection",
            },
            {
                "path": "lms_document_apply",
                "status": "guarded",
                "reason": "approval_token_required",
            },
        ],
        "provider_diagnostics": [
            {
                "provider_slug": "facebook",
                "label": "Facebook",
                "provider_kind": "composio",
                "status": "guarded",
                "reason": "provider_adapter_not_bound",
                "connection_status": "connected",
                "active": True,
                "agent_ready": False,
                "connection_count": 1,
                "active_connection_count": 1,
                "action_count": 1,
                "scope_count": 1,
                "required_next": ["bind_provider_adapter"],
                "stages": [
                    {"key": "registry", "status": "ready", "reason": "registered"},
                    {"key": "adapter", "status": "blocked", "reason": "provider_adapter_not_bound"},
                    {"key": "account", "status": "ready", "reason": "connected"},
                    {"key": "agent_policy", "status": "blocked", "reason": "provider_not_agent_ready"},
                    {"key": "gateway", "status": "blocked", "reason": "provider_not_agent_ready"},
                ],
            }
        ],
        "top_blockers": ["path:external_app_action:no_agent_ready_external_provider"],
        "warnings": ["adapter_disabled"],
    }
    payload.update(overrides)
    return payload


def sample_snapshot_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": "wiii_connect_snapshot.v0",
        "generated_at": "2026-05-30T00:00:00+00:00",
        "surface": "desktop",
        "connections": [
            {
                "slug": "server",
                "label": "Server runtime",
                "status": "connected",
                "active": True,
                "agent_ready": True,
                "capabilities": ["chat"],
            },
            {
                "slug": "facebook",
                "label": "Facebook",
                "provider_kind": "composio",
                "status": "connected",
                "active": True,
                "agent_ready": False,
                "connection_count": 1,
                "active_connection_count": 1,
                "connection_ref_present": True,
                "scopes": {"read": True},
            },
        ],
        "path_capabilities": [
            {"path": "casual_chat", "allowed_connection_slugs": ["server"]},
            {"path": "weather_lookup", "allowed_connection_slugs": ["weather"]},
            {"path": "external_app_action", "allowed_connection_slugs": ["facebook"]},
            {"path": "lms_document_preview", "allowed_connection_slugs": ["lms_authoring"]},
            {"path": "lms_document_apply", "allowed_connection_slugs": ["lms_authoring"]},
        ],
        "capability_summary": {
            "active_connection_slugs": ["server", "facebook"],
            "agent_ready_connection_slugs": ["server"],
            "connected_provider_slugs": ["facebook"],
            "agent_ready_provider_slugs": [],
            "connected_scope_names": ["read"],
            "suppressed_tool_groups": ["host_action"],
            "path_readiness": [
                {
                    "path": "casual_chat",
                    "status": "ready",
                    "reason": "no_connection_required",
                },
                {
                    "path": "weather_lookup",
                    "status": "ready",
                    "reason": "ready",
                },
                {
                    "path": "external_app_action",
                    "status": "guarded",
                    "reason": "provider_adapter_not_bound",
                },
                {
                    "path": "lms_document_preview",
                    "status": "blocked",
                    "reason": "missing_required_connection",
                },
                {
                    "path": "lms_document_apply",
                    "status": "guarded",
                    "reason": "approval_token_required",
                },
            ],
        },
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def test_parse_sse_events_supports_multiline_data() -> None:
    raw = (
        "event: answer\n"
        "data: {\"content\":\"xin\"}\n\n"
        "event: metadata\n"
        "data: {\"a\":1,\n"
        "data: \"b\":2}\n\n"
    )

    events = acceptance.parse_sse_events(raw)

    assert [event.name for event in events] == ["answer", "metadata"]
    assert events[0].json() == {"content": "xin"}
    assert events[1].data == '{"a":1,\n"b":2}'


def test_runtime_trace_prefers_done_then_metadata() -> None:
    events = [
        acceptance.SseEvent(
            "metadata",
            json.dumps({"runtime_flow_trace": {"from": "metadata"}}),
        ),
        acceptance.SseEvent(
            "done",
            json.dumps({"runtime_flow_trace": {"from": "done"}}),
        ),
    ]

    assert acceptance.runtime_trace_from_events(events) == {"from": "done"}


def test_sync_stream_parity_accepts_matching_route_and_runtime_metadata() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parity_ok",
        prompt="hello",
        expected_path="casual_chat",
        sync_parity=True,
    )
    trace = sample_trace(path="casual_chat")
    ledger = sample_ledger(
        request={"host_surface": "unknown", "host_capabilities": []},
    )
    ledger["runtime"] = {
        "provider": "zhipu",
        "model": "glm-5",
        "runtime_authoritative": True,
    }
    result = scenario_result(scenario, trace=trace, ledger=ledger, answer="ok")
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "provider": "zhipu",
            "model": "glm-5",
            "agent_type": "chat",
            "runtime_flow_trace": trace,
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }

    acceptance.assert_sync_stream_parity_contract(
        scenario_id=scenario.id,
        scenario=scenario,
        sync_payload=sync_payload,
        stream_result=result,
    )


def test_sync_stream_parity_accepts_missing_provider_when_trace_matches() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parity_providerless_sync",
        prompt="hello",
        expected_path="casual_chat",
        sync_parity=True,
    )
    trace = sample_trace(path="casual_chat")
    ledger = sample_ledger(
        request={"host_surface": "unknown", "host_capabilities": []},
    )
    ledger["runtime"] = {
        "provider": "",
        "model": "glm-5",
        "runtime_authoritative": False,
    }
    result = scenario_result(scenario, trace=trace, ledger=ledger, answer="ok")
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "runtime_flow_trace": trace,
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }

    acceptance.assert_sync_stream_parity_contract(
        scenario_id=scenario.id,
        scenario=scenario,
        sync_payload=sync_payload,
        stream_result=result,
    )


def test_sync_stream_parity_rejects_route_mismatch() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parity_route_mismatch",
        prompt="hello",
        expected_path="casual_chat",
        sync_parity=True,
    )
    result = scenario_result(
        scenario,
        trace=sample_trace(path="casual_chat"),
        ledger=sample_ledger(),
        answer="ok",
    )
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "provider": "zhipu",
            "model": "glm-5",
            "agent_type": "chat",
            "runtime_flow_trace": sample_trace(path="external_app_action"),
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }

    with pytest.raises(acceptance.AcceptanceFailure, match="sync path"):
        acceptance.assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload=sync_payload,
            stream_result=result,
        )


def test_sync_stream_parity_rejects_missing_sync_metadata() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parity_missing_metadata",
        prompt="hello",
        expected_path="casual_chat",
        sync_parity=True,
    )
    result = scenario_result(scenario)

    with pytest.raises(acceptance.AcceptanceFailure, match="metadata is missing"):
        acceptance.assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload={"status": "success", "data": {"answer": "ok"}},
            stream_result=result,
        )


def test_sync_stream_parity_rejects_raw_post_turn_lifecycle_scope() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parity_raw_post_turn",
        prompt="hello",
        expected_path="casual_chat",
        sync_parity=True,
    )
    raw_lifecycle = sample_post_turn_lifecycle()
    raw_lifecycle["message"] = "PRIVATE PROMPT"
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "runtime_flow_trace": sample_trace(path="casual_chat"),
            "post_turn_lifecycle": raw_lifecycle,
        },
    }

    with pytest.raises(acceptance.AcceptanceFailure, match="exposes raw turn scope"):
        acceptance.assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload=sync_payload,
            stream_result=scenario_result(scenario),
        )


def test_sync_stream_parity_rejects_missing_required_sync_tool() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="weather_parity",
        prompt="thoi tiet",
        expected_path="weather_lookup",
        required_visible_tools=("tool_current_weather",),
    )
    result = scenario_result(
        scenario,
        trace=sample_trace(
            path="weather_lookup",
            visible_tools=["tool_current_weather"],
        ),
        answer="ok",
    )
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "provider": "zhipu",
            "model": "glm-5",
            "agent_type": "chat",
            "runtime_flow_trace": sample_trace(path="weather_lookup", visible_tools=[]),
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }

    with pytest.raises(acceptance.AcceptanceFailure, match="sync required visible tool"):
        acceptance.assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload=sync_payload,
            stream_result=result,
        )


def test_sync_stream_parity_rejects_missing_sync_external_plan() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="facebook_block_parity",
        prompt="dang facebook",
        expected_path="external_app_action",
        require_no_visible_tools=True,
        expected_external_plan_status="blocked",
        expected_external_provider="facebook",
        expected_external_kind="facebook_post_direct_apply",
    )
    stream_plan = {
        "status": "blocked",
        "provider_slug": "facebook",
        "kind": "facebook_post_direct_apply",
    }
    result = scenario_result(
        scenario,
        trace=sample_trace(path="external_app_action", external_plan=stream_plan),
        answer="ok",
    )
    sync_payload = {
        "status": "success",
        "data": {"answer": "ok"},
        "metadata": {
            "provider": "zhipu",
            "model": "glm-5",
            "agent_type": "chat",
            "runtime_flow_trace": sample_trace(path="external_app_action"),
            "post_turn_lifecycle": sample_post_turn_lifecycle(),
        },
    }

    with pytest.raises(acceptance.AcceptanceFailure, match="sync external plan status"):
        acceptance.assert_sync_stream_parity_contract(
            scenario_id=scenario.id,
            scenario=scenario,
            sync_payload=sync_payload,
            stream_result=result,
        )


def test_assert_scenario_result_passes_casual_no_tools() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
        require_no_visible_tools=True,
    )

    acceptance.assert_scenario_result(scenario_result(scenario))


def test_assert_scenario_result_rejects_saved_finalization_without_lifecycle() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
    )
    ledger = sample_ledger()
    ledger["finalization"]["post_turn_lifecycle"] = None

    with pytest.raises(acceptance.AcceptanceFailure, match="post_turn_lifecycle"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_wrong_path() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="path='web_search'"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(path="web_search"),
            )
        )


def test_assert_scenario_result_rejects_forbidden_tool() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="weather",
        prompt="thoi tiet",
        expected_path="weather_lookup",
        required_visible_tools=("tool_current_weather",),
        forbidden_tool_names=("tool_web_search",),
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden tool"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(
                    path="weather_lookup",
                    visible_tools=["tool_current_weather", "tool_web_search"],
                ),
            )
        )


def test_assert_scenario_result_rejects_global_diagnostic_tool_surface() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="external",
        prompt="doc gmail",
        expected_path="external_app_action",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden runtime tool"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(
                    path="external_app_action",
                    visible_tools=["tool_wiii_connect_execute_action"],
                ),
            )
        )


def test_assert_scenario_result_rejects_model_control_key_leaks() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="external",
        prompt="dang facebook",
        expected_path="external_app_action",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="model-control key"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace={
                    **sample_trace(path="external_app_action"),
                    "external_action_trace": {
                        "events": [
                            {
                                "type": "call",
                                "tool_name": "host_action__wiii_connect__facebook_post__direct_apply",
                                "page_id": "private_page",
                            }
                        ]
                    },
                },
            )
        )


def test_assert_scenario_result_rejects_sensitive_runtime_trace_keys() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="external",
        prompt="dang facebook",
        expected_path="external_app_action",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="sensitive key"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace={
                    **sample_trace(path="external_app_action"),
                    "external_app_action_plan": {
                        "connection_ref": "wcn_public_ref",
                    },
                },
            )
        )


def test_assert_scenario_result_rejects_sensitive_tool_call_event_args() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="external",
        prompt="dang facebook",
        expected_path="external_app_action",
    )
    events = [
        acceptance.SseEvent(
            "tool_call",
            json.dumps(
                {
                    "content": {
                        "name": "tool_wiii_connect_delegate_to_integration",
                        "args": {
                            "connection_ref": "wcn_public_ref",
                            "page_id": "private_page",
                            "safe": "ok",
                        },
                        "id": "tc_1",
                    }
                }
            ),
        )
    ]

    with pytest.raises(acceptance.AcceptanceFailure, match="sse_tool_call"):
        acceptance.assert_scenario_result(scenario_result(scenario, events=events))


def test_assert_scenario_result_rejects_sensitive_tool_result_event_payload() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="external",
        prompt="dang facebook",
        expected_path="external_app_action",
    )
    events = [
        acceptance.SseEvent(
            "tool_result",
            json.dumps(
                {
                    "content": {
                        "name": "tool_wiii_connect_delegate_to_integration",
                        "result": json.dumps(
                            {
                                "status": "action_completed",
                                "provider_payload": {
                                    "access_token": "raw-result-token-123456"
                                },
                                "fallback_html": "<script>raw-code</script>",
                            }
                        ),
                        "id": "tc_1",
                    }
                }
            ),
        )
    ]

    with pytest.raises(acceptance.AcceptanceFailure, match="sse_tool_result"):
        acceptance.assert_scenario_result(scenario_result(scenario, events=events))


def test_assert_scenario_result_accepts_redacted_tool_result_event_payload() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="code_studio",
        prompt="tao demo",
        expected_path="code_studio",
    )
    events = [
        acceptance.SseEvent(
            "tool_result",
            json.dumps(
                {
                    "content": {
                        "name": "tool_create_visual_code",
                        "result": json.dumps(
                            {
                                "status": "ok",
                                "fallback_html": {
                                    "redacted": True,
                                    "chars": 1234,
                                },
                                "summary": "Visual ready",
                            }
                        ),
                        "id": "tc_1",
                    }
                }
            ),
        )
    ]

    acceptance.assert_scenario_result(scenario_result(scenario, events=events))


def test_assert_scenario_result_checks_external_plan() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="facebook_block",
        prompt="dang facebook",
        expected_path="external_app_action",
        expected_external_plan_status="blocked",
        expected_external_provider="facebook",
        expected_external_kind="facebook_post_direct_apply",
    )

    acceptance.assert_scenario_result(
        scenario_result(
            scenario,
            trace=sample_trace(
                path="external_app_action",
                external_plan={
                    "status": "blocked",
                    "provider_slug": "facebook",
                    "kind": "facebook_post_direct_apply",
                },
            ),
            answer="Facebook cần Wiii Connect trước.",
        )
    )


def test_assert_scenario_result_checks_worker_outcome_and_final_answer_source() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="gmail_action",
        prompt="doc gmail",
        expected_path="external_app_action",
        expected_worker_outcome="completed",
        expected_final_answer_source="wiii_connect_action_result",
    )

    acceptance.assert_scenario_result(
        scenario_result(
            scenario,
            trace={
                **sample_trace(path="external_app_action"),
                "external_action_trace": {
                    "observed_action_result": True,
                    "worker_outcome": "completed",
                    "integration_worker": {
                        "result_classification": {
                            "outcome": "completed",
                        }
                    },
                },
                "final_answer": {
                    "source": "wiii_connect_action_result",
                    "status": "resolved",
                },
            },
            answer="Done.",
        )
    )


def test_assert_scenario_result_checks_subagent_boundary_contract() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parallel_subagent_boundary",
        prompt="phan tich bang nhieu subagent",
        expected_path="casual_chat",
        expected_min_subagent_reports=2,
        expected_subagent_warning_codes=("state_top_level_keys_dropped",),
    )
    ledger = sample_ledger(
        subagents={
            "schema_version": acceptance.SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
            "report_count": 2,
            "raw_content_included": False,
            "warning_codes": ["state_top_level_keys_dropped"],
            "reports": [
                {
                    "agent_name": "rag",
                    "agent_type": "retrieval",
                    "status": "success",
                    "handoff_schema_version": "wiii.subagent_handoff_boundary.v1",
                    "result_schema_version": "wiii.subagent_result_boundary.v1",
                    "state_projected_key_count": 4,
                    "state_dropped_key_count": 2,
                    "output_char_count": 96,
                    "source_count": 2,
                    "tool_count": 1,
                    "thinking_dropped": True,
                },
                {
                    "agent_name": "search",
                    "agent_type": "web",
                    "status": "success",
                    "handoff_schema_version": "wiii.subagent_handoff_boundary.v1",
                    "result_schema_version": "wiii.subagent_result_boundary.v1",
                    "state_projected_key_count": 3,
                    "state_dropped_key_count": 1,
                    "output_char_count": 72,
                    "source_count": 1,
                    "tool_count": 1,
                    "thinking_dropped": False,
                },
            ],
        }
    )

    acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_subagent_raw_boundary() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parallel_subagent_boundary",
        prompt="phan tich bang nhieu subagent",
        expected_path="casual_chat",
        expected_min_subagent_reports=1,
    )
    ledger = sample_ledger(
        subagents={
            "schema_version": acceptance.SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
            "report_count": 1,
            "raw_content_included": True,
            "warning_codes": [],
            "reports": [
                {
                    "agent_name": "rag",
                    "agent_type": "retrieval",
                    "status": "success",
                    "state_projected_key_count": 1,
                    "state_dropped_key_count": 0,
                    "output_char_count": 20,
                    "source_count": 0,
                    "tool_count": 0,
                    "thinking_dropped": False,
                }
            ],
        }
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="subagent raw content"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_subagent_raw_child_payload_key() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="parallel_subagent_boundary",
        prompt="phan tich bang nhieu subagent",
        expected_path="casual_chat",
    )
    ledger = sample_ledger(
        subagents={
            "schema_version": acceptance.SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
            "report_count": 1,
            "raw_content_included": False,
            "warning_codes": [],
            "reports": [
                {
                    "agent_name": "rag",
                    "agent_type": "retrieval",
                    "status": "success",
                    "state_projected_key_count": 1,
                    "state_dropped_key_count": 0,
                    "output_char_count": 20,
                    "source_count": 0,
                    "tool_count": 0,
                    "thinking_dropped": False,
                    "output": "PRIVATE CHILD OUTPUT SHOULD NOT PASS",
                }
            ],
        }
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="raw child payload"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_missing_worker_outcome() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="gmail_action",
        prompt="doc gmail",
        expected_path="external_app_action",
        expected_worker_outcome="completed",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="worker outcome"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace={
                    **sample_trace(path="external_app_action"),
                    "external_action_trace": {
                        "observed_action_result": True,
                        "worker_outcome": "preview_required",
                    },
                },
            )
        )


def test_assert_scenario_result_rejects_wrong_final_answer_source() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="gmail_action",
        prompt="doc gmail",
        expected_path="external_app_action",
        expected_final_answer_source="wiii_connect_action_result",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="final answer source"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace={
                    **sample_trace(path="external_app_action"),
                    "final_answer": {
                        "source": "missing_explicit_final_answer_source",
                    },
                },
            )
        )


def test_assert_scenario_result_rejects_raw_payload_leak() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="raw runtime marker"):
        acceptance.assert_scenario_result(
            scenario_result(scenario, answer='hello "tool_calls"')
        )


def test_assert_scenario_result_checks_suppressed_no_action_tools() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
        require_no_visible_tools=True,
        expected_suppressed_tools=(
            "host_action",
            "pointy_action",
            "visual_runtime",
            "code_studio",
        ),
    )
    ledger = sample_ledger(
        suppressed_tools=[
            "host_action",
            "pointy_action",
            "visual_runtime",
            "code_studio",
        ]
    )

    acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_checks_required_observed_tool_and_stream_events() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="visual_inline_figure_stream_replay",
        prompt="tao visual",
        expected_path="visual_generation",
        required_observed_tools=("visual_runtime",),
        expected_stream_events=("visual_open", "visual_commit"),
    )
    ledger = sample_ledger(
        observed_tools=["visual_runtime"],
        stream={
            "transport": "sse_v3",
            "event_counts": {
                "answer": 1,
                "metadata": 1,
                "visual_open": 1,
                "visual_commit": 1,
                "done": 1,
            },
            "event_sequence_tail": ["answer", "visual_open", "visual_commit", "done"],
            "metadata_seen": True,
            "done_seen": True,
        },
    )

    acceptance.assert_scenario_result(
        scenario_result(
            scenario,
            trace=sample_trace(path="visual_generation"),
            ledger=ledger,
        )
    )


def test_assert_scenario_result_rejects_missing_expected_stream_event() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="code_studio_app_stream_replay",
        prompt="tao mini app",
        expected_path="visual_generation",
        required_observed_tools=("code_studio",),
        expected_stream_events=("code_open", "code_complete"),
    )
    ledger = sample_ledger(
        observed_tools=["code_studio"],
        stream={
            "transport": "sse_v3",
            "event_counts": {
                "answer": 1,
                "metadata": 1,
                "code_open": 1,
                "done": 1,
            },
            "event_sequence_tail": ["answer", "code_open", "done"],
            "metadata_seen": True,
            "done_seen": True,
        },
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="code_complete"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(path="visual_generation"),
                ledger=ledger,
            )
        )


def test_assert_scenario_result_rejects_missing_required_observed_tool() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="visual_inline_figure_stream_replay",
        prompt="tao visual",
        expected_path="visual_generation",
        required_observed_tools=("visual_runtime",),
        expected_stream_events=("visual_open", "visual_commit"),
    )
    ledger = sample_ledger(
        observed_tools=[],
        stream={
            "transport": "sse_v3",
            "event_counts": {
                "answer": 1,
                "metadata": 1,
                "visual_open": 1,
                "visual_commit": 1,
                "done": 1,
            },
            "event_sequence_tail": ["answer", "visual_open", "visual_commit", "done"],
            "metadata_seen": True,
            "done_seen": True,
        },
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="required observed tool"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(path="visual_generation"),
                ledger=ledger,
            )
        )


def test_assert_scenario_result_rejects_forbidden_stream_event() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual_chat_no_tools",
        prompt="xin chao",
        expected_path="casual_chat",
        require_no_visible_tools=True,
        forbidden_stream_events=("pointy_action",),
    )
    ledger = sample_ledger(
        stream={
            "transport": "sse_v3",
            "event_counts": {
                "answer": 1,
                "metadata": 1,
                "pointy_action": 1,
                "done": 1,
            },
            "event_sequence_tail": ["answer", "pointy_action", "done"],
            "metadata_seen": True,
            "done_seen": True,
        },
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden stream event"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_missing_suppressed_no_action_tool() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
        expected_suppressed_tools=("pointy_action",),
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="expected suppressed tool"):
        acceptance.assert_scenario_result(
            scenario_result(scenario, ledger=sample_ledger(suppressed_tools=[]))
        )


def test_assert_scenario_result_rejects_terminal_ledger_without_done_seen() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
    )
    ledger = sample_ledger(
        stream={
            "transport": "sse_v3",
            "event_counts": {"answer": 1, "metadata": 1},
            "event_sequence_tail": ["answer", "metadata", "done"],
            "metadata_seen": True,
            "done_seen": False,
        }
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="done_seen"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_checks_terminal_context_provenance_document_memory() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document_memory",
        prompt="tom tat tai lieu va nho so thich cua toi",
        expected_path="casual_chat",
        expected_min_uploaded_documents=1,
        expected_min_source_refs=2,
        expected_min_memory_contexts=1,
    )
    ledger = sample_ledger(
        context=sample_context_payload(
            uploaded_document_count=1,
            source_ref_count=2,
            memory_context_count=1,
            provenance=sample_context_provenance(
                uploaded_document_count=1,
                document_source_ref_count=2,
                semantic_memory_count=1,
                host_context_present=True,
            ),
        )
    )

    acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_checks_memory_turn_retrieval_contract() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="semantic_memory_turn_context_replay",
        prompt="goi y cach on dua tren dieu ban da nho",
        expected_path="casual_chat",
        expected_min_memory_contexts=1,
        expected_memory_retrieval_status="ready",
        expected_min_relevant_memories=1,
    )
    ledger = sample_ledger(
        context=sample_context_payload(
            memory_context_count=1,
            provenance=sample_context_provenance(
                semantic_memory_count=1,
                relevant_memory_count=1,
                memory_retrieval_status="ready",
            ),
        )
    )

    acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_memory_turn_without_retrieved_memories() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="semantic_memory_turn_context_replay",
        prompt="goi y cach on dua tren dieu ban da nho",
        expected_path="casual_chat",
        expected_min_memory_contexts=1,
        expected_memory_retrieval_status="ready",
        expected_min_relevant_memories=1,
    )
    ledger = sample_ledger(
        context=sample_context_payload(
            memory_context_count=0,
            provenance=sample_context_provenance(
                semantic_memory_count=0,
                relevant_memory_count=0,
                memory_retrieval_status="degraded",
            ),
        )
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="memory retrieval status"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_checks_lms_document_preview_replay_contract() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document_preview_replay",
        prompt="tao preview_lesson_patch tu tai lieu",
        expected_path="lms_document_preview",
        expected_min_uploaded_documents=1,
        expected_min_source_refs=1,
        expected_document_media_kinds=("document",),
        expected_document_source_ref_kinds=("heading",),
        expected_host_surface="embed_lms",
        expected_host_capabilities=("lms", "host_action", "document_preview"),
        expect_preview_required=True,
        expect_no_apply_attempted=True,
    )
    ledger = sample_ledger(
        request={
            "host_surface": "embed_lms",
            "host_capabilities": ["lms", "host_action", "document_preview"],
        },
        host_actions={
            "preview_required": True,
            "preview_emitted": True,
            "apply_attempted": False,
        },
        context=sample_context_payload(
            uploaded_document_count=1,
            source_ref_count=1,
            provenance=sample_context_provenance(
                uploaded_document_count=1,
                document_source_ref_count=1,
                host_context_present=True,
                host_capability_names=[
                    "lms",
                    "host_action",
                    "document_preview",
                ],
            ),
        ),
    )

    acceptance.assert_scenario_result(
        scenario_result(
            scenario,
            trace=sample_trace(path="lms_document_preview"),
            ledger=ledger,
        )
    )


def test_assert_scenario_result_rejects_lms_preview_apply_attempt() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document_preview_replay",
        prompt="tao preview_lesson_patch tu tai lieu",
        expected_path="lms_document_preview",
        expected_host_surface="embed_lms",
        expected_host_capabilities=("lms", "host_action", "document_preview"),
        expect_preview_required=True,
        expect_no_apply_attempted=True,
    )
    ledger = sample_ledger(
        request={
            "host_surface": "embed_lms",
            "host_capabilities": ["lms", "host_action", "document_preview"],
        },
        host_actions={
            "preview_required": True,
            "apply_attempted": True,
        },
        context=sample_context_payload(
            uploaded_document_count=1,
            source_ref_count=1,
            provenance=sample_context_provenance(
                uploaded_document_count=1,
                document_source_ref_count=1,
                host_context_present=True,
                host_capability_names=[
                    "lms",
                    "host_action",
                    "document_preview",
                ],
            ),
        ),
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="apply attempted"):
        acceptance.assert_scenario_result(
            scenario_result(
                scenario,
                trace=sample_trace(path="lms_document_preview"),
                ledger=ledger,
            )
        )


def test_chat_payload_includes_source_backed_replay_context() -> None:
    scenario = next(
        item
        for item in acceptance.DEFAULT_SCENARIOS
        if item.id == "uploaded_document_lms_preview_source_replay"
    )
    harness = acceptance.RuntimeFlowAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8000",
            org_id="default",
            demo_role="teacher",
            session_id="unit",
            domain_id="maritime",
            thinking_effort="low",
            provider="",
            model="",
        )
    )
    harness.user = {"id": "user-1"}

    payload = harness.chat_payload(scenario)

    document_context = payload["user_context"]["document_context"]
    attachment = document_context["attachments"][0]
    assert payload["role"] == "teacher"
    assert attachment["markdown"]
    assert attachment["source_references"][0]["content_type"] == "heading"
    assert payload["user_context"]["host_context"]["surface"] == "embed_lms"


def test_default_scenarios_include_memory_turn_context_replay() -> None:
    scenario = next(
        item
        for item in acceptance.DEFAULT_SCENARIOS
        if item.id == "semantic_memory_turn_context_replay"
    )

    assert scenario.prelude_prompts
    assert scenario.require_no_visible_tools is True
    assert scenario.expected_min_memory_contexts == 1
    assert scenario.expected_memory_retrieval_status == "ready"
    assert scenario.expected_min_relevant_memories == 1


def test_default_scenarios_include_visual_and_code_studio_stream_replays() -> None:
    by_id = {scenario.id: scenario for scenario in acceptance.DEFAULT_SCENARIOS}

    visual = by_id["visual_inline_figure_stream_replay"]
    code_studio = by_id["code_studio_app_stream_replay"]

    assert visual.expected_path == "visual_generation"
    assert visual.required_visible_tools == ("tool_generate_visual",)
    assert visual.required_observed_tools == ("visual_runtime",)
    assert visual.expected_stream_events == ("visual_open", "visual_commit")
    assert code_studio.expected_path == "visual_generation"
    assert code_studio.required_visible_tools == ("tool_create_visual_code",)
    assert code_studio.required_observed_tools == ("code_studio",)
    assert code_studio.expected_stream_events == ("code_open", "code_complete")


def test_default_sync_parity_covers_weather_and_blocked_external_paths() -> None:
    by_id = {scenario.id: scenario for scenario in acceptance.DEFAULT_SCENARIOS}

    for scenario_id in (
        "casual_chat_no_tools",
        "weather_intent_weather_only",
        "facebook_connection_status_control_plane",
        "facebook_action_blocks_without_agent_ready_provider",
        "gmail_capability_status_control_plane",
        "external_action_missing_provider_blocks_before_tools",
    ):
        assert by_id[scenario_id].sync_parity is True

    assert by_id["facebook_action_continuation_blocks_without_agent_ready_provider"].sync_parity is False
    assert by_id["gmail_action_continuation_blocks_without_agent_ready_provider"].sync_parity is False


def test_default_casual_scenario_forbids_pointy_host_visual_and_code_events() -> None:
    scenario = next(
        item
        for item in acceptance.DEFAULT_SCENARIOS
        if item.id == "casual_chat_no_tools"
    )

    assert "pointy_action" in scenario.expected_suppressed_tools
    assert "pointy_action" in scenario.forbidden_stream_events
    assert "host_action" in scenario.forbidden_stream_events
    assert "visual_open" in scenario.forbidden_stream_events
    assert "code_open" in scenario.forbidden_stream_events


def test_assert_scenario_result_rejects_missing_context_provenance() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
    )
    ledger = sample_ledger(context={"uploaded_document_count": 0, "source_ref_count": 0})

    with pytest.raises(acceptance.AcceptanceFailure, match="context provenance ledger missing"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_raw_context_payload_keys() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document",
        prompt="tom tat tai lieu",
        expected_path="casual_chat",
    )
    provenance = sample_context_provenance(uploaded_document_count=1)
    provenance["documents"]["file_name"] = "private.pdf"
    ledger = sample_ledger(
        context=sample_context_payload(
            uploaded_document_count=1,
            provenance=provenance,
        )
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="raw context key"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_unhashed_context_attachment_ids() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document",
        prompt="tom tat tai lieu",
        expected_path="casual_chat",
    )
    provenance = sample_context_provenance(uploaded_document_count=1)
    provenance["documents"]["attachment_id_hashes"] = ["private.pdf"]
    ledger = sample_ledger(
        context=sample_context_payload(
            uploaded_document_count=1,
            provenance=provenance,
        )
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="unhashed attachment"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_assert_scenario_result_rejects_source_backed_context_gap() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="document_memory",
        prompt="tom tat tai lieu",
        expected_path="casual_chat",
        expected_min_uploaded_documents=1,
        expected_min_source_refs=1,
    )
    ledger = sample_ledger(
        context=sample_context_payload(
            uploaded_document_count=1,
            source_ref_count=0,
            provenance=sample_context_provenance(
                uploaded_document_count=1,
                document_source_ref_count=0,
                warnings=["document_context_without_source_refs"],
            ),
        )
    )

    with pytest.raises(acceptance.AcceptanceFailure, match="source refs=0"):
        acceptance.assert_scenario_result(scenario_result(scenario, ledger=ledger))


def test_redact_for_log_removes_tokens_connection_refs_and_payloads() -> None:
    payload = {
        "access_token": "secret-token",
        "connection_ref": "wcn_public_ref",
        "provider_payload": {"text": "raw"},
        "safe": "visible",
        "nested": ["Bearer abc", "ok"],
    }

    redacted = acceptance.redact_for_log(payload)
    serialized = acceptance.json_for_log(payload)

    assert redacted["access_token"] == "[redacted]"
    assert redacted["connection_ref"] == "[redacted]"
    assert redacted["provider_payload"] == "[redacted]"
    assert redacted["safe"] == "visible"
    assert redacted["nested"][0] == "[redacted]"
    assert "secret-token" not in serialized
    assert "wcn_public_ref" not in serialized


def test_assert_doctor_contract_accepts_openhuman_style_lifecycle() -> None:
    acceptance.assert_doctor_contract(sample_doctor_payload())


def test_assert_doctor_contract_rejects_provider_without_gateway_stage() -> None:
    payload = sample_doctor_payload()
    provider = payload["provider_diagnostics"][0]
    provider["stages"] = [
        stage for stage in provider["stages"] if stage["key"] != "gateway"
    ]

    with pytest.raises(acceptance.AcceptanceFailure, match="gateway"):
        acceptance.assert_doctor_contract(payload)


def test_assert_doctor_contract_rejects_sensitive_refs() -> None:
    payload = sample_doctor_payload()
    provider = payload["provider_diagnostics"][0]
    provider["connection_ref"] = "wcn_public_ref"

    with pytest.raises(acceptance.AcceptanceFailure, match="sensitive"):
        acceptance.assert_doctor_contract(payload)


def test_validate_evidence_path_rejects_forbidden_locations() -> None:
    with pytest.raises(acceptance.AcceptanceFailure, match="forbidden"):
        acceptance.validate_evidence_path("logs/runtime-flow.json")
    with pytest.raises(acceptance.AcceptanceFailure, match="end with .json"):
        acceptance.validate_evidence_path("tmp/runtime-flow.txt")


def test_redaction_preserves_safe_token_flags_but_redacts_raw_tokens() -> None:
    payload = {
        "approval_token_present": True,
        "approval_token_hash": "sha256:abc123",
        "approval_token": "raw-approval-secret",
    }

    redacted = acceptance.redact_for_log(payload)

    assert redacted["approval_token_present"] is True
    assert redacted["approval_token_hash"] == "sha256:abc123"
    assert redacted["approval_token"] == "[redacted]"
    acceptance.assert_no_sensitive_payload(
        {
            "approval_token_present": True,
            "approval_token_hash": "sha256:abc123",
        },
        path="unit",
    )


def test_evidence_payload_includes_browser_replay_terminal_metadata_without_raw_text() -> None:
    scenario = acceptance.ScenarioExpectation(
        id="browser_replay_unit",
        prompt="private prompt that must not be exported",
        expected_path="casual_chat",
    )
    ledger = sample_ledger(
        request={
            "host_surface": "embed_lms",
            "host_capabilities": ["lms", "host_action"],
        },
        host_actions={
            "preview_required": True,
            "apply_attempted": False,
            "approval_token_present": True,
            "approval_token_hash": "sha256:previewhash",
        },
    )
    result = scenario_result(
        scenario,
        trace=sample_trace(path="casual_chat"),
        ledger=ledger,
        answer="private answer that must not be exported",
    )
    harness = acceptance.RuntimeFlowAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8000",
            target_env="unit",
            commit_sha="abc123",
            org_id="org-1",
        )
    )
    harness.doctor_payload = sample_doctor_payload()
    harness.wiii_connect_snapshot_payload = sample_snapshot_payload()
    harness.results = [result]

    evidence = harness.evidence_payload()
    replay = evidence["browser_replay"]
    case = replay["cases"][0]
    capability = evidence["wiii_connect_capability"]
    rendered_replay = json.dumps(replay, ensure_ascii=False, sort_keys=True)
    rendered_capability = json.dumps(capability, ensure_ascii=False, sort_keys=True)
    rendered_summary = json.dumps(evidence["scenarios"], ensure_ascii=False, sort_keys=True)

    assert replay["schema"] == acceptance.BROWSER_REPLAY_SCHEMA_VERSION
    assert capability["snapshot_version"] == "wiii_connect_snapshot.v0"
    assert capability["connected_provider_count"] == 1
    assert capability["connected_scope_count"] == 1
    assert capability["raw_content_included"] is False
    assert capability["identifier_strategy"] == "hash_or_count_only"
    assert case["assistant_content"] == "Runtime flow acceptance evidence replay."
    assert case["assistant_metadata"]["runtime_flow_ledger"]["host_actions"][
        "approval_token_present"
    ] is True
    assert case["assistant_metadata"]["runtime_flow_ledger"]["host_actions"][
        "approval_token_hash"
    ] == "sha256:previewhash"
    assert "private prompt" not in rendered_replay
    assert "private answer" not in rendered_replay
    assert '"facebook"' not in rendered_capability
    assert '"read"' not in rendered_capability
    assert "provider_adapter_not_bound" not in rendered_capability
    assert "answer_hash" in rendered_summary
    assert "private answer" not in rendered_summary


def test_write_evidence_json_uses_shared_runtime_output_helper(monkeypatch, tmp_path) -> None:
    evidence_path = tmp_path / "runtime-flow-evidence.json"
    captured: dict[str, object] = {}
    harness = acceptance.RuntimeFlowAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8000",
            target_env="unit",
            commit_sha="abc123",
            org_id="org-1",
            evidence_json=str(evidence_path),
        )
    )
    harness.doctor_payload = sample_doctor_payload()
    harness.wiii_connect_snapshot_payload = sample_snapshot_payload()
    harness.results = []

    def fake_emit_json_payload(payload, out_path=None):
        captured["payload"] = payload
        captured["out_path"] = out_path

    monkeypatch.setattr(acceptance, "emit_json_payload", fake_emit_json_payload)

    harness.write_evidence_json()

    assert captured["out_path"] == evidence_path
    assert captured["payload"]["schema"] == acceptance.TRACE_VERSION
    assert not evidence_path.exists()


def test_write_evidence_json_rejects_symlink_output_target(tmp_path) -> None:
    target_path = tmp_path / "target.json"
    target_path.write_text("keep\n", encoding="utf-8")
    evidence_path = tmp_path / "runtime-flow-evidence.json"
    try:
        os.symlink(target_path, evidence_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink not available: {exc}")

    harness = acceptance.RuntimeFlowAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8000",
            target_env="unit",
            commit_sha="abc123",
            org_id="org-1",
            evidence_json=str(evidence_path),
        )
    )
    harness.doctor_payload = sample_doctor_payload()
    harness.wiii_connect_snapshot_payload = sample_snapshot_payload()
    harness.results = []

    with pytest.raises(ValueError, match="must not be a symlink"):
        harness.write_evidence_json()

    assert target_path.read_text(encoding="utf-8") == "keep\n"


def test_wiii_connect_snapshot_contract_requires_hash_count_capability_summary() -> None:
    payload = sample_snapshot_payload()

    acceptance.assert_wiii_connect_snapshot_contract(payload)
    summary = acceptance.wiii_connect_capability_summary_from_snapshot(payload)
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)

    assert summary["connection_count"] == 2
    assert summary["path_readiness_count"] == 5
    assert summary["connected_provider_count"] == 1
    assert summary["connected_scope_count"] == 1
    assert summary["path_status_counts"]["guarded"] == 2
    assert '"facebook"' not in rendered
    assert '"read"' not in rendered
    assert "provider_adapter_not_bound" not in rendered


def test_wiii_connect_snapshot_contract_allows_authorization_readiness_flags() -> None:
    payload = sample_snapshot_payload()
    connections = payload["connections"]
    assert isinstance(connections, list)
    facebook = connections[1]
    assert isinstance(facebook, dict)
    facebook["adapter_authorization_ready"] = False

    acceptance.assert_wiii_connect_snapshot_contract(payload)


def test_wiii_connect_snapshot_contract_rejects_agent_ready_provider_without_connection() -> None:
    payload = sample_snapshot_payload()
    payload["capability_summary"]["agent_ready_provider_slugs"] = ["gmail"]

    with pytest.raises(acceptance.AcceptanceFailure, match="subset"):
        acceptance.assert_wiii_connect_snapshot_contract(payload)


def test_selected_scenarios_accepts_comma_separated_ids() -> None:
    selected = acceptance.selected_scenarios(
        "casual_chat_no_tools,facebook_connection_status_control_plane"
    )

    assert [scenario.id for scenario in selected] == [
        "casual_chat_no_tools",
        "facebook_connection_status_control_plane",
    ]


def test_run_scenario_uses_sse_trace(monkeypatch) -> None:
    trace = sample_trace(path="casual_chat")
    ledger = sample_ledger(
        context=sample_context_payload(
            uploaded_document_count=1,
            source_ref_count=1,
            memory_context_count=1,
            provenance=sample_context_provenance(
                uploaded_document_count=1,
                document_source_ref_count=1,
                semantic_memory_count=1,
            ),
        )
    )
    events = [
        acceptance.SseEvent("answer", json.dumps({"content": "xin chao"})),
        acceptance.SseEvent("metadata", json.dumps({"runtime_flow_trace": trace})),
        acceptance.SseEvent("done", json.dumps({"runtime_flow_ledger": ledger})),
    ]

    def fake_request_sse_events(*_args, **_kwargs):
        return acceptance.SseReadResult(
            events=events,
            first_event_seconds=0.1,
            first_answer_seconds=0.2,
            total_seconds=0.3,
        )

    monkeypatch.setattr(acceptance, "request_sse_events", fake_request_sse_events)
    harness = acceptance.RuntimeFlowAcceptance(
        SimpleNamespace(
            backend_url="http://localhost:8000",
            org_id="default",
            demo_role="admin",
            session_id="unit",
            domain_id="maritime",
            thinking_effort="low",
            provider="",
            model="",
            stream_idle_timeout=1.0,
            stream_timeout=3.0,
        )
    )
    harness.token = "token"
    harness.user = {"id": "user-1"}
    scenario = acceptance.ScenarioExpectation(
        id="casual",
        prompt="xin chao",
        expected_path="casual_chat",
        require_no_visible_tools=True,
        expected_min_uploaded_documents=1,
        expected_min_source_refs=1,
        expected_min_memory_contexts=1,
    )

    detail = harness.run_scenario(scenario)

    assert "path=casual_chat" in detail
    assert harness.results[0].answer == "xin chao"
