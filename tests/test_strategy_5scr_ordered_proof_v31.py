from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_reference_pattern_v31 import (
    ReferencePatternPolicyV31,
    build_reference_pattern_receipts_v31,
    reference_pattern_policy_hash,
)
from contracts.strategy_5scr_ordered_proof_v31 import OrderedProofEvidenceV31, ordered_proof_hash_v31
from tests.test_strategy_5scr_context_route_v31 import NOW, H, receipt
from tests.test_strategy_5scr_directional_thesis_v1 import _candles, _rehash_candle


def reference_policy():
    return ReferencePatternPolicyV31(
        profile="TEST_ONLY",
        rule_id="ADJACENT_H1_PAIR_M15_TRIPLE_TEST_V1",
        source_rule="5scr.directional-thesis.v1",
        selected_route="FIXTURE_CONTINUATION",
    )


def proof(context=None, thesis_id=None):
    context = context or receipt()
    thesis_id = thesis_id or UUID(int=2)
    h1, m15 = _candles(context.direction)
    offset = NOW - timedelta(minutes=1) - m15[-1].close_time_utc

    def shifted(candles):
        return tuple(
            _rehash_candle(
                {
                    **c.model_dump(),
                    "symbol": context.symbol,
                    "open_time_utc": c.open_time_utc + offset,
                    "close_time_utc": c.close_time_utc + offset,
                }
            )
            for c in candles
        )

    h1, m15 = shifted(h1), shifted(m15)
    value = OrderedProofEvidenceV31(
        profile="TEST_ONLY",
        strategy_thesis_id=thesis_id,
        strategy_lifecycle_id=context.strategy_lifecycle_id,
        context_epoch_id=context.context_epoch_id,
        symbol=context.symbol,
        direction=context.direction,
        selected_route=context.selected_route,
        context_material_hash=context.material_context_hash,
        pattern_policy_hash=reference_pattern_policy_hash(reference_policy()),
        level_version="fixture-level-v1",
        h1_proof_id=UUID(int=70),
        m15_proof_id=UUID(int=71),
        h1_source_candles=h1,
        m15_source_candles=m15,
        h1_closed_at=h1[-1].close_time_utc,
        m15_closed_at=m15[-1].close_time_utc,
        m15_break_candle_id=m15[-2].candle_evidence_id,
        m15_completion_candle_id=m15[-1].candle_evidence_id,
        m15_completion_kind="RETEST",
        h1_resolution_receipt_hash=H,
        m15_resolution_receipt_hash=H,
        evaluated_at=NOW,
        valid_until=NOW + timedelta(hours=1),
    )
    return build_reference_pattern_receipts_v31(value, policy=reference_policy())


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_full_candle_content_roundtrips_with_ordered_proof_hash(direction):
    value = proof(receipt(direction))
    restored = OrderedProofEvidenceV31.model_validate_json(value.model_dump_json())
    assert restored == value and ordered_proof_hash_v31(restored) == ordered_proof_hash_v31(value)
    assert value.h1_closed_at <= value.m15_closed_at <= value.evaluated_at


@pytest.mark.parametrize(
    "fault",
    [
        "future",
        "expiry",
        "naive",
        "h1_close",
        "m15_close",
        "same_proof_id",
        "duplicate",
        "reversed",
        "wrong_symbol",
        "wrong_timeframe",
        "material_hash",
        "content_hash",
        "missing_break",
        "completion_is_break",
        "level_missing",
    ],
)
def test_incoherent_proof_rejected(fault):
    body = proof().model_dump()
    if fault == "future":
        body["evaluated_at"] = body["m15_closed_at"] - timedelta(seconds=1)
    elif fault == "expiry":
        body["valid_until"] = body["evaluated_at"]
    elif fault == "naive":
        body["evaluated_at"] = NOW.replace(tzinfo=None)
    elif fault == "h1_close":
        body["h1_closed_at"] -= timedelta(seconds=1)
    elif fault == "m15_close":
        body["m15_closed_at"] += timedelta(seconds=1)
    elif fault == "same_proof_id":
        body["m15_proof_id"] = body["h1_proof_id"]
    elif fault == "duplicate":
        body["h1_source_candles"] *= 2
    elif fault == "reversed":
        body["m15_source_candles"] = tuple(reversed(body["m15_source_candles"]))
    elif fault == "wrong_symbol":
        body["h1_source_candles"][0]["symbol"] = "XAUUSD"
    elif fault == "wrong_timeframe":
        body["h1_source_candles"] = body["m15_source_candles"]
    elif fault == "material_hash":
        body["h1_source_candles"][0]["close"] += 0.0001
    elif fault == "content_hash":
        body["h1_source_candles"][0]["source_content_hash"] = "sha256:" + "8" * 64
    elif fault == "missing_break":
        body["m15_break_candle_id"] = "sha256:" + "8" * 64
    elif fault == "completion_is_break":
        body["m15_completion_candle_id"] = body["m15_break_candle_id"]
    elif fault == "level_missing":
        body.pop("level_version")
    with pytest.raises(ValidationError):
        OrderedProofEvidenceV31.model_validate(body)
