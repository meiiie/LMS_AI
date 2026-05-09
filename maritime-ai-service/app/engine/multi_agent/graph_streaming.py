"""
Multi-Agent Runtime Streaming - Extracted from graph.py

Handles streaming execution for the runner-backed multi-agent runtime,
yielding progressive SSE events for real-time UI updates.

**Feature: v3-full-graph-streaming**

REFACTORED v3 (2026-02-09):
- Token-level streaming with asyncio.sleep delays for natural UX
- Real AI thinking content from agent nodes (not just status labels)
- Fixed direct node duplicate response
- Smaller chunk sizes for smoother streaming appearance

REFACTORED v4 (2026-02-12):
- Strict separation: status events (pipeline progress) vs thinking events (AI reasoning)
- Supervisor routing and grader scores are STATUS, not THINKING
- No truncation of real AI thinking content
- _extract_thinking_content() forwards raw thinking without summarization

Sprint 69:
- Event bus for intra-node streaming (thinking_delta from inside nodes)
- _EVENT_QUEUES registry keyed by request ID
- Concurrent graph + queue consumption for real-time events

Sprint 70: True Interleaved Thinking (Claude pattern)
- Concurrent merged-queue consumption: graph events + bus events in real-time
- Nodes push thinking_delta via .astream() during LLM inference
- Bus events yielded IMMEDIATELY (not only between node completions)
- Skip bulk thinking re-emission when bus already streamed deltas
"""

import asyncio
import functools
import logging
import re
import time
from typing import Optional, AsyncGenerator

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.core.constants import PREVIEW_SNIPPET_MAX_LENGTH
from app.engine.context.pointy_actions import POINTY_ACTION_HIGHLIGHT
from app.engine.context.pointy_fast_path import build_pointy_fast_path_action
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.graph_support import (
    _build_domain_config,
    _build_turn_local_state_defaults,
)
from app.engine.reasoning import ReasoningRenderRequest, get_reasoning_narrator
from app.engine.reasoning.reasoning_narrator import build_tool_context_summary
from app.engine.agents import get_agent_registry
from app.engine.multi_agent.graph_stream_surface import (
    _collapse_narration_impl as _collapse_narration,
    _clean_thinking_text_impl as _clean_thinking_text,
    _convert_bus_event_impl as _convert_bus_event,
    _ensure_vietnamese_impl as _ensure_vietnamese,
    _extract_and_stream_emotion_then_answer_impl,
    _extract_thinking_content_impl as _extract_thinking_content,
    _extract_thinking_label_impl as _extract_thinking_label,
    _extract_thinking_with_label_impl as _extract_thinking_with_label,
    _is_likely_english_impl as _is_likely_english,
    _is_pipeline_summary_impl as _is_pipeline_summary,
    _narration_delta_chunks_impl as _narration_delta_chunks,
    _normalize_narration_text_impl as _normalize_narration_text,
    _normalize_tool_names_impl as _normalize_tool_names,
    _render_fallback_narration_impl as _render_fallback_narration,
    _stream_answer_tokens_impl,
)
from app.engine.multi_agent.graph_stream_runtime import (
    build_stream_bootstrap_impl,
    emit_stream_finalization_impl,
)
from app.engine.multi_agent.graph_event_bus import (
    _EVENT_QUEUE_CREATED,
    _EVENT_QUEUES,
    _cleanup_stale_queues,
    _discard_event_queue,
    _get_event_queue,
    _register_event_queue,
)
from app.engine.multi_agent.graph_stream_finalize_runtime import (
    cleanup_stream_tasks_impl,
    emit_stream_completion_impl,
)
from app.engine.multi_agent.graph_stream_merge_runtime import (
    drain_pending_bus_events_impl,
    forward_bus_events_impl,
    forward_graph_events_impl,
    handle_bus_message_impl,
)
from app.engine.multi_agent.graph_stream_dispatch_runtime import (
    emit_state_update_events_impl,
)
from app.engine.multi_agent.graph_stream_node_runtime import (
    emit_document_previews_impl,
    emit_node_thinking_impl,
    emit_product_previews_impl,
    emit_tool_call_events_impl,
    emit_web_previews_impl,
)
from app.engine.multi_agent.graph_stream_agent_handlers import (
    handle_direct_node_impl,
    handle_product_search_node_impl,
)
from app.services.llm_runtime_audit_service import record_llm_runtime_observation

