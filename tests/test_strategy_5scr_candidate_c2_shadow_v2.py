from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

import pytest

from analysis.strategy_5scr_candidate_c2_shadow_v2 import (
    evaluate_candidate_c2_shadow_v2,
    size_c2_shadow_parent_decimal_v2,
)
from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    MarginMode,
    OpenBrokerOrder,
    OpenBrokerPosition,
    SymbolCapability,
)
from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2ShadowAuthorityBundleV2,
    C2ShadowCampaignRiskLockV2,
    C2ShadowDecimalSizingV2,
    C2ShadowExecutionCampaignV2,
    C2ShadowExistingRiskEvidenceV2,
    C2ShadowFinalSignalV2,
    C2ShadowGovernanceEvidenceV2,
    C2ShadowRiskReservationV2,
    CandidateC2ShadowBuildEvidenceV2,
    CandidateC2ShadowHandoffV2,
    _durable_numeric_v2,
    account_snapshot_authority_hash_v2,
    c2_shadow_existing_risk_evidence_v2,
    c2_shadow_governance_evidence_v2,
    candidate_c2_shadow_handoff_authority_material_v2,
    candidate_c2_shadow_handoff_identity_material_v2,
)
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    TradePlanCandidateV2,
    canonical_hash_v1,
    canonical_tradeplan_numeric_v2,
)
from risk.s5_campaign_risk import CampaignRiskPolicy
from tests.test_strategy_5scr_tradeplan_candidate_v2 import NOW, _solve

EXECUTOR_ID = UUID("11111111-1111-4111-8111-111111111111")


def _authority_id(prefix: str, material: object) -> str:
    return f"{prefix}:" + hashlib.sha256(canonical_hash_v1(material).encode()).hexdigest()[:32]


def _reauthorize_reservation(payload: dict[str, object]) -> C2ShadowRiskReservationV2:
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "risk_lock_id": payload["risk_lock_id"],
        "handoff_id": payload["handoff_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "executor_id": str(payload["executor_id"]),
        "account_id": payload["account_id"],
        "account_snapshot_id": payload["account_snapshot_id"],
        "account_snapshot_hash": payload["account_snapshot_hash"],
        "symbol_capability_hash": payload["symbol_capability_hash"],
        "governance_evidence_hash": payload["governance_evidence_hash"],
        "existing_risk_evidence_hash": payload["existing_risk_evidence_hash"],
        "broker_server": payload["broker_server"],
        "symbol": payload["canonical_symbol"],
        "broker_symbol": payload["broker_symbol"],
        "direction": payload["direction"],
        "volume": payload["volume"],
        "entry": payload["entry_price"],
        "stop": payload["stop_loss"],
        "target": payload["take_profit"],
        "risk_unit_usd": payload["risk_unit_usd"],
        "reserved_risk_usd": payload["reserved_risk_usd"],
        "reserved_at_utc": payload["reserved_at_utc"],
        "expires_at_utc": payload["expires_at_utc"],
    }
    payload.update(
        reservation_id=_authority_id("5scr-c2-reservation-v2", material),
        authority_hash=canonical_hash_v1(material),
    )
    return C2ShadowRiskReservationV2.model_validate(payload)


def _reauthorize_campaign(campaign: C2ShadowExecutionCampaignV2, reservation_id: str) -> C2ShadowExecutionCampaignV2:
    payload = campaign.model_dump(mode="python")
    payload["reservation_id"] = reservation_id
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "reservation_id": payload["reservation_id"],
        "account_id": payload["account_id"],
        "symbol": payload["canonical_symbol"],
        "direction": payload["direction"],
        "state": payload["state"],
        "opened_at_utc": payload["opened_at_utc"],
    }
    payload["authority_hash"] = canonical_hash_v1(material)
    return C2ShadowExecutionCampaignV2.model_validate(payload)


def _reauthorize_signal(signal: C2ShadowFinalSignalV2, reservation_id: str) -> C2ShadowFinalSignalV2:
    payload = signal.model_dump(mode="python")
    payload["reservation_id"] = reservation_id
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "reservation_id": payload["reservation_id"],
        "handoff_id": payload["handoff_id"],
        "risk_lock_id": payload["risk_lock_id"],
        "account_id": payload["account_id"],
        "executor_id": str(payload["executor_id"]),
        "broker_server": payload["broker_server"],
        "risk_snapshot_id": payload["risk_snapshot_id"],
        "account_snapshot_hash": payload["account_snapshot_hash"],
        "symbol_capability_hash": payload["symbol_capability_hash"],
        "governance_evidence_hash": payload["governance_evidence_hash"],
        "existing_risk_evidence_hash": payload["existing_risk_evidence_hash"],
        "material_candidate_hash": payload["material_candidate_hash"],
        "candidate_evidence_hash": payload["candidate_evidence_hash"],
        "symbol": payload["canonical_symbol"],
        "broker_symbol": payload["broker_symbol"],
        "direction": payload["final_direction"],
        "entry_role": payload["entry_role"],
        "entry": payload["entry_price"],
        "stop": payload["stop_loss"],
        "target": payload["take_profit"],
        "volume": payload["reserved_volume"],
        "issued_at_utc": payload["issued_at_utc"],
        "expires_at_utc": payload["expires_at_utc"],
    }
    payload.update(
        signal_id=_authority_id("5scr-signal-shadow-v2", material),
        authority_hash=canonical_hash_v1(material),
    )
    return C2ShadowFinalSignalV2.model_validate(payload)


