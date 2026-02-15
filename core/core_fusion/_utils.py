"""Fusion Utilities -- shared helper functions."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def _clamp(value: float, low: float, high: float) -> float:
    if value != value: return low  # NaN
    return max(low, min(high, value))

def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default

def _inputs_valid(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)

def _last_numeric(values: Optional[Sequence[Any]]) -> Optional[float]:
    if not values: return None
    try: return float(values[-1])
    except (TypeError, ValueError): return None

def _min_numeric(values: Optional[Sequence[Any]]) -> Optional[float]:
    if not values: return None
    nums = []
    for v in values:
        try: nums.append(float(v))
        except (TypeError, ValueError): continue
    return min(nums) if nums else None

def _average_numeric(values: Optional[Sequence[Any]]) -> Optional[float]:
    if not values: return None
    nums = []
    for v in values:
        try: nums.append(float(v))
        except (TypeError, ValueError): continue
    return sum(nums) / len(nums) if nums else None

def validate_price_data(prices: Sequence[float], min_length: int = 10, allow_zero: bool = False) -> bool:
    if not prices or len(prices) < min_length: return False
    return all(p is not None and isinstance(p, (int, float)) and (allow_zero or p > 0) for p in prices)

def normalize_timeframe(timeframe: str) -> str:
    tf = str(timeframe).upper().strip()
    m = {"1M":"M1","5M":"M5","15M":"M15","30M":"M30","1H":"H1","4H":"H4",
         "1D":"D1","1W":"W1","60":"H1","240":"H4","1440":"D1","MINUTE":"M1",
         "HOUR":"H1","DAY":"D1","WEEK":"W1"}
    return m.get(tf, tf)

def calculate_rr_ratio(entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(entry - stop_loss)
    return round(abs(take_profit - entry) / risk, 2) if risk else 0.0

def timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_jsonl_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False); f.write("\n")
    except OSError: pass

def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        if tmp.exists(): tmp.unlink()

def moving_average(values: List[float], period: int) -> Optional[float]:
    if not values or len(values) < period: return None
    return sum(values[-period:]) / period

def exponential_moving_average(values: List[float], period: int, smoothing: float = 2.0) -> Optional[float]:
    if not values or len(values) < period: return None
    m = smoothing / (period + 1)
    ema = sum(values[:period]) / period
    for p in values[period:]: ema = (p * m) + (ema * (1 - m))
    return ema
