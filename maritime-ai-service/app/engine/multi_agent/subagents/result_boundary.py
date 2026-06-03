"""Parent-safe result projection for subagent executor returns."""

from __future__ import annotations

from typing import Any

from app.engine.multi_agent.subagents.result import SubagentResult
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)


SUBAGENT_RESULT_BOUNDARY_SCHEMA_VERSION = "wiii.subagent_result_boundary.v1"
_MAX_RESULT_TEXT = 4000
_MAX_ERROR_TEXT = 500
_MAX_PUBLIC_ITEMS = 16
_SAFE_SOURCE_KEYS = {
    "id",
    "node_id",
    "source_id",
    "title",
    "source",
    "source_type",
    "content_type",
    "page",
    "page_number",
    "document_id",
    "image_url",
    "url",
    "relevance_score",
    "score",
    "bounding_boxes",
}
_SAFE_TOOL_KEYS = {
    "name",
    "status",
    "duration_ms",
    "tool",
    "tool_name",
    "provider",
    "source",
    "error_type",
}
_SAFE_EVIDENCE_KEYS = {
    "url",
    "image_url",
    "page",
    "page_number",
    "document_id",
    "content_type",
    "source",
}


def _safe_text(value: Any, *, max_length: int = _MAX_RESULT_TEXT) -> str:
    text = redact_runtime_secret_text(str(value or ""))
    if len(text) > max_length:
        return text[: max_length - 1] + "..."
    return text


def _safe_mapping_list(values: Any, *, allowed_keys: set[str]) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    safe_values: list[dict[str, Any]] = []
    for raw_item in values[:_MAX_PUBLIC_ITEMS]:
        safe_item = sanitize_runtime_payload(raw_item)
        if not isinstance(safe_item, dict):
            continue
        item = {
            str(key): value
            for key, value in safe_item.items()
            if str(key) in allowed_keys and value not in (None, "", [], {})
        }
        if item:
            safe_values.append(item)
    return safe_values


def _sanitize_dict_payload(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value)
    if not isinstance(safe_value, dict):
        return {}
    return _drop_internal_redaction_counts(safe_value)


def _sanitize_list_payload(value: Any) -> list[Any]:
    safe_value = sanitize_runtime_payload(value)
    if not isinstance(safe_value, list):
        return []
    cleaned = _drop_internal_redaction_counts(safe_value)
    return cleaned if isinstance(cleaned, list) else []


def _drop_internal_redaction_counts(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _drop_internal_redaction_counts(item)
            for key, item in value.items()
            if str(key) != "redacted_secret_count"
        }
    if isinstance(value, list):
        return [_drop_internal_redaction_counts(item) for item in value]
    return value


def _payload_from_result(value: Any) -> dict[str, Any]:
    if isinstance(value, SubagentResult):
        return value.model_dump()
    return {}


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _safe_data_keys(value: Any) -> list[str]:
    safe_value = sanitize_runtime_payload(value)
    if not isinstance(safe_value, dict):
        return []
    return sorted(
        str(key)
        for key in safe_value.keys()
        if str(key) != "redacted_secret_count"
    )[:_MAX_PUBLIC_ITEMS]


