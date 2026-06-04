"""Provider-scoped external app action planning for direct chat turns.

This module is the direct-chat analogue of OpenHuman's integration-agent gate:
choose the external provider/action boundary first, then let tool collection and
tool-round execution bind only the tools allowed for that boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

from app.engine.multi_agent.external_app_integration_lane import (
    EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY,
    ExternalAppIntegrationLane,
    external_app_integration_lane_from_plan,
    record_external_app_integration_lane,
    select_tools_for_external_app_integration_lane,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.wiii_connect_intent import (
    build_wiii_connect_facebook_post_unavailable_answer,
    build_wiii_connect_provider_status_answer,
    looks_wiii_connect_external_app_action_request_for_state,
    looks_wiii_connect_facebook_post_request_for_state,
    resolve_wiii_connect_target_provider_slugs_for_state,
    wiii_connect_provider_connection_lifecycle_from_state,
)
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
)
from app.engine.wiii_connect.connection_lifecycle import (
    sanitize_connection_lifecycle_metadata,
)


EXTERNAL_APP_ACTION_PLAN_VERSION = "external_app_action_plan.v1"
EXTERNAL_APP_ACTION_PLAN_STATE_KEY = "_external_app_action_plan"
_FACEBOOK_POST_ACTION_SLUGS = frozenset(
    {
        "FACEBOOK_CREATE_POST",
        "FACEBOOK_CREATE_PHOTO_POST",
    }
)

ExternalAppActionPlanStatus = Literal["not_applicable", "ready", "blocked"]
ExternalAppActionPlanKind = Literal[
    "none",
    "facebook_post_direct_apply",
    "provider_action",
]


@dataclass(frozen=True, slots=True)
class ExternalAppActionPlan:
    """Policy-safe plan for one external app action turn."""

    version: str
    status: ExternalAppActionPlanStatus
    kind: ExternalAppActionPlanKind
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = ""
    forced_tool_name: str = ""
    allowed_tool_names: tuple[str, ...] = ()
    requested_provider_slugs: tuple[str, ...] = ()
    ready_provider_slugs: tuple[str, ...] = ()
    action_allowlists_by_provider: dict[str, tuple[str, ...]] = field(default_factory=dict)
    connection_lifecycle: dict[str, Any] = field(default_factory=dict)
    unavailable_answer: str = ""

    @property
    def active(self) -> bool:
        return self.status in {"ready", "blocked"} and self.kind != "none"

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_metadata(self) -> dict[str, Any]:
        """Serialize without raw prompts, arguments, tokens, or provider payloads."""

        metadata = {
            "version": self.version,
            "status": self.status,
            "kind": self.kind,
            "provider_slug": self.provider_slug,
            "action_slug": self.action_slug,
            "reason": self.reason,
            "forced_tool_name": self.forced_tool_name,
            "allowed_tool_names": list(self.allowed_tool_names),
            "requested_provider_slugs": list(self.requested_provider_slugs),
            "ready_provider_slugs": list(self.ready_provider_slugs),
            "action_allowlists_by_provider": {
                provider: list(actions)
                for provider, actions in sorted(self.action_allowlists_by_provider.items())
            },
            "unavailable_answer_present": bool(self.unavailable_answer),
        }
        lifecycle = sanitize_connection_lifecycle_metadata(self.connection_lifecycle)
        if lifecycle:
            metadata["connection_lifecycle"] = lifecycle
        return metadata


@dataclass(frozen=True, slots=True)
class ExternalAppActionTurnPreparation:
    """Prepared direct-loop state for one external app action turn."""

    plan: ExternalAppActionPlan
    integration_lane: ExternalAppIntegrationLane
    tools: list[Any]
    forced_tool_choice: str | None = None
    preflight_response: Any | None = None

    @property
    def preempted(self) -> bool:
        return self.preflight_response is not None


def resolve_external_app_action_plan(
    *,
    query: str,
    state: AgentState | None,
    ready_provider_slugs: Iterable[str] | None = None,
    action_allowlists_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> ExternalAppActionPlan:
    """Return the external app action plan for a direct chat turn."""

    ready_providers = (
        _normalized_slugs(ready_provider_slugs)
        if ready_provider_slugs is not None
        else _ready_provider_slugs_from_state(state, query)
    )
    requested_providers = resolve_wiii_connect_target_provider_slugs_for_state(
        query,
        state if isinstance(state, dict) else None,
    )
    action_allowlists = (
        _normalize_action_allowlists(action_allowlists_by_provider)
        if action_allowlists_by_provider is not None
        else _action_allowlists_for_providers(ready_providers, state=state)
    )
    if looks_wiii_connect_facebook_post_request_for_state(
        query,
        state if isinstance(state, dict) else None,
    ):
        if ready_provider_slugs is not None:
            if "facebook" not in ready_providers:
                return _blocked_facebook_plan(
                    reason="provider_not_agent_ready",
                    requested_provider_slugs=requested_providers or ("facebook",),
                    ready_provider_slugs=ready_providers,
                    action_allowlists_by_provider=action_allowlists,
                    state=state,
                    unavailable_answer=(
                        build_wiii_connect_facebook_post_unavailable_answer(
                            state if isinstance(state, dict) else {}
                        )
                        or ""
                    ),
                )
            if not _has_action_allowlist(
                action_allowlists,
                "facebook",
                _FACEBOOK_POST_ACTION_SLUGS,
            ):
                return _blocked_facebook_plan(
                    reason="no_agent_ready_actions",
                    requested_provider_slugs=requested_providers or ("facebook",),
                    ready_provider_slugs=ready_providers,
                    action_allowlists_by_provider=action_allowlists,
                    state=state,
                    unavailable_answer=_facebook_no_agent_ready_actions_answer(),
                )
            return _ready_facebook_plan(
                requested_provider_slugs=requested_providers or ("facebook",),
                ready_provider_slugs=ready_providers,
                action_allowlists_by_provider=action_allowlists,
            )

        unavailable_answer = build_wiii_connect_facebook_post_unavailable_answer(
            state if isinstance(state, dict) else {}
        )
        if unavailable_answer:
            return _blocked_facebook_plan(
                reason="provider_not_agent_ready",
                requested_provider_slugs=requested_providers or ("facebook",),
                ready_provider_slugs=ready_providers,
                action_allowlists_by_provider=action_allowlists,
                state=state,
                unavailable_answer=unavailable_answer,
            )

        if not _has_action_allowlist(
            action_allowlists,
            "facebook",
            _FACEBOOK_POST_ACTION_SLUGS,
        ):
            return _blocked_facebook_plan(
                reason="no_agent_ready_actions",
                requested_provider_slugs=requested_providers or ("facebook",),
                ready_provider_slugs=ready_providers,
                action_allowlists_by_provider=action_allowlists,
                state=state,
                unavailable_answer=_facebook_no_agent_ready_actions_answer(),
            )

        return _ready_facebook_plan(
            requested_provider_slugs=requested_providers or ("facebook",),
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
        )

    if not looks_wiii_connect_external_app_action_request_for_state(
        query,
        state if isinstance(state, dict) else None,
    ):
        return ExternalAppActionPlan(
            version=EXTERNAL_APP_ACTION_PLAN_VERSION,
            status="not_applicable",
            kind="none",
            reason="no_external_app_action_intent",
            requested_provider_slugs=requested_providers,
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
        )

    if len(requested_providers) > 1:
        return _blocked_provider_action_plan(
            reason="ambiguous_provider_target",
            provider_slug="",
            requested_provider_slugs=requested_providers,
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
            state=state,
        )

    target_provider = requested_providers[0] if requested_providers else ""
    if not target_provider:
        return _blocked_provider_action_plan(
            reason="missing_provider_target",
            provider_slug="",
            requested_provider_slugs=requested_providers,
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
            state=state,
        )

    if target_provider not in ready_providers:
        return _blocked_provider_action_plan(
            reason="provider_not_agent_ready",
            provider_slug=target_provider,
            requested_provider_slugs=requested_providers,
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
            state=state,
        )

    target_action_allowlists = _scope_action_allowlists(action_allowlists, target_provider)
    if not target_action_allowlists:
        return _blocked_provider_action_plan(
            reason="no_agent_ready_actions",
            provider_slug=target_provider,
            requested_provider_slugs=requested_providers,
            ready_provider_slugs=ready_providers,
            action_allowlists_by_provider=action_allowlists,
            state=state,
        )

    return ExternalAppActionPlan(
        version=EXTERNAL_APP_ACTION_PLAN_VERSION,
        status="ready",
        kind="provider_action",
        provider_slug=target_provider,
        reason="registered_provider_action_request",
        allowed_tool_names=(WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,),
        requested_provider_slugs=requested_providers,
        ready_provider_slugs=ready_providers,
        action_allowlists_by_provider=target_action_allowlists,
    )


def prepare_external_app_action_turn(
    *,
    query: str,
    state: AgentState | None,
    tools: list[Any],
    forced_tool_choice: str | None,
    native_tool_messages: bool,
    build_assistant_message,
) -> ExternalAppActionTurnPreparation:
    """Prepare an external action turn before the direct loop invokes the model."""

    plan = external_app_action_plan_from_state(state)
    if plan is None:
        plan = resolve_external_app_action_plan(
            query=query,
            state=state,
            ready_provider_slugs=None,
        )
        record_external_app_action_plan(state, plan)

    if plan.status == "blocked":
        unavailable_answer = plan.unavailable_answer or _blocked_plan_unavailable_answer(
            plan,
            state=state,
        )
        return ExternalAppActionTurnPreparation(
            plan=plan,
            integration_lane=external_app_integration_lane_from_plan(plan),
            tools=tools,
            forced_tool_choice=forced_tool_choice,
            preflight_response=build_assistant_message(
                unavailable_answer,
                native_tool_messages=native_tool_messages,
            ),
        )

    integration_lane = external_app_integration_lane_from_plan(plan)
    record_external_app_integration_lane(
        state if isinstance(state, dict) else None,
        integration_lane,
    )
    prepared_tools, prepared_forced_tool_choice = (
        select_tools_for_external_app_integration_lane(
            tools=tools,
            lane=integration_lane,
        )
    )
    return ExternalAppActionTurnPreparation(
        plan=plan,
        integration_lane=integration_lane,
        tools=prepared_tools,
        forced_tool_choice=prepared_forced_tool_choice or forced_tool_choice,
    )


def record_external_app_action_plan(
    state: AgentState | None,
    plan: ExternalAppActionPlan,
) -> None:
    """Store the active plan in AgentState for policy and diagnostics."""

    if isinstance(state, dict):
        state[EXTERNAL_APP_ACTION_PLAN_STATE_KEY] = plan.to_metadata()
        record_external_app_integration_lane(
            state,
            external_app_integration_lane_from_plan(plan),
        )


def external_app_action_plan_from_state(
    state: AgentState | None,
) -> ExternalAppActionPlan | None:
    """Read a previously recorded external app action plan."""

    if not isinstance(state, dict):
        return None
    metadata = state.get(EXTERNAL_APP_ACTION_PLAN_STATE_KEY)
    if not isinstance(metadata, dict):
        return None
    return ExternalAppActionPlan(
        version=str(metadata.get("version") or EXTERNAL_APP_ACTION_PLAN_VERSION),
        status=_safe_status(metadata.get("status")),
        kind=_safe_kind(metadata.get("kind")),
        provider_slug=_safe_slug(metadata.get("provider_slug")),
        action_slug=str(metadata.get("action_slug") or "").strip()[:160],
        reason=str(metadata.get("reason") or "").strip()[:160],
        forced_tool_name=str(metadata.get("forced_tool_name") or "").strip()[:160],
        allowed_tool_names=_safe_tool_names(metadata.get("allowed_tool_names")),
        requested_provider_slugs=_safe_slugs(metadata.get("requested_provider_slugs")),
        ready_provider_slugs=_safe_slugs(metadata.get("ready_provider_slugs")),
        action_allowlists_by_provider=_safe_action_allowlists(
            metadata.get("action_allowlists_by_provider")
        ),
        connection_lifecycle=sanitize_connection_lifecycle_metadata(
            metadata.get("connection_lifecycle")
        ),
        unavailable_answer="",
    )


def force_tools_for_external_app_action_plan(
    *,
    tools: list[Any],
    plan: ExternalAppActionPlan | None,
) -> tuple[list[Any], str | None]:
    """Narrow a mixed tool bundle to the planned external action tools."""

    if plan is None or not plan.ready:
        return tools, None
    lane = external_app_integration_lane_from_plan(plan)
    return select_tools_for_external_app_integration_lane(tools=tools, lane=lane)


def external_app_action_final_answer(
    tool_call_events: list[dict[str, Any]],
) -> str:
    """Return stable final prose for Wiii Connect action result envelopes."""

    for event in reversed(tool_call_events):
        if event.get("type") != "result":
            continue
        payload = _parse_tool_result_payload(event.get("result"))
        if not _is_wiii_connect_action_payload(payload):
            continue
        return _final_answer_for_payload(payload)
    return ""


def facebook_direct_apply_final_answer(
    tool_call_events: list[dict[str, Any]],
) -> str:
    """Compatibility wrapper for existing direct Facebook publish tests."""

    saw_direct_apply = any(
        event.get("name") == WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
        for event in tool_call_events
    )
    if not saw_direct_apply:
        return ""

    for event in reversed(tool_call_events):
        if (
            event.get("type") != "result"
            or event.get("name") != WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL
        ):
            continue
        payload = _parse_tool_result_payload(event.get("result"))
        localized = _localized_final_answer_for_payload(
            {
                **payload,
                "provider_slug": payload.get("provider_slug") or "facebook",
                "action": payload.get("action") or WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
            }
        )
        if localized:
            return localized
        status = str(payload.get("status") or "").strip()
        if status == "action_completed":
            summary = str(payload.get("summary") or "").strip()
            if summary:
                return summary
            return "Đã đăng bài lên Facebook qua Wiii Connect."
        if status == "action_failed":
            reason = str(payload.get("error") or payload.get("summary") or "").strip()
            suffix = f": {reason}" if reason else "."
            return f"Facebook chưa đăng được{suffix}"
        if status == "action_requested":
            return (
                "Mình đã gửi yêu cầu đăng bài Facebook qua Wiii Connect. "
                "Host action sẽ dùng kết nối Facebook hiện tại để preview/apply "
                "qua gateway đã bật và hiển thị kết quả sau khi chạy xong."
            )
        if status == "validation_failed":
            missing = payload.get("missing_fields")
            missing_fields = ", ".join(
                str(item)
                for item in missing
                if str(item or "").strip()
            ) if isinstance(missing, list) else ""
            suffix = f" Trường thiếu: {missing_fields}." if missing_fields else ""
            return (
                "Mình chưa thể đăng Facebook vì yêu cầu host action "
                "thiếu dữ liệu bắt buộc."
                f"{suffix}"
            )
        if status == "approval_required":
            return (
                "Mình cần bạn xác nhận rõ trước khi Wiii Connect "
                "thực hiện thao tác đăng."
            )
        if status == "preview_required":
            return "Mình cần tạo preview Facebook hợp lệ trước khi đăng."
    return ""


def _tool_name(tool: object) -> str:
    return str(getattr(tool, "name", "") or getattr(tool, "__name__", "") or "").strip()


def _blocked_facebook_plan(
    *,
    reason: str,
    requested_provider_slugs: tuple[str, ...],
    ready_provider_slugs: tuple[str, ...],
    action_allowlists_by_provider: Mapping[str, Iterable[str]] | None = None,
    state: AgentState | None = None,
    unavailable_answer: str = "",
) -> ExternalAppActionPlan:
    return ExternalAppActionPlan(
        version=EXTERNAL_APP_ACTION_PLAN_VERSION,
        status="blocked",
        kind="facebook_post_direct_apply",
        provider_slug="facebook",
        action_slug=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        reason=reason,
        requested_provider_slugs=requested_provider_slugs,
        ready_provider_slugs=ready_provider_slugs,
        action_allowlists_by_provider=_normalize_action_allowlists(
            action_allowlists_by_provider
        ),
        connection_lifecycle=_connection_lifecycle_for_provider(state, "facebook"),
        unavailable_answer=unavailable_answer,
    )


def _ready_facebook_plan(
    *,
    requested_provider_slugs: tuple[str, ...],
    ready_provider_slugs: tuple[str, ...],
    action_allowlists_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> ExternalAppActionPlan:
    return ExternalAppActionPlan(
        version=EXTERNAL_APP_ACTION_PLAN_VERSION,
        status="ready",
        kind="facebook_post_direct_apply",
        provider_slug="facebook",
        action_slug=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        reason="facebook_post_request",
        forced_tool_name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        allowed_tool_names=(WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,),
        requested_provider_slugs=requested_provider_slugs,
        ready_provider_slugs=ready_provider_slugs,
        action_allowlists_by_provider=_normalize_action_allowlists(
            action_allowlists_by_provider
        ),
    )


def _has_action_allowlist(
    values: Mapping[str, Iterable[str]] | None,
    provider_slug: str,
    required_actions: Iterable[str] | None = None,
) -> bool:
    provider = _safe_slug(provider_slug)
    if not provider:
        return False
    action_allowlists = _normalize_action_allowlists(values)
    actions = set(action_allowlists.get(provider, ()))
    if not actions:
        return False
    required = {
        str(action or "").strip().upper().replace("-", "_")
        for action in (required_actions or ())
        if str(action or "").strip()
    }
    return bool(actions.intersection(required)) if required else True


def _facebook_no_agent_ready_actions_answer() -> str:
    return (
        "Facebook đã có thể xuất hiện trong Wiii Connect, nhưng action đăng bài "
        "chưa nằm trong effective action inventory của lượt này. Wiii sẽ không "
        "mở tool đăng bài cho đến khi kết nối, scope `apply`, gateway, schema, "
        "preview/approval và audit đều sẵn sàng."
    )


def _blocked_plan_unavailable_answer(
    plan: ExternalAppActionPlan,
    *,
    state: AgentState | None = None,
) -> str:
    if plan.kind == "facebook_post_direct_apply":
        if plan.reason == "no_agent_ready_actions":
            return _facebook_no_agent_ready_actions_answer()
        return (
            build_wiii_connect_facebook_post_unavailable_answer(
                state if isinstance(state, dict) else {}
            )
            or "Facebook chưa sẵn sàng cho thao tác agent qua Wiii Connect."
        )
    if plan.kind == "provider_action":
        return _provider_action_unavailable_answer(
            reason=plan.reason or "external_app_action_plan_not_ready",
            provider_slug=plan.provider_slug,
            requested_provider_slugs=plan.requested_provider_slugs,
            ready_provider_slugs=plan.ready_provider_slugs,
            state=state,
        )
    return "Wiii Connect chưa sẵn sàng để mở tool hành động ngoài ứng dụng trong lượt này."


def _blocked_provider_action_plan(
    *,
    reason: str,
    provider_slug: str,
    requested_provider_slugs: tuple[str, ...],
    ready_provider_slugs: tuple[str, ...],
    action_allowlists_by_provider: Mapping[str, Iterable[str]] | None = None,
    state: AgentState | None = None,
) -> ExternalAppActionPlan:
    scoped_allowlists = (
        _scope_action_allowlists(action_allowlists_by_provider, provider_slug)
        if provider_slug
        else _normalize_action_allowlists(action_allowlists_by_provider)
    )
    return ExternalAppActionPlan(
        version=EXTERNAL_APP_ACTION_PLAN_VERSION,
        status="blocked",
        kind="provider_action",
        provider_slug=provider_slug,
        reason=reason,
        requested_provider_slugs=requested_provider_slugs,
        ready_provider_slugs=ready_provider_slugs,
        action_allowlists_by_provider=scoped_allowlists,
        connection_lifecycle=_connection_lifecycle_for_provider(state, provider_slug),
        unavailable_answer=_provider_action_unavailable_answer(
            reason=reason,
            provider_slug=provider_slug,
            requested_provider_slugs=requested_provider_slugs,
            ready_provider_slugs=ready_provider_slugs,
            state=state,
        ),
    )


def _connection_lifecycle_for_provider(
    state: AgentState | None,
    provider_slug: str,
) -> dict[str, Any]:
    provider = _safe_slug(provider_slug)
    if not provider:
        return {}
    try:
        lifecycle = wiii_connect_provider_connection_lifecycle_from_state(
            state if isinstance(state, dict) else None,
            provider,
        )
    except Exception:
        return {}
    return sanitize_connection_lifecycle_metadata(lifecycle)


def _action_allowlists_for_providers(
    provider_slugs: tuple[str, ...],
    *,
    state: AgentState | None = None,
) -> dict[str, tuple[str, ...]]:
    """Return effective model-visible action allowlists for connected providers."""

    if not provider_slugs:
        return {}
    if isinstance(state, dict):
        inventory_actions = _effective_action_allowlists_for_providers(
            provider_slugs,
            state=state,
        )
        if inventory_actions:
            return inventory_actions
        return {}
    return _configured_action_allowlists_for_providers(provider_slugs)


def _effective_action_allowlists_for_providers(
    provider_slugs: tuple[str, ...],
    *,
    state: AgentState,
) -> dict[str, tuple[str, ...]]:
    """Derive action allowlists from the same effective inventory shown in UI."""

    try:
        from app.engine.wiii_connect.action_inventory import (
            build_wiii_connect_effective_action_inventory,
        )
        from app.engine.wiii_connect.backend_action_executor import (
            audit_persistent,
            authenticated_user_from_state,
            select_wiii_connect_connection,
            storage_status_metadata,
        )
        from app.engine.wiii_connect.composio_adapter import (
            build_composio_adapter_config,
            build_composio_execution_enabled_entry,
            build_composio_provider_adapter_capability,
        )
        from app.engine.wiii_connect.provider_registry import (
            get_wiii_connect_provider_entry,
        )
        from app.engine.wiii_connect.scope_policy import (
            scope_policy_for_provider_entry,
        )

        config = build_composio_adapter_config()
        adapter_capability = build_composio_provider_adapter_capability(config)
        storage = storage_status_metadata()
        current_user = authenticated_user_from_state(state)
        result: dict[str, tuple[str, ...]] = {}
        for provider in provider_slugs:
            entry = get_wiii_connect_provider_entry(provider)
            if entry is None:
                continue
            effective_entry = build_composio_execution_enabled_entry(entry, config)
            connection = select_wiii_connect_connection(
                effective_entry.slug,
                current_user=current_user,
                storage=storage,
            )
            inventory = build_wiii_connect_effective_action_inventory(
                entry=effective_entry,
                connection=connection,
                adapter_capability=adapter_capability,
                runtime_enabled_action_slugs=(
                    config.executable_action_slugs_for_provider(effective_entry.slug)
                ),
                audit_ledger_metadata={"persistent": audit_persistent(storage)},
                connection_ref_present=bool(
                    getattr(connection, "connection_ref", "") if connection else ""
                ),
                connection_selection_required=False,
                storage_metadata=storage,
                scope_policy=scope_policy_for_provider_entry(effective_entry),
            )
            visible_actions = tuple(
                action.slug for action in inventory.actions if action.visible_to_agent
            )
            if visible_actions:
                result[effective_entry.slug] = _safe_action_slugs(visible_actions)
        return result
    except Exception:
        return {}


def _configured_action_allowlists_for_providers(
    provider_slugs: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    """Return config-level action allowlists for explicit test/diagnostic callers."""

    try:
        from app.engine.wiii_connect.composio_adapter import (
            build_composio_adapter_config,
            build_composio_execution_enabled_entry,
        )
        from app.engine.wiii_connect.provider_registry import (
            get_wiii_connect_provider_entry,
        )

        config = build_composio_adapter_config()
        result: dict[str, tuple[str, ...]] = {}
        for provider in provider_slugs:
            entry = get_wiii_connect_provider_entry(provider)
            if entry is None:
                continue
            effective = build_composio_execution_enabled_entry(entry, config)
            actions = _safe_action_slugs(effective.action_allowlist)
            if actions:
                result[effective.slug] = actions
        return result
    except Exception:
        return {}


def _scope_action_allowlists(
    values: Mapping[str, Iterable[str]] | None,
    provider_slug: str,
) -> dict[str, tuple[str, ...]]:
    provider = _safe_slug(provider_slug)
    normalized = _normalize_action_allowlists(values)
    if not provider:
        return normalized
    actions = normalized.get(provider)
    return {provider: actions} if actions else {}


def _ready_provider_slugs_from_state(
    state: AgentState | None,
    query: str,
) -> tuple[str, ...]:
    if not isinstance(state, dict):
        return ()
    try:
        from app.engine.wiii_connect.snapshot import build_wiii_connect_snapshot

        return build_wiii_connect_snapshot(
            state=state,
            query=query,
        ).agent_ready_external_provider_slugs()
    except Exception:
        return ()


def _provider_action_unavailable_answer(
    *,
    reason: str,
    provider_slug: str,
    requested_provider_slugs: tuple[str, ...],
    ready_provider_slugs: tuple[str, ...],
    state: AgentState | None = None,
) -> str:
    provider_label = _provider_label(provider_slug)
    if reason == "ambiguous_provider_target":
        names = ", ".join(_provider_label(slug) for slug in requested_provider_slugs)
        return (
            "Mình chưa thể chạy hành động ngoài ứng dụng vì yêu cầu đang nhắc tới "
            f"nhiều provider ({names}). Hãy chọn rõ một kết nối trong Wiii Connect "
            "trước khi yêu cầu agent thao tác."
        )
    if reason == "missing_provider_target":
        return (
            "Mình chưa thể chạy hành động ngoài ứng dụng vì chưa xác định được "
            "provider mục tiêu. Hãy nói rõ Gmail, GitHub, Notion, Slack, hoặc "
            "provider đã kết nối trong Wiii Connect."
        )
    if reason == "provider_not_agent_ready":
        if provider_label:
            status_answer = build_wiii_connect_provider_status_answer(
                state if isinstance(state, dict) else {},
                provider_slug=provider_slug,
            )
            return (
                f"{status_answer}\n\n"
                f"Mình sẽ không mở action schema hoặc tool thực thi cho {provider_label} "
                "cho tới khi provider này agent-ready trong Wiii Connect."
            )
        return (
            "Mình chưa thể chạy hành động ngoài ứng dụng vì chưa có provider nào "
            "agent-ready trong Wiii Connect."
        )
    if reason == "no_agent_ready_actions":
        return (
            f"{provider_label or 'Provider này'} có thể đã kết nối hoặc agent-ready, "
            "nhưng lượt này không có action hiệu lực nào được phép lộ cho agent. "
            "Hãy kiểm tra scope, action allowlist, gateway, schema và audit trong Wiii Connect."
        )
    ready = ", ".join(_provider_label(slug) for slug in ready_provider_slugs) or "không có"
    return (
        "Mình chưa thể chạy hành động ngoài ứng dụng qua Wiii Connect "
        f"(lý do: {reason}; provider sẵn sàng: {ready})."
    )


def _provider_label(provider_slug: str) -> str:
    provider = _safe_slug(provider_slug)
    if not provider:
        return ""
    try:
        from app.engine.wiii_connect.provider_registry import (
            get_wiii_connect_provider_entry,
        )

        entry = get_wiii_connect_provider_entry(provider)
        if entry is not None and entry.label:
            return str(entry.label)
    except Exception:
        pass
    return provider.replace("_", " ").title()


def _normalized_slugs(values: Iterable[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return _safe_slugs(values)


def _safe_slugs(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    result: list[str] = []
    for value in values:
        slug = _safe_slug(value)
        if slug and slug not in result:
            result.append(slug)
    return tuple(result)


def _safe_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _safe_tool_names(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    result: list[str] = []
    for value in values:
        name = str(value or "").strip()[:160]
        if name and name not in result:
            result.append(name)
    return tuple(result)


def _normalize_action_allowlists(
    values: Mapping[str, Iterable[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for provider, actions in values.items():
        provider_slug = _safe_slug(provider)
        action_slugs = _safe_action_slugs(actions)
        if provider_slug and action_slugs:
            result[provider_slug] = action_slugs
    return result


def _safe_action_allowlists(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    return _normalize_action_allowlists(value)


def _safe_action_slugs(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    result: list[str] = []
    for value in values:
        slug = str(value or "").strip().upper().replace("-", "_")[:160]
        if slug and slug not in result:
            result.append(slug)
    return tuple(result)


def _safe_status(value: Any) -> ExternalAppActionPlanStatus:
    status = str(value or "").strip()
    if status in {"not_applicable", "ready", "blocked"}:
        return status  # type: ignore[return-value]
    return "not_applicable"


def _safe_kind(value: Any) -> ExternalAppActionPlanKind:
    kind = str(value or "").strip()
    if kind in {"none", "facebook_post_direct_apply", "provider_action"}:
        return kind  # type: ignore[return-value]
    return "none"


def _parse_tool_result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _is_wiii_connect_action_payload(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    if _is_wiii_connect_catalog_only_payload(payload):
        return False
    version = str(payload.get("version") or "").strip()
    if version.startswith("wiii_connect_"):
        return True
    action = str(payload.get("action") or "").strip()
    if action.startswith("wiii_connect.") and payload.get("status") in {
        "action_completed",
        "action_failed",
        "action_requested",
        "validation_failed",
        "approval_required",
        "preview_required",
    }:
        return True
    if payload.get("provider_slug") and payload.get("status") in {
        "action_completed",
        "action_failed",
        "action_requested",
        "validation_failed",
        "approval_required",
        "preview_required",
    }:
        return True
    return False


def _is_wiii_connect_catalog_only_payload(payload: Mapping[str, Any]) -> bool:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return False
    if "action_catalog" not in data:
        return False
    if payload.get("action") or payload.get("action_slug"):
        return False
    if "integration_worker" in data or "execution_gate" in data:
        return False
    return not any(payload.get(key) for key in ("gateway", "schema", "execution"))


def _final_answer_for_payload(payload: dict[str, Any]) -> str:
    localized = _localized_final_answer_for_payload(payload)
    if localized:
        return localized

    status = str(payload.get("status") or "").strip()
    if status == "action_completed":
        summary = str(payload.get("summary") or "").strip()
        if summary:
            return summary
        provider = str(payload.get("provider_slug") or "provider").strip()
        return f"Wiii Connect đã thực hiện xong thao tác với {provider}."
    if status == "action_failed":
        reason = str(payload.get("error") or payload.get("summary") or "").strip()
        suffix = f": {reason}" if reason else "."
        action = str(payload.get("action") or "").strip()
        provider_slug = str(payload.get("provider_slug") or "").strip().lower()
        if provider_slug == "facebook" or action == "wiii_connect.facebook_post.direct_apply":
            return f"Facebook chưa đăng được{suffix}"
        return f"Wiii Connect chưa thực hiện được thao tác{suffix}"
    if status == "action_requested":
        action = str(payload.get("action") or "").strip()
        provider_slug = str(payload.get("provider_slug") or "").strip().lower()
        if (
            provider_slug == "facebook"
            or action == "wiii_connect.facebook_post.direct_apply"
        ):
            return (
                "Mình đã gửi yêu cầu đăng bài Facebook qua Wiii Connect. "
                "Host action sẽ dùng kết nối Facebook hiện tại để preview/apply "
                "qua gateway đã audit và trả kết quả sau khi chạy xong."
            )
        return (
            "Mình đã gửi yêu cầu qua Wiii Connect. Runtime sẽ thực hiện qua "
            "gateway đã audit và trả kết quả sau khi chạy xong."
        )
    if status == "validation_failed":
        return "Wiii Connect chưa thể chạy vì thiếu dữ liệu bắt buộc."
    if status == "approval_required":
        return "Wiii Connect cần xác nhận rõ trước khi thực hiện thao tác này."
    if status == "preview_required":
        return "Wiii Connect cần tạo preview hợp lệ trước khi apply."
    return ""


def _localized_final_answer_for_payload(payload: dict[str, Any]) -> str:
    """Return UTF-8 safe Vietnamese copy for Wiii Connect action envelopes."""

    status = str(payload.get("status") or "").strip()
    action = str(payload.get("action") or "").strip()
    provider_slug = str(payload.get("provider_slug") or "").strip().lower()
    if status == "action_completed":
        summary = str(payload.get("summary") or "").strip()
        if summary:
            return summary
        provider = str(payload.get("provider_slug") or "provider").strip()
        if provider.lower() == "facebook":
            return "Đã đăng bài lên Facebook qua Wiii Connect."
        return f"Wiii Connect đã thực hiện xong thao tác với {provider}."
    if status == "action_failed":
        reason = str(payload.get("error") or payload.get("summary") or "").strip()
        suffix = f": {reason}" if reason else "."
        if provider_slug == "facebook" or action == "wiii_connect.facebook_post.direct_apply":
            return f"Facebook chưa đăng được{suffix}"
        return f"Wiii Connect chưa thực hiện được thao tác{suffix}"
    if status == "action_requested":
        if provider_slug == "facebook" or action == "wiii_connect.facebook_post.direct_apply":
            return (
                "Mình đã gửi yêu cầu đăng bài Facebook qua Wiii Connect. "
                "Runtime sẽ trả kết quả sau khi gateway đã audit chạy xong."
            )
        return (
            "Mình đã gửi yêu cầu qua Wiii Connect. Runtime sẽ thực hiện qua "
            "gateway đã audit và trả kết quả sau khi chạy xong."
        )
    if status == "validation_failed":
        return "Wiii Connect chưa thể chạy vì thiếu dữ liệu bắt buộc."
    if status == "approval_required":
        return "Wiii Connect cần xác nhận rõ trước khi thực hiện thao tác này."
    if status == "preview_required":
        return "Wiii Connect cần tạo preview hợp lệ trước khi apply."
    return ""


__all__ = [
    "EXTERNAL_APP_ACTION_PLAN_STATE_KEY",
    "EXTERNAL_APP_ACTION_PLAN_VERSION",
    "EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY",
    "ExternalAppActionPlan",
    "ExternalAppActionTurnPreparation",
    "ExternalAppIntegrationLane",
    "external_app_action_plan_from_state",
    "external_app_action_final_answer",
    "external_app_integration_lane_from_plan",
    "force_tools_for_external_app_action_plan",
    "facebook_direct_apply_final_answer",
    "prepare_external_app_action_turn",
    "record_external_app_action_plan",
    "resolve_external_app_action_plan",
]
