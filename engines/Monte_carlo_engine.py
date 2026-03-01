"""Monte Carlo Engine -- Bootstrap simulation over historical trade returns.

ANALYSIS-ONLY module. No execution side-effects.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


class MonteCarloEngineError(ValueError):
    """Base exception for Monte Carlo engine validation errors."""


@dataclass(frozen=True)
class MonteCarloResult:
    win_probability: float
    simulations: int
    max_drawdown_mean: float
    max_drawdown_p95: float
    profit_factor: float
    expected_value: float
    risk_of_ruin: float
    passed_threshold: bool

    @property
    def passed(self) -> bool:
        return self.passed_threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "win_probability": float(self.win_probability),
            "simulations": int(self.simulations),
            "max_drawdown_mean": float(self.max_drawdown_mean),
            "max_drawdown_p95": float(self.max_drawdown_p95),
            "profit_factor": float(self.profit_factor),
            "expected_value": float(self.expected_value),
            "risk_of_ruin": float(self.risk_of_ruin),
            "passed_threshold": bool(self.passed_threshold),
        }


class MonteCarloEngine:
    def __init__(
        self,
        simulations: int = 1000,
        seed: int | None = 42,
        min_trades: int = 30,
        win_threshold: float = 0.60,
        pf_threshold: float = 1.5,
        ruin_capital_fraction: float = 0.20,
    ) -> None:
        if simulations <= 0:
            raise MonteCarloEngineError("simulations must be > 0")
        if min_trades <= 0:
            raise MonteCarloEngineError("min_trades must be > 0")
        if not (0.0 < win_threshold <= 1.0):
            raise MonteCarloEngineError("win_threshold must be in (0, 1]")
        if pf_threshold <= 0.0:
            raise MonteCarloEngineError("pf_threshold must be > 0")
        if not (0.0 < ruin_capital_fraction < 1.0):
            raise MonteCarloEngineError("ruin_capital_fraction must be in (0, 1)")
        super().__init__()
        self.simulations = int(simulations)
        self.min_trades = int(min_trades)
        self.win_threshold = float(win_threshold)
        self.pf_threshold = float(pf_threshold)
        self.ruin_capital_fraction = float(ruin_capital_fraction)
        self._rng = np.random.default_rng(seed)

    def run(self, returns: Iterable[float]) -> MonteCarloResult:
        r = self._to_returns_array(returns)
        if r.size < self.min_trades:
            raise ValueError(f"Minimum {self.min_trades} trades required")
        win_probability_obs = float(np.mean(r > 0.0))
        profit_factor_obs = float(self._profit_factor(r))
        expected_value_obs = float(np.mean(r))
        n = int(r.size)
        idx = self._rng.integers(low=0, high=n, size=(self.simulations, n), dtype=np.int64)
        sims = r[idx]
        equity = np.cumsum(sims, axis=1)
        peak = np.maximum.accumulate(equity, axis=1)
        drawdown = equity - peak
        max_drawdown: NDArray[np.float64] = np.min(drawdown, axis=1)
        max_drawdown_mean = float(np.mean(max_drawdown))
        max_drawdown_p95 = float(np.percentile(max_drawdown, 5))
        ruin_threshold = -abs(self.ruin_capital_fraction)
        ruin_mask: NDArray[np.float64] = (max_drawdown <= ruin_threshold).astype(np.float64)
        risk_of_ruin = float(np.mean(ruin_mask))
        passed_threshold = bool(
            (win_probability_obs >= self.win_threshold) and (profit_factor_obs >= self.pf_threshold)
        )
        return MonteCarloResult(
            win_probability=win_probability_obs,
            simulations=self.simulations,
            max_drawdown_mean=max_drawdown_mean,
            max_drawdown_p95=max_drawdown_p95,
            profit_factor=profit_factor_obs,
            expected_value=expected_value_obs,
            risk_of_ruin=risk_of_ruin,
            passed_threshold=passed_threshold,
        )

    @staticmethod
    def _to_returns_array(returns: Iterable[float]) -> NDArray[np.float64]:
        try:
            r = np.asarray(list(returns), dtype=np.float64)
        except (TypeError, ValueError) as e:
            raise MonteCarloEngineError("returns must be an iterable of floats") from e
        if r.ndim != 1:
            raise MonteCarloEngineError("returns must be a 1D sequence")
        if r.size == 0:
            raise MonteCarloEngineError("returns must not be empty")
        if not np.all(np.isfinite(r)):
            raise MonteCarloEngineError("returns contains NaN or infinite values")
        return r

    @staticmethod
    def _profit_factor(r: NDArray[np.float64]) -> float:
        gains = r[r > 0.0]
        losses = r[r < 0.0]
        gross_profit = float(np.sum(gains)) if gains.size else 0.0
        gross_loss = float(-np.sum(losses)) if losses.size else 0.0
        if gross_loss == 0.0:
            return 999.0 if gross_profit > 0.0 else 0.0
        pf = gross_profit / gross_loss
        if math.isnan(pf) or math.isinf(pf) or pf < 0.0:
            return 0.0
        return float(pf)


__all__ = ["MonteCarloEngine", "MonteCarloEngineError", "MonteCarloResult"]
