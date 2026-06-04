import pytest
from starlette.requests import Request


def test_host_action_audit_route_registered_when_host_actions_disabled(monkeypatch):
    import app.api.v1 as api_v1
    from app.core.config import settings

    registered: list[tuple[str, str]] = []
    optional_registered: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        api_v1,
        "_register_router",
        lambda _router, import_path, label: registered.append((import_path, label)),
    )
    monkeypatch.setattr(
        api_v1,
        "_register_optional_router",
        lambda _router, flag_name, import_path, label: optional_registered.append(
            (flag_name, import_path, label)
        ),
    )
    monkeypatch.setattr(settings, "enable_host_actions", False, raising=False)

    api_v1._build_router()

    assert ("app.api.v1.host_actions.router", "Host Action Audit") in registered
    assert all(
        import_path != "app.api.v1.host_actions.router"
        for _flag_name, import_path, _label in optional_registered
    )


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/host-actions/audit",
        "headers": [(b"user-agent", b"pytest-agent")],
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
        "query_string": b"",
        "http_version": "1.1",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_log_host_action_event_hashes_preview_token(monkeypatch):
    from app.engine.context.host_action_audit import log_host_action_event

    captured = {}

    async def _fake_log_auth_event(event_type, **kwargs):
        captured["event_type"] = event_type
        captured["kwargs"] = kwargs

    monkeypatch.setattr("app.auth.auth_audit.log_auth_event", _fake_log_auth_event)

    await log_host_action_event(
        event_type="preview_created",
        user_id="teacher-1",
        action="authoring.preview_lesson_patch",
        request_id="req-preview-1",
        preview_token="preview-token-secret",
        preview_kind="lesson_patch",
        summary="Preview ready",
        host_type="lms",
        page_type="course_editor",
        metadata={"lesson_id": "lesson-1"},
    )

    assert captured["event_type"] == "host_action.preview_created"
    metadata = captured["kwargs"]["metadata"]
    assert metadata["preview_token_hash"]
    assert metadata["preview_token_hash"] != "preview-token-secret"
    assert metadata["action"] == "authoring.preview_lesson_patch"
    assert metadata["metadata"]["lesson_id"] == "lesson-1"


@pytest.mark.asyncio
async def test_submit_host_action_audit_logs_success(monkeypatch):
    from app.api.v1.host_actions import submit_host_action_audit
    from app.core.security import AuthenticatedUser
    from app.models.host_context_schemas import HostActionAuditRequest

    captured = {}

    async def _fake_log_host_action_event(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "app.api.v1.host_actions.log_host_action_event",
        _fake_log_host_action_event,
    )

    body = HostActionAuditRequest(
        event_type="publish_confirmed",
        action="publish.apply_quiz",
        request_id="req-publish-1",
        summary="Published quiz quiz-1.",
        host_type="lms",
        page_type="course_editor",
        user_role="teacher",
        workflow_stage="authoring",
        preview_kind="quiz_publish",
        preview_token="preview-1",
        target_type="quiz",
        target_id="quiz-1",
        surface="editor_shell",
        metadata={"quiz_title": "Quiz cuoi chuong"},
    )
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-1",
    )

    response = await submit_host_action_audit(_make_request(), body, auth)

    assert response.status == "success"
    assert response.event_type == "publish_confirmed"
    assert captured["user_id"] == "teacher-1"
    assert captured["organization_id"] == "org-1"
    assert captured["target_id"] == "quiz-1"
    assert captured["metadata"]["quiz_title"] == "Quiz cuoi chuong"


@pytest.mark.asyncio
async def test_host_action_result_bridge_resumes_pending_result() -> None:
    from app.engine.context.host_action_result_bridge import (
        publish_host_action_result,
        register_host_action_result_request,
        wait_for_host_action_result,
    )

    ticket = register_host_action_result_request(
        request_id="req-result-bridge-1",
        action="wiii_connect.facebook_post.direct_apply",
        user_id="teacher-1",
        organization_id="org-1",
    )

    publication = publish_host_action_result(
        request_id="req-result-bridge-1",
        action="wiii_connect.facebook_post.direct_apply",
        success=True,
        summary="Da dang.",
        data={
            "post_id": "post-1",
            "approval_token": "secret-approval",
            "nested": {"image_base64": "secret-image"},
        },
        user_id="teacher-1",
        organization_id="org-1",
    )
    payload = await wait_for_host_action_result(ticket, timeout_seconds=0.1)

    assert publication.status == "accepted"
    assert payload is not None
    assert payload["status"] == "action_completed"
    assert payload["success"] is True
    assert payload["data"]["post_id"] == "post-1"
    assert payload["data"]["approval_token"] == "[redacted]"
    assert payload["data"]["nested"]["image_base64"] == "[redacted]"


@pytest.mark.asyncio
async def test_submit_host_action_result_rejects_identity_mismatch() -> None:
    from app.api.v1.host_actions import submit_host_action_result
    from app.core.security import AuthenticatedUser
    from app.engine.context.host_action_result_bridge import (
        register_host_action_result_request,
        wait_for_host_action_result,
    )
    from app.models.host_context_schemas import HostActionResultRequest
    from fastapi import HTTPException

    ticket = register_host_action_result_request(
        request_id="req-result-identity-1",
        action="wiii_connect.facebook_post.direct_apply",
        user_id="teacher-1",
        organization_id="org-1",
    )
    auth = AuthenticatedUser(
        user_id="other-user",
        auth_method="jwt",
        role="teacher",
        organization_id="org-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        await submit_host_action_result(
            _make_request(),
            HostActionResultRequest(
                action="wiii_connect.facebook_post.direct_apply",
                request_id="req-result-identity-1",
                success=True,
            ),
            auth,
        )

    assert exc_info.value.status_code == 403
    assert await wait_for_host_action_result(ticket, timeout_seconds=0.01) is None


@pytest.mark.asyncio
async def test_submit_host_action_result_accepts_matching_pending_request() -> None:
    from app.api.v1.host_actions import submit_host_action_result
    from app.core.security import AuthenticatedUser
    from app.engine.context.host_action_result_bridge import (
        register_host_action_result_request,
        wait_for_host_action_result,
    )
    from app.models.host_context_schemas import HostActionResultRequest

    ticket = register_host_action_result_request(
        request_id="req-result-api-1",
        action="wiii_connect.facebook_post.direct_apply",
        user_id="teacher-1",
        organization_id="org-1",
    )
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-1",
    )

    response = await submit_host_action_result(
        _make_request(),
        HostActionResultRequest(
            action="wiii_connect.facebook_post.direct_apply",
            request_id="req-result-api-1",
            success=True,
            summary="Da dang len Facebook.",
            data={"provider_post_id": "post-123"},
        ),
        auth,
    )
    payload = await wait_for_host_action_result(ticket, timeout_seconds=0.1)

    assert response.status == "accepted"
    assert response.matched is True
    assert payload is not None
    assert payload["summary"] == "Da dang len Facebook."
