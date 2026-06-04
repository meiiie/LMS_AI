from __future__ import annotations

import json
from types import SimpleNamespace

from app.engine.multi_agent.runtime_flow_ledger import (
    RuntimeFlowLedger,
    RUNTIME_FLOW_TRACE_VERSION,
    SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
    build_runtime_flow_trace_from_state,
    sanitize_runtime_flow_trace,
)


def test_runtime_flow_ledger_records_host_action_result_without_raw_payload() -> None:
    ledger = RuntimeFlowLedger(request_id="req-host-result")

    ledger.record_event(
        SimpleNamespace(
            type="host_action_result",
            content={
                "action": "wiii_connect.facebook_post.direct_apply",
                "status": "action_completed",
                "success": True,
                "approval_token": "raw-approval-token",
                "data": {
                    "provider_post_id": "safe-post-id",
                    "access_token": "raw-provider-token",
                },
            },
        )
    )

    payload = ledger.to_payload()

    assert "wiii_connect.facebook_post.direct_apply" in payload["tools"]["observed"]
    assert "host_action" not in payload["tools"]["suppressed"]
    assert payload["stream"]["event_counts"]["host_action_result"] == 1
    assert payload["host_actions"]["apply_attempted"] is True
    assert payload["host_actions"]["result_received"] is True
    assert payload["host_actions"]["result_success"] is True
    assert payload["host_actions"]["result_statuses"] == ["action_completed"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "raw-approval-token" not in serialized
    assert "raw-provider-token" not in serialized


def test_runtime_flow_ledger_records_post_turn_lifecycle_without_raw_scope() -> None:
    ledger = RuntimeFlowLedger(request_id="req-post-turn")

    ledger.mark_finalization(
        "saved",
        save_response_immediately=False,
        post_turn_lifecycle={
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
                        "group": "PRIVATE GROUP SHOULD NOT APPEAR",
                        "status": "PRIVATE STATUS SHOULD NOT APPEAR",
                        "reason": "PRIVATE REASON SHOULD NOT APPEAR",
                    },
                ],
                "privacy": {
                    "raw_content_included": False,
                    "identifier_strategy": "status_only",
                },
            },
            "message": "PRIVATE PROMPT",
            "response_text": "PRIVATE RESPONSE",
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        },
    )

    payload = ledger.to_payload()

    lifecycle = payload["finalization"]["post_turn_lifecycle"]
    assert lifecycle["schema_version"] == "wiii.post_turn_lifecycle.v1"
    assert lifecycle["status"] == "scheduled"
    assert lifecycle["background_schedule"]["task_count"] == 2
    assert lifecycle["background_schedule"]["groups"][0] == {
        "group": "semantic_memory_interaction",
        "status": "scheduled",
        "reason": "extract_facts",
    }
    assert "message" not in lifecycle
    assert "response_text" not in lifecycle
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "PRIVATE PROMPT" not in serialized
    assert "PRIVATE RESPONSE" not in serialized
    assert "PRIVATE GROUP SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE STATUS SHOULD NOT APPEAR" not in serialized
    assert "PRIVATE REASON SHOULD NOT APPEAR" not in serialized
    assert "unknown_hash:" in serialized


