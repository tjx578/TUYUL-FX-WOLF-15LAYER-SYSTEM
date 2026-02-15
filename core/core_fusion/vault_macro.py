"""Vault Macro Engine -- Reflective Gravity Anchor (EMA+SMA)."""

from typing import Any, Dict, List, Optional


class VaultMacroLayer:
    """EMA-200 / SMA-200 / SMA-800 macro bias system."""

    def __init__(self, ema_period: int = 200, sma_periods: Optional[List[int]] = None) -> None:
        self.ema_period = ema_period
        self.sma_periods = sma_periods or [200, 800]

    def calculate_ema(self, closes: List[float], period: int) -> float:
        if not closes: return 0.0
        a = 2 / (period + 1); ema = closes[0]
        for p in closes[1:]: ema = (p * a) + (ema * (1 - a))
        return round(float(ema), 5)

    def calculate_sma(self, closes: List[float], period: int) -> float:
        if not closes: return 0.0
        if len(closes) < period: return round(float(sum(closes) / len(closes)), 5)
        return round(float(sum(closes[-period:]) / period), 5)

    def derive_macro_bias(self, closes: List[float]) -> Dict[str, Any]:
        if not closes: return {"error": "No price data"}
        ema200 = self.calculate_ema(closes, self.ema_period)
        sma_r = {f"sma_{p}": self.calculate_sma(closes, p) for p in self.sma_periods}
        pn = float(closes[-1])
        sr = sma_r.get("sma_800", ema200)
        dp = round(((pn - sr) / sr) * 100, 3) if sr != 0 else 0.0
        sa = self._structural(ema200, sma_r, pn)
        return {"ema_200": ema200, **sma_r, "price_now": round(pn, 5),
                "macro_bias": "Bullish" if pn > ema200 else "Bearish",
                "distance_pct": dp, "structural_alignment": sa}

    def _structural(self, ema200: float, sma_r: Dict[str, float], pn: float) -> str:
        s200 = sma_r.get("sma_200", ema200); s800 = sma_r.get("sma_800", ema200)
        if pn > ema200 > s200 > s800: return "Strong_Bullish"
        if pn < ema200 < s200 < s800: return "Strong_Bearish"
        if pn > ema200 and ema200 > s200: return "Bullish"
        if pn < ema200 and ema200 < s200: return "Bearish"
        return "Neutral"

    def get_reflective_gravity_score(self, closes: List[float]) -> Dict[str, Any]:
        md = self.derive_macro_bias(closes)
        if "error" in md: return md
        d = abs(md["distance_pct"])
        if d <= 0.5: gs = 1.0
        elif d <= 1.0: gs = 0.9
        elif d <= 2.0: gs = 0.8
        elif d <= 5.0: gs = 0.6
        else: gs = 0.4
        return {**md, "gravity_score": round(gs, 3),
                "gravity_status": "Strong" if gs >= 0.8 else "Moderate" if gs >= 0.6 else "Weak"}
