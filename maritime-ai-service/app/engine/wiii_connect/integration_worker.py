"""Provider-scoped Wiii Connect integration worker contract.

This module is Wiii's backend analogue of OpenHuman's integrations_agent gate:
the main chat delegate supplies a provider and task, then the worker validates
provider scope, resolves the curated action, and returns a privacy-safe plan.
Execution still happens through the backend action executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any, Iterable, Literal, Mapping

from .action_catalog import action_catalog_public_metadata
from .argument_key_policy import (
    model_visible_argument_keys,
    normalize_argument_key,
    safe_public_argument_key,
)
from .action_policy import (
    WiiiConnectActionPolicyDecision,
    select_wiii_connect_action,
)
from .adapter_v1 import ActionMutation
from .composio_adapter import (
    WiiiConnectComposioAdapterConfig,
    build_composio_execution_enabled_entry,
)
from .provider_registry import get_wiii_connect_provider_entry


WIII_CONNECT_INTEGRATION_WORKER_VERSION = "wiii_connect_integration_worker.v1"

IntegrationWorkerStatus = Literal["ready", "blocked"]
IntegrationWorkerReason = Literal[
    "ready",
    "missing_provider_slug",
    "provider_not_agent_ready",
    "unknown_wiii_connect_provider",
    "selected_explicit_action",
    "selected_single_read_action",
    "missing_provider_slug_policy",
    "unknown_curated_action",
    "action_not_allowlisted",
    "no_enabled_actions",
    "explicit_action_required_for_mutation",
    "ambiguous_action_selection",
]
IntegrationWorkerOutcome = Literal[
    "completed",
    "blocked",
    "failed",
    "requested",
    "validation_required",
    "approval_required",
    "preview_required",
    "unknown",
]
WorkerArgumentSource = Literal["none", "caller_provided", "backend_prompt_mapper"]


@dataclass(frozen=True, slots=True)
class WiiiConnectIntegrationWorkerPlan:
    """Privacy-safe worker plan for one provider-scoped delegate call."""

    version: str
    status: IntegrationWorkerStatus
    reason: IntegrationWorkerReason
    provider_slug: str = ""
    requested_provider_slug: str = ""
    allowed_provider_slugs: tuple[str, ...] = ()
    prompt_present: bool = False
    requested_action_slug: str = ""
    requested_mutation: ActionMutation = "read"
    action_slug: str = ""
    selected_mutation: ActionMutation = "read"
    action_allowlist: tuple[str, ...] = ()
    action_policy: WiiiConnectActionPolicyDecision | None = None
    stage_sequence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.status == "ready" and bool(self.action_slug)

    def to_public_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "executor": "provider_worker",
            "provider_slug": self.provider_slug,
            "requested_provider_slug": self.requested_provider_slug,
            "allowed_provider_slugs": list(self.allowed_provider_slugs),
            "prompt_present": self.prompt_present,
            "requested_action_slug": self.requested_action_slug,
            "requested_mutation": self.requested_mutation,
            "action_slug": self.action_slug,
            "selected_mutation": self.selected_mutation,
            "action_allowlist": list(self.action_allowlist),
            "stage_sequence": list(self.stage_sequence),
        }
        if self.action_policy is not None:
            metadata["action_policy"] = self.action_policy.to_public_metadata()
        return metadata


@dataclass(frozen=True, slots=True)
class WiiiConnectWorkerArgumentPlan:
    """Provider arguments selected behind the worker boundary.

    The values are sent only to the backend executor; public metadata exposes
    source and key names, never raw prompt text or provider payload values.
    """

    source: WorkerArgumentSource
    reason: str
    arguments: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def argument_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(safe_public_argument_key(key) for key in self.arguments if key)
        )

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_INTEGRATION_WORKER_VERSION,
            "source": self.source,
            "reason": _safe_surface(self.reason),
            "argument_keys": list(self.argument_keys),
            "argument_count": len(self.argument_keys),
        }


def plan_wiii_connect_integration_worker(
    *,
    provider_slug: str = "",
    prompt: str = "",
    action_slug: str = "",
    mutation: str = "read",
    allowed_provider_slugs: Iterable[str] = (),
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None = None,
    composio_config: WiiiConnectComposioAdapterConfig,
) -> WiiiConnectIntegrationWorkerPlan:
    """Validate a delegate call and select one curated provider action."""

    allowed_providers = _normalize_provider_allowlist(tuple(allowed_provider_slugs))
    provider = _provider_slug(provider_slug)
    if not provider and len(allowed_providers) == 1:
        provider = allowed_providers[0]
    requested_action = _action_slug(action_slug)
    requested_mutation = _safe_mutation(mutation)
    prompt_present = bool(str(prompt or "").strip())
    base = {
        "requested_provider_slug": _provider_slug(provider_slug),
        "allowed_provider_slugs": allowed_providers,
        "prompt_present": prompt_present,
        "requested_action_slug": requested_action,
        "requested_mutation": requested_mutation,
    }

    if not provider:
        return _blocked(
            "missing_provider_slug",
            stage_sequence=("provider_gate", "blocked"),
            **base,
        )
    if allowed_providers and provider not in allowed_providers:
        return _blocked(
            "provider_not_agent_ready",
            provider_slug=provider,
            stage_sequence=("provider_gate", "blocked"),
            **base,
        )

    entry = get_wiii_connect_provider_entry(provider)
    if entry is None:
        return _blocked(
            "unknown_wiii_connect_provider",
            provider_slug=provider,
            stage_sequence=("provider_gate", "blocked"),
            **base,
        )

    effective_entry = build_composio_execution_enabled_entry(entry, composio_config)
    action_allowlist = _action_allowlist_for_provider(
        effective_entry.slug,
        allowed_action_slugs_by_provider=allowed_action_slugs_by_provider,
        fallback=effective_entry.action_allowlist,
    )
    action_policy = select_wiii_connect_action(
        provider_slug=effective_entry.slug,
        action_slug=requested_action,
        mutation=requested_mutation,
        action_allowlist=action_allowlist,
        prompt=prompt,
    )
    if not action_policy.selected or action_policy.selected_action is None:
        return _blocked(
            _policy_reason(action_policy.reason),
            provider_slug=effective_entry.slug,
            action_slug=action_policy.action_slug,
            action_allowlist=action_allowlist,
            action_policy=action_policy,
            stage_sequence=("provider_gate", "action_policy", "blocked"),
            **base,
        )

    return WiiiConnectIntegrationWorkerPlan(
        version=WIII_CONNECT_INTEGRATION_WORKER_VERSION,
        status="ready",
        reason=_policy_reason(action_policy.reason),
        provider_slug=effective_entry.slug,
        action_slug=action_policy.action_slug,
        selected_mutation=action_policy.selected_action.mutation,
        action_allowlist=action_allowlist,
        action_policy=action_policy,
        stage_sequence=("provider_gate", "action_policy", "ready"),
        **base,
    )


def build_wiii_connect_worker_arguments(
    *,
    plan: WiiiConnectIntegrationWorkerPlan,
    prompt: str = "",
    provided_arguments: Mapping[str, Any] | None = None,
) -> WiiiConnectWorkerArgumentPlan:
    """Resolve provider arguments without giving the main model raw control."""

    caller_arguments = _safe_arguments(provided_arguments, plan=plan)
    if caller_arguments:
        return WiiiConnectWorkerArgumentPlan(
            source="caller_provided",
            reason="internal_arguments_provided",
            arguments=caller_arguments,
        )
    if not plan.ready:
        return WiiiConnectWorkerArgumentPlan(
            source="none",
            reason="worker_plan_not_ready",
        )
    if plan.action_slug == "GMAIL_FETCH_EMAILS":
        arguments = _gmail_fetch_email_arguments(prompt)
        return WiiiConnectWorkerArgumentPlan(
            source="backend_prompt_mapper" if arguments else "none",
            reason="gmail_fetch_email_prompt_mapper"
            if arguments
            else "missing_supported_gmail_query",
            arguments=arguments,
        )
    if plan.action_slug == "FACEBOOK_LIST_MANAGED_PAGES":
        return WiiiConnectWorkerArgumentPlan(
            source="backend_prompt_mapper",
            reason="facebook_pages_default_read_arguments",
            arguments={"fields": "id,name", "limit": 25},
        )
    return WiiiConnectWorkerArgumentPlan(
        source="none",
        reason="unsupported_worker_argument_mapper",
    )


def worker_block_payload(
    plan: WiiiConnectIntegrationWorkerPlan,
) -> dict[str, Any]:
    """Return sanitized data for a blocked worker result envelope."""

    data: dict[str, Any] = {
        "integration_worker": plan.to_public_metadata(),
        "action_catalog": action_catalog_public_metadata(
            provider_slug=plan.provider_slug,
            enabled_slugs=plan.action_allowlist,
        )
        if plan.provider_slug
        else None,
    }
    if plan.action_policy is not None:
        data["action_policy"] = plan.action_policy.to_public_metadata()
    return data


def classify_wiii_connect_integration_worker_result(
    payload: Mapping[str, Any],
    *,
    plan: WiiiConnectIntegrationWorkerPlan,
) -> dict[str, Any]:
    """Classify worker output for UI/logs without exposing provider payloads."""

    status = str(payload.get("status") or "").strip()
    success = payload.get("success")
    reason = str(payload.get("error") or payload.get("reason") or "").strip()
    if plan.status == "blocked":
        return _classification(
            outcome="blocked",
            status=status or "action_failed",
            reason=reason or plan.reason,
            failed_stage=_failed_stage_for_blocked_plan(plan),
            plan=plan,
        )
    if status == "action_completed" or success is True:
        return _classification(
            outcome="completed",
            status=status or "action_completed",
            reason=reason or "completed",
            failed_stage="",
            plan=plan,
        )
    if status == "action_requested":
        return _classification(
            outcome="requested",
            status=status,
            reason=reason or "action_requested",
            failed_stage="",
            plan=plan,
        )
    if status == "validation_failed":
        return _classification(
            outcome="validation_required",
            status=status,
            reason=reason or "validation_failed",
            failed_stage="argument_validation",
            plan=plan,
        )
    if status == "approval_required":
        return _classification(
            outcome="approval_required",
            status=status,
            reason=reason or "approval_required",
            failed_stage="approval",
            plan=plan,
        )
    if status == "preview_required":
        return _classification(
            outcome="preview_required",
            status=status,
            reason=reason or "preview_required",
            failed_stage="preview",
            plan=plan,
        )
    if status == "action_failed" or success is False:
        return _classification(
            outcome="failed",
            status=status or "action_failed",
            reason=reason or "action_failed",
            failed_stage=_failed_stage_for_payload(payload),
            plan=plan,
        )
    return _classification(
        outcome="unknown",
        status=status or "unknown",
        reason=reason or "unknown",
        failed_stage="unknown",
        plan=plan,
    )


def _blocked(
    reason: IntegrationWorkerReason,
    *,
    requested_provider_slug: str = "",
    provider_slug: str = "",
    allowed_provider_slugs: tuple[str, ...] = (),
    prompt_present: bool = False,
    requested_action_slug: str = "",
    requested_mutation: ActionMutation = "read",
    action_slug: str = "",
    action_allowlist: tuple[str, ...] = (),
    action_policy: WiiiConnectActionPolicyDecision | None = None,
    stage_sequence: tuple[str, ...] = ("blocked",),
) -> WiiiConnectIntegrationWorkerPlan:
    return WiiiConnectIntegrationWorkerPlan(
        version=WIII_CONNECT_INTEGRATION_WORKER_VERSION,
        status="blocked",
        reason=reason,
        provider_slug=provider_slug,
        requested_provider_slug=requested_provider_slug,
        allowed_provider_slugs=allowed_provider_slugs,
        prompt_present=prompt_present,
        requested_action_slug=requested_action_slug,
        requested_mutation=requested_mutation,
        action_slug=action_slug,
        selected_mutation=requested_mutation,
        action_allowlist=action_allowlist,
        action_policy=action_policy,
        stage_sequence=stage_sequence,
    )


def _classification(
    *,
    outcome: IntegrationWorkerOutcome,
    status: str,
    reason: str,
    failed_stage: str,
    plan: WiiiConnectIntegrationWorkerPlan,
) -> dict[str, Any]:
    return {
        "version": WIII_CONNECT_INTEGRATION_WORKER_VERSION,
        "outcome": outcome,
        "status": _safe_surface(status),
        "reason": _safe_surface(reason),
        "failed_stage": _safe_surface(failed_stage) if failed_stage else "",
        "provider_slug": plan.provider_slug,
        "action_slug": plan.action_slug,
        "plan_status": plan.status,
        "plan_reason": plan.reason,
    }


def _failed_stage_for_blocked_plan(plan: WiiiConnectIntegrationWorkerPlan) -> str:
    sequence = tuple(item for item in plan.stage_sequence if item and item != "blocked")
    return sequence[-1] if sequence else "provider_gate"


def _failed_stage_for_payload(payload: Mapping[str, Any]) -> str:
    error = str(payload.get("error") or "").strip().lower()
    if error in {"missing_required_arguments", "invalid_argument"}:
        return "argument_validation"
    gateway = payload.get("gateway")
    if isinstance(gateway, Mapping):
        status = str(gateway.get("status") or "").strip().lower()
        reason = str(gateway.get("reason") or "").strip().lower()
        if status == "blocked" or reason:
            return "gateway"
    schema = payload.get("schema")
    if isinstance(schema, Mapping):
        ready = schema.get("ready")
        if ready is False:
            return "schema"
    execution = payload.get("execution")
    if isinstance(execution, Mapping):
        status = str(execution.get("status") or "").strip().lower()
        if status and status not in {"succeeded", "success"}:
            return "execute"
    return "execute"


def _gmail_fetch_email_arguments(prompt: str) -> dict[str, Any]:
    query = _extract_explicit_gmail_query(prompt)
    tokens = _tokens(prompt)
    if not query and ("teacher" in tokens or {"giao", "vien"}.issubset(tokens)):
        query = "from:teacher"
    if not query and ("unread" in tokens or {"chua", "doc"}.issubset(tokens)):
        query = "is:unread"
    if not query:
        return {}
    return {
        "query": query,
        "max_results": _extract_small_limit(prompt) or 3,
    }


def _extract_explicit_gmail_query(prompt: str) -> str:
    text = str(prompt or "").strip()
    match = re.search(
        r"\b(?:from|to|subject|label|older_than|newer_than|after|before):[^\s,;]{1,96}",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(0)[:120] if match else ""


def _extract_small_limit(prompt: str) -> int | None:
    match = re.search(r"\b([1-9]|10)\b", str(prompt or ""))
    if not match:
        return None
    return int(match.group(1))


def _tokens(value: Any) -> frozenset[str]:
    normalized = _ascii_fold(str(value or "")).lower().replace("_", " ")
    return frozenset(re.findall(r"[a-z0-9]+", normalized))


def _ascii_fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _safe_arguments(
    values: Mapping[str, Any] | None,
    *,
    plan: WiiiConnectIntegrationWorkerPlan,
) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    allowed_keys = set(
        model_visible_argument_keys(
            provider_slug=plan.provider_slug,
            action_slug=plan.action_slug,
            argument_keys=values.keys(),
        )
    )
    result: dict[str, Any] = {}
    for key, value in values.items():
        safe_key = _safe_argument_key(key)
        if safe_key and safe_key in allowed_keys:
            result[safe_key] = value
    return result


def _safe_argument_key(value: Any) -> str:
    return normalize_argument_key(value)[:80]


def _action_allowlist_for_provider(
    provider_slug: str,
    *,
    allowed_action_slugs_by_provider: Mapping[str, Iterable[str]] | None,
    fallback: Iterable[str],
) -> tuple[str, ...]:
    scoped = _normalize_action_allowlists_by_provider(allowed_action_slugs_by_provider)
    return scoped.get(_provider_slug(provider_slug)) or _normalize_action_allowlist(tuple(fallback))


def _normalize_action_allowlists_by_provider(
    values: Mapping[str, Iterable[str]] | None,
) -> dict[str, tuple[str, ...]]:
    if not isinstance(values, Mapping):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for provider, actions in values.items():
        provider_slug = _provider_slug(provider)
        action_slugs = _normalize_action_allowlist(tuple(actions or ()))
        if provider_slug and action_slugs:
            result[provider_slug] = action_slugs
    return result


def _normalize_provider_allowlist(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or ():
        slug = _provider_slug(value)
        if slug and slug not in normalized:
            normalized.append(slug)
    return tuple(normalized)


def _normalize_action_allowlist(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or ():
        slug = _action_slug(value)
        if slug and slug not in normalized:
            normalized.append(slug)
    return tuple(normalized)


def _provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_mutation(value: Any) -> ActionMutation:
    mutation = str(value or "").strip().lower()
    if mutation in {"read", "preview", "write", "apply", "admin"}:
        return mutation  # type: ignore[return-value]
    return "read"


def _policy_reason(value: Any) -> IntegrationWorkerReason:
    reason = str(value or "").strip()
    if reason == "missing_provider_slug":
        return "missing_provider_slug_policy"
    if reason in {
        "selected_explicit_action",
        "selected_single_read_action",
        "unknown_curated_action",
        "action_not_allowlisted",
        "no_enabled_actions",
        "explicit_action_required_for_mutation",
        "ambiguous_action_selection",
    }:
        return reason  # type: ignore[return-value]
    return "ready"


def _safe_surface(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return text[:80] or "unknown"


__all__ = [
    "WIII_CONNECT_INTEGRATION_WORKER_VERSION",
    "WiiiConnectIntegrationWorkerPlan",
    "classify_wiii_connect_integration_worker_result",
    "plan_wiii_connect_integration_worker",
    "worker_block_payload",
]
