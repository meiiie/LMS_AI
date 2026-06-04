"""
Supervisor Agent - Phase 8.2 + Sprint 71 + Sprint 103

Coordinator agent that routes queries to specialized agents.

Pattern: WiiiRunner supervisor with tool-based handoffs

Sprint 103: LLM-First Routing (SOTA 2026)
- Structured output (_route_structured) is now the PRIMARY and ONLY LLM path
- _route_legacy() deleted, feature flag check removed
- LEARNING_KEYWORDS, LOOKUP_KEYWORDS, WEB_KEYWORDS deleted (~80 keywords)
- _rule_based_route() simplified to 4 guardrail checks (social, personal, domain, default)
- New web_search intent in RoutingDecision for news/legal/maritime search queries
- Off-topic + web_search intent override → DIRECT (prevents false domain_notices)

Sprint 71: SOTA Routing (foundation)
- Chain-of-thought reasoning prompt with few-shot Vietnamese examples
- Confidence-gated structured output (low confidence → rule-based override)
- Routing metadata for observability (intent, confidence, reasoning, method)

**Integrated with agents/ framework for config and tracing.**
"""

import asyncio
import logging
import re
from typing import Optional
from enum import Enum

from app.core.config import settings
from app.engine.messages import Message
from app.engine.messages_adapters import to_openai_dict
from app.core.exceptions import ProviderUnavailableError
from app.core.resilience import retry_on_transient
from app.engine.multi_agent.supervisor_runtime_bindings import (
    LLMPool,
    RoutingDecision,
    StructuredInvokeService,
    build_supervisor_card_prompt,
    build_supervisor_micro_card_prompt,
    build_synthesis_card_prompt,
    extract_thinking_from_response,
    get_domain_registry,
    get_skill_handbook,
    get_synth_settings,
    is_rate_limit_error,
    plan_parallel_targets,
    resolve_visual_intent,
)
from app.engine.multi_agent.agent_config import AgentConfigRegistry
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor_runtime_support import (
    conservative_fast_route_impl,
    get_domain_keywords_impl,
    is_complex_query_impl,
    rule_based_route_impl,
    resolve_house_routing_provider_impl,
    _looks_source_backed_domain_lookup_turn,
    validate_domain_routing_impl,
)
from app.engine.multi_agent.direct_search_synthesis_fallback import (
    build_search_template_fallback,
)
from app.engine.multi_agent.supervisor_surface import (
    _build_recent_turns_for_routing_impl as _build_recent_turns_for_routing,
    _clean_supervisor_visible_reasoning_impl as _clean_supervisor_visible_reasoning,
    _finalize_routing_reasoning_impl as _finalize_routing_reasoning,
    _get_supervisor_stream_queue_impl as _get_supervisor_stream_queue,
    _looks_like_artifact_payload_impl as _looks_like_artifact_payload,
    _push_supervisor_stream_event_impl as _push_supervisor_stream_event,
    _quote_query_for_visible_reasoning_impl as _quote_query_for_visible_reasoning,
    _render_supervisor_visible_reasoning_impl as _render_supervisor_visible_reasoning,
    _summarize_routing_turn_content_impl as _summarize_routing_turn_content,
)
from app.engine.multi_agent.supervisor_hint_runtime import (
    _apply_routing_hint_impl as _apply_routing_hint,
    _looks_clear_learning_turn_impl as _looks_clear_learning_turn,
    _looks_clear_product_intent_impl as _looks_clear_product_intent,
    _looks_clear_social_impl as _looks_clear_social,
    _looks_clear_web_intent_impl as _looks_clear_web_intent,
    _looks_identity_probe_impl as _looks_identity_probe,
    _looks_like_short_natural_question_impl as _looks_like_short_natural_question,
    _looks_like_visual_data_request_impl as _looks_like_visual_data_request,
    _looks_short_capability_probe_impl as _looks_short_capability_probe,
    _needs_code_studio_impl as _needs_code_studio,
    _normalize_router_text_impl as _normalize_router_text,
    _should_use_compact_routing_prompt_impl as _should_use_compact_routing_prompt,
    classify_fast_chatter_turn_impl as classify_fast_chatter_turn,
    is_obvious_social_turn_impl as is_obvious_social_turn,
)
from app.engine.multi_agent.supervisor_contract import (
    CODE_STUDIO_KEYWORDS,
    COMPACT_ROUTING_PROMPT_TEMPLATE,
    CONFIDENCE_THRESHOLD,
    FAST_PRODUCT_KEYWORDS,
    FAST_WEB_KEYWORDS,
    PERSONAL_KEYWORDS,
    ROUTING_PROMPT_TEMPLATE,
    SOCIAL_KEYWORDS,
    SYNTHESIS_PROMPT,
    SYNTHESIS_PROMPT_NATURAL,
    _COMPLEX_QUERY_MIN_LENGTH,
    _FAST_CHATTER_BLOCKERS,
    _IDENTITY_PROBE_MARKERS,
    _MIXED_INTENT_PAIRS,
    _NORMALIZED_SOCIAL_PREFIXES,
    _REACTION_TOKENS,
    _ROUTING_ARTIFACT_MARKERS,
    _SOCIAL_LAUGH_TOKENS,
    _SUPERVISOR_HEARTBEAT_INTERVAL_SEC,
    _VAGUE_BANTER_PHRASES,
)
from app.engine.multi_agent.supervisor_structured_runtime import (
    route_structured_impl,
)

