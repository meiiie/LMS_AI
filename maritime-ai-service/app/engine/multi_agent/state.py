"""Agent State Schema - Phase 8.1 + P2 Typed Overlays

Shared state between all agents in the multi-agent system.

Architecture (P2):
- AgentState remains a flat TypedDict for backward compatibility
- Group TypedDicts (InputContext, RoutingState, etc.) provide type-safe views
- Accessor functions extract typed groups from the flat state
- New code should use accessors; existing code keeps flat access

Inspired by OpenAI Agents SDK's separation of context, usage, and state.
The flat dict is the wire format; the group types are compile-time safety.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# =========================================================================
# Group 1: Input Context — set before pipeline starts
# =========================================================================


class InputContext(TypedDict, total=False):
    """Fields populated before the pipeline executes.

    Set by ChatOrchestrator from the incoming request.
    Read-only during pipeline execution (agents should not modify these).
    """
    query: str
    user_id: str
    session_id: str
    context: Dict[str, Any]
    user_context: Dict[str, Any]
    learning_context: Dict[str, Any]
    messages: List[Dict[str, Any]]
    images: List[Dict[str, Any]]  # Sprint 200: visual product search
    conversation_phase: str  # Sprint 203: "opening" | "engaged" | "deep" | "closing"


# =========================================================================
# Group 2: Routing State — determines pipeline flow
# =========================================================================


class RoutingState(TypedDict, total=False):
    """Fields that control which agent handles the request.

    Written by: supervisor_node, route_decision, runner
    Read by: runner (for orchestration), streaming (for status)
    """
    current_agent: str
    next_agent: str
    routing_metadata: Dict[str, Any]  # {intent, confidence, reasoning, method}
    guardian_passed: bool
    domain_notice: str  # Sprint 80b: out-of-domain indicator


# =========================================================================
# Group 3: Agent Outputs — written by agent nodes
# =========================================================================


class AgentOutput(TypedDict, total=False):
    """Fields written by individual agent nodes during execution.

    Each agent writes its own output field(s).
    Synthesizer reads these to produce final_response.
    """
    agent_outputs: Dict[str, Any]
    rag_output: str
    tutor_output: str
    memory_output: str
    final_response: str
    sources: List[Dict[str, Any]]
    tools_used: List[Dict[str, Any]]
    tool_call_events: List[Dict[str, Any]]  # Sprint 58: SSE streaming
    grader_score: float
    grader_feedback: str
    evidence_images: List[Dict[str, Any]]  # Sprint 189b
    _answer_streamed_via_bus: bool  # Sprint 74: dedup signal


# =========================================================================
# Group 4: Runtime Metadata — internal execution state
# =========================================================================


class RuntimeMeta(TypedDict, total=False):
    """Internal metadata for tracing, streaming, and error handling.

    Prefixed with _ to indicate internal use.
    NOT serialized in API responses directly.
    """
    iteration: int
    max_iterations: int
    error: Optional[str]
    _trace_id: Optional[str]
    _event_bus_id: Optional[str]
    _execution_provider: Optional[str]
    _execution_model: Optional[str]
    _execution_tier: Optional[str]  # "deep" | "moderate" | "light" — which tier was used
    _llm_failover_events: List[Dict[str, Any]]
    _runner_error: Optional[str]
    _runner_error_node: Optional[str]
    _reroute_count: Optional[int]
    _aggregator_action: Optional[str]
    _aggregator_reasoning: Optional[str]
    _parallel_targets: List[str]
    _handoff_target: Optional[str]       # Agent-initiated handoff target
    _agentic_continue: Optional[bool]     # Agent signals more turns needed
    _orchestrator_turn: Optional[int]     # Current orchestrator loop turn
    _handoff_count: Optional[int]         # Handoff counter (bounded by agent_handoff_max_count)
    _self_correction_retry: Optional[int] # Self-correction retry counter (max 1)


# =========================================================================
# Group 5: Thinking & Reasoning — AI transparency fields
# =========================================================================


class ThinkingState(TypedDict, total=False):
    """Reasoning and thinking trace fields for AI transparency.

    Written by: agentic loop, RAG pipeline, tutor agent
    Read by: synthesizer (for output), streaming (for SSE events)
    Serialized in API response metadata.
    """
    reasoning_trace: Optional[Any]
    thinking_content: Optional[str]
    thinking_lifecycle: Optional[Dict[str, Any]]
    thinking: Optional[str]  # Native Gemini thinking
    _public_thinking_fragments: List[str]
    _thinking_trajectory: Optional[Dict[str, Any]]
    thinking_effort: Optional[str]  # "low" | "medium" | "high" | "max"
    _thinking_history: List[Dict[str, Any]]  # Preserved thinking across NextStep turns


# =========================================================================
# Group 6: Domain & Config — request-level configuration
# =========================================================================


class DomainConfig(TypedDict, total=False):
    """Domain plugin and per-request configuration.

    Set by: ChatOrchestrator, graph.py (domain routing)
    Read by: all agents (for domain-specific behavior)
    """
    domain_id: str
    domain_config: Dict[str, Any]
    skill_context: Optional[str]
    capability_context: Optional[str]
    provider: Optional[str]  # "auto" | "google" | "zhipu" | None
    model: Optional[str]
    organization_id: Optional[str]


# =========================================================================
# Group 7: Host Context — Universal Context Engine (Sprint 222)
# =========================================================================


class HostContext(TypedDict, total=False):
    """Host context fields from Universal Context Engine.

    Set by: ChatOrchestrator from request body
    Processed by: graph_surface_runtime.py (prompt injection)
    Read by: all agents (via injected prompt blocks)
    """
    host_context: Optional[Dict[str, Any]]
    host_capabilities: Optional[Dict[str, Any]]
    host_action_feedback: Optional[Dict[str, Any]]
    _host_action_control_feedback: Optional[Dict[str, Any]]
    host_context_prompt: Optional[str]
    host_capabilities_prompt: Optional[str]
    host_session: Optional[Dict[str, Any]]
    host_session_prompt: Optional[str]
    operator_session: Optional[Dict[str, Any]]
    operator_context_prompt: Optional[str]
    document_context_prompt: Optional[str]
    widget_feedback_prompt: Optional[str]
    living_context_prompt: Optional[str]
    memory_block_context: Optional[str]
    reasoning_policy: Optional[Dict[str, Any]]


# =========================================================================
# Group 8: Subagent Reports — parallel dispatch results
# =========================================================================


class SubagentState(TypedDict, total=False):
    """Fields for parallel subagent dispatch and aggregation."""
    subagent_reports: Optional[List[Dict[str, Any]]]


# =========================================================================
# AgentState — flat union of all groups (backward compatible)
# =========================================================================


class AgentState(TypedDict, total=False):
    """
    Shared state between agents.

    All agents read and write to this flat dict.
    Group TypedDicts above provide type-safe views for new code.

    Fields are organized by group — see InputContext, RoutingState,
    AgentOutput, RuntimeMeta, ThinkingState, DomainConfig, HostContext.
    """

    # -- InputContext --
    query: str
    user_id: str
    session_id: str
    context: Dict[str, Any]
    user_context: Dict[str, Any]
    learning_context: Dict[str, Any]
    messages: List[Dict[str, Any]]
    images: List[Dict[str, Any]]
    conversation_phase: str

    # -- RoutingState --
    current_agent: str
    next_agent: str
    routing_metadata: Optional[Dict[str, Any]]
    guardian_passed: Optional[bool]
    domain_notice: Optional[str]

    # -- AgentOutput --
    agent_outputs: Dict[str, Any]
    rag_output: str
    tutor_output: str
    memory_output: str
    final_response: str
    sources: List[Dict[str, Any]]
    tools_used: List[Dict[str, Any]]
    tool_call_events: Optional[List[Dict[str, Any]]]
    grader_score: float
    grader_feedback: str
    evidence_images: Optional[List[Dict[str, Any]]]
    _answer_streamed_via_bus: Optional[bool]

    # -- ThinkingState --
    reasoning_trace: Optional[Any]
    thinking_content: Optional[str]
    thinking_lifecycle: Optional[Dict[str, Any]]
    thinking: Optional[str]
    _public_thinking_fragments: Optional[List[str]]
    _thinking_trajectory: Optional[Dict[str, Any]]
    thinking_effort: Optional[str]

    # -- DomainConfig --
    domain_id: str
    domain_config: Dict[str, Any]
    skill_context: Optional[str]
    capability_context: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    organization_id: Optional[str]

    # -- RuntimeMeta --
    iteration: int
    max_iterations: int
    error: Optional[str]
    _trace_id: Optional[str]
    _event_bus_id: Optional[str]
    _execution_provider: Optional[str]
    _execution_model: Optional[str]
    _llm_failover_events: Optional[List[Dict[str, Any]]]
    _runner_error: Optional[str]
    _runner_error_node: Optional[str]
    _reroute_count: Optional[int]
    _aggregator_action: Optional[str]
    _aggregator_reasoning: Optional[str]
    _parallel_targets: Optional[List[str]]

    # -- HostContext --
    host_context: Optional[Dict[str, Any]]
    host_capabilities: Optional[Dict[str, Any]]
    host_action_feedback: Optional[Dict[str, Any]]
    _host_action_control_feedback: Optional[Dict[str, Any]]
    host_context_prompt: Optional[str]
    host_capabilities_prompt: Optional[str]
    host_session: Optional[Dict[str, Any]]
    host_session_prompt: Optional[str]
    operator_session: Optional[Dict[str, Any]]
    operator_context_prompt: Optional[str]
    document_context_prompt: Optional[str]
    widget_feedback_prompt: Optional[str]
    living_context_prompt: Optional[str]
    memory_block_context: Optional[str]
    reasoning_policy: Optional[Dict[str, Any]]

    # -- SubagentState --
    subagent_reports: Optional[List[Dict[str, Any]]]


# =========================================================================
# Typed accessor functions
# =========================================================================

_INPUT_KEYS = frozenset(InputContext.__annotations__.keys())
_ROUTING_KEYS = frozenset(RoutingState.__annotations__.keys())
_OUTPUT_KEYS = frozenset(AgentOutput.__annotations__.keys())
_RUNTIME_KEYS = frozenset(RuntimeMeta.__annotations__.keys())
_THINKING_KEYS = frozenset(ThinkingState.__annotations__.keys())
_DOMAIN_KEYS = frozenset(DomainConfig.__annotations__.keys())
_HOST_KEYS = frozenset(HostContext.__annotations__.keys())
_SUBAGENT_KEYS = frozenset(SubagentState.__annotations__.keys())


def get_input_context(state: AgentState) -> InputContext:
    """Extract input context fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _INPUT_KEYS}  # type: ignore[return-value]


