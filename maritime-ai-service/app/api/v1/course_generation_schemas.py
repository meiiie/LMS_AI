"""Course generation API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class GenerationJobSummaryResponse(BaseModel):
    generation_id: str
    phase: str
    course_id: Optional[str] = None
    progress_percent: int = 0
    status_message: Optional[str] = None
    completed_chapter_count: int = 0
    failed_chapter_count: int = 0
    cancel_requested: bool = False
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    error: Optional[str] = None


class GenerationStatusResponse(BaseModel):
    generation_id: str
    phase: str
    outline: Optional[dict] = None
    source_references: list[dict] = Field(default_factory=list)
    course_id: Optional[str] = None
    completed_chapters: list[dict] = Field(default_factory=list)
    failed_chapters: list[dict] = Field(default_factory=list)
    progress_percent: int = 0
    status_message: Optional[str] = None
    cancel_requested: bool = False
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    error: Optional[str] = None


class ExpandRequest(BaseModel):
    teacher_id: str
    course_id: Optional[str] = None
    category_id: str
    course_title: str
    approved_chapters: list[int] = Field(min_length=1)
    language: str = "vi"
    legacy_lms_mutation_confirmed: bool = Field(
        default=False,
        description=(
            "Explicit opt-in for the legacy direct LMS mutation path. "
            "Product LMS doc-to-course flows must use preview -> teacher confirm -> apply."
        ),
    )

    @field_validator("approved_chapters")
    @classmethod
    def validate_approved_chapters(cls, value: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for idx in value:
            if idx < 0:
                raise ValueError("approved_chapters must contain only non-negative indices")
            if idx in seen:
                continue
            seen.add(idx)
            normalized.append(idx)
        return normalized
