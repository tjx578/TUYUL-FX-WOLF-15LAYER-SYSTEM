"""
DecisionBundle — Blueprint v2 P0 Contract
==========================================
Frozen envelope-only input to Layer-12 Authority.

Replaces leaky ``WolfContext`` consumption at the L12 boundary. L12 must
see ONLY structured evidence envelopes, never raw mutable state.

Authority invariants enforced here:
  - Every evidence list contains only ``LayerEnvelope`` instances.
  - Envelopes are organized by evidence plane, matching Blueprint v2.
  - No account state leaks into the bundle (balance/equity/margin are
    already rejected at the ``LayerEnvelope`` layer).
  - The bundle is immutable after construction.

Zone: contracts — pure data, no market logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.layer_envelope import LayerEnvelope

SCHEMA_VERSION = "decision_bundle.v2"


class DecisionBundle(BaseModel):
    """Single input object handed to Layer-12 Authority.

    The bundle is organized by evidence plane to keep the L12 policy code
    small and auditable:

      - ``context``      : L1 regime/coherence/bias.
      - ``alpha``        : L2 MTA, L3 technical, L4 confluence, L9 SMC.
      - ``validation``   : L5 psychology, L7 Monte Carlo, L8 TII.
      - ``risk``         : L6 risk matrix + runtime_risk + capital_guardian.
      - ``portfolio``    : L10 position sizing / exposure.
      - ``economics``    : L11 RR / battle strategy / expectancy economics.
      - ``meta``         : L13 reflective, L15 learning (advisory only).

    ``post_authority_veto`` (V11) is intentionally NOT part of the bundle:
    V11 runs AFTER L12 emits EXECUTE, not before.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION)

    signal_id: str = Field(..., min_length=3)
    symbol: str = Field(..., min_length=3, max_length=20)
    timeframe: str = Field(..., min_length=2, max_length=8)

    runtime_context_ref: str = Field(
        ...,
        description=(
            "Opaque reference to the RuntimeContext snapshot (event log seq "
            "or Redis key). Never embed full market state here."
        ),
    )

    context_evidence: list[LayerEnvelope] = Field(default_factory=list)
    alpha_evidence: list[LayerEnvelope] = Field(default_factory=list)
    validation_evidence: list[LayerEnvelope] = Field(default_factory=list)
    risk_evidence: list[LayerEnvelope] = Field(default_factory=list)
    portfolio_evidence: list[LayerEnvelope] = Field(default_factory=list)
    economics_evidence: list[LayerEnvelope] = Field(default_factory=list)
    meta_evidence: list[LayerEnvelope] = Field(default_factory=list)

    created_at: datetime

    @field_validator(
        "context_evidence",
        "alpha_evidence",
        "validation_evidence",
        "risk_evidence",
        "portfolio_evidence",
        "economics_evidence",
        "meta_evidence",
    )
    @classmethod
    def _reject_post_authority_plane(cls, v: list[LayerEnvelope]) -> list[LayerEnvelope]:
        """V11 / post_authority_veto must never appear in pre-L12 bundle."""
        for env in v:
            if env.plane == "post_authority_veto":
                raise ValueError(
                    f"Envelope with plane=post_authority_veto ({env.layer_id}) "
                    "must not be included in DecisionBundle; it runs AFTER L12."
                )
        return v

    # ── convenience accessors ────────────────────────────────────────────────

    def all_envelopes(self) -> list[LayerEnvelope]:
        return [
            *self.context_evidence,
            *self.alpha_evidence,
            *self.validation_evidence,
            *self.risk_evidence,
            *self.portfolio_evidence,
            *self.economics_evidence,
            *self.meta_evidence,
        ]

    def hard_blockers(self) -> list[str]:
        """All blocker codes coming from non-advisory planes.

        Meta evidence (L13/L15) is advisory and excluded.
        """
        advisory = {"meta"}
        out: list[str] = []
        seen: set[str] = set()
        for env in self.all_envelopes():
            if env.plane in advisory:
                continue
            if not env.is_blocking():
                continue
            for code in env.blockers:
                if code not in seen:
                    seen.add(code)
                    out.append(code)
        return out

    def has_hard_failure(self) -> bool:
        return bool(self.hard_blockers())

    def summary(self) -> dict[str, Any]:
        """Compact summary suitable for event sourcing / journal."""
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "runtime_context_ref": self.runtime_context_ref,
            "created_at": self.created_at.isoformat(),
            "schema_version": self.schema_version,
            "counts": {
                "context": len(self.context_evidence),
                "alpha": len(self.alpha_evidence),
                "validation": len(self.validation_evidence),
                "risk": len(self.risk_evidence),
                "portfolio": len(self.portfolio_evidence),
                "economics": len(self.economics_evidence),
                "meta": len(self.meta_evidence),
            },
            "hard_blockers": self.hard_blockers(),
        }


__all__ = ["SCHEMA_VERSION", "DecisionBundle"]
