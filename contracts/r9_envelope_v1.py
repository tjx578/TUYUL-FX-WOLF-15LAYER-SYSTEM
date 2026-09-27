"""R9EnvelopeV1: strict envelope over one R9 operator evidence artifact for exact snapshot S.

Status: FROZEN by the owner 2026-09-28 (schema doc sha256 10732eeb…, blob 9a895e34…, 13162 bytes); runtime_activation=false.
Schema document: docs/governance/r9-envelope-v1.md (the two must stay equal; see tests/test_r9_envelope_v1.py).

R9 = identity S -> collect -> import -> ACTIVE readback -> capability -> direct receipt. Every identity and
status name below is reused from the existing reconciliation stack; the document cites file:line for each.
``exact_s_accepted`` is DERIVED only and exists only on the verifier verdict (``verify_r9_envelope_v1``), the sole
final authority because only the verifier holds the source artifact bytes. It is never an input field: an input
that supplies it is rejected. The envelope itself exposes ``intrinsic_checks_passed`` (every rule except the bytes).
There is no fallback to a latest snapshot, no default for any field, and a missing component fails closed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

R9_ENVELOPE_SCHEMA_ID: Final = "wolf15.r9-envelope"
R9_ENVELOPE_SCHEMA_VERSION: Final = "v1"
R9_SOURCE_ARTIFACT: Final = "R9"
R9_DERIVED_FIELDS_V1: Final = ("exact_s_accepted",)

# Reused constraints (see the schema document for the source of each).
SnapshotId = Annotated[str, Field(min_length=3, max_length=200)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PrefixedSha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

CollectStatus = Literal["MATCHED_FLAT_DEMO"]
# Q5: QUALIFIED_C2_WRAPPER_STATUS normalized as the R9 import status; NOT a main-repository canonical status. It only
# says the wrapper finished the import; persistence is proven by the main-side ACTIVE readback (same evidence_id,
# same payload_sha256, same S).
ImportStatus = Literal["STORED"]
ReadbackStatus = Literal["ACTIVE", "REVOKED"]
CapabilityStatus = Literal["MEASURED", "MEASURED_EMPTY", "NOT_MEASURED"]
DirectReceiptStatus = Literal["ABSENT", "PRESENT"]

R9FailureReason = Literal[
    "EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT",
    "ENVELOPE_SCHEMA_INVALID",
    "SOURCE_ARTIFACT_NOT_R9",
    "ARTIFACT_BYTES_REQUIRED",
    "ARTIFACT_SHA256_MISMATCH",
    "COLLECT_SNAPSHOT_IDENTITY_MISMATCH",
    "IMPORT_SNAPSHOT_IDENTITY_MISMATCH",
    "IMPORT_EVIDENCE_ID_MISMATCH",
    "ACTIVE_READBACK_STATUS_NOT_ACTIVE",
    "ACTIVE_READBACK_SNAPSHOT_IDENTITY_MISMATCH",
    "ACTIVE_READBACK_EVIDENCE_ID_MISMATCH",
    "ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH",
    "CAPABILITY_STATUS_NOT_MEASURED",
    "CAPABILITY_EVIDENCE_MISSING",
    "CAPABILITY_SNAPSHOT_ID_MISMATCH",
    "DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH",
    "DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY",
    "DIRECT_RECEIPT_NOT_RECONCILED",
    "DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY",
]

# Canonical order of failure reasons; every verdict lists its reasons in exactly this order.
R9_FAILURE_REASONS_V1: Final[tuple[R9FailureReason, ...]] = (
    "EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT",
    "ENVELOPE_SCHEMA_INVALID",
    "SOURCE_ARTIFACT_NOT_R9",
    "ARTIFACT_BYTES_REQUIRED",
    "ARTIFACT_SHA256_MISMATCH",
    "COLLECT_SNAPSHOT_IDENTITY_MISMATCH",
    "IMPORT_SNAPSHOT_IDENTITY_MISMATCH",
    "IMPORT_EVIDENCE_ID_MISMATCH",
    "ACTIVE_READBACK_STATUS_NOT_ACTIVE",
    "ACTIVE_READBACK_SNAPSHOT_IDENTITY_MISMATCH",
    "ACTIVE_READBACK_EVIDENCE_ID_MISMATCH",
    "ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH",
    "CAPABILITY_STATUS_NOT_MEASURED",
    "CAPABILITY_EVIDENCE_MISSING",
    "CAPABILITY_SNAPSHOT_ID_MISMATCH",
    "DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH",
    "DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY",
    "DIRECT_RECEIPT_NOT_RECONCILED",
    "DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class R9SnapshotIdentityV1(_StrictModel):
    """Exact snapshot identity S: the (snapshot_id, snapshot_sha256) pair the backend binding pins."""

    snapshot_id: SnapshotId
    snapshot_sha256: Sha256Hex


class R9CollectV1(_StrictModel):
    status: CollectStatus
    attested_snapshot_identity: R9SnapshotIdentityV1
    evidence_id: UUID
    report_sha256: Sha256Hex


class R9ImportV1(_StrictModel):
    status: ImportStatus
    imported_snapshot_identity: R9SnapshotIdentityV1
    evidence_id: UUID
    payload_sha256: Sha256Hex


class R9ActiveReadbackV1(_StrictModel):
    status: ReadbackStatus
    readback_snapshot_identity: R9SnapshotIdentityV1
    evidence_id: UUID
    payload_sha256: Sha256Hex


class R9CapabilityV1(_StrictModel):
    """The capability view is keyed by snapshot_id only; it proves no snapshot_sha256, so it carries none (Q1)."""

    status: CapabilityStatus
    snapshot_id: SnapshotId
    canonical_symbol: Annotated[str, Field(min_length=3, max_length=32)] | None
    broker_symbol: Annotated[str, Field(min_length=1, max_length=64)] | None
    volume_min: Annotated[float, Field(gt=0)] | None
    volume_step: Annotated[float, Field(gt=0)] | None


class R9DirectReceiptV1(_StrictModel):
    """Keyed by the receipt's source_snapshot_id only (Q1). ABSENT still names the exact S that was queried (Q2);
    PRESENT must be a reconciled receipt (Q3)."""

    status: DirectReceiptStatus
    snapshot_id: SnapshotId
    reconciliation_id: UUID | None
    receipt_sha256: PrefixedSha256 | None
    broker_ledger_reconciled: bool | None


class R9EnvelopeV1(_StrictModel):
    schema_id: Literal["wolf15.r9-envelope"]
    schema_version: Literal["v1"]
    source_artifact: Annotated[str, Field(min_length=1, max_length=64)]
    artifact_sha256: Sha256Hex
    snapshot_s: R9SnapshotIdentityV1
    collect: R9CollectV1
    import_: R9ImportV1 = Field(alias="import")
    active_readback: R9ActiveReadbackV1
    capability: R9CapabilityV1
    direct_receipt: R9DirectReceiptV1
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("created_at must be timezone-aware UTC")
        return value

    @property
    def intrinsic_failure_reasons(self) -> tuple[R9FailureReason, ...]:
        """Envelope-intrinsic failures. Artifact bytes are checked only by verify_r9_envelope_v1."""
        return r9_envelope_failures_v1(self)

    @property
    def intrinsic_checks_passed(self) -> bool:
        """Never exact-S acceptance: without the artifact bytes there is no final verdict (Q4)."""
        return not self.intrinsic_failure_reasons


class R9EnvelopeVerdictV1(_StrictModel):
    """The only final exact_s_accepted authority. Accepted implies no failure and verified artifact bytes."""

    exact_s_accepted: bool
    failure_reasons: tuple[R9FailureReason, ...]
    artifact_bytes_verified: bool

    @model_validator(mode="after")
    def _consistent(self) -> R9EnvelopeVerdictV1:
        if self.exact_s_accepted != (not self.failure_reasons):
            raise ValueError("VERDICT_ACCEPTANCE_INCONSISTENT")
        if self.exact_s_accepted and not self.artifact_bytes_verified:
            raise ValueError("EXACT_S_ACCEPTED_WITHOUT_ARTIFACT_BYTES")
        return self


def _same_s(candidate: R9SnapshotIdentityV1, snapshot_s: R9SnapshotIdentityV1) -> bool:
    return candidate.snapshot_id == snapshot_s.snapshot_id and candidate.snapshot_sha256 == snapshot_s.snapshot_sha256


def r9_envelope_failures_v1(envelope: R9EnvelopeV1) -> tuple[R9FailureReason, ...]:
    s = envelope.snapshot_s
    collect, imported, readback = envelope.collect, envelope.import_, envelope.active_readback
    capability, receipt = envelope.capability, envelope.direct_receipt
    receipt_identity = (receipt.reconciliation_id, receipt.receipt_sha256)
    checks: tuple[tuple[bool, R9FailureReason], ...] = (
        (envelope.source_artifact != R9_SOURCE_ARTIFACT, "SOURCE_ARTIFACT_NOT_R9"),
        (not _same_s(collect.attested_snapshot_identity, s), "COLLECT_SNAPSHOT_IDENTITY_MISMATCH"),
        (not _same_s(imported.imported_snapshot_identity, s), "IMPORT_SNAPSHOT_IDENTITY_MISMATCH"),
        (imported.evidence_id != collect.evidence_id, "IMPORT_EVIDENCE_ID_MISMATCH"),
        (readback.status != "ACTIVE", "ACTIVE_READBACK_STATUS_NOT_ACTIVE"),
        (not _same_s(readback.readback_snapshot_identity, s), "ACTIVE_READBACK_SNAPSHOT_IDENTITY_MISMATCH"),
        (readback.evidence_id != imported.evidence_id, "ACTIVE_READBACK_EVIDENCE_ID_MISMATCH"),
        (readback.payload_sha256 != imported.payload_sha256, "ACTIVE_READBACK_PAYLOAD_SHA256_MISMATCH"),
        (capability.status != "MEASURED", "CAPABILITY_STATUS_NOT_MEASURED"),
        (
            None
            in (capability.canonical_symbol, capability.broker_symbol, capability.volume_min, capability.volume_step),
            "CAPABILITY_EVIDENCE_MISSING",
        ),
        # Q1: the capability and receipt views prove snapshot_id only; the S sha256 is not re-claimed for them.
        (capability.snapshot_id != s.snapshot_id, "CAPABILITY_SNAPSHOT_ID_MISMATCH"),
        (receipt.snapshot_id != s.snapshot_id, "DIRECT_RECEIPT_SNAPSHOT_ID_MISMATCH"),
        (receipt.status == "PRESENT" and None in receipt_identity, "DIRECT_RECEIPT_PRESENT_WITHOUT_RECEIPT_IDENTITY"),
        (receipt.status == "PRESENT" and receipt.broker_ledger_reconciled is not True, "DIRECT_RECEIPT_NOT_RECONCILED"),
        (
            receipt.status == "ABSENT" and receipt_identity + (receipt.broker_ledger_reconciled,) != (None, None, None),
            "DIRECT_RECEIPT_ABSENT_WITH_RECEIPT_IDENTITY",
        ),
    )
    return tuple(reason for failed, reason in checks if failed)


def _verdict(reasons: set[R9FailureReason], *, artifact_bytes_verified: bool) -> R9EnvelopeVerdictV1:
    ordered: tuple[R9FailureReason, ...] = tuple(r for r in R9_FAILURE_REASONS_V1 if r in reasons)
    return R9EnvelopeVerdictV1(
        exact_s_accepted=not ordered, failure_reasons=ordered, artifact_bytes_verified=artifact_bytes_verified
    )


def verify_r9_envelope_v1(
    envelope: R9EnvelopeV1 | Mapping[str, object], artifact_bytes: bytes | None
) -> R9EnvelopeVerdictV1:
    """Derive exact_s_accepted, the only final authority. Fail closed; never raises on malformed input.

    ``artifact_bytes`` are the SOURCE R9 evidence artifact bytes (not the envelope) and are REQUIRED (Q4): None is
    ARTIFACT_BYTES_REQUIRED; otherwise their sha256 must equal ``artifact_sha256``.
    """
    if isinstance(envelope, R9EnvelopeV1):
        model = envelope
    elif isinstance(envelope, Mapping):
        if "exact_s_accepted" in envelope:
            return _verdict({"EXACT_S_ACCEPTED_SUPPLIED_BY_INPUT"}, artifact_bytes_verified=False)
        try:
            model = R9EnvelopeV1.model_validate(envelope)
        except ValidationError:
            return _verdict({"ENVELOPE_SCHEMA_INVALID"}, artifact_bytes_verified=False)
    else:
        return _verdict({"ENVELOPE_SCHEMA_INVALID"}, artifact_bytes_verified=False)
    reasons: set[R9FailureReason] = set(model.intrinsic_failure_reasons)
    verified = False
    if artifact_bytes is None:
        reasons.add("ARTIFACT_BYTES_REQUIRED")
    elif isinstance(artifact_bytes, bytes) and hashlib.sha256(artifact_bytes).hexdigest() == model.artifact_sha256:
        verified = True
    else:
        reasons.add("ARTIFACT_SHA256_MISMATCH")
    return _verdict(reasons, artifact_bytes_verified=verified)


def r9_envelope_field_paths_v1() -> tuple[str, ...]:
    """Wire field paths (aliases, dotted for nested components) followed by the derived fields."""

    def walk(model: type[BaseModel], prefix: str) -> list[str]:
        paths: list[str] = []
        for name, info in model.model_fields.items():
            path = prefix + (info.alias or name)
            annotation = info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                paths.extend(walk(annotation, path + "."))
            else:
                paths.append(path)
        return paths

    return (*walk(R9EnvelopeV1, ""), *R9_DERIVED_FIELDS_V1)
