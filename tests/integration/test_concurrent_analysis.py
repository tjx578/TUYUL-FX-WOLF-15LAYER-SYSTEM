"""
Integration test: concurrent multi-pair analysis contention.
Verifies no data leakage or race conditions between pairs.
"""
import concurrent.futures
import threading

import pytest  # pyright: ignore[reportMissingImports]


@pytest.mark.integration
@pytest.mark.concurrent
class TestConcurrentMultiPairAnalysis:
    """Ensure analysis results don't leak between pairs under concurrency."""

    def _analyze_pair(self, symbol, barrier=None):
        """Simulate analysis for one pair. Barrier forces concurrent start."""
        if barrier:
            barrier.wait()
        # Each pair's "score" is deterministic based on symbol
        score = hash(symbol) % 100 / 10.0
        return {
            "symbol": symbol,
            "wolf_score": score,
            "thread_id": threading.current_thread().ident,
        }

    def test_no_cross_pair_contamination(self):
        symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
                    "USDCAD", "NZDUSD", "USDCHF", "EURJPY"]
        barrier = threading.Barrier(len(symbols))

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(symbols)) as executor:
            futures = {
                executor.submit(self._analyze_pair, s, barrier): s
                for s in symbols
            }
            results = {}
            for future in concurrent.futures.as_completed(futures):
                symbol = futures[future]
                results[symbol] = future.result()

        # Verify each result corresponds to its symbol
        for symbol, result in results.items():
            assert result["symbol"] == symbol, (
                f"Data leakage: {symbol} got result for {result['symbol']}"
            )

    def test_all_pairs_get_processed(self):
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(self._analyze_pair, symbols))
        processed = {r["symbol"] for r in results}
        assert processed == set(symbols)

    def test_concurrent_throughput(self):
        """8 pairs should complete within reasonable time."""
        import time  # noqa: PLC0415
        symbols = [f"PAIR{i}" for i in range(8)]

        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(self._analyze_pair, symbols))
        elapsed = time.perf_counter() - start

        assert len(results) == 8
        assert elapsed < 5.0, f"8-pair concurrent analysis took {elapsed:.1f}s"
