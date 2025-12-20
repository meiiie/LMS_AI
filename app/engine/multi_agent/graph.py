"""
Multi-Agent Graph - Phase 8.4

LangGraph workflow for multi-agent orchestration.

Pattern: Supervisor with specialized worker agents

**Integrated with agents/ framework for registry and tracing.**

**CHỈ THỊ SỐ 30: Universal ReasoningTrace for ALL paths**
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

# CHỈ THỊ SỐ 30: Universal ReasoningTrace
from app.engine.reasoning_tracer import get_reasoning_tracer, StepNames, ReasoningTracer

logger = logging.getLogger(__name__)


def _get_or_create_tracer(state: AgentState) -> ReasoningTracer:
    """
    Get existing tracer from state or create new one.
    
    CHỈ THỊ SỐ 30: Enables tracer inheritance across nodes for unified trace.
    This ensures ALL paths (direct, memory, tutor, rag) contribute to
    the same reasoning trace, matching SOTA patterns from OpenAI o1, Claude, etc.
    
    Args:
        state: Current agent state
        
    Returns:
        ReasoningTracer instance (either inherited or new)
    """
    tracer = state.get("_tracer")
    if tracer is None:
        tracer = get_reasoning_tracer()
        state["_tracer"] = tracer
    return tracer


# =============================================================================
# Node Functions with Tracing
# =============================================================================

async def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor node - routes to appropriate agent.
    
    CHỈ THỊ SỐ 30: Adds ROUTING step to reasoning trace.
    """
    registry = get_agent_registry()
    
    # CHỈ THỊ SỐ 30: Universal tracing - start routing step
    tracer = _get_or_create_tracer(state)
    tracer.start_step(StepNames.ROUTING, "Phân tích và định tuyến câu hỏi")
    
    with registry.tracer.span("supervisor", "route"):
        supervisor = get_supervisor_agent()
        result_state = await supervisor.process(state)
        
        # Record routing decision
        next_agent = result_state.get("next_agent", "unknown")
        tracer.end_step(
            result=f"Định tuyến đến: {next_agent}",
            confidence=0.9,
            details={"routed_to": next_agent}
        )
        
        # Propagate tracer to result state
        result_state["_tracer"] = tracer
        
        return result_state


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
    """
    Memory agent node - context retrieval.
    
    CHỈ THỊ SỐ 30: Adds MEMORY_LOOKUP step to reasoning trace.
    """
    registry = get_agent_registry()
    
    # CHỈ THỊ SỐ 30: Universal tracing
    tracer = _get_or_create_tracer(state)
    tracer.start_step(StepNames.MEMORY_LOOKUP, "Truy xuất ngữ cảnh và bộ nhớ người dùng")
    
    with registry.tracer.span("memory_agent", "process"):
        # SOTA FIX: Use singleton pattern (like ChatGPT/Claude) for memory engine
        from app.engine.semantic_memory import get_semantic_memory_engine
        semantic_memory = get_semantic_memory_engine()
        memory_agent = get_memory_agent_node(semantic_memory=semantic_memory)
        result_state = await memory_agent.process(state)
        
        # End step with result
        memory_output = result_state.get("memory_output", "")
        tracer.end_step(
            result=f"Truy xuất ngữ cảnh: {len(memory_output)} chars",
            confidence=0.85,
            details={"has_context": bool(memory_output)}
        )
        
        # Propagate tracer
        result_state["_tracer"] = tracer
        
        return result_state


async def grader_node(state: AgentState) -> AgentState:
    """
    Grader agent node - quality control.
    
    CHỈ THỊ SỐ 30: Adds QUALITY_CHECK step to reasoning trace.
    """
    registry = get_agent_registry()
    
    # CHỈ THỊ SỐ 30: Universal tracing
    tracer = _get_or_create_tracer(state)
    tracer.start_step(StepNames.QUALITY_CHECK, "Kiểm tra chất lượng câu trả lời")
    
    with registry.tracer.span("grader_agent", "process"):
        grader_agent = get_grader_agent_node()
        result_state = await grader_agent.process(state)
        
        # End step with grader result
        score = result_state.get("grader_score", 0)
        tracer.end_step(
            result=f"Điểm chất lượng: {score}/10",
            confidence=score / 10,
            details={"score": score, "passed": score >= 6}
        )
        
        # Propagate tracer
        result_state["_tracer"] = tracer
        
        return result_state


