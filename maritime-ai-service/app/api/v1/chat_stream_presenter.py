"""Presentation helpers for streaming SSE responses."""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload

try:
    from app.engine.llm_providers.wiii_chat_model import _ViSpaceInjector
except ModuleNotFoundError as exc:
    if exc.name != "openai":
        raise

    class _ViSpaceInjector:
        """No-op fallback when optional provider SDKs are not installed."""

        def process(self, token: str) -> str:
            return token

# ── Soul Emotion Tag Stripper ──────────────────────────────────────────────
# LLM sometimes emits <!--WIII_SOUL:...--> or <!-- WIII_SOUL:...--> tags
# that must NEVER reach the frontend as visible text. Some markdown/HTML
# surfaces can also expose malformed variants such as <! --WIII_SOUL:...-->.
# Strip them at the SSE layer as a safety net regardless of upstream extraction.
_SOUL_TAG_RE = re.compile(
    r"(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:.*?(?:--\s*>|--\s*&gt;)",
    re.DOTALL | re.IGNORECASE,
)
_SOUL_TAG_AT_START_RE = re.compile(
    r"^\s*(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:",
    re.IGNORECASE,
)
_SOUL_TAG_OPEN_RE = re.compile(
    r"(?:<\s*!\s*--|&lt;\s*!\s*--)\s*WIII_SOUL\s*:",
    re.IGNORECASE,
)
_SOUL_TAG_PREFIXES = ("<!--wiii_soul:", "&lt;!--wiii_soul:")


