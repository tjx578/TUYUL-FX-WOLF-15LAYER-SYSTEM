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

        # bars bisa beda nama, coba beberapa opsi
        bars_val: Any = m.get("bars") or m.get("count") or m.get("available")
        try:
            bars = int(bars_val) if bars_val is not None else (required if ready_val else 0)
        except (TypeError, ValueError):
            bars = required if ready_val else 0

        req_val: Any = m.get("required")
        try:
            req = int(req_val) if req_val is not None else int(required)
        except (TypeError, ValueError):
            req = int(required)

        missing_val: Any = m.get("missing")
        if missing_val is None:
            missing = max(0, req - bars)
        else:
            try:
                missing = max(0, int(missing_val))
            except (TypeError, ValueError):
                missing = max(0, req - bars)

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