def _candidate(direction: Literal["BUY", "SELL"]) -> TradePlanCandidateV2:
    result = _solve(direction)
    assert result.candidate is not None
    return result.candidate


def _snapshot(candidate: TradePlanCandidateV2, *, captured_at: datetime) -> AccountSnapshotV1:
    return AccountSnapshotV1(
        snapshot_id="snapshot-c2-shadow-001",
        captured_at_utc=captured_at,
        executor_id=EXECUTOR_ID,
        account_id="xm-demo-account-hash",
        currency="USD",
        balance=1000.0,
        equity=1000.0,
        floating_pnl=0.0,
        used_margin=0.0,
        free_margin=1000.0,
        margin_level_pct=None,
        margin_mode=MarginMode.HEDGING,
        trade_allowed=True,
        autotrading_enabled=True,
        open_positions=[],
        pending_orders=[],
        broker_ledger_reconciled=True,
        symbols=[
            SymbolCapability(
                canonical_symbol=candidate.symbol,
                broker_symbol="EURUSD",
                digits=candidate.broker_digits,
                point=float(candidate.broker_point),
                tick_size=float(candidate.broker_tick_size),
                tick_value_profit=1.0,
                tick_value_loss=1.0,
                volume_min=0.01,
                volume_max=50.0,
                volume_step=0.01,
                stops_level_points=0,
                freeze_level_points=0,
            )
        ],
    )


def _governance(*, decision_at: datetime, kill_switch: str = "DISENGAGED") -> C2ShadowGovernanceEvidenceV2:
    payload = {
        "executor_id": EXECUTOR_ID,
        "account_id": "xm-demo-account-hash",
        "broker_server": "XMGlobal-MT5 10",
        "executor_registered": True,
        "executor_revoked": False,
        "execution_mode": "SHADOW",
        "kill_switch_state": kill_switch,
        "verified_at_utc": decision_at,
    }
    return C2ShadowGovernanceEvidenceV2(**payload, evidence_hash=canonical_hash_v1(payload))


def _evidence(
    direction: Literal["BUY", "SELL"],
    *,
    request: str = "c2-request-1",
    kill_switch: str = "DISENGAGED",
    decision_at: datetime | None = None,
    existing_risk: C2ShadowExistingRiskEvidenceV2 | None = None,
) -> CandidateC2ShadowBuildEvidenceV2:
    candidate = _candidate(direction)
    now = decision_at or NOW + timedelta(seconds=5)
    snapshot = _snapshot(candidate, captured_at=now)
    return CandidateC2ShadowBuildEvidenceV2(
        source_request_id=request,
        decision_at_utc=now,
        expires_at_utc=now + timedelta(seconds=60),
        candidate=candidate,
        governance=_governance(decision_at=now, kill_switch=kill_switch),
        account_snapshot=snapshot,
        account_snapshot_hash=account_snapshot_authority_hash_v2(snapshot),
        existing_risk=existing_risk
        or c2_shadow_existing_risk_evidence_v2(
            account_id=snapshot.account_id,
            tradeplan_id=candidate.tradeplan_id,
            captured_at_utc=now,
        ),
        broker_symbol="EURUSD",
    )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_valid_candidate_creates_atomic_shadow_risk_authority(direction: str) -> None:
    evidence = _evidence(cast(Literal["BUY", "SELL"], direction))
    result = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)

    assert (result.decision, result.reason_code) == ("APPROVED", "C2_SHADOW_RISK_AUTHORIZED")
    assert result.evaluation is not None and result.evaluation.decision == "APPROVED"
    assert result.authority_bundle is not None
    bundle = result.authority_bundle
    assert bundle.reservation.state == "RESERVED"
    assert bundle.execution_campaign.state == "PARENT_PENDING"
    assert bundle.final_signal.is_final_signal is True
    assert bundle.final_signal.valid_for_execution is True
    assert bundle.final_signal.execution_mode == "SHADOW"
    assert bundle.final_signal.broker_execution_authority is False
    assert bundle.final_signal.command_authority is False
    assert bundle.final_signal.delivery_authority is False
    assert bundle.final_signal.next_required_stage == "C3_MANUAL_SHADOW_PROMOTION"
    assert bundle.risk_lock.risk_unit_usd == canonical_tradeplan_numeric_v2(
        bundle.risk_lock.balance_base * bundle.risk_lock.risk_percent_per_entry
    )
    assert bundle.risk_lock.max_campaign_risk_usd == bundle.risk_lock.risk_unit_usd * 2
    assert bundle.reservation.risk_unit_usd == bundle.risk_lock.risk_unit_usd
    capability = evidence.account_snapshot.symbols[0]
    effective_loss = (
        abs(bundle.reservation.entry_price - bundle.reservation.stop_loss)
        / Decimal(str(capability.tick_size))
        * Decimal(str(capability.tick_value_loss))
    )
    assert bundle.reservation.reserved_risk_usd == bundle.reservation.volume * effective_loss


