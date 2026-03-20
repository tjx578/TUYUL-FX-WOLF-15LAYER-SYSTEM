"""
Monthly Regime Analyzer

Provides top-level macro regime classification using Monthly (MN) timeframe:
1. Macro regime classifier (BULLISH_EXPANSION, BEARISH_EXPANSION, CONSOLIDATION, TRANSITION)
2. Expansion / contraction detector via ATR
3. Structural dominance filter
4. Hard bias override layer (counter-macro trades penalized)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from context.live_context_bus import LiveContextBus


class MonthlyRegimeAnalyzer:
    """
    Monthly Regime Analyzer.

    Analyzes Monthly (MN) timeframe candles to determine macro market regime,
    volatility phase, liquidity zones, and bias override for counter-macro trades.
    """

    def __init__(self) -> None:
        """Initialize the Monthly Regime Analyzer."""
        self.context_bus = LiveContextBus()

    def analyze(self, symbol: str) -> dict[str, Any]:
        """
        Analyze monthly regime for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD")

        Returns:
            Dictionary containing:
                - regime: BULLISH_EXPANSION, BEARISH_EXPANSION, CONSOLIDATION,
                  TRANSITION, or UNKNOWN
                - phase: EXPANSION, CONTRACTION, or NEUTRAL
                - mn_atr: Monthly ATR value
                - macro_vol_ratio: Current MN ATR / rolling mean
                - liquidity: Macro liquidity zones and proximity
                - bias_override: Counter-macro trade penalties
                - alignment: True if MN agrees with lower TFs
                - valid: Whether analysis is valid
        """
        # Get MN candle history (24 months for comprehensive analysis)
        mn_data = self.context_bus.get_candle_history(symbol, "MN", count=24)

        if len(mn_data) < 2:
            logger.warning(
                f"Insufficient MN data for {symbol}: {len(mn_data)} candles (need 2+)"
            )
            return self._invalid_result()

        # Detect regime
        regime = self._detect_regime(mn_data)

        # Calculate ATR and volatility metrics
        mn_atr, macro_vol_ratio, phase = self._calculate_volatility(mn_data)

        # Map liquidity zones
        liquidity = self._map_liquidity_zones(mn_data)

        # Determine bias override (this requires trade direction which we don't have here)
        # Will be applied in synthesis or verdict engine
        bias_override = {
            "active": False,
            "penalized_direction": None,
            "confidence_multiplier": 1.0,
        }

        # Regime-based bias override setup
        if regime == "BULLISH_EXPANSION":
            bias_override = {
                "active": True,
                "penalized_direction": "SELL",
                "confidence_multiplier": 0.7,  # Penalty for counter-macro
            }
        elif regime == "BEARISH_EXPANSION":
            bias_override = {
                "active": True,
                "penalized_direction": "BUY",
                "confidence_multiplier": 0.7,  # Penalty for counter-macro
            }

        logger.info(
            f"MN Regime Analysis for {symbol}: regime={regime}, phase={phase}, "
            f"mn_atr={mn_atr:.6f}, macro_vol_ratio={macro_vol_ratio:.4f}"
        )

        return {
            "regime": regime,
            "phase": phase,
            "mn_atr": mn_atr,
            "macro_vol_ratio": macro_vol_ratio,
            "liquidity": liquidity,
            "bias_override": bias_override,
            "alignment": True,  # Placeholder - will be set by MTA layer
            "valid": True,
        }

    def _detect_regime(self, mn_data: list[dict]) -> str:
        """
        Detect monthly regime type.

        Args:
            mn_data: List of monthly candle dictionaries

        Returns:
            Regime type: BULLISH_EXPANSION, BEARISH_EXPANSION, CONSOLIDATION, TRANSITION, or UNKNOWN
        """
        if len(mn_data) < 2:
            return "UNKNOWN"

        last = mn_data[-1]
        prev = mn_data[-2]

        range_size = last["high"] - last["low"]
        prev_range = prev["high"] - prev["low"]
        bullish = last["close"] > last["open"]
        expansion = range_size > prev_range * 1.2

        if bullish and expansion:
            return "BULLISH_EXPANSION"
        if not bullish and expansion:
            return "BEARISH_EXPANSION"
        if not expansion:
            return "CONSOLIDATION"
        return "TRANSITION"

    def _calculate_volatility(self, mn_data: list[dict]) -> tuple[float, float, str]:
        """
        Calculate MN ATR and volatility metrics.

        Args:
            mn_data: List of monthly candle dictionaries

        Returns:
            Tuple of (mn_atr, macro_vol_ratio, phase)
        """
        if len(mn_data) < 2:
            return 0.0, 1.0, "NEUTRAL"

        # Calculate true ranges for all available candles
        true_ranges: list[float] = []
        for i in range(1, len(mn_data)):
            high = mn_data[i]["high"]
            low = mn_data[i]["low"]
            prev_close = mn_data[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if not true_ranges:
            return 0.0, 1.0, "NEUTRAL"

        # Current MN ATR (latest true range)
        mn_atr = true_ranges[-1]

        # Rolling mean of last 12 MN ATRs (or all if less than 12)
        lookback = min(12, len(true_ranges))
        rolling_mean = sum(true_ranges[-lookback:]) / lookback

        # Macro volatility ratio
        macro_vol_ratio = mn_atr / rolling_mean if rolling_mean > 0 else 1.0

        # Determine phase
        if macro_vol_ratio > 1.4:
            phase = "EXPANSION"
        elif macro_vol_ratio > 0.8:
            phase = "NEUTRAL"
        else:
            phase = "CONTRACTION"

        return round(mn_atr, 6), round(macro_vol_ratio, 4), phase

    def _map_liquidity_zones(self, mn_data: list[dict]) -> dict[str, Any]:
        """
        Map macro liquidity zones from MN candles.

        Args:
            mn_data: List of monthly candle dictionaries

        Returns:
            Dictionary with liquidity zone data
        """
        if len(mn_data) < 2:
            return {
                "macro_buy_liquidity": 0.0,
                "macro_sell_liquidity": 0.0,
                "near_macro_liquidity": False,
            }

        # Get last 5 completed months (exclude current incomplete month)
        completed_months = mn_data[-6:-1] if len(mn_data) >= 6 else mn_data[:-1]

        if not completed_months:
            return {
                "macro_buy_liquidity": 0.0,
                "macro_sell_liquidity": 0.0,
                "near_macro_liquidity": False,
            }

        mn_highs = [c["high"] for c in completed_months]
        mn_lows = [c["low"] for c in completed_months]

        macro_buy_liquidity = max(mn_highs) if mn_highs else 0.0
        macro_sell_liquidity = min(mn_lows) if mn_lows else 0.0

        # Check if current price is within 0.5% of either liquidity zone
        current_price = mn_data[-1]["close"]
        near_buy = False
        near_sell = False

        # Only check proximity if liquidity zones are valid (non-zero)
        if macro_buy_liquidity > 0 and current_price > 0:
            near_buy = abs(current_price - macro_buy_liquidity) / current_price <= 0.005
        if macro_sell_liquidity > 0 and current_price > 0:
            near_sell = abs(current_price - macro_sell_liquidity) / current_price <= 0.005

        near_macro_liquidity = near_buy or near_sell

        return {
            "macro_buy_liquidity": round(macro_buy_liquidity, 5),
            "macro_sell_liquidity": round(macro_sell_liquidity, 5),
            "near_macro_liquidity": near_macro_liquidity,
        }

    def _invalid_result(self) -> dict[str, Any]:
        """
        Return invalid result structure.

        Returns:
            Dictionary with valid=False and default values
        """
        return {
            "regime": "UNKNOWN",
            "phase": "NEUTRAL",
            "mn_atr": 0.0,
            "macro_vol_ratio": 1.0,
            "liquidity": {
                "macro_buy_liquidity": 0.0,
                "macro_sell_liquidity": 0.0,
                "near_macro_liquidity": False,
            },
            "bias_override": {
                "active": False,
                "penalized_direction": None,
                "confidence_multiplier": 1.0,
            },
            "alignment": False,
            "valid": False,
        }
