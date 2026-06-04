import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_runtime_evidence_artifact as artifact_validator
import validate_runtime_evidence_registry as registry_validator


AS_OF = artifact_validator._parse_timestamp("2026-06-01T12:00:00+00:00")
GENERATED_AT = "2026-06-01T10:00:00+00:00"


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_lms_payload() -> dict:
    return {
        "schema_version": "wiii.live_lms_test_course_replay.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "identity": {
            "request_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
            "course_id_hash_present": True,
            "lesson_id_hash_present": True,
        },
        "runtime": {
            "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
            "path": "lms_document_preview",
            "stream_transport": "sse_v3",
            "metadata_seen": True,
            "done_seen": True,
            "terminal_event_name": "done",
            "done_event_count": 1,
            "metadata_event_count": 1,
            "host_action_event_count": 1,
            "host_surface": "embed_lms",
            "host_capability_lms_present": True,
            "host_capability_host_action_present": True,
            "host_capability_document_preview_present": True,
            "document_context_present": True,
            "uploaded_document_count": 1,
            "source_ref_count": 2,
            "context_provenance_schema_version": "wiii.context_provenance_ledger.v1",
            "context_provenance_raw_content_included": False,
            "context_provenance_identifier_strategy": "hash_or_count_only",
            "context_provenance_document_present": True,
            "context_provenance_attachment_count": 1,
            "context_provenance_usable_attachment_count": 1,
            "context_provenance_source_ref_count": 2,
            "context_provenance_attachment_id_hash_count": 1,
            "context_provenance_media_kinds": ["document"],
            "context_provenance_source_ref_kinds": ["heading"],
            "context_provenance_host_context_present": True,
            "context_provenance_host_surface": "embed_lms",
            "context_provenance_host_capabilities": [
                "document_preview",
                "host_action",
                "lms",
            ],
            "preview_required": True,
            "preview_emitted": True,
            "apply_attempted": False,
            "approval_token_present": False,
            "host_action_result_received": False,
            "finalization_status": "saved",
            "finalization_error_absent": True,
            "post_turn_lifecycle_schema_version": "wiii.post_turn_lifecycle.v1",
            "post_turn_lifecycle_raw_content_included": False,
            "post_turn_lifecycle_identifier_strategy": "status_only",
        },
        "host_action": {
            "request_id_hash": "sha256:preview-request",
            "request_id_hash_present": True,
            "action": "authoring.preview_lesson_patch",
            "source_reference_count": 2,
            "content_present": True,
            "content_char_count": 120,
            "lesson_id_hash_present": True,
            "course_id_hash_present": True,
        },
        "source_contract": {
            "schema_version": "wiii.lms_test_course_source_contract.v1",
            "document_context_present": True,
            "provenance_schema_version": "wiii.context_provenance_ledger.v1",
            "provenance_privacy_hash_count_only": True,
            "provenance_attachment_count_matches_runtime": True,
            "provenance_usable_attachment_count_matches_runtime": True,
            "provenance_source_ref_count_matches_runtime": True,
            "provenance_attachment_id_hash_present": True,
            "provenance_media_kind_document": True,
            "provenance_source_ref_kind_heading": True,
            "host_context_matches_lms_surface": True,
            "host_capabilities_match_request": True,
            "host_action_source_ref_count_matches_runtime": True,
            "preview_audit_source_ref_count_matches_runtime": True,
            "apply_audit_source_ref_count_matches_runtime": True,
            "preview_audit_document_count_matches_runtime": True,
            "apply_audit_document_count_matches_runtime": True,
        },
        "evidence_contract": {
            "schema_version": "wiii.lms_test_course_evidence_contract.v1",
            "uses_stream_v3": True,
            "uses_host_action_audit_route": True,
            "requires_live_env_flag": "WIII_LIVE_LMS_TEST_COURSE_REPLAY",
            "requires_allow_write": True,
            "requires_allow_external_lms_write": True,
            "requires_live_channel_credentials": True,
            "requires_external_lms_apply_endpoint": "WIII_LMS_TEST_COURSE_APPLY_URL",
            "requires_external_lms_apply_token": "WIII_LMS_TEST_COURSE_APPLY_TOKEN",
            "external_lms_write_required": True,
            "external_lms_write_mode": "webhook",
            "synthetic_host_side_replay": False,
            "external_lms_write_disabled": False,
            "hash_count_only_output": True,
            "runtime_apply_forbidden_before_host": True,
            "preview_before_apply_audit_required": True,
            "source_count_parity_required": True,
        },
        "host_side_replay": {
            "preview_token_hash_present": True,
            "approval_token_present": True,
            "approval_token_in_audit_payload": False,
            "external_lms_mutated": True,
        },
        "external_lms_write": {
            "schema_version": "wiii.external_lms_test_course_write.v1",
            "mode": "webhook",
            "write_attempted": True,
            "write_acknowledged": True,
            "status_code_ok": True,
            "endpoint_hash_present": True,
            "credential_hash_present": True,
            "request_id_hash_present": True,
            "course_id_hash_present": True,
            "lesson_id_hash_present": True,
            "preview_request_id_hash_present": True,
            "preview_token_hash_present": True,
            "payload_content_hash_present": True,
            "payload_source_reference_count": 2,
            "raw_request_payload_included": False,
            "raw_response_payload_included": False,
            "raw_credential_included": False,
        },
        "audits": {
            "sequence_contract": {
                "schema_version": "wiii.lms_host_action_audit_sequence.v1",
                "event_count": 2,
                "events": [
                    {
                        "stage": "preview",
                        "event_type": "preview_created",
                        "action": "authoring.preview_lesson_patch",
                        "status": "success",
                        "status_code_ok": True,
                        "request_id_hash_present": True,
                    },
                    {
                        "stage": "apply",
                        "event_type": "apply_confirmed",
                        "action": "authoring.apply_lesson_patch",
                        "status": "success",
                        "status_code_ok": True,
                        "request_id_hash_present": True,
                    },
                ],
                "preview_before_apply": True,
                "preview_request_linked_to_apply": True,
                "shared_preview_token_hash": True,
                "response_echo_parity": True,
                "audit_surface_parity": True,
                "audit_metadata_parity": True,
                "raw_audit_payloads_included": False,
            },
            "preview_created": {
                "status_code": 200,
                "status_code_ok": True,
                "status": "success",
                "status_success": True,
                "event_type": "preview_created",
                "event_type_matches_payload": True,
                "action": "authoring.preview_lesson_patch",
                "action_matches_payload": True,
                "request_id_hash_present": True,
                "request_id_hash_matches_payload": True,
                "preview_token_hash_present": True,
                "host_type_matches_lms": True,
                "surface": "preview_panel",
                "workflow_stage_matches_authoring": True,
                "preview_kind_matches_lesson_patch": True,
                "target_type_matches_lesson": True,
                "metadata_probe_matches": True,
                "metadata_audit_stage": "preview",
                "metadata_course_id_hash_present": True,
                "metadata_lesson_id_hash_present": True,
                "metadata_preview_request_id_hash_present": False,
                "metadata_raw_content_included": False,
                "metadata_raw_lms_document_included": False,
                "metadata_raw_host_action_params_included": False,
                "metadata_source_reference_count": 2,
                "metadata_uploaded_document_count": 1,
                "raw_summary_included": False,
                "raw_preview_token_included": False,
                "raw_target_id_included": False,
            },
            "apply_confirmed": {
                "status_code": 200,
                "status_code_ok": True,
                "status": "success",
                "status_success": True,
                "event_type": "apply_confirmed",
                "event_type_matches_payload": True,
                "action": "authoring.apply_lesson_patch",
                "action_matches_payload": True,
                "request_id_hash_present": True,
                "request_id_hash_matches_payload": True,
                "preview_token_hash_present": True,
                "host_type_matches_lms": True,
                "surface": "editor_shell",
                "workflow_stage_matches_authoring": True,
                "preview_kind_matches_lesson_patch": True,
                "target_type_matches_lesson": True,
                "metadata_probe_matches": True,
                "metadata_audit_stage": "apply",
                "metadata_course_id_hash_present": True,
                "metadata_lesson_id_hash_present": True,
                "metadata_preview_request_id_hash_present": True,
                "metadata_raw_content_included": False,
                "metadata_raw_lms_document_included": False,
                "metadata_raw_host_action_params_included": False,
                "metadata_source_reference_count": 2,
                "metadata_uploaded_document_count": 1,
                "metadata_approval_token_present": True,
                "metadata_approval_credential_present": True,
                "raw_summary_included": False,
                "raw_preview_token_included": False,
                "raw_target_id_included": False,
            },
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "event_payloads_printed": False,
            "raw_sse_payload_included": False,
            "raw_approval_token_included": False,
            "raw_preview_token_included": False,
            "raw_request_identifiers_included": False,
            "raw_auth_header_included": False,
            "raw_host_action_params_included": False,
            "raw_audit_payloads_included": False,
            "raw_lms_document_included": False,
            "raw_external_lms_request_payload_included": False,
            "raw_external_lms_response_payload_included": False,
            "raw_external_lms_token_included": False,
            "raw_external_lms_endpoint_included": False,
            "raw_document_marker_hash_present": True,
        },
    }