from app.engine.multi_agent.stream_utils import (
    StreamEvent,
    NODE_DESCRIPTIONS,
    create_status_event,
    create_thinking_start_event,
    create_thinking_end_event,
    create_thinking_delta_event,
    create_answer_event,
    create_sources_event,
    create_metadata_event,
    create_done_event,
    create_error_event,
    create_tool_call_event,
    create_tool_result_event,
    create_domain_notice_event,
    create_emotion_event,
    create_action_text_event,
    create_browser_screenshot_event,
    create_preview_event,
    create_artifact_event,
    create_visual_open_event,
    create_visual_patch_event,
    create_visual_commit_event,
    create_visual_dispose_event,
    create_code_open_event,
    create_code_delta_event,
    create_code_complete_event,
    create_host_action_event,
    create_pointy_action_event,
)

logger = logging.getLogger(__name__)

# Phase 0 Surface Contract: pipeline/runtime status events are hidden from
# the visible thinking rail.  Frontend checks details.visibility == "status_only"
# and skips rendering.  Only genuine Wiii inner-voice events reach the gray rail.
_PIPELINE_STATUS_DETAILS: dict = {"visibility": "status_only"}

# Token streaming config — simulate natural typing speed
TOKEN_CHUNK_SIZE = 40          # ~8-10 words per chunk (Sprint 103b: was 12)
TOKEN_DELAY_SEC = 0.008        # 8ms between chunks (Sprint 103b: was 18ms, ~125 tokens/sec)

# Compatibility re-exports for older tests and patch paths.  The shared
# state now lives in graph_event_bus so app modules can depend on the bus
# without importing graph_streaming's heavier orchestration shell.


# Vietnamese labels for thinking block headers (Sprint 64)
_NODE_LABELS = {
    "guardian": "Kiểm tra an toàn",
    "supervisor": "Phân tích câu hỏi",
    "rag_agent": "Tra cứu tri thức",
    "tutor_agent": "Soạn bài giảng",
    # Sprint 233: grader removed from pipeline
    "synthesizer": "Tổng hợp câu trả lời",
    "memory_agent": "Truy xuất bộ nhớ",
    "direct": "Suy nghĩ câu trả lời",
    "product_search_agent": "Tìm kiếm sản phẩm",
    "colleague_agent": "Hỏi ý kiến Bro",
    "parallel_dispatch": "Triển khai song song",
    "aggregator": "Tổng hợp báo cáo",
    # Sprint 164: Per-worker subagent labels (short names from parallel_dispatch)
    "rag": "Tra cứu tri thức",
    "tutor": "Soạn bài giảng",
    "search": "Tìm kiếm sản phẩm",
    "code_studio_agent": "Code Studio",
}

_stream_answer_tokens = functools.partial(
    _stream_answer_tokens_impl,
    token_chunk_size=TOKEN_CHUNK_SIZE,
    token_delay_sec=TOKEN_DELAY_SEC,
)

_extract_and_stream_emotion_then_answer = functools.partial(
    _extract_and_stream_emotion_then_answer_impl,
    token_chunk_size=TOKEN_CHUNK_SIZE,
    token_delay_sec=TOKEN_DELAY_SEC,
)


def _pointy_fast_path_target_label(action: dict | None) -> str:
    if not isinstance(action, dict):
        return ""
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    return str(target.get("label") or target.get("id") or params.get("selector") or "").strip()


def _pointy_fast_path_public_thinking(action: dict | None) -> str:
    label = _pointy_fast_path_target_label(action)
    if label:
        return (
            f"Mình thấy mục tiêu trên màn hình rồi: {label}. "
            "Đây là thao tác chỉ vị trí an toàn, nên Wiii đưa con trỏ tới đúng chỗ ngay "
            "thay vì bắt cậu chờ thêm một vòng suy luận dài."
        )
    return (
        "Mình thấy mục tiêu UI đã đủ rõ trong host context. "
        "Đây là thao tác chỉ vị trí an toàn, nên Wiii đưa con trỏ tới đúng chỗ ngay."
    )


def _pointy_fast_path_answer(action: dict | None) -> str:
    params = action.get("params") if isinstance(action, dict) and isinstance(action.get("params"), dict) else {}
    message = str(params.get("message") or "").strip()
    if message:
        return message
    label = _pointy_fast_path_target_label(action)
    if label:
        return f"Mình đã trỏ vào {label} cho cậu thấy ngay."
    return "Mình đã trỏ đúng vị trí trên giao diện cho cậu."


