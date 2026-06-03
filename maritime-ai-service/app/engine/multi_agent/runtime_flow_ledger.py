"""Privacy-safe runtime flow ledger for Wiii chat turns."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping

from app.engine.multi_agent.context_provenance_ledger import (
    build_context_provenance_ledger,
    build_request_context_provenance_ledger,
)
from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text
from app.engine.wiii_connect.connection_lifecycle import (
    sanitize_connection_lifecycle_metadata,
)


RUNTIME_FLOW_LEDGER_SCHEMA_VERSION = "wiii.runtime_flow_ledger.v1"
RUNTIME_FLOW_TRACE_VERSION = "wiii.runtime_flow_trace.v1"
SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION = "wiii.subagent_boundary_trace.v1"
_MAX_TOKEN_LENGTH = 96
_MAX_SEQUENCE_ITEMS = 24
_SAFE_LIFECYCLE_LABEL_RE = re.compile(
    rf"^[A-Za-z0-9_.:/-]{{1,{_MAX_TOKEN_LENGTH}}}$"
)


def _hash_identifier(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _safe_token(value: Any, *, max_length: int = _MAX_TOKEN_LENGTH) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    token = redact_runtime_secret_text(token)
    token = " ".join(token.split())
    if len(token) > max_length:
        return token[: max_length - 1] + "..."
    return token


def _safe_token_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    tokens: list[str] = []
    for value in values:
        token = _safe_token(value)
        if token and token not in tokens:
            tokens.append(token)
        if len(tokens) >= _MAX_SEQUENCE_ITEMS:
            break
    return tokens


def _safe_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _safe_public_mapping(
    value: Any,
    *,
    allowed_keys: set[str],
    max_items: int = _MAX_SEQUENCE_ITEMS,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        if key not in allowed_keys:
            continue
        result[key] = _safe_public_value(raw_value)
        if len(result) >= max_items:
            break
    return result


def _safe_public_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return _safe_token(value)
    if isinstance(value, Mapping):
        return {
            str(key): _safe_public_value(item)
            for key, item in list(value.items())[:_MAX_SEQUENCE_ITEMS]
            if not _looks_sensitive_key(str(key))
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_public_value(item) for item in list(value)[:_MAX_SEQUENCE_ITEMS]]
    return _safe_token(value)


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in (
            "authorization",
            "bearer",
            "connection_id",
            "connection_ref",
            "credential",
            "external_account_ref",
            "page_id",
            "password",
            "provider_payload",
            "raw_provider",
            "secret",
            "token",
            "api_key",
            "vault_ref",
            "code",
        )
    )


def _plain_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        model_value = value.model_dump()
        return model_value if isinstance(model_value, Mapping) else {}
    if hasattr(value, "dict"):
        dict_value = value.dict()
        return dict_value if isinstance(dict_value, Mapping) else {}
    return {}


def _request_id_from_state(state: Mapping[str, Any]) -> str | None:
    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    for candidate in (
        state.get("request_id"),
        context.get("request_id") if isinstance(context, Mapping) else None,
    ):
        request_id = _safe_token(candidate)
        if request_id:
            return request_id
    return None


def _context_value(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _host_context_from_request(chat_request: Any) -> Mapping[str, Any]:
    user_context = _context_value(chat_request, "user_context")
    host_context = _context_value(user_context, "host_context")
    return _plain_mapping(host_context)


def _document_context_from_request(chat_request: Any) -> Mapping[str, Any]:
    user_context = _context_value(chat_request, "user_context")
    document_context = _context_value(user_context, "document_context")
    return _plain_mapping(document_context)


def _uploaded_document_count(chat_request: Any) -> int:
    document_context = _document_context_from_request(chat_request)
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return 0
    return sum(
        1
        for item in attachments
        if isinstance(item, Mapping) and bool(str(item.get("markdown") or "").strip())
    )


def _host_surface(host_context: Mapping[str, Any]) -> str:
    for key in ("surface", "host_surface", "app_surface", "client", "source"):
        token = _safe_token(host_context.get(key))
        if token:
            return token
    return "unknown"


def _host_capabilities(host_context: Mapping[str, Any]) -> list[str]:
    capabilities = _safe_token_list(host_context.get("capabilities"))
    if capabilities:
        return capabilities
    if not host_context:
        return []
    safe_keys = {
        "lms",
        "document_preview",
        "host_action",
        "pointy",
        "visual",
        "code_studio",
    }
    return sorted(key for key in safe_keys if bool(host_context.get(key)))


def _source_count(value: Any) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, Mapping):
        sources = (
            value.get("sources")
            or value.get("source_refs")
            or value.get("source_references")
            or value.get("citations")
        )
        if isinstance(sources, (list, tuple)):
            return len(sources)
    return 0


def _event_tool_name(event_type: str, content: Any) -> str | None:
    if event_type in {
        "visual",
        "visual_open",
        "visual_patch",
        "visual_commit",
        "visual_dispose",
    }:
        return "visual_runtime"
    if event_type in {"code_open", "code_delta", "code_complete"}:
        return "code_studio"
    if event_type == "preview":
        return "preview"
    if not isinstance(content, Mapping):
        if event_type in {
            "tool_call",
            "tool_result",
            "host_action",
            "host_action_result",
            "pointy_action",
        }:
            return event_type
        return None
    for key in ("tool_name", "name", "tool", "action", "type"):
        token = _safe_token(content.get(key))
        if token:
            return token
    if event_type in {
        "tool_call",
        "tool_result",
        "host_action",
        "host_action_result",
        "pointy_action",
    }:
        return event_type
    return None


def _preserve_provenance_section(
    provenance: dict[str, Any],
    previous: Mapping[str, Any],
    *,
    section: str,
    count_key: str,
) -> None:
    current_section = provenance.get(section)
    previous_section = previous.get(section)
    if not isinstance(current_section, Mapping) or not isinstance(
        previous_section,
        Mapping,
    ):
        return
    if int(current_section.get(count_key) or 0) == 0 and int(
        previous_section.get(count_key) or 0
    ) > 0:
        provenance[section] = dict(previous_section)


def _preserve_request_provenance(
    provenance: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(previous, Mapping):
        return provenance
    _preserve_provenance_section(
        provenance,
        previous,
        section="documents",
        count_key="usable_attachment_count",
    )
    current_host = provenance.get("host")
    previous_host = previous.get("host")
    if (
        isinstance(current_host, Mapping)
        and isinstance(previous_host, Mapping)
        and not current_host.get("host_context_present")
        and previous_host.get("host_context_present")
    ):
        provenance["host"] = dict(previous_host)
    warnings = provenance.get("warnings")
    documents = provenance.get("documents")
    if isinstance(warnings, list) and isinstance(documents, Mapping):
        if (
            int(documents.get("usable_attachment_count") or 0) > 0
            and int(documents.get("source_ref_count") or 0) == 0
            and "document_context_without_source_refs" not in warnings
        ):
            warnings.append("document_context_without_source_refs")
    return provenance


_TURN_PATH_DECISION_KEYS = {
    "version",
    "path",
    "reason",
    "bind_tools",
    "force_tools",
    "allow_all_tools",
    "allowed_tool_names",
    "allowed_tool_prefixes",
    "forbidden_tool_names",
    "forbidden_tool_prefixes",
    "allow_agent_handoff",
    "allow_rag_delegation",
}
_TOOL_POLICY_SESSION_KEYS = {
    "version",
    "path",
    "reason",
    "bind_tools",
    "force_tools",
    "allow_all_tools",
    "allowed_tool_names",
    "allowed_tool_prefixes",
    "forbidden_tool_names",
    "forbidden_tool_prefixes",
    "candidate_tool_names",
    "visible_tool_names",
    "connection_status",
    "approval_required_tool_names",
    "tool_capabilities",
    "external_app_action_plan",
    "external_app_integration_lane",
    "allow_agent_handoff",
    "allow_rag_delegation",
}
_EXTERNAL_APP_ACTION_PLAN_KEYS = {
    "version",
    "status",
    "kind",
    "provider_slug",
    "action_slug",
    "reason",
    "forced_tool_name",
    "allowed_tool_names",
    "requested_provider_slugs",
    "ready_provider_slugs",
    "action_allowlists_by_provider",
    "connection_lifecycle",
    "unavailable_answer_present",
}
_EXTERNAL_APP_INTEGRATION_LANE_KEYS = {
    "version",
    "status",
    "executor",
    "provider_slug",
    "action_slug",
    "reason",
    "visible_tool_names",
    "forced_tool_name",
    "requested_provider_slugs",
    "ready_provider_slugs",
    "action_allowlists_by_provider",
    "ui_activity_title",
}
_FINAL_ANSWER_TRACE_KEYS = {
    "version",
    "source",
    "reason",
    "status",
    "provider_slug",
    "action_slug",
    "answer_present",
}
_GATEWAY_TRACE_KEYS = {
    "version",
    "status",
    "reason",
    "connection_present",
    "audit_persistent",
    "required_next",
}
_SCHEMA_TRACE_KEYS = {"ready", "reason", "required_argument_keys"}
_EXECUTION_TRACE_KEYS = {"status", "reason", "success", "provider_status"}
_STORAGE_TRACE_KEYS = {
    "persistent",
    "connection_table_ready",
    "audit_ledger_ready",
}
_EXTERNAL_ACTION_TRACE_KEYS = {
    "version",
    "observed_action_result",
    "result_count",
    "last_status",
    "last_success",
    "provider_slug",
    "action",
    "action_slug",
    "gateway",
    "integration_worker",
    "worker_outcome",
    "worker_failed_stage",
    "worker_reason",
    "provider_call_correlation",
}
_EXTERNAL_ACTION_TRACE_EVENT_KEYS = {
    "type",
    "tool_name",
    "policy",
    "status",
    "success",
    "provider_slug",
    "action",
    "action_slug",
    "summary_present",
    "gateway",
    "schema",
    "execution",
    "storage",
    "integration_worker",
    "provider_call_correlation",
}
_PROVIDER_CALL_CORRELATION_COUNT_KEYS = {
    "stage_count",
    "stage_request_id_present_count",
    "stage_request_id_missing_count",
    "stage_request_id_match_count",
    "stage_request_id_mismatch_count",
}


def build_runtime_flow_trace_from_state(
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build an OpenHuman-style sanitized trace from final AgentState."""

    if not isinstance(state, Mapping):
        return {"version": RUNTIME_FLOW_TRACE_VERSION}
    request_id = _request_id_from_state(state)
    action_trace = _build_external_action_trace(
        state.get("tool_call_events"),
        request_id=request_id,
    )
    return {
        "version": RUNTIME_FLOW_TRACE_VERSION,
        "turn_path_decision": _plain_turn_path_decision(
            state.get("_turn_path_decision")
        ),
        "tool_policy_session": _plain_tool_policy_session(
            state.get("_tool_policy_session")
        ),
        "external_app_action_plan": _plain_external_app_action_plan(
            state.get("_external_app_action_plan")
        ),
        "external_app_integration_lane": _plain_external_app_integration_lane(
            state.get("_external_app_integration_lane")
        ),
        "external_action_trace": action_trace,
        "subagents": _plain_subagent_boundary_trace(state.get("subagent_reports")),
        "final_answer": _plain_final_answer_trace(
            state.get("_final_answer_trace"),
            action_trace=action_trace,
        ),
    }


