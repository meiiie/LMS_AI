"""Sprint 222: Universal Context Engine — host_context_prompt in AgentState."""
import json


def test_agent_state_has_host_context_prompt_field():
    """AgentState TypedDict must include host_context_prompt."""
    from app.engine.multi_agent.state import AgentState
    annotations = AgentState.__annotations__
    assert "host_context_prompt" in annotations, (
        "AgentState missing host_context_prompt field"
    )


def test_agent_state_has_host_context_field():
    """AgentState must include host_context (raw dict from request)."""
    from app.engine.multi_agent.state import AgentState
    annotations = AgentState.__annotations__
    assert "host_context" in annotations, (
        "AgentState missing host_context field"
    )


def test_agent_state_has_operator_contract_fields():
    """AgentState must include host capability and operator-session prompts."""
    from app.engine.multi_agent.state import AgentState

    annotations = AgentState.__annotations__
    assert "host_capabilities" in annotations
    assert "host_capabilities_prompt" in annotations
    assert "operator_session" in annotations
    assert "operator_context_prompt" in annotations


# ── Sprint 222 Task 4: Feature gate tests ──────────────────────────


def test_config_has_enable_host_context_flag():
    """Feature gate must exist and default to False."""
    from app.core.config import Settings
    default = Settings.model_fields["enable_host_context"].default
    assert default is False


def test_config_has_enable_host_actions_flag():
    """Action gate must exist and default to False."""
    from app.core.config import Settings
    default = Settings.model_fields["enable_host_actions"].default
    assert default is False


def test_config_has_enable_host_skills_flag():
    """Skills gate must exist and default to False."""
    from app.core.config import Settings
    default = Settings.model_fields["enable_host_skills"].default
    assert default is False


# ── Sprint 222 Task 2: HostContext Pydantic models ───────────────────


def test_host_context_model_accepts_generic_page():
    """HostContext must accept any host_type with generic page structure."""
    from app.engine.context.host_context import HostContext
    ctx = HostContext(
        host_type="lms",
        page={"type": "lesson", "title": "COLREGs Rule 14", "url": "/course/123/lesson/5"},
    )
    assert ctx.host_type == "lms"
    assert ctx.page["type"] == "lesson"


def test_host_context_model_accepts_operator_fields():
    """HostContext accepts role, workflow, selection, editable scope, and entity refs."""
    from app.engine.context.host_context import HostContext

    ctx = HostContext(
        host_type="lms",
        page={"type": "course_editor", "title": "Course Editor"},
        user_role="teacher",
        workflow_stage="authoring",
        selection={"type": "lesson_block", "label": "Intro block"},
        editable_scope={"type": "course", "allowed_operations": ["lesson_content", "quiz"]},
        entity_refs=[{"type": "course", "id": "c-1", "title": "COLREGs"}],
    )

    assert ctx.user_role == "teacher"
    assert ctx.workflow_stage == "authoring"
    assert ctx.selection["type"] == "lesson_block"
    assert ctx.editable_scope["type"] == "course"
    assert ctx.entity_refs[0]["id"] == "c-1"


def test_host_context_model_accepts_ecommerce():
    """HostContext works for e-commerce host type too."""
    from app.engine.context.host_context import HostContext
    ctx = HostContext(
        host_type="ecommerce",
        page={"type": "product", "title": "Máy Bơm Shimizu", "url": "/product/xyz"},
        content={"snippet": "Máy bơm nước Shimizu PS-128 BIT..."},
    )
    assert ctx.host_type == "ecommerce"
    assert ctx.content["snippet"].startswith("Máy bơm")


def test_host_context_backward_compat_from_page_context():
    """Sprint 221 PageContext can be wrapped into HostContext."""
    from app.engine.context.host_context import from_legacy_page_context
    legacy = {
        "page_type": "quiz",
        "page_title": "Bài kiểm tra COLREGs",
        "connector_id": "maritime-lms",
        "host_user_id": "student-1",
        "host_workspace_id": "org-1",
        "host_organization_id": "org-1",
        "course_id": "colregs_2024",
        "course_name": "COLREGs",
        "quiz_question": "Tàu nào nhường?",
        "quiz_options": ["Tàu A", "Tàu B"],
    }
    ctx = from_legacy_page_context(legacy)
    assert ctx.host_type == "lms"
    assert ctx.connector_id == "maritime-lms"
    assert ctx.host_user_id == "student-1"
    assert ctx.host_workspace_id == "org-1"
    assert ctx.host_organization_id == "org-1"
    assert ctx.page["type"] == "quiz"
    assert ctx.page["title"] == "Bài kiểm tra COLREGs"
    assert ctx.page["metadata"]["course_id"] == "colregs_2024"


