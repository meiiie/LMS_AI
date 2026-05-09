"""WiiiRunner — Custom orchestrator replacing LangGraph StateGraph.

Inspired by OpenAI Agents SDK Runner pattern:
- NextStep loop: RunAgain, Handoff, FinalOutput (typed next-step variants)
- Simple async execution loop (no framework dependency)
- Guardian → Supervisor → {Agent} → Synthesize
- Streaming via event bus (already custom, not LangGraph streaming)
- Agent-as-Tool support built-in
- Lifecycle hooks (P1): RunHooks + AgentHooks for observability
- Agent handoffs (Phase 3): agents can transfer to other agents
- Orchestrator-level agentic loop (Phase 4): agents can request re-invocation

Design principles:
- All node functions are UNCHANGED (they take AgentState, return AgentState)
- No LangGraph imports — pure Python async orchestration
- Streaming format matches LangGraph's stream_mode="updates" for drop-in compat
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from app.core.config import settings
from app.engine.multi_agent.stream_events import make_bus_event, make_graph_event
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.guardrails import run_input_guardrails, run_output_guardrails
from app.engine.multi_agent.next_step import (
    NextStep,
    NextStepFinalOutput,
    NextStepHandoff,
    NextStepRunAgain,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (replace magic strings)
# ---------------------------------------------------------------------------

_NODE_GUARDIAN = "guardian"
_NODE_SUPERVISOR = "supervisor"
_NODE_SYNTHESIZER = "synthesizer"
_NODE_PARALLEL_DISPATCH = "parallel_dispatch"
_NODE_AGGREGATOR = "aggregator"

_MAX_DISPATCH_ITERATIONS = 2  # Safety limit for aggregator→supervisor loop
_MAX_HANDOFF_COUNT = 2  # Max agent-to-agent handoffs per request


_RUNTIME_STEP_MESSAGES = {
    _NODE_GUARDIAN: "Wiii đang kiểm tra an toàn...",
    _NODE_SUPERVISOR: "Wiii đang định tuyến câu hỏi...",
    "rag_agent": "Wiii đang tra cứu tri thức...",
    "tutor_agent": "Wiii đang soạn phần giải thích...",
    "memory_agent": "Wiii đang nối lại trí nhớ...",
    "direct": "Wiii đang gọi model để trả lời...",
    "code_studio_agent": "Wiii đang chuẩn bị Code Studio...",
    "product_search_agent": "Wiii đang tìm tín hiệu sản phẩm...",
    "colleague_agent": "Wiii đang hỏi thêm một góc nhìn...",
    _NODE_PARALLEL_DISPATCH: "Wiii đang chia việc cho các agent...",
    _NODE_AGGREGATOR: "Wiii đang tổng hợp báo cáo agent...",
    _NODE_SYNTHESIZER: "Wiii đang chốt câu trả lời cuối...",
}


def _ensure_runtime_latency(state: AgentState) -> dict[str, Any]:
    if "_runtime_latency_started_at" not in state:
        state["_runtime_latency_started_at"] = time.perf_counter()
    latency = state.setdefault("_runtime_latency", {"timeline": []})
    if not isinstance(latency, dict):
        latency = {"timeline": []}
        state["_runtime_latency"] = latency
    timeline = latency.setdefault("timeline", [])
    if not isinstance(timeline, list):
        latency["timeline"] = []
    return latency


def _runtime_elapsed_ms(state: AgentState) -> int:
    started_at = state.get("_runtime_latency_started_at")
    if not isinstance(started_at, (int, float)):
        started_at = time.perf_counter()
        state["_runtime_latency_started_at"] = started_at
    return int((time.perf_counter() - started_at) * 1000)


def _record_runtime_timeline_entry(
    state: AgentState,
    entry: dict[str, Any],
) -> dict[str, Any]:
    latency = _ensure_runtime_latency(state)
    timeline = latency.setdefault("timeline", [])
    timeline.append(entry)
    latency["elapsed_ms"] = _runtime_elapsed_ms(state)
    return entry


def _export_runtime_latency(state: AgentState) -> dict[str, Any]:
    latency = _ensure_runtime_latency(state)
    latency["elapsed_ms"] = _runtime_elapsed_ms(state)
    return latency


class WiiiRunner:
    """Custom orchestrator replacing LangGraph StateGraph.

    Instead of building a StateGraph → compile → invoke/astream,
    we directly call node functions in sequence:

        guardian → supervisor → {chosen_agent} → synthesizer

    This gives us:
    - Zero framework dependency (no langgraph)
    - Full control over execution flow
    - Simpler debugging (just function calls)
    - Same streaming behavior via event bus
    - Lifecycle hooks for observability, metrics, tracing
    """

    def __init__(self):
        self._nodes: dict[str, Callable] = {}
        self._feature_nodes: dict[str, tuple[Callable, Callable]] = {}
        self._hooks: Optional[HookDispatcher] = None

    def register_node(self, name: str, fn: Callable) -> None:
        """Register a node function: async (AgentState) -> AgentState."""
        self._nodes[name] = fn

    def register_feature_node(
        self,
        name: str,
        fn: Callable,
        gate_fn: Callable[[], bool],
    ) -> None:
        """Register a feature-gated node (only active when gate returns True)."""
        self._feature_nodes[name] = (fn, gate_fn)

    def set_hooks(self, dispatcher: Optional[HookDispatcher]) -> None:
        """Attach a HookDispatcher for lifecycle callbacks."""
        self._hooks = dispatcher

    def _get_node(self, name: str) -> Optional[Callable]:
        """Get a node function by name, checking feature gates."""
        if name in self._nodes:
            return self._nodes[name]
        if name in self._feature_nodes:
            fn, gate_fn = self._feature_nodes[name]
            if gate_fn():
                return fn
        return None

    # ------------------------------------------------------------------
    # Hook helpers
    # ------------------------------------------------------------------

    @property
    def hooks(self) -> Optional[HookDispatcher]:
        return self._hooks

    async def _emit_run_start(self, state: AgentState) -> None:
        if self._hooks:
            await self._hooks.emit_run_start(state)

    async def _emit_run_end(self, state: AgentState, duration_ms: float) -> None:
        if self._hooks:
            await self._hooks.emit_run_end(state, duration_ms)

    async def _emit_step_start(self, step_name: str, state: AgentState) -> None:
        if self._hooks:
            await self._hooks.emit_step_start(step_name, state)

    async def _emit_step_end(self, step_name: str, state: AgentState, duration_ms: float) -> None:
        if self._hooks:
            await self._hooks.emit_step_end(step_name, state, duration_ms)

    async def _emit_step_error(self, step_name: str, state: AgentState, error: Exception) -> None:
        if self._hooks:
            await self._hooks.emit_step_error(step_name, state, error)

    async def _emit_route(self, from_step: str, to_step: str, state: AgentState) -> None:
        if self._hooks:
            await self._hooks.emit_route(from_step, to_step, state)

    @staticmethod
    def _push_runtime_status(
        queue: Optional[asyncio.Queue],
        *,
        state: AgentState,
        node_name: str,
        stage: str,
        content: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Push a status-only bus event before long-running runtime work."""
        if queue is None:
            return
        details: dict[str, Any] = {
            "visibility": "status_only",
            "subtype": "runtime_status",
            "stage": stage,
            "node_name": node_name,
            "elapsed_ms": _runtime_elapsed_ms(state),
        }
        if extra:
            details.update(extra)
        queue.put_nowait(
            make_bus_event(
                {
                    "type": "status",
                    "content": content,
                    "node": node_name,
                    "details": details,
                }
            )
        )

    @classmethod
    def _push_runtime_route_status(
        cls,
        queue: Optional[asyncio.Queue],
        *,
        state: AgentState,
        from_step: str,
        to_step: str,
    ) -> None:
        _record_runtime_timeline_entry(
            state,
            {
                "stage": "runtime_route",
                "from": from_step,
                "to": to_step,
                "status": "ok",
                "elapsed_ms": _runtime_elapsed_ms(state),
            },
        )
        cls._push_runtime_status(
            queue,
            state=state,
            node_name=from_step or "runner",
            stage="runtime_route",
            content=f"Wiii chuyển luồng sang {to_step}...",
            extra={"route_from": from_step, "route_to": to_step},
        )

    @classmethod
    def _start_runtime_step(
        cls,
        queue: Optional[asyncio.Queue],
        *,
        name: str,
        state: AgentState,
    ) -> dict[str, Any]:
        entry = _record_runtime_timeline_entry(
            state,
            {
                "stage": "runtime_step",
                "node": name,
                "status": "running",
                "started_ms": _runtime_elapsed_ms(state),
            },
        )
        cls._push_runtime_status(
            queue,
            state=state,
            node_name=name,
            stage="runtime_step_start",
            content=_RUNTIME_STEP_MESSAGES.get(name, f"Wiii đang chạy {name}..."),
        )
        return entry

    @staticmethod
    def _finish_runtime_step(
        *,
        source_state: AgentState,
        result_state: AgentState,
        entry: dict[str, Any],
        started_at: float,
        status: str,
    ) -> AgentState:
        if result_state is not source_state:
            result_state.setdefault(
                "_runtime_latency_started_at",
                source_state.get("_runtime_latency_started_at"),
            )
            result_state.setdefault(
                "_runtime_latency",
                source_state.get("_runtime_latency", {"timeline": []}),
            )
        entry["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        entry["status"] = status
        _export_runtime_latency(result_state)
        return result_state

    # ------------------------------------------------------------------
    # Sync execution (replaces graph.ainvoke)
    # ------------------------------------------------------------------

    async def run(self, state: AgentState) -> AgentState:
        """Execute: Guardian → Supervisor → Agent → Synthesize.

        Uses a NextStep loop (inspired by OpenAI Agents SDK Runner):
        - Turn 0: supervisor routes to an agent
        - Subsequent turns: agent can request continuation (_agentic_continue),
          handoff to another agent (_handoff_target), or finalize.
        - Max turns protected by ``agentic_loop_max_steps``.
        """
        t_start = time.perf_counter()
        await self._emit_run_start(state)

        # 1. Guardian
        state = await self._run_step(_NODE_GUARDIAN, state)

        # 1b. Extended input guardrails
        guardian_passed = state.get("guardian_passed", True)
        passed, reason = await run_input_guardrails(state, guardian_passed=guardian_passed)
        if not passed:
            state["guardian_passed"] = False
            state["final_response"] = reason or "Nội dung không phù hợp."

        # 2. Guardian route
        from app.engine.multi_agent.runtime_routes import guardian_route

        route = guardian_route(state)
        await self._emit_route(_NODE_GUARDIAN, route, state)
        self._push_runtime_route_status(
            None,
            state=state,
            from_step=_NODE_GUARDIAN,
            to_step=route,
        )

        if route == _NODE_SYNTHESIZER:
            state["current_agent"] = _NODE_SYNTHESIZER
            state = await self._run_step(_NODE_SYNTHESIZER, state)
            await run_output_guardrails(state)
            elapsed = (time.perf_counter() - t_start) * 1000
            await self._emit_run_end(state, elapsed)
            return state

        # === NextStep Loop ===
        max_turns = getattr(settings, "agentic_loop_max_steps", 8)
        state["_orchestrator_turn"] = 0
        state["_handoff_count"] = 0

        for turn in range(max_turns):
            step = await self._resolve_next_step(state, turn)

            if isinstance(step, NextStepFinalOutput):
                break

            elif isinstance(step, NextStepHandoff):
                current_agent = state.get("current_agent", "")
                await self._emit_route(current_agent, step.target_agent, state)
                if current_agent != step.target_agent:
                    self._push_runtime_route_status(
                        None,
                        state=state,
                        from_step=current_agent,
                        to_step=step.target_agent,
                    )
                state["current_agent"] = step.target_agent
                state["next_agent"] = step.target_agent

                if step.target_agent == _NODE_PARALLEL_DISPATCH:
                    state = await self._run_parallel_dispatch(state)
                    elapsed = (time.perf_counter() - t_start) * 1000
                    await self._emit_run_end(state, elapsed)
                    return state

                state = await self._run_step(step.target_agent, state)

            elif isinstance(step, NextStepRunAgain):
                state = await self._run_step(step.agent_name, state)

            state["_orchestrator_turn"] = turn + 1
            self._preserve_thinking(state)

        # Synthesize + output guardrails
        state = await self._run_step(_NODE_SYNTHESIZER, state)
        await run_output_guardrails(state)

        elapsed = (time.perf_counter() - t_start) * 1000
        await self._emit_run_end(state, elapsed)
        return state

    # ------------------------------------------------------------------
    # Streaming execution (replaces graph.astream)
    # ------------------------------------------------------------------

    async def run_streaming(
        self,
        state: AgentState,
        *,
        merged_queue: Optional[asyncio.Queue] = None,
    ) -> AgentState:
        """Execute with streaming — push node updates to merged_queue.

        Same NextStep loop as run(), but pushes state snapshots to merged_queue
        after each node completion for real-time UI updates.
        """
        t_start = time.perf_counter()
        await self._emit_run_start(state)

        # 1. Guardian
        state = await self._run_step(
            _NODE_GUARDIAN,
            state,
            stream_queue=merged_queue,
        )

        # Keep streaming semantics aligned with run(): extended input
        # guardrails are part of the active runtime contract, not only sync API.
        guardian_passed = state.get("guardian_passed", True)
        passed, reason = await run_input_guardrails(state, guardian_passed=guardian_passed)
        if not passed:
            state["guardian_passed"] = False
            state["final_response"] = reason or "Nội dung không phù hợp."

        self._push_queue(merged_queue, _NODE_GUARDIAN, state)

        # 2. Guardian route
        from app.engine.multi_agent.runtime_routes import guardian_route

        route = guardian_route(state)
        await self._emit_route(_NODE_GUARDIAN, route, state)
        self._push_runtime_route_status(
            merged_queue,
            state=state,
            from_step=_NODE_GUARDIAN,
            to_step=route,
        )

        if route == _NODE_SYNTHESIZER:
            state["current_agent"] = _NODE_SYNTHESIZER
            state = await self._run_step(
                _NODE_SYNTHESIZER,
                state,
                stream_queue=merged_queue,
            )
            await run_output_guardrails(state)
            self._push_queue(merged_queue, _NODE_SYNTHESIZER, state)
            elapsed = (time.perf_counter() - t_start) * 1000
            await self._emit_run_end(state, elapsed)
            return state

        # === NextStep Loop ===
        max_turns = getattr(settings, "agentic_loop_max_steps", 8)
        state["_orchestrator_turn"] = 0
        state["_handoff_count"] = 0

        for turn in range(max_turns):
            step = await self._resolve_next_step(
                state,
                turn,
                stream_queue=merged_queue,
            )

            if isinstance(step, NextStepFinalOutput):
                break

            elif isinstance(step, NextStepHandoff):
                current_agent = state.get("current_agent", "")
                await self._emit_route(current_agent, step.target_agent, state)
                if current_agent != step.target_agent:
                    self._push_runtime_route_status(
                        merged_queue,
                        state=state,
                        from_step=current_agent,
                        to_step=step.target_agent,
                    )
                state["current_agent"] = step.target_agent
                state["next_agent"] = step.target_agent

                if step.target_agent == _NODE_PARALLEL_DISPATCH:
                    state = await self._run_parallel_dispatch(state, merged_queue=merged_queue)
                    elapsed = (time.perf_counter() - t_start) * 1000
                    await self._emit_run_end(state, elapsed)
                    return state

                state = await self._run_step(
                    step.target_agent,
                    state,
                    stream_queue=merged_queue,
                )
                self._push_queue(merged_queue, step.target_agent, state)

            elif isinstance(step, NextStepRunAgain):
                state = await self._run_step(
                    step.agent_name,
                    state,
                    stream_queue=merged_queue,
                )
                self._push_queue(merged_queue, step.agent_name, state)

            state["_orchestrator_turn"] = turn + 1
            self._preserve_thinking(state)

        # Synthesize
        state = await self._run_step(
            _NODE_SYNTHESIZER,
            state,
            stream_queue=merged_queue,
        )
        await run_output_guardrails(state)
        self._push_queue(merged_queue, _NODE_SYNTHESIZER, state)

        elapsed = (time.perf_counter() - t_start) * 1000
        await self._emit_run_end(state, elapsed)
        return state

    # ------------------------------------------------------------------
    # NextStep resolution
    # ------------------------------------------------------------------

    async def _resolve_next_step(
        self,
        state: AgentState,
        turn: int,
        *,
        stream_queue: Optional[asyncio.Queue] = None,
    ) -> NextStep:
        """Determine the next step in the orchestrator loop.

        - Turn 0: run supervisor, route to agent
        - Turn > 0: check for handoff, agentic continuation, or finalize
        """
        if turn == 0:
            # First turn: run supervisor routing
            state = await self._run_step(
                _NODE_SUPERVISOR,
                state,
                stream_queue=stream_queue,
            )
            from app.engine.multi_agent.graph_support import route_decision

            agent_name = route_decision(state)
            state["current_agent"] = agent_name
            state["next_agent"] = agent_name
            await self._emit_route(_NODE_SUPERVISOR, agent_name, state)
            self._push_runtime_route_status(
                stream_queue,
                state=state,
                from_step=_NODE_SUPERVISOR,
                to_step=agent_name,
            )
            return NextStepHandoff(target_agent=agent_name, reason="supervisor_route")

        # Subsequent turns: check for agent-initiated handoff
        handoff_target = state.get("_handoff_target")
        if handoff_target and settings.enable_agent_handoffs:
            handoff_count = state.get("_handoff_count", 0) or 0
            max_handoffs = getattr(settings, "agent_handoff_max_count", _MAX_HANDOFF_COUNT)
            if handoff_count < max_handoffs:
                state["_handoff_target"] = None
                state["_handoff_count"] = handoff_count + 1
                return NextStepHandoff(target_agent=handoff_target, reason="agent_handoff")
            else:
                logger.warning("[RUNNER] Handoff limit (%d) reached, finalizing", max_handoffs)
                state["_handoff_target"] = None
                return NextStepFinalOutput(reason="handoff_limit_reached")

        # Check if agent wants to continue (orchestrator-level agentic loop)
        if state.get("_agentic_continue"):
            current = state.get("current_agent", "")
            # Only allow continuation if agent config enables agentic loop
            if self._agent_has_agentic_loop(current):
                state["_agentic_continue"] = None
                return NextStepRunAgain(agent_name=current, reason="tool_calls_pending")
            state["_agentic_continue"] = None

        # Self-correction: check if response quality is too low for a retry
        if self._should_retry_response(state, turn):
            state["_self_correction_retry"] = (state.get("_self_correction_retry") or 0) + 1
            logger.info(
                "[RUNNER] Self-correction: re-routing to supervisor (retry %d)",
                state["_self_correction_retry"],
            )
            return NextStepHandoff(target_agent=_NODE_SUPERVISOR, reason="self_correction_retry")

        # Default: finalize
        return NextStepFinalOutput(reason="agent_complete")

    @staticmethod
    def _agent_has_agentic_loop(agent_name: str) -> bool:
        """Check if agent config has agentic loop enabled."""
        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry
            config = AgentConfigRegistry.get_config(agent_name)
            return getattr(config, "enable_agentic_loop", False)
        except Exception:
            return False

    @staticmethod
    def _should_retry_response(state: AgentState, turn: int) -> bool:
        """Check if the agent response is low-quality and worth a retry.

        Conditions for retry (max 1 retry to prevent loops):
        - Runner error occurred during agent execution
        - Grader score is critically low (< 3/10) when available
        - Response is empty or very short (< 20 chars) when no grader score
        - Haven't already retried
        """
        if turn < 1:
            return False  # Don't retry before agent has executed

        retry_count = state.get("_self_correction_retry") or 0
        if retry_count >= 1:
            return False  # Max 1 retry

        # Check for error state
        if state.get("_runner_error"):
            return True

        # Check grader score first (most reliable signal)
        grader_score = state.get("grader_score", 0)
        if isinstance(grader_score, (int, float)) and grader_score > 0:
            return grader_score < 3

        if state.get("_direct_reply_only_ack"):
            return False

        # No grader score — check response quality
        response = (state.get("final_response") or "").strip()
        if not response or len(response) < 20:
            return True

        return False

    @staticmethod
    def _preserve_thinking(state: AgentState) -> None:
        """Save thinking fragments from current turn into _thinking_history.

        Subsequent agents can build on previous reasoning rather than
        starting from scratch on each NextStep turn.
        """
        thinking_content = state.get("thinking_content")
        fragments = state.get("_public_thinking_fragments")
        thinking = state.get("thinking")  # Native Gemini thinking

        # Only preserve if there's something meaningful
        if not thinking_content and not fragments and not thinking:
            return

        history = state.get("_thinking_history") or []
        history.append({
            "turn": state.get("_orchestrator_turn", 0),
            "agent": state.get("current_agent", ""),
            "thinking_content": thinking_content,
            "fragments": fragments,
            "thinking": thinking,
        })
        state["_thinking_history"] = history

    @staticmethod
    def _push_queue(
        queue: Optional[asyncio.Queue],
        node_name: str,
        state: AgentState,
    ) -> None:
        """Push a graph event to the merged queue if available."""
        if queue is not None:
            queue.put_nowait(make_graph_event(node_name, dict(state)))

    # ------------------------------------------------------------------
    # Parallel dispatch (replaces LangGraph conditional edges + aggregator)
    # ------------------------------------------------------------------

    async def _run_parallel_dispatch(
        self,
        state: AgentState,
        *,
        merged_queue: Optional[asyncio.Queue] = None,
    ) -> AgentState:
        """Handle parallel_dispatch → aggregator → (synthesizer | supervisor loop).

        Protected by _MAX_DISPATCH_ITERATIONS to prevent infinite loops
        if aggregator keeps routing back to supervisor.
        """
        # Run parallel_dispatch
        state = await self._run_step(
            _NODE_PARALLEL_DISPATCH,
            state,
            stream_queue=merged_queue,
        )
        self._push_queue(merged_queue, _NODE_PARALLEL_DISPATCH, state)

        # Run aggregator
        state = await self._run_step(
            _NODE_AGGREGATOR,
            state,
            stream_queue=merged_queue,
        )
        self._push_queue(merged_queue, _NODE_AGGREGATOR, state)

        # Aggregator route: synthesizer or back to supervisor (with loop limit)
        for _iteration in range(_MAX_DISPATCH_ITERATIONS):
            next_route = self._resolve_aggregator_route(state)
            await self._emit_route(_NODE_AGGREGATOR, next_route, state)
            self._push_runtime_route_status(
                merged_queue,
                state=state,
                from_step=_NODE_AGGREGATOR,
                to_step=next_route,
            )

            if next_route != _NODE_SUPERVISOR:
                break

            # Loop back: supervisor → agent → (continue or break)
            state = await self._run_step(
                _NODE_SUPERVISOR,
                state,
                stream_queue=merged_queue,
            )
            self._push_queue(merged_queue, _NODE_SUPERVISOR, state)

            from app.engine.multi_agent.graph_support import route_decision

            agent_name = route_decision(state)
            state["current_agent"] = agent_name
            await self._emit_route(_NODE_SUPERVISOR, agent_name, state)
            self._push_runtime_route_status(
                merged_queue,
                state=state,
                from_step=_NODE_SUPERVISOR,
                to_step=agent_name,
            )

            node_fn = self._get_node(agent_name)
            if node_fn:
                state = await self._run_step(
                    agent_name,
                    state,
                    stream_queue=merged_queue,
                )
                self._push_queue(merged_queue, agent_name, state)

            # After agent execution, run aggregator again to decide next step
            state = await self._run_step(
                _NODE_AGGREGATOR,
                state,
                stream_queue=merged_queue,
            )
            self._push_queue(merged_queue, _NODE_AGGREGATOR, state)

        return await self._run_step(
            _NODE_SYNTHESIZER,
            state,
            stream_queue=merged_queue,
        )

    @staticmethod
    def _resolve_aggregator_route(state: AgentState) -> str:
        """Resolve aggregator routing decision with safe fallback."""
        try:
            from app.engine.multi_agent.subagents.aggregator import (
                aggregator_route as aggregator_route_impl,
            )
            return aggregator_route_impl(state)
        except Exception:
            return _NODE_SYNTHESIZER

    @staticmethod
    def _inject_tier_info(node_name: str, state: AgentState) -> None:
        """Inject tier info from AgentConfigRegistry into state for observability.

        Only injects for agent nodes (not infrastructure nodes like guardian/synthesizer).
        """
        if node_name in (_NODE_GUARDIAN, _NODE_SYNTHESIZER, _NODE_PARALLEL_DISPATCH, _NODE_AGGREGATOR):
            return
        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry

            config = AgentConfigRegistry.get_config(node_name)
            state["_execution_tier"] = config.tier
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Single step execution (with hooks)
    # ------------------------------------------------------------------

    async def _run_step(
        self,
        name: str,
        state: AgentState,
        *,
        stream_queue: Optional[asyncio.Queue] = None,
    ) -> AgentState:
        """Run a single node function with error handling and lifecycle hooks.

        Critical nodes (guardian, supervisor, synthesizer) re-raise on failure.
        Agent nodes continue with error state, allowing graceful degradation.
        """
        node_fn = self._get_node(name)
        if node_fn is None:
            logger.warning("[RUNNER] Node %s not found, skipping", name)
            return state

        # Inject tier info for observability (P3)
        self._inject_tier_info(name, state)

        t_start = time.perf_counter()
        timeline_entry = self._start_runtime_step(
            stream_queue,
            name=name,
            state=state,
        )
        await self._emit_step_start(name, state)

        try:
            result = await node_fn(state)
            duration_ms = (time.perf_counter() - t_start) * 1000
            await self._emit_step_end(name, result, duration_ms)
            return self._finish_runtime_step(
                source_state=state,
                result_state=result,
                entry=timeline_entry,
                started_at=t_start,
                status="ok",
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t_start) * 1000
            await self._emit_step_error(name, state, exc)
            logger.error("[RUNNER] Node %s failed (%.1fms): %s", name, duration_ms, exc)
            self._finish_runtime_step(
                source_state=state,
                result_state=state,
                entry=timeline_entry,
                started_at=t_start,
                status="error",
            )
            # Critical infrastructure nodes re-raise; agent nodes degrade gracefully
            if name in (_NODE_GUARDIAN, _NODE_SUPERVISOR, _NODE_SYNTHESIZER):
                raise
            state["_runner_error"] = str(exc)
            state["_runner_error_node"] = name
            return state


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_RUNNER: Optional[WiiiRunner] = None


def get_wiii_runner() -> WiiiRunner:
    """Get or create the WiiiRunner singleton.

    The runner is configured with the core orchestration node functions.
    Node functions are imported lazily to avoid circular imports.
    """
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER

    from app.engine.multi_agent.runtime_nodes import (
        guardian_node,
        supervisor_node,
        rag_node,
        tutor_node,
        memory_node,
        direct_response_node,
        code_studio_node,
        synthesizer_node,
        parallel_dispatch_node,
    )

    runner = WiiiRunner()

    # Core nodes (always active)
    runner.register_node(_NODE_GUARDIAN, guardian_node)
    runner.register_node(_NODE_SUPERVISOR, supervisor_node)
    runner.register_node("rag_agent", rag_node)
    runner.register_node("tutor_agent", tutor_node)
    runner.register_node("memory_agent", memory_node)
    runner.register_node("direct", direct_response_node)
    runner.register_node("code_studio_agent", code_studio_node)
    runner.register_node(_NODE_SYNTHESIZER, synthesizer_node)

    # Feature-gated nodes
    try:
        from app.engine.multi_agent.runtime_nodes import (
            colleague_agent_node,
            product_search_node,
        )

        runner.register_feature_node(
            "colleague_agent",
            colleague_agent_node,
            lambda: bool(
                settings.enable_cross_soul_query and settings.enable_soul_bridge
            ),
        )

        runner.register_feature_node(
            "product_search_agent",
            product_search_node,
            lambda: bool(settings.enable_product_search),
        )

        runner.register_feature_node(
            _NODE_PARALLEL_DISPATCH,
            parallel_dispatch_node,
            lambda: bool(settings.enable_subagent_architecture),
        )
    except Exception as exc:
        logger.warning("[RUNNER] Feature nodes registration partial: %s", exc)

    # Aggregator (only for subagent architecture)
    try:
        from app.engine.multi_agent.subagents.aggregator import aggregator_node

        runner.register_feature_node(
            _NODE_AGGREGATOR,
            aggregator_node,
            lambda: bool(settings.enable_subagent_architecture),
        )
    except Exception as exc:
        logger.debug("[RUNNER] Aggregator node not available: %s", exc)

    # Lifecycle hooks (feature-gated)
    _attach_default_hooks(runner)

    _RUNNER = runner
    logger.info(
        "[RUNNER] WiiiRunner initialized with %d core + %d feature nodes",
        len(runner._nodes),
        len(runner._feature_nodes),
    )
    return runner


def _attach_default_hooks(runner: WiiiRunner) -> None:
    """Attach default hooks for observability and metrics.

    Feature-gated by ``enable_runner_hooks`` (default True).
    LoggingHooks (INFO): pipeline lifecycle visible in production logs.
    MetricsHooks: auto-collect duration/status per step via SubagentMetrics.
    """
    if not settings.enable_runner_hooks:
        return

    from app.engine.multi_agent.hooks import HookDispatcher, LoggingHooks, MetricsHooks

    dispatcher = HookDispatcher()
    dispatcher.add_run_hooks(LoggingHooks())  # INFO level — visible in production
    dispatcher.add_run_hooks(MetricsHooks())   # Auto metrics collection
    runner.set_hooks(dispatcher)


# Late import to avoid circular dependency
from app.engine.multi_agent.hooks import HookDispatcher  # noqa: E402
