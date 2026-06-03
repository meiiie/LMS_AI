"""Shared support helpers for chat history endpoints."""

from fastapi import status
from fastapi.responses import JSONResponse

from app.api.v1 import chat_endpoint_presenter as _chat_endpoint_presenter
from app.core.security import is_platform_admin

build_chat_api_error_response = _chat_endpoint_presenter.build_chat_api_error_response

__all__ = [
    "ensure_chat_history_access_allowed",
    "ensure_delete_chat_history_allowed",
    "load_chat_history_page",
    "delete_chat_history_records",
    "process_get_chat_history_request",
    "process_delete_chat_history_request",
    "build_chat_history_operation_error_response",
]


def ensure_chat_history_access_allowed(
    *,
    auth,
    user_id: str,
) -> JSONResponse | None:
    """Return a standard error response when history access is not allowed."""
    if not is_platform_admin(auth) and auth.user_id != user_id:
        return build_chat_api_error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error="permission_denied",
            message="Bạn chỉ có thể xem lịch sử của chính mình.",
        )
    return None


def ensure_delete_chat_history_allowed(
    *,
    auth,
    user_id: str,
) -> JSONResponse | None:
    """Return a standard error response when history deletion is not allowed."""
    if is_platform_admin(auth):
        return None
    if auth.user_id == user_id:
        return None
    return build_chat_api_error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        error="permission_denied",
        message=(
            "Permission denied. Users can only delete their own "
            "chat history."
        ),
    )


def load_chat_history_page(
    *,
    user_id: str,
    limit: int,
    offset: int,
    organization_id: str | None = None,
):
    """Load paginated chat history from the repository."""
    from app.repositories.chat_history_repository import get_chat_history_repository

    chat_history_repo = get_chat_history_repository()
    return chat_history_repo.get_user_history(
        user_id,
        limit,
        offset,
        organization_id=organization_id,
    )


def delete_chat_history_records(
    *,
    user_id: str,
    organization_id: str | None = None,
) -> int:
    """Delete all chat history for a user via the repository."""
    from app.repositories.chat_history_repository import get_chat_history_repository

    chat_history_repo = get_chat_history_repository()
    return chat_history_repo.delete_user_history(
        user_id,
        organization_id=organization_id,
    )


def process_get_chat_history_request(
    *,
    logger,
    user_id: str,
    limit: int,
    offset: int,
    organization_id: str | None = None,
):
    """Load, shape, and log the standard get-history response."""
    limit, offset = _chat_endpoint_presenter.normalize_history_pagination(
        limit,
        offset,
    )
    messages, total = load_chat_history_page(
        user_id=user_id,
        limit=limit,
        offset=offset,
        organization_id=organization_id,
    )
    response = _chat_endpoint_presenter.build_get_chat_history_response(
        messages=messages,
        total=total,
        limit=limit,
        offset=offset,
    )
    _chat_endpoint_presenter.log_get_chat_history_response(
        logger=logger,
        message_count=len(response.data),
        user_id=user_id,
        total=total,
    )
    return response


def process_delete_chat_history_request(
    *,
    logger,
    user_id: str,
    deleted_by: str,
    role: str,
    organization_id: str | None = None,
):
    """Delete, shape, and log the standard delete-history response."""
    deleted_count = delete_chat_history_records(
        user_id=user_id,
        organization_id=organization_id,
    )
    _chat_endpoint_presenter.log_delete_chat_history_response(
        logger=logger,
        deleted_count=deleted_count,
        user_id=user_id,
        deleted_by=deleted_by,
        role=role,
    )
    return _chat_endpoint_presenter.build_delete_chat_history_response(
        user_id=user_id,
        deleted_count=deleted_count,
        deleted_by=deleted_by,
    )


def build_chat_history_operation_error_response(
    *,
    logger,
    operation_label: str,
    error,
    message: str,
) -> JSONResponse:
    """Log and build the standard failure payload for history endpoints."""
    return _chat_endpoint_presenter.build_logged_chat_api_error_response(
        logger=logger,
        operation_label=operation_label,
        error=error,
        error_code="internal_error",
        message=message,
    )
