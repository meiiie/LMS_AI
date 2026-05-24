"""Typed contracts for deterministic Direct Node pre-LLM stages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True, slots=True)
class DirectDocumentPreviewPreflightRequest:
    """Per-turn state for the uploaded-document preview host-action preflight."""

    query: str
    state: AgentState
    ctx: dict[str, Any]
    bus_id: str | None
    response_present: bool
    has_uploaded_document_context: bool
    push_event: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class DirectDocumentPreviewPreflightDependencies:
    """Injected runtime functions for the document preview host-action preflight."""

    looks_uploaded_document_preview_request: Callable[[str], bool]
    build_visual_tool_runtime_metadata: Callable[..., dict[str, Any]]
    execute_direct_tool_rounds: Callable[..., Any]
    extract_direct_response: Callable[..., Any]
    sanitize_preview_response: Callable[[str, list[dict[str, Any]]], str]
    fallback_response: str
    logger_obj: logging.Logger


@dataclass(frozen=True, slots=True)
class DirectDocumentPreviewPreflightResult:
    """Document preview host action was emitted before the provider loop."""

    response: str
    response_type: str = "document_preview_host_action"


@dataclass(frozen=True, slots=True)
class DirectImageInputPreflightRequest:
    """Per-turn state for deterministic image-input handling before the LLM."""

    query: str
    state: AgentState
    ctx: dict[str, Any]
    response_present: bool
    has_uploaded_document_context: bool


@dataclass(frozen=True, slots=True)
class DirectImageInputPreflightDependencies:
    """Injected runtime functions for deterministic image-input handling."""

    record_thinking_snapshot_fn: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class DirectImageInputPreflightResult:
    """Image-input preflight answered the turn before the provider loop."""

    response: str
    response_type: str


@dataclass(frozen=True, slots=True)
class DirectNodeFastResponseRequest:
    """Per-turn state for deterministic fast responses before provider execution."""

    query: str
    state: AgentState
    ctx: dict[str, Any]
    has_uploaded_document_context: bool


@dataclass(frozen=True, slots=True)
class DirectNodeFastResponseDependencies:
    """Injected runtime functions for deterministic fast-response selection."""

    normalize_for_intent: Callable[[str], str]
    needs_web_search: Callable[[str], bool]
    needs_datetime: Callable[[str], bool]
    record_thinking_snapshot_fn: Callable[..., Any]
    logger_obj: logging.Logger | None = None


@dataclass(frozen=True, slots=True)
class DirectNodeFastResponse:
    """Resolved deterministic fast response for a direct turn."""

    response: str
    response_type: str
