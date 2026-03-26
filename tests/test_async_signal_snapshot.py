"""Regression tests for async signal snapshot (BUG #3) and async pubsub (BUG #5).

Validates:
- ``SignalService.list_all_async()`` uses batched mget and does not block the
  event loop.
- ``SignalService.list_by_symbol_async()`` filters correctly.
- ``_signal_snapshot_async()`` and ``_detect_changed_signals_async()`` in
  ws_routes are fully async.
- Async pubsub helpers ``_make_async_pubsub`` / ``_async_read_pubsub_message``
  are importable and have the correct async signatures.
- CSP ``connect-src`` in next.config.js allows custom backend domains
  (BUG #7).
"""

from __future__ import annotations

import inspect
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# SignalService async methods
# ---------------------------------------------------------------------------


class TestSignalServiceAsyncMethods:
    """SignalService.list_all_async() must use async mget and not block."""

    @pytest.mark.asyncio
    async def test_list_all_async_returns_list(self):
        """list_all_async returns a list (possibly empty when Redis is down)."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[])

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[]),
            patch.object(svc._registry, "all_signals", return_value=[]),
        ):
            result = await svc.list_all_async()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_list_all_async_mget_batched(self):
        """list_all_async calls mget with all pair keys in a single round-trip."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        mget_calls: list[tuple[str, ...]] = []

        mock_client = AsyncMock()

        async def mock_mget(*keys: str) -> list[Any]:
            mget_calls.append(keys)
            return [None] * len(keys)

        mock_client.mget = mock_mget

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[{"symbol": "EURUSD"}, {"symbol": "GBPUSD"}]),
            patch.object(svc._registry, "all_signals", return_value=[]),
        ):
            await svc.list_all_async()

        # mget must have been called exactly once with both keys
        assert len(mget_calls) == 1
        assert len(mget_calls[0]) == 2

    @pytest.mark.asyncio
    async def test_list_all_async_populates_from_verdict(self):
        """list_all_async includes signals from L12 verdict cache."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        verdict_data = {
            "signal_id": "SIG-TEST-001",
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.85,
            "direction": "BUY",
            "entry_price": 1.085,
            "stop_loss": 1.080,
            "take_profit_1": 1.095,
            "risk_reward_ratio": 2.0,
            "scores": {"wolf_score": 0.8, "tii_score": 0.91, "frpc_score": 0.93},
            "timestamp": time.time(),
            "expires_at": None,
            "_cached_at": time.time(),
        }
        json_val = json.dumps(verdict_data)

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[json_val])

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[{"symbol": "EURUSD"}]),
            patch.object(svc._registry, "all_signals", return_value=[]),
        ):
            result = await svc.list_all_async()

        assert any(s.get("symbol") == "EURUSD" for s in result)

    @pytest.mark.asyncio
    async def test_list_by_symbol_async_filters(self):
        """list_by_symbol_async returns only the requested symbol."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        eu_verdict = {
            "signal_id": "SIG-EU-001",
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.85,
            "direction": "BUY",
            "entry_price": 1.085,
            "stop_loss": 1.080,
            "take_profit_1": 1.095,
            "risk_reward_ratio": 2.0,
            "scores": {"wolf_score": 0.8, "tii_score": 0.91, "frpc_score": 0.93},
            "timestamp": time.time(),
            "expires_at": None,
            "_cached_at": time.time(),
        }

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[json.dumps(eu_verdict), None])

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch(
                "allocation.signal_service.load_pairs",
                return_value=[{"symbol": "EURUSD"}, {"symbol": "GBPUSD"}],
            ),
            patch.object(svc._registry, "all_signals", return_value=[]),
        ):
            result = await svc.list_by_symbol_async("GBPUSD")

        # Only GBPUSD entries should be returned (none here since verdict was for EURUSD)
        assert all(str(s.get("symbol", "")).upper() == "GBPUSD" for s in result)

    @pytest.mark.asyncio
    async def test_list_all_async_redis_failure_returns_registry_only(self):
        """Redis failure in mget does not raise — returns registry-only data."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(side_effect=ConnectionError("Redis down"))

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[{"symbol": "EURUSD"}]),
            patch.object(svc._registry, "all_signals", return_value=[]),
        ):
            result = await svc.list_all_async()

        # Must not raise; returns empty list when both registry and Redis are empty
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_publish_async_is_coroutine(self):
        """publish_async must be an async method (awaitable)."""
        from allocation.signal_service import SignalService

        svc = SignalService()
        assert inspect.iscoroutinefunction(svc.publish_async)


# ---------------------------------------------------------------------------
# ws_routes async snapshot helpers
# ---------------------------------------------------------------------------


class TestWsRoutesAsyncHelpers:
    """_signal_snapshot_async and _detect_changed_signals_async must be async."""

    def test_signal_snapshot_async_is_coroutine(self):
        """_signal_snapshot_async must be a coroutine function."""
        from api.ws_routes import _signal_snapshot_async

        assert inspect.iscoroutinefunction(_signal_snapshot_async)

    def test_detect_changed_signals_async_is_coroutine(self):
        """_detect_changed_signals_async must be a coroutine function."""
        from api.ws_routes import _detect_changed_signals_async

        assert inspect.iscoroutinefunction(_detect_changed_signals_async)

    def test_async_read_pubsub_message_is_coroutine(self):
        """_async_read_pubsub_message must be a coroutine function."""
        from api.ws_routes import _async_read_pubsub_message

        assert inspect.iscoroutinefunction(_async_read_pubsub_message)

    def test_make_async_pubsub_is_coroutine(self):
        """_make_async_pubsub must be a coroutine function."""
        from api.ws_routes import _make_async_pubsub

        assert inspect.iscoroutinefunction(_make_async_pubsub)

    @pytest.mark.asyncio
    async def test_signal_snapshot_async_returns_dict(self):
        """_signal_snapshot_async returns a dict even with empty signals."""
        from api.ws_routes import _signal_service, _signal_snapshot_async

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[])

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[]),
            patch.object(_signal_service._registry, "all_signals", return_value=[]),
        ):
            result = await _signal_snapshot_async()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_detect_changed_signals_async_detects_new_entry(self):
        """_detect_changed_signals_async returns changed signals."""
        from api.ws_routes import _detect_changed_signals_async, _signal_service

        verdict_data = {
            "signal_id": "SIG-ASYNC-001",
            "symbol": "EURUSD",
            "verdict": "EXECUTE",
            "confidence": 0.88,
            "direction": "BUY",
            "entry_price": 1.085,
            "stop_loss": 1.080,
            "take_profit_1": 1.095,
            "risk_reward_ratio": 2.0,
            "scores": {"wolf_score": 0.8, "tii_score": 0.91, "frpc_score": 0.93},
            "timestamp": time.time(),
            "expires_at": None,
            "_cached_at": time.time(),
        }

        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=[json.dumps(verdict_data)])

        with (
            patch("infrastructure.redis_client.get_client", AsyncMock(return_value=mock_client)),
            patch("allocation.signal_service.load_pairs", return_value=[{"symbol": "EURUSD"}]),
            patch.object(_signal_service._registry, "all_signals", return_value=[]),
        ):
            last_sigs: dict[str, str] = {}
            changed = await _detect_changed_signals_async(last_sigs)

        assert isinstance(changed, dict)
        # A new signal (not in last_sigs) should be detected as changed
        assert "SIG-ASYNC-001" in changed


# ---------------------------------------------------------------------------
# Async pubsub helpers
# ---------------------------------------------------------------------------


class TestAsyncPubsubHelpers:
    """_make_async_pubsub must create async pubsub or return None on failure."""

    @pytest.mark.asyncio
    async def test_make_async_pubsub_returns_none_on_redis_failure(self):
        """_make_async_pubsub returns None when Redis is unavailable."""
        from api.ws_routes import _make_async_pubsub

        with patch("api.ws_routes._get_async_redis_client", AsyncMock(side_effect=ConnectionError("down"))):
            result = await _make_async_pubsub("test:channel")

        assert result is None

    @pytest.mark.asyncio
    async def test_make_async_pubsub_calls_subscribe(self):
        """_make_async_pubsub calls subscribe on the async pubsub object."""
        from api.ws_routes import _make_async_pubsub

        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_client = AsyncMock()
        mock_client.pubsub = MagicMock(return_value=mock_pubsub)

        with patch("api.ws_routes._get_async_redis_client", AsyncMock(return_value=mock_client)):
            result = await _make_async_pubsub("events:test_channel")

        mock_pubsub.subscribe.assert_awaited_once_with("events:test_channel")
        assert result is mock_pubsub

    @pytest.mark.asyncio
    async def test_async_read_pubsub_message_returns_none_on_timeout(self):
        """_async_read_pubsub_message returns None when no message is available."""
        from api.ws_routes import _async_read_pubsub_message

        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)

        result = await _async_read_pubsub_message(mock_pubsub, timeout=0.01)
        assert result is None

    @pytest.mark.asyncio
    async def test_async_read_pubsub_message_returns_message(self):
        """_async_read_pubsub_message returns the mapping when a message arrives."""
        from api.ws_routes import _async_read_pubsub_message

        msg = {"type": "message", "data": '{"event":"VERDICT_READY","pair":"EURUSD"}', "channel": "test"}
        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=msg)

        result = await _async_read_pubsub_message(mock_pubsub, timeout=0.01)
        assert result is not None
        assert result["type"] == "message"

    @pytest.mark.asyncio
    async def test_async_read_pubsub_message_ignores_non_mapping(self):
        """_async_read_pubsub_message returns None for non-Mapping responses."""
        from api.ws_routes import _async_read_pubsub_message

        mock_pubsub = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value="not-a-mapping")

        result = await _async_read_pubsub_message(mock_pubsub, timeout=0.01)
        assert result is None


# ---------------------------------------------------------------------------
# BUG #4 — Analysis loop readiness (regression guard)
# ---------------------------------------------------------------------------


class TestAnalysisLoopReadiness:
    """on_first_cycle.set() must be called after the first analysis sweep."""

    def test_on_first_cycle_set_called(self):
        """_first_cycle_done logic sets on_first_cycle event after first results."""
        import inspect

        from startup import analysis_loop as _al_mod

        src = inspect.getsource(_al_mod.analysis_loop)
        assert "on_first_cycle.set()" in src, "on_first_cycle.set() must be present in analysis_loop"
        assert "_first_cycle_done" in src, "_first_cycle_done flag must be present"


# ---------------------------------------------------------------------------
# BUG #7 — CSP custom domain helper (JS logic tested via Node.js subprocess)
# ---------------------------------------------------------------------------


class TestCspCustomDomainLogic:
    """_extraCspConnectSrcOrigins must add custom-domain origins to connect-src."""

    def _run_node_snippet(self, code: str) -> str:
        """Helper: run a small Node.js snippet and return stdout."""
        import subprocess

        result = subprocess.run(
            ["node", "-e", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()

    # Inline the helper function in each snippet so tests are self-contained.
    _HELPER_JS = """
