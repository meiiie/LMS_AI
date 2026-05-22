"""
Multi-Agent System Module - Phase 8

Supervisor pattern with specialized agents, routed through WiiiRunner.

The public package surface now exposes runner-backed processing only; retired
graph builder/checkpointer APIs were removed with the LangGraph purge.

Sprint 140: Lazy imports via __getattr__ to break circular dependency
(state ↔ graph via __init__.py eager imports).
"""

__all__ = [
    "AgentState",
    "SupervisorAgent",
    "get_supervisor_agent",
    "process_with_multi_agent",
    "process_with_multi_agent_streaming",
]


def __getattr__(name: str):
    if name == "AgentState":
        from app.engine.multi_agent.state import AgentState
        return AgentState
    if name in ("SupervisorAgent", "get_supervisor_agent"):
        from app.engine.multi_agent import supervisor
        return getattr(supervisor, name)
    if name == "process_with_multi_agent":
        from app.engine.multi_agent.runtime import process_with_multi_agent
        return process_with_multi_agent
    if name == "process_with_multi_agent_streaming":
        from app.engine.multi_agent.streaming_runtime import process_with_multi_agent_streaming
        return process_with_multi_agent_streaming
    if name == "graph":
        import importlib
        return importlib.import_module(f"{__name__}.graph")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
