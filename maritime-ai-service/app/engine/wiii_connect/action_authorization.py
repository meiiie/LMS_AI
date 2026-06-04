"""Backend-owned authorization contract for Wiii Connect actions.

External mutations must not be authorized by model-visible booleans or caller
claims. Specialized preview/apply routes may verify approval tokens and pass a
trusted authorization; generic tools and generic APIs should fail closed until
that verified authorization exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .adapter_v1 import ActionMutation


WIII_CONNECT_ACTION_AUTHORIZATION_VERSION = "wiii_connect_action_authorization.v1"

ActionAuthorizationStatus = Literal["not_required", "verified", "required"]
ActionAuthorizationReason = Literal[
    "non_mutating_action",
    "verified_backend_authorization",
    "backend_verified_authorization_required",
]

_MUTATING_ACTIONS: frozenset[str] = frozenset({"write", "apply", "admin"})
_VALID_MUTATIONS: frozenset[str] = frozenset(
    {"read", "preview", "write", "apply", "admin"}
)


@dataclass(frozen=True, slots=True)
class WiiiConnectActionAuthorization:
    """Trusted mutation authorization state for one backend action plan."""

    status: ActionAuthorizationStatus
    reason: ActionAuthorizationReason
    mutation: ActionMutation
    trusted_preview_evidence_id: str | None = None
    trusted_approval_token_present: bool = False
    caller_preview_evidence_present: bool = False
    caller_approval_token_present: bool = False
    caller_authorization_ignored: bool = False

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ACTION_AUTHORIZATION_VERSION,
            "status": self.status,
            "reason": self.reason,
            "mutation": self.mutation,
            "trusted_preview_evidence_present": bool(
                self.trusted_preview_evidence_id
            ),
            "trusted_approval_present": self.trusted_approval_token_present,
            "caller_preview_evidence_present": self.caller_preview_evidence_present,
            "caller_approval_present": self.caller_approval_token_present,
            "caller_claim_ignored": self.caller_authorization_ignored,
        }


def resolve_wiii_connect_action_authorization(
    *,
    mutation: str,
    preview_evidence_id: str | None = None,
    approval_token_present: bool = False,
    authorization_verified: bool = False,
) -> WiiiConnectActionAuthorization:
    """Return trusted authorization values for a Wiii Connect action request."""

    safe_mutation = _safe_mutation(mutation)
    caller_preview_present = bool(_safe_public_id(preview_evidence_id))
    caller_approval_present = bool(approval_token_present)
    if safe_mutation not in _MUTATING_ACTIONS:
        return WiiiConnectActionAuthorization(
            status="not_required",
            reason="non_mutating_action",
            mutation=safe_mutation,
            caller_preview_evidence_present=caller_preview_present,
            caller_approval_token_present=caller_approval_present,
        )
    if authorization_verified:
        return WiiiConnectActionAuthorization(
            status="verified",
            reason="verified_backend_authorization",
            mutation=safe_mutation,
            trusted_preview_evidence_id=_safe_public_id(preview_evidence_id),
            trusted_approval_token_present=bool(approval_token_present),
            caller_preview_evidence_present=caller_preview_present,
            caller_approval_token_present=caller_approval_present,
        )
    return WiiiConnectActionAuthorization(
        status="required",
        reason="backend_verified_authorization_required",
        mutation=safe_mutation,
        caller_preview_evidence_present=caller_preview_present,
        caller_approval_token_present=caller_approval_present,
        caller_authorization_ignored=bool(
            caller_preview_present or caller_approval_present
        ),
    )


def _safe_mutation(value: Any) -> ActionMutation:
    mutation = str(value or "").strip().lower()
    if mutation in _VALID_MUTATIONS:
        return mutation  # type: ignore[return-value]
    return "read"


def _safe_public_id(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if any(marker in text.lower() for marker in ("token", "secret", "password")):
        return None
    return text[:160]


__all__ = [
    "WIII_CONNECT_ACTION_AUTHORIZATION_VERSION",
    "WiiiConnectActionAuthorization",
    "resolve_wiii_connect_action_authorization",
]
