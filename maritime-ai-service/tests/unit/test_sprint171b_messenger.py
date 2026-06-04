"""
Tests for Sprint 171b: CallMeBot Messenger Integration + Local LLM Optimization.

Sprint 171b: "Tin Nhắn Tự Chủ" — Wiii can notify user via Facebook Messenger
when it discovers something interesting during autonomous browsing.

Updated for plugin architecture — tests use MessengerAdapter directly.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest


# =============================================================================
# Helper
# =============================================================================

def _make_settings(**overrides):
    """Create a mock settings object with defaults."""
    defaults = {
        "living_agent_callmebot_api_key": "test-api-key-123",
        "living_agent_notification_channel": "messenger",
        "enable_websocket": True,
        "telegram_bot_token": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


_SETTINGS_PATCH = "app.core.config.settings"


# =============================================================================
# MessengerAdapter Tests
# =============================================================================

class TestMessengerNotification:
    """Tests for MessengerAdapter.send()."""

    @pytest.mark.asyncio
    async def test_messenger_sends_via_callmebot(self):
        """Should send GET request to CallMeBot API."""
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):

            result = await adapter.send("user-1", "Hello Wiii!")

            assert result.delivered is True
            assert result.channel == "messenger"
            assert "CallMeBot" in result.detail
            mock_client.get.assert_called_once()
            call_url = mock_client.get.call_args[0][0]
            parsed_url = urlparse(call_url)
            query = parse_qs(parsed_url.query)
            assert parsed_url.scheme == "https"
            assert parsed_url.netloc == "api.callmebot.com"
            assert query["apikey"] == ["test-api-key-123"]

    @pytest.mark.asyncio
    async def test_messenger_fails_without_api_key(self):
        """Should fail gracefully when no API key configured."""
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings(living_agent_callmebot_api_key=None)

        with patch(_SETTINGS_PATCH, settings):
            result = await adapter.send("user-1", "Hello")

            assert result.delivered is False
            assert "not configured" in result.detail

    @pytest.mark.asyncio
    async def test_messenger_handles_api_error(self):
        """Should handle non-200 responses gracefully."""
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):

            result = await adapter.send("user-1", "Hello")

            assert result.delivered is False
            assert "429" in result.detail

    @pytest.mark.asyncio
    async def test_messenger_api_error_omits_provider_body_secrets(self):
        """Provider body is diagnostic-only and must not enter result detail."""
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = (
            "apikey=test-api-key-123 text=private-message user_id=user-1"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):

            result = await adapter.send("user-1", "private-message")

            assert result.delivered is False
            assert result.detail == "CallMeBot API error: 429"
            assert "test-api-key-123" not in result.detail
            assert "private-message" not in result.detail
            assert "user-1" not in result.detail

    @pytest.mark.asyncio
    async def test_messenger_handles_network_error(self):
        """Should handle network exceptions gracefully."""
        import httpx
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings()

        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("Connection timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):

            result = await adapter.send("user-1", "Hello")

            assert result.delivered is False

    @pytest.mark.asyncio
    async def test_messenger_parses_json_payload(self):
        """Should extract content from JSON message payload."""
        import json
        from app.services.notifications.adapters.messenger import MessengerAdapter

        adapter = MessengerAdapter()
        settings = _make_settings()

        payload = json.dumps({"content": "Wiii found something!", "type": "discovery"})

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):

            result = await adapter.send("user-1", payload)

            assert result.delivered is True
            call_url = mock_client.get.call_args[0][0]
            assert "Wiii+found+something" in call_url or "Wiii%20found%20something" in call_url


class TestDispatcherRouting:
    """Tests for notify_user() channel routing via registry."""

    @pytest.mark.asyncio
    async def test_routes_to_messenger(self):
        """notify_user(channel='messenger') should route to MessengerAdapter."""
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.base import NotificationResult
        from app.services.notifications.registry import NotificationChannelRegistry

        dispatcher = NotificationDispatcher()
        dispatcher._registry = NotificationChannelRegistry()

        mock_adapter = MagicMock()
        mock_adapter.get_config.return_value = MagicMock(id="messenger", enabled=True)
        mock_adapter.send = AsyncMock(return_value=NotificationResult(
            delivered=True, channel="messenger", detail="ok"
        ))
        dispatcher._registry.register(mock_adapter)

        result = await dispatcher.notify_user("u1", "test", channel="messenger")

        assert result["channel"] == "messenger"
        assert result["delivered"] is True
        mock_adapter.send.assert_called_once_with("u1", "test", None)

    @pytest.mark.asyncio
    async def test_routes_unknown_channel(self):
        """Unknown channel should return not-delivered."""
        from app.services.notification_dispatcher import NotificationDispatcher
        from app.services.notifications.registry import NotificationChannelRegistry

        dispatcher = NotificationDispatcher()
        dispatcher._registry = NotificationChannelRegistry()

        result = await dispatcher.notify_user("u1", "test", channel="pigeon")

        assert result["delivered"] is False
        assert "Unknown" in result["detail"]


# =============================================================================
# Heartbeat Discovery Notification Tests
# =============================================================================

class TestHeartbeatNotification:
    """Tests for _notify_discovery() in HeartbeatScheduler."""

    @pytest.mark.asyncio
    async def test_notify_discovery_sends_message(self):
        """Should format and send discovery notification."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_notification_channel="messenger",
            enable_websocket=True,
        )

        mock_item = MagicMock()
        mock_item.title = "IMO SOLAS Chapter III Update"
        mock_item.url = "https://imo.org/news/solas"
        mock_item.relevance_score = 0.85

        mock_dispatcher = AsyncMock()
        mock_dispatcher.notify_user.return_value = {"delivered": True}

        with patch(_SETTINGS_PATCH, settings), \
             patch(
                 "app.services.notification_dispatcher.get_notification_dispatcher",
                 return_value=mock_dispatcher,
             ):

            await scheduler._notify_discovery([mock_item], "maritime")

            mock_dispatcher.notify_user.assert_called_once()
            call_args = mock_dispatcher.notify_user.call_args
            assert call_args.kwargs["channel"] == "messenger"
            message = call_args.kwargs["message"]
            assert "IMO SOLAS" in message
            assert "maritime" in message

    @pytest.mark.asyncio
    async def test_notify_discovery_skips_when_ws_disabled(self):
        """Should skip WS notification when websocket is disabled."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_notification_channel="websocket",
            enable_websocket=False,
        )

        with patch(_SETTINGS_PATCH, settings):
            # Should not raise, just return silently
            await scheduler._notify_discovery([MagicMock()], "news")

    @pytest.mark.asyncio
    async def test_notify_discovery_handles_error(self):
        """Should catch exceptions without propagating."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler

        scheduler = HeartbeatScheduler()
        settings = _make_settings()

        with patch(_SETTINGS_PATCH, settings), \
             patch(
                 "app.services.notification_dispatcher.get_notification_dispatcher",
                 side_effect=RuntimeError("Import failed"),
             ):
            # Should not raise
            await scheduler._notify_discovery([MagicMock()], "tech")


