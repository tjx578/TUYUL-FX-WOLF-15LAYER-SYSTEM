"""Pure Redis warmup decoding and stale-OHLC acceptance shared with the API."""

from typing import Any, cast

import orjson


def decode_candle_history(raw_entries: list[Any]) -> tuple[list[dict[str, Any]], int, int]:
    """Return dictionary candles plus non-dictionary and malformed counts."""
    candles: list[dict[str, Any]] = []
    non_dict = 0
    malformed = 0
    for raw in raw_entries:
        try:
            candle = orjson.loads(raw)
            if isinstance(candle, dict):
                candles.append(cast(dict[str, Any], candle))
            else:
                non_dict += 1
        except Exception:
            malformed += 1
    return candles, non_dict, malformed


def collapse_stale_ohlc(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain at most two consecutive equal OHLC bars, as engine warmup does."""
    if not candles:
        return []
    deduped = [candles[0]]
    run_len = 1
    for candle in candles[1:]:
        previous = deduped[-1]
        try:
            same = all(
                round(float(candle.get(field, 0)), 8) == round(float(previous.get(field, -1)), 8)
                for field in ("open", "high", "low", "close")
            )
        except (TypeError, ValueError):
            same = False
        if same:
            run_len += 1
            if run_len <= 2:
                deduped.append(candle)
        else:
            run_len = 1
            deduped.append(candle)
    return deduped
