"""Service-level coordinator for chat streaming event orchestration."""

import asyncio
import inspect
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Mapping

from app.core.config import settings
from app.core.exceptions import ProviderUnavailableError
from app.engine.llm_runtime_metadata import resolve_runtime_llm_metadata
from app.services.llm_runtime_audit_service import record_llm_runtime_observation
from app.services.chat_orchestrator_runtime import build_wiii_turn_request
from app.services.model_switch_prompt_service import (
    build_model_switch_prompt_for_failover,
    build_model_switch_prompt_for_unavailable,
)


logger = logging.getLogger(__name__)


_STAGE_HEARTBEAT_FIRST_AFTER_SEC = 2.5
_STAGE_HEARTBEAT_INTERVAL_SEC = 7.0
_RUNTIME_FIRST_EVENT_HEARTBEAT_AFTER_SEC = 3.5
_RUNTIME_IDLE_HEARTBEAT_INTERVAL_SEC = 8.0
_FINALIZABLE_AGENT_NODES = {
    "direct",
    "memory_agent",
    "rag_agent",
    "tutor_agent",
    "product_search_agent",
    "code_studio_agent",
    "grader",
    "colleague_agent",
}


def _stream_agent_for_finalization(event: Any, current_agent: str = "") -> str:
    event_type = str(getattr(event, "type", "") or "")
    content = getattr(event, "content", None)
    if event_type == "metadata" and isinstance(content, Mapping):
        routing_metadata = content.get("routing_metadata")
        if not isinstance(routing_metadata, Mapping):
            routing_metadata = {}
        for candidate in (
            content.get("agent_type"),
            routing_metadata.get("final_agent"),
            routing_metadata.get("selected_agent"),
            routing_metadata.get("target_agent"),
        ):
            normalized = str(candidate or "").strip()
            if normalized in _FINALIZABLE_AGENT_NODES:
                return normalized

    node = str(getattr(event, "node", "") or "").strip()
    if node in _FINALIZABLE_AGENT_NODES:
        return node
    return current_agent


def _plain_context_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _pointy_request_context(chat_request: Any) -> dict[str, Any]:
    user_context = getattr(chat_request, "user_context", None)
    if isinstance(user_context, Mapping):
        host_context = user_context.get("host_context")
        page_context = user_context.get("page_context")
        host_action_feedback = user_context.get("host_action_feedback")
    else:
        host_context = getattr(user_context, "host_context", None)
        page_context = getattr(user_context, "page_context", None)
        host_action_feedback = getattr(user_context, "host_action_feedback", None)

    return {
        "host_context": _plain_context_value(host_context),
        "page_context": _plain_context_value(page_context),
        "host_action_feedback": _plain_context_value(host_action_feedback),
    }


def _has_uploaded_document_context(chat_request: Any) -> bool:
    user_context = getattr(chat_request, "user_context", None)
    if isinstance(user_context, Mapping):
        document_context = user_context.get("document_context")
    else:
        document_context = getattr(user_context, "document_context", None)
    document_context = _plain_context_value(document_context)
    if not isinstance(document_context, Mapping):
        return False

    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return False
    return any(
        isinstance(item, Mapping) and str(item.get("markdown") or "").strip()
        for item in attachments
    )


def _has_image_input(chat_request: Any) -> bool:
    images = getattr(chat_request, "images", None)
    return isinstance(images, list) and any(images)


def _initial_visible_thinking_for_request(chat_request: Any) -> str | None:
    """Return an early, public reasoning cue for context-heavy turns.

    Some providers expose reasoning only after the answer stream is nearly
    complete. For uploads and image turns, that feels wrong in the UI because
    the user needs immediate confidence that Wiii noticed the attached context.
    Keep this as public-facing intent, not private chain-of-thought.
    """
    has_uploaded_context = _has_uploaded_document_context(chat_request)
    has_image_input = _has_image_input(chat_request)
    if not has_uploaded_context and not has_image_input:
        return None

    if has_uploaded_context and has_image_input:
        subject = "tài liệu và ảnh đính kèm"
        evidence_note = "đối chiếu heading, marker, bảng và khung hình/ảnh trước"
    elif has_uploaded_context:
        subject = "tài liệu đính kèm"
        evidence_note = "đọc heading, marker và các đoạn liên quan trong markdown trước"
    else:
        subject = "ảnh đính kèm"
        evidence_note = "kiểm tra dữ liệu ảnh và trạng thái vision trước"

    return (
        f"Mình thấy lượt này có {subject}, nên Wiii sẽ lấy phần upload làm mốc "
        f"thay vì trả lời theo trí nhớ trống. Mình sẽ {evidence_note}, sau đó mới "
        "dùng câu hỏi của cậu để chọn lát cắt cần phân tích. Nếu dữ kiện chưa đủ, "
        "mình sẽ nói rõ chỗ thiếu thay vì đoán mò."
    )


