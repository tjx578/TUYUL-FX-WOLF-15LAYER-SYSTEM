"""Synthetic spread estimator for Finnhub trade data.

Finnhub WebSocket trade data provides only last-trade price, not bid/ask.
This module provides realistic synthetic spread estimation based on pair
characteristics and market session.

Used by ingest/dependencies.py to produce more accurate bid/ask from
single trade prices.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.pair_spreads import DEFAULT_SPREAD_PIPS, PAIR_SPREADS_PIPS  # noqa: F401

# Pip value per pair (how many price units = 1 pip)
PIP_VALUES: dict[str, float] = {
    # JPY pairs: 1 pip = 0.01
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "GBPJPY": 0.01,
    "AUDJPY": 0.01,
    "NZDJPY": 0.01,
    "CADJPY": 0.01,
    "CHFJPY": 0.01,
    # Gold
    "XAUUSD": 0.10,
}
DEFAULT_PIP_VALUE = 0.0001  # For most pairs


# Session multipliers (spreads widen during off-peak)
SESSION_MULTIPLIER = {
    "OVERLAP": 1.0,  # London-NY overlap: tightest
    "LONDON": 1.1,
    "NEWYORK": 1.1,
    "TOKYO": 1.4,
    "SYDNEY": 1.6,
    "OFF_PEAK": 2.0,
}


def _get_active_session(hour_utc: int) -> str:
    """Determine active session from UTC hour."""
    # London-NY overlap
    if 12 <= hour_utc < 16:
        return "OVERLAP"
    # London session
    if 7 <= hour_utc < 16:
        return "LONDON"
    # NY session
    if 12 <= hour_utc < 21:
        return "NEWYORK"
    # Tokyo session
    if 0 <= hour_utc < 9:
        return "TOKYO"
    # Sydney
    if hour_utc >= 22 or hour_utc < 7:
        return "SYDNEY"
    return "OFF_PEAK"


def estimate_spread(
    symbol: str,
    price: float,
    timestamp: float | None = None,
) -> tuple[float, float]:
    """Estimate bid/ask from a single trade price.

    Parameters
    ----------
    symbol : str
        Normalized pair name (e.g. "EURUSD").
    price : float
        Last trade price.
    timestamp : float, optional
        Unix timestamp UTC. If None, uses current time.

    Returns
    -------
    (bid, ask) : tuple[float, float]
        Estimated bid and ask prices.
    """
    if price <= 0:
        return price, price

    # Normalize symbol
    sym_clean = symbol.upper().replace("/", "").replace("_", "").replace(".", "")

    # Get pip value
    pip_value = PIP_VALUES.get(sym_clean, DEFAULT_PIP_VALUE)

    # Get base spread in pips
    base_spread_pips = PAIR_SPREADS_PIPS.get(sym_clean, DEFAULT_SPREAD_PIPS)

    # Session multiplier
    if timestamp:
        try:
            dt = datetime.fromtimestamp(timestamp, tz=UTC)
            hour = dt.hour
        except (OSError, ValueError):
            hour = datetime.now(UTC).hour
    else:
        hour = datetime.now(UTC).hour

    session = _get_active_session(hour)
    multiplier = SESSION_MULTIPLIER.get(session, 1.5)

    # Compute spread in price units
    spread = base_spread_pips * pip_value * multiplier

    # Split evenly around trade price
    half_spread = spread / 2.0
    bid = price - half_spread
    ask = price + half_spread

    return round(bid, 6), round(ask, 6)