logger = logging.getLogger(__name__)


def _store_capability_context(state: AgentState, capability_context: str) -> None:
    """Keep handbook guidance separate from domain skill content."""
    if capability_context:
        state["capability_context"] = capability_context


class AgentType(str, Enum):
    """Available agent types."""
    RAG = "rag_agent"
    TUTOR = "tutor_agent"
    MEMORY = "memory_agent"
    DIRECT = "direct"
    CODE_STUDIO = "code_studio_agent"
    PRODUCT_SEARCH = "product_search_agent"  # Sprint 148
    COLLEAGUE = "colleague_agent"            # Sprint 215


_TURN_PATH_PREFLIGHT_DIRECT_PATHS = frozenset(
    {
        "weather_lookup",
        "external_connection_status",
        "external_app_action",
    }
)


def _user_role_for_turn_path_preflight(state: AgentState) -> str:
    context = state.get("context") if isinstance(state.get("context"), dict) else {}
    role = str(context.get("user_role") or state.get("role") or "student").strip()
    return role or "student"


def _intent_for_turn_path_preflight(path: str) -> str:
    if path == "weather_lookup":
        return "weather_lookup"
    if path == "external_connection_status":
        return "external_connection_status"
    if path == "external_app_action":
        return "external_app_action"
    return "direct"


def _apply_turn_path_governor_preflight(
    state: AgentState,
    query: str,
) -> str | None:
    """Let typed path governance short-circuit obvious direct tool lanes.

    OpenHuman routes integration work by choosing the toolkit boundary before
    exposing tools. This preflight gives Wiii the same control-plane behavior
    for deterministic direct lanes, while leaving ambiguous learning/RAG turns
    to the existing supervisor.
    """

    try:
        from app.engine.multi_agent.tool_collection import (
            ensure_direct_turn_policy_metadata,
        )

        decision = ensure_direct_turn_policy_metadata(
            query=query,
            state=state,
            user_role=_user_role_for_turn_path_preflight(state),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SUPERVISOR] Turn-path preflight skipped: %s", exc)
        return None

    path = str(getattr(decision, "path", "") or "").strip()
    if path not in _TURN_PATH_PREFLIGHT_DIRECT_PATHS:
        return None

    agent = AgentType.DIRECT.value
    intent = _intent_for_turn_path_preflight(path)
    method = "turn_path_governor_preflight"
    reason = str(getattr(decision, "reason", "") or "typed_turn_path")
    state["routing_metadata"] = {
        "intent": intent,
        "confidence": 1.0,
        "reasoning": _finalize_routing_reasoning(
            raw_reasoning=f"typed turn path selected {path}: {reason}",
            method=method,
            chosen_agent=agent,
            intent=intent,
            query=query,
        ),
        "llm_reasoning": "",
        "method": method,
        "final_agent": agent,
        "turn_path": path,
        "turn_path_reason": reason,
    }
    return agent


# =============================================================================
# Sprint 71: SOTA Routing Prompt with CoT and Few-Shot Examples
# =============================================================================

# Supervisor heartbeat removed — thinking comes from agent nodes, not supervisor.

_VISUAL_LEARNING_CUES = (
    "giai thich",
    "explain",
    "how it works",
    "step by step",
    "in charts",
    "with charts",
    "visual",
)


