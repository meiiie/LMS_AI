"""
Agent Registry Module - Centralized Agent Management

SOTA 2025 Pattern: Agent Registry with Observability

Usage:
    from app.engine.agents import get_agent_registry, AgentConfig
    
    # Get registry
    registry = get_agent_registry()
    
    # Register an agent
    registry.register(my_agent, config)
    
    # Start tracing
    trace_id = registry.start_request_trace()
    with registry.tracer.span("my_agent", "process"):
        result = await my_agent.process(state)
    summary = registry.end_request_trace(trace_id)
"""

import logging

# Core exports
from app.engine.agents.config import (
    AgentConfig,
    AgentCategory,
    AccessLevel,
    DEFAULT_AGENT_CONFIGS,
    # Pre-defined configs
    RAG_AGENT_CONFIG,
    TUTOR_AGENT_CONFIG,
    MEMORY_AGENT_CONFIG,
    GRADER_AGENT_CONFIG,
    SUPERVISOR_AGENT_CONFIG
)

from app.engine.agents.base import (
    BaseAgent,
    AgentMixin
)

from app.engine.agents.registry import (
    AgentRegistry,
    AgentTracer,
    TraceSpan,
    get_agent_registry,
    register_agent
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_all_agents() -> dict:
    """Get all registered agents."""
    return get_agent_registry().get_all()


def get_agent_summary() -> dict:
    """Get summary of agent registry."""
    return get_agent_registry().summary()


__all__ = [
    # Config
    "AgentConfig",
    "AgentCategory",
    "AccessLevel",
    "DEFAULT_AGENT_CONFIGS",
    "RAG_AGENT_CONFIG",
    "TUTOR_AGENT_CONFIG",
    "MEMORY_AGENT_CONFIG",
    "GRADER_AGENT_CONFIG",
    "SUPERVISOR_AGENT_CONFIG",
    
    # Base
    "BaseAgent",
    "AgentMixin",
    
    # Registry
    "AgentRegistry",
    "AgentTracer",
    "TraceSpan",
    "get_agent_registry",
    "register_agent",
    
    # Convenience
    "get_all_agents",
    "get_agent_summary"
]
