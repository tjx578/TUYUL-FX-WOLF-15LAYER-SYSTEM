"""
Tests for monotonic seq# on ConnectionManager.broadcast().

Validates: seq stamping, monotonic increment, seq-based replay_buffer filtering.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConnectionManagerSeq:
    """Test seq# stamping in ConnectionManager."""

    def _make_manager(self) -> Any:
        """Import and create a ConnectionManager without side effects."""
        # Patch out redis_client at module level to avoid real Redis calls
        with patch.dict(
            "sys.modules",
            {
                "storage.redis_client": MagicMock(),
                "storage.l12_cache": MagicMock(VERDICT_READY_CHANNEL="test"),
                "allocation.signal_service": MagicMock(SIGNAL_READY_CHANNEL="test"),
            },
        ):
            # Dynamic import to avoid global import issues in test env
            import importlib

            ws_mod = importlib.import_module("api.ws_routes")
            return ws_mod.ConnectionManager(name="test_seq", buffer_size=100)

    @pytest.mark.asyncio
    async def test_broadcast_stamps_monotonic_seq(self) -> None:
        mgr = self._make_manager()

        # Mock a connected websocket
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mgr.active_connections = {mock_ws}

        msg1 = {"type": "test", "data": "a"}
        msg2 = {"type": "test", "data": "b"}
        msg3 = {"type": "test", "data": "c"}

        await mgr.broadcast(msg1)
        await mgr.broadcast(msg2)
        await mgr.broadcast(msg3)

        # Check seq numbers are monotonically increasing
        assert msg1["seq"] == 1
        assert msg2["seq"] == 2
        assert msg3["seq"] == 3

    @pytest.mark.asyncio
    async def test_replay_buffer_filters_by_seq(self) -> None:
        mgr = self._make_manager()

        # Broadcast 5 messages (no connected clients needed for buffering)
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mgr.active_connections = {mock_ws}

        for i in range(5):
            await mgr.broadcast({"type": "test", "idx": i})

        # Now replay to a "reconnecting" client, asking for messages since seq=3
        replay_ws = AsyncMock()
        replay_ws.send_json = AsyncMock()

        await mgr.replay_buffer(replay_ws, since_seq=3)

        # Should only receive seq 4 and 5
        assert replay_ws.send_json.await_count == 2
        sent_seqs = [call.args[0]["seq"] for call in replay_ws.send_json.call_args_list]
        assert sent_seqs == [4, 5]

    @pytest.mark.asyncio
    async def test_replay_buffer_ts_fallback_when_no_seq(self) -> None:
        mgr = self._make_manager()

        # Directly insert messages into buffer (no seq — simulates pre-upgrade messages)
        mgr._message_buffer.append({"type": "old", "ts": 100.0})
        mgr._message_buffer.append({"type": "old", "ts": 200.0})
        mgr._message_buffer.append({"type": "old", "ts": 300.0})

        replay_ws = AsyncMock()
        replay_ws.send_json = AsyncMock()

        await mgr.replay_buffer(replay_ws, since_ts=150.0)

        # Should get messages with ts > 150 (ts=200 and ts=300)
        assert replay_ws.send_json.await_count == 2
