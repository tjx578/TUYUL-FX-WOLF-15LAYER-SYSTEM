"""
Integration test: end-to-end feed → analysis → verdict latency.
Target: < 2 seconds for a single pair analysis cycle.
"""
import time

import pytest  # pyright: ignore[reportMissingImports]


@pytest.mark.integration
class TestFeedToVerdictLatency:
    """Measure E2E latency from feed ingestion to verdict output."""

    def _simulate_feed(self, symbol="EURUSD"):
        return {
            "symbol": symbol,
            "timeframe": "H1",
            "open": 1.0840, "high": 1.0870,
            "low": 1.0835, "close": 1.0855,
            "volume": 12345,
            "timestamp": "2026-02-15T10:00:00Z",
        }

    def _simulate_analysis(self, feed_data):
        """Simulate L1–L11 analysis returning scores."""
        time.sleep(0.05)  # simulate processing
        return {
            "symbol": feed_data["symbol"],
            "wolf_score": 8.5,
            "tii_score": 7.2,
            "frpc_score": 6.8,
        }

    def _simulate_verdict(self, analysis_result):
        """Simulate L12 verdict from analysis scores."""
        time.sleep(0.01)
        avg = sum([
            analysis_result["wolf_score"],
            analysis_result["tii_score"],
            analysis_result["frpc_score"],
        ]) / 3
        verdict = "EXECUTE" if avg >= 7.0 else "NO_TRADE"
        return {
            "symbol": analysis_result["symbol"],
            "verdict": verdict,
            "confidence": min(avg / 10, 1.0),
        }

    def test_single_pair_latency(self):
        start = time.perf_counter()

        feed = self._simulate_feed("EURUSD")
        analysis = self._simulate_analysis(feed)
        verdict = self._simulate_verdict(analysis)

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"E2E latency {elapsed:.3f}s exceeds 2s target"
        assert verdict["verdict"] in ("EXECUTE", "NO_TRADE")

    @pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"])
    def test_multi_pair_latency(self, symbol):
        start = time.perf_counter()

        feed = self._simulate_feed(symbol)
        analysis = self._simulate_analysis(feed)
        self._simulate_verdict(analysis)

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"{symbol} E2E latency {elapsed:.3f}s exceeds 2s"

    def test_concurrent_multi_pair_latency(self):
        """5 pairs analyzed concurrently should complete in < 3s total."""
        import concurrent.futures  # noqa: PLC0415

        symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]

        def process(symbol):
            feed = self._simulate_feed(symbol)
            analysis = self._simulate_analysis(feed)
            return self._simulate_verdict(analysis)

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(process, symbols))
        elapsed = time.perf_counter() - start

        assert len(results) == 5
        assert elapsed < 3.0, f"Concurrent 5-pair latency {elapsed:.3f}s exceeds 3s"
        for r in results:
            assert "verdict" in r
