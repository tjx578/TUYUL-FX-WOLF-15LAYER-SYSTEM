"""
Tests for ingest/spread_estimator.py — synthetic bid/ask spread from trade prices.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ingest.spread_estimator import (
    PAIR_SPREADS_PIPS,
    PIP_VALUES,
    SESSION_MULTIPLIER,
    _get_active_session,
    estimate_spread,
)

# ---------------------------------------------------------------------------
# Session detection
# ---------------------------------------------------------------------------

class TestGetActiveSession:
    def test_london_ny_overlap(self):
        assert _get_active_session(13) == "OVERLAP"

    def test_london_session(self):
        assert _get_active_session(8) == "LONDON"

    def test_newyork_session(self):
        assert _get_active_session(18) == "NEWYORK"

    def test_tokyo_session(self):
        assert _get_active_session(3) == "TOKYO"

    def test_sydney_session(self):
        assert _get_active_session(23) == "SYDNEY"


# ---------------------------------------------------------------------------
# Spread estimation
# ---------------------------------------------------------------------------

class TestEstimateSpread:
    def test_bid_less_than_ask(self):
        bid, ask = estimate_spread("EURUSD", 1.0842)
        assert bid < ask

    def test_mid_equals_trade_price(self):
        price = 1.0842
        bid, ask = estimate_spread("EURUSD", price)
        mid = (bid + ask) / 2
        assert abs(mid - price) < 1e-6

    def test_spread_positive(self):
        bid, ask = estimate_spread("GBPJPY", 185.50)
        assert ask - bid > 0

    def test_xauusd_wider_than_eurusd(self):
        _, ask_eur = estimate_spread("EURUSD", 1.0842, timestamp=1700049600.0)
        bid_eur, _ = estimate_spread("EURUSD", 1.0842, timestamp=1700049600.0)
        eur_spread = ask_eur - bid_eur

        _, ask_xau = estimate_spread("XAUUSD", 2000.0, timestamp=1700049600.0)
        bid_xau, _ = estimate_spread("XAUUSD", 2000.0, timestamp=1700049600.0)
        xau_spread = ask_xau - bid_xau

        assert xau_spread > eur_spread

    def test_off_peak_wider_than_overlap(self):
        # London-NY overlap = hour 13
        overlap_ts = datetime(2026, 2, 16, 13, 0, 0, tzinfo=UTC).timestamp()
        bid_o, ask_o = estimate_spread("EURUSD", 1.0842, timestamp=overlap_ts)
        spread_overlap = ask_o - bid_o

        # Tokyo = hour 3
        tokyo_ts = datetime(2026, 2, 16, 3, 0, 0, tzinfo=UTC).timestamp()
        bid_t, ask_t = estimate_spread("EURUSD", 1.0842, timestamp=tokyo_ts)
        spread_tokyo = ask_t - bid_t

        assert spread_tokyo > spread_overlap

    def test_zero_price_returns_identity(self):
        bid, ask = estimate_spread("EURUSD", 0.0)
        assert bid == 0.0
        assert ask == 0.0

    def test_negative_price_returns_identity(self):
        bid, ask = estimate_spread("EURUSD", -1.0)
        assert bid == -1.0
        assert ask == -1.0

    def test_unknown_pair_uses_defaults(self):
        bid, ask = estimate_spread("SOMEPAIR", 1.5)
        assert bid < ask  # Should still produce a spread

    def test_jpy_pair_pip_value(self):
        """JPY pairs use pip = 0.01, so spread should be in hundredths."""
        bid, ask = estimate_spread("USDJPY", 150.00, timestamp=1700049600.0)
        spread = ask - bid
        # 1 pip = 0.01, base spread = 1.0 pip, overlap multiplier = 1.0
        # Expected: ~0.01 price units
        assert 0.005 < spread < 0.05

    def test_eurusd_spread_in_realistic_range(self):
        """EURUSD spread should be ~0.0001 (1 pip) during overlap."""
        overlap_ts = datetime(2026, 2, 16, 13, 0, 0, tzinfo=UTC).timestamp()
        bid, ask = estimate_spread("EURUSD", 1.0842, timestamp=overlap_ts)
        spread = ask - bid
        # 1 pip = 0.0001, base = 1.0 pip, overlap multiplier = 1.0
        assert 0.00005 < spread < 0.0005


# ---------------------------------------------------------------------------
# Config sanity
# ---------------------------------------------------------------------------

class TestSpreadConfig:
    def test_all_default_pairs_have_spreads(self):
        for pair in ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "AUDUSD", "XAUUSD"]:
            assert pair in PAIR_SPREADS_PIPS

    def test_jpy_pairs_have_correct_pip_value(self):
        for pair in ["USDJPY", "EURJPY", "GBPJPY"]:
            assert PIP_VALUES[pair] == 0.01

    def test_xauusd_pip_value(self):
        assert PIP_VALUES["XAUUSD"] == 0.10

    def test_session_multipliers_positive(self):
        for session, mult in SESSION_MULTIPLIER.items():
            assert mult > 0
