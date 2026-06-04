"""
HostContext & HostCapabilities -- generic host application context models.
Sprint 222: Universal Context Engine.
Sprint 234: Operator Platform V1.
MCP-compatible schema: Resources (context) + Tools (actions).
"""
import json
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

MAX_SNIPPET_LENGTH = 2000


def _normalize_action_name(action: dict[str, Any]) -> str:
    return str(action.get("name") or action.get("action") or "").strip()


class HostActionDefinition(BaseModel):
    """Action contract declared by the host application."""

    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None
    roles: Optional[list[str]] = None
    permission: Optional[str] = None
    required_permissions: Optional[list[str]] = None
    requires_confirmation: bool = False
    mutates_state: bool = False
    surface: Optional[str] = None
    result_schema: Optional[dict[str, Any]] = None


class OperatorSessionV1(BaseModel):
    """Internal operator framing for host-aware turns."""

    goal: str
    current_plan: str
    candidate_actions: list[str] = Field(default_factory=list)
    pending_approval: bool = False
    last_host_result: Optional[str] = None
    next_best_step: str


class HostSessionV1(BaseModel):
    """Runtime host-session overlay for the current turn."""

    host_type: str
    host_name: Optional[str] = None
    connector_id: Optional[str] = None
    host_workspace_id: Optional[str] = None
    host_organization_id: Optional[str] = None
    host_role: Optional[str] = None
    page_type: str
    page_title: Optional[str] = None
    workflow_stage: Optional[str] = None
    capability_surfaces: list[str] = Field(default_factory=list)
    available_action_names: list[str] = Field(default_factory=list)
    selection_label: Optional[str] = None
    editable_scope_type: Optional[str] = None
    resource_uri: Optional[str] = None
    external_connection_summaries: list[str] = Field(default_factory=list)


class HostContext(BaseModel):
    """Generic context from any host application."""
    host_type: str = Field(..., description="Host app type: lms | ecommerce | trading | crm | custom")
    host_name: Optional[str] = Field(default=None, description="Human-readable host name")
    connector_id: Optional[str] = Field(default=None, description="Durable connector/workspace identifier")
    host_user_id: Optional[str] = Field(default=None, description="User identifier inside the host system")
    host_workspace_id: Optional[str] = Field(default=None, description="Workspace/site identifier inside the host")
    host_organization_id: Optional[str] = Field(default=None, description="Organization identifier inside the host")
    resource_uri: str = Field(default="host://current-page", description="MCP Resource URI")
    page: dict[str, Any] = Field(..., description="Current page: {type, title?, url?, metadata?}")
    user_role: Optional[str] = Field(default=None, description="Role inside host app: student | teacher | admin")
    workflow_stage: Optional[str] = Field(default=None, description="Host workflow stage: learning | authoring | assessment | analytics | governance")
    selection: Optional[dict[str, Any]] = Field(default=None, description="Current host selection")
    editable_scope: Optional[dict[str, Any]] = Field(default=None, description="Structured scope Wiii is allowed to edit")
    entity_refs: Optional[list[dict[str, Any]]] = Field(default=None, description="Entities referenced on this page")
    user_state: Optional[dict[str, Any]] = Field(default=None, description="User interaction state")
    content: Optional[dict[str, Any]] = Field(default=None, description="Content: {snippet?, structured?}")
    available_actions: Optional[list[dict[str, Any]]] = Field(default=None, description="Host-declared actions")

    @field_validator("content", mode="before")
    @classmethod
    def truncate_snippet(cls, v):
        if v and isinstance(v, dict) and "snippet" in v:
            snippet = v.get("snippet")
            if snippet and len(snippet) > MAX_SNIPPET_LENGTH:
                v = {**v, "snippet": snippet[:MAX_SNIPPET_LENGTH]}
        return v


class HostCapabilities(BaseModel):
    """Capability declaration from host app (sent once on iframe load)."""
    host_type: str
    host_name: Optional[str] = None
    connector_id: Optional[str] = None
    host_workspace_id: Optional[str] = None
    host_organization_id: Optional[str] = None
    version: str = "1"
    resources: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)


