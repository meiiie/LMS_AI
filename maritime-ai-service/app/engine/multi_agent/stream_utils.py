"""
Stream utilities for WiiiRunner multi-agent streaming

SOTA Dec 2025: evented agent streaming pattern
Pattern: OpenAI Responses API + Claude Extended Thinking + Gemini astream

This module provides utilities to stream events from WiiiRunner execution,
transforming internal runtime events into user-friendly SSE events.

**Feature: v3-full-graph-streaming**
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from app.engine.multi_agent.tool_event_sanitizer import sanitize_tool_args_for_event
from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload

logger = logging.getLogger(__name__)


# =============================================================================
# EVENT TYPES (OpenAI Responses API pattern)
# =============================================================================

class StreamEventType:
    """Standard event types for SSE streaming."""
    STATUS = "status"           # Processing stage updates (typing indicator)
    THINKING = "thinking"       # AI reasoning steps (collapsible section)
    TOOL_CALL = "tool_call"     # Tool invocation (transparency)
    TOOL_RESULT = "tool_result" # Tool result summary
    ANSWER = "answer"           # Response tokens (streamed real-time)
    SOURCES = "sources"         # Citation list with image_url
    METADATA = "metadata"       # reasoning_trace, confidence, timing
    CHAT_LIFECYCLE = "chat_lifecycle"  # Typed chat runtime lifecycle/progress
    THINKING_DELTA = "thinking_delta"   # Incremental thinking token (real-time)
    THINKING_START = "thinking_start"  # Thinking block opened (lifecycle)
    THINKING_END = "thinking_end"      # Thinking block closed (lifecycle)
    DONE = "done"               # Stream complete
    ERROR = "error"             # Error occurred
    DOMAIN_NOTICE = "domain_notice"  # Gentle notice: content outside active domain
    EMOTION = "emotion"              # Sprint 135: Soul emotion for avatar expression
    ACTION_TEXT = "action_text"      # Sprint 147: Bold narrative between thinking blocks
    BROWSER_SCREENSHOT = "browser_screenshot"  # Sprint 153: Playwright screenshot
    PREVIEW = "preview"                          # Sprint 166: Rich preview cards
    ARTIFACT = "artifact"                        # Sprint 167: Interactive artifacts (code, HTML, data)
    VISUAL = "visual"                            # Sprint 230: Structured inline visuals
    VISUAL_OPEN = "visual_open"                  # Sprint 231: Open inline visual session
    VISUAL_PATCH = "visual_patch"                # Sprint 231: Patch inline visual session
    VISUAL_COMMIT = "visual_commit"              # Sprint 231: Commit inline visual session
    VISUAL_DISPOSE = "visual_dispose"            # Sprint 231: Dispose inline visual session
    HOST_ACTION = "host_action"                    # Sprint 222b: Bidirectional host action request
    POINTY_ACTION = "pointy_action"                # Wiii Pointy: agent-controlled cursor / spotlight
    CODE_OPEN = "code_open"                          # Code Studio: session metadata
    CODE_DELTA = "code_delta"                        # Code Studio: chunked code content
    CODE_COMPLETE = "code_complete"                  # Code Studio: full code + trigger preview


# =============================================================================
# NODE NAME MAPPINGS (transport-level fallbacks only)
# =============================================================================

NODE_DESCRIPTIONS = {
    "supervisor": "Đang canh lại hướng xử lý...",
    "rag_agent": "Đang tiếp tục tra cứu...",
    "tutor_agent": "Đang tiếp tục giải thích...",
    "memory_agent": "Đang gọi lại ngữ cảnh...",
    "direct": "Đang tiếp tục trả lời...",
    "grader": "Đang rà soát độ chắc chắn...",
    "synthesizer": "Đang khâu lại phản hồi...",
    "product_search_agent": "Đang tiếp tục đối chiếu...",
    "code_studio_agent": "Đang chế tác đầu ra kỹ thuật...",
}

NODE_STEPS = {
    "supervisor": "routing",
    "rag_agent": "retrieval",
    "tutor_agent": "teaching",
    "product_search_agent": "product_search",
    "memory_agent": "memory_lookup",
    "direct": "direct_response",
    "grader": "quality_check",
    "synthesizer": "synthesis",
    "code_studio_agent": "code_studio",
}


def _sanitize_event_dict(value: Dict[str, Any]) -> Dict[str, Any]:
    safe = sanitize_runtime_payload(value)
    return safe if isinstance(safe, dict) else {}


def _sanitize_event_list(value: List[Dict]) -> List[Dict]:
    safe = sanitize_runtime_payload(value)
    return safe if isinstance(safe, list) else []


def _sanitize_event_text(value: Any) -> str:
    safe = sanitize_runtime_payload(str(value or ""))
    return str(safe or "")


# =============================================================================
# STREAM EVENT DATACLASS
# =============================================================================

@dataclass
class StreamEvent:
    """
    Unified stream event for SSE.
    
    Attributes:
        type: Event type (status, thinking, answer, etc.)
        content: Event content (string or dict)
        node: Source node name (optional)
        step: Reasoning step name (optional)
        confidence: Confidence score 0-1 (optional)
        details: Additional details (optional)
    """
    type: str
    content: Any
    node: Optional[str] = None
    step: Optional[str] = None
    confidence: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    subtype: Optional[str] = None  # Phase2: forward-looking State Machine prep

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for SSE serialization."""
        result = {
            "type": self.type,
            "content": self.content
        }
        if self.node:
            result["node"] = self.node
        if self.step:
            result["step"] = self.step
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.details:
            result["details"] = self.details
        if self.subtype:
            result["subtype"] = self.subtype
        return result


