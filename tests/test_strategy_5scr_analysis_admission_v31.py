"""S1B-1 acceptance: StrategyAnalysisAdmissionV31 (implements SSOT v3.1 §7A.4), both classes, hard containment."""

from __future__ import annotations

import ast
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_analysis_admission_v31 import (
    classify_advisory_maturity_v31,
    evaluate_canonical_raw_admission_v31,
    evaluate_mature_advisory_admission_v31,
)
from contracts.strategy_5scr_analysis_admission_v31 import (
    AdvisoryMaturityTierV31,
    AdvisoryPressureEvidenceV31,
    AdvisoryPressureMaturityPolicyV31,
    StrategyAnalysisAdmissionPolicyV31,
    StrategyAnalysisAdmissionV31,
)
from contracts.strategy_5scr_market_episode_v31 import canonical_sha256_v31
from tests.test_strategy_5scr_market_episode_v31 import _event, _reduce
from tests.test_strategy_5scr_pair_admission_coverage_v31 import W1, _classify, _evaluation, _observation

ROOT = Path(__file__).resolve().parents[1]
AT = W1 + timedelta(minutes=1)


def _hashed(model_type: Any, hash_field: str, **values: Any) -> Any:
    probe = model_type.model_construct(**{**values, hash_field: "sha256:" + "0" * 64})
    body = {k: v for k, v in probe.model_dump(mode="json").items() if k != hash_field}
    return model_type.model_validate({**values, hash_field: canonical_sha256_v31(body)})


def _tier(status: str, scale: float) -> AdvisoryMaturityTierV31:
    return AdvisoryMaturityTierV31(
        status=status,  # type: ignore[arg-type]
        min_duration_seconds=300 * scale,
        min_effective_events=3 * int(scale),
        min_pulse_count=1,
        min_direction_persistence=0.8,
        min_continuity_quality=0.7,
        min_source_quality=0.5,
    )


MATURITY = _hashed(
    AdvisoryPressureMaturityPolicyV31,
    "policy_hash",
    policy_version="test-advisory-maturity.v1",
    admissible_source_families=("CANARY", "DERIVED_PRESSURE"),
    tiers=(_tier("MATURE", 1), _tier("EXTREME", 6)),
)
ADMISSION = _hashed(
    StrategyAnalysisAdmissionPolicyV31,
    "policy_hash",
    policy_version="test-analysis-admission.v1",
    canonical_admission_ttl_seconds=3600,
    advisory_analysis_ttl_seconds=1800,
)


def _require(value: Any) -> Any:
    assert value is not None
    return value


def _episode(symbol: str = "EURUSD"):
    reduction = _reduce([_event(0, 0, symbol=symbol), _event(1, 60, symbol=symbol)])
    ((episode_id, episode),) = reduction.episodes.items()
    return episode, reduction.states[episode_id]


def _evidence(episode, **overrides: Any) -> AdvisoryPressureEvidenceV31:
    values: dict[str, Any] = {
        "canonical_symbol": episode.canonical_symbol,
        "market_episode_id": episode.market_episode_id,
        "source_event_ids": ("c-1", "c-2", "c-3"),
        "source_family": "CANARY",
        "source_authority_class": "DERIVED_PRESSURE_ADVISORY",
        "pressure_direction": "BUY",
        "direction_lineage_alignment": "ALIGNED",
        "duration_seconds": 600.0,
        "effective_events": 5,
        "pulse_count": 2,
        "direction_persistence": 0.9,
        "continuity_quality": 0.9,
        "source_quality": 0.9,
        "density_bucket": "MEDIUM",
        "evidence_coverage_sufficient": True,
        "eligible_for_context_resolution": True,
        "observed_from": W1 - timedelta(minutes=10),
        "observed_until": W1,
        "pressure_valid_until": W1 + timedelta(hours=1),
        **overrides,
    }
    return _hashed(AdvisoryPressureEvidenceV31, "evidence_hash", **values)


