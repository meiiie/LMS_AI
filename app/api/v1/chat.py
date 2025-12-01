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
    TODO: Use LLM to generate more relevant questions.
    """
    # Default suggestions based on common maritime topics
    default_suggestions = [
        "Bạn có thể giải thích thêm về quy tắc này không?",
        "Có ví dụ thực tế nào về tình huống này không?",
        "Quy tắc nào liên quan đến vấn đề này?"
    ]
    
    # Topic-based suggestions
    if "colreg" in user_message.lower() or "quy tắc" in user_message.lower():
        return [
            "Tàu nào phải nhường đường trong tình huống này?",
            "Khi nào áp dụng quy tắc này?",
            "Có ngoại lệ nào cho quy tắc này không?"
        ]
    elif "solas" in user_message.lower() or "an toàn" in user_message.lower():
        return [
            "Yêu cầu về thiết bị cứu sinh là gì?",
            "Quy định về huấn luyện thủy thủ đoàn?",
            "Kiểm tra an toàn định kỳ như thế nào?"
        ]
    elif "marpol" in user_message.lower() or "ô nhiễm" in user_message.lower():
        return [
            "Quy định về xả thải dầu là gì?",
            "Vùng biển đặc biệt có quy định gì?",
            "Xử phạt vi phạm MARPOL như thế nào?"
        ]
    
    return default_suggestions


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
