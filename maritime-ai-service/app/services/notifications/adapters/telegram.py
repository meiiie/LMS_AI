"""
Telegram Notification Adapter

Sprint 171b: Extracted from NotificationDispatcher._notify_telegram()
Sends notifications via Telegram Bot API.
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


class TelegramAdapter(NotificationChannelAdapter):
    """Delivers notifications via Telegram Bot API."""

    def get_config(self) -> ChannelConfig:
        return ChannelConfig(
            id="telegram",
            display_name="Telegram Bot",
            enabled=True,
            requires_config=True,
        )

    def validate_config(self) -> bool:
        from app.core.config import settings
        return bool(settings.telegram_bot_token)

    async def send(
        self,
        user_id: str,
        message: str,
        metadata: Optional[dict] = None,
    ) -> NotificationResult:
        recipient_ref = notification_recipient_ref(user_id)
        bot_token = ""
        try:
            from app.core.config import settings

            bot_token = settings.telegram_bot_token or ""
            if not bot_token:
                return NotificationResult(
                    delivered=False,
                    channel="telegram",
                    detail="Telegram bot token not configured",
                )

            # Parse message if it's a JSON payload, extract content for Telegram
            try:
                payload = json.loads(message)
                text = payload.get("content") or payload.get("description", message)
            except (json.JSONDecodeError, TypeError):
                text = message

            import httpx

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": user_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )

            if response.status_code == 200:
                logger.info(
                    "[NOTIFY] Telegram notification sent recipient_ref=%s",
                    recipient_ref,
                )
                return NotificationResult(
                    delivered=True,
                    channel="telegram",
                    detail="Sent via Telegram Bot API",
                )
            else:
                detail = f"Telegram API error: {response.status_code}"
                logger.warning("[NOTIFY] %s", detail)
                return NotificationResult(
                    delivered=False, channel="telegram",
                    detail=detail,
                )

        except Exception as e:
            safe_detail = sanitize_notification_detail(e, bot_token, user_id, message)
            logger.error(
                "[NOTIFY] Telegram failed recipient_ref=%s: %s",
                recipient_ref,
                safe_detail,
            )
            return NotificationResult(
                delivered=False,
                channel="telegram",
                detail=safe_detail,
            )
