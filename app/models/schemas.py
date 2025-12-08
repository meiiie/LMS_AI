"""
Pydantic Schemas for API Request/Response
Requirements: 1.1, 1.5, 1.6
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    """Get current UTC time (timezone-aware)"""
    return datetime.now(timezone.utc)


class AgentType(str, Enum):
    """Type of agent that processed the request"""
    CHAT = "chat"
    RAG = "rag"
    TUTOR = "tutor"


class IntentType(str, Enum):
    """Classification of user intent"""
    GENERAL = "general"
    KNOWLEDGE = "knowledge"
    TEACHING = "teaching"


class ComponentStatus(str, Enum):
    """Status of a system component"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


# =============================================================================
# Chat Request/Response Schemas
# =============================================================================

class UserRole(str, Enum):
    """User role from LMS"""
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class ChatRequest(BaseModel):
    """
    Chat request payload from LMS Core
    Requirements: 1.1, 1.5
    Spec: CHỈ THỊ KỸ THUẬT SỐ 03
    """
    user_id: str = Field(..., description="BẮT BUỘC: ID user từ LMS (để map lịch sử chat)")
    message: str = Field(..., min_length=1, max_length=10000, description="BẮT BUỘC: Câu hỏi người dùng")
    role: UserRole = Field(..., description="BẮT BUỘC: student | teacher | admin")
    session_id: Optional[str] = Field(default=None, description="Tùy chọn: ID phiên học (nếu có)")
    context: Optional[dict[str, Any]] = Field(
        default=None, 
        description="Tùy chọn: Dữ liệu ngữ cảnh thêm (course_id, lesson_id, etc.)"
    )
    
    @field_validator("message")
    @classmethod
    def validate_message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v.strip()
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "student_12345",
                    "session_id": "session_abc123",
                    "message": "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
                    "role": "student",
                    "context": {
                        "course_id": "COLREGs_101"
                    }
                }
            ]
        }
    }



class Source(BaseModel):
    """Source citation from Knowledge Graph"""
    node_id: str = Field(..., description="Knowledge Graph node ID")
    title: str = Field(..., description="Source title")
    source_type: str = Field(..., description="Type: regulation, concept, etc.")
    content_snippet: Optional[str] = Field(default=None, description="Relevant content snippet")


class SourceInfo(BaseModel):
    """Source citation info for LMS response"""
    title: str = Field(..., description="Tiêu đề nguồn tài liệu")
    content: str = Field(..., description="Nội dung trích dẫn")


class ChatResponseData(BaseModel):
    """Data payload in chat response"""
    answer: str = Field(..., description="Câu trả lời của AI (Markdown format)")
    sources: list[SourceInfo] = Field(default_factory=list, description="Danh sách nguồn tài liệu tham khảo")
    suggested_questions: list[str] = Field(default_factory=list, description="3 câu hỏi gợi ý tiếp theo")


class ChatResponseMetadata(BaseModel):
    """Metadata in chat response"""
    processing_time: float = Field(..., description="Thời gian xử lý (giây)")
    model: str = Field(default="maritime-rag-v1", description="Model AI sử dụng")
    agent_type: AgentType = Field(default=AgentType.RAG, description="Agent xử lý request")


class ChatResponse(BaseModel):
    """
    Chat response payload to LMS Core
    Requirements: 1.1, 1.6
    Spec: CHỈ THỊ KỸ THUẬT SỐ 03
    """
    status: str = Field(default="success", description="success | error")
    data: ChatResponseData = Field(..., description="Dữ liệu response")
    metadata: ChatResponseMetadata = Field(..., description="Metadata response")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "data": {
                        "answer": "Theo Điều 15 COLREGs, khi hai tàu máy đi cắt hướng nhau...",
                        "sources": [
                            {
                                "title": "COLREGs Rule 15 - Crossing Situation",
                                "content": "When two power-driven vessels are crossing..."
                            }
                        ],
                        "suggested_questions": [
                            "Tàu nào phải nhường đường trong tình huống cắt hướng?",
                            "Quy tắc 16 về hành động của tàu nhường đường là gì?",
                            "Khi nào áp dụng quy tắc cắt hướng?"
                        ]
                    },
                    "metadata": {
                        "processing_time": 1.25,
                        "model": "maritime-rag-v1",
                        "agent_type": "rag"
                    }
                }
            ]
        }
    }


