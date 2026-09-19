"""Native V31 admission identity and canonical admission receipt (authority decision 2026-09-19).

Identity (``v31.native-identity.v1``): deterministic UUIDv5 under pinned namespaces. It is derived from
V31/v3 canonical inputs only and never from a legacy ``5scr-...:<hex32>`` identity. Legacy identities may be
kept elsewhere as AUDIT_REFERENCE_ONLY; they are not part of any V31 identity or receipt hash.

Receipt (``5scr.admission-receipt.v31.v1``): ``admission_receipt_hash`` = sha256 over the V31 canonical JSON
(model_dump json mode, sorted keys, compact separators, NaN forbidden), the same serializer the V31 family
uses for its other receipts. The receipt proves the canonical per-symbol admission decision only. Global
safety overlay, broker/runtime state, database row metadata, deployment ids and secrets are never part of it.

Changing a namespace, the identity tuple layout or the serializer is a contract change, not a refactor.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_per_symbol_admission import (
    PER_SYMBOL_ADMISSION_RULE_VERSION,
    PerSymbolAdmissionPolicyV3,
    SymbolAdmissionLineageV3,
)

IDENTITY_ENCODING_VERSION = "v31.native-identity.v1"
ADMISSION_RECEIPT_VERSION = "5scr.admission-receipt.v31.v1"
ADMISSION_RECEIPT_HASH_ALGORITHM = "sha256"
ADMISSION_RECEIPT_SERIALIZER = "v31.canonical-json.sorted-compact.v1"
SELECTED_SSOT_HASH = "sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"

WOLF15_V31_ADMISSION_NAMESPACE = UUID("221b74fd-95a4-4133-9db1-482fda36c331")
WOLF15_V31_LIFECYCLE_NAMESPACE = UUID("7f5e5517-372c-43ef-b243-00e1e665fe84")

_DIGEST = r"^sha256:[0-9a-f]{64}$"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def admission_id_v31(*, pair_admission_rule_version: str, canonical_symbol: str, opening_source_event_id: str) -> UUID:
    """UUIDv5 over a JSON array (no string concatenation, so no field-boundary ambiguity)."""

    if not canonical_symbol or canonical_symbol != canonical_symbol.strip().upper():
        raise ValueError("canonical_symbol must be normalized upper-case")
    if not opening_source_event_id:
        raise ValueError("opening_source_event_id is required")
    name = _canonical_json(
        [IDENTITY_ENCODING_VERSION, pair_admission_rule_version, canonical_symbol, opening_source_event_id]
    )
    return uuid5(WOLF15_V31_ADMISSION_NAMESPACE, name)


def lifecycle_id_v31(*, strategy_analysis_admission_id: UUID, lifecycle_anchor: str) -> UUID:
    if not lifecycle_anchor:
        raise ValueError("lifecycle_anchor is required")
    name = _canonical_json([IDENTITY_ENCODING_VERSION, str(strategy_analysis_admission_id), lifecycle_anchor])
    return uuid5(WOLF15_V31_LIFECYCLE_NAMESPACE, name)


def policy_fingerprint_v31(policy: PerSymbolAdmissionPolicyV3) -> str:
    return _sha256(policy.model_dump(mode="json"))


class AdmissionReceiptV31(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    receipt_version: Literal["5scr.admission-receipt.v31.v1"] = ADMISSION_RECEIPT_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"] = (
        SELECTED_SSOT_HASH
    )
    pair_admission_rule_version: Literal["5scr.pair-admission.per-symbol-isolated.v3"] = (
        PER_SYMBOL_ADMISSION_RULE_VERSION
    )
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    strategy_analysis_admission_id: UUID
    decision: Literal["GRANTED", "REJECTED", "SUSPENDED"] | None
    reason_code: str = Field(min_length=3, max_length=200)
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    policy_fingerprint: str = Field(pattern=_DIGEST)
    admission_opened_at: datetime
    decision_effective_at: datetime | None

    @model_validator(mode="after")
    def _bound(self) -> AdmissionReceiptV31:
        expected = admission_id_v31(
            pair_admission_rule_version=self.pair_admission_rule_version,
            canonical_symbol=self.canonical_symbol,
            opening_source_event_id=self.source_event_ids[0],
        )
        if self.strategy_analysis_admission_id != expected:
            raise ValueError("ADMISSION_ID_NOT_DERIVED_FROM_OPENING_EVENT")
        if (self.decision == "GRANTED") != (self.decision_effective_at is not None):
            raise ValueError("decision_effective_at is required exactly for GRANTED receipts")
        for moment in (self.admission_opened_at, self.decision_effective_at):
            if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
                raise ValueError("receipt clocks must be timezone-aware")
        return self


def admission_receipt_hash_v31(receipt: AdmissionReceiptV31) -> str:
    return _sha256(receipt.model_dump(mode="json"))


def build_admission_receipt_v31(
    lineage: SymbolAdmissionLineageV3, *, policy: PerSymbolAdmissionPolicyV3
) -> AdmissionReceiptV31:
    """Receipt of one per-symbol lineage decision. Takes no global safety or runtime input by construction."""

    return AdmissionReceiptV31(
        canonical_symbol=lineage.canonical_symbol,
        strategy_analysis_admission_id=admission_id_v31(
            pair_admission_rule_version=lineage.rule_version,
            canonical_symbol=lineage.canonical_symbol,
            opening_source_event_id=lineage.source_event_ids[0],
        ),
        decision=lineage.decision,
        reason_code=lineage.reason_code,
        source_event_ids=lineage.source_event_ids,
        policy_fingerprint=policy_fingerprint_v31(policy),
        admission_opened_at=lineage.opened_at,
        decision_effective_at=lineage.granted_at,
    )


def verify_handoff_admission_receipt_v31(
    receipt: AdmissionReceiptV31,
    *,
    admission_receipt_hash: str,
    strategy_analysis_admission_id: UUID,
    canonical_symbol: str,
) -> None:
    """A CandidateHandoffV31 may reference only a GRANTED receipt whose hash and scope match exactly."""

    if receipt.decision != "GRANTED":
        raise ValueError("HANDOFF_REQUIRES_GRANTED_ADMISSION_RECEIPT")
    if admission_receipt_hash != admission_receipt_hash_v31(receipt):
        raise ValueError("HANDOFF_ADMISSION_RECEIPT_HASH_MISMATCH")
    if (receipt.strategy_analysis_admission_id, receipt.canonical_symbol) != (
        strategy_analysis_admission_id,
        canonical_symbol,
    ):
        raise ValueError("HANDOFF_ADMISSION_SCOPE_MISMATCH")


__all__ = [
    "ADMISSION_RECEIPT_HASH_ALGORITHM",
    "ADMISSION_RECEIPT_SERIALIZER",
    "ADMISSION_RECEIPT_VERSION",
    "IDENTITY_ENCODING_VERSION",
    "WOLF15_V31_ADMISSION_NAMESPACE",
    "WOLF15_V31_LIFECYCLE_NAMESPACE",
    "AdmissionReceiptV31",
    "admission_id_v31",
    "admission_receipt_hash_v31",
    "build_admission_receipt_v31",
    "lifecycle_id_v31",
    "policy_fingerprint_v31",
    "verify_handoff_admission_receipt_v31",
]
