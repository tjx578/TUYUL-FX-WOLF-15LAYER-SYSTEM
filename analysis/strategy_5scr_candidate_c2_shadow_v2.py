"""Pure CandidateV2 -> C2 SHADOW risk-authority reduction."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Literal, cast

from pydantic import ValidationError

from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS,
    C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS,
    C2_SHADOW_MAX_ENTRIES,
    C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT,
    C2_SHADOW_RISK_PERCENT_PER_ENTRY,
    C2_SHADOW_RISK_POLICY_ID,
    C2_SHADOW_RULE_VERSION,
    C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS,
    C2ShadowAuthorityBundleV2,
    C2ShadowCampaignRiskLockV2,
    C2ShadowDecimalSizingV2,
    C2ShadowEvaluationV2,
    C2ShadowExecutionCampaignV2,
    C2ShadowFinalSignalV2,
    C2ShadowRiskReservationV2,
    CandidateC2ShadowBuildEvidenceV2,
    CandidateC2ShadowHandoffV2,
    CandidateC2ShadowReductionResultV2,
    candidate_c2_shadow_handoff_authority_material_v2,
    candidate_c2_shadow_handoff_identity_material_v2,
    snapshot_candidate_c2_build_evidence_v2,
    symbol_capability_authority_hash_v2,
)
from contracts.strategy_5scr_tradeplan_candidate_v2 import canonical_hash_v1, canonical_tradeplan_numeric_v2
from risk.s5_campaign_risk import (
    CampaignRiskLock,
    CampaignRiskPolicy,
    S5RiskReason,
    find_symbol_capability,
    validate_account_snapshot,
)

_C2_NUMERIC_28_12_ABS_LIMIT = Decimal("1e16")


def _id(prefix: str, material: object) -> str:
    import hashlib

    return f"{prefix}:" + hashlib.sha256(canonical_hash_v1(material).encode()).hexdigest()[:32]


def _is_canonical_c2_shadow_policy(policy: CampaignRiskPolicy) -> bool:
    """Pin every behavior-bearing field to the versioned P7 risk policy."""

    return (
        policy.risk_percent_per_entry == C2_SHADOW_RISK_PERCENT_PER_ENTRY
        and policy.max_entries == C2_SHADOW_MAX_ENTRIES
        and policy.max_total_open_risk_percent == C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT
        and policy.snapshot_max_age_seconds == C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS
    )


def _evaluation(
    evidence: CandidateC2ShadowBuildEvidenceV2,
    *,
    sequence: int,
    decision: str,
    reason: str,
    campaign_id: str | None = None,
    reservation_id: str | None = None,
) -> C2ShadowEvaluationV2:
    persisted = cast(Literal["APPROVED", "WAIT", "REJECTED"], decision)
    material = canonical_hash_v1(
        {
            "tradeplan_id": evidence.candidate.tradeplan_id,
            "candidate_material_hash": evidence.candidate.material_candidate_hash,
            "account_id": evidence.account_snapshot.account_id,
            "executor_id": str(evidence.account_snapshot.executor_id),
            "decision": persisted,
            "reason": reason,
            "campaign_id": campaign_id,
            "reservation_id": reservation_id,
            "rule_version": C2_SHADOW_RULE_VERSION,
        }
    )
    identity = {
        "source_request_id": evidence.source_request_id,
        "sequence": sequence,
        "decision_at_utc": evidence.decision_at_utc,
        "evidence_hash": evidence.authority_hash(),
        "material_hash": material,
    }
    return C2ShadowEvaluationV2(
        evaluation_id=_id("5scr-c2-eval-v2", identity),
        evaluation_sequence=sequence,
        source_request_id=evidence.source_request_id,
        tradeplan_id=evidence.candidate.tradeplan_id,
        material_candidate_hash=evidence.candidate.material_candidate_hash,
        account_id=evidence.account_snapshot.account_id,
        executor_id=evidence.account_snapshot.executor_id,
        decision=persisted,
        reason_code=reason,
        decision_at_utc=evidence.decision_at_utc,
        evidence_hash=evidence.authority_hash(),
        material_evaluation_hash=material,
        result_execution_campaign_id=campaign_id,
        result_reservation_id=reservation_id,
    )


def _rejected(
    evidence: CandidateC2ShadowBuildEvidenceV2,
    sequence: int,
    reason: str,
    *,
    wait: bool = False,
) -> CandidateC2ShadowReductionResultV2:
    decision = "WAIT" if wait else "REJECTED"
    return CandidateC2ShadowReductionResultV2(
        decision=decision,
        reason_code=reason,
        evaluation=_evaluation(evidence, sequence=sequence, decision=decision, reason=reason),
    )


def _on_grid(value: Decimal, tick: Decimal) -> bool:
    try:
        return value % tick == 0
    except InvalidOperation:
        return False


def _exact_c2_numeric_v2(value: Decimal) -> Decimal | None:
    """Return an exact durable NUMERIC(28,12) value, never a Decimal exception."""

    if not value.is_finite() or abs(value) >= _C2_NUMERIC_28_12_ABS_LIMIT:
        return None
    try:
        canonical = canonical_tradeplan_numeric_v2(value)
    except (InvalidOperation, ValueError):
        return None
    return canonical if canonical == value else None


def _exact_c2_capability_numeric_v2(value: Decimal | float | int) -> Decimal | None:
    """Safely project one broker capability number onto the durable grid."""

    try:
        projected = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return _exact_c2_numeric_v2(projected)


def size_c2_shadow_parent_decimal_v2(
    *,
    risk_unit_usd: Decimal,
    entry_price: Decimal,
    stop_loss: Decimal,
    tick_size: Decimal,
    tick_value_loss: Decimal,
    volume_min: Decimal,
    volume_max: Decimal,
    volume_step: Decimal,
) -> C2ShadowDecimalSizingV2:
    """Mirror the parent-only CampaignRiskPolicy sizing without float conversion."""

    values = (risk_unit_usd, entry_price, stop_loss, tick_size, tick_value_loss, volume_min, volume_max, volume_step)
    if any(value <= 0 for value in values) or entry_price == stop_loss or volume_max < volume_min:
        return C2ShadowDecimalSizingV2(
            allowed=False,
            reason_code="C2_RISK_INVALID_SYMBOL_SPEC",
            risk_unit_usd=max(risk_unit_usd, Decimal("0.000000000001")),
            effective_loss_per_lot=Decimal("0"),
            raw_volume=Decimal("0"),
            final_volume=Decimal("0"),
            actual_planned_risk_usd=Decimal("0"),
        )
    effective_loss = abs(entry_price - stop_loss) / tick_size * tick_value_loss
    raw_volume = risk_unit_usd / effective_loss
    final_volume = (raw_volume / volume_step).to_integral_value(rounding=ROUND_FLOOR) * volume_step
    actual_risk = final_volume * effective_loss
    if final_volume < volume_min:
        reason = "C2_RISK_VOLUME_BELOW_MINIMUM"
    elif final_volume > volume_max:
        reason = "C2_RISK_VOLUME_ABOVE_MAXIMUM"
    elif actual_risk > risk_unit_usd:
        reason = "C2_RISK_ACTUAL_EXCEEDS_1R"
    else:
        reason = "C2_RISK_APPROVED_PARENT"
    return C2ShadowDecimalSizingV2(
        allowed=reason == "C2_RISK_APPROVED_PARENT",
        reason_code=reason,
        risk_unit_usd=risk_unit_usd,
        effective_loss_per_lot=effective_loss,
        raw_volume=raw_volume,
        final_volume=final_volume,
        actual_planned_risk_usd=actual_risk,
    )


def evaluate_candidate_c2_shadow_v2(
    evidence: CandidateC2ShadowBuildEvidenceV2,
    *,
    evaluation_sequence: int,
    current_authority: C2ShadowAuthorityBundleV2 | None = None,
    risk_policy: CampaignRiskPolicy | None = None,
) -> CandidateC2ShadowReductionResultV2:
    """Evaluate and assemble one atomic, command-inert C2 SHADOW authority bundle."""

    # ``FrozenC2Contract`` does not make mutable protocol children such as
    # AccountSnapshotV1/SymbolCapability recursively immutable.  Snapshot the
    # complete graph and re-run every nested hash/invariant before trusting any
    # material or an idempotent current-authority path.
    try:
        evidence = snapshot_candidate_c2_build_evidence_v2(evidence)
    except (TypeError, ValidationError, ValueError) as exc:
        reason = (
            "C2_ACCOUNT_SNAPSHOT_HASH_DRIFT"
            if "C2_ACCOUNT_SNAPSHOT_HASH_DRIFT" in str(exc)
            else "C2_BUILD_EVIDENCE_INTEGRITY_INVALID"
        )
        return CandidateC2ShadowReductionResultV2(
            decision="QUARANTINED",
            reason_code=reason,
        )

    candidate = evidence.candidate
    policy = risk_policy or CampaignRiskPolicy()
    if not _is_canonical_c2_shadow_policy(policy):
        return _rejected(evidence, evaluation_sequence, "C2_RISK_POLICY_NOT_CANONICAL")

    current = current_authority
    if current is not None:
        # Never trust a typed instance alone: ``model_copy(update=...)`` can
        # bypass Pydantic validation. Re-run every nested authority invariant
        # before allowing the idempotent fast path.
        try:
            current = C2ShadowAuthorityBundleV2.model_validate(current.model_dump(mode="python"))
        except (ValidationError, ValueError):
            return CandidateC2ShadowReductionResultV2(
                decision="QUARANTINED", reason_code="C2_CURRENT_AUTHORITY_INTEGRITY_INVALID"
            )
        if current.handoff.tradeplan_id != candidate.tradeplan_id:
            return CandidateC2ShadowReductionResultV2(
                decision="QUARANTINED", reason_code="C2_CURRENT_AUTHORITY_SCOPE_MISMATCH"
            )
        expected_scope = (
            current.handoff.candidate_sequence == candidate.candidate_sequence
            and current.handoff.candidate_revision == candidate.candidate_revision
            and current.handoff.strategy_lifecycle_id == candidate.strategy_lifecycle_id
            and current.handoff.context_epoch_id == candidate.context_epoch_id
            and current.handoff.execution_box_id == candidate.execution_box_id
            and current.handoff.strategy_thesis_id == candidate.strategy_thesis_id
            and current.handoff.material_context_hash == candidate.material_context_hash
            and current.handoff.thesis_semantic_identity_hash == candidate.thesis_semantic_identity_hash
            and current.handoff.execution_box_material_hash == candidate.execution_box_material_hash
            and current.handoff.execution_box_freeze_authority_hash == candidate.execution_box_freeze_authority_hash
            and current.handoff.material_candidate_hash == candidate.material_candidate_hash
            and current.handoff.candidate_evidence_hash == candidate.evidence_hash
            and current.handoff.symbol == candidate.symbol
            and current.handoff.direction == candidate.direction
            and current.handoff.candidate_price == candidate.candidate_price
            and current.handoff.stop_loss == candidate.stop_authority.structural_stop_price
            and current.handoff.take_profit == candidate.target_authority.target_price
            and current.handoff.target_authority_hash == candidate.target_authority.authority_hash
            and current.handoff.stop_authority_hash == candidate.stop_authority.authority_hash
            and current.handoff.broker_geometry_material_hash == candidate.broker_geometry_material_hash
            and current.reservation.account_id == evidence.account_snapshot.account_id
            and current.reservation.executor_id == evidence.account_snapshot.executor_id
            and current.reservation.broker_server == evidence.governance.broker_server
            and current.reservation.canonical_symbol == candidate.symbol
            and current.reservation.broker_symbol == evidence.broker_symbol
        )
        if not expected_scope:
            return CandidateC2ShadowReductionResultV2(
                decision="QUARANTINED", reason_code="C2_CURRENT_AUTHORITY_SCOPE_MISMATCH"
            )

    if candidate.lifecycle_state != "ACTIVE":
        return _rejected(evidence, evaluation_sequence, "C2_CANDIDATE_NOT_ACTIVE")
    if candidate.valid_for_execution or candidate.execution_authority:
        return _rejected(evidence, evaluation_sequence, "C2_CANDIDATE_PREMATURE_AUTHORITY")
    if candidate.next_required_stage != "RISK_RESERVATION":
        return _rejected(evidence, evaluation_sequence, "C2_CANDIDATE_STAGE_MISMATCH")
    if evidence.decision_at_utc < candidate.decision_at_utc:
        return _rejected(evidence, evaluation_sequence, "C2_DECISION_PRECEDES_CANDIDATE")
    if (evidence.decision_at_utc - candidate.decision_at_utc).total_seconds() > C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS:
        return _rejected(evidence, evaluation_sequence, "C2_CANDIDATE_STALE")

    governance = evidence.governance
    if not governance.executor_registered or governance.executor_revoked:
        return _rejected(evidence, evaluation_sequence, "C2_EXECUTOR_NOT_ACTIVE")
    if governance.execution_mode != "SHADOW":
        return _rejected(evidence, evaluation_sequence, "C2_EXECUTOR_MODE_NOT_SHADOW")
    if governance.kill_switch_state != "DISENGAGED":
        return _rejected(evidence, evaluation_sequence, "C2_KILL_SWITCH_ENGAGED")
    if governance.verified_at_utc > evidence.decision_at_utc:
        return _rejected(evidence, evaluation_sequence, "C2_GOVERNANCE_FROM_FUTURE")
    if (evidence.decision_at_utc - governance.verified_at_utc).total_seconds() > C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS:
        return _rejected(evidence, evaluation_sequence, "C2_GOVERNANCE_STALE")

    snapshot = evidence.account_snapshot
    age = (evidence.decision_at_utc - snapshot.captured_at_utc).total_seconds()
    if age < -2:
        return _rejected(evidence, evaluation_sequence, "C2_ACCOUNT_SNAPSHOT_FROM_FUTURE")
    if age > C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS:
        return _rejected(evidence, evaluation_sequence, "C2_ACCOUNT_SNAPSHOT_STALE")
    snapshot_validation = validate_account_snapshot(
        snapshot,
        expected_account_id=governance.account_id,
        policy=policy,
        now=evidence.decision_at_utc,
    )
    if not snapshot_validation.allowed:
        reason = snapshot_validation.reason
        mapping = {
            S5RiskReason.ACCOUNT_MISMATCH: "C2_ACCOUNT_BINDING_MISMATCH",
            S5RiskReason.SNAPSHOT_INCONSISTENT: "C2_ACCOUNT_SNAPSHOT_INCONSISTENT",
            S5RiskReason.TRADE_DISABLED: "C2_ACCOUNT_TRADE_DISABLED",
            S5RiskReason.SNAPSHOT_STALE: "C2_ACCOUNT_SNAPSHOT_STALE",
        }
        resolved_reason = mapping[reason] if reason is not None and reason in mapping else "C2_ACCOUNT_SNAPSHOT_INVALID"
        return _rejected(evidence, evaluation_sequence, resolved_reason)
    if snapshot.currency != "USD":
        return _rejected(evidence, evaluation_sequence, "C2_ACCOUNT_CURRENCY_UNSUPPORTED")
    if snapshot.open_positions:
        return _rejected(evidence, evaluation_sequence, "C2_PARENT_REQUIRES_FLAT_ACCOUNT")
    if not snapshot.broker_ledger_reconciled:
        return _rejected(evidence, evaluation_sequence, "C2_BROKER_LEDGER_NOT_RECONCILED")
    if snapshot.pending_orders:
        return _rejected(evidence, evaluation_sequence, "C2_PARENT_REQUIRES_NO_PENDING_ORDERS")
    existing = evidence.existing_risk
    existing_age = (evidence.decision_at_utc - existing.captured_at_utc).total_seconds()
    if existing_age < 0:
        return _rejected(evidence, evaluation_sequence, "C2_EXISTING_RISK_FROM_FUTURE")
    if existing_age > C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS:
        return _rejected(evidence, evaluation_sequence, "C2_EXISTING_RISK_STALE")
    if not existing.broker_ledger_reconciled:
        return _rejected(evidence, evaluation_sequence, "C2_BROKER_LEDGER_NOT_RECONCILED")
    if existing.pending_order_count:
        return _rejected(evidence, evaluation_sequence, "C2_PARENT_REQUIRES_NO_PENDING_ORDERS")
    if (
        existing.active_campaign_count
        or existing.active_reservation_count
        or existing.committed_or_reserved_campaign_risk_usd
        or existing.account_total_open_risk_usd
    ):
        return _rejected(evidence, evaluation_sequence, "C2_EXISTING_RISK_NOT_FLAT")

    matching_specs = [
        item
        for item in snapshot.symbols
        if item.canonical_symbol == candidate.symbol and item.broker_symbol == evidence.broker_symbol
    ]
    if len(matching_specs) != 1:
        return _rejected(evidence, evaluation_sequence, "C2_SYMBOL_CAPABILITY_NOT_EXACT")
    spec = find_symbol_capability(snapshot, canonical_symbol=candidate.symbol, broker_symbol=evidence.broker_symbol)
    assert spec is not None
    projected_capability = tuple(
        _exact_c2_capability_numeric_v2(value)
        for value in (
            spec.point,
            spec.tick_size,
            spec.tick_value_loss,
            spec.volume_min,
            spec.volume_max,
            spec.volume_step,
            spec.stops_level_points,
            spec.freeze_level_points,
        )
    )
    if any(value is None for value in projected_capability):
        return _rejected(evidence, evaluation_sequence, "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE")
    point, tick, tick_value_loss, volume_min, volume_max, volume_step, stops_level, freeze_level = (
        value for value in projected_capability if value is not None
    )
    symbol_capability_hash = symbol_capability_authority_hash_v2(spec)
    projected_entry = _exact_c2_numeric_v2(candidate.candidate_price)
    projected_stop = _exact_c2_numeric_v2(candidate.stop_authority.structural_stop_price)
    projected_target = _exact_c2_numeric_v2(candidate.target_authority.target_price)
    if projected_entry is None or projected_stop is None or projected_target is None:
        return _rejected(evidence, evaluation_sequence, "C2_AUTHORITY_NUMERIC_GRID_UNREPRESENTABLE")
    entry_price, stop_loss, take_profit = projected_entry, projected_stop, projected_target
    geometry = (entry_price, stop_loss, take_profit)
    if (
        spec.digits != candidate.broker_digits
        or tick != candidate.broker_tick_size
        or point != candidate.broker_point
        or any(not _on_grid(value, tick) for value in geometry)
    ):
        return _rejected(evidence, evaluation_sequence, "C2_BROKER_GEOMETRY_DRIFT")
    minimum_distance = max(stops_level, freeze_level) * point
    if abs(entry_price - stop_loss) < minimum_distance or abs(take_profit - entry_price) < minimum_distance:
        return _rejected(evidence, evaluation_sequence, "C2_BROKER_DISTANCE_REJECTED")

    execution_campaign_id = _id(
        "5scr-execution-campaign-v2",
        {
            "tradeplan_id": candidate.tradeplan_id,
            "candidate_sequence": candidate.candidate_sequence,
            "candidate_revision": candidate.candidate_revision,
            "account_id": snapshot.account_id,
            "policy_id": C2_SHADOW_RISK_POLICY_ID,
        },
    )
    legacy_lock = CampaignRiskLock.create(
        campaign_id=execution_campaign_id,
        account_id=snapshot.account_id,
        closed_balance=snapshot.balance,
        policy=policy,
        now=evidence.decision_at_utc,
    )
    risk_percent_per_entry = _exact_c2_numeric_v2(legacy_lock.risk_percent_per_entry)
    if risk_percent_per_entry is None:
        return _rejected(evidence, evaluation_sequence, "C2_RISK_POLICY_NUMERIC_GRID_UNREPRESENTABLE")
    balance_base = _exact_c2_numeric_v2(legacy_lock.balance_base)
    if balance_base is None:
        return _rejected(evidence, evaluation_sequence, "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE")
    raw_risk_unit_usd = balance_base * risk_percent_per_entry
    raw_max_campaign_risk_usd = raw_risk_unit_usd * Decimal(policy.max_entries)
    risk_unit_usd = _exact_c2_numeric_v2(raw_risk_unit_usd)
    max_campaign_risk_usd = _exact_c2_numeric_v2(raw_max_campaign_risk_usd)
    if risk_unit_usd is None or max_campaign_risk_usd is None:
        return _rejected(evidence, evaluation_sequence, "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE")
    sized = size_c2_shadow_parent_decimal_v2(
        risk_unit_usd=risk_unit_usd,
        entry_price=entry_price,
        stop_loss=stop_loss,
        tick_size=tick,
        tick_value_loss=tick_value_loss,
        volume_min=volume_min,
        volume_max=volume_max,
        volume_step=volume_step,
    )
    if not sized.allowed:
        return _rejected(evidence, evaluation_sequence, sized.reason_code)
    volume = _exact_c2_numeric_v2(sized.final_volume)
    reserved_risk = _exact_c2_numeric_v2(sized.actual_planned_risk_usd)
    if volume is None or reserved_risk is None:
        return _rejected(evidence, evaluation_sequence, "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE")
    if reserved_risk != volume * sized.effective_loss_per_lot:
        return _rejected(evidence, evaluation_sequence, "C2_RISK_LOSS_DERIVATION_MISMATCH")

    # A durable reservation is idempotent only while its complete current
    # authority remains live.  In particular, a fresh retry must not bypass
    # account-ledger, risk, or broker-capability gates merely because a bundle
    # already exists.  Existing-risk evidence is defined as account risk
    # excluding this exact current campaign/reservation.
    if current is not None:
        if evidence.decision_at_utc >= current.reservation.expires_at_utc:
            return _rejected(evidence, evaluation_sequence, "C2_AUTHORITY_EXPIRED")
        if current.reservation.symbol_capability_hash != symbol_capability_hash:
            return _rejected(evidence, evaluation_sequence, "C2_BROKER_CAPABILITY_CHANGED")
        return CandidateC2ShadowReductionResultV2(
            decision="DUPLICATE",
            reason_code="C2_AUTHORITY_ALREADY_RESERVED",
            authority_bundle=current,
        )

    handoff_payload = {
        "tradeplan_id": candidate.tradeplan_id,
        "candidate_sequence": candidate.candidate_sequence,
        "candidate_revision": candidate.candidate_revision,
        "strategy_lifecycle_id": candidate.strategy_lifecycle_id,
        "context_epoch_id": candidate.context_epoch_id,
        "execution_box_id": candidate.execution_box_id,
        "strategy_thesis_id": candidate.strategy_thesis_id,
        "material_context_hash": candidate.material_context_hash,
        "thesis_semantic_identity_hash": candidate.thesis_semantic_identity_hash,
        "execution_box_material_hash": candidate.execution_box_material_hash,
        "execution_box_freeze_authority_hash": candidate.execution_box_freeze_authority_hash,
        "material_candidate_hash": candidate.material_candidate_hash,
        "candidate_evidence_hash": candidate.evidence_hash,
        "symbol": candidate.symbol,
        "direction": candidate.direction,
        "candidate_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "target_authority_hash": candidate.target_authority.authority_hash,
        "stop_authority_hash": candidate.stop_authority.authority_hash,
        "broker_geometry_material_hash": candidate.broker_geometry_material_hash,
        "account_id": snapshot.account_id,
        "executor_id": str(snapshot.executor_id),
        "broker_server": governance.broker_server,
        "account_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_hash": evidence.account_snapshot_hash,
        "symbol_capability_hash": symbol_capability_hash,
        "governance_evidence_hash": governance.evidence_hash,
        "existing_risk_evidence_hash": existing.evidence_hash,
        "accepted_at_utc": evidence.decision_at_utc,
        "risk_policy_id": C2_SHADOW_RISK_POLICY_ID,
        "rule_version": C2_SHADOW_RULE_VERSION,
        "execution_mode": "SHADOW",
        "execution_authority": False,
    }
    handoff_identity_material = candidate_c2_shadow_handoff_identity_material_v2(handoff_payload)
    handoff_id = _id("5scr-c2-handoff-v2", handoff_identity_material)
    handoff_payload["handoff_id"] = handoff_id
    handoff_authority_material = candidate_c2_shadow_handoff_authority_material_v2(handoff_payload)
    handoff_hash = canonical_hash_v1(handoff_authority_material)
    handoff = CandidateC2ShadowHandoffV2(
        handoff_id=handoff_id,
        tradeplan_id=candidate.tradeplan_id,
        candidate_sequence=candidate.candidate_sequence,
        candidate_revision=candidate.candidate_revision,
        strategy_lifecycle_id=candidate.strategy_lifecycle_id,
        context_epoch_id=candidate.context_epoch_id,
        strategy_thesis_id=candidate.strategy_thesis_id,
        execution_box_id=candidate.execution_box_id,
        account_id=snapshot.account_id,
        executor_id=snapshot.executor_id,
        broker_server=governance.broker_server,
        account_snapshot_id=snapshot.snapshot_id,
        account_snapshot_hash=evidence.account_snapshot_hash,
        symbol_capability_hash=symbol_capability_hash,
        governance_evidence_hash=governance.evidence_hash,
        existing_risk_evidence_hash=existing.evidence_hash,
        material_context_hash=candidate.material_context_hash,
        thesis_semantic_identity_hash=candidate.thesis_semantic_identity_hash,
        execution_box_material_hash=candidate.execution_box_material_hash,
        execution_box_freeze_authority_hash=candidate.execution_box_freeze_authority_hash,
        material_candidate_hash=candidate.material_candidate_hash,
        candidate_evidence_hash=candidate.evidence_hash,
        symbol=candidate.symbol,
        direction=candidate.direction,
        candidate_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        target_authority_hash=candidate.target_authority.authority_hash,
        stop_authority_hash=candidate.stop_authority.authority_hash,
        broker_geometry_material_hash=candidate.broker_geometry_material_hash,
        accepted_at_utc=evidence.decision_at_utc,
        authority_hash=handoff_hash,
    )
    risk_lock_material = {
        "execution_campaign_id": execution_campaign_id,
        "tradeplan_id": candidate.tradeplan_id,
        "account_id": snapshot.account_id,
        "account_snapshot_id": snapshot.snapshot_id,
        "balance_base": balance_base,
        "risk_percent_per_entry": risk_percent_per_entry,
        "risk_unit_usd": risk_unit_usd,
        "max_campaign_risk_usd": max_campaign_risk_usd,
        "locked_at_utc": evidence.decision_at_utc,
        "policy_id": C2_SHADOW_RISK_POLICY_ID,
    }
    risk_lock_hash = canonical_hash_v1(risk_lock_material)
    risk_lock = C2ShadowCampaignRiskLockV2(
        risk_lock_id=_id("5scr-c2-risk-lock-v2", risk_lock_material),
        authority_hash=risk_lock_hash,
        **risk_lock_material,
    )
    reservation_material = {
        "execution_campaign_id": execution_campaign_id,
        "risk_lock_id": risk_lock.risk_lock_id,
        "handoff_id": handoff.handoff_id,
        "tradeplan_id": candidate.tradeplan_id,
        "executor_id": str(snapshot.executor_id),
        "account_id": snapshot.account_id,
        "account_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_hash": evidence.account_snapshot_hash,
        "symbol_capability_hash": symbol_capability_hash,
        "governance_evidence_hash": governance.evidence_hash,
        "existing_risk_evidence_hash": existing.evidence_hash,
        "broker_server": governance.broker_server,
        "symbol": candidate.symbol,
        "broker_symbol": evidence.broker_symbol,
        "direction": candidate.direction,
        "volume": volume,
        "entry": entry_price,
        "stop": stop_loss,
        "target": take_profit,
        "risk_unit_usd": risk_unit_usd,
        "reserved_risk_usd": reserved_risk,
        "reserved_at_utc": evidence.decision_at_utc,
        "expires_at_utc": evidence.expires_at_utc,
    }
    reservation_hash = canonical_hash_v1(reservation_material)
    reservation = C2ShadowRiskReservationV2(
        reservation_id=_id("5scr-c2-reservation-v2", reservation_material),
        execution_campaign_id=execution_campaign_id,
        risk_lock_id=risk_lock.risk_lock_id,
        handoff_id=handoff.handoff_id,
        tradeplan_id=candidate.tradeplan_id,
        executor_id=snapshot.executor_id,
        account_id=snapshot.account_id,
        account_snapshot_id=snapshot.snapshot_id,
        account_snapshot_hash=evidence.account_snapshot_hash,
        symbol_capability_hash=symbol_capability_hash,
        governance_evidence_hash=governance.evidence_hash,
        existing_risk_evidence_hash=existing.evidence_hash,
        broker_server=governance.broker_server,
        canonical_symbol=candidate.symbol,
        broker_symbol=evidence.broker_symbol,
        direction=candidate.direction,
        volume=volume,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_unit_usd=risk_unit_usd,
        reserved_risk_usd=reserved_risk,
        reserved_at_utc=evidence.decision_at_utc,
        expires_at_utc=evidence.expires_at_utc,
        authority_hash=reservation_hash,
    )
    campaign_material = {
        "execution_campaign_id": execution_campaign_id,
        "tradeplan_id": candidate.tradeplan_id,
        "reservation_id": reservation.reservation_id,
        "account_id": snapshot.account_id,
        "symbol": candidate.symbol,
        "direction": candidate.direction,
        "state": "PARENT_PENDING",
        "opened_at_utc": evidence.decision_at_utc,
    }
    campaign = C2ShadowExecutionCampaignV2(
        execution_campaign_id=execution_campaign_id,
        tradeplan_id=candidate.tradeplan_id,
        reservation_id=reservation.reservation_id,
        account_id=snapshot.account_id,
        canonical_symbol=candidate.symbol,
        direction=candidate.direction,
        opened_at_utc=evidence.decision_at_utc,
        authority_hash=canonical_hash_v1(campaign_material),
    )
    signal_material = {
        "execution_campaign_id": execution_campaign_id,
        "tradeplan_id": candidate.tradeplan_id,
        "reservation_id": reservation.reservation_id,
        "handoff_id": handoff.handoff_id,
        "risk_lock_id": risk_lock.risk_lock_id,
        "account_id": snapshot.account_id,
        "executor_id": str(snapshot.executor_id),
        "broker_server": governance.broker_server,
        "risk_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_hash": evidence.account_snapshot_hash,
        "symbol_capability_hash": symbol_capability_hash,
        "governance_evidence_hash": governance.evidence_hash,
        "existing_risk_evidence_hash": existing.evidence_hash,
        "material_candidate_hash": candidate.material_candidate_hash,
        "candidate_evidence_hash": candidate.evidence_hash,
        "symbol": candidate.symbol,
        "broker_symbol": evidence.broker_symbol,
        "direction": candidate.direction,
        "entry_role": "PARENT",
        "entry": entry_price,
        "stop": stop_loss,
        "target": take_profit,
        "volume": volume,
        "issued_at_utc": evidence.decision_at_utc,
        "expires_at_utc": evidence.expires_at_utc,
    }
    signal_hash = canonical_hash_v1(signal_material)
    signal = C2ShadowFinalSignalV2(
        signal_id=_id("5scr-signal-shadow-v2", signal_material),
        execution_campaign_id=execution_campaign_id,
        tradeplan_id=candidate.tradeplan_id,
        reservation_id=reservation.reservation_id,
        handoff_id=handoff.handoff_id,
        risk_lock_id=risk_lock.risk_lock_id,
        account_id=snapshot.account_id,
        executor_id=snapshot.executor_id,
        broker_server=governance.broker_server,
        risk_snapshot_id=snapshot.snapshot_id,
        account_snapshot_hash=evidence.account_snapshot_hash,
        symbol_capability_hash=symbol_capability_hash,
        governance_evidence_hash=governance.evidence_hash,
        existing_risk_evidence_hash=existing.evidence_hash,
        material_candidate_hash=candidate.material_candidate_hash,
        candidate_evidence_hash=candidate.evidence_hash,
        canonical_symbol=candidate.symbol,
        broker_symbol=evidence.broker_symbol,
        final_direction=candidate.direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reserved_volume=volume,
        issued_at_utc=evidence.decision_at_utc,
        expires_at_utc=evidence.expires_at_utc,
        authority_hash=signal_hash,
    )
    bundle = C2ShadowAuthorityBundleV2(
        handoff=handoff,
        risk_lock=risk_lock,
        reservation=reservation,
        execution_campaign=campaign,
        final_signal=signal,
    )
    evaluation = _evaluation(
        evidence,
        sequence=evaluation_sequence,
        decision="APPROVED",
        reason="C2_SHADOW_RISK_AUTHORIZED",
        campaign_id=execution_campaign_id,
        reservation_id=reservation.reservation_id,
    )
    return CandidateC2ShadowReductionResultV2(
        decision="APPROVED",
        reason_code="C2_SHADOW_RISK_AUTHORIZED",
        evaluation=evaluation,
        authority_bundle=bundle,
    )


__all__ = ["evaluate_candidate_c2_shadow_v2", "size_c2_shadow_parent_decimal_v2"]
