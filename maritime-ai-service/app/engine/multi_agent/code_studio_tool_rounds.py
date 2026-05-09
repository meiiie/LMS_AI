"""Code Studio tool-round execution extracted from graph.py."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Optional

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.code_studio_template_scaffold import (
    build_code_studio_scaffold,
    build_scaffold_visible_caption,
    detect_scaffold_kind,
)
from app.engine.runtime.runtime_metrics import inc_counter

logger = logging.getLogger(__name__)


def _normalize_tc(tc: object) -> dict:
    """Normalize a tool_call entry into a dict with id/name/args.

    LangChain BaseChatModel emits dict-shaped tool_calls, native ``Message``
    construction (``_AM``) emits Pydantic ``ToolCall`` objects with
    attributes ``id``/``name``/``arguments``. Iterators in this module
    expect both shapes to expose ``.get(...)``-style access — this helper
    bridges the gap so the scaffold injection path stays compatible with
    real LLM-driven tool calls.
    """
    if isinstance(tc, dict):
        return tc
    return {
        "id": str(getattr(tc, "id", "") or ""),
        "name": str(getattr(tc, "name", "") or ""),
        "args": getattr(tc, "arguments", None) or getattr(tc, "args", {}) or {},
    }


def _build_scaffold_manual_tool_call(
    query: str,
    *,
    reason: str = "unknown",
) -> tuple[dict, str]:
    """Build a synthetic tool_call payload that injects an HTML scaffold.

    Returned ``manual_tc`` matches the shape expected by the rest of the
    code_studio loop (``name``/``args``/``id``); ``visible_caption`` is the
    short Vietnamese explainer the chat thread shows above the canvas.

    The ``reason`` label is forwarded to the
    ``wiii.code_studio.scaffold.engaged`` counter so operators can see in
    Grafana whether stream timeouts, ainvoke timeouts, or LLM-prose-only
    rounds are driving the fallback rate.

    Pattern reference: Anthropic Computer Use 2026 evidence-pool retention
    + Wiii VISUAL_CODE_GEN.md "host-governed runtime" lane.
    """
    scaffold_html = build_code_studio_scaffold(query)
    visible_caption = build_scaffold_visible_caption(query)
    kind = detect_scaffold_kind(query)
    short_title = (query or "Khung dựng cảnh").strip()[:60]
    manual_tc = {
        "name": "tool_create_visual_code",
        "args": {
            "code_html": scaffold_html,
            "title": short_title,
            "subtitle": "Khung tạm — Wiii sẽ mở rộng khi bạn mô tả thêm",
        },
        "id": f"scaffold_tc_{uuid.uuid4().hex[:8]}",
    }
    try:
        inc_counter(
            "wiii.code_studio.scaffold.engaged",
            labels={"kind": kind, "reason": reason},
        )
    except Exception:  # noqa: BLE001 — never let metrics break a request
        pass
    return manual_tc, visible_caption


async def execute_code_studio_tool_rounds_impl(
    llm_with_tools,
    llm_auto,
    messages: list,
    tools: list,
    push_event,
    runtime_context_base=None,
    max_rounds: int = 3,
    query: str = "",
    state: Optional[AgentState] = None,
    provider: str | None = None,
    runtime_provider: str | None = None,
    forced_tool_choice: str | None = None,
    *,
    should_enable_real_code_streaming,
    derive_code_stream_session_id,
    ainvoke_with_fallback,
    build_code_studio_progress_messages,
    render_reasoning_fast,
    infer_code_studio_reasoning_cue,
    thinking_start_label,
    code_studio_delta_chunks,
    stream_code_studio_wait_heartbeats,
    format_code_studio_progress_message,
    build_code_studio_retry_status,
    build_code_studio_missing_tool_response,
    requires_code_studio_visual_delivery,
    collect_active_visual_session_ids,
    get_tool_by_name,
    invoke_tool_with_runtime,
    summarize_tool_result_for_stream,
    maybe_emit_visual_event,
    emit_visual_commit_events,
    build_code_studio_tool_reflection,
    is_terminal_code_studio_tool_error,
    build_code_studio_terminal_failure_response,
    build_code_studio_synthesis_observations,
    inject_widget_blocks_from_tool_results,
    push_status_only_progress,
    settings_obj,
):
    """Execute multi-round tool calling loop for the code studio capability."""
    from app.engine.messages import Message, ToolCall
    from app.engine.llm_pool import TIMEOUT_PROFILE_BACKGROUND

    def _AM(content: str = "", tool_calls: list[dict] | None = None) -> Message:
        """Native assistant message — keeps the tool-rounds construction call sites short."""
        if tool_calls:
            native_tcs = [
                ToolCall(
                    id=str(tc.get("id") or ""),
                    name=str(tc.get("name") or ""),
                    arguments=tc.get("args") if isinstance(tc.get("args"), dict) else {},
                )
                for tc in tool_calls
            ]
            return Message(role="assistant", content=content, tool_calls=native_tcs)
        return Message(role="assistant", content=content)

    def _TM(content: str = "", *, tool_call_id: str = "") -> Message:
        """Native tool-result message."""
        return Message(role="tool", content=str(content), tool_call_id=str(tool_call_id))

    tool_call_events: list[dict] = []
    state = state or {}
    code_open_emitted = False
    stream_session_id = ""
    stream_chunk_index = 0

    stream_provider = runtime_provider or provider
    use_real_streaming = should_enable_real_code_streaming(
        stream_provider,
        llm=llm_with_tools,
    )

    if use_real_streaming:
        from app.engine.multi_agent.tool_call_stream_parser import ToolCallCodeHtmlStreamer

        code_streamer = ToolCallCodeHtmlStreamer()
        stream_session_id = derive_code_stream_session_id(
            runtime_context_base=runtime_context_base,
            state=state,
        )

        await push_event(
            {
                "type": "status",
                "content": "Đang phân tích yêu cầu...",
                "step": "code_generation",
                "node": "code_studio_agent",
                "details": {"visibility": "status_only"},
            }
        )

        llm_response = None
        # Operator-tunable resilience timeouts (Sprint 35d). Defaults trade
        # provider-healthy latency against worst-case scaffold-fallback time.
        chunk_timeout = float(getattr(settings_obj, "code_studio_chunk_timeout_seconds", 30.0))
        code_done_timeout = float(getattr(settings_obj, "code_studio_code_done_timeout_seconds", 30.0))
        # Overall ceiling for the streaming pass. NVIDIA NIM occasionally
        # emits tiny chunks indefinitely without ever closing the stream,
        # and the per-chunk asyncio.wait_for cannot reliably cancel the
        # underlying httpx connection. We therefore wrap the entire stream
        # loop with asyncio.timeout() (Python 3.11+) so the runtime cancels
        # the whole task tree and the graceful scaffold fallback engages.
        stream_overall_timeout = float(getattr(settings_obj, "code_studio_stream_overall_timeout_seconds", 90.0))
        code_html_done_at: float | None = None
        astream_timed_out = False
        try:
            try:
                async with asyncio.timeout(stream_overall_timeout):
                    # Sprint 35e follow-up: bring astream() initialisation
                    # INSIDE the asyncio.timeout block. NVIDIA NIM can hang
                    # at the HTTP-setup phase before the first chunk lands;
                    # initialising the iterator outside the timeout context
                    # let those hangs bypass the cap and stall the pipeline
                    # for >360s in the worst case.
                    astream_iter = llm_with_tools.astream(messages).__aiter__()
                    while True:
                        if code_html_done_at and (time.time() - code_html_done_at) > code_done_timeout:
                            has_tool_calls = bool(llm_response and getattr(llm_response, "tool_calls", None))
                            if has_tool_calls:
                                logger.info("[CODE_STUDIO] code_html + tool_call complete, breaking astream")
                                break
                            if (time.time() - code_html_done_at) > code_done_timeout * 3:
                                logger.warning(
                                    "[CODE_STUDIO] code_html done but no tool_call after %ds, force break",
                                    code_done_timeout * 3,
                                )
                                break

                        try:
                            timeout = code_done_timeout if code_html_done_at else chunk_timeout
                            chunk = await asyncio.wait_for(astream_iter.__anext__(), timeout=timeout)
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError:
                            if code_html_done_at:
                                logger.info("[CODE_STUDIO] code_html already complete, proceeding to tool execution")
                            else:
                                logger.warning("[CODE_STUDIO] astream chunk timeout after %ds", chunk_timeout)
                            break

                        llm_response = chunk if llm_response is None else llm_response + chunk

                        if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                            for tc_chunk in chunk.tool_call_chunks:
                                tc_args = tc_chunk.get("args") or ""
                                if not tc_args:
                                    continue
                                delta = code_streamer.feed(tc_args)

                                if delta and not code_open_emitted and code_streamer.is_code_html_started:
                                    await push_event(
                                        {
                                            "type": "code_open",
                                            "content": {
                                                "session_id": stream_session_id,
                                                "title": query[:60] if query else "Code Studio",
                                                "language": "html",
                                                "version": 1,
                                                "studio_lane": "app",
                                                "artifact_kind": "html_app",
                                            },
                                            "node": "code_studio_agent",
                                        }
                                    )
                                    code_open_emitted = True

                                if delta and code_open_emitted:
                                    stream_chunk_size = 500
                                    for ci in range(0, len(delta), stream_chunk_size):
                                        sub_chunk = delta[ci : ci + stream_chunk_size]
                                        await push_event(
                                            {
                                                "type": "code_delta",
                                                "content": {
                                                    "session_id": stream_session_id,
                                                    "chunk": sub_chunk,
                                                    "chunk_index": stream_chunk_index,
                                                    "total_bytes": 0,
                                                },
                                                "node": "code_studio_agent",
                                            }
                                        )
                                        stream_chunk_index += 1
                                        if ci + stream_chunk_size < len(delta):
                                            await asyncio.sleep(0.02)

                                if code_streamer.is_code_html_complete and not code_html_done_at:
                                    code_html_done_at = time.time()
                                    logger.info(
                                        "[CODE_STUDIO] code_html fully extracted: %d chars",
                                        len(code_streamer.full_code_html),
                                    )
            except (asyncio.TimeoutError, TimeoutError):
                astream_timed_out = True
                logger.warning(
                    "[CODE_STUDIO] astream overall timeout after %ds — engaging graceful scaffold",
                    stream_overall_timeout,
                )
            # Existing code below uses the astream loop's outputs.
            # Fall through to the unchanged tail logic.
            pass
        except Exception as stream_err_outer:
            logger.warning(
                "[CODE_STUDIO] astream wrapper failed: %s",
                stream_err_outer,
            )
            astream_timed_out = True

        if astream_timed_out:
            # Graceful path when the entire streaming pass had to be cancelled
            # (provider-level hang or connection reset that the per-chunk
            # timeout could not interrupt).
            try:
                manual_tc, visible_caption = _build_scaffold_manual_tool_call(
                    query, reason="stream_overall_timeout"
                )
                llm_response = _AM(content=visible_caption, tool_calls=[manual_tc])
            except Exception as scaffold_err:
                logger.warning(
                    "[CODE_STUDIO] Scaffold construction after stream timeout failed: %s",
                    scaffold_err,
                )

        if llm_response is None:
            llm_response = _AM(content="")

        has_tool_calls = bool(llm_response and getattr(llm_response, "tool_calls", None))
        if not has_tool_calls and code_streamer.is_code_html_complete and code_streamer.full_code_html:
            logger.info(
                "[CODE_STUDIO] No tool_calls in astream response, constructing from streamed code_html (%d chars)",
                len(code_streamer.full_code_html),
            )
            manual_tc = {
                "name": "tool_create_visual_code",
                "args": {
                    "code_html": code_streamer.full_code_html,
                    "title": query[:60] if query else "Visual",
                },
                "id": f"manual_tc_{uuid.uuid4().hex[:8]}",
            }
            llm_response = _AM(
                content=getattr(llm_response, "content", "") if llm_response else "",
                tool_calls=[manual_tc],
            )
        elif not has_tool_calls and not code_streamer.full_code_html:
            # Stream finished/timed-out without producing either a tool call
            # or any usable code_html. Fall through to the topic-aware scaffold
            # so the user still gets a canvas instead of an empty turn.
            logger.warning(
                "[CODE_STUDIO] Stream produced no tool_calls and no code_html — "
                "engaging graceful HTML scaffold"
            )
            manual_tc, visible_caption = _build_scaffold_manual_tool_call(
                query, reason="stream_empty"
            )
            llm_response = _AM(
                content=visible_caption,
                tool_calls=[manual_tc],
            )
    else:
        progress_messages = build_code_studio_progress_messages(query, state)
        # Non-streaming planning call — operator-tunable so the graceful
        # scaffold can engage well before the user's HTTP timeout. The
        # streaming path covers the same query type within
        # ``code_studio_stream_overall_timeout_seconds`` when the provider
        # is healthy; an unhealthy provider fails over to the topic-aware
        # scaffold rather than burning a multi-minute wait.
        llm_hard_timeout = float(getattr(settings_obj, "code_studio_llm_hard_timeout_seconds", 90.0))
        poll_interval = 8.0

        async def llm_call():
            return await ainvoke_with_fallback(
                llm_with_tools,
                messages,
                tools=tools,
                tool_choice=forced_tool_choice,
                provider=provider,
                push_event=push_event,
                timeout_profile=TIMEOUT_PROFILE_BACKGROUND,
            )

        llm_task = asyncio.create_task(llm_call())
        progress_idx = 0
        llm_start = time.time()
        llm_response = None
        planning_beat = await render_reasoning_fast(
            state=state,
            node="code_studio_agent",
            phase="attune",
            cue=infer_code_studio_reasoning_cue(query, []),
            tool_names=[],
            next_action="Chốt cấu trúc sáng tạo trước, rồi mới gọi công cụ để dựng thành thứ có thể mở ra ngay.",
            observations=["Đang ở lượt dựng đầu tiên cho lane sáng tạo này."],
            style_tags=["code-studio", "planning"],
        )
        await push_event(
            {
                "type": "thinking_start",
                "content": thinking_start_label(planning_beat.label),
                "node": "code_studio_agent",
                "summary": planning_beat.summary,
                "details": {"phase": planning_beat.phase},
            }
        )
        for chunk in code_studio_delta_chunks(planning_beat):
            await push_event({"type": "thinking_delta", "content": chunk, "node": "code_studio_agent"})
        await push_event(
            {
                "type": "status",
                "content": format_code_studio_progress_message(progress_messages[0], 0),
                "step": "code_generation",
                "node": "code_studio_agent",
                "details": {"visibility": "status_only"},
            }
        )
        heartbeat_task = asyncio.create_task(
            stream_code_studio_wait_heartbeats(
                push_event,
                query=query,
                state=state,
                interval_sec=poll_interval,
            )
        )
        progress_idx = 1
        while not llm_task.done():
            if time.time() - llm_start > llm_hard_timeout:
                llm_task.cancel()
                logger.warning("[CODE_STUDIO] ainvoke hard timeout after %ds", llm_hard_timeout)
                await push_event(
                    {
                        "type": "status",
                        "content": build_code_studio_retry_status(
                            query,
                            state,
                            elapsed_seconds=time.time() - llm_start,
                        ),
                        "step": "code_generation",
                        "node": "code_studio_agent",
                        "details": {"visibility": "status_only"},
                    }
                )
                try:
                    from app.engine.llm_pool import get_llm_moderate

                    fallback_llm = get_llm_moderate()
                    if tools:
                        if forced_tool_choice:
                            fallback_llm = fallback_llm.bind_tools(tools, tool_choice=forced_tool_choice)
                        else:
                            fallback_llm = fallback_llm.bind_tools(tools)
                    fallback_ainvoke_timeout = float(getattr(
                        settings_obj,
                        "code_studio_fallback_ainvoke_timeout_seconds",
                        60.0,
                    ))
                    llm_response = await asyncio.wait_for(
                        fallback_llm.ainvoke(messages),
                        timeout=fallback_ainvoke_timeout,
                    )
                except Exception as fb_err:
                    logger.warning(
                        "[CODE_STUDIO] Fallback ainvoke also failed (%s) — engaging "
                        "graceful HTML scaffold so user still gets a canvas",
                        fb_err,
                    )
                    manual_tc, visible_caption = _build_scaffold_manual_tool_call(
                        query, reason="ainvoke_fallback_fail"
                    )
                    llm_response = _AM(
                        content=visible_caption,
                        tool_calls=[manual_tc],
                    )
                break
            try:
                await asyncio.wait_for(asyncio.shield(llm_task), timeout=poll_interval)
            except asyncio.TimeoutError:
                msg = progress_messages[min(progress_idx, len(progress_messages) - 1)]
                await push_event(
                    {
                        "type": "status",
                        "content": format_code_studio_progress_message(msg, time.time() - llm_start),
                        "step": "code_generation",
                        "node": "code_studio_agent",
                        "details": {"visibility": "status_only"},
                    }
                )
                progress_idx += 1
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        await push_event({"type": "thinking_end", "content": "", "node": "code_studio_agent"})
        if llm_response is None:
            if llm_task.cancelled():
                logger.warning(
                    "[CODE_STUDIO] LLM call cancelled — engaging graceful HTML scaffold"
                )
                manual_tc, visible_caption = _build_scaffold_manual_tool_call(
                    query, reason="ainvoke_cancelled"
                )
                llm_response = _AM(
                    content=visible_caption,
                    tool_calls=[manual_tc],
                )
            else:
                llm_exc = llm_task.exception()
                if llm_exc is not None:
                    logger.warning(
                        "[CODE_STUDIO] Initial tool-planning call failed before any tool call (%s) "
                        "— engaging graceful HTML scaffold",
                        llm_exc,
                    )
                    manual_tc, visible_caption = _build_scaffold_manual_tool_call(
                        query, reason="ainvoke_exception"
                    )
                    llm_response = _AM(
                        content=visible_caption,
                        tool_calls=[manual_tc],
                    )
                else:
                    llm_response = llm_task.result()

    has_initial_tool_calls = bool(llm_response and getattr(llm_response, "tool_calls", None))
    if not has_initial_tool_calls and requires_code_studio_visual_delivery(query, tools):
        logger.warning(
            "[CODE_STUDIO] LLM returned prose without tool call but visual "
            "delivery is required — engaging graceful HTML scaffold"
        )
        manual_tc, visible_caption = _build_scaffold_manual_tool_call(
            query, reason="llm_prose_no_tool_call"
        )
        llm_response = _AM(
            content=visible_caption,
            tool_calls=[manual_tc],
        )

    total_tool_calls = 0
    max_total_tool_calls = 6
    # Sprint 35e follow-up: cap the post-tool synthesizer round so the
    # graceful scaffold path doesn't burn 15+ minutes when NVIDIA NIM
    # stalls after our scaffold tool result lands. Without this cap,
    # ``TIMEOUT_PROFILE_BACKGROUND`` lets the wait stretch indefinitely.
    post_tool_synthesis_timeout = float(getattr(
        settings_obj,
        "code_studio_post_tool_synthesis_timeout_seconds",
        90.0,
    ))

    for tool_round in range(max_rounds):
        if not (tools and hasattr(llm_response, "tool_calls") and llm_response.tool_calls):
            break
        if total_tool_calls >= max_total_tool_calls:
            logger.warning("[CODE_STUDIO] Total tool call cap reached (%d), stopping retry loop", max_total_tool_calls)
            break

        round_tool_names = [
            str(_normalize_tc(tc).get("name", "unknown"))
            for tc in llm_response.tool_calls
            if _normalize_tc(tc).get("name")
        ]
        round_cue = infer_code_studio_reasoning_cue(query, round_tool_names)
        round_phase = "verify" if tool_round > 0 else "ground"
        try:
            round_beat = await render_reasoning_fast(
                state=state,
                node="code_studio_agent",
                phase=round_phase,
                cue=round_cue,
                tool_names=round_tool_names,
                next_action="Mo cong cu can thiet roi xac minh output co the dung that.",
                observations=[f"Sap goi {len(round_tool_names)} cong cu trong vong nay."],
                style_tags=["code-studio", "tooling"],
            )
        except Exception as rr_err:
            logger.debug("[CODE_STUDIO] _render_reasoning failed: %s", rr_err)
            round_beat = None

        if round_beat is not None:
            await push_status_only_progress(
                push_event,
                node="code_studio_agent",
                content=(getattr(round_beat, "action_text", "") or getattr(round_beat, "summary", "")),
                step="code_generation",
                subtype="tool_round",
            )
        else:
            await push_event(
                {
                    "type": "status",
                    "content": "Đang tạo mã nguồn...",
                    "step": "code_generation",
                    "node": "code_studio_agent",
                    "details": {"visibility": "status_only"},
                }
            )

        messages.append(llm_response)
        terminal_failure_detected = False
        terminal_failure_tool_name: str | None = None
        visual_session_ids: list[str] = []
        active_visual_session_ids = collect_active_visual_session_ids(state)
        logger.info(
            "[CODE_STUDIO] Entering tool round %d/%d, %d tool_calls in response",
            tool_round + 1,
            max_rounds,
            len(llm_response.tool_calls),
        )
        for tc in llm_response.tool_calls:
            total_tool_calls += 1
            if total_tool_calls > max_total_tool_calls:
                logger.warning("[CODE_STUDIO] Skipping tool call %d (cap %d)", total_tool_calls, max_total_tool_calls)
                break
            tc_dict = _normalize_tc(tc)
            tc_id = tc_dict.get("id") or f"tc_{tool_round}"
            tc_name = tc_dict.get("name", "unknown")
            tc_args = tc_dict.get("args") or {}
            logger.info(
                "[CODE_STUDIO] Invoking tool %s (id=%s, args_keys=%s)",
                tc_name, tc_id, list(tc_args.keys()) if isinstance(tc_args, dict) else "?",
            )
            await push_event({"type": "tool_call", "content": {"name": tc_name, "args": tc_args, "id": tc_id}, "node": "code_studio_agent"})
            tool_call_events.append({"type": "call", "name": tc_name, "args": tc_args, "id": tc_id})
            matched = get_tool_by_name(tools, str(tc_name).strip())
            logger.info(
                "[CODE_STUDIO] Tool match: %s (matched=%s, tools_count=%d)",
                tc_name, bool(matched), len(tools),
            )
            try:
                if matched:
                    result = await invoke_tool_with_runtime(
                        matched,
                        tc_args,
                        tool_name=tc_name,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tc_id,
                        query_snippet=str(tc_args.get("query", "") if isinstance(tc_args, dict) else "")[:100],
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                    logger.info(
                        "[CODE_STUDIO] Tool %s returned %d chars (preview: %s)",
                        tc_name, len(str(result)), str(result)[:120].replace("\n", " "),
                    )
                else:
                    logger.warning(
                        "[CODE_STUDIO] Unknown tool %s; available: %s",
                        tc_name,
                        [getattr(t, "name", "?") for t in tools],
                    )
                    result = "Unknown tool"
            except Exception as te:
                logger.warning("[CODE_STUDIO] Tool %s failed: %s", tc_name, te, exc_info=True)
                result = "Tool unavailable"

            await push_event(
                {
                    "type": "tool_result",
                    "content": {"name": tc_name, "result": summarize_tool_result_for_stream(tc_name, result), "id": tc_id},
                    "node": "code_studio_agent",
                }
            )
            emitted_visual_session_ids, disposed_visual_session_ids = await maybe_emit_visual_event(
                push_event=push_event,
                tool_name=tc_name,
                tool_call_id=tc_id,
                result=result,
                node="code_studio_agent",
                tool_call_events=tool_call_events,
                previous_visual_session_ids=active_visual_session_ids,
                skip_fake_chunking=code_open_emitted,
                code_session_id_override=(
                    stream_session_id
                    or derive_code_stream_session_id(runtime_context_base=runtime_context_base, state=state)
                ),
            )

            if code_open_emitted and tc_name == "tool_create_visual_code" and emitted_visual_session_ids:
                try:
                    from app.engine.tools.visual_tools import parse_visual_payloads as pvp

                    vps = pvp(result)
                    if vps:
                        await push_event(
                            {
                                "type": "code_complete",
                                "content": {
                                    "session_id": stream_session_id,
                                    "full_code": vps[0].fallback_html or "",
                                    "language": "html",
                                    "version": 1,
                                    "visual_payload": vps[0].model_dump(mode="json"),
                                    "visual_session_id": emitted_visual_session_ids[0] if emitted_visual_session_ids else "",
                                },
                                "node": "code_studio_agent",
                            }
                        )
                except Exception as cc_err:
                    logger.debug("[CODE_STUDIO] code_complete emission failed: %s", cc_err)

            if emitted_visual_session_ids:
                visual_session_ids.extend(emitted_visual_session_ids)
                active_visual_session_ids = list(dict.fromkeys(emitted_visual_session_ids))
            elif disposed_visual_session_ids:
                active_visual_session_ids = [
                    session_id
                    for session_id in active_visual_session_ids
                    if session_id not in set(disposed_visual_session_ids)
                ]
            reflection = await build_code_studio_tool_reflection(state, tc_name, result)
            if reflection:
                await push_status_only_progress(
                    push_event,
                    node="code_studio_agent",
                    content=reflection,
                    step="code_generation",
                    subtype="tool_reflection",
                )
            tool_call_events.append({"type": "result", "name": tc_name, "result": str(result), "id": tc_id})
            messages.append(_TM(content=str(result), tool_call_id=tc_id))
            if is_terminal_code_studio_tool_error(tc_name, result):
                terminal_failure_detected = True
                terminal_failure_tool_name = str(tc_name)

        await emit_visual_commit_events(
            push_event=push_event,
            node="code_studio_agent",
            visual_session_ids=visual_session_ids,
            tool_call_events=tool_call_events,
        )
        await push_event({"type": "thinking_end", "content": "", "node": "code_studio_agent"})
        if terminal_failure_detected:
            if str(terminal_failure_tool_name or "").strip() == "tool_create_visual_code":
                llm_response = _AM(
                    content=build_code_studio_missing_tool_response(
                        query,
                        state,
                        timed_out=True,
                    )
                )
            else:
                llm_response = _AM(content=build_code_studio_terminal_failure_response(query, tool_call_events))
            break
        try:
            llm_response = await asyncio.wait_for(
                ainvoke_with_fallback(
                    llm_auto,
                    messages,
                    tools=tools,
                    provider=provider,
                    push_event=push_event,
                    timeout_profile=TIMEOUT_PROFILE_BACKGROUND,
                ),
                timeout=post_tool_synthesis_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                "[CODE_STUDIO] Post-tool synthesizer exceeded %.1fs — keeping "
                "scaffold output and emitting a short Vietnamese summary",
                post_tool_synthesis_timeout,
            )
            llm_response = _AM(
                content=(
                    "Mình đã ghim canvas ngay phía trên. Chia sẻ thêm chi tiết "
                    "(tâm trạng nhân vật, bối cảnh, hoặc tham số cụ thể) để "
                    "Wiii mở rộng cảnh đúng hướng nhé."
                )
            )
            break
        except Exception as synth_err:
            logger.warning(
                "[CODE_STUDIO] Post-tool synthesizer failed (%s) — keeping "
                "scaffold output and emitting a short Vietnamese summary",
                synth_err,
            )
            llm_response = _AM(
                content=(
                    "Mình đã ghim canvas ngay phía trên. Chia sẻ thêm chi tiết "
                    "để Wiii mở rộng cảnh đúng hướng nhé."
                )
            )
            break
        if tools and hasattr(llm_response, "tool_calls") and llm_response.tool_calls:
            transition = await render_reasoning_fast(
                state=state,
                node="code_studio_agent",
                phase="act",
                cue=round_cue,
                tool_names=round_tool_names,
                next_action="Rut gon thanh mot buoc thuc hien tiep theo roi moi chot.",
                observations=["Da co them ket qua moi va dang can khau lai."],
                style_tags=["code-studio", "transition"],
            )
            await push_event(
                {
                    "type": "action_text",
                    "content": transition.action_text or transition.summary,
                    "node": "code_studio_agent",
                }
            )

    synthesis_tool_names = [
        str(event.get("name", "")) for event in tool_call_events if event.get("type") == "call"
    ]
    synthesis_cue = infer_code_studio_reasoning_cue(query, synthesis_tool_names)
    synthesis_observations = build_code_studio_synthesis_observations(tool_call_events)
    synthesis_beat = await render_reasoning_fast(
        state=state,
        node="code_studio_agent",
        phase="synthesize",
        cue=synthesis_cue,
        tool_names=synthesis_tool_names,
        next_action="Noi ro da tao xong san pham nao, no dung de lam gi, va nguoi dung co the mo artifact ay ngay luc nay.",
        observations=synthesis_observations,
        style_tags=["code-studio", "synthesis"],
    )
    await push_event(
        {
            "type": "thinking_start",
            "content": thinking_start_label(synthesis_beat.label),
            "node": "code_studio_agent",
            "summary": synthesis_beat.summary,
            "details": {"phase": synthesis_beat.phase},
        }
    )
    for chunk in code_studio_delta_chunks(synthesis_beat):
        await push_event({"type": "thinking_delta", "content": chunk, "node": "code_studio_agent"})
    await push_event({"type": "thinking_end", "content": "", "node": "code_studio_agent"})

    llm_response = inject_widget_blocks_from_tool_results(
        llm_response,
        tool_call_events,
        query=query,
        structured_visuals_enabled=getattr(settings_obj, "enable_structured_visuals", False),
    )

    return llm_response, messages, tool_call_events
