"""Tests for EA manager backpressure and overload mode behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from execution.broker_executor import ExecutionRequest, OrderAction
from execution.ea_manager import EAManager


def _make_request(request_id: str) -> ExecutionRequest:
    return ExecutionRequest(
        action=OrderAction.PLACE,
        account_id="ACC-001",
        symbol="EURUSD",
        lot_size=0.1,
        order_type="BUY_LIMIT",
        entry_price=1.1,
        stop_loss=1.09,
        take_profit=1.11,
        request_id=request_id,
    )


class TestEAManagerBackpressure:
    def test_reject_new_mode_rejects_when_full(self) -> None:
        with patch.dict(
            "os.environ",
            {"EA_QUEUE_MAXSIZE": "1", "EA_QUEUE_OVERLOAD_MODE": "reject_new"},
            clear=False,
        ):
            manager = EAManager()

        manager.submit(_make_request("REQ-1"))

        with pytest.raises(ValueError, match="queue overloaded"):
            manager.submit(_make_request("REQ-2"))

        snap = manager.queue_snapshot()
        assert snap["queue_depth"] == 1
        assert snap["overload_rejections"] == 1
        assert snap["overload_drops"] == 0

    def test_drop_oldest_mode_sheds_oldest_when_full(self) -> None:
        with patch.dict(
            "os.environ",
            {"EA_QUEUE_MAXSIZE": "1", "EA_QUEUE_OVERLOAD_MODE": "drop_oldest"},
            clear=False,
        ):
            manager = EAManager()

        req1 = _make_request("REQ-OLD")
        req2 = _make_request("REQ-NEW")

        manager.submit(req1)
        manager.submit(req2)

        queued = manager._queue.get_nowait()  # pyright: ignore[reportPrivateUsage]
        assert queued.request_id == "REQ-NEW"

        snap = manager.queue_snapshot()
        assert snap["overload_rejections"] == 0
        assert snap["overload_drops"] == 1
        assert snap["queue_depth"] == 0
