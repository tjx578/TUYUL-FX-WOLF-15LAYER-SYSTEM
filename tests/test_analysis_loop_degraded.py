"""Tests for degraded verdict writing in the analysis loop.

Validates that _build_degraded_verdict and the fallback paths in
_analyze_pair always produce a Redis-writable verdict so the
dashboard never sees zero verdicts when the engine is running.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _mock_tracing():
    """Stub the tracing module so it doesn't require OTel runtime."""
    mock_tracer = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.set_attribute = MagicMock()
    ctx.record_exception = MagicMock()
    mock_tracer.start_as_current_span.return_value = ctx
    with patch("startup.analysis_loop._engine_tracer", mock_tracer):
        yield


class TestBuildDegradedVerdict:
    """_build_degraded_verdict must produce a well-formed cache payload."""

    def test_contains_required_keys(self):
        from startup.analysis_loop import _build_degraded_verdict

        v = _build_degraded_verdict("EURUSD", "PIPELINE_TIMEOUT:30s")
        assert v["symbol"] == "EURUSD"
        assert v["verdict"] == "HOLD"
        assert v["wolf_status"] == "DEGRADED"
        assert v["confidence"] == 0.0
        assert v["direction"] == "HOLD"
        assert isinstance(v["timestamp"], float)
        assert v["errors"] == ["PIPELINE_TIMEOUT:30s"]
        assert v["last_hold_block_reason"] == "PIPELINE_TIMEOUT:30s"
        assert v["system"]["degraded"] is True
        assert v["system"]["degraded_reason"] == "PIPELINE_TIMEOUT:30s"

    def test_signal_id_has_deg_prefix(self):
        from startup.analysis_loop import _build_degraded_verdict

        v = _build_degraded_verdict("GBPUSD", "TEST")
        assert v["signal_id"].startswith("DEG-GBPUSD-")

    def test_serializable_to_json(self):
        import json

        from startup.analysis_loop import _build_degraded_verdict

        v = _build_degraded_verdict("XAUUSD", "PIPELINE_ERROR:ValueError")
        # Must not raise
        serialized = json.dumps(v)
        assert '"DEGRADED"' in serialized


