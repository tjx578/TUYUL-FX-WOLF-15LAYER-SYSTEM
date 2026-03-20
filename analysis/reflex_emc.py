"""Exponential Moving Coherence (EMC) filter for RQI smoothing.

Provides stateful per-symbol RQI smoothing to eliminate gate flip-flop.
Implements adaptive sigma that widens latency tolerance under emotional
stress (preventing double-punishment from latency + emotion penalties).

This module is analysis-only and has no execution side-effects.

EMC formula:
    RQI_smooth(t) = α × RQI_smooth(t-1) + (1 - α) × RQI_raw(t)

Adaptive sigma:
    σ_adaptive = σ_base × (1 + emotion_delta)

When emotion_delta is high (stressed), σ widens → latency penalty softens.
The emotion penalty (1 - E_Δ) already constrains RQI, so widening σ
prevents double-punishment.

History is bounded per symbol to prevent memory leaks.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_DECAY: float = 0.8         # α  (weight of previous smoothed value)
_DEFAULT_SIGMA_BASE: float = 60.0   # σ_base in seconds
_MAX_HISTORY: int = 500             # bounded per-symbol history


# ── Session state per symbol ──────────────────────────────────────────────────

@dataclass
class _SymbolSession:
    """Mutable per-symbol EMC state."""
    smoothed_rqi: float | None = None
    history: deque[float] = field(default_factory=lambda: deque(maxlen=_MAX_HISTORY))
    cycle_count: int = 0


# ── EMC Filter ────────────────────────────────────────────────────────────────

class EMCFilter:
    """Stateful Exponential Moving Coherence filter.

    Maintains per-symbol sessions. Each call to ``smooth()`` advances the
    session by one cycle and returns the dampened RQI value.

    Thread-safety: NOT thread-safe. The pipeline is expected to call this
    from a single async task per symbol (which is already the case).
    """

    def __init__(
        self,
        decay: float = _DEFAULT_DECAY,
        sigma_base: float = _DEFAULT_SIGMA_BASE,
        max_history: int = _MAX_HISTORY,
    ) -> None:
        super().__init__()
        if not 0.0 < decay < 1.0:
            raise ValueError(f"decay must be in (0, 1), got {decay}")
        self._decay = decay
        self._sigma_base = max(1e-9, float(sigma_base))
        self._max_history = max(1, int(max_history))
        self._sessions: dict[str, _SymbolSession] = {}

    # ── Adaptive sigma ────────────────────────────────────────────────────────

    def adaptive_sigma(self, emotion_delta: float) -> float:
        """Compute adaptive σ from base σ and current emotion_delta.

        σ_adaptive = σ_base × (1 + emotion_delta)

        Under stress (high emotion_delta), σ widens, which softens the
        latency penalty in the RQI Gaussian decay term. This prevents
        double-punishment since the emotion penalty (1 - E_Δ) already
        heavily constrains RQI.
        """
        e_delta = max(0.0, min(1.0, float(emotion_delta)))
        return self._sigma_base * (1.0 + e_delta)

    # ── Core smoothing ────────────────────────────────────────────────────────

    def smooth(self, symbol: str, rqi_raw: float) -> float:
        """Apply EMC smoothing to a raw RQI value.

        First call for a symbol initializes with the raw value (no
        smoothing on the first observation).

        Args:
            symbol: Trading pair identifier (e.g. "XAUUSD").
            rqi_raw: Raw (unsmoothed) RQI in [0, 1].

        Returns:
            Smoothed RQI in [0, 1].
        """
        rqi_clamped = max(0.0, min(1.0, float(rqi_raw)))

        session = self._sessions.get(symbol)
        if session is None:
            session = _SymbolSession()
            session.history = deque(maxlen=self._max_history)
            self._sessions[symbol] = session

        session.cycle_count += 1
        session.history.append(rqi_clamped)

        if session.smoothed_rqi is None:
            # First observation — no history to smooth against
            session.smoothed_rqi = rqi_clamped
        else:
            session.smoothed_rqi = (
                self._decay * session.smoothed_rqi
                + (1.0 - self._decay) * rqi_clamped
            )

        return max(0.0, min(1.0, session.smoothed_rqi))

    # ── Query helpers ─────────────────────────────────────────────────────────

    def get_session(self, symbol: str) -> dict[str, Any]:
        """Return session summary for a symbol (for diagnostics/logging)."""
        session = self._sessions.get(symbol)
        if session is None:
            return {"exists": False}
        return {
            "exists": True,
            "smoothed_rqi": round(session.smoothed_rqi or 0.0, 6),
            "cycle_count": session.cycle_count,
            "history_len": len(session.history),
        }

    def reset(self, symbol: str) -> None:
        """Clear state for a single symbol."""
        self._sessions.pop(symbol, None)

    def reset_all(self) -> None:
        """Clear all session state."""
        self._sessions.clear()

    @property
    def decay(self) -> float:
        return self._decay

    @property
    def sigma_base(self) -> float:
        return self._sigma_base