def test_host_context_max_snippet_length():
    """Content snippet must be truncated to 2000 chars."""
    from app.engine.context.host_context import HostContext
    long_snippet = "A" * 5000
    ctx = HostContext(
        host_type="lms",
        page={"type": "lesson", "title": "Test"},
        content={"snippet": long_snippet},
    )
    assert len(ctx.content["snippet"]) <= 2000


def test_host_capabilities_model():
    """HostCapabilities declares available resources and tools."""
    from app.engine.context.host_context import HostCapabilities
    caps = HostCapabilities(
        host_type="lms",
        host_name="Maritime Academy LMS",
        connector_id="maritime-lms",
        host_workspace_id="org-1",
        host_organization_id="org-1",
        version="2",
        resources=["current-page", "user-profile"],
        surfaces=["ai_sidebar", "editor_shell"],
        tools=[
            {"name": "navigate", "description": "Navigate to a page",
             "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}}},
        ],
    )
    assert caps.host_type == "lms"
    assert caps.connector_id == "maritime-lms"
    assert caps.host_workspace_id == "org-1"
    assert caps.host_organization_id == "org-1"
    assert caps.version == "2"
    assert caps.surfaces == ["ai_sidebar", "editor_shell"]
    assert len(caps.tools) == 1
    assert caps.tools[0]["name"] == "navigate"


def test_from_legacy_with_student_state():
    """Legacy conversion should include student_state as user_state."""
    from app.engine.context.host_context import from_legacy_page_context
    ctx = from_legacy_page_context(
        {"page_type": "lesson", "page_title": "Test"},
        student_state={"scroll_percent": 75, "time_on_page_ms": 60000},
    )
    assert ctx.user_state is not None
    assert ctx.user_state["scroll_percent"] == 75


# --- Tasks 11-12: Schema + InputProcessor ---

def test_user_context_accepts_host_context():
    """UserContext must accept optional host_context dict."""
    from app.models.schemas import UserContext
    uc = UserContext(
        display_name="Minh",
        role="student",
        host_context={
            "host_type": "lms",
            "page": {"type": "lesson", "title": "COLREGs"},
        },
    )
    assert uc.host_context is not None
    assert uc.host_context["host_type"] == "lms"


def test_user_context_sanitizes_public_host_payload_and_keeps_control_feedback():
    from app.models.schemas import ChatRequest

    request = ChatRequest(
        user_id="user-1",
        message="Hien thi context",
        role="teacher",
        user_context={
            "display_name": "Minh",
            "role": "teacher",
            "current_course_id": "course-safe",
            "host_context": {
                "host_type": "lms",
                "connection_ref": "conn-secret",
                "page": {
                    "type": "lesson",
                    "title": "COLREGs",
                    "page_id": "page-secret",
                    "metadata": {
                        "access_token": "access-secret",
                        "safe_label": "visible",
                    },
                },
            },
            "available_actions": [
                {
                    "name": "authoring.apply_lesson_patch",
                    "input_schema": {
                        "type": "object",
                        "required": ["preview_token", "approval_token", "message"],
                        "properties": {
                            "preview_token": {"type": "string"},
                            "approval_token": {"type": "string"},
                            "message": {"type": "string"},
                            "page_id": {"type": "string"},
                        },
                    },
                }
            ],
            "host_action_feedback": {
                "last_action_result": {
                    "action": "authoring.preview_lesson_patch",
                    "success": True,
                    "summary": "Preview ready",
                    "data": {
                        "preview_token": "preview-secret",
                        "approval_token": "approval-secret",
                        "preview_kind": "lesson_patch",
                    },
                }
            },
            "host_action_control_feedback": {
                "last_action_result": {
                    "data": {"approval_token": "client-injected-secret"}
                }
            },
        },
    )

    public_payload = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)

    assert request.user_context.current_course_id == "course-safe"
    assert request.user_context.host_context["host_type"] == "lms"
    assert request.user_context.host_context["page"]["metadata"]["safe_label"] == "visible"
    assert request.user_context.available_actions[0]["input_schema"]["required"] == [
        "message"
    ]
    assert request.user_context.available_actions[0]["input_schema"]["properties"] == {
        "message": {"type": "string"}
    }
    assert request.user_context.host_action_feedback["last_action_result"]["data"] == {
        "preview_kind": "lesson_patch",
        "preview_available": True,
        "approval_available": True,
    }
    assert request.user_context.host_action_control_feedback["last_action_result"]["data"] == {
        "approval_token": "approval-secret",
        "preview_kind": "lesson_patch",
        "preview_token": "preview-secret",
    }

    for forbidden in [
        "conn-secret",
        "page-secret",
        "access-secret",
        "preview-secret",
        "approval-secret",
        "client-injected-secret",
        "connection_ref",
        "page_id",
        "access_token",
        "preview_token",
        "approval_token",
        "host_action_control_feedback",
    ]:
        assert forbidden not in public_payload


