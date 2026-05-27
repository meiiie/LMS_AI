"""Composio adapter configuration status for Wiii Connect.

This module does not call Composio. It turns backend settings into a
privacy-safe provider adapter capability so operators can see whether Wiii is
configured enough to attempt a future Connect Link flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .provider_adapters import WiiiConnectProviderAdapterCapability


WIII_CONNECT_COMPOSIO_ADAPTER_VERSION = "wiii_connect_composio_adapter.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioAdapterConfig:
    """Sanitized Composio adapter configuration state."""

    enabled: bool = False
    api_key_present: bool = False
    base_url: str = "https://backend.composio.dev"
    api_version: str = "v3.1"
    auth_config_by_provider: dict[str, str] | None = None

    @property
    def auth_config_count(self) -> int:
        return len(self.auth_config_by_provider or {})

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
    return WiiiConnectComposioAdapterConfig(
        enabled=bool(getattr(settings_obj, "enable_wiii_connect_composio", False)),
        api_key_present=bool(str(getattr(settings_obj, "composio_api_key", "") or "").strip()),
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


__all__ = [
    "WIII_CONNECT_COMPOSIO_ADAPTER_VERSION",
    "WiiiConnectComposioAdapterConfig",
    "build_composio_adapter_config",
    "build_composio_provider_adapter_capability",
    "parse_composio_auth_config_map",
]
