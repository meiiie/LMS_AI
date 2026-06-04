"""Fallback/persistence helpers extracted from chat_orchestrator.py."""

from __future__ import annotations


def persist_chat_message_impl(
    *,
    chat_history,
    session_id,
    role: str,
    content: str,
    user_id: str | None = None,
    organization_id: str | None = None,
    background_save=None,
    immediate: bool = False,
) -> None:
    """Persist a chat message using transport-specific timing."""
    if not content:
        return
    if not chat_history or not chat_history.is_available():
        return

    if immediate or background_save is None:
        chat_history.save_message(
            session_id,
            role,
            content,
            user_id,
            organization_id=organization_id,
        )
        return

    background_save(
        chat_history.save_message,
        session_id,
        role,
        content,
        user_id,
        organization_id=organization_id,
    )


def upsert_thread_view_impl(
    *,
    logger_obj,
    user_id: str,
    session_id,
    domain_id: str | None,
    title: str,
    organization_id: str | None,
) -> None:
    """Keep thread discovery state aligned across sync and streaming paths."""
    if not title:
        return

    try:
        from app.repositories.thread_repository import get_thread_repository
        from app.core.thread_utils import build_thread_id

        thread_repo = get_thread_repository()
        if not thread_repo.is_available():
            return

        thread_id = build_thread_id(
            str(user_id),
            str(session_id),
            org_id=organization_id,
        )
        thread_repo.upsert_thread(
            thread_id=thread_id,
            user_id=str(user_id),
            domain_id=domain_id or "maritime",
            title=title[:50],
            message_count_increment=2,
            organization_id=organization_id,
        )
    except Exception as exc:
        logger_obj.warning("[ORCHESTRATOR] thread_views upsert failed: %s", exc)


def should_use_local_direct_llm_fallback_impl(*, settings_obj) -> bool:
    """Use direct local inference when local mode is enabled without cloud retrieval support."""
    provider = getattr(settings_obj, "llm_provider", "google")
    return provider == "ollama" and not settings_obj.google_api_key


def _has_fast_chatter_blocking_context(context) -> bool:
    """Keep deterministic replies away from file, host-action, and tool turns."""
    if context is None:
        return True
    return any(
        bool(getattr(context, field_name, None))
        for field_name in (
            "images",
            "image_input_error",
            "document_context",
            "force_skills",
            "pointy_mode",
            "host_action_feedback",
        )
    )


def _build_social_chatter_answer(message: str, shape: str) -> tuple[str, str]:
    from app.engine.multi_agent.supervisor_hint_runtime import (
        _normalize_router_text_impl,
    )

    normalized = _normalize_router_text_impl(message)
    if shape == "reaction":
        return (
            "Mình nghe thấy rồi. Nếu cậu muốn, cứ ném phần tiếp theo qua đây, mình bắt nhịp cùng cậu.",
            "Đây chỉ là một phản ứng ngắn, không phải lượt cần tra cứu hay dùng tool. Mình nên đáp lại có mặt, gọn, và mở đường để cậu nói tiếp.",
        )
    if any(marker in normalized for marker in ("cam on", "thanks", "thank you", "thank")):
        return (
            "Không có gì đâu, mình ở đây mà. Cần mình phụ tiếp đoạn nào thì cứ nói nhé.",
            "Cậu đang cảm ơn, nên câu trả lời tốt nhất là ấm, ngắn, không kéo pipeline LLM chỉ để tạo thêm chữ.",
        )
    if any(marker in normalized for marker in ("tam biet", "bye", "goodbye", "hen gap lai")):
        return (
            "Ừ, mình tạm gác ở đây nha. Khi cậu quay lại, mình tiếp tục cùng cậu từ mạch đang làm.",
            "Đây là lượt kết thúc nhẹ, nên Wiii nên giữ cảm giác liên tục thay vì route sang RAG hoặc tool.",
        )
    if "alo" in normalized:
        return (
            "Mình nghe đây. Cậu cần mình phụ phần nào trước?",
            "Câu này là tín hiệu gọi Wiii, không có yêu cầu tri thức hay hành động. Mình đáp nhanh để cuộc trò chuyện không bị khựng.",
        )
    return (
        "Chào cậu, mình đây. Cậu muốn mình cùng xử lý phần nào trước?",
        "Đây là lời chào rất rõ, không cần RAG, web hay tool. Mình nên phản hồi ngay để tạo nhịp tự nhiên rồi chờ yêu cầu thật sự của cậu.",
    )


