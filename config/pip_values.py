"""
💰 Pip Value Constants -- TUYUL FX (SINGLE SOURCE OF TRUTH)
-------------------------------------------------------------
P0 BUG FIX: XAUUSD was 0.10 in dashboard vs 10.0 in config.

This module provides:
  - Pip values per standard lot (USD-denominated accounts)
  - Pip multipliers (price difference -> pip count)
  - Pure lookups only -- NO business logic

All modules that need pip values MUST import from here.
No position sizing, no lot clamping, no risk calculations.
Those belong in risk/position_sizer.py.

Limitation: Values are approximate and assume a USD-denominated
account.  For non-USD accounts, a conversion factor must be
applied by the consuming module (risk/position_sizer.py).

Zone: config/ -- pure data, no side effects, no business logic.
"""


__all__ = [
    "DEFAULT_PIP_VALUE",
    "PIP_MULTIPLIERS",
    "PIP_VALUES_PER_STANDARD_LOT",
    "PipLookupError",
    "get_pip_info",
    "get_pip_multiplier",
    "get_pip_value",
    "is_pair_supported",
    "list_supported_pairs",
]


# ── Exceptions ───────────────────────────────────────────────────────

class PipLookupError(LookupError):
    """Raised when a pair is not found in pip value or multiplier tables."""

    def __init__(self, pair: str, table_name: str) -> None:
        self.pair = pair
        self.table_name = table_name
        super().__init__(
            f"Pair '{pair}' not found in {table_name}. "
            f"Use is_pair_supported() to check before lookup."
        )


# ── Constants ────────────────────────────────────────────────────────

# Default pip value for unknown pairs (used ONLY by analysis layers
# in degraded mode -- risk/position_sizer.py must NOT fall back to this
# silently).
DEFAULT_PIP_VALUE: float = 10.0

# Standard Lot = 100,000 units (forex) / 100 oz (gold) / 5,000 oz (silver)
# Values are per 1 standard lot, USD-denominated account.
# Cross-pair values (e.g. EURGBP) vary with exchange rates;
# the numbers here are typical approximations.
PIP_VALUES_PER_STANDARD_LOT: dict[str, float] = {
    # ── Major Pairs (USD quote) ──
    "EURUSD": 10.00,
    "GBPUSD": 10.00,
    "AUDUSD": 10.00,
    "NZDUSD": 10.00,

    # ── Major Pairs (USD base) ──
    "USDJPY": 6.67,   # Varies with USD/JPY rate
    "USDCHF": 10.00,
    "USDCAD": 7.50,   # Varies with USD/CAD rate

    # ── Cross Pairs ──
    "GBPJPY": 6.67,
    "EURJPY": 6.67,
    "AUDJPY": 6.67,
    "NZDJPY": 6.67,
    "EURGBP": 12.50,  # Varies with GBP/USD rate
    "EURAUD": 7.50,
    "GBPCHF": 10.00,
    "GBPAUD": 7.50,
    "GBPCAD": 7.50,
    "GBPNZD": 6.50,
    "EURCHF": 10.00,
    "EURCAD": 7.50,
    "AUDCAD": 7.50,
    "AUDNZD": 6.50,

    # ── Metals -- CORRECTED VALUES ──
    # Gold:   1 pip = $0.10 price movement, 100oz/lot -> $10 per pip per lot
    "XAUUSD": 10.00,
    # Silver: 1 pip = $0.01 price movement, 5000oz/lot -> $50 per pip per lot
    "XAGUSD": 50.00,

    # ── Indices (approximate, broker-dependent) ──
    "US30":   10.00,
    "US500":  10.00,
    "NAS100": 10.00,
}


# ── Pip Multipliers ──────────────────────────────────────────────────
#
# Converts a price difference to pip count:
#   pips = abs(price_a - price_b) * PIP_MULTIPLIERS[pair]
#
# Standard FX:  1 pip = 0.0001 -> multiplier = 10,000
# JPY pairs:    1 pip = 0.01   -> multiplier = 100
# XAUUSD:       1 pip = 0.10   -> multiplier = 10
# XAGUSD:       1 pip = 0.01   -> multiplier = 100
# Indices:      1 pip = 1.0    -> multiplier = 1

