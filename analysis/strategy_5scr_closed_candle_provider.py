"""Provider-neutral closed-candle adapter for Strategy 5S-CR evidence.

The provider reads only a frozen candle store.  It never calls Finnhub, never
reads outcome candles, and never talks to an EA or broker.  The resulting
tradeplan evidence is therefore suitable only for SHADOW or REPLAY operation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Literal, Protocol

from contracts.canonical_candle import CanonicalCandle, as_utc
from contracts.strategy_5scr import (
    ContextResolution,
    H1Confirmation,
    H4StructuralTarget,
    M1ExecutionBox,
    M15Confirmation,
)
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence

EvidenceMode = Literal["SHADOW", "REPLAY"]

_LOOKBACKS = {
    "D1": 30,
    "H4": 60,
    "H1": 24,
    "M15": 48,
    "M1": 30,
}
_MINIMUM_BARS = {
    "D1": 3,
    "H4": 4,
    "H1": 2,
    "M15": 3,
    "M1": 3,
}


class ClosedCandleEvidenceError(RuntimeError):
    """Base error for fail-closed evidence construction."""


class FutureCandleLeakageError(ClosedCandleEvidenceError):
    """Raised when a store exposes a candle after the decision cutoff."""


class ClosedCandleStore(Protocol):
    """Read boundary implemented by PostgreSQL, Redis, or frozen replay data."""

    async def load_closed_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        as_of_utc: datetime,
        limit: int,
    ) -> Sequence[CanonicalCandle]: ...


def _pip_size(symbol: str) -> float:
    normalized = symbol.upper()
    if normalized.startswith("XAU"):
        return 0.01
    if normalized.endswith("JPY"):
        return 0.01
    return 0.0001


def _estimated_shadow_spread(symbol: str, pip_size: float) -> float:
    # This estimate is deliberately labelled non-broker authority in the
    # evidence contract.  It is only an execution-floor approximation.
    return 0.50 if symbol.upper().startswith("XAU") else pip_size


class Strategy5SCRClosedCandleEvidenceProvider:
    """Build deterministic 5S-CR evidence from candles closed at a cutoff."""

    def __init__(
        self,
        store: ClosedCandleStore,
        *,
        mode: EvidenceMode = "SHADOW",
        spread_estimator: Callable[[str, float], float] | None = None,
    ) -> None:
        self._store = store
        self._mode: EvidenceMode = mode
        self._spread_estimator = spread_estimator or _estimated_shadow_spread

    async def provide(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
        lifecycle_anchor_utc: datetime | None = None,
    ) -> Strategy5SCRMarketEvidence | None:
        cutoff = as_utc(decision_at_utc, "decision_at_utc")
        snapshot = await self._load_snapshot(symbol.upper(), cutoff)
        if any(len(snapshot[timeframe]) < minimum for timeframe, minimum in _MINIMUM_BARS.items()):
            return None
        return self.build_from_snapshot(
            symbol=symbol.upper(),
            decision_at_utc=cutoff,
            lifecycle_anchor_utc=lifecycle_anchor_utc,
            candles_by_timeframe=snapshot,
        )

    async def _load_snapshot(
        self,
        symbol: str,
        cutoff: datetime,
    ) -> dict[str, list[CanonicalCandle]]:
        timeframes = tuple(_LOOKBACKS)
        batches = await asyncio.gather(
            *(
                self._store.load_closed_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    as_of_utc=cutoff,
                    limit=_LOOKBACKS[timeframe],
                )
                for timeframe in timeframes
            )
        )
        snapshot: dict[str, list[CanonicalCandle]] = {}
        for timeframe, raw_batch in zip(timeframes, batches, strict=True):
            deduplicated: dict[datetime, CanonicalCandle] = {}
            for candle in raw_batch:
                if candle.symbol != symbol or candle.timeframe != timeframe:
                    raise ClosedCandleEvidenceError("CANDLE_STORE_SCOPE_MISMATCH")
                if candle.close_time > cutoff:
                    raise FutureCandleLeakageError("STRATEGY_5SCR_FUTURE_CANDLE_LEAKAGE")
                if not candle.is_authoritative_closed_as_of(cutoff):
                    continue
                deduplicated[candle.open_time] = candle
            snapshot[timeframe] = sorted(deduplicated.values(), key=lambda item: item.open_time)
        return snapshot

    def build_from_snapshot(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
        lifecycle_anchor_utc: datetime | None = None,
        candles_by_timeframe: Mapping[str, Sequence[CanonicalCandle]],
    ) -> Strategy5SCRMarketEvidence | None:
        cutoff = as_utc(decision_at_utc, "decision_at_utc")
        normalized: dict[str, list[CanonicalCandle]] = {}
        for timeframe, minimum in _MINIMUM_BARS.items():
            candles = sorted(candles_by_timeframe.get(timeframe, ()), key=lambda item: item.open_time)
            if len(candles) < minimum:
                return None
            for candle in candles:
                if candle.symbol != symbol or candle.timeframe != timeframe:
                    raise ClosedCandleEvidenceError("CANDLE_SNAPSHOT_SCOPE_MISMATCH")
                if candle.close_time > cutoff:
                    raise FutureCandleLeakageError("STRATEGY_5SCR_FUTURE_CANDLE_LEAKAGE")
                if not candle.is_authoritative_closed_as_of(cutoff):
                    raise ClosedCandleEvidenceError("CANDLE_SNAPSHOT_NOT_AUTHORITATIVE")
            normalized[timeframe] = candles

        d1 = normalized["D1"]
        h4 = normalized["H4"]
        h1 = normalized["H1"]
        m15 = normalized["M15"]
        m1 = normalized["M1"]
        anchor = (
            as_utc(lifecycle_anchor_utc, "lifecycle_anchor_utc")
            if lifecycle_anchor_utc is not None
            else m15[0].open_time
        )
        if anchor > cutoff:
            raise ClosedCandleEvidenceError("LIFECYCLE_ANCHOR_AFTER_DECISION")
        direction, h1_confirmed = self._h1_direction(h1)
        m15_confirmation = self._m15_confirmation(direction, m15, anchor)
        m15_ready = m15_confirmation.acceptance_confirmed or (
            m15_confirmation.structural_break and m15_confirmation.failed_reclaim_or_retest_confirmed
        )
        m1_box = self._m1_box(symbol, m1, after_utc=m15_confirmation.confirmed_at_utc) if m15_ready else None
        entry = m1_box.fill_price if m1_box is not None else m1[-1].close
        context = self._context(direction, entry, d1, h4)
        h4_target = self._h4_target(direction, entry, h4)
        h1_confirmation = H1Confirmation(
            direction=direction,
            structure_state=(
                f"{direction}_CLOSED_BREAK_CONFIRMED" if h1_confirmed else f"{direction}_CLOSED_DIRECTION_UNCONFIRMED"
            ),
            structure_confirmed=h1_confirmed,
            candle_closed=True,
            confirmed_at_utc=h1[-1].close_time,
        )
        structural_sl = self._structural_sl(direction, entry, h1, m15, m1)
        if h4_target is None or structural_sl is None:
            return None

        all_candles = [candle for timeframe in _LOOKBACKS for candle in normalized[timeframe]]
        close_times = tuple(sorted({candle.close_time for candle in all_candles}))
        snapshot_id = self._snapshot_id(
            symbol,
            cutoff,
            normalized,
            lifecycle_anchor_utc=anchor,
        )
        providers = "+".join(sorted({candle.provider for candle in all_candles}))
        pip_size = _pip_size(symbol)
        spread_price = max(0.0, float(self._spread_estimator(symbol, pip_size)))

        return Strategy5SCRMarketEvidence(
            decision_at_utc=cutoff,
            lifecycle_anchor_utc=anchor,
            evidence_mode=self._mode,
            evidence_snapshot_id=snapshot_id,
            market_data_provider=providers,
            execution_cost_authority="ESTIMATED_NOT_BROKER",
            context_resolution=context,
            h4=h4_target,
            h1=h1_confirmation,
            m15=m15_confirmation,
            m1=m1_box,
            structural_sl=structural_sl,
            pip_size=pip_size,
            spread_price=spread_price,
            source_candle_close_times=close_times,
            source_candle_count=len(all_candles),
            source_candles=tuple(all_candles),
        )

    @staticmethod
    def _h1_direction(candles: Sequence[CanonicalCandle]) -> tuple[Literal["BUY", "SELL"], bool]:
        previous, latest = candles[-2], candles[-1]
        if latest.close > previous.high:
            return "BUY", True
        if latest.close < previous.low:
            return "SELL", True
        direction: Literal["BUY", "SELL"] = "BUY" if latest.close >= previous.close else "SELL"
        return direction, False

    @staticmethod
    def _context(
        direction: Literal["BUY", "SELL"],
        entry: float,
        d1: Sequence[CanonicalCandle],
        h4: Sequence[CanonicalCandle],
    ) -> ContextResolution:
        daily_bias = "BULLISH" if d1[-1].close >= d1[0].close else "BEARISH"
        h4_structure = (
            "BULLISH_IMPULSE"
            if h4[-1].close > h4[-2].high
            else "BEARISH_IMPULSE"
            if h4[-1].close < h4[-2].low
            else "BULLISH_PULLBACK"
            if h4[-1].close >= h4[-2].close
            else "BEARISH_PULLBACK"
        )
        recent_high = max(candle.high for candle in h4[-12:])
        recent_low = min(candle.low for candle in h4[-12:])
        midpoint = (recent_high + recent_low) / 2
        price_location = "H4_PREMIUM" if entry > midpoint else "H4_DISCOUNT"
        aligned = (direction == "BUY" and daily_bias == "BULLISH") or (direction == "SELL" and daily_bias == "BEARISH")
        playbook = f"{direction}_ON_CONFIRMED_BREAK_RETEST"
        opposite = "SELL" if direction == "BUY" else "BUY"
        return ContextResolution(
            status="RESOLVED" if aligned else "WAIT_FOR_CONFIRMATION",
            origin="DIRECT_CONTEXT" if aligned else "WAIT_FOR_CONFIRMATION",
            price_location=price_location,
            liquidity_context=(
                "SELL_SIDE_LIQUIDITY_RECLAIMED" if direction == "BUY" else "BUY_SIDE_LIQUIDITY_REJECTED"
            ),
            daily_bias=daily_bias,
            h4_structure=h4_structure,
            allowed_playbook=playbook,
            selected_playbook=playbook,
            blocked_playbook=(f"{opposite}_BREAKOUT_CHASE",),
            scenario_allowed=True,
        )

    @staticmethod
    def _h4_target(
        direction: Literal["BUY", "SELL"],
        entry: float,
        candles: Sequence[CanonicalCandle],
    ) -> H4StructuralTarget | None:
        if direction == "BUY":
            candidates = sorted({candle.high for candle in candles[:-1] if candle.high > entry})
            target = candidates[0] if candidates else None
        else:
            candidates = sorted(
                {candle.low for candle in candles[:-1] if candle.low < entry},
                reverse=True,
            )
            target = candidates[0] if candidates else None
        if target is None:
            return None
        return H4StructuralTarget(
            target_mode="FINAL_MARKET_STRUCTURE",
            structural_tp1=target,
            target_room_valid=abs(target - entry) > 0,
        )

    @staticmethod
    def _m15_confirmation(
        direction: Literal["BUY", "SELL"],
        candles: Sequence[CanonicalCandle],
        lifecycle_anchor_utc: datetime,
    ) -> M15Confirmation:
        ordered = list(candles)
        first_eligible = next(
            (index for index, candle in enumerate(ordered) if candle.close_time > lifecycle_anchor_utc),
            len(ordered),
        )
        first_break: tuple[CanonicalCandle, float] | None = None
        for index in range(max(1, first_eligible), len(ordered)):
            previous, breakout = ordered[index - 1 : index + 1]
            if direction == "BUY":
                broke = breakout.close > previous.high
                level = previous.high
            else:
                broke = breakout.close < previous.low
                level = previous.low
            if not broke:
                continue
            first_break = (breakout, level)
            if index + 1 >= len(ordered):
                break
            confirmation = ordered[index + 1]
            if direction == "BUY":
                acceptance = confirmation.close > level
                retest = confirmation.low <= level and confirmation.close > level
            else:
                acceptance = confirmation.close < level
                retest = confirmation.high >= level and confirmation.close < level
            if acceptance or retest:
                return M15Confirmation(
                    direction=direction,
                    structural_break=True,
                    candle_closed=True,
                    acceptance_confirmed=acceptance,
                    failed_reclaim_or_retest_confirmed=retest,
                    rejection_candle_only=False,
                    confirmed_at_utc=confirmation.close_time,
                )
        if first_break is not None:
            breakout, _level = first_break
            return M15Confirmation(
                direction=direction,
                structural_break=True,
                candle_closed=True,
                acceptance_confirmed=False,
                failed_reclaim_or_retest_confirmed=False,
                rejection_candle_only=False,
                confirmed_at_utc=breakout.close_time,
            )
        latest = ordered[-1]
        return M15Confirmation(
            direction=direction,
            structural_break=False,
            candle_closed=True,
            acceptance_confirmed=False,
            failed_reclaim_or_retest_confirmed=False,
            rejection_candle_only=True,
            confirmed_at_utc=latest.close_time,
        )

    @staticmethod
    def _m1_box(
        symbol: str,
        candles: Sequence[CanonicalCandle],
        *,
        after_utc: datetime,
    ) -> M1ExecutionBox | None:
        eligible = [candle for candle in candles if candle.open_time >= after_utc]
        if len(eligible) < 3:
            return None
        window = eligible[:3]
        low = min(candle.low for candle in window)
        high = max(candle.high for candle in window)
        latest = window[-1]
        box_basis = f"{symbol}|{window[0].open_time.isoformat()}|{latest.close_time.isoformat()}"
        box_id = f"{symbol}:m1:{hashlib.sha256(box_basis.encode()).hexdigest()[:16]}"
        return M1ExecutionBox(
            box_id=box_id,
            box_low=low,
            box_high=high,
            fill_price=latest.close,
            return_to_box_invalidated=False,
            formed_at_utc=latest.close_time,
        )

    @staticmethod
    def _structural_sl(
        direction: Literal["BUY", "SELL"],
        entry: float,
        h1: Sequence[CanonicalCandle],
        m15: Sequence[CanonicalCandle],
        m1: Sequence[CanonicalCandle],
    ) -> float | None:
        structure = [*h1[-2:], *m15[-4:], *m1[-5:]]
        if direction == "BUY":
            candidates = [candle.low for candle in structure if candle.low < entry]
            return min(candidates) if candidates else None
        candidates = [candle.high for candle in structure if candle.high > entry]
        return max(candidates) if candidates else None

    @staticmethod
    def _snapshot_id(
        symbol: str,
        cutoff: datetime,
        snapshot: Mapping[str, Sequence[CanonicalCandle]],
        lifecycle_anchor_utc: datetime | None = None,
    ) -> str:
        payload = {
            "symbol": symbol,
            "decision_at_utc": cutoff.isoformat(),
            "lifecycle_anchor_utc": (lifecycle_anchor_utc.isoformat() if lifecycle_anchor_utc is not None else None),
            "candles": {
                timeframe: [
                    (
                        candle.open_time.isoformat(),
                        candle.close_time.isoformat(),
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.provider,
                    )
                    for candle in candles
                ]
                for timeframe, candles in sorted(snapshot.items())
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"5scr-evidence:{hashlib.sha256(encoded).hexdigest()[:32]}"


__all__ = [
    "ClosedCandleEvidenceError",
    "ClosedCandleStore",
    "EvidenceMode",
    "FutureCandleLeakageError",
    "Strategy5SCRClosedCandleEvidenceProvider",
]
