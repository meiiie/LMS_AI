"""
SoulBridge API — Monitoring, control, and WebSocket endpoints for soul-to-soul communication.

Sprint 213: "Cầu Nối Linh Hồn"
Sprint 216: Peer events + detail endpoints for SoulBridgePanel

Endpoints:
    GET  /api/v1/soul-bridge/status                 — Bridge status + peer connection states
    GET  /api/v1/soul-bridge/peers                  — List connected peers with agent cards
    GET  /api/v1/soul-bridge/peers/{id}/card        — Fetch specific peer's agent card
    GET  /api/v1/soul-bridge/peers/{id}/events      — Recent events from a specific peer
    GET  /api/v1/soul-bridge/peers/{id}/detail      — Full peer detail (card + state + events)
    POST /api/v1/soul-bridge/events                 — HTTP fallback for receiving events
    WS   /api/v1/soul-bridge/ws                     — WebSocket for real-time connection
    POST /api/v1/soul-bridge/connect                — Manually trigger connection to a peer
    POST /api/v1/soul-bridge/disconnect             — Disconnect from a peer
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import AuthenticatedUser, is_platform_admin, require_auth

router = APIRouter(prefix="/soul-bridge", tags=["soul-bridge"])
logger = logging.getLogger(__name__)


def _require_admin(auth: AuthenticatedUser) -> None:
    """Only admin users can manage soul bridge connections."""
    if not is_platform_admin(auth):
        raise HTTPException(
            status_code=403,
            detail="Admin role required to manage SoulBridge connections.",
        )


def _get_bridge():
    """Get SoulBridge instance or raise 503."""
    from app.engine.soul_bridge import get_soul_bridge
    bridge = get_soul_bridge()
    if not bridge.is_initialized:
        raise HTTPException(
            status_code=503,
            detail="SoulBridge not initialized. Check enable_soul_bridge flag.",
        )
    return bridge


def _disabled_bridge_status() -> Dict[str, Any]:
    events = [
        item.strip()
        for item in getattr(settings, "soul_bridge_bridge_events", "").split(",")
        if item.strip()
    ]
    return {
        "initialized": False,
        "soul_id": "wiii",
        "bridge_events": events,
        "peer_count": 0,
        "peers": {},
        "enabled": bool(getattr(settings, "enable_soul_bridge", False)),
    }


# =============================================================================
# REST Endpoints
# =============================================================================


@router.get("/status")
async def get_bridge_status(
    auth: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """Full bridge status including all peer connection states. Admin only."""
    _require_admin(auth)
    if not settings.enable_soul_bridge:
        return _disabled_bridge_status()
    try:
        bridge = _get_bridge()
    except HTTPException as exc:
        if exc.status_code == 503:
            return _disabled_bridge_status()
        raise
    return bridge.get_bridge_status()


@router.get("/peers")
async def list_peers(
    auth: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """List all configured peers with their connection state and agent cards. Admin only."""
    _require_admin(auth)
    bridge = _get_bridge()
    peers = {}
    for peer_id, status_data in bridge.get_all_peer_status().items():
        card = bridge.get_peer_card(peer_id)
        peers[peer_id] = {
            "state": status_data,
            "card": card.to_dict() if card else None,
        }
    return {"peers": peers, "count": len(peers)}


@router.get("/peers/{peer_id}/card")
async def get_peer_card(
    peer_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """Fetch a specific peer's agent card (from cache). Admin only."""
    _require_admin(auth)
    bridge = _get_bridge()
    card = bridge.get_peer_card(peer_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"No agent card cached for peer '{peer_id}'")
    return card.to_dict()


@router.get("/peers/{peer_id}/events")
async def get_peer_events(
    peer_id: str,
    limit: int = 50,
    event_type: str | None = None,
) -> Dict[str, Any]:
    """Recent events from a specific peer (from Soul Bridge ring buffer)."""
    bridge = _get_bridge()
    events = bridge.get_peer_events(peer_id, event_type=event_type, limit=limit)
    return {"peer_id": peer_id, "events": events, "count": len(events)}