def from_legacy_page_context(
    page_context: dict,
    student_state=None,
    available_actions=None,
) -> HostContext:
    """Convert Sprint 221 PageContext dict to HostContext (backward compat)."""
    page_type = page_context.get("page_type", "unknown")
    page_title = page_context.get("page_title")

    metadata = {}
    for key in (
        "course_id",
        "course_name",
        "lesson_id",
        "lesson_name",
        "chapter_name",
        "content_type",
        "quiz_question",
        "quiz_options",
        "assignment_description",
        "action",
        "workflow_stage",
    ):
        val = page_context.get(key)
        if val is not None:
            metadata[key] = val

    for key, val in page_context.items():
        if key in {"page_type", "page_title", "content_snippet"} or key in metadata:
            continue
        if val is not None:
            metadata[key] = val

    page = {"type": page_type, "title": page_title, "metadata": metadata}

    content = None
    snippet = page_context.get("content_snippet")
    structured = page_context.get("structured")
    if snippet:
        content = {"snippet": snippet}
    if structured is not None:
        content = {**(content or {}), "structured": structured}

    selection = page_context.get("selection")
    editable_scope = page_context.get("editable_scope")
    entity_refs = page_context.get("entity_refs")
    user_role = page_context.get("user_role")
    workflow_stage = page_context.get("workflow_stage") or metadata.get("workflow_stage")

    user_state_dict = None
    if student_state:
        if isinstance(student_state, dict):
            user_state_dict = student_state
        elif hasattr(student_state, "model_dump"):
            user_state_dict = student_state.model_dump(exclude_none=True)
        else:
            user_state_dict = dict(student_state)

    actions_list = None
    if available_actions:
        actions_list = [
            a if isinstance(a, dict) else a.model_dump() if hasattr(a, "model_dump") else dict(a)
            for a in available_actions
        ]

    return HostContext(
        host_type="lms",
        connector_id=page_context.get("connector_id"),
        host_user_id=page_context.get("host_user_id"),
        host_workspace_id=page_context.get("host_workspace_id"),
        host_organization_id=page_context.get("host_organization_id"),
        page=page,
        user_role=str(user_role).strip() if user_role else None,
        workflow_stage=str(workflow_stage).strip() if workflow_stage else None,
        selection=selection if isinstance(selection, dict) else None,
        editable_scope=editable_scope if isinstance(editable_scope, dict) else None,
        entity_refs=entity_refs if isinstance(entity_refs, list) else None,
        user_state=user_state_dict,
        content=content,
        available_actions=actions_list,
    )


def _summarize_action(action: dict[str, Any]) -> str:
    action_name = _normalize_action_name(action)
    label = str(action.get("label") or action.get("title") or action_name).strip()
    roles = action.get("roles") or []
    surface = str(action.get("surface") or "").strip()
    mutates_state = bool(action.get("mutates_state"))
    requires_confirmation = bool(action.get("requires_confirmation"))

    suffix_parts: list[str] = []
    if roles:
        suffix_parts.append("roles=" + "/".join(str(role) for role in roles))
    if surface:
        suffix_parts.append(f"surface={surface}")
    if mutates_state:
        suffix_parts.append("write")
    else:
        suffix_parts.append("read")
    if requires_confirmation:
        suffix_parts.append("confirm")

    suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
    return f"- {label}: `{action_name}`{suffix}"


def format_host_capabilities_for_prompt(
    caps: HostCapabilities | dict[str, Any] | None,
    *,
    user_role: Optional[str] = None,
) -> str:
    """Format host capabilities into a compact prompt block."""
    if not caps:
        return ""

    capabilities = caps if isinstance(caps, HostCapabilities) else HostCapabilities(**caps)
    role = str(user_role or "").strip()
    lines = ["## Host Capabilities"]
    if capabilities.host_name:
        lines.append(f"- Host: {capabilities.host_name}")
    if capabilities.connector_id:
        lines.append(f"- Connector: {capabilities.connector_id}")
    if capabilities.host_workspace_id:
        lines.append(f"- Workspace: {capabilities.host_workspace_id}")
    if capabilities.host_organization_id:
        lines.append(f"- Host organization: {capabilities.host_organization_id}")
    if capabilities.resources:
        lines.append("- Resources: " + ", ".join(capabilities.resources))
    if capabilities.surfaces:
        lines.append("- Surfaces: " + ", ".join(capabilities.surfaces))

    if capabilities.tools:
        visible_tools = []
        for raw_tool in capabilities.tools:
            tool = raw_tool if isinstance(raw_tool, dict) else raw_tool.model_dump()
            roles = tool.get("roles")
            if roles and role and role not in roles:
                continue
            visible_tools.append(tool)
        if visible_tools:
            lines.append("### Actions")
            lines.extend(_summarize_action(tool) for tool in visible_tools[:10])
    return "\n".join(lines)


