"""Backend-owned Wiii Connect tools for the direct agent loop."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.security_models import AuthenticatedUser
from app.engine.tools.native_tool import StructuredTool
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
)
from app.engine.wiii_connect import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectExecutionRequest,
    action_catalog_public_metadata,
    build_audit_ledger_record,
    build_composio_adapter_config,
    build_composio_execution_enabled_entry,
    build_composio_external_user_id,
    build_composio_provider_adapter_capability,
    build_facebook_post_approval_token,
    build_facebook_post_preview_evidence_id,
    connection_ref_matches,
    decide_execution_gateway,
    default_persistent_storage_status_metadata,
    execute_composio_tool,
    facebook_image_sha256,
    get_wiii_connect_persistent_storage,
    get_wiii_connect_provider_entry,
    list_composio_facebook_pages,
    normalize_facebook_image_filename,
    normalize_facebook_image_media_type,
    normalize_facebook_image_url,
    normalize_facebook_page_id,
    normalize_facebook_post_message,
    scope_policy_for_provider_entry,
    stage_composio_file_upload,
    verify_composio_tool_schema,
)


WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION = "wiii_connect_facebook_direct_tool.v1"
_MAX_SURFACE_LEN = 80


class WiiiConnectFacebookPostDirectApplyInput(BaseModel):
    """Model-authored Facebook Page post request for Wiii Connect."""

    model_config = ConfigDict(extra="ignore")

    provider_slug: str = Field(default="facebook")
    connection_ref: str = Field(default="")
    page_id: str = Field(default="")
    message: str = Field(default="")
    image_policy: str = Field(default="none")
    image_base64: str | None = Field(default=None)
    image_media_type: str | None = Field(default=None)
    image_filename: str | None = Field(default=None)
    image_url: str | None = Field(default=None)


@dataclass(frozen=True, slots=True)
class _ImagePayload:
    content: bytes = b""
    media_type: str = ""
    filename: str = ""
    image_url: str = ""
    error: str = ""


def make_wiii_connect_facebook_post_direct_apply_tool(
    *,
    state: Mapping[str, Any] | None = None,
) -> StructuredTool:
    """Return a backend-owned Facebook publish tool scoped to one chat state."""

    captured_state = dict(state or {})

    async def _run(
        provider_slug: str = "facebook",
        connection_ref: str = "",
        page_id: str = "",
        message: str = "",
        image_policy: str = "none",
        image_base64: str | None = None,
        image_media_type: str | None = None,
        image_filename: str | None = None,
        image_url: str | None = None,
    ) -> str:
        payload = await execute_wiii_connect_facebook_post_direct_apply(
            state=captured_state,
            provider_slug=provider_slug,
            connection_ref=connection_ref,
            page_id=page_id,
            message=message,
            image_policy=image_policy,
            image_base64=image_base64,
            image_media_type=image_media_type,
            image_filename=image_filename,
            image_url=image_url,
        )
        return json.dumps(payload, ensure_ascii=False)

    generated = StructuredTool.from_function(
        _run,
        name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        description=(
            "Publish a Facebook Page post through Wiii Connect's backend-owned "
            "connector gateway for an explicit user request. Draft `message` as "
            "the exact post copy. If the user asks for any/random content, write "
            "a short original safe post. If the user attached an image, set "
            "`image_policy` to `use_latest_user_image`; never include raw image "
            "bytes unless the tool input already provides them from Wiii runtime."
        ),
        args_schema=WiiiConnectFacebookPostDirectApplyInput,
    )
    generated.mutates_state = True
    generated.requires_confirmation = False
    return generated


async def execute_wiii_connect_facebook_post_direct_apply(
    *,
    state: Mapping[str, Any],
    provider_slug: str = "facebook",
    connection_ref: str = "",
    page_id: str = "",
    message: str = "",
    image_policy: str = "none",
    image_base64: str | None = None,
    image_media_type: str | None = None,
    image_filename: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Execute Facebook preview/apply entirely behind Wiii's backend policy."""

    user = _authenticated_user_from_state(state)
    provider = _provider_slug(provider_slug)
    if provider != "facebook":
        return _failure("unsupported_provider_post", provider_slug=provider)
    entry = get_wiii_connect_provider_entry(provider)
    if entry is None:
        return _failure("unknown_wiii_connect_provider", provider_slug=provider)

    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = _storage_status()
    connection = _select_connection(
        effective_entry.slug,
        current_user=user,
        storage=storage,
        connection_ref=connection_ref,
    )
    selected_connection_ref = connection.connection_ref if connection else ""
    safe_connection_id = connection.connection_id if connection else ""
    normalized_message = normalize_facebook_post_message(message)
    image = _resolve_image_payload(
        state=state,
        image_policy=image_policy,
        image_base64=image_base64,
        image_media_type=image_media_type,
        image_filename=image_filename,
        image_url=image_url,
    )
    normalized_page_id = normalize_facebook_page_id(page_id)

    if image.error or not normalized_message:
        return _failure(
            image.error or "missing_message",
            provider_slug=effective_entry.slug,
            storage=storage,
            connection_ref_present=bool(selected_connection_ref),
        )
    if connection is None:
        request = _execution_request(
            provider_slug=effective_entry.slug,
            action_slug=_facebook_post_action_slug(image),
            mutation="apply",
            approval_token_present=True,
            preview_evidence_id="connection_missing",
            argument_keys=_facebook_post_argument_keys(image),
        )
        gateway = decide_execution_gateway(
            effective_entry,
            None,
            request,
            adapter_capability=build_composio_provider_adapter_capability(
                composio_config,
            ),
            audit_ledger_metadata={"persistent": _audit_persistent(storage)},
            connection_selection_required=not bool(connection_ref),
            scope_policy=scope_policy_for_provider_entry(effective_entry),
        )
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=user,
            metadata={
                "surface": "direct_tool",
                "stage": "connection",
                "connection_ref_present": bool(connection_ref),
            },
        )
        return _failure(
            gateway.reason,
            provider_slug=effective_entry.slug,
            gateway=gateway.to_public_metadata(),
            storage=storage,
        )

    if not normalized_page_id:
        page_decision = await _select_default_facebook_page(
            effective_entry,
            connection,
            composio_config=composio_config,
            storage=storage,
            current_user=user,
        )
        if not page_decision["ready"]:
            return _failure(
                str(page_decision["reason"]),
                provider_slug=effective_entry.slug,
                gateway=page_decision.get("gateway"),
                storage=storage,
            )
        normalized_page_id = str(page_decision["page_id"])

    action_slug = _facebook_post_action_slug(image)
    preview_evidence_id = build_facebook_post_preview_evidence_id(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=normalized_page_id,
        message=normalized_message,
        image_sha256=facebook_image_sha256(image.content),
        image_url=image.image_url,
    )
    approval_token = build_facebook_post_approval_token(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=normalized_page_id,
        message=normalized_message,
        image_sha256=facebook_image_sha256(image.content),
        image_url=image.image_url,
        secret_key=settings.session_secret_key,
    )
    request = _execution_request(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        mutation="apply",
        approval_token_present=True,
        preview_evidence_id=preview_evidence_id,
        preview_evidence_required=True,
        argument_keys=_facebook_post_argument_keys(image),
    )
    gateway = decide_execution_gateway(
        effective_entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(
            composio_config,
        ),
        audit_ledger_metadata={"persistent": _audit_persistent(storage)},
        connection_selection_required=False,
        scope_policy=scope_policy_for_provider_entry(effective_entry),
    )
    audit_base = {
        "surface": "direct_tool",
        "stage": "apply",
        "connection_ref_present": bool(selected_connection_ref),
        "connection_id_present": bool(safe_connection_id),
        "preview_evidence_id_present": bool(preview_evidence_id),
        "approval_token_present": bool(approval_token),
        "message_length": len(normalized_message),
        "image_present": bool(image.content or image.image_url),
        "image_size_bytes": len(image.content),
    }
    if not gateway.allowed:
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=user,
            metadata=audit_base,
        )
        return _failure(
            gateway.reason,
            provider_slug=effective_entry.slug,
            gateway=gateway.to_public_metadata(),
            storage=storage,
        )

    schema = await verify_composio_tool_schema(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
    )
    if not schema.ready:
        _append_execution_stage_audit(
            gateway,
            request,
            storage,
            current_user=user,
            status="blocked",
            reason=schema.reason,
            metadata={**audit_base, "stage": "schema", "schema": schema.to_public_metadata()},
        )
        return _failure(
            schema.reason,
            provider_slug=effective_entry.slug,
            gateway=gateway.to_public_metadata(),
            schema=schema.to_public_metadata(),
            storage=storage,
        )

    arguments: dict[str, Any] = {
        "page_id": normalized_page_id,
        "message": normalized_message,
        "published": True,
    }
    upload_metadata: dict[str, Any] | None = None
    if image.content:
        upload = await stage_composio_file_upload(
            config=composio_config,
            provider_slug=effective_entry.slug,
            action_slug=action_slug,
            filename=image.filename,
            mimetype=image.media_type,
            content=image.content,
        )
        upload_metadata = upload.to_public_metadata()
        if not upload.ready:
            _append_execution_stage_audit(
                gateway,
                request,
                storage,
                current_user=user,
                status="blocked",
                reason=upload.reason,
                metadata={**audit_base, "stage": "file_upload", "upload": upload_metadata},
            )
            return _failure(
                upload.reason,
                provider_slug=effective_entry.slug,
                gateway=gateway.to_public_metadata(),
                schema=schema.to_public_metadata(),
                upload=upload_metadata,
                storage=storage,
            )
        arguments["photo"] = upload.file_descriptor
    elif image.image_url:
        arguments["url"] = image.image_url

    missing_argument_keys = _missing_required_argument_keys(
        required_keys=schema.required_argument_keys,
        arguments=arguments,
    )
    if missing_argument_keys:
        return _failure(
            "missing_required_arguments",
            provider_slug=effective_entry.slug,
            gateway=gateway.to_public_metadata(),
            schema=schema.to_public_metadata(),
            storage=storage,
            data={"missing_argument_keys": list(missing_argument_keys)},
        )

    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=user,
        status="started",
        reason="provider_execution_started",
        metadata={**audit_base, "stage": "execute", "upload": upload_metadata},
    )
    execution = await execute_composio_tool(
        config=composio_config,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        user_id=build_composio_external_user_id(
            organization_id=user.organization_id,
            user_id=user.user_id,
        ),
        connected_account_id=connection.connection_id,
        arguments=arguments,
    )
    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=user,
        status=execution.status,
        reason=execution.reason,
        metadata={
            **audit_base,
            "stage": "execute_result",
            "schema": schema.to_public_metadata(),
            "upload": upload_metadata,
            "execution": execution.to_public_metadata(),
        },
    )
    if execution.status == "succeeded":
        return _success(
            "Đã đăng bài lên Facebook qua Wiii Connect.",
            provider_slug=effective_entry.slug,
            action_slug=action_slug,
            page_id=normalized_page_id,
            gateway=gateway.to_public_metadata(),
            execution=execution.to_public_metadata(),
            storage=storage,
            data={
                "preview_evidence_id_present": True,
                "approval_token_present": True,
                "image_present": bool(image.content or image.image_url),
            },
        )
    return _failure(
        execution.reason,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        gateway=gateway.to_public_metadata(),
        execution=execution.to_public_metadata(),
        storage=storage,
    )


