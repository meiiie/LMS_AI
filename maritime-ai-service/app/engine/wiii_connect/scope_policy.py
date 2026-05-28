"""Wiii Connect provider/action scope policy.

This policy is separate from provider connection state. A provider account can
be connected and still be blocked from agent execution when Wiii has not granted
the required product scope for the selected action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .adapter_v1 import (
    ActionMutation,
    ScopeName,
    WiiiConnectExecutionRequest,
    WiiiConnectProviderRegistryEntry,
    WiiiConnectScopeGrant,
)


WIII_CONNECT_SCOPE_POLICY_VERSION = "wiii_connect_scope_policy.v1"

ScopePolicyReason = Literal[
    "allowed",
    "scope_policy_denied",
    "scope_policy_provider_mismatch",
]


@dataclass(frozen=True, slots=True)
class WiiiConnectScopePolicy:
    """Wiii-owned scope grant for one provider/action boundary."""

    provider_slug: str
    allowed_scopes: WiiiConnectScopeGrant = field(default_factory=WiiiConnectScopeGrant)
    source: str = "provider_registry_default_scopes"
    warnings: tuple[str, ...] = ()

    def allows(self, scope: ScopeName) -> bool:
        return self.allowed_scopes.allows(scope)

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_SCOPE_POLICY_VERSION,
            "provider_slug": _safe_slug(self.provider_slug),
            "allowed_scopes": list(self.allowed_scopes.enabled_scopes()),
            "source": _safe_slug(self.source),
            "warnings": [_safe_slug(warning) for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectScopePolicyDecision:
    """Policy decision before a provider action may enter the adapter."""

    status: Literal["allowed", "blocked"]
    reason: ScopePolicyReason
    provider_slug: str
    required_scopes: tuple[ScopeName, ...] = ()
    allowed_scopes: tuple[ScopeName, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_SCOPE_POLICY_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": _safe_slug(self.provider_slug),
            "required_scopes": list(self.required_scopes),
            "allowed_scopes": list(self.allowed_scopes),
        }


def scope_policy_for_provider_entry(
    entry: WiiiConnectProviderRegistryEntry,
) -> WiiiConnectScopePolicy:
    """Build the runtime scope policy from the effective provider entry."""

    return WiiiConnectScopePolicy(
        provider_slug=entry.slug,
        allowed_scopes=entry.default_scopes,
    )


def decide_scope_policy(
    policy: WiiiConnectScopePolicy,
    request: WiiiConnectExecutionRequest,
) -> WiiiConnectScopePolicyDecision:
    """Return whether Wiii policy permits the requested mutation scope."""

    required_scope = required_scope_for_mutation(request.mutation)
    if _safe_slug(policy.provider_slug) != _safe_slug(request.provider_slug):
        return WiiiConnectScopePolicyDecision(
            status="blocked",
            reason="scope_policy_provider_mismatch",
            provider_slug=request.provider_slug,
            required_scopes=(required_scope,),
            allowed_scopes=policy.allowed_scopes.enabled_scopes(),
        )
    if not policy.allows(required_scope):
        return WiiiConnectScopePolicyDecision(
            status="blocked",
            reason="scope_policy_denied",
            provider_slug=request.provider_slug,
            required_scopes=(required_scope,),
            allowed_scopes=policy.allowed_scopes.enabled_scopes(),
        )
    return WiiiConnectScopePolicyDecision(
        status="allowed",
        reason="allowed",
        provider_slug=request.provider_slug,
        required_scopes=(required_scope,),
        allowed_scopes=policy.allowed_scopes.enabled_scopes(),
    )


def required_scope_for_mutation(mutation: ActionMutation) -> ScopeName:
    """Return the minimum Wiii Connect scope required by a mutation class."""

    if mutation == "admin":
        return "admin"
    if mutation == "apply":
        return "apply"
    if mutation == "write":
        return "write"
    if mutation == "preview":
        return "preview"
    return "read"


def _safe_slug(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:120] or "unknown"


__all__ = [
    "WIII_CONNECT_SCOPE_POLICY_VERSION",
    "WiiiConnectScopePolicy",
    "WiiiConnectScopePolicyDecision",
    "decide_scope_policy",
    "required_scope_for_mutation",
    "scope_policy_for_provider_entry",
]
