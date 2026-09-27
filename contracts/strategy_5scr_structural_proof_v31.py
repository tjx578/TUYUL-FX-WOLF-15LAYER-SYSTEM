"""StructuralProofEvidenceV31: native, thesis-independent structural evidence (gap #10, decisions 2026-09-19).

SSOT §14.3/§14.5: closed H1 structure confirmed → closed M15 structural break → M15 acceptance / failed
reclaim / retest, with H1 ≤ M15 ≤ decision time. This object records that such evidence exists for one route.
It is STRUCTURAL_EVIDENCE_ONLY: it never creates a thesis, never carries legal direction, and has no clock
(existence is permanent; actionability is decided downstream by thesis/stage clocks).

Identity is material-only (no observation, evaluation or validity time). The existing ``OrderedProofEvidenceV31``
is unchanged and will be emitted as a thesis-bound projection by gap #11.
First increment: CONTINUATION only; counter-pressure proof is NOT_IMPLEMENTED_BY_DESIGN.

Requalified on #504 (2026-09-20): the lifecycle is the MarketEpisode-rooted one of the S1B lineage. The identity
tuple is unchanged and stays material-only: no admission id, no admission class, no S1B receipt hash and no
revision ever enters it, so an advisory-to-canonical authority upgrade over the same closed candles reproduces
exactly the same proof. Lineage and progression context live on the evaluation and the lifecycle, not here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1
from contracts.strategy_5scr_identity_v31 import (
    IDENTITY_ENCODING_VERSION,
    canonical_sha256_v31,
    identity_uuid_v31,
)
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31

STRUCTURAL_PROOF_V31_RULE_VERSION = "5scr.structural-proof.v31.v2"
V31_STRUCTURAL_PROOF_NAMESPACE = UUID("ad37bf4a-15d0-4c34-94f8-38fa0aad3e2c")
Direction = Literal["BUY", "SELL"]
CompletionKind = Literal["ACCEPTANCE", "FAILED_RECLAIM", "RETEST"]  # SSOT §14.3 wording
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StructuralPatternV31(_Strict):
    """A named, objective pattern (§14.6). Rules are named predicates; there are no numeric thresholds."""

    pattern_id: str = Field(min_length=3, max_length=120)
    route: str = Field(min_length=1, max_length=160)
    proof_class: Literal["CONTINUATION"]
    h1_witness_count: Literal[2]
    m15_witness_count: Literal[3]
    adjacent_witnesses_required: bool
    h1_rule: Literal["CONFIRMATION_CLOSE_BEYOND_ANCHOR_EXTREME"]
    m15_break_rule: Literal["BREAK_CLOSE_BEYOND_REFERENCE_EXTREME"]
    completion_kinds: tuple[CompletionKind, ...] = Field(min_length=1)


class StructuralPatternRegistryV31(_Strict):
    registry_version: str = Field(min_length=3, max_length=120)
    patterns: tuple[StructuralPatternV31, ...] = Field(min_length=1)
    registry_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> StructuralPatternRegistryV31:
        if len({(p.pattern_id, p.route) for p in self.patterns}) != len(self.patterns):
            raise ValueError("one pattern per (pattern_id, route)")
        body = {k: v for k, v in self.model_dump(mode="json").items() if k != "registry_hash"}
        if self.registry_hash != canonical_sha256_v31(body):
            raise ValueError("STRUCTURAL_PATTERN_REGISTRY_HASH_MISMATCH")
        return self

    def pattern(self, pattern_id: str, route: str) -> StructuralPatternV31 | None:
        return next((p for p in self.patterns if p.pattern_id == pattern_id and p.route == route), None)


def structural_proof_id_v31(
    *,
    strategy_lifecycle_id: UUID,
    context_epoch_id: UUID,
    proof_direction: str,
    selected_route: str,
    level_version: str,
    h1_confirmation_candle_id: str,
    m15_break_candle_id: str,
    m15_completion_candle_id: str,
    m15_completion_kind: str,
    pattern_registry_hash: str,
) -> UUID:
    """Material tuple only: re-observing the same closed candles later yields the same id.

    Deliberately absent: admission id, admission class, admission revision, S1B receipt hash, observation time and
    any clock. Structural evidence is what the market did, not who was allowed to look at it.
    """

    return identity_uuid_v31(
        V31_STRUCTURAL_PROOF_NAMESPACE,
        [
            str(strategy_lifecycle_id),
            str(context_epoch_id),
            proof_direction,
            selected_route,
            level_version,
            h1_confirmation_candle_id,
            m15_break_candle_id,
            m15_completion_candle_id,
            m15_completion_kind,
            pattern_registry_hash,
        ],
    )


class StructuralLevelEvidenceV31(_Strict):
    rule: str
    reference_candle_id: str = Field(pattern=_DIGEST)
    level: float = Field(gt=0)
    evidence_candle_id: str = Field(pattern=_DIGEST)
    evidence_close: float = Field(gt=0)


class StructuralProofEvidenceV31(_Strict):
    rule_version: Literal["5scr.structural-proof.v31.v2"] = STRUCTURAL_PROOF_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    proof_id: UUID
    strategy_lifecycle_id: UUID
    market_episode_id: UUID  # section 8.1 provenance; audit only, never part of the identity tuple
    context_epoch_id: UUID
    context_route_evaluation_id: UUID
    context_route_receipt_hash: str = Field(pattern=_DIGEST)
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    proof_class: Literal["CONTINUATION"]
    proof_direction: Direction
    selected_route: str
    level_version: str = Field(min_length=1, max_length=160)
    pattern_id: str
    pattern_registry_version: str
    pattern_registry_hash: str = Field(pattern=_DIGEST)
    h1_source_candles: tuple[ClosedCandleAuthorityRefV1, ClosedCandleAuthorityRefV1]
    m15_source_candles: tuple[ClosedCandleAuthorityRefV1, ClosedCandleAuthorityRefV1, ClosedCandleAuthorityRefV1]
    h1_closed_at: datetime
    h1_structure_evidence: StructuralLevelEvidenceV31
    m15_break_candle_id: str = Field(pattern=_DIGEST)
    m15_break_evidence: StructuralLevelEvidenceV31
    m15_completion_kind: CompletionKind
    m15_completion_candle_id: str = Field(pattern=_DIGEST)
    m15_closed_at: datetime
    source_evidence_ids: tuple[str, ...] = Field(min_length=5, max_length=5)
    material_evidence_hash: str = Field(pattern=_DIGEST)
    proof_sequence_valid: Literal[True] = True
    authority: Literal["STRUCTURAL_EVIDENCE_ONLY"] = "STRUCTURAL_EVIDENCE_ONLY"
    legal_direction_authority: Literal[False] = False
    thesis_authority: Literal[False] = False
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> StructuralProofEvidenceV31:
        anchor, confirmation = self.h1_source_candles
        reference, breaking, completion = self.m15_source_candles
        # Chronology is an invariant of the positional witnesses, never the result of sorting.
        if not (
            anchor.close_time_utc <= confirmation.close_time_utc == self.h1_closed_at
            and self.h1_closed_at <= breaking.close_time_utc
            and reference.close_time_utc <= breaking.close_time_utc < completion.close_time_utc == self.m15_closed_at
        ):
            raise ValueError("PROOF_SEQUENCE_INVALID")
        if (breaking.candle_evidence_id, completion.candle_evidence_id) != (
            self.m15_break_candle_id,
            self.m15_completion_candle_id,
        ):
            raise ValueError("PROOF_WITNESS_REFERENCE_MISMATCH")
        ids = tuple(c.candle_evidence_id for c in (*self.h1_source_candles, *self.m15_source_candles))
        if ids != self.source_evidence_ids or len(set(ids)) != len(ids):
            raise ValueError("PROOF_SOURCE_IDS_MISMATCH")
        expected_id = structural_proof_id_v31(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            context_epoch_id=self.context_epoch_id,
            proof_direction=self.proof_direction,
            selected_route=self.selected_route,
            level_version=self.level_version,
            h1_confirmation_candle_id=confirmation.candle_evidence_id,
            m15_break_candle_id=self.m15_break_candle_id,
            m15_completion_candle_id=self.m15_completion_candle_id,
            m15_completion_kind=self.m15_completion_kind,
            pattern_registry_hash=self.pattern_registry_hash,
        )
        if self.proof_id != expected_id:
            raise ValueError("STRUCTURAL_PROOF_ID_NOT_DERIVED")
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("STRUCTURAL_PROOF_LIFECYCLE_NOT_EPISODE_ROOTED")
        if self.material_evidence_hash != structural_material_hash_v31(self):
            raise ValueError("STRUCTURAL_PROOF_MATERIAL_HASH_MISMATCH")
        return self


def structural_material_hash_v31(proof: StructuralProofEvidenceV31) -> str:
    body = proof.model_dump(mode="json")
    body.pop("material_evidence_hash", None)
    return canonical_sha256_v31(body)


__all__ = [
    "STRUCTURAL_PROOF_V31_RULE_VERSION",
    "V31_STRUCTURAL_PROOF_NAMESPACE",
    "StructuralLevelEvidenceV31",
    "StructuralPatternRegistryV31",
    "StructuralPatternV31",
    "StructuralProofEvidenceV31",
    "structural_material_hash_v31",
    "structural_proof_id_v31",
]
