"""Smart Money Counter Zone v3.5 Reflective."""

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ._types import CounterZoneContext
from ._utils import _clamp, write_jsonl_atomic


def _compute_confidence(ctx: CounterZoneContext) -> float:
    es = _clamp(ctx.trq_energy / 2.5, 0.0, 1.0)
    rs = _clamp((ctx.reflective_intensity + ctx.integrity_index) / 2, 0.0, 1.0)
    gs = _clamp((ctx.alpha + ctx.beta + ctx.gamma) / 3, 0.0, 1.0)
    ms = _clamp((abs(ctx.rsi - 50) / 50 + abs(ctx.mfi - 50) / 50 + min(abs(ctx.cci50) / 200, 1) + abs(ctx.rsi_h4 - 50) / 50) / 4, 0.0, 1.0)
    return round(_clamp(0.35 + 0.25 * es + 0.2 * rs + 0.1 * gs + 0.1 * ms, 0.0, 1.0), 3)


def _derive_direction(ctx: CounterZoneContext) -> str:
    if ctx.price > ctx.vwap and ctx.rsi >= 60: return "SELL"
    if ctx.price < ctx.vwap and ctx.rsi <= 40: return "BUY"
    if ctx.mfi <= 45 and ctx.price <= ctx.vwap: return "BUY"
    if ctx.rsi_h4 >= 65: return "SELL"
    return "BUY" if ctx.price <= ctx.vwap else "SELL"


def smart_money_counter_v3_5_reflective(
    *, price: float, vwap: float, atr: float, rsi: float, mfi: float,
    cci50: float, rsi_h4: float, trq_energy: float = 1.0,
    reflective_intensity: float = 1.0, alpha: float = 1.0, beta: float = 1.0,
    gamma: float = 1.0, integrity_index: float = 0.97,
    journal_path: Optional[Path] = None, symbol: Optional[str] = None,
    pair: Optional[str] = None, trade_id: Optional[str] = None,
) -> Dict[str, Any]:
    ctx = CounterZoneContext(price=price, vwap=vwap, atr=atr, rsi=rsi, mfi=mfi,
        cci50=cci50, rsi_h4=rsi_h4, trq_energy=trq_energy,
        reflective_intensity=reflective_intensity, alpha=alpha, beta=beta,
        gamma=gamma, integrity_index=integrity_index, journal_path=journal_path,
        symbol=symbol, pair=pair, trade_id=trade_id)

    nums = {"price": ctx.price, "vwap": ctx.vwap, "atr": ctx.atr, "rsi": ctx.rsi,
            "mfi": ctx.mfi, "cci50": ctx.cci50, "rsi_h4": ctx.rsi_h4,
            "trq_energy": ctx.trq_energy, "reflective_intensity": ctx.reflective_intensity,
            "alpha": ctx.alpha, "beta": ctx.beta, "gamma": ctx.gamma, "integrity_index": ctx.integrity_index}
    if not all(math.isfinite(v) for v in nums.values()): return {"status": "invalid_input"}
    if ctx.atr <= 0: return {"status": "invalid_atr"}

    vd = abs(ctx.price - ctx.vwap); spread = abs(ctx.mfi - ctx.cci50)
    vt = 1.2 * ctx.atr; re = ctx.trq_energy * ctx.reflective_intensity
    est = min(55.0, 40.0)
    if not (vd >= vt and spread >= est and re >= 0.85):
        return {"status": "No valid counter-zone", "confidence": 0.0, "counter_zone": False}

    d = _derive_direction(ctx); rb = max(ctx.atr * 1.6, 0.0008); tb = max(ctx.atr * 1.8, 0.0012)
    if d == "BUY":
        entry = round(ctx.price - ctx.atr * 0.1, 5); sl = round(entry - rb, 5); tp = round(entry + tb, 5)
    else:
        entry = round(ctx.price + ctx.atr * 0.1, 5); sl = round(entry + rb, 5); tp = round(entry - tb, 5)

    result: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "entry": entry, "sl": sl, "tp": tp,
        "type": d, "confidence": _compute_confidence(ctx), "spread": round(spread, 2),
        "deviation": round(vd, 5), "note": "Smart Money VWAP Counter-Zone v3.5 (Reflective Adaptive Mode)",
        "meta": {"trq_energy": round(ctx.trq_energy, 6), "reflective_intensity": round(ctx.reflective_intensity, 6),
                 "alpha": round(ctx.alpha, 6), "beta": round(ctx.beta, 6), "gamma": round(ctx.gamma, 6),
                 "integrity_index": round(ctx.integrity_index, 6)},
        "status": "ok", "counter_zone": True, "symbol": ctx.symbol, "pair": ctx.pair, "trade_id": ctx.trade_id,
    }
    if journal_path: write_jsonl_atomic(journal_path, result)
    return result