def _pointy_action_label(action: dict[str, Any] | None) -> str:
    if not isinstance(action, dict):
        return ""
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    return str(target.get("label") or target.get("id") or params.get("selector") or "").strip()


def _pointy_action_answer(action: dict[str, Any] | None) -> str:
    params = action.get("params") if isinstance(action, dict) and isinstance(action.get("params"), dict) else {}
    message = str(params.get("message") or "").strip()
    if message:
        return message
    label = _pointy_action_label(action)
    if label:
        return f"Mình đã trỏ vào {label} cho cậu thấy ngay."
    return "Mình đã trỏ đúng vị trí trên giao diện cho cậu."


def _pointy_action_thinking(action: dict[str, Any] | None) -> str:
    label = _pointy_action_label(action)
    if label:
        return (
            f"Mình thấy mục tiêu trên màn hình rồi: {label}. "
            "Đây là thao tác chỉ vị trí an toàn, nên Wiii đưa con trỏ tới đúng chỗ ngay "
            "thay vì bắt cậu chờ thêm một vòng gom ngữ cảnh dài."
        )
    return (
        "Mình thấy mục tiêu UI đã đủ rõ trong host context. "
        "Đây là thao tác chỉ vị trí an toàn, nên Wiii đưa con trỏ tới đúng chỗ ngay."
    )


@dataclass(frozen=True)
class _AwaitUpdate:
    kind: str
    value: Any


class _StreamLatencyTracker:
    """Track stream stages so long waits are visible without changing routing."""

    def __init__(self) -> None:
        self._started_at = time.perf_counter()
        self._active: dict[str, float] = {}
        self._timeline: list[dict[str, Any]] = []

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started_at) * 1000)

    def start(self, stage: str) -> None:
        if stage in self._active:
            return
        self._active[stage] = time.perf_counter()
        self._timeline.append(
            {
                "stage": stage,
                "started_ms": self.elapsed_ms(),
                "status": "running",
            }
        )

    def finish(self, stage: str, status: str = "ok") -> None:
        started_at = self._active.pop(stage, None)
        if started_at is None:
            return
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        for item in reversed(self._timeline):
            if item.get("stage") == stage and item.get("status") == "running":
                item["duration_ms"] = duration_ms
                item["status"] = status
                return

    def status_details(
        self,
        *,
        stage: str,
        request_id: str | None,
        heartbeat_index: int | None = None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "visibility": "status_only",
            "subtype": "heartbeat",
            "stage": stage,
            "elapsed_ms": self.elapsed_ms(),
        }
        if request_id:
            details["request_id"] = request_id
        if heartbeat_index is not None:
            details["heartbeat_index"] = heartbeat_index
        return details

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "elapsed_ms": self.elapsed_ms(),
            "timeline": [dict(item) for item in self._timeline],
        }
        if self._active:
            payload["active"] = [
                {
                    "stage": stage,
                    "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
                }
                for stage, started_at in self._active.items()
            ]
        return payload


async def _await_with_stage_heartbeats(
    awaitable: Awaitable[Any],
    *,
    stage: str,
    tracker: _StreamLatencyTracker,
    request_id: str | None,
    create_status_event,
    heartbeat_message: str,
    node: str,
) -> AsyncGenerator[_AwaitUpdate, None]:
    tracker.start(stage)
    task = asyncio.ensure_future(awaitable)
    timeout = _STAGE_HEARTBEAT_FIRST_AFTER_SEC
    heartbeat_index = 0

    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=timeout)
            if task in done:
                break
            heartbeat_index += 1
            yield _AwaitUpdate(
                "status",
                await create_status_event(
                    heartbeat_message,
                    node=node,
                    details=tracker.status_details(
                        stage=stage,
                        request_id=request_id,
                        heartbeat_index=heartbeat_index,
                    ),
                ),
            )
            timeout = _STAGE_HEARTBEAT_INTERVAL_SEC

        result = await task
    except Exception:
        tracker.finish(stage, status="error")
        raise
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    tracker.finish(stage)
    yield _AwaitUpdate("result", result)


