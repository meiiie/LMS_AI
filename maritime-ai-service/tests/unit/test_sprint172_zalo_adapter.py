"""
Tests for Sprint 172: Zalo OA Notification Adapter

Verifies:
- ZaloAdapter config and validate_config
- send() success with Zalo API v3 response format
- send() failure handling (no token, API errors, network errors)
- JSON payload parsing
- Message truncation (2000 char limit)
- Init function registration with enable_zalo flag
- Config fields in Settings
- Dispatcher integration routing
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


_SETTINGS_PATCH = "app.core.config.settings"


def _make_settings(**overrides):
    """Create mock settings with Zalo defaults."""
    defaults = {
        "enable_zalo": True,
        "zalo_oa_access_token": "test-zalo-token-abc",
        "zalo_oa_refresh_token": "test-refresh-token",
        "zalo_oa_app_id": "app-123",
        "zalo_oa_secret_key": "secret-456",
        "enable_websocket": False,
        "enable_telegram": False,
        "telegram_bot_token": None,
        "living_agent_callmebot_api_key": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# =============================================================================
# ZaloAdapter Config Tests
# =============================================================================

class TestZaloAdapterConfig:
    """Tests for ZaloAdapter.get_config() and validate_config()."""

    def test_config_values(self):
        from app.services.notifications.adapters.zalo import ZaloAdapter
        cfg = ZaloAdapter().get_config()
        assert cfg.id == "zalo"
        assert cfg.display_name == "Zalo OA"
        assert cfg.enabled is True
        assert cfg.requires_config is True

    def test_validate_config_with_token(self):
        from app.services.notifications.adapters.zalo import ZaloAdapter
        settings = _make_settings()
        with patch(_SETTINGS_PATCH, settings):
            assert ZaloAdapter().validate_config() is True

    def test_validate_config_without_token(self):
        from app.services.notifications.adapters.zalo import ZaloAdapter
        settings = _make_settings(zalo_oa_access_token=None)
        with patch(_SETTINGS_PATCH, settings):
            assert ZaloAdapter().validate_config() is False

    def test_validate_config_disabled(self):
        from app.services.notifications.adapters.zalo import ZaloAdapter
        settings = _make_settings(enable_zalo=False)
        with patch(_SETTINGS_PATCH, settings):
            assert ZaloAdapter().validate_config() is False


# =============================================================================
# ZaloAdapter Send Tests
# =============================================================================

class TestZaloAdapterSend:
    """Tests for ZaloAdapter.send()."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Should POST to Zalo OA API v3 and return success."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": 0,
            "message": "Success",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-zalo-1", "Xin chao!")

        assert result.delivered is True
        assert result.channel == "zalo"
        assert "Zalo OA" in result.detail

        # Verify API call
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url = call_args[0][0]
        assert "openapi.zalo.me" in url
        assert "v3.0/oa/message/cs" in url

        # Verify headers
        headers = call_args[1]["headers"]
        assert headers["access_token"] == "test-zalo-token-abc"
        assert headers["Content-Type"] == "application/json"

        # Verify body
        body = call_args[1]["json"]
        assert body["recipient"]["user_id"] == "user-zalo-1"
        assert body["message"]["text"] == "Xin chao!"

    @pytest.mark.asyncio
    async def test_send_no_access_token(self):
        """Should return failure when no access token."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings(zalo_oa_access_token=None)

        with patch(_SETTINGS_PATCH, settings):
            result = await adapter.send("user-1", "Hello")

        assert result.delivered is False
        assert "not configured" in result.detail

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        """Should handle Zalo API error response."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": -216,
            "message": "Access token is invalid",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-1", "Hello")

        assert result.delivered is False
        assert "-216" in result.detail
        assert "invalid" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_send_api_error_redacts_provider_secret_and_recipient(self):
        """Provider error message must not expose token or raw recipient."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": -216,
            "message": (
                "invalid access_token=test-zalo-token-abc user_id=user-secret"
            ),
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-secret", "Hello")

        assert result.delivered is False
        assert "invalid" in result.detail
        assert "test-zalo-token-abc" not in result.detail
        assert "user-secret" not in result.detail

    @pytest.mark.asyncio
    async def test_send_http_error(self):
        """Should handle HTTP non-200 with error body."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": -1,
            "message": "Rate limited",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-1", "Hello")

        assert result.delivered is False

    @pytest.mark.asyncio
    async def test_send_network_error(self):
        """Should handle network exceptions."""
        import httpx
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException(
            "Connection timeout",
        )
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("user-1", "Hello")

        assert result.delivered is False
        assert result.channel == "zalo"

    @pytest.mark.asyncio
    async def test_send_parses_json_payload(self):
        """Should extract content from JSON message payload."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        payload = json.dumps({
            "content": "Wiii phat hien bai viet moi!",
            "type": "discovery",
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": 0, "message": "Success",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("u1", payload)

        assert result.delivered is True
        body = mock_client.post.call_args[1]["json"]
        assert body["message"]["text"] == "Wiii phat hien bai viet moi!"

    @pytest.mark.asyncio
    async def test_send_truncates_long_message(self):
        """Should truncate messages to 2000 characters."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        long_msg = "A" * 3000

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": 0, "message": "Success",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("u1", long_msg)

        assert result.delivered is True
        body = mock_client.post.call_args[1]["json"]
        assert len(body["message"]["text"]) == 2000

    @pytest.mark.asyncio
    async def test_send_vietnamese_content(self):
        """Should handle Vietnamese content correctly."""
        from app.services.notifications.adapters.zalo import (
            ZaloAdapter,
        )

        adapter = ZaloAdapter()
        settings = _make_settings()

        vn_msg = "Theo Điều 12 Luật GTĐB, tàu phải nhường đường"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error": 0, "message": "Success",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(
            return_value=mock_client,
        )
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(_SETTINGS_PATCH, settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await adapter.send("u1", vn_msg)

        assert result.delivered is True
        body = mock_client.post.call_args[1]["json"]
        assert "Điều 12" in body["message"]["text"]


# =============================================================================
# Init Function Tests — Zalo Registration
# =============================================================================

class TestInitZaloRegistration:
    """Tests for Zalo adapter in init_notification_channels()."""

    def test_zalo_registered_when_enabled(self):
        """Zalo adapter registered when flag + token set."""
        settings = _make_settings(
            enable_zalo=True,
            zalo_oa_access_token="token-123",
        )

        import app.services.notifications.registry as reg_mod
        old = reg_mod._registry_instance
        reg_mod._registry_instance = None

        try:
            with patch(_SETTINGS_PATCH, settings):
                from app.services.notifications import (
                    init_notification_channels,
                )
                registry = init_notification_channels()

            assert "zalo" in registry.list_ids()
        finally:
            reg_mod._registry_instance = old

    def test_zalo_not_registered_when_disabled(self):
        """Zalo adapter NOT registered when flag is False."""
        settings = _make_settings(
            enable_zalo=False,
            zalo_oa_access_token="token-123",
        )

        import app.services.notifications.registry as reg_mod
        old = reg_mod._registry_instance
        reg_mod._registry_instance = None

        try:
            with patch(_SETTINGS_PATCH, settings):
                from app.services.notifications import (
                    init_notification_channels,
                )
                registry = init_notification_channels()

            assert "zalo" not in registry.list_ids()
        finally:
            reg_mod._registry_instance = old

    def test_zalo_not_registered_without_token(self):
        """Zalo adapter NOT registered when no access token."""
        settings = _make_settings(
            enable_zalo=True,
            zalo_oa_access_token=None,
        )

        import app.services.notifications.registry as reg_mod
        old = reg_mod._registry_instance
        reg_mod._registry_instance = None

        try:
            with patch(_SETTINGS_PATCH, settings):
                from app.services.notifications import (
                    init_notification_channels,
                )
                registry = init_notification_channels()

            assert "zalo" not in registry.list_ids()
        finally:
            reg_mod._registry_instance = old

    def test_all_4_channels_registered(self):
        """All 4 channels registered when all enabled."""
        settings = _make_settings(
            enable_websocket=True,
            enable_telegram=True,
            telegram_bot_token="bot-123",
            living_agent_callmebot_api_key="cm-key",
            enable_zalo=True,
            zalo_oa_access_token="zalo-token",
        )

        import app.services.notifications.registry as reg_mod
        old = reg_mod._registry_instance
        reg_mod._registry_instance = None

        try:
            with patch(_SETTINGS_PATCH, settings):
                from app.services.notifications import (
                    init_notification_channels,
                )
                registry = init_notification_channels()

            ids = registry.list_ids()
            assert len(registry) == 4
            assert "websocket" in ids
            assert "telegram" in ids
            assert "messenger" in ids
            assert "zalo" in ids
        finally:
            reg_mod._registry_instance = old


# =============================================================================
# Config Fields Tests
# =============================================================================

class TestZaloConfigFields:
    """Tests for Zalo config fields in Settings."""

    def test_zalo_fields_exist_with_defaults(self):
        """Zalo config fields should have safe defaults."""
        from app.core.config import Settings

        # Check field defaults exist
        fields = Settings.model_fields
        assert "enable_zalo" in fields
        assert "zalo_oa_access_token" in fields
        assert "zalo_oa_refresh_token" in fields
        assert "zalo_oa_app_id" in fields
        assert "zalo_oa_secret_key" in fields

    def test_zalo_defaults_are_safe(self):
        """Default values should be disabled/None."""
        from app.core.config import Settings
        fields = Settings.model_fields
        assert fields["enable_zalo"].default is False
        assert fields["zalo_oa_access_token"].default is None


# =============================================================================
# Dispatcher Integration
# =============================================================================

class TestDispatcherZaloRouting:
    """Tests for dispatcher routing to Zalo adapter."""

    @pytest.mark.asyncio
    async def test_routes_to_zalo(self):
        """notify_user(channel='zalo') routes to ZaloAdapter."""
        from app.services.notification_dispatcher import (
            NotificationDispatcher,
        )
        from app.services.notifications.base import (
            NotificationResult,
        )
        from app.services.notifications.registry import (
            NotificationChannelRegistry,
        )

        dispatcher = NotificationDispatcher()
        dispatcher._registry = NotificationChannelRegistry()

        mock_adapter = MagicMock()
        mock_adapter.get_config.return_value = MagicMock(
            id="zalo", enabled=True,
        )
        mock_adapter.send = AsyncMock(
            return_value=NotificationResult(
                delivered=True, channel="zalo",
                detail="ok",
            ),
        )
        dispatcher._registry.register(mock_adapter)

        result = await dispatcher.notify_user(
            "u1", "test", channel="zalo",
        )

        assert result["delivered"] is True
        assert result["channel"] == "zalo"
        mock_adapter.send.assert_called_once_with(
            "u1", "test", None,
        )
