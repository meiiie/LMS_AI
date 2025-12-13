"""
Agent Registry - Centralized Agent Management for Maritime AI Tutor

SOTA 2025 Pattern: Agent Registry with Tracing
- Centralized agent lifecycle management
- Observability and tracing
- Category-based filtering
- Tool-Agent mapping
"""

import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from contextlib import contextmanager

from app.engine.agents.config import (
    AgentConfig, 
    AgentCategory, 
    AccessLevel,
    DEFAULT_AGENT_CONFIGS
)
from app.engine.agents.base import BaseAgent

logger = logging.getLogger(__name__)


# =============================================================================
# TRACING - Observability for Agent Execution
# =============================================================================

@dataclass
class TraceSpan:
    """A single span in the execution trace."""
    span_id: str
    trace_id: str
    agent_id: str
    operation: str
    start_time: float
    end_time: Optional[float] = None
    status: str = "running"
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


class AgentTracer:
    """
    Tracer for agent execution observability.
    
    Provides:
    - Request tracing with unique IDs
    - Execution timing
    - Error tracking
    - Performance metrics
    """
    
    def __init__(self):
        self._traces: Dict[str, List[TraceSpan]] = {}
        self._current_trace_id: Optional[str] = None
        
    def start_trace(self) -> str:
        """Start a new trace for a request."""
        trace_id = str(uuid.uuid4())[:8]
        self._traces[trace_id] = []
        self._current_trace_id = trace_id
        logger.debug(f"[TRACE] Started trace: {trace_id}")
        return trace_id
    
    def end_trace(self, trace_id: str) -> List[TraceSpan]:
        """End a trace and return all spans."""
        self._current_trace_id = None
        spans = self._traces.get(trace_id, [])
        logger.debug(f"[TRACE] Ended trace: {trace_id}, spans: {len(spans)}")
        return spans
    
    @contextmanager
    def span(self, agent_id: str, operation: str, metadata: Dict = None):
        """Context manager for tracing a span."""
        trace_id = self._current_trace_id or "untraced"
        span = TraceSpan(
            span_id=str(uuid.uuid4())[:8],
            trace_id=trace_id,
            agent_id=agent_id,
            operation=operation,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        if trace_id in self._traces:
            self._traces[trace_id].append(span)
        
        try:
            yield span
            span.status = "success"
        except Exception as e:
            span.status = "error"
            span.error = str(e)
            raise
        finally:
            span.end_time = time.time()
            logger.info(
                f"[TRACE] {span.agent_id}.{span.operation} "
                f"[{span.status}] {span.duration_ms:.1f}ms"
            )
    
    def get_trace_summary(self, trace_id: str) -> Dict[str, Any]:
        """Get summary of a trace."""
        spans = self._traces.get(trace_id, [])
        if not spans:
            return {}
        
        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "total_duration_ms": sum(s.duration_ms for s in spans),
            "agents_involved": list(set(s.agent_id for s in spans)),
            "errors": [s for s in spans if s.status == "error"]
        }


# =============================================================================
# AGENT REGISTRY
# =============================================================================

