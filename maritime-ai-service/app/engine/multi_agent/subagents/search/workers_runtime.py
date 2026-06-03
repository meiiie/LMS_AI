"""Runtime implementations for search subagent workers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)

logger = logging.getLogger(__name__)


def _safe_search_text(value: Any, *, max_length: int = 200) -> str:
    return redact_runtime_secret_text(str(value or "")[:max_length])


def _safe_product_payload(value: Any) -> Dict[str, Any]:
    safe_value = sanitize_runtime_payload(value)
    if not isinstance(safe_value, dict):
        return {}
    return {
        str(key): item
        for key, item in safe_value.items()
        if str(key) != "redacted_secret_count"
    }


async def plan_search_impl(
    state: Dict[str, Any],
    *,
    get_available_platforms: Callable[[], List[str]],
    order_platforms: Callable[[List[str]], List[str]],
    get_event_queue: Callable[[Optional[str]], Any],
    render_search_narration: Callable[..., Awaitable[Any]],
    emit_search_narration: Callable[..., Awaitable[None]],
    push: Callable[[Any, dict], Awaitable[None]],
) -> dict:
    query = state.get("query", "")
    available = get_available_platforms()
    ordered = order_platforms(available)
    event_queue = get_event_queue(state.get("_event_bus_id"))

    query_plan_text = None
    query_plan = None
    try:
        from app.core.config import get_settings as _get_settings

        if _get_settings().enable_query_planner:
            from app.engine.tools.query_planner import (
                format_plan_for_prompt,
                plan_search_queries,
            )

            if event_queue:
                plan_narration = await render_search_narration(
                    state=state,
                    phase="route",
                    cue="query_planner",
                    next_action=(
                        "Bẻ yêu cầu thành những nhánh dò ngắn hơn trước khi chạy tìm kiếm."
                    ),
                    observations=[query],
                )
                await emit_search_narration(event_queue, plan_narration)

            query_plan = await plan_search_queries(query, state.get("context", {}))
            if query_plan:
                query_plan_text = format_plan_for_prompt(query_plan)
                if event_queue:
                    detail_narration = await render_search_narration(
                        state=state,
                        phase="route",
                        cue=query_plan.intent.value,
                        next_action=(
                            "Giữ lại vài lối dò đủ chặt để so giá mà không lệch ý người dùng."
                        ),
                        observations=[
                            f"intent={query_plan.intent.value}",
                            f"sub_queries={len(query_plan.sub_queries)}",
                        ],
                    )
                    await emit_search_narration(
                        event_queue,
                        detail_narration,
                        include_start=False,
                    )
                logger.info(
                    "[PLAN_SEARCH] Query plan: intent=%s, strategy=%s, %d sub_queries",
                    query_plan.intent.value,
                    query_plan.search_strategy.value,
                    len(query_plan.sub_queries),
                )
            if event_queue:
                await push(
                    event_queue,
                    {"type": "thinking_end", "content": "", "node": "product_search_agent"},
                )
    except Exception as exc:
        logger.debug("[PLAN_SEARCH] Query planner skipped: %s", exc)

    if event_queue:
        platform_narration = await render_search_narration(
            state=state,
            phase="retrieve",
            cue="platform_plan",
            next_action=(
                "Dò nhiều nền tảng song song rồi chỉ giữ lại nơi thật sự giúp quyết định cuối."
            ),
            observations=[f"platforms={', '.join(ordered[:6])}"],
        )
        await emit_search_narration(event_queue, platform_narration)
        await push(
            event_queue,
            {"type": "thinking_end", "content": "", "node": "product_search_agent"},
        )

    effective_query = query
    if query_plan_text and query_plan:
        plan_product = query_plan.product_name_vi or ""
        if (
            plan_product
            and plan_product.lower() not in query.lower()
            and len(plan_product) > len(query)
        ):
            effective_query = f"{plan_product} {query}"
            logger.info(
                "[PLAN_SEARCH] Follow-up detected: rewriting '%s' -> '%s'",
                query,
                effective_query,
            )

    result: Dict[str, Any] = {
        "platforms_to_search": ordered,
        "query": effective_query,
        "query_variants": [effective_query],
        "search_round": 1,
        "current_agent": "product_search_agent",
    }
    if query_plan_text:
        result["_query_plan_text"] = query_plan_text
    return result


async def platform_worker_impl(
    state: Dict[str, Any],
    *,
    get_event_queue: Callable[[Optional[str]], Any],
    push: Callable[[Any, dict], Awaitable[None]],
    render_search_narration: Callable[..., Awaitable[Any]],
    emit_search_narration: Callable[..., Awaitable[None]],
    extract_rating: Callable[[str], Optional[float]],
    extract_sold: Callable[[str], Optional[int]],
) -> dict:
    platform_id = state.get("platform_id", "")
    safe_platform_id = _safe_search_text(platform_id, max_length=80) or "unknown"
    query = state.get("query", "")
    safe_query = _safe_search_text(query, max_length=1000)
    max_results = state.get("max_results", 20)
    page = state.get("page", 1)

    event_queue = get_event_queue(state.get("_event_bus_id"))
    tool_name = f"tool_search_{safe_platform_id}"
    await push(
        event_queue,
        {
            "type": "tool_call",
            "content": {
                "name": tool_name,
                "args": {"query": safe_query, "max_results": max_results},
                "id": f"sw_{safe_platform_id}",
            },
            "node": "product_search_agent",
        },
    )

    start = time.monotonic()
    products: List[Dict[str, Any]] = []
    error: Optional[str] = None

    try:
        from app.engine.search_platforms import get_search_platform_registry

        adapter = get_search_platform_registry().get(platform_id)
        if adapter is None:
            error = f"Platform {safe_platform_id} not found in registry"
        else:
            results = await asyncio.to_thread(adapter.search_sync, query, max_results, page)
            products = [_safe_product_payload(result.to_dict()) for result in results]
    except Exception as exc:
        error = f"{safe_platform_id}: {type(exc).__name__}"
        logger.warning(
            "[SEARCH_WORKER] %s failed: %s",
            safe_platform_id,
            type(exc).__name__,
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    try:
        from app.engine.skills.skill_tool_bridge import record_tool_usage

        record_tool_usage(
            tool_name=tool_name,
            success=bool(products),
            latency_ms=duration_ms,
            query_snippet=_safe_search_text(query, max_length=100),
            error_message=error or "",
        )
    except Exception as exc:
        logger.debug("[WORKER] Skill bridge recording failed: %s", exc)

    result_summary = f"{len(products)} kết quả" if products else (error or "Không có kết quả")
    await push(
        event_queue,
        {
            "type": "tool_result",
            "content": {
                "name": tool_name,
                "result": result_summary,
                "id": f"sw_{safe_platform_id}",
            },
            "node": "product_search_agent",
        },
    )
    ack_narration = await render_search_narration(
        state=state,
        phase="act",
        cue=safe_platform_id,
        tool_names=[tool_name],
        result=result_summary,
        next_action="Lồng mặt bằng giá mới này vào bức tranh chung rồi đi tiếp.",
        observations=[
            f"platform={safe_platform_id}",
            f"results={len(products)}",
            f"duration_ms={duration_ms}",
        ],
    )
    await emit_search_narration(event_queue, ack_narration, include_start=False)

    try:
        from app.core.config import get_settings as _get_settings

        settings = _get_settings()
        if getattr(settings, "enable_product_image_enrichment", False) and products:
            from app.engine.search_platforms.image_enricher import enrich_product_images

            products = enrich_product_images(products, query, platform_id)
            products = [_safe_product_payload(product) for product in products]
    except Exception as exc:
        logger.debug(
            "[WORKER] Image enrichment failed for %s: %s",
            safe_platform_id,
            type(exc).__name__,
        )

    for product in products:
        if not product.get("rating"):
            rating = extract_rating(
                (product.get("snippet") or "") + " " + (product.get("title") or "")
            )
            if rating is not None:
                product["rating"] = rating
        if not product.get("sold_count"):
            sold = extract_sold(product.get("snippet") or "")
            if sold is not None:
                product["sold_count"] = sold

    if event_queue is not None and products:
        try:
            from app.core.config import get_settings as _get_settings

            settings = _get_settings()
            curation_active = getattr(settings, "enable_curated_product_cards", False) is True
            if settings.enable_product_preview_cards and not curation_active:
                max_per_platform = min(8, settings.product_preview_max_cards)
                for index, product in enumerate(products[:max_per_platform]):
                    title = product.get("title") or product.get("name", "")
                    if not title:
                        continue
                    link = product.get("link") or product.get("url", "")
                    preview_id = (
                        f"sw_{safe_platform_id}_{hash(link) % 100000}_{index}"
                        if link
                        else f"sw_{safe_platform_id}_{index}"
                    )
                    await push(
                        event_queue,
                        {
                            "type": "preview",
                            "content": {
                                "preview_type": "product",
                                "preview_id": preview_id,
                                "title": title[:120],
                                "snippet": (
                                    product.get("snippet")
                                    or product.get("description", "")
                                )[:150],
                                "url": link,
                                "image_url": (
                                    product.get("image")
                                    or product.get("image_url")
                                    or product.get("thumbnail", "")
                                ),
                                "metadata": {
                                    "price": product.get("price", ""),
                                    "platform": safe_platform_id,
                                    "seller": product.get("seller", ""),
                                    "rating": product.get("rating"),
                                    "sold_count": product.get("sold_count"),
                                    "delivery": product.get("delivery", ""),
                                    "extracted_price": product.get("extracted_price"),
                                    "location": product.get("location", ""),
                                },
                            },
                            "node": "product_search_agent",
                        },
                    )
        except Exception as exc:
            logger.debug(
                "[WORKER] Preview emission failed for %s: %s",
                safe_platform_id,
                type(exc).__name__,
            )

    return {
        "all_products": products,
        "platform_errors": [error] if error else [],
        "platforms_searched": [safe_platform_id],
        "tools_used": [
            {
                "name": tool_name,
                "args": {"query": safe_query},
                "duration_ms": duration_ms,
            }
        ],
    }


async def aggregate_results_impl(
    state: Dict[str, Any],
    *,
    get_event_queue: Callable[[Optional[str]], Any],
    push: Callable[[Any, dict], Awaitable[None]],
    render_search_narration: Callable[..., Awaitable[Any]],
    emit_search_narration: Callable[..., Awaitable[None]],
) -> dict:
    all_products: List[Dict[str, Any]] = state.get("all_products", [])
    platforms = state.get("platforms_searched", [])
    query = state.get("query", "")

    event_queue = get_event_queue(state.get("_event_bus_id"))
    aggregate_narration = await render_search_narration(
        state=state,
        phase="verify",
        cue="aggregate",
        next_action="Gạn trùng và giữ lại mặt bằng giá đủ sạch để so tiếp.",
        observations=[f"platforms={len(platforms)}", f"all_products={len(all_products)}"],
    )
    await emit_search_narration(event_queue, aggregate_narration)

    seen_links: set = set()
    unique: List[Dict[str, Any]] = []
    for product in all_products:
        link = product.get("link", "")
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        unique.append(product)

    await emit_search_narration(
        event_queue,
        await render_search_narration(
            state=state,
            phase="verify",
            cue="dedupe",
            next_action="Giữ lại những lựa chọn thật sự khác nhau để bảng so đỡ nhiễu.",
            observations=[
                f"unique={len(unique)}",
                f"duplicates={len(all_products) - len(unique)}",
                f"platforms={len(platforms)}",
            ],
            result=f"{len(unique)} sản phẩm sau khi gạn trùng",
        ),
        include_start=False,
    )

    excel_path: Optional[str] = None
    if len(unique) >= 5:
        try:
            from app.engine.tools.excel_report_tool import tool_generate_product_report

            excel_result = await asyncio.to_thread(
                tool_generate_product_report.invoke,
                {"query": query, "products_json": json.dumps(unique, ensure_ascii=False)},
            )
            excel_str = str(excel_result)
            if "excel" in excel_str.lower() or "xlsx" in excel_str.lower():
                excel_path = excel_str
        except Exception as exc:
            logger.warning("[AGGREGATE] Excel generation failed: %s", exc)

    await push(
        event_queue,
        {"type": "thinking_end", "content": "", "node": "product_search_agent"},
    )
    return {"deduped_products": unique, "excel_path": excel_path}


async def emit_curated_previews_impl(
    event_queue,
    curated_products: List[Dict[str, Any]],
    push: Callable[[Any, dict], Awaitable[None]],
) -> None:
    """Emit preview events for curated products."""
    if event_queue is None or not curated_products:
        return

    for index, product in enumerate(curated_products):
        title = product.get("title") or product.get("name", "")
        if not title:
            continue
        link = product.get("link") or product.get("url", "")
        preview_id = f"curated_{hash(link) % 100000}_{index}" if link else f"curated_{index}"
        metadata = {
            "price": product.get("price", ""),
            "platform": product.get("platform", ""),
            "seller": product.get("seller", ""),
            "rating": product.get("rating"),
            "sold_count": product.get("sold_count"),
            "delivery": product.get("delivery", ""),
            "extracted_price": product.get("extracted_price"),
            "location": product.get("location", ""),
        }
        if product.get("_highlight"):
            metadata["highlight"] = product["_highlight"]
        if product.get("_relevance_score") is not None:
            metadata["relevance_score"] = product["_relevance_score"]

        await push(
            event_queue,
            {
                "type": "preview",
                "content": {
                    "preview_type": "product",
                    "preview_id": preview_id,
                    "title": title[:120],
                    "snippet": (
                        product.get("snippet") or product.get("description", "")
                    )[:150],
                    "url": link,
                    "image_url": (
                        product.get("image")
                        or product.get("image_url")
                        or product.get("thumbnail", "")
                    ),
                    "metadata": metadata,
                },
                "node": "product_search_agent",
            },
        )


async def curate_products_impl(
    state: Dict[str, Any],
    *,
    get_event_queue: Callable[[Optional[str]], Any],
    push: Callable[[Any, dict], Awaitable[None]],
    render_search_narration: Callable[..., Awaitable[Any]],
    emit_search_narration: Callable[..., Awaitable[None]],
    emit_curated_previews: Callable[[Any, List[Dict[str, Any]], str], Awaitable[None]],
) -> dict:
    deduped = state.get("deduped_products", [])
    query = state.get("query", "")
    event_queue = get_event_queue(state.get("_event_bus_id"))

    try:
        from app.core.config import get_settings as _get_settings

        settings = _get_settings()
        curation_enabled = getattr(settings, "enable_curated_product_cards", False)
        max_curated = getattr(settings, "curated_product_max_cards", 8)
        llm_tier = getattr(settings, "curated_product_llm_tier", "light")
    except Exception as exc:
        logger.debug("[CURATE] Config load failed, curation disabled: %s", exc)
        curation_enabled = False
        max_curated = 8
        llm_tier = "light"

    if not curation_enabled or len(deduped) <= max_curated:
        curated = deduped[:max_curated]
        if curation_enabled:
            await emit_curated_previews(event_queue, curated, query)
        return {"curated_products": curated}

    curation_narration = await render_search_narration(
        state=state,
        phase="verify",
        cue="curation",
        next_action="Gạn những lựa chọn đáng cân nhắc nhất trước khi chốt.",
        observations=[f"deduped={len(deduped)}", f"max_curated={max_curated}"],
    )
    await emit_search_narration(event_queue, curation_narration)

    curated = None
    try:
        from app.engine.multi_agent.subagents.search.curation import curate_with_llm

        selection = await curate_with_llm(
            query=query,
            products=deduped,
            max_curated=max_curated,
            llm_tier=llm_tier,
            provider_override=state.get("provider"),
            requested_model=state.get("model"),
        )
        if selection and selection.selected:
            curated = []
            for pick in selection.selected:
                product = deduped[pick.index].copy()
                product["_highlight"] = pick.highlight
                product["_relevance_score"] = pick.relevance_score
                product["_curation_reason"] = pick.reason
                curated.append(product)

            await emit_search_narration(
                event_queue,
                await render_search_narration(
                    state=state,
                    phase="verify",
                    cue="curated",
                    next_action="Giữ lại vài lựa chọn đủ đáng mua rồi bước sang lúc chốt.",
                    observations=[
                        f"curated={len(curated)}",
                        ", ".join(p.get("_highlight", "") for p in curated[:5]),
                    ],
                ),
                include_start=False,
            )
    except Exception as exc:
        logger.warning("[CURATE_NODE] LLM curation failed: %s", exc)

    if not curated:
        curated = deduped[:max_curated]
        await emit_search_narration(
            event_queue,
            await render_search_narration(
                state=state,
                phase="verify",
                cue="fallback_curated",
                next_action="Tạm giữ top sản phẩm giá ổn nhất để bạn so nhanh trước.",
                observations=[f"curated={len(curated)}"],
            ),
            include_start=False,
        )

    await push(
        event_queue,
        {"type": "thinking_end", "content": "", "node": "product_search_agent"},
    )
    await emit_curated_previews(event_queue, curated, query)
    return {"curated_products": curated}


async def synthesize_response_impl(
    state: Dict[str, Any],
    *,
    chunk_size: int,
    chunk_delay: float,
    get_event_queue: Callable[[Optional[str]], Any],
    push: Callable[[Any, dict], Awaitable[None]],
    render_search_narration: Callable[..., Awaitable[Any]],
    emit_search_narration: Callable[..., Awaitable[None]],
) -> dict:
    products = state.get(
        "curated_products",
        state.get("deduped_products", state.get("all_products", [])),
    )
    platforms = state.get("platforms_searched", [])
    errors = state.get("platform_errors", [])
    query = state.get("query", "")
    excel_path = state.get("excel_path")
    event_queue = get_event_queue(state.get("_event_bus_id"))

    top_products = products[:20]
    product_text = json.dumps(top_products, ensure_ascii=False, indent=2)[:8000]
    synthesis_prompt = (
        f"Tổng hợp kết quả tìm kiếm sản phẩm:\n\n"
        f"Query: {query}\n"
        f"Tìm được: {len(products)} sản phẩm từ {len(platforms)} nền tảng ({', '.join(platforms[:6])})\n"
        f"{'Lỗi: ' + ', '.join(errors[:3]) if errors else ''}\n"
        f"{'File Excel: ' + excel_path if excel_path else ''}\n\n"
        f"Top {len(top_products)} sản phẩm "
        f"({'đã được LLM lọc chọn' if state.get('curated_products') else 'sắp xếp giá rẻ nhất'}):\n"
        f"{product_text}\n\n"
        "YÊU CẦU:\n"
        "- Trả lời tiếng Việt\n"
        "- Format bảng Markdown so sánh\n"
        "- Link sản phẩm: markdown link [Xem ngay](url)\n"
        "- Ghi rõ nguồn (sàn nào), giá VNĐ\n"
        "- Nêu top 5 giá tốt nhất"
    )

    final_response = ""
    answer_streamed = False
    try:
        from app.engine.character.character_card import build_wiii_runtime_prompt
        from app.engine.messages import Message
        from app.engine.messages_adapters import to_openai_dict
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        llm = AgentConfigRegistry.get_llm(
            "product_search",
            effort_override=state.get("thinking_effort"),
            provider_override=state.get("provider"),
            requested_model=state.get("model"),
        )
        if not llm:
            raise RuntimeError("LLM unavailable")

        system_sections = [
            build_wiii_runtime_prompt(
                user_id=state.get("user_id", "__global__"),
                organization_id=state.get("organization_id"),
                mood_hint=(state.get("context") or {}).get("mood_hint"),
                personality_mode=(state.get("context") or {}).get("personality_mode"),
            ),
            (
                "Bạn là Wiii — trợ lý tìm kiếm sản phẩm. Tổng hợp kết quả tìm kiếm "
                "và trình bày rõ ràng."
            ),
        ]
        plan_text = state.get("_query_plan_text", "")
        if plan_text:
            system_sections.append(plan_text)
        if state.get("skill_context"):
            system_sections.append("## Skill Context\n" + str(state.get("skill_context")))
        if state.get("capability_context"):
            system_sections.append(
                "## Capability Handbook\n" + str(state.get("capability_context"))
            )
        if state.get("host_context_prompt"):
            system_sections.append(str(state.get("host_context_prompt")))

        system_content = "\n\n".join(section for section in system_sections if section)
        messages = [to_openai_dict(Message(role="system", content=system_content))]

        recent_messages = state.get("context", {}).get("langchain_messages", [])
        if recent_messages:
            for message in recent_messages[-4:]:
                if isinstance(message, dict):
                    role = message.get("role", "human")
                    content = str(message.get("content", ""))
                else:
                    role = getattr(message, "type", "human")
                    content = str(getattr(message, "content", ""))
                if not content.strip():
                    continue
                if role in ("human", "user"):
                    messages.append(to_openai_dict(Message(role="user", content=content[:500])))
                elif role in ("ai", "assistant"):
                    messages.append(to_openai_dict(Message(role="assistant", content=content[:500])))

        messages.append(to_openai_dict(Message(role="user", content=synthesis_prompt)))

        if event_queue:
            synthesis_narration = await render_search_narration(
                state=state,
                phase="synthesize",
                cue="final_response",
                next_action=(
                    "Xếp lại các nguồn theo giá, độ tin cậy, rồi chốt lựa chọn đáng mua nhất."
                ),
                observations=[f"products={len(products)}", f"platforms={len(platforms)}"],
            )
            await emit_search_narration(event_queue, synthesis_narration)

            chunks: List[str] = []
            async for chunk in llm.astream(messages):
                text = ""
                if hasattr(chunk, "content"):
                    content = chunk.content
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text += block.get("text", "")
                if text:
                    chunks.append(text)
                    for index in range(0, len(text), chunk_size):
                        sub = text[index : index + chunk_size]
                        await push(
                            event_queue,
                            {
                                "type": "answer_delta",
                                "content": sub,
                                "node": "product_search_agent",
                            },
                        )
                        if index + chunk_size < len(text):
                            await asyncio.sleep(chunk_delay)

            final_response = "".join(chunks)
            answer_streamed = True
            await push(
                event_queue,
                {"type": "thinking_end", "content": "", "node": "product_search_agent"},
            )
        else:
            result = await llm.ainvoke(messages)
            final_response = result.content if hasattr(result, "content") else str(result)

    except Exception as exc:
        logger.warning("[SYNTHESIZE] LLM failed: %s", exc)
        final_response = (
            f"Tìm thấy {len(products)} sản phẩm từ {len(platforms)} nền tảng."
        )

    all_products_json = ""
    try:
        deduped = state.get("deduped_products", [])
        if deduped:
            all_products_json = json.dumps(deduped[:100], ensure_ascii=False)[:50000]
    except Exception as exc:
        logger.debug("[SYNTHESIZE] Product JSON serialization failed: %s", exc)

    thinking_rollup = await render_search_narration(
        state=state,
        phase="synthesize",
        cue="summary_rollup",
        next_action="Giữ lại mặt bằng giá đủ tin rồi chốt phương án phù hợp nhất.",
        observations=[f"platforms={len(platforms)}", f"products={len(products)}"],
        result=final_response[:400],
    )
    return {
        "final_response": final_response,
        "agent_outputs": {"product_search": final_response},
        "current_agent": "product_search_agent",
        "_answer_streamed_via_bus": answer_streamed,
        "thinking": thinking_rollup.summary,
        "_all_search_products_json": all_products_json,
    }