# Explicitly listed instruments take priority.
# Everything else falls through to the JPY / standard heuristic.
_EXPLICIT_MULTIPLIERS: dict[str, float] = {
    "XAUUSD": 10.0,
    "XAGUSD": 100.0,
    "US30":   1.0,
    "US500":  1.0,
    "NAS100": 1.0,
}

_JPY_MULTIPLIER: float = 100.0
_STANDARD_MULTIPLIER: float = 10_000.0

# Frozen public view for importers who want the full table.
PIP_MULTIPLIERS: dict[str, float] = {
    **dict.fromkeys(PIP_VALUES_PER_STANDARD_LOT, _STANDARD_MULTIPLIER),
    **{pair: _JPY_MULTIPLIER
       for pair in PIP_VALUES_PER_STANDARD_LOT if "JPY" in pair},
    **_EXPLICIT_MULTIPLIERS,
}


# ── Lookup Functions ─────────────────────────────────────────────────

def _normalize_pair(pair: str) -> str:
    """Normalize pair name: uppercase, strip slash."""
    return pair.upper().replace("/", "").strip()


def is_pair_supported(pair: str) -> bool:
    """Check if a pair exists in the pip value table."""
    return _normalize_pair(pair) in PIP_VALUES_PER_STANDARD_LOT


def list_supported_pairs() -> list[str]:
    """Return sorted list of all supported pairs."""
    return sorted(PIP_VALUES_PER_STANDARD_LOT.keys())


def get_pip_value(pair: str) -> float:
    """Get pip value per standard lot for a pair.

    Returns the dollar value of a 1-pip movement for 1.0 standard lot
    on a USD-denominated account.

    Parameters
    ----------
    pair : str
        Trading pair (e.g. "XAUUSD", "gbp/usd").

    Returns
    -------
    float
        Pip value in USD per standard lot.

    Raises
    ------
    PipLookupError
        If the pair is not in the table.
    """
    key = _normalize_pair(pair)
    if key not in PIP_VALUES_PER_STANDARD_LOT:
        raise PipLookupError(key, "PIP_VALUES_PER_STANDARD_LOT")
    return PIP_VALUES_PER_STANDARD_LOT[key]


def get_pip_multiplier(pair: str) -> float:
    """Get pip multiplier for price-to-pip conversion.

    Converts a price difference to pip count:
        pips = abs(price_a - price_b) * get_pip_multiplier(pair)

    Parameters
    ----------
    pair : str
        Trading pair (e.g. "XAUUSD", "USDJPY").

    Returns
    -------
    float
        Multiplier for converting price deltas to pips.

    Raises
    ------
    PipLookupError
        If the pair is not in the table and cannot be resolved
        by heuristic (JPY detection).

    Notes
    -----
    Resolution order:
      1. Explicit multiplier table (metals, indices)
      2. JPY heuristic (any pair containing "JPY")
      3. Standard FX multiplier (10000) -- only if pair is in
         PIP_VALUES_PER_STANDARD_LOT
      4. PipLookupError for unknown pairs
    """
    key = _normalize_pair(pair)

    # 1. Explicit overrides (metals, indices)
    if key in _EXPLICIT_MULTIPLIERS:
        return _EXPLICIT_MULTIPLIERS[key]

    # 2. JPY heuristic
    if "JPY" in key:
        return _JPY_MULTIPLIER

    # 3. Known standard FX pair
    if key in PIP_VALUES_PER_STANDARD_LOT:
        return _STANDARD_MULTIPLIER

    # 4. Unknown -- raise, don't guess
    raise PipLookupError(key, "PIP_MULTIPLIERS")


def get_pip_info(pair: str) -> tuple[float, float]:
    """Get both pip value and pip multiplier for a pair.

    Convenience function for modules that need both values.

    Parameters
    ----------
    pair : str
        Trading pair.

    Returns
    -------
    tuple[float, float]
        (pip_value_per_standard_lot, pip_multiplier)

    Raises
    ------
    PipLookupError
        If the pair is not supported.
    """
    return get_pip_value(pair), get_pip_multiplier(pair)
