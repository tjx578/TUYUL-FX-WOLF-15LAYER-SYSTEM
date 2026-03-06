"""Unified Reflex Gate Controller.

Maps the RQI score to a discrete gate decision (OPEN / CAUTION / LOCK)
with an associated lot-scaling factor.

This module is analysis-only and has no execution side-effects.
Gate output is consumed by L12 verdict engine as an additional constitutional
input — L12 retains sole verdict authority.

Gate bands (configurable):
    RQI >= 0.85  →  OPEN     lot_scale = 1.0
    RQI >= 0.70  →  CAUTION  lot_scale = 0.5
    RQI <  0.70  →  LOCK     lot_scale = 0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Default thresholds ────────────────────────────────────────────────────────

_DEFAULT_OPEN_THRESHOLD: float = 0.85
_DEFAULT_CAUTION_THRESHOLD: float = 0.70

_DEFAULT_OPEN_LOT_SCALE: float = 1.0
_DEFAULT_CAUTION_LOT_SCALE: float = 0.5
_DEFAULT_LOCK_LOT_SCALE: float = 0.0


# ── Gate decision data ────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class GateDecision:
    """Immutable gate decision produced by the reflex gate controller."""

    gate: str          # "OPEN" | "CAUTION" | "LOCK"
    lot_scale: float   # 0.0 – 1.0
    rqi: float         # smoothed RQI that triggered this decision
    reason: str        # human-readable explanation

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "lot_scale": self.lot_scale,
            "rqi": round(self.rqi, 6),
            "reason": self.reason,
        }


# ── Gate controller ───────────────────────────────────────────────────────────

class ReflexGateController:
    """Stateless gate controller that classifies RQI into OPEN/CAUTION/LOCK.

    Thresholds are configurable at construction time so they can be loaded
    from ``config/settings`` or environment overrides.
    """

    def __init__(
        self,
        open_threshold: float = _DEFAULT_OPEN_THRESHOLD,
        caution_threshold: float = _DEFAULT_CAUTION_THRESHOLD,
        open_lot_scale: float = _DEFAULT_OPEN_LOT_SCALE,
        caution_lot_scale: float = _DEFAULT_CAUTION_LOT_SCALE,
        lock_lot_scale: float = _DEFAULT_LOCK_LOT_SCALE,
    ) -> None:
        super().__init__()
        if caution_threshold >= open_threshold:
            raise ValueError(
                f"caution_threshold ({caution_threshold}) must be < "
                f"open_threshold ({open_threshold})"
            )
        self._open_threshold = open_threshold
        self._caution_threshold = caution_threshold
        self._open_lot = max(0.0, min(1.0, open_lot_scale))
        self._caution_lot = max(0.0, min(1.0, caution_lot_scale))
        self._lock_lot = max(0.0, min(1.0, lock_lot_scale))

    # ── Core evaluation ───────────────────────────────────────────────────────

    def evaluate(self, rqi: float) -> GateDecision:
        """Classify *rqi* into a gate band.

        Args:
            rqi: Smoothed (or raw) RQI value in [0, 1].

        Returns:
            GateDecision with gate label, lot_scale, and reason.
        """
        rqi_clamped = max(0.0, min(1.0, float(rqi)))

        if rqi_clamped >= self._open_threshold:
            return GateDecision(
                gate="OPEN",
                lot_scale=self._open_lot,
                rqi=rqi_clamped,
                reason=f"RQI {rqi_clamped:.4f} >= {self._open_threshold} — full execution",
            )

        if rqi_clamped >= self._caution_threshold:
            return GateDecision(
                gate="CAUTION",
                lot_scale=self._caution_lot,
                rqi=rqi_clamped,
                reason=(
                    f"RQI {rqi_clamped:.4f} in [{self._caution_threshold}, "
                    f"{self._open_threshold}) — reduced lot"
                ),
            )

        return GateDecision(
            gate="LOCK",
            lot_scale=self._lock_lot,
            rqi=rqi_clamped,
            reason=f"RQI {rqi_clamped:.4f} < {self._caution_threshold} — execution blocked",
        )

    @property
    def thresholds(self) -> dict[str, float]:
        """Return current threshold configuration."""
        return {
            "open_threshold": self._open_threshold,
            "caution_threshold": self._caution_threshold,
            "open_lot_scale": self._open_lot,
            "caution_lot_scale": self._caution_lot,
            "lock_lot_scale": self._lock_lot,
        }