async def _select_default_facebook_page(
    entry: Any,
    connection: WiiiConnectConnectionRecordV1,
    *,
    composio_config: Any,
    storage: dict[str, Any],
    current_user: AuthenticatedUser,
) -> dict[str, Any]:
    request = _execution_request(
        provider_slug=entry.slug,
        action_slug="FACEBOOK_LIST_MANAGED_PAGES",
        mutation="read",
        argument_keys=("fields", "limit"),
    )
    gateway = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(composio_config),
        audit_ledger_metadata={"persistent": _audit_persistent(storage)},
        connection_selection_required=False,
        scope_policy=scope_policy_for_provider_entry(entry),
    )
    if not gateway.allowed:
        _append_execution_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            metadata={"surface": "direct_tool", "stage": "page_list"},
        )
        return {"ready": False, "reason": gateway.reason, "gateway": gateway.to_public_metadata()}
    result = await list_composio_facebook_pages(
        config=composio_config,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        connected_account_id=connection.connection_id,
    )
    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status="succeeded" if result.ready else "blocked",
        reason=result.reason,
        metadata={
            "surface": "direct_tool",
            "stage": "page_list",
            "page_list": result.to_public_metadata(),
        },
    )
    page = result.pages[0] if result.ready and result.pages else None
    if page is None:
        return {
            "ready": False,
            "reason": result.reason or "facebook_page_missing",
            "gateway": gateway.to_public_metadata(),
        }
    return {
        "ready": True,
        "reason": "ready",
        "page_id": page.page_id,
        "page_label": page.name,
        "gateway": gateway.to_public_metadata(),
    }


