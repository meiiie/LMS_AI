"""Runtime helpers for ProductSearchAgentNode."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple

from app.engine.messages import Message, ToolCall

from app.engine.multi_agent.agents.product_search_surface import (
    _DEEP_SEARCH_PROMPT,
    _SYSTEM_PROMPT,
    _iteration_label,
    _iteration_phase,
    _render_product_search_narration,
    emit_product_previews_impl,
)
from app.engine.multi_agent.agents.product_search_runtime_bindings import (
    build_wiii_runtime_prompt,
    curate_with_llm,
    filter_tools_for_role,
    format_plan_for_prompt,
    get_agent_llm,
    get_effective_provider_impl,
    get_search_platform_registry,
    get_settings,
    invoke_tool_with_runtime,
    load_product_search_tools,
    plan_search_queries,
    select_runtime_tools,
)
from app.engine.multi_agent.graph_runtime_helpers import _get_requested_model, _remember_runtime_target
from app.engine.multi_agent.tool_policy_session import (
    build_visible_tool_policy_session,
    record_tool_policy_session,
    resolve_tool_policy_denial,
)


logger = logging.getLogger(__name__)


def _tool_name(tool: object) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def init_llm_impl(node) -> None:
    """Initialize LLM and bind product-search tools."""

    try:
        node._llm = get_agent_llm("product_search")
        if not node._llm:
            node._llm = get_agent_llm("direct")
    except Exception as exc:
        logger.warning("[PRODUCT_SEARCH] LLM init failed: %s", exc)

    try:
        node._tools = load_product_search_tools()
    except Exception as exc:
        logger.warning("[PRODUCT_SEARCH] Tools init failed: %s", exc)

    if node._llm and node._tools:
        node._llm_with_tools = node._llm.bind_tools(node._tools)
    elif node._llm:
        node._llm_with_tools = node._llm


async def react_loop_impl(
    node,
    *,
    query: str,
    context: dict,
    state=None,
    event_queue=None,
    thinking_effort: str = None,
    images: list = None,
    runtime_context_base=None,
    max_iterations_default: int,
    chunk_size: int,
    chunk_delay: float,
    product_result_tools: set[str],
    product_search_required_tools,
) -> Tuple[str, List[Dict], Optional[str], bool]:
    """Run the product-search ReAct loop."""

    if not node._llm:
        return "Hmm, mình chưa sẵn sàng tìm kiếm sản phẩm lúc này nè~ Bạn thử lại sau nhé? (˶˃ ᵕ ˂˶)", [], None, False

    state = state or {}
    allow_authored_fallback = bool(state.get("allow_authored_thinking_fallback", True))

    active_tools = filter_tools_for_role(
        node._tools,
        (context or {}).get("user_role", "student"),
    )
    candidate_tool_names = [_tool_name(tool) for tool in active_tools]
    llm_to_use = node._llm_with_tools

    async def _push(event):
        if event_queue is None:
            return
        try:
            event_queue.put_nowait(event)
        except Exception:
            pass

    async def _push_thinking_deltas(text: str):
        for idx in range(0, len(text), chunk_size):
            sub = text[idx : idx + chunk_size]
            await _push({"type": "thinking_delta", "content": sub, "node": "product_search_agent"})
            if idx + chunk_size < len(text):
                await asyncio.sleep(chunk_delay)

    async def _push_answer_deltas(text: str):
        for idx in range(0, len(text), chunk_size):
            sub = text[idx : idx + chunk_size]
            await _push({"type": "answer_delta", "content": sub, "node": "product_search_agent"})
            if idx + chunk_size < len(text):
                await asyncio.sleep(chunk_delay)

    async def _emit_narration(narration, *, include_start: bool = True):
        if event_queue is None or narration is None or not allow_authored_fallback:
            return
        if include_start:
            await _push(
                {
                    "type": "thinking_start",
                    "content": narration.label,
                    "node": "product_search_agent",
                    "summary": narration.summary,
                    "details": {
                        "phase": narration.phase,
                        "style_tags": narration.style_tags,
                    },
                }
            )
        chunks = narration.delta_chunks or ([narration.summary] if narration.summary else [])
        for chunk in chunks:
            await _push_thinking_deltas(chunk)

    system_sections = [
        build_wiii_runtime_prompt(
            user_id=state.get("user_id", "__global__"),
            organization_id=state.get("organization_id"),
            mood_hint=context.get("mood_hint"),
            personality_mode=context.get("personality_mode"),
        ),
        _SYSTEM_PROMPT,
        _DEEP_SEARCH_PROMPT,
    ]

    for key, heading in (
        ("skill_context", "## Skill Context\n"),
        ("capability_context", "## Capability Handbook\n"),
        ("host_context_prompt", ""),
        ("living_context_prompt", ""),
        ("widget_feedback_prompt", ""),
    ):
        value = state.get(key)
        if value:
            system_sections.append(f"{heading}{value}")

    system_prompt = "\n\n".join(section for section in system_sections if section)

    # Unified thinking enforcement at TOP for maximum model attention
    try:
        from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement
        system_prompt = get_thinking_enforcement() + "\n\n" + system_prompt
    except Exception:
        pass
    narrated_thinking: List[str] = []
    query_plan = None

    try:
        if get_settings().enable_query_planner:
            query_plan = await plan_search_queries(query, context)
            if event_queue is not None:
                plan_narration = await _render_product_search_narration(
                    state=state,
                    context=context,
                    phase="route",
                    cue="query_planner",
                    next_action="Bẻ yêu cầu thành vài lối dò gọn trước khi bung tìm kiếm thật.",
                    observations=[query],
                )
                if allow_authored_fallback:
                    narrated_thinking.append(plan_narration.summary)
                await _emit_narration(plan_narration)
            if query_plan:
                system_prompt += "\n\n" + format_plan_for_prompt(query_plan)
                if event_queue is not None:
                    plan_detail = await _render_product_search_narration(
                        state=state,
                        context=context,
                        phase="route",
                        cue=query_plan.intent.value,
                        next_action="Giữ lại đúng vài hướng dò giúp so giá sát nhu cầu hơn.",
                        observations=[
                            f"intent={query_plan.intent.value}",
                            f"sub_queries={len(query_plan.sub_queries)}",
                        ],
                    )
                    if allow_authored_fallback:
                        narrated_thinking.append(plan_detail.summary)
                    await _emit_narration(plan_detail, include_start=False)
                logger.info(
                    "[PRODUCT_SEARCH] Query plan: intent=%s, strategy=%s, %d sub_queries",
                    query_plan.intent.value,
                    query_plan.search_strategy.value,
                    len(query_plan.sub_queries),
                )
            if event_queue is not None:
                await _push({"type": "thinking_end", "content": "", "node": "product_search_agent"})
    except Exception as plan_err:
        logger.debug("[PRODUCT_SEARCH] Query planner skipped: %s", plan_err)

    try:
        selected_tools = select_runtime_tools(
            active_tools,
            query=query,
            intent="product_search",
            user_role=(context or {}).get("user_role", "student"),
            max_tools=min(len(active_tools), 10),
            must_include=product_search_required_tools(query, context, query_plan),
        )
        if selected_tools:
            active_tools = selected_tools
            logger.info(
                "[PRODUCT_SEARCH] Runtime-selected tools: %s",
                [getattr(tool, "name", getattr(tool, "__name__", "unknown")) for tool in active_tools],
            )
    except Exception as selection_err:
        logger.debug("[PRODUCT_SEARCH] Runtime tool selection skipped: %s", selection_err)

    policy_session = build_visible_tool_policy_session(
        path="product_search",
        reason="product_search_tool_setup",
        state=state,
        query=query,
        candidate_tool_names=candidate_tool_names,
        visible_tool_names=[_tool_name(tool) for tool in active_tools],
    )
    record_tool_policy_session(state, policy_session)

    runtime_llm_source = node._llm
    llm_to_use = node._llm.bind_tools(active_tools) if node._llm and active_tools else node._llm_with_tools

    provider_override = get_effective_provider_impl(state)
    if (thinking_effort or provider_override) and node._llm:
        try:
            llm_override = get_agent_llm(
                "product_search",
                effort_override=thinking_effort,
                provider_override=provider_override,
                requested_model=_get_requested_model(state),
            )
            if llm_override and active_tools:
                runtime_llm_source = llm_override
                llm_to_use = llm_override.bind_tools(active_tools)
        except Exception:
            pass

    _remember_runtime_target(state, runtime_llm_source or llm_to_use)

    if images and len(images) > 0:
        try:
            if get_settings().enable_visual_product_search:
                system_prompt += """

