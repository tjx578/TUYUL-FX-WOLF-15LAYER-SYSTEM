"""Monte Carlo Engines — Confidence simulation + FTTC."""

import math
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ._types import (
    MonteCarloResult, FTTCConfig, FTTCResult, MarketState,
    DEFAULT_MC_SIMULATIONS, DEFAULT_MC_MIN_SIMULATIONS,
)
from ._utils import _clamp, _clamp01


class MonteCarloConfidence:
    """Single Source of Truth for CONF12 (RAW) via simulation."""

    def __init__(self, simulations: int = DEFAULT_MC_SIMULATIONS, seed: Optional[int] = None) -> None:
        if simulations < DEFAULT_MC_MIN_SIMULATIONS:
            raise ValueError(f"simulations too small; minimum {DEFAULT_MC_MIN_SIMULATIONS}")
        self.simulations = simulations
        self._random = random.Random(seed)

    def run(self, *, base_bias: float, coherence: float, volatility_index: float,
            confidence_weight: float = 1.0) -> MonteCarloResult:
        base_bias = _clamp01(float(base_bias))
        c01 = _clamp01(float(coherence) / 100.0)
        vn = _clamp01((float(volatility_index) - 10.0) / 30.0)
        cw = _clamp(float(confidence_weight), 0.85, 1.15)

        samples: List[float] = []; vol_samples: List[float] = []
        ns = 0.35 * (0.4 + 0.6 * vn) * (0.7 + 0.3 * (1.0 - c01))

        for _ in range(self.simulations):
            b = _clamp01(base_bias + self._random.gauss(0.0, ns))
            dec = abs(b - 0.5) * 2.0
            rel = _clamp01(0.55 * c01 + 0.45 * dec)
            conf = rel * (1.0 - 0.35 * vn)
            samples.append(_clamp01(conf)); vol_samples.append(vn)

        cm = sum(samples) / len(samples)
        var = sum((x - cm) ** 2 for x in samples) / len(samples)
        si = _clamp01(1.0 - math.sqrt(var) * 1.35)
        ri = _clamp01((0.6 * c01) + (0.4 * si))

        return MonteCarloResult(
            conf12_raw=float(_clamp01(cm * cw)), reliability_score=float(_clamp01(cm)),
            stability_index=float(si), total_simulations=self.simulations,
            bias_mean=float(base_bias), volatility_mean=float(sum(vol_samples) / len(vol_samples)),
            reflective_integrity=float(ri), timestamp=datetime.now(timezone.utc).isoformat())


class ReflectiveMonteCarlo:
    """FTTC Event-Driven Monte Carlo Engine."""

    def __init__(self, config: Optional[FTTCConfig] = None, seed: Optional[int] = None) -> None:
        self.config = config or FTTCConfig()
        self.states = list(MarketState)
        if seed is None:
            seed = int(datetime.now(timezone.utc).timestamp() * 1000) % (2**31)
        self._seed = seed; self._rng = random.Random(seed)

    def calculate_waiting_time(self, escape_rate: float) -> float:
        return float("inf") if escape_rate <= 0 else self._rng.expovariate(escape_rate)

    def calculate_meta_drift(self, frpc_gradient: float, tii_feedback: float, win_rate_mean: float) -> float:
        return self.config.alpha * frpc_gradient + self.config.beta * tii_feedback + self.config.gamma * win_rate_mean

    def run_simulation(self, initial_state: MarketState, market_data: Dict[str, float],
                       signal_direction: str, entry_price: float, stop_loss: float,
                       take_profit: float) -> FTTCResult:
        wins = 0; returns: List[float] = []; max_dds: List[float] = []
        for _ in range(self.config.iterations):
            o = self._sim_trade(initial_state, signal_direction, entry_price, stop_loss, take_profit)
            if o["won"]: wins += 1; returns.append(o["return"])
            else: returns.append(-o["loss"])
            max_dds.append(o["max_drawdown"])

        wp = wins / self.config.iterations
        er = sum(returns) / len(returns)
        mddp = sum(1 for dd in max_dds if dd > 0.05) / len(max_dds)
        sr = sorted(returns)
        ci = (sr[int(len(sr) * 0.025)], sr[int(len(sr) * 0.975)])

        fg = market_data.get("frpc_gradient", 0.01); tf = market_data.get("tii_feedback", 0.02)
        md = self.calculate_meta_drift(fg, tf, wp)

        # Kelly
        pos_r = [r for r in returns if r > 0]; neg_r = [r for r in returns if r < 0]
        if wp > 0 and pos_r and neg_r:
            aw = sum(pos_r) / len(pos_r); al = abs(sum(neg_r) / len(neg_r))
            if al > 0 and aw > 0:
                k = (wp * aw - (1 - wp) * al) / aw
                os = _clamp(k * 0.5, 0.0, 0.02)
            else: os = 0.01
        else: os = 0.01

        return FTTCResult(win_probability=round(wp, 4), expected_return=round(er, 6),
            max_drawdown_probability=round(mddp, 4), optimal_position_size=round(os, 4),
            confidence_interval=(round(ci[0], 6), round(ci[1], 6)),
            transition_probabilities={s.value: 0.2 for s in self.states if s != initial_state},
            escape_rates={s.value: 0.5 for s in self.states}, meta_drift=round(md, 6))

    def _sim_trade(self, state: MarketState, direction: str, entry: float,
                   sl: float, tp: float) -> Dict[str, Any]:
        fav = state in ({MarketState.BULLISH} if direction == "BUY" else {MarketState.BEARISH})
        won = self._rng.random() < (0.6 if fav else 0.4)
        risk = abs(entry - sl); reward = abs(tp - entry)
        return {"won": won, "return": reward / entry if won else 0,
                "loss": risk / entry if not won else 0, "max_drawdown": self._rng.uniform(0.01, 0.08)}

    def validate_signal(self, signal: Dict[str, Any], market_data: Dict[str, float]) -> Dict[str, Any]:
        regime = market_data.get("regime", "RANGING")
        try: initial = MarketState(regime)
        except ValueError: initial = MarketState.RANGING

        r = self.run_simulation(initial, market_data, signal.get("direction", "BUY"),
            signal.get("entry", 1.0), signal.get("stop_loss", 0.99), signal.get("take_profit", 1.02))
        approved = r.win_probability >= 0.65 and r.meta_drift <= self.config.target_drift and r.max_drawdown_probability < 0.30
        return {"approved": approved, "win_probability": r.win_probability,
                "expected_return": r.expected_return, "optimal_position_size": r.optimal_position_size,
                "confidence_interval": r.confidence_interval, "meta_drift": r.meta_drift,
                "recommendation": "EXECUTE" if approved else "WAIT", "timestamp": r.timestamp}


def create_fttc_engine(config: Optional[Dict[str, Any]] = None) -> ReflectiveMonteCarlo:
    return ReflectiveMonteCarlo(FTTCConfig(**config) if config else FTTCConfig())
