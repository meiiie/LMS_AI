"""
Pydantic Schemas for API Request/Response
Requirements: 1.1, 1.5, 1.6
"""
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
from app.models.host_context_schemas import (
    ImageInput,
    PageContext,  # noqa: F401 - compatibility re-export
    StudentPageState,  # noqa: F401 - compatibility re-export
    UserContext,
    UserRole,
    utc_now,
)


class AgentType(str, Enum):
    """Type of agent that processed the request"""
    CHAT = "chat"
    RAG = "rag"
    TUTOR = "tutor"
    DIRECT = "direct"
    MEMORY = "memory"
    CODE_STUDIO = "code_studio"


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


class ChatRequest(BaseModel):
    """
    Chat request payload from LMS Core.

    v2.0: Added user_context for Contextual RAG pattern.
    Spec: AI_LMS_INTEGRATION_PROPOSAL.md
    Feature: ai-lms-integration-v2
    """
    user_id: str = Field(..., description="BẮT BUỘC: UUID user từ LMS")
    message: str = Field(..., min_length=1, max_length=10000, description="BẮT BUỘC: Câu hỏi người dùng")
    role: UserRole = Field(..., description="BẮT BUỘC: student | teacher | admin")
    session_id: Optional[str] = Field(default=None, description="Tùy chọn: ID phiên học")
    
    # v2.1: Thread-based sessions (like ChatGPT "New Chat")
    thread_id: Optional[str] = Field(
        default=None,
        description="Thread ID cho phiên hội thoại. Nếu None hoặc 'new', tạo thread mới. "
                    "User facts vẫn persist qua threads, chỉ chat history riêng."
    )
    
    # v2.0: User context from LMS for personalization
    user_context: Optional[UserContext] = Field(
        default=None,
        description="User context từ LMS cho personalization (Contextual RAG)"
    )

    # v3.0: Domain Plugin System (Wiii)
    domain_id: Optional[str] = Field(
        default=None,
        description="Domain ID cho domain-specific processing. "
                    "Nếu None, hệ thống tự detect từ query hoặc dùng default."
    )

    # v4.0: Multi-Organization (Sprint 24)
    organization_id: Optional[str] = Field(
        default=None,
        description="Organization ID. If None, uses auth header or default."
    )

    # v5.0: Adaptive Thinking Effort (Sprint 66)
    thinking_effort: Optional[Literal["low", "medium", "high", "max"]] = Field(
        default=None,
        description="Thinking effort level. Controls LLM reasoning depth and cost. "
                    "low=fast/cheap, medium=balanced (default), high=thorough, max=deepest reasoning."
    )

    # v9.0: Per-Request Provider Selection
    provider: Optional[Literal["auto", "google", "zhipu", "openai", "openrouter", "nvidia", "ollama"]] = Field(
        default=None,
        description="Provider for this request. 'auto'=system failover (default), "
                    "'google'=Gemini, 'zhipu'=GLM-5, 'openai'=OpenAI-compatible, "
                    "'openrouter'=OpenRouter, 'nvidia'=NVIDIA NIM, 'ollama'=local."
    )
    model: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Optional per-request model override. Best paired with an explicit provider.",
    )

    # v6.0: Preview Configuration (Sprint 166)
    show_previews: Optional[bool] = Field(default=None, description="Enable preview cards in streaming")
    preview_types: Optional[list[str]] = Field(default=None, description="Allowed preview types (document, product, web, link, code)")
    preview_max_count: Optional[int] = Field(default=None, ge=1, le=50, description="Max number of preview cards per response")

    # v7.0: Artifact Configuration (Sprint 167)
    enable_artifacts: Optional[bool] = Field(default=None, description="Enable interactive artifacts in streaming")

    # v8.0: Multimodal Vision Input (Sprint 179)
    images: Optional[list[ImageInput]] = Field(
        default=None,
        max_length=5,
        description="Optional images for multimodal chat. Max 5 images per request."
    )

    # Wiii Pointy v2.8: explicit `@plugin-name` mention force-bind.
    # Frontend parses `@wiii-pointy`, `@web-search`, `@visual-code-gen`
    # mentions từ chat input → set force_skills=[<canonical-id>, ...]
    # Backend bypass `_needs_pointy/_needs_news/_needs_legal` intent
    # gates và force-bind tools + inject SKILL bất kể keyword match.
    # Pattern chuẩn SOTA 2026: Cursor `@codebase`, GitHub Copilot
    # `@workspace`, Claude Code `@file`, Cline `@docs`.
    force_skills: Optional[list[str]] = Field(
        default=None,
        max_length=10,
        description="Explicit skill invocation từ @ mentions trong chat input. "
                    "Bypass keyword intent gating. Skill ids: 'wiii-pointy', "
                    "'web-search', 'visual-code-gen'."
    )

    # F18 Phase B (2026-05-07) — Pointy mode UX flag.
    # When True, every query is treated as UI-navigation intent: backend
    # auto-injects "wiii-pointy" into force_skills, forces tool_choice=
    # "tool_pointy_show" with enum-constrained selector. AI persona shifts
    # to "cursor agent" — terse, action-focused, always pointing.
    # Inspired by Cursor's agent-mode toggle + Claude Code --agent flag.
    pointy_mode: Optional[bool] = Field(
        default=False,
        description="When True, treat user as talking directly to the cursor. "
                    "Forces deterministic tool_pointy_show invocation per turn.",
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
                    "user_id": "550e8400-e29b-41d4-a716-446655440000",
                    "message": "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
                    "role": "student",
                    "session_id": "session-abc123",
                    "user_context": {
                        "display_name": "Minh",
                        "role": "student",
                        "current_course_id": "colregs_2024",
                        "current_module_id": "rule_13_15",
                        "progress_percent": 45.0,
                        "language": "vi"
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
    image_url: Optional[str] = Field(default=None, description="URL ảnh trang tài liệu (CHỈ THỊ 26)")
    page_number: Optional[int] = Field(default=None, description="Page number in PDF (Feature: source-highlight-citation)")
    document_id: Optional[str] = Field(default=None, description="Document ID for PDF reference (Feature: source-highlight-citation)")
    bounding_boxes: Optional[list[dict]] = Field(default=None, description="Normalized coordinates for text highlighting (Feature: source-highlight-citation)")


class SourceInfo(BaseModel):
    """Source citation info for LMS response"""
    title: str = Field(..., description="Tiêu đề nguồn tài liệu")
    content: str = Field(..., description="Nội dung trích dẫn")
    url: Optional[str] = Field(default=None, description="Public URL for web sources")
    source_type: Optional[str] = Field(default=None, description="Source type, e.g. web or document")
    image_url: Optional[str] = Field(default=None, description="URL ảnh trang tài liệu (CHỈ THỊ 26)")
    page_number: Optional[int] = Field(default=None, description="Page number in PDF (Feature: source-highlight-citation)")
    document_id: Optional[str] = Field(default=None, description="Document ID for PDF reference (Feature: source-highlight-citation)")
    bounding_boxes: Optional[list[dict]] = Field(default=None, description="Normalized coordinates for text highlighting (Feature: source-highlight-citation)")


class ChatResponseData(BaseModel):
    """Data payload in chat response"""
    answer: str = Field(..., description="Câu trả lời của AI (Markdown format)")
    sources: list[SourceInfo] = Field(default_factory=list, description="Danh sách nguồn tài liệu tham khảo")
    suggested_questions: list[str] = Field(default_factory=list, description="3 câu hỏi gợi ý tiếp theo")
    domain_notice: Optional[str] = Field(default=None, description="Thông báo nhẹ nhàng khi nội dung ngoài domain chuyên môn")


class ToolUsageInfo(BaseModel):
    """
    Information about a tool that was used during processing.
    
    CHỈ THỊ KỸ THUẬT SỐ 27: API Transparency
    **Feature: api-transparency-thinking**
    **Validates: Requirements 1.3**
    """
    name: str = Field(..., description="Tên tool đã gọi (tool_knowledge_search, tool_save_user_info, tool_get_user_info)")
    description: str = Field(default="", description="Mô tả ngắn về kết quả hoặc hành động của tool")


class ReasoningStep(BaseModel):
    """
    A single step in the AI reasoning process.
    
    **Feature: reasoning-trace**
    **CHỈ THỊ KỸ THUẬT SỐ 28: Explainability Layer**
    """
    step_name: str = Field(..., description="Tên bước: query_analysis, retrieval, grading, rewrite, generation, verification")
    description: str = Field(..., description="Mô tả ngắn gọn bước này")
    result: str = Field(..., description="Kết quả/summary của bước")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Độ tin cậy của bước (0.0-1.0)")
    duration_ms: int = Field(default=0, description="Thời gian xử lý bước (milliseconds)")
    details: Optional[dict] = Field(default=None, description="Chi tiết bổ sung (optional)")


class ReasoningTrace(BaseModel):
    """
    Complete reasoning trace for AI transparency.
    
    Shows user how AI arrived at the answer step-by-step.
    
    **Feature: reasoning-trace**
    **CHỈ THỊ KỸ THUẬT SỐ 28: Explainability Layer**
    """
    total_steps: int = Field(..., description="Tổng số bước xử lý")
    total_duration_ms: int = Field(..., description="Tổng thời gian xử lý (milliseconds)")
    was_corrected: bool = Field(default=False, description="Query có được viết lại không?")
    correction_reason: Optional[str] = Field(default=None, description="Lý do viết lại query (nếu có)")
    final_confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Độ tin cậy cuối cùng")
    steps: list[ReasoningStep] = Field(default_factory=list, description="Danh sách các bước suy luận")


class ChatResponseMetadata(BaseModel):
    """
    Metadata in chat response.
    
    CHỈ THỊ KỸ THUẬT SỐ 27: API Transparency - Added tools_used field
    CHỈ THỊ KỸ THUẬT SỐ 28: Explainability - Added reasoning_trace field
    CHỈ THỊ LMS INTEGRATION: Added analytics fields (topics, confidence, etc.)
    **Feature: api-transparency-thinking, reasoning-trace**
    **Validates: Requirements 1.1, 1.4, 3.2**
    """
    processing_time: float = Field(..., description="Thời gian xử lý (giây)")
    provider: Optional[str] = Field(default=None, description="LLM provider runtime")
    model: str = Field(default="agentic-rag-v3", description="Model AI sử dụng")
    runtime_authoritative: bool = Field(
        default=True,
        description="True khi provider/model phản ánh đúng execution runtime của lượt này",
    )
    agent_type: AgentType = Field(default=AgentType.RAG, description="Agent xử lý request")
    session_id: Optional[str] = Field(default=None, description="Session ID của cuộc hội thoại")
    tools_used: list[ToolUsageInfo] = Field(
        default_factory=list, 
        description="Danh sách tools đã sử dụng trong quá trình xử lý (CHỈ THỊ 27)"
    )
    # Reasoning Trace (Feature: reasoning-trace)
    reasoning_trace: Optional[ReasoningTrace] = Field(
        default=None,
        description="Chi tiết quá trình suy luận của AI (CHỈ THỊ 28)"
    )
    # LMS Integration: Analytics fields
    topics_accessed: Optional[list[str]] = Field(
        default=None,
        description="Topics học viên quan tâm (extracted from query/response)"
    )
    confidence_score: Optional[float] = Field(
        default=None,
        description="Độ tin cậy câu trả lời (0.0-1.0)"
    )
    document_ids_used: Optional[list[str]] = Field(
        default=None,
        description="Danh sách document_id được sử dụng"
    )
    query_type: Optional[str] = Field(
        default=None,
        description="Loại câu hỏi: factual, conceptual, procedural"
    )
    # CHỈ THỊ SỐ 28: SOTA Thinking Content (Claude/OpenAI style)
    # Raw prose format for LMS frontend "Thought Process" display
    thinking_content: Optional[str] = Field(
        default=None,
        description="Nội dung suy nghĩ có cấu trúc (structured summary) - legacy fallback"
    )
    # CHỈ THỊ SỐ 29: Natural Vietnamese Thinking (Qwen/Claude style)
    thinking: Optional[str] = Field(
        default=None,
        description="Quá trình suy nghĩ tự nhiên bằng Tiếng Việt - hiển thị 'Đang suy luận' cho LMS frontend"
    )
    thinking_lifecycle: Optional[dict[str, Any]] = Field(
        default=None,
        description="Lifecycle snapshot authority for stream/sync thinking parity"
    )
    failover: Optional[dict[str, Any]] = Field(
        default=None,
        description="Runtime failover taxonomy and route trail for this request"
    )
    model_switch_prompt: Optional[dict[str, Any]] = Field(
        default=None,
        description="User-facing suggestion for switching provider/model after hard failover or provider outage"
    )
    # Sprint 103: Routing metadata for debugging and monitoring
    routing_metadata: Optional[dict] = Field(
        default=None,
        description="Supervisor routing decision: intent, confidence, reasoning, method"
    )
    runtime_flow_trace: Optional[dict[str, Any]] = Field(
        default=None,
        description="Privacy-safe turn-path/tool-policy/action trace for runtime observability",
    )
    post_turn_lifecycle: Optional[dict[str, Any]] = Field(
        default=None,
        description="Status-only post-turn lifecycle scheduling summary",
    )


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
                        "model": "agentic-rag-v3",
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
                            "url": "https://storage.example.com/wiii-docs/colregs/page_15.jpg",
                            "page_number": 15,
                            "document_id": "colregs_2024"
                        }
                    ]
                }
            ]
        }
    }


