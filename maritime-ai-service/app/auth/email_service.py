"""
Sprint 224: Magic Link Email Service — Resend wrapper.

Sends magic link emails using Resend API.
"""
import logging

from app.core.config import settings
from app.core.secret_validation import is_missing_or_placeholder_secret
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    redact_runtime_secret_text,
)

logger = logging.getLogger(__name__)
_MAX_EMAIL_DIAGNOSTIC_LENGTH = 500

try:
    import resend
except ImportError:
    resend = None  # type: ignore


MAGIC_LINK_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px; color: #1a1a1a;">
  <div style="text-align: center; margin-bottom: 32px;">
    <h1 style="font-size: 24px; font-weight: 600; margin: 0;">Đăng nhập Wiii</h1>
  </div>
  <p style="font-size: 16px; line-height: 1.6;">Xin chào,</p>
  <p style="font-size: 16px; line-height: 1.6;">Click nút bên dưới để đăng nhập vào Wiii. Link có hiệu lực trong <strong>10 phút</strong>.</p>
  <div style="text-align: center; margin: 32px 0;">
    <a href="{url}" style="display: inline-block; padding: 14px 32px; background-color: #E8713A; color: white; text-decoration: none; border-radius: 8px; font-size: 16px; font-weight: 600;">
      Đăng nhập Wiii
    </a>
  </div>
  <p style="font-size: 14px; color: #666; line-height: 1.5;">Nếu bạn không yêu cầu đăng nhập, hãy bỏ qua email này.</p>
  <hr style="border: none; border-top: 1px solid #eee; margin: 32px 0;">
  <p style="font-size: 12px; color: #999; text-align: center;">by The Wiii Lab</p>
</body>
</html>
"""


def build_magic_link_html(verify_url: str) -> str:
    """Build HTML email body with magic link button."""
    return MAGIC_LINK_HTML_TEMPLATE.format(url=verify_url)


def _is_resend_configured() -> bool:
    key = getattr(settings, "resend_api_key", "") or ""
    return not is_missing_or_placeholder_secret(key)


def _email_ref(value: object) -> str:
    return hash_runtime_identifier(value) or "sha256:empty"


def _safe_email_detail(value: object, *secret_values: object) -> str:
    text = str(value or "")
    for secret_value in secret_values:
        secret = str(secret_value or "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return redact_runtime_secret_text(text, max_length=_MAX_EMAIL_DIAGNOSTIC_LENGTH)


async def send_magic_link_email(to_email: str, verify_url: str) -> bool:
    """Send magic link email via Resend.

    Dev fallback: when Resend is not configured OR environment != production,
    log the verify URL to stdout so developers can open it manually instead
    of waiting for email delivery.

    Returns True if sent (or logged in dev mode), False on error.
    """
    resend_ready = _is_resend_configured() and resend is not None

    if not resend_ready and getattr(settings, "environment", "") == "production":
        logger.error(
            "Magic Link email blocked in production because Resend is not configured."
        )
        return False

    if not resend_ready:
        # Development-only fallback for missing package or common placeholder
        # secrets such as "your-", "placeholder", "example", and "dummy".
        logger.warning(
            "[DEV MAGIC LINK] Resend not configured for email_ref=%s; "
            "dev verify URL is returned by the request endpoint.",
            _email_ref(to_email),
        )
        return True

    try:
        resend.api_key = settings.resend_api_key
        html = build_magic_link_html(verify_url)
        resend.Emails.send({
            "from": settings.magic_link_from_email,
            "to": to_email,
            "subject": "Đăng nhập Wiii",
            "html": html,
        })
        logger.info("Magic link email sent email_ref=%s", _email_ref(to_email))
        return True
    except Exception as e:
        logger.error(
            "Failed to send magic link email email_ref=%s: %s",
            _email_ref(to_email),
            _safe_email_detail(
                e,
                to_email,
                verify_url,
                getattr(settings, "resend_api_key", ""),
                getattr(settings, "magic_link_from_email", ""),
            ),
        )
        return False
