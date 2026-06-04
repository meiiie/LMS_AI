"""Curated Wiii Connect action catalog.

The catalog is the review boundary between a connected external provider and
the action schemas an agent may see. It intentionally stores only public action
metadata and sanitized argument key names, not provider payload schemas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .argument_key_policy import (
    WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
    hidden_model_argument_key_count,
    model_visible_argument_keys,
    safe_public_argument_key,
)
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
            "argument_policy_version": WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION,
            "argument_keys": list(
                model_visible_argument_keys(
                    provider_slug=self.provider_slug,
                    action_slug=self.slug,
                    argument_keys=self.argument_keys,
                )
            ),
            "model_argument_keys": list(
                model_visible_argument_keys(
                    provider_slug=self.provider_slug,
                    action_slug=self.slug,
                    argument_keys=self.argument_keys,
                )
            ),
            "hidden_argument_count": hidden_model_argument_key_count(
                provider_slug=self.provider_slug,
                action_slug=self.slug,
                argument_keys=self.argument_keys,
            ),
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
    WiiiConnectCuratedAction(
        slug="FACEBOOK_LIST_MANAGED_PAGES",
        provider_slug="facebook",
        provider_kind="composio",
        label="List managed Facebook Pages",
        mutation="read",
        enabled=False,
        required_scopes=("read",),
        argument_keys=("fields", "limit", "after", "before", "user_id"),
        description=(
            "Read-only Facebook Page selector. It may expose Page ids and "
            "names to the authenticated user, but must not expose Page access "
            "tokens returned by Facebook/Composio."
        ),
        warnings=("runtime_enabled_requires_live_facebook_schema_verification",),
    ),
    WiiiConnectCuratedAction(
        slug="FACEBOOK_CREATE_POST",
        provider_slug="facebook",
        provider_kind="composio",
        label="Create Facebook Page post",
        mutation="apply",
        enabled=False,
        requires_preview=True,
        requires_approval=True,
        required_scopes=("apply",),
        argument_keys=("page_id", "message", "link", "published", "scheduled_publish_time"),
        description=(
            "Creates a text/link post on a Facebook Page. Wiii may call this "
            "only after a preview, explicit user approval, selected account, "
            "scope grant, schema verification, and audit append."
        ),
        warnings=("external_mutation_requires_preview_and_approval",),
    ),
    WiiiConnectCuratedAction(
        slug="FACEBOOK_CREATE_PHOTO_POST",
        provider_slug="facebook",
        provider_kind="composio",
        label="Create Facebook Page photo post",
        mutation="apply",
        enabled=False,
        requires_preview=True,
        requires_approval=True,
        required_scopes=("apply",),
        argument_keys=("page_id", "message", "photo", "media", "url", "published"),
        description=(
            "Creates a photo post on a Facebook Page. User-uploaded images "
            "must stay behind Wiii preview/apply and use controlled Composio "
            "file staging, never arbitrary local paths from the model."
        ),
        warnings=("external_mutation_requires_preview_and_approval",),
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


def get_wiii_connect_curated_action(
    provider_slug: str,
    action_slug: str,
) -> WiiiConnectCuratedAction | None:
    """Return one curated action candidate for a provider."""

    provider = _normalize_provider_slug(provider_slug)
    action_key = _normalize_action_slug(action_slug)
    if not provider or not action_key:
        return None
    for action in _CURATED_ACTIONS:
        if action.provider_slug == provider and action.slug == action_key:
            return action
    return None


def enabled_action_slugs_for_provider(
    provider_slug: str,
    *,
    enabled_slugs: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return action slugs that may enter gateway allowlists."""

    allowed = {
        _normalize_action_slug(slug)
        for slug in (enabled_slugs or ())
        if _normalize_action_slug(slug)
    }
    return tuple(
        action.slug
        for action in list_wiii_connect_curated_actions(
            provider_slug=provider_slug,
            include_disabled=False,
        )
        if not allowed or action.slug in allowed
    )


def configured_action_slugs_for_provider(
    provider_slug: str,
    *,
    enabled_slugs: Iterable[str],
    mutations: Iterable[ActionMutation] | None = ("read",),
) -> tuple[str, ...]:
    """Return catalog candidates explicitly enabled by deployment config."""

    allowed = {
        _normalize_action_slug(slug)
        for slug in enabled_slugs
        if _normalize_action_slug(slug)
    }
    if not allowed:
        return ()
    allowed_mutations = set(mutations or ())
    return tuple(
        action.slug
        for action in list_wiii_connect_curated_actions(provider_slug=provider_slug)
        if action.slug in allowed
        and (not allowed_mutations or action.mutation in allowed_mutations)
    )


def action_catalog_summary_for_provider(
    provider_slug: str,
    *,
    enabled_slugs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a privacy-safe catalog summary for one provider."""

    actions = list_wiii_connect_curated_actions(provider_slug=provider_slug)
    runtime_enabled = {
        _normalize_action_slug(slug)
        for slug in (enabled_slugs or ())
        if _normalize_action_slug(slug)
    }
    enabled = [
        action
        for action in actions
        if action.enabled or action.slug in runtime_enabled
    ]
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
    enabled_slugs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return the public action catalog projection."""

    enabled = {
        _normalize_action_slug(slug)
        for slug in (enabled_slugs or ())
        if _normalize_action_slug(slug)
    }
    actions = list_wiii_connect_curated_actions(
        provider_slug=provider_slug,
        include_disabled=True,
    )
    if not include_disabled:
        actions = tuple(
            action for action in actions if action.enabled or action.slug in enabled
        )
    return {
        "version": WIII_CONNECT_ACTION_CATALOG_VERSION,
        "provider_slug": _normalize_provider_slug(provider_slug) or None,
        "action_count": len(actions),
        "enabled_action_count": len(
            [action for action in actions if action.enabled or action.slug in enabled]
        ),
        "actions": [
            _public_metadata_with_runtime_enabled(action, action.slug in enabled)
            for action in actions
        ],
    }


def _normalize_provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")


def _public_metadata_with_runtime_enabled(
    action: WiiiConnectCuratedAction,
    runtime_enabled: bool,
) -> dict[str, Any]:
    metadata = action.to_public_metadata()
    if runtime_enabled and not action.enabled:
        metadata["enabled"] = True
        metadata["warnings"] = sorted(
            set(metadata.get("warnings", []))
            | {"runtime_enabled_requires_live_schema_verification"}
        )
    return metadata


def _safe_public_key(value: str) -> str:
    return safe_public_argument_key(value)


__all__ = [
    "WIII_CONNECT_ACTION_CATALOG_VERSION",
    "WiiiConnectCuratedAction",
    "action_catalog_public_metadata",
    "action_catalog_summary_for_provider",
    "configured_action_slugs_for_provider",
    "enabled_action_slugs_for_provider",
    "get_wiii_connect_curated_action",
    "list_wiii_connect_curated_actions",
]
