"""
Tests for monotonic seq# on ConnectionManager.broadcast().

Validates: per-connection seq stamping, monotonic increment, seq-based replay_buffer filtering.
"""

from __future__ import annotations

import itertools
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

        # Mock a connected websocket with per-connection seq counter
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mgr.active_connections = {mock_ws}
        mgr._per_conn_seq[mock_ws] = itertools.count(1)

        msg1 = {"type": "test", "data": "a"}
        msg2 = {"type": "test", "data": "b"}
        msg3 = {"type": "test", "data": "c"}

        await mgr.broadcast(msg1)
        await mgr.broadcast(msg2)
        await mgr.broadcast(msg3)

        # Per-connection seq is stamped on the copy sent to the client
        sent_calls = mock_ws.send_json.call_args_list
        assert sent_calls[0].args[0]["seq"] == 1
        assert sent_calls[1].args[0]["seq"] == 2
        assert sent_calls[2].args[0]["seq"] == 3

    @pytest.mark.asyncio
    async def test_broadcast_per_connection_no_gap(self) -> None:
        """Two clients each see contiguous seq even when send_stamped interleaves."""
        mgr = self._make_manager()

        ws_a = AsyncMock()
        ws_a.send_json = AsyncMock()
        ws_b = AsyncMock()
        ws_b.send_json = AsyncMock()
        mgr.active_connections = {ws_a, ws_b}
        mgr._per_conn_seq[ws_a] = itertools.count(1)
        mgr._per_conn_seq[ws_b] = itertools.count(1)

        # broadcast → both get seq=1
        await mgr.broadcast({"type": "test", "data": "1"})
        # send_stamped to ws_b only → ws_b gets seq=2, ws_a unaffected
        await mgr.send_stamped(ws_b, {"type": "heartbeat"})
        # broadcast → ws_a gets seq=2, ws_b gets seq=3
        await mgr.broadcast({"type": "test", "data": "2"})

        a_seqs = [c.args[0]["seq"] for c in ws_a.send_json.call_args_list]
        b_seqs = [c.args[0]["seq"] for c in ws_b.send_json.call_args_list]

        # ws_a sees 1, 2 (contiguous — no gap from ws_b's heartbeat)
        assert a_seqs == [1, 2]
        # ws_b sees 1, 2, 3 (contiguous)
        assert b_seqs == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_replay_buffer_filters_by_buf_seq(self) -> None:
        mgr = self._make_manager()

        # Broadcast 5 messages
        mock_ws = AsyncMock()
        mock_ws.send_json = AsyncMock()
        mgr.active_connections = {mock_ws}
        mgr._per_conn_seq[mock_ws] = itertools.count(1)

        for i in range(5):
            await mgr.broadcast({"type": "test", "idx": i})

        # Now replay to a "reconnecting" client, asking for messages since _buf_seq=3
        replay_ws = AsyncMock()
        replay_ws.send_json = AsyncMock()
        mgr._per_conn_seq[replay_ws] = itertools.count(1)

        await mgr.replay_buffer(replay_ws, since_seq=3)

        # Should only receive buf_seq 4 and 5, re-stamped with replay_ws's own seq
        assert replay_ws.send_json.await_count == 2
        sent_seqs = [call.args[0]["seq"] for call in replay_ws.send_json.call_args_list]
        assert sent_seqs == [1, 2]  # replay_ws's own counter starts at 1

    @pytest.mark.asyncio
    async def test_replay_buffer_ts_fallback_when_no_seq(self) -> None:
        mgr = self._make_manager()

        # Directly insert messages into buffer (no seq — simulates pre-upgrade messages)
        mgr._message_buffer.append({"type": "old", "ts": 100.0})
        mgr._message_buffer.append({"type": "old", "ts": 200.0})
        mgr._message_buffer.append({"type": "old", "ts": 300.0})

        replay_ws = AsyncMock()
        replay_ws.send_json = AsyncMock()
        mgr._per_conn_seq[replay_ws] = itertools.count(1)

        await mgr.replay_buffer(replay_ws, since_ts=150.0)

        # Should get messages with ts > 150 (ts=200 and ts=300)
        assert replay_ws.send_json.await_count == 2
