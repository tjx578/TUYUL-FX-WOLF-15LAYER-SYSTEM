"""
Trade Desk Read Router — Extended read endpoints for the Trade Desk UI.

Endpoints:
  GET  /api/v1/trades/active   — All non-terminal trades (INTENDED/PENDING/OPEN)
  GET  /api/v1/trades/{trade_id} — Single trade detail with execution timeline

NOTE: Write lifecycle (take/skip/confirm/close/events) lives in allocation_router.py.
      This router adds ONLY read-side enrichment that the Trade Desk needs.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import verify_token
from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from schemas.trade_models import TradeStatus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/trades",
    tags=["trade-desk"],
    dependencies=[Depends(verify_token)],
)

_trade_ledger = TradeLedger()
_price_feed = PriceFeed()


# ─── Helpers ──────────────────────────────────────────────────

_ACTIVE_STATUSES = frozenset({
    TradeStatus.INTENDED,
    TradeStatus.PENDING,
    TradeStatus.OPEN,
})


def _detect_anomalies(trade: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of anomaly flags for a trade (execution mismatch, stale, etc.)."""
    anomalies: list[dict[str, Any]] = []

    # Stale pending: PENDING for > 5 minutes without fill
    if trade.get("status") == TradeStatus.PENDING:
        created = trade.get("created_at")
        if created:
            try:
                from datetime import datetime
                if isinstance(created, str):
                    created_ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                elif isinstance(created, (int, float)):
                    created_ts = float(created)
                else:
                    created_ts = 0
                if created_ts > 0 and (time.time() - created_ts) > 300:
                    anomalies.append({
                        "type": "STALE_PENDING",
                        "message": "Order pending > 5 minutes without fill",
                        "severity": "WARNING",
                    })
            except (ValueError, TypeError):
                pass

    # Price mismatch: entry vs current price divergence > 2%
    entry = trade.get("entry_price")
    current = trade.get("current_price")
    if entry and current and entry > 0:
        deviation = abs(current - entry) / entry
        if deviation > 0.02:
            anomalies.append({
                "type": "PRICE_DEVIATION",
                "message": f"Current price deviates {deviation:.1%} from entry",
                "severity": "WARNING",
            })

    return anomalies


def _build_execution_timeline(trade: dict[str, Any]) -> list[dict[str, Any]]:
    """Build execution timeline events from trade metadata."""
    events: list[dict[str, Any]] = []

    if trade.get("created_at"):
        events.append({
            "event": "TRADE_CREATED",
            "status": TradeStatus.INTENDED,
            "timestamp": trade["created_at"],
        })

    if trade.get("confirmed_at"):
        events.append({
            "event": "TRADE_CONFIRMED",
            "status": TradeStatus.PENDING,
            "timestamp": trade["confirmed_at"],
        })

    if trade.get("opened_at"):
        events.append({
            "event": "ORDER_FILLED",
            "status": TradeStatus.OPEN,
            "timestamp": trade["opened_at"],
        })

    if trade.get("closed_at"):
        events.append({
            "event": "TRADE_CLOSED",
            "status": trade.get("status", TradeStatus.CLOSED),
            "timestamp": trade["closed_at"],
            "close_reason": trade.get("close_reason"),
            "pnl": trade.get("pnl"),
        })

    # Sort by timestamp
    events.sort(key=lambda e: str(e.get("timestamp", "")))
    return events


