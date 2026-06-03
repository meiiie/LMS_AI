"""Low-level graph support helpers that do not need to live in graph orchestration."""

from __future__ import annotations

import logging
from typing import Literal, Optional

from app.core.config import settings
from app.engine.multi_agent.state import AgentState

logger = logging.getLogger(__name__)

# Sprint 79: Generate session summary at these message milestones.
_SUMMARY_MILESTONES = {6, 12, 20, 30}


def _build_turn_local_state_defaults(context: Optional[dict] = None) -> dict:
    """Reset request-local fields that must never bleed across checkpointed turns."""
    ctx = context or {}
    return {
        "rag_output": "",
        "tutor_output": "",
        "memory_output": "",
        "tools_used": [],
        "reasoning_trace": None,
        "thinking_content": None,
        "thinking": None,
        "_public_thinking_fragments": [],
        "_trace_id": None,
        "guardian_passed": None,
        "skill_context": None,
        "capability_context": None,
        "tool_call_events": [],
        "_answer_streamed_via_bus": False,
        "_execution_provider": None,
        "_execution_model": None,
        "_execution_tier": None,
        "_llm_failover_events": [],
        "domain_notice": None,
        "evidence_images": [],
        "conversation_phase": ctx.get("conversation_phase"),
        "host_context": ctx.get("host_context"),
        "host_capabilities": ctx.get("host_capabilities"),
        "host_action_feedback": ctx.get("host_action_feedback"),
        "host_context_prompt": None,
        "host_capabilities_prompt": None,
        "host_session": None,
        "host_session_prompt": None,
        "operator_session": None,
        "operator_context_prompt": None,
        "document_context_prompt": None,
        "living_context_prompt": None,
        "memory_block_context": None,
        "reasoning_policy": None,
        "subagent_reports": [],
        "_aggregator_action": None,
        "_aggregator_reasoning": None,
        "_reroute_count": 0,
        "_parallel_targets": [],
    }


def _build_recent_conversation_context(state: AgentState) -> str:
    """Build a compact conversation context for narrator prompts."""
    ctx = state.get("context", {}) or {}
    summary = str(ctx.get("conversation_summary", "") or "").strip()
    if summary:
        return summary
    return ""


def route_decision(state: AgentState) -> str:
    """Determine next agent based on supervisor decision."""
    next_agent = state.get("next_agent", "rag_agent")
    valid_routes = {
        "rag_agent",
        "tutor_agent",
        "memory_agent",
        "direct",
        "code_studio_agent",
        "product_search_agent",
        "parallel_dispatch",
        "colleague_agent",
    }
    if next_agent in valid_routes:
        return next_agent
    return "direct"


def _build_domain_config(domain_id: str) -> dict:
    """Build domain config dict for injection into AgentState."""
    try:
        from app.domains.registry import get_domain_registry

        registry = get_domain_registry()
        domain = registry.get(domain_id)
        if domain:
            config = domain.get_config()
            routing = domain.get_routing_config()
            return {
                "domain_name": config.name,
                "domain_id": config.id,
                "routing_keywords": config.routing_keywords,
                "rag_description": routing.get("rag_description", ""),
                "tutor_description": routing.get("tutor_description", ""),
                "scope_description": routing.get("scope_description", ""),
            }
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("Domain config fallback: %s", exc)

    return {
        "domain_name": settings.app_name,
        "domain_id": settings.default_domain,
        "routing_keywords": [],
        "rag_description": "Tra cứu kiến thức, quy định, luật, thủ tục trong cơ sở dữ liệu",
        "tutor_description": "Giải thích, dạy học, quiz về kiến thức chuyên ngành",
        "scope_description": "",
    }


def _get_domain_greetings(domain_id: str) -> dict:
    """Get greeting responses from the active domain plugin, with safe fallback."""
    try:
        from app.domains.registry import get_domain_registry

        registry = get_domain_registry()
        domain = registry.get(domain_id)
        if domain:
            return domain.get_greetings()
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("Domain greetings fallback: %s", exc)

    name = settings.app_name
    return {
        "xin chào": f"Xin chào! Tôi là {name}. Tôi có thể giúp gì cho bạn?",
        "hello": f"Hello! I'm {name}. How can I help you?",
        "hi": "Chào bạn! Bạn muốn hỏi về vấn đề gì?",
        "cảm ơn": "Không có gì! Nếu có thắc mắc gì khác, cứ hỏi nhé!",
        "thanks": "You're welcome! Let me know if you have more questions.",
    }


async def _generate_session_summary_bg(
    thread_id: str,
    user_id: str,
    organization_id: str | None = None,
) -> None:
    """Background: generate session summary for cross-session preamble."""
    try:
        from app.services.session_summarizer import get_session_summarizer

        summarizer = get_session_summarizer()
        await summarizer.summarize_thread(
            thread_id,
            user_id,
            organization_id=organization_id,
        )
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.debug("Background session summary failed: %s", exc)
