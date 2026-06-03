"""
Channel Sender — Shared Messenger + Zalo Send API for Wiii.

Sprint 188: "Linh Hồn Thức Tỉnh"

DRY helper used by:
- proactive_messenger.py (autonomous outreach)
- messenger_webhook.py (reply to incoming)
- zalo_webhook.py (reply to incoming)
- briefing_composer.py (scheduled briefings)

Design:
    - Configurable Graph API version via settings.facebook_graph_api_version
    - Structured delivery result with error details
    - Logs delivery to wiii_proactive_messages table (fire-and-forget)
    - Emits PROACTIVE_MESSAGE life event on proactive sends
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.engine.semantic_memory.privacy import hash_memory_identifier

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    """Result of a channel message delivery attempt."""
    success: bool = False
    channel: str = ""
    recipient_id: str = ""
    error: Optional[str] = None
    status_code: Optional[int] = None


async def send_messenger_message(recipient_id: str, text: str) -> DeliveryResult:
    """Send a text message via Facebook Messenger Graph API.

    Args:
        recipient_id: Facebook PSID (page-scoped user ID).
        text: Message text (truncated to 2000 chars per Meta limit).

    Returns:
        DeliveryResult with success/error details.
    """
    import httpx
    from app.core.config import settings

    token = settings.facebook_page_access_token
    if not token:
        return DeliveryResult(
            channel="messenger",
            recipient_id=recipient_id,
            error="facebook_page_access_token not configured",
        )

    api_version = getattr(settings, "facebook_graph_api_version", "v22.0")
    url = f"https://graph.facebook.com/{api_version}/me/messages"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                params={"access_token": token},
                json={
                    "recipient": {"id": recipient_id},
                    "message": {"text": text[:2000]},
                    "messaging_type": "RESPONSE",
                },
            )

        if resp.status_code == 200:
            logger.info(
                "[CHANNEL] Messenger reply sent to recipient_hash=%s",
                hash_memory_identifier(recipient_id),
            )
            return DeliveryResult(
                success=True,
                channel="messenger",
                recipient_id=recipient_id,
                status_code=200,
            )
        else:
            error_msg = resp.text[:300]
            logger.error(
                "[CHANNEL] Messenger send error %s: %s",
                resp.status_code,
                error_msg,
            )
            return DeliveryResult(
                channel="messenger",
                recipient_id=recipient_id,
                error=error_msg,
                status_code=resp.status_code,
            )
    except Exception as e:
        logger.error("[CHANNEL] Messenger send exception: %s", e)
        return DeliveryResult(
            channel="messenger",
            recipient_id=recipient_id,
            error=str(e),
        )


async def send_zalo_message(recipient_id: str, text: str) -> DeliveryResult:
    """Send a text message via Zalo OA API v3.

    Args:
        recipient_id: Zalo user ID.
        text: Message text (truncated to 2000 chars per Zalo limit).

    Returns:
        DeliveryResult with success/error details.
    """
    import httpx
    from app.core.config import settings

    token = settings.zalo_oa_access_token
    if not token:
        return DeliveryResult(
            channel="zalo",
            recipient_id=recipient_id,
            error="zalo_oa_access_token not configured",
        )

    url = "https://openapi.zalo.me/v3.0/oa/message/cs"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "access_token": token,
                },
                json={
                    "recipient": {"user_id": recipient_id},
                    "message": {"text": text[:2000]},
                },
            )

        if resp.status_code == 200:
            resp_data = resp.json()
            if resp_data.get("error") != 0:
                error_msg = str(resp_data)[:300]
                logger.error("[CHANNEL] Zalo API error: %s", error_msg)
                return DeliveryResult(
                    channel="zalo",
                    recipient_id=recipient_id,
                    error=error_msg,
                    status_code=resp.status_code,
                )
            logger.info(
                "[CHANNEL] Zalo reply sent to recipient_hash=%s",
                hash_memory_identifier(recipient_id),
            )
            return DeliveryResult(
                success=True,
                channel="zalo",
                recipient_id=recipient_id,
                status_code=200,
            )
        else:
            error_msg = resp.text[:300]
            logger.error(
                "[CHANNEL] Zalo send error %s: %s",
                resp.status_code,
                error_msg,
            )
            return DeliveryResult(
                channel="zalo",
                recipient_id=recipient_id,
                error=error_msg,
                status_code=resp.status_code,
            )
    except Exception as e:
        logger.error("[CHANNEL] Zalo send exception: %s", e)
        return DeliveryResult(
            channel="zalo",
            recipient_id=recipient_id,
            error=str(e),
        )


async def send_to_channel(
    channel: str,
    recipient_id: str,
    text: str,
) -> DeliveryResult:
    """Route message to the appropriate channel sender.

    Args:
        channel: "messenger" or "zalo".
        recipient_id: Platform-specific user ID.
        text: Message text.

    Returns:
        DeliveryResult.
    """
    if channel == "messenger":
        return await send_messenger_message(recipient_id, text)
    elif channel == "zalo":
        return await send_zalo_message(recipient_id, text)
    else:
        return DeliveryResult(
            channel=channel,
            recipient_id=recipient_id,
            error=f"Unsupported channel: {channel}",
        )
