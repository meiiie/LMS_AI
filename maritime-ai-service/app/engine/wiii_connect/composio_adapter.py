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

from app.engine.runtime.event_payload_sanitizer import redact_runtime_secret_text

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
from .argument_key_policy import (
    WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
    hidden_model_argument_key_count,
    safe_public_argument_keys,
)
from .provider_adapters import WiiiConnectProviderAdapterCapability
from .vault import WiiiConnectVaultCapability, default_wiii_connect_vault_capability


WIII_CONNECT_COMPOSIO_ADAPTER_VERSION = "wiii_connect_composio_adapter.v1"
WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION = "wiii_connect_composio_connections.v1"
WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION = "wiii_connect_composio_tool_schema.v1"
WIII_CONNECT_COMPOSIO_EXECUTION_VERSION = "wiii_connect_composio_execution.v1"
WIII_CONNECT_COMPOSIO_DISCONNECT_VERSION = "wiii_connect_composio_disconnect.v1"
WIII_CONNECT_COMPOSIO_FILE_UPLOAD_VERSION = "wiii_connect_composio_file_upload.v1"
WIII_CONNECT_FACEBOOK_PAGE_LIST_VERSION = "wiii_connect_facebook_pages.v1"


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
    apply_execute_enabled: bool = False
    apply_action_allowlist_by_provider: dict[str, tuple[str, ...]] | None = None

    @property
    def auth_config_count(self) -> int:
        return len(self.auth_config_by_provider or {})

    @property
    def readonly_action_count(self) -> int:
        return sum(
            len(actions)
            for actions in (self.readonly_action_allowlist_by_provider or {}).values()
        )

    @property
    def apply_action_count(self) -> int:
        return sum(
            len(actions)
            for actions in (self.apply_action_allowlist_by_provider or {}).values()
        )

    @property
    def executable_action_count(self) -> int:
        return self.readonly_action_count + self.apply_action_count

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
            mutations=("read",),
        )

    def apply_action_slugs_for_provider(self, provider_slug: str) -> tuple[str, ...]:
        provider = _normalize_provider_slug(provider_slug)
        enabled_slugs = (self.apply_action_allowlist_by_provider or {}).get(
            provider,
            (),
        )
        return configured_action_slugs_for_provider(
            provider,
            enabled_slugs=enabled_slugs,
            mutations=("apply",),
        )

    def executable_action_slugs_for_provider(self, provider_slug: str) -> tuple[str, ...]:
        provider = _normalize_provider_slug(provider_slug)
        actions = set()
        if self.readonly_execute_enabled:
            actions.update(self.readonly_action_slugs_for_provider(provider))
        if self.apply_execute_enabled:
            actions.update(self.apply_action_slugs_for_provider(provider))
        return tuple(sorted(actions))

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
            "apply_execute_enabled": self.apply_execute_enabled,
            "apply_action_count": self.apply_action_count,
            "apply_action_provider_slugs": sorted(
                (self.apply_action_allowlist_by_provider or {}).keys(),
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
class WiiiConnectComposioAuthConfigLookupResult:
    """Internal auth-config lookup result.

    Auth config ids are provider configuration handles. They must never be
    exposed through public metadata or chat-visible payloads.
    """

    ready: bool = False
    auth_config_id: str = field(default="", repr=False)
    reason: str = "not_requested"


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
    request_id: str = ""
    schema_present: bool = False
    argument_keys: tuple[str, ...] = ()
    required_argument_keys: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        metadata = {
            "version": WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION,
            "status": "ready" if self.ready else "blocked",
            "reason": _safe_tool_schema_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "action_slug": _normalize_action_slug(self.action_slug),
            "schema_present": self.schema_present,
            "argument_policy_version": WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
            "argument_keys": list(safe_public_argument_keys(self.argument_keys)),
            "required_argument_keys": list(
                safe_public_argument_keys(self.required_argument_keys)
            ),
            "hidden_argument_count": hidden_model_argument_key_count(
                provider_slug=self.provider_slug,
                action_slug=self.action_slug,
                argument_keys=self.argument_keys,
            ),
        }
        request_id = _safe_request_id(self.request_id)
        if request_id:
            metadata["request_id"] = request_id
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioExecuteResult:
    """Sanitized Composio tool execution result."""

    ready: bool = False
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = "not_requested"
    request_id: str = ""
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
        metadata = {
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
        request_id = _safe_request_id(self.request_id)
        if request_id:
            metadata["request_id"] = request_id
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioFileUploadResult:
    """Sanitized Composio file-staging result for user-approved uploads."""

    ready: bool = False
    provider_slug: str = ""
    action_slug: str = ""
    reason: str = "not_requested"
    request_id: str = ""
    status_code: int = 0
    file_descriptor: dict[str, str] = field(default_factory=dict, repr=False)
    file_ref_present: bool = False
    upload_url_present: bool = False
    size_bytes: int = 0

    def to_public_metadata(self) -> dict[str, Any]:
        metadata = {
            "version": WIII_CONNECT_COMPOSIO_FILE_UPLOAD_VERSION,
            "status": "ready" if self.ready else "blocked",
            "reason": _safe_execute_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "action_slug": _normalize_action_slug(self.action_slug),
            "file_ref_present": self.file_ref_present,
            "upload_url_present": self.upload_url_present,
            "size_bytes": self.size_bytes,
            "status_code": self.status_code,
        }
        request_id = _safe_request_id(self.request_id)
        if request_id:
            metadata["request_id"] = request_id
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectFacebookPageOption:
    """A sanitized Facebook Page selector option."""

    page_id: str
    name: str = ""
    category: str = ""
    link: str = ""

    def to_public_metadata(self) -> dict[str, str]:
        return {
            "page_id": _safe_public_key(self.page_id),
            "name": _safe_page_text(self.name),
            "category": _safe_page_text(self.category),
            "link": _safe_page_link(self.link),
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectFacebookPageListResult:
    """Sanitized result for the Facebook managed Page selector."""

    ready: bool = False
    reason: str = "not_requested"
    provider_slug: str = "facebook"
    action_slug: str = "FACEBOOK_LIST_MANAGED_PAGES"
    request_id: str = ""
    status_code: int = 0
    pages: tuple[WiiiConnectFacebookPageOption, ...] = ()
    error_present: bool = False

    @property
    def status(self) -> str:
        return "ready" if self.ready else "blocked"

    def to_public_metadata(self) -> dict[str, Any]:
        metadata = {
            "version": WIII_CONNECT_FACEBOOK_PAGE_LIST_VERSION,
            "status": self.status,
            "reason": _safe_execute_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "action_slug": _normalize_action_slug(self.action_slug),
            "status_code": self.status_code,
            "page_count": len(self.pages),
            "error_present": self.error_present,
            "pages": [page.to_public_metadata() for page in self.pages],
        }
        request_id = _safe_request_id(self.request_id)
        if request_id:
            metadata["request_id"] = request_id
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectComposioDisconnectResult:
    """Sanitized Composio connected-account delete result."""

    ready: bool = False
    provider_slug: str = ""
    reason: str = "not_requested"
    status_code: int = 0
    connection_ref_present: bool = False
    provider_success: bool = False

    @property
    def status(self) -> str:
        if self.ready and self.provider_success:
            return "succeeded"
        if self.ready:
            return "failed"
        return "blocked"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_COMPOSIO_DISCONNECT_VERSION,
            "status": self.status,
            "reason": _safe_disconnect_reason(self.reason),
            "provider_slug": _normalize_provider_slug(self.provider_slug),
            "status_code": self.status_code,
            "connection_ref_present": self.connection_ref_present,
            "provider_success": self.provider_success,
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

    return _parse_composio_action_allowlist(raw_value, mutations=("read",))


def parse_composio_apply_action_allowlist(
    raw_value: Any,
) -> dict[str, tuple[str, ...]]:
    """Parse provider->apply action allowlist from JSON or comma text."""

    return _parse_composio_action_allowlist(raw_value, mutations=("apply",))


def _parse_composio_action_allowlist(
    raw_value: Any,
    *,
    mutations: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    """Parse provider->action allowlist from JSON or comma text."""

    if isinstance(raw_value, Mapping):
        return _normalize_action_allowlist_mapping(raw_value, mutations=mutations)
    text = str(raw_value or "").strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return _normalize_action_allowlist_mapping(parsed, mutations=mutations)
        if isinstance(parsed, list):
            return _normalize_action_allowlist_items(parsed, mutations=mutations)
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
            provider = provider_slug or _provider_for_curated_action_slug(
                action_slug,
                mutations=mutations,
            )
            if provider and _curated_action_exists(
                provider,
                action_slug,
                mutations=mutations,
            ):
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
    apply_allowlist = parse_composio_apply_action_allowlist(
        getattr(settings_obj, "composio_apply_action_allowlist", ""),
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
        apply_execute_enabled=bool(
            getattr(
                settings_obj,
                "enable_wiii_connect_composio_apply_execute",
                False,
            )
        ),
        apply_action_allowlist_by_provider=apply_allowlist,
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
    can_execute_readonly = bool(
        resolved.readonly_execute_enabled and resolved.readonly_action_count > 0
    )
    can_execute_apply = bool(
        resolved.apply_execute_enabled and resolved.apply_action_count > 0
    )
    can_execute = can_execute_readonly or can_execute_apply
    warnings_list: list[str] = []
    if can_execute_readonly:
        warnings_list.append("composio_readonly_execution_limited_to_curated_allowlist")
    if can_execute_apply:
        warnings_list.append("composio_apply_execution_requires_preview_and_approval")
    if resolved.auth_config_count <= 0:
        warnings_list.append("composio_auth_config_will_be_resolved_from_provider")
    if not warnings_list:
        warnings_list.append("execution_disabled_or_no_curated_actions")
    return WiiiConnectProviderAdapterCapability(
        provider_kind="composio",
        adapter_name="composio_adapter",
        bound=True,
        configured=True,
        can_create_authorization_url=True,
        can_exchange_callback=True,
        can_execute_actions=can_execute,
        reason="ready",
        warnings=tuple(warnings_list),
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
    if not capability.authorization_ready:
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
    """Enable execution for configured curated Composio actions only."""

    connect_entry = build_composio_connect_enabled_entry(
        entry,
        config,
        settings_obj=settings_obj,
    )
    if connect_entry.provider_kind != "composio" or not connect_entry.enabled:
        return connect_entry

    resolved = config or build_composio_adapter_config(settings_obj)
    readonly_actions = (
        resolved.readonly_action_slugs_for_provider(connect_entry.slug)
        if resolved.readonly_execute_enabled
        else ()
    )
    apply_actions = (
        resolved.apply_action_slugs_for_provider(connect_entry.slug)
        if resolved.apply_execute_enabled
        else ()
    )
    allowed_actions = tuple(sorted(set(readonly_actions + apply_actions)))
    if not allowed_actions:
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
        "agent_actions_require_live_schema_verification",
    )
    if apply_actions:
        warnings = _append_unique(
            warnings,
            "apply_agent_actions_require_preview_approval_and_scope_grant",
        )
    return replace(
        connect_entry,
        agent_ready=True,
        requirements=(),
        agent_ready_requirements=(),
        action_allowlist=allowed_actions,
        default_scopes=WiiiConnectScopeGrant(
            read=bool(readonly_actions or apply_actions),
            preview=bool(apply_actions),
            apply=bool(apply_actions),
        ),
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


async def resolve_composio_auth_config_id(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioAuthConfigLookupResult:
    """Resolve the Composio auth_config_id for a toolkit.

    Deployment config may pin provider->auth_config ids. If it does not, use
    the same direct-mode pattern OpenHuman uses: ask Composio for the enabled
    auth config matching the toolkit slug. The resolved id stays server-side.
    """

    provider = _normalize_provider_slug(provider_slug)
    configured = config.auth_config_id_for_provider(provider)
    if configured:
        return WiiiConnectComposioAuthConfigLookupResult(
            ready=True,
            auth_config_id=configured,
            reason="configured",
        )
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_adapter_not_configured",
        )
    if not provider:
        return WiiiConnectComposioAuthConfigLookupResult(reason="missing_provider")

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/auth_configs"
    )
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.get(
            url,
            params={
                "toolkit_slug": provider,
                "show_disabled": "true",
                "limit": "25",
            },
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_response_rejected",
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_response_invalid",
        )

    items = _extract_auth_config_items(data)
    if not items:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_auth_config_missing",
        )
    preferred = next(
        (item for item in items if _is_composio_auth_config_enabled(item)),
        items[0],
    )
    auth_config_id = _safe_auth_config_id(preferred)
    if not auth_config_id:
        return WiiiConnectComposioAuthConfigLookupResult(
            reason="provider_response_invalid",
        )
    return WiiiConnectComposioAuthConfigLookupResult(
        ready=True,
        auth_config_id=auth_config_id,
        reason="provider_lookup",
    )


async def create_composio_connect_link(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    user_id: str,
    callback_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioConnectLinkResult:
    """Create a Composio hosted auth link without leaking provider payloads."""

    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioConnectLinkResult(
            reason="provider_adapter_not_configured",
        )
    if not user_id or not callback_url:
        return WiiiConnectComposioConnectLinkResult(
            reason="missing_user_or_callback",
        )

    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        auth_config = await resolve_composio_auth_config_id(
            config=config,
            provider_slug=provider_slug,
            http_client=client,
        )
        if not auth_config.ready:
            return WiiiConnectComposioConnectLinkResult(reason=auth_config.reason)

        payload = {
            "auth_config_id": auth_config.auth_config_id,
            "user_id": user_id,
            "callback_url": callback_url,
        }
        url = (
            f"{config.base_url.rstrip('/')}/api/"
            f"{config.api_version.strip('/')}/connected_accounts/link"
        )
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

    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioConnectionListResult(
            reason="provider_adapter_not_configured",
        )
    if not user_id:
        return WiiiConnectComposioConnectionListResult(reason="missing_user")

    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        auth_config = await resolve_composio_auth_config_id(
            config=config,
            provider_slug=provider_slug,
            http_client=client,
        )
        if not auth_config.ready:
            return WiiiConnectComposioConnectionListResult(reason=auth_config.reason)

        url = (
            f"{config.base_url.rstrip('/')}/api/"
            f"{config.api_version.strip('/')}/connected_accounts"
        )
        params: list[tuple[str, str | int]] = [
            ("user_ids", user_id),
            ("auth_config_ids", auth_config.auth_config_id),
            ("account_type", "PRIVATE"),
            ("limit", max(1, min(int(limit or 50), 100))),
        ]
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
    request_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioToolSchemaResult:
    """Fetch one Composio tool schema and return only safe shape metadata."""

    provider = _normalize_provider_slug(provider_slug)
    action = _normalize_action_slug(action_slug)
    safe_request_id = _safe_request_id(request_id)
    curated = get_wiii_connect_curated_action(provider, action)
    if curated is None:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_curated",
            request_id=safe_request_id,
        )
    if action not in config.executable_action_slugs_for_provider(provider):
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_allowlisted",
            request_id=safe_request_id,
        )
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_adapter_not_configured",
            request_id=safe_request_id,
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
            headers=_provider_request_headers(config, request_id=safe_request_id),
        )
    except httpx.HTTPError:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_transport_error",
            request_id=safe_request_id,
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_rejected",
            request_id=safe_request_id,
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_invalid",
            request_id=safe_request_id,
        )
    if not isinstance(data, Mapping):
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_response_invalid",
            request_id=safe_request_id,
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
            request_id=safe_request_id,
        )
    toolkit_slug = _extract_composio_toolkit_slug(data)
    if toolkit_slug and toolkit_slug != provider:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="tool_schema_not_found",
            request_id=safe_request_id,
        )

    schema = _extract_composio_input_schema(data)
    argument_keys = _extract_schema_argument_keys(schema)
    required_argument_keys = _extract_schema_required_keys(schema)
    if not schema or not argument_keys:
        return WiiiConnectComposioToolSchemaResult(
            provider_slug=provider,
            action_slug=action,
            reason="tool_schema_missing_arguments",
            request_id=safe_request_id,
            schema_present=bool(schema),
        )
    return WiiiConnectComposioToolSchemaResult(
        ready=True,
        provider_slug=provider,
        action_slug=action,
        reason="ready",
        request_id=safe_request_id,
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
    request_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioExecuteResult:
    """Execute one curated Composio action and redact provider output."""

    provider = _normalize_provider_slug(provider_slug)
    action = _normalize_action_slug(action_slug)
    safe_request_id = _safe_request_id(request_id)
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_adapter_not_configured",
            request_id=safe_request_id,
        )
    if action not in config.executable_action_slugs_for_provider(provider):
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_allowlisted",
            request_id=safe_request_id,
        )
    if not user_id or not connected_account_id:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="missing_user_or_connection",
            request_id=safe_request_id,
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
            headers=_provider_request_headers(config, request_id=safe_request_id),
        )
    except httpx.HTTPError:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_transport_error",
            request_id=safe_request_id,
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
            request_id=safe_request_id,
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            status_code=response.status_code,
            reason="provider_response_invalid",
            request_id=safe_request_id,
        )
    if not isinstance(data, Mapping):
        return WiiiConnectComposioExecuteResult(
            provider_slug=provider,
            action_slug=action,
            status_code=response.status_code,
            reason="provider_response_invalid",
            request_id=safe_request_id,
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
        request_id=safe_request_id,
        successful=successful,
        status_code=response.status_code,
        data_keys=data_keys,
        error_present=bool(data.get("error")),
        session_info_present=bool(data.get("session_info")),
        log_id_present=bool(data.get("log_id")),
    )


