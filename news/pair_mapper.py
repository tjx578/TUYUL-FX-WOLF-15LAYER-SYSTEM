"""
Currency → affected Forex pairs mapper.

Given the currency code affected by an economic event, this module
returns the list of major and minor FX pairs that are likely to move.

This is advisory information only — it does not imply execution authority.
"""

from __future__ import annotations

# ── Currency → pairs mapping ───────────────────────────────────────────────────
# Each currency maps to the pairs most commonly impacted by that currency's
# economic releases, ordered by typical liquidity.
_CURRENCY_PAIRS: dict[str, list[str]] = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD"],
    "EUR": ["EURUSD", "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD"],
    "GBP": ["GBPUSD", "EURGBP", "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "CADJPY", "AUDJPY", "NZDJPY", "CHFJPY"],
    "CHF": ["USDCHF", "EURCHF", "GBPCHF", "CHFJPY"],
    "AUD": ["AUDUSD", "EURAUD", "GBPAUD", "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF"],
    "NZD": ["NZDUSD", "EURNZD", "GBPNZD", "NZDJPY", "AUDNZD", "NZDCAD", "NZDCHF"],
    "CAD": ["USDCAD", "EURCAD", "GBPCAD", "CADJPY", "AUDCAD", "NZDCAD", "CADCHF"],
    "CNY": ["USDCNH"],
    "CNH": ["USDCNH"],
    "SGD": ["USDSGD"],
    "HKD": ["USDHKD"],
    "NOK": ["USDNOK", "EURNOK"],
    "SEK": ["USDSEK", "EURSEK"],
    "DKK": ["USDDKK", "EURDKK"],
    "MXN": ["USDMXN"],
    "ZAR": ["USDZAR"],
    "TRY": ["USDTRY"],
}


def get_affected_pairs(currency: str | None) -> list[str]:
    """
    Return the list of FX pairs typically affected by a *currency* release.

    Parameters
    ----------
    currency : str | None
        ISO 4217 currency code (e.g. 'USD', 'EUR').  Case-insensitive.
        If None or unknown, returns an empty list.

    Returns
    -------
    list[str]
        Ordered list of impacted FX pair symbols.  Empty if currency unknown.
    """
    if not currency:
        return []
    return _CURRENCY_PAIRS.get(currency.strip().upper(), [])
