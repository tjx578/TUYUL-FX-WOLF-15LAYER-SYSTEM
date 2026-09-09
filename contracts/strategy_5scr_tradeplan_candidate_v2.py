"""Shadow-only contracts for target-first Strategy 5S-CR tradeplan candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TRADEPLAN_CANDIDATE_V2_RULE_VERSION = "5scr.tradeplan-candidate.v2"
TARGET_MAP_RULE_VERSION = "5scr.structural-target-map.v1"
TARGET_COHORT_POLICY_ID = "CONTEXT_EPOCH_FULL_CANONICAL_TARGET_MAP_V1"
TARGET_FRESHNESS_POLICY_ID = "CONTEXT_EPOCH_STRUCTURAL_TARGET_LIVENESS_V1"
STOP_POLICY_ID = "P5_ROUTE_EXTREME_1_TICK_V1"
COST_POLICY_ID = "ESTIMATED_STRATEGY_COST_V1"

Direction = Literal["BUY", "SELL"]
TargetKind = Literal["H4_STRICT_SWING_HIGH", "H4_STRICT_SWING_LOW"]
CandidateLifecycleState = Literal["ACTIVE", "SUPERSEDED", "INVALIDATED", "EXPIRED"]
EvaluationDecision = Literal["CANDIDATE", "WAIT", "NO_TRADE", "QUARANTINED", "DUPLICATE"]
PersistedEvaluationDecision = Literal["CANDIDATE", "WAIT", "NO_TRADE"]

_HASH_SENTINEL = "sha256:" + "0" * 64
TRADEPLAN_NUMERIC_QUANTUM_V2 = Decimal("0.000000000001")


class FrozenTradePlanContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def canonical_hash_v1(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_tradeplan_numeric_v2(value: Decimal) -> Decimal:
    """Project derived tradeplan values onto the durable NUMERIC(28,12) grid."""

    return value.quantize(TRADEPLAN_NUMERIC_QUANTUM_V2, rounding=ROUND_HALF_EVEN)


class StructuralCandleAuthorityV1(FrozenTradePlanContract):
    """Canonical H4/H1 OHLC and row lineage used by the target map."""

    candle_evidence_id: str = Field(default=_HASH_SENTINEL, pattern=r"^sha256:[0-9a-f]{64}$")
    material_candle_hash: str = Field(default=_HASH_SENTINEL, pattern=r"^sha256:[0-9a-f]{64}$")
    source_content_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_row_id: int = Field(..., ge=1)
    selected_raw_candle_id: int = Field(..., ge=1)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    timeframe: Literal["H4", "H1"]
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal = Field(..., gt=0)
    high: Decimal = Field(..., gt=0)
    low: Decimal = Field(..., gt=0)
    close: Decimal = Field(..., gt=0)
    provider: str = Field(..., min_length=2, max_length=100)
    feed: str = Field(..., min_length=1, max_length=100)
    provider_timestamp_semantics: Literal["PERIOD_OPEN", "PERIOD_END", "CANONICAL_WINDOW"]
    selection_policy: str = Field(..., min_length=3, max_length=100)
    selection_rank: int = Field(..., ge=0)
    is_closed: Literal[True] = True
    structural_authority: Literal[True] = True

    @field_validator("open_time_utc", "close_time_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _candle_is_coherent(self) -> StructuralCandleAuthorityV1:
        duration = timedelta(hours=4 if self.timeframe == "H4" else 1)
        if self.close_time_utc - self.open_time_utc != duration:
            raise ValueError("structural candle window does not match timeframe")
        if self.high < max(self.open, self.close, self.low) or self.low > min(self.open, self.close, self.high):
            raise ValueError("structural candle OHLC is incoherent")
        material = canonical_hash_v1(
            {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "open_time_utc": self.open_time_utc,
                "close_time_utc": self.close_time_utc,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
            }
        )
        if self.material_candle_hash not in {_HASH_SENTINEL, material}:
            raise ValueError("structural material candle hash mismatch")
        object.__setattr__(self, "material_candle_hash", material)
        evidence = canonical_hash_v1(self.model_dump(mode="json", exclude={"candle_evidence_id"}))
        if self.candle_evidence_id not in {_HASH_SENTINEL, evidence}:
            raise ValueError("structural candle evidence hash mismatch")
        object.__setattr__(self, "candle_evidence_id", evidence)
        return self


class StructuralTargetMapEvidenceV1(FrozenTradePlanContract):
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    direction: Direction
    target_map_version: str = Field(..., min_length=3, max_length=100)
    decision_at_utc: datetime
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    h4_cohort_count: int = Field(..., ge=3)
    h1_coverage_start_utc: datetime
    h1_coverage_end_utc: datetime
    h1_cohort_count: int = Field(..., ge=1)
    selection_anchor: StructuralCandleAuthorityV1
    h4_candles: tuple[StructuralCandleAuthorityV1, ...] = Field(..., min_length=3)
    h1_consumption_candles: tuple[StructuralCandleAuthorityV1, ...] = Field(..., min_length=1)
    rule_version: Literal["5scr.structural-target-map.v1"] = TARGET_MAP_RULE_VERSION
    cohort_policy_id: Literal["CONTEXT_EPOCH_FULL_CANONICAL_TARGET_MAP_V1"] = TARGET_COHORT_POLICY_ID
    freshness_policy_id: Literal["CONTEXT_EPOCH_STRUCTURAL_TARGET_LIVENESS_V1"] = TARGET_FRESHNESS_POLICY_ID
    execution_authority: Literal[False] = False

    @field_validator(
        "decision_at_utc",
        "coverage_start_utc",
        "coverage_end_utc",
        "h1_coverage_start_utc",
        "h1_coverage_end_utc",
    )
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "decision_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _coverage_is_canonical(self) -> StructuralTargetMapEvidenceV1:
        if self.selection_anchor.timeframe != "H1" or self.selection_anchor.symbol != self.symbol:
            raise ValueError("selection anchor must be canonical H1 in target scope")
        if self.coverage_end_utc != self.decision_at_utc or self.h1_coverage_end_utc != self.decision_at_utc:
            raise ValueError("target evidence coverage must end at decision")
        if self.coverage_start_utc >= self.coverage_end_utc:
            raise ValueError("target evidence coverage interval is invalid")
        if self.h4_cohort_count != len(self.h4_candles) or self.h1_cohort_count != len(self.h1_consumption_candles):
            raise ValueError("target cohort counts must match exact evidence rows")
        if self.h1_coverage_start_utc != self.h4_candles[2].close_time_utc:
            raise ValueError("H1 coverage must start at earliest possible strict-swing formation")
        if self.selection_anchor.candle_evidence_id != self.h1_consumption_candles[-1].candle_evidence_id:
            raise ValueError("selection anchor must be the latest H1 row in exact coverage")
        for timeframe, candles in (("H4", self.h4_candles), ("H1", self.h1_consumption_candles)):
            if any(item.timeframe != timeframe or item.symbol != self.symbol for item in candles):
                raise ValueError(f"{timeframe} target evidence scope mismatch")
            ordering = tuple(item.close_time_utc for item in candles)
            if (
                ordering != tuple(sorted(ordering))
                or len(set(ordering)) != len(candles)
                or len({item.candle_evidence_id for item in candles}) != len(candles)
            ):
                raise ValueError(f"{timeframe} target evidence must be ordered and unique")
        if any(item.close_time_utc <= self.coverage_start_utc for item in self.h4_candles):
            raise ValueError("H4 cohort must be strictly inside context coverage")
        if any(item.close_time_utc <= self.h1_coverage_start_utc for item in self.h1_consumption_candles):
            raise ValueError("H1 cohort must follow earliest possible target formation")
        all_candles = (*self.h4_candles, *self.h1_consumption_candles, self.selection_anchor)
        if any(item.close_time_utc > self.decision_at_utc for item in all_candles):
            raise ValueError("future candle leakage in target evidence")
        return self


class StructuralTargetAuthorityV1(FrozenTradePlanContract):
    target_id: str = Field(..., pattern=r"^5scr-target:[0-9a-f]{32}$")
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_target_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    target_kind: TargetKind
    target_price: Decimal = Field(..., gt=0)
    left_candle_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    pivot_candle_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    right_candle_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    left_material_candle_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    pivot_material_candle_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    right_material_candle_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    formed_at_utc: datetime
    consumed_at_utc: datetime | None = None
    consumed_by_h1_candle_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    target_map_version: str = Field(..., min_length=3, max_length=100)
    execution_authority: Literal[False] = False

    @field_validator("formed_at_utc", "consumed_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _consumption_is_atomic(self) -> StructuralTargetAuthorityV1:
        if (self.consumed_at_utc is None) != (self.consumed_by_h1_candle_id is None):
            raise ValueError("target consumption clock and H1 proof must be present together")
        if self.consumed_at_utc is not None and self.consumed_at_utc <= self.formed_at_utc:
            raise ValueError("target consumption must follow formation")
        expected_material_hash = structural_target_material_hash_v1(
            symbol=self.symbol,
            direction=self.direction,
            target_kind=self.target_kind,
            target_price=self.target_price,
            left_material_candle_hash=self.left_material_candle_hash,
            pivot_material_candle_hash=self.pivot_material_candle_hash,
            right_material_candle_hash=self.right_material_candle_hash,
            formed_at_utc=self.formed_at_utc,
            target_map_version=self.target_map_version,
        )
        if self.material_target_hash != expected_material_hash:
            raise ValueError("structural target material hash mismatch")
        expected_id = "5scr-target:" + hashlib.sha256(self.material_target_hash.encode()).hexdigest()[:32]
        if self.target_id != expected_id:
            raise ValueError("structural target ID does not match its pivot authority")
        expected_hash = canonical_hash_v1(self.model_dump(mode="json", exclude={"authority_hash"}))
        if self.authority_hash not in {_HASH_SENTINEL, expected_hash}:
            raise ValueError("structural target authority hash mismatch")
        object.__setattr__(self, "authority_hash", expected_hash)
        return self


def structural_target_material_hash_v1(
    *,
    symbol: str,
    direction: Direction,
    target_kind: TargetKind,
    target_price: Decimal,
    left_material_candle_hash: str,
    pivot_material_candle_hash: str,
    right_material_candle_hash: str,
    formed_at_utc: datetime,
    target_map_version: str,
) -> str:
    """Hash strategy-material target facts, excluding provider/row lineage."""

    return canonical_hash_v1(
        {
            "symbol": symbol,
            "direction": direction,
            "target_kind": target_kind,
            "target_price": target_price,
            "left_material_candle_hash": left_material_candle_hash,
            "pivot_material_candle_hash": pivot_material_candle_hash,
            "right_material_candle_hash": right_material_candle_hash,
            "formed_at_utc": formed_at_utc,
            "target_map_version": target_map_version,
        }
    )


class StructuralTargetMapAuthorityV1(FrozenTradePlanContract):
    target_map_id: str = Field(..., pattern=r"^5scr-target-map:[0-9a-f]{32}$")
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    target_map_version: str = Field(..., min_length=3, max_length=100)
    source_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    selection_anchor_price: Decimal = Field(..., gt=0)
    selected_target_id: str | None = Field(default=None, pattern=r"^5scr-target:[0-9a-f]{32}$")
    targets: tuple[StructuralTargetAuthorityV1, ...]
    latest_h4_confirmation_at_utc: datetime
    decision_at_utc: datetime
    execution_authority: Literal[False] = False

    @field_validator("latest_h4_confirmation_at_utc", "decision_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "target map time")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _map_authority_is_coherent(self) -> StructuralTargetMapAuthorityV1:
        if self.latest_h4_confirmation_at_utc > self.decision_at_utc:
            raise ValueError("target-map confirmation cannot be in the future")
        if any(
            item.symbol != self.symbol
            or item.direction != self.direction
            or item.target_map_version != self.target_map_version
            or item.target_kind != ("H4_STRICT_SWING_HIGH" if self.direction == "BUY" else "H4_STRICT_SWING_LOW")
            or (
                item.target_price <= self.selection_anchor_price
                if self.direction == "BUY"
                else item.target_price >= self.selection_anchor_price
            )
            for item in self.targets
        ):
            raise ValueError("target-map target scope mismatch")
        expected_order = tuple(
            sorted(
                self.targets,
                key=lambda item: (
                    abs(item.target_price - self.selection_anchor_price),
                    item.formed_at_utc,
                    item.material_target_hash,
                ),
            )
        )
        if self.targets != expected_order or len({item.target_id for item in self.targets}) != len(self.targets):
            raise ValueError("target-map targets must use canonical nearest-first order")
        expected_selected = next((item.target_id for item in self.targets if item.consumed_at_utc is None), None)
        if self.selected_target_id != expected_selected:
            raise ValueError("selected target must be the nearest unconsumed map target")
        expected_hash = structural_target_map_authority_hash_v1(self)
        expected_id = "5scr-target-map:" + hashlib.sha256(expected_hash.encode()).hexdigest()[:32]
        if self.authority_hash != expected_hash or self.target_map_id != expected_id:
            raise ValueError("structural target-map authority integrity mismatch")
        return self


def structural_target_map_authority_hash_v1(authority: StructuralTargetMapAuthorityV1) -> str:
    return canonical_hash_v1(authority.model_dump(mode="json", exclude={"target_map_id", "authority_hash"}))


class BrokerGeometryCostAuthorityV1(FrozenTradePlanContract):
    authority_id: str = Field(..., min_length=3, max_length=200)
    authority_hash: str = Field(default=_HASH_SENTINEL, pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32)
    captured_at_utc: datetime
    valid_until_utc: datetime
    digits: int = Field(..., ge=0, le=12)
    point: Decimal = Field(..., gt=0)
    tick_size: Decimal = Field(..., gt=0)
    pip_size: Decimal = Field(..., gt=0)
    spread_price: Decimal = Field(..., ge=0)
    cost_policy_id: Literal["ESTIMATED_STRATEGY_COST_V1"] = COST_POLICY_ID
    cost_authority: Literal["ESTIMATED_NOT_BROKER"] = "ESTIMATED_NOT_BROKER"
    requires_risk_revalidation: Literal[True] = True
    account_id: None = None
    execution_authority: Literal[False] = False

    @field_validator("captured_at_utc", "valid_until_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _geometry_is_coherent(self) -> BrokerGeometryCostAuthorityV1:
        if self.valid_until_utc <= self.captured_at_utc:
            raise ValueError("cost authority validity must follow capture")
        if self.point > self.tick_size:
            raise ValueError("point cannot exceed tick size")
        expected_point = Decimal("1").scaleb(-self.digits)
        if self.point != expected_point or self.tick_size % self.point != 0 or self.pip_size % self.point != 0:
            raise ValueError("broker digits/point/tick/pip geometry is incoherent")
        expected = canonical_hash_v1(self.model_dump(mode="json", exclude={"authority_hash"}))
        if self.authority_hash not in {_HASH_SENTINEL, expected}:
            raise ValueError("broker geometry/cost authority hash mismatch")
        object.__setattr__(self, "authority_hash", expected)
        return self


def broker_geometry_material_hash_v1(authority: BrokerGeometryCostAuthorityV1) -> str:
    """Hash strategy-relevant broker geometry, excluding capture/expiry lineage clocks."""

    return canonical_hash_v1(
        authority.model_dump(
            mode="json",
            include={
                "symbol",
                "digits",
                "point",
                "tick_size",
                "pip_size",
                "spread_price",
                "cost_policy_id",
                "cost_authority",
                "requires_risk_revalidation",
            },
        )
    )


class PriceIntervalV1(FrozenTradePlanContract):
    low: Decimal = Field(..., gt=0)
    high: Decimal = Field(..., gt=0)
    source: str = Field(..., min_length=2, max_length=100)

    @model_validator(mode="after")
    def _ordered(self) -> PriceIntervalV1:
        if self.high < self.low:
            raise ValueError("price interval is empty")
        return self


class StructuralStopAuthorityV1(FrozenTradePlanContract):
    authority_id: str = Field(..., pattern=r"^5scr-stop:[0-9a-f]{32}$")
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    direction: Direction
    policy_id: Literal["P5_ROUTE_EXTREME_1_TICK_V1"] = STOP_POLICY_ID
    route_extreme: Decimal = Field(..., gt=0)
    buffer_price: Decimal = Field(..., gt=0)
    structural_stop_price: Decimal = Field(..., gt=0)
    execution_authority: Literal[False] = False


class TradePlanCandidateV2(FrozenTradePlanContract):
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    candidate_sequence: int = Field(..., ge=1)
    candidate_revision: int = Field(default=1, ge=1)
    previous_tradeplan_id: str | None = Field(default=None, pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_freeze_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    box_sequence: int = Field(..., ge=1)
    box_version: int = Field(..., ge=1)
    symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    route_type: str = Field(..., min_length=2, max_length=120)
    decision_at_utc: datetime
    lifecycle_state: CandidateLifecycleState = "ACTIVE"
    target_authority: StructuralTargetAuthorityV1
    target_map_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    stop_authority: StructuralStopAuthorityV1
    broker_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_geometry_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_digits: int = Field(..., ge=0, le=12)
    broker_point: Decimal = Field(..., gt=0)
    broker_tick_size: Decimal = Field(..., gt=0)
    broker_pip_size: Decimal = Field(..., gt=0)
    broker_spread_price: Decimal = Field(..., ge=0)
    structural_interval: PriceIntervalV1
    route_interval: PriceIntervalV1
    target_room_interval: PriceIntervalV1
    cost_room_interval: PriceIntervalV1
    rr_interval: PriceIntervalV1
    feasible_interval: PriceIntervalV1
    candidate_price: Decimal = Field(..., gt=0)
    target_distance_pips: Decimal = Field(..., ge=0)
    risk_distance_pips: Decimal = Field(..., gt=0)
    gross_rr: Decimal = Field(..., ge=Decimal("1.5"))
    execution_policy_id: Literal["FX_MIN_TARGET_10P_V1"] = "FX_MIN_TARGET_10P_V1"
    minimum_target_pips: Decimal = Decimal("10")
    minimum_rr: Decimal = Decimal("1.5")
    material_candidate_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: Literal["5scr.tradeplan-candidate.v2"] = TRADEPLAN_CANDIDATE_V2_RULE_VERSION
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False
    next_required_stage: Literal["RISK_RESERVATION"] = "RISK_RESERVATION"

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "decision_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _candidate_identity_is_coherent(self) -> TradePlanCandidateV2:
        if self.candidate_sequence == 1 and self.previous_tradeplan_id is not None:
            raise ValueError("first candidate occurrence cannot reference a predecessor")
        if self.candidate_sequence > 1 and self.previous_tradeplan_id is None:
            raise ValueError("successor candidate occurrence requires predecessor")
        if self.candidate_revision != 1:
            raise ValueError("immutable candidate occurrences always use revision one")
        if self.target_map_authority_hash == self.stop_authority.authority_hash:
            raise ValueError("target and stop authorities must be independent")
        if (
            self.target_authority.symbol != self.symbol
            or self.target_authority.direction != self.direction
            or self.stop_authority.execution_box_id != self.execution_box_id
            or self.stop_authority.direction != self.direction
        ):
            raise ValueError("candidate target/stop authority scope mismatch")
        expected_stop_payload = {
            "execution_box_id": self.execution_box_id,
            "execution_box_material_hash": self.execution_box_material_hash,
            "freeze_authority_hash": self.execution_box_freeze_authority_hash,
            "direction": self.direction,
            "policy_id": self.stop_authority.policy_id,
            "route_extreme": self.stop_authority.route_extreme,
            "buffer_price": self.stop_authority.buffer_price,
            "structural_stop_price": self.stop_authority.structural_stop_price,
        }
        expected_stop_hash = canonical_hash_v1(expected_stop_payload)
        expected_stop_id = "5scr-stop:" + hashlib.sha256(expected_stop_hash.encode()).hexdigest()[:32]
        if (
            self.stop_authority.authority_hash != expected_stop_hash
            or self.stop_authority.authority_id != expected_stop_id
        ):
            raise ValueError("structural stop authority integrity mismatch")
        expected_extreme = self.route_interval.low if self.direction == "BUY" else self.route_interval.high
        if self.stop_authority.route_extreme != expected_extreme:
            raise ValueError("structural stop must bind the exact route extreme")
        if not self.feasible_interval.low <= self.candidate_price <= self.feasible_interval.high:
            raise ValueError("candidate price must remain inside the feasible interval")
        if self.direction == "BUY" and not (
            self.stop_authority.structural_stop_price < self.candidate_price < self.target_authority.target_price
        ):
            raise ValueError("BUY candidate target/entry/stop geometry is invalid")
        if self.direction == "SELL" and not (
            self.target_authority.target_price < self.candidate_price < self.stop_authority.structural_stop_price
        ):
            raise ValueError("SELL candidate target/entry/stop geometry is invalid")
        if self.minimum_target_pips != Decimal("10") or self.minimum_rr != Decimal("1.5"):
            raise ValueError("candidate policy thresholds do not match FX_MIN_TARGET_10P_V1")
        broker_material = canonical_hash_v1(
            {
                "symbol": self.symbol,
                "digits": self.broker_digits,
                "point": self.broker_point,
                "tick_size": self.broker_tick_size,
                "pip_size": self.broker_pip_size,
                "spread_price": self.broker_spread_price,
                "cost_policy_id": COST_POLICY_ID,
                "cost_authority": "ESTIMATED_NOT_BROKER",
                "requires_risk_revalidation": True,
            }
        )
        if self.broker_geometry_material_hash != broker_material:
            raise ValueError("broker geometry material hash mismatch")
        grid_values = (
            self.route_interval.low,
            self.route_interval.high,
            self.structural_interval.low,
            self.structural_interval.high,
            self.target_room_interval.low,
            self.target_room_interval.high,
            self.cost_room_interval.low,
            self.cost_room_interval.high,
            self.rr_interval.low,
            self.rr_interval.high,
            self.feasible_interval.low,
            self.feasible_interval.high,
            self.candidate_price,
            self.target_authority.target_price,
            self.stop_authority.route_extreme,
            self.stop_authority.structural_stop_price,
        )
        if any(value % self.broker_tick_size != 0 for value in grid_values):
            raise ValueError("candidate price geometry must lie on the broker tick grid")
        expected_target_distance = abs(self.target_authority.target_price - self.candidate_price)
        expected_risk_distance = abs(self.candidate_price - self.stop_authority.structural_stop_price)
        canonical_gross_rr = canonical_tradeplan_numeric_v2(self.target_distance_pips / self.risk_distance_pips)
        if (
            self.target_distance_pips < self.minimum_target_pips
            or self.gross_rr != canonical_gross_rr
            or self.target_distance_pips != expected_target_distance / self.broker_pip_size
            or self.risk_distance_pips != expected_risk_distance / self.broker_pip_size
        ):
            raise ValueError("candidate distance/RR evidence is incoherent")
        expected_material_hash = tradeplan_candidate_material_hash_v2(self)
        if self.material_candidate_hash != expected_material_hash:
            raise ValueError("tradeplan material candidate hash mismatch")
        expected_id = (
            "5scr-tradeplan-v2:"
            + hashlib.sha256(
                (
                    f"{self.execution_box_id}|{self.candidate_sequence}|{self.candidate_revision}|"
                    f"{self.material_candidate_hash}|{self.rule_version}"
                ).encode()
            ).hexdigest()[:32]
        )
        if self.tradeplan_id != expected_id:
            raise ValueError("tradeplan ID does not match occurrence and material identity")
        return self


def tradeplan_candidate_material_hash_v2(candidate: TradePlanCandidateV2) -> str:
    """Recompute immutable strategy material without observation-only target-map churn."""

    return canonical_hash_v1(
        {
            "context_material_hash": candidate.material_context_hash,
            "thesis_semantic_identity_hash": candidate.thesis_semantic_identity_hash,
            "execution_box_id": candidate.execution_box_id,
            "execution_box_material_hash": candidate.execution_box_material_hash,
            "execution_box_freeze_authority_hash": candidate.execution_box_freeze_authority_hash,
            # The selected target authority is material.  The full target-map
            # authority is retained separately for lineage because a later
            # neutral H1 close may extend coverage without changing the plan.
            "material_target_hash": candidate.target_authority.material_target_hash,
            "stop_authority_hash": candidate.stop_authority.authority_hash,
            "broker_geometry_material_hash": candidate.broker_geometry_material_hash,
            "intervals": [
                item.model_dump(mode="json")
                for item in (
                    candidate.structural_interval,
                    candidate.route_interval,
                    candidate.target_room_interval,
                    candidate.cost_room_interval,
                    candidate.rr_interval,
                    candidate.feasible_interval,
                )
            ],
            "candidate_price": candidate.candidate_price,
            "execution_policy_id": candidate.execution_policy_id,
            "rule_version": candidate.rule_version,
        }
    )


class TradePlanCandidateTransitionV2(FrozenTradePlanContract):
    transition_id: str = Field(..., pattern=r"^5scr-tradeplan-transition:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    from_state: Literal["ACTIVE"]
    to_state: Literal["SUPERSEDED", "INVALIDATED", "EXPIRED"]
    reason_code: str = Field(..., min_length=3, max_length=120)
    occurred_at_utc: datetime
    successor_tradeplan_id: str | None = Field(default=None, pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @field_validator("occurred_at_utc")
    @classmethod
    def _occurred_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "occurred_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _transition_authority_is_coherent(self) -> TradePlanCandidateTransitionV2:
        if (self.to_state == "SUPERSEDED") != (self.successor_tradeplan_id is not None):
            raise ValueError("only SUPERSEDED transition may identify a successor")
        expected_hash = canonical_hash_v1(
            {
                "from": self.tradeplan_id,
                "to": self.successor_tradeplan_id,
                "occurred_at": self.occurred_at_utc,
                "reason": self.reason_code,
            }
        )
        expected_id = "5scr-tradeplan-transition:" + hashlib.sha256(expected_hash.encode()).hexdigest()[:32]
        if self.authority_hash != expected_hash or self.transition_id != expected_id:
            raise ValueError("tradeplan transition authority integrity mismatch")
        return self


class TradePlanEvaluationV2(FrozenTradePlanContract):
    evaluation_id: str = Field(..., pattern=r"^5scr-tradeplan-eval:[0-9a-f]{32}$")
    evaluation_sequence: int = Field(..., ge=1)
    source_request_id: str = Field(..., min_length=1, max_length=240)
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_freeze_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    decision_at_utc: datetime
    decision: PersistedEvaluationDecision
    reason_codes: tuple[str, ...] = Field(..., min_length=1)
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_evaluation_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    result_tradeplan_id: str | None = Field(default=None, pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    rule_version: Literal["5scr.tradeplan-candidate.v2"] = TRADEPLAN_CANDIDATE_V2_RULE_VERSION
    execution_authority: Literal[False] = False

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "decision_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _result_shape_is_valid(self) -> TradePlanEvaluationV2:
        if self.reason_codes != tuple(dict.fromkeys(self.reason_codes)):
            raise ValueError("evaluation reason codes must be ordered and unique")
        if (self.decision == "CANDIDATE") != (self.result_tradeplan_id is not None):
            raise ValueError("only CANDIDATE evaluation may link a tradeplan")
        return self


class TradePlanCandidateBuildEvidenceV2(FrozenTradePlanContract):
    source_request_id: str = Field(..., min_length=1, max_length=240)
    decision_at_utc: datetime
    target_map_evidence: StructuralTargetMapEvidenceV1
    broker_geometry: BrokerGeometryCostAuthorityV1
    source_deployment_id: str | None = Field(default=None, max_length=200)
    source_replica_id: str | None = Field(default=None, max_length=200)
    execution_authority: Literal[False] = False

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "decision_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _clocks_match(self) -> TradePlanCandidateBuildEvidenceV2:
        if self.target_map_evidence.decision_at_utc != self.decision_at_utc:
            raise ValueError("target-map and build decision clocks must match")
        return self


class TradePlanCandidateReductionResultV2(FrozenTradePlanContract):
    decision: EvaluationDecision
    reason_code: str
    evaluation: TradePlanEvaluationV2 | None = None
    candidate: TradePlanCandidateV2 | None = None
    previous_candidate: TradePlanCandidateV2 | None = None
    transition: TradePlanCandidateTransitionV2 | None = None
    target_map: StructuralTargetMapAuthorityV1 | None = None

    @model_validator(mode="after")
    def _reduction_shape_is_coherent(self) -> TradePlanCandidateReductionResultV2:
        if self.transition is None:
            if self.previous_candidate is not None:
                raise ValueError("previous candidate requires an explicit transition")
            return self
        if self.previous_candidate is None or self.transition.tradeplan_id != self.previous_candidate.tradeplan_id:
            raise ValueError("transition must bind the exact previous candidate")
        if self.transition.occurred_at_utc < self.previous_candidate.decision_at_utc:
            raise ValueError("transition cannot predate its candidate")
        if self.transition.to_state == "SUPERSEDED":
            if (
                self.decision != "CANDIDATE"
                or self.candidate is None
                or self.transition.successor_tradeplan_id != self.candidate.tradeplan_id
            ):
                raise ValueError("SUPERSEDED transition requires its material successor")
        elif self.transition.to_state == "INVALIDATED" and (self.decision != "NO_TRADE" or self.candidate is not None):
            raise ValueError("INVALIDATED transition requires a NO_TRADE result without successor")
        return self


__all__ = [
    "BrokerGeometryCostAuthorityV1",
    "CandidateLifecycleState",
    "COST_POLICY_ID",
    "EvaluationDecision",
    "PriceIntervalV1",
    "STOP_POLICY_ID",
    "StructuralCandleAuthorityV1",
    "StructuralStopAuthorityV1",
    "StructuralTargetAuthorityV1",
    "StructuralTargetMapAuthorityV1",
    "StructuralTargetMapEvidenceV1",
    "structural_target_map_authority_hash_v1",
    "structural_target_material_hash_v1",
    "TARGET_COHORT_POLICY_ID",
    "TARGET_FRESHNESS_POLICY_ID",
    "TARGET_MAP_RULE_VERSION",
    "TRADEPLAN_CANDIDATE_V2_RULE_VERSION",
    "TradePlanCandidateBuildEvidenceV2",
    "TradePlanCandidateReductionResultV2",
    "TradePlanCandidateTransitionV2",
    "TradePlanCandidateV2",
    "TradePlanEvaluationV2",
    "canonical_hash_v1",
    "broker_geometry_material_hash_v1",
    "tradeplan_candidate_material_hash_v2",
]
