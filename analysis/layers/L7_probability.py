"""
L7 — Probability Estimation
Statistical, NOT predictive.
"""

from config.constants import get_threshold

# Liquidity and Monte Carlo thresholds
LIQUIDITY_SWEEP_THRESHOLD: float = get_threshold("liquidity.sweep_threshold", 0.65)
MC_DEFAULT_RUNS: int = get_threshold("monte_carlo.default_runs", 1000)
MC_DEFAULT_HORIZON: int = get_threshold("monte_carlo.default_horizon", 50)
MC_WIN_PROB_MIN: float = get_threshold("monte_carlo.gate.win_prob_min", 68.0)
MC_PROFIT_FACTOR_MIN: float = get_threshold("monte_carlo.gate.profit_factor_min", 2.0)
MC_MAX_DRAWDOWN: float = get_threshold("monte_carlo.gate.max_drawdown", 5.0)


class L7ProbabilityAnalyzer:
    def analyze(
        self, 
        symbol: str, 
        technical_score: float, 
        rr: float = 2.0, 
        historical_win_rate: float | None = None
    ) -> dict:
        """
        Simple mapping placeholder:
        Higher technical score → higher probability.
        
        Args:
            symbol: Trading pair symbol
            technical_score: Technical score from L4
            rr: Risk-reward ratio
            historical_win_rate: Optional historical win rate
        """
        if technical_score is None:
            return {"valid": False}

        win_prob = min(80.0, max(40.0, technical_score * 0.8))
        profit_factor = round(1.0 + (technical_score / 100), 2)

        return {
            "win_probability": win_prob,
            "profit_factor": profit_factor,
            "valid": True,
        }


# Placeholder
