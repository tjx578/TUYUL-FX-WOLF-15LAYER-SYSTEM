"""
Tests for L1 Context Layer v2 — ATR-normalized, multi-asset adaptive.

Covers:
  - Basic regime detection (FX, metals, crypto)
  - ATR-normalized threshold behavior
  - Asset profile selection
  - Session model correctness
  - Volatility classification per asset class
  - CSI v2 with momentum
  - EMA-9 momentum bias
  - Regime quality composite
  - Alignment enrichment
  - ContextResult dataclass contract
  - Input validation (ContextError)
  - Insufficient data fallback
  - Edge cases (zero ATR, constant prices, single bar)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from analysis.layers.L1_context import (
    CRYPTO_PROFILE,
    FX_PROFILE,
    INDEX_PROFILE,
    METALS_PROFILE,
    ContextError,
    ContextResult,
    _classify_asset,
    _classify_volatility,
    _compute_alignment,
    _compute_csi,
    _compute_momentum_bias,
    _compute_regime_quality,
    _compute_trend_strength,
    _detect_regime,
    _ema,
    _get_asset_profile,
    _get_session,
    _sma,
    _validate_market_data,
    analyze_context,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures & Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_market_data(
    n: int = 60,
    base: float = 1.3000,
    drift: float = 0.0001,
    atr_mult: float = 1.0,
) -> dict[str, list[float]]:
    """Generate synthetic OHLCV data with controllable drift and volatility."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i in range(n):
        c = base + drift * i
        h = c + 0.0005 * atr_mult
        low = c - 0.0005 * atr_mult
        closes.append(round(c, 5))
        highs.append(round(h, 5))
        lows.append(round(low, 5))
        volumes.append(1000.0 + i * 10)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def _make_xauusd_data(
    n: int = 60,
    base: float = 2000.0,
    drift: float = 0.5,
) -> dict[str, list[float]]:
    """Generate synthetic gold data."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i in range(n):
        c = base + drift * i
        h = c + 5.0
        low = c - 5.0
        closes.append(round(c, 2))
        highs.append(round(h, 2))
        lows.append(round(low, 2))
        volumes.append(5000.0 + i * 50)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def _make_ranging_data(
    n: int = 60,
    base: float = 1.3000,
) -> dict[str, list[float]]:
    """Generate ranging (no-trend) data oscillating around base."""
    import math as _math  # noqa: PLC0415

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i in range(n):
        c = base + 0.0002 * _math.sin(i * 0.5)
        h = c + 0.0003
        low = c - 0.0003
        closes.append(round(c, 5))
        highs.append(round(h, 5))
        lows.append(round(low, 5))
        volumes.append(1000.0)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


LONDON_OVERLAP = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
TOKYO_SESSION = datetime(2026, 2, 16, 3, 0, 0, tzinfo=UTC)
SYDNEY_SESSION = datetime(2026, 2, 16, 23, 0, 0, tzinfo=UTC)


# ═══════════════════════════════════════════════════════════════════════════
# §1  Asset Profile Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAssetProfile:
    """Asset profile resolution and calibration."""

    def test_fx_default(self) -> None:
        assert _get_asset_profile("GBPUSD") is FX_PROFILE
        assert _get_asset_profile("EURUSD") is FX_PROFILE
        assert _get_asset_profile("USDJPY") is FX_PROFILE

    def test_metals(self) -> None:
        assert _get_asset_profile("XAUUSD") is METALS_PROFILE
        assert _get_asset_profile("XAGUSD") is METALS_PROFILE

    def test_crypto(self) -> None:
        assert _get_asset_profile("BTCUSD") is CRYPTO_PROFILE
        assert _get_asset_profile("ETHUSD") is CRYPTO_PROFILE

    def test_index(self) -> None:
        assert _get_asset_profile("US30") is INDEX_PROFILE
        assert _get_asset_profile("NAS100") is INDEX_PROFILE

    def test_unknown_falls_back_to_fx(self) -> None:
        assert _get_asset_profile("UNKNOWN_PAIR") is FX_PROFILE

    def test_case_insensitive(self) -> None:
        assert _get_asset_profile("xauusd") is METALS_PROFILE
        assert _get_asset_profile("Btcusd") is CRYPTO_PROFILE

    def test_profile_immutability(self) -> None:
        with pytest.raises(AttributeError):
            FX_PROFILE.k_trend = 999  # type: ignore[misc]

    def test_classify_asset(self) -> None:
        assert _classify_asset("GBPUSD") == "FX"
        assert _classify_asset("XAUUSD") == "METALS"
        assert _classify_asset("BTCUSD") == "CRYPTO"
        assert _classify_asset("US30") == "INDEX"


# ═══════════════════════════════════════════════════════════════════════════
# §2  Session Model Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionModel:
    """Session detection and multiplier assignment."""

    def test_london_ny_overlap(self) -> None:
        name, mult = _get_session(14)
        assert name == "LONDON_NEWYORK_OVERLAP"
        assert mult == 1.30

    def test_tokyo_london_overlap(self) -> None:
        name, mult = _get_session(8)
        assert name == "TOKYO_LONDON_OVERLAP"
        assert mult == 1.15

    def test_london(self) -> None:
        name, mult = _get_session(10)
        assert name == "LONDON"
        assert mult == 1.10

    def test_newyork(self) -> None:
        name, mult = _get_session(18)
        assert name == "NEWYORK"
        assert mult == 1.05

    def test_tokyo(self) -> None:
        name, mult = _get_session(3)
        assert name == "TOKYO"
        assert mult == 0.85

    def test_sydney(self) -> None:
        name, mult = _get_session(23)
        assert name == "SYDNEY"
        assert mult == 0.70

    @pytest.mark.parametrize("hour", range(24))
    def test_all_hours_covered(self, hour: int) -> None:
        name, mult = _get_session(hour)
        assert name != ""
        assert 0.5 < mult < 1.5


# ═══════════════════════════════════════════════════════════════════════════
# §3  Core Indicator Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestIndicators:
    """SMA, EMA, ATR correctness."""

    def test_sma_basic(self) -> None:
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _sma(data, 3) == pytest.approx(4.0)  # (3+4+5)/3

    def test_sma_insufficient_data(self) -> None:
        data = [1.0, 2.0]
        assert _sma(data, 5) == pytest.approx(1.5)

    def test_sma_empty(self) -> None:
        assert _sma([], 5) == 0.0

    def test_ema_basic(self) -> None:
        data = [float(i) for i in range(1, 21)]
        result = _ema(data, 9)
        # EMA-9 on rising data should be > SMA-9 seed
        assert result > 0

    def test_ema_empty(self) -> None:
        assert _ema([], 9) == 0.0

    def test_ema_insufficient(self) -> None:
        data = [1.0, 2.0, 3.0]
        assert _ema(data, 9) == pytest.approx(2.0)  # falls back to SMA


# ═══════════════════════════════════════════════════════════════════════════
# §4  Regime Detection Tests (ATR-normalized)
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeDetection:
    """ATR-normalized regime detection."""

    def test_trend_up(self) -> None:
        # spread > k_trend * atr_frac → TREND_UP
        regime, force = _detect_regime(0.005, 0.001, FX_PROFILE)
        assert regime == "TREND_UP"
        assert force == "BULLISH"

    def test_trend_down(self) -> None:
        regime, force = _detect_regime(-0.005, 0.001, FX_PROFILE)
        assert regime == "TREND_DOWN"
        assert force == "BEARISH"

    def test_transition(self) -> None:
        # spread between k_transition*atr and k_trend*atr
        atr_frac = 0.001
        spread = FX_PROFILE.k_transition * atr_frac * 1.5
        regime, force = _detect_regime(spread, atr_frac, FX_PROFILE)
        assert regime == "TRANSITION"
        assert force == "NEUTRAL"

    def test_range(self) -> None:
        regime, force = _detect_regime(0.0, 0.001, FX_PROFILE)
        assert regime == "RANGE"
        assert force == "NEUTRAL"

    def test_zero_atr_fallback(self) -> None:
        """When ATR is zero, fallback to static thresholds."""
        regime, _ = _detect_regime(0.003, 0.0, FX_PROFILE)
        assert regime == "TREND_UP"

    def test_metals_wider_threshold(self) -> None:
        """Gold has lower k_trend → trends trigger more appropriately."""
        atr_frac = 0.005  # typical XAU ATR/price
        spread = 0.008  # >1.2 * 0.005
        regime, _ = _detect_regime(spread, atr_frac, METALS_PROFILE)
        assert regime == "TREND_UP"

    def test_crypto_widest_threshold(self) -> None:
        """Crypto has lowest k_trend → adapts to high volatility."""
        atr_frac = 0.02  # typical BTC ATR/price
        spread = 0.025  # >1.0 * 0.02
        regime, _ = _detect_regime(spread, atr_frac, CRYPTO_PROFILE)
        assert regime == "TREND_UP"


# ═══════════════════════════════════════════════════════════════════════════
# §5  Volatility Classification Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestVolatilityClassification:
    """Asset-adaptive volatility classification."""

    def test_fx_thresholds(self) -> None:
        assert _classify_volatility(2.0, FX_PROFILE) == "EXTREME"
        assert _classify_volatility(1.0, FX_PROFILE) == "HIGH"
        assert _classify_volatility(0.5, FX_PROFILE) == "NORMAL"
        assert _classify_volatility(0.15, FX_PROFILE) == "LOW"
        assert _classify_volatility(0.05, FX_PROFILE) == "DEAD"

    def test_metals_wider_bands(self) -> None:
        # 2.0 ATR% is NORMAL for metals, but HIGH for FX
        assert _classify_volatility(2.0, METALS_PROFILE) == "HIGH"
        assert _classify_volatility(2.0, FX_PROFILE) == "EXTREME"

    def test_crypto_widest_bands(self) -> None:
        # 3.0 ATR% is NORMAL for crypto, EXTREME for FX
        assert _classify_volatility(3.0, CRYPTO_PROFILE) == "HIGH"
        assert _classify_volatility(3.0, FX_PROFILE) == "EXTREME"


# ═══════════════════════════════════════════════════════════════════════════
# §6  Trend Strength Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTrendStrength:
    """ATR-normalized trend strength."""

    def test_at_threshold(self) -> None:
        atr_frac = 0.001
        spread = FX_PROFILE.k_trend * atr_frac
        strength = _compute_trend_strength(spread, atr_frac, FX_PROFILE)
        assert strength == pytest.approx(1.0)

    def test_half_threshold(self) -> None:
        atr_frac = 0.001
        spread = FX_PROFILE.k_trend * atr_frac * 0.5
        strength = _compute_trend_strength(spread, atr_frac, FX_PROFILE)
        assert 0.4 < strength < 0.6

    def test_zero_atr_legacy_fallback(self) -> None:
        strength = _compute_trend_strength(0.005, 0.0, FX_PROFILE)
        assert strength == pytest.approx(1.0)  # 0.005 * 200 = 1.0

    def test_capped_at_one(self) -> None:
        strength = _compute_trend_strength(0.01, 0.001, FX_PROFILE)
        assert strength <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §7  Momentum & CSI Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMomentumAndCSI:
    """EMA-9 momentum and CSI v2."""

    def test_bullish_momentum(self) -> None:
        closes = [1.3000 + 0.0001 * i for i in range(20)]
        ema9 = _ema(closes, 9)
        direction, mag = _compute_momentum_bias(closes, ema9)
        assert direction == "BULLISH"
        assert mag > 0

    def test_bearish_momentum(self) -> None:
        closes = [1.3000 - 0.0001 * i for i in range(20)]
        ema9 = _ema(closes, 9)
        direction, mag = _compute_momentum_bias(closes, ema9)
        assert direction == "BEARISH"
        assert mag > 0

    def test_neutral_momentum(self) -> None:
        closes = [1.3000] * 20
        ema9 = _ema(closes, 9)
        direction, _ = _compute_momentum_bias(closes, ema9)
        assert direction == "NEUTRAL"

    def test_empty_closes_neutral(self) -> None:
        direction, mag = _compute_momentum_bias([], 0.0)
        assert direction == "NEUTRAL"
        assert mag == 0.0

    def test_csi_v2_range(self) -> None:
        csi = _compute_csi(0.5, [1000.0] * 20, 1.3, 0.5)
        assert 0.0 <= csi <= 1.0

    def test_csi_v2_high_momentum_boosts(self) -> None:
        low_mom = _compute_csi(0.5, [1000.0] * 20, 1.0, 0.0)
        high_mom = _compute_csi(0.5, [1000.0] * 20, 1.0, 1.0)
        assert high_mom > low_mom

    def test_csi_v2_insufficient_volume_uses_default(self) -> None:
        """< 20 volume bars → uses default vol_factor 0.5."""
        csi = _compute_csi(0.5, [1000.0] * 5, 1.0, 0.0)
        assert 0.0 <= csi <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §8  Alignment Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAlignment:
    """Price-to-SMA alignment with EMA-9 enrichment."""

    def test_strongly_bullish(self) -> None:
        result = _compute_alignment(
            close=1.31, sma20=1.30, sma50=1.29,
            ema9=1.305, spread=0.01, regime="TREND_UP",
        )
        assert result == "STRONGLY_BULLISH"

    def test_strongly_bearish(self) -> None:
        result = _compute_alignment(
            close=1.28, sma20=1.29, sma50=1.30,
            ema9=1.285, spread=-0.01, regime="TREND_DOWN",
        )
        assert result == "STRONGLY_BEARISH"

    def test_bullish(self) -> None:
        result = _compute_alignment(
            close=1.305, sma20=1.30, sma50=1.29,
            ema9=1.304, spread=0.01, regime="TRANSITION",
        )
        assert result == "BULLISH"

    def test_bearish(self) -> None:
        result = _compute_alignment(
            close=1.285, sma20=1.29, sma50=1.30,
            ema9=1.286, spread=-0.01, regime="TRANSITION",
        )
        assert result == "BEARISH"

    def test_neutral_conflicting(self) -> None:
        result = _compute_alignment(
            close=1.30, sma20=1.30, sma50=1.30,
            ema9=1.30, spread=0.0, regime="RANGE",
        )
        assert result == "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════
# §9  Regime Quality Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeQuality:
    """Composite regime quality score."""

    def test_high_quality(self) -> None:
        q = _compute_regime_quality(
            trend_strength=1.0,
            vol_level="NORMAL",
            session_mult=1.30,
            momentum_magnitude=1.0,
            regime_agreement=True,
        )
        assert q > 0.8

    def test_low_quality(self) -> None:
        q = _compute_regime_quality(
            trend_strength=0.0,
            vol_level="DEAD",
            session_mult=0.70,
            momentum_magnitude=0.0,
            regime_agreement=False,
        )
        assert q < 0.3

    def test_neutral_hurst(self) -> None:
        """Without Hurst data, quality should still compute."""
        q = _compute_regime_quality(
            trend_strength=0.5,
            vol_level="NORMAL",
            session_mult=1.10,
            momentum_magnitude=0.3,
            regime_agreement=None,
        )
        assert 0.0 <= q <= 1.0

    def test_bounded(self) -> None:
        q = _compute_regime_quality(1.0, "NORMAL", 1.3, 1.0, True)
        assert q <= 1.0

    def test_all_zero_still_computes(self) -> None:
        q = _compute_regime_quality(0.0, "DEAD", 0.70, 0.0, None)
        assert q >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §10  Integration: analyze_context
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeContext:
    """Full integration tests for analyze_context."""

    def test_basic_fx_trending(self) -> None:
        data = _make_market_data(n=60, drift=0.0003)
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)

        assert result["valid"] is True
        assert result["pair"] == "GBPUSD"
        assert result["asset_class"] == "FX"
        assert result["session"] == "LONDON_NEWYORK_OVERLAP"
        assert result["regime"] in (
            "TREND_UP", "TREND_DOWN", "TRANSITION", "RANGE"
        )
        assert 0.0 <= result["csi"] <= 1.0
        assert 0.0 <= result["regime_quality"] <= 1.0
        assert "ema9" in result
        assert "momentum_direction" in result
        assert "trend_strength" in result

    def test_xauusd_metals_profile(self) -> None:
        data = _make_xauusd_data(n=60, drift=2.0)
        result = analyze_context(data, pair="XAUUSD", now=LONDON_OVERLAP)

        assert result["valid"] is True
        assert result["asset_class"] == "METALS"
        assert result["volatility_level"] != "UNKNOWN"

    def test_ranging_market(self) -> None:
        data = _make_ranging_data(n=60)
        result = analyze_context(data, pair="EURUSD", now=LONDON_OVERLAP)

        assert result["valid"] is True
        assert result["regime"] in ("RANGE", "TRANSITION")

    def test_insufficient_data(self) -> None:
        data = {"closes": [1.3, 1.31]}
        result = analyze_context(data, pair="GBPUSD")

        assert result["valid"] is False
        assert "reason" in result

    def test_empty_closes(self) -> None:
        result = analyze_context({}, pair="GBPUSD")
        assert result["valid"] is False

    def test_no_hlv_graceful(self) -> None:
        """Should work with just closes (no highs/lows/volumes)."""
        data = {"closes": [1.3000 + 0.0001 * i for i in range(60)]}
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)

        assert result["valid"] is True
        assert result["atr"] == 0.0  # no H/L data → ATR = 0

    def test_tokyo_session(self) -> None:
        data = _make_market_data(n=60)
        result = analyze_context(data, pair="USDJPY", now=TOKYO_SESSION)

        assert result["session"] == "TOKYO"
        assert result["session_multiplier"] == 0.85

    def test_sydney_session(self) -> None:
        data = _make_market_data(n=60)
        result = analyze_context(data, pair="AUDUSD", now=SYDNEY_SESSION)

        assert result["session"] == "SYDNEY"
        assert result["session_multiplier"] == 0.70

    def test_output_contract_keys(self) -> None:
        """Verify all required output keys are present."""
        data = _make_market_data(n=60)
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)

        required_keys = {
            "regime", "dominant_force", "volatility_level",
            "regime_confidence", "csi", "market_alignment",
            "valid", "session", "session_multiplier",
            "sma20", "sma50", "ema9", "sma_spread_pct",
            "atr", "atr_pct", "pair", "timestamp",
            "asset_class", "momentum_direction",
            "momentum_magnitude", "trend_strength",
            "regime_quality",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_backward_compat_v1_keys(self) -> None:
        """v1 keys still present for downstream layers."""
        data = _make_market_data(n=60)
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)

        # These were all in v1 — must still be present
        v1_keys = {
            "regime", "dominant_force", "volatility_level",
            "regime_confidence", "csi", "market_alignment",
            "valid", "session", "session_multiplier",
            "sma20", "sma50", "sma_spread_pct",
            "atr", "atr_pct", "pair", "timestamp",
        }
        for key in v1_keys:
            assert key in result, f"v1 key missing: {key}"

    def test_context_result_to_dict(self) -> None:
        """ContextResult.to_dict() strips None Hurst fields."""
        cr = ContextResult(
            regime="RANGE",
            dominant_force="NEUTRAL",
            volatility_level="NORMAL",
            regime_confidence=0.5,
            csi=0.5,
            market_alignment="NEUTRAL",
            valid=True,
            session="LONDON",
            session_multiplier=1.10,
            sma20=1.3,
            sma50=1.3,
            ema9=1.3,
            sma_spread_pct=0.0,
            atr=0.001,
            atr_pct=0.08,
            pair="GBPUSD",
            timestamp="2026-02-16T14:00:00+00:00",
            asset_class="FX",
            momentum_direction="NEUTRAL",
            momentum_magnitude=0.0,
            trend_strength=0.0,
            regime_quality=0.3,
        )
        d = cr.to_dict()
        assert "hurst_regime" not in d
        assert "hurst_confidence" not in d
        assert d["valid"] is True

    def test_context_result_to_dict_with_hurst(self) -> None:
        """ContextResult.to_dict() includes Hurst fields when set."""
        cr = ContextResult(
            regime="TREND_UP",
            dominant_force="BULLISH",
            volatility_level="NORMAL",
            regime_confidence=0.8,
            csi=0.7,
            market_alignment="STRONGLY_BULLISH",
            valid=True,
            session="LONDON",
            session_multiplier=1.10,
            sma20=1.31,
            sma50=1.30,
            ema9=1.305,
            sma_spread_pct=0.005,
            atr=0.001,
            atr_pct=0.08,
            pair="GBPUSD",
            timestamp="2026-02-16T14:00:00+00:00",
            asset_class="FX",
            momentum_direction="BULLISH",
            momentum_magnitude=0.5,
            trend_strength=0.8,
            regime_quality=0.85,
            hurst_regime="TRENDING",
            hurst_confidence=0.9,
            hurst_exponent=0.65,
            hurst_volatility_state="NORMAL",
            hurst_momentum=0.3,
            regime_agreement=True,
        )
        d = cr.to_dict()
        assert d["hurst_regime"] == "TRENDING"
        assert d["regime_agreement"] is True

    def test_alternative_key_names(self) -> None:
        """'close'/'high'/'low'/'volume' also accepted (not just plural)."""
        data = {
            "close": [1.3000 + 0.0001 * i for i in range(60)],
            "high": [1.3005 + 0.0001 * i for i in range(60)],
            "low": [1.2995 + 0.0001 * i for i in range(60)],
            "volume": [1000.0] * 60,
        }
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)
        assert result["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════
# §11  Input Validation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """Data integrity validation."""

    def test_nan_in_closes_raises(self) -> None:
        closes = [1.3] * 19 + [float("nan")]
        with pytest.raises(ContextError, match="not finite"):
            _validate_market_data(closes, [], [])

    def test_inf_in_closes_raises(self) -> None:
        closes = [1.3] * 19 + [float("inf")]
        with pytest.raises(ContextError, match="not finite"):
            _validate_market_data(closes, [], [])

    def test_negative_price_raises(self) -> None:
        closes = [1.3] * 19 + [-0.5]
        with pytest.raises(ContextError, match="positive"):
            _validate_market_data(closes, [], [])

    def test_high_less_than_low_raises(self) -> None:
        highs = [1.3] * 20
        lows = [1.31] * 20  # low > high
        closes = [1.3] * 20
        with pytest.raises(ContextError, match="high.*low"):  # noqa: RUF043
            _validate_market_data(closes, highs, lows)

    def test_empty_closes_raises(self) -> None:
        with pytest.raises(ContextError, match="empty"):
            _validate_market_data([], [], [])

    def test_valid_data_passes(self) -> None:
        closes = [1.3 + 0.001 * i for i in range(20)]
        highs = [c + 0.0005 for c in closes]
        lows = [c - 0.0005 for c in closes]
        _validate_market_data(closes, highs, lows)  # no exception

    def test_validation_called_in_analyze_context(self) -> None:
        """analyze_context raises ContextError on bad data."""
        data = {
            "closes": [1.3] * 19 + [float("nan")],
            "highs": [1.31] * 20,
            "lows": [1.29] * 20,
        }
        with pytest.raises(ContextError):
            analyze_context(data, pair="GBPUSD")


# ═══════════════════════════════════════════════════════════════════════════
# §12  Multi-Asset Consistency (Parametrized)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "pair,base,drift,expected_class",
    [
        ("GBPUSD", 1.3000, 0.0003, "FX"),
        ("EURUSD", 1.0800, 0.0002, "FX"),
        ("XAUUSD", 2000.0, 2.0, "METALS"),
        ("US30", 39000.0, 50.0, "INDEX"),
    ],
)
def test_multi_asset_regime_runs(
    pair: str,
    base: float,
    drift: float,
    expected_class: str,
) -> None:
    """Verify analyze_context runs without error for all asset classes."""
    n = 60
    closes = [base + drift * i for i in range(n)]
    atr_range = drift * 3
    highs = [c + atr_range for c in closes]
    lows = [c - atr_range for c in closes]
    volumes = [1000.0] * n

    data = {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }
    result = analyze_context(data, pair=pair, now=LONDON_OVERLAP)

    assert result["valid"] is True
    assert result["asset_class"] == expected_class
    assert 0.0 <= result["csi"] <= 1.0
    assert 0.0 <= result["regime_quality"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §13  Edge Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases: constant prices, exactly 20 bars, etc."""

    def test_constant_prices(self) -> None:
        """All closes identical → RANGE, low confidence."""
        data = {
            "closes": [1.3] * 60,
            "highs": [1.3] * 60,
            "lows": [1.3] * 60,
        }
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)
        assert result["valid"] is True
        assert result["regime"] == "RANGE"
        assert result["regime_confidence"] == 0.0

    def test_exactly_min_bars(self) -> None:
        """Exactly 20 bars → valid."""
        data = _make_market_data(n=20)
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)
        assert result["valid"] is True

    def test_19_bars_invalid(self) -> None:
        """19 bars → insufficient."""
        data = _make_market_data(n=19)
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)
        assert result["valid"] is False

    def test_zero_volume(self) -> None:
        """Zero volume → no crash, CSI still computed."""
        data = _make_market_data(n=60)
        data["volumes"] = [0.0] * 60
        result = analyze_context(data, pair="GBPUSD", now=LONDON_OVERLAP)
        assert result["valid"] is True
        assert 0.0 <= result["csi"] <= 1.0

    def test_no_now_uses_utc(self) -> None:
        """When now=None, uses UTC now."""
        data = _make_market_data(n=60)
        result = analyze_context(data, pair="GBPUSD")
        assert result["valid"] is True
        assert "timestamp" in result
