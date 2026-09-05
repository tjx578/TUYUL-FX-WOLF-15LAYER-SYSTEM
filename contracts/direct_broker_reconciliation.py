"""Fail-closed contract for durable direct-broker reconciliation evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

DIRECT_SOURCE = "DIRECT_MT5_BROKER"


def canonical_sha256(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(to_jsonable_python(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReconciliationCounts(StrictModel):
    positions: int = Field(ge=0)
    pending_orders: int = Field(ge=0)
    orders: int = Field(ge=0)
    deals: int = Field(ge=0)
    matched_wolf15: int = Field(ge=0)
    manual_external: int = Field(ge=0)
    preexisting: int = Field(ge=0)
    orphan_wolf15: int = Field(ge=0)
    unattributed: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    ledger_mismatch: int = Field(ge=0)

    @property
    def reconciled(self) -> bool:
        return not any((self.orphan_wolf15, self.unattributed, self.ambiguous, self.ledger_mismatch))


class DirectBrokerSourceSnapshotV1(StrictModel):
    schema_version: Literal["wolf15.mt5.direct-broker-snapshot.v1"] = "wolf15.mt5.direct-broker-snapshot.v1"
    source_type: Literal["DIRECT_MT5_BROKER"] = DIRECT_SOURCE
    snapshot_id: str = Field(min_length=3, max_length=200)
    executor_id: UUID
    account_reference: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_at_utc: datetime
    counts: ReconciliationCounts

    @field_validator("observed_at_utc")
    @classmethod
    def _snapshot_utc_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at_utc must be timezone-aware UTC")
        return value


class DirectBrokerReconciliationRequest(StrictModel):
    reconciliation_id: UUID
    executor_id: UUID
    account_reference: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_at_utc: datetime
    source_type: Literal["DIRECT_MT5_BROKER"] = DIRECT_SOURCE
    source_snapshot_id: str = Field(min_length=3, max_length=200)
    source_snapshot_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    command_id: UUID | None = None
    order_ticket_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    deal_ticket_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    position_id_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    counts: ReconciliationCounts
    terminal_reason: str = Field(min_length=1, max_length=100)

    @field_validator("observed_at_utc")
    @classmethod
    def _utc_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("observed_at_utc must be timezone-aware UTC")
        return value


class DirectBrokerReconciliationReceipt(StrictModel):
    reconciliation_id: UUID
    executor_id: UUID
    account_reference: str
    broker_server_sha256: str
    observed_at_utc: datetime
    source_type: Literal["DIRECT_MT5_BROKER"]
    source_snapshot_id: str
    source_snapshot_sha256: str
    command_id: UUID | None
    order_ticket_sha256: str | None
    deal_ticket_sha256: str | None
    position_id_sha256: str | None
    counts: ReconciliationCounts
    broker_ledger_reconciled: bool
    terminal_reason: str
    created_at_utc: datetime
    receipt_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _derived_result_cannot_be_forged(self) -> DirectBrokerReconciliationReceipt:
        if self.broker_ledger_reconciled != self.counts.reconciled:
            raise ValueError("broker_ledger_reconciled must be derived from reconciliation counts")
        material = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if self.receipt_sha256 != canonical_sha256(material):
            raise ValueError("receipt_sha256 does not match canonical receipt material")
        return self
