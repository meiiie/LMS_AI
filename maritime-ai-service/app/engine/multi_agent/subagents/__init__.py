"""
Subagent architecture for Wiii multi-agent system.

Feature-gated: ``enable_subagent_architecture=False`` by default.

Provides
--------
- SubagentResult / SubagentConfig / SubagentRegistry — Core primitives
- execute_subagent / execute_parallel_subagents — Timeout + retry wrapper
- RequestScopedToolCache — Avoid duplicate API calls within a request
- SubagentMetrics — Per-subagent observability
- search/, rag/, tutor/ — Domain-specific subgraph packages
"""

from app.engine.multi_agent.subagents.result import (
    SubagentResult,
    SubagentStatus,
    SearchSubagentResult,
    RAGSubagentResult,
    TutorSubagentResult,
)
from app.engine.multi_agent.subagents.config import (
    SubagentConfig,
    FallbackBehavior,
)
from app.engine.multi_agent.subagents.registry import SubagentRegistry
from app.engine.multi_agent.subagents.tool_cache import RequestScopedToolCache
from app.engine.multi_agent.subagents.metrics import SubagentMetrics
from app.engine.multi_agent.subagents.report import (
    SubagentReport,
    ReportVerdict,
    AggregatorDecision,
    build_report,
)
from app.engine.multi_agent.subagents.handoff_context import (
    build_subagent_handoff_boundary_summary,
    project_kwargs_for_subagent,
    project_state_for_subagent,
)
from app.engine.multi_agent.subagents.result_boundary import (
    build_subagent_result_boundary_summary,
    sanitize_subagent_result_for_executor,
)
from app.engine.multi_agent.subagents.event_stream import (
    push_subagent_stream_event,
    sanitize_subagent_stream_event,
)

__all__ = [
    "SubagentResult",
    "SubagentStatus",
    "SearchSubagentResult",
    "RAGSubagentResult",
    "TutorSubagentResult",
    "SubagentConfig",
    "FallbackBehavior",
    "SubagentRegistry",
    "RequestScopedToolCache",
    "SubagentMetrics",
    # Phase 4
    "SubagentReport",
    "ReportVerdict",
    "AggregatorDecision",
    "build_report",
    "build_subagent_handoff_boundary_summary",
    "build_subagent_result_boundary_summary",
    "project_kwargs_for_subagent",
    "project_state_for_subagent",
    "push_subagent_stream_event",
    "sanitize_subagent_result_for_executor",
    "sanitize_subagent_stream_event",
]