def test_chat_request_canonicalization_resanitizes_mutated_user_context():
    from app.api.v1.chat import _canonicalize_chat_request_from_auth
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth
    from app.core.security_models import AuthenticatedUser
    from app.models.schemas import ChatRequest

    chat_request = ChatRequest(
        user_id="spoofed-user",
        message="Hien thi context",
        role="student",
        user_context={
            "display_name": "Minh",
            "role": "student",
            "host_context": {"host_type": "lms"},
        },
    )
    chat_request.user_context.host_context["connection_ref"] = "late-conn-secret"
    chat_request.user_context.host_action_feedback = {
        "last_action_result": {
            "action": "authoring.preview_lesson_patch",
            "data": {
                "preview_token": "late-preview-secret",
                "approval_token": "late-approval-secret",
                "preview_kind": "lesson_patch",
            },
        }
    }

    auth = AuthenticatedUser(
        user_id="auth-user",
        auth_method="api_key",
        role="teacher",
        organization_id="org-auth",
    )

    for canonical in [
        _canonicalize_chat_request_from_auth(chat_request, auth),
        _canonicalize_stream_request_from_auth(chat_request, auth),
    ]:
        public_payload = json.dumps(canonical.model_dump(mode="json"), ensure_ascii=False)

        assert canonical.user_id == "auth-user"
        assert canonical.role == "teacher"
        assert canonical.organization_id == "org-auth"
        assert canonical.user_context.host_context == {"host_type": "lms"}
        assert canonical.user_context.host_action_feedback["last_action_result"]["data"] == {
            "preview_kind": "lesson_patch",
            "preview_available": True,
            "approval_available": True,
        }
        assert canonical.user_context.host_action_control_feedback["last_action_result"]["data"] == {
            "approval_token": "late-approval-secret",
            "preview_kind": "lesson_patch",
            "preview_token": "late-preview-secret",
        }

        assert "late-conn-secret" not in public_payload
        assert "late-preview-secret" not in public_payload
        assert "late-approval-secret" not in public_payload


def test_graph_bootstrap_splits_control_feedback_from_model_context():
    from app.engine.multi_agent.graph_process import _split_model_context as split_sync_context
    from app.engine.multi_agent.graph_stream_runtime import (
        _split_model_context as split_stream_context,
    )

    context = {
        "host_context": {"host_type": "lms"},
        "host_action_feedback": {
            "last_action_result": {
                "data": {
                    "preview_kind": "lesson_patch",
                    "preview_available": True,
                }
            }
        },
        "_host_action_control_feedback": {
            "last_action_result": {
                "data": {"preview_token": "internal-preview-secret"}
            }
        },
    }

    for split_context in [split_sync_context, split_stream_context]:
        model_context, control_feedback = split_context(context)

        assert "_host_action_control_feedback" not in model_context
        assert "internal-preview-secret" not in json.dumps(
            model_context,
            ensure_ascii=False,
        )
        assert control_feedback["last_action_result"]["data"]["preview_token"] == (
            "internal-preview-secret"
        )


def test_user_context_host_context_defaults_none():
    """host_context should default to None."""
    from app.models.schemas import UserContext
    uc = UserContext(display_name="Minh", role="student")
    assert uc.host_context is None


def test_chat_context_has_host_context_field():
    """ChatContext must have host_context field."""
    from app.services.input_processor import ChatContext
    import dataclasses
    field_names = [f.name for f in dataclasses.fields(ChatContext)]
    assert "host_context" in field_names


