"""Shared direct-lane runtime bindings decoupled from the graph shell."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Optional

from app.engine.multi_agent.code_studio_response import (
    _truncate_before_code_dump as _truncate_before_code_dump,
)
from app.engine.multi_agent.graph_runtime_helpers import (
    _extract_runtime_target,
    _is_native_runtime_handle as _is_native_runtime_handle,
    _remember_runtime_target,
)
from app.engine.multi_agent.graph_surface_runtime import render_reasoning_fast_impl
from app.engine.multi_agent.openai_stream_runtime import (
    _create_openai_compatible_stream_client_impl,
    _extract_openai_delta_text_impl,
    _resolve_openai_stream_model_name_impl,
    _stream_openai_compatible_answer_with_route_impl,
    _supports_native_answer_streaming_impl,
)
from app.engine.multi_agent.state import AgentState
from app.engine.native_chat_runtime import message_to_openai_payload
from app.engine.multi_agent.widget_surface import (
    _inject_widget_blocks_from_tool_results as _inject_widget_blocks_from_tool_results,
)


@dataclass(frozen=True)
class DirectToolRuntimeBindings:
    """Graph-compatible callable bindings used by the direct tool loop."""

    ainvoke_with_fallback: Any
    stream_direct_answer_with_fallback: Any
    stream_direct_wait_heartbeats: Any
    build_direct_tool_reflection: Any
    maybe_emit_host_action_event: Any
    maybe_emit_visual_event: Any
    emit_visual_commit_events: Any
    get_tool_by_name: Any
    invoke_tool_with_runtime: Any


@dataclass(frozen=True)
class DirectToolProviderPolicy:
    """Per-turn provider/failover helpers for direct tool-loop calls."""

    state: AgentState
    llm_base: Any
    llm_auto: Any
    llm_with_tools: Any
    request_failover_mode: str
    resolved_provider: str | None

    def remember_execution_target(
        self,
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> tuple[str | None, str | None]:
        provider_name, model_name = _remember_runtime_target(self.state, candidate_llm)
        if (not provider_name or not model_name) and fallback_source is not None:
            fallback_provider, fallback_model = _remember_runtime_target(
                self.state,
                fallback_source,
            )
            provider_name = provider_name or fallback_provider
            model_name = model_name or fallback_model
        return provider_name, model_name

    def runtime_tier_for(
        self,
        candidate_llm: Any,
        fallback_source: Any | None = None,
    ) -> str:
        for source in (
            candidate_llm,
            fallback_source,
            self.llm_base,
            self.llm_auto,
            self.llm_with_tools,
        ):
            tier_value = (
                getattr(source, "_wiii_tier_key", None) if source is not None else None
            )
            if isinstance(tier_value, str) and tier_value.strip():
                return tier_value.strip().lower()
        return "moderate"


def resolve_direct_tool_runtime_bindings(
    *,
    ainvoke_with_fallback: Any,
    stream_direct_answer_with_fallback: Any,
    stream_direct_wait_heartbeats: Any,
    build_direct_tool_reflection: Any,
    maybe_emit_host_action_event: Any,
    maybe_emit_visual_event: Any,
    emit_visual_commit_events: Any,
    get_tool_by_name: Any,
    invoke_tool_with_runtime: Any,
) -> DirectToolRuntimeBindings:
    """Resolve graph override bindings used by the direct tool loop."""

    graph_module = sys.modules.get("app.engine.multi_agent.graph")
    return DirectToolRuntimeBindings(
        ainvoke_with_fallback=getattr(
            graph_module,
            "_ainvoke_with_fallback",
            ainvoke_with_fallback,
        ),
        stream_direct_answer_with_fallback=getattr(
            graph_module,
            "_stream_direct_answer_with_fallback",
            stream_direct_answer_with_fallback,
        ),
        stream_direct_wait_heartbeats=getattr(
            graph_module,
            "_stream_direct_wait_heartbeats",
            stream_direct_wait_heartbeats,
        ),
        build_direct_tool_reflection=getattr(
            graph_module,
            "_build_direct_tool_reflection",
            build_direct_tool_reflection,
        ),
        maybe_emit_host_action_event=getattr(
            graph_module,
            "_maybe_emit_host_action_event",
            maybe_emit_host_action_event,
        ),
        maybe_emit_visual_event=getattr(
            graph_module,
            "_maybe_emit_visual_event",
            maybe_emit_visual_event,
        ),
        emit_visual_commit_events=getattr(
            graph_module,
            "_emit_visual_commit_events",
            emit_visual_commit_events,
        ),
        get_tool_by_name=getattr(graph_module, "get_tool_by_name", get_tool_by_name),
        invoke_tool_with_runtime=getattr(
            graph_module,
            "invoke_tool_with_runtime",
            invoke_tool_with_runtime,
        ),
    )


def build_direct_tool_provider_policy(
    *,
    state: AgentState,
    provider: str | None,
    llm_base: Any,
    llm_auto: Any,
    llm_with_tools: Any,
    failover_mode_auto: str,
    failover_mode_pinned: str,
) -> DirectToolProviderPolicy:
    """Build provider/failover state helpers for one direct tool-loop turn."""

    request_failover_mode = (
        failover_mode_pinned
        if provider and str(provider).strip().lower() != "auto"
        else failover_mode_auto
    )
    resolved_provider = _extract_runtime_target(llm_base or llm_auto or llm_with_tools)[0]
    return DirectToolProviderPolicy(
        state=state,
        llm_base=llm_base,
        llm_auto=llm_auto,
        llm_with_tools=llm_with_tools,
        request_failover_mode=request_failover_mode,
        resolved_provider=resolved_provider,
    )


def _graph_override(name: str, current):
    graph_module = sys.modules.get("app.engine.multi_agent.graph")
    if graph_module is None:
        return None
    candidate = getattr(graph_module, name, None)
    if candidate is None or candidate is current:
        return None
    return candidate


def _langchain_message_to_openai_payload(message: Any) -> dict[str, Any]:
    return message_to_openai_payload(message)


async def _stream_openai_compatible_answer_with_route(
    route,
    messages: list,
    push_event,
    *,
    node: str = "direct",
    thinking_stop_signal=None,
    primary_timeout: float | None = None,
) -> tuple[object | None, bool]:
    override = _graph_override("_stream_openai_compatible_answer_with_route", _stream_openai_compatible_answer_with_route)
    if override is not None:
        return await override(
            route,
            messages,
            push_event,
            node=node,
            thinking_stop_signal=thinking_stop_signal,
            primary_timeout=primary_timeout,
        )
    return await _stream_openai_compatible_answer_with_route_impl(
        route,
        messages,
        push_event,
        node=node,
        thinking_stop_signal=thinking_stop_signal,
        primary_timeout=primary_timeout,
        supports_native_answer_streaming=_supports_native_answer_streaming_impl,
        create_openai_compatible_stream_client=_create_openai_compatible_stream_client_impl,
        resolve_openai_stream_model_name=_resolve_openai_stream_model_name_impl,
        langchain_message_to_openai_payload=_langchain_message_to_openai_payload,
        extract_openai_delta_text=_extract_openai_delta_text_impl,
    )


async def _render_reasoning_fast(
    *,
    state: AgentState,
    node: str,
    phase: str,
    intent: str = "",
    cue: str = "",
    next_action: str = "",
    tool_names: Optional[list[str]] = None,
    result: object = None,
    observations: Optional[list[str]] = None,
    confidence: float = 0.0,
    visibility_mode: str = "rich",
    style_tags: Optional[list[str]] = None,
    thinking_mode: str = "",
    topic_hint: str = "",
    evidence_plan: Optional[list[str]] = None,
    analytical_axes: Optional[list[str]] = None,
):
    override = _graph_override("_render_reasoning_fast", _render_reasoning_fast)
    if override is not None:
        return await override(
            state=state,
            node=node,
            phase=phase,
            intent=intent,
            cue=cue,
            next_action=next_action,
            tool_names=tool_names,
            result=result,
            observations=observations,
            confidence=confidence,
            visibility_mode=visibility_mode,
            style_tags=style_tags,
            thinking_mode=thinking_mode,
            topic_hint=topic_hint,
            evidence_plan=evidence_plan,
            analytical_axes=analytical_axes,
        )
    return await render_reasoning_fast_impl(
        state=state,
        node=node,
        phase=phase,
        intent=intent,
        cue=cue,
        next_action=next_action,
        tool_names=tool_names,
        result=result,
        observations=observations,
        confidence=confidence,
        visibility_mode=visibility_mode,
        style_tags=style_tags,
        thinking_mode=thinking_mode,
        topic_hint=topic_hint,
        evidence_plan=evidence_plan,
        analytical_axes=analytical_axes,
    )
