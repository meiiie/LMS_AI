"""
Multi-Agent System Module - Phase 8

Supervisor Pattern with Specialized Agents.

Components:
- SupervisorAgent: Coordinator and router
- RAGAgentNode: Knowledge retrieval specialist
- TutorAgentNode: Teaching specialist
- MemoryAgentNode: Context specialist
- GraderAgentNode: Quality control
"""

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor import SupervisorAgent, get_supervisor_agent
from app.engine.multi_agent.graph import build_multi_agent_graph, get_multi_agent_graph

__all__ = [
    "AgentState",
    "SupervisorAgent",
    "get_supervisor_agent",
    "build_multi_agent_graph",
    "get_multi_agent_graph"
]
