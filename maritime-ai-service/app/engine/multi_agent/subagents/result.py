"""Base result classes for all subagent outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SubagentStatus(str, Enum):
    """Execution status of a subagent."""

    SUCCESS = "success"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"


class SubagentResult(BaseModel):
    """Base class for all subagent results.

    Every subagent must return an instance (or subclass) of this.
    """

    status: SubagentStatus = SubagentStatus.SUCCESS
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    output: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tools_used: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_images: List[Dict[str, Any]] = Field(default_factory=list)  # Sprint 189b
    boundary: Dict[str, Any] = Field(default_factory=dict)
    thinking: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int = Field(default=0, ge=0)

    @property
    def is_valid(self) -> bool:
        """True when the result is usable (success or partial)."""
        return self.status in (SubagentStatus.SUCCESS, SubagentStatus.PARTIAL)

    @property
    def is_retriable(self) -> bool:
        """True when the failure may resolve on retry (timeout)."""
        return self.status == SubagentStatus.TIMEOUT


# ---------------------------------------------------------------------------
# Domain-specific result subclasses
# ---------------------------------------------------------------------------


class SearchSubagentResult(SubagentResult):
    """Result from a product-search subagent."""

    products: List[Dict[str, Any]] = Field(default_factory=list)
    platforms_searched: List[str] = Field(default_factory=list)
    total_results: int = Field(default=0, ge=0)
    excel_path: Optional[str] = None


class RAGSubagentResult(SubagentResult):
    """Result from a RAG (retrieval-augmented generation) subagent."""

    documents: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    correction_rounds: int = Field(default=0, ge=0)


class TutorSubagentResult(SubagentResult):
    """Result from a tutor/teaching subagent."""

    phase_completed: str = ""
    pedagogical_approach: Optional[str] = None
