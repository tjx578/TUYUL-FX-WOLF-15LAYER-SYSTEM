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


class ExecutionBoxEvidenceV1(FrozenExecutionBoxContract):
    """One candidate material geometry observation for an active thesis."""

    contract_version: Literal["5scr.execution-box-evidence.v1"] = EXECUTION_BOX_EVIDENCE_VERSION
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    route_type: str = Field(..., min_length=2, max_length=120)
    observed_at_utc: datetime
    material_m1_candles: tuple[M1CandleAuthorityV1, ...]
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
        if not self.material_m1_candles:
            raise ValueError("execution box evidence requires material M1 candles")
        identity = tuple((item.open_time_utc, item.material_candle_hash) for item in self.material_m1_candles)
        if identity != tuple(sorted(identity)):
            raise ValueError("material M1 candles must be ordered")
        if len({item.material_candle_hash for item in self.material_m1_candles}) != len(self.material_m1_candles):
            raise ValueError("material M1 candles must be unique")
        if any(item.symbol != self.symbol for item in self.material_m1_candles):
            raise ValueError("material M1 candle scope mismatch")
        if any(item.close_time_utc > self.observed_at_utc for item in self.material_m1_candles):
            raise ValueError("future M1 candle leakage")
        for previous, current in zip(self.material_m1_candles, self.material_m1_candles[1:], strict=False):
            if previous.close_time_utc != current.open_time_utc:
                raise ValueError("material M1 candle coverage must be contiguous")
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
            "observed_at_utc": evidence.observed_at_utc,
            "source_m1_material_hashes": [item.material_candle_hash for item in evidence.material_m1_candles],
            "freeze_reason": evidence.freeze_reason,
            "rule_version": EXECUTION_BOX_RULE_VERSION,
        }
    )


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
        return self


__all__ = [
    "EXECUTION_BOX_EVIDENCE_VERSION",
    "EXECUTION_BOX_RULE_VERSION",
    "Direction",
    "ExecutionBoxEvidenceV1",
    "ExecutionBoxState",
    "ExecutionBoxV1",
    "M1CandleAuthorityV1",
    "execution_box_freeze_authority_hash",
]
