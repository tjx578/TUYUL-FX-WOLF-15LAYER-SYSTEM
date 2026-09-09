"""Observational comparison of independently identified, closed H1 bars.

A live quote is never a substitute for a WS-built closed candle. Missing
evidence is not evidence of either provider corruption or recovery.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from config.pip_values import get_pip_multiplier


def _epoch(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return None
            value = value.timestamp()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None
    except (ValueError, OverflowError, OSError):
        return None


def _price(value: Any) -> float | None:
    try:
        result = float(value)
        return result if not isinstance(value, bool) and math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def compare_closed_h1(
    symbol: str,
    candles: list[dict[str, Any]],
    tick: dict[str, Any] | None,
    max_drift_pips: float,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Require exact UTC-hour alignment and a just-closed (age <1h) pair.

    Each bar must carry source/provider identity, provider_symbol, explicit
    open/close timestamps, complete=True and a post-close receipt timestamp.
    Old aligned bars remain historical evidence, not actionable live drift.
    """
    now = datetime.now(UTC).timestamp() if now is None else now
    symbol = symbol.strip().upper()
    rest = next((c for c in reversed(candles) if c.get("source") == "rest_api"), None)
    ws = [c for c in reversed(candles) if c.get("provider") == "wolf15_tick_builder"]
    result: dict[str, Any] = {
        "comparable": False,
        "actionable": False,
        "reason": "MISSING_REST_H1",
        "drifted": False,
        "drift_pips": 0.0,
        "rest_close": _price(rest.get("close")) if rest else None,
        "ws_h1_close": None,
        "ws_mid": None,
        "observed_live_gap_pips": None,
    }
    try:
        multiplier = get_pip_multiplier(symbol)
    except LookupError:
        result["reason"] = "UNKNOWN_PIP_MULTIPLIER"
        return result
    if tick:
        bid = _price(tick.get("bid", tick.get("price")))
        ask = _price(tick.get("ask", tick.get("price")))
        if bid is not None and ask is not None:
            result["ws_mid"] = (bid + ask) / 2
            if result["rest_close"] is not None:
                result["observed_live_gap_pips"] = abs(result["rest_close"] - result["ws_mid"]) * multiplier
    if rest is None:
        return result

    def validate(bar: dict[str, Any], lane: str) -> str | None:
        if bar.get("symbol") != symbol or bar.get("timeframe") != "H1":
            return f"{lane}_SYMBOL_OR_TIMEFRAME_MISMATCH"
        provider_symbol = bar.get("provider_symbol")
        if not isinstance(provider_symbol, str) or provider_symbol.rsplit(":", 1)[-1].replace("_", "") != symbol:
            return f"{lane}_PROVIDER_SYMBOL_MISSING_OR_MISMATCH"
        if not isinstance(bar.get("provider"), str) or not bar["provider"].strip():
            return f"{lane}_PROVIDER_MISSING"
        if lane == "REST" and (bar["provider"] == "wolf15_tick_builder" or bar.get("provider_feed") == "finnhub_ws"):
            return "REST_LINEAGE_INVALID"
        if lane == "WS" and (bar.get("provider_feed") != "finnhub_ws" or bar.get("source") == "rest_api"):
            return "WS_LINEAGE_MISSING_OR_INVALID"
        if bar.get("complete") is not True:
            return f"{lane}_NOT_EXPLICITLY_CLOSED"
        opened, closed = _epoch(bar.get("open_time")), _epoch(bar.get("close_time"))
        received = _epoch(bar.get("received_at_utc"))
        if opened is None or closed is None or received is None:
            return f"{lane}_TIMESTAMP_MISSING_OR_INVALID"
        if closed - opened != 3600 or opened % 3600 != 0:
            return f"{lane}_H1_PERIOD_INVALID"
        if closed > now or received < closed or received > now:
            return f"{lane}_TIMESTAMP_ORDER_INVALID"
        if now - closed >= 3600:
            return f"{lane}_STALE_CLOSED_H1"
        if _price(bar.get("close")) is None:
            return f"{lane}_PRICE_INVALID"
        return None

    reason = validate(rest, "REST")
    if reason:
        result["reason"] = reason
        return result
    matches = [
        c
        for c in ws
        if _epoch(c.get("open_time")) == _epoch(rest.get("open_time"))
        and _epoch(c.get("close_time")) == _epoch(rest.get("close_time"))
    ]
    if len(matches) != 1:
        result["reason"] = "MISSING_WS_CLOSED_H1" if not ws else "WS_PERIOD_MISMATCH_OR_AMBIGUOUS"
        return result
    reason = validate(matches[0], "WS")
    if reason:
        result["reason"] = reason
        return result
    if not math.isfinite(max_drift_pips) or max_drift_pips < 0:
        result["reason"] = "INVALID_DRIFT_THRESHOLD"
        return result
    result.update(
        comparable=True, actionable=True, reason="ALIGNED_CLOSED_H1", ws_h1_close=_price(matches[0].get("close"))
    )
    result["drift_pips"] = abs(result["rest_close"] - result["ws_h1_close"]) * multiplier
    result["drifted"] = result["drift_pips"] > max_drift_pips
    if result["drifted"]:
        logger.warning(
            "Price drift alert: {} REST_close={:.5f} WS_H1_close={:.5f} drift={:.1f} pips (max={:.1f})",
            symbol,
            result["rest_close"],
            result["ws_h1_close"],
            result["drift_pips"],
            max_drift_pips,
        )
    return result