# Legacy response model (for internal use)
class InternalChatResponse(BaseModel):
    """Internal chat response (before formatting for LMS)"""
    response_id: UUID = Field(default_factory=uuid4, description="Unique response identifier")
    message: str = Field(..., description="AI-generated response message")
    agent_type: AgentType = Field(..., description="Agent that processed the request")
    sources: Optional[list[Source]] = Field(
        default=None, 
        description="Source citations for RAG responses"
    )
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional metadata (confidence, processing time, etc.)"
    )
    created_at: datetime = Field(default_factory=utc_now, description="Response timestamp")
    # CHỈ THỊ 26: Evidence Images for Multimodal RAG
    evidence_images: Optional[list["EvidenceImageSchema"]] = Field(
        default=None,
        description="Evidence images from document pages (CHỈ THỊ 26)"
    )


# =============================================================================
# Health Check Schemas
# =============================================================================

class ComponentHealth(BaseModel):
    """Health status of a single component"""
    name: str = Field(..., description="Component name")
    status: ComponentStatus = Field(..., description="Component status")
    latency_ms: Optional[float] = Field(default=None, description="Response latency in ms")
    message: Optional[str] = Field(default=None, description="Status message or error")


class HealthResponse(BaseModel):
    """
    Health check response
    Requirements: 8.4
    """
    status: str = Field(..., description="Overall system status")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Current environment")
    components: dict[str, ComponentHealth] = Field(
        ..., 
        description="Status of all components: API, Memory, Knowledge_Graph"
    )
    timestamp: datetime = Field(default_factory=utc_now, description="Check timestamp")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "healthy",
                    "version": "0.1.0",
                    "environment": "development",
                    "components": {
                        "api": {"name": "API", "status": "healthy", "latency_ms": 5.2},
                        "memory": {"name": "Memori Engine", "status": "healthy", "latency_ms": 12.5},
                        "knowledge_graph": {"name": "Neo4j", "status": "healthy", "latency_ms": 8.3}
                    }
                }
            ]
        }
    }


# =============================================================================
# Error Response Schemas
# =============================================================================

class ErrorDetail(BaseModel):
    """Detail of a validation or processing error"""
    field: Optional[str] = Field(default=None, description="Field that caused the error")
    message: str = Field(..., description="Error message")
    code: Optional[str] = Field(default=None, description="Error code")


