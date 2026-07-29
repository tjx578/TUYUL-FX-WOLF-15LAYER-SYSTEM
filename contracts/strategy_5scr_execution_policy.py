"""Versioned execution policy for the Strategy 5S-CR target-first solver.

The solver is target-first: it locates the nearest legal structural TP1 *before*
sizing risk.  The floors that decision depends on are strategy rules, not
implementation details, so they live here as versioned objects a replay manifest
can pin -- never as a bare module constant that silently re-decides every
caller's history.

Two policies coexist on purpose:

``FX_MIN_TARGET_10P_V1``
    Canonical for Hybrid V3 and every new tradeplan.  A structural target below
    10 pips is ``NO_TRADE``.

``FX_LEGACY_6P_V1``
    Kept so decisions recorded under the 6-pip rule stay reproducible on replay.
    Not a production default.

Selecting a policy changes which candidates exist, so it changes trade count,
win rate and net R.  That is a deliberate strategy-rule change, not a
regression; comparisons across policies must always name the policy.

Nothing here authorizes execution.  A policy only decides whether a tradeplan
*candidate* may be built; the candidate stays ``valid_for_execution=False``
until the risk plane commits a durable reservation.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionPolicyId = Literal["FX_MIN_TARGET_10P_V1", "FX_LEGACY_6P_V1"]
TargetFloorStatus = Literal["PASS", "BELOW_STRUCTURAL_FLOOR", "BELOW_COST_FLOOR"]

EXECUTION_POLICY_ENV = "STRATEGY_5SCR_EXECUTION_POLICY_ID"

#: Raised as a build reason when no policy was supplied and none resolved.
EXECUTION_POLICY_MISSING_REASON = "STRATEGY_5SCR_EXECUTION_POLICY_MISSING"


class TargetFloorAssessment(BaseModel):
    """Why a structural target passed or failed the floor, in pip terms."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_policy_id: ExecutionPolicyId
    execution_policy_version: int
    target_distance_pips: float = Field(..., ge=0)
    minimum_target_pips: float = Field(..., ge=0)
    broker_cost_floor_pips: float = Field(..., ge=0)
    required_target_pips: float = Field(..., ge=0)
    target_floor_status: TargetFloorStatus

    @property
    def passed(self) -> bool:
        return self.target_floor_status == "PASS"


class ExecutionPolicy(BaseModel):
    """Frozen structural-target policy applied by the tradeplan solver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: ExecutionPolicyId
    policy_version: int = Field(default=1, ge=1)
    minimum_fx_target_pips: float = Field(..., gt=0)
    minimum_rr: float = Field(default=1.5, ge=1.5)
    spread_multiplier: float = Field(default=5.0, ge=0)
    #: Metals are quoted in price, not pips, so they never inherit the FX floor.
    minimum_metal_target_price: float = Field(default=5.0, gt=0)
    close_policy: Literal["FULL_CLOSE_AT_TP1"] = "FULL_CLOSE_AT_TP1"
    target_source_required: Literal["STRUCTURAL"] = "STRUCTURAL"

    @staticmethod
    def is_metal(symbol: str) -> bool:
        return symbol.upper().startswith(("XAU", "XAG"))

    def execution_floor(self, symbol: str, pip_size: float, spread_price: float) -> float:
        """Minimum acceptable target distance, in price terms.

        Both the structural floor and the broker-cost floor apply: a
        structurally adequate target is still refused when spread would eat it.
        """
        cost_floor = self.spread_multiplier * spread_price
        if self.is_metal(symbol):
            return max(self.minimum_metal_target_price, cost_floor)
        return max(self.minimum_fx_target_pips * pip_size, cost_floor)

    def assess_target(
        self,
        symbol: str,
        *,
        target_distance_price: float,
        pip_size: float,
        spread_price: float,
    ) -> TargetFloorAssessment:
        """Explain the floor decision in pips so the tradeplan can record it."""
        if pip_size <= 0:
            raise ValueError("pip_size must be positive")

        metal = self.is_metal(symbol)
        # For metals the "pip" unit is the price unit itself, keeping the
        # recorded numbers meaningful rather than silently FX-scaled.
        unit = 1.0 if metal else pip_size
        target_pips = target_distance_price / unit
        minimum_pips = (self.minimum_metal_target_price if metal else self.minimum_fx_target_pips * pip_size) / unit
        cost_floor_pips = (self.spread_multiplier * spread_price) / unit
        required_pips = max(minimum_pips, cost_floor_pips)

        if target_pips + 1e-9 >= required_pips:
            status: TargetFloorStatus = "PASS"
        elif minimum_pips >= cost_floor_pips:
            status = "BELOW_STRUCTURAL_FLOOR"
        else:
            status = "BELOW_COST_FLOOR"

        return TargetFloorAssessment(
            execution_policy_id=self.policy_id,
            execution_policy_version=self.policy_version,
            target_distance_pips=target_pips,
            minimum_target_pips=minimum_pips,
            broker_cost_floor_pips=cost_floor_pips,
            required_target_pips=required_pips,
            target_floor_status=status,
        )


FX_MIN_TARGET_10P_V1 = ExecutionPolicy(
    policy_id="FX_MIN_TARGET_10P_V1",
    minimum_fx_target_pips=10.0,
)

FX_LEGACY_6P_V1 = ExecutionPolicy(
    policy_id="FX_LEGACY_6P_V1",
    minimum_fx_target_pips=6.0,
)

EXECUTION_POLICIES: dict[str, ExecutionPolicy] = {
    FX_MIN_TARGET_10P_V1.policy_id: FX_MIN_TARGET_10P_V1,
    FX_LEGACY_6P_V1.policy_id: FX_LEGACY_6P_V1,
}

#: Explicit policy for the Hybrid V3 entrypoint.
HYBRID_V3_EXECUTION_POLICY = FX_MIN_TARGET_10P_V1
#: Explicit policy for legacy replay/compatibility wrappers only.
LEGACY_REPLAY_EXECUTION_POLICY = FX_LEGACY_6P_V1


def resolve_execution_policy(policy_id: str | None = None) -> ExecutionPolicy | None:
    """Resolve a policy from an explicit id, then env.  Never guesses.

    Returns ``None`` when nothing resolves so the caller can fail closed with
    ``STRATEGY_5SCR_EXECUTION_POLICY_MISSING`` rather than inherit a hidden
    default.  Numeric overrides are deliberately unsupported: changing a floor
    means minting a new policy id, not mutating an existing one.
    """
    resolved = (policy_id or os.getenv(EXECUTION_POLICY_ENV) or "").strip().upper()
    if not resolved:
        return None
    return EXECUTION_POLICIES.get(resolved)


__all__ = [
    "EXECUTION_POLICIES",
    "EXECUTION_POLICY_ENV",
    "EXECUTION_POLICY_MISSING_REASON",
    "FX_LEGACY_6P_V1",
    "FX_MIN_TARGET_10P_V1",
    "HYBRID_V3_EXECUTION_POLICY",
    "LEGACY_REPLAY_EXECUTION_POLICY",
    "ExecutionPolicy",
    "ExecutionPolicyId",
    "TargetFloorAssessment",
    "TargetFloorStatus",
    "resolve_execution_policy",
]