def _has_uploaded_document_context(context: dict) -> bool:
    document_context = context.get("document_context")
    if not isinstance(document_context, dict):
        return False
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("markdown") or "").strip()
        for item in attachments
    )


class SupervisorAgent:
    """
    Supervisor Agent - Coordinates specialized agents.

    Sprint 71: SOTA routing with intent classification, confidence gate,
    and chain-of-thought reasoning.

    Responsibilities:
    - Analyze query intent (lookup/learning/personal/social)
    - Route to appropriate agent with confidence scoring
    - Synthesize final response
    - Quality control
    """

    def __init__(self):
        """Initialize Supervisor Agent."""
        self._llm = None
        self._init_llm()
        logger.info("SupervisorAgent initialized")

    def _init_llm(self):
        """Initialize default LLM from shared pool for routing decisions."""
        try:
            # Sprint 69: Use AgentConfigRegistry for per-node LLM config
            self._llm = AgentConfigRegistry.get_llm("supervisor")
            logger.info("SupervisorAgent initialized (via AgentConfigRegistry)")
        except Exception as e:
            logger.error("Failed to initialize Supervisor LLM: %s", e)
            self._llm = None

    def _get_llm_for_state(self, state: AgentState):
        """Resolve the house routing model instead of the user-selected generator.

        Wiii's supervisor is the conductor of the conversation, so we keep it on
        the admin-managed routing profile to preserve routing quality, visible
        reasoning tone, and house identity.
        """
        try:
            provider_override = self._resolve_house_routing_provider(state)
            if provider_override:
                state["_house_routing_provider"] = provider_override
                return AgentConfigRegistry.get_llm(
                    "supervisor",
                    provider_override=provider_override,
                    strict_provider_pin=False,
                )
            return AgentConfigRegistry.get_llm("supervisor")
        except Exception as e:
            logger.debug("Falling back to cached Supervisor LLM: %s", e)
            return self._llm

    def _resolve_house_routing_provider(self, state: AgentState) -> Optional[str]:
        return resolve_house_routing_provider_impl(
            state,
            settings_obj=settings,
            logger=logger,
        )

    async def route(self, state: AgentState) -> str:
        """
        Determine which agent should handle the query.

        Sprint 71: Returns agent name and stores routing_metadata in state.

        Args:
            state: Current agent state

        Returns:
            Agent name to route to
        """
        query = state.get("query", "")
        context = state.get("context", {})
        domain_config = state.get("domain_config", {})

        if isinstance(context, dict) and _has_uploaded_document_context(context):
            agent = AgentType.DIRECT.value
            intent = "uploaded_file_context"
            method = "deterministic_document_context_guard"
            state["routing_metadata"] = {
                "intent": intent,
                "confidence": 1.0,
                "reasoning": _finalize_routing_reasoning(
                    raw_reasoning=(
                        "user attached a per-turn parsed file; use uploaded file context "
                        "before broad RAG corpus retrieval"
                    ),
                    method=method,
                    chosen_agent=agent,
                    intent=intent,
                    query=query,
                ),
                "llm_reasoning": "",
                "method": method,
                "final_agent": agent,
            }
            return agent

        image_guard_intent = ""
        image_guard_reason = ""
        if isinstance(context, dict):
            if context.get("image_input_error"):
                image_guard_intent = "image_input_unavailable"
                image_guard_reason = "image attached but vision runtime is unavailable"
            elif context.get("images"):
                image_guard_intent = "image_input"
                image_guard_reason = "image attached and should be handled by direct vision lane"

        if image_guard_intent:
            agent = AgentType.DIRECT.value
            method = "deterministic_image_input_guard"
            state["routing_metadata"] = {
                "intent": image_guard_intent,
                "confidence": 1.0,
                "reasoning": _finalize_routing_reasoning(
                    raw_reasoning=image_guard_reason,
                    method=method,
                    chosen_agent=agent,
                    intent=image_guard_intent,
                    query=query,
                ),
                "llm_reasoning": "",
                "method": method,
                "final_agent": agent,
            }
            return agent

        _apply_routing_hint(state, query)
        turn_path_agent = _apply_turn_path_governor_preflight(state, query)
        if turn_path_agent:
            return turn_path_agent

        normalized_query = _normalize_router_text(query)
        if _looks_source_backed_domain_lookup_turn(normalized_query):
            agent = AgentType.RAG.value
            intent = "lookup"
            method = "deterministic_source_backed_lookup_guard"
            state["routing_metadata"] = {
                "intent": intent,
                "confidence": 1.0,
                "reasoning": _finalize_routing_reasoning(
                    raw_reasoning=(
                        "user asked for a source-backed domain answer; use RAG "
                        "before direct model synthesis so citations can surface"
                    ),
                    method=method,
                    chosen_agent=agent,
                    intent=intent,
                    query=query,
                ),
                "llm_reasoning": "",
                "method": method,
                "final_agent": agent,
            }
            return agent

        routing_hint = state.get("_routing_hint") or {}
        if (
            isinstance(routing_hint, dict)
            and routing_hint.get("kind") == "fast_chatter"
            and routing_hint.get("shape") == "social_status"
        ):
            agent = AgentType.DIRECT.value
            intent = str(routing_hint.get("intent") or "social")
            method = "always_on_social_status_fast_path"
            state["routing_metadata"] = {
                "intent": intent,
                "confidence": 1.0,
                "reasoning": _finalize_routing_reasoning(
                    raw_reasoning="obvious short social status update",
                    method=method,
                    chosen_agent=agent,
                    intent=intent,
                    query=query,
                ),
                "llm_reasoning": "",
                "method": method,
                "final_agent": agent,
            }
            return agent
        if (
            settings.enable_conservative_fast_routing
            and (not routing_hint or routing_hint.get("kind") == "fast_chatter")
        ):
            fast_result = self._conservative_fast_route(query, context, domain_config)
            if fast_result is not None:
                agent, intent, confidence, reasoning = fast_result
                method = "conservative_fast_path"
                state["routing_metadata"] = {
                    "intent": intent,
                    "confidence": confidence,
                    "reasoning": _finalize_routing_reasoning(
                        raw_reasoning=reasoning,
                        method=method,
                        chosen_agent=agent,
                        intent=intent,
                        query=query,
                    ),
                    "llm_reasoning": "",
                    "method": method,
                    "final_agent": agent,
                }
                return agent

        # Per-request provider-aware LLM resolution
        llm = self._get_llm_for_state(state)

        if not llm:
            result = self._rule_based_route(query, domain_config)
            state["routing_metadata"] = {
                "intent": "unknown",
                "confidence": 1.0,
                "reasoning": "rule-based (no LLM)",
                "method": "rule_based",
            }
            return result

        # Build domain-aware routing prompt
        domain_name = domain_config.get("domain_name", "AI")
        rag_desc = domain_config.get("rag_description", "Tra cứu quy định, luật, thủ tục")
        tutor_desc = domain_config.get("tutor_description", "Giải thích, dạy học, quiz")

        # Issue #206: bound the sync structured-route LLM call so a stalled
        # provider does not blow the conversation budget. SSE V3 path observes
        # ~2.6s for the same prompt; we cap sync at ~10s and fall back to
        # `_rule_based_route()` if exceeded.
        from app.engine.multi_agent.lane_timeout_policy import (
            resolve_supervisor_route_timeout_seconds_impl,
        )
        from app.engine.multi_agent.runner import _record_runtime_timeline_entry

        route_timeout_s = resolve_supervisor_route_timeout_seconds_impl(
            state=state,
            settings_obj=settings,
        )

        try:
            # Sprint 103: Always use structured routing (no feature flag check)
            return await asyncio.wait_for(
                self._route_structured(
                    query, context, domain_name, rag_desc, tutor_desc,
                    domain_config, state, llm=llm,
                ),
                timeout=route_timeout_s,
            )

        except asyncio.TimeoutError:
            logger.warning(
                "LLM routing exceeded %.1fs sync bound; falling back to rules",
                route_timeout_s,
            )
            try:
                _record_runtime_timeline_entry(
                    state,
                    {
                        "stage": "supervisor.route_timeout",
                        "elapsed_ms": int(route_timeout_s * 1000),
                        "reason": "structured_route_sync_bound",
                    },
                )
            except Exception:
                pass  # timeline emit is best-effort, never blocks routing
            result = self._rule_based_route(query, domain_config)
            state["routing_metadata"] = {
                "intent": "unknown",
                "confidence": 1.0,
                "reasoning": (
                    f"rule-based fallback (sync route timeout > {route_timeout_s:.1f}s)"
                ),
                "method": "rule_based_timeout",
                "final_agent": result,
                "route_timeout_seconds": route_timeout_s,
            }
            return result

        except ProviderUnavailableError as e:
            logger.warning(
                "LLM routing provider unavailable; falling back to rules: %s",
                e,
            )
            result = self._rule_based_route(query, domain_config)
            state["routing_metadata"] = {
                "intent": "unknown",
                "confidence": 1.0,
                "reasoning": "rule-based fallback (routing provider unavailable)",
                "method": "rule_based",
                "provider": getattr(e, "provider", ""),
                "reason_code": getattr(e, "reason_code", ""),
                "final_agent": result,
            }
            return result
        except Exception as e:
            logger.warning("LLM routing failed: %s", e)
            result = self._rule_based_route(query, domain_config)
            state["routing_metadata"] = {
                "intent": "unknown",
                "confidence": 1.0,
                "reasoning": "rule-based fallback (LLM routing unavailable)",
                "method": "rule_based",
                "final_agent": result,
            }
            return result

    @retry_on_transient()
    async def _route_structured(self, query: str, context: dict, domain_name: str,
                                 rag_desc: str, tutor_desc: str, domain_config: dict,
                                 state: AgentState, *, llm=None) -> str:
        """Route using structured output with CoT and confidence gate (Sprint 71)."""

        return await route_structured_impl(
            query=query,
            context=context,
            domain_name=domain_name,
            rag_desc=rag_desc,
            tutor_desc=tutor_desc,
            domain_config=domain_config,
            state=state,
            llm=llm,
            default_llm=self._llm,
            structured_invoke_service_cls=StructuredInvokeService,
            routing_decision_schema=RoutingDecision,
            build_supervisor_card_prompt_fn=build_supervisor_card_prompt,
            build_supervisor_micro_card_prompt_fn=build_supervisor_micro_card_prompt,
            resolve_visual_intent_fn=resolve_visual_intent,
            should_use_compact_routing_prompt_fn=_should_use_compact_routing_prompt,
            build_recent_turns_for_routing_fn=_build_recent_turns_for_routing,
            needs_code_studio_fn=_needs_code_studio,
            looks_like_visual_data_request_fn=_looks_like_visual_data_request,
            finalize_routing_reasoning_fn=_finalize_routing_reasoning,
            rule_based_route_fn=self._rule_based_route,
            validate_domain_routing_fn=self._validate_domain_routing,
            agent_type_enum=AgentType,
            compact_routing_prompt_template=COMPACT_ROUTING_PROMPT_TEMPLATE,
            routing_prompt_template=ROUTING_PROMPT_TEMPLATE,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            settings_obj=settings,
            logger_obj=logger,
        )

    def _conservative_fast_route(self, query: str, context: dict, domain_config: dict) -> Optional[tuple[str, str, float, str]]:
        return conservative_fast_route_impl(
            query=query,
            normalize_router_text_fn=_normalize_router_text,
            classify_fast_chatter_turn_fn=classify_fast_chatter_turn,
            looks_clear_social_fn=_looks_clear_social,
            direct_agent_name=AgentType.DIRECT.value,
            memory_agent_name=AgentType.MEMORY.value,
            rag_agent_name=AgentType.RAG.value,
            code_studio_agent_name=AgentType.CODE_STUDIO.value,
            needs_code_studio_fn=_needs_code_studio,
        )

    def _validate_domain_routing(self, query: str, chosen_agent: str,
                                   domain_config: dict = None, context: dict | None = None) -> str:
        return validate_domain_routing_impl(
            query=query,
            chosen_agent=chosen_agent,
            domain_config=domain_config,
            context=context,
            rag_agent_name=AgentType.RAG.value,
            tutor_agent_name=AgentType.TUTOR.value,
            direct_agent_name=AgentType.DIRECT.value,
            get_domain_keywords_fn=self._get_domain_keywords,
            logger=logger,
        )

    def _rule_based_route(self, query: str, domain_config: dict = None) -> str:
        return rule_based_route_impl(
            query=query,
            domain_config=domain_config,
            normalize_router_text_fn=_normalize_router_text,
            is_obvious_social_turn_fn=is_obvious_social_turn,
            needs_code_studio_fn=_needs_code_studio,
            get_domain_keywords_fn=self._get_domain_keywords,
            looks_clear_learning_turn_fn=_looks_clear_learning_turn,
            personal_keywords=PERSONAL_KEYWORDS,
            direct_agent_name=AgentType.DIRECT.value,
            memory_agent_name=AgentType.MEMORY.value,
            code_studio_agent_name=AgentType.CODE_STUDIO.value,
            rag_agent_name=AgentType.RAG.value,
            tutor_agent_name=AgentType.TUTOR.value,
        )

    def _get_domain_keywords(self, domain_config: dict = None) -> list:
        return get_domain_keywords_impl(
            domain_config=domain_config,
            logger=logger,
            settings_obj=settings,
        )

    async def synthesize(self, state: AgentState) -> str:
        """
        Synthesize final response from agent outputs.

        Args:
            state: State with agent outputs

        Returns:
            Final synthesized response
        """
        outputs = state.get("agent_outputs", {}) or {}
        text_outputs = {
            key: value.strip()
            for key, value in outputs.items()
            if isinstance(value, str) and value.strip()
        }

        # If only one output, return it directly
        if len(text_outputs) == 1:
            return list(text_outputs.values())[0]

        # If no outputs, preserve evidence gathered by a tool round before
        # falling back to a generic apology. This catches cases where an agent
        # node failed after search succeeded, leaving tool_call_events in state.
        if not text_outputs:
            tool_events = state.get("tool_call_events") or []
            if tool_events:
                try:
                    template_response = build_search_template_fallback(
                        query=str(state.get("query") or ""),
                        tool_call_events=list(tool_events),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[SYNTHESIZER] Search template salvage failed: %s",
                        exc,
                    )
                    template_response = ""
                if template_response:
                    logger.warning(
                        "[SYNTHESIZER] No agent output, salvaged %d chars from tool_call_events",
                        len(template_response),
                    )
                    return template_response

            existing_final = str(state.get("final_response") or "").strip()
            if existing_final:
                return existing_final

            return "Xin lỗi, mình chưa xử lý được yêu cầu này nha~ (˶˃ ᵕ ˂˶)"

        # Synthesize multiple outputs
        llm = self._get_llm_for_state(state)
        if not llm:
            # Simple concatenation
            return "\n\n".join(text_outputs.values())

        try:
            output_text = "\n---\n".join([
                f"[{k}]: {v}" for k, v in text_outputs.items()
            ])

            # Sprint 203: Use natural prompt when enabled (no word limits)
            try:
                _synth_s = get_synth_settings()
                _synth_prompt = SYNTHESIS_PROMPT_NATURAL if getattr(_synth_s, "enable_natural_conversation", False) is True else SYNTHESIS_PROMPT
            except Exception as e:
                logger.debug("Natural conversation config unavailable: %s", e)
                _synth_prompt = SYNTHESIS_PROMPT

            # Sprint 222: Include host context in synthesis
            _host_prompt = state.get("host_context_prompt", "")
            _host_suffix = f"\n\nHost Context:\n{_host_prompt}" if _host_prompt else ""
            _host_capabilities_prompt = state.get("host_capabilities_prompt", "")
            _host_capabilities_suffix = (
                f"\n\nHost Capabilities:\n{_host_capabilities_prompt}"
                if _host_capabilities_prompt else ""
            )
            _operator_prompt = state.get("operator_context_prompt", "")
            _operator_suffix = f"\n\nOperator Context:\n{_operator_prompt}" if _operator_prompt else ""
            _living_prompt = state.get("living_context_prompt", "")
            _living_suffix = f"\n\nLiving Context:\n{_living_prompt}" if _living_prompt else ""
            _widget_feedback_prompt = state.get("widget_feedback_prompt", "")
            _widget_suffix = (
                f"\n\nWidget Feedback Context:\n{_widget_feedback_prompt}"
                if _widget_feedback_prompt else ""
            )

            messages = [
                to_openai_dict(Message(role="system", content=build_synthesis_card_prompt())),
                to_openai_dict(Message(
                    role="user",
                    content=_synth_prompt.format(
                        query=state.get("query", ""),
                        outputs=output_text,
                    ) + _host_suffix + _host_capabilities_suffix + _operator_suffix + _living_suffix + _widget_suffix,
                )),
            ]

            try:
                response = await llm.ainvoke(messages)
            except Exception as _synth_exc:
                if not is_rate_limit_error(_synth_exc):
                    raise
                _fb = LLMPool.get_fallback("moderate")
                if _fb is None:
                    raise
                logger.warning("[SUPERVISOR] Rate-limited, using fallback for synthesis")
                response = await _fb.ainvoke(messages)

            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            text_content, _ = extract_thinking_from_response(response.content)
            return text_content.strip()

        except Exception as e:
            logger.warning("Synthesis failed: %s", e)
            return list(text_outputs.values())[0]  # Return first output

    def _is_complex_query(self, query: str, routing_metadata: dict) -> bool:
        return is_complex_query_impl(
            query=query,
            routing_metadata=routing_metadata,
            min_length=_COMPLEX_QUERY_MIN_LENGTH,
            mixed_intent_pairs=_MIXED_INTENT_PAIRS,
        )

    async def process(self, state: AgentState) -> AgentState:
        """
        Process state as supervisor node.

        Args:
            state: Current state

        Returns:
            Updated state with routing decision, skill context, and routing metadata
        """
        event_queue = _get_supervisor_stream_queue(state)

        # Skill Activation: match query against domain skills (progressive disclosure)
        domain_id = state.get("domain_id", "")
        query = state.get("query", "")
        if query:
            _apply_routing_hint(state, query)
        if domain_id and query:
            try:
                registry = get_domain_registry()
                domain_plugin = registry.get(domain_id)
                if domain_plugin:
                    matched_skills = domain_plugin.match_skills(query)
                    if matched_skills:
                        skill = matched_skills[0]  # Use top match
                        skill_content = domain_plugin.activate_skill(skill.id)
                        if skill_content:
                            state["skill_context"] = skill_content
                            logger.info("[SUPERVISOR] Skill activated: %s (%d chars)", skill.id, len(skill_content))
            except Exception as e:
                logger.debug("Skill activation skipped: %s", e)

        if query:
            try:
                capability_context = get_skill_handbook().summarize_for_query(query, max_entries=3)
                if capability_context:
                    _store_capability_context(state, capability_context)
            except Exception as e:
                logger.debug("Capability handbook summary skipped: %s", e)

        # Supervisor does NOT push thinking bus events (matches production GitHub code).
        # All visible thinking comes from agent nodes via astream() + narrator.render().

        try:
            # Route to appropriate agent (also sets routing_metadata in state)
            next_agent = await self.route(state)

            try:
                routed_intent = (state.get("routing_metadata") or {}).get("intent")
                capability_context = get_skill_handbook().summarize_for_query(
                        query,
                    intent=routed_intent,
                    max_entries=3,
                )
                if capability_context:
                    _store_capability_context(state, capability_context)
            except Exception as e:
                logger.debug("Post-routing capability handbook summary skipped: %s", e)

            # Sprint 163 Phase 4: Parallel dispatch for complex queries
            try:
                if (
                    settings.enable_subagent_architecture
                    and next_agent in (
                        AgentType.RAG.value,
                        AgentType.TUTOR.value,
                        AgentType.PRODUCT_SEARCH.value,
                    )
                    and self._is_complex_query(query, state.get("routing_metadata") or {})
                ):
                    planned_targets = plan_parallel_targets(
                        query,
                        next_agent,
                        intent=(state.get("routing_metadata") or {}).get("intent"),
                        max_targets=2,
                    )
                    if len(planned_targets) > 1:
                        logger.info(
                            "[SUPERVISOR] Complex query detected -> parallel_dispatch %s",
                            planned_targets,
                        )
                        next_agent = "parallel_dispatch"
                        state["_parallel_targets"] = planned_targets
            except Exception as e:
                logger.debug("Parallel dispatch check failed: %s", e)

            state["next_agent"] = next_agent
            state["current_agent"] = "supervisor"

            metadata = state.get("routing_metadata", {}) or {}
            logger.info(
                "[SUPERVISOR] Routing to: %s (method=%s, intent=%s, conf=%.2f)",
                next_agent,
                metadata.get("method", "unknown"),
                metadata.get("intent", "unknown"),
                metadata.get("confidence", 0.0),
            )

            return state
        except Exception:
            raise

    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._llm is not None


# Singleton
_supervisor: Optional[SupervisorAgent] = None

def get_supervisor_agent() -> SupervisorAgent:
    """Get or create SupervisorAgent singleton."""
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorAgent()
    return _supervisor
