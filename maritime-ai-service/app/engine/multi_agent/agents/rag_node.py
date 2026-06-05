"""
RAG Agent Node - Knowledge Retrieval Specialist

Uses Corrective RAG for intelligent document retrieval and generation.

**Integrated with agents/ framework for config and tracing.**
"""

import asyncio
import logging
from typing import Optional

from app.engine.agents import AgentConfig, RAG_AGENT_CONFIG
from app.engine.agentic_rag.corrective_rag import get_corrective_rag
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator
from app.engine.agentic_rag.runtime_llm_socket import agentic_rag_runtime_target

logger = logging.getLogger(__name__)

_RAG_STATUS_ONLY_STEPS = {
    "analysis",
    "adaptive_rag",
    "visual_rag",
    "graph_rag",
    "grading",
    "rewrite",
    "generation",
}

_RAG_STATUS_ONLY_MESSAGES = {
    "analysis": "Đang canh lại hướng tra cứu.",
    "adaptive_rag": "Đang chọn cách tìm phù hợp.",
    "visual_rag": "Đang rà thêm ngữ cảnh hình ảnh.",
    "graph_rag": "Đang nối thêm ngữ cảnh liên quan.",
    "grading": "Đang cân độ chắc của nguồn.",
    "rewrite": "Đang tinh lại cách tra cứu.",
    "generation": "Đang khâu lại phần trả lời.",
}

_RAG_TELEMETRY_MARKERS = (
    "độ phức tạp:",
    "do phuc tap:",
    "chủ đề:",
    "chu de:",
    "knowledge base",
    "độ tin cậy phân tích",
    "do tin cay phan tich",
    "chiến lược tìm kiếm:",
    "chien luoc tim kiem:",
    "điểm chất lượng:",
    "diem chat luong:",
    "tài liệu liên quan:",
    "tai lieu lien quan:",
    "ngưỡng yêu cầu:",
    "nguong yeu cau:",
    "câu gốc:",
    "cau goc:",
    "câu mới:",
    "cau moi:",
    "đồ thị tri thức:",
    "do thi tri thuc:",
    "hình ảnh từ tài liệu",
    "hinh anh tu tai lieu",
)


def _sanitize_visible_rag_text(content: object, *, step: str = "") -> str:
    text = " ".join(str(content or "").split()).strip()
    if not text:
        return text

    lowered = text.lower()
    if step == "retrieval":
        if any(marker in lowered for marker in ("0 tài liệu", "không tìm thấy tài liệu", "khong tim thay tai lieu", "0 documents", "no documents")):
            return "Mình chưa thấy nguồn nào thật sự khớp, nên chuyển sang cách đáp trực tiếp."
        return "Mình đang rà nguồn phù hợp trước khi chốt câu trả lời."

    if any(marker in lowered for marker in ("0 tài liệu", "không tìm thấy tài liệu", "khong tim thay tai lieu", "0 documents", "no documents")):
        return "Mình chưa thấy nguồn nào thật sự khớp, nên chuyển sang cách đáp trực tiếp."

    return text


def _looks_like_rag_telemetry(content: object) -> bool:
    normalized = " ".join(str(content or "").lower().split())
    if not normalized:
        return False
    return any(marker in normalized for marker in _RAG_TELEMETRY_MARKERS)


def _sanitize_public_rag_state_text(content: object) -> str:
    clean = _sanitize_visible_rag_text(content).strip()
    if not clean:
        return ""
    if _looks_like_rag_telemetry(clean):
        return ""
    return clean


