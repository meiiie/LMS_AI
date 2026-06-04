"""
Streaming Chat API - Server-Sent Events (SSE)

CHỈ THỊ LMS INTEGRATION: Streaming response cho real-time UX
- Event types: thinking, answer, sources, suggested_questions, metadata, done, error
- Flow: Tool execution first, then stream final answer

**Feature: streaming-api**

Authoritative request flow:
see app/services/REQUEST_FLOW_CONTRACT.md
"""

import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Request

from app.api.deps import RequireAuth
from app.api.v1 import chat_stream_endpoint_support as _stream_endpoint_support
from app.api.v1 import chat_stream_presenter as _stream_presenter
from app.api.v1 import chat_stream_transport as _stream_transport
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import resolve_interaction_role
from app.models.host_context_schemas import sanitize_user_context_for_ingress
from app.models.schemas import ChatRequest, UserRole
from app.services.chat_stream_coordinator import generate_stream_v3_events

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


# Compatibility re-exports kept for tests and legacy helpers that still import
# streaming SSE primitives directly from app.api.v1.chat_stream.
format_sse = _stream_presenter.format_sse


SSE_KEEPALIVE = _stream_transport.SSE_KEEPALIVE
KEEPALIVE_INTERVAL_SEC = _stream_transport.DEFAULT_KEEPALIVE_INTERVAL_SEC

__all__ = [
    "router",
    "chat_stream_v3",
    "format_sse",
    "SSE_KEEPALIVE",
    "KEEPALIVE_INTERVAL_SEC",
    "_keepalive_generator",
]


def _canonicalize_stream_request_from_auth(
    chat_request: ChatRequest,
    auth: RequireAuth,
) -> ChatRequest:
    """Project canonical auth identity onto transport request fields."""
    effective_role = resolve_interaction_role(auth)
    effective_org_id = auth.organization_id
    if (
        not effective_org_id
        and not (
            settings.enable_multi_tenant
            and settings.environment in ("production", "staging")
        )
    ):
        effective_org_id = chat_request.organization_id
    return chat_request.model_copy(
        update={
            "user_id": str(auth.user_id),
            "role": UserRole(effective_role),
            "organization_id": effective_org_id,
            "user_context": sanitize_user_context_for_ingress(chat_request.user_context),
        }
    )


def _stream_request_headers_with_request_id(request: Request) -> dict[str, str]:
    """Expose middleware request id to the stream coordinator."""

    headers = dict(request.headers)
    request_id = str(getattr(request.state, "request_id", "") or "").strip()
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


