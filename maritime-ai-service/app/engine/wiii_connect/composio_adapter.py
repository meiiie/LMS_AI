"""Composio adapter configuration and Connect Link boundary for Wiii Connect.

The status helpers expose only privacy-safe readiness metadata. The Connect
Link client is the only function in this module that may call Composio, and it
returns only the hosted redirect URL needed by the UI.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import httpx

from .adapter_v1 import (
    WiiiConnectConnectionRecordV1,
    WiiiConnectProviderRegistryEntry,
    WiiiConnectVaultSecretRef,
    normalize_connection_state,
)
from .provider_adapters import WiiiConnectProviderAdapterCapability
from .vault import WiiiConnectVaultCapability, default_wiii_connect_vault_capability


WIII_CONNECT_COMPOSIO_ADAPTER_VERSION = "wiii_connect_composio_adapter.v1"
WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION = "wiii_connect_composio_connections.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioAdapterConfig:
    """Sanitized Composio adapter configuration state."""

    enabled: bool = False
    api_key: str = field(default="", repr=False)
    api_key_present: bool = False
    base_url: str = "https://backend.composio.dev"
    api_version: str = "v3.1"
    auth_config_by_provider: dict[str, str] | None = None

    @property
    def auth_config_count(self) -> int:
        return len(self.auth_config_by_provider or {})

    def auth_config_id_for_provider(self, provider_slug: str) -> str:
        return (self.auth_config_by_provider or {}).get(
            _normalize_provider_slug(provider_slug),
            "",
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


def build_composio_adapter_config(
    settings_obj: Any | None = None,
) -> WiiiConnectComposioAdapterConfig:
    """Build sanitized Composio adapter config from backend settings."""

    if settings_obj is None:
        from app.core.config import settings as settings_obj

    auth_config_map = parse_composio_auth_config_map(
        getattr(settings_obj, "composio_auth_config_map", ""),
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

    return WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=False,
        reason="ready",
        warnings=("action_execution_disabled_until_gateway_enablement",),
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
    return WiiiConnectConnectionRecordV1(
        connection_id=connection_id,
        provider_slug=_normalize_provider_slug(provider_slug),
        state=normalize_connection_state(status),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug=_normalize_provider_slug(provider_slug),
            connection_id=connection_id,
            vault_key_id=f"provider-managed://composio/{connection_id}",
            secret_version="provider_managed",
        ),
        reason="provider_connection_list",
        warnings=()
        if normalize_connection_state(status) == "connected"
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


__all__ = [
    "WIII_CONNECT_COMPOSIO_ADAPTER_VERSION",
    "WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION",
    "WiiiConnectComposioAdapterConfig",
    "WiiiConnectComposioConnectionListResult",
    "WiiiConnectComposioConnectLinkResult",
    "build_composio_adapter_config",
    "build_composio_connect_enabled_entry",
    "build_composio_external_user_id",
    "build_composio_provider_managed_vault_capability",
    "build_composio_provider_adapter_capability",
    "create_composio_connect_link",
    "list_composio_connected_accounts",
    "parse_composio_auth_config_map",
]