async def synthesizer_node(state: AgentState) -> AgentState:
    """
    Synthesizer node - combine outputs into final response.
    
    CHỈ THỊ SỐ 30: Adds SYNTHESIS step and builds final reasoning_trace.
    CHỈ THỊ SỐ 31: Merges CRAG trace with graph trace for complete picture.
    
    This is the final node where trace is compiled for non-direct paths.
    """
    # CHỈ THỊ SỐ 30: Universal tracing
    tracer = _get_or_create_tracer(state)
    tracer.start_step(StepNames.SYNTHESIS, "Tổng hợp câu trả lời cuối cùng")
    
    supervisor = get_supervisor_agent()
    
    # Synthesize outputs
    final_response = await supervisor.synthesize(state)
    state["final_response"] = final_response
    
    # End synthesis step
    tracer.end_step(
        result=f"Tổng hợp hoàn tất: {len(final_response)} chars",
        confidence=0.9,
        details={"response_length": len(final_response)}
    )
    
    # CHỈ THỊ SỐ 31 v3 SOTA: Priority Merge - ONLY merge CRAG trace (not graph trace)
    # CRAG trace has was_corrected attribute, graph trace doesn't
    existing_trace = state.get("reasoning_trace")
    is_crag_trace = (
        existing_trace and 
        hasattr(existing_trace, 'was_corrected') and  # CRAG-specific field
        hasattr(existing_trace, 'steps') and 
        len(existing_trace.steps) > 0
    )
    if is_crag_trace:
        # CRAG trace exists - merge graph steps AROUND it
        tracer.merge_trace(existing_trace, position="after_first")
        logger.info(f"[SYNTHESIZER] Merged CRAG trace ({len(existing_trace.steps)} steps) with graph trace")
    
    # Build final merged trace
    state["reasoning_trace"] = tracer.build_trace()
    logger.info(f"[SYNTHESIZER] Final trace: {state['reasoning_trace'].total_steps} steps")
    
    logger.info(f"[SYNTHESIZER] Final response generated, length={len(final_response)}")
    
    return state


async def direct_response_node(state: AgentState) -> AgentState:
    """
    Direct response node - simple responses without RAG.
    
    CHỈ THỊ SỐ 30: Adds DIRECT_RESPONSE step and builds reasoning_trace.
    This ensures direct path has consistent trace like other paths.
    """
    query = state.get("query", "")
    
    # CHỈ THỊ SỐ 30: Get inherited tracer from supervisor
    tracer = _get_or_create_tracer(state)
    tracer.start_step(StepNames.DIRECT_RESPONSE, "Tạo phản hồi trực tiếp")
    
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
    
    # End step with result
    tracer.end_step(
        result=f"Phản hồi đơn giản: {response[:50]}...",
        confidence=1.0,
        details={"response_type": "greeting", "query": query_lower}
    )
    
    state["final_response"] = response
    state["agent_outputs"] = {"direct": response}
    
    # CHỈ THỊ SỐ 31 v3 SOTA: Single Build Point Pattern
    # DON'T build trace here - only synthesizer builds trace
    # This follows DeepSeek R1 pattern: single accumulator, build at END
    state["_tracer"] = tracer  # Pass tracer for synthesizer to build
    
    logger.info(f"[DIRECT] Response prepared, tracer passed to synthesizer")
    
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
# P1 SOTA Early Exit: Skip Quality Check at High Confidence
# Saves ~7.8s when CRAG confidence is high
# =============================================================================

QUALITY_SKIP_THRESHOLD = 0.85  # Skip grader when confidence >= 85%


def should_skip_grader(state: AgentState) -> Literal["grader", "synthesizer"]:
    """
    Determine if quality check can be skipped based on confidence.
    
    SOTA 2025 Pattern: Self-RAG Early Exit
    - If CRAG pipeline returned high confidence, skip expensive grader LLM call
    - Saves ~7.8s per request
    
    Args:
        state: Current agent state with potential CRAG trace
        
    Returns:
        "synthesizer" if skip, "grader" if quality check needed
    """
    # Check for CRAG trace with confidence
    reasoning_trace = state.get("reasoning_trace")
    
    if reasoning_trace and hasattr(reasoning_trace, 'final_confidence'):
        confidence = reasoning_trace.final_confidence
        if confidence >= QUALITY_SKIP_THRESHOLD:
            logger.info(
                f"[P1 EARLY EXIT] Skipping quality_check: confidence={confidence:.2f} >= {QUALITY_SKIP_THRESHOLD}"
            )
            return "synthesizer"
    
    # Also check state-level confidence from CRAG
    crag_confidence = state.get("crag_confidence", 0)
    if crag_confidence >= QUALITY_SKIP_THRESHOLD:
        logger.info(
            f"[P1 EARLY EXIT] Skipping quality_check: crag_confidence={crag_confidence:.2f} >= {QUALITY_SKIP_THRESHOLD}"
        )
        return "synthesizer"
    
    # Default: run quality check
    return "grader"


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
    
    # All agents → Grader (with conditional skip)
    # P1 SOTA: Use conditional edges for tutor and rag - skip grader at high confidence
    workflow.add_conditional_edges(
        "rag_agent",
        should_skip_grader,
        {
            "grader": "grader",
            "synthesizer": "synthesizer"
        }
    )
    workflow.add_conditional_edges(
        "tutor_agent",
        should_skip_grader,
        {
            "grader": "grader",
            "synthesizer": "synthesizer"
        }
    )
    # Memory agent always goes through grader (low traffic)
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