def build_operator_session_v1(
    *,
    query: str,
    host_context: HostContext | dict[str, Any],
    host_capabilities: HostCapabilities | dict[str, Any] | None = None,
    last_host_result: Optional[str] = None,
    host_action_feedback: Optional[dict[str, Any]] = None,
) -> OperatorSessionV1:
    """Build a light operator-session contract from host context."""
    ctx = host_context if isinstance(host_context, HostContext) else HostContext(**host_context)
    capabilities = None
    if host_capabilities:
        capabilities = (
            host_capabilities if isinstance(host_capabilities, HostCapabilities) else HostCapabilities(**host_capabilities)
        )

    page = ctx.page if isinstance(ctx.page, dict) else {}
    page_type = str(page.get("type") or "unknown")
    page_title = str(page.get("title") or page_type)
    workflow_stage = str(ctx.workflow_stage or page.get("metadata", {}).get("workflow_stage") or "general")

    candidate_actions: list[str] = []
    if capabilities and capabilities.tools:
        for raw_tool in capabilities.tools:
            tool = raw_tool if isinstance(raw_tool, dict) else raw_tool.model_dump()
            roles = tool.get("roles")
            if roles and ctx.user_role and ctx.user_role not in roles:
                continue
            name = _normalize_action_name(tool)
            if name and name not in candidate_actions:
                candidate_actions.append(name)
    elif ctx.available_actions:
        for action in ctx.available_actions:
            if not isinstance(action, dict):
                continue
            name = _normalize_action_name(action)
            if name and name not in candidate_actions:
                candidate_actions.append(name)

    if workflow_stage == "authoring":
        current_plan = f"Đang ở workflow authoring trên `{page_title}`; ưu tiên action host thay vì chỉ mô tả."
        next_best_step = "Đề xuất action authoring phù hợp hoặc mở preview trước khi commit."
    elif workflow_stage == "assessment":
        current_plan = f"Đang ở workflow assessment trên `{page_title}`; phải giữ an toàn sư phạm và đúng vai trò."
        next_best_step = "Chỉ dùng action host khi nó giúp review/tạo practice an toàn, không lộ đáp án."
    elif workflow_stage == "governance":
        current_plan = f"Đang ở workflow governance trên `{page_title}`; ưu tiên audit, policy, và xác nhận rõ."
        next_best_step = "Giữ câu trả lời ngắn, rõ, và chỉ đề xuất action có thể kiểm soát."
    else:
        current_plan = f"Đang làm việc trên `{page_title}` trong host `{ctx.host_type}`; ưu tiên bám trang hiện tại."
        next_best_step = "Chọn bước tiếp theo vừa đúng vai trò vừa tận dụng được capability của host."

    pending_approval = False
    editable_scope = ctx.editable_scope or {}
    if editable_scope.get("requires_confirmation"):
        pending_approval = True

    last_result = host_action_feedback.get("last_action_result") if isinstance(host_action_feedback, dict) else None
    if isinstance(last_result, dict):
        data = last_result.get("data")
        if isinstance(data, dict):
            preview_available = bool(data.get("preview_available")) or bool(
                str(data.get("preview_token") or "").strip()
            )
            preview_kind = str(data.get("preview_kind") or "").strip()
            if preview_available:
                pending_approval = True
                follow_up_action = {
                    "lesson_patch": "authoring.apply_lesson_patch",
                    "quiz_commit": "assessment.apply_quiz_commit",
                    "quiz_publish": "publish.apply_quiz",
                }.get(preview_kind, "matching apply/publish action")
                next_best_step = (
                    f"Nếu người dùng xác nhận rõ, gọi `{follow_up_action}` cho preview hiện tại; "
                    "nếu chưa chắc, tiếp tục giải thích preview thay vì áp dụng ngay."
                )

    return OperatorSessionV1(
        goal=query.strip() or f"Hỗ trợ trên trang {page_title}",
        current_plan=current_plan,
        candidate_actions=candidate_actions[:10],
        pending_approval=pending_approval,
        last_host_result=last_host_result,
        next_best_step=next_best_step,
    )