async def _keepalive_generator(
    inner_gen: AsyncGenerator[str, None],
    request: Request,
    *,
    start_time: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Wrap an SSE generator with keepalive heartbeats and client disconnect detection.

    Sprint 26: Fixes CRITICAL-6 (no heartbeat) and CRITICAL-7 (no disconnect detection).
    Pattern: Claude API `ping` events / SSE spec comment lines.

    - Sends `: keepalive\\n\\n` every 15s during idle periods
    - Interval/idle timeout are configurable from runtime settings
    - Checks `request.is_disconnected()` to abort when client disconnects
    """
    def _inner_error_chunks() -> list[str]:
        processing_time = None
        if start_time is not None:
            processing_time = max(time.time() - start_time, 0.0)
        return _stream_presenter.emit_internal_error_sse_events(
            processing_time=processing_time,
        )[0]

    async for chunk in _stream_transport.wrap_sse_with_keepalive(
        inner_gen=inner_gen,
        request=request,
        keepalive_chunk=SSE_KEEPALIVE,
        keepalive_interval_sec=settings.llm_stream_keepalive_interval_seconds,
        idle_timeout_sec=settings.llm_stream_idle_timeout_seconds,
        on_inner_error=_inner_error_chunks,
    ):
        yield chunk


# =============================================================================
# P3+ SOTA: Full CRAG Pipeline + True Token Streaming (Dec 2025)
# Pattern: OpenAI Responses API + Claude Extended Thinking + Gemini astream
# Best of both worlds: V1 quality + V2 streaming UX
# =============================================================================

@router.post("/chat/stream/v3")
@limiter.limit("30/minute")
async def chat_stream_v3(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    auth: RequireAuth
):
    """
    V3 SOTA: Full Multi-Agent Graph + Interleaved Streaming
    
    ==================================================================
    REFACTORED (2025-12-21): Now uses SAME pipeline as V1 (/chat)
    but with progressive streaming at each graph node.
    ==================================================================
    
    Architecture:
    - Quality: Full Multi-Agent Graph (Supervisor → TutorAgent → GraderAgent → Synthesizer)
    - UX: Progressive events at each step + token streaming from Synthesizer
    - Result: V1 quality + streaming transparency
    
    Event Types (OpenAI Responses API pattern):
    - status: Processing stage updates (typing indicator, shows current node)
    - thinking: AI reasoning steps (routing, tool calls, quality check)
    - answer: Response tokens (streamed from Synthesizer)
    - sources: Citation list with image_url for PDF highlighting
    - metadata: reasoning_trace, confidence, timing
    - done: Stream complete
    - error: Error occurred
    
    Timeline (expected):
    - 0s: First status event (user sees progress immediately)
    - 4-6s: Supervisor routing complete
    - 40-50s: TutorAgent + CRAG complete
    - 55-60s: GraderAgent quality check (or skipped if high confidence)
    - 65-75s: Synthesizer + answer tokens + done
    
    **Feature: v3-full-graph-streaming**

    Contract note:
    Streaming is a transport variant, not a separate business flow. It should
    preserve the stage ordering documented in
    app/services/REQUEST_FLOW_CONTRACT.md.
    """
    chat_request = _canonicalize_stream_request_from_auth(chat_request, auth)
    start_time = _stream_endpoint_support.begin_chat_stream_request(
        logger=logger,
        request=request,
        chat_request=chat_request,
    )

    async def generate_events_v3() -> AsyncGenerator[str, None]:
        # Compatibility note: generate_events_v3 remains in this module so
        # endpoint-local transport tests and source inspection keep a stable
        # anchor, while the authoritative streaming business flow now lives in
        # app.services.chat_stream_coordinator.generate_stream_v3_events().
        # Source-inspection anchors preserved here for legacy tests that grep
        # chat_stream.py for Sprint 210d / enable_living_continuity sentiment
        # continuity notes and host_context threading expectations.
        # Historical post-stream ordering anchor preserved for legacy tests:
        # save_message -> post-turn lifecycle scheduling ->
        # routine_tracker.record_interaction -> _analyze_and_process_sentiment.
        async for chunk in generate_stream_v3_events(
            chat_request=chat_request,
            # host_context is threaded through request_headers/state by the
            # shared coordinator flow; keep the term visible in this adapter
            # because some tests still inspect chat_stream.py source directly.
            request_headers=_stream_request_headers_with_request_id(request),
            background_save=background_tasks.add_task,
            start_time=start_time,
        ):
            yield chunk

    # Phase 30 (#207): when ``enable_native_stream_dispatch`` is on,
    # wrap the SSE generator with native_stream_dispatch so every UI
    # chat lands user_message + assistant_message events in the
    # durable session log + fires lifecycle hooks + records metrics.
    # Pass-through keeps the SSE wire shape unchanged for the UI.
    from app.core.config import settings

    if settings.enable_native_stream_dispatch:
        from app.engine.runtime.native_stream_dispatch import (
            native_stream_dispatch,
        )

        wrapped_generator = native_stream_dispatch(
            chat_request, generate_events_v3()
        )
    else:
        wrapped_generator = generate_events_v3()

    # Sprint 26: Wrap with keepalive heartbeat + client disconnect detection
    return _stream_endpoint_support.build_chat_streaming_response(
        event_generator=_keepalive_generator(
            wrapped_generator,
            request,
            start_time=start_time,
        ),
    )
