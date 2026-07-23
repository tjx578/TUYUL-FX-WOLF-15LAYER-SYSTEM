"""Deterministic M1 outcome classifier for frozen 5S-CR tradeplans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import cast

from contracts.canonical_candle import CanonicalCandle, as_utc
from contracts.strategy_5scr_pressure import Strategy5SCRTradePlan
from contracts.strategy_5scr_replay import Strategy5SCRM1Outcome, Strategy5SCROutcomeStatus

CLASSIFIER_VERSION = "5scr.m1-outcome.v1"


def tradeplan_from_candidate_payload(
    payload: Mapping[str, object],
) -> Strategy5SCRTradePlan:
    """Rebuild the typed immutable plan stored inside a candidate payload."""

    preview = payload.get("tradeplan_preview")
    proof = payload.get("strategy_5scr")
    if not isinstance(preview, Mapping) or not isinstance(proof, Mapping):
        raise ValueError("5S-CR candidate is missing tradeplan_preview or strategy_5scr proof")
    return cast(
        Strategy5SCRTradePlan,
        Strategy5SCRTradePlan.model_validate(
            {
                **dict(preview),
                "proof": dict(proof),
            }
        ),
    )


def _canonical_outcome_candles(
    tradeplan: Strategy5SCRTradePlan,
    candles: Iterable[CanonicalCandle],
    *,
    until_utc: datetime | None,
    max_bars: int,
) -> tuple[CanonicalCandle, ...]:
    until = as_utc(until_utc, "until_utc") if until_utc is not None else None
    selected = sorted(
        (
            candle
            for candle in candles
            if candle.symbol == tradeplan.symbol
            and candle.timeframe == "M1"
            and candle.complete
            and candle.provider_timestamp_semantics != "UNSPECIFIED"
            # Never use a candle containing any price action before the decision.
            and candle.open_time >= tradeplan.decision_at_utc
            and (until is None or candle.close_time <= until)
        ),
        key=lambda candle: (candle.open_time, candle.close_time, candle.provider),
    )
    by_window: dict[tuple[datetime, datetime], CanonicalCandle] = {}
    for candle in selected:
        window = (candle.open_time, candle.close_time)
        existing = by_window.get(window)
        if existing is not None:
            existing_ohlc = (existing.open, existing.high, existing.low, existing.close)
            candle_ohlc = (candle.open, candle.high, candle.low, candle.close)
            if candle_ohlc != existing_ohlc:
                raise ValueError(f"conflicting canonical M1 candles for window {window!r}")
            continue
        by_window[window] = candle
    return tuple(by_window.values())[:max_bars]


def _touches(
    tradeplan: Strategy5SCRTradePlan,
    candle: CanonicalCandle,
) -> tuple[bool, bool]:
    if tradeplan.direction == "BUY":
        return candle.high >= tradeplan.tp1, candle.low <= tradeplan.stop_loss
    return candle.low <= tradeplan.tp1, candle.high >= tradeplan.stop_loss


def _outcome_id(
    tradeplan: Strategy5SCRTradePlan,
    status: Strategy5SCROutcomeStatus,
    candles: tuple[CanonicalCandle, ...],
    until_utc: datetime | None,
) -> str:
    identity = {
        "classifier_version": CLASSIFIER_VERSION,
        "tradeplan_id": tradeplan.tradeplan_id,
        "status": status,
        "until_utc": until_utc.isoformat() if until_utc is not None else None,
        "candles": [
            {
                "open_time": candle.open_time.isoformat(),
                "close_time": candle.close_time.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            }
            for candle in candles
        ],
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"5scr-outcome:{digest[:32]}"


def classify_strategy_5scr_m1_outcome(
    tradeplan: Strategy5SCRTradePlan,
    candles: Iterable[CanonicalCandle],
    *,
    until_utc: datetime | None = None,
    max_bars: int = 240,
) -> Strategy5SCRM1Outcome:
    """Classify which terminal level was touched first after decision freeze.

    OHLC cannot reveal intrabar order.  A bar touching both levels is therefore
    explicitly ambiguous.  If no level is touched, the supplied replay horizon
    ends as ``TIMEOUT``; an empty legal horizon is ``NO_DATA``.
    """

    if max_bars < 1:
        raise ValueError("max_bars must be positive")
    until = as_utc(until_utc, "until_utc") if until_utc is not None else None
    if until is not None and until <= tradeplan.decision_at_utc:
        raise ValueError("until_utc must follow tradeplan decision_at_utc")
    legal = _canonical_outcome_candles(
        tradeplan,
        candles,
        until_utc=until,
        max_bars=max_bars,
    )
    status: Strategy5SCROutcomeStatus = "NO_DATA" if not legal else "TIMEOUT"
    terminal_candle: CanonicalCandle | None = None
    evaluated: tuple[CanonicalCandle, ...] = legal
    for index, candle in enumerate(legal):
        tp1_touched, stop_touched = _touches(tradeplan, candle)
        if tp1_touched and stop_touched:
            status = "AMBIGUOUS_SAME_CANDLE"
        elif tp1_touched:
            status = "TP1_FIRST"
        elif stop_touched:
            status = "SL_FIRST"
        else:
            continue
        terminal_candle = candle
        evaluated = legal[: index + 1]
        break

    realized_r: float | None = None
    if status == "TP1_FIRST":
        realized_r = abs(tradeplan.tp1 - tradeplan.entry) / abs(tradeplan.entry - tradeplan.stop_loss)
    elif status == "SL_FIRST":
        realized_r = -1.0

    return Strategy5SCRM1Outcome(
        outcome_id=_outcome_id(tradeplan, status, evaluated, until),
        tradeplan_id=tradeplan.tradeplan_id,
        symbol=tradeplan.symbol,
        direction=tradeplan.direction,
        decision_at_utc=tradeplan.decision_at_utc,
        evaluated_until_utc=until,
        entry=tradeplan.entry,
        stop_loss=tradeplan.stop_loss,
        tp1=tradeplan.tp1,
        status=status,
        realized_r=realized_r,
        bars_evaluated=len(evaluated),
        first_bar_open_utc=evaluated[0].open_time if evaluated else None,
        last_bar_close_utc=evaluated[-1].close_time if evaluated else None,
        terminal_candle=terminal_candle,
    )


__all__ = [
    "CLASSIFIER_VERSION",
    "classify_strategy_5scr_m1_outcome",
    "tradeplan_from_candidate_payload",
]
