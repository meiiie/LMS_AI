"""
Agent State Schema - Phase 8.1

Shared state between all agents in the multi-agent system.
"""

from typing import TypedDict, List, Dict, Any, Optional


class AgentState(TypedDict, total=False):
    """
    Shared state between agents.
    
    All agents read and write to this state.
    LangGraph manages state transitions.
    """
    # Input
    query: str
    user_id: str
    session_id: str
    
    # Context
    context: Dict[str, Any]
    user_context: Dict[str, Any]
    learning_context: Dict[str, Any]
    
    # Messages
    messages: List[Dict[str, Any]]
    
    # Routing
    current_agent: str
    next_agent: str
    
    # Agent outputs
    agent_outputs: Dict[str, Any]
    rag_output: str
    tutor_output: str
    memory_output: str
    
    # Quality
    grader_score: float
    grader_feedback: str
    
    # KG Builder outputs (Feature: document-kg)
    kg_builder_output: Dict[str, Any]
    extracted_entities: List[Any]
    extracted_relations: List[Any]
    
    # Final
    final_response: str
    sources: List[Dict[str, Any]]
    tools_used: List[Dict[str, Any]]  # SOTA: Track tool usage for transparency
    
    # Metadata
    iteration: int
    max_iterations: int
    error: Optional[str]
    
    # CHỈ THỊ SỐ 28: SOTA Reasoning Trace for API transparency
    reasoning_trace: Optional[Any]  # ReasoningTrace from CorrectiveRAG
    thinking_content: Optional[str]  # Structured prose summary (fallback)
    
    # CHỈ THỊ SỐ 29: Native thinking from Gemini (SOTA 2025)
    thinking: Optional[str]  # Native Gemini thinking (priority)
    
    # CHỈ THỊ SỐ 30: Internal tracer reference for graph-level universal tracing
    # Enables consistent ReasoningTrace across ALL paths (direct, memory, tutor, rag)
    _tracer: Optional[Any]  # ReasoningTracer instance inherited across nodes


