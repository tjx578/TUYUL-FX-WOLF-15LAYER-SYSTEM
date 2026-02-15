"""Integration tests for analysis/layers/L7_probability.py."""  # noqa: N999

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]

from analysis.layers.L7_probability import L7ProbabilityAnalyzer


def _make_returns(n: int = 100, win_rate: float = 0.65, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    returns = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(10, 100)))
        else:
            returns.append(float(rng.uniform(-80, -5)))
    return returns


class TestL7ProbabilityAnalyzer:

    def test_analyze_with_returns_pass(self) -> None:
        analyzer = L7ProbabilityAnalyzer(mc_simulations=200, mc_seed=42)
        returns = _make_returns(100, win_rate=0.75)
        result = analyzer.analyze(
            "EURUSD",
            technical_score=80,
            trade_returns=returns,
            prior_wins=20,
            prior_losses=5,
        )

        assert result["valid"] is True
        assert result["symbol"] == "EURUSD"
        assert result["win_probability"] > 0
        assert result["validation"] in ("PASS", "CONDITIONAL", "FAIL")
        assert result["bayesian_posterior"] > 0

    def test_analyze_without_returns(self) -> None:
        analyzer = L7ProbabilityAnalyzer(mc_simulations=100, mc_seed=42)
        result = analyzer.analyze("GBPUSD", technical_score=50)

        assert result["valid"] is True
        # MC skipped → defaults
        assert result["win_probability"] == 0.0
        assert result["profit_factor"] == 0.0
        assert result["validation"] == "FAIL"
        # Bayesian should still run
        assert result["bayesian_posterior"] > 0

    def test_analyze_insufficient_returns(self) -> None:
        analyzer = L7ProbabilityAnalyzer(mc_simulations=100, mc_seed=42)
        result = analyzer.analyze(
            "USDJPY",
            technical_score=60,
            trade_returns=[1.0, -0.5, 2.0],
        )

        assert result["valid"] is True
        assert result["win_probability"] == 0.0
        assert result["mc_passed_threshold"] is False

    def test_gate_logic_conditional(self) -> None:
        analyzer = L7ProbabilityAnalyzer(mc_simulations=300, mc_seed=42)
        # ~55% win rate → should be CONDITIONAL or FAIL
        returns = _make_returns(100, win_rate=0.55, seed=11)
        result = analyzer.analyze(
            "AUDUSD",
            technical_score=60,
            trade_returns=returns,
        )
        assert result["validation"] in ("CONDITIONAL", "FAIL")

    def test_all_expected_keys_present(self) -> None:
        analyzer = L7ProbabilityAnalyzer(mc_simulations=100, mc_seed=42)
        result = analyzer.analyze("NZDUSD", technical_score=70)

        expected_keys = {
            "symbol", "win_probability", "profit_factor", "conf12_raw",
            "max_drawdown", "validation", "valid", "bayesian_posterior",
            "bayesian_ci_low", "bayesian_ci_high", "risk_of_ruin",
            "expected_value", "mc_passed_threshold",
        }
        assert expected_keys.issubset(result.keys())