@pytest.mark.parametrize(
    "policy",
    [
        CampaignRiskPolicy(risk_percent_per_entry=Decimal("0.04")),
        CampaignRiskPolicy(max_total_open_risk_percent=Decimal("0.09")),
        CampaignRiskPolicy(snapshot_max_age_seconds=29),
    ],
)
def test_noncanonical_injected_risk_policy_fails_closed_before_authority(
    policy: CampaignRiskPolicy,
) -> None:
    result = evaluate_candidate_c2_shadow_v2(
        _evidence("BUY"),
        evaluation_sequence=1,
        risk_policy=policy,
    )

    assert (result.decision, result.reason_code) == (
        "REJECTED",
        "C2_RISK_POLICY_NOT_CANONICAL",
    )
    assert result.evaluation is not None
    assert result.authority_bundle is None


def test_engaged_kill_switch_rejects_without_any_authority_rows() -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY", kill_switch="ENGAGED"), evaluation_sequence=1)

    assert (result.decision, result.reason_code) == ("REJECTED", "C2_KILL_SWITCH_ENGAGED")
    assert result.evaluation is not None
    assert result.authority_bundle is None


def test_exact_current_authority_is_duplicate_without_new_evaluation() -> None:
    evidence = _evidence("BUY")
    first = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    assert first.authority_bundle is not None

    retry = evaluate_candidate_c2_shadow_v2(
        evidence,
        evaluation_sequence=2,
        current_authority=first.authority_bundle,
    )
    assert (retry.decision, retry.reason_code) == ("DUPLICATE", "C2_AUTHORITY_ALREADY_RESERVED")
    assert retry.evaluation is None
    assert retry.authority_bundle == first.authority_bundle


def test_build_evidence_hash_binds_deployment_and_replica_provenance() -> None:
    evidence = _evidence("BUY").model_copy(
        update={
            "source_deployment_id": "p7-deployment-a",
            "source_replica_id": "p7-replica-a",
        }
    )
    deployment_drift = evidence.model_copy(update={"source_deployment_id": "p7-deployment-b"})
    replica_drift = evidence.model_copy(update={"source_replica_id": "p7-replica-b"})

    assert len({evidence.authority_hash(), deployment_drift.authority_hash(), replica_drift.authority_hash()}) == 3

    original = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    changed = evaluate_candidate_c2_shadow_v2(deployment_drift, evaluation_sequence=1)
    assert original.evaluation is not None and changed.evaluation is not None
    assert original.evaluation.evidence_hash != changed.evaluation.evidence_hash
    assert original.evaluation.evaluation_id != changed.evaluation.evaluation_id


def test_mutated_nested_account_snapshot_cannot_rebind_risk_under_stale_hash() -> None:
    evidence = _evidence("BUY")
    original_hash = evidence.account_snapshot_hash
    evidence.account_snapshot.balance = 2000.0
    evidence.account_snapshot.equity = 2000.0
    evidence.account_snapshot.free_margin = 2000.0

    assert account_snapshot_authority_hash_v2(evidence.account_snapshot) != original_hash
    result = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.evaluation, result.authority_bundle) == (
        "QUARANTINED",
        "C2_ACCOUNT_SNAPSHOT_HASH_DRIFT",
        None,
        None,
    )


def test_mutated_nested_capability_cannot_rebind_sizing_under_stale_hash() -> None:
    evidence = _evidence("BUY")
    evidence.account_snapshot.symbols[0].volume_max = 500.0

    result = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.evaluation, result.authority_bundle) == (
        "QUARANTINED",
        "C2_ACCOUNT_SNAPSHOT_HASH_DRIFT",
        None,
        None,
    )


@pytest.mark.parametrize("nested_authority", ["governance", "existing_risk"])
def test_forged_nested_hashed_authority_is_deeply_revalidated(nested_authority: str) -> None:
    evidence = _evidence("BUY")
    if nested_authority == "governance":
        forged = evidence.governance.model_copy(update={"broker_server": "forged-server"})
    else:
        forged = evidence.existing_risk.model_copy(update={"active_reservation_count": 1})
    changed = evidence.model_copy(update={nested_authority: forged})

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.evaluation, result.authority_bundle) == (
        "QUARANTINED",
        "C2_BUILD_EVIDENCE_INTEGRITY_INVALID",
        None,
        None,
    )


