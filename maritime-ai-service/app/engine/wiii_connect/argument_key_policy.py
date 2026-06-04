"""Public argument-key projection for Wiii Connect actions.

Provider schemas often contain account selectors, approval controls, media
handles, or secret-like fields. Those keys are backend/runtime-owned even when
the provider names them as ordinary arguments. This module keeps model-facing
catalogs and audit metadata from teaching the main model to author those
controls directly.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION = "wiii_connect_argument_key_policy.v1"

REDACTED_SENSITIVE_ARGUMENT_KEY = "redacted_sensitive_field"
BACKEND_OWNED_ARGUMENT_KEY = "backend_owned_field"

_SENSITIVE_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "key",
    "code",
    "authorization",
)

_BACKEND_OWNED_ARGUMENT_KEYS = frozenset(
    {
        "account_id",
        "account_ref",
        "approval_token",
        "connected_account_id",
        "connection_id",
        "connection_ref",
        "cursor",
        "external_account_ref",
        "file",
        "files",
        "image",
        "image_base64",
        "image_filename",
        "image_media_type",
        "image_url",
        "media",
        "page_access_token",
        "page_id",
        "page_ids",
        "photo",
        "preview_evidence_id",
        "provider_payload",
        "published",
        "raw_prompt",
        "scheduled_publish_time",
        "upload",
        "user_id",
        "vault_key_id",
    }
)

_MODEL_ARGUMENT_KEYS_BY_ACTION = {
    ("gmail", "GMAIL_FETCH_EMAILS"): ("query", "max_results"),
    ("facebook", "FACEBOOK_LIST_MANAGED_PAGES"): ("fields", "limit"),
    ("facebook", "FACEBOOK_CREATE_POST"): ("message", "link"),
    ("facebook", "FACEBOOK_CREATE_PHOTO_POST"): ("message",),
}


def normalize_argument_key(value: Any) -> str:
    """Return the canonical public spelling for an argument key."""

    return str(value or "").strip().lower().replace("-", "_")[:120]


def safe_public_argument_key(value: Any) -> str:
    """Return a public audit/schema key without raw secrets or controls."""

    key = normalize_argument_key(value)
    if not key:
        return "empty"
    if is_sensitive_argument_key(key):
        return REDACTED_SENSITIVE_ARGUMENT_KEY
    if is_backend_owned_argument_key(key):
        return BACKEND_OWNED_ARGUMENT_KEY
    return key[:80]


def safe_public_argument_keys(values: Iterable[Any]) -> tuple[str, ...]:
    """Return de-duplicated safe public keys for audit/schema metadata."""

    return _dedupe(safe_public_argument_key(value) for value in values)


def model_visible_argument_keys(
    *,
    provider_slug: str,
    action_slug: str,
    argument_keys: Iterable[Any],
) -> tuple[str, ...]:
    """Return only argument keys a model may author for a curated action."""

    provider = _provider_slug(provider_slug)
    action = _action_slug(action_slug)
    keys = tuple(normalize_argument_key(value) for value in argument_keys)
    allowlist = _MODEL_ARGUMENT_KEYS_BY_ACTION.get((provider, action))
    if allowlist is not None:
        allowed = set(allowlist)
        return _dedupe(key for key in keys if key in allowed)
    return _dedupe(
        safe_public_argument_key(key)
        for key in keys
        if key and not is_backend_owned_argument_key(key)
    )


def model_visible_arguments(
    *,
    provider_slug: str,
    action_slug: str,
    arguments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return caller arguments that may cross the model/API boundary."""

    if not isinstance(arguments, Mapping):
        return {}
    allowed = set(
        model_visible_argument_keys(
            provider_slug=provider_slug,
            action_slug=action_slug,
            argument_keys=arguments.keys(),
        )
    )
    result: dict[str, Any] = {}
    for key, value in arguments.items():
        normalized = normalize_argument_key(key)
        if normalized and normalized in allowed:
            result[normalized] = value
    return result


def hidden_model_argument_key_count(
    *,
    provider_slug: str,
    action_slug: str,
    argument_keys: Iterable[Any],
) -> int:
    """Count raw provider keys hidden from model-facing catalogs."""

    provider = _provider_slug(provider_slug)
    action = _action_slug(action_slug)
    keys = tuple(key for key in (normalize_argument_key(value) for value in argument_keys) if key)
    allowlist = _MODEL_ARGUMENT_KEYS_BY_ACTION.get((provider, action))
    if allowlist is not None:
        allowed = set(allowlist)
        return sum(1 for key in keys if key not in allowed)
    return sum(
        1
        for key in keys
        if is_backend_owned_argument_key(key) or is_sensitive_argument_key(key)
    )


def is_sensitive_argument_key(value: Any) -> bool:
    key = normalize_argument_key(value)
    return any(marker in key for marker in _SENSITIVE_KEY_MARKERS)


def is_backend_owned_argument_key(value: Any) -> bool:
    key = normalize_argument_key(value)
    return key in _BACKEND_OWNED_ARGUMENT_KEYS


def _provider_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _action_slug(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return tuple(result[:50])


__all__ = [
    "BACKEND_OWNED_ARGUMENT_KEY",
    "REDACTED_SENSITIVE_ARGUMENT_KEY",
    "WIII_CONNECT_ARGUMENT_KEY_POLICY_VERSION",
    "hidden_model_argument_key_count",
    "is_backend_owned_argument_key",
    "is_sensitive_argument_key",
    "model_visible_argument_keys",
    "model_visible_arguments",
    "normalize_argument_key",
    "safe_public_argument_key",
    "safe_public_argument_keys",
]
