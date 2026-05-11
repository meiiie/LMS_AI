"""Sprint 222b Phase 5: Dynamic LangChain tool generation from host capabilities.

Generates StructuredTool instances from host-declared action definitions.
Each tool calls HostActionBridge.emit_action_request() when invoked.
"""
import json
import logging
import re
from typing import Any

from app.engine.tools.native_tool import StructuredTool

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


def host_action_tool_name(action_name: str) -> str:
    """Map dotted/slashed action names to OpenAI-safe tool names."""
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "__", action_name.strip())
    normalized = normalized.strip("_") or "host_action"
    return f"host_action__{normalized}"


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
                if definition.get("requires_confirmation") and definition.get("mutates_state"):
                    expected_preview_kind = _expected_preview_kind(name)
                    preview_token = str(params.get("preview_token") or "").strip()
                    if not preview_token and latest_preview:
                        latest_kind = str(latest_preview.get("preview_kind") or "").strip()
                        if not expected_preview_kind or latest_kind == expected_preview_kind:
                            preview_token = str(latest_preview.get("preview_token") or "").strip()
                            if preview_token:
                                params["preview_token"] = preview_token

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
        )
        tools.append(tool)

    return tools