@router.get("/peers/{peer_id}/detail")
async def get_peer_detail(peer_id: str) -> Dict[str, Any]:
    """Detailed peer status: agent card + connection state + recent events."""
    bridge = _get_bridge()

    if peer_id not in bridge._peers:
        raise HTTPException(status_code=404, detail=f"Peer '{peer_id}' not found")

    conn = bridge._peers[peer_id]
    card = bridge.get_peer_card(peer_id)
    card_dict = None
    if card:
        card_dict = {
            "name": getattr(card, "name", ""),
            "description": getattr(card, "description", ""),
            "capabilities": getattr(card, "capabilities", []),
            "supported_events": getattr(card, "supported_events", []),
            "soul_id": getattr(card, "soul_id", peer_id),
        }

    recent = bridge.get_peer_events(peer_id, limit=20)

    # Extract latest status from most recent STATUS_UPDATE
    latest_status = None
    for evt in reversed(recent):
        if evt.get("event_type") == "STATUS_UPDATE":
            latest_status = evt.get("payload")
            break

    return {
        "peer_id": peer_id,
        "state": conn.state.value if hasattr(conn.state, "value") else str(conn.state),
        "card": card_dict,
        "latest_status": latest_status,
        "recent_events": recent,
        "event_count": len(recent),
    }


class EventPayload(BaseModel):
    """HTTP fallback event payload."""
    id: Optional[str] = None
    source_soul: str = ""
    target_soul: str = ""
    event_type: str = ""
    payload: Dict[str, Any] = {}
    timestamp: Optional[str] = None
    priority: str = "NORMAL"


@router.post("/events")
async def receive_event(event: EventPayload) -> Dict[str, Any]:
    """HTTP fallback endpoint for receiving events from peers.

    Used when WebSocket is unavailable. Same processing as WebSocket messages.
    """
    bridge = _get_bridge()

    from app.engine.soul_bridge.models import SoulBridgeMessage
    message = SoulBridgeMessage.from_json_dict(event.model_dump(mode="json"))

    # Process via bridge's remote event handler
    await bridge._on_remote_event(message)

    return {"received": True, "message_id": message.id}


class ConnectRequest(BaseModel):
    """Request to connect to a peer."""
    peer_id: str


@router.post("/connect")
async def connect_to_peer(
    request: ConnectRequest,
    auth: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """Manually trigger connection to a specific peer. Admin only."""
    _require_admin(auth)
    bridge = _get_bridge()
    success = await bridge.connect_to_peer(request.peer_id)
    return {
        "peer_id": request.peer_id,
        "connected": success,
        "state": bridge.get_peer_status(request.peer_id).value if bridge.get_peer_status(request.peer_id) else "UNKNOWN",
    }


@router.post("/disconnect")
async def disconnect_from_peer(
    request: ConnectRequest,
    auth: AuthenticatedUser = Depends(require_auth),
) -> Dict[str, Any]:
    """Disconnect from a specific peer. Admin only."""
    _require_admin(auth)
    bridge = _get_bridge()
    success = await bridge.disconnect_from_peer(request.peer_id)
    return {"peer_id": request.peer_id, "disconnected": success}


# =============================================================================
# WebSocket Endpoint
# =============================================================================


@router.websocket("/ws")
async def soul_bridge_ws(websocket: WebSocket):
    """WebSocket endpoint for real-time soul-to-soul communication.

    Peers connect here to exchange events bidirectionally.
    Messages are JSON-encoded SoulBridgeMessage envelopes.
    """
    await websocket.accept()
    logger.info("[SOUL_BRIDGE_WS] Peer connected from %s", websocket.client)

    if not settings.enable_soul_bridge:
        await websocket.close(code=1008, reason="SoulBridge disabled")
        return

    bridge = None
    try:
        from app.engine.soul_bridge import get_soul_bridge
        bridge = get_soul_bridge()
    except Exception:
        await websocket.close(code=1011, reason="SoulBridge not available")
        return

    try:
        while True:
            raw = await websocket.receive_text()

            # Handle ping/pong
            if raw == "ping":
                await websocket.send_text("pong")
                continue

            # Parse message
            try:
                data = json.loads(raw)
                from app.engine.soul_bridge.models import SoulBridgeMessage
                message = SoulBridgeMessage.from_json_dict(data)

                # Process via bridge
                await bridge._on_remote_event(message)
            except json.JSONDecodeError:
                logger.warning("[SOUL_BRIDGE_WS] Invalid JSON received")
            except Exception as e:
                logger.warning("[SOUL_BRIDGE_WS] Message processing error: %s", e)

    except WebSocketDisconnect:
        logger.info("[SOUL_BRIDGE_WS] Peer disconnected")
    except Exception as e:
        logger.warning("[SOUL_BRIDGE_WS] WebSocket error: %s", e)


# =============================================================================
# Agent Card Endpoint (served at app level, not under /api/v1/)
# =============================================================================
# Note: The /.well-known/agent.json endpoint is registered in main.py
# at the app root level, not under the API prefix.
