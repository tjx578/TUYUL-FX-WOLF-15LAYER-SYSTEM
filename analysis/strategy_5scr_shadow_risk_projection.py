"""Evaluate canonical Candidate V2 risk as a command-inert SHADOW projection."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from analysis.strategy_5scr_candidate_c2_shadow_v2 import size_c2_shadow_parent_decimal_v2
from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS,
    C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS,
    C2_SHADOW_MAX_ENTRIES,
    C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT,
    C2_SHADOW_RISK_PERCENT_PER_ENTRY,
    C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS,
    CandidateC2ShadowBuildEvidenceV2,
    snapshot_candidate_c2_build_evidence_v2,
)
from contracts.strategy_5scr_shadow_risk_projection import (
    C2_SHADOW_RISK_PROJECTION_RULE_VERSION,
    C2_SHADOW_SOURCE_ADMISSION_CLASS,
    C2ShadowRiskProjectionDecision,
    C2ShadowRiskProjectionEvaluationV1,
    C2ShadowRiskProjectionState,
    C2ShadowRiskProjectionV1,
    c2_shadow_risk_projection_authority_material_v1,
    c2_shadow_risk_projection_id_v1,
)
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    TRADEPLAN_CANDIDATE_V2_RULE_VERSION,
    TradePlanCandidateV2,
    canonical_hash_v1,
    canonical_tradeplan_numeric_v2,
)
from risk.s5_campaign_risk import (
    CampaignRiskLock,
    CampaignRiskPolicy,
    S5RiskReason,
    find_symbol_capability,
    validate_account_snapshot,
)

_NUMERIC_28_12_ABS_LIMIT = Decimal("1e16")


class ShadowRiskProjectionInputIntegrityError(ValueError):
    """Raised when canonical-looking input cannot be revalidated safely."""


def _exact_numeric(value: Decimal) -> Decimal | None:
    if not value.is_finite() or abs(value) >= _NUMERIC_28_12_ABS_LIMIT:
        return None
    try:
        canonical = canonical_tradeplan_numeric_v2(value)
    except (InvalidOperation, ValueError):
        return None
    return canonical if canonical == value else None


def _capability_numeric(value: Decimal | float | int) -> Decimal | None:
    try:
        return _exact_numeric(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _canonical_policy(policy: CampaignRiskPolicy) -> bool:
    return (
        policy.risk_percent_per_entry == C2_SHADOW_RISK_PERCENT_PER_ENTRY
        and policy.max_entries == C2_SHADOW_MAX_ENTRIES
        and policy.max_total_open_risk_percent == C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT
        and policy.snapshot_max_age_seconds == C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS
    )


def _on_grid(value: Decimal, tick: Decimal) -> bool:
    try:
        return value % tick == 0
    except InvalidOperation:
        return False


def _build_projection(
    evidence: CandidateC2ShadowBuildEvidenceV2,
    *,
    decision: C2ShadowRiskProjectionDecision,
    reason_code: str,
    would_volume: Decimal | None = None,
    would_risk_usd: Decimal | None = None,
    would_open_risk_after_usd: Decimal | None = None,
) -> C2ShadowRiskProjectionV1:
    candidate = evidence.candidate
    snapshot = evidence.account_snapshot
    payload = {
        "source_admission_class": C2_SHADOW_SOURCE_ADMISSION_CLASS,
        "tradeplan_id": candidate.tradeplan_id,
        "strategy_lifecycle_id": candidate.strategy_lifecycle_id,
        "context_epoch_id": candidate.context_epoch_id,
        "strategy_thesis_id": candidate.strategy_thesis_id,
        "execution_box_id": candidate.execution_box_id,
        "candidate_sequence": candidate.candidate_sequence,
        "candidate_revision": candidate.candidate_revision,
        "material_context_hash": candidate.material_context_hash,
        "thesis_semantic_identity_hash": candidate.thesis_semantic_identity_hash,
        "material_candidate_hash": candidate.material_candidate_hash,
        "candidate_evidence_hash": candidate.evidence_hash,
        "executor_id": snapshot.executor_id,
        "account_id": snapshot.account_id,
        "account_snapshot_id": snapshot.snapshot_id,
        "account_snapshot_hash": evidence.account_snapshot_hash,
        "broker_server": evidence.governance.broker_server,
        "symbol": candidate.symbol,
        "broker_symbol": evidence.broker_symbol,
        "direction": candidate.direction,
        "entry_price": candidate.candidate_price,
        "stop_loss": candidate.stop_authority.structural_stop_price,
        "target_price": candidate.target_authority.target_price,
        "would_volume": would_volume,
        "would_risk_usd": would_risk_usd,
        "would_margin_usd": None,
        "would_margin_status": "NOT_MEASURED",
        "would_open_risk_after_usd": would_open_risk_after_usd,
        "decision": decision,
        "reason_code": reason_code,
        "state": (
            C2ShadowRiskProjectionState.AVAILABLE
            if decision is C2ShadowRiskProjectionDecision.WOULD_RESERVE
            else C2ShadowRiskProjectionState.REJECTED
        ),
        "state_version": 1,
        "kill_switch_observed": "ENGAGED",
        "projected_at_utc": evidence.decision_at_utc,
        "expires_at_utc": evidence.expires_at_utc,
        "evidence_hash": evidence.authority_hash(),
        "rule_version": C2_SHADOW_RISK_PROJECTION_RULE_VERSION,
        "execution_authority": False,
        "capital_reserved": False,
        "broker_side_effect_allowed": False,
        "order_send_eligible": False,
    }
    authority_hash = canonical_hash_v1(c2_shadow_risk_projection_authority_material_v1(payload))
    return C2ShadowRiskProjectionV1(
        **payload,
        authority_hash=authority_hash,
        shadow_authority_id=c2_shadow_risk_projection_id_v1(payload, authority_hash),
    )


def _result(projection: C2ShadowRiskProjectionV1) -> C2ShadowRiskProjectionEvaluationV1:
    return C2ShadowRiskProjectionEvaluationV1(
        source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
        decision=projection.decision,
        reason_code=projection.reason_code,
        projection=projection,
    )


class Strategy5SCRShadowRiskProjectionEvaluatorV1:
    """Evaluate risk feasibility while kill switch stays ENGAGED and authority stays false."""

    def __init__(self, risk_policy: CampaignRiskPolicy | None = None) -> None:
        self._risk_policy = risk_policy or CampaignRiskPolicy()

    def evaluate(
        self,
        evidence: CandidateC2ShadowBuildEvidenceV2 | None,
        *,
        source_admission_class: str,
    ) -> C2ShadowRiskProjectionEvaluationV1:
        if source_admission_class != C2_SHADOW_SOURCE_ADMISSION_CLASS:
            return C2ShadowRiskProjectionEvaluationV1(
                source_admission_class=source_admission_class,
                decision=C2ShadowRiskProjectionDecision.WOULD_REJECT,
                reason_code="C2_SHADOW_SOURCE_NOT_CANONICAL",
                projection=None,
            )
        if evidence is None:
            raise ShadowRiskProjectionInputIntegrityError("canonical Candidate V2 evidence is required")
        try:
            evidence = snapshot_candidate_c2_build_evidence_v2(evidence)
            candidate = TradePlanCandidateV2.model_validate(evidence.candidate.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise ShadowRiskProjectionInputIntegrityError("canonical Candidate V2 evidence is invalid") from exc
        if candidate.rule_version != TRADEPLAN_CANDIDATE_V2_RULE_VERSION:
            raise ShadowRiskProjectionInputIntegrityError("candidate rule version is not canonical V2")
        if evidence.governance.kill_switch_state != "ENGAGED":
            raise ShadowRiskProjectionInputIntegrityError("SHADOW projection requires observed kill switch ENGAGED")

        reject = lambda reason: _result(  # noqa: E731 - compact fail-closed gate table
            _build_projection(evidence, decision=C2ShadowRiskProjectionDecision.WOULD_REJECT, reason_code=reason)
        )
        policy = self._risk_policy
        if not _canonical_policy(policy):
            return reject("C2_SHADOW_RISK_POLICY_NOT_CANONICAL")
        if candidate.lifecycle_state != "ACTIVE":
            return reject("C2_SHADOW_CANDIDATE_NOT_ACTIVE")
        candidate_age = (evidence.decision_at_utc - candidate.decision_at_utc).total_seconds()
        if candidate_age < 0:
            return reject("C2_SHADOW_CANDIDATE_FROM_FUTURE")
        if candidate_age > C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS:
            return reject("C2_SHADOW_CANDIDATE_STALE")

        governance = evidence.governance
        if not governance.executor_registered or governance.executor_revoked:
            return reject("C2_SHADOW_EXECUTOR_NOT_ACTIVE")
        if governance.execution_mode != "SHADOW":
            return reject("C2_SHADOW_EXECUTOR_MODE_NOT_SHADOW")
        if governance.verified_at_utc > evidence.decision_at_utc:
            return reject("C2_SHADOW_GOVERNANCE_FROM_FUTURE")
        if (
            evidence.decision_at_utc - governance.verified_at_utc
        ).total_seconds() > C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS:
            return reject("C2_SHADOW_GOVERNANCE_STALE")

        snapshot = evidence.account_snapshot
        age = (evidence.decision_at_utc - snapshot.captured_at_utc).total_seconds()
        if age < -2:
            return reject("C2_SHADOW_ACCOUNT_SNAPSHOT_FROM_FUTURE")
        if age > C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS:
            return reject("C2_SHADOW_ACCOUNT_SNAPSHOT_STALE")
        snapshot_verdict = validate_account_snapshot(
            snapshot,
            expected_account_id=governance.account_id,
            policy=policy,
            now=evidence.decision_at_utc,
        )
        if not snapshot_verdict.allowed:
            mapping = {
                S5RiskReason.ACCOUNT_MISMATCH: "C2_SHADOW_ACCOUNT_BINDING_MISMATCH",
                S5RiskReason.SNAPSHOT_INCONSISTENT: "C2_SHADOW_ACCOUNT_SNAPSHOT_INCONSISTENT",
                S5RiskReason.TRADE_DISABLED: "C2_SHADOW_ACCOUNT_TRADE_DISABLED",
                S5RiskReason.SNAPSHOT_STALE: "C2_SHADOW_ACCOUNT_SNAPSHOT_STALE",
            }
            return reject(mapping.get(snapshot_verdict.reason, "C2_SHADOW_ACCOUNT_SNAPSHOT_INVALID"))
        if snapshot.currency != "USD":
            return reject("C2_SHADOW_ACCOUNT_CURRENCY_UNSUPPORTED")
        if snapshot.open_positions:
            return reject("C2_SHADOW_PARENT_REQUIRES_FLAT_ACCOUNT")
        if not snapshot.broker_ledger_reconciled:
            return reject("C2_SHADOW_BROKER_LEDGER_NOT_RECONCILED")
        if snapshot.pending_orders:
            return reject("C2_SHADOW_PARENT_REQUIRES_NO_PENDING_ORDERS")

        existing = evidence.existing_risk
        existing_age = (evidence.decision_at_utc - existing.captured_at_utc).total_seconds()
        if existing_age < 0:
            return reject("C2_SHADOW_EXISTING_RISK_FROM_FUTURE")
        if existing_age > C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS:
            return reject("C2_SHADOW_EXISTING_RISK_STALE")
        if not existing.broker_ledger_reconciled:
            return reject("C2_SHADOW_BROKER_LEDGER_NOT_RECONCILED")
        if existing.pending_order_count:
            return reject("C2_SHADOW_PARENT_REQUIRES_NO_PENDING_ORDERS")
        if (
            existing.active_campaign_count
            or existing.active_reservation_count
            or existing.committed_or_reserved_campaign_risk_usd
            or existing.account_total_open_risk_usd
        ):
            return reject("C2_SHADOW_EXISTING_RISK_NOT_FLAT")

        matches = [
            item
            for item in snapshot.symbols
            if item.canonical_symbol == candidate.symbol and item.broker_symbol == evidence.broker_symbol
        ]
        if len(matches) != 1:
            return reject("C2_SHADOW_SYMBOL_CAPABILITY_NOT_EXACT")
        spec = find_symbol_capability(
            snapshot,
            canonical_symbol=candidate.symbol,
            broker_symbol=evidence.broker_symbol,
        )
        assert spec is not None
        projected = tuple(
            _capability_numeric(value)
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
        if any(value is None for value in projected):
            return reject("C2_SHADOW_RISK_NUMERIC_GRID_UNREPRESENTABLE")
        point, tick, tick_value_loss, volume_min, volume_max, volume_step, stops_level, freeze_level = (
            value for value in projected if value is not None
        )
        entry = _exact_numeric(candidate.candidate_price)
        stop = _exact_numeric(candidate.stop_authority.structural_stop_price)
        target = _exact_numeric(candidate.target_authority.target_price)
        if entry is None or stop is None or target is None:
            return reject("C2_SHADOW_AUTHORITY_NUMERIC_GRID_UNREPRESENTABLE")
        if (
            spec.digits != candidate.broker_digits
            or tick != candidate.broker_tick_size
            or point != candidate.broker_point
            or any(not _on_grid(value, tick) for value in (entry, stop, target))
        ):
            return reject("C2_SHADOW_BROKER_GEOMETRY_DRIFT")
        minimum_distance = max(stops_level, freeze_level) * point
        if abs(entry - stop) < minimum_distance or abs(target - entry) < minimum_distance:
            return reject("C2_SHADOW_BROKER_DISTANCE_REJECTED")

        risk_lock = CampaignRiskLock.create(
            campaign_id="shadow-projection-only",
            account_id=snapshot.account_id,
            closed_balance=snapshot.balance,
            policy=policy,
            now=evidence.decision_at_utc,
        )
        risk_unit = _exact_numeric(risk_lock.risk_unit_usd)
        if risk_unit is None:
            return reject("C2_SHADOW_RISK_NUMERIC_GRID_UNREPRESENTABLE")
        sized = size_c2_shadow_parent_decimal_v2(
            risk_unit_usd=risk_unit,
            entry_price=entry,
            stop_loss=stop,
            tick_size=tick,
            tick_value_loss=tick_value_loss,
            volume_min=volume_min,
            volume_max=volume_max,
            volume_step=volume_step,
        )
        if not sized.allowed:
            return reject(sized.reason_code.replace("C2_RISK_", "C2_SHADOW_RISK_"))
        volume = _exact_numeric(sized.final_volume)
        would_risk = _exact_numeric(sized.actual_planned_risk_usd)
        open_risk_after = _exact_numeric(existing.account_total_open_risk_usd + sized.actual_planned_risk_usd)
        if volume is None or would_risk is None or open_risk_after is None:
            return reject("C2_SHADOW_RISK_NUMERIC_GRID_UNREPRESENTABLE")
        account_cap = _exact_numeric(Decimal(str(snapshot.balance)) * policy.max_total_open_risk_percent)
        if account_cap is None or open_risk_after > account_cap:
            return reject("C2_SHADOW_ACCOUNT_OPEN_RISK_EXCEEDED")
        projection = _build_projection(
            evidence,
            decision=C2ShadowRiskProjectionDecision.WOULD_RESERVE,
            reason_code="C2_SHADOW_WOULD_RESERVE",
            would_volume=volume,
            would_risk_usd=would_risk,
            would_open_risk_after_usd=open_risk_after,
        )
        return _result(projection)


def evaluate_strategy_5scr_shadow_risk_projection_v1(
    evidence: CandidateC2ShadowBuildEvidenceV2 | None,
    *,
    source_admission_class: str,
    risk_policy: CampaignRiskPolicy | None = None,
) -> C2ShadowRiskProjectionEvaluationV1:
    return Strategy5SCRShadowRiskProjectionEvaluatorV1(risk_policy).evaluate(
        evidence,
        source_admission_class=source_admission_class,
    )


__all__ = [
    "ShadowRiskProjectionInputIntegrityError",
    "Strategy5SCRShadowRiskProjectionEvaluatorV1",
    "evaluate_strategy_5scr_shadow_risk_projection_v1",
]