# =============================================================================
# STREAM EVENT GENERATORS
# =============================================================================

async def create_status_event(
    message: str,
    node: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> StreamEvent:
    """Create a status event for progress indication."""
    return StreamEvent(
        type=StreamEventType.STATUS,
        content=_sanitize_event_text(message),
        node=node,
        step=NODE_STEPS.get(node) if node else None,
        details=_sanitize_event_dict(details) if isinstance(details, dict) else None,
    )


async def create_thinking_event(
    content: str,
    step: str,
    confidence: Optional[float] = None,
    details: Optional[Dict] = None
) -> StreamEvent:
    """Create a thinking event for reasoning transparency."""
    return StreamEvent(
        type=StreamEventType.THINKING,
        content=_sanitize_event_text(content),
        step=step,
        confidence=confidence,
        details=_sanitize_event_dict(details) if isinstance(details, dict) else None,
    )


async def create_answer_event(content: str) -> StreamEvent:
    """Create an answer token event."""
    return StreamEvent(
        type=StreamEventType.ANSWER,
        content=_sanitize_event_text(content)
    )


async def create_sources_event(sources: List[Dict]) -> StreamEvent:
    """Create a sources event with citations."""
    return StreamEvent(
        type=StreamEventType.SOURCES,
        content=_sanitize_event_list(sources)
    )


async def create_metadata_event(
    reasoning_trace: Optional[Dict] = None,
    processing_time: float = 0,
    confidence: float = 0,
    **kwargs
) -> StreamEvent:
    """Create a metadata event with full trace info."""
    content = {
        "reasoning_trace": reasoning_trace,
        "processing_time": processing_time,
        "confidence": confidence,
        "streaming_version": "v3",
        **kwargs
    }
    safe_content = sanitize_runtime_payload(content)
    return StreamEvent(
        type=StreamEventType.METADATA,
        content=safe_content if isinstance(safe_content, dict) else {}
    )


async def create_done_event(total_time: float = 0) -> StreamEvent:
    """Create a done event signaling stream completion."""
    return StreamEvent(
        type=StreamEventType.DONE,
        content={"status": "complete", "total_time": round(total_time, 3)}
    )


async def create_error_event(message: str) -> StreamEvent:
    """Create an error event."""
    return StreamEvent(
        type=StreamEventType.ERROR,
        content={"message": _sanitize_event_text(message)}
    )


async def create_thinking_start_event(
    label: str,
    node: str,
    block_id: Optional[str] = None,
    summary: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> StreamEvent:
    """Create a thinking_start event to open a new thinking block."""
    merged_details: Optional[Dict[str, Any]] = dict(details or {}) if details else None
    if block_id or summary:
        merged_details = dict(merged_details or {})
        if block_id:
            merged_details["block_id"] = block_id
        if summary:
            merged_details["summary"] = _sanitize_event_text(summary)
            merged_details.setdefault("summary_mode", "header_only")
    return StreamEvent(
        type=StreamEventType.THINKING_START,
        content=_sanitize_event_text(label),
        node=node,
        details=_sanitize_event_dict(merged_details) if isinstance(merged_details, dict) else None,
        subtype="thinking",
    )


async def create_thinking_end_event(
    node: str,
    duration_ms: Optional[int] = None,
    block_id: Optional[str] = None,
) -> StreamEvent:
    """Create a thinking_end event to close the current thinking block."""
    details: Optional[Dict[str, Any]] = None
    if duration_ms is not None or block_id is not None:
        details = {}
        if duration_ms is not None:
            details["duration_ms"] = duration_ms
        if block_id is not None:
            details["block_id"] = block_id
    return StreamEvent(
        type=StreamEventType.THINKING_END,
        content="",
        node=node,
        details=details,
    )


async def create_tool_call_event(
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_call_id: str,
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a tool call event for agentic loop transparency."""
    return StreamEvent(
        type=StreamEventType.TOOL_CALL,
        content={
            "name": tool_name,
            "args": sanitize_tool_args_for_event(tool_args),
            "id": tool_call_id,
        },
        node=node,
        step="tool_execution",
        subtype="tool_call",
    )


def _sanitize_tool_result_summary(result_summary: Any) -> str:
    safe_payload = sanitize_runtime_payload({"result": result_summary})
    if isinstance(safe_payload, dict):
        safe_result = safe_payload.get("result", "")
    else:
        safe_result = safe_payload
    if isinstance(safe_result, (dict, list)):
        return json.dumps(safe_result, ensure_ascii=False)
    return str(safe_result or "")


async def create_tool_result_event(
    tool_name: str,
    result_summary: str,
    tool_call_id: str,
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a tool result event for agentic loop transparency."""
    return StreamEvent(
        type=StreamEventType.TOOL_RESULT,
        content={
            "name": tool_name,
            "result": _sanitize_tool_result_summary(result_summary),
            "id": tool_call_id,
        },
        node=node,
        step="tool_execution",
        subtype="tool_result",
    )


async def create_domain_notice_event(message: str) -> StreamEvent:
    """Create a domain_notice event — gentle UI indicator for off-domain content."""
    return StreamEvent(
        type=StreamEventType.DOMAIN_NOTICE,
        content=_sanitize_event_text(message),
    )


async def create_emotion_event(
    mood: str,
    face: dict,
    intensity: float,
) -> StreamEvent:
    """Sprint 135: Create an emotion event for avatar facial expression control."""
    return StreamEvent(
        type=StreamEventType.EMOTION,
        content=_sanitize_event_dict({
            "mood": mood,
            "face": face,
            "intensity": intensity,
        }),
    )


async def create_thinking_delta_event(
    content: str,
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a thinking_delta event for incremental thinking token streaming."""
    return StreamEvent(
        type=StreamEventType.THINKING_DELTA,
        content=_sanitize_event_text(content),
        node=node,
    )


async def create_action_text_event(
    content: str,
    node: Optional[str] = None,
) -> StreamEvent:
    """Create an action_text event as a narrative bridge between reasoning beats."""
    return StreamEvent(
        type=StreamEventType.ACTION_TEXT,
        content=_sanitize_event_text(content),
        node=node,
    )


async def create_browser_screenshot_event(
    url: str,
    image_base64: str,
    label: str,
    node: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> StreamEvent:
    """Sprint 153: Create a browser screenshot event for visual transparency."""
    return StreamEvent(
        type=StreamEventType.BROWSER_SCREENSHOT,
        content={
            "url": _sanitize_event_text(url),
            "image": image_base64,
            "label": _sanitize_event_text(label),
            "metadata": _sanitize_event_dict(metadata) if isinstance(metadata, dict) else {},
        },
        node=node,
    )


async def create_artifact_event(
    artifact_type: str,
    artifact_id: str,
    title: str,
    content: str,
    language: str = "",
    node: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> StreamEvent:
    """Sprint 167: Create an artifact event for interactive content rendering.

    Emits structured artifact data — frontend renders in ArtifactCard (inline)
    or ArtifactPanel (expanded). Supports code execution, HTML preview, data tables.

    Args:
        artifact_type: "code" | "html" | "react" | "table" | "chart" | "document" | "excel"
        artifact_id: Unique ID for dedup + panel reference
        title: Artifact title
        content: Source code / HTML / JSON data
        language: Programming language (for code: "python", "javascript", etc.)
        node: Source agent node name
        metadata: Extra metadata (execution_status, output, error, etc.)
    """
    content_payload = {
        "artifact_type": _sanitize_event_text(artifact_type),
        "artifact_id": _sanitize_event_text(artifact_id),
        "title": _sanitize_event_text(title),
        "content": _sanitize_event_text(content),
        "language": _sanitize_event_text(language),
        "metadata": _sanitize_event_dict(metadata) if isinstance(metadata, dict) else {},
    }
    return StreamEvent(
        type=StreamEventType.ARTIFACT,
        content=content_payload,
        node=node,
    )


async def create_visual_event(
    payload: Dict[str, Any],
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a structured inline visual event."""
    return StreamEvent(
        type=StreamEventType.VISUAL,
        content=_sanitize_event_dict(payload),
        node=node,
    )


async def create_visual_open_event(
    payload: Dict[str, Any],
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a visual_open lifecycle event."""
    return StreamEvent(
        type=StreamEventType.VISUAL_OPEN,
        content=_sanitize_event_dict(payload),
        node=node,
    )


async def create_visual_patch_event(
    payload: Dict[str, Any],
    node: Optional[str] = None,
) -> StreamEvent:
    """Create a visual_patch lifecycle event."""
    return StreamEvent(
        type=StreamEventType.VISUAL_PATCH,
        content=_sanitize_event_dict(payload),
        node=node,
    )


async def create_visual_commit_event(
    visual_session_id: str,
    node: Optional[str] = None,
    status: str = "committed",
) -> StreamEvent:
    """Create a visual_commit lifecycle event."""
    return StreamEvent(
        type=StreamEventType.VISUAL_COMMIT,
        content={
            "visual_session_id": _sanitize_event_text(visual_session_id),
            "status": _sanitize_event_text(status),
        },
        node=node,
    )


async def create_visual_dispose_event(
    visual_session_id: str,
    node: Optional[str] = None,
    reason: str = "",
    status: str = "disposed",
) -> StreamEvent:
    """Create a visual_dispose lifecycle event."""
    payload: Dict[str, Any] = {
        "visual_session_id": visual_session_id,
        "status": status,
    }
    if reason:
        payload["reason"] = _sanitize_event_text(reason)
    return StreamEvent(
        type=StreamEventType.VISUAL_DISPOSE,
        content=_sanitize_event_dict(payload),
        node=node,
    )


async def create_preview_event(
    preview_type: str,
    preview_id: str,
    title: str,
    snippet: str = "",
    url: Optional[str] = None,
    image_url: Optional[str] = None,
    citation_index: Optional[int] = None,
    node: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> StreamEvent:
    """Sprint 166: Create a preview card event for rich content rendering.

    Emits structured preview data — frontend decides rendering (document, product,
    web, link, code cards). Backend sends data, frontend renders.

    Args:
        preview_type: "document" | "product" | "web" | "link" | "code"
        preview_id: Unique ID for dedup + panel reference
        title: Card title (truncated to PREVIEW_TITLE_MAX_LENGTH)
        snippet: Content snippet (truncated to PREVIEW_SNIPPET_MAX_LENGTH)
        url: Source URL (optional)
        image_url: Thumbnail URL (optional)
        citation_index: Citation number [N] (optional)
        node: Source agent node name
        metadata: Type-specific metadata (score, price, platform, etc.)
    """
    from app.core.constants import PREVIEW_SNIPPET_MAX_LENGTH, PREVIEW_TITLE_MAX_LENGTH

    content_payload = _sanitize_event_dict(
        {
            "preview_type": preview_type,
            "preview_id": preview_id,
            "title": title[:PREVIEW_TITLE_MAX_LENGTH],
            "snippet": snippet[:PREVIEW_SNIPPET_MAX_LENGTH] if snippet else "",
            "url": url,
            "image_url": image_url,
            "citation_index": citation_index,
            "metadata": metadata or {},
        }
    )
    return StreamEvent(
        type=StreamEventType.PREVIEW,
        content=content_payload,
        node=node,
    )


async def create_code_open_event(
    session_id: str,
    title: str,
    language: str,
    version: int,
    studio_lane: Optional[str] = None,
    artifact_kind: Optional[str] = None,
    quality_profile: Optional[str] = None,
    renderer_contract: Optional[str] = None,
    node: Optional[str] = None,
) -> StreamEvent:
    """Code Studio: Create a code_open event to start a streaming code session."""
    content: Dict[str, Any] = {
        "session_id": session_id,
        "title": title,
        "language": language,
        "version": version,
    }
    if studio_lane:
        content["studio_lane"] = studio_lane
    if artifact_kind:
        content["artifact_kind"] = artifact_kind
    if quality_profile:
        content["quality_profile"] = quality_profile
    if renderer_contract:
        content["renderer_contract"] = renderer_contract

    return StreamEvent(
        type=StreamEventType.CODE_OPEN,
        content=_sanitize_event_dict(content),
        node=node,
    )


async def create_code_delta_event(
    session_id: str,
    chunk: str,
    chunk_index: int,
    total_bytes: int,
    node: Optional[str] = None,
) -> StreamEvent:
    """Code Studio: Create a code_delta event with a chunk of streaming code."""
    return StreamEvent(
        type=StreamEventType.CODE_DELTA,
        content=_sanitize_event_dict({
            "session_id": session_id,
            "chunk": chunk,
            "chunk_index": chunk_index,
            "total_bytes": total_bytes,
        }),
        node=node,
    )


async def create_code_complete_event(
    session_id: str,
    full_code: str,
    language: str,
    version: int,
    visual_payload: Optional[Dict[str, Any]] = None,
    studio_lane: Optional[str] = None,
    artifact_kind: Optional[str] = None,
    quality_profile: Optional[str] = None,
    renderer_contract: Optional[str] = None,
    node: Optional[str] = None,
) -> StreamEvent:
    """Code Studio: Create a code_complete event with full code and optional visual payload."""
    content: Dict[str, Any] = {
        "session_id": session_id,
        "full_code": full_code,
        "language": language,
        "version": version,
    }
    if visual_payload:
        content["visual_payload"] = visual_payload
    if studio_lane:
        content["studio_lane"] = studio_lane
    if artifact_kind:
        content["artifact_kind"] = artifact_kind
    if quality_profile:
        content["quality_profile"] = quality_profile
    if renderer_contract:
        content["renderer_contract"] = renderer_contract
    return StreamEvent(
        type=StreamEventType.CODE_COMPLETE,
        content=_sanitize_event_dict(content),
        node=node,
    )


async def create_host_action_event(
    request_id: str,
    action: str,
    params: dict,
    node: Optional[str] = None,
) -> StreamEvent:
    """Sprint 222b: Create a host action request event.

    Emitted when AI agent wants the host application to perform an action.
    Frontend receives this SSE event and forwards via PostMessage to host.
    """
    return StreamEvent(
        type=StreamEventType.HOST_ACTION,
        content=_sanitize_event_dict({
            "id": request_id,
            "action": action,
            "params": params,
        }),
        node=node,
    )


async def create_pointy_action_event(
    payload: dict,
    node: Optional[str] = None,
) -> StreamEvent:
    """Wiii Pointy: SSE event carrying an agent-controlled cursor command.

    The bus-side payload built by ``build_pointy_event`` already has the
    canonical shape (action, requestId, params, mode). Wrap it in a
    StreamEvent so the bus→stream converter and presenter can route the
    event through the SSE wire as a ``pointy_action`` event (not a fallback
    ``status`` event, which silently drops the cursor command).
    """
    return StreamEvent(
        type=StreamEventType.POINTY_ACTION,
        content=_sanitize_event_dict(dict(payload) if isinstance(payload, dict) else {}),
        node=node,
    )
