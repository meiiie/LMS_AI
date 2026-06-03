"""Structured routing runtime for SupervisorAgent."""

from __future__ import annotations

from app.engine.messages import Message
from app.engine.messages_adapters import to_openai_dict
from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.supervisor_runtime_support import (
    _looks_wiii_capability_inventory_turn,
)


_SELFHOOD_FOLLOWUP_QUERY_MARKERS: tuple[str, ...] = (
    "bong",
    "the wiii lab",
    "dem mua",
    "thang gieng",
)

_SELFHOOD_FOLLOWUP_CONTEXT_MARKERS: tuple[str, ...] = (
    "wiii duoc sinh ra",
    "the wiii lab",
    "bong",
    "dem mua",
    "thang gieng",
    "nguon goc",
    "ra doi",
)

def _looks_selfhood_followup_from_context(*, query: str, context_text: str) -> bool:
    normalized_query = _normalize_for_intent(query)
    normalized_context = _normalize_for_intent(context_text)
    if not normalized_query or not normalized_context:
        return False
    tokens = [token for token in normalized_query.split() if token]
    if not tokens or len(tokens) > 12:
        return False
    has_query_signal = any(marker in normalized_query for marker in _SELFHOOD_FOLLOWUP_QUERY_MARKERS)
    has_context_signal = any(marker in normalized_context for marker in _SELFHOOD_FOLLOWUP_CONTEXT_MARKERS)
    return has_query_signal and has_context_signal


