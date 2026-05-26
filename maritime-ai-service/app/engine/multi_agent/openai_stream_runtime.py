"""OpenAI-compatible/native streaming helpers extracted from the graph shell."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

from app.core.exceptions import ProviderStreamInterruptedError
from app.core import config as app_config
from app.core.config import settings
from app.engine.openai_compatible_credentials import (
    resolve_nvidia_api_key,
    resolve_nvidia_base_url,
    resolve_nvidia_model,
    resolve_nvidia_model_advanced,
    resolve_openai_api_key,
    resolve_openai_base_url,
    resolve_openrouter_api_key,
    resolve_openrouter_base_url,
)
from app.engine.native_chat_runtime import (
    make_assistant_message,
    message_to_openai_payload,
    normalize_tool_choice,
    openai_response_to_assistant_message,
)
from app.engine.multi_agent.tool_call_text_parser import (
    extract_raw_tool_calls_from_text,
    tool_names_from_tools,
)
from app.engine.reasoning import sanitize_visible_reasoning_text

logger = logging.getLogger(__name__)


def _derive_code_stream_session_id_impl(
    *,
    runtime_context_base=None,
    state=None,
) -> str:
    """Build a stable Code Studio stream session id for one request lifecycle."""
    request_id = ""
    if runtime_context_base is not None:
        request_id = str(getattr(runtime_context_base, "request_id", "") or "").strip()
    if not request_id and state:
        context = state.get("context") or {}
        if isinstance(context, dict):
            request_id = str(context.get("request_id") or "").strip()
    if request_id:
        return f"vs-stream-{uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex[:12]}"
    return f"vs-stream-{uuid.uuid4().hex[:12]}"


def _should_enable_real_code_streaming_impl(
    provider: str | None,
    *,
    llm: Any | None = None,
) -> bool:
    """Enable real Code Studio code-delta streaming only for proven-stable providers.

    NVIDIA NIM + DeepSeek emit OpenAI-compatible streaming chunks
    (``delta.tool_calls[].function.arguments``) which LangChain maps to
    ``chunk.tool_call_chunks`` — same shape as OpenAI/Zhipu/OpenRouter.
    DeepSeek V4 Flash/Pro have been the Wiii local-prod default since
    Phase 9c, so they belong in the allowlist alongside the other
    OpenAI-compat providers.
    """
    if not getattr(app_config.get_settings(), "enable_real_code_streaming", False):
        return False

    normalized = str(provider or "").strip().lower()
    # Sprint 35e follow-up: include NVIDIA NIM (OpenAI-compat) so
    # local-prod Wiii deployments running DeepSeek see real token-by-token
    # code streaming on every code_studio turn.
    if normalized in {"openai", "openrouter", "zhipu", "nvidia"}:
        return True

    return False


def _supports_native_answer_streaming_impl(provider: str | None) -> bool:
    normalized = str(provider or "").strip().lower()
    return normalized in {"google", "zhipu", "openai", "openrouter", "nvidia"}


def _flatten_langchain_content_impl(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content") or item.get("value")
            if text:
                parts.append(str(text))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _langchain_message_to_openai_payload_impl(
    message: Any,
    *,
    flatten_langchain_content,
) -> dict[str, Any]:
    # Compatibility shim: callers still use the legacy function name, but the
    # conversion is now framework-free and accepts LangChain-like duck objects.
    return message_to_openai_payload(message)


def _create_openai_compatible_stream_client_impl(provider_name: str):
    from openai import AsyncOpenAI

    normalized = str(provider_name or "").strip().lower()
    if normalized == "google":
        if not settings.google_api_key:
            return None
        return AsyncOpenAI(
            api_key=settings.google_api_key,
            base_url=settings.google_openai_compat_url,
        )
    if normalized == "zhipu":
        if not settings.zhipu_api_key:
            return None
        return AsyncOpenAI(
            api_key=settings.zhipu_api_key,
            base_url=settings.zhipu_base_url,
        )
    if normalized == "openrouter":
        if not resolve_openrouter_api_key(settings):
            return None
        return AsyncOpenAI(
            api_key=resolve_openrouter_api_key(settings),
            base_url=resolve_openrouter_base_url(settings),
        )
    if normalized == "nvidia":
        if not resolve_nvidia_api_key(settings):
            return None
        return AsyncOpenAI(
            api_key=resolve_nvidia_api_key(settings),
            base_url=resolve_nvidia_base_url(settings),
        )
    if normalized == "openai":
        if not resolve_openai_api_key(settings):
            return None
        return AsyncOpenAI(
            api_key=resolve_openai_api_key(settings),
            base_url=resolve_openai_base_url(settings),
        )
    return None


def _resolve_openai_stream_model_name_impl(
    llm: Any,
    provider_name: str,
    tier_key: str,
) -> str | None:
    tagged_provider = str(getattr(llm, "_wiii_provider_name", "") or "").strip().lower()
    tagged_model = (
        getattr(llm, "_wiii_model_name", None)
        or getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
    )
    if tagged_provider == provider_name and tagged_model:
        return str(tagged_model)

    normalized = str(provider_name or "").strip().lower()
    if normalized == "google":
        if tier_key == "deep":
            return getattr(settings, "google_model_advanced", settings.google_model)
        return settings.google_model
    if normalized == "zhipu":
        if tier_key == "deep":
            return settings.zhipu_model_advanced
        return settings.zhipu_model
    if normalized == "openrouter":
        return settings.openai_model or "openai/gpt-oss-20b:free"
    if normalized == "nvidia":
        if tier_key == "deep":
            return resolve_nvidia_model_advanced(settings)
        return resolve_nvidia_model(settings)
    if normalized == "openai":
        if tier_key == "deep":
            return settings.openai_model_advanced
        return settings.openai_model
    return None


async def _ainvoke_openai_compatible_chat_impl(
    llm: Any,
    messages: list,
) -> Any:
    """Invoke one native OpenAI-compatible chat completion, including tools."""
    provider_name = str(getattr(llm, "_wiii_provider_name", "") or "").strip().lower()
    if not _supports_native_answer_streaming_impl(provider_name):
        raise RuntimeError(f"Native provider is not supported: {provider_name or 'unknown'}")

    client = _create_openai_compatible_stream_client_impl(provider_name)
    if client is None:
        raise RuntimeError(f"Native provider client is unavailable: {provider_name}")

    tier_key = str(getattr(llm, "_wiii_tier_key", "") or "moderate").strip().lower()
    model_name = _resolve_openai_stream_model_name_impl(llm, provider_name, tier_key)
    if not model_name:
        raise RuntimeError(f"Native model is not configured for provider: {provider_name}")

    request_kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": [message_to_openai_payload(message) for message in messages],
    }
    temperature = getattr(llm, "temperature", None)
    if temperature is not None:
        request_kwargs["temperature"] = temperature

    bound_tools = list(getattr(llm, "_wiii_bound_tools", []) or [])
    if bound_tools:
        request_kwargs["tools"] = bound_tools
    tool_choice = normalize_tool_choice(getattr(llm, "_wiii_tool_choice", None))
    if tool_choice is not None:
        request_kwargs["tool_choice"] = tool_choice

    if provider_name == "openrouter":
        from app.engine.openrouter_routing import build_openrouter_extra_body

        extra_body = build_openrouter_extra_body(settings, primary_model=model_name)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

    response = await client.chat.completions.create(**request_kwargs)
    return openai_response_to_assistant_message(response)


def _extract_openai_delta_text_impl(delta: Any) -> tuple[str, str]:
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []

    reasoning = getattr(delta, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning:
        reasoning_parts.append(reasoning)
    elif isinstance(reasoning, list):
        for item in reasoning:
            text = item.get("text") if isinstance(item, dict) else None
            if text:
                reasoning_parts.append(str(text))

    content = getattr(delta, "content", None)
    if isinstance(content, str) and content:
        answer_parts.append(content)
    elif isinstance(content, list):
        for item in content:
            text = item.get("text") if isinstance(item, dict) else None
            if text:
                answer_parts.append(str(text))

    return "".join(reasoning_parts), "".join(answer_parts)


def _extract_google_tagged_thinking_impl(
    text: str,
    *,
    state: dict[str, Any],
) -> tuple[str, str]:
    """Split streamed Google <thinking> tags out of visible answer text."""
    incoming = f"{state.get('pending', '')}{text or ''}"
    state["pending"] = ""
    if not incoming:
        return "", ""

    reasoning_parts: list[str] = []
    visible_parts: list[str] = []
    inside_thinking = bool(state.get("inside_thinking"))
    index = 0

    while index < len(incoming):
        if incoming[index] == "<":
            close_index = incoming.find(">", index + 1)
            if close_index < 0:
                state["pending"] = incoming[index:]
                break
            tag = incoming[index : close_index + 1].strip().lower()
            if tag == "<thinking>":
                inside_thinking = True
            elif tag == "</thinking>":
                inside_thinking = False
            else:
                target = reasoning_parts if inside_thinking else visible_parts
                target.append(incoming[index : close_index + 1])
            index = close_index + 1
            continue

        next_tag_index = incoming.find("<", index)
        if next_tag_index < 0:
            segment = incoming[index:]
            index = len(incoming)
        else:
            segment = incoming[index:next_tag_index]
            index = next_tag_index
        if not segment:
            continue
        target = reasoning_parts if inside_thinking else visible_parts
        target.append(segment)

    state["inside_thinking"] = inside_thinking
    return "".join(reasoning_parts), "".join(visible_parts)


def _get_chunk_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _accumulate_tool_call_chunk(
    accumulator: dict[int, dict[str, str]],
    tool_call_chunk: Any,
) -> None:
    """Merge OpenAI-compatible streamed function-call chunks by index."""
    try:
        index = int(_get_chunk_value(tool_call_chunk, "index") or 0)
    except Exception:
        index = 0
    slot = accumulator.setdefault(index, {"id": "", "name": "", "arguments": ""})

    tool_call_id = _get_chunk_value(tool_call_chunk, "id")
    if tool_call_id:
        slot["id"] = str(tool_call_id)

    function = _get_chunk_value(tool_call_chunk, "function") or {}
    name = _get_chunk_value(function, "name")
    if name:
        if slot["name"] and str(name) not in slot["name"]:
            slot["name"] = f"{slot['name']}{name}"
        else:
            slot["name"] = str(name)

    arguments = _get_chunk_value(function, "arguments")
    if arguments:
        slot["arguments"] = f"{slot['arguments']}{arguments}"


def _finalize_tool_call_chunks(
    accumulator: dict[int, dict[str, str]],
) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for index in sorted(accumulator):
        chunk = accumulator[index]
        name = str(chunk.get("name") or "").strip()
        if not name:
            continue
        raw_arguments = str(chunk.get("arguments") or "").strip()
        args: Any = {}
        if raw_arguments:
            try:
                args = json.loads(raw_arguments)
            except Exception:
                args = {"_raw": raw_arguments}
        tool_calls.append({
            "id": str(chunk.get("id") or f"call_{index}"),
            "name": name,
            "args": args if isinstance(args, dict) else {"_raw": str(args)},
        })
    return tool_calls


async def _stream_openai_compatible_answer_with_route_impl(
    route,
    messages: list,
    push_event,
    *,
    node: str = "direct",
    thinking_stop_signal: Optional[asyncio.Event] = None,
    primary_timeout: float | None = None,
    supports_native_answer_streaming,
    create_openai_compatible_stream_client,
    resolve_openai_stream_model_name,
    langchain_message_to_openai_payload,
    extract_openai_delta_text,
) -> tuple[object | None, bool]:
    provider_name = str(route.provider or "").strip().lower()
    if not supports_native_answer_streaming(provider_name):
        return None, False

    client = create_openai_compatible_stream_client(provider_name)
    if client is None:
        return None, False

    tier_key = str(getattr(route.llm, "_wiii_tier_key", "") or "moderate").strip().lower()
    model_name = resolve_openai_stream_model_name(route.llm, provider_name, tier_key)
    if not model_name:
        return None, False

    request_messages = [
        langchain_message_to_openai_payload(message)
        for message in messages
    ]

    # P3: Assistant pre-fill to force System 2 activation for Z.ai/GLM.
    # The incomplete <thinking> tag compels the model to continue the thought.
    if provider_name and ("zhipu" in provider_name.lower() or "glm" in provider_name.lower()):
        try:
            from app.engine.reasoning.thinking_enforcement import should_prefill_thinking
            if should_prefill_thinking(request_messages, provider=provider_name):
                from app.engine.reasoning.thinking_enforcement import get_thinking_prefill_message
                request_messages.append(get_thinking_prefill_message())
        except Exception:
            pass
    request_kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": request_messages,
        "stream": True,
    }
    temperature = getattr(route.llm, "temperature", None)
    if temperature is not None:
        request_kwargs["temperature"] = temperature

    bound_tools = list(getattr(route.llm, "_wiii_bound_tools", []) or [])
    allowed_raw_tool_names = tool_names_from_tools(bound_tools)
    if bound_tools:
        request_kwargs["tools"] = bound_tools
    tool_choice = normalize_tool_choice(getattr(route.llm, "_wiii_tool_choice", None))
    if tool_choice is not None:
        request_kwargs["tool_choice"] = tool_choice

    if provider_name == "openrouter":
        from app.engine.openrouter_routing import build_openrouter_extra_body

        extra_body = build_openrouter_extra_body(settings, primary_model=model_name)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

    emitted_answer = ""
    thinking_closed = False
    emit_provider_reasoning = str(node or "").strip().lower() != "code_studio_agent"
    google_tag_state = {"inside_thinking": False, "pending": ""}
    reasoning_started = False
    tool_call_chunks: dict[int, dict[str, str]] = {}
    raw_tool_answer_candidate: bool | None = None
    raw_tool_answer_chunks: list[str] = []

    # Phase 34 (#207): boundary-aware token batching. When the
    # ``enable_stream_smoother`` flag is on, we route every answer_delta
    # through a StreamSmoother that flushes at sentence/punctuation
    # boundaries so the UI repaints with even cadence regardless of
    # whether the provider bursts 30 tokens at once or trickles char-
    # by-char. Default off — when off, the emit path is unchanged.
    answer_smoother = None
    try:
        if settings.enable_stream_smoother:
            from app.engine.runtime.stream_smoother import StreamSmoother

            answer_smoother = StreamSmoother()
    except Exception:  # noqa: BLE001
        # Settings unavailable / smoother import failed → fall through
        # to the legacy path. Telemetry-style improvements never break
        # the request.
        answer_smoother = None

    async def _close_thinking_for_non_answer() -> None:
        nonlocal thinking_closed
        if thinking_closed:
            return
        if thinking_stop_signal is not None:
            thinking_stop_signal.set()
        if reasoning_started:
            await push_event({
                "type": "thinking_end",
                "content": "",
                "node": node,
            })
        thinking_closed = True

    async def _emit_visible_answer_delta(answer_text: str) -> None:
        nonlocal emitted_answer, thinking_closed
        if not answer_text:
            return
        if not thinking_closed:
            if thinking_stop_signal is not None:
                thinking_stop_signal.set()
            if reasoning_started:
                await push_event({
                    "type": "thinking_end",
                    "content": "",
                    "node": node,
                })
            thinking_closed = True
        if answer_smoother is not None:
            for flushed in answer_smoother.feed(answer_text):
                await push_event({
                    "type": "answer_delta",
                    "content": flushed,
                    "node": node,
                })
        else:
            await push_event({
                "type": "answer_delta",
                "content": answer_text,
                "node": node,
            })
        emitted_answer += answer_text

    try:
        stream = await client.chat.completions.create(**request_kwargs)
        stream_iter = stream.__aiter__()
        first_stream_chunk = None
        try:
            if primary_timeout is not None and primary_timeout > 0:
                first_stream_chunk = await asyncio.wait_for(
                    anext(stream_iter),
                    timeout=primary_timeout,
                )
            else:
                first_stream_chunk = await anext(stream_iter)
        except StopAsyncIteration:
            first_stream_chunk = None

        async def _iter_stream_chunks():
            if first_stream_chunk is not None:
                yield first_stream_chunk
            while True:
                try:
                    yield await anext(stream_iter)
                except StopAsyncIteration:
                    break

        async for chunk in _iter_stream_chunks():
            for choice in getattr(chunk, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                for tool_call_chunk in getattr(delta, "tool_calls", []) or []:
                    _accumulate_tool_call_chunk(tool_call_chunks, tool_call_chunk)
                if tool_call_chunks:
                    await _close_thinking_for_non_answer()
                reasoning_delta, answer_delta = extract_openai_delta_text(delta)
                if answer_delta and str(node or "").strip().lower() != "code_studio_agent":
                    tagged_reasoning, cleaned_answer = _extract_google_tagged_thinking_impl(
                        answer_delta,
                        state=google_tag_state,
                    )
                    if tagged_reasoning:
                        reasoning_delta = f"{reasoning_delta}{tagged_reasoning}"
                    answer_delta = cleaned_answer
                if reasoning_delta and emit_provider_reasoning and not thinking_closed:
                    reasoning_delta = sanitize_visible_reasoning_text(reasoning_delta)
                if reasoning_delta and emit_provider_reasoning and not thinking_closed and not reasoning_started:
                    await push_event({
                        "type": "thinking_start",
                        "content": "Suy nghĩ câu trả lời",
                        "node": node,
                    })
                    reasoning_started = True
                if reasoning_delta and emit_provider_reasoning and not thinking_closed:
                    await push_event({
                        "type": "thinking_delta",
                        "content": reasoning_delta,
                        "node": node,
                    })
                if not answer_delta:
                    continue
                if raw_tool_answer_candidate is not False:
                    probe_text = "".join(raw_tool_answer_chunks) + answer_delta
                    stripped_probe = probe_text.lstrip()
                    if raw_tool_answer_candidate is None:
                        if not stripped_probe:
                            raw_tool_answer_chunks.append(answer_delta)
                            continue
                        raw_tool_answer_candidate = stripped_probe[0] in "{["
                    if raw_tool_answer_candidate:
                        raw_tool_answer_chunks.append(answer_delta)
                        continue
                    if raw_tool_answer_chunks:
                        answer_delta = "".join(raw_tool_answer_chunks) + answer_delta
                        raw_tool_answer_chunks.clear()
                # Phase 34: route through StreamSmoother when enabled.
                # Smoother yields 0+ flushed strings per chunk based on
                # punctuation / length / time-watchdog boundaries, so
                # the UI sees even-cadence repaints instead of provider-
                # burst flicker. When disabled, single direct emit.
                await _emit_visible_answer_delta(answer_delta)
        if raw_tool_answer_chunks:
            raw_tool_text = "".join(raw_tool_answer_chunks)
            raw_tool_calls = extract_raw_tool_calls_from_text(
                raw_tool_text,
                allowed_tool_names=allowed_raw_tool_names or None,
            )
            if raw_tool_calls:
                from app.engine.llm_model_health import record_model_success

                record_model_success(provider_name, model_name)
                await _close_thinking_for_non_answer()
                logger.info(
                    "[%s] Converted raw JSON assistant text into %d structured tool call(s)",
                    node.upper(),
                    len(raw_tool_calls),
                )
                return make_assistant_message("", tool_calls=raw_tool_calls), False
            await _emit_visible_answer_delta(raw_tool_text)
            raw_tool_answer_chunks.clear()
        tool_calls = _finalize_tool_call_chunks(tool_call_chunks)
        if tool_calls:
            from app.engine.llm_model_health import record_model_success

            record_model_success(provider_name, model_name)
            await _close_thinking_for_non_answer()
            return make_assistant_message(
                emitted_answer,
                tool_calls=tool_calls,
            ), bool(emitted_answer)
        if emitted_answer:
            from app.engine.llm_model_health import record_model_success

            record_model_success(provider_name, model_name)
            # Phase 34: drain any answer fragment still in the smoother
            # so the tail token (final word, punctuation) doesn't get
            # silently dropped.
            if answer_smoother is not None:
                tail = answer_smoother.flush_remaining()
                if tail:
                    await push_event({
                        "type": "answer_delta",
                        "content": tail,
                        "node": node,
                    })
            await _close_thinking_for_non_answer()
            return make_assistant_message(emitted_answer), True
        await _close_thinking_for_non_answer()
    except Exception as exc:
        from app.engine.llm_failover_runtime import classify_failover_reason_impl
        from app.engine.llm_model_health import record_model_failure

        timeout_seconds = primary_timeout if isinstance(exc, asyncio.TimeoutError) else None
        classified = classify_failover_reason_impl(
            error=exc,
            timeout_seconds=timeout_seconds,
        )
        record_model_failure(
            provider_name,
            model_name,
            reason_code=classified.get("reason_code"),
            error=exc,
            timeout_seconds=timeout_seconds,
        )
        logger.warning(
            "[%s] Native OpenAI-compatible stream failed (%s/%s): %s",
            node.upper(),
            provider_name,
            model_name,
            exc,
            exc_info=True,
        )
        reason_code = str(classified.get("reason_code") or "")
        if emitted_answer and reason_code == "provider_stream_interrupted":
            await _close_thinking_for_non_answer()
            raise ProviderStreamInterruptedError(
                provider=provider_name,
                model=model_name or "",
                partial_chars=len(emitted_answer),
                details=str(exc),
            ) from exc
        if emitted_answer:
            await _close_thinking_for_non_answer()
            raise
        await _close_thinking_for_non_answer()
    logger.info(
        "[%s] Native stream result: provider=%s model=%s answer=%d chars",
        node.upper(),
        provider_name,
        model_name,
        len(emitted_answer),
    )
    return None, False
