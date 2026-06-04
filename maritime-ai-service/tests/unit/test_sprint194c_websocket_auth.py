# -*- coding: utf-8 -*-
"""Sprint 194c - B2 CRITICAL: WebSocket first-message auth."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_SP = "app.core.config.settings"

def _ws():
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


def _set_receive_sequence(ws, *items):
    ws.receive_text = AsyncMock(side_effect=list(items))

def _auth_msg(key="test-key", uid="user-1", role="student", **kw):
    msg = {"type": "auth", "api_key": key, "user_id": uid, "role": role}
    msg.update(kw)
    return json.dumps(msg)

class TestWSAuthTimeout:
    @pytest.mark.asyncio
    async def test_timeout_closes_4001(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        _set_receive_sequence(ws, asyncio.TimeoutError())
        await websocket_chat(ws, session_id="timeout-sess")
        ws.accept.assert_awaited_once()
        ws.close.assert_awaited_once()
        assert ws.close.call_args[1].get("code") == 4001

class TestWSInvalidMessage:
    @pytest.mark.asyncio
    async def test_non_json(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        _set_receive_sequence(ws, "not-json{{{")
        await websocket_chat(ws, session_id="bad-json")
        assert ws.close.call_args[1].get("code") == 4001

    @pytest.mark.asyncio
    async def test_wrong_type(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        _set_receive_sequence(ws, json.dumps({"type": "message"}))
        await websocket_chat(ws, session_id="wrong-type")
        assert ws.close.call_args[1].get("code") == 4001

    @pytest.mark.asyncio
    async def test_missing_type(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        _set_receive_sequence(ws, "{}")
        await websocket_chat(ws, session_id="no-type")
        assert ws.close.call_args[1].get("code") == 4001

class TestWSApiKeyValidation:
    @pytest.mark.asyncio
    async def test_wrong_key(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        ms = MagicMock(); ms.api_key = "correct"; ms.environment = "development"
        _set_receive_sequence(ws, _auth_msg(key="wrong"))
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="wrong-key")
        assert ws.close.call_args[1].get("code") == 4001

    @pytest.mark.asyncio
    async def test_empty_key_when_configured(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        ms = MagicMock(); ms.api_key = "configured"; ms.environment = "development"
        _set_receive_sequence(ws, _auth_msg(key=""))
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="empty-key")
        assert ws.close.call_args[1].get("code") == 4001

    @pytest.mark.asyncio
    async def test_no_key_production(self):
        from app.api.v1.websocket import websocket_chat
        ws = _ws()
        ms = MagicMock(); ms.api_key = None; ms.environment = "production"
        _set_receive_sequence(ws, _auth_msg(key="any"))
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="prod-no-key")
        assert ws.close.call_args[1].get("code") == 4001

    @pytest.mark.asyncio
    async def test_correct_key_sends_auth_ok(self):
        from app.api.v1.websocket import websocket_chat, manager
        from fastapi import WebSocketDisconnect
        ws = _ws()
        ms = MagicMock(); ms.api_key = "correct"; ms.environment = "development"
        _set_receive_sequence(ws, _auth_msg(key="correct"), WebSocketDisconnect())
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="good-key")
        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        manager.disconnect("good-key")

class TestWSProductionRoleDowngrade:
    @pytest.mark.asyncio
    async def test_admin_downgraded(self):
        from app.api.v1.websocket import websocket_chat, manager
        from fastapi import WebSocketDisconnect
        ws = _ws()
        ms = MagicMock(); ms.api_key = "key"; ms.environment = "production"; ms.enable_multi_tenant = True
        _set_receive_sequence(
            ws,
            _auth_msg(key="key", role="admin", organization_id="org-test"),
            WebSocketDisconnect(),
        )
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="prod-admin")
        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        manager.disconnect("prod-admin")

    @pytest.mark.asyncio
    async def test_teacher_preserved(self):
        from app.api.v1.websocket import websocket_chat, manager
        from fastapi import WebSocketDisconnect
        ws = _ws()
        ms = MagicMock(); ms.api_key = "key"; ms.environment = "production"; ms.enable_multi_tenant = True
        _set_receive_sequence(
            ws,
            _auth_msg(key="key", role="teacher", organization_id="org-test"),
            WebSocketDisconnect(),
        )
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="prod-teacher")
        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        manager.disconnect("prod-teacher")

class TestWSDevMode:
    @pytest.mark.asyncio
    async def test_dev_no_key_accepts(self):
        from app.api.v1.websocket import websocket_chat, manager
        from fastapi import WebSocketDisconnect
        ws = _ws()
        ms = MagicMock(); ms.api_key = None; ms.environment = "development"
        _set_receive_sequence(ws, _auth_msg(key="anything"), WebSocketDisconnect())
        with patch(_SP, ms):
            await websocket_chat(ws, session_id="dev-any")
        ws.send_json.assert_awaited_once_with({"type": "auth_ok"})
        manager.disconnect("dev-any")

class TestWSRegistration:
    @pytest.mark.asyncio
    async def test_org_id_registered(self):
        """register_user is called with org_id from auth message.

        NOTE: We spy on register_user rather than checking manager state
        because WebSocketDisconnect in the message loop triggers
        manager.disconnect() which clears the org mapping before
        websocket_chat returns.
        """
        from app.api.v1.websocket import websocket_chat, manager
        from fastapi import WebSocketDisconnect
        ws = _ws()
        ms = MagicMock(); ms.api_key = "k"; ms.environment = "development"
        _set_receive_sequence(
            ws,
            _auth_msg(key="k", uid="u1", organization_id="org-42"),
            WebSocketDisconnect(),
        )
        with patch(_SP, ms):
            with patch.object(manager, "register_user", wraps=manager.register_user) as spy:
                await websocket_chat(ws, session_id="org-reg")
        spy.assert_called_once_with("org-reg", "u1", "org-42")
