"""
WebSocket Connection Manager and real-time event broadcaster.
"""
from __future__ import annotations

import asyncio
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

        payload = json.dumps(message)
        connections = list(self.active_connections)

        # Fan-out concurrently — all clients receive the message in parallel
        results = await asyncio.gather(
            *[conn.send_text(payload) for conn in connections],
            return_exceptions=True,
        )

        # Prune any connections that raised an exception
        for conn, result in zip(connections, results):
            if isinstance(result, Exception):
                logger.warning(f"WebSocket send failed, dropping client: {result}")
                self.active_connections.discard(conn)


manager = ConnectionManager()
websocket_router = APIRouter()


@websocket_router.websocket("")
@websocket_router.websocket("/")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial connected status enriched with live telemetry and latest entries
        init_payload: dict = {
            "type": "connected",
            "message": "Connected to Global AI Gazette Autonomous Intelligence Radar",
        }
        try:
            from ai_security_monitor.presentation.api.routers.entries import query_serialized_entries
            from ai_security_monitor.presentation.api.routers.stats import get_monitor_service

            svc = get_monitor_service()
            init_payload["stats"] = await svc.get_stats()
            entries_list, total_cnt = await query_serialized_entries(limit=50)
            init_payload["recent_entries"] = entries_list
            init_payload["total_entries"] = total_cnt
        except Exception as hydrate_err:
            logger.debug(f"Failed to attach live telemetry to WS connected message: {hydrate_err}")

        await websocket.send_text(json.dumps(init_payload))

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
