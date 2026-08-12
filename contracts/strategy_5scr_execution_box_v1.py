"""Shadow-only contracts for versioned Strategy 5S-CR execution geometry.

P5 freezes *where* one already-valid directional thesis may be observed on M1.
It deliberately does not answer whether to enter, where to place a stop/target,
how much to risk, or whether any broker action is authorised.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXECUTION_BOX_RULE_VERSION = "5scr.execution-box.v1"
EXECUTION_BOX_EVIDENCE_VERSION = "5scr.execution-box-evidence.v1"

Direction = Literal["BUY", "SELL"]
ExecutionBoxRouteType = Literal["BUY_BREAK_RETEST", "SELL_BREAK_RETEST"]
ExecutionBoxGeometryKind = Literal["BREAK_RETEST_INTERVAL"]
ExecutionBoxState = Literal[
    "BUILDING",
    "FROZEN",
    "SUPERSEDED",
    "INVALIDATED",
    "CONSUMED",
    "EXPIRED",
]


class FrozenExecutionBoxContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class M1CandleAuthorityV1(FrozenExecutionBoxContract):
    """Frozen M1 OHLC content plus lineage from a canonical selection row."""

    candle_evidence_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_candle_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_content_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_row_id: int | None = Field(default=None, ge=1)
    selected_raw_candle_id: int | None = Field(default=None, ge=1)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    timeframe: Literal["M1"] = "M1"
    open_time_utc: datetime
    close_time_utc: datetime
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(default=0, ge=0)
    tick_count: int = Field(default=0, ge=0)
    provider: str = Field(..., min_length=2, max_length=100)
    feed: str = Field(..., min_length=1, max_length=100)
    provider_timestamp_semantics: Literal["PERIOD_OPEN", "PERIOD_END", "CANONICAL_WINDOW"]
    selection_policy: str = Field(..., min_length=3, max_length=100)
    selection_rank: int = Field(..., ge=0)
    is_closed: Literal[True] = True
    price_authority: Literal[True] = True

    @field_validator("open_time_utc", "close_time_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _numbers_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("M1 candle numbers must be finite")
        return value

    @model_validator(mode="after")
    def _candle_is_coherent(self) -> M1CandleAuthorityV1:
        if self.close_time_utc - self.open_time_utc != timedelta(minutes=1):
            raise ValueError("M1 authority window must be exactly one minute")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("M1 candle high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("M1 candle low is inconsistent with OHLC")
        expected_material = _sha256(
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
        if self.material_candle_hash != expected_material:
            raise ValueError("M1 material candle hash does not match frozen OHLC")
        payload = self.model_dump(mode="json", exclude={"candle_evidence_id"})
        if self.candle_evidence_id != _sha256(payload):
            raise ValueError("M1 candle evidence hash does not match frozen evidence")
        return self


class ExecutionBoxRouteGeometryAuthorityV1(FrozenExecutionBoxContract):
    """Typed, reproducible BREAK_RETEST geometry selected from canonical M1 evidence."""

    geometry_kind: ExecutionBoxGeometryKind = "BREAK_RETEST_INTERVAL"
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    route_type: ExecutionBoxRouteType
    reference_candle_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    break_candle_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    retest_candle_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    acceptance_candle_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    route_low: float = Field(..., gt=0)
    route_high: float = Field(..., gt=0)
    authority_hash: str = Field(default="sha256:" + "0" * 64, pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: Literal["5scr.execution-box-route-geometry.v1"] = "5scr.execution-box-route-geometry.v1"
    execution_authority: Literal[False] = False

    @field_validator("route_low", "route_high")
    @classmethod
    def _bounds_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("route geometry bounds must be finite")
        return value

    @model_validator(mode="after")
    def _authority_is_coherent(self) -> ExecutionBoxRouteGeometryAuthorityV1:
        expected_route = f"{self.strategy_direction}_BREAK_RETEST"
        if self.route_type != expected_route:
            raise ValueError("BREAK_RETEST route must match strategy direction")
        role_ids = (
            self.reference_candle_material_hash,
            self.break_candle_material_hash,
            self.retest_candle_material_hash,
            self.acceptance_candle_material_hash,
        )
        if len(set(role_ids)) != len(role_ids):
            raise ValueError("reference, break, retest, and acceptance roles require distinct M1 candles")
        if self.route_high <= self.route_low:
            raise ValueError("route geometry high must exceed low")
        expected_hash = execution_box_route_geometry_authority_hash(self)
        sentinel = "sha256:" + "0" * 64
        if self.authority_hash not in {sentinel, expected_hash}:
            raise ValueError("route geometry authority hash does not match material geometry")
        object.__setattr__(self, "authority_hash", expected_hash)
        return self


def execution_box_route_geometry_authority_hash(
    authority: ExecutionBoxRouteGeometryAuthorityV1,
) -> str:
    """Bind a route interval to exact thesis scope and M1 structural roles."""

    return _sha256(
        authority.model_dump(
            mode="json",
            exclude={"authority_hash", "execution_authority"},
        )
    )


def _derive_break_retest_bounds(
    *,
    direction: Direction,
    reference_candle: M1CandleAuthorityV1,
    break_candle: M1CandleAuthorityV1,
    retest_candle: M1CandleAuthorityV1,
    acceptance_candle: M1CandleAuthorityV1,
) -> tuple[float, float]:
    """Derive one legal retest interval; caller-supplied arbitrary bounds are forbidden."""

    if not (
        reference_candle.open_time_utc
        < break_candle.open_time_utc
        < retest_candle.open_time_utc
        < acceptance_candle.open_time_utc
    ):
        raise ValueError("reference, break, retest, and acceptance M1 roles must be strictly ordered")
    if direction == "BUY":
        break_level = reference_candle.high
        if break_candle.close <= max(break_candle.open, break_level):
            raise ValueError("BUY break candle must close bullish through the reference high")
        if not (retest_candle.low < break_level <= retest_candle.high and retest_candle.close >= break_level):
            raise ValueError("BUY retest candle must test and hold the break level")
        if acceptance_candle.close <= break_level or acceptance_candle.close <= acceptance_candle.open:
            raise ValueError("BUY acceptance candle must close bullish beyond the break level")
        return retest_candle.low, break_level
    break_level = reference_candle.low
    if break_candle.close >= min(break_candle.open, break_level):
        raise ValueError("SELL break candle must close bearish through the reference low")
    if not (retest_candle.low <= break_level < retest_candle.high and retest_candle.close <= break_level):
        raise ValueError("SELL retest candle must test and reject the break level")
    if acceptance_candle.close >= break_level or acceptance_candle.close >= acceptance_candle.open:
        raise ValueError("SELL acceptance candle must close bearish beyond the break level")
    return break_level, retest_candle.high


def derive_execution_box_route_geometry_authority(
    *,
    context_epoch_id: str,
    strategy_thesis_id: str,
    symbol: str,
    strategy_direction: Direction,
    route_type: ExecutionBoxRouteType,
    material_m1_candles: tuple[M1CandleAuthorityV1, ...],
    reference_candle_material_hash: str,
    break_candle_material_hash: str,
    retest_candle_material_hash: str,
    acceptance_candle_material_hash: str,
) -> ExecutionBoxRouteGeometryAuthorityV1:
    """Build typed route geometry by resolving its roles from frozen candle evidence."""

    by_hash = {item.material_candle_hash: item for item in material_m1_candles}
    try:
        reference_candle = by_hash[reference_candle_material_hash]
        break_candle = by_hash[break_candle_material_hash]
        retest_candle = by_hash[retest_candle_material_hash]
        acceptance_candle = by_hash[acceptance_candle_material_hash]
    except KeyError as exc:
        raise ValueError("route geometry role is absent from material M1 evidence") from exc
    route_low, route_high = _derive_break_retest_bounds(
        direction=strategy_direction,
        reference_candle=reference_candle,
        break_candle=break_candle,
        retest_candle=retest_candle,
        acceptance_candle=acceptance_candle,
    )
    return ExecutionBoxRouteGeometryAuthorityV1(
        context_epoch_id=context_epoch_id,
        strategy_thesis_id=strategy_thesis_id,
        symbol=symbol,
        strategy_direction=strategy_direction,
        route_type=route_type,
        reference_candle_material_hash=reference_candle_material_hash,
        break_candle_material_hash=break_candle_material_hash,
        retest_candle_material_hash=retest_candle_material_hash,
        acceptance_candle_material_hash=acceptance_candle_material_hash,
        route_low=route_low,
        route_high=route_high,
    )


class ExecutionBoxEvidenceV1(FrozenExecutionBoxContract):
    """One candidate material geometry observation for an active thesis."""

    contract_version: Literal["5scr.execution-box-evidence.v1"] = EXECUTION_BOX_EVIDENCE_VERSION
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    route_type: ExecutionBoxRouteType
    observed_at_utc: datetime
    material_m1_candles: tuple[M1CandleAuthorityV1, ...]
    route_geometry_authority: ExecutionBoxRouteGeometryAuthorityV1
    freeze_requested: bool = False
    freeze_reason: Literal["M1_ROUTE_GEOMETRY_CONFIRMED"] | None = None
    freeze_authority_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_request_id: str | None = Field(default=None, max_length=240)
    source_deployment_id: str | None = Field(default=None, max_length=200)
    source_replica_id: str | None = Field(default=None, max_length=200)
    source_cluster_id: str | None = Field(default=None, max_length=240)
    source_stage: str | None = Field(default=None, max_length=100)
    source_family: str | None = Field(default=None, max_length=100)
    telemetry_count: int = Field(default=0, ge=0)
    reference_price: float | None = Field(default=None, gt=0)
    execution_authority: Literal[False] = False

    @field_validator("observed_at_utc")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "observed_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _evidence_is_coherent(self) -> ExecutionBoxEvidenceV1:
        if len(self.material_m1_candles) != 4:
            raise ValueError("BREAK_RETEST evidence requires exactly four material M1 role candles")
        identity = tuple((item.open_time_utc, item.material_candle_hash) for item in self.material_m1_candles)
        if identity != tuple(sorted(identity)):
            raise ValueError("material M1 candles must be ordered")
        if len({item.material_candle_hash for item in self.material_m1_candles}) != len(self.material_m1_candles):
            raise ValueError("material M1 candles must be unique")
        if any(item.symbol != self.symbol for item in self.material_m1_candles):
            raise ValueError("material M1 candle scope mismatch")
        if any(
            item.canonical_row_id is None or item.selected_raw_candle_id is None for item in self.material_m1_candles
        ):
            raise ValueError("material M1 candles require canonical and selected-raw identities")
        if any(item.close_time_utc > self.observed_at_utc for item in self.material_m1_candles):
            raise ValueError("future M1 candle leakage")
        for previous, current in zip(self.material_m1_candles, self.material_m1_candles[1:], strict=False):
            if previous.close_time_utc != current.open_time_utc:
                raise ValueError("material M1 candle coverage must be contiguous")
        geometry = self.route_geometry_authority
        geometry_scope = (
            geometry.context_epoch_id,
            geometry.strategy_thesis_id,
            geometry.symbol,
            geometry.strategy_direction,
            geometry.route_type,
        )
        evidence_scope = (
            self.context_epoch_id,
            self.strategy_thesis_id,
            self.symbol,
            self.strategy_direction,
            self.route_type,
        )
        if geometry_scope != evidence_scope:
            raise ValueError("route geometry authority scope mismatch")
        role_order = (
            geometry.reference_candle_material_hash,
            geometry.break_candle_material_hash,
            geometry.retest_candle_material_hash,
            geometry.acceptance_candle_material_hash,
        )
        if tuple(item.material_candle_hash for item in self.material_m1_candles) != role_order:
            raise ValueError("material M1 candles must exactly match reference, break, retest, acceptance roles")
        expected_geometry = derive_execution_box_route_geometry_authority(
            context_epoch_id=self.context_epoch_id,
            strategy_thesis_id=self.strategy_thesis_id,
            symbol=self.symbol,
            strategy_direction=self.strategy_direction,
            route_type=self.route_type,
            material_m1_candles=self.material_m1_candles,
            reference_candle_material_hash=geometry.reference_candle_material_hash,
            break_candle_material_hash=geometry.break_candle_material_hash,
            retest_candle_material_hash=geometry.retest_candle_material_hash,
            acceptance_candle_material_hash=geometry.acceptance_candle_material_hash,
        )
        if geometry != expected_geometry:
            raise ValueError("route geometry authority does not match canonical M1 roles")
        if self.freeze_requested != (self.freeze_reason is not None and self.freeze_authority_hash is not None):
            raise ValueError("freeze request, reason, and authority hash must be present together")
        if self.freeze_requested and self.freeze_authority_hash != execution_box_freeze_authority_hash(self):
            raise ValueError("freeze authority hash does not match material evidence")
        return self


def execution_box_freeze_authority_hash(evidence: ExecutionBoxEvidenceV1) -> str:
    """Bind a freeze request to its exact parent, route, clock, and M1 material."""

    return _sha256(
        {
            "strategy_lifecycle_id": evidence.strategy_lifecycle_id,
            "context_epoch_id": evidence.context_epoch_id,
            "strategy_thesis_id": evidence.strategy_thesis_id,
            "thesis_semantic_identity_hash": evidence.thesis_semantic_identity_hash,
            "symbol": evidence.symbol,
            "strategy_direction": evidence.strategy_direction,
            "route_type": evidence.route_type,
            "route_geometry_authority_hash": evidence.route_geometry_authority.authority_hash,
            "observed_at_utc": evidence.observed_at_utc,
            "source_m1_material_hashes": [item.material_candle_hash for item in evidence.material_m1_candles],
            "freeze_reason": evidence.freeze_reason,
            "rule_version": EXECUTION_BOX_RULE_VERSION,
        }
    )


def execution_box_identity_v1(
    strategy_thesis_id: str,
    box_sequence: int,
    box_version: int,
    material_box_hash: str,
) -> str:
    """Canonical immutable identity for one box occurrence and material version."""

    basis = f"{strategy_thesis_id}|{box_sequence}|{box_version}|{material_box_hash}"
    return "5scr-execution-box:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


class ExecutionBoxV1(FrozenExecutionBoxContract):
    """One immutable geometry version; only its lifecycle state may advance."""

    contract_version: Literal["5scr.execution-box.v1"] = EXECUTION_BOX_RULE_VERSION
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    box_sequence: int = Field(..., ge=1)
    box_version: int = Field(..., ge=1)
    previous_execution_box_id: str | None = Field(default=None, pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    route_type: str = Field(..., min_length=2, max_length=120)
    state: ExecutionBoxState
    box_low: float = Field(..., gt=0)
    box_high: float = Field(..., gt=0)
    opened_at_utc: datetime
    frozen_at_utc: datetime | None = None
    freeze_authority_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    superseded_at_utc: datetime | None = None
    invalidated_at_utc: datetime | None = None
    consumed_at_utc: datetime | None = None
    expired_at_utc: datetime | None = None
    material_box_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_m1_ids: tuple[str, ...]
    source_m1_evidence_ids: tuple[str, ...]
    last_observed_at_utc: datetime
    last_source_request_id: str | None = Field(default=None, max_length=240)
    state_version: int = Field(default=1, ge=1)
    rule_version: Literal["5scr.execution-box.v1"] = EXECUTION_BOX_RULE_VERSION
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "opened_at_utc",
        "frozen_at_utc",
        "superseded_at_utc",
        "invalidated_at_utc",
        "consumed_at_utc",
        "expired_at_utc",
        "last_observed_at_utc",
    )
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _box_is_coherent(self) -> ExecutionBoxV1:
        if self.box_high <= self.box_low:
            raise ValueError("execution box high must exceed low")
        if not self.source_m1_ids or self.source_m1_ids != tuple(sorted(set(self.source_m1_ids))):
            raise ValueError("source M1 IDs must be non-empty, sorted, and unique")
        if not self.source_m1_evidence_ids or self.source_m1_evidence_ids != tuple(
            sorted(set(self.source_m1_evidence_ids))
        ):
            raise ValueError("source M1 evidence IDs must be non-empty, sorted, and unique")
        if self.last_observed_at_utc < self.opened_at_utc:
            raise ValueError("last observation cannot precede box open")
        terminal_clocks = {
            "SUPERSEDED": self.superseded_at_utc,
            "INVALIDATED": self.invalidated_at_utc,
            "CONSUMED": self.consumed_at_utc,
            "EXPIRED": self.expired_at_utc,
        }
        all_terminal = tuple(value for value in terminal_clocks.values() if value is not None)
        if self.state == "BUILDING":
            if self.frozen_at_utc is not None or self.freeze_authority_hash is not None or all_terminal:
                raise ValueError("building box cannot carry terminal/frozen clocks")
        elif self.state == "FROZEN":
            if self.frozen_at_utc is None or self.freeze_authority_hash is None or all_terminal:
                raise ValueError("frozen box requires only frozen_at")
        else:
            expected = terminal_clocks[self.state]
            if expected is None or sum(value is not None for value in terminal_clocks.values()) != 1:
                raise ValueError("closed box requires exactly its matching terminal clock")
            if self.state == "SUPERSEDED" and self.frozen_at_utc is not None:
                raise ValueError("only a building box may be superseded")
            if self.frozen_at_utc is None and self.freeze_authority_hash is not None:
                raise ValueError("unfrozen terminal box cannot claim freeze authority")
            if self.frozen_at_utc is not None and self.freeze_authority_hash is None:
                raise ValueError("frozen lineage requires freeze authority")
            if self.state == "CONSUMED" and self.frozen_at_utc is None:
                raise ValueError("only a frozen box may be consumed")
        for value in (self.frozen_at_utc, *all_terminal):
            if value is not None and value < self.opened_at_utc:
                raise ValueError("box transition cannot precede opening")
        if self.box_version == 1 and self.previous_execution_box_id is not None:
            raise ValueError("first box version cannot reference a predecessor")
        if self.box_version > 1 and self.previous_execution_box_id is None:
            raise ValueError("successor box version requires predecessor")
        expected_id = execution_box_identity_v1(
            self.strategy_thesis_id,
            self.box_sequence,
            self.box_version,
            self.material_box_hash,
        )
        if self.execution_box_id != expected_id:
            raise ValueError("execution box ID does not match sequence, version, and material identity")
        return self


__all__ = [
    "EXECUTION_BOX_EVIDENCE_VERSION",
    "EXECUTION_BOX_RULE_VERSION",
    "Direction",
    "ExecutionBoxGeometryKind",
    "ExecutionBoxEvidenceV1",
    "ExecutionBoxRouteGeometryAuthorityV1",
    "ExecutionBoxRouteType",
    "ExecutionBoxState",
    "ExecutionBoxV1",
    "M1CandleAuthorityV1",
    "derive_execution_box_route_geometry_authority",
    "execution_box_freeze_authority_hash",
    "execution_box_identity_v1",
    "execution_box_route_geometry_authority_hash",
]
