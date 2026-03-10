"""Immediate PostgreSQL write-through for trade lifecycle snapshots."""

from __future__ import annotations

import json
import uuid
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

    event_payload_safe = {"trade_id": trade_id, **(event_payload or {})}
    outbox_topic = str((event_payload or {}).get("outbox_topic") or "trade_lifecycle")
    outbox_status = "PENDING"
    outbox_id = str(uuid.uuid4())
    outbox_key = str((event_payload or {}).get("execution_intent_id") or "").strip() or outbox_id

    trade_sql = """
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
    """
    trade_args: tuple[Any, ...] = (
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

    operations: list[tuple[str, tuple[Any, ...]]] = [(trade_sql, trade_args)]

    if event_type:
        operations.append(
            (
                """
                INSERT INTO system_events (event_type, account_id, severity, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                (
                    event_type,
                    str(trade.get("account_id") or "") or None,
                    "INFO",
                    json.dumps(event_payload_safe),
                ),
            )
        )
        operations.append(
            (
                """
                INSERT INTO trade_outbox (
                    outbox_id, outbox_key, trade_id, event_type, topic, payload,
                    status, attempts, next_attempt_at, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6::jsonb,
                    $7, $8, $9, $10, $11
                )
                ON CONFLICT (outbox_key) DO NOTHING
                """,
                (
                    outbox_id,
                    outbox_key,
                    trade_id,
                    event_type,
                    outbox_topic,
                    json.dumps(event_payload_safe),
                    outbox_status,
                    0,
                    now,
                    now,
                    now,
                ),
            )
        )

    try:
        if hasattr(client, "execute_in_transaction"):
            await client.execute_in_transaction(operations)
        else:
            for query, args in operations:
                await client.execute(query, *args)
    except Exception as exc:
        logger.warning("Trade write-through failed for %s: %s", trade_id, exc)
        return False

    return True


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
