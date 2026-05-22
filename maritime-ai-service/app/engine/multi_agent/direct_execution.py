"""Direct response execution — LLM invocation, streaming, tool rounds.

Extracted from graph.py — handles the core execution loop for the direct
response lane including answer streaming, heartbeats, and multi-round
tool calling.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from app.engine.multi_agent.direct_intent import (
    _looks_emotional_support_turn,
    _looks_identity_selfhood_turn,
    _looks_selfhood_followup_turn,
)
from app.engine.multi_agent.direct_wait_surface import (
    _build_direct_wait_heartbeat_text,
)
from app.engine.multi_agent.direct_tool_rounds_runtime import (
    execute_direct_tool_rounds_impl,
)
from app.engine.multi_agent.direct_response_runtime import (
    extract_direct_response_impl,
    resolve_direct_answer_primary_timeout_impl,
    resolve_direct_answer_timeout_profile_impl,
)
from app.engine.multi_agent.state import AgentState

from app.engine.multi_agent.direct_prompt_tool_binding import _resolve_tool_choice
from app.engine.multi_agent.direct_runtime_bindings import (
    _extract_runtime_target,
    _is_native_runtime_handle,
    _remember_runtime_target,
    _stream_openai_compatible_answer_with_route,
    _truncate_before_code_dump,
)
from app.engine.multi_agent.direct_stream_text_runtime import (
    _compute_visible_answer_delta,
    _extract_message_text,
    _extract_stream_chunk_parts,
    _normalize_direct_visible_thinking_impl,
    _split_visible_answer_chunks,
    _split_visible_thinking_chunks,
    _strip_incomplete_thinking_blocks,
)
from app.engine.reasoning import (
    align_visible_thinking_language,
    sanitize_visible_reasoning_text,
    should_align_visible_thinking_language,
)
from app.engine.llm_runtime_metadata import record_runtime_failover_event

logger = logging.getLogger(__name__)


def _looks_primary_timeout_failure(exc: Exception) -> bool:
    text = " ".join(str(exc or "").split()).strip().lower()
    if not text:
        return False
    return "timed out" in text or "timeout" in text



async def _normalize_direct_visible_thinking(
    text: str,
    *,
    response_language: str,
    alignment_mode: str | None,
    llm: Any,
) -> str:
    """Compatibility wrapper for tests that patch direct_execution reasoning hooks."""
    return await _normalize_direct_visible_thinking_impl(
        text,
        response_language=response_language,
        alignment_mode=alignment_mode,
        llm=llm,
        align_visible_thinking_language_fn=align_visible_thinking_language,
        should_align_visible_thinking_language_fn=should_align_visible_thinking_language,
        sanitize_visible_reasoning_text_fn=sanitize_visible_reasoning_text,
    )

def _should_prefer_native_langchain_stream(
    *,
    provider_name: str,
    node: str,
) -> bool:
    """Prefer provider-native LangChain streaming when compat streaming loses thought quality.

    On March 31, 2026, Google direct no-tool turns were returning good answers via the
    OpenAI-compatible stream path but silently dropping visible native thought in live SSE.
    The native LangChain ``astream`` path, however, surfaced Gemini thinking blocks correctly.

    UPDATE (2026-04-19, De-LangChaining Phase 2): Disabled for direct node so that the
    Native AsyncOpenAI SDK path handles streaming instead. The Native SDK path provides
    real-time reasoning_content extraction + <thinking> tag parsing + thinking event
    emission, giving 95-100% thinking coverage instead of LangChain's string-only content.
    """
    normalized_provider = str(provider_name or "").strip().lower()
    normalized_node = str(node or "").strip().lower()
    # Phase 2: route direct node through Native SDK for thinking event coverage
    if normalized_node == "direct":
        return False
    return normalized_provider == "google"


def _should_prefer_invoke_backfilled_stream(
    *,
    node: str,
    query: str,
    state: AgentState | None = None,
) -> bool:
    """Use final-result playback on turns where live thought is less trustworthy."""
    normalized_node = str(node or "").strip().lower()
    if normalized_node != "direct":
        return False
    return (
        _looks_identity_selfhood_turn(query)
        or _looks_selfhood_followup_turn(query, state)
        or _looks_emotional_support_turn(query)
    )


async def _preserve_ai_message_metadata(
    merged_chunk: Any,
    *,
    visible_text: str,
    response_language: str | None,
    alignment_mode: str | None = None,
    llm: Any = None,
):
    """Keep native message metadata when stream rendering trims visible content.

    Some providers stream plain answer deltas but only attach thought metadata on the
    final merged message. If we replace that object with a bare response object,
    sync/stream parity breaks and visible-thought review loses the model-authored
    reasoning that is still present in the final object.
    """
    from app.engine.native_chat_runtime import make_assistant_message

    preserved: dict[str, Any] = {}
    additional_kwargs = dict(getattr(merged_chunk, "additional_kwargs", None) or {})
    response_metadata = dict(getattr(merged_chunk, "response_metadata", None) or {})

    raw_thinking = str(
        response_metadata.get("thinking_content")
        or response_metadata.get("thinking")
        or additional_kwargs.get("thinking")
        or ""
    ).strip()
    if raw_thinking:
        sanitized_thinking = sanitize_visible_reasoning_text(raw_thinking).strip() or raw_thinking
        if should_align_visible_thinking_language(
            sanitized_thinking,
            target_language=response_language,
        ):
            try:
                aligned_thinking = await align_visible_thinking_language(
                    sanitized_thinking,
                    target_language=response_language,
                    alignment_mode=alignment_mode,
                    llm=llm,
                )
                if aligned_thinking and not should_align_visible_thinking_language(
                    aligned_thinking,
                    target_language=response_language,
                ):
                    sanitized_thinking = aligned_thinking.strip()
            except Exception:
                pass
        response_metadata["thinking_content"] = sanitized_thinking
        if "thinking" in response_metadata:
            response_metadata["thinking"] = sanitized_thinking
        if additional_kwargs.get("thinking") is not None:
            additional_kwargs["thinking"] = sanitized_thinking

    if additional_kwargs:
        preserved["additional_kwargs"] = additional_kwargs
    if response_metadata:
        preserved["response_metadata"] = response_metadata

    for field_name in (
        "tool_calls",
        "invalid_tool_calls",
        "usage_metadata",
        "id",
        "name",
    ):
        value = getattr(merged_chunk, field_name, None)
        if value in (None, "", [], {}):
            continue
        preserved[field_name] = value
    return make_assistant_message(visible_text, **preserved)

async def _ainvoke_with_fallback(
    llm, messages, tools=None, tool_choice=None, tier="moderate",
    provider: str | None = None,
    resolved_provider: str | None = None,
    failover_mode: str | None = None,
    allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    push_event=None,
    primary_timeout: float | None = None,
    timeout_profile: str | None = None,
    state: Optional[AgentState] = None,
):
    """Invoke LLM with request-scoped runtime failover.

    Delegates timeout / circuit-breaker / catch-and-switch logic to
    ``ainvoke_with_failover`` in ``llm_pool``. Graph-specific extras stay
    here: SSE ``model_switch`` emission and fallback tool re-binding with
    provider-aware ``tool_choice`` translation.
    """
    from app.engine.llm_pool import (
        FAILOVER_MODE_AUTO,
        FAILOVER_MODE_PINNED,
        ainvoke_with_failover,
    )

    normalized_provider = str(provider or "").strip().lower()
    concrete_provider = (
        str(resolved_provider or "").strip().lower()
        or _extract_runtime_target(llm)[0]
        or normalized_provider
        or None
    )
    effective_failover_mode = failover_mode or (
        FAILOVER_MODE_PINNED if normalized_provider and normalized_provider != "auto" else FAILOVER_MODE_AUTO
    )
    prefer_selectable_fallback = (
        effective_failover_mode == FAILOVER_MODE_AUTO
        and normalized_provider in {"", "auto"}
        and bool(concrete_provider)
    )

    def _prepare_fallback(fallback_llm, fallback_provider):
        """Re-bind tools on fallback LLM with provider-aware tool_choice."""
        prepared_llm = fallback_llm
        if tools:
            if tool_choice:
                translated = _resolve_tool_choice(True, tools, provider=fallback_provider)
                prepared_llm = fallback_llm.bind_tools(tools, tool_choice=translated or tool_choice)
            else:
                prepared_llm = fallback_llm.bind_tools(tools)
        _remember_runtime_target(state, prepared_llm or fallback_llm)
        return prepared_llm

    async def _notify_switch(from_provider: str, to_provider: str, reason: str) -> None:
        if isinstance(state, dict) and to_provider:
            state["_execution_provider"] = str(to_provider).strip().lower()
        if push_event:
            await push_event({
                "type": "model_switch",
                "from_provider": from_provider,
                "to_provider": to_provider,
                "reason": reason,
            })

    async def _record_failover(event: dict[str, Any]) -> None:
        if isinstance(state, dict):
            record_runtime_failover_event(state, event)

    return await ainvoke_with_failover(
        llm,
        messages,
        tier=tier,
        provider=concrete_provider,
        failover_mode=effective_failover_mode,
        prefer_selectable_fallback=prefer_selectable_fallback,
        allowed_fallback_providers=allowed_fallback_providers,
        on_fallback=lambda fb: _prepare_fallback(
            fb,
            getattr(fb, "_wiii_provider_name", None) or "google",
        ),
        on_switch=_notify_switch,
        on_failover=_record_failover,
        primary_timeout=primary_timeout,
        timeout_profile=timeout_profile,
    )


async def _push_status_only_progress(
    push_event,
    *,
    node: str,
    content: str,
    step: str | None = None,
    subtype: str = "progress",
) -> None:
    """Emit non-primary progress copy that should stay out of the main thinking rail."""
    text = " ".join((content or "").split()).strip()
    if not text:
        return

    event: dict[str, Any] = {
        "type": "status",
        "content": text,
        "node": node,
        "details": {
            "subtype": subtype,
            "visibility": "status_only",
        },
    }
    if step:
        event["step"] = step
    await push_event(event)


async def _stream_direct_wait_heartbeats(
    push_event,
    *,
    query: str,
    phase: str,
    cue: str,
    tool_names: Optional[list[str]] = None,
    interval_sec: float = 3.0,
    stop_signal: Optional[asyncio.Event] = None,
) -> None:
    """Emit compact visible wait beats so slow provider paths do not feel frozen.

    Phase 35 — interval bumped 6→3s + cap 2→8 beats (covers up to 24s of
    silence). User reports "không biết Wiii đang làm gì" during NVIDIA
    NIM synth pauses; 3s cadence keeps the StreamingTimer status alive
    so the UI always shows the current phase ("Đang đọc reuters.com",
    "Đang dệt câu trả lời", etc.) rather than freezing at last value.
    """
    beat_index = 0
    while True:
        if stop_signal is not None:
            try:
                await asyncio.wait_for(stop_signal.wait(), timeout=interval_sec)
                return
            except asyncio.TimeoutError:
                pass
            if stop_signal.is_set():
                return
        else:
            await asyncio.sleep(interval_sec)
        beat_index += 1
        if beat_index > 8:
            # 8 × 3s = 24s coverage. Beyond this NVIDIA almost certainly
            # timed out at the LLM-pool layer (45s LIGHT timeout); don't
            # spam status events — let the timeout propagate normally.
            return
        wait_text = _build_direct_wait_heartbeat_text(
            query=query,
            phase=phase,
            cue=cue,
            beat_index=beat_index,
            elapsed_sec=beat_index * interval_sec,
            tool_names=tool_names,
        )
        _hb_event: dict = {
            "type": "status",
            "content": wait_text,
            "node": "direct",
            "details": {"subtype": "visible_wait", "visibility": "progress"},
        }
        await push_event(_hb_event)


async def _stream_code_studio_wait_heartbeats(
    push_event,
    *,
    query: str,
    state: Optional[dict] = None,
    interval_sec: float = 8.0,
    stop_signal: Optional[asyncio.Event] = None,
) -> None:
    """Emit hidden wait heartbeats so code studio progress stays separate from public thinking."""
    beat_index = 0
    while True:
        if stop_signal is not None:
            try:
                await asyncio.wait_for(stop_signal.wait(), timeout=interval_sec)
                return
            except asyncio.TimeoutError:
                pass
            if stop_signal.is_set():
                return
        else:
            await asyncio.sleep(interval_sec)
        beat_index += 1
        if beat_index > 2:
            return
        _hb_event: dict = {
            "type": "status",
            "content": "Đang dựng tiếp...",
            "node": "code_studio_agent",
            "details": {"visibility": "status_only"},
        }
        await push_event(_hb_event)




async def _stream_answer_with_fallback(
    llm,
    messages: list,
    push_event,
    *,
    provider: str | None = None,
    resolved_provider: str | None = None,
    failover_mode: str | None = None,
    allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    node: str = "direct",
    thinking_stop_signal: Optional[asyncio.Event] = None,
    thinking_block_opened: bool = True,
    state: Optional[AgentState] = None,
    primary_timeout: float | None = None,
    timeout_profile: str | None = None,
) -> tuple[object, bool]:
    """Stream answer text deltas for provider-backed lanes when no tools are needed."""
    from app.services.output_processor import extract_thinking_from_response
    FAILOVER_MODE_AUTO = "auto"
    FAILOVER_MODE_PINNED = "pinned"
    tier_key = str(getattr(llm, "_wiii_tier_key", "") or "moderate").strip().lower()
    native_route_enabled = _is_native_runtime_handle(llm)
    if native_route_enabled and not str(resolved_provider or "").strip():
        native_provider, _native_model = _extract_runtime_target(llm)
        resolved_provider = native_provider or ""
    normalized_provider = str(provider or "").strip().lower()
    effective_failover_mode = failover_mode or (
        FAILOVER_MODE_PINNED if normalized_provider and normalized_provider != "auto" else FAILOVER_MODE_AUTO
    )
    prefer_selectable_fallback = (
        effective_failover_mode == FAILOVER_MODE_AUTO
        and normalized_provider in {"", "auto"}
        and bool(str(resolved_provider or "").strip())
    )
    if native_route_enabled:
        from types import SimpleNamespace

        native_provider, _native_model = _extract_runtime_target(llm)
        route = SimpleNamespace(
            provider=str(native_provider or resolved_provider or provider or "").strip().lower(),
            llm=llm,
        )
        _remember_runtime_target(state, route.llm)
        logger.info("[%s] Path: Native SDK handle (provider=%s)", node.upper(), route.provider)
        native_response, native_streamed = await _stream_openai_compatible_answer_with_route(
            route,
            messages,
            push_event,
            node=node,
            thinking_stop_signal=thinking_stop_signal,
            primary_timeout=primary_timeout,
        )
        if native_response is not None:
            return native_response, native_streamed
        logger.warning(
            "[%s] Native handle produced no response; falling back to legacy pool route",
            node.upper(),
        )

    from app.engine.llm_pool import LLMPool
    if not str(resolved_provider or provider or "").strip():
        fallback_response = await llm.ainvoke(messages)
        _remember_runtime_target(state, llm)
        return fallback_response, False
    route = LLMPool.resolve_runtime_route(
        resolved_provider or provider,
        tier_key,
        failover_mode=effective_failover_mode,
        prefer_selectable_fallback=prefer_selectable_fallback,
    )
    _remember_runtime_target(state, route.llm)
    route_provider = str(getattr(route, "provider", "") or resolved_provider or provider or "").strip().lower()
    response_language = (
        str(((state or {}).get("context") or {}).get("response_language") or "vi").strip()
        or "vi"
    )
    query = str((state or {}).get("query") or "").strip()
    if not query and messages:
        try:
            query = _extract_message_text(getattr(messages[-1], "content", ""))
        except Exception:
            query = ""
    is_selfhood_stream_turn = _looks_identity_selfhood_turn(query) or _looks_selfhood_followup_turn(query, state)
    alignment_mode = "direct_selfhood" if is_selfhood_stream_turn else None
    if _should_prefer_invoke_backfilled_stream(node=node, query=query, state=state):
        logger.info("[%s] Path: invoke-backfilled (identity/emotional)", node.upper())
        try:
            fallback_response = await _ainvoke_with_fallback(
                route.llm,
                messages,
                tools=[],
                tier=tier_key,
                provider=provider,
                resolved_provider=resolved_provider,
                failover_mode=failover_mode,
                push_event=push_event,
                primary_timeout=primary_timeout,
                timeout_profile=timeout_profile,
                state=state,
            )
        except Exception as exc:
            if (
                _looks_emotional_support_turn(query)
                and primary_timeout is not None
                and _looks_primary_timeout_failure(exc)
            ):
                logger.warning(
                    "[%s] Emotional invoke-backfill timed out under primary SLA; retrying without primary timeout",
                    node.upper(),
                )
                fallback_response = await _ainvoke_with_fallback(
                    route.llm,
                    messages,
                    tools=[],
                    tier=tier_key,
                    provider=provider,
                    resolved_provider=resolved_provider,
                    failover_mode=failover_mode,
                    push_event=push_event,
                    primary_timeout=None,
                    timeout_profile=timeout_profile,
                    state=state,
                )
            else:
                raise
        response_text, thinking_text, _tools_used = extract_direct_response_impl(
            fallback_response,
            messages,
        )
        preserved_response = await _preserve_ai_message_metadata(
            fallback_response,
            visible_text=response_text,
            response_language=response_language,
            alignment_mode=alignment_mode,
            llm=route.llm,
        )
        preserved_metadata = dict(getattr(preserved_response, "response_metadata", None) or {})
        preserved_kwargs = dict(getattr(preserved_response, "additional_kwargs", None) or {})
        visible_thinking = str(
            preserved_metadata.get("thinking_content")
            or preserved_metadata.get("thinking")
            or preserved_kwargs.get("thinking")
            or thinking_text
            or ""
        ).strip()
        if visible_thinking:
            visible_thinking = await _normalize_direct_visible_thinking(
                visible_thinking,
                response_language=response_language,
                alignment_mode=alignment_mode,
                llm=route.llm,
            )
            response_metadata_obj = getattr(preserved_response, "response_metadata", None)
            if isinstance(response_metadata_obj, dict):
                response_metadata_obj["thinking_content"] = visible_thinking
                if "thinking" in response_metadata_obj:
                    response_metadata_obj["thinking"] = visible_thinking
            additional_kwargs_obj = getattr(preserved_response, "additional_kwargs", None)
            if isinstance(additional_kwargs_obj, dict) and additional_kwargs_obj.get("thinking") is not None:
                additional_kwargs_obj["thinking"] = visible_thinking
        if visible_thinking:
            await push_event({
                "type": "thinking_start",
                "content": "Suy nghĩ câu trả lời",
                "node": node,
            })
            for chunk in _split_visible_thinking_chunks(visible_thinking):
                await push_event({
                    "type": "thinking_delta",
                    "content": chunk,
                    "node": node,
                })
            await push_event({
                "type": "thinking_end",
                "content": "",
                "node": node,
            })
        answer_text = str(getattr(preserved_response, "content", "") or "").strip()
        if answer_text:
            for chunk in _split_visible_answer_chunks(answer_text):
                await push_event({
                    "type": "answer_delta",
                    "content": chunk,
                    "node": node,
                })
            return preserved_response, True
        return preserved_response, False
    if not _should_prefer_native_langchain_stream(
        provider_name=route_provider,
        node=node,
    ):
        logger.info("[%s] Path: Native SDK (provider=%s)", node.upper(), route_provider)
        native_response, native_streamed = await _stream_openai_compatible_answer_with_route(
            route,
            messages,
            push_event,
            node=node,
            thinking_stop_signal=thinking_stop_signal,
            primary_timeout=primary_timeout,
        )
        if native_response is not None:
            return native_response, native_streamed

    llm = route.llm
    logger.info("[%s] Path: LangChain astream (provider=%s)", node.upper(), route_provider)
    merged_chunk = None
    emitted_text = ""
    # Even when the opening phase did not emit a visible thinking block, a later
    # native reasoning chunk from the model should still be allowed to open one.
    thinking_closed = False
    reasoning_started = False

    stream_iter = llm.astream(messages)
    first_stream_chunk: Any | None = None
    try:
        if primary_timeout is not None:
            first_stream_chunk = await asyncio.wait_for(anext(stream_iter), timeout=primary_timeout)
        else:
            first_stream_chunk = await anext(stream_iter)
    except StopAsyncIteration:
        first_stream_chunk = None
    except Exception as exc:
        logger.warning(
            "[%s] astream first-chunk wait failed, falling back to ainvoke: %s",
            node.upper(),
            exc,
        )
        fallback_response = await _ainvoke_with_fallback(
            llm,
            messages,
            tools=[],
            tier=tier_key,
            provider=provider,
            resolved_provider=resolved_provider,
            failover_mode=failover_mode,
            allowed_fallback_providers=allowed_fallback_providers,
            push_event=push_event,
            primary_timeout=primary_timeout,
            timeout_profile=timeout_profile,
            state=state,
        )
        return fallback_response, False

    async def _iter_stream_chunks():
        if first_stream_chunk is not None:
            yield first_stream_chunk
        async for chunk in stream_iter:
            yield chunk

    try:
        async for chunk in _iter_stream_chunks():
            if merged_chunk is None:
                merged_chunk = chunk
            else:
                try:
                    merged_chunk = merged_chunk + chunk
                except Exception:
                    merged_chunk = chunk

            chunk_content = getattr(chunk, "content", "")
            reasoning_piece, answer_piece = _extract_stream_chunk_parts(chunk_content)
            if reasoning_piece and not thinking_closed:
                clean_reasoning = await _normalize_direct_visible_thinking(
                    reasoning_piece,
                    response_language=response_language,
                    alignment_mode=alignment_mode,
                    llm=llm,
                )
                if clean_reasoning:
                    if not reasoning_started:
                        await push_event({
                            "type": "thinking_start",
                            "content": "Suy nghĩ câu trả lời",
                            "node": node,
                        })
                        reasoning_started = True
                    await push_event({
                        "type": "thinking_delta",
                        "content": clean_reasoning,
                        "node": node,
                    })

            if answer_piece:
                clean_text = answer_piece
            else:
                content = getattr(merged_chunk, "content", getattr(chunk, "content", ""))
                text_content, _ = extract_thinking_from_response(content)
                if isinstance(content, str) and "<thinking>" in content.lower():
                    text_content = _strip_incomplete_thinking_blocks(content)
                clean_text = text_content or ""
            if re.search(r"</?\s*thinking", clean_text, flags=re.IGNORECASE):
                clean_text = _strip_incomplete_thinking_blocks(clean_text)
            if not clean_text:
                continue
            visible_text = clean_text
            if node == "code_studio_agent":
                visible_text = _truncate_before_code_dump(clean_text)
            if not visible_text:
                continue
            delta = _compute_visible_answer_delta(
                emitted_text=emitted_text,
                visible_text=visible_text,
            )
            if not delta:
                continue
            if not thinking_closed:
                if thinking_stop_signal is not None:
                    thinking_stop_signal.set()
                if reasoning_started or thinking_block_opened:
                    await push_event({
                        "type": "thinking_end",
                        "content": "",
                        "node": node,
                    })
                thinking_closed = True
            await push_event({
                "type": "answer_delta",
                "content": delta,
                "node": node,
            })
            emitted_text += delta

        if merged_chunk is not None:
            if not thinking_closed:
                if thinking_stop_signal is not None:
                    thinking_stop_signal.set()
                if reasoning_started or thinking_block_opened:
                    await push_event({
                        "type": "thinking_end",
                        "content": "",
                        "node": node,
                    })
            if (
                node == "direct"
                and emitted_text
                and isinstance(getattr(merged_chunk, "content", None), str)
                and str(getattr(merged_chunk, "content", "") or "") != emitted_text
            ):
                return await _preserve_ai_message_metadata(
                    merged_chunk,
                    visible_text=emitted_text,
                    response_language=response_language,
                    alignment_mode=alignment_mode,
                    llm=llm,
                ), True
            return merged_chunk, bool(emitted_text)
    except Exception as exc:
        logger.warning("[%s] astream failed, falling back to ainvoke: %s", node.upper(), exc)

    fallback_response = await _ainvoke_with_fallback(
        llm,
        messages,
        tools=[],
        tier=tier_key,
        provider=provider,
        resolved_provider=resolved_provider,
        failover_mode=failover_mode,
        allowed_fallback_providers=allowed_fallback_providers,
        push_event=push_event,
        primary_timeout=primary_timeout,
        timeout_profile=timeout_profile,
        state=state,
    )
    return fallback_response, False


async def _stream_direct_answer_with_fallback(
    llm,
    messages: list,
    push_event,
    *,
    provider: str | None = None,
    resolved_provider: str | None = None,
    failover_mode: str | None = None,
    allowed_fallback_providers: set[str] | list[str] | tuple[str, ...] | None = None,
    thinking_stop_signal: Optional[asyncio.Event] = None,
    thinking_block_opened: bool = True,
    state: Optional[AgentState] = None,
    primary_timeout: float | None = None,
    timeout_profile: str | None = None,
) -> tuple[object, bool]:
    return await _stream_answer_with_fallback(
        llm,
        messages,
        push_event,
        provider=provider,
        resolved_provider=resolved_provider,
        failover_mode=failover_mode,
        allowed_fallback_providers=allowed_fallback_providers,
        node="direct",
        thinking_stop_signal=thinking_stop_signal,
        thinking_block_opened=thinking_block_opened,
        state=state,
        primary_timeout=primary_timeout,
        timeout_profile=timeout_profile,
    )


def _resolve_direct_answer_timeout_profile(
    *,
    provider_name: str | None,
    query: str = "",
    state: object | None = None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    tools_bound: bool,
) -> str | None:
    """Give short/direct Wiii turns more room on slow-but-healthy providers."""
    return resolve_direct_answer_timeout_profile_impl(
        provider_name=provider_name,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=tools_bound,
    )


def _resolve_direct_answer_primary_timeout(
    *,
    provider_name: str | None,
    query: str = "",
    state: object | None = None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    tools_bound: bool,
) -> float | None:
    """Give direct no-tool turns a lane-specific first-token SLA."""
    return resolve_direct_answer_primary_timeout_impl(
        provider_name=provider_name,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=tools_bound,
    )


async def _execute_direct_tool_rounds(
    llm_with_tools, llm_auto, messages: list, tools: list, push_event,
    runtime_context_base=None,
    max_rounds: int = 3,
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    forced_tool_choice: str | None = None,
    llm_base=None,
    direct_answer_timeout_profile: str | None = None,
    direct_answer_primary_timeout: float | None = None,
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None = None,
    native_tool_messages: bool = False,
):
    """Execute multi-round tool calling loop for direct response.

    Sprint 154: Extracted from direct_response_node.
    Gemini often calls tools sequentially (datetime → web_search → answer).

    Returns:
        tuple: (assistant response, messages, tool_call_events) — final response, messages, and
               structured tool events for downstream preview emission (Sprint 166).
    """
    return await execute_direct_tool_rounds_impl(
        llm_with_tools,
        llm_auto,
        messages,
        tools,
        push_event,
        runtime_context_base=runtime_context_base,
        max_rounds=max_rounds,
        query=query,
        state=state,
        provider=provider,
        forced_tool_choice=forced_tool_choice,
        llm_base=llm_base,
        direct_answer_timeout_profile=direct_answer_timeout_profile,
        direct_answer_primary_timeout=direct_answer_primary_timeout,
        allowed_fallback_providers=allowed_fallback_providers,
        native_tool_messages=native_tool_messages,
        ainvoke_with_fallback=_ainvoke_with_fallback,
        stream_direct_answer_with_fallback=_stream_direct_answer_with_fallback,
        stream_direct_wait_heartbeats=_stream_direct_wait_heartbeats,
        push_status_only_progress=_push_status_only_progress,
    )


def _extract_direct_response(llm_response, messages: list):
    """Extract response text, thinking content, and tools used from LLM result."""
    return extract_direct_response_impl(llm_response, messages)

_STRUCTURED_VISUAL_MARKER_RE = re.compile(
    r"\{visual-[a-f0-9]+\}|<!--\s*WiiiVisualBridge:[^>]+-->|"
    r"\[Biểu đồ[^\]]*\]|\[Bieu do[^\]]*\]|\[Chart[^\]]*\]|\[Visual[^\]]*\]",
    re.IGNORECASE,
)
_STRUCTURED_VISUAL_PLACEHOLDER_MD_RE = re.compile(
    r"!\[[^\]]*\]\((?:https?://example\.com/[^)\s]+|https?://[^)\s]*chart-placeholder[^)\s]*|sandbox:[^)]+)\)",
    re.IGNORECASE,
)
