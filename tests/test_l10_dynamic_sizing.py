"""Tests: DynamicPositionSizingEngine integration INTO L10 core sizing path.

Verifies that when ``enable_dynamic_sizing`` is True and upstream
provides ``trade_returns`` + ``win_probability``, the Kelly-optimal
risk fraction actually drives ``base_risk_pct -> risk_amount -> lot_size``
instead of the static ``max_risk_pct`` from ``risk_data``.

Previous state: Kelly fields were appended AFTER the return statement
(dead code).  This test proves the L10 sizing path now uses them.

Authority: ANALYSIS ZONE only. No execution side-effects.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np  # pyright: ignore[reportMissingImports]

from analysis.layers.L10_position_sizing import (
    _DYNAMIC_SIZING_ENABLED,
    L10PositionAnalyzer,
    _dps_engine,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────

_TRADE_PARAMS = {
    "entry": 1.2650,
    "stop_loss": 1.2620,
    "take_profit": 1.2710,
}

_PAIR = "GBPUSD"
_BALANCE = 10_000.0


def _winning_returns(n: int = 200, win_rate: float = 0.65, seed: int = 42) -> list[float]:
    """Generate trade history with positive Kelly edge."""
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(20.0, 60.0)))  # wins
        else:
            returns.append(float(rng.uniform(-30.0, -10.0)))  # losses
    return returns


def _losing_returns(n: int = 200, seed: int = 99) -> list[float]:
    """Generate trade history where Kelly says no edge."""
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < 0.25:  # 25% win rate
            returns.append(float(rng.uniform(5.0, 15.0)))  # small wins
        else:
            returns.append(float(rng.uniform(-40.0, -20.0)))  # big losses
    return returns


# ══════════════════════════════════════════════════════════════════════════════
# PREREQUISITE: Engine and config must be loaded
# ══════════════════════════════════════════════════════════════════════════════


class TestPrerequisites:
    """Verify the config toggle and engine loaded correctly."""

    def test_dynamic_sizing_enabled(self) -> None:
        assert _DYNAMIC_SIZING_ENABLED is True, (
            "constitution.yaml position_sizing.enable_dynamic_sizing must be true"
        )

    def test_engine_loaded(self) -> None:
        assert _dps_engine is not None, (
            "DynamicPositionSizingEngine must be instantiated at module level"
        )


# ══════════════════════════════════════════════════════════════════════════════
# CORE: Kelly fraction drives lot_size
# ══════════════════════════════════════════════════════════════════════════════


class TestKellyDrivesLotSize:
    """Verify Kelly-optimal fraction actually changes lot_size (not just metadata)."""

    def test_dynamic_vs_static_lot_differs(self) -> None:
        """With trade_returns and win_probability, lot_size differs from static."""
        analyzer = L10PositionAnalyzer()

        # Static sizing (no trade_returns -> falls back to max_risk_pct)
        static = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            risk_data={"max_risk_pct": 1.0},
            confidence=0.80,
        )

        # Dynamic sizing (with trade_returns + win_probability)
        dynamic = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            risk_data={"max_risk_pct": 1.0},
            confidence=0.80,
            trade_returns=_winning_returns(),
            win_probability=0.65,
            bayesian_posterior=0.67,
        )

        assert static["sizing_source"] == "STATIC"
        assert dynamic["sizing_source"] == "DYNAMIC_KELLY"

        # Kelly output should differ from 1.0% static
        assert dynamic["kelly_risk_percent"] is not None
        assert dynamic["adjusted_risk_pct"] != static["adjusted_risk_pct"]

    def test_kelly_fraction_in_result(self) -> None:
        """Dynamic result contains all Kelly diagnostic fields."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            trade_returns=_winning_returns(),
            win_probability=0.65,
            bayesian_posterior=0.67,
        )

        assert result["sizing_source"] == "DYNAMIC_KELLY"
        assert result["kelly_fraction"] is not None
        assert result["kelly_raw"] is not None
        assert result["kelly_risk_percent"] is not None
        assert result["kelly_edge_negative"] is False
        assert result["cvar_adjustment"] is not None
        assert result["cvar_value"] is not None
        assert result["volatility_adjustment"] is not None
        assert result["dps_result"] is not None  # full dict

    def test_risk_amount_reflects_kelly(self) -> None:
        """risk_amount = balance * (kelly-based adjusted_risk_pct / 100)."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            confidence=1.0,  # FTA multiplier = 1.20 (VERY_HIGH)
            trade_returns=_winning_returns(),
            win_probability=0.65,
            bayesian_posterior=0.67,
        )

        # risk_amount should be derived from Kelly-driven adjusted_risk_pct
        # Allow rounding tolerance: risk_amount uses pre-rounded pct,
        # result["adjusted_risk_pct"] is rounded to 2 decimal places.
        expected_risk = _BALANCE * (result["adjusted_risk_pct"] / 100.0)
        assert abs(result["risk_amount"] - expected_risk) < 1.0

    def test_lot_size_computed_from_kelly_amount(self) -> None:
        """lot_size = risk_amount / (sl_pips * pip_value) -- using Kelly amount."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            confidence=0.80,
            trade_returns=_winning_returns(),
            win_probability=0.65,
        )

        sl_pips = result["sl_pips"]
        pip_value = result["pip_value"]
        risk_amount = result["risk_amount"]

        if sl_pips > 0 and pip_value > 0:
            expected_lot_raw = risk_amount / (sl_pips * pip_value)
            # lot_size floors to 0.01 step, so allow tolerance
            assert abs(result["lot_size"] - expected_lot_raw) < 0.02


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASE: Negative Kelly edge -> fallback to static
# ══════════════════════════════════════════════════════════════════════════════


