"""Tests for risk/slippage_model.py — Spread widening and execution cost estimator."""

from __future__ import annotations

import pytest

from risk.slippage_model import (
    LiquiditySession,
    NewsImpact,
    SlippageModel,
)


@pytest.fixture()
def model() -> SlippageModel:
    return SlippageModel()


class TestBasicEstimate:
    """Normal conditions estimation."""

    def test_eurusd_london_no_news(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0)
        assert est.base_spread_pips == 1.0
        assert est.spread_multiplier == 1.0
        assert est.estimated_spread_pips == 1.0
        assert est.slippage_pips == 0.3
        assert est.total_cost_pips == pytest.approx(1.3)
        assert est.sl_adjusted_pips == pytest.approx(21.3)

    def test_lot_adjustment_reduces_size(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0)
        # sl_adjusted > sl_pips → factor < 1.0
        assert est.lot_adjustment_factor < 1.0
        assert est.lot_adjustment_factor == pytest.approx(20.0 / 21.3, rel=1e-3)

    def test_xauusd_wider_base_spread(self, model: SlippageModel):
        est = model.estimate("XAUUSD", sl_pips=50.0)
        assert est.base_spread_pips == 3.0

    def test_unknown_pair_uses_default(self, model: SlippageModel):
        est = model.estimate("SOMEPAIR", sl_pips=30.0)
        assert est.base_spread_pips == 2.0  # default


class TestNewsImpact:
    """Spread widening under news conditions."""

    def test_high_impact_news_triples_spread(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0, news_impact=NewsImpact.HIGH)
        assert est.spread_multiplier == 3.0
        assert est.estimated_spread_pips == pytest.approx(3.0)
        assert est.slippage_pips == 2.5

    def test_medium_impact_news(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0, news_impact=NewsImpact.MEDIUM)
        assert est.spread_multiplier == pytest.approx(1.8)
        assert est.slippage_pips == 1.0

    def test_low_impact_news(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0, news_impact=NewsImpact.LOW)
        assert est.spread_multiplier == pytest.approx(1.2)


class TestSessionImpact:
    """Spread inflation based on trading session."""

    def test_asia_session_widens_spread(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            session=LiquiditySession.ASIA,
        )
        assert est.spread_multiplier == 1.5
        assert est.estimated_spread_pips == pytest.approx(1.5)

    def test_off_hours_doubles_spread(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            session=LiquiditySession.OFF_HOURS,
        )
        assert est.spread_multiplier == 2.0

    def test_london_session_normal(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            session=LiquiditySession.LONDON,
        )
        assert est.spread_multiplier == 1.0

    def test_new_york_session_normal(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            session=LiquiditySession.NEW_YORK,
        )
        assert est.spread_multiplier == 1.0


class TestCombinedFactors:
    """Session + News combined spread multiplier."""

    def test_asia_plus_high_news(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            news_impact=NewsImpact.HIGH,
            session=LiquiditySession.ASIA,
        )
        # 1.5 * 3.0 = 4.5
        assert est.spread_multiplier == pytest.approx(4.5)

    def test_off_hours_plus_high_news_capped(self, model: SlippageModel):
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            news_impact=NewsImpact.HIGH,
            session=LiquiditySession.OFF_HOURS,
        )
        # 2.0 * 3.0 = 6.0 → capped at 5.0
        assert est.spread_multiplier == 5.0

    def test_max_multiplier_respected(self):
        model = SlippageModel(max_spread_multiplier=3.0)
        est = model.estimate(
            "EURUSD",
            sl_pips=20.0,
            news_impact=NewsImpact.HIGH,
            session=LiquiditySession.ASIA,
        )
        assert est.spread_multiplier == 3.0


class TestShouldSkipTrade:
    """Cost-to-SL ratio skip logic."""

    def test_high_cost_ratio_skips(self, model: SlippageModel):
        # Very tight SL + high news = huge cost ratio
        skip, reason = model.should_skip_trade(
            "GBPJPY",
            sl_pips=5.0,
            news_impact=NewsImpact.HIGH,
        )
        assert skip is True
        assert "%" in reason

    def test_normal_conditions_no_skip(self, model: SlippageModel):
        skip, reason = model.should_skip_trade("EURUSD", sl_pips=30.0)
        assert skip is False
        assert reason == ""

    def test_custom_max_cost_ratio(self, model: SlippageModel):
        skip, _ = model.should_skip_trade(
            "EURUSD",
            sl_pips=10.0,
            max_cost_ratio=0.05,
        )
        # 1.3 / 10 = 13% > 5%
        assert skip is True


class TestAdjustLotForSlippage:
    """Lot size adjustment accounting for execution cost."""

    def test_lot_reduced(self, model: SlippageModel):
        adjusted_lot, est = model.adjust_lot_for_slippage(
            lot_size=1.0,
            sl_pips=20.0,
            symbol="EURUSD",
        )
        assert adjusted_lot < 1.0
        assert adjusted_lot >= 0.01

    def test_lot_not_below_min(self, model: SlippageModel):
        adjusted_lot, est = model.adjust_lot_for_slippage(
            lot_size=0.01,
            sl_pips=20.0,
            symbol="EURUSD",
            min_lot=0.01,
        )
        assert adjusted_lot == 0.01

    def test_lot_respects_step(self, model: SlippageModel):
        adjusted_lot, est = model.adjust_lot_for_slippage(
            lot_size=0.50,
            sl_pips=20.0,
            symbol="EURUSD",
            lot_step=0.01,
        )
        # Should be rounded to lot_step
        assert round(adjusted_lot * 100) == adjusted_lot * 100  # clean to cents

    def test_high_news_reduces_lot_more(self, model: SlippageModel):
        normal_lot, _ = model.adjust_lot_for_slippage(
            lot_size=1.0,
            sl_pips=20.0,
            symbol="EURUSD",
        )
        news_lot, _ = model.adjust_lot_for_slippage(
            lot_size=1.0,
            sl_pips=20.0,
            symbol="EURUSD",
            news_impact=NewsImpact.HIGH,
        )
        assert news_lot < normal_lot


class TestEdgeCases:
    """Edge case handling."""

    def test_zero_sl_returns_neutral(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=0.0)
        assert est.total_cost_pips == 0.0
        assert est.lot_adjustment_factor == 1.0

    def test_negative_sl_returns_neutral(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=-5.0)
        assert est.total_cost_pips == 0.0

    def test_custom_spreads_override(self):
        model = SlippageModel(custom_spreads={"EURUSD": 0.5})
        est = model.estimate("EURUSD", sl_pips=20.0)
        assert est.base_spread_pips == 0.5

    def test_estimate_immutable(self, model: SlippageModel):
        est = model.estimate("EURUSD", sl_pips=20.0)
        with pytest.raises(AttributeError):
            est.total_cost_pips = 999.0  # type: ignore[misc]

    def test_to_dict_schema(self, model: SlippageModel):
        d = model.estimate("EURUSD", sl_pips=20.0).to_dict()
        expected_keys = {
            "symbol",
            "base_spread_pips",
            "estimated_spread_pips",
            "slippage_pips",
            "total_cost_pips",
            "spread_multiplier",
            "news_impact",
            "session",
            "sl_adjusted_pips",
            "lot_adjustment_factor",
        }
        assert expected_keys <= set(d.keys())
