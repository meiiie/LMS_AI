"""Typed external-app integration lane contract for Wiii Connect turns.

OpenHuman keeps the main orchestrator away from broad integration schemas by
first selecting a toolkit/integration boundary, then handing the turn to a
toolkit-scoped worker. Wiii does not yet run a separate worker agent for every
provider, but this lane contract gives the direct runtime the same boundary:
the main chat path sees a lane, not ad hoc provider/tool conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Protocol

from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    WIII_CONNECT_LIST_ACTIONS_TOOL,
)


EXTERNAL_APP_INTEGRATION_LANE_VERSION = "external_app_integration_lane.v1"
EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY = "_external_app_integration_lane"

ExternalAppIntegrationLaneStatus = Literal["not_applicable", "ready", "blocked"]
ExternalAppIntegrationLaneExecutor = Literal[
    "none",
    "provider_worker",
    "specialized_direct_tool",
]


class _ExternalAppActionPlanLike(Protocol):
    status: str
    kind: str
    provider_slug: str
    action_slug: str
    reason: str
    forced_tool_name: str
    allowed_tool_names: tuple[str, ...]
    requested_provider_slugs: tuple[str, ...]
    ready_provider_slugs: tuple[str, ...]
    action_allowlists_by_provider: dict[str, tuple[str, ...]]

    @property
    def ready(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExternalAppIntegrationLane:
    """Prompt/execution boundary for one provider-scoped action lane."""

    version: str
    status: ExternalAppIntegrationLaneStatus
    executor: ExternalAppIntegrationLaneExecutor
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = ""
    visible_tool_names: tuple[str, ...] = ()
    forced_tool_name: str = ""
    requested_provider_slugs: tuple[str, ...] = ()
    ready_provider_slugs: tuple[str, ...] = ()
    action_allowlists_by_provider: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ui_activity_title: str = ""

    @property
    def active(self) -> bool:
        return self.status in {"ready", "blocked"} and self.executor != "none"

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_metadata(self) -> dict[str, Any]:
        """Serialize without prompts, arguments, raw provider payloads, or secrets."""

        return {
            "version": self.version,
            "status": self.status,
            "executor": self.executor,
            "provider_slug": self.provider_slug,
            "action_slug": self.action_slug,
            "reason": self.reason,
            "visible_tool_names": list(self.visible_tool_names),
            "forced_tool_name": self.forced_tool_name,
            "requested_provider_slugs": list(self.requested_provider_slugs),
            "ready_provider_slugs": list(self.ready_provider_slugs),
            "action_allowlists_by_provider": {
                provider: list(actions)
                for provider, actions in sorted(self.action_allowlists_by_provider.items())
            },
            "ui_activity_title": self.ui_activity_title,
        }


def external_app_integration_lane_from_plan(
    plan: _ExternalAppActionPlanLike | None,
) -> ExternalAppIntegrationLane:
    """Convert a provider/action plan into an execution lane."""

    if plan is None or str(getattr(plan, "kind", "")) == "none":
        return ExternalAppIntegrationLane(
            version=EXTERNAL_APP_INTEGRATION_LANE_VERSION,
            status="not_applicable",
            executor="none",
            reason="no_external_app_action_plan",
        )

    status = _safe_status(getattr(plan, "status", "not_applicable"))
    if status == "blocked":
        return ExternalAppIntegrationLane(
            version=EXTERNAL_APP_INTEGRATION_LANE_VERSION,
            status="blocked",
            executor=_executor_for_plan(plan),
            provider_slug=_safe_slug(getattr(plan, "provider_slug", "")),
            action_slug=_safe_action_slug(getattr(plan, "action_slug", "")),
            reason=str(getattr(plan, "reason", "") or "")[:160],
            requested_provider_slugs=_safe_slugs(
                getattr(plan, "requested_provider_slugs", ())
            ),
            ready_provider_slugs=_safe_slugs(getattr(plan, "ready_provider_slugs", ())),
            action_allowlists_by_provider=_safe_action_allowlists(
                getattr(plan, "action_allowlists_by_provider", {})
            ),
            ui_activity_title=_activity_title_for_provider(
                getattr(plan, "provider_slug", "")
            ),
        )

    if not bool(getattr(plan, "ready", False)):
        return ExternalAppIntegrationLane(
            version=EXTERNAL_APP_INTEGRATION_LANE_VERSION,
            status="not_applicable",
            executor="none",
            provider_slug=_safe_slug(getattr(plan, "provider_slug", "")),
            action_slug=_safe_action_slug(getattr(plan, "action_slug", "")),
            reason=str(getattr(plan, "reason", "") or "")[:160],
            requested_provider_slugs=_safe_slugs(
                getattr(plan, "requested_provider_slugs", ())
            ),
        )

    executor = _executor_for_plan(plan)
    visible_tool_names = _visible_tool_names_for_plan(plan, executor)
    forced_tool_name = (
        str(getattr(plan, "forced_tool_name", "") or "").strip()
        if executor == "specialized_direct_tool"
        else ""
    )
    return ExternalAppIntegrationLane(
        version=EXTERNAL_APP_INTEGRATION_LANE_VERSION,
        status="ready",
        executor=executor,
        provider_slug=_safe_slug(getattr(plan, "provider_slug", "")),
        action_slug=_safe_action_slug(getattr(plan, "action_slug", "")),
        reason=str(getattr(plan, "reason", "") or "")[:160],
        visible_tool_names=visible_tool_names,
        forced_tool_name=forced_tool_name,
        requested_provider_slugs=_safe_slugs(
            getattr(plan, "requested_provider_slugs", ())
        ),
        ready_provider_slugs=_safe_slugs(getattr(plan, "ready_provider_slugs", ())),
        action_allowlists_by_provider=_safe_action_allowlists(
            getattr(plan, "action_allowlists_by_provider", {})
        ),
        ui_activity_title=_activity_title_for_provider(
            getattr(plan, "provider_slug", "")
        ),
    )


def select_tools_for_external_app_integration_lane(
    *,
    tools: list[Any],
    lane: ExternalAppIntegrationLane | None,
) -> tuple[list[Any], str | None]:
    """Narrow visible tools using the lane, not provider-specific conditionals."""

    if lane is None:
        return tools, None
    if lane.status == "blocked":
        return [], None
    if not lane.ready:
        return tools, None
    visible = set(lane.visible_tool_names)
    if not visible:
        return [], lane.forced_tool_name or None
    selected = [tool for tool in tools if _tool_name(tool) in visible]
    if lane.executor == "specialized_direct_tool":
        selected = _dedupe_specialized_direct_tools(selected)
    return selected, lane.forced_tool_name or None


def external_app_integration_lane_from_state(
    state: Mapping[str, Any] | None,
) -> ExternalAppIntegrationLane | None:
    if not isinstance(state, Mapping):
        return None
    metadata = state.get(EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY)
    if not isinstance(metadata, Mapping):
        return None
    return ExternalAppIntegrationLane(
        version=str(metadata.get("version") or EXTERNAL_APP_INTEGRATION_LANE_VERSION),
        status=_safe_status(metadata.get("status")),
        executor=_safe_executor(metadata.get("executor")),
        provider_slug=_safe_slug(metadata.get("provider_slug")),
        action_slug=_safe_action_slug(metadata.get("action_slug")),
        reason=str(metadata.get("reason") or "")[:160],
        visible_tool_names=_safe_tool_names(metadata.get("visible_tool_names")),
        forced_tool_name=str(metadata.get("forced_tool_name") or "").strip()[:160],
        requested_provider_slugs=_safe_slugs(metadata.get("requested_provider_slugs")),
        ready_provider_slugs=_safe_slugs(metadata.get("ready_provider_slugs")),
        action_allowlists_by_provider=_safe_action_allowlists(
            metadata.get("action_allowlists_by_provider")
        ),
        ui_activity_title=str(metadata.get("ui_activity_title") or "")[:160],
    )


def record_external_app_integration_lane(
    state: dict[str, Any] | None,
    lane: ExternalAppIntegrationLane,
) -> None:
    if isinstance(state, dict):
        state[EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY] = lane.to_metadata()


def _executor_for_plan(
    plan: _ExternalAppActionPlanLike,
) -> ExternalAppIntegrationLaneExecutor:
    kind = str(getattr(plan, "kind", "") or "")
    if kind == "facebook_post_direct_apply":
        return "specialized_direct_tool"
    if kind == "provider_action":
        return "provider_worker"
    return "none"


def _visible_tool_names_for_plan(
    plan: _ExternalAppActionPlanLike,
    executor: ExternalAppIntegrationLaneExecutor,
) -> tuple[str, ...]:
    if executor == "specialized_direct_tool":
        forced = str(getattr(plan, "forced_tool_name", "") or "").strip()
        if forced:
            return (forced,)
        return (WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,)
    if executor == "provider_worker":
        allowed = _safe_tool_names(getattr(plan, "allowed_tool_names", ()))
        if allowed:
            return tuple(dict.fromkeys((WIII_CONNECT_LIST_ACTIONS_TOOL, *allowed)))
        return (
            WIII_CONNECT_LIST_ACTIONS_TOOL,
            WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        )
    return ()


def _activity_title_for_provider(provider_slug: Any) -> str:
    provider = _safe_slug(provider_slug)
    if provider == "facebook":
        return "Working with your Facebook connection"
    if provider:
        return f"Working with your {provider} connection"
    return "Checking your connected app"


def _tool_name(tool: object) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def _dedupe_specialized_direct_tools(tools: list[Any]) -> list[Any]:
    """Keep one owner per specialized action, preferring the backend gateway."""

    by_name: dict[str, Any] = {}
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        existing = by_name.get(name)
        if existing is None or _is_backend_gateway_tool(tool):
            by_name[name] = tool
    return list(by_name.values())


def _is_backend_gateway_tool(tool: object) -> bool:
    return str(getattr(tool, "wiii_connect_action_owner", "") or "") == "backend_gateway"


def _safe_status(value: Any) -> ExternalAppIntegrationLaneStatus:
    status = str(value or "").strip()
    if status in {"not_applicable", "ready", "blocked"}:
        return status  # type: ignore[return-value]
    return "not_applicable"


def _safe_executor(value: Any) -> ExternalAppIntegrationLaneExecutor:
    executor = str(value or "").strip()
    if executor in {"none", "provider_worker", "specialized_direct_tool"}:
        return executor  # type: ignore[return-value]
    return "none"


def _safe_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _safe_action_slug(value: Any) -> str:
    return str(value or "").strip()[:160]


def _safe_slugs(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    result: list[str] = []
    for value in values:
        slug = _safe_slug(value)
        if slug and slug not in result:
            result.append(slug)
    return tuple(result)


def _safe_tool_names(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    result: list[str] = []
    for value in values:
        name = str(value or "").strip()[:160]
        if name and name not in result:
            result.append(name)
    return tuple(result)


def _safe_action_allowlists(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for provider, actions in value.items():
        provider_slug = _safe_slug(provider)
        action_slugs = _safe_tool_names(actions)
        if provider_slug and action_slugs:
            result[provider_slug] = action_slugs
    return result


__all__ = [
    "EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY",
    "EXTERNAL_APP_INTEGRATION_LANE_VERSION",
    "ExternalAppIntegrationLane",
    "external_app_integration_lane_from_plan",
    "external_app_integration_lane_from_state",
    "record_external_app_integration_lane",
    "select_tools_for_external_app_integration_lane",
]
