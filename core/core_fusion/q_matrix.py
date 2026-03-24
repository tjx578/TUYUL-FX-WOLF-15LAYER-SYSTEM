"""Q-Matrix Generator for FTTC Monte Carlo."""
from __future__ import annotations

from typing import Any

from ._types import QMatrixConfig, TransitionState


class QMatrixGenerator:
    """Generates Q-Matrix defining transition rates between market states."""

    def __init__(self, config: QMatrixConfig | None = None) -> None:
        self.config = config or QMatrixConfig()
        self.states = list(TransitionState)
        self.n_states = len(self.states)
        self.state_to_idx = {s: i for i, s in enumerate(self.states)}
        self.q_matrix: list[list[float]] | None = None

    def _calculate_base_rates(self) -> list[list[float]]:
        rates = [[0.0] * self.n_states for _ in range(self.n_states)]
        ts = TransitionState
        bt = {
            (ts.STRONG_BULLISH, ts.WEAK_BULLISH): 0.25,
            (ts.STRONG_BULLISH, ts.NEUTRAL): 0.10,
            (ts.STRONG_BULLISH, ts.HIGH_VOLATILITY): 0.05,
            (ts.WEAK_BULLISH, ts.STRONG_BULLISH): 0.20,
            (ts.WEAK_BULLISH, ts.NEUTRAL): 0.30,
            (ts.WEAK_BULLISH, ts.WEAK_BEARISH): 0.15,
            (ts.NEUTRAL, ts.WEAK_BULLISH): 0.25,
            (ts.NEUTRAL, ts.WEAK_BEARISH): 0.25,
            (ts.NEUTRAL, ts.LOW_VOLATILITY): 0.10,
            (ts.WEAK_BEARISH, ts.STRONG_BEARISH): 0.20,
            (ts.WEAK_BEARISH, ts.NEUTRAL): 0.30,
            (ts.WEAK_BEARISH, ts.WEAK_BULLISH): 0.15,
            (ts.STRONG_BEARISH, ts.WEAK_BEARISH): 0.25,
            (ts.STRONG_BEARISH, ts.NEUTRAL): 0.10,
            (ts.STRONG_BEARISH, ts.HIGH_VOLATILITY): 0.05,
            (ts.HIGH_VOLATILITY, ts.STRONG_BULLISH): 0.15,
            (ts.HIGH_VOLATILITY, ts.STRONG_BEARISH): 0.15,
            (ts.HIGH_VOLATILITY, ts.NEUTRAL): 0.20,
            (ts.LOW_VOLATILITY, ts.NEUTRAL): 0.30,
            (ts.LOW_VOLATILITY, ts.WEAK_BULLISH): 0.15,
            (ts.LOW_VOLATILITY, ts.WEAK_BEARISH): 0.15,
        }
        for (f, t), rate in bt.items():
            rates[self.state_to_idx[f]][self.state_to_idx[t]] = rate * self.config.base_transition_rate
        return rates

    def generate(self, market_data: dict[str, float]) -> list[list[float]]:
        rates = self._calculate_base_rates()
        vol = market_data.get("volatility", 1.0)
        ts = market_data.get("trend_strength", 0.0)
        vf = 1 + (vol - 1) * self.config.volatility_sensitivity
        hv = self.state_to_idx[TransitionState.HIGH_VOLATILITY]
        lv = self.state_to_idx[TransitionState.LOW_VOLATILITY]

        if vol > 1.5:
            for i in range(self.n_states):
                rates[i][hv] *= vf
                rates[lv][i] *= vf
        elif vol < 0.5:
            for i in range(self.n_states):
                rates[i][lv] *= 2 - vf
                rates[hv][i] *= 2 - vf

        if ts > 0.5:
            sb = self.state_to_idx[TransitionState.STRONG_BULLISH]
            for i in range(self.n_states):
                rates[i][sb] *= 1 + ts * self.config.trend_sensitivity
        elif ts < -0.5:
            sbe = self.state_to_idx[TransitionState.STRONG_BEARISH]
            for i in range(self.n_states):
                rates[i][sbe] *= 1 + abs(ts) * self.config.trend_sensitivity

        for i in range(self.n_states):
            rs = 0.0
            for j in range(self.n_states):
                if i != j:
                    rates[i][j] += self.config.regularization
                    rs += rates[i][j]
            rates[i][i] = -rs
        self.q_matrix = rates
        return rates

    def get_escape_rate(self, state: TransitionState) -> float:
        if self.q_matrix is None:
            raise ValueError("Call generate() first.")
        return -self.q_matrix[self.state_to_idx[state]][self.state_to_idx[state]]

    def get_transition_probability(self, from_state: TransitionState, to_state: TransitionState) -> float:
        if self.q_matrix is None:
            raise ValueError("Call generate() first.")
        if from_state == to_state:
            return 0.0
        er = self.get_escape_rate(from_state)
        return self.q_matrix[self.state_to_idx[from_state]][self.state_to_idx[to_state]] / er if er else 0.0

    def export_matrix(self) -> dict[str, Any]:
        if self.q_matrix is None:
            return {}
        return {
            "states": [s.value for s in self.states],
            "matrix": self.q_matrix,
            "escape_rates": {s.value: self.get_escape_rate(s) for s in self.states},
        }
