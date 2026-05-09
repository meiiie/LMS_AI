"""Guardian runtime helpers extracted from the graph shell."""

from __future__ import annotations

import logging
from typing import Literal

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query
from app.engine.multi_agent.supervisor_hint_runtime import _normalize_router_text_impl
from app.engine.multi_agent.supervisor_runtime_support import _looks_reasoning_safety_meta_turn

logger = logging.getLogger(__name__)

_guardian_instance = None

_SAFE_IMAGE_INSPECTION_MARKERS = (
    "anh",
    "attached image",
    "doc chu",
    "hinh",
    "image",
    "marker",
    "mau",
    "noi dung anh",
    "ocr",
    "photo",
    "vision",
)

_IMAGE_GUARDIAN_BLOCKER_MARKERS = (
    "blood",
    "bomb",
    "bao luc",
    "che tao vu khi",
    "explosive",
    "kill",
    "nude",
    "sex",
    "vu khi",
    "weapon",
)


def get_guardian_impl():
    """Get or create Guardian agent singleton (lazy init)."""
    global _guardian_instance
    if _guardian_instance is None:
        from app.engine.guardian_agent import GuardianAgent

        _guardian_instance = GuardianAgent()
    return _guardian_instance


async def guardian_node_impl(
    state: AgentState,
    *,
    get_guardian,
) -> AgentState:
    """Guardian Agent node — input validation perimeter."""
    query = state.get("query", "")
    normalized_query = _normalize_router_text_impl(query)

    if len(query.strip()) < 3:
        state["guardian_passed"] = True
        return state

    if _looks_reasoning_safety_meta_turn(normalized_query):
        state["guardian_passed"] = True
        state["_guardian_fast_path"] = "reasoning_safety_meta"
        return state

    if _is_codebase_analysis_query(normalized_query):
        state["guardian_passed"] = True
        state["_guardian_fast_path"] = "codebase_source_backed_analysis"
        return state

    context = state.get("context") if isinstance(state, dict) else None
    has_images = bool(isinstance(context, dict) and context.get("images"))
    if has_images and any(marker in normalized_query for marker in _SAFE_IMAGE_INSPECTION_MARKERS):
        if not any(marker in normalized_query for marker in _IMAGE_GUARDIAN_BLOCKER_MARKERS):
            state["guardian_passed"] = True
            state["_guardian_fast_path"] = "safe_image_inspection"
            return state

    try:
        guardian = get_guardian()
        domain_id = state.get("domain_id")
        provider = state.get("provider")
        validate_kwargs = {
            "context": "education",
            "domain_id": domain_id,
        }
        if provider:
            validate_kwargs["provider"] = provider
        decision = await guardian.validate_message(query, **validate_kwargs)

        if decision.action == "BLOCK":
            logger.warning("[GUARDIAN] Blocked: %s", decision.reason)
            state["final_response"] = decision.reason or "Nội dung không phù hợp."
            state["guardian_passed"] = False
            return state

        if decision.action == "FLAG":
            logger.info("[GUARDIAN] Flagged: %s", decision.reason)

        state["guardian_passed"] = True
        return state

    except Exception as exc:
        logger.warning("[GUARDIAN] Validation error (allowing): %s", exc)
        state["guardian_passed"] = True
        return state


def guardian_route_impl(state: AgentState) -> Literal["supervisor", "synthesizer"]:
    """Route based on Guardian decision: pass to supervisor or block to synthesizer."""
    if state.get("guardian_passed", True):
        return "supervisor"
    return "synthesizer"
