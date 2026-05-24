"""Direct-node deterministic pre-LLM pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    has_uploaded_document_context as _has_uploaded_document_context,
)
from app.engine.multi_agent.direct_node_document_preflight import (
    build_document_preview_response_sanitizer,
    execute_direct_node_document_preview_preflight,
    record_uploaded_document_context_plan,
)
from app.engine.multi_agent.direct_node_fast_response_runtime import (
    resolve_direct_node_fast_response,
)
from app.engine.multi_agent.direct_node_image_input_preflight import (
    execute_direct_node_image_input_preflight,
)
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _strip_dsml_residue,
)
from app.engine.multi_agent.direct_node_pre_llm_stage_contract import (
    DirectDocumentPreviewPreflightDependencies,
    DirectDocumentPreviewPreflightRequest,
    DirectImageInputPreflightDependencies,
    DirectImageInputPreflightRequest,
    DirectNodeFastResponseDependencies,
    DirectNodeFastResponseRequest,
)
from app.engine.multi_agent.direct_node_turn_start import start_direct_node_turn
from app.engine.multi_agent.direct_node_uploaded_context import (
    _looks_uploaded_document_preview_request,
)
from app.engine.multi_agent.direct_node_visible_thought import (
    _strip_direct_inline_private_asides,
)
from app.engine.multi_agent.state import AgentState


@dataclass(slots=True)
class DirectNodePreLlmPipelineResult:
    """Resolved deterministic state before direct-node provider execution."""

    query_lower: str
    response: str | None
    response_type: str
    explicit_web_search_turn: bool
    ctx_for_preflight: dict[str, Any]
    has_uploaded_document_context: bool
    domain_name_vi: str
    sanitize_document_preview_response: Callable[[str, list[dict[str, Any]]], str]


@dataclass(frozen=True, slots=True)
class DirectNodePreLlmPipelineRequest:
    """Per-turn input for deterministic direct-node pre-LLM stages."""

    query: str
    state: AgentState
    bus_id: str | None
    push_event: Callable[..., Any]
    tracer: Any
    enable_natural_conversation: bool
    default_domain: str


@dataclass(frozen=True, slots=True)
class DirectNodePreLlmPipelineDependencies:
    """Injected contracts used by document/image/fast-response pre-LLM stages."""

    get_domain_greetings: Callable[[str], dict[str, str]]
    normalize_for_intent: Callable[[str], str]
    needs_web_search: Callable[[str], bool]
    needs_datetime: Callable[[str], bool]
    build_visual_tool_runtime_metadata: Callable[..., dict[str, Any]]
    execute_direct_tool_rounds: Callable[..., Any]
    extract_direct_response: Callable[..., Any]
    sanitize_structured_visual_answer_text: Callable[..., str]
    sanitize_wiii_house_text: Callable[..., str]
    record_thinking_snapshot_fn: Callable[..., Any]
    logger_obj: logging.Logger
    start_turn_fn: Callable[..., Any] = start_direct_node_turn
    has_uploaded_document_context_fn: Callable[[dict[str, Any]], bool] = (
        _has_uploaded_document_context
    )
    build_preview_sanitizer_fn: Callable[..., Callable[..., str]] = (
        build_document_preview_response_sanitizer
    )
    record_document_plan_fn: Callable[..., None] = record_uploaded_document_context_plan
    document_preview_preflight_fn: Callable[..., Any] = (
        execute_direct_node_document_preview_preflight
    )
    image_input_preflight_fn: Callable[..., Any] = execute_direct_node_image_input_preflight
    fast_response_fn: Callable[..., Any] = resolve_direct_node_fast_response


def _resolve_domain_name_vi(
    *,
    state: AgentState,
    default_domain: str,
) -> str:
    domain_config = state.get("domain_config", {})
    domain_name_vi = domain_config.get("name_vi", "") if isinstance(domain_config, dict) else ""
    if domain_name_vi:
        return str(domain_name_vi)

    domain_id = state.get("domain_id", default_domain)
    return {
        "maritime": "Hang hai",
        "traffic_law": "Luat Giao thong",
    }.get(domain_id, str(domain_id))


async def execute_direct_node_pre_llm_pipeline(
    *,
    request: DirectNodePreLlmPipelineRequest,
    dependencies: DirectNodePreLlmPipelineDependencies,
) -> DirectNodePreLlmPipelineResult:
    """Run deterministic direct-node work before provider/tool-loop execution."""

    query = request.query
    state = request.state
    ctx_for_preflight = (
        state.get("context", {}) if isinstance(state.get("context"), dict) else {}
    )

    turn_start = dependencies.start_turn_fn(
        query=query,
        state=state,
        enable_natural_conversation=request.enable_natural_conversation,
        default_domain=request.default_domain,
        get_domain_greetings=dependencies.get_domain_greetings,
        record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
    )
    query_lower = turn_start.query_lower
    response = turn_start.response
    response_type = turn_start.response_type
    explicit_web_search_turn = turn_start.explicit_web_search_turn

    has_uploaded_document_context = dependencies.has_uploaded_document_context_fn(
        ctx_for_preflight
    )

    sanitize_document_preview_response = dependencies.build_preview_sanitizer_fn(
        query=query,
        sanitize_structured_visual_answer_text=(
            dependencies.sanitize_structured_visual_answer_text
        ),
        sanitize_wiii_house_text=dependencies.sanitize_wiii_house_text,
        strip_direct_inline_private_asides=_strip_direct_inline_private_asides,
        strip_dsml_residue=_strip_dsml_residue,
    )

    document_thinking = (
        "Mình nhận đây là lượt hỏi có tài liệu upload đã được parse thành Markdown, "
        "nên ưu tiên đối chiếu marker, bảng và các dòng trong document_context trước khi suy luận thêm. "
        "Nếu phần nào không có trong file, Wiii phải nói rõ thay vì bịa."
    )
    dependencies.record_document_plan_fn(
        state=state,
        response_present=bool(response),
        has_uploaded_document_context=has_uploaded_document_context,
        document_thinking=document_thinking,
        record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
    )

    document_preflight_result = await dependencies.document_preview_preflight_fn(
        request=DirectDocumentPreviewPreflightRequest(
            query=query,
            state=state,
            ctx=ctx_for_preflight,
            bus_id=request.bus_id,
            response_present=bool(response),
            has_uploaded_document_context=has_uploaded_document_context,
            push_event=request.push_event,
        ),
        dependencies=DirectDocumentPreviewPreflightDependencies(
            looks_uploaded_document_preview_request=(
                _looks_uploaded_document_preview_request
            ),
            build_visual_tool_runtime_metadata=(
                dependencies.build_visual_tool_runtime_metadata
            ),
            execute_direct_tool_rounds=dependencies.execute_direct_tool_rounds,
            extract_direct_response=dependencies.extract_direct_response,
            sanitize_preview_response=sanitize_document_preview_response,
            fallback_response=(
                "Mình đã gửi bản preview bài học sang LMS. "
                "Giáo viên cần xem phần so sánh thay đổi và nguồn trích dẫn rồi bấm Áp dụng để cấp approval_token."
            ),
            logger_obj=dependencies.logger_obj,
        ),
    )
    if document_preflight_result is not None:
        response = document_preflight_result.response
        response_type = document_preflight_result.response_type

    image_preflight_result = await dependencies.image_input_preflight_fn(
        request=DirectImageInputPreflightRequest(
            query=query,
            state=state,
            ctx=ctx_for_preflight,
            response_present=bool(response),
            has_uploaded_document_context=has_uploaded_document_context,
        ),
        dependencies=DirectImageInputPreflightDependencies(
            record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
        ),
    )
    if image_preflight_result is not None:
        response = image_preflight_result.response
        response_type = image_preflight_result.response_type

    if not response:
        fast_response = dependencies.fast_response_fn(
            request=DirectNodeFastResponseRequest(
                query=query,
                state=state,
                ctx=ctx_for_preflight,
                has_uploaded_document_context=has_uploaded_document_context,
            ),
            dependencies=DirectNodeFastResponseDependencies(
                normalize_for_intent=dependencies.normalize_for_intent,
                needs_web_search=dependencies.needs_web_search,
                needs_datetime=dependencies.needs_datetime,
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
                logger_obj=dependencies.logger_obj,
            ),
        )
        if fast_response is not None:
            response = fast_response.response
            response_type = fast_response.response_type

    domain_name_vi = _resolve_domain_name_vi(
        state=state,
        default_domain=request.default_domain,
    )

    if response:
        request.tracer.end_step(
            result=f"Direct fast response: {response[:50]}...",
            confidence=1.0,
            details={"response_type": response_type or "greeting", "query": query_lower},
        )

    return DirectNodePreLlmPipelineResult(
        query_lower=query_lower,
        response=response,
        response_type=response_type,
        explicit_web_search_turn=explicit_web_search_turn,
        ctx_for_preflight=ctx_for_preflight,
        has_uploaded_document_context=has_uploaded_document_context,
        domain_name_vi=domain_name_vi,
        sanitize_document_preview_response=sanitize_document_preview_response,
    )
