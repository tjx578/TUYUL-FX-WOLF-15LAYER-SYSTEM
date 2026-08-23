"""Pure C2 SHADOW projection -> signed C3 command promotion.

The function in this module performs no database work and is not imported by
any runner.  The operator wiring owns locking and atomic persistence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorBinding,
    ExecutorMode,
    OrderInstruction,
    ShadowProjectionCommandGuards,
    ShadowProjectionCommandSource,
    sign_execution_command,
)
from contracts.mt5_shadow_projection_command import C3ShadowProjectionCommandRequest
from contracts.strategy_5scr_candidate_c2_shadow_v2 import account_snapshot_authority_hash_v2
from contracts.strategy_5scr_shadow_risk_projection import (
    C2_SHADOW_RISK_PROJECTION_RULE_VERSION,
    C2_SHADOW_SOURCE_ADMISSION_CLASS,
    C2ShadowRiskProjectionDecision,
    C2ShadowRiskProjectionState,
    C2ShadowRiskProjectionV1,
)


class ShadowProjectionCommandPromotionError(ValueError):
    """A stable fail-closed promotion rejection."""

    reason_code = "C3_SHADOW_PROJECTION_PROMOTION_REJECTED"


def _reject(reason_code: str) -> None:
    error = ShadowProjectionCommandPromotionError(reason_code)
    error.reason_code = reason_code
    raise error


def promote_shadow_projection_to_command(
    projection: C2ShadowRiskProjectionV1,
    request: C3ShadowProjectionCommandRequest,
    snapshot: AccountSnapshotV1,
    *,
    executor_login_hash: str,
    governance_version: int,
    issued_at_utc: datetime,
    signing_secret: str | bytes,
    signing_key_id: str,
) -> ExecutionCommandV1:
    """Build one signed, broker-inert command from exact locked authority."""

    issued_at = issued_at_utc.astimezone(UTC)
    if projection.source_admission_class != C2_SHADOW_SOURCE_ADMISSION_CLASS:
        _reject("C3_SOURCE_NOT_CANONICAL_CANDIDATE_V2")
    if projection.decision is not C2ShadowRiskProjectionDecision.WOULD_RESERVE:
        _reject("C3_PROJECTION_NOT_WOULD_RESERVE")
    if projection.state is not C2ShadowRiskProjectionState.AVAILABLE:
        _reject("C3_PROJECTION_NOT_AVAILABLE")
    if projection.kill_switch_observed != "ENGAGED":
        _reject("C3_PROJECTION_KILL_SWITCH_NOT_ENGAGED")
    if projection.expires_at_utc <= issued_at:
        _reject("C3_PROJECTION_EXPIRED")
    if (
        projection.shadow_authority_id != request.shadow_authority_id
        or projection.tradeplan_id != request.source_candidate_id
        or projection.candidate_revision != request.source_candidate_revision
        or projection.executor_id != request.executor_id
        or projection.account_id != request.account_id
        or projection.broker_symbol != request.broker_symbol
    ):
        _reject("C3_OPERATOR_TARGET_MISMATCH")
    if (
        snapshot.snapshot_id != projection.account_snapshot_id
        or snapshot.executor_id != projection.executor_id
        or snapshot.account_id != projection.account_id
        or account_snapshot_authority_hash_v2(snapshot) != projection.account_snapshot_hash
    ):
        _reject("C3_ACCOUNT_SNAPSHOT_BINDING_MISMATCH")
    if projection.would_volume is None:
        _reject("C3_PROJECTION_VOLUME_NOT_AVAILABLE")
    if request.expires_at_utc <= issued_at:
        _reject("C3_OPERATOR_REQUEST_EXPIRED")

    expires_at = min(request.expires_at_utc, projection.expires_at_utc)
    source = ShadowProjectionCommandSource(
        source_signal_id=projection.shadow_authority_id,
        source_signal_hash=projection.authority_hash,
        source_shadow_authority_id=projection.shadow_authority_id,
        source_shadow_authority_hash=projection.authority_hash,
        source_candidate_id=projection.tradeplan_id,
        source_candidate_sequence=projection.candidate_sequence,
        source_candidate_revision=projection.candidate_revision,
        source_candidate_material_hash=projection.material_candidate_hash,
        source_candidate_evidence_hash=projection.candidate_evidence_hash,
        source_admission_class=projection.source_admission_class,
        strategy_rule_version=C2_SHADOW_RISK_PROJECTION_RULE_VERSION,
        strategy_proof_hash=projection.evidence_hash,
    )
    order = OrderInstruction(
        canonical_symbol=projection.symbol,
        broker_symbol=projection.broker_symbol,
        side=projection.direction,
        order_type=projection.direction,
        volume=float(projection.would_volume),
        entry_price=float(projection.entry_price),
        stop_loss=float(projection.stop_loss),
        take_profit=float(projection.target_price),
        magic=request.magic,
        comment_tag=request.comment_tag,
        time_in_force="GTC",
    )
    payload = {
        "command_id": request.command_id,
        "idempotency_key": f"c3-shadow-projection:{request.operator_run_id}",
        "revision": 1,
        "issued_at_utc": issued_at,
        "not_before_utc": issued_at,
        "expires_at_utc": expires_at,
        "executor_binding": ExecutorBinding(
            executor_id=projection.executor_id,
            account_id=projection.account_id,
            login_hash=executor_login_hash,
            broker_server=projection.broker_server,
            execution_mode=ExecutorMode.SHADOW,
        ),
        "source": source,
        "action": ExecutionAction.PLACE_MARKET,
        "order": order,
        "guards": ShadowProjectionCommandGuards(
            max_spread_points=request.max_spread_points,
            max_price_drift_points=request.max_price_drift_points,
            expected_margin_mode=snapshot.margin_mode,
            account_snapshot_id=snapshot.snapshot_id,
            observed_governance_version=governance_version,
            balance_snapshot=snapshot.balance,
            equity_snapshot=snapshot.equity,
        ),
    }
    return sign_execution_command(payload, secret=signing_secret, key_id=signing_key_id)


__all__ = [
    "ShadowProjectionCommandPromotionError",
    "promote_shadow_projection_to_command",
]
