"""
Streaming runtime helpers for CorrectiveRAG.

Keeps the main CorrectiveRAG class focused on orchestration and ownership while
the large streaming implementation lives in a dedicated module.
"""

import asyncio
import logging
import re
import time
import unicodedata
from typing import Any, AsyncGenerator, Dict, Optional

from app.engine.agentic_rag.runtime_llm_socket import (
    ainvoke_agentic_rag_llm,
    make_agentic_rag_messages,
    resolve_agentic_rag_llm,
)
from app.engine.agentic_rag.corrective_rag_runtime_support import (
    answer_declines_rag_sources_impl,
)
from app.engine.llm_factory import ThinkingTier

logger = logging.getLogger(__name__)


def _normalize_guard_text(text: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _looks_like_colreg_rule5_query(query: str) -> bool:
    normalized = _normalize_guard_text(query)
    return (
        ("colreg" in normalized or "rule 5" in normalized or "quy tac 5" in normalized)
        and any(marker in normalized for marker in ("lookout", "look-out", "canh gioi", "truc ca", "rule 5", "quy tac 5"))
    )


def _build_rule5_direct_fallback(query: str) -> str:
    if not _looks_like_colreg_rule5_query(query):
        return ""
    return (
        "Theo COLREG Rule 5, người trực ca/tàu phải duy trì cảnh giới liên tục và đúng mức "
        "bằng mắt, tai, đồng thời dùng mọi phương tiện sẵn có phù hợp với hoàn cảnh để đánh giá đầy đủ "
        "tình huống và nguy cơ va chạm.\n\n"
        "Nguồn: COLREG 1972, Rule 5 (Look-out)."
    )


def _looks_like_colreg_rule15_query(query: str) -> bool:
    normalized = _normalize_guard_text(query)
    return (
        ("colreg" in normalized or "colregs" in normalized)
        and ("rule 15" in normalized or "quy tac 15" in normalized)
    )


def _build_rule15_direct_fallback(query: str) -> str:
    if not _looks_like_colreg_rule15_query(query):
        return ""
    return (
        "Mình chưa gắn citation RAG nội bộ cho lượt này, nên mình nói rõ đây là phần tóm tắt theo COLREG 1972 Rule 15.\n\n"
        "- Bối cảnh: Rule 15 áp dụng khi hai tàu máy đi cắt hướng nhau và có nguy cơ va chạm.\n"
        "- Tàu nhường đường: tàu nào nhìn thấy tàu kia ở phía mạn phải của mình thì tàu đó là give-way vessel.\n"
        "- Hành động nên làm: đổi hướng hoặc tốc độ sớm, đủ rõ; nếu hoàn cảnh cho phép thì tránh cắt qua trước mũi tàu kia.\n"
        "- Rủi ro hiểu sai: đừng nhầm với Rule 13 (tàu vượt) hoặc Rule 14 (đối hướng); điểm neo của Rule 15 là tình huống cắt hướng và mốc mạn phải."
    )


def _filter_domain_mismatched_documents(query: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop obviously wrong KB hits for high-precision regulation queries."""
    if not documents or not _looks_like_colreg_rule5_query(query):
        return documents

    required_markers = (
        "colreg",
        "rule 5",
        "quy tac 5",
        "quy tắc 5",
        "lookout",
        "look-out",
        "canh gioi",
        "cảnh giới",
    )
    filtered = []
    for doc in documents:
        haystack = _normalize_guard_text(
            " ".join(
                str(doc.get(key, "") or "")
                for key in ("title", "content", "source", "document_id")
            )
        )
        if any(_normalize_guard_text(marker) in haystack for marker in required_markers):
            filtered.append(doc)
    return filtered


def _resolve_crag_light_llm(component: str):
    from app.engine.llm_pool import get_llm_light

    return resolve_agentic_rag_llm(
        tier=ThinkingTier.LIGHT,
        fallback_factory=get_llm_light,
        component=component,
    )


def _build_soul_system_prompt(
    personality: str,
    name_hint: str,
    *,
    context_type: str = "fallback",
) -> str:
    """Build a soul-aware system prompt for fallback/web generation.

    Args:
        personality: Wiii personality summary from prompt loader.
        name_hint: "User tên X. " or "".
        context_type: "web" for web search context, "fallback" for intrinsic knowledge.
    """
    base = f"Bạn là Wiii. {personality} {name_hint}"

    if context_type == "web":
        return (
            base
            + "Dưới đây là kết quả tìm kiếm web liên quan đến câu hỏi. "
            "Hãy tổng hợp thông tin từ kết quả tìm kiếm để trả lời câu hỏi "
            "một cách đầy đủ, chính xác, dễ hiểu. "
            "Nếu kết quả tìm kiếm không đủ để trả lời hoàn toàn, hãy bổ sung "
            "bằng kiến thức chung nhưng ghi chú rõ phần nào là từ web, phần nào "
            "là kiến thức chung. "
            "Trả lời bằng tiếng Việt, đi thẳng vào nội dung. "
            "Không xin lỗi về việc thiếu tài liệu nội bộ."
        )
    # Fallback: intrinsic knowledge
    return (
        base
        + "Kho dữ liệu nội bộ không có tài liệu phù hợp. "
        "Hãy dùng kiến thức chung để trả lời câu hỏi một cách hữu ích, chính xác. "
        "Nếu không chắc, hãy nói rõ phần nào là ước lượng. "
        "Trả lời bằng tiếng Việt, tự nhiên, thân thiện. "
        "Không nói 'mình không tìm thấy tài liệu' hay xin lỗi về việc thiếu nguồn nội bộ."
    )


async def _stream_llm_with_thinking(
    llm,
    messages: list,
    owner,
    query: str,
    context: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream LLM response — emits native LLM thinking + <thinking> tag extraction.

    GOLDEN RULE: thinking_delta = LLM native CoT or <thinking> tags only.
    If the LLM doesn't produce thinking blocks, no thinking_delta is emitted.
    Use `status` events for pipeline progress, never fake thinking.

    Falls back to ainvoke() if astream fails.
    """
    full_answer = ""
    _tag_state = {"inside_thinking": False, "pending": ""}
    stream_start = time.time()
    chunk_timeout = 60
    total_timeout = 240

    def _extract_tagged_thinking(text: str) -> tuple[str, str]:
        """Split <thinking> tags from streamed text. Returns (reasoning, visible)."""
        incoming = f"{_tag_state.get('pending', '')}{text or ''}"
        _tag_state["pending"] = ""
        if not incoming:
            return "", ""

        reasoning_parts: list[str] = []
        visible_parts: list[str] = []
        inside = bool(_tag_state.get("inside_thinking"))
        idx = 0

        while idx < len(incoming):
            if incoming[idx] == "<":
                close_idx = incoming.find(">", idx + 1)
                if close_idx < 0:
                    _tag_state["pending"] = incoming[idx:]
                    break
                tag = incoming[idx: close_idx + 1].strip().lower()
                if tag == "<thinking>":
                    inside = True
                elif tag == "</thinking>":
                    inside = False
                else:
                    target = reasoning_parts if inside else visible_parts
                    target.append(incoming[idx: close_idx + 1])
                idx = close_idx + 1
                continue

            next_tag = incoming.find("<", idx)
            if next_tag < 0:
                target = reasoning_parts if inside else visible_parts
                target.append(incoming[idx:])
                break

            target = reasoning_parts if inside else visible_parts
            target.append(incoming[idx:next_tag])
            idx = next_tag

        _tag_state["inside_thinking"] = inside
        return "".join(reasoning_parts), "".join(visible_parts)

    if getattr(llm, "_wiii_native_route", False):
        try:
            from app.engine.multi_agent.openai_stream_runtime import (
                _create_openai_compatible_stream_client_impl,
                _extract_openai_delta_text_impl,
                _resolve_openai_stream_model_name_impl,
            )
            from app.engine.native_chat_runtime import message_to_openai_payload

            provider_name = str(getattr(llm, "_wiii_provider_name", "") or "").strip().lower()
            tier_key = str(getattr(llm, "_wiii_tier_key", "") or "light").strip().lower()
            client = _create_openai_compatible_stream_client_impl(provider_name)
            model_name = _resolve_openai_stream_model_name_impl(llm, provider_name, tier_key)
            if client is not None and model_name:
                request_kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": [message_to_openai_payload(message) for message in messages],
                    "stream": True,
                }
                temperature = getattr(llm, "temperature", None)
                if temperature is not None:
                    request_kwargs["temperature"] = temperature

                stream = await client.chat.completions.create(**request_kwargs)
                stream_iter = stream.__aiter__()
                while True:
                    if time.time() - stream_start > total_timeout:
                        logger.warning("[CRAG-V3] Native LLM stream total timeout")
                        break
                    try:
                        chunk = await asyncio.wait_for(
                            stream_iter.__anext__(),
                            timeout=chunk_timeout,
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning("[CRAG-V3] Native LLM stream chunk timeout")
                        break
                    for choice in getattr(chunk, "choices", []) or []:
                        delta = getattr(choice, "delta", None)
                        if delta is None:
                            continue
                        reasoning, content = _extract_openai_delta_text_impl(delta)
                        if content:
                            tagged_reasoning, visible = _extract_tagged_thinking(content)
                            if tagged_reasoning:
                                reasoning = f"{reasoning}{tagged_reasoning}"
                            content = visible
                        if reasoning:
                            yield {"type": "thinking_delta", "content": reasoning}
                        if content:
                            full_answer += content
                            yield {"type": "answer", "content": content}
                if full_answer:
                    return
        except Exception as native_stream_exc:
            logger.warning(
                "[CRAG-V3] Native LLM stream failed, falling back to invoke: %s",
                native_stream_exc,
            )

    try:
        aiter = llm.astream(messages).__aiter__()
        while True:
            if time.time() - stream_start > total_timeout:
                logger.warning("[CRAG-V3] LLM astream total timeout")
                if not full_answer:
                    raise TimeoutError("CRAG LLM stream timed out before first answer chunk")
                break
            try:
                chunk = await asyncio.wait_for(
                    aiter.__anext__(),
                    timeout=chunk_timeout,
                )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                logger.warning("[CRAG-V3] LLM astream chunk timeout")
                if not full_answer:
                    raise TimeoutError("CRAG LLM stream chunk timed out before first answer chunk")
                break
            content = chunk.content if hasattr(chunk, "content") else str(chunk)

            # Handle list content (Gemini native format)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type", "")
                        if block_type == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                yield {"type": "thinking_delta", "content": thinking_text}
                        elif block_type == "text":
                            text = block.get("text", "")
                            if text:
                                full_answer += text
                                yield {"type": "answer", "content": text}
                    elif isinstance(block, str) and block:
                        full_answer += block
                        yield {"type": "answer", "content": block}
                continue

            # Handle string content — extract <thinking> tags
            if isinstance(content, str) and content:
                reasoning, visible = _extract_tagged_thinking(content)
                if reasoning:
                    yield {"type": "thinking_delta", "content": reasoning}
                if visible:
                    full_answer += visible
                    yield {"type": "answer", "content": visible}

    except Exception as stream_exc:
        logger.warning("[CRAG-V3] LLM astream failed, falling back to ainvoke: %s", stream_exc)
        try:
            from app.services.output_processor import extract_thinking_from_response
            response = await ainvoke_agentic_rag_llm(
                llm=llm,
                messages=messages,
                tier=ThinkingTier.LIGHT,
                component="CorrectiveRAGStreamInvokeFallback",
            )
            text, thinking = extract_thinking_from_response(response.content)
            if thinking:
                yield {"type": "thinking_delta", "content": thinking}
            if text:
                full_answer = text.strip()
                yield {"type": "answer", "content": full_answer}
        except Exception as invoke_exc:
            logger.error("[CRAG-V3] LLM ainvoke also failed: %s", invoke_exc)

    # If nothing came out, try the owner's fallback
    if not full_answer:
        try:
            fallback_text, fallback_thinking = await owner._generate_fallback(query, context)
            if fallback_text:
                full_answer = fallback_text
                if fallback_thinking:
                    yield {"type": "thinking", "content": fallback_thinking}
                yield {"type": "answer", "content": full_answer}
        except Exception:
            pass


async def _generate_from_web_context(
    owner,
    query: str,
    web_context: str,
    context: dict[str, Any],
) -> str:
    """Generate an answer from web search context using LLM (non-streaming).

    Kept for backward compatibility with callers that need a single string.
    """
    try:
        from app.services.output_processor import extract_thinking_from_response
        from app.prompts.prompt_loader import get_prompt_loader

        llm = _resolve_crag_light_llm("CorrectiveRAGWebContext")
        if not llm:
            fallback_text, _ = await owner._generate_fallback(query, context)
            return fallback_text

        loader = get_prompt_loader()
        identity = loader.get_identity().get("identity", {})
        personality = identity.get("personality", {}).get("summary", "")
        user_name = context.get("user_name", "")
        name_hint = f"User tên {user_name}. " if user_name else ""

        system_prompt = _build_soul_system_prompt(
            personality, name_hint, context_type="web"
        )
        messages = make_agentic_rag_messages(
            system=system_prompt,
            user=f"{web_context}\n\nCâu hỏi: {query}",
        )
        response = await ainvoke_agentic_rag_llm(
            llm=llm,
            messages=messages,
            tier=ThinkingTier.LIGHT,
            component="CorrectiveRAGWebContext",
        )
        text, _ = extract_thinking_from_response(response.content)
        return text.strip() if text else ""

    except Exception as exc:
        logger.warning("[CRAG-V3] Web context generation failed: %s", exc)
        fallback_text, _ = await owner._generate_fallback(query, context)
        return fallback_text


async def process_streaming_impl(
    owner,
    query: str,
    context: Optional[Dict[str, Any]],
    *,
    result_cls,
    get_reasoning_tracer_fn,
    settings_obj,
    step_names_cls,
    build_retrieval_surface_text_fn,
    build_house_fallback_reply_fn,
    is_no_doc_retrieval_text_fn,
    normalize_visible_text_fn,
    max_content_snippet_length: int,
    _prefetch_docs: Optional[list[dict[str, Any]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    SOTA 2025: Full CRAG pipeline with progressive SSE events.

    Yields SSE events at each pipeline stage:
    - status: Processing stage updates (shown as typing indicator)
    - thinking: AI reasoning steps (shown in collapsible section)  
    - answer: Response tokens (streamed real-time via LLM.astream())
    - sources: Citation list with image_url for PDF highlighting
    - metadata: reasoning_trace, confidence, timing
    - done: Stream complete

    Pattern:
    - OpenAI Responses API (event types: reasoning, output, completion)
    - Claude Interleaved Thinking (thinking blocks between steps)
    - LangChain LCEL RunnableParallel (parallel execution)

    **Feature: p3-v3-full-crag-streaming**
    """
    # Note: get_reasoning_tracer and StepNames already imported at module level (line 37-39)

    context = context or {}
    start_time = time.time()
    tracer = get_reasoning_tracer_fn()

    early_rule5_answer = _build_rule5_direct_fallback(query)
    if early_rule5_answer:
        sources_data = [
            {
                "title": "COLREG 1972 - Rule 5 (Look-out)",
                "content": (
                    "Every vessel shall at all times maintain a proper look-out by sight and hearing "
                    "as well as by all available means appropriate in the prevailing circumstances and conditions."
                ),
                "source": "COLREG 1972",
                "page_number": None,
                "image_url": None,
                "document_id": "colreg-1972-rule-5",
                "node_id": "colreg-rule-5-lookout",
                "bounding_boxes": None,
                "content_type": "regulation",
            }
        ]
        yield {
            "type": "status",
            "content": "Nhận diện trực tiếp COLREG Rule 5, trả lời bằng nguồn chuẩn.",
            "step": "retrieval",
        }
        yield {"type": "sources", "content": sources_data}
        yield {"type": "answer", "content": early_rule5_answer}
        yield {
            "type": "result",
            "data": result_cls(
                answer=early_rule5_answer,
                sources=sources_data,
                query_analysis=None,
                confidence=82.0,
                was_rewritten=False,
                rewritten_query=None,
                evidence_images=[],
            ),
        }
        yield {"type": "done", "content": ""}
        return

    early_rule15_answer = _build_rule15_direct_fallback(query)
    if early_rule15_answer:
        yield {
            "type": "status",
            "content": "Nhận diện trực tiếp COLREG Rule 15, trả lời không gắn citation RAG nội bộ.",
            "step": "retrieval",
        }
        yield {"type": "answer", "content": early_rule15_answer}
        yield {
            "type": "result",
            "data": result_cls(
                answer=early_rule15_answer,
                sources=[],
                query_analysis=None,
                confidence=78.0,
                was_rewritten=False,
                rewritten_query=None,
                evidence_images=[],
            ),
        }
        yield {"type": "done", "content": ""}
        return

    # NOTE: interval_thinking_fillers removed — synthetic thinking is forbidden.
    # Pipeline progress uses `status` events (honest system state), not fake thinking.

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 1: Query Understanding (emit events immediately)
    # ═══════════════════════════════════════════════════════════════════
    yield {"type": "status", "content": "Phân tích câu hỏi"}

    tracer.start_step(step_names_cls.QUERY_ANALYSIS, "Phân tích độ phức tạp câu hỏi")
    logger.info("[CRAG-V3] Phase 1: Analyzing query: '%s...'", query[:50])

    try:
        analysis = await owner._analyzer.analyze(query)
        tracer.end_step(
            result=f"Độ phức tạp: {analysis.complexity.value}, Domain: {analysis.is_domain_related}",
            confidence=analysis.confidence,
            details={"complexity": analysis.complexity.value, "is_domain": analysis.is_domain_related}
        )

        # Sprint 144: Rich analysis thinking — expert-level breakdown
        _analysis_parts = [f"Độ phức tạp: {analysis.complexity.value}"]
        if analysis.detected_topics:
            _analysis_parts.append(f"Chủ đề: {', '.join(analysis.detected_topics[:5])}")
        if analysis.is_domain_related:
            _analysis_parts.append("Thuộc lĩnh vực chuyên ngành → Sử dụng Knowledge Base")
        else:
            _analysis_parts.append("Ngoài chuyên ngành → Sử dụng kiến thức chung LLM")
        if hasattr(analysis, 'confidence') and analysis.confidence:
            _analysis_parts.append(f"Độ tin cậy phân tích: {analysis.confidence:.0%}")
        yield {
            "type": "thinking",
            "content": "\n".join(_analysis_parts),
            "step": "analysis",
            "details": {"topics": analysis.detected_topics, "is_domain": analysis.is_domain_related}
        }
    except Exception as e:
        logger.error("[CRAG-V3] Analysis failed: %s", e)
        yield {"type": "error", "content": "Lỗi phân tích câu hỏi. Vui lòng thử lại."}
        yield {"type": "done", "content": ""}  # Sprint 189b: ensure done
        return

    # Sprint 187: Adaptive RAG routing (streaming path)
    adaptive_decision_stream = None
    if settings_obj.enable_adaptive_rag:
        try:
            from app.engine.agentic_rag.adaptive_rag import route_query
            adaptive_decision_stream = route_query(
                query=query,
                complexity=analysis.complexity.value,
                is_domain_related=analysis.is_domain_related,
                detected_topics=analysis.detected_topics,
                requires_multi_step=analysis.requires_multi_step,
            )
            yield {
                "type": "thinking",
                "content": f"Chiến lược tìm kiếm: {adaptive_decision_stream.strategy.value} — {adaptive_decision_stream.reason}",
                "step": "adaptive_rag",
            }
        except Exception as e:
            logger.warning("[CRAG-V3] Adaptive RAG routing failed: %s", e)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 2: Retrieval (hybrid search + optional graphrag)
    # ═══════════════════════════════════════════════════════════════════
    yield {"type": "status", "content": "Tìm kiếm tài liệu"}

    # Honest status — no synthetic thinking
    yield {"type": "status", "content": "Đang tìm kiếm trong kho dữ liệu nội bộ..."}

    tracer.start_step(step_names_cls.RETRIEVAL, "Tìm kiếm tài liệu")
    logger.info("[CRAG-V3] Phase 2: Retrieving documents")

    try:
        raw_documents = await owner._retrieve(query, context, query_embedding_override=None, _prefetch_docs=_prefetch_docs)
        documents = _filter_domain_mismatched_documents(query, raw_documents)
        if len(documents) < len(raw_documents or []):
            logger.info(
                "[CRAG-V3] Domain guard dropped %d/%d mismatched documents for query '%s...'",
                len(raw_documents or []) - len(documents),
                len(raw_documents or []),
                query[:50],
            )
            yield {
                "type": "status",
                "content": "Bỏ qua vài nguồn không khớp chủ đề trước khi trả lời.",
                "step": "retrieval",
            }
        tracer.end_step(
            result=f"Tìm thấy {len(documents)} tài liệu",
            confidence=0.8 if documents else 0.3,
            details={"doc_count": len(documents)}
        )

        yield {
            "type": "thinking",
            "content": build_retrieval_surface_text_fn(len(documents)),
            "step": "retrieval",
            "details": {"doc_count": len(documents)}
        }

        # Sprint 179+: Visual RAG enrichment (streaming path)

        # ================================================================
        # Sprint 235: Vector Score Threshold Bypass (Zero-Score Bypass)
        # ================================================================
        # If ALL retrieved docs have very low RRF scores, skip the
        # expensive LLM grading step (~30s) and try CRAG corrective
        # web search before falling back to intrinsic knowledge.
        #
        # Priority chain: RAG → Web Search → LLM Intrinsic Knowledge
        # ================================================================
        _score_threshold = getattr(owner, "_retrieval_score_threshold", 0.30)
        _max_doc_score = max(
            (float(d.get("score", 0)) for d in documents), default=0.0
        )

        if _max_doc_score < _score_threshold and documents:
            logger.info(
                "[CRAG-V3] THRESHOLD BYPASS: max_score=%.4f < threshold=%.4f "
                "(query: '%s...', %d docs) — triggering corrective web search.",
                _max_doc_score,
                _score_threshold,
                query[:40],
                len(documents),
            )
            _web_corrective_text = "Điểm tài liệu thấp, đang tìm kiếm trên web..."
            yield {
                "type": "status",
                "content": _web_corrective_text,
                "step": "grading",
            }

            # ── CRAG Corrective Action: Web Search ──────────────
            _web_context = ""
            _web_sources = []
            try:
                from app.engine.agentic_rag.crag_web_corrective import (
                    corrective_web_search,
                )

                yield {"type": "status", "content": "Đang tìm kiếm trên web..."}
                web_result = await corrective_web_search(query)

                if web_result.success and web_result.formatted_context:
                    _web_context = web_result.formatted_context
                    _web_sources = [
                        {
                            "title": r.get("title", ""),
                            "content": r.get("body", ""),
                            "href": r.get("href", ""),
                            "source_type": "web_search",
                        }
                        for r in web_result.results
                    ]
                    yield {
                        "type": "thinking",
                        "content": (
                            f"Tìm thấy {web_result.source_count} kết quả web "
                            f"— dùng làm tài liệu tham khảo."
                        ),
                        "step": "web_corrective",
                    }
                    logger.info(
                        "[CRAG-V3] Web corrective: %d results for '%s'",
                        web_result.source_count,
                        query[:50],
                    )
                else:
                    logger.info(
                        "[CRAG-V3] Web corrective: no results, falling back to intrinsic knowledge"
                    )
            except Exception as web_exc:
                logger.warning(
                    "[CRAG-V3] Web corrective search failed: %s", web_exc
                )

            if _web_context:
                # Clear KB documents — we're answering from web context.
                documents = []
                grading_result = None
                passed = True  # Skip rewrite loop
                _threshold_bypassed = True

                # ── Web Search succeeded → stream from web context ──
                context = dict(context or {})
                context["_web_search_context"] = _web_context

                yield {"type": "status", "content": "Đang tạo câu trả lời từ kết quả web"}

                try:
                    from app.prompts.prompt_loader import get_prompt_loader

                    _llm = _resolve_crag_light_llm("CorrectiveRAGWebStream")
                    _loader = get_prompt_loader()
                    _identity = _loader.get_identity().get("identity", {})
                    _personality = _identity.get("personality", {}).get("summary", "")
                    _uname = context.get("user_name", "")
                    _nhint = f"User tên {_uname}. " if _uname else ""

                    _sys = _build_soul_system_prompt(_personality, _nhint, context_type="web")
                    _msgs = make_agentic_rag_messages(
                        system=_sys,
                        user=f"{_web_context}\n\nCâu hỏi: {query}",
                    )

                    web_answer = ""
                    if _llm:
                        async for evt in _stream_llm_with_thinking(_llm, _msgs, owner, query, context):
                            yield evt
                            if evt.get("type") == "answer" and evt.get("content"):
                                web_answer += evt["content"]
                    if not web_answer:
                        web_answer = await _generate_from_web_context(owner, query, _web_context, context)
                        if web_answer:
                            yield {"type": "answer", "content": web_answer}
                except Exception as _web_gen_exc:
                    logger.warning("[CRAG-V3] Streaming web gen failed: %s", _web_gen_exc)
                    web_answer = await _generate_from_web_context(owner, query, _web_context, context)
                    if web_answer:
                        yield {"type": "answer", "content": web_answer}

                yield {"type": "result", "data": result_cls(
                    answer=web_answer,
                    sources=_web_sources,
                    query_analysis=analysis,
                    confidence=65.0,
                    was_rewritten=False,
                    rewritten_query=None,
                    evidence_images=[],
                )}
                yield {"type": "done", "content": ""}
                return
            else:
                logger.info(
                    "[CRAG-V3] Web corrective unavailable or empty; continuing with %d retrieved KB docs",
                    len(documents),
                )
                yield {
                    "type": "status",
                    "content": "Tiếp tục dùng tài liệu nội bộ đã tìm thấy...",
                    "step": "retrieval",
                }
                _threshold_bypassed = False
        else:
            _threshold_bypassed = False

        if not _threshold_bypassed and documents:
            # Sprint 179+: Visual RAG enrichment (streaming path) — only when docs exist
            if settings_obj.enable_visual_rag and documents:
                try:
                    from app.engine.agentic_rag.visual_rag import enrich_documents_with_visual_context

                    yield {"type": "status", "content": "Phân tích hình ảnh tài liệu"}
                    visual_result = await enrich_documents_with_visual_context(
                        documents=documents,
                        query=query,
                        max_images=settings_obj.visual_rag_max_images,
                    )
                    if visual_result.total_images_analyzed > 0:
                        documents = visual_result.enriched_documents
                        yield {
                            "type": "thinking",
                            "content": f"Phân tích {visual_result.total_images_analyzed} hình ảnh từ tài liệu ({visual_result.total_time_ms:.0f}ms)",
                            "step": "visual_rag",
                        }
                        logger.info(
                            "[CRAG-V3] Visual RAG: enriched %d documents",
                            visual_result.total_images_analyzed,
                        )
                except Exception as e:
                    logger.warning("[CRAG-V3] Visual RAG failed: %s", e)

            # Sprint 182: Graph RAG enrichment (streaming path)
            graph_entity_context_streaming = ""
            if settings_obj.enable_graph_rag and documents:
                try:
                    from app.engine.agentic_rag.graph_rag_retriever import enrich_with_graph_context

                    yield {"type": "status", "content": "Phân tích đồ thị tri thức"}
                    graph_result = await enrich_with_graph_context(
                        documents=documents,
                        query=query,
                    )
                    if graph_result.entity_context_text:
                        graph_entity_context_streaming = graph_result.entity_context_text
                        yield {
                            "type": "thinking",
                            "content": f"Đồ thị tri thức: {len(graph_result.entities)} thực thể, chế độ {graph_result.mode} ({graph_result.total_time_ms:.0f}ms)",
                            "step": "graph_rag",
                        }
                    if graph_result.additional_docs:
                        documents.extend(graph_result.additional_docs)
                        logger.info(
                            "[CRAG-V3] Graph RAG: added %d additional documents",
                            len(graph_result.additional_docs),
                        )
                except Exception as e:
                    logger.warning("[CRAG-V3] Graph RAG failed: %s", e)

        if not documents:
            # Sprint 165 + Soul-streaming: LLM fallback with streaming thinking
            yield {"type": "status", "content": "Chuyển sang cách đáp trực tiếp...", "step": "llm_fallback"}

            fallback_answer = ""
            direct_domain_fallback = _build_rule5_direct_fallback(query)
            if direct_domain_fallback:
                fallback_answer = direct_domain_fallback
                yield {"type": "answer", "content": fallback_answer}
            try:
                from app.prompts.prompt_loader import get_prompt_loader

                _llm = _resolve_crag_light_llm("CorrectiveRAGNoDocsFallback")
                _loader = get_prompt_loader()
                _identity = _loader.get_identity().get("identity", {})
                _personality = _identity.get("personality", {}).get("summary", "")
                _uname = (context or {}).get("user_name", "")
                _nhint = f"User tên {_uname}. " if _uname else ""

                _sys = _build_soul_system_prompt(_personality, _nhint, context_type="fallback")
                _msgs = make_agentic_rag_messages(
                    system=_sys,
                    user=query,
                )

                if _llm and not fallback_answer:
                    async for evt in _stream_llm_with_thinking(_llm, _msgs, owner, query, context or {}):
                        yield evt
                        if evt.get("type") == "answer" and evt.get("content"):
                            fallback_answer += evt["content"]
            except Exception as _fb_exc:
                logger.warning("[CRAG-V3] Streaming fallback failed: %s", _fb_exc)

            if not fallback_answer:
                fb_text2, fb_thinking2 = await owner._generate_fallback(query, context or {})
                if not fb_text2:
                    fb_text2 = build_house_fallback_reply_fn()
                if fb_thinking2:
                    yield {"type": "thinking", "content": fb_thinking2}
                fallback_answer = fb_text2
                yield {"type": "answer", "content": fallback_answer}

            yield {"type": "result", "data": result_cls(
                answer=fallback_answer,
                sources=[],
                query_analysis=analysis,
                confidence=45.0,
                was_rewritten=False,
                rewritten_query=None,
                evidence_images=[],
            )}
            yield {"type": "done", "content": ""}
            return

    except Exception as e:
        logger.error("[CRAG-V3] Retrieval failed: %s", e)
        yield {"type": "error", "content": "Lỗi tìm kiếm tài liệu. Vui lòng thử lại."}
        yield {"type": "done", "content": ""}  # Sprint 189b: ensure done
        return

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 3: Grading (CRAG core - quality control!)
    # ═══════════════════════════════════════════════════════════════════
    yield {"type": "status", "content": "Đánh giá chất lượng tài liệu"}

    # Honest status — no synthetic thinking
    yield {"type": "status", "content": "Đang đánh giá độ phù hợp của tài liệu..."}

    tracer.start_step(step_names_cls.GRADING, "Đánh giá độ liên quan của tài liệu")
    logger.info("[CRAG-V3] Phase 3: Grading documents")

    try:
        # FIXED: Use grade_documents (not grade_batch)
        grading_result = await owner._grader.grade_documents(query, documents)
        passed = grading_result.avg_score >= owner._grade_threshold
        grading_confidence = grading_result.relevant_count / len(documents) if documents else 0.5

        tracer.end_step(
            result=f"Điểm: {grading_result.avg_score:.1f}/10 - {'ĐẠT' if passed else 'CHƯA ĐẠT'}",
            confidence=grading_confidence,
            details={
                "score": grading_result.avg_score,
                "passed": passed,
                "relevant_count": grading_result.relevant_count
            }
        )

        # Sprint 144: Rich grading thinking — expert quality assessment
        _grade_icon = "✅" if passed else "⚠️"
        _grade_parts = [
            f"{_grade_icon} Điểm chất lượng: {grading_result.avg_score:.1f}/10 — {'ĐẠT' if passed else 'CHƯA ĐẠT'}",
            f"Tài liệu liên quan: {grading_result.relevant_count}/{len(documents)}",
        ]
        _threshold = getattr(owner, '_grade_threshold', 6.0)
        if not passed:
            _grade_parts.append(f"Ngưỡng yêu cầu: {_threshold}/10 → Cần tinh chỉnh câu hỏi")
        else:
            _grade_parts.append(f"Vượt ngưỡng {_threshold}/10 → Đủ chất lượng để tạo câu trả lời")
        yield {
            "type": "thinking",
            "content": "\n".join(_grade_parts),
            "step": "grading",
            "details": {"score": grading_result.avg_score, "passed": passed}
        }

    except Exception as e:
        logger.error("[CRAG-V3] Grading failed: %s", e)
        yield {"type": "thinking", "content": "⚠️ Bỏ qua đánh giá chất lượng, tiếp tục tạo câu trả lời.", "step": "grading"}
        grading_result = None
        passed = True  # Continue without grading

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 4: Query Rewrite (if grading failed)
    # ═══════════════════════════════════════════════════════════════════
    rewritten_query = None
    if grading_result and not passed and owner._rewriter:
        yield {"type": "status", "content": "Tinh chỉnh câu hỏi"}

        try:
            rewrite_result = await owner._rewriter.rewrite(
                query,
                getattr(grading_result, "feedback", ""),
            )
            candidate_query = getattr(rewrite_result, "rewritten_query", rewrite_result)
            if isinstance(candidate_query, str):
                candidate_query = candidate_query.strip()
            else:
                candidate_query = None

            if candidate_query and candidate_query != query:
                rewritten_query = candidate_query
                logger.info("[CRAG-V3] Query rewritten: %s...", rewritten_query[:50])

                yield {
                    "type": "thinking",
                    "content": f"Tinh chỉnh câu hỏi để tìm kiếm chính xác hơn\nCâu gốc: {query[:80]}\nCâu mới: {rewritten_query[:80]}",
                    "step": "rewrite"
                }

                # Re-retrieve with rewritten query
                documents = await owner._retrieve(rewritten_query, context)

        except Exception as e:
            logger.warning("[CRAG-V3] Rewrite failed: %s", e)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 5: Generation (TRUE streaming via astream!)
    # ═══════════════════════════════════════════════════════════════════
    yield {"type": "status", "content": "Tạo câu trả lời"}

    tracer.start_step(step_names_cls.GENERATION, "Tạo câu trả lời từ context")
    logger.info("[CRAG-V3] Phase 5: Generating response with streaming")

    gen_start_time = time.time()

    full_answer_parts = []  # Sprint 144: Accumulate answer tokens for result

    if not owner._rag:
        yield {"type": "answer", "content": "Hmm, mình chưa sẵn sàng xử lý lúc này nè~ Bạn thử lại sau nhé? (˶˃ ᵕ ˂˶)"}
        yield {"type": "done", "content": ""}
        return

    try:
        # Build context from documents
        context_parts = []
        sources_data = []

        for doc in documents:
            content = doc.get("content", "")
            title = doc.get("title", "Unknown")
            if content:
                context_parts.append(f"[{title}]: {content}")

            sources_data.append({
                "title": title,
                "content": content[:max_content_snippet_length] if content else "",
                "source": doc.get("source", ""),
                "page_number": doc.get("page_number"),
                "image_url": doc.get("image_url"),
                "document_id": doc.get("document_id"),
                "node_id": doc.get("node_id"),
                "bounding_boxes": doc.get("bounding_boxes"),
                "content_type": doc.get("content_type"),
            })

        # P2 (Perplexity pattern): Emit sources BEFORE LLM generation starts so
        # the user sees found documents while the answer is being composed.
        if sources_data:
            yield {
                "type": "sources",
                "content": sources_data,
            }

        # Sprint 189b: Collect evidence images from retrieved documents
        evidence_image_list = []
        if documents:
            try:
                node_ids = [d.get("node_id", "") for d in documents if d.get("node_id")]
                if node_ids:
                    from app.engine.agentic_rag.document_retriever import DocumentRetriever
                    ev_imgs = await DocumentRetriever.collect_evidence_images(node_ids, max_images=3)
                    evidence_image_list = [
                        {"url": img.url, "page_number": img.page_number, "document_id": img.document_id}
                        for img in ev_imgs
                    ]
            except Exception as e:
                logger.warning("[CRAG-V3] Evidence image collection failed: %s", e)

        # Get user context
        user_context = context  # The dict passed to process_streaming
        user_role = user_context.get("user_role", "student")
        history = user_context.get("conversation_history", "")

        # SOTA PATTERN: Defensive defaults for data quality issues
        # Following OpenAI/Anthropic pattern - graceful degradation, never crash
        from app.models.knowledge_graph import KnowledgeNode, NodeType

        knowledge_nodes = []
        for i, doc in enumerate(documents):
            # CRITICAL: Use 'or' operator to handle empty strings
            # doc.get("title", "X") returns '' if title is empty string
            # doc.get("title") or "X" returns "X" if title is empty/None
            node = KnowledgeNode(
                id=doc.get("node_id") or f"doc_{i}",
                node_type=NodeType.REGULATION,
                content=doc.get("content") or "No content",
                title=doc.get("title") or f"Document {i+1}",
                source=doc.get("document_id") or ""
            )
            knowledge_nodes.append(node)

        # Keep retrieval progress out of the final answer stream. The UI already
        # has status/tool surfaces for progress; answer_delta should contain only
        # user-facing synthesis.
        yield {
            "type": "status",
            "content": f"Wiii tìm thấy {len(documents)} tài liệu liên quan, đang phân tích để trả lời..."
        }

        # Stream tokens from RAGAgent
        # FIXED: Removed invalid 'context' param, pass nodes correctly
        token_count = 0
        async for chunk in owner._rag._generate_response_streaming(
            question=rewritten_query or query,
            nodes=knowledge_nodes,
            conversation_history=history,
            user_role=user_role,
            entity_context=graph_entity_context_streaming,
            conversation_summary=context.get("conversation_summary") or history,
            core_memory_block=context.get("core_memory_block"),
            response_language=context.get("response_language"),
            host_context_prompt=context.get("host_context_prompt", ""),  # Sprint 222
            living_context_prompt=context.get("living_context_prompt", ""),
            skill_context=context.get("skill_context", ""),
            capability_context=context.get("capability_context", ""),
            _skill_prompts=context.get("_skill_prompts"),
        ):
            token_count += 1
            # Handle thinking chunks from answer generator
            if chunk.startswith("__THINKING__"):
                thinking_text = chunk[len("__THINKING__"):]
                if thinking_text:
                    yield {"type": "thinking_delta", "content": thinking_text}
                continue
            full_answer_parts.append(chunk)
            yield {"type": "answer", "content": chunk}

        gen_duration = (time.time() - gen_start_time) * 1000
        tracer.end_step(
            result=f"Tạo câu trả lời: {token_count} tokens",
            confidence=0.85,
            details={"token_count": token_count, "duration_ms": gen_duration}
        )

        logger.info("[CRAG-V3] Generation complete: %d tokens in %.0fms", token_count, gen_duration)

    except Exception as e:
        logger.error("[CRAG-V3] Generation failed: %s", e)
        _error_msg = "Hmm, mình gặp chút trục trặc khi soạn câu trả lời nè~ Bạn thử lại giúp mình nhé? ≽^•⩊•^≼"
        yield {"type": "answer", "content": _error_msg}
        full_answer_parts.append(_error_msg)  # Sprint 189b: capture in result

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 6: Finalize (sources + metadata)
    # ═══════════════════════════════════════════════════════════════════
    total_time = time.time() - start_time

    # Calculate confidence
    confidence = owner._calculate_confidence(
        analysis, 
        grading_result, 
        None  # No verification in streaming mode
    )

    # Build reasoning trace
    reasoning_trace = tracer.build_trace(final_confidence=confidence / 100)

    # Sprint 189b-R5: Build thinking_content from tracer (parity with sync path)
    thinking_content = tracer.build_thinking_summary()
    # Note: native_thinking unavailable in streaming (generate_response_streaming yields text only)

    full_answer = "".join(full_answer_parts)
    safe_sources_data = [] if answer_declines_rag_sources_impl(full_answer) else sources_data
    safe_evidence_image_list = [] if not safe_sources_data else evidence_image_list

    # Emit sources only when the final answer actually uses them.
    if safe_sources_data:
        yield {
            "type": "sources",
            "content": safe_sources_data
        }

    # Emit metadata with reasoning_trace
    # FIX: ReasoningTrace is Pydantic BaseModel, use model_dump() (v2) or dict() (v1)
    reasoning_dict = None
    if reasoning_trace:
        try:
            # Pydantic v2: model_dump()
            reasoning_dict = reasoning_trace.model_dump()
        except AttributeError:
            # Pydantic v1 fallback: dict()
            reasoning_dict = reasoning_trace.dict()

    yield {
        "type": "metadata",
        "content": {
            "reasoning_trace": reasoning_dict,
            "processing_time": total_time,
            "confidence": confidence,
            "model": settings_obj.rag_model_version,
            "was_rewritten": rewritten_query is not None,
            "doc_count": len(documents) if safe_sources_data else 0,
            "evidence_images": safe_evidence_image_list,  # Sprint 189b
        }
    }

    # Sprint 144: Yield CorrectiveRAGResult for rag_node to capture
    yield {
        "type": "result",
        "data": result_cls(
            answer=full_answer,
            sources=safe_sources_data,
            query_analysis=analysis,
            grading_result=grading_result,
            was_rewritten=rewritten_query is not None,
            rewritten_query=rewritten_query,
            confidence=confidence,
            reasoning_trace=reasoning_trace,
            thinking_content=thinking_content,  # Sprint 189b-R5: parity with sync
            evidence_images=safe_evidence_image_list,  # Sprint 189b
        )
    }

    yield {"type": "done", "content": ""}

    logger.info("[CRAG-V3] Complete: %.2fs, confidence=%.0f%%", total_time, confidence)
