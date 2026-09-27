"""Thin G4 broker/cost adaptation contract for StructuralGeometryV31 — owner GO 2026-09-27, source/test only.

Pipeline (owner, 2026-09-27): StructuralGeometryV31 → broker/cost adaptation → executable entry domain → net RR →
existing risk engine (``risk.strategy_5scr_risk_adapter_v31.size_parent_v31``) → B5 volume / NO_SUBMIT downstream.

This step never sizes a lot, never authorizes a submit, never moves the SL or TP1, never expands the box and never
selects another target (A4-07, Q-A4-1). Broker facts come from explicit measurements; costs come from the explicit,
versioned ``NetCostSnapshotV31``. There is no hidden spread multiple, minimum-distance floor, commission or slippage default.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from math import gcd
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_net_geometry_v31 import NetGeometryRequestV31, Price

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"
_Digest = Annotated[str, Field(pattern=_DIGEST)]

# SSOT v3.1 §17.3 `minimum_net_rr: 1.5` — the existing canonical gate (A4-03), not a G4 parameter.
MINIMUM_NET_RR_V31 = Decimal("1.5")

BrokerAdaptationStatus = Literal[
    "ELIGIBLE_FOR_RISK_ENGINE",
    "NO_EXECUTABLE_ENTRY",
    "NET_RR_BELOW_MINIMUM",
    "BROKER_PRICE_OFF_TICK_GRID",
    "BROKER_MEASUREMENT_INVALID",
    "COST_EVIDENCE_INVALID",
    "COST_SPREAD_UNDERSTATED",
    "BROKER_ADAPTATION_POLICY_INVALID",
]
BROKER_ADAPTATION_STATUSES_V31: tuple[str, ...] = (
    "ELIGIBLE_FOR_RISK_ENGINE",
    "NO_EXECUTABLE_ENTRY",
    "NET_RR_BELOW_MINIMUM",
    "BROKER_PRICE_OFF_TICK_GRID",
    "BROKER_MEASUREMENT_INVALID",
    "COST_EVIDENCE_INVALID",
    "COST_SPREAD_UNDERSTATED",
    "BROKER_ADAPTATION_POLICY_INVALID",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class BrokerQuoteV31(_Strict):
    """One measured bid/ask for the broker symbol. Freshness is judged against the explicit policy age."""

    canonical_symbol: str = Field(pattern=_SYMBOL)
    broker_symbol: str = Field(min_length=1, max_length=64)
    bid: Price
    ask: Price
    observed_at: datetime
    evidence_hash: _Digest

    @model_validator(mode="after")
    def _ordered(self) -> BrokerQuoteV31:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("QUOTE_CLOCK_NOT_AWARE")
        if self.ask < self.bid:
            raise ValueError("QUOTE_ASK_BELOW_BID")
        return self


class BrokerAdaptationPolicyV31(_Strict):
    """Explicit, versioned adaptation policy. Every value is supplied; none has a code default."""

    profile: Literal["TEST_ONLY"]
    policy_id: str = Field(min_length=3, max_length=120)
    policy_version: str = Field(min_length=1, max_length=40)
    policy_hash: _Digest
    instrument_class: Literal["FX", "METAL", "OTHER"]
    max_quote_age_seconds: int = Field(gt=0, le=3600, strict=True)
    minimum_net_rr: Decimal

    @model_validator(mode="after")
    def _canonical_gate(self) -> BrokerAdaptationPolicyV31:
        if self.minimum_net_rr != MINIMUM_NET_RR_V31:
            raise ValueError("MINIMUM_NET_RR_IS_THE_CANONICAL_1_5")
        return self


class ExactRatioV31(_Strict):
    numerator: int
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def _reduced(self) -> ExactRatioV31:
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("RATIO_NOT_REDUCED")
        return self

    @classmethod
    def of(cls, value: Fraction) -> ExactRatioV31:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class BrokerAdaptationV31(_Strict):
    """Executable domain and net RR for one geometry revision. Gross RR stays strategy truth; net RR is
    downstream feasibility truth; the two are never merged."""

    material_geometry_hash: _Digest
    canonical_symbol: str = Field(pattern=_SYMBOL)
    broker_symbol: str = Field(min_length=1, max_length=64)
    direction: Literal["BUY", "SELL"]
    structural_sl: Price
    tp1: Price
    strategy_domain_low: Price
    strategy_domain_high: Price
    executable_domain_low: Price
    executable_domain_high: Price
    worst_case_executable_entry: Price
    measured_spread: Decimal = Field(ge=0)
    gross_rr: ExactRatioV31
    net_rr: ExactRatioV31
    minimum_net_rr: Decimal
    policy_id: str
    policy_version: str
    policy_hash: _Digest
    quote_evidence_hash: _Digest
    cost_source_hash: _Digest
    capability_digest: _Digest
    risk_engine_request: NetGeometryRequestV31
    volume_decided: Literal[False] = False
    submit_authorized: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> BrokerAdaptationV31:
        if (
            not self.strategy_domain_low
            <= self.executable_domain_low
            <= self.executable_domain_high
            <= (self.strategy_domain_high)
        ):
            raise ValueError("EXECUTABLE_DOMAIN_OUTSIDE_STRATEGY_DOMAIN")
        buy = self.direction == "BUY"
        if self.worst_case_executable_entry != (self.executable_domain_high if buy else self.executable_domain_low):
            raise ValueError("NET_RR_NOT_AT_THE_WORST_CASE_EXECUTABLE_ENTRY")
        if buy and not self.structural_sl < self.executable_domain_low <= self.executable_domain_high < self.tp1:
            raise ValueError("EXECUTABLE_DOMAIN_NOT_INSIDE_SL_TP1")
        if not buy and not self.tp1 < self.executable_domain_low <= self.executable_domain_high < self.structural_sl:
            raise ValueError("EXECUTABLE_DOMAIN_NOT_INSIDE_SL_TP1")
        if self.net_rr.as_fraction() < Fraction(self.minimum_net_rr) or self.minimum_net_rr != MINIMUM_NET_RR_V31:
            raise ValueError("NET_RR_BELOW_MINIMUM")
        request = self.risk_engine_request
        if (request.stop_price, request.target_price) != (self.structural_sl, self.tp1):
            raise ValueError("RISK_ENGINE_REQUEST_MOVED_SL_OR_TP1")
        if (request.broker_interval.low, request.broker_interval.high) != (
            self.executable_domain_low,
            self.executable_domain_high,
        ):
            raise ValueError("RISK_ENGINE_REQUEST_NOT_BOUND_TO_THE_EXECUTABLE_DOMAIN")
        return self


class BrokerAdaptationDecisionV31(_Strict):
    status: BrokerAdaptationStatus
    reason: str = Field(min_length=3, max_length=120)
    adaptation: BrokerAdaptationV31 | None
    submit_authorized: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> BrokerAdaptationDecisionV31:
        if (self.status == "ELIGIBLE_FOR_RISK_ENGINE") != (self.adaptation is not None):
            raise ValueError("ADAPTATION_PRESENT_IFF_ELIGIBLE")
        return self


__all__ = [
    "BROKER_ADAPTATION_STATUSES_V31",
    "MINIMUM_NET_RR_V31",
    "BrokerAdaptationDecisionV31",
    "BrokerAdaptationPolicyV31",
    "BrokerAdaptationStatus",
    "BrokerAdaptationV31",
    "BrokerQuoteV31",
    "ExactRatioV31",
]