def _authenticated_user_from_state(state: Mapping[str, Any]) -> AuthenticatedUser:
    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    user_id = str(state.get("user_id") or context.get("user_id") or "").strip()
    organization_id = str(
        state.get("organization_id") or context.get("organization_id") or ""
    ).strip() or None
    session_id = str(state.get("session_id") or context.get("session_id") or "").strip() or None
    role = str(context.get("user_role") or state.get("user_role") or "student").strip() or "student"
    return AuthenticatedUser(
        user_id=user_id or "__global__",
        auth_method="chat_runtime",
        role=role,
        session_id=session_id,
        organization_id=organization_id,
    )


def _select_connection(
    provider_slug: str,
    *,
    current_user: AuthenticatedUser,
    storage: dict[str, Any],
    connection_ref: str,
) -> WiiiConnectConnectionRecordV1 | None:
    if not _connection_storage_ready(storage):
        return None
    owner = _owner_organization_id(current_user)
    records = get_wiii_connect_persistent_storage().list_connection_records(
        organization_id=owner,
        user_id=current_user.user_id,
        provider_slug=provider_slug,
    )
    safe_ref = _safe_public_connection_ref(connection_ref)
    if safe_ref:
        for record in records:
            if connection_ref_matches(
                provider_slug=record.provider_slug,
                connection_id=record.connection_id,
                candidate=safe_ref,
            ):
                return record
        return None
    for record in records:
        if record.active:
            return record
    return records[0] if records else None