def _compact_soul_prefix(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _find_incomplete_soul_tag_start(text: str) -> int | None:
    open_match = _SOUL_TAG_OPEN_RE.search(text)
    if open_match:
        return open_match.start()

    # Hold only a tiny trailing prefix that could become a soul tag in the
    # next token. If it is normal prose (for example "<b"), the next pass will
    # release it because it no longer matches these prefixes.
    scan_start = max(0, len(text) - 32)
    for index in range(scan_start, len(text)):
        compact_tail = _compact_soul_prefix(text[index:])
        if compact_tail and any(
            prefix.startswith(compact_tail) for prefix in _SOUL_TAG_PREFIXES
        ):
            return index
    return None


def _strip_soul_tags(text: str) -> str:
    if not text or "WIII_SOUL" not in text.upper():
        return text
    starts_with_internal_tag = bool(_SOUL_TAG_AT_START_RE.search(text))
    cleaned = _SOUL_TAG_RE.sub("", text)
    incomplete_start = _find_incomplete_soul_tag_start(cleaned)
    if incomplete_start is not None:
        cleaned = cleaned[:incomplete_start]
    if starts_with_internal_tag:
        cleaned = cleaned.lstrip()
    return cleaned

# ── Unified Zombie Phrase Filter (Expert Review P1) ──────────────────────
# Single source of truth for zombie phrase filtering at SSE presentation
# layer. ALL thinking_delta events pass through this filter regardless of
# which agent path generated them (Direct, RAG, Product Search, etc.).
# Thà không có thinking còn hơn có suy nghĩ giả.
_ZOMBIE_PHRASES = (
    "Chỗ khó của câu này không nằm ở",
    "Mình sẽ đi thẳng vào phần lõi",
    "Điều dễ sai nhất là nhầm giữa",
    "Câu này nhẹ hơn một lượt đào sâu",
    "giữ phản hồi ngắn và tự nhiên",
    "giữ đúng cảnh này trước đã",
    "Đang chuẩn bị lượt trả lời",
)


def _filter_thinking_content(content: str) -> str:
    """Strip zombie boilerplate from thinking content.

    Returns empty string if content is all zombie filler (should be skipped).
    """
    if not content:
        return content
    cleaned = content
    for phrase in _ZOMBIE_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    return cleaned.strip()


DISPLAY_ROLE_BY_EVENT: dict[str, str] = {
    "thinking": "thinking",
    "thinking_start": "thinking",
    "thinking_end": "thinking",
    "thinking_delta": "thinking",
    "tool_call": "tool",
    "tool_result": "tool",
    "host_action": "tool",
    "pointy_action": "tool",
    "guided_tutor_proposal": "action",
    "browser_screenshot": "tool",
    "preview": "tool",
    "action_text": "action",
    "answer": "answer",
    "artifact": "artifact",
    "code_open": "artifact",
    "code_delta": "artifact",
    "code_complete": "artifact",
    "visual": "artifact",
    "visual_open": "artifact",
    "visual_patch": "artifact",
    "visual_commit": "artifact",
    "visual_dispose": "artifact",
}

PRESENTATION_BY_EVENT: dict[str, str] = {
    "thinking": "expanded",
    "thinking_start": "expanded",
    "thinking_end": "compact",
    "thinking_delta": "expanded",
    "tool_call": "technical",
    "tool_result": "technical",
    "host_action": "technical",
    "pointy_action": "compact",
    "guided_tutor_proposal": "compact",
    "browser_screenshot": "technical",
    "preview": "compact",
    "action_text": "compact",
    "status": "compact",
    "chat_lifecycle": "compact",
    "answer": "compact",
    "artifact": "compact",
    "code_open": "compact",
    "code_delta": "compact",
    "code_complete": "compact",
    "visual": "compact",
    "visual_open": "compact",
    "visual_patch": "compact",
    "visual_commit": "compact",
    "visual_dispose": "compact",
    "sources": "compact",
    "metadata": "compact",
    "done": "compact",
    "error": "compact",
}


@dataclass
class StreamPresentationState:
    """Track active reasoning step ids for interleaved streaming UI."""

    active_step_by_node: dict[str, str] = field(default_factory=dict)
    last_step_id: str | None = None
    answer_control_buffer: str = ""
    _vi_thinking: _ViSpaceInjector = field(default_factory=_ViSpaceInjector)
    _vi_answer: _ViSpaceInjector = field(default_factory=_ViSpaceInjector)

    @staticmethod
    def _node_key(node: str | None) -> str:
        return node or "__default__"

    def resolve_step_id(
        self,
        *,
        event_type: str,
        event_counter: int,
        node: str | None,
        details: dict[str, Any] | None,
    ) -> str | None:
        explicit_step_id = None
        if details:
            explicit_step_id = (
                details.get("step_id")
                or details.get("block_id")
            )

        node_key = self._node_key(node)

        if event_type == "thinking_start":
            step_id = explicit_step_id or f"{node_key}-step-{event_counter}"
            self.active_step_by_node[node_key] = step_id
            self.last_step_id = step_id
            return step_id

        if event_type == "thinking_end":
            step_id = (
                explicit_step_id
                or self.active_step_by_node.get(node_key)
                or self.last_step_id
            )
            self.active_step_by_node.pop(node_key, None)
            if step_id:
                self.last_step_id = step_id
            return step_id

        step_id = (
            explicit_step_id
            or self.active_step_by_node.get(node_key)
            or self.last_step_id
        )
        if step_id:
            self.last_step_id = step_id
        return step_id

    def strip_answer_delta_control_tags(self, content: str) -> str:
        """Remove internal control tags even when they span SSE deltas."""
        combined = f"{self.answer_control_buffer}{content or ''}"
        self.answer_control_buffer = ""
        if not combined:
            return ""

        starts_with_internal_tag = bool(_SOUL_TAG_AT_START_RE.search(combined))
        cleaned = _SOUL_TAG_RE.sub("", combined)
        incomplete_start = _find_incomplete_soul_tag_start(cleaned)
        if incomplete_start is not None:
            self.answer_control_buffer = cleaned[incomplete_start:]
            cleaned = cleaned[:incomplete_start]
        if starts_with_internal_tag:
            cleaned = cleaned.lstrip()
        return cleaned


def _step_state_for_event(event_type: str) -> str | None:
    if event_type == "thinking_end":
        return "completed"
    if event_type in {
        "thinking_start",
        "thinking",
        "thinking_delta",
        "tool_call",
        "tool_result",
        "host_action",
        "guided_tutor_proposal",
        "action_text",
        "browser_screenshot",
        "preview",
        "code_open",
        "code_delta",
        "code_complete",
        "visual",
        "visual_open",
        "visual_patch",
    }:
        return "live"
    if event_type in {"answer", "artifact", "chat_lifecycle", "visual", "visual_commit", "visual_dispose", "sources", "metadata", "done", "error"}:
        return "completed"
    return None


def _apply_presentation_metadata(
    *,
    payload: dict[str, Any],
    event_type: str,
    event_counter: int,
    event,
    presentation_state: StreamPresentationState | None,
) -> dict[str, Any]:
    if presentation_state is None:
        presentation_state = StreamPresentationState()

    details = getattr(event, "details", None)
    step_id = presentation_state.resolve_step_id(
        event_type=event_type,
        event_counter=event_counter,
        node=getattr(event, "node", None),
        details=details,
    )

    display_role = DISPLAY_ROLE_BY_EVENT.get(event_type)
    if display_role:
        payload["display_role"] = display_role

    payload["sequence_id"] = event_counter

    if step_id:
        payload["step_id"] = step_id

    step_state = _step_state_for_event(event_type)
    if step_state:
        payload["step_state"] = step_state

    presentation = PRESENTATION_BY_EVENT.get(event_type)
    if presentation:
        payload["presentation"] = presentation

    return payload


def format_sse(event: str, data: dict, event_id: int | None = None) -> str:
    """Format data as a Server-Sent Event with optional event id."""
    safe_data = sanitize_runtime_payload(data)
    if not isinstance(safe_data, dict):
        safe_data = {}
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(f"data: {json.dumps(safe_data, ensure_ascii=False)}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


def emit_blocked_sse_events(
    *,
    blocked_response,
    session_id: str,
    processing_time: float,
    event_counter: int,
    extra_metadata: Mapping[str, Any] | None = None,
) -> tuple[list[str], int]:
    """Emit the standard blocked-response SSE sequence."""
    chunks = []

    event_counter += 1
    chunks.append(
        format_sse(
            "answer",
            {"content": blocked_response.message},
            event_id=event_counter,
        )
    )
    event_counter += 1
    chunks.append(
        format_sse(
            "metadata",
            {
                **(blocked_response.metadata or {}),
                "session_id": session_id,
                **dict(extra_metadata or {}),
            },
            event_id=event_counter,
        )
    )
    event_counter += 1
    chunks.append(
        format_sse(
            "done",
            {"processing_time": processing_time},
            event_id=event_counter,
        )
    )
    return chunks, event_counter


def emit_internal_error_sse_events(
    *,
    processing_time: float | None = None,
    event_counter: int | None = None,
) -> tuple[list[str], int | None]:
    """Emit the standard internal-error SSE sequence."""
    chunks: list[str] = []

    next_event_id = None
    if event_counter is not None:
        event_counter += 1
        next_event_id = event_counter

    chunks.append(
        format_sse(
            "error",
            {
                "message": "Internal processing error",
                "type": "internal_error",
            },
            event_id=next_event_id,
        )
    )

    if processing_time is not None:
        next_event_id = None
        if event_counter is not None:
            event_counter += 1
            next_event_id = event_counter
        chunks.append(
            format_sse(
                "done",
                {"processing_time": processing_time},
                event_id=next_event_id,
            )
        )

    return chunks, event_counter


def serialize_stream_event(
    *,
    event,
    event_counter: int,
    enable_artifacts: bool,
    presentation_state: StreamPresentationState | None = None,
) -> tuple[list[str], int, bool]:
    """Serialize a StreamEvent into one or more SSE chunks."""
    event_type = event.type

    if event_type == "artifact" and not enable_artifacts:
        return [], event_counter, False

    event_counter += 1

    if event_type == "status":
        data: dict[str, Any] = {
            "content": event.content,
            "step": event.step,
            "node": event.node,
        }
        if event.details:
            data["details"] = event.details
        data = _apply_presentation_metadata(
            payload=data,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("status", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "chat_lifecycle":
        payload = dict(event.content) if isinstance(event.content, Mapping) else {}
        if event.node:
            payload.setdefault("node", event.node)
        if event.step:
            payload.setdefault("step", event.step)
        if event.details:
            payload.setdefault("details", event.details)
        data = _apply_presentation_metadata(
            payload=payload,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("chat_lifecycle", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "thinking":
        data = _apply_presentation_metadata(
            payload={
                "content": event.content,
                "step": event.step,
                "confidence": event.confidence,
                "details": event.details,
            },
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("thinking", data, event_id=event_counter)], event_counter, False

    if event_type == "answer":
        answer_content = _strip_soul_tags(event.content or "")
        data = _apply_presentation_metadata(
            payload={"content": answer_content},
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("answer", data, event_id=event_counter)], event_counter, False

    # Sprint 35e follow-up: also strip the soul tag from streaming chunks.
    # When the LLM begins its reply with ``<!--WIII_SOUL:...-->`` the first
    # ``answer_delta`` chunk carries the comment opener; without this guard
    # the SPA renders the raw HTML comment until the closing ``-->`` lands.
    if event_type == "answer_delta":
        if presentation_state:
            delta_content = presentation_state.strip_answer_delta_control_tags(
                event.content or ""
            )
        else:
            delta_content = _strip_soul_tags(event.content or "")
        if not delta_content:
            return [], event_counter, False
        data = _apply_presentation_metadata(
            payload={"content": delta_content, "node": getattr(event, "node", None)},
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("answer_delta", data, event_id=event_counter)], event_counter, False

    if event_type in {"tool_call", "tool_result", "host_action", "pointy_action", "guided_tutor_proposal"}:
        # v3.0 F6 (2026-05-06): pointy_action MUST be in this allowlist.
        # Without it, presenter falls through to default-drop branch and
        # the event NEVER reaches the SSE wire — frontend onPointyAction
        # never fires even though backend yielded the event correctly.
        # This was the root cause of "tool dispatched but cursor doesn't
        # move" symptom user hit 2026-05-06.
        data = _apply_presentation_metadata(
            payload={
                "content": event.content,
                "node": getattr(event, "node", None),
                "step": getattr(event, "step", None),
            },
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse(event_type, data, event_id=event_counter)], event_counter, False

    if event_type in {"action_text", "browser_screenshot", "preview"}:
        data = _apply_presentation_metadata(
            payload={
                "content": event.content,
                "node": event.node,
            },
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse(event_type, data, event_id=event_counter)], event_counter, False

    if event_type in {
        "artifact",
        "code_open",
        "code_delta",
        "code_complete",
        "visual",
        "visual_open",
        "visual_patch",
        "visual_commit",
        "visual_dispose",
    }:
        data = _apply_presentation_metadata(
            payload={
                "content": event.content,
                "node": event.node,
            },
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse(event_type, data, event_id=event_counter)], event_counter, False

    if event_type == "thinking_start":
        data = {
            "type": "thinking_start",
            "content": event.content,
            "node": event.node,
        }
        if event.details:
            data.update(event.details)
        if event.details and event.details.get("summary"):
            data["summary"] = event.details["summary"]
        data = _apply_presentation_metadata(
            payload=data,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("thinking_start", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "thinking_end":
        data = {
            "type": "thinking_end",
            "node": event.node,
        }
        if event.details:
            data.update(event.details)
        data = _apply_presentation_metadata(
            payload=data,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("thinking_end", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "thinking_delta":
        filtered_content = _filter_thinking_content(event.content or "")
        if not filtered_content:
            return [], event_counter, False
        if presentation_state:
            filtered_content = presentation_state._vi_thinking.process(filtered_content)
        data = _apply_presentation_metadata(
            payload={"content": filtered_content, "node": event.node},
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("thinking_delta", data, event_id=event_counter)], event_counter, False

    if event_type == "domain_notice":
        data = _apply_presentation_metadata(
            payload={"content": event.content},
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("domain_notice", data, event_id=event_counter)], event_counter, False

    if event_type == "emotion":
        data = _apply_presentation_metadata(
            payload=dict(event.content),
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("emotion", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "sources":
        data = _apply_presentation_metadata(
            payload={"sources": event.content},
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("sources", data, event_id=event_counter)], event_counter, False

    if event_type == "metadata":
        metadata = dict(event.content)
        metadata.setdefault("streaming_version", "v3-graph")
        metadata = _apply_presentation_metadata(
            payload=metadata,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("metadata", metadata, event_id=event_counter)
        ], event_counter, False

    if event_type == "done":
        data = _apply_presentation_metadata(
            payload=dict(event.content),
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [
            format_sse("done", data, event_id=event_counter)
        ], event_counter, False

    if event_type == "error":
        if isinstance(event.content, dict):
            payload = dict(event.content)
        else:
            payload = {"message": str(event.content)}
        payload.setdefault("message", str(event.content))
        payload.setdefault("type", "stream_error")
        data = _apply_presentation_metadata(
            payload=payload,
            event_type=event_type,
            event_counter=event_counter,
            event=event,
            presentation_state=presentation_state,
        )
        return [format_sse("error", data, event_id=event_counter)], event_counter, True

    return [], event_counter, False
