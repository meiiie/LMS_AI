"""Runtime/bootstrap helpers extracted from graph_streaming.py."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Optional

from app.core.constants import MAX_CONTENT_SNIPPET_LENGTH
from app.engine.multi_agent.public_thinking import _resolve_public_thinking_content
from app.engine.multi_agent.runtime_flow_ledger import (
    build_runtime_flow_trace_from_state,
)
from app.engine.reasoning import (
    build_thinking_lifecycle_snapshot,
    merge_thinking_trajectory_state,
)
from app.engine.multi_agent.state import AgentState
from app.services.llm_runtime_audit_service import infer_runtime_completion_degraded_reason

logger = logging.getLogger(__name__)


def _split_model_context(context: dict | None) -> tuple[dict, dict | None]:
    """Remove backend-only continuation data from model-facing context."""

    model_context = dict(context or {})
    host_action_control_feedback = model_context.pop(
        "_host_action_control_feedback",
        None,
    )
    return model_context, host_action_control_feedback


async def build_stream_bootstrap_impl(
    *,
    query: str,
    user_id: str,
    session_id: str,
    context: dict | None,
    domain_id: str,
    thinking_effort: Optional[str],
    provider: Optional[str],
    model: Optional[str] = None,
    settings_obj,
    register_event_queue,
    cleanup_stale_queues,
    build_domain_config,
    build_turn_local_state_defaults,
) -> dict[str, Any]:
    """Build initial streaming state, event bus, and invoke config."""
    domain_config = build_domain_config(domain_id)

    bus_id = str(uuid.uuid4())
    event_queue: asyncio.Queue = asyncio.Queue()
    register_event_queue(bus_id, event_queue)
    cleanup_stale_queues()

    model_context, host_action_control_feedback = _split_model_context(context)
    langchain_messages = model_context.get("langchain_messages", [])
    serialized_messages = []
    for message in langchain_messages:
        if isinstance(message, dict):
            serialized_messages.append(message)
        else:
            serialized_messages.append(
                {
                    "role": getattr(message, "type", "human"),
                    "content": message.content,
                }
            )

    initial_state: AgentState = {
        "query": query,
        "user_id": user_id,
        "session_id": session_id,
        "context": model_context,
        "messages": serialized_messages,
        "current_agent": "",
        "next_agent": "",
        "agent_outputs": {},
        "grader_score": 0.0,
        "grader_feedback": "",
        "final_response": "",
        "sources": [],
        "iteration": 0,
        "max_iterations": 3,
        "error": None,
        "domain_id": domain_id,
        "domain_config": domain_config,
        "thinking_effort": thinking_effort,
        "provider": provider,
        "model": model,
        "routing_metadata": None,
        "organization_id": model_context.get("organization_id"),
        "_event_bus_id": bus_id,
        "_host_action_control_feedback": host_action_control_feedback,
        **build_turn_local_state_defaults(model_context),
    }

    from app.engine.multi_agent.graph_runtime_bindings import (
        _inject_code_studio_context,
        _inject_document_context,
        _inject_host_context,
        _inject_host_session,
        _inject_living_context,
        _inject_operator_context,
        _inject_visual_cognition_context,
        _inject_visual_context,
        _inject_widget_feedback_context,
    )

    host_prompt = _inject_host_context(initial_state)
    if host_prompt:
        initial_state["host_context_prompt"] = host_prompt
    document_prompt = _inject_document_context(initial_state)
    if document_prompt:
        existing_host_prompt = initial_state.get("host_context_prompt", "")
        initial_state["document_context_prompt"] = document_prompt
        initial_state["host_context_prompt"] = (
            f"{existing_host_prompt}\n\n{document_prompt}"
            if existing_host_prompt
            else document_prompt
        )
    host_capabilities_prompt = initial_state.get("host_capabilities_prompt", "")
    if host_capabilities_prompt:
        initial_state["host_capabilities_prompt"] = host_capabilities_prompt
    host_session_prompt = _inject_host_session(initial_state)
    if host_session_prompt:
        initial_state["host_session_prompt"] = host_session_prompt
    operator_prompt = _inject_operator_context(initial_state)
    if operator_prompt:
        initial_state["operator_context_prompt"] = operator_prompt
    living_prompt = _inject_living_context(initial_state)
    if living_prompt:
        initial_state["living_context_prompt"] = living_prompt
    visual_prompt = _inject_visual_context(initial_state)
    if visual_prompt:
        initial_state["visual_context_prompt"] = visual_prompt
    visual_cognition_prompt = _inject_visual_cognition_context(initial_state)
    if visual_cognition_prompt:
        initial_state["visual_cognition_prompt"] = visual_cognition_prompt
    widget_feedback_prompt = _inject_widget_feedback_context(initial_state)
    if widget_feedback_prompt:
        initial_state["widget_feedback_prompt"] = widget_feedback_prompt
    code_studio_prompt = _inject_code_studio_context(initial_state)
    if code_studio_prompt:
        initial_state["code_studio_context_prompt"] = code_studio_prompt

    preview_enabled = settings_obj.enable_preview
    preview_types: set[str] | None = None
    preview_max = getattr(settings_obj, "PREVIEW_MAX_PER_MESSAGE", None)
    if preview_max is None:
        from app.core.constants import PREVIEW_MAX_PER_MESSAGE

        preview_max = PREVIEW_MAX_PER_MESSAGE
    if context:
        if context.get("show_previews") is False:
            preview_enabled = False
        if context.get("preview_types"):
            preview_types = set(context["preview_types"])
        if context.get("preview_max_count"):
            preview_max = int(context["preview_max_count"])

    soul_buffer = None
    soul_emotion_emitted = False
    if settings_obj.enable_soul_emotion:
        from app.engine.soul_emotion_buffer import SoulEmotionBuffer

        soul_buffer = SoulEmotionBuffer(max_bytes=settings_obj.soul_emotion_buffer_bytes)

    invoke_config: dict[str, Any] = {}
    sid = str(session_id) if session_id else ""
    uid = str(user_id) if user_id else ""
    org_id = (context or {}).get("organization_id")
    if sid and uid:
        from app.core.thread_utils import build_thread_id

        thread_id = build_thread_id(uid, sid, org_id=org_id)
        invoke_config = {"configurable": {"thread_id": thread_id}}
    elif sid:
        invoke_config = {"configurable": {"thread_id": sid}}

    from app.core.langsmith import get_langsmith_callback, is_langsmith_enabled

    if is_langsmith_enabled():
        ls_cb = get_langsmith_callback(uid, sid, domain_id)
        if ls_cb:
            invoke_config.setdefault("callbacks", []).append(ls_cb)

    return {
        "domain_config": domain_config,
        "bus_id": bus_id,
        "event_queue": event_queue,
        "initial_state": initial_state,
        "preview_enabled": preview_enabled,
        "preview_types": preview_types,
        "preview_max": preview_max,
        "soul_buffer": soul_buffer,
        "soul_emotion_emitted": soul_emotion_emitted,
        "invoke_config": invoke_config,
    }


async def emit_stream_finalization_impl(
    *,
    final_state,
    initial_state=None,
    session_id: str,
    context: dict | None,
    start_time: float,
    resolve_runtime_llm_metadata,
    create_sources_event,
    create_metadata_event,
    create_done_event,
    record_llm_runtime_observation=None,
    registry,
    trace_id: str,
) -> AsyncGenerator[Any, None]:
    """Emit final sources, metadata, done, and trace completion."""
    effective_state = final_state
    if not effective_state and isinstance(initial_state, dict):
        effective_state = initial_state
    if effective_state and isinstance(initial_state, dict) and effective_state is not initial_state:
        merge_thinking_trajectory_state(effective_state, initial_state)

    sources = []
    if effective_state:
        sources = effective_state.get("sources", [])
        if sources:
            formatted_sources = []
            for source in sources:
                if isinstance(source, dict):
                    formatted_sources.append(
                        {
                            "title": source.get("title", ""),
                            "content": (
                                source.get("content", "")[:MAX_CONTENT_SNIPPET_LENGTH]
                                if source.get("content")
                                else ""
                            ),
                            "image_url": source.get("image_url"),
                            "page_number": source.get("page_number"),
                            "document_id": source.get("document_id"),
                            "content_type": source.get("content_type"),
                            "bounding_boxes": source.get("bounding_boxes"),
                        }
                    )
            if formatted_sources:
                yield await create_sources_event(formatted_sources)

        reasoning_trace = effective_state.get("reasoning_trace")
        reasoning_dict = None
        if reasoning_trace:
            try:
                reasoning_dict = reasoning_trace.model_dump()
            except AttributeError:
                try:
                    reasoning_dict = reasoning_trace.dict()
                except Exception as exc:
                    logger.warning("Failed to serialize reasoning trace: %s", exc)
                    reasoning_dict = None

        processing_time = time.time() - start_time
        mood_data = None
        try:
            from app.core.config import settings as runtime_settings

            if runtime_settings.enable_emotional_state:
                from app.engine.emotional_state import get_emotional_state_manager

                esm = get_emotional_state_manager()
                meta_user_id = (context or {}).get("user_id", "")
                if meta_user_id:
                    es = esm.get_state(meta_user_id)
                    mood_data = {
                        "positivity": round(es.positivity, 3),
                        "energy": round(es.energy, 3),
                        "mood": es.mood.value,
                    }
        except Exception as mood_err:
            logger.debug("[STREAM] Emotional state retrieval failed: %s", mood_err)

        meta_thread_id = ""
        try:
            from app.core.thread_utils import build_thread_id as build_tid

            meta_user_id = (context or {}).get("user_id", "")
            meta_session_id = effective_state.get("session_id", session_id)
            meta_org_id = (context or {}).get("organization_id")
            if meta_user_id and meta_session_id:
                meta_thread_id = build_tid(str(meta_user_id), str(meta_session_id), org_id=meta_org_id)
        except Exception:
            pass

        runtime_llm = resolve_runtime_llm_metadata(effective_state, allow_fallback=False)
        runtime_failover = runtime_llm.get("failover") if isinstance(runtime_llm, dict) else None
        runtime_provider = runtime_llm.get("provider") if isinstance(runtime_llm, dict) else None
        runtime_model = runtime_llm.get("model") if isinstance(runtime_llm, dict) else None
        runtime_authoritative = (
            runtime_llm.get("runtime_authoritative")
            if isinstance(runtime_llm, dict)
            else False
        )
        request_id = str((context or {}).get("request_id") or "").strip() or None
        routing_metadata = effective_state.get("routing_metadata") or {}
        runtime_latency = None
        raw_runtime_latency = effective_state.get("_runtime_latency")
        if isinstance(raw_runtime_latency, dict):
            runtime_latency = {
                "elapsed_ms": raw_runtime_latency.get("elapsed_ms"),
                "timeline": [
                    dict(item)
                    for item in raw_runtime_latency.get("timeline", [])
                    if isinstance(item, dict)
                ],
            }
        agent_type = routing_metadata.get("final_agent") or effective_state.get("next_agent") or "rag_agent"
        if record_llm_runtime_observation is not None:
            try:
                record_llm_runtime_observation(
                    provider=runtime_provider,
                    success=bool(runtime_provider),
                    model_name=runtime_model,
                    note=None if runtime_provider else "chat_stream: stream finalized without authoritative runtime provider.",
                    error=None if runtime_provider else "Missing authoritative runtime provider for stream finalization.",
                    source="chat_stream",
                    failover=runtime_failover,
                    degraded_reason=infer_runtime_completion_degraded_reason(effective_state),
                )
            except Exception as exc:
                logger.debug("[STREAM] Could not record LLM runtime observation: %s", exc)
        public_thinking_content = _resolve_public_thinking_content(
            effective_state,
            fallback=effective_state.get("thinking_content") or "",
        )
        lifecycle_state = effective_state
        if public_thinking_content:
            lifecycle_state = dict(effective_state)
            lifecycle_state["thinking_content"] = public_thinking_content
        thinking_lifecycle = build_thinking_lifecycle_snapshot(
            lifecycle_state,
            fallback=public_thinking_content or effective_state.get("thinking") or "",
            default_node=agent_type,
        )

        yield await create_metadata_event(
            reasoning_trace=reasoning_dict,
            processing_time=processing_time,
            confidence=effective_state.get("grader_score", 0) / 10,
            model=runtime_model,
            provider=runtime_provider,
            runtime_authoritative=runtime_authoritative,
            failover=runtime_failover,
            doc_count=len(sources),
            thinking=public_thinking_content or None,
            thinking_content=public_thinking_content,
            thinking_lifecycle=thinking_lifecycle,
            agent_type=agent_type,
            mood=mood_data,
            session_id=effective_state.get("session_id", session_id),
            evidence_images=effective_state.get("evidence_images", []),
            thread_id=meta_thread_id,
            routing_metadata=routing_metadata,
            runtime_flow_trace=build_runtime_flow_trace_from_state(effective_state),
            runtime_latency=runtime_latency,
            request_id=request_id,
        )

    total_time = time.time() - start_time
    yield await create_done_event(total_time)

    trace_summary = registry.end_request_trace(trace_id)
    logger.info(
        "[MULTI_AGENT_STREAM] Completed in %.2fs, %d spans",
        total_time,
        trace_summary.get("span_count", 0),
    )
