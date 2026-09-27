"""
Pip Value Constants — TUYUL FX (SINGLE SOURCE OF TRUTH)

Provides pip values and pip multipliers for all supported instruments.
Pure lookups only — NO business logic, NO position sizing.

All modules that need pip values MUST import from here.
"""

from __future__ import annotations

__all__ = [
    "PIP_MULTIPLIERS",
    "PIP_VALUES_PER_STANDARD_LOT",
    "PipLookupError",
    "QUOTE_CURRENCY_PIP_VALUES_USD",
    "WOLF15_XM_30_V1_PAIRS",
    "get_pip_info",
    "get_pip_multiplier",
    "get_pip_value",
    "is_pair_supported",
    "list_supported_pairs",
]


class PipLookupError(LookupError):
    def __init__(self, pair: str, table_name: str) -> None:
        self.pair = pair
        self.table_name = table_name
        super().__init__(f"Pair '{pair}' not found in {table_name}. Use is_pair_supported() to check availability.")


# There is deliberately no default pip value. A pair without an explicit entry fails closed
# (PipLookupError) so lot sizing can never silently use a USD pip value for a non-USD quote.

# USD value of one pip per standard lot, by quote currency (USD-denominated account).
# Every FX entry below must equal the value for its quote currency (enforced by tests).
QUOTE_CURRENCY_PIP_VALUES_USD: dict[str, float] = {
    "USD": 10.00,
    "JPY": 6.67,
    "CAD": 7.50,
    "CHF": 10.00,
    "AUD": 7.50,
    "NZD": 6.50,
    "GBP": 12.50,
}

# Canonical symbols of the EA universe WOLF15_XM_30_V1 (ea_interface/.../broker_maps/xmglobal-mt5-10.csv).
WOLF15_XM_30_V1_PAIRS: tuple[str, ...] = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
    "XAUUSD", "XAGUSD",
)  # fmt: skip

PIP_VALUES_PER_STANDARD_LOT: dict[str, float] = {
    "EURUSD": 10.00,
    "GBPUSD": 10.00,
    "AUDUSD": 10.00,
    "NZDUSD": 10.00,
    "USDJPY": 6.67,
    "USDCHF": 10.00,
    "USDCAD": 7.50,
    "GBPJPY": 6.67,
    "EURJPY": 6.67,
    "AUDJPY": 6.67,
    "NZDJPY": 6.67,
    "EURGBP": 12.50,
    "EURAUD": 7.50,
    "GBPCHF": 10.00,
    "GBPAUD": 7.50,
    "GBPCAD": 7.50,
    "GBPNZD": 6.50,
    "EURCHF": 10.00,
    "EURCAD": 7.50,
    "AUDCAD": 7.50,
    "AUDNZD": 6.50,
    "EURNZD": 6.50,
    "AUDCHF": 10.00,
    "NZDCHF": 10.00,
    "NZDCAD": 7.50,
    "CADJPY": 6.67,
    "CADCHF": 10.00,
    "CHFJPY": 6.67,
    "XAUUSD": 10.00,
    "XAGUSD": 50.00,
    "US30": 10.00,
    "US500": 10.00,
    "NAS100": 10.00,
}

_EXPLICIT_MULTIPLIERS: dict[str, float] = {
    "XAUUSD": 10.0,
    "XAGUSD": 100.0,
    "US30": 1.0,
    "US500": 1.0,
    "NAS100": 1.0,
}
_JPY_MULTIPLIER: float = 100.0
_STANDARD_MULTIPLIER: float = 10_000.0

PIP_MULTIPLIERS: dict[str, float] = {
    **dict.fromkeys(PIP_VALUES_PER_STANDARD_LOT, _STANDARD_MULTIPLIER),
    **{pair: _JPY_MULTIPLIER for pair in PIP_VALUES_PER_STANDARD_LOT if "JPY" in pair},
    **_EXPLICIT_MULTIPLIERS,
}


def _normalize_pair(pair: str) -> str:
    return pair.upper().replace("/", "").strip()


def is_pair_supported(pair: str) -> bool:
    return _normalize_pair(pair) in PIP_VALUES_PER_STANDARD_LOT


def list_supported_pairs() -> list[str]:
    return sorted(PIP_VALUES_PER_STANDARD_LOT.keys())


def get_pip_value(pair: str) -> float:
    key = _normalize_pair(pair)
    if key not in PIP_VALUES_PER_STANDARD_LOT:
        raise PipLookupError(key, "PIP_VALUES_PER_STANDARD_LOT")
    return PIP_VALUES_PER_STANDARD_LOT[key]


def get_pip_multiplier(pair: str) -> float:
    key = _normalize_pair(pair)
    if key in _EXPLICIT_MULTIPLIERS:
        return _EXPLICIT_MULTIPLIERS[key]
    if "JPY" in key:
        return _JPY_MULTIPLIER
    if key in PIP_VALUES_PER_STANDARD_LOT:
        return _STANDARD_MULTIPLIER
    raise PipLookupError(key, "PIP_MULTIPLIERS")


def get_pip_info(pair: str) -> tuple[float, float]:
    return get_pip_value(pair), get_pip_multiplier(pair)
