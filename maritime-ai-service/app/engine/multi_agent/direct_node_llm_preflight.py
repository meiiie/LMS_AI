"""Direct-node LLM selection and preflight guards."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from app.engine.multi_agent.graph_runtime_helpers import (
    _copy_runtime_metadata,
    _extract_runtime_target,
    _is_native_runtime_handle,
)
from app.engine.multi_agent.state import AgentState


@dataclass(slots=True)
class DirectNodeLlmSelection:
    direct_node_id: str
    native_direct_possible: bool
    llm: Any | None


@dataclass(slots=True)
class DirectNodeUploadedVisualGuard:
    response: str
    provider: str | None
    model: str | None


@dataclass(slots=True)
class DirectNodeLlmPreflightResult:
    """Resolved direct-node LLM state before the tool loop executes."""

    llm: Any | None
    response: str
    selection: DirectNodeLlmSelection
    visual_guard: DirectNodeUploadedVisualGuard | None


def select_direct_node_llm(
    *,
    is_identity_turn: bool,
    ctx: dict[str, Any],
    is_short_house_chatter: bool,
    is_emotional_support_turn: bool,
    use_house_voice_direct: bool,
    is_codebase_source_turn: bool,
    response_present: bool,
    thinking_effort: str | None,
    direct_provider_override: str | None,
    requested_model: str | None,
    get_native_llm: Callable[..., Any],
    get_llm: Callable[..., Any],
    supports_native_answer_streaming: Callable[[str | None], bool],
) -> DirectNodeLlmSelection:
    """Choose the direct-node LLM without binding tools or executing it."""

    if is_identity_turn:
        direct_node_id = "direct_identity"
    elif is_short_house_chatter:
        direct_node_id = "direct_chatter"
    else:
        direct_node_id = "direct"
    native_direct_possible = (
        not bool(ctx.get("images") or [])
        and not is_short_house_chatter
        and not is_identity_turn
        and not is_emotional_support_turn
        and not use_house_voice_direct
        and not is_codebase_source_turn
    )

    llm = None
    if native_direct_possible and not response_present:
        llm = get_native_llm(
            direct_node_id,
            effort_override=thinking_effort,
            provider_override=direct_provider_override,
            requested_model=requested_model,
        )
        if llm and not supports_native_answer_streaming(
            getattr(llm, "_wiii_provider_name", None)
        ):
            llm = None

    if llm is None and not response_present:
        llm = get_llm(
            direct_node_id,
            effort_override=thinking_effort,
            provider_override=direct_provider_override,
            requested_model=requested_model,
        )

    return DirectNodeLlmSelection(
        direct_node_id=direct_node_id,
        native_direct_possible=native_direct_possible,
        llm=llm,
    )


def maybe_build_uploaded_visual_guard(
    *,
    llm: Any | None,
    query: str,
    state: AgentState,
    ctx_for_preflight: dict[str, Any],
    has_uploaded_document_context: bool,
    direct_provider_override: str | None,
    preferred_provider: str | None,
    looks_uploaded_file_visual_inspection_query: Callable[[str], bool],
    provider_likely_supports_image_blocks: Callable[[str | None, str | None], bool],
    build_uploaded_document_visual_guard_answer: Callable[[str, dict[str, Any]], str],
    extract_runtime_target: Callable[[Any | None], tuple[str | None, str | None]] = _extract_runtime_target,
) -> DirectNodeUploadedVisualGuard | None:
    """Return an uploaded-file visual guard when a text-only provider is selected."""

    llm_provider_for_images, llm_model_for_images = (
        extract_runtime_target(llm) if llm else (None, None)
    )
    llm_provider_for_images = (
        llm_provider_for_images or direct_provider_override or preferred_provider
    )
    llm_model_for_images = llm_model_for_images or state.get("model")

    if not (
        llm
        and has_uploaded_document_context
        and looks_uploaded_file_visual_inspection_query(query)
        and not provider_likely_supports_image_blocks(
            llm_provider_for_images,
            llm_model_for_images,
        )
    ):
        return None

    response = build_uploaded_document_visual_guard_answer(query, ctx_for_preflight)
    if not response:
        return None

    ctx_for_preflight["images"] = []
    return DirectNodeUploadedVisualGuard(
        response=response,
        provider=llm_provider_for_images,
        model=llm_model_for_images,
    )


def apply_direct_node_natural_conversation_penalties(
    llm: Any | None,
    *,
    response_present: bool,
    enable_natural_conversation: bool,
    presence_penalty: float,
    frequency_penalty: float,
    is_native_runtime_handle: Callable[[Any | None], bool] = _is_native_runtime_handle,
    copy_runtime_metadata: Callable[[Any | None, Any | None], Any] = _copy_runtime_metadata,
) -> Any | None:
    """Bind natural-conversation penalties while preserving Wiii runtime metadata."""

    if (
        not llm
        or response_present
        or not enable_natural_conversation
        or is_native_runtime_handle(llm)
        or not (presence_penalty or frequency_penalty)
    ):
        return llm

    try:
        return copy_runtime_metadata(
            llm,
            llm.bind(
                presence_penalty=presence_penalty,
                frequency_penalty=frequency_penalty,
            ),
        )
    except Exception:
        return llm


def prepare_direct_node_llm_preflight(
    *,
    query: str,
    state: AgentState,
    ctx: dict[str, Any],
    ctx_for_preflight: dict[str, Any],
    has_uploaded_document_context: bool,
    response: str,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    is_emotional_support_turn: bool,
    use_house_voice_direct: bool,
    is_codebase_source_turn: bool,
    thinking_effort: str | None,
    direct_provider_override: str | None,
    preferred_provider: str | None,
    requested_model: str | None,
    enable_natural_conversation: bool,
    presence_penalty: float,
    frequency_penalty: float,
    get_native_llm: Callable[..., Any],
    get_llm: Callable[..., Any],
    supports_native_answer_streaming: Callable[[str | None], bool],
    looks_uploaded_file_visual_inspection_query: Callable[[str], bool],
    provider_likely_supports_image_blocks: Callable[[str | None, str | None], bool],
    build_uploaded_document_visual_guard_answer: Callable[[str, dict[str, Any]], str],
    tracer: Any,
    logger_obj: logging.Logger,
    select_llm_fn: Callable[..., DirectNodeLlmSelection] = select_direct_node_llm,
    build_visual_guard_fn: Callable[
        ...,
        DirectNodeUploadedVisualGuard | None,
    ] = maybe_build_uploaded_visual_guard,
    apply_penalties_fn: Callable[..., Any | None] = (
        apply_direct_node_natural_conversation_penalties
    ),
) -> DirectNodeLlmPreflightResult:
    """Select an LLM, apply uploaded-file guards, then bind safe penalties."""

    selection = select_llm_fn(
        is_identity_turn=is_identity_turn,
        ctx=ctx,
        is_short_house_chatter=is_short_house_chatter,
        is_emotional_support_turn=is_emotional_support_turn,
        use_house_voice_direct=use_house_voice_direct,
        is_codebase_source_turn=is_codebase_source_turn,
        response_present=bool(response),
        thinking_effort=thinking_effort,
        direct_provider_override=direct_provider_override,
        requested_model=requested_model,
        get_native_llm=get_native_llm,
        get_llm=get_llm,
        supports_native_answer_streaming=supports_native_answer_streaming,
    )
    llm = selection.llm

    visual_guard = build_visual_guard_fn(
        llm=llm,
        query=query,
        state=state,
        ctx_for_preflight=ctx_for_preflight,
        has_uploaded_document_context=has_uploaded_document_context,
        direct_provider_override=direct_provider_override,
        preferred_provider=preferred_provider,
        looks_uploaded_file_visual_inspection_query=(
            looks_uploaded_file_visual_inspection_query
        ),
        provider_likely_supports_image_blocks=provider_likely_supports_image_blocks,
        build_uploaded_document_visual_guard_answer=(
            build_uploaded_document_visual_guard_answer
        ),
    )
    if visual_guard is not None:
        response = visual_guard.response
        logger_obj.info(
            "[DIRECT] Uploaded video frame question routed to text-only provider; "
            "returned visual guard fallback (provider=%s model=%s)",
            visual_guard.provider,
            visual_guard.model,
        )
        tracer.end_step(
            result="Uploaded-file visual guard fallback (text-only provider)",
            confidence=0.7,
            details={
                "response_type": "uploaded_file_visual_guard_fallback",
                "provider": visual_guard.provider,
                "model": visual_guard.model,
            },
        )

    llm = apply_penalties_fn(
        llm,
        response_present=bool(response),
        enable_natural_conversation=enable_natural_conversation,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
    )

    return DirectNodeLlmPreflightResult(
        llm=llm,
        response=response,
        selection=selection,
        visual_guard=visual_guard,
    )
