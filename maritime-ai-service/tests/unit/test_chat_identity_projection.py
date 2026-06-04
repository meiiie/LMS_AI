from app.core.security import AuthenticatedUser
from app.models.schemas import ChatRequest, UserRole


def _make_request(**overrides) -> ChatRequest:
    payload = {
        "user_id": "legacy-user",
        "message": "Xin chao",
        "role": UserRole.STUDENT,
        "organization_id": "legacy-org",
    }
    payload.update(overrides)
    return ChatRequest(**payload)


def _make_auth(**overrides) -> AuthenticatedUser:
    payload = {
        "user_id": "canonical-user",
        "auth_method": "jwt",
        "role": "teacher",
        "platform_role": "user",
        "organization_id": "org-wiii",
        "identity_version": "2",
    }
    payload.update(overrides)
    return AuthenticatedUser(**payload)


def test_sync_chat_projects_canonical_identity_from_auth():
    from app.api.v1.chat import _canonicalize_chat_request_from_auth

    projected = _canonicalize_chat_request_from_auth(_make_request(), _make_auth())

    assert projected.user_id == "canonical-user"
    assert projected.role == UserRole.STUDENT
    assert projected.organization_id == "org-wiii"


def test_stream_chat_projects_canonical_identity_from_auth():
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth

    projected = _canonicalize_stream_request_from_auth(_make_request(), _make_auth(role="student"))

    assert projected.user_id == "canonical-user"
    assert projected.role == UserRole.STUDENT
    assert projected.organization_id == "org-wiii"


def test_stream_chat_preserves_request_org_when_auth_has_no_org():
    from app.core.config import settings
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth

    original_multi_tenant = settings.enable_multi_tenant
    original_environment = settings.environment
    settings.enable_multi_tenant = True
    settings.environment = "development"
    try:
        projected = _canonicalize_stream_request_from_auth(
            _make_request(organization_id="org-host"),
            _make_auth(organization_id=None),
        )
    finally:
        settings.enable_multi_tenant = original_multi_tenant
        settings.environment = original_environment

    assert projected.user_id == "canonical-user"
    assert projected.organization_id == "org-host"


def test_sync_chat_drops_body_org_when_prod_auth_has_no_org():
    from app.core.config import settings
    from app.api.v1.chat import _canonicalize_chat_request_from_auth

    original_multi_tenant = settings.enable_multi_tenant
    original_environment = settings.environment
    settings.enable_multi_tenant = True
    settings.environment = "production"
    try:
        projected = _canonicalize_chat_request_from_auth(
            _make_request(organization_id="org-body-only"),
            _make_auth(organization_id=None),
        )
    finally:
        settings.enable_multi_tenant = original_multi_tenant
        settings.environment = original_environment

    assert projected.user_id == "canonical-user"
    assert projected.organization_id is None


def test_stream_chat_drops_body_org_when_prod_auth_has_no_org():
    from app.core.config import settings
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth

    original_multi_tenant = settings.enable_multi_tenant
    original_environment = settings.environment
    settings.enable_multi_tenant = True
    settings.environment = "production"
    try:
        projected = _canonicalize_stream_request_from_auth(
            _make_request(organization_id="org-body-only"),
            _make_auth(organization_id=None),
        )
    finally:
        settings.enable_multi_tenant = original_multi_tenant
        settings.environment = original_environment

    assert projected.user_id == "canonical-user"
    assert projected.organization_id is None


def test_sync_chat_prefers_host_role_overlay_for_lms_sessions():
    from app.api.v1.chat import _canonicalize_chat_request_from_auth

    projected = _canonicalize_chat_request_from_auth(
        _make_request(),
        _make_auth(
            role="student",
            auth_method="lms",
            role_source="lms_host",
            host_role="teacher",
        ),
    )

    assert projected.role == UserRole.TEACHER


def test_stream_chat_does_not_promote_platform_admin_to_admin_persona():
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth

    projected = _canonicalize_stream_request_from_auth(
        _make_request(role=UserRole.ADMIN),
        _make_auth(
            role="admin",
            platform_role="platform_admin",
            auth_method="google",
            role_source="platform",
        ),
    )

    assert projected.role == UserRole.STUDENT


def test_sync_chat_preserves_request_model_override():
    from app.api.v1.chat import _canonicalize_chat_request_from_auth

    projected = _canonicalize_chat_request_from_auth(
        _make_request(model="qwen/qwen3.6-plus:free", provider="openrouter"),
        _make_auth(),
    )

    assert projected.model == "qwen/qwen3.6-plus:free"
    assert projected.provider == "openrouter"


def test_stream_chat_preserves_request_model_override():
    from app.api.v1.chat_stream import _canonicalize_stream_request_from_auth

    projected = _canonicalize_stream_request_from_auth(
        _make_request(model="qwen/qwen3.6-plus:free", provider="openrouter"),
        _make_auth(role="student"),
    )

    assert projected.model == "qwen/qwen3.6-plus:free"
    assert projected.provider == "openrouter"
