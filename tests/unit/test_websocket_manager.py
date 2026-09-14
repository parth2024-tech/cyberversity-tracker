"""
Unit tests for ConnectionManager — concurrent broadcast, dead-connection pruning,
connect/disconnect lifecycle.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_security_monitor.presentation.api.websocket.manager import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_ws(fail: bool = False) -> MagicMock:
    """Return a mock WebSocket. If fail=True, send_text raises RuntimeError."""
    ws = MagicMock()
    if fail:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    else:
        ws.send_text = AsyncMock()
    ws.accept = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_adds_to_active_set(self):
        mgr = ConnectionManager()
        ws = _mock_ws()
        await mgr.connect(ws)
        assert ws in mgr.active_connections

    def test_disconnect_removes_from_active_set(self):
        mgr = ConnectionManager()
        ws = _mock_ws()
        mgr.active_connections.add(ws)
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    def test_disconnect_unknown_ws_is_noop(self):
        """Calling disconnect on a socket that isn't tracked must not raise."""
        mgr = ConnectionManager()
        ws = _mock_ws()
        mgr.disconnect(ws)  # should not raise


# ---------------------------------------------------------------------------
# broadcast — no connections
# ---------------------------------------------------------------------------


class TestBroadcastEmpty:
    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections_is_noop(self):
        mgr = ConnectionManager()
        # Should complete without error and without calling gather
        await mgr.broadcast({"type": "ping"})


# ---------------------------------------------------------------------------
# broadcast — concurrent fan-out
# ---------------------------------------------------------------------------


class TestBroadcastConcurrent:
    @pytest.mark.asyncio
    async def test_all_live_connections_receive_message(self):
        mgr = ConnectionManager()
        ws1, ws2, ws3 = _mock_ws(), _mock_ws(), _mock_ws()
        mgr.active_connections = {ws1, ws2, ws3}

        message = {"type": "alert", "payload": "AI model released"}
        await mgr.broadcast(message)

        payload = json.dumps(message)
        ws1.send_text.assert_awaited_once_with(payload)
        ws2.send_text.assert_awaited_once_with(payload)
        ws3.send_text.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_dead_connection_is_pruned(self):
        mgr = ConnectionManager()
        live = _mock_ws(fail=False)
        dead = _mock_ws(fail=True)
        mgr.active_connections = {live, dead}

        await mgr.broadcast({"type": "heartbeat"})

        assert live in mgr.active_connections
        assert dead not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_multiple_dead_connections_all_pruned(self):
        mgr = ConnectionManager()
        live = _mock_ws(fail=False)
        dead1 = _mock_ws(fail=True)
        dead2 = _mock_ws(fail=True)
        mgr.active_connections = {live, dead1, dead2}

        await mgr.broadcast({"type": "sweep"})

        assert mgr.active_connections == {live}

    @pytest.mark.asyncio
    async def test_broadcast_serializes_message_as_json(self):
        """Verify that broadcast sends proper JSON, not repr(dict)."""
        mgr = ConnectionManager()
        ws = _mock_ws()
        mgr.active_connections = {ws}

        msg = {"event": "model_release", "model": "GPT-5", "score": 99}
        await mgr.broadcast(msg)

        sent_payload = ws.send_text.call_args[0][0]
        parsed = json.loads(sent_payload)
        assert parsed == msg

    @pytest.mark.asyncio
    async def test_broadcast_sends_same_payload_to_all(self):
        """Verify all clients receive exactly the same serialized payload."""
        mgr = ConnectionManager()
        ws_list = [_mock_ws() for _ in range(5)]
        mgr.active_connections = set(ws_list)

        msg = {"type": "global_broadcast"}
        await mgr.broadcast(msg)

        expected = json.dumps(msg)
        for ws in ws_list:
            ws.send_text.assert_awaited_once_with(expected)
