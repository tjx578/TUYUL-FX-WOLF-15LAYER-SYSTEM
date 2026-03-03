"""
TUYUL FX Wolf-15 — Journal Extended Routes
============================================
NEW ENDPOINTS:
  GET /api/v1/journal/search  → Filter by pair, regime, session, outcome, journal_type
  GET /api/v1/journal/today   → Today's entries (enhanced with constitutional fields)
  GET /api/v1/journal/weekly  → Weekly entries
  GET /api/v1/journal/metrics → Extended metrics including constitutional_violation_count
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, Query

from api.middleware.auth import verify_token
from infrastructure.redis_url import get_redis_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/journal",
    tags=["journal"],
    dependencies=[Depends(verify_token)],
)


def _get_redis() -> Optional[redis_lib.Redis]:
    url = get_redis_url()
    try:
        r = redis_lib.from_url(url, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _load_journal_entries(
    r: Optional[redis_lib.Redis],
    since: Optional[datetime] = None,
) -> list[dict]:
    """Load all JOURNAL:* entries from Redis, optionally filtered by time."""
    entries: list[dict] = []
    if not r:
        return entries
    try:
        for key in r.scan_iter("JOURNAL:*"):
            raw = r.get(key)
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if since:
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < since:
                            continue
                    except ValueError:
                        pass
            entries.append(entry)
    except Exception as exc:
        logger.warning("Journal entries scan failed: %s", exc)
    return entries


def _compute_metrics(entries: list[dict]) -> dict:
    """Compute journal metrics from a list of entries."""
    takes   = [e for e in entries if e.get("action") == "TAKE"]
    skips   = [e for e in entries if e.get("action") == "SKIP"]
    closes  = [e for e in entries if e.get("action") == "CLOSE"]
    wins    = [e for e in closes if e.get("outcome") == "WIN"]
    losses  = [e for e in closes if e.get("outcome") == "LOSS"]
    be      = [e for e in closes if e.get("outcome") == "BREAKEVEN"]

    total_pnl = sum(e.get("pnl", 0.0) for e in closes)
    rr_values = [e.get("rr_achieved", 0.0) for e in closes if e.get("rr_achieved")]
    avg_rr = round(sum(rr_values) / len(rr_values), 3) if rr_values else 0.0

    total_closed = len(wins) + len(losses) + len(be)
    win_rate = round(len(wins) / total_closed, 4) if total_closed > 0 else 0.0
    rejection_rate = (
        round(len(skips) / (len(takes) + len(skips)), 4)
        if (len(takes) + len(skips)) > 0
        else 0.0
    )

    # Profit factor
    gross_profit = sum(e.get("pnl", 0.0) for e in wins)
    gross_loss = abs(sum(e.get("pnl", 0.0) for e in losses))
    profit_factor = (
        round(gross_profit / gross_loss, 3) if gross_loss > 0 else 0.0
    )

    # Expectancy = (win_rate * avg_win_rr) - (loss_rate * avg_loss_rr)
    avg_win_rr = (
        round(sum(e.get("rr_achieved", 0.0) for e in wins if e.get("rr_achieved")) / len(wins), 3)
        if wins else 0.0
    )
    avg_loss_rr = (
        round(abs(sum(e.get("rr_achieved", 0.0) for e in losses if e.get("rr_achieved"))) / len(losses), 3)
        if losses else 0.0
    )
    loss_rate = 1 - win_rate
    expectancy = round(win_rate * avg_win_rr - loss_rate * avg_loss_rr, 3)

    # Constitutional violations = SKIP entries with reason containing "CONSTITUTIONAL" or "GATE"
    constitutional_violations = len([
        e for e in skips
        if any(kw in str(e.get("reason", "")).upper() for kw in ("CONSTITUTIONAL", "GATE", "L12", "CIRCUIT"))
    ])

    # Top mistake category (most common skip reason keyword)
    skip_reasons = [e.get("reason", "") for e in skips]
    reason_counts: dict[str, int] = {}
    for r_str in skip_reasons:
        category = _categorize_skip(r_str)
        reason_counts[category] = reason_counts.get(category, 0) + 1
    top_mistake = max(reason_counts, key=lambda k: reason_counts[k]) if reason_counts else None

    # Best / worst pair
    pair_pnl: dict[str, float] = {}
    for e in closes:
        p = e.get("pair", "UNKNOWN")
        pair_pnl[p] = pair_pnl.get(p, 0.0) + e.get("pnl", 0.0)
    best_pair = max(pair_pnl, key=lambda k: pair_pnl[k]) if pair_pnl else None
    worst_pair = min(pair_pnl, key=lambda k: pair_pnl[k]) if pair_pnl else None

    return {
        "total_trades": total_closed,
        "total_wins": len(wins),
        "total_losses": len(losses),
        "total_skipped": len(skips),
        "total_breakeven": len(be),
        "win_rate": win_rate,
        "rejection_rate": rejection_rate,
        "avg_rr": avg_rr,
        "avg_win_rr": avg_win_rr,
        "avg_loss_rr": avg_loss_rr,
        "total_pnl": round(total_pnl, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "best_pair": best_pair,
        "worst_pair": worst_pair,
        "constitutional_violation_count": constitutional_violations,
        "top_mistake_category": top_mistake,
    }


def _categorize_skip(reason: str) -> str:
    reason_upper = reason.upper()
    if any(k in reason_upper for k in ("NEWS", "CALENDAR", "FOMC", "NFP")):
        return "NEWS_RISK"
    if any(k in reason_upper for k in ("SPREAD", "LIQUIDITY")):
        return "SPREAD_WIDE"
    if any(k in reason_upper for k in ("CONFLUENCE", "WEAK", "SCORE")):
        return "LOW_CONFLUENCE"
    if any(k in reason_upper for k in ("SESSION", "TIME")):
        return "OFF_SESSION"
    if any(k in reason_upper for k in ("GATE", "CONSTITUTIONAL", "L12")):
        return "CONSTITUTIONAL"
    if any(k in reason_upper for k in ("DD", "DRAWDOWN", "RISK")):
        return "RISK_LIMIT"
    return "OTHER"


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/search")
async def journal_search(
    pair: Optional[str] = Query(default=None),
    regime: Optional[str] = Query(default=None),
    session: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None, pattern="^(WIN|LOSS|BREAKEVEN)?$"),
    journal_type: Optional[str] = Query(default=None, pattern="^(J1|J2|J3|J4)?$"),
    action: Optional[str] = Query(default=None, pattern="^(TAKE|SKIP|OPEN|CLOSE)?$"),
    limit: int = Query(default=100, ge=1, le=500),
    days_back: int = Query(default=7, ge=1, le=90),
) -> dict:
    """
    Filter journal entries by pair, regime, session, outcome, journal_type.
    Frontend: Journal page → filter controls
    """
    r = _get_redis()
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    all_entries = _load_journal_entries(r, since=since)

    filtered = all_entries
    if pair:
        filtered = [e for e in filtered if e.get("pair", "").upper() == pair.upper()]
    if regime:
        filtered = [e for e in filtered if e.get("regime", "").upper() == regime.upper()]
    if session:
        filtered = [e for e in filtered if e.get("session", "").upper() == session.upper()]
    if outcome:
        filtered = [e for e in filtered if e.get("outcome", "").upper() == outcome.upper()]
    if journal_type:
        filtered = [e for e in filtered if e.get("journal_type", "") == journal_type]
    if action:
        filtered = [e for e in filtered if e.get("action", "").upper() == action.upper()]

    filtered.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    filtered = filtered[:limit]

    return {
        "total": len(filtered),
        "filters": {
            "pair": pair, "regime": regime, "session": session,
            "outcome": outcome, "journal_type": journal_type, "action": action,
        },
        "entries": filtered,
    }


@router.get("/today")
async def journal_today() -> dict:
    r = _get_redis()
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    entries = _load_journal_entries(r, since=start_of_day)
    entries.sort(key=lambda e: e.get("timestamp", ""))

    return {
        "date": start_of_day.strftime("%Y-%m-%d"),
        "entries": entries,
        "metrics": _compute_metrics(entries),
        "net_pnl": round(sum(e.get("pnl", 0.0) for e in entries if e.get("action") == "CLOSE"), 2),
        "sessions": list({e.get("session", "") for e in entries if e.get("session")}),
    }


@router.get("/weekly")
async def journal_weekly() -> list[dict]:
    r = _get_redis()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    all_entries = _load_journal_entries(r, since=since)

    # Group by date
    by_date: dict[str, list[dict]] = {}
    for entry in all_entries:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            date_key = ts.strftime("%Y-%m-%d")
        except ValueError:
            date_key = "unknown"
        by_date.setdefault(date_key, []).append(entry)

    result = []
    for date, day_entries in sorted(by_date.items(), reverse=True):
        day_entries.sort(key=lambda e: e.get("timestamp", ""))
        result.append({
            "date": date,
            "entries": day_entries,
            "metrics": _compute_metrics(day_entries),
            "net_pnl": round(
                sum(e.get("pnl", 0.0) for e in day_entries if e.get("action") == "CLOSE"), 2
            ),
            "sessions": list({e.get("session", "") for e in day_entries if e.get("session")}),
        })
    return result


@router.get("/metrics")
async def journal_metrics(days_back: int = Query(default=30, ge=1, le=365)) -> dict:
    """Extended metrics including constitutional_violation_count, top_mistake_category."""
    r = _get_redis()
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    entries = _load_journal_entries(r, since=since)
    metrics = _compute_metrics(entries)
    metrics["period_days"] = days_back
    metrics["as_of"] = datetime.now(timezone.utc).isoformat()
    return metrics
