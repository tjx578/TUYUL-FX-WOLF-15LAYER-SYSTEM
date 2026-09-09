from datetime import timedelta

import pytest

from analysis.strategy_5scr_reference_pattern_v31 import (
    ReferencePatternHandoffVerifierV31,
    build_reference_pattern_receipts_v31,
    derive_reference_pattern_v31,
)
from contracts.strategy_5scr_context_route_v31 import content_hash
from contracts.strategy_5scr_ordered_proof_v31 import OrderedProofEvidenceV31, ordered_proof_hash_v31
from risk.strategy_5scr_candidate_handoff_v31 import candidate_handoff_hash_v31
from tests.test_strategy_5scr_candidate_handoff_v31 import bundle, propose
from tests.test_strategy_5scr_context_route_v31 import receipt
from tests.test_strategy_5scr_directional_thesis_v1 import _rehash_candle
from tests.test_strategy_5scr_ordered_proof_v31 import proof, reference_policy


def rebind_candles(body):
    for field in ("h1_source_candles", "m15_source_candles"):
        body[field] = tuple(_rehash_candle(c) for c in body[field])
    body["h1_closed_at"] = body["h1_source_candles"][-1].close_time_utc
    body["m15_closed_at"] = body["m15_source_candles"][-1].close_time_utc
    body["m15_break_candle_id"] = body["m15_source_candles"][-2].candle_evidence_id
    body["m15_completion_candle_id"] = body["m15_source_candles"][-1].candle_evidence_id
    return OrderedProofEvidenceV31.model_validate(body)


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
@pytest.mark.parametrize("kind", ["ACCEPTANCE", "FAILED_RECLAIM", "RETEST"])
def test_completion_kind_and_resolutions_derive_from_prices(direction, kind):
    body = proof(receipt(direction)).model_dump()
    reference = body["m15_source_candles"][0]
    c = body["m15_source_candles"][-1]
    level = reference["high"] if direction == "BUY" else reference["low"]
    sign = 1 if direction == "BUY" else -1
    c["close"] = level + sign * 0.0002
    c["open"] = level + sign * (0.0001 if kind != "FAILED_RECLAIM" else -0.0001)
    c["high"], c["low"] = max(c["open"], c["close"]) + 0.00005, min(c["open"], c["close"]) - 0.00005
    if kind == "RETEST":
        c["low" if direction == "BUY" else "high"] = level
    built = build_reference_pattern_receipts_v31(rebind_candles(body), policy=reference_policy())
    h1, m15 = derive_reference_pattern_v31(built, policy=reference_policy())
    assert built.m15_completion_kind == kind
    assert built.h1_resolution_receipt_hash == content_hash(h1)
    assert built.m15_resolution_receipt_hash == content_hash(m15)


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("h1", "H1_BREAK_MISSING"),
        ("m15", "M15_BREAK_MISSING"),
        ("completion", "COMPLETION_MISSING"),
        ("gap", "WITNESS_GAP"),
        ("early_break", "BREAK_PRECEDES_H1"),
        ("count", "WITNESS_COUNT_INVALID"),
        ("policy", "POLICY_MISMATCH"),
    ],
)
def test_rehashed_but_invalid_pattern_still_rejected(fault, reason):
    body = proof().model_dump()
    if fault == "h1":
        body["h1_source_candles"][-1]["close"] = body["h1_source_candles"][0]["high"]
    elif fault == "m15":
        body["m15_source_candles"][-2]["close"] = body["m15_source_candles"][0]["high"]
    elif fault == "completion":
        body["m15_source_candles"][-1]["close"] = body["m15_source_candles"][0]["high"]
    elif fault == "gap":
        for key in ("open_time_utc", "close_time_utc"):
            body["h1_source_candles"][0][key] -= timedelta(minutes=1)
    elif fault == "early_break":
        for c in body["h1_source_candles"]:
            for key in ("open_time_utc", "close_time_utc"):
                c[key] += timedelta(minutes=15)
    elif fault == "count":
        body["h1_source_candles"] = body["h1_source_candles"][-1:]
    elif fault == "policy":
        body["pattern_policy_hash"] = "sha256:" + "8" * 64
    with pytest.raises(ValueError, match=reason):
        derive_reference_pattern_v31(rebind_candles(body), policy=reference_policy())


@pytest.mark.parametrize("field", ["h1_resolution_receipt_hash", "m15_resolution_receipt_hash", "m15_completion_kind"])
def test_claimed_resolution_tampering_stops_before_remaining_attestor(field):
    _, handoff, _ = bundle()
    structural = handoff.thesis_structural_proof.model_copy(
        update={field: "ACCEPTANCE" if field == "m15_completion_kind" else "sha256:" + "8" * 64}
    )
    handoff = handoff.model_copy(
        update={
            "thesis_structural_proof": structural,
            "thesis_structural_proof_hash": ordered_proof_hash_v31(structural),
        }
    )
    calls = []
    verifier = ReferencePatternHandoffVerifierV31(
        policy=reference_policy(), attest_remaining=lambda *args: calls.append(args)
    )
    assert verifier(handoff, candidate_handoff_hash_v31(handoff)) is False
    assert calls == []


@pytest.mark.parametrize("answer", [False, 1, "yes"])
def test_valid_reference_pattern_still_requires_literal_remaining_attestation(answer):
    _, handoff, _ = bundle()
    verifier = ReferencePatternHandoffVerifierV31(policy=reference_policy(), attest_remaining=lambda *_: answer)
    assert verifier(handoff, candidate_handoff_hash_v31(handoff)) is False


def test_missing_or_mutating_attestor_cannot_pass():
    with pytest.raises(ValueError, match="ATTESTOR_REQUIRED"):
        ReferencePatternHandoffVerifierV31(policy=reference_policy(), attest_remaining=None)
    _, handoff, _ = bundle()
    before = candidate_handoff_hash_v31(handoff)

    def mutate(value, digest):
        object.__setattr__(value.candidate, "evidence_hash", "sha256:" + "8" * 64)
        return True

    verifier = ReferencePatternHandoffVerifierV31(policy=reference_policy(), attest_remaining=mutate)
    assert verifier(handoff, before) is False
    assert candidate_handoff_hash_v31(handoff) == before


def test_actual_risk_handoff_rejects_false_break_even_when_content_hashes_match():
    ledger, handoff, request = bundle()
    body = handoff.thesis_structural_proof.model_dump()
    body["h1_source_candles"][-1]["close"] = body["h1_source_candles"][0]["high"]
    structural = rebind_candles(body)
    handoff = handoff.model_copy(
        update={
            "thesis_structural_proof": structural,
            "thesis_structural_proof_hash": ordered_proof_hash_v31(structural),
        }
    )
    request = request.model_copy(update={"strategy_candidate_receipt_hash": candidate_handoff_hash_v31(handoff)})
    with pytest.raises(ValueError, match="H1_BREAK_MISSING"):
        propose(ledger, handoff, request)
    assert not ledger.reservations
