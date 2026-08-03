"""Increment H1 — HTF Structure Snapshot (NON-EXECUTABLE, flag-guarded default ON).

Strategic role
--------------
After the safety / watch / microboost / Patch-3 layer was made leak-proof, the
*next* primary filter is no longer intraday pressure but **higher-timeframe
market structure**::

    Microboost / SignalThrottle = intraday pressure radar
    M15 / M5                    = entry timing + validation
    H4                          = primary operational structure
    Daily                       = big-picture bias / premium-discount / invalidation

This module is the first increment (H1) of the HTF Market Structure Resolver
roadmap.  It reads **Daily + H4** candles and emits a *structure snapshot* — a
read-only description of where price is and what is structurally allowed.  It
deliberately does **not**:

    * produce a SignalJSON,
    * produce SL / TP,
    * turn BUY pressure into a BUY LIMIT,
    * set ``valid_for_execution`` to anything but ``False``.

The single hard invariant of H1 is::

    valid_for_execution == False    # always, by construction

Turning pressure into ``BUY_LIMIT_WATCH`` / ``SELL_LIMIT_WATCH`` is a *later*
increment (H4) and only after structure is proven valid.  H1 only describes;
it never authorises.

Output event (compact JSON log line, prefix ``[HTFStructureSnapshot]``)::

    {
      "event": "htf_structure_snapshot_json",
      "symbol": "GBPNZD",
      "daily_bias": "BEARISH",
      "h4_structure": "BEARISH_PULLBACK",
      "price_location": "H4_SUPPLY",
      "liquidity_context": "BUY_SIDE_LIQUIDITY_TEST",
      "allowed_playbook": "SELL_ON_REJECTION",
      "blocked_playbook": ["BUY_LIMIT", "BUY_BREAKOUT_CHASE"],
      "valid_for_execution": false,
      "is_final_signal": false
    }

Zone: analysis/ — perception & context only.  No execution, no side effects
beyond an opt-in log line.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from analysis.candle_freshness import candle_age_seconds, parse_candle_timestamp
from utils.forex_session_calendar import (
    FOREX_DAILY_FRESHNESS_BASIS,
    forex_daily_period_from_close,
    forex_daily_period_from_open,
    latest_expected_forex_daily_period,
    missed_expected_forex_daily_bars,
)

__all__ = [
    "HTFStructureSnapshot",
    "HTFStructureSnapshotResolver",
    "build_htf_structure_snapshot_event",
    "classify_daily_bias_v2",
    "classify_liquidity_resolution",
    "emit_htf_structure_snapshot",
    "resolve_htf_structure_snapshot",
]

# ═══════════════════════════════════════════════════════════════════════════
# §0  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

EVENT_NAME = "htf_structure_snapshot_json"
SCHEMA_VERSION = "2.1"
LOG_PREFIX = "[HTFStructureSnapshot]"

# Env flag — default ON.  HTF structure is now a first-class map/context feed;
# it remains non-executable and can still be disabled instantly for rollback.
ENABLE_ENV = "HTF_STRUCTURE_SNAPSHOT_ENABLED"

# Candle lookbacks (how many bars to pull per timeframe).
_DAILY_LOOKBACK = 60
_H4_LOOKBACK = 120

# Fractal swing window: a bar is a swing point if it dominates ``window`` bars
# on each side.
_SWING_WINDOW = 2

# Minimum bars required for a timeframe to be considered analysable.
_MIN_DAILY_BARS = 10
_MIN_H4_BARS = 12
_DAILY_BIAS_RULE_VERSION = 3
_LIQUIDITY_RESOLUTION_RULE_VERSION = 1
_DEFAULT_DAILY_BIAS_MAX_AGE_SECONDS = 259_200.0
_DEFAULT_LIQUIDITY_MAX_AGE_SECONDS = 21_600.0

# Premium/discount equilibrium band (fraction of dealing range around 0.5).
# pct >= 0.5 + band -> PREMIUM ; pct <= 0.5 - band -> DISCOUNT ; else EQUILIBRIUM.
_EQUILIBRIUM_BAND = 0.05

# Dealing-range lookback for premium/discount (most recent N bars high/low).
_RANGE_LOOKBACK_DAILY = 30

# Proximity tolerance to a structural extreme, as a fraction of the dealing
# range.  Used for liquidity-test detection and supply/demand refinement.
_EXTREME_TOL = 0.12
_ZONE_TOL = 0.15

# ── Bias / structure / location / liquidity / playbook vocabularies ────────
# (declared here so downstream increments + tests share one source of truth)

BIAS_BULLISH = "BULLISH"
BIAS_BEARISH = "BEARISH"
BIAS_RANGE = "RANGE"
BIAS_TRANSITION = "TRANSITION"
BIAS_NO_BIAS = "NO_BIAS"
BIAS_STALE = "STALE"

H4_BULLISH_IMPULSE = "BULLISH_IMPULSE"
H4_BULLISH_PULLBACK = "BULLISH_PULLBACK"
H4_BEARISH_IMPULSE = "BEARISH_IMPULSE"
H4_BEARISH_PULLBACK = "BEARISH_PULLBACK"
H4_RANGE = "RANGE"
H4_NO_STRUCTURE = "NO_STRUCTURE"

LOC_PREMIUM = "PREMIUM"
LOC_DISCOUNT = "DISCOUNT"
LOC_EQUILIBRIUM = "EQUILIBRIUM"
LOC_H4_SUPPLY = "H4_SUPPLY"
LOC_H4_DEMAND = "H4_DEMAND"
LOC_UNKNOWN = "UNKNOWN"

LIQ_BUY_SIDE = "BUY_SIDE_LIQUIDITY_TEST"
LIQ_SELL_SIDE = "SELL_SIDE_LIQUIDITY_TEST"
LIQ_NONE = "NONE"

LIQ_BUY_APPROACHING = "BUY_SIDE_APPROACHING"
LIQ_BUY_TESTING = "BUY_SIDE_TESTING"
LIQ_BUY_ACCEPTED = "BUY_SIDE_ACCEPTED"
LIQ_BUY_REJECTED = "BUY_SIDE_REJECTED"
LIQ_BUY_EXPIRED = "BUY_SIDE_EXPIRED"
LIQ_SELL_APPROACHING = "SELL_SIDE_APPROACHING"
LIQ_SELL_TESTING = "SELL_SIDE_TESTING"
LIQ_SELL_ACCEPTED = "SELL_SIDE_ACCEPTED"
LIQ_SELL_REJECTED = "SELL_SIDE_REJECTED"
LIQ_SELL_EXPIRED = "SELL_SIDE_EXPIRED"


# ═══════════════════════════════════════════════════════════════════════════
# §1  PURE STRUCTURE PRIMITIVES (no I/O, fully unit-testable)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Swing:
    """A detected swing point."""

    index: int
    price: float


def _candle_high(candle: dict[str, Any]) -> float | None:
    try:
        return float(candle["high"])
    except (KeyError, TypeError, ValueError):
        return None


def _candle_low(candle: dict[str, Any]) -> float | None:
    try:
        return float(candle["low"])
    except (KeyError, TypeError, ValueError):
        return None


def _candle_close(candle: dict[str, Any]) -> float | None:
    try:
        return float(candle["close"])
    except (KeyError, TypeError, ValueError):
        return None


def find_swing_highs(candles: list[dict[str, Any]], window: int = _SWING_WINDOW) -> list[Swing]:
    """Return fractal swing highs (strictly dominant over ``window`` neighbours)."""
    highs = [_candle_high(c) for c in candles]
    out: list[Swing] = []
    n = len(highs)
    for i in range(window, n - window):
        pivot = highs[i]
        if pivot is None:
            continue
        is_peak = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            neighbour = highs[j]
            if neighbour is None or neighbour >= pivot:
                is_peak = False
                break
        if is_peak:
            out.append(Swing(i, pivot))
    return out


def find_swing_lows(candles: list[dict[str, Any]], window: int = _SWING_WINDOW) -> list[Swing]:
    """Return fractal swing lows (strictly dominant over ``window`` neighbours)."""
    lows = [_candle_low(c) for c in candles]
    out: list[Swing] = []
    n = len(lows)
    for i in range(window, n - window):
        pivot = lows[i]
        if pivot is None:
            continue
        is_valley = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            neighbour = lows[j]
            if neighbour is None or neighbour <= pivot:
                is_valley = False
                break
        if is_valley:
            out.append(Swing(i, pivot))
    return out


def classify_bias(swing_highs: list[Swing], swing_lows: list[Swing]) -> str:
    """Classify HTF directional bias from the last two swing highs/lows.

    Matrix (HH = higher high, LH = lower high, HL = higher low, LL = lower low):

        HH + HL -> BULLISH
        LH + LL -> BEARISH
        LH + HL -> RANGE        (contraction / inside structure)
        HH + LL -> TRANSITION   (expansion — direction unconfirmed)
        otherwise -> RANGE

    Insufficient swings -> NO_BIAS.
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return BIAS_NO_BIAS

    hh = swing_highs[-1].price > swing_highs[-2].price
    lh = swing_highs[-1].price < swing_highs[-2].price
    hl = swing_lows[-1].price > swing_lows[-2].price
    ll = swing_lows[-1].price < swing_lows[-2].price

    if hh and hl:
        return BIAS_BULLISH
    if lh and ll:
        return BIAS_BEARISH
    if hh and ll:
        return BIAS_TRANSITION
    # LH+HL (contraction) and all equal-price ties fall through to RANGE.
    return BIAS_RANGE