def _resolve_image_payload(
    *,
    state: Mapping[str, Any],
    image_policy: str,
    image_base64: str | None,
    image_media_type: str | None,
    image_filename: str | None,
    image_url: str | None,
) -> _ImagePayload:
    normalized_url = normalize_facebook_image_url(image_url)
    raw_image = str(image_base64 or "").strip()
    media_type = str(image_media_type or "").strip()
    filename = str(image_filename or "").strip()
    if not raw_image and str(image_policy or "").strip() == "use_latest_user_image":
        latest = _latest_state_image(state)
        raw_image = str(latest.get("data") or "").strip()
        media_type = str(latest.get("media_type") or latest.get("mime_type") or "").strip()
        filename = str(latest.get("filename") or "wiii-chat-image").strip()
    if not raw_image:
        return _ImagePayload(image_url=normalized_url)
    if "," in raw_image and raw_image.lower().startswith("data:"):
        raw_image = raw_image.split(",", 1)[1]
    normalized_media_type = normalize_facebook_image_media_type(media_type)
    if not normalized_media_type:
        return _ImagePayload(error="unsupported_image_type")
    try:
        content = base64.b64decode(raw_image, validate=True)
    except (binascii.Error, ValueError):
        return _ImagePayload(error="invalid_image_base64")
    if not content:
        return _ImagePayload(error="missing_image")
    if len(content) > 10 * 1024 * 1024:
        return _ImagePayload(error="image_too_large")
    return _ImagePayload(
        content=content,
        media_type=normalized_media_type,
        filename=normalize_facebook_image_filename(
            filename,
            media_type=normalized_media_type,
        ),
    )


def _latest_state_image(state: Mapping[str, Any]) -> Mapping[str, Any]:
    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    images = context.get("images") if isinstance(context, Mapping) else None
    if not isinstance(images, list):
        images = state.get("images")
    if not isinstance(images, list):
        return {}
    for image in images:
        if isinstance(image, Mapping) and image.get("data"):
            return image
    return {}


def _facebook_post_action_slug(image: _ImagePayload) -> str:
    if image.content or image.image_url:
        return "FACEBOOK_CREATE_PHOTO_POST"
    return "FACEBOOK_CREATE_POST"


def _facebook_post_argument_keys(image: _ImagePayload) -> tuple[str, ...]:
    if image.content:
        return ("page_id", "message", "photo", "published")
    if image.image_url:
        return ("page_id", "message", "url", "published")
    return ("page_id", "message", "published")