def _valid_scheduler_payload() -> dict:
    return {
        "schema_version": "wiii.live_scheduler_replay_probe.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "scope": {
            "organization_context": "request_scoped",
            "request_org_context_set": True,
            "user_id_hash": "sha256:user",
            "user_id_hash_present": True,
            "session_id_hash": "sha256:session",
            "session_id_hash_present": True,
            "organization_id_hash": "sha256:org",
            "organization_id_hash_present": True,
            "domain_id": "maritime",
        },
        "database": {
            "url_present": True,
            "scheduled_tasks_table": "present",
            "task_id_hash": "sha256:task",
            "task_id_hash_present": True,
            "created_status": "active",
            "created_row_org_hash": "sha256:org",
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_status": "completed",
            "completed_run_count": 1,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
            "organization_id_hash": "sha256:org",
            "organization_id_hash_present": True,
        },
        "replay_contract": {
            "schema_version": "wiii.scheduler_replay_contract.v1",
            "uses_scheduler_tool": True,
            "uses_scoped_repository_poll": True,
            "executor_observability_path_used": True,
            "websocket_adapter_delivery_used": True,
            "single_created_task_executed": True,
            "cleanup_required_by_default": True,
            "hash_count_only_output": True,
            "raw_scheduler_tool_result_included": False,
        },
        "database_lifecycle_contract": {
            "schema_version": "wiii.scheduler_database_lifecycle_contract.v1",
            "created_active_before_execution": True,
            "created_row_org_hash_present": True,
            "created_row_matches_scope": True,
            "completed_row_present": True,
            "completed_status_final": True,
            "created_to_completed_transition": True,
            "completed_run_count_positive": True,
            "completed_last_run_present": True,
            "completed_next_run_is_null": True,
            "completed_org_hash_matches_created": True,
            "raw_database_row_included": False,
        },
        "clock": {
            "scheduled_for": "2026-06-01T10:00:00+00:00",
            "due_poll_seen": True,
            "due_poll_scoped": True,
            "due_poll_allow_all_orgs": False,
            "due_poll_limit": 10,
            "due_task_count": 1,
            "due_task_found_by_hash": True,
        },
        "execution": {
            "mode": "notification",
            "status": "success",
            "description_hash": "sha256:description",
            "description_hash_present": True,
            "response_hash": "sha256:response",
            "response_hash_present": True,
            "response_char_count": 80,
            "response_matches_description": True,
            "raw_description_included": False,
        },
        "delivery": {
            "delivered": True,
            "channel": "websocket",
            "socket_accepted": True,
            "socket_message_count": 1,
            "payload_type": "scheduled_task",
            "payload_mode": "notification",
            "payload_task_id_hash": "sha256:task",
            "payload_task_id_hash_present": True,
            "payload_task_id_matches_created": True,
            "payload_content_hash": "sha256:response",
            "payload_content_hash_present": True,
            "payload_content_char_count": 80,
            "payload_content_matches_response_hash": True,
            "payload_raw_content_included": False,
        },
        "delivery_contract": {
            "schema_version": "wiii.scheduler_delivery_contract.v1",
            "websocket_channel_used": True,
            "scheduled_task_payload_used": True,
            "notification_mode_used": True,
            "socket_delivery_count_positive": True,
            "payload_task_hash_matches_created": True,
            "payload_content_hash_matches_response": True,
            "raw_delivery_payload_included": False,
        },
        "metrics": {
            "counter_names_present": [
                "runtime.scheduled_tasks.delivery",
                "runtime.scheduled_tasks.due",
                "runtime.scheduled_tasks.polls",
                "runtime.scheduled_tasks.runs",
            ],
            "histogram_names_present": [
                "runtime.scheduled_tasks.duration_ms",
            ],
            "polls": {"{\"status\": \"success\"}": 1},
            "due": {"{}": 1},
            "runs": {"{\"mode\": \"notification\", \"status\": \"success\"}": 1},
            "delivery": {"{\"mode\": \"notification\", \"status\": \"delivered\"}": 1},
            "poll_success_count": 1,
            "poll_success_seen": True,
            "due_event_count": 1,
            "runs_event_count": 1,
            "run_success_count": 1,
            "run_success_seen": True,
            "delivery_event_count": 1,
            "delivery_delivered_count": 1,
            "delivery_delivered_seen": True,
            "duration_event_count": 1,
            "duration_success_count": 1,
            "duration_success_seen": True,
            "metric_label_strategy": "bounded_mode_status_only",
            "raw_metric_payload_included": False,
        },
        "cleanup": {
            "requested": True,
            "deleted": True,
            "task_id_hash_present": True,
            "raw_task_id_included": False,
            "raw_organization_identifier_included": False,
            "identifier_strategy": "hash_only",
        },
        "privacy": {
            "raw_content_included": False,
            "raw_task_id_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_description_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_row_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def _valid_heartbeat_payload() -> dict:
    return {
        "schema_version": "wiii.live_heartbeat_cycle_probe.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "scope": {
            "requested_organization_id_hash": "sha256:org",
            "requested_organization_id_hash_present": True,
            "effective_organization_id_hash": "sha256:org",
            "effective_organization_id_hash_present": True,
            "requested_matches_effective_org": True,
            "organization_context": "request_scoped",
            "warnings": [],
            "user_id_hash": "sha256:user",
            "user_id_hash_present": True,
            "session_id_hash": "sha256:session",
            "session_id_hash_present": True,
        },
        "heartbeat_cycle": {
            "cycle_id_hash": "sha256:cycle",
            "cycle_id_hash_present": True,
            "is_noop": False,
            "error_present": False,
            "duration_ms": 125,
            "planned_action_count": 2,
            "planned_action_type_names": ["reflect", "write_journal"],
            "reflect_planned": True,
            "write_journal_planned": True,
            "planned_actions": [
                {
                    "action_type": "reflect",
                    "target_present": False,
                    "target_hash": None,
                    "target_hash_present": False,
                    "priority": 0.9,
                    "metadata_keys": ["probe"],
                    "metadata_key_count": 1,
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
                {
                    "action_type": "write_journal",
                    "target_present": False,
                    "target_hash": None,
                    "target_hash_present": False,
                    "priority": 0.8,
                    "metadata_keys": ["probe"],
                    "metadata_key_count": 1,
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
            ],
            "actions_recorded_count": 2,
            "actions_recorded_type_names": ["reflect", "write_journal"],
            "reflect_recorded": True,
            "write_journal_recorded": True,
            "actions_recorded": [
                {
                    "action_type": "reflect",
                    "target_present": False,
                    "target_hash": None,
                    "target_hash_present": False,
                    "priority": 0.9,
                    "metadata_keys": ["probe"],
                    "metadata_key_count": 1,
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
                {
                    "action_type": "write_journal",
                    "target_present": False,
                    "target_hash": None,
                    "target_hash_present": False,
                    "priority": 0.8,
                    "metadata_keys": ["probe"],
                    "metadata_key_count": 1,
                    "metadata_values_included": False,
                    "raw_target_included": False,
                },
            ],
            "raw_action_payload_included": False,
        },
        "lifecycle_contract": {
            "schema_version": "wiii.heartbeat_lifecycle_contract.v1",
            "controlled_plan_used": True,
            "scheduler_execute_heartbeat_used": True,
            "prompt_patch_dependency": False,
            "required_actions_planned": True,
            "required_actions_recorded": True,
            "planned_recorded_action_count_matches": True,
            "planned_recorded_action_types_match": True,
            "briefing_audit_write_explicit": True,
            "proactive_websocket_requires_explicit_flag": True,
            "proactive_websocket_requested": False,
            "hash_count_only_output": True,
            "raw_action_metadata_values_absent": True,
            "raw_action_targets_absent": True,
        },
        "briefing": {
            "status": "pass",
            "briefing_id_hash": "sha256:briefing",
            "briefing_id_hash_present": True,
            "briefing_type": "midday",
            "content_hash": "sha256:briefing-content",
            "content_hash_present": True,
            "content_char_count": 120,
            "weather_summary_char_count": 0,
            "news_highlight_count": 0,
            "delivered_count": 0,
            "raw_content_included": False,
        },
        "proactive_websocket": {
            "status": "skipped",
            "socket_message_count": 0,
            "raw_content_included": False,
            "payload_raw_content_included": False,
        },
        "database": {
            "tables_checked": [
                "wiii_briefings",
                "wiii_emotional_snapshots",
                "wiii_heartbeat_audit",
                "wiii_journal",
                "wiii_reflections",
            ],
            "core_tables_checked": True,
            "counted_table_count": 5,
            "deltas": {
                "wiii_heartbeat_audit": {"before": 0, "after": 1, "delta": 1},
                "wiii_reflections": {"before": 0, "after": 1, "delta": 1},
                "wiii_journal": {"before": 0, "after": 1, "delta": 1},
                "wiii_briefings": {"before": 0, "after": 1, "delta": 1},
                "wiii_emotional_snapshots": {"before": 0, "after": 0, "delta": 0},
            },
        },
        "database_scope_contract": {
            "schema_version": "wiii.heartbeat_database_scope_contract.v1",
            "request_org_context_set": True,
            "required_table_count": 5,
            "counted_table_count": 5,
            "counted_table_count_matches_deltas": True,
            "core_table_set_checked": True,
            "heartbeat_audit_delta_observed": True,
            "briefing_delta_observed": True,
            "reflection_scope_observed": True,
            "journal_scope_observed": True,
            "proactive_websocket_requested": False,
            "proactive_message_delta_observed_when_requested": True,
            "raw_table_rows_included": False,
            "raw_sql_payload_included": False,
        },
        "metrics": {
            "heartbeat_cycles_event_count": 1,
            "heartbeat_cycle_success_count": 1,
            "heartbeat_cycle_success_seen": True,
            "heartbeat_cycle_duration_event_count": 1,
            "heartbeat_cycle_duration_success_count": 1,
            "heartbeat_cycle_duration_success_seen": True,
            "heartbeat_actions_event_count": 2,
            "heartbeat_action_success_count": 2,
            "heartbeat_action_duration_event_count": 2,
            "heartbeat_action_duration_success_count": 2,
            "heartbeat_action_duration_success_seen": True,
            "heartbeat_reflect_success_count": 1,
            "heartbeat_reflect_success_seen": True,
            "heartbeat_write_journal_success_count": 1,
            "heartbeat_write_journal_success_seen": True,
            "heartbeat_reflect_duration_success_count": 1,
            "heartbeat_reflect_duration_success_seen": True,
            "heartbeat_write_journal_duration_success_count": 1,
            "heartbeat_write_journal_duration_success_seen": True,
            "proactive_can_send_event_count": 0,
            "proactive_sends_event_count": 0,
            "metric_label_strategy": "bounded_status_and_action_type_only",
            "raw_metric_payload_included": False,
        },
        "privacy": {
            "raw_content_included": False,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_action_target_included": False,
            "raw_action_metadata_values_included": False,
            "raw_briefing_content_included": False,
            "raw_socket_payload_included": False,
            "raw_metric_payload_included": False,
            "raw_database_rows_included": False,
            "raw_emotional_state_included": False,
            "metric_labels_include_identifiers": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def _valid_proactive_channel_payload() -> dict:
    return {
        "schema_version": "wiii.live_proactive_channel_probe.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "channel": "telegram",
        "delivered": True,
        "recipient_id_hash": "sha256:recipient",
        "recipient_id_hash_present": True,
        "organization_id_hash": "sha256:org",
        "organization_id_hash_present": True,
        "message_hash": "sha256:message",
        "message_hash_present": True,
        "message_char_count": 80,
        "trigger": "operator_live_channel_probe",
        "database": {
            "connection_verified": True,
            "opt_out_lookup_verifiable": True,
            "send_audit_verifiable": True,
            "opt_out_scope_request_org": True,
            "send_audit_scope_request_org": True,
            "raw_connection_details_included": False,
        },
        "evidence_contract": {
            "single_outbound_send": True,
            "uses_proactive_messenger": True,
            "requires_live_channel_credentials": True,
            "requires_database_guardrail": True,
            "delivery_adapter_boundary": "configured_channel_sender",
            "identifier_strategy": "hash_or_count_only",
        },
        "org_scope": {
            "context_token_set": True,
            "organization_id_hash_present": True,
            "write_scope_expected": "request_scoped",
            "raw_organization_identifier_included": False,
        },
        "guardrail": {
            "allowed": True,
            "reason_allowed": True,
            "blocked_metric_count": 0,
            "decision_source": "ProactiveMessenger.can_send",
            "database_opt_out_check_used": True,
            "opt_out_checked_via_database": True,
        },
        "delivery": {
            "channel": "telegram",
            "delivered": True,
            "status": "delivered",
            "channel_matches_request": True,
            "duration_observed": True,
            "duration_ms_min": 12.5,
            "duration_ms_count": 1,
            "raw_delivery_payload_included": False,
        },
        "send_attempt": {
            "channel": "telegram",
            "channel_supported": True,
            "trigger": "operator_live_channel_probe",
            "priority": 0.1,
            "single_send_attempt": True,
            "recipient_id_hash_present": True,
            "organization_id_hash_present": True,
            "message_hash_present": True,
            "raw_message_included": False,
        },
        "channel_contract": {
            "requested_channel": "telegram",
            "requested_channel_supported": True,
            "requested_channel_matches_delivery": True,
            "supported_channel_count": 3,
            "credential_configured": True,
            "credential_value_included": False,
            "credential_name_value_pair_included": False,
        },
        "channel_config": {
            "supported": True,
            "enabled": True,
            "credential_present": True,
            "credential_name": "TELEGRAM_BOT_TOKEN",
            "credential_value_included": False,
        },
        "metrics": {
            "can_send_event_count": 1,
            "sends_event_count": 1,
            "can_send_allowed_count": 1,
            "send_delivered_count": 1,
            "send_duration_count": 1,
            "send_duration_observed": True,
            "send_duration_ms_min": 12.5,
            "duration_metric_label_status_delivered_seen": True,
            "metric_labels_include_identifiers": False,
            "metric_label_strategy": "bounded_status_reason_channel_only",
            "raw_metric_payload_included": False,
            "can_send_allowed_seen": True,
            "send_delivered_seen": True,
            "can_send": {
                "{\"reason\": \"allowed\", \"status\": \"allowed\"}": 1,
            },
            "sends": {
                "{\"status\": \"delivered\"}": 1,
            },
        },
        "privacy": {
            "raw_content_included": False,
            "raw_message_included": False,
            "raw_recipient_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_channel_credentials_included": False,
            "raw_delivery_payload_included": False,
            "raw_metric_payload_included": False,
            "credential_name_value_pair_included": False,
            "raw_trigger_target_included": False,
            "metric_labels_include_identifiers": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def _valid_browser_replay_summary_payload() -> dict:
    payload = {
        "schema": "wiii.runtime_flow_browser_replay_summary.v1",
        "generated_at": GENERATED_AT,
        "evidence": {
            "file_name": "runtime-flow-acceptance-evidence.json",
            "byte_count": 4096,
            "sha256_present": True,
            "schema": "wiii.runtime_flow_acceptance.v1",
            "browser_replay_schema": "wiii.runtime_flow_browser_replay.v1",
            "case_count": 6,
            "case_count_matches_browser_replay": True,
        },
        "target": {
            "target_env": "browser-replay",
            "commit_sha": "abc123",
            "backend_url_hash": "hash",
            "org_id_hash_present": True,
        },
        "doctor": {
            "status": "degraded",
            "ready_paths": 1,
            "blocked_paths": 6,
        },
        "checks": {
            "total": 4,
            "failed": 0,
            "sync_parity_passed": 3,
        },
        "browser_replay": {
            "validated_by_playwright": True,
            "exact_evidence_file_replayed": True,
            "raw_prompt_answer_or_sse_payload_absent": True,
            "raw_assistant_content_included": False,
            "all_cases_validated_by_playwright": True,
            "all_cases_finalized": True,
            "all_cases_have_post_turn_lifecycle_hash": True,
            "route_path_counts": {
                "lms_document_preview": 1,
                "external_connection_status": 1,
                "external_app_action": 2,
                "visual_generation": 2,
            },
            "route_reason_hash_present_count": 6,
            "validated_case_id_hashes": [
                "sha256:lms",
                "sha256:status",
                "sha256:action",
                "sha256:missing-provider",
                "sha256:visual",
                "sha256:code",
            ],
            "document_context_case_count": 1,
            "source_ref_case_count": 1,
            "preview_required_case_count": 1,
            "apply_attempted_count": 0,
            "visual_lifecycle_case_count": 1,
            "code_studio_lifecycle_case_count": 1,
            "finalization_status_counts": {"saved": 6},
            "finalization_saved_case_count": 6,
            "finalization_error_case_count": 0,
            "finalized_case_id_hashes": [
                "sha256:lms",
                "sha256:status",
                "sha256:action",
                "sha256:missing-provider",
                "sha256:visual",
                "sha256:code",
            ],
            "post_turn_lifecycle_status_counts": {"scheduled": 6},
            "post_turn_lifecycle_case_count": 6,
            "post_turn_lifecycle_case_id_hashes": [
                "sha256:lms",
                "sha256:status",
                "sha256:action",
                "sha256:missing-provider",
                "sha256:visual",
                "sha256:code",
            ],
            "cases": [
                {
                    "scenario_id": "uploaded_document_lms_preview_source_replay",
                    "case_id_hash_present": True,
                    "path": "lms_document_preview",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash1",
                    "route_bind_tools": True,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 2,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 1,
                    "source_ref_count": 2,
                    "preview_required": True,
                    "approval_token_present": None,
                    "apply_attempted": False,
                },
                {
                    "scenario_id": "facebook_connection_status_control_plane",
                    "case_id_hash_present": True,
                    "path": "external_connection_status",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash2",
                    "route_bind_tools": False,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 2,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 0,
                    "source_ref_count": 0,
                    "preview_required": False,
                    "approval_token_present": None,
                    "apply_attempted": False,
                },
                {
                    "scenario_id": "facebook_action_blocks_without_agent_ready_provider",
                    "case_id_hash_present": True,
                    "path": "external_app_action",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash3",
                    "route_bind_tools": False,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 2,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 0,
                    "source_ref_count": 0,
                    "preview_required": False,
                    "approval_token_present": None,
                    "apply_attempted": False,
                },
                {
                    "scenario_id": "external_action_missing_provider_blocks_before_tools",
                    "case_id_hash_present": True,
                    "path": "external_app_action",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash4",
                    "route_bind_tools": False,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 2,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 0,
                    "source_ref_count": 0,
                    "preview_required": False,
                    "approval_token_present": None,
                    "apply_attempted": False,
                },
                {
                    "scenario_id": "visual_inline_figure_stream_replay",
                    "case_id_hash_present": True,
                    "path": "visual_generation",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash5",
                    "route_bind_tools": True,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 3,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "observed_visual_runtime": True,
                    "observed_code_studio": False,
                    "visual_event_count": 2,
                    "code_studio_event_count": 0,
                    "visual_lifecycle_complete": True,
                    "code_studio_lifecycle_complete": False,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 0,
                    "source_ref_count": 0,
                    "preview_required": False,
                    "approval_token_present": None,
                    "apply_attempted": False,
                },
                {
                    "scenario_id": "code_studio_app_stream_replay",
                    "case_id_hash_present": True,
                    "path": "visual_generation",
                    "path_hash_present": True,
                    "route_reason_hash_present": True,
                    "route_reason_hash": "routehash6",
                    "route_bind_tools": True,
                    "route_force_tools": False,
                    "prompt_hash_present": True,
                    "event_name_count": 3,
                    "event_names_hash_present": True,
                    "raw_prompt_included": False,
                    "raw_answer_included": False,
                    "raw_sse_payload_included": False,
                    "assistant_content_included": False,
                    "observed_visual_runtime": False,
                    "observed_code_studio": True,
                    "visual_event_count": 0,
                    "code_studio_event_count": 2,
                    "visual_lifecycle_complete": False,
                    "code_studio_lifecycle_complete": True,
                    "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
                    "trace_version": "wiii.runtime_flow_trace.v1",
                    "uploaded_document_count": 0,
                    "source_ref_count": 0,
                    "preview_required": False,
                    "approval_token_present": None,
                    "apply_attempted": False,
                }
            ],
        },
        "wiii_connect_capability": {
            "snapshot_version": "wiii_connect_snapshot.v0",
            "surface": "desktop",
            "connection_count": 2,
            "path_capability_count": 5,
            "path_readiness_count": 5,
            "active_connection_count": 2,
            "agent_ready_connection_count": 1,
            "connected_provider_count": 1,
            "agent_ready_provider_count": 0,
            "connected_scope_count": 1,
            "suppressed_tool_group_count": 1,
            "active_connection_slug_hashes": ["sha256:server", "sha256:facebook"],
            "agent_ready_connection_slug_hashes": ["sha256:server"],
            "connected_provider_slug_hashes": ["sha256:facebook"],
            "agent_ready_provider_slug_hashes": [],
            "connected_scope_name_hashes": ["sha256:read"],
            "suppressed_tool_group_hashes": ["sha256:host_action"],
            "connection_status_counts": {"connected": 2},
            "path_status_counts": {"ready": 2, "guarded": 2, "blocked": 1},
            "path_count": 5,
            "path_count_matches_readiness_count": True,
            "path_reason_hash_present_count": 5,
            "paths": [
                {
                    "path": "casual_chat",
                    "status": "ready",
                    "reason_hash_present": True,
                },
                {
                    "path": "weather_lookup",
                    "status": "ready",
                    "reason_hash_present": True,
                },
                {
                    "path": "external_app_action",
                    "status": "guarded",
                    "reason_hash_present": True,
                },
                {
                    "path": "lms_document_preview",
                    "status": "blocked",
                    "reason_hash_present": True,
                },
                {
                    "path": "lms_document_apply",
                    "status": "guarded",
                    "reason_hash_present": True,
                },
            ],
            "raw_content_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
        "summary_archive": {
            "schema": "wiii.runtime_flow_browser_replay_summary_archive.v1",
            "enabled": True,
            "retention_limit": 25,
            "raw_prompt_answer_or_sse_payload_absent": True,
            "index_file_name": "runtime-flow-browser-replay-summary-index.json",
        },
    }
    for replay_case in payload["browser_replay"]["cases"]:
        replay_case.update(
            {
                "finalization_status": "saved",
                "finalization_saved": True,
                "finalization_error_type_present": False,
                "save_response_immediately": False,
                "post_turn_lifecycle_schema_version": "wiii.post_turn_lifecycle.v1",
                "post_turn_lifecycle_status": "scheduled",
                "post_turn_lifecycle_semantic_memory_policy": "extract_facts",
                "post_turn_lifecycle_background_tasks_scheduled_is_boolean": True,
                "post_turn_lifecycle_raw_content_included": False,
                "post_turn_lifecycle_identifier_strategy": "status_only",
                "post_turn_lifecycle_raw_scope_keys_present": False,
            }
        )
    return payload


def _valid_semantic_memory_write_payload() -> dict:
    return {
        "schema_version": "wiii.live_semantic_memory_write_doctor.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "runtime": {
            "path": "semantic_memory_write_doctor",
        },
        "semantic_memory_write": {
            "audit_schema_version": "wiii.semantic_memory_write.v1",
            "event_type": "semantic_memory_write",
        },
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
            "scheduled_task_count": 2,
            "scheduled_task_names": [
                "_store_semantic_interaction",
                "_enqueue_or_run_semantic_memory_maintenance",
            ],
            "lifecycle_owned_semantic_scheduling": True,
            "compatibility_wrapper_used": False,
            "privacy": {
                "raw_content_included": False,
                "identifier_strategy": "status_only",
            },
        },
        "session_log": {
            "backend": "in_memory",
            "append_count": 3,
            "total_event_count": 6,
            "total_semantic_write_event_count": 3,
            "org_scoped_semantic_write_event_count": 2,
            "total_runtime_flow_ledger_event_count": 2,
            "org_scoped_runtime_flow_ledger_event_count": 1,
            "cross_org_event_excluded": True,
            "cross_org_runtime_flow_ledger_excluded": True,
            "raw_non_memory_event_ignored": True,
        },
        "runtime_flow_doctor": {
            "version": "wiii.runtime_flow_doctor.v1",
            "status": "ready",
            "summary": {
                "turn_count": 1,
            },
            "finalization_statuses": {
                "saved": 1,
            },
            "post_turn_lifecycle_ledger": {
                "version": "wiii.post_turn_lifecycle_ledger.v1",
                "event_count": 1,
                "missing_count": 0,
                "background_tasks_scheduled_count": 1,
                "background_schedule": {
                    "task_count": 2,
                    "group_counts": {
                        "semantic_memory_interaction": 1,
                        "semantic_memory_maintenance": 1,
                    },
                },
                "privacy": {
                    "raw_content_included": False,
                },
            },
            "source": {
                "runtime_flow_ledger_event_count": 1,
                "org_scoped": True,
            },
            "privacy": {
                "raw_content_included": False,
            },
        },
        "runtime_flow_doctor_history": {
            "version": "wiii.runtime_flow_doctor_history.v1",
            "bucket_strategy": "event_created_at_hour",
            "post_turn_lifecycle_ledger": {
                "event_count": 1,
            },
            "source": {
                "runtime_flow_ledger_event_count": 1,
                "org_scoped": True,
                "window": "recent_runtime_flow_ledger_history",
            },
            "buckets": [
                {
                    "post_turn_lifecycle_ledger": {
                        "event_count": 1,
                    },
                },
            ],
            "privacy": {
                "raw_content_included": False,
            },
        },
        "org_scoped_doctor": {
            "version": "wiii.semantic_memory_write_doctor.v1",
            "status": "degraded",
            "summary": {
                "write_count": 2,
                "stored_fact_total": 2,
                "stored_insight_total": 1,
                "warning_count": 1,
            },
            "source": {
                "semantic_memory_write_event_count": 2,
                "org_scoped": True,
            },
            "privacy": {
                "raw_content_included": False,
            },
        },
        "org_scoped_history": {
            "version": "wiii.semantic_memory_write_doctor_history.v1",
            "bucket_strategy": "event_created_at_hour",
            "identifier_strategy": "aggregate_counts_only",
            "source": {
                "semantic_memory_write_event_count": 2,
                "org_scoped": True,
                "window": "recent_semantic_memory_write_history",
                "bucket_count": 1,
            },
            "buckets": [
                {
                    "status": "degraded",
                    "summary": {
                        "write_count": 2,
                        "stored_fact_total": 2,
                        "stored_insight_total": 1,
                    },
                    "warnings": {
                        "insight_store_degraded": 1,
                    },
                },
            ],
            "privacy": {
                "raw_content_included": False,
            },
        },
        "blocked_missing_org_context": {
            "status": "degraded",
            "summary": {
                "write_count": 1,
                "blocked_count": 1,
            },
            "organization_contexts": {
                "blocked_missing_org_context": 1,
            },
            "warnings": {
                "missing_org_context": 1,
            },
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
        },
    }


def _valid_wiii_connect_action_payload() -> dict:
    return {
        "schema_version": "wiii.live_wiii_connect_action_replay.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "runtime": {
            "path": "external_app_action",
            "request_id_hash": "sha256:request",
            "request_id_hash_present": True,
            "session_id_hash": "sha256:session",
            "session_id_hash_present": True,
            "organization_id_hash": "sha256:org",
            "organization_id_hash_present": True,
            "user_id_hash": "sha256:user",
            "user_id_hash_present": True,
            "prompt_hash": "sha256:prompt",
            "prompt_hash_present": True,
            "raw_prompt_included": False,
            "plan": {
                "version": "external_app_action_plan.v1",
                "status": "ready",
                "kind": "provider_action",
                "provider_slug": "gmail",
                "provider_ready": True,
                "action_allowlists_by_provider": {
                    "gmail": ["GMAIL_FETCH_EMAILS"],
                },
                "action_allowlist_count": 1,
            },
            "integration_lane": {
                "version": "external_app_integration_lane.v1",
                "status": "ready",
                "executor": "provider_worker",
                "provider_slug": "gmail",
                "visible_tool_names": [
                    "tool_wiii_connect_list_actions",
                    "tool_wiii_connect_delegate_to_integration",
                ],
                "visible_tool_count": 2,
                "visible_tool_count_matches": True,
            },
        },
        "integration_worker": {
            "version": "wiii_connect_integration_worker.v1",
            "delegate_version": "wiii_connect_integration_delegate_tool.v1",
            "planner_version": "wiii_connect_integration_worker.v1",
            "worker_result_version": "wiii_connect_generic_direct_tool.v1",
            "status": "ready",
            "reason": "selected_single_read_action",
            "executor": "provider_worker",
            "provider_slug": "gmail",
            "requested_provider_slug": "gmail",
            "allowed_provider_slugs": ["gmail"],
            "action_slug": "GMAIL_FETCH_EMAILS",
            "selected_mutation": "read",
            "action_allowlist": ["GMAIL_FETCH_EMAILS"],
            "prompt_present": True,
            "stage_sequence": ["provider_gate", "action_policy", "ready"],
            "stage_sequence_ready": True,
            "action_policy": {
                "reason": "selected_single_read_action",
                "selected": False,
            },
            "argument_plan": {
                "source": "caller_provided",
                "argument_keys": ["max_results", "query"],
                "argument_count": 2,
                "required_argument_keys_present": True,
            },
            "raw_prompt_included": False,
            "result_classification": {
                "version": "wiii_connect_integration_worker.v1",
                "outcome": "completed",
                "status": "action_completed",
                "failed_stage": "",
            },
        },
        "backend_gateway": {
            "version": "wiii_connect_execution_gateway.v1",
            "status": "allowed",
            "reason": "allowed",
            "connection_present": True,
            "audit_persistent": True,
            "scope_policy": {
                "version": "wiii_connect_scope_policy.v1",
                "status": "allowed",
                "reason": "allowed",
                "required_scopes": ["read"],
                "required_scope_count": 1,
                "allowed_scopes": ["read"],
                "allowed_scope_count": 1,
            },
        },
        "backend_executor": {
            "schema": {
                "status": "ready",
                "reason": "ready",
                "schema_present": True,
                "argument_keys": ["query", "max_results"],
                "required_argument_keys": ["query"],
                "hidden_argument_count": 0,
            },
            "execution": {
                "status": "succeeded",
                "reason": "ready",
                "successful": True,
                "data_keys": ["messages"],
                "data_key_count": 1,
                "log_id_present": True,
                "provider_payload_included": False,
            },
            "connected_account_seen": True,
            "observed_execute_argument_keys": ["query", "max_results"],
            "observed_execute_argument_count": 2,
            "required_arguments_present": True,
        },
        "connection_lookup": {
            "list_call_count": 1,
            "organization_id_hash_present": True,
            "user_id_hash_present": True,
            "provider_slug": "gmail",
            "provider_scope_matches": True,
            "record_count": 1,
            "raw_connection_identifier_included": False,
        },
        "audits": {
            "record_count": 2,
            "event_kinds": ["execution", "execution"],
            "statuses": ["started", "succeeded"],
            "stages": ["execute", "execute_result"],
            "execution_event_count": 2,
            "started_seen": True,
            "succeeded_seen": True,
            "execute_stage_seen": True,
            "execute_result_stage_seen": True,
            "organization_hash_count": 1,
            "user_hash_count": 1,
            "all_records_org_scoped": True,
            "all_records_user_scoped": True,
            "raw_metadata_included": False,
        },
        "final_answer": {
            "source": "external_app_action_final_answer",
            "present": True,
            "char_count": 26,
            "raw_answer_included": False,
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_prompt_included": False,
            "raw_request_identifiers_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "raw_audit_metadata_included": False,
            "opaque_connection_identifier_included": False,
            "final_answer_text_included": False,
        },
    }


def _valid_wiii_connect_facebook_post_replay_payload() -> dict:
    return {
        "schema_version": "wiii.live_wiii_connect_facebook_post_replay.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "provider": "facebook",
        "action": "FACEBOOK_CREATE_POST",
        "runtime": {
            "path": "external_app_action",
            "mutation": "apply",
            "request_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
            "user_id_hash_present": True,
            "raw_identifiers_included": False,
        },
        "preview": {
            "status": "ready",
            "reason": "preview_ready",
            "http_status": 200,
            "preview_evidence_id_present": True,
            "preview_evidence_id_hash_present": True,
            "approval_credential_present": True,
            "approval_credential_hash_present": True,
            "approval_ledger": {
                "version": "wiii_connect_operation_approval.v1",
                "status": "pending",
                "reason": "preview_recorded",
                "preview_evidence_id_present": True,
                "request_fingerprint_present": True,
                "persistent": True,
                "metadata": {
                    "selected_connection_present": True,
                    "selected_page_present": True,
                    "message_length": 39,
                    "image_present": False,
                },
            },
            "raw_response_payload_included": False,
        },
        "apply": {
            "status": "succeeded",
            "http_status": 200,
            "approval_credential_hash_present": True,
            "preview_evidence_id_hash_present": True,
            "gateway": {
                "status": "allowed",
                "scope_policy": {
                    "status": "allowed",
                    "required_scopes": ["apply"],
                },
            },
            "schema": {
                "status": "ready",
                "schema_present": True,
                "required_argument_count": 2,
            },
            "execution": {
                "status": "succeeded",
                "successful": True,
                "data_key_count": 1,
                "log_id_present": True,
            },
            "approval_ledger": {
                "version": "wiii_connect_operation_approval.v1",
                "status": "consumed",
                "preview_evidence_id_present": True,
                "request_fingerprint_present": True,
                "consumed": True,
                "persistent": True,
            },
            "raw_response_payload_included": False,
        },
        "replay": {
            "status": "blocked",
            "reason": "approval_record_already_consumed",
            "http_status": 200,
            "gateway_evaluated": False,
            "schema_evaluated": False,
            "execution_attempted": False,
            "approval_credential_hash_present": True,
            "preview_evidence_id_hash_present": True,
            "approval_ledger": {
                "version": "wiii_connect_operation_approval.v1",
                "status": "blocked",
                "reason": "approval_record_already_consumed",
                "preview_evidence_id_present": True,
                "request_fingerprint_present": True,
                "blocked": True,
                "persistent": True,
            },
            "raw_response_payload_included": False,
        },
        "operation_approval": {
            "append_count": 1,
            "consume_count": 2,
            "persistent": True,
            "preview_evidence_id_hash_present": True,
        },
        "provider_execute_call_count": 1,
        "provider_executor": {
            "call_count": 1,
            "argument_count": 3,
            "required_arguments_present": True,
            "connected_account_seen": True,
            "raw_arguments_included": False,
            "raw_response_included": False,
            "provider_account_identifier_included": False,
        },
        "storage_scope": {
            "list_call_count": 3,
            "get_call_count": 3,
            "all_calls_org_scoped": True,
            "all_calls_user_scoped": True,
            "facebook_provider_filter_seen": True,
            "connection_lookup_count": 3,
            "raw_identifiers_included": False,
        },
        "audits": {
            "record_count": 3,
            "statuses": ["allowed", "started", "succeeded"],
            "stages": ["preview", "execute", "execute_result"],
        },
        "privacy": {
            "identifier_strategy": "presence_hash_or_count_only",
            "raw_content_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "request_payload_included": False,
            "approval_credential_included": False,
            "opaque_connection_identifier_included": False,
            "selected_page_value_included": False,
            "audit_metadata_raw_content_included": False,
            "raw_request_identifiers_included": False,
        },
    }


def _valid_wiii_connect_composio_acceptance_payload() -> dict:
    return {
        "schema_version": "wiii.live_wiii_connect_composio_acceptance.v1",
        "schema": "wiii_connect_composio_acceptance_evidence.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "provider": "gmail",
        "action": "GMAIL_FETCH_EMAILS",
        "flags": {
            "expect_connected": True,
            "require_execution_ready": True,
            "execute_readonly": True,
            "explicit_connection_selected": False,
            "connection_selected_for_action": True,
        },
        "runtime": {
            "path": "external_app_action",
            "mutation": "read",
            "argument_key_count": 2,
            "arguments_present": True,
            "check_count": 13,
            "observed_section_count": 11,
        },
        "evidence_contract": {
            "backend_only_harness": True,
            "external_provider_execution": True,
            "requires_connected_account": True,
            "requires_readonly_execution": True,
        },
        "summary": {
            "passed": 13,
            "failed": 0,
            "total": 13,
            "success": True,
        },
        "check_statuses": {
            "backend_health": "passed",
            "authentication": "passed",
            "provider_registry": "passed",
            "adapter_readiness": "passed",
            "storage_readiness": "passed",
            "audit_readiness": "passed",
            "activation_readiness_connect": "passed",
            "curated_actions": "passed",
            "gateway_fail_closed_control": "passed",
            "connection_listing": "passed",
            "activation_readiness_execution": "passed",
            "execution_gateway_allowed": "passed",
            "read_only_provider_execution": "passed",
        },
        "backend": {
            "health_status": "ok",
            "origin_present": True,
        },
        "authentication": {
            "status": "authenticated",
            "mode": "bearer",
            "source": "environment",
            "bearer_value_included": False,
            "bearer_env_name_included": False,
        },
        "provider_registry": {
            "provider_slug": "gmail",
            "provider_kind": "composio",
            "provider_found": True,
        },
        "adapter": {
            "bound": True,
            "configured": True,
            "auth_ready": True,
            "can_execute_actions": True,
        },
        "storage": {
            "persistent": True,
            "connection_table_ready": True,
            "audit_ledger_ready": True,
        },
        "audit_ledger": {
            "persistent": True,
        },
        "activation": {
            "connect": {
                "status": "ready",
                "ready_to_connect": True,
                "ready_to_execute_readonly": False,
            },
            "execution": {
                "status": "ready",
                "ready_to_execute_readonly": True,
                "selected_connection_hash_present": True,
                "scope_policy": {
                    "version": "wiii_connect_scope_policy.v1",
                    "status": "allowed",
                    "reason": "allowed",
                    "read_required": True,
                    "read_allowed": True,
                    "required_scope_count": 1,
                    "allowed_scope_count": 1,
                },
            },
        },
        "curated_action": {
            "provider_slug": "gmail",
            "action_slug": "GMAIL_FETCH_EMAILS",
            "mutation": "read",
            "enabled": True,
        },
        "gateway_fail_closed": {
            "status": "blocked",
            "reason": "connection_selection_required",
            "missing_connection_selection_blocked": True,
            "provider_execution_attempted": False,
        },
        "connection_selection": {
            "list_status": "ready",
            "account_count": 1,
            "active_connection_found": True,
            "selected_connection_hash_present": True,
            "selected_connection_source": "listing",
            "opaque_connection_included": False,
        },
        "execution_gateway": {
            "status": "allowed",
            "reason": "allowed",
            "selected_connection_hash_present": True,
            "argument_key_count": 2,
            "scope_policy": {
                "version": "wiii_connect_scope_policy.v1",
                "status": "allowed",
                "reason": "allowed",
                "read_required": True,
                "read_allowed": True,
                "required_scope_count": 1,
                "allowed_scope_count": 1,
            },
            "provider_execution_attempted": False,
        },
        "readonly_execution": {
            "status": "succeeded",
            "reason": "succeeded",
            "provider_slug": "gmail",
            "action_slug": "GMAIL_FETCH_EMAILS",
            "selected_connection_hash_present": True,
            "schema": {
                "status": "ready",
                "schema_present": True,
                "provider_slug": "gmail",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "argument_key_count": 2,
                "required_argument_key_count": 1,
                "required_argument_keys_present": True,
                "raw_schema_included": False,
            },
            "execution": {
                "status": "succeeded",
                "successful": True,
                "provider_slug": "gmail",
                "action_slug": "GMAIL_FETCH_EMAILS",
                "status_code": 200,
                "data_key_count": 1,
                "error_present": False,
                "session_info_present": False,
                "log_id_present": True,
                "provider_response_included": False,
            },
            "provider_payload_included": False,
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "opaque_connection_included": False,
            "provider_payload_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "raw_schema_included": False,
            "connect_link_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
        },
    }


def _valid_provider_runtime_payload() -> dict:
    return {
        "schema_version": "wiii.live_provider_runtime_probe.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "evidence_contract": {
            "schema_version": "wiii.provider_runtime_evidence_contract.v1",
            "credentialed_provider_call_required": True,
            "tool_roundtrip_required": True,
            "single_tool_call_required": True,
            "tool_result_linkage_required": True,
            "followup_without_extra_tool_calls_required": True,
            "trace_span_pair_required": True,
            "stream_ledger_optional": True,
            "stream_ledger_requested": False,
            "stream_ledger_requires_allow_stream_write": True,
            "hash_count_only_output": True,
        },
        "direct_provider_tool_roundtrip": {
            "status": "pass",
            "duration_ms": 10,
            "provider": "google",
            "provider_present": True,
            "model": "gemini-live-test",
            "model_present": True,
            "selectable_provider_count": 1,
            "route": {
                "provider": "google",
                "provider_matches_resolved": True,
                "fallback_provider_present": False,
                "fallback_llm_present": False,
            },
            "runtime_boundary": {
                "schema_version": "wiii.provider_runtime_boundary.v1",
                "llm_pool_route_used": True,
                "wiii_chat_model_interface_used": True,
                "native_message_contract_used": True,
                "raw_provider_http_used": False,
                "raw_provider_payload_included": False,
                "raw_provider_response_included": False,
            },
            "tool_contract": {
                "schema_version": "wiii.provider_tool_contract.v1",
                "tool_name": "record_probe_fact",
                "tool_name_matches_probe": True,
                "forced_tool_choice_used": True,
                "required_argument_keys": ["label", "value"],
                "required_argument_key_count": 2,
                "additional_properties_allowed": False,
                "no_side_effect_tool": True,
                "raw_schema_values_included": False,
            },
            "scope": {
                "session_id_hash_present": True,
                "organization_id_hash_present": True,
                "raw_request_identifiers_included": False,
            },
            "tool_call_count": 1,
            "tool_call_count_exactly_one": True,
            "tool_result_count": 1,
            "tool_call": {
                "name": "record_probe_fact",
                "id_hash_present": True,
                "argument_keys": ["value", "label"],
                "argument_count": 2,
                "argument_values_included": False,
                "raw_id_included": False,
            },
            "tool_result": {
                "role": "tool",
                "tool_call_id_hash_present": True,
                "content_json_keys": ["ok", "label", "observed_at"],
                "content_json_key_count": 3,
                "content_json_values_included": False,
                "raw_content_included": False,
                "raw_tool_call_id_included": False,
            },
            "tool_result_linked_to_tool_call": True,
            "tool_result_followup": {
                "final_response_received": True,
                "raw_content_included": False,
                "returned_tool_call_count": 0,
            },
            "trace": {
                "span_count": 2,
                "tool_call_span_seen": True,
                "tool_result_span_seen": True,
                "duration_observed": True,
                "raw_attribute_values_included": False,
            },
        },
        "stream_runtime_ledger": {"status": "skipped"},
        "privacy": {
            "raw_content_included": False,
            "tool_argument_values_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
            "stream_payload_included": False,
            "raw_request_identifiers_included": False,
            "identifier_strategy": "hashes_and_counts",
        },
    }


def _valid_provider_stream_runtime_ledger_payload(**overrides: object) -> dict:
    payload = {
        "status": "pass",
        "status_code": 200,
        "ledger_schema_version": "wiii.runtime_flow_ledger.v1",
        "provider_present": True,
        "model_present": True,
        "runtime_authoritative": True,
        "metadata_seen": True,
        "done_seen": True,
        "terminal_event_name": "done",
        "done_count_matches_ledger": True,
        "metadata_count_matches_ledger": True,
        "event_count": 3,
        "event_counts": {"metadata": 1, "done": 1},
        "ledger_event_counts": {"metadata": 1, "done": 1},
        "request_id_hash_present": True,
        "session_id_hash_present": True,
        "organization_id_hash_present": True,
        "finalization_status": "saved",
        "post_turn_lifecycle_schema_version": "wiii.post_turn_lifecycle.v1",
        "post_turn_lifecycle_raw_content_included": False,
        "post_turn_lifecycle_raw_scope_keys_present": False,
        "privacy": {
            "raw_sse_data_included": False,
            "request_payload_included": False,
            "stream_prompt_included": False,
            "auth_secret_included": False,
        },
    }
    payload.update(overrides)
    return payload


def _valid_subagent_boundary_payload() -> dict:
    return {
        "schema": "wiii.live_subagent_boundary_replay.v1",
        "generated_at": GENERATED_AT,
        "status": "pass",
        "request": {
            "request_id_hash_present": True,
            "session_id_hash_present": True,
            "organization_id_hash_present": True,
        },
        "execution": {
            "parallel_task_count": 2,
            "max_concurrent": 2,
            "result_statuses": ["success", "partial"],
            "result_count_matches_task_count": True,
            "parallel_execution_configured": True,
            "duration_ms": 10,
        },
        "runtime_ledger": {
            "schema_version": "wiii.runtime_flow_ledger.v1",
            "done_seen": True,
            "subagent_schema_version": "wiii.subagent_boundary_trace.v1",
            "subagent_report_count": 2,
            "subagent_report_count_matches_execution": True,
            "raw_request_identifiers_included": False,
        },
        "subagents": {
            "schema_version": "wiii.subagent_boundary_trace.v1",
            "raw_content_included": False,
            "report_count": 2,
            "warning_codes": [
                "kwargs_top_level_keys_dropped",
                "state_top_level_keys_dropped",
                "subagent_output_sanitized_or_truncated",
                "subagent_thinking_dropped",
            ],
            "warning_counts": {
                "kwargs_top_level_keys_dropped": 1,
                "state_top_level_keys_dropped": 1,
                "subagent_output_sanitized_or_truncated": 1,
                "subagent_thinking_dropped": 1,
            },
            "counts": {
                "report_count": 2,
                "source_count": 3,
                "tool_count": 2,
                "state_projected_key_count": 12,
                "state_dropped_key_count": 12,
                "output_char_count": 159,
                "thinking_dropped_count": 2,
            },
        },
        "handoff_boundary": {
            "schema_versions": ["wiii.subagent_handoff_boundary.v1"],
            "boundary_count": 2,
            "state_projected_key_count": 12,
            "state_dropped_key_count": 12,
            "kwargs_projected_key_count": 4,
            "kwargs_dropped_key_count": 2,
            "warning_counts": {
                "kwargs_top_level_keys_dropped": 2,
                "state_top_level_keys_dropped": 2,
            },
            "raw_content_included": False,
        },
        "result_boundary": {
            "schema_versions": ["wiii.subagent_result_boundary.v1"],
            "boundary_count": 2,
            "status_counts": {"partial": 1, "success": 1},
            "raw_output_char_count": 181,
            "output_char_count": 159,
            "output_sanitized_or_truncated": True,
            "data_key_count": 7,
            "source_count": 3,
            "tool_count": 2,
            "evidence_image_count": 1,
            "thinking_dropped_count": 2,
            "warning_counts": {
                "subagent_output_sanitized_or_truncated": 2,
                "subagent_thinking_dropped": 2,
            },
            "raw_content_included": False,
        },
        "doctor": {
            "status": "degraded",
            "subagents": {
                "identifier_strategy": "aggregate_counts_only",
                "raw_content_flag_count": 0,
                "report_count": 2,
                "source_count": 3,
                "tool_count": 2,
                "state_projected_key_count": 12,
                "state_dropped_key_count": 12,
                "thinking_dropped_count": 2,
                "warning_count": 4,
                "warnings": {
                    "state_top_level_keys_dropped": 1,
                    "kwargs_top_level_keys_dropped": 1,
                    "subagent_thinking_dropped": 1,
                },
            },
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_request_identifiers_included": False,
            "raw_secret_included": False,
        },
    }


class RuntimeEvidenceArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = registry_validator.load_registry(registry_validator.DEFAULT_REGISTRY)

    def test_provider_artifact_validates_with_tool_call_contract(self) -> None:
        payload = _valid_provider_runtime_payload()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_artifact_validation_result_exposes_validation_schema_version(self) -> None:
        payload = _valid_provider_runtime_payload()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertEqual(
            artifact_validator.ARTIFACT_VALIDATION_SCHEMA_VERSION,
            result.validation_schema_version,
        )
        self.assertEqual(
            artifact_validator.ARTIFACT_VALIDATION_SCHEMA_VERSION,
            result.to_dict()["validation_schema_version"],
        )
        self.assertEqual([], result.to_dict()["error_codes"])
        self.assertEqual({}, result.to_dict()["error_code_counts"])
        self.assertIn(
            "validation_schema: wiii.runtime_evidence_artifact_validation.v1",
            artifact_validator.format_summary(result),
        )

    def test_artifact_validation_json_error_exposes_validation_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            missing_artifact = Path(temp_dir) / "provider-runtime-evidence.json"
            with contextlib.redirect_stdout(stdout):
                exit_code = artifact_validator.main(
                    [
                        str(missing_artifact),
                        "--registry",
                        str(registry_validator.DEFAULT_REGISTRY),
                        "--json",
                    ]
                )

        data = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(data["ok"])
        self.assertEqual(
            artifact_validator.ARTIFACT_VALIDATION_SCHEMA_VERSION,
            data["validation_schema_version"],
        )
        self.assertIn("artifact_json_read_failed", data["error_codes"])
        self.assertGreaterEqual(
            data["error_code_counts"].get("artifact_json_read_failed", 0),
            1,
        )

    def test_artifact_cli_validates_registry_contract_before_payload(self) -> None:
        broken_registry = copy.deepcopy(self.registry)
        broken_registry["decorative_config"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            registry_path = _write_json(temp_root / "registry.json", broken_registry)
            artifact_path = _write_json(
                temp_root / "provider-runtime-evidence.json",
                _valid_provider_runtime_payload(),
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = artifact_validator.main(
                    [
                        str(artifact_path),
                        "--registry",
                        str(registry_path),
                        "--json",
                    ]
                )

        data = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(data["ok"])
        self.assertEqual(
            artifact_validator.ARTIFACT_VALIDATION_SCHEMA_VERSION,
            data["validation_schema_version"],
        )
        self.assertIn("registry_contract_invalid", data["error_codes"])
        self.assertEqual(
            1,
            data["error_code_counts"].get("registry_contract_invalid"),
        )
        self.assertTrue(
            any("registry validation failed" in error for error in data["errors"]),
            data["errors"],
        )

    def test_provider_artifact_enforces_conditional_stream_done(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["stream_runtime_ledger"] = _valid_provider_stream_runtime_ledger_payload(done_seen=False)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("stream_runtime_ledger.done_seen" in error for error in result.errors), result.errors)

    def test_provider_artifact_requires_direct_provider_authority(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["provider_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("direct_provider_tool_roundtrip.provider_present" in error for error in result.errors),
            result.errors,
        )

    def test_provider_artifact_rejects_non_finite_json_numbers(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["duration_ms"] = float("nan")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("non-finite JSON number" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("artifact_json_read_failed", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_path = Path(temp_dir) / "provider-runtime-evidence.json"
            artifact_path.write_text(
                '{"schema_version": "wiii.live_provider_runtime_probe.v1", '
                '"schema_version": "wiii.live_provider_runtime_probe.v1"}',
                encoding="utf-8",
            )

            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=artifact_path,
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("duplicate JSON object key" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("artifact_json_read_failed", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_symlink_artifact_path(self) -> None:
        payload = _valid_provider_runtime_payload()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = _write_json(root / "target.json", payload)
            artifact_path = root / "provider-runtime-evidence.json"
            try:
                artifact_path.symlink_to(target_path)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink not available: {exc}")

            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=artifact_path,
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("path must not be a symlink" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("artifact_path_symlink", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_boolean_min_values(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["duration_ms"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "direct_provider_tool_roundtrip.duration_ms" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("payload_check_min_mismatch", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_numeric_string_min_values(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["duration_ms"] = "10"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "direct_provider_tool_roundtrip.duration_ms" in error
                for error in result.errors
            ),
            result.errors,
        )
        self.assertIn("payload_check_min_mismatch", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_mixed_type_sorted_equals_without_crashing(
        self,
    ) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["tool_contract"][
            "required_argument_keys"
        ] = ["label", 7]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("sorted value mismatch" in error for error in result.errors),
            result.errors,
        )
        self.assertIn("payload_check_sorted_equals_mismatch", result.to_dict()["error_codes"])

    def test_provider_artifact_rejects_boolean_freshness_max_age(self) -> None:
        payload = _valid_provider_runtime_payload()
        registry = copy.deepcopy(self.registry)
        requirement = next(
            item
            for item in registry["requirements"]
            if item["artifact"] == "provider-runtime-evidence.json"
        )
        requirement["freshness"]["max_age_hours"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertIn(
            "artifact_freshness_max_age_hours_missing",
            result.to_dict()["error_codes"],
        )

    def test_provider_artifact_requires_tool_result_linkage(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["tool_result_linked_to_tool_call"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("direct_provider_tool_roundtrip.tool_result_linked_to_tool_call" in error for error in result.errors),
            result.errors,
        )

    def test_provider_artifact_requires_evidence_contract(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["evidence_contract"]["tool_result_linkage_required"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("evidence_contract.tool_result_linkage_required" in error for error in result.errors),
            result.errors,
        )

    def test_provider_artifact_rejects_raw_provider_http_boundary(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["runtime_boundary"][
            "raw_provider_http_used"
        ] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "direct_provider_tool_roundtrip.runtime_boundary.raw_provider_http_used"
                in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_provider_artifact_rejects_tool_argument_value_leak_flag(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["direct_provider_tool_roundtrip"]["tool_call"]["argument_values_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "direct_provider_tool_roundtrip.tool_call.argument_values_included" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_provider_artifact_requires_stream_finalization_when_stream_passes(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["stream_runtime_ledger"] = _valid_provider_stream_runtime_ledger_payload(
            finalization_status="pending",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("stream_runtime_ledger.finalization_status" in error for error in result.errors),
            result.errors,
        )

    def test_provider_artifact_rejects_stream_prompt_leak_when_stream_passes(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["stream_runtime_ledger"] = _valid_provider_stream_runtime_ledger_payload(
            privacy={
                "raw_sse_data_included": False,
                "request_payload_included": False,
                "stream_prompt_included": True,
                "auth_secret_included": False,
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("stream_runtime_ledger.privacy.stream_prompt_included" in error for error in result.errors),
            result.errors,
        )

    def test_provider_artifact_rejects_stream_auth_secret_flag_when_stream_passes(self) -> None:
        payload = _valid_provider_runtime_payload()
        payload["stream_runtime_ledger"] = _valid_provider_stream_runtime_ledger_payload(
            privacy={
                "raw_sse_data_included": False,
                "request_payload_included": False,
                "stream_prompt_included": False,
                "auth_secret_included": True,
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "provider-runtime-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("stream_runtime_ledger.privacy.auth_secret_included" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_validates_delivery_and_cleanup_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    _valid_scheduler_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_scheduler_artifact_fails_without_cleanup_delete(self) -> None:
        payload = _valid_scheduler_payload()
        payload["cleanup"]["deleted"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("cleanup.deleted" in error for error in result.errors), result.errors)

    def test_scheduler_artifact_fails_without_socket_delivery(self) -> None:
        payload = _valid_scheduler_payload()
        payload["delivery"]["socket_message_count"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("delivery.socket_message_count" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_fails_without_scoped_due_poll(self) -> None:
        payload = _valid_scheduler_payload()
        payload["clock"]["due_poll_allow_all_orgs"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("clock.due_poll_allow_all_orgs" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_fails_without_worker_run_metric(self) -> None:
        payload = _valid_scheduler_payload()
        payload["metrics"]["run_success_seen"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.run_success_seen" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_fails_with_raw_delivery_payload(self) -> None:
        payload = _valid_scheduler_payload()
        payload["privacy"]["raw_delivery_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("privacy.raw_delivery_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_fails_without_replay_contract(self) -> None:
        payload = _valid_scheduler_payload()
        payload["replay_contract"]["uses_scoped_repository_poll"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("replay_contract.uses_scoped_repository_poll" in error for error in result.errors),
            result.errors,
        )

    def test_scheduler_artifact_fails_without_database_lifecycle_transition(self) -> None:
        payload = _valid_scheduler_payload()
        payload["database_lifecycle_contract"]["created_to_completed_transition"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "database_lifecycle_contract.created_to_completed_transition" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_scheduler_artifact_fails_with_raw_metric_payload_flag(self) -> None:
        payload = _valid_scheduler_payload()
        payload["metrics"]["raw_metric_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-scheduler-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.raw_metric_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_validates_living_action_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    _valid_heartbeat_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_heartbeat_artifact_fails_without_reflection_evidence(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["heartbeat_cycle"]["reflect_recorded"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("heartbeat_cycle.reflect_recorded" in error for error in result.errors), result.errors)

    def test_heartbeat_artifact_fails_without_briefing_write(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["database"]["deltas"]["wiii_briefings"]["delta"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("database.deltas.wiii_briefings.delta" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_fails_without_action_metrics(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["metrics"]["heartbeat_actions_event_count"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.heartbeat_actions_event_count" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_fails_without_scope_hashes(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["scope"]["user_id_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("scope.user_id_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_fails_with_raw_action_metadata(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["heartbeat_cycle"]["planned_actions"][0]["metadata_values_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "heartbeat_cycle.planned_actions.*.metadata_values_included" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_heartbeat_artifact_fails_without_reflect_success_metric(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["metrics"]["heartbeat_reflect_success_seen"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.heartbeat_reflect_success_seen" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_fails_with_raw_socket_payload_flag(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["privacy"]["raw_socket_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("privacy.raw_socket_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_heartbeat_artifact_fails_without_lifecycle_action_parity(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["lifecycle_contract"]["planned_recorded_action_types_match"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "lifecycle_contract.planned_recorded_action_types_match" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_heartbeat_artifact_fails_without_database_scope_contract(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["database_scope_contract"]["request_org_context_set"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "database_scope_contract.request_org_context_set" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_heartbeat_artifact_fails_with_raw_metric_payload_flag(self) -> None:
        payload = _valid_heartbeat_payload()
        payload["metrics"]["raw_metric_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-heartbeat-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.raw_metric_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_validates_guardrail_metrics_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    _valid_proactive_channel_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_proactive_channel_artifact_fails_without_allowed_guardrail_metric(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["metrics"]["can_send_allowed_seen"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.can_send_allowed_seen" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_credential_ready(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["channel_config"]["credential_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("channel_config.credential_present" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_hash_identifiers(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["recipient_id_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("recipient_id_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_message_hash(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["send_attempt"]["message_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("send_attempt.message_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_on_raw_credential_flag(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["privacy"]["raw_channel_credentials_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("privacy.raw_channel_credentials_included" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_duration_metric(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["metrics"]["send_duration_observed"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.send_duration_observed" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_database_scope_proof(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["database"]["opt_out_lookup_verifiable"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("database.opt_out_lookup_verifiable" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_when_metric_labels_include_identifiers(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["privacy"]["metric_labels_include_identifiers"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "privacy.metric_labels_include_identifiers" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_single_send_contract(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["evidence_contract"]["single_outbound_send"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("evidence_contract.single_outbound_send" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_on_blocked_guardrail_metric(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["guardrail"]["blocked_metric_count"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("guardrail.blocked_metric_count" in error for error in result.errors),
            result.errors,
        )

    def test_proactive_channel_artifact_fails_without_bounded_metric_label_strategy(self) -> None:
        payload = _valid_proactive_channel_payload()
        payload["metrics"]["metric_label_strategy"] = "raw_identifiers"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "autonomy-proactive-channel-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("metrics.metric_label_strategy" in error for error in result.errors),
            result.errors,
        )

    def test_schema_mismatch_fails(self) -> None:
        payload = {
            "schema_version": "wiii.other.v1",
            "generated_at": GENERATED_AT,
            "status": "pass",
            "delivered": True,
            "privacy": {"raw_content_included": False},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "autonomy-proactive-channel-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("schema_version" in error for error in result.errors), result.errors)
        self.assertIn("artifact_schema_mismatch", result.to_dict()["error_codes"])
        self.assertEqual(
            1,
            result.to_dict()["error_code_counts"]["artifact_schema_mismatch"],
        )
        self.assertEqual(
            "artifact_schema_mismatch",
            artifact_validator.normalize_artifact_error_code(result.errors[0]),
        )
        self.assertIn("Error codes:", artifact_validator.format_summary(result))
        self.assertIn("Error code counts:", artifact_validator.format_summary(result))
        self.assertIn("artifact_schema_mismatch", artifact_validator.format_summary(result))

    def test_forbidden_token_fails(self) -> None:
        payload = {
            "schema_version": "wiii.live_proactive_channel_probe.v1",
            "generated_at": GENERATED_AT,
            "status": "pass",
            "delivered": True,
            "leak": "authorization",
            "privacy": {"raw_content_included": False},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "autonomy-proactive-channel-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_forbidden_token_match_is_case_insensitive(self) -> None:
        payload = {
            "schema_version": "wiii.live_proactive_channel_probe.v1",
            "generated_at": GENERATED_AT,
            "status": "pass",
            "delivered": True,
            "leak": "Authorization",
            "privacy": {"raw_content_included": False},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "autonomy-proactive-channel-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_subagent_artifact_validates_hash_count_doctor_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "subagent-boundary-evidence.json",
                    _valid_subagent_boundary_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_subagent_report_minimum_fails(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["subagents"]["report_count"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("subagents.report_count" in error for error in result.errors), result.errors)

    def test_subagent_artifact_fails_without_hash_presence(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["request"]["organization_id_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("request.organization_id_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_subagent_artifact_fails_on_raw_content_flag(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["doctor"]["subagents"]["raw_content_flag_count"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("doctor.subagents.raw_content_flag_count" in error for error in result.errors),
            result.errors,
        )

    def test_subagent_artifact_fails_without_runtime_ledger_done(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["runtime_ledger"]["done_seen"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("runtime_ledger.done_seen" in error for error in result.errors), result.errors)

    def test_subagent_artifact_fails_without_handoff_kwargs_drop(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["handoff_boundary"]["kwargs_dropped_key_count"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("handoff_boundary.kwargs_dropped_key_count" in error for error in result.errors),
            result.errors,
        )

    def test_subagent_artifact_fails_without_result_boundary_sanitization(self) -> None:
        payload = _valid_subagent_boundary_payload()
        payload["result_boundary"]["output_sanitized_or_truncated"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(Path(temp_dir) / "subagent-boundary-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("result_boundary.output_sanitized_or_truncated" in error for error in result.errors),
            result.errors,
        )

    def test_lms_artifact_validates_host_preview_replay_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    _valid_lms_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_lms_artifact_rejects_events_object_for_length_check(self) -> None:
        payload = _valid_lms_payload()
        events = payload["audits"]["sequence_contract"]["events"]
        payload["audits"]["sequence_contract"]["events"] = {
            str(index): event for index, event in enumerate(events)
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("audits.sequence_contract.events" in error for error in result.errors),
            result.errors,
        )

    def test_lms_artifact_fails_without_external_lms_write_ack(self) -> None:
        payload = _valid_lms_payload()
        payload["host_side_replay"]["external_lms_mutated"] = False
        payload["external_lms_write"]["write_acknowledged"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("external_lms_write.write_acknowledged" in error for error in result.errors),
            result.errors,
        )

    def test_lms_artifact_fails_without_identity_hashes(self) -> None:
        payload = _valid_lms_payload()
        payload["identity"]["organization_id_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("identity.organization_id_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_lms_artifact_fails_if_audit_metadata_contains_raw_content(self) -> None:
        payload = _valid_lms_payload()
        payload["audits"]["apply_confirmed"]["metadata_raw_content_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("audits.apply_confirmed.metadata_raw_content_included" in error for error in result.errors),
            result.errors,
        )

    def test_lms_artifact_fails_if_approval_token_marker_leaks(self) -> None:
        payload = _valid_lms_payload()
        payload["leak"] = "probe-approval-token"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_lms_artifact_fails_without_preview_apply_sequence_link(self) -> None:
        payload = _valid_lms_payload()
        payload["audits"]["sequence_contract"]["preview_request_linked_to_apply"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "audits.sequence_contract.preview_request_linked_to_apply" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_lms_artifact_fails_without_source_count_parity(self) -> None:
        payload = _valid_lms_payload()
        payload["source_contract"]["preview_audit_source_ref_count_matches_runtime"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "source_contract.preview_audit_source_ref_count_matches_runtime" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_lms_artifact_fails_without_context_provenance_privacy(self) -> None:
        payload = _valid_lms_payload()
        payload["runtime"]["context_provenance_raw_content_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "runtime.context_provenance_raw_content_included" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_semantic_memory_write_artifact_validates_doctor_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    _valid_semantic_memory_write_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_semantic_memory_write_artifact_fails_without_org_filtering(self) -> None:
        payload = _valid_semantic_memory_write_payload()
        payload["session_log"]["cross_org_event_excluded"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("session_log.cross_org_event_excluded" in error for error in result.errors),
            result.errors,
        )

    def test_semantic_memory_write_artifact_fails_without_history_bucket(self) -> None:
        payload = _valid_semantic_memory_write_payload()
        payload["org_scoped_history"]["source"]["bucket_count"] = 0
        payload["org_scoped_history"]["buckets"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("org_scoped_history.source.bucket_count" in error for error in result.errors),
            result.errors,
        )

    def test_semantic_memory_write_artifact_fails_without_lifecycle_proof(self) -> None:
        payload = _valid_semantic_memory_write_payload()
        payload["post_turn_lifecycle"]["lifecycle_owned_semantic_scheduling"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "post_turn_lifecycle.lifecycle_owned_semantic_scheduling" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_semantic_memory_write_artifact_fails_without_durable_lifecycle_ledger(
        self,
    ) -> None:
        payload = _valid_semantic_memory_write_payload()
        payload["runtime_flow_doctor"]["post_turn_lifecycle_ledger"][
            "event_count"
        ] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "runtime_flow_doctor.post_turn_lifecycle_ledger.event_count" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_semantic_memory_write_artifact_fails_on_raw_memory_leak(self) -> None:
        payload = _valid_semantic_memory_write_payload()
        payload["leak"] = "PRIVATE SEMANTIC MEMORY MESSAGE"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "semantic-memory-write-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_wiii_connect_action_artifact_validates_gateway_worker_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    _valid_wiii_connect_action_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_wiii_connect_action_artifact_fails_on_raw_connection_ref(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["leak"] = "connection_ref=wcn_private"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_wiii_connect_action_artifact_fails_without_completed_worker(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["integration_worker"]["result_classification"]["outcome"] = "failed"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("integration_worker.result_classification.outcome" in error for error in result.errors),
            result.errors,
        )

    def test_wiii_connect_action_artifact_fails_without_request_hash(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["runtime"]["request_id_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("runtime.request_id_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_wiii_connect_action_artifact_fails_without_ready_stage_sequence(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["integration_worker"]["stage_sequence_ready"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("integration_worker.stage_sequence_ready" in error for error in result.errors),
            result.errors,
        )

    def test_wiii_connect_action_artifact_fails_without_audit_scope(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["audits"]["all_records_org_scoped"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("audits.all_records_org_scoped" in error for error in result.errors),
            result.errors,
        )

    def test_wiii_connect_action_artifact_fails_with_provider_payload_flag(self) -> None:
        payload = _valid_wiii_connect_action_payload()
        payload["privacy"]["provider_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-action-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("privacy.provider_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_facebook_post_replay_artifact_validates_approval_ledger_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    _valid_wiii_connect_facebook_post_replay_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_facebook_post_replay_artifact_fails_without_replay_block(self) -> None:
        payload = _valid_wiii_connect_facebook_post_replay_payload()
        payload["replay"]["status"] = "succeeded"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("replay.status" in error for error in result.errors), result.errors)

    def test_facebook_post_replay_artifact_fails_on_approval_token_leak(self) -> None:
        payload = _valid_wiii_connect_facebook_post_replay_payload()
        payload["leak"] = "approval_token"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_facebook_post_replay_artifact_fails_without_approval_hash(self) -> None:
        payload = _valid_wiii_connect_facebook_post_replay_payload()
        payload["preview"]["approval_credential_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("preview.approval_credential_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_facebook_post_replay_artifact_fails_without_storage_scope(self) -> None:
        payload = _valid_wiii_connect_facebook_post_replay_payload()
        payload["storage_scope"]["all_calls_org_scoped"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("storage_scope.all_calls_org_scoped" in error for error in result.errors),
            result.errors,
        )

    def test_facebook_post_replay_artifact_fails_with_provider_argument_leak_flag(self) -> None:
        payload = _valid_wiii_connect_facebook_post_replay_payload()
        payload["provider_executor"]["raw_arguments_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-facebook-post-replay-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("provider_executor.raw_arguments_included" in error for error in result.errors),
            result.errors,
        )

    def test_composio_acceptance_artifact_validates_credentialed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    _valid_wiii_connect_composio_acceptance_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_composio_acceptance_artifact_fails_without_readonly_execution(self) -> None:
        payload = _valid_wiii_connect_composio_acceptance_payload()
        payload["flags"]["execute_readonly"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("flags.execute_readonly" in error for error in result.errors),
            result.errors,
        )

    def test_composio_acceptance_artifact_fails_on_connection_ref_leak(self) -> None:
        payload = _valid_wiii_connect_composio_acceptance_payload()
        payload["leak"] = "connection_ref=wcn_live_secret"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("forbidden token" in error for error in result.errors), result.errors)

    def test_composio_acceptance_artifact_fails_without_schema_proof(self) -> None:
        payload = _valid_wiii_connect_composio_acceptance_payload()
        payload["readonly_execution"]["schema"]["schema_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("readonly_execution.schema.schema_present" in error for error in result.errors),
            result.errors,
        )

    def test_composio_acceptance_artifact_fails_without_fail_closed_gateway(self) -> None:
        payload = _valid_wiii_connect_composio_acceptance_payload()
        payload["gateway_fail_closed"]["provider_execution_attempted"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "gateway_fail_closed.provider_execution_attempted" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_composio_acceptance_artifact_fails_with_bearer_env_name_flag(self) -> None:
        payload = _valid_wiii_connect_composio_acceptance_payload()
        payload["authentication"]["bearer_env_name_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "wiii-connect-composio-acceptance-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("authentication.bearer_env_name_included" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_validates_exact_file_runtime_tab_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    _valid_browser_replay_summary_payload(),
                ),
                as_of=AS_OF,
            )

        self.assertTrue(result.ok, result.errors)

    def test_browser_replay_summary_fails_without_playwright_validation(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["validated_by_playwright"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.validated_by_playwright" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_without_exact_evidence_replay(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["exact_evidence_file_replayed"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.exact_evidence_file_replayed" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_without_ready_doctor_path(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["doctor"]["ready_paths"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("doctor.ready_paths" in error for error in result.errors), result.errors)

    def test_browser_replay_summary_fails_when_apply_was_attempted(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][0]["apply_attempted"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*.apply_attempted" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_backend_route_counts(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["route_path_counts"]["external_app_action"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.route_path_counts.external_app_action" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_route_reason_hashes(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["route_reason_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*.route_reason_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_rejects_case_raw_sse_payload_flag(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["raw_sse_payload_included"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*.raw_sse_payload_included" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_all_cases_validated_by_browser(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["validated_case_id_hashes"] = payload["browser_replay"][
            "validated_case_id_hashes"
        ][:-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("len(browser_replay.validated_case_id_hashes)" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_all_cases_finalized_by_backend(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["finalized_case_id_hashes"] = payload["browser_replay"][
            "finalized_case_id_hashes"
        ][:-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("len(browser_replay.finalized_case_id_hashes)" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_when_case_finalization_not_saved(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["finalization_saved"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*.finalization_saved" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_on_finalization_error_count(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["finalization_error_case_count"] = 1

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.finalization_error_case_count" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_all_cases_have_lifecycle_hashes(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["post_turn_lifecycle_case_id_hashes"] = payload["browser_replay"][
            "post_turn_lifecycle_case_id_hashes"
        ][:-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("len(browser_replay.post_turn_lifecycle_case_id_hashes)" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_without_case_lifecycle_schema(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["post_turn_lifecycle_schema_version"] = ""

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "browser_replay.cases.*.post_turn_lifecycle_schema_version" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_browser_replay_summary_fails_on_case_lifecycle_raw_scope(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["post_turn_lifecycle_raw_scope_keys_present"] = True

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "browser_replay.cases.*.post_turn_lifecycle_raw_scope_keys_present" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_browser_replay_summary_requires_safe_sync_parity_passes(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["checks"]["sync_parity_passed"] = 2

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("checks.sync_parity_passed" in error for error in result.errors), result.errors)

    def test_browser_replay_summary_requires_visual_and_code_lifecycle_cases(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["visual_lifecycle_case_count"] = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.visual_lifecycle_case_count" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_capability_snapshot_summary(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["wiii_connect_capability"]["snapshot_version"] = "wiii.other.v0"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("wiii_connect_capability.snapshot_version" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_capability_path_reason_hashes(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["wiii_connect_capability"]["paths"][2]["reason_hash_present"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("wiii_connect_capability.paths.*.reason_hash_present" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_requires_capability_path_count_consistency(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["wiii_connect_capability"]["path_count_matches_readiness_count"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                "wiii_connect_capability.path_count_matches_readiness_count" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_browser_replay_summary_requires_archive_index_contract(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["summary_archive"]["enabled"] = False

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("summary_archive.enabled" in error for error in result.errors), result.errors)

    def test_browser_replay_summary_wildcard_checks_all_cases(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"][1]["ledger_schema_version"] = "wiii.other.v1"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*.ledger_schema_version" in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_wildcard_requires_matching_cases(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("matched no values" in error for error in result.errors), result.errors)

    def test_browser_replay_summary_rejects_cases_object_for_wildcard_checks(
        self,
    ) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["browser_replay"]["cases"] = {
            f"case-{index}": item
            for index, item in enumerate(payload["browser_replay"]["cases"])
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(
            any("browser_replay.cases.*." in error for error in result.errors),
            result.errors,
        )

    def test_browser_replay_summary_fails_when_case_count_is_inconsistent(self) -> None:
        payload = _valid_browser_replay_summary_payload()
        payload["evidence"]["case_count"] = 4

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "runtime-flow-browser-replay-summary.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("len(browser_replay.cases)" in error for error in result.errors), result.errors)

    def test_missing_freshness_timestamp_fails(self) -> None:
        payload = _valid_lms_payload()
        payload.pop("generated_at")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("freshness timestamp" in error for error in result.errors), result.errors)

    def test_stale_artifact_fails(self) -> None:
        payload = _valid_lms_payload()
        payload["generated_at"] = "2026-05-20T10:00:00+00:00"

        with tempfile.TemporaryDirectory() as temp_dir:
            result = artifact_validator.validate_artifact(
                registry=self.registry,
                artifact_path=_write_json(
                    Path(temp_dir) / "lms-test-course-evidence.json",
                    payload,
                ),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("stale evidence" in error for error in result.errors), result.errors)

    def test_unknown_artifact_requires_requirement_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = _write_json(Path(temp_dir) / "unknown-evidence.json", {"status": "pass"})

            with self.assertRaises(ValueError):
                artifact_validator.validate_artifact(registry=self.registry, artifact_path=path)

    def test_requirement_id_still_requires_registered_artifact_filename(self) -> None:
        payload = _valid_provider_runtime_payload()

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "does not match registered artifact"):
                artifact_validator.validate_artifact(
                    registry=self.registry,
                    artifact_path=_write_json(Path(temp_dir) / "wrong-provider-name.json", payload),
                    requirement_id="provider-runtime-tool-loop",
                    as_of=AS_OF,
                )

        self.assertEqual(
            "registry_artifact_filename_mismatch",
            artifact_validator.normalize_artifact_error_code(
                "artifact filename 'wrong-provider-name.json' does not match registered artifact "
                "'provider-runtime-evidence.json' for requirement 'provider-runtime-tool-loop'"
            ),
        )

    def test_registry_payload_contract_requires_checks(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["requirements"][0]["payload_checks"] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = {
                "schema_version": "wiii.live_provider_runtime_probe.v1",
                "generated_at": GENERATED_AT,
                "status": "pass",
            }
            result = artifact_validator.validate_artifact(
                registry=broken,
                artifact_path=_write_json(Path(temp_dir) / "provider-runtime-evidence.json", payload),
                as_of=AS_OF,
            )

        self.assertFalse(result.ok)
        self.assertTrue(any("payload_checks" in error for error in result.errors), result.errors)


if __name__ == "__main__":
    unittest.main()