async def stage_composio_file_upload(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    action_slug: str,
    filename: str,
    mimetype: str,
    content: bytes,
    request_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioFileUploadResult:
    """Stage one user-selected file for a curated Composio tool argument."""

    provider = _normalize_provider_slug(provider_slug)
    action = _normalize_action_slug(action_slug)
    safe_request_id = _safe_request_id(request_id)
    safe_filename = _safe_filename(filename)
    safe_mimetype = _safe_mimetype(mimetype)
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioFileUploadResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_adapter_not_configured",
            request_id=safe_request_id,
        )
    if action not in config.executable_action_slugs_for_provider(provider):
        return WiiiConnectComposioFileUploadResult(
            provider_slug=provider,
            action_slug=action,
            reason="action_not_allowlisted",
            request_id=safe_request_id,
        )
    if not content or not safe_filename or not safe_mimetype:
        return WiiiConnectComposioFileUploadResult(
            provider_slug=provider,
            action_slug=action,
            reason="missing_file",
            request_id=safe_request_id,
        )

    request_url = f"{config.base_url.rstrip('/')}/api/v3/files/upload/request"
    payload = {
        "toolkit_slug": provider,
        "tool_slug": action,
        "filename": safe_filename,
        "mimetype": safe_mimetype,
        "md5": hashlib.md5(content, usedforsecurity=False).hexdigest(),
    }
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=60)
    try:
        response = await client.post(
            request_url,
            json=payload,
            headers=_provider_request_headers(config, request_id=safe_request_id),
        )
    except httpx.HTTPError:
        return WiiiConnectComposioFileUploadResult(
            provider_slug=provider,
            action_slug=action,
            reason="provider_transport_error",
            request_id=safe_request_id,
            size_bytes=len(content),
        )

    try:
        if response.status_code < 200 or response.status_code >= 300:
            return WiiiConnectComposioFileUploadResult(
                provider_slug=provider,
                action_slug=action,
                status_code=response.status_code,
                reason="provider_response_rejected",
                request_id=safe_request_id,
                size_bytes=len(content),
            )
        try:
            data = response.json()
        except ValueError:
            return WiiiConnectComposioFileUploadResult(
                provider_slug=provider,
                action_slug=action,
                status_code=response.status_code,
                reason="provider_response_invalid",
                request_id=safe_request_id,
                size_bytes=len(content),
            )
        if not isinstance(data, Mapping):
            return WiiiConnectComposioFileUploadResult(
                provider_slug=provider,
                action_slug=action,
                status_code=response.status_code,
                reason="provider_response_invalid",
                request_id=safe_request_id,
                size_bytes=len(content),
            )
        s3key = str(
            data.get("key")
            or data.get("s3key")
            or data.get("s3Key")
            or ""
        ).strip()
        upload_url = str(
            data.get("new_presigned_url")
            or data.get("newPresignedUrl")
            or data.get("presigned_url")
            or data.get("presignedUrl")
            or ""
        ).strip()
        if not s3key:
            return WiiiConnectComposioFileUploadResult(
                provider_slug=provider,
                action_slug=action,
                status_code=response.status_code,
                reason="provider_response_invalid",
                request_id=safe_request_id,
                size_bytes=len(content),
            )
        if upload_url:
            try:
                upload_response = await client.put(
                    upload_url,
                    content=content,
                    headers={"Content-Type": safe_mimetype},
                )
            except httpx.HTTPError:
                return WiiiConnectComposioFileUploadResult(
                    provider_slug=provider,
                    action_slug=action,
                    status_code=response.status_code,
                    reason="provider_transport_error",
                    request_id=safe_request_id,
                    file_ref_present=True,
                    upload_url_present=True,
                    size_bytes=len(content),
                )
            if upload_response.status_code < 200 or upload_response.status_code >= 300:
                return WiiiConnectComposioFileUploadResult(
                    provider_slug=provider,
                    action_slug=action,
                    status_code=upload_response.status_code,
                    reason="provider_response_rejected",
                    request_id=safe_request_id,
                    file_ref_present=True,
                    upload_url_present=True,
                    size_bytes=len(content),
                )
        return WiiiConnectComposioFileUploadResult(
            ready=True,
            provider_slug=provider,
            action_slug=action,
            reason="ready",
            request_id=safe_request_id,
            status_code=response.status_code,
            file_descriptor={
                "name": safe_filename,
                "mimetype": safe_mimetype,
                "s3key": s3key,
            },
            file_ref_present=True,
            upload_url_present=bool(upload_url),
            size_bytes=len(content),
        )
    finally:
        if client_created:
            await client.aclose()