class AgentRegistry:
    """
    Centralized registry for all AI agents.
    
    SOTA 2025 Pattern:
    - Agent lifecycle management
    - Category-based filtering
    - Tool-Agent mapping
    - Integrated tracing
    
    Usage:
        registry = get_agent_registry()
        registry.register(my_agent, config)
        agents = registry.get_by_category(AgentCategory.RETRIEVAL)
    """
    
    def __init__(self):
        self._agents: Dict[str, Any] = {}  # agent_id -> agent instance
        self._configs: Dict[str, AgentConfig] = {}  # agent_id -> config
        self._tracer = AgentTracer()
        self._initialized = False
        
        # Pre-register default configs (instances added later)
        for agent_id, config in DEFAULT_AGENT_CONFIGS.items():
            self._configs[agent_id] = config
    
    # =========================================================================
    # REGISTRATION
    # =========================================================================
    
    def register(
        self,
        agent: Any,
        config: Optional[AgentConfig] = None,
        agent_id: Optional[str] = None
    ) -> None:
        """
        Register an agent with the registry.
        
        Args:
            agent: The agent instance
            config: Optional config (uses default if not provided)
            agent_id: Optional ID override
        """
        # Determine agent ID
        if agent_id:
            aid = agent_id
        elif hasattr(agent, 'agent_id'):
            aid = agent.agent_id
        elif hasattr(agent, 'config') and hasattr(agent.config, 'id'):
            aid = agent.config.id
        else:
            aid = agent.__class__.__name__.lower()
        
        # Get or create config
        if config:
            self._configs[aid] = config
        elif aid not in self._configs:
            # Create minimal config
            self._configs[aid] = AgentConfig(
                id=aid,
                name=agent.__class__.__name__,
                role="Generic Agent",
                goal="Process requests"
            )
        
        self._agents[aid] = agent
        logger.info(f"[REGISTRY] Registered agent: {aid} ({self._configs[aid].name})")
    
    def unregister(self, agent_id: str) -> bool:
        """Unregister an agent by ID."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info(f"[REGISTRY] Unregistered agent: {agent_id}")
            return True
        return False
    
    # =========================================================================
    # RETRIEVAL
    # =========================================================================
    
    def get(self, agent_id: str) -> Optional[Any]:
        """Get agent by ID."""
        return self._agents.get(agent_id)
    
    def get_config(self, agent_id: str) -> Optional[AgentConfig]:
        """Get agent config by ID."""
        return self._configs.get(agent_id)
    
    def get_by_category(self, category: AgentCategory) -> List[Any]:
        """Get all agents in a category."""
        return [
            agent for aid, agent in self._agents.items()
            if self._configs.get(aid) and self._configs[aid].category == category
        ]
    
    def get_by_access_level(self, level: AccessLevel) -> List[Any]:
        """Get agents by access level."""
        return [
            agent for aid, agent in self._agents.items()
            if self._configs.get(aid) and self._configs[aid].access_level == level
        ]
    
    def get_all(self) -> Dict[str, Any]:
        """Get all registered agents."""
        return dict(self._agents)
    
    def get_all_configs(self) -> Dict[str, AgentConfig]:
        """Get all agent configs."""
        return dict(self._configs)
    
    # =========================================================================
    # TOOL MAPPING
    # =========================================================================
    
    def get_tools_for_agent(self, agent_id: str) -> List[str]:
        """Get tools available to an agent."""
        config = self._configs.get(agent_id)
        return config.tools if config else []
    
    def get_agents_for_tool(self, tool_id: str) -> List[str]:
        """Get agents that can use a specific tool."""
        return [
            aid for aid, config in self._configs.items()
            if tool_id in config.tools
        ]
    
    # =========================================================================
    # TRACING
    # =========================================================================
    
    @property
    def tracer(self) -> AgentTracer:
        """Get the tracer instance."""
        return self._tracer
    
    def start_request_trace(self) -> str:
        """Start tracing a new request."""
        return self._tracer.start_trace()
    
    def end_request_trace(self, trace_id: str) -> Dict[str, Any]:
        """End request trace and get summary."""
        spans = self._tracer.end_trace(trace_id)
        return self._tracer.get_trace_summary(trace_id)
    
    # =========================================================================
    # UTILITIES
    # =========================================================================
    
    def count(self) -> int:
        """Get number of registered agents."""
        return len(self._agents)
    
    def is_registered(self, agent_id: str) -> bool:
        """Check if agent is registered."""
        return agent_id in self._agents
    
    def summary(self) -> Dict[str, Any]:
        """Get summary of registered agents."""
        categories = {}
        for aid, config in self._configs.items():
            if aid in self._agents:  # Only count registered agents
                cat = config.category.value
                categories[cat] = categories.get(cat, 0) + 1
        
        return {
            "total_registered": len(self._agents),
            "total_configs": len(self._configs),
            "categories": categories,
            "agents": [
                {
                    "id": aid,
                    "name": config.name,
                    "category": config.category.value,
                    "tools": config.tools
                }
                for aid, config in self._configs.items()
                if aid in self._agents
            ]
        }
    
    def list_all(self) -> List[str]:
        """List all registered agent IDs."""
        return list(self._agents.keys())


# =============================================================================
# SINGLETON
# =============================================================================

_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """Get or create the global agent registry singleton."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        logger.info("AgentRegistry initialized")
    return _registry


def register_agent(
    agent: Any,
    config: Optional[AgentConfig] = None,
    agent_id: Optional[str] = None
) -> None:
    """Convenience function to register an agent."""
    get_agent_registry().register(agent, config, agent_id)
