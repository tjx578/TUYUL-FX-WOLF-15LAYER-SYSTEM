"""Fail-closed promotion from final SignalJSON to an MT5 command.

Pressure, watch, and diagnostic payloads are explicitly non-promotable. This
module maps an already authorized trade plan to a broker command; it does not
calculate a side, target, stop, or volume.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from contracts.mt5_execution_protocol import (
    CommandGuards,
    CommandSource,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorBinding,
    ExecutorMode,
    MarginMode,
    OrderInstruction,
    sha256_tag,
    sign_execution_command,
)
from contracts.strategy_5scr import Strategy5SCRProof, evaluate_strategy_5scr_proof
from contracts.strategy_5scr_risk_reservation import (
    FinalSignalRiskReservation,
    validate_final_signal_reservation,
)

_DENIED_EVENTS = {
    "signal_pressure_state_json",
    "signal_pressure_state_summary",
    "signal_watch_json",
    "signal_decision_update_json",
    "signal_throttle",
    "signal_throttle_pressure_tier_snapshot",
}


class PromotionRejectedError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class PromotionContext(BaseModel):
    """Inputs already resolved by strategy, risk, and broker mapping planes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    login_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server: str = Field(..., min_length=1, max_length=200)
    execution_mode: ExecutorMode = ExecutorMode.SHADOW
    campaign_id: str = Field(..., min_length=3, max_length=200)
    block_id: str = Field(..., min_length=3, max_length=200)
    block_role: Literal["PARENT", "CHILD", "REVERSAL"]
    revision: int = Field(default=1, ge=1)
    action: ExecutionAction
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    order_type: Literal["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]
    volume: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    magic: int = Field(..., ge=1, le=2_147_483_647)
    issued_at_utc: datetime
    not_before_utc: datetime
    expires_at_utc: datetime
    expected_margin_mode: MarginMode
    max_spread_points: int = Field(..., ge=0)
    max_price_drift_points: int = Field(..., ge=0)
    risk_snapshot_id: str = Field(..., min_length=3, max_length=200)
    risk_reservation_id: str = Field(..., min_length=3, max_length=200)
    balance_snapshot: float = Field(..., gt=0)
    equity_snapshot: float = Field(..., gt=0)
    max_balance_drift_pct: float = Field(default=0.1, ge=0, le=5)
    max_equity_drift_pct: float = Field(default=1.0, ge=0, le=10)
    broker_expiration_utc: datetime | None = None


def _effective_bool(signal: Mapping[str, Any], field: str, nested: str) -> bool:
    block = signal.get(nested)
    if isinstance(block, Mapping) and field in block:
        return block.get(field) is True
    return signal.get(field) is True


def _validate_final_signal(
    signal: Mapping[str, Any],
) -> tuple[Literal["BUY", "SELL"], str, str, Strategy5SCRProof, FinalSignalRiskReservation]:
    event = str(signal.get("event") or "").lower()
    if event in _DENIED_EVENTS or event != "signal_json":
        raise PromotionRejectedError("PROMOTION_SOURCE_DENIED", f"event={event or 'missing'} is not final SignalJSON")
    if signal.get("is_final_signal") is not True:
        raise PromotionRejectedError("PROMOTION_NOT_FINAL", "is_final_signal must be true")
    if not _effective_bool(signal, "valid_for_execution", "execution_gate"):
        raise PromotionRejectedError("PROMOTION_EXECUTION_INVALID", "valid_for_execution must be true")
    if not _effective_bool(signal, "execution_valid_now", "execution_gate"):
        raise PromotionRejectedError("PROMOTION_EXECUTION_NOT_CURRENT", "execution_valid_now must be true")
    if not _effective_bool(signal, "tradeplan_valid", "tradeplan_preview"):
        raise PromotionRejectedError("PROMOTION_TRADEPLAN_INVALID", "tradeplan_valid must be true")
    for field in ("analysis_valid", "direction_valid", "signal_valid"):
        if signal.get(field) is not True:
            raise PromotionRejectedError("PROMOTION_CONTRACT_INVALID", f"{field} must be true")
    if str(signal.get("rr_status") or "").upper() not in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}:
        raise PromotionRejectedError("PROMOTION_RR_INVALID", "RR must be final and execution-grade")

    resolved_side = str(signal.get("final_direction") or "").upper()
    if resolved_side not in {"BUY", "SELL"}:
        raise PromotionRejectedError("PROMOTION_SIDE_INVALID", "final_direction must be BUY or SELL")
    side = cast(Literal["BUY", "SELL"], resolved_side)
    signal_id = str(signal.get("signal_id") or "").strip()
    lifecycle_anchor = str(
        signal.get("lifecycle_id") or signal.get("terminal_decision_id") or signal.get("source_clean_block_id") or ""
    ).strip()
    schema_version = str(signal.get("schema_version") or "").strip()
    if len(signal_id) < 3 or len(lifecycle_anchor) < 3 or not schema_version:
        raise PromotionRejectedError(
            "PROMOTION_LINEAGE_MISSING", "signal id, lifecycle anchor, and schema are required"
        )
    strategy_evaluation = evaluate_strategy_5scr_proof(signal)
    if not strategy_evaluation.ready or strategy_evaluation.proof is None:
        raise PromotionRejectedError(
            "PROMOTION_5SCR_GATE_REJECTED",
            ",".join(strategy_evaluation.reasons) or "strategy proof is not execution-ready",
        )
    try:
        reservation = validate_final_signal_reservation(dict(signal))
    except ValueError as exc:
        raise PromotionRejectedError("PROMOTION_RISK_RESERVATION_INVALID", str(exc)) from exc
    return side, signal_id, lifecycle_anchor, strategy_evaluation.proof, reservation


