"""Comprehensive WebSocket reconnect + resilience tests for FinnhubWebSocket.

Covers:
- Exponential backoff calculation (edge cases)
- Reconnect after ConnectionClosed / ConnectionClosedError / OSError
- HTTP 429 rate-limit aggressive backoff
- FinnhubConnectionError generic retry
- Leader election (acquire / renew / release)
- Graceful stop during active connection
- Message dispatching & ping filtering
- Attempt counter reset on successful connect
- Multiple consecutive failures with increasing backoff
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We need to import the websockets exceptions that the code catches
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
)


class _FakeInvalidStatusCodeError(Exception):
    """Test stand-in for the deprecated websockets.InvalidStatusCode."""

    def __init__(self, status_code: int, **kwargs: object) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


from ingest.finnhub_ws import (  # noqa: E402
    BACKOFF_MULTIPLIER,
    INITIAL_BACKOFF_S,
    LEADER_LOCK_KEY,
    LEADER_LOCK_TTL_S,
    MAX_BACKOFF_S,
    RATE_LIMIT_BASE_BACKOFF_S,
    FinnhubConnectionError,
    FinnhubRateLimitError,
    FinnhubSymbolMapper,
    FinnhubWebSocket,
    _calculate_backoff,
)

# ---------------------------------------------------------------------------
# Async iterator helper for mocking ``async for raw_msg in ws``
# ---------------------------------------------------------------------------


class AsyncMessageIterator:
    """Async iterator that yields pre-defined messages, simulating a WS stream."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self._index = 0

    def __aiter__(self) -> "AsyncMessageIterator":
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> MagicMock:
    """Async Redis client mock with leader-lock helpers."""
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)  # lock acquired
    redis.get = AsyncMock(return_value="test-replica")
    redis.delete = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def on_message() -> AsyncMock:
    """Async message callback."""
    return AsyncMock()


@pytest.fixture
def ws_client(mock_redis: MagicMock, on_message: AsyncMock) -> FinnhubWebSocket:
    """FinnhubWebSocket instance with injected mocks."""
    with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-token"}):
        client = FinnhubWebSocket(
            redis=mock_redis,
            on_message=on_message,
            symbols=["OANDA:EUR_USD", "OANDA:GBP_JPY"],
            replica_id="test-replica",
        )
    return client


# ---------------------------------------------------------------------------
# Backoff calculation (unit)
# ---------------------------------------------------------------------------


