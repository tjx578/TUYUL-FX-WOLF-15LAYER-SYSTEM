"""Warmup utilities for pipeline.

Normalize output dari context_bus.check_warmup(...) supaya schema konsisten.
Hindari KeyError di pipeline logging.
Support berbagai bentuk return lama/baru:
  - bool
  - {"ready": bool}
  - {"ready": bool, "bars": int, "required": int, "missing": int}
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class WarmupStatus:
    ready: bool
    bars: int
    required: int
    missing: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "bars": self.bars,
            "required": self.required,
            "missing": self.missing,
        }


def normalize_warmup(raw: Any, *, required: int) -> WarmupStatus:
    """Normalize warmup return value into WarmupStatus.

    Args:
        raw: return dari context_bus.check_warmup(...)
        required: minimum bars required (pipeline constant)

    Returns:
        WarmupStatus with guaranteed keys and safe defaults.
    """
    # Case 1: raw is boolean
    if isinstance(raw, bool):
        bars = required if raw else 0
        return WarmupStatus(
            ready=raw,
            bars=bars,
            required=required,
            missing=max(0, required - bars),
        )

    # Case 2: raw is mapping-like
    if isinstance(raw, Mapping):
        m: Mapping[str, Any] = cast(Mapping[str, Any], raw)
        ready_val = bool(m.get("ready", False))

        def _coerce_int_map(value: Any) -> dict[str, int]:
            if not isinstance(value, Mapping):
                return {}
            out: dict[str, int] = {}
            for key, val in value.items():
                try:
                    out[str(key)] = int(val)
                except (TypeError, ValueError):
                    continue
            return out

        # bars bisa beda nama, coba beberapa opsi
        bars_val: Any = m.get("bars") or m.get("count") or m.get("available")
        # check_warmup returns per-timeframe dicts; collapse to scalar
        bars_map = _coerce_int_map(bars_val)
        if bars_map:
            bars = min(bars_map.values(), default=0)
        else:
            try:
                bars = int(bars_val) if bars_val is not None else (required if ready_val else 0)
            except (TypeError, ValueError):
                bars = required if ready_val else 0

        req_val: Any = m.get("required")
        req_map = _coerce_int_map(req_val)
        if req_map:
            req = min(req_map.values(), default=required)
        else:
            try:
                req = int(req_val) if req_val is not None else int(required)
            except (TypeError, ValueError):
                req = int(required)

        missing_val: Any = m.get("missing")
        if missing_val is None:
            missing = max(0, req - bars)
        else:
            miss_map = _coerce_int_map(missing_val)
            if miss_map:
                missing = max(miss_map.values(), default=0)
            else:
                try:
                    missing = max(0, int(missing_val))
                except (TypeError, ValueError):
                    missing = max(0, req - bars)

        # If check_warmup returned per-timeframe maps, collapse scalars from one
        # consistent timeframe (the largest shortfall) to avoid impossible tuples
        # such as required=4 but missing=6.
        if bars_map and req_map:
            shortfalls = {tf: max(0, req_map.get(tf, 0) - bars_map.get(tf, 0)) for tf in req_map}
            if shortfalls:
                worst_tf = max(shortfalls, key=lambda tf: shortfalls[tf])
                bars = bars_map.get(worst_tf, 0)
                req = req_map.get(worst_tf, int(required))
                missing = shortfalls.get(worst_tf, max(0, req - bars))
                if req < bars + missing:
                    req = bars + missing

        return WarmupStatus(
            ready=ready_val,
            bars=bars,
            required=req,
            missing=missing,
        )

    # Case 3: unknown type -> treat as not ready
    return WarmupStatus(
        ready=False,
        bars=0,
        required=int(required),
        missing=int(required),
    )
