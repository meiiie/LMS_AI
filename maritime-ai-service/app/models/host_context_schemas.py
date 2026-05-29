"""Host, page, and user context schema contracts used across chat flows."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    """User role from LMS."""

    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"


class PageContext(BaseModel):
    """Page-level context from LMS frontend (Sprint 221: Page-Aware AI)."""

    page_type: Optional[str] = Field(
        default=None,
        description="dashboard | lesson | quiz | assignment | resource | forum | grades | settings",
    )
    page_title: Optional[str] = Field(default=None, description="Tiêu đề trang hiện tại")
    course_id: Optional[str] = Field(default=None, description="UUID khóa học")
    course_name: Optional[str] = Field(default=None, description="Tên khóa học")
    lesson_id: Optional[str] = Field(default=None, description="UUID bài học")
    lesson_name: Optional[str] = Field(default=None, description="Tên bài học")
    chapter_name: Optional[str] = Field(default=None, description="Tên chương")
    content_snippet: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Nội dung đang xem (max 2000 ký tự)",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="theory | exercise | video | pdf | discussion",
    )
    quiz_question: Optional[str] = Field(default=None, description="Câu hỏi đang làm")
    quiz_options: Optional[list[str]] = Field(default=None, description="Các đáp án")
    assignment_description: Optional[str] = Field(default=None, description="Mô tả bài tập")
    action: Optional[str] = Field(default=None, description="Requested sidebar/operator action")
    user_role: Optional[str] = Field(default=None, description="Host role on the current page")
    workflow_stage: Optional[str] = Field(
        default=None,
        description="learning | authoring | assessment | analytics | governance",
    )
    selection: Optional[dict[str, Any]] = Field(
        default=None,
        description="Current structured selection on page",
    )
    editable_scope: Optional[dict[str, Any]] = Field(
        default=None,
        description="Editable scope exposed by host",
    )
    entity_refs: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Referenced entities on the page",
    )


class StudentPageState(BaseModel):
    """Student interaction state on current page (Sprint 221)."""

    time_on_page_ms: Optional[int] = Field(default=None, description="Thời gian trên trang (ms)")
    scroll_percent: Optional[float] = Field(default=None, description="Tỷ lệ cuộn trang (0-100)")
    quiz_attempts: Optional[int] = Field(default=None, description="Số lần thử câu hỏi")
    last_answer: Optional[str] = Field(default=None, description="Đáp án cuối cùng")
    is_correct: Optional[bool] = Field(default=None, description="Đáp án đúng/sai")
    progress_percent: Optional[float] = Field(default=None, description="Tiến độ (%)")


class HostResourceV1(BaseModel):
    """WebMCP-compatible host resource descriptor."""

    id: str
    title: str
    description: Optional[str] = None
    mime_type: Optional[str] = None
    access: Optional[str] = None
    freshness: Optional[str] = None
    fetch_mode: Optional[Literal["push", "pull"]] = None


class HostToolV1(BaseModel):
    """WebMCP-compatible host tool descriptor."""

    name: str
    title: str
    description: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None
    roles: Optional[list[str]] = None
    permission: Optional[str] = None
    required_permissions: Optional[list[str]] = None
    requires_confirmation: bool = False
    mutates_state: bool = False
    transport: Optional[Literal["postmessage", "http"]] = None
    surface: Optional[str] = None
    result_schema: Optional[dict[str, Any]] = None


class HostManifestV1(BaseModel):
    """WebMCP-compatible host manifest surfaced by LMS/Wiii bridge layers."""

    host_id: str
    origin: Optional[str] = None
    version: str = "1"
    resources: list[HostResourceV1] = Field(default_factory=list)
    tools: list[HostToolV1] = Field(default_factory=list)
    surfaces: list[str] = Field(default_factory=list)
    auth_mode: Optional[str] = None
    transport: Optional[str] = None
    page_types: list[str] = Field(default_factory=list)


class WidgetResultV1(BaseModel):
    """Normalized widget/app outcome passed back into the assistant loop."""

    widget_id: str
    widget_kind: str
    status: Optional[str] = None
    summary: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class HostActionAuditRequest(BaseModel):
    """Audit event emitted after a host action resolves on the client."""

    event_type: Literal["preview_created", "apply_confirmed", "publish_confirmed"]
    action: str = Field(..., min_length=1, max_length=120)
    request_id: str = Field(..., min_length=1, max_length=160)
    summary: Optional[str] = Field(default=None, max_length=2000)
    host_type: Optional[str] = Field(default=None, max_length=80)
    host_name: Optional[str] = Field(default=None, max_length=160)
    page_type: Optional[str] = Field(default=None, max_length=80)
    page_title: Optional[str] = Field(default=None, max_length=240)
    user_role: Optional[str] = Field(default=None, max_length=40)
    workflow_stage: Optional[str] = Field(default=None, max_length=80)
    preview_kind: Optional[str] = Field(default=None, max_length=80)
    preview_token: Optional[str] = Field(default=None, max_length=240)
    target_type: Optional[str] = Field(default=None, max_length=80)
    target_id: Optional[str] = Field(default=None, max_length=160)
    surface: Optional[str] = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HostActionAuditResponse(BaseModel):
    """Acknowledgement for a host action audit event."""

    status: Literal["success"] = "success"
    event_type: str
    action: str
    request_id: str


class HostActionResultRequest(BaseModel):
    """Execution result returned by the host for a pending host action."""

    action: str = Field(..., min_length=1, max_length=160)
    request_id: str = Field(..., min_length=1, max_length=160)
    success: bool
    summary: Optional[str] = Field(default=None, max_length=2000)
    error: Optional[str] = Field(default=None, max_length=1000)
    data: dict[str, Any] = Field(default_factory=dict)


class HostActionResultResponse(BaseModel):
    """Acknowledgement for a host action result submission."""

    status: Literal["accepted", "ignored"]
    action: str
    request_id: str
    matched: bool
    reason: Optional[str] = None


class UserContext(BaseModel):
    """
    User context from LMS for personalization.

    Spec: AI_LMS_INTEGRATION_PROPOSAL.md
    Pattern: Contextual RAG
    Feature: ai-lms-integration-v2
    """

    display_name: str = Field(..., description="Tên hiển thị (từ LMS)")
    role: UserRole = Field(..., description="student | teacher | admin")
    level: Optional[str] = Field(default=None, description="Cấp độ: Sinh viên năm 3, Sĩ quan hạng 2...")
    organization: Optional[str] = Field(default=None, description="Tổ chức: Đại học Hàng hải...")
    current_course_id: Optional[str] = Field(default=None, description="ID khóa học hiện tại")
    current_course_name: Optional[str] = Field(default=None, description="Tên khóa học")
    current_module_id: Optional[str] = Field(default=None, description="ID module (dùng làm process_id)")
    current_module_name: Optional[str] = Field(default=None, description="Tên module")
    progress_percent: Optional[float] = Field(default=None, ge=0, le=100, description="Tiến độ học (%)")
    completed_modules: Optional[list[str]] = Field(
        default=None,
        description="Danh sách module đã hoàn thành",
    )
    quiz_scores: Optional[dict[str, float]] = Field(
        default=None,
        description="Điểm quiz theo module_id",
    )
    language: str = Field(default="vi", description="Language preference: vi | en")
    page_context: Optional[PageContext] = Field(
        default=None,
        description="Ngữ cảnh trang hiện tại từ LMS (Sprint 221)",
    )
    student_state: Optional[StudentPageState] = Field(
        default=None,
        description="Trạng thái tương tác trên trang (Sprint 221)",
    )
    available_actions: Optional[list[dict]] = Field(
        default=None,
        description="Các hành động có sẵn trên trang (Sprint 221)",
    )
    host_context: Optional[dict] = Field(
        default=None,
        description="Generic host context (Sprint 222 — replaces page_context)",
    )
    host_capabilities: Optional[dict] = Field(
        default=None,
        description="Host capabilities and actions available to Wiii",
    )
    host_action_feedback: Optional[dict] = Field(
        default=None,
        description="Recent host action results so Wiii can continue preview/confirm/apply flows safely",
    )
    visual_context: Optional[dict] = Field(
        default=None,
        description="Inline visual session context from chat client for follow-up visual patching",
    )
    widget_feedback: Optional[dict] = Field(
        default=None,
        description="Recent widget/app interaction results from chat client for personalized follow-up",
    )
    code_studio_context: Optional[dict] = Field(
        default=None,
        description="Active Code Studio session context from chat client for code/app follow-up turns",
    )
    document_context: Optional[dict] = Field(
        default=None,
        description="Per-turn Markdown extracted from files attached in the desktop chat UI",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "display_name": "Minh",
                    "role": "student",
                    "level": "Sinh viên năm 3",
                    "organization": "Đại học Hàng hải Việt Nam",
                    "current_course_id": "colregs_2024",
                    "current_course_name": "COLREGs - Quy tắc phòng ngừa đâm va",
                    "current_module_id": "rule_13_15",
                    "progress_percent": 45.0,
                    "completed_modules": ["rule_1_3", "rule_4_10"],
                    "language": "vi",
                }
            ]
        }
    }


class ImageInput(BaseModel):
    """Image input for multimodal chat. Supports base64 and URL."""

    type: Literal["base64", "url"] = Field(default="base64", description="Image source type")
    media_type: str = Field(
        default="image/jpeg",
        description="MIME type: image/jpeg, image/png, image/webp, image/gif",
    )
    data: str = Field(..., description="Base64 encoded image data or URL")
    detail: Literal["auto", "low", "high"] = Field(
        default="auto",
        description="Vision detail level (low=85 tokens, high=up to 1105 tokens)",
    )

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, value: str) -> str:
        allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
        if value not in allowed:
            raise ValueError(f"Unsupported media type: {value}. Allowed: {allowed}")
        return value

    @field_validator("data")
    @classmethod
    def validate_data_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Image data cannot be empty")
        return value.strip()