# --- Task 13: Pipeline threading ---

def test_orchestrator_threads_host_context():
    """Multi-agent context builder must include host_context in graph context."""
    import inspect
    from app.services import chat_orchestrator_multi_agent
    source = inspect.getsource(chat_orchestrator_multi_agent.build_multi_agent_context_impl)
    assert "host_context" in source, "chat_orchestrator must thread host_context"


def test_chat_stream_threads_host_context():
    """chat_stream.py must include host_context in context dict."""
    import inspect
    from app.api.v1 import chat_stream
    source = inspect.getsource(chat_stream)
    assert "host_context" in source, "chat_stream must thread host_context"


def test_build_operator_session_includes_candidate_actions_and_confirmation():
    """Operator session should summarize host actions and confirmation policy."""
    from app.engine.context.host_context import (
        build_operator_session_v1,
        format_operator_session_for_prompt,
    )

    session = build_operator_session_v1(
        query="Tạo quiz mới cho bài này",
        host_context={
            "host_type": "lms",
            "page": {"type": "course_editor", "title": "Curriculum"},
            "user_role": "teacher",
            "workflow_stage": "authoring",
            "editable_scope": {
                "type": "course",
                "allowed_operations": ["quiz"],
                "requires_confirmation": True,
            },
        },
        host_capabilities={
            "host_type": "lms",
            "resources": ["current-page"],
            "tools": [
                {
                    "name": "assessment.create_quiz",
                    "description": "Create quiz",
                    "roles": ["teacher", "admin"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
        },
    )

    assert session.pending_approval is True
    assert "assessment.create_quiz" in session.candidate_actions
    prompt = format_operator_session_for_prompt(session)
    assert "Operator Session V1" in prompt
    assert "assessment.create_quiz" in prompt
    assert "Identity boundary" in prompt


def test_build_operator_session_prefers_confirm_apply_when_preview_exists():
    """Preview feedback should turn operator next step into an explicit apply flow."""
    from app.engine.context.host_context import build_operator_session_v1

    session = build_operator_session_v1(
        query="Neu preview on thi ap dung cho lesson nay",
        host_context={
            "host_type": "lms",
            "page": {"type": "course_editor", "title": "Curriculum"},
            "user_role": "teacher",
            "workflow_stage": "authoring",
        },
        host_capabilities={
            "host_type": "lms",
            "resources": ["current-page"],
            "tools": [
                {
                    "name": "authoring.apply_lesson_patch",
                    "description": "Apply lesson patch",
                    "roles": ["teacher"],
                    "requires_confirmation": True,
                    "mutates_state": True,
                }
            ],
        },
        last_host_result="Lesson patch preview ready (token=lesson-preview-123).",
        host_action_feedback={
            "last_action_result": {
                "action": "authoring.preview_lesson_patch",
                "success": True,
                "summary": "Lesson patch preview ready.",
                "data": {
                    "preview_token": "lesson-preview-123",
                    "preview_kind": "lesson_patch",
                },
            }
        },
    )

    assert session.pending_approval is True
    assert "authoring.apply_lesson_patch" in session.next_best_step


def test_host_session_prompt_includes_wiii_connect_snapshot():
    from app.engine.context.host_context import (
        build_host_session_v1,
        format_host_session_for_prompt,
    )

    session = build_host_session_v1(
        host_context={
            "host_type": "wiii_desktop",
            "host_name": "Wiii Desktop",
            "page": {
                "type": "chat",
                "title": "Wiii",
                "metadata": {
                    "wiii_connect": {
                        "provider_slug": "facebook",
                        "provider_label": "Facebook",
                        "status": "connected",
                        "active_connection_count": 1,
                        "page_count": 1,
                        "page_names": ["Wiii"],
                        "available_actions": [
                            "wiii_connect.facebook_post.direct_apply",
                            "wiii_connect.facebook_post.preview",
                            "wiii_connect.facebook_post.apply",
                        ],
                    }
                },
            },
        }
    )

    prompt = format_host_session_for_prompt(session)

    assert "External connections" in prompt
    assert "Facebook: connected" in prompt
    assert "Wiii" in prompt
    assert "wiii_connect.facebook_post.direct_apply" in prompt
    assert "wiii_connect.facebook_post.preview" in prompt