async def _stream_pointy_fast_path_completion(
    *,
    action: dict,
    session_id: str,
    start_time: float,
    registry,
    trace_id: str,
) -> AsyncGenerator[StreamEvent, None]:
    """Finish safe Pointy highlight turns without paying a full graph/LLM round."""
    thinking = _pointy_fast_path_public_thinking(action)
    answer = _pointy_fast_path_answer(action)
    label = _pointy_fast_path_target_label(action)
    elapsed = max(time.time() - start_time, 0.0)

    yield await create_thinking_start_event(
        "Wiii đang định vị UI",
        "pointy_fast_path",
        summary=thinking,
    )
    yield await create_thinking_delta_event(thinking, node="pointy_fast_path")
    yield await create_thinking_end_event(
        "pointy_fast_path",
        duration_ms=max(1, int(elapsed * 1000)),
    )
    yield await create_answer_event(answer)
    yield await create_metadata_event(
        reasoning_trace={
            "method": "pointy_fast_path",
            "steps": [
                "matched_host_inventory_target",
                "emitted_pointy_action",
                "completed_without_llm",
            ],
        },
        processing_time=time.time() - start_time,
        confidence=1.0,
        model=None,
        provider="deterministic",
        runtime_authoritative=True,
        doc_count=0,
        thinking=thinking,
        thinking_content=thinking,
        agent_type="pointy_fast_path",
        session_id=session_id,
        routing_metadata={
            "method": "pointy_fast_path",
            "intent": "host_ui_navigation",
            "target_id": action.get("target", {}).get("id") if isinstance(action.get("target"), dict) else None,
            "target_label": label or None,
        },
    )
    total_time = time.time() - start_time
    yield await create_done_event(total_time)

    try:
        trace_summary = registry.end_request_trace(trace_id)
        logger.info(
            "[POINTY_FAST_PATH] Completed safe highlight in %.2fs, %d spans",
            total_time,
            trace_summary.get("span_count", 0),
        )
    except Exception as exc:
        logger.debug("[POINTY_FAST_PATH] Trace finalization skipped: %s", exc)