def format_operator_session_for_prompt(session: OperatorSessionV1 | dict[str, Any]) -> str:
    """Format operator session into a prompt block."""
    operator_session = session if isinstance(session, OperatorSessionV1) else OperatorSessionV1(**session)
    lines = [
        "## Operator Session V1",
        f"- Goal: {operator_session.goal}",
        f"- Current plan: {operator_session.current_plan}",
        "- Identity boundary: Host/plugin context only shapes what Wiii should notice and what actions are available on this turn. Keep Wiii's own living identity, story, and tone intact; do not become the website itself.",
    ]
    if operator_session.candidate_actions:
        lines.append("- Candidate actions: " + ", ".join(operator_session.candidate_actions))
    lines.append(
        "- Approval: "
        + ("mutating/publish/admin actions must be previewed and explicitly confirmed" if operator_session.pending_approval
           else "read actions can run immediately; write/publish/admin actions still require explicit confirmation")
    )
    if operator_session.last_host_result:
        lines.append(f"- Last host result: {operator_session.last_host_result}")
    lines.append(f"- Next best step: {operator_session.next_best_step}")
    return "\n".join(lines)


def _extract_action_names(
    host_context: HostContext,
    host_capabilities: HostCapabilities | None,
) -> list[str]:
    names: list[str] = []

    for raw_tool in (host_capabilities.tools if host_capabilities else []):
        tool = raw_tool if isinstance(raw_tool, dict) else raw_tool.model_dump(exclude_none=True)
        name = _normalize_action_name(tool)
        if name and name not in names:
            names.append(name)

    if not names:
        for raw_action in host_context.available_actions or []:
            if not isinstance(raw_action, dict):
                continue
            name = _normalize_action_name(raw_action)
            if name and name not in names:
                names.append(name)

    return names


