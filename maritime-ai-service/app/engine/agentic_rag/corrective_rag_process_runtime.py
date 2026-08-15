"""Runtime orchestration for the synchronous Corrective RAG pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.engine.agentic_rag.corrective_rag_runtime_support import (
    build_cache_hit_result_impl,
    build_final_result_impl,
    build_thinking_payload_impl,
    cache_hit_matches_runtime_scope_impl,
    collect_evidence_images_impl,
    get_query_embedding_impl,
    store_cache_response_impl,
)
from app.engine.agentic_rag.corrective_rag_surface import (
    build_retrieval_surface_text,
    is_likely_english,
    is_no_doc_retrieval_text,
    normalize_visible_text,
    translate_to_vietnamese,
)
from app.engine.agentic_rag.query_analyzer import QueryComplexity

logger = logging.getLogger(__name__)


def _emit_crag_progress(content: str, step: str = "crag") -> None:
    """Best-effort status event so the user sees pipeline progress."""
    try:
        from app.engine.tools.runtime_context import emit_tool_bus_event

        emit_tool_bus_event({
            "type": "status",
            "content": content,
            "step": step,
            "details": {"subtype": "progress", "visibility": "status_only"},
        })
    except Exception:
        pass


async def process_impl(
    rag,
    query: str,
    context: Optional[Dict[str, Any]],
    *,
    settings_obj,
    result_cls,
    get_reasoning_tracer_fn,
    step_names_cls,
    _prefetch_docs: Optional[list] = None,
):
    """Run the synchronous Corrective RAG pipeline for ``CorrectiveRAG.process``."""
    context = context or {}

    tracer = get_reasoning_tracer_fn()

    query_embedding = None
    if rag._cache_enabled and rag._cache:
        try:
            query_embedding = await get_query_embedding_impl(query)
            if query_embedding:
                _uid = context.get("user_id", "")
                _org = context.get("organization_id") or ""
                cache_result = await rag._cache.get(
                    query,
                    query_embedding,
                    user_id=_uid,
                    org_id=_org,
                )

                if cache_result.hit:
                    scope_matches, scope_details = cache_hit_matches_runtime_scope_impl(
                        cache_result=cache_result,
                        context=context,
                    )
                    if not scope_matches:
                        logger.info(
                            "[CRAG] Cache hit ignored due to runtime model mismatch "
                            "(requested_provider=%s requested_model=%s cached_provider=%s cached_model=%s)",
                            scope_details["requested_provider"],
                            scope_details["requested_model"],
                            scope_details["cached_provider"] or "<unscoped>",
                            scope_details["cached_model"] or "<unscoped>",
                        )
                    else:
                        logger.info(
                            "[CRAG] CACHE HIT! similarity=%.3f lookup_time=%.1fms",
                            cache_result.similarity,
                            cache_result.lookup_time_ms,
                        )
                        return await build_cache_hit_result_impl(
                            cache_result=cache_result,
                            query=query,
                            context=context,
                            result_cls=result_cls,
                        )

                logger.debug("[CRAG] Cache MISS, proceeding with full pipeline")
            else:
                logger.warning("[CRAG] Cache lookup skipped due to missing query embedding")
        except Exception as exc:
            logger.warning(
                "[CRAG] Cache lookup failed: %s, proceeding without cache",
                exc,
            )
            query_embedding = None

    tracer.start_step(
        step_names_cls.QUERY_ANALYSIS,
        "Phân tích độ phức tạp câu hỏi",
    )
    _emit_crag_progress("Đang phân tích câu hỏi...", "query_analysis")
    logger.info("[CRAG] Step 1: Analyzing query: '%s...'", query[:50])
    analysis = await rag._analyzer.analyze(query)
    logger.info("[CRAG] Analysis: %s", analysis)
    tracer.end_step(
        result=(
            f"Độ phức tạp: {analysis.complexity.value}, "
            f"Domain: {analysis.is_domain_related}"
        ),
        confidence=analysis.confidence,
        details={
            "complexity": analysis.complexity.value,
            "is_domain": analysis.is_domain_related,
            "topics": analysis.detected_topics,
        },
    )

    adaptive_decision = None
    if settings_obj.enable_adaptive_rag:
        try:
            from app.engine.agentic_rag.adaptive_rag import route_query

            adaptive_decision = route_query(
                query=query,
                complexity=analysis.complexity.value,
                is_domain_related=analysis.is_domain_related,
                detected_topics=analysis.detected_topics,
                requires_multi_step=analysis.requires_multi_step,
            )
            logger.info(
                "[CRAG] Adaptive RAG: strategy=%s, reason=%s",
                adaptive_decision.strategy.value,
                adaptive_decision.reason,
            )
        except Exception as exc:
            logger.warning("[CRAG] Adaptive RAG routing failed: %s", exc)

    hyde_embedding = None
    if settings_obj.enable_hyde:
        use_hyde = True
        if adaptive_decision:
            from app.engine.agentic_rag.adaptive_rag import should_use_hyde

            use_hyde = should_use_hyde(adaptive_decision)
        if use_hyde:
            try:
                from app.engine.agentic_rag.hyde_generator import (
                    blend_embeddings,
                    generate_hyde_embedding,
                )

                hyde_result = await generate_hyde_embedding(query, query_embedding)
                if hyde_result.used and hyde_result.hyde_embedding:
                    hyde_embedding = blend_embeddings(
                        query_embedding or [],
                        hyde_result.hyde_embedding,
                        alpha=settings_obj.hyde_blend_alpha,
                    )
                    logger.info(
                        "[CRAG] HyDE: blended embedding (%.0fms gen + %.0fms emb)",
                        hyde_result.generation_time_ms,
                        hyde_result.embedding_time_ms,
                    )
            except Exception as exc:
                logger.warning("[CRAG] HyDE generation failed: %s", exc)

    current_query = query
    documents = []
    grading_result = None
    was_rewritten = False
    rewritten_query = None
    iterations = 0

    for iteration in range(rag._max_iterations):
        iterations = iteration + 1

        tracer.start_step(
            step_names_cls.RETRIEVAL,
            f"Tìm kiếm tài liệu (lần {iterations})",
        )
        _emit_crag_progress(
            f"Tìm kiếm tài liệu liên quan (lần {iterations})...",
            "retrieval",
        )
        logger.info(
            "[CRAG] Step 2.%d: Retrieving for '%s...'",
            iterations,
            current_query[:50],
        )

        embedding_override = (
            hyde_embedding
            if iteration == 0 and hyde_embedding is not None
            else None
        )
        documents = await rag._retrieve(
            current_query,
            context,
            query_embedding_override=embedding_override,
            _prefetch_docs=_prefetch_docs if iteration == 0 else None,
        )

        if not documents:
            logger.warning("[CRAG] No documents retrieved")
            tracer.end_step(result="Không tìm thấy tài liệu", confidence=0.0)

            if iteration < rag._max_iterations - 1:
                tracer.start_step(
                    step_names_cls.QUERY_REWRITE,
                    "Viết lại query do không có kết quả",
                )
                current_query = await rag._rewriter.rewrite(
                    current_query,
                    "No documents found",
                )
                rewritten_query = current_query
                was_rewritten = True
                tracer.end_step(
                    result=f"Query mới: {current_query[:50]}...",
                    confidence=0.7,
                )
                tracer.record_correction("Không tìm thấy tài liệu")
                continue
            break

        tracer.end_step(
            result=f"Tìm thấy {len(documents)} tài liệu",
            confidence=0.8,
            details={"doc_count": len(documents)},
        )

        tracer.start_step(
            step_names_cls.GRADING,
            "Đánh giá độ liên quan của tài liệu",
        )
        _emit_crag_progress(
            f"Đánh giá {len(documents)} tài liệu...",
            "grading",
        )
        logger.info(
            "[CRAG] Step 3.%d: Grading %d documents",
            iterations,
            len(documents),
        )

        if query_embedding is None:
            query_embedding = await get_query_embedding_impl(current_query)

        grading_result = await rag._grader.grade_documents(
            current_query,
            documents,
            query_embedding=query_embedding,
        )

        normalized_confidence = grading_result.avg_score / 10.0

        if grading_result.avg_score >= rag._grade_threshold:
            logger.info(
                "[CRAG] Grade passed: %.1f/10 (confidence=%.2f >= %.2f)",
                grading_result.avg_score,
                normalized_confidence,
                settings_obj.rag_confidence_high,
            )
            tracer.end_step(
                result=f"Điểm: {grading_result.avg_score:.1f}/10 - ĐẠT",
                confidence=normalized_confidence,
                details={
                    "score": grading_result.avg_score,
                    "passed": True,
                    "confidence": normalized_confidence,
                },
            )
            break

        if (
            settings_obj.rag_early_exit_on_high_confidence
            and normalized_confidence >= settings_obj.rag_confidence_medium
        ):
            logger.info(
                "[CRAG] MEDIUM confidence (%.2f) - early exit enabled, proceeding to generation",
                normalized_confidence,
            )
            tracer.end_step(
                result=(
                    f"Điểm: {grading_result.avg_score:.1f}/10 - MEDIUM "
                    "(early exit)"
                ),
                confidence=normalized_confidence,
                details={
                    "score": grading_result.avg_score,
                    "passed": False,
                    "early_exit": True,
                },
            )
            break

        tracer.end_step(
            result=f"Điểm: {grading_result.avg_score:.1f}/10 - Cần cải thiện",
            confidence=normalized_confidence,
            details={"score": grading_result.avg_score, "passed": False},
        )

        if grading_result.relevant_count >= 1:
            logger.info(
                "[CRAG] SOTA: Found %d relevant docs, skipping rewrite (trust retriever pattern)",
                grading_result.relevant_count,
            )
            break

        if iteration < rag._max_iterations - 1:
            tracer.start_step(
                step_names_cls.QUERY_REWRITE,
                "Viết lại query để cải thiện kết quả",
            )
            _emit_crag_progress("Viết lại câu hỏi để tìm chính xác hơn...", "rewrite")
            logger.info(
                "[CRAG] Step 4.%d: Rewriting query (score=%.1f, 0 relevant docs)",
                iterations,
                grading_result.avg_score,
            )

            if analysis.complexity == QueryComplexity.COMPLEX:
                sub_queries = await rag._rewriter.decompose(current_query)
                if len(sub_queries) > 1:
                    current_query = sub_queries[0]
            else:
                current_query = await rag._rewriter.rewrite(
                    current_query,
                    grading_result.feedback,
                )

            rewritten_query = current_query
            was_rewritten = True
            tracer.end_step(
                result=f"Query mới: {current_query[:50]}...",
                confidence=0.8,
            )
            tracer.record_correction(
                "Không tìm thấy doc liên quan "
                f"(score={grading_result.avg_score:.1f}/10)"
            )

    if settings_obj.enable_visual_rag and documents:
        try:
            from app.engine.agentic_rag.visual_rag import (
                enrich_documents_with_visual_context,
            )

            visual_result = await enrich_documents_with_visual_context(
                documents=documents,
                query=query,
                max_images=settings_obj.visual_rag_max_images,
            )
            if visual_result.total_images_analyzed > 0:
                documents = visual_result.enriched_documents
                logger.info(
                    "[CRAG] Visual RAG: enriched %d documents with image analysis",
                    visual_result.total_images_analyzed,
                )
        except Exception as exc:
            logger.warning(
                "[CRAG] Visual RAG enrichment failed, continuing without: %s",
                exc,
            )

    graph_entity_context = ""
    if settings_obj.enable_graph_rag and documents:
        try:
            from app.engine.agentic_rag.graph_rag_retriever import (
                enrich_with_graph_context,
            )

            graph_result = await enrich_with_graph_context(
                documents=documents,
                query=query,
            )
            if graph_result.entity_context_text:
                graph_entity_context = graph_result.entity_context_text
                logger.info(
                    "[CRAG] Graph RAG: %d entities, mode=%s (%.0fms)",
                    len(graph_result.entities),
                    graph_result.mode,
                    graph_result.total_time_ms,
                )
            if graph_result.additional_docs:
                documents.extend(graph_result.additional_docs)
                logger.info(
                    "[CRAG] Graph RAG: added %d additional documents",
                    len(graph_result.additional_docs),
                )
        except Exception as exc:
            logger.warning(
                "[CRAG] Graph RAG enrichment failed, continuing without: %s",
                exc,
            )

    if graph_entity_context:
        context["entity_context"] = graph_entity_context

    _emit_crag_progress("Tạo câu trả lời từ nguồn tài liệu...", "generation")
    tracer.start_step(step_names_cls.GENERATION, "Tạo câu trả lời từ context")
    logger.info("[CRAG] Step 5: Generating answer")
    answer, sources, native_thinking = await rag._generate(
        query,
        documents,
        context,
    )

    if answer and is_likely_english(answer):
        logger.info("[CRAG] Answer is in English, translating to Vietnamese...")
        answer = await translate_to_vietnamese(answer)

    tracer.end_step(
        result=f"Tạo câu trả lời dựa trên {len(sources)} nguồn",
        confidence=0.85,
        details={"source_count": len(sources)},
    )

    reflection_result = None
    if settings_obj.rag_enable_reflection:
        from app.engine.agentic_rag.reflection_parser import (
            get_reflection_parser,
        )

        reflection_parser = get_reflection_parser()
        reflection_result = reflection_parser.parse(answer)

        logger.info(
            "[CRAG] Reflection: supported=%s, useful=%s, needs_correction=%s, confidence=%s",
            reflection_result.is_supported,
            reflection_result.is_useful,
            reflection_result.needs_correction,
            reflection_result.confidence.value,
        )

        if (
            reflection_result.needs_correction
            and iterations < rag._max_iterations
        ):
            logger.warning(
                "[CRAG] Reflection suggests correction: %s",
                reflection_result.correction_reason,
            )
            tracer.record_correction(
                f"Reflection: {reflection_result.correction_reason}"
            )

    verification_result = None
    grading_confidence = (
        grading_result.avg_score / 10.0 if grading_result else 0.5
    )

    reflection_is_high = bool(
        reflection_result
        and reflection_result.confidence.value == "high"
        and reflection_result.is_supported
        and not reflection_result.needs_correction
    )

    should_verify = (
        rag._enable_verification
        and analysis.requires_verification
        and len(sources) > 0
        and grading_confidence < settings_obj.rag_confidence_medium
        and not reflection_is_high
    )

    if should_verify:
        _emit_crag_progress("Kiểm tra độ chính xác câu trả lời...", "verification")
        tracer.start_step(
            step_names_cls.VERIFICATION,
            "Kiểm tra độ chính xác và hallucination",
        )
        logger.info(
            "[CRAG] Step 6: Verifying answer (low confidence=%.2f)",
            grading_confidence,
        )
        verification_result = await rag._verifier.verify(answer, sources)

        if verification_result.warning:
            answer = f"\u26a0\ufe0f {verification_result.warning}\n\n{answer}"
            tracer.end_step(
                result=f"Cảnh báo: {verification_result.warning}",
                confidence=(
                    verification_result.confidence / 100
                    if verification_result.confidence
                    else 0.5
                ),
            )
        else:
            tracer.end_step(
                result="Đã xác minh - Không phát hiện vấn đề",
                confidence=(
                    verification_result.confidence / 100
                    if verification_result.confidence
                    else 0.9
                ),
            )
    elif reflection_is_high:
        logger.info(
            "[CRAG] Skipping verification (reflection.confidence=HIGH, supported=True)"
        )
    elif rag._enable_verification and len(sources) == 0:
        logger.info(
            "[CRAG] Skipping verification (0 sources - fallback answer from LLM general knowledge)"
        )
    elif (
        rag._enable_verification
        and grading_confidence >= settings_obj.rag_confidence_medium
    ):
        logger.info(
            "[CRAG] Skipping verification (confidence=%.2f >= MEDIUM)",
            grading_confidence,
        )

    confidence = rag._calculate_confidence(
        analysis,
        grading_result,
        verification_result,
    )
    reasoning_trace = tracer.build_trace(final_confidence=confidence / 100)

    thinking, thinking_content = build_thinking_payload_impl(
        native_thinking=native_thinking,
        tracer=tracer,
        is_no_doc_retrieval_text_fn=is_no_doc_retrieval_text,
        build_retrieval_surface_text_fn=build_retrieval_surface_text,
        normalize_visible_text_fn=normalize_visible_text,
    )

    logger.info(
        "[CRAG] Complete: iterations=%d, confidence=%.0f%%",
        iterations,
        confidence,
    )

    await store_cache_response_impl(
        cache_enabled=rag._cache_enabled,
        cache_manager=rag._cache,
        confidence=confidence,
        query_embedding=query_embedding,
        query=query,
        answer=answer,
        sources=sources,
        thinking=thinking,
        iterations=iterations,
        was_rewritten=was_rewritten,
        context=context,
    )

    evidence_images = await collect_evidence_images_impl(sources=sources)

    return build_final_result_impl(
        result_cls=result_cls,
        answer=answer,
        sources=sources,
        analysis=analysis,
        grading_result=grading_result,
        verification_result=verification_result,
        was_rewritten=was_rewritten,
        rewritten_query=rewritten_query,
        iterations=iterations,
        confidence=confidence,
        reasoning_trace=reasoning_trace,
        thinking_content=thinking_content,
        thinking=thinking,
        evidence_images=evidence_images,
    )
