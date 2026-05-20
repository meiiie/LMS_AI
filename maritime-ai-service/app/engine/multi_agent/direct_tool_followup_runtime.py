"""Follow-up LLM/tool selection after direct tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.direct_prompts import _resolve_tool_choice, _tool_name
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
            llm_base
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
