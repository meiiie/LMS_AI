"""Transport helpers for chat context management endpoints."""

from fastapi import status
from fastapi.responses import JSONResponse

from app.api.v1.chat_api_response_support import build_json_response
from app.api.v1 import chat_endpoint_presenter as _chat_endpoint_presenter

__all__ = [
    "get_context_session_id",
    "resolve_context_session_request",
    "build_missing_context_session_response",
    "load_recent_history_payload",
    "compact_context_session",
    "clear_context_session",
    "load_context_info_inputs",
    "build_context_operation_error_response",
    "build_context_compacted_response",
    "build_context_cleared_response",
    "build_context_info_response",
]


def get_context_session_id(*, request) -> str:
    """Extract the context session id from the standard request header."""
    return request.headers.get("X-Session-ID", "")


def resolve_context_session_request(*, request) -> tuple[str, JSONResponse | None]:
    """Return the context session id or the standard missing-session response."""
    session_id = get_context_session_id(request=request)
    if not session_id:
        return "", build_missing_context_session_response()
    return session_id, None


def build_missing_context_session_response() -> JSONResponse:
    """Build the standard missing-session payload for context endpoints."""
    return _chat_endpoint_presenter.build_missing_session_response()


def load_recent_history_payload(
    *,
    chat_history,
    session_id: str,
    user_id: str,
    organization_id: str | None = None,
) -> list[dict[str, str]]:
    """Load recent chat history into the compact context payload shape."""
    history_list: list[dict[str, str]] = []
    if chat_history.is_available():
        recent = chat_history.get_recent_messages(
            session_id,
            user_id=user_id,
            organization_id=organization_id,
        )
        history_list = [{"role": m.role, "content": m.content} for m in recent]
    return history_list


async def compact_context_session(
    *,
    session_id: str,
    user_id: str,
    organization_id: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Run the context compactor with the standard history-loading flow."""
    from app.engine.context_manager import get_compactor
    from app.repositories.chat_history_repository import get_chat_history_repository

    compactor = get_compactor()
    chat_history = get_chat_history_repository()
    history_list = load_recent_history_payload(
        chat_history=chat_history,
        session_id=session_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    summary = await compactor.force_compact(
        session_id,
        history_list,
        user_id=user_id,
    )
    return summary, history_list


def clear_context_session(*, session_id: str, user_id: str) -> None:
    """Clear running summary and summarizer state for a chat session."""
    from app.engine.context_manager import get_compactor
    from app.engine.memory_summarizer import get_memory_summarizer

    compactor = get_compactor()
    summarizer = get_memory_summarizer()
    compactor.clear_session(session_id, user_id=user_id)
    summarizer.clear_session(session_id)


def load_context_info_inputs(
    *,
    session_id: str,
    user_id: str,
    organization_id: str | None = None,
):
    """Load the standard compactor and history payload for context info."""
    from app.engine.context_manager import get_compactor
    from app.repositories.chat_history_repository import get_chat_history_repository

    compactor = get_compactor()
    chat_history = get_chat_history_repository()
    history_list = load_recent_history_payload(
        chat_history=chat_history,
        session_id=session_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    return compactor, history_list


def build_context_operation_error_response(
    *,
    logger,
    operation_label: str,
    error,
    error_code: str,
    message: str,
) -> JSONResponse:
    """Log and build the standard failure payload for context endpoints."""
    return _chat_endpoint_presenter.build_logged_chat_api_error_response(
        logger=logger,
        operation_label=operation_label,
        error=error,
        error_code=error_code,
        message=message,
    )


def build_context_compacted_response(
    *,
    session_id: str,
    summary: str,
    history_list: list[dict[str, str]],
) -> JSONResponse:
    """Build the standard successful compact-context response payload."""
    return build_json_response(
        status_code=status.HTTP_200_OK,
        content={
            "status": "compacted",
            "session_id": session_id,
            "summary_length": len(summary),
            "messages_summarized": max(0, len(history_list) - 4),
            "message": "Hội thoại đã được tóm tắt thành công.",
        },
    )


def build_context_cleared_response(*, session_id: str) -> JSONResponse:
    """Build the standard successful clear-context response payload."""
    return build_json_response(
        status_code=status.HTTP_200_OK,
        content={
            "status": "cleared",
            "session_id": session_id,
            "message": "Context đã được xóa. Bắt đầu cuộc trò chuyện mới.",
        },
    )


def build_context_info_response(*, info: dict) -> JSONResponse:
    """Build the standard successful context-info response payload."""
    return build_json_response(
        status_code=status.HTTP_200_OK,
        content=info,
    )
