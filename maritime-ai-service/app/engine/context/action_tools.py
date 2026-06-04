"""Sprint 222b Phase 5: Dynamic LangChain tool generation from host capabilities.

Generates StructuredTool instances from host-declared action definitions.
Each tool calls HostActionBridge.emit_action_request() when invoked.
"""
import json
import logging
import re
from typing import Any

from pydantic import ConfigDict, Field, create_model

from app.engine.tools.native_tool import StructuredTool
from app.engine.tools.tool_capability_registry import (
    host_action_requires_approval_token,
    host_action_tool_name,
)

from app.engine.context.action_bridge import HostActionBridge

logger = logging.getLogger(__name__)

_EXPLICIT_CONFIRM_RE = re.compile(
    r"\b("
    r"dong y|đồng ý|xac nhan|xác nhận|ap dung|áp dụng|thuc hien|thực hiện|"
    r"trien khai|triển khai|tien hanh|tiến hành|cu lam|cứ làm|ok lam|oke lam|"
    r"confirm|confirmed|apply it|go ahead|proceed|publish it|ship it"
    r")\b",
    re.IGNORECASE,
)


def _query_explicitly_confirms(query: str) -> bool:
    normalized = " ".join(str(query or "").strip().lower().split())
    if not normalized:
        return False
    return bool(_EXPLICIT_CONFIRM_RE.search(normalized))