def sanitize_runtime_flow_trace(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize an existing trace before exposing it through response metadata."""

    if not isinstance(trace, Mapping):
        return {"version": RUNTIME_FLOW_TRACE_VERSION}
    action_trace = _plain_external_action_trace(trace.get("external_action_trace"))
    return {
        "version": RUNTIME_FLOW_TRACE_VERSION,
        "turn_path_decision": _plain_turn_path_decision(
            trace.get("turn_path_decision")
        ),
        "tool_policy_session": _plain_tool_policy_session(
            trace.get("tool_policy_session")
        ),
        "external_app_action_plan": _plain_external_app_action_plan(
            trace.get("external_app_action_plan")
        ),
        "external_app_integration_lane": _plain_external_app_integration_lane(
            trace.get("external_app_integration_lane")
        ),
        "external_action_trace": action_trace,
        "subagents": _plain_subagent_boundary_trace(trace.get("subagents")),
        "final_answer": _plain_final_answer_trace(
            trace.get("final_answer"),
            action_trace=action_trace,
        ),
    }


def _nonnegative_int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _safe_lifecycle_label(value: Any, *, fallback: str = "unknown") -> str:
    token = _safe_token(value)
    if not token:
        return fallback
    if _SAFE_LIFECYCLE_LABEL_RE.fullmatch(token):
        return token
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    safe_fallback = (
        fallback if _SAFE_LIFECYCLE_LABEL_RE.fullmatch(fallback) else "unknown"
    )
    return f"{safe_fallback}_hash:{digest}"


def _plain_lifecycle_privacy(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    return {
        "raw_content_included": bool(source.get("raw_content_included")),
        "identifier_strategy": _safe_lifecycle_label(
            source.get("identifier_strategy"),
            fallback="status_only",
        ),
    }


def _plain_background_schedule(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    if not source:
        return {}
    groups: list[dict[str, str]] = []
    source_groups = source.get("groups")
    if isinstance(source_groups, list):
        for raw_group in source_groups[:_MAX_SEQUENCE_ITEMS]:
            group = _plain_mapping(raw_group)
            groups.append(
                {
                    "group": _safe_lifecycle_label(group.get("group")),
                    "status": _safe_lifecycle_label(group.get("status")),
                    "reason": _safe_lifecycle_label(group.get("reason")),
                }
            )
    return {
        "schema_version": _safe_lifecycle_label(source.get("schema_version")),
        "task_count": _nonnegative_int(source.get("task_count")),
        "groups": groups,
        "privacy": _plain_lifecycle_privacy(source.get("privacy")),
    }


def _plain_post_turn_lifecycle(value: Any) -> dict[str, Any] | None:
    source = _plain_mapping(value)
    if not source:
        return None
    result: dict[str, Any] = {
        "schema_version": _safe_lifecycle_label(source.get("schema_version")),
        "status": _safe_lifecycle_label(source.get("status")),
        "reason": _safe_lifecycle_label(source.get("reason")),
        "semantic_memory_policy": _safe_lifecycle_label(
            source.get("semantic_memory_policy")
        ),
        "background_tasks_scheduled": bool(source.get("background_tasks_scheduled")),
        "privacy": _plain_lifecycle_privacy(source.get("privacy")),
    }
    background_schedule = _plain_background_schedule(source.get("background_schedule"))
    if background_schedule:
        result["background_schedule"] = background_schedule
    return result


def _plain_subagent_boundary_trace(value: Any) -> dict[str, Any]:
    source_mapping = _plain_mapping(value)
    if source_mapping:
        reports = source_mapping.get("reports")
        reports = reports if isinstance(reports, list) else []
        report_count = _nonnegative_int(source_mapping.get("report_count")) or len(
            reports
        )
    else:
        reports = value if isinstance(value, list) else []
        report_count = len(reports)
    safe_reports: list[dict[str, Any]] = []
    warning_codes: set[str] = set(_safe_token_list(source_mapping.get("warning_codes")))
    raw_content_flagged = bool(source_mapping.get("raw_content_included"))
    for raw_report in reports[:_MAX_SEQUENCE_ITEMS]:
        report = _plain_mapping(raw_report)
        if "result" not in report:
            safe_reports.append(
                {
                    "agent_name": _safe_token(report.get("agent_name")) or "unknown",
                    "agent_type": _safe_token(report.get("agent_type")) or "general",
                    "status": _safe_token(report.get("status")) or "unknown",
                    "handoff_schema_version": _safe_token(
                        report.get("handoff_schema_version")
                    ),
                    "result_schema_version": _safe_token(
                        report.get("result_schema_version")
                    ),
                    "state_projected_key_count": _nonnegative_int(
                        report.get("state_projected_key_count")
                    ),
                    "state_dropped_key_count": _nonnegative_int(
                        report.get("state_dropped_key_count")
                    ),
                    "output_char_count": _nonnegative_int(
                        report.get("output_char_count")
                    ),
                    "source_count": _nonnegative_int(report.get("source_count")),
                    "tool_count": _nonnegative_int(report.get("tool_count")),
                    "thinking_dropped": bool(report.get("thinking_dropped")),
                }
            )
            continue
        result = _plain_mapping(report.get("result"))
        boundary = _plain_mapping(result.get("boundary"))
        handoff = _plain_mapping(boundary.get("handoff"))
        handoff_state = _plain_mapping(handoff.get("state"))
        result_boundary = _plain_mapping(boundary.get("result"))
        for warning in _safe_token_list(boundary.get("warning_codes")):
            warning_codes.add(warning)
        for warning in _safe_token_list(handoff.get("warning_codes")):
            warning_codes.add(warning)
        for warning in _safe_token_list(result_boundary.get("warning_codes")):
            warning_codes.add(warning)
        raw_content_flagged = raw_content_flagged or bool(
            boundary.get("raw_content_included")
            or handoff.get("raw_content_included")
            or result_boundary.get("raw_content_included")
        )
        safe_reports.append(
            {
                "agent_name": _safe_token(report.get("agent_name")) or "unknown",
                "agent_type": _safe_token(report.get("agent_type")) or "general",
                "status": _safe_token(
                    result_boundary.get("status") or result.get("status")
                )
                or "unknown",
                "handoff_schema_version": _safe_token(
                    handoff.get("schema_version")
                ),
                "result_schema_version": _safe_token(
                    result_boundary.get("schema_version")
                ),
                "state_projected_key_count": _nonnegative_int(
                    handoff_state.get("projected_key_count")
                ),
                "state_dropped_key_count": _nonnegative_int(
                    handoff_state.get("dropped_key_count")
                ),
                "output_char_count": _nonnegative_int(
                    result_boundary.get("output_char_count")
                ),
                "source_count": _nonnegative_int(
                    result_boundary.get("source_count")
                ),
                "tool_count": _nonnegative_int(result_boundary.get("tool_count")),
                "thinking_dropped": bool(result_boundary.get("thinking_dropped")),
            }
        )
    return {
        "schema_version": SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
        "report_count": report_count,
        "reports": safe_reports,
        "raw_content_included": raw_content_flagged,
        "warning_codes": sorted(warning_codes)[:_MAX_SEQUENCE_ITEMS],
    }


def _plain_turn_path_decision(value: Any) -> dict[str, Any]:
    return _safe_public_mapping(value, allowed_keys=_TURN_PATH_DECISION_KEYS)


def _plain_tool_policy_session(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    session = _safe_public_mapping(source, allowed_keys=_TOOL_POLICY_SESSION_KEYS)
    capabilities = session.get("tool_capabilities")
    if isinstance(capabilities, dict):
        session["tool_capabilities"] = {
            str(tool_name): _safe_public_value(metadata)
            for tool_name, metadata in list(capabilities.items())[:_MAX_SEQUENCE_ITEMS]
            if isinstance(metadata, Mapping)
        }
    action_plan = _plain_external_app_action_plan(
        source.get("external_app_action_plan")
    )
    if action_plan:
        session["external_app_action_plan"] = action_plan
    else:
        session.pop("external_app_action_plan", None)
    integration_lane = _plain_external_app_integration_lane(
        source.get("external_app_integration_lane")
    )
    if integration_lane:
        session["external_app_integration_lane"] = integration_lane
    else:
        session.pop("external_app_integration_lane", None)
    return session


def _plain_external_app_action_plan(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    plan = _safe_public_mapping(source, allowed_keys=_EXTERNAL_APP_ACTION_PLAN_KEYS)
    lifecycle = sanitize_connection_lifecycle_metadata(
        source.get("connection_lifecycle")
    )
    if lifecycle:
        plan["connection_lifecycle"] = lifecycle
    else:
        plan.pop("connection_lifecycle", None)
    return plan


def _plain_external_app_integration_lane(value: Any) -> dict[str, Any]:
    return _safe_public_mapping(
        value,
        allowed_keys=_EXTERNAL_APP_INTEGRATION_LANE_KEYS,
    )


def _plain_final_answer_trace(
    value: Any,
    *,
    action_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    trace = _safe_public_mapping(value, allowed_keys=_FINAL_ANSWER_TRACE_KEYS)
    if trace:
        return trace
    if isinstance(action_trace, Mapping) and action_trace.get("observed_action_result"):
        return {
            "version": "final_answer_trace.v1",
            "source": "missing_explicit_final_answer_source",
            "reason": "external_action_result_seen_without_final_answer_trace",
            "answer_present": None,
        }
    return {}


def _plain_external_action_trace(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    if not source:
        return {
            "version": "wiii.external_action_trace.v1",
            "observed_action_result": False,
            "result_count": 0,
            "events": [],
        }
    trace = _safe_public_mapping(
        source,
        allowed_keys=_EXTERNAL_ACTION_TRACE_KEYS,
    )
    events = source.get("events")
    if isinstance(events, (list, tuple)):
        safe_events: list[dict[str, Any]] = []
        for raw_event in events[:_MAX_SEQUENCE_ITEMS]:
            event = _safe_public_mapping(
                raw_event,
                allowed_keys=_EXTERNAL_ACTION_TRACE_EVENT_KEYS,
            )
            if event:
                safe_events.append(event)
        trace["events"] = safe_events
    else:
        trace.setdefault("events", [])
    trace.setdefault("version", "wiii.external_action_trace.v1")
    trace.setdefault("observed_action_result", False)
    trace.setdefault("result_count", len(trace.get("events") or []))
    trace["provider_call_correlation"] = _plain_provider_call_correlation(
        trace.get("provider_call_correlation")
    )
    if not trace["provider_call_correlation"]:
        trace.pop("provider_call_correlation", None)
    return trace


def _build_external_action_trace(
    value: Any,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": "wiii.external_action_trace.v1",
        "observed_action_result": False,
        "result_count": 0,
        "events": [],
    }
    if not isinstance(value, (list, tuple)):
        return result

    events: list[dict[str, Any]] = []
    last_status = ""
    last_success: bool | None = None
    last_provider = ""
    last_action = ""
    last_action_slug = ""
    last_gateway: dict[str, Any] = {}
    last_worker: dict[str, Any] = {}
    provider_call_correlation: dict[str, Any] = {}

    for raw_event in value[:_MAX_SEQUENCE_ITEMS]:
        if not isinstance(raw_event, Mapping):
            continue
        event_type = _safe_token(raw_event.get("type")) or ""
        tool_name = _safe_token(raw_event.get("name")) or ""
        policy = _plain_policy_denial(raw_event.get("policy"))
        payload = _parse_tool_result_payload(raw_event.get("result"))
        if not payload and not policy:
            continue

        event_trace: dict[str, Any] = {
            "type": event_type,
            "tool_name": tool_name,
        }
        if policy:
            event_trace["policy"] = policy
        if _is_external_action_payload(payload):
            event_trace.update(
                _plain_external_action_result_payload(
                    payload,
                    request_id=request_id,
                )
            )
            provider_call_correlation = _merge_provider_call_correlation(
                provider_call_correlation,
                event_trace.get("provider_call_correlation"),
            )
            last_status = str(event_trace.get("status") or last_status)
            success = event_trace.get("success")
            if isinstance(success, bool):
                last_success = success
            last_provider = str(event_trace.get("provider_slug") or last_provider)
            last_action = str(event_trace.get("action") or last_action)
            last_action_slug = str(event_trace.get("action_slug") or last_action_slug)
            gateway = event_trace.get("gateway")
            if isinstance(gateway, dict):
                last_gateway = gateway
            worker = event_trace.get("integration_worker")
            if isinstance(worker, dict):
                last_worker = worker
        events.append(event_trace)

    result["events"] = events
    result["result_count"] = sum(
        1 for event in events if str(event.get("type") or "") == "result"
    )
    result["observed_action_result"] = any(
        "status" in event and "provider_slug" in event for event in events
    )
    if last_status:
        result["last_status"] = last_status
    if last_success is not None:
        result["last_success"] = last_success
    if last_provider:
        result["provider_slug"] = last_provider
    if last_action:
        result["action"] = last_action
    if last_action_slug:
        result["action_slug"] = last_action_slug
    if last_gateway:
        result["gateway"] = last_gateway
    if last_worker:
        result["integration_worker"] = last_worker
        classification = last_worker.get("result_classification")
        if isinstance(classification, Mapping):
            outcome = _safe_token(classification.get("outcome"))
            failed_stage = _safe_token(classification.get("failed_stage"))
            reason = _safe_token(classification.get("reason"))
            if outcome:
                result["worker_outcome"] = outcome
            if failed_stage:
                result["worker_failed_stage"] = failed_stage
            if reason:
                result["worker_reason"] = reason
    if provider_call_correlation:
        result["provider_call_correlation"] = provider_call_correlation
    return result


def _plain_external_action_result_payload(
    payload: Mapping[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "status": _safe_token(payload.get("status")),
        "success": _safe_bool(payload.get("success")),
        "provider_slug": _safe_token(payload.get("provider_slug")),
        "action": _safe_token(payload.get("action")),
        "action_slug": _safe_token(payload.get("action_slug")),
        "summary_present": bool(str(payload.get("summary") or "").strip()),
    }
    gateway = _plain_gateway_trace(payload.get("gateway"))
    if gateway:
        trace["gateway"] = gateway
    schema = _safe_public_mapping(
        payload.get("schema"),
        allowed_keys=_SCHEMA_TRACE_KEYS,
    )
    if schema:
        trace["schema"] = schema
    execution = _safe_public_mapping(
        payload.get("execution"),
        allowed_keys=_EXECUTION_TRACE_KEYS,
    )
    if execution:
        trace["execution"] = execution
    storage = _safe_public_mapping(
        payload.get("storage"),
        allowed_keys=_STORAGE_TRACE_KEYS,
    )
    if storage:
        trace["storage"] = storage
    worker = _plain_integration_worker_trace(payload)
    if worker:
        trace["integration_worker"] = worker
    correlation = _provider_call_correlation_trace(
        payload,
        request_id=request_id,
    )
    if correlation:
        trace["provider_call_correlation"] = correlation
    return {key: value for key, value in trace.items() if value not in ("", None)}


def _plain_gateway_trace(value: Any) -> dict[str, Any]:
    gateway = _safe_public_mapping(value, allowed_keys=_GATEWAY_TRACE_KEYS)
    if not gateway:
        return {}
    raw_decision = value.get("decision") if isinstance(value, Mapping) else None
    if isinstance(raw_decision, Mapping):
        gateway["decision"] = _safe_public_mapping(
            raw_decision,
            allowed_keys={
                "outcome",
                "reason",
                "provider_slug",
                "action_slug",
                "path",
                "mutation",
                "required_scopes",
            },
        )
    return gateway


def _plain_integration_worker_trace(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return {}
    worker = data.get("integration_worker")
    if not isinstance(worker, Mapping):
        return {}
    return _safe_public_mapping(
        worker,
        allowed_keys={
            "version",
            "status",
            "reason",
            "executor",
            "provider_slug",
            "requested_provider_slug",
            "allowed_provider_slugs",
            "requested_action_slug",
            "requested_mutation",
            "action_slug",
            "selected_mutation",
            "action_allowlist",
            "stage_sequence",
            "result_classification",
            "planner_version",
            "worker_result_version",
        },
    )


def _plain_policy_denial(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    allowed = _safe_bool(value.get("allowed"))
    if allowed is not False:
        return {}
    return _safe_public_mapping(
        value,
        allowed_keys={"allowed", "path", "reason"},
    )


def _tool_policy_denials_from_trace(
    trace: Mapping[str, Any],
) -> list[dict[str, Any]]:
    action_trace = trace.get("external_action_trace")
    if not isinstance(action_trace, Mapping):
        return []
    events = action_trace.get("events")
    if not isinstance(events, list):
        return []
    denials: list[dict[str, Any]] = []
    for event in events[:_MAX_SEQUENCE_ITEMS]:
        if not isinstance(event, Mapping):
            continue
        policy = event.get("policy")
        if not isinstance(policy, Mapping):
            continue
        denial = _plain_policy_denial(policy)
        if not denial:
            continue
        denials.append(
            {
                "tool_name": _safe_token(event.get("tool_name")),
                "path": _safe_token(denial.get("path")),
                "reason": _safe_token(denial.get("reason")),
            }
        )
    return denials


def _parse_tool_result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _is_external_action_payload(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    if _is_catalog_only_external_payload(payload):
        return False
    version = str(payload.get("version") or "")
    if version.startswith("wiii_connect_"):
        return True
    action = str(payload.get("action") or "")
    status = str(payload.get("status") or "")
    return bool(
        payload.get("provider_slug")
        and status
        and (
            action.startswith("wiii_connect.")
            or status.startswith("action_")
            or status in {"validation_failed", "approval_required", "preview_required"}
        )
    )


def _is_catalog_only_external_payload(payload: Mapping[str, Any]) -> bool:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return False
    if "action_catalog" not in data:
        return False
    if payload.get("action") or payload.get("action_slug"):
        return False
    if "integration_worker" in data or "execution_gate" in data:
        return False
    return not any(payload.get(key) for key in ("gateway", "schema", "execution"))


def _provider_call_correlation_trace(
    payload: Mapping[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    stages = list(_iter_provider_call_stage_maps(payload))
    if not stages:
        return {}

    expected_request_id = _safe_token(request_id)
    stage_request_ids: list[str] = []
    for _stage_name, stage in stages:
        stage_request_id = _safe_token(stage.get("request_id"))
        if stage_request_id:
            stage_request_ids.append(stage_request_id)
    stage_count = len(stages)
    present_count = len(stage_request_ids)
    missing_count = max(0, stage_count - present_count)
    match_count = (
        sum(1 for stage_request_id in stage_request_ids if stage_request_id == expected_request_id)
        if expected_request_id
        else 0
    )
    mismatch_count = (
        sum(1 for stage_request_id in stage_request_ids if stage_request_id != expected_request_id)
        if expected_request_id
        else 0
    )

    return {
        "provider_call_seen": True,
        "request_id_present": bool(expected_request_id),
        "stage_count": stage_count,
        "stage_request_id_present_count": present_count,
        "stage_request_id_missing_count": missing_count,
        "stage_request_id_match_count": match_count,
        "stage_request_id_mismatch_count": mismatch_count,
        "stage_request_id_consistent": (
            present_count == stage_count and len(set(stage_request_ids)) <= 1
        ),
        "all_stage_request_ids_match_request": (
            bool(expected_request_id)
            and stage_count > 0
            and missing_count == 0
            and mismatch_count == 0
        ),
    }


def _iter_provider_call_stage_maps(
    payload: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    stages: list[tuple[str, Mapping[str, Any]]] = []
    for key in ("schema", "execution", "upload", "page_list", "provider"):
        section = _plain_mapping(payload.get(key))
        if section:
            stages.append((key, section))

    data = _plain_mapping(payload.get("data"))
    for key in ("schema", "execution", "upload", "page_list", "provider"):
        section = _plain_mapping(data.get(key))
        if section:
            stages.append((key, section))
    return stages[:_MAX_SEQUENCE_ITEMS]


def _plain_provider_call_correlation(value: Any) -> dict[str, Any]:
    source = _plain_mapping(value)
    if not source:
        return {}
    stage_count = _positive_int(source.get("stage_count"))
    result: dict[str, Any] = {}
    if bool(source.get("provider_call_seen")) or stage_count > 0:
        result["provider_call_seen"] = True
    if "request_id_present" in source:
        result["request_id_present"] = bool(source.get("request_id_present"))
    for key in _PROVIDER_CALL_CORRELATION_COUNT_KEYS:
        result[key] = _positive_int(source.get(key))
    if "stage_request_id_consistent" in source:
        result["stage_request_id_consistent"] = bool(
            source.get("stage_request_id_consistent")
        )
    if "all_stage_request_ids_match_request" in source:
        result["all_stage_request_ids_match_request"] = bool(
            source.get("all_stage_request_ids_match_request")
        )
    return result if result.get("provider_call_seen") else {}


def _merge_provider_call_correlation(
    current: Mapping[str, Any] | None,
    update: Any,
) -> dict[str, Any]:
    incoming = _plain_provider_call_correlation(update)
    if not incoming:
        return dict(current or {})
    merged = _plain_provider_call_correlation(current)
    merged["provider_call_seen"] = True
    merged["request_id_present"] = bool(
        merged.get("request_id_present") or incoming.get("request_id_present")
    )
    for key in _PROVIDER_CALL_CORRELATION_COUNT_KEYS:
        merged[key] = _positive_int(merged.get(key)) + _positive_int(
            incoming.get(key)
        )

    current_consistent = merged.get("stage_request_id_consistent")
    incoming_consistent = incoming.get("stage_request_id_consistent")
    merged["stage_request_id_consistent"] = (
        current_consistent is not False and incoming_consistent is not False
    )
    merged["all_stage_request_ids_match_request"] = bool(
        merged.get("request_id_present")
        and merged.get("stage_count")
        and merged.get("stage_request_id_missing_count") == 0
        and merged.get("stage_request_id_mismatch_count") == 0
    )
    return _plain_provider_call_correlation(merged)


def _positive_int(value: Any) -> int:
    return value if type(value) is int and value > 0 else 0


@dataclass
class RuntimeFlowLedger:
    """Mutable recorder that serializes to a stable, privacy-safe payload."""

    request_id: str | None
    provider_requested: str | None = None
    model_requested: str | None = None
    session_id: str | None = None
    user_id_hash: str | None = None
    organization_id_hash: str | None = None
    domain_id: str | None = None
    host_surface: str = "unknown"
    host_capabilities: list[str] = field(default_factory=list)
    document_context_present: bool = False
    uploaded_document_count: int = 0
    route_lane: str = "preparing"
    route_reason: str | None = None
    selected_agent: str | None = None
    final_agent: str | None = None
    provider: str | None = None
    model: str | None = None
    runtime_authoritative: bool | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    failover_used: bool = False
    observed_tools: list[str] = field(default_factory=list)
    suppressed_tools: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    event_sequence_tail: list[str] = field(default_factory=list)
    metadata_seen: bool = False
    done_seen: bool = False
    source_ref_count: int = 0
    memory_context_count: int | None = None
    history_context_count: int | None = None
    history_retrieval_status: str = "unknown"
    history_source: str | None = None
    context_budget_utilization: float | None = None
    context_budget_messages_dropped: int | None = None
    context_budget_status: str = "unknown"
    context_provenance: dict[str, Any] | None = None
    preview_required: bool = False
    preview_emitted: bool = False
    approval_token_present: bool = False
    approval_token_hash: str | None = None
    apply_attempted: bool = False
    host_action_result_received: bool = False
    host_action_result_success: bool | None = None
    host_action_result_statuses: list[str] = field(default_factory=list)
    mutation_blocked_reason: str | None = None
    turn_path_decision: dict[str, Any] = field(default_factory=dict)
    tool_policy_session: dict[str, Any] = field(default_factory=dict)
    tool_policy_denials: list[dict[str, Any]] = field(default_factory=list)
    external_app_action_plan: dict[str, Any] = field(default_factory=dict)
    external_app_integration_lane: dict[str, Any] = field(default_factory=dict)
    external_action_trace: dict[str, Any] = field(default_factory=dict)
    subagent_boundary_trace: dict[str, Any] = field(default_factory=dict)
    final_answer_trace: dict[str, Any] = field(default_factory=dict)
    finalization_status: str = "pending"
    finalization_error_type: str | None = None
    save_response_immediately: bool | None = None
    post_turn_lifecycle: dict[str, Any] | None = None

    @classmethod
    def from_chat_request(
        cls,
        *,
        chat_request: Any,
        request_id: str | None,
    ) -> "RuntimeFlowLedger":
        host_context = _host_context_from_request(chat_request)
        uploaded_count = _uploaded_document_count(chat_request)
        host_capabilities = _host_capabilities(host_context)
        return cls(
            request_id=_safe_token(request_id),
            provider_requested=_safe_token(_context_value(chat_request, "provider")),
            model_requested=_safe_token(_context_value(chat_request, "model")),
            user_id_hash=_hash_identifier(_context_value(chat_request, "user_id")),
            host_surface=_host_surface(host_context),
            host_capabilities=host_capabilities,
            document_context_present=uploaded_count > 0,
            uploaded_document_count=uploaded_count,
            context_provenance=build_request_context_provenance_ledger(
                chat_request
            ),
            preview_required=uploaded_count > 0 and "lms" in host_capabilities,
        )

    def mark_prepared_turn(
        self,
        *,
        session_id: Any,
        organization_id: Any,
        domain_id: Any,
    ) -> None:
        self.session_id = _safe_token(session_id)
        self.organization_id_hash = _hash_identifier(organization_id)
        self.domain_id = _safe_token(domain_id)

    def mark_route(
        self,
        lane: str,
        *,
        reason: str | None = None,
        fallback_used: bool | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        self.route_lane = _safe_token(lane) or "unknown"
        self.route_reason = _safe_token(reason)
        if fallback_used is not None:
            self.fallback_used = fallback_used
        if fallback_reason:
            self.fallback_reason = _safe_token(fallback_reason)

    def mark_execution_input(self, execution_input: Any) -> None:
        self.provider = self.provider or _safe_token(
            _context_value(execution_input, "provider")
        )
        self.model = self.model or _safe_token(
            _context_value(execution_input, "model")
        )
        context = _plain_mapping(_context_value(execution_input, "context"))
        self.context_provenance = _preserve_request_provenance(
            build_context_provenance_ledger(context),
            self.context_provenance,
        )
        documents = self.context_provenance.get("documents", {})
        if isinstance(documents, Mapping):
            uploaded_count = int(documents.get("usable_attachment_count") or 0)
            if uploaded_count > 0:
                self.document_context_present = True
                self.uploaded_document_count = max(
                    self.uploaded_document_count,
                    uploaded_count,
                )
            self.source_ref_count = max(
                self.source_ref_count,
                int(documents.get("source_ref_count") or 0),
            )

        source_refs = (
            context.get("source_refs")
            or context.get("sources")
            or context.get("source_references")
            or context.get("citations")
        )
        self.source_ref_count = max(self.source_ref_count, _source_count(source_refs))
        memories = context.get("memories") or context.get("semantic_memories")
        if isinstance(memories, (list, tuple)):
            self.memory_context_count = len(memories)
        memory = self.context_provenance.get("memory", {})
        if isinstance(memory, Mapping) and isinstance(
            memory.get("semantic_memory_count"),
            int,
        ):
            self.memory_context_count = memory.get("semantic_memory_count")
        conversation = self.context_provenance.get("conversation", {})
        if isinstance(conversation, Mapping):
            selected_history_count = conversation.get("selected_history_item_count")
            if isinstance(selected_history_count, int):
                self.history_context_count = selected_history_count
            elif isinstance(conversation.get("history_item_count"), int):
                self.history_context_count = conversation.get("history_item_count")
            self.history_retrieval_status = (
                _safe_token(conversation.get("history_retrieval_status"))
                or self.history_retrieval_status
            )
            self.history_source = (
                _safe_token(conversation.get("history_source"))
                or self.history_source
            )
            utilization = conversation.get("context_budget_utilization")
            if isinstance(utilization, (int, float)):
                numeric_utilization = float(utilization)
                if isfinite(numeric_utilization):
                    self.context_budget_utilization = round(numeric_utilization, 4)
            dropped = conversation.get("context_budget_messages_dropped")
            if isinstance(dropped, int):
                self.context_budget_messages_dropped = dropped
            self.context_budget_status = (
                _safe_token(conversation.get("context_budget_status"))
                or self.context_budget_status
            )

    def record_event(self, event: Any) -> None:
        event_type = _safe_token(getattr(event, "type", None)) or "unknown"
        content = getattr(event, "content", None)
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.event_sequence_tail.append(event_type)
        if len(self.event_sequence_tail) > _MAX_SEQUENCE_ITEMS:
            self.event_sequence_tail = self.event_sequence_tail[-_MAX_SEQUENCE_ITEMS:]
        if event_type == "metadata":
            self.metadata_seen = True
        elif event_type == "done":
            self.done_seen = True
        elif event_type == "sources":
            self.source_ref_count = max(self.source_ref_count, _source_count(content))
        elif event_type in {
            "tool_call",
            "tool_result",
            "host_action",
            "host_action_result",
            "pointy_action",
            "preview",
            "visual",
            "visual_open",
            "visual_patch",
            "visual_commit",
            "visual_dispose",
            "code_open",
            "code_delta",
            "code_complete",
        }:
            self._record_tool_event(event_type, content)

    def record_wire_event(self, event_type: str) -> None:
        event_type = _safe_token(event_type) or "unknown"
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.event_sequence_tail.append(event_type)
        if len(self.event_sequence_tail) > _MAX_SEQUENCE_ITEMS:
            self.event_sequence_tail = self.event_sequence_tail[-_MAX_SEQUENCE_ITEMS:]
        if event_type == "metadata":
            self.metadata_seen = True
        elif event_type == "done":
            self.done_seen = True

    def observe_metadata(self, metadata: Mapping[str, Any]) -> None:
        self.metadata_seen = True
        self.provider = self.provider or _safe_token(metadata.get("provider"))
        self.model = self.model or _safe_token(metadata.get("model"))
        runtime_authoritative = metadata.get("runtime_authoritative")
        if isinstance(runtime_authoritative, bool):
            self.runtime_authoritative = runtime_authoritative
        self.selected_agent = self.selected_agent or _safe_token(metadata.get("agent_type"))

        routing_metadata = metadata.get("routing_metadata")
        if isinstance(routing_metadata, Mapping):
            self.selected_agent = self.selected_agent or _safe_token(
                routing_metadata.get("selected_agent")
                or routing_metadata.get("target_agent")
            )
            self.final_agent = self.final_agent or _safe_token(
                routing_metadata.get("final_agent")
            )
            if not self.route_reason:
                self.route_reason = _safe_token(
                    routing_metadata.get("method") or routing_metadata.get("intent")
                )

        failover = metadata.get("failover")
        if isinstance(failover, Mapping):
            switched = failover.get("switched")
            self.failover_used = bool(switched)
            self.fallback_reason = self.fallback_reason or _safe_token(
                failover.get("last_reason_code") or failover.get("last_reason_category")
            )

        token = metadata.get("approval_token")
        token_hash = metadata.get("approval_token_hash")
        if token:
            self.approval_token_present = True
            self.approval_token_hash = _hash_identifier(token)
        elif token_hash:
            self.approval_token_present = True
            self.approval_token_hash = _safe_token(token_hash)

        runtime_trace = metadata.get("runtime_flow_trace")
        if isinstance(runtime_trace, Mapping):
            self.observe_runtime_trace(runtime_trace)

    def mark_finalization(
        self,
        status: str,
        *,
        error: Exception | None = None,
        save_response_immediately: bool | None = None,
        post_turn_lifecycle: Mapping[str, Any] | None = None,
    ) -> None:
        self.finalization_status = _safe_token(status) or "unknown"
        self.finalization_error_type = type(error).__name__ if error else None
        self.save_response_immediately = save_response_immediately
        self.post_turn_lifecycle = _plain_post_turn_lifecycle(post_turn_lifecycle)

    def _record_tool_event(self, event_type: str, content: Any) -> None:
        tool_name = _event_tool_name(event_type, content)
        if tool_name and tool_name not in self.observed_tools:
            self.observed_tools.append(tool_name)
        if event_type == "preview":
            self.preview_emitted = True
        if isinstance(content, Mapping):
            if event_type == "host_action_result":
                self.host_action_result_received = True
                success = content.get("success")
                if isinstance(success, bool):
                    self.host_action_result_success = success
                status = _safe_token(content.get("status"))
                if status and status not in self.host_action_result_statuses:
                    self.host_action_result_statuses.append(status)
                    if len(self.host_action_result_statuses) > _MAX_SEQUENCE_ITEMS:
                        self.host_action_result_statuses = (
                            self.host_action_result_statuses[-_MAX_SEQUENCE_ITEMS:]
                        )
            action = _safe_token(
                content.get("action") or content.get("type") or content.get("name")
            )
            if action and "preview" in action.lower():
                self.preview_emitted = True
            if action and "apply" in action.lower():
                self.apply_attempted = True
            token = content.get("approval_token")
            token_hash = content.get("approval_token_hash")
            if token:
                self.approval_token_present = True
                self.approval_token_hash = _hash_identifier(token)
            elif token_hash:
                self.approval_token_present = True
                self.approval_token_hash = _safe_token(token_hash)

    def observe_runtime_trace(self, trace: Mapping[str, Any]) -> None:
        """Merge sanitized runtime policy/action trace into the ledger."""

        if not isinstance(trace, Mapping):
            return
        turn_path = _plain_turn_path_decision(trace.get("turn_path_decision"))
        if turn_path:
            self.turn_path_decision = turn_path
            path = _safe_token(turn_path.get("path"))
            reason = _safe_token(turn_path.get("reason"))
            if path:
                self.route_lane = path
            if reason and not self.route_reason:
                self.route_reason = reason

        tool_policy = _plain_tool_policy_session(trace.get("tool_policy_session"))
        if tool_policy:
            self.tool_policy_session = tool_policy
            visible = _safe_token_list(tool_policy.get("visible_tool_names"))
            if visible:
                self.observed_tools = list(dict.fromkeys([*self.observed_tools, *visible]))

        self.external_app_action_plan = _plain_external_app_action_plan(
            trace.get("external_app_action_plan")
        ) or self.external_app_action_plan
        self.external_app_integration_lane = _plain_external_app_integration_lane(
            trace.get("external_app_integration_lane")
        ) or self.external_app_integration_lane

        external_trace = trace.get("external_action_trace")
        if isinstance(external_trace, Mapping):
            self.external_action_trace = _safe_public_value(external_trace)
            if bool(external_trace.get("observed_action_result")):
                self.apply_attempted = True
            success = _safe_bool(external_trace.get("last_success"))
            if success is not None:
                self.host_action_result_received = True
                self.host_action_result_success = success
            last_status = _safe_token(external_trace.get("last_status"))
            if last_status and last_status not in self.host_action_result_statuses:
                self.host_action_result_statuses.append(last_status)

        subagents = _plain_subagent_boundary_trace(trace.get("subagents"))
        if subagents.get("report_count") or subagents.get("reports"):
            self.subagent_boundary_trace = subagents

        final_answer = _plain_final_answer_trace(
            trace.get("final_answer"),
            action_trace=self.external_action_trace,
        )
        if final_answer:
            self.final_answer_trace = final_answer

        denials = _tool_policy_denials_from_trace(trace)
        if denials:
            merged = [*self.tool_policy_denials, *denials]
            deduped: list[dict[str, Any]] = []
            seen: set[tuple[str, str, str]] = set()
            for item in merged:
                key = (
                    str(item.get("tool_name") or ""),
                    str(item.get("path") or ""),
                    str(item.get("reason") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            self.tool_policy_denials = deduped[-_MAX_SEQUENCE_ITEMS:]

    def to_payload(self) -> dict[str, Any]:
        self._refresh_suppressed_tools()
        return {
            "schema_version": RUNTIME_FLOW_LEDGER_SCHEMA_VERSION,
            "request": {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "user_id_hash": self.user_id_hash,
                "organization_id_hash": self.organization_id_hash,
                "domain_id": self.domain_id,
                "host_surface": self.host_surface,
                "host_capabilities": list(self.host_capabilities),
            },
            "context": {
                "document_context_present": self.document_context_present,
                "uploaded_document_count": self.uploaded_document_count,
                "source_ref_count": self.source_ref_count,
                "memory_context_count": self.memory_context_count,
                "history_context_count": self.history_context_count,
                "history_retrieval_status": self.history_retrieval_status,
                "history_source": self.history_source,
                "context_budget_utilization": self.context_budget_utilization,
                "context_budget_messages_dropped": self.context_budget_messages_dropped,
                "context_budget_status": self.context_budget_status,
                "context_provenance": self.context_provenance,
            },
            "route": {
                "lane": self.route_lane,
                "reason": self.route_reason,
                "selected_agent": self.selected_agent,
                "final_agent": self.final_agent,
                "turn_path_decision": dict(self.turn_path_decision),
            },
            "runtime": {
                "requested_provider": self.provider_requested,
                "requested_model": self.model_requested,
                "provider": self.provider,
                "model": self.model,
                "runtime_authoritative": self.runtime_authoritative,
                "fallback_used": self.fallback_used,
                "fallback_reason": self.fallback_reason,
                "failover_used": self.failover_used,
            },
            "tools": {
                "observed": list(self.observed_tools),
                "suppressed": list(self.suppressed_tools),
                "policy_session": dict(self.tool_policy_session),
                "policy_denials": list(self.tool_policy_denials),
            },
            "external_app": {
                "action_plan": dict(self.external_app_action_plan),
                "integration_lane": dict(self.external_app_integration_lane),
                "action_trace": dict(self.external_action_trace),
            },
            "subagents": dict(self.subagent_boundary_trace),
            "stream": {
                "transport": "sse_v3",
                "event_counts": dict(self.event_counts),
                "event_sequence_tail": list(self.event_sequence_tail),
                "metadata_seen": self.metadata_seen,
                "done_seen": self.done_seen,
            },
            "host_actions": {
                "preview_required": self.preview_required,
                "preview_emitted": self.preview_emitted,
                "approval_token_present": self.approval_token_present,
                "approval_token_hash": self.approval_token_hash,
                "apply_attempted": self.apply_attempted,
                "result_received": self.host_action_result_received,
                "result_success": self.host_action_result_success,
                "result_statuses": list(self.host_action_result_statuses),
                "mutation_blocked_reason": self.mutation_blocked_reason,
            },
            "finalization": {
                "status": self.finalization_status,
                "error_type": self.finalization_error_type,
                "save_response_immediately": self.save_response_immediately,
                "post_turn_lifecycle": self.post_turn_lifecycle,
            },
            "final_answer": dict(self.final_answer_trace),
        }

    def _refresh_suppressed_tools(self) -> None:
        suppressed: list[str] = []
        if (
            "host_action" not in self.host_capabilities
            and not self.event_counts.get("host_action")
            and not self.event_counts.get("host_action_result")
        ):
            suppressed.append("host_action")
        if "pointy" not in self.host_capabilities and not self.event_counts.get(
            "pointy_action"
        ):
            suppressed.append("pointy_action")
        if (
            self.route_lane != "visual_fast_path"
            and "visual_runtime" not in self.observed_tools
        ):
            suppressed.append("visual_runtime")
        if (
            "code_studio" not in self.host_capabilities
            and "code_studio" not in self.observed_tools
        ):
            suppressed.append("code_studio")
        self.suppressed_tools = suppressed


__all__ = [
    "RUNTIME_FLOW_LEDGER_SCHEMA_VERSION",
    "RUNTIME_FLOW_TRACE_VERSION",
    "RuntimeFlowLedger",
    "build_runtime_flow_trace_from_state",
    "sanitize_runtime_flow_trace",
]
