"""
Chat API Endpoint for LMS Integration
Requirements: 1.1, 1.2, 1.4
Spec: CHỈ THỊ KỸ THUẬT SỐ 03, SỐ 04

POST /api/v1/chat - Main chat endpoint for LMS integration
"""
import logging
import time
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import RequireAuth
from app.core.config import settings
from app.core.rate_limit import chat_rate_limit, limiter
from app.models.schemas import (
    AgentType,
    ChatRequest,
    ChatResponse,
    ChatResponseData,
    ChatResponseMetadata,
    SourceInfo,
    ErrorResponse,
    Source,
    UserRole,
    DeleteHistoryRequest,
    DeleteHistoryResponse,
    GetHistoryResponse,
    HistoryMessage,
    HistoryPagination,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


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
    """
    start_time = time.time()
    
    logger.info(
        f"Chat request from user {chat_request.user_id} "
        f"(role: {chat_request.role.value}, auth: {auth.auth_method}): "
        f"{chat_request.message[:50]}..."
    )
    
    try:
        # Process through integrated ChatService with role-based prompting
        # Use BackgroundTasks to save chat history without blocking response
        # Spec: CHỈ THỊ KỸ THUẬT SỐ 04
        from app.services.chat_service import get_chat_service
        
        chat_service = get_chat_service()
        internal_response = await chat_service.process_message(
            chat_request,
            background_save=background_tasks.add_task
        )
        
        processing_time = time.time() - start_time
        
        # Convert sources to LMS format
        sources = []
        if internal_response.sources:
            for src in internal_response.sources:
                sources.append(SourceInfo(
                    title=src.title,
                    content=src.content_snippet or ""
                ))
        
        # Generate suggested questions based on context
        suggested_questions = _generate_suggested_questions(
            chat_request.message, 
            internal_response.message
        )
        
        # Build LMS-compatible response
        response = ChatResponse(
            status="success",
            data=ChatResponseData(
                answer=internal_response.message,
                sources=sources,
                suggested_questions=suggested_questions
            ),
            metadata=ChatResponseMetadata(
                processing_time=round(processing_time, 3),
                model="maritime-rag-v1",
                agent_type=internal_response.agent_type
            )
        )
        
        logger.info(
            f"Chat response generated in {processing_time:.3f}s "
            f"(agent: {internal_response.agent_type.value})"
        )
        
        return response
        
    except Exception as e:
        logger.exception(f"Error processing chat request: {e}")
        # Return JSON error response (không để 500 lộ ra ngoài)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "code": 500,
                "message": f"Lỗi xử lý request: {str(e)}"
            }
        )


def _generate_suggested_questions(user_message: str, ai_response: str) -> list[str]:
    """
    Generate 3 suggested follow-up questions based on context.
    
    Logic:
    1. Detect maritime topic from user message
    2. Return topic-specific suggestions
    3. If no maritime topic detected, return general maritime suggestions
       (not generic "quy tắc" suggestions for non-maritime queries)
    """
    user_lower = user_message.lower()
    response_lower = ai_response.lower()
    
    # Check if this is a maritime-related query
    maritime_keywords = [
        'colreg', 'solas', 'marpol', 'stcw', 'quy tắc', 'rule',
        'tàu', 'thuyền', 'hàng hải', 'biển', 'maritime', 'vessel',
        'navigation', 'safety', 'an toàn', 'thuyền viên', 'seafarer'
    ]
    
    is_maritime_query = any(kw in user_lower for kw in maritime_keywords)
    
    # Topic-based suggestions for maritime queries
    if "colreg" in user_lower or "quy tắc" in user_lower or "rule" in user_lower:
        return [
            "Tàu nào phải nhường đường trong tình huống này?",
            "Khi nào áp dụng quy tắc này?",
            "Có ngoại lệ nào cho quy tắc này không?"
        ]
    elif "solas" in user_lower or ("an toàn" in user_lower and is_maritime_query):
        return [
            "Yêu cầu về thiết bị cứu sinh là gì?",
            "Quy định về huấn luyện thủy thủ đoàn?",
            "Kiểm tra an toàn định kỳ như thế nào?"
        ]
    elif "marpol" in user_lower or "ô nhiễm" in user_lower:
        return [
            "Quy định về xả thải dầu là gì?",
            "Vùng biển đặc biệt có quy định gì?",
            "Xử phạt vi phạm MARPOL như thế nào?"
        ]
    elif is_maritime_query:
        # General maritime suggestions
        return [
            "Bạn muốn tìm hiểu thêm về quy định nào?",
            "Có câu hỏi nào khác về hàng hải không?",
            "Bạn cần giải thích chi tiết hơn không?"
        ]
    else:
        # Non-maritime query - return empty or generic helpful suggestions
        return [
            "Bạn có câu hỏi nào về hàng hải không?",
            "Tôi có thể giúp gì về COLREGs, SOLAS, hoặc MARPOL?",
            "Bạn muốn tìm hiểu về quy định hàng hải nào?"
        ]


@router.get(
    "/status",
    summary="Chat Service Status",
    description="Check if the chat service is available",
)
async def chat_status():
    """Get chat service status"""
    return {
        "service": "chat",
        "status": "available",
        "agents": ["chat", "rag", "tutor"],
    }


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
    try:
        # Validate limit
        if limit > 100:
            limit = 100
        if limit < 1:
            limit = 20
        if offset < 0:
            offset = 0
        
        # Get history from repository
        from app.repositories.chat_history_repository import get_chat_history_repository
        
        chat_history_repo = get_chat_history_repository()
        messages, total = chat_history_repo.get_user_history(user_id, limit, offset)
        
        # Convert to response format
        history_messages = [
            HistoryMessage(
                role=msg.role,
                content=msg.content,
                timestamp=msg.created_at
            )
            for msg in messages
        ]
        
        logger.info(f"Retrieved {len(history_messages)} messages for user {user_id} (total: {total})")
        
        return GetHistoryResponse(
            data=history_messages,
            pagination=HistoryPagination(
                total=total,
                limit=limit,
                offset=offset
            )
        )
        
    except Exception as e:
        logger.exception(f"Error retrieving chat history: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": f"Failed to retrieve chat history: {str(e)}"
            }
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
        # Check permissions
        if request.role == "admin":
            # Admin can delete any user's history
            pass
        elif request.role in ["student", "teacher"]:
            # Users can only delete their own history
            if request.requesting_user_id != user_id:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "error": "permission_denied",
                        "message": "Permission denied. Users can only delete their own chat history."
                    }
                )
        else:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "invalid_role",
                    "message": "Permission denied. Invalid role."
                }
            )
        
        # Delete from chat history repository
        from app.repositories.chat_history_repository import get_chat_history_repository
        
        chat_history_repo = get_chat_history_repository()
        deleted_count = chat_history_repo.delete_user_history(user_id)
        
        logger.info(
            f"Deleted {deleted_count} chat messages for user {user_id} "
            f"by {request.requesting_user_id} ({request.role})"
        )
        
        return DeleteHistoryResponse(
            status="deleted",
            user_id=user_id,
            messages_deleted=deleted_count,
            deleted_by=request.requesting_user_id
        )
        
    except Exception as e:
        logger.exception(f"Error deleting chat history: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": f"Failed to delete chat history: {str(e)}"
            }
        )
