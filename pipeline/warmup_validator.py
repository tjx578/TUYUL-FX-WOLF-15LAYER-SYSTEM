from __future__ import annotations

import logging
import time


class TradingError(Exception):
    """Base exception for trading-related errors."""


class WarmupBarsMissingError(TradingError):
    """Raised when not enough bars are available for warmup."""


def fetch_historical_bars(symbol: str, required: int, fetch_fn, max_retries: int = 5) -> list[dict]:
    """
    Ensure sufficient bars exist for a symbol. Retries with exponential backoff if missing.
    Args:
        symbol (str): Forex symbol.
        required (int): Required number of bars.
        fetch_fn (Callable): Function to fetch bars (symbol) -> List.
        max_retries (int): Max retry attempts.
    Returns:
        List[dict]: List of bar data.
    """
    delay = 1
    for attempt in range(max_retries):
        bars = fetch_fn(symbol)
        logging.info(f"Fetched {len(bars)} bars for {symbol} (attempt {attempt + 1})")
        if len(bars) >= required:
            return bars
        logging.warning(f"[Warmup] Not enough bars for {symbol}: required={required}, found={len(bars)}")
        if attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2  # Exponential backoff
    raise WarmupBarsMissingError(f"Failed to obtain {required} bars for {symbol} after {max_retries} attempts")


def validate_warmup_all(
    data: dict[str, list[dict]],
    required_bars: int = 2,
    fetch_fn=None,
):
    """
    Validate and optionally fetch missing data for all tracked symbols.
    Args:
        data (dict): {symbol: [bars]}
        required_bars (int): Minimum bars required.
        fetch_fn (Callable): Fetch function for missing bars (symbol) -> List.
    Raises:
        WarmupBarsMissingError: If bars are still insufficient after retries.
    """
    for symbol, bars in data.items():
        if len(bars) < required_bars:
            if fetch_fn is not None:
                bars = fetch_historical_bars(symbol, required_bars, fetch_fn)
                data[symbol] = bars
            if len(bars) < required_bars:
                logging.error(f"[Warmup] Insufficient bars for {symbol} | bars={len(bars)} required={required_bars}")
                raise WarmupBarsMissingError(
                    f"Warmup rejected | symbol={symbol} bars={len(bars)} "
                    f"required={required_bars} missing={required_bars - len(bars)}"
                )
