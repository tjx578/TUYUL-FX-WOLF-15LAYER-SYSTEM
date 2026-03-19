"""
Execution Truth Feed — P1-7
==============================
Feeds execution truth back into journal and portfolio read models.

Appends journal entries (J3) for all execution lifecycle events:
  - ORDER_PLACED, ACKNOWLEDGED, FILLED, REJECTED, CANCELLED, EXPIRED, UNRESOLVED
Updates trade detail read model with slippage and RR truth.
Ensures portfolio views reflect actual confirmed exposure state.

Zone: execution + journal — write-only journal authority, no decision power.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from execution.execution_intent import (
    ExecutionIntentRecord,
    ExecutionLifecycleState,
)


class ExecutionTruthFeed:
    """Feeds execution outcome truth into journal and portfolio read models.

    Ensures both executed and rejected paths are journaled.
    """

    async def on_execution_state_change(
        self,
        intent: ExecutionIntentRecord,
        previous_state: ExecutionLifecycleState,
    ) -> None:
        """Called on every execution lifecycle state change.

        Appends J3 journal entry and updates portfolio read model.
        """
        await self._append_journal_entry(intent, previous_state)
        await self._update_portfolio_read_model(intent)
        await self._emit_truth_event(intent, previous_state)

    async def _append_journal_entry(
        self,
        intent: ExecutionIntentRecord,
        previous_state: ExecutionLifecycleState,
    ) -> None:
        """Append a J3 (Execution) journal entry for this state change."""
        entry = {
            "journal_type": "J3",
            "category": "execution",
            "execution_intent_id": intent.execution_intent_id,
            "take_id": intent.take_id,
            "signal_id": intent.signal_id,
            "account_id": intent.account_id,
            "symbol": intent.symbol,
            "direction": intent.direction,
            "previous_state": previous_state.value,
            "current_state": intent.state.value,
            "state_reason": intent.state_reason,
            "broker_order_id": intent.broker_order_id,
            "entry_price_planned": intent.entry_price,
            "fill_price_actual": intent.fill_price,
            "slippage": intent.slippage,
            "lot_size_planned": intent.lot_size,
            "lot_size_actual": intent.actual_lot_size,
            "stop_loss": intent.stop_loss,
            "take_profit_1": intent.take_profit_1,
            "rejection_code": intent.rejection_code,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Journal writer (execution lifecycle — raw JSON, not typed J3 model)
        try:
            import json as _json  # noqa: PLC0415
            from pathlib import Path as _Path  # noqa: PLC0415

            now = datetime.now(UTC)
            date_str = now.strftime("%Y-%m-%d")
            ts_str = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            archive_dir = _Path("storage/decision_archive") / date_str
            archive_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{ts_str}_execution_{intent.symbol}.json"
            with open(archive_dir / fname, "x", encoding="utf-8") as f:
                _json.dump(entry, f, indent=2, ensure_ascii=False)
        except Exception:
            logger.warning("[ExecTruthFeed] Journal write failed", exc_info=True)

        # Audit trail (immutable, hash-chained)
        try:
            from journal.audit_trail import AuditAction, AuditTrail  # noqa: PLC0415

            _audit_map: dict[str, AuditAction] = {
                "ORDER_PLACED": AuditAction.ORDER_PLACED,
                "FILLED": AuditAction.ORDER_FILLED,
                "CANCELLED": AuditAction.ORDER_CANCELLED,
                "EXPIRED": AuditAction.ORDER_EXPIRED,
            }
            audit_action = _audit_map.get(intent.state.value, AuditAction.ORDER_MODIFIED)
            trail = AuditTrail()
            trail.log(
                action=audit_action,
                actor="system:execution",
                resource=f"intent:{intent.execution_intent_id}",
                details={
                    "take_id": intent.take_id,
                    "signal_id": intent.signal_id,
                    "account_id": intent.account_id,
                    "symbol": intent.symbol,
                    "state": intent.state.value,
                    "fill_price": intent.fill_price,
                    "slippage": intent.slippage,
                },
            )
        except Exception:
            logger.debug("[ExecTruthFeed] Audit trail append failed")

    async def _update_portfolio_read_model(
        self,
        intent: ExecutionIntentRecord,
    ) -> None:
        """Update portfolio/trade detail read model with execution truth."""
        if intent.state not in (
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.EXPIRED,
        ):
            return  # Only update on definitive outcomes

        trade_detail: dict[str, Any] = {
            "execution_intent_id": intent.execution_intent_id,
            "take_id": intent.take_id,
            "signal_id": intent.signal_id,
            "account_id": intent.account_id,
            "symbol": intent.symbol,
            "direction": intent.direction,
            "outcome": intent.state.value,
            "entry_price_planned": intent.entry_price,
            "fill_price_actual": intent.fill_price,
            "slippage": intent.slippage,
            "lot_size_planned": intent.lot_size,
            "lot_size_actual": intent.actual_lot_size,
            "stop_loss": intent.stop_loss,
            "take_profit_1": intent.take_profit_1,
            "updated_at": intent.updated_at,
        }

        # Compute RR truth if fill data is available
        if intent.fill_price and intent.stop_loss and intent.take_profit_1:
            try:
                risk_distance = abs(intent.fill_price - intent.stop_loss)
                reward_distance = abs(intent.take_profit_1 - intent.fill_price)
                if risk_distance > 0:
                    trade_detail["rr_actual"] = round(reward_distance / risk_distance, 2)
            except (TypeError, ZeroDivisionError):
                pass

        # Persist to PostgreSQL read model
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if pg_client.is_available:
                import json  # noqa: PLC0415

                await pg_client.execute(
                    """
                    INSERT INTO trade_detail_read_model (
                        execution_intent_id, take_id, signal_id, account_id,
                        symbol, direction, outcome, details, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (execution_intent_id) DO UPDATE SET
                        outcome = EXCLUDED.outcome,
                        details = EXCLUDED.details,
                        updated_at = EXCLUDED.updated_at
                    """,
                    intent.execution_intent_id,
                    intent.take_id,
                    intent.signal_id,
                    intent.account_id,
                    intent.symbol,
                    intent.direction,
                    intent.state.value,
                    json.dumps(trade_detail),
                    intent.updated_at,
                )
        except Exception:
            logger.warning("[ExecTruthFeed] Portfolio read model update failed", exc_info=True)

        # Also cache in Redis for fast API reads
        try:
            import json  # noqa: PLC0415

            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                f"trade_detail:{intent.execution_intent_id}",
                json.dumps(trade_detail),
                ex=60 * 60 * 24 * 7,
            )
        except Exception:
            pass

    @staticmethod
    async def _emit_truth_event(
        intent: ExecutionIntentRecord,
        previous_state: ExecutionLifecycleState,
    ) -> None:
        """Emit execution truth event for downstream consumers."""
        try:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            publisher = StreamPublisher()
            await publisher.publish(
                stream="wolf15:execution:truth",
                fields={
                    "event_type": f"EXECUTION_TRUTH_{intent.state.value}",
                    "execution_intent_id": intent.execution_intent_id,
                    "take_id": intent.take_id,
                    "signal_id": intent.signal_id,
                    "account_id": intent.account_id,
                    "symbol": intent.symbol,
                    "previous_state": previous_state.value,
                    "current_state": intent.state.value,
                    "fill_price": str(intent.fill_price or ""),
                    "slippage": str(intent.slippage or ""),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.debug("[ExecTruthFeed] Truth event emission failed")

    @staticmethod
    async def ensure_table() -> None:
        """Create the trade_detail_read_model table if it does not exist."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_detail_read_model (
                    execution_intent_id TEXT PRIMARY KEY,
                    take_id             TEXT NOT NULL,
                    signal_id           TEXT NOT NULL,
                    account_id          TEXT NOT NULL,
                    symbol              TEXT NOT NULL DEFAULT '',
                    direction           TEXT NOT NULL DEFAULT '',
                    outcome             TEXT NOT NULL,
                    details             JSONB,
                    updated_at          TEXT NOT NULL
                )
                """
            )
            await pg_client.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_detail_account ON trade_detail_read_model (account_id)"
            )
            await pg_client.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_detail_signal ON trade_detail_read_model (signal_id)"
            )
        except Exception:
            logger.warning("[ExecTruthFeed] Table creation failed", exc_info=True)
