"""
Tests for NotificationDispatcher — Multi-channel notification routing.

Sprint 20: Proactive Agent Activation.
Sprint 171b: Updated for plugin architecture (adapters + registry).

Verifies:
- WebSocket notification delivery (user online/offline)
- Telegram notification delivery (with/without token)
- Task result formatting
- Unknown channel handling
- Vietnamese message content
"""

import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.notification_dispatcher import (
    NotificationDispatcher,
    get_notification_dispatcher,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def dispatcher():
    """Fresh NotificationDispatcher instance with pre-initialized registry."""
    d = NotificationDispatcher()
    # Pre-populate registry so tests don't trigger lazy init
    from app.services.notifications.registry import NotificationChannelRegistry
    d._registry = NotificationChannelRegistry()
    return d


@pytest.fixture
def sample_task():
    """Sample scheduled task dict."""
    return {
        "id": "task-abc-12345678",
        "user_id": "user-1",
        "domain_id": "maritime",
        "description": "Nhắc ôn tập COLREGs Rule 13",
        "schedule_type": "once",
        "channel": "websocket",
        "extra_data": {},
        "organization_id": "org-1",
    }


@pytest.fixture
def sample_result():
    """Sample execution result."""
    return {
        "mode": "notification",
        "response": "Đã đến giờ ôn tập COLREGs Rule 13 — Overtaking!",
    }


# =============================================================================
# WebSocket notifications (via adapter)
# =============================================================================

class TestWebSocketNotification:

    @pytest.mark.asyncio
    async def test_notify_user_online(self):
        """Delivers notification when user is online."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        mock_manager = MagicMock()
        mock_manager.is_user_online.return_value = True
        mock_manager.send_to_user = AsyncMock(return_value=2)

        with patch("app.api.v1.websocket.manager", mock_manager):
            result = await adapter.send("user-1", "hello")

        assert result.delivered is True
        assert result.channel == "websocket"
        assert "2 sessions" in result.detail
        mock_manager.send_to_user.assert_awaited_once_with(
            "user-1",
            "hello",
            organization_id="",
        )

    @pytest.mark.asyncio
    async def test_notify_user_filters_websocket_by_metadata_org(self):
        """WebSocket notifications carry org scope into session filtering."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        mock_manager = MagicMock()
        mock_manager.is_user_online.return_value = True
        mock_manager.send_to_user = AsyncMock(return_value=1)

        with patch("app.api.v1.websocket.manager", mock_manager):
            result = await adapter.send(
                "user-1",
                "hello",
                metadata={"organization_id": "org-A"},
            )

        assert result.delivered is True
        mock_manager.send_to_user.assert_awaited_once_with(
            "user-1",
            "hello",
            organization_id="org-A",
        )

    @pytest.mark.asyncio
    async def test_notify_user_metadata_org_without_matching_session_not_delivered(self):
        """Online users are not delivered when no session matches the target org."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        mock_manager = MagicMock()
        mock_manager.is_user_online.return_value = True
        mock_manager.send_to_user = AsyncMock(return_value=0)

        with patch("app.api.v1.websocket.manager", mock_manager):
            result = await adapter.send(
                "user-1",
                "hello",
                metadata={"organization_id": "org-A"},
            )

        assert result.delivered is False
        assert result.detail == "No matching WebSocket sessions"

    @pytest.mark.asyncio
    async def test_notify_user_offline(self):
        """Handles offline user gracefully."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        mock_manager = MagicMock()
        mock_manager.is_user_online.return_value = False

        with patch("app.api.v1.websocket.manager", mock_manager):
            result = await adapter.send("user-1", "hello")

        assert result.delivered is False
        assert "offline" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_notify_websocket_exception(self):
        """Handles WebSocket errors gracefully."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        with patch(
            "app.api.v1.websocket.manager",
            side_effect=RuntimeError("Connection pool full"),
        ):
            result = await adapter.send("user-1", "hello")

        assert result.delivered is False
        assert result.channel == "websocket"

    @pytest.mark.asyncio
    async def test_notify_websocket_exception_redacts_detail(self):
        """WebSocket exception diagnostics must not expose user or message."""
        from app.services.notifications.adapters.websocket import WebSocketAdapter

        adapter = WebSocketAdapter()
        mock_manager = MagicMock()
        mock_manager.is_user_online.return_value = True
        mock_manager.send_to_user = AsyncMock(
            side_effect=RuntimeError(
                "failed for user-secret with access_token=raw-ws-token "
                "message=private-message"
            )
        )

        with patch("app.api.v1.websocket.manager", mock_manager):
            result = await adapter.send("user-secret", "private-message")

        assert result.delivered is False
        assert result.channel == "websocket"
        assert "user-secret" not in result.detail
        assert "raw-ws-token" not in result.detail
        assert "private-message" not in result.detail

    @pytest.mark.asyncio
    async def test_notify_user_via_channel_websocket(self, dispatcher):
        """notify_user routes to WebSocket adapter correctly."""
        from app.services.notifications.base import NotificationResult

        mock_adapter = MagicMock()
        mock_adapter.get_config.return_value = MagicMock(id="websocket", enabled=True)
        mock_adapter.send = AsyncMock(return_value=NotificationResult(
            delivered=True, channel="websocket", detail="ok"
        ))
        dispatcher._registry.register(mock_adapter)

        result = await dispatcher.notify_user("user-1", "test", channel="websocket")

        assert result["delivered"] is True
        mock_adapter.send.assert_called_once()


# =============================================================================
# Telegram notifications (via adapter)
# =============================================================================

class TestTelegramNotification:

    @pytest.mark.asyncio
    async def test_notify_telegram_no_token(self):
        """Returns not delivered when bot token is not configured."""
        from app.services.notifications.adapters.telegram import TelegramAdapter

        adapter = TelegramAdapter()
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = None

        with patch("app.core.config.settings", mock_settings):
            result = await adapter.send("user-1", "test")

        assert result.delivered is False
        assert "not configured" in result.detail

    @pytest.mark.asyncio
    async def test_notify_telegram_success(self):
        """Delivers via Telegram Bot API successfully."""
        from app.services.notifications.adapters.telegram import TelegramAdapter

        adapter = TelegramAdapter()
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "bot-token-123"

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.config.settings", mock_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-1", "Hello!")

        assert result.delivered is True
        assert result.channel == "telegram"

    @pytest.mark.asyncio
    async def test_notify_telegram_api_error(self):
        """Handles Telegram API error response."""
        from app.services.notifications.adapters.telegram import TelegramAdapter

        adapter = TelegramAdapter()
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "bot-token-123"

        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.config.settings", mock_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-1", "test")

        assert result.delivered is False
        assert "403" in result.detail

    @pytest.mark.asyncio
    async def test_notify_telegram_exception_redacts_secret_diagnostics(self):
        """Network exception detail must not expose token, recipient, or text."""
        from app.services.notifications.adapters.telegram import TelegramAdapter

        adapter = TelegramAdapter()
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "bot-token-123"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=RuntimeError(
                "failed https://api.telegram.org/botbot-token-123/sendMessage"
                "?chat_id=user-secret&text=private-message"
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.core.config.settings", mock_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-secret", "private-message")

        assert result.delivered is False
        assert "bot-token-123" not in result.detail
        assert "user-secret" not in result.detail
        assert "private-message" not in result.detail

    @pytest.mark.asyncio
    async def test_notify_telegram_json_payload(self):
        """Extracts content from JSON payload for Telegram text."""
        from app.services.notifications.adapters.telegram import TelegramAdapter

        adapter = TelegramAdapter()
        mock_settings = MagicMock()
        mock_settings.telegram_bot_token = "bot-token-123"

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        payload = json.dumps({"content": "Đã đến giờ ôn tập!", "type": "scheduled_task"})

        with patch("app.core.config.settings", mock_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            await adapter.send("user-1", payload)

        call_args = mock_client.post.call_args
        sent_text = call_args[1]["json"]["text"]
        assert sent_text == "Đã đến giờ ôn tập!"

    @pytest.mark.asyncio
    async def test_notify_user_via_channel_telegram(self, dispatcher):
        """notify_user routes to Telegram adapter correctly."""
        from app.services.notifications.base import NotificationResult

        mock_adapter = MagicMock()
        mock_adapter.get_config.return_value = MagicMock(id="telegram", enabled=True)
        mock_adapter.send = AsyncMock(return_value=NotificationResult(
            delivered=True, channel="telegram", detail="ok"
        ))
        dispatcher._registry.register(mock_adapter)

        result = await dispatcher.notify_user("user-1", "test", channel="telegram")

        assert result["delivered"] is True
        mock_adapter.send.assert_called_once()


# =============================================================================
# Unknown channel
# =============================================================================

class TestUnknownChannel:

    @pytest.mark.asyncio
    async def test_unknown_channel(self, dispatcher):
        """Unknown channel returns not delivered."""
        result = await dispatcher.notify_user("user-1", "test", channel="carrier_pigeon")

        assert result["delivered"] is False
        assert "Unknown channel" in result["detail"]

    @pytest.mark.asyncio
    async def test_unknown_channel_log_hashes_recipient(self, dispatcher, caplog):
        """Unknown channel diagnostics must not log the raw recipient."""
        caplog.set_level(logging.WARNING, logger="app.services.notification_dispatcher")

        result = await dispatcher.notify_user(
            "user-secret",
            "private-message",
            channel="discord",
        )

        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert result["delivered"] is False
        assert "Unknown channel: discord" in result["detail"]
        assert "recipient_ref=sha256:" in log_text
        assert "user-secret" not in log_text
        assert "private-message" not in log_text


# =============================================================================
# Task result formatting
# =============================================================================

class TestNotifyTaskResult:

    @pytest.mark.asyncio
    async def test_task_result_format(self, dispatcher, sample_task, sample_result):
        """notify_task_result formats payload correctly."""
        sent_payloads = []

        async def mock_notify(user_id, message, channel="websocket", metadata=None):
            sent_payloads.append(json.loads(message))
            return {"delivered": True, "channel": channel, "detail": "ok"}

        dispatcher.notify_user = mock_notify

        await dispatcher.notify_task_result(sample_task, sample_result)

        assert len(sent_payloads) == 1
        payload = sent_payloads[0]
        assert payload["type"] == "scheduled_task"
        assert payload["task_id"] == "task-abc-12345678"
        assert payload["description"] == "Nhắc ôn tập COLREGs Rule 13"
        assert payload["content"] == sample_result["response"]
        assert payload["mode"] == "notification"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_task_result_metadata_includes_org_scope(
        self,
        dispatcher,
        sample_task,
        sample_result,
    ):
        """Task result delivery passes org scope to channel adapters."""
        sent_metadata = []

        async def mock_notify(user_id, message, channel="websocket", metadata=None):
            sent_metadata.append(metadata)
            return {"delivered": True, "channel": channel, "detail": "ok"}

        dispatcher.notify_user = mock_notify
        await dispatcher.notify_task_result(sample_task, sample_result)

        assert sent_metadata == [
            {
                "task_id": "task-abc-12345678",
                "organization_id": "org-1",
            }
        ]

    @pytest.mark.asyncio
    async def test_task_result_uses_task_channel(self, dispatcher, sample_task, sample_result):
        """notify_task_result uses the task's channel preference."""
        sample_task["channel"] = "telegram"
        calls = []

        async def mock_notify(user_id, message, channel="websocket", metadata=None):
            calls.append(channel)
            return {"delivered": True, "channel": channel, "detail": "ok"}

        dispatcher.notify_user = mock_notify
        await dispatcher.notify_task_result(sample_task, sample_result)

        assert calls[0] == "telegram"

    @pytest.mark.asyncio
    async def test_task_result_vietnamese_content(self, dispatcher):
        """Vietnamese content is preserved (ensure_ascii=False)."""
        task = {"id": "t1", "user_id": "u1", "description": "Ôn tập Luật Giao thông", "channel": "websocket"}
        result = {"mode": "agent", "response": "Theo Điều 12 Luật GTĐB..."}
        sent = []

        async def mock_notify(user_id, message, channel="websocket", metadata=None):
            sent.append(message)
            return {"delivered": True, "channel": channel, "detail": "ok"}

        dispatcher.notify_user = mock_notify
        await dispatcher.notify_task_result(task, result)

        payload = json.loads(sent[0])
        assert "Ôn tập" in payload["description"]
        assert "Điều 12" in payload["content"]


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    def test_get_notification_dispatcher_singleton(self):
        """Singleton returns same instance."""
        import app.services.notification_dispatcher as mod
        mod._dispatcher = None  # Reset

        d1 = get_notification_dispatcher()
        d2 = get_notification_dispatcher()
        assert d1 is d2

        mod._dispatcher = None  # Clean up
