"""
RAG Tools - Knowledge Retrieval Tools for Wiii

Category: RAG (Knowledge Retrieval)
Access: READ (safe, no mutations)
"""

import contextvars
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from app.engine.tools.native_tool import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# ASYNC-SAFE STATE (contextvars for per-request isolation)
# =============================================================================

@dataclass
class RAGToolState:
    """Per-request state for RAG tools. Isolated between concurrent requests."""
    sources: List[Dict[str, str]] = field(default_factory=list)
    native_thinking: Optional[str] = None
    reasoning_trace: Optional[Any] = None
    confidence: float = 0.0
    is_complete: bool = False
    identity_key: Optional[str] = None


# ContextVar: each async request gets its own RAGToolState
_rag_tool_state: contextvars.ContextVar[RAGToolState] = contextvars.ContextVar(
    '_rag_tool_state', default=None
)

# RAG agent is a singleton (shared across requests) - this is safe as module-level
_rag_agent = None


def _tool_identity() -> tuple[str, bool]:
    """Resolve the current RAG tool identity for state isolation."""
    runtime_user_id = ""
    runtime_org_id = ""
    runtime_session_id = ""
    identity_available = False

    try:
        from app.engine.tools.runtime_context import get_current_tool_runtime_context

        runtime = get_current_tool_runtime_context()
        if runtime:
            runtime_user_id = str(runtime.user_id or "").strip()
            runtime_org_id = str(runtime.organization_id or "").strip()
            runtime_session_id = str(runtime.session_id or "").strip()
            identity_available = bool(
                runtime_user_id or runtime_org_id or runtime_session_id
            )
    except Exception:
        pass

    if not runtime_org_id:
        try:
            from app.core.org_context import get_current_org_id

            runtime_org_id = str(get_current_org_id() or "").strip()
            identity_available = identity_available or bool(runtime_org_id)
        except Exception:
            pass

    identity_key = (
        f"user={runtime_user_id}|org={runtime_org_id}|session={runtime_session_id}"
    )
    return identity_key, identity_available


def _new_state() -> RAGToolState:
    identity_key, _ = _tool_identity()
    return RAGToolState(identity_key=identity_key)


def _get_state() -> RAGToolState:
    """Get or create identity-scoped RAG tool state."""
    identity_key, identity_available = _tool_identity()
    state = _rag_tool_state.get(None)
    if state is None:
        state = _new_state()
        _rag_tool_state.set(state)
    elif identity_available and state.identity_key != identity_key:
        state = _new_state()
        _rag_tool_state.set(state)
    elif state.identity_key is None:
        state.identity_key = identity_key
    return state


def init_rag_tools(rag_agent):
    """Initialize RAG tools with the RAG agent (singleton, safe)."""
    global _rag_agent
    _rag_agent = rag_agent
    logger.info("RAG tools initialized")


def get_last_retrieved_sources() -> List[Dict[str, str]]:
    """Get the last retrieved sources for API response (per-request)."""
    return _get_state().sources


def get_last_native_thinking() -> Optional[str]:
    """
    Get the last native thinking from RAG for SOTA reasoning transparency.
    Per-request isolated via contextvars.
    """
    return _get_state().native_thinking


def get_last_reasoning_trace():
    """
    Get the last reasoning_trace from RAG for SOTA trace merge.
    Per-request isolated via contextvars.
    """
    return _get_state().reasoning_trace


def get_last_confidence() -> tuple[float, bool]:
    """
    Get the last confidence score and completion flag from RAG.
    Per-request isolated via contextvars.
    """
    state = _get_state()
    return state.confidence, state.is_complete


def clear_retrieved_sources():
    """Reset per-request state for a new request."""
    _rag_tool_state.set(_new_state())


def is_no_internal_match_observation(text: str) -> bool:
    """Check if a tool result is a 'no internal match' / no-result observation.

    Returns True when the text indicates that RAG retrieval found nothing
    useful, meaning the answer should fall back to direct knowledge.
    """
    if not text or not str(text).strip():
        return True
    lowered = str(text).lower().strip()
    no_match_markers = (
        "không tìm thấy",
        "khong tim thay",
        "không có kết quả",
        "khong co ket qua",
        "no relevant",
        "no documents",
        "no results",
        "0 document",
        "no matching",
        "không có nguồn",
        "khong co nguon",
        "không tìm được",
        "khong tim duoc",
        "xin lỗi, mình không",
        "xin lỗi, không",
        "không thể tìm",
        "khong the tim",
        "no internal match",
    )
    return any(marker in lowered for marker in no_match_markers)


