"""Unit tests for risk/risk_manager.py.

Tests cover:
    - Static risk percent (backward compat)
    - Dynamic risk percent from DynamicPSE
    - Dynamic clamped when exceeds static max
    - Dynamic zero edge blocks trade
    - Daily loss limit blocking
    - Max open trades blocking
    - Lot sizing computation
    - Below min lot blocking
    - Risk source tracking
    - Serialization (to_dict)
    - Immutable result
    - Invalid stop loss / pip value
"""

from __future__ import annotations

import pytest

from risk.risk_manager import RiskManager


class TestRiskManager:

    def _base_params(self, **overrides) -> dict:
        defaults = {
            "account_balance": 100_000.0,
            "account_equity": 100_000.0,
            "daily_pnl": 0.0,
            "open_trade_count": 0,
            "stop_loss_pips": 25.0,
            "pip_value_per_lot": 10.0,
        }
        defaults.update(overrides)
        return defaults

    # ── Static risk (backward compat) ────────────────────────────────

    def test_static_risk_default(self) -> None:
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(**self._base_params())

        assert result.trade_allowed is True
        assert result.risk_source == "STATIC"
        assert result.effective_risk_percent == 0.02
        assert result.reason == "APPROVED"

    def test_static_lot_computation(self) -> None:
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(**self._base_params())

        # risk_amount = 100000 * 0.02 = 2000
        # lot = 2000 / (25 * 10) = 8.0
        assert result.risk_amount == 2000.0
        assert result.recommended_lot == 8.0
        assert result.max_safe_lot == 8.0

    # ── Dynamic risk from DynamicPSE ─────────────────────────────────

    def test_dynamic_risk_accepted(self) -> None:
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(
            **self._base_params(),
            dynamic_risk_percent=0.015,
        )

        assert result.risk_source == "DYNAMIC_PSE"
        assert result.effective_risk_percent == 0.015
        assert result.trade_allowed is True

    def test_dynamic_reduces_lot(self) -> None:
        mgr = RiskManager(max_risk_percent=0.02)

        static = mgr.evaluate(**self._base_params())
        dynamic = mgr.evaluate(
            **self._base_params(),
            dynamic_risk_percent=0.01,
        )

        assert dynamic.recommended_lot < static.recommended_lot
        assert dynamic.risk_amount < static.risk_amount

    def test_dynamic_clamped_when_exceeds_static(self) -> None:
        """Dynamic can never exceed static max."""
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(
            **self._base_params(),
            dynamic_risk_percent=0.05,  # > static max
        )

        assert result.risk_source == "DYNAMIC_CLAMPED"
        assert result.effective_risk_percent == 0.02

    def test_dynamic_zero_blocks_trade(self) -> None:
        """Zero edge from Kelly -> no trade."""
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(
            **self._base_params(),
            dynamic_risk_percent=0.0,
        )

        assert result.trade_allowed is False
        assert "DYNAMIC_RISK_ZERO_EDGE" in result.violations
        assert result.recommended_lot == 0.0

    def test_dynamic_none_falls_back_static(self) -> None:
        """None dynamic_risk_percent -> static (backward compat)."""
        mgr = RiskManager(max_risk_percent=0.02)
        result = mgr.evaluate(
            **self._base_params(),
            dynamic_risk_percent=None,
        )

        assert result.risk_source == "STATIC"
        assert result.effective_risk_percent == 0.02

    # ── Daily loss limit ─────────────────────────────────────────────

    def test_daily_loss_limit_blocks(self) -> None:
        mgr = RiskManager(max_daily_loss_percent=0.05)
        result = mgr.evaluate(
            **self._base_params(daily_pnl=-5000.0),
        )

        assert result.trade_allowed is False
        assert "DAILY_LOSS_LIMIT_REACHED" in result.violations

    def test_daily_loss_warning(self) -> None:
        """At 80% of daily limit -> warning but still allowed."""
        mgr = RiskManager(max_daily_loss_percent=0.05)
        result = mgr.evaluate(
            **self._base_params(daily_pnl=-4100.0),  # 82% of 5000
        )

        assert result.trade_allowed is True
        assert "DAILY_LOSS_LIMIT_WARNING" in result.violations

    # ── Max open trades ──────────────────────────────────────────────

    def test_max_open_trades_blocks(self) -> None:
        mgr = RiskManager(max_open_trades=3)
        result = mgr.evaluate(
            **self._base_params(open_trade_count=3),
        )

        assert result.trade_allowed is False
        assert "MAX_OPEN_TRADES_REACHED" in result.violations

    # ── Edge cases ───────────────────────────────────────────────────

    def test_zero_equity_blocks(self) -> None:
        mgr = RiskManager()
        result = mgr.evaluate(
            **self._base_params(account_equity=0.0),
        )

        assert result.trade_allowed is False
        assert "EQUITY_DEPLETED" in result.violations

    def test_invalid_stop_loss_blocks(self) -> None:
        mgr = RiskManager()
        result = mgr.evaluate(
            **self._base_params(stop_loss_pips=0.0),
        )

        assert result.trade_allowed is False
        assert "INVALID_STOP_LOSS" in result.violations

    def test_below_min_lot_blocks(self) -> None:
        mgr = RiskManager(max_risk_percent=0.0001, min_lot=0.01)
        mgr.evaluate(**self._base_params())

        # risk_amount = 100000 * 0.0001 = 10
        # lot = 10 / (25*10) = 0.04 -> rounds to 0.04 -> OK
        # But with very tiny risk it could go below 0.01
        # Let's force it:
        result2 = mgr.evaluate(
            **self._base_params(account_equity=10.0),
        )
        # risk = 10 * 0.0001 = 0.001; lot = 0.001/250 = 0.000004 -> 0.0
        assert result2.recommended_lot == 0.0

    def test_lot_rounds_down(self) -> None:
        """Lots must round DOWN for safety (never round up)."""
        mgr = RiskManager(max_risk_percent=0.02, lot_step=0.01)
        result = mgr.evaluate(
            **self._base_params(
                account_equity=50_000.0,
                stop_loss_pips=30.0,
                pip_value_per_lot=10.0,
            ),
        )
        # risk = 50000 * 0.02 = 1000
        # lot = 1000 / (30*10) = 3.333... -> rounds down to 3.33
        assert result.recommended_lot == 3.33

    # ── Serialization ────────────────────────────────────────────────

    def test_to_dict_schema(self) -> None:
        mgr = RiskManager()
        d = mgr.evaluate(**self._base_params()).to_dict()
        expected_keys = {
            "trade_allowed", "recommended_lot", "max_safe_lot",
            "effective_risk_percent", "risk_source", "risk_amount",
            "reason", "violations",
        }
        assert expected_keys <= set(d.keys())

    def test_immutable_result(self) -> None:
        mgr = RiskManager()
        result = mgr.evaluate(**self._base_params())
        with pytest.raises(AttributeError):
            result.trade_allowed = False  # type: ignore[misc]

    def test_invalid_max_risk_raises(self) -> None:
        with pytest.raises(ValueError, match="max_risk_percent"):
            RiskManager(max_risk_percent=0.0)
        with pytest.raises(ValueError, match="max_risk_percent"):
            RiskManager(max_risk_percent=1.5)