def _ema(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append((value * alpha) + (result[-1] * (1.0 - alpha)))
    return result


def classify_daily_bias_v2(candles: list[dict[str, Any]], window: int = _SWING_WINDOW) -> str:
    """Resolve Daily bias from closed-bar swing structure plus EMA20 momentum.

    The legacy two-swing classifier is retained as the structural authority.
    EMA20 position and five-bar slope only resolve the legacy ``RANGE`` /
    ``NO_BIAS`` blind spot, or downgrade a direct swing/momentum conflict to
    ``TRANSITION``.  It never creates execution authority.
    """

    closed = [candle for candle in candles if not _is_explicitly_forming(candle)]
    swing_bias = classify_bias(find_swing_highs(closed, window), find_swing_lows(closed, window))
    closes = [value for candle in closed if (value := _candle_close(candle)) is not None]
    if len(closes) < 20:
        return swing_bias

    ema20 = _ema(closes, 20)
    slope_lookback = min(5, len(ema20) - 1)
    if slope_lookback <= 0:
        return swing_bias
    slope = ema20[-1] - ema20[-1 - slope_lookback]
    atr = _average_true_range(closed) or 0.0
    material_move = max(atr * 0.05, abs(ema20[-1]) * 1e-6)
    momentum_bias = BIAS_RANGE
    if closes[-1] > ema20[-1] and slope > material_move:
        momentum_bias = BIAS_BULLISH
    elif closes[-1] < ema20[-1] and slope < -material_move:
        momentum_bias = BIAS_BEARISH

    if swing_bias in {BIAS_RANGE, BIAS_NO_BIAS} and momentum_bias in {BIAS_BULLISH, BIAS_BEARISH}:
        return momentum_bias
    if swing_bias == BIAS_BULLISH and momentum_bias == BIAS_BEARISH:
        return BIAS_TRANSITION
    if swing_bias == BIAS_BEARISH and momentum_bias == BIAS_BULLISH:
        return BIAS_TRANSITION
    return swing_bias


def _detect_choch(bias: str, close: float | None, swing_highs: list[Swing], swing_lows: list[Swing]) -> bool:
    """Detect a fresh change-of-character against the swing-derived bias.

    A close beyond the *opposing* most-recent swing flips the read into a
    transition (the trend is no longer cleanly intact).
    """
    if close is None:
        return False
    if bias == BIAS_BULLISH and swing_lows:
        return close < swing_lows[-1].price
    if bias == BIAS_BEARISH and swing_highs:
        return close > swing_highs[-1].price
    return False


def classify_h4_structure(candles: list[dict[str, Any]], window: int = _SWING_WINDOW) -> str:
    """Classify H4 operating structure as impulse / pullback / range.

    Uses the swing-derived trend, then asks whether price is *extending* the
    trend (impulse) or retracing inside it (pullback) by comparing the latest
    close against the most recent swing high/low.
    """
    if len(candles) < _MIN_H4_BARS:
        return H4_NO_STRUCTURE

    highs = find_swing_highs(candles, window)
    lows = find_swing_lows(candles, window)
    trend = classify_bias(highs, lows)
    close = _candle_close(candles[-1])

    if close is None or not highs or not lows:
        return H4_NO_STRUCTURE

    last_high = highs[-1].price
    last_low = lows[-1].price

    if trend == BIAS_BULLISH:
        # At/above the last swing high = still impulsing up; below = pullback.
        return H4_BULLISH_IMPULSE if close >= last_high else H4_BULLISH_PULLBACK
    if trend == BIAS_BEARISH:
        return H4_BEARISH_IMPULSE if close <= last_low else H4_BEARISH_PULLBACK
    if trend in (BIAS_RANGE, BIAS_TRANSITION):
        return H4_RANGE
    return H4_NO_STRUCTURE


def dealing_range(candles: list[dict[str, Any]], lookback: int) -> tuple[float, float] | None:
    """Return ``(range_high, range_low)`` over the last ``lookback`` bars."""
    window = candles[-lookback:] if lookback and lookback < len(candles) else candles
    highs = [h for c in window if (h := _candle_high(c)) is not None]
    lows = [low for c in window if (low := _candle_low(c)) is not None]
    if not highs or not lows:
        return None
    hi, lo = max(highs), min(lows)
    if hi <= lo:
        return None
    return hi, lo


def location_pct(close: float, range_high: float, range_low: float) -> float:
    """Where ``close`` sits inside the dealing range, in ``[0.0, 1.0]``."""
    span = range_high - range_low
    if span <= 0:
        return 0.5
    return max(0.0, min(1.0, (close - range_low) / span))


def classify_price_location(
    close: float | None,
    daily_range: tuple[float, float] | None,
    h4_swing_high: float | None,
    h4_swing_low: float | None,
) -> str:
    """Premium / discount / equilibrium, refined to H4 supply/demand at extremes."""
    if close is None or daily_range is None:
        return LOC_UNKNOWN

    range_high, range_low = daily_range
    pct = location_pct(close, range_high, range_low)
    span = range_high - range_low

    if pct >= 0.5 + _EQUILIBRIUM_BAND:
        base = LOC_PREMIUM
    elif pct <= 0.5 - _EQUILIBRIUM_BAND:
        base = LOC_DISCOUNT
    else:
        return LOC_EQUILIBRIUM

    # Refine to a structural H4 zone when price is parked at an H4 extreme.
    tol = span * _ZONE_TOL
    if base == LOC_PREMIUM and h4_swing_high is not None and abs(close - h4_swing_high) <= tol:
        return LOC_H4_SUPPLY
    if base == LOC_DISCOUNT and h4_swing_low is not None and abs(close - h4_swing_low) <= tol:
        return LOC_H4_DEMAND
    return base


def classify_liquidity_context(close: float | None, daily_range: tuple[float, float] | None) -> str:
    """Which liquidity pool price is currently testing (proximity to extremes).

    Buy-side liquidity rests above prior highs; sell-side below prior lows.
    A price hugging the range high is *testing buy-side liquidity*, and vice
    versa.  H1 keeps this proximity-based — true sweep/reclaim detection is a
    later increment (H3).
    """
    if close is None or daily_range is None:
        return LIQ_NONE
    range_high, range_low = daily_range
    span = range_high - range_low
    if span <= 0:
        return LIQ_NONE
    tol = span * _EXTREME_TOL
    if abs(range_high - close) <= tol:
        return LIQ_BUY_SIDE
    if abs(close - range_low) <= tol:
        return LIQ_SELL_SIDE
    return LIQ_NONE


def classify_liquidity_resolution(
    candle: dict[str, Any] | None,
    daily_range: tuple[float, float] | None,
    *,
    atr: float | None = None,
) -> str:
    """Classify an auditable buy/sell-side liquidity lifecycle state.

    Acceptance requires a closed price beyond the prior range. Rejection
    requires a wick through the range followed by a close back inside. Merely
    approaching or touching an extreme remains unresolved telemetry.
    """

    if not isinstance(candle, dict) or daily_range is None:
        return LIQ_NONE
    close = _candle_close(candle)
    high = _candle_high(candle)
    low = _candle_low(candle)
    if close is None or high is None or low is None:
        return LIQ_NONE
    range_high, range_low = daily_range
    span = range_high - range_low
    if span <= 0:
        return LIQ_NONE

    break_buffer = max(span * 0.0025, float(atr or 0.0) * 0.10)
    test_tolerance = max(span * 0.03, float(atr or 0.0) * 0.25)
    ratio = location_pct(close, range_high, range_low)

    if close > range_high + break_buffer:
        return LIQ_BUY_ACCEPTED
    if high > range_high and close < range_high - break_buffer:
        return LIQ_BUY_REJECTED
    if close < range_low - break_buffer:
        return LIQ_SELL_ACCEPTED
    if low < range_low and close > range_low + break_buffer:
        return LIQ_SELL_REJECTED
    if high >= range_high - test_tolerance or ratio >= 0.88:
        return LIQ_BUY_TESTING
    if low <= range_low + test_tolerance or ratio <= 0.12:
        return LIQ_SELL_TESTING
    if ratio >= 0.72:
        return LIQ_BUY_APPROACHING
    if ratio <= 0.28:
        return LIQ_SELL_APPROACHING
    return LIQ_NONE


def _liquidity_context_from_resolution(resolution: str) -> str:
    if resolution.startswith("BUY_SIDE_"):
        return LIQ_BUY_SIDE
    if resolution.startswith("SELL_SIDE_"):
        return LIQ_SELL_SIDE
    return LIQ_NONE


def _zone_pad(daily_range: tuple[float, float] | None) -> float | None:
    if daily_range is None:
        return None
    high, low = daily_range
    span = high - low
    if span <= 0:
        return None
    return span * 0.03


def _average_true_range(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    """Return a closed-bar ATR in price units without introducing a TA dependency."""

    closed_candles = [candle for candle in candles if not _is_explicitly_forming(candle)]
    if len(closed_candles) < 2 or period <= 0:
        return None
    true_ranges: list[float] = []
    start = max(1, len(closed_candles) - period)
    for index in range(start, len(closed_candles)):
        high = _candle_high(closed_candles[index])
        low = _candle_low(closed_candles[index])
        previous_close = _candle_close(closed_candles[index - 1])
        if high is None or low is None or previous_close is None:
            continue
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if not true_ranges:
        return None
    return sum(true_ranges) / len(true_ranges)


def _is_explicitly_forming(candle: dict[str, Any]) -> bool:
    for key in ("closed", "is_closed", "complete", "is_complete"):
        if key not in candle:
            continue
        value = candle.get(key)
        if value is False or str(value).strip().lower() in {"false", "0", "no", "open", "forming"}:
            return True
    return False


def _closed_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candle for candle in candles if not _is_explicitly_forming(candle)]


def _candle_source_time(candle: dict[str, Any] | None) -> str | None:
    if not isinstance(candle, dict):
        return None
    raw = (
        candle.get("timestamp")
        or candle.get("time")
        or candle.get("datetime")
        or candle.get("open_time")
        or candle.get("close_time")
    )
    parsed = parse_candle_timestamp(raw)
    return None if parsed is None else parsed.isoformat()


@dataclass(frozen=True)
class _DailyFreshnessEvidence:
    status: str
    basis: str
    source_period_open: str | None
    source_period_close: str | None
    latest_expected_period_open: str | None
    latest_expected_period_close: str | None
    missed_expected_closed_bars: int | None
    provider_timestamp_semantics: str


def _daily_freshness_evidence(
    candle: dict[str, Any] | None,
    *,
    now: datetime,
    fallback_age_seconds: float | None,
    fallback_max_age_seconds: float,
) -> _DailyFreshnessEvidence:
    """Resolve Daily freshness from closed trading periods, not wall time."""

    expected = latest_expected_forex_daily_period(now)
    if not isinstance(candle, dict):
        return _DailyFreshnessEvidence(
            status=_freshness_status(fallback_age_seconds, fallback_max_age_seconds),
            basis="WALL_CLOCK_FALLBACK_NO_D1_PERIOD",
            source_period_open=None,
            source_period_close=None,
            latest_expected_period_open=expected.open_at_utc.isoformat(),
            latest_expected_period_close=expected.close_at_utc.isoformat(),
            missed_expected_closed_bars=None,
            provider_timestamp_semantics="UNKNOWN",
        )

    semantics = str(candle.get("provider_timestamp_semantics") or "UNSPECIFIED").strip().upper()
    explicit_open = parse_candle_timestamp(candle.get("open_time"))
    explicit_close = parse_candle_timestamp(candle.get("close_time"))
    provider_time = parse_candle_timestamp(candle.get("provider_timestamp"))
    generic_time = parse_candle_timestamp(
        candle.get("timestamp") or candle.get("time") or candle.get("datetime")
    )

    period = None
    if explicit_close is not None:
        period = forex_daily_period_from_close(explicit_close)
        if explicit_open is not None:
            period = period.__class__(open_at_utc=explicit_open, close_at_utc=explicit_close)
        resolved_semantics = semantics if semantics != "UNSPECIFIED" else "EXPLICIT_PERIOD_BOUNDS"
    elif semantics == "PERIOD_END" and (provider_time or generic_time) is not None:
        period = forex_daily_period_from_close(provider_time or generic_time)  # type: ignore[arg-type]
        resolved_semantics = semantics
    else:
        # The live Finnhub provider and the legacy HTF snapshots use period-open
        # timestamps.  Explicit semantics win; UNSPECIFIED remains auditable as
        # a compatibility assumption instead of silently pretending PERIOD_END.
        open_at = explicit_open or provider_time or generic_time
        if open_at is not None:
            period = forex_daily_period_from_open(open_at)
        resolved_semantics = semantics if semantics != "UNSPECIFIED" else "ASSUMED_PERIOD_OPEN"

    if period is None:
        return _DailyFreshnessEvidence(
            status=_freshness_status(fallback_age_seconds, fallback_max_age_seconds),
            basis="WALL_CLOCK_FALLBACK_UNRESOLVED_D1_PERIOD",
            source_period_open=None,
            source_period_close=None,
            latest_expected_period_open=expected.open_at_utc.isoformat(),
            latest_expected_period_close=expected.close_at_utc.isoformat(),
            missed_expected_closed_bars=None,
            provider_timestamp_semantics=resolved_semantics,
        )

    missed = missed_expected_forex_daily_bars(period.close_at_utc, expected.close_at_utc)
    return _DailyFreshnessEvidence(
        status="FRESH" if missed == 0 else "STALE",
        basis=FOREX_DAILY_FRESHNESS_BASIS,
        source_period_open=period.open_at_utc.isoformat(),
        source_period_close=period.close_at_utc.isoformat(),
        latest_expected_period_open=expected.open_at_utc.isoformat(),
        latest_expected_period_close=expected.close_at_utc.isoformat(),
        missed_expected_closed_bars=missed,
        provider_timestamp_semantics=resolved_semantics,
    )


def _env_max_age(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _freshness_status(age_seconds: float | None, max_age_seconds: float) -> str:
    if age_seconds is None:
        return "UNKNOWN"
    return "STALE" if age_seconds > max_age_seconds else "FRESH"


def _pip_size(symbol: str) -> float:
    symbol_key = str(symbol or "").upper()
    if symbol_key.endswith("JPY"):
        return 0.01
    if symbol_key in {"XAUUSD", "XAGUSD"}:
        return 0.01
    return 0.0001


def _distance_pips(left: float | None, right: float | None, symbol: str) -> float | None:
    if left is None or right is None:
        return None
    return round(abs(float(left) - float(right)) / _pip_size(symbol), 3)


def _h4_supply_zone(swing_high: float | None, daily_range: tuple[float, float] | None) -> list[float] | None:
    pad = _zone_pad(daily_range)
    if swing_high is None or pad is None:
        return None
    return [round(swing_high - pad, 6), round(swing_high, 6)]


def _h4_demand_zone(swing_low: float | None, daily_range: tuple[float, float] | None) -> list[float] | None:
    pad = _zone_pad(daily_range)
    if swing_low is None or pad is None:
        return None
    return [round(swing_low, 6), round(swing_low + pad, 6)]


def _daily_fib_levels(daily_range: tuple[float, float] | None) -> dict[str, float] | None:
    if daily_range is None:
        return None
    high, low = daily_range
    span = high - low
    if span <= 0:
        return None
    return {
        "fib_382": round(low + span * 0.382, 6),
        "fib_500": round(low + span * 0.5, 6),
        "fib_618": round(low + span * 0.618, 6),
    }


def _daily_fib_zone(daily_range: tuple[float, float] | None) -> list[float] | None:
    levels = _daily_fib_levels(daily_range)
    if not levels:
        return None
    return [levels["fib_382"], levels["fib_618"]]


def resolve_playbook(daily_bias: str, price_location: str) -> tuple[str, list[str]]:
    """Map (daily_bias, price_location) to (allowed_playbook, blocked_playbook).

    This is the structural guardrail that enforces the core rule —
    *BUY pressure is never automatically a BUY LIMIT*.  A counter-trend limit
    order is always present in ``blocked_playbook`` whenever the Daily does not
    support it.  ``allowed_playbook`` is descriptive only; nothing here
    authorises execution (``valid_for_execution`` stays ``False``).
    """
    in_premium = price_location in (LOC_PREMIUM, LOC_H4_SUPPLY)
    in_discount = price_location in (LOC_DISCOUNT, LOC_H4_DEMAND)

    if daily_bias == BIAS_BEARISH:
        allowed = "SELL_ON_REJECTION" if in_premium else "WAIT_FOR_SELL_LOCATION"
        return allowed, ["BUY_LIMIT", "BUY_BREAKOUT_CHASE"]

    if daily_bias == BIAS_BULLISH:
        allowed = "BUY_ON_REJECTION" if in_discount else "WAIT_FOR_BUY_LOCATION"
        return allowed, ["SELL_LIMIT", "SELL_BREAKOUT_CHASE"]

    if daily_bias == BIAS_RANGE:
        return "RANGE_FADE_EXTREME", ["BUY_BREAKOUT_CHASE", "SELL_BREAKOUT_CHASE"]

    if daily_bias == BIAS_TRANSITION:
        # Regime in flux / unconfirmed CHoCH — no resting limits either side.
        return "WAIT_FOR_CONFIRMATION", ["BUY_LIMIT", "SELL_LIMIT"]

    # NO_BIAS — nothing is structurally supported.
    return "NONE", ["BUY_LIMIT", "SELL_LIMIT", "BUY_BREAKOUT_CHASE", "SELL_BREAKOUT_CHASE"]


# ═══════════════════════════════════════════════════════════════════════════
# §2  SNAPSHOT EVENT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class HTFStructureSnapshot:
    """Immutable, non-executable HTF structure snapshot (Increment H1)."""

    symbol: str
    daily_bias: str
    h4_structure: str
    price_location: str
    liquidity_context: str
    allowed_playbook: str
    blocked_playbook: list[str]
    data_sufficient: bool
    reason: str
    daily_bars: int = 0
    h4_bars: int = 0
    h4_swing_high: float | None = None
    h4_swing_low: float | None = None
    h4_atr: float | None = None
    daily_atr: float | None = None
    daily_range_high: float | None = None
    daily_range_low: float | None = None
    h4_supply_zone: list[float] | None = None
    h4_demand_zone: list[float] | None = None
    daily_fib_zone: list[float] | None = None
    daily_fib_levels: dict[str, float] | None = None
    daily_bias_unstaled: str | None = None
    daily_bias_source: str = "D1_CLOSED_CANDLE_SWING_EMA20"
    daily_bias_source_candle: str | None = None
    daily_bias_snapshot_time: str | None = None
    daily_bias_age_seconds: float | None = None
    daily_bias_freshness_status: str = "UNKNOWN"
    daily_bias_freshness_basis: str = "UNKNOWN"
    daily_bias_source_period_open: str | None = None
    daily_bias_source_period_close: str | None = None
    daily_bias_latest_expected_period_open: str | None = None
    daily_bias_latest_expected_period_close: str | None = None
    daily_bias_missed_expected_closed_bars: int | None = None
    daily_bias_provider_timestamp_semantics: str = "UNKNOWN"
    daily_bias_max_age_seconds: float = _DEFAULT_DAILY_BIAS_MAX_AGE_SECONDS
    daily_bias_rule_version: int = _DAILY_BIAS_RULE_VERSION
    daily_bias_advisory_only: bool = False
    daily_bias_execution_impact: bool = True
    daily_bias_execution_block_reason: str | None = None
    location_reference_price: float | None = None
    location_reference_time: str | None = None
    location_reference_source: str | None = None
    location_reference_age_seconds: float | None = None
    location_ratio: float | None = None
    dealing_range_source: str | None = None
    distance_to_range_high_pips: float | None = None
    distance_to_range_low_pips: float | None = None
    liquidity_resolution: str = LIQ_NONE
    liquidity_resolution_time: str | None = None
    liquidity_resolution_age_seconds: float | None = None
    liquidity_resolution_freshness_status: str = "UNKNOWN"
    liquidity_resolution_rule_version: int = _LIQUIDITY_RESOLUTION_RULE_VERSION
    # Hard invariant — H1 never authorises execution.
    valid_for_execution: bool = False
    is_final_signal: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": EVENT_NAME,
            "schema_version": SCHEMA_VERSION,
            "symbol": self.symbol,
            "daily_bias": self.daily_bias,
            "h4_structure": self.h4_structure,
            "price_location": self.price_location,
            "liquidity_context": self.liquidity_context,
            "allowed_playbook": self.allowed_playbook,
            "blocked_playbook": list(self.blocked_playbook),
            "data_sufficient": self.data_sufficient,
            "daily_bars": self.daily_bars,
            "h4_bars": self.h4_bars,
            "h4_swing_high": self.h4_swing_high,
            "h4_swing_low": self.h4_swing_low,
            "h4_atr": self.h4_atr,
            "daily_atr": self.daily_atr,
            "daily_range_high": self.daily_range_high,
            "daily_range_low": self.daily_range_low,
            "h4_supply_zone": self.h4_supply_zone,
            "h4_demand_zone": self.h4_demand_zone,
            "daily_fib_zone": self.daily_fib_zone,
            "daily_fib_levels": self.daily_fib_levels,
            "daily_bias_unstaled": self.daily_bias_unstaled,
            "daily_bias_source": self.daily_bias_source,
            "daily_bias_source_candle": self.daily_bias_source_candle,
            "daily_bias_snapshot_time": self.daily_bias_snapshot_time,
            "daily_bias_age_seconds": self.daily_bias_age_seconds,
            "daily_bias_freshness_status": self.daily_bias_freshness_status,
            "daily_bias_freshness_basis": self.daily_bias_freshness_basis,
            "daily_bias_source_period_open": self.daily_bias_source_period_open,
            "daily_bias_source_period_close": self.daily_bias_source_period_close,
            "daily_bias_latest_expected_period_open": self.daily_bias_latest_expected_period_open,
            "daily_bias_latest_expected_period_close": self.daily_bias_latest_expected_period_close,
            "daily_bias_missed_expected_closed_bars": self.daily_bias_missed_expected_closed_bars,
            "daily_bias_provider_timestamp_semantics": self.daily_bias_provider_timestamp_semantics,
            "daily_bias_max_age_seconds": self.daily_bias_max_age_seconds,
            "daily_bias_rule_version": self.daily_bias_rule_version,
            "daily_bias_advisory_only": self.daily_bias_advisory_only,
            "daily_bias_execution_impact": self.daily_bias_execution_impact,
            "daily_bias_execution_block_reason": self.daily_bias_execution_block_reason,
            "location_reference_price": self.location_reference_price,
            "location_reference_time": self.location_reference_time,
            "location_reference_source": self.location_reference_source,
            "location_reference_age_seconds": self.location_reference_age_seconds,
            "location_ratio": self.location_ratio,
            "dealing_range_source": self.dealing_range_source,
            "distance_to_range_high_pips": self.distance_to_range_high_pips,
            "distance_to_range_low_pips": self.distance_to_range_low_pips,
            "liquidity_resolution": self.liquidity_resolution,
            "liquidity_resolution_time": self.liquidity_resolution_time,
            "liquidity_resolution_age_seconds": self.liquidity_resolution_age_seconds,
            "liquidity_resolution_freshness_status": self.liquidity_resolution_freshness_status,
            "liquidity_resolution_rule_version": self.liquidity_resolution_rule_version,
            "reason": self.reason,
            # Safety lock — emitted explicitly so consumers can never misread it.
            "valid_for_execution": False,
            "is_final_signal": False,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def dedupe_key(self) -> tuple[Any, ...]:
        """Stable identity for per-symbol emit deduplication."""
        return (
            self.symbol,
            self.daily_bias,
            self.h4_structure,
            self.price_location,
            self.liquidity_context,
            self.allowed_playbook,
            tuple(self.blocked_playbook),
            self.h4_swing_high,
            self.h4_swing_low,
            self.h4_atr,
            self.daily_atr,
            self.daily_range_high,
            self.daily_range_low,
            self.daily_bias_source_candle,
            self.daily_bias_freshness_status,
            self.daily_bias_source_period_close,
            self.daily_bias_latest_expected_period_close,
            self.daily_bias_missed_expected_closed_bars,
            self.location_reference_price,
            self.location_reference_time,
            self.liquidity_resolution,
            self.liquidity_resolution_time,
        )


# ═══════════════════════════════════════════════════════════════════════════
# §3  RESOLVER (candle I/O via an injectable LiveContextBus-compatible source)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class HTFStructureSnapshotResolver:
    """Read Daily + H4 candles and produce a non-executable structure snapshot.

    ``candle_source`` is any object exposing
    ``get_candle_history(symbol, timeframe, count) -> list[dict]`` — i.e. the
    same contract as :class:`context.live_context_bus.LiveContextBus`.  Left as
    ``None`` it lazily binds the singleton bus (mirroring ``L2MTAAnalyzer``).
    """

    candle_source: Any = None
    swing_window: int = _SWING_WINDOW
    daily_lookback: int = _DAILY_LOOKBACK
    h4_lookback: int = _H4_LOOKBACK
    daily_bias_max_age_seconds: float | None = None
    liquidity_max_age_seconds: float | None = None

    def _bind_source(self) -> Any:
        if self.candle_source is not None:
            return self.candle_source
        try:
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415

            self.candle_source = LiveContextBus()
        except Exception:  # pragma: no cover - defensive
            self.candle_source = None
        return self.candle_source

    def _history(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        source = self._bind_source()
        if source is None:
            return []
        try:
            history = source.get_candle_history(symbol, timeframe, count)
        except TypeError:
            # Source without a ``count`` kwarg — fall back to full history.
            try:
                history = source.get_candle_history(symbol, timeframe)
            except Exception:
                return []
        except Exception:
            return []
        return list(history) if isinstance(history, (list, tuple)) else []

    def resolve(self, symbol: str) -> HTFStructureSnapshot:
        """Produce the HTF structure snapshot for ``symbol`` (never executable)."""
        sym = str(symbol or "").upper()
        daily = self._history(sym, "D1", self.daily_lookback)
        h4 = self._history(sym, "H4", self.h4_lookback)
        return build_snapshot(
            sym,
            daily,
            h4,
            swing_window=self.swing_window,
            daily_bias_max_age_seconds=self.daily_bias_max_age_seconds,
            liquidity_max_age_seconds=self.liquidity_max_age_seconds,
        )


def build_snapshot(
    symbol: str,
    daily: list[dict[str, Any]],
    h4: list[dict[str, Any]],
    *,
    swing_window: int = _SWING_WINDOW,
    now: datetime | None = None,
    daily_bias_max_age_seconds: float | None = None,
    liquidity_max_age_seconds: float | None = None,
) -> HTFStructureSnapshot:
    """Pure snapshot builder over already-fetched Daily + H4 candle lists."""
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    daily_closed = _closed_candles(daily)
    h4_closed = _closed_candles(h4)
    daily_bars = len(daily_closed)
    h4_bars = len(h4_closed)
    daily_max_age = (
        _env_max_age("HTF_DAILY_BIAS_MAX_AGE_SECONDS", _DEFAULT_DAILY_BIAS_MAX_AGE_SECONDS)
        if daily_bias_max_age_seconds is None
        else max(0.0, float(daily_bias_max_age_seconds))
    )
    liquidity_max_age = (
        _env_max_age("HTF_LIQUIDITY_RESOLUTION_MAX_AGE_SECONDS", _DEFAULT_LIQUIDITY_MAX_AGE_SECONDS)
        if liquidity_max_age_seconds is None
        else max(0.0, float(liquidity_max_age_seconds))
    )
    snapshot_time = now_utc.isoformat()
    daily_source_candle = daily_closed[-1] if daily_closed else None
    daily_source_time = _candle_source_time(daily_source_candle)
    daily_age = None if daily_source_candle is None else candle_age_seconds(daily_source_candle, now_utc)
    daily_freshness_evidence = _daily_freshness_evidence(
        daily_source_candle,
        now=now_utc,
        fallback_age_seconds=daily_age,
        fallback_max_age_seconds=daily_max_age,
    )
    daily_freshness = daily_freshness_evidence.status

    daily_ok = daily_bars >= _MIN_DAILY_BARS
    h4_ok = h4_bars >= _MIN_H4_BARS
    data_sufficient = daily_ok and h4_ok

    if not daily_ok:
        # Without a Daily map there is no structural authority at all.
        return HTFStructureSnapshot(
            symbol=symbol,
            daily_bias=BIAS_NO_BIAS,
            h4_structure=H4_NO_STRUCTURE,
            price_location=LOC_UNKNOWN,
            liquidity_context=LIQ_NONE,
            allowed_playbook="NONE",
            blocked_playbook=["BUY_LIMIT", "SELL_LIMIT", "BUY_BREAKOUT_CHASE", "SELL_BREAKOUT_CHASE"],
            data_sufficient=False,
            reason=f"insufficient_daily_bars:{daily_bars}<{_MIN_DAILY_BARS}",
            daily_bars=daily_bars,
            h4_bars=h4_bars,
            daily_bias_unstaled=BIAS_NO_BIAS,
            daily_bias_source_candle=daily_source_time,
            daily_bias_snapshot_time=snapshot_time,
            daily_bias_age_seconds=None if daily_age is None else round(daily_age, 3),
            daily_bias_freshness_status=daily_freshness,
            daily_bias_freshness_basis=daily_freshness_evidence.basis,
            daily_bias_source_period_open=daily_freshness_evidence.source_period_open,
            daily_bias_source_period_close=daily_freshness_evidence.source_period_close,
            daily_bias_latest_expected_period_open=daily_freshness_evidence.latest_expected_period_open,
            daily_bias_latest_expected_period_close=daily_freshness_evidence.latest_expected_period_close,
            daily_bias_missed_expected_closed_bars=daily_freshness_evidence.missed_expected_closed_bars,
            daily_bias_provider_timestamp_semantics=daily_freshness_evidence.provider_timestamp_semantics,
            daily_bias_max_age_seconds=daily_max_age,
        )

    daily_highs = find_swing_highs(daily_closed, swing_window)
    daily_lows = find_swing_lows(daily_closed, swing_window)
    daily_close = _candle_close(daily_closed[-1])

    daily_bias_unstaled = classify_daily_bias_v2(daily_closed, swing_window)
    if daily_bias_unstaled in (BIAS_BULLISH, BIAS_BEARISH) and _detect_choch(
        daily_bias_unstaled, daily_close, daily_highs, daily_lows
    ):
        daily_bias_unstaled = BIAS_TRANSITION
    daily_bias = BIAS_STALE if daily_freshness == "STALE" else daily_bias_unstaled

    h4_structure = classify_h4_structure(h4_closed, swing_window) if h4_ok else H4_NO_STRUCTURE

    d_range = dealing_range(daily_closed, _RANGE_LOOKBACK_DAILY)
    h4_highs = find_swing_highs(h4_closed, swing_window) if h4_ok else []
    h4_lows = find_swing_lows(h4_closed, swing_window) if h4_ok else []
    h4_swing_high = h4_highs[-1].price if h4_highs else None
    h4_swing_low = h4_lows[-1].price if h4_lows else None
    daily_range_high = d_range[0] if d_range else None
    daily_range_low = d_range[1] if d_range else None

    location_candle = h4_closed[-1] if h4_ok else daily_closed[-1]
    location_price = _candle_close(location_candle)
    location_time = _candle_source_time(location_candle)
    location_age = candle_age_seconds(location_candle, now_utc)
    location_source = "H4_CLOSED_CANDLE" if h4_ok else "D1_CLOSED_CANDLE"
    price_location = classify_price_location(location_price, d_range, h4_swing_high, h4_swing_low)
    location_ratio_value = (
        None if location_price is None or d_range is None else round(location_pct(location_price, *d_range), 6)
    )

    liquidity_resolution = classify_liquidity_resolution(
        location_candle,
        d_range,
        atr=_average_true_range(h4_closed),
    )
    liquidity_freshness = _freshness_status(location_age, liquidity_max_age)
    if liquidity_freshness == "STALE":
        if liquidity_resolution.startswith("BUY_SIDE_"):
            liquidity_resolution = LIQ_BUY_EXPIRED
        elif liquidity_resolution.startswith("SELL_SIDE_"):
            liquidity_resolution = LIQ_SELL_EXPIRED
    liquidity_context = _liquidity_context_from_resolution(liquidity_resolution)
    allowed, blocked = resolve_playbook(daily_bias, price_location)

    if daily_freshness == "STALE":
        reason = "daily_bias_stale_execution_block"
    else:
        reason = "htf_structure_snapshot" if data_sufficient else f"degraded_h4_bars:{h4_bars}<{_MIN_H4_BARS}"

    return HTFStructureSnapshot(
        symbol=symbol,
        daily_bias=daily_bias,
        h4_structure=h4_structure,
        price_location=price_location,
        liquidity_context=liquidity_context,
        allowed_playbook=allowed,
        blocked_playbook=blocked,
        data_sufficient=data_sufficient,
        reason=reason,
        daily_bars=daily_bars,
        h4_bars=h4_bars,
        h4_swing_high=h4_swing_high,
        h4_swing_low=h4_swing_low,
        h4_atr=_average_true_range(h4_closed),
        daily_atr=_average_true_range(daily_closed),
        daily_range_high=daily_range_high,
        daily_range_low=daily_range_low,
        h4_supply_zone=_h4_supply_zone(h4_swing_high, d_range),
        h4_demand_zone=_h4_demand_zone(h4_swing_low, d_range),
        daily_fib_zone=_daily_fib_zone(d_range),
        daily_fib_levels=_daily_fib_levels(d_range),
        daily_bias_unstaled=daily_bias_unstaled,
        daily_bias_source_candle=daily_source_time,
        daily_bias_snapshot_time=snapshot_time,
        daily_bias_age_seconds=None if daily_age is None else round(daily_age, 3),
        daily_bias_freshness_status=daily_freshness,
        daily_bias_freshness_basis=daily_freshness_evidence.basis,
        daily_bias_source_period_open=daily_freshness_evidence.source_period_open,
        daily_bias_source_period_close=daily_freshness_evidence.source_period_close,
        daily_bias_latest_expected_period_open=daily_freshness_evidence.latest_expected_period_open,
        daily_bias_latest_expected_period_close=daily_freshness_evidence.latest_expected_period_close,
        daily_bias_missed_expected_closed_bars=daily_freshness_evidence.missed_expected_closed_bars,
        daily_bias_provider_timestamp_semantics=daily_freshness_evidence.provider_timestamp_semantics,
        daily_bias_max_age_seconds=daily_max_age,
        daily_bias_execution_block_reason="DAILY_CONTEXT_STALE" if daily_freshness == "STALE" else None,
        location_reference_price=location_price,
        location_reference_time=location_time,
        location_reference_source=location_source,
        location_reference_age_seconds=None if location_age is None else round(location_age, 3),
        location_ratio=location_ratio_value,
        dealing_range_source=f"D1_{_RANGE_LOOKBACK_DAILY}D_CLOSED",
        distance_to_range_high_pips=_distance_pips(
            location_price,
            daily_range_high,
            symbol,
        ),
        distance_to_range_low_pips=_distance_pips(
            location_price,
            daily_range_low,
            symbol,
        ),
        liquidity_resolution=liquidity_resolution,
        liquidity_resolution_time=location_time,
        liquidity_resolution_age_seconds=None if location_age is None else round(location_age, 3),
        liquidity_resolution_freshness_status=liquidity_freshness,
    )


# ═══════════════════════════════════════════════════════════════════════════
# §4  BUILD + EMIT (flag-guarded, default OFF)
# ═══════════════════════════════════════════════════════════════════════════


def build_htf_structure_snapshot_event(snapshot: HTFStructureSnapshot | dict[str, Any]) -> dict[str, Any]:
    """Return the canonical event dict for a snapshot (idempotent on dicts)."""
    if isinstance(snapshot, HTFStructureSnapshot):
        return snapshot.to_dict()
    payload = dict(snapshot)
    payload.setdefault("event", EVENT_NAME)
    payload["schema_version"] = SCHEMA_VERSION
    # Re-assert the safety lock even if a caller handed us a loose dict.
    payload["valid_for_execution"] = False
    payload["is_final_signal"] = False
    return payload


def _flag_enabled() -> bool:
    return os.getenv(ENABLE_ENV, "true").strip().lower() == "true"


def emit_htf_structure_snapshot(
    snapshot: HTFStructureSnapshot | dict[str, Any] | None,
    *,
    enabled: bool | None = None,
    use_logger: bool = True,
) -> bool:
    """Emit the snapshot as a compact JSON log line — only when enabled.

    Default ON (env ``HTF_STRUCTURE_SNAPSHOT_ENABLED``).  Pass ``enabled``
    explicitly to override the env flag (used by tests / canary harnesses).

    Returns ``True`` if a line was emitted, ``False`` otherwise.  Never raises
    on a bad payload and never carries execution authority.
    """
    if snapshot is None:
        return False
    if enabled is None:
        enabled = _flag_enabled()
    if not enabled:
        return False

    payload = build_htf_structure_snapshot_event(snapshot)
    line = f"{LOG_PREFIX} {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}"
    if use_logger:
        logging.getLogger("signal_json").warning(line)
    else:  # pragma: no cover - stdout path mirrors microboost_event_log
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    return True


def resolve_htf_structure_snapshot(symbol: str, *, candle_source: Any = None) -> dict[str, Any]:
    """Convenience one-shot: resolve + return the event dict (non-executable)."""
    resolver = HTFStructureSnapshotResolver(candle_source=candle_source)
    return resolver.resolve(symbol).to_dict()