def build_subagent_result_boundary_summary(
    raw_result: SubagentResult,
    sanitized_result: SubagentResult,
) -> dict[str, Any]:
    """Build count-only evidence for child-to-parent result projection."""

    raw_payload = _payload_from_result(raw_result)
    safe_payload = _payload_from_result(sanitized_result)
    raw_output_chars = len(str(raw_payload.get("output") or ""))
    safe_output_chars = len(str(safe_payload.get("output") or ""))
    raw_error_chars = len(str(raw_payload.get("error_message") or ""))
    safe_error_chars = len(str(safe_payload.get("error_message") or ""))
    warning_codes: list[str] = []
    if raw_output_chars > safe_output_chars or raw_output_chars > _MAX_RESULT_TEXT:
        warning_codes.append("subagent_output_sanitized_or_truncated")
    if bool(raw_payload.get("thinking")):
        warning_codes.append("subagent_thinking_dropped")
    if raw_error_chars > safe_error_chars or raw_error_chars > _MAX_ERROR_TEXT:
        warning_codes.append("subagent_error_sanitized_or_truncated")
    for key, warning in (
        ("sources", "subagent_sources_filtered"),
        ("tools_used", "subagent_tools_filtered"),
        ("evidence_images", "subagent_evidence_images_filtered"),
    ):
        if _list_count(raw_payload.get(key)) > _list_count(safe_payload.get(key)):
            warning_codes.append(warning)

    return {
        "schema_version": SUBAGENT_RESULT_BOUNDARY_SCHEMA_VERSION,
        "status": str(
            getattr(sanitized_result.status, "value", sanitized_result.status)
        ),
        "raw_output_char_count": raw_output_chars,
        "output_char_count": safe_output_chars,
        "raw_error_char_count": raw_error_chars,
        "error_char_count": safe_error_chars,
        "data_key_count": len(_safe_data_keys(sanitized_result.data)),
        "data_keys": _safe_data_keys(sanitized_result.data),
        "source_count": _list_count(sanitized_result.sources),
        "tool_count": _list_count(sanitized_result.tools_used),
        "evidence_image_count": _list_count(sanitized_result.evidence_images),
        "thinking_dropped": bool(raw_payload.get("thinking")),
        "raw_content_included": False,
        "warning_codes": sorted(set(warning_codes)),
    }


def sanitize_subagent_result_for_executor(result: SubagentResult) -> SubagentResult:
    """Return a child result safe to hand back to parent orchestration."""

    payload = result.model_dump()
    safe_payload = sanitize_runtime_payload(payload)
    if not isinstance(safe_payload, dict):
        safe_payload = {}

    safe_payload.update(
        {
            "status": result.status,
            "confidence": result.confidence,
            "output": _safe_text(result.output),
            "data": _sanitize_dict_payload(result.data),
            "sources": _safe_mapping_list(
                result.sources,
                allowed_keys=_SAFE_SOURCE_KEYS,
            ),
            "tools_used": _safe_mapping_list(
                result.tools_used,
                allowed_keys=_SAFE_TOOL_KEYS,
            ),
            "evidence_images": _safe_mapping_list(
                result.evidence_images,
                allowed_keys=_SAFE_EVIDENCE_KEYS,
            ),
            "boundary": _sanitize_dict_payload(getattr(result, "boundary", {})),
            "thinking": None,
            "error_message": (
                _safe_text(result.error_message, max_length=_MAX_ERROR_TEXT)
                if result.error_message
                else None
            ),
            "duration_ms": result.duration_ms,
        }
    )

    if "documents" in payload:
        safe_payload["documents"] = _safe_mapping_list(
            getattr(result, "documents", []),
            allowed_keys=_SAFE_SOURCE_KEYS,
        )
    if "products" in payload:
        safe_payload["products"] = _sanitize_list_payload(
            getattr(result, "products", [])
        )
    if "excel_path" in payload and getattr(result, "excel_path", None):
        safe_payload["excel_path"] = _safe_text(
            getattr(result, "excel_path"),
            max_length=240,
        )

    try:
        return type(result)(**safe_payload)
    except Exception:
        return SubagentResult(
            status=result.status,
            confidence=result.confidence,
            output=safe_payload.get("output") or "",
            data=safe_payload.get("data") or {},
            sources=safe_payload.get("sources") or [],
            tools_used=safe_payload.get("tools_used") or [],
            evidence_images=safe_payload.get("evidence_images") or [],
            boundary=safe_payload.get("boundary") or {},
            thinking=None,
            error_message=safe_payload.get("error_message"),
            duration_ms=result.duration_ms,
        )


__all__ = [
    "SUBAGENT_RESULT_BOUNDARY_SCHEMA_VERSION",
    "build_subagent_result_boundary_summary",
    "sanitize_subagent_result_for_executor",
]