def promote_final_signal_to_command(
    signal: Mapping[str, Any],
    *,
    context: PromotionContext,
    signing_secret: str | bytes,
    signing_key_id: str,
    command_id: UUID | None = None,
) -> ExecutionCommandV1:
    side, signal_id, lifecycle_anchor, strategy_proof, reservation = _validate_final_signal(signal)
    if context.action not in {ExecutionAction.PLACE_MARKET, ExecutionAction.PLACE_PENDING}:
        raise PromotionRejectedError(
            "PROMOTION_ACTION_INVALID",
            "final SignalJSON promotion may only create a new market or pending order",
        )
    if context.canonical_symbol != str(signal.get("symbol") or "").upper():
        raise PromotionRejectedError("PROMOTION_SYMBOL_MISMATCH", "context symbol does not match final signal")
    if context.execution_mode is not ExecutorMode.SHADOW:
        raise PromotionRejectedError(
            "PROMOTION_RISK_AUTHORITY_SHADOW_ONLY",
            "durable parent risk authority V1 may only create SHADOW commands",
        )
    if context.block_role != "PARENT":
        raise PromotionRejectedError(
            "PROMOTION_RISK_AUTHORITY_PARENT_ONLY",
            "durable risk reservation is bound to a parent entry",
        )
    if context.campaign_id != lifecycle_anchor or context.campaign_id != reservation.campaign_id:
        raise PromotionRejectedError(
            "PROMOTION_CAMPAIGN_MISMATCH",
            "context campaign does not match final-signal lifecycle",
        )
    if context.block_id != reservation.tradeplan_id:
        raise PromotionRejectedError(
            "PROMOTION_TRADEPLAN_MISMATCH",
            "command block identity does not match the reserved tradeplan",
        )
    if context.canonical_symbol != reservation.canonical_symbol or context.broker_symbol != reservation.broker_symbol:
        raise PromotionRejectedError(
            "PROMOTION_RESERVED_SYMBOL_MISMATCH",
            "command symbol mapping does not match the durable reservation",
        )
    if side != reservation.direction:
        raise PromotionRejectedError(
            "PROMOTION_RESERVED_DIRECTION_MISMATCH",
            "final signal direction does not match the durable reservation",
        )
    if context.risk_reservation_id != str(reservation.reservation_id):
        raise PromotionRejectedError(
            "PROMOTION_RISK_RESERVATION_MISMATCH",
            "command context does not match the durable reservation",
        )
    if context.risk_snapshot_id != reservation.risk_snapshot_id:
        raise PromotionRejectedError(
            "PROMOTION_RISK_SNAPSHOT_MISMATCH",
            "command context does not match the reserved account snapshot",
        )
    if not math.isclose(context.volume, reservation.reserved_volume, rel_tol=1e-9, abs_tol=1e-9):
        raise PromotionRejectedError(
            "PROMOTION_RESERVED_VOLUME_MISMATCH",
            "command volume does not match the reserved volume",
        )
    if context.issued_at_utc < reservation.reserved_at_utc:
        raise PromotionRejectedError(
            "PROMOTION_RISK_RESERVATION_NOT_ACTIVE",
            "command predates the durable reservation",
        )
    if context.not_before_utc >= reservation.expires_at_utc or context.expires_at_utc > reservation.expires_at_utc:
        raise PromotionRejectedError(
            "PROMOTION_RISK_RESERVATION_EXPIRED",
            "command validity window exceeds the reservation",
        )
    if not context.order_type.startswith(side):
        raise PromotionRejectedError("PROMOTION_ORDER_SIDE_MISMATCH", "order type does not match final side")
    if not math.isclose(context.entry_price, strategy_proof.m1.fill_price, rel_tol=1e-9, abs_tol=1e-9):
        raise PromotionRejectedError("PROMOTION_5SCR_ENTRY_MISMATCH", "command entry is not the authorized M1 fill")
    if not math.isclose(context.stop_loss, strategy_proof.risk.structural_sl, rel_tol=1e-9, abs_tol=1e-9):
        raise PromotionRejectedError("PROMOTION_5SCR_SL_MISMATCH", "command stop is not the structural SL")
    if not math.isclose(context.take_profit, strategy_proof.h4.structural_tp1, rel_tol=1e-9, abs_tol=1e-9):
        raise PromotionRejectedError("PROMOTION_5SCR_TP1_MISMATCH", "command target is not structural TP1")

    command_uuid = command_id or uuid4()
    idempotency_key = ":".join(
        (
            context.account_id,
            context.campaign_id,
            context.block_id,
            str(context.revision),
            context.action.value,
        )
    )
    time_in_force: Literal["GTC", "SPECIFIED"] = (
        "SPECIFIED" if context.action == ExecutionAction.PLACE_PENDING else "GTC"
    )
    comment_tag = f"W15:{command_uuid.hex[:12].upper()}"

    payload = {
        "event": "execution_command",
        "protocol_version": "wolf15.mt5.exec.v1",
        "command_id": command_uuid,
        "idempotency_key": idempotency_key,
        "revision": context.revision,
        "issued_at_utc": context.issued_at_utc.astimezone(UTC),
        "not_before_utc": context.not_before_utc.astimezone(UTC),
        "expires_at_utc": context.expires_at_utc.astimezone(UTC),
        "executor_binding": ExecutorBinding(
            executor_id=context.executor_id,
            account_id=context.account_id,
            login_hash=context.login_hash,
            broker_server=context.broker_server,
            execution_mode=context.execution_mode,
        ),
        "source": CommandSource(
            source_event="signal_json",
            source_schema_version=str(signal["schema_version"]),
            source_signal_id=signal_id,
            source_signal_hash=sha256_tag(dict(signal)),
            campaign_id=context.campaign_id,
            block_id=context.block_id,
            block_role=context.block_role,
            lifecycle_anchor=lifecycle_anchor,
            valid_for_execution=True,
            execution_gate_passed=True,
            tradeplan_valid=True,
            strategy_model=strategy_proof.strategy_model,
            strategy_rule_version=strategy_proof.rule_version,
            strategy_rule_status=strategy_proof.rule_status,
            strategy_proof_hash=sha256_tag(strategy_proof.model_dump(mode="json")),
            context_resolution_status=cast(Literal["RESOLVED"], strategy_proof.context_resolution.status),
            confirmation_policy=strategy_proof.confirmation_policy,
        ),
        "action": context.action,
        "order": OrderInstruction(
            canonical_symbol=context.canonical_symbol,
            broker_symbol=context.broker_symbol,
            side=side,
            order_type=context.order_type,
            volume=context.volume,
            entry_price=context.entry_price,
            stop_loss=context.stop_loss,
            take_profit=context.take_profit,
            magic=context.magic,
            comment_tag=comment_tag,
            time_in_force=time_in_force,
            broker_expiration_utc=context.broker_expiration_utc,
        ),
        "guards": CommandGuards(
            max_spread_points=context.max_spread_points,
            max_price_drift_points=context.max_price_drift_points,
            expected_margin_mode=context.expected_margin_mode,
            risk_snapshot_id=context.risk_snapshot_id,
            risk_reservation_id=context.risk_reservation_id,
            balance_snapshot=context.balance_snapshot,
            equity_snapshot=context.equity_snapshot,
            max_balance_drift_pct=context.max_balance_drift_pct,
            max_equity_drift_pct=context.max_equity_drift_pct,
        ),
    }
    return sign_execution_command(payload, secret=signing_secret, key_id=signing_key_id)


__all__ = ["PromotionRejectedError", "PromotionContext", "promote_final_signal_to_command"]
