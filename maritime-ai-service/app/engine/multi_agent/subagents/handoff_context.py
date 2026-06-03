"""Bounded parent context inherited by child subagents."""

from __future__ import annotations

from typing import Any, Mapping

from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text


SUBAGENT_HANDOFF_BOUNDARY_SCHEMA_VERSION = "wiii.subagent_handoff_boundary.v1"
_MAX_SUBAGENT_STATE_DEPTH = 8
_MAX_SUBAGENT_STATE_ITEMS = 64
_MAX_SUBAGENT_STATE_STRING = 4000
_MAX_BOUNDARY_KEYS = 24
_ALLOWED_TOP_LEVEL_RUNTIME_KEYS = {
    "_event_bus_id",
    "_trace_id",
}
_BLOCKED_TOP_LEVEL_SUBAGENT_KEYS = {
    "_aggregator_action",
    "_aggregator_reasoning",
    "_agentic_continue",
    "_answer_streamed_via_bus",
    "_external_app_action_plan",
    "_external_app_integration_lane",
    "_handoff_count",
    "_handoff_target",
    "_host_action_control_feedback",
    "_orchestrator_turn",
    "_parallel_targets",
    "_public_thinking_fragments",
    "_reroute_count",
    "_runner_error",
    "_runner_error_node",
    "_self_correction_retry",
    "_thinking_history",
    "_thinking_trajectory",
    "_tool_policy_session",
    "_turn_path_decision",
    "agent_outputs",
    "current_agent",
    "domain_notice",
    "evidence_images",
    "final_response",
    "grader_feedback",
    "grader_score",
    "host_action_control_feedback",
    "host_action_feedback",
    "memory_output",
    "next_agent",
    "rag_output",
    "reasoning_trace",
    "routing_metadata",
    "runtime_flow_ledger",
    "runtime_flow_trace",
    "sources",
    "subagent_reports",
    "thinking",
    "thinking_content",
    "thinking_effort",
    "thinking_lifecycle",
    "tool_call_events",
    "tools_used",
    "tutor_output",
}
_SENSITIVE_SUBAGENT_KEY_MARKERS = (
    "access_token",
    "ak_secret",
    "api_key",
    "apikey",
    "approval_token",
    "authorization",
    "bearer",
    "client_secret",
    "connection_id",
    "connection_ref",
    "cookie",
    "credential",
    "external_account_ref",
    "image_base64",
    "page_id",
    "password",
    "private_key",
    "provider_payload",
    "raw_provider",
    "refresh_token",
    "secret",
    "token",
    "vault_ref",
)
_CONTROL_KEYS = {"__proto__", "constructor", "prototype"}
_REDACTED_SECRET_MARKER = "<redacted-secret>"


