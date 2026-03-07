"""Immediate PostgreSQL write-through for trade lifecycle snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from storage.postgres_client import PostgresClient, pg_client

_TERMINAL_STATUS = {"CLOSED", "CANCELLED", "SKIPPED", "ABORTED"}


async def persist_trade_snapshot(
    trade: dict[str, Any],
    *,
    event_type: str | None = None,
    event_payload: dict[str, Any] | None = None,
    pg: PostgresClient | None = None,
) -> bool:
    """Persist one trade snapshot immediately to PostgreSQL.

    This function is intentionally best-effort; caller should not fail request
    flow when PostgreSQL is unavailable.
    """
    client = pg or pg_client
    if not client.is_available:
        return False

    trade_id = str(trade.get("trade_id") or "").strip()
    if not trade_id:
        return False

    now = datetime.now(UTC)
    created_at = _as_datetime(trade.get("created_at"), fallback=now)
    updated_at = _as_datetime(trade.get("updated_at"), fallback=now)

    status = str(trade.get("status") or "INTENDED").upper()
    closed_at = _as_datetime(trade.get("closed_at"), fallback=updated_at) if status in _TERMINAL_STATUS else None

    try:
        await client.execute(
            """
            INSERT INTO trade_history (
                trade_id, signal_id, account_id, pair, direction, status, risk_mode,
                total_risk_percent, total_risk_amount, pnl, close_reason, legs,
                metadata, created_at, updated_at, closed_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12::jsonb,
                $13::jsonb, $14, $15, $16
            )
            ON CONFLICT (trade_id) DO UPDATE SET
                signal_id = EXCLUDED.signal_id,
                account_id = EXCLUDED.account_id,
                pair = EXCLUDED.pair,
                direction = EXCLUDED.direction,
                status = EXCLUDED.status,
                risk_mode = EXCLUDED.risk_mode,
                total_risk_percent = EXCLUDED.total_risk_percent,
                total_risk_amount = EXCLUDED.total_risk_amount,
                pnl = EXCLUDED.pnl,
                close_reason = EXCLUDED.close_reason,
                legs = EXCLUDED.legs,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at,
                closed_at = EXCLUDED.closed_at
            """,
            trade_id,
            str(trade.get("signal_id") or ""),
            str(trade.get("account_id") or ""),
            str(trade.get("pair") or ""),
            str(trade.get("direction") or ""),
            status,
            str(trade.get("risk_mode") or "FIXED"),
            float(trade.get("total_risk_percent", 0.0) or 0.0),
            float(trade.get("total_risk_amount", 0.0) or 0.0),
            _optional_float(trade.get("pnl")),
            trade.get("close_reason"),
            json.dumps(trade.get("legs", [])),
            json.dumps(trade.get("metadata", {})),
            created_at,
            updated_at,
            closed_at,
        )
    except Exception as exc:
        logger.warning("Trade write-through failed for %s: %s", trade_id, exc)
        return False

    if event_type:
        await _persist_event(
            client,
            event_type=event_type,
            account_id=str(trade.get("account_id") or "") or None,
            payload={"trade_id": trade_id, **(event_payload or {})},
        )

    return True


async def _persist_event(
    client: PostgresClient,
    *,
    event_type: str,
    account_id: str | None,
    payload: dict[str, Any],
) -> None:
    try:
        await client.execute(
            """
            INSERT INTO system_events (event_type, account_id, severity, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            account_id,
            "INFO",
            json.dumps(payload),
        )
    except Exception as exc:
        logger.warning("Trade event write-through failed for %s: %s", event_type, exc)


def _as_datetime(value: Any, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        with_value = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(with_value)
        except ValueError:
            return fallback
    return fallback


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
