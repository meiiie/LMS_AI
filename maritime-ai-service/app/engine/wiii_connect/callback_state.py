"""Signed callback state for Wiii Connect provider handoffs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


WIII_CONNECT_CALLBACK_STATE_VERSION = "wiii_connect_callback_state.v1"
WIII_CONNECT_CALLBACK_STATE_PARAM = "wiii_state"
_MAX_STATE_AGE_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class WiiiConnectCallbackStateClaims:
    """Verified Wiii-owned callback state claims."""

    valid: bool = False
    reason: str = "missing_state"
    provider_slug: str = ""
    organization_id: str = ""
    user_id: str = ""
    issued_at: int = 0

    def to_audit_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_CALLBACK_STATE_VERSION,
            "valid": self.valid,
            "reason": self.reason,
            "provider_slug": self.provider_slug,
            "organization_id_present": bool(self.organization_id),
            "user_id_present": bool(self.user_id),
            "issued_at_present": bool(self.issued_at),
        }


def build_wiii_connect_callback_state(
    *,
    provider_slug: str,
    organization_id: str,
    user_id: str,
    secret_key: str,
    issued_at: int | None = None,
    nonce: str | None = None,
) -> str:
    """Build a signed, URL-safe state value for provider callbacks."""

    secret = str(secret_key or "").encode("utf-8")
    if not secret:
        return ""
    payload = {
        "v": 1,
        "p": _normalize_slug(provider_slug),
        "o": str(organization_id or "").strip(),
        "u": str(user_id or "").strip(),
        "iat": int(issued_at if issued_at is not None else time.time()),
        "n": nonce or secrets.token_urlsafe(16),
    }
    if not payload["p"] or not payload["u"]:
        return ""
    payload_b64 = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature}"


def verify_wiii_connect_callback_state(
    state: str | None,
    *,
    provider_slug: str,
    secret_key: str,
    now: int | None = None,
    max_age_seconds: int = _MAX_STATE_AGE_SECONDS,
) -> WiiiConnectCallbackStateClaims:
    """Verify callback state without exposing the raw state value."""

    text = str(state or "").strip()
    if not text:
        return WiiiConnectCallbackStateClaims(reason="missing_state")
    secret = str(secret_key or "").encode("utf-8")
    if not secret:
        return WiiiConnectCallbackStateClaims(reason="state_secret_missing")
    try:
        payload_b64, signature = text.split(".", 1)
    except ValueError:
        return WiiiConnectCallbackStateClaims(reason="invalid_state_format")
    expected = _sign(payload_b64, secret)
    if not hmac.compare_digest(signature, expected):
        return WiiiConnectCallbackStateClaims(reason="invalid_state_signature")
    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return WiiiConnectCallbackStateClaims(reason="invalid_state_payload")

    callback_provider = _normalize_slug(payload.get("p"))
    expected_provider = _normalize_slug(provider_slug)
    if callback_provider != expected_provider:
        return WiiiConnectCallbackStateClaims(
            reason="state_provider_mismatch",
            provider_slug=callback_provider,
        )
    issued_at = _safe_int(payload.get("iat"))
    current_time = int(now if now is not None else time.time())
    if not issued_at or issued_at > current_time + 60:
        return WiiiConnectCallbackStateClaims(
            reason="invalid_state_time",
            provider_slug=callback_provider,
        )
    if current_time - issued_at > max_age_seconds:
        return WiiiConnectCallbackStateClaims(
            reason="state_expired",
            provider_slug=callback_provider,
            issued_at=issued_at,
        )
    user_id = str(payload.get("u") or "").strip()
    if not user_id:
        return WiiiConnectCallbackStateClaims(
            reason="state_user_missing",
            provider_slug=callback_provider,
            issued_at=issued_at,
        )
    return WiiiConnectCallbackStateClaims(
        valid=True,
        reason="valid",
        provider_slug=callback_provider,
        organization_id=str(payload.get("o") or "").strip(),
        user_id=user_id,
        issued_at=issued_at,
    )


def append_wiii_connect_callback_state(
    callback_url: str,
    state: str,
) -> str:
    """Attach Wiii state to a callback URL without dropping existing params."""

    text = str(callback_url or "").strip()
    state_text = str(state or "").strip()
    if not text or not state_text:
        return text
    parts = urlsplit(text)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[WIII_CONNECT_CALLBACK_STATE_PARAM] = state_text
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _sign(payload_b64: str, secret: bytes) -> str:
    digest = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _normalize_slug(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
