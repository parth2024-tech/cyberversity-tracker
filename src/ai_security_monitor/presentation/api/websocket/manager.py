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
        logger.info(
            f"WebSocket client connected. Total clients: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(
            f"WebSocket client disconnected. Total clients: {len(self.active_connections)}"
        )

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return

        payload = json.dumps(message)
        connections = list(self.active_connections)

        async def _send_with_timeout(conn: WebSocket) -> bool:
            try:
                # Enforce 2.0s send timeout to apply backpressure on slow/stalled consumers
                await asyncio.wait_for(conn.send_text(payload), timeout=2.0)
                return True
            except (TimeoutError, Exception) as err:
                logger.warning(
                    f"WebSocket consumer stalled or failed ({err}), dropping connection."
                )
                from ai_security_monitor.core.diagnostics import diagnostics

                diagnostics.record_websocket_backpressure_drop()
                self.active_connections.discard(conn)
                try:
                    await conn.close(code=1008)
                except Exception:
                    pass
                return False

        # Fan-out concurrently with timeout protection across all active connections
        await asyncio.gather(
            *[_send_with_timeout(c) for c in connections], return_exceptions=True
        )


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
            from ai_security_monitor.presentation.api.routers.entries import (
                query_serialized_entries,
            )
            from ai_security_monitor.presentation.api.routers.stats import (
                get_monitor_service,
            )

            svc = get_monitor_service()
            init_payload["stats"] = await svc.get_stats()
            entries_list, total_cnt = await query_serialized_entries(limit=50)
            init_payload["recent_entries"] = entries_list
            init_payload["total_entries"] = total_cnt
        except Exception as hydrate_err:
            logger.debug(
                f"Failed to attach live telemetry to WS connected message: {hydrate_err}"
            )

        await websocket.send_text(json.dumps(init_payload))

        while True:
            # Handle incoming ping / messages
            data_raw = await websocket.receive_text()
            try:
                msg = json.loads(data_raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong", "timestamp": msg.get("timestamp")})
                    )
            except Exception as _msg_err:
                logger.debug(f"Ignoring malformed WebSocket message: {_msg_err}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket connection error: {e}")
        manager.disconnect(websocket)
