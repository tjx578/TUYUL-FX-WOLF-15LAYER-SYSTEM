from datetime import timedelta

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_candle_targets_v31 import (
    TargetCandleSnapshotV31,
    candle_snapshot_hash_v31,
    derive_candle_targets_v31,
    solve_candle_target_geometry_v31,
)
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryContextV31
from tests.test_strategy_5scr_net_geometry_v31 import NOW, H, request_data


def snapshot_data(direction="BUY"):
    frames = []
    for timeframe, hours, count in (("D1", 24, 3), ("H4", 4, 3), ("H1", 1, 72)):
        rows = []
        for i in range(count):
            opened = NOW - timedelta(hours=hours * (count - i))
            high, low = 1.1001, 1.0999
            if timeframe != "H1" and i == 1:
                if direction == "BUY":
                    high = 1.1012 if timeframe == "D1" else 1.103
                else:
                    low = 1.0988 if timeframe == "D1" else 1.097
            rows.append(
                {
                    "symbol": "EURUSD",
                    "timeframe": timeframe,
                    "open_time": opened,
                    "close_time": opened + timedelta(hours=hours),
                    "open": 1.1,
                    "high": high,
                    "low": low,
                    "close": 1.1,
                    "complete": True,
                    "provider": "TEST_ONLY",
                    "provider_timestamp_semantics": "CANONICAL_WINDOW",
                }
            )
        frames.append({"timeframe": timeframe, "expected_open_times": [r["open_time"] for r in rows], "candles": rows})
    return {
        "profile": "TEST_ONLY",
        "derivation_policy": "STRICT_THREE_CONTINUOUS_CANDLES_TEST_V1",
        "policy_hash": H,
        "symbol": "EURUSD",
        "direction": direction,
        "decision_at": NOW,
        "target_lifetime_seconds": 86400,
        "frames": frames,
    }


def context(direction="BUY"):
    data = request_data(direction)
    del data["target_price"], data["target_evidence_hash"]
    return NetGeometryContextV31(**data)


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_canonical_candles_derive_targets_and_reach_net_geometry(direction):
    snapshot = TargetCandleSnapshotV31(**snapshot_data(direction))
    pinned = candle_snapshot_hash_v31(snapshot)
    result = solve_candle_target_geometry_v31(
        snapshot=snapshot, context=context(direction), verify_snapshot=lambda s, h: h == pinned
    )
    universe = derive_candle_targets_v31(snapshot, verify_snapshot=lambda s, h: h == pinned)
    assert len(universe.targets) == 2
    selected = next(t for t in universe.targets if t.target_id == result.selected_target_id)
    assert abs(float(selected.price) - 1.1) == pytest.approx(0.0012)
    assert result.geometry.status == "FEASIBLE_TEST_ONLY"
    assert not result.execution_authority and not result.geometry.execution_authority


@pytest.mark.parametrize("mutation", ["omit_row", "gap", "unclosed", "future", "wrong_symbol", "wrong_timeframe"])
def test_untrusted_candle_cohort_fails_before_derivation(mutation):
    data = snapshot_data()
    frame = data["frames"][2]
    if mutation == "omit_row":
        frame["candles"].pop(10)
    elif mutation == "gap":
        frame["candles"].pop(10)
        frame["expected_open_times"].pop(10)
    elif mutation == "unclosed":
        frame["candles"][10]["complete"] = False
    elif mutation == "future":
        data["decision_at"] -= timedelta(hours=1)
    elif mutation == "wrong_symbol":
        frame["candles"][10]["symbol"] = "USDJPY"
    else:
        frame["timeframe"] = "H4"
    with pytest.raises(ValidationError):
        TargetCandleSnapshotV31(**data)


def test_receipt_detects_price_changes_and_missing_attestor_never_derives():
    data = snapshot_data()
    original = TargetCandleSnapshotV31(**data)
    pinned = candle_snapshot_hash_v31(original)
    with pytest.raises(ValueError, match="ATTESTOR_UNBOUND"):
        derive_candle_targets_v31(original, verify_snapshot=None)
    data["frames"][0]["candles"][1]["high"] = 1.102
    altered = TargetCandleSnapshotV31(**data)
    with pytest.raises(ValueError, match="ATTESTATION_REJECTED"):
        derive_candle_targets_v31(altered, verify_snapshot=lambda s, h: h == pinned)


def test_h1_touch_consumes_only_after_confirmation_and_ties_are_not_swings():
    data = snapshot_data()
    h1 = data["frames"][2]["candles"]
    h1[20]["high"] = 1.101
    h1[25]["high"] = 1.101
    universe = derive_candle_targets_v31(TargetCandleSnapshotV31(**data), verify_snapshot=lambda s, h: True)
    consumed = [t for t in universe.targets if t.consumed_at is not None]
    assert len(consumed) == 1 and consumed[0].consumed_at == h1[25]["close_time"]
    h1[21]["high"] = 1.101
    universe = derive_candle_targets_v31(TargetCandleSnapshotV31(**data), verify_snapshot=lambda s, h: True)
    assert not any(t.formed_at == h1[21]["close_time"] for t in universe.targets)


def test_source_frame_reordering_does_not_change_receipt_or_outcome():
    data = snapshot_data()
    original = TargetCandleSnapshotV31(**data)
    data["frames"].reverse()
    reordered = TargetCandleSnapshotV31(**data)
    assert candle_snapshot_hash_v31(original) == candle_snapshot_hash_v31(reordered)
    assert derive_candle_targets_v31(original, verify_snapshot=lambda s, h: True) == derive_candle_targets_v31(
        reordered, verify_snapshot=lambda s, h: True
    )


def test_nonrepresentable_float_price_is_rejected_without_rounding():
    data = snapshot_data()
    data["frames"][0]["candles"][1]["high"] = 1.1 + 0.0012
    with pytest.raises(ValidationError, match="decimal places"):
        derive_candle_targets_v31(TargetCandleSnapshotV31(**data), verify_snapshot=lambda s, h: True)


def test_cross_timeframe_confirmation_cannot_split_an_h1_consumption_candle():
    data = snapshot_data()
    frame = data["frames"][0]
    for candle in frame["candles"]:
        candle["open_time"] -= timedelta(minutes=30)
        candle["close_time"] -= timedelta(minutes=30)
    frame["expected_open_times"] = [c["open_time"] for c in frame["candles"]]
    with pytest.raises(ValidationError, match="NOT_ALIGNED"):
        TargetCandleSnapshotV31(**data)