@pytest.mark.parametrize("drift", ["target", "stop", "material_hash"])
def test_forged_nested_candidate_authority_is_deeply_revalidated(drift: str) -> None:
    evidence = _evidence("BUY")
    candidate = evidence.candidate
    if drift == "target":
        forged_target = candidate.target_authority.model_copy(
            update={"target_price": candidate.target_authority.target_price + candidate.broker_tick_size}
        )
        forged_candidate = candidate.model_copy(update={"target_authority": forged_target})
    elif drift == "stop":
        forged_stop = candidate.stop_authority.model_copy(
            update={
                "structural_stop_price": candidate.stop_authority.structural_stop_price - candidate.broker_tick_size
            }
        )
        forged_candidate = candidate.model_copy(update={"stop_authority": forged_stop})
    else:
        forged_candidate = candidate.model_copy(update={"material_candidate_hash": "sha256:" + "0" * 64})
    changed = evidence.model_copy(update={"candidate": forged_candidate})

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.evaluation, result.authority_bundle) == (
        "QUARANTINED",
        "C2_BUILD_EVIDENCE_INTEGRITY_INVALID",
        None,
        None,
    )


def test_handoff_occurrence_id_is_stable_but_authority_hash_binds_admission_observation() -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    assert result.authority_bundle is not None
    original = result.authority_bundle.handoff
    payload = original.model_dump(mode="python")
    payload.update(
        account_snapshot_id="account-snapshot-retry",
        account_snapshot_hash="sha256:" + "a" * 64,
        symbol_capability_hash="sha256:" + "b" * 64,
        governance_evidence_hash="sha256:" + "c" * 64,
        existing_risk_evidence_hash="sha256:" + "d" * 64,
        accepted_at_utc=original.accepted_at_utc + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="handoff authority integrity mismatch"):
        CandidateC2ShadowHandoffV2.model_validate(payload)

    payload["authority_hash"] = canonical_hash_v1(candidate_c2_shadow_handoff_authority_material_v2(payload))
    changed = CandidateC2ShadowHandoffV2.model_validate(payload)
    assert changed.handoff_id == original.handoff_id
    assert changed.authority_hash != original.authority_hash


def test_reauthorized_handoff_lineage_drift_changes_identity_and_never_duplicates() -> None:
    evidence = _evidence("BUY")
    result = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    assert result.authority_bundle is not None
    bundle = result.authority_bundle
    payload = bundle.handoff.model_dump(mode="python")
    payload["material_context_hash"] = "sha256:" + "f" * 64
    payload["handoff_id"] = _authority_id(
        "5scr-c2-handoff-v2", candidate_c2_shadow_handoff_identity_material_v2(payload)
    )
    payload["authority_hash"] = canonical_hash_v1(candidate_c2_shadow_handoff_authority_material_v2(payload))
    forged_handoff = CandidateC2ShadowHandoffV2.model_validate(payload)
    assert forged_handoff.handoff_id != bundle.handoff.handoff_id
    assert forged_handoff.authority_hash != bundle.handoff.authority_hash

    # model_copy is intentionally able to bypass validation; the evaluator
    # must still revalidate the complete nested authority before DUPLICATE.
    forged_bundle = bundle.model_copy(update={"handoff": forged_handoff})
    retry = evaluate_candidate_c2_shadow_v2(
        evidence,
        evaluation_sequence=2,
        current_authority=forged_bundle,
    )
    assert (retry.decision, retry.reason_code) == (
        "QUARANTINED",
        "C2_CURRENT_AUTHORITY_INTEGRITY_INVALID",
    )


def test_unvalidated_handoff_model_copy_drift_never_reaches_duplicate_fast_path() -> None:
    evidence = _evidence("SELL")
    result = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    assert result.authority_bundle is not None
    bundle = result.authority_bundle
    forged_handoff = bundle.handoff.model_copy(update={"execution_box_freeze_authority_hash": "sha256:" + "0" * 64})
    forged_bundle = bundle.model_copy(update={"handoff": forged_handoff})

    retry = evaluate_candidate_c2_shadow_v2(
        evidence,
        evaluation_sequence=2,
        current_authority=forged_bundle,
    )
    assert (retry.decision, retry.reason_code) == (
        "QUARANTINED",
        "C2_CURRENT_AUTHORITY_INTEGRITY_INVALID",
    )


@pytest.mark.parametrize(
    ("snapshot_change", "expected_reason"),
    [
        ({"broker_ledger_reconciled": False}, "C2_BROKER_LEDGER_NOT_RECONCILED"),
        (
            {
                "pending_orders": [
                    OpenBrokerOrder(
                        order_ticket=123,
                        symbol="EURUSD",
                        order_type="BUY_LIMIT",
                        volume=0.01,
                        requested_price=1.099,
                        magic=150015,
                    )
                ]
            },
            "C2_PARENT_REQUIRES_NO_PENDING_ORDERS",
        ),
        (
            {
                "open_positions": [
                    OpenBrokerPosition(
                        position_id=456,
                        symbol="EURUSD",
                        side="BUY",
                        volume=0.01,
                        entry_price=1.1,
                        current_price=1.101,
                        magic=150015,
                        floating_pnl=1.0,
                    )
                ]
            },
            "C2_PARENT_REQUIRES_FLAT_ACCOUNT",
        ),
    ],
)
def test_current_authority_cannot_bypass_live_broker_ledger_gates(
    snapshot_change: dict[str, object], expected_reason: str
) -> None:
    evidence = _evidence("BUY")
    first = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    assert first.authority_bundle is not None

    snapshot = evidence.account_snapshot.model_copy(update=snapshot_change)
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )
    retry = evaluate_candidate_c2_shadow_v2(
        changed,
        evaluation_sequence=2,
        current_authority=first.authority_bundle,
    )

    assert retry.decision == "REJECTED"
    assert retry.reason_code == expected_reason
    assert retry.decision != "DUPLICATE"
    assert retry.authority_bundle is None