def build_fast_chatter_result_impl(
    *,
    context,
    processing_result_cls,
    agent_type_direct,
    routing_method: str = "fast_chatter",
    model_name: str = "wiii-fast-chatter-v1",
):
    """Return deterministic direct output for obvious short social turns."""
    if _has_fast_chatter_blocking_context(context):
        return None

    message = getattr(context, "message", "") or ""
    from app.engine.multi_agent.supervisor_hint_runtime import (
        classify_fast_chatter_turn_impl,
    )

    classification = classify_fast_chatter_turn_impl(message)
    if not classification:
        return None

    intent, shape = classification
    if intent != "social":
        return None

    if shape == "hunger_chatter":
        from app.engine.multi_agent.direct_node_chatter_runtime import (
            _build_hunger_chatter_answer,
            _build_hunger_chatter_thinking,
        )

        answer = _build_hunger_chatter_answer(message)
        thinking = _build_hunger_chatter_thinking(message)
    elif shape in {"social", "reaction"}:
        answer, thinking = _build_social_chatter_answer(message, shape)
    else:
        return None

    return processing_result_cls(
        message=answer,
        agent_type=agent_type_direct,
        sources=None,
        metadata={
            "multi_agent": False,
            "provider": "deterministic",
            "model": model_name,
            "runtime_authoritative": True,
            "current_agent": "direct",
            "tools_used": [],
            "reasoning_trace": None,
            "thinking": thinking,
            "thinking_content": thinking,
            "routing_metadata": {
                "method": routing_method,
                "intent": intent,
                "shape": shape,
                "reason": "obvious_short_social_turn_without_tool_context",
            },
        },
        thinking=thinking,
    )


def _runtime_text(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _authoritative_runtime_metadata(runtime_llm: dict | None, llm=None) -> dict:
    metadata = dict(runtime_llm or {})
    provider = _runtime_text(getattr(llm, "_wiii_provider_name", None)) or _runtime_text(
        metadata.get("_execution_provider")
    ) or _runtime_text(
        metadata.get("provider")
    )
    model = _runtime_text(getattr(llm, "model", None)) or _runtime_text(
        metadata.get("_execution_model")
    ) or _runtime_text(metadata.get("model"))

    if provider:
        metadata["provider"] = provider
        metadata["_execution_provider"] = provider
    if model:
        metadata["model"] = model
        metadata["_execution_model"] = model
    if provider and model:
        metadata["runtime_authoritative"] = True
    return metadata


async def process_with_direct_llm_impl(
    *,
    context,
    get_llm_light_fn,
    extract_thinking_from_response_fn,
    resolve_runtime_llm_metadata_fn,
    processing_result_cls,
    agent_type_direct,
):
    """Generate a local-first response without RAG when cloud retrieval is unavailable."""
    llm = get_llm_light_fn()
    response = await llm.ainvoke([{"role": "user", "content": context.message}])
    message, thinking = extract_thinking_from_response_fn(response.content)
    runtime_llm = _authoritative_runtime_metadata(
        resolve_runtime_llm_metadata_fn(),
        llm=llm,
    )

    return processing_result_cls(
        message=message,
        agent_type=agent_type_direct,
        metadata={
            "mode": "local_direct_llm",
            **runtime_llm,
        },
        thinking=thinking,
    )


async def process_without_multi_agent_impl(
    *,
    context,
    rag_agent,
    output_processor,
    logger_obj,
    should_use_local_direct_llm_fallback: bool,
    process_with_direct_llm_fn,
    resolve_runtime_llm_metadata_fn,
    processing_result_cls,
    agent_type_rag,
    agent_type_direct="direct",
):
    """Run the authoritative non-multi-agent fallback used by sync and stream."""
    fast_result = build_fast_chatter_result_impl(
        context=context,
        processing_result_cls=processing_result_cls,
        agent_type_direct=agent_type_direct,
    )
    if fast_result is not None:
        logger_obj.warning("[FALLBACK] Multi-Agent unavailable, using deterministic chatter")
        return fast_result

    if should_use_local_direct_llm_fallback:
        logger_obj.warning("[FALLBACK] Multi-Agent unavailable, using local direct LLM")
        return await process_with_direct_llm_fn(context)

    logger_obj.warning("[FALLBACK] Multi-Agent unavailable, using direct RAG")

    if rag_agent:
        rag_result = await rag_agent.query(
            question=context.message,
            user_role=context.user_role.value,
            limit=5,
        )
        runtime_llm = _authoritative_runtime_metadata(resolve_runtime_llm_metadata_fn())
        return processing_result_cls(
            message=rag_result.content,
            agent_type=agent_type_rag,
            sources=output_processor.format_sources(rag_result.citations) if rag_result.citations else None,
            metadata={
                "mode": "fallback_rag",
                **runtime_llm,
            },
            thinking=getattr(rag_result, "native_thinking", None),
        )

    logger_obj.error("[ERROR] No processing agent available")
    raise RuntimeError("No processing agent available")