async def _stream_with_idle_heartbeats(
    stream_events,
    *,
    tracker: _StreamLatencyTracker,
    request_id: str | None,
    create_status_event,
) -> AsyncGenerator[Any, None]:
    iterator = stream_events.__aiter__()
    first_event = True

    while True:
        stage = "runtime_first_event" if first_event else "runtime_idle"
        heartbeat_message = (
            "Wiii đang chờ model bắt đầu phản hồi..."
            if first_event
            else "Wiii vẫn đang đợi phần tiếp theo từ runtime..."
        )
        timeout = (
            _RUNTIME_FIRST_EVENT_HEARTBEAT_AFTER_SEC
            if first_event
            else _RUNTIME_IDLE_HEARTBEAT_INTERVAL_SEC
        )
        tracker.start(stage)
        next_task = asyncio.ensure_future(iterator.__anext__())
        heartbeat_index = 0

        try:
            while not next_task.done():
                done, _ = await asyncio.wait({next_task}, timeout=timeout)
                if next_task in done:
                    break
                heartbeat_index += 1
                yield await create_status_event(
                    heartbeat_message,
                    node="runtime",
                    details=tracker.status_details(
                        stage=stage,
                        request_id=request_id,
                        heartbeat_index=heartbeat_index,
                    ),
                )
                timeout = _RUNTIME_IDLE_HEARTBEAT_INTERVAL_SEC

            event = await next_task
        except StopAsyncIteration:
            tracker.finish(stage, status="complete")
            break
        except Exception:
            tracker.finish(stage, status="error")
            raise
        finally:
            if not next_task.done():
                next_task.cancel()
                with suppress(asyncio.CancelledError):
                    await next_task

        tracker.finish(stage)
        first_event = False
        yield event


def _with_latency_metadata(event, tracker: _StreamLatencyTracker):
    if getattr(event, "type", None) != "metadata":
        return event
    content = getattr(event, "content", None)
    if not isinstance(content, dict):
        return event

    from app.engine.multi_agent.stream_utils import StreamEvent

    metadata = dict(content)
    metadata.setdefault("stream_latency", tracker.to_payload())
    return StreamEvent(
        type="metadata",
        content=metadata,
        node=getattr(event, "node", None),
        step=getattr(event, "step", None),
        confidence=getattr(event, "confidence", None),
        details=getattr(event, "details", None),
        subtype=getattr(event, "subtype", None),
    )


def _source_to_payload(source):
    """Serialize Source-like objects for SSE transport."""
    if hasattr(source, "model_dump"):
        return source.model_dump(exclude_none=True)
    if hasattr(source, "dict"):
        return source.dict(exclude_none=True)
    return source


def _expects_native_turn_request(stream_fn) -> bool:
    """Return true when an injected stream function expects one turn request."""

    try:
        parameters = list(inspect.signature(stream_fn).parameters.values())
    except (TypeError, ValueError):
        return False

    return (
        len(parameters) == 1
        and parameters[0].kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    )


