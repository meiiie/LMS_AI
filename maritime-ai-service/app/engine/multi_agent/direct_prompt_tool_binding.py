"""Direct prompt tool binding helpers.

Kept outside ``direct_prompts`` so provider-aware tool-choice behavior can be
reviewed and tested without loading the full prompt assembly surface.
"""

from __future__ import annotations

from app.engine.multi_agent.graph_runtime_helpers import _copy_runtime_metadata


def _tool_name(tool: object) -> str:
    """Return a stable tool name for binding and telemetry."""
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def _resolve_tool_choice(
    force: bool, tools: list, provider: str | None = None,
) -> str | None:
    """Translate force_tool intent → provider-specific tool_choice value.

    Single tool → exact name (works on all providers).
    Multiple tools → provider-aware "force any":
      - google/zhipu: "any"  (Gemini mode=ANY)
      - openai:       "required"
      - ollama:       "any"  (best-effort)
    """
    if not force:
        return None
    if len(tools) == 1:
        name = _tool_name(tools[0])
        if name:
            return name
    if not provider:
        from app.engine.llm_pool import LLMPool
        provider = LLMPool.get_active_provider() or "google"
    if provider == "openai":
        return "required"
    return "any"


def _bind_direct_tools(
    llm,
    tools: list,
    force: bool,
    provider: str | None = None,
    *,
    include_forced_choice: bool = False,
):
    """Bind tools to LLM with optional forced calling.

    Sprint 154: Extracted from direct_response_node.
    Provider-aware: translates force intent to correct tool_choice
    for Gemini ("any"), OpenAI ("required"), etc.

    Returns:
        tuple: (llm_with_tools, llm_auto) by default for backward compatibility.
        When ``include_forced_choice=True`` it returns
        ``(llm_with_tools, llm_auto, forced_choice)``.
    """
    forced_choice = None
    if tools:
        llm_auto = _copy_runtime_metadata(llm, llm.bind_tools(tools))
        forced_choice = _resolve_tool_choice(force, tools, provider)
        if forced_choice:
            llm_with_tools = _copy_runtime_metadata(
                llm,
                llm.bind_tools(tools, tool_choice=forced_choice),
            )
        else:
            llm_with_tools = llm_auto
    else:
        llm_with_tools = llm
        llm_auto = llm
    if include_forced_choice:
        return llm_with_tools, llm_auto, forced_choice
    return llm_with_tools, llm_auto
