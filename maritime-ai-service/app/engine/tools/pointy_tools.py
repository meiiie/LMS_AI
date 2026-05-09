"""Wiii Pointy backend tools — agent-controlled cursor pointing.

Lets a chat agent point at UI elements during a conversation, the same
way OpenClicky's `/cursor` HTTP bridge works on macOS but rendered as
an in-frame SVG cursor with smooth arc animation. The cursor itself is
implemented in ``wiii-desktop/src/pointy-host/cursor.ts`` (Web
Animations API, 4-keyframe arc with cubic-bezier easing) — these tools
just emit the trigger.

## How dispatch works

1. The LLM calls ``tool_pointy_show(...)`` mid-answer.
2. The tool function returns a short acknowledgement string to the LLM
   so the streaming loop can continue.
3. The tool-dispatch interception in
   ``app/engine/multi_agent/agents/<node>_tool_dispatch_runtime.py``
   recognises the tool name and pushes a ``pointy_action`` SSE event
   carrying the target + caption + duration.
4. ``useSSEStream`` on the frontend dispatches the event into the
   already-built ``pointy-host`` bridge, which animates the cursor
   along a curved arc to the requested element.

The tool itself does **not** execute the cursor move — it's the
streaming runtime that emits the SSE event. This keeps the tool pure
(testable, no side effects on import) and the dispatch logic owns the
real-time streaming concern.

## When the agent should call it

See ``app/engine/skills/library/wiii-pointy/SKILL.md`` for the full
trigger taxonomy (when the user asks "where is X", "show me how to do
Y", "click on Z for me", etc.) and the Vietnamese / English caption
patterns the cursor uses.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, create_model

from app.engine.tools.native_tool import Tool, tool

logger = logging.getLogger(__name__)


# Action names match the existing pointy-host bridge protocol so the
# frontend can dispatch directly without a translation layer. Keep this
# in sync with ``wiii-desktop/src/pointy-host/types.ts`` POINTY_ACTIONS.
POINTY_ACTION_HIGHLIGHT = "ui.highlight"
POINTY_ACTION_CURSOR_MOVE = "ui.cursor_move"
POINTY_ACTION_CLEAR = "ui.clear"


@tool("tool_pointy_show")
def tool_pointy_show(
    selector: str,
    caption: str = "",
    duration_ms: int = 4500,
    mode: str = "highlight",
) -> str:
    """Point Wiii's collaborator cursor at a UI element on the user's screen.

    Use this when the user asks "where is the X button", "show me how to
    open Y", "highlight the Z field". The cursor swings along a smooth
    arc to the element, displays the caption next to it, then fades.

    Args:
        selector: EXACT id from tool_pointy_inventory. Annotated ids such
            as "chat-send-button" and scanner-generated synthetic ids such
            as "auto:button:gui-tin-nhan" are valid when they appear in
            inventory. DO NOT generate CSS selectors, aria-label patterns,
            .class selectors, or compound selectors — server-side validation
            rejects them with error tool_result để LLM correct trong round
            tiếp theo. If unsure, call tool_pointy_inventory first.
        caption: Short Vietnamese tooltip shown next to the cursor
            (≤80 chars, e.g. "Đây là nút gửi tin nhắn.").
        duration_ms: How long the spotlight stays on screen before
            fading. Range 1500-8000 ms; default 4500.
        mode: ``"highlight"`` (default — spotlight + tooltip + cursor),
            ``"cursor"`` (presence-only cursor without spotlight), or
            ``"clear"`` (remove any active overlay).

    Returns:
        A short acknowledgement string for the LLM so it can keep
        streaming. The actual SSE event is emitted by the tool-dispatch
        runtime when it sees the tool name.
    """
    target = (selector or "").strip()
    if not target and mode != "clear":
        return "[POINTY] selector required for highlight/cursor mode"
    duration_clamped = max(1500, min(int(duration_ms or 4500), 8000))
    label = (caption or "").strip()
    if len(label) > 80:
        label = label[:77].rstrip() + "…"
    logger.debug(
        "[POINTY_TOOL] mode=%s selector=%s caption=%r duration=%dms",
        mode, target, label, duration_clamped,
    )
    return f"[POINTY:{mode}] target={target!r} duration={duration_clamped}ms"


@tool("tool_pointy_clear")
def tool_pointy_clear() -> str:
    """Clear any active Wiii Pointy cursor / spotlight from the screen.

    Use this when you've finished pointing at a sequence of elements,
    or when the user explicitly says "thôi" / "stop pointing" /
    "clear that".

    Returns:
        Acknowledgement string. The streaming runtime emits the
        ``pointy_action`` clear SSE event.
    """
    return "[POINTY:clear]"


@tool("tool_pointy_inventory")
def tool_pointy_inventory() -> str:
    """List the pointable UI elements currently visible on screen.

    Use this when you need to know which buttons / links / inputs the
    user has on their screen RIGHT NOW before deciding which selector
    to pass to ``tool_pointy_show``. Especially useful when the user
    says something ambiguous like "click that" or "where do I go to
    submit?".

    The actual inventory is published by the frontend via the host
    context (``host_context.page.metadata.available_targets``). The
    tool dispatch layer reads that context and formats it for you;
    the tool function itself only emits the trigger.

    Returns:
        Marker string for the dispatch layer. The real inventory comes
        through as a SSE ``pointy_action`` event with mode="inventory"
        plus injected into the next observation message so you can
        read it before issuing another tool call.
    """
    return "[POINTY:inventory]"


def build_pointy_event(
    *,
    selector: str = "",
    caption: str = "",
    duration_ms: int = 4500,
    mode: str = "highlight",
    request_id: Optional[str] = None,
) -> dict:
    """Construct a ``pointy_action`` SSE event payload.

    Called by the tool-dispatch runtime when it intercepts a
    ``tool_pointy_show`` / ``tool_pointy_clear`` call. The shape matches
    the frontend ``PointyFastPathAction`` so ``useSSEStream`` can hand
    it straight to the ``pointy-host`` bridge.

    Args:
        selector: Element id or CSS selector.
        caption: Tooltip text.
        duration_ms: Spotlight duration (clamped 1500-8000).
        mode: One of ``highlight``, ``cursor``, ``clear``.
        request_id: Optional correlation id; auto-generated if absent.

    Returns:
        A dict ready to be wrapped as
        ``{"type": "pointy_action", "content": <payload>, "node": ...}``
        for the SSE pipeline.
    """
    if mode == "clear":
        action = POINTY_ACTION_CLEAR
    elif mode == "cursor":
        action = POINTY_ACTION_CURSOR_MOVE
    else:
        action = POINTY_ACTION_HIGHLIGHT
    duration_clamped = max(1500, min(int(duration_ms or 4500), 8000))
    label = (caption or "").strip()
    if len(label) > 80:
        label = label[:77].rstrip() + "…"
    rid = request_id or _make_request_id()
    return {
        "action": action,
        "requestId": rid,
        "params": {
            "selector": (selector or "").strip(),
            "message": label,
            "duration_ms": duration_clamped,
            "source": "agent_tool",
        },
        "mode": mode,
    }


def _make_request_id() -> str:
    import secrets
    return f"pointy-tool-{secrets.token_hex(6)}"


# ────────────────────────────────────────────────────────────────────────
# v9.0 F18 (2026-05-07) — Enum-constrained tool variant.
#
# SOTA reference: SeeAct (Zheng et al., ICML 2024 — arXiv:2401.01614).
# Textual multiple-choice grounding > free-form ID recall > image annotation.
# When AI must RECALL an unseen ID, error rate is 14-43%. When AI PICKS
# from an enumerated visible list, error rate drops to ~5-10%.
#
# `make_pointy_show_with_enum` clones the static tool with a Pydantic
# model whose `selector` field is `Literal[...]` populated at runtime
# from the current PageScanner inventory. JSON schema emits
# `"enum": [...]` constraint that OpenAI-compatible APIs (NVIDIA NIM
# DeepSeek, OpenAI tools) physically enforce.
# ────────────────────────────────────────────────────────────────────────


def make_pointy_show_with_enum(
    target_ids: list[str] | list[tuple[str, str]],
    *,
    fallback_to_static: bool = True,
) -> "Tool":
    """Build a tool_pointy_show variant with selector constrained to enum.

    Args:
        target_ids: Current page inventory. Either ``list[str]`` (ids only)
            or ``list[tuple[id, label]]`` for SeeAct-style textual
            multiple-choice grounding (preferred — LLM picks RIGHT id when
            it can read the label, not just the slug).
        fallback_to_static: When True (default), no inventory → return
            unchanged static tool. When False, raise ValueError.

    Returns:
        New ``Tool`` with the same name/handler but enum-constrained input.
    """
    pairs: list[tuple[str, str]] = []
    for item in (target_ids or []):
        if isinstance(item, tuple):
            tid, lbl = item
            tid_s = str(tid).strip()
            if tid_s:
                pairs.append((tid_s, str(lbl or "").strip()))
        elif item:
            tid_s = str(item).strip()
            if tid_s:
                pairs.append((tid_s, ""))
    if not pairs:
        if fallback_to_static:
            return tool_pointy_show
        raise ValueError("Cannot build enum-constrained tool with empty inventory")

    # Sanity cap — keep top 64 by order to bound prompt tokens.
    if len(pairs) > 64:
        pairs = pairs[:64]

    target_ids_clean = [p[0] for p in pairs]
    SelectorType = Literal[tuple(target_ids_clean)]  # type: ignore[valid-type]

    # SeeAct ICML'24: textual multiple-choice grounding > free-form ID
    # recall. Pair each id with its accessible label so LLM can choose
    # by INTENT instead of guessing slug→meaning. Without labels both
    # `chat-send-button` and `chat-textarea` look like valid answers
    # for "where is the send button" — LLM picks ~50/50.
    def _format_choice(tid: str, lbl: str) -> str:
        return f"{tid} — {lbl}" if lbl else tid

    rendered_choices = "; ".join(
        _format_choice(tid, lbl) for tid, lbl in pairs[:18]
    )
    desc_text = (
        "REQUIRED — pick EXACTLY one id below by matching the user's "
        "intent against the LABEL (not the slug). Choices: "
        f"{rendered_choices}"
        + ("; …" if len(pairs) > 18 else "")
    )
    DynamicArgs: type[BaseModel] = create_model(  # type: ignore[call-overload]
        "PointyShowEnumArgs",
        selector=(
            SelectorType,
            Field(description=desc_text),
        ),
        caption=(
            str,
            Field(
                default="",
                description="Short Vietnamese tooltip (≤80 chars).",
            ),
        ),
        duration_ms=(
            int,
            Field(
                default=4500,
                description="Spotlight duration ms (1500-8000).",
            ),
        ),
        mode=(
            str,
            Field(
                default="highlight",
                description='"highlight" (default), "cursor", or "clear".',
            ),
        ),
    )

    return Tool.from_function(
        tool_pointy_show.fn,
        name="tool_pointy_show",
        description=(
            "Point Wiii's cursor at a UI element. selector MUST be one "
            "of the exact ids from the current inventory enum. The cursor "
            "swings smoothly to the element + shows the caption."
        ),
        args_schema=DynamicArgs,
    )


def validate_pointy_target(
    selector: str,
    inventory_ids: list[str] | tuple[str, ...] | set[str],
) -> Optional[str]:
    """Server-side belt-and-suspenders validation.

    Returns None when selector valid, or an error message string when
    invalid (caller surfaces as tool_result with is_error=True so AI
    can retry with a correct id).
    """
    if not selector or not selector.strip():
        return "ERROR: empty selector. Pick from inventory."
    if selector not in set(inventory_ids):
        valid_preview = ", ".join(list(inventory_ids)[:8])
        return (
            f"ERROR: selector '{selector}' not in current inventory. "
            f"Valid ids: {valid_preview}. Re-call tool_pointy_show with "
            f"a valid id."
        )
    return None


def extract_inventory_ids_from_state(state: Any) -> list[str]:
    """Read available_targets ids from agent state's host_context."""
    return [tid for tid, _ in extract_inventory_pairs_from_state(state)]


def extract_inventory_pairs_from_state(state: Any) -> list[tuple[str, str]]:
    """Read (id, label) pairs from agent state's host_context.

    Label is the human-readable accessible name (button text, aria-label,
    title) the page scanner attached. Empty string when scanner couldn't
    derive one. Used by enum tool factory for SeeAct-style multiple-choice
    grounding.
    """
    if not isinstance(state, dict):
        return []
    ctx = state.get("context") or {}
    if not isinstance(ctx, dict):
        return []
    host = ctx.get("host_context") or state.get("host_context") or {}
    if not isinstance(host, dict):
        return []
    page = host.get("page") or {}
    metadata = page.get("metadata") or {} if isinstance(page, dict) else {}
    targets = metadata.get("available_targets") or []
    if not isinstance(targets, list):
        return []
    pairs: list[tuple[str, str]] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        tid = t.get("id")
        if not tid:
            continue
        label = t.get("label") or t.get("aria_label") or ""
        pairs.append((str(tid), str(label or "")))
    return pairs
