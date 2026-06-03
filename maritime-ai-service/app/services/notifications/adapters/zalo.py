"""
Zalo Official Account Notification Adapter

Sprint 172: Zalo OA integration for notification delivery.

Sends notifications via Zalo Official Account API v3.0.
Endpoint: POST https://openapi.zalo.me/v3.0/oa/message/cs
Auth: access_token header

Reference:
- https://developers.zalo.me/docs/api/official-account-api-230
- https://github.com/nh4ttruong/zalo-oa-api-wrapper
- OpenClaw extensions/zalo channel plugin pattern

Setup:
1. Create Zalo OA at https://oa.zalo.me
2. Register app at https://developers.zalo.me
3. Get access_token via OAuth flow
4. Set env: ZALO_OA_ACCESS_TOKEN, ZALO_OA_APP_ID, etc.
"""

import json
import logging
from typing import Optional

from app.services.notifications.base import (
    ChannelConfig,
    NotificationChannelAdapter,
    NotificationResult,
)
from app.services.notifications.privacy import (
    notification_recipient_ref,
    sanitize_notification_detail,
)

logger = logging.getLogger(__name__)

# Zalo OA API v3.0 endpoint
_ZALO_OA_API_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"


class ZaloAdapter(NotificationChannelAdapter):
    """Delivers notifications via Zalo Official Account API v3.

    Uses the consultation message endpoint to send text messages
    to users who have interacted with the OA.

    Required config:
    - zalo_oa_access_token: OAuth access token for the OA
    - enable_zalo: feature flag
    """

    def get_config(self) -> ChannelConfig:
        return ChannelConfig(
            id="zalo",
            display_name="Zalo OA",
            enabled=True,
            requires_config=True,
        )

    def validate_config(self) -> bool:
        from app.core.config import settings
        return bool(
            settings.enable_zalo
            and settings.zalo_oa_access_token
        )

    async def send(
        self,
        user_id: str,
        message: str,
        metadata: Optional[dict] = None,
    ) -> NotificationResult:
        recipient_ref = notification_recipient_ref(user_id)
        access_token = ""
        try:
            from app.core.config import settings

            access_token = settings.zalo_oa_access_token or ""
            if not access_token:
                return NotificationResult(
                    delivered=False,
                    channel="zalo",
                    detail="Zalo OA access token not configured",
                )

            # Parse JSON payload → extract text content
            try:
                payload = json.loads(message)
                text = (
                    payload.get("content")
                    or payload.get("description", message)
                )
            except (json.JSONDecodeError, TypeError):
                text = message

            # Truncate to Zalo's message limit (2000 chars)
            text = text[:2000]

            import httpx

            headers = {
                "Content-Type": "application/json",
                "access_token": access_token,
            }
            body = {
                "recipient": {
                    "user_id": user_id,
                },
                "message": {
                    "text": text,
                },
            }

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    _ZALO_OA_API_URL,
                    headers=headers,
                    json=body,
                )

            # Zalo returns {"error": 0, "message": "Success"}
            # on success, or {"error": <code>, "message": "..."}
            resp_data = response.json()
            error_code = resp_data.get("error", -1)

            if response.status_code == 200 and error_code == 0:
                logger.info(
                    "[NOTIFY] Zalo OA message sent recipient_ref=%s",
                    recipient_ref,
                )
                return NotificationResult(
                    delivered=True,
                    channel="zalo",
                    detail="Sent via Zalo OA API v3",
                )
            else:
                err_msg = resp_data.get("message", "Unknown")
                safe_err_msg = sanitize_notification_detail(
                    err_msg,
                    access_token,
                    user_id,
                )
                detail = (
                    f"Zalo API error {error_code}: {safe_err_msg}"
                )
                logger.warning(
                    "[NOTIFY] %s recipient_ref=%s",
                    detail,
                    recipient_ref,
                )
                return NotificationResult(
                    delivered=False, channel="zalo",
                    detail=detail,
                )

        except Exception as e:
            safe_detail = sanitize_notification_detail(
                e,
                access_token,
                user_id,
                message,
            )
            logger.error(
                "[NOTIFY] Zalo notification failed recipient_ref=%s: %s",
                recipient_ref,
                safe_detail,
            )
            return NotificationResult(
                delivered=False,
                channel="zalo",
                detail=safe_detail,
            )
