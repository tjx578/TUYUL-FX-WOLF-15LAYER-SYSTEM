"""
Volatility Analysis
"""
from __future__ import annotations

from typing import Any

from context.live_context_bus import LiveContextBus


class VolatilityAnalyzer:
    def __init__(self):
        self.context = LiveContextBus()

    def analyze(self, symbol: str) -> dict[str, Any]:
        """
        Analyze volatility for a symbol using ATR.

        Args:
            symbol: Trading pair symbol

        Returns:
            Dict with profile, atr, and valid status
        """
        candle = self.context.get_candle(symbol, "H1")
        if not candle:
            return {"valid": False, "profile": "UNKNOWN", "atr": 0.0}

        # For basic implementation, use simplified ATR estimation
        # In production, would need multiple candles for proper ATR calculation
        high = candle.get("high", 0)
        low = candle.get("low", 0)
        close = candle.get("close", 0)

        if not (high and low and close):
            return {"valid": False, "profile": "UNKNOWN", "atr": 0.0}

        # Simplified ATR as range
        atr = high - low

        # Profile determination based on ATR relative to price
        atr_percent = (atr / close) * 100 if close > 0 else 0

        if atr_percent > 1.0:
            profile = "HIGH"
        elif atr_percent > 0.5:
            profile = "MEDIUM"
        else:
            profile = "LOW"

        return {
            "atr": atr,
            "profile": profile,
            "valid": True,
        }

    def analyze_macro(self, symbol: str) -> dict[str, Any]:
        """
        Analyze macro volatility using MN (Monthly) candles.

        Args:
            symbol: Trading pair symbol

        Returns:
            Dict with mn_atr, macro_vol_ratio, macro_profile, valid
        """
        mn_candles = self.context.get_candle_history(symbol, "MN", count=14)
        if len(mn_candles) < 2:
            return {
                "valid": False,
                "macro_profile": "UNKNOWN",
                "mn_atr": 0.0,
                "macro_vol_ratio": 1.0,
            }

        # Calculate true range for each candle
        true_ranges: list[float] = []
        for i in range(1, len(mn_candles)):
            high = mn_candles[i]["high"]
            low = mn_candles[i]["low"]
            prev_close = mn_candles[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if not true_ranges:
            return {
                "valid": False,
                "macro_profile": "UNKNOWN",
                "mn_atr": 0.0,
                "macro_vol_ratio": 1.0,
            }

        mn_atr = true_ranges[-1]  # Latest ATR
        rolling_mean = sum(true_ranges) / len(true_ranges)
        macro_vol_ratio = mn_atr / rolling_mean if rolling_mean > 0 else 1.0

        if macro_vol_ratio > 1.4:
            profile = "EXPANSION"
        elif macro_vol_ratio > 0.8:
            profile = "NORMAL"
        else:
            profile = "CONTRACTION"

        return {
            "mn_atr": round(mn_atr, 6),
            "macro_vol_ratio": round(macro_vol_ratio, 4),
            "macro_profile": profile,
            "valid": True,
        }