def test_current_authority_cannot_bypass_snapshot_freshness_or_expiry() -> None:
    evidence = _evidence("BUY")
    first = evaluate_candidate_c2_shadow_v2(evidence, evaluation_sequence=1)
    assert first.authority_bundle is not None

    stale_snapshot = evidence.account_snapshot.model_copy(
        update={"captured_at_utc": evidence.decision_at_utc - timedelta(seconds=31)}
    )
    stale = evidence.model_copy(
        update={
            "account_snapshot": stale_snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(stale_snapshot),
        }
    )
    stale_result = evaluate_candidate_c2_shadow_v2(
        stale,
        evaluation_sequence=2,
        current_authority=first.authority_bundle,
    )
    assert (stale_result.decision, stale_result.reason_code) == (
        "REJECTED",
        "C2_ACCOUNT_SNAPSHOT_STALE",
    )

    expired_at = first.authority_bundle.reservation.expires_at_utc
    expired = _evidence("BUY", request="c2-expired", decision_at=expired_at)
    expired_result = evaluate_candidate_c2_shadow_v2(
        expired,
        evaluation_sequence=2,
        current_authority=first.authority_bundle,
    )
    assert (expired_result.decision, expired_result.reason_code) == (
        "REJECTED",
        "C2_AUTHORITY_EXPIRED",
    )


def test_stale_candidate_and_nonflat_risk_fail_closed() -> None:
    stale = evaluate_candidate_c2_shadow_v2(
        _evidence("BUY", decision_at=NOW + timedelta(seconds=121)), evaluation_sequence=1
    )
    assert (stale.decision, stale.reason_code) == ("REJECTED", "C2_CANDIDATE_STALE")

    candidate = _candidate("BUY")
    now = NOW + timedelta(seconds=5)
    payload = {
        "account_id": "xm-demo-account-hash",
        "tradeplan_id": candidate.tradeplan_id,
        "active_campaign_count": 1,
        "active_reservation_count": 0,
        "pending_order_count": 0,
        "broker_ledger_reconciled": True,
        "committed_or_reserved_campaign_risk_usd": "0",
        "account_total_open_risk_usd": "0",
        "captured_at_utc": now,
    }
    nonflat = C2ShadowExistingRiskEvidenceV2(**payload, evidence_hash=canonical_hash_v1(payload))
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY", existing_risk=nonflat), evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", "C2_EXISTING_RISK_NOT_FLAT")
    assert result.authority_bundle is None


def test_helpers_build_only_disengaged_zero_risk_evidence() -> None:
    governance = c2_shadow_governance_evidence_v2(
        executor_id=EXECUTOR_ID,
        account_id="xm-demo-account-hash",
        broker_server="XMGlobal-MT5 10",
        verified_at_utc=NOW,
    )
    assert governance.kill_switch_state == "DISENGAGED"
    assert governance.execution_mode == "SHADOW"


