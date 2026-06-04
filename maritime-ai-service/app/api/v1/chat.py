"""
Chat API Endpoint for LMS Integration
Requirements: 1.1, 1.2, 1.4
Spec: CHỈ THỊ KỸ THUẬT SỐ 03, SỐ 04

POST /api/v1/chat - Main chat endpoint for LMS integration

Authoritative request flow:
see app/services/REQUEST_FLOW_CONTRACT.md
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.api.deps import RequireAuth
from app.api.v1 import (
    chat_completion_endpoint_support as _chat_completion_support,
)
from app.api.v1 import chat_context_endpoint_support as _chat_context_support
from app.api.v1 import chat_endpoint_presenter as _chat_endpoint_presenter
from app.api.v1 import chat_history_endpoint_support as _chat_history_support
from app.core.config import settings
from app.core.security import resolve_interaction_role
from app.core.rate_limit import limiter
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.models.host_context_schemas import sanitize_user_context_for_ingress
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    DeleteHistoryRequest,
    DeleteHistoryResponse,
    GetHistoryResponse,
    UserRole,
)
from app.services import chat_response_presenter as _chat_response_presenter


# Compatibility re-exports kept for tests that still import these helpers
# directly from app.api.v1.chat.
build_chat_response = _chat_response_presenter.build_chat_response
_classify_query_type = _chat_response_presenter.classify_query_type
_generate_suggested_questions = _chat_response_presenter.generate_suggested_questions
_get_tool_description = _chat_response_presenter.get_tool_description

__all__ = [
    "router",
    "chat_completion",
    "get_chat_history",
    "delete_chat_history",
    "compact_context",
    "clear_context",
    "get_context_info",
    "build_chat_response",
    "_classify_query_type",
    "_generate_suggested_questions",
    "_get_tool_description",
]

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


def _canonicalize_chat_request_from_auth(chat_request: ChatRequest, auth: RequireAuth) -> ChatRequest:
    """Project canonical auth identity onto transport request fields."""
    effective_role = resolve_interaction_role(auth)
    effective_org_id = auth.organization_id
    if (
        not effective_org_id
        and not (
            settings.enable_multi_tenant
            and settings.environment in ("production", "staging")
        )
    ):
        effective_org_id = chat_request.organization_id
    return chat_request.model_copy(
        update={
            "user_id": str(auth.user_id),
            "role": UserRole(effective_role),
            "organization_id": effective_org_id,
            "user_context": sanitize_user_context_for_ingress(chat_request.user_context),
        }
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {"description": "Validation error - thiếu trường bắt buộc"},
        401: {"description": "Authentication required - thiếu X-API-Key"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
    },
    summary="Chat Completion (LMS Integration)",
    description="""
    **Endpoint chính cho LMS Hàng Hải gọi vào.**
    
    Nhận câu hỏi từ LMS, xử lý qua RAG/Memory, trả về câu trả lời JSON.
    
    **Role-Based Prompting:**
    - `student`: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
    - `teacher`/`admin`: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
    
    **Requirements: 1.1, 1.2, 1.4**
    **Spec: CHỈ THỊ KỸ THUẬT SỐ 03**
    """,
)
@limiter.limit("30/minute")
async def chat_completion(
    request: Request,
    chat_request: ChatRequest,
    auth: RequireAuth,
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    """
    Process a chat completion request from LMS.
    
    Args:
        request: FastAPI request object (for rate limiting)
        chat_request: The chat request payload with user_id, message, role
        auth: Authenticated via X-API-Key header
    
    Returns:
        ChatResponse with status, data (answer, sources, suggested_questions), metadata

    Contract note:
        This endpoint is transport-only. The authoritative business flow from
        session normalization through continuity scheduling is documented in
        app/services/REQUEST_FLOW_CONTRACT.md.
    """
    chat_request = _canonicalize_chat_request_from_auth(chat_request, auth)

    start_time, request_id = _chat_completion_support.begin_chat_completion_request(
        logger=logger,
        request=request,
        chat_request=chat_request,
        auth_method=auth.auth_method,
    )

    try:
        internal_response = await (
            _chat_completion_support.process_chat_completion_request(
                chat_request=chat_request,
                background_save=background_tasks.add_task,
            )
        )

        runtime_metadata = resolve_runtime_llm_metadata(
            internal_response.metadata or {},
            allow_fallback=False,
        )

        return _chat_endpoint_presenter.build_chat_completion_success_response(
            logger=logger,
            chat_request=chat_request,
            internal_response=internal_response,
            start_time=start_time,
            provider_name=runtime_metadata["provider"],
            model_name=runtime_metadata["model"],
            runtime_authoritative=bool(runtime_metadata["runtime_authoritative"]),
        )
    except Exception as error:
        return _chat_endpoint_presenter.build_chat_completion_error_response(
            logger=logger,
            error=error,
            request_id=request_id,
        )


@router.get(
    "/history/{user_id}",
    response_model=GetHistoryResponse,
    responses={
        200: {"description": "Chat history retrieved successfully"},
        401: {"description": "Authentication required", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse}
    },
    summary="Get user chat history (Phase 2)",
    description="""
    **Lấy lịch sử chat của một user với phân trang.**
    
    Hỗ trợ đồng bộ hóa đa thiết bị trong Phase 2.
    
    **Query Parameters:**
    - `limit`: Số tin nhắn trả về (default: 20, max: 100)
    - `offset`: Vị trí bắt đầu (default: 0)
    
    **Spec: CHỈ THỊ KỸ THUẬT SỐ 11**
    """
)
async def get_chat_history(
    user_id: str,
    auth: RequireAuth,
    limit: int = 20,
    offset: int = 0,
) -> GetHistoryResponse:
    """
    Get paginated chat history for a user.
    
    Args:
        user_id: ID of user whose history to retrieve
        auth: Authenticated via X-API-Key header
        limit: Number of messages to return (default 20, max 100)
        offset: Offset for pagination (default 0)
    
    Returns:
        GetHistoryResponse with messages and pagination info
    """
    permission_error = _chat_history_support.ensure_chat_history_access_allowed(
        auth=auth,
        user_id=user_id,
    )
    if permission_error is not None:
        return permission_error

    try:
        return _chat_history_support.process_get_chat_history_request(
            logger=logger,
            user_id=user_id,
            limit=limit,
            offset=offset,
            organization_id=auth.organization_id,
        )

    except Exception as error:
        return _chat_history_support.build_chat_history_operation_error_response(
            logger=logger,
            operation_label="retrieving chat history",
            error=error,
            message="Failed to retrieve chat history",
        )


@router.delete(
    "/history/{user_id}",
    response_model=DeleteHistoryResponse,
    responses={
        200: {"description": "Chat history deleted successfully"},
        403: {"description": "Permission denied", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse}
    },
    summary="Delete user chat history",
    description="""
    **Xóa toàn bộ lịch sử chat của một user.**
    
    **Access Control:**
    - `admin`: Có thể xóa lịch sử của bất kỳ user nào
    - `student`/`teacher`: Chỉ có thể xóa lịch sử của chính mình
    """
)
async def delete_chat_history(
    user_id: str,
    request: DeleteHistoryRequest,
    auth: RequireAuth,
) -> DeleteHistoryResponse:
    """
    Delete chat history for a user.
    
    Args:
        user_id: ID of user whose history to delete
        request: Contains role and requesting_user_id
        auth: Authenticated via X-API-Key header
    
    Returns:
        DeleteHistoryResponse with status and count of deleted messages
    """
    try:
        permission_error = _chat_history_support.ensure_delete_chat_history_allowed(
            auth=auth,
            user_id=user_id,
        )
        if permission_error is not None:
            return permission_error

        return _chat_history_support.process_delete_chat_history_request(
            logger=logger,
            user_id=user_id,
            deleted_by=auth.user_id,
            role=resolve_interaction_role(auth),
            organization_id=auth.organization_id,
        )

    except Exception as error:
        return _chat_history_support.build_chat_history_operation_error_response(
            logger=logger,
            operation_label="deleting chat history",
            error=error,
            message="Failed to delete chat history",
        )


# =============================================================================
# Sprint 78: Context Management API — User controls for conversation context
# SOTA Reference: Claude /compact, /clear, /context commands
# =============================================================================


@router.post(
    "/context/compact",
    summary="Compact conversation context",
    description="""
    **Tóm tắt lịch sử hội thoại để giải phóng context window.**

    Tương đương `/compact` trong Claude Code.
    Giữ lại 4 tin nhắn gần nhất, tóm tắt phần còn lại thành running summary.
    """,
    responses={
        200: {"description": "Context compacted successfully"},
        401: {"description": "Authentication required"},
    },
)
@limiter.limit("10/minute")
async def compact_context(
    request: Request,
    auth: RequireAuth,
) -> JSONResponse:
    """Compact conversation context — summarize older turns."""
    user_id = auth.user_id
    session_id, missing_session_response = (
        _chat_context_support.resolve_context_session_request(request=request)
    )
    if missing_session_response is not None:
        return missing_session_response

    try:
        summary, history_list = await _chat_context_support.compact_context_session(
            session_id=session_id,
            user_id=user_id,
            organization_id=auth.organization_id,
        )

        return _chat_context_support.build_context_compacted_response(
            session_id=session_id,
            summary=summary,
            history_list=history_list,
        )

    except Exception as error:
        return _chat_context_support.build_context_operation_error_response(
            logger=logger,
            operation_label="compacting context",
            error=error,
            error_code="compact_failed",
            message="Failed to compact context",
        )


@router.post(
    "/context/clear",
    summary="Clear conversation context",
    description="""
    **Xóa toàn bộ context hội thoại và bắt đầu cuộc trò chuyện mới.**

    Tương đương `/clear` trong Claude Code.
    Xóa running summary, memory state, nhưng KHÔNG xóa user facts (Core Memory).
    """,
    responses={
        200: {"description": "Context cleared successfully"},
        401: {"description": "Authentication required"},
    },
)
@limiter.limit("10/minute")
async def clear_context(
    request: Request,
    auth: RequireAuth,
) -> JSONResponse:
    """Clear conversation context — start fresh (preserves user facts)."""
    user_id = auth.user_id  # Sprint 79: needed for DB cleanup
    session_id, missing_session_response = (
        _chat_context_support.resolve_context_session_request(request=request)
    )
    if missing_session_response is not None:
        return missing_session_response

    try:
        _chat_context_support.clear_context_session(
            session_id=session_id,
            user_id=user_id,
        )

        return _chat_context_support.build_context_cleared_response(
            session_id=session_id,
        )

    except Exception as error:
        return _chat_context_support.build_context_operation_error_response(
            logger=logger,
            operation_label="clearing context",
            error=error,
            error_code="clear_failed",
            message="Failed to clear context",
        )


@router.get(
    "/context/info",
    summary="Get context usage info",
    description="""
    **Xem thông tin sử dụng context window.**

    Tương đương `/context list` trong Claude Code / OpenClawd `/status`.
    Hiển thị: token budget, utilization, số tin nhắn, running summary.
    """,
    responses={
        200: {"description": "Context info retrieved"},
        401: {"description": "Authentication required"},
    },
)
@limiter.limit("30/minute")
async def get_context_info(
    request: Request,
    auth: RequireAuth,
) -> JSONResponse:
    """Get context usage info for introspection."""
    user_id = auth.user_id
    session_id, missing_session_response = (
        _chat_context_support.resolve_context_session_request(request=request)
    )
    if missing_session_response is not None:
        return missing_session_response

    try:
        compactor, history_list = _chat_context_support.load_context_info_inputs(
            session_id=session_id,
            user_id=user_id,
            organization_id=auth.organization_id,
        )

        # Sprint 210g: Fetch system_prompt + core_memory for accurate layer display
        _system_prompt = ""
        _core_memory = ""
        try:
            from app.prompts.prompt_loader import get_prompt_loader
            loader = get_prompt_loader()
            _system_prompt = loader.build_system_prompt(
                role=resolve_interaction_role(auth),
            )
        except Exception:
            pass
        try:
            from app.engine.semantic_memory.core_memory_block import get_core_memory_block
            from app.engine.semantic_memory import get_semantic_memory_engine
            core_block = get_core_memory_block()
            sem_engine = get_semantic_memory_engine()
            if sem_engine.is_available():
                _core_memory = await core_block.get_block(
                    user_id=user_id,
                    semantic_memory=sem_engine,
                )
        except Exception:
            pass

        info = compactor.get_context_info(
            session_id=session_id,
            history_list=history_list,
            system_prompt=_system_prompt,
            core_memory=_core_memory or "",
            user_id=user_id,
        )

        return _chat_context_support.build_context_info_response(info=info)

    except Exception as error:
        return _chat_context_support.build_context_operation_error_response(
            logger=logger,
            operation_label="getting context info",
            error=error,
            error_code="info_failed",
            message="Failed to get context info",
        )
