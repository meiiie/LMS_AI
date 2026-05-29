"""Preview and approval-token helpers for Facebook posting.

The token proves that the apply request matches a preview Wiii already showed
to the user. It is not a provider token and must never be logged as a value.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any


WIII_CONNECT_FACEBOOK_POST_PREVIEW_VERSION = "wiii_connect_facebook_post_preview.v1"
FACEBOOK_POST_APPROVAL_TOKEN_MAX_AGE_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class FacebookPostApprovalTokenCheck:
    """Result of verifying a Facebook post approval token."""

    valid: bool
    reason: str = "valid"
    preview_evidence_id: str = ""

    def to_public_metadata(self) -> dict[str, Any]:
        return {
            "version": WIII_CONNECT_FACEBOOK_POST_PREVIEW_VERSION,
            "valid": self.valid,
            "reason": _safe_reason(self.reason),
            "preview_evidence_id_present": bool(self.preview_evidence_id),
        }


def normalize_facebook_post_message(value: Any) -> str:
    """Normalize user-visible post text without inventing content."""

    text = " ".join(str(value or "").strip().split())
    return text[:5000]


def normalize_facebook_image_media_type(value: Any) -> str:
    media_type = str(value or "").strip().lower()
    if media_type in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return media_type
    return ""


def normalize_facebook_image_filename(value: Any, *, media_type: str) -> str:
    text = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(media_type, ".img")
    if not text:
        return f"wiii-facebook-post{suffix}"
    if any(marker in text.lower() for marker in ("token", "secret", "password", "key")):
        return f"wiii-facebook-post{suffix}"
    allowed = []
    for char in text[:120]:
        if char.isalnum() or char in {" ", ".", "_", "-"}:
            allowed.append(char)
    safe = "".join(allowed).strip(" .")
    if not safe:
        return f"wiii-facebook-post{suffix}"
    if "." not in safe:
        safe = f"{safe}{suffix}"
    return safe


def normalize_facebook_page_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    allowed = []
    for char in text[:120]:
        if char.isalnum() or char in {"_", "-", ":"}:
            allowed.append(char)
    return "".join(allowed)


def normalize_facebook_image_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith("https://"):
        return ""
    if any(marker in text.lower() for marker in ("token", "secret", "password", "key")):
        return ""
    return text[:2000]


def facebook_image_sha256(image_bytes: bytes) -> str:
    if not image_bytes:
        return ""
    return hashlib.sha256(image_bytes).hexdigest()


def build_facebook_post_preview_evidence_id(
    *,
    provider_slug: str,
    action_slug: str,
    connection_ref: str,
    page_id: str,
    message: str,
    image_sha256: str = "",
    image_url: str = "",
) -> str:
    payload = {
        "provider_slug": _safe_provider(provider_slug),
        "action_slug": _safe_action(action_slug),
        "connection_ref": _safe_connection_ref(connection_ref),
        "page_id": normalize_facebook_page_id(page_id),
        "message_hash": _sha256_text(message),
        "image_hash": _safe_hash(image_sha256),
        "image_url_hash": _sha256_text(normalize_facebook_image_url(image_url)),
    }
    digest = _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return f"wcp_{digest[:32]}"


def build_facebook_post_approval_token(
    *,
    provider_slug: str,
    action_slug: str,
    connection_ref: str,
    page_id: str,
    message: str,
    secret_key: str,
    image_sha256: str = "",
    image_url: str = "",
    issued_at: int | None = None,
) -> str:
    issued = int(issued_at if issued_at is not None else time.time())
    preview_id = build_facebook_post_preview_evidence_id(
        provider_slug=provider_slug,
        action_slug=action_slug,
        connection_ref=connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_sha256,
        image_url=image_url,
    )
    payload = {
        "v": WIII_CONNECT_FACEBOOK_POST_PREVIEW_VERSION,
        "provider_slug": _safe_provider(provider_slug),
        "action_slug": _safe_action(action_slug),
        "connection_ref": _safe_connection_ref(connection_ref),
        "page_id": normalize_facebook_page_id(page_id),
        "message_hash": _sha256_text(message),
        "image_hash": _safe_hash(image_sha256),
        "image_url_hash": _sha256_text(normalize_facebook_image_url(image_url)),
        "preview_evidence_id": preview_id,
        "iat": issued,
        "nonce": secrets.token_urlsafe(16),
    }
    encoded = _b64_json(payload)
    signature = _signature(encoded, secret_key)
    return f"{encoded}.{signature}"


def verify_facebook_post_approval_token(
    token: str,
    *,
    provider_slug: str,
    action_slug: str,
    connection_ref: str,
    page_id: str,
    message: str,
    secret_key: str,
    preview_evidence_id: str = "",
    image_sha256: str = "",
    image_url: str = "",
    now: int | None = None,
    max_age_seconds: int = FACEBOOK_POST_APPROVAL_TOKEN_MAX_AGE_SECONDS,
) -> FacebookPostApprovalTokenCheck:
    text = str(token or "").strip()
    if "." not in text:
        return FacebookPostApprovalTokenCheck(valid=False, reason="missing_token")
    encoded, signature = text.rsplit(".", 1)
    expected = _signature(encoded, secret_key)
    if not hmac.compare_digest(signature, expected):
        return FacebookPostApprovalTokenCheck(valid=False, reason="invalid_signature")
    try:
        payload = _unb64_json(encoded)
    except ValueError:
        return FacebookPostApprovalTokenCheck(valid=False, reason="invalid_payload")
    issued_at = int(payload.get("iat") or 0)
    current = int(now if now is not None else time.time())
    if issued_at <= 0 or current - issued_at > max_age_seconds:
        return FacebookPostApprovalTokenCheck(valid=False, reason="token_expired")
    expected_preview_id = build_facebook_post_preview_evidence_id(
        provider_slug=provider_slug,
        action_slug=action_slug,
        connection_ref=connection_ref,
        page_id=page_id,
        message=message,
        image_sha256=image_sha256,
        image_url=image_url,
    )
    checks = {
        "v": WIII_CONNECT_FACEBOOK_POST_PREVIEW_VERSION,
        "provider_slug": _safe_provider(provider_slug),
        "action_slug": _safe_action(action_slug),
        "connection_ref": _safe_connection_ref(connection_ref),
        "page_id": normalize_facebook_page_id(page_id),
        "message_hash": _sha256_text(message),
        "image_hash": _safe_hash(image_sha256),
        "image_url_hash": _sha256_text(normalize_facebook_image_url(image_url)),
        "preview_evidence_id": expected_preview_id,
    }
    for key, expected_value in checks.items():
        if str(payload.get(key) or "") != str(expected_value):
            return FacebookPostApprovalTokenCheck(
                valid=False,
                reason="preview_mismatch",
                preview_evidence_id=str(payload.get("preview_evidence_id") or ""),
            )
    if preview_evidence_id and preview_evidence_id != expected_preview_id:
        return FacebookPostApprovalTokenCheck(
            valid=False,
            reason="preview_mismatch",
            preview_evidence_id=expected_preview_id,
        )
    return FacebookPostApprovalTokenCheck(
        valid=True,
        reason="valid",
        preview_evidence_id=expected_preview_id,
    )


def _b64_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64_json(value: str) -> dict[str, Any]:
    padded = value + "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid_payload")
    return data


def _signature(encoded_payload: str, secret_key: str) -> str:
    digest = hmac.new(
        str(secret_key or "").encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _safe_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 64 and all(char in "0123456789abcdef" for char in text):
        return text
    return ""


def _safe_provider(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")[:80]


def _safe_action(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_")[:120]


def _safe_connection_ref(value: Any) -> str:
    text = str(value or "").strip()
    return text[:180] if text.startswith("wcn_") else ""


def _safe_reason(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    allowed = {
        "valid",
        "missing_token",
        "invalid_signature",
        "invalid_payload",
        "token_expired",
        "preview_mismatch",
    }
    return text if text in allowed else "invalid_payload"


__all__ = [
    "FACEBOOK_POST_APPROVAL_TOKEN_MAX_AGE_SECONDS",
    "WIII_CONNECT_FACEBOOK_POST_PREVIEW_VERSION",
    "FacebookPostApprovalTokenCheck",
    "build_facebook_post_approval_token",
    "build_facebook_post_preview_evidence_id",
    "facebook_image_sha256",
    "normalize_facebook_image_filename",
    "normalize_facebook_image_media_type",
    "normalize_facebook_image_url",
    "normalize_facebook_page_id",
    "normalize_facebook_post_message",
    "verify_facebook_post_approval_token",
]