def _sanitize_direct_rag_answer(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return "Mình chưa thấy nguồn nội bộ thật sự khớp, nên mình chuyển sang cách đáp trực tiếp nhé."
    lowered = normalized.lower()
    if any(marker in lowered for marker in ("xin lỗi", "khong co thong tin", "không có thông tin", "không thể trả lời", "khong the tra loi")):
        return "Mình chưa thấy nguồn nội bộ thật sự khớp, nên mình chuyển sang cách đáp trực tiếp nhé."
    return normalized


# =============================================================================
# RAG TOOLS
# =============================================================================

@tool(description="""
Tra cứu kiến thức từ cơ sở dữ liệu nội bộ (tài liệu đã tải lên, tri thức tổ chức, kiến thức chuyên ngành).
Gọi khi user hỏi về nội dung tài liệu, kiến thức đã nạp, hoặc thông tin chuyên môn.
""")
async def tool_knowledge_search(query: str) -> str:
    """Search domain knowledge base.

    Uses CorrectiveRAG for full 8-step trace with per-request state isolation.
    Generic name for multi-domain support. Alias: tool_maritime_search.
    """
    # Import CorrectiveRAG for SOTA trace generation
    from app.engine.agentic_rag.corrective_rag import get_corrective_rag

    if not _rag_agent:
        return "Xin lỗi, mình chưa tra cứu được kiến thức lúc này nha~ ≽^•⩊•^≼"

    # Get per-request state (async-safe via contextvars)
    state = _get_state()

    try:
        logger.info("[TOOL] Knowledge Search (CRAG): %s", query)

        crag = get_corrective_rag(_rag_agent)
        # Sprint 214: Pass org_id for org-scoped knowledge retrieval
        from app.core.org_context import get_current_org_id
        _org_id = get_current_org_id()
        _ctx = {"organization_id": _org_id} if _org_id else {}
        crag_result = await crag.process(query, context=_ctx)

        result = _sanitize_direct_rag_answer(crag_result.answer)

        # Normalize confidence from 0-100 (CRAG internal) to 0-1 (config thresholds)
        from app.core.config import settings
        state.confidence = crag_result.confidence / 100.0
        state.is_complete = state.confidence >= settings.rag_confidence_high
        logger.info("[TOOL] Confidence: %.2f, is_complete: %s (threshold=%s)", state.confidence, state.is_complete, settings.rag_confidence_high)

        # Store CRAG trace for propagation (per-request)
        state.reasoning_trace = crag_result.reasoning_trace
        if state.reasoning_trace:
            logger.info("[TOOL] CRAG trace captured: %d steps", state.reasoning_trace.total_steps)

        # Capture native thinking (per-request)
        state.native_thinking = crag_result.thinking
        if state.native_thinking:
            logger.info("[TOOL] Native thinking captured: %d chars", len(state.native_thinking))

        # Store sources for API response (per-request)
        if crag_result.sources:
            state.sources = [
                {
                    "node_id": src.get("node_id", ""),
                    "title": src.get("title", ""),
                    "content": src.get("content", "")[:500] if src.get("content") else "",
                    "image_url": src.get("image_url"),
                    "page_number": src.get("page_number"),
                    "document_id": src.get("document_id"),
                    "bounding_boxes": src.get("bounding_boxes"),
                    "content_type": src.get("content_type"),  # Sprint 189b
                }
                for src in crag_result.sources[:5]
            ]
            for i, src in enumerate(state.sources[:2]):
                logger.info("[TOOL] Source %d: page=%s, doc=%s, bbox=%s", i+1, src.get('page_number'), src.get('document_id'), bool(src.get('bounding_boxes')))
            logger.info("[TOOL] Saved %d sources for API response", len(state.sources))

            sources_text = [f"- {src.get('title', 'Unknown')}" for src in crag_result.sources[:3]]
            result += "\n\n**Nguồn tham khảo:**\n" + "\n".join(sources_text)
        else:
            state.sources = []

        confidence_signal = f"\n\n<!-- CONFIDENCE: {state.confidence:.2f} | IS_COMPLETE: {state.is_complete} -->"
        return result + confidence_signal

    except Exception as e:
        logger.error("Knowledge search error: %s", e)
        # Reset state on error
        _rag_tool_state.set(_new_state())
        return f"Lỗi khi tra cứu: {str(e)}"


# =============================================================================
# REGISTER TOOLS
# =============================================================================

def register_rag_tools():
    """Register all RAG tools with the registry."""
    registry = get_tool_registry()

    registry.register(
        tool=tool_knowledge_search,
        category=ToolCategory.RAG,
        access=ToolAccess.READ,
        description="Search domain knowledge base"
    )

    logger.info("RAG tools registered")


# Backward compatibility alias
tool_maritime_search = tool_knowledge_search


# Auto-register on import
register_rag_tools()
