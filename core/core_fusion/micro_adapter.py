"""Micro Adapter -- normalizes microstructure signals for WLWCI."""

import math
from typing import Any

from ._types import MicroBounds, NormalizedMicro, VolatilityRegime
from ._utils import _clamp, _clamp01


class MicroAdapter:
    """Ensures micro signals ENHANCE but never OVERRIDE macro."""

    VOL_LOW = 0.15
    VOL_MEDIUM = 0.35
    VOL_HIGH = 0.55
    CONFIDENCE_MULTIPLIERS = {
        VolatilityRegime.LOW: 1.05,
        VolatilityRegime.MEDIUM: 1.00,
        VolatilityRegime.HIGH: 0.85,
        VolatilityRegime.EXTREME: 0.70,
    }

    def __init__(self, bounds: MicroBounds | None = None) -> None:
        self.bounds = bounds or MicroBounds()

    def normalize(self, micro: dict[str, Any], macro_direction: float | None = None) -> NormalizedMicro:
        rt = self._extract(micro, ["twms_micro", "micro_twms", "twms", "micro"])
        rv = self._extract_vol(micro)
        if rt is None or rv is None:
            return self._invalid(rt, rv)
        bt = _clamp(rt, self.bounds.twms_min, self.bounds.twms_max)
        bv = min(rv, self.bounds.vol_cap)
        regime = self._regime(rv)
        cm = self.CONFIDENCE_MULTIPLIERS.get(regime, 1.0)
        conflict = self._conflict(bt, macro_direction)
        if conflict:
            bt *= 0.5
        return NormalizedMicro(
            twms_micro=round(bt, 4),
            vol_penalty=round(bv, 4),
            regime=regime,
            confidence_multiplier=cm,
            is_valid=True,
            conflict_detected=conflict,
            raw_twms_micro=rt,
            raw_volatility=rv,
        )

    def apply_to_wlwci(
        self, wlwci_base: float, normalized: NormalizedMicro, weights: dict[str, float] | None = None
    ) -> dict[str, Any]:
        w = weights or {"twms_micro": 0.18, "volatility_penalty": 0.12}
        if not normalized.is_valid:
            return {
                "wlwci": round(wlwci_base, 4),
                "adjusted": False,
                "reason": "invalid_micro_data",
                "normalized": normalized.to_dict(),
            }
        mc = w["twms_micro"] * normalized.twms_micro
        vp = w["volatility_penalty"] * normalized.vol_penalty
        final = _clamp01((wlwci_base + mc - vp) * normalized.confidence_multiplier)
        return {
            "wlwci": round(final, 4),
            "wlwci_base": round(wlwci_base, 4),
            "micro_contrib": round(mc, 4),
            "vol_penalty": round(vp, 4),
            "confidence_multiplier": normalized.confidence_multiplier,
            "regime": normalized.regime.value,
            "adjusted": True,
            "conflict_detected": normalized.conflict_detected,
            "normalized": normalized.to_dict(),
        }

    def _extract(self, d: dict[str, Any], keys: list) -> float | None:
        for k in keys:
            if k in d:
                try:
                    v = float(d[k])
                    if math.isfinite(v):
                        return v
                except (TypeError, ValueError):
                    continue
        return None

    def _extract_vol(self, d: dict[str, Any]) -> float | None:
        for k in ["volatility", "micro_volatility", "vol", "micro_vol"]:
            if k in d:
                try:
                    v = float(d[k])
                    if math.isfinite(v) and v >= 0:
                        return v
                except (TypeError, ValueError):
                    continue
        return None

    def _regime(self, vol: float) -> VolatilityRegime:
        if vol <= self.VOL_LOW:
            return VolatilityRegime.LOW
        if vol <= self.VOL_MEDIUM:
            return VolatilityRegime.MEDIUM
        if vol <= self.VOL_HIGH:
            return VolatilityRegime.HIGH
        return VolatilityRegime.EXTREME

    def _conflict(self, micro: float, macro: float | None) -> bool:
        if macro is None:
            return False
        ms = 1 if micro > 0 else -1 if micro < 0 else 0
        mas = 1 if macro > 0 else -1 if macro < 0 else 0
        return ms != 0 and mas != 0 and ms != mas and abs(micro) > 0.1 and abs(macro) > 0.1

    def _invalid(self, rt: float | None, rv: float | None) -> NormalizedMicro:
        return NormalizedMicro(
            twms_micro=0.0,
            vol_penalty=0.0,
            regime=VolatilityRegime.MEDIUM,
            confidence_multiplier=1.0,
            is_valid=False,
            conflict_detected=False,
            raw_twms_micro=rt or 0.0,
            raw_volatility=rv or 0.0,
        )
