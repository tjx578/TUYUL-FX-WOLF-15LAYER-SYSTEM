"""In-memory observability accounting for SignalPressureStateJSON.

The tracker explains why pressure-state logs are sparse without changing the
pressure router, Watch promotion, or execution eligibility.  It keeps a small
rolling summary and cumulative per-symbol emit/suppression counters.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any


class PressureStateSummaryTracker:
    """Track pressure-state attempts, emits, and suppressions in memory."""

    def __init__(self, *, now: float | None = None) -> None:
        self._symbol_totals: dict[str, Counter[str]] = {}
        self._reset_window(time.time() if now is None else float(now))

    def record(
        self,
        payload: dict[str, Any],
        *,
        emitted: bool,
        suppression_reason: str | None = None,
    ) -> dict[str, int]:
        symbol = str(payload.get("symbol") or "*").upper()
        source_stage = str(payload.get("source_stage") or "UNKNOWN").upper()
        reason = str(suppression_reason or "UNSPECIFIED").upper()

        self._attempted += 1
        self._active_symbols.add(symbol)
        self._by_source_stage[source_stage] += 1
        if emitted:
            self._emitted += 1
        else:
            self._suppressed += 1
            self._by_suppression_reason[reason] += 1

        totals = self._symbol_totals.setdefault(symbol, Counter())
        totals["pressure_state_attempted"] += 1
        if emitted:
            totals["pressure_state_emitted"] += 1
        else:
            totals["pressure_state_suppressed"] += 1

        self._update_top_pressure(symbol, payload)
        return self.symbol_totals(symbol)

    def symbol_totals(self, symbol: str) -> dict[str, int]:
        totals = self._symbol_totals.get(str(symbol or "*").upper(), Counter())
        return {
            "pressure_state_attempted": int(totals.get("pressure_state_attempted", 0)),
            "pressure_state_emitted": int(totals.get("pressure_state_emitted", 0)),
            "pressure_state_suppressed": int(totals.get("pressure_state_suppressed", 0)),
        }

    def roll_if_due(
        self,
        *,
        interval_seconds: float,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        current = time.time() if now is None else float(now)
        interval = max(1.0, float(interval_seconds))
        if self._attempted <= 0 or current - self._window_started_at < interval:
            return None

        payload = {
            "event": "signal_pressure_state_summary",
            "window_start_utc": _utc_iso(self._window_started_at),
            "window_end_utc": _utc_iso(current),
            "window_seconds": round(max(0.0, current - self._window_started_at), 3),
            "attempted": self._attempted,
            "emitted": self._emitted,
            "suppressed": self._suppressed,
            "active_symbols": len(self._active_symbols),
            "active_symbol_list": sorted(self._active_symbols),
            "by_source_stage": dict(self._by_source_stage.most_common()),
            "by_suppression_reason": dict(self._by_suppression_reason.most_common()),
            "top_pressure": sorted(
                self._top_pressure.values(),
                key=_top_pressure_rank,
                reverse=True,
            )[:8],
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "final_direction": "WAIT",
            "eligible_for_signal_decision": False,
        }
        self._reset_window(current)
        return payload

    def _reset_window(self, now: float) -> None:
        self._window_started_at = float(now)
        self._attempted = 0
        self._emitted = 0
        self._suppressed = 0
        self._active_symbols: set[str] = set()
        self._by_source_stage: Counter[str] = Counter()
        self._by_suppression_reason: Counter[str] = Counter()
        self._top_pressure: dict[str, dict[str, Any]] = {}

    def _update_top_pressure(self, symbol: str, payload: dict[str, Any]) -> None:
        candidate = {
            "symbol": symbol,
            "direction": payload.get("raw_direction") or payload.get("candidate_direction"),
            "source_stage": payload.get("source_stage"),
            "source_family": payload.get("source_family") or payload.get("signal_family"),
            "events": _number(
                payload.get("session_symbol_event_count")
                or payload.get("current_snapshot_events")
                or payload.get("pressure_event_count")
            ),
            "block_events": _number(payload.get("block_event_count") or payload.get("current_block_events")),
            "effective_ticks": _number(
                payload.get("block_effective_ticks") or payload.get("current_block_effective_ticks")
            ),
            "duration_seconds": _number(payload.get("block_duration_seconds")),
            "density_per_minute": _number(payload.get("block_density")),
        }
        previous = self._top_pressure.get(symbol)
        if previous is None or _top_pressure_rank(candidate) >= _top_pressure_rank(previous):
            self._top_pressure[symbol] = candidate


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 3)


def _top_pressure_rank(payload: dict[str, Any]) -> tuple[float, float, float]:
    return (
        float(payload.get("events") or 0.0),
        float(payload.get("effective_ticks") or 0.0),
        float(payload.get("duration_seconds") or 0.0),
    )


def _utc_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(float(epoch_seconds), UTC).isoformat()


__all__ = ["PressureStateSummaryTracker"]