# =============================================================================
# AI Event Callback Schemas (AI-LMS Integration v2.0)
# =============================================================================

# =============================================================================
# Message Feedback Schemas (Sprint 107)
# =============================================================================

class FeedbackRating(str, Enum):
    """User feedback rating"""
    UP = "up"
    DOWN = "down"


class FeedbackRequest(BaseModel):
    """Request to submit feedback on an AI message"""
    message_id: str = Field(..., description="ID of the message being rated")
    session_id: str = Field(..., description="Session ID of the conversation")
    rating: FeedbackRating = Field(..., description="up or down")
    comment: Optional[str] = Field(default=None, max_length=1000, description="Optional feedback comment")


class FeedbackResponse(BaseModel):
    """Response after submitting feedback"""
    status: str = Field(default="success")
    message_id: str
    rating: FeedbackRating


class AIEventType(str, Enum):
    """
    Types of AI events for LMS callback.
    
    Spec: LMS_RESPONSE_TO_AI_PROPOSAL.md
    Feature: ai-lms-integration-v2
    """
    KNOWLEDGE_GAP_DETECTED = "knowledge_gap_detected"
    GOAL_EVOLUTION = "goal_evolution"
    MODULE_COMPLETED_CONFIDENCE = "module_completed_confidence"
    STUCK_DETECTED = "stuck_detected"


