"""Runtime support helpers for CorrectiveRAG orchestration."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _fold_source_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", folded).strip()


def answer_declines_rag_sources_impl(answer: str) -> bool:
    """Detect answers that explicitly refused to attach retrieved RAG sources."""
    folded = _fold_source_text(answer)
    return any(
        marker in folded
        for marker in (
            "khong gan citation rag",
            "chua thay nguon noi bo that su khop",
            "chua co du doan nguon ro rang",
        )
    )


def _normalize_cached_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure cached source payloads keep minimum UI-compatible fields."""
    for source in sources:
        if isinstance(source, dict) and "content_type" not in source:
            source["content_type"] = "text"
    return sources


async def get_query_embedding_impl(query: str) -> Optional[list[float]]:
    """Resolve a query embedding via the shared embedding authority."""
    if not query:
        return None

    try:
        from app.engine.embedding_runtime import get_embedding_backend

        backend = get_embedding_backend()
        embedding = await backend.aembed_query(query)
        if embedding:
            logger.info(
                "[CRAG] Query embedding resolved via provider=%s model=%s dims=%d",
                backend.provider,
                backend.model_name,
                len(embedding),
            )
            return embedding

        logger.warning("[CRAG] Query embedding backend returned empty vector")
        return None
    except Exception as exc:
        logger.warning("[CRAG] Query embedding failed: %s", exc)
        return None


async def get_document_embedding_impl(text: str) -> list[float]:
    """Resolve a document-style embedding via the shared embedding authority."""
    if not text:
        return []

    try:
        from app.engine.embedding_runtime import get_embedding_backend

        backend = get_embedding_backend()
        result = await backend.aembed_documents([text])
        embedding = result[0] if result else []
        if embedding:
            logger.info(
                "[CRAG] Document embedding resolved via provider=%s model=%s dims=%d",
                backend.provider,
                backend.model_name,
                len(embedding),
            )
            return embedding

        logger.warning("[CRAG] Document embedding backend returned empty vector")
        return []
    except Exception as exc:
        logger.warning("[CRAG] Document embedding failed: %s", exc)
        return []


async def build_cache_hit_result_impl(
    *,
    cache_result: Any,
    query: str,
    context: dict[str, Any],
    result_cls: type,
) -> Any:
    """Adapt a semantic cache hit into the public CorrectiveRAG result shape."""
    from app.engine.agentic_rag.adaptive_router import get_adaptive_router
    from app.engine.agentic_rag.thinking_adapter import get_thinking_adapter

    router = get_adaptive_router()
    routing = router.route(cache_result=cache_result)

    logger.info("[CRAG] Router: %s (%s)", routing.path.value, routing.reason)

    if routing.use_thinking_adapter:
        adapter = get_thinking_adapter()
        adapted = await adapter.adapt(
            query=query,
            cached_response=cache_result.value,
            context=context,
            similarity=cache_result.similarity,
        )

        logger.info(
            "[CRAG] ThinkingAdapter: %.0fms (method=%s)",
            adapted.adaptation_time_ms,
            adapted.adaptation_method,
        )

        cached_sources = _normalize_cached_sources(
            cache_result.value.get("sources", [])
        )
        return result_cls(
            answer=adapted.answer,
            sources=cached_sources,
            iterations=0,
            confidence=cache_result.value.get("confidence", 0.9),
            reasoning_trace=None,
            thinking=adapted.thinking,
            thinking_content=f"[Cache-Augmented Generation]\n{adapted.thinking}",
        )

    cached_data = cache_result.value
    cached_sources = _normalize_cached_sources(cached_data.get("sources", []))
    return result_cls(
        answer=cached_data.get("answer", ""),
        sources=cached_sources,
        iterations=0,
        confidence=cached_data.get("confidence", 0.9),
        reasoning_trace=None,
        thinking=cached_data.get("thinking"),
        thinking_content="[Low similarity - fallback response]",
    )


