"""Canonical-candle strict swings feeding the TEST_ONLY target/net caller.

This explicitly versioned continuous-window test policy is not an active market
calendar, support/resistance, range, liquidity or Fibonacci derivation policy.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from analysis.strategy_5scr_target_selection_v31 import solve_target_geometry_v31, target_universe_hash_v31
from contracts.canonical_candle import CanonicalCandle
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract, NetGeometryContextV31
from contracts.strategy_5scr_target_selection_v31 import StructuralTargetV31, TargetGeometryResultV31, TargetUniverseV31


class TargetCandleFrameV31(GeometryContract):
    timeframe: Literal["D1", "H4", "H1"]
    expected_open_times: tuple[datetime, ...] = Field(min_length=3, max_length=10000)
    candles: tuple[CanonicalCandle, ...] = Field(min_length=3, max_length=10000)


class TargetCandleSnapshotV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    derivation_policy: Literal["STRICT_THREE_CONTINUOUS_CANDLES_TEST_V1"]
    policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(min_length=3, max_length=32)
    direction: Literal["BUY", "SELL"]
    decision_at: datetime
    target_lifetime_seconds: int = Field(gt=0, le=31536000, strict=True)
    frames: tuple[TargetCandleFrameV31, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def complete_frames(self) -> "TargetCandleSnapshotV31":
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("TARGET_DECISION_CLOCK_UNBOUND")
        if {frame.timeframe for frame in self.frames} != {"D1", "H4", "H1"}:
            raise ValueError("TARGET_TIMEFRAME_COVERAGE_INCOMPLETE")
        for frame in self.frames:
            clocks = tuple(c.open_time for c in frame.candles)
            if clocks != frame.expected_open_times or clocks != tuple(sorted(set(clocks))):
                raise ValueError("TARGET_CANONICAL_COHORT_INCOMPLETE_OR_REORDERED")
            if any(
                c.symbol != self.symbol
                or c.timeframe != frame.timeframe
                or not c.is_authoritative_closed_as_of(self.decision_at)
                for c in frame.candles
            ):
                raise ValueError("TARGET_CANDLE_SCOPE_OR_CLOSURE_INVALID")
            if any(
                left.close_time != right.open_time
                for left, right in zip(frame.candles, frame.candles[1:], strict=False)
            ):
                raise ValueError("TARGET_CANDLE_GAP_POLICY_UNBOUND")
        h1 = next(frame.candles for frame in self.frames if frame.timeframe == "H1")
        earliest_formation = min(frame.candles[2].close_time for frame in self.frames)
        if h1[0].open_time > earliest_formation or h1[-1].close_time != self.decision_at:
            raise ValueError("TARGET_CONSUMPTION_COVERAGE_INCOMPLETE")
        h1_closes = {c.close_time for c in h1}
        if any(c.close_time not in h1_closes for frame in self.frames for c in frame.candles[2:]):
            raise ValueError("TARGET_CONFIRMATION_NOT_ALIGNED_TO_CONSUMPTION_WINDOW")
        return self


def candle_snapshot_hash_v31(snapshot: TargetCandleSnapshotV31) -> str:
    payload = snapshot.model_dump(mode="json")
    payload["frames"] = sorted(payload["frames"], key=lambda frame: frame["timeframe"])
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def derive_candle_targets_v31(
    snapshot: TargetCandleSnapshotV31,
    *,
    verify_snapshot: Callable[[TargetCandleSnapshotV31, str], bool] | None,
) -> TargetUniverseV31:
    snapshot = TargetCandleSnapshotV31.model_validate(snapshot.model_dump())
    digest = candle_snapshot_hash_v31(snapshot)
    if verify_snapshot is None:
        raise ValueError("TARGET_CANDLE_ATTESTOR_UNBOUND")
    if verify_snapshot(snapshot, digest) is not True:
        raise ValueError("TARGET_CANDLE_ATTESTATION_REJECTED")
    h1 = next(frame.candles for frame in snapshot.frames if frame.timeframe == "H1")
    targets = []
    buying = snapshot.direction == "BUY"
    for frame in sorted(snapshot.frames, key=lambda item: item.timeframe):
        for left, pivot, right in zip(frame.candles, frame.candles[1:], frame.candles[2:], strict=False):
            strict_swing = pivot.high > max(left.high, right.high) if buying else pivot.low < min(left.low, right.low)
            if not strict_swing:
                continue
            price = Decimal(str(pivot.high if buying else pivot.low))
            formed = right.close_time
            consumed = next(
                (
                    c.close_time
                    for c in h1
                    if c.close_time > formed
                    and (Decimal(str(c.high)) >= price if buying else Decimal(str(c.low)) <= price)
                ),
                None,
            )
            identity = json.dumps(
                {
                    "symbol": snapshot.symbol,
                    "direction": snapshot.direction,
                    "timeframe": frame.timeframe,
                    "pivot_open": pivot.open_time.isoformat(),
                    "price": str(price),
                    "policy": snapshot.policy_hash,
                },
                sort_keys=True,
            )
            target_id = "swing:" + hashlib.sha256(identity.encode()).hexdigest()
            targets.append(
                StructuralTargetV31(
                    target_id=target_id,
                    source="SWING",
                    price=price,
                    evidence_hash=digest,
                    formed_at=formed,
                    valid_until=formed + timedelta(seconds=snapshot.target_lifetime_seconds),
                    consumed_at=consumed,
                )
            )
    return TargetUniverseV31(
        profile="TEST_ONLY",
        symbol=snapshot.symbol,
        direction=snapshot.direction,
        decision_at=snapshot.decision_at,
        anchor_price=Decimal(str(h1[-1].close)),
        anchor_evidence_hash=digest,
        policy_hash=snapshot.policy_hash,
        required_sources=("SWING",),
        covered_sources=("SWING",),
        targets=tuple(targets),
    )


def solve_candle_target_geometry_v31(
    *,
    snapshot: TargetCandleSnapshotV31,
    context: NetGeometryContextV31,
    verify_snapshot: Callable[[TargetCandleSnapshotV31, str], bool] | None,
) -> TargetGeometryResultV31:
    universe = derive_candle_targets_v31(snapshot, verify_snapshot=verify_snapshot)
    pinned = target_universe_hash_v31(universe)
    # The source receipt was verified before derivation. Bind only that exact
    # derived cohort to the next stage; never expose a blanket accepting verifier.
    return solve_target_geometry_v31(
        universe=universe, context=context, verify_universe=lambda candidate, digest: digest == pinned
    )
