"""
Notification Dispatcher — Multi-channel notification routing for Wiii.

Sprint 20: Proactive Agent Activation.
Sprint 171b: Refactored to plugin architecture — delegates to NotificationChannelRegistry.

Routes notifications to users via their preferred channel
(WebSocket, Telegram, Messenger, or any registered plugin).
Used by the scheduled task executor and heartbeat system.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.notifications.privacy import notification_recipient_ref

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """
    Routes notifications to users based on channel preference.

    Delegates to registered NotificationChannelAdapter instances via
    NotificationChannelRegistry (plugin architecture).
    Falls back gracefully when a channel is unavailable.
    """

    def __init__(self):
        self._registry = None

    def _get_registry(self):
        """Lazy-initialize the notification channel registry."""
        if self._registry is None:
            from app.services.notifications import init_notification_channels
            self._registry = init_notification_channels()
        return self._registry

    async def notify_user(
        self,
        user_id: str,
        message: str,
        channel: str = "websocket",
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Dispatch a notification to a user.

        Args:
            user_id: Target user ID
            message: Notification content
            channel: Delivery channel ("websocket", "telegram", "messenger", etc.)
            metadata: Additional metadata to include in the notification

        Returns:
            {"delivered": bool, "channel": str, "detail": str}
        """
        adapter = self._get_registry().get(channel)
        if adapter is None:
            logger.warning(
                "[NOTIFY] Unknown channel '%s' recipient_ref=%s",
                channel,
                notification_recipient_ref(user_id),
            )
            return {
                "delivered": False,
                "channel": channel,
                "detail": f"Unknown channel: {channel}",
            }

        result = await adapter.send(user_id, message, metadata)
        return result.to_dict()

    async def notify_task_result(self, task: dict, result: dict) -> dict:
        """
        Format and send a scheduled task result to its owner.

        Args:
            task: Scheduled task dict from repository
            result: Execution result dict with "mode" and "response"

        Returns:
            Delivery status dict
        """
        user_id = task.get("user_id", "")
        channel = task.get("channel", "websocket")

        payload = json.dumps(
            {
                "type": "scheduled_task",
                "task_id": task.get("id", ""),
                "description": task.get("description", ""),
                "content": result.get("response", ""),
                "mode": result.get("mode", "notification"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )

        return await self.notify_user(
            user_id=user_id,
            message=payload,
            channel=channel,
            metadata={
                "task_id": task.get("id"),
                "organization_id": task.get("organization_id"),
            },
        )


# =============================================================================
# Singleton
# =============================================================================

_dispatcher: Optional[NotificationDispatcher] = None


def get_notification_dispatcher() -> NotificationDispatcher:
    """Get or create the NotificationDispatcher singleton."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NotificationDispatcher()
    return _dispatcher
