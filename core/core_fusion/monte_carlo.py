"""Monte Carlo Engines -- Confidence simulation + FTTC.

IMPORTANT: These engines are used by core_fusion for CONF12 raw simulation
    and reflective FTTC analysis. They do NOT feed L7 -> L12 directly.
    The L7-to-L12 Monte Carlo path uses engines/monte_carlo_engine.py
    (bootstrap over historical trade returns).
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from typing import Any

from ._types import (
    DEFAULT_MC_MIN_SIMULATIONS,
    DEFAULT_MC_SIMULATIONS,
    FTTCConfig,
    FTTCResult,
    MarketState,
    MonteCarloResult,
)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))


def clamp01(value: float) -> float:
    """Clamp a value between 0 and 1."""
    return max(0.0, min(1.0, value))


class MonteCarloConfidence:
    """Single Source of Truth for CONF12 (RAW) via simulation."""

    def __init__(self, simulations: int = DEFAULT_MC_SIMULATIONS, seed: int | None = None) -> None:
        super().__init__()
        if simulations < DEFAULT_MC_MIN_SIMULATIONS:
            raise ValueError(f"simulations too small; minimum {DEFAULT_MC_MIN_SIMULATIONS}")
        self.simulations = simulations
        self._random = random.Random(seed)

    def run(
        self, *, base_bias: float, coherence: float, volatility_index: float, confidence_weight: float = 1.0
    ) -> MonteCarloResult:
        base_bias_clamped: float = clamp01(float(base_bias))
        c01: float = clamp01(float(coherence) / 100.0)
        vn: float = clamp01((float(volatility_index) - 10.0) / 30.0)
        cw: float = clamp(float(confidence_weight), 0.85, 1.15)

        samples: list[float] = []
        vol_samples: list[float] = []
        ns: float = 0.35 * (0.4 + 0.6 * vn) * (0.7 + 0.3 * (1.0 - c01))

        for _ in range(self.simulations):
            b: float = float(clamp01(base_bias_clamped + self._random.gauss(0.0, ns)))
            dec: float = abs(b - 0.5) * 2.0
            rel: float = float(clamp01(0.55 * c01 + 0.45 * dec))
            conf: float = float(rel * (1.0 - 0.35 * vn))
            samples.append(conf)
            vol_samples.append(vn)

        cm = sum(samples) / len(samples)
        var = sum((x - cm) ** 2 for x in samples) / len(samples)
        si_val: float = 1.0 - math.sqrt(var) * 1.35
        si: float = float(clamp01(si_val))
        ri: float = float(clamp01((0.6 * c01) + (0.4 * si)))

        conf12_raw_val: float = float(clamp01(cm * cw))
        reliability_val: float = float(clamp01(cm))

        return MonteCarloResult(
            conf12_raw=conf12_raw_val,
            reliability_score=reliability_val,
            stability_index=si,
            total_simulations=self.simulations,
            bias_mean=float(base_bias_clamped),
            volatility_mean=float(sum(vol_samples) / len(vol_samples)),
            reflective_integrity=ri,
            timestamp=datetime.now(UTC).isoformat(),
        )


class ReflectiveMonteCarlo:
    """FTTC Event-Driven Monte Carlo Engine."""

    def __init__(self, config: FTTCConfig | None = None, seed: int | None = None) -> None:
        super().__init__()
        self.config = config or FTTCConfig()
        self.states = list(MarketState)
        if seed is None:
            seed = int(datetime.now(UTC).timestamp() * 1000) % (2**31)
        self._seed = seed
        self._rng = random.Random(seed)

    def calculate_waiting_time(self, escape_rate: float) -> float:
        return float("inf") if escape_rate <= 0 else self._rng.expovariate(escape_rate)

    def calculate_meta_drift(self, frpc_gradient: float, tii_feedback: float, win_rate_mean: float) -> float:
        return self.config.alpha * frpc_gradient + self.config.beta * tii_feedback + self.config.gamma * win_rate_mean

    def run_simulation(
        self,
        initial_state: MarketState,
        market_data: dict[str, float],
        signal_direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> FTTCResult:
        wins = 0
        returns: list[float] = []
        max_dds: list[float] = []
        for _ in range(self.config.iterations):
            o = self._sim_trade(initial_state, signal_direction, entry_price, stop_loss, take_profit)
            if o["won"]:
                wins += 1
                returns.append(o["return"])
            else:
                returns.append(-o["loss"])
            max_dds.append(o["max_drawdown"])

        wp = wins / self.config.iterations
        er = sum(returns) / len(returns)
        mddp = sum(1 for dd in max_dds if dd > 0.05) / len(max_dds)
        sr = sorted(returns)
        ci = (sr[int(len(sr) * 0.025)], sr[int(len(sr) * 0.975)])

        fg = market_data.get("frpc_gradient", 0.01)
        tf = market_data.get("tii_feedback", 0.02)
        md = self.calculate_meta_drift(fg, tf, wp)

        # Kelly
        optimal_size: float = 0.01
        pos_r = [r for r in returns if r > 0]
        neg_r = [r for r in returns if r < 0]
        if wp > 0 and pos_r and neg_r:
            aw = sum(pos_r) / len(pos_r)
            al = abs(sum(neg_r) / len(neg_r))
            if al > 0 and aw > 0:
                k = (wp * aw - (1 - wp) * al) / aw
                optimal_size = clamp(k * 0.5, 0.0, 0.02)

        return FTTCResult(
            win_probability=round(wp, 4),
            expected_return=round(er, 6),
            max_drawdown_probability=round(mddp, 4),
            optimal_position_size=round(optimal_size, 4),
            confidence_interval=(round(ci[0], 6), round(ci[1], 6)),
            transition_probabilities={s.value: 0.2 for s in self.states if s != initial_state},
            escape_rates={s.value: 0.5 for s in self.states},
            meta_drift=round(md, 6),
        )

    def _sim_trade(self, state: MarketState, direction: str, entry: float, sl: float, tp: float) -> dict[str, Any]:
        fav = state in ({MarketState.BULLISH} if direction == "BUY" else {MarketState.BEARISH})
        won = self._rng.random() < (0.6 if fav else 0.4)
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        return {
            "won": won,
            "return": reward / entry if won else 0,
            "loss": risk / entry if not won else 0,
            "max_drawdown": self._rng.uniform(0.01, 0.08),
        }

    def validate_signal(self, signal: dict[str, Any], market_data: dict[str, float]) -> dict[str, Any]:
        regime = market_data.get("regime", "RANGING")
        try:
            initial = MarketState(regime)
        except ValueError:
            initial = MarketState.RANGING

        from schemas.direction import normalize_direction

        direction = normalize_direction(signal.get("direction"), signal.get("verdict")) or "BUY"

        r = self.run_simulation(
            initial,
            market_data,
            direction,
            signal.get("entry", 1.0),
            signal.get("stop_loss", 0.99),
            signal.get("take_profit", 1.02),
        )
        approved = (
            r.win_probability >= 0.65 and r.meta_drift <= self.config.target_drift and r.max_drawdown_probability < 0.30
        )
        return {
            "approved": approved,
            "win_probability": r.win_probability,
            "expected_return": r.expected_return,
            "optimal_position_size": r.optimal_position_size,
            "confidence_interval": r.confidence_interval,
            "meta_drift": r.meta_drift,
            "recommendation": "EXECUTE" if approved else "WAIT",
            "timestamp": r.timestamp,
        }


def create_fttc_engine(config: dict[str, Any] | None = None) -> ReflectiveMonteCarlo:
    return ReflectiveMonteCarlo(FTTCConfig(**config) if config else FTTCConfig())
