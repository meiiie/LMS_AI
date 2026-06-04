"""Direct-node deterministic image-input preflight."""

from __future__ import annotations

from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_image_input_thinking,
    _build_image_input_unavailable_answer,
    _build_image_input_unavailable_thinking,
)
from app.engine.multi_agent.direct_node_pre_llm_stage_contract import (
    DirectImageInputPreflightDependencies,
    DirectImageInputPreflightRequest,
    DirectImageInputPreflightResult,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_uploaded_context import _build_image_input_answer
from app.engine.multi_agent.wiii_connect_intent import (
    looks_wiii_connect_facebook_post_request_for_state,
)


async def execute_direct_node_image_input_preflight(
    *,
    request: DirectImageInputPreflightRequest,
    dependencies: DirectImageInputPreflightDependencies,
) -> DirectImageInputPreflightResult | None:
    """Resolve image-input turns before the direct node falls through to an LLM."""

    ctx = request.ctx
    state = request.state
    if ctx.get("image_input_error") and request.has_uploaded_document_context:
        ctx["images"] = []
    if request.response_present:
        return None
    if looks_wiii_connect_facebook_post_request_for_state(request.query, state):
        return None

    if ctx.get("image_input_error") and not request.has_uploaded_document_context:
        fast_thinking = _build_image_input_unavailable_thinking()
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input_unavailable",
            record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
        )
        return DirectImageInputPreflightResult(
            response=_build_image_input_unavailable_answer(request.query),
            response_type="image_input_unavailable",
        )

    if ctx.get("images") and not request.has_uploaded_document_context:
        fast_thinking = _build_image_input_thinking(request.query)
        record_direct_node_thinking_snapshot(
            state=state,
            thinking=fast_thinking,
            provenance="deterministic_image_input",
            record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
        )
        return DirectImageInputPreflightResult(
            response=await _build_image_input_answer(
                request.query,
                list(ctx.get("images") or []),
            ),
            response_type="image_input",
        )

    return None