def _extract_latest_preview(approval_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(approval_context, dict):
        return None

    feedback = approval_context.get("host_action_feedback")
    if not isinstance(feedback, dict):
        return None

    last_result = feedback.get("last_action_result")
    if not isinstance(last_result, dict):
        return None

    data = last_result.get("data")
    if not isinstance(data, dict):
        return None

    preview_token = str(data.get("preview_token") or "").strip()
    if not preview_token:
        return None

    return {
        "preview_token": preview_token,
        "approval_token": str(data.get("approval_token") or "").strip(),
        "preview_kind": str(data.get("preview_kind") or "").strip(),
        "action": str(last_result.get("action") or "").strip(),
        "summary": str(last_result.get("summary") or "").strip(),
    }


def _expected_preview_kind(action_name: str) -> str | None:
    normalized = action_name.strip().lower()
    if normalized.endswith("apply_course_plan"):
        return "course_plan"
    if normalized.endswith("apply_lesson_patch"):
        return "lesson_patch"
    if normalized.endswith("apply_quiz_commit"):
        return "quiz_commit"
    if normalized.endswith("apply_quiz"):
        return "quiz_publish"
    return None


def _action_requires_approval_token(action_name: str) -> bool:
    return host_action_requires_approval_token(action_name)


def _latest_preview_matches(
    latest_preview: dict[str, Any] | None,
    expected_preview_kind: str | None,
) -> bool:
    if not latest_preview:
        return False
    latest_kind = str(latest_preview.get("preview_kind") or "").strip()
    return not expected_preview_kind or latest_kind == expected_preview_kind


def _populate_latest_preview_tokens(
    params: dict[str, Any],
    latest_preview: dict[str, Any] | None,
    expected_preview_kind: str | None,
) -> tuple[str, str]:
    preview_token = str(params.get("preview_token") or "").strip()
    approval_token = str(params.get("approval_token") or "").strip()

    if _latest_preview_matches(latest_preview, expected_preview_kind):
        if not preview_token:
            preview_token = str(latest_preview.get("preview_token") or "").strip()
            if preview_token:
                params["preview_token"] = preview_token
        if not approval_token:
            approval_token = str(latest_preview.get("approval_token") or "").strip()
            if approval_token:
                params["approval_token"] = approval_token

    return preview_token, approval_token


def _format_input_contract(action_name: str, action_def: dict[str, Any]) -> str:
    input_schema = action_def.get("input_schema")
    if not isinstance(input_schema, dict):
        return ""

    properties = input_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return ""

    fields = [str(name) for name in properties.keys() if str(name).strip()]
    if not fields:
        return ""

    lines = ["Input fields: " + ", ".join(fields[:12])]
    required = input_schema.get("required")
    if isinstance(required, list):
        required_fields = [str(name) for name in required if str(name).strip()]
        if required_fields:
            lines.append("Required: " + ", ".join(required_fields[:12]))

    if (
        action_name.strip().lower().endswith("preview_lesson_patch")
        and "source_references" in properties
    ):
        lines.append(
            "For document-derived lesson/course previews, include `source_references` "
            "from the uploaded source document so the teacher can verify citations."
        )
        lines.append(
            "When an uploaded Word/PDF/document is the source, build `content` from that "
            "document context and keep preview-only behavior; do not call an apply action."
        )

    if action_name.strip().lower().endswith("generate_course_from_document"):
        lines.append(
            "For uploaded Word/PDF/document course generation, include a structured "
            "`course_plan` with `chapters`, each chapter's `lessons`, and "
            "`source_references` so the teacher can verify citations."
        )
        lines.append(
            "This action is preview-first: do not call `authoring.apply_course_plan` "
            "unless the LMS has returned a matching preview_token and the user has "
            "explicitly confirmed apply."
        )

    return "\n" + "\n".join(lines)


def _annotation_for_json_schema(schema: dict[str, Any]) -> Any:
    schema_type = str(schema.get("type") or "").strip().lower()
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[Any]
    if schema_type == "object":
        return dict[str, Any]
    return str


def _build_action_args_schema(action_name: str, action_def: dict[str, Any]):
    input_schema = action_def.get("input_schema")
    if not isinstance(input_schema, dict):
        return None
    properties = input_schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return None

    required = {
        str(name).strip()
        for name in input_schema.get("required", [])
        if str(name).strip()
    }
    fields: dict[str, tuple[Any, Any]] = {}
    for raw_name, raw_schema in properties.items():
        field_name = str(raw_name).strip()
        if not field_name:
            continue
        schema = raw_schema if isinstance(raw_schema, dict) else {}
        annotation = _annotation_for_json_schema(schema)
        description = str(schema.get("description") or "").strip() or None
        default = ... if field_name in required else schema.get("default", None)
        fields[field_name] = (
            annotation,
            Field(default, description=description),
        )
    if not fields:
        return None

    model_name = re.sub(r"[^a-zA-Z0-9]+", " ", action_name).title().replace(" ", "")
    model_name = f"{model_name or 'HostAction'}Input"
    return create_model(
        model_name,
        __config__=ConfigDict(extra="allow"),
        **fields,
    )


def _missing_required_action_fields(
    definition: dict[str, Any],
    params: dict[str, Any],
) -> list[str]:
    input_schema = definition.get("input_schema")
    if not isinstance(input_schema, dict):
        return []
    required = input_schema.get("required")
    if not isinstance(required, list):
        return []

    missing: list[str] = []
    for raw_name in required:
        name = str(raw_name or "").strip()
        if not name:
            continue
        value = params.get(name)
        if value is None:
            missing.append(name)
        elif isinstance(value, str) and not value.strip():
            missing.append(name)
    return missing


def generate_host_action_tools(
    capabilities_tools: list[dict[str, Any]],
    user_role: str,
    event_bus_id: str,
    approval_context: dict[str, Any] | None = None,
) -> list[StructuredTool]:
    """Generate LangChain tools from host-declared action definitions.

    Filters by user role. Only creates tools the user is allowed to execute.
    Tools call HostActionBridge.emit_action_request() when invoked.
    """
    bridge = HostActionBridge(capabilities_tools=capabilities_tools)
    available = bridge.get_available_actions(user_role)
    explicit_confirmation = _query_explicitly_confirms(str((approval_context or {}).get("query") or ""))
    latest_preview = _extract_latest_preview(approval_context)

    tools: list[StructuredTool] = []
    for action_def in available:
        action_name = action_def["name"]
        description = action_def.get("description", f"Execute {action_name} on host")
        input_contract = _format_input_contract(action_name, action_def)

        def _make_tool_fn(name: str, br: HostActionBridge, bus_id: str, definition: dict[str, Any]):
            def tool_fn(**kwargs: Any) -> str:
                params = dict(kwargs)
                expected_preview_kind = _expected_preview_kind(name)
                preview_token, approval_token = _populate_latest_preview_tokens(
                    params,
                    latest_preview,
                    expected_preview_kind,
                )
                missing_required_fields = _missing_required_action_fields(
                    definition,
                    params,
                )
                if missing_required_fields:
                    return json.dumps({
                        "status": "validation_failed",
                        "action": name,
                        "params": params,
                        "message": "Missing required host-action input.",
                        "missing_fields": missing_required_fields,
                    }, ensure_ascii=False)

                declared_mutation = bool(
                    definition.get("requires_confirmation") and definition.get("mutates_state")
                )
                requires_lms_approval_token = _action_requires_approval_token(name)

                if declared_mutation or requires_lms_approval_token:
                    if not explicit_confirmation:
                        return json.dumps({
                            "status": "approval_required",
                            "action": name,
                            "params": params,
                            "message": "Explicit confirmation required before mutating host state.",
                        }, ensure_ascii=False)

                    if expected_preview_kind and not preview_token:
                        return json.dumps({
                            "status": "preview_required",
                            "action": name,
                            "params": params,
                            "message": "A matching preview must exist before apply/publish can run.",
                            "expected_preview_kind": expected_preview_kind,
                        }, ensure_ascii=False)

                if requires_lms_approval_token and not approval_token:
                    return json.dumps({
                        "status": "approval_token_required",
                        "action": name,
                        "params": params,
                        "message": "A host-issued approval_token is required before LMS authoring apply can run.",
                        "expected_preview_kind": expected_preview_kind,
                    }, ensure_ascii=False)

                request_id = br.emit_action_request(name, params, bus_id)
                return json.dumps({
                    "status": "action_requested",
                    "request_id": request_id,
                    "action": name,
                    "params": params,
                }, ensure_ascii=False)
            return tool_fn

        tool = StructuredTool.from_function(
            func=_make_tool_fn(action_name, bridge, event_bus_id, action_def),
            name=host_action_tool_name(action_name),
            description=f"[Host Action: {action_name}] {description}{input_contract}",
            args_schema=_build_action_args_schema(action_name, action_def),
        )
        tools.append(tool)

    return tools
