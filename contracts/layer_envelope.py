"""
LayerEnvelope — Blueprint v2 P0 Contract
==========================================
Uniform output contract for every analysis/validation/risk/meta layer.

Authority boundary:
  - Layers (L1..L11, L13, L15) MUST NOT emit BUY/SELL.
  - Layers return evidence via LayerEnvelope; only L12 authorizes execution
    via AuthorizedOrderIntent.
  - V11 post-L12 veto also uses LayerEnvelope (plane = "post_authority_veto").

This module is a pure contract: no market logic, no mutation of existing
layer outputs. Adapters (.to_envelope) will be added in a follow-up PR so
P0 diff stays minimal and fully reviewable.

Zone: contracts — frozen, validation-only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "layer_envelope.v2"

LayerStatus = Literal["PASS", "FAIL", "DEGRADED", "SKIPPED"]
Direction = Literal["BUY", "SELL", "NEUTRAL", "NONE"]

# Evidence planes — keep aligned with Blueprint v2 DecisionBundle fields
# and constitutional doctrine (V11 is post-L12 veto, not pre-L12 validation).
EvidencePlane = Literal[
    "context",  # L1
    "alpha",  # L2, L3, L4, L9
    "validation",  # L5, L7, L8
    "risk",  # L6, runtime_risk, capital_guardian
    "portfolio",  # L10
    "economics",  # L11 (RR)
    "meta",  # L13, L15 (advisory only)
    "post_authority_veto",  # V11 — runs AFTER L12 EXECUTE
]


class LayerEnvelope(BaseModel):
    """Frozen evidence envelope emitted by every non-authority layer.

    Authority invariants:
      - status == "FAIL" with a blocker MUST be treated as hard-fail by L12.
      - direction is advisory; only L12 decides the final BUY/SELL.
      - evidence payload must NOT contain account state (balance/equity/margin);
        sizing is owned by the risk/dashboard plane.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION)

    signal_id: str = Field(..., min_length=3, description="Correlation ID for the pipeline run")
    symbol: str = Field(..., min_length=3, max_length=20)
    layer_id: str = Field(..., min_length=1, description="Layer code, e.g. L1, L12, V11")
    module: str = Field(..., min_length=1, description="Fully qualified module path")
    plane: EvidencePlane = Field(..., description="Evidence plane; enforces authority boundary")

    status: LayerStatus
    score: float | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    direction: Direction = Field(default="NONE")

    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)

    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    stale_after_ms: int = Field(default=30_000, ge=0)

    @field_validator("evidence")
    @classmethod
    def _reject_account_state_keys(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Guard against account-state leak into evidence payload.

        Constitutional invariant: L12 signal MUST NOT contain balance/equity/margin.
        We enforce the same at the envelope level to prevent leakage upstream.
        """
        forbidden = {"balance", "equity", "margin", "free_margin", "account_balance"}
        leaked = forbidden.intersection({k.lower() for k in v})
        if leaked:
            raise ValueError(f"Evidence payload must not carry account state; forbidden keys: {sorted(leaked)}")
        return v

    @field_validator("blockers", "warnings")
    @classmethod
    def _dedupe_and_strip(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for code in v:
            code = str(code).strip()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
        return out

    def is_fail(self) -> bool:
        return self.status == "FAIL"

    def is_blocking(self) -> bool:
        """Hard fail with at least one blocker — L12 must treat as hard reject."""
        return self.status == "FAIL" and bool(self.blockers)

    def is_degraded(self) -> bool:
        return self.status == "DEGRADED"

    def age_ms(self, now: datetime | None = None) -> float | None:
        if self.finished_at is None:
            return None
        now = now or datetime.now(tz=UTC)
        return (now - self.finished_at).total_seconds() * 1000.0

    def is_stale(self, now: datetime | None = None) -> bool:
        age = self.age_ms(now=now)
        return age is not None and age > float(self.stale_after_ms)


__all__ = [
    "SCHEMA_VERSION",
    "LayerStatus",
    "Direction",
    "EvidencePlane",
    "LayerEnvelope",
]
