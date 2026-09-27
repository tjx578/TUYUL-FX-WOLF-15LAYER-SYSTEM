"""Capture-only evidence records for offline 30-pair SHADOW evaluation.

These records describe *what was observed* (ids, hashes, timestamps, symbol).
They are not strategy contracts and must never be fed back into runtime.

Existing strategy lineage ids come in two formats (prefixed-hex ids in the v2
contracts, UUIDs in the v3.1 contracts), so lineage ids here are bounded opaque
strings. No existing contract type is itself a capture record, so none is
reused; this keeps the package free of runtime imports.

Bundle format ``shadow_capture_bundle/v1`` is IMPLEMENTATION_ONLY and
NON_CANONICAL: it is a harness input format, not a WOLF15 authority object.

Exact-S is never invented here. An exact-S capture either says
``exact_s_status = "NOT_MEASURED"`` (the only honest value before R9) with no
id/digest, or carries ``exact_s_id`` + ``exact_s_sha256`` together with the
digest of the R9 artifact they were taken from. Whether that R9 artifact was
actually supplied is decided by the evaluator, never by the capture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tools.shadow_harness.manifest import CANONICAL_SYMBOL_PATTERN, SHA256_PATTERN

EvidenceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9:._-]{2,127}$")]
Sha256Hex = Annotated[str, Field(pattern=SHA256_PATTERN)]
GitObjectId = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
CanonicalSymbol = Annotated[str, Field(pattern=CANONICAL_SYMBOL_PATTERN)]
Direction = Literal["BUY", "SELL"]
SelectionSource = Literal["STRATEGY", "OPERATOR"]
PriceName = Literal["ENTRY", "STOP_LOSS", "TAKE_PROFIT"]
ExactSStatus = Literal["MEASURED", "NOT_MEASURED"]

BUNDLE_SCHEMA_VERSION: Final = "shadow_capture_bundle/v1"
BUNDLE_MARKING: Final = ("IMPLEMENTATION_ONLY", "NON_CANONICAL")
BUNDLE_HEADER_FIELDS: Final = (
    "schema_version",
    "candidate_git_sha",
    "candidate_tree_digest",
    "manifest_hash",
    "SSOT_hash",
    "A1_hash",
    "A2_hash",
    "A3_hash",
    "A4_hash",
    "configuration_digest",
    "created_at",
)
DERIVED_REPORT_FIELDS: Final = ("gate_failures", "gate_passed")
"""Report fields that only the evaluator may compute; supplying them in capture input is rejected."""

LINEAGE_FIELDS: tuple[str, ...] = (
    "lifecycle_id",
    "thesis_id",
    "proof_id",
    "pressure_range_id",
    "target_id",
    "execution_box_id",
    "tradeplan_candidate_id",
)
"""Lineage ids scanned by the primary cross-pair contamination detector (together with ``symbol``)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a UTC offset")
    return value.astimezone(UTC)


class CaptureLineage(_Frozen):
    """Lineage ids referenced by one capture; which are required depends on the capture kind.

    Every key is required (explicit ``null`` when not applicable) so absence is never implied.
    """

    lifecycle_id: EvidenceId | None
    thesis_id: EvidenceId | None
    proof_id: EvidenceId | None
    pressure_range_id: EvidenceId | None
    target_id: EvidenceId | None
    execution_box_id: EvidenceId | None
    tradeplan_candidate_id: EvidenceId | None

    def present(self) -> tuple[tuple[str, str], ...]:
        return tuple((name, value) for name in LINEAGE_FIELDS if (value := getattr(self, name)) is not None)


class PricePoint(_Frozen):
    name: PriceName
    value: Decimal = Field(..., gt=0)

    @field_validator("value", mode="before")
    @classmethod
    def _no_binary_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("prices must be decimal strings or JSON decimals, not binary floats")
        return value


class _CaptureBase(_Frozen):
    capture_schema_version: Literal["wolf15.shadow-harness.capture.v1"]
    capture_id: EvidenceId
    symbol: CanonicalSymbol
    captured_at_utc: datetime
    evidence_sha256: Sha256Hex
    lineage: CaptureLineage

    required_lineage: ClassVar[tuple[str, ...]] = ()

    @field_validator("captured_at_utc")
    @classmethod
    def _captured_utc(cls, value: datetime) -> datetime:
        return _utc(value, "captured_at_utc")

    @model_validator(mode="after")
    def _lineage_complete(self) -> _CaptureBase:
        missing = [name for name in self.required_lineage if getattr(self.lineage, name) is None]
        if missing:
            raise ValueError(f"lineage is missing required ids: {', '.join(missing)}")
        return self

    def price_points(self) -> tuple[PricePoint, ...]:
        return ()


def _unique_price_names(prices: tuple[PricePoint, ...]) -> tuple[PricePoint, ...]:
    names = [item.name for item in prices]
    if len(set(names)) != len(names):
        raise ValueError("price names must be unique within one capture")
    return prices


class CandidateCapture(_CaptureBase):
    """A natural strategy candidate. Pair and direction provenance are attested, not assumed."""

    capture_kind: Literal["CANDIDATE"]
    candidate_id: EvidenceId
    direction: Direction
    pair_selection_source: SelectionSource
    direction_selection_source: SelectionSource

    required_lineage = ("lifecycle_id", "thesis_id")


