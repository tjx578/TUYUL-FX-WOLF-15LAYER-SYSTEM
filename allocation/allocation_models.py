"""
Allocation Models — Pydantic schemas for allocation domain.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AllocationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"


class AccountAllocationResult(BaseModel):
    account_id: str
    approved: bool = False
    allowed: bool
    lot_size: float = 0.0
    risk_percent: float = 0.0
    daily_buffer_percent: float = 0.0
    total_buffer_percent: float = 0.0
    status: str = "SKIP"
    reason: str = ""
    severity: str = "SAFE"

    model_config = ConfigDict(frozen=True)


class AllocationRequest(BaseModel):
    request_id: str = Field(..., description="Unique allocation request ID")
    signal_id: str = Field(..., description="Source L12 signal ID")
    account_ids: list[str] = Field(..., description="Accounts to allocate to")
    operator: str = Field(default="system", description="Operator identity")
    action: str = Field(default="TAKE", description="TAKE or PREVIEW")
    risk_percent: float = Field(1.0, gt=0, le=5.0, description="Risk % per account")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(frozen=False)


class AllocationResult(BaseModel):
    request_id: str
    signal_id: str
    status: AllocationStatus
    account_results: list[AccountAllocationResult] = Field(default_factory=list)
    approved_count: int = 0
    rejected_count: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(frozen=False)

    def summary(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "signal_id": self.signal_id,
            "status": self.status,
            "approved": self.approved_count,
            "rejected": self.rejected_count,
        }
