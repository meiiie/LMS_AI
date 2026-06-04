"""Backend-owned Wiii Connect tools for the direct agent loop."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.core.config import settings
from app.core.security_models import AuthenticatedUser
from app.engine.multi_agent.external_app_action_runtime import (
    external_app_action_plan_from_state,
)
from app.engine.multi_agent.external_app_integration_lane import (
    external_app_integration_lane_from_state,
)
from app.engine.tools.native_tool import StructuredTool
from app.engine.tools.runtime_context import build_runtime_correlation_metadata
from app.engine.tools.tool_capability_registry import (
    WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    WIII_CONNECT_EXECUTE_ACTION_TOOL,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
    WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
    WIII_CONNECT_LIST_ACTIONS_TOOL,
)
from app.engine.wiii_connect.backend_action_executor import (
    WiiiConnectBackendActionPlan,
    append_execution_audit,
    append_execution_stage_audit,
    audit_persistent,
    authenticated_user_from_state,
    build_execution_request,
    execute_wiii_connect_composio_backend_action,
    preflight_wiii_connect_composio_backend_action,
    select_wiii_connect_connection,
    storage_status_metadata,
)
from app.engine.wiii_connect.integration_worker import (
    WIII_CONNECT_INTEGRATION_WORKER_VERSION,
    WiiiConnectIntegrationWorkerPlan,
    WiiiConnectWorkerArgumentPlan,
    build_wiii_connect_worker_arguments,
    classify_wiii_connect_integration_worker_result,
    plan_wiii_connect_integration_worker,
    worker_block_payload,
)
from app.engine.wiii_connect.action_policy import (
    WIII_CONNECT_ACTION_POLICY_VERSION,
    enabled_action_slugs_for_providers,
    rank_wiii_connect_action_candidates,
    select_wiii_connect_action,
)
from app.engine.wiii_connect.action_authorization import (
    resolve_wiii_connect_action_authorization,
)
from app.engine.wiii_connect.argument_key_policy import (
    model_visible_arguments,
    safe_public_argument_keys,
)
from app.engine.wiii_connect import (
    WiiiConnectConnectionRecordV1,
    action_catalog_public_metadata,
    build_composio_adapter_config,
    build_composio_execution_enabled_entry,
    build_composio_external_user_id,
    build_composio_provider_adapter_capability,
    build_facebook_post_approval_token,
    build_facebook_post_preview_evidence_id,
    decide_execution_gateway,
    facebook_image_sha256,
    get_wiii_connect_provider_entry,
    list_composio_facebook_pages,
    normalize_facebook_image_filename,
    normalize_facebook_image_media_type,
    normalize_facebook_image_url,
    normalize_facebook_page_id,
    normalize_facebook_post_message,
    scope_policy_for_provider_entry,
    stage_composio_file_upload,
)


WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION = "wiii_connect_facebook_direct_tool.v1"
WIII_CONNECT_GENERIC_DIRECT_TOOL_VERSION = "wiii_connect_generic_direct_tool.v1"
WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION = (
    "wiii_connect_integration_delegate_tool.v1"
)
_MAX_SURFACE_LEN = 80


class WiiiConnectDelegateToIntegrationInput(BaseModel):
    """Collapsed model request for one provider-scoped integration worker."""

    model_config = ConfigDict(extra="ignore")

    provider_slug: str = Field(default="")
    prompt: str = Field(default="")
    action_slug: str = Field(default="")


class WiiiConnectListActionsInput(BaseModel):
    """Model request for a privacy-safe Wiii Connect action catalog view."""

    model_config = ConfigDict(extra="ignore")

    provider_slug: str = Field(default="")
    include_disabled: bool = Field(default=False)
    intent_prompt: str = Field(default="")


class WiiiConnectExecuteActionInput(BaseModel):
    """Model request for one backend-owned Wiii Connect provider action."""

    model_config = ConfigDict(extra="ignore")

    provider_slug: str = Field(default="")
    action_slug: str = Field(default="")
    mutation: str = Field(default="read")
    arguments: dict[str, Any] = Field(default_factory=dict)
    preview_evidence_id: str = Field(default="")
    approval_token_present: bool = Field(default=False)


class WiiiConnectFacebookPostDirectApplyInput(BaseModel):
    """Model-authored Facebook Page post request for Wiii Connect."""

    model_config = ConfigDict(extra="ignore")

    message: str = Field(default="")
    image_policy: str = Field(default="none")


def _list_actions_input_schema(
    allowed_provider_slugs: tuple[str, ...],
) -> type[BaseModel]:
    provider_type = _provider_slug_literal_type(
        allowed_provider_slugs,
        include_empty=True,
    )
    fields: dict[str, Any] = {
        "provider_slug": (provider_type, Field(default="")),
        "intent_prompt": (str, Field(default="")),
    }
    if not allowed_provider_slugs:
        fields["include_disabled"] = (bool, Field(default=False))
    return create_model(
        "WiiiConnectListActionsInputScoped",
        __config__=ConfigDict(extra="ignore"),
        **fields,
    )


def _execute_action_input_schema(
    allowed_provider_slugs: tuple[str, ...],
    allowed_action_slugs: tuple[str, ...] = (),
) -> type[BaseModel]:
    provider_type = _provider_slug_literal_type(
        allowed_provider_slugs,
        include_empty=False,
    )
    action_type = _action_slug_literal_type(allowed_action_slugs)
    default_provider = allowed_provider_slugs[0] if allowed_provider_slugs else ""
    action_field = (
        Field(
            ...,
            description=(
                "Curated Wiii Connect action slug from the scoped action catalog."
            ),
        )
        if allowed_action_slugs
        else Field(default="")
    )
    return create_model(
        "WiiiConnectExecuteActionInputScoped",
        __config__=ConfigDict(extra="ignore"),
        provider_slug=(provider_type, Field(default=default_provider)),
        action_slug=(action_type, action_field),
        mutation=(str, Field(default="read")),
        arguments=(dict[str, Any], Field(default_factory=dict)),
    )


def _delegate_input_schema(
    allowed_provider_slugs: tuple[str, ...],
    allowed_action_slugs: tuple[str, ...] = (),
) -> type[BaseModel]:
    provider_type = _provider_slug_literal_type(
        allowed_provider_slugs,
        include_empty=False,
    )
    action_type = _action_slug_literal_type(allowed_action_slugs)
    default_provider = allowed_provider_slugs[0] if allowed_provider_slugs else ""
    return create_model(
        "WiiiConnectDelegateToIntegrationInputScoped",
        __config__=ConfigDict(extra="ignore"),
        provider_slug=(provider_type, Field(default=default_provider)),
        prompt=(
            str,
            Field(
                default="",
                description=(
                    "The user's integration task, passed verbatim into the "
                    "provider-scoped Wiii Connect worker."
                ),
            ),
        ),
        action_slug=(action_type, Field(default="")),
    )


def _provider_slug_literal_type(
    allowed_provider_slugs: tuple[str, ...],
    *,
    include_empty: bool,
) -> Any:
    values = _normalize_provider_allowlist(allowed_provider_slugs)
    if not values:
        return str
    literal_values = (("",) if include_empty else ()) + values
    return Literal.__getitem__(literal_values)


def _action_slug_literal_type(allowed_action_slugs: tuple[str, ...]) -> Any:
    values = _normalize_action_allowlist(allowed_action_slugs)
    if not values:
        return str
    return Literal.__getitem__(values)


def _normalize_provider_allowlist(values: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or ():
        slug = _provider_slug(str(value))
        if slug and slug not in normalized:
            normalized.append(slug)
    return tuple(normalized)


def _normalize_action_allowlist(values: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or ():
        slug = _action_slug(str(value))
        if slug and slug not in normalized:
            normalized.append(slug)
    return tuple(normalized)


def _normalize_action_allowlists_by_provider(
    values: Mapping[str, Iterable[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for provider, actions in values.items():
        provider_slug = _provider_slug(str(provider))
        action_slugs = _normalize_action_allowlist(tuple(actions or ()))
        if provider_slug and action_slugs:
            result[provider_slug] = action_slugs
    return result


def _allowed_provider_description(allowed_provider_slugs: tuple[str, ...]) -> str:
    if not allowed_provider_slugs:
        return ""
    return (
        " This tool is scoped to currently agent-ready connected providers only: "
        + ", ".join(allowed_provider_slugs)
        + "."
    )


def _allowed_actions_by_provider(
    allowed_provider_slugs: tuple[str, ...],
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    if not allowed_provider_slugs:
        return {}
    override = _normalize_action_allowlists_by_provider(
        allowed_action_slugs_by_provider
    )
    result: dict[str, tuple[str, ...]] = {}
    missing_providers = tuple(
        provider for provider in allowed_provider_slugs if provider not in override
    )
    if not missing_providers:
        return {
            provider: override[provider]
            for provider in allowed_provider_slugs
            if provider in override
        }
    composio_config = build_composio_adapter_config()
    for provider in allowed_provider_slugs:
        if provider in override:
            result[provider] = override[provider]
            continue
        entry = get_wiii_connect_provider_entry(provider)
        if entry is None:
            continue
        effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
        result[effective_entry.slug] = tuple(effective_entry.action_allowlist)
    return result


def _attach_ranked_action_candidates(
    catalog: dict[str, Any],
    *,
    provider_slug: str,
    action_allowlist: tuple[str, ...],
    intent_prompt: str,
) -> None:
    prompt = str(intent_prompt or "").strip()
    if not prompt:
        return
    ranked = rank_wiii_connect_action_candidates(
        provider_slug=provider_slug,
        action_allowlist=action_allowlist,
        prompt=prompt,
    )
    catalog["ranking"] = {
        "version": WIII_CONNECT_ACTION_POLICY_VERSION,
        "prompt_present": True,
        "candidate_count": len(ranked),
        "candidates": [candidate.to_public_metadata() for candidate in ranked],
    }


def _external_action_execution_gate(
    state: Mapping[str, Any],
    *,
    provider_slug: str,
    action_slug: str,
    tool_name: str,
    expected_kind: str,
    expected_executor: str,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate that the current turn's plan/lane authorizes this execution.

    Tool visibility is necessary but not sufficient. OpenHuman enforces
    integration boundaries at dispatch time; Wiii mirrors that by checking the
    typed action plan and lane before any provider call.
    """

    plan = external_app_action_plan_from_state(state)
    lane = external_app_integration_lane_from_state(state)
    raw_action = str(action_slug or "").strip()
    normalized_provider_action = _action_slug(raw_action)
    planned_action = raw_action if raw_action.startswith("wiii_connect.") else normalized_provider_action
    metadata = {
        "plan": plan.to_metadata() if plan is not None else None,
        "lane": lane.to_metadata() if lane is not None else None,
        "requested_provider_slug": _provider_slug(provider_slug),
        "requested_action_slug": planned_action,
        "requested_tool_name": str(tool_name or "").strip(),
        "expected_kind": expected_kind,
        "expected_executor": expected_executor,
    }
    provider = _provider_slug(provider_slug)

    if plan is None:
        return False, "missing_external_app_action_plan", metadata
    if not plan.ready:
        return False, plan.reason or "external_app_action_plan_not_ready", metadata
    if expected_kind and plan.kind != expected_kind:
        return False, "external_app_action_kind_mismatch", metadata
    if provider and plan.provider_slug and plan.provider_slug != provider:
        return False, "external_app_action_provider_mismatch", metadata
    if planned_action and plan.action_slug and plan.action_slug != planned_action:
        return False, "external_app_action_slug_mismatch", metadata
    if provider and plan.ready_provider_slugs and provider not in plan.ready_provider_slugs:
        return False, "provider_not_agent_ready", metadata

    action_allowlist = plan.action_allowlists_by_provider.get(provider, ())
    if (
        expected_kind == "provider_action"
        and action_allowlist
        and normalized_provider_action
        and normalized_provider_action not in action_allowlist
    ):
        return False, "external_app_action_not_in_plan_allowlist", metadata

    if lane is None:
        return False, "missing_external_app_integration_lane", metadata
    if not lane.ready:
        return False, lane.reason or "external_app_integration_lane_not_ready", metadata
    if expected_executor and lane.executor != expected_executor:
        return False, "external_app_integration_executor_mismatch", metadata
    if provider and lane.provider_slug and lane.provider_slug != provider:
        return False, "external_app_integration_provider_mismatch", metadata
    if planned_action and lane.action_slug and lane.action_slug != planned_action:
        return False, "external_app_integration_action_mismatch", metadata

    visible_tools = tuple(str(name or "").strip() for name in lane.visible_tool_names)
    requested_tool = str(tool_name or "").strip()
    if visible_tools and requested_tool not in visible_tools:
        return False, "external_app_integration_tool_not_visible", metadata
    if lane.forced_tool_name and lane.forced_tool_name != requested_tool:
        return False, "external_app_integration_forced_tool_mismatch", metadata

    return True, "ready", metadata


