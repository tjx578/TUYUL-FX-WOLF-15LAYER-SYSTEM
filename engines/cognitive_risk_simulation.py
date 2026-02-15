"""Cognitive Risk Simulation — Layer-10 risk scenario modelling.

Runs Monte Carlo-style simulations and risk scenarios to estimate
drawdown probability, expected payoff, and position risk metrics.

ANALYSIS-ONLY module. No execution side-effects. Does NOT access account state.
"""

from __future__ import annotations

import logging
import math

from dataclasses import dataclass, field
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class RiskSimulationResult:
    """Output of the Risk Simulation Engine."""

    # Core metrics (market-side, not account-side)
    expected_move_pct: float = 0.0
    volatility_pct: float = 0.0
    downside_risk_pct: float = 0.0
    upside_potential_pct: float = 0.0

    # Scenario simulation
    win_probability: float = 0.5
    loss_probability: float = 0.5
    expected_rr: float = 0.0

    # Drawdown simulation
    max_adverse_excursion: float = 0.0  # MAE as price %
    max_favorable_excursion: float = 0.0  # MFE as price %

    # Risk classification
    risk_class: str = "MODERATE"  # LOW | MODERATE | HIGH | EXTREME
    risk_score: float = 0.5  # 0.0–1.0 (lower is riskier)

    # Simulation details
    simulations_run: int = 0
    scenario_results: list[dict[str, float]] = field(default_factory=list)

    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0 and self.simulations_run > 0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CognitiveRiskSimulation:
    """Risk simulation engine — analysis only, no execution.

    Parameters
    ----------
    num_simulations : int
        Number of Monte Carlo paths to simulate.
    horizon_bars : int
        Forward simulation horizon in bars.
    seed : int or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        num_simulations: int = 500,
        horizon_bars: int = 20,
        seed: int | None = None,
        **_extra: Any,
    ) -> None:
        self.num_simulations = num_simulations
        self.horizon_bars = horizon_bars
        self.rng = np.random.default_rng(seed)

    def analyze(
        self,
        candles: dict[str, list[dict[str, Any]]],
        direction: str = "NONE",
        entry_price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        symbol: str = "",
    ) -> RiskSimulationResult:
        """Run risk simulations.

        Parameters
        ----------
        candles : dict
            Multi-TF candle data for volatility estimation.
        direction : str
            "BUY" | "SELL" | "NONE".
        entry_price, stop_loss, take_profit : float
            Proposed trade levels (from precision engine).
        """
        if not candles or direction == "NONE":
            return RiskSimulationResult(
                metadata={"symbol": symbol, "error": "no_data_or_direction"}
            )

        primary_tf = self._select_primary(candles)
        tf_candles = candles[primary_tf]

        if len(tf_candles) < 20:
            return RiskSimulationResult(
                metadata={"symbol": symbol, "error": "insufficient_candles"}
            )

        closes = np.array([c.get("close", 0.0) for c in tf_candles], dtype=np.float64)
        returns = np.diff(np.log(closes[closes > 0]))
        returns = returns[np.isfinite(returns)]

        if len(returns) < 10:
            return RiskSimulationResult(
                metadata={"symbol": symbol, "error": "insufficient_returns"}
            )

        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        current_price = float(closes[-1])

        if entry_price <= 0:
            entry_price = current_price
        if stop_loss <= 0 or take_profit <= 0:
            return RiskSimulationResult(
                expected_move_pct=mu * self.horizon_bars * 100,
                volatility_pct=sigma * math.sqrt(self.horizon_bars) * 100,
                risk_class="MODERATE",
                risk_score=0.5,
                confidence=0.3,
                metadata={"symbol": symbol, "note": "no_sl_tp_provided"},
            )

        # Monte Carlo simulation
        wins = 0
        losses = 0
        mae_list: list[float] = []
        mfe_list: list[float] = []
        scenarios: list[dict[str, float]] = []

        for _ in range(self.num_simulations):
            path = self._simulate_path(entry_price, mu, sigma, self.horizon_bars)
            result = self._evaluate_path(path, entry_price, stop_loss, take_profit, direction)
            if result["outcome"] == "WIN":
                wins += 1
            elif result["outcome"] == "LOSS":
                losses += 1
            mae_list.append(result["mae"])
            mfe_list.append(result["mfe"])
            scenarios.append(result)

        total = wins + losses if (wins + losses) > 0 else 1
        win_prob = wins / total
        loss_prob = losses / total

        risk_dist = abs(entry_price - stop_loss)
        reward_dist = abs(take_profit - entry_price)
        expected_rr = (reward_dist / risk_dist) if risk_dist > 0 else 0.0
        win_prob * reward_dist - loss_prob * risk_dist # type: ignore

        avg_mae = float(np.mean(mae_list)) if mae_list else 0.0
        avg_mfe = float(np.mean(mfe_list)) if mfe_list else 0.0

        vol_pct = sigma * math.sqrt(self.horizon_bars) * 100

        # Risk classification
        if win_prob >= 0.65 and expected_rr >= 2.0:
            risk_class = "LOW"
            risk_score = 0.85
        elif win_prob >= 0.50 and expected_rr >= 1.5:
            risk_class = "MODERATE"
            risk_score = 0.6
        elif win_prob >= 0.40:
            risk_class = "HIGH"
            risk_score = 0.35
        else:
            risk_class = "EXTREME"
            risk_score = 0.15

        confidence = min(1.0, 0.4 + (self.num_simulations / 1000) * 0.3 + (len(returns) / 100) * 0.3)

        return RiskSimulationResult(
            expected_move_pct=round(mu * self.horizon_bars * 100, 4),
            volatility_pct=round(vol_pct, 4),
            downside_risk_pct=round(avg_mae / entry_price * 100, 4),
            upside_potential_pct=round(avg_mfe / entry_price * 100, 4),
            win_probability=round(win_prob, 4),
            loss_probability=round(loss_prob, 4),
            expected_rr=round(expected_rr, 2),
            max_adverse_excursion=round(avg_mae, 6),
            max_favorable_excursion=round(avg_mfe, 6),
            risk_class=risk_class,
            risk_score=round(risk_score, 3),
            simulations_run=self.num_simulations,
            scenario_results=scenarios[:10],  # Keep top 10 for metadata
            confidence=round(confidence, 3),
            metadata={"symbol": symbol, "primary_tf": primary_tf, "mu": mu, "sigma": sigma},
        )

    def _simulate_path(
        self, start_price: float, mu: float, sigma: float, steps: int
    ) -> np.ndarray:
        """Simulate a GBM price path."""
        shocks = self.rng.normal(mu, sigma, steps)
        log_prices = np.cumsum(shocks)
        prices = start_price * np.exp(log_prices)
        return np.insert(prices, 0, start_price)

    @staticmethod
    def _evaluate_path(
        path: np.ndarray,
        entry: float,
        sl: float,
        tp: float,
        direction: str,
    ) -> dict[str, Any]:
        """Evaluate a simulated path against SL/TP."""
        is_buy = direction == "BUY"
        mae = 0.0
        mfe = 0.0
        outcome = "NEUTRAL"

        for price in path[1:]:
            if is_buy:
                pnl = price - entry
            else:
                pnl = entry - price

            mfe = max(mfe, pnl)
            if pnl < -mae:
                mae = -pnl

            # Check SL
            if is_buy and price <= sl:
                outcome = "LOSS"
                break
            if not is_buy and price >= sl:
                outcome = "LOSS"
                break

            # Check TP
            if is_buy and price >= tp:
                outcome = "WIN"
                break
            if not is_buy and price <= tp:
                outcome = "WIN"
                break

        return {"outcome": outcome, "mae": mae, "mfe": mfe}

    @staticmethod
    def _select_primary(candles: dict[str, list[dict[str, Any]]]) -> str:
        for tf in ["M15", "H1", "H4"]:
            if tf in candles and len(candles[tf]) >= 20:
                return tf
        return max(candles, key=lambda k: len(candles[k]))