@pytest.mark.parametrize(
    ("kill_switch", "mode", "expected"),
    [
        ("ENGAGED", "SHADOW", "C2_KILL_SWITCH_ENGAGED"),
        ("DISENGAGED", "DEMO", "C2_EXECUTOR_MODE_NOT_SHADOW"),
        ("DISENGAGED", "LIVE", "C2_EXECUTOR_MODE_NOT_SHADOW"),
    ],
)
def test_governance_authority_fails_closed(kill_switch: str, mode: str, expected: str) -> None:
    evidence = _evidence("BUY", kill_switch=kill_switch)
    governance_payload = evidence.governance.model_dump(mode="python")
    governance_payload.update(execution_mode=mode)
    hash_payload = {
        key: value for key, value in governance_payload.items() if key not in {"evidence_hash", "execution_authority"}
    }
    governance_payload["evidence_hash"] = canonical_hash_v1(hash_payload)
    changed = evidence.model_copy(
        update={"governance": C2ShadowGovernanceEvidenceV2.model_validate(governance_payload)}
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", expected)
    assert result.authority_bundle is None


def test_symbol_capability_drift_and_existing_risk_clock_fail_closed() -> None:
    evidence = _evidence("BUY")
    snapshot_payload = evidence.account_snapshot.model_dump(mode="python")
    snapshot_payload["symbols"][0]["tick_size"] = 0.0001
    snapshot = AccountSnapshotV1.model_validate(snapshot_payload)
    drifted = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )
    result = evaluate_candidate_c2_shadow_v2(drifted, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", "C2_BROKER_GEOMETRY_DRIFT")

    risk_payload = evidence.existing_risk.model_dump(mode="python")
    risk_payload["captured_at_utc"] = evidence.decision_at_utc + timedelta(seconds=1)
    hash_payload = {
        key: value for key, value in risk_payload.items() if key not in {"evidence_hash", "execution_authority"}
    }
    risk_payload["evidence_hash"] = canonical_hash_v1(hash_payload)
    future = evidence.model_copy(update={"existing_risk": C2ShadowExistingRiskEvidenceV2.model_validate(risk_payload)})
    result = evaluate_candidate_c2_shadow_v2(future, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", "C2_EXISTING_RISK_FROM_FUTURE")


def test_authority_bundle_rejects_crossmixed_reservation() -> None:
    buy = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    sell = evaluate_candidate_c2_shadow_v2(_evidence("SELL", request="sell"), evaluation_sequence=1)
    assert buy.authority_bundle is not None and sell.authority_bundle is not None
    payload = buy.authority_bundle.model_dump(mode="python")
    payload["reservation"] = deepcopy(sell.authority_bundle.reservation.model_dump(mode="python"))

    with pytest.raises(ValueError, match="scope mismatch"):
        type(buy.authority_bundle).model_validate(payload)


@pytest.mark.parametrize(
    ("risk_unit_delta", "campaign_cap_delta", "error"),
    [
        (Decimal("1"), Decimal("2"), "risk unit must equal closed balance"),
        (Decimal("0"), Decimal("1"), "two-R campaign cap"),
    ],
)
def test_cryptographically_coherent_forged_risk_lock_units_fail_closed(
    risk_unit_delta: Decimal, campaign_cap_delta: Decimal, error: str
) -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    assert result.authority_bundle is not None
    payload = result.authority_bundle.risk_lock.model_dump(mode="python")
    payload["risk_unit_usd"] += risk_unit_delta
    payload["max_campaign_risk_usd"] += campaign_cap_delta
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "account_id": payload["account_id"],
        "account_snapshot_id": payload["account_snapshot_id"],
        "balance_base": payload["balance_base"],
        "risk_percent_per_entry": payload["risk_percent_per_entry"],
        "risk_unit_usd": payload["risk_unit_usd"],
        "max_campaign_risk_usd": payload["max_campaign_risk_usd"],
        "locked_at_utc": payload["locked_at_utc"],
        "policy_id": payload["policy_id"],
    }
    payload.update(
        risk_lock_id=_authority_id("5scr-c2-risk-lock-v2", material),
        authority_hash=canonical_hash_v1(material),
    )

    with pytest.raises(ValueError, match=error):
        C2ShadowCampaignRiskLockV2.model_validate(payload)


def test_cryptographically_coherent_noncanonical_risk_percent_fails_closed() -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    assert result.authority_bundle is not None
    payload = result.authority_bundle.risk_lock.model_dump(mode="python")
    payload["risk_percent_per_entry"] = canonical_tradeplan_numeric_v2(Decimal("0.04"))
    payload["risk_unit_usd"] = canonical_tradeplan_numeric_v2(
        cast(Decimal, payload["balance_base"]) * cast(Decimal, payload["risk_percent_per_entry"])
    )
    payload["max_campaign_risk_usd"] = canonical_tradeplan_numeric_v2(cast(Decimal, payload["risk_unit_usd"]) * 2)
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "account_id": payload["account_id"],
        "account_snapshot_id": payload["account_snapshot_id"],
        "balance_base": payload["balance_base"],
        "risk_percent_per_entry": payload["risk_percent_per_entry"],
        "risk_unit_usd": payload["risk_unit_usd"],
        "max_campaign_risk_usd": payload["max_campaign_risk_usd"],
        "locked_at_utc": payload["locked_at_utc"],
        "policy_id": payload["policy_id"],
    }
    payload.update(
        risk_lock_id=_authority_id("5scr-c2-risk-lock-v2", material),
        authority_hash=canonical_hash_v1(material),
    )

    with pytest.raises(ValueError, match="canonical 5% fractional"):
        C2ShadowCampaignRiskLockV2.model_validate(payload)


def test_cryptographically_coherent_reservation_budget_cannot_escape_risk_lock() -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    assert result.authority_bundle is not None
    bundle = result.authority_bundle
    payload = bundle.reservation.model_dump(mode="python")
    payload["risk_unit_usd"] = bundle.risk_lock.risk_unit_usd + Decimal("1")
    forged_reservation = _reauthorize_reservation(payload)
    forged_campaign = _reauthorize_campaign(bundle.execution_campaign, forged_reservation.reservation_id)
    forged_signal = _reauthorize_signal(bundle.final_signal, forged_reservation.reservation_id)

    with pytest.raises(ValueError, match="reservation/risk-lock budget mismatch"):
        C2ShadowAuthorityBundleV2(
            handoff=bundle.handoff,
            risk_lock=bundle.risk_lock,
            reservation=forged_reservation,
            execution_campaign=forged_campaign,
            final_signal=forged_signal,
        )


