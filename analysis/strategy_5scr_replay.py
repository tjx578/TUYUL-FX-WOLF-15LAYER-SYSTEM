"""Frozen historical replay boundary for Strategy 5S-CR.

Evidence and outcome reads are intentionally separate.  The evidence provider
can only see candles closed at the decision cutoff; later candles are exposed
only through ``load_outcome_candles`` after the decision has been frozen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from analysis.strategy_5scr_closed_candle_provider import (
    Strategy5SCRClosedCandleEvidenceProvider,
)
from analysis.strategy_5scr_m1_outcome import classify_strategy_5scr_m1_outcome
from contracts.canonical_candle import CanonicalCandle, as_utc
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence, Strategy5SCRTradePlan
from contracts.strategy_5scr_replay import Strategy5SCRM1Outcome


class FrozenClosedCandleStore:
    """In-memory immutable store used by deterministic replay tests/tools."""

    def __init__(self, candles: Iterable[CanonicalCandle]) -> None:
        self._candles = tuple(sorted(candles, key=lambda candle: (candle.symbol, candle.timeframe, candle.open_time)))

    async def load_closed_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        as_of_utc: datetime,
        limit: int,
    ) -> Sequence[CanonicalCandle]:
        cutoff = as_utc(as_of_utc, "as_of_utc")
        selected = [
            candle
            for candle in self._candles
            if candle.symbol == symbol.upper()
            and candle.timeframe == timeframe.upper()
            and candle.is_authoritative_closed_as_of(cutoff)
        ]
        return tuple(selected[-max(1, int(limit)) :])

    def load_outcome_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        after_utc: datetime,
        until_utc: datetime | None = None,
    ) -> tuple[CanonicalCandle, ...]:
        after = as_utc(after_utc, "after_utc")
        until = as_utc(until_utc, "until_utc") if until_utc is not None else None
        return tuple(
            candle
            for candle in self._candles
            if candle.symbol == symbol.upper()
            and candle.timeframe == timeframe.upper()
            and candle.complete
            and candle.provider_timestamp_semantics != "UNSPECIFIED"
            and candle.open_time >= after
            and (until is None or candle.close_time <= until)
        )


class Strategy5SCRReplay:
    """Build replay evidence first, then expose post-decision outcomes."""

    def __init__(self, candles: Iterable[CanonicalCandle]) -> None:
        self._store = FrozenClosedCandleStore(candles)
        self._provider = Strategy5SCRClosedCandleEvidenceProvider(
            self._store,
            mode="REPLAY",
        )

    async def build_evidence(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
    ) -> Strategy5SCRMarketEvidence | None:
        return await self._provider.provide(
            symbol=symbol,
            decision_at_utc=decision_at_utc,
        )

    def load_outcome_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        decision_at_utc: datetime,
        until_utc: datetime | None = None,
    ) -> tuple[CanonicalCandle, ...]:
        return self._store.load_outcome_candles(
            symbol=symbol,
            timeframe=timeframe,
            after_utc=decision_at_utc,
            until_utc=until_utc,
        )

    def classify_m1_outcome(
        self,
        *,
        tradeplan: Strategy5SCRTradePlan,
        until_utc: datetime | None = None,
        max_bars: int = 240,
    ) -> Strategy5SCRM1Outcome:
        """Evaluate post-decision M1 bars without reopening frozen evidence."""

        candles = self.load_outcome_candles(
            symbol=tradeplan.symbol,
            timeframe="M1",
            decision_at_utc=tradeplan.decision_at_utc,
            until_utc=until_utc,
        )
        return classify_strategy_5scr_m1_outcome(
            tradeplan,
            candles,
            until_utc=until_utc,
            max_bars=max_bars,
        )


__all__ = [
    "FrozenClosedCandleStore",
    "Strategy5SCRReplay",
]
