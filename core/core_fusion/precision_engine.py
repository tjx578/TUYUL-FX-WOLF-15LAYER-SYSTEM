"""Fusion Precision Engine + Metrics Analyzer."""

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from ._types import (
    FusionBiasMode, FusionAction, FusionPrecisionResult,
    DEFAULT_EMA_FAST, DEFAULT_EMA_SLOW,
    DEFAULT_PRECISION_WEIGHT_MIN, DEFAULT_PRECISION_WEIGHT_MAX,
)
from ._utils import _clamp, _clamp01, _safe_float, _inputs_valid


class FusionPrecisionEngine:
    def __init__(self, ema_fast: int = DEFAULT_EMA_FAST, ema_slow: int = DEFAULT_EMA_SLOW) -> None:
        self.ema_fast = ema_fast; self.ema_slow = ema_slow

    def compute_precision(self, *, price: float, ema_fast_val: float, ema_slow_val: float,
                          vwap: float, atr: float, reflex_strength: float, volatility: float,
                          rsi: float, symbol: Optional[str] = None, pair: Optional[str] = None,
                          trade_id: Optional[str] = None) -> FusionPrecisionResult:
        ts = datetime.now(timezone.utc).isoformat()
        if not _inputs_valid(price, ema_fast_val, ema_slow_val, vwap, atr, reflex_strength, volatility, rsi) or atr <= 0:
            return FusionPrecisionResult(timestamp=ts, fusion_strength=0.0, bias_mode="NEUTRAL",
                precision_weight=1.0, precision_confidence_hint=0.0,
                details={"status": "invalid_input"}, symbol=symbol, pair=pair, trade_id=trade_id)

        ema_str = math.tanh((ema_fast_val - ema_slow_val) / (ema_slow_val + 1e-6) * 5.0)
        vwap_sig = math.tanh((price - vwap) / (atr + 1e-6) * 0.8)
        ref_w = _clamp(reflex_strength, 0.0, 1.0)
        vol_adj = _clamp(1.0 - (volatility / (atr * 2.5)), 0.4, 1.0)

        fusion_raw = (ema_str * 0.45) + (vwap_sig * 0.35) + (ref_w * 0.2)
        fusion = float(fusion_raw * vol_adj)

        bias = FusionBiasMode.BULLISH.value if fusion > 0.25 else \
               FusionBiasMode.BEARISH.value if fusion < -0.25 else FusionBiasMode.NEUTRAL.value
        hint = _clamp(abs(fusion) * 0.85, 0.0, 1.0)
        rsi_bonus = 0.10 if (rsi >= 65 and fusion > 0) or (rsi <= 35 and fusion < 0) else 0.0
        pw = _clamp(1.0 + (_clamp(abs(fusion), 0, 1) - 0.35) * 0.45 + rsi_bonus,
                     DEFAULT_PRECISION_WEIGHT_MIN, DEFAULT_PRECISION_WEIGHT_MAX)

        return FusionPrecisionResult(
            timestamp=ts, fusion_strength=round(fusion, 6), bias_mode=bias,
            precision_weight=round(float(pw), 4), precision_confidence_hint=round(float(hint), 4),
            details={"ema_strength": round(float(ema_str), 6), "vwap_signal": round(float(vwap_sig), 6),
                     "reflex_strength": round(float(ref_w), 6), "volatility_adj": round(float(vol_adj), 6),
                     "rsi": float(rsi)},
            symbol=symbol, pair=pair, trade_id=trade_id)


def calculate_fusion_precision(market_data: Dict[str, Any]) -> Dict[str, Any]:
    engine = FusionPrecisionEngine()
    res = engine.compute_precision(
        price=_safe_float(market_data.get("price", 0.0)),
        ema_fast_val=_safe_float(market_data.get("ema_fast_val", market_data.get("ema_fast", 0.0))),
        ema_slow_val=_safe_float(market_data.get("ema_slow_val", market_data.get("ema_slow", 0.0))),
        vwap=_safe_float(market_data.get("vwap", 0.0)),
        atr=_safe_float(market_data.get("atr", 0.0)),
        reflex_strength=_safe_float(market_data.get("reflex_strength", 0.0)),
        volatility=_safe_float(market_data.get("volatility", 0.0)),
        rsi=_safe_float(market_data.get("rsi", 50.0)),
        symbol=market_data.get("symbol"), pair=market_data.get("pair"), trade_id=market_data.get("trade_id"))
    p = res.as_dict()
    p["bias"] = {"BULLISH": "Bullish", "BEARISH": "Bearish"}.get(p.get("bias_mode", ""), "Neutral")
    p["CONF12"] = max(0.95, min(1.0, float(p.get("precision_weight", 1.0)) * 0.98))
    return p


def evaluate_fusion_metrics(fusion_data: Dict[str, Any], threshold: float = 0.75) -> Dict[str, Any]:
    conf = fusion_data.get("fusion_strength", 0.5)
    direction = fusion_data.get("direction", "NEUTRAL")
    valid = conf >= threshold and direction != "NEUTRAL"
    score = _calculate_composite_score(fusion_data)
    action = FusionAction.EXECUTE.value if valid and score >= 0.8 else \
             FusionAction.MONITOR.value if valid and score >= 0.6 else FusionAction.WAIT.value
    return {"confidence": conf, "direction": direction, "signal_valid": valid,
            "composite_score": score, "action": action, "threshold": threshold,
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _calculate_composite_score(fusion_data: Dict[str, Any]) -> float:
    weights = {"fusion_strength": 0.4, "coherence": 0.3, "resonance": 0.2, "integrity": 0.1}
    return round(_clamp01(sum(_safe_float(fusion_data.get(k, 0.5), 0.5) * w for k, w in weights.items())), 3)


def aggregate_multi_timeframe_metrics(metrics_list: list) -> Dict[str, Any]:
    if not metrics_list:
        return {"aggregated_score": 0.5, "consensus_direction": "NEUTRAL", "timeframes_analyzed": 0}
    scores = [m.get("composite_score", 0.5) for m in metrics_list]
    dirs = [m.get("direction", "NEUTRAL") for m in metrics_list]
    counts: Dict[str, int] = {}
    for d in dirs: counts[d] = counts.get(d, 0) + 1
    consensus = max(counts.keys(), key=lambda k: counts[k])
    return {"aggregated_score": round(sum(scores) / len(scores), 3),
            "consensus_direction": consensus,
            "consensus_strength": round(counts[consensus] / len(dirs), 2),
            "timeframes_analyzed": len(metrics_list),
            "timestamp": datetime.now(timezone.utc).isoformat()}
