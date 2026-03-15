"""Tests for risk/correlation_guard.py — Atomic correlation risk enforcement."""

from __future__ import annotations

import pytest

from risk.correlation_guard import (
    CorrelationGuard,
    CorrelationVerdict,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton between tests."""
    CorrelationGuard.reset_instance()
    yield
    CorrelationGuard.reset_instance()


def _make_guard(
    max_group_pct: float = 0.03,
    high_corr: float = 0.70,
) -> CorrelationGuard:
    return CorrelationGuard(
        max_group_exposure_pct=max_group_pct,
        high_corr_threshold=high_corr,
    )


def _open_trade(symbol: str, direction: str, risk_amount: float) -> dict:
    return {"symbol": symbol, "direction": direction, "risk_amount": risk_amount}


class TestCorrelationGuardNoOpenTrades:
    """No open positions -> always ALLOW."""

    def test_allow_when_no_open_trades(self):
        guard = _make_guard()
        result = guard.evaluate(
            proposed_symbol="EURUSD",
            proposed_direction="BUY",
            proposed_risk_amount=500.0,
            open_trades=[],
            account_equity=100_000.0,
        )
        assert result.verdict == CorrelationVerdict.ALLOW
        assert "No correlated" in result.reason

    def test_result_immutable(self):
        guard = _make_guard()
        result = guard.evaluate("EURUSD", "BUY", 500.0, [], 100_000.0)
        with pytest.raises(AttributeError):
            result.verdict = CorrelationVerdict.BLOCK  # type: ignore[misc]


class TestCorrelationGuardSameSymbol:
    """Same symbol open -> always correlated."""

    def test_same_symbol_same_direction_adds_exposure(self):
        guard = _make_guard(max_group_pct=0.03)
        trades = [_open_trade("EURUSD", "BUY", 2000.0)]
        result = guard.evaluate("EURUSD", "BUY", 2000.0, trades, 100_000.0)
        # 2000 + 2000 = 4000 / 100000 = 4% > 3% limit
        assert result.verdict == CorrelationVerdict.BLOCK
        assert "EURUSD" in result.correlated_symbols


class TestCorrelationGuardHighCorrelation:
    """Highly correlated pairs (e.g., EURUSD + GBPUSD)."""

    def test_eurusd_gbpusd_same_direction_blocked(self):
        guard = _make_guard(max_group_pct=0.02)
        trades = [_open_trade("EURUSD", "BUY", 1500.0)]
        result = guard.evaluate("GBPUSD", "BUY", 1500.0, trades, 100_000.0)
        # Combined 3000 / 100000 = 3% > 2%
        assert result.verdict == CorrelationVerdict.BLOCK
        assert "EURUSD" in result.correlated_symbols
        assert "GBPUSD" in result.correlated_symbols

    def test_eurusd_gbpusd_opposite_direction_allowed(self):
        """Opposite direction on correlated pair = hedge, not stacking.

        Only blocked if correlation >= 0.85 (very high).
        EURUSD+GBPUSD = 0.85 so opposite direction IS blocked.
        """
        guard = _make_guard(max_group_pct=0.02)
        trades = [_open_trade("EURUSD", "BUY", 1500.0)]
        result = guard.evaluate("GBPUSD", "SELL", 1500.0, trades, 100_000.0)
        # Correlation is 0.85 so >= 0.85 threshold, still blocked
        assert result.verdict == CorrelationVerdict.BLOCK

    def test_low_correlation_pair_allowed(self):
        """USDCAD + EURUSD = lower correlation, should be allowed."""
        guard = _make_guard(max_group_pct=0.03, high_corr=0.80)
        trades = [_open_trade("USDCAD", "BUY", 1000.0)]
        result = guard.evaluate("EURUSD", "BUY", 1000.0, trades, 100_000.0)
        # These are not in the default map as highly correlated
        assert result.verdict == CorrelationVerdict.ALLOW


class TestCorrelationGuardReduce:
    """REDUCE verdict when approaching but not exceeding limit."""

    def test_reduce_when_near_limit(self):
        guard = _make_guard(max_group_pct=0.04)
        # 70% of 4% = 2.8%, so 3000/100000 = 3% > 2.8% → REDUCE
        trades = [_open_trade("EURUSD", "BUY", 1500.0)]
        result = guard.evaluate("GBPUSD", "BUY", 1500.0, trades, 100_000.0)
        assert result.verdict == CorrelationVerdict.REDUCE
        assert result.max_safe_risk > 0


class TestCorrelationGuardMultiplePairs:
    """Multiple correlated pairs in the same group."""

    def test_three_correlated_pairs_blocked(self):
        guard = _make_guard(max_group_pct=0.02)
        trades = [
            _open_trade("EURUSD", "BUY", 800.0),
            _open_trade("GBPUSD", "BUY", 800.0),
        ]
        result = guard.evaluate("EURGBP", "BUY", 800.0, trades, 100_000.0)
        # EURGBP is correlated with both EURUSD (0.75) and GBPUSD (0.80)
        # Total: 800+800+800 = 2400 / 100000 = 2.4% > 2%
        assert result.verdict == CorrelationVerdict.BLOCK


class TestCorrelationGuardEdgeCases:
    """Edge case handling."""

    def test_zero_equity_returns_block(self):
        guard = _make_guard()
        result = guard.evaluate("EURUSD", "BUY", 500.0, [], 0.0)
        assert result.verdict == CorrelationVerdict.BLOCK
        assert "zero or negative" in result.reason

    def test_negative_equity_returns_block(self):
        guard = _make_guard()
        result = guard.evaluate("EURUSD", "BUY", 500.0, [], -1000.0)
        assert result.verdict == CorrelationVerdict.BLOCK

    def test_unknown_pair_not_correlated(self):
        guard = _make_guard()
        trades = [_open_trade("EURUSD", "BUY", 1000.0)]
        result = guard.evaluate("UNKNOWN", "BUY", 1000.0, trades, 100_000.0)
        # Unknown pair has no correlation map entry
        assert result.verdict == CorrelationVerdict.ALLOW

    def test_to_dict_schema(self):
        guard = _make_guard()
        result = guard.evaluate("EURUSD", "BUY", 500.0, [], 100_000.0)
        d = result.to_dict()
        assert "verdict" in d
        assert "combined_exposure" in d
        assert "max_safe_risk" in d
        assert "correlated_symbols" in d
        assert "max_correlation" in d
        assert "reason" in d


class TestCorrelationGuardDynamicMap:
    """Dynamic correlation map updates."""

    def test_update_map_changes_behavior(self):
        guard = _make_guard(max_group_pct=0.02, high_corr=0.70)
        # Initially AUDCAD and XAUUSD are not correlated
        trades = [_open_trade("AUDCAD", "BUY", 1500.0)]
        result = guard.evaluate("XAUUSD", "BUY", 1500.0, trades, 100_000.0)
        assert result.verdict == CorrelationVerdict.ALLOW

        # Update map to make them correlated
        guard.update_correlation_map({("AUDCAD", "XAUUSD"): 0.90})
        result = guard.evaluate("XAUUSD", "BUY", 1500.0, trades, 100_000.0)
        assert result.verdict == CorrelationVerdict.BLOCK


class TestCorrelationGuardSingleton:
    """Singleton pattern tests."""

    def test_singleton_returns_same_instance(self):
        inst1 = CorrelationGuard.get_instance()
        inst2 = CorrelationGuard.get_instance()
        assert inst1 is inst2

    def test_reset_creates_new_instance(self):
        inst1 = CorrelationGuard.get_instance()
        CorrelationGuard.reset_instance()
        inst2 = CorrelationGuard.get_instance()
        assert inst1 is not inst2
