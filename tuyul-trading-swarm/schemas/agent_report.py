"""Agent report schema — output contract dari setiap agent evaluation."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class GateResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HALT = "HALT"
    CAUTION = "CAUTION"
    SKIP = "SKIP"


class AgentReport(BaseModel):
    """Laporan evaluasi dari satu agent."""

    agent_id: int
    agent_name: str
    candidate_id: str
    gate_result: GateResult
    score: Optional[float] = Field(default=None, description="Skor 0-100 jika berlaku")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    reason: str = Field(..., description="Alasan utama keputusan")
    details: dict[str, Any] = Field(default_factory=dict)
    disqualifiers: list[str] = Field(default_factory=list, description="Daftar disqualifier yang ditemukan")
    warnings: list[str] = Field(default_factory=list, description="Peringatan non-fatal")
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    evaluation_ms: Optional[float] = Field(default=None, description="Durasi evaluasi dalam ms")

    model_config = ConfigDict(use_enum_values=True)

    class _Config:
        use_enum_values = True

    @property
    def is_pass(self) -> bool:
        return self.gate_result == GateResult.PASS

    @property
    def is_halt(self) -> bool:
        return self.gate_result == GateResult.HALT

    @property
    def is_fail(self) -> bool:
        return self.gate_result in (GateResult.FAIL, GateResult.HALT, GateResult.SKIP)