# =============================================================================
# Local LLM Think Optimization Tests
# =============================================================================

class TestLocalLLMThinkParam:
    """Tests for think parameter in LocalLLMClient."""

    @pytest.mark.asyncio
    async def test_generate_default_think_true(self):
        """Default generate() should use think=True."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(model="qwen3:4b", base_url="http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Generated text"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.generate("Hello")

            assert result == "Generated text"
            payload = mock_http.post.call_args.kwargs["json"]
            assert payload["think"] is True
            # With think=True, num_predict should be 3x max_tokens
            assert payload["options"]["num_predict"] == 2048 * 3

    @pytest.mark.asyncio
    async def test_generate_think_false(self):
        """generate(think=False) should set think=False and reduce num_predict."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(model="qwen3:4b", base_url="http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "0.75"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.generate("Rate this", think=False, max_tokens=10)

            assert result == "0.75"
            payload = mock_http.post.call_args.kwargs["json"]
            assert payload["think"] is False
            # With think=False, num_predict = max_tokens (no multiplier)
            assert payload["options"]["num_predict"] == 10

    @pytest.mark.asyncio
    async def test_generate_qwen3_instruct_forces_think_false(self):
        """Explicit Qwen3 instruct tags should not receive think=True."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(
            model="qwen3:4b-instruct-2507-q4_K_M",
            base_url="http://localhost:11434",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Generated text"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.generate("Hello")

            assert result == "Generated text"
            payload = mock_http.post.call_args.kwargs["json"]
            assert payload["think"] is False
            assert payload["options"]["num_predict"] == 2048


    @pytest.mark.asyncio
    async def test_rate_relevance_uses_think_false(self):
        """rate_relevance() should use think=False for speed."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(model="qwen3:4b", base_url="http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "0.85"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            score = await client.rate_relevance("IMO SOLAS update", ["maritime"])

            assert score == 0.85
            payload = mock_http.post.call_args.kwargs["json"]
            assert payload["think"] is False

    @pytest.mark.asyncio
    async def test_generate_json_default_think_false(self):
        """generate_json() should default to think=False."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(model="qwen3:4b", base_url="http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": '{"key": "value"}'}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.generate_json("Extract JSON from this")

            assert result == {"key": "value"}
            payload = mock_http.post.call_args.kwargs["json"]
            assert payload["think"] is False

    @pytest.mark.asyncio
    async def test_generate_includes_keep_alive_when_configured(self):
        """Configured keep_alive should be forwarded to Ollama API."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Generated text"}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.config.settings") as mock_settings:
            mock_settings.living_agent_local_model = "qwen3:4b-instruct-2507-q4_K_M"
            mock_settings.ollama_base_url = "http://localhost:11434"
            mock_settings.ollama_keep_alive = "30m"
            client = LocalLLMClient()

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.generate("Hello", think=False)

        assert result == "Generated text"
        payload = mock_http.post.call_args.kwargs["json"]
        assert payload["keep_alive"] == "30m"

    @pytest.mark.asyncio
    async def test_summarize_uses_think_true(self):
        """summarize() should use think=True for quality."""
        from app.engine.living_agent.local_llm import LocalLLMClient

        client = LocalLLMClient(model="qwen3:4b", base_url="http://localhost:11434")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Đây là bản tóm tắt."}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post.return_value = mock_response
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            result = await client.summarize("A" * 100)

            assert "tóm tắt" in result
            payload = mock_http.post.call_args.kwargs["json"]
            # summarize calls generate() with default think=True
            assert payload["think"] is True


# =============================================================================
# Config Tests
# =============================================================================

class TestCallMeBotConfig:
    """Tests for CallMeBot config fields."""

    def test_callmebot_config_defaults(self):
        """CallMeBot fields should have safe defaults."""
        from app.core.config import LivingAgentConfig

        config = LivingAgentConfig()
        assert config.callmebot_api_key is None
        assert config.notification_channel == "websocket"

    def test_callmebot_config_custom(self):
        """CallMeBot fields should accept custom values."""
        from app.core.config import LivingAgentConfig

        config = LivingAgentConfig(
            callmebot_api_key="my-key-123",
            notification_channel="messenger",
        )
        assert config.callmebot_api_key == "my-key-123"
        assert config.notification_channel == "messenger"
