"""Curated Wiii Connect action catalog.

The catalog is the review boundary between a connected external provider and
the action schemas an agent may see. It intentionally stores only public action
metadata and sanitized argument key names, not provider payload schemas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter_v1 import ActionMutation, ProviderKind, ScopeName


WIII_CONNECT_ACTION_CATALOG_VERSION = "wiii_connect_action_catalog.v1"


@dataclass(frozen=True, slots=True)
class WiiiConnectCuratedAction:
    """One reviewed external action candidate."""

    slug: str
    provider_slug: str
    provider_kind: ProviderKind
    label: str
    mutation: ActionMutation = "read"
    path: str = "external_app_action"
    enabled: bool = False
    requires_preview: bool = False
    requires_approval: bool = False
    required_scopes: tuple[ScopeName, ...] = ("read",)
    argument_keys: tuple[str, ...] = ()
    description: str = ""
    source: str = "wiii_connect_action_catalog"
    warnings: tuple[str, ...] = ()

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ACTION_CATALOG_VERSION,
            "slug": self.slug,
            "provider_slug": self.provider_slug,
            "provider_kind": self.provider_kind,
            "label": self.label,
            "mutation": self.mutation,
            "path": self.path,
            "enabled": self.enabled,
            "requires_preview": self.requires_preview,
            "requires_approval": self.requires_approval,
            "required_scopes": list(self.required_scopes),
            "argument_keys": [_safe_public_key(key) for key in self.argument_keys],
            "description": self.description,
            "source": self.source,
            "warnings": list(self.warnings),
        }


_CURATED_ACTIONS: tuple[WiiiConnectCuratedAction, ...] = (
    WiiiConnectCuratedAction(
        slug="GMAIL_FETCH_EMAILS",
        provider_slug="gmail",
        provider_kind="composio",
        label="Fetch Gmail emails",
        mutation="read",
        enabled=False,
        required_scopes=("read",),
        argument_keys=("query", "max_results"),
        description=(
            "Read-only candidate listed in current Composio Gmail docs. Enable "
            "only after a real Gmail auth-config and live tool schema are verified."
        ),
        warnings=("disabled_until_live_gmail_schema_verified",),
    ),
)


def list_wiii_connect_curated_actions(
    *,
    provider_slug: str | None = None,
    include_disabled: bool = True,
) -> tuple[WiiiConnectCuratedAction, ...]:
    """Return curated action metadata, optionally scoped to one provider."""

    provider = _normalize_provider_slug(provider_slug)
    actions = []
    for action in _CURATED_ACTIONS:
        if provider and action.provider_slug != provider:
            continue
        if not include_disabled and not action.enabled:
            continue
        actions.append(action)
    return tuple(sorted(actions, key=lambda item: (item.provider_slug, item.slug)))


def enabled_action_slugs_for_provider(provider_slug: str) -> tuple[str, ...]:
    """Return action slugs that may enter gateway allowlists."""

    return tuple(
        action.slug
        for action in list_wiii_connect_curated_actions(
            provider_slug=provider_slug,
            include_disabled=False,
        )
    )


def action_catalog_summary_for_provider(provider_slug: str) -> dict[str, Any]:
    """Return a privacy-safe catalog summary for one provider."""

    actions = list_wiii_connect_curated_actions(provider_slug=provider_slug)
    enabled = [action for action in actions if action.enabled]
    read_only = [action for action in actions if action.mutation == "read"]
    return {
        "version": WIII_CONNECT_ACTION_CATALOG_VERSION,
        "provider_slug": _normalize_provider_slug(provider_slug),
        "catalog_action_count": len(actions),
        "enabled_action_count": len(enabled),
        "read_only_action_count": len(read_only),
        "write_action_count": len(
            [action for action in actions if action.mutation in {"write", "apply", "admin"}]
        ),
        "enabled_action_slugs": [action.slug for action in enabled],
        "warnings": sorted({warning for action in actions for warning in action.warnings}),
    }


def action_catalog_public_metadata(
    *,
    provider_slug: str | None = None,
    include_disabled: bool = True,
) -> dict[str, Any]:
    """Return the public action catalog projection."""

    actions = list_wiii_connect_curated_actions(
        provider_slug=provider_slug,
        include_disabled=include_disabled,
    )
    return {
        "version": WIII_CONNECT_ACTION_CATALOG_VERSION,
        "provider_slug": _normalize_provider_slug(provider_slug) or None,
        "action_count": len(actions),
        "enabled_action_count": len([action for action in actions if action.enabled]),
        "actions": [action.to_public_metadata() for action in actions],
    }


_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "credential", "key", "code")


def _normalize_provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _safe_public_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "empty"
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return "redacted_sensitive_field"
    return normalized[:80]


__all__ = [
    "WIII_CONNECT_ACTION_CATALOG_VERSION",
    "WiiiConnectCuratedAction",
    "action_catalog_public_metadata",
    "action_catalog_summary_for_provider",
    "enabled_action_slugs_for_provider",
    "list_wiii_connect_curated_actions",
]
