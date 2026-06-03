"""Deterministic fast-response selection for the direct node."""

from __future__ import annotations

from typing import Any, Callable

from app.engine.multi_agent.direct_node_meta_fast_paths import (
    _build_reasoning_safety_meta_answer,
    _build_reasoning_safety_meta_thinking,
    _build_self_feeling_probe_answer,
    _build_self_feeling_probe_thinking,
    _build_wiii_capability_inventory_answer,
    _build_wiii_capability_inventory_thinking,
    _looks_self_feeling_probe_turn,
)
from app.engine.multi_agent.direct_node_operational_fast_paths import (
    _build_pointy_fast_path_thinking,
    _build_pointy_missing_inventory_answer,
    _build_pointy_missing_inventory_thinking,
    _build_wiii_pipeline_meta_answer,
    _build_wiii_pipeline_meta_thinking,
    _extract_direct_reply_only_answer,
    _extract_pointy_fast_path_answer,
    _pointy_requested_without_inventory,
)
from app.engine.multi_agent.direct_node_thinking_snapshot import (
    record_direct_node_thinking_snapshot,
)
from app.engine.multi_agent.direct_node_pre_llm_stage_contract import (
    DirectNodeFastResponse,
    DirectNodeFastResponseDependencies,
    DirectNodeFastResponseRequest,
)
from app.engine.multi_agent.direct_node_uploaded_context import (
    _build_uploaded_document_context_fallback_answer,
    _looks_uploaded_context_fact_query,
    _looks_uploaded_file_visual_inspection_query,
)
from app.engine.multi_agent.direct_session_memory_runtime import (
    _build_session_memory_write_answer,
    _build_session_memory_write_thinking,
    _extract_session_memory_recall_answer,
    _with_requested_response_marker,
)
from app.engine.multi_agent.direct_text_utils import _fold_direct_text
from app.engine.multi_agent.external_app_action_runtime import (
    record_external_app_action_plan,
    resolve_external_app_action_plan,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor_runtime_support import (
    _looks_reasoning_safety_meta_turn,
    _looks_session_memory_ack_only_turn,
    _looks_session_memory_recall_turn,
    _looks_session_memory_write_turn,
    _looks_wiii_capability_inventory_turn,
    _looks_wiii_pipeline_meta_turn,
)
from app.engine.multi_agent.wiii_connect_intent import (
    build_wiii_connect_facebook_post_unavailable_answer,
    build_wiii_connect_provider_status_answer,
    looks_wiii_connect_external_app_action_request_for_state,
    looks_wiii_connect_facebook_post_request_for_state,
    looks_wiii_connect_facebook_status_request,
    resolve_wiii_connect_status_provider_slugs,
)


RecordThinkingSnapshot = Callable[..., Any]


def _record_fast_thinking(
    *,
    state: AgentState,
    thinking: str,
    provenance: str,
    record_thinking_snapshot_fn: RecordThinkingSnapshot,
) -> None:
    """Store visible thinking for a deterministic fast response."""

    record_direct_node_thinking_snapshot(
        state=state,
        thinking=thinking,
        provenance=provenance,
        record_thinking_snapshot_fn=record_thinking_snapshot_fn,
    )


def resolve_direct_node_fast_response(
    *,
    request: DirectNodeFastResponseRequest,
    dependencies: DirectNodeFastResponseDependencies,
) -> DirectNodeFastResponse | None:
    """Resolve deterministic fast responses before the planner/provider path."""

    query = request.query
    state = request.state
    ctx = request.ctx
    try:
        routing_meta_for_fast = state.get("routing_metadata") or {}
        fast_method = str(routing_meta_for_fast.get("method") or "").strip().lower()
        fast_intent = str(routing_meta_for_fast.get("intent") or "").strip().lower()
        normalized_for_fast = dependencies.normalize_for_intent(query)
        status_provider_slugs = resolve_wiii_connect_status_provider_slugs(query)
        if status_provider_slugs:
            response = "\n\n".join(
                build_wiii_connect_provider_status_answer(
                    state,
                    provider_slug=provider_slug,
                )
                for provider_slug in status_provider_slugs[:3]
            )
            response_type = (
                "wiii_connect_facebook_status"
                if looks_wiii_connect_facebook_status_request(query)
                and status_provider_slugs == ("facebook",)
                else "wiii_connect_provider_status"
            )
            provenance = (
                "deterministic_wiii_connect_facebook_status"
                if response_type == "wiii_connect_facebook_status"
                else "deterministic_wiii_connect_provider_status"
            )
            _record_fast_thinking(
                state=state,
                thinking=(
                    "Mình nhận đây là câu hỏi trạng thái Wiii Connect/provider. "
                    "Trả lời từ snapshot runtime thay vì để model đoán hoặc phủ nhận capability."
                ),
                provenance=provenance,
                record_thinking_snapshot_fn=(
                    dependencies.record_thinking_snapshot_fn
                ),
            )
            return DirectNodeFastResponse(response, response_type)
        if looks_wiii_connect_facebook_post_request_for_state(query, state):
            external_action_plan = resolve_external_app_action_plan(
                query=query,
                state=state,
                ready_provider_slugs=None,
            )
            record_external_app_action_plan(state, external_action_plan)
            response = (
                external_action_plan.unavailable_answer
                or build_wiii_connect_facebook_post_unavailable_answer(state)
            )
            if response:
                _record_fast_thinking(
                    state=state,
                    thinking=(
                        "Mình nhận đây là yêu cầu đăng Facebook. Kiểm tra Wiii Connect snapshot trước khi gọi model; "
                        "nếu Facebook chưa agent-ready thì fail-closed thay vì để model đoán hoặc hứa đã đăng."
                    ),
                    provenance="deterministic_wiii_connect_facebook_unavailable",
                    record_thinking_snapshot_fn=(
                        dependencies.record_thinking_snapshot_fn
                    ),
                )
                return DirectNodeFastResponse(
                    response,
                    "wiii_connect_facebook_unavailable",
                )
        if looks_wiii_connect_external_app_action_request_for_state(query, state):
            external_action_plan = resolve_external_app_action_plan(
                query=query,
                state=state,
                ready_provider_slugs=None,
            )
            record_external_app_action_plan(state, external_action_plan)
            if (
                external_action_plan.status == "blocked"
                and external_action_plan.unavailable_answer
            ):
                _record_fast_thinking(
                    state=state,
                    thinking=(
                        "Mình nhận đây là yêu cầu hành động qua ứng dụng ngoài. "
                        "Kiểm tra provider/action plan trước khi gọi model; nếu thiếu provider "
                        "hoặc provider chưa agent-ready thì fail-closed thay vì để model đoán."
                    ),
                    provenance="deterministic_wiii_connect_external_app_action_unavailable",
                    record_thinking_snapshot_fn=(
                        dependencies.record_thinking_snapshot_fn
                    ),
                )
                return DirectNodeFastResponse(
                    external_action_plan.unavailable_answer,
                    "wiii_connect_external_app_action_unavailable",
                )
        if state.get("_pointy_fast_path_action"):
            response = _extract_pointy_fast_path_answer(state)
            if response:
                _record_fast_thinking(
                    state=state,
                    thinking=_build_pointy_fast_path_thinking(state),
                    provenance="deterministic_pointy_fast_path",
                    record_thinking_snapshot_fn=(
                        dependencies.record_thinking_snapshot_fn
                    ),
                )
                return DirectNodeFastResponse(response, "pointy_fast_path")
        elif _pointy_requested_without_inventory(state):
            response = _build_pointy_missing_inventory_answer(query)
            _record_fast_thinking(
                state=state,
                thinking=_build_pointy_missing_inventory_thinking(query),
                provenance="deterministic_pointy_missing_inventory",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "pointy_missing_inventory")
        elif (
            _looks_self_feeling_probe_turn(query)
            and not dependencies.needs_web_search(query)
            and not dependencies.needs_datetime(query)
        ):
            response = _build_self_feeling_probe_answer(query)
            _record_fast_thinking(
                state=state,
                thinking=_build_self_feeling_probe_thinking(query),
                provenance="deterministic_self_feeling_probe",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "self_feeling_probe")
        elif (
            _looks_wiii_capability_inventory_turn(_fold_direct_text(query))
            and not dependencies.needs_web_search(query)
            and not dependencies.needs_datetime(query)
        ):
            response = _build_wiii_capability_inventory_answer(query)
            _record_fast_thinking(
                state=state,
                thinking=_build_wiii_capability_inventory_thinking(query),
                provenance="deterministic_wiii_capability_inventory",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "wiii_capability_inventory")
        elif (
            request.has_uploaded_document_context
            and _looks_uploaded_context_fact_query(query, ctx)
            and not _looks_uploaded_file_visual_inspection_query(query)
        ):
            response = _build_uploaded_document_context_fallback_answer(
                query,
                ctx,
                provider_unstable=False,
            )
            if response:
                _record_fast_thinking(
                    state=state,
                    thinking=(
                        "Mình nhận đây là câu hỏi fact-check trực tiếp về file/video vừa upload, "
                        "nên ưu tiên dữ kiện parser đã trích ra thay vì gọi LLM suy diễn."
                    ),
                    provenance="deterministic_uploaded_file_context_fact",
                    record_thinking_snapshot_fn=(
                        dependencies.record_thinking_snapshot_fn
                    ),
                )
                return DirectNodeFastResponse(response, "uploaded_file_context_fact")
        elif (
            fast_method == "conservative_fast_path"
            and fast_intent == "off_topic"
            and _looks_reasoning_safety_meta_turn(normalized_for_fast)
        ):
            response = _build_reasoning_safety_meta_answer(query)
            _record_fast_thinking(
                state=state,
                thinking=_build_reasoning_safety_meta_thinking(query),
                provenance="deterministic_reasoning_safety_meta",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "reasoning_safety_meta")
        elif (
            fast_method == "conservative_fast_path"
            and fast_intent == "off_topic"
            and _looks_wiii_pipeline_meta_turn(normalized_for_fast)
        ):
            response = _build_wiii_pipeline_meta_answer(query)
            _record_fast_thinking(
                state=state,
                thinking=_build_wiii_pipeline_meta_thinking(query),
                provenance="deterministic_wiii_pipeline_meta",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "wiii_pipeline_meta")
        elif (
            fast_method == "conservative_fast_path"
            and _looks_session_memory_recall_turn(normalized_for_fast)
        ):
            response = _extract_session_memory_recall_answer(state, query) or (
                "Mình chưa thấy đủ neo trong phiên này để nhắc lại chắc chắn."
            )
            response = _with_requested_response_marker(query, response)
            _record_fast_thinking(
                state=state,
                thinking=(
                    "Mình nhận đây là lượt gọi lại thông tin trong chính phiên này, "
                    "nên ưu tiên đọc lịch sử gần nhất thay vì ghi thêm memory mới."
                ),
                provenance="deterministic_session_memory_recall",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "session_memory_recall")
        elif (
            fast_method == "conservative_fast_path"
            and _looks_session_memory_ack_only_turn(normalized_for_fast)
        ):
            response = _extract_direct_reply_only_answer(query) or "Đã ghi nhận."
            state["_direct_reply_only_ack"] = True
            _record_fast_thinking(
                state=state,
                thinking=(
                    "Mình ghi nhận điều bạn muốn giữ trong phiên hiện tại và giữ phản hồi "
                    "đúng một câu như bạn yêu cầu."
                ),
                provenance="deterministic_session_ack",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "session_memory_ack")
        elif _looks_session_memory_write_turn(normalized_for_fast):
            response = _with_requested_response_marker(
                query,
                _build_session_memory_write_answer(query),
            )
            _record_fast_thinking(
                state=state,
                thinking=_build_session_memory_write_thinking(query),
                provenance="deterministic_session_memory_write",
                record_thinking_snapshot_fn=dependencies.record_thinking_snapshot_fn,
            )
            return DirectNodeFastResponse(response, "session_memory_write")
        elif (
            fast_method == "conservative_fast_path"
            and _looks_session_memory_recall_turn(normalized_for_fast)
        ):
            response = _extract_session_memory_recall_answer(state, query)
            if response:
                _record_fast_thinking(
                    state=state,
                    thinking=(
                        "Mình dùng ngữ cảnh ngay trong phiên này để nhắc lại đúng "
                        "mẫu thông tin bạn vừa yêu cầu Wiii giữ."
                    ),
                    provenance="deterministic_session_memory_recall",
                    record_thinking_snapshot_fn=(
                        dependencies.record_thinking_snapshot_fn
                    ),
                )
                return DirectNodeFastResponse(response, "session_memory_recall")
    except Exception as exc:  # noqa: BLE001
        if dependencies.logger_obj is not None:
            dependencies.logger_obj.debug(
                "[DIRECT] Session memory ack fast response skipped: %s",
                exc,
            )
    return None
