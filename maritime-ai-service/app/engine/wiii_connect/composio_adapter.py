"""Composio adapter configuration and provider-call boundaries for Wiii Connect.

The status helpers expose only privacy-safe readiness metadata. Provider calls
stay behind backend policy: Connect Link may create hosted OAuth URLs, while
read-only execution requires curated action enablement, schema verification,
gateway approval, and audit records before this adapter may call Composio.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from .adapter_v1 import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectProviderRegistryEntry,
    WiiiConnectScopeGrant,
    WiiiConnectVaultSecretRef,
    normalize_connection_state,
)
from .action_catalog import (
    configured_action_slugs_for_provider,
    get_wiii_connect_curated_action,
    list_wiii_connect_curated_actions,
)
from .provider_adapters import WiiiConnectProviderAdapterCapability
from .vault import WiiiConnectVaultCapability, default_wiii_connect_vault_capability


WIII_CONNECT_COMPOSIO_ADAPTER_VERSION = "wiii_connect_composio_adapter.v1"
WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION = "wiii_connect_composio_connections.v1"
WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION = "wiii_connect_composio_tool_schema.v1"
WIII_CONNECT_COMPOSIO_EXECUTION_VERSION = "wiii_connect_composio_execution.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioAdapterConfig:
    """Sanitized Composio adapter configuration state."""

    enabled: bool = False
    api_key: str = field(default="", repr=False)
    api_key_present: bool = False
    base_url: str = "https://backend.composio.dev"
    api_version: str = "v3.1"
    auth_config_by_provider: dict[str, str] | None = None
    readonly_execute_enabled: bool = False
    readonly_action_allowlist_by_provider: dict[str, tuple[str, ...]] | None = None

    @property
    def auth_config_count(self) -> int:
        return len(self.auth_config_by_provider or {})

    @property
    def readonly_action_count(self) -> int:
        return sum(
            len(actions)
            for actions in (self.readonly_action_allowlist_by_provider or {}).values()
        )

    def auth_config_id_for_provider(self, provider_slug: str) -> str:
        return (self.auth_config_by_provider or {}).get(
            _normalize_provider_slug(provider_slug),
            "",
        )

    def readonly_action_slugs_for_provider(self, provider_slug: str) -> tuple[str, ...]:
        provider = _normalize_provider_slug(provider_slug)
        enabled_slugs = (self.readonly_action_allowlist_by_provider or {}).get(
            provider,
            (),
        )
        return configured_action_slugs_for_provider(
            provider,
            enabled_slugs=enabled_slugs,
        )

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_COMPOSIO_ADAPTER_VERSION,
            "enabled": self.enabled,
            "api_key_present": self.api_key_present,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "auth_config_count": self.auth_config_count,
            "provider_slugs": sorted((self.auth_config_by_provider or {}).keys()),
            "readonly_execute_enabled": self.readonly_execute_enabled,
            "readonly_action_count": self.readonly_action_count,
            "readonly_action_provider_slugs": sorted(
                (self.readonly_action_allowlist_by_provider or {}).keys(),
            ),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioConnectLinkResult:
    """Sanitized result of a Composio Connect Link creation attempt."""

    ready: bool = False
    redirect_url: str = ""
    connected_account_id: str = field(default="", repr=False)
    expires_at: str = ""
    connected_account_ref_present: bool = False
    reason: str = "not_requested"

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "redirect_url_present": bool(self.redirect_url),
            "expires_at_present": bool(self.expires_at),
            "connected_account_ref_present": self.connected_account_ref_present,
            "reason": _safe_connect_link_reason(self.reason),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioConnectionListResult:
    """Sanitized Composio connected-account list result."""

    ready: bool = False
    reason: str = "not_requested"
    connections: tuple[WiiiConnectConnectionRecordV1, ...] = ()
    cursor: str = ""

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION,
            "status": "ready" if self.ready else "blocked",
            "reason": _safe_connection_list_reason(self.reason),
            "connection_count": len(self.connections),
            "cursor_present": bool(self.cursor),
            "connections": [
                connection.to_public_metadata() for connection in self.connections
            ],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioToolSchemaResult:
    """Sanitized Composio tool schema verification result."""

    ready: bool = False
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = "not_requested"
    schema_present: bool = False
    argument_keys: tuple[str, ...] = ()
    required_argument_keys: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION,
            "status": "ready" if self.ready else "blocked",
            "reason": _safe_tool_schema_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "action_slug": _normalize_action_slug(self.action_slug),
            "schema_present": self.schema_present,
            "argument_keys": [_safe_public_key(key) for key in self.argument_keys],
            "required_argument_keys": [
                _safe_public_key(key) for key in self.required_argument_keys
            ],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioExecuteResult:
    """Sanitized Composio tool execution result."""

    ready: bool = False
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = "not_requested"
    successful: bool = False
    status_code: int = 0
    data_keys: tuple[str, ...] = ()
    error_present: bool = False
    session_info_present: bool = False
    log_id_present: bool = False

    @property
    def status(self) -> str:
        if self.ready and self.successful:
            return "succeeded"
        if self.ready:
            return "failed"
        return "blocked"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_COMPOSIO_EXECUTION_VERSION,
            "status": self.status,
            "reason": _safe_execute_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "action_slug": _normalize_action_slug(self.action_slug),
            "successful": self.successful,
            "status_code": self.status_code,
            "data_keys": [_safe_public_key(key) for key in self.data_keys],
            "error_present": self.error_present,
            "session_info_present": self.session_info_present,
            "log_id_present": self.log_id_present,
        }


def parse_composio_auth_config_map(raw_value: Any) -> dict[str, str]:
    """Parse provider->auth_config_id mappings from JSON or comma text."""

    if isinstance(raw_value, Mapping):
        return _normalize_mapping(raw_value)
    text = str(raw_value or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return _normalize_mapping(parsed)
        return {}

    result: dict[str, str] = {}
    for item in text.split(","):
        pair = item.strip()
        if not pair:
            continue
        if "=" in pair:
            provider, auth_config = pair.split("=", 1)
        elif ":" in pair:
            provider, auth_config = pair.split(":", 1)
        else:
            continue
        provider_slug = _normalize_provider_slug(provider)
        auth_config_id = str(auth_config or "").strip()
        if provider_slug and auth_config_id:
            result[provider_slug] = auth_config_id
    return result


def parse_composio_readonly_action_allowlist(
    raw_value: Any,
) -> dict[str, tuple[str, ...]]:
    """Parse provider->read-only action allowlist from JSON or comma text."""

    if isinstance(raw_value, Mapping):
        return _normalize_action_allowlist_mapping(raw_value)
    text = str(raw_value or "").strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return _normalize_action_allowlist_mapping(parsed)
        if isinstance(parsed, list):
            return _normalize_action_allowlist_items(parsed)
        return {}

    result: dict[str, set[str]] = {}
    for item in text.split(","):
        pair = item.strip()
        if not pair:
            continue
        provider_slug = ""
        action_text = pair
        if "=" in pair:
            provider, action_text = pair.split("=", 1)
            provider_slug = _normalize_provider_slug(provider)
        elif ":" in pair and not pair.upper().startswith(("HTTP:", "HTTPS:")):
            provider, action_text = pair.split(":", 1)
            provider_slug = _normalize_provider_slug(provider)
        elif "." in pair:
            provider, action_text = pair.split(".", 1)
            provider_slug = _normalize_provider_slug(provider)
        for action_slug in _split_action_slugs(action_text):
            provider = provider_slug or _provider_for_curated_action_slug(action_slug)
            if provider and _curated_read_action_exists(provider, action_slug):
                result.setdefault(provider, set()).add(action_slug)
    return {
        provider: tuple(sorted(actions))
        for provider, actions in sorted(result.items())
        if actions
    }


def build_composio_adapter_config(
    settings_obj: Any | None = None,
) -> WiiiConnectComposioAdapterConfig:
    """Build sanitized Composio adapter config from backend settings."""

    if settings_obj is None:
        from app.core.config import settings as settings_obj

    auth_config_map = parse_composio_auth_config_map(
        getattr(settings_obj, "composio_auth_config_map", ""),
    )
    readonly_allowlist = parse_composio_readonly_action_allowlist(
        getattr(settings_obj, "composio_readonly_action_allowlist", ""),
    )
    api_key = str(getattr(settings_obj, "composio_api_key", "") or "").strip()
    return WiiiConnectComposioAdapterConfig(
        enabled=bool(getattr(settings_obj, "enable_wiii_connect_composio", False)),
        api_key=api_key,
        api_key_present=bool(api_key),
        base_url=str(
            getattr(settings_obj, "composio_base_url", "https://backend.composio.dev")
            or "https://backend.composio.dev"
        ).rstrip("/"),
        api_version=str(getattr(settings_obj, "composio_api_version", "v3.1") or "v3.1").strip(),
        auth_config_by_provider=auth_config_map,
        readonly_execute_enabled=bool(
            getattr(
                settings_obj,
                "enable_wiii_connect_composio_readonly_execute",
                False,
            )
        ),
        readonly_action_allowlist_by_provider=readonly_allowlist,
    )


def build_composio_provider_adapter_capability(
    config: WiiiConnectComposioAdapterConfig | None = None,
    *,
    settings_obj: Any | None = None,
) -> WiiiConnectProviderAdapterCapability:
    """Return privacy-safe Composio adapter capability metadata."""

    resolved = config or build_composio_adapter_config(settings_obj)
    if not resolved.enabled:
        return WiiiConnectProviderAdapterCapability(
            provider_kind="composio",
            adapter_name="composio_adapter",
            bound=False,
            configured=False,
            can_create_authorization_url=False,
            can_exchange_callback=False,
            can_execute_actions=False,
            reason="provider_adapter_not_bound",
            warnings=("composio_disabled",),
        )
    if not resolved.api_key_present:
        return WiiiConnectProviderAdapterCapability(
            provider_kind="composio",
            adapter_name="composio_adapter",
            bound=True,
            configured=False,
            can_create_authorization_url=False,
            can_exchange_callback=False,
            can_execute_actions=False,
            reason="provider_adapter_not_configured",
            warnings=("missing_composio_api_key",),
        )
    if resolved.auth_config_count <= 0:
        return WiiiConnectProviderAdapterCapability(
            provider_kind="composio",
            adapter_name="composio_adapter",
            bound=True,
            configured=False,
            can_create_authorization_url=False,
            can_exchange_callback=False,
            can_execute_actions=False,
            reason="provider_adapter_not_configured",
            warnings=("missing_composio_auth_config_map",),
        )

    can_execute = bool(
        resolved.readonly_execute_enabled and resolved.readonly_action_count > 0
    )
    warnings = (
        ("composio_readonly_execution_limited_to_curated_allowlist",)
        if can_execute
        else (
            "readonly_execution_disabled_or_no_curated_actions",
        )
    )
    return WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=can_execute,
        reason="ready",
        warnings=warnings,
    )


def build_composio_provider_managed_vault_capability(
    config: WiiiConnectComposioAdapterConfig | None = None,
    *,
    settings_obj: Any | None = None,
) -> WiiiConnectVaultCapability:
    """Return the vault policy for Composio-managed credentials."""

    resolved = config or build_composio_adapter_config(settings_obj)
    capability = build_composio_provider_adapter_capability(resolved)
    if not capability.authorization_ready:
        return default_wiii_connect_vault_capability()
    return WiiiConnectVaultCapability(
        enabled=True,
        backend="provider_managed",
        accepts_secret_material=True,
        provider_managed=True,
        key_namespace="composio",
        reason="ready",
        warnings=("secrets_remain_provider_managed",),
    )


def build_composio_connect_enabled_entry(
    entry: WiiiConnectProviderRegistryEntry,
    config: WiiiConnectComposioAdapterConfig | None = None,
    *,
    settings_obj: Any | None = None,
) -> WiiiConnectProviderRegistryEntry:
    """Enable only the connect phase when Composio is configured for a slug."""

    if entry.provider_kind != "composio":
        return entry
    resolved = config or build_composio_adapter_config(settings_obj)
    capability = build_composio_provider_adapter_capability(resolved)
    if (
        not capability.authorization_ready
        or not resolved.auth_config_id_for_provider(entry.slug)
    ):
        return entry

    warnings = tuple(
        warning for warning in entry.warnings if warning != "adapter_disabled"
    )
    warnings = _append_unique(
        warnings,
        "agent_actions_disabled_until_gateway_ready",
    )
    return replace(
        entry,
        enabled=True,
        agent_ready=False,
        requirements=entry.agent_ready_requirements,
        connect_requirements=(),
        warnings=warnings,
    )


def build_composio_execution_enabled_entry(
    entry: WiiiConnectProviderRegistryEntry,
    config: WiiiConnectComposioAdapterConfig | None = None,
    *,
    settings_obj: Any | None = None,
) -> WiiiConnectProviderRegistryEntry:
    """Enable read-only execution for curated Composio actions only."""

    connect_entry = build_composio_connect_enabled_entry(
        entry,
        config,
        settings_obj=settings_obj,
    )
    if connect_entry.provider_kind != "composio" or not connect_entry.enabled:
        return connect_entry

    resolved = config or build_composio_adapter_config(settings_obj)
    allowed_actions = resolved.readonly_action_slugs_for_provider(connect_entry.slug)
    if not resolved.readonly_execute_enabled or not allowed_actions:
        return connect_entry

    blocked_warnings = {
        "adapter_disabled",
        "agent_actions_disabled_until_gateway_ready",
    }
    warnings = tuple(
        warning
        for warning in connect_entry.warnings
        if warning and warning not in blocked_warnings
    )
    warnings = _append_unique(
        warnings,
        "read_only_agent_actions_require_live_schema_verification",
    )
    return replace(
        connect_entry,
        agent_ready=True,
        requirements=(),
        agent_ready_requirements=(),
        action_allowlist=allowed_actions,
        default_scopes=WiiiConnectScopeGrant(read=True),
        warnings=warnings,
    )


def build_composio_external_user_id(
    *,
    organization_id: str | None,
    user_id: str,
) -> str:
    """Create a stable non-PII Composio user id for Wiii identities."""

    owner = f"{organization_id or 'personal'}:{user_id}".encode("utf-8")
    digest = hashlib.sha256(owner).hexdigest()[:32]
    return f"wiii_{digest}"


async def create_composio_connect_link(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    user_id: str,
    callback_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioConnectLinkResult:
    """Create a Composio hosted auth link without leaking provider payloads."""

    auth_config_id = config.auth_config_id_for_provider(provider_slug)
    if not config.enabled or not config.api_key_present or not auth_config_id:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_adapter_not_configured",
        )
    if not user_id or not callback_url:
        return WiiiConnectComposioConnectLinkResult(
            reason="missing_user_or_callback",
        )

    payload = {
        "auth_config_id": auth_config_id,
        "user_id": user_id,
        "callback_url": callback_url,
    }
    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/connected_accounts/link"
    )
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.post(
            url,
            json=payload,
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_response_rejected",
        )

    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_response_invalid",
        )

    redirect_url = str(data.get("redirect_url") or data.get("redirectUrl") or "").strip()
    if not redirect_url:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_response_missing_redirect",
        )
    connected_account_id = str(
        data.get("connected_account_id") or data.get("connectedAccountId") or ""
    ).strip()
    return WiiiConnectComposioConnectLinkResult(
        ready=True,
        redirect_url=redirect_url,
        connected_account_id=connected_account_id,
        expires_at=str(data.get("expires_at") or data.get("expiresAt") or "").strip(),
        connected_account_ref_present=bool(connected_account_id),
        reason="ready",
    )


async def list_composio_connected_accounts(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    user_id: str,
    limit: int = 50,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioConnectionListResult:
    """List Composio connected accounts for one Wiii external user id."""

    auth_config_id = config.auth_config_id_for_provider(provider_slug)
    if not config.enabled or not config.api_key_present or not auth_config_id:
        return WiiiConnectComposioConnectionListResult(
            reason="provider_adapter_not_configured",
        )
    if not user_id:
        return WiiiConnectComposioConnectionListResult(reason="missing_user")

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/connected_accounts"
    )
    params: list[tuple[str, str | int]] = [
        ("user_ids", user_id),
        ("auth_config_ids", auth_config_id),
        ("limit", max(1, min(int(limit or 50), 100))),
    ]
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.get(
            url,
            params=params,
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioConnectionListResult(
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioConnectionListResult(
            reason="provider_response_rejected",
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioConnectionListResult(
            reason="provider_response_invalid",
        )

    connections = tuple(
        connection
        for connection in (
            _connection_record_from_composio_account(provider_slug, account)
            for account in _extract_connection_items(data)
        )
        if connection is not None
    )
    return WiiiConnectComposioConnectionListResult(
        ready=True,
        reason="ready",
        connections=connections,
        cursor=str(data.get("cursor") or data.get("next_cursor") or "").strip()
        if isinstance(data, dict)
        else "",
    )


async def verify_composio_tool_schema(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    action_slug: str,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioToolSchemaResult:
    """Fetch one Composio tool schema and return only safe shape metadata."""

    provider = _normalize_provider_slug(provider_slug)
    action = _normalize_action_slug(action_slug)
    curated = get_wiii_connect_curated_action(provider, action)
    if curated is None:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_curated",
        )
    if curated.mutation != "read":
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_read_only",
        )
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_adapter_not_configured",
        )

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/tools/{action}"
    )
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.get(
            url,
            params={"toolkit_versions": "latest"},
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_rejected",
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_invalid",
        )
    if not isinstance(data, Mapping):
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_invalid",
        )
    schema_action = _normalize_action_slug(
        data.get("slug")
        or data.get("tool_slug")
        or data.get("toolSlug")
        or data.get("name")
        or action
    )
    if schema_action != action:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="tool_schema_not_found",
        )
    toolkit_slug = _extract_composio_toolkit_slug(data)
    if toolkit_slug and toolkit_slug != provider:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="tool_schema_not_found",
        )

    schema = _extract_composio_input_schema(data)
    argument_keys = _extract_schema_argument_keys(schema)
    required_argument_keys = _extract_schema_required_keys(schema)
    if not schema or not argument_keys:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="tool_schema_missing_arguments",
            schema_present=bool(schema),
        )
    return WiiiConnectComposioToolSchemaResult(
        ready=True,
        provider_slug=provider,
        action_slug=action,
        reason="ready",
        schema_present=True,
        argument_keys=argument_keys,
        required_argument_keys=required_argument_keys,
    )


async def execute_composio_tool(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    action_slug: str,
    user_id: str,
    connected_account_id: str,
    arguments: Mapping[str, Any] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioExecuteResult:
    """Execute one read-only Composio action and redact provider output."""

    provider = _normalize_provider_slug(provider_slug)
    action = _normalize_action_slug(action_slug)
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_adapter_not_configured",
        )
    if action not in config.readonly_action_slugs_for_provider(provider):
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_allowlisted",
        )
    if not user_id or not connected_account_id:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="missing_user_or_connection",
        )

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/tools/execute/{action}"
    )
    payload = {
        "user_id": user_id,
        "connected_account_id": connected_account_id,
        "arguments": dict(arguments or {}),
    }
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            url,
            json=payload,
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            status_code=response.status_code,
            reason="provider_response_rejected",
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            status_code=response.status_code,
            reason="provider_response_invalid",
        )
    if not isinstance(data, Mapping):
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            status_code=response.status_code,
            reason="provider_response_invalid",
        )
    successful = bool(data.get("successful"))
    data_shape = data.get("data")
    data_keys = (
        tuple(sorted(str(key) for key in data_shape.keys()))
        if isinstance(data_shape, Mapping)
        else ()
    )
    return WiiiConnectComposioExecuteResult(
        ready=True,
        provider_slug=provider,
        action_slug=action,
        reason="ready" if successful else "provider_execution_failed",
        successful=successful,
        status_code=response.status_code,
        data_keys=data_keys,
        error_present=bool(data.get("error")),
        session_info_present=bool(data.get("session_info")),
        log_id_present=bool(data.get("log_id")),
    )


def _normalize_action_allowlist_mapping(
    value: Mapping[Any, Any],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for raw_provider, raw_actions in value.items():
        provider = _normalize_provider_slug(raw_provider)
        for action_slug in _coerce_action_values(raw_actions):
            if provider and _curated_read_action_exists(provider, action_slug):
                result.setdefault(provider, set()).add(action_slug)
    return {
        provider: tuple(sorted(actions))
        for provider, actions in sorted(result.items())
        if actions
    }


def _normalize_action_allowlist_items(
    values: Iterable[Any],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for raw_action in values:
        action_slug = _normalize_action_slug(raw_action)
        provider = _provider_for_curated_action_slug(action_slug)
        if provider and _curated_read_action_exists(provider, action_slug):
            result.setdefault(provider, set()).add(action_slug)
    return {
        provider: tuple(sorted(actions))
        for provider, actions in sorted(result.items())
        if actions
    }


def _coerce_action_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return _split_action_slugs(value)
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return tuple(
            action
            for action in (_normalize_action_slug(item) for item in value)
            if action
        )
    action = _normalize_action_slug(value)
    return (action,) if action else ()


def _split_action_slugs(value: Any) -> tuple[str, ...]:
    text = str(value or "")
    for separator in ("|", ";"):
        text = text.replace(separator, ",")
    return tuple(
        action
        for action in (_normalize_action_slug(item) for item in text.split(","))
        if action
    )


def _provider_for_curated_action_slug(action_slug: str) -> str:
    action = _normalize_action_slug(action_slug)
    matches = tuple(
        candidate.provider_slug
        for candidate in list_wiii_connect_curated_actions()
        if candidate.slug == action and candidate.mutation == "read"
    )
    if len(matches) == 1:
        return matches[0]
    return ""


def _curated_read_action_exists(provider_slug: str, action_slug: str) -> bool:
    action = get_wiii_connect_curated_action(provider_slug, action_slug)
    return bool(action and action.mutation == "read")


def _extract_composio_input_schema(data: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in (
        "input_parameters",
        "input_schema",
        "inputSchema",
        "parameters",
        "args_schema",
        "schema",
    ):
        value = data.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _extract_composio_toolkit_slug(data: Mapping[str, Any]) -> str:
    toolkit = data.get("toolkit")
    if isinstance(toolkit, Mapping):
        return _normalize_provider_slug(
            toolkit.get("slug")
            or toolkit.get("toolkit_slug")
            or toolkit.get("name")
            or "",
        )
    return _normalize_provider_slug(data.get("toolkit_slug") or "")


def _extract_schema_argument_keys(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        return tuple(sorted(str(key) for key in properties.keys() if str(key)))
    return tuple(sorted(str(key) for key in schema.keys() if str(key)))


def _extract_schema_required_keys(schema: Mapping[str, Any]) -> tuple[str, ...]:
    required = schema.get("required")
    if isinstance(required, list):
        return tuple(sorted(str(item) for item in required if str(item)))
    keys: list[str] = []
    for key, value in schema.items():
        if isinstance(value, Mapping) and bool(value.get("required")):
            keys.append(str(key))
    return tuple(sorted(keys))


def _normalize_mapping(value: Mapping[Any, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_provider, raw_auth_config in value.items():
        provider = _normalize_provider_slug(raw_provider)
        auth_config = str(raw_auth_config or "").strip()
        if provider and auth_config:
            result[provider] = auth_config
    return result


def _normalize_provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return values
    return values + (value,)


def _connection_record_from_composio_account(
    provider_slug: str,
    account: Any,
) -> WiiiConnectConnectionRecordV1 | None:
    if not isinstance(account, Mapping):
        return None
    connection_id = str(
        account.get("id")
        or account.get("nanoid")
        or account.get("nanoId")
        or account.get("connected_account_id")
        or account.get("connectedAccountId")
        or ""
    ).strip()
    if not connection_id:
        return None
    status = str(account.get("status") or "").strip()
    state = normalize_connection_state(status)
    return WiiiConnectConnectionRecordV1(
        connection_id=connection_id,
        provider_slug=_normalize_provider_slug(provider_slug),
        state=state,
        scopes=WiiiConnectScopeGrant(read=state == "connected"),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug=_normalize_provider_slug(provider_slug),
            connection_id=connection_id,
            vault_key_id=f"provider-managed://composio/{connection_id}",
            secret_version="provider_managed",
        ),
        reason="provider_connection_list",
        warnings=()
        if state == "connected"
        else ("provider_status_not_active",),
    )


def _extract_connection_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, Mapping):
        return []
    for key in ("items", "data", "connected_accounts", "connectedAccounts", "connections"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _safe_connect_link_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "provider_adapter_not_configured",
        "missing_user_or_callback",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
        "provider_response_missing_redirect",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


def _safe_connection_list_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "provider_adapter_not_configured",
        "missing_user",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")


def _safe_public_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]


def _safe_tool_schema_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "action_not_curated",
        "action_not_read_only",
        "provider_adapter_not_configured",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
        "tool_schema_not_found",
        "tool_schema_missing_arguments",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


def _safe_execute_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "provider_adapter_not_configured",
        "action_not_allowlisted",
        "missing_user_or_connection",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
        "provider_execution_failed",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


__all__ = [
    "WIII_CONNECT_COMPOSIO_ADAPTER_VERSION",
    "WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION",
    "WIII_CONNECT_COMPOSIO_EXECUTION_VERSION",
    "WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION",
    "WiiiConnectComposioAdapterConfig",
    "WiiiConnectComposioConnectionListResult",
    "WiiiConnectComposioConnectLinkResult",
    "WiiiConnectComposioExecuteResult",
    "WiiiConnectComposioToolSchemaResult",
    "build_composio_adapter_config",
    "build_composio_connect_enabled_entry",
    "build_composio_execution_enabled_entry",
    "build_composio_external_user_id",
    "build_composio_provider_managed_vault_capability",
    "build_composio_provider_adapter_capability",
    "create_composio_connect_link",
    "execute_composio_tool",
    "list_composio_connected_accounts",
    "parse_composio_auth_config_map",
    "parse_composio_readonly_action_allowlist",
    "verify_composio_tool_schema",
]