class ExactSCapture(_CaptureBase):
    """Exact-S evidence for one candidate.

    ``NOT_MEASURED`` carries no exact-S id, digest or R9 artifact digest.
    ``MEASURED`` must carry all three; the evaluator accepts it only when
    ``r9_artifact_sha256`` matches an R9 artifact actually supplied to the run.
    """

    capture_kind: Literal["EXACT_S"]
    exact_s_status: ExactSStatus
    exact_s_id: EvidenceId | None
    exact_s_sha256: Sha256Hex | None
    r9_artifact_sha256: Sha256Hex | None

    required_lineage = ("lifecycle_id", "thesis_id", "execution_box_id")

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> ExactSCapture:
        carried = {
            "exact_s_id": self.exact_s_id,
            "exact_s_sha256": self.exact_s_sha256,
            "r9_artifact_sha256": self.r9_artifact_sha256,
        }
        if self.exact_s_status == "NOT_MEASURED":
            present = sorted(name for name, value in carried.items() if value is not None)
            if present:
                raise ValueError(f"NOT_MEASURED exact-S must not carry {', '.join(present)}")
        else:
            absent = sorted(name for name, value in carried.items() if value is None)
            if absent:
                raise ValueError(f"MEASURED exact-S requires {', '.join(absent)} from an R9 artifact")
        return self


class TradeplanCapture(_CaptureBase):
    capture_kind: Literal["TRADEPLAN"]
    tradeplan_revision: int = Field(..., ge=1)
    direction: Direction
    direction_selection_source: SelectionSource
    prices: tuple[PricePoint, ...] = Field(..., min_length=1)

    required_lineage = ("lifecycle_id", "thesis_id", "target_id", "execution_box_id", "tradeplan_candidate_id")

    @field_validator("prices")
    @classmethod
    def _prices_unique(cls, value: tuple[PricePoint, ...]) -> tuple[PricePoint, ...]:
        return _unique_price_names(value)

    def price_points(self) -> tuple[PricePoint, ...]:
        return self.prices


class BrokerAdaptationDryRunCapture(_CaptureBase):
    """Dry-run broker adaptation. ``broker_submit_attempted`` is observed evidence, counted by the evaluator."""

    capture_kind: Literal["BROKER_ADAPTATION_DRY_RUN"]
    dry_run: Literal[True]
    adaptation_id: EvidenceId
    broker_symbol: str = Field(..., pattern=r"^[A-Za-z0-9._#-]{1,32}$")
    adaptation_status: Literal["ADAPTED", "VETO"]
    broker_submit_attempted: bool
    prices: tuple[PricePoint, ...]

    required_lineage = ("tradeplan_candidate_id",)

    @field_validator("prices")
    @classmethod
    def _prices_unique(cls, value: tuple[PricePoint, ...]) -> tuple[PricePoint, ...]:
        return _unique_price_names(value)

    def price_points(self) -> tuple[PricePoint, ...]:
        return self.prices


class RiskDryRunCapture(_CaptureBase):
    """Dry-run risk evaluation. Risk may only veto; it never selects a pair or direction."""

    capture_kind: Literal["RISK_DRY_RUN"]
    dry_run: Literal[True]
    risk_evaluation_id: EvidenceId
    risk_decision: Literal["ALLOW", "VETO"]
    broker_submit_attempted: bool

    required_lineage = ("tradeplan_candidate_id",)


Capture = Annotated[
    CandidateCapture | ExactSCapture | TradeplanCapture | BrokerAdaptationDryRunCapture | RiskDryRunCapture,
    Field(discriminator="capture_kind"),
]

DOWNSTREAM_KINDS: frozenset[str] = frozenset({"EXACT_S", "TRADEPLAN", "BROKER_ADAPTATION_DRY_RUN", "RISK_DRY_RUN"})


class BundleHeader(BaseModel):
    """``shadow_capture_bundle/v1`` header. Every key is required; only ``A4_hash`` may be ``null``.

    ``A4_hash`` stays ``null`` until A4 is approved. ``manifest_hash`` and
    ``configuration_digest`` are bound by the evaluator to the pinned symbol
    universe and the harness policy respectively; the other hashes are recorded
    and format-checked only (the harness has no authority to verify them).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["shadow_capture_bundle/v1"]
    candidate_git_sha: GitObjectId
    candidate_tree_digest: GitObjectId
    manifest_hash: Sha256Hex
    ssot_hash: Sha256Hex = Field(..., alias="SSOT_hash")
    a1_hash: Sha256Hex = Field(..., alias="A1_hash")
    a2_hash: Sha256Hex = Field(..., alias="A2_hash")
    a3_hash: Sha256Hex = Field(..., alias="A3_hash")
    a4_hash: Sha256Hex | None = Field(..., alias="A4_hash")
    configuration_digest: Sha256Hex
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_utc(cls, value: datetime) -> datetime:
        return _utc(value, "created_at")


class ShadowCaptureBundle(_Frozen):
    """Captured evidence keyed by canonical symbol.

    Keys are deliberately plain strings here so the isolation validator, not the
    parser, reports unknown or mismatched symbol keys. An empty list is an
    evaluated symbol with no captures (``WAIT``); a missing key is an
    unevaluated symbol.
    """

    header: BundleHeader
    captures_by_symbol: dict[Annotated[str, Field(min_length=1, max_length=32)], tuple[Capture, ...]]


__all__ = [
    "BUNDLE_HEADER_FIELDS",
    "BUNDLE_MARKING",
    "BUNDLE_SCHEMA_VERSION",
    "DERIVED_REPORT_FIELDS",
    "DOWNSTREAM_KINDS",
    "LINEAGE_FIELDS",
    "BrokerAdaptationDryRunCapture",
    "BundleHeader",
    "CandidateCapture",
    "Capture",
    "CaptureLineage",
    "ExactSCapture",
    "PricePoint",
    "RiskDryRunCapture",
    "ShadowCaptureBundle",
    "TradeplanCapture",
]
