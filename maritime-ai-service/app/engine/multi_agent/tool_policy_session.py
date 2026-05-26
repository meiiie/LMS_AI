"""Per-turn tool policy sessions for prompt visibility and execution guards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from app.core.config import settings
from app.engine.multi_agent.document_preview_contract import (
    LMS_AUTHORING_CAPABILITY_NAMES,
    lms_authoring_connection_status,
)
from app.engine.multi_agent.turn_path_governor import TurnPathDecision


TOOL_POLICY_SESSION_VERSION = "tool_policy_session.v1"
TOOL_POLICY_STATE_KEY = "_tool_policy_session"

HOST_ACTION_PREFIX = "host_action__"
LMS_AUTHORING_PREFIX = "host_action__authoring__"
POINTY_PREFIX = "tool_pointy_"
WEATHER_TOOL_NAME = "tool_current_weather"


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    """Decision for one tool under the active policy session."""

    tool_name: str
    allowed: bool
    reason: str
    path: str
    visible: bool = False


@dataclass(frozen=True, slots=True)
class ToolPolicySession:
    """Immutable policy for tool visibility and execution in one turn."""

    version: str
    path: str
    reason: str
    bind_tools: bool
    force_tools: bool
    allow_all_tools: bool
    allowed_tool_names: frozenset[str] = frozenset()
    allowed_tool_prefixes: tuple[str, ...] = ()
    forbidden_tool_names: frozenset[str] = frozenset()
    forbidden_tool_prefixes: tuple[str, ...] = ()
    candidate_tool_names: frozenset[str] = frozenset()
    visible_tool_names: frozenset[str] = frozenset()
    connection_status: dict[str, dict[str, Any]] | None = None
    approval_required_tool_names: frozenset[str] = frozenset()
    allow_agent_handoff: bool = True
    allow_rag_delegation: bool = False

    def should_expose_tool(self, tool_name: str) -> bool:
        """Return whether a tool can be shown to the model for this turn."""

        name = _normalize_tool_name(tool_name)
        if not name or not self.bind_tools:
            return False
        if name in self.forbidden_tool_names:
            return False
        if any(name.startswith(prefix) for prefix in self.forbidden_tool_prefixes):
            return False
        if self._requires_inactive_connection(name):
            return False
        if self.allow_all_tools:
            return True
        if name in self.allowed_tool_names:
            return True
        return any(name.startswith(prefix) for prefix in self.allowed_tool_prefixes)

    def decision_for(self, tool_name: str) -> ToolPolicyDecision:
        """Return execution-time policy for a normalized tool call."""

        name = _normalize_tool_name(tool_name)
        if not name:
            return ToolPolicyDecision(
                tool_name=name,
                allowed=False,
                reason="missing_tool_name",
                path=self.path,
                visible=False,
            )
        if not self.should_expose_tool(name):
            return ToolPolicyDecision(
                tool_name=name,
                allowed=False,
                reason="not_allowed_by_path_policy",
                path=self.path,
                visible=False,
            )
        visible = name in self.visible_tool_names
        if self.visible_tool_names and not visible:
            return ToolPolicyDecision(
                tool_name=name,
                allowed=False,
                reason="not_visible_in_bound_tool_set",
                path=self.path,
                visible=False,
            )
        return ToolPolicyDecision(
            tool_name=name,
            allowed=True,
            reason="allowed",
            path=self.path,
            visible=visible,
        )

    def with_visible_tools(self, tool_names: list[str] | tuple[str, ...] | set[str]) -> "ToolPolicySession":
        """Return a copy with final bound tool names recorded."""

        visible = frozenset(_normalize_tool_name(name) for name in tool_names if _normalize_tool_name(name))
        return replace(self, visible_tool_names=visible)

    def to_metadata(self) -> dict[str, Any]:
        """Serialize to state-safe metadata."""

        return {
            "version": self.version,
            "path": self.path,
            "reason": self.reason,
            "bind_tools": self.bind_tools,
            "force_tools": self.force_tools,
            "allow_all_tools": self.allow_all_tools,
            "allowed_tool_names": sorted(self.allowed_tool_names),
            "allowed_tool_prefixes": list(self.allowed_tool_prefixes),
            "forbidden_tool_names": sorted(self.forbidden_tool_names),
            "forbidden_tool_prefixes": list(self.forbidden_tool_prefixes),
            "candidate_tool_names": sorted(self.candidate_tool_names),
            "visible_tool_names": sorted(self.visible_tool_names),
            "connection_status": dict(self.connection_status or {}),
            "approval_required_tool_names": sorted(self.approval_required_tool_names),
            "allow_agent_handoff": self.allow_agent_handoff,
            "allow_rag_delegation": self.allow_rag_delegation,
        }

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> "ToolPolicySession":
        """Rehydrate policy metadata stored in AgentState."""

        return cls(
            version=str(metadata.get("version") or TOOL_POLICY_SESSION_VERSION),
            path=str(metadata.get("path") or "unknown"),
            reason=str(metadata.get("reason") or ""),
            bind_tools=bool(metadata.get("bind_tools", True)),
            force_tools=bool(metadata.get("force_tools", False)),
            allow_all_tools=bool(metadata.get("allow_all_tools", True)),
            allowed_tool_names=_frozen_name_set(metadata.get("allowed_tool_names")),
            allowed_tool_prefixes=_name_tuple(metadata.get("allowed_tool_prefixes")),
            forbidden_tool_names=_frozen_name_set(metadata.get("forbidden_tool_names")),
            forbidden_tool_prefixes=_name_tuple(metadata.get("forbidden_tool_prefixes")),
            candidate_tool_names=_frozen_name_set(metadata.get("candidate_tool_names")),
            visible_tool_names=_frozen_name_set(metadata.get("visible_tool_names")),
            connection_status=_plain_connection_status(metadata.get("connection_status")),
            approval_required_tool_names=_frozen_name_set(
                metadata.get("approval_required_tool_names")
            ),
            allow_agent_handoff=bool(metadata.get("allow_agent_handoff", True)),
            allow_rag_delegation=bool(metadata.get("allow_rag_delegation", False)),
        )

    def _requires_inactive_connection(self, tool_name: str) -> bool:
        if _is_lms_authoring_tool(tool_name):
            status = (self.connection_status or {}).get("lms_authoring") or {}
            return not bool(status.get("active"))
        return False


def build_tool_policy_session(
    *,
    decision: TurnPathDecision,
    state: dict[str, Any] | None,
    query: str = "",
    user_role: str = "student",
    candidate_tool_names: list[str] | tuple[str, ...] | set[str] = (),
) -> ToolPolicySession:
    """Build the authoritative per-turn tool policy session."""

    normalized_candidates = frozenset(
        _normalize_tool_name(name) for name in candidate_tool_names if _normalize_tool_name(name)
    )
    connection_status = _connection_status_for_turn(state=state, query=query)
    approval_required_names = frozenset(
        name for name in normalized_candidates if _requires_approval_token(name)
    )
    return ToolPolicySession(
        version=TOOL_POLICY_SESSION_VERSION,
        path=decision.path,
        reason=decision.reason,
        bind_tools=decision.bind_tools,
        force_tools=decision.force_tools,
        allow_all_tools=decision.allow_all_tools,
        allowed_tool_names=frozenset(decision.allowed_tool_names),
        allowed_tool_prefixes=tuple(decision.allowed_tool_prefixes),
        forbidden_tool_names=frozenset(decision.forbidden_tool_names),
        forbidden_tool_prefixes=tuple(decision.forbidden_tool_prefixes),
        candidate_tool_names=normalized_candidates,
        connection_status=connection_status,
        approval_required_tool_names=approval_required_names,
        allow_agent_handoff=decision.allow_agent_handoff,
        allow_rag_delegation=decision.allow_rag_delegation,
    )


def record_tool_policy_session(
    state: dict[str, Any] | None,
    session: ToolPolicySession,
) -> None:
    if isinstance(state, dict):
        state[TOOL_POLICY_STATE_KEY] = session.to_metadata()


def tool_policy_session_from_state(state: dict[str, Any] | None) -> ToolPolicySession | None:
    """Read the active policy session from AgentState, if present."""

    if not isinstance(state, dict):
        return None
    metadata = state.get(TOOL_POLICY_STATE_KEY)
    if isinstance(metadata, dict):
        return ToolPolicySession.from_metadata(metadata)

    legacy_decision = state.get("_turn_path_decision")
    if isinstance(legacy_decision, dict):
        return ToolPolicySession.from_metadata(
            {
                "path": legacy_decision.get("path"),
                "reason": legacy_decision.get("reason"),
                "bind_tools": legacy_decision.get("bind_tools", True),
                "force_tools": legacy_decision.get("force_tools", False),
                "allow_all_tools": legacy_decision.get("allow_all_tools", True),
                "allowed_tool_names": legacy_decision.get("allowed_tool_names") or [],
                "allowed_tool_prefixes": legacy_decision.get("allowed_tool_prefixes") or [],
                "forbidden_tool_names": legacy_decision.get("forbidden_tool_names") or [],
                "forbidden_tool_prefixes": legacy_decision.get("forbidden_tool_prefixes") or [],
                "allow_agent_handoff": legacy_decision.get("allow_agent_handoff", True),
                "allow_rag_delegation": legacy_decision.get("allow_rag_delegation", False),
            }
        )
    return None


def filter_tools_for_policy_session(
    tools: list[Any],
    session: ToolPolicySession,
    *,
    tool_name: Callable[[Any], str],
) -> list[Any]:
    """Apply prompt-visibility policy to a candidate tool list."""

    return [
        tool
        for tool in tools
        if session.should_expose_tool(tool_name(tool))
    ]


def finalize_tool_policy_visible_tools(
    state: dict[str, Any] | None,
    tools: list[Any],
    *,
    tool_name: Callable[[Any], str],
) -> ToolPolicySession | None:
    """Record the final bound tool set after runtime pruning."""

    session = tool_policy_session_from_state(state)
    if session is None:
        return None
    visible_names = [tool_name(tool) for tool in tools]
    updated = session.with_visible_tools(visible_names)
    record_tool_policy_session(state, updated)
    return updated


def tool_policy_denial_message(decision: ToolPolicyDecision) -> str:
    """User-visible tool result when execution is denied by policy."""

    return (
        "Tool bị chặn bởi chính sách lượt hiện tại: "
        f"`{decision.tool_name}` không thuộc path `{decision.path}` "
        f"({decision.reason})."
    )


def _connection_status_for_turn(
    *,
    state: dict[str, Any] | None,
    query: str,
) -> dict[str, dict[str, Any]]:
    lms_status = lms_authoring_connection_status(
        state,
        (state or {}).get("context") if isinstance((state or {}).get("context"), dict) else {},
    )
    return {
        "lms_authoring": lms_status,
        "weather": _weather_connection_status(),
        "host_actions": _host_action_connection_status(state),
        "query": {
            "active": bool(str(query or "").strip()),
            "reason": "present" if str(query or "").strip() else "missing_query",
        },
    }


def _weather_connection_status() -> dict[str, Any]:
    enabled = bool(getattr(settings, "living_agent_enable_weather", False))
    has_provider = bool(str(getattr(settings, "living_agent_weather_api_key", "") or "").strip())
    active = enabled and has_provider
    return {
        "active": active,
        "reason": "active" if active else "missing_weather_provider",
        "fail_closed_tool": True,
        "default_city": str(getattr(settings, "living_agent_weather_city", "") or "").strip() or None,
    }


def _host_action_connection_status(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {"active": False, "reason": "missing_state"}
    host_capabilities = state.get("host_capabilities")
    if not isinstance(host_capabilities, dict):
        context = state.get("context")
        if isinstance(context, dict):
            host_capabilities = context.get("host_capabilities")
    if not isinstance(host_capabilities, dict):
        return {"active": False, "reason": "missing_host_capabilities"}
    tools = host_capabilities.get("tools")
    tool_count = len(tools) if isinstance(tools, list) else 0
    return {
        "active": tool_count > 0,
        "reason": "active" if tool_count > 0 else "missing_host_tools",
        "tool_count": tool_count,
    }


def _is_lms_authoring_tool(tool_name: str) -> bool:
    if not tool_name.startswith(LMS_AUTHORING_PREFIX):
        return False
    action_name = tool_name.removeprefix(HOST_ACTION_PREFIX).replace("__", ".")
    return action_name in LMS_AUTHORING_CAPABILITY_NAMES


def _requires_approval_token(tool_name: str) -> bool:
    normalized = tool_name.strip().lower()
    return normalized.endswith("apply_lesson_patch") or normalized.endswith("apply_course_plan")


def _normalize_tool_name(value: Any) -> str:
    return str(value or "").strip()


def _frozen_name_set(value: Any) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(_normalize_tool_name(item) for item in value if _normalize_tool_name(item))


def _name_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(_normalize_tool_name(item) for item in value if _normalize_tool_name(item))


def _plain_connection_status(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    plain: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            plain[str(key)] = dict(item)
    return plain
