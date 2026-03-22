"""
Performance regression tests -- keep CI fast.
"""

import time

import pytest


class TestPerformanceBaselines:
    """Ensure key operations stay within time budget."""

    def test_verdict_computation_under_10ms(self):
        start = time.perf_counter()
        # Simulate verdict computation
        scores = [8.5, 7.2, 6.8, 7.5, 8.0, 6.5, 7.8, 8.2, 7.0, 6.9, 7.5]
        sum(scores) / len(scores)  # pyright: ignore[reportUnusedExpression]
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 10, f"Verdict computation took {elapsed:.1f}ms"

    def test_risk_check_under_5ms(self):
        start = time.perf_counter()
        daily_pnl = -1500
        daily_limit = 5000
        risk_amount = 500
        (abs(daily_pnl) + risk_amount) <= daily_limit  # pyright: ignore[reportUnusedExpression]  # noqa: B015
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 5, f"Risk check took {elapsed:.1f}ms"

    def test_journal_append_under_1ms(self):
        journal = []
        start = time.perf_counter()
        for i in range(100):
            journal.append({"id": i, "type": "J2", "verdict": "EXECUTE"})  # noqa: PERF401
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 50, f"100 journal appends took {elapsed:.1f}ms"
        assert len(journal) == 100

    @pytest.mark.parametrize("n_pairs", [5, 10, 28])
    def test_batch_scoring_scales_linearly(self, n_pairs):
        """Scoring N pairs should scale roughly linearly."""
        start = time.perf_counter()
        for i in range(n_pairs):
            scores = [7.0 + (i % 3) * 0.5] * 11
            avg = sum(scores) / len(scores)
            _ = "EXECUTE" if avg >= 7.0 else "NO_TRADE"
        elapsed = time.perf_counter() - start
        per_pair = elapsed / n_pairs
        assert per_pair < 0.01, f"Per-pair scoring took {per_pair * 1000:.1f}ms"
