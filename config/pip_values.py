"""
Pip Value Constants — TUYUL FX (SINGLE SOURCE OF TRUTH)

Provides pip values and pip multipliers for all supported instruments.
Pure lookups only — NO business logic, NO position sizing.

All modules that need pip values MUST import from here.
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


class PipLookupError(LookupError):
    def __init__(self, pair: str, table_name: str) -> None:
        self.pair = pair
        self.table_name = table_name
        super().__init__(f"Pair '{pair}' not found in {table_name}.")


DEFAULT_PIP_VALUE: float = 10.0

PIP_VALUES_PER_STANDARD_LOT: dict[str, float] = {
    "EURUSD": 10.00, "GBPUSD": 10.00, "AUDUSD": 10.00, "NZDUSD": 10.00,
    "USDJPY": 6.67,  "USDCHF": 10.00, "USDCAD": 7.50,
    "GBPJPY": 6.67,  "EURJPY": 6.67,  "AUDJPY": 6.67,  "NZDJPY": 6.67,
    "EURGBP": 12.50, "EURAUD": 7.50,  "GBPCHF": 10.00, "GBPAUD": 7.50,
    "GBPCAD": 7.50,  "GBPNZD": 6.50,  "EURCHF": 10.00, "EURCAD": 7.50,
    "AUDCAD": 7.50,  "AUDNZD": 6.50,
    "XAUUSD": 10.00, "XAGUSD": 50.00,
    "US30":   10.00, "US500":  10.00, "NAS100": 10.00,
}

_EXPLICIT_MULTIPLIERS: dict[str, float] = {
    "XAUUSD": 10.0, "XAGUSD": 100.0,
    "US30": 1.0, "US500": 1.0, "NAS100": 1.0,
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
