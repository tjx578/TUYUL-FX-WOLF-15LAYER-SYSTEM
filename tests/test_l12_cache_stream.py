"""Tests for L12 cache verdict stream (durable event delivery).

Validates FIX-4: set_verdict now writes to Redis Stream in addition to pub/sub.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_redis():
    return MagicMock()


class TestSetVerdictStream:
    """set_verdict should XADD to the verdict stream for durable delivery."""

    def test_set_verdict_writes_stream(self, mock_redis):
        with patch("storage.l12_cache.redis_client", mock_redis):
            from storage.l12_cache import VERDICT_STREAM, set_verdict

            set_verdict("EURUSD", {"verdict": "EXECUTE", "confidence": 0.85})

            # Verify XADD was called
            mock_redis.xadd.assert_called_once()
            stream_call = mock_redis.xadd.call_args
            assert stream_call[0][0] == VERDICT_STREAM
            fields = stream_call[0][1]
            assert fields["pair"] == "EURUSD"
            assert "data" in fields

            # Verify data contains the verdict
            data = json.loads(fields["data"])
            assert data["verdict"] == "EXECUTE"
            assert "_cached_at" in data

    def test_set_verdict_still_publishes_pubsub(self, mock_redis):
        with patch("storage.l12_cache.redis_client", mock_redis):
            from storage.l12_cache import VERDICT_READY_CHANNEL, set_verdict

            set_verdict("GBPUSD", {"verdict": "HOLD"})

            mock_redis.publish.assert_called_once()
            pub_call = mock_redis.publish.call_args
            assert pub_call[0][0] == VERDICT_READY_CHANNEL

    def test_set_verdict_stream_maxlen(self, mock_redis):
        with patch("storage.l12_cache.redis_client", mock_redis):
            from storage.l12_cache import VERDICT_STREAM_MAXLEN, set_verdict

            set_verdict("XAUUSD", {"verdict": "NO_TRADE"})

            stream_call = mock_redis.xadd.call_args
            assert stream_call[1].get("maxlen") == VERDICT_STREAM_MAXLEN
            assert stream_call[1].get("approximate") is True

    def test_stream_failure_does_not_break_set_verdict(self, mock_redis):
        """Stream write failure is suppressed — cache + pubsub still work."""
        mock_redis.xadd.side_effect = ConnectionError("Redis down")
        with patch("storage.l12_cache.redis_client", mock_redis):
            from storage.l12_cache import set_verdict

            # Should not raise
            set_verdict("EURUSD", {"verdict": "EXECUTE"})

            # Cache was still written
            mock_redis.set.assert_called_once()
            # Pub/sub was still attempted
            mock_redis.publish.assert_called_once()

    def test_pubsub_failure_does_not_break_set_verdict(self, mock_redis):
        """Pub/sub failure is logged but doesn't affect cache or stream."""
        mock_redis.publish.side_effect = ConnectionError("Pub/Sub down")
        with patch("storage.l12_cache.redis_client", mock_redis):
            from storage.l12_cache import set_verdict

            # Should not raise
            set_verdict("EURUSD", {"verdict": "EXECUTE"})

            # Cache and stream were still written
            mock_redis.set.assert_called_once()
            mock_redis.xadd.assert_called_once()


class TestSetVerdictAsyncStream:
    """set_verdict_async should also write to Redis Stream."""

    @pytest.mark.asyncio
    async def test_set_verdict_async_writes_stream(self):
        mock_client = MagicMock()
        mock_client.set = MagicMock(return_value=None)
        mock_client.xadd = MagicMock(return_value=None)
        mock_client.publish = MagicMock(return_value=None)

        # Make all methods awaitable

        async def _noop(*a, **kw):
            return None

        mock_client.set.side_effect = _noop
        mock_client.xadd.side_effect = _noop
        mock_client.publish.side_effect = _noop

        with patch("storage.l12_cache.get_client", return_value=mock_client):
            from storage.l12_cache import set_verdict_async

            await set_verdict_async("EURUSD", {"verdict": "EXECUTE"})

            mock_client.xadd.assert_called_once()
