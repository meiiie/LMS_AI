"""Direct-node deterministic image-input preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_image_input_thinking,
    _build_image_input_unavailable_answer,
    _build_image_input_unavailable_thinking,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_uploaded_context import _build_image_input_answer
from app.engine.multi_agent.state import AgentState


@dataclass(frozen=True)
class DirectImageInputPreflightResult:
    response: str
    response_type: str


async def execute_direct_node_image_input_preflight(
    *,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    response_present: bool,
    has_uploaded_document_context: bool,
    record_thinking_snapshot_fn: Callable[..., Any],
) -> DirectImageInputPreflightResult | None:
    """Resolve image-input turns before the direct node falls through to an LLM."""

    if ctx.get("image_input_error") and has_uploaded_document_context:
        ctx["images"] = []
    if response_present:
        return None

    if ctx.get("image_input_error") and not has_uploaded_document_context:
        fast_thinking = _build_image_input_unavailable_thinking()
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input_unavailable",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )
        return DirectImageInputPreflightResult(
            response=_build_image_input_unavailable_answer(query),
            response_type="image_input_unavailable",
        )

    if ctx.get("images") and not has_uploaded_document_context:
        fast_thinking = _build_image_input_thinking(query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input",
            record_thinking_snapshot_fn=record_thinking_snapshot_fn,
        )
        return DirectImageInputPreflightResult(
            response=await _build_image_input_answer(
                query,
                list(ctx.get("images") or []),
            ),
            response_type="image_input",
        )

    return None
