"""
Tests for WebSocket endpoint and WebSocketAdapter.

Sprint 12: Multi-Channel Gateway.
Tests WebSocket message parsing, response formatting, heartbeat, connection manager.
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.channels.websocket_adapter import WebSocketAdapter
from app.channels.base import ChannelMessage
from app.api.v1.websocket import (
    ConnectionManager,
    _resolve_ws_auth_identity,
    _resolve_ws_connection_org_id,
    _resolve_ws_message_org_id,
)


# ============================================================================
# WebSocketAdapter Tests
# ============================================================================


class TestWebSocketAdapter:
    """Test WebSocket channel adapter."""

    def setup_method(self):
        self.adapter = WebSocketAdapter()

    def test_channel_type(self):
        assert self.adapter.channel_type == "websocket"

    # --- parse_incoming ---

    def test_parse_json_string(self):
        raw = json.dumps({
            "type": "message",
            "content": "Hello Wiii",
            "sender_id": "user-1",
        })
        msg = self.adapter.parse_incoming(raw)
        assert msg.text == "Hello Wiii"
        assert msg.sender_id == "user-1"
        assert msg.channel_type == "websocket"

    def test_parse_dict(self):
        raw = {
            "type": "message",
            "content": "Hello",
            "sender_id": "user-2",
        }
        msg = self.adapter.parse_incoming(raw)
        assert msg.text == "Hello"
        assert msg.sender_id == "user-2"

    def test_parse_with_session_id(self):
        raw = {
            "type": "message",
            "content": "test",
            "sender_id": "u",
            "session_id": "sess-123",
        }
        msg = self.adapter.parse_incoming(raw)
        assert msg.metadata["session_id"] == "sess-123"
        assert "sess-123" in msg.channel_id

    def test_parse_ping_message(self):
        raw = {"type": "ping"}
        msg = self.adapter.parse_incoming(raw)
        assert msg.metadata["ws_message_type"] == "ping"
        assert msg.text == "__ping__"

    def test_parse_typing_message(self):
        raw = {"type": "typing", "content": "true"}
        msg = self.adapter.parse_incoming(raw)
        assert msg.metadata["ws_message_type"] == "typing"

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            self.adapter.parse_incoming("not valid json {{{")

    def test_parse_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown message type"):
            self.adapter.parse_incoming({"type": "unknown_type"})

    def test_parse_invalid_input_type_raises(self):
        with pytest.raises(ValueError, match="Unexpected message type"):
            self.adapter.parse_incoming(12345)

    def test_parse_default_sender_anonymous(self):
        raw = {"type": "message", "content": "hi"}
        msg = self.adapter.parse_incoming(raw)
        assert msg.sender_id == "anonymous"

    # --- format_outgoing ---

    def test_format_outgoing_basic(self):
        response = {"answer": "Xin chào!", "sources": []}
        result = json.loads(self.adapter.format_outgoing(response))
        assert result["type"] == "response"
        assert result["content"] == "Xin chào!"

    def test_format_outgoing_with_sources(self):
        response = {
            "answer": "answer",
            "sources": [{"title": "COLREGs Rule 15"}],
        }
        result = json.loads(self.adapter.format_outgoing(response))
        assert result["sources"] == [{"title": "COLREGs Rule 15"}]

    def test_format_outgoing_fallback_content_key(self):
        """If 'answer' not in response, fall back to 'content'."""
        response = {"content": "fallback answer"}
        result = json.loads(self.adapter.format_outgoing(response))
        assert result["content"] == "fallback answer"

    # --- format helpers ---

    def test_format_error(self):
        result = json.loads(self.adapter.format_error("Something went wrong"))
        assert result["type"] == "error"
        assert result["content"] == "Something went wrong"

    def test_format_pong(self):
        result = json.loads(self.adapter.format_pong())
        assert result["type"] == "pong"

    def test_format_typing_true(self):
        result = json.loads(self.adapter.format_typing(True))
        assert result["type"] == "typing"
        assert result["content"] is True

    def test_format_typing_false(self):
        result = json.loads(self.adapter.format_typing(False))
        assert result["content"] is False


# ============================================================================
# WebSocket org projection tests
# ============================================================================


class TestWebSocketOrgProjection:
    def test_connection_org_strict_requires_org_context(self):
        with pytest.raises(ValueError, match="Organization context required"):
            _resolve_ws_connection_org_id({}, "", strict=True)

    def test_connection_org_strict_rejects_auth_query_mismatch(self):
        with pytest.raises(ValueError, match="mismatch"):
            _resolve_ws_connection_org_id(
                {"organization_id": "org-A"},
                "org-B",
                strict=True,
            )

    def test_message_org_strict_pins_connection_org(self):
        assert (
            _resolve_ws_message_org_id(
                {},
                connection_org_id="org-A",
                strict=True,
            )
            == "org-A"
        )

    def test_message_org_strict_rejects_message_override(self):
        with pytest.raises(ValueError, match="mismatch"):
            _resolve_ws_message_org_id(
                {"organization_id": "org-B"},
                connection_org_id="org-A",
                strict=True,
            )

    def test_message_org_strict_rejects_body_only_org(self):
        with pytest.raises(ValueError, match="established during auth"):
            _resolve_ws_message_org_id(
                {"organization_id": "org-body-only"},
                connection_org_id="",
                strict=True,
            )

    def test_message_org_legacy_allows_metadata_override(self):
        assert (
            _resolve_ws_message_org_id(
                {"organization_id": "org-message"},
                connection_org_id="org-connection",
                strict=False,
            )
            == "org-message"
        )


# ============================================================================
# WebSocket first-message auth tests
# ============================================================================


class TestWebSocketFirstMessageAuth:
    def test_jwt_auth_uses_token_identity_even_when_api_key_is_configured(self, monkeypatch):
        from app.auth.token_service import create_access_token
        from app.core.config import settings

        monkeypatch.setattr(settings, "api_key", "configured-api-key", raising=False)
        monkeypatch.setattr(settings, "environment", "production", raising=False)
        monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-key-for-wiii-ws-auth-123", raising=False)
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256", raising=False)
        monkeypatch.setattr(settings, "jwt_audience", "wiii", raising=False)

        token = create_access_token(
            user_id="jwt-user",
            role="teacher",
            active_organization_id="org-token",
            auth_method="google",
        )

        identity = _resolve_ws_auth_identity(
            {
                "type": "auth",
                "access_token": token,
                "api_key": "wrong-api-key",
                "user_id": "spoofed-user",
                "role": "admin",
                "organization_id": "org-token",
            },
            strict_org_mode=True,
        )

        assert identity == {
            "user_id": "jwt-user",
            "role": "teacher",
            "organization_id": "org-token",
            "auth_method": "google",
        }

    def test_jwt_auth_rejects_body_org_mismatch(self, monkeypatch):
        from app.auth.token_service import create_access_token
        from app.core.config import settings

        monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-key-for-wiii-ws-auth-123", raising=False)
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256", raising=False)
        monkeypatch.setattr(settings, "jwt_audience", "wiii", raising=False)

        token = create_access_token(
            user_id="jwt-user",
            role="teacher",
            active_organization_id="org-token",
        )

        with pytest.raises(ValueError, match="organization context mismatch"):
            _resolve_ws_auth_identity(
                {
                    "type": "auth",
                    "authorization": f"Bearer {token}",
                    "organization_id": "org-other",
                },
                strict_org_mode=True,
            )

    def test_legacy_api_key_auth_still_uses_first_message_identity(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "api_key", "configured-api-key", raising=False)
        monkeypatch.setattr(settings, "environment", "development", raising=False)

        identity = _resolve_ws_auth_identity(
            {
                "type": "auth",
                "api_key": "configured-api-key",
                "user_id": "legacy-user",
                "role": "teacher",
                "organization_id": "org-legacy",
            },
            strict_org_mode=False,
        )

        assert identity == {
            "user_id": "legacy-user",
            "role": "teacher",
            "organization_id": "org-legacy",
            "auth_method": "api_key",
        }


# ============================================================================
# ConnectionManager Tests
# ============================================================================


class TestConnectionManager:
    """Test WebSocket connection manager."""

    def test_initial_state(self):
        mgr = ConnectionManager()
        assert mgr.active_connections == 0
        assert mgr.get_sessions() == []

    @pytest.mark.asyncio
    async def test_connect_registers_session(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "session-1")
        assert mgr.active_connections == 1
        assert "session-1" in mgr.get_sessions()
        ws.accept.assert_awaited_once()

    def test_disconnect_removes_session(self):
        mgr = ConnectionManager()
        mgr._connections["session-1"] = MagicMock()
        mgr.disconnect("session-1")
        assert mgr.active_connections == 0

    def test_disconnect_nonexistent_no_error(self):
        mgr = ConnectionManager()
        mgr.disconnect("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_send_json(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        mgr._connections["session-1"] = ws
        await mgr.send_json("session-1", '{"type": "test"}')
        ws.send_text.assert_awaited_once_with('{"type": "test"}')

    @pytest.mark.asyncio
    async def test_send_json_no_connection(self):
        mgr = ConnectionManager()
        await mgr.send_json("nonexistent", "data")  # Should not raise
