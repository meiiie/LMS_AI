"""
WebSocket Notification Adapter

Sprint 171b: Extracted from NotificationDispatcher._notify_websocket()
Sends notifications to connected user sessions via WebSocket ConnectionManager.
"""

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


class WebSocketAdapter(NotificationChannelAdapter):
    """Delivers notifications via WebSocket to all active user sessions."""

    def get_config(self) -> ChannelConfig:
        return ChannelConfig(
            id="websocket",
            display_name="WebSocket",
            enabled=True,
            requires_config=False,
        )

    async def send(
        self,
        user_id: str,
        message: str,
        metadata: Optional[dict] = None,
    ) -> NotificationResult:
        recipient_ref = notification_recipient_ref(user_id)
        try:
            from app.api.v1.websocket import manager

            if not manager.is_user_online(user_id):
                logger.info(
                    "[NOTIFY] recipient_ref=%s offline, WS queued",
                    recipient_ref,
                )
                return NotificationResult(
                    delivered=False,
                    channel="websocket",
                    detail="User offline",
                )

            organization_id = ""
            if isinstance(metadata, dict):
                raw_org_id = metadata.get("organization_id") or metadata.get("org_id")
                if isinstance(raw_org_id, str):
                    organization_id = raw_org_id.strip()

            sent = await manager.send_to_user(
                user_id,
                message,
                organization_id=organization_id,
            )
            logger.info(
                "[NOTIFY] WS sent recipient_ref=%s (%d sessions)",
                recipient_ref, sent,
            )
            if sent <= 0:
                return NotificationResult(
                    delivered=False,
                    channel="websocket",
                    detail="No matching WebSocket sessions",
                )
            return NotificationResult(
                delivered=True,
                channel="websocket",
                detail=f"Sent to {sent} sessions",
            )

        except Exception as e:
            safe_detail = sanitize_notification_detail(e, user_id, message)
            logger.error(
                "[NOTIFY] WS notification failed recipient_ref=%s: %s",
                recipient_ref,
                safe_detail,
            )
            return NotificationResult(
                delivered=False,
                channel="websocket",
                detail=safe_detail,
            )