async def generate_stream_v3_events(
    *,
    chat_request,
    request_headers: Mapping[str, str],
    background_save,
    start_time: float,
    orchestrator=None,
    stream_fn=None,
) -> AsyncGenerator[str, None]:
    """Generate the authoritative event sequence for /chat/stream/v3.
    """
    from app.api.v1.chat_stream_presenter import (
        StreamPresentationState,
        emit_blocked_sse_events,
        emit_internal_error_sse_events,
        format_sse,
        serialize_stream_event,
    )
    from app.engine.multi_agent.stream_utils import (
        create_answer_event,
        create_done_event,
        create_error_event,
        create_metadata_event,
        create_pointy_action_event,
        create_sources_event,
        create_status_event,
        create_thinking_delta_event,
        create_thinking_end_event,
        create_thinking_start_event,
    )

    yield "retry: 3000\n\n"
    event_counter = 0
    presentation_state = StreamPresentationState()
    latency_tracker = _StreamLatencyTracker()
    request_id = str(
        request_headers.get("X-Request-ID")
        or request_headers.get("x-request-id")
        or ""
    ).strip() or None

    event_counter += 1
    yield format_sse(
        "status",
        {
            "content": "Đang chuẩn bị lượt trả lời...",
            "step": "preparing",
            "node": "system",
            "details": latency_tracker.status_details(
                stage="preparing",
                request_id=request_id,
            ),
        },
        event_id=event_counter,
    )

    fb_cookie = request_headers.get("x-facebook-cookie", "")
    if fb_cookie and settings.enable_facebook_cookie:
        from app.engine.search_platforms.facebook_context import (
            set_facebook_cookie,
        )

        set_facebook_cookie(fb_cookie)

    try:
        requested_provider = getattr(chat_request, "provider", None)
        if requested_provider and requested_provider != "auto":
            from app.services.llm_selectability_service import ensure_provider_is_selectable

            has_uploaded_context = _has_uploaded_document_context(chat_request)
            has_image_input = _has_image_input(chat_request)
            try:
                ensure_provider_is_selectable(requested_provider)
            except ProviderUnavailableError:
                if not (has_uploaded_context or has_image_input):
                    raise
                logger.warning(
                    "[STREAM-V3] Requested provider is not selectable for uploaded media context; "
                    "falling back to auto routing (provider=%s uploaded=%s images=%s)",
                    requested_provider,
                    has_uploaded_context,
                    has_image_input,
                )
                try:
                    setattr(chat_request, "provider", "auto")
                    requested_provider = "auto"
                except Exception:
                    logger.debug("[STREAM-V3] Could not rewrite uploaded-file provider to auto")

        uses_native_turn_stream = stream_fn is None
        if stream_fn is None:
            from app.engine.multi_agent.streaming_runtime import (
                stream_wiii_turn,
            )

            stream_fn = stream_wiii_turn
        else:
            uses_native_turn_stream = _expects_native_turn_request(stream_fn)

        if orchestrator is None:
            from app.services.chat_service import get_chat_service

            chat_svc = get_chat_service()
            orchestrator = chat_svc._orchestrator

        prepared_turn = None
        async for update in _await_with_stage_heartbeats(
            orchestrator.prepare_turn(
                request=chat_request,
                background_save=background_save,
                persist_user_message_immediately=True,
            ),
            stage="prepare_turn",
            tracker=latency_tracker,
            request_id=request_id,
            create_status_event=create_status_event,
            heartbeat_message="Wiii đang mở phiên và kiểm tra quyền truy cập...",
            node="system",
        ):
            if update.kind == "status":
                chunks, event_counter, should_stop = serialize_stream_event(
                    event=update.value,
                    event_counter=event_counter,
                    enable_artifacts=settings.enable_artifacts,
                    presentation_state=presentation_state,
                )
                for chunk in chunks:
                    yield chunk
                if should_stop:
                    return
            else:
                prepared_turn = update.value
        if prepared_turn is None:
            raise RuntimeError("prepare_turn did not return a turn context")
        resolved_org_id = prepared_turn.request_scope.organization_id
        resolved_domain_id = prepared_turn.request_scope.domain_id
        effective_session_id = prepared_turn.session_id
        effective_session_id_str = str(effective_session_id)

        if prepared_turn.validation.blocked:
            blocked_chunks, event_counter = (
                emit_blocked_sse_events(
                    blocked_response=prepared_turn.validation.blocked_response,
                    session_id=effective_session_id_str,
                    processing_time=time.time() - start_time,
                    event_counter=event_counter,
                )
            )
            for chunk in blocked_chunks:
                yield chunk
            return

        finalization_context = prepared_turn.chat_context
        use_multi_agent = getattr(
            orchestrator,
            "_use_multi_agent",
            getattr(settings, "use_multi_agent", True),
        )
        try:
            from app.services.chat_stream_visual_fast_path import (
                build_visual_fast_path_result,
            )

            visual_fast_path = await build_visual_fast_path_result(chat_request)
        except Exception as visual_fast_path_err:
            logger.debug(
                "[STREAM-V3] Structured visual fast-path skipped: %s",
                visual_fast_path_err,
            )
            visual_fast_path = None

        if visual_fast_path is not None:
            visual_started_ms = latency_tracker.elapsed_ms()
            visual_events = [
                await create_thinking_start_event(
                    "Wiii đang dựng minh họa",
                    "visual_fast_path",
                    summary=visual_fast_path.thinking,
                ),
                await create_thinking_delta_event(
                    visual_fast_path.thinking,
                    node="visual_fast_path",
                ),
                await create_thinking_end_event(
                    "visual_fast_path",
                    duration_ms=max(1, latency_tracker.elapsed_ms() - visual_started_ms),
                ),
                *visual_fast_path.events,
                await create_answer_event(visual_fast_path.answer),
                await create_metadata_event(
                    reasoning_trace={
                        "method": "structured_visual_fast_path",
                        "steps": [
                            "prepared_turn_validated",
                            "matched_explicit_visual_creation",
                            "emitted_structured_visual_lifecycle",
                        ],
                    },
                    processing_time=time.time() - start_time,
                    confidence=1.0,
                    model=None,
                    provider="deterministic",
                    runtime_authoritative=True,
                    doc_count=0,
                    thinking=visual_fast_path.thinking,
                    thinking_content=visual_fast_path.thinking,
                    agent_type="visual_fast_path",
                    session_id=effective_session_id_str,
                    request_id=request_id,
                    routing_metadata=visual_fast_path.routing_metadata,
                    stream_latency=latency_tracker.to_payload(),
                    streaming_version="v3-visual_fast_path",
                ),
                await create_done_event(time.time() - start_time),
            ]

            for event in visual_events:
                chunks, event_counter, should_stop = serialize_stream_event(
                    event=event,
                    event_counter=event_counter,
                    enable_artifacts=settings.enable_artifacts,
                    presentation_state=presentation_state,
                )
                for chunk in chunks:
                    yield chunk
                if should_stop:
                    return

            try:
                orchestrator.finalize_response_turn(
                    session_id=effective_session_id,
                    user_id=str(chat_request.user_id),
                    user_role=chat_request.role,
                    message=chat_request.message,
                    response_text=visual_fast_path.answer,
                    context=finalization_context,
                    domain_id=resolved_domain_id,
                    organization_id=resolved_org_id,
                    current_agent="visual_fast_path",
                    background_save=background_save,
                    save_response_immediately=False,
                    include_lms_insights=False,
                    continuity_channel="web",
                    transport_type="stream",
                )
            except Exception as finalize_err:
                logger.warning(
                    "[STREAM-V3] Visual fast-path finalization failed: %s",
                    finalize_err,
                )
            return

        pointy_highlight_action_name = "ui.highlight"
        try:
            from app.engine.context.pointy_actions import POINTY_ACTION_HIGHLIGHT
            from app.engine.context.pointy_fast_path import build_pointy_fast_path_action

            pointy_highlight_action_name = POINTY_ACTION_HIGHLIGHT
            pointy_fast_path = build_pointy_fast_path_action(
                chat_request.message,
                _pointy_request_context(chat_request),
            )
        except Exception as pointy_err:
            logger.debug("[STREAM-V3] Prepared Pointy fast-path skipped: %s", pointy_err)
            pointy_fast_path = None

        pointy_fast_path_action = (
            str(pointy_fast_path.get("action") or "").strip()
            if isinstance(pointy_fast_path, dict)
            else ""
        )
        if pointy_fast_path_action == pointy_highlight_action_name:
            pointy_answer = _pointy_action_answer(pointy_fast_path)
            pointy_thinking = _pointy_action_thinking(pointy_fast_path)
            pointy_label = _pointy_action_label(pointy_fast_path)
            pointy_started_ms = latency_tracker.elapsed_ms()
            pointy_events = [
                await create_pointy_action_event(
                    payload={
                        "action": pointy_fast_path_action,
                        "requestId": pointy_fast_path["request_id"],
                        "request_id": pointy_fast_path["request_id"],
                        "params": pointy_fast_path["params"],
                        "mode": "highlight",
                    },
                    node="pointy_fast_path",
                ),
                await create_thinking_start_event(
                    "Wiii đang định vị UI",
                    "pointy_fast_path",
                    summary=pointy_thinking,
                ),
                await create_thinking_delta_event(
                    pointy_thinking,
                    node="pointy_fast_path",
                ),
                await create_thinking_end_event(
                    "pointy_fast_path",
                    duration_ms=max(1, latency_tracker.elapsed_ms() - pointy_started_ms),
                ),
                await create_answer_event(pointy_answer),
                await create_metadata_event(
                    reasoning_trace={
                        "method": "pointy_prepared_fast_path",
                        "steps": [
                            "prepared_turn_validated",
                            "matched_host_inventory_target",
                            "completed_without_context_build_or_llm",
                        ],
                    },
                    processing_time=time.time() - start_time,
                    confidence=1.0,
                    model=None,
                    provider="deterministic",
                    runtime_authoritative=True,
                    doc_count=0,
                    thinking=pointy_thinking,
                    thinking_content=pointy_thinking,
                    agent_type="pointy_fast_path",
                    session_id=effective_session_id_str,
                    request_id=request_id,
                    routing_metadata={
                        "method": "pointy_prepared_fast_path",
                        "intent": "host_ui_navigation",
                        "target_id": pointy_fast_path.get("target", {}).get("id")
                        if isinstance(pointy_fast_path.get("target"), dict)
                        else None,
                        "target_label": pointy_label or None,
                    },
                    stream_latency=latency_tracker.to_payload(),
                    streaming_version="v3-pointy_fast_path",
                ),
                await create_done_event(time.time() - start_time),
            ]

            for event in pointy_events:
                chunks, event_counter, should_stop = serialize_stream_event(
                    event=event,
                    event_counter=event_counter,
                    enable_artifacts=settings.enable_artifacts,
                    presentation_state=presentation_state,
                )
                for chunk in chunks:
                    yield chunk
                if should_stop:
                    return

            try:
                orchestrator.finalize_response_turn(
                    session_id=effective_session_id,
                    user_id=str(chat_request.user_id),
                    user_role=chat_request.role,
                    message=chat_request.message,
                    response_text=pointy_answer,
                    context=finalization_context,
                    domain_id=resolved_domain_id,
                    organization_id=resolved_org_id,
                    current_agent="pointy_fast_path",
                    background_save=background_save,
                    save_response_immediately=False,
                    include_lms_insights=False,
                    continuity_channel="web",
                    transport_type="stream",
                )
            except Exception as finalize_err:
                logger.warning(
                    "[STREAM-V3] Pointy fast-path finalization failed: %s",
                    finalize_err,
                )
            logger.info(
                "[STREAM-V3] Completed in %.3fs (prepared pointy fast path)",
                time.time() - start_time,
            )
            return

        if not use_multi_agent:
            logger.warning("[STREAM-V3] Multi-Agent disabled, using sync fallback path")
            fallback_status = await create_status_event(
                "Wiii đang mở đường trả lời nhanh...",
                node="direct",
                details={
                    "mode": "fallback",
                    "subtype": "heartbeat",
                    "visibility": "status_only",
                },
            )
            chunks, event_counter, should_stop = serialize_stream_event(
                event=fallback_status,
                event_counter=event_counter,
                enable_artifacts=settings.enable_artifacts,
                presentation_state=presentation_state,
            )
            for chunk in chunks:
                yield chunk
            if should_stop:
                return

            fallback_result = await orchestrator.process_without_multi_agent(
                finalization_context,
            )
            full_answer = fallback_result.message or ""
            processing_time = time.time() - start_time
            fallback_meta = dict(fallback_result.metadata or {})
            runtime_llm = resolve_runtime_llm_metadata(fallback_meta)
            fallback_thinking = (
                fallback_meta.get("thinking")
                or fallback_result.thinking
            )
            fallback_thinking_content = (
                fallback_meta.get("thinking_content")
                or fallback_thinking
                or ""
            )
            try:
                record_llm_runtime_observation(
                    provider=runtime_llm["provider"],
                    success=bool(runtime_llm["provider"]),
                    model_name=runtime_llm["model"],
                    note=None if runtime_llm["provider"] else "chat_stream:fallback: completed without authoritative runtime provider.",
                    error=None if runtime_llm["provider"] else "Missing authoritative runtime provider for fallback stream response.",
                    source="chat_stream:fallback",
                    failover=runtime_llm["failover"],
                )
            except Exception as exc:
                logger.debug("[STREAM-V3] Could not record fallback runtime observation: %s", exc)
            extra_meta = {
                key: value for key, value in fallback_meta.items()
                if key not in {
                    "agent_type",
                    "confidence",
                    "model",
                    "provider",
                    "processing_time",
                    "reasoning_trace",
                    "session_id",
                    "streaming_version",
                    "thinking",
                    "thinking_content",
                    "failover",
                    "routing_metadata",
                    "request_id",
                }
            }

            fallback_events = [
                await create_status_event(
                    "Đang tiếp tục trả lời...",
                    node="direct",
                    details={"mode": fallback_meta.get("mode", "fallback")},
                ),
                await create_answer_event(full_answer),
            ]

            if fallback_result.sources:
                fallback_events.append(
                    await create_sources_event(
                        [_source_to_payload(source) for source in fallback_result.sources]
                    )
                )

            fallback_events.extend(
                [
                    await create_metadata_event(
                        processing_time=processing_time,
                        agent_type=getattr(fallback_result.agent_type, "value", str(fallback_result.agent_type)),
                        model=runtime_llm["model"],
                        provider=runtime_llm["provider"],
                        failover=runtime_llm["failover"],
                        model_switch_prompt=build_model_switch_prompt_for_failover(
                            failover=runtime_llm["failover"],
                            requested_provider=getattr(chat_request, "provider", None),
                        ),
                        session_id=effective_session_id_str,
                        thinking=fallback_thinking,
                        thinking_content=fallback_thinking_content,
                        streaming_version=f"v3-{fallback_meta.get('mode', 'fallback')}",
                        request_id=request_id,
                        routing_metadata=fallback_meta.get("routing_metadata"),
                        **extra_meta,
                    ),
                    await create_done_event(processing_time),
                ]
            )

            for event in fallback_events:
                chunks, event_counter, should_stop = serialize_stream_event(
                    event=event,
                    event_counter=event_counter,
                    enable_artifacts=settings.enable_artifacts,
                    presentation_state=presentation_state,
                )
                for chunk in chunks:
                    yield chunk
                if should_stop:
                    return

            try:
                orchestrator.finalize_response_turn(
                    session_id=effective_session_id,
                    user_id=str(chat_request.user_id),
                    user_role=chat_request.role,
                    message=chat_request.message,
                    response_text=full_answer,
                    context=finalization_context,
                    domain_id=resolved_domain_id,
                    organization_id=resolved_org_id,
                    current_agent=(fallback_result.metadata or {}).get("current_agent", ""),
                    background_save=background_save,
                    save_response_immediately=True,
                    include_lms_insights=True,
                    continuity_channel="web",
                    transport_type="stream",
                )
            except Exception as finalize_err:
                logger.warning(
                    "[STREAM-V3] Fallback post-response finalization failed: %s",
                    finalize_err,
                )
            return

        _provider = requested_provider
        context_status = await create_status_event(
            "Wiii đang gom ngữ cảnh và trí nhớ...",
            node="context",
            details={
                "mode": "native_turn",
                **latency_tracker.status_details(
                    stage="context",
                    request_id=request_id,
                ),
            },
        )
        chunks, event_counter, should_stop = serialize_stream_event(
            event=context_status,
            event_counter=event_counter,
            enable_artifacts=settings.enable_artifacts,
            presentation_state=presentation_state,
        )
        for chunk in chunks:
            yield chunk
        if should_stop:
            return

        try:
            execution_input = None
            async for update in _await_with_stage_heartbeats(
                orchestrator.build_multi_agent_execution_input(
                    request=chat_request,
                    prepared_turn=prepared_turn,
                    include_streaming_fields=True,
                    thinking_effort=getattr(
                        chat_request,
                        "thinking_effort",
                        None,
                    ),
                    provider=_provider,
                    request_id=request_id,
                ),
                stage="build_execution_input",
                tracker=latency_tracker,
                request_id=request_id,
                create_status_event=create_status_event,
                heartbeat_message="Wiii đang gom trí nhớ, ngữ cảnh và tín hiệu trang...",
                node="context",
            ):
                if update.kind == "status":
                    chunks, event_counter, should_stop = serialize_stream_event(
                        event=update.value,
                        event_counter=event_counter,
                        enable_artifacts=settings.enable_artifacts,
                        presentation_state=presentation_state,
                    )
                    for chunk in chunks:
                        yield chunk
                    if should_stop:
                        return
                else:
                    execution_input = update.value
            if execution_input is None:
                raise RuntimeError(
                    "build_multi_agent_execution_input did not return context"
                )
        except Exception as ctx_err:
            logger.warning(
                "[STREAM-V3] Full context build failed, using minimal: %s",
                ctx_err,
            )
            latency_tracker.start("minimal_execution_input")
            try:
                execution_input = (
                    orchestrator.build_minimal_multi_agent_execution_input(
                        request=chat_request,
                        prepared_turn=prepared_turn,
                        thinking_effort=getattr(
                            chat_request,
                            "thinking_effort",
                            None,
                        ),
                        provider=_provider,
                        request_id=request_id,
                    )
                )
            except Exception:
                latency_tracker.finish("minimal_execution_input", status="error")
                raise
            latency_tracker.finish("minimal_execution_input")

        accumulated_answer: list[str] = []
        saw_done_event = False
        stream_current_agent = ""
        answer_started = False

        latency_tracker.start("build_turn_request")
        try:
            turn_request = build_wiii_turn_request(
                execution_input=execution_input,
                organization_id=resolved_org_id,
            )
        except Exception:
            latency_tracker.finish("build_turn_request", status="error")
            raise
        latency_tracker.finish("build_turn_request")

        early_context_thinking = _initial_visible_thinking_for_request(chat_request)
        if early_context_thinking:
            early_thinking_started_ms = latency_tracker.elapsed_ms()
            early_thinking_events = [
                await create_thinking_start_event(
                    "Wiii đang đọc bối cảnh đính kèm",
                    "context",
                    summary=early_context_thinking,
                ),
                await create_thinking_delta_event(
                    early_context_thinking,
                    node="context",
                ),
                await create_thinking_end_event(
                    "context",
                    duration_ms=max(
                        1,
                        latency_tracker.elapsed_ms() - early_thinking_started_ms,
                    ),
                ),
            ]
            for early_event in early_thinking_events:
                chunks, event_counter, should_stop = serialize_stream_event(
                    event=early_event,
                    event_counter=event_counter,
                    enable_artifacts=settings.enable_artifacts,
                    presentation_state=presentation_state,
                )
                for chunk in chunks:
                    yield chunk
                if should_stop:
                    return

        stream_events = (
            stream_fn(turn_request)
            if uses_native_turn_stream
            else stream_fn(**turn_request.to_runtime_kwargs())
        )

        # Phase 35 — stream-resume: ensure finalize ALWAYS runs even if the
        # stream is interrupted (client disconnect, error, healthcheck race).
        # Previously `if should_stop: return` skipped finalize entirely, so a
        # 90-second pipeline that completed but lost the SSE channel before
        # done event would have NO assistant_message persisted. With finalize
        # in a try/finally block, the answer text reaches the durable
        # session_events log no matter what — FE can fetch via
        # /api/v1/threads/{id}/messages on reconnect.
        early_stop_reason: str | None = None
        try:
            async for event in _stream_with_idle_heartbeats(
                stream_events,
                tracker=latency_tracker,
                request_id=request_id,
                create_status_event=create_status_event,
            ):
                event = _with_latency_metadata(event, latency_tracker)
                stream_current_agent = _stream_agent_for_finalization(
                    event,
                    stream_current_agent,
                )
                if event.type == "answer":
                    accumulated_answer.append(event.content)
                    answer_started = True
                elif event.type == "done":
                    saw_done_event = True
                elif early_context_thinking and event.type in {
                    "thinking_start",
                    "thinking_delta",
                    "thinking_end",
                }:
                    # Upload/image turns already receive one early public
                    # context-thinking block. Runtime/provider thinking may
                    # arrive either before or after answer tokens depending on
                    # the selected path; showing both creates duplicate UX.
                    # Keep the visible timeline to one coherent context block.
                    continue

                chunks, event_counter, should_stop = (
                    serialize_stream_event(
                        event=event,
                        event_counter=event_counter,
                        enable_artifacts=settings.enable_artifacts,
                        presentation_state=presentation_state,
                    )
                )
                if not chunks and event.type not in {"artifact"}:
                    logger.warning(
                        "[STREAM-V3] Unknown event type: %s",
                        event.type,
                    )

                for chunk in chunks:
                    yield chunk

                # `done` is a terminal wire event. Do not ask the underlying
                # async generator for one more item just to observe
                # StopAsyncIteration: the idle-heartbeat wrapper can otherwise
                # hold the UI in a streaming state for another full idle tick.
                if event.type == "done":
                    break

                if should_stop:
                    early_stop_reason = "should_stop_signal"
                    break

                await asyncio.sleep(0.01)
        except (asyncio.CancelledError, GeneratorExit) as cancel_err:
            # Client disconnected mid-stream. Persist what we have anyway.
            early_stop_reason = type(cancel_err).__name__
            logger.warning(
                "[STREAM-V3] Stream cancelled (%s) — persisting partial answer",
                early_stop_reason,
            )

        full_answer = "".join(accumulated_answer) if accumulated_answer else ""
        try:
            if early_stop_reason and full_answer:
                logger.info(
                    "[STREAM-V3] Persisting partial answer (%d chars) after %s",
                    len(full_answer), early_stop_reason,
                )
            orchestrator.finalize_response_turn(
                session_id=effective_session_id,
                user_id=str(chat_request.user_id),
                user_role=chat_request.role,
                message=chat_request.message,
                response_text=full_answer,
                context=finalization_context,
                domain_id=resolved_domain_id,
                organization_id=resolved_org_id,
                current_agent=stream_current_agent,
                background_save=background_save,
                save_response_immediately=bool(early_stop_reason),
                include_lms_insights=True,
                continuity_channel="web",
                transport_type="stream",
            )
        except Exception as finalize_err:
            logger.warning(
                "[STREAM-V3] Post-response finalization failed: %s",
                finalize_err,
            )

        processing_time = time.time() - start_time
        logger.info(
            "[STREAM-V3] Completed in %.3fs (full graph)",
            processing_time,
        )
        if not saw_done_event:
            done_event = await create_done_event(processing_time)
            done_chunks, event_counter, _ = serialize_stream_event(
                event=done_event,
                event_counter=event_counter,
                enable_artifacts=settings.enable_artifacts,
                presentation_state=presentation_state,
            )
            for chunk in done_chunks:
                yield chunk

    except ProviderUnavailableError as exc:
        logger.warning(
            "[STREAM-V3] Requested provider unavailable: provider=%s reason=%s",
            exc.provider,
            exc.reason_code,
        )
        try:
            record_llm_runtime_observation(
                provider=exc.provider,
                success=False,
                error=exc.message,
                note=(
                    f"chat_stream:error: requested provider {exc.provider} unavailable"
                    f"{f' ({exc.reason_code})' if exc.reason_code else ''}."
                ),
                source="chat_stream:error",
            )
        except Exception as audit_exc:
            logger.debug("[STREAM-V3] Could not record unavailable provider audit: %s", audit_exc)
        error_event = await create_error_event(exc.message)
        error_event.content["provider"] = exc.provider
        error_event.content["reason_code"] = exc.reason_code
        error_event.content["model_switch_prompt"] = (
            build_model_switch_prompt_for_unavailable(
                provider=exc.provider,
                reason_code=exc.reason_code,
            )
        )
        error_chunks, event_counter, _ = serialize_stream_event(
            event=error_event,
            event_counter=event_counter,
            enable_artifacts=settings.enable_artifacts,
            presentation_state=presentation_state,
        )
        for chunk in error_chunks:
            yield chunk
        done_event = await create_done_event(time.time() - start_time)
        done_chunks, _, _ = serialize_stream_event(
            event=done_event,
            event_counter=event_counter + 1,
            enable_artifacts=settings.enable_artifacts,
            presentation_state=presentation_state,
        )
        for chunk in done_chunks:
            yield chunk
    except Exception as exc:
        import traceback

        tb = traceback.format_exc()
        logger.error("[STREAM-V3] Error: %s\n%s", exc, tb)
        error_chunks, _ = emit_internal_error_sse_events(
            processing_time=time.time() - start_time,
        )
        for chunk in error_chunks:
            yield chunk