def build_thinking_payload_impl(
    *,
    native_thinking: Optional[str],
    tracer: Any,
    is_no_doc_retrieval_text_fn: Callable[[object], bool],
    build_retrieval_surface_text_fn: Callable[[int], str],
    normalize_visible_text_fn: Callable[[object], str],
) -> tuple[Optional[str], Optional[str]]:
    """Build thinking + thinking_content without bloating CorrectiveRAG.process()."""
    thinking = native_thinking or None
    thinking_content = tracer.build_thinking_summary()

    if thinking:
        logger.info("[CRAG] Using native Gemini thinking: %d chars", len(thinking))

    if thinking_content:
        if is_no_doc_retrieval_text_fn(thinking_content):
            thinking_content = build_retrieval_surface_text_fn(0)
        else:
            thinking_content = normalize_visible_text_fn(thinking_content)
        logger.info(
            "[CRAG] Built structured thinking summary: %d chars",
            len(thinking_content),
        )

    if not thinking:
        logger.info(
            "[CRAG] No native thinking available - thinking_content kept separate for metadata only"
        )

    return thinking, thinking_content


async def collect_evidence_images_impl(
    *,
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect small evidence image previews for the final response."""
    if not sources:
        return []

    try:
        from app.engine.agentic_rag.document_retriever import DocumentRetriever

        node_ids = [source.get("node_id", "") for source in sources if source.get("node_id")]
        if not node_ids:
            return []

        images = await DocumentRetriever.collect_evidence_images(node_ids, max_images=3)
        return [
            {
                "url": image.url,
                "page_number": image.page_number,
                "document_id": image.document_id,
            }
            for image in images
        ]
    except Exception as exc:
        logger.warning("[CRAG] Evidence image collection failed: %s", exc)
        return []


def build_final_result_impl(
    *,
    result_cls: type,
    answer: str,
    sources: list[dict[str, Any]],
    analysis: Any,
    grading_result: Any,
    verification_result: Any,
    was_rewritten: bool,
    rewritten_query: Optional[str],
    iterations: int,
    confidence: float,
    reasoning_trace: Any,
    thinking_content: Optional[str],
    thinking: Optional[str],
    evidence_images: list[dict[str, Any]],
) -> Any:
    """Create the public CorrectiveRAGResult payload."""
    safe_sources = [] if answer_declines_rag_sources_impl(answer) else sources
    safe_evidence_images = [] if not safe_sources else evidence_images
    return result_cls(
        answer=answer,
        sources=safe_sources,
        query_analysis=analysis,
        grading_result=grading_result,
        verification_result=verification_result,
        was_rewritten=was_rewritten,
        rewritten_query=rewritten_query,
        iterations=iterations,
        confidence=confidence,
        reasoning_trace=reasoning_trace,
        thinking_content=thinking_content,
        thinking=thinking,
        evidence_images=safe_evidence_images,
    )


async def store_cache_response_impl(
    *,
    cache_enabled: bool,
    cache_manager: Any,
    confidence: float,
    query_embedding: Optional[list[float]],
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    thinking: Optional[str],
    iterations: int,
    was_rewritten: bool,
    context: dict[str, Any],
) -> None:
    """Persist a high-confidence CRAG result into semantic cache."""
    if not cache_enabled or not cache_manager or confidence < 70:
        return

    try:
        safe_sources = [] if answer_declines_rag_sources_impl(answer) else sources
        if query_embedding is None:
            query_embedding = await get_query_embedding_impl(query)
        if not query_embedding:
            logger.warning("[CRAG] Skipping cache store due to missing query embedding")
            return

        doc_ids = [source.get("document_id", "") for source in safe_sources if source.get("document_id")]
        cache_data = {
            "answer": answer,
            "sources": safe_sources,
            "confidence": confidence,
            "thinking": thinking,
        }
        cache_org = context.get("organization_id") or ""
        cache_uid = context.get("user_id", "")
        await cache_manager.set(
            query=query,
            embedding=query_embedding,
            response=cache_data,
            document_ids=doc_ids,
            metadata={"iterations": iterations, "was_rewritten": was_rewritten},
            user_id=cache_uid,
            org_id=cache_org,
        )
        logger.info("[CRAG] Response cached (confidence=%.0f%%, docs=%d)", confidence, len(doc_ids))
    except Exception as exc:
        logger.warning("[CRAG] Failed to cache response: %s", exc)
