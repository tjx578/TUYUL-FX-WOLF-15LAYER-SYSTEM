"""Regression tests for the Redis candle-cache clearing script."""

from __future__ import annotations

from unittest.mock import MagicMock

from scripts.clear_redis_cache import _delete_scan_pattern


def test_delete_scan_pattern_does_not_send_empty_del() -> None:
    client = MagicMock()
    client.scan_iter.return_value = []
    client.delete.return_value = 0

    deleted = _delete_scan_pattern(client, "wolf15:candle_history:*")

    assert deleted == 0
    client.delete.assert_not_called()


def test_delete_scan_pattern_deletes_in_batches() -> None:
    client = MagicMock()
    client.scan_iter.return_value = ["k1", "k2", "k3", "k4", "k5"]
    client.delete.side_effect = [2, 2, 1]

    deleted = _delete_scan_pattern(client, "wolf15:candle_history:*", batch_size=2)

    assert deleted == 5
    assert client.delete.call_args_list[0].args == ("k1", "k2")
    assert client.delete.call_args_list[1].args == ("k3", "k4")
    assert client.delete.call_args_list[2].args == ("k5",)
