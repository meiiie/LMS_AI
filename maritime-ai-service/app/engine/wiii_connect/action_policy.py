"""Scoped action-selection policy for Wiii Connect provider tools.

This module is the Wiii analogue of OpenHuman's toolkit-scoped integration
gate: a connected provider may be visible to the model, but an action still has
to pass a reviewed allowlist and an explicit selection policy before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Literal

from .action_catalog import (
    WiiiConnectCuratedAction,
    get_wiii_connect_curated_action,
    list_wiii_connect_curated_actions,
)
from .adapter_v1 import ActionMutation


WIII_CONNECT_ACTION_POLICY_VERSION = "wiii_connect_action_policy.v1"

ActionPolicyStatus = Literal["selected", "blocked"]
ActionPolicyReason = Literal[
    "selected_explicit_action",
    "selected_single_read_action",
    "missing_provider_slug",
    "unknown_curated_action",
    "action_not_allowlisted",
    "no_enabled_actions",
    "explicit_action_required_for_mutation",
    "ambiguous_action_selection",
]

_MUTATING_ACTIONS: frozenset[ActionMutation] = frozenset({"write", "apply", "admin"})
_SAFE_MUTATIONS: frozenset[str] = frozenset({"read", "preview", "write", "apply", "admin"})
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "cho",
        "cua",
        "de",
        "di",
        "for",
        "gi",
        "hay",
        "len",
        "mot",
        "of",
        "on",
        "the",
        "to",
        "toi",
        "wiii",
    }
)
_MUTATION_ALIASES: dict[ActionMutation, tuple[str, ...]] = {
    "read": (
        "check",
        "doc",
        "fetch",
        "get",
        "kiem",
        "list",
        "lay",
        "read",
        "search",
        "tim",
        "tra",
        "xem",
    ),
    "preview": ("draft", "nhap", "preview", "soan", "xem"),
    "write": ("create", "edit", "tao", "update", "write"),
    "apply": ("dang", "gui", "post", "publish", "send"),
    "admin": ("admin", "delete", "remove", "xoa"),
}


@dataclass(frozen=True, slots=True)
class WiiiConnectActionCandidate:
    """Privacy-safe action candidate used in policy diagnostics."""

    slug: str
    provider_slug: str
    mutation: ActionMutation
    label: str
    score: int = 0
    rank_reasons: tuple[str, ...] = ()
    requires_preview: bool = False
    requires_approval: bool = False

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "provider_slug": self.provider_slug,
            "mutation": self.mutation,
            "label": self.label,
            "score": self.score,
            "rank_reasons": list(self.rank_reasons),
            "requires_preview": self.requires_preview,
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True, slots=True)
class WiiiConnectActionPolicyDecision:
    """Decision returned before generic Wiii Connect execution."""

    status: ActionPolicyStatus
    reason: ActionPolicyReason
    provider_slug: str
    requested_action_slug: str = ""
    requested_mutation: ActionMutation = "read"
    action_slug: str = ""
    selected_action: WiiiConnectCuratedAction | None = None
    candidates: tuple[WiiiConnectActionCandidate, ...] = ()

    @property
    def selected(self) -> bool:
        return self.status == "selected" and self.selected_action is not None

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_ACTION_POLICY_VERSION,
            "status": self.status,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "requested_action_slug": self.requested_action_slug,
            "requested_mutation": self.requested_mutation,
            "action_slug": self.action_slug,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_public_metadata() for candidate in self.candidates],
        }


def select_wiii_connect_action(
    *,
    provider_slug: str,
    action_slug: str = "",
    mutation: str = "read",
    action_allowlist: Iterable[str] = (),
    prompt: str = "",
) -> WiiiConnectActionPolicyDecision:
    """Select one reviewed action or return a fail-closed policy reason."""

    provider = _provider_slug(provider_slug)
    requested_action = _action_slug(action_slug)
    requested_mutation = _safe_mutation(mutation)
    if not provider:
        return WiiiConnectActionPolicyDecision(
            status="blocked",
            reason="missing_provider_slug",
            provider_slug="",
            requested_action_slug=requested_action,
            requested_mutation=requested_mutation,
        )

    allowed = _allowed_action_set(action_allowlist)
    candidates = rank_wiii_connect_action_candidates(
        provider_slug=provider,
        action_allowlist=allowed,
        prompt=prompt,
        preferred_mutation=requested_mutation,
    )
    if not allowed:
        return WiiiConnectActionPolicyDecision(
            status="blocked",
            reason="no_enabled_actions",
            provider_slug=provider,
            requested_action_slug=requested_action,
            requested_mutation=requested_mutation,
            candidates=candidates,
        )

    if requested_action:
        action = get_wiii_connect_curated_action(provider, requested_action)
        if action is None:
            return WiiiConnectActionPolicyDecision(
                status="blocked",
                reason="unknown_curated_action",
                provider_slug=provider,
                requested_action_slug=requested_action,
                requested_mutation=requested_mutation,
                action_slug=requested_action,
                candidates=candidates,
            )
        if action.slug not in allowed:
            return WiiiConnectActionPolicyDecision(
                status="blocked",
                reason="action_not_allowlisted",
                provider_slug=provider,
                requested_action_slug=requested_action,
                requested_mutation=requested_mutation,
                action_slug=action.slug,
                candidates=candidates,
            )
        return WiiiConnectActionPolicyDecision(
            status="selected",
            reason="selected_explicit_action",
            provider_slug=provider,
            requested_action_slug=requested_action,
            requested_mutation=requested_mutation,
            action_slug=action.slug,
            selected_action=action,
            candidates=candidates,
        )

    mutation_candidates = tuple(
        candidate for candidate in candidates if candidate.mutation == requested_mutation
    )
    if requested_mutation in _MUTATING_ACTIONS or requested_mutation == "preview":
        return WiiiConnectActionPolicyDecision(
            status="blocked",
            reason="explicit_action_required_for_mutation",
            provider_slug=provider,
            requested_action_slug=requested_action,
            requested_mutation=requested_mutation,
            candidates=mutation_candidates or candidates,
        )
    if len(mutation_candidates) == 1:
        selected = get_wiii_connect_curated_action(provider, mutation_candidates[0].slug)
        return WiiiConnectActionPolicyDecision(
            status="selected",
            reason="selected_single_read_action",
            provider_slug=provider,
            requested_action_slug=requested_action,
            requested_mutation=requested_mutation,
            action_slug=mutation_candidates[0].slug,
            selected_action=selected,
            candidates=mutation_candidates,
        )
    reason: ActionPolicyReason = (
        "no_enabled_actions" if not mutation_candidates else "ambiguous_action_selection"
    )
    return WiiiConnectActionPolicyDecision(
        status="blocked",
        reason=reason,
        provider_slug=provider,
        requested_action_slug=requested_action,
        requested_mutation=requested_mutation,
        candidates=mutation_candidates or candidates,
    )


def rank_wiii_connect_action_candidates(
    *,
    provider_slug: str,
    action_allowlist: Iterable[str],
    prompt: str = "",
    preferred_mutation: str = "read",
    max_results: int = 8,
) -> tuple[WiiiConnectActionCandidate, ...]:
    """Rank allowlisted curated actions against a user/task prompt."""

    provider = _provider_slug(provider_slug)
    allowed = _allowed_action_set(action_allowlist)
    preferred = _safe_mutation(preferred_mutation)
    prompt_tokens = _tokens(prompt)
    ranked: list[WiiiConnectActionCandidate] = []
    for action in list_wiii_connect_curated_actions(provider_slug=provider):
        if action.slug not in allowed:
            continue
        score, reasons = _score_action(action, prompt_tokens, preferred)
        ranked.append(
            WiiiConnectActionCandidate(
                slug=action.slug,
                provider_slug=action.provider_slug,
                mutation=action.mutation,
                label=action.label,
                score=score,
                rank_reasons=tuple(reasons),
                requires_preview=action.requires_preview,
                requires_approval=action.requires_approval,
            )
        )
    ranked.sort(key=lambda item: (-item.score, item.provider_slug, item.slug))
    return tuple(ranked[:max(1, max_results)])


def enabled_action_slugs_for_providers(
    *,
    provider_slugs: Iterable[str],
    action_allowlists_by_provider: dict[str, Iterable[str]],
) -> tuple[str, ...]:
    """Return sorted allowlisted action slugs for a provider allowlist."""

    allowed: set[str] = set()
    for provider in {_provider_slug(value) for value in provider_slugs}:
        if not provider:
            continue
        allowed.update(_allowed_action_set(action_allowlists_by_provider.get(provider, ())))
    return tuple(sorted(allowed))


def _score_action(
    action: WiiiConnectCuratedAction,
    prompt_tokens: frozenset[str],
    preferred_mutation: ActionMutation,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if action.mutation == preferred_mutation:
        score += 3
        reasons.append("mutation_match")
    action_tokens = _tokens(action.slug)
    label_tokens = _tokens(action.label)
    description_tokens = _tokens(action.description)
    name_hits = prompt_tokens & action_tokens
    label_hits = prompt_tokens & label_tokens
    description_hits = prompt_tokens & description_tokens
    if name_hits:
        score += 4 * len(name_hits)
        reasons.append("action_name_overlap")
    if label_hits:
        score += 2 * len(label_hits)
        reasons.append("label_overlap")
    if description_hits:
        score += len(description_hits)
        reasons.append("description_overlap")
    prompt_mutations = _prompt_mutations(prompt_tokens)
    if action.mutation in prompt_mutations:
        score += 5
        reasons.append("verb_match")
    elif prompt_mutations and action.mutation not in prompt_mutations:
        score -= 2
        reasons.append("verb_mismatch")
    return score, reasons


def _prompt_mutations(tokens: frozenset[str]) -> set[ActionMutation]:
    detected: set[ActionMutation] = set()
    for mutation, aliases in _MUTATION_ALIASES.items():
        if tokens.intersection(aliases):
            detected.add(mutation)
    return detected


def _tokens(value: Any) -> frozenset[str]:
    normalized = _ascii_fold(str(value or "")).lower().replace("_", " ")
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if token and token not in _STOPWORDS
    )


def _ascii_fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _allowed_action_set(values: Iterable[str]) -> frozenset[str]:
    return frozenset(_action_slug(value) for value in values if _action_slug(value))


def _provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_mutation(value: Any) -> ActionMutation:
    mutation = str(value or "").strip().lower()
    if mutation in _SAFE_MUTATIONS:
        return mutation  # type: ignore[return-value]
    return "read"


__all__ = [
    "WIII_CONNECT_ACTION_POLICY_VERSION",
    "WiiiConnectActionCandidate",
    "WiiiConnectActionPolicyDecision",
    "enabled_action_slugs_for_providers",
    "rank_wiii_connect_action_candidates",
    "select_wiii_connect_action",
]
