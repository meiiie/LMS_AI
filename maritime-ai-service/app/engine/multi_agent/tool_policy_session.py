"""Per-turn tool policy sessions for prompt visibility and execution guards."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from app.engine.multi_agent.turn_path_governor import TurnPathDecision
from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot
from app.engine.wiii_connect.connection_lifecycle import (
    sanitize_connection_lifecycle_metadata,
)
from app.engine.tools.tool_capability_registry import (
    approval_required_tool_names_for,
    lookup_tool_capability,
    tool_capability_metadata_for_names,
    tool_requires_inactive_connection,
)


TOOL_POLICY_SESSION_VERSION = "tool_policy_session.v1"
TOOL_POLICY_STATE_KEY = "_tool_policy_session"
EXTERNAL_APP_ACTION_PLAN_STATE_KEY = "_external_app_action_plan"
EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY = "_external_app_integration_lane"


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
    external_app_action_plan: dict[str, Any] | None = None
    external_app_integration_lane: dict[str, Any] | None = None
    approval_required_tool_names: frozenset[str] = frozenset()
    tool_capabilities: dict[str, dict[str, Any]] | None = None
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
        if not self._surface_scope_allows(name):
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
        if not self._surface_scope_allows(name):
            return ToolPolicyDecision(
                tool_name=name,
                allowed=False,
                reason="surface_scope_not_allowed",
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
            "external_app_action_plan": _plain_external_app_action_plan(
                self.external_app_action_plan
            ),
            "external_app_integration_lane": _plain_external_app_integration_lane(
                self.external_app_integration_lane
            ),
            "approval_required_tool_names": sorted(self.approval_required_tool_names),
            "tool_capabilities": dict(self.tool_capabilities or {}),
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
            external_app_action_plan=_plain_external_app_action_plan(
                metadata.get("external_app_action_plan")
            ),
            external_app_integration_lane=_plain_external_app_integration_lane(
                metadata.get("external_app_integration_lane")
            ),
            approval_required_tool_names=_frozen_name_set(
                metadata.get("approval_required_tool_names")
            ),
            tool_capabilities=_plain_tool_capabilities(metadata.get("tool_capabilities")),
            allow_agent_handoff=bool(metadata.get("allow_agent_handoff", True)),
            allow_rag_delegation=bool(metadata.get("allow_rag_delegation", False)),
        )

    def _requires_inactive_connection(self, tool_name: str) -> bool:
        return tool_requires_inactive_connection(
            tool_name,
            self.connection_status or {},
        )

    def _surface_scope_allows(self, tool_name: str) -> bool:
        capabilities = self.tool_capabilities or {}
        name = _normalize_tool_name(tool_name)
        metadata = capabilities.get(name)
        if not isinstance(metadata, dict):
            capability = lookup_tool_capability(name)
            metadata = capability.to_metadata() if capability is not None else None
        if not isinstance(metadata, dict):
            return True
        scopes = {
            str(scope or "").strip()
            for scope in metadata.get("surface_scopes") or ()
            if str(scope or "").strip()
        }
        if not scopes:
            return True
        required_scopes = _required_surface_scopes_for_path(self.path)
        return bool(scopes.intersection(required_scopes))


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
    approval_required_names = approval_required_tool_names_for(normalized_candidates)
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
        external_app_action_plan=_external_app_action_plan_for_turn(state),
        external_app_integration_lane=_external_app_integration_lane_for_turn(state),
        approval_required_tool_names=approval_required_names,
        tool_capabilities=tool_capability_metadata_for_names(normalized_candidates),
        allow_agent_handoff=decision.allow_agent_handoff,
        allow_rag_delegation=decision.allow_rag_delegation,
    )


def build_visible_tool_policy_session(
    *,
    path: str,
    reason: str,
    state: dict[str, Any] | None,
    query: str = "",
    candidate_tool_names: list[str] | tuple[str, ...] | set[str] = (),
    visible_tool_names: list[str] | tuple[str, ...] | set[str] | None = None,
    force_tools: bool = False,
) -> ToolPolicySession:
    """Build a policy session for runtimes that already selected visible tools."""

    normalized_candidates = frozenset(
        _normalize_tool_name(name) for name in candidate_tool_names if _normalize_tool_name(name)
    )
    normalized_visible = frozenset(
        _normalize_tool_name(name)
        for name in (visible_tool_names if visible_tool_names is not None else normalized_candidates)
        if _normalize_tool_name(name)
    )
    connection_status = _connection_status_for_turn(state=state, query=query)
    return ToolPolicySession(
        version=TOOL_POLICY_SESSION_VERSION,
        path=str(path or "unknown"),
        reason=str(reason or ""),
        bind_tools=bool(normalized_visible),
        force_tools=bool(force_tools),
        allow_all_tools=False,
        allowed_tool_names=normalized_visible,
        candidate_tool_names=normalized_candidates,
        visible_tool_names=normalized_visible,
        connection_status=connection_status,
        external_app_action_plan=_external_app_action_plan_for_turn(state),
        external_app_integration_lane=_external_app_integration_lane_for_turn(state),
        approval_required_tool_names=approval_required_tool_names_for(normalized_candidates),
        tool_capabilities=tool_capability_metadata_for_names(normalized_candidates),
        allow_agent_handoff=False,
        allow_rag_delegation=False,
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


def resolve_tool_policy_denial(
    state: dict[str, Any] | None,
    tool_name: str,
) -> tuple[ToolPolicyDecision, str] | None:
    """Return a policy denial decision/message for a runtime tool call."""

    session = tool_policy_session_from_state(state)
    if session is None:
        return None
    decision = session.decision_for(tool_name)
    if decision.allowed:
        return None
    return decision, tool_policy_denial_message(decision)


def _required_surface_scopes_for_path(path: str) -> frozenset[str]:
    normalized = str(path or "").strip()
    if normalized == "product_search":
        return frozenset({"product_search"})
    if normalized in {"code_studio", "code_execution"}:
        return frozenset({"code_studio"})
    if normalized == "tutor":
        return frozenset({"tutor", "direct_chat", "visual"})
    if normalized == "visual_generation":
        return frozenset({"visual", "direct_chat"})
    return frozenset({"direct_chat"})


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
    return build_wiii_connect_snapshot(state=state, query=query).connection_status_map()


def _external_app_action_plan_for_turn(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    value = state.get(EXTERNAL_APP_ACTION_PLAN_STATE_KEY)
    if not isinstance(value, dict):
        return {}
    return _plain_external_app_action_plan(value)


def _external_app_integration_lane_for_turn(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    value = state.get(EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY)
    if not isinstance(value, dict):
        return {}
    return _plain_external_app_integration_lane(value)


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


def _plain_tool_capabilities(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    plain: dict[str, dict[str, Any]] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            plain[_normalize_tool_name(key)] = dict(item)
    return plain


def _plain_external_app_action_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_keys = {
        "version",
        "status",
        "kind",
        "provider_slug",
        "action_slug",
        "reason",
        "forced_tool_name",
        "allowed_tool_names",
        "requested_provider_slugs",
        "ready_provider_slugs",
        "action_allowlists_by_provider",
        "connection_lifecycle",
        "unavailable_answer_present",
    }
    result = {str(key): item for key, item in value.items() if str(key) in allowed_keys}
    lifecycle = sanitize_connection_lifecycle_metadata(value.get("connection_lifecycle"))
    if lifecycle:
        result["connection_lifecycle"] = lifecycle
    else:
        result.pop("connection_lifecycle", None)
    return result


def _plain_external_app_integration_lane(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_keys = {
        "version",
        "status",
        "executor",
        "provider_slug",
        "action_slug",
        "reason",
        "visible_tool_names",
        "forced_tool_name",
        "requested_provider_slugs",
        "ready_provider_slugs",
        "action_allowlists_by_provider",
        "ui_activity_title",
    }
    return {str(key): item for key, item in value.items() if str(key) in allowed_keys}