def _summarize_selection(selection: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(selection, dict):
        return None
    for key in ("label", "title", "name", "text", "id"):
        value = selection.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_scope_type(editable_scope: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(editable_scope, dict):
        return None
    for key in ("type", "kind", "scope_type", "resource_type"):
        value = editable_scope.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_external_connection_summaries(page_metadata: dict[str, Any]) -> list[str]:
    raw = page_metadata.get("wiii_connect")
    if not isinstance(raw, dict):
        return []

    summaries: list[str] = []
    providers = raw.get("providers")
    if isinstance(providers, list):
        provider_items = [item for item in providers if isinstance(item, dict)]
    else:
        provider_items = [raw]

    for provider in provider_items[:5]:
        slug = str(provider.get("provider_slug") or provider.get("slug") or "").strip()
        label = str(provider.get("provider_label") or provider.get("label") or slug or "provider").strip()
        status = str(provider.get("status") or "unknown").strip()
        active_count = provider.get("active_connection_count")
        page_count = provider.get("page_count")
        page_names = provider.get("page_names")
        actions = provider.get("available_actions")

        parts = [f"{label}: {status}"]
        if isinstance(active_count, int):
            parts.append(f"{active_count} active account(s)")
        if isinstance(page_count, int):
            page_part = f"{page_count} page(s)"
            if isinstance(page_names, list) and page_names:
                names = [str(name) for name in page_names[:3] if str(name).strip()]
                if names:
                    page_part += " (" + ", ".join(names) + ")"
            parts.append(page_part)
        if isinstance(actions, list):
            action_names = [str(action) for action in actions[:4] if str(action).strip()]
            if action_names:
                parts.append("actions: " + ", ".join(action_names))
        if slug:
            parts.append(f"provider={slug}")
        summaries.append("; ".join(parts))

    return summaries


def build_host_session_v1(
    *,
    host_context: HostContext | dict[str, Any],
    host_capabilities: HostCapabilities | dict[str, Any] | None = None,
) -> HostSessionV1:
    """Build a runtime host-session overlay for the current turn."""
    ctx = host_context if isinstance(host_context, HostContext) else HostContext(**host_context)
    caps = None
    if host_capabilities:
        caps = host_capabilities if isinstance(host_capabilities, HostCapabilities) else HostCapabilities(**host_capabilities)

    page = ctx.page if isinstance(ctx.page, dict) else {}
    page_metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    page_type = str(page.get("type") or "unknown")
    page_title = str(page.get("title") or page_type)
    workflow_stage = str(ctx.workflow_stage or page_metadata.get("workflow_stage") or "").strip() or None

    return HostSessionV1(
        host_type=ctx.host_type,
        host_name=ctx.host_name,
        connector_id=ctx.connector_id,
        host_workspace_id=ctx.host_workspace_id,
        host_organization_id=ctx.host_organization_id,
        host_role=ctx.user_role,
        page_type=page_type,
        page_title=page_title,
        workflow_stage=workflow_stage,
        capability_surfaces=list(caps.surfaces) if caps else [],
        available_action_names=_extract_action_names(ctx, caps)[:12],
        selection_label=_summarize_selection(ctx.selection),
        editable_scope_type=_extract_scope_type(ctx.editable_scope),
        resource_uri=ctx.resource_uri,
        external_connection_summaries=_extract_external_connection_summaries(page_metadata),
    )


def format_host_session_for_prompt(session: HostSessionV1 | dict[str, Any]) -> str:
    """Format runtime host-session overlay into a compact prompt block."""
    host_session = session if isinstance(session, HostSessionV1) else HostSessionV1(**session)

    lines = [
        "## Host Session V1",
        f"- Host: {host_session.host_name or host_session.host_type}",
        f"- Page: {host_session.page_type}" + (f" — {host_session.page_title}" if host_session.page_title else ""),
        "- Session boundary: host roles and workflow state are local overlays for this website only. They do not redefine Wiii's core identity.",
    ]
    if host_session.connector_id:
        lines.append(f"- Connected workspace: {host_session.connector_id}")
    if host_session.host_workspace_id:
        lines.append(f"- Host workspace id: {host_session.host_workspace_id}")
    if host_session.host_organization_id:
        lines.append(f"- Host organization id: {host_session.host_organization_id}")
    if host_session.host_role:
        lines.append(f"- Host role on this turn: {host_session.host_role}")
    if host_session.workflow_stage:
        lines.append(f"- Workflow stage: {host_session.workflow_stage}")
    if host_session.selection_label:
        lines.append(f"- Current selection: {host_session.selection_label}")
    if host_session.editable_scope_type:
        lines.append(f"- Editable scope: {host_session.editable_scope_type}")
    if host_session.capability_surfaces:
        lines.append("- Capability surfaces: " + ", ".join(host_session.capability_surfaces))
    if host_session.available_action_names:
        lines.append("- Available host actions: " + ", ".join(host_session.available_action_names))
    if host_session.resource_uri:
        lines.append(f"- Resource URI: {host_session.resource_uri}")
    if host_session.external_connection_summaries:
        lines.append(
            "- External connections: "
            + " | ".join(host_session.external_connection_summaries)
        )
    return "\n".join(lines)


# ── Structured Data Formatters (Sprint 223) ──

_STATUS_VN = {
    "active": "Đang học",
    "completed": "Hoàn thành",
    "NOT_STARTED": "Chưa bắt đầu",
    "IN_PROGRESS": "Đang làm",
    "SUBMITTED": "Đã nộp",
    "GRADED": "Đã chấm",
    "OVERDUE": "Quá hạn",
}


def _format_grades(data: dict) -> str:
    lines = []
    for i, c in enumerate(data.get("courses", []), 1):
        status = _STATUS_VN.get(c.get("status", ""), c.get("status", ""))
        grade_str = f", điểm {c['grade']}" if c.get("grade") is not None else ""
        lines.append(
            f"  {i}. {c.get('code', '')} — {c.get('name', '')}: "
            f"tiến độ {c.get('progress', 0)}%, {status}{grade_str}"
        )
    summary = data.get("summary", {})
    lines.append(
        f"  Tổng kết: {summary.get('total', 0)} khóa, "
        f"{summary.get('completed', 0)} hoàn thành, "
        f"tiến độ TB {summary.get('avg_progress', 0)}%"
    )
    return "\n".join(lines)


def _format_assignment_list(data: dict) -> str:
    lines = []
    for i, a in enumerate(data.get("assignments", []), 1):
        status = _STATUS_VN.get(a.get("status", ""), a.get("status", ""))
        due = a.get("due_date", "")[:10] if a.get("due_date") else "không rõ"
        lines.append(
            f"  {i}. {a.get('name', '')} ({a.get('course_name', '')}) — "
            f"hạn {due}, {status}"
        )
    summary = data.get("summary", {})
    lines.append(
        f"  Tổng: {summary.get('total', 0)} bài tập, "
        f"{summary.get('pending', 0)} cần làm, "
        f"{summary.get('overdue', 0)} quá hạn"
    )
    return "\n".join(lines)


def _format_lesson(data: dict) -> str:
    lines = [
        f"  Khóa: {data.get('course_name', '')} / {data.get('chapter_name', '')}",
        f"  Bài: {data.get('lesson_title', '')}",
        f"  Tiến độ: {data.get('progress', 0)}%",
    ]
    if data.get("media_types"):
        lines.append(f"  Nội dung: {', '.join(data['media_types'])}")
    if data.get("content_text"):
        lines.append(f"  Nội dung bài học: {data['content_text'][:2000]}")
    return "\n".join(lines)


def _format_quiz(data: dict) -> str:
    lines = [
        f"  Bài kiểm tra: {data.get('quiz_title', '')}",
        f"  Câu hỏi {data.get('question_number', '?')}/{data.get('total_questions', '?')}",
        f"  Nội dung: {data.get('question_text', '')}",
    ]
    if data.get("options"):
        for j, opt in enumerate(data["options"]):
            lines.append(f"    {chr(65 + j)}) {opt}")
    if data.get("attempts_used") is not None:
        lines.append(f"  Số lần thử: {data['attempts_used']}")
    if data.get("time_remaining_seconds") is not None:
        mins = data["time_remaining_seconds"] // 60
        lines.append(f"  Thời gian còn: {mins} phút")
    return "\n".join(lines)


def _format_course_overview(data: dict) -> str:
    lines = [
        f"  Khóa: {data.get('course_code', '')} — {data.get('course_name', '')}",
        f"  Giảng viên: {data.get('instructor', '')}",
        f"  Tiến độ: {data.get('total_progress', 0)}%",
    ]
    for ch in data.get("chapters", []):
        lines.append(
            f"    - {ch.get('name', '')}: "
            f"{ch.get('completed', 0)}/{ch.get('lesson_count', 0)} bài"
        )
    return "\n".join(lines)


_FORMATTERS = {
    "grades": _format_grades,
    "assignment_list": _format_assignment_list,
    "lesson": _format_lesson,
    "quiz": _format_quiz,
    "course_overview": _format_course_overview,
}


def format_structured_data_for_prompt(ctx: "HostContext") -> str:
    """Format structured page data as Vietnamese text for prompt injection.

    Sprint 223: Hybrid Visual Context Engine -- Path A.
    Returns empty string if no structured data available.
    """
    if not ctx.content or not isinstance(ctx.content, dict):
        return ""
    structured = ctx.content.get("structured")
    if not structured or not isinstance(structured, dict):
        return ""

    data_type = structured.get("_type", "")
    formatter = _FORMATTERS.get(data_type)
    if formatter:
        return formatter(structured)

    # Fallback: JSON dump for unknown types
    return json.dumps(structured, ensure_ascii=False, indent=2)