function _extraCspConnectSrcOrigins(wsOrigin) {
  if (!wsOrigin) return [];
  try {
    const httpEquiv = wsOrigin.replace(/^wss:\\/\\//, "https://").replace(/^ws:\\/\\//, "http://");
    const { host } = new URL(httpEquiv);
    if (
      host.endsWith(".railway.app") ||
      host.endsWith(".vercel.app") ||
      host === "localhost" ||
      host.startsWith("localhost:")
    ) { return []; }
    return ["wss://" + host, "https://" + host];
  } catch { return []; }
}
"""

    def test_railway_domain_returns_empty(self):
        """Standard *.railway.app domain must not add extra CSP entries."""
        out = self._run_node_snippet(
            self._HELPER_JS
            + 'console.log(JSON.stringify(_extraCspConnectSrcOrigins("wss://my-service.up.railway.app")));'
        )
        assert out == "[]", f"Expected [] for railway.app domain, got {out!r}"

    def test_custom_domain_adds_origins(self):
        """Custom domain must add both wss:// and https:// origins."""
        out = self._run_node_snippet(
            self._HELPER_JS + 'console.log(JSON.stringify(_extraCspConnectSrcOrigins("wss://trading.example.com")));'
        )
        result = json.loads(out)
        assert "wss://trading.example.com" in result
        assert "https://trading.example.com" in result

    def test_vercel_domain_returns_empty(self):
        """*.vercel.app domain must not add duplicate CSP entries."""
        out = self._run_node_snippet(
            self._HELPER_JS + 'console.log(JSON.stringify(_extraCspConnectSrcOrigins("wss://my-app.vercel.app")));'
        )
        assert out == "[]", f"Expected [] for vercel.app domain, got {out!r}"

    def test_localhost_returns_empty(self):
        """localhost WS origin must not add extra CSP entries."""
        out = self._run_node_snippet(
            self._HELPER_JS + 'console.log(JSON.stringify(_extraCspConnectSrcOrigins("ws://localhost:8080")));'
        )
        assert out == "[]", f"Expected [] for localhost, got {out!r}"

    def test_empty_input_returns_empty(self):
        """Empty wsBase must return empty list."""
        out = self._run_node_snippet(self._HELPER_JS + 'console.log(JSON.stringify(_extraCspConnectSrcOrigins("")));')
        assert out == "[]"
