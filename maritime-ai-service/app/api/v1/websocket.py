"""
WebSocket Chat Endpoint — Real-time bidirectional messaging for Wiii.

Provides WebSocket connections at /api/v1/ws/{session_id} for real-time
chat. Supports JSON message protocol with typing indicators and heartbeat.

Sprint 12: Multi-Channel Gateway.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.channels.base import to_chat_request
from app.channels.websocket_adapter import WebSocketAdapter

logger = logging.getLogger(__name__)

router = APIRouter()

# WebSocket adapter singleton
_ws_adapter = WebSocketAdapter()


def _normalize_ws_org_id(value: Any) -> str:
    """Return a stripped org id only when the client sent a string."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _is_strict_websocket_org_mode() -> bool:
    try:
        from app.core.config import settings

        return bool(
            settings.enable_multi_tenant
            and settings.environment in ("production", "staging")
        )
    except Exception:
        return False


def _resolve_ws_connection_org_id(
    auth_msg: dict[str, Any],
    query_org_id: str = "",
    *,
    strict: bool | None = None,
) -> str:
    strict_mode = _is_strict_websocket_org_mode() if strict is None else strict
    auth_org_id = _normalize_ws_org_id(auth_msg.get("organization_id"))
    query_org = _normalize_ws_org_id(query_org_id)

    if strict_mode:
        if auth_org_id and query_org and auth_org_id != query_org:
            raise ValueError("WebSocket organization context mismatch")
        if not auth_org_id and not query_org:
            raise ValueError("Organization context required for WebSocket")

    return auth_org_id or query_org


def _resolve_ws_message_org_id(
    metadata: dict[str, Any],
    *,
    connection_org_id: str = "",
    query_org_id: str = "",
    strict: bool | None = None,
) -> str:
    strict_mode = _is_strict_websocket_org_mode() if strict is None else strict
    metadata_org_id = _normalize_ws_org_id(metadata.get("organization_id"))
    pinned_org_id = _normalize_ws_org_id(connection_org_id) or _normalize_ws_org_id(
        query_org_id
    )

    if strict_mode:
        if metadata_org_id and not pinned_org_id:
            raise ValueError("WebSocket organization must be established during auth")
        if metadata_org_id and metadata_org_id != pinned_org_id:
            raise ValueError("WebSocket message organization mismatch")
        return pinned_org_id

    return metadata_org_id or pinned_org_id


def _extract_ws_access_token(auth_msg: dict[str, Any]) -> str:
    raw_token = auth_msg.get("access_token") or auth_msg.get("authorization")
    if not isinstance(raw_token, str):
        return ""
    token = raw_token.strip()
    if token.lower().startswith("bearer "):
        return token.split(" ", 1)[1].strip()
    return token


def _value_error_detail(error: ValueError) -> str:
    """Return controlled ValueError text without stringifying arbitrary errors."""
    if len(error.args) == 1 and isinstance(error.args[0], str):
        return error.args[0]
    return ""


def _public_ws_auth_close_reason(error: ValueError) -> str:
    detail = _value_error_detail(error)
    if detail in {
        "Invalid API key",
        "API key required in production",
        "Invalid or expired access token",
        "JWT organization context required for WebSocket",
        "WebSocket organization context mismatch",
    }:
        return detail
    return "Authentication failed"


def _public_ws_org_close_reason(error: ValueError) -> str:
    detail = _value_error_detail(error)
    if detail in {
        "Organization context required for WebSocket",
        "WebSocket organization context mismatch",
        "WebSocket organization must be established during auth",
        "WebSocket message organization mismatch",
    }:
        return detail
    return "Organization context rejected"


def _resolve_ws_auth_identity(
    auth_msg: dict[str, Any],
    *,
    strict_org_mode: bool | None = None,
) -> dict[str, str]:
    """Resolve first-message WebSocket auth from JWT or legacy API key."""
    strict_mode = _is_strict_websocket_org_mode() if strict_org_mode is None else strict_org_mode
    access_token = _extract_ws_access_token(auth_msg)
    if access_token:
        try:
            from app.auth.token_service import verify_access_token

            payload = verify_access_token(access_token)
        except Exception as e:
            raise ValueError("Invalid or expired access token") from e

        token_org_id = _normalize_ws_org_id(payload.active_organization_id)
        body_org_id = _normalize_ws_org_id(auth_msg.get("organization_id"))
        if token_org_id and body_org_id and token_org_id != body_org_id:
            raise ValueError("WebSocket organization context mismatch")
        if strict_mode and not token_org_id:
            raise ValueError("JWT organization context required for WebSocket")

        return {
            "user_id": payload.sub,
            "role": payload.role or "student",
            "organization_id": token_org_id or body_org_id,
            "auth_method": payload.auth_method or "jwt",
        }

    api_key = auth_msg.get("api_key", "")
    try:
        from app.core.config import settings
        import hmac as _hmac

        if settings.api_key:
            if not isinstance(api_key, str) or not _hmac.compare_digest(api_key, settings.api_key):
                raise ValueError("Invalid API key")
        elif settings.environment == "production":
            raise ValueError("API key required in production")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("Authentication error") from e

    ws_user_role = auth_msg.get("role", "student")
    if not isinstance(ws_user_role, str):
        ws_user_role = "student"
    if settings.environment == "production" and ws_user_role not in ("student", "teacher"):
        logger.warning(
            "[WS] SECURITY: API key auth attempted role=%s - downgraded to student",
            ws_user_role,
        )
        ws_user_role = "student"

    ws_user_id = auth_msg.get("user_id", "anonymous")
    if not isinstance(ws_user_id, str) or not ws_user_id.strip():
        ws_user_id = "anonymous"

    return {
        "user_id": ws_user_id,
        "role": ws_user_role,
        "organization_id": _normalize_ws_org_id(auth_msg.get("organization_id")),
        "auth_method": "api_key",
    }


