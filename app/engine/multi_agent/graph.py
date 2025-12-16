"""
Multi-Agent Graph - Phase 8.4

LangGraph workflow for multi-agent orchestration.

Pattern: Supervisor with specialized worker agents

**Integrated with agents/ framework for registry and tracing.**
"""

import logging
from typing import Optional, Literal

from langgraph.graph import StateGraph, END

from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.supervisor import SupervisorAgent, get_supervisor_agent
from app.engine.multi_agent.agents.rag_node import RAGAgentNode, get_rag_agent_node
from app.engine.multi_agent.agents.tutor_node import TutorAgentNode, get_tutor_agent_node
from app.engine.multi_agent.agents.memory_agent import MemoryAgentNode, get_memory_agent_node
from app.engine.multi_agent.agents.grader_agent import GraderAgentNode, get_grader_agent_node

# Agent Registry integration
from app.engine.agents import get_agent_registry, register_agent

logger = logging.getLogger(__name__)


# =============================================================================
# Node Functions with Tracing
# =============================================================================

async def supervisor_node(state: AgentState) -> AgentState:
    """Supervisor node - routes to appropriate agent."""
    registry = get_agent_registry()
    with registry.tracer.span("supervisor", "route"):
        supervisor = get_supervisor_agent()
        return await supervisor.process(state)


async def rag_node(state: AgentState) -> AgentState:
    """RAG agent node - knowledge retrieval."""
    registry = get_agent_registry()
    with registry.tracer.span("rag_agent", "process"):
        rag_agent = get_rag_agent_node()
        return await rag_agent.process(state)


async def tutor_node(state: AgentState) -> AgentState:
    """Tutor agent node - teaching."""
    registry = get_agent_registry()
    with registry.tracer.span("tutor_agent", "process"):
        tutor_agent = get_tutor_agent_node()
        return await tutor_agent.process(state)


async def memory_node(state: AgentState) -> AgentState:
    """Memory agent node - context retrieval."""
    registry = get_agent_registry()
    with registry.tracer.span("memory_agent", "process"):
        # SOTA FIX: Use singleton pattern (like ChatGPT/Claude) for memory engine
        # Avoids creating new instances each call - resource efficient
        from app.engine.semantic_memory import get_semantic_memory_engine
        semantic_memory = get_semantic_memory_engine()
        memory_agent = get_memory_agent_node(semantic_memory=semantic_memory)
        return await memory_agent.process(state)


async def grader_node(state: AgentState) -> AgentState:
    """Grader agent node - quality control."""
    registry = get_agent_registry()
    with registry.tracer.span("grader_agent", "process"):
        grader_agent = get_grader_agent_node()
        return await grader_agent.process(state)


async def synthesizer_node(state: AgentState) -> AgentState:
    """Synthesizer node - combine outputs into final response."""
    supervisor = get_supervisor_agent()
    
    # Synthesize outputs
    final_response = await supervisor.synthesize(state)
    state["final_response"] = final_response
    
    logger.info(f"[SYNTHESIZER] Final response generated, length={len(final_response)}")
    
    return state


async def direct_response_node(state: AgentState) -> AgentState:
    """Direct response node - simple responses without RAG."""
    query = state.get("query", "")
    
    # Simple greeting responses
    greetings = {
        "xin chào": "Xin chào! Tôi là Maritime AI Tutor. Tôi có thể giúp gì cho bạn?",
        "hello": "Hello! I'm Maritime AI Tutor. How can I help you?",
        "hi": "Chào bạn! Bạn muốn hỏi về vấn đề hàng hải nào?",
        "cảm ơn": "Không có gì! Nếu có thắc mắc gì khác, cứ hỏi nhé!",
        "thanks": "You're welcome! Let me know if you have more questions.",
    }
    
    query_lower = query.lower().strip()
    response = greetings.get(query_lower, "Tôi có thể giúp gì cho bạn?")
    
    state["final_response"] = response
    state["agent_outputs"] = {"direct": response}
    
    return state


# =============================================================================
# Routing Function
# =============================================================================

def route_decision(state: AgentState) -> Literal["rag_agent", "tutor_agent", "memory_agent", "direct"]:
    """
    Determine next agent based on supervisor decision.
    
    Returns edge name for LangGraph routing.
    """
    next_agent = state.get("next_agent", "rag_agent")
    
    if next_agent == "rag_agent":
        return "rag_agent"
    elif next_agent == "tutor_agent":
        return "tutor_agent"
    elif next_agent == "memory_agent":
        return "memory_agent"
    else:
        return "direct"


