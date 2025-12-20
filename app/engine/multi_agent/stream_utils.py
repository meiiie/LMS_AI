"""
Stream Utilities for Multi-Agent Graph Streaming

SOTA Dec 2025: LangGraph 1.0 astream_events() pattern
Pattern: OpenAI Responses API + Claude Extended Thinking + Gemini astream

This module provides utilities to stream events from LangGraph execution,
transforming internal graph events into user-friendly SSE events.

**Feature: v3-full-graph-streaming**
"""

import logging
import time
from typing import AsyncGenerator, Dict, Any, Optional, List
from dataclasses import dataclass

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
    DONE = "done"               # Stream complete
    ERROR = "error"             # Error occurred


# =============================================================================
# NODE NAME MAPPINGS (User-friendly descriptions)
# =============================================================================

NODE_DESCRIPTIONS = {
    "supervisor": "🎯 Phân tích và định tuyến câu hỏi",
    "rag_agent": "📚 Tra cứu cơ sở tri thức",
    "tutor_agent": "👨‍🏫 Tạo bài giảng",
    "memory_agent": "🧠 Truy xuất bộ nhớ",
    "direct": "💬 Tạo phản hồi trực tiếp",
    "grader": "✅ Kiểm tra chất lượng",
    "synthesizer": "📝 Tổng hợp câu trả lời"
}

NODE_STEPS = {
    "supervisor": "routing",
    "rag_agent": "retrieval",
    "tutor_agent": "teaching",
    "memory_agent": "memory_lookup",
    "direct": "direct_response",
    "grader": "quality_check",
    "synthesizer": "synthesis"
}


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
        return result


# =============================================================================
# EVENT TRANSFORMERS
# =============================================================================

def transform_langgraph_event(
    event: Dict[str, Any],
    event_type: str = "on_chain_start"
) -> Optional[StreamEvent]:
    """
    Transform LangGraph event to StreamEvent.
    
    LangGraph event types:
    - on_chain_start: Node execution starts
    - on_chain_end: Node execution ends  
    - on_chain_stream: Streaming from node
    - on_chat_model_stream: Token from LLM
    
    Args:
        event: Raw LangGraph event
        event_type: Type of LangGraph event
        
    Returns:
        StreamEvent or None if event should be filtered
    """
    try:
        name = event.get("name", "")
        data = event.get("data", {})
        
        # Filter internal events
        if name.startswith("_"):
            return None
        
        # Handle node start events
        if event_type == "on_chain_start":
            node_name = _extract_node_name(name)
            if node_name and node_name in NODE_DESCRIPTIONS:
                return StreamEvent(
                    type=StreamEventType.STATUS,
                    content=NODE_DESCRIPTIONS[node_name],
                    node=node_name,
                    step=NODE_STEPS.get(node_name)
                )
        
        # Handle node end events
        elif event_type == "on_chain_end":
            node_name = _extract_node_name(name)
            output = data.get("output", {})
            
            if node_name == "grader":
                # Extract grader score
                score = output.get("grader_score", 0)
                return StreamEvent(
                    type=StreamEventType.THINKING,
                    content=f"Điểm chất lượng: {score}/10",
                    node=node_name,
                    step="quality_check",
                    confidence=score / 10
                )
            
            elif node_name == "supervisor":
                # Extract routing decision
                next_agent = output.get("next_agent", "unknown")
                return StreamEvent(
                    type=StreamEventType.THINKING,
                    content=f"Định tuyến đến: {next_agent}",
                    node=node_name,
                    step="routing",
                    details={"routed_to": next_agent}
                )
        
        # Handle LLM token streaming
        elif event_type == "on_chat_model_stream":
            chunk = data.get("chunk", {})
            content = _extract_content_from_chunk(chunk)
            if content:
                return StreamEvent(
                    type=StreamEventType.ANSWER,
                    content=content
                )
        
        return None
        
    except Exception as e:
        logger.warning(f"[STREAM] Failed to transform event: {e}")
        return None


def _extract_node_name(event_name: str) -> Optional[str]:
    """Extract node name from LangGraph event name."""
    # LangGraph event names can be like "supervisor" or "AgentState.supervisor"
    for node in NODE_DESCRIPTIONS.keys():
        if node in event_name.lower():
            return node
    return None


def _extract_content_from_chunk(chunk: Any) -> Optional[str]:
    """
    Extract text content from LLM chunk.
    
    Handles:
    - Gemini 2.0 Flash format
    - OpenAI format
    - Anthropic format
    """
    # String content
    if isinstance(chunk, str):
        return chunk
    
    # Dict with content field
    if isinstance(chunk, dict):
        if "content" in chunk:
            content = chunk["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Gemini format: list of content blocks
                texts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        texts.append(block["text"])
                    elif isinstance(block, str):
                        texts.append(block)
                return "".join(texts) if texts else None
    
    # AIMessageChunk or similar
    if hasattr(chunk, "content"):
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    texts.append(block["text"])
            return "".join(texts) if texts else None
    
    return None


# =============================================================================
# STREAM EVENT GENERATORS
# =============================================================================

async def create_status_event(
    message: str,
    node: Optional[str] = None
) -> StreamEvent:
    """Create a status event for progress indication."""
    return StreamEvent(
        type=StreamEventType.STATUS,
        content=message,
        node=node,
        step=NODE_STEPS.get(node) if node else None
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
        content=content,
        step=step,
        confidence=confidence,
        details=details
    )


async def create_answer_event(content: str) -> StreamEvent:
    """Create an answer token event."""
    return StreamEvent(
        type=StreamEventType.ANSWER,
        content=content
    )


async def create_sources_event(sources: List[Dict]) -> StreamEvent:
    """Create a sources event with citations."""
    return StreamEvent(
        type=StreamEventType.SOURCES,
        content=sources
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
    return StreamEvent(
        type=StreamEventType.METADATA,
        content=content
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
        content={"message": message}
    )


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def should_filter_event(event: StreamEvent) -> bool:
    """
    Determine if an event should be filtered out.
    
    Filters:
    - Empty content
    - Duplicate status events
    - Internal events
    """
    if event.content is None:
        return True
    if isinstance(event.content, str) and not event.content.strip():
        return True
    return False


logger.info("[STREAM_UTILS] Loaded streaming utilities for Multi-Agent Graph")