def test_runtime_flow_ledger_observes_policy_and_external_action_trace() -> None:
    state = {
        "_turn_path_decision": {
            "version": "turn_path_decision.v1",
            "path": "external_app_action",
            "reason": "external_app_action_request",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "allowed_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
        },
        "_tool_policy_session": {
            "version": "tool_policy_session.v1",
            "path": "external_app_action",
            "reason": "external_app_action_request",
            "bind_tools": True,
            "force_tools": True,
            "allow_all_tools": False,
            "candidate_tool_names": [
                "tool_web_search",
                "host_action__wiii_connect__facebook_post__direct_apply",
            ],
            "visible_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
            "tool_capabilities": {
                "host_action__wiii_connect__facebook_post__direct_apply": {
                    "group": "external_app_action",
                    "permission": "write",
                    "required_connection": "facebook",
                    "requires_agent_ready": True,
                    "mutates_state": True,
                }
            },
            "connection_status": {
                "facebook": {
                    "status": "connected",
                    "active": True,
                    "agent_ready": True,
                    "connection_lifecycle": {
                        "version": "wiii_connect_connection_lifecycle.v1",
                        "provider_slug": "facebook",
                        "status": "connected",
                        "reason": "connected",
                        "connection_present": True,
                        "ready_to_execute_action": True,
                        "access_token": "raw-provider-token",
                    },
                }
            },
            "external_app_action_plan": {
                "version": "external_app_action_plan.v1",
                "status": "ready",
                "kind": "facebook_post_direct_apply",
                "provider_slug": "facebook",
                "connection_lifecycle": {
                    "version": "wiii_connect_connection_lifecycle.v1",
                    "provider_slug": "facebook",
                    "status": "connected",
                    "reason": "connected",
                    "connection_present": True,
                    "ready_to_execute_action": True,
                    "account_label": "private@example.test",
                    "access_token": "raw-provider-token",
                },
            },
            "external_app_integration_lane": {
                "version": "external_app_integration_lane.v1",
                "status": "ready",
                "executor": "specialized_direct_tool",
                "provider_slug": "facebook",
            },
        },
        "_external_app_action_plan": {
            "version": "external_app_action_plan.v1",
            "status": "ready",
            "kind": "facebook_post_direct_apply",
            "provider_slug": "facebook",
            "action_slug": "wiii_connect.facebook_post.direct_apply",
            "forced_tool_name": "host_action__wiii_connect__facebook_post__direct_apply",
            "connection_lifecycle": {
                "version": "wiii_connect_connection_lifecycle.v1",
                "provider_slug": "facebook",
                "status": "connected",
                "reason": "connected",
                "connection_present": True,
                "ready_to_execute_action": True,
                "account_label": "private@example.test",
                "access_token": "raw-provider-token",
            },
        },
        "_external_app_integration_lane": {
            "version": "external_app_integration_lane.v1",
            "status": "ready",
            "executor": "specialized_direct_tool",
            "provider_slug": "facebook",
            "action_slug": "wiii_connect.facebook_post.direct_apply",
            "visible_tool_names": [
                "host_action__wiii_connect__facebook_post__direct_apply"
            ],
        },
        "_final_answer_trace": {
            "version": "final_answer_trace.v1",
            "source": "wiii_connect_action_result",
            "reason": "external_app_action_payload",
            "status": "resolved",
            "answer_present": True,
        },
        "tool_call_events": [
            {
                "type": "call",
                "name": "tool_web_search",
                "policy": {
                    "allowed": False,
                    "path": "external_app_action",
                    "reason": "not_visible_in_bound_tool_set",
                },
            },
            {
                "type": "result",
                "name": "host_action__wiii_connect__facebook_post__direct_apply",
                "result": json.dumps(
                    {
                        "version": "wiii_connect_facebook_direct_tool.v1",
                        "status": "action_completed",
                        "success": True,
                        "summary": "Posted.",
                        "provider_slug": "facebook",
                        "action": "wiii_connect.facebook_post.direct_apply",
                        "action_slug": "FACEBOOK_CREATE_POST",
                        "gateway": {
                            "version": "wiii_connect_execution_gateway.v1",
                            "status": "allowed",
                            "reason": "allowed",
                            "connection_present": True,
                            "audit_persistent": True,
                            "decision": {
                                "provider_slug": "facebook",
                                "action_slug": "FACEBOOK_CREATE_POST",
                                "path": "external_app_action",
                            },
                        },
                        "data": {
                            "access_token": "raw-provider-token",
                            "approval_token": "raw-approval-token",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    trace = build_runtime_flow_trace_from_state(state)
    ledger = RuntimeFlowLedger(request_id="req-trace")

    ledger.observe_metadata({"runtime_flow_trace": trace})
    payload = ledger.to_payload()

    assert trace["version"] == RUNTIME_FLOW_TRACE_VERSION
    assert payload["route"]["lane"] == "external_app_action"
    assert (
        payload["route"]["turn_path_decision"]["path"]
        == "external_app_action"
    )
    assert payload["tools"]["policy_session"]["visible_tool_names"] == [
        "host_action__wiii_connect__facebook_post__direct_apply"
    ]
    assert (
        trace["tool_policy_session"]["connection_status"]["facebook"][
            "connection_lifecycle"
        ]["status"]
        == "connected"
    )
    assert (
        payload["tools"]["policy_session"]["connection_status"]["facebook"][
            "connection_lifecycle"
        ]["ready_to_execute_action"]
        is True
    )
    assert (
        trace["tool_policy_session"]["external_app_action_plan"][
            "connection_lifecycle"
        ]["status"]
        == "connected"
    )
    assert (
        "account_label"
        not in payload["tools"]["policy_session"]["external_app_action_plan"][
            "connection_lifecycle"
        ]
    )
    assert (
        payload["tools"]["policy_session"]["external_app_integration_lane"][
            "executor"
        ]
        == "specialized_direct_tool"
    )
    assert (
        trace["external_app_action_plan"]["connection_lifecycle"]["status"]
        == "connected"
    )
    assert (
        payload["external_app"]["action_plan"]["connection_lifecycle"][
            "ready_to_execute_action"
        ]
        is True
    )
    assert (
        "account_label"
        not in payload["external_app"]["action_plan"]["connection_lifecycle"]
    )
    assert payload["tools"]["policy_denials"] == [
        {
            "tool_name": "tool_web_search",
            "path": "external_app_action",
            "reason": "not_visible_in_bound_tool_set",
        }
    ]
    external_trace = payload["external_app"]["action_trace"]
    assert external_trace["observed_action_result"] is True
    assert external_trace["last_status"] == "action_completed"
    assert external_trace["last_success"] is True
    assert external_trace["provider_slug"] == "facebook"
    assert external_trace["gateway"]["status"] == "allowed"
    assert payload["final_answer"]["source"] == "wiii_connect_action_result"


def test_runtime_flow_trace_counts_subagent_boundaries_without_raw_child_payload() -> None:
    trace = build_runtime_flow_trace_from_state(
        {
            "subagent_reports": [
                {
                    "agent_name": "rag",
                    "agent_type": "retrieval",
                    "summary": "raw child answer Bearer raw-child-token-123",
                    "result": {
                        "status": "success",
                        "output": "raw child output Bearer raw-output-token-123",
                        "boundary": {
                            "schema_version": "wiii.subagent_execution_boundary.v1",
                            "handoff": {
                                "schema_version": "wiii.subagent_handoff_boundary.v1",
                                "state": {
                                    "projected_key_count": 4,
                                    "dropped_key_count": 6,
                                },
                                "raw_content_included": False,
                                "warning_codes": ["state_top_level_keys_dropped"],
                            },
                            "result": {
                                "schema_version": "wiii.subagent_result_boundary.v1",
                                "status": "success",
                                "output_char_count": 128,
                                "source_count": 2,
                                "tool_count": 1,
                                "thinking_dropped": True,
                                "raw_content_included": False,
                                "warning_codes": ["subagent_thinking_dropped"],
                            },
                            "raw_content_included": False,
                            "warning_codes": [
                                "state_top_level_keys_dropped",
                                "subagent_thinking_dropped",
                            ],
                        },
                    },
                }
            ]
        }
    )
    ledger = RuntimeFlowLedger(request_id="req-subagent")
    ledger.observe_metadata({"runtime_flow_trace": trace})
    payload = ledger.to_payload()

    subagents = payload["subagents"]
    assert subagents["schema_version"] == SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION
    assert subagents["report_count"] == 1
    assert subagents["raw_content_included"] is False
    assert "state_top_level_keys_dropped" in subagents["warning_codes"]
    assert "subagent_thinking_dropped" in subagents["warning_codes"]
    report = subagents["reports"][0]
    assert report["agent_name"] == "rag"
    assert report["state_projected_key_count"] == 4
    assert report["state_dropped_key_count"] == 6
    assert report["output_char_count"] == 128
    assert report["source_count"] == 2
    assert report["tool_count"] == 1
    assert report["thinking_dropped"] is True

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "raw-child-token-123" not in serialized
    assert "raw-output-token-123" not in serialized

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "raw-provider-token" not in serialized
    assert "raw-approval-token" not in serialized


def test_runtime_flow_trace_flags_external_action_without_final_answer_source() -> None:
    trace = build_runtime_flow_trace_from_state(
        {
            "tool_call_events": [
                {
                    "type": "result",
                    "name": "tool_wiii_connect_delegate_to_integration",
                    "result": json.dumps(
                        {
                            "version": "wiii_connect_generic_direct_tool.v1",
                            "status": "action_completed",
                            "success": True,
                            "provider_slug": "gmail",
                            "summary": "Done.",
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    )

    assert trace["external_action_trace"]["observed_action_result"] is True
    assert trace["final_answer"]["source"] == (
        "missing_explicit_final_answer_source"
    )


def test_runtime_flow_trace_ignores_catalog_only_external_payload() -> None:
    trace = build_runtime_flow_trace_from_state(
        {
            "tool_call_events": [
                {
                    "type": "result",
                    "name": "tool_wiii_connect_list_actions",
                    "result": json.dumps(
                        {
                            "version": "wiii_connect_generic_direct_tool.v1",
                            "status": "action_completed",
                            "success": True,
                            "summary": "Action catalog loaded.",
                            "provider_slug": "gmail",
                            "data": {
                                "action_catalog": {
                                    "provider_slug": "gmail",
                                    "actions": [{"slug": "GMAIL_FETCH_EMAILS"}],
                                },
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    )

    action_trace = trace["external_action_trace"]
    assert action_trace["observed_action_result"] is False
    assert "last_status" not in action_trace
    assert trace["final_answer"] == {}


def test_runtime_flow_trace_promotes_integration_worker_classification() -> None:
    trace = build_runtime_flow_trace_from_state(
        {
            "tool_call_events": [
                {
                    "type": "result",
                    "name": "tool_wiii_connect_delegate_to_integration",
                    "result": json.dumps(
                        {
                            "version": "wiii_connect_integration_delegate_tool.v1",
                            "status": "preview_required",
                            "success": False,
                            "provider_slug": "facebook",
                            "action_slug": "FACEBOOK_CREATE_POST",
                            "data": {
                                "integration_worker": {
                                    "version": "wiii_connect_integration_worker.v1",
                                    "status": "ready",
                                    "reason": "selected_explicit_action",
                                    "executor": "provider_worker",
                                    "provider_slug": "facebook",
                                    "action_slug": "FACEBOOK_CREATE_POST",
                                    "stage_sequence": [
                                        "provider_gate",
                                        "action_policy",
                                        "ready",
                                    ],
                                    "result_classification": {
                                        "outcome": "preview_required",
                                        "status": "preview_required",
                                        "reason": "missing_preview_evidence",
                                        "failed_stage": "preview",
                                        "provider_slug": "facebook",
                                        "action_slug": "FACEBOOK_CREATE_POST",
                                        "access_token": "raw-provider-token",
                                    },
                                },
                                "raw_prompt": "doc email moi nhat",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    )

    external_trace = trace["external_action_trace"]
    assert external_trace["integration_worker"]["result_classification"][
        "outcome"
    ] == "preview_required"
    assert external_trace["worker_outcome"] == "preview_required"
    assert external_trace["worker_failed_stage"] == "preview"
    assert external_trace["worker_reason"] == "missing_preview_evidence"
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "raw-provider-token" not in serialized
    assert "raw_prompt" not in serialized


def test_sanitize_runtime_flow_trace_strips_private_control_feedback() -> None:
    trace = sanitize_runtime_flow_trace(
        {
            "version": RUNTIME_FLOW_TRACE_VERSION,
            "_host_action_control_feedback": {
                "last_action_result": {
                    "data": {
                        "preview_token": "internal-preview-secret",
                        "approval_token": "internal-approval-secret",
                    }
                }
            },
            "turn_path_decision": {
                "path": "external_app_action",
                "reason": (
                    "facebook_post_request Bearer raw-bearer-token-123 "
                    "api_key=raw-api-key-inline"
                ),
                "approval_token": "raw-approval-token",
            },
            "external_action_trace": {
                "version": "wiii.external_action_trace.v1",
                "observed_action_result": True,
                "last_status": (
                    "action_completed Authorization: Bearer raw-status-token-123"
                ),
                "events": [
                    {
                        "type": "result",
                        "tool_name": "tool_wiii_connect_delegate_to_integration",
                        "provider_slug": "facebook",
                        "policy": {
                            "allowed": False,
                            "path": "external_app_action",
                            "reason": "denied client_secret=raw-client-secret-inline",
                        },
                        "approval_token": "raw-approval-token",
                        "data": {
                            "access_token": "raw-provider-token",
                            "provider_payload": {"id": "raw-provider"},
                            "connection_ref": "wcn_private_ref",
                            "page_id": "123456",
                        },
                    }
                ],
            },
        }
    )

    assert trace["turn_path_decision"]["path"] == "external_app_action"
    assert trace["external_action_trace"]["observed_action_result"] is True
    assert trace["external_action_trace"]["events"][0]["provider_slug"] == "facebook"
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "internal-preview-secret" not in serialized
    assert "internal-approval-secret" not in serialized
    assert "raw-approval-token" not in serialized
    assert "raw-provider-token" not in serialized
    assert "raw-bearer-token-123" not in serialized
    assert "raw-status-token-123" not in serialized
    assert "raw-api-key-inline" not in serialized
    assert "raw-client-secret-inline" not in serialized
    assert "raw-provider" not in serialized
    assert "wcn_private_ref" not in serialized
    assert "page_id" not in serialized
    assert "<redacted-secret>" in serialized
    assert "_host_action_control_feedback" not in serialized
