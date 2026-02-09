"""
Risk Multiplier Engine
Adjusts risk exposure based on drawdown state.
"""


class RiskMultiplier:
    def calculate(self, drawdown_level: float) -> float:
        """
        Calculate the risk multiplier based on the current drawdown.

        Parameters
        ----------
        drawdown_level : float
            Fraction of the maximum allowed drawdown that has been used,
            expressed as a value between 0.0 and 1.0 (e.g. 0.3 == 30%).
        """
        # Normalize input to a float in the [0.0, 1.0] range to avoid
        # ambiguity between percentages (0–100) and fractions (0.0–1.0).
        level = max(0.0, min(float(drawdown_level), 1.0))

        if level < 0.3:
            return 1.0
        if level < 0.6:
            return 0.75
        if level < 0.8:
            return 0.5
        return 0.25
# Placeholder
