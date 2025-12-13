"""
Base Agent Protocol - Interface for all agents

SOTA 2025 Pattern: Protocol-based agent abstraction
"""

from typing import Protocol, Dict, Any, Optional, runtime_checkable
from abc import abstractmethod

from app.engine.agents.config import AgentConfig


@runtime_checkable
class BaseAgent(Protocol):
    """
    Protocol defining the interface for all agents.
    
    All agents in the multi-agent system should implement this protocol
    to ensure consistency and interoperability.
    """
    
    @property
    def config(self) -> AgentConfig:
        """Get agent configuration."""
        ...
    
    @property
    def agent_id(self) -> str:
        """Get unique agent identifier."""
        ...
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process the current state and return updated state.
        
        Args:
            state: Current agent state with query, context, etc.
            
        Returns:
            Updated state with agent's output
        """
        ...
    
    def is_available(self) -> bool:
        """Check if agent is ready to process requests."""
        ...


class AgentMixin:
    """
    Mixin class providing common agent functionality.
    
    Inherit from this to get default implementations.
    """
    
    _config: Optional[AgentConfig] = None
    
    @property
    def config(self) -> AgentConfig:
        """Get agent configuration."""
        if self._config is None:
            raise ValueError("Agent config not set")
        return self._config
    
    @config.setter
    def config(self, value: AgentConfig) -> None:
        """Set agent configuration."""
        self._config = value
    
    @property
    def agent_id(self) -> str:
        """Get unique agent identifier."""
        return self.config.id if self._config else "unknown"
    
    def is_available(self) -> bool:
        """Default availability check."""
        return True
    
    def get_tools(self) -> list:
        """Get tools this agent can use."""
        return self.config.tools if self._config else []
    
    def can_delegate(self) -> bool:
        """Check if agent can delegate to others."""
        return self.config.allow_delegation if self._config else False