def _execution_request(
    *,
    provider_slug: str,
    action_slug: str,
    mutation: str,
    approval_token_present: bool = False,
    preview_evidence_id: str | None = None,
    preview_evidence_required: bool = False,
    argument_keys: tuple[str, ...] = (),
) -> WiiiConnectExecutionRequest:
    return WiiiConnectExecutionRequest(
        provider_slug=_provider_slug(provider_slug),
        action_slug=str(action_slug or "").strip().upper().replace("-", "_")[:120],
        path="external_app_action",
        mutation=mutation if mutation in {"read", "preview", "write", "apply", "admin"} else "read",  # type: ignore[arg-type]
        approval_token_present=approval_token_present,
        preview_evidence_id=preview_evidence_id,
        preview_evidence_required=preview_evidence_required,
        argument_keys=argument_keys,
    )


def _append_execution_audit(
    gateway: Any,
    request: WiiiConnectExecutionRequest,
    storage: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    metadata: dict[str, Any],
) -> None:
    _append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status=gateway.status,
        reason=gateway.reason,
        metadata=metadata,
    )


def _append_execution_stage_audit(
    gateway: Any,
    request: WiiiConnectExecutionRequest,
    storage: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    status: str,
    reason: str,
    metadata: dict[str, Any],
) -> None:
    if not _audit_persistent(storage):
        return
    record = build_audit_ledger_record(
        event_kind="execution",
        provider_slug=gateway.decision.provider_slug,
        status=_safe_surface(status),
        reason=_safe_surface(reason),
        surface=_safe_surface(metadata.get("surface") or "backend"),
        metadata={
            "request": request.to_audit_metadata(),
            "decision": gateway.decision.to_metadata(),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=_owner_organization_id(current_user),
        user_id=current_user.user_id,
    )


def _storage_status() -> dict[str, Any]:
    try:
        return (
            get_wiii_connect_persistent_storage()
            .status(probe_database=True)
            .to_public_metadata()
        )
    except Exception:
        return default_persistent_storage_status_metadata()


def _connection_storage_ready(storage: dict[str, Any]) -> bool:
    return bool(
        storage.get("persistent")
        and storage.get("connection_table_ready")
        and storage.get("audit_ledger_ready")
    )


def _audit_persistent(storage: dict[str, Any]) -> bool:
    return bool(storage.get("persistent") and storage.get("audit_ledger_ready"))


def _owner_organization_id(user: AuthenticatedUser) -> str:
    if user.organization_id:
        return user.organization_id
    return build_composio_external_user_id(
        organization_id=None,
        user_id=user.user_id,
    )


def _safe_public_connection_ref(value: str | None) -> str:
    text = str(value or "").strip()
    if text.startswith("wcn_"):
        return text[:160]
    return ""


def _missing_required_argument_keys(
    *,
    required_keys: tuple[str, ...],
    arguments: dict[str, Any],
) -> tuple[str, ...]:
    provided = {str(key or "").strip() for key in arguments.keys()}
    missing = []
    for raw_key in required_keys:
        key = str(raw_key or "").strip()
        if key and key not in provided:
            missing.append(key[:80])
    return tuple(missing[:50])


def _provider_slug(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:_MAX_SURFACE_LEN] or "backend"


def _success(
    summary: str,
    *,
    provider_slug: str,
    action_slug: str,
    page_id: str,
    gateway: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION,
        "status": "action_completed",
        "action": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        "success": True,
        "summary": summary,
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "page_id": page_id,
        "gateway": gateway,
        "execution": execution,
        "storage": storage,
        "data": data or {},
    }


def _failure(
    reason: str,
    *,
    provider_slug: str = "facebook",
    action_slug: str = "",
    gateway: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    upload: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    connection_ref_present: bool | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION,
        "status": "action_failed",
        "action": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        "success": False,
        "summary": f"Facebook chưa đăng: {_safe_surface(reason)}",
        "error": _safe_surface(reason),
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "gateway": gateway,
        "schema": schema,
        "upload": upload,
        "execution": execution,
        "storage": storage,
        "action_catalog": action_catalog_public_metadata(
            provider_slug=provider_slug,
            enabled_slugs=(),
        ),
        "data": data or {},
    }
    if connection_ref_present is not None:
        payload["connection_ref_present"] = connection_ref_present
    return payload


__all__ = [
    "WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION",
    "WiiiConnectFacebookPostDirectApplyInput",
    "execute_wiii_connect_facebook_post_direct_apply",
    "make_wiii_connect_facebook_post_direct_apply_tool",
]
