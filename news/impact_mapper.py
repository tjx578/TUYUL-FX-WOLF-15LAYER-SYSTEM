"""
Impact mapping utilities.

Converts raw provider-specific impact strings / numeric codes
into the canonical ImpactLevel enum and its numeric score.
"""

from __future__ import annotations

from news.models import ImpactLevel

# ── Forex Factory ──────────────────────────────────────────────────────────────
# FF uses string labels: "High", "Medium", "Low", "Holiday" (case-insensitive)
_FF_IMPACT_MAP: dict[str, ImpactLevel] = {
    "high": ImpactLevel.HIGH,
    "medium": ImpactLevel.MEDIUM,
    "med": ImpactLevel.MEDIUM,
    "low": ImpactLevel.LOW,
    "holiday": ImpactLevel.HOLIDAY,
    "non-economic": ImpactLevel.HOLIDAY,
}

# ── Finnhub ────────────────────────────────────────────────────────────────────
# Finnhub uses integer codes: 3=high, 2=medium, 1=low, 0=holiday/unknown
_FINNHUB_IMPACT_MAP: dict[str | int, ImpactLevel] = {
    3: ImpactLevel.HIGH,
    2: ImpactLevel.MEDIUM,
    1: ImpactLevel.LOW,
    0: ImpactLevel.HOLIDAY,
    "3": ImpactLevel.HIGH,
    "2": ImpactLevel.MEDIUM,
    "1": ImpactLevel.LOW,
    "0": ImpactLevel.HOLIDAY,
}

# ── Numeric scores ─────────────────────────────────────────────────────────────
IMPACT_SCORES: dict[ImpactLevel, int] = {
    ImpactLevel.HIGH: 3,
    ImpactLevel.MEDIUM: 2,
    ImpactLevel.LOW: 1,
    ImpactLevel.HOLIDAY: 0,
    ImpactLevel.UNKNOWN: 0,
}


def map_ff_impact(raw: str | None) -> ImpactLevel:
    """Map a Forex Factory impact string to ``ImpactLevel``."""
    if not raw:
        return ImpactLevel.UNKNOWN
    return _FF_IMPACT_MAP.get(raw.strip().lower(), ImpactLevel.UNKNOWN)


def map_finnhub_impact(raw: str | int | None) -> ImpactLevel:
    """Map a Finnhub impact code (str or int) to ``ImpactLevel``."""
    if raw is None:
        return ImpactLevel.UNKNOWN
    return _FINNHUB_IMPACT_MAP.get(raw, ImpactLevel.UNKNOWN)


def impact_score(level: ImpactLevel) -> int:
    """Return numeric impact score for a given ``ImpactLevel``."""
    return IMPACT_SCORES.get(level, 0)