def get_routing_state(state: AgentState) -> RoutingState:
    """Extract routing state fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _ROUTING_KEYS}  # type: ignore[return-value]


def get_agent_output(state: AgentState) -> AgentOutput:
    """Extract agent output fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _OUTPUT_KEYS}  # type: ignore[return-value]


def get_runtime_meta(state: AgentState) -> RuntimeMeta:
    """Extract runtime metadata fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _RUNTIME_KEYS}  # type: ignore[return-value]


def get_thinking_state(state: AgentState) -> ThinkingState:
    """Extract thinking/reasoning fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _THINKING_KEYS}  # type: ignore[return-value]


def get_domain_config(state: AgentState) -> DomainConfig:
    """Extract domain/config fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _DOMAIN_KEYS}  # type: ignore[return-value]


def get_host_context(state: AgentState) -> HostContext:
    """Extract host context fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _HOST_KEYS}  # type: ignore[return-value]


def get_subagent_state(state: AgentState) -> SubagentState:
    """Extract subagent dispatch fields as a typed dict."""
    return {k: v for k, v in state.items() if k in _SUBAGENT_KEYS}  # type: ignore[return-value]


# =========================================================================
# Merge helper — merge a typed group back into flat state
# =========================================================================


def merge_into_state(state: AgentState, **groups: dict) -> None:
    """Merge one or more typed group dicts back into the flat AgentState.

    Example: merge_into_state(state, routing=RoutingState(current_agent="rag_agent"))
    """
    for group_dict in groups.values():
        state.update(group_dict)
