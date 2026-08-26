"""
WebSocket Connection Manager and real-time event broadcaster.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return

        dead_connections = set()
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.warn(f"Failed to send to WebSocket client: {e}")
                dead_connections.add(connection)

        for dead in dead_connections:
            self.active_connections.discard(dead)


manager = ConnectionManager()
websocket_router = APIRouter()


@websocket_router.websocket("")
@websocket_router.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial connected status
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "Connected to AetherGuard Autonomous Intelligence Radar"
        }))

        while True:
            # Handle incoming ping / messages
            data_raw = await websocket.receive_text()
            try:
                msg = json.loads(data_raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": msg.get("timestamp")
                    }))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warn(f"WebSocket connection error: {e}")
        manager.disconnect(websocket)
