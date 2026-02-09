"""
Volatility Analysis
"""

from typing import Dict, List

from analysis.market.indicators import IndicatorEngine


class VolatilityAnalyzer:
    def analyze(self, highs: List[float], lows: List[float], closes: List[float]) -> Dict:
        atr = IndicatorEngine.atr(highs, lows, closes)

        if atr is None:
            return {"valid": False}

        profile = "NORMAL"
        if atr > sum(highs) / len(highs) * 0.01:
            profile = "HIGH"

        return {
            "atr": atr,
            "profile": profile,
            "valid": True,
        }
# Placeholder