def _normalize_state_key(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(".", "_")


def _is_sensitive_subagent_key(key: str) -> bool:
    normalized = _normalize_state_key(key)
    return any(marker in normalized for marker in _SENSITIVE_SUBAGENT_KEY_MARKERS)


def _sanitize_inherited_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_SUBAGENT_STATE_DEPTH:
        return "<truncated>"
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif hasattr(value, "dict"):
        value = value.dict()
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_item in list(value.items())[:_MAX_SUBAGENT_STATE_ITEMS]:
            key = str(raw_key)
            normalized = _normalize_state_key(key)
            if (
                not normalized
                or normalized in _CONTROL_KEYS
                or normalized in _BLOCKED_TOP_LEVEL_SUBAGENT_KEYS
                or _is_sensitive_subagent_key(key)
            ):
                continue
            cleaned_item = _sanitize_inherited_value(raw_item, depth=depth + 1)
            if cleaned_item not in (None, {}, []):
                cleaned[key] = cleaned_item
        return cleaned
    if isinstance(value, list):
        return [
            _sanitize_inherited_value(item, depth=depth + 1)
            for item in value[:_MAX_SUBAGENT_STATE_ITEMS]
        ]
    if isinstance(value, str):
        return redact_runtime_secret_text(value[:_MAX_SUBAGENT_STATE_STRING])
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_runtime_secret_text(str(value)[:_MAX_SUBAGENT_STATE_STRING])


def _safe_boundary_key(value: object) -> str:
    token = redact_runtime_secret_text(str(value or "").strip())
    return " ".join(token.split())[:96]


def _safe_boundary_keys(value: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    for raw_key in value.keys():
        key = _safe_boundary_key(raw_key)
        if key:
            keys.append(key)
    return sorted(keys)[:_MAX_BOUNDARY_KEYS]


def _redacted_secret_count(value: Any, *, depth: int = 0) -> int:
    if depth > _MAX_SUBAGENT_STATE_DEPTH:
        return 0
    if isinstance(value, Mapping):
        return sum(
            _redacted_secret_count(item, depth=depth + 1)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return sum(
            _redacted_secret_count(item, depth=depth + 1)
            for item in value[:_MAX_SUBAGENT_STATE_ITEMS]
        )
    if isinstance(value, str) and _REDACTED_SECRET_MARKER in value:
        return value.count(_REDACTED_SECRET_MARKER)
    return 0


def _projection_summary(
    *,
    source: str,
    original: Mapping[str, Any],
    projected: Mapping[str, Any],
) -> dict[str, Any]:
    original_key_count = len(original)
    projected_key_count = len(projected)
    dropped_key_count = max(0, original_key_count - projected_key_count)
    redacted_count = _redacted_secret_count(projected)
    warning_codes: list[str] = []
    if dropped_key_count > 0:
        warning_codes.append(f"{source}_top_level_keys_dropped")
    if redacted_count > 0:
        warning_codes.append(f"{source}_secret_text_redacted")
    return {
        "source": source,
        "original_key_count": original_key_count,
        "projected_key_count": projected_key_count,
        "dropped_key_count": dropped_key_count,
        "projected_keys": _safe_boundary_keys(projected),
        "redacted_secret_count": redacted_count,
        "raw_content_included": False,
        "warning_codes": warning_codes,
    }


def project_state_for_subagent(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return a safe child-state view for parent-to-subagent handoffs."""

    projected: dict[str, Any] = {}
    for raw_key, raw_value in state.items():
        key = str(raw_key)
        normalized = _normalize_state_key(key)
        if normalized in _BLOCKED_TOP_LEVEL_SUBAGENT_KEYS:
            continue
        if key.startswith("_") and key not in _ALLOWED_TOP_LEVEL_RUNTIME_KEYS:
            continue
        if _is_sensitive_subagent_key(key):
            continue
        projected_value = _sanitize_inherited_value(raw_value)
        if projected_value not in (None, {}, []):
            projected[key] = projected_value
    return projected


def project_kwargs_for_subagent(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Return safe keyword arguments for parent-to-subagent calls."""

    projected: dict[str, Any] = {}
    for raw_key, raw_value in kwargs.items():
        key = str(raw_key)
        normalized = _normalize_state_key(key)
        if (
            not normalized
            or key.startswith("_")
            or normalized in _CONTROL_KEYS
            or normalized in _BLOCKED_TOP_LEVEL_SUBAGENT_KEYS
            or _is_sensitive_subagent_key(key)
        ):
            continue
        projected_value = _sanitize_inherited_value(raw_value)
        if projected_value not in (None, {}, []):
            projected[key] = projected_value
    return projected


def build_subagent_handoff_boundary_summary(
    *,
    parent_state: Mapping[str, Any],
    child_state: Mapping[str, Any],
    parent_kwargs: Mapping[str, Any] | None = None,
    child_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build count-only evidence for parent-to-child context projection."""

    kwargs = parent_kwargs or {}
    projected_kwargs = child_kwargs or {}
    state_summary = _projection_summary(
        source="state",
        original=parent_state,
        projected=child_state,
    )
    kwargs_summary = _projection_summary(
        source="kwargs",
        original=kwargs,
        projected=projected_kwargs,
    )
    warning_codes = sorted(
        {
            *state_summary["warning_codes"],
            *kwargs_summary["warning_codes"],
        }
    )
    return {
        "schema_version": SUBAGENT_HANDOFF_BOUNDARY_SCHEMA_VERSION,
        "state": state_summary,
        "kwargs": kwargs_summary,
        "raw_content_included": False,
        "warning_codes": warning_codes,
    }


__all__ = [
    "SUBAGENT_HANDOFF_BOUNDARY_SCHEMA_VERSION",
    "build_subagent_handoff_boundary_summary",
    "project_kwargs_for_subagent",
    "project_state_for_subagent",
]