def _canonical(
    episode: Any = None,
    state: Any = None,
    *,
    coverage: Any = None,
    evaluation: Any = None,
    direction: Any = "BUY",
    alignment: Any = "ALIGNED",
    policy: Any = ADMISSION,
    at=AT,
):
    if episode is None:
        episode, state = _episode()
    evaluation = evaluation or _evaluation()
    return evaluate_canonical_raw_admission_v31(
        episode=episode,
        episode_state=state,
        coverage=coverage or _require(_classify(evaluation=evaluation).coverage),
        evaluation=evaluation,
        pressure_direction=direction,
        direction_lineage_alignment=alignment,
        direction_evidence_hash="sha256:" + hashlib.sha256(b"raw-direction").hexdigest(),
        policy=policy,
        decision_at=at,
    )


def _advisory(
    episode: Any = None,
    state: Any = None,
    *,
    coverage: Any = None,
    maturity: Any = MATURITY,
    policy: Any = ADMISSION,
    at=AT,
    **evidence: Any,
):
    if episode is None:
        episode, state = _episode()
    return evaluate_mature_advisory_admission_v31(
        episode=episode,
        episode_state=state,
        coverage=coverage or _require(_classify(_observation(block=None), maturity="MATURE").coverage),
        evidence=_evidence(episode, **evidence),
        maturity_policy=maturity,
        policy=policy,
        decision_at=at,
    )


def test_canonical_raw_is_granted_only_from_an_evaluated_granted_pair_admission():
    decision = _canonical()
    admission = decision.admission
    assert admission is not None and decision.reason_code == "STRATEGY_ANALYSIS_ADMISSION_CANONICAL_RAW_GRANTED"
    assert (admission.admission_class, admission.admission_status) == ("CANONICAL_RAW", "GRANTED")
    assert (admission.analysis_authority, admission.source_authority, admission.promotion_eligibility) == (
        "FULL_CANONICAL_ANALYSIS",
        "RAW_SIGNALTHROTTLE_LEDGER",
        "CANONICAL_RISK_PATH",
    )
    assert admission.pair_admission_evaluation_id is not None and admission.pair_admission_coverage_id is not None
    assert (admission.risk_authority, admission.execution_authority) == (False, False)
    assert admission.expires_at_utc == AT + timedelta(seconds=3600)


def test_canonical_raw_requires_coverage_evaluation_grant_alignment_and_policy():
    rejected = _evaluation(decision="REJECTED")
    assert _canonical(evaluation=rejected).reason_code == "PAIR_ADMISSION_NOT_GRANTED"
    not_applicable = _classify(_observation(block=None)).coverage
    assert _canonical(coverage=not_applicable).reason_code == "PAIR_ADMISSION_COVERAGE_NOT_EVALUATED"
    other = _evaluation(admission_evaluation_id=__import__("uuid").UUID(int=7))
    assert _canonical(coverage=_classify(evaluation=_evaluation()).coverage, evaluation=other).reason_code == (
        "COVERAGE_EVALUATION_MISMATCH"
    )
    assert _canonical(policy=None).reason_code == "STRATEGY_ANALYSIS_ADMISSION_POLICY_MISSING"
    assert _canonical(at=W1 - timedelta(seconds=1)).reason_code == "FUTURE_LEAKAGE_BLOCK"
    gbp_episode, gbp_state = _episode("GBPUSD")
    assert _canonical(gbp_episode, gbp_state).reason_code == "SYMBOL_SCOPE_MISMATCH"
    suspended = _canonical(direction="CONFLICT", alignment="CONFLICT").admission
    assert suspended is not None and suspended.admission_status == "SUSPENDED"
    assert (suspended.context_resolution_allowed, suspended.tradeplan_candidate_allowed) == (False, False)


