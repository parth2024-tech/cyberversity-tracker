#!/usr/bin/env python3
"""
AetherGuard Desktop Status Bar & System Tray Companion Widget.
Connects via WebSocket to the AetherGuard intelligence monitor and displays live breaking alerts.
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets

from ai_security_monitor.core.logging import get_logger

logger = get_logger(__name__)


class DesktopStatusWidget:
    """Simulates/runs a lightweight system tray & status bar widget companion."""

    def __init__(self, ws_url: str = "ws://localhost:8000/api/ws"):
        self.ws_url = ws_url
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info(f"Starting AetherGuard Desktop Status Bar Widget connecting to {self.ws_url}...")
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    logger.info("Connected to AetherGuard Intelligence Stream.")
                    async for message in websocket:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        if msg_type == "connected":
                            stats = data.get("stats", {})
                            logger.info(f"[STATUS BAR] Online | Total Entries: {stats.get('total_entries', 0)} | Threat Velocity Avg: {stats.get('avg_velocity', 0)}")
                        elif msg_type == "triage_queue_updated":
                            q_data = data.get("data", {})
                            logger.info(f"[STATUS BAR ALERT] Triage Queue Updated: {q_data.get('queue_size', 0)} pending LLM analysis.")
            except Exception as e:
                logger.warning(f"Status Bar Widget connection drop ({e}). Reconnecting in 5 seconds...")
                await asyncio.sleep(5)


if __name__ == "__main__":
    widget = DesktopStatusWidget()
    try:
        asyncio.run(widget.run())
    except KeyboardInterrupt:
        print("Status bar widget stopped.")
