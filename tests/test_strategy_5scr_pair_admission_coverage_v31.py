"""S1B-0 acceptance: PairAdmissionCoverageV1 (owner decision S4, SSOT v3.1 §7.5–7.6, §7.12, §23.8–23.10)."""

from __future__ import annotations

import ast
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_pair_admission_coverage_v31 import classify_pair_admission_coverage_v31
from contracts.strategy_5scr_market_episode_v31 import canonical_sha256_v31
from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    PairAdmissionCoveragePolicyV31,
    PairAdmissionCoverageV1,
    PairAdmissionEvaluationRefV31,
    RawAuthorityBlockRefV31,
    RawAuthorityCoverageObservationV31,
)

ROOT = Path(__file__).resolve().parents[1]
W0 = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
W1 = W0 + timedelta(hours=1)
_BODY: dict[str, Any] = {"policy_version": "test-coverage.v1", "evaluation_sla_seconds": 120}
POLICY = PairAdmissionCoveragePolicyV31(**_BODY, policy_hash=canonical_sha256_v31(_BODY))


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _block(*, eligible: bool = True, symbol: str = "EURUSD") -> RawAuthorityBlockRefV31:
    return RawAuthorityBlockRefV31(
        raw_authority_block_id=f"{symbol}-block-1",
        canonical_symbol=symbol,
        block_started_at=W0 + timedelta(minutes=5),
        eligible=eligible,
        eligible_at=W0 + timedelta(minutes=10) if eligible else None,
        raw_lineage_hash=_digest("lineage"),
    )


def _observation(status: Any = "COMPLETE", block: Any = "eligible", symbol: str = "EURUSD"):
    resolved = _block(symbol=symbol) if block == "eligible" else block
    return RawAuthorityCoverageObservationV31(
        canonical_symbol=symbol,
        observed_window_start_utc=W0,
        observed_window_end_utc=W1,
        raw_authority_coverage_status=status,
        coverage_evidence_hash=_digest(f"coverage-{status}"),
        block=resolved,
    )


def _evaluation(*, decision: Any = "GRANTED", rule: str = "5scr.pair-admission.per-symbol-isolated.v3", **overrides):
    values: dict[str, Any] = {
        "admission_evaluation_id": UUID(int=42),
        "raw_authority_block_id": "EURUSD-block-1",
        "canonical_symbol": "EURUSD",
        "decision": decision,
        "reason_code": "PAIR_ADMISSION_GRANTED",
        "evaluated_at": W0 + timedelta(minutes=11),
        "admission_rule_version": rule,
        "evaluation_hash": _digest("evaluation"),
        **overrides,
    }
    return PairAdmissionEvaluationRefV31(**values)


def _classify(observation=None, evaluation=None, maturity: Any = "UNKNOWN", policy: Any = POLICY, as_of=W1):
    return classify_pair_admission_coverage_v31(
        observation=observation or _observation(),
        evaluation=evaluation,
        advisory_pressure_maturity=maturity,
        policy=policy,
        as_of=as_of,
    )


@pytest.mark.parametrize("status", ["INCOMPLETE", "UNKNOWN"])
@pytest.mark.parametrize("block", [None, "eligible"])
def test_incomplete_raw_coverage_is_indeterminate_never_not_applicable(status, block):
    decision = _classify(_observation(status, block), maturity="MATURE")
    coverage = decision.coverage
    assert coverage is not None
    assert coverage.admission_coverage_status == "INDETERMINATE_RAW_AUTHORITY_COVERAGE"
    assert (coverage.replay_required, coverage.incident_required) == (True, False)
    assert coverage.reason_code == "RAW_AUTHORITY_COVERAGE_INDETERMINATE"


def test_complete_coverage_without_eligible_block_is_not_applicable_even_with_mature_advisory():
    for block in (None, _block(eligible=False)):
        coverage = _classify(_observation(block=block), maturity="EXTREME").coverage
        assert coverage is not None
        assert coverage.admission_coverage_status == "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK"
        assert coverage.advisory_pressure_maturity == "EXTREME"  # recorded
        assert coverage.raw_authority_block_eligible is not True  # never implied by maturity (§7.12)
        assert (coverage.incident_required, coverage.replay_required) == (False, False)


