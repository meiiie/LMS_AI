"""Provider-neutral backend execution helpers for Wiii Connect actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.core.security_models import AuthenticatedUser

from .adapter_v1 import (
    ActionMutation,
    WiiiConnectConnectionRecordV1,
    WiiiConnectExecutionRequest,
    WiiiConnectProviderRegistryEntry,
    connection_ref_matches,
)
from .argument_key_policy import safe_public_argument_key
from .audit_ledger import build_audit_ledger_record
from .composio_adapter import (
    WiiiConnectComposioAdapterConfig,
    WiiiConnectComposioExecuteResult,
    WiiiConnectComposioToolSchemaResult,
    build_composio_external_user_id,
    build_composio_provider_adapter_capability,
    execute_composio_tool,
    verify_composio_tool_schema,
)
from .execution_gateway import (
    WiiiConnectExecutionGatewayDecision,
    decide_execution_gateway,
)
from .persistent_storage import (
    default_persistent_storage_status_metadata,
    get_wiii_connect_persistent_storage,
)
from .scope_policy import scope_policy_for_provider_entry


WIII_CONNECT_BACKEND_ACTION_EXECUTOR_VERSION = "wiii_connect_backend_action_executor.v1"
_MAX_SURFACE_LEN = 80
_VALID_MUTATIONS: frozenset[str] = frozenset(
    {"read", "preview", "write", "apply", "admin"}
)


@dataclass(frozen=True, slots=True)
class WiiiConnectBackendActionPlan:
    """Sanitized plan for one provider action entering backend execution."""

    entry: WiiiConnectProviderRegistryEntry
    config: WiiiConnectComposioAdapterConfig
    current_user: AuthenticatedUser
    connection: WiiiConnectConnectionRecordV1 | None
    storage: dict[str, Any]
    action_slug: str
    mutation: ActionMutation
    arguments: dict[str, Any] = field(default_factory=dict)
    argument_keys: tuple[str, ...] = ()
    path: str = "external_app_action"
    approval_token_present: bool = False
    preview_evidence_id: str | None = None
    preview_evidence_required: bool = False
    connection_selection_required: bool = False
    surface: str = "backend"
    stage: str = "execute"
    request_id: str | None = None
    audit_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WiiiConnectBackendActionResult:
    """Provider-neutral execution result returned to a path-specific tool."""

    status: str
    reason: str
    request: WiiiConnectExecutionRequest
    gateway: WiiiConnectExecutionGatewayDecision
    schema: WiiiConnectComposioToolSchemaResult | None = None
    execution: WiiiConnectComposioExecuteResult | None = None
    missing_argument_keys: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_BACKEND_ACTION_EXECUTOR_VERSION,
            "status": self.status,
            "reason": self.reason,
            "request": self.request.to_audit_metadata(),
            "gateway": self.gateway.to_public_metadata(),
            "schema": self.schema.to_public_metadata() if self.schema else None,
            "execution": self.execution.to_public_metadata()
            if self.execution is not None
            else None,
            "missing_argument_keys": list(self.missing_argument_keys),
        }


def authenticated_user_from_state(state: Mapping[str, Any]) -> AuthenticatedUser:
    """Build an AuthenticatedUser from runtime AgentState without raw prompt data."""

    context = state.get("context") if isinstance(state.get("context"), Mapping) else {}
    user_id = str(state.get("user_id") or context.get("user_id") or "").strip()
    organization_id = str(
        state.get("organization_id") or context.get("organization_id") or ""
    ).strip() or None
    session_id = str(state.get("session_id") or context.get("session_id") or "").strip() or None
    role = str(context.get("user_role") or state.get("user_role") or "student").strip() or "student"
    return AuthenticatedUser(
        user_id=user_id or "__global__",
        auth_method="chat_runtime",
        role=role,
        session_id=session_id,
        organization_id=organization_id,
    )


def storage_status_metadata() -> dict[str, Any]:
    """Return privacy-safe Wiii Connect storage status."""

    try:
        return (
            get_wiii_connect_persistent_storage()
            .status(probe_database=True)
            .to_public_metadata()
        )
    except Exception:
        return default_persistent_storage_status_metadata()


def connection_storage_ready(storage: Mapping[str, Any]) -> bool:
    return bool(
        storage.get("persistent")
        and storage.get("connection_table_ready")
        and storage.get("audit_ledger_ready")
    )


def audit_persistent(storage: Mapping[str, Any]) -> bool:
    return bool(storage.get("persistent") and storage.get("audit_ledger_ready"))


def owner_organization_id(user: AuthenticatedUser) -> str:
    if user.organization_id:
        return user.organization_id
    return build_composio_external_user_id(
        organization_id=None,
        user_id=user.user_id,
    )


def select_wiii_connect_connection(
    provider_slug: str,
    *,
    current_user: AuthenticatedUser,
    storage: Mapping[str, Any],
    connection_ref: str = "",
) -> WiiiConnectConnectionRecordV1 | None:
    """Resolve an active connection record from opaque public state."""

    if not connection_storage_ready(storage):
        return None
    provider = _provider_slug(provider_slug)
    records = get_wiii_connect_persistent_storage().list_connection_records(
        organization_id=owner_organization_id(current_user),
        user_id=current_user.user_id,
        provider_slug=provider,
    )
    records = tuple(
        record for record in records if _provider_slug(record.provider_slug) == provider
    )
    safe_ref = _safe_public_connection_ref(connection_ref)
    if safe_ref:
        for record in records:
            if connection_ref_matches(
                provider_slug=record.provider_slug,
                connection_id=record.connection_id,
                candidate=safe_ref,
            ):
                return record
        return None
    for record in records:
        if record.active:
            return record
    return records[0] if records else None


def build_execution_request(
    *,
    provider_slug: str,
    action_slug: str,
    mutation: str,
    path: str = "external_app_action",
    approval_token_present: bool = False,
    preview_evidence_id: str | None = None,
    preview_evidence_required: bool = False,
    argument_keys: tuple[str, ...] = (),
    request_id: str | None = None,
) -> WiiiConnectExecutionRequest:
    safe_mutation = mutation if mutation in _VALID_MUTATIONS else "read"
    return WiiiConnectExecutionRequest(
        provider_slug=_provider_slug(provider_slug),
        action_slug=_action_slug(action_slug),
        path=str(path or "external_app_action")[:120],
        mutation=safe_mutation,  # type: ignore[arg-type]
        approval_token_present=approval_token_present,
        preview_evidence_id=preview_evidence_id,
        preview_evidence_required=preview_evidence_required,
        argument_keys=argument_keys,
        request_id=str(request_id or ""),
    )


async def execute_wiii_connect_composio_backend_action(
    plan: WiiiConnectBackendActionPlan,
    *,
    preflight: WiiiConnectBackendActionResult | None = None,
) -> WiiiConnectBackendActionResult:
    """Run a Composio action through Wiii gateway, schema, audit, and execute."""

    preflight_result = preflight or await preflight_wiii_connect_composio_backend_action(
        plan,
    )
    if preflight_result.status != "ready":
        return preflight_result

    request = preflight_result.request
    gateway = preflight_result.gateway
    schema = preflight_result.schema
    if schema is None:
        return WiiiConnectBackendActionResult(
            status="blocked",
            reason="missing_schema_preflight",
            request=request,
            gateway=gateway,
        )

    audit_base = {
        "surface": _safe_surface(plan.surface),
        "stage": _safe_surface(plan.stage),
        **plan.audit_metadata,
    }
    missing_argument_keys = missing_required_argument_keys(
        required_keys=schema.required_argument_keys,
        arguments=plan.arguments,
    )
    if missing_argument_keys:
        append_execution_stage_audit(
            gateway,
            request,
            plan.storage,
            current_user=plan.current_user,
            status="blocked",
            reason="missing_required_arguments",
            metadata={
                **audit_base,
                "stage": "argument_validation",
                "missing_argument_keys": list(missing_argument_keys),
            },
        )
        return WiiiConnectBackendActionResult(
            status="blocked",
            reason="missing_required_arguments",
            request=request,
            gateway=gateway,
            schema=schema,
            missing_argument_keys=missing_argument_keys,
        )

    append_execution_stage_audit(
        gateway,
        request,
        plan.storage,
        current_user=plan.current_user,
        status="started",
        reason="provider_execution_started",
        metadata={**audit_base, "stage": "execute"},
    )
    execution = await execute_composio_tool(
        config=plan.config,
        provider_slug=plan.entry.slug,
        action_slug=request.action_slug,
        user_id=build_composio_external_user_id(
            organization_id=plan.current_user.organization_id,
            user_id=plan.current_user.user_id,
        ),
        connected_account_id=plan.connection.connection_id if plan.connection else "",
        arguments=plan.arguments,
        request_id=request.request_id,
    )
    append_execution_stage_audit(
        gateway,
        request,
        plan.storage,
        current_user=plan.current_user,
        status=execution.status,
        reason=execution.reason,
        metadata={
            **audit_base,
            "stage": "execute_result",
            "schema": schema.to_public_metadata(),
            "execution": execution.to_public_metadata(),
        },
    )
    return WiiiConnectBackendActionResult(
        status=execution.status,
        reason=execution.reason,
        request=request,
        gateway=gateway,
        schema=schema,
        execution=execution,
    )


async def preflight_wiii_connect_composio_backend_action(
    plan: WiiiConnectBackendActionPlan,
) -> WiiiConnectBackendActionResult:
    """Verify gateway and live schema before any provider-side execution."""

    request = build_execution_request(
        provider_slug=plan.entry.slug,
        action_slug=plan.action_slug,
        mutation=plan.mutation,
        path=plan.path,
        approval_token_present=plan.approval_token_present,
        preview_evidence_id=plan.preview_evidence_id,
        preview_evidence_required=plan.preview_evidence_required,
        argument_keys=plan.argument_keys or tuple(plan.arguments.keys()),
        request_id=plan.request_id,
    )
    gateway = decide_execution_gateway(
        plan.entry,
        plan.connection,
        request,
        adapter_capability=build_composio_provider_adapter_capability(plan.config),
        audit_ledger_metadata={"persistent": audit_persistent(plan.storage)},
        connection_selection_required=plan.connection_selection_required,
        scope_policy=scope_policy_for_provider_entry(plan.entry),
    )
    audit_base = {
        "surface": _safe_surface(plan.surface),
        "stage": _safe_surface(plan.stage),
        **plan.audit_metadata,
    }
    if not gateway.allowed:
        append_execution_audit(
            gateway,
            request,
            plan.storage,
            current_user=plan.current_user,
            metadata=audit_base,
        )
        return WiiiConnectBackendActionResult(
            status="blocked",
            reason=gateway.reason,
            request=request,
            gateway=gateway,
        )

    schema = await verify_composio_tool_schema(
        config=plan.config,
        provider_slug=plan.entry.slug,
        action_slug=request.action_slug,
        request_id=request.request_id,
    )
    if not schema.ready:
        append_execution_stage_audit(
            gateway,
            request,
            plan.storage,
            current_user=plan.current_user,
            status="blocked",
            reason=schema.reason,
            metadata={**audit_base, "stage": "schema", "schema": schema.to_public_metadata()},
        )
        return WiiiConnectBackendActionResult(
            status="blocked",
            reason=schema.reason,
            request=request,
            gateway=gateway,
            schema=schema,
        )

    return WiiiConnectBackendActionResult(
        status="ready",
        reason="ready",
        request=request,
        gateway=gateway,
        schema=schema,
    )


def append_execution_audit(
    gateway: WiiiConnectExecutionGatewayDecision,
    request: WiiiConnectExecutionRequest,
    storage: Mapping[str, Any],
    *,
    current_user: AuthenticatedUser,
    metadata: dict[str, Any],
) -> None:
    append_execution_stage_audit(
        gateway,
        request,
        storage,
        current_user=current_user,
        status=gateway.status,
        reason=gateway.reason,
        metadata=metadata,
    )


def append_execution_stage_audit(
    gateway: WiiiConnectExecutionGatewayDecision,
    request: WiiiConnectExecutionRequest,
    storage: Mapping[str, Any],
    *,
    current_user: AuthenticatedUser,
    status: str,
    reason: str,
    metadata: dict[str, Any],
) -> None:
    if not audit_persistent(storage):
        return
    record = build_audit_ledger_record(
        event_kind="execution",
        provider_slug=gateway.decision.provider_slug,
        status=_safe_surface(status),
        reason=_safe_surface(reason),
        surface=_safe_surface(metadata.get("surface") or "backend"),
        metadata={
            "request": request.to_audit_metadata(),
            "decision": gateway.decision.to_metadata(),
            **metadata,
        },
    )
    get_wiii_connect_persistent_storage().append_audit_record(
        record,
        organization_id=owner_organization_id(current_user),
        user_id=current_user.user_id,
    )


def missing_required_argument_keys(
    *,
    required_keys: tuple[str, ...],
    arguments: Mapping[str, Any],
) -> tuple[str, ...]:
    provided = {str(key or "").strip() for key in arguments.keys()}
    missing = []
    for raw_key in required_keys:
        key = str(raw_key or "").strip()
        if key and key not in provided:
            missing.append(_safe_argument_key(key))
    return tuple(missing[:50])


def _safe_argument_key(value: str) -> str:
    return safe_public_argument_key(value)


def safe_failure_reason(value: Any) -> str:
    return _safe_surface(value)


def _provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:_MAX_SURFACE_LEN] or "backend"


def _safe_public_connection_ref(value: str | None) -> str:
    text = str(value or "").strip()
    if text.startswith("wcn_"):
        return text[:160]
    return ""


__all__ = [
    "WIII_CONNECT_BACKEND_ACTION_EXECUTOR_VERSION",
    "WiiiConnectBackendActionPlan",
    "WiiiConnectBackendActionResult",
    "append_execution_audit",
    "append_execution_stage_audit",
    "audit_persistent",
    "authenticated_user_from_state",
    "build_execution_request",
    "connection_storage_ready",
    "execute_wiii_connect_composio_backend_action",
    "missing_required_argument_keys",
    "owner_organization_id",
    "preflight_wiii_connect_composio_backend_action",
    "safe_failure_reason",
    "select_wiii_connect_connection",
    "storage_status_metadata",
]
