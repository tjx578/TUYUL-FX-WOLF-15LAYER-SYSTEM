"""#493 replacement acceptance: StrategyAnalysisAdmissionReceiptV31 binds the S1B lineage (owner decision 2026-09-20).

    PairAdmission → PairAdmissionCoverage → StrategyAnalysisAdmission → AnalysisLifecycle → receipt
    AdvisoryPressureEvidence → maturity → StrategyAnalysisAdmission → same episode/lifecycle → receipt

The superseded #493 receipt derived the admission and lifecycle ids from PairAdmission. Here nothing is derived:
every id comes from its authority object and is cross-checked.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_admission_receipt_v31 import build_strategy_analysis_admission_receipt_v31
from analysis.strategy_5scr_analysis_admission_v31 import evaluate_canonical_raw_admission_v31
from analysis.strategy_5scr_analysis_lifecycle_v31 import (
    InMemoryAnalysisLifecycleLedgerV31,
    lifecycle_view_v31,
)
from analysis.strategy_5scr_pair_admission_coverage_v31 import classify_pair_admission_coverage_v31
from contracts.strategy_5scr_admission_receipt_v31 import (
    StrategyAnalysisAdmissionReceiptV31,
    admission_receipt_hash_v31,
)
from contracts.strategy_5scr_identity_v31 import IDENTITY_ENCODING_VERSION, canonical_sha256_v31
from contracts.strategy_5scr_market_episode_v31 import V31_MARKET_EPISODE_NAMESPACE, market_episode_id_v31
from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    PairAdmissionEvaluationRefV31,
    RawAuthorityBlockRefV31,
    RawAuthorityCoverageObservationV31,
)
from tests.test_strategy_5scr_analysis_admission_v31 import ADMISSION, _evidence
from tests.test_strategy_5scr_analysis_lifecycle_v31 import _apply, _chain
from tests.test_strategy_5scr_market_episode_v31 import POLICY as MERGE_POLICY
from tests.test_strategy_5scr_market_episode_v31 import _event, _reduce
from tests.test_strategy_5scr_pair_admission_coverage_v31 import POLICY as COVERAGE_POLICY
from tests.test_strategy_5scr_pair_admission_coverage_v31 import _classify, _evaluation, _observation
from tests.test_strategy_5scr_per_symbol_admission import START, _raw
from tests.test_strategy_5scr_per_symbol_admission import _evaluate as _pair_admission

ROOT = Path(__file__).resolve().parents[1]
_PROJECTION_NS = UUID("00000000-0000-4000-8000-000000000492")  # test-local projection of a #492 lineage


def _receipt(ledger, ep, st, adm, /, *, coverage, evaluation=None, evidence=None, **overrides: Any):
    lifecycle_id = ep.strategy_lifecycle_id
    attachment = next(
        a
        for a in ledger.attachments[lifecycle_id]
        if a.strategy_analysis_admission_id == adm.strategy_analysis_admission_id
    )
    revision = next(
        r
        for r in ledger.revisions[adm.strategy_analysis_admission_id]
        if r.revision_id == attachment.attached_revision_id
    )
    values: dict[str, Any] = {
        "admission": adm,
        "revision": revision,
        "attachment": attachment,
        "lifecycle": lifecycle_view_v31(ledger, lifecycle_id, st),
        "episode": ep,
        "coverage": coverage,
        "evaluation": evaluation,
        "evidence": evidence,
        **overrides,
    }
    return build_strategy_analysis_admission_receipt_v31(**values)


def _sources(symbol: str = "EURUSD"):
    evaluation = _evaluation(canonical_symbol=symbol, raw_authority_block_id=f"{symbol}-block-1")
    return (
        _classify(_observation(block=None, symbol=symbol), maturity="MATURE").coverage,
        _classify(_observation(symbol=symbol), evaluation=evaluation).coverage,
        evaluation,
    )


def _upgraded(symbol: str = "EURUSD"):
    episode, state, immature, advisory, canonical = _chain(symbol)
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, immature, advisory, canonical)
    return ledger, episode, state, immature, advisory, canonical


def test_canonical_raw_from_a_real_pair_admission_through_coverage_admission_and_lifecycle():
    lineage = _pair_admission([_raw(0), _raw(300)]).lineages["EURUSD"][-1]
    assert lineage.decision == "GRANTED" and lineage.granted_at is not None
    evaluation = PairAdmissionEvaluationRefV31(  # implementation-neutral projection of the #492 lineage
        admission_evaluation_id=uuid5(_PROJECTION_NS, lineage.lineage_id),
        raw_authority_block_id=lineage.lineage_id,
        canonical_symbol="EURUSD",
        decision="GRANTED",
        reason_code=lineage.reason_code,
        evaluated_at=lineage.granted_at,
        admission_rule_version=lineage.rule_version,
        evaluation_hash=canonical_sha256_v31(lineage.model_dump(mode="json")),
    )
    window_end = lineage.granted_at + timedelta(minutes=1)
    coverage = classify_pair_admission_coverage_v31(
        observation=RawAuthorityCoverageObservationV31(
            canonical_symbol="EURUSD",
            observed_window_start_utc=START,
            observed_window_end_utc=window_end,
            raw_authority_coverage_status="COMPLETE",
            coverage_evidence_hash=canonical_sha256_v31(["coverage", lineage.lineage_id]),
            block=RawAuthorityBlockRefV31(
                raw_authority_block_id=lineage.lineage_id,
                canonical_symbol="EURUSD",
                block_started_at=lineage.opened_at,
                eligible=True,
                eligible_at=lineage.granted_at,
                raw_lineage_hash=evaluation.evaluation_hash,
            ),
        ),
        evaluation=evaluation,
        advisory_pressure_maturity="UNKNOWN",
        policy=COVERAGE_POLICY,
        as_of=window_end,
    ).coverage
    assert coverage is not None and coverage.admission_coverage_status == "EVALUATED"
    reduction = _reduce(
        [_event(0, 0, event_time=START), _event(1, 0, event_time=START + timedelta(minutes=2))], MERGE_POLICY
    )
    ((episode_id, episode),) = reduction.episodes.items()
    state = reduction.states[episode_id]
    admission = evaluate_canonical_raw_admission_v31(
        episode=episode,
        episode_state=state,
        coverage=coverage,
        evaluation=evaluation,
        pressure_direction="BUY",
        direction_lineage_alignment="ALIGNED",
        direction_evidence_hash=evaluation.evaluation_hash,
        policy=ADMISSION,
        decision_at=window_end,
    ).admission
    assert admission is not None and admission.admission_status == "GRANTED"
    ledger = InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, admission)
    receipt = _receipt(ledger, episode, state, admission, coverage=coverage, evaluation=evaluation)
    assert (receipt.admission_class, receipt.source_authority, receipt.promotion_eligibility) == (
        "CANONICAL_RAW",
        "RAW_SIGNALTHROTTLE_LEDGER",
        "CANONICAL_RISK_PATH",
    )
    assert receipt.strategy_lifecycle_id == episode.strategy_lifecycle_id
    assert receipt.pair_admission_evaluation_id == evaluation.admission_evaluation_id
    # PairAdmission is a SOURCE only: neither id is derived from the #492 lineage.
    assert receipt.strategy_analysis_admission_id != evaluation.admission_evaluation_id
    assert admission_receipt_hash_v31(receipt) == admission_receipt_hash_v31(
        _receipt(ledger, episode, state, admission, coverage=coverage, evaluation=evaluation)
    )


def test_mature_advisory_receipt_carries_no_pair_admission_and_the_same_lifecycle():
    ledger, episode, state, _, advisory, _ = _upgraded()
    advisory_coverage, _, _ = _sources()
    receipt = _receipt(ledger, episode, state, advisory, coverage=advisory_coverage, evidence=_evidence(episode))
    assert (receipt.pair_admission_evaluation_id, receipt.pair_admission_evaluation_hash) == (None, None)
    assert (receipt.analysis_authority, receipt.source_authority, receipt.promotion_eligibility) == (
        "FULL_SHADOW_ANALYSIS",
        "DERIVED_PRESSURE_ADVISORY",
        "SHADOW_ONLY",
    )
    assert (receipt.admission_revision_number, receipt.risk_authority, receipt.execution_authority) == (2, False, False)


def test_upgrade_gives_two_receipts_on_one_unchanged_lifecycle():
    ledger, episode, state, _, advisory, canonical = _upgraded()
    advisory_coverage, canonical_coverage, evaluation = _sources()
    receipt_a = _receipt(ledger, episode, state, advisory, coverage=advisory_coverage, evidence=_evidence(episode))
    receipt_b = _receipt(ledger, episode, state, canonical, coverage=canonical_coverage, evaluation=evaluation)
    assert receipt_a.strategy_analysis_admission_id != receipt_b.strategy_analysis_admission_id
    assert admission_receipt_hash_v31(receipt_a) != admission_receipt_hash_v31(receipt_b)
    assert receipt_a.strategy_lifecycle_id == receipt_b.strategy_lifecycle_id == episode.strategy_lifecycle_id
    assert (
        lifecycle_view_v31(ledger, episode.strategy_lifecycle_id, state).highest_analysis_authority == "CANONICAL_RAW"
    )


def test_pair_admission_objects_are_never_accepted_as_an_s1b_receipt():
    ledger, episode, state, _, advisory, _ = _upgraded()
    advisory_coverage, _, _ = _sources()
    lineage = _pair_admission([_raw(0), _raw(300)]).lineages["EURUSD"][-1]
    with pytest.raises(ValidationError):
        _receipt(
            ledger, episode, state, advisory, coverage=advisory_coverage, evidence=_evidence(episode), admission=lineage
        )
    superseded_shape = {  # the #493 AdmissionReceiptV31 shape
        "rule_version": "5scr.admission-receipt.v31.v1",
        "strategy_analysis_admission_id": str(advisory.strategy_analysis_admission_id),
        "canonical_symbol": "EURUSD",
        "pair_admission_rule_version": lineage.rule_version,
        "decision": "GRANTED",
        "reason_code": lineage.reason_code,
        "source_event_ids": list(lineage.source_event_ids),
    }
    with pytest.raises(ValidationError):
        StrategyAnalysisAdmissionReceiptV31.model_validate(superseded_shape)


def test_wrong_episode_lifecycle_class_status_or_revision_is_rejected():
    ledger, episode, state, immature, advisory, canonical = _upgraded()
    gbp_ledger, gbp_episode, gbp_state, _, gbp_advisory, _ = _upgraded("GBPUSD")
    advisory_coverage, canonical_coverage, evaluation = _sources()
    common = {"coverage": advisory_coverage, "evidence": _evidence(episode)}
    with pytest.raises(ValueError, match="RECEIPT_MARKET_EPISODE_MISMATCH"):
        _receipt(ledger, episode, state, advisory, episode=gbp_episode, **common)
    gbp_attachment = gbp_ledger.attachments[gbp_episode.strategy_lifecycle_id][0]
    with pytest.raises(ValueError, match="RECEIPT_LIFECYCLE_MISMATCH"):
        _receipt(ledger, episode, state, advisory, attachment=gbp_attachment, **common)
    with pytest.raises(ValueError, match="RECEIPT_REQUIRES_GRANTED_ADMISSION"):
        _receipt(ledger, episode, state, advisory, admission=immature, **common)
    rejected_revision = ledger.revisions[advisory.strategy_analysis_admission_id][0]
    with pytest.raises(ValueError, match="ADMISSION_REVISION_MISMATCH"):
        _receipt(ledger, episode, state, advisory, revision=rejected_revision, **common)
    with pytest.raises(ValueError, match="RECEIPT_ATTACHMENT_MISMATCH"):
        _receipt(
            ledger,
            episode,
            state,
            advisory,
            attachment=ledger.attachments[episode.strategy_lifecycle_id][1],  # the canonical attachment
            **common,
        )
    receipt = _receipt(ledger, episode, state, advisory, **common)
    body = receipt.model_dump()
    for broken, message in (
        ({"strategy_lifecycle_id": gbp_episode.strategy_lifecycle_id}, "RECEIPT_LIFECYCLE_NOT_DERIVED_FROM_EPISODE"),
        ({"admission_class": "CANONICAL_RAW"}, "RECEIPT_CLASS_SCOPE_MISMATCH"),
        ({"admission_status": "REJECTED"}, "literal_error"),
    ):
        with pytest.raises(ValidationError, match=message):
            StrategyAnalysisAdmissionReceiptV31.model_validate({**body, **broken})
    assert gbp_advisory.strategy_analysis_admission_id != advisory.strategy_analysis_admission_id


def test_mature_advisory_with_a_fake_pair_admission_is_rejected():
    ledger, episode, state, _, advisory, _ = _upgraded()
    advisory_coverage, _, evaluation = _sources()
    with pytest.raises(ValueError, match="binds advisory evidence and no PairAdmission evaluation"):
        _receipt(
            ledger,
            episode,
            state,
            advisory,
            coverage=advisory_coverage,
            evidence=_evidence(episode),
            evaluation=evaluation,
        )
    receipt = _receipt(ledger, episode, state, advisory, coverage=advisory_coverage, evidence=_evidence(episode))
    with pytest.raises(ValidationError, match="only CANONICAL_RAW receipts bind a PairAdmission evaluation"):
        StrategyAnalysisAdmissionReceiptV31.model_validate(
            {
                **receipt.model_dump(),
                "pair_admission_evaluation_id": evaluation.admission_evaluation_id,
                "pair_admission_evaluation_hash": evaluation.evaluation_hash,
            }
        )


def test_unified_identity_helper_keeps_every_existing_id_byte_identical():
    opened = START + timedelta(minutes=1)
    legacy_name = json.dumps(
        [IDENTITY_ENCODING_VERSION, "EURUSD", opened.isoformat(), MERGE_POLICY.policy_hash], separators=(",", ":")
    )
    assert market_episode_id_v31(
        canonical_symbol="EURUSD", opened_at=opened, merge_policy_hash=MERGE_POLICY.policy_hash
    ) == uuid5(V31_MARKET_EPISODE_NAMESPACE, legacy_name)
    namespaces: dict[str, str] = {}
    for path in ROOT.glob("contracts/*_v31.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id.endswith("NAMESPACE") and node.value.args:
                    arg = node.value.args[0]
                    if isinstance(arg, ast.Constant):
                        assert arg.value not in namespaces.values(), f"namespace collision: {target.id}"
                        namespaces[f"{path.name}:{target.id}"] = str(arg.value)
    assert len(namespaces) >= 5


def test_no_module_derives_a_lifecycle_or_admission_id_from_pair_admission():
    for path in (*ROOT.glob("contracts/*_v31.py"), *ROOT.glob("analysis/*_v31.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "lifecycle_id_v31" not in defined and "admission_id_v31" not in defined, path.name
    builder = (ROOT / "analysis/strategy_5scr_admission_receipt_v31.py").read_text(encoding="utf-8")
    assert "uuid5" not in builder and "identity_uuid_v31" not in builder
