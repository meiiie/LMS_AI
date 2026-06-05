"""Runtime LLM socket helpers for agentic RAG components."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Optional
from unittest.mock import Mock

from app.engine.llm_factory import ThinkingTier
from app.engine.llm_pool import ainvoke_with_failover, get_llm_for_provider
from app.engine.native_chat_runtime import (
    make_assistant_message,
    make_system_message,
    make_user_message,
)

logger = logging.getLogger(__name__)

_REQUESTED_PROVIDER: ContextVar[str | None] = ContextVar("agentic_rag_requested_provider", default=None)
_REQUESTED_MODEL: ContextVar[str | None] = ContextVar("agentic_rag_requested_model", default=None)


def _clean_runtime_text(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


@contextmanager
def agentic_rag_runtime_target(*, provider: Any = None, model: Any = None):
    """Pin agentic RAG model resolution to the active user/session request."""

    provider_token = _REQUESTED_PROVIDER.set(_clean_runtime_text(provider))
    model_token = _REQUESTED_MODEL.set(_clean_runtime_text(model))
    try:
        yield
    finally:
        _REQUESTED_MODEL.reset(model_token)
        _REQUESTED_PROVIDER.reset(provider_token)


def resolve_agentic_rag_llm(
    *,
    tier: ThinkingTier,
    cached_llm: Any = None,
    fallback_factory: Optional[Callable[[], Any]] = None,
    component: str = "agentic_rag",
    node_id: str = "rag_agent",
    prefer_native: bool = True,
) -> Any:
    """Resolve the request-time LLM for an agentic RAG component.

    Preference order:
    1. Shared runtime-selectable route from the LLM pool
    2. Existing cached instance
    3. Legacy fallback factory for compatibility/test seams
    """

    if isinstance(cached_llm, Mock):
        return cached_llm

    if isinstance(fallback_factory, Mock):
        try:
            return fallback_factory()
        except Exception as exc:
            logger.warning(
                "[%s] Mocked %s-tier fallback unavailable: %s",
                component,
                getattr(tier, "value", str(tier)),
                exc,
            )
            return cached_llm

    if prefer_native:
        try:
            native_llm = _resolve_native_agentic_rag_llm(
                node_id=node_id,
                tier=tier,
                component=component,
                requested_provider=_REQUESTED_PROVIDER.get(),
                requested_model=_REQUESTED_MODEL.get(),
            )
            if native_llm is not None:
                return native_llm
        except Exception as exc:
            logger.debug(
                "[%s] Native %s-tier RAG LLM unavailable: %s",
                component,
                getattr(tier, "value", str(tier)),
                exc,
            )

    try:
        requested_provider = _REQUESTED_PROVIDER.get()
        requested_model = _REQUESTED_MODEL.get()
        if requested_provider and requested_model:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry

            llm = AgentConfigRegistry.get_llm(
                node_id,
                provider_override=requested_provider,
                requested_model=requested_model,
                strict_provider_pin=True,
            )
        else:
            llm = get_llm_for_provider(requested_provider, default_tier=tier)
        if llm is not None:
            return llm
    except Exception as exc:
        logger.warning(
            "[%s] Runtime %s-tier LLM unavailable: %s",
            component,
            getattr(tier, "value", str(tier)),
            exc,
        )

    if cached_llm is not None:
        return cached_llm

    if fallback_factory is not None:
        try:
            return fallback_factory()
        except Exception as exc:
            logger.warning(
                "[%s] Legacy %s-tier fallback unavailable: %s",
                component,
                getattr(tier, "value", str(tier)),
                exc,
            )

    return None


def make_agentic_rag_messages(
    *,
    user: Any,
    system: Any | None = None,
    assistant_prefill: Any | None = None,
) -> list[Any]:
    """Build framework-free chat messages for RAG/CRAG model calls."""
    messages: list[Any] = []
    if system is not None:
        messages.append(make_system_message(system))
    messages.append(make_user_message(user))
    if assistant_prefill is not None:
        messages.append(make_assistant_message(assistant_prefill))
    return messages


def _normalize_tier_name(tier: ThinkingTier | str) -> str:
    return str(getattr(tier, "value", tier) or "moderate").strip().lower() or "moderate"


def _resolve_native_agentic_rag_llm(
    *,
    node_id: str,
    tier: ThinkingTier | str,
    component: str,
    requested_provider: str | None = None,
    requested_model: str | None = None,
) -> Any:
    """Resolve a native provider handle only when its OpenAI-compatible client exists."""
    from app.engine.multi_agent.agent_config import AgentConfigRegistry
    from app.engine.multi_agent.openai_stream_runtime import (
        _create_openai_compatible_stream_client_impl,
    )

    tier_name = _normalize_tier_name(tier)
    native_llm = AgentConfigRegistry.get_native_llm(
        node_id,
        effort_override=tier_name,
        provider_override=requested_provider,
        requested_model=requested_model,
    )
    provider_name = str(getattr(native_llm, "_wiii_provider_name", "") or "").strip().lower()
    if not native_llm or not provider_name:
        return None

    # AgentConfigRegistry can create a metadata-only native handle. Keep runtime
    # fail-closed unless credentials/client config are actually present.
    if _create_openai_compatible_stream_client_impl(provider_name) is None:
        return None

    logger.info(
        "[%s] Using native RAG LLM: provider=%s model=%s tier=%s",
        component,
        provider_name,
        getattr(native_llm, "_wiii_model_name", "unknown"),
        tier_name,
    )
    return native_llm


async def ainvoke_agentic_rag_llm(
    *,
    llm: Any,
    messages: Any,
    tier: ThinkingTier | str,
    component: str = "agentic_rag",
    provider: Optional[str] = None,
    timeout_profile: Optional[str] = None,
    primary_timeout: Optional[float] = None,
) -> Any:
    """Invoke an agentic RAG LLM through the shared failover socket.

    This keeps async agentic-RAG callsites provider-agnostic at invocation
    time instead of only at object-selection time.
    """

    if llm is None:
        raise RuntimeError(f"{component} LLM is unavailable")

    if isinstance(llm, Mock):
        return await llm.ainvoke(messages)

    tier_name = _normalize_tier_name(tier)
    effective_provider = provider
    if not effective_provider and getattr(llm, "_wiii_native_route", False):
        effective_provider = getattr(llm, "_wiii_provider_name", None)
    try:
        return await ainvoke_with_failover(
            llm,
            messages,
            tier=tier_name,
            provider=effective_provider,
            failover_mode="auto",
            prefer_selectable_fallback=effective_provider in {None, "", "auto"},
            primary_timeout=primary_timeout,
            timeout_profile=timeout_profile,
        )
    except Exception as exc:
        logger.warning(
            "[%s] %s-tier invoke failed via runtime failover: %s",
            component,
            tier_name,
            exc,
        )
        raise