class ErrorResponse(BaseModel):
    """Standard error response format"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[list[ErrorDetail]] = Field(default=None, description="Error details")
    request_id: Optional[str] = Field(default=None, description="Request ID for tracking")
    timestamp: datetime = Field(default_factory=utc_now, description="Error timestamp")


class RateLimitResponse(BaseModel):
    """Rate limit exceeded response"""
    error: str = Field(default="rate_limited", description="Error type")
    message: str = Field(default="Rate limit exceeded", description="Error message")
    retry_after: int = Field(..., description="Seconds until rate limit resets")


# =============================================================================
# Delete History Schemas
# =============================================================================

class DeleteHistoryRequest(BaseModel):
    """Request to delete chat history"""
    role: str = Field(..., description="Role of requesting user (admin, student, teacher)")
    requesting_user_id: str = Field(..., description="ID of user making the request")


class DeleteHistoryResponse(BaseModel):
    """Response after deleting chat history"""
    status: str = Field(default="deleted", description="Operation status")
    user_id: str = Field(..., description="ID of user whose history was deleted")
    messages_deleted: int = Field(..., description="Number of messages deleted")
    deleted_by: str = Field(..., description="ID of user who performed the deletion")


# =============================================================================
# Get History Schemas (Phase 2 - CHỈ THỊ KỸ THUẬT SỐ 11)
# =============================================================================

class HistoryMessage(BaseModel):
    """Single message in chat history"""
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., description="Nội dung tin nhắn")
    timestamp: datetime = Field(..., description="Thời gian gửi tin nhắn (ISO 8601)")


class HistoryPagination(BaseModel):
    """Pagination info for history response"""
    total: int = Field(..., description="Tổng số tin nhắn")
    limit: int = Field(..., description="Số tin nhắn trả về")
    offset: int = Field(..., description="Vị trí bắt đầu")


class GetHistoryResponse(BaseModel):
    """Response for GET /api/v1/history/{user_id}"""
    data: list[HistoryMessage] = Field(default_factory=list, description="Danh sách tin nhắn")
    pagination: HistoryPagination = Field(..., description="Thông tin phân trang")


# =============================================================================
# Multimodal RAG Schemas (CHỈ THỊ KỸ THUẬT SỐ 26)
# =============================================================================

class EvidenceImageSchema(BaseModel):
    """
    Evidence image reference for Multimodal RAG responses.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Vision-based Document Understanding
    **Feature: multimodal-rag-vision**
    **Validates: Requirements 6.2**
    """
    url: str = Field(..., description="Public URL của ảnh trang tài liệu")
    page_number: int = Field(..., description="Số trang trong tài liệu gốc")
    document_id: str = Field(default="", description="ID của tài liệu nguồn")


class IngestionResultSchema(BaseModel):
    """
    Result of PDF ingestion process.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Multimodal Ingestion Pipeline
    **Feature: multimodal-rag-vision**
    **Validates: Requirements 7.4**
    """
    document_id: str = Field(..., description="ID của tài liệu đã nạp")
    total_pages: int = Field(..., description="Tổng số trang")
    successful_pages: int = Field(..., description="Số trang xử lý thành công")
    failed_pages: int = Field(..., description="Số trang xử lý thất bại")
    errors: list[str] = Field(default_factory=list, description="Danh sách lỗi (nếu có)")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_pages == 0:
            return 0.0
        return (self.successful_pages / self.total_pages) * 100


class ExtractionResultSchema(BaseModel):
    """
    Result of Vision extraction from image.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Gemini Vision Extraction
    **Feature: multimodal-rag-vision**
    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    text: str = Field(..., description="Văn bản trích xuất từ ảnh")
    has_tables: bool = Field(default=False, description="Có chứa bảng biểu")
    has_diagrams: bool = Field(default=False, description="Có chứa sơ đồ/hình vẽ")
    headings_found: list[str] = Field(default_factory=list, description="Danh sách tiêu đề tìm thấy")
    success: bool = Field(default=True, description="Trích xuất thành công")
    error: Optional[str] = Field(default=None, description="Thông báo lỗi (nếu có)")
    processing_time: float = Field(default=0.0, description="Thời gian xử lý (giây)")


class MultimodalIngestRequest(BaseModel):
    """
    Request to ingest PDF document with Multimodal pipeline.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Multimodal Ingestion
    **Feature: multimodal-rag-vision**
    """
    document_id: str = Field(..., description="ID định danh cho tài liệu")
    resume: bool = Field(default=True, description="Tiếp tục từ trang cuối nếu bị gián đoạn")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "document_id": "colregs_2024",
                    "resume": True
                }
            ]
        }
    }


class ChatResponseDataWithEvidence(ChatResponseData):
    """
    Extended chat response data with evidence images.
    
    CHỈ THỊ KỸ THUẬT SỐ 26: Evidence Images in Response
    **Feature: multimodal-rag-vision**
    **Validates: Requirements 6.2**
    """
    evidence_images: list[EvidenceImageSchema] = Field(
        default_factory=list, 
        description="Danh sách ảnh dẫn chứng từ tài liệu gốc (tối đa 3)"
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "answer": "Theo Điều 15 COLREGs, khi hai tàu máy đi cắt hướng nhau...",
                    "sources": [
                        {
                            "title": "COLREGs Rule 15 - Crossing Situation",
                            "content": "When two power-driven vessels are crossing..."
                        }
                    ],
                    "suggested_questions": [
                        "Tàu nào phải nhường đường trong tình huống cắt hướng?"
                    ],
                    "evidence_images": [
                        {
                            "url": "https://xyz.supabase.co/storage/v1/object/public/maritime-docs/colregs/page_15.jpg",
                            "page_number": 15,
                            "document_id": "colregs_2024"
                        }
                    ]
                }
            ]
        }
    }
