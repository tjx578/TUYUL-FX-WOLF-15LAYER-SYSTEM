"""RSI Alignment Engine -- cross-timeframe RSI analysis."""

from typing import Any


def rsi_alignment_engine(*, rsi_w1: float, rsi_d1: float, rsi_h4: float, rsi_h1: float) -> dict[str, Any]:
    def bias(r: float) -> str:
        return "BULLISH" if r >= 60 else "BEARISH" if r <= 40 else "NEUTRAL"

    tb = {"W1": bias(rsi_w1), "D1": bias(rsi_d1), "H4": bias(rsi_h4), "H1": bias(rsi_h1)}
    bc = list(tb.values()).count("BULLISH")
    brc = list(tb.values()).count("BEARISH")
    mb = "BULLISH" if bc >= 3 else "BEARISH" if brc >= 3 else "NEUTRAL"
    asc = round((max(bc, brc) / 4) * 100, 2)
    vals = [rsi_w1, rsi_d1, rsi_h4, rsi_h1]
    avg = sum(vals) / 4
    rr = max(vals) - min(vals)
    cf = max(0.0, 1 - (rr / 50))
    return {
        "alignment_score": asc,
        "momentum_bias": mb,
        "confidence": round(asc * cf, 2),
        "rsi_mean": round(avg, 2),
        "rsi_range": round(rr, 2),
        "detail": tb,
    }