@pytest.mark.parametrize("status", ["NOT_APPLICABLE", "INDETERMINATE"])
def test_mature_advisory_needs_no_pair_admission_and_is_hard_contained(status):
    coverage = (
        _classify(_observation(block=None), maturity="MATURE").coverage
        if status == "NOT_APPLICABLE"
        else _classify(_observation("UNKNOWN", block=None), maturity="MATURE").coverage
    )
    admission = _advisory(coverage=coverage).admission
    assert admission is not None and admission.admission_status == "GRANTED"
    assert admission.reason_code == "STRATEGY_ANALYSIS_ADMISSION_MATURE_ADVISORY_GRANTED"
    assert admission.pair_admission_evaluation_id is None  # no fabricated PairAdmission
    assert (admission.analysis_authority, admission.source_authority, admission.promotion_eligibility) == (
        "FULL_SHADOW_ANALYSIS",
        "DERIVED_PRESSURE_ADVISORY",
        "SHADOW_ONLY",
    )
    assert admission.tradeplan_candidate_allowed is True  # SHADOW_ONLY candidate per §7A.2
    assert (
        admission.risk_authority,
        admission.execution_authority,
        admission.final_signal_allowed,
        admission.execution_command_allowed,
        admission.broker_side_effect_allowed,
    ) == (False, False, False, False, False)
    assert admission.advisory_maturity_policy_version == MATURITY.policy_version
    assert admission.expires_at_utc == AT + timedelta(seconds=1800)


@pytest.mark.parametrize(
    "overrides,status,reason",
    [
        ({"source_family": "MICROBOOST_DERIVED"}, "REJECTED", "ADVISORY_SOURCE_FAMILY_NOT_ADMISSIBLE"),
        (
            {"direction_lineage_alignment": "CONFLICT", "pressure_direction": "CONFLICT"},
            "SUSPENDED",
            "ADVISORY_DIRECTION_LINEAGE_CONFLICT",
        ),
        ({"pressure_valid_until": AT}, "REJECTED", "ADVISORY_PRESSURE_EXPIRED"),
        (
            {"pressure_direction": "INCOMPLETE", "direction_lineage_alignment": "UNAVAILABLE"},
            "SUSPENDED",
            "STRATEGY_ANALYSIS_ADMISSION_SUSPENDED",
        ),
        ({"evidence_coverage_sufficient": False}, "REJECTED", "ADVISORY_EVIDENCE_COVERAGE_INSUFFICIENT"),
        ({"eligible_for_context_resolution": False}, "REJECTED", "ADVISORY_CONTEXT_RESOLUTION_INELIGIBLE"),
        ({"duration_seconds": 100.0}, "REJECTED", "ADVISORY_PRESSURE_IMMATURE"),
    ],
)
def test_mature_advisory_rejections_carry_explicit_reason_codes(overrides, status, reason):
    admission = _advisory(**overrides).admission
    assert admission is not None and (admission.admission_status, admission.reason_code) == (status, reason)
    assert (admission.granted_at_utc, admission.tradeplan_candidate_allowed) == (None, False)


def test_maturity_comes_only_from_the_hashed_policy():
    episode, _ = _episode()
    assert classify_advisory_maturity_v31(_evidence(episode), MATURITY) == "MATURE"
    extreme = _evidence(episode, duration_seconds=1800.0, effective_events=18)
    assert classify_advisory_maturity_v31(extreme, MATURITY) == "EXTREME"
    assert _advisory(maturity=None).reason_code == "ADVISORY_MATURITY_POLICY_MISSING"
    assert _advisory(policy=None).reason_code == "STRATEGY_ANALYSIS_ADMISSION_POLICY_MISSING"
    with pytest.raises(ValidationError, match="ADVISORY_MATURITY_POLICY_HASH_MISMATCH"):
        AdvisoryPressureMaturityPolicyV31.model_validate({**MATURITY.model_dump(), "policy_version": "tampered.v1"})
    with pytest.raises(ValidationError, match="ADVISORY_EVIDENCE_HASH_MISMATCH"):
        AdvisoryPressureEvidenceV31.model_validate({**_evidence(episode).model_dump(), "effective_events": 99})