# =============================================================================
# Graph Builder
# =============================================================================

def build_multi_agent_graph():
    """
    Build LangGraph workflow for multi-agent system.
    
    Flow:
    1. Supervisor → Route decision
    2. [RAG | Tutor | Memory | Direct]
    3. Grader (optional)
    4. Synthesizer
    5. END
    
    Returns:
        Compiled LangGraph
    """
    logger.info("Building Multi-Agent Graph...")
    
    # Create graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("rag_agent", rag_node)
    workflow.add_node("tutor_agent", tutor_node)
    workflow.add_node("memory_agent", memory_node)
    workflow.add_node("direct", direct_response_node)
    workflow.add_node("grader", grader_node)
    workflow.add_node("synthesizer", synthesizer_node)
    
    # Set entry point
    workflow.set_entry_point("supervisor")
    
    # Conditional routing from supervisor
    workflow.add_conditional_edges(
        "supervisor",
        route_decision,
        {
            "rag_agent": "rag_agent",
            "tutor_agent": "tutor_agent",
            "memory_agent": "memory_agent",
            "direct": "direct"
        }
    )
    
    # All agents → Grader
    workflow.add_edge("rag_agent", "grader")
    workflow.add_edge("tutor_agent", "grader")
    workflow.add_edge("memory_agent", "grader")
    
    # Direct → Synthesizer (skip grader)
    workflow.add_edge("direct", "synthesizer")
    
    # Grader → Synthesizer
    workflow.add_edge("grader", "synthesizer")
    
    # Synthesizer → END
    workflow.add_edge("synthesizer", END)
    
    # Compile
    graph = workflow.compile()
    
    logger.info("Multi-Agent Graph built successfully")
    
    return graph


# =============================================================================
# Singleton
# =============================================================================

_graph = None

def get_multi_agent_graph():
    """Get or create Multi-Agent Graph singleton."""
    global _graph
    if _graph is None:
        _graph = build_multi_agent_graph()
    return _graph


async def process_with_multi_agent(
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict = None
) -> dict:
    """
    High-level function to process query with multi-agent system.
    
    Args:
        query: User query
        user_id: User identifier
        session_id: Session identifier
        context: Additional context
        
    Returns:
        Dict with final_response, sources, trace info, etc.
    """
    graph = get_multi_agent_graph()
    registry = get_agent_registry()
    
    # Start request trace
    trace_id = registry.start_request_trace()
    logger.info(f"[MULTI_AGENT] Started trace: {trace_id}")
    
    # Create initial state
    initial_state: AgentState = {
        "query": query,
        "user_id": user_id,
        "session_id": session_id,
        "context": context or {},
        "messages": [],
        "current_agent": "",
        "next_agent": "",
        "agent_outputs": {},
        "grader_score": 0.0,
        "grader_feedback": "",
        "final_response": "",
        "sources": [],
        "iteration": 0,
        "max_iterations": 3,
        "error": None
    }
    
    # Run graph
    result = await graph.ainvoke(initial_state)
    
    # End trace and get summary
    trace_summary = registry.end_request_trace(trace_id)
    logger.info(f"[MULTI_AGENT] Trace completed: {trace_summary.get('span_count', 0)} spans, {trace_summary.get('total_duration_ms', 0):.1f}ms")
    
    return {
        "response": result.get("final_response", ""),
        "sources": result.get("sources", []),
        "tools_used": result.get("tools_used", []),  # SOTA: Track tool usage
        "grader_score": result.get("grader_score", 0),
        "agent_outputs": result.get("agent_outputs", {}),
        "error": result.get("error"),
        # CHỈ THỊ SỐ 28: SOTA Reasoning Trace for API transparency
        "reasoning_trace": result.get("reasoning_trace"),
        # CHỈ THỊ SỐ 29: Native thinking from Gemini (SOTA 2025)
        "thinking": result.get("thinking"),  # Priority: native Gemini thinking
        # CHỈ THỊ SỐ 28: Structured summary (fallback)
        "thinking_content": result.get("thinking_content"),
        # Trace info
        "trace_id": trace_id,
        "trace_summary": trace_summary
    }