class TestAnalyzePairDegradedFallback:
    """_analyze_pair must write degraded verdict on failure paths."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_tracing")
    async def test_timeout_writes_degraded(self):
        """Pipeline timeout → degraded verdict written to Redis."""
        mock_pipeline = MagicMock()

        written = {}

        def _capture_set_verdict(pair, data):
            written[pair] = data

        with (
            patch("context.live_context_bus.LiveContextBus") as mock_bus_cls,
            patch("startup.analysis_loop.set_verdict", side_effect=_capture_set_verdict),
            patch("startup.analysis_loop._PIPELINE_TIMEOUT_SEC", 0.01),
            patch("startup.analysis_loop.VERDICT_PATH_EVENT_TOTAL", MagicMock()),
        ):
            mock_bus = MagicMock()
            mock_bus.get_latest_tick.return_value = None
            mock_bus_cls.return_value = mock_bus

            # Simulate timeout by making to_thread block
            async def _blocking_thread(fn):
                await asyncio.sleep(999)

            with patch("asyncio.to_thread", _blocking_thread):
                from startup.analysis_loop import _analyze_pair

                result = await asyncio.wait_for(_analyze_pair("EURUSD", mock_pipeline), timeout=5.0)

            assert result is None
            assert "EURUSD" in written
            assert written["EURUSD"]["wolf_status"] == "DEGRADED"
            assert "PIPELINE_TIMEOUT" in written["EURUSD"]["errors"][0]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_tracing")
    async def test_exception_writes_degraded(self):
        """Pipeline exception → degraded verdict written to Redis."""
        mock_pipeline = MagicMock()

        written = {}

        def _capture_set_verdict(pair, data):
            written[pair] = data

        with (
            patch("context.live_context_bus.LiveContextBus") as mock_bus_cls,
            patch("startup.analysis_loop.set_verdict", side_effect=_capture_set_verdict),
            patch("startup.analysis_loop.VERDICT_PATH_EVENT_TOTAL", MagicMock()),
        ):
            mock_bus = MagicMock()
            mock_bus.get_latest_tick.return_value = None
            mock_bus_cls.return_value = mock_bus

            async def _raise_thread(fn):
                raise RuntimeError("Simulated crash")

            with patch("asyncio.to_thread", _raise_thread):
                from startup.analysis_loop import _analyze_pair

                result = await _analyze_pair("GBPUSD", mock_pipeline)

            assert result is None
            assert "GBPUSD" in written
            assert written["GBPUSD"]["wolf_status"] == "DEGRADED"
            assert "PIPELINE_ERROR:RuntimeError" in written["GBPUSD"]["errors"][0]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_tracing")
    async def test_abort_result_skips_set_verdict(self):
        """Pipeline ABORT (verdict=None) → set_verdict must NOT be called."""
        mock_pipeline = MagicMock()
        # Simulate the exact ABORT payload the pipeline produces on warmup rejection:
        # result is a non-empty dict (truthy) but result["verdict"] is explicitly None.
        # Note: l12_verdict is present because _early_exit() populates it with a HOLD
        # before the warmup gate appends result["verdict"]=None as the abort signal.
        abort_result = {
            "verdict": None,  # explicit ABORT signal — pipeline ran no analysis
            "errors": ["WARMUP_INSUFFICIENT:17_bars_missing"],
            "l12_verdict": {"verdict": "HOLD", "confidence": "LOW"},
            "synthesis": {},
            "warmup": {"ready": False, "bars": 3, "required": 20, "missing": 17},
        }

        set_verdict_calls: list = []

        with (
            patch("context.live_context_bus.LiveContextBus") as mock_bus_cls,
            patch("startup.analysis_loop.set_verdict", side_effect=lambda p, d: set_verdict_calls.append((p, d))),
            patch("startup.analysis_loop.VERDICT_PATH_EVENT_TOTAL", MagicMock()),
            patch("startup.analysis_loop.LatencyTracker") as mock_lt,
        ):
            mock_bus = MagicMock()
            mock_bus.get_latest_tick.return_value = None
            mock_bus_cls.return_value = mock_bus
            mock_lt.return_value = MagicMock()

            async def _return_abort(fn):
                return abort_result

            with patch("asyncio.to_thread", _return_abort):
                from startup.analysis_loop import _analyze_pair

                result = await _analyze_pair("EURUSD", mock_pipeline)

        # _analyze_pair must return None so the pair is retried next cycle
        assert result is None
        # set_verdict must NOT be called — no stale/empty verdict should be written
        assert set_verdict_calls == [], f"set_verdict was unexpectedly called: {set_verdict_calls}"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_tracing")
    async def test_persist_failure_falls_back_to_degraded(self):
        """set_verdict fails for rich payload → falls back to degraded verdict."""
        mock_pipeline = MagicMock()
        fake_result = {
            "synthesis": {"scores": {}, "layers": {}, "execution": {}, "system": {}},
            "l12_verdict": {"verdict": "EXECUTE", "confidence": 0.85},
        }

        call_count = 0
        written = {}

        def _failing_then_ok(pair, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis down on first try")
            written[pair] = data

        with (
            patch("context.live_context_bus.LiveContextBus") as mock_bus_cls,
            patch("startup.analysis_loop.set_verdict", side_effect=_failing_then_ok),
            patch("startup.analysis_loop.VERDICT_PATH_EVENT_TOTAL", MagicMock()),
            patch("startup.analysis_loop.LatencyTracker") as mock_lt,
        ):
            mock_bus = MagicMock()
            mock_bus.get_latest_tick.return_value = None
            mock_bus_cls.return_value = mock_bus
            mock_lt.return_value = MagicMock()

            async def _return_result(fn):
                return fake_result

            with patch("asyncio.to_thread", _return_result):
                from startup.analysis_loop import _analyze_pair

                result = await _analyze_pair("EURUSD", mock_pipeline)

            # Pipeline returned result, but first set_verdict failed
            assert result == fake_result
            # Fallback degraded was written on second call
            assert "EURUSD" in written
            assert written["EURUSD"]["wolf_status"] == "DEGRADED"
            assert "PERSIST_ERROR" in written["EURUSD"]["errors"][0]


class TestBuildVerdictCachePayload:
    """_build_verdict_cache_payload handles all pipeline result shapes."""

    def test_empty_l12_verdict_produces_hold(self):
        from startup.analysis_loop import _build_verdict_cache_payload

        result = {
            "synthesis": {},
            "l12_verdict": {},
            "execution_map": {},
            "governance": {},
        }
        payload = _build_verdict_cache_payload("EURUSD", result)
        assert payload["verdict"] == "HOLD"
        assert payload["confidence"] == 0.0
        assert payload["wolf_status"] == "NO_HUNT"
        assert payload["symbol"] == "EURUSD"

    def test_warmup_early_exit_produces_valid_payload(self):
        from startup.analysis_loop import _build_verdict_cache_payload

        # Simulates what pipeline._early_exit returns
        result = {
            "synthesis": {
                "scores": {"wolf_30_point": 0, "f_score": 0},
                "layers": {},
                "execution": {"direction": "HOLD"},
                "system": {"latency_ms": 5.0},
            },
            "l12_verdict": {
                "verdict": "HOLD",
                "confidence": "LOW",
                "wolf_status": "NO_HUNT",
                "gates": {"passed": 0, "total": 9},
            },
            "execution_map": {},
            "governance": {},
            "errors": ["WARMUP_INSUFFICIENT:15_bars_missing"],
        }
        payload = _build_verdict_cache_payload("EURUSD", result)
        assert payload["verdict"] == "HOLD"
        assert payload["errors"] == ["WARMUP_INSUFFICIENT:15_bars_missing"]
        assert payload["last_hold_block_reason"] == "WARMUP_INSUFFICIENT:15_bars_missing"
        assert payload["confidence"] == 0.25  # LOW → 0.25

    def test_string_confidence_mapped_correctly(self):
        from startup.analysis_loop import _build_verdict_cache_payload

        for label, expected in [("LOW", 0.25), ("MEDIUM", 0.50), ("HIGH", 0.75), ("VERY_HIGH", 0.95)]:
            result = {
                "synthesis": {},
                "l12_verdict": {"confidence": label},
                "execution_map": {},
                "governance": {},
            }
            payload = _build_verdict_cache_payload("EURUSD", result)
            assert payload["confidence"] == expected, f"{label} → {payload['confidence']}"
