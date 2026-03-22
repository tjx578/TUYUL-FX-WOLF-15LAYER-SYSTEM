"""
Pip & Lot Calculation Utilities for Wolf-15 Layer System.

Provides pip value, pip multiplier, and lot sizing helpers
for supported forex pairs. Pure analysis utility — no execution
side-effects.
"""

from __future__ import annotations

__all__ = [
    "get_pip_info",
    "get_pip_multiplier",
    "get_pip_value",
    "is_pair_supported",
    "list_supported_pairs",
]

# ---------------------------------------------------------------------------
# Pair metadata
# ---------------------------------------------------------------------------

# pip_decimal  : number of decimal places that represent 1 pip
# pip_multiplier: multiply price difference by this to get pips
# typ_spread   : typical spread in pips (informational only)

_PAIR_DATA: dict[str, dict] = {
    # --- JPY pairs (2-decimal pip) ---
    "USDJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.0},
    "EURJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.2},
    "GBPJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.8},
    "AUDJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.5},
    "NZDJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.8},
    "CADJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.6},
    "CHFJPY": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 1.8},
    # --- Standard 4-decimal pairs ---
    "EURUSD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 0.8},
    "GBPUSD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.0},
    "AUDUSD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.0},
    "NZDUSD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.2},
    "USDCAD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.2},
    "USDCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.2},
    "EURGBP": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.0},
    "EURAUD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.8},
    "EURNZD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.5},
    "EURCAD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.8},
    "EURCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 1.5},
    "GBPAUD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.5},
    "GBPNZD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 3.0},
    "GBPCAD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.2},
    "GBPCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.0},
    "AUDNZD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.0},
    "AUDCAD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.0},
    "AUDCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.0},
    "NZDCAD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.2},
    "NZDCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.5},
    "CADCHF": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.2},
    # --- Metals (2-decimal pip for gold, wider for silver) ---
    "XAUUSD": {"pip_decimal": 2, "pip_multiplier": 100, "typ_spread": 2.5},
    "XAGUSD": {"pip_decimal": 4, "pip_multiplier": 10000, "typ_spread": 2.0},
}


def _normalise_symbol(symbol: str) -> str:
    """Normalise a symbol string: uppercase, strip '/' or '.' separators."""
    return symbol.upper().replace("/", "").replace(".", "").strip()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def is_pair_supported(symbol: str) -> bool:
    """Return True if *symbol* is in the supported pair table."""
    return _normalise_symbol(symbol) in _PAIR_DATA


def list_supported_pairs() -> list[str]:
    """Return sorted list of all supported pair symbols."""
    return sorted(_PAIR_DATA.keys())


def get_pip_info(symbol: str) -> dict:
    """Return full pip metadata dict for *symbol*.

    Raises ``KeyError`` if the pair is not supported.
    """
    key = _normalise_symbol(symbol)
    if key not in _PAIR_DATA:
        raise KeyError(f"Unsupported pair: {symbol!r}")
    return dict(_PAIR_DATA[key])  # return a copy


def get_pip_multiplier(symbol: str) -> int:
    """Return the pip multiplier for *symbol* (e.g. 10000 for EURUSD)."""
    return get_pip_info(symbol)["pip_multiplier"]


def get_pip_value(
    symbol: str,
    lot_size: float = 1.0,
    account_currency: str = "USD",
    current_price: float | None = None,
) -> float:
    """Estimate the value of 1 pip in *account_currency* for a given lot size.

    For simplicity this uses a standard-lot base (100 000 units) and
    assumes the account currency is USD.  When the quote currency is not
    USD, *current_price* is needed for conversion; if omitted an
    approximate value of 1.0 is used (caller should supply live price
    for accuracy).

    Returns value in account-currency units.
    """
    key = _normalise_symbol(symbol)
    info = get_pip_info(key)
    pip_size = 1.0 / info["pip_multiplier"]
    contract_size = 100_000  # standard lot

    # Base pip value in quote currency
    base_pip_value = pip_size * contract_size * lot_size

    # --- Determine quote currency ---
    quote_ccy = _quote_currency(key)

    if quote_ccy == account_currency.upper():
        return base_pip_value

    # Need conversion — use current_price as a rough proxy
    price = current_price if current_price is not None else 1.0

    # If the pair itself IS <something>/account_ccy we already have it.
    # Otherwise divide or multiply depending on direction.
    # Simplified: for XXX/USD pairs base_pip_value is already in USD.
    # For USD/XXX pairs, convert:  pip_value_usd = base / price
    # For cross pairs the caller should supply a conversion rate to USD.
    if key.startswith(account_currency.upper()):
        # e.g. USDJPY — quote is JPY, convert JPY→USD
        return base_pip_value / price if price != 0 else 0.0

    # For metals or cross pairs, approximate
    return base_pip_value / price if price != 0 else 0.0


def _quote_currency(symbol: str) -> str:
    """Extract quote currency (last 3 chars) — works for 6-char FX pairs."""
    key = _normalise_symbol(symbol)
    if key in ("XAUUSD", "XAGUSD"):
        return "USD"
    return key[-3:] if len(key) >= 6 else "USD"


# ---------------------------------------------------------------------------
# Lot sizing helper
# ---------------------------------------------------------------------------


def calc_lot_size(
    symbol: str,
    risk_amount: float,
    stop_loss_pips: float,
    current_price: float | None = None,
    account_currency: str = "USD",
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    lot_step: float = 0.01,
) -> float:
    """Calculate lot size given a fixed risk amount and SL distance in pips.

    The result is clamped to [*min_lot*, *max_lot*] and rounded to the
    nearest *lot_step*.
    """
    if stop_loss_pips <= 0:
        return min_lot

    pip_val = get_pip_value(
        symbol,
        lot_size=1.0,
        account_currency=account_currency,
        current_price=current_price,
    )

    if pip_val <= 0:
        return min_lot

    raw_lot = risk_amount / (stop_loss_pips * pip_val)

    # Round to nearest lot_step
    raw_lot = round(round(raw_lot / lot_step) * lot_step, 8)

    # Clamp
    return max(min_lot, min(raw_lot, max_lot))
