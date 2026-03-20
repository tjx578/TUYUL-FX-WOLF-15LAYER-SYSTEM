"""
Pair Spread Constants — TUYUL FX (SINGLE SOURCE OF TRUTH)

Average spreads in pips per pair under normal London/NY session conditions.
Pure lookups only — NO business logic.

Consumed by:
  - ingest/spread_estimator.py   (synthetic bid/ask at ingest time)
  - risk/slippage_model.py       (execution cost estimation at trade time)
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_SPREAD_PIPS",
    "PAIR_SPREADS_PIPS",
    "get_spread_pips",
]

# Average spreads in pips per pair (during normal London/NY session)
PAIR_SPREADS_PIPS: dict[str, float] = {
    # ── Forex Majors ──
    "EURUSD": 1.0,
    "GBPUSD": 1.2,
    "USDJPY": 1.0,
    "USDCHF": 1.3,
    "AUDUSD": 1.2,
    "USDCAD": 1.4,
    "NZDUSD": 1.5,
    # ── Minors / Crosses ──
    "EURGBP": 1.5,
    "EURJPY": 1.5,
    "GBPJPY": 2.0,
    "AUDJPY": 1.8,
    "EURAUD": 2.0,
    "EURCHF": 1.8,
    "EURCAD": 2.0,
    "EURNZD": 2.5,
    "GBPAUD": 2.5,
    "GBPCAD": 2.5,
    "GBPCHF": 2.5,
    "GBPNZD": 3.0,
    "AUDCAD": 2.0,
    "AUDNZD": 2.0,
    "AUDCHF": 2.0,
    "NZDJPY": 2.0,
    "NZDCAD": 2.5,
    "NZDCHF": 2.5,
    "CADJPY": 2.0,
    "CADCHF": 2.5,
    "CHFJPY": 2.0,
    # ── Exotics ──
    "USDMXN": 30.0,
    "USDTRY": 50.0,
    "USDZAR": 40.0,
    "USDSGD": 3.0,
    "USDHKD": 3.0,
    # ── Commodities ──
    "XAUUSD": 3.0,
    "XAGUSD": 3.5,
}

DEFAULT_SPREAD_PIPS: float = 2.0


def get_spread_pips(pair: str) -> float:
    """Return the base spread in pips for *pair*, falling back to DEFAULT."""
    clean = pair.upper().replace("/", "").replace("_", "").replace(".", "")
    return PAIR_SPREADS_PIPS.get(clean, DEFAULT_SPREAD_PIPS)
