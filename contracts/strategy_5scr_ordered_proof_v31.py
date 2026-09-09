"""TEST_ONLY ordered proof evidence binding; pattern derivation remains external.

Reuse the established candle format and hashes without converting V1 thesis or
context identities. A content-coherent candle is not an authenticated feed.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from contracts.strategy_5scr_candle_identity import candle_evidence_hash, candle_material_hash
from contracts.strategy_5scr_context_route_v31 import Digest, Direction, Label, content_hash
from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract


class OrderedProofEvidenceV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    strategy_thesis_id: UUID
    strategy_lifecycle_id: UUID
    context_epoch_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    direction: Direction
    selected_route: Label
    context_material_hash: Digest
    pattern_policy_hash: Digest
    level_version: Label
    h1_proof_id: UUID
    m15_proof_id: UUID
    h1_source_candles: tuple[ClosedCandleAuthorityRefV1, ...] = Field(min_length=1, max_length=1000)
    m15_source_candles: tuple[ClosedCandleAuthorityRefV1, ...] = Field(min_length=2, max_length=1000)
    h1_closed_at: datetime
    m15_closed_at: datetime
    m15_break_candle_id: Digest
    m15_completion_candle_id: Digest
    m15_completion_kind: Literal["ACCEPTANCE", "FAILED_RECLAIM", "RETEST"]
    h1_resolution_receipt_hash: Digest
    m15_resolution_receipt_hash: Digest
    evaluated_at: datetime
    valid_until: datetime

    @field_validator("h1_closed_at", "m15_closed_at", "evaluated_at", "valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ORDERED_PROOF_CLOCK_MUST_BE_AWARE")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self):
        if self.h1_proof_id == self.m15_proof_id:
            raise ValueError("ORDERED_PROOF_ID_CONFLICT")
        if not self.h1_closed_at <= self.m15_closed_at <= self.evaluated_at < self.valid_until:
            raise ValueError("ORDERED_PROOF_CLOCK_ORDER_INVALID")
        for timeframe, candles, closed_at in (
            ("H1", self.h1_source_candles, self.h1_closed_at),
            ("M15", self.m15_source_candles, self.m15_closed_at),
        ):
            ids = [c.candle_evidence_id for c in candles]
            times = [c.close_time_utc for c in candles]
            if len(set(ids)) != len(ids) or times != sorted(set(times)):
                raise ValueError("ORDERED_PROOF_CANDLE_ORDER_OR_DUPLICATE")
            if times[-1] != closed_at:
                raise ValueError("ORDERED_PROOF_CLOSE_NOT_BOUND_TO_SOURCE")
            for candle in candles:
                if candle.symbol != self.symbol or candle.timeframe != timeframe:
                    raise ValueError("ORDERED_PROOF_CANDLE_SCOPE_MISMATCH")
                if candle.material_candle_hash != candle_material_hash(
                    candle
                ) or candle.candle_evidence_id != candle_evidence_hash(candle):
                    raise ValueError("ORDERED_PROOF_CANDLE_HASH_MISMATCH")
        by_id = {c.candle_evidence_id: c for c in self.m15_source_candles}
        breaking = by_id.get(self.m15_break_candle_id)
        completion = by_id.get(self.m15_completion_candle_id)
        if (
            breaking is None
            or completion is None
            or not self.h1_closed_at <= breaking.close_time_utc < completion.close_time_utc == self.m15_closed_at
        ):
            raise ValueError("ORDERED_PROOF_BREAK_COMPLETION_NOT_BOUND")
        return self


def ordered_proof_hash_v31(proof: OrderedProofEvidenceV31) -> str:
    proof = OrderedProofEvidenceV31.model_validate(proof.model_dump())
    return content_hash(proof.model_dump(mode="json"))