async def list_composio_facebook_pages(
    *,
    config: WiiiConnectComposioAdapterConfig,
    user_id: str,
    connected_account_id: str,
    request_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectFacebookPageListResult:
    """List sanitized Facebook Pages for the user-approved account."""

    provider = "facebook"
    action = "FACEBOOK_LIST_MANAGED_PAGES"
    safe_request_id = _safe_request_id(request_id)
    if not config.enabled or not config.api_key_present:
        return WiiiConnectFacebookPageListResult(
            reason="provider_adapter_not_configured",
            request_id=safe_request_id,
        )
    if action not in config.executable_action_slugs_for_provider(provider):
        return WiiiConnectFacebookPageListResult(
            reason="action_not_allowlisted",
            request_id=safe_request_id,
        )
    if not user_id or not connected_account_id:
        return WiiiConnectFacebookPageListResult(
            reason="missing_user_or_connection",
            request_id=safe_request_id,
        )

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/tools/execute/{action}"
    )
    payload = {
        "user_id": user_id,
        "connected_account_id": connected_account_id,
        "arguments": {"fields": "id,name,category,link", "limit": 25},
    }
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30)
    try:
        response = await client.post(
            url,
            json=payload,
            headers=_provider_request_headers(config, request_id=safe_request_id),
        )
    except httpx.HTTPError:
        return WiiiConnectFacebookPageListResult(
            reason="provider_transport_error",
            request_id=safe_request_id,
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectFacebookPageListResult(
            status_code=response.status_code,
            reason="provider_response_rejected",
            request_id=safe_request_id,
        )
    try:
        data = response.json()
    except ValueError:
        return WiiiConnectFacebookPageListResult(
            status_code=response.status_code,
            reason="provider_response_invalid",
            request_id=safe_request_id,
        )
    if not isinstance(data, Mapping):
        return WiiiConnectFacebookPageListResult(
            status_code=response.status_code,
            reason="provider_response_invalid",
            request_id=safe_request_id,
        )
    pages = tuple(
        page
        for page in (_facebook_page_option_from_item(item) for item in _extract_facebook_page_items(data))
        if page is not None
    )
    return WiiiConnectFacebookPageListResult(
        ready=bool(data.get("successful", True)),
        reason="ready" if bool(data.get("successful", True)) else "provider_execution_failed",
        request_id=safe_request_id,
        status_code=response.status_code,
        pages=pages,
        error_present=bool(data.get("error")),
    )


async def disconnect_composio_connected_account(
    *,
    config: WiiiConnectComposioAdapterConfig,
    provider_slug: str,
    connected_account_id: str,
    http_client: httpx.AsyncClient | None = None,
) -> WiiiConnectComposioDisconnectResult:
    """Soft-delete a Composio connected account without leaking payloads."""

    provider = _normalize_provider_slug(provider_slug)
    connection_id = str(connected_account_id or "").strip()
    if not config.enabled or not config.api_key_present:
        return WiiiConnectComposioDisconnectResult(
            provider_slug=provider,
            connection_ref_present=bool(connection_id),
            reason="provider_adapter_not_configured",
        )
    if not connection_id:
        return WiiiConnectComposioDisconnectResult(
            provider_slug=provider,
            reason="missing_connection",
        )

    url = (
        f"{config.base_url.rstrip('/')}/api/"
        f"{config.api_version.strip('/')}/connected_accounts/{connection_id}"
    )
    client_created = http_client is None
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        auth_config = await resolve_composio_auth_config_id(
            config=config,
            provider_slug=provider,
            http_client=client,
        )
        if not auth_config.ready:
            return WiiiConnectComposioDisconnectResult(
                provider_slug=provider,
                connection_ref_present=True,
                reason=auth_config.reason,
            )

        response = await client.delete(
            url,
            headers={"x-api-key": config.api_key},
        )
    except httpx.HTTPError:
        return WiiiConnectComposioDisconnectResult(
            provider_slug=provider,
            connection_ref_present=True,
            reason="provider_transport_error",
        )
    finally:
        if client_created:
            await client.aclose()

    if response.status_code < 200 or response.status_code >= 300:
        return WiiiConnectComposioDisconnectResult(
            provider_slug=provider,
            status_code=response.status_code,
            connection_ref_present=True,
            reason="provider_response_rejected",
        )
    provider_success = True
    if response.content:
        try:
            data = response.json()
        except ValueError:
            return WiiiConnectComposioDisconnectResult(
                provider_slug=provider,
                status_code=response.status_code,
                connection_ref_present=True,
                reason="provider_response_invalid",
            )
        if isinstance(data, Mapping) and "success" in data:
            provider_success = bool(data.get("success"))
    return WiiiConnectComposioDisconnectResult(
        ready=True,
        provider_slug=provider,
        status_code=response.status_code,
        connection_ref_present=True,
        reason="ready" if provider_success else "provider_disconnect_failed",
        provider_success=provider_success,
    )


def _normalize_action_allowlist_mapping(
    value: Mapping[Any, Any],
    *,
    mutations: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for raw_provider, raw_actions in value.items():
        provider = _normalize_provider_slug(raw_provider)
        for action_slug in _coerce_action_values(raw_actions):
            if provider and _curated_action_exists(
                provider,
                action_slug,
                mutations=mutations,
            ):
                result.setdefault(provider, set()).add(action_slug)
    return {
        provider: tuple(sorted(actions))
        for provider, actions in sorted(result.items())
        if actions
    }


def _normalize_action_allowlist_items(
    values: Iterable[Any],
    *,
    mutations: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for raw_action in values:
        action_slug = _normalize_action_slug(raw_action)
        provider = _provider_for_curated_action_slug(action_slug, mutations=mutations)
        if provider and _curated_action_exists(provider, action_slug, mutations=mutations):
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


def _provider_for_curated_action_slug(
    action_slug: str,
    *,
    mutations: tuple[str, ...],
) -> str:
    action = _normalize_action_slug(action_slug)
    matches = tuple(
        candidate.provider_slug
        for candidate in list_wiii_connect_curated_actions()
        if candidate.slug == action and candidate.mutation in mutations
    )
    if len(matches) == 1:
        return matches[0]
    return ""


def _curated_action_exists(
    provider_slug: str,
    action_slug: str,
    *,
    mutations: tuple[str, ...],
) -> bool:
    action = get_wiii_connect_curated_action(provider_slug, action_slug)
    return bool(action and action.mutation in mutations)


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


def _extract_auth_config_items(data: Any) -> list[Mapping[str, Any]]:
    """Extract Composio auth config rows from v3 response variants."""

    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if not isinstance(data, Mapping):
        return []
    for key in ("items", "data", "auth_configs", "authConfigs", "configs"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _is_composio_auth_config_enabled(item: Mapping[str, Any]) -> bool:
    enabled = item.get("enabled")
    if isinstance(enabled, bool):
        return enabled
    status = str(item.get("status") or item.get("state") or "").strip().lower()
    return status in {"active", "enabled", "connected", "ready"}


def _safe_auth_config_id(item: Mapping[str, Any]) -> str:
    return str(
        item.get("id")
        or item.get("nanoid")
        or item.get("nanoId")
        or item.get("auth_config_id")
        or item.get("authConfigId")
        or ""
    ).strip()


def _extract_facebook_page_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, Mapping):
        return []
    for key in ("data", "pages", "items", "accounts"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            nested = _extract_facebook_page_items(value)
            if nested:
                return nested
    provider_data = data.get("data")
    if isinstance(provider_data, Mapping):
        return _extract_facebook_page_items(provider_data)
    return []


def _facebook_page_option_from_item(item: Any) -> WiiiConnectFacebookPageOption | None:
    if not isinstance(item, Mapping):
        return None
    page_id = _safe_page_id(item.get("id") or item.get("page_id") or "")
    if not page_id:
        return None
    return WiiiConnectFacebookPageOption(
        page_id=page_id,
        name=_safe_page_text(item.get("name") or ""),
        category=_safe_page_text(item.get("category") or ""),
        link=_safe_page_link(item.get("link") or item.get("url") or ""),
    )


def _safe_page_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    allowed = []
    for char in text[:120]:
        if char.isalnum() or char in {"_", "-", ":"}:
            allowed.append(char)
    return "".join(allowed)


def _safe_page_text(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if any(marker in text.lower() for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_value"
    return text[:160]


def _safe_page_link(value: Any) -> str:
    text = str(value or "").strip()
    if not text.startswith(("https://", "http://")):
        return ""
    if any(marker in text.lower() for marker in _SENSITIVE_KEY_MARKERS):
        return ""
    return text[:240]


def _safe_filename(value: Any) -> str:
    text = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not text:
        return "wiii-upload"
    if any(marker in text.lower() for marker in _SENSITIVE_KEY_MARKERS):
        return "wiii-upload"
    allowed = []
    for char in text[:120]:
        if char.isalnum() or char in {" ", ".", "_", "-"}:
            allowed.append(char)
    result = "".join(allowed).strip(" .")
    return result or "wiii-upload"


def _safe_mimetype(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "/" not in text or any(marker in text for marker in _SENSITIVE_KEY_MARKERS):
        return ""
    return text[:80]


def _safe_connect_link_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "provider_adapter_not_configured",
        "missing_user_or_callback",
        "missing_provider",
        "provider_auth_config_missing",
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
        "missing_provider",
        "provider_auth_config_missing",
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


def _safe_request_id(value: Any) -> str:
    text = redact_runtime_secret_text(value, max_length=160)
    text = " ".join(text.split())
    return text[:96]


def _provider_request_headers(
    config: WiiiConnectComposioAdapterConfig,
    *,
    request_id: str | None = None,
) -> dict[str, str]:
    headers = {"x-api-key": config.api_key}
    safe_request_id = _safe_request_id(request_id)
    if safe_request_id:
        headers["X-Request-ID"] = safe_request_id
    return headers


def _safe_tool_schema_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "action_not_curated",
        "action_not_allowlisted",
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
        "missing_file",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
        "provider_execution_failed",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


def _safe_disconnect_reason(value: str) -> str:
    allowed = {
        "ready",
        "not_requested",
        "provider_adapter_not_configured",
        "missing_connection",
        "missing_provider",
        "provider_auth_config_missing",
        "provider_transport_error",
        "provider_response_rejected",
        "provider_response_invalid",
        "provider_disconnect_failed",
    }
    reason = str(value or "").strip()
    return reason if reason in allowed else "provider_response_unavailable"


__all__ = [
    "WIII_CONNECT_COMPOSIO_ADAPTER_VERSION",
    "WIII_CONNECT_COMPOSIO_CONNECTION_LIST_VERSION",
    "WIII_CONNECT_COMPOSIO_DISCONNECT_VERSION",
    "WIII_CONNECT_COMPOSIO_EXECUTION_VERSION",
    "WIII_CONNECT_COMPOSIO_FILE_UPLOAD_VERSION",
    "WIII_CONNECT_COMPOSIO_TOOL_SCHEMA_VERSION",
    "WIII_CONNECT_FACEBOOK_PAGE_LIST_VERSION",
    "WiiiConnectComposioAdapterConfig",
    "WiiiConnectComposioAuthConfigLookupResult",
    "WiiiConnectComposioConnectionListResult",
    "WiiiConnectComposioConnectLinkResult",
    "WiiiConnectComposioDisconnectResult",
    "WiiiConnectComposioExecuteResult",
    "WiiiConnectComposioFileUploadResult",
    "WiiiConnectComposioToolSchemaResult",
    "WiiiConnectFacebookPageListResult",
    "WiiiConnectFacebookPageOption",
    "build_composio_adapter_config",
    "build_composio_connect_enabled_entry",
    "build_composio_execution_enabled_entry",
    "build_composio_external_user_id",
    "build_composio_provider_managed_vault_capability",
    "build_composio_provider_adapter_capability",
    "create_composio_connect_link",
    "disconnect_composio_connected_account",
    "execute_composio_tool",
    "list_composio_facebook_pages",
    "list_composio_connected_accounts",
    "parse_composio_auth_config_map",
    "parse_composio_apply_action_allowlist",
    "parse_composio_readonly_action_allowlist",
    "resolve_composio_auth_config_id",
    "stage_composio_file_upload",
    "verify_composio_tool_schema",
]
