"""
WebSocket package router export.
"""
from ai_security_monitor.presentation.api.websocket.manager import (
    manager,
    websocket_router,
)

__all__ = ["websocket_router", "manager"]
