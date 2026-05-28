"""Backend-owned Wiii Connect provider registry.

This registry is the source of truth for external provider catalog entries that
are visible to Wiii but not executable yet. Entries are deliberately disabled
until provider-specific OAuth, vault, scope, gateway, and audit plumbing exists.
"""

from __future__ import annotations

from typing import Iterable

from .adapter_v1 import (
    WIII_CONNECT_ADAPTER_VERSION,
    ProviderKind,
    WiiiConnectProviderRegistryEntry,
)
from .action_catalog import action_catalog_summary_for_provider
from .composio_adapter import (
    WiiiConnectComposioAdapterConfig,
    build_composio_adapter_config,
    build_composio_execution_enabled_entry,
)


WIII_CONNECT_PROVIDER_REGISTRY_VERSION = "wiii_connect_provider_registry.v1"


_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS = (
    "oauth_or_connect_link",
    "provider_managed_vault_ref",
    "audit_ledger",
)

_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS = (
    "scope_policy",
    "curated_action_catalog",
    "execution_gateway",
)

_DISABLED_COMPOSIO_REQUIREMENTS = (
    _DISABLED_COMPOSIO_CONNECT_REQUIREMENTS
    + _DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS
)


_PROVIDER_REGISTRY: tuple[WiiiConnectProviderRegistryEntry, ...] = (
    WiiiConnectProviderRegistryEntry(
        slug="facebook",
        label="Facebook",
        provider_kind="composio",
        auth_mode="oauth2",
        category="social",
        description="Facebook Pages/content via a brokered OAuth adapter.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="gmail",
        label="Gmail",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Gmail read/write actions with explicit scope gates.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="google_calendar",
        label="Google Calendar",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Calendar lookup and event drafting through Composio.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="google_drive",
        label="Google Drive",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Drive file lookup and source reference workflows.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="notion",
        label="Notion",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Notion workspace search and page drafting.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="slack",
        label="Slack",
        provider_kind="composio",
        auth_mode="oauth2",
        category="chat",
        description="Slack workspace/channel read and message drafting.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="github",
        label="GitHub",
        provider_kind="composio",
        auth_mode="oauth2",
        category="platform",
        description="GitHub issue, PR, and repository workflows.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="airtable",
        label="Airtable",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Airtable base lookup and record drafting.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
    WiiiConnectProviderRegistryEntry(
        slug="asana",
        label="Asana",
        provider_kind="composio",
        auth_mode="oauth2",
        category="productivity",
        description="Asana project/task lookup and task drafting.",
        requirements=_DISABLED_COMPOSIO_REQUIREMENTS,
        connect_requirements=_DISABLED_COMPOSIO_CONNECT_REQUIREMENTS,
        agent_ready_requirements=_DISABLED_COMPOSIO_AGENT_READY_REQUIREMENTS,
        warnings=("adapter_disabled",),
    ),
)


def list_wiii_connect_provider_registry(
    *,
    provider_kind: ProviderKind | None = None,
) -> tuple[WiiiConnectProviderRegistryEntry, ...]:
    """Return provider registry entries filtered by optional provider kind."""

    entries: Iterable[WiiiConnectProviderRegistryEntry] = _PROVIDER_REGISTRY
    if provider_kind is not None:
        entries = (entry for entry in entries if entry.provider_kind == provider_kind)
    return tuple(sorted(entries, key=lambda entry: (entry.provider_kind, entry.slug)))


def get_wiii_connect_provider_entry(
    slug: str,
) -> WiiiConnectProviderRegistryEntry | None:
    """Return one provider registry entry by slug, if registered."""

    key = slug.strip().lower().replace("-", "_")
    if not key:
        return None
    for entry in _PROVIDER_REGISTRY:
        if entry.slug == key:
            return entry
    return None


def provider_registry_public_metadata(
    *,
    composio_config: WiiiConnectComposioAdapterConfig | None = None,
) -> dict[str, object]:
    """Return the privacy-safe provider catalog projection for UI/API use."""

    resolved_composio_config = composio_config or build_composio_adapter_config()
    providers = []
    for entry in list_wiii_connect_provider_registry():
        effective_entry = _provider_registry_runtime_entry(
            entry,
            composio_config=resolved_composio_config,
        )
        metadata = effective_entry.to_public_metadata()
        metadata["action_catalog"] = action_catalog_summary_for_provider(
            effective_entry.slug,
            enabled_slugs=effective_entry.action_allowlist,
        )
        providers.append(metadata)
    return {
        "version": WIII_CONNECT_PROVIDER_REGISTRY_VERSION,
        "adapter_version": WIII_CONNECT_ADAPTER_VERSION,
        "providers": providers,
    }


def _provider_registry_runtime_entry(
    entry: WiiiConnectProviderRegistryEntry,
    *,
    composio_config: WiiiConnectComposioAdapterConfig,
) -> WiiiConnectProviderRegistryEntry:
    if entry.provider_kind != "composio":
        return entry
    return build_composio_execution_enabled_entry(entry, composio_config)
