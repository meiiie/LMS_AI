"""Follow-up LLM/tool selection after direct tool execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Awaitable, Callable

from app.engine.multi_agent.direct_prompt_tool_binding import (
    _resolve_tool_choice,
    _tool_name,
)
from app.engine.multi_agent.visual_intent_resolver import (
    required_visual_tool_names,
)


@dataclass(slots=True)
class DirectToolFollowupSelection:
    """Invocation target and metadata for the next post-tool LLM call."""

    llm: Any
    tools: list[Any]
    tool_choice: Any | None
    fallback_source: Any | None


@dataclass(slots=True)
class DirectToolFollowupInvocation:
    """Post-tool LLM response and provider metadata."""

    llm_response: Any
    resolved_provider: str | None


def select_direct_tool_followup(
    *,
    llm_auto: Any,
    llm_base: Any,
    llm_with_tools: Any,
    tools: list[Any],
    requires_visual_commit: bool,
    visual_emitted_any: bool,
    visual_decision: Any,
    resolved_provider: str | None,
    provider: str | None,
) -> DirectToolFollowupSelection:
    """Choose the follow-up LLM and tool declarations after one tool round."""
    followup_llm = llm_auto
    followup_tool_choice = None
    followup_tools = tools
    bind_source = None

    if requires_visual_commit and not visual_emitted_any:
        required_visual_tool_name_set = set(required_visual_tool_names(visual_decision))
        visual_only_tools = [
            tool for tool in tools if _tool_name(tool) in required_visual_tool_name_set
        ]
        bind_source = (
            (llm_base if hasattr(llm_base, "bind_tools") else None)
            or (llm_auto if hasattr(llm_auto, "bind_tools") else None)
            or (llm_with_tools if hasattr(llm_with_tools, "bind_tools") else None)
        )
        if bind_source is not None and visual_only_tools:
            followup_tools = visual_only_tools
            followup_tool_choice = _resolve_tool_choice(
                True,
                visual_only_tools,
                resolved_provider or provider,
            )
            if followup_tool_choice:
                followup_llm = bind_source.bind_tools(
                    visual_only_tools,
                    tool_choice=followup_tool_choice,
                )
            else:
                followup_llm = bind_source.bind_tools(visual_only_tools)

    return DirectToolFollowupSelection(
        llm=followup_llm,
        tools=followup_tools,
        tool_choice=followup_tool_choice,
        fallback_source=bind_source or llm_base,
    )


async def invoke_direct_tool_followup(
    *,
    llm_auto: Any,
    llm_base: Any,
    llm_with_tools: Any,
    tools: list[Any],
    messages: list[Any],
    query: str,
    push_event: Callable[[dict[str, Any]], Awaitable[Any]],
    requires_visual_commit: bool,
    visual_emitted_any: bool,
    visual_decision: Any,
    resolved_provider: str | None,
    provider: str | None,
    request_failover_mode: str,
    followup_timeout_profile: str,
    state: dict[str, Any],
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None,
    ainvoke_with_fallback: Callable[..., Awaitable[Any]],
    stream_direct_wait_heartbeats: Callable[..., Awaitable[Any]],
    remember_execution_target: Callable[..., tuple[str | None, str | None]],
    runtime_tier_for: Callable[..., str],
    round_cue: str,
    round_tool_names: list[str],
    logger_obj: logging.Logger | None = None,
) -> DirectToolFollowupInvocation:
    """Run the post-tool follow-up LLM call with heartbeat lifecycle handling."""
    log = logger_obj or logging.getLogger(__name__)
    post_tool_heartbeat = asyncio.create_task(
        stream_direct_wait_heartbeats(
            push_event,
            query=query,
            phase="ground",
            cue=round_cue,
            tool_names=round_tool_names,
        )
    )
    try:
        followup_selection = select_direct_tool_followup(
            llm_auto=llm_auto,
            llm_base=llm_base,
            llm_with_tools=llm_with_tools,
            tools=tools,
            requires_visual_commit=requires_visual_commit,
            visual_emitted_any=visual_emitted_any,
            visual_decision=visual_decision,
            resolved_provider=resolved_provider,
            provider=provider,
        )
        candidate_provider, _candidate_model = remember_execution_target(
            followup_selection.llm,
            fallback_source=followup_selection.fallback_source,
        )
        next_resolved_provider = candidate_provider or resolved_provider
        llm_response = await ainvoke_with_fallback(
            followup_selection.llm,
            messages,
            tools=followup_selection.tools,
            tool_choice=followup_selection.tool_choice,
            tier=runtime_tier_for(
                followup_selection.llm,
                followup_selection.fallback_source,
            ),
            provider=provider,
            resolved_provider=next_resolved_provider,
            failover_mode=request_failover_mode,
            push_event=push_event,
            timeout_profile=followup_timeout_profile,
            state=state,
            allowed_fallback_providers=allowed_fallback_providers,
        )
        return DirectToolFollowupInvocation(
            llm_response=llm_response,
            resolved_provider=next_resolved_provider,
        )
    finally:
        post_tool_heartbeat.cancel()
        try:
            await post_tool_heartbeat
        except asyncio.CancelledError:
            pass
        except Exception as heartbeat_error:
            log.debug(
                "[DIRECT] Post-tool heartbeat shutdown skipped: %s",
                heartbeat_error,
            )