def test_risk_lock_contract_rejects_rounded_balance_policy_product() -> None:
    result = evaluate_candidate_c2_shadow_v2(_evidence("BUY"), evaluation_sequence=1)
    assert result.authority_bundle is not None
    payload = result.authority_bundle.risk_lock.model_dump(mode="python")
    payload["balance_base"] = Decimal("1000.123456789012")
    payload["risk_unit_usd"] = canonical_tradeplan_numeric_v2(
        cast(Decimal, payload["balance_base"]) * cast(Decimal, payload["risk_percent_per_entry"])
    )
    payload["max_campaign_risk_usd"] = canonical_tradeplan_numeric_v2(cast(Decimal, payload["risk_unit_usd"]) * 2)
    material = {
        "execution_campaign_id": payload["execution_campaign_id"],
        "tradeplan_id": payload["tradeplan_id"],
        "account_id": payload["account_id"],
        "account_snapshot_id": payload["account_snapshot_id"],
        "balance_base": payload["balance_base"],
        "risk_percent_per_entry": payload["risk_percent_per_entry"],
        "risk_unit_usd": payload["risk_unit_usd"],
        "max_campaign_risk_usd": payload["max_campaign_risk_usd"],
        "locked_at_utc": payload["locked_at_utc"],
        "policy_id": payload["policy_id"],
    }
    payload.update(
        risk_lock_id=_authority_id("5scr-c2-risk-lock-v2", material),
        authority_hash=canonical_hash_v1(material),
    )

    with pytest.raises(ValueError, match="not exactly representable"):
        C2ShadowCampaignRiskLockV2.model_validate(payload)


def test_approved_decimal_sizing_rejects_forged_volume_loss_relation() -> None:
    with pytest.raises(ValueError, match="exact volume-derived one-R loss"):
        C2ShadowDecimalSizingV2(
            allowed=True,
            reason_code="C2_RISK_APPROVED_PARENT",
            risk_unit_usd=Decimal("50"),
            effective_loss_per_lot=Decimal("87"),
            raw_volume=Decimal("0.57"),
            final_volume=Decimal("0.57"),
            actual_planned_risk_usd=Decimal("49.58"),
        )


def test_high_precision_closed_balance_rejects_before_risk_authority() -> None:
    evidence = _evidence("BUY")
    high_precision_balance = 1000.1234567890123
    snapshot = evidence.account_snapshot.model_copy(
        update={
            "balance": high_precision_balance,
            "equity": high_precision_balance,
            "free_margin": high_precision_balance,
        }
    )
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code, result.authority_bundle) == (
        "REJECTED",
        "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
        None,
    )


def test_numeric_28_12_boundary_is_exact_and_overflow_is_a_value_error() -> None:
    maximum = Decimal("9999999999999999.999999999999")
    assert _durable_numeric_v2(maximum, "boundary") == maximum
    with pytest.raises(ValueError, match=r"NUMERIC\(28,12\)"):
        _durable_numeric_v2(Decimal("10000000000000000"), "overflow")


def test_closed_balance_numeric_overflow_rejects_without_decimal_exception() -> None:
    evidence = _evidence("BUY")
    snapshot = evidence.account_snapshot.model_copy(
        update={
            "balance": 1e16,
            "equity": 1e16,
            "free_margin": 1e16,
        }
    )
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code, result.authority_bundle) == (
        "REJECTED",
        "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
        None,
    )


def test_oversized_candidate_geometry_rejects_without_decimal_exception() -> None:
    evidence = _evidence("BUY")
    forged_candidate = evidence.candidate.model_copy(update={"candidate_price": Decimal("1e16")})
    changed = evidence.model_copy(update={"candidate": forged_candidate})

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code, result.authority_bundle) == (
        "REJECTED",
        "C2_AUTHORITY_NUMERIC_GRID_UNREPRESENTABLE",
        None,
    )


def test_forged_candidate_price_type_quarantines_without_numeric_exception() -> None:
    evidence = _evidence("BUY")
    forged_candidate = evidence.candidate.model_copy(update={"candidate_price": "not-a-decimal"})
    changed = evidence.model_copy(update={"candidate": forged_candidate})

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.evaluation, result.authority_bundle) == (
        "QUARANTINED",
        "C2_BUILD_EVIDENCE_INTEGRITY_INVALID",
        None,
        None,
    )


def test_oversized_capability_derived_volume_rejects_without_decimal_exception() -> None:
    evidence = _evidence("BUY")
    capability = evidence.account_snapshot.symbols[0].model_copy(update={"tick_value_loss": 1e-20, "volume_max": 1e100})
    snapshot = evidence.account_snapshot.model_copy(update={"symbols": [capability]})
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code, result.authority_bundle) == (
        "REJECTED",
        "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
        None,
    )