@dataclass(frozen=True, slots=True)
class _ImagePayload:
    content: bytes = b""
    media_type: str = ""
    filename: str = ""
    image_url: str = ""
    error: str = ""


def make_wiii_connect_list_actions_tool(
    *,
    state: Mapping[str, Any] | None = None,
    allowed_provider_slugs: tuple[str, ...] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> StructuredTool:
    """Return the backend-owned Wiii Connect action catalog tool."""

    captured_state = dict(state or {})
    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    allowed_actions_by_provider = _allowed_actions_by_provider(
        allowed_providers,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
    )

    async def _run(
        provider_slug: str = "",
        include_disabled: bool = True,
        intent_prompt: str = "",
    ) -> str:
        payload = execute_wiii_connect_list_actions(
            provider_slug=provider_slug,
            include_disabled=False if allowed_providers else include_disabled,
            allowed_provider_slugs=allowed_providers,
            allowed_action_slugs_by_provider=allowed_actions_by_provider,
            intent_prompt=intent_prompt or _action_policy_prompt_from_state(captured_state),
        )
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        _run,
        name=WIII_CONNECT_LIST_ACTIONS_TOOL,
        description=(
            "List Wiii Connect provider action catalog metadata before choosing "
            "a provider action. In agent-scoped turns this returns enabled "
            "provider actions only. The payload contains sanitized "
            "provider/action names, mutation types, required scopes, and "
            "enabled status; never secrets."
            + _allowed_provider_description(allowed_providers)
        ),
        args_schema=_list_actions_input_schema(allowed_providers),
    )


