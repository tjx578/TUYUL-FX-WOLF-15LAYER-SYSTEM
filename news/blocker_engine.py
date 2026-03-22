"""
BlockerEngine — determines whether trading is locked due to news.

Design
------
- Produces a rich ``BlockerStatus`` for consumers that need detail.
- Preserves a simple ``is_locked()`` boolean shortcut for the existing
  ``NewsEngine`` API.
- Tie-breaks by highest impact score first, then nearest event.
- Skips timeless events (``is_timeless=True``) — they never trigger
  time-based lock windows.
- Skips events with unparseable / missing ``datetime_utc`` safely.
- Scans an exact horizon overlap to surface *upcoming* blockers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from news.models import BlockerStatus, EconomicEvent, ImpactLevel
from news.news_rules import NEWS_RULES


def _rule_for(impact: ImpactLevel) -> dict:
    return NEWS_RULES.get(impact.value, NEWS_RULES["UNKNOWN"])


def _lock_window(event: EconomicEvent) -> tuple[datetime, datetime] | None:
    """
    Return the (start, end) UTC lock window for *event*, or None if
    the event does not lock or has no fixed time.
    """
    if event.is_timeless:
        return None

    if event.datetime_utc is None:
        return None

    rule = _rule_for(event.impact)
    if not rule["lock"]:
        return None

    start = event.datetime_utc - timedelta(minutes=rule["pre_minutes"])
    end = event.datetime_utc + timedelta(minutes=rule["post_minutes"])
    return start, end


class BlockerEngine:
    """
    Evaluates a collection of economic events to produce a ``BlockerStatus``.

    Parameters
    ----------
    lookahead_minutes : int
        How far ahead to scan for upcoming blocking events (default 90 min).
    """

    def __init__(self, lookahead_minutes: int = 90) -> None:
        self.lookahead_minutes = lookahead_minutes

    def evaluate(
        self,
        events: Sequence[EconomicEvent],
        symbol: str | None = None,
        now: datetime | None = None,
    ) -> BlockerStatus:
        """
        Evaluate events against the current time and return a ``BlockerStatus``.

        Parameters
        ----------
        events : Sequence[EconomicEvent]
            All known events for the relevant day(s).
        symbol : str | None
            If provided, only events whose ``affected_pairs`` include this
            symbol (or have an empty ``affected_pairs`` list) are considered.
        now : datetime | None
            Override for the current UTC time (useful in tests).

        Returns
        -------
        BlockerStatus
        """
        now = now or datetime.now(UTC)
        horizon = now + timedelta(minutes=self.lookahead_minutes)

        relevant = self._filter_relevant(events, symbol)

        locked_event: EconomicEvent | None = None
        upcoming: list[EconomicEvent] = []

        for event in relevant:
            window = _lock_window(event)
            if window is None:
                continue

            start, end = window

            # Active lock — event window covers right now
            if start <= now <= end:
                if locked_event is None or self._beats(event, locked_event, now):
                    locked_event = event

            # Upcoming — event window overlaps the lookahead horizon
            elif start <= horizon and end >= now:
                upcoming.append(event)

        # Sort upcoming: soonest first, then highest impact
        upcoming.sort(
            key=lambda e: (
                e.datetime_utc or datetime.max.replace(tzinfo=UTC),
                -_rule_for(e.impact)["pre_minutes"],  # higher impact → bigger window
            )
        )

        if locked_event is not None:
            rule = _rule_for(locked_event.impact)
            lock_reason = (
                f"{locked_event.impact.value} event '{locked_event.title}' "
                f"({locked_event.currency}) — lock window "
                f"{rule['pre_minutes']}m pre / {rule['post_minutes']}m post"
            )
            return BlockerStatus(
                is_locked=True,
                locked_by=locked_event,
                lock_reason=lock_reason,
                upcoming=upcoming,
                checked_at=now,
            )

        return BlockerStatus(
            is_locked=False,
            locked_by=None,
            lock_reason="",
            upcoming=upcoming,
            checked_at=now,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _filter_relevant(
        events: Sequence[EconomicEvent],
        symbol: str | None,
    ) -> list[EconomicEvent]:
        """Filter events to those relevant for *symbol*."""
        if symbol is None:
            return list(events)
        result = []
        for e in events:
            if not e.affected_pairs or symbol in e.affected_pairs:
                result.append(e)
        return result

    @staticmethod
    def _beats(challenger: EconomicEvent, champion: EconomicEvent, now: datetime) -> bool:
        """
        Return True if *challenger* should replace *champion* as the
        primary lock event.

        Tie-break rules (in order):
          1. Higher impact score wins.
          2. If equal impact, nearest event to ``now`` wins
             (smallest absolute time distance).
        """
        c_score = challenger.impact_score
        x_score = champion.impact_score

        if c_score != x_score:
            return c_score > x_score

        # Equal impact → prefer the event nearest to now (smallest |dt - now|)
        c_time = challenger.datetime_utc
        x_time = champion.datetime_utc
        if c_time is not None and x_time is not None:
            c_dist = abs((c_time - now).total_seconds())
            x_dist = abs((x_time - now).total_seconds())
            return c_dist < x_dist
        return False