class AIEventData(BaseModel):
    """
    Event data payload for AI events.
    
    Feature: ai-lms-integration-v2
    """
    topic: Optional[str] = Field(default=None, description="Topic liên quan")
    gap_type: Optional[str] = Field(default=None, description="Loại lỗ hổng: conceptual, procedural")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="Độ tin cậy (0.0-1.0)")
    suggested_action: Optional[str] = Field(default=None, description="Hành động đề xuất: review_module, suggest_quiz")
    module_id: Optional[str] = Field(default=None, description="Module ID liên quan")
    details: Optional[dict] = Field(default=None, description="Chi tiết bổ sung")


class AIEvent(BaseModel):
    """
    AI Event for callback to LMS.
    
    Spec: LMS_RESPONSE_TO_AI_PROPOSAL.md
    Feature: ai-lms-integration-v2
    """
    user_id: str = Field(..., description="User UUID")
    event_type: AIEventType = Field(..., description="Loại event")
    data: AIEventData = Field(..., description="Payload data")
    timestamp: datetime = Field(default_factory=utc_now, description="Thời gian event")
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "user_id": "550e8400-e29b-41d4-a716-446655440000",
                    "event_type": "knowledge_gap_detected",
                    "data": {
                        "topic": "Rule 15 - Crossing Situation",
                        "gap_type": "conceptual",
                        "confidence": 0.9,
                        "suggested_action": "review_module",
                        "module_id": "rule_13_15"
                    },
                    "timestamp": "2025-12-13T00:00:00Z"
                }
            ]
        }
    }
