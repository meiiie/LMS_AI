"""
Multi-Agent System Module - Phase 8

Supervisor Pattern with Specialized Agents.

Components:
- SupervisorAgent: Coordinator and router
- RAGAgentNode: Knowledge retrieval specialist
- TutorAgentNode: Teaching specialist
- MemoryAgentNode: Context specialist
- GraderAgentNode: Quality control

V3 Streaming (2025-12-21):
- process_with_multi_agent_streaming: Full graph with interleaved streaming
"""

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor import SupervisorAgent, get_supervisor_agent
from app.engine.multi_agent.graph import (
    build_multi_agent_graph,
    get_multi_agent_graph,
    process_with_multi_agent,
    process_with_multi_agent_streaming  # V3 streaming
)

__all__ = [
    "AgentState",
    "SupervisorAgent",
    "get_supervisor_agent",
    "build_multi_agent_graph",
    "get_multi_agent_graph",
    "process_with_multi_agent",
    "process_with_multi_agent_streaming"
]