@pytest.mark.parametrize("rule", ["5scr.pair-admission.per-symbol-isolated.v3", "pair-admission.v3.1-global-block"])
def test_eligible_block_with_its_evaluation_is_evaluated_for_any_pair_admission_implementation(rule):
    coverage = _classify(evaluation=_evaluation(decision="REJECTED", rule=rule)).coverage
    assert coverage is not None
    assert (coverage.admission_coverage_status, coverage.admission_decision) == ("EVALUATED", "REJECTED")
    assert coverage.admission_evaluation_id == UUID(int=42)


def test_missing_evaluation_is_transient_within_sla_and_an_incident_after_it():
    eligible_at = W0 + timedelta(minutes=10)
    whole_window = _classify(as_of=W1)  # the SLA ran out long before the window closed
    late_observation = RawAuthorityCoverageObservationV31.model_validate(
        {**_observation().model_dump(), "observed_window_end_utc": W0 + timedelta(minutes=11)}
    )
    within = _classify(late_observation, as_of=eligible_at + timedelta(seconds=119))
    assert within.outcome == "NOT_CLASSIFIED" and within.reason_code == "PAIR_ADMISSION_NOT_EVALUATED_WITHIN_SLA"
    assert whole_window.coverage is not None
    assert whole_window.coverage.admission_coverage_status == "MISSING_EVALUATION_INCIDENT"
    after = _classify(late_observation, as_of=eligible_at + timedelta(seconds=120)).coverage
    assert after is not None and (after.incident_required, after.replay_required) == (True, True)


def test_scope_mismatch_future_evaluation_open_window_and_missing_policy_fail_closed():
    assert _classify(evaluation=_evaluation(raw_authority_block_id="other")).reason_code == (
        "PAIR_ADMISSION_EVALUATION_SCOPE_MISMATCH"
    )
    assert _classify(_observation(block=None), evaluation=_evaluation()).reason_code == (
        "PAIR_ADMISSION_EVALUATION_SCOPE_MISMATCH"
    )
    assert (
        _classify(evaluation=_evaluation(evaluated_at=W1 + timedelta(seconds=1))).reason_code == "FUTURE_LEAKAGE_BLOCK"
    )
    assert _classify(as_of=W1 - timedelta(seconds=1)).reason_code == "COVERAGE_WINDOW_NOT_CLOSED"
    assert _classify(policy=None).reason_code == "PAIR_ADMISSION_COVERAGE_POLICY_MISSING"
    with pytest.raises(ValidationError, match="PAIR_ADMISSION_COVERAGE_POLICY_HASH_MISMATCH"):
        PairAdmissionCoveragePolicyV31.model_validate({**POLICY.model_dump(), "evaluation_sla_seconds": 1})


def test_classification_is_deterministic_and_the_contract_rejects_incoherent_records():
    first = _classify(evaluation=_evaluation()).coverage
    again = _classify(evaluation=_evaluation()).coverage
    assert first is not None and first == again and first.pair_admission_coverage_id.version == 5
    assert (first.admission_authority, first.risk_authority, first.execution_authority) == (False, False, False)
    body = first.model_dump()
    for broken, message in (
        ({"admission_evaluation_id": None, "admission_decision": None}, "EVALUATED needs"),
        ({"reason_code": "PAIR_ADMISSION_GRANTED"}, "COVERAGE_REASON_CODE_MISMATCH"),
        ({"raw_authority_coverage_status": "UNKNOWN"}, "INDETERMINATE is exactly"),
        ({"symbol": "GBPUSD"}, "PAIR_ADMISSION_COVERAGE_ID_NOT_DERIVED"),
    ):
        with pytest.raises(ValidationError, match=message):
            PairAdmissionCoverageV1.model_validate({**body, **broken})


def test_coverage_boundary_is_implementation_neutral():
    for name in (
        "contracts/strategy_5scr_pair_admission_coverage_v31.py",
        "analysis/strategy_5scr_pair_admission_coverage_v31.py",
    ):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not any("per_symbol_admission" in module or "pair_admission_blocks" in module for module in imported)
