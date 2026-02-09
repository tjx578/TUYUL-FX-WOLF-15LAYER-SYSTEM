"""
Risk Multiplier Engine
Adjusts risk exposure based on drawdown state.
"""


class RiskMultiplier:
    def calculate(self, drawdown_level: float) -> float:
        """
        drawdown_level: percentage used of max drawdown
        """
        if drawdown_level < 0.3:
            return 1.0
        if drawdown_level < 0.6:
            return 0.75
        if drawdown_level < 0.8:
            return 0.5
        return 0.25