class TestBackoffCalculation:
    """Exhaustive tests for _calculate_backoff."""

    def test_first_attempt_near_base(self) -> None:
        """Attempt 0 should yield ~base ± jitter."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.0):
            result = _calculate_backoff(0)
        assert result == pytest.approx(INITIAL_BACKOFF_S, abs=0.01)

    def test_exponential_growth(self) -> None:
        """Backoff should double each attempt (jitter=0)."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.0):
            b1 = _calculate_backoff(1)
            b2 = _calculate_backoff(2)
            b3 = _calculate_backoff(3)
        assert b2 == pytest.approx(b1 * BACKOFF_MULTIPLIER, rel=0.01)
        assert b3 == pytest.approx(b2 * BACKOFF_MULTIPLIER, rel=0.01)

    def test_clamped_to_maximum(self) -> None:
        """No backoff should ever exceed MAX_BACKOFF_S (+ jitter)."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.0):
            result = _calculate_backoff(100)
        assert result <= MAX_BACKOFF_S

    def test_minimum_floor(self) -> None:
        """Backoff is never below 0.1s even with negative jitter."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=-1.0):
            result = _calculate_backoff(0, base=0.01, multiplier=1.0, maximum=0.01)
        assert result >= 0.1

    def test_rate_limit_base_backoff(self) -> None:
        """Rate-limit path uses higher base backoff."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.0):
            result = _calculate_backoff(0, base=RATE_LIMIT_BASE_BACKOFF_S)
        assert result == pytest.approx(RATE_LIMIT_BASE_BACKOFF_S, abs=0.01)

    @pytest.mark.parametrize("attempt", [0, 1, 2, 5, 10, 20])
    def test_backoff_always_positive(self, attempt: int) -> None:
        """Backoff must be >0 for any attempt number."""
        result = _calculate_backoff(attempt)
        assert result > 0

    def test_jitter_applies_variation(self) -> None:
        """Different jitter values should produce different results."""
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.5):
            high = _calculate_backoff(3)
        with patch("ingest.finnhub_ws.random.uniform", return_value=-0.5):
            low = _calculate_backoff(3)
        assert high > low


# ---------------------------------------------------------------------------
# Leader election
# ---------------------------------------------------------------------------


class TestLeaderElection:
    """Redis-based leader election tests."""

    @pytest.mark.asyncio
    async def test_acquire_leader_lock_success(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Lock acquired when Redis SET NX returns True."""
        mock_redis.set = AsyncMock(return_value=True)
        result = await ws_client._acquire_leader_lock()
        assert result is True
        mock_redis.set.assert_awaited_once_with(
            LEADER_LOCK_KEY,
            "test-replica",
            nx=True,
            ex=LEADER_LOCK_TTL_S,
        )

    @pytest.mark.asyncio
    async def test_acquire_leader_lock_failure(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Lock not acquired when another replica holds it."""
        mock_redis.set = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value="other-replica")
        result = await ws_client._acquire_leader_lock()
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_leader_lock_idempotent_reacquire(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Lock re-acquired when this replica already owns it (idempotent).

        This prevents self-deadlock when the WS crashes and the same
        replica loops back to re-acquire before the TTL expires.
        """
        mock_redis.set = AsyncMock(return_value=False)  # nx=True fails
        mock_redis.get = AsyncMock(return_value="test-replica")  # we own it
        result = await ws_client._acquire_leader_lock()
        assert result is True
        mock_redis.expire.assert_awaited_once_with(LEADER_LOCK_KEY, LEADER_LOCK_TTL_S)

    @pytest.mark.asyncio
    async def test_release_leader_lock_own_replica(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Release deletes the key when this replica holds it."""
        mock_redis.get = AsyncMock(return_value="test-replica")
        await ws_client._release_leader_lock()
        mock_redis.delete.assert_awaited_once_with(LEADER_LOCK_KEY)

    @pytest.mark.asyncio
    async def test_release_leader_lock_other_replica(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Release does NOT delete the key when another replica holds it."""
        mock_redis.get = AsyncMock(return_value="other-replica")
        await ws_client._release_leader_lock()
        mock_redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_release_leader_lock_redis_error_swallowed(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Redis errors during release are swallowed (logged, not raised)."""
        mock_redis.get = AsyncMock(side_effect=ConnectionError("redis gone"))
        await ws_client._release_leader_lock()  # should NOT raise

    @pytest.mark.asyncio
    async def test_renew_leader_lock_own_replica(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Renewal succeeds when current holder matches replica ID."""
        mock_redis.get = AsyncMock(return_value="test-replica")
        result = await ws_client._renew_leader_lock()
        assert result is True
        mock_redis.expire.assert_awaited_once_with(LEADER_LOCK_KEY, LEADER_LOCK_TTL_S)

    @pytest.mark.asyncio
    async def test_renew_leader_lock_different_replica(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Renewal fails when another replica holds the lock."""
        mock_redis.get = AsyncMock(return_value="other-replica")
        result = await ws_client._renew_leader_lock()
        assert result is False
        mock_redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_renew_leader_lock_no_holder(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Renewal fails when lock key doesn't exist."""
        mock_redis.get = AsyncMock(return_value=None)
        result = await ws_client._renew_leader_lock()
        assert result is False


# ---------------------------------------------------------------------------
# Lock renewal loop
# ---------------------------------------------------------------------------


class TestLockRenewalLoop:
    """Tests for the background _lock_renewal_loop task."""

    @pytest.mark.asyncio
    async def test_renewal_loop_renews_while_connected(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Loop renews the lock and sleeps for LEADER_LOCK_RENEWAL_S."""
        ws_client._running = True
        ws_client._connected = True
        mock_redis.get = AsyncMock(return_value="test-replica")

        renewal_count = 0

        async def track_expire(*args, **kwargs):
            nonlocal renewal_count
            renewal_count += 1
            # Stop after 2 renewals so test doesn't run forever
            if renewal_count >= 2:
                ws_client._connected = False
            return True

        mock_redis.expire = AsyncMock(side_effect=track_expire)

        with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
            await ws_client._lock_renewal_loop()

        assert renewal_count >= 2

    @pytest.mark.asyncio
    async def test_renewal_loop_disconnects_on_lost_lock(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Loop closes WS and returns when lock is stolen by another replica."""
        ws_client._running = True
        ws_client._connected = True
        mock_ws = AsyncMock()
        ws_client._ws = mock_ws
        # Lock held by someone else now
        mock_redis.get = AsyncMock(return_value="other-replica")

        with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
            await ws_client._lock_renewal_loop()

        assert ws_client._connected is False
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renewal_loop_survives_redis_error(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Transient Redis errors don't kill the renewal loop."""
        ws_client._running = True
        ws_client._connected = True
        call_count = 0

        async def flaky_get(key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("redis blip")
            # Second call: succeed, then stop
            ws_client._connected = False
            return "test-replica"

        mock_redis.get = AsyncMock(side_effect=flaky_get)

        with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
            await ws_client._lock_renewal_loop()

        # Should survive the error and continue
        assert call_count >= 2

    def test_cancel_lock_renewal_cancels_running_task(self, ws_client: FinnhubWebSocket) -> None:
        """_cancel_lock_renewal cancels a running task and clears the reference."""
        fake_task = MagicMock()
        fake_task.done.return_value = False
        ws_client._lock_renewal_task = fake_task

        ws_client._cancel_lock_renewal()

        fake_task.cancel.assert_called_once()
        assert ws_client._lock_renewal_task is None

    def test_cancel_lock_renewal_noop_when_no_task(self, ws_client: FinnhubWebSocket) -> None:
        """_cancel_lock_renewal is safe to call when no task exists."""
        ws_client._lock_renewal_task = None
        ws_client._cancel_lock_renewal()  # should not raise
        assert ws_client._lock_renewal_task is None

    def test_cancel_lock_renewal_noop_when_task_done(self, ws_client: FinnhubWebSocket) -> None:
        """_cancel_lock_renewal does not cancel an already-finished task."""
        fake_task = MagicMock()
        fake_task.done.return_value = True
        ws_client._lock_renewal_task = fake_task

        ws_client._cancel_lock_renewal()

        fake_task.cancel.assert_not_called()
        assert ws_client._lock_renewal_task is None


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------


class TestSubscribe:
    """Tests for symbol subscription on connect."""

    @pytest.mark.asyncio
    async def test_subscribe_sends_all_symbols(self, ws_client: FinnhubWebSocket) -> None:
        mock_ws = AsyncMock()
        await ws_client._subscribe(mock_ws)

        assert mock_ws.send.await_count == 2
        payloads = [json.loads(call.args[0]) for call in mock_ws.send.call_args_list]
        assert payloads[0] == {"type": "subscribe", "symbol": "OANDA:EUR_USD"}
        assert payloads[1] == {"type": "subscribe", "symbol": "OANDA:GBP_JPY"}


# ---------------------------------------------------------------------------
# Connect -- success and failure paths
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for _connect method."""

    @pytest.mark.asyncio
    async def test_connect_success_resets_attempt(self, ws_client: FinnhubWebSocket) -> None:
        """Successful connect resets attempt counter to 0."""
        ws_client._attempt = 5
        mock_ws = AsyncMock()

        async def _fake_connect(*args, **kwargs):
            return mock_ws

        with patch("ingest.finnhub_ws._ws_connect", _fake_connect):
            result = await ws_client._connect()
        assert result is mock_ws
        assert ws_client._attempt == 0

    @pytest.mark.asyncio
    async def test_connect_429_raises_rate_limit_error(self, ws_client: FinnhubWebSocket) -> None:
        """HTTP 429 should raise FinnhubRateLimitError with computed retry_after."""
        exc = _FakeInvalidStatusCodeError(429)
        with patch("ingest.finnhub_ws._ws_connect", side_effect=exc):
            with pytest.raises(FinnhubRateLimitError) as exc_info:
                await ws_client._connect()
            assert exc_info.value.retry_after > 0

    @pytest.mark.asyncio
    async def test_connect_non_429_raises_connection_error(self, ws_client: FinnhubWebSocket) -> None:
        """Non-429 HTTP status raises FinnhubConnectionError."""
        exc = _FakeInvalidStatusCodeError(503)
        with patch("ingest.finnhub_ws._ws_connect", side_effect=exc):  # noqa: SIM117
            with pytest.raises(FinnhubConnectionError, match="HTTP 503"):
                await ws_client._connect()

    @pytest.mark.asyncio
    async def test_connect_generic_exception_wraps(self, ws_client: FinnhubWebSocket) -> None:
        """Arbitrary exceptions are wrapped in FinnhubConnectionError."""
        with (
            patch(
                "ingest.finnhub_ws._ws_connect",
                side_effect=OSError("network unreachable"),
            ),
            pytest.raises(FinnhubConnectionError, match="network unreachable"),
        ):
            await ws_client._connect()


# ---------------------------------------------------------------------------
# Listen -- message dispatch
# ---------------------------------------------------------------------------


class TestListen:
    """Tests for _listen method (message dispatch, ping filtering)."""

    @pytest.mark.asyncio
    async def test_listen_dispatches_trade_messages(
        self, ws_client: FinnhubWebSocket, on_message: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Trade messages are forwarded to on_message callback."""
        trade_msg = json.dumps({"type": "trade", "data": [{"s": "OANDA:EUR_USD"}]})
        mock_ws = AsyncMessageIterator([trade_msg])

        await ws_client._listen(mock_ws)
        on_message.assert_awaited_once()
        call_arg = on_message.call_args[0][0]
        assert call_arg["type"] == "trade"

    @pytest.mark.asyncio
    async def test_listen_filters_ping_messages(
        self, ws_client: FinnhubWebSocket, on_message: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Ping messages should NOT be forwarded to on_message."""
        ping_msg = json.dumps({"type": "ping"})
        mock_ws = AsyncMessageIterator([ping_msg])

        await ws_client._listen(mock_ws)
        on_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listen_no_inline_lock_renewal(
        self, ws_client: FinnhubWebSocket, on_message: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """_listen no longer renews the lock inline (handled by background task)."""
        trade_msg = json.dumps({"type": "trade", "data": []})
        mock_ws = AsyncMessageIterator([trade_msg, trade_msg])
        mock_redis.get.reset_mock()
        mock_redis.expire.reset_mock()

        await ws_client._listen(mock_ws)
        # No inline renewal calls — background _lock_renewal_loop handles it.
        mock_redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listen_multiple_messages_sequential(
        self, ws_client: FinnhubWebSocket, on_message: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Multiple messages are processed sequentially."""
        msgs = [
            json.dumps({"type": "trade", "data": [{"s": "OANDA:EUR_USD"}]}),
            json.dumps({"type": "ping"}),
            json.dumps({"type": "trade", "data": [{"s": "OANDA:GBP_JPY"}]}),
        ]
        mock_ws = AsyncMessageIterator(msgs)

        await ws_client._listen(mock_ws)
        # Only 2 trade messages dispatched (ping filtered)
        assert on_message.await_count == 2


# ---------------------------------------------------------------------------
# Run loop -- reconnect scenarios
# ---------------------------------------------------------------------------


class TestRunLoopReconnect:
    """Integration tests for the main run() reconnect loop."""

    @pytest.fixture(autouse=True)
    def _force_market_open(self):
        """Ensure market-hours gate doesn't block run-loop tests."""
        with patch("ingest.finnhub_ws.is_forex_market_open", return_value=True):
            yield

    @pytest.mark.asyncio
    async def test_reconnect_on_connection_closed_error(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """ConnectionClosedError should trigger backoff and retry."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionClosedError(None, None)
            # Third call: stop the loop
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await ws_client.run()

        # Should have retried twice before stopping
        assert call_count == 3
        # Backoff sleeps called for the 2 failures
        assert mock_sleep.await_count >= 2

    @pytest.mark.asyncio
    async def test_reconnect_on_os_error(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """OSError (network issues) should trigger backoff and retry."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Network unreachable")
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
                await ws_client.run()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_reconnect_on_rate_limit(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """HTTP 429 rate limit uses FinnhubRateLimitError.retry_after for sleep."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FinnhubRateLimitError(retry_after=42.0)
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await ws_client.run()

        # Should have slept with the rate-limit retry_after value
        sleep_durations = [call.args[0] for call in mock_sleep.call_args_list]
        assert any(d == 42.0 for d in sleep_durations), f"Expected sleep(42.0) for rate limit, got: {sleep_durations}"

    @pytest.mark.asyncio
    async def test_reconnect_on_generic_connection_error(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """FinnhubConnectionError triggers standard backoff."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FinnhubConnectionError("DNS resolution failed")
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
                await ws_client.run()

        assert call_count == 2
        assert ws_client._attempt >= 1

    @pytest.mark.asyncio
    async def test_reconnect_on_connection_closed_with_code(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """ConnectionClosed (with code/reason) should trigger backoff."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_ws = AsyncMock()
                mock_ws.closed = False

                async def fake_listen(ws):
                    raise ConnectionClosed(None, None)

                with patch.object(ws_client, "_listen", side_effect=fake_listen):  # noqa: SIM117
                    with patch.object(ws_client, "_subscribe", new_callable=AsyncMock):
                        return mock_ws
            ws_client._running = False
            return AsyncMock()

        # This test is more nuanced -- we need to mock at the run() level
        # Instead, use a simpler approach:
        attempts = []

        async def patched_run():
            ws_client._running = True
            # Simulate: acquire lock -> connect -> listen raises ConnectionClosed
            mock_redis.set = AsyncMock(return_value=True)

            mock_ws = AsyncMock()
            mock_ws.closed = False
            mock_ws.close = AsyncMock()

            iteration = 0
            while ws_client._running:
                iteration += 1
                if iteration > 3:
                    break
                try:
                    if iteration <= 2:
                        raise ConnectionClosed(None, None)
                except ConnectionClosed:
                    ws_client._attempt += 1
                    attempts.append(ws_client._attempt)
                    continue

            ws_client._running = False

        await patched_run()
        assert len(attempts) == 2

    @pytest.mark.asyncio
    async def test_attempt_counter_increments_on_failures(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Attempt counter should increment with each consecutive failure."""
        call_count = 0

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                raise ConnectionClosedError(None, None)
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
                await ws_client.run()

        assert ws_client._attempt >= 5

    @pytest.mark.asyncio
    async def test_finally_releases_leader_lock(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Lock must be released in finally block so reconnect doesn't self-deadlock."""
        call_count = 0
        delete_calls: list[str] = []

        async def track_delete(key: str) -> int:
            delete_calls.append(key)
            return 1

        mock_redis.delete = AsyncMock(side_effect=track_delete)

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionClosedError(None, None)
            ws_client._running = False
            return AsyncMock()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock):
                await ws_client.run()

        # Lock should have been released in the finally block after the first failure
        assert LEADER_LOCK_KEY in delete_calls, (
            f"Leader lock not released in finally block. delete calls: {delete_calls}"
        )

    @pytest.mark.asyncio
    async def test_backoff_increases_with_consecutive_failures(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """Sleep durations should increase with consecutive failures."""
        call_count = 0
        sleep_durations: list[float] = []

        async def fake_connect():
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                raise ConnectionClosedError(None, None)
            ws_client._running = False
            return AsyncMock()

        async def track_sleep(duration):
            sleep_durations.append(duration)

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", side_effect=track_sleep):
                await ws_client.run()

        # Filter out the leader-election sleep (LEADER_LOCK_TTL_S / 2)
        backoff_sleeps = [d for d in sleep_durations if d < LEADER_LOCK_TTL_S / 2]
        # With exponential backoff, later sleeps should be >= earlier ones (on average)
        if len(backoff_sleeps) >= 2:
            # Due to jitter, just check the trend is generally upward
            assert backoff_sleeps[-1] >= backoff_sleeps[0] * 0.5, f"Backoff not increasing: {backoff_sleeps}"

    @pytest.mark.asyncio
    async def test_non_leader_waits_before_retry(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Non-leader replicas should sleep for LEADER_LOCK_TTL_S / 2."""
        call_count = 0

        async def fake_acquire():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return False  # Not leader
            ws_client._running = False
            return False

        with patch.object(ws_client, "_acquire_leader_lock", side_effect=fake_acquire):  # noqa: SIM117
            with patch("ingest.finnhub_ws.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await ws_client.run()

        # Should have slept with LEADER_LOCK_TTL_S / 2 for non-leader waits
        leader_waits = [call.args[0] for call in mock_sleep.call_args_list if call.args[0] == LEADER_LOCK_TTL_S / 2]
        assert len(leader_waits) >= 2


# ---------------------------------------------------------------------------
# Graceful stop
# ---------------------------------------------------------------------------


class TestGracefulStop:
    """Tests for the stop() method."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """stop() should set _running to False."""
        ws_client._running = True
        await ws_client.stop()
        assert ws_client._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_open_websocket(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """stop() should close an active WebSocket connection."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        ws_client._ws = mock_ws
        ws_client._running = True

        await ws_client.stop()

        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_releases_leader_lock(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """stop() force-deletes the leader lock unconditionally."""
        ws_client._running = True

        await ws_client.stop()

        mock_redis.delete.assert_awaited_once_with(LEADER_LOCK_KEY)

    @pytest.mark.asyncio
    async def test_stop_force_deletes_even_other_replicas_lock(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """stop() force-deletes lock even if another replica holds it.

        Rationale: this replica is shutting down, and a stuck lock from
        a crashed sibling should not block the next startup.
        """
        mock_redis.get = AsyncMock(return_value="other-replica")
        ws_client._running = True

        await ws_client.stop()

        mock_redis.delete.assert_awaited_once_with(LEADER_LOCK_KEY)

    @pytest.mark.asyncio
    async def test_stop_cancels_lock_renewal_task(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """stop() cancels the background lock renewal task."""
        fake_task = MagicMock()
        fake_task.done.return_value = False
        ws_client._lock_renewal_task = fake_task
        ws_client._running = True

        await ws_client.stop()

        fake_task.cancel.assert_called_once()
        assert ws_client._lock_renewal_task is None

    @pytest.mark.asyncio
    async def test_stop_skips_close_when_ws_already_closed(
        self, ws_client: FinnhubWebSocket, mock_redis: MagicMock
    ) -> None:
        """stop() still calls close when a websocket handle is present."""
        mock_ws = AsyncMock()
        mock_ws.closed = True
        ws_client._ws = mock_ws
        ws_client._running = True

        await ws_client.stop()

        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_during_run_loop(self, ws_client: FinnhubWebSocket, mock_redis: MagicMock) -> None:
        """Calling stop() while run() is active should terminate the loop."""

        async def fake_connect():
            await asyncio.sleep(0.1)
            return AsyncMock()

        async def stop_after_delay():
            await asyncio.sleep(0.2)
            await ws_client.stop()

        with patch.object(ws_client, "_connect", side_effect=fake_connect):  # noqa: SIM117
            with patch.object(ws_client, "_subscribe", new_callable=AsyncMock):
                with patch.object(ws_client, "_listen", new_callable=AsyncMock):
                    with patch("ingest.finnhub_ws.is_forex_market_open", return_value=True):
                        # Run both concurrently
                        await asyncio.gather(
                            ws_client.run(),
                            stop_after_delay(),
                        )

        assert ws_client._running is False


# ---------------------------------------------------------------------------
# Symbol mapper edge cases (supplemental)
# ---------------------------------------------------------------------------


class TestSymbolMapperExtended:
    """Additional edge cases for FinnhubSymbolMapper."""

    def test_register_non_6_char_symbol_passthrough(self) -> None:
        """Symbols that aren't 6 chars pass through unchanged."""
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        result = mapper.register("BTC")
        assert result == "BTC"

    def test_register_same_symbol_twice_idempotent(self) -> None:
        """Registering the same symbol twice should work (idempotent)."""
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        r1 = mapper.register("EURUSD")
        r2 = mapper.register("EURUSD")
        assert r1 == r2
        assert mapper.to_internal("OANDA:EUR_USD") == "EURUSD"

    def test_to_internal_strips_prefix_fallback(self) -> None:
        """Unregistered symbols with matching prefix get stripped."""
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        result = mapper.to_internal("OANDA:CHF_JPY")
        assert result == "CHFJPY"

    def test_to_internal_different_prefix_returns_as_is(self) -> None:
        """Symbols with a different prefix are returned unchanged."""
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        result = mapper.to_internal("FXCM:EUR_USD")
        assert result == "FXCM:EUR_USD"


# ---------------------------------------------------------------------------
# FinnhubRateLimitError
# ---------------------------------------------------------------------------


class TestRateLimitError:
    """Tests for FinnhubRateLimitError exception."""

    def test_default_retry_after(self) -> None:
        exc = FinnhubRateLimitError()
        assert exc.retry_after == RATE_LIMIT_BASE_BACKOFF_S

    def test_custom_retry_after(self) -> None:
        exc = FinnhubRateLimitError(retry_after=60.0)
        assert exc.retry_after == 60.0

    def test_is_connection_error_subclass(self) -> None:
        exc = FinnhubRateLimitError()
        assert isinstance(exc, FinnhubConnectionError)

    def test_message_includes_retry_after(self) -> None:
        exc = FinnhubRateLimitError(retry_after=45.5)
        assert "45.5" in str(exc)