def test_two_classes_in_one_episode_are_distinct_admissions_on_the_same_lifecycle():
    episode, state = _episode()
    advisory = _advisory(episode, state).admission
    canonical = _canonical(episode, state).admission
    assert advisory is not None and canonical is not None
    assert advisory.market_episode_id == canonical.market_episode_id == episode.market_episode_id
    assert advisory.strategy_analysis_admission_id != canonical.strategy_analysis_admission_id
    # Receipts (lifecycle-bound) are covered by tests/test_strategy_5scr_admission_receipt_v31.py.


def test_admission_identity_is_stable_under_telemetry_and_moves_only_with_the_maturity_policy():
    episode, state = _episode()
    first = _advisory(episode, state).admission
    refreshed = _advisory(episode, state, at=AT + timedelta(minutes=5), effective_events=7).admission
    assert first is not None and refreshed is not None
    assert first.strategy_analysis_admission_id == refreshed.strategy_analysis_admission_id  # §4.2: 0/1 per revision
    revised = _hashed(
        AdvisoryPressureMaturityPolicyV31,
        "policy_hash",
        **{**MATURITY.model_dump(exclude={"policy_hash"}), "policy_version": "test-advisory-maturity.v2"},
    )
    moved = _advisory(episode, state, maturity=revised).admission
    assert moved is not None and moved.strategy_analysis_admission_id != first.strategy_analysis_admission_id


def test_contract_forbids_fabricated_pair_admission_and_authority_leaks():
    advisory = _advisory().admission
    canonical = _canonical().admission
    assert advisory is not None and canonical is not None
    body = advisory.model_dump()
    with pytest.raises(ValidationError, match="never carries a PairAdmission evaluation"):
        StrategyAnalysisAdmissionV31.model_validate(
            {**body, "pair_admission_evaluation_id": canonical.pair_admission_evaluation_id}
        )
    with pytest.raises(ValidationError, match="FULL_SHADOW_ANALYSIS / SHADOW_ONLY"):
        StrategyAnalysisAdmissionV31.model_validate({**body, "promotion_eligibility": "CANONICAL_RISK_PATH"})
    for field in ("risk_authority", "execution_authority", "final_signal_allowed", "broker_side_effect_allowed"):
        with pytest.raises(ValidationError):
            StrategyAnalysisAdmissionV31.model_validate({**body, field: True})
    with pytest.raises(ValidationError, match="both admission classes pass PairAdmissionCoverage first"):
        StrategyAnalysisAdmissionV31.model_validate({**body, "pair_admission_coverage_id": None})
    with pytest.raises(ValidationError, match="STRATEGY_ANALYSIS_ADMISSION_ID_NOT_DERIVED"):
        StrategyAnalysisAdmissionV31.model_validate(
            {**canonical.model_dump(), "symbol": "GBPUSD", "market_episode_id": advisory.strategy_analysis_admission_id}
        )


def test_closed_episode_admits_nothing_and_there_is_no_path_to_execution():
    reduction = _reduce([_event(0, 0), _event(1, 60, hard_structural_invalidation_evidence_id="inv-1")])
    closed = next(e for e in reduction.episodes.values() if reduction.states[e.market_episode_id].state == "CLOSED")
    assert _advisory(closed, reduction.states[closed.market_episode_id]).reason_code == "MARKET_EPISODE_CLOSED"
    forbidden = ("execution", "services.trade", "contracts.mt5_execution_protocol", "risk", "storage", "services")
    for name in (
        "contracts/strategy_5scr_analysis_admission_v31.py",
        "analysis/strategy_5scr_analysis_admission_v31.py",
    ):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any(m == p or m.startswith(p + ".") for m in imported for p in forbidden), name