def _compute_exposure(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate exposure by pair and account from a list of active trades."""
    by_pair: dict[str, dict[str, Any]] = {}
    by_account: dict[str, dict[str, Any]] = {}

    for t in trades:
        pair = t.get("pair", t.get("symbol", "UNKNOWN"))
        acct = t.get("account_id", "UNKNOWN")
        lot = t.get("lot_size", t.get("lot", 0)) or 0
        direction = t.get("direction", t.get("side", ""))

        # By pair
        if pair not in by_pair:
            by_pair[pair] = {"pair": pair, "total_lots": 0, "buy_lots": 0, "sell_lots": 0, "count": 0}
        by_pair[pair]["total_lots"] += lot
        by_pair[pair]["count"] += 1
        if direction == "BUY":
            by_pair[pair]["buy_lots"] += lot
        elif direction == "SELL":
            by_pair[pair]["sell_lots"] += lot

        # By account
        if acct not in by_account:
            by_account[acct] = {"account_id": acct, "total_lots": 0, "count": 0, "pairs": set()}
        by_account[acct]["total_lots"] += lot
        by_account[acct]["count"] += 1
        by_account[acct]["pairs"].add(pair)

    # Convert sets to lists for JSON serialization
    for acct_data in by_account.values():
        acct_data["pairs"] = sorted(acct_data["pairs"])

    return {
        "by_pair": list(by_pair.values()),
        "by_account": list(by_account.values()),
        "total_lots": sum(v["total_lots"] for v in by_pair.values()),
        "total_trades": sum(v["count"] for v in by_pair.values()),
    }


# ─── Endpoints ────────────────────────────────────────────────


@router.get("/desk")
async def get_trade_desk() -> dict[str, Any]:
    """
    Trade Desk aggregate: active trades + exposure + anomalies.

    Used by the Trade Desk page for real-time overview.
    """
    all_trades = await _trade_ledger.get_all_trades_async()
    trade_list = all_trades if isinstance(all_trades, list) else list(all_trades.values()) if isinstance(all_trades, dict) else []

    # Normalize to dicts
    normalized: list[dict[str, Any]] = []
    for t in trade_list:
        if isinstance(t, dict):
            normalized.append(t)
        elif hasattr(t, "model_dump"):
            normalized.append(t.model_dump())
        elif hasattr(t, "__dict__"):
            normalized.append(vars(t))

    active = [t for t in normalized if t.get("status") in _ACTIVE_STATUSES]
    closed = [t for t in normalized if t.get("status") == TradeStatus.CLOSED]
    cancelled = [t for t in normalized if t.get("status") in {TradeStatus.CANCELLED, TradeStatus.SKIPPED}]

    # Detect anomalies across active trades
    trade_anomalies: list[dict[str, Any]] = []
    for t in active:
        anomalies = _detect_anomalies(t)
        if anomalies:
            trade_anomalies.append({
                "trade_id": t.get("trade_id"),
                "anomalies": anomalies,
            })

    return {
        "trades": {
            "pending": [t for t in active if t.get("status") == TradeStatus.INTENDED or t.get("status") == TradeStatus.PENDING],
            "open": [t for t in active if t.get("status") == TradeStatus.OPEN],
            "closed": closed,
            "cancelled": cancelled,
        },
        "exposure": _compute_exposure(active),
        "anomalies": trade_anomalies,
        "counts": {
            "pending": sum(1 for t in active if t.get("status") in {TradeStatus.INTENDED, TradeStatus.PENDING}),
            "open": sum(1 for t in active if t.get("status") == TradeStatus.OPEN),
            "closed": len(closed),
            "cancelled": len(cancelled),
            "total": len(normalized),
        },
        "server_ts": time.time(),
    }


@router.get("/{trade_id}/detail")
async def get_trade_detail(trade_id: str) -> dict[str, Any]:
    """Trade detail with execution timeline + anomaly markers."""
    trade = await _trade_ledger.get_trade_async(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade not found: {trade_id}")

    trade_dict = trade.model_dump() if hasattr(trade, "model_dump") else dict(trade) if isinstance(trade, dict) else vars(trade)

    # Enrich with current price
    pair = trade_dict.get("pair", trade_dict.get("symbol"))
    if pair:
        current_price = await _price_feed.get_price_async(pair.upper())
        if current_price:
            trade_dict["current_price"] = current_price

    return {
        "trade": trade_dict,
        "timeline": _build_execution_timeline(trade_dict),
        "anomalies": _detect_anomalies(trade_dict),
    }


@router.get("/exposure")
async def get_exposure_summary() -> dict[str, Any]:
    """Aggregated exposure by pair and account for active trades."""
    all_trades = await _trade_ledger.get_all_trades_async()
    trade_list = all_trades if isinstance(all_trades, list) else list(all_trades.values()) if isinstance(all_trades, dict) else []

    normalized: list[dict[str, Any]] = []
    for t in trade_list:
        if isinstance(t, dict):
            normalized.append(t)
        elif hasattr(t, "model_dump"):
            normalized.append(t.model_dump())
        elif hasattr(t, "__dict__"):
            normalized.append(vars(t))

    active = [t for t in normalized if t.get("status") in _ACTIVE_STATUSES]
    return _compute_exposure(active)
