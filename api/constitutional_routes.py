"""
TUYUL FX Wolf-15 — Constitutional Health + Equity History Routes
================================================================
NEW ENDPOINTS:
  GET /api/v1/health/constitutional  → L12 pass rate, gate violations, circuit breaker
  GET /api/v1/equity/history         → Historical equity curve for charting
"""

import json
import contextlib
import logging
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Request

from api.middleware.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["health-equity"],
    dependencies=[Depends(verify_token)],
)


# ─── Endpoint 1: Constitutional Health ───────────────────────────────────────

@router.get("/health/constitutional")
async def constitutional_health(request: Request) -> dict:
    """
    Aggregate constitutional health for today's session.
    Data sources:
      - DASHBOARD:VERDICT:* keys in Redis (L12 verdicts)
      - Circuit breaker state per account
      - Gate violation counts

    Frontend: Overview page → ConstitutionalHealth panel
    """
    r: aioredis.Redis = request.app.state.redis

    total_verdicts = 0
    passed_verdicts = 0
    execute_count = 0
    hold_count = 0
    no_trade_count = 0
    gate_violations: dict[str, int] = {}
    pairs_scanned: list[str] = []

    try:
        async for key in r.scan_iter("DASHBOARD:VERDICT:*"):
            raw = await r.get(key)
            if not raw:
                continue
            try:
                verdict = json.loads(raw) if isinstance(raw, (str, bytes)) else json.loads(str(raw))
            except json.JSONDecodeError:
                continue

            total_verdicts += 1
            v_type = verdict.get("verdict", "")
            symbol = verdict.get("symbol", key.split(":")[-1])
            pairs_scanned.append(symbol)

            if v_type.startswith("EXECUTE"):
                execute_count += 1
                passed_verdicts += 1
            elif v_type == "HOLD":
                hold_count += 1
            elif v_type == "NO_TRADE":
                no_trade_count += 1

            # Count gate violations
            for gate in verdict.get("gates", []):
                if not gate.get("passed", True):
                    gate_id = gate.get("gate_id", "unknown")
                    gate_violations[gate_id] = gate_violations.get(gate_id, 0) + 1

    except Exception as exc:
        logger.warning("Redis scan for constitutional health failed: %s", exc)

    pass_rate = (
        round(passed_verdicts / total_verdicts, 4) if total_verdicts > 0 else 0.0
    )

    # Top violated gates
    top_violations = sorted(
        [{"gate_id": k, "count": v} for k, v in gate_violations.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:5]

    # Circuit breaker aggregate
    circuit_breaker_state = "CLOSED"
    with contextlib.suppress(Exception):
        async for key in r.scan_iter("RISK:CB:*"):
            cb = await r.get(key)
            if cb and cb != "CLOSED":
                circuit_breaker_state = str(cb)
                break

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_pairs_scanned": total_verdicts,
        "pairs_scanned": pairs_scanned,
        "l12_pass_rate": pass_rate,
        "l12_pass_count": passed_verdicts,
        "execute_signals": execute_count,
        "hold_signals": hold_count,
        "no_trade_signals": no_trade_count,
        "gate_violations_today": sum(gate_violations.values()),
        "top_violated_gates": top_violations,
        "circuit_breaker": circuit_breaker_state,
        "system_grade": _grade_health(pass_rate, circuit_breaker_state),
    }


def _grade_health(pass_rate: float, cb: str) -> str:
    if cb != "CLOSED":
        return "RESTRICTED"
    if pass_rate >= 0.7:
        return "OPTIMAL"
    if pass_rate >= 0.4:
        return "MODERATE"
    return "DEGRADED"


# ─── Endpoint 2: Equity History ───────────────────────────────────────────────

@router.get("/equity/history")
async def equity_history(
    request: Request,
    account_id: str | None = Query(default=None),
    period: str = Query(default="1d", pattern="^(1h|4h|1d|1w)$"),
) -> dict:
    """
    Historical equity curve data for charting.
    Frontend: Overview page → EquityCurve mini sparkline + Risk Monitor page.

    period: 1h = last hour, 4h = last 4 hours, 1d = today, 1w = this week
    """
    r: aioredis.Redis = request.app.state.redis

    # Time range
    now = datetime.now(UTC)
    period_map = {"1h": 1, "4h": 4, "1d": 24, "1w": 168}
    cutoff = now - timedelta(hours=period_map.get(period, 24))

    history: list[dict] = []

    try:
        pattern = (
            f"EQUITY:{account_id}:*"
            if account_id
            else "EQUITY:*"
        )
        keys: list[str] = []
        async for key in r.scan_iter(pattern):
            keys.append(key)
        keys.sort()

        for key in keys:
            raw = await r.get(key)
            if not raw:
                continue
            try:
                point = json.loads(raw)  # pyright: ignore[reportArgumentType]
                ts_str = point.get("timestamp", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts >= cutoff:
                        history.append(point)
            except (json.JSONDecodeError, ValueError):
                continue
    except Exception as exc:
        logger.warning("Redis equity history scan failed: %s", exc)

    # Sort by timestamp
    history.sort(key=lambda p: p.get("timestamp", ""))

    # Summary stats
    equities = [p.get("equity", 0) for p in history if p.get("equity")]
    equity_start = equities[0] if equities else 0
    equity_end = equities[-1] if equities else 0
    equity_change_pct = (
        round((equity_end - equity_start) / equity_start * 100, 3)
        if equity_start > 0
        else 0.0
    )

    return {
        "account_id": account_id,
        "period": period,
        "from": cutoff.isoformat(),
        "to": now.isoformat(),
        "data_points": len(history),
        "equity_start": equity_start,
        "equity_end": equity_end,
        "equity_change_pct": equity_change_pct,
        "history": history,
    }