## NHẬN DIỆN SẢN PHẨM TỪ ẢNH (Sprint 200)
Người dùng đã gửi ảnh sản phẩm.
BƯỚC 1: Gọi tool_identify_product_from_image với ảnh (image_data = base64) để xác định sản phẩm.
BƯỚC 2: Dùng kết quả (search_keywords) để tìm kiếm trên các sàn TMĐT.
BƯỚC 3: So sánh giá và tổng hợp kết quả.
"""
        except Exception:
            pass

    messages: list = [Message(role="system", content=system_prompt)]
    lc_messages = context.get("langchain_messages", [])
    if lc_messages:
        messages.extend(lc_messages[-6:])

    if images and len(images) > 0:
        content_parts: list = []
        for image in images[:1]:
            image_data = image.get("data", "") if isinstance(image, dict) else ""
            media_type = image.get("media_type", "image/jpeg") if isinstance(image, dict) else "image/jpeg"
            if image_data:
                content_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                    }
                )
        content_parts.append({"type": "text", "text": query})
        # Multimodal block list — pass directly as dict; LLM coercion preserves the list
        messages.append({"role": "user", "content": content_parts})
    else:
        messages.append(Message(role="user", content=query))

    tools_used = []
    all_thinking = []
    final_response = ""
    answer_streamed = False
    response = None
    preview_emitted_ids: set = set()
    preview_card_count = 0
    curation_active = False

    try:
        current_settings = get_settings()
        preview_enabled = current_settings.enable_product_preview_cards
        preview_max = current_settings.product_preview_max_cards
        curation_active = getattr(current_settings, "enable_curated_product_cards", False)
        if curation_active:
            preview_enabled = False
    except Exception:
        preview_enabled = True
        preview_max = 20

    accumulated_products: List[Dict] = []

    try:
        max_iterations = get_settings().product_search_max_iterations
    except Exception:
        max_iterations = max_iterations_default

    for iteration in range(max_iterations):
        if event_queue is not None:
            label = _iteration_label(iteration, tools_used)
            iteration_narration = await _render_product_search_narration(
                state=state,
                context=context,
                phase=_iteration_phase(iteration, tools_used),
                cue=label,
                next_action="Dò tiếp nguồn giá, rồi tự gạn xem nơi nào đáng giữ lại.",
                observations=[f"iteration={iteration}", f"tools_used={len(tools_used)}", label],
            )
            narrated_thinking.append(iteration_narration.summary)
            await _emit_narration(iteration_narration)

        if event_queue is not None:
            response = None
            pre_tool_stream_text = ""
            async for chunk in llm_to_use.astream(messages):
                response = chunk if response is None else response + chunk
                text = ""
                if hasattr(chunk, "content"):
                    content = chunk.content
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text += block.get("text", "")
                            elif isinstance(block, str):
                                text += block
                if text:
                    pre_tool_stream_text += text
        else:
            response = await llm_to_use.ainvoke(messages)

        if response is None:
            break

        tool_calls = getattr(response, "tool_calls", [])
        if not tool_calls:
            if event_queue is not None:
                await _push({"type": "thinking_end", "content": "", "node": "product_search_agent"})

            final_response = node._extract_text(response.content)
            thinking_text = node._extract_thinking(response.content)
            if thinking_text:
                all_thinking.append(thinking_text)
            if event_queue is not None and final_response:
                answer_streamed = True
                await _push_answer_deltas(final_response)
            break

        if event_queue is not None and pre_tool_stream_text.strip() and allow_authored_fallback:
            await _push_thinking_deltas(pre_tool_stream_text)

        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "unknown")
            tool_args = tool_call.get("args", {})
            tool_id = tool_call.get("id", f"tc_{iteration}")
            if not isinstance(tool_args, dict):
                tool_args = {"value": tool_args}
                tool_call["args"] = tool_args

            policy_denial = resolve_tool_policy_denial(state, str(tool_name or "").strip())
            if policy_denial is not None:
                policy_decision, policy_message = policy_denial
                policy_payload = {
                    "allowed": False,
                    "path": policy_decision.path,
                    "reason": policy_decision.reason,
                }
                logger.warning(
                    "[PRODUCT_SEARCH] Tool policy denied tool=%r path=%s reason=%s",
                    tool_name,
                    policy_decision.path,
                    policy_decision.reason,
                )
                await _push(
                    {
                        "type": "tool_call",
                        "content": {
                            "name": tool_name,
                            "args": tool_args,
                            "id": tool_id,
                            "policy": policy_payload,
                        },
                        "node": "product_search_agent",
                    }
                )
                await _push(
                    {
                        "type": "tool_result",
                        "content": {
                            "name": tool_name,
                            "result": str(policy_message)[:500],
                            "id": tool_id,
                        },
                        "node": "product_search_agent",
                    }
                )
                messages.append(
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id=str(tool_id),
                                name=str(tool_name or ""),
                                arguments=tool_args,
                            )
                        ],
                    )
                )
                messages.append(Message(role="tool", content=str(policy_message), tool_call_id=tool_id))
                continue

            await _push(
                {
                    "type": "tool_call",
                    "content": {"name": tool_name, "args": tool_args, "id": tool_id},
                    "node": "product_search_agent",
                }
            )

            matched = next((tool for tool in active_tools if tool.name == tool_name), None)
            try:
                if matched:
                    result = await invoke_tool_with_runtime(
                        matched,
                        tool_args,
                        tool_name=tool_name,
                        runtime_context_base=runtime_context_base,
                        tool_call_id=tool_id,
                        prefer_async=False,
                        run_sync_in_thread=True,
                    )
                else:
                    result = json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
            except Exception as exc:
                logger.warning("[PRODUCT_SEARCH] Tool %s failed: %s", tool_name, exc)
                result = json.dumps(
                    {"error": f"Tool {tool_name} failed: {str(exc)[:200]}"},
                    ensure_ascii=False,
                )

            await _push(
                {
                    "type": "tool_result",
                    "content": {"name": tool_name, "result": str(result)[:500], "id": tool_id},
                    "node": "product_search_agent",
                }
            )

            if tool_name.startswith("tool_search_facebook") or tool_name.startswith("tool_search_instagram"):
                try:
                    registry = get_search_platform_registry()
                    platform_id = tool_name.replace("tool_search_", "")
                    adapter = registry.get(platform_id)
                    if adapter and hasattr(adapter, "get_last_screenshots"):
                        for screenshot in adapter.get_last_screenshots():
                            await _push(
                                {
                                    "type": "browser_screenshot",
                                    "content": screenshot,
                                    "node": "product_search_agent",
                                }
                            )
                except Exception:
                    pass

            result_str = str(result)[:5000]
            ack_narration = await _render_product_search_narration(
                state=state,
                context=context,
                phase="act",
                cue=tool_name,
                tool_names=[tool_name],
                result=result_str[:500],
                next_action="Lồng kết quả vừa có vào mặt bằng giá chung rồi quyết định có dò tiếp hay không.",
                observations=[f"iteration={iteration}", f"tool={tool_name}"],
            )
            if allow_authored_fallback:
                narrated_thinking.append(ack_narration.summary)
            await _emit_narration(ack_narration, include_start=False)
            messages.append(
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id=str(tool_call.get("id") or tool_id),
                            name=str(tool_call.get("name") or ""),
                            arguments=tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                        )
                    ],
                )
            )
            messages.append(Message(role="tool", content=result_str, tool_call_id=tool_id))
            tools_used.append({"name": tool_name, "args": tool_args, "iteration": iteration})

            if preview_enabled and event_queue is not None:
                preview_events = emit_product_previews_impl(
                    tool_name=tool_name,
                    result_str=result_str,
                    emitted_ids=preview_emitted_ids,
                    max_cards=preview_max,
                    current_count=preview_card_count,
                    product_result_tools=product_result_tools,
                )
                for preview_event in preview_events:
                    await _push(preview_event)
                    preview_card_count += 1

            if curation_active and tool_name in product_result_tools:
                try:
                    parsed = json.loads(result_str) if isinstance(result_str, str) else result_str
                    if isinstance(parsed, dict):
                        platform = parsed.get("platform", tool_name.replace("tool_search_", ""))
                        for product in parsed.get("results", []) or []:
                            if isinstance(product, dict):
                                product.setdefault("platform", platform)
                                accumulated_products.append(product)
                except (json.JSONDecodeError, Exception):
                    pass

        if event_queue is not None:
            await _push({"type": "thinking_end", "content": "", "node": "product_search_agent"})

    if not final_response and response is not None:
        if event_queue is not None:
            final_narration = await _render_product_search_narration(
                state=state,
                context=context,
                phase="synthesize",
                cue="final_response",
                next_action="Xếp lại các nguồn theo giá, độ tin cậy, rồi chốt lựa chọn đáng mua nhất.",
                observations=[
                    f"tools_used={len(tools_used)}",
                    f"accumulated_products={len(accumulated_products)}",
                ],
            )
            if allow_authored_fallback:
                narrated_thinking.append(final_narration.summary)
            await _emit_narration(final_narration)

        if event_queue is not None:
            final_chunks = []
            async for chunk in node._llm.astream(messages):
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
                    final_chunks.append(text)
                    await _push_answer_deltas(text)
            final_response = "".join(final_chunks)
            answer_streamed = True
            await _push({"type": "thinking_end", "content": "", "node": "product_search_agent"})
        else:
            final_gen = await node._llm.ainvoke(messages)
            final_response = node._extract_text(final_gen.content)

    if curation_active and accumulated_products and event_queue is not None:
        try:
            current_settings = get_settings()
            max_curated = getattr(current_settings, "curated_product_max_cards", 8)
            llm_tier = getattr(current_settings, "curated_product_llm_tier", "light")

            seen_links: set = set()
            deduped: List[Dict] = []
            for product in accumulated_products:
                link = product.get("link", "")
                if link and link in seen_links:
                    continue
                if link:
                    seen_links.add(link)
                deduped.append(product)

            selection = await curate_with_llm(
                query=query,
                products=deduped,
                max_curated=max_curated,
                llm_tier=llm_tier,
                provider_override=provider_override,
                requested_model=_get_requested_model(state),
            )
            curated_list = []
            if selection and selection.selected:
                for pick in selection.selected:
                    if 0 <= pick.index < len(deduped):
                        product = deduped[pick.index].copy()
                        product["_highlight"] = pick.highlight
                        product["_relevance_score"] = pick.relevance_score
                        curated_list.append(product)

            if not curated_list:
                curated_list = deduped[:max_curated]

            for index, product in enumerate(curated_list):
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
                await _push(
                    {
                        "type": "preview",
                        "content": {
                            "preview_type": "product",
                            "preview_id": preview_id,
                            "title": title[:120],
                            "snippet": (product.get("snippet") or product.get("description", ""))[:150],
                            "url": link,
                            "image_url": product.get("image")
                            or product.get("image_url")
                            or product.get("thumbnail", ""),
                            "metadata": metadata,
                        },
                        "node": "product_search_agent",
                    }
                )
        except Exception as cur_exc:
            logger.warning("[PRODUCT_SEARCH] Post-loop curation failed: %s", cur_exc)

    combined_parts = [
        part
        for part in ((narrated_thinking if allow_authored_fallback else []) + all_thinking)
        if part
    ]
    combined_thinking = "\n\n".join(combined_parts) if combined_parts else None
    return final_response, tools_used, combined_thinking, answer_streamed
