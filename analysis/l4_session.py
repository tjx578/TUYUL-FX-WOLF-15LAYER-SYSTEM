"""
🕐 L4 — Session & Timing Layer (PRODUCTION)
----------------------------------------------
Provides session context, timing gates, and event awareness.

Responsibilities:
  - Identify active trading session (with overlap detection)
  - Session quality scoring
  - Weekend / off-hours gating
  - High-impact news event buffer zones
  - Friday-close and Sunday-open degradation

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

import logging

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)

__all__ = ["analyze_session"]

# ── Session Definitions ─────────────────────────────────────────────
# Ordered by priority: overlaps first, then single sessions.
# (start_hour_utc, end_hour_utc, base_quality)
_SESSIONS: list[tuple[str, int, int, float]] = [
    ("LONDON_NEWYORK", 13, 16, 1.00),
    ("TOKYO_LONDON",    7,  9, 0.85),
    ("LONDON",          9, 13, 0.90),
    ("NEWYORK",        16, 22, 0.85),
    ("TOKYO",           1,  7, 0.60),
    # SYDNEY is the fallback (22–1 UTC)
]
_SYDNEY_QUALITY = 0.40

# ── Quality Modifiers ───────────────────────────────────────────────
_WEEKEND_QUALITY = 0.0
_FRIDAY_CLOSE_MULT = 0.30
_FRIDAY_CLOSE_START_HOUR = 21
_SUNDAY_OPEN_MULT = 0.50
_SUNDAY_OPEN_END_HOUR = 1
_OFF_HOURS_MULT = 0.50
_EVENT_BUFFER_MULT = 0.30

# ── Known Currencies ────────────────────────────────────────────────
_KNOWN_CURRENCIES = ("USD", "GBP", "EUR", "JPY", "AUD", "NZD", "CAD", "CHF")

# ── High Impact Events ──────────────────────────────────────────────
# day: weekday (0=Mon, 4=Fri).
# hour/minute: scheduled UTC time.
# buffer_min: minutes before AND after to flag as near-event.
# recurring: "weekly" or "monthly_first_X" for monthly events.
# pair_impact: currencies affected.
class _HighImpactEvent(TypedDict):
    day: int
    hour: int
    minute: int
    buffer_min: int
    pair_impact: list[str]
    recurring: Literal["monthly_first_friday", "scheduled", "weekly"]


HIGH_IMPACT_EVENTS: dict[str, _HighImpactEvent] = {
    "NFP": {
        "day": 4,
        "hour": 13,
        "minute": 30,
        "buffer_min": 30,
        "pair_impact": ["USD"],
        "recurring": "monthly_first_friday",
    },
    "FOMC": {
        "day": 2,
        "hour": 19,
        "minute": 0,
        "buffer_min": 60,
        "pair_impact": ["USD"],
        "recurring": "scheduled",  # 8 times/year — not every Wednesday
    },
    "BOE": {
        "day": 3,
        "hour": 12,
        "minute": 0,
        "buffer_min": 30,
        "pair_impact": ["GBP"],
        "recurring": "scheduled",
    },
    "ECB": {
        "day": 3,
        "hour": 13,
        "minute": 45,
        "buffer_min": 30,
        "pair_impact": ["EUR"],
        "recurring": "scheduled",
    },
}


def _identify_session(h: int) -> tuple[str, float]:
    """Return (session_name, base_quality) for a UTC hour.

    Non-overlapping ranges checked in priority order.
    """
    for name, start, end, quality in _SESSIONS:
        if start <= h < end:
            return name, quality
    return "SYDNEY", _SYDNEY_QUALITY


def _extract_currencies(pair: str) -> list[str]:
    """Extract known currency codes from a pair string.

    Handles standard 6-char pairs (GBPUSD) and slash format (GBP/USD).
    """
    pair_upper = pair.upper().replace("/", "").replace("_", "")
    found: list[str] = []
    for ccy in _KNOWN_CURRENCIES:
        if ccy in pair_upper:
            found.append(ccy)  # noqa: PERF401
    return found


def _is_near_event(
    now: datetime,
    pair_currencies: list[str],
) -> tuple[bool, str | None]:
    """Check if current time is within a high-impact event buffer.

    Uses minute-level precision for buffer comparison.

    Returns (is_near, event_name_or_none).

    NOTE: Events marked 'scheduled' (FOMC, BOE, ECB) fire on every
    matching weekday. For production use, integrate a real economic
    calendar API. NFP uses a first-Friday-of-month heuristic.
    """
    dow = now.weekday()
    for name, ev in HIGH_IMPACT_EVENTS.items():
        if dow != ev["day"]:
            continue

        # NFP: only the first Friday of the month (day-of-month <= 7)
        if ev.get("recurring") == "monthly_first_friday" and now.day > 7:
            continue

        # Currency relevance check
        if not any(c in ev["pair_impact"] for c in pair_currencies):
            continue

        # Minute-precision buffer check
        event_time = now.replace(
            hour=ev["hour"],
            minute=ev.get("minute", 0),
            second=0,
            microsecond=0,
        )
        delta = abs((now - event_time).total_seconds()) / 60.0
        if delta <= ev["buffer_min"]:
            return True, name

    return False, None


def analyze_session(
    market_data: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """L4 Session & Timing Analysis — PRODUCTION.

    Pure analysis function.  Returns session identification, quality score,
    tradeability gate, and event buffer status.
    No execution side-effects.

    Parameters
    ----------
    market_data : dict
        Market data context (currently unused by L4 but accepted for
        pipeline consistency with other layers).
    pair : str
        Currency pair label, used for event-currency relevance checks.
    now : datetime, optional
        UTC timestamp override (for deterministic testing).

    Returns
    -------
    dict
        Session profile with ``session``, ``quality``, ``tradeable``,
        ``gate_reasons``, ``near_event``, ``event_name``, ``valid``.
    """
    if now is None:
        now = datetime.now(UTC)

    h = now.hour
    dow = now.weekday()

    # ── Session identification ──
    session, quality = _identify_session(h)

    # ── Tradeability & quality modifiers ──
    tradeable = True
    gate_reasons: list[str] = []

    # Weekend gate (absolute block)
    if dow >= 5:  # Saturday=5, Sunday=6
        tradeable = False
        quality = _WEEKEND_QUALITY
        gate_reasons.append("WEEKEND")
    else:
        # Friday close degradation
        if dow == 4 and h >= _FRIDAY_CLOSE_START_HOUR:
            quality *= _FRIDAY_CLOSE_MULT
            gate_reasons.append("FRIDAY_CLOSE")

        # Sunday open degradation
        if dow == 0 and h < _SUNDAY_OPEN_END_HOUR:
            quality *= _SUNDAY_OPEN_MULT
            gate_reasons.append("SUNDAY_OPEN")

        # General off-hours (outside major sessions)
        if session == "SYDNEY":
            quality *= _OFF_HOURS_MULT
            gate_reasons.append("OFF_HOURS")

    # ── Event buffer ──
    pair_ccys = _extract_currencies(pair)
    near_event, event_name = _is_near_event(now, pair_ccys)

    if near_event:
        quality *= _EVENT_BUFFER_MULT
        gate_reasons.append(f"EVENT_BUFFER_{event_name}")

    # ── Normalize quality ──
    quality = round(max(0.0, min(1.0, quality)), 4)

    # ── Gate reason summary ──
    if not gate_reasons:
        gate_reasons.append("OK")

    logger.debug(
        "L4 session: pair=%s session=%s quality=%.4f tradeable=%s reasons=%s",
        pair, session, quality, tradeable, gate_reasons,
    )

    return {
        "session": session,
        "quality": quality,
        "tradeable": tradeable,
        "gate_reasons": gate_reasons,
        "near_event": near_event,
        "event_name": event_name,
        "hour_utc": h,
        "day_of_week": dow,
        "pair": pair,
        "valid": True,
        "timestamp": now.isoformat(),
    }