def test_unrepresentable_high_precision_capability_fails_before_authority() -> None:
    evidence = _evidence("BUY")
    capability = evidence.account_snapshot.symbols[0].model_copy(update={"volume_step": 0.0100000000001})
    snapshot = evidence.account_snapshot.model_copy(update={"symbols": [capability]})
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == (
        "REJECTED",
        "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
    )
    assert result.authority_bundle is None


@pytest.mark.parametrize(
    "field_name",
    [
        "point",
        "tick_size",
        "tick_value_loss",
        "volume_min",
        "volume_max",
        "volume_step",
        "stops_level_points",
        "freeze_level_points",
    ],
)
@pytest.mark.parametrize(
    "unrepresentable",
    [float("nan"), float("inf"), float("-inf"), 1e16],
    ids=["nan", "positive-infinity", "negative-infinity", "numeric-28-12-overflow"],
)
def test_unrepresentable_capability_numbers_fail_closed(
    field_name: str,
    unrepresentable: float,
) -> None:
    evidence = _evidence("BUY")
    capability = evidence.account_snapshot.symbols[0].model_copy(update={field_name: unrepresentable})
    snapshot = evidence.account_snapshot.model_copy(update={"symbols": [capability]})
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            # `model_copy` deliberately forges otherwise impossible typed
            # values; suppress only Pydantic's expected-type serializer noise.
            "account_snapshot_hash": canonical_hash_v1(snapshot.model_dump(mode="json", warnings=False)),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)

    assert (result.decision, result.reason_code, result.authority_bundle) == (
        "REJECTED",
        "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
        None,
    )


def test_non_usd_account_requires_explicit_conversion_authority() -> None:
    evidence = _evidence("BUY")
    snapshot = evidence.account_snapshot.model_copy(update={"currency": "EUR"})
    changed = evidence.model_copy(
        update={
            "account_snapshot": snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
        }
    )

    result = evaluate_candidate_c2_shadow_v2(changed, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == (
        "REJECTED",
        "C2_ACCOUNT_CURRENCY_UNSUPPORTED",
    )
    assert result.authority_bundle is None


def test_snapshot_broker_ledger_attestation_and_pending_orders_fail_closed() -> None:
    evidence = _evidence("BUY")
    unreconciled_snapshot = evidence.account_snapshot.model_copy(update={"broker_ledger_reconciled": False})
    unreconciled = evidence.model_copy(
        update={
            "account_snapshot": unreconciled_snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(unreconciled_snapshot),
        }
    )
    result = evaluate_candidate_c2_shadow_v2(unreconciled, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", "C2_BROKER_LEDGER_NOT_RECONCILED")

    pending_payload = evidence.account_snapshot.model_dump(mode="python")
    pending_payload["pending_orders"] = [
        {
            "order_ticket": 123,
            "symbol": "EURUSD",
            "order_type": "BUY_LIMIT",
            "volume": 0.01,
            "requested_price": 1.099,
            "magic": 150015,
        }
    ]
    pending_snapshot = AccountSnapshotV1.model_validate(pending_payload)
    pending = evidence.model_copy(
        update={
            "account_snapshot": pending_snapshot,
            "account_snapshot_hash": account_snapshot_authority_hash_v2(pending_snapshot),
        }
    )
    result = evaluate_candidate_c2_shadow_v2(pending, evaluation_sequence=1)
    assert (result.decision, result.reason_code) == ("REJECTED", "C2_PARENT_REQUIRES_NO_PENDING_ORDERS")


def test_decimal_sizing_floors_to_step_and_never_exceeds_one_r() -> None:
    result = size_c2_shadow_parent_decimal_v2(
        risk_unit_usd=Decimal("50"),
        entry_price=Decimal("1.10000"),
        stop_loss=Decimal("1.09913"),
        tick_size=Decimal("0.00001"),
        tick_value_loss=Decimal("1"),
        volume_min=Decimal("0.01"),
        volume_max=Decimal("50"),
        volume_step=Decimal("0.01"),
    )
    assert result.allowed is True
    assert result.raw_volume == Decimal("50") / Decimal("87")
    assert result.final_volume == Decimal("0.57")
    assert result.actual_planned_risk_usd == Decimal("49.59")
    assert result.actual_planned_risk_usd <= result.risk_unit_usd


@pytest.mark.parametrize(
    ("risk", "minimum", "maximum", "reason"),
    [
        ("0.50", "0.01", "50", "C2_RISK_VOLUME_BELOW_MINIMUM"),
        ("5000", "0.01", "1", "C2_RISK_VOLUME_ABOVE_MAXIMUM"),
    ],
)
def test_decimal_sizing_minimum_and_maximum_boundaries(risk: str, minimum: str, maximum: str, reason: str) -> None:
    result = size_c2_shadow_parent_decimal_v2(
        risk_unit_usd=Decimal(risk),
        entry_price=Decimal("1.10000"),
        stop_loss=Decimal("1.09900"),
        tick_size=Decimal("0.00001"),
        tick_value_loss=Decimal("1"),
        volume_min=Decimal(minimum),
        volume_max=Decimal(maximum),
        volume_step=Decimal("0.01"),
    )
    assert result.allowed is False
    assert result.reason_code == reason