class RAGAgentNode:
    """
    RAG Agent - Knowledge retrieval specialist.

    Uses Corrective RAG with self-correction loop.

    Implements agents/ framework integration:
    - config property from RAG_AGENT_CONFIG
    - agent_id from config
    """

    _STEP_BEATS = {
        "analysis": ("clarify", "analysis"),
        "retrieval": ("retrieve", "retrieval"),
        "grading": ("verify", "grading"),
        "rewrite": ("retrieve", "rewrite"),
        "generation": ("synthesis", "generation"),
    }

    def __init__(self, rag_agent=None):
        """
        Initialize RAG Agent Node.

        Args:
            rag_agent: Optional base RAG agent for retrieval
        """
        self._corrective_rag = get_corrective_rag(rag_agent)
        self._config = RAG_AGENT_CONFIG
        logger.info("RAGAgentNode initialized with config: %s", self._config.id)

    async def process(self, state: AgentState) -> AgentState:
        """
        Process state through RAG pipeline.

        Sprint 144: When streaming via event bus, uses process_streaming()
        for progressive real-time events. Otherwise uses process() as before.

        Args:
            state: Current agent state

        Returns:
            Updated state with RAG output
        """
        query = state.get("query", "")
        context = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            **state.get("context", {}),
        }

        _skill_ctx = state.get("skill_context")
        if _skill_ctx:
            context["skill_context"] = _skill_ctx

        _capability_ctx = state.get("capability_context")
        if _capability_ctx:
            context["capability_context"] = _capability_ctx

        _host_ctx = state.get("host_context_prompt", "")
        if _host_ctx:
            context["host_context_prompt"] = _host_ctx
        _host_caps_ctx = state.get("host_capabilities_prompt", "")
        if _host_caps_ctx:
            context["host_capabilities_prompt"] = _host_caps_ctx
        _operator_ctx = state.get("operator_context_prompt", "")
        if _operator_ctx:
            context["operator_context_prompt"] = _operator_ctx
        _living_ctx = state.get("living_context_prompt", "")
        if _living_ctx:
            context["living_context_prompt"] = _living_ctx
        _widget_feedback_ctx = state.get("widget_feedback_prompt", "")
        if _widget_feedback_ctx:
            context["widget_feedback_prompt"] = _widget_feedback_ctx
        if state.get("provider"):
            context["provider"] = state.get("provider")
        if state.get("model"):
            context["model"] = state.get("model")

        bus_id = state.get("_event_bus_id")
        event_queue = None
        if bus_id:
            from app.engine.multi_agent.graph_event_bus import _get_event_queue

            event_queue = _get_event_queue(bus_id)

        try:
            with agentic_rag_runtime_target(
                provider=state.get("provider"),
                model=state.get("model"),
            ):
                if event_queue:
                    result = await self._process_with_streaming(query, context, event_queue)
                else:
                    result = await self._corrective_rag.process(query, context)

            if result is None:
                raise RuntimeError("process_streaming returned no result")

            state["rag_output"] = result.answer
            state["sources"] = result.sources
            state["evidence_images"] = getattr(result, "evidence_images", [])
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["rag"] = result.answer
            state["current_agent"] = "rag_agent"

            if result.grading_result:
                state["grader_score"] = result.grading_result.avg_score

            if result.reasoning_trace:
                state["reasoning_trace"] = result.reasoning_trace

            if result.thinking_content:
                public_thinking_content = _sanitize_public_rag_state_text(
                    result.thinking_content,
                )
                if public_thinking_content:
                    state["thinking_content"] = public_thinking_content

            if result.thinking:
                public_native_thinking = _sanitize_public_rag_state_text(result.thinking)
                if public_native_thinking:
                    state["thinking"] = public_native_thinking

            logger.info("[RAG_AGENT] Processed query with confidence=%.0f%%", result.confidence)

        except Exception as e:
            logger.error("[RAG_AGENT] Error: %s", e)
            state["rag_output"] = "Wiii tìm kiếm bị trục trặc rồi. Bạn thử hỏi lại mình nhé!"
            state["error"] = "rag_error"
            state["evidence_images"] = []

        return state

    async def _process_with_streaming(
        self,
        query: str,
        context: dict,
        event_queue: asyncio.Queue,
    ):
        """Forward CRAG streaming events to the event bus."""

        result = None
        async for event in self._corrective_rag.process_streaming(query, context):
            etype = event.get("type", "")
            content = event.get("content", "")

            if etype == "status":
                event_queue.put_nowait({
                    "type": "status",
                    "content": content,
                    "node": "rag_agent",
                })
            elif etype == "thinking":
                step = str(event.get("step", "analysis"))
                if step in _RAG_STATUS_ONLY_STEPS:
                    event_queue.put_nowait({
                        "type": "status",
                        "content": _RAG_STATUS_ONLY_MESSAGES.get(step, "Đang rà lại ngữ cảnh."),
                        "node": "rag_agent",
                        "details": {"visibility": "status_only", "rag_step": step},
                    })
                    continue

                phase, cue = self._STEP_BEATS.get(step, ("clarify", "general"))
                surface_content = _sanitize_visible_rag_text(content, step=step)
                if not surface_content or _looks_like_rag_telemetry(surface_content):
                    continue
                beat = await get_reasoning_narrator().render(
                    ReasoningRenderRequest(
                        node="rag_agent",
                        phase=phase,
                        cue=cue,
                        user_goal=query,
                        conversation_context=str(context.get("conversation_summary", "")),
                        capability_context=str(context.get("capability_context", "")),
                        next_action="Tiếp tục kéo các đoạn tài liệu đáng tin nhất lên trước.",
                        observations=[surface_content],
                        user_id=str(context.get("user_id", "__global__")),
                        organization_id=context.get("organization_id"),
                        personality_mode=context.get("personality_mode"),
                        mood_hint=context.get("mood_hint"),
                        visibility_mode="rich",
                        style_tags=["rag", step],
                    )
                )
                event_queue.put_nowait({
                    "type": "thinking_start",
                    "content": beat.label,
                    "node": "rag_agent",
                    "summary": beat.summary,
                    "details": {"phase": beat.phase, "rag_step": step},
                })
                event_queue.put_nowait({
                    "type": "thinking_delta",
                    "content": surface_content or beat.summary,
                    "node": "rag_agent",
                })
                event_queue.put_nowait({
                    "type": "thinking_end",
                    "node": "rag_agent",
                })
            elif etype == "answer":
                event_queue.put_nowait({
                    "type": "answer_delta",
                    "content": content,
                    "node": "rag_agent",
                })
            elif etype == "result":
                result = event.get("data")

        return result

    @property
    def config(self) -> AgentConfig:
        """Get agent configuration."""
        return self._config

    @property
    def agent_id(self) -> str:
        """Get unique agent identifier."""
        return self._config.id

    def is_available(self) -> bool:
        """Check if RAG is available."""
        return self._corrective_rag.is_available()


_rag_node: Optional[RAGAgentNode] = None


def get_rag_agent_node(rag_agent=None) -> RAGAgentNode:
    """Get or create RAGAgentNode singleton."""
    global _rag_node
    if _rag_node is None:
        _rag_node = RAGAgentNode(rag_agent)
    return _rag_node