class ConnectionManager:
    """
    Manages active WebSocket connections.

    Tracks connections by session_id and user_id for targeted messaging
    and ensures clean disconnect handling.

    Sprint 20: Added user_id tracking for proactive notifications.
    Sprint 171b: Added organization_id tracking for multi-tenant isolation.
    """

    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}       # session_id → ws
        self._user_sessions: Dict[str, Set[str]] = {}      # user_id → {session_ids}
        self._session_users: Dict[str, str] = {}            # session_id → user_id
        self._session_orgs: Dict[str, str] = {}             # session_id → org_id

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a WebSocket connection and register it."""
        await websocket.accept()
        self._connections[session_id] = websocket
        logger.info("[WS] Connected: session=%s", session_id)

    def register_user(
        self, session_id: str, user_id: str, organization_id: str = ""
    ) -> None:
        """Link a session to a user_id and optional org_id."""
        self._session_users[session_id] = user_id
        if organization_id:
            self._session_orgs[session_id] = organization_id
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = set()
        self._user_sessions[user_id].add(session_id)
        logger.debug(
            "[WS] Registered user=%s org=%s on session=%s",
            user_id, organization_id or "(none)", session_id,
        )

    def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection and clean up user/org mapping."""
        self._connections.pop(session_id, None)
        self._session_orgs.pop(session_id, None)
        user_id = self._session_users.pop(session_id, None)
        if user_id and user_id in self._user_sessions:
            self._user_sessions[user_id].discard(session_id)
            if not self._user_sessions[user_id]:
                del self._user_sessions[user_id]
        logger.info("[WS] Disconnected: session=%s", session_id)

    async def send_json(self, session_id: str, data: str) -> None:
        """Send a JSON string to a specific session."""
        ws = self._connections.get(session_id)
        if ws:
            await ws.send_text(data)

    async def send_to_user(
        self, user_id: str, data: str, organization_id: str = ""
    ) -> int:
        """
        Send a message to sessions belonging to a user.

        When organization_id is provided, only sends to sessions in that org
        (prevents cross-org message leakage in multi-tenant mode).

        Returns the number of sessions the message was sent to.
        """
        session_ids = self._user_sessions.get(user_id, set())
        sent = 0
        for sid in list(session_ids):
            # Filter by org if specified
            if organization_id and self._session_orgs.get(sid) != organization_id:
                continue
            ws = self._connections.get(sid)
            if ws:
                try:
                    await ws.send_text(data)
                    sent += 1
                except Exception as e:
                    logger.warning("[WS] Failed to send to session=%s: %s", sid, e)
        return sent

    def is_user_online(self, user_id: str) -> bool:
        """Check if a user has any active WebSocket connections."""
        session_ids = self._user_sessions.get(user_id, set())
        return any(sid in self._connections for sid in session_ids)

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    def get_sessions(self) -> list:
        return list(self._connections.keys())

    def get_user_sessions(self, user_id: str) -> Set[str]:
        """Get all session_ids for a user."""
        return self._user_sessions.get(user_id, set()).copy()

    def get_session_org(self, session_id: str) -> str:
        """Get organization_id for a session."""
        return self._session_orgs.get(session_id, "")


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    organization_id: str = Query(default="", alias="org_id"),
):
    """
    WebSocket endpoint for real-time chat.

    Protocol:
    - First message MUST be auth: {"type": "auth", "access_token": "jwt"} or {"type": "auth", "api_key": "xxx", "user_id": "...", "role": "..."}
    - Server responds: {"type": "auth_ok"} or closes with 4001
    - Client sends: {"type": "message", "content": "question", "sender_id": "user-123"}
    - Server responds: {"type": "response", "content": "answer", "sources": [...]}
    - Heartbeat: Client sends {"type": "ping"}, server responds {"type": "pong"}
    - Typing: Server sends {"type": "typing", "content": true/false}

    Sprint 194c (B2 CRITICAL): API key moved from query parameter to first-message
    auth to prevent leaking credentials in access logs, browser history, and CDN logs.
    OAuth/JWT clients use the same first-message envelope via access_token.
    """
    await websocket.accept()

    # ── First-message auth (timeout 10s) ──────────────────────────
    try:
        raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        auth_msg = json.loads(raw_auth)
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout — send auth message within 10s")
        return
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("[WS] Auth message parse failed: %s", e)
        await websocket.close(code=4001, reason="Invalid auth message format")
        return

    if auth_msg.get("type") != "auth":
        await websocket.close(code=4001, reason="First message must be type='auth'")
        return

    strict_org_mode = _is_strict_websocket_org_mode()
    try:
        ws_identity = _resolve_ws_auth_identity(
            auth_msg,
            strict_org_mode=strict_org_mode,
        )
    except ValueError as exc:
        logger.warning("[WS] Auth rejected: %s", exc)
        await websocket.close(code=4001, reason=_public_ws_auth_close_reason(exc))
        return

    ws_user_id = ws_identity["user_id"]
    ws_user_role = ws_identity["role"]
    auth_context_msg = {
        **auth_msg,
        "organization_id": ws_identity.get("organization_id", ""),
    }

    # Auth OK - register connection
    try:
        connection_org_id = _resolve_ws_connection_org_id(
            auth_context_msg,
            organization_id,
            strict=strict_org_mode,
        )
    except ValueError as exc:
        logger.warning("[WS] Organization context rejected: %s", exc)
        await websocket.close(code=4003, reason=_public_ws_org_close_reason(exc))
        return

    manager._connections[session_id] = websocket
    logger.info("[WS] Connected: session=%s user=%s", session_id, ws_user_id)

    # Register user from auth message
    if ws_user_id:
        manager.register_user(session_id, ws_user_id, connection_org_id)

    await websocket.send_json({"type": "auth_ok"})

    # ── Message loop ──────────────────────────────────────────────
    try:
        while True:
            raw_data = await websocket.receive_text()

            try:
                channel_msg = _ws_adapter.parse_incoming(raw_data)
            except ValueError as e:
                await websocket.send_text(
                    _ws_adapter.format_error(f"Invalid message: {e}")
                )
                continue

            try:
                msg_org_id = _resolve_ws_message_org_id(
                    channel_msg.metadata,
                    connection_org_id=connection_org_id,
                    query_org_id=organization_id,
                    strict=strict_org_mode,
                )
            except ValueError as exc:
                logger.warning("[WS] Message organization context rejected: %s", exc)
                await websocket.close(
                    code=4003,
                    reason=_public_ws_org_close_reason(exc),
                )
                manager.disconnect(session_id)
                return

            if channel_msg.sender_id:
                manager.register_user(session_id, channel_msg.sender_id, msg_org_id)

            # Handle ping/pong heartbeat
            if channel_msg.metadata.get("ws_message_type") == "ping":
                await websocket.send_text(_ws_adapter.format_pong())
                continue

            # Handle typing indicator (client-side, just acknowledge)
            if channel_msg.metadata.get("ws_message_type") == "typing":
                continue

            # Process message through the pipeline
            org_context_var = None
            org_context_token = None
            try:
                # Send typing indicator
                await websocket.send_text(_ws_adapter.format_typing(True))

                # Set org context ContextVar for downstream filtering
                if msg_org_id:
                    try:
                        from app.core.org_context import current_org_id

                        org_context_var = current_org_id
                        org_context_token = current_org_id.set(msg_org_id)
                    except Exception:
                        pass

                # Convert to ChatRequest
                chat_request = to_chat_request(channel_msg)
                chat_request.session_id = session_id
                if msg_org_id:
                    chat_request.organization_id = msg_org_id

                # Process via ChatOrchestrator
                from app.services.chat_orchestrator import ChatOrchestrator
                orchestrator = ChatOrchestrator()
                result = await orchestrator.process(chat_request)

                # Format and send response
                response_data = {
                    "answer": result.get("answer", result.get("response", "")),
                    "sources": result.get("sources", []),
                    "metadata": result.get("metadata", {}),
                }
                await websocket.send_text(_ws_adapter.format_outgoing(response_data))

            except Exception as e:
                logger.error("[WS] Error processing message: %s", e, exc_info=True)
                await websocket.send_text(
                    _ws_adapter.format_error("Internal processing error")
                )
            finally:
                if org_context_var is not None and org_context_token is not None:
                    try:
                        org_context_var.reset(org_context_token)
                    except Exception:
                        pass
                await websocket.send_text(_ws_adapter.format_typing(False))

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error("[WS] Unexpected error: %s", e, exc_info=True)
        manager.disconnect(session_id)