class TestNegativeEdgeFallback:
    """When Kelly indicates no edge, system falls back to static max_risk_pct."""

    def test_no_edge_uses_static(self) -> None:
        """Losing history -> Kelly no edge -> sizing_source = STATIC_KELLY_NO_EDGE."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            risk_data={"max_risk_pct": 1.0},
            confidence=0.80,
            trade_returns=_losing_returns(),
            win_probability=0.25,
            bayesian_posterior=0.30,
        )

        assert result["sizing_source"] == "STATIC_KELLY_NO_EDGE"
        assert result["kelly_edge_negative"] is True
        assert result["kelly_raw"] is not None
        assert result["kelly_raw"] <= 0.0
        # Falls back to static 1.0%, so base_risk_pct should be 1.0
        assert result["base_risk_pct"] == 1.0
        assert any("KELLY_NO_EDGE" in w for w in result["warnings"])


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY: No trade_returns -> pure static
# ══════════════════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Without trade_returns, system is identical to pre-integration behavior."""

    def test_no_returns_static_path(self) -> None:
        """No trade_returns -> sizing_source=STATIC, no Kelly fields."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            risk_data={"max_risk_pct": 1.5},
            confidence=0.80,
        )

        assert result["sizing_source"] == "STATIC"
        assert result["kelly_fraction"] is None
        assert result["kelly_raw"] is None
        assert result["dps_result"] is None

        # Static path: base = 1.5 * 1.0 = 1.5, FTA(0.80) = 1.0x -> 1.5%
        assert result["base_risk_pct"] == 1.5
        assert result["adjusted_risk_pct"] == 1.5  # HIGH band -> 1.0x

    def test_insufficient_returns_static_path(self) -> None:
        """Fewer than min_returns -> falls back to static."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            trade_returns=[10.0, -5.0, 8.0],  # only 3 -- under threshold
            win_probability=0.65,
        )

        assert result["sizing_source"] == "STATIC"

    def test_no_win_probability_static_path(self) -> None:
        """win_probability=None -> falls back to static."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            trade_returns=_winning_returns(),
            win_probability=None,
        )

        assert result["sizing_source"] == "STATIC"


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG TOGGLE: Disabled -> always static
# ══════════════════════════════════════════════════════════════════════════════


class TestConfigToggle:
    """When enable_dynamic_sizing=False, Kelly never activates."""

    def test_disabled_config_forces_static(self) -> None:
        """Even with trade_returns, disabled flag -> STATIC."""
        with patch(
            "analysis.layers.L10_position_sizing._DYNAMIC_SIZING_ENABLED",
            False,
        ):
            analyzer = L10PositionAnalyzer()
            result = analyzer.analyze(
                trade_params=_TRADE_PARAMS,
                account_balance=_BALANCE,
                pair=_PAIR,
                trade_returns=_winning_returns(),
                win_probability=0.65,
            )

            assert result["sizing_source"] == "STATIC"
            assert result["kelly_fraction"] is None


# ══════════════════════════════════════════════════════════════════════════════
# SAFETY: Kelly capped by _MAX_RISK_PCT and FTA still applies
# ══════════════════════════════════════════════════════════════════════════════


class TestSafetyClamps:
    """Kelly output is always clamped, and FTA still modulates."""

    def test_kelly_capped_at_max_risk(self) -> None:
        """Even aggressive Kelly can't exceed _MAX_RISK_PCT (5%)."""
        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            confidence=1.0,  # FTA 1.20x
            trade_returns=_winning_returns(),
            win_probability=0.65,
            bayesian_posterior=0.67,
        )

        assert result["adjusted_risk_pct"] <= 5.0

    def test_fta_still_modulates_kelly(self) -> None:
        """Low confidence FTA reduces Kelly-derived risk."""
        analyzer = L10PositionAnalyzer()

        # High confidence (VERY_HIGH -> 1.20x)
        high = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            confidence=0.95,
            trade_returns=_winning_returns(),
            win_probability=0.65,
        )

        # Low confidence (LOW -> 0.60x)
        low = analyzer.analyze(
            trade_params=_TRADE_PARAMS,
            account_balance=_BALANCE,
            pair=_PAIR,
            confidence=0.45,
            trade_returns=_winning_returns(),
            win_probability=0.65,
        )

        # Both use Kelly, but FTA scales differently
        assert high["sizing_source"] == "DYNAMIC_KELLY"
        assert low["sizing_source"] == "DYNAMIC_KELLY"
        assert high["adjusted_risk_pct"] > low["adjusted_risk_pct"]
        assert high["lot_size"] >= low["lot_size"]