# =============================================================================
# V3 STREAMING: Full Graph with Interleaved Events
# SOTA Dec 2025: LangGraph 1.0 astream_events() pattern
# =============================================================================

from typing import AsyncGenerator
import time

# Import streaming utilities
from app.engine.multi_agent.stream_utils import (
    StreamEvent,
    StreamEventType,
    NODE_DESCRIPTIONS,
    NODE_STEPS,
    create_status_event,
    create_thinking_event,
    create_answer_event,
    create_sources_event,
    create_metadata_event,
    create_done_event,
    create_error_event,
    transform_langgraph_event
)


async def process_with_multi_agent_streaming(
    query: str,
    user_id: str,
    session_id: str = "",
    context: dict = None
) -> AsyncGenerator[StreamEvent, None]:
    """
    Process with Multi-Agent graph with interleaved streaming.
    
    SOTA Dec 2025: Full Multi-Agent pipeline + progressive SSE events
    Pattern: OpenAI Responses API + Claude Extended Thinking + LangGraph 1.0
    
    Yields StreamEvents at each graph node:
    - Supervisor: routing decision (thinking event)
    - TutorAgent: tool calls + reasoning (thinking events)
    - GraderAgent: quality score (thinking event) 
    - Synthesizer: answer tokens (answer events)
    
    Timeline:
    - 0s: First status event (user sees progress)
    - 4-6s: Supervisor routing complete
    - 40-50s: TutorAgent + CRAG complete
    - 55-60s: GraderAgent complete (or skipped if high confidence)
    - 65-75s: Synthesizer + answer tokens
    
    **Feature: v3-full-graph-streaming**
    
    Args:
        query: User query
        user_id: User identifier
        session_id: Session identifier (optional)
        context: Additional context (optional)
        
    Yields:
        StreamEvent objects ready for SSE serialization
    """
    start_time = time.time()
    graph = get_multi_agent_graph()
    registry = get_agent_registry()
    
    # Start trace
    trace_id = registry.start_request_trace()
    logger.info(f"[MULTI_AGENT_STREAM] Started streaming trace: {trace_id}")
    
    try:
        # Yield initial status
        yield await create_status_event("🚀 Bắt đầu xử lý câu hỏi...", None)
        
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
            "error": None,
            # V3 Streaming: Signal that we want streaming
            "_streaming_mode": True
        }
        
        # Track current node for event deduplication
        last_node = None
        final_state = None
        
        # LangGraph streaming execution
        # Note: astream_events requires langgraph >= 0.2.x
        try:
            async for event in graph.astream_events(initial_state, version="v2"):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})
                
                # Extract node name from event
                node_name = _extract_node_from_event(event_name, event_data)
                
                # Handle node start events
                if event_type == "on_chain_start" and node_name and node_name != last_node:
                    last_node = node_name
                    if node_name in NODE_DESCRIPTIONS:
                        yield await create_status_event(
                            NODE_DESCRIPTIONS[node_name],
                            node_name
                        )
                
                # Handle node end events with results
                elif event_type == "on_chain_end" and node_name:
                    output = event_data.get("output", {})
                    
                    # Supervisor routing decision
                    if node_name == "supervisor":
                        next_agent = output.get("next_agent", "")
                        if next_agent:
                            yield await create_thinking_event(
                                f"Định tuyến đến: {next_agent}",
                                "routing",
                                confidence=0.9,
                                details={"routed_to": next_agent}
                            )
                    
                    # Grader quality check result
                    elif node_name == "grader":
                        score = output.get("grader_score", 0)
                        yield await create_thinking_event(
                            f"Điểm chất lượng: {score}/10 - {'ĐẠT' if score >= 6 else 'CHƯA ĐẠT'}",
                            "quality_check",
                            confidence=score / 10,
                            details={"score": score, "passed": score >= 6}
                        )
                    
                    # Synthesizer final response
                    elif node_name == "synthesizer":
                        final_response = output.get("final_response", "")
                        if final_response:
                            # Stream the final response in chunks for progressive display
                            # This simulates token streaming for the synthesized response
                            chunk_size = 100  # Characters per chunk
                            for i in range(0, len(final_response), chunk_size):
                                chunk = final_response[i:i+chunk_size]
                                yield await create_answer_event(chunk)
                        
                        # Store final state for sources/metadata
                        final_state = output
                    
                    # TutorAgent with tool usage
                    elif node_name in ["tutor_agent", "rag_agent"]:
                        # Check for tool calls
                        tools_used = output.get("tools_used", [])
                        if tools_used:
                            for tool in tools_used:
                                yield await create_thinking_event(
                                    f"Tra cứu: {tool.get('description', tool.get('name', 'unknown'))}",
                                    "tool_call",
                                    details={"tool": tool.get("name")}
                                )
                        
                        # Check for CRAG trace
                        reasoning_trace = output.get("reasoning_trace")
                        if reasoning_trace and hasattr(reasoning_trace, "steps"):
                            for step in reasoning_trace.steps:
                                yield await create_thinking_event(
                                    f"{step.description}: {step.result}",
                                    step.step_name,
                                    confidence=step.confidence
                                )
                
                # Handle LLM token streaming (if available)
                elif event_type == "on_chat_model_stream":
                    chunk = event_data.get("chunk", {})
                    content = _extract_chunk_content(chunk)
                    if content:
                        yield await create_answer_event(content)
        
        except AttributeError:
            # Fallback for LangGraph versions without astream_events
            logger.warning("[MULTI_AGENT_STREAM] astream_events not available, using ainvoke")
            
            # Fall back to non-streaming execution with synthetic events
            yield await create_status_event("⚠️ Streaming không khả dụng, đang xử lý...", None)
            
            result = await graph.ainvoke(initial_state)
            final_state = result
            
            # Yield the final response as chunks
            final_response = result.get("final_response", "")
            chunk_size = 100
            for i in range(0, len(final_response), chunk_size):
                yield await create_answer_event(final_response[i:i+chunk_size])
        
        # Emit sources
        if final_state:
            sources = final_state.get("sources", [])
            if sources:
                # Format sources for SSE
                formatted_sources = []
                for s in sources:
                    formatted_sources.append({
                        "title": s.get("title", ""),
                        "content": s.get("content", "")[:200] if s.get("content") else "",
                        "image_url": s.get("image_url"),
                        "page_number": s.get("page_number"),
                        "document_id": s.get("document_id")
                    })
                yield await create_sources_event(formatted_sources)
            
            # Emit metadata with reasoning_trace
            reasoning_trace = final_state.get("reasoning_trace")
            reasoning_dict = None
            if reasoning_trace:
                try:
                    reasoning_dict = reasoning_trace.model_dump()
                except AttributeError:
                    try:
                        reasoning_dict = reasoning_trace.dict()
                    except:
                        reasoning_dict = None
            
            processing_time = time.time() - start_time
            yield await create_metadata_event(
                reasoning_trace=reasoning_dict,
                processing_time=processing_time,
                confidence=final_state.get("grader_score", 0) / 10,
                model="maritime-rag-v3-streaming",
                doc_count=len(sources),
                thinking=final_state.get("thinking")
            )
        
        # Done signal
        total_time = time.time() - start_time
        yield await create_done_event(total_time)
        
        # End trace
        trace_summary = registry.end_request_trace(trace_id)
        logger.info(
            f"[MULTI_AGENT_STREAM] Completed in {total_time:.2f}s, "
            f"{trace_summary.get('span_count', 0)} spans"
        )
        
    except Exception as e:
        logger.exception(f"[MULTI_AGENT_STREAM] Error: {e}")
        yield await create_error_event(str(e))
        registry.end_request_trace(trace_id)


def _extract_node_from_event(event_name: str, event_data: dict) -> Optional[str]:
    """Extract node name from LangGraph event."""
    # Check event name
    for node in NODE_DESCRIPTIONS.keys():
        if node in event_name.lower():
            return node
    
    # Check event data
    if "name" in event_data:
        data_name = event_data["name"]
        for node in NODE_DESCRIPTIONS.keys():
            if node in data_name.lower():
                return node
    
    return None


def _extract_chunk_content(chunk: Any) -> Optional[str]:
    """Extract text content from LLM chunk."""
    if isinstance(chunk, str):
        return chunk
    
    if hasattr(chunk, "content"):
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    texts.append(block["text"])
            return "".join(texts) if texts else None
    
    if isinstance(chunk, dict) and "content" in chunk:
        return chunk["content"] if isinstance(chunk["content"], str) else None
    
    return None