async def route_structured_impl(
    *,
    query: str,
    context: dict,
    domain_name: str,
    rag_desc: str,
    tutor_desc: str,
    domain_config: dict,
    state,
    llm,
    default_llm,
    structured_invoke_service_cls,
    routing_decision_schema,
    build_supervisor_card_prompt_fn,
    build_supervisor_micro_card_prompt_fn,
    resolve_visual_intent_fn,
    should_use_compact_routing_prompt_fn,
    build_recent_turns_for_routing_fn,
    needs_code_studio_fn,
    looks_like_visual_data_request_fn,
    finalize_routing_reasoning_fn,
    rule_based_route_fn,
    validate_domain_routing_fn,
    agent_type_enum,
    compact_routing_prompt_template: str,
    routing_prompt_template: str,
    confidence_threshold: float,
    settings_obj,
    logger_obj,
):
    """Route using structured output with confidence gates and overrides."""
    runtime_llm = llm or default_llm

    routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
    fast_chatter_hint = None
    if routing_hint.get("kind") == "fast_chatter":
        fast_chatter_hint = (
            str(routing_hint.get("intent") or ""),
            str(routing_hint.get("shape") or ""),
        )
    use_compact_prompt = should_use_compact_routing_prompt_fn(query, fast_chatter_hint)

    lc_messages = (context or {}).get("langchain_messages", [])
    conv_summary = (context or {}).get("conversation_summary", "")
    if lc_messages:
        turn_window = 2 if use_compact_prompt else 6
        turn_limit = 88 if use_compact_prompt else 200
        recent_turns = build_recent_turns_for_routing_fn(
            lc_messages,
            turn_window=turn_window,
            turn_limit=turn_limit,
        )
        context_str = f"Recent conversation:\n{recent_turns}"
        if conv_summary:
            summary_limit = 96 if use_compact_prompt else 300
            context_str = (
                f"Summary of earlier conversation:\n{conv_summary[:summary_limit]}"
                f"\n\n{context_str}"
            )
    else:
        context_str = str(context)[:160 if use_compact_prompt else 500]

    capability_context = state.get("capability_context", "")
    if capability_context:
        cap_limit = 120 if use_compact_prompt else len(capability_context)
        context_str = f"{context_str}\n\n{capability_context[:cap_limit]}"

    if not routing_hint and _looks_selfhood_followup_from_context(query=query, context_text=context_str):
        routing_hint = {"kind": "selfhood_followup", "intent": "selfhood", "shape": "lore_followup"}
        state["_routing_hint"] = routing_hint

    user_role = (context or {}).get("user_role") or (context or {}).get("role") or "student"

    routing_hints: list[str] = []
    if fast_chatter_hint is not None:
        routing_hints.append(f"short_{fast_chatter_hint[1]} -> intent={fast_chatter_hint[0]}")
    if routing_hint.get("kind") == "identity_probe":
        routing_hints.append("identity_probe -> intent=selfhood")
    if routing_hint.get("kind") == "selfhood_followup":
        routing_hints.append("selfhood_followup -> intent=selfhood")
    if routing_hint.get("kind") == "capability_probe":
        routing_hints.append("short_capability_probe")
    if needs_code_studio_fn(query):
        routing_hints.append("code_studio_signal")
    house_provider = state.get("_house_routing_provider")
    if house_provider:
        routing_hints.append(f"house_provider={house_provider}")
    routing_hints_text = ", ".join(routing_hints) or "none"

    if use_compact_prompt:
        messages = [
            to_openai_dict(Message(role="system", content=build_supervisor_micro_card_prompt_fn())),
            to_openai_dict(Message(
                role="user",
                content=compact_routing_prompt_template.format(
                    query=query,
                    context=context_str,
                    routing_hints=routing_hints_text,
                ),
            )),
        ]
    else:
        messages = [
            to_openai_dict(Message(role="system", content=build_supervisor_card_prompt_fn())),
            to_openai_dict(Message(
                role="system",
                content=(
                    "You are a query router. Analyze the query step by step, classify intent, "
                    "choose agent, and provide confidence."
                ),
            )),
            to_openai_dict(Message(
                role="system",
                content=(
                    "Visual policy: explanatory charts, comparisons, process diagrams, architecture diagrams, "
                    "and concept visuals should stay on DIRECT or TUTOR so those agents can call "
                    "article-figure/chart tools. Reserve CODE_STUDIO_AGENT for code execution, app/widget "
                    "generation, simulations, artifacts, files, or browser sandbox work."
                ),
            )),
            to_openai_dict(Message(
                role="user",
                content=routing_prompt_template.format(
                    domain_name=domain_name,
                    rag_description=rag_desc,
                    tutor_description=tutor_desc,
                    scope_hint=domain_config.get("scope_description", ""),
                    query=query,
                    context=context_str,
                    user_role=user_role,
                ),
            )),
        ]

    result = await structured_invoke_service_cls.ainvoke(
        llm=runtime_llm,
        schema=routing_decision_schema,
        payload=messages,
        tier="light",
        provider=None,
    )

    agent_map = {
        "RAG_AGENT": agent_type_enum.RAG.value,
        "TUTOR_AGENT": agent_type_enum.TUTOR.value,
        "MEMORY_AGENT": agent_type_enum.MEMORY.value,
        "DIRECT": agent_type_enum.DIRECT.value,
        "CODE_STUDIO_AGENT": agent_type_enum.CODE_STUDIO.value,
        "PRODUCT_SEARCH_AGENT": agent_type_enum.PRODUCT_SEARCH.value,
        "COLLEAGUE_AGENT": agent_type_enum.COLLEAGUE.value,
    }

    chosen_agent = agent_map.get(result.agent, agent_type_enum.DIRECT.value)
    method = "structured"
    visual_decision = resolve_visual_intent_fn(query)
    is_wiii_capability_inventory = _looks_wiii_capability_inventory_turn(
        _normalize_for_intent(query)
    )

    logger_obj.info(
        "[SUPERVISOR] CoT: %s -> %s (conf=%.2f, intent=%s)",
        result.reasoning,
        result.agent,
        result.confidence,
        result.intent,
    )

    if result.confidence < confidence_threshold:
        rule_result = rule_based_route_fn(query, domain_config)
        if rule_result != chosen_agent:
            logger_obj.info(
                "[SUPERVISOR] Low confidence override: %s -> %s (conf=%.2f)",
                result.agent,
                rule_result,
                result.confidence,
            )
            chosen_agent = rule_result
            method = "structured+rule_override"

    if result.intent in ("off_topic", "web_search") and chosen_agent in (
        agent_type_enum.RAG.value,
        agent_type_enum.TUTOR.value,
    ):
        logger_obj.info(
            "[SUPERVISOR] Intent override (%s): %s -> direct",
            result.intent,
            chosen_agent,
        )
        chosen_agent = agent_type_enum.DIRECT.value
        method = "structured+intent_override"

    if result.intent == "code_execution" and chosen_agent != agent_type_enum.CODE_STUDIO.value:
        logger_obj.info(
            "[SUPERVISOR] Intent override (%s): %s -> code_studio_agent",
            result.intent,
            chosen_agent,
        )
        chosen_agent = agent_type_enum.CODE_STUDIO.value
        method = "structured+intent_override"

    resolved_intent = result.intent

    if routing_hint.get("kind") == "identity_probe":
        resolved_intent = "selfhood"
        if chosen_agent != agent_type_enum.DIRECT.value:
            logger_obj.info("[SUPERVISOR] Identity override: %s -> direct", chosen_agent)
            chosen_agent = agent_type_enum.DIRECT.value
            method = "structured+identity_override"

    if routing_hint.get("kind") == "selfhood_followup":
        resolved_intent = "selfhood"
        if chosen_agent != agent_type_enum.DIRECT.value or result.intent not in {"identity", "selfhood"}:
            logger_obj.info("[SUPERVISOR] Selfhood follow-up override: %s/%s -> direct", chosen_agent, result.intent)
            chosen_agent = agent_type_enum.DIRECT.value
            method = "structured+selfhood_followup_override"

    if is_wiii_capability_inventory:
        resolved_intent = "off_topic"
        if chosen_agent != agent_type_enum.DIRECT.value:
            logger_obj.info("[SUPERVISOR] Capability inventory override: %s -> direct", chosen_agent)
            chosen_agent = agent_type_enum.DIRECT.value
            method = "structured+capability_inventory_override"

    if (
        routing_hint.get("kind") == "visual_followup"
        and routing_hint.get("intent") == "learning"
        and chosen_agent == agent_type_enum.DIRECT.value
    ):
        logger_obj.info("[SUPERVISOR] Visual follow-up override: direct -> tutor_agent")
        chosen_agent = agent_type_enum.TUTOR.value
        method = "structured+visual_followup_override"

    if needs_code_studio_fn(query) and chosen_agent in (
        agent_type_enum.DIRECT.value,
        agent_type_enum.RAG.value,
        agent_type_enum.TUTOR.value,
    ) and not is_wiii_capability_inventory:
        logger_obj.info("[SUPERVISOR] Capability override: %s -> code_studio_agent", chosen_agent)
        chosen_agent = agent_type_enum.CODE_STUDIO.value
        method = "structured+capability_override"

    if (
        (
            (
                visual_decision.presentation_intent in {"article_figure", "chart_runtime"}
                and not needs_code_studio_fn(query)
            )
            or looks_like_visual_data_request_fn(query)
        )
        and chosen_agent != agent_type_enum.DIRECT.value
        and result.intent not in ("learning", "lookup")
    ):
        logger_obj.info(
            "[SUPERVISOR] Visual lane override: %s -> direct (%s)",
            chosen_agent,
            visual_decision.presentation_intent or "visual_data_request",
        )
        chosen_agent = agent_type_enum.DIRECT.value
        method = "structured+visual_lane_override"

    if (
        chosen_agent == agent_type_enum.TUTOR.value
        and (visual_decision.presentation_intent == "chart_runtime" or visual_decision.force_tool)
        and result.intent not in ("learning", "lookup")
    ):
        logger_obj.info(
            "[SUPERVISOR] Visual override: tutor -> direct (force_tool=%s, intent=%s)",
            visual_decision.force_tool,
            visual_decision.presentation_intent,
        )
        chosen_agent = agent_type_enum.DIRECT.value
        method = "structured+visual_override"

    if chosen_agent == agent_type_enum.PRODUCT_SEARCH.value and not settings_obj.enable_product_search:
        logger_obj.info("[SUPERVISOR] Product search disabled, falling back to DIRECT")
        chosen_agent = agent_type_enum.DIRECT.value
        method = "structured+product_search_disabled"

    if chosen_agent == agent_type_enum.COLLEAGUE.value:
        if (
            not settings_obj.enable_cross_soul_query
            or user_role != "admin"
            or not settings_obj.enable_soul_bridge
        ):
            logger_obj.info(
                "[SUPERVISOR] Colleague query denied (role=%s, cross_soul=%s, bridge=%s), falling back to DIRECT",
                user_role,
                settings_obj.enable_cross_soul_query,
                settings_obj.enable_soul_bridge,
            )
            chosen_agent = agent_type_enum.DIRECT.value
            method = "structured+colleague_denied"

    pre_validation = chosen_agent
    chosen_agent = validate_domain_routing_fn(
        query,
        chosen_agent,
        domain_config,
        context=context,
    )
    if chosen_agent != pre_validation:
        method = "structured+domain_validation"

    state["routing_metadata"] = {
        "intent": resolved_intent,
        "confidence": result.confidence,
        "reasoning": finalize_routing_reasoning_fn(
            raw_reasoning=result.reasoning,
            method=method,
            chosen_agent=chosen_agent,
            intent=resolved_intent,
            query=query,
        ),
        "llm_reasoning": result.reasoning,
        "method": method,
        "final_agent": chosen_agent,
        "house_provider": house_provider,
        "compact_prompt": use_compact_prompt,
    }

    return chosen_agent
