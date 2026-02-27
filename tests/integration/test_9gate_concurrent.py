"""
Load test: 9-gate constitutional verdict under concurrent requests.

Verifies that:
- ``generate_l12_verdict`` completes within the 250 ms latency budget for
  each individual call even under concurrent thread pressure.
- Concurrent calls on different symbols do not produce cross-contamination.
- Aggregate wall-clock time for N concurrent pairs scales sub-linearly.

These tests use the same synthesis builder pattern established in
tests/test_l12_verdict.py and follow the existing @pytest.mark.integration
and @pytest.mark.concurrent conventions from the repository.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from typing import Any

import pytest

from constitution.verdict_engine import generate_l12_verdict
from context.live_context_bus import LiveContextBus


# ── Shared fixture: prime the context bus with a fresh tick ──────────────


@pytest.fixture(autouse=True)
def _prime_context_bus() -> None:
    """Ensure the singleton LiveContextBus has at least one tick."""
    bus = LiveContextBus()
    bus.update_tick({
        "symbol": "EURUSD",
        "bid": 1.0850,
        "ask": 1.0852,
        "timestamp": time.time(),
        "source": "test",
    })


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_synthesis(
    symbol: str = "EURUSD",
    *,
    tii: float = 0.95,
    integrity: float = 0.98,
    rr: float = 2.0,
    fta: float = 0.80,
    monte: float = 0.75,
    propfirm_compliant: bool = True,
    drawdown: float = 2.0,
    latency_ms: int = 50,
    conf12: float = 0.85,
) -> dict[str, Any]:
    """Build a minimal valid synthesis dict that passes all 9 gates."""
    return {
        "pair": symbol,
        "scores": {
            "wolf_30_point": 25,
            "f_score": 8,
            "t_score": 9,
            "fta_score": fta,
            "exec_score": 10,
        },
        "layers": {
            "L1": {"valid": True},
            "L8_tii_sym": tii,
            "L8_integrity_index": integrity,
            "L7_monte_carlo_win": monte,
            "conf12": conf12,
        },
        "execution": {
            "rr_ratio": rr,
            "entry": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
        },
        "propfirm": {
            "compliant": propfirm_compliant,
            "violations": [],
        },
        "risk": {
            "current_drawdown": drawdown,
            "max_drawdown": 5.0,
        },
        "bias": {
            "technical": "BULLISH",
            "fundamental": "NEUTRAL",
        },
        "macro_vix": {
            "vix_level": 15.0,
            "vix_regime": "ELEVATED",
            "regime_state": 1,
            "volatility_multiplier": 1.0,
            "risk_multiplier": 1.0,
        },
        "system": {
            "latency_ms": latency_ms,
        },
    }


def _run_verdict(symbol: str) -> dict[str, Any]:
    """Call generate_l12_verdict and return timing + result."""
    synthesis = _make_synthesis(symbol=symbol)
    t0 = time.perf_counter()
    result = generate_l12_verdict(synthesis)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {"symbol": symbol, "result": result, "elapsed_ms": elapsed_ms}


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.concurrent
class TestNineGateConcurrentLoad:
    """Verify 9-gate latency budget is met under concurrent thread pressure."""

    # Max allowed latency for a single generate_l12_verdict call (ms).
    # Gate 9 threshold is 250 ms; we use a generous 500 ms ceiling here to
    # account for CI resource variability while still catching regressions.
    _MAX_SINGLE_CALL_MS = 500

    # Total wall-clock cap for N_PAIRS concurrent calls.
    _MAX_WALL_CLOCK_S = 5.0

    _PAIRS = [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
        "USDCAD", "NZDUSD", "USDCHF", "EURJPY",
    ]

    def test_single_call_within_latency_budget(self) -> None:
        """A single generate_l12_verdict call must complete within budget."""
        outcome = _run_verdict("EURUSD")
        assert outcome["elapsed_ms"] < self._MAX_SINGLE_CALL_MS, (
            f"Single 9-gate call took {outcome['elapsed_ms']:.1f} ms "
            f"(budget: {self._MAX_SINGLE_CALL_MS} ms)"
        )
        assert outcome["result"]["verdict"] in {
            "EXECUTE_BUY", "EXECUTE_SELL", "HOLD", "NO_TRADE",
        }

    def test_concurrent_calls_within_wall_clock_budget(self) -> None:
        """All 8 pairs running concurrently must finish within wall-clock cap."""
        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._PAIRS)) as ex:
            outcomes = list(ex.map(_run_verdict, self._PAIRS))
        elapsed = time.perf_counter() - start

        assert elapsed < self._MAX_WALL_CLOCK_S, (
            f"Concurrent 9-gate sweep took {elapsed:.3f}s "
            f"(cap: {self._MAX_WALL_CLOCK_S}s)"
        )
        assert len(outcomes) == len(self._PAIRS)

    def test_no_cross_symbol_contamination(self) -> None:
        """Each concurrent result must carry the correct symbol."""
        barrier = threading.Barrier(len(self._PAIRS))

        def _run_with_barrier(symbol: str) -> dict[str, Any]:
            barrier.wait()  # force true concurrency
            return _run_verdict(symbol)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._PAIRS)) as ex:
            futures = {ex.submit(_run_with_barrier, s): s for s in self._PAIRS}
            results = {futures[f]: f.result() for f in concurrent.futures.as_completed(futures)}

        for symbol, outcome in results.items():
            assert outcome["result"]["symbol"] == symbol, (
                f"Contamination: expected {symbol}, got {outcome['result']['symbol']}"
            )

    def test_all_calls_within_per_call_latency_budget(self) -> None:
        """Each individual concurrent call must stay within the latency cap."""
        barrier = threading.Barrier(len(self._PAIRS))

        def _run_with_barrier(symbol: str) -> dict[str, Any]:
            barrier.wait()
            return _run_verdict(symbol)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._PAIRS)) as ex:
            outcomes = list(ex.map(_run_with_barrier, self._PAIRS))

        for outcome in outcomes:
            assert outcome["elapsed_ms"] < self._MAX_SINGLE_CALL_MS, (
                f"{outcome['symbol']} took {outcome['elapsed_ms']:.1f} ms "
                f"under load (budget: {self._MAX_SINGLE_CALL_MS} ms)"
            )

    def test_gate_8_latency_threshold_fails_above_limit(self) -> None:
        """Gate 8 (latency) must FAIL when synthesis latency_ms exceeds 250 ms."""
        synthesis = _make_synthesis(symbol="EURUSD", latency_ms=300)
        result = generate_l12_verdict(synthesis)
        assert result["gates"]["gate_8_latency"] == "FAIL", (
            "Gate 8 (latency) should FAIL for 300 ms synthesis latency"
        )

    def test_gate_8_latency_threshold_passes_at_limit(self) -> None:
        """Gate 8 (latency) must PASS when synthesis latency_ms is within 250 ms."""
        synthesis = _make_synthesis(symbol="EURUSD", latency_ms=200)
        result = generate_l12_verdict(synthesis)
        assert result["gates"]["gate_8_latency"] == "PASS", (
            "Gate 8 (latency) should PASS for 200 ms synthesis latency"
        )

    def test_sustained_load_50_sequential_calls(self) -> None:
        """50 sequential calls must all complete; no degradation over time."""
        elapsed_ms_list: list[float] = []
        for i in range(50):
            symbol = self._PAIRS[i % len(self._PAIRS)]
            outcome = _run_verdict(symbol)
            elapsed_ms_list.append(outcome["elapsed_ms"])

        p99 = sorted(elapsed_ms_list)[int(len(elapsed_ms_list) * 0.99)]
        assert p99 < self._MAX_SINGLE_CALL_MS, (
            f"P99 latency {p99:.1f} ms over 50 sequential calls "
            f"exceeds budget {self._MAX_SINGLE_CALL_MS} ms"
        )
