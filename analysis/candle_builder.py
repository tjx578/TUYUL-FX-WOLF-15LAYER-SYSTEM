"""
Backward-compatible re-export of the unified CandleBuilder.

All candle construction logic lives in ingest/candle_builder.py.
Analysis modules should consume candles, not build them — this shim
exists only for import compatibility during the migration period.

Zone: analysis (read-only re-export). No side-effects.
"""

# Re-export everything from the single source of truth
from ingest.candle_builder import (  # noqa: F401
    Candle,
    CandleBuilder,
    MultiTimeframeCandleBuilder,
    OnCandleComplete,
    Timeframe,
)

__all__ = [
    "Candle",
    "CandleBuilder",
    "MultiTimeframeCandleBuilder",
    "OnCandleComplete",
    "Timeframe",
]