_LABEL_PATTERN = re.compile(r"<label>(.*?)</label>", re.DOTALL | re.IGNORECASE)
# Strip metadata tags that leak node info into thinking text
_METADATA_TAG_PATTERN = re.compile(
    r"^>\s*(?:ĐIỀU HƯỚNG|GIẢI THÍCH|TRA CỨU|TRỰC TIẾP|TỔNG HỢP|ĐÁNH GIÁ|"
    r"Điều hướng|Giải thích|Tra cứu|Trực tiếp|Tổng hợp|Đánh giá)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
# Strip <answer> tags that leak into RAG results
_ANSWER_TAG_PATTERN = re.compile(r"</?answer>|‹/?answer›", re.IGNORECASE)
# Strip visual reference markers and placeholders that LLM puts in answer text
_VISUAL_REF_PATTERN = re.compile(
    r"\{visual-[a-f0-9]+\}|<!-- WiiiVisualBridge:visual-[a-f0-9]+ -->|"
    r"\[Biểu đồ[^\]]*\]|\[Chart[^\]]*\]|\[Visual[^\]]*\]|"
    r"\(Visuals?\s+đang[^)]*\)|\(Visual[^)]*displayed[^)]*\)",
    re.IGNORECASE,
)

async def process_with_multi_agent_streaming(
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict = None,
    domain_id: Optional[str] = None,
    thinking_effort: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Process with the runner-backed multi-agent runtime with token-level streaming.

    v3 REFACTORED (2026-02-09):
    - Token-level answer streaming (12-char chunks with 18ms delays)
    - Real AI thinking content from nodes
    - Proper status → thinking → answer → sources → metadata flow

    Yields StreamEvents at each runtime node:
    - Supervisor: routing decision (thinking event)
    - RAG/TutorAgent: tool calls + actual reasoning (thinking events)
    - GraderAgent: quality score (thinking event)
    - Synthesizer: token-streamed final_response (answer events)
    """
    # Sprint 121b: Ensure session_id is always a string (callers may pass UUID)
    session_id = str(session_id) if session_id else ""
    domain_id = domain_id or settings.default_domain
    start_time = time.time()
    registry = get_agent_registry()

    # Start trace
    trace_id = registry.start_request_trace()
    logger.info("[MULTI_AGENT_STREAM] Started streaming trace: %s", trace_id)

    bus_id = None
    final_state = None

    try:
        # Yield initial status (pipeline — hidden from thinking rail)
        yield await create_status_event("Đang bắt đầu lượt xử lý...", None, details=_PIPELINE_STATUS_DETAILS)

        pointy_fast_path = build_pointy_fast_path_action(query, context)
        if pointy_fast_path:
            pointy_fast_path_action = str(pointy_fast_path.get("action") or "").strip()
            logger.info(
                "[POINTY_FAST_PATH] Emitting %s for target=%s reason=%s before router",
                pointy_fast_path_action,
                pointy_fast_path.get("target", {}).get("id"),
                pointy_fast_path.get("reason"),
            )
            # v3.0 dual-path dispatch:
            # - HIGHLIGHT (read-only): emit `pointy_action` SSE event so the
            #   frontend's onPointyAction handler dispatches DIRECTLY into
            #   the pointy-host CursorRegistry (spring physics + dock cursor),
            #   NO PostMessage roundtrip needed → works on Wiii desktop
            #   standalone AND inside LMS embed.
            # - CLICK (mutating): keep `host_action` event so the host
            #   action bridge handshake gates the click for safety. Only
            #   reaches LMS embed (standalone has no host parent → 30s
            #   timeout there is expected and harmless because click intent
            #   in standalone has no UI to click anyway).
            from app.engine.context.pointy_actions import POINTY_ACTION_CLICK
            if pointy_fast_path_action == POINTY_ACTION_CLICK:
                yield await create_host_action_event(
                    request_id=pointy_fast_path["request_id"],
                    action=pointy_fast_path_action,
                    params=pointy_fast_path["params"],
                    node="pointy_fast_path",
                )
            else:
                # Pointy-action shape mirror tutor_tool_dispatch_runtime.
                # `requestId` (camelCase) is the field onPointyAction reads;
                # we keep `request_id` too for backward compat with any
                # listener that still uses snake_case.
                yield await create_pointy_action_event(
                    payload={
                        "action": pointy_fast_path_action,
                        "requestId": pointy_fast_path["request_id"],
                        "request_id": pointy_fast_path["request_id"],
                        "params": pointy_fast_path["params"],
                        "mode": "highlight",
                    },
                    node="pointy_fast_path",
                )

            if pointy_fast_path_action == POINTY_ACTION_HIGHLIGHT:
                async for completion_event in _stream_pointy_fast_path_completion(
                    action=pointy_fast_path,
                    session_id=session_id,
                    start_time=start_time,
                    registry=registry,
                    trace_id=trace_id,
                ):
                    yield completion_event
                return

        bootstrap = await build_stream_bootstrap_impl(
            query=query,
            user_id=user_id,
            session_id=session_id,
            context=context,
            domain_id=domain_id,
            thinking_effort=thinking_effort,
            provider=provider,
            model=model,
            settings_obj=settings,
            register_event_queue=_register_event_queue,
            cleanup_stale_queues=_cleanup_stale_queues,
            build_domain_config=_build_domain_config,
            build_turn_local_state_defaults=_build_turn_local_state_defaults,
        )
        bus_id = bootstrap["bus_id"]
        event_queue = bootstrap["event_queue"]
        initial_state = bootstrap["initial_state"]
        if pointy_fast_path:
            initial_state["_pointy_fast_path_action"] = pointy_fast_path

        supervisor_thinking_open = False
        supervisor_status_emitted = False

        if event_queue is None:
            try:
                # Keep supervisor progress off the public gray rail.
                # Agent lanes own visible thinking; a public supervisor prelude
                # creates a second narrator voice before the real turn begins.
                yield await create_status_event(
                    NODE_DESCRIPTIONS.get("supervisor", "Đang canh lại hướng xử lý..."),
                    "supervisor",
                    details=_PIPELINE_STATUS_DETAILS,
                )
                supervisor_status_emitted = True
            except Exception as _prelude_exc:
                logger.debug("[STREAM] Supervisor prelude status skipped: %s", _prelude_exc)

        answer_emitted = False
        partial_answer_emitted = False
        rag_answer_text = ""
        # Sprint 70: Track nodes that streamed via event bus (skip bulk re-emit)
        _bus_streamed_nodes: set = set()
        # Sprint 74: Track nodes that streamed answer_delta via bus
        _bus_answer_nodes: set = set()

        # Sprint 166: Preview dedup — track emitted preview IDs per request
        _emitted_preview_ids: set = set()
        # Sprint 166: Preview settings from context (ChatRequest)
        _preview_enabled = bootstrap["preview_enabled"]
        _preview_types = bootstrap["preview_types"]
        _preview_max = bootstrap["preview_max"]

        # Sprint 135: Soul emotion buffer — intercepts first ~512 bytes of answer
        _soul_buffer = bootstrap["soul_buffer"]
        _soul_emotion_emitted = bootstrap["soul_emotion_emitted"]

        # Build config for thread persistence with per-user isolation (Sprint 16)
        # Timeout: max 10 min per graph node, 20 min total
        # Code Studio + Gemini Pro deep thinking can take 3-5 min per generation
        GRAPH_NODE_TIMEOUT = 600
        GRAPH_TOTAL_TIMEOUT = 1200

        # Sprint 70: Concurrent merged-queue pattern for true interleaved streaming
        # Two event sources merged into one queue:
        #   1. Graph node completions ("graph", state_update)
        #   2. Intra-node bus events ("bus", event_dict)
        # This ensures thinking_delta tokens are yielded IMMEDIATELY
        # during LLM inference, not only between node completions.
        _SENTINEL = object()
        merged_queue: asyncio.Queue = asyncio.Queue()

        graph_task = asyncio.create_task(
            forward_graph_events_impl(
                initial_state=initial_state,
                merged_queue=merged_queue,
            )
        )
        bus_task = asyncio.create_task(
            forward_bus_events_impl(
                event_queue=event_queue,
                merged_queue=merged_queue,
                sentinel=_SENTINEL,
                bus_streamed_nodes=_bus_streamed_nodes,
                bus_answer_nodes=_bus_answer_nodes,
                lifecycle_state=initial_state,
            )
        )

        try:
          while True:
            elapsed = time.time() - start_time
            if elapsed > GRAPH_TOTAL_TIMEOUT:
                logger.warning(
                    "[STREAM] Total graph timeout exceeded (%ds)",
                    GRAPH_TOTAL_TIMEOUT,
                )
                yield await create_error_event("Processing timeout exceeded")
                break

            try:
                msg_type, payload = await asyncio.wait_for(
                    merged_queue.get(), timeout=GRAPH_NODE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("[STREAM] Merged queue timeout (%ds)", GRAPH_NODE_TIMEOUT)
                yield await create_error_event("Processing timeout exceeded")
                break

            if msg_type == "bus":
                bus_events, _soul_emotion_emitted, supervisor_status_emitted, supervisor_thinking_open = await handle_bus_message_impl(
                    payload=payload,
                    settings_enable_soul_emotion=settings.enable_soul_emotion,
                    soul_buffer=_soul_buffer,
                    soul_emotion_emitted=_soul_emotion_emitted,
                    supervisor_status_emitted=supervisor_status_emitted,
                    supervisor_thinking_open=supervisor_thinking_open,
                    convert_bus_event=_convert_bus_event,
                    create_emotion_event=create_emotion_event,
                    create_answer_event=create_answer_event,
                )
                for event in bus_events:
                    if getattr(event, "type", None) == "answer":
                        answer_emitted = True
                    yield event
                continue
            elif msg_type == "provider_unavailable":
                if isinstance(payload, ProviderUnavailableError):
                    raise payload
                raise ProviderUnavailableError(
                    provider=str(getattr(payload, "provider", None) or provider or "unknown"),
                    reason_code=str(getattr(payload, "reason_code", None) or "provider_unavailable"),
                    message=str(getattr(payload, "message", None) or "Provider currently unavailable."),
                )
            elif msg_type == "error":
                yield await create_error_event(str(payload))
                break
            elif msg_type == "graph_done":
                drained_events, answer_emitted = await drain_pending_bus_events_impl(
                    merged_queue=merged_queue,
                    event_queue=event_queue,
                    convert_bus_event=_convert_bus_event,
                    answer_emitted=answer_emitted,
                    sentinel=_SENTINEL,
                )
                for event in drained_events:
                    yield event
                break
            elif msg_type != "graph":
                continue

            state_result = await emit_state_update_events_impl(
                state_update=payload,
                query=query,
                user_id=user_id,
                context=context,
                initial_state=initial_state,
                bus_streamed_nodes=_bus_streamed_nodes,
                bus_answer_nodes=_bus_answer_nodes,
                preview_enabled=_preview_enabled,
                preview_types=_preview_types,
                preview_max=_preview_max,
                emitted_preview_ids=_emitted_preview_ids,
                soul_emotion_emitted=_soul_emotion_emitted,
                answer_emitted=answer_emitted,
                partial_answer_emitted=partial_answer_emitted,
                rag_answer_text=rag_answer_text,
                pipeline_status_details=_PIPELINE_STATUS_DETAILS,
                node_descriptions=NODE_DESCRIPTIONS,
                node_labels=_NODE_LABELS,
                preview_snippet_max_length=PREVIEW_SNIPPET_MAX_LENGTH,
                emit_tool_call_events=emit_tool_call_events_impl,
                emit_document_previews=emit_document_previews_impl,
                emit_node_thinking=emit_node_thinking_impl,
                emit_web_previews=emit_web_previews_impl,
                emit_product_previews=emit_product_previews_impl,
                handle_direct_node=handle_direct_node_impl,
                handle_product_search_node=handle_product_search_node_impl,
                extract_thinking_content=_extract_thinking_content,
                render_fallback_narration=_render_fallback_narration,
                create_status_event=create_status_event,
                create_tool_call_event=create_tool_call_event,
                create_tool_result_event=create_tool_result_event,
                create_thinking_start_event=create_thinking_start_event,
                create_thinking_delta_event=create_thinking_delta_event,
                create_thinking_end_event=create_thinking_end_event,
                narration_delta_chunks=_narration_delta_chunks,
                extract_and_stream_emotion_then_answer=_extract_and_stream_emotion_then_answer,
                create_preview_event=create_preview_event,
                create_domain_notice_event=create_domain_notice_event,
                is_pipeline_summary=_is_pipeline_summary,
                logger_obj=logger,
            )
            for event in state_result["events"]:
                yield event
            answer_emitted = state_result["answer_emitted"]
            partial_answer_emitted = state_result["partial_answer_emitted"]
            rag_answer_text = state_result["rag_answer_text"]
            _soul_emotion_emitted = state_result["soul_emotion_emitted"]
            if state_result["final_state"] is not None:
                final_state = state_result["final_state"]

          completion_events, answer_emitted, _soul_emotion_emitted = await emit_stream_completion_impl(
              answer_emitted=answer_emitted,
              final_state=final_state,
              initial_state=initial_state,
              soul_emotion_emitted=_soul_emotion_emitted,
              session_id=session_id,
              context=context,
              start_time=start_time,
              resolve_runtime_llm_metadata=resolve_runtime_llm_metadata,
              create_sources_event=create_sources_event,
              create_metadata_event=create_metadata_event,
              create_done_event=create_done_event,
              record_llm_runtime_observation=record_llm_runtime_observation,
              registry=registry,
              trace_id=trace_id,
              emit_stream_finalization=emit_stream_finalization_impl,
              extract_and_stream_emotion_then_answer=_extract_and_stream_emotion_then_answer,
              is_pipeline_summary=_is_pipeline_summary,
              logger_obj=logger,
          )
          for event in completion_events:
              yield event

        except ProviderUnavailableError:
            raise
        except Exception as e:
            logger.exception("[MULTI_AGENT_STREAM] Inner loop error: %s", e)
            yield await create_error_event("Internal processing error")
            # Sprint 153: Always emit done so frontend exits streaming state
            yield await create_done_event(time.time() - start_time)
        finally:
            # Sprint 70: Stop bus forwarder and clean up tasks
            await cleanup_stream_tasks_impl(
                event_queue=event_queue,
                sentinel=_SENTINEL,
                tasks=[graph_task, bus_task],
            )

    except ProviderUnavailableError:
        registry.end_request_trace(trace_id)
        raise
    except Exception as e:
        logger.exception("[MULTI_AGENT_STREAM] Error: %s", e)
        yield await create_error_event("Internal processing error")
        # Sprint 153: Always emit done so frontend exits streaming state
        yield await create_done_event(time.time() - start_time)
        registry.end_request_trace(trace_id)
    finally:
        # Sprint 139: Clean up tracer from module-level storage
        if final_state:
            from app.engine.multi_agent.graph_trace_store import _cleanup_tracer
            _cleanup_tracer(final_state.get("_trace_id"))
        # Sprint 69+153: Clean up event bus (guard against None bus_id)
        if bus_id:
            _discard_event_queue(bus_id)
