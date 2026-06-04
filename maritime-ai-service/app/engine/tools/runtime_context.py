"""Shared runtime context for tool execution across agent, MCP, and sandbox layers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Iterator, Optional

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


@dataclass(slots=True)
class ToolRuntimeContext:
    """Per-invocation context propagated to tools through contextvars."""

    event_bus_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    node: Optional[str] = None
    source: str = "tool_registry"
    tool_name: str = ""
    tool_call_id: Optional[str] = None
    metadata: dict[str, Any] | None = None

    def for_tool(
        self,
        tool_name: str,
        *,
        tool_call_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> "ToolRuntimeContext":
        """Clone the current context for a specific tool call."""
        merged_metadata = dict(self.metadata or {})
        merged_metadata.update(_safe_metadata(metadata))
        return replace(
            self,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            metadata=_safe_metadata(merged_metadata),
        )


_CURRENT_TOOL_RUNTIME_CONTEXT: ContextVar[Optional[ToolRuntimeContext]] = ContextVar(
    "current_tool_runtime_context",
    default=None,
)


@contextmanager
def tool_runtime_scope(context: ToolRuntimeContext) -> Iterator[ToolRuntimeContext]:
    """Temporarily bind the current tool runtime context."""
    token = _CURRENT_TOOL_RUNTIME_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_TOOL_RUNTIME_CONTEXT.reset(token)


def get_current_tool_runtime_context() -> Optional[ToolRuntimeContext]:
    """Return the current tool runtime context, if any."""
    return _CURRENT_TOOL_RUNTIME_CONTEXT.get()


def build_tool_runtime_context(
    *,
    event_bus_id: Optional[str] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    node: Optional[str] = None,
    source: str = "tool_registry",
    metadata: Optional[dict[str, Any]] = None,
) -> ToolRuntimeContext:
    """Create a normalized runtime context for a request/tool scope."""
    resolved_request_id = request_id or _get_bound_request_id() or event_bus_id or session_id
    return ToolRuntimeContext(
        event_bus_id=event_bus_id,
        request_id=resolved_request_id,
        session_id=session_id,
        organization_id=organization_id,
        user_id=user_id,
        user_role=user_role,
        node=node,
        source=source,
        metadata=_safe_metadata(metadata),
    )


def _get_bound_request_id() -> Optional[str]:
    """Read the current HTTP request ID from structlog contextvars when available."""
    try:
        import structlog

        return structlog.contextvars.get_contextvars().get("request_id")
    except Exception:
        return None


def emit_tool_bus_event(event: Optional[dict[str, Any]]) -> bool:
    """Push a tool-generated event to the current request event bus."""
    if not event:
        return False

    runtime = get_current_tool_runtime_context()
    if runtime is None or not runtime.event_bus_id:
        return False

    try:
        from app.engine.multi_agent.graph_event_bus import _get_event_queue

        queue = _get_event_queue(runtime.event_bus_id)
    except Exception:
        return False

    if queue is None:
        return False

    payload = dict(event)
    if payload.get("node") is None and runtime.node:
        payload["node"] = runtime.node
    _merge_runtime_event_metadata(payload, runtime)

    try:
        queue.put_nowait(payload)
        return True
    except Exception:
        return False


def build_sandbox_execution_context(
    tool_name: str,
    *,
    source: Optional[str] = None,
    approval_scope: str = "",
    metadata: Optional[dict[str, Any]] = None,
):
    """Translate the current tool runtime context into sandbox execution context."""
    from app.sandbox.service import SandboxExecutionContext

    runtime = get_current_tool_runtime_context()
    merged_metadata = dict(metadata or {})
    if runtime and runtime.metadata:
        for key, value in runtime.metadata.items():
            merged_metadata.setdefault(key, value)
    if runtime and runtime.node:
        merged_metadata.setdefault("node", runtime.node)
    if runtime and runtime.tool_call_id:
        merged_metadata.setdefault("tool_call_id", runtime.tool_call_id)
    if runtime and runtime.user_role:
        merged_metadata.setdefault("user_role", runtime.user_role)

    return SandboxExecutionContext(
        tool_name=tool_name,
        source=source or (runtime.source if runtime else "tool_registry"),
        organization_id=runtime.organization_id if runtime else None,
        user_id=runtime.user_id if runtime else None,
        session_id=runtime.session_id if runtime else None,
        request_id=runtime.request_id if runtime else None,
        approval_scope=approval_scope,
        metadata=_safe_metadata(merged_metadata),
    )


def build_runtime_correlation_metadata(
    runtime: Optional[ToolRuntimeContext] = None,
) -> dict[str, Any]:
    """Build a compact correlation payload for events and execution metadata."""
    runtime = runtime or get_current_tool_runtime_context()
    if runtime is None:
        return {}

    metadata: dict[str, Any] = {}
    if runtime.request_id:
        metadata["request_id"] = runtime.request_id
    if runtime.session_id:
        metadata["session_id"] = runtime.session_id
    if runtime.organization_id:
        metadata["organization_id"] = runtime.organization_id
    if runtime.user_id:
        metadata["user_id"] = runtime.user_id
    if runtime.user_role:
        metadata["user_role"] = runtime.user_role
    if runtime.node:
        metadata["node"] = runtime.node
    if runtime.source:
        metadata["request_source"] = runtime.source
    if runtime.tool_name:
        metadata["tool_name"] = runtime.tool_name
    if runtime.tool_call_id:
        metadata["tool_call_id"] = runtime.tool_call_id
    for key, value in (runtime.metadata or {}).items():
        metadata.setdefault(key, value)
    return _safe_metadata(metadata)


def _merge_runtime_event_metadata(
    payload: dict[str, Any],
    runtime: Optional[ToolRuntimeContext],
) -> None:
    """Attach correlation metadata to event payloads emitted by tools."""
    correlation = build_runtime_correlation_metadata(runtime)
    if not correlation:
        return

    content = payload.get("content")
    if not isinstance(content, dict):
        return

    existing_metadata = content.get("metadata")
    if isinstance(existing_metadata, dict):
        merged_metadata = dict(existing_metadata)
    else:
        merged_metadata = {}

    for key, value in correlation.items():
        merged_metadata.setdefault(key, value)

    if merged_metadata:
        content["metadata"] = _safe_metadata(merged_metadata)


def filter_tools_for_role(tools: list, user_role: str) -> list:
    """Filter a tool list using ToolRegistry role metadata when available."""
    try:
        from app.engine.tools.registry import get_tool_registry

        registry = get_tool_registry()
    except Exception:
        return list(tools)

    filtered = []
    for tool in tools:
        tool_name = getattr(tool, "name", getattr(tool, "__name__", ""))
        info = registry.get_info(tool_name) if tool_name else None
        if info is None or not getattr(info, "roles", None):
            filtered.append(tool)
            continue
        if user_role in info.roles:
            filtered.append(tool)
    return filtered