def make_wiii_connect_execute_action_tool(
    *,
    state: Mapping[str, Any] | None = None,
    allowed_provider_slugs: tuple[str, ...] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> StructuredTool:
    """Return the provider-neutral backend action executor tool."""

    captured_state = dict(state or {})
    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    allowed_actions_by_provider = _allowed_actions_by_provider(
        allowed_providers,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
    )
    allowed_actions = enabled_action_slugs_for_providers(
        provider_slugs=allowed_providers,
        action_allowlists_by_provider=allowed_actions_by_provider,
    )

    async def _run(
        provider_slug: str = "",
        action_slug: str = "",
        connection_ref: str = "",
        mutation: str = "read",
        arguments: dict[str, Any] | None = None,
        preview_evidence_id: str = "",
        approval_token_present: bool = False,
    ) -> str:
        payload = await execute_wiii_connect_provider_action(
            state=captured_state,
            provider_slug=provider_slug,
            action_slug=action_slug,
            connection_ref=connection_ref,
            mutation=mutation,
            arguments=arguments or {},
            preview_evidence_id=preview_evidence_id,
            approval_token_present=approval_token_present,
            allowed_provider_slugs=allowed_providers,
        )
        return json.dumps(payload, ensure_ascii=False)

    generated = StructuredTool.from_function(
        _run,
        name=WIII_CONNECT_EXECUTE_ACTION_TOOL,
        description=(
            "Execute one curated Wiii Connect provider action through backend "
            "gateway, schema verification, audit, and Composio. Use read-only "
            "actions directly. Write/apply/admin actions fail closed unless "
            "preview evidence and approval presence are provided by Wiii runtime."
            + _allowed_provider_description(allowed_providers)
        ),
        args_schema=_execute_action_input_schema(allowed_providers, allowed_actions),
    )
    generated.mutates_state = True
    generated.requires_confirmation = False
    generated.wiii_connect_action_owner = "backend_gateway"
    return generated


def make_wiii_connect_delegate_to_integration_tool(
    *,
    state: Mapping[str, Any] | None = None,
    allowed_provider_slugs: tuple[str, ...] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> StructuredTool:
    """Return the collapsed OpenHuman-style integration delegation tool."""

    captured_state = dict(state or {})
    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    allowed_actions_by_provider = _allowed_actions_by_provider(
        allowed_providers,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
    )
    allowed_actions = enabled_action_slugs_for_providers(
        provider_slugs=allowed_providers,
        action_allowlists_by_provider=allowed_actions_by_provider,
    )

    async def _run(
        provider_slug: str = "",
        prompt: str = "",
        action_slug: str = "",
        mutation: str = "read",
        connection_ref: str = "",
        arguments: dict[str, Any] | None = None,
        preview_evidence_id: str = "",
        approval_token_present: bool = False,
    ) -> str:
        payload = await execute_wiii_connect_delegate_to_integration(
            state=captured_state,
            provider_slug=provider_slug,
            prompt=prompt,
            action_slug=action_slug,
            mutation=mutation,
            connection_ref=connection_ref,
            arguments=arguments or {},
            preview_evidence_id=preview_evidence_id,
            approval_token_present=approval_token_present,
            allowed_provider_slugs=allowed_providers,
            allowed_action_slugs_by_provider=allowed_actions_by_provider,
        )
        return json.dumps(payload, ensure_ascii=False)

    generated = StructuredTool.from_function(
        _run,
        name=WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        description=(
            "Delegate one explicit external-app task to Wiii Connect's "
            "provider-scoped integration worker. The main chat sees this "
            "single collapsed handle instead of broad provider action tools. "
            "The worker will validate connected provider readiness, select only "
            "from the curated action allowlist, pass through the backend gateway, "
            "and audit execution. Pass the user's task in `prompt`."
            + _allowed_provider_description(allowed_providers)
        ),
        args_schema=_delegate_input_schema(allowed_providers, allowed_actions),
    )
    generated.mutates_state = True
    generated.requires_confirmation = False
    return generated


def execute_wiii_connect_list_actions(
    *,
    provider_slug: str = "",
    include_disabled: bool = True,
    allowed_provider_slugs: tuple[str, ...] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
    intent_prompt: str = "",
) -> dict[str, Any]:
    """Return provider/action catalog metadata without secrets."""

    provider = _provider_slug(provider_slug)
    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    allowed_actions_by_provider = _allowed_actions_by_provider(
        allowed_providers,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
    )
    if allowed_providers and provider and provider not in allowed_providers:
        return _generic_failure(
            "provider_not_agent_ready",
            provider_slug=provider,
            data={"allowed_provider_slugs": list(allowed_providers)},
        )
    composio_config = build_composio_adapter_config()
    if provider:
        entry = get_wiii_connect_provider_entry(provider)
        if entry is None:
            return _generic_failure("unknown_wiii_connect_provider", provider_slug=provider)
        effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
        enabled_slugs = (
            allowed_actions_by_provider.get(effective_entry.slug, ())
            if allowed_providers
            else effective_entry.action_allowlist
        )
        catalog = action_catalog_public_metadata(
            provider_slug=effective_entry.slug,
            include_disabled=include_disabled,
            enabled_slugs=enabled_slugs,
        )
        _attach_ranked_action_candidates(
            catalog,
            provider_slug=effective_entry.slug,
            action_allowlist=enabled_slugs,
            intent_prompt=intent_prompt,
        )
        return _generic_success(
            "Action catalog loaded.",
            provider_slug=effective_entry.slug,
            data={"action_catalog": catalog},
        )
    catalog = action_catalog_public_metadata(
        include_disabled=include_disabled,
    )
    if allowed_providers:
        allowed_action_slugs = {
            slug
            for actions in allowed_actions_by_provider.values()
            for slug in actions
        }
        actions = [
            action
            for action in catalog.get("actions", [])
            if isinstance(action, dict)
            and _provider_slug(str(action.get("provider_slug") or ""))
            in allowed_providers
            and (
                not allowed_action_slugs
                or _action_slug(str(action.get("slug") or "")) in allowed_action_slugs
            )
        ]
        catalog = {
            **catalog,
            "allowed_provider_slugs": list(allowed_providers),
            "action_count": len(actions),
            "enabled_action_count": len(
                [action for action in actions if bool(action.get("enabled"))]
            ),
            "actions": actions,
        }
    return _generic_success(
        "Action catalog loaded.",
        provider_slug="",
        data={"action_catalog": catalog},
    )


async def execute_wiii_connect_provider_action(
    *,
    state: Mapping[str, Any],
    provider_slug: str = "",
    action_slug: str = "",
    connection_ref: str = "",
    mutation: str = "read",
    arguments: dict[str, Any] | None = None,
    preview_evidence_id: str = "",
    approval_token_present: bool = False,
    allowed_provider_slugs: tuple[str, ...] = (),
    intent_prompt: str = "",
    execution_tool_name: str = WIII_CONNECT_EXECUTE_ACTION_TOOL,
    authorization_verified: bool = False,
) -> dict[str, Any]:
    """Execute one curated provider action through the generic backend executor."""

    user = authenticated_user_from_state(state)
    request_id = _request_id_from_state(state)
    provider = _provider_slug(provider_slug)
    if not provider:
        return _generic_failure("missing_provider_slug")
    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    if allowed_providers and provider not in allowed_providers:
        return _generic_failure(
            "provider_not_agent_ready",
            provider_slug=provider,
            data={"allowed_provider_slugs": list(allowed_providers)},
        )
    entry = get_wiii_connect_provider_entry(provider)
    if entry is None:
        return _generic_failure("unknown_wiii_connect_provider", provider_slug=provider)

    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    action_policy = select_wiii_connect_action(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        mutation=mutation,
        action_allowlist=effective_entry.action_allowlist,
        prompt=_safe_intent_prompt(intent_prompt, state),
    )
    if not action_policy.selected or action_policy.selected_action is None:
        return _generic_failure(
            action_policy.reason,
            provider_slug=effective_entry.slug,
            action_slug=action_policy.action_slug,
            data={
                "action_policy": action_policy.to_public_metadata(),
                "action_catalog": action_catalog_public_metadata(
                    provider_slug=effective_entry.slug,
                    enabled_slugs=effective_entry.action_allowlist,
                )
            },
        )
    action = action_policy.selected_action
    authorization = resolve_wiii_connect_action_authorization(
        mutation=action.mutation,
        preview_evidence_id=preview_evidence_id,
        approval_token_present=approval_token_present,
        authorization_verified=authorization_verified,
    )
    if allowed_providers:
        gate_allowed, gate_reason, gate_metadata = _external_action_execution_gate(
            state,
            provider_slug=effective_entry.slug,
            action_slug=action.slug,
            tool_name=execution_tool_name,
            expected_kind="provider_action",
            expected_executor="provider_worker",
        )
        if not gate_allowed:
            return _generic_failure(
                gate_reason,
                provider_slug=effective_entry.slug,
                action_slug=action.slug,
                data={
                    "execution_gate": gate_metadata,
                    "action_policy": action_policy.to_public_metadata(),
                },
            )

    storage = storage_status_metadata()
    connection = select_wiii_connect_connection(
        effective_entry.slug,
        current_user=user,
        storage=storage,
        connection_ref=connection_ref,
    )
    safe_arguments = model_visible_arguments(
        provider_slug=effective_entry.slug,
        action_slug=action.slug,
        arguments=arguments or {},
    )
    argument_policy = _argument_policy_metadata(
        provider_slug=effective_entry.slug,
        action_slug=action.slug,
        raw_arguments=arguments or {},
        safe_arguments=safe_arguments,
    )
    preflight = await preflight_wiii_connect_composio_backend_action(
        WiiiConnectBackendActionPlan(
            entry=effective_entry,
            config=composio_config,
            current_user=user,
            connection=connection,
            storage=storage,
            action_slug=action.slug,
            mutation=action.mutation,
            arguments=safe_arguments,
            approval_token_present=authorization.trusted_approval_token_present,
            preview_evidence_id=authorization.trusted_preview_evidence_id,
            preview_evidence_required=bool(action.requires_preview),
            argument_keys=tuple(_safe_argument_keys(safe_arguments.keys())),
            surface="direct_tool",
            stage="generic_preflight",
            request_id=request_id,
            audit_metadata={
                "connection_ref_present": bool(connection_ref),
                "connection_found": connection is not None,
                "action_policy": action_policy.to_public_metadata(),
                "operation_policy": authorization.to_public_metadata(),
                "argument_policy": argument_policy,
                "catalog_action": action.to_public_metadata(),
            },
        )
    )
    if preflight.status != "ready":
        return _generic_failure(
            preflight.reason,
            provider_slug=effective_entry.slug,
            action_slug=action.slug,
            gateway=preflight.gateway.to_public_metadata(),
            schema=preflight.schema.to_public_metadata() if preflight.schema else None,
            storage=storage,
            data={
                "operation_policy": authorization.to_public_metadata(),
                "argument_policy": argument_policy,
            },
        )

    result = await execute_wiii_connect_composio_backend_action(
        WiiiConnectBackendActionPlan(
            entry=effective_entry,
            config=composio_config,
            current_user=user,
            connection=connection,
            storage=storage,
            action_slug=action.slug,
            mutation=action.mutation,
            arguments=safe_arguments,
            approval_token_present=authorization.trusted_approval_token_present,
            preview_evidence_id=authorization.trusted_preview_evidence_id,
            preview_evidence_required=bool(action.requires_preview),
            argument_keys=tuple(_safe_argument_keys(safe_arguments.keys())),
            surface="direct_tool",
            stage="generic_execute",
            request_id=request_id,
            audit_metadata={
                "action_policy": action_policy.to_public_metadata(),
                "operation_policy": authorization.to_public_metadata(),
                "argument_policy": argument_policy,
                "catalog_action": action.to_public_metadata(),
            },
        ),
        preflight=preflight,
    )
    if result.succeeded:
        return _generic_success(
            "Provider action completed.",
            provider_slug=effective_entry.slug,
            action_slug=action.slug,
            gateway=result.gateway.to_public_metadata(),
            schema=result.schema.to_public_metadata() if result.schema else None,
            execution=result.execution.to_public_metadata()
            if result.execution
            else None,
            storage=storage,
            data={
                "operation_policy": authorization.to_public_metadata(),
                "argument_policy": argument_policy,
            },
        )
    return _generic_failure(
        result.reason,
        provider_slug=effective_entry.slug,
        action_slug=action.slug,
        gateway=result.gateway.to_public_metadata(),
        schema=result.schema.to_public_metadata() if result.schema else None,
        execution=result.execution.to_public_metadata() if result.execution else None,
        storage=storage,
        data={
            "operation_policy": authorization.to_public_metadata(),
            "argument_policy": argument_policy,
            **(
                {"missing_argument_keys": list(result.missing_argument_keys)}
                if result.missing_argument_keys
                else {}
            ),
        },
    )


async def execute_wiii_connect_delegate_to_integration(
    *,
    state: Mapping[str, Any],
    provider_slug: str = "",
    prompt: str = "",
    action_slug: str = "",
    mutation: str = "read",
    connection_ref: str = "",
    arguments: dict[str, Any] | None = None,
    preview_evidence_id: str = "",
    approval_token_present: bool = False,
    allowed_provider_slugs: tuple[str, ...] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Run one provider-scoped worker turn behind a single delegation tool."""

    allowed_providers = _normalize_provider_allowlist(allowed_provider_slugs)
    task_prompt = _safe_intent_prompt(prompt, state)
    composio_config = build_composio_adapter_config()
    worker_plan = plan_wiii_connect_integration_worker(
        provider_slug=provider_slug,
        prompt=task_prompt,
        action_slug=action_slug,
        mutation=mutation,
        allowed_provider_slugs=allowed_providers,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
        composio_config=composio_config,
    )
    if not worker_plan.ready:
        return _delegate_envelope(
            _generic_failure(
                worker_plan.reason,
                provider_slug=worker_plan.provider_slug,
                action_slug=worker_plan.action_slug,
                data=worker_block_payload(worker_plan),
            ),
            worker_plan=worker_plan,
        )

    gate_allowed, gate_reason, gate_metadata = _external_action_execution_gate(
        state,
        provider_slug=worker_plan.provider_slug,
        action_slug=worker_plan.action_slug,
        tool_name=WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
        expected_kind="provider_action",
        expected_executor="provider_worker",
    )
    if not gate_allowed:
        return _delegate_envelope(
            _generic_failure(
                gate_reason,
                provider_slug=worker_plan.provider_slug,
                action_slug=worker_plan.action_slug,
                data={
                    "execution_gate": gate_metadata,
                    "worker": worker_block_payload(worker_plan),
                },
            ),
            worker_plan=worker_plan,
        )

    worker_argument_plan = build_wiii_connect_worker_arguments(
        plan=worker_plan,
        prompt=task_prompt,
        provided_arguments=arguments,
    )
    worker_result = await execute_wiii_connect_provider_action(
        state=state,
        provider_slug=worker_plan.provider_slug,
        action_slug=worker_plan.action_slug,
        connection_ref=connection_ref,
        mutation=worker_plan.selected_mutation,
        arguments=worker_argument_plan.arguments,
        preview_evidence_id=preview_evidence_id,
        approval_token_present=approval_token_present,
        allowed_provider_slugs=allowed_providers,
        intent_prompt=task_prompt,
        execution_tool_name=WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    )
    return _delegate_envelope(
        worker_result,
        worker_plan=worker_plan,
        worker_argument_plan=worker_argument_plan,
    )


def make_wiii_connect_facebook_post_direct_apply_tool(
    *,
    state: Mapping[str, Any] | None = None,
) -> StructuredTool:
    """Return a backend-owned Facebook publish tool scoped to one chat state."""

    captured_state = dict(state or {})

    async def _run(
        provider_slug: str = "facebook",
        connection_ref: str = "",
        page_id: str = "",
        message: str = "",
        image_policy: str = "none",
        image_base64: str | None = None,
        image_media_type: str | None = None,
        image_filename: str | None = None,
        image_url: str | None = None,
    ) -> str:
        payload = await execute_wiii_connect_facebook_post_direct_apply(
            state=captured_state,
            provider_slug=provider_slug,
            connection_ref=connection_ref,
            page_id=page_id,
            message=message,
            image_policy=image_policy,
            image_base64=image_base64,
            image_media_type=image_media_type,
            image_filename=image_filename,
            image_url=image_url,
        )
        return json.dumps(payload, ensure_ascii=False)

    generated = StructuredTool.from_function(
        _run,
        name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        description=(
            "Publish a Facebook Page post through Wiii Connect's backend-owned "
            "connector gateway for an explicit user request. Draft `message` as "
            "the exact post copy. If the user asks for any/random content, write "
            "a short original safe post. If the user attached an image, set "
            "`image_policy` to `use_latest_user_image`; never include raw image "
            "bytes unless the tool input already provides them from Wiii runtime."
        ),
        args_schema=WiiiConnectFacebookPostDirectApplyInput,
    )
    generated.mutates_state = True
    generated.requires_confirmation = False
    return generated


async def execute_wiii_connect_facebook_post_direct_apply(
    *,
    state: Mapping[str, Any],
    provider_slug: str = "facebook",
    connection_ref: str = "",
    page_id: str = "",
    message: str = "",
    image_policy: str = "none",
    image_base64: str | None = None,
    image_media_type: str | None = None,
    image_filename: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    """Execute Facebook preview/apply entirely behind Wiii's backend policy."""

    user = authenticated_user_from_state(state)
    request_id = _request_id_from_state(state)
    provider = _provider_slug(provider_slug)
    if provider != "facebook":
        return _failure("unsupported_provider_post", provider_slug=provider)
    entry = get_wiii_connect_provider_entry(provider)
    if entry is None:
        return _failure("unknown_wiii_connect_provider", provider_slug=provider)
    gate_allowed, gate_reason, gate_metadata = _external_action_execution_gate(
        state,
        provider_slug=provider,
        action_slug=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        tool_name=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_TOOL,
        expected_kind="facebook_post_direct_apply",
        expected_executor="specialized_direct_tool",
    )
    if not gate_allowed:
        return _failure(
            gate_reason,
            provider_slug=provider,
            action_slug=WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
            data={"execution_gate": gate_metadata},
        )

    composio_config = build_composio_adapter_config()
    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    storage = storage_status_metadata()
    connection = select_wiii_connect_connection(
        effective_entry.slug,
        current_user=user,
        storage=storage,
        connection_ref=connection_ref,
    )
    selected_connection_ref = connection.connection_ref if connection else ""
    safe_connection_id = connection.connection_id if connection else ""
    normalized_message = normalize_facebook_post_message(message)
    image = _resolve_image_payload(
        state=state,
        image_policy=image_policy,
        image_base64=image_base64,
        image_media_type=image_media_type,
        image_filename=image_filename,
        image_url=image_url,
    )
    normalized_page_id = normalize_facebook_page_id(page_id)

    if image.error or not normalized_message:
        return _failure(
            image.error or "missing_message",
            provider_slug=effective_entry.slug,
            storage=storage,
            connection_ref_present=bool(selected_connection_ref),
        )
    if connection is None:
        preflight = await preflight_wiii_connect_composio_backend_action(
            WiiiConnectBackendActionPlan(
                entry=effective_entry,
                config=composio_config,
                current_user=user,
                connection=None,
                storage=storage,
                action_slug=_facebook_post_action_slug(image),
                mutation="apply",
                approval_token_present=True,
                preview_evidence_id="connection_missing",
                argument_keys=_facebook_post_argument_keys(image),
                connection_selection_required=not bool(connection_ref),
                surface="direct_tool",
                stage="connection",
                request_id=request_id,
                audit_metadata={"connection_ref_present": bool(connection_ref)},
            )
        )
        return _failure(
            preflight.reason,
            provider_slug=effective_entry.slug,
            gateway=preflight.gateway.to_public_metadata(),
            schema=preflight.schema.to_public_metadata() if preflight.schema else None,
            storage=storage,
        )

    if not normalized_page_id:
        page_decision = await _select_default_facebook_page(
            effective_entry,
            connection,
            composio_config=composio_config,
            storage=storage,
            current_user=user,
            request_id=request_id,
        )
        if not page_decision["ready"]:
            return _failure(
                str(page_decision["reason"]),
                provider_slug=effective_entry.slug,
                gateway=page_decision.get("gateway"),
                storage=storage,
            )
        normalized_page_id = str(page_decision["page_id"])

    action_slug = _facebook_post_action_slug(image)
    preview_evidence_id = build_facebook_post_preview_evidence_id(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=normalized_page_id,
        message=normalized_message,
        image_sha256=facebook_image_sha256(image.content),
        image_url=image.image_url,
    )
    approval_token = build_facebook_post_approval_token(
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        connection_ref=selected_connection_ref,
        page_id=normalized_page_id,
        message=normalized_message,
        image_sha256=facebook_image_sha256(image.content),
        image_url=image.image_url,
        secret_key=settings.session_secret_key,
    )
    audit_base = {
        "connection_ref_present": bool(selected_connection_ref),
        "connection_id_present": bool(safe_connection_id),
        "preview_evidence_id_present": bool(preview_evidence_id),
        "approval_token_present": bool(approval_token),
        "message_length": len(normalized_message),
        "image_present": bool(image.content or image.image_url),
        "image_size_bytes": len(image.content),
    }
    preflight_plan = WiiiConnectBackendActionPlan(
        entry=effective_entry,
        config=composio_config,
        current_user=user,
        connection=connection,
        storage=storage,
        action_slug=action_slug,
        mutation="apply",
        approval_token_present=True,
        preview_evidence_id=preview_evidence_id,
        preview_evidence_required=True,
        argument_keys=_facebook_post_argument_keys(image),
        surface="direct_tool",
        stage="apply",
        request_id=request_id,
        audit_metadata=audit_base,
    )
    preflight = await preflight_wiii_connect_composio_backend_action(preflight_plan)
    if preflight.status != "ready":
        return _failure(
            preflight.reason,
            provider_slug=effective_entry.slug,
            action_slug=action_slug,
            gateway=preflight.gateway.to_public_metadata(),
            schema=preflight.schema.to_public_metadata() if preflight.schema else None,
            storage=storage,
        )

    arguments: dict[str, Any] = {
        "page_id": normalized_page_id,
        "message": normalized_message,
        "published": True,
    }
    upload_metadata: dict[str, Any] | None = None
    if image.content:
        upload = await stage_composio_file_upload(
            config=composio_config,
            action_slug=_facebook_post_action_slug(image),
            provider_slug=effective_entry.slug,
            filename=image.filename,
            mimetype=image.media_type,
            content=image.content,
            request_id=request_id,
        )
        upload_metadata = upload.to_public_metadata()
        if not upload.ready:
            append_execution_stage_audit(
                preflight.gateway,
                preflight.request,
                storage,
                current_user=user,
                status="blocked",
                reason=upload.reason,
                metadata={
                    "surface": "direct_tool",
                    **audit_base,
                    "stage": "file_upload",
                    "upload": upload_metadata,
                },
            )
            return _failure(
                upload.reason,
                provider_slug=effective_entry.slug,
                action_slug=action_slug,
                gateway=preflight.gateway.to_public_metadata(),
                schema=preflight.schema.to_public_metadata() if preflight.schema else None,
                upload=upload_metadata,
                storage=storage,
            )
        arguments["photo"] = upload.file_descriptor
    elif image.image_url:
        arguments["url"] = image.image_url

    execution_result = await execute_wiii_connect_composio_backend_action(
        WiiiConnectBackendActionPlan(
            entry=effective_entry,
            config=composio_config,
            current_user=user,
            connection=connection,
            storage=storage,
            action_slug=action_slug,
            mutation="apply",
            arguments=arguments,
            argument_keys=_facebook_post_argument_keys(image),
            approval_token_present=True,
            preview_evidence_id=preview_evidence_id,
            preview_evidence_required=True,
            surface="direct_tool",
            stage="apply",
            request_id=request_id,
            audit_metadata={**audit_base, "upload": upload_metadata},
        ),
        preflight=preflight,
    )
    if execution_result.succeeded:
        return _success(
            "Đã đăng bài lên Facebook qua Wiii Connect.",
            provider_slug=effective_entry.slug,
            action_slug=action_slug,
            page_id=normalized_page_id,
            gateway=execution_result.gateway.to_public_metadata(),
            execution=execution_result.execution.to_public_metadata()
            if execution_result.execution
            else None,
            storage=storage,
            data={
                "preview_evidence_id_present": True,
                "approval_token_present": True,
                "image_present": bool(image.content or image.image_url),
            },
        )
    return _failure(
        execution_result.reason,
        provider_slug=effective_entry.slug,
        action_slug=action_slug,
        gateway=execution_result.gateway.to_public_metadata(),
        schema=execution_result.schema.to_public_metadata()
        if execution_result.schema
        else None,
        execution=execution_result.execution.to_public_metadata()
        if execution_result.execution
        else None,
        storage=storage,
        data={"missing_argument_keys": list(execution_result.missing_argument_keys)}
        if execution_result.missing_argument_keys
        else None,
    )


async def _select_default_facebook_page(
    entry: Any,
    connection: WiiiConnectConnectionRecordV1,
    *,
    composio_config: Any,
    storage: dict[str, Any],
    current_user: AuthenticatedUser,
    request_id: str | None = None,
) -> dict[str, Any]:
    request = build_execution_request(
        provider_slug=entry.slug,
        action_slug="FACEBOOK_LIST_MANAGED_PAGES",
        mutation="read",
        argument_keys=("fields", "limit"),
        request_id=request_id,
    )
    gateway = decide_execution_gateway(
        entry,
        connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(composio_config),
        audit_ledger_metadata={"persistent": audit_persistent(storage)},
        connection_selection_required=False,
        scope_policy=scope_policy_for_provider_entry(entry),
    )
    if not gateway.allowed:
        append_execution_audit(
            gateway,
            request,
            storage,
            current_user=current_user,
            metadata={"surface": "direct_tool", "stage": "page_list"},
        )
        return {"ready": False, "reason": gateway.reason, "gateway": gateway.to_public_metadata()}
    result = await list_composio_facebook_pages(
        config=composio_config,
        user_id=build_composio_external_user_id(
            organization_id=current_user.organization_id,
            user_id=current_user.user_id,
        ),
        connected_account_id=connection.connection_id,
        request_id=request.request_id,
    )
    append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status="succeeded" if result.ready else "blocked",
        reason=result.reason,
        metadata={
            "surface": "direct_tool",
            "stage": "page_list",
            "page_list": result.to_public_metadata(),
        },
    )
    page = result.pages[0] if result.ready and result.pages else None
    if page is None:
        return {
            "ready": False,
            "reason": result.reason or "facebook_page_missing",
            "gateway": gateway.to_public_metadata(),
        }
    return {
        "ready": True,
        "reason": "ready",
        "page_id": page.page_id,
        "page_label": page.name,
        "gateway": gateway.to_public_metadata(),
    }


def _resolve_image_payload(
    *,
    state: Mapping[str, Any],
    image_policy: str,
    image_base64: str | None,
    image_media_type: str | None,
    image_filename: str | None,
    image_url: str | None,
) -> _ImagePayload:
    normalized_url = normalize_facebook_image_url(image_url)
    raw_image = str(image_base64 or "").strip()
    media_type = str(image_media_type or "").strip()
    filename = str(image_filename or "").strip()
    if not raw_image and str(image_policy or "").strip() == "use_latest_user_image":
        latest = _latest_state_image(state)
        raw_image = str(latest.get("data") or "").strip()
        media_type = str(latest.get("media_type") or latest.get("mime_type") or "").strip()
        filename = str(latest.get("filename") or "wiii-chat-image").strip()
    if not raw_image:
        return _ImagePayload(image_url=normalized_url)
    if "," in raw_image and raw_image.lower().startswith("data:"):
        raw_image = raw_image.split(",", 1)[1]
    normalized_media_type = normalize_facebook_image_media_type(media_type)
    if not normalized_media_type:
        return _ImagePayload(error="unsupported_image_type")
    try:
        content = base64.b64decode(raw_image, validate=True)
    except (binascii.Error, ValueError):
        return _ImagePayload(error="invalid_image_base64")
    if not content:
        return _ImagePayload(error="missing_image")
    if len(content) > 10 * 1024 * 1024:
        return _ImagePayload(error="image_too_large")
    return _ImagePayload(
        content=content,
        media_type=normalized_media_type,
        filename=normalize_facebook_image_filename(
            filename,
            media_type=normalized_media_type,
        ),
    )


def _latest_state_image(state: Mapping[str, Any]) -> Mapping[str, Any]:
    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    images = context.get("images") if isinstance(context, Mapping) else None
    if not isinstance(images, list):
        images = state.get("images")
    if not isinstance(images, list):
        return {}
    for image in images:
        if isinstance(image, Mapping) and image.get("data"):
            return image
    return {}


def _facebook_post_action_slug(image: _ImagePayload) -> str:
    if image.content or image.image_url:
        return "FACEBOOK_CREATE_PHOTO_POST"
    return "FACEBOOK_CREATE_POST"


def _facebook_post_argument_keys(image: _ImagePayload) -> tuple[str, ...]:
    if image.content:
        return ("page_id", "message", "photo", "published")
    if image.image_url:
        return ("page_id", "message", "url", "published")
    return ("page_id", "message", "published")


def _provider_slug(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_argument_keys(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    return safe_public_argument_keys(values)


def _argument_policy_metadata(
    *,
    provider_slug: str,
    action_slug: str,
    raw_arguments: Mapping[str, Any],
    safe_arguments: Mapping[str, Any],
) -> dict[str, Any]:
    raw_keys = tuple(raw_arguments.keys()) if isinstance(raw_arguments, Mapping) else ()
    accepted_keys = tuple(safe_arguments.keys()) if isinstance(safe_arguments, Mapping) else ()
    safe_accepted_keys = _safe_argument_keys(accepted_keys)
    return {
        "version": "wiii_connect_argument_filter.v1",
        "provider_slug": _provider_slug(provider_slug),
        "action_slug": _action_slug(action_slug),
        "provided_argument_count": len(raw_keys),
        "accepted_argument_count": len(accepted_keys),
        "accepted_argument_keys": sorted(safe_accepted_keys),
        "hidden_argument_count": max(0, len(raw_keys) - len(accepted_keys)),
    }


def _safe_intent_prompt(value: Any, state: Mapping[str, Any]) -> str:
    prompt = str(value or "").strip()
    if prompt:
        return " ".join(prompt.split())[:800]
    return _action_policy_prompt_from_state(state)


def _request_id_from_state(state: Mapping[str, Any]) -> str | None:
    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    runtime_metadata = build_runtime_correlation_metadata()
    candidates = (
        state.get("request_id"),
        context.get("request_id") if isinstance(context, Mapping) else None,
        runtime_metadata.get("request_id"),
    )
    for candidate in candidates:
        request_id = str(candidate or "").strip()
        if request_id:
            return request_id
    return None


def _action_policy_prompt_from_state(state: Mapping[str, Any]) -> str:
    """Extract a bounded user-task string for action ranking diagnostics."""

    for key in ("query", "current_query", "user_query", "question"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:800]
    context = state.get("context")
    if isinstance(context, Mapping):
        for key in ("query", "current_query", "user_query", "question"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:800]
    return ""


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:_MAX_SURFACE_LEN] or "backend"


def _delegate_envelope(
    payload: dict[str, Any],
    *,
    worker_plan: WiiiConnectIntegrationWorkerPlan,
    worker_argument_plan: WiiiConnectWorkerArgumentPlan | None = None,
) -> dict[str, Any]:
    """Annotate worker output without exposing prompt text or raw payloads."""

    result = dict(payload)
    previous_version = str(result.get("version") or "")
    result["version"] = WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION
    worker_metadata = worker_plan.to_public_metadata()
    worker_metadata["delegate_version"] = WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION
    worker_metadata["planner_version"] = WIII_CONNECT_INTEGRATION_WORKER_VERSION
    worker_metadata["worker_result_version"] = previous_version
    if worker_argument_plan is not None:
        worker_metadata["argument_plan"] = worker_argument_plan.to_public_metadata()
    worker_metadata["result_classification"] = (
        classify_wiii_connect_integration_worker_result(
            result,
            plan=worker_plan,
        )
    )
    data = result.get("data")
    if not isinstance(data, dict):
        data = {}
    result["data"] = {
        **data,
        "integration_worker": worker_metadata,
    }
    return result


def _success(
    summary: str,
    *,
    provider_slug: str,
    action_slug: str,
    page_id: str,
    gateway: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION,
        "status": "action_completed",
        "action": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        "success": True,
        "summary": summary,
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "page_id_present": bool(page_id),
        "gateway": gateway,
        "execution": execution,
        "storage": storage,
        "data": data or {},
    }


def _failure(
    reason: str,
    *,
    provider_slug: str = "facebook",
    action_slug: str = "",
    gateway: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    upload: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    connection_ref_present: bool | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION,
        "status": "action_failed",
        "action": WIII_CONNECT_FACEBOOK_POST_DIRECT_APPLY_ACTION,
        "success": False,
        "summary": f"Facebook chưa đăng: {_safe_surface(reason)}",
        "error": _safe_surface(reason),
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "gateway": gateway,
        "schema": schema,
        "upload": upload,
        "execution": execution,
        "storage": storage,
        "action_catalog": action_catalog_public_metadata(
            provider_slug=provider_slug,
            enabled_slugs=(),
        ),
        "data": data or {},
    }
    if connection_ref_present is not None:
        payload["connection_ref_present"] = connection_ref_present
    return payload


def _generic_success(
    summary: str,
    *,
    provider_slug: str,
    action_slug: str = "",
    gateway: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": WIII_CONNECT_GENERIC_DIRECT_TOOL_VERSION,
        "status": "action_completed",
        "success": True,
        "summary": summary,
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "gateway": gateway,
        "schema": schema,
        "execution": execution,
        "storage": storage,
        "data": data or {},
    }


def _generic_failure(
    reason: str,
    *,
    provider_slug: str = "",
    action_slug: str = "",
    gateway: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_reason = _safe_surface(reason)
    return {
        "version": WIII_CONNECT_GENERIC_DIRECT_TOOL_VERSION,
        "status": _generic_failure_status(safe_reason),
        "success": False,
        "summary": f"Wiii Connect action blocked: {safe_reason}",
        "error": safe_reason,
        "provider_slug": provider_slug,
        "action_slug": action_slug,
        "gateway": gateway,
        "schema": schema,
        "execution": execution,
        "storage": storage,
        "data": data or {},
    }


def _generic_failure_status(reason: str) -> str:
    """Map policy/gateway reasons to user-facing action lifecycle states."""

    if reason in {"missing_required_arguments", "invalid_argument"}:
        return "validation_failed"
    if reason == "missing_preview_evidence":
        return "preview_required"
    if reason == "missing_approval_token":
        return "approval_required"
    return "action_failed"


__all__ = [
    "WIII_CONNECT_FACEBOOK_DIRECT_TOOL_VERSION",
    "WIII_CONNECT_GENERIC_DIRECT_TOOL_VERSION",
    "WIII_CONNECT_INTEGRATION_DELEGATE_TOOL_VERSION",
    "WiiiConnectDelegateToIntegrationInput",
    "WiiiConnectExecuteActionInput",
    "WiiiConnectFacebookPostDirectApplyInput",
    "WiiiConnectListActionsInput",
    "execute_wiii_connect_delegate_to_integration",
    "execute_wiii_connect_list_actions",
    "execute_wiii_connect_facebook_post_direct_apply",
    "execute_wiii_connect_provider_action",
    "make_wiii_connect_delegate_to_integration_tool",
    "make_wiii_connect_execute_action_tool",
    "make_wiii_connect_facebook_post_direct_apply_tool",
    "make_wiii_connect_list_actions_tool",
]
